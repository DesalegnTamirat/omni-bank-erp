# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import timedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

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
            lambda c: c.state == 'enforced' and (
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
                lambda c: c.state == 'enforced' and (
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
            elif any(kw in job_name for kw in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                emp.executive_level = 'chief'
            elif any(kw in job_name for kw in ['director', 'directorate']):
                emp.executive_level = 'director'
            elif emp.is_managerial or any(kw in job_name for kw in ['manager', 'head', 'supervisor', 'division', 'branch manager']):
                emp.executive_level = 'manager'
            else:
                emp.executive_level = 'employee'

    def get_supervisor_chain(self):
        """Return ordered list of supervisor hr.employee records from direct coach/manager up to CEO."""
        self.ensure_one()
        chain = []
        current = self.coach_id or self.parent_id
        visited = set()
        while current and current.id not in visited:
            visited.add(current.id)
            chain.append(current)
            current = current.coach_id or current.parent_id
        return chain

    def is_supervisor_of(self, target_employee):
        """Return True if self is in the supervisory chain of target_employee."""
        if not target_employee:
            return False
        return self in target_employee.get_supervisor_chain()

    @api.model
    def get_cpco_user(self):
        """
        Unified CPCO Resolution Engine:
        1. Explicit UI Setting in Discipline & Governance Settings (discipline.cpco_user_id)
        2. Security Group Membership (group_discipline_cpco)
        3. Job Position / Employee matching CPCO / Chief People
        4. Fallback to System Administrator
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

        # 2. Check Security Group
        cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
        if cpco_group:
            cpco_users = cpco_group.all_user_ids or cpco_group.user_ids
            if cpco_users:
                return cpco_users[0]

        # 3. Check Job Title
        cpco_emp = self.search([
            '|', ('job_id.name', 'ilike', 'Chief People'),
            ('job_id.name', 'ilike', 'CPCO')
        ], limit=1)
        if cpco_emp and cpco_emp.user_id:
            return cpco_emp.user_id

        # 4. Fallback Admin
        return self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user

    @api.model
    def get_secretary_user(self):
        """Resolve Disciplinary Committee Secretary (POMD Director)."""
        ICP = self.env['ir.config_parameter'].sudo()
        sec_id_param = ICP.get_param('discipline.secretary_user_id')
        if sec_id_param:
            try:
                sec_user = self.env['res.users'].browse(int(sec_id_param)).exists()
                if sec_user:
                    return sec_user
            except (ValueError, TypeError):
                pass

        pomd_emp = self.search([
            '|', ('job_id.name', 'ilike', 'People Operations Management Director'),
            ('job_id.name', 'ilike', 'People Operation')
        ], limit=1)
        if pomd_emp and pomd_emp.user_id:
            return pomd_emp.user_id

        pomd_group = self.env.ref('discipline_management.group_discipline_pomd', raise_if_not_found=False)
        if pomd_group:
            pomd_users = pomd_group.all_user_ids or pomd_group.user_ids
            if pomd_users:
                return pomd_users[0]

        return self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user

    @api.model
    def get_legal_user(self):
        """Resolve Legal Directorate Representative."""
        ICP = self.env['ir.config_parameter'].sudo()
        legal_id_param = ICP.get_param('discipline.legal_user_id')
        if legal_id_param:
            try:
                legal_user = self.env['res.users'].browse(int(legal_id_param)).exists()
                if legal_user:
                    return legal_user
            except (ValueError, TypeError):
                pass

        legal_emp = self.search([
            '|', ('job_id.name', 'ilike', 'Legal Director'),
            ('job_id.name', 'ilike', 'Legal Services Director')
        ], limit=1)
        if not legal_emp:
            legal_emp = self.search([('job_id.name', 'ilike', 'Legal')], limit=1)
        if legal_emp and legal_emp.user_id:
            return legal_emp.user_id

        legal_group = self.env.ref('discipline_management.group_discipline_legal', raise_if_not_found=False)
        if legal_group:
            legal_users = legal_group.all_user_ids or legal_group.user_ids
            if legal_users:
                return legal_users[0]

        return False

    @api.model
    def get_union_user(self):
        """Resolve Labour Union Representative for Disciplinary Committee meetings."""
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
        """Resolve Internal Audit Directorate Director."""
        ICP = self.env['ir.config_parameter'].sudo()
        audit_id_param = ICP.get_param('discipline.audit_user_id')
        if audit_id_param:
            try:
                audit_user = self.env['res.users'].browse(int(audit_id_param)).exists()
                if audit_user:
                    return audit_user
            except (ValueError, TypeError):
                pass

        audit_emp = self.search([
            '|', ('job_id.name', 'ilike', 'Internal Audit Director'),
            ('job_id.name', 'ilike', 'Audit Director')
        ], limit=1)
        if audit_emp and audit_emp.user_id:
            return audit_emp.user_id

        audit_group = self.env.ref('discipline_management.group_discipline_auditor', raise_if_not_found=False)
        if audit_group:
            audit_users = audit_group.all_user_ids or audit_group.user_ids
            if audit_users:
                return audit_users[0]

        return False

    @api.model
    def get_ceo_user(self):
        """Resolve Chief Executive Officer (CEO)."""
        ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
        if ceo_group:
            ceo_users = ceo_group.all_user_ids or ceo_group.user_ids
            if ceo_users:
                return ceo_users[0]

        ceo_emp = self.search([('executive_level', '=', 'ceo')], limit=1)
        if ceo_emp and ceo_emp.user_id:
            return ceo_emp.user_id

        return False

    @api.depends('job_id', 'job_id.name')
    def _compute_is_managerial(self):
        for emp in self:
            job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
            if emp.job_id and getattr(emp.job_id, 'is_managerial', False):
                emp.is_managerial = True
            elif any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor', 'president', 'officer in charge']):
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

