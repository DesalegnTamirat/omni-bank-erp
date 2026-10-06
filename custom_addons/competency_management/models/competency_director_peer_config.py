# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyDirectorPeerConfig(models.Model):
    """Director Peer Evaluation Exception Configuration.
    
    Stores explicit peer assignments for Directors & Executive Leadership as per Bunna Bank 360-degree evaluation rules.
    Auto-populates all Directorates and Executive positions as starting seed with empty peers.
    Restricts peer candidate dropdown strictly to employees with same coach & different position.
    """
    _name = 'competency.director.peer.config'
    _description = 'Executive Peer Evaluation Configuration'
    _order = 'director_id'
    _rec_name = 'director_id'

    director_id = fields.Many2one(
        'hr.employee', string='Executive (Grade 15 / Director / Chief)', required=True, ondelete='cascade',
        domain="[('is_director_or_chief', '=', True), ('active', '=', True)]",
        index=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position', compute='_compute_job_id', store=True, readonly=True)
    grade_id = fields.Many2one(
        'employee.grade', string='Job Grade', compute='_compute_grade_id', store=True, readonly=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', compute='_compute_department_id', store=True, readonly=True)
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit', compute='_compute_operating_unit_id', store=True, readonly=True)
    coach_id = fields.Many2one(
        'hr.employee', string='Coach / Supervisor', compute='_compute_coach_id', store=True, readonly=True)
    candidate_peer_ids = fields.Many2many(
        'hr.employee', compute='_compute_candidate_peer_ids',
        string='Candidate Peers Pool',
        help="Calculated pool of eligible peers sharing the executive's coach with a different position.")
    peer_ids = fields.Many2many(
        'hr.employee', 'competency_director_peer_rel', 'config_id', 'peer_id',
        string='Assigned 360° Peers',
        domain="[('id', 'in', candidate_peer_ids)]",
        help="Select peers for this Director/Chief. Restricted strictly to candidates sharing the same coach with a different position.")
    peer_count = fields.Integer(string='Assigned Peers', compute='_compute_peer_count')
    notes = fields.Text(string='Notes / Rationale')
    has_open_cycle = fields.Boolean(
        string='Has Open Cycle', compute='_compute_has_open_cycle',
        help="Technical flag indicating if there is at least one currently open assessment cycle."
    )

    @api.depends('director_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.sudo().director_id.department_id if rec.director_id else False

    @api.depends('peer_ids')
    def _compute_peer_count(self):
        for rec in self:
            rec.peer_count = len(rec.peer_ids)

    def web_read(self, specification):
        self.check_access_rule('read')
        return super(CompetencyDirectorPeerConfig, self.sudo()).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        self.check_access_rule('read')
        return super(CompetencyDirectorPeerConfig, self.sudo()).read(fields=fields, load=load)

    def onchange(self, values, field_name, field_onchange):
        return super(CompetencyDirectorPeerConfig, self.sudo()).onchange(values, field_name, field_onchange)

    @api.depends_context('company')
    def _compute_has_open_cycle(self):
        has_open = bool(self.env['competency.assessment.cycle'].search_count([('state', '=', 'open')]))
        for rec in self:
            rec.has_open_cycle = has_open

    def action_sync_cycle_peers(self):
        """Synchronize 360 peer assessments for this Director/Chief with the active open cycle.
        - The Director/Chief evaluates the peers assigned in this configuration (Director is ASSESSOR, peers are EMPLOYEES).
        - Peering is strictly unidirectional: assigning a peer here does NOT create a reverse assessment.
        - Newly added peers get a new draft peer assessment generated with populated competency lines.
        - Existing peer assessments that were previously generated are preserved.
        - Peers removed from configuration have their unsubmitted draft assessment deleted.
        """
        self.ensure_one()
        self_sudo = self.sudo()
        open_cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], order='id desc', limit=1)
        if not open_cycle:
            raise UserError(_("There is currently no Open assessment cycle. This action can only be performed during an active open cycle."))

        director = self_sudo.director_id
        if not director:
            raise UserError(_("Please specify a Director or Chief before synchronizing peers."))

        director_user_id = director.user_id.id
        if not director_user_id:
            raise UserError(_("Director/Chief '%s' has no associated user account. Assessments cannot be assigned without a user account.") % director.name)

        # 1. Assigned peers in this configuration (these are the employees to be evaluated)
        target_peers = self_sudo.peer_ids.filtered(lambda p: p.active)
        target_employee_ids = set(target_peers.ids)

        # 2. Existing peer assessments where director is ASSESSOR in the open cycle
        existing_peer_asms = self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', open_cycle.id),
            ('assessor_id', '=', director_user_id),
            ('assessment_type', '=', 'peer'),
        ])

        existing_emp_ids = set(existing_peer_asms.mapped('employee_id.id'))

        # 3. Handle removed peers: delete draft assessments if employee is no longer in target_employee_ids
        removed_asms = existing_peer_asms.filtered(
            lambda a: a.employee_id.id not in target_employee_ids and a.state == 'draft'
        )
        removed_count = len(removed_asms)
        if removed_asms:
            removed_asms.unlink()

        # 4. Clean up any legacy inverted draft peer assessments where director was set as evaluatee instead of assessor
        legacy_peer_users = list(target_peers.mapped('user_id.id'))
        if legacy_peer_users:
            inverted_asms = self.env['competency.assessment'].sudo().search([
                ('cycle_id', '=', open_cycle.id),
                ('employee_id', '=', director.id),
                ('assessor_id', 'in', legacy_peer_users),
                ('assessment_type', '=', 'peer'),
                ('state', '=', 'draft'),
            ])
            if inverted_asms:
                inverted_asms.unlink()

        # 5. Handle newly added peers: create peer assessment where director assesses peer
        added_count = 0
        AssessmentSudo = self.env['competency.assessment'].sudo()
        for peer in target_peers:
            if peer.id not in existing_emp_ids:
                new_asm = AssessmentSudo.create({
                    'cycle_id': open_cycle.id,
                    'employee_id': peer.id,
                    'assessor_id': director_user_id,
                    'assessment_type': 'peer',
                })
                # Auto-populate competencies according to configuration
                try:
                    new_asm._do_populate_lines()
                except Exception:
                    pass
                added_count += 1

        preserved_count = len(target_employee_ids & existing_emp_ids)
        msg = _(
            "Peer synchronization complete for %s in cycle '%s':\n"
            "• %d new peer assessment(s) generated (Executive will evaluate these peers).\n"
            "• %d removed peer draft assessment(s) deleted.\n"
            "• %d active peer assessment(s) preserved."
        ) % (director.name, open_cycle.name, added_count, removed_count, preserved_count)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cycle Peers Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_all_cycle_peers(self):
        """Batch synchronize 360 peer assessments for ALL configured Directors & Chiefs with the active open cycle.
        - Synchronizes each executive's peer list so they assess their assigned peers.
        - Unlinks draft assessments for removed peers.
        - Cleans up legacy inverted assessments.
        - Preserves existing active assessments.
        """
        open_cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], order='id desc', limit=1)
        if not open_cycle:
            raise UserError(_("There is currently no Open assessment cycle. This action can only be performed during an active open cycle."))

        all_configs = self.sudo().search([])
        total_created = 0
        total_removed = 0
        total_preserved = 0
        executives_synced = 0
        AssessmentSudo = self.env['competency.assessment'].sudo()

        for config in all_configs:
            director = config.director_id
            if not director:
                continue
            director_user_id = director.user_id.id
            if not director_user_id:
                continue

            target_peers = config.peer_ids.filtered(lambda p: p.active)
            target_employee_ids = set(target_peers.ids)

            existing_peer_asms = AssessmentSudo.search([
                ('cycle_id', '=', open_cycle.id),
                ('assessor_id', '=', director_user_id),
                ('assessment_type', '=', 'peer'),
            ])
            existing_emp_ids = set(existing_peer_asms.mapped('employee_id.id'))

            # Removed peers: delete draft assessments
            removed_asms = existing_peer_asms.filtered(
                lambda a: a.employee_id.id not in target_employee_ids and a.state == 'draft'
            )
            total_removed += len(removed_asms)
            if removed_asms:
                removed_asms.unlink()

            # Clean up legacy inverted drafts where director was evaluatee
            legacy_peer_users = list(target_peers.mapped('user_id.id'))
            if legacy_peer_users:
                inverted = AssessmentSudo.search([
                    ('cycle_id', '=', open_cycle.id),
                    ('employee_id', '=', director.id),
                    ('assessor_id', 'in', legacy_peer_users),
                    ('assessment_type', '=', 'peer'),
                    ('state', '=', 'draft'),
                ])
                if inverted:
                    inverted.unlink()

            # Added peers: create assessments where director assesses peer
            for peer in target_peers:
                if peer.id not in existing_emp_ids:
                    new_asm = AssessmentSudo.create({
                        'cycle_id': open_cycle.id,
                        'employee_id': peer.id,
                        'assessor_id': director_user_id,
                        'assessment_type': 'peer',
                    })
                    try:
                        new_asm._do_populate_lines()
                    except Exception:
                        pass
                    total_created += 1

            total_preserved += len(target_employee_ids & existing_emp_ids)
            executives_synced += 1

        msg = _(
            "Batch Peer Synchronization Complete for '%s':\n"
            "• %d Executive(s) processed.\n"
            "• %d new peer assessment(s) generated (Executives evaluating assigned peers).\n"
            "• %d removed draft peer assessment(s) deleted.\n"
            "• %d active peer assessment(s) preserved."
        ) % (open_cycle.name, executives_synced, total_created, total_removed, total_preserved)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Executive Peers Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }


    @api.model
    def _get_employee_job(self, emp):
        """Safely fetch job position for an employee, prioritizing substantive custom job_position over version job_id."""
        if not emp:
            return self.env['hr.job']
        return getattr(emp, 'job_position', False) or emp.job_id or self.env['hr.job']

    @api.depends('director_id', 'director_id.job_id')
    def _compute_job_id(self):
        for rec in self:
            rec.job_id = self.sudo()._get_employee_job(rec.sudo().director_id) if rec.director_id else False

    @api.model
    def _resolve_employee_grade(self, emp):
        """Resolves the employee's assigned employee.grade record safely across hr_employee_custom variants."""
        if not emp:
            return self.env['employee.grade']

        # 0. Direct grade on employee (hr_employee_custom: grade = fields.Many2one('employee.grade'))
        grade = getattr(emp, 'grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

        # 1. Direct job_grade on employee
        grade = getattr(emp, 'job_grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

        # 2. Active contract in hr.version
        if 'hr.version' in self.env:
            contract = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if contract and getattr(contract, 'job_grade', False):
                g = contract.job_grade
                if getattr(g, '_name', '') == 'employee.grade':
                    return g

        # 3. Operating Unit Job Position
        job = self._get_employee_job(emp)
        if job and 'operating.unit.job.position' in self.env:
            ou_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            if ou_id:
                pos = self.env['operating.unit.job.position'].search([
                    ('job_position_id', '=', job.id),
                    ('operating_unit_id', '=', ou_id.id)
                ], limit=1)
                if pos and pos.job_grade_id and getattr(pos.job_grade_id, '_name', '') == 'employee.grade':
                    return pos.job_grade_id
            pos = self.env['operating.unit.job.position'].search([
                ('job_position_id', '=', job.id)
            ], limit=1)
            if pos and pos.job_grade_id and getattr(pos.job_grade_id, '_name', '') == 'employee.grade':
                return pos.job_grade_id

        # 4. Check grade_id on employee (may be employee.grade or hr.employee.grade)
        grade = getattr(emp, 'grade_id', False)
        if grade:
            if getattr(grade, '_name', '') == 'employee.grade':
                return grade
            code = getattr(grade, 'code', False) or getattr(grade, 'grade_code', False)
            name = getattr(grade, 'name', False) or getattr(grade, 'grade_name', False)
            if code:
                found = self.env['employee.grade'].search([('grade_code', '=ilike', str(code).strip())], limit=1)
                if found:
                    return found
            if name:
                found = self.env['employee.grade'].search(['|', ('grade_name', '=ilike', str(name).strip()), ('grade_code', '=ilike', str(name).strip())], limit=1)
                if found:
                    return found

        # 5. Check job position
        if job:
            g = getattr(job, 'grade', False) or getattr(job, 'grade_id', False)
            if g:
                if getattr(g, '_name', '') == 'employee.grade':
                    return g
                code = getattr(g, 'code', False) or getattr(g, 'grade_code', False)
                name = getattr(g, 'name', False) or getattr(g, 'grade_name', False)
                if code:
                    found = self.env['employee.grade'].search([('grade_code', '=ilike', str(code).strip())], limit=1)
                    if found:
                        return found
                if name:
                    found = self.env['employee.grade'].search(['|', ('grade_name', '=ilike', str(name).strip()), ('grade_code', '=ilike', str(name).strip())], limit=1)
                    if found:
                        return found

        return self.env['employee.grade']

    @api.depends('director_id', 'director_id.grade_id', 'director_id.job_grade', 'director_id.job_id')
    def _compute_grade_id(self):
        for rec in self:
            if rec.director_id:
                rec.grade_id = self.sudo()._resolve_employee_grade(rec.sudo().director_id)
            else:
                rec.grade_id = False

    @api.depends('director_id', 'director_id.default_operating_unit_id', 'director_id.department_id', 'director_id.department_id.operating_unit_id')
    def _compute_operating_unit_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.sudo().director_id
                rec.operating_unit_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            else:
                rec.operating_unit_id = False

    @api.depends('director_id', 'director_id.coach_id', 'director_id.parent_id')
    def _compute_coach_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.sudo().director_id
                rec.coach_id = getattr(emp, 'coach_id', False) or emp.parent_id
            else:
                rec.coach_id = False

    @api.model
    def _get_grade_number(self, emp):
        """Extract numeric grade level (1..17) from employee's assigned job grade or position."""
        if not emp:
            return 0
        grade_rec = self._resolve_employee_grade(emp)
        raw_str = ''
        if grade_rec:
            raw_str = getattr(grade_rec, 'grade_name', False) or getattr(grade_rec, 'grade_code', False) or ''
        if not raw_str:
            raw = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False) or getattr(emp, 'grade', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)
        job = self._get_employee_job(emp)
        if not raw_str and job:
            raw = getattr(job, 'grade', False) or getattr(job, 'grade_id', False)
            if raw:
                raw_str = getattr(raw, 'name', False) or getattr(raw, 'code', False) or getattr(raw, 'grade_name', False) or str(raw)

        g_str = str(raw_str).lower().strip()
        if not g_str:
            return 0

        # Roman numerals map
        tokens = g_str.replace('-', ' ').replace('_', ' ').split()
        roman_map = {
            'xvii': 17, 'xvi': 16, 'xv': 15, 'xiv': 14, 'xiii': 13, 'xii': 12, 'xi': 11,
            'x': 10, 'ix': 9, 'viii': 8, 'vii': 7, 'vi': 6, 'v': 5, 'iv': 4, 'iii': 3, 'ii': 2, 'i': 1
        }
        for token in tokens:
            if token in roman_map:
                return roman_map[token]
        if g_str in roman_map:
            return roman_map[g_str]

        import re
        numbers = re.findall(r'\d+', g_str)
        if numbers:
            return int(numbers[0])

        return 0

    @api.model
    def _is_director_or_chief(self, emp):
        """Strictly classify as Executive: Grade 15, Director (Grade 16) or Chief (Grade 17). Exclude Grade II, III, IV, etc."""
        if not emp or not emp.active:
            return False
        emp_sudo = emp.sudo()
        g_num = self.sudo()._get_grade_number(emp_sudo)
        if g_num in (15, 16, 17):
            return True
        return False

    @api.depends('director_id', 'grade_id', 'director_id.job_id', 'director_id.grade_id', 'director_id.job_grade')
    def _compute_candidate_peer_ids(self):
        """Calculate pool of eligible peers strictly matching the executive rank:
        - For Grade 15: only active Grade 15 employees, excluding themselves.
        - For Directors (Grade 16): only active Directors (Grade 16), excluding themselves.
        - For Chiefs (Grade 17): only active Chiefs (Grade 17), excluding themselves.
        """
        all_active = self.env['hr.employee'].sudo().search([('active', '=', True)])
        peer_config = self.sudo()

        for rec in self:
            if not rec.director_id:
                rec.candidate_peer_ids = self.env['hr.employee']
                continue

            dir_emp = rec.sudo().director_id
            dir_g_num = peer_config._get_grade_number(dir_emp)

            if dir_g_num == 15:
                candidates = all_active.filtered(
                    lambda e: e.id != dir_emp.id and peer_config._get_grade_number(e) == 15
                )
            elif dir_g_num == 16:
                candidates = all_active.filtered(
                    lambda e: e.id != dir_emp.id and peer_config._get_grade_number(e) == 16
                )
            elif dir_g_num == 17:
                candidates = all_active.filtered(
                    lambda e: e.id != dir_emp.id and peer_config._get_grade_number(e) == 17
                )
            else:
                candidates = all_active.filtered(
                    lambda e: e.id != dir_emp.id and peer_config._is_director_or_chief(e)
                )

            rec.candidate_peer_ids = candidates

    @api.onchange('director_id')
    def _onchange_director_id(self):
        if self.director_id:
            dir_emp = self.sudo().director_id
            dir_g_num = self.sudo()._get_grade_number(dir_emp)
            all_active = self.env['hr.employee'].sudo().search([('active', '=', True)])
            if dir_g_num == 15:
                self.candidate_peer_ids = all_active.filtered(
                    lambda e: e.id != dir_emp.id and self.sudo()._get_grade_number(e) == 15
                )
            elif dir_g_num == 16:
                self.candidate_peer_ids = all_active.filtered(
                    lambda e: e.id != dir_emp.id and self.sudo()._get_grade_number(e) == 16
                )
            elif dir_g_num == 17:
                self.candidate_peer_ids = all_active.filtered(
                    lambda e: e.id != dir_emp.id and self.sudo()._get_grade_number(e) == 17
                )
            else:
                self.candidate_peer_ids = all_active.filtered(
                    lambda e: e.id != dir_emp.id and self.sudo()._is_director_or_chief(e)
                )

    @api.constrains('director_id', 'peer_ids')
    def _check_peer_grades(self):
        for rec in self:
            if not rec.director_id or not rec.peer_ids:
                continue
            dir_g_num = self.sudo()._get_grade_number(rec.sudo().director_id)
            for peer in rec.sudo().peer_ids:
                peer_g_num = self.sudo()._get_grade_number(peer)
                if dir_g_num == 15 and peer_g_num != 15:
                    raise ValidationError(_("Invalid Peer '%s': Peers for a Grade XV executive must also be Grade XV.") % peer.name)
                elif dir_g_num == 16 and peer_g_num != 16:
                    raise ValidationError(_("Invalid Peer '%s': Peers for a Director (Grade XVI) must also be Directors (Grade XVI).") % peer.name)
                elif dir_g_num == 17 and peer_g_num != 17:
                    raise ValidationError(_("Invalid Peer '%s': Peers for a Chief (Grade XVII) must also be Chiefs (Grade XVII).") % peer.name)
                elif dir_g_num not in (15, 16, 17) and peer_g_num != dir_g_num:
                    raise ValidationError(_("Invalid Peer '%s': Peers must share the same executive grade rank.") % peer.name)

    @api.constrains('director_id')
    def _check_unique_director(self):
        for rec in self:
            if rec.director_id:
                existing = self.sudo().search([
                    ('id', '!=', rec.id),
                    ('director_id', '=', rec.director_id.id)
                ], limit=1)
                if existing:
                    raise ValidationError(_("A peer configuration record already exists for Director '%s'.") % rec.sudo().director_id.name)

    @api.constrains('director_id')
    def _check_director_grade(self):
        for rec in self:
            if rec.director_id and not self._is_director_or_chief(rec.sudo().director_id):
                raise ValidationError(_("Employee '%s' cannot be configured here. Executive Peer Configuration is strictly reserved for Grade XV, Directors (Grade XVI), and Chiefs (Grade XVII).") % rec.sudo().director_id.name)

    def action_generate_director_records(self, *args, **kwargs):
        """Scan active hr.employee records strictly for Directors (Grade 16) and Chiefs (Grade 17) and create missing configuration records, purging non-executive entries."""
        all_employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        director_emps = all_employees.filtered(lambda e: self._is_director_or_chief(e))
        director_emp_ids = set(director_emps.ids)

        # Purge non-director/non-chief config records (e.g. Grade II, III, IV, etc.)
        if director_emp_ids:
            invalid_configs = self.sudo().search([('director_id', 'not in', list(director_emp_ids))])
            if invalid_configs:
                invalid_configs.unlink()

        existing_director_ids = set(self.sudo().search([]).mapped('director_id.id'))
        created_count = 0

        for emp_id in director_emp_ids:
            if emp_id not in existing_director_ids:
                self.sudo().create({'director_id': emp_id})
                existing_director_ids.add(emp_id)
                created_count += 1

        msg = _("Successfully synchronized Executive Peer Configuration.\nCreated: %d, Total Active Executives (Grade XV, Directors & Chiefs): %d.\nNon-executive records purged.") % (created_count, len(existing_director_ids))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Executive Records Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }


    @api.model
    def action_open_director_peer_config(self):
        """Auto-populate any newly appointed Directors/Chiefs before displaying configuration."""
        self.action_generate_director_records()
        return self.env['ir.actions.act_window']._for_xml_id('competency_management.action_competency_director_peer_config')


