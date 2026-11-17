# -*- coding: utf-8 -*-
from datetime import datetime, time
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineAttendanceActionWizard(models.TransientModel):
    _name = 'discipline.attendance.action.wizard'
    _description = 'Attendance Case Action Wizard (Leave Adjustment, Coach Exoneration & Batch HR Refusal)'

    action_type = fields.Selection([
        ('adjust_leave', 'Convert / Adjust Absent Days by Leave'),
        ('coach_exonerate', 'Acknowledge / Exonerate with Justification (Coach)'),
        ('hr_refuse', 'Refuse Attendance Case(s) (HR / POMD)'),
    ], string='Action Type', required=True, default='coach_exonerate')

    attendance_case_ids = fields.Many2many(
        'discipline.attendance.case',
        'discipline_att_case_action_wiz_rel',
        'wizard_id',
        'case_id',
        string='Selected Attendance Cases',
        required=True,
    )
    case_count = fields.Integer(compute='_compute_case_count', string='Selected Cases Count')
    employee_id = fields.Many2one('hr.employee', string='Employee')

    # Leave Conversion Fields
    leave_mode = fields.Selection([
        ('existing', 'Link Existing Time Off / Leave Record'),
        ('create_new', 'Create & Submit New Time Off Request for Absent Dates'),
        ('manual_adjust', 'Direct Leave Adjustment (Administrative / Coach Confirmation)'),
    ], string='Leave Adjustment Method', default='create_new')

    leave_id = fields.Many2one(
        'hr.leave',
        string='Existing Leave Record',
        domain="[('employee_id', '=', employee_id)]",
    )
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        help='Select the Leave / Time Off Type to cover the unexcused absent dates.',
    )
    leave_date_from = fields.Date(string='Leave Start Date', default=fields.Date.context_today)
    leave_date_to = fields.Date(string='Leave End Date', default=fields.Date.context_today)

    reason_notes = fields.Text(
        string='Justification / Refusal Reason',
        required=True,
        help='Provide detailed justification for leave adjustment, coach exoneration, or HR refusal.',
    )

    @api.depends('attendance_case_ids')
    def _compute_case_count(self):
        for rec in self:
            rec.case_count = len(rec.attendance_case_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids')
        if active_ids and self.env.context.get('active_model') == 'discipline.attendance.case' and not res.get('attendance_case_ids'):
            res['attendance_case_ids'] = [(6, 0, active_ids)]
            cases = self.env['discipline.attendance.case'].browse(active_ids)
            if len(cases) == 1:
                res['employee_id'] = cases.employee_id.id
                res['leave_date_from'] = cases.date_from
                res['leave_date_to'] = cases.date_to
        if 'holiday_status_id' in fields_list and not res.get('holiday_status_id'):
            LeaveType = self.env.get('hr.leave.type')
            if LeaveType is not None:
                lt = LeaveType.sudo().search([], limit=1)
                if lt:
                    res['holiday_status_id'] = lt.id
        return res

    def action_confirm(self):
        self.ensure_one()
        cases = self.attendance_case_ids
        if not cases:
            raise UserError(_('No attendance disciplinary cases selected.'))

        if self.action_type == 'hr_refuse':
            cases.action_hr_refuse(refusal_reason=self.reason_notes)
            return {'type': 'ir.actions.act_window_close'}

        if self.action_type == 'coach_exonerate':
            cases.action_coach_exonerate(justification=self.reason_notes)
            return {'type': 'ir.actions.act_window_close'}

        if self.action_type == 'adjust_leave':
            today = fields.Date.context_today(self)
            for case in cases:
                if case.state in ('enforced', 'leave_adjusted', 'exonerated', 'hr_refused'):
                    raise UserError(_('Case %s is already finalized and cannot be adjusted by leave.') % case.name)

                linked_leave = self.leave_id
                if self.leave_mode == 'create_new':
                    if not self.holiday_status_id:
                        raise UserError(_('Please select a Time Off Type to create the leave request.'))
                    if not self.leave_date_from or not self.leave_date_to or self.leave_date_from > self.leave_date_to:
                        raise UserError(_('Please specify a valid Leave Start Date and End Date.'))
                    LeaveModel = self.env['hr.leave'].sudo()
                    leave_vals = {
                        'name': _('Attendance Case %s Adjustment: %s') % (case.name, self.reason_notes),
                        'employee_id': case.employee_id.id,
                        'holiday_status_id': self.holiday_status_id.id,
                        'request_date_from': self.leave_date_from,
                        'request_date_to': self.leave_date_to,
                        'date_from': datetime.combine(self.leave_date_from, time(8, 0, 0)),
                        'date_to': datetime.combine(self.leave_date_to, time(17, 0, 0)),
                    }
                    try:
                        linked_leave = LeaveModel.create(leave_vals)
                    except Exception:
                        # Fallback if custom hr.leave constraints block automatic creation (e.g. insufficient allocation balance)
                        linked_leave = False

                if linked_leave:
                    case.write({
                        'leave_id': linked_leave.id,
                        'justification_reason': self.reason_notes,
                    })
                    case.action_recheck_leave_coverage(silent=True)

                # If manual adjustment or full period covered
                if self.leave_mode == 'manual_adjust' or case.state not in ('leave_adjusted',):
                    covered_days = (
                        (self.leave_date_to - self.leave_date_from).days + 1
                        if (self.leave_date_from and self.leave_date_to)
                        else case.absent_days_count
                    )
                    if self.leave_mode == 'manual_adjust' or covered_days >= (case.absent_days_count or 1):
                        case.write({
                            'state': 'leave_adjusted',
                            'punishment_type': 'leave_adjusted',
                            'penalty_percentage': 0.0,
                            'fine_days': 0.0,
                            'covered_leave_days': case.absent_days_count or covered_days,
                            'justification_reason': self.reason_notes,
                            'deduction_status': 'cancelled',
                            'exonerated_by_id': self.env.user.id,
                            'exonerated_date': today,
                        })
                        pending_pens = case.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
                        if pending_pens:
                            pending_pens.write({'state': 'cancelled'})
                        case.message_post(body=Markup(_(
                            '<strong>✅ Attendance Case Adjusted by Leave (%s):</strong><br/>'
                            '• <strong>Adjusted By:</strong> %s<br/>'
                            '• <strong>Leave / Justification:</strong> %s<br/>'
                            '• <strong>Outcome:</strong> Closed as Adjusted by Leave with zero penalty.'
                        ) % (
                            linked_leave.display_name if linked_leave else _('Direct Leave Adjustment'),
                            self.env.user.name,
                            self.reason_notes,
                        )))
            return {'type': 'ir.actions.act_window_close'}
