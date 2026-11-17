# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import timedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    name_amharic = fields.Char(
        string='Name (Amharic / ሙሉ ስም በአማርኛ)',
        tracking=True,
        help='Official employee name in Amharic script used for legal notices and memos.'
    )

    # Disciplinary History Smart Fields
    executive_level = fields.Selection([
        ('ceo', 'Chief Executive Officer (CEO)'),
        ('chief', 'Chief Officer / CPCO'),
        ('director', 'Directorate Director'),
        ('manager', 'Division / Branch Manager'),
        ('employee', 'Non-Managerial / Specialist Employee'),
    ], string='Organizational Tier Level', compute='_compute_executive_level', store=True)

    is_managerial = fields.Boolean(
        string='Is Managerial Staff',
        compute='_compute_is_managerial',
        store=True,
        readonly=False,
        help='Indicates whether employee belongs to Managerial Staff (uses managerial penalty rates)'
    )
    active_disciplinary_action = fields.Boolean(
        string='Has Active Disciplinary Action',
        default=False,
        help='Indicates whether employee has an active/enforced disciplinary warning or pending case',
        tracking=True
    )
    disciplinary_warning_count = fields.Integer(
        string='Total Disciplinary Warnings',
        default=0,
        readonly=True,
        tracking=True
    )
    last_disciplinary_date = fields.Date(
        string='Last Disciplinary Action Date',
        readonly=True,
        tracking=True
    )
    is_suspended = fields.Boolean(
        string='Currently Suspended',
        default=False,
        readonly=True,
        tracking=True
    )
    suspension_type = fields.Selection([
        ('with_pay', 'Suspension With Pay'),
        ('without_pay', 'Suspension Without Pay'),
    ], string='Active Suspension Type', readonly=True)

    is_ineligible_for_promotion_transfer = fields.Boolean(
        string='Ineligible for Promotion / Transfer',
        default=False,
        help='Automatically set to True when active disciplinary penalties (warnings, demotion) are enforced.',
        tracking=True
    )

    discipline_case_ids = fields.One2many(
        'discipline.case',
        'employee_id',
        string='Disciplinary Cases History'
    )
    discipline_case_count = fields.Integer(
        string='Disciplinary Cases Count',
        compute='_compute_discipline_case_count'
    )

    @api.depends('discipline_case_ids')
    def _compute_discipline_case_count(self):
        for emp in self:
            emp.discipline_case_count = len(emp.discipline_case_ids)

    def check_discipline_eligibility(self, action_type='promotion', is_forced=False):
        """
        Check if employee is eligible for promotion, transfer, or internal recruitment.
        :param action_type: 'promotion', 'transfer', or 'recruitment'
        :param is_forced: Boolean - True if HR/Management is executing an administrative/forced transfer
        :return: (is_eligible: bool, reason: str)
        """
        self.ensure_one()
        if self.is_suspended:
            return (False, _('Employee is currently under active disciplinary suspension (%s).') % (self.suspension_type or 'Standard'))
        
        # Administrative / forced transfer initiated by HR/Management is always permitted
        if action_type == 'transfer' and is_forced:
            return (True, _('Administrative transfer permitted for operational or disciplinary reassignment.'))

        if self.is_ineligible_for_promotion_transfer:
            return (False, _('Candidate is currently ineligible for promotion/transfer due to an active disciplinary penalty.'))
        
        today = fields.Date.context_today(self)
        active_cases = self.discipline_case_ids.filtered(
            lambda c: c.state in ('enforced', 'closed', 'appealed') and (
                (c.active_penalty_end_date and c.active_penalty_end_date >= today) or
                (not c.active_penalty_end_date and c.final_decision_date and c.final_decision_date >= (today - timedelta(days=365)))
            ) and (c.severity_level in ['level_1', 'level_2'] or c.punishment_type in ['dismissal', 'demotion', 'final_warning_penalty'])
        )
        if active_cases:
            case_names = ", ".join(active_cases.mapped('name'))
            return (False, _('Candidate is currently ineligible for promotion due to an active disciplinary penalty (Cases: %s).') % case_names)
        
        return (True, _('Employee is eligible.'))

    @api.model
    def _cron_revert_ineligibility(self):
        """Cron job: automatically revert ineligibility flag once legal active penalty period expires."""
        today = fields.Date.context_today(self)
        ineligible_employees = self.search([
            ('is_ineligible_for_promotion_transfer', '=', True),
            ('is_suspended', '=', False),
        ])
        for emp in ineligible_employees:
            active_recent_cases = emp.discipline_case_ids.filtered(
                lambda c: c.state in ('enforced', 'closed', 'appealed') and (
                    (c.active_penalty_end_date and c.active_penalty_end_date >= today) or
                    (not c.active_penalty_end_date and c.final_decision_date and c.final_decision_date >= (today - timedelta(days=365)))
                ) and (c.severity_level in ['level_1', 'level_2'] or c.punishment_type in ['dismissal', 'demotion', 'final_warning_penalty'])
            )
            if not active_recent_cases:
                emp.with_context(no_leave_resource_calendar_update=True).write({
                    'is_ineligible_for_promotion_transfer': False,
                    'active_disciplinary_action': False,
                })

    @api.depends('job_id', 'job_id.name', 'is_managerial')
    def _compute_executive_level(self):
        for emp in self:
            job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
            if any(kw in job_name for kw in ['ceo', 'chief executive officer', 'president']):
                emp.executive_level = 'ceo'
            elif any(kw in job_name for kw in ['deputy chief', 'chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                emp.executive_level = 'chief'
            elif any(kw in job_name for kw in ['director', 'directorate', 'regional manager']):
                emp.executive_level = 'director'
            elif emp.is_managerial or any(kw in job_name for kw in ['manager', 'head', 'supervisor', 'division', 'branch manager']):
                emp.executive_level = 'manager'
            else:
                emp.executive_level = 'employee'

    @api.model
    def get_user_hierarchy_role(self, user):
        """
        Dynamically determine user's governance hierarchy tier from organizational structure:
        - 'ceo': Chief Executive Officer / Superuser / Discipline Admin
        - 'chief': Chief Officer / Deputy Chief / C-Level Executive
        - 'director': Directorate Director / Regional Director
        - 'manager': Line Coach / Division Manager / Branch Manager
        - 'employee': Individual Contributor
        """
        if not user:
            return 'employee'
        
        # Superuser / Admin
        if user._is_superuser() or user.has_group('base.group_system'):
            return 'ceo'
            
        EmpModel = self.sudo()
        ceo_user = EmpModel.get_ceo_user()
        if ceo_user and user.id == ceo_user.id:
            return 'ceo'
        if user.has_group('discipline_management.group_discipline_ceo'):
            return 'ceo'

        emp = user.employee_id.sudo() if user.employee_id else False
        if not emp:
            if user.has_group('discipline_management.group_discipline_admin'):
                return 'ceo'
            return 'employee'

        job_name = (emp.job_id.name or '').lower() if emp.job_id else ''
        exec_level = getattr(emp, 'executive_level', False)

        # 1. CEO check
        if any(kw in job_name for kw in ['ceo', 'chief executive officer', 'president']) or exec_level == 'ceo':
            return 'ceo'

        # 2. Chief / Deputy Chief / C-Level Executive check
        is_chief_kw = any(kw in job_name for kw in ['deputy chief', 'chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp'])
        if is_chief_kw or exec_level == 'chief':
            return 'chief'
        # Check if they supervise any Directors in reporting tree
        has_director_subs = bool(EmpModel.search_count([
            ('id', 'child_of', emp.id),
            ('id', '!=', emp.id),
            '|', ('executive_level', '=', 'director'), ('job_id.name', 'ilike', 'director')
        ]))
        if has_director_subs:
            return 'chief'

        # 3. Director check
        is_dir_kw = any(kw in job_name for kw in ['director', 'directorate', 'regional manager'])
        if is_dir_kw or exec_level == 'director' or user.has_group('discipline_management.group_discipline_director'):
            return 'director'
        # Check if department manager of directorate-level department or supervises managers
        if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.id == emp.id:
            dept_name = (emp.department_id.name or '').lower()
            if 'director' in dept_name or 'directorate' in dept_name or 'region' in dept_name:
                return 'director'
        has_mgr_subs = bool(EmpModel.search_count([
            ('id', 'child_of', emp.id),
            ('id', '!=', emp.id),
            '|', ('executive_level', '=', 'manager'), ('job_id.name', 'ilike', 'manager')
        ]))
        if has_mgr_subs:
            return 'director'

        # 4. Manager / Coach check
        has_subs = bool(EmpModel.search_count([('id', 'child_of', emp.id), ('id', '!=', emp.id)]))
        if has_subs or emp.is_managerial or any(kw in job_name for kw in ['manager', 'head', 'supervisor', 'division', 'branch manager', 'coach']):
            return 'manager'

        return 'employee'

    def get_subordinate_employee_ids(self, scope='all_hierarchy'):
        """
        Retrieve subordinate hr.employee IDs based on hierarchy scope:
        - 'all_hierarchy': Entire downstream reporting tree (child_of)
        - 'direct_reports': Direct reports only (child_ids)
        """
        self.ensure_one()
        if scope == 'direct_reports':
            return self.child_ids.ids + [self.id]
        # all_hierarchy
        return self.env['hr.employee'].sudo().search([('id', 'child_of', self.id)]).ids

    def get_supervisor_chain(self):
        """Return ordered list of supervisor hr.employee records from direct coach/manager up to CEO."""
        self.ensure_one()
        chain = []
        current = (self.coach_id or self.parent_id).sudo()
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            chain.append(current)
            current = (current.coach_id or current.parent_id).sudo()
        return chain

    def is_supervisor_of(self, target_employee):
        """Return True if self is in the supervisory chain of target_employee."""
        if not target_employee:
            return False
        return self.id in [s.id for s in target_employee.sudo().get_supervisor_chain()]

    @api.model
    def get_cpco_user(self):
        """
        Unified CPCO Resolution Engine:
        1. Explicit UI Setting in Discipline & Governance Settings (discipline.cpco_user_id)
        2. Pure Security Group Membership (group_discipline_cpco)
        3. Fallback to System Administrator or current user
        """
        ICP = self.env['ir.config_parameter'].sudo()
        cpco_user_id_param = ICP.get_param('discipline.cpco_user_id')
        if cpco_user_id_param:
            try:
                cpco_user = self.env['res.users'].browse(int(cpco_user_id_param)).exists()
                if cpco_user:
                    return cpco_user
            except (ValueError, TypeError):
                pass

        # 2. Check Pure Security Group
        cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
        ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
        admin_group = self.env.ref('discipline_management.group_discipline_admin', raise_if_not_found=False)
        if cpco_group:
            cpco_users = cpco_group.all_user_ids or cpco_group.user_ids
            higher_users = (ceo_group.all_user_ids if ceo_group else self.env['res.users']) | (admin_group.all_user_ids if admin_group else self.env['res.users'])
            dedicated_cpco = cpco_users - higher_users
            if dedicated_cpco:
                return dedicated_cpco[0]
            if cpco_users:
                return cpco_users[0]

        # 3. Fallback Admin
        return self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user

    @api.model
    def get_secretary_user(self):
        """
        Resolve Disciplinary Committee Secretary (POMD Director):
        1. Explicit UI Setting in Discipline & Governance Settings (discipline.secretary_user_id)
        2. Pure Security Group Membership (group_discipline_pomd_director or group_discipline_pomd)
        3. Fallback to System Administrator or current user
        """
        ICP = self.env['ir.config_parameter'].sudo()
        sec_id_param = ICP.get_param('discipline.secretary_user_id')
        if sec_id_param:
            try:
                sec_user = self.env['res.users'].browse(int(sec_id_param)).exists()
                if sec_user:
                    return sec_user
            except (ValueError, TypeError):
                pass

        pomd_dir_group = self.env.ref('discipline_management.group_discipline_pomd_director', raise_if_not_found=False)
        pomd_group = self.env.ref('discipline_management.group_discipline_pomd', raise_if_not_found=False)
        cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
        ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
        admin_group = self.env.ref('discipline_management.group_discipline_admin', raise_if_not_found=False)

        higher_users = (
            (cpco_group.all_user_ids if cpco_group else self.env['res.users']) |
            (ceo_group.all_user_ids if ceo_group else self.env['res.users']) |
            (admin_group.all_user_ids if admin_group else self.env['res.users'])
        )

        # Check dedicated POMD Director group first, then general POMD group
        for group in (pomd_dir_group, pomd_group):
            if group:
                users = (group.all_user_ids or group.user_ids) - higher_users
                if users:
                    return users[0]

        # Fallback to employee with Talent Management / People Operations Directorate role
        sec_emp = self.sudo().search([
            '|', '|',
            ('name', 'ilike', 'Abayneh Habtie'),
            ('job_id.name', 'ilike', 'Talent Management'),
            ('job_id.name', 'ilike', 'People Operations'),
            ('user_id', '!=', False),
            ('user_id', 'not in', higher_users.ids if higher_users else [0])
        ], limit=1)
        if sec_emp and sec_emp.user_id:
            return sec_emp.user_id

        return self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user

    @api.model
    def get_pomd_user(self):
        """Alias for get_secretary_user (POMD Director / Committee Secretary)."""
        return self.get_secretary_user()

    @api.model
    def get_legal_user(self):
        """
        Resolve Legal Directorate Representative:
        1. Explicit UI Setting in Discipline & Governance Settings (discipline.legal_user_id)
        2. Security Group Membership (group_discipline_legal)
        """
        ICP = self.env['ir.config_parameter'].sudo()
        legal_id_param = ICP.get_param('discipline.legal_user_id')
        if legal_id_param:
            try:
                legal_user = self.env['res.users'].browse(int(legal_id_param)).exists()
                if legal_user:
                    return legal_user
            except (ValueError, TypeError):
                pass

        legal_group = self.env.ref('discipline_management.group_discipline_legal', raise_if_not_found=False)
        if legal_group:
            legal_users = legal_group.all_user_ids or legal_group.user_ids
            if legal_users:
                return legal_users[0]

        return False

    @api.model
    def get_union_user(self):
        """
        Resolve Labour Union Representative for Disciplinary Committee meetings:
        Strictly configured via Settings (discipline.union_user_id).
        """
        ICP = self.env['ir.config_parameter'].sudo()
        union_id_param = ICP.get_param('discipline.union_user_id')
        if union_id_param:
            try:
                union_user = self.env['res.users'].browse(int(union_id_param)).exists()
                if union_user:
                    return union_user
            except (ValueError, TypeError):
                pass
        return False

    @api.model
    def get_audit_director_user(self):
        """
        Resolve Internal Audit Directorate Director:
        1. Explicit UI Setting in Discipline & Governance Settings (discipline.audit_user_id)
        2. Security Group Membership (group_discipline_auditor)
        """
        ICP = self.env['ir.config_parameter'].sudo()
        audit_id_param = ICP.get_param('discipline.audit_user_id')
        if audit_id_param:
            try:
                audit_user = self.env['res.users'].browse(int(audit_id_param)).exists()
                if audit_user:
                    return audit_user
            except (ValueError, TypeError):
                pass

        audit_group = self.env.ref('discipline_management.group_discipline_auditor', raise_if_not_found=False)
        if audit_group:
            audit_users = audit_group.all_user_ids or audit_group.user_ids
            if audit_users:
                return audit_users[0]

        return False

    @api.model
    def get_ceo_user(self):
        """
        Resolve Chief Executive Officer (CEO):
        1. Pure Security Group Membership (group_discipline_ceo)
        2. Executive Level on Employee record ('ceo')
        """
        ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
        admin_user = self.env.ref('base.user_admin', raise_if_not_found=False)
        if ceo_group:
            ceo_users = (ceo_group.all_user_ids or ceo_group.user_ids)
            non_admin_ceo = ceo_users - (admin_user if admin_user else self.env['res.users'])
            if non_admin_ceo:
                return non_admin_ceo[0]
            if ceo_users:
                return ceo_users[0]

        ceo_emp = self.sudo().search([
            ('user_id', '!=', False),
            ('executive_level', '=', 'ceo'),
        ], limit=1)
        if ceo_emp and ceo_emp.user_id:
            return ceo_emp.user_id

        return False

    @api.depends('job_id', 'job_id.name', 'job_id.employee_category')
    def _compute_is_managerial(self):
        for emp in self:
            job = emp.job_id or getattr(emp, 'job_position', False)
            job_name = (job.name or '').lower() if job else ''
            job_cat = getattr(job, 'employee_category', False) if job else False
            if job and getattr(job, 'is_managerial', False):
                emp.is_managerial = True
            elif job_cat == 'Managerial':
                emp.is_managerial = True
            elif job_cat == 'Non Managerial':
                # Respect explicit Non Managerial category on job (e.g. Relationship Manager), unless acting managerial role
                if any(kw in job_name for kw in ['acting manager', 'acting director', 'acting branch manager', 'acting chief']):
                    emp.is_managerial = True
                else:
                    emp.is_managerial = False
            elif any(kw in job_name for kw in ['manager', 'director', 'chief', 'team leader', 'head', 'vp', 'supervisor', 'president', 'officer in charge']) and 'relationship manager' not in job_name:
                emp.is_managerial = True
            else:
                emp.is_managerial = False

    def action_view_discipline_cases(self):
        self.ensure_one()
        return {
            'name': _('Disciplinary Cases History'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id}
        }


class HrJob(models.Model):
    _inherit = 'hr.job'

    is_managerial = fields.Boolean(
        string='Is Managerial Position',
        default=False,
        help='Check if this job position belongs to Managerial Staff'
    )

