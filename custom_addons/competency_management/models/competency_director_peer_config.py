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
    _description = 'Director Peer Evaluation Configuration'
    _order = 'director_id'
    _rec_name = 'director_id'

    director_id = fields.Many2one(
        'hr.employee', string='Director', required=True, ondelete='cascade',
        domain="[('is_director_or_chief', '=', True), ('active', '=', True)]",
        index=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position', compute='_compute_job_id', store=True, readonly=True)
    grade_id = fields.Many2one(
        'employee.grade', string='Job Grade', compute='_compute_grade_id', store=True, readonly=True)
    department_id = fields.Many2one(
        'hr.department', related='director_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit', compute='_compute_operating_unit_id', store=True, readonly=True)
    coach_id = fields.Many2one(
        'hr.employee', string='Coach / Supervisor', compute='_compute_coach_id', store=True, readonly=True)
    candidate_peer_ids = fields.Many2many(
        'hr.employee', compute='_compute_candidate_peer_ids',
        string='Candidate Peers Pool',
        help="Calculated pool of eligible peers sharing the director's coach with a different position.")
    peer_ids = fields.Many2many(
        'hr.employee', 'competency_director_peer_rel', 'config_id', 'peer_id',
        string='Assigned 360° Peers',
        domain="[('id', 'in', candidate_peer_ids)]",
        help="Select peers for this Director. Restricted strictly to candidates sharing the same coach with a different position.")
    notes = fields.Text(string='Notes / Rationale')
    has_open_cycle = fields.Boolean(
        string='Has Open Cycle', compute='_compute_has_open_cycle',
        help="Technical flag indicating if there is at least one currently open assessment cycle."
    )

    def _compute_has_open_cycle(self):
        has_open = bool(self.env['competency.assessment.cycle'].search_count([('state', '=', 'open')]))
        for rec in self:
            rec.has_open_cycle = has_open

    def action_sync_cycle_peers(self):
        """Synchronize 360 peer assessments for this Director/Chief with the active open cycle.
        - Newly added peers get a new draft peer assessment generated with populated competency lines.
        - Existing peer assessments that were previously generated are preserved.
        - Peers removed from configuration have their unsubmitted draft assessment deleted.
        """
        self.ensure_one()
        open_cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], order='id desc', limit=1)
        if not open_cycle:
            raise UserError(_("There is currently no Open assessment cycle. This action can only be performed during an active open cycle."))

        director = self.director_id
        if not director:
            raise UserError(_("Please specify a Director or Chief before synchronizing peers."))

        # 1. Assigned peers in this configuration
        target_peers = self.peer_ids.filtered(lambda p: p.active and p.user_id)
        target_user_ids = set(target_peers.mapped('user_id.id'))

        # 2. Existing peer assessments for this director in the open cycle
        existing_peer_asms = self.env['competency.assessment'].search([
            ('cycle_id', '=', open_cycle.id),
            ('employee_id', '=', director.id),
            ('assessment_type', '=', 'peer'),
        ])

        existing_user_ids = set(existing_peer_asms.mapped('assessor_id.id'))

        # 3. Handle removed peers: delete draft assessments if assessor is no longer in target_user_ids
        removed_asms = existing_peer_asms.filtered(
            lambda a: a.assessor_id.id not in target_user_ids and a.state == 'draft'
        )
        removed_count = len(removed_asms)
        if removed_asms:
            removed_asms.unlink()

        # 4. Handle newly added peers: create peer assessment if assessor is in target_user_ids but not yet created
        added_count = 0
        AssessmentSudo = self.env['competency.assessment'].sudo()
        for peer in target_peers:
            if peer.user_id.id not in existing_user_ids:
                new_asm = AssessmentSudo.create({
                    'cycle_id': open_cycle.id,
                    'employee_id': director.id,
                    'assessor_id': peer.user_id.id,
                    'assessment_type': 'peer',
                })
                # Auto-populate competencies according to configuration
                try:
                    new_asm._do_populate_lines()
                except Exception:
                    pass
                added_count += 1

        preserved_count = len(target_user_ids & existing_user_ids)
        msg = _(
            "Peer synchronization complete for %s in cycle '%s':\n"
            "• %d new peer assessment(s) generated.\n"
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


    @api.model
    def _get_employee_job(self, emp):
        """Safely fetch job position for an employee, supporting both standard job_id and custom job_position."""
        if not emp:
            return self.env['hr.job']
        return emp.job_id or getattr(emp, 'job_position', self.env['hr.job'])

    @api.depends('director_id', 'director_id.job_id')
    def _compute_job_id(self):
        for rec in self:
            rec.job_id = self._get_employee_job(rec.director_id) if rec.director_id else False

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
                rec.grade_id = self._resolve_employee_grade(rec.director_id)
            else:
                rec.grade_id = False

    @api.depends('director_id', 'director_id.default_operating_unit_id', 'director_id.department_id', 'director_id.department_id.operating_unit_id')
    def _compute_operating_unit_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.director_id
                rec.operating_unit_id = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id.operating_unit_id if emp.department_id else False)
            else:
                rec.operating_unit_id = False

    @api.depends('director_id', 'director_id.coach_id', 'director_id.parent_id')
    def _compute_coach_id(self):
        for rec in self:
            if rec.director_id:
                emp = rec.director_id
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
        """Strictly classify as Director (Grade 16) or Chief (Grade 17). Exclude Grade II, III, IV, etc."""
        if not emp or not emp.active:
            return False
        g_num = self._get_grade_number(emp)
        if g_num in (16, 17):
            return True
        return False

    @api.depends('director_id', 'grade_id', 'director_id.job_id', 'director_id.grade_id', 'director_id.job_grade')
    def _compute_candidate_peer_ids(self):
        """Calculate pool of eligible peers for Directors (Grade 16) & Chiefs (Grade 17) matching the exception rule: Same Job Grade."""
        # Retrieve all active executive peers from existing configurations or active directors
        all_configs = self.search([])
        dir_pool = all_configs.mapped('director_id').filtered(lambda e: e.active)
        if not dir_pool:
            all_active = self.env['hr.employee'].search([('active', '=', True)])
            dir_pool = all_active.filtered(lambda e: self._is_director_or_chief(e))

        for rec in self:
            if not rec.director_id:
                rec.candidate_peer_ids = self.env['hr.employee']
                continue

            dir_emp = rec.director_id
            dir_g_num = self._get_grade_number(dir_emp)
            pool = dir_pool.filtered(lambda e: e.id != dir_emp.id)

            if dir_g_num in (16, 17):
                candidates = pool.filtered(lambda c: self._get_grade_number(c) == dir_g_num)
            elif rec.grade_id:
                candidates = pool.filtered(lambda c: self._resolve_employee_grade(c).id == rec.grade_id.id)
            else:
                candidates = pool

            rec.candidate_peer_ids = candidates

    @api.constrains('director_id')
    def _check_unique_director(self):
        for rec in self:
            if rec.director_id:
                existing = self.search([
                    ('id', '!=', rec.id),
                    ('director_id', '=', rec.director_id.id)
                ], limit=1)
                if existing:
                    raise ValidationError(_("A peer configuration record already exists for Director '%s'.") % rec.director_id.name)

    @api.constrains('director_id')
    def _check_director_grade(self):
        for rec in self:
            if rec.director_id and not self._is_director_or_chief(rec.director_id):
                raise ValidationError(_("Employee '%s' cannot be configured here. Director Peer Configuration is strictly reserved for Directors (Grade XVI) and Chiefs (Grade XVII).") % rec.director_id.name)

    def action_generate_director_records(self, *args, **kwargs):
        """Scan active hr.employee records strictly for Directors (Grade 16) and Chiefs (Grade 17) and create missing configuration records, purging non-executive entries."""
        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        director_emps = all_employees.filtered(lambda e: self._is_director_or_chief(e))
        director_emp_ids = set(director_emps.ids)

        # Purge non-director/non-chief config records (e.g. Grade II, III, IV, etc.)
        if director_emp_ids:
            invalid_configs = self.search([('director_id', 'not in', list(director_emp_ids))])
            if invalid_configs:
                invalid_configs.unlink()

        existing_director_ids = set(self.search([]).mapped('director_id.id'))
        created_count = 0

        for emp_id in director_emp_ids:
            if emp_id not in existing_director_ids:
                self.create({'director_id': emp_id})
                existing_director_ids.add(emp_id)
                created_count += 1

        msg = _("Successfully synchronized Director Peer Configuration.\nCreated: %d, Total Active Directors & Chiefs: %d.\nNon-executive records purged.") % (created_count, len(existing_director_ids))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Director Records Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def action_open_director_peer_config(self):
        """Auto-populate any newly appointed Directors/Chiefs before displaying configuration."""
        self.action_generate_director_records()
        return self.env.ref('competency_management.action_competency_director_peer_config').read()[0]

    def _register_hook(self):
        super()._register_hook()
        # Scan and populate when the module / server registry loads
        try:
            with self.env.cr.savepoint():
                self.sudo().action_generate_director_records()
        except Exception:
            pass


