# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EdsDashboard(models.TransientModel):
    """Dynamic Role-Adaptive Dashboard for Employee Development System."""
    _name = 'eds.dashboard'
    _description = 'EDS Role-Adaptive Learning & Development Dashboard'

    name = fields.Char(string='Dashboard Title', default='Bunna Bank Employee Development Dashboard')

    # Role Persona Indicator
    role_persona = fields.Selection([
        ('admin', 'L&D Executive & Administrator'),
        ('manager', 'Line Manager / Unit Supervisor'),
        ('employee', 'Employee Self-Service (ESS)'),
    ], string='Role View', compute='_compute_role_data', readonly=True)

    is_admin = fields.Boolean(compute='_compute_role_data')
    is_manager = fields.Boolean(compute='_compute_role_data')
    is_employee = fields.Boolean(compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 1. Bank-wide Admin & Executive KPIs
    # ══════════════════════════════════════════════════════════════════════════
    total_tna_entries = fields.Integer(string='Total TNA Submissions', compute='_compute_role_data')
    approved_tna_entries = fields.Integer(string='Approved TNA Needs', compute='_compute_role_data')
    converted_tna_entries = fields.Integer(string='Converted to Plan', compute='_compute_role_data')

    total_budget_allocated = fields.Float(string='Allocated Budget (ETB)', compute='_compute_role_data')
    total_budget_spent = fields.Float(string='Actual Spend (ETB)', compute='_compute_role_data')
    budget_utilization_pct = fields.Float(string='Budget Utilization %', compute='_compute_role_data')

    active_sessions_count = fields.Integer(string='Active / Scheduled Sessions', compute='_compute_role_data')
    completed_sessions_count = fields.Integer(string='Completed Sessions', compute='_compute_role_data')
    total_enrolled_participants = fields.Integer(string='Enrolled Participants', compute='_compute_role_data')
    bank_avg_attendance_pct = fields.Float(string='Bank Attendance Rate %', compute='_compute_role_data')

    issued_certificates_count = fields.Integer(string='Issued Certificates', compute='_compute_role_data')
    avg_level1_satisfaction = fields.Float(string='Avg L1 Satisfaction %', compute='_compute_role_data')
    avg_level2_learning_gain = fields.Float(string='Avg L2 Learning Gain %', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 2. Line Manager KPIs (Team & Unit View)
    # ══════════════════════════════════════════════════════════════════════════
    team_members_count = fields.Integer(string='Team Members', compute='_compute_role_data')
    team_tna_submissions = fields.Integer(string='Team TNA Needs', compute='_compute_role_data')
    pending_team_nominations = fields.Integer(string='Pending Team Nominations', compute='_compute_role_data')
    upcoming_team_sessions = fields.Integer(string='Team Upcoming Sessions', compute='_compute_role_data')
    team_avg_attendance = fields.Float(string='Team Attendance Rate %', compute='_compute_role_data')
    team_certificates_count = fields.Integer(string='Team Certificates Earned', compute='_compute_role_data')
    team_active_idps = fields.Integer(string='Team Active IDPs', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 3. Employee Self-Service (ESS) KPIs
    # ══════════════════════════════════════════════════════════════════════════
    my_tna_needs_count = fields.Integer(string='My Training Needs', compute='_compute_role_data')
    my_approved_needs_count = fields.Integer(string='My Approved Needs', compute='_compute_role_data')
    my_enrolled_sessions_count = fields.Integer(string='My Enrolled Sessions', compute='_compute_role_data')
    my_attended_hours = fields.Float(string='My Training Hours', compute='_compute_role_data')
    my_attendance_rate = fields.Float(string='My Attendance Rate %', compute='_compute_role_data')
    my_certificates_count = fields.Integer(string='My Certificates', compute='_compute_role_data')
    my_active_idps_count = fields.Integer(string='My Active IDPs', compute='_compute_role_data')
    my_sponsorships_count = fields.Integer(string='My Sponsorships', compute='_compute_role_data')

    _transient_max_hours = 0.5  # Auto-vacuum transient records after 30 minutes

    @api.depends_context('uid')
    def _compute_role_data(self):
        user = self.env.user
        emp = user.employee_id
        is_admin_user = (
            user.has_group('employee_development_system.group_eds_officer')
            or user.has_group('employee_development_system.group_eds_manager')
            or user.has_group('employee_development_system.group_eds_admin')
            or user.has_group('employee_development_system.group_eds_executive')
        )
        is_mgr_user = user.has_group('employee_development_system.group_eds_line_manager')

        # Check direct reports
        has_subordinates = False
        team_emp_ids = []
        if emp:
            subordinates = self.env['hr.employee'].sudo().search([('parent_id', '=', emp.id)])
            if subordinates:
                has_subordinates = True
                team_emp_ids = subordinates.ids

        # Determine default role
        if is_admin_user:
            active_persona = 'admin'
        elif is_mgr_user or has_subordinates:
            active_persona = 'manager'
        else:
            active_persona = 'employee'

        # Gather Bank-wide Stats (sudo)
        tna_obj = self.env['eds.tna.entry'].sudo()
        session_obj = self.env['eds.session'].sudo()
        plan_obj = self.env['eds.annual.plan'].sudo()
        cert_obj = self.env['eds.certificate'].sudo()
        nom_obj = self.env['eds.nomination'].sudo()
        att_obj = self.env['eds.session.attendance'].sudo()
        idp_obj = self.env['eds.idp'].sudo()
        spons_obj = self.env['eds.sponsorship'].sudo()
        l1_obj = self.env['eds.evaluation.level1'].sudo()
        l2_obj = self.env['eds.evaluation.level2'].sudo()

        # 1. Admin Aggregations
        all_tna_cnt = tna_obj.search_count([])
        app_tna_cnt = tna_obj.search_count([('state', 'in', ('approved', 'converted'))])
        conv_tna_cnt = tna_obj.search_count([('state', '=', 'converted')])

        plans = plan_obj.search([('state', 'in', ('published', 'amended', 'smc_approval'))])
        alloc_budget = sum(plans.mapped('budget_total'))
        all_lines = plans.mapped('line_ids')
        actual_spend = sum(all_lines.mapped('actual_cost'))
        spend_pct = (actual_spend / alloc_budget * 100.0) if alloc_budget > 0 else 0.0

        act_sess = session_obj.search_count([('status', 'in', ('scheduled', 'ongoing', 'rescheduled'))])
        comp_sess = session_obj.search_count([('status', '=', 'completed')])
        completed_sessions = session_obj.search([('status', '=', 'completed')])
        tot_enrolled = sum(session_obj.search([]).mapped('enrolled_count'))
        bank_att_rate = (
            sum(completed_sessions.mapped('attendance_rate')) / len(completed_sessions)
            if completed_sessions else 0.0
        )

        issued_certs = cert_obj.search_count([('state', '=', 'issued')])
        l1_records = l1_obj.search([('state', 'in', ('submitted', 'consolidated'))])
        avg_l1 = (sum(l1_records.mapped('overall_score')) / len(l1_records)) if l1_records else 0.0
        l2_records = l2_obj.search([('state', '=', 'evaluated')])
        avg_l2 = (sum(l2_records.mapped('learning_gain')) / len(l2_records)) if l2_records else 0.0

        # 2. Manager Aggregations
        team_members_cnt = len(team_emp_ids)
        team_tna_cnt = tna_obj.search_count([('employee_id', 'in', team_emp_ids)]) if team_emp_ids else 0
        team_pending_nom = nom_obj.search_count([
            ('employee_id', 'in', team_emp_ids),
            ('state', 'in', ('submitted', 'line_manager_approved'))
        ]) if team_emp_ids else 0
        team_up_sess = session_obj.search_count([
            ('enrollment_ids.employee_id', 'in', team_emp_ids),
            ('status', 'in', ('scheduled', 'ongoing'))
        ]) if team_emp_ids else 0
        team_att_recs = att_obj.search([('employee_id', 'in', team_emp_ids)]) if team_emp_ids else att_obj.browse()
        team_att_pct = (
            sum(team_att_recs.mapped('attendance_percentage')) / len(team_att_recs)
            if team_att_recs else 0.0
        )
        team_certs = cert_obj.search_count([('employee_id', 'in', team_emp_ids), ('state', '=', 'issued')]) if team_emp_ids else 0
        team_idps = idp_obj.search_count([('employee_id', 'in', team_emp_ids), ('state', 'in', ('approved', 'in_progress'))]) if team_emp_ids else 0

        # 3. Employee Aggregations
        emp_id = emp.id if emp else False
        my_tna_cnt = tna_obj.search_count([('employee_id', '=', emp_id)]) if emp_id else 0
        my_app_tna = tna_obj.search_count([('employee_id', '=', emp_id), ('state', 'in', ('approved', 'converted'))]) if emp_id else 0
        my_sess_cnt = session_obj.search_count([
            ('enrollment_ids.employee_id', '=', emp_id),
            ('enrollment_ids.state', '=', 'enrolled')
        ]) if emp_id else 0
        my_atts = att_obj.search([('employee_id', '=', emp_id)]) if emp_id else att_obj.browse()
        my_hours = sum(my_atts.mapped('hours_attended'))
        my_att_rate = (sum(my_atts.mapped('attendance_percentage')) / len(my_atts)) if my_atts else 0.0
        my_cert_cnt = cert_obj.search_count([('employee_id', '=', emp_id), ('state', '=', 'issued')]) if emp_id else 0
        my_idp_cnt = idp_obj.search_count([('employee_id', '=', emp_id), ('state', 'in', ('draft', 'submitted', 'approved', 'in_progress'))]) if emp_id else 0
        my_spons_cnt = spons_obj.search_count([('employee_id', '=', emp_id)]) if emp_id else 0

        for rec in self:
            rec.role_persona = active_persona
            rec.is_admin = is_admin_user
            rec.is_manager = is_mgr_user or has_subordinates
            rec.is_employee = not is_admin_user and not (is_mgr_user or has_subordinates)

            # Bank-wide
            rec.total_tna_entries = all_tna_cnt
            rec.approved_tna_entries = app_tna_cnt
            rec.converted_tna_entries = conv_tna_cnt
            rec.total_budget_allocated = alloc_budget
            rec.total_budget_spent = actual_spend
            rec.budget_utilization_pct = round(spend_pct, 1)
            rec.active_sessions_count = act_sess
            rec.completed_sessions_count = comp_sess
            rec.total_enrolled_participants = tot_enrolled
            rec.bank_avg_attendance_pct = round(bank_att_rate, 1)
            rec.issued_certificates_count = issued_certs
            rec.avg_level1_satisfaction = round(avg_l1, 1)
            rec.avg_level2_learning_gain = round(avg_l2, 1)

            # Team
            rec.team_members_count = team_members_cnt
            rec.team_tna_submissions = team_tna_cnt
            rec.pending_team_nominations = team_pending_nom
            rec.upcoming_team_sessions = team_up_sess
            rec.team_avg_attendance = round(team_att_pct, 1)
            rec.team_certificates_count = team_certs
            rec.team_active_idps = team_idps

            # Employee
            rec.my_tna_needs_count = my_tna_cnt
            rec.my_approved_needs_count = my_app_tna
            rec.my_enrolled_sessions_count = my_sess_cnt
            rec.my_attended_hours = round(my_hours, 1)
            rec.my_attendance_rate = round(my_att_rate, 1)
            rec.my_certificates_count = my_cert_cnt
            rec.my_active_idps_count = my_idp_cnt
            rec.my_sponsorships_count = my_spons_cnt

    @api.model
    def action_open_dashboard(self):
        """Action invoked when opening the EDS Dashboard menu item."""
        dash = self.create({'name': _('Employee Development Overview')})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Employee Development Dashboard'),
            'res_model': 'eds.dashboard',
            'res_id': dash.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Navigation Action Shortcuts
    # ══════════════════════════════════════════════════════════════════════════
    def action_open_tna_entries(self):
        self.ensure_one()
        action = self.env.ref('employee_development_system.action_eds_tna_entry').read()[0]
        if self.role_persona == 'employee':
            action['domain'] = [('employee_id.user_id', '=', self.env.user.id)]
        return action

    def action_open_sessions(self):
        self.ensure_one()
        return self.env.ref('employee_development_system.action_eds_session').read()[0]

    def action_open_annual_plans(self):
        self.ensure_one()
        return self.env.ref('employee_development_system.action_eds_annual_plan').read()[0]

    def action_open_certificates(self):
        self.ensure_one()
        action = self.env.ref('employee_development_system.action_eds_certificate').read()[0]
        if self.role_persona == 'employee':
            action['domain'] = [('employee_id.user_id', '=', self.env.user.id)]
        return action

    def action_open_nominations(self):
        self.ensure_one()
        return self.env.ref('employee_development_system.action_eds_nomination').read()[0]

    def action_open_idps(self):
        self.ensure_one()
        action = self.env.ref('employee_development_system.action_eds_idp').read()[0]
        if self.role_persona == 'employee':
            action['domain'] = [('employee_id.user_id', '=', self.env.user.id)]
        return action

    def action_open_sponsorships(self):
        self.ensure_one()
        action = self.env.ref('employee_development_system.action_eds_sponsorship').read()[0]
        if self.role_persona == 'employee':
            action['domain'] = [('employee_id.user_id', '=', self.env.user.id)]
        return action
