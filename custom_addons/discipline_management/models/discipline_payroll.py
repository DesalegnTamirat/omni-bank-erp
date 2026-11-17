# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplinePayrollPenalty(models.Model):
    _name = 'discipline.payroll.penalty'
    _description = 'Disciplinary Payroll Salary Penalty Deduction'
    _inherit = ['mail.thread']
    _order = 'effective_date desc, id desc'

    name = fields.Char(
        string='Penalty Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=False, ondelete='cascade', tracking=True)
    attendance_case_id = fields.Many2one('discipline.attendance.case', string='Attendance Case', required=False, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)

    transaction_type = fields.Selection([
        ('deduction', 'Salary Deduction'),
        ('refund', 'Appeal Reimbursement / Refund'),
    ], string='Transaction Type', required=True, default='deduction', tracking=True,
        help='Salary Deduction: deducts penalty from employee salary. Appeal Reimbursement / Refund: reimburses decreased or overturned penalty amount in the next payroll period.')

    parent_penalty_id = fields.Many2one(
        'discipline.payroll.penalty',
        string='Original Deducted Penalty',
        ondelete='set null',
        tracking=True,
        help='References the original payroll penalty record that was already deducted/transferred prior to appeal reduction.'
    )
    appeal_id = fields.Many2one(
        'discipline.appeal',
        string='Originating Appeal',
        ondelete='set null',
        tracking=True,
        help='The appeal decision that triggered this reimbursement.'
    )
    refund_amount = fields.Float(
        string='Reimbursement Amount (ETB)',
        tracking=True,
        help='Exact amount to be reimbursed to the employee in the next payroll period.'
    )

    # Penalty can be a percentage OR a day-count (for suspension without pay)
    penalty_type = fields.Selection([
        ('percentage', 'Salary Percentage Deduction'),
        ('suspension_without_pay', 'Suspension Without Pay (Daily Rate)'),
        ('managerial', 'Managerial Day-Count Deduction'),
        ('reimbursement', 'Appeal Penalty Reimbursement'),
    ], string='Penalty Calculation Type', required=True, default='percentage', tracking=True,
        help='Percentage deduction for warning penalties. Daily deduction for suspension without pay. Managerial: deducts based on working day count.')

    penalty_percentage = fields.Float(string='Penalty Deduction (%)', tracking=True)

    # For daily-rate based deductions
    suspension_id = fields.Many2one('discipline.suspension', string='Linked Suspension', tracking=True,
                                    help='Link to the suspension record to auto-fill days.')
    suspension_days = fields.Integer(string='Suspension Days Without Pay', tracking=True)
    managerial_days = fields.Integer(string='Managerial Deduction Days', tracking=True,
                                    help='Days authorised by management for penalty.')

    # Calculated amounts
    calculated_amount = fields.Float(
        string='Calculated Gross Amount (ETB)',
        compute='_compute_calculated_amount',
        store=True,
        tracking=True
    )
    daily_rate = fields.Float(
        string='Daily Rate (ETB)',
        compute='_compute_daily_rate',
        store=True,
        help='Basic wage / 30 working days per policy.'
    )

    effective_date = fields.Date(string='Effective Penalty Date', required=True, default=fields.Date.context_today, tracking=True)
    payroll_month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
        ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
        ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string='Target Payroll Month', store=True, readonly=False, tracking=True)
    state = fields.Selection([
        ('pending', 'Pending Transmission'),
        ('transferred', 'Transmitted to Payroll'),
        ('deducted', 'Deducted in Payslip'),
        ('reimbursed', 'Reimbursed in Payslip'),
        ('cancelled', 'Cancelled on Appeal / Waived'),
    ], string='Status', default='pending', required=True, tracking=True)

    payslip_reference = fields.Char(string='Payslip Ref / ID', tracking=True)
    notes = fields.Text(string='Integration Notes')

    is_appeal_window_active = fields.Boolean(
        string='Appeal Window / Review Active',
        compute='_compute_is_appeal_window_active',
        help='Informational indicator showing whether the appeal window is open or an appeal is under review. Does not block payroll deduction.'
    )
    is_appeal_held = fields.Boolean(
        string='Appeal Hold Active',
        default=False,
        tracking=True,
        help='When True, this pending penalty is held from payroll batch processing because an active appeal is under review.'
    )

    @api.depends(
        'case_id.state',
        'case_id.appeal_deadline',
        'case_id.appeal_ids.state',
        'case_id.deduction_status',
        'case_id.is_appeal_window_open'
    )
    def _compute_is_appeal_window_active(self):
        today = fields.Date.context_today(self)
        for rec in self:
            case = rec.case_id
            if not case:
                rec.is_appeal_window_active = False
                continue
            active_appeals = case.appeal_ids.filtered(lambda a: a.state not in ('decided', 'revoked', 'closed', 'cancelled'))
            is_window_open = bool(
                case.is_appeal_window_open or
                (case.state == 'enforced' and case.appeal_deadline and today <= case.appeal_deadline and not case.appeal_ids) or
                case.deduction_status == 'appeal_pending'
            )
            rec.is_appeal_window_active = bool(active_appeals or is_window_open)

    def _get_employee_wage(self):
        """Helper: return current active contract basic wage, or 0."""
        self.ensure_one()
        emp = self.sudo().employee_id
        ContractModel = self.env.get('hr.contract') or self.env.get('hr.version')
        if ContractModel:
            contract = ContractModel.sudo().search([
                ('employee_id', '=', emp.id),
            ], limit=1)
            if contract:
                wage = getattr(contract, 'wage', 0.0) or getattr(contract, 'basic_salary', 0.0) or getattr(contract, 'salary', 0.0)
                if wage:
                    return float(wage)
        return getattr(emp, 'wage', 0.0) or getattr(emp, 'basic_salary', 0.0)

    @api.depends('employee_id', 'penalty_percentage', 'penalty_type', 'suspension_days', 'managerial_days')
    def _compute_daily_rate(self):
        for rec in self:
            if not rec.employee_id:
                rec.daily_rate = 0.0
                continue
            wage = rec._get_employee_wage()
            rec.daily_rate = wage / 30.0 if wage else 0.0

    @api.depends('employee_id', 'transaction_type', 'refund_amount', 'penalty_percentage',
                 'penalty_type', 'suspension_days', 'managerial_days', 'daily_rate', 'state')
    def _compute_calculated_amount(self):
        for rec in self:
            if not rec.employee_id:
                rec.calculated_amount = 0.0
                continue
            if rec.state == 'cancelled':
                # Preserve the historical gross calculated amount for audit visibility
                if rec.calculated_amount > 0:
                    continue
                rec.calculated_amount = 0.0
                continue
            if rec.transaction_type == 'refund' or rec.penalty_type == 'reimbursement':
                if rec.refund_amount > 0:
                    rec.calculated_amount = rec.refund_amount
                    continue
            wage = rec._get_employee_wage()
            if rec.penalty_type == 'percentage':
                rec.calculated_amount = (wage * rec.penalty_percentage) / 100.0
            elif rec.penalty_type == 'suspension_without_pay':
                rec.calculated_amount = (rec.suspension_days or 0) * rec.daily_rate
            elif rec.penalty_type == 'managerial':
                rec.calculated_amount = (rec.managerial_days or 0) * rec.daily_rate
            else:
                rec.calculated_amount = rec.refund_amount or 0.0

    @api.onchange('suspension_id')
    def _onchange_suspension_id(self):
        if self.suspension_id:
            self.suspension_days = self.suspension_id.working_days_count
            self.penalty_type = 'suspension_without_pay'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('discipline.payroll.penalty') or _('New')
            if not vals.get('payroll_month') and vals.get('case_id'):
                case = self.env['discipline.case'].browse(vals['case_id'])
                if case.payroll_month:
                    vals['payroll_month'] = case.payroll_month
                else:
                    eff_date = fields.Date.to_date(vals.get('effective_date')) if vals.get('effective_date') else fields.Date.context_today(self)
                    vals['payroll_month'] = str(eff_date.month)
            emp_id = vals.get('employee_id')
            tx_type = vals.get('transaction_type', 'deduction')
            if emp_id and tx_type == 'deduction':
                emp = self.env['hr.employee'].browse(emp_id)
                is_managerial = self.env['discipline.case']._is_employee_managerial(emp)
                if is_managerial and vals.get('penalty_type') in (False, 'percentage'):
                    case_id = vals.get('case_id')
                    if case_id:
                        case = self.env['discipline.case'].browse(case_id)
                        if case.severity_level != 'level_5':
                            vals['penalty_type'] = 'managerial'
                            prior_cases_count = self.env['discipline.case'].search_count([
                                ('employee_id', '=', emp.id),
                                ('offense_category_id', '=', case.offense_category_id.id if case.offense_category_id else False),
                                ('state', 'in', ['enforced', 'closed', 'appealed']),
                                ('id', '!=', case.id)
                            ])
                            vals['managerial_days'] = min(prior_cases_count + 1, 3)
        return super().create(vals_list)

    def action_transmit_to_payroll(self):
        """Transmit penalty deduction or appeal reimbursement to payroll immediately (no appeal window freeze)."""
        for rec in self:
            if rec.is_appeal_held:
                raise UserError(_('Cannot transmit penalty [%s] to payroll while an active appeal is under review.') % rec.name)
            if rec.calculated_amount <= 0:
                raise UserError(_('Calculated amount is zero. Verify contract wage and penalty/reimbursement settings.'))
            rec.write({'state': 'transferred'})
            if rec.case_id:
                emp_name = rec.sudo().employee_id.name if rec.sudo().employee_id else _('Employee')
                if rec.transaction_type == 'refund':
                    rec.case_id.sudo().write({'deduction_status': 'refund_scheduled'})
                    rec.case_id.message_post(
                        body=_('Payroll Reimbursement [%s] of ETB %.2f transmitted to Payroll for %s.') % (
                            rec.name, rec.calculated_amount, emp_name
                        )
                    )
                else:
                    rec.case_id.sudo().write({'deduction_status': 'scheduled'})
                    rec.case_id.message_post(
                        body=_('Penalty deduction [%s] of ETB %.2f (%s) transmitted to Payroll for %s.') % (
                            rec.penalty_type, rec.calculated_amount, rec.penalty_percentage,
                            emp_name
                        )
                    )
            if rec.attendance_case_id:
                emp_name = rec.sudo().employee_id.name if rec.sudo().employee_id else _('Employee')
                rec.attendance_case_id.sudo().write({'deduction_status': 'transferred'})
                rec.attendance_case_id.message_post(
                    body=_('Attendance penalty deduction [%s] of ETB %.2f transmitted to Payroll for %s.') % (
                        rec.penalty_type, rec.calculated_amount, emp_name
                    )
                )

    def action_mark_deducted(self, payslip_reference=None):
        for rec in self:
            if payslip_reference:
                rec.payslip_reference = payslip_reference
            if not rec.payslip_reference:
                raise UserError(_('Payslip Reference must be entered before marking as Deducted / Reimbursed.'))
            if rec.transaction_type == 'refund':
                rec.write({'state': 'reimbursed'})
                if rec.case_id:
                    rec.case_id.sudo().write({'deduction_status': 'refunded'})
                    rec.case_id.message_post(
                        body=_('Appeal Reimbursement %s of ETB %.2f completed in Payslip (%s).') % (
                            rec.name, rec.calculated_amount, rec.payslip_reference
                        )
                    )
            else:
                rec.write({'state': 'deducted'})
                if rec.case_id:
                    rec.case_id.sudo().write({'deduction_status': 'deducted'})
                    rec.case_id.message_post(
                        body=_('Penalty deduction %s of ETB %.2f deducted in Payslip (%s).') % (
                            rec.name, rec.calculated_amount, rec.payslip_reference
                        )
                    )
                if rec.attendance_case_id:
                    rec.attendance_case_id.sudo().write({'deduction_status': 'deducted'})
                    rec.attendance_case_id.message_post(
                        body=_('Attendance penalty deduction %s of ETB %.2f deducted in Payslip (%s).') % (
                            rec.name, rec.calculated_amount, rec.payslip_reference
                        )
                    )

    def action_mark_reimbursed(self):
        """Alias for marking refund records as reimbursed in payslip."""
        return self.action_mark_deducted()

    def action_cancel(self):
        for rec in self:
            if rec.state in ('deducted', 'reimbursed'):
                raise UserError(_('Cannot cancel a payroll transaction that has already been processed in a payslip.'))
            rec.write({'state': 'cancelled'})
            if rec.case_id:
                rec.case_id.message_post(body=_('Payroll transaction %s cancelled/waived.') % rec.name)
            if rec.attendance_case_id:
                rec.attendance_case_id.sudo().write({'deduction_status': 'cancelled'})
                rec.attendance_case_id.message_post(body=_('Payroll transaction %s cancelled/waived.') % rec.name)

    def get_payroll_transmission_payload(self):
        """Public API returning structured penalty/reimbursement transmission payload for HR Payroll rule processing."""
        self.ensure_one()
        is_refund = (self.transaction_type == 'refund')
        case_ref = self.case_id.name if self.case_id else (self.attendance_case_id.name if self.attendance_case_id else '')
        v_type = 'Appeal Penalty Reimbursement' if is_refund else (
            (self.case_id.offense_id.name if self.case_id and self.case_id.offense_id else
             (self.attendance_case_id.offense_id.name if self.attendance_case_id and self.attendance_case_id.offense_id else 'Disciplinary Deduction'))
        )
        return {
            'penalty_id': self.id,
            'penalty_reference': self.name,
            'transaction_type': self.transaction_type,
            'parent_penalty_id': self.parent_penalty_id.id if self.parent_penalty_id else False,
            'appeal_reference': self.appeal_id.name if self.appeal_id else '',
            'case_reference': case_ref,
            'employee_id': self.employee_id.id,
            'employee_name': self.sudo().employee_id.name if self.sudo().employee_id else '',
            'violation_type': v_type,
            'calculation_method': self.penalty_type,
            'effective_date': fields.Date.to_string(self.effective_date or fields.Date.today()),
            'payroll_month': self.payroll_month,
            'approval_status': self.state,
            'amount': self.calculated_amount,
            'signed_amount': -self.calculated_amount if is_refund else self.calculated_amount,
            'penalty_percentage': self.penalty_percentage,
            'suspension_days': self.suspension_days,
            'managerial_days': self.managerial_days,
        }

    @api.model
    def get_pending_penalties(self, employee_id=None, date_from=None, date_to=None):
        """Public API returning list of pending penalty and reimbursement records for an employee or all employees during payroll execution.
        Note: Deductions take effect immediately upon enforcement regardless of whether the appeal window is open,
        unless held due to an active appeal under review.
        """
        domain = [
            ('state', 'in', ['pending', 'transferred']),
            ('is_appeal_held', '=', False),
        ]
        if employee_id:
            domain.append(('employee_id', '=', employee_id))
        if date_from:
            domain.append(('effective_date', '>=', date_from))
        if date_to:
            domain.append(('effective_date', '<=', date_to))
        penalties = self.search(domain)
        return [p.get_payroll_transmission_payload() for p in penalties]


