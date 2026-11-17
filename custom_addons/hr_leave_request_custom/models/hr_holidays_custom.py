# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
from markupsafe import Markup
import base64
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
        user = self.env.user
        # HR/Suspense HR users can request on behalf of other employees
        # (e.g. Suspense Leave). Do NOT lock them to their own employee record.
        is_hr_user = user.has_group('hr_leave_request_custom.group_hr_leave_suspense_hr')
        employee = self._get_current_employee()
        if employee and not is_hr_user:
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
        del_emp_id = ctx.get('default_delegated_employee_id', False)
        if not del_emp_id and defaults.get('employee_id') and 'hr.employee.delegation' in self.env:
            try:
                today = fields.Date.today()
                del_rec = self.env['hr.employee.delegation'].sudo().search([
                    ('employee_id', '=', defaults['employee_id']),
                    ('state', '=', 'submitted'),
                    ('start_date', '<=', today),
                    ('end_date', '>=', today),
                ], order='id desc', limit=1)
                if not del_rec:
                    del_rec = self.env['hr.employee.delegation'].sudo().search([
                        ('employee_id', '=', defaults['employee_id']),
                        ('state', '=', 'submitted'),
                    ], order='start_date desc, id desc', limit=1)
                if del_rec and del_rec.delegate_id:
                    del_emp_id = del_rec.delegate_id.id
            except Exception as e:
                _logger.warning("Could not fetch delegation for default_get: %s", e)
        defaults['delegated_employee_id'] = del_emp_id
        defaults['computed_leave'] = ctx.get('default_computed_leave', 0.0)
        defaults['number_of_days'] = ctx.get('default_number_of_days', 0.0)
        defaults['single_half_day_period'] = ctx.get('default_single_half_day_period', 'am')
        defaults['multi_half_day_period'] = ctx.get('default_multi_half_day_period', False)
        defaults['is_continuous_half_day'] = ctx.get('default_is_continuous_half_day', False)
        defaults['continuous_half_day_period'] = ctx.get('default_continuous_half_day_period', 'am')
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

        del_emp_id = False
        today = fields.Date.today()
        if 'hr.employee.delegation' in self.env and employee:
            try:
                Delegation = self.env['hr.employee.delegation'].sudo()
                del_rec = Delegation.search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'submitted'),
                    ('start_date', '<=', today),
                    ('end_date', '>=', today),
                ], order='id desc', limit=1)
                if not del_rec:
                    del_rec = Delegation.search([
                        ('employee_id', '=', employee.id),
                        ('state', '=', 'submitted'),
                    ], order='start_date desc, id desc', limit=1)
                if del_rec and del_rec.delegate_id:
                    del_emp_id = del_rec.delegate_id.id
            except Exception as e:
                _logger.warning("Could not fetch delegation for employee %s: %s", employee.id, e)

        return {
            'employee_id': employee.id,
            'requester_name': employee.name or '',
            'job_position': job_pos,
            'job_grade': job_grd,
            'job_category': job_cat,
            'operating_unit': op_unit,
            'accrued_leave_balance': balances.get('accrued', 0.0),
            'scheduled_leave_balance': balances.get('scheduled', 0.0),
            'delegated_employee_id': del_emp_id,
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
    is_continuous_half_day = fields.Boolean(string='Continuous Half Day', default=False)
    continuous_half_day_period = fields.Selection([('am', 'Morning'), ('pm', 'Afternoon')], string='Continuous Period', default='am')

    operating_unit = fields.Many2one('operating.unit', string='Operating Unit')
    job_grade = fields.Char(string='Job Grade', readonly=True)
    job_category = fields.Char(string='Job Category', readonly=True)
    job_position = fields.Char(string='Job Position', readonly=True)

    leave_request_description = fields.Text(string='Leave Request Description')
    delegated_employee_id = fields.Many2one(
        'hr.employee',
        string='Delegated Employee',
        compute='_compute_delegated_employee_id',
        store=True,
        readonly=True,
        precompute=True,
        help="Delegated employee automatically populated from submitted Manager Delegations."
    )

    @api.depends('employee_id', 'leave_start_date', 'leave_end_date')
    def _compute_delegated_employee_id(self):
        Delegation = self.env['hr.employee.delegation'].sudo() if 'hr.employee.delegation' in self.env else False
        today = fields.Date.today()
        for record in self:
            if not record.employee_id or not Delegation:
                record.delegated_employee_id = False
                continue

            try:
                start = record.leave_start_date or today
                end = record.leave_end_date or start

                # 1. Search for submitted delegation covering the leave period
                del_rec = Delegation.search([
                    ('employee_id', '=', record.employee_id.id),
                    ('state', '=', 'submitted'),
                    ('start_date', '<=', end),
                    ('end_date', '>=', start),
                ], order='id desc', limit=1)

                # 2. If not found, check active delegation today
                if not del_rec:
                    del_rec = Delegation.search([
                        ('employee_id', '=', record.employee_id.id),
                        ('state', '=', 'submitted'),
                        ('start_date', '<=', today),
                        ('end_date', '>=', today),
                    ], order='id desc', limit=1)

                # 3. If not found, check any submitted delegation for this employee
                if not del_rec:
                    del_rec = Delegation.search([
                        ('employee_id', '=', record.employee_id.id),
                        ('state', '=', 'submitted'),
                    ], order='start_date desc, id desc', limit=1)

                record.delegated_employee_id = del_rec.delegate_id if del_rec else False
            except Exception as e:
                _logger.warning("Error computing delegated_employee_id: %s", e)
                record.delegated_employee_id = False
    requester_name = fields.Char(string='Requester Name', readonly=True)
    accrued_leave_balance = fields.Float(string='Accrued Leave Balance', digits=(16, 2), default=0.0, readonly=True)
    scheduled_leave_balance = fields.Float(string='Scheduled Leave Balance', digits=(16, 2), default=0.0, readonly=True)
    computed_leave = fields.Float(string='Computed Leave', digits=(16, 2), default=0.0, readonly=True)
    attachment = fields.Binary(string='Attachment', attachment=True)
    attachment_name = fields.Char(string='Attachment Name')
    attachment_base64 = fields.Text(
        string='Attachment Base64',
        compute='_compute_attachment_base64',
        help='Base64 (64-bit encoded) string of the uploaded supporting document'
    )
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
    show_refuse_btn = fields.Boolean(string='Show Refuse', compute='_compute_button_visibility')
    show_cancel_btn = fields.Boolean(string='Show Cancel', compute='_compute_button_visibility')
    show_compute_btn = fields.Boolean(string='Show Compute', compute='_compute_button_visibility')

    employee_id_readonly = fields.Boolean(
        string='Employee Readonly',
        compute='_compute_employee_id_readonly',
    )

    employee_gender = fields.Selection(
        selection=[
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
        ],
        string='Employee Gender',
        compute='_compute_employee_gender',
        store=True,
        readonly=True,
    )
    is_hr_user = fields.Boolean(
        string='Is HR User',
        compute='_compute_is_hr_user',
        readonly=True,
    )
    holiday_status_domain = fields.Binary(
        string='Leave Reason Domain',
        compute='_compute_holiday_status_domain',
        readonly=True,
    )

    is_suspense_leave_hr = fields.Boolean(
        string='Is Suspense Leave HR',
        compute='_compute_is_suspense_leave_hr',
    )
    notified_date = fields.Datetime(
        string='Notified Date',
        copy=False,
        help="Timestamp when the leave request was notified to the approver."
    )

    is_lwp_leave = fields.Boolean(
        string='Is Leave Without Pay',
        compute='_compute_is_lwp_leave',
        store=True,
    )
    chief_id = fields.Many2one(
        'hr.employee',
        string='Chief Officer',
        tracking=True,
        help="For Leave Without Pay, select the Chief Officer whose approval is required first.",
    )
    is_chief_notified = fields.Boolean(string='Chief Notified', default=False, tracking=True)
    is_chief_approved = fields.Boolean(string='Chief Approved', default=False, tracking=True)
    chief_approved_by = fields.Many2one('res.users', string='Chief Approved By', readonly=True)
    chief_approved_date = fields.Datetime(string='Chief Approved Date', readonly=True)
    chief_approval_status = fields.Selection([
        ('none', 'Not Required'),
        ('waiting_chief_selection', 'Pending Chief Selection'),
        ('pending_chief', 'Waiting for Chief Approval'),
        ('chief_approved', 'Chief Approved'),
    ], string='Chief Approval Status', compute='_compute_chief_approval_status', store=True)

    show_notify_chief_btn = fields.Boolean(string='Show Notify Chief', compute='_compute_button_visibility')
    show_chief_approve_btn = fields.Boolean(string='Show Chief Approve', compute='_compute_button_visibility')
    is_chief_selectable = fields.Boolean(string='Can Select Chief', compute='_compute_button_visibility')
    show_chief_section = fields.Boolean(string='Show Chief Section', compute='_compute_button_visibility')
    show_chief_manager_banner = fields.Boolean(string='Show Chief Manager Banner', compute='_compute_button_visibility')
    show_chief_pending_banner = fields.Boolean(string='Show Chief Pending Banner', compute='_compute_button_visibility')
    show_chief_approved_banner = fields.Boolean(string='Show Chief Approved Banner', compute='_compute_button_visibility')

    @api.depends('attachment')
    def _compute_attachment_base64(self):
        for record in self:
            if not record.attachment:
                record.attachment_base64 = False
            elif isinstance(record.attachment, bytes):
                record.attachment_base64 = record.attachment.decode('ascii', errors='ignore')
            else:
                record.attachment_base64 = str(record.attachment)

    @api.depends('holiday_status_id', 'holiday_status_id.is_lwp')
    def _compute_is_lwp_leave(self):
        for record in self:
            lt = record.holiday_status_id
            record.is_lwp_leave = bool(lt and (lt.is_lwp or 'without pay' in (lt.name or '').lower()))

    @api.depends('is_lwp_leave', 'is_chief_approved', 'is_chief_notified', 'state', 'leave_request_status')
    def _compute_chief_approval_status(self):
        for record in self:
            if not record.is_lwp_leave:
                record.chief_approval_status = 'none'
            elif record.is_chief_approved:
                record.chief_approval_status = 'chief_approved'
            elif record.is_chief_notified:
                record.chief_approval_status = 'pending_chief'
            elif record.state == 'confirm' or record.leave_request_status == 'notify':
                record.chief_approval_status = 'waiting_chief_selection'
            else:
                record.chief_approval_status = 'none'


    def _get_leave_approver(self):
        self.ensure_one()
        employee = self.employee_id.sudo() if self.employee_id else False
        if not employee:
            return False
        # Priority 1: Coach with linked user
        if employee.coach_id:
            coach = employee.coach_id.sudo()
            if coach.user_id:
                return coach
            coach_user = self.env['res.users'].sudo().search([('employee_ids', 'in', [coach.id])], limit=1)
            if coach_user:
                return coach
            return coach
        # Priority 2: Direct Manager with linked user
        if employee.parent_id:
            parent = employee.parent_id.sudo()
            if parent.user_id:
                return parent
            parent_user = self.env['res.users'].sudo().search([('employee_ids', 'in', [parent.id])], limit=1)
            if parent_user:
                return parent
            return parent
        # Priority 3: Leave Manager
        if employee.leave_manager_id:
            lm_user = employee.leave_manager_id.sudo()
            if lm_user.employee_id:
                return lm_user.employee_id.sudo()
            return employee
        # Priority 4: Fallback to any active Time Off Officer/Manager
        officers = self.env.ref('hr_holidays.group_hr_holidays_user', raise_if_not_found=False)
        if officers:
            officer_users = officers.sudo().all_user_ids if hasattr(officers, 'all_user_ids') else getattr(officers.sudo(), 'user_ids', self.env['res.users'])
            for u in officer_users:
                if u.sudo().employee_id and u != self.env.user:
                    return u.sudo().employee_id
        return False

    @api.depends('employee_id', 'employee_id.gender')
    def _compute_employee_gender(self):
        for record in self:
            record.employee_gender = record.employee_id.gender if record.employee_id else False

    def _get_user_leave_roles(self):
        user = self.env.user
        is_admin = (
            self.env.is_superuser() or
            user.has_group('base.group_system') or
            user.has_group('base.group_erp_manager') or
            user.has_group('hr_holidays.group_hr_holidays_manager')
        )
        is_hr = (
            user.has_group('hr_holidays.group_hr_holidays_user') or
            user.has_group('hr_leave_request_custom.group_hr_leave_suspense_hr') or
            user.has_group('hr.group_hr_manager')
        )
        emp = (user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)).sudo() if user else False
        is_active_delegate = False
        if emp and 'hr.employee.delegation' in self.env:
            try:
                today = fields.Date.today()
                is_active_delegate = bool(self.env['hr.employee.delegation'].sudo().search_count([
                    ('delegate_id', '=', emp.id),
                    ('state', '=', 'submitted'),
                    ('start_date', '<=', today),
                    ('end_date', '>=', today),
                ]))
            except Exception:
                is_active_delegate = False
        is_manager = is_hr or is_admin or is_active_delegate or (
            user.has_group('hr_leave_request_custom.group_hr_holidays_manager_approver') or
            user.has_group('hr_holidays.group_hr_holidays_responsible') or
            bool(emp and emp.child_ids)
        )
        return {
            'is_admin': is_admin,
            'is_hr': is_hr,
            'is_manager': is_manager,
            'is_active_delegate': is_active_delegate,
            'is_employee': True,
        }

    def _compute_is_hr_user(self):
        roles = self._get_user_leave_roles()
        for record in self:
            record.is_hr_user = roles['is_hr']

    @api.depends('employee_id', 'employee_id.gender')
    def _compute_holiday_status_domain(self):
        roles = self._get_user_leave_roles()
        is_admin = roles['is_admin']
        is_hr = roles['is_hr']
        is_manager = roles['is_manager']

        for record in self:
            domain = []

            # 1. Role / Group Filtering:
            if is_admin:
                pass  # Admins can see all leave types
            elif is_hr:
                domain.extend(['|', ('allowed_group', '=', False), ('allowed_group', 'in', ['all', 'manager', 'hr'])])
            elif is_manager:
                domain.extend(['|', ('allowed_group', '=', False), ('allowed_group', 'in', ['all', 'manager'])])
                domain.append(('name', 'not ilike', 'suspense leave'))
            else:
                # Regular employee
                domain.extend(['|', ('allowed_group', '=', False), ('allowed_group', '=', 'all')])
                domain.append(('hr_only', '=', False))
                domain.append(('name', 'not ilike', 'suspense leave'))

            # 2. Gender Filtering:
            gender = record.employee_id.gender if record.employee_id else False
            if gender == 'female':
                domain.extend(['|', ('gender_rule', '=', False), ('gender_rule', 'in', ['all', 'female'])])
            elif gender == 'male':
                domain.extend(['|', ('gender_rule', '=', False), ('gender_rule', 'in', ['all', 'male'])])
            else:
                domain.extend(['|', ('gender_rule', '=', False), ('gender_rule', '=', 'all')])

            record.holiday_status_domain = domain

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

    @api.depends('number_of_days', 'half_day', 'starting_half_day', 'ending_half_day', 'leave_start_date', 'leave_end_date', 'is_continuous_half_day')
    def _compute_half_day_visibility(self):
        for record in self:
            if record.is_continuous_half_day:
                record.is_single_half_day = False
                record.is_multi_half_day = False
                continue
            days = record.number_of_days
            start_date = record.leave_start_date
            end_date = record.leave_end_date
            is_half = (days == 0.5) or (record.half_day and start_date and end_date and start_date == end_date)
            is_multi = (not is_half) and (days > 0)
            record.is_single_half_day = bool(is_half)
            record.is_multi_half_day = bool(is_multi)

    @api.depends('custom_saved', 'is_edit_mode', 'leave_request_status', 'state', 'holiday_status_id', 'holiday_status_id.check_accrual_balance', 'holiday_status_id.is_scheduled_leave', 'is_lwp_leave', 'is_chief_approved', 'is_chief_notified', 'chief_id', 'delegated_employee_id')
    def _compute_button_visibility(self):
        user = self.env.user
        roles = self._get_user_leave_roles()
        is_admin = roles['is_admin']
        is_hr = roles['is_hr']
        is_manager_role = roles['is_manager']

        for record in self:
            saved = record.custom_saved
            editing = record.is_edit_mode
            status = record.leave_request_status
            state = record.state

            # Check if this is the user's own leave request
            is_own_request = bool(record.employee_id and (
                record.employee_id.user_id == user or
                record.employee_id.id in user.employee_ids.ids
            ))

            approver = record._get_leave_approver() if record.employee_id else False
            is_approver = bool(approver and approver.user_id == user)
            is_coach = bool(record.employee_id and (
                (record.employee_id.sudo().coach_id and record.employee_id.sudo().coach_id.user_id == user) or
                (record.employee_id.sudo().coach_id and record.employee_id.sudo().coach_id.id in user.employee_ids.ids)
            ))
            is_manager_rel = bool(record.employee_id and (
                (record.employee_id.sudo().parent_id and record.employee_id.sudo().parent_id.user_id == user) or
                (record.employee_id.sudo().parent_id and record.employee_id.sudo().parent_id.id in user.employee_ids.ids)
            ))
            is_leave_manager = bool(record.employee_id and (
                record.employee_id.leave_manager_id == user or
                (record.employee_id.leave_manager_id and record.employee_id.leave_manager_id.id == user.id) or
                bool(record.employee_id.leave_manager_id.employee_ids.ids and set(record.employee_id.leave_manager_id.employee_ids.ids) & set(user.employee_ids.ids))
            ))
            is_dept_manager = bool(record.employee_id and (
                (record.employee_id.sudo().department_id.manager_id and record.employee_id.sudo().department_id.manager_id.user_id == user) or
                (record.employee_id.sudo().department_id.manager_id and record.employee_id.sudo().department_id.manager_id.id in user.employee_ids.ids)
            ))

            # Check if current user is an active delegate for this employee's manager or specified as delegated employee
            is_delegated_approver = False
            user_emp_ids = (user.employee_id.ids if user.employee_id else []) + user.employee_ids.ids
            if record.delegated_employee_id and (
                (record.delegated_employee_id.user_id and record.delegated_employee_id.user_id == user) or
                record.delegated_employee_id.id in user_emp_ids
            ):
                is_delegated_approver = True
            elif user_emp_ids and 'hr.employee.delegation' in self.env:
                try:
                    today = fields.Date.today()
                    mgr_emp_ids = set()
                    if record.employee_id:
                        emp_sudo = record.employee_id.sudo()
                        if emp_sudo.parent_id:
                            mgr_emp_ids.add(emp_sudo.parent_id.id)
                        if emp_sudo.coach_id:
                            mgr_emp_ids.add(emp_sudo.coach_id.id)
                        if emp_sudo.department_id and emp_sudo.department_id.manager_id:
                            mgr_emp_ids.add(emp_sudo.department_id.manager_id.id)
                        if emp_sudo.leave_manager_id:
                            mgr_emp_ids.update(emp_sudo.leave_manager_id.employee_ids.ids)
                    if mgr_emp_ids:
                        is_delegated_approver = bool(self.env['hr.employee.delegation'].sudo().search_count([
                            ('employee_id', 'in', list(mgr_emp_ids)),
                            ('delegate_id', 'in', user_emp_ids),
                            ('state', '=', 'submitted'),
                            ('start_date', '<=', today),
                            ('end_date', '>=', today),
                        ]))
                except Exception:
                    is_delegated_approver = False

            is_employee_manager = bool(is_approver or is_coach or is_manager_rel or is_leave_manager or is_dept_manager or is_delegated_approver or is_manager_role)

            # Neither Manager nor HR can approve their own leave request!
            if is_own_request and not self.env.is_superuser():
                is_can_approve = False
            else:
                is_can_approve = is_admin or is_hr or is_employee_manager

            record.is_hr_admin = is_admin or is_hr
            record.show_compute_btn = False

            # Chief Officer permissions and button visibility
            record.show_notify_chief_btn = False
            record.show_chief_approve_btn = False
            record.is_chief_selectable = False
            record.show_chief_section = False
            record.show_chief_manager_banner = False
            record.show_chief_pending_banner = False
            record.show_chief_approved_banner = False

            is_chief = bool(
                record.chief_id and (
                    (record.chief_id.sudo().user_id and record.chief_id.sudo().user_id == user) or
                    record.chief_id.id in user.employee_ids.ids
                )
            )

            # Chief section and banners should ONLY appear on Manager/Reviewer side, NEVER on employee side!
            is_manager_or_reviewer = bool(
                (is_employee_manager or is_admin or is_hr or is_chief)
                and not (is_own_request and not self.env.is_superuser())
            )

            # Show Chief section only once submitted (notify / confirm or later) and only to Manager / Chief / Admin
            show_chief_section = bool(
                record.is_lwp_leave
                and is_manager_or_reviewer
                and (status in ('notify', 'approved', 'refused') or state in ('confirm', 'validate', 'validate1', 'refuse'))
            )
            record.show_chief_section = show_chief_section

            is_chief_selectable = bool(
                show_chief_section
                and not record.is_chief_approved
                and record.leave_request_status != 'approved'
                and record.state != 'validate'
                and (is_admin or is_hr or is_employee_manager)
            )
            record.is_chief_selectable = is_chief_selectable

            show_notify_chief = bool(
                show_chief_section
                and (status == 'notify' or state == 'confirm')
                and not record.is_chief_approved
                and (is_admin or is_hr or is_employee_manager)
            )
            record.show_notify_chief_btn = show_notify_chief

            show_chief_approve = bool(
                show_chief_section
                and (status == 'notify' or state == 'confirm')
                and not record.is_chief_approved
                and (is_chief or is_admin)
            )
            record.show_chief_approve_btn = show_chief_approve

            # Manager alerts on top of sheet for Manager / Reviewer
            record.show_chief_manager_banner = bool(
                show_chief_section
                and (status == 'notify' or state == 'confirm')
                and not record.is_chief_approved
                and not record.is_chief_notified
            )
            record.show_chief_pending_banner = bool(
                show_chief_section
                and (status == 'notify' or state == 'confirm')
                and not record.is_chief_approved
                and record.is_chief_notified
            )
            record.show_chief_approved_banner = bool(
                show_chief_section
                and (status == 'notify' or state == 'confirm')
                and record.is_chief_approved
            )

            # Determine who can edit in Approved stage:
            # - STRICT RULE: No one can edit their own approved leave request, regardless of role (Admin, HR, Manager, etc.)
            # - For leave types that require accrued balance (or scheduled balance): HR and Admin can edit other employees' approved leave
            # - For leave types that do NOT require accrual or scheduled balance: Manager can also edit subordinate's approved leave
            lt = record.holiday_status_id
            requires_accrual_or_scheduled = bool(lt and (lt.check_accrual_balance or lt.is_scheduled_leave))

            if is_own_request:
                can_edit_approved = False
            elif is_admin or is_hr:
                can_edit_approved = True
            elif not requires_accrual_or_scheduled and is_employee_manager:
                can_edit_approved = True
            else:
                can_edit_approved = False

            if not saved:
                record.fields_readonly = False
                record.show_save_btn = True
                record.show_notify_btn = True
                record.show_discard_btn = True
                record.show_edit_btn = False
                record.show_approve_btn = False
                record.show_refuse_btn = False
                record.show_cancel_btn = False
            elif status in ('draft', 'fetch') and not (state in ('confirm', 'validate', 'validate1', 'refuse')):
                if editing:
                    record.fields_readonly = False
                    record.show_save_btn = True
                    record.show_notify_btn = True
                    record.show_discard_btn = True
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = False
                else:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = True
                    record.show_discard_btn = True
                    record.show_edit_btn = True
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = False
            elif status == 'notify' or state == 'confirm':
                # Submitted / To Approve stage
                if editing and (is_admin or is_hr or is_employee_manager):
                    record.fields_readonly = False
                    record.show_save_btn = True
                    record.show_notify_btn = False
                    record.show_discard_btn = True
                    record.show_edit_btn = False
                    if record.is_lwp_leave and not record.is_chief_approved:
                        record.show_approve_btn = False
                    else:
                        record.show_approve_btn = is_can_approve
                    if record.is_lwp_leave:
                        record.show_refuse_btn = bool((is_can_approve or is_chief) and not (is_own_request and not self.env.is_superuser()))
                    else:
                        record.show_refuse_btn = is_can_approve
                    record.show_cancel_btn = False
                else:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = False
                    record.show_discard_btn = False
                    record.show_edit_btn = is_admin or is_hr or is_employee_manager
                    if record.is_lwp_leave and not record.is_chief_approved:
                        record.show_approve_btn = False
                    else:
                        record.show_approve_btn = is_can_approve
                    if record.is_lwp_leave:
                        record.show_refuse_btn = bool((is_can_approve or is_chief) and not (is_own_request and not self.env.is_superuser()))
                    else:
                        record.show_refuse_btn = is_can_approve
                    record.show_cancel_btn = False
            elif status == 'approved' or state in ('validate', 'validate1'):
                # Approved stage
                if editing and can_edit_approved:
                    record.fields_readonly = False
                    record.show_save_btn = True
                    record.show_notify_btn = False
                    record.show_discard_btn = True
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = False
                else:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = False
                    record.show_discard_btn = False
                    record.show_edit_btn = can_edit_approved
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = (is_admin or is_hr) and not is_own_request
            elif status == 'refused' or state == 'refuse':
                # Refused stage: employee / requester can edit and re-save/re-notify
                if editing:
                    record.fields_readonly = False
                    record.show_save_btn = True
                    record.show_notify_btn = True
                    record.show_discard_btn = True
                    record.show_edit_btn = False
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = False
                else:
                    record.fields_readonly = True
                    record.show_save_btn = False
                    record.show_notify_btn = False
                    record.show_discard_btn = False
                    record.show_edit_btn = True  # Employee or Admin can click Edit
                    record.show_approve_btn = False
                    record.show_refuse_btn = False
                    record.show_cancel_btn = False
            else:
                record.fields_readonly = True
                record.show_save_btn = False
                record.show_notify_btn = False
                record.show_discard_btn = False
                record.show_edit_btn = is_admin
                record.show_approve_btn = False
                record.show_refuse_btn = False
                record.show_cancel_btn = False

    def _is_suspense_leave_type(self, leave_type):
        """Match by name rather than a dedicated boolean field, per current
        config: any hr.leave.type whose name contains 'Suspense Leave'
        (case-insensitive) is treated as Suspense Leave."""
        return bool(leave_type and leave_type.name and 'suspense leave' in leave_type.name.lower())

    @api.depends_context('uid')
    def _compute_is_suspense_leave_hr(self):
        """Only users with the HR Suspense Leave Authorized role can request
        Suspense Leave on behalf of other employees.
        Administrators and Managers cannot request Suspense Leave on behalf of others."""
        user = self.env.user
        is_hr = user.has_group('hr_leave_request_custom.group_hr_leave_suspense_hr')
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
        ('notify', 'Notify'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancel', 'Cancelled'),
    ], default='fetch', string='Leave Status', readonly=True)

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

        if self.is_continuous_half_day:
            if self.continuous_half_day_period == 'pm':
                self.date_from = start_dt.replace(hour=12, minute=0, second=0)
                self.date_to = end_dt.replace(hour=18, minute=0, second=0)
            else:
                self.date_from = start_dt.replace(hour=6, minute=0, second=0)
                self.date_to = end_dt.replace(hour=11, minute=59, second=59)
        elif self.half_day or self.number_of_days == 0.5:
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
        employee = employee.sudo()
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
        employee = employee.sudo()

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
        emp = self.employee_id.sudo() if self.employee_id else False
        wut = self._get_employee_work_unit_type(emp)
        return wut == 'head_office'

    def _get_day_weight_from_holidays(self, date_val):
        if not date_val:
            return False, 1.0
        # Check if holidays should be deducted:
        # Either 'Ignore Public Holidays' (include_public_holidays_in_duration) is True,
        # OR this is an accrual leave type (check_accrual_balance is True),
        # OR this is Annual / Vacation Leave
        should_check_holidays = bool(
            self.holiday_status_id and (
                self.holiday_status_id.include_public_holidays_in_duration or
                getattr(self.holiday_status_id, 'check_accrual_balance', False) or
                'annual' in (self.holiday_status_id.name or '').lower() or
                'vacation' in (self.holiday_status_id.name or '').lower()
            )
        )
        if not should_check_holidays:
            return False, 1.0

        emp = self.employee_id.sudo() if self.employee_id else False
        emp_wut = self._get_employee_work_unit_type(emp)
        wut_domain = ['|', ('work_unit_type', '=', False), ('work_unit_type', '=', emp_wut)] if emp_wut else [
            ('work_unit_type', '=', False)]
        weekday_str = str(date_val.weekday())

        calendar = self.resource_calendar_id or (emp and emp.resource_calendar_id)
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

        should_check_holidays = bool(
            self.holiday_status_id and (
                self.holiday_status_id.include_public_holidays_in_duration or
                getattr(self.holiday_status_id, 'check_accrual_balance', False) or
                'annual' in (self.holiday_status_id.name or '').lower() or
                'vacation' in (self.holiday_status_id.name or '').lower()
            )
        )
        if should_check_holidays:
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
        if self.is_continuous_half_day:
            return
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
        if self.is_continuous_half_day:
            return
        self._sync_datetime_fields()

    @api.onchange('is_continuous_half_day', 'continuous_half_day_period')
    def _onchange_continuous_half_day(self):
        if self.is_continuous_half_day:
            self.half_day = False
            self.starting_half_day = False
            self.ending_half_day = False
            if self.leave_start_date and self.number_of_days > 0:
                end_date, _ = self._calculate_end_date_from_days(self.leave_start_date, self.number_of_days)
                self.leave_end_date = end_date
                self.computed_leave = self.number_of_days
            elif self.leave_start_date and self.leave_end_date:
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
        else:
            if self.leave_start_date and self.leave_end_date:
                days = self._compute_days_preview()
                self.number_of_days = days
                self.computed_leave = days
                self.half_day = bool(days == 0.5 and self.leave_start_date == self.leave_end_date)
            elif self.leave_start_date and self.number_of_days > 0:
                period = self.multi_half_day_period if (self.number_of_days % 1 != 0 or (self.starting_half_day and self.ending_half_day)) else False
                end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, self.number_of_days, period)
                self.leave_end_date = end_date
                for k, v in half_vals.items():
                    setattr(self, k, v)
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
        epsilon = 1e-4

        if self.is_continuous_half_day:
            remaining = days
            curr_date = effective_start_date
            lookahead = 0
            while True:
                w = self._get_day_weight(curr_date)
                day_contrib = min(w, 0.5) if w > 0 else 0.0
                if day_contrib > 0:
                    if remaining <= day_contrib + epsilon:
                        break
                    remaining -= day_contrib
                curr_date += timedelta(days=1)
                lookahead += 1
                if lookahead > self._MAX_LOOKAHEAD_DAYS:
                    raise UserError(_("Could not find a valid end date for this leave within 730 days."))
            return curr_date, {'half_day': False, 'starting_half_day': False, 'ending_half_day': False}

        if days == 0.5:
            return effective_start_date, {'half_day': True, 'starting_half_day': False, 'ending_half_day': False}

        starts_half = (multi_half_period == 'start')

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

        if self.is_continuous_half_day:
            curr_date = self.leave_start_date
            total_days = 0.0
            while curr_date <= self.leave_end_date:
                w = self._get_day_weight(curr_date)
                if w > 0:
                    total_days += min(w, 0.5)
                curr_date += timedelta(days=1)
            return max(0.0, float_round(total_days, precision_digits=2))

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
        if self.holiday_status_id and self.employee_id:
            employee = self.employee_id.sudo()
            gender = employee.gender if employee else False
            gender_rule = getattr(self.holiday_status_id, 'gender_rule', 'all') or 'all'
            if gender_rule == 'female' and gender != 'female':
                lt_name = self.holiday_status_id.name
                self.holiday_status_id = False
                return {
                    'warning': {
                        'title': _('Gender Restriction'),
                        'message': _("Leave Reason '%s' is only applicable to Female employees.") % lt_name,
                    }
                }
            if gender_rule == 'male' and gender != 'male':
                lt_name = self.holiday_status_id.name
                self.holiday_status_id = False
                return {
                    'warning': {
                        'title': _('Gender Restriction'),
                        'message': _("Leave Reason '%s' is only applicable to Male employees.") % lt_name,
                    }
                }

            # Check role permissions
            roles = self._get_user_leave_roles()
            is_admin = roles['is_admin']
            is_hr = roles['is_hr']
            is_manager = roles['is_manager']
            allowed_group = getattr(self.holiday_status_id, 'allowed_group', 'all') or 'all'
            if getattr(self.holiday_status_id, 'hr_only', False):
                allowed_group = 'hr'

            if allowed_group == 'admin' and not is_admin:
                lt_name = self.holiday_status_id.name
                self.holiday_status_id = False
                return {
                    'warning': {
                        'title': _('Restricted Leave Reason'),
                        'message': _("Leave Reason '%s' is restricted and can only be requested by System Administrators.") % lt_name,
                    }
                }

            if (allowed_group == 'hr' or self._is_suspense_leave_type(self.holiday_status_id)) and not is_hr:
                lt_name = self.holiday_status_id.name
                self.holiday_status_id = False
                return {
                    'warning': {
                        'title': _('Restricted Leave Reason'),
                        'message': _("Leave Reason '%s' is restricted and can only be requested by HR Officers / Administrators.") % lt_name,
                    }
                }

            if allowed_group == 'manager' and not is_manager:
                lt_name = self.holiday_status_id.name
                self.holiday_status_id = False
                return {
                    'warning': {
                        'title': _('Restricted Leave Reason'),
                        'message': _("Leave Reason '%s' is restricted and can only be requested by Managers, HR, or Administrators.") % lt_name,
                    }
                }

            # Check for Leave Without Pay (LWP) restrictions
            is_lwp = bool(self.holiday_status_id.is_lwp or 'without pay' in (self.holiday_status_id.name or '').lower())
            if is_lwp and self.employee_id:
                # 1. Validation: Balance check (Accrued or Scheduled balance > 0.5)
                balances = self._get_leave_balances(self.employee_id)
                accrued = round(float(balances.get('accrued', 0.0) or self.accrued_leave_balance or 0.0), 2)
                scheduled = round(float(balances.get('scheduled', 0.0) or self.scheduled_leave_balance or 0.0), 2)
                if accrued > 0.5 or scheduled > 0.5 or round(accrued + scheduled, 2) > 0.5:
                    self.holiday_status_id = False
                    return {
                        'warning': {
                            'title': _('Leave Without Pay Not Allowed'),
                            'message': _(
                                "Employee '%s' cannot request Leave Without Pay while having available leave balance.\n\n"
                                "Current Balances:\n"
                                "• Accrued Leave Balance: %.2f day(s)\n"
                                "• Scheduled Leave Balance: %.2f day(s)\n\n"
                                "Employees with more than 0.5 day(s) of accrued or scheduled leave balance must utilize their paid leave before requesting Leave Without Pay."
                            ) % (self.employee_id.name, accrued, scheduled)
                        }
                    }

                # 2. Validation: Once per calendar year
                target_year = (self.leave_start_date or fields.Date.today()).year
                start_of_year = date(target_year, 1, 1)
                end_of_year = date(target_year, 12, 31)
                domain = [
                    ('employee_id', '=', self.employee_id.id),
                    ('id', '!=', self._origin.id if self._origin else (self.id or 0)),
                    ('state', 'not in', ('refuse', 'cancel')),
                    ('leave_request_status', 'not in', ('refused', 'cancelled')),
                    '|',
                    ('holiday_status_id.is_lwp', '=', True),
                    ('holiday_status_id.name', 'ilike', 'without pay'),
                    '|', '&',
                    ('leave_start_date', '>=', start_of_year),
                    ('leave_start_date', '<=', end_of_year),
                    '&',
                    ('date_from', '>=', fields.Datetime.to_datetime(start_of_year)),
                    ('date_from', '<=', fields.Datetime.to_datetime(end_of_year)),
                ]
                existing = self.env['hr.leave'].sudo().search(domain, limit=1)
                if existing:
                    ref_name = existing.leave_reference or existing.display_name or f"LR-{existing.id}"
                    self.holiday_status_id = False
                    return {
                        'warning': {
                            'title': _('Leave Without Pay Limit'),
                            'message': _(
                                "Employee '%s' already has a Leave Without Pay request (%s) in %s.\n\n"
                                "Employees can only request Leave Without Pay once per calendar year."
                            ) % (self.employee_id.name, ref_name, target_year)
                        }
                    }

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
                self.half_day = bool(days == 0.5 and not self.is_continuous_half_day)
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
            if self.is_continuous_half_day:
                self.half_day = False
                self.starting_half_day = False
                self.ending_half_day = False
                if self.leave_start_date:
                    end_date, half_vals = self._calculate_end_date_from_days(self.leave_start_date, target_days)
                    self.leave_end_date = end_date
                    for k, v in half_vals.items():
                        setattr(self, k, v)
            elif target_days == 0.5:
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
            self._compute_holiday_status_domain()
            if self.holiday_status_id:
                gender = self.employee_id.gender
                gender_rule = getattr(self.holiday_status_id, 'gender_rule', 'all') or 'all'
                if (gender_rule == 'female' and gender != 'female') or (gender_rule == 'male' and gender != 'male'):
                    self.holiday_status_id = False
                is_lwp = bool(self.holiday_status_id.is_lwp or 'without pay' in (self.holiday_status_id.name or '').lower())
                if is_lwp:
                    balances = self._get_leave_balances(self.employee_id)
                    accrued = round(float(balances.get('accrued', 0.0) or self.accrued_leave_balance or 0.0), 2)
                    scheduled = round(float(balances.get('scheduled', 0.0) or self.scheduled_leave_balance or 0.0), 2)
                    if accrued > 0.5 or scheduled > 0.5 or round(accrued + scheduled, 2) > 0.5:
                        self.holiday_status_id = False
        else:
            self.fetch_status = 'not_fetched'
            self._compute_holiday_status_domain()

    @api.constrains('holiday_status_id', 'employee_id')
    def _check_leave_type_gender_and_hr_rules(self):
        roles = self._get_user_leave_roles()
        is_admin = roles['is_admin']
        is_hr = roles['is_hr']
        is_manager = roles['is_manager']

        for record in self:
            if not record.holiday_status_id or not record.employee_id:
                continue

            leave_type = record.holiday_status_id
            gender = record.employee_id.gender
            gender_rule = getattr(leave_type, 'gender_rule', 'all') or 'all'

            if gender_rule == 'female' and gender != 'female':
                raise ValidationError(_(
                    "Leave Reason '%s' is only applicable to Female employees. Employee '%s' is registered as %s."
                ) % (leave_type.name, record.employee_id.name, (gender.capitalize() if gender else 'Unspecified')))

            if gender_rule == 'male' and gender != 'male':
                raise ValidationError(_(
                    "Leave Reason '%s' is only applicable to Male employees. Employee '%s' is registered as %s."
                ) % (leave_type.name, record.employee_id.name, (gender.capitalize() if gender else 'Unspecified')))

            # Check role permissions
            allowed_group = getattr(leave_type, 'allowed_group', 'all') or 'all'
            if getattr(leave_type, 'hr_only', False):
                allowed_group = 'hr'

            if allowed_group == 'admin' and not is_admin:
                raise ValidationError(_(
                    "Leave Reason '%s' is restricted and can only be requested by System Administrators."
                ) % leave_type.name)

            if (allowed_group == 'hr' or record._is_suspense_leave_type(leave_type)) and not is_hr:
                raise ValidationError(_(
                    "Leave Reason '%s' is restricted and can only be requested by HR Officers / Administrators."
                ) % leave_type.name)

            if allowed_group == 'manager' and not is_manager:
                raise ValidationError(_(
                    "Leave Reason '%s' is restricted and can only be requested by Managers, HR, or Administrators."
                ) % leave_type.name)

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
        if self.env.context.get('leave_skip_date_check') or self.env.context.get('discard_mode') or self.env.context.get('skip_leave_overlap_check'):
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

        if self.is_continuous_half_day:
            period = 'PM' if self.continuous_half_day_period == 'pm' else 'AM'
            curr = start
            while curr <= end:
                slots.add((curr, period))
                curr += timedelta(days=1)
            return slots

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

            roles = record._get_user_leave_roles()
            is_admin = roles['is_admin']
            is_hr = roles['is_hr']
            is_manager = roles['is_manager']
            allowed_group = getattr(leave_type, 'allowed_group', 'all') or 'all'
            if getattr(leave_type, 'hr_only', False):
                allowed_group = 'hr'

            if allowed_group == 'admin' and not is_admin:
                raise UserError(_(
                    "Leave Reason '%s' is restricted to System Administrators only."
                ) % leave_type.name)

            if (allowed_group == 'hr' or record._is_suspense_leave_type(leave_type)) and not is_hr:
                raise UserError(_(
                    "Leave Reason '%s' can only be requested by HR Officers / Administrators."
                ) % leave_type.name)

            if allowed_group == 'manager' and not is_manager:
                raise UserError(_(
                    "Leave Reason '%s' is restricted to Managers, HR, and Administrators."
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

            # Rule: Leave Without Pay (LWP) restrictions
            if record.is_lwp_leave and record.employee_id:
                # 1. Validation: Balance check (Accrued or Scheduled balance > 0.5)
                balances = record._get_leave_balances(record.employee_id)
                accrued = round(float(balances.get('accrued', 0.0) or record.accrued_leave_balance or 0.0), 2)
                scheduled = round(float(balances.get('scheduled', 0.0) or record.scheduled_leave_balance or 0.0), 2)
                if accrued > 0.5 or scheduled > 0.5 or round(accrued + scheduled, 2) > 0.5:
                    raise ValidationError(_(
                        "Employee '%s' cannot request Leave Without Pay while having available leave balance.\n\n"
                        "Current Balances:\n"
                        "- Accrued Leave Balance: %.2f day(s)\n"
                        "- Scheduled Leave Balance: %.2f day(s)\n\n"
                        "Employees with more than 0.5 day(s) of accrued or scheduled leave balance must utilize their paid leave before requesting Leave Without Pay."
                    ) % (record.employee_id.name, accrued, scheduled))

                # 2. Validation: LWP once per calendar year
                target_date = record.leave_start_date or (record.request_date_from or fields.Date.today())
                target_year = target_date.year
                start_of_year = date(target_year, 1, 1)
                end_of_year = date(target_year, 12, 31)
                domain = [
                    ('employee_id', '=', record.employee_id.id),
                    ('id', '!=', record.id or 0),
                    ('state', 'not in', ('refuse', 'cancel')),
                    ('leave_request_status', 'not in', ('refused', 'cancelled')),
                    '|',
                    ('holiday_status_id.is_lwp', '=', True),
                    ('holiday_status_id.name', 'ilike', 'without pay'),
                    '|', '&',
                    ('leave_start_date', '>=', start_of_year),
                    ('leave_start_date', '<=', end_of_year),
                    '&',
                    ('date_from', '>=', fields.Datetime.to_datetime(start_of_year)),
                    ('date_from', '<=', fields.Datetime.to_datetime(end_of_year)),
                ]
                existing = self.env['hr.leave'].sudo().search(domain, limit=1)
                if existing:
                    ref_name = existing.leave_reference or existing.display_name or f"LR-{existing.id}"
                    raise ValidationError(_(
                        "An employee can only request Leave Without Pay (LWP) once per calendar year.\n\n"
                        "Employee '%s' already has a Leave Without Pay request (%s) for the year %s."
                    ) % (record.employee_id.name, ref_name, target_year))

    @api.constrains('holiday_status_id', 'employee_id', 'leave_start_date', 'date_from', 'state')
    def _check_lwp_once_per_year(self):
        for record in self:
            if record.state in ('refuse', 'cancel') or record.leave_request_status in ('refused', 'cancelled'):
                continue
            if record.is_lwp_leave and record.employee_id:
                # Do not retroactively block already approved historic records
                if record.leave_request_status != 'approved' and record.state not in ('validate', 'validate1'):
                    balances = record._get_leave_balances(record.employee_id)
                    accrued = round(float(balances.get('accrued', 0.0) or record.accrued_leave_balance or 0.0), 2)
                    scheduled = round(float(balances.get('scheduled', 0.0) or record.scheduled_leave_balance or 0.0), 2)
                    if accrued > 0.5 or scheduled > 0.5 or round(accrued + scheduled, 2) > 0.5:
                        raise ValidationError(_(
                            "Employee '%s' cannot request Leave Without Pay while having available leave balance.\n\n"
                            "Current Balances:\n"
                            "- Accrued Leave Balance: %.2f day(s)\n"
                            "- Scheduled Leave Balance: %.2f day(s)\n\n"
                            "Employees with more than 0.5 day(s) of accrued or scheduled leave balance must utilize their paid leave before requesting Leave Without Pay."
                        ) % (record.employee_id.name, accrued, scheduled))

                target_date = record.leave_start_date or (record.request_date_from or fields.Date.today())
                target_year = target_date.year
                start_of_year = date(target_year, 1, 1)
                end_of_year = date(target_year, 12, 31)
                domain = [
                    ('employee_id', '=', record.employee_id.id),
                    ('id', '!=', record.id),
                    ('state', 'not in', ('refuse', 'cancel')),
                    ('leave_request_status', 'not in', ('refused', 'cancelled')),
                    '|',
                    ('holiday_status_id.is_lwp', '=', True),
                    ('holiday_status_id.name', 'ilike', 'without pay'),
                    '|', '&',
                    ('leave_start_date', '>=', start_of_year),
                    ('leave_start_date', '<=', end_of_year),
                    '&',
                    ('date_from', '>=', fields.Datetime.to_datetime(start_of_year)),
                    ('date_from', '<=', fields.Datetime.to_datetime(end_of_year)),
                ]
                existing = self.env['hr.leave'].sudo().search(domain, limit=1)
                if existing:
                    ref_name = existing.leave_reference or existing.display_name or f"LR-{existing.id}"
                    raise ValidationError(_(
                        "An employee can only request Leave Without Pay (LWP) once per calendar year.\n\n"
                        "Employee '%s' already has a Leave Without Pay request (%s) for the year %s."
                    ) % (record.employee_id.name, ref_name, target_year))

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
            is_own = bool(holiday.employee_id and (
                holiday.employee_id.user_id == self.env.user or
                holiday.employee_id.id in self.env.user.employee_ids.ids
            ))
            if is_own and (holiday.leave_request_status == 'approved' or holiday.state in ['validate1', 'validate']):
                raise ValidationError(_("You cannot modify your own approved leave request, regardless of your role."))
            if holiday.is_edit_mode or (is_admin and holiday.custom_saved):
                continue
            if holiday.state in ['validate1', 'validate']:
                raise ValidationError(_("This modification is not allowed in the current state."))

    def write(self, vals):
        user = self.env.user
        business_edit_fields = {
            'leave_start_date', 'leave_end_date', 'holiday_status_id',
            'number_of_days', 'half_day', 'starting_half_day', 'ending_half_day',
            'comments', 'attachment', 'continuous_half_day_period',
            'single_half_day_period', 'multi_half_day_period', 'delegated_employee_id',
            'is_continuous_half_day', 'request_date_from', 'request_date_to',
            'date_from', 'date_to', 'is_edit_mode'
        }
        if any(f in vals for f in business_edit_fields) and not self.env.context.get('discard_mode'):
            for record in self:
                is_own = bool(record.employee_id and (
                    record.employee_id.user_id == user or
                    record.employee_id.id in user.employee_ids.ids
                ))
                if is_own and (record.leave_request_status == 'approved' or record.state in ('validate', 'validate1')):
                    if vals.get('is_edit_mode') is False and len(vals) == 1:
                        continue
                    raise UserError(_("You cannot edit your own approved leave request, regardless of your role."))

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

        if 'attachment' in vals or 'attachment_name' in vals:
            self._sync_uploaded_attachment()

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
        records._sync_uploaded_attachment()
        return records

    def _sync_uploaded_attachment(self):
        """
        Ensure any document uploaded in Leave Request is stored in Base64 (64-bit) format
        and synchronized with ir.attachment linked to this hr.leave record.
        """
        Attachment = self.env['ir.attachment'].sudo()
        for record in self:
            if not record.attachment:
                continue

            data = record.attachment
            if isinstance(data, bytes):
                try:
                    base64.b64decode(data, validate=True)
                    b64_data = data
                except Exception:
                    b64_data = base64.b64encode(data)
            elif isinstance(data, str):
                try:
                    base64.b64decode(data.encode('ascii'), validate=True)
                    b64_data = data
                except Exception:
                    b64_data = base64.b64encode(data.encode('utf-8')).decode('ascii')
            else:
                b64_data = data

            filename = record.attachment_name or f"Leave_Document_{record.leave_reference or record.id}"

            existing_attachment = Attachment.search([
                ('res_model', '=', 'hr.leave'),
                ('res_id', '=', record.id),
                '|', ('res_field', '=', 'attachment'), ('name', '=', filename)
            ], limit=1)

            if existing_attachment:
                existing_attachment.write({
                    'name': filename,
                    'datas': b64_data,
                    'res_field': 'attachment',
                })
                att_id = existing_attachment.id
            else:
                new_att = Attachment.create({
                    'name': filename,
                    'type': 'binary',
                    'datas': b64_data,
                    'res_model': 'hr.leave',
                    'res_id': record.id,
                    'res_field': 'attachment',
                })
                att_id = new_att.id

            if hasattr(record, 'attachment_ids') and att_id not in record.attachment_ids.ids:
                record.sudo().write({'attachment_ids': [(4, att_id)]})

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
        user = self.env.user
        for record in self:
            is_own = bool(record.employee_id and (
                record.employee_id.user_id == user or
                record.employee_id.id in user.employee_ids.ids
            ))
            if is_own and (record.leave_request_status == 'approved' or record.state in ('validate', 'validate1')):
                raise UserError(_("You cannot edit your own approved leave request, regardless of your role."))
            record = record.with_context(leave_skip_state_check=True, leave_skip_date_check=True)
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason before saving."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date before saving."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days) before saving."))

            if record.is_continuous_half_day:
                record.half_day = False
                record.starting_half_day = False
                record.ending_half_day = False

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

            is_already_approved = (record.leave_request_status == 'approved' or record.state in ('validate', 'validate1'))

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
                'is_continuous_half_day': record.is_continuous_half_day,
                'continuous_half_day_period': record.continuous_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
            }
            if is_already_approved:
                vals['leave_request_status'] = 'approved'
                vals['state'] = 'validate'
            else:
                vals['leave_request_status'] = 'draft'
                if record.state != 'confirm':
                    vals['state'] = 'confirm'

            record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)

            if is_already_approved:
                # Sync resource calendar leave entries for the updated dates
                try:
                    record.sudo()._remove_resource_leave()
                    record.sudo()._create_resource_leave()
                except Exception as e:
                    _logger.warning(f"Could not re-sync resource calendar leaves on approved edit: {e}")

                # Post update note in chatter
                try:
                    record.sudo().message_post(
                        body=Markup(_("Leave request dates/details were updated by <b>%s</b>.<br/><b>New Dates:</b> %s &rarr; %s (%s day(s))") % (
                            self.env.user.name,
                            record.leave_start_date,
                            record.leave_end_date or record.leave_start_date,
                            record.number_of_days
                        )),
                        subtype_xmlid='mail.mt_note',
                    )
                except Exception as e:
                    _logger.warning(f"Could not post edit chatter note: {e}")

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after save: {e}")

        return True

    def action_edit_custom(self):
        user = self.env.user
        for record in self:
            is_own = bool(record.employee_id and (
                record.employee_id.user_id == user or
                record.employee_id.id in user.employee_ids.ids
            ))
            if is_own and (record.leave_request_status == 'approved' or record.state in ('validate', 'validate1')):
                raise UserError(_("You cannot edit your own approved leave request, regardless of your role."))
            record.write({'is_edit_mode': True})
        return True

    def action_notify_chief(self):
        for record in self:
            if not record.chief_id:
                raise UserError(_("Please select the Chief Officer before notifying."))

            record.write({
                'is_chief_notified': True,
            })
            record._assign_leave_reference()
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Pending")

            # Schedule activity for Chief
            if record.chief_id.user_id:
                activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                if activity_type:
                    try:
                        record.sudo().activity_ids.filtered(
                            lambda a: a.activity_type_id == activity_type and a.summary and 'Chief' in a.summary
                        ).unlink()
                        record.sudo().activity_schedule(
                            activity_type_id=activity_type.id,
                            summary=_("[%s] Chief Approval Required: %s - Leave Without Pay") % (ref_no, record.employee_id.name),
                            note=_(
                                "Leave Request Reference: <b>%s</b><br/>"
                                "Employee <b>%s</b> has requested <b>Leave Without Pay</b> (%s day(s) from %s to %s).<br/>"
                                "Manager <b>%s</b> has forwarded this request for your Chief Officer approval.<br/>"
                                "Please review and approve or refuse."
                            ) % (
                                ref_no,
                                record.employee_id.name,
                                record.number_of_days,
                                record.leave_start_date,
                                record.leave_end_date or record.leave_start_date,
                                self.env.user.name,
                            ),
                            user_id=record.chief_id.user_id.id,
                        )
                    except Exception as e:
                        _logger.warning(f"Could not schedule activity for chief: {e}")

            # Post chatter notification
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
            record_url = f"{base_url}/odoo/time-off/{record.id}" if base_url else f"/odoo/time-off/{record.id}"
            partner_id = record.chief_id.user_id.partner_id.id if record.chief_id.user_id and record.chief_id.user_id.partner_id else False

            notify_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #fffcf9; border: 1px solid #ebdcd0; border-left: 5px solid #c17540; border-radius: 8px; padding: 16px 20px; margin: 6px 0;">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #f0e6dd; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #541718;">
            📋 Leave Without Pay: Forwarded to Chief Officer
        </span>
        <span style="background-color: #c17540; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #726732; width: 140px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Employee:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{record.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: 600;">{record.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{record.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{record.leave_start_date} &rarr; {record.leave_end_date or record.leave_start_date}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Forwarded by:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{self.env.user.name}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Chief Officer:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: bold;">{record.chief_id.name}</td>
        </tr>
    </table>
    <div style="margin-top: 15px; text-align: center;">
        <a href="{record_url}" style="background-color: #541718; color: #ffffff; padding: 8px 18px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block;">
            👉 Review &amp; Approve as Chief ({ref_no})
        </a>
    </div>
</div>
"""
            try:
                record.sudo().message_post(
                    body=Markup(notify_body),
                    subject=_("[%s] Forwarded to Chief for Approval: %s") % (ref_no, record.employee_id.name),
                    partner_ids=[partner_id] if partner_id else [],
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception as e:
                _logger.warning(f"Could not post chief chatter: {e}")

    def action_chief_approve(self):
        for record in self:
            if record.employee_id and record.employee_id.user_id == self.env.user and not self.env.is_superuser():
                raise UserError(_("You cannot approve your own leave request."))

            record.write({
                'is_chief_approved': True,
                'chief_approved_by': self.env.user.id,
                'chief_approved_date': fields.Datetime.now(),
            })
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Approved")

            # Mark pending chief activities done
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            activities = record.activity_ids.filtered(lambda a: (activity_type and a.activity_type_id == activity_type) or (a.summary and 'Chief' in a.summary))
            if activities:
                try:
                    activities.sudo().action_feedback(feedback=_("Chief approval granted by %s.") % self.env.user.name)
                except Exception as e:
                    _logger.warning(f"Could not complete chief activity: {e}")

            # Notify the manager that Chief approved and manager can now approve
            approver = record._get_leave_approver()
            manager_user = approver.user_id if approver and approver.user_id else False
            if manager_user:
                try:
                    record.sudo().activity_schedule(
                        activity_type_id=activity_type.id if activity_type else 1,
                        summary=_("[%s] Chief Approved - Ready for Manager Approval: %s") % (ref_no, record.employee_id.name),
                        note=_(
                            "Chief Officer <b>%s</b> has approved the Leave Without Pay request for <b>%s</b>.<br/>"
                            "You can now provide final Manager Approval."
                        ) % (self.env.user.name, record.employee_id.name),
                        user_id=manager_user.id,
                    )
                except Exception as e:
                    _logger.warning(f"Could not schedule activity for manager: {e}")

            # Post chatter
            chief_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #f6fbf7; border: 1px solid #d4edd9; border-left: 5px solid #28a745; border-radius: 8px; padding: 16px 20px; margin: 6px 0;">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #d4edd9; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #155724;">
            ✅ Chief Officer Approval Granted
        </span>
        <span style="background-color: #28a745; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px;">
            {ref_no}
        </span>
    </div>
    <p>Approved by Chief Officer <b>{self.env.user.name}</b>. The request is now ready for final Manager approval.</p>
</div>
"""
            try:
                record.sudo().message_post(
                    body=Markup(chief_body),
                    subject=_("[%s] Chief Approved: %s") % (ref_no, record.employee_id.name),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception as e:
                _logger.warning(f"Could not post chief approve chatter: {e}")
    def _get_approver_info(self):
        self.ensure_one()
        user = self.env.user
        emp_ids = (user.employee_id.ids if user.employee_id else []) + user.employee_ids.ids
        today = fields.Date.today()
        del_rec = False
        if emp_ids and 'hr.employee.delegation' in self.env:
            try:
                if self.delegated_employee_id and self.delegated_employee_id.id in emp_ids:
                    del_rec = self.env['hr.employee.delegation'].sudo().search([
                        ('delegate_id', 'in', emp_ids),
                        ('state', '=', 'submitted'),
                        ('start_date', '<=', today),
                        ('end_date', '>=', today),
                    ], limit=1)
                if not del_rec and self.employee_id:
                    mgr_emp_ids = set()
                    emp_sudo = self.employee_id.sudo()
                    if emp_sudo.parent_id:
                        mgr_emp_ids.add(emp_sudo.parent_id.id)
                    if emp_sudo.coach_id:
                        mgr_emp_ids.add(emp_sudo.coach_id.id)
                    if emp_sudo.department_id and emp_sudo.department_id.manager_id:
                        mgr_emp_ids.add(emp_sudo.department_id.manager_id.id)
                    if emp_sudo.leave_manager_id:
                        mgr_emp_ids.update(emp_sudo.leave_manager_id.employee_ids.ids)
                    if mgr_emp_ids:
                        del_rec = self.env['hr.employee.delegation'].sudo().search([
                            ('employee_id', 'in', list(mgr_emp_ids)),
                            ('delegate_id', 'in', emp_ids),
                            ('state', '=', 'submitted'),
                            ('start_date', '<=', today),
                            ('end_date', '>=', today),
                        ], limit=1)
            except Exception:
                del_rec = False

        if del_rec and del_rec.employee_id:
            approver_str = f"{user.name} (on behalf of Manager {del_rec.employee_id.name} via delegation)"
            approver_html = f"<b>{user.name}</b> (on behalf of Manager <b>{del_rec.employee_id.name}</b> via delegation)"
        else:
            approver_str = user.name
            approver_html = f"<b>{user.name}</b>"
        return approver_str, approver_html

    def action_admin_approve_edit(self):
        for record in self:
            is_own = bool(record.employee_id and (
                record.employee_id.user_id == self.env.user or
                record.employee_id.id in self.env.user.employee_ids.ids
            ))
            if is_own and not self.env.is_superuser():
                raise UserError(_("You cannot approve your own leave request."))
            if record.is_lwp_leave and not record.is_chief_approved:
                chief_name = record.chief_id.name if record.chief_id else _("Chief Officer")
                raise UserError(_(
                    "For Leave Without Pay, the request must first be approved by the Chief Officer (%s) before Manager approval."
                ) % chief_name)
            record = record.with_context(leave_skip_state_check=True, leave_skip_date_check=True)
            if not record.holiday_status_id:
                raise UserError(_("Please select a Leave Reason."))
            if not record.leave_start_date:
                raise UserError(_("Please fill in Start Date."))
            if not record.leave_end_date and record.number_of_days <= 0:
                raise UserError(_("Please fill in either End Date or Duration (Days)."))

            if record.is_continuous_half_day:
                record.half_day = False
                record.starting_half_day = False
                record.ending_half_day = False

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
                'is_continuous_half_day': record.is_continuous_half_day,
                'continuous_half_day_period': record.continuous_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
                'leave_request_status': 'approved',
            }
            if record.state != 'validate':
                vals['state'] = 'validate'

            record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)

            # Mark pending approval activities done
            approver_str, approver_html = record._get_approver_info()
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            activities = record.activity_ids.filtered(lambda a: (activity_type and a.activity_type_id == activity_type) or (a.summary and 'Approval' in a.summary))
            if activities:
                try:
                    activities.sudo().action_feedback(feedback=_("Leave request approved by %s.") % approver_str)
                except Exception as e:
                    _logger.warning(f"Could not complete activity on approve: {e}")

            # Notify the employee in Odoo
            record._assign_leave_reference()
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Approved")
            emp_user = record.employee_id.user_id
            if emp_user and emp_user.partner_id:
                approved_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #f6fbf7; border: 1px solid #d4edd9; border-left: 5px solid #28a745; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #d4edd9; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #155724;">
            ✅ Leave Request Approved
        </span>
        <span style="background-color: #28a745; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #555; width: 130px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #155724; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Employee:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{record.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #155724; font-weight: 600;">{record.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{record.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{record.leave_start_date} &rarr; {record.leave_end_date or record.leave_start_date}</td>
        </tr>
    </table>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #c3e6cb; font-size: 12px; color: #155724;">
        Approved by {approver_html}.
    </div>
</div>
"""
                try:
                    record.sudo().message_post(
                        body=Markup(approved_body),
                        subject=_("[%s] Leave Request Approved: %s") % (ref_no, record.holiday_status_id.name),
                        partner_ids=[emp_user.partner_id.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception as e:
                    _logger.warning(f"Could not post approve chatter: {e}")

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after approve: {e}")
                _logger.warning(f"Could not refresh leave balances after approve edit: {e}")

        return True

    def action_discard_custom(self):
        for record in self:
            if record.leave_request_status in ('approved', 'notify', 'refused') or record.state in ('validate', 'validate1', 'confirm', 'refuse') or (record.custom_saved and record.leave_request_status == 'draft'):
                record.sudo().write({'is_edit_mode': False})
                return True
            else:
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

            if record.is_continuous_half_day:
                record.half_day = False
                record.starting_half_day = False
                record.ending_half_day = False

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
                'is_continuous_half_day': record.is_continuous_half_day,
                'continuous_half_day_period': record.continuous_half_day_period,
                'computed_leave': days,
                'number_of_days': days,
                'is_computed': True,
                'custom_saved': True,
                'is_edit_mode': False,
                'leave_request_status': 'notify',
                'notified_date': fields.Datetime.now(),
                'is_chief_notified': False,
                'is_chief_approved': False,
                'chief_approved_by': False,
                'chief_approved_date': False,
            }
            if record.state != 'confirm':
                vals['state'] = 'confirm'

            record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write(vals)
            record._assign_leave_reference()
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Pending")

            # Refresh balances on the record so UI shows updated values
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after notify: {e}")

            # Notify Approver (Coach/Manager)
            try:
                approver = record._get_leave_approver()
                if approver and approver.user_id:
                    # Schedule To-Do activity
                    activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                    if activity_type:
                        try:
                            record.sudo().activity_ids.filtered(
                                lambda a: a.activity_type_id == activity_type or (a.summary and 'Approval' in a.summary)
                            ).unlink()
                            record.sudo().activity_schedule(
                                activity_type_id=activity_type.id,
                                summary=_("[%s] Leave Request Approval: %s - %s") % (ref_no, record.employee_id.name, record.holiday_status_id.name),
                                note=_(
                                    "Leave Request Reference: <b>%s</b><br/>"
                                    "Employee <b>%s</b> has submitted a Leave Request for <b>%s</b> (%s day(s) from %s to %s).<br/>"
                                    "Please review and approve or refuse."
                                ) % (
                                    ref_no,
                                    record.employee_id.name,
                                    record.holiday_status_id.name,
                                    record.number_of_days,
                                    record.leave_start_date,
                                    record.leave_end_date or record.leave_start_date,
                                ),
                                user_id=approver.user_id.id,
                            )
                        except Exception as act_err:
                            _logger.warning(f"Could not schedule activity: {act_err}")

                    # Post formatted message on chatter with direct link button
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
                    record_url = f"{base_url}/odoo/time-off/{record.id}" if base_url else f"/odoo/time-off/{record.id}"
                    partner_id = approver.user_id.partner_id.id if approver.user_id.partner_id else False
                    desc_html = f'<tr><td style="padding: 5px 0; color: #726732; font-weight: 600;">Description:</td><td style="padding: 5px 0; color: #555;">{record.leave_request_description}</td></tr>' if record.leave_request_description else ''
                    notify_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #fffcf9; border: 1px solid #ebdcd0; border-left: 5px solid #c17540; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #f0e6dd; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #541718;">
            📋 Leave Request Submitted for Approval
        </span>
        <span style="background-color: #c17540; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #726732; width: 130px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Requester:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{record.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: 600;">{record.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{record.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{record.leave_start_date} &rarr; {record.leave_end_date or record.leave_start_date}</td>
        </tr>
        {desc_html}
    </table>
    <div style="margin-top: 15px; text-align: center;">
        <a href="{record_url}" style="background-color: #541718; color: #ffffff; padding: 8px 18px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block;">
            👉 Review &amp; Approve Leave Request ({ref_no})
        </a>
    </div>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e2d2c5; font-size: 12px; color: #726732;">
        Notified to approver <b>{approver.name}</b> for review and approval.
    </div>
</div>
"""
                    try:
                        record.sudo().message_post(
                            body=Markup(notify_body),
                            subject=_("[%s] Leave Request Submitted: %s - %s") % (ref_no, record.employee_id.name, record.holiday_status_id.name),
                            partner_ids=[partner_id] if partner_id else [],
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                        )
                    except Exception as post_err:
                        _logger.warning(f"Could not post chatter notification: {post_err}")
            except Exception as approver_err:
                _logger.warning(f"Could not resolve or notify approver: {approver_err}")

    def _get_next_states_by_state(self):
        state_result = super()._get_next_states_by_state()
        user = self.env.user
        for leave in self:
            is_coach = bool(leave.employee_id and (
                (leave.employee_id.sudo().coach_id and leave.employee_id.sudo().coach_id.user_id == user) or
                (leave.employee_id.sudo().coach_id and leave.employee_id.sudo().coach_id.id in user.employee_ids.ids)
            ))
            is_parent = bool(leave.employee_id and (
                (leave.employee_id.sudo().parent_id and leave.employee_id.sudo().parent_id.user_id == user) or
                (leave.employee_id.sudo().parent_id and leave.employee_id.sudo().parent_id.id in user.employee_ids.ids)
            ))
            is_chief = bool(leave.chief_id and (
                (leave.chief_id.sudo().user_id and leave.chief_id.sudo().user_id == user) or
                (leave.chief_id.id in user.employee_ids.ids)
            ))
            is_manager_group = user.has_group('hr_leave_request_custom.group_hr_holidays_manager_approver')
            is_own = bool(leave.employee_id and leave.employee_id.user_id == user)

            if (is_coach or is_parent or is_chief or is_manager_group) and not (is_own and not self.env.is_superuser()):
                state_result['confirm'].update({'validate', 'refuse', 'validate1'})
                state_result['validate1'].update({'validate', 'refuse'})
                state_result['refuse'].update({'confirm', 'validate'})
        return state_result

    def _check_approval_update(self, state, raise_if_not_possible=True):
        if self.env.is_superuser():
            return True
        user = self.env.user
        for leave in self:
            is_own = bool(leave.employee_id and leave.employee_id.user_id == user)
            if is_own and not self.env.is_superuser() and state in ('validate', 'validate1', 'refuse'):
                if raise_if_not_possible:
                    raise UserError(_("You cannot approve or refuse your own leave request."))
                return False
            is_coach = bool(leave.employee_id and (
                (leave.employee_id.sudo().coach_id and leave.employee_id.sudo().coach_id.user_id == user) or
                (leave.employee_id.sudo().coach_id and leave.employee_id.sudo().coach_id.id in user.employee_ids.ids)
            ))
            is_parent = bool(leave.employee_id and (
                (leave.employee_id.sudo().parent_id and leave.employee_id.sudo().parent_id.user_id == user) or
                (leave.employee_id.sudo().parent_id and leave.employee_id.sudo().parent_id.id in user.employee_ids.ids)
            ))
            is_chief = bool(leave.chief_id and (
                (leave.chief_id.sudo().user_id and leave.chief_id.sudo().user_id == user) or
                (leave.chief_id.id in user.employee_ids.ids)
            ))
            is_manager_group = user.has_group('hr_leave_request_custom.group_hr_holidays_manager_approver')
            if (is_coach or is_parent or is_chief or is_manager_group) and state in ('validate', 'validate1', 'refuse'):
                return True
        return super()._check_approval_update(state, raise_if_not_possible=raise_if_not_possible)

    def unlink(self):
        for record in self:
            if record.state in ('validate', 'validate1') or record.leave_request_status == 'approved':
                raise UserError(_(
                    "Approved leave request '%s' (%s) cannot be deleted. "
                    "It must be refused before it can be deleted."
                ) % (
                    record.leave_reference or record.name or record.display_name,
                    record.employee_id.name if record.employee_id else ''
                ))
        return super().unlink()

    def action_approve(self, check_state=True):
        for record in self:
            is_own = bool(record.employee_id and (
                record.employee_id.user_id == self.env.user or
                record.employee_id.id in self.env.user.employee_ids.ids
            ))
            if is_own and not self.env.is_superuser():
                raise UserError(_("You cannot approve your own leave request."))
            if record.is_lwp_leave and not record.is_chief_approved:
                chief_name = record.chief_id.name if record.chief_id else _("Chief Officer")
                raise UserError(_(
                    "For Leave Without Pay, the request must first be approved by the Chief Officer (%s) before Manager approval."
                ) % chief_name)
        res = super().action_approve(check_state=check_state)
        for record in self:
            record._assign_leave_reference()
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Approved")
            approver_str, approver_html = record._get_approver_info()
            # Mark pending approval activities done
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            activities = record.activity_ids.filtered(lambda a: (activity_type and a.activity_type_id == activity_type) or (a.summary and 'Approval' in a.summary))
            if activities:
                try:
                    activities.sudo().action_feedback(feedback=_("[%s] Leave request approved by %s.") % (ref_no, approver_str))
                except Exception as e:
                    _logger.warning(f"Could not complete activity on approve: {e}")

            # Notify the employee
            emp_user = record.employee_id.user_id
            if emp_user and emp_user.partner_id:
                approved_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #f6fbf7; border: 1px solid #d4edd9; border-left: 5px solid #28a745; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #d4edd9; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #155724;">
            ✅ Leave Request Approved
        </span>
        <span style="background-color: #28a745; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #555; width: 130px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #155724; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Employee:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{record.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #155724; font-weight: 600;">{record.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{record.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{record.leave_start_date} &rarr; {record.leave_end_date or record.leave_start_date}</td>
        </tr>
    </table>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #c3e6cb; font-size: 12px; color: #155724;">
        Approved by {approver_html}.
    </div>
</div>
"""
                try:
                    record.sudo().message_post(
                        body=Markup(approved_body),
                        subject=_("[%s] Leave Request Approved: %s") % (ref_no, record.holiday_status_id.name),
                        partner_ids=[emp_user.partner_id.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception as e:
                    _logger.warning(f"Could not post approve chatter: {e}")
            # Refresh balances & status
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.sudo().with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'leave_request_status': 'approved',
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after approve: {e}")
        return res

    def action_refuse(self):
        for record in self:
            is_own = bool(record.employee_id and (
                record.employee_id.user_id == self.env.user or
                record.employee_id.id in self.env.user.employee_ids.ids
            ))
            if is_own and not self.env.is_superuser():
                raise UserError(_("You cannot refuse your own leave request."))
        res = super().action_refuse()
        for record in self:
            record._assign_leave_reference()
            ref_no = record.leave_reference or (f"LR-{record.id:06d}" if record.id else "LR-Refused")
            approver_str, approver_html = record._get_approver_info()
            # Mark pending approval activities done
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            activities = record.activity_ids.filtered(lambda a: (activity_type and a.activity_type_id == activity_type) or (a.summary and 'Approval' in a.summary))
            if activities:
                try:
                    activities.sudo().action_feedback(feedback=_("[%s] Leave request refused by %s.") % (ref_no, approver_str))
                except Exception as e:
                    _logger.warning(f"Could not complete activity on refuse: {e}")

            # Notify the employee
            emp_user = record.employee_id.user_id
            if emp_user and emp_user.partner_id:
                refused_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #fdf7f7; border: 1px solid #f5c6cb; border-left: 5px solid #dc3545; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #f5c6cb; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #721c24;">
            ❌ Leave Request Refused
        </span>
        <span style="background-color: #dc3545; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #555; width: 130px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #721c24; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Employee:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{record.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #721c24; font-weight: 600;">{record.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{record.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #555; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{record.leave_start_date} &rarr; {record.leave_end_date or record.leave_start_date}</td>
        </tr>
    </table>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #f5c6cb; font-size: 12px; color: #721c24;">
        Refused by {approver_html}.
    </div>
</div>
"""
                try:
                    record.sudo().message_post(
                        body=Markup(refused_body),
                        subject=_("[%s] Leave Request Refused: %s") % (ref_no, record.holiday_status_id.name),
                        partner_ids=[emp_user.partner_id.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception as e:
                    _logger.warning(f"Could not post refuse chatter: {e}")
            # Refresh balances & status
            try:
                balances = record._get_leave_balances(record.employee_id)
                record.with_context(leave_skip_state_check=True, leave_skip_date_check=True).write({
                    'leave_request_status': 'refused',
                    'accrued_leave_balance': balances.get('accrued', 0.0),
                    'scheduled_leave_balance': balances.get('scheduled', 0.0),
                })
            except Exception as e:
                _logger.warning(f"Could not refresh leave balances after refuse: {e}")
        return res

    @api.model
    def _cron_remind_pending_leave_approvals(self):
        """Finds leave requests that have been in 'confirm' (To Approve) state
        for 3 or more days and sends daily reminder notifications to the approver (coach_id).
        """
        now = fields.Datetime.now()
        three_days_ago = now - timedelta(days=3)
        pending_leaves = self.search([
            ('state', '=', 'confirm'),
            ('custom_saved', '=', True),
            '|',
            ('notified_date', '<=', three_days_ago),
            '&',
            ('notified_date', '=', False),
            ('write_date', '<=', three_days_ago),
        ])

        for leave in pending_leaves:
            ref_date = leave.notified_date or leave.write_date or leave.create_date
            pending_days = (now.date() - fields.Date.to_date(ref_date)).days if ref_date else 3
            if pending_days < 3:
                continue

            leave._assign_leave_reference()
            ref_no = leave.leave_reference or (f"LR-{leave.id:06d}" if leave.id else "LR-Pending")

            approver = leave._get_leave_approver()
            if approver and approver.user_id:
                partner_id = approver.user_id.partner_id.id if approver.user_id.partner_id else False
                reminder_body = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #fffdf5; border: 1px solid #faebcc; border-left: 5px solid #d97706; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #faebcc; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #92400e;">
            ⏰ Approval Reminder: Pending {pending_days} Days
        </span>
        <span style="background-color: #d97706; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {ref_no}
        </span>
    </div>
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr>
            <td style="padding: 5px 0; color: #726732; width: 130px; font-weight: 600;">Reference No:</td>
            <td style="padding: 5px 0; color: #92400e; font-weight: bold;">{ref_no}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Requester:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: 600;">{leave.employee_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Leave Reason:</td>
            <td style="padding: 5px 0; color: #541718; font-weight: 600;">{leave.holiday_status_id.name or ''}</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Duration:</td>
            <td style="padding: 5px 0; color: #1d2b32; font-weight: bold;">{leave.number_of_days} Day(s)</td>
        </tr>
        <tr>
            <td style="padding: 5px 0; color: #726732; font-weight: 600;">Dates:</td>
            <td style="padding: 5px 0; color: #1d2b32;">{leave.leave_start_date} &rarr; {leave.leave_end_date or leave.leave_start_date}</td>
        </tr>
    </table>
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #faebcc; font-size: 12px; color: #92400e;">
        This leave request has been awaiting approval for <b>{pending_days} days</b>. Please review and <b>Approve</b> or <b>Refuse</b> it.
    </div>
</div>
"""
                leave.message_post(
                    body=Markup(reminder_body),
                    subject=_("[%s] Approval Reminder: Pending Leave Request for %s (%s days)") % (ref_no, leave.employee_id.name, leave.number_of_days),
                    partner_ids=[partner_id] if partner_id else [],
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

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
            # Search for Opening Balance allocations by name / description / holiday_status_id (case-insensitive)
            ob_allocs = self.env['hr.leave.allocation'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                '|', '|', '|',
                ('name', '=ilike', opening_balance_name),
                ('name', 'ilike', opening_balance_name),
                ('holiday_status_id.name', '=ilike', opening_balance_name),
                ('holiday_status_id.name', 'ilike', opening_balance_name),
            ])
            opening_balance_leave = sum(a.number_of_days for a in ob_allocs)
            if opening_balance_leave:
                _logger.info("Found Opening Balance Load allocation of %s days for employee %s",
                             opening_balance_leave, employee.name)
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

        # Opening Balance is folded into the "completed" bucket since it represents
        # leave already banked as of the policy cutover.
        gross_accrued_completed = accrued_completed + opening_balance_leave

        # Calculate the maximum total balance allowed by category. This cap
        # is anchored on the LAST COMPLETED accrual year's entitlement.
        # If no year completed within the post-cutover loop, derive anchor from
        # the employee's seniority (completed years of service as of as_of_date).
        if last_completed_entitlement is not None:
            anchor_entitlement = last_completed_entitlement
        elif hire_date:
            years_service = relativedelta(as_of_date, hire_date).years
            completed_offset = max(0, years_service - 1) if years_service >= 1 else 0
            anchor_entitlement = base_entitlement + completed_offset
        else:
            anchor_entitlement = base_entitlement

        if str(employee_category).lower() == 'managerial':
            cap_years = managerial_cap_years
        else:
            cap_years = non_managerial_cap_years

        max_allowed_carryover = sum(
            max(0, anchor_entitlement - yr)
            for yr in range(cap_years)
        )

        # Enforce maximum balance ceiling (carryover cap) on completed years.
        # Note: An explicit Opening Balance Load approved by HR represents the verified baseline
        # starting balance at policy cutover, so the cap on completed years cannot be lower than
        # the approved opening balance itself.
        maximum_eligible_accrual = max(max_allowed_carryover, opening_balance_leave)

        eligible_completed = min(
            gross_accrued_completed,
            maximum_eligible_accrual,
        )

        # The current, still-in-progress accrual year is added on top of the
        # capped completed-years total, uncapped for now.
        eligible = eligible_completed + accrued_current_partial

        return float_round(
            max(0.0, eligible),
            precision_digits=2,
        )

    def _get_leave_balances(self, employee, as_of_date=None):
        """Waterfall balance derivation:
        1. Scheduled pool = Total approved/saved Scheduled Leaves - Total consumed by actual leaves.
        2. Accrual pool = Gross Eligible Accrual - Total Scheduled Transferred - Total Direct Accrual Deductions.
        """
        if not employee:
            return {'accrued': 0.0, 'scheduled': 0.0}

        gross_accrual = self._calculate_eligible_leave(employee, as_of_date=as_of_date)

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

        # 1. Total Scheduled Leave Days Booked (Validated / Approved Only)
        total_scheduled_booked = 0.0
        if scheduled_type_ids:
            sched_domain = [
                ('employee_id', '=', employee.id),
                ('state', 'in', ['validate', 'validate1']),
                ('holiday_status_id', 'in', scheduled_type_ids),
                ('custom_saved', '=', True),
            ]
            if current_rec_id:
                sched_domain.append(('id', '!=', current_rec_id))
            if as_of_date:
                sched_domain.append(('leave_start_date', '<=', as_of_date))

            sched_leaves = self.env['hr.leave'].sudo().search(sched_domain)
            total_scheduled_booked = sum(lv.number_of_days for lv in sched_leaves)

        # 2. Chronological Waterfall Deduction by Actual Leaves (Validated / Approved Only)
        actual_domain = [
            ('employee_id', '=', employee.id),
            ('state', 'in', ['validate', 'validate1']),
            ('holiday_status_id', 'in', accrual_type_ids),
            ('custom_saved', '=', True),
        ]
        if current_rec_id:
            actual_domain.append(('id', '!=', current_rec_id))
        if as_of_date:
            actual_domain.append(('leave_start_date', '<=', as_of_date))

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

    @api.model
    def get_dashboard_balances(self, employee_id=None):
        """Public RPC endpoint to fetch accrued and scheduled leave balances,
        daily accrual rate, maximum carryover cap, and live accrual status for the dashboard."""
        employee = None
        if employee_id:
            try:
                employee = self.env['hr.employee'].browse(int(employee_id)).exists()
            except Exception:
                employee = None

        if not employee:
            employee = self._get_current_employee()

        if not employee:
            employee = self.env.user.employee_id or self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.env.user.id)], limit=1
            )

        if not employee:
            return {
                'accrued': 0.0,
                'scheduled': 0.0,
                'daily_rate': 0.0,
                'annual_entitlement': 0.0,
                'max_cap': 0.0,
                'remaining_to_cap': 0.0,
                'cap_percentage': 0.0,
                'accrual_status': 'active',
                'accrual_status_label': 'Actively Accruing',
                'employee_category': '',
            }

        try:
            balances = self._get_leave_balances(employee)
            accrued = round(float(balances.get('accrued', 0.0)), 2)
            scheduled = round(float(balances.get('scheduled', 0.0)), 2)

            # Compute Accrual Metrics & Maximum Carryover Cap
            config = self._get_accrual_config()
            base_entitlement = config['base_entitlement']
            managerial_cap_years = config['managerial_cap_years']
            non_managerial_cap_years = config['non_managerial_cap_years']

            hire_date = self._get_employee_hire_date(employee)
            category = self._get_employee_category(employee)
            is_managerial = str(category).lower() == 'managerial'
            cap_years = managerial_cap_years if is_managerial else non_managerial_cap_years

            today = fields.Date.today()
            if hire_date:
                year_offset = relativedelta(today, hire_date).years
                annual_entitlement = base_entitlement + max(0, year_offset)
                # Anchor entitlement for max carryover cap
                anchor_entitlement = base_entitlement + max(0, year_offset - 1) if year_offset >= 1 else base_entitlement
            else:
                annual_entitlement = base_entitlement
                anchor_entitlement = base_entitlement

            max_cap = float(sum(max(0, anchor_entitlement - yr) for yr in range(cap_years)))
            daily_rate = round(float(annual_entitlement) / 365.0, 4) if annual_entitlement else 0.0438

            # Total Earned / Active Leave against the Maximum Carryover Cap
            total_earned = round(accrued + scheduled, 2)

            remaining_to_cap = max(0.0, round(max_cap - total_earned, 2)) if max_cap > 0 else 0.0
            cap_percentage = min(100.0, round((total_earned / max_cap) * 100.0, 1)) if max_cap > 0 else 0.0

            # Determine Accrual Status based on total_earned
            if max_cap > 0 and total_earned >= max_cap:
                accrual_status = 'capped'
                accrual_status_label = 'Accrual Paused (Max Cap Reached)'
            elif max_cap > 0 and total_earned >= (max_cap * 0.85):
                accrual_status = 'near_cap'
                accrual_status_label = f'Approaching Cap ({remaining_to_cap}d left)'
            else:
                accrual_status = 'active'
                accrual_status_label = 'Actively Accruing'

            _logger.info(
                "HrLeave.get_dashboard_balances: Employee %s (#%s) -> Accrued: %s, Sched: %s, Total: %s, MaxCap: %s, DailyRate: %s, Status: %s",
                employee.name, employee.id, accrued, scheduled, total_earned, max_cap, daily_rate, accrual_status
            )
            return {
                'accrued': accrued,
                'scheduled': scheduled,
                'total_earned': total_earned,
                'daily_rate': daily_rate,
                'annual_entitlement': annual_entitlement,
                'max_cap': max_cap,
                'remaining_to_cap': remaining_to_cap,
                'cap_percentage': cap_percentage,
                'accrual_status': accrual_status,
                'accrual_status_label': accrual_status_label,
                'employee_category': category or ('Managerial' if is_managerial else 'Non Managerial'),
                'employee_id': employee.id,
                'employee_name': employee.name,
            }
        except Exception as e:
            _logger.exception("Error computing leave balances in get_dashboard_balances: %s", e)
            return {
                'accrued': 0.0,
                'scheduled': 0.0,
                'daily_rate': 0.0,
                'annual_entitlement': 0.0,
                'max_cap': 0.0,
                'remaining_to_cap': 0.0,
                'cap_percentage': 0.0,
                'accrual_status': 'active',
                'accrual_status_label': 'Actively Accruing',
                'employee_category': '',
            }

    @api.model
    def _cron_cleanup_abandoned_leave_requests(self):
        """Clean up uncompleted/abandoned leave drafts older than 24 hours."""
        threshold = fields.Datetime.now() - timedelta(hours=24)
        abandoned_leaves = self.sudo().search([
            ('state', '=', 'draft'),
            ('custom_saved', '=', False),
            ('create_date', '<', threshold),
        ])
        if abandoned_leaves:
            _logger.info("Cleaning up %d abandoned leave requests", len(abandoned_leaves))
            abandoned_leaves.unlink()

    @api.model
    def _cron_remind_pending_leave_approvals(self):
        """Remind approvers for pending leave requests that are waiting for more than 3 days."""
        threshold = fields.Datetime.now() - timedelta(days=3)
        pending_leaves = self.sudo().search([
            ('state', '=', 'confirm'),
            ('leave_request_status', '=', 'notify'),
            ('write_date', '<', threshold),
        ])
        for leave in pending_leaves:
            try:
                approver = leave._get_leave_approver()
                if approver and approver.user_id:
                    activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
                    if activity_type:
                        existing = leave.activity_ids.filtered(lambda a: a.activity_type_id == activity_type and a.user_id == approver.user_id)
                        if not existing:
                            leave.sudo().activity_schedule(
                                'mail.mail_activity_data_todo',
                                summary=_('Pending Leave Approval Reminder: %s') % (leave.employee_id.name or ''),
                                user_id=approver.user_id.id,
                            )
            except Exception as e:
                _logger.warning("Failed to send pending reminder for leave %s: %s", leave.id, e)



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

    # ── Date-only proxy fields for the UI ────────────────────────────────────
    date_from_date = fields.Date(
        string='Start Date',
        compute='_compute_date_proxy',
        inverse='_inverse_date_from_date',
        store=False,
    )
    date_to_date = fields.Date(
        string='End Date',
        compute='_compute_date_proxy',
        inverse='_inverse_date_to_date',
        store=False,
    )

    @api.depends('date_from', 'date_to')
    def _compute_date_proxy(self):
        for rec in self:
            rec.date_from_date = rec.date_from.date() if rec.date_from else False
            rec.date_to_date = rec.date_to.date() if rec.date_to else False

    def _inverse_date_from_date(self):
        from datetime import datetime, time
        for rec in self:
            if rec.date_from_date:
                rec.date_from = datetime.combine(rec.date_from_date, time.min)

    def _inverse_date_to_date(self):
        from datetime import datetime, time
        for rec in self:
            if rec.date_to_date:
                rec.date_to = datetime.combine(rec.date_to_date, time.max).replace(microsecond=0)

    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('day_of_week')
    def _onchange_day_of_week(self):
        if self.day_of_week and not self.name:
            day_names = {'0': 'Monday', '1': 'Tuesday', '2': 'Wednesday', '3': 'Thursday', '4': 'Friday',
                         '5': 'Saturday', '6': 'Sunday'}
            self.name = day_names.get(self.day_of_week, '')

    @staticmethod
    def _normalize_date_range(vals):
        """Normalize date_from to midnight and date_to to end-of-day for public holidays."""
        from datetime import datetime, time
        if vals.get('date_from'):
            dt_from = fields.Datetime.to_datetime(vals['date_from'])
            if dt_from:
                vals['date_from'] = datetime.combine(dt_from.date(), time.min)
        if vals.get('date_to'):
            dt_to = fields.Datetime.to_datetime(vals['date_to'])
            if dt_to:
                vals['date_to'] = datetime.combine(dt_to.date(), time.max).replace(microsecond=0)
        elif vals.get('date_from'):
            # If date_to not supplied, default to end of same day as date_from
            dt_from = fields.Datetime.to_datetime(vals['date_from'])
            if dt_from:
                vals['date_to'] = datetime.combine(dt_from.date(), time.max).replace(microsecond=0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('day_of_week'):
                # Recurring weekday holiday: assign fixed spanning range
                if not vals.get('date_from'):
                    vals['date_from'] = fields.Datetime.to_datetime('2000-01-01 00:00:00')
                if not vals.get('date_to'):
                    vals['date_to'] = fields.Datetime.to_datetime('2099-12-31 23:59:59')
            else:
                # Regular public holiday: normalize to full calendar day
                self._normalize_date_range(vals)
        # Use context flag so that _reevaluate_leaves does NOT trigger
        # _check_scheduled_leave_overlap when it processes affected hr.leave records.
        # NOTE: We must pass self.with_context(...) as the instance argument to super()
        # explicitly — calling super().with_context(...).create() returns a new recordset
        # of the same class and causes infinite recursion through the MRO.
        return super(ResourceCalendarLeavesCustom, self.with_context(skip_leave_overlap_check=True)).create(vals_list)

    def write(self, vals):
        # Determine effective day_of_week for each record
        for rec in self:
            effective_dow = vals.get('day_of_week', rec.day_of_week)
            if effective_dow:
                # Recurring weekday holiday
                if not rec.date_from and not vals.get('date_from'):
                    vals.setdefault('date_from', fields.Datetime.to_datetime('2000-01-01 00:00:00'))
                if not rec.date_to and not vals.get('date_to'):
                    vals.setdefault('date_to', fields.Datetime.to_datetime('2099-12-31 23:59:59'))
                break  # same vals dict applied to all, so update once and stop
        else:
            # No record has day_of_week set → regular public holiday: normalize dates
            self._normalize_date_range(vals)
        # Use context flag so that _reevaluate_leaves does NOT fire our
        # _check_scheduled_leave_overlap when it adjusts affected hr.leave states.
        # NOTE: Must pass self.with_context(...) explicitly to super() to avoid
        # infinite recursion — super().with_context(...).write() re-enters this class.
        return super(ResourceCalendarLeavesCustom, self.with_context(skip_leave_overlap_check=True)).write(vals)

    @api.constrains('date_from', 'date_to', 'calendar_id')
    def _check_compare_dates(self):
        """
        Override Odoo's overlap check to skip recurring weekday holidays.
        day_of_week records use a synthetic 2000–2099 date range and must NOT
        be compared against one-off dated public holidays.
        """
        # Only run the overlap check for dated (non-recurring) public holidays
        dated_records = self.filtered(lambda h: not h.day_of_week)
        if dated_records:
            return super(ResourceCalendarLeavesCustom, dated_records)._check_compare_dates()
        return True

    def _check_overlapping_public_holidays(self):
        dated_holidays = self.filtered(lambda h: not h.day_of_week)
        if dated_holidays:
            return super(ResourceCalendarLeavesCustom, dated_holidays)._check_overlapping_public_holidays()
        return True

    def _reevaluate_leaves(self, time_domain_dict):
        """
        Custom re-evaluation: completely replaces the standard Odoo
        ``_reevaluate_leaves`` to avoid triggering hr.leave validations.

        Only leaves whose leave type requires accrual check, has 'Ignore Public
        Holidays' enabled, or is Annual/Vacation leave are re-evaluated.
        The computed days and employee accrual balances are recalculated
        and updated cleanly with all validations suppressed.
        """
        if not time_domain_dict:
            return 0

        from datetime import date as _date, timedelta as _timedelta, datetime as _datetime, time as _time

        def _to_date(val):
            if not val:
                return None
            if isinstance(val, _datetime):
                return val.date()
            if isinstance(val, _date):
                return val
            if isinstance(val, str):
                try:
                    return _date.fromisoformat(val[:10])
                except Exception:
                    dt = fields.Datetime.to_datetime(val)
                    return dt.date() if dt else None
            return None

        # Derive the overall date span from time_domain_dict safely
        try:
            td_dates_from = [_to_date(d.get('date_from')) for d in time_domain_dict if d.get('date_from')]
            td_dates_from = [d for d in td_dates_from if d]
            td_dates_to = [_to_date(d.get('date_to')) for d in time_domain_dict if d.get('date_to')]
            td_dates_to = [d for d in td_dates_to if d]

            # Fallback to self records if time_domain_dict didn't yield dates
            if not td_dates_from or not td_dates_to:
                dated_self = self.filtered(lambda h: not h.day_of_week and (h.date_from or h.date_from_date))
                if dated_self:
                    td_dates_from = [_to_date(h.date_from_date or h.date_from) for h in dated_self]
                    td_dates_to = [_to_date(h.date_to_date or h.date_to) for h in dated_self]
                    td_dates_from = [d for d in td_dates_from if d]
                    td_dates_to = [d for d in td_dates_to if d]

            if not td_dates_from or not td_dates_to:
                return 0

            ph_min_date = min(td_dates_from)
            ph_max_date = max(td_dates_to)
        except Exception as e:
            _logger.warning("_reevaluate_leaves: could not compute PH date range: %s", e)
            return 0

        # Skip if this is a recurring weekday-only batch (synthetic 2000-2099 span)
        if (ph_max_date - ph_min_date).days > 366 * 10:
            return 0

        # Find target leave types:
        # 1. 'Requires Accrual Check' enabled
        # 2. 'Ignore Public Holidays' (include_public_holidays_in_duration) enabled
        # 3. Annual Leave / Vacation
        target_leave_types = self.env['hr.leave.type'].sudo().search([
            '|', '|', '|',
            ('check_accrual_balance', '=', True),
            ('include_public_holidays_in_duration', '=', True),
            ('name', '=ilike', '%annual%'),
            ('name', '=ilike', '%vacation%'),
        ])
        if not target_leave_types:
            _logger.info("_reevaluate_leaves: no target leave types found — skipping")
            return 0

        # Search affected hr.leave records overlapping the public holiday range
        base_domain = [
            ('holiday_status_id', 'in', target_leave_types.ids),
            ('state', 'not in', ['refuse', 'cancel']),
        ]

        # 1. Primary search: custom Date fields
        leaves = self.env['hr.leave'].sudo().search(
            base_domain + [
                ('leave_start_date', '<=', ph_max_date),
                ('leave_end_date', '>=', ph_min_date),
            ]
        )

        # 2. Fallback search: standard Datetime fields (date_from / date_to)
        if not leaves:
            ph_min_dt = fields.Datetime.to_string(_datetime.combine(ph_min_date, _time.min))
            ph_max_dt = fields.Datetime.to_string(_datetime.combine(ph_max_date, _time.max))
            leaves = self.env['hr.leave'].sudo().search(
                base_domain + [
                    ('date_from', '<=', ph_max_dt),
                    ('date_to', '>=', ph_min_dt),
                ]
            )

        if not leaves:
            _logger.info(
                "_reevaluate_leaves: no overlapping leaves found for PH range %s – %s",
                ph_min_date, ph_max_date,
            )
            return 0

        # Pre-build lookup of ALL active public holidays for day-by-day fallback
        all_dated_ph = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
        ]).filtered(lambda h: not getattr(h, 'day_of_week', False) and (h.date_from or h.date_from_date))

        ph_day_weights = {}
        for ph in all_dated_ph:
            ph_start = _to_date(ph.date_from_date or ph.date_from)
            ph_end = _to_date(ph.date_to_date or ph.date_to)
            if not ph_start or not ph_end or (ph_end - ph_start).days > 366:
                continue
            ph_weight = getattr(ph, 'holiday_day_weight', 1.0) or 1.0
            subtract = min(1.0, max(0.0, ph_weight))
            wut = getattr(ph, 'work_unit_type', False) or False
            curr = ph_start
            while curr <= ph_end:
                ph_day_weights.setdefault(curr, {})[wut] = max(
                    ph_day_weights.get(curr, {}).get(wut, 0.0),
                    subtract,
                )
                curr += _timedelta(days=1)

        ctx = {
            'skip_leave_overlap_check': True,
            'leave_skip_date_check': True,
            'leave_skip_state_check': True,
            'tracking_disable': True,
            'mail_notrack': True,
        }

        adjusted_count = 0
        for leave in leaves:
            try:
                start = leave.leave_start_date or (leave.date_from.date() if leave.date_from else False)
                end = leave.leave_end_date or (leave.date_to.date() if leave.date_to else False)
                if not start or not end or end < start:
                    continue

                # Recompute days using standard preview method first
                new_days = leave._compute_days_preview()

                # Fallback to day-by-day calculation if preview gave 0 on valid range
                if (not new_days or new_days <= 0) and start and end and end >= start:
                    emp = leave.employee_id.sudo() if leave.employee_id else False
                    emp_wut = False
                    if emp:
                        try:
                            emp_wut = leave._get_employee_work_unit_type(emp)
                        except Exception:
                            emp_wut = False

                    total_days = 0.0
                    curr = start
                    while curr <= end:
                        weekday = curr.weekday()
                        if weekday == 6:  # Sunday
                            curr += _timedelta(days=1)
                            continue
                        base_w = 0.5 if (weekday == 5 and emp_wut == 'head_office') else 1.0
                        ph_info = ph_day_weights.get(curr, {})
                        if ph_info:
                            sub = ph_info.get(emp_wut, ph_info.get(False, 0.0))
                            if not emp_wut:
                                sub = max(ph_info.values())
                            day_w = max(0.0, base_w - sub)
                        else:
                            day_w = base_w
                        total_days += day_w
                        curr += _timedelta(days=1)

                    if leave.half_day and start == end:
                        total_days = 0.5
                    else:
                        if leave.starting_half_day and total_days >= 0.5:
                            total_days -= 0.5
                        if leave.ending_half_day and total_days >= 0.5:
                            total_days -= 0.5
                    new_days = max(0.0, float_round(total_days, precision_digits=2))

                old_days = leave.computed_leave or leave.number_of_days or 0.0

                # Write if changed
                if abs(new_days - old_days) > 0.001:
                    leave.sudo().with_context(**ctx).write({
                        'computed_leave': new_days,
                        'number_of_days': new_days,
                    })

                    # Refresh employee accrual / scheduled balances on this leave
                    try:
                        balances = leave._get_leave_balances(leave.employee_id)
                        leave.sudo().with_context(**ctx).write({
                            'accrued_leave_balance': balances.get('accrued', 0.0),
                            'scheduled_leave_balance': balances.get('scheduled', 0.0),
                        })
                    except Exception as eb:
                        _logger.warning("Could not refresh balances for leave %s: %s", leave.id, eb)

                    # Re-sync resource leave interval for approved requests
                    if leave.state in ('validate', 'validate1') or leave.leave_request_status == 'approved':
                        try:
                            leave.sudo()._remove_resource_leave()
                            leave.sudo()._create_resource_leave()
                        except Exception as el:
                            _logger.warning("Could not sync resource leave for leave %s: %s", leave.id, el)

                    # Post update note in chatter
                    try:
                        leave.sudo().message_post(
                            body=Markup(_(
                                "<b>Public Holiday Adjustment:</b> Leave duration was re-evaluated from "
                                "<b>%s</b> to <b>%s</b> day(s)."
                            )) % (old_days, new_days),
                            subtype_xmlid='mail.mt_note',
                        )
                    except Exception as em:
                        _logger.warning("Could not post chatter note for leave %s: %s", leave.id, em)

                    _logger.info(
                        "Re-evaluated leave %s (%s): %s → %s days (PH adjustment)",
                        leave.id,
                        leave.holiday_status_id.name,
                        old_days,
                        new_days,
                    )
                    adjusted_count += 1
            except Exception as e:
                _logger.warning(
                    "Failed to re-evaluate leave %s after public holiday change: %s",
                    leave.id, e,
                )

        return adjusted_count

    # Note: unlink is intentionally NOT overridden here.
    # The standard resource.calendar.leaves.unlink() already calls
    # self._reevaluate_leaves(time_domain_dict) after super().unlink(),
    # and Python MRO ensures that call resolves to our custom override above.

    def action_manual_reevaluate_leaves(self):
        """
        Manual re-evaluation action for selected public holiday record(s).
        Can be triggered from list view (Actions menu or button) or form view.
        """
        dated = self.filtered(lambda h: not h.day_of_week and (h.date_from or h.date_from_date))
        if not dated:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nothing to Re-evaluate'),
                    'message': _('Only dated (non-recurring) public holidays can trigger leave re-evaluation.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        time_domain_dict = []
        for rec in dated:
            time_domain_dict.append({
                'company_id': rec.company_id.id if rec.company_id else False,
                'date_from': rec.date_from or rec.date_from_date,
                'date_to': rec.date_to or rec.date_to_date,
            })

        count = self._reevaluate_leaves(time_domain_dict)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Re-evaluation Complete'),
                'message': _(
                    'Re-evaluation completed! %s overlapping leave request(s) were adjusted.'
                ) % count,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reevaluate_all_leaves(self):
        """
        Global re-evaluation action: re-evaluates ALL leave requests against
        all active dated public holidays in the system.
        """
        dated_phs = self.env['resource.calendar.leaves'].sudo().search([
            ('resource_id', '=', False),
        ]).filtered(lambda h: not getattr(h, 'day_of_week', False) and (h.date_from or h.date_from_date))

        if not dated_phs:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Public Holidays Found'),
                    'message': _('There are no dated public holidays to re-evaluate leaves against.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        time_domain_dict = []
        for ph in dated_phs:
            time_domain_dict.append({
                'company_id': ph.company_id.id if ph.company_id else False,
                'date_from': ph.date_from or ph.date_from_date,
                'date_to': ph.date_to or ph.date_to_date,
            })

        count = self._reevaluate_leaves(time_domain_dict)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Leaves Re-evaluation Complete'),
                'message': _(
                    'Global re-evaluation complete! %s leave request(s) were adjusted.'
                ) % count,
                'type': 'success',
                'sticky': False,
            },
        }


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