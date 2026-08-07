# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrAttendanceFlagWizard(models.TransientModel):
    """
    / FR-Wizard for flagging an attendance record for discipline review.
    Allows a supervisor or HR officer to provide a mandatory reason before flagging.
    After saving, the wizard marks the attendance record and optionally pre-creates
    a discipline case for HR review.
    """
    _name = 'hr.attendance.flag.wizard'
    _description = 'Flag Attendance for Discipline Review'

    attendance_id = fields.Many2one(
        'hr.attendance',
        string='Attendance Record',
        required=True,
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='attendance_id.employee_id',
        readonly=True,
    )
    check_in = fields.Datetime(
        string='Check-in Time',
        related='attendance_id.check_in',
        readonly=True,
    )
    flag_reason = fields.Text(
        string='Reason for Flagging',
        required=True,
        help='Provide a clear reason for flagging this attendance for discipline review.',
    )
    create_discipline_case = fields.Boolean(
        string='Also Create Discipline Case',
        default=False,
        help='If checked, a draft discipline case will be pre-created for HR to review.',
    )

    def action_confirm_flag(self):
        """Mark the attendance record as flagged and optionally create a discipline case."""
        self.ensure_one()
        att = self.attendance_id
        if not att:
            raise UserError(_('No attendance record linked to this flag.'))

        att.write({
            'flagged_for_discipline': True,
            'flagged_reason': self.flag_reason,
            'flagged_by_id': self.env.user.id,
            'flagged_date': fields.Datetime.now(),
        })

        # Log in chatter if attendance has tracking
        if hasattr(att, 'message_post'):
            att.message_post(
                body=_('Flagged for discipline review by %s: %s') % (self.env.user.name, self.flag_reason)
            )

        if self.create_discipline_case and self.env.get('discipline.case'):
            case = self.env['discipline.case'].sudo()._create_from_attendance(
                att.employee_id.id,
                'lateness',  # Generic — HR can change offense after case is created
                att.id
            )
            if case:
                return {
                    'name': _('Discipline Case Created'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'discipline.case',
                    'res_id': case.id,
                    'view_mode': 'form',
                    'target': 'current',
                }

        return {'type': 'ir.actions.act_window_close'}
