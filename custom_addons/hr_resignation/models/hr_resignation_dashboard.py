# -*- coding: utf-8 -*-
from odoo import models, api

class HrResignationDashboard(models.AbstractModel):
    _name = 'hr.resignation.dashboard'
    _description = 'HR Resignation Dashboard'

    @api.model
    def get_dashboard_data(self):
        Resignation = self.env['hr.resignation']
        Settlement = self.env['hr.resignation.settlement']

        # Metrics
        total_requests = Resignation.search_count([])
        draft_requests = Resignation.search_count([('state', 'in', ['draft', 'submitted'])])
        manager_reviewed = Resignation.search_count([('state', '=', 'submitted')]) # 'submitted' is waiting for HR, meaning manager already saw it if they needed to
        approved_count = Resignation.search_count([('state', 'in', ['approved', 'release_date_set', 'handover_completed'])])
        clearance_in_progress = Resignation.search_count([('state', '=', 'clearance_in_progress')])
        cleared_awaiting_settlement = Resignation.search_count([('state', '=', 'cleared')])
        completed_requests = Resignation.search_count([('state', '=', 'completed')])

        # Settlement metrics (settlement records)
        settlement_in_progress = Settlement.search_count([('state', 'in', ['draft', 'waiting_audit'])])
        waiting_payment = Settlement.search_count([('state', '=', 'waiting_payment')])

        Clearance = self.env['hr.resignation.clearance']
        pending_clearances = Clearance.search([('state', '=', 'pending')])
        pending_clearances._compute_is_overdue() # Force SLA check update in DB
        overdue_clearances = Clearance.search_count([('is_overdue', '=', True), ('state', '=', 'pending')])

        # Charts Data

        # 1. Pie Chart: Resignations by Type
        pie_data = []
        pie_labels = []
        all_types = self.env['hr.separation.type'].search([])
        types_group = Resignation._read_group(
            domain=[],
            groupby=['resignation_type_id'],
            aggregates=['__count'],
        )
        type_counts = {rtype.id: count for (rtype, count) in types_group if rtype}

        for rtype in all_types:
            pie_labels.append(rtype.name)
            pie_data.append(type_counts.get(rtype.id, 0))

        # 2. Bar Chart: Resignations by Department (top 10)
        bar_data = []
        bar_labels = []
        depts_group = Resignation._read_group(
            domain=[],
            groupby=['department_id'],
            aggregates=['__count'],
            order='__count desc',
            limit=10,
        )
        for (department, count) in depts_group:
            bar_labels.append(department.name if department else 'No Department')
            bar_data.append(count)

        # 3. Bar Chart: Pending Clearances by Work Unit (Bottlenecks)
        clearance_bar_data = []
        clearance_bar_labels = []
        clearance_bottlenecks = []
        work_unit_group = Clearance._read_group(
            domain=[('state', '=', 'pending')],
            groupby=['work_unit_id'],
            aggregates=['__count'],
            order='__count desc',
            limit=5,
        )
        for (wu, count) in work_unit_group:
            clearance_bar_labels.append(wu.name if wu else 'Unknown')
            clearance_bar_data.append(count)
            if wu:
                clearance_bottlenecks.append({
                    'id': wu.id,
                    'name': wu.name,
                    'pending_count': count,
                })

        # 4. Recent Resignations for Dashboard Table
        recent_resignations = []
        for r in Resignation.search([], order='id desc', limit=10):
            # SLA status
            clearance_pending = r.clearance_line_ids.filtered(lambda c: c.state == 'pending')
            if any(c.is_overdue for c in clearance_pending):
                sla_status = 'overdue'
            elif r.state in ['cleared', 'completed']:
                sla_status = 'completed'
            elif r.state in ['clearance_in_progress']:
                sla_status = 'in_progress'
            else:
                sla_status = 'normal'

            state_labels = dict(r._fields['state'].selection)
            recent_resignations.append({
                'id': r.id,
                'name': r.name or f'RES/{r.id}',
                'employee_name': r.employee_id.name or 'Unknown',
                'job_title': r.job_id.name or (r.employee_id.job_id.name if r.employee_id.job_id else ''),
                'department': r.department_id.name or 'No Department',
                'resignation_type': r.resignation_type_id.name or 'Resignation',
                'expected_date': str(r.release_date or r.expected_last_day) if r.release_date or r.expected_last_day else '',
                'state': r.state,
                'state_label': state_labels.get(r.state, r.state.title() if r.state else ''),
                'sla_status': sla_status,
            })

        return {
            'stats': {
                'total_requests': total_requests,
                'draft_requests': draft_requests,
                'manager_reviewed': manager_reviewed,
                'approved': approved_count,
                'clearance_in_progress': clearance_in_progress,
                'cleared_awaiting_settlement': cleared_awaiting_settlement,
                'settlement_in_progress': settlement_in_progress,
                'completed_requests': completed_requests,
                'waiting_payment': waiting_payment,
                'overdue_clearances': overdue_clearances,
            },
            'charts': {
                'pie': {
                    'labels': pie_labels,
                    'data': pie_data,
                },
                'bar': {
                    'labels': bar_labels,
                    'data': bar_data,
                },
                'clearance_bar': {
                    'labels': clearance_bar_labels,
                    'data': clearance_bar_data,
                }
            },
            'recent_resignations': recent_resignations,
            'clearance_bottlenecks': clearance_bottlenecks,
        }