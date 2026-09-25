# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
import logging
import math
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class HrLeaveInheritCustom(models.Model):
    _inherit = 'hr.leave'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        ctx = self.env.context
        employee = self._get_current_employee()
        if employee:
            defaults['employee_id'] = employee.id
            try:
                fetch_vals = self._get_employee_fetch_values(employee)
                defaults.update(fetch_vals)
            except Exception as e:
                _logger.error(f"Error auto-fetching employee data on New: {str(e)}")

        defaults['holiday_status_id'] = ctx.get('default_holiday_status_id', False)
        defaults['leave_start_date'] = ctx.get('default_leave_start_date', False)
        defaults['leave_end_date'] = ctx.get('default_leave_end_date', False)
        defaults['starting_half_day'] = ctx.get('default_starting_half_day', False)
        defaults['ending_half_day'] = ctx.get('default_ending_half_day', False)
        defaults['half_day'] = ctx.get('default_half_day', False)
        defaults['comments'] = ctx.get('default_comments', False)
        defaults['attachment'] = ctx.get('default_attachment', False)
        defaults['attachment_name'] = ctx.get('default_attachment_name', False)
        defaults['delegated_employee_id'] = ctx.get('default_delegated_employee_id', False)
        defaults['computed_leave'] = ctx.get('default_computed_leave', 0.0)
        defaults['number_of_days'] = ctx.get('default_number_of_days', 0.0)
        defaults['single_half_day_period'] = ctx.get('default_single_half_day_period', 'am')
        defaults['multi_half_day_period'] = ctx.get('default_multi_half_day_period', False)
        defaults['is_computed'] = ctx.get('default_is_computed', True)
        defaults['custom_saved'] = ctx.get('default_custom_saved', False)
        defaults['is_edit_mode'] = ctx.get('default_is_edit_mode', False)
        defaults['leave_request_status'] = ctx.get('default_leave_request_status', 'fetch')

        defaults['date_from'] = False
        defaults['date_to'] = False
        defaults['request_date_from'] = False
        defaults['request_date_to'] = False

        return defaults

    @api.depends('employee_id', 'holiday_status_id', 'leave_start_date', 'leave_end_date')
    def _compute_display_name(self):
        for leave in self:
            leave.display_name = _('Leave Request')

    def _get_current_employee(self):
        user = self.env.user
        employee = user.employee_id
        if not employee:
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
        return employee

    def _get_active_contract(self, employee):
        for model_name in ('hr.version', 'hr.contract'):
            if model_name not in self.env.registry.models:
                continue
            try:
                contract = self.env[model_name].sudo().search(
                    [('employee_id', '=', employee.id)],
                    limit=1, order='id desc',
                )
                if contract:
                    return contract
            except Exception as e:
                _logger.warning(f"Could not look up {model_name} for employee {employee.id}: {str(e)}")
        return False

    @staticmethod
    def _to_display_text(value):
        if not value:
            return ''
        if hasattr(value, '_name') and hasattr(value, 'display_name'):
            return value.display_name or value.name or ''
        return str(value)

    def _get_employee_fetch_values(self, employee):
        if not employee:
            return {}
        employee = employee.sudo()

        job_pos = ''
        if hasattr(employee, 'job_id') and employee.job_id:
            job_pos = employee.job_id.name
        elif hasattr(employee, 'job_title') and employee.job_title:
            job_pos = self._to_display_text(employee.job_title)
        elif hasattr(employee, 'job_position') and employee.job_position:
            job_pos = self._to_display_text(employee.job_position)

        job_grd = ''
        if hasattr(employee, 'job_grade') and employee.job_grade:
            job_grd = self._to_display_text(employee.job_grade)
        elif hasattr(employee, 'grade_id') and employee.grade_id:
            job_grd = employee.grade_id.name

        job_cat = self._to_display_text(self._get_employee_category(employee))

        op_unit = False
        if hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            op_unit = employee.default_operating_unit_id.id
        elif hasattr(employee, 'operating_unit') and employee.operating_unit:
            op_unit = employee.operating_unit.id
        elif hasattr(employee, 'operating_unit_ids') and employee.operating_unit_ids:
            op_unit = employee.operating_unit_ids[0].id

        balances = self._get_leave_balances(employee)

        return {
            'employee_id': employee.id,
            'requester_name': employee.name or '',
            'job_position': job_pos,
            'job_grade': job_grd,
            'job_category': job_cat,
            'operating_unit': op_unit,
            'accrued_leave_balance': balances.get('accrued', 0.0),
            'scheduled_leave_balance': balances.get('scheduled', 0.0),
            'computed_leave': 0.0,
            'fetch_status': 'fetched',
            'leave_request_status': 'fetch',
        }

    holiday_status_id = fields.Many2one('hr.leave.type', string='Leave Reason', default=False)
    support_document = fields.Boolean(string='Require Supporting Document', related='holiday_status_id.support_document', readonly=True)
    is_exact_days = fields.Boolean(string='Exact Days Required', compute='_compute_is_exact_days')
    is_duration_readonly = fields.Boolean(string='Duration Readonly', compute='_compute_is_duration_readonly')
    is_single_half_day = fields.Boolean(string='Is Single Half Day', compute='_compute_half_day_visibility')
    is_multi_half_day = fields.Boolean(string='Is Multi Half Day', compute='_compute_half_day_visibility')
    single_half_day_period = fields.Selection([('am', 'Morning'), ('pm', 'Afternoon')], string='Half Day Period', default='am')
    multi_half_day_period = fields.Selection([('full_day', 'Full Day'), ('start', 'Starting Half Day (Starts in Afternoon)')], string='Select Half Day', default=False)

    operating_unit = fields.Many2one('operating.unit', string='Operating Unit')
    job_grade = fields.Char(string='Job Grade', readonly=True)
    job_category = fields.Char(string='Job Category', readonly=True)
    job_position = fields.Char(string='Job Position', readonly=True)

    leave_request_description = fields.Text(string='Leave Request Description')
    delegated_employee_id = fields.Many2one('hr.employee', string='Delegated Employee')
    requester_name = fields.Char(string='Requester Name', readonly=True)
    accrued_leave_balance = fields.Float(string='Accrued Leave Balance', digits=(16, 2), default=0.0, readonly=True)
    scheduled_leave_balance = fields.Float(string='Scheduled Leave Balance', digits=(16, 2), default=0.0, readonly=True)
    computed_leave = fields.Float(string='Computed Leave', digits=(16, 2), default=0.0, readonly=True)
    attachment = fields.Binary(string='Attachment')
    attachment_name = fields.Char(string='Attachment Name')
    comments = fields.Text(string='Comments')
    starting_half_day = fields.Boolean(string='Starting Half Day')
    ending_half_day = fields.Boolean(string='Ending Half Day')
    half_day = fields.Boolean(string='Half day')
    fetch_status = fields.Selection([('not_fetched', 'Not Fetched'), ('fetched', 'Fetched')], string='Fetch Status', default='not_fetched')

    leave_start_date = fields.Date(string='Start Date')
    leave_end_date = fields.Date(string='End Date')
    custom_saved = fields.Boolean(string='Is Saved', default=False)
    leave_reference = fields.Char(
        string='Reference No.',
        copy=False,
        readonly=True,
        index=True,
        default='New',
        help="Unique sequential reference assigned the first time this "
             "leave request is saved (e.g. LR-000001).",
    )
    is_edit_mode = fields.Boolean(string='Is Edit Mode', default=False)
    is_computed = fields.Boolean(string='Is Computed', default=True)

    is_hr_admin = fields.Boolean(string='Is Time Off Admin', compute='_compute_button_visibility')
    fields_readonly = fields.Boolean(string='Fields Readonly', compute='_compute_button_visibility')
    show_save_btn = fields.Boolean(string='Show Save', compute='_compute_button_visibility')
    show_discard_btn = fields.Boolean(string='Show Discard', compute='_compute_button_visibility')
    show_edit_btn = fields.Boolean(string='Show Edit', compute='_compute_button_visibility')
    show_notify_btn = fields.Boolean(string='Show Notify', compute='_compute_button_visibility')
    show_approve_btn = fields.Boolean(string='Show Approve', compute='_compute_button_visibility')
    show_cancel_btn = fields.Boolean(string='Show Cancel', compute='_compute_button_visibility')
    show_compute_btn = fields.Boolean(string='Show Compute', compute='_compute_button_visibility')

    employee_id_readonly = fields.Boolean(
        string='Employee Readonly',
        compute='_compute_employee_id_readonly',
    )

    is_suspense_leave_hr = fields.Boolean(
        string='Is Suspense Leave HR',
        compute='_compute_is_suspense_leave_hr',
    )

    @api.depends('date_from', 'date_to', 'resource_calendar_id', 'holiday_status_id.request_unit')
    def _compute_duration(self):
        for record in self:
            if record.computed_leave > 0:
                record.number_of_days = record.computed_leave
            elif record.number_of_days > 0:
                record.computed_leave = record.number_of_days
            else:
                record.number_of_days = 0.0
                record.computed_leave = 0.0
            record.number_of_hours = record.number_of_days * 8.0

    @api.depends('date_from', 'date_to', 'employee_id')
    def _compute_number_of_days(self):
        self._compute_duration()

    def _get_durations(self, check_leave_type=True, resource_calendar=None):
        result = {}
        for leave in self:
            days = leave.computed_leave or leave.number_of_days or 0.0
            hours = days * 8.0
            result[leave.id] = (days, hours)
        return result

    @api.depends('holiday_status_id', 'holiday_status_id.is_exact_days', 'holiday_status_id.exact_days')
    def _compute_is_exact_days(self):
        for record in self:
            ht = record.holiday_status_id
            record.is_exact_days = bool(ht and (ht.is_exact_days or ht.exact_days > 0))

    @api.depends('fields_readonly', 'is_exact_days')
    def _compute_is_duration_readonly(self):
        for record in self:
            record.is_duration_readonly = bool(record.fields_readonly or record.is_exact_days)

    @api.depends('number_of_days', 'half_day', 'starting_half_day', 'ending_half_day', 'leave_start_date', 'leave_end_date')
    def _compute_half_day_visibility(self):
        for record in self:
            days = record.number_of_days
            start_date = record.leave_start_date
            end_date = record.leave_end_date
            is_half = (days == 0.5) or (record.half_day and start_date and end_date and start_date == end_date)
            is_multi = (not is_half) and (days > 0)
            record.is_single_half_day = bool(is_half)
            record.is_multi_half_day = bool(is_multi)

    @api.depends('custom_saved', 'is_edit_mode', 'leave_request_status', 'state')
    def _compute_button_visibility(self):
        is_admin = (
            self.env.user.has_group('hr_holidays.group_hr_holidays_manager') or
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
        )
        for record in self:
            saved = record.custom_saved
            editing = record.is_edit_mode
            status = record.leave_request_status
            state = record.state
            is_submitted = (status == 'notify' or state in ('confirm', 'validate', 'validate1'))

            record.is_hr_admin = is_admin
            record.show_compute_btn = False

            if not saved:
                record.fields_readonly = False
                record.show_save_btn = True
                record.show_notify_btn = True
                record.show_discard_btn = True
                record.show_edit_btn = False
                record.show_approve_btn = False
                record.show_cancel_btn = False
            elif status == 'draft':
                if editing:
                    record.fields_readonly = False
                    record.show_save_btn = True
                    record.show_notify_btn = True
                    record.show_discard_btn = True
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_cancel_btn = False
                else:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = True
                    record.show_discard_btn = True
                    record.show_edit_btn = True
                    record.show_approve_btn = False
                    record.show_cancel_btn = False
            elif is_submitted:
                if not is_admin:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = False
                    record.show_discard_btn = False
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_cancel_btn = False
                else:
                    if editing:
                        record.fields_readonly = False
                        record.show_approve_btn = True
                        record.show_discard_btn = True
                        record.show_save_btn = False
                        record.show_notify_btn = False
                        record.show_edit_btn = False
                        record.show_cancel_btn = False
                    else:
                        record.fields_readonly = True
                        record.show_edit_btn = True
                        record.show_approve_btn = (status == 'notify' and state != 'validate')
                        record.show_cancel_btn = (state == 'validate')
                        record.show_save_btn = False
                        record.show_notify_btn = False
                        record.show_discard_btn = False

    def _is_suspense_leave_type(self, leave_type):
        """Match by name rather than a dedicated boolean field, per current
        config: any hr.leave.type whose name contains 'Suspense Leave'
        (case-insensitive) is treated as Suspense Leave."""
        return bool(leave_type and leave_type.name and 'suspense leave' in leave_type.name.lower())

    @api.depends_context('uid')
    def _compute_is_suspense_leave_hr(self):
        """Dedicated HR group for the Suspense Leave workflow - deliberately
        separate from is_hr_admin (Time Off Administrator/Officer), since
        that group is about the Time Off app in general and may not be held
        by the same people who count as 'HR' for this specific rule."""
        is_hr = self.env.user.has_group('hr_leave_request_custom.group_hr_leave_suspense_hr')
        for record in self:
            record.is_suspense_leave_hr = is_hr

    @api.depends('holiday_status_id', 'is_suspense_leave_hr')
    def _compute_employee_id_readonly(self):
        """Employee is readonly by default for everyone - the requester is
        fixed to the logged-in employee (see default_get). The one
        exception is Suspense Leave: it must be requested by HR on behalf
        of the actual employee taking it, so HR needs to be able to pick
        any employee here rather than being locked to their own record.
        Non-HR users never get this exception - _check_leave_type_constraints()
        also blocks them from saving a Suspense Leave request at all.

        Note: this deliberately does NOT fall back to fields_readonly.
        fields_readonly reflects the general form-editing state (e.g. it's
        False for everyone while a new request is still unsaved), which is
        unrelated to who is allowed to change the requester. Falling back
        to it would unlock Requester Name for any user, on any leave type,
        any time the form itself happens to be editable."""
        for record in self:
            record.employee_id_readonly = not (
                record.is_suspense_leave_hr and record._is_suspense_leave_type(record.holiday_status_id)
            )

    number_of_days = fields.Float(string='Duration (Days)', compute='_compute_number_of_days', store=True, default=0.0, readonly=False)

    @api.constrains('number_of_days', 'computed_leave')
    def _check_number_of_days_format(self):
        """Strictly validates that Duration (Days) ends in .0 or .5 (e.g. 0.5, 1, 1.5, 2, 2.5, 3, etc.)."""
        if self.env.context.get('discard_mode'):
            return
        for record in self:
            days = record.number_of_days
            if not days:
                continue
            if days <= 0:
                raise ValidationError(_("Duration (Days) must be greater than 0."))
            frac = round(days - math.floor(days), 4)
            if frac not in (0.0, 0.5):
                raise ValidationError(_(
                    "Duration (Days) must be a whole number or end in .5 "
                    "(e.g., 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5). Value %s is not allowed.") % days)

    leave_request_status = fields.Selection([
        ('draft', 'Draft'),
        ('fetch', 'Fetch'),
        ('check_leave_balance', 'Check Leave Balance'),
        ('notify', 'Notify'),
    ], default='fetch', string='Leave Balance Status', readonly=True)

    def _sync_datetime_fields(self):
        if not self.leave_start_date:
            self.date_from = False
            self.request_date_from = False
            self.date_to = False
            self.request_date_to = False
            return

        self.request_date_from = self.leave_start_date

        if not self.leave_end_date:
            self.request_date_to = False
            start_dt = fields.Datetime.to_datetime(self.leave_start_date)
            self.date_from = start_dt.replace(hour=0, minute=0, second=0)
            self.date_to = False
            return

        self.request_date_to = self.leave_end_date

        start_dt = fields.Datetime.to_datetime(self.leave_start_date)
        end_dt = fields.Datetime.to_datetime(self.leave_end_date)

        if self.half_day or self.number_of_days == 0.5:
            # Morning and Afternoon slots must not touch at the boundary,
            # otherwise Odoo's inclusive (<=, >=) overlap check treats an AM
            # leave ending at 12:00:00 and a PM leave starting at 12:00:00 as
            # overlapping, even though they don't actually share any time.
            if self.single_half_day_period == 'pm':
                self.date_from = start_dt.replace(hour=12, minute=0, second=0)
                self.date_to = start_dt.replace(hour=18, minute=0, second=0)
            else:
                self.date_from = start_dt.replace(hour=6, minute=0, second=0)
                self.date_to = start_dt.replace(hour=11, minute=59, second=59)
        else:
            if self.starting_half_day:
                self.date_from = start_dt.replace(hour=12, minute=0, second=0)
            else:
                self.date_from = start_dt.replace(hour=0, minute=0, second=0)

            if self.ending_half_day:
                # Same boundary-touching fix as above, applied to the end of a
                # multi-day leave that finishes on a half day.
                self.date_to = end_dt.replace(hour=11, minute=59, second=59)
            else:
                self.date_to = end_dt.replace(hour=23, minute=59, second=59)

    def _get_employee_department(self, employee):
        if not employee:
            return False
        ou = False
        if hasattr(self, 'operating_unit') and self.operating_unit:
            ou = self.operating_unit
        elif hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            ou = employee.default_operating_unit_id
        elif hasattr(employee, 'operating_unit_id') and employee.operating_unit_id:
            ou = employee.operating_unit_id
        elif hasattr(employee, 'operating_unit_ids') and employee.operating_unit_ids:
            ou = employee.operating_unit_ids[0]

        if ou and hasattr(ou, 'department') and ou.department:
            return ou.department

        if hasattr(employee, 'department_id') and employee.department_id:
            return employee.department_id

        return False

    def _get_employee_work_unit_type(self, employee):
        if not employee:
            return False

        ou = False
        if hasattr(self, 'operating_unit') and self.operating_unit:
            ou = self.operating_unit
        elif hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            ou = employee.default_operating_unit_id
        elif hasattr(employee, 'operating_unit_id') and employee.operating_unit_id:
            ou = employee.operating_unit_id
        elif hasattr(employee, 'operating_unit_ids') and employee.operating_unit_ids:
            ou = employee.operating_unit_ids[0]

        if ou and hasattr(ou, 'work_unit_type') and ou.work_unit_type:
            return ou.work_unit_type

        emp_dept = self._get_employee_department(employee)
        dept_name = emp_dept.name.lower() if emp_dept else ''
        ou_name = (ou.name or '') if ou else ''
        combined = f"{dept_name} {ou_name}".lower()
        if any(term in combined for term in ['head office', 'head_office', 'h.o', 'ho']):
            return 'head_office'
        if dept_name:
            return 'branch'
        return False

    def _is_ho_employee(self):
        wut = self._get_employee_work_unit_type(self.employee_id)
        return wut == 'head_office'

    def _get_day_weight_from_holidays(self, date_val):
        if not date_val:
            return False, 1.0
        if not self.holiday_status_id or not self.holiday_status_id.include_public_holidays_in_duration:
            return False, 1.0

        emp_wut = self._get_employee_work_unit_type(self.employee_id)
        wut_domain = ['|', ('work_unit_type', '=', False), ('work_unit_type', '=', emp_wut)] if emp_wut else [
            ('work_unit_type', '=', False)]
        weekday_str = str(date_val.weekday())

        calendar = self.resource_calendar_id or (self.employee_id and self.employee_id.resource_calendar_id)
        calendar_domain = ['|', ('calendar_id', '=', False), ('calendar_id', '=', calendar.id)] if calendar else []

        try:
            domain = [('resource_id', '=', False)] + calendar_domain + wut_domain
            all_holidays = self.env['resource.calendar.leaves'].sudo().search(domain)
            if not all_holidays:
                return False, 1.0

            matching_holidays = []
            day_name_map = {
                'monday': '0', 'tuesday': '1', 'wednesday': '2', 'thursday': '3',
                'friday': '4', 'saturday': '5', 'sunday': '6'
            }
            for h in all_holidays:
                dow = h.day_of_week
                if not dow and h.name:
                    cleaned_name = h.name.strip().lower()
                    if cleaned_name in day_name_map:
                        dow = day_name_map[cleaned_name]

                if dow:
                    if str(dow) == weekday_str:
                        matching_holidays.append(h)
                else:
                    if h.date_from and h.date_to:
                        p_start = fields.Datetime.to_datetime(h.date_from).date()
                        p_end = fields.Datetime.to_datetime(h.date_to).date()
                        if (p_end - p_start).days <= 366 and p_start <= date_val <= p_end:
                            matching_holidays.append(h)

            if not matching_holidays:
                return False, 1.0

            if emp_wut:
                wut_specific = [h for h in matching_holidays if h.work_unit_type and h.work_unit_type == emp_wut]
                if wut_specific:
                    matching_holidays = wut_specific

            target_holiday = matching_holidays[0]
            weight_holiday = getattr(target_holiday, 'holiday_day_weight', 1.0)
            if weight_holiday is False or weight_holiday is None:
                weight_holiday = 1.0

            leave_count_weight = max(0.0, 1.0 - weight_holiday)
            return True, leave_count_weight
        except Exception as e:
            _logger.warning(f"Error checking day weight from holidays: {e}")
            return False, 1.0

    def _get_day_weight(self, date_val):
        if not date_val:
            return 1.0

        if not self.holiday_status_id or not self.holiday_status_id.include_public_holidays_in_duration:
            return 1.0

        has_match, weight = self._get_day_weight_from_holidays(date_val)
        if has_match:
            return weight

        if date_val.weekday() == 6:  # Sunday
            return 0.0

        if date_val.weekday() == 5:  # Saturday
            if self._is_ho_employee():
                return 0.5
            return 1.0

        return 1.0

    def _is_excluded_leave_day(self, date_val):
        if not date_val:
            return False
        if not self.holiday_status_id or not self.holiday_status_id.include_public_holidays_in_duration:
            return False
        w = self._get_day_weight(date_val)
        return w <= 0.0

    _MAX_LOOKAHEAD_DAYS = 730

    @api.onchange('multi_half_day_period')
    def _onchange_multi_half_day_period(self):
        """The Full Day / Starting Half Day radio for multi-day leaves is
        bound directly to this field, but nothing else recomputes the End
        Date and half-day flags when the user toggles it after the duration
        was already set - without this handler the UI keeps showing a stale
        End Date computed under the previous selection."""
        if not self.leave_start_date:
            return

        days = self.number_of_days or self.computed_leave
        if not days or days <= 0 or days == 0.5:
            # 0.5 is a single half-day and doesn't use multi_half_day_period
            return

        end_date, half_vals = self._calculate_end_date_from_days(
            self.leave_start_date, days, self.multi_half_day_period
        )
        self.leave_end_date = end_date
        for k, v in half_vals.items():
            setattr(self, k, v)

        self._sync_datetime_fields()

    @api.onchange('single_half_day_period')
    def _onchange_single_half_day_period(self):
        """The Morning / Afternoon radio for a single half-day leave is bound
        directly to this field, but nothing recomputes date_from/date_to when
        it's toggled. Without this handler, a leave created as 'am' and then
        switched to 'pm' (or vice-versa) keeps the old time slot in
        date_from/date_to, which can make a brand-new PM request collide with
        an existing AM request for the same day (or fail to collide with a
        genuine PM conflict)."""
        self._sync_datetime_fields()

    def _calculate_end_date_from_days(self, start_date, days, multi_half_period='start'):
        if not start_date or days <= 0:
            return False, {'half_day': False, 'starting_half_day': False, 'ending_half_day': False}

        curr_date = start_date
        lookahead = 0
        while self._is_excluded_leave_day(curr_date):
            curr_date += timedelta(days=1)
            lookahead += 1
            if lookahead > self._MAX_LOOKAHEAD_DAYS:
                raise UserError(_("Could not find a valid start date for this leave within 730 days."))

        effective_start_date = curr_date

        if days == 0.5:
            return effective_start_date, {'half_day': True, 'starting_half_day': False, 'ending_half_day': False}

        starts_half = (multi_half_period == 'start')
        epsilon = 1e-4

        remaining = days
        curr_date = effective_start_date
        first_day = True
        lookahead = 0
        ends_half = False

        while True:
            w = self._get_day_weight(curr_date)
            if first_day and starts_half:
                # Only the afternoon of the start day counts toward the total.
                w = min(w, 0.5)
            if remaining <= w + epsilon:
                # This day only needed to supply part of its weight -> it's a half day.
                ends_half = (w - remaining) > epsilon
                break
            remaining -= w
            curr_date += timedelta(days=1)
            first_day = False
            lookahead += 1
            if lookahead > self._MAX_LOOKAHEAD_DAYS:
                raise UserError(_("Could not find a valid end date for this leave within 730 days."))

        end_date = curr_date
        half_vals = {
            'half_day': False,
            'starting_half_day': bool(starts_half),
            'ending_half_day': bool(ends_half),
        }
        return end_date, half_vals

    def _compute_days_preview(self):
        if not self.leave_start_date or not self.leave_end_date:
            return 0.0
        if self.leave_end_date < self.leave_start_date:
            return 0.0

        curr_date = self.leave_start_date
        total_days = 0.0
        while curr_date <= self.leave_end_date:
            w = self._get_day_weight(curr_date)
            total_days += w
            curr_date += timedelta(days=1)

        if self.half_day and self.leave_start_date == self.leave_end_date:
            total_days = 0.5
        else:
            if self.starting_half_day and total_days >= 0.5:
                total_days -= 0.5
            if self.ending_half_day and total_days >= 0.5:
                total_days -= 0.5

        return max(0.0, float_round(total_days, precision_digits=2))

    def _ensure_multi_half_day_default(self):
        if not self.multi_half_day_period:
            self.multi_half_day_period = 'full_day'

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id(self):
        if self.holiday_status_id:
            is_exact = bool(self.holiday_status_id.is_exact_days or self.holiday_status_id.exact_days > 0)
            if is_exact:
                exact = self.holiday_status_id.exact_days
                self.number_of_days = exact
                self.computed_leave = exact
                self._ensure_multi_half_day_default()
                if self.leave_start_date:
                    period = self.multi_half_day_period if (exact % 1 != 0 or (self.starting_half_day and self.ending_half_day)) else False
                    end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, exact, period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
            else:
                if self.leave_start_date and self.leave_end_date:
                    days = self._compute_days_preview()
                    if days > 0:
                        self.number_of_days = days
                        self.computed_leave = days
                    elif self.number_of_days > 0:
                        period = self.multi_half_day_period if (self.number_of_days % 1 != 0 or (self.starting_half_day and self.ending_half_day)) else False
                        end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, self.number_of_days, period)
                        self.leave_end_date = end_date
                        for k, v in half_vals.items():
                            setattr(self, k, v)
                elif self.leave_start_date and self.number_of_days > 0:
                    period = self.multi_half_day_period if (self.number_of_days % 1 != 0 or (self.starting_half_day and self.ending_half_day)) else False
                    end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, self.number_of_days, period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
        self._sync_datetime_fields()

    @api.onchange('leave_start_date')
    def _onchange_leave_start_date(self):
        if self.leave_start_date:
            if self.number_of_days > 0:
                period = self.multi_half_day_period if (self.number_of_days % 1 != 0 or (self.starting_half_day and self.ending_half_day)) else False
                end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, self.number_of_days, period)
                self.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(self, k, v)
                self.computed_leave = self.number_of_days
                self._ensure_multi_half_day_default()
            elif self.leave_end_date:
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
        self._sync_datetime_fields()

    @api.onchange('leave_end_date')
    def _onchange_leave_end_date(self):
        if self.leave_start_date and self.leave_end_date:
            if self.leave_end_date < self.leave_start_date:
                self.number_of_days = 0.0
                self.computed_leave = 0.0
            elif self.leave_end_date == self.leave_start_date:
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
                self.half_day = bool(days == 0.5)
                self.starting_half_day = False
                self.ending_half_day = False
            else:
                self.half_day = False
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
        self._ensure_multi_half_day_default()
        self._sync_datetime_fields()

    @api.onchange('number_of_days')
    def _onchange_number_of_days(self):
        warning = None
        if not self.number_of_days or self.number_of_days <= 0:
            self.number_of_days = 0.0
            self.computed_leave = 0.0
            self._sync_datetime_fields()
            return

        target_days = self.number_of_days
        frac = round(target_days - math.floor(target_days), 4)

        if frac not in (0.0, 0.5):
            warning = {
                'title': _('Invalid Duration'),
                'message': _("Duration (Days) must be a whole number or end in .5 (e.g. 0.5, 1, 1.5, 2). Value %s is not allowed.") % target_days,
            }
        elif self.is_exact_days and self.holiday_status_id and self.holiday_status_id.exact_days > 0:
            exact = self.holiday_status_id.exact_days
            if target_days != exact:
                warning = {
                    'title': _('Exact Days Required'),
                    'message': _("Leave Reason '%s' requires exactly %s day(s). You typed %s.") % (self.holiday_status_id.name, exact, target_days),
                }
        elif self.holiday_status_id and self.holiday_status_id.max_allowed_days > 0:
            max_days = self.holiday_status_id.max_allowed_days
            if target_days > max_days:
                warning = {
                    'title': _('Max Allowed Days Exceeded'),
                    'message': _("Leave Reason '%s' allows a maximum of %s day(s). You typed %s.") % (self.holiday_status_id.name, max_days, target_days),
                }

        self.computed_leave = target_days

        if frac in (0.0, 0.5):
            if target_days == 0.5:
                self.half_day = True
                self.starting_half_day = False
                self.ending_half_day = False
                if self.leave_start_date:
                    self.leave_end_date = self.leave_start_date
            elif target_days > 0 and target_days % 1 != 0:
                self.half_day = False
                if not self.multi_half_day_period:
                    self.multi_half_day_period = 'full_day'
                if self.multi_half_day_period == 'start':
                    self.starting_half_day = True
                    self.ending_half_day = False
                else:
                    self.starting_half_day = False
                    self.ending_half_day = True
                if self.leave_start_date:
                    end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, target_days, self.multi_half_day_period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
            elif target_days >= 1.0 and target_days % 1 == 0:
                self.half_day = False
                if not self.multi_half_day_period:
                    self.multi_half_day_period = 'full_day'
                if self.multi_half_day_period == 'full_day':
                    self.starting_half_day = False
                    self.ending_half_day = False
                else:
                    self.starting_half_day = True
                    self.ending_half_day = True
                if self.leave_start_date:
                    end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, target_days, self.multi_half_day_period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)

            self._sync_datetime_fields()

        if warning:
            return {'warning': warning}

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            for field_name, value in self._get_employee_fetch_values(self.employee_id).items():
                setattr(self, field_name, value)
        else:
            self.fetch_status = 'not_fetched'

    def _check_validity(self):
        """NOTE: this method only covers leave-balance/allocation validation
        (e.g. "you do not have any allocation for this time off type") and
        is UNRELATED to the "already booked time off which overlaps" error -
        that one comes from _check_date() below. Left as the original
        pass-through to native behaviour, just skipped for the same
        edge cases as before (blank/discarded records, explicit skip
        contexts)."""
        if self.env.context.get('discard_mode') or self.env.context.get('leave_skip_date_check') or self.env.context.get('leave_skip_state_check'):
            return
        valid_leaves = self.filtered(lambda l: bool(l.holiday_status_id and l.date_from))
        if not valid_leaves:
            return
        return super(HrLeaveInheritCustom, valid_leaves)._check_validity()

    @api.constrains('date_from', 'date_to', 'employee_id', 'state')
    def _check_date(self):
        """Native Odoo's _check_date() is the ACTUAL source of the generic
        "You've already booked time off which overlaps with this period"
        error (via holiday.dashboard_warning_message). It has no concept of
        Scheduled Leave vs. non-Scheduled Leave, so it must be replaced -
        not just skipped - by _check_scheduled_leave_overlap(), which does.

        Because this is a real @api.constrains, it runs automatically on
        every create/write, including the web client's implicit pre-save
        that happens before any button's server action (action_save_custom,
        etc.) ever runs. Overriding it here - rather than only calling
        _check_scheduled_leave_overlap() from those button actions - is
        what actually closes that gap.
        """
        if self.env.context.get('leave_skip_date_check') or self.env.context.get('discard_mode'):
            return
        valid_leaves = self.filtered(
            lambda l: bool(
                l.holiday_status_id and l.date_from and l.date_to and l.employee_id
                and l.state not in ('refuse', 'cancel')
            )
        )
        valid_leaves._check_scheduled_leave_overlap()

    def _get_leave_day_slots(self):
        """Return the set of (date, 'AM'/'PM') slots this leave actually
        occupies, derived straight from the fields the user edits
        (leave_start_date, leave_end_date, half_day, starting_half_day,
        ending_half_day, single_half_day_period) - NOT from date_from/
        date_to.

        date_from/date_to are hand-encoded fake clock times
        (e.g. Morning = 06:00-11:59:59, Afternoon = 12:00-18:00) that only
        get (re)computed by _sync_datetime_fields() at specific points in
        the request lifecycle. Odoo's web client does an implicit
        create/write of the current form the instant a header button is
        clicked, BEFORE that button's own server-side logic runs - so if
        e.g. the Morning/Afternoon radio's onchange hasn't fully
        round-tripped yet, that implicit save can carry a stale
        date_from/date_to and _check_date() will compare against it,
        producing a false "overlaps" error for two leaves that don't
        actually share any time (e.g. AM vs PM on the same day).
        Comparing on slots removes that race: it always derives fresh
        from the fields actually shown and edited on screen.
        """
        self.ensure_one()
        slots = set()
        start = self.leave_start_date
        if not start:
            return slots
        end = self.leave_end_date or start

        if self.half_day or (start == end and self.number_of_days == 0.5):
            period = 'PM' if self.single_half_day_period == 'pm' else 'AM'
            slots.add((start, period))
            return slots

        curr = start
        while curr <= end:
            if curr == start and self.starting_half_day:
                slots.add((curr, 'PM'))
            elif curr == end and self.ending_half_day:
                slots.add((curr, 'AM'))
            else:
                slots.add((curr, 'AM'))
                slots.add((curr, 'PM'))
            curr += timedelta(days=1)
        return slots

    def _check_scheduled_leave_overlap(self):
        """Prevent overlapping leaves based on leave type:
        - Scheduled Leave: cannot overlap with another Scheduled Leave.
        - Other Leave Types: cannot overlap with other NON-scheduled leaves.
        Scheduled Leaves and non-scheduled leaves are always allowed to overlap
        with each other, regardless of which side is being checked.

        Candidates are pre-filtered with a plain Date range on
        leave_start_date/leave_end_date (immune to any time-of-day
        ambiguity), then narrowed down in Python by comparing actual
        half-day slots via _get_leave_day_slots(), so an AM leave and a
        PM leave on the same day are correctly treated as non-overlapping.
        """
        scheduled_type_ids = self.env['hr.leave.type'].sudo().search([
            '|',
            ('is_scheduled_leave', '=', True),
            ('name', 'ilike', 'Scheduled Leave'),
        ]).ids

        for record in self:
            if not record.leave_start_date or not record.employee_id:
                continue

            record_slots = record._get_leave_day_slots()
            if not record_slots:
                continue
            record_end = record.leave_end_date or record.leave_start_date

            is_scheduled = bool(record.holiday_status_id and record.holiday_status_id.is_scheduled_leave)

            base_domain = [
                ('employee_id', '=', record.employee_id.id),
                ('state', 'in', ['confirm', 'validate', 'validate1']),
                ('custom_saved', '=', True),
                ('leave_start_date', '<=', record_end),
                ('leave_end_date', '>=', record.leave_start_date),
                ('id', '!=', record.id or 0),
            ]

            def _find_conflict(domain):
                for cand in self.env['hr.leave'].sudo().search(domain):
                    if cand._get_leave_day_slots() & record_slots:
                        return cand
                return False

            if is_scheduled:
                # Rule 1a: a NEW Scheduled Leave can't be booked over days
                # already consumed by a real (non-scheduled) leave. This is
                # checked first, and its message takes priority, since the
                # concrete leave already on those days is the actual
                # conflict - the reservation can't be made "after the fact"
                # once the days are already spoken for. (Note this is
                # asymmetric with Rule 2: a non-scheduled leave can still be
                # freely booked over an EXISTING Scheduled Leave - that
                # direction, scheduling ahead then taking the actual leave
                # within it, is the normal, intended workflow.)
                overlapping_non_scheduled = _find_conflict(
                    base_domain + [('holiday_status_id', 'not in', scheduled_type_ids)])
                if overlapping_non_scheduled:
                    raise ValidationError(_(
                        "This scheduled leave overlaps with an existing leave '%s'. "
                        "Please choose different dates."
                    ) % overlapping_non_scheduled.holiday_status_id.name)

                # Rule 1b: a Scheduled Leave also can't overlap another
                # Scheduled Leave.
                overlapping_scheduled = _find_conflict(
                    base_domain + [('holiday_status_id', 'in', scheduled_type_ids)])
                if overlapping_scheduled:
                    raise ValidationError(_(
                        "A scheduled leave cannot overlap with another scheduled leave '%s'. "
                        "Please choose different dates."
                    ) % overlapping_scheduled.holiday_status_id.name)
            else:
                # Rule 2: a non-scheduled leave can't overlap another
                # non-scheduled leave, but overlapping a Scheduled Leave is fine.
                overlapping = _find_conflict(
                    base_domain + [('holiday_status_id', 'not in', scheduled_type_ids)])
                if overlapping:
                    raise ValidationError(_(
                        "Your leave request overlaps with an existing leave '%s'. "
                        "Please choose different dates."
                    ) % overlapping.holiday_status_id.name)

    def _check_leave_type_constraints(self):
        """Hard, server-side counterpart to the soft warnings already shown
        by _onchange_number_of_days(). The onchange only warns in the UI and
        can be bypassed (ignored warning, direct RPC call, etc.), so this is
        called from the Save/Edit-Approve/Notify actions to actually block
        saving when a leave type's constraints aren't met:
        - Exact Days Required: duration must equal the configured exact_days.
        - Max Allowed Days: duration must not exceed max_allowed_days.
        - Require Supporting Document: an attachment must be provided.
        """
        for record in self:
            leave_type = record.holiday_status_id
            if not leave_type:
                continue

            if record._is_suspense_leave_type(leave_type) and not record.is_suspense_leave_hr:
                raise UserError(_(
                    "Leave Reason '%s' can only be requested by HR."
                ) % leave_type.name)

            days = record.computed_leave or record.number_of_days

            if leave_type.is_exact_days and leave_type.exact_days > 0:
                if days != leave_type.exact_days:
                    raise UserError(_(
                        "Leave Reason '%s' requires exactly %s day(s). You requested %s."
                    ) % (leave_type.name, leave_type.exact_days, days))

            if leave_type.max_allowed_days > 0 and days > leave_type.max_allowed_days:
                raise UserError(_(
                    "Leave Reason '%s' allows a maximum of %s day(s). You requested %s."
                ) % (leave_type.name, leave_type.max_allowed_days, days))

            if leave_type.support_document and not record.attachment:
                raise UserError(_(
                    "Leave Reason '%s' requires a supporting document to be attached."
                ) % leave_type.name)

    @api.constrains('date_from', 'date_to', 'employee_id')
    def _check_date_state(self):
        if self.env.context.get('leave_skip_state_check') or self.env.context.get('discard_mode'):
            return
        is_admin = (
            self.env.user.has_group('hr_holidays.group_hr_holidays_manager') or
            self.env.user.has_group('hr_holidays.group_hr_holidays_user') or
            self.env.is_superuser()
        )
        for holiday in self:
            if holiday.is_edit_mode or (is_admin and holiday.custom_saved):
                continue
            if holiday.state in ['validate1', 'validate']:
                raise ValidationError(_("This modification is not allowed in the current state."))

    def write(self, vals):
        is_admin = (
            self.env.user.has_group('hr_holidays.group_hr_holidays_manager') or
            self.env.user.has_group('hr_holidays.group_hr_holidays_user') or
            self.env.is_superuser()
        )
        if is_admin or any(r.is_edit_mode for r in self):
            self = self.with_context(leave_skip_state_check=True)

        res = super().write(vals)

        # A request only "exists" for reference-numbering purposes once
        # custom_saved becomes True (Save / Notify / Approve). Assign the
        # next sequence value the first time that happens.
        if vals.get('custom_saved'):
            self._assign_leave_reference()

        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('leave_start_date') and not vals.get('date_from'):
                vals['date_from'] = fields.Datetime.to_datetime(vals['leave_start_date'])
                vals['request_date_from'] = vals['leave_start_date']
            if vals.get('leave_end_date') and not vals.get('date_to'):
                vals['date_to'] = fields.Datetime.to_datetime(vals['leave_end_date'])
                vals['request_date_to'] = vals['leave_end_date']
        records = super().create(vals_list)

        # The "New Request" wizard creates records with custom_saved=True
        # directly on create() (no follow-up write()), so cover that path too.
        records.filtered(lambda r: r.custom_saved)._assign_leave_reference()
        return records

    def _assign_leave_reference(self):
        """Assign a sequential reference number (e.g. LR-000001) to any
        record in self that has been saved but doesn't have one yet.
        Idempotent - never overwrites an existing reference."""
        Sequence = self.env['ir.sequence'].sudo()
        for record in self:
            if record.custom_saved and (not record.leave_reference or record.leave_reference == 'New'):
                ref = Sequence.next_by_code('hr.leave.reference')
                if ref:
                    record.leave_reference = ref

    def action_fetch(self):
        for record in self:
            if not record.employee_id:
                raise UserError(_("Please select an employee first."))
            try:
                for field_name, value in self._get_employee_fetch_values(record.employee_id).items():
                    record[field_name] = value
                record.leave_request_status = 'fetch'
            except Exception as e:
                _logger.error(f"Error fetching employee data: {str(e)}")
                raise UserError(_("Error fetching employee data: %s") % str(e))

    def action_save_custom(self):
        for record in self:
            record = record.with_context(leave_skip_state_check=True, leave_skip_date_check=True)
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason before saving."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date before saving."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days) before saving."))

            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                period = record.multi_half_day_period if (days % 1 != 0 or (record.starting_half_day and record.ending_half_day)) else False
                end_date, half_vals = record._calculate_end_date_from_days(record.leave_start_date, days, period)
                record.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(record, k, v)

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days
            record._sync_datetime_fields()
            record._check_scheduled_leave_overlap()
            record._check_number_of_days_format()
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.request_date_from or record.leave_start_date,
                'request_date_to': record.request_date_to or record.leave_end_date,
                'date_from': record.date_from or fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': record.date_to or fields.Datetime.to_datetime(record.leave_end_date),
                'starting_half_day': record.starting_half_day,
                'ending_half_day': record.ending_half_day,
                'half_day': record.half_day,
                'multi_half_day_period': record.multi_half_day_period,
                'single_half_day_period': record.single_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
                'leave_request_status': 'draft',
            }
            if record.state != 'confirm':
                vals['state'] = 'confirm'

            record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after save: {e}")

        return True

    def action_edit_custom(self):
        for record in self:
            record.write({'is_edit_mode': True})
        return True

    def action_admin_approve_edit(self):
        for record in self:
            record = record.with_context(leave_skip_state_check=True, leave_skip_date_check=True)
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days)."))

            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                period = record.multi_half_day_period if (days % 1 != 0 or (record.starting_half_day and record.ending_half_day)) else False
                end_date, half_vals = record._calculate_end_date_from_days(record.leave_start_date, days, period)
                record.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(record, k, v)

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days
            record._sync_datetime_fields()
            record._check_scheduled_leave_overlap()
            record._check_number_of_days_format()
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.request_date_from or record.leave_start_date,
                'request_date_to': record.request_date_to or record.leave_end_date,
                'date_from': record.date_from or fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': record.date_to or fields.Datetime.to_datetime(record.leave_end_date),
                'starting_half_day': record.starting_half_day,
                'ending_half_day': record.ending_half_day,
                'half_day': record.half_day,
                'multi_half_day_period': record.multi_half_day_period,
                'single_half_day_period': record.single_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
                'leave_request_status': 'notify',
            }
            if record.state != 'validate':
                vals['state'] = 'validate'

            record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after approve edit: {e}")

        return True

    def action_discard_custom(self):
        for record in self:
            try:
                record.with_context(
                    discard_mode=True,
                    leave_skip_state_check=True,
                    leave_skip_date_check=True
                ).sudo().unlink()
            except Exception as e:
                _logger.warning(f"Could not delete discarded leave record: {e}")

        action = self.env.ref('hr_holidays.hr_leave_action_my', raise_if_not_found=False)
        if action:
            act_dict = action.read()[0]
            act_dict['target'] = 'main'
            return act_dict
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Time Off'),
            'res_model': 'hr.leave',
            'view_mode': 'list,form,kanban,activity',
            'domain': [('user_id', '=', self.env.user.id), ('custom_saved', '=', True)],
            'target': 'main',
        }

    def action_notify_request(self):
        for record in self:
            record = record.with_context(leave_skip_state_check=True, leave_skip_date_check=True)
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason before notifying."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date before notifying."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days) before notifying."))

            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                period = record.multi_half_day_period if (days % 1 != 0 or (record.starting_half_day and record.ending_half_day)) else False
                end_date, half_vals = record._calculate_end_date_from_days(record.leave_start_date, days, period)
                record.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(record, k, v)

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days
            record._sync_datetime_fields()
            record._check_scheduled_leave_overlap()
            record._check_number_of_days_format()
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.request_date_from or record.leave_start_date,
                'request_date_to': record.request_date_to or record.leave_end_date,
                'date_from': record.date_from or fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': record.date_to or fields.Datetime.to_datetime(record.leave_end_date),
                'starting_half_day': record.starting_half_day,
                'ending_half_day': record.ending_half_day,
                'half_day': record.half_day,
                'multi_half_day_period': record.multi_half_day_period,
                'single_half_day_period': record.single_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
                'leave_request_status': 'notify',
            }
            if record.state != 'confirm':
                vals['state'] = 'confirm'

            record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after notify: {e}")

            template = self.env.ref('hr_holidays.mail_template_leave_approval', raise_if_not_found=False)
            if template:
                try:
                    template.send_mail(record.id, force_send=True)
                except Exception as e:
                    _logger.warning(f"Could not send email notification: {str(e)}")

        return True

    # -------------------------------------------------------------------------
    # ACCRUAL & WATERFALL CALCULATION LOGIC
    # -------------------------------------------------------------------------

    def _get_accrual_config(self):
        get_param = self.env['ir.config_parameter'].sudo().get_param
        policy_opening_date_str = get_param('hr_leave_request_custom.policy_opening_date', '2023-08-31')
        try:
            policy_opening_date = fields.Date.from_string(policy_opening_date_str)
        except Exception:
            policy_opening_date = date(2023, 8, 31)

        try:
            base_entitlement = int(get_param('hr_leave_request_custom.base_entitlement', '16'))
        except (ValueError, TypeError):
            base_entitlement = 16

        try:
            managerial_cap_years = int(get_param('hr_leave_request_custom.managerial_cap_years', '3'))
        except (ValueError, TypeError):
            managerial_cap_years = 3

        try:
            non_managerial_cap_years = int(get_param('hr_leave_request_custom.non_managerial_cap_years', '2'))
        except (ValueError, TypeError):
            non_managerial_cap_years = 2

        opening_balance_name = get_param('hr_leave_request_custom.opening_balance_name', 'Opening Balance Load')

        return {
            'policy_opening_date': policy_opening_date,
            'base_entitlement': base_entitlement,
            'managerial_cap_years': managerial_cap_years,
            'non_managerial_cap_years': non_managerial_cap_years,
            'opening_balance_name': opening_balance_name,
        }

    def _get_employee_hire_date(self, employee):
        """Hire date is sourced exclusively from hr.version (falling back to
        hr.contract on databases that still use it), never from hr.employee
        fields like service_start_date. We take the EARLIEST version/contract
        record for the employee (ordered by its start-date field ascending),
        since that represents the employee's original hire date - the most
        recent version/contract may just reflect a later promotion, role
        change, or renewal, not the true start of service."""
        employee = employee.sudo()
        hire_date = None

        for model_name in ('hr.version', 'hr.contract'):
            if model_name not in self.env.registry.models:
                continue
            try:
                contract_model = self.env[model_name].sudo()
                start_field = 'contract_date_start' if 'contract_date_start' in contract_model._fields else 'date_start'
                earliest = contract_model.search(
                    [('employee_id', '=', employee.id), (start_field, '!=', False)],
                    order='%s asc' % start_field,
                    limit=1,
                )
                if earliest:
                    hire_date = getattr(earliest, start_field)
                    break
            except Exception as e:
                _logger.warning(f"Could not resolve hire date via {model_name}: {e}")

        if not hire_date:
            return None

        if hire_date.month == 2 and hire_date.day == 29:
            hire_date = hire_date.replace(day=28)

        return hire_date

    def _get_employee_category(self, employee):
        """Employee category (Managerial / Non-Managerial) lives on hr.job.employee_category,
        reached via the employee's contract (hr.version/hr.contract) -> job_id -> hr.job.
        Do NOT look for a 'job_category' field on the contract itself - it doesn't exist."""
        employee = employee.sudo()
        for model_name in ('hr.version', 'hr.contract'):
            if model_name not in self.env.registry.models:
                continue
            try:
                contract = self.env[model_name].sudo().search(
                    [('employee_id', '=', employee.id)],
                    order='id desc', limit=1,
                )
                job = getattr(contract, 'job_id', False)
                if job and hasattr(job, 'employee_category') and job.employee_category:
                    return job.employee_category
            except Exception as e:
                _logger.warning(f"Could not resolve employee_category via {model_name}.job_id: {e}")

        # Fallback: employee's own job_id, in case contract lookup fails/misses
        job = getattr(employee, 'job_id', False)
        if job and hasattr(job, 'employee_category') and job.employee_category:
            return job.employee_category

        return ''

    def _calculate_eligible_leave(self, employee, as_of_date=None):
        """
        Calculates eligible accrued leave while enforcing:
        1. Opening Balance Load as the starting balance.
        2. Pro-rata accrual based on elapsed days and existing LWP rules.
        3. A per-accrual-year ceiling equal to that year's entitlement.
        4. A maximum balance ceiling (carryover cap) based on the employee
           category, anchored on the LAST COMPLETED accrual year's
           entitlement - NOT the current, still-in-progress year's
           entitlement, since that hasn't been fully earned yet.
        5. The current in-progress year's partial accrual is added on top
           of the capped completed-years total, uncapped, since it will
           only be subject to its own completed-year cap once it finishes.
        6. Consumption creates room for previously earned accrual to resume.
        """
        if not employee:
            return 0.0

        if as_of_date is None:
            as_of_date = fields.Date.today()

        config = self._get_accrual_config()
        policy_opening_date = config['policy_opening_date']
        base_entitlement = config['base_entitlement']
        managerial_cap_years = config['managerial_cap_years']
        non_managerial_cap_years = config['non_managerial_cap_years']
        opening_balance_name = config['opening_balance_name']

        hire_date = self._get_employee_hire_date(employee)
        if not hire_date:
            return 0.0

        employee_category = self._get_employee_category(employee)

        opening_balance_leave = 0.0
        try:
            ob_allocs = self.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('name', '=', opening_balance_name),
            ])
            opening_balance_leave = sum(a.number_of_days for a in ob_allocs)
        except Exception as e:
            _logger.warning(f"Could not fetch opening balance: {e}")

        lwp_leave_type_ids = []
        try:
            lwp_leave_type_ids = self.env['hr.leave.type'].sudo().search([
                ('is_lwp', '=', True),
            ]).ids
        except Exception as e:
            _logger.warning(f"Could not fetch LWP leave types: {e}")

        if hire_date > policy_opening_date:
            accrual_start_date = hire_date
            opening_balance_leave = 0.0
        else:
            accrual_start_date = policy_opening_date + timedelta(days=1)
            if not opening_balance_leave:
                _logger.warning(
                    "Employee %s (id=%s): hire_date=%s is before "
                    "policy_opening_date=%s but no '%s' allocation was found.",
                    employee.name, employee.id, hire_date, policy_opening_date,
                    opening_balance_name,
                )

        accrued_completed = 0.0
        accrued_current_partial = 0.0
        last_completed_entitlement = None

        while accrual_start_date <= as_of_date:
            year_offset = relativedelta(accrual_start_date, hire_date).years
            entitlement = base_entitlement + max(0, year_offset)
            next_anniversary = hire_date + relativedelta(years=year_offset + 1)
            interval_end_date = min(
                next_anniversary - timedelta(days=1),
                as_of_date,
            )

            # True only for the single accrual year still in progress as of
            # as_of_date (its full entitlement window hasn't elapsed yet).
            # All prior years in the loop have already reached their own
            # anniversary and are treated as completed.
            is_partial_current_year = (next_anniversary - timedelta(days=1)) > as_of_date

            if interval_end_date < accrual_start_date:
                break

            year_accrued = 0.0
            lwp_handled = False

            if lwp_leave_type_ids:
                try:
                    lwp_leaves = self.env['hr.leave'].sudo().search([
                        ('employee_id', '=', employee.id),
                        ('holiday_status_id', 'in', lwp_leave_type_ids),
                        ('state', '=', 'validate'),
                        ('date_from', '<=', fields.Datetime.to_datetime(interval_end_date)),
                        ('date_to', '>=', fields.Datetime.to_datetime(accrual_start_date)),
                    ], order='date_from asc')

                    if lwp_leaves:
                        for lwp in lwp_leaves:
                            lwp_start = lwp.date_from.date() if lwp.date_from else None
                            lwp_end = lwp.date_to.date() if lwp.date_to else None

                            if not lwp_start or not lwp_end:
                                continue

                            lwp_start_in_interval = max(lwp_start, accrual_start_date)
                            lwp_end_in_interval = min(lwp_end, interval_end_date)

                            if lwp_start_in_interval > accrual_start_date:
                                pre_lwp_days = (
                                    lwp_start_in_interval - accrual_start_date
                                ).days
                                year_accrued += (pre_lwp_days / 365.0) * entitlement

                            accrual_start_date = lwp_end_in_interval + timedelta(days=1)
                            lwp_handled = True

                            if accrual_start_date > interval_end_date:
                                break

                        if lwp_handled and accrual_start_date > interval_end_date:
                            accrual_start_date = next_anniversary
                            capped_year_accrued = min(year_accrued, entitlement)
                            if is_partial_current_year:
                                accrued_current_partial += capped_year_accrued
                            else:
                                accrued_completed += capped_year_accrued
                                last_completed_entitlement = entitlement
                            continue

                        if lwp_handled:
                            if accrual_start_date <= interval_end_date:
                                remaining_days = (
                                    interval_end_date - accrual_start_date + timedelta(days=1)
                                ).days
                                year_accrued += (remaining_days / 365.0) * entitlement

                            accrual_start_date = next_anniversary
                            capped_year_accrued = min(year_accrued, entitlement)
                            if is_partial_current_year:
                                accrued_current_partial += capped_year_accrued
                            else:
                                accrued_completed += capped_year_accrued
                                last_completed_entitlement = entitlement
                            continue

                except Exception as e:
                    _logger.warning(f"Error checking LWP in interval: {e}")

            interval_days = (
                interval_end_date - accrual_start_date + timedelta(days=1)
            ).days
            year_accrued += (interval_days / 365.0) * entitlement

            # A particular accrual year can never contribute more than
            # that year's annual entitlement.
            year_accrued = min(year_accrued, entitlement)
            if is_partial_current_year:
                accrued_current_partial += year_accrued
            else:
                accrued_completed += year_accrued
                last_completed_entitlement = entitlement
            accrual_start_date = next_anniversary

        # Opening Balance is folded into the "completed" bucket (same as
        # before) since it represents leave already banked as of the policy
        # cutover, and is therefore subject to the same carryover cap as
        # fully-completed accrual years.
        gross_accrued_completed = accrued_completed + opening_balance_leave

        # Calculate the maximum total balance allowed by category. This cap
        # is anchored on the LAST COMPLETED accrual year's entitlement, not
        # the current in-progress year's entitlement - the current year
        # hasn't finished accruing yet, so using its (higher) entitlement as
        # the anchor overstated the cap. If no year has completed yet
        # (employee is within their first accrual year), fall back to the
        # base entitlement.
        anchor_entitlement = (
            last_completed_entitlement
            if last_completed_entitlement is not None
            else base_entitlement
        )

        if str(employee_category).lower() == 'managerial':
            cap_years = managerial_cap_years
        else:
            cap_years = non_managerial_cap_years

        max_allowed_carryover = sum(
            max(0, anchor_entitlement - yr)
            for yr in range(cap_years)
        )

        # Find Scheduled Leave Type(s) - by is_scheduled_leave flag or fallback by name
        scheduled_types = self.env['hr.leave.type'].sudo().search([
            '|',
            ('is_scheduled_leave', '=', True),
            ('name', '=ilike', 'Schedule%Leave%'),
        ])
        scheduled_type_ids = scheduled_types.ids

        accrual_types = self.env['hr.leave.type'].sudo().search([
            '|',
            ('check_accrual_balance', '=', True),
            ('name', '=ilike', 'Annual%'),
            ('id', 'not in', scheduled_type_ids),
        ])
        accrual_type_ids = [tid for tid in accrual_types.ids if tid not in scheduled_type_ids]

        current_rec_id = (
            self.id
            if hasattr(self, 'id') and self.id and isinstance(self.id, int)
            else False
        )

        total_leave_consumed = 0.0
        if accrual_type_ids:
            actual_domain = [
                ('employee_id', '=', employee.id),
                ('state', 'in', ['confirm', 'validate', 'validate1']),
                ('holiday_status_id', 'in', accrual_type_ids),
                ('custom_saved', '=', True),
            ]
            if current_rec_id:
                actual_domain.append(('id', '!=', current_rec_id))

            actual_leaves = self.env['hr.leave'].sudo().search(
                actual_domain,
                order='date_from asc, id asc',
            )
            total_leave_consumed = sum(
                lv.number_of_days for lv in actual_leaves
            )

        # Enforce maximum balance ceiling (carryover cap) on completed years
        maximum_eligible_accrual = max_allowed_carryover

        eligible_completed = min(
            gross_accrued_completed,
            maximum_eligible_accrual,
        )

        # The current, still-in-progress accrual year is added on top of the
        # capped completed-years total, uncapped for now - it hasn't had a
        # chance to be measured against a full year's entitlement yet, and
        # will fall under its own completed-year cap check once it finishes.
        eligible = eligible_completed + accrued_current_partial

        return float_round(
            max(0.0, eligible),
            precision_digits=2,
        )

    def _get_leave_balances(self, employee):
        """Waterfall balance derivation:
        1. Scheduled pool = Total approved/saved Scheduled Leaves - Total consumed by actual leaves.
        2. Accrual pool = Gross Eligible Accrual - Total Scheduled Transferred - Total Direct Accrual Deductions.
        """
        if not employee:
            return {'accrued': 0.0, 'scheduled': 0.0}

        gross_accrual = self._calculate_eligible_leave(employee)

        # Find Scheduled Leave Type(s) - by is_scheduled_leave flag or fallback by name
        scheduled_types = self.env['hr.leave.type'].sudo().search([
            '|',
            ('is_scheduled_leave', '=', True),
            ('name', '=ilike', 'Schedule%Leave%'),
        ])
        scheduled_type_ids = scheduled_types.ids

        # Find Regular Accrual-Consuming Type(s)
        accrual_types = self.env['hr.leave.type'].sudo().search([
            '|',
            ('check_accrual_balance', '=', True),
            ('name', '=ilike', 'Annual%'),
            ('id', 'not in', scheduled_type_ids),
        ])
        accrual_type_ids = [tid for tid in accrual_types.ids if tid not in scheduled_type_ids]

        current_rec_id = self.id if (hasattr(self, 'id') and self.id and isinstance(self.id, int)) else False

        # 1. Total Scheduled Leave Days Booked (Confirmed or Validated)
        total_scheduled_booked = 0.0
        if scheduled_type_ids:
            sched_domain = [
                ('employee_id', '=', employee.id),
                ('state', 'in', ['confirm', 'validate', 'validate1']),
                ('holiday_status_id', 'in', scheduled_type_ids),
                ('custom_saved', '=', True),
            ]
            if current_rec_id:
                sched_domain.append(('id', '!=', current_rec_id))

            sched_leaves = self.env['hr.leave'].sudo().search(sched_domain)
            total_scheduled_booked = sum(lv.number_of_days for lv in sched_leaves)

        # 2. Chronological Waterfall Deduction by Actual Leaves
        actual_domain = [
            ('employee_id', '=', employee.id),
            ('state', 'in', ['confirm', 'validate', 'validate1']),
            ('holiday_status_id', 'in', accrual_type_ids),
            ('custom_saved', '=', True),
        ]
        if current_rec_id:
            actual_domain.append(('id', '!=', current_rec_id))

        actual_leaves = self.env['hr.leave'].sudo().search(actual_domain, order='date_from asc, id asc') if accrual_type_ids else []

        remaining_scheduled = total_scheduled_booked
        total_direct_accrual_deductions = 0.0

        for lv in actual_leaves:
            req_days = lv.number_of_days
            if remaining_scheduled >= req_days:
                remaining_scheduled -= req_days
            else:
                from_scheduled = remaining_scheduled
                from_accrual = req_days - from_scheduled
                remaining_scheduled = 0.0
                total_direct_accrual_deductions += from_accrual

        # 3. Derive Net Balances
        net_accrued = max(0.0, gross_accrual - total_scheduled_booked - total_direct_accrual_deductions)
        net_scheduled = max(0.0, remaining_scheduled)

        return {
            'accrued': float_round(net_accrued, precision_digits=2),
            'scheduled': float_round(net_scheduled, precision_digits=2),
        }


