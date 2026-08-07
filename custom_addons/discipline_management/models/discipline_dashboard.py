# -*- coding: utf-8 -*-
from odoo import models, api, fields
from datetime import date, timedelta


class DisciplineCaseDashboard(models.Model):
    _inherit = 'discipline.case'

    @api.model
    def get_dashboard_data(self):
        """Returns aggregated data for the Discipline Management Dashboard."""
        today = fields.Date.context_today(self)
        first_of_month = today.replace(day=1)

        # ---- Case Counts ----
        total_cases = self.search_count([])
        active_cases = self.search_count([
            ('state', 'in', ['initiated', 'investigating', 'committee_review', 'pending_approval'])
        ])
        pending_approval = self.search_count([('state', '=', 'pending_approval')])
        sla_breached = self.search_count([('is_sla_exceeded', '=', True)])
        level1_cases = self.search_count([('severity_level', '=', 'level_1')])
        level2_cases = self.search_count([('severity_level', '=', 'level_2')])
        level3_cases = self.search_count([('severity_level', '=', 'level_3')])
        level4_cases = self.search_count([('severity_level', '=', 'level_4')])
        level5_cases = self.search_count([('severity_level', '=', 'level_5')])
        revoked_cases = self.search_count([('state', '=', 'revoked')])
        enforced_this_month = self.search_count([
            ('state', '=', 'enforced'),
            ('final_decision_date', '>=', first_of_month),
        ])

        # ---- Related Model Counts ----
        inv_model = self.env.get('discipline.investigation')
        # FR-BUG-DIS1: discipline.investigation valid states: draft/submitted/approved
        investigations = inv_model.search_count([('state', '!=', 'approved')]) if inv_model else 0

        comm_model = self.env.get('discipline.committee.meeting')
        # FR-BUG-DIS1: discipline.committee.meeting valid terminal state: 'completed' (not 'concluded')
        committee_meetings = comm_model.search_count([
            ('state', 'not in', ['completed', 'cancelled'])
        ]) if comm_model else 0

        susp_model = self.env.get('discipline.suspension')
        active_suspensions = susp_model.search_count([
            ('state', 'in', ['active', 'extended'])
        ]) if susp_model else 0

        appeal_model = self.env.get('discipline.appeal')
        pending_appeals = appeal_model.search_count([
            ('state', 'in', ['submitted', 'under_review'])
        ]) if appeal_model else 0

        payroll_model = self.env.get('discipline.payroll.penalty')
        payroll_penalties = payroll_model.search_count([
            ('state', '=', 'pending')
        ]) if payroll_model else 0

        # ---- Recent Cases ----
        recent_case_ids = self.search([], limit=10, order='incident_date desc, id desc')
        recent_cases = []
        for case in recent_case_ids:
            recent_cases.append({
                'id': case.id,
                'name': case.name,
                'employee_id': [case.employee_id.id, case.employee_id.name] if case.employee_id else [False, '—'],
                'severity_level': case.severity_level,
                'state': case.state,
                'incident_date': str(case.incident_date) if case.incident_date else False,
                'sla_deadline': str(case.sla_deadline) if case.sla_deadline else False,
                'is_sla_exceeded': case.is_sla_exceeded,
            })

        return {
            'stats': {
                'total_cases': total_cases,
                'active_cases': active_cases,
                'pending_approval': pending_approval,
                'sla_breached': sla_breached,
                'investigations': investigations,
                'committee_meetings': committee_meetings,
                'active_suspensions': active_suspensions,
                'pending_appeals': pending_appeals,
                'payroll_penalties': payroll_penalties,
                'level1_cases': level1_cases,
                'level2_cases': level2_cases,
                'level3_cases': level3_cases,
                'level4_cases': level4_cases,
                'level5_cases': level5_cases,
                'revoked_cases': revoked_cases,
                'enforced_this_month': enforced_this_month,
            },
            'recent_cases': recent_cases,
        }
