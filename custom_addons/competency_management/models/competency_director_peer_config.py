# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError
import re


class CompetencyDirectorPeerConfig(models.Model):
    """Director, Executive & Branch Manager Peer Evaluation Configuration.
    
    Stores explicit peer assignments for Chiefs, Directors, Grade XV Executives,
    and Branch Managers as per Bunna Bank 360-degree evaluation hierarchy:
    - CEO: Configures peers for Chiefs (candidate pool: all active Chiefs bank-wide)
    - Chief: Configures peers for Directors under them (candidate pool: all active Directors bank-wide)
             and Grade 15s under them (candidate pool: all active Grade 15s bank-wide)
    - Director: Configures peers for Branch Managers under them (candidate pool: only BMs under same Director)
                and Grade 15s under them (candidate pool: all active Grade 15s bank-wide)
    - Admin / Officer: Full access to all tiers
    """
    _name = 'competency.director.peer.config'
    _description = 'Executive & Branch Manager Peer Evaluation Configuration'
    _order = 'director_id'
    _rec_name = 'director_id'

    director_id = fields.Many2one(
        'hr.employee', string='Employee (Chief / Director / Executive / Branch Manager)',
        required=True, ondelete='cascade',
        domain="[('active', '=', True)]",
        index=True)
    config_tier = fields.Selection([
        ('chief', 'Chief (Grade XVII)'),
        ('director', 'Director (Grade XVI)'),
        ('executive_15', 'Executive (Grade XV)'),
        ('branch_manager', 'Branch Manager'),
    ], string='Configuration Tier', compute='_compute_config_tier', store=True, index=True)
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
        'hr.employee',
        compute='_compute_candidate_peer_ids',
        string='Candidate Peers Pool',
        help="Calculated pool of eligible peers strictly matching hierarchical evaluation rules.")
    peer_ids = fields.Many2many(
        'hr.employee', 'competency_director_peer_rel', 'config_id', 'peer_id',
        string='Assigned 360° Peers',
        domain="[('id', 'in', candidate_peer_ids)]",
        help="Select peers for this employee. Restricted strictly to candidates eligible under their tier.")
    peer_count = fields.Integer(string='Assigned Peers', compute='_compute_peer_count')
    notes = fields.Text(string='Notes / Rationale')
    has_open_cycle = fields.Boolean(
        string='Has Open Cycle', compute='_compute_has_open_cycle',
        help="Technical flag indicating if there is at least one currently open assessment cycle."
    )

    # ---------------------------------------------------------
    # Accurate Classification Helpers
    # ---------------------------------------------------------
    @api.model
    def _get_job_name(self, emp):
        if not emp:
            return ''
        candidates = []
        if getattr(emp, 'job_id', False) and emp.job_id.name:
            candidates.append(str(emp.job_id.name).strip().lower())
        if getattr(emp, 'job_position', False) and emp.job_position.name:
            candidates.append(str(emp.job_position.name).strip().lower())
        if getattr(emp, 'job_name', False) and emp.job_name:
            candidates.append(str(emp.job_name).strip().lower())
        if not candidates and 'hr.version' in self.env:
            v = self.env['hr.version'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if v and v.job_id and v.job_id.name:
                candidates.append(str(v.job_id.name).strip().lower())

        for c in candidates:
            if any(k in c for k in ('acting', 'chief', 'director', 'branch manager', 'branch manger')):
                return c
        return candidates[0] if candidates else ''

    @api.model
    def _is_ceo(self, emp):
        """Identify CEO by job title or hierarchy."""
        if not emp or not emp.active:
            return False
        j = self._get_job_name(emp)
        if not j:
            return False
        if any(w in j for w in ('vice president', 'deputy', 'assistant', 'assistance', 'support')):
            return False
        return (
            'chief executive officer' in j
            or j.strip() in ('ceo', 'president')
            or 'group president' in j
        )

    @api.model
    def _is_branch_manager(self, emp):
        """Strictly classify as Branch Manager based on actual managerial position."""
        if not emp or not emp.active:
            return False
        j = self._get_job_name(emp)
        if not j:
            return False
        exclusions = (
            'chief', 'director', 'supervisor', 'officer', 'team leader', 'division',
            'compliance', 'support manager', 'operations manager', 'coordination',
            'assistant', 'associate'
        )
        if any(ex in j for ex in exclusions):
            return False
        return bool(
            re.search(r'\b(branch\s+man[a-z]*ger|basic\s+branch\s+man[a-z]*ger|sub\s+branch\s+man[a-z]*ger|relief\s+branch\s+man[a-z]*ger)\b', j)
            or j.startswith('bm ') or j.startswith('bm-') or j.endswith(' bm') or ' bm ' in j
        )

    @api.model
    def _is_chief(self, emp):
        """Strictly classify as C-Suite Executive (exclude Chief Cashier, Chief Driver, assistants, deputies)."""
        if not emp or not emp.active:
            return False
        if self._is_ceo(emp) or self._is_branch_manager(emp):
            return False
        j = self._get_job_name(emp)
        if not j:
            return False
        exclusions = (
            'assistant', 'assistance', 'support manager', 'special assistant',
            'cashier', 'driver', 'security', 'clerk', 'deputy'
        )
        if any(ex in j for ex in exclusions):
            return False
        # Must have 'chief' as distinct word and contain 'officer' or 'c-level'
        if re.search(r'\b(acting[\s\-]*)?chief\b', j) and ('officer' in j or 'c-level' in j):
            return True
        return False

    @api.model
    def _is_director(self, emp):
        """Strictly classify as Directorate Director (exclude District Manager, Branch Manager, Chief, Directorate officers)."""
        if not emp or not emp.active:
            return False
        if self._is_chief(emp) or self._is_ceo(emp) or self._is_branch_manager(emp):
            return False
        j = self._get_job_name(emp)
        if not j:
            return False
        exclusions = (
            'assistant', 'assistance', 'deputy', 'secretary', 'support manager',
            'special assistant', 'cashier', 'driver', 'security', 'clerk',
            'officer', 'specialist', 'analyst', 'team leader'
        )
        if any(ex in j for ex in exclusions):
            return False
        # Must be Director (not merely an officer whose dept is '... Directorate')
        if re.search(r'\b(acting[\s\-]+director|senior[\s\-]+director|director)\b', j):
            return True
        g_num = self._get_grade_number(emp)
        if g_num == 16 and 'director' in j:
            return True
        return False

    @api.model
    def _is_grade_15(self, emp):
        """Strictly classify as Grade 15 Executive."""
        if not emp or not emp.active:
            return False
        if self._is_chief(emp) or self._is_director(emp) or self._is_ceo(emp) or self._is_branch_manager(emp):
            return False
        g_num = self._get_grade_number(emp)
        return g_num == 15

    @api.model
    def _is_director_or_chief(self, emp):
        """Classify as Executive: Grade 15, Director (Grade 16) or Chief (Grade 17)."""
        if not emp or not emp.active:
            return False
        emp_sudo = emp.sudo()
        return self._is_chief(emp_sudo) or self._is_director(emp_sudo) or self._is_grade_15(emp_sudo)

    # ---------------------------------------------------------
    # Access Scoping & Search Filters
    # ---------------------------------------------------------
    @api.model
    def _get_manageable_employee_ids(self, user=None):
        """Returns list of employee IDs whose peer configuration this user can manage:
        - Admin / Officer / Superuser: returns None (unrestricted, sees all records)
        - CEO: returns all active Chiefs (Grade 17)
        - Chief: returns Directors directly under them + Grade 15s directly under them
        - Director: returns Branch Managers directly under them + Grade 15s directly under them
        - Others: returns [] (no access)
        """
        user = user or self.env.user
        is_admin = (
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('competency_management.group_competency_officer')
            or self.env.su
            or self.env.is_admin()
        )
        if is_admin:
            return None

        user_emp = user.employee_id
        if not user_emp or not user_emp.active:
            return []

        user_emp_id = user_emp.id
        emp_model = self.env['hr.employee'].sudo()

        # 1. CEO -> manages all Chiefs
        if self._is_ceo(user_emp):
            possible = emp_model.search([
                ('active', '=', True),
                ('id', '!=', user_emp_id),
                '|',
                ('job_position.name', 'ilike', 'chief'),
                ('job_id.name', 'ilike', 'chief'),
            ])
            chiefs = possible.filtered(lambda e: self._is_chief(e))
            return chiefs.ids

        # 2. Chief / Director -> manages direct subordinates
        subordinates = emp_model.search([
            ('active', '=', True),
            '|',
            ('coach_id', '=', user_emp_id),
            ('parent_id', '=', user_emp_id),
        ])

        # Chief -> manages Directors under them + Grade 15s under them
        if self._is_chief(user_emp):
            managed = subordinates.filtered(
                lambda e: self._is_director(e) or self._is_grade_15(e)
            )
            return managed.ids

        # Director -> manages Branch Managers under them + Grade 15s under them
        if self._is_director(user_emp):
            managed = subordinates.filtered(
                lambda e: self._is_branch_manager(e) or self._is_grade_15(e)
            )
            return managed.ids

        return []

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, *, active_test=True, bypass_access=False):
        manageable_ids = self._get_manageable_employee_ids()
        if manageable_ids is not None and not bypass_access:
            domain = [('director_id', 'in', manageable_ids)] + list(domain)
        return super()._search(domain, offset=offset, limit=limit, order=order, active_test=active_test, bypass_access=bypass_access)

    def check_access_rule(self, operation):
        if (self.env.user.has_group('competency_management.group_competency_admin')
                or self.env.user.has_group('competency_management.group_competency_officer')
                or self.env.su
                or self.env.is_admin()):
            return super().check_access_rule(operation)

        manageable_ids = self._get_manageable_employee_ids()
        if manageable_ids is None:
            return super().check_access_rule(operation)

        for rec in self:
            if rec.director_id and rec.director_id.id not in manageable_ids:
                raise AccessError(_("You are not authorized to view or configure peers for '%s'.") % rec.director_id.name)
        return super().check_access_rule(operation)

    def web_read(self, specification):
        self.check_access_rule('read')
        return super(CompetencyDirectorPeerConfig, self.sudo()).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        self.check_access_rule('read')
        return super(CompetencyDirectorPeerConfig, self.sudo()).read(fields=fields, load=load)

    # ---------------------------------------------------------
    # Field Computes & Constraints
    # ---------------------------------------------------------
    @api.depends('director_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.sudo().director_id.department_id if rec.director_id else False

    @api.depends('peer_ids')
    def _compute_peer_count(self):
        for rec in self:
            rec.peer_count = len(rec.peer_ids)

    @api.depends_context('company')
    def _compute_has_open_cycle(self):
        has_open = bool(self.env['competency.assessment.cycle'].search_count([('state', '=', 'open')]))
        for rec in self:
            rec.has_open_cycle = has_open

    @api.depends('director_id', 'grade_id', 'director_id.job_id')
    def _compute_config_tier(self):
        for rec in self:
            if not rec.director_id:
                rec.config_tier = False
                continue
            emp = rec.sudo().director_id
            if self._is_chief(emp):
                rec.config_tier = 'chief'
            elif self._is_branch_manager(emp):
                rec.config_tier = 'branch_manager'
            elif self._is_director(emp):
                rec.config_tier = 'director'
            elif self._is_grade_15(emp):
                rec.config_tier = 'executive_15'
            else:
                rec.config_tier = False

    @api.model
    def _get_employee_job(self, emp):
        """Safely fetch job position for an employee."""
        if not emp:
            return self.env['hr.job']
        return getattr(emp, 'job_position', False) or emp.job_id or self.env['hr.job']

    @api.depends('director_id', 'director_id.job_id')
    def _compute_job_id(self):
        for rec in self:
            rec.job_id = self.sudo()._get_employee_job(rec.sudo().director_id) if rec.director_id else False

    @api.model
    def _resolve_employee_grade(self, emp):
        """Resolves employee.grade record safely."""
        if not emp:
            return self.env['employee.grade']

        grade = getattr(emp, 'grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

        grade = getattr(emp, 'job_grade', False)
        if grade and getattr(grade, '_name', '') == 'employee.grade':
            return grade

        if 'hr.version' in self.env:
            contract = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'probation', 'draft'])
            ], order='id desc', limit=1)
            if contract and getattr(contract, 'job_grade', False):
                g = contract.job_grade
                if getattr(g, '_name', '') == 'employee.grade':
                    return g

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

    @api.depends('director_id', 'config_tier', 'grade_id', 'director_id.job_id', 'director_id.coach_id', 'director_id.parent_id')
    def _compute_candidate_peer_ids(self):
        """Calculate pool of eligible peers strictly based on evaluation hierarchy:
        - Chiefs (Grade XVII): pool = ALL other active Chiefs bank-wide (assigned by CEO).
        - Directors (Grade XVI): pool = ALL active Directors bank-wide (ONLY directors).
        - Branch Managers: pool = ONLY other Branch Managers under the SAME Director/Coach.
        - Grade XV Executives: pool = ALL other active Grade XV employees bank-wide.
        """
        peer_config = self.sudo()
        emp_model = self.env['hr.employee'].sudo()

        for rec in self:
            if not rec.director_id:
                rec.candidate_peer_ids = self.env['hr.employee']
                continue

            emp = rec.sudo().director_id
            tier = rec.config_tier
            if not tier:
                if peer_config._is_chief(emp):
                    tier = 'chief'
                elif peer_config._is_branch_manager(emp):
                    tier = 'branch_manager'
                elif peer_config._is_director(emp):
                    tier = 'director'
                elif peer_config._is_grade_15(emp):
                    tier = 'executive_15'

            if tier == 'chief':
                possible = emp_model.search([
                    ('active', '=', True),
                    ('id', '!=', emp.id),
                    '|',
                    ('job_position.name', 'ilike', 'chief'),
                    ('job_id.name', 'ilike', 'chief'),
                ])
                rec.candidate_peer_ids = possible.filtered(lambda e: peer_config._is_chief(e))
            elif tier == 'branch_manager':
                emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id or rec.coach_id
                if emp_coach:
                    possible = emp_model.search([
                        ('active', '=', True),
                        ('id', '!=', emp.id),
                        '|',
                        ('coach_id', '=', emp_coach.id),
                        ('parent_id', '=', emp_coach.id),
                    ])
                    rec.candidate_peer_ids = possible.filtered(lambda e: peer_config._is_branch_manager(e))
                else:
                    rec.candidate_peer_ids = self.env['hr.employee']
            elif tier == 'director':
                possible = emp_model.search([
                    ('active', '=', True),
                    ('id', '!=', emp.id),
                    '|',
                    ('job_position.name', 'ilike', 'director'),
                    ('job_id.name', 'ilike', 'director'),
                ])
                rec.candidate_peer_ids = possible.filtered(lambda e: peer_config._is_director(e))
            elif tier == 'executive_15':
                all_active = emp_model.search([
                    ('active', '=', True),
                    ('id', '!=', emp.id),
                ])
                rec.candidate_peer_ids = all_active.filtered(lambda e: peer_config._is_grade_15(e))
            else:
                rec.candidate_peer_ids = self.env['hr.employee']

    @api.onchange('director_id')
    def _onchange_director_id(self):
        if not self.director_id:
            self.candidate_peer_ids = self.env['hr.employee']
            return {'domain': {'peer_ids': [('id', 'in', [])]}}

        self._compute_config_tier()
        self._compute_candidate_peer_ids()
        valid_peer_ids = self.candidate_peer_ids.ids
        if self.peer_ids:
            self.peer_ids = self.peer_ids.filtered(lambda p: p.id in valid_peer_ids)
        return {'domain': {'peer_ids': [('id', 'in', valid_peer_ids)]}}

    @api.constrains('director_id', 'peer_ids')
    def _check_peer_grades(self):
        for rec in self:
            if not rec.director_id or not rec.peer_ids:
                continue
            emp = rec.sudo().director_id
            if self._is_chief(emp) or rec.config_tier == 'chief':
                for peer in rec.sudo().peer_ids:
                    if not self._is_chief(peer):
                        raise ValidationError(_("Invalid Peer '%s': Peers for a Chief must also be Chiefs.") % peer.name)
            elif self._is_director(emp) or rec.config_tier == 'director':
                for peer in rec.sudo().peer_ids:
                    if not self._is_director(peer):
                        raise ValidationError(_("Invalid Peer '%s': Peers for a Director must also be Directors.") % peer.name)
            elif self._is_branch_manager(emp) or rec.config_tier == 'branch_manager':
                emp_coach = getattr(emp, 'coach_id', False) or emp.parent_id or rec.coach_id
                for peer in rec.sudo().peer_ids:
                    if not self._is_branch_manager(peer):
                        raise ValidationError(_("Invalid Peer '%s': Peers for a Branch Manager must also be Branch Managers.") % peer.name)
                    peer_coach = getattr(peer, 'coach_id', False) or peer.parent_id
                    if not emp_coach or not peer_coach or emp_coach.id != peer_coach.id:
                        raise ValidationError(_(
                            "Invalid Peer '%s': Branch Manager peers must be under the same Director/Coach (%s)."
                        ) % (peer.name, emp_coach.name if emp_coach else 'None'))
            elif self._is_grade_15(emp) or rec.config_tier == 'executive_15':
                for peer in rec.sudo().peer_ids:
                    if not self._is_grade_15(peer):
                        raise ValidationError(_("Invalid Peer '%s': Peers for a Grade XV Executive must also be Grade XV.") % peer.name)

    @api.constrains('director_id')
    def _check_unique_director(self):
        for rec in self:
            if rec.director_id:
                existing = self.sudo().search([
                    ('id', '!=', rec.id),
                    ('director_id', '=', rec.director_id.id)
                ], limit=1)
                if existing:
                    raise ValidationError(_("A peer configuration record already exists for '%s'.") % rec.sudo().director_id.name)

    @api.constrains('director_id')
    def _check_director_grade(self):
        for rec in self:
            if rec.director_id:
                emp = rec.sudo().director_id
                if not (self._is_director_or_chief(emp) or self._is_branch_manager(emp)):
                    raise ValidationError(_(
                        "Employee '%s' cannot be configured here. "
                        "Peer Configuration is strictly reserved for Chiefs (Grade XVII), Directors (Grade XVI), "
                        "Grade XV Executives, and Branch Managers."
                    ) % emp.name)

    # ---------------------------------------------------------
    # Synchronization & Discovery Actions
    # ---------------------------------------------------------
    def action_populate_my_team(self):
        """Populates all eligible subordinates for the logged-in user:
        - If Chief: finds all Directors under this Chief + Grade 15s under this Chief
        - If Director: finds all Branch Managers under this Director + Grade 15s under this Director
        - If CEO: finds all Chiefs
        Creates missing configuration records for them.
        """
        manageable_ids = self._get_manageable_employee_ids()
        if manageable_ids is None:
            return self.action_generate_director_records()

        created_count = 0
        existing_ids = set(self.sudo().search([('director_id', 'in', manageable_ids)]).mapped('director_id.id'))
        for emp_id in manageable_ids:
            if emp_id not in existing_ids:
                self.sudo().create({'director_id': emp_id})
                created_count += 1

        total_count = len(manageable_ids)
        user_emp = self.env.user.employee_id
        role_label = _("My Team")
        if user_emp:
            if self._is_ceo(user_emp):
                role_label = _("Chiefs")
            elif self._is_chief(user_emp):
                role_label = _("Directors")
            elif self._is_director(user_emp):
                role_label = _("Branch Managers")

        msg = _("Successfully populated %s for peer assignment. Total: %d, newly created: %d.") % (
            role_label, total_count, created_count
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Team Populated'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    def _sync_peer_assessments_for_cycle(self, cycle):
        """Apply one peer configuration to one open cycle's evaluated cohort."""
        self.ensure_one()
        config = self.sudo()
        director = config.director_id
        director_user_id = director.user_id.id if director else False
        if not director_user_id:
            return (0, 0, 0)

        # Peer ratings stay inside the cycle's frozen cohort. A manager outside
        # it may rate a direct report through the team/supervisor path, not here.
        director_in_scope = cycle._includes_employee(director)
        target_peers = config.peer_ids.filtered(
            lambda peer: director_in_scope and peer.active and cycle._includes_employee(peer)
        )
        target_employee_ids = set(target_peers.ids)
        AssessmentSudo = self.env['competency.assessment'].sudo()
        existing_peer_asms = AssessmentSudo.search([
            ('cycle_id', '=', cycle.id),
            ('assessor_id', '=', director_user_id),
            ('assessment_type', '=', 'peer'),
        ])
        existing_emp_ids = set(existing_peer_asms.mapped('employee_id.id'))

        removed_asms = existing_peer_asms.filtered(
            lambda assessment: assessment.state == 'draft'
            and assessment.employee_id.id not in target_employee_ids
        )
        removed_count = len(removed_asms)
        if removed_asms:
            removed_asms.unlink()

        added_count = 0
        for peer in target_peers:
            if peer.id in existing_emp_ids:
                continue
            new_asm = AssessmentSudo.create({
                'cycle_id': cycle.id,
                'employee_id': peer.id,
                'assessor_id': director_user_id,
                'assessment_type': 'peer',
            })
            try:
                new_asm._do_populate_lines()
            except Exception:
                pass
            added_count += 1

        return (added_count, removed_count, len(target_employee_ids & existing_emp_ids))

    def action_sync_cycle_peers(self):
        """Synchronize this configuration into every currently open cycle."""
        self.ensure_one()
        director = self.sudo().director_id
        if not director:
            raise UserError(_("Please specify an employee before synchronizing peers."))
        if not director.user_id:
            raise UserError(_("Employee '%s' has no associated user account. Assessments cannot be assigned without a user account.") % director.name)

        open_cycles = self.env['competency.assessment.cycle'].sudo().search([
            ('state', '=', 'open'), ('active', '=', True)
        ], order='id desc')
        if not open_cycles:
            raise UserError(_("There is currently no open assessment cycle."))

        totals = [0, 0, 0]
        for cycle in open_cycles:
            for index, count in enumerate(self._sync_peer_assessments_for_cycle(cycle)):
                totals[index] += count

        msg = _(
            "Peer synchronization complete for %(employee)s across %(cycles)d open cycle(s):\n"
            "%(added)d new peer assessment(s), %(removed)d draft assessment(s) removed, "
            "and %(preserved)d existing assessment(s) preserved."
        ) % {
            'employee': director.name,
            'cycles': len(open_cycles),
            'added': totals[0],
            'removed': totals[1],
            'preserved': totals[2],
        }

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
        """Synchronize every permitted peer configuration into all open cycles."""
        open_cycles = self.env['competency.assessment.cycle'].sudo().search([
            ('state', '=', 'open'), ('active', '=', True)
        ], order='id desc')
        if not open_cycles:
            raise UserError(_("There is currently no open assessment cycle."))

        # Scope configs according to manageable IDs if not admin
        manageable_ids = self._get_manageable_employee_ids()
        if manageable_ids is not None:
            all_configs = self.sudo().search([('director_id', 'in', manageable_ids)])
        else:
            all_configs = self.sudo().search([])

        total_created = 0
        total_removed = 0
        total_preserved = 0
        employees_synced = 0
        for config in all_configs:
            director = config.director_id
            if not director or not director.user_id:
                continue
            for cycle in open_cycles:
                added, removed, preserved = config._sync_peer_assessments_for_cycle(cycle)
                total_created += added
                total_removed += removed
                total_preserved += preserved
            employees_synced += 1

        msg = _(
            "Peer Synchronization Complete across %d open cycle(s):\n"
            "• %d Employee(s) processed.\n"
            "• %d new peer assessment(s) generated.\n"
            "• %d removed draft peer assessment(s) deleted.\n"
            "• %d active peer assessment(s) preserved."
        ) % (len(open_cycles), employees_synced, total_created, total_removed, total_preserved)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Peers Synchronized'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                },
            }
        }

    def action_generate_director_records(self, *args, **kwargs):
        """Scan active hr.employee records for Chiefs, Directors, Grade 15s, and Branch Managers."""
        all_employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        eligible_emps = all_employees.filtered(
            lambda e: self._is_director_or_chief(e) or self._is_branch_manager(e)
        )
        eligible_emp_ids = set(eligible_emps.ids)

        existing_emp_ids = set(self.sudo().search([]).mapped('director_id.id'))
        created_count = 0

        for emp_id in eligible_emp_ids:
            if emp_id not in existing_emp_ids:
                self.sudo().create({'director_id': emp_id})
                existing_emp_ids.add(emp_id)
                created_count += 1

        msg = _("Successfully synchronized Peer Configurations.\nCreated: %d, Total Active Configured Positions: %d.") % (
            created_count, len(existing_emp_ids)
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Records Synchronized'),
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
        """Auto-populate any newly appointed positions before displaying configuration."""
        self.action_generate_director_records()
        return self.env['ir.actions.act_window']._for_xml_id('competency_management.action_competency_director_peer_config')

    @api.model
    def action_open_scoped_peer_config(self):
        """Entry point for CEO, Chiefs, and Directors to assign peers for their subordinates."""
        # 1. Auto-populate eligible subordinates for current user
        self.action_populate_my_team()

        # 2. Determine title based on role
        user_emp = self.env.user.employee_id
        action_name = _('My Team Peer Configuration')
        if user_emp:
            if self._is_ceo(user_emp):
                action_name = _('Chief Peer Configuration (CEO Scope)')
            elif self._is_chief(user_emp):
                action_name = _('Director Peer Configuration (Chief Scope)')
            elif self._is_director(user_emp):
                action_name = _('Branch Manager Peer Configuration (Director Scope)')

        action = self.env['ir.actions.act_window']._for_xml_id('competency_management.action_competency_director_peer_config_scoped')
        action['name'] = action_name
        return action
