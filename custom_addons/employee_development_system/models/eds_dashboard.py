# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsDashboard(models.TransientModel):
    """Small, role-scoped snapshot of training work and delivery."""
    _name = 'eds.dashboard'
    _description = 'EDS Role-Adaptive Learning & Development Dashboard'

    name = fields.Char(string='Dashboard Title', default='Employee Development Dashboard')

    # Role Persona Indicator
    role_persona = fields.Selection([
        ('admin', 'L&D Executive & Administrator'),
        ('manager', 'Line Manager / Unit Supervisor'),
        ('employee', 'Employee Self-Service (ESS)'),
    ], string='Role View', compute='_compute_role_data', readonly=True)

    is_admin = fields.Boolean(compute='_compute_role_data')
    is_manager = fields.Boolean(compute='_compute_role_data')
    is_employee = fields.Boolean(compute='_compute_role_data')
    reporting_year = fields.Char(string='Calendar Year', compute='_compute_role_data')
    reporting_fiscal_year = fields.Char(string='Fiscal Year Starting', compute='_compute_role_data')
    reporting_company = fields.Char(string='Reporting Company', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 1. Bank-wide Admin & Executive KPIs
    # ══════════════════════════════════════════════════════════════════════════
    total_tna_entries = fields.Integer(string='Submitted Training Needs', compute='_compute_role_data')
    published_plans_count = fields.Integer(string='Published Annual Plans', compute='_compute_role_data')
    upcoming_sessions_count = fields.Integer(string='Current and Upcoming Sessions', compute='_compute_role_data')
    completed_sessions_count = fields.Integer(string='Completed Sessions', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 2. Line Manager KPIs (Team & Unit View)
    # ══════════════════════════════════════════════════════════════════════════
    team_members_count = fields.Integer(string='Direct Reports', compute='_compute_role_data')
    team_tna_submissions = fields.Integer(string='Submitted Team Needs', compute='_compute_role_data')
    pending_team_nominations = fields.Integer(string='Pending Team Invitations', compute='_compute_role_data')
    team_confirmed_seats = fields.Integer(string='Confirmed Team Seats', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 3. Employee Self-Service (ESS) KPIs
    # ══════════════════════════════════════════════════════════════════════════
    my_tna_needs_count = fields.Integer(string='My Training Needs', compute='_compute_role_data')
    my_pending_invitations = fields.Integer(string='My Pending Invitations', compute='_compute_role_data')
    my_upcoming_sessions = fields.Integer(string='My Confirmed Seats', compute='_compute_role_data')
    my_certificates_count = fields.Integer(string='My Certificates', compute='_compute_role_data')

    _transient_max_hours = 0.5  # Auto-vacuum transient records after 30 minutes

    def _scope(self):
        """One company and one year; never aggregate another company's HR data."""
        user = self.env.user
        employee = user.employee_id
        company = self.env.company
        year = str(fields.Date.context_today(self).year)
        team_ids = (self.env['hr.employee'].sudo().search([
            ('parent_id', '=', employee.id), ('company_id', '=', company.id),
        ]).ids if employee else [])
        staff = any(user.has_group('employee_development_system.' + group) for group in (
            'group_eds_officer', 'group_eds_manager', 'group_eds_admin', 'group_eds_executive'))
        persona = 'admin' if staff else ('manager' if team_ids or user.has_group(
            'employee_development_system.group_eds_line_manager') else 'employee')
        return persona, company, year, employee.id if employee else False, team_ids

    def _metric_domains(self):
        """Use identical filters for dashboard numbers and drill-downs."""
        persona, company, year, employee_id, team_ids = self._scope()
        start = '%s-01-01 00:00:00' % year
        end = '%s-01-01 00:00:00' % (int(year) + 1)
        now = fields.Datetime.now()
        company_domain = [('company_id', '=', company.id)]
        tna = company_domain + [('cycle_id.year', '=', year)]
        submitted_tna = tna + [('state', 'in',
                                ('submitted', 'validated', 'approved', 'converted'))]
        active_session = company_domain + [
            ('date_start', '>=', start), ('date_start', '<', end),
            ('date_end', '>=', now),
            ('status', 'in', ('scheduled', 'ongoing', 'rescheduled'))]
        active_enrollment = company_domain + [
            ('session_id.date_start', '>=', start),
            ('session_id.date_start', '<', end),
            ('session_id.date_end', '>=', now),
            ('session_id.status', 'in', ('scheduled', 'ongoing', 'rescheduled'))]
        pending_enrollment = active_enrollment + [
            ('state', '=', 'invited'), '|',
            ('session_id.response_deadline', '=', False),
            ('session_id.response_deadline', '>=', now)]
        team_tna = submitted_tna + [
            '|', ('employee_id', 'in', team_ids), '&',
            ('request_level', '=', 'work_unit'), ('submitted_by', '=', self.env.uid)]
        return persona, company, year, employee_id, team_ids, {
            'own_tna': tna,
            'submitted_tna': submitted_tna,
            'team_tna': team_tna,
            'published_plans': company_domain + [
                ('fiscal_year', '=like', year + '%'), ('state', '=', 'published')],
            'upcoming_sessions': active_session,
            'completed_sessions': company_domain + [
                ('date_start', '>=', start), ('date_start', '<', end),
                ('status', '=', 'completed')],
            'active_enrollments': active_enrollment,
            'pending_enrollments': pending_enrollment,
            'issued_certificates': [
                ('employee_id.company_id', '=', company.id),
                ('issue_date', '>=', year + '-01-01'),
                ('issue_date', '<', str(int(year) + 1) + '-01-01'),
                ('state', '=', 'issued')],
        }

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_role_data(self):
        persona, company, year, employee_id, team_ids, domains = self._metric_domains()
        values = {name: 0 for name in (
            'total_tna_entries', 'published_plans_count', 'upcoming_sessions_count',
            'completed_sessions_count', 'team_members_count', 'team_tna_submissions',
            'pending_team_nominations', 'team_confirmed_seats', 'my_tna_needs_count',
            'my_pending_invitations', 'my_upcoming_sessions', 'my_certificates_count')}

        if persona == 'admin':
            values['total_tna_entries'] = self.env['eds.tna.entry'].sudo().search_count(
                domains['submitted_tna'])
            values['published_plans_count'] = self.env['eds.annual.plan'].sudo().search_count(
                domains['published_plans'])
            values['upcoming_sessions_count'] = self.env['eds.session'].sudo().search_count(
                domains['upcoming_sessions'])
            values['completed_sessions_count'] = self.env['eds.session'].sudo().search_count(
                domains['completed_sessions'])
        elif persona == 'manager':
            values['team_members_count'] = len(team_ids)
            values['team_tna_submissions'] = self.env['eds.tna.entry'].sudo().search_count(
                domains['team_tna'])
            if team_ids:
                enrollment = self.env['eds.enrollment'].sudo()
                values['pending_team_nominations'] = enrollment.search_count(
                    domains['pending_enrollments'] + [('employee_id', 'in', team_ids)])
                values['team_confirmed_seats'] = enrollment.search_count(
                    domains['active_enrollments'] + [
                        ('employee_id', 'in', team_ids), ('state', '=', 'enrolled')])
        elif employee_id:
            enrollment = self.env['eds.enrollment'].sudo()
            values['my_tna_needs_count'] = self.env['eds.tna.entry'].sudo().search_count(
                domains['own_tna'] + [('employee_id', '=', employee_id)])
            values['my_pending_invitations'] = enrollment.search_count(
                domains['pending_enrollments'] + [('employee_id', '=', employee_id)])
            values['my_upcoming_sessions'] = enrollment.search_count(
                domains['active_enrollments'] + [
                    ('employee_id', '=', employee_id), ('state', '=', 'enrolled')])
            values['my_certificates_count'] = self.env['eds.certificate'].sudo().search_count(
                domains['issued_certificates'] + [('employee_id', '=', employee_id)])

        for rec in self:
            rec.role_persona = persona
            rec.is_admin = persona == 'admin'
            rec.is_manager = persona == 'manager'
            rec.is_employee = persona == 'employee'
            rec.reporting_year = year
            rec.reporting_fiscal_year = year
            rec.reporting_company = company.name
            for field_name, value in values.items():
                rec[field_name] = value
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
        persona, _company, _year, employee_id, _team_ids, domains = self._metric_domains()
        own_action = persona == 'employee'
        action_xmlid = ('action_eds_tna_entry_own' if own_action else 'action_eds_tna_entry')
        action = self.env.ref('employee_development_system.' + action_xmlid).sudo().read()[0]
        if persona == 'manager':
            domain = domains['team_tna']
        elif persona == 'employee':
            domain = domains['own_tna'] + (
                [('employee_id', '=', employee_id)] if employee_id else [('id', '=', 0)])
        else:
            domain = domains['submitted_tna']
        action['domain'] = domain
        if persona == 'manager':
            action['name'] = _('Team Training Needs')
            action['context'] = {}
        return action

    def action_open_sessions(self):
        self.ensure_one()
        persona, _company, _year, employee_id, team_ids, domains = self._metric_domains()
        if persona == 'admin':
            action = self.env.ref('employee_development_system.action_eds_session').sudo().read()[0]
            action['domain'] = domains['upcoming_sessions']
        else:
            action = self.env.ref('employee_development_system.action_eds_enrollment').sudo().read()[0]
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            action['domain'] = domains['active_enrollments'] + [
                ('employee_id', 'in', ids), ('state', '=', 'enrolled')]
            action['name'] = _('Confirmed Team Seats') if persona == 'manager' else _('My Confirmed Seats')
        return action

    def action_open_completed_sessions(self):
        self.ensure_one()
        persona, _company, _year, _employee_id, _team_ids, domains = self._metric_domains()
        if persona != 'admin':
            raise UserError(_('Completed session reports are available to L&D staff and executives.'))
        action = self.env.ref('employee_development_system.action_eds_session').sudo().read()[0]
        action['domain'] = domains['completed_sessions']
        action['name'] = _('Completed Sessions')
        return action

    def action_open_annual_plans(self):
        self.ensure_one()
        persona, _company, _year, _employee_id, _team_ids, domains = self._metric_domains()
        if persona != 'admin':
            raise UserError(_('Annual plans are available to L&D staff and executives.'))
        action = self.env.ref('employee_development_system.action_eds_annual_plan').sudo().read()[0]
        action['domain'] = domains['published_plans']
        return action

    def action_open_certificates(self):
        self.ensure_one()
        persona, _company, _year, employee_id, team_ids, domains = self._metric_domains()
        action = self.env.ref('employee_development_system.action_eds_certificate').sudo().read()[0]
        domain = domains['issued_certificates'][:]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action

    def action_open_nominations(self):
        self.ensure_one()
        persona, _company, _year, employee_id, team_ids, domains = self._metric_domains()
        action = self.env.ref('employee_development_system.action_eds_enrollment').sudo().read()[0]
        domain = domains['pending_enrollments'][:]
        if persona == 'manager':
            domain.append(('employee_id', 'in', team_ids))
        elif persona == 'employee':
            domain += [('employee_id', '=', employee_id)] if employee_id else [('id', '=', 0)]
        action['domain'] = domain
        return action

    def action_open_idps(self):
        self.ensure_one()
        persona, company, year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_idp').sudo().read()[0]
        domain = [('company_id', '=', company.id), ('year', '=', year)]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action

    def action_open_sponsorships(self):
        self.ensure_one()
        persona, company, _year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_sponsorship').sudo().read()[0]
        domain = [('employee_id.company_id', '=', company.id)]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action
