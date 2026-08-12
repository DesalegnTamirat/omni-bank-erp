from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import time
import logging

_logger = logging.getLogger(__name__)

class JobPositionException(models.Model):
    _name = "job.position.exception"
    _rec_name = "job_position_exception_name"
    _description = "Job Position Exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(string="Active", default=True, index=True)
    job_position_exception_name = fields.Char(
        string="Exception Name",
        compute="_compute_job_position_exception_name",
        store=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee Name",
        required=True,
        index=True,
        domain=lambda self: self._get_team_member_domain()
    )
    job_position = fields.Char(
        string="Job Position", 
        compute='_compute_job_position', 
        store=True,
        readonly=True
    )
    department_id = fields.Many2one('hr.department', string="Department", related='employee_id.department_id', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string="Operating Unit", related='employee_id.default_operating_unit_id', store=True, readonly=True)

    allowed_shift_ids = fields.Many2many(
        'job.shift',
        compute='_compute_allowed_shift_ids',
        string="Allowed Shifts"
    )

    shift_id = fields.Many2one(
        'job.shift',
        string="Schedule Name",
        required=True,
        index=True
    )

    time_range = fields.Char(string="Time Range", compute='_compute_time_range', store=True)
    day_off = fields.Date(string="Day Off")
    status = fields.Selection(
        string="Status",
        selection=[('active', "Active"), ('inactive', "Inactive")],
        default='active'
    )
    notify_status = fields.Selection([('notified', 'Notified'), ('not_notified', 'Not Notified')], string="Notification Status", default='not_notified')

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can create Job Position Exceptions."))

        for vals in vals_list:
            if vals.get('status', 'active') == 'active' and vals.get('employee_id'):
                other_actives = self.search([
                    ('employee_id', '=', vals['employee_id']),
                    ('status', '=', 'active'),
                    ('active', '=', True)
                ])
                if other_actives:
                    other_actives.sudo().write({'status': 'inactive'})

        records = super().create(vals_list)
        for rec in records:
            if rec.employee_id and rec.employee_id.user_id:
                body = (
                    f"???? <b>Job Shift Exception Assigned</b><br/>"
                    f"You have been assigned to shift schedule <b>{rec.shift_id.name if rec.shift_id else 'N/A'}</b> "
                    f"({rec.time_range or ''})."
                )
                rec._send_notification_to_employee(rec, body)
                rec.write({'notify_status': 'notified'})
        return records

    def write(self, vals):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can edit Job Position Exceptions."))

        if 'shift_id' in vals and 'status' not in vals:
            vals['status'] = 'active'

        if vals.get('status') == 'active':
            for rec in self:
                emp_id = vals.get('employee_id', rec.employee_id.id)
                if emp_id:
                    other_actives = self.search([
                        ('id', '!=', rec.id),
                        ('employee_id', '=', emp_id),
                        ('status', '=', 'active'),
                        ('active', '=', True)
                    ])
                    if other_actives:
                        other_actives.sudo().write({'status': 'inactive'})

        return super().write(vals)

    def unlink(self):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can delete Job Position Exceptions."))
        for rec in self:
            rec.write({'active': False})
        return True

    def _send_notification_to_employee(self, record, body_html):
        """ Sends direct chat notification in Discuss and posts to record chatter """
        emp_user = record.employee_id.user_id
        if not emp_user or not emp_user.partner_id:
            return

        from markupsafe import Markup
        markup_body = Markup(body_html)

        try:
            record.sudo().message_subscribe(partner_ids=[emp_user.partner_id.id])
            record.sudo().message_post(
                body=markup_body,
                partner_ids=[emp_user.partner_id.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
        except Exception as e:
            _logger.warning(f"Could not post to chatter: {e}")

        try:
            sender = self.env.user if self.env.user else self.env.ref('base.user_admin')
            channel = self.env['discuss.channel'].sudo().with_user(sender)._get_or_create_chat(
                partners_to=[emp_user.partner_id.id]
            )
            if channel:
                channel.sudo().with_user(sender).message_post(
                    body=markup_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception as e:
            _logger.warning(f"Could not send direct chat message: {e}")

    @api.depends('employee_id', 'shift_id', 'job_position')
    def _compute_job_position_exception_name(self):
        for rec in self:
            rec.job_position_exception_name = f'{rec.employee_id.name} - {rec.shift_id.name} - Job Position'

    @api.model
    def _get_team_member_domain(self):
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

    @api.depends('employee_id')
    def _compute_job_position(self):
        for record in self:
            record.job_position = record.employee_id.job_position.name or ""

    @api.depends('employee_id')
    def _compute_allowed_shift_ids(self):
        for rec in self:
            if rec.employee_id:
                allowed = self.env.user._get_allowed_job_shift_ids(target_employee=rec.employee_id)
            else:
                allowed = self.env['job.shift'].sudo().search([('active', '=', True)]).ids
            rec.allowed_shift_ids = [(6, 0, allowed)]

    @api.depends('shift_id')
    def _compute_time_range(self):
        for record in self:
            record.time_range = record.shift_id.time_range if record.shift_id else ""

    @api.constrains('employee_id', 'shift_id', 'status', 'active')
    def _check_duplicate_exception(self):
        for record in self:
            if not record.employee_id or not record.shift_id:
                continue

            emp_ou = record.employee_id.default_operating_unit_id
            emp_dept = record.employee_id.department_id
            if not record.shift_id.is_applicable_for(operating_unit=emp_ou, department=emp_dept):
                raise ValidationError(
                    _(
                        "The selected shift '%s' is not configured to apply to employee %s's "
                        "operating unit (%s) or department (%s)."
                    ) % (
                        record.shift_id.name,
                        record.employee_id.name,
                        emp_ou.name if emp_ou else "N/A",
                        emp_dept.name if emp_dept else "N/A"
                    )
                )

            # Restrict duplicate definitions of the SAME shift template (even if inactive/archived)
            duplicate_definition = self.with_context(active_test=False).search([
                ('id', '!=', record.id),
                ('employee_id', '=', record.employee_id.id),
                ('shift_id', '=', record.shift_id.id),
            ], limit=1)

            if duplicate_definition:
                raise ValidationError(
                    _(
                        "A Job Position Exception definition for employee '%s' with shift '%s' "
                        "already exists in the system (Status: %s). Duplicate shift definitions for the same employee are not allowed."
                    ) % (
                        record.employee_id.name,
                        record.shift_id.name,
                        "Active" if duplicate_definition.active and duplicate_definition.status == 'active' else "Inactive/Archived"
                    )
                )

    @api.onchange('shift_id')
    def _onchange_shift_id_update_status(self):
        if self.shift_id:
            self.status = 'active'
        if self.employee_id:
            ou_id = self.employee_id.default_operating_unit_id.id if self.employee_id.default_operating_unit_id else False
            dept_id = self.employee_id.department_id.id if self.employee_id.department_id else False
            allowed_ids = self.env['job.shift'].get_allowed_shift_ids(operating_unit_id=ou_id, department_id=dept_id)
            return {'domain': {'shift_id': [('id', 'in', allowed_ids)]}}
        return {'domain': {'shift_id': [('id', '=', False)]}}

    @api.onchange('employee_id')
    def _onchange_employee_id_filter_shifts(self):
        if self.employee_id:
            ou_id = self.employee_id.default_operating_unit_id.id if self.employee_id.default_operating_unit_id else False
            dept_id = self.employee_id.department_id.id if self.employee_id.department_id else False
            allowed_ids = self.env['job.shift'].get_allowed_shift_ids(operating_unit_id=ou_id, department_id=dept_id)
            return {'domain': {'shift_id': [('id', 'in', allowed_ids)]}}
        return {'domain': {'shift_id': [('id', '=', False)]}}

    def notify(self):
        for record in self:
            employee = record.employee_id
            if not employee:
                raise ValidationError("No employee is assigned.")

            body = """Dear %s,<br>
            You have a Job Position Exception.<br><br>
            <strong>Job Position:</strong> %s<br>
            <strong>Schedule:</strong> %s (%s)<br>
            <strong>Status:</strong> %s<br><br>
            Please take note of this exception.
            """ % (
                employee.name,
                record.job_position or "N/A",
                record.shift_id.name if record.shift_id else "N/A",
                record.time_range,
                record.status,
            )

            record._send_notification_to_employee(record, body)
            record.write({'notify_status': 'notified'})
