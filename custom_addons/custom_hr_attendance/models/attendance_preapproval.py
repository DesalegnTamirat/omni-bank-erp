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
    @api.model
    def _get_employee_domain(self):
        if self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return []
        current_employee = self.env.user.employee_id
        if not current_employee:
            current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if current_employee:
            return ['|', '|', '|',
                ('user_id', '=', self.env.uid),
                ('parent_id.user_id', '=', self.env.uid),
                ('attendance_manager_id', '=', self.env.uid),
                ('id', 'child_of', current_employee.id)
            ]
        return [('user_id', '=', self.env.uid)]

    def _default_employee_id(self):
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return emp.id if emp else False

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        required=True,
        index=True,
        default=_default_employee_id,
        domain=lambda self: self._get_employee_domain()
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
    # Direct Messaging Helper (Odoo Discuss Direct Chat)
    # ---------------------------
    def _get_manager_user(self, employee):
        if not employee:
            return False
        emp_sudo = employee.sudo()
        if emp_sudo.parent_id and emp_sudo.parent_id.user_id:
            return emp_sudo.parent_id.user_id
        if emp_sudo.coach_id and emp_sudo.coach_id.user_id:
            return emp_sudo.coach_id.user_id
        if emp_sudo.attendance_manager_id:
            return emp_sudo.attendance_manager_id
        return False

    def _send_direct_message(self, sender_user, target_user, html_body):
        """ Posts a Direct Message in Odoo Discuss (1-on-1 Chat Channel) """
        if not sender_user or not target_user or not target_user.partner_id:
            return
        try:
            from markupsafe import Markup
            channel = self.env['discuss.channel'].sudo().with_user(sender_user)._get_or_create_chat(
                partners_to=[target_user.partner_id.id]
            )
            if channel:
                channel.sudo().with_user(sender_user).message_post(
                    body=Markup(html_body),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception as e:
            _logger.warning(f"Could not send direct chat message: {e}")

    # ---------------------------
    # Workflow
    # ---------------------------
    def action_submit(self):
        for rec in self:
            rec.write({'state': 'requested'})
            emp_sudo = rec.employee_id.sudo()
            mgr_user = rec._get_manager_user(emp_sudo)
            sender_user = emp_sudo.user_id or self.env.user
            if mgr_user and mgr_user.partner_id:
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                
                dm_body = f"""
<p>Dear Colleague,</p>
<p>A new Predefined Attendance Request has been submitted with the following details:</p>
<p><b>Requester Name:</b> {emp_sudo.name}<br/>
<b>Request Type:</b> {type_label}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Reason:</b> {rec.approval_reason or 'N/A'}</p>
<p>Kindly review and process.</p>
"""
                rec._send_direct_message(sender_user, mgr_user, dm_body)

                try:
                    rec.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=mgr_user.id,
                        summary=f"Approval Needed: Predefined Attendance for {emp_sudo.name}",
                        note=f"Review request for {rec.date} ({rec.time_range}). Reason: {rec.approval_reason or 'N/A'}"
                    )
                except Exception as e:
                    _logger.warning(f"Could not schedule activity for preapproval: {e}")

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

            # Complete activity
            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'])
            except Exception as e:
                _logger.warning(f"Activity feedback error: {e}")

            # Send Direct Chat Message to Requester in Odoo Discuss
            emp_user = rec.employee_id.user_id or rec.create_uid
            if emp_user and emp_user.partner_id:
                approver_name = self.env.user.name
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                dm_body = f"""
<p>Dear {emp_user.name},</p>
<p>Your Predefined Attendance Request has been <b>APPROVED</b>:</p>
<p><b>Request Type:</b> {type_label}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Approved By:</b> {approver_name}</p>
<p>Thank you.</p>
"""
                rec._send_direct_message(self.env.user, emp_user, dm_body)

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

            # Complete activity
            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'])
            except Exception as e:
                _logger.warning(f"Activity feedback error: {e}")

            # Send Direct Chat Message to Requester in Odoo Discuss
            emp_user = rec.employee_id.user_id or rec.create_uid
            if emp_user and emp_user.partner_id:
                rejecter_name = self.env.user.name
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                dm_body = f"""
<p>Dear {emp_user.name},</p>
<p>Your Predefined Attendance Request has been <b style="color:red;">REJECTED</b>:</p>
<p><b>Request Type:</b> {type_label}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Rejected By:</b> {rejecter_name}</p>
<p>Please contact your manager for further details.</p>
"""
                rec._send_direct_message(self.env.user, emp_user, dm_body)

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_emp = self.env.user.employee_id
        if not current_emp:
            current_emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)

        for vals in vals_list:
            if not is_admin and current_emp and 'employee_id' not in vals:
                vals['employee_id'] = current_emp.id
        return super().create(vals_list)

    def write(self, vals):
        op_fields = {'employee_id', 'exception_type', 'approval_reason', 'date', 'start_time', 'end_time'}
        is_op_change = bool(op_fields.intersection(vals.keys()))
        for rec in self:
            if rec.state != 'draft' and is_op_change:
                raise ValidationError("Once submitted or approved/rejected, request details cannot be modified.")
        return super().write(vals)
