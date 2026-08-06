# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrAttendanceManualWizard(models.TransientModel):
    """
    ATT-016 / FR-ATT-016: Dedicated Manual Attendance Creation Wizard.
    Allows HR officers and supervisors to create manual attendance records for
    employees who were unable to check in electronically.
    Requires mandatory justification and supervisor sign-off.
    """
    _name = 'hr.attendance.manual.wizard'
    _description = 'Manual Attendance Entry Wizard'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        domain="[('active', '=', True)]",
    )
    work_date = fields.Date(
        string='Attendance Date',
        required=True,
        default=fields.Date.context_today,
    )
    check_in = fields.Datetime(
        string='Check-In Time',
        required=True,
    )
    check_out = fields.Datetime(
        string='Check-Out Time',
    )
    justification = fields.Text(
        string='Reason / Justification',
        required=True,
        help='Mandatory explanation for why manual attendance entry is required.',
    )
    attendance_reason_ids = fields.Many2many(
        'hr.attendance.reason',
        string='Attendance Reasons',
    )

    @api.onchange('work_date')
    def _onchange_work_date(self):
        if self.work_date:
            import datetime
            import pytz
            # Default check_in to 08:00 AM local time on selected date
            local_tz = pytz.timezone('Africa/Addis_Ababa')
            local_dt_in = local_tz.localize(datetime.datetime.combine(self.work_date, datetime.time(8, 0)))
            local_dt_out = local_tz.localize(datetime.datetime.combine(self.work_date, datetime.time(17, 0)))
            self.check_in = local_dt_in.astimezone(pytz.utc).replace(tzinfo=None)
            self.check_out = local_dt_out.astimezone(pytz.utc).replace(tzinfo=None)

    def action_create_manual_attendance(self):
        """ATT-016: Create acknowledged manual attendance record."""
        self.ensure_one()
        if self.check_out and self.check_out <= self.check_in:
            raise ValidationError(_('Check-Out time must be strictly after Check-In time.'))

        vals = {
            'employee_id': self.employee_id.id,
            'check_in': self.check_in,
            'check_out': self.check_out if self.check_out else False,
            'is_acknowledged': True,
            'acknowledged_by': self.env.user.id,
            'acknowledged_date': fields.Datetime.now(),
            'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
        }

        att = self.env['hr.attendance'].sudo().create(vals)

        # Log justification in chatter
        if hasattr(att, 'message_post'):
            att.message_post(
                body=_('Manual attendance created by %s. Justification: %s') % (
                    self.env.user.name, self.justification
                )
            )

        return {
            'name': _('Manual Attendance Created'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.attendance',
            'res_id': att.id,
            'view_mode': 'form',
            'target': 'current',
        }
