from odoo import models, fields, api, Command, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta

class JobPositionRosterException(models.Model):
    _name = "job.position.roster.exception"
    _rec_name = "name"
    _description = "Job Position Roster Exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "start_date desc, id desc"

    name = fields.Char(
        string="Roster Name",
        compute="_compute_name",
        store=True,
        index=True
    )
    active = fields.Boolean(string="Active", default=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee Name",
        required=True,
        index=True,
        tracking=True
    )
    job_position = fields.Char(
        string="Job Position",
        related='employee_id.job_position.name',
        store=True,
        readonly=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string="Department",
        related='employee_id.department_id',
        store=True,
        readonly=True
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string="Operating Unit",
        related='employee_id.default_operating_unit_id',
        store=True,
        readonly=True
    )

    start_date = fields.Date(
        string="Shift Start Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    end_date = fields.Date(
        string="Shift End Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    status = fields.Selection(
        string="Status",
        selection=[('active', "Active"), ('inactive', "Inactive")],
        default='active',
        tracking=True
    )
    notes = fields.Text(string="Notes & Special Instructions")

    line_ids = fields.One2many(
        'job.position.roster.exception.line',
        'roster_id',
        string="Daily Roster Schedule",
        copy=True
    )

    @api.depends('employee_id', 'start_date', 'end_date')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or "Employee"
            s_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else ""
            e_date = rec.end_date.strftime('%Y-%m-%d') if rec.end_date else ""
            rec.name = f"{emp} - Roster ({s_date} to {e_date})"

    @api.onchange('start_date', 'end_date')
    def _onchange_dates_generate_lines(self):
        if not self.start_date or not self.end_date:
            return

        if self.end_date < self.start_date:
            self.end_date = self.start_date

        existing_map = {l.date: l for l in self.line_ids if l.date}
        commands = []
        valid_dates = set()

        cur_date = self.start_date
        while cur_date <= self.end_date:
            valid_dates.add(cur_date)
            day_name = cur_date.strftime('%A')
            display_str = cur_date.strftime('%A, %b %d, %Y')
            is_sunday = (cur_date.weekday() == 6)

            if cur_date not in existing_map:
                commands.append(Command.create({
                    'date': cur_date,
                    'day_name': day_name,
                    'display_date_str': display_str,
                    'schedule_type': 'day_off' if is_sunday else 'shift',
                    'shift_id': False
                }))
            cur_date += timedelta(days=1)

        # Unlink lines outside date range
        for l in self.line_ids:
            if l.date and l.date not in valid_dates:
                commands.append(Command.delete(l.id if isinstance(l.id, int) else l._origin.id or l.id))

        if commands:
            self.line_ids = commands

    def generate_roster_lines(self):
        """Generates or updates line_ids for each date from start_date to end_date."""
        for rec in self:
            if not rec.start_date or not rec.end_date:
                continue

            existing_map = {l.date: l for l in rec.line_ids if l.date}
            valid_dates = set()

            cur_date = rec.start_date
            while cur_date <= rec.end_date:
                valid_dates.add(cur_date)
                day_name = cur_date.strftime('%A')
                display_str = cur_date.strftime('%A, %b %d, %Y')
                is_sunday = (cur_date.weekday() == 6)

                if cur_date not in existing_map:
                    if rec.id:
                        self.env['job.position.roster.exception.line'].create({
                            'roster_id': rec.id,
                            'date': cur_date,
                            'day_name': day_name,
                            'display_date_str': display_str,
                            'schedule_type': 'day_off' if is_sunday else 'shift',
                            'shift_id': False
                        })
                cur_date += timedelta(days=1)

            # Remove lines outside date range
            lines_to_remove = rec.line_ids.filtered(lambda l: l.date not in valid_dates)
            if lines_to_remove:
                lines_to_remove.unlink()

    @api.constrains('start_date', 'end_date', 'employee_id', 'status', 'active')
    def _check_overlap(self):
        for rec in self:
            if not rec.employee_id or not rec.start_date or not rec.end_date:
                continue

            if rec.end_date < rec.start_date:
                raise ValidationError(_("Shift End Date cannot be earlier than Shift Start Date."))

            if rec.active and rec.status == 'active':
                # 1. Check overlap with other active Roster Exceptions
                overlap_roster = self.search([
                    ('id', '!=', rec.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('active', '=', True),
                    ('status', '=', 'active'),
                    ('start_date', '<=', rec.end_date),
                    ('end_date', '>=', rec.start_date)
                ], limit=1)
                if overlap_roster:
                    raise ValidationError(_(
                        "An active Job Position Roster Exception for employee '%s' already exists for dates %s to %s."
                    ) % (rec.employee_id.name, overlap_roster.start_date, overlap_roster.end_date))

                # 2. Check conflict with active Static Job Position Exception
                static_exception = self.env['job.position.exception'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('active', '=', True),
                    ('status', '=', 'active')
                ], limit=1)
                if static_exception:
                    raise ValidationError(_(
                        "Employee '%s' already has an active static Job Position Exception assigned (%s). "
                        "Please deactivate or update the static exception before activating a date-based roster exception."
                    ) % (rec.employee_id.name, static_exception.shift_id.name if static_exception.shift_id else "Exception"))

    @api.constrains('start_date', 'end_date', 'line_ids')
    def _check_line_date_integrity(self):
        for rec in self:
            if not rec.start_date or not rec.end_date:
                continue
            expected_dates = {rec.start_date + timedelta(days=i) for i in range((rec.end_date - rec.start_date).days + 1)}
            actual_dates = set(rec.line_ids.mapped('date'))
            if expected_dates != actual_dates:
                raise ValidationError(_(
                    "Roster line dates do not match the required date range from %s to %s. "
                    "Please click 'Generate / Refresh Daily Lines' to synchronize all daily lines."
                ) % (rec.start_date, rec.end_date))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can create Roster Exceptions."))

        records = super().create(vals_list)
        for rec in records:
            if rec.start_date and rec.end_date and not rec.line_ids:
                rec.generate_roster_lines()

            if rec.employee_id and rec.employee_id.user_id:
                body = f"📅 <b>Job Position Shift Roster Assigned</b><br/>A shift roster schedule has been assigned to you from <b>{rec.start_date}</b> to <b>{rec.end_date}</b>."
                rec._send_notification_to_employee(rec, body)
        return records

    def write(self, vals):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can edit Roster Exceptions."))

        # In-Use Active Shift Deactivation Guard
        if ('status' in vals and vals['status'] == 'inactive') or ('active' in vals and not vals['active']):
            today = fields.Date.context_today(self.env.user)
            for rec in self:
                if rec.status == 'active' and rec.active:
                    if rec.start_date and rec.end_date and rec.start_date <= today <= rec.end_date:
                        today_line = rec.line_ids.filtered(lambda l: l.date == today)
                        if today_line and today_line[0].schedule_type == 'shift':
                            day_label = today_line[0].display_date_str or today.strftime('%A, %b %d, %Y')
                            raise ValidationError(_(
                                "Cannot Deactivate Schedule: The shift roster schedule for '%s' is currently in use today (%s). "
                                "Active ongoing shift schedules cannot be set to inactive while in progress to protect live check-in and attendance integrity."
                            ) % (rec.employee_id.name, day_label))

        res = super().write(vals)
        if 'start_date' in vals or 'end_date' in vals:
            for rec in self:
                rec.generate_roster_lines()
        return res

    def _send_notification_to_employee(self, record, body_html):
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
        except Exception:
            pass

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
        except Exception:
            pass


class JobPositionRosterExceptionLine(models.Model):
    _name = "job.position.roster.exception.line"
    _description = "Job Position Roster Exception Line"
    _order = "date asc, id asc"

    roster_id = fields.Many2one(
        'job.position.roster.exception',
        string="Roster Exception",
        required=False,
        ondelete='cascade',
        index=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        related='roster_id.employee_id',
        store=True,
        readonly=True,
        index=True
    )
    date = fields.Date(string="Date", required=True, index=True)
    day_name = fields.Char(string="Day of Week")
    display_date_str = fields.Char(string="Date Details")

    schedule_type = fields.Selection([
        ('shift', 'Assigned Shift'),
        ('day_off', 'Day Off')
    ], string="Schedule Type", default='shift', required=True)

    shift_id = fields.Many2one('job.shift', string="Assigned Shift")

    @api.constrains('schedule_type', 'shift_id', 'display_date_str', 'day_name', 'date')
    def _check_shift_id_required(self):
        for rec in self:
            if rec.schedule_type == 'shift' and not rec.shift_id:
                label = rec.display_date_str or rec.day_name or (str(rec.date) if rec.date else "")
                raise ValidationError(_("Assigned Shift is required for %s when schedule type is set to 'Assigned Shift'.") % label)
