from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import time

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

    def unlink(self):
        """ Soft delete: Archive records instead of removing them from database """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            emp_user = rec.employee_id.user_id
            if emp_user and emp_user.partner_id:
                from markupsafe import Markup
                body = Markup(
                    f"📅 <b>Job Shift Exception Assigned</b><br/>"
                    f"You have been assigned to shift schedule <b>{rec.shift_id.name}</b> ({rec.time_range or ''})."
                )
                try:
                    rec.message_post(
                        body=body,
                        partner_ids=[emp_user.partner_id.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )
                except Exception as e:
                    pass
                rec.write({'notify_status': 'notified'})
        return records

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

    @api.depends('shift_id')
    def _compute_time_range(self):
        for record in self:
            record.time_range = record.shift_id.time_range if record.shift_id else ""

    @api.constrains('employee_id', 'shift_id')
    def _check_duplicate_exception(self):
        for record in self:
            duplicate = self.search([
                ('id', '!=', record.id),
                ('employee_id', '=', record.employee_id.id),
                ('shift_id', '=', record.shift_id.id),
                ('active', '=', True)
            ], limit=1)

            if duplicate:
                raise ValidationError(
                    f"{record.employee_id.name} already has an exception "
                    f"for shift {record.shift_id.name}."
                )

    def notify(self):
        for record in self:
            employee = record.employee_id
            if not employee:
                raise ValidationError("No employee is assigned.")

            message = """Dear %s,<br>
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

            partner = employee.user_id.partner_id
            if partner:
                channel = self.env['discuss.channel'].channel_get([partner.id])
                channel_id = self.env['discuss.channel'].browse(channel["id"])
                channel_id.message_post(
                    body=message,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

            record.notify_status = "notified"

