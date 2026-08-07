from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime, time
import pytz
import logging

_logger = logging.getLogger(__name__)


class AttendancePreApproval(models.Model):
    _name = 'attendance.preapproval'
    _description = 'Predefined Attendance Exception'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'employee_id'

    active = fields.Boolean(string="Active", default=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        required=True,
        index=True,
        default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1),
        domain=lambda self: [('user_id', '=', self.env.uid)]
    )
    exception_type = fields.Selection([
        ('predefined_late', 'Pre-Defined Lateness'),
        ('predefined_early_exit', 'Pre-Defined Early Exit')
    ], required=True, index=True)

    approval_reason = fields.Text(required=True)
    date = fields.Date(required=True, index=True)
    start_time = fields.Float(required=True)
    end_time = fields.Float(required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='draft', tracking=True, index=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    approved_by = fields.Many2one('res.users', string="Approved By", readonly=True)
    time_range = fields.Char(compute='_compute_time_range', store=True)
    is_manager_or_admin = fields.Boolean(
        compute='_compute_is_manager_or_admin',
        string="Is Manager or Admin"
    )

    @api.depends('employee_id')
    def _compute_is_manager_or_admin(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_uid = self.env.uid
        for rec in self:
            if is_admin:
                rec.is_manager_or_admin = True
            else:
                emp = rec.employee_id.sudo() if rec.employee_id else False
                is_manager = False
                if emp:
                    parent_user_id = emp.parent_id.sudo().user_id.id if (emp.parent_id and emp.parent_id.user_id) else False
                    coach_user_id = emp.coach_id.sudo().user_id.id if (emp.coach_id and emp.coach_id.user_id) else False
                    if (parent_user_id and parent_user_id == current_uid) or (coach_user_id and coach_user_id == current_uid):
                        is_manager = True
                rec.is_manager_or_admin = is_manager

    @api.depends('create_uid')
    def _compute_employee_id(self):
        for rec in self:
            employee = self.env['hr.employee'].search([
                ('user_id', '=', rec.create_uid.id)
            ], limit=1)
            rec.employee_id = employee

    # ---------------------------
    # Utilities
    # ---------------------------
    @staticmethod
    def _float_to_time(float_time):
        h = int(float_time)
        m = int(round((float_time - h) * 60))
        return time(h, m)

    @api.depends('start_time', 'end_time')
    def _compute_time_range(self):
        for rec in self:
            start = rec._float_to_time(rec.start_time)
            end = rec._float_to_time(rec.end_time)
            rec.time_range = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    # ---------------------------
    # Validations
    # ---------------------------
    @api.constrains('date', 'start_time', 'end_time')
    def _check_time_validity(self):

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        now = datetime.now(user_tz)
        today = now.date()
        current_time_float = now.hour + now.minute / 60.0

        for rec in self:
            _logger.info(f"Validating attendance for {rec.employee_id.name} on {rec.date}")

            if rec.start_time < 0 or rec.end_time < 0:
                raise ValidationError("Start and end times must be positive.")

            if rec.end_time <= rec.start_time:
                raise ValidationError("End time must be greater than start time.")

            if (rec.end_time - rec.start_time) > 4:
                raise ValidationError("Maximum allowed window is 4 hours.")

            if rec.date < today:
                raise ValidationError("Past date not allowed.")

            if rec.date == today:
                if rec.start_time < current_time_float:
                    raise ValidationError("Start time cannot be in the past.")
                if rec.end_time < current_time_float:
                    raise ValidationError("End time cannot be in the past.")
             # Overlap protection
            conflict = self.search([
                        ('id', '!=', rec.id),
                        ('employee_id', '=', rec.employee_id.id),
                        ('date', '=', rec.date),
                        ('state', '!=', 'rejected'),
                        ('start_time', '<', rec.end_time),
                        ('end_time', '>', rec.start_time)
                    ], limit=1)

            if conflict:
                raise ValidationError("This time window overlaps with another pre-approval.")

    # ---------------------------
    # Workflow
    # ---------------------------
    def action_submit(self):
        self.write({'state': 'requested'})

    def action_approve(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_uid = self.env.uid
        for rec in self:
            if rec.create_uid.id == current_uid and not is_admin:
                raise ValidationError("You are not allowed to approve your own request.")
            emp = rec.employee_id
            is_manager = False
            if emp:
                if emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == current_uid:
                    is_manager = True
                elif emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == current_uid:
                    is_manager = True

            if not (is_admin or is_manager):
                raise ValidationError("Only the employee's manager or an administrator can approve this request.")

            rec.write({
                'state': 'approved',
                'approved_by': current_uid
            })

    def action_reject(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_uid = self.env.uid
        for rec in self:
            emp = rec.employee_id
            is_manager = False
            if emp:
                if emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == current_uid:
                    is_manager = True
                elif emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == current_uid:
                    is_manager = True

            if not (is_admin or is_manager):
                raise ValidationError("Only the employee's manager or an administrator can reject this request.")

            rec.write({'state': 'rejected'})

    def write(self, vals):
        for rec in self:
            if rec.state == 'approved':
                raise ValidationError("Approved records cannot be modified.")
        return super().write(vals)
