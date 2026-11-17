# -*- coding: utf-8 -*-
from odoo import models, api, fields


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_validate(self):
        """When a Time Off / Leave request is officially approved (validated),
        automatically re-evaluate any open attendance disciplinary cases for this
        employee overlapping the approved leave dates and reconcile or downgrade them."""
        res = super().action_validate()
        AttCase = self.env['discipline.attendance.case'].sudo()
        for leave in self:
            if not leave.employee_id or not leave.date_from or not leave.date_to:
                continue
            l_start = leave.date_from.date() if hasattr(leave.date_from, 'date') else leave.date_from
            l_end = leave.date_to.date() if hasattr(leave.date_to, 'date') else leave.date_to
            cases = AttCase.search([
                ('employee_id', '=', leave.employee_id.id),
                ('state', 'in', ['draft', 'coach_review', 'director_review', 'pomd_review']),
                ('date_from', '<=', l_end),
                ('date_to', '>=', l_start),
            ])
            for case in cases:
                try:
                    case.action_recheck_leave_coverage(silent=True)
                except Exception:
                    pass
        return res

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') in ('validate', 'validate1') or vals.get('leave_request_status') == 'approved':
            AttCase = self.env['discipline.attendance.case'].sudo()
            for leave in self:
                if not leave.employee_id or not leave.date_from or not leave.date_to:
                    continue
                l_start = leave.date_from.date() if hasattr(leave.date_from, 'date') else leave.date_from
                l_end = leave.date_to.date() if hasattr(leave.date_to, 'date') else leave.date_to
                cases = AttCase.search([
                    ('employee_id', '=', leave.employee_id.id),
                    ('state', 'in', ['draft', 'coach_review', 'director_review', 'pomd_review']),
                    ('date_from', '<=', l_end),
                    ('date_to', '>=', l_start),
                ])
                for case in cases:
                    try:
                        case.action_recheck_leave_coverage(silent=True)
                    except Exception:
                        pass
        return res
