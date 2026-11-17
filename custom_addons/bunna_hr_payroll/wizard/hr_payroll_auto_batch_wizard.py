# -*- coding: utf-8 -*-

from math import ceil
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrPayrollAutoBatchWizard(models.TransientModel):
    """Wizard to automatically validate employee payroll eligibility,
    exclude non-eligible or on-hold employees with transparent reasons,
    and dynamically chunk eligible employees into manageable payslip batches.
    """
    _name = 'hr.payroll.auto.batch.wizard'
    _description = 'Auto-Generate Payroll Batches Wizard'

    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        required=True,
        domain="[('state', '=', 'open')]",
        help='Select an open payroll period for which to generate batches.'
    )
    date_from = fields.Date(string='Start Date', required=True)
    date_to = fields.Date(string='End Date', required=True)
    payment_date = fields.Date(string='Date of Payment', required=True)

    batch_size = fields.Integer(
        string='Batch Size (Employees / Batch)',
        default=300,
        required=True,
        help='Maximum number of employees per payslip batch (e.g. 300).'
    )
    batch_prefix = fields.Char(
        string='Batch Name Prefix',
        default='Payroll Batch',
        required=True,
        help='Prefix for naming the generated batches.'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # ── Configurable Eligibility & Exclusion Rules ─────────────────────────
    exclude_no_contract = fields.Boolean(
        string='Exclude Without Active Contract / Version',
        default=True,
        help='Skip employees who do not have an active employment version/contract covering this period.'
    )
    exclude_unpaid_leave = fields.Boolean(
        string='Exclude on Full Leave Without Pay (LWOP)',
        default=True,
        help='Skip employees who are on approved Leave Without Pay for the payroll period.'
    )
    exclude_unpaid_suspension = fields.Boolean(
        string='Exclude on Unpaid Suspension',
        default=True,
        help='Skip employees under active disciplinary suspension without pay.'
    )
    exclude_profile_flagged = fields.Boolean(
        string='Exclude Employees Flagged On Hold',
        default=True,
        help='Skip employees marked with "Hold / Exclude from Payroll" on their employee profile.'
    )
    exclude_new_hires = fields.Boolean(
        string='Exclude Mid-Period Hires (Hired after Period Start)',
        default=False,
        help='Skip employees whose employment/contract started after the period start date. If unchecked, newly hired employees are included to receive prorated pay.'
    )

    # ── Temporary Manual Exclusions for this run ───────────────────────────
    manual_excluded_employee_ids = fields.Many2many(
        'hr.employee',
        'auto_batch_manual_exclude_rel',
        'wizard_id',
        'employee_id',
        string='Additional Manual Exclusions',
        help='Pick any specific employees to exclude only for this payroll period.'
    )
    manual_exclude_reason = fields.Char(
        string='Manual Exclusion Reason',
        default='Excluded manually by Payroll Officer for this period'
    )

    # ── Wizard Lifecycle & Preview ─────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Setup & Filters'),
        ('preview', 'Eligibility Review'),
    ], default='draft', string='Step')

    total_active_employees = fields.Integer(string='Total Evaluated', readonly=True)
    eligible_count = fields.Integer(string='Eligible Employees', readonly=True)
    excluded_count = fields.Integer(string='Excluded Employees', readonly=True)
    estimated_batches = fields.Integer(string='Estimated Batches', readonly=True)

    eligible_line_ids = fields.One2many(
        'hr.payroll.auto.batch.eligible.line',
        'wizard_id',
        string='Eligible Employees'
    )
    excluded_line_ids = fields.One2many(
        'hr.payroll.auto.batch.excluded.line',
        'wizard_id',
        string='Excluded Employees & Reasons'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')

        period = False
        if active_model == 'hr.payroll.period' and active_id:
            period = self.env['hr.payroll.period'].browse(active_id)
            if period.state != 'open':
                period = False
        elif self.env.context.get('default_period_id'):
            period = self.env['hr.payroll.period'].browse(self.env.context.get('default_period_id'))
            if period.state != 'open':
                period = False
        else:
            period = self.env['hr.payroll.period'].search([('state', '=', 'open')], limit=1)

        if period:
            res['period_id'] = period.id
            res['date_from'] = period.date_from
            res['date_to'] = period.date_to
            res['payment_date'] = period.payment_date
            res['batch_prefix'] = f"{period.name} - Batch"

        return res

    @api.onchange('period_id')
    def _onchange_period_id(self):
        if self.period_id:
            self.date_from = self.period_id.date_from
            self.date_to = self.period_id.date_to
            self.payment_date = self.period_id.payment_date
            self.batch_prefix = f"{self.period_id.name} - Batch"

    def _get_bulk_eligibility_data(self):
        """Pre-fetches all exclusion and version records in bulk (5 queries total)
        instead of 16,000 queries for 4,000 employees.
        """
        # 1. Manual exclusions
        manual_ids = set(self.manual_excluded_employee_ids.ids)

        # 2. Permanent/Profile flagged
        flagged_map = {}
        if self.exclude_profile_flagged and hasattr(self.env['hr.employee'], 'exclude_from_payroll'):
            try:
                flagged_emps = self.env['hr.employee'].sudo().search([('exclude_from_payroll', '=', True)])
                for e in flagged_emps:
                    flagged_map[e.id] = getattr(e, 'payroll_exclude_reason', False) or _("Flagged On Hold on Employee Profile")
            except Exception:
                pass

        # 3. Disciplinary suspension
        suspended_ids = set()
        if self.exclude_unpaid_suspension and hasattr(self.env['hr.employee'], 'is_suspended'):
            try:
                suspended_ids = set(self.env['hr.employee'].sudo().search([
                    ('is_suspended', '=', True),
                    ('suspension_type', '=', 'without_pay')
                ]).ids)
            except Exception:
                pass

        # 4. Leave without pay (leave.request)
        lwop_map = {}
        if self.exclude_unpaid_leave and 'leave.request' in self.env:
            try:
                lwop_records = self.env['leave.request'].sudo().search([
                    ('leave_reason', '=', 'leave_without_pay'),
                    ('start_date', '<=', self.date_from),
                    ('end_date', '>=', self.date_to),
                ])
                for lr in lwop_records:
                    if lr.requester_name:
                        lwop_map[lr.requester_name.id] = _("On full Leave Without Pay (LWOP) from %s to %s") % (lr.start_date, lr.end_date)
            except Exception:
                pass

        # 5. Standard hr.leave unpaid
        hr_leave_ids = set()
        if self.exclude_unpaid_leave and 'hr.leave' in self.env:
            try:
                hr_leave_ids = set(self.env['hr.leave'].sudo().search([
                    ('state', '=', 'validate'),
                    ('holiday_status_id.unpaid', '=', True),
                    ('date_from', '<=', fields.Datetime.to_datetime(self.date_from)),
                    ('date_to', '>=', fields.Datetime.to_datetime(self.date_to)),
                ]).mapped('employee_id.id'))
            except Exception:
                pass

        # 6. Active versions covering period
        version_by_emp = {}
        if 'hr.version' in self.env:
            all_versions = self.env['hr.version'].sudo().search([
                ('contract_date_start', '<=', self.date_to),
                '|',
                ('contract_date_end', '=', False),
                ('contract_date_end', '>=', self.date_from)
            ])
            for v in all_versions:
                if v.employee_id and v.employee_id.id not in version_by_emp:
                    version_by_emp[v.employee_id.id] = v

        return {
            'manual_ids': manual_ids,
            'flagged_map': flagged_map,
            'suspended_ids': suspended_ids,
            'lwop_map': lwop_map,
            'hr_leave_ids': hr_leave_ids,
            'version_by_emp': version_by_emp,
        }

    def _check_employee_eligibility_fast(self, employee, bulk_data):
        """In-memory eligibility validation using pre-fetched sets (0 queries)."""
        if not employee.active:
            return False, _("Employee is Inactive / Archived")

        if employee.id in bulk_data['manual_ids']:
            return False, self.manual_exclude_reason or _("Manually excluded for this period")

        if employee.id in bulk_data['flagged_map']:
            return False, bulk_data['flagged_map'][employee.id]

        if employee.id in bulk_data['suspended_ids']:
            return False, _("Under active Disciplinary Suspension Without Pay")

        if employee.id in bulk_data['lwop_map']:
            return False, bulk_data['lwop_map'][employee.id]

        if employee.id in bulk_data['hr_leave_ids']:
            return False, _("On approved Unpaid Leave (LWOP) for the entire period")

        version = bulk_data['version_by_emp'].get(employee.id)
        if self.exclude_no_contract:
            if not version:
                return False, _("No Active Employment Version/Contract covering period (%s - %s)") % (
                    self.date_from, self.date_to
                )
            if not version.struct_id and not employee.struct_id:
                return False, _("Employment Version/Contract has no Salary Structure assigned")

        if self.exclude_new_hires and version:
            start_date = version.contract_date_start or getattr(version, 'date_start', False)
            if start_date and start_date > self.date_from:
                return False, _("Mid-Period New Hire: Joined on %s (after period start %s)") % (
                    start_date, self.date_from
                )

        return True, None

    def _check_employee_eligibility(self, employee):
        """Centralized eligibility engine (supports single employee evaluation)."""
        bulk_data = self._get_bulk_eligibility_data()
        return self._check_employee_eligibility_fast(employee, bulk_data)

    def action_compute_preview(self):
        """Analyzes all employees in high-speed bulk mode, classifies them as
        eligible or excluded, and displays the interactive preview.
        """
        self.ensure_one()
        if self.period_id.state == 'closed':
            raise UserError(_("Cannot generate batches for a closed payroll period ('%s'). Finalized periods are locked in viewing mode.") % self.period_id.name)
        if self.batch_size <= 0:
            raise ValidationError(_("Batch size must be greater than 0."))

        # Clear previous preview lines
        self.eligible_line_ids.unlink()
        self.excluded_line_ids.unlink()

        # Pre-fetch bulk eligibility data (5 queries total instead of 16,000)
        bulk_data = self._get_bulk_eligibility_data()

        # Fetch employees for this company using sudo
        all_employees = self.env['hr.employee'].sudo().with_context(active_test=False).search([
            '|',
            ('company_id', '=', self.company_id.id),
            ('company_id', '=', False)
        ])

        eligible_vals = []
        excluded_vals = []

        for emp in all_employees:
            is_eligible, reason = self._check_employee_eligibility_fast(emp, bulk_data)
            ou_name = False
            if hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
                ou_name = emp.default_operating_unit_id.name

            if is_eligible:
                version = bulk_data['version_by_emp'].get(emp.id)
                struct_name = version.struct_id.name if version and version.struct_id else (
                    emp.struct_id.name if emp.struct_id else ''
                )
                eligible_vals.append({
                    'wizard_id': self.id,
                    'employee_id': emp.id,
                    'operating_unit': ou_name or 'Head Office / Unassigned',
                    'version_id': version.id if version else False,
                    'structure_name': struct_name,
                })
            else:
                excluded_vals.append({
                    'wizard_id': self.id,
                    'employee_id': emp.id,
                    'operating_unit': ou_name or 'Head Office / Unassigned',
                    'reason': reason or _("Excluded"),
                })

        # Bulk insert preview lines in chunks of 1000 for fast ingestion
        if eligible_vals:
            for i in range(0, len(eligible_vals), 1000):
                self.env['hr.payroll.auto.batch.eligible.line'].create(eligible_vals[i:i + 1000])
        if excluded_vals:
            for i in range(0, len(excluded_vals), 1000):
                self.env['hr.payroll.auto.batch.excluded.line'].create(excluded_vals[i:i + 1000])

        eligible_total = len(eligible_vals)
        self.total_active_employees = len(all_employees)
        self.eligible_count = eligible_total
        self.excluded_count = len(excluded_vals)
        self.estimated_batches = ceil(eligible_total / self.batch_size) if eligible_total > 0 else 0
        self.state = 'preview'

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.auto.batch.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back_to_draft(self):
        """Allows user to go back and modify batch size or filter toggles."""
        self.ensure_one()
        if self.period_id.state == 'closed':
            raise UserError(_("Cannot generate batches for a closed payroll period ('%s'). Finalized periods are locked in viewing mode.") % self.period_id.name)
        self.state = 'draft'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.auto.batch.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate_batches(self):
        """Creates all hr.payslip.run batches and populates them with payslips in fast bulk chunks."""
        self.ensure_one()
        if self.period_id.state == 'closed':
            raise UserError(_("Cannot generate batches for a closed payroll period ('%s'). Finalized periods are locked in viewing mode.") % self.period_id.name)

        # If preview not yet run, run it automatically
        if not self.eligible_line_ids:
            self.action_compute_preview()

        if not self.eligible_line_ids:
            raise UserError(_("There are no eligible employees to generate batches for!"))

        # Safety: Check if there are confirmed/closed runs for this period
        closed_runs = self.env['hr.payslip.run'].sudo().search([
            ('period_id', '=', self.period_id.id),
            ('state', '!=', 'draft')
        ])
        if closed_runs:
            raise UserError(_(
                "Cannot auto-generate batches: Period '%s' already has %d confirmed/closed batch(es). "
                "Confirmed batches cannot be overwritten."
            ) % (self.period_id.name, len(closed_runs)))

        # Clean up existing draft batches and payslips for this period before regenerating
        existing_draft_runs = self.env['hr.payslip.run'].sudo().search([
            ('period_id', '=', self.period_id.id),
            ('state', '=', 'draft')
        ])
        if existing_draft_runs:
            existing_draft_runs.mapped('slip_ids').unlink()
            existing_draft_runs.unlink()

        # Sort eligible employees by Operating Unit and ID for cohesive grouping
        eligible_employees = self.eligible_line_ids.mapped('employee_id')
        bulk_data = self._get_bulk_eligibility_data()
        period_name = self.period_id.name or 'Payroll'

        # Number of standard days in this period
        start_d = fields.Date.from_string(self.date_from)
        end_d = fields.Date.from_string(self.date_to)
        period_days = (end_d - start_d).days + 1 if (start_d and end_d) else 30

        batch_size = self.batch_size
        batches = [eligible_employees[i:i + batch_size] for i in range(0, len(eligible_employees), batch_size)]

        created_runs = self.env['hr.payslip.run'].sudo()

        for idx, chunk in enumerate(batches, start=1):
            batch_name = f"{self.batch_prefix} {idx:02d} ({len(chunk)} Emps)"
            run = self.env['hr.payslip.run'].sudo().create({
                'name': batch_name,
                'period_id': self.period_id.id,
                'date_start': self.date_from,
                'date_end': self.date_to,
                'payment_date': self.payment_date,
            })
            created_runs += run

            # Bulk prepare payslip dicts for this chunk
            chunk_slip_vals = []
            for employee in chunk:
                version = bulk_data['version_by_emp'].get(employee.id)
                struct_id = version.struct_id.id if version and version.struct_id else (
                    employee.struct_id.id if employee.struct_id else False
                )
                slip_name = _('Salary Slip of %s for %s') % (employee.name, period_name)

                # Fast standard attendance line (30 days / full period)
                worked_days_data = [{
                    'name': _("Normal Working Days paid at 100%"),
                    'sequence': 1,
                    'code': 'WORK100',
                    'number_of_days': period_days,
                    'number_of_hours': period_days * 8,
                    'version_id': version.id if version else False,
                }]

                chunk_slip_vals.append({
                    'employee_id': employee.id,
                    'name': slip_name,
                    'struct_id': struct_id,
                    'version_id': version.id if version else False,
                    'payslip_run_id': run.id,
                    'period_id': self.period_id.id,
                    'payment_date': self.payment_date,
                    'worked_days_line_ids': [(0, 0, x) for x in worked_days_data],
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                    'company_id': employee.company_id.id,
                })

            # Bulk multi-create all payslips for this chunk in ONE single SQL multi-insert
            payslips = self.env['hr.payslip'].sudo().create(chunk_slip_vals)

            # Compute payslip sheets for this batch chunk
            payslips.sudo().compute_sheet()

            # Commit after each batch: keeps memory low, saves transaction logs & avoids 504 gateway timeouts
            self.env.cr.commit()
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_hr_payslip_run_tree')
        action['context'] = {'search_default_group_period': 1}
        action['domain'] = []
        action['name'] = _("Payslips Batches")
        return action


class HrPayrollAutoBatchEligibleLine(models.TransientModel):
    _name = 'hr.payroll.auto.batch.eligible.line'
    _description = 'Eligible Employee for Auto-Batch'
    _order = 'operating_unit, employee_id'

    wizard_id = fields.Many2one('hr.payroll.auto.batch.wizard', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    operating_unit = fields.Char(string='Operating Unit / Branch')
    version_id = fields.Many2one('hr.version', string='Active Contract / Version')
    structure_name = fields.Char(string='Salary Structure')

    def action_exclude(self):
        """Allows one-click manual exclusion of this employee from the wizard."""
        wizard = self.wizard_id
        wizard.manual_excluded_employee_ids = [(4, self.employee_id.id)]
        return wizard.action_compute_preview()


class HrPayrollAutoBatchExcludedLine(models.TransientModel):
    _name = 'hr.payroll.auto.batch.excluded.line'
    _description = 'Excluded Employee from Auto-Batch'
    _order = 'reason, employee_id'

    wizard_id = fields.Many2one('hr.payroll.auto.batch.wizard', ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    operating_unit = fields.Char(string='Operating Unit / Branch')
    reason = fields.Char(string='Reason for Exclusion', required=True)

    def action_include(self):
        """Allows re-including an employee if they were manually excluded."""
        wizard = self.wizard_id
        if self.employee_id in wizard.manual_excluded_employee_ids:
            wizard.manual_excluded_employee_ids = [(3, self.employee_id.id)]
        return wizard.action_compute_preview()
