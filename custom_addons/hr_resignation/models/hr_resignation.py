from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import datetime
from dateutil.relativedelta import relativedelta

_CLEARANCE_DONE_STATES = ('cleared',)

class HrResignation(models.Model):
    """
    HR Resignation Request
    Manages the end-to-end workflow of an employee's separation from the company,
    including request submission, manager  review, HR approval, clearance tasks,
    exit interviews, and final settlement.
    """
    _name = 'hr.resignation'
    _description = 'HR Resignation Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    _rec_name = 'name'
    _order = 'id desc'

    # A tuple of clearance states considered as 'completed'
    _clearance_done_states = ('cleared',)

    # ── Identity ──────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference', default=lambda self: _('New'),
        readonly=True, copy=False)

    initiated_by = fields.Selection([
        ('employee', 'Employee'),
        ('company', 'Company'),
    ], required=True, default='employee',
        string='Initiated By',
        help='Employee: the employee requested to leave.\n'
             'Company: the company is ending the employment.')

    initiated_by_user_id = fields.Many2one(
        'res.users',
        string='Initiated By (User)',
        readonly=True,
        copy=False,
        help='The POMD/HR user who created this company-initiated resignation.'
    )

    resignation_type_id = fields.Many2one(
        'hr.separation.type',
        string='Separation Type',
        required=True,
        ondelete='restrict',
        help='Select the separation type that applies to this case. '
             'Types are managed in Configuration → Separation Types.')

    is_company_terminated = fields.Boolean(
        related='resignation_type_id.is_company_terminated',
        readonly=True,
        store=True,
        string="Is Company Terminated?"
    )

    # ── Employee Info ─────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', required=True,
        default=lambda self: self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.env.uid)], limit=1)
    )

    employee_sudo_name = fields.Char(
        string='Employee',
        compute='_compute_employee_sudo_name',
        help='Bypasses strict hierarchy rules to display employee name.'
    )
    
    employee_user_id = fields.Many2one('res.users', related='employee_id.user_id', store=True, compute_sudo=True)
    coach_user_id = fields.Many2one('res.users', related='coach_id.user_id', store=True, compute_sudo=True)

    
    @api.depends('employee_id')
    def _compute_employee_sudo_name(self):
        for rec in self:
            rec.employee_sudo_name = rec.employee_id.sudo().name if rec.employee_id else ''
    department_id = fields.Many2one('hr.department', readonly=True, store=True,
                                    compute='_compute_employee_info')
    job_id = fields.Many2one('hr.job', string='Job Position', readonly=True, store=True,
                             compute='_compute_employee_info')
    coach_id = fields.Many2one('hr.employee', string='Coach', readonly=True, store=True,
                                 compute='_compute_employee_info')
    is_current_manager = fields.Boolean(compute='_compute_is_current_manager')
    is_hr_user = fields.Boolean(compute='_compute_is_hr_user')
    is_direct_manager = fields.Boolean(compute='_compute_is_direct_manager')

    def _compute_is_direct_manager(self):
        for rec in self:
            rec.is_direct_manager = (rec.coach_id and rec.coach_id.sudo().user_id == self.env.user)

    @api.depends_context('uid')
    def _compute_is_hr_user(self):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        for rec in self:
            rec.is_hr_user = is_hr
    operating_unit_id = fields.Many2one('operating.unit', readonly=True, store=True,
                                        compute='_compute_employee_info')
    current_version_id = fields.Many2one('hr.version', string='Current Contract', readonly=True, store=True,
                                         compute='_compute_employee_info')
    joined_date = fields.Date(compute='_compute_joined_date', store=True, readonly=True,
                             string='Join Date')
    job_category = fields.Char(string='Job Category', compute='_compute_employee_info', store=True, readonly=True)
    basic_salary = fields.Float(string='Basic Salary', compute='_compute_employee_info', store=True, readonly=True)
    total_accrued_leave = fields.Float(string='Total Accrued Leave', compute='_compute_employee_info', store=True, readonly=True)
    total_scheduled_leave = fields.Float(string='Total Scheduled Leave', compute='_compute_employee_info', store=True, readonly=True)
    rssa = fields.Float(string='RSSA (Total Loan Taken)', compute='_compute_rssa_info', store=True)
    rssa_od_guarantier = fields.Char(string='RSSA/OD Guarantier', compute='_compute_rssa_info', store=True)
    liability = fields.Float(
        string='Notice Period Liability', 
        compute='_compute_liability', 
        store=True, 
        readonly=True,
        help="It is going to be deducted or he has to pay his one month salary when he does not accept the notice period."
    )
    release_date = fields.Date(
        string='Actual Last Day',
        tracking=True,
        help='Can only be set by the employee\'s Manager or by HR — '
             'never by the employee who filed the request.')

    @api.depends('notice_period_accepted', 'basic_salary')
    def _compute_liability(self):
        for rec in self:
            if rec.notice_period_accepted == 'no':
                rec.liability = rec.basic_salary
            else:
                rec.liability = 0.0

    @api.depends('employee_id')
    def _compute_employee_info(self):
        for rec in self:
            emp = rec.employee_id.sudo()
            if not emp:
                rec.department_id = False
                rec.job_id = False
                rec.coach_id = False
                rec.operating_unit_id = False
                rec.current_version_id = False
                rec.basic_salary = 0.0
                rec.job_category = ''
                rec.total_accrued_leave = 0.0
                rec.total_scheduled_leave = 0.0
                continue
            rec.department_id = emp.department_id
            rec.job_id = emp.job_position
            rec.coach_id = emp.coach_id
            rec.operating_unit_id = emp.operating_unit_id if 'operating_unit_id' in emp._fields else False
            # Forcefully search for the active contract in hr.version to guarantee we find it
            domain = [('employee_id', '=', emp._origin.id if hasattr(emp, '_origin') and emp._origin else emp.id), ('state', 'in', ['open', 'probation'])]
            contract = self.env['hr.version'].sudo().search(domain, limit=1)
            
            if not contract:
                contract = getattr(emp, 'contract_id', False) or getattr(emp, 'current_version_id', False)
                
            rec.current_version_id = contract
            rec.basic_salary = contract.wage if contract else 0.0

            # Fetch job category (Managerial / Non Managerial) from the employee's job position
            if 'employee_category' in emp.job_position._fields and emp.job_position.employee_category:
                rec.job_category = dict(emp.job_position._fields['employee_category'].selection).get(emp.job_position.employee_category, emp.job_position.employee_category)
            else:
                rec.job_category = ''
                
            # Fetch leave balances from HR Leave Request Custom module
            active_emp = emp._origin if hasattr(emp, '_origin') and emp._origin else emp
            balances = self.env['hr.leave'].sudo()._get_leave_balances(active_emp)
            rec.total_accrued_leave = balances.get('accrued', 0.0)
            rec.total_scheduled_leave = balances.get('scheduled', 0.0)

    @api.depends('employee_id')
    def _compute_rssa_info(self):
        for rec in self:
            if not rec.employee_id:
                rec.rssa = 0.0
                rec.rssa_od_guarantier = ''
                continue

            # Fetch RSSA (Total Loan Taken)
            Loan = self.env['resl.loan'].sudo()
            total_taken = Loan._employee_total_disbursed(rec.employee_id)
            rec.rssa = total_taken
            
            # Fetch Guarantors for this employee's loans
            my_loans = self.env['resl.loan'].sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('status', 'not in', ['rejected'])
            ])
            my_guarantors = my_loans.mapped('guarantor_line_ids').filtered(
                lambda l: l.state in ['pending', 'accepted']
            ).mapped('guarantor_id.name')
            
            info = []
            if my_guarantors:
                info.extend(my_guarantors)
                
            rec.rssa_od_guarantier = ', '.join(set(info)) if info else 'None'

    @api.depends('employee_id')
    def _compute_joined_date(self):
        for rec in self:
            emp = rec.employee_id.sudo()
            if not emp:
                rec.joined_date = False
                continue

            if hasattr(emp, 'first_contract_date') and emp.first_contract_date:
                rec.joined_date = emp.first_contract_date
            elif hasattr(emp, 'contract_id') and emp.contract_id and emp.contract_id.date_start:
                rec.joined_date = emp.contract_id.date_start
            elif emp.start_date:
                rec.joined_date = emp.start_date
            else:
                rec.joined_date = emp.create_date.date()


    @api.constrains('initiated_by', 'resignation_type_id')
    def _check_initiated_by_type(self):
        for rec in self:
            if rec.initiated_by == 'company':
                is_hr = self.env.user.has_group('hr.group_hr_user')
                is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
                is_own_record = (rec.employee_id.sudo().user_id == self.env.user)
                
                if is_own_record:
                    raise ValidationError(_("You cannot create a company-initiated termination for yourself."))
                    
                if not is_hr and not is_admin:
                    raise ValidationError(_("Only users with an HR role can initiate a company-terminated resignation."))

            if not rec.resignation_type_id:
                continue
            is_company = rec.resignation_type_id.is_company_terminated
            if rec.initiated_by == 'employee' and is_company:
                raise ValidationError(_("An employee-initiated request cannot use a company-termination separation type."))
            if rec.initiated_by == 'company' and not is_company:
                raise ValidationError(_("A company-initiated request must use a company-termination separation type."))

    @api.constrains('employee_id', 'resignation_type_id')
    def _check_employee_creation_rights(self):
        for rec in self:
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_own_record = (rec.employee_id.sudo().user_id == self.env.user)
            
            if not is_admin and not is_hr and not is_own_record:
                raise ValidationError(_("You cannot create a resignation request for another employee."))
                
            if not is_admin and is_hr and not is_own_record:
                if rec.resignation_type_id.code == 'voluntary':
                    raise ValidationError(_("HR cannot create a Voluntary Resignation on behalf of an employee. The employee must initiate it themselves."))
                    
            # Uniqueness check: An employee can only have one active resignation.
            active_resignation = self.env['hr.resignation'].sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('id', '!=', rec.id),
                ('state', 'not in', ('manager_rejected', 'hr_rejected', 'completed', 'settled'))
            ], limit=1)
            if active_resignation:
                raise ValidationError(_("This employee already has an active resignation request. You cannot create another one until the current request is finished or rejected."))

    @api.onchange('initiated_by')
    def _onchange_initiated_by(self):
        if self.resignation_type_id:
            is_company = self.resignation_type_id.is_company_terminated
            if self.initiated_by == 'company' and not is_company:
                self.resignation_type_id = False
            elif self.initiated_by == 'employee' and is_company:
                self.resignation_type_id = False

    # ── Dates ─────────────────────────────────────────────────────────
    application_date = fields.Date(
        default=fields.Date.context_today, readonly=True,
        string='Application Date')
    notice_period = fields.Integer(
        string='Notice Period (Days)',
        compute='_compute_notice_period', store=True, readonly=True,
        help="Automatically derived from the number of notice days on the "
             "employee's active contract (hr.version.notice_period). "
             "Falls back to 30 days if no contract, or no contract notice "
             "period, is available.")
    notice_period_accepted = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='Notice Period', copy=False,
        help='Employee confirms they accept the notice period derived from '
             'their hr.version contract. Required before the request can be '
             'submitted.')
    expected_last_day = fields.Date(
        compute='_compute_expected_last_day', store=True,
        string='Expected Last Day')
    release_date = fields.Date(
        string='Actual Last Day',
        tracking=True,
        help='Can only be set by the employee\'s Manager or by HR — '
             'never by the employee who filed the request.')
             
    release_date_justification = fields.Text(
        string='Release Date Justification',
        help='Required if the release date differs from the expected last day.')

    # ── Content ───────────────────────────────────────────────────────
    reason = fields.Text(required=True)

    # ── Manager Handover ──────────────────────────────────────────────
    handover_notes = fields.Text(
        string='Handover Notes',
        help='Supervisor records pending tasks, ongoing projects, access '
             'credentials to revoke/transfer, and other instructions.'
    )

    # ── Rejection ─────────────────────────────────────────────────────
    rejection_reason = fields.Text(readonly=True)

    # ── State ─────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('release_date_set', 'Release Date Set'),
        ('handover_completed', 'Handover Completed'),
        ('clearance_in_progress', 'Clearance In Progress'),
        ('cleared', 'Cleared'),
        ('settled', 'Settled'),
        ('completed', 'Completed'),
        ('returned', 'Returned'),
        ('revoked', 'Revoked'),
    ], default='draft', copy=False)

    # ── Clearance ─────────────────────────────────────────────────────
    clearance_line_ids = fields.One2many(
        'hr.resignation.clearance', 'resignation_id', string='Clearance Lines')
    clearance_progress = fields.Char(
        compute='_compute_clearance_progress', string='Clearance Progress')
    is_fully_cleared = fields.Boolean(
        compute='_compute_is_fully_cleared', store=True)

    cleared_by_id = fields.Many2one('res.users', string='Cleared By', readonly=True, tracking=True)
    cleared_date = fields.Datetime(string='Date Cleared', readonly=True)

    exit_interview_id = fields.Many2one('hr.exit.interview', readonly=True)
    performance_rating = fields.Selection([
        ('low', 'Low / Needs Improvement'),
        ('average', 'Average / Meets Expectations'),
        ('high', 'High / Exceeds Expectations'),
        ('excellent', 'Excellent / Outstanding')
    ], string='Performance Rating')
    exit_interview_waived = fields.Boolean(string="Exit Interview Waived", tracking=True)
    settlement_id = fields.Many2one('hr.resignation.settlement', readonly=True)

    # ── Related fields from exit interview (inline display on form) ──
    exit_interview_date = fields.Date(related='exit_interview_id.interview_date', readonly=True)
    exit_interview_state = fields.Selection(related='exit_interview_id.state', readonly=True)
    can_view_exit_interview = fields.Boolean(compute='_compute_can_view_exit_interview')

    @api.depends_context('uid')
    def _compute_can_view_exit_interview(self):
        is_hr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        for rec in self:
            is_employee = (rec.employee_id.sudo().user_id == self.env.user)
            rec.can_view_exit_interview = is_hr or is_admin or is_pomd or is_employee

    show_release_date_to_employee = fields.Boolean(compute='_compute_show_release_date_to_employee')

    @api.depends('state', 'release_date', 'resignation_type_id')
    def _compute_show_release_date_to_employee(self):
        for rec in self:
            is_hr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            is_manager = (rec.coach_id and rec.coach_id.sudo().user_id == self.env.user) or \
                         (rec.employee_id and rec.employee_id.parent_id and rec.employee_id.sudo().parent_id.user_id == self.env.user)
            is_pomd = self.env.user.has_group('hr_resignation.group_resignation_pomd_officer')

            if rec.is_company_terminated:
                # Always show release date for company-initiated types
                rec.show_release_date_to_employee = True
            elif rec.state in ('draft', 'submitted', 'manager_reviewed'):
                # Hidden from everyone during early stages for voluntary
                rec.show_release_date_to_employee = False
            elif rec.state in ('approved', 'handover_completed'):
                # Only HR / Admin / Manager / POMD can see and set it
                rec.show_release_date_to_employee = bool(is_hr or is_admin or is_manager or is_pomd)
            else:
                # release_date_set and beyond — visible to everyone including employee
                rec.show_release_date_to_employee = True

    can_edit_handover = fields.Boolean(compute='_compute_can_edit_handover')
    show_handover_tab = fields.Boolean(compute='_compute_show_handover_tab')

    @api.depends('state')
    def _compute_show_handover_tab(self):
        for rec in self:
            if rec.state in ('draft', 'submitted'):
                rec.show_handover_tab = False
            else:
                rec.show_handover_tab = True

    @api.depends('state', 'coach_id', 'employee_id')
    def _compute_can_edit_handover(self):
        for rec in self:
            is_manager = ((rec.coach_id and rec.coach_id.sudo().user_id == self.env.user) or (rec.employee_id and rec.employee_id.parent_id and rec.employee_id.sudo().parent_id.user_id == self.env.user))
            is_employee = (rec.employee_id and rec.employee_id.sudo().user_id == self.env.user)
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_pomd = self.env.user.has_group('hr_resignation.group_resignation_pomd_officer')
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            rec.can_edit_handover = (rec.state in ('approved', 'handover_completed', 'release_date_set')) and (is_manager or is_employee or is_hr or is_pomd or is_admin)

    # ── Related fields from settlement (inline display on form) ──────
    settlement_service_years = fields.Float(related='settlement_id.service_years', readonly=True)
    settlement_pf_eligible = fields.Selection(related='settlement_id.pf_eligible', readonly=True)
    settlement_severance_eligible = fields.Selection(related='settlement_id.severance_eligible', readonly=True)
    settlement_pf_amount = fields.Float(related='settlement_id.pf_amount', readonly=False)
    settlement_severance_amount = fields.Float(related='settlement_id.severance_amount', readonly=False)
    settlement_accrued_leave_pay = fields.Float(related='settlement_id.accrued_leave_pay', readonly=False)
    settlement_remaining_salary = fields.Float(related='settlement_id.remaining_salary', readonly=False)
    settlement_total = fields.Float(related='settlement_id.total_payment', readonly=True)

    settlement_line_ids = fields.One2many('hr.resignation.settlement.line', 'resignation_id', string='Settlement Lines')
    settlement_taxable_gross = fields.Float(related='settlement_id.taxable_gross', readonly=True)
    settlement_total_earnings = fields.Float(related='settlement_id.total_earnings', readonly=True)
    settlement_total_deductions = fields.Float(related='settlement_id.total_deductions_taxes', readonly=True)
    settlement_net = fields.Float(related='settlement_id.net_payment', readonly=True)
    settlement_state = fields.Selection(related='settlement_id.state', string='Settlement State')

    def action_generate_settlement_lines(self):
        for rec in self:
            if rec.settlement_id:
                rec.settlement_id.action_generate_lines()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # ── Counts for smart buttons ──────────────────────────────────────
    clearance_count = fields.Integer(compute='_compute_clearance_count')
    clearance_rejected_count = fields.Integer(
        compute='_compute_clearance_count',
        string='Rejected Clearances')

    allow_salary_payment = fields.Boolean(related='resignation_type_id.allow_salary_payment', readonly=True)
    allow_leave_encashment = fields.Boolean(related='resignation_type_id.allow_leave_encashment', readonly=True)
    show_severance_pay = fields.Boolean(related='resignation_type_id.pays_severance', readonly=True)
    show_pf_payment = fields.Boolean(related='resignation_type_id.pays_provident_fund', readonly=True)

    @api.onchange('resignation_type_id')
    def _onchange_resignation_type_id_entitlements(self):
        for rec in self:
            if rec.resignation_type_id:
                if not rec.allow_salary_payment:
                    rec.payment_request_unpaid_salary = False
                if not rec.allow_leave_encashment:
                    rec.payment_request_leave_pay = False
                if not rec.show_severance_pay:
                    rec.payment_request_severance = False
                if not rec.show_pf_payment:
                    rec.payment_request_pf = False

    payment_request_leave_pay = fields.Boolean(
        string='Accrued leave pay',
        default=False,
        help='Request payment for unutilized/accrued annual leave.')
    payment_request_unpaid_salary = fields.Boolean(
        string='Remaining salary',
        default=False,
        help='Request payment of any salary remaining for the current period.')
    payment_request_severance = fields.Boolean(
        string='Severance pay',
        default=False,
        help='Request severance pay where applicable.')
    payment_request_pf = fields.Boolean(
        string='PF',
        default=False,
        help='Request release of Provident Fund contributions.')
    payment_request_other = fields.Boolean(
        string='Any other payable benefits',
        default=False,
        help='Request any other payable benefits not listed above.')
    payment_request_other_detail = fields.Char(
        string='Specify Other Benefits',
        help='Describe the other payable benefits being requested.')
    payment_declaration_confirmed = fields.Boolean(
        string='I confirm the above payment requests are accurate',
        default=False,
        help='Employee must tick this to confirm the payment declaration '
             'before submitting.')

    debt_has_staff_loan = fields.Boolean(
        string='Staff Loan',
        default=False,
        help='Employee has an outstanding staff loan balance.')
    debt_has_rssa = fields.Boolean(
        string='RSSA',
        default=False,
        help='Employee has outstanding RSSA obligations.')
    debt_has_guarantee = fields.Boolean(
        string='Guarantee',
        default=False,
        help='Employee has active guarantees that may be deducted.')
    debt_has_advance = fields.Boolean(
        string='Salary Advance',
        default=False,
        help='Employee has outstanding salary advances.')
    debt_has_credit_facility = fields.Boolean(
        string='Credit Facility',
        default=False,
        help='Employee has an outstanding credit facility balance.')
    debt_has_other = fields.Boolean(
        string='Other Obligations',
        default=False,
        help='Employee has other outstanding debts or obligations.')
    debt_other_detail = fields.Char(
        string='Specify Other Obligations',
        help='Describe any other outstanding obligations.')
    debt_settlement_authorized = fields.Boolean(
        string='I authorize the Bank to settle any outstanding obligations from my separation payments',
        default=False,
        help='By ticking this, the employee authorizes the Bank to apply any '
             'separation payments toward settlement of outstanding obligations '
             '(staff loans, RSSA, guarantees, advances, credit facilities, or '
             'other debts) before releasing any remaining balance.')

    notice_override_justification = fields.Text(
        string='Notice Period Override Justification',
        help='Mandatory when the Actual Last Day falls before the notice '
             'period end date. Requires POMD authorization.')
    notice_override_by = fields.Many2one(
        'res.users', readonly=True, string='Override Authorized By')
    notice_override_date = fields.Date(readonly=True, string='Override Date')

    # ==================================================================
    # COMPUTES
    # ==================================================================

    @api.depends('employee_id', 'current_version_id', 'resignation_type_id', 'resignation_type_id.is_company_terminated')
    def _compute_notice_period(self):
        for rec in self:
            if rec.is_company_terminated:
                rec.notice_period = 0
            else:
                contract = rec.current_version_id
                default_np = rec.resignation_type_id.default_notice_period if rec.resignation_type_id else 30
                rec.notice_period = (
                    contract.notice_period if (contract and contract.notice_period) else default_np
                )

    @api.constrains('application_date')
    def _check_application_date_backdate(self):
        for rec in self:
            if rec.application_date and rec.application_date < fields.Date.today():
                raise ValidationError(_('Resignation Applied Date cannot be backdated (cannot be in the past).'))

    @api.depends('application_date', 'notice_period', 'notice_period_accepted')
    def _compute_expected_last_day(self):
        from datetime import timedelta
        for rec in self:
            if not rec.application_date:
                rec.expected_last_day = False
            elif rec.notice_period_accepted == 'no':
                rec.expected_last_day = rec.application_date
            elif rec.notice_period:
                # Subtract 1 day so that the application date is counted as day 1
                rec.expected_last_day = rec.application_date + timedelta(days=rec.notice_period - 1)
            else:
                rec.expected_last_day = rec.application_date

    @api.depends('clearance_line_ids.state', 'clearance_line_ids.is_mandatory')
    def _compute_clearance_progress(self):
        for rec in self:
            mandatory = rec.clearance_line_ids.filtered('is_mandatory')
            done = mandatory.filtered(lambda l: l.state in rec._clearance_done_states)
            rejected = mandatory.filtered(lambda l: l.state == 'rejected')
            total = len(mandatory)
            n_done = len(done)
            n_rejected = len(rejected)
            progress = f'{n_done} / {total}'
            if n_rejected:
                progress += f'  ({n_rejected} rejected)'
            rec.clearance_progress = progress if total else '0 / 0'

    @api.depends('clearance_line_ids.state', 'clearance_line_ids.is_mandatory')
    def _compute_is_fully_cleared(self):
        for rec in self:
            mandatory = rec.clearance_line_ids.filtered('is_mandatory')
            total = len(mandatory)
            done = mandatory.filtered(lambda l: l.state in rec._clearance_done_states)
            rejected = mandatory.filtered(lambda l: l.state == 'rejected')
            rec.is_fully_cleared = (
                    total > 0
                    and len(done) == total
                    and not rejected
            )

    @api.depends('clearance_line_ids.state')
    def _compute_clearance_count(self):
        for rec in self:
            lines = rec.clearance_line_ids
            rec.clearance_count = len(lines)
            rec.clearance_rejected_count = len(lines.filtered(lambda l: l.state == 'rejected'))

    # Validation Warning Counts for Banners (FR-SEP-007A)
    warning_disciplinary_count = fields.Integer(compute='_compute_validation_warnings')
    warning_investigation_count = fields.Integer(compute='_compute_validation_warnings')
    warning_commitment_count = fields.Integer(compute='_compute_validation_warnings')
    warning_probation_status = fields.Boolean(compute='_compute_validation_warnings')
    is_allowed_to_see_warnings = fields.Boolean(compute='_compute_is_allowed_to_see_warnings', default=False)

    @api.depends_context('uid')
    @api.depends('employee_id')
    def _compute_is_allowed_to_see_warnings(self):
        for rec in self:
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_self = rec.employee_id and rec.employee_id.sudo().user_id == self.env.user
            is_manager = rec.employee_id and rec.employee_id.coach_id and rec.employee_id.sudo().coach_id.user_id == self.env.user
            
            # Explicitly block the employee and their direct manager from seeing the warnings, 
            # even if they happen to have HR rights in the system for other reasons.
            if is_self or is_manager:
                rec.is_allowed_to_see_warnings = False
            else:
                rec.is_allowed_to_see_warnings = is_hr

    @api.depends('employee_id', 'resignation_type_id', 'current_version_id')
    def _compute_validation_warnings(self):
        for rec in self:
            emp = rec.employee_id
            sep_type = rec.resignation_type_id
            
            d_count, i_count, c_count, prob = 0, 0, 0, False
            if emp and sep_type:
                if sep_type.check_disciplinary and 'discipline.case' in self.env:
                    d_count = self.env['discipline.case'].sudo().search_count([
                        ('employee_id', '=', emp.id),
                        ('state', 'not in', ('closed', 'revoked', 'enforced'))
                    ])
                if sep_type.check_investigations and 'discipline.investigation' in self.env:
                    i_count = self.env['discipline.investigation'].sudo().search_count([
                        ('employee_id', '=', emp.id),
                        ('state', '!=', 'approved')
                    ])
                if sep_type.check_commitments:
                    if 'training.commitment' in self.env:
                        c_count += self.env['training.commitment'].sudo().search_count([
                            ('commitment_id', '=', emp.id),
                            ('end_date', '>=', fields.Date.today())
                        ])
                    if 'education.fee.sponsorship' in self.env:
                        c_count += self.env['education.fee.sponsorship'].sudo().search_count([
                            ('sponsorship_id', '=', emp.id),
                            ('end_date', '>=', fields.Date.today())
                        ])
                if sep_type.check_probation:
                    contract = rec.current_version_id
                    if contract and contract.state == 'probation':
                        prob = True

            rec.warning_disciplinary_count = d_count
            rec.warning_investigation_count = i_count
            rec.warning_commitment_count = c_count
            rec.warning_probation_status = prob

    def action_open_disciplinary_cases(self):
        self.ensure_one()
        return {
            'name': _('Active Disciplinary Cases'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('employee_id.name', '=', self.employee_id.sudo().name), ('state', 'not in', ['closed', 'revoked', 'enforced'])],
            'context': {'create': False, 'edit': False},
        }


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('hr.resignation') or _('New')
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            
            if not (is_hr or is_pomd or is_admin):
                employee = self.env['hr.employee'].sudo().search(
                    [('user_id', '=', self.env.uid)], limit=1)
                if employee:
                    if self.search([('employee_id', '=', employee.id), ('state', '!=', 'completed')], limit=1):
                        raise UserError(_('An active resignation request already exists for this employee.'))
                    vals['employee_id'] = employee.id
                vals['initiated_by'] = 'employee'
            # Capture who created the resignation when company-initiated
            if vals.get('initiated_by') == 'company' and not vals.get('initiated_by_user_id'):
                vals['initiated_by_user_id'] = self.env.uid
            if 'release_date' in vals:
                is_hr = self.env.user.has_group('hr.group_hr_user')
                is_manager = self.env.user.has_group('hr.group_hr_manager')
                is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
                if not (is_hr or is_manager or is_admin):
                    vals.pop('release_date', None)

        records = super().create(vals_list)
        return records

    def write(self, vals):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        
        if not (is_hr or is_pomd or is_admin):
            vals.pop('initiated_by', None)
            vals.pop('employee_id', None)

        if 'release_date' in vals:
            is_hr = self.env.user.has_group('hr.group_hr_user')
            is_manager = self.env.user.has_group('hr.group_hr_manager')
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            if not (is_hr or is_manager or is_admin):
                raise UserError(_(
                    'Only the employee\'s Manager or HR can set the '
                    'Actual Last Day.'))

        return super(HrResignation, self).write(vals)

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'manager_rejected', 'hr_rejected'):
                raise UserError(_('You can only delete draft or rejected resignation requests.'))
        return super().unlink()

    # ==================================================================
    # WORKFLOW ACTIONS
    # ==================================================================


    @api.depends('coach_id')
    def _compute_is_current_manager(self):
        for rec in self:
            rec.is_current_manager = (rec.coach_id.sudo().user_id == self.env.user)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.resignation_type_id:
                raise UserError(_('Separation Type is required.'))
            if not rec.employee_id:
                raise UserError(_('Employee is required.'))

            # Explicitly trigger constraints on submit
            rec._check_initiated_by_type()

            if rec.notice_period > 0 and not rec.notice_period_accepted:
                raise UserError(_('You must specify if you accept the Notice Period before submitting your resignation.'))
            rec.name = self.env['ir.sequence'].sudo().next_by_code('hr.resignation') or _('New')
            # Validate Payment Request Declaration
            missing = []
            if rec.allow_leave_encashment and not rec.payment_request_leave_pay: missing.append('Accrued leave pay')
            if rec.allow_salary_payment and not rec.payment_request_unpaid_salary: missing.append('Remaining salary')
            if rec.show_severance_pay and not rec.payment_request_severance: missing.append('Severance pay')
            if rec.show_pf_payment and not rec.payment_request_pf: missing.append('PF')
            
            if missing:
                raise UserError(_('Payment Request Declaration is incomplete.\n\nYou must select: %s.') % ', '.join(missing))
            if rec.payment_request_other and not rec.payment_request_other_detail:
                raise UserError(_(
                    'Please specify the other payable benefits you are '
                    'requesting in the "Specify Other Benefits" field.'))
            # Validate Debt Settlement Authorization
            if not rec.debt_settlement_authorized:
                raise UserError(_(
                    'Debt Settlement Authorization is required.\n\n'
                    'Please tick the authorization checkbox in the '
                    '"Debt Settlement Authorization" section before submitting.'))
            if rec.debt_has_other and not rec.debt_other_detail:
                raise UserError(_(
                    'Please specify the other obligations in the '
                    '"Specify Other Obligations" field.'))

            rec.state = 'submitted'

            # Auto-approve if Company-Initiated and user is HR Manager
            if rec.is_company_terminated and self.env.user.has_group('hr_resignation.group_resignation_hr_manager'):
                rec.action_hr_approve()

            # -------------------------------------------------------------
            # ASYNCHRONOUS NOTIFICATIONS
            # Send notifications in a true background thread so the UI 
            # responds instantly to the user without waiting.
            # -------------------------------------------------------------
            rec_id = rec.id
            dbname = self.env.cr.dbname
            original_uid = self.env.uid

            def _send_async_notifications(record_id, db_name, uid):
                import threading
                import time
                from odoo.modules.registry import Registry
                from odoo.api import Environment
                
                # Small delay to ensure the main transaction is committed before we read it
                time.sleep(1)
                
                try:
                    with Registry(db_name).cursor() as cr:
                        env = Environment(cr, uid, {})
                        rec2 = env['hr.resignation'].sudo().browse(record_id)
                        if not rec2.exists():
                            return

                        emp_name = rec2.employee_id.sudo().name or ''
                        ref = rec2.name or ''

                        is_company = rec2.is_company_terminated
                        sep_type_name = rec2.resignation_type_id.name if rec2.resignation_type_id else 'Separation'

                        # Pre-compute notification text to handle Employee vs HR initiated appropriately
                        if is_company:
                            rssa_subj = 'Separation of RSSA Loanee: %s' % emp_name
                            rssa_body = 'A company-initiated separation (%s) has been submitted for %s. As an active RSSA Guarantor, please be aware of this process.' % (sep_type_name, emp_name)
                            
                            mgr_subj = 'New Employee Separation (View Only): %s' % emp_name
                            mgr_body = 'HR has initiated a %s separation process for %s (%s). You have view-only access until it is formally approved.' % (sep_type_name, emp_name, ref)
                            
                            hr_subj = 'New Company-Initiated Separation for HR Approval: %s' % emp_name
                            hr_body = 'A company-initiated separation (%s) has been drafted for %s (%s) and is awaiting your approval.' % (sep_type_name, emp_name, ref)
                            
                            emp_subj = 'Separation Process Initiated: %s' % ref
                            emp_body = 'Dear %s,\n\nA company-initiated separation process (%s) has been formally initiated for you (%s). Please await further instructions from HR.' % (emp_name, sep_type_name, ref)
                        else:
                            rssa_subj = 'Resignation of RSSA Loanee: %s' % emp_name
                            rssa_body = 'The employee %s has submitted a resignation request. As an active RSSA Guarantor, please be aware of this resignation.' % emp_name
                            
                            mgr_subj = 'New Resignation Request (View Only): %s' % emp_name
                            mgr_body = '%s has submitted a resignation request (%s). You have view-only access until HR approves it.' % (emp_name, ref)
                            
                            hr_subj = 'New Resignation Request for HR Approval: %s' % emp_name
                            hr_body = '%s has submitted a resignation request (%s) and it is awaiting HR Manager approval.' % (emp_name, ref)
                            
                            emp_subj = 'Resignation Request Submitted: %s' % ref
                            emp_body = 'Dear %s,\n\nYour resignation request (%s) has been successfully submitted and is now pending HR Review.' % (emp_name, ref)

                        # 1. RSSA Guarantors
                        if rec2.rssa > 0.0 and 'resl.loan' in env:
                            active_loans = env['resl.loan'].sudo().search([
                                ('employee_id', '=', rec2.employee_id.id),
                                ('state', 'in', ['approved', 'disbursed'])
                            ])
                            guarantors = active_loans.mapped('guarantor_line_ids').filtered(lambda g: g.state == 'approved')
                            guarantor_partners = []
                            for g in guarantors:
                                if g.guarantor_id:
                                    if hasattr(g.guarantor_id, 'user_id') and g.guarantor_id.user_id:
                                        guarantor_partners.append(g.guarantor_id.user_id.partner_id.id)
                                    elif hasattr(g.guarantor_id, 'partner_id'):
                                        guarantor_partners.append(g.guarantor_id.partner_id.id)
                            if guarantor_partners:
                                rec2._send_notification(
                                    partner_ids=list(set(guarantor_partners)),
                                    subject=rssa_subj,
                                    body=rssa_body
                                )

                        # 2. Manager
                        manager = rec2.coach_id
                        if manager and manager.user_id:
                            rec2._send_notification(
                                partner_ids=manager.user_id.partner_id.ids,
                                subject=mgr_subj,
                                body=mgr_body,
                            )

                        # 3. Notification for HR Approval (If still submitted and not auto-approved)
                        if rec2.state == 'submitted':
                            hr_manager_ref = env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
                            hr_managers = hr_manager_ref.sudo().user_ids.filtered(lambda u: u.active) if hr_manager_ref else env['res.users'].sudo()
                            hr_manager_partners = hr_managers.mapped('partner_id').ids
                            
                            if hr_manager_partners:
                                rec2._send_notification(
                                    partner_ids=hr_manager_partners,
                                    subject=hr_subj,
                                    body=hr_body,
                                )

                        # 4. POMD Officers — always informed of every new submission
                        pomd_ref = env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
                        if pomd_ref:
                            pomd_partners = pomd_ref.sudo().user_ids.filtered(lambda u: u.active).mapped('partner_id').ids
                            if pomd_partners:
                                pomd_subj = 'New Separation Request Submitted: %s' % emp_name
                                pomd_body = (
                                    'A new separation request (%s) has been submitted for %s (%s). '
                                    'Please be aware and prepare for the upcoming clearance and settlement process.'
                                ) % (ref, emp_name, sep_type_name)
                                rec2._send_notification(
                                    partner_ids=pomd_partners,
                                    subject=pomd_subj,
                                    body=pomd_body,
                                )

                        # 5. Employee confirmation
                        emp_user = rec2.employee_id.sudo().user_id
                        if emp_user and emp_user.active:
                            rec2._send_notification(
                                partner_ids=emp_user.partner_id.ids,
                                subject=emp_subj,
                                body=emp_body,
                            )
                        
                        cr.commit()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error('Async notification failed: %s', e, exc_info=True)

            # Start the background thread
            import threading
            t = threading.Thread(target=_send_async_notifications, args=(rec_id, dbname, original_uid))
            t.daemon = True
            t.start()
            # -------------------------------------------------------------

        # Build a rich, personalised success message for the submitting user
        rec = self[:1]
        emp_name = rec.employee_id.sudo().name if rec else ''
        ref = rec.name if rec else ''
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted Successfully!'),
                'message': _('✅ Resignation request %s submitted successfully! Dear %s, your request has been received and is now pending HR Review. You will be notified at each step of the process.') % (ref, emp_name),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.resignation',
                    'res_id': rec.id,
                    'view_mode': 'form',
                    'views': [[False, 'form']],
                    'target': 'current',
                    'context': {'form_view_initial_mode': 'readonly'},
                },
            },
        }


    def action_hr_approve(self):
        if not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
            raise UserError(_('Only HR Manager can approve resignation requests.'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved.'))

            # Dynamic pre-separation validations based on Separation Type
            sep_type = rec.resignation_type_id
            emp = rec.employee_id
            
            if sep_type:
                # 1. Disciplinary Cases check
                if sep_type.check_disciplinary and 'discipline.case' in self.env:
                    active_cases = self.env['discipline.case'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('state', 'not in', ('closed', 'revoked', 'enforced'))
                    ])
                    if active_cases:
                        pass # Allowed to proceed, HR reviews it visually.

                # 2. Ongoing Investigations check
                if sep_type.check_investigations and 'discipline.investigation' in self.env:
                    active_invs = self.env['discipline.investigation'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('state', '!=', 'approved')
                    ])
                    if active_invs:
                        inv_refs = ', '.join(active_invs.mapped('name'))
                        raise UserError(_(
                            "Cannot approve separation. The employee is subject to ongoing disciplinary investigations: %s. "
                            "These findings must be finalized and approved first."
                        ) % inv_refs)

                # 3. Contractual Commitments & Sponsorships check
                if sep_type.check_commitments:
                    active_commitments = []
                    if 'training.commitment' in self.env:
                        commitments = self.env['training.commitment'].sudo().search([
                            ('commitment_id', '=', emp.id),
                            ('end_date', '>=', fields.Date.today())
                        ])
                        if commitments:
                            active_commitments.extend([f"Training Commitment ({c.training_reference or 'N/A'})" for c in commitments])
                    if 'education.fee.sponsorship' in self.env:
                        sponsorships = self.env['education.fee.sponsorship'].sudo().search([
                            ('sponsorship_id', '=', emp.id),
                            ('end_date', '>=', fields.Date.today())
                        ])
                        if sponsorships:
                            active_commitments.extend([f"Education Sponsorship ({s.sponsorhip_reference or 'N/A'})" for s in sponsorships])
                    if active_commitments:
                        raise UserError(_(
                            "Cannot approve separation. The employee has active contractual/bond commitments: %s. "
                            "Please settle these commitments before proceeding."
                        ) % ', '.join(active_commitments))

                # 4. Probation status check
                if sep_type.check_probation:
                    contract = rec.current_version_id
                    if contract and contract.state == 'probation':
                        raise UserError(_(
                            "Cannot approve separation. The employee is still on probation. "
                            "Please evaluate or adjust their probation status first."
                        ))
            rec.state = 'approved'
            
            # Update the flag on the contract
            if rec.current_version_id and hasattr(rec.current_version_id, 'has_approved_resignation'):
                rec.current_version_id.has_approved_resignation = True

            # Assign exit interview
            if not rec.exit_interview_id:
                template = rec.resignation_type_id.exit_interview_template_id
                if not template:
                    template = self.env['hr.exit.interview.template'].sudo().search([], limit=1)
                interview = self.env['hr.exit.interview'].sudo().create({
                    'resignation_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'template_id': template.id if template else False,
                })
                rec.exit_interview_id = interview

            if rec.exit_interview_id:
                # Schedule an activity for the employee to complete the exit interview
                emp_user = rec.employee_id.sudo().user_id
                if emp_user:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=emp_user.id,
                        note=_('Please complete your exit interview.'),
                        summary=_('Complete Exit Interview'),
                        date_deadline=fields.Date.today()
                    )
                
                try:
                    rec.exit_interview_id.action_open_interview()
                except Exception:
                    pass  # Non-critical, interview created but portal link not generated
                
            emp_name = rec.employee_id.sudo().name
            rec_name = rec.name

            # Notify the employee
            emp_user = rec.employee_id.sudo().user_id
            if emp_user and emp_user.active:
                rec._send_notification(
                    partner_ids=emp_user.partner_id.ids,
                    subject=_('Your Resignation Has Been Approved: %s') % rec_name,
                    body=_(
                        'Dear %s,\n\n'
                        'Your resignation request (%s) has been formally approved by HR. '
                        'An Exit Interview has been assigned to you. Please complete it.\n'
                        'Your manager will now set your Release Date.'
                    ) % (emp_name, rec_name),
                )

            # Notify the direct manager
            manager_user = rec.coach_id.sudo().user_id
            if manager_user and manager_user.active:
                rec._send_notification(
                    partner_ids=manager_user.partner_id.ids,
                    subject=_('Resignation Approved — Please Set Release Date: %s') % emp_name,
                    body=_(
                        'The resignation request (%s) for %s has been approved by HR. '
                        'Please open the record and set the Release Date.'
                    ) % (rec_name, emp_name),
                )

            # Notify POMD officers
            pomd_group = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
            if pomd_group:
                pomd_partners = pomd_group.sudo().user_ids.mapped('partner_id').ids
                if pomd_partners:
                    rec._send_notification(
                        partner_ids=pomd_partners,
                        subject=_('Resignation Approved: %s') % emp_name,
                        body=_(
                            'The resignation request for %s has been formally approved by HR. '
                            'The direct manager is now prompted to set the Release Date.'
                        ) % (emp_name),
                    )

            # Notify Auditor
            auditor_group = self.env.ref('hr_resignation.group_resignation_auditor', raise_if_not_found=False)
            if auditor_group:
                auditor_partners = auditor_group.sudo().user_ids.mapped('partner_id').ids
                if auditor_partners:
                    rec._send_notification(
                        partner_ids=auditor_partners,
                        subject=_('Resignation Approved: %s') % emp_name,
                        body=_(
                            'The resignation request for %s has been formally approved by HR. '
                            'The separation process is now moving forward.'
                        ) % (emp_name),
                    )

    def action_set_release_date(self):
        for rec in self:
            if rec.state != 'handover_completed':
                raise UserError(_('Can only set Release Date after the Handover is completed.'))
            if not rec.release_date:
                raise UserError(_('Please specify the Release Date before confirming.'))
                
            if rec.release_date < fields.Date.today():
                raise UserError(_('Release Date cannot be in the past. Backdating is invalid.'))
                
            if rec.expected_last_day and rec.release_date != rec.expected_last_day and not rec.release_date_justification:
                raise UserError(_('Because the Release Date differs from the Expected Last Day, you must provide a justification.'))
            
            # Validation for exit interview at release date (as requested by user)
            if not rec.exit_interview_waived and (not rec.exit_interview_id or rec.exit_interview_id.state != 'completed'):
                raise UserError(_('The employee must complete the exit interview before the Release Date can be set.'))
                
            rec.state = 'clearance_in_progress'
            
            # Notify employee, HR Officers, HR Manager, POMD Officers
            partners = []
            if rec.employee_id.sudo().user_id:
                partners.append(rec.employee_id.sudo().user_id.partner_id.id)
                
            hr_group_ref = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
            if hr_group_ref:
                partners.extend(hr_group_ref.sudo().user_ids.mapped('partner_id').ids)
            hr_manager_ref = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
            if hr_manager_ref:
                partners.extend(hr_manager_ref.sudo().user_ids.mapped('partner_id').ids)
            pomd_ref = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
            if pomd_ref:
                partners.extend(pomd_ref.sudo().user_ids.mapped('partner_id').ids)
                
            if partners:
                rec._send_notification(
                    partner_ids=list(set(partners)),
                    subject=_('Release Date Set for %s') % rec.employee_id.sudo().name,
                    body=_('The Release Date for %s has been set to %s by their manager. Handover can now proceed.') 
                          % (rec.employee_id.sudo().name, rec.release_date)
                )

            # Create clearance lines
            rec._create_clearance_lines()

            # Notify clearance units
            for line in rec.clearance_line_ids:
                if line.responsible_user and line.responsible_user.partner_id:
                    rec._send_notification(
                        partner_ids=line.responsible_user.partner_id.ids,
                        subject=_('Clearance Action Required: %s') % rec.employee_id.sudo().name,
                        body=_('The Release Date for %s is set to %s. You may now begin clearance processing.')
                             % (rec.employee_id.sudo().name, rec.release_date)
                    )

    def action_complete_handover(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Handover can only be completed after HR approval.'))
            
            # Just require the text field to have something in it (strip HTML tags)
            from odoo.tools import html2plaintext
            if not rec.handover_notes or not html2plaintext(rec.handover_notes).strip():
                raise UserError(_('Handover Notes are required.'))
            
            rec.state = 'handover_completed'

            # --- USER REQUEST: Create clearance lines & Notify on handover complete ---
            if not rec.clearance_line_ids:
                rec._create_clearance_lines()
            
            # Notify employee, HR Officers, HR Manager, POMD Officers
            partners = []
            if rec.employee_id.sudo().user_id:
                partners.append(rec.employee_id.sudo().user_id.partner_id.id)
            hr_group_ref = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
            if hr_group_ref:
                partners.extend(hr_group_ref.sudo().user_ids.mapped('partner_id').ids)
            hr_manager_ref = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
            if hr_manager_ref:
                partners.extend(hr_manager_ref.sudo().user_ids.mapped('partner_id').ids)
            pomd_ref = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
            if pomd_ref:
                partners.extend(pomd_ref.sudo().user_ids.mapped('partner_id').ids)
                
            if partners:
                rec._send_notification(
                    partner_ids=list(set(partners)),
                    subject=_('Handover Completed for %s') % rec.employee_id.sudo().name,
                    body=_('The manager has completed the handover for %s. Please proceed to complete the clearance process.') % rec.employee_id.sudo().name
                )

            # Notify clearance units
            for line in rec.clearance_line_ids:
                if line.responsible_user and line.responsible_user.partner_id:
                    rec._send_notification(
                        partner_ids=line.responsible_user.partner_id.ids,
                        subject=_('Handover Completed: %s') % rec.employee_id.sudo().name,
                        body=_('The manager has completed the handover for %s. Please proceed to complete the clearance process.') % rec.employee_id.sudo().name
                    )

            if rec.is_company_terminated:
                # Bypass action_set_release_date validations for company-initiated
                # since HR already set the release date during creation.
                rec.state = 'clearance_in_progress'

    def action_complete_exit_interview(self):
        self.ensure_one()
        if not self.exit_interview_id:
            template = self.resignation_type_id.exit_interview_template_id
            if not template:
                template = self.env['hr.exit.interview.template'].sudo().search([], limit=1)
            interview = self.env['hr.exit.interview'].sudo().create({
                'resignation_id': self.id,
                'employee_id': self.employee_id.id,
                'template_id': template.id if template else False,
            })
            self.exit_interview_id = interview
        return self.exit_interview_id.action_open_interview()

    def action_mark_exit_interviewed(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Please wait for HR Approval first.'))
            rec._check_and_advance_cleared()
        return self._show_success_message(_('Exit interview marked as completed.'))

    def action_waive_exit_interview(self):
        if not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_auditor') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager can waive the exit interview.'))
        for rec in self:
            if rec.state not in ('approved', 'release_date_set', 'clearance_in_progress'):
                raise UserError(_('Please wait for HR Approval first before waiving exit interview.'))
            rec.exit_interview_waived = True
            rec.message_post(body=_("Exit Interview has been waived."))
            rec._check_and_advance_cleared()
        return self._show_success_message(_('Exit interview successfully waived.'))

    def action_complete_clearance(self):

        if not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_auditor') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager can complete clearance.'))
        for rec in self:
            if not rec.exit_interview_waived and (not rec.exit_interview_id or rec.exit_interview_id.state != 'completed'):
                raise UserError(_('The Exit Interview has to be processed first, unless waived by authorized HR or POMD personnel.'))
            mandatory = rec.clearance_line_ids.filtered('is_mandatory')
            if not mandatory:
                raise UserError(_('No mandatory clearance lines found.'))
            unresolved = mandatory.filtered(lambda l: l.state not in _CLEARANCE_DONE_STATES)
            if unresolved:
                raise UserError(_(
                    'Cannot complete clearance: %d mandatory clearance line(s) are still pending or rejected.')
                                % len(unresolved))
            rec.state = 'cleared'

        if len(self) == 1:
            return self.action_process_settlement()

    def action_process_settlement(self):
        if not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_auditor') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager can process settlement.'))
        self.ensure_one()
        if not self.settlement_id:
            settlement = self.env['hr.resignation.settlement'].sudo().create({
                'resignation_id': self.id,
                'employee_id': self.employee_id.id,
                'settlement_date': self.release_date,
            })
            self.settlement_id = settlement
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.resignation.settlement',
            'res_id': self.settlement_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_settlement_submit(self):
        for rec in self:
            if rec.settlement_id:
                rec.settlement_id.action_confirm_settlement()
    
    def action_settlement_approve(self):
        for rec in self:
            if rec.settlement_id:
                rec.settlement_id.action_approve_settlement()

    def action_settlement_pay(self):
        for rec in self:
            if rec.settlement_id:
                rec.settlement_id.action_mark_paid()

    def action_mark_settled_no_payment(self):
        """
        For employees who are not entitled to any payment (e.g. probation termination
        with no eligible benefits), HR Manager can mark the resignation as settled
        directly without going through the payment workflow. The Certificate of Release
        is then available to be issued.
        """
        is_hr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        if not (is_hr or is_admin):
            raise UserError(_('Only an HR Manager can mark a case as settled with no payment.'))
        for rec in self:
            if rec.state != 'cleared':
                raise UserError(_('Clearance must be completed before marking as settled.'))
            # Move settlement to paid state if it exists and is in draft
            if rec.settlement_id and rec.settlement_id.state == 'draft':
                rec.settlement_id.sudo().write({
                    'state': 'paid',
                    'paid_by_id': self.env.user.id,
                    'paid_date': fields.Datetime.now(),
                })
            rec.state = 'settled'
            rec.message_post(
                body=_('Marked as Settled (No Payment): No financial entitlements are applicable for this separation. Certificate of Release is now available.'),
                message_type='notification',
            )
        return self._show_success_message(_('Case marked as settled. You can now issue the Certificate of Release.'))

    def action_confirm_settled(self):

        if not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_auditor') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager can confirm settlement.'))
        for rec in self:
            if rec.state != 'cleared':
                raise UserError(_('Clearance must be completed before settlement.'))
            rec.state = 'settled'
        return self._show_success_message(_('Settlement confirmed successfully.'))

    def action_issue_certificate(self):

        is_hr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        
        if not (is_hr or is_pomd or is_admin):
            raise UserError(_('Only an HR Manager or POMD Officer can issue the Certificate of Release.'))
        for rec in self:
            if rec.state != 'settled':
                raise UserError(_('Settlement must be confirmed before issuing the certificate.'))
            rejected = rec.clearance_line_ids.filtered(
                lambda l: l.is_mandatory and l.state == 'rejected')
            if rejected:
                units = ', '.join(rejected.mapped('work_unit_id.name'))
                raise UserError(_(
                    'Cannot close case. The following mandatory clearance lines '
                    'are still rejected and must be resolved first:\n• %s') % units)
            rec.state = 'completed'
            rec._trigger_access_revocation()
        return self.env.ref(
            'hr_resignation.action_report_certificate_of_release').report_action(self)

    def action_download_certificate(self):
        """Download certificate for a completed resignation."""
        self.ensure_one()
        if self.state != 'completed':
            raise UserError(_('Certificate is only available after the resignation is completed.'))
        return self.env.ref('hr_resignation.action_report_certificate_of_release').report_action(self)

    def _trigger_access_revocation(self):

        for rec in self:
            emp = rec.employee_id
            if emp.user_id and emp.user_id.active:
                emp.user_id.sudo().write({'active': False})
            if emp.active:
                emp.sudo().write({'active': False})
                
    def _show_success_message(self, message, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': message,
                'type': 'success',
                'sticky': sticky,
            }
        }


    # ==================================================================
    # CLEARANCE HELPERS
    # ==================================================================

    def action_regenerate_clearance_lines(self):

        for rec in self:
            if rec.state in ('cleared', 'settled', 'completed'):
                raise UserError(_(
                    'Clearance lines cannot be regenerated after the case '
                    'has been cleared or closed.'))
            rec._create_clearance_lines()
        return self._show_success_message(_('Clearance lines have been recreated from the current template.'))

    def _create_clearance_lines(self):

        self.ensure_one()
        self.env['hr.resignation.clearance'].sudo().search(
            [('resignation_id', '=', self.id)]
        ).unlink()

        templates = self.env['hr.resignation.clearance.template'].sudo().search(
            [('active', '=', True)], order='sequence asc')

        if not templates:
            raise UserError(_(
                'No active clearance work units found.\n'
                'Go to Configuration → Clearance Work Units and add at least one.'))

        sep_type_rec = self.resignation_type_id
        ClearLine = self.env['hr.resignation.clearance'].sudo()
        ItemModel = self.env['hr.resignation.clearance.line.item'].sudo()
        created_lines = ClearLine


        for tmpl in templates.sorted(lambda t: t.sequence):
            line = ClearLine.create({
                'resignation_id': self.id,
                'template_id': tmpl.id,
                'sequence': tmpl.sequence,
                'work_unit_id': tmpl.work_unit_id.id,
                'responsible_user': tmpl.responsible_user.id,
                'is_mandatory':     tmpl.is_mandatory,
                'sdt_days':         tmpl.sdt_days,
                'pending_since':    fields.Datetime.now(),
                'state': 'pending',
                'notification_sent': False,
            })
            created_lines |= line

            for item in tmpl.checklist_item_ids.sorted('sequence'):
                ItemModel.create({
                    'clearance_line_id': line.id,
                    'sequence': item.sequence,
                    'name': item.name,
                    'is_mandatory': item.is_mandatory,
                    'note': item.note,
                })

        # Notify all lines immediately.
        for line in created_lines:
            line._notify_responsible_user()

        return created_lines


    def _check_and_advance_cleared(self):
        for rec in self:
            if rec.state not in ('clearance_in_progress', 'handover_completed'):
                continue
            mandatory = rec.clearance_line_ids.filtered('is_mandatory')
            if not mandatory:
                continue
            unresolved = mandatory.filtered(
                lambda l: l.state not in _CLEARANCE_DONE_STATES)
            if unresolved:
                return
            
            # If we just now advanced to cleared
            if rec.state != 'cleared':
                rec.state = 'cleared'
                
                # Notify POMD officers that clearance is done and settlement can begin
                pomd_group = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
                if pomd_group:
                    pomd_partners = pomd_group.sudo().user_ids.mapped('partner_id').ids
                    if pomd_partners:
                        rec._send_notification(
                            partner_ids=pomd_partners,
                            subject=_('Clearance Completed: %s') % rec.employee_id.sudo().name,
                            body=_(
                                'All mandatory clearance tasks for %s have been completed. '
                                'The resignation is now in the "Cleared" state. '
                                'You may now proceed to process their Final Settlement.'
                            ) % (rec.employee_id.sudo().name),
                        )


    def _trigger_access_revocation(self):

        for rec in self:
            emp = rec.employee_id
            if emp.user_id and emp.user_id.active:
                emp.user_id.sudo().write({'active': False})


    def _send_notification(self, partner_ids, subject, body):
        self.ensure_one()
        if not partner_ids:
            return

        from markupsafe import Markup
        # Use the current user's profile so it shows their Avatar and Name, not OdooBot
        author_id = self.env.user.partner_id.id

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        discuss_body = Markup(f"<b>{subject}</b><br/><br/>{body}<br/><br/><a href='{record_url}'>Click here to view</a>")

        # Post the message as a Direct Message so it appears with the sender's Avatar
        author_user = self.env['res.users'].sudo().sudo().search([('partner_id', '=', author_id)], limit=1)
        if not author_user:
            author_user = self.env.user

        for partner_id in list(set(partner_ids)):
            try:
                if partner_id == author_id:
                    # Sending to yourself - skip DM
                    continue
                
                # Use with_user to correctly pair the two users in the chat without injecting the system user
                channel = self.env['discuss.channel'].sudo().with_user(author_user)._get_or_create_chat([partner_id])
                if channel:
                    channel.sudo().with_context(mail_create_nosubscribe=True).message_post(
                        body=discuss_body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        author_id=author_id,
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning('Failed to send discuss message to %s: %s', partner_id, e)



    def action_hr_return(self):
        return self._open_reject_wizard('return')

    def action_hr_revoke(self):
        return self._open_reject_wizard('revoke')

    def _open_reject_wizard(self, reject_by):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rejection Reason'),
            'res_model': 'hr.resignation.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_resignation_id': self.id,
                'default_reject_by': reject_by,
            },
        }

    @api.model
    def update_employee_status(self):

        today = fields.Date.today()
        completed_resignations = self.search([
            ('state', '=', 'completed'),
            ('release_date', '<=', today),
            ('employee_id.active', '=', True)
        ])
        for rec in completed_resignations:
            rec.employee_id.sudo().write({'active': False})
            rec.message_post(body=_("Employee deactivated/archived automatically on their last working day (%s) by scheduler.") % rec.release_date)
        return True
