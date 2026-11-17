from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, time, timedelta
import pytz
import logging

_logger = logging.getLogger(__name__)


class AttendancePreApproval(models.Model):
    _name = 'attendance.preapproval'
    _description = 'Predefined Attendance Exception'
    _inherit = ['mail.thread']
    _rec_name = 'employee_id'

    @api.model
    def init(self):
        super().init()
        try:
            self.env['mail.activity'].sudo().search([('res_model', '=', 'attendance.preapproval')]).unlink()
        except Exception:
            pass

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

    target_session = fields.Selection([
        ('morning', 'Morning Session'),
        ('afternoon', 'Afternoon Session'),
        ('single_shift', 'Shift Session (Continuous / Saturday)'),
    ], string="Session", required=True, default='morning', index=True)

    shift_name = fields.Char(string="Scheduled Shift", compute="_compute_schedule_info", store=True)
    scheduled_shift_start = fields.Float(string="Shift Start", compute="_compute_schedule_info", store=True)
    scheduled_shift_end = fields.Float(string="Shift End", compute="_compute_schedule_info", store=True)
    has_lunch_break = fields.Boolean(string="Has Lunch Break", compute="_compute_schedule_info", store=True)
    lunch_start = fields.Float(string="Lunch Start", compute="_compute_schedule_info", store=True)
    lunch_end = fields.Float(string="Lunch End", compute="_compute_schedule_info", store=True)

    approval_reason = fields.Text(required=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    start_time = fields.Float(string="Start Time", required=True, default=8.0)
    end_time = fields.Float(string="End Time", required=True, default=17.0)

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
    is_utilized = fields.Boolean(
        string="Utilized",
        default=False,
        readonly=True,
        index=True,
        help="Set to True only when employee actually checks in late or checks out early using this preapproval."
    )
    utilization_attendance_id = fields.Many2one(
        'hr.attendance',
        string="Used In Attendance",
        readonly=True,
        index=True
    )
    time_range = fields.Char(compute='_compute_time_range', store=True)
    is_manager_or_admin = fields.Boolean(
        compute='_compute_is_manager_or_admin',
        string="Is Manager or Admin"
    )

    @api.depends('employee_id', 'date')
    def _compute_schedule_info(self):
        for rec in self:
            if rec.employee_id and rec.date:
                try:
                    target_date = fields.Date.to_date(rec.date)
                    sched = rec.employee_id._resolve_employee_full_schedule(target_date=target_date)
                    rec.shift_name = sched.get('shift_name') or 'Standard Shift'
                    rec.scheduled_shift_start = sched.get('shift_start', 8.0)
                    rec.scheduled_shift_end = sched.get('shift_end', 17.0)
                    rec.has_lunch_break = bool(sched.get('has_lunch', False))
                    rec.lunch_start = sched.get('lunch_start', 12.0)
                    rec.lunch_end = sched.get('lunch_end', 13.0)
                except Exception as e:
                    _logger.warning("Error computing schedule info for preapproval: %s", e)
                    rec.shift_name = 'Standard Shift'
                    rec.scheduled_shift_start = 8.0
                    rec.scheduled_shift_end = 17.0
                    rec.has_lunch_break = True
                    rec.lunch_start = 12.0
                    rec.lunch_end = 13.0
            else:
                rec.shift_name = ''
                rec.scheduled_shift_start = 8.0
                rec.scheduled_shift_end = 17.0
                rec.has_lunch_break = True
                rec.lunch_start = 12.0
                rec.lunch_end = 13.0

    @api.onchange('employee_id', 'date', 'exception_type', 'target_session')
    def _onchange_schedule_and_times(self):
        if not self.employee_id or not self.date:
            return
        target_date = fields.Date.to_date(self.date)
        sched = self.employee_id._resolve_employee_full_schedule(target_date=target_date)
        has_lunch = bool(sched.get('has_lunch', False))
        self.has_lunch_break = has_lunch
        self.shift_name = sched.get('shift_name') or ''
        self.scheduled_shift_start = sched.get('shift_start', 8.0)
        self.scheduled_shift_end = sched.get('shift_end', 17.0)
        self.lunch_start = sched.get('lunch_start', 12.0)
        self.lunch_end = sched.get('lunch_end', 13.0)

        if not has_lunch:
            self.target_session = 'single_shift'
        elif self.target_session == 'single_shift':
            self.target_session = 'morning'

        s_start = sched.get('shift_start', 8.0)
        s_end = sched.get('shift_end', 17.0)
        l_start = sched.get('lunch_start', 12.0)
        l_end = sched.get('lunch_end', 13.0)

        if self.exception_type == 'predefined_late':
            if self.target_session == 'morning':
                self.start_time = s_start
                if not self.end_time or self.end_time <= s_start or self.end_time > l_start:
                    self.end_time = min(s_start + 1.0, l_start)
            elif self.target_session == 'afternoon':
                self.start_time = l_end
                if not self.end_time or self.end_time <= l_end or self.end_time > s_end:
                    self.end_time = min(l_end + 1.0, s_end)
            else:  # single_shift
                self.start_time = s_start
                if not self.end_time or self.end_time <= s_start or self.end_time > s_end:
                    self.end_time = min(s_start + 1.0, s_end)

        elif self.exception_type == 'predefined_early_exit':
            if self.target_session == 'morning':
                self.end_time = l_start
                if not self.start_time or self.start_time >= l_start or self.start_time < s_start:
                    self.start_time = max(l_start - 1.0, s_start)
            elif self.target_session == 'afternoon':
                self.end_time = s_end
                if not self.start_time or self.start_time >= s_end or self.start_time < l_end:
                    self.start_time = max(s_end - 1.0, l_end)
            else:  # single_shift
                self.end_time = s_end
                if not self.start_time or self.start_time >= s_end or self.start_time < s_start:
                    self.start_time = max(s_end - 1.0, s_start)

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
    @api.constrains('date', 'start_time', 'end_time', 'target_session', 'exception_type', 'employee_id')
    def _check_time_validity(self):
        user_tz = pytz.timezone(self.env.user.tz or 'Africa/Addis_Ababa')
        mock_now = self.env.context.get('mock_now_utc')
        if mock_now:
            if isinstance(mock_now, str):
                mock_now = fields.Datetime.to_datetime(mock_now)
            now = pytz.utc.localize(mock_now).astimezone(user_tz)
        else:
            now = datetime.now(user_tz)
        today = now.date()
        current_time_float = now.hour + (now.minute / 60.0) + (now.second / 3600.0)

        for rec in self:
            rec_date = fields.Date.to_date(rec.date)
            _logger.info("Validating preapproval for %s on %s (Session: %s, Type: %s)",
                         rec.employee_id.name, rec_date, rec.target_session, rec.exception_type)

            if rec.start_time >= rec.end_time:
                raise ValidationError(_("Start time must be strictly earlier than End time."))

            if rec_date < today:
                raise ValidationError(_("Pre-approval cannot be requested for past dates. For missed or late attendance on past days, please use the Manual Attendance Entry workflow."))

            sched = rec.employee_id._resolve_employee_full_schedule(target_date=rec_date)
            if sched.get('is_day_off', False):
                raise ValidationError(_("Cannot request predefined attendance on a non-working day (%s).") % (sched.get('shift_name') or 'Day Off'))

            s_start = sched.get('shift_start', 8.0)
            s_end = sched.get('shift_end', 17.0)
            has_lunch = bool(sched.get('has_lunch', False))
            l_start = sched.get('lunch_start', 12.0)
            l_end = sched.get('lunch_end', 13.0)

            # Session compatibility check
            if not has_lunch and rec.target_session != 'single_shift':
                raise ValidationError(_("This employee's shift on %s does not have a lunch break. Target session must be 'Shift Session'.") % rec.date)
            if has_lunch and rec.target_session == 'single_shift':
                raise ValidationError(_("This employee's shift on %s has a lunch break. Target session must be Morning or Afternoon Session.") % rec.date)

            # Bounds check per session & exception type
            if rec.exception_type == 'predefined_late':
                if rec.target_session == 'morning':
                    if abs(rec.start_time - s_start) > 0.05:
                        raise ValidationError(_("Pre-defined morning lateness start time must match scheduled shift start (%02d:%02d).") % (int(s_start), int(round((s_start % 1) * 60))))
                    if rec.end_time > l_start + 0.05:
                        raise ValidationError(_("Pre-defined morning lateness end time cannot exceed lunch start (%02d:%02d).") % (int(l_start), int(round((l_start % 1) * 60))))
                elif rec.target_session == 'afternoon':
                    if abs(rec.start_time - l_end) > 0.05:
                        raise ValidationError(_("Pre-defined afternoon lateness start time must match afternoon shift start (%02d:%02d).") % (int(l_end), int(round((l_end % 1) * 60))))
                    if rec.end_time > s_end + 0.05:
                        raise ValidationError(_("Pre-defined afternoon lateness end time cannot exceed shift end (%02d:%02d).") % (int(s_end), int(round((s_end % 1) * 60))))
                else:  # single_shift
                    if abs(rec.start_time - s_start) > 0.05:
                        raise ValidationError(_("Pre-defined lateness start time must match scheduled shift start (%02d:%02d).") % (int(s_start), int(round((s_start % 1) * 60))))
                    if rec.end_time > s_end + 0.05:
                        raise ValidationError(_("Pre-defined lateness end time cannot exceed shift end (%02d:%02d).") % (int(s_end), int(round((s_end % 1) * 60))))

            elif rec.exception_type == 'predefined_early_exit':
                if rec.target_session == 'morning':
                    if abs(rec.end_time - l_start) > 0.05:
                        raise ValidationError(_("Pre-defined morning early exit end time must match lunch start (%02d:%02d).") % (int(l_start), int(round((l_start % 1) * 60))))
                    if rec.start_time < s_start - 0.05:
                        raise ValidationError(_("Pre-defined morning early exit departure cannot be earlier than shift start (%02d:%02d).") % (int(s_start), int(round((s_start % 1) * 60))))
                elif rec.target_session == 'afternoon':
                    if abs(rec.end_time - s_end) > 0.05:
                        raise ValidationError(_("Pre-defined afternoon early exit end time must match shift end (%02d:%02d).") % (int(s_end), int(round((s_end % 1) * 60))))
                    if rec.start_time < l_end - 0.05:
                        raise ValidationError(_("Pre-defined afternoon early exit departure cannot be earlier than afternoon shift start (%02d:%02d).") % (int(l_end), int(round((l_end % 1) * 60))))
                else:  # single_shift
                    if abs(rec.end_time - s_end) > 0.05:
                        raise ValidationError(_("Pre-defined early exit end time must match shift end (%02d:%02d).") % (int(s_end), int(round((s_end % 1) * 60))))
                    if rec.start_time < s_start - 0.05:
                        raise ValidationError(_("Pre-defined early exit departure cannot be earlier than shift start (%02d:%02d).") % (int(s_start), int(round((s_start % 1) * 60))))

            # Same-day checks
            if rec_date == today:
                # 1. Check-in state validation
                start_today = datetime.combine(today, time.min)
                end_today = datetime.combine(today, time.max)
                utc_start = user_tz.localize(start_today).astimezone(pytz.utc).replace(tzinfo=None)
                utc_end = user_tz.localize(end_today).astimezone(pytz.utc).replace(tzinfo=None)

                today_attendances = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('check_in', '>=', utc_start),
                    ('check_in', '<=', utc_end),
                ], order='check_in asc')

                if rec.exception_type == 'predefined_late':
                    # Predefined checkin/lateness: employee must NOT have already checked in for that session!
                    if rec.target_session in ('morning', 'single_shift'):
                        if today_attendances:
                            raise ValidationError(_("Cannot request pre-approved lateness for morning session: You have already checked in today."))
                    elif rec.target_session == 'afternoon':
                        afternoon_att = False
                        for att in today_attendances:
                            local_in = pytz.utc.localize(att.check_in).astimezone(user_tz)
                            in_hour = local_in.hour + (local_in.minute / 60.0) + (local_in.second / 3600.0)
                            if in_hour >= (l_end - 0.5):
                                afternoon_att = True
                                break
                        if afternoon_att or len(today_attendances) >= 2:
                            raise ValidationError(_("Cannot request pre-approved lateness for afternoon session: You have already checked in for the afternoon session today."))

                elif rec.exception_type == 'predefined_early_exit':
                    # Predefined early exit: employee MUST have an active check-in for that session!
                    open_att = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('check_out', '=', False),
                    ], limit=1)

                    if not open_att:
                        raise ValidationError(_("Cannot request pre-approved early exit: You do not have an active open check-in session."))

                    if rec.target_session == 'morning':
                        local_in = pytz.utc.localize(open_att.check_in).astimezone(user_tz)
                        in_hour = local_in.hour + (local_in.minute / 60.0) + (local_in.second / 3600.0)
                        if in_hour >= (l_start - 0.05):
                            raise ValidationError(_("Cannot request pre-approved morning early exit: Your active check-in is not a morning session."))

                # 2. Advance notice window: strictly enforced during creation/submission
                if rec.state in ('draft', 'requested'):
                    if rec.exception_type == 'predefined_late':
                        if rec.target_session in ('morning', 'single_shift'):
                            # Employees on bank intranet cannot request same-day morning lateness from home after shift starts.
                            # It must be requested prior to shift start (or in advance on a prior day).
                            if current_time_float >= s_start:
                                raise ValidationError(_("Pre-approved lateness for the morning session must be requested in advance before the shift start (%02d:%02d). For unapproved late arrival today, please use the Manual Attendance Entry workflow upon reporting to your direct coach.") % (int(s_start), int(round((s_start % 1) * 60))))
                        elif rec.target_session == 'afternoon':
                            # Afternoon lateness can be requested during morning work, but must be submitted before afternoon shift starts (lunch_end)
                            if current_time_float >= l_end:
                                raise ValidationError(_("Pre-approved lateness for the afternoon session must be requested before the afternoon shift start (%02d:%02d).") % (int(l_end), int(round((l_end % 1) * 60))))
                            if current_time_float >= rec.end_time:
                                raise ValidationError(_("Pre-approved lateness must be requested before your planned arrival time (%02d:%02d).") % (int(rec.end_time), int(round((rec.end_time % 1) * 60))))

                    elif rec.exception_type == 'predefined_early_exit':
                        if current_time_float >= rec.start_time:
                            raise ValidationError(_("Pre-approved early exit must be requested before your departure time (%02d:%02d).") % (int(rec.start_time), int(round((rec.start_time % 1) * 60))))

            # Overlap check for same employee, date, and target_session
            conflict = self.search([
                ('id', '!=', rec.id),
                ('active', '=', True),
                ('employee_id', '=', rec.employee_id.id),
                ('date', '=', rec.date),
                ('target_session', '=', rec.target_session),
                ('state', 'in', ['draft', 'requested', 'approved']),
                ('start_time', '<', rec.end_time),
                ('end_time', '>', rec.start_time)
            ], limit=1)

            if conflict:
                raise ValidationError(_("This time window overlaps with another pre-approval for the same session (%s).") % conflict.time_range)

    # ---------------------------
    # System Notification Helper (Odoo Discuss System Bot Chat)
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

    def _send_system_notification(self, target_user, html_body, sender_user=None):
        """ Posts a notification directly to the target user. If sender_user is provided,
            it sends the message from that user so Discuss shows their actual name and avatar. """
        if not target_user or not target_user.partner_id:
            return
        try:
            from markupsafe import Markup
            if sender_user and sender_user.partner_id:
                author_user = sender_user
                channel = self.env['discuss.channel'].sudo().with_user(author_user)._get_or_create_chat(
                    partners_to=[target_user.partner_id.id, author_user.partner_id.id]
                )
            else:
                author_user = self.env.ref('base.user_root', raise_if_not_found=False) or self.env.ref('base.user_admin')
                channel = self.env['discuss.channel'].sudo().with_user(author_user)._get_or_create_chat(
                    partners_to=[target_user.partner_id.id]
                )
            if channel:
                channel.sudo().with_user(author_user).message_post(
                    body=Markup(html_body),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception as e:
            _logger.warning(f"Could not send system notification message: {e}")

    # ---------------------------
    # Workflow
    # ---------------------------
    def action_submit(self):
        mgr_name = "Supervisor"
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_("Only draft requests can be submitted."))
            # Strictly validate advance notice and schedule constraints at submission time
            rec._check_time_validity()
            rec.write({'state': 'requested'})
            emp_sudo = rec.employee_id.sudo()
            sender_user = emp_sudo.user_id or self.env.user
            mgr_user = rec._get_manager_user(emp_sudo)
            if mgr_user and mgr_user.partner_id:
                mgr_name = (mgr_user.employee_id.name if mgr_user.employee_id else mgr_user.name) or "Manager"
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                session_label = dict(rec._fields['target_session'].selection).get(rec.target_session, rec.target_session)
                dm_body = f"""
<p>Dear {mgr_name},</p>
<p>A new Predefined Attendance Request has been submitted with the following details:</p>
<p><b>Requester Name:</b> {emp_sudo.name}<br/>
<b>Request Type:</b> {type_label}<br/>
<b>Session:</b> {session_label}<br/>
<b>Shift:</b> {rec.shift_name or 'Standard'}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Reason:</b> {rec.approval_reason or 'N/A'}</p>
<p>Kindly review and process.</p>
"""
                rec._send_system_notification(mgr_user, dm_body, sender_user=sender_user)

        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _('Predefined Request Submitted to %s') % mgr_name,
                'subtitle': _('Pending Supervisor Review'),
                'type': 'success',
                'icon': 'fa-paper-plane',
                'reload': True,
            }
        }

    def action_approve(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_uid = self.env.uid
        user_emp = self.env.user.employee_id
        emp_name = "Employee"
        for rec in self:
            if rec.state != 'requested':
                raise ValidationError(_("Only requests in 'Submitted' status can be approved."))
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False

            # Strict Anti-Self-Approval
            if (emp_user and emp_user.id == current_uid) or (user_emp and emp.id == user_emp.id) or (rec.create_uid.id == current_uid):
                raise ValidationError(_("You cannot approve your own predefined attendance request. Approval must come from your supervisor, coach, or another administrator."))

            is_manager = False
            if emp:
                if emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == current_uid:
                    is_manager = True
                elif emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == current_uid:
                    is_manager = True

            if not (is_admin or is_manager):
                raise ValidationError(_("Only the employee's manager or an administrator can approve this request."))

            rec.write({
                'state': 'approved',
                'approved_by': current_uid
            })

            # Send Notification directly to Requester in Odoo Discuss via System Bot
            emp_target_user = rec.employee_id.user_id or rec.create_uid
            if emp_target_user and emp_target_user.partner_id:
                approver_name = self.env.user.employee_id.name or self.env.user.name
                emp_name = (rec.employee_id.name if rec.employee_id else emp_target_user.name) or "Colleague"
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                session_label = dict(rec._fields['target_session'].selection).get(rec.target_session, rec.target_session)
                dm_body = f"""
<p>Dear {emp_name},</p>
<p>Your Predefined Attendance Request has been <b>APPROVED</b>:</p>
<p><b>Request Type:</b> {type_label}<br/>
<b>Session:</b> {session_label}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Approved By:</b> {approver_name}</p>
<p>Thank you.</p>
"""
                rec._send_system_notification(emp_target_user, dm_body, sender_user=self.env.user)

        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _('Predefined Request Approved'),
                'subtitle': _('Permission active for %s') % emp_name,
                'type': 'success',
                'icon': 'fa-check',
                'reload': True,
            }
        }

    def action_reject(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_uid = self.env.uid
        emp_name = "Employee"
        for rec in self:
            if rec.state != 'requested':
                raise ValidationError(_("Only requests in 'Submitted' status can be rejected."))
            emp = rec.employee_id
            is_manager = False
            if emp:
                if emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == current_uid:
                    is_manager = True
                elif emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == current_uid:
                    is_manager = True

            if not (is_admin or is_manager):
                raise ValidationError(_("Only the employee's manager or an administrator can reject this request."))

            rec.write({'state': 'rejected'})

            # Send Notification directly to Requester in Odoo Discuss via System Bot
            emp_target_user = rec.employee_id.user_id or rec.create_uid
            if emp_target_user and emp_target_user.partner_id:
                rejecter_name = self.env.user.employee_id.name or self.env.user.name
                emp_name = (rec.employee_id.name if rec.employee_id else emp_target_user.name) or "Colleague"
                type_label = dict(rec._fields['exception_type'].selection).get(rec.exception_type, rec.exception_type)
                session_label = dict(rec._fields['target_session'].selection).get(rec.target_session, rec.target_session)
                dm_body = f"""
<p>Dear {emp_name},</p>
<p>Your Predefined Attendance Request has been <b style="color:red;">REJECTED</b>:</p>
<p><b>Request Type:</b> {type_label}<br/>
<b>Session:</b> {session_label}<br/>
<b>Date:</b> {rec.date}<br/>
<b>Time Window:</b> {rec.time_range}<br/>
<b>Rejected By:</b> {rejecter_name}</p>
<p>Please contact your manager for further details.</p>
"""
                rec._send_system_notification(emp_target_user, dm_body, sender_user=self.env.user)

        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _('Predefined Request Rejected'),
                'subtitle': _('Notification sent to %s') % emp_name,
                'type': 'warning',
                'icon': 'fa-times',
                'reload': True,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
        current_emp = self.env.user.employee_id
        if not current_emp:
            current_emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)

        for vals in vals_list:
            if not is_admin and current_emp and 'employee_id' not in vals:
                vals['employee_id'] = current_emp.id
            if 'employee_id' not in vals:
                def_emp = self._default_employee_id()
                if def_emp:
                    vals['employee_id'] = def_emp

            target_date = fields.Date.to_date(vals.get('date') or fields.Date.context_today(self))
            vals['date'] = target_date

            emp_id = vals.get('employee_id')
            exc_type = vals.get('exception_type')
            session = vals.get('target_session', 'morning')

            if emp_id and target_date:
                emp = self.env['hr.employee'].sudo().browse(emp_id)
                sched = emp._resolve_employee_full_schedule(target_date=target_date)
                s_start = sched.get('shift_start', 8.0)
                s_end = sched.get('shift_end', 17.0)
                l_start = sched.get('lunch_start', 12.0)
                l_end = sched.get('lunch_end', 13.0)

                # Ensure start_time / end_time are correctly auto-anchored even if web client omitted readonly fields
                if exc_type == 'predefined_late':
                    if session == 'morning':
                        vals['start_time'] = s_start
                    elif session == 'afternoon':
                        vals['start_time'] = l_end
                    else:
                        vals['start_time'] = s_start

                    if not vals.get('end_time') or vals.get('end_time') <= vals['start_time']:
                        vals['end_time'] = min(vals['start_time'] + 1.0, s_end)

                elif exc_type == 'predefined_early_exit':
                    if session == 'morning':
                        vals['end_time'] = l_start
                    elif session == 'afternoon':
                        vals['end_time'] = s_end
                    else:
                        vals['end_time'] = s_end

                    if not vals.get('start_time') or vals.get('start_time') >= vals['end_time']:
                        vals['start_time'] = max(vals['end_time'] - 1.0, s_start)

        return super().create(vals_list)

    def write(self, vals):
        op_fields = {'employee_id', 'exception_type', 'target_session', 'approval_reason', 'date', 'start_time', 'end_time'}
        is_op_change = bool(op_fields.intersection(vals.keys()))
        for rec in self:
            if rec.state != 'draft' and is_op_change:
                raise ValidationError(_("Once submitted or approved/rejected, request details cannot be modified."))

            if is_op_change:
                emp_id = vals.get('employee_id') or rec.employee_id.id
                target_date = fields.Date.to_date(vals.get('date') or rec.date or fields.Date.context_today(self))
                exc_type = vals.get('exception_type') or rec.exception_type
                session = vals.get('target_session') or rec.target_session or 'morning'

                if emp_id and target_date:
                    emp = self.env['hr.employee'].sudo().browse(emp_id)
                    sched = emp._resolve_employee_full_schedule(target_date=target_date)
                    s_start = sched.get('shift_start', 8.0)
                    s_end = sched.get('shift_end', 17.0)
                    l_start = sched.get('lunch_start', 12.0)
                    l_end = sched.get('lunch_end', 13.0)

                    if exc_type == 'predefined_late':
                        if session == 'morning':
                            vals['start_time'] = s_start
                        elif session == 'afternoon':
                            vals['start_time'] = l_end
                        else:
                            vals['start_time'] = s_start

                    elif exc_type == 'predefined_early_exit':
                        if session == 'morning':
                            vals['end_time'] = l_start
                        elif session == 'afternoon':
                            vals['end_time'] = s_end
                        else:
                            vals['end_time'] = s_end

        return super().write(vals)
