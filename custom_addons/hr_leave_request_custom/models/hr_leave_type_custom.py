# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrLeaveTypeCustom(models.Model):
    _inherit = 'hr.leave.type'

    check_accrual_balance = fields.Boolean(
        string='Requires Accrual Check',
        default=False,
        help="If enabled, this leave type consumes from Scheduled Leave Balance first, then Accrued Leave Balance."
    )
    is_scheduled_leave = fields.Boolean(
        string='Is Scheduled Leave',
        default=False,
        help="If enabled, booking this leave reserves days from Accrual into the Scheduled Leave Balance for future use."
    )
    is_lwp = fields.Boolean(
        string='Is Leave Without Pay (LWP)',
        default=False,
        help="If enabled, time off of this type halts accrual during the leave period."
    )
    is_exact_days = fields.Boolean(
        string='Exact Days Required',
        default=False,
        help="If enabled, leave requests of this type will enforce and display this exact number of days as read-only."
    )
    exact_days = fields.Float(
        string='Exact Days',
        default=0.0,
        help="If set greater than 0, the requested leave duration must be exactly this number of days."
    )
    requires_allocation = fields.Boolean(
        default=False,
        required=True,
        string='Requires allocation',
        help="If disabled (default), employees can request this leave type without needing prior leave allocations."
    )
    max_allowed_days = fields.Float(
        string='Max Allowed Days',
        default=0.0,
        help="If set greater than 0, the requested leave duration cannot exceed this number of days."
    )
    gender_rule = fields.Selection([
        ('all', 'All Employees (Male & Female)'),
        ('female', 'Female Only (F)'),
        ('male', 'Male Only (M)'),
    ], string='Gender Restriction', default='all', required=True,
       help="Restricts this leave type to specific employee gender (e.g. Maternity for Female, Paternity for Male).")
    allowed_group = fields.Selection([
        ('all', 'All (Employee, Manager, HR, Admin)'),
        ('manager', 'Manager, HR & Admin Only'),
        ('hr', 'HR & Admin Only'),
        ('admin', 'Administrator Only'),
    ], string='Allowed User Role', default='all', required=True,
       help="Restricts which user roles can view and request this leave type.")
    hr_only = fields.Boolean(
        string='HR / Admin Only',
        compute='_compute_hr_only',
        inverse='_inverse_hr_only',
        store=True,
        help="Maintained for compatibility; synced with Allowed User Role = HR & Admin Only."
    )

    @api.depends('allowed_group')
    def _compute_hr_only(self):
        for record in self:
            record.hr_only = (record.allowed_group in ('hr', 'admin'))

    def _inverse_hr_only(self):
        for record in self:
            if record.hr_only and record.allowed_group not in ('hr', 'admin'):
                record.allowed_group = 'hr'
            elif not record.hr_only and record.allowed_group in ('hr', 'admin'):
                record.allowed_group = 'all'

    @api.onchange('is_exact_days')
    def _onchange_is_exact_days(self):
        if not self.is_exact_days:
            self.exact_days = 0.0

    @api.onchange('exact_days')
    def _onchange_exact_days(self):
        if self.exact_days > 0:
            self.is_exact_days = True

    @api.constrains('is_exact_days', 'exact_days')
    def _check_exact_days(self):
        for record in self:
            if record.is_exact_days and record.exact_days <= 0:
                raise ValidationError(_("Please specify an Exact Days value greater than 0 when 'Exact Days Required' is enabled."))

    @api.constrains('include_public_holidays_in_duration')
    def _check_overlapping_public_holidays(self):
        # Override to prevent false validation errors caused by recurring blanket-dated public holidays
        return True

    @api.model
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
        is_manager = is_hr or is_admin or (
            user.has_group('hr_leave_request_custom.group_hr_holidays_manager_approver') or
            user.has_group('hr_holidays.group_hr_holidays_responsible') or
            bool(emp and emp.child_ids)
        )
        return {
            'is_admin': is_admin,
            'is_hr': is_hr,
            'is_manager': is_manager,
            'is_employee': True,
        }

    @api.model
    def get_allocation_data_request(self, target_date=None, hidden_allocations=True):
        res = super().get_allocation_data_request(target_date=target_date, hidden_allocations=hidden_allocations)
        employee = self.env['hr.employee']._get_contextual_employee()
        if not employee:
            employee = self.env['hr.leave']._get_current_employee()
        if not employee:
            return res

        gender = employee.gender
        roles = self._get_user_leave_roles()
        is_admin = roles['is_admin']
        is_hr = roles['is_hr']
        is_manager = roles['is_manager']

        filtered_res = []
        for item in res:
            lt_id = item[3] if len(item) > 3 else False
            if lt_id:
                lt = self.browse(lt_id)
                # Gender check
                if lt.gender_rule == 'female' and gender != 'female':
                    continue
                if lt.gender_rule == 'male' and gender != 'male':
                    continue

                # Role / Group check
                grp = getattr(lt, 'allowed_group', 'all') or 'all'
                if grp == 'admin' and not is_admin:
                    continue
                if grp == 'hr' and not is_hr:
                    continue
                if grp == 'manager' and not is_manager:
                    continue
                if getattr(lt, 'hr_only', False) and not is_hr:
                    continue
                if bool(lt.name and 'suspense leave' in lt.name.lower()) and not is_hr:
                    continue

            filtered_res.append(item)
        return filtered_res

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=None, order=None):
        domain = list(domain or [])
        if name:
            domain = ['|', ('name', operator, name), ('display_name', operator, name)] + domain
        return self._search(domain, limit=limit, order=order)