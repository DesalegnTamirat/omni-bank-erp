from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import datetime
from datetime import time, timedelta
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
    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
        help="Date when this shift exception starts taking effect."
    )
    end_date = fields.Date(
        string="End Date",
        required=False,
        index=True,
        tracking=True,
        help="Optional end date. If left blank, shift holds indefinitely until changed. If set, shift reverts to default after this date."
    )
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

        today_date = fields.Date.context_today(self)
        for vals in vals_list:
            if vals.get('status', 'active') == 'active' and vals.get('employee_id'):
                new_start = vals.get('start_date') or today_date
                if isinstance(new_start, str):
                    new_start = fields.Date.from_string(new_start)
                other_actives = self.search([
                    ('employee_id', '=', vals['employee_id']),
                    ('status', '=', 'active'),
                    ('active', '=', True)
                ])
                for old in other_actives:
                    if new_start > today_date:
                        old.sudo().write({'end_date': new_start - datetime.timedelta(days=1)})
                    else:
                        old.sudo().write({'status': 'inactive'})

        records = super().create(vals_list)
        for rec in records:
            if rec.employee_id and rec.employee_id.user_id:
                body = (
                    f"📅 <b>Job Shift Exception Assigned</b><br/>"
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

        if 'employee_id' in vals:
            for rec in self:
                if rec.employee_id and vals['employee_id'] != rec.employee_id.id:
                    raise UserError(_("Employee Name cannot be changed on an existing Shift Exception record. Please create a new Shift Exception record for the other employee."))

        if 'shift_id' in vals and 'status' not in vals:
            vals['status'] = 'active'

        # Deactivation guard: only block setting status=inactive or active=False when in use today
        if ('status' in vals and vals['status'] == 'inactive') or ('active' in vals and not vals['active']):
            today = fields.Date.context_today(self.env.user)
            is_today_sunday = (today.weekday() == 6)
            for rec in self:
                if rec.status == 'active' and rec.active:
                    open_att = rec._get_open_attendance()
                    if open_att:
                        is_today_off = is_today_sunday or (rec.day_off == today)
                        if not is_today_off:
                            raise ValidationError(_(
                                "Cannot Deactivate Exception: The static shift exception for '%s' (%s) is currently in use today (%s). "
                                "Active ongoing shift exceptions cannot be set to inactive while in progress to protect live check-in and attendance integrity."
                            ) % (rec.employee_id.name, rec.shift_id.name if rec.shift_id else "Shift", today.strftime('%A, %b %d, %Y')))

        if vals.get('status') == 'active':
            for rec in self:
                emp_id = vals.get('employee_id', rec.employee_id.id)
                new_start = vals.get('start_date', rec.start_date or fields.Date.context_today(self))
                if isinstance(new_start, str):
                    new_start = fields.Date.from_string(new_start)
                if emp_id:
                    other_actives = self.search([
                        ('id', '!=', rec.id),
                        ('employee_id', '=', emp_id),
                        ('status', '=', 'active'),
                        ('active', '=', True)
                    ])
                    today_date = fields.Date.context_today(self)
                    for old in other_actives:
                        if old.start_date and old.start_date <= (new_start - datetime.timedelta(days=1)):
                            old.sudo().write({'end_date': new_start - datetime.timedelta(days=1)})
                        else:
                            old.sudo().write({'status': 'inactive'})

        return super().write(vals)

    def _get_open_attendance(self, emp_id=None):
        target_emp_id = emp_id or (self.employee_id.id if self.employee_id else False)
        if not target_emp_id:
            return False
        return self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', target_emp_id),
            ('check_out', '=', False)
        ], limit=1)

    @api.onchange('shift_id', 'start_date', 'end_date', 'employee_id')
    def _onchange_dates_and_employee(self):
        today = fields.Date.context_today(self)
        warning_msg = None

        if self.start_date and self.start_date < today:
            self.start_date = today
            warning_msg = _("Start Date cannot be in the past. It has been set to today (%s).") % today.strftime('%Y-%m-%d')

        if self.start_date and self.end_date and self.end_date < self.start_date:
            self.end_date = self.start_date
            warning_msg = _("End Date cannot be earlier than Start Date.")

        if self.employee_id:
            open_att = self._get_open_attendance()
            if open_att and self.start_date and self.start_date <= today:
                tomorrow = today + datetime.timedelta(days=1)
                self.start_date = tomorrow
                warning_msg = _(
                    "Notice: Employee '%s' is currently checked in for today (%s).\n\n"
                    "You cannot assign or change today's shift while they are actively working. "
                    "The Start Date has been automatically set to TOMORROW (%s). "
                    "You can keep tomorrow or set it to any future date."
                ) % (self.employee_id.name, today.strftime('%Y-%m-%d'), tomorrow.strftime('%Y-%m-%d'))

        if warning_msg:
            return {'warning': {'title': _("Active Attendance Notice"), 'message': warning_msg}}

    @api.constrains('employee_id', 'shift_id', 'start_date', 'status', 'active')
    def _check_open_attendance_blocking(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.active and rec.status == 'active' and rec.employee_id and rec.start_date and rec.start_date <= today:
                open_att = rec._get_open_attendance()
                if open_att:
                    tomorrow = today + datetime.timedelta(days=1)
                    raise ValidationError(_(
                        "Employee '%s' is currently checked in for today (%s).\n\n"
                        "You cannot assign or change a shift schedule starting today while the employee is actively working.\n\n"
                        "Please change the Start Date to TOMORROW (%s) or a future date (e.g. next Sunday)."
                    ) % (rec.employee_id.name, today.strftime('%Y-%m-%d'), tomorrow.strftime('%Y-%m-%d')))

    can_end_shift = fields.Boolean(
        string="Can End Shift",
        compute="_compute_can_end_shift"
    )

    @api.depends_context('uid')
    def _compute_can_end_shift(self):
        current_uid = self.env.uid
        is_admin = (
            self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
            self.env.user.has_group('base.group_system') or
            self.env.is_superuser()
        )
        for rec in self:
            is_creator = bool(rec.create_uid and rec.create_uid.id == current_uid)
            is_direct_mgr = bool(rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.user_id and rec.employee_id.parent_id.user_id.id == current_uid)
            is_attendance_mgr = bool(rec.employee_id and rec.employee_id.attendance_manager_id and rec.employee_id.attendance_manager_id.id == current_uid)
            rec.can_end_shift = is_admin or is_creator or is_direct_mgr or is_attendance_mgr

    @api.constrains('start_date', 'end_date')
    def _check_dates_validity(self):
        if self.env.context.get('skip_date_check'):
            return
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.start_date and rec.start_date < today and not rec.create_date:
                raise ValidationError(_("Start Date (%s) cannot be in the past. Please select today (%s) or a future date.") % (rec.start_date, today))
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_("End Date (%s) cannot be earlier than Start Date (%s).") % (rec.end_date, rec.start_date))

    def unlink(self):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.user.has_group('base.group_system') or
                self.env.is_superuser()):
            for rec in self:
                is_creator = bool(rec.create_uid and rec.create_uid.id == self.env.uid)
                is_direct_mgr = bool(rec.employee_id and rec.employee_id.parent_id and rec.employee_id.parent_id.user_id and rec.employee_id.parent_id.user_id.id == self.env.uid)
                is_attendance_mgr = bool(rec.employee_id and rec.employee_id.attendance_manager_id and rec.employee_id.attendance_manager_id.id == self.env.uid)
                if not (is_creator or is_direct_mgr or is_attendance_mgr):
                    raise UserError(_("Only Job Position Officers, Attendance Administrators, or the creating manager can delete Job Position Exceptions."))
        return super(JobPositionException, self.with_context(skip_date_check=True)).unlink()

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

    @api.depends('employee_id', 'shift_id', 'start_date', 'end_date')
    def _compute_job_position_exception_name(self):
        for rec in self:
            emp = rec.employee_id.name or "Employee"
            shift = rec.shift_id.name if rec.shift_id else "Shift"
            s_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else ""
            e_date = rec.end_date.strftime('%Y-%m-%d') if rec.end_date else "Indefinite"
            rec.job_position_exception_name = f"{emp} - {shift} ({s_date} to {e_date})"

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

    @api.depends('employee_id')
    def _compute_job_position(self):
        for record in self:
            record.job_position = record.employee_id.job_position.name or ""

    def _compute_allowed_shift_ids(self):
        for rec in self:
            allowed = self.env.user.sudo()._get_allowed_job_shift_ids()
            rec.allowed_shift_ids = [(6, 0, allowed)]

    start_time = fields.Float(string="Start Time", compute="_compute_shift_details", store=True, readonly=True)
    end_time = fields.Float(string="End Time", compute="_compute_shift_details", store=True, readonly=True)
    duration = fields.Float(string="Net Worked Duration (Hours)", compute="_compute_shift_details", store=True, readonly=True)
    has_lunch_break = fields.Boolean(string="Includes Lunch Break", compute="_compute_shift_details", store=True, readonly=True)
    morning_window = fields.Char(string="Morning Shift Window", compute="_compute_shift_details", store=True, readonly=True)
    lunch_window = fields.Char(string="Lunch Break Window", compute="_compute_shift_details", store=True, readonly=True)
    afternoon_window = fields.Char(string="Afternoon Shift Window", compute="_compute_shift_details", store=True, readonly=True)
    time_range = fields.Char(string="Time Range", compute="_compute_shift_details", store=True, readonly=True)

    @api.depends('shift_id', 'shift_id.start_time', 'shift_id.end_time', 'shift_id.has_lunch_break', 'shift_id.lunch_start_time', 'shift_id.lunch_duration', 'shift_id.is_night_shift')
    def _compute_shift_details(self):
        def _format_decimal_time(float_val):
            if float_val is None or float_val is False:
                return "00:00"
            val = float(float_val) % 24.0
            h = int(val)
            m = int(round((val - h) * 60))
            if m >= 60:
                h = (h + 1) % 24
                m = 0
            return f"{h:02d}:{m:02d}"

        for rec in self:
            s = rec.shift_id
            if not s:
                rec.start_time = 0.0
                rec.end_time = 0.0
                rec.duration = 0.0
                rec.has_lunch_break = False
                rec.morning_window = "-"
                rec.lunch_window = "No Lunch Break"
                rec.afternoon_window = "-"
                rec.time_range = "-"
                continue

            rec.start_time = s.start_time
            rec.end_time = s.end_time
            rec.has_lunch_break = s.has_lunch_break

            gross = s.end_time - s.start_time
            if s.is_night_shift or gross < 0:
                gross += 24.0

            lunch_deduction = s.lunch_duration if s.has_lunch_break else 0.0
            rec.duration = max(0.0, round(gross - lunch_deduction, 2))

            start_str = _format_decimal_time(s.start_time)
            end_str = _format_decimal_time(s.end_time)

            if s.has_lunch_break and s.lunch_start_time:
                l_start_str = _format_decimal_time(s.lunch_start_time)
                l_end = s.lunch_start_time + (s.lunch_duration or 1.0)
                l_end_str = _format_decimal_time(l_end)

                rec.morning_window = f"{start_str} - {l_start_str}"
                rec.lunch_window = f"{l_start_str} - {l_end_str} ({s.lunch_duration or 1.0:g}h break)"
                rec.afternoon_window = f"{l_end_str} - {end_str}"
                rec.time_range = f"{start_str} - {end_str} (Lunch: {l_start_str} - {l_end_str})"
            else:
                rec.morning_window = f"{start_str} - {end_str}"
                rec.lunch_window = "No Lunch Break"
                rec.afternoon_window = "N/A"
                rec.time_range = f"{start_str} - {end_str}"

    @api.constrains('employee_id', 'shift_id', 'status', 'active')
    def _check_duplicate_exception(self):
        for record in self:
            if not record.employee_id or not record.shift_id:
                continue

            assigner_emp = self.env.user.employee_id or (self.env.user.employee_ids[0] if self.env.user.employee_ids else False)
            assigner_ou = assigner_emp.default_operating_unit_id if assigner_emp else False
            assigner_dept = assigner_emp.department_id if assigner_emp else False

            emp_ou = record.employee_id.default_operating_unit_id
            emp_dept = record.employee_id.department_id
            if not record.shift_id.is_applicable_for(
                operating_unit=emp_ou,
                department=emp_dept,
                assigner_operating_unit=assigner_ou,
                assigner_department=assigner_dept
            ):
                raise ValidationError(
                    _(
                        "The selected shift '%s' is not configured to apply to employee %s's "
                        "operating unit/department nor to assigner %s's operating unit/department."
                    ) % (
                        record.shift_id.name,
                        record.employee_id.name,
                        self.env.user.name
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
        warning = None
        today = fields.Date.context_today(self)
        if self.shift_id:
            self.status = 'active'
        if self.employee_id:
            open_att = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
                ('check_out', '=', False)
            ], limit=1)
            if open_att and self.start_date and self.start_date <= today:
                tomorrow = today + datetime.timedelta(days=1)
                self.start_date = tomorrow
                warning = {
                    'title': _("Active Attendance Notice"),
                    'message': _(
                        "Notice: Employee '%s' is currently checked in for today (%s).\n\n"
                        "You cannot assign or change today's shift while they are actively working. "
                        "The Start Date has been automatically set to TOMORROW (%s)."
                    ) % (self.employee_id.name, today.strftime('%Y-%m-%d'), tomorrow.strftime('%Y-%m-%d'))
                }
            ou_id = self.employee_id.default_operating_unit_id.id if self.employee_id.default_operating_unit_id else False
            dept_id = self.employee_id.department_id.id if self.employee_id.department_id else False
            allowed_ids = self.env['job.shift'].get_allowed_shift_ids(operating_unit_id=ou_id, department_id=dept_id)
            res = {'domain': {'shift_id': [('id', 'in', allowed_ids)]}}
            if warning:
                res['warning'] = warning
            return res
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

    def action_end_shift(self):
        """Ends shift exception, sets status inactive, and archives the exception record."""
        self.ensure_one()
        if not self.can_end_shift:
            raise UserError(_("Only System/Attendance Administrators or the manager who created this exception can end it."))

        today_date = fields.Date.context_today(self)
        _logger.info("Archiving shift exception for employee %s (Shift: %s)", self.employee_id.name, self.shift_id.name if self.shift_id else 'N/A')
        
        self.with_context(skip_date_check=True).sudo().write({
            'end_date': today_date,
            'status': 'inactive',
            'active': False,
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Shift Exception Ended & Archived'),
                'message': _('The shift exception has been archived successfully. Employee schedule has reverted to default.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }


