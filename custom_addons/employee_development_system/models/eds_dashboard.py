# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    reporting_year = fields.Char(string='Reporting Year', compute='_compute_role_data')
    reporting_company = fields.Char(string='Reporting Company', compute='_compute_role_data')

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
    bank_attendance_records_count = fields.Integer(string='Bank Attendance Records', compute='_compute_role_data')

    issued_certificates_count = fields.Integer(string='Issued Certificates', compute='_compute_role_data')
    avg_level1_satisfaction = fields.Float(string='Avg L1 Satisfaction %', compute='_compute_role_data')
    avg_level2_learning_gain = fields.Float(string='Avg L2 Learning Gain %', compute='_compute_role_data')

    # ══════════════════════════════════════════════════════════════════════════
    # 2. Line Manager KPIs (Team & Unit View)
    # ══════════════════════════════════════════════════════════════════════════
    team_members_count = fields.Integer(string='Team Members', compute='_compute_role_data')
    team_tna_submissions = fields.Integer(string='Team TNA Needs', compute='_compute_role_data')
    pending_team_nominations = fields.Integer(string='Pending Team Invitations', compute='_compute_role_data')
    upcoming_team_sessions = fields.Integer(string='Team Upcoming Sessions', compute='_compute_role_data')
    team_avg_attendance = fields.Float(string='Team Attendance Rate %', compute='_compute_role_data')
    team_attendance_records_count = fields.Integer(string='Team Attendance Records', compute='_compute_role_data')
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
    my_attendance_records_count = fields.Integer(string='My Attendance Records', compute='_compute_role_data')
    my_certificates_count = fields.Integer(string='My Certificates', compute='_compute_role_data')
    my_active_idps_count = fields.Integer(string='My Active IDPs', compute='_compute_role_data')
    my_sponsorships_count = fields.Integer(string='My Sponsorships', compute='_compute_role_data')

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

    @api.model
    def _aggregate(self, model_name, domain, aggregate):
        rows = self.env[model_name].sudo()._read_group(domain, [], [aggregate])
        return (rows[0][0] or 0.0) if rows else 0.0

    @api.model
    def _attendance_stats(self, domain):
        rows = self.env['eds.session.attendance'].sudo()._read_group(
            domain, ['attended'], ['__count'])
        counts = {attended: count for attended, count in rows}
        total = sum(counts.values())
        return (100.0 * counts.get(True, 0) / total if total else 0.0, total)

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_role_data(self):
        persona, company, year, employee_id, team_ids = self._scope()
        start, end = '%s-01-01' % year, '%s-01-01' % (int(year) + 1)
        company_domain = [('company_id', '=', company.id)]
        tna_domain = company_domain + [('cycle_id.year', '=', year)]
        session_domain = company_domain + [('date_start', '>=', start), ('date_start', '<', end)]
        enrollment_domain = company_domain + [
            ('session_id.date_start', '>=', start), ('session_id.date_start', '<', end)]
        attendance_domain = company_domain + [
            ('attendance_date', '>=', start), ('attendance_date', '<', end)]
        cert_domain = [('employee_id.company_id', '=', company.id),
                       ('issue_date', '>=', start), ('issue_date', '<', end)]
        values = {name: 0 for name in (
            'total_tna_entries', 'approved_tna_entries', 'converted_tna_entries',
            'total_budget_allocated', 'total_budget_spent', 'budget_utilization_pct',
            'active_sessions_count', 'completed_sessions_count', 'total_enrolled_participants',
            'bank_avg_attendance_pct', 'bank_attendance_records_count',
            'issued_certificates_count', 'avg_level1_satisfaction',
            'avg_level2_learning_gain', 'team_members_count', 'team_tna_submissions',
            'pending_team_nominations', 'upcoming_team_sessions', 'team_avg_attendance',
            'team_attendance_records_count',
            'team_certificates_count', 'team_active_idps', 'my_tna_needs_count',
            'my_approved_needs_count', 'my_enrolled_sessions_count', 'my_attended_hours',
            'my_attendance_rate', 'my_attendance_records_count',
            'my_certificates_count', 'my_active_idps_count',
            'my_sponsorships_count')}
        Tna = self.env['eds.tna.entry'].sudo()
        Enrollment = self.env['eds.enrollment'].sudo()
        Session = self.env['eds.session'].sudo()
        Certificate = self.env['eds.certificate'].sudo()
        Idp = self.env['eds.idp'].sudo()

        if persona == 'admin':
            valid_tna = tna_domain + [('state', 'in', ('submitted', 'validated', 'approved', 'converted'))]
            values['total_tna_entries'] = Tna.search_count(valid_tna)
            values['approved_tna_entries'] = Tna.search_count(
                tna_domain + [('state', 'in', ('approved', 'converted'))])
            values['converted_tna_entries'] = Tna.search_count(tna_domain + [('state', '=', 'converted')])
            plan_domain = company_domain + [('fiscal_year', '=like', year + '%'),
                                            ('state', 'in', ('published', 'amended'))]
            values['total_budget_allocated'] = self._aggregate(
                'eds.annual.plan', plan_domain, 'budget_total:sum')
            # Group paid costs by currency and payment day. Historical paid
            # records without a payment_date use their last recorded day.
            cost_domain = [
                ('session_id.company_id', '=', company.id),
                ('session_id.plan_line_id.plan_id.fiscal_year', '=like', year + '%'),
                ('session_id.plan_line_id.plan_id.state', 'in', ('published', 'amended')),
                ('payment_state', '=', 'paid'),
            ]
            spent = 0.0
            Costs = self.env['eds.cost'].sudo()
            for extra_domain, day_group in (
                    ([('payment_date', '!=', False)], 'payment_date:day'),
                    ([('payment_date', '=', False)], 'write_date:day')):
                rows = Costs._read_group(cost_domain + extra_domain,
                                         ['currency_id', day_group], ['amount:sum'])
                for currency, day, amount in rows:
                    currency = currency or company.currency_id
                    spent += currency._convert(
                        amount or 0.0, company.currency_id, company,
                        fields.Date.to_date(day) or fields.Date.context_today(self))
            values['total_budget_spent'] = spent
            values['budget_utilization_pct'] = round(
                spent * 100.0 / values['total_budget_allocated'], 1
            ) if values['total_budget_allocated'] else 0.0
            values['active_sessions_count'] = Session.search_count(
                session_domain + [('status', 'in', ('scheduled', 'ongoing', 'rescheduled'))])
            values['completed_sessions_count'] = Session.search_count(
                session_domain + [('status', '=', 'completed')])
            values['total_enrolled_participants'] = Enrollment.search_count(
                enrollment_domain + [('state', 'in', ('enrolled', 'completed'))])
            rate, count = self._attendance_stats(attendance_domain)
            values['bank_avg_attendance_pct'] = round(rate, 1)
            values['bank_attendance_records_count'] = count
            values['issued_certificates_count'] = Certificate.search_count(
                cert_domain + [('state', '=', 'issued')])
            evaluation_domain = [('session_id.company_id', '=', company.id),
                                 ('session_id.date_start', '>=', start),
                                 ('session_id.date_start', '<', end)]
            values['avg_level1_satisfaction'] = round(self._aggregate(
                'eds.evaluation.level1', evaluation_domain +
                [('state', 'in', ('submitted', 'consolidated'))], 'overall_score:avg'), 1)
            values['avg_level2_learning_gain'] = round(self._aggregate(
                'eds.evaluation.level2', evaluation_domain +
                [('state', '=', 'evaluated')], 'learning_gain:avg'), 1)

        elif persona == 'manager':
            values['team_members_count'] = len(team_ids)
            if team_ids:
                team_tna = tna_domain + [('state', 'in',
                    ('submitted', 'validated', 'approved', 'converted')),
                    '|', ('employee_id', 'in', team_ids),
                    '&', ('request_level', '=', 'work_unit'), ('submitted_by', '=', self.env.uid)]
                values['team_tna_submissions'] = Tna.search_count(team_tna)
                values['pending_team_nominations'] = Enrollment.search_count(
                    enrollment_domain + [('employee_id', 'in', team_ids), ('state', '=', 'invited')])
                values['upcoming_team_sessions'] = Session.search_count(
                    session_domain + [('status', 'in', ('scheduled', 'ongoing', 'rescheduled')),
                                      ('enrollment_ids.employee_id', 'in', team_ids)])
                rate, count = self._attendance_stats(
                    attendance_domain + [('employee_id', 'in', team_ids)])
                values['team_avg_attendance'] = round(rate, 1)
                values['team_attendance_records_count'] = count
                values['team_certificates_count'] = Certificate.search_count(
                    cert_domain + [('employee_id', 'in', team_ids), ('state', '=', 'issued')])
                values['team_active_idps'] = Idp.search_count(
                    company_domain + [('year', '=', year), ('employee_id', 'in', team_ids),
                                      ('state', 'in', ('approved', 'in_progress'))])

        elif employee_id:
            own_tna = tna_domain + [('employee_id', '=', employee_id)]
            values['my_tna_needs_count'] = Tna.search_count(own_tna)
            values['my_approved_needs_count'] = Tna.search_count(
                own_tna + [('state', 'in', ('approved', 'converted'))])
            values['my_enrolled_sessions_count'] = Enrollment.search_count(
                enrollment_domain + [('employee_id', '=', employee_id),
                                     ('state', 'in', ('enrolled', 'completed'))])
            own_attendance = attendance_domain + [('employee_id', '=', employee_id)]
            values['my_attended_hours'] = round(self._aggregate(
                'eds.session.attendance', own_attendance + [('attended', '=', True)],
                'hours_attended:sum'), 1)
            rate, count = self._attendance_stats(own_attendance)
            values['my_attendance_rate'] = round(rate, 1)
            values['my_attendance_records_count'] = count
            values['my_certificates_count'] = Certificate.search_count(
                cert_domain + [('employee_id', '=', employee_id), ('state', '=', 'issued')])
            values['my_active_idps_count'] = Idp.search_count(
                company_domain + [('year', '=', year), ('employee_id', '=', employee_id),
                                  ('state', 'in', ('draft', 'submitted', 'approved', 'in_progress'))])
            values['my_sponsorships_count'] = self.env['eds.sponsorship'].sudo().search_count(
                [('employee_id', '=', employee_id), ('employee_id.company_id', '=', company.id)])

        for rec in self:
            rec.role_persona = persona
            rec.is_admin = persona == 'admin'
            rec.is_manager = persona == 'manager'
            rec.is_employee = persona == 'employee'
            rec.reporting_year = year
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
        persona, company, year, employee_id, team_ids = self._scope()
        own_action = persona == 'employee'
        action_xmlid = ('action_eds_tna_entry_own' if own_action else 'action_eds_tna_entry')
        action = self.env.ref('employee_development_system.' + action_xmlid).read()[0]
        domain = [('company_id', '=', company.id), ('cycle_id.year', '=', year)]
        if persona == 'manager':
            domain += [('state', '!=', 'draft'), '|', ('employee_id', 'in', team_ids),
                       '&', ('request_level', '=', 'work_unit'), ('submitted_by', '=', self.env.uid)]
        elif persona == 'employee':
            domain += [('employee_id', '=', employee_id)] if employee_id else [('id', '=', 0)]
        action['domain'] = domain
        if persona == 'manager':
            action['name'] = _('Team Training Needs')
            action['context'] = {}
        return action

    def action_open_sessions(self):
        self.ensure_one()
        persona, company, year, employee_id, team_ids = self._scope()
        if persona == 'admin':
            action = self.env.ref('employee_development_system.action_eds_session').read()[0]
            action['domain'] = [('company_id', '=', company.id),
                                ('date_start', '>=', year + '-01-01'),
                                ('date_start', '<', str(int(year) + 1) + '-01-01')]
        else:
            action = self.env.ref('employee_development_system.action_eds_enrollment').read()[0]
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            action['domain'] = [('company_id', '=', company.id), ('employee_id', 'in', ids),
                                ('session_id.date_start', '>=', year + '-01-01'),
                                ('session_id.date_start', '<', str(int(year) + 1) + '-01-01')]
            action['name'] = _('Team Sessions') if persona == 'manager' else _('My Sessions')
        return action

    def action_open_annual_plans(self):
        self.ensure_one()
        persona, company, year, _employee_id, _team_ids = self._scope()
        if persona != 'admin':
            raise UserError(_('Annual plans are available to L&D staff and executives.'))
        action = self.env.ref('employee_development_system.action_eds_annual_plan').read()[0]
        action['domain'] = [('company_id', '=', company.id), ('fiscal_year', '=like', year + '%')]
        return action

    def action_open_certificates(self):
        self.ensure_one()
        persona, company, year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_certificate').read()[0]
        domain = [('employee_id.company_id', '=', company.id),
                  ('issue_date', '>=', year + '-01-01'),
                  ('issue_date', '<', str(int(year) + 1) + '-01-01')]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action

    def action_open_nominations(self):
        self.ensure_one()
        persona, company, year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_enrollment').read()[0]
        domain = [('company_id', '=', company.id),
                  ('session_id.date_start', '>=', year + '-01-01'),
                  ('session_id.date_start', '<', str(int(year) + 1) + '-01-01')]
        if persona == 'manager':
            domain += [('employee_id', 'in', team_ids), ('state', '=', 'invited')]
        elif persona == 'employee':
            domain += [('employee_id', '=', employee_id)] if employee_id else [('id', '=', 0)]
        action['domain'] = domain
        return action

    def action_open_idps(self):
        self.ensure_one()
        persona, company, year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_idp').read()[0]
        domain = [('company_id', '=', company.id), ('year', '=', year)]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action

    def action_open_sponsorships(self):
        self.ensure_one()
        persona, company, _year, employee_id, team_ids = self._scope()
        action = self.env.ref('employee_development_system.action_eds_sponsorship').read()[0]
        domain = [('employee_id.company_id', '=', company.id)]
        if persona != 'admin':
            ids = team_ids if persona == 'manager' else ([employee_id] if employee_id else [])
            domain.append(('employee_id', 'in', ids))
        action['domain'] = domain
        return action
