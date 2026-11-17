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
        tracking=True,
        domain=lambda self: self._get_team_member_domain()
    )

    allowed_shift_ids = fields.Many2many(
        'job.shift',
        compute='_compute_allowed_shift_ids',
        string="Allowed Shifts"
    )

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

    def _compute_allowed_shift_ids(self):
        for rec in self:
            allowed = self.env.user.sudo()._get_allowed_job_shift_ids()
            rec.allowed_shift_ids = [(6, 0, allowed)]

    job_position = fields.Char(
        string="Job Position",
        related='employee_id.job_position.name',
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
        selection=[('draft', "Draft"), ('active', "Active"), ('inactive', "Inactive")],
        default='draft',
        tracking=True
    )
    is_modified = fields.Boolean(
        string="Has Pending Modifications",
        default=False,
        copy=False,
        tracking=True
    )
    is_expired = fields.Boolean(
        string="Is Expired",
        compute="_compute_is_expired"
    )

    @api.depends('end_date')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_expired = bool(rec.end_date and rec.end_date < today)
    notes = fields.Text(string="Notes & Special Instructions")

    line_ids = fields.One2many(
        'job.position.roster.exception.line',
        'roster_id',
        string="Daily Roster Schedule",
        copy=True
    )

    @api.onchange('line_ids')
    def _onchange_line_ids(self):
        for rec in self:
            if rec.status == 'active':
                rec.is_modified = True

    @api.depends('employee_id', 'start_date', 'end_date')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or "Employee"
            s_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else ""
            e_date = rec.end_date.strftime('%Y-%m-%d') if rec.end_date else ""
            rec.name = f"{emp} - Roster ({s_date} to {e_date})"

    @api.onchange('start_date', 'end_date', 'employee_id')
    def _onchange_dates_generate_lines(self):
        if not self.start_date or not self.end_date or self.end_date < self.start_date:
            return

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
                        self.env['job.position.roster.exception.line'].with_context(generating_roster_lines=True).create({
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

    def action_submit_roster(self):
        """Submit and validate the roster schedule."""
        for rec in self:
            rec.generate_roster_lines()
            rec._check_overlap()
            rec._check_line_date_integrity()
            unassigned = rec.line_ids.filtered(lambda l: l.schedule_type == 'shift' and not l.shift_id)
            if unassigned:
                missing_str = ", ".join(l.date.strftime('%Y-%m-%d (%A)') for l in unassigned[:5])
                if len(unassigned) > 5:
                    missing_str += f" and {len(unassigned) - 5} more"
                raise ValidationError(_(
                    "Cannot submit roster: Please select an assigned shift for all working days before submitting.\n\n"
                    "Unassigned shift on: %s"
                ) % missing_str)

            rec.with_context(submitting_roster=True).write({'status': 'active', 'is_modified': False})
            updater_name = self.env.user.employee_id.name or self.env.user.name or _("Administrator")
            rec.message_post(body=_("Shift Roster submitted and activated by %s.") % updater_name)
            if rec.employee_id and rec.employee_id.user_id:
                body = f"📅 <b>Job Position Shift Roster Schedule Updated</b><br/>Your shift roster schedule ({rec.start_date} to {rec.end_date}) has been updated by <b>{updater_name}</b>. Current Status: <b>Active</b>."
                rec._send_notification_to_employee(rec, body)

        emp_label = self[0].employee_id.name if self and self[0].employee_id else "Employee"
        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _("Shift Roster Activated"),
                'subtitle': _("Active schedule for %s") % emp_label,
                'type': 'success',
                'icon': 'fa-calendar-check-o',
                'reload': True,
            }
        }

    def action_deactivate_roster(self):
        """Deactivates and archives the roster schedule with active shift guard."""
        updater_name = self.env.user.employee_id.name or self.env.user.name or _("Administrator")
        emp_label = "Employee"
        for rec in self:
            emp_label = rec.employee_id.name if rec.employee_id else "Employee"
            rec.write({'status': 'inactive', 'active': False})
            rec.message_post(body=_("Shift Roster deactivated by %s.") % updater_name)
            if rec.employee_id and rec.employee_id.user_id:
                body = f"📅 <b>Job Position Shift Roster Schedule Deactivated</b><br/>Your shift roster schedule ({rec.start_date} to {rec.end_date}) has been deactivated by <b>{updater_name}</b>."
                rec._send_notification_to_employee(rec, body)
        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _("Shift Roster Deactivated"),
                'subtitle': _("Schedule ended for %s") % emp_label,
                'type': 'warning',
                'icon': 'fa-ban',
                'reload': True,
            }
        }

    @api.constrains('start_date', 'end_date', 'employee_id', 'status', 'active')
    def _check_overlap(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.employee_id or not rec.start_date or not rec.end_date:
                continue

            if not self.env.context.get('skip_date_check'):
                rec_created_today = not rec.create_date or (fields.Date.context_today(rec, rec.create_date) == today)
                if rec_created_today and rec.start_date < today:
                    raise ValidationError(_("Shift Start Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (rec.start_date, today))

                if rec_created_today and rec.end_date < today:
                    raise ValidationError(_("Shift End Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (rec.end_date, today))

            if rec.end_date < rec.start_date:
                raise ValidationError(_("Shift End Date (%s) cannot be earlier than Shift Start Date (%s).") % (rec.end_date, rec.start_date))

            if rec.active and rec.status == 'active':
                # 0. Check open attendance blocking ONLY if assigning a NEW roster covering TODAY
                # For existing active rosters, daily line edits are protected individually
                # by _check_open_attendance_line_blocking (which only blocks if editing today's line).
                rec_created_today = not rec.create_date or (fields.Date.context_today(rec, rec.create_date) == today)
                if rec_created_today and rec.start_date <= today and rec.end_date >= today:
                    open_att = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('check_out', '=', False)
                    ], limit=1)
                    if open_att:
                        att_date = fields.Date.context_today(self, open_att.check_in)
                        if att_date == today:
                            raise ValidationError(_(
                                "Cannot assign, modify, or change today's roster exception for '%s' while they have an active open attendance session today.\n\n"
                                "Employee checked in at %s. Please wait until the employee checks out before changing today's roster schedule."
                            ) % (rec.employee_id.name, open_att.check_in))

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
                    ('status', '=', 'active'),
                    ('start_date', '<=', rec.end_date),
                    '|', ('end_date', '=', False), ('end_date', '>=', rec.start_date)
                ], limit=1)
                if static_exception:
                    e_str = static_exception.end_date.strftime('%Y-%m-%d') if static_exception.end_date else 'Indefinite'
                    raise ValidationError(_(
                        "Cannot assign Job Position Roster Exception: Employee '%s' already has an active Job Position Exception "
                        "(%s) assigned from %s to %s. Multiple active shift assignments covering the same dates are not allowed. "
                        "Please end or deactivate the static shift exception first."
                    ) % (rec.employee_id.name, static_exception.shift_id.name if static_exception.shift_id else "Exception", static_exception.start_date, e_str))

    @api.constrains('status', 'line_ids', 'active')
    def _check_active_lines_assigned(self):
        for rec in self:
            if rec.active and rec.status == 'active':
                if not rec.line_ids:
                    raise ValidationError(_("Cannot save active roster: No daily schedule lines found. Please add schedule lines or click 'Submit'."))
                unassigned = rec.line_ids.filtered(lambda l: l.schedule_type == 'shift' and not l.shift_id)
                if unassigned:
                    missing_str = ", ".join(l.date.strftime('%Y-%m-%d (%A)') for l in unassigned[:5])
                    raise ValidationError(_(
                        "Cannot save active roster: All working days must have an assigned shift template.\n"
                        "Please assign a shift or mark the day as Day Off for: %s"
                    ) % missing_str)

    @api.constrains('start_date', 'end_date', 'line_ids')
    def _check_line_date_integrity(self):
        for rec in self:
            if not rec.start_date or not rec.end_date:
                continue
            if not rec.line_ids:
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

        if not self.env.context.get('skip_date_check'):
            today = fields.Date.context_today(self)
            for vals in vals_list:
                s_date = vals.get('start_date')
                if s_date:
                    if isinstance(s_date, str):
                        s_date = fields.Date.from_string(s_date)
                    if s_date < today:
                        raise ValidationError(_("Shift Start Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (s_date, today))
                e_date = vals.get('end_date')
                if e_date:
                    if isinstance(e_date, str):
                        e_date = fields.Date.from_string(e_date)
                    if e_date < today:
                        raise ValidationError(_("Shift End Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (e_date, today))
                    if s_date and e_date < s_date:
                        raise ValidationError(_("Shift End Date (%s) cannot be earlier than Shift Start Date (%s).") % (e_date, s_date))

        records = super().create(vals_list)
        for rec in records:
            if rec.start_date and rec.end_date and not rec.line_ids:
                rec.generate_roster_lines()

            if rec.status == 'active' and rec.employee_id and rec.employee_id.user_id:
                updater_name = self.env.user.employee_id.name or self.env.user.name or _("Administrator")
                body = f"📅 <b>Job Position Shift Roster Assigned</b><br/>A shift roster schedule has been assigned to you from <b>{rec.start_date}</b> to <b>{rec.end_date}</b> by <b>{updater_name}</b>."
                rec._send_notification_to_employee(rec, body)
        return records

    def write(self, vals):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can edit Roster Exceptions."))

        if not self.env.context.get('install_mode'):
            for rec in self:
                if rec.status != 'draft':
                    if 'employee_id' in vals and vals['employee_id'] != rec.employee_id.id:
                        raise ValidationError(_("Cannot change Employee Name once the roster schedule has been submitted."))
                    if 'start_date' in vals:
                        new_s = vals['start_date']
                        if isinstance(new_s, str):
                            new_s = fields.Date.from_string(new_s)
                        if new_s != rec.start_date:
                            raise ValidationError(_("Cannot change Shift Start Date once the roster schedule has been submitted."))

        if not self.env.context.get('skip_date_check') and ('start_date' in vals or 'end_date' in vals):
            today = fields.Date.context_today(self)
            for rec in self:
                s_date = vals.get('start_date', rec.start_date)
                if isinstance(s_date, str):
                    s_date = fields.Date.from_string(s_date)
                e_date = vals.get('end_date', rec.end_date)
                if isinstance(e_date, str):
                    e_date = fields.Date.from_string(e_date)
                if 'start_date' in vals and s_date and s_date < today:
                    raise ValidationError(_("Shift Start Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (s_date, today))
                if 'end_date' in vals and e_date and e_date < today:
                    raise ValidationError(_("Shift End Date (%s) cannot be in the past (previous day). Please select today (%s) or a future date.") % (e_date, today))
                if s_date and e_date and e_date < s_date:
                    raise ValidationError(_("Shift End Date (%s) cannot be earlier than Shift Start Date (%s).") % (e_date, s_date))

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
        if not self.env.context.get('submitting_roster') and not self.env.context.get('install_mode') and not self.env.context.get('generating_roster_lines'):
            if 'line_ids' in vals:
                for rec in self:
                    if rec.status == 'active' and not rec.is_modified:
                        rec.is_modified = True
        if any(k in vals for k in ['start_date', 'end_date']):
            for rec in self:
                rec.generate_roster_lines()
        return res

    def unlink(self):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can delete Roster Exceptions."))
        for rec in self:
            if rec.active and rec.status == 'active' and rec.employee_id:
                open_att = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('check_out', '=', False)
                ], limit=1)
                if open_att:
                    raise ValidationError(_(
                        "Cannot delete or archive roster exception for '%s' while they have an active open attendance session.\n\n"
                        "Employee checked in at %s. Please wait until the employee checks out before deleting their roster schedule."
                    ) % (rec.employee_id.name, open_att.check_in))
            rec.write({'active': False})
        return True

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

    allowed_shift_ids = fields.Many2many(
        'job.shift',
        compute='_compute_allowed_shift_ids',
        string="Allowed Shifts"
    )

    shift_id = fields.Many2one('job.shift', string="Assigned Shift")
    is_past_date = fields.Boolean(
        string="Is Past Date",
        compute="_compute_is_past_date"
    )

    @api.model
    def _float_to_time_str(self, float_val):
        if float_val is None or float_val is False:
            return ""
        hours = int(float_val)
        minutes = int(round((float_val - hours) * 60))
        if minutes >= 60:
            hours = (hours + 1) % 24
            minutes = 0
        period = "AM" if hours < 12 else "PM"
        display_hour = hours % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour:02d}:{minutes:02d} {period}"

    def _has_attendance_today(self, employee):
        """Checks if employee has recorded attendance check-in for today."""
        if not employee:
            return False
        today = fields.Date.context_today(self)
        recent_atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', fields.Datetime.to_datetime(today) - timedelta(days=1))
        ])
        for att in recent_atts:
            if fields.Date.context_today(self, att.check_in) == today:
                return True
        return False

    @api.depends('date', 'shift_id', 'shift_id.start_time', 'roster_id.employee_id')
    def _compute_is_past_date(self):
        today = fields.Date.context_today(self)
        now_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        now_hour = now_dt.hour + (now_dt.minute / 60.0)
        for rec in self:
            if rec.date and rec.date < today:
                rec.is_past_date = True
            elif rec.date and rec.date == today:
                emp = rec.roster_id.employee_id if rec.roster_id else False
                has_checkin = rec._has_attendance_today(emp)
                if has_checkin:
                    rec.is_past_date = True
                else:
                    # If no check-in today, check if any future shifts can start after now
                    allowed = self.env.user._get_allowed_job_shift_ids(target_employee=emp)
                    future_shifts = self.env['job.shift'].browse(allowed).filtered(lambda s: s.start_time > now_hour)
                    rec.is_past_date = not bool(future_shifts)
            else:
                rec.is_past_date = False

    @api.onchange('schedule_type', 'shift_id')
    def _onchange_mark_roster_modified(self):
        if self.roster_id:
            self.roster_id.is_modified = True

    def write(self, vals):
        if not self.env.context.get('skip_past_date_check') and not self.env.context.get('generating_roster_lines') and not self.env.context.get('install_mode'):
            if 'schedule_type' in vals or 'shift_id' in vals:
                today = fields.Date.context_today(self)
                now_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
                now_hour = now_dt.hour + (now_dt.minute / 60.0)
                cur_time_str = self._float_to_time_str(now_hour)
                for rec in self:
                    if rec.date and rec.date < today:
                        date_str = rec.date.strftime('%B %d, %Y')
                        raise ValidationError(_(
                            "Modifying shift assignments for past dates (%(date)s) is strictly prohibited. "
                            "Historical roster schedules are locked to preserve attendance data integrity."
                        ) % {'date': date_str})
                    elif rec.date and rec.date == today:
                        emp = rec.roster_id.employee_id if rec.roster_id else False
                        if rec._has_attendance_today(emp):
                            raise ValidationError(_(
                                "Cannot modify shift schedule for today (%(date)s): "
                                "Employee '%(emp)s' has already recorded attendance today."
                            ) % {
                                'date': rec.date.strftime('%B %d, %Y'),
                                'emp': emp.name if emp else _("Employee"),
                            })

                        # Block assigning a shift for today whose start time has already passed
                        if vals.get('shift_id'):
                            new_shift = self.env['job.shift'].browse(vals['shift_id'])
                            if new_shift and now_hour >= new_shift.start_time:
                                start_str = self._float_to_time_str(new_shift.start_time)
                                raise ValidationError(_(
                                    "Cannot assign shift '%(shift)s' for today (%(date)s): "
                                    "shift start time (%(start)s) has already passed. Current time is %(cur)s. "
                                    "The assigned shift must start after the current time."
                                ) % {
                                    'date': rec.date.strftime('%B %d, %Y'),
                                    'shift': new_shift.name,
                                    'start': start_str,
                                    'cur': cur_time_str,
                                })

        res = super().write(vals)
        if ('schedule_type' in vals or 'shift_id' in vals) and not self.env.context.get('generating_roster_lines') and not self.env.context.get('submitting_roster'):
            for rec in self:
                if rec.roster_id and rec.roster_id.status == 'active' and not rec.roster_id.is_modified:
                    rec.roster_id.is_modified = True
        return res

    def unlink(self):
        if not self.env.context.get('generating_roster_lines') and not self.env.context.get('install_mode'):
            today = fields.Date.context_today(self)
            for rec in self:
                if rec.date and rec.date < today:
                    date_str = rec.date.strftime('%B %d, %Y')
                    raise ValidationError(_(
                        "Cannot delete roster schedule line for past date (%(date)s)."
                    ) % {'date': date_str})
        return super().unlink()

    @api.depends('roster_id.employee_id', 'date')
    def _compute_allowed_shift_ids(self):
        today = fields.Date.context_today(self)
        now_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        now_hour = now_dt.hour + (now_dt.minute / 60.0)
        for rec in self:
            target_emp = rec.roster_id.employee_id if rec.roster_id else False
            allowed = self.env.user._get_allowed_job_shift_ids(target_employee=target_emp)
            if rec.date and rec.date == today:
                # For today: only allow shifts that start after the current time
                allowed_records = self.env['job.shift'].browse(allowed).filtered(lambda s: s.start_time > now_hour)
                rec.allowed_shift_ids = [(6, 0, allowed_records.ids)]
            else:
                rec.allowed_shift_ids = [(6, 0, allowed)]

    @api.constrains('schedule_type', 'shift_id', 'display_date_str', 'day_name', 'date')
    def _check_shift_id_required(self):
        if self.env.context.get('generating_roster_lines'):
            return
        for rec in self:
            if rec.roster_id and rec.roster_id.active and rec.roster_id.status == 'active':
                if rec.schedule_type == 'shift' and not rec.shift_id:
                    label = rec.display_date_str or rec.day_name or (str(rec.date) if rec.date else "")
                    raise ValidationError(_("Assigned Shift is required for %s when schedule type is set to 'Assigned Shift'.") % label)

    @api.constrains('schedule_type', 'shift_id')
    def _check_open_attendance_line_blocking(self):
        today = fields.Date.context_today(self)
        for rec in self:
            # ONLY block if line date is today or in the past
            if rec.date and rec.date <= today and rec.roster_id and rec.roster_id.active and rec.roster_id.status == 'active':
                emp = rec.roster_id.employee_id
                if emp:
                    open_att = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('check_out', '=', False)
                    ], limit=1)
                    if open_att:
                        att_date = fields.Date.context_today(self, open_att.check_in)
                        if att_date == rec.date:
                            raise ValidationError(_(
                                "Cannot modify daily shift line for employee '%s' on %s while they have an active open attendance session.\n\n"
                                "Employee checked in at %s. Please wait until the employee checks out before modifying today's roster schedule."
                            ) % (emp.name, rec.date, open_att.check_in))
