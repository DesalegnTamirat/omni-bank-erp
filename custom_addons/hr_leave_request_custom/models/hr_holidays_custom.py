# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
import logging
from datetime import timedelta

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

        # Ensure leave type and dates are NOT auto-selected on fresh New form
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
        defaults['multi_half_day_period'] = ctx.get('default_multi_half_day_period', 'start')
        defaults['is_computed'] = ctx.get('default_is_computed', True)
        defaults['custom_saved'] = ctx.get('default_custom_saved', False)
        defaults['is_edit_mode'] = ctx.get('default_is_edit_mode', False)
        defaults['leave_request_status'] = ctx.get('default_leave_request_status', 'fetch')

        # Clear standard Odoo auto-populated dates
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
        """Return the employee's contract (or, on Odoo 19+, hr.version) record."""
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
                _logger.warning(
                    f"Could not look up {model_name} for employee "
                    f"{employee.id}: {str(e)}")
        return False

    @staticmethod
    def _to_display_text(value):
        """Best-effort conversion of a field's value to a human-readable string."""
        if not value:
            return ''
        if hasattr(value, '_name') and hasattr(value, 'display_name'):
            return value.display_name or value.name or ''
        return str(value)

    def _get_employee_fetch_values(self, employee):
        if not employee:
            return {}
        employee = employee.sudo()

        # Job Position
        job_pos = ''
        if hasattr(employee, 'job_id') and employee.job_id:
            job_pos = employee.job_id.name
        elif hasattr(employee, 'job_title') and employee.job_title:
            job_pos = self._to_display_text(employee.job_title)
        elif hasattr(employee, 'job_position') and employee.job_position:
            job_pos = self._to_display_text(employee.job_position)

        # Job Grade
        job_grd = ''
        if hasattr(employee, 'job_grade') and employee.job_grade:
            job_grd = self._to_display_text(employee.job_grade)
        elif hasattr(employee, 'grade_id') and employee.grade_id:
            job_grd = employee.grade_id.name

        # Job Category (fetched like requester_name)
        job_cat = ''
        if hasattr(employee, 'job_category') and employee.job_category:
            job_cat = self._to_display_text(employee.job_category)
        elif hasattr(employee, 'contract_id') and employee.contract_id and hasattr(employee.contract_id, 'job_category'):
            job_cat = self._to_display_text(employee.contract_id.job_category)
        if not job_cat:
            contract = self._get_active_contract(employee)
            if contract and hasattr(contract, 'job_category'):
                job_cat = self._to_display_text(contract.job_category)

        # Operating Unit
        op_unit = False
        if hasattr(employee, 'default_operating_unit_id') and employee.default_operating_unit_id:
            op_unit = employee.default_operating_unit_id.id
        elif hasattr(employee, 'operating_unit') and employee.operating_unit:
            op_unit = employee.operating_unit.id
        elif hasattr(employee, 'operating_unit_ids') and employee.operating_unit_ids:
            op_unit = employee.operating_unit_ids[0].id

        balances = self._get_leave_balances(employee)

        vals = {
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
        return vals

    # -- Job / Requester info matching the Leave Request form -----------
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Leave Reason',
        default=False,
    )
    support_document = fields.Boolean(
        string='Require Supporting Document',
        related='holiday_status_id.support_document',
        readonly=True,
    )
    is_exact_days = fields.Boolean(
        string='Exact Days Required',
        compute='_compute_is_exact_days',
    )
    is_duration_readonly = fields.Boolean(
        string='Duration Readonly',
        compute='_compute_is_duration_readonly',
    )
    is_single_half_day = fields.Boolean(
        string='Is Single Half Day',
        compute='_compute_half_day_visibility',
    )
    is_multi_half_day = fields.Boolean(
        string='Is Multi Half Day',
        compute='_compute_half_day_visibility',
    )
    single_half_day_period = fields.Selection([
        ('am', 'Morning'),
        ('pm', 'Afternoon'),
    ], string='Half Day Period', default='am')
    multi_half_day_period = fields.Selection([
        ('none', 'Full Days'),
        ('start', 'Starting Half Day (Starts in Afternoon)'),
        ('end', 'Ending Half Day (Ends in Morning)'),
        ('both', 'Both (Starts Afternoon & Ends Morning)'),
    ], string='Half Day Selection', default='start')

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
    fetch_status = fields.Selection([
        ('not_fetched', 'Not Fetched'),
        ('fetched', 'Fetched'),
    ], string='Fetch Status', default='not_fetched')

    # Date pickers
    leave_start_date = fields.Date(string='Start Date')
    leave_end_date = fields.Date(string='End Date')

    # Tracks whether user explicitly clicked Save
    custom_saved = fields.Boolean(string='Is Saved', default=False)

    # Tracks whether the record is currently unlocked for editing
    is_edit_mode = fields.Boolean(string='Is Edit Mode', default=False)

    # Tracks whether duration has been computed
    is_computed = fields.Boolean(string='Is Computed', default=True)

    # -- Button / field visibility helpers -------------------------------
    is_hr_admin = fields.Boolean(
        string='Is Time Off Admin', compute='_compute_button_visibility')
    fields_readonly = fields.Boolean(
        string='Fields Readonly', compute='_compute_button_visibility')
    show_save_btn = fields.Boolean(
        string='Show Save', compute='_compute_button_visibility')
    show_discard_btn = fields.Boolean(
        string='Show Discard', compute='_compute_button_visibility')
    show_edit_btn = fields.Boolean(
        string='Show Edit', compute='_compute_button_visibility')
    show_notify_btn = fields.Boolean(
        string='Show Notify', compute='_compute_button_visibility')
    show_approve_btn = fields.Boolean(
        string='Show Approve', compute='_compute_button_visibility')
    show_cancel_btn = fields.Boolean(
        string='Show Cancel', compute='_compute_button_visibility')
    show_compute_btn = fields.Boolean(
        string='Show Compute', compute='_compute_button_visibility')

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
            is_half = (days == 0.5) or (record.half_day and record.leave_start_date == record.leave_end_date)
            is_multi = (days > 1.0 and (days % 1 != 0 or record.starting_half_day or record.ending_half_day)) or (
                record.leave_start_date and record.leave_end_date and record.leave_start_date != record.leave_end_date and (record.starting_half_day or record.ending_half_day)
            )
            record.is_single_half_day = bool(is_half)
            record.is_multi_half_day = bool(is_multi and not is_half)

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
                # Fresh, unsaved request being created
                record.fields_readonly = False
                record.show_save_btn = True
                record.show_notify_btn = True
                record.show_discard_btn = True
                record.show_edit_btn = False
                record.show_approve_btn = False
                record.show_cancel_btn = False

            elif status == 'draft':
                # Saved as draft (not yet submitted/notified)
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
                # Notified or Approved request
                if not is_admin:
                    # Regular user must NEVER see any buttons once submitted/notified
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = False
                    record.show_discard_btn = False
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_cancel_btn = False
                else:
                    # Admin viewing submitted/notified or approved request
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

    # Override number_of_days
    number_of_days = fields.Float(
        string='Duration (Days)',
        compute=False,
        store=True,
        default=0.0,
        readonly=False,
    )

    # Custom workflow status
    leave_request_status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('fetch', 'Fetch'),
            ('check_leave_balance', 'Check Leave Balance'),
            ('notify', 'Notify'),
        ],
        default='fetch',
        string='Leave Balance Status',
        readonly=True,
    )

    def _sync_datetime_fields(self):
        """Synchronize stock Odoo date_from / date_to and request dates."""
        if not self.leave_start_date:
            self.date_from = False
            self.request_date_from = False
            self.date_to = False
            self.request_date_to = False
            return

        self.request_date_from = self.leave_start_date
        self.request_date_to = self.leave_end_date or self.leave_start_date

        start_dt = fields.Datetime.to_datetime(self.leave_start_date)
        end_dt = fields.Datetime.to_datetime(self.leave_end_date or self.leave_start_date)

        if self.half_day or self.number_of_days == 0.5:
            if self.single_half_day_period == 'pm':
                self.date_from = start_dt.replace(hour=12, minute=0, second=0)
                self.date_to = start_dt.replace(hour=18, minute=0, second=0)
            else:
                self.date_from = start_dt.replace(hour=6, minute=0, second=0)
                self.date_to = start_dt.replace(hour=12, minute=0, second=0)
        else:
            if self.starting_half_day:
                self.date_from = start_dt.replace(hour=12, minute=0, second=0)
            else:
                self.date_from = start_dt.replace(hour=0, minute=0, second=0)

            if self.ending_half_day:
                self.date_to = end_dt.replace(hour=12, minute=0, second=0)
            else:
                self.date_to = end_dt.replace(hour=23, minute=59, second=59)

    def _calculate_end_date_from_days(self, start_date, days, multi_half_period='start'):
        """Calculate leave end date and half-day flags from start_date and duration (days)."""
        if not start_date or days <= 0:
            return False, {'half_day': False, 'starting_half_day': False, 'ending_half_day': False}

        # Single half-day: duration 0.5
        if days == 0.5:
            return start_date, {'half_day': True, 'starting_half_day': False, 'ending_half_day': False}

        # Multi-day with start in afternoon
        if multi_half_period == 'start':
            int_days = int(days)
            end_date = start_date + timedelta(days=int_days)
            return end_date, {'starting_half_day': True, 'ending_half_day': False, 'half_day': False}

        # Multi-day with end in morning
        if multi_half_period == 'end':
            int_days = int(days)
            end_date = start_date + timedelta(days=int_days)
            return end_date, {'starting_half_day': False, 'ending_half_day': True, 'half_day': False}

        # Multi-day with both start in afternoon and end in morning
        if multi_half_period == 'both':
            int_days = int(days)
            end_date = start_date + timedelta(days=int_days)
            return end_date, {'starting_half_day': True, 'ending_half_day': True, 'half_day': False}

        # Full Days (none)
        if days % 1 != 0:
            int_days = int(days)
            end_date = start_date + timedelta(days=int_days)
            return end_date, {'starting_half_day': True, 'ending_half_day': False, 'half_day': False}

        end_date = start_date + timedelta(days=int(days) - 1)
        return end_date, {'starting_half_day': False, 'ending_half_day': False, 'half_day': False}

    def _compute_days_preview(self):
        """Calculate leave days duration from start and end dates with half-day rules."""
        self.ensure_one()
        start_date = self.leave_start_date
        end_date = self.leave_end_date
        if not start_date or not end_date:
            return 0.0
        if end_date < start_date:
            return 0.0

        delta_days = (end_date - start_date).days + 1

        if delta_days == 1:
            if self.half_day or self.number_of_days == 0.5:
                return 0.5
            return 1.0

        days = float(delta_days)
        if self.starting_half_day and self.ending_half_day:
            days = max(0.5, days - 1.0)
        elif self.starting_half_day or self.ending_half_day:
            days = max(0.5, days - 0.5)

        return float_round(days, precision_digits=2)

    @api.onchange('holiday_status_id')
    def _onchange_holiday_status_id_custom(self):
        """React when Leave Reason is selected: enforce exact days if configured."""
        if self.holiday_status_id:
            is_exact = bool(self.holiday_status_id.is_exact_days or self.holiday_status_id.exact_days > 0)
            if is_exact:
                exact = self.holiday_status_id.exact_days
                self.number_of_days = exact
                self.computed_leave = exact
                if self.leave_start_date:
                    end_date, half_vals = self._calculate_end_date_from_days(
                        self.leave_start_date, exact, self.multi_half_day_period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
            else:
                if self.leave_start_date and self.leave_end_date:
                    days = self._compute_days_preview()
                    self.number_of_days = days
                    self.computed_leave = days
                elif self.leave_start_date and self.number_of_days > 0:
                    end_date, half_vals = self._calculate_end_date_from_days(
                        self.leave_start_date, self.number_of_days, self.multi_half_day_period)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
        self._sync_datetime_fields()

    @api.onchange('leave_start_date')
    def _onchange_leave_start_date(self):
        """When Start Date changes, compute End Date or Duration."""
        if self.leave_start_date:
            if self.number_of_days > 0:
                end_date, half_vals = self._calculate_end_date_from_days(
                    self.leave_start_date, self.number_of_days, self.multi_half_day_period)
                self.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(self, k, v)
                self.computed_leave = self.number_of_days
            elif self.leave_end_date:
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
        self._sync_datetime_fields()

    @api.onchange('leave_end_date')
    def _onchange_leave_end_date(self):
        """When End Date is manually changed, compute Duration."""
        if self.leave_start_date and self.leave_end_date:
            if self.leave_end_date < self.leave_start_date:
                self.number_of_days = 0.0
                self.computed_leave = 0.0
            elif self.leave_end_date == self.leave_start_date:
                if self.number_of_days == 0.5 or self.half_day:
                    self.number_of_days = 0.5
                    self.computed_leave = 0.5
                    self.half_day = True
                    self.starting_half_day = False
                    self.ending_half_day = False
                else:
                    self.number_of_days = 1.0
                    self.computed_leave = 1.0
                    self.half_day = False
                    self.starting_half_day = False
                    self.ending_half_day = False
            else:
                self.half_day = False
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
        self._sync_datetime_fields()

    @api.onchange('number_of_days')
    def _onchange_number_of_days(self):
        """When Number of Days is filled/changed, compute End Date automatically."""
        if self.is_exact_days and self.holiday_status_id and self.holiday_status_id.exact_days > 0:
            self.number_of_days = self.holiday_status_id.exact_days

        if self.number_of_days < 0:
            self.number_of_days = 0.0

        self.computed_leave = self.number_of_days

        if self.number_of_days == 0.5:
            self.half_day = True
            self.starting_half_day = False
            self.ending_half_day = False
            if self.leave_start_date:
                self.leave_end_date = self.leave_start_date
        elif self.number_of_days > 1 and self.number_of_days % 1 != 0:
            self.half_day = False
            if not self.multi_half_day_period:
                self.multi_half_day_period = 'start'
            if self.multi_half_day_period == 'start':
                self.starting_half_day = True
                self.ending_half_day = False
            else:
                self.starting_half_day = False
                self.ending_half_day = True
            if self.leave_start_date:
                end_date, half_vals = self._calculate_end_date_from_days(
                    self.leave_start_date, self.number_of_days, self.multi_half_day_period)
                self.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(self, k, v)
        elif self.number_of_days >= 1.0 and self.number_of_days % 1 == 0:
            self.half_day = False
            self.starting_half_day = False
            self.ending_half_day = False
            if self.leave_start_date:
                end_date, half_vals = self._calculate_end_date_from_days(
                    self.leave_start_date, self.number_of_days, self.multi_half_day_period)
                self.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(self, k, v)

        self._sync_datetime_fields()

    @api.onchange('single_half_day_period')
    def _onchange_single_half_day_period(self):
        """When single day half day period (morning vs afternoon) changes."""
        self._sync_datetime_fields()

    @api.onchange('multi_half_day_period')
    def _onchange_multi_half_day_period(self):
        """When multi-day half day period (start in afternoon, end in morning, both, or none) changes."""
        if self.multi_half_day_period == 'start':
            self.starting_half_day = True
            self.ending_half_day = False
            self.half_day = False
        elif self.multi_half_day_period == 'end':
            self.starting_half_day = False
            self.ending_half_day = True
            self.half_day = False
        elif self.multi_half_day_period == 'both':
            self.starting_half_day = True
            self.ending_half_day = True
            self.half_day = False
        else:  # none
            self.starting_half_day = False
            self.ending_half_day = False
            self.half_day = False

        if self.leave_start_date and self.number_of_days > 0:
            end_date, half_vals = self._calculate_end_date_from_days(
                self.leave_start_date, self.number_of_days, self.multi_half_day_period)
            self.leave_end_date = end_date
            for k, v in half_vals.items():
                setattr(self, k, v)
        elif self.leave_start_date and self.leave_end_date:
            days = self._compute_days_preview()
            self.number_of_days = days
            self.computed_leave = days
        self._sync_datetime_fields()

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            for field_name, value in self._get_employee_fetch_values(self.employee_id).items():
                setattr(self, field_name, value)
        else:
            self.fetch_status = 'not_fetched'

    def _check_leave_type_constraints(self):
        """Validate leave request against leave type configurations."""
        for record in self:
            leave_type = record.holiday_status_id
            if not leave_type:
                continue

            days = record.computed_leave or record.number_of_days

            # 1. Accrual balance check & positive scheduled balance
            if leave_type.check_accrual_balance:
                if record.scheduled_leave_balance < 0:
                    raise ValidationError(_(
                        "Scheduled leave balance must be positive (>= 0) for '%s'."
                    ) % leave_type.name)
                total_available = record.accrued_leave_balance
                if days > total_available:
                    raise ValidationError(_(
                        "Requested days (%(requested)g) exceeds your available accrued leave balance (%(balance)g) for '%(type)s'.",
                        requested=days,
                        balance=total_available,
                        type=leave_type.name,
                    ))

            # 2. Exact days check
            is_exact = bool(leave_type.is_exact_days or leave_type.exact_days > 0)
            if is_exact and leave_type.exact_days > 0:
                if days != leave_type.exact_days:
                    raise ValidationError(_(
                        "The duration for '%(type)s' must be exactly %(exact)g day(s). You requested %(requested)g day(s).",
                        type=leave_type.name,
                        exact=leave_type.exact_days,
                        requested=days,
                    ))

            # 3. Max allowed days check
            if leave_type.max_allowed_days > 0:
                if days > leave_type.max_allowed_days:
                    raise ValidationError(_(
                        "The duration for '%(type)s' cannot exceed %(max)g day(s). You requested %(requested)g day(s).",
                        type=leave_type.name,
                        max=leave_type.max_allowed_days,
                        requested=days,
                    ))

            # 4. Require supporting document / attachment check
            if leave_type.support_document and not record.attachment:
                raise ValidationError(_(
                    "An attachment/supporting document is required for '%s'."
                ) % leave_type.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Synchronize date_from / date_to
            if vals.get('leave_start_date') and not vals.get('date_from'):
                vals['date_from'] = fields.Datetime.to_datetime(vals['leave_start_date'])
                vals['request_date_from'] = vals['leave_start_date']
            if vals.get('leave_end_date') and not vals.get('date_to'):
                vals['date_to'] = fields.Datetime.to_datetime(vals['leave_end_date'])
                vals['request_date_to'] = vals['leave_end_date']
        return super().create(vals_list)

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

    def action_compute_actual_leave_days(self):
        """Compute actual leave days and display result immediately in computed_leave field."""
        self.ensure_one()
        start_date = self.leave_start_date
        end_date = self.leave_end_date

        if not start_date or not end_date:
            raise UserError(_("Please fill in both Start Date and End Date before computing."))
        if end_date < start_date:
            raise UserError(_("End Date cannot be earlier than Start Date."))

        days = self._compute_days_preview()

        # Update record in-place bypassing state checks if already validated
        self.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
            'computed_leave': days,
            'number_of_days': days,
            'is_computed': True,
        })

        return True

    def action_save_custom(self):
        """Save the leave request as Draft and lock fields."""
        for record in self:
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason before saving."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date before saving."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days) before saving."))

            # Auto-compute days & end date if needed
            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                end_date, _ = record._calculate_end_date_from_days(record.leave_start_date, days, record.half_day_type)
                record.leave_end_date = end_date

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days

            # Enforce leave type constraints
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.leave_start_date,
                'request_date_to': record.leave_end_date,
                'date_from': fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': fields.Datetime.to_datetime(record.leave_end_date),
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

        return True

    def action_edit_custom(self):
        """Unlock the form fields for editing."""
        for record in self:
            record.write({
                'is_edit_mode': True,
            })
        return True

    def action_admin_approve_edit(self):
        """When Admin approves or finishes editing a notified/approved request."""
        for record in self:
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days)."))

            # Auto-compute days & end date if needed
            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                end_date, _ = record._calculate_end_date_from_days(record.leave_start_date, days, record.half_day_type)
                record.leave_end_date = end_date

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days

            # Enforce leave type constraints
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.leave_start_date,
                'request_date_to': record.leave_end_date,
                'date_from': fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': fields.Datetime.to_datetime(record.leave_end_date),
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

        return True

    def action_discard_custom(self):
        """Discard changes and reset/unlink the request, returning a fresh empty form."""
        for record in self:
            # If editing an already notified/approved record, simply exit edit mode
            if record.custom_saved and (record.leave_request_status == 'notify' or record.state in ('validate', 'validate1')):
                record.write({'is_edit_mode': False})
                return True

            if isinstance(record.id, int):
                try:
                    record.sudo().unlink()
                except Exception as e:
                    _logger.warning(f"Could not delete leave record on discard: {e}")

        return {
            'type': 'ir.actions.act_window',
            'name': _('Leave Request'),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_holiday_status_id': False,
                'default_leave_start_date': False,
                'default_leave_end_date': False,
                'default_starting_half_day': False,
                'default_ending_half_day': False,
                'default_half_day': False,
                'default_comments': False,
                'default_attachment': False,
                'default_attachment_name': False,
                'default_delegated_employee_id': False,
                'default_computed_leave': 0.0,
                'default_number_of_days': 0.0,
                'default_is_computed': True,
                'default_custom_saved': False,
                'default_is_edit_mode': False,
                'default_leave_request_status': 'fetch',
            },
        }

    def action_notify_request(self):
        """Notify manager for approval."""
        for record in self:
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason before notifying."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date before notifying."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days) before notifying."))

            # Auto-compute days & end date if needed
            days = record.computed_leave or record.number_of_days
            if not days and record.leave_start_date and record.leave_end_date:
                days = record._compute_days_preview()
            elif not record.leave_end_date and days > 0:
                end_date, _ = record._calculate_end_date_from_days(record.leave_start_date, days, record.half_day_type)
                record.leave_end_date = end_date

            if record.leave_end_date and record.leave_end_date < record.leave_start_date:
                raise UserError(_("End Date cannot be earlier than Start Date."))

            record.computed_leave = days
            record.number_of_days = days

            # Enforce leave type constraints
            record._check_leave_type_constraints()

            vals = {
                'leave_start_date': record.leave_start_date,
                'leave_end_date': record.leave_end_date,
                'request_date_from': record.leave_start_date,
                'request_date_to': record.leave_end_date,
                'date_from': fields.Datetime.to_datetime(record.leave_start_date),
                'date_to': fields.Datetime.to_datetime(record.leave_end_date),
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

            template = self.env.ref(
                'hr_holidays.mail_template_leave_approval', raise_if_not_found=False)
            if template:
                try:
                    template.send_mail(record.id, force_send=True)
                except Exception as e:
                    _logger.warning(f"Could not send email notification: {str(e)}")

            if record.employee_id and record.employee_id.parent_id:
                try:
                    manager_employee = record.employee_id.sudo().parent_id
                    manager_user = manager_employee.user_id
                    if manager_user:
                        existing_activity = self.env['mail.activity'].sudo().search([
                            ('res_model', '=', 'hr.leave'),
                            ('res_id', '=', record.id),
                            ('user_id', '=', manager_user.id),
                        ], limit=1)
                        if not existing_activity:
                            manager_user.sudo().activity_schedule(
                                'mail.mail_activity_data_todo',
                                summary=f'Leave Request: {record.holiday_status_id.name if record.holiday_status_id else "Leave"}',
                                note=f'{record.employee_id.name} has requested leave from {record.leave_start_date} to {record.leave_end_date}',
                                user_id=manager_user.id,
                            )
                except Exception as e:
                    _logger.warning(f"Could not create activity: {str(e)}")

        return True

    @api.model
    def _cron_cleanup_abandoned_leave_requests(self):
        """Cleanup unsaved abandoned requests created more than 30 minutes ago."""
        threshold = fields.Datetime.now() - timedelta(minutes=30)
        stale = self.search([
            ('custom_saved', '=', False),
            ('create_date', '<', threshold),
        ])
        if stale:
            _logger.info(
                f"Cleaning up {len(stale)} abandoned leave request(s) "
                f"created by implicit autosave but never submitted.")
            stale.sudo().unlink()

    def _get_leave_balances(self, employee):
        accrued = 0.0
        scheduled = 0.0
        if not employee:
            return {'accrued': accrued, 'scheduled': scheduled}
        try:
            allocations = self.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate')
            ])
            for allocation in allocations:
                accrued += allocation.number_of_days
            current_year = fields.Date.today().year
            leaves_taken = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['validate', 'validate1', 'confirm']),
                ('date_from', '>=', fields.Date.from_string(f'{current_year}-01-01'))
            ])
            for leave in leaves_taken:
                scheduled += leave.number_of_days
        except Exception as e:
            _logger.warning(f"Error calculating leave balances: {str(e)}")
        return {
            'accrued': float_round(accrued, precision_digits=2),
            'scheduled': float_round(scheduled, precision_digits=2)
        }