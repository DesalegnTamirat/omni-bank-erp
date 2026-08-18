from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime
import pytz
import logging

_logger = logging.getLogger(__name__)


class OverTime(models.Model):
    _name = "over.time"
    _rec_name = "over_time"
    _description = "Over Time"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(string="Active", default=True, index=True)
    over_time = fields.Char(
        string="Over Time",
        compute='_compute_over_time_name',
        store=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee Name",
        required=True,
        index=True,
        domain=lambda self: self._get_team_member_domain()
    )

    date = fields.Date(string="Date", required=True, index=True)
    start_time = fields.Float(string="Start Time", required=True)
    end_time = fields.Float(string="End Time", required=True)

    # Synchronized Employee Hierarchy Fields
    department_id = fields.Many2one('hr.department', string="Department", related='employee_id.department_id', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string="Job Position", related='employee_id.job_id', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string="Operating Unit", related='employee_id.default_operating_unit_id', store=True, readonly=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            emp = rec.employee_id
            mgr_user = False
            if emp:
                if emp.parent_id and emp.parent_id.user_id:
                    mgr_user = emp.parent_id.user_id
                elif emp.coach_id and emp.coach_id.user_id:
                    mgr_user = emp.coach_id.user_id
                elif emp.attendance_manager_id:
                    mgr_user = emp.attendance_manager_id

            if mgr_user and mgr_user.partner_id:
                from markupsafe import Markup
                body = Markup(
                    f"⏰ <b>New Overtime Logged</b><br/>"
                    f"<b>Employee:</b> {emp.name}<br/>"
                    f"<b>Date:</b> {rec.date}<br/>"
                    f"<b>Hours:</b> {rec.over_time_hour:.1f} hrs<br/>"
                    f"<b>Reason:</b> {rec.over_time_reason or 'N/A'}"
                )
                try:
                    rec.sudo().message_post(
                        body=body,
                        partner_ids=[mgr_user.partner_id.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=mgr_user.id,
                        summary=f"Overtime Logged for {emp.name}",
                        note=f"Overtime logged for {rec.date} ({rec.over_time_hour:.1f} hrs). Reason: {rec.over_time_reason or ''}"
                    )
                except Exception as e:
                    _logger.warning(f"Could not send notification for overtime: {e}")
        return records

    over_time_hour = fields.Float(
        string="Over Time Hour",
        compute="_compute_over_time_hour",
        store=True,
        readonly=True
    )
    used_hours = fields.Float(
        string="Used Hours",
        compute="_compute_used_hours",
        store=True,
        readonly=True
    )
    remaining_hours = fields.Float(
        string="Remaining Hours",
        compute="_compute_remaining_hours",
        store=True,
        readonly=True
    )

    compensation_type = fields.Selection(
        [('compensatory_day', 'Compensatory Day'),
         # ('payment','Payment')
         ],
        string="Compensation Type",
        required=True,
        default='compensatory_day'
    )
    over_time_reason = fields.Text(string="Over Time Reason",required=True)
    consumption_ids = fields.One2many(
        'over.time.consumption',
        'over_time_id',
        string='Consumed By Leaves'
    )
    state = fields.Selection(
        [
            ('draft', 'Available'),
            ('partially_used', 'Partially Used'),
            ('used', 'Used'),
        ],
        compute="_compute_state",
        store=True,
        readonly=True
    )
    _sql_constraints = [
        (
            'check_positive_overtime',
            'CHECK(over_time_hour > 0)',
            'Overtime must be greater than zero.'
        ),
        (
            'check_remaining_non_negative',
            'CHECK(remaining_hours >= 0)',
            'Remaining overtime cannot be negative.'
        )
    ]

    # show team members under manager hierarchy
    @api.model
    def _get_team_member_domain(self):
        if self.env.is_superuser() or self.env.user.has_group('base.group_system'):
            return [('active', '=', True)]

        current_employee = self.env.user.employee_id
        if not current_employee:
            current_employee = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)

        emp_id = current_employee.id if current_employee else 0

        return [
            ('active', '=', True),
            '|', '|', '|', '|', '|',
            ('user_id', '=', self.env.uid),
            ('parent_id.user_id', '=', self.env.uid),
            ('parent_id', '=', emp_id),
            ('coach_id.user_id', '=', self.env.uid),
            ('coach_id', '=', emp_id),
            ('attendance_manager_id', '=', self.env.uid)
        ]


    # Compute: over_time display name
    @api.depends('employee_id', 'date')
    def _compute_over_time_name(self):
        for record in self:
            if record.employee_id:
                record.over_time = f"{record.employee_id.name} {record.date} Over Time"
            else:
                record.over_time = "Overtime"

    # Compute: over_time_hour
    @api.depends('start_time', 'end_time')
    def _compute_over_time_hour(self):
        for record in self:
            record.over_time_hour = record.end_time - record.start_time

    @api.depends('consumption_ids.hours')
    def _compute_used_hours(self):
        for rec in self:
            rec.used_hours = sum(rec.consumption_ids.mapped('hours'))


    @api.depends('over_time_hour', 'used_hours')
    def _compute_remaining_hours(self):
        for rec in self:
            rec.remaining_hours = max(0.0, rec.over_time_hour - rec.used_hours)
    @api.depends('remaining_hours', 'over_time_hour', 'used_hours')
    def _compute_state(self):
        for rec in self:
            if not rec.over_time_hour or rec.over_time_hour <= 0:
                rec.state = 'draft'
            elif rec.used_hours >= rec.over_time_hour or rec.remaining_hours <= 0:
                rec.state = 'used'
            elif rec.used_hours > 0:
                rec.state = 'partially_used'
            else:
                rec.state = 'draft'

    @api.constrains('employee_id', 'over_time_hour', 'state')
    def _check_total_hours_cap(self):
        """ Prevents employee from accumulating more than 18 hours of total unused OT """
        for record in self:
            if not record.employee_id:
                continue

            # Search for all existing records for this employee that are NOT fully used
            existing_ot = self.search([
                ('employee_id', '=', record.employee_id.id),
                ('state', 'in', ['draft', 'partially_used']),
                ('id', '!=', record.id)  # Exclude current record to avoid double counting
            ])

            total_unused = sum(existing_ot.mapped('remaining_hours'))
            total_with_current = total_unused + record.over_time_hour

            if total_with_current > 8.0:
                raise ValidationError(
                    f"Action Denied: This would bring {record.employee_id.name}'s "
                    f"total unused overtime to {total_with_current} hours. "
                    f"Maximum allowed is 8 hours. Please utilize existing overtime first."
                )
    # Validations
    @api.constrains('date', 'start_time', 'end_time')
    def _check_time_validity(self):
        for record in self:
            if record.end_time <= record.start_time:
                raise ValidationError("End time must be after start time.")

            user_tz = self.env.user.tz or 'UTC'
            tz = pytz.timezone(user_tz)
            now = datetime.now(tz)

            today = now.date()
            current_float_time = now.hour + now.minute / 60.0

            if record.date < today:
                raise ValidationError("The selected date cannot be in the past.")

            if record.date == today:
                if record.start_time < current_float_time:
                    raise ValidationError("Start time cannot be in the past.")
                if record.end_time < current_float_time:
                    raise ValidationError("End time cannot be in the past.")

    @api.constrains('employee_id', 'date', 'start_time', 'end_time')
    def _check_duplicate_overtime(self):
        for record in self:
            duplicate = self.search([
                ('id', '!=', record.id),
                ('employee_id', '=', record.employee_id.id),
                ('date', '=', record.date),
                ('start_time', '=', record.start_time),
                ('end_time', '=', record.end_time)
            ], limit=1)
            if duplicate:
                raise ValidationError("Duplicate overtime entry is not allowed.")

    def write(self, vals):
        op_fields = {'employee_id', 'date', 'start_time', 'end_time', 'over_time_reason', 'compensation_type'}
        is_op_change = bool(op_fields.intersection(vals.keys()))
        for rec in self:
            if rec.used_hours > 0 or rec.state != 'draft':
                if is_op_change:
                    raise ValidationError("Partially used or fully consumed overtime records cannot be modified.")
        return super().write(vals)
