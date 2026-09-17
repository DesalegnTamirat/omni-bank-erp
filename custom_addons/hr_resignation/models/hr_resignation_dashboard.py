# -*- coding: utf-8 -*-
from odoo import models, api

class HrResignationDashboard(models.AbstractModel):
    _name = 'hr.resignation.dashboard'
    _description = 'HR Resignation Dashboard'

    @api.model
    def get_dashboard_data(self):
        Resignation = self.env['hr.resignation']

        # Metrics
        total_requests = Resignation.search_count([])
        draft_requests = Resignation.search_count([('state', 'in', ['draft', 'submitted'])])
        manager_reviewed = Resignation.search_count([('state', '=', 'submitted')]) # 'submitted' is waiting for HR, meaning manager already saw it if they needed to
        hr_approved = Resignation.search_count([('state', 'in', ['hr_approved', 'release_date_set', 'handover_completed'])])
        clearance_in_progress = Resignation.search_count([('state', '=', 'clearance')])
        cleared_awaiting_settlement = Resignation.search_count([('state', '=', 'cleared')])
        completed_requests = Resignation.search_count([('state', 'in', ['settled', 'done'])])

        Clearance = self.env['hr.resignation.clearance']
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

        return {
            'stats': {
                'total_requests': total_requests,
                'draft_requests': draft_requests,
                'manager_reviewed': manager_reviewed,
                'hr_approved': hr_approved,
                'clearance_in_progress': clearance_in_progress,
                'cleared_awaiting_settlement': cleared_awaiting_settlement,
                'completed_requests': completed_requests,
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
            }
        }