class ResourceCalendarLeavesCustom(models.Model):
    _inherit = 'resource.calendar.leaves'

    work_unit_type = fields.Selection([
        ('head_office', 'Head Office'),
        ('branch', 'Branch'),
    ], string='Work Unit Type',
        help="If set, this public holiday only applies to employees whose "
             "Operating Unit has this Work Unit Type. Leave blank to apply to everyone.")

    day_of_week = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string='Day', help="If specified, this day of the week is treated as a recurring Public Holiday.")

    holiday_day_weight = fields.Float(
        string='Number of Days',
        default=1.0,
        help="Amount of holiday duration (1.0 = Full Day Holiday / 0 days counted; 0.5 = Half Day Holiday / 0.5 day counted)."
    )

    date_from = fields.Datetime('Start Date', required=False)
    date_to = fields.Datetime('End Date', compute="_compute_date_to", readonly=False, required=False, store=True)

    @api.onchange('day_of_week')
    def _onchange_day_of_week(self):
        if self.day_of_week and not self.name:
            day_names = {'0': 'Monday', '1': 'Tuesday', '2': 'Wednesday', '3': 'Thursday', '4': 'Friday',
                         '5': 'Saturday', '6': 'Sunday'}
            self.name = day_names.get(self.day_of_week, '')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('day_of_week') and not vals.get('date_from'):
                vals['date_from'] = fields.Datetime.to_datetime('2000-01-01 00:00:00')
                vals['date_to'] = fields.Datetime.to_datetime('2099-12-31 23:59:59')
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('day_of_week') and not vals.get('date_from'):
            vals['date_from'] = fields.Datetime.to_datetime('2000-01-01 00:00:00')
            vals['date_to'] = fields.Datetime.to_datetime('2099-12-31 23:59:59')
        elif 'day_of_week' not in vals or vals.get('day_of_week'):
            for rec in self:
                effective_day_of_week = vals.get('day_of_week', rec.day_of_week)
                if effective_day_of_week and not rec.date_from and not vals.get('date_from'):
                    vals['date_from'] = fields.Datetime.to_datetime('2000-01-01 00:00:00')
                    vals['date_to'] = fields.Datetime.to_datetime('2099-12-31 23:59:59')
                    break
        return super().write(vals)

    def _check_overlapping_public_holidays(self):
        dated_holidays = self.filtered(lambda h: not h.day_of_week)
        if dated_holidays:
            return super(ResourceCalendarLeavesCustom, dated_holidays)._check_overlapping_public_holidays()
        return True


class OperatingUnitInheritCustom(models.Model):
    _inherit = 'operating.unit'

    saturday_work_type = fields.Selection([
        ('half_day', 'Half Day (0.5 Day - Morning)'),
        ('full_day', 'Full Day (1.0 Day)'),
        ('off', 'Non-Working (0.0 Day)'),
    ], string='Saturday Schedule', default='half_day',
       help="Defines how Saturday is counted during leave calculation for employees in this operating unit.")


class HrDepartmentInheritCustom(models.Model):
    _inherit = 'hr.department'

    saturday_work_type = fields.Selection([
        ('half_day', 'Half Day (0.5 Day - Morning)'),
        ('full_day', 'Full Day (1.0 Day)'),
        ('off', 'Non-Working (0.0 Day)'),
    ], string='Saturday Schedule', default=False,
       help="Optional override for Saturday schedule for employees in this department.")