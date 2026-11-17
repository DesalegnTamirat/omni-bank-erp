from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import os
import base64
import requests
import logging
_logger = logging.getLogger(__name__)
_CLEARANCE_DONE_STATES = ('cleared',)
_SEPARATED_RESIGNATION_STATES = ('settled', 'completed')
_APPROVED_RESIGNATION_STATES = (
    'approved', 'release_date_set', 'handover_completed',
    'clearance_in_progress', 'cleared', 'settled', 'completed',
)


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

    def init(self):
        super().init()
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS hr_resignation_emp_state_idx "
            "ON hr_resignation (employee_id, state)"
        )

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

    certificate_signing_mode = fields.Selection(
        [
            ('digital', 'Digital (Include Uploaded Signature and Stamp)'),
            ('manual', 'Manual (Print Blank for Physical Hand Signing and Stamping)'),
        ],
        string="Certificate Print Option",
        default='digital',
        help="Controls how this certificate is printed."
    )
    acceptance_signing_mode = fields.Selection(
        [
            ('digital', 'Digital (Include Uploaded Signature and Stamp)'),
            ('manual', 'Manual (Print Blank for Physical Hand Signing and Stamping)'),
        ],
        string="Acceptance Letter Print Option",
        default='digital',
        help="Controls how the Acceptance Letter signature/stamp is printed."
    )

    @api.model
    def _default_resignation_type_id(self):
        # Automatically pre-fill Voluntary Resignation
        sep_type = self.env['hr.separation.type'].search([('code', '=', 'voluntary')], limit=1)
        if not sep_type:
            sep_type = self.env['hr.separation.type'].search([('is_company_terminated', '=', False)], limit=1)
        return sep_type.id if sep_type else False

    resignation_type_id = fields.Many2one(
        'hr.separation.type',
        string='Separation Type',
        required=True,
        default=lambda self: self._default_resignation_type_id(),
        ondelete='restrict',
        help='Select the separation type that applies to this case. '
             'Types are managed in Configuration → Separation Types.')

    is_company_terminated = fields.Boolean(
        related='resignation_type_id.is_company_terminated',
        readonly=True,
        store=True,
        string="Is Company Terminated?"
    )

    bypass_handover = fields.Boolean(
        related='resignation_type_id.bypass_handover',
        readonly=True,
        store=True,
        string="Bypass Handover"
    )

    # ── Employee Info ─────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', required=True, index=True,
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
    can_hr_approve = fields.Boolean(compute='_compute_can_hr_approve')
    can_issue_certificate = fields.Boolean(compute='_compute_can_issue_certificate')
    is_direct_manager = fields.Boolean(compute='_compute_is_direct_manager')
    is_my_team = fields.Boolean(
        string='Is My Team',
        compute='_compute_is_my_team',
        search='_search_is_my_team'
    )

    # ── Delegation Support Helpers ────────────────────────────────────

    @api.model
    def _is_user_acting_delegate(self, user, manager_employee):
        """Check if `user` is an active delegate of `manager_employee` today."""
        if not user or not manager_employee:
            return False
        today = fields.Date.today()
        user_emp = user.employee_id
        if not user_emp:
            return False
        delegation = self.env['hr.employee.delegation'].sudo().search([
            ('employee_id', '=', manager_employee.id),
            ('delegate_id', '=', user_emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ], limit=1)
        return bool(delegation)

    @api.model
    def _get_active_delegates_for_employee(self, employee):
        """Return active delegate users for `employee` today."""
        if not employee:
            return self.env['res.users']
        today = fields.Date.today()
        delegations = self.env['hr.employee.delegation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        return delegations.mapped('delegate_id.user_id').filtered(lambda u: u.active)

    @api.model
    def _is_user_acting_hr_manager(self, user):
        """Check if `user` is an HR Manager directly, or is acting as an active delegate of an HR Manager."""
        if not user:
            return False
        if (user.has_group('hr_resignation.group_resignation_hr_manager') or
            user.has_group('base.group_system') or
            user.has_group('hr_resignation.group_resignation_admin')):
            return True
        user_emp = user.employee_id
        if not user_emp:
            return False
        today = fields.Date.today()
        hr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        if not hr_group:
            return False
        hr_mgr_emps = hr_group.sudo().user_ids.filtered(lambda u: u.active).mapped('employee_id')
        if not hr_mgr_emps:
            return False
        delegation = self.env['hr.employee.delegation'].sudo().search([
            ('employee_id', 'in', hr_mgr_emps.ids),
            ('delegate_id', '=', user_emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ], limit=1)
        return bool(delegation)

    @api.model
    def _get_acting_delegation(self, user, manager_employee):
        """Return the active delegation record if `user` is currently acting on behalf of `manager_employee`."""
        if not user or not manager_employee:
            return False
        user_emp = user.employee_id
        if not user_emp:
            return False
        today = fields.Date.today()
        return self.env['hr.employee.delegation'].sudo().search([
            ('employee_id', '=', manager_employee.id),
            ('delegate_id', '=', user_emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ], limit=1)

    @api.model
    def _get_acting_hr_delegation(self, user):
        """Return the active delegation record if `user` is acting on behalf of an HR Manager."""
        if not user:
            return False
        user_emp = user.employee_id
        if not user_emp:
            return False
        today = fields.Date.today()
        hr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        if not hr_group:
            return False
        hr_mgr_emps = hr_group.sudo().user_ids.filtered(lambda u: u.active).mapped('employee_id')
        if not hr_mgr_emps:
            return False
        return self.env['hr.employee.delegation'].sudo().search([
            ('employee_id', 'in', hr_mgr_emps.ids),
            ('delegate_id', '=', user_emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ], limit=1)

    @api.model
    def _get_delegation_visible_resignation_ids(self):
        """Used in ir.rule domain force for acting delegates."""
        emp = self.env.user.employee_id
        if not emp:
            return []
        today = fields.Date.today()
        active_delegations = self.env['hr.employee.delegation'].sudo().search([
            ('delegate_id', '=', emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        if not active_delegations:
            return []

        delegator_emps = active_delegations.mapped('employee_id')
        delegator_users = delegator_emps.mapped('user_id').filtered(lambda u: u)

        # Check if any delegator is an HR Manager / POMD / Admin
        hr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        pomd_group = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
        is_acting_hr = False
        if hr_group and any(u in hr_group.user_ids for u in delegator_users):
            is_acting_hr = True
        if pomd_group and any(u in pomd_group.user_ids for u in delegator_users):
            is_acting_hr = True

        if is_acting_hr:
            return self.sudo().search([]).ids

        # Otherwise: visible if delegator is coach_id, direct manager (parent_id), or responsible for clearance
        visible = self.sudo().search([
            '|', '|',
            ('coach_id', 'in', delegator_emps.ids),
            ('employee_id.parent_id', 'in', delegator_emps.ids),
            ('clearance_line_ids.responsible_user', 'in', delegator_users.ids),
        ])
        return visible.ids

    def _compute_is_direct_manager(self):
        current_user = self.env.user
        for rec in self:
            is_mgr = False
            if rec.coach_id and rec.coach_id.sudo().user_id == current_user:
                is_mgr = True
            elif rec.coach_id and rec._is_user_acting_delegate(current_user, rec.coach_id):
                is_mgr = True
            elif rec.employee_id and rec.employee_id.parent_id and rec.employee_id.sudo().parent_id.user_id == current_user:
                is_mgr = True
            elif rec.employee_id and rec.employee_id.parent_id and rec._is_user_acting_delegate(current_user, rec.employee_id.parent_id):
                is_mgr = True
            rec.is_direct_manager = is_mgr

    @api.depends_context('uid')
    def _compute_is_hr_user(self):
        for rec in self:
            rec.is_hr_user = rec._is_user_acting_hr_manager(self.env.user) or self.env.user.has_group('hr.group_hr_user')

    @api.depends_context('uid')
    def _compute_can_hr_approve(self):
        for rec in self:
            rec.can_hr_approve = rec._is_user_acting_hr_manager(self.env.user)

    @api.depends_context('uid')
    def _compute_can_issue_certificate(self):
        user = self.env.user
        for rec in self:
            rec.can_issue_certificate = (
                rec._is_user_acting_hr_manager(user) or
                user.has_group('hr_resignation.group_pomd_officer') or
                user.has_group('base.group_system')
            )

    def _compute_is_my_team(self):
        current_user = self.env.user
        current_emp = current_user.employee_id
        today = fields.Date.today()
        delegator_emp_ids = set()
        if current_emp:
            delegations = self.env['hr.employee.delegation'].sudo().search([
                ('delegate_id', '=', current_emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            delegator_emp_ids = set(delegations.mapped('employee_id.id'))

        for rec in self:
            is_team = False
            # Check coach
            if rec.coach_id and (rec.coach_id.sudo().user_id == current_user or rec.coach_id.id in delegator_emp_ids):
                is_team = True
            # Check direct manager (parent_id)
            elif rec.employee_id and rec.employee_id.parent_id and (
                rec.employee_id.sudo().parent_id.user_id == current_user or rec.employee_id.parent_id.id in delegator_emp_ids
            ):
                is_team = True
            rec.is_my_team = is_team

    def _search_is_my_team(self, operator, value):
        current_user = self.env.user
        current_emp = current_user.employee_id
        today = fields.Date.today()
        delegator_emp_ids = []
        if current_emp:
            delegations = self.env['hr.employee.delegation'].sudo().search([
                ('delegate_id', '=', current_emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            delegator_emp_ids = delegations.mapped('employee_id.id')

        mgr_emp_ids = ([current_emp.id] if current_emp else []) + delegator_emp_ids

        team_domain = [
            '|', '|', '|',
            ('coach_id.user_id', '=', current_user.id),
            ('employee_id.parent_id.user_id', '=', current_user.id),
            ('coach_id', 'in', mgr_emp_ids),
            ('employee_id.parent_id', 'in', mgr_emp_ids),
        ]

        is_positive = False
        if operator in ('=', '=='):
            is_positive = bool(value)
        elif operator in ('!=', '<>'):
            is_positive = not bool(value)
        elif operator == 'in':
            is_positive = any(value) if hasattr(value, '__iter__') else bool(value)
        elif operator == 'not in':
            is_positive = not any(value) if hasattr(value, '__iter__') else not bool(value)

        if is_positive:
            return team_domain
        else:
            return ['!'] + team_domain
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
    rssa = fields.Float(string='RSSA (Total Loan Taken)', compute='_compute_rssa_info', store=True, readonly=False)
    rssa_od_guarantier = fields.Char(string='RSSA/OD Guarantier', compute='_compute_rssa_info', store=True, readonly=False)
    liability = fields.Float(
        string='Notice Period Liability',
        compute='_compute_liability',
        store=True,
        readonly=True,
        help="It is going to be deducted or he has to pay his one month salary when he does not accept the notice period."
    )

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
            rec.coach_id = emp.coach_id or emp.parent_id
            rec.operating_unit_id = (
                getattr(emp, 'default_operating_unit_id', False)
                or getattr(emp, 'operating_unit_id', False)
                or (emp.department_id.operating_unit_id if emp.department_id and hasattr(emp.department_id, 'operating_unit_id') else False)
            )
            # Forcefully search for the active contract in hr.version to guarantee we find it
            domain = [('employee_id', '=', emp._origin.id if hasattr(emp, '_origin') and emp._origin else emp.id), ('state', 'in', ['open', 'probation'])]
            contract = self.env['hr.version'].sudo().search(domain, limit=1)

            if not contract:
                contract = getattr(emp, 'contract_id', False) or getattr(emp, 'current_version_id', False)
                if not contract:
                    contract = self.env['hr.version'].sudo().search([
                        ('employee_id', '=', emp._origin.id if hasattr(emp, '_origin') and emp._origin else emp.id)
                    ], order='id desc', limit=1)

            rec.current_version_id = contract
            rec.basic_salary = contract.wage if (contract and hasattr(contract, 'wage') and contract.wage) else (getattr(emp, 'wage', 0.0) or 0.0)

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
            if not rec.rssa:
                try:
                    rec._compute_rssa_info()
                except Exception as e:
                    _logger.warning("Error computing RSSA on approval: %s", e)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self._compute_employee_info()
            self._compute_rssa_info()

    def _get_cbs_api_token(self, feature_name="CBS", force_refresh=False):
        """Authenticate with CBS API using the settlement model configuration."""
        Settlement = self.env['hr.resignation.settlement']
        if hasattr(Settlement, '_get_cbs_api_token'):
            return Settlement._get_cbs_api_token(feature_name=feature_name, force_refresh=force_refresh)
        raise UserError(_("CBS authentication method not found in Settlement model."))

    def action_fetch_cbs_rssa(self):
        """Manually re-fetch OD/RSSA loan from CBS API."""
        self._compute_rssa_info()
        return True

    @api.model
    def _is_employee_separated(self, emp):
        """Return True only when BOTH hr.employee is archived and res.users is disabled or absent."""
        if not emp:
            return False
        emp_su = emp.with_context(active_test=False).sudo()
        return (not emp_su.active) and (not emp_su.user_id or not emp_su.user_id.sudo().active)

    @api.model
    def _is_borrower_separated(self, emp):
        """Return True only if employee is actually separated (archived or has a settled/completed resignation)."""
        if not emp:
            return False
        return self._is_employee_separated(emp) or bool(
            self.env['hr.resignation'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', _SEPARATED_RESIGNATION_STATES),
            ], limit=1)
        )

    @api.model
    def _get_employee_partner_id(self, emp):
        """Resolve the best available partner ID for an employee record."""
        if not emp:
            return False
        if emp.user_id and emp.user_id.partner_id:
            return emp.user_id.partner_id.id
        if getattr(emp, 'work_contact_id', False):
            return emp.work_contact_id.id
        if getattr(emp, 'partner_id', False):
            return emp.partner_id.id
        return False

    @api.depends('employee_id')
    def _compute_rssa_info(self):
        for rec in self:
            emp = rec.employee_id
            if not emp:
                rec.rssa = 0.0
                rec.rssa_od_guarantier = ''
                continue
            real_emp_id = emp._origin.id if hasattr(emp, '_origin') and emp._origin else emp.id
            emp_cbs_id = getattr(emp, 'employee_identification', False) or getattr(emp, 'identification_id', False) or ''
            emp_cbs_id = str(emp_cbs_id).strip() if emp_cbs_id else ''
            # 1. Fetch RSSA / Overdraft Loan Balance from CBS API
            rec.rssa = 0.0
            if emp_cbs_id:
                try:
                    base_url, token = self._get_cbs_api_token("OD Loan")
                    fetch_url = f"{base_url.rstrip('/')}/api/cbs/employee-accounts/{emp_cbs_id}"
                    headers = {
                        'Authorization': f'Bearer {token}',
                        'Accept': 'application/json',
                    }
                    resp = requests.get(fetch_url, headers=headers, timeout=(0.5, 1.2))
                    if resp.status_code == 401:
                        base_url, token = self._get_cbs_api_token("OD Loan", force_refresh=True)
                        headers['Authorization'] = f'Bearer {token}'
                        resp = requests.get(fetch_url, headers=headers, timeout=(0.5, 1.2))
                    if resp.status_code == 200:
                        data = resp.json() if resp.content else {}
                        if isinstance(data, dict):
                            od_acc = data.get('od_account') or {}
                            clr_bal = od_acc.get('CLR_BAL_AMT')
                            if clr_bal is not None:
                                try:
                                    bal_float = float(clr_bal)
                                    # Negative (< 0) indicates an outstanding loan debt
                                    if bal_float < 0:
                                        rec.rssa = abs(bal_float)
                                    else:
                                        rec.rssa = 0.0
                                except (ValueError, TypeError):
                                    rec.rssa = 0.0
                except Exception as e:
                    _logger.warning("Failed to fetch CBS OD loan for employee %s: %s", emp_cbs_id, e)
            # 2. Check for loans guaranteed by this employee
            guaranteed_debt = 0.0
            guaranteed_lines = self.env['resl.loan.guarantee'].sudo().search([
                ('guarantor_id', '=', real_emp_id),
                ('state', 'in', ['accepted', 'separated']),
            ])
            for g_line in guaranteed_lines:
                loan = g_line.loan_id
                if not loan:
                    continue
                b_emp = loan.employee_id
                if not b_emp or b_emp.id == real_emp_id:
                    continue
                # Check if borrower is actually separated
                if not self._is_borrower_separated(b_emp):
                    continue
                b_cbs_id = getattr(b_emp, 'employee_identification', False) or getattr(b_emp, 'identification_id', False) or ''
                b_cbs_id = str(b_cbs_id).strip() if b_cbs_id else ''
                b_unpaid = 0.0
                if b_cbs_id:
                    try:
                        base_url, token = self._get_cbs_api_token("OD Loan")
                        b_url = f"{base_url.rstrip('/')}/api/cbs/employee-accounts/{b_cbs_id}"
                        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
                        b_resp = requests.get(b_url, headers=headers, timeout=(0.5, 1.2))
                        if b_resp.status_code == 200:
                            b_data = b_resp.json() if b_resp.content else {}
                            if isinstance(b_data, dict) and b_data.get('status') != 'not_found':
                                b_od = b_data.get('od_account') or {}
                                b_status = str(b_od.get('status', '')).lower()
                                if b_status == 'closed':
                                    b_unpaid = 0.0
                                else:
                                    b_clr = b_od.get('CLR_BAL_AMT')
                                    if b_clr is not None:
                                        b_val = float(b_clr)
                                        if b_val < 0:
                                            b_unpaid = abs(b_val)
                    except Exception as e:
                        _logger.warning("Failed to fetch borrower CBS OD loan for %s: %s", b_cbs_id, e)
                if b_unpaid > 0:
                    live_guarantors = loan.guarantor_line_ids.filtered(
                        lambda l: l.guarantor_id and l.state in ('accepted', 'separated')
                    )
                    # Check guarantor status from hr_employee and res_users:
                    # Resigned only when BOTH employee is archived and user account disabled.
                    unseparated_guarantors = live_guarantors.filtered(
                        lambda l: l.guarantor_id.id == real_emp_id
                        or not self._is_employee_separated(l.guarantor_id)
                    )
                    guarantor_count = len(unseparated_guarantors) or 1
                    g_share = round(b_unpaid / guarantor_count, 2)
                    guaranteed_debt += g_share
            if guaranteed_debt > 0:
                rec.rssa += guaranteed_debt
            # 3. Fetch Guarantors for this employee's loans
            my_loans = self.env['resl.loan'].sudo().search([
                ('employee_id', '=', real_emp_id),
                ('status', 'not in', ['rejected'])
            ])
            info = []
            for l in my_loans.mapped('guarantor_line_ids').filtered(lambda x: x.state in ['pending', 'accepted', 'separated']):
                g = l.guarantor_id
                if not g:
                    continue
                if self._is_employee_separated(g):
                    info.append(f"{g.name} (Resigned)")
                else:
                    info.append(g.name)
            rec.rssa_od_guarantier = ', '.join(sorted(set(info))) if info else 'None'
            # 4. If CBS OD live balance was not found or 0.0, use the approved OD loan from resl.loan module
            if rec.rssa == 0.0 and my_loans:
                resl_loan_total = sum(
                    float(l.approved_amount or l.requested_amount or l.loan_amount or 0.0)
                    for l in my_loans.filtered(
                        lambda l: l.status in ['approved', 'disbursed', 'active']
                        or (hasattr(l, 'core_banking_status') and l.core_banking_status == 'disbursed')
                    )
                )
                if resl_loan_total > 0:
                    rec.rssa = resl_loan_total

    @api.depends('rssa', 'employee_id')
    def _compute_debt_has_rssa(self):
        for rec in self:
            rec.debt_has_rssa = bool(rec.rssa and rec.rssa > 0.0)

    def _get_od_guarantors_info(self):
        """Finds all OD/RSSA guarantors and guaranteed borrowers for this resignation record."""
        self.ensure_one()
        guarantor_partners = []
        guarantor_names = []
        borrower_partners = []
        borrower_names = []
        emp = self.employee_id.sudo()
        if not emp:
            return {
                'guarantor_partners': [],
                'guarantor_names': [],
                'guaranteed_borrower_partners': [],
                'guaranteed_borrower_names': [],
            }

        # 1. Search in resl.loan for active/pending loans of this employee
        if 'resl.loan' in self.env:
            try:
                active_loans = self.env['resl.loan'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('status', 'not in', ['rejected']),
                    ('settlement_status', '!=', 'settled'),
                ])
                for loan in active_loans:
                    for g in loan.guarantor_line_ids:
                        if g.state in ['accepted', 'pending'] and g.guarantor_id and g.guarantor_id.id != emp.id:
                            g_emp = g.guarantor_id
                            if self._is_employee_separated(g_emp):
                                continue
                            guarantor_names.append(g_emp.name)
                            partner_id = self._get_employee_partner_id(g_emp)
                            if partner_id:
                                guarantor_partners.append(partner_id)
            except Exception as e:
                _logger.warning('Error retrieving loan guarantors: %s', e)

        # 2. Also check if rssa_od_guarantier has names
        if self.rssa_od_guarantier and self.rssa_od_guarantier not in ['None', 'none', '']:
            raw_names = [n.strip() for n in self.rssa_od_guarantier.split(',') if n.strip()]
            for name in raw_names:
                matched_emps = self.env['hr.employee'].sudo().search([('name', 'ilike', name)])
                for m_emp in matched_emps:
                    if m_emp.id != emp.id:
                        guarantor_names.append(m_emp.name)
                        partner_id = self._get_employee_partner_id(m_emp)
                        if partner_id:
                            guarantor_partners.append(partner_id)

        # 3. Check loans where this resigning employee is an active guarantor for others
        if 'resl.loan.guarantee' in self.env:
            try:
                guarantees_given = self.env['resl.loan.guarantee'].sudo().search([
                    ('guarantor_id', '=', emp.id),
                    ('state', 'in', ['accepted', 'pending']),
                    ('loan_id.status', 'not in', ['rejected']),
                    ('loan_id.settlement_status', '!=', 'settled'),
                ])
                for g_line in guarantees_given:
                    borrower_emp = g_line.loan_id.employee_id
                    if borrower_emp and borrower_emp.id != emp.id:
                        borrower_names.append(borrower_emp.name)
                        partner_id = self._get_employee_partner_id(borrower_emp)
                        if partner_id:
                            borrower_partners.append(partner_id)
            except Exception as e:
                _logger.warning('Error retrieving loans guaranteed by employee: %s', e)

        return {
            'guarantor_partners': list(set(guarantor_partners)),
            'guarantor_names': list(set(guarantor_names)),
            'guaranteed_borrower_partners': list(set(borrower_partners)),
            'guaranteed_borrower_names': list(set(borrower_names)),
        }

    def _get_external_guarantees_info(self):
        """Retrieve active external guarantees given by this resigning employee.
        Checks guarentees.details (linked to hr.employee) and employee.service.request.
        Returns a list of target descriptions, e.g. ['Aster Aweke (Commercial Bank of Ethiopia)'].
        """
        self.ensure_one()
        emp = self.employee_id
        if not emp:
            return []
        targets = []
        # 1. Check guarentees.details (One2many gurentee_ids on hr.employee)
        try:
            if 'guarentees.details' in self.env:
                recs = self.env['guarentees.details'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('state', '!=', 'inactive'),
                ])
                for g in recs:
                    if getattr(g, 'type', False) and g.type not in ['external', False] and getattr(g, 'type_guarantee', '') not in ['out', 'External', 'external']:
                        continue
                    p_name = (g.external_person_name or (g.name_of_staff.name if g.name_of_staff and g.name_of_staff.id != emp.id else '') or '').strip()
                    org = (g.name_of_institution or '').strip()
                    if p_name and org:
                        targets.append(f"{p_name} ({org})")
                    elif p_name:
                        targets.append(p_name)
                    elif org:
                        targets.append(_("an employee of %s") % org)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Error fetching guarentees.details for %s: %s", emp.name, e)
        # 2. Check employee.service.request for Guarantee Letter
        try:
            if 'employee.service.request' in self.env:
                srs = self.env['employee.service.request'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('letter_name', '=', 'Guarantee Letter'),
                    ('status', 'not in', ['rejected', 'cancelled', 'draft']),
                ])
                for s in srs:
                    p_name = (s.name_of_the_external_person or '').strip()
                    org = (s.name_of_the_organization or '').strip()
                    desc = f"{p_name} ({org})" if p_name and org else (p_name or (_("an employee of %s") % org if org else ""))
                    if desc and desc not in targets:
                        targets.append(desc)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Error fetching employee.service.request guarantees for %s: %s", emp.name, e)
        return list(dict.fromkeys(targets))

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
        if self.initiated_by == 'employee':
            self.application_date = fields.Date.context_today(self)
            # Auto-populate Voluntary Resignation when initiated by employee
            if not self.resignation_type_id or self.resignation_type_id.is_company_terminated:
                vol_type = self.env['hr.separation.type'].search([('code', '=', 'voluntary')], limit=1)
                self.resignation_type_id = vol_type.id if vol_type else False
        elif self.initiated_by == 'company':
            # Clear if it was set to an employee-initiated voluntary type
            if self.resignation_type_id and not self.resignation_type_id.is_company_terminated:
                self.resignation_type_id = False

    # ── Dates ─────────────────────────────────────────────────────────
    application_date = fields.Date(
        default=fields.Date.context_today,
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

    @api.onchange('release_date')
    def _onchange_release_date(self):
        for rec in self:
            if not rec.bypass_handover and rec.expected_last_day and rec.release_date and rec.state in ('approved', 'handover_completed'):
                today = fields.Date.today()
                if rec.release_date == rec.expected_last_day and today != rec.expected_last_day:
                    return {
                        'warning': {
                            'title': _("Invalid Release Date"),
                            'message': _(
                                "The Release Date can only be set to the Expected Last Day (%s) on that actual date. "
                                "Current date must be that date.\n\n"
                                "If the employee is being released on a different date, please enter that specific date "
                                "and provide the Release Date Justification."
                            ) % rec.expected_last_day
                        }
                    }

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
    ], default='draft', copy=False, index=True)

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
    settlement_id = fields.Many2one('hr.resignation.settlement', readonly=True, index=True)
    letter_log_ids = fields.One2many(
        'hr.resignation.letter.log',
        'resignation_id',
        string='Printed Letters Log'
    )
    letter_log_count = fields.Integer(
        string='Printed Letters Count',
        compute='_compute_letter_log_count'
    )

    @api.depends('letter_log_ids')
    def _compute_letter_log_count(self):
        for rec in self:
            rec.letter_log_count = len(rec.letter_log_ids)

    def action_view_printed_letters(self):
        self.ensure_one()
        return {
            'name': _('Printed Letters & Documents'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.resignation.letter.log',
            'view_mode': 'list,form',
            'domain': [('resignation_id', '=', self.id)],
            'context': {'default_resignation_id': self.id},
        }

    # ── Related fields from exit interview (inline display on form) ──
    exit_interview_date = fields.Date(related='exit_interview_id.interview_date', readonly=True, related_sudo=True)
    exit_interview_state = fields.Selection(related='exit_interview_id.state', string='Interview Status', readonly=True, related_sudo=True)
    exit_interview_line_ids = fields.One2many(related='exit_interview_id.line_ids', string='Exit Interview Responses', readonly=True)
    has_active_exit_template = fields.Boolean(
        string='Has Active Exit Template',
        compute='_compute_has_active_exit_template',
    )
    exit_interview_template_id = fields.Many2one(
        'hr.exit.interview.template',
        string='Questionnaire Template',
        compute='_compute_exit_interview_template_id',
        readonly=True,
    )

    def _get_active_exit_interview_template(self):
        """Return the single active exit interview template based on priority:
        1. Resignation Separation Type's template (if set and active).
        2. Top active template from hr.exit.interview.template (order: sequence, name, id).
        3. False if no active template exists.
        """
        self.ensure_one()
        sep_template = self.resignation_type_id.exit_interview_template_id if self.resignation_type_id else False
        if sep_template and sep_template.active:
            return sep_template
        return self.env['hr.exit.interview.template'].sudo().search(
            [('active', '=', True)], order='sequence, name, id', limit=1
        )

    def _compute_has_active_exit_template(self):
        for rec in self:
            template = rec._get_active_exit_interview_template()
            rec.has_active_exit_template = bool(template)

    def _compute_exit_interview_template_id(self):
        for rec in self:
            active_template = rec._get_active_exit_interview_template()
            if rec.exit_interview_id and rec.exit_interview_id.state == 'completed':
                rec.exit_interview_template_id = rec.exit_interview_id.template_id
            else:
                rec.exit_interview_template_id = active_template or (rec.exit_interview_id.template_id if rec.exit_interview_id else False)
    can_view_exit_interview = fields.Boolean(compute='_compute_can_view_exit_interview')

    @api.depends_context('uid')
    def _compute_can_view_exit_interview(self):
        is_hr = (
            self.env.user.has_group('hr_resignation.group_resignation_hr_manager') or
            self.env.user.has_group('hr.group_hr_user')
        )
        is_admin = (
            self.env.user.has_group('base.group_system') or
            self.env.user.has_group('hr_resignation.group_resignation_admin')
        )
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_auditor = self.env.user.has_group('hr_resignation.group_resignation_auditor')
        for rec in self:
            is_employee = (rec.employee_id.sudo().user_id == self.env.user)
            # The resigning employee, HR, Pomd, auditor, and admin can view the exit interview section
            rec.can_view_exit_interview = is_employee or is_hr or is_admin or is_pomd or is_auditor
    show_release_date_to_employee = fields.Boolean(compute='_compute_show_release_date_to_employee')

    @api.depends('state', 'release_date', 'resignation_type_id', 'bypass_handover')
    def _compute_show_release_date_to_employee(self):
        for rec in self:
            is_hr = rec.can_hr_approve or self.env.user.has_group('hr.group_hr_user')
            is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
            is_manager = rec.is_current_manager
            is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')

            if rec.bypass_handover:
                # Always show release date for termination types
                rec.show_release_date_to_employee = True
            elif rec.state in ('draft', 'submitted'):
                # Hidden from employee during early stages for voluntary & non-termination
                rec.show_release_date_to_employee = bool(is_hr or is_admin or is_manager or is_pomd)
            elif rec.state in ('approved', 'handover_completed'):
                # Only HR / Admin / Manager / POMD can see and set it
                rec.show_release_date_to_employee = bool(is_hr or is_admin or is_manager or is_pomd)
            else:
                # release_date_set and beyond — visible to everyone including employee
                rec.show_release_date_to_employee = True

    can_edit_handover = fields.Boolean(compute='_compute_can_edit_handover')
    show_handover_tab = fields.Boolean(compute='_compute_show_handover_tab')

    @api.depends_context('uid')
    @api.depends('state', 'employee_id', 'coach_id')
    def _compute_show_handover_tab(self):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        for rec in self:
            is_employee = bool(rec.employee_id and rec.employee_id.sudo().user_id == self.env.user)
            is_manager = rec.is_current_manager

            # Never visible in early draft/submitted states
            if rec.state in ('draft', 'submitted'):
                rec.show_handover_tab = False
            # Handover tab is strictly for the manager / HR / POMD / admin, not for the resigning employee
            elif is_employee and not is_admin:
                rec.show_handover_tab = False
            else:
                rec.show_handover_tab = bool(is_manager or is_hr or is_pomd or is_admin)

    @api.depends_context('uid')
    @api.depends('state', 'coach_id', 'employee_id')
    def _compute_can_edit_handover(self):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        for rec in self:
            is_employee = bool(rec.employee_id and rec.employee_id.sudo().user_id == self.env.user)
            is_manager = rec.is_current_manager

            # The resigning employee must NEVER be able to edit manager handover
            if is_employee and not is_admin:
                rec.can_edit_handover = False
            else:
                rec.can_edit_handover = bool(
                    (rec.state in ('approved', 'handover_completed', 'release_date_set'))
                    and (is_manager or is_hr or is_pomd or is_admin)
                )

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

    has_no_payment_configured = fields.Boolean(
        compute='_compute_has_no_payment_configured',
        string='Has No Payment Configured'
    )

    @api.depends('resignation_type_id', 'allow_salary_payment', 'allow_leave_encashment', 'show_severance_pay', 'show_pf_payment')
    def _compute_has_no_payment_configured(self):
        for rec in self:
            if not rec.resignation_type_id:
                rec.has_no_payment_configured = False
            else:
                has_any = (
                    rec.allow_salary_payment
                    or rec.allow_leave_encashment
                    or rec.show_severance_pay
                    or rec.show_pf_payment
                )
                rec.has_no_payment_configured = not has_any

    @api.depends('resignation_type_id')
    def _compute_payment_requests(self):
        for rec in self:
            st = rec.resignation_type_id
            rec.payment_request_unpaid_salary = bool(st and st.allow_salary_payment)
            rec.payment_request_leave_pay = bool(st and st.allow_leave_encashment)
            rec.payment_request_severance = bool(st and st.pays_severance)
            rec.payment_request_pf = bool(st and st.pays_provident_fund)

    payment_request_leave_pay = fields.Boolean(
        string='Accrued leave pay',
        compute='_compute_payment_requests', store=True, readonly=False, precompute=True,
        help='Request payment for unutilized/accrued annual leave.')
    payment_request_unpaid_salary = fields.Boolean(
        string='Remaining salary',
        compute='_compute_payment_requests', store=True, readonly=False, precompute=True,
        help='Request payment of any salary remaining for the current period.')
    payment_request_severance = fields.Boolean(
        string='Severance pay',
        compute='_compute_payment_requests', store=True, readonly=False, precompute=True,
        help='Request severance pay where applicable.')
    payment_request_pf = fields.Boolean(
        string='PF',
        compute='_compute_payment_requests', store=True, readonly=False, precompute=True,
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
        compute='_compute_debt_has_rssa', store=True, readonly=False,
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
        default=True,
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
    warning_commitment_count = fields.Integer(compute='_compute_validation_warnings')
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

    @api.depends('employee_id', 'resignation_type_id')
    def _compute_validation_warnings(self):
        today = fields.Date.today()
        for rec in self:
            emp = rec.employee_id
            sep_type = rec.resignation_type_id

            d_count, c_count = 0, 0
            if emp and sep_type:
                # 1. Active Disciplinary Cases from discipline_management
                if sep_type.check_disciplinary and 'discipline.case' in self.env:
                    d_count = self.env['discipline.case'].sudo().search_count([
                        ('employee_id', '=', emp.id),
                        ('state', 'not in', ('closed', 'revoked')),
                    ])

                # 2. Contractual Commitments from employee_development_system (EDS)
                if sep_type.check_commitments:
                    if 'training.commitment' in self.env:
                        c_count += self.env['training.commitment'].sudo().search_count([
                            ('commitment_id', '=', emp.id),
                            '|',
                            ('state', '=', 'active'),
                            '&',
                            ('state', '!=', 'cancelled'),
                            ('end_date', '>=', today),
                        ])
                    if 'eds.enrollment' in self.env:
                        c_count += self.env['eds.enrollment'].sudo().search_count([
                            ('employee_id', '=', emp.id),
                            ('session_id.commitment_required', '=', True),
                            ('session_id.status', 'in', ('scheduled', 'ongoing')),
                            ('state', 'in', ('draft', 'submitted', 'line_manager_approved', 'lnd_approved', 'approved')),
                        ])
                    if 'education.fee.sponsorship' in self.env:
                        c_count += self.env['education.fee.sponsorship'].sudo().search_count([
                            ('sponsorship_id', '=', emp.id),
                            ('end_date', '>=', today),
                        ])

            rec.warning_disciplinary_count = d_count
            rec.warning_commitment_count = c_count

    def action_open_disciplinary_cases(self):
        self.ensure_one()
        return {
            'name': _('Active Disciplinary Cases'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('state', 'not in', ['closed', 'revoked'])],
            'context': {'create': False, 'edit': False},
        }

    def action_open_training_commitments(self):
        self.ensure_one()
        return {
            'name': _('Active Contractual Commitments'),
            'type': 'ir.actions.act_window',
            'res_model': 'training.commitment',
            'view_mode': 'list,form',
            'domain': [('commitment_id', '=', self.employee_id.id)],
            'context': {'create': False, 'edit': False},
        }

    def _sync_employee_resignation_fields(self):
        """Synchronize resignation status, remarks (separation type), and approved date to hr.employee."""
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            if not emp:
                continue
            vals = {}
            # 1. resignation_status (matches resignation state)
            if hasattr(emp, 'resignation_status'):
                vals['resignation_status'] = rec.state if rec.state != 'draft' else False
            # 2. resignation_remarks = separation type name
            if hasattr(emp, 'resignation_remarks'):
                vals['resignation_remarks'] = rec.resignation_type_id.name if rec.resignation_type_id else False
            # 3. resignation_approved_date (set on approval, cleared on draft/returned/revoked)
            if hasattr(emp, 'resignation_approved_date'):
                approved_states = (
                    'approved', 'release_date_set', 'handover_completed',
                    'clearance_in_progress', 'cleared', 'settled', 'completed'
                )
                if rec.state in approved_states:
                    if not emp.resignation_approved_date:
                        vals['resignation_approved_date'] = fields.Date.today()
                elif rec.state in ('draft', 'submitted', 'revoked', 'returned'):
                    vals['resignation_approved_date'] = False
            if vals:
                emp.write(vals)

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
                vals['application_date'] = fields.Date.context_today(self)
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
        for rec in records:
            if rec.state != 'draft':
                rec._sync_employee_resignation_fields()
        return records

    def write(self, vals):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')

        if not (is_hr or is_pomd or is_admin):
            vals.pop('initiated_by', None)
            vals.pop('employee_id', None)
            for rec in self:
                if rec.state != 'draft' and rec.initiated_by == 'employee' and 'application_date' in vals:
                    vals.pop('application_date', None)

        if 'release_date' in vals:
            for rec in self:
                is_hr = rec.can_hr_approve or self.env.user.has_group('hr.group_hr_user')
                is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
                is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
                is_direct_manager = rec.is_current_manager
                if not (is_hr or is_pomd or is_admin or is_direct_manager):
                    raise UserError(_('Only the employee\'s Direct Manager, an authorized delegate, or HR can set the Actual Last Day.'))

                new_rel_date = fields.Date.to_date(vals.get('release_date'))
                if new_rel_date and not rec.bypass_handover and rec.state in ('approved', 'handover_completed'):
                    today = fields.Date.today()
                    if rec.expected_last_day and new_rel_date == rec.expected_last_day and today != rec.expected_last_day:
                        raise UserError(_(
                            'The Release Date can only be set to the Expected Last Day (%s) on that actual date. '
                            'Current date must be that date.\n\n'
                            'If the employee is being released on a different date, please set that specific date '
                            'and provide the Release Date Justification.'
                        ) % rec.expected_last_day)

        res = super(HrResignation, self).write(vals)
        if any(f in vals for f in ('state', 'resignation_type_id', 'employee_id')):
            self._sync_employee_resignation_fields()
        return res

    def unlink(self):
        employees = self.mapped('employee_id')
        for rec in self:
            if rec.state not in ('draft', 'returned', 'revoked'):
                raise UserError(_('You can only delete draft or cancelled resignation requests.'))
        res = super().unlink()
        for emp in employees:
            if hasattr(emp, 'resignation_status'):
                emp.sudo().write({
                    'resignation_status': False,
                    'resignation_approved_date': False,
                    'resignation_remarks': False,
                })
        return res

    # ==================================================================
    # WORKFLOW ACTIONS
    # ==================================================================

    @api.depends('coach_id', 'employee_id')
    def _compute_is_current_manager(self):
        current_user = self.env.user
        for rec in self:
            is_mgr = False
            if rec.coach_id and rec.coach_id.sudo().user_id == current_user:
                is_mgr = True
            elif rec.coach_id and rec._is_user_acting_delegate(current_user, rec.coach_id):
                is_mgr = True
            elif rec.employee_id and rec.employee_id.parent_id and rec.employee_id.sudo().parent_id.user_id == current_user:
                is_mgr = True
            elif rec.employee_id and rec.employee_id.parent_id and rec._is_user_acting_delegate(current_user, rec.employee_id.parent_id):
                is_mgr = True
            rec.is_current_manager = is_mgr

    def action_submit(self):
        for rec in self:
            if not rec.rssa:
                try:
                    rec._compute_rssa_info()
                except Exception as e:
                    _logger.warning("Error computing RSSA on approval: %s", e)
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if not rec.resignation_type_id:
                raise UserError(_('Separation Type is required.'))
            if not rec.employee_id:
                raise UserError(_('Employee is required.'))

            # Explicitly trigger constraints on submit
            rec._check_initiated_by_type()

            if not rec.application_date:
                raise UserError(_('Resignation Applied Date is required.'))
            if not rec.application_date or rec.application_date < fields.Date.today():
                rec.sudo().write({'application_date': fields.Date.today()})

            if rec.bypass_handover:
                if not rec.release_date:
                    raise UserError(_('For this separation type, both Resignation Applied Date and Release Date are mandatory and must be set by HR/POMD when creating the form.'))
                if rec.release_date < rec.application_date:
                    raise UserError(_('Release Date cannot be earlier than Resignation Applied Date.'))

            if rec.notice_period > 0 and not rec.notice_period_accepted:
                raise UserError(_('You must specify if you accept the Notice Period before submitting your resignation.'))
            rec.name = self.env['ir.sequence'].sudo().next_by_code('hr.resignation') or _('New')
            # Validate Payment Request Declaration
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
                            mgr_subj = 'New Employee Separation: %s' % emp_name
                            mgr_body = 'HR has initiated a %s separation process for %s (%s).' % (sep_type_name, emp_name, ref)

                            hr_subj = 'New Company-Initiated Separation for HR Approval: %s' % emp_name
                            hr_body = 'A company-initiated separation (%s) has been drafted for %s (%s) and is awaiting your approval.' % (sep_type_name, emp_name, ref)

                            emp_subj = 'Separation Process Initiated: %s' % ref
                            emp_body = 'Dear %s,\n\nA company-initiated separation process (%s) has been formally initiated for you (%s). Please await further instructions from HR.' % (emp_name, sep_type_name, ref)
                        else:
                            mgr_subj = 'New Resignation Request: %s' % emp_name
                            mgr_body = '%s has submitted a resignation request (%s).' % (emp_name, ref)

                            hr_subj = 'New Resignation Request for HR Approval: %s' % emp_name
                            hr_body = '%s has submitted a resignation request (%s) and it is awaiting HR Manager approval.' % (emp_name, ref)

                            emp_subj = 'Resignation Request Submitted: %s' % ref
                            emp_body = 'Dear %s,\n\nYour resignation request (%s) has been successfully submitted and is now pending HR Review.' % (emp_name, ref)

                        # 1. OD / RSSA Guarantors (Guarantors who guaranteed this employee)
                        od_info = rec2._get_od_guarantors_info()
                        if od_info['guarantor_partners']:
                            od_subj = 'Separation of OD/RSSA Loanee: %s' % emp_name if is_company else 'Resignation of OD/RSSA Loanee: %s' % emp_name
                            od_body = (
                                'Dear Guarantor,\n\n'
                                'This is to inform you that %s has submitted a resignation request (%s).\n\n'
                                'As an active OD/RSSA Guarantor for this employee, please be advised that the borrower '
                                'has initiated separation from the Bank. Outstanding OD loan balances and guarantee '
                                'commitments must be settled in accordance with Bank procedures.'
                            ) % (emp_name, ref)
                            rec2._send_notification(
                                partner_ids=od_info['guarantor_partners'],
                                subject=od_subj,
                                body=od_body,
                            )
                            rec2.message_post(
                                body='Notification sent to OD Guarantor(s): %s' % ', '.join(od_info['guarantor_names'])
                            )

                        # 1b. Borrowers of loans guaranteed by the resigning employee
                        if od_info['guaranteed_borrower_partners']:
                            b_subj = 'OD/RSSA Guarantee Notice: Guarantor %s Has Submitted Resignation' % emp_name
                            b_body = (
                                'Dear Loanee,\n\n'
                                'Your OD/RSSA loan guarantor, %s, has submitted a resignation request (%s).\n\n'
                                'Because your loan requires an active guarantor, you are required to arrange for a '
                                'replacement guarantor in accordance with the Bank\'s staff loan procedures.'
                            ) % (emp_name, ref)
                            rec2._send_notification(
                                partner_ids=od_info['guaranteed_borrower_partners'],
                                subject=b_subj,
                                body=b_body,
                            )
                            rec2.message_post(
                                body='Notification sent to Borrowers guaranteed by resigning employee: %s' % ', '.join(od_info['guaranteed_borrower_names'])
                            )

                        # 2. Manager & Active Delegates
                        manager = rec2.coach_id or (rec2.employee_id and rec2.employee_id.parent_id)
                        if manager and manager.user_id:
                            mgr_partners = list(manager.user_id.partner_id.ids)
                            del_users = rec2._get_active_delegates_for_employee(manager)
                            if del_users:
                                mgr_partners.extend(del_users.mapped('partner_id').ids)
                            rec2._send_notification(
                                partner_ids=list(set(mgr_partners)),
                                subject=mgr_subj,
                                body=mgr_body,
                            )

                        # 3. Notification for HR Approval & Active HR Delegates (If still submitted and not auto-approved)
                        if rec2.state == 'submitted':
                            hr_manager_ref = env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
                            hr_managers = hr_manager_ref.sudo().user_ids.filtered(lambda u: u.active) if hr_manager_ref else env['res.users'].sudo()
                            hr_manager_partners = list(hr_managers.mapped('partner_id').ids)
                            for hr_u in hr_managers:
                                if hr_u.employee_id:
                                    hr_del_users = rec2._get_active_delegates_for_employee(hr_u.employee_id)
                                    if hr_del_users:
                                        hr_manager_partners.extend(hr_del_users.mapped('partner_id').ids)

                            if hr_manager_partners:
                                rec2._send_notification(
                                    partner_ids=list(set(hr_manager_partners)),
                                    subject=hr_subj,
                                    body=hr_body,
                                )

                        # 4. POMD Officers — always informed of every new submission
                        pomd_ref = env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
                        if pomd_ref:
                            pomd_partners = pomd_ref.sudo().user_ids.filtered(lambda u: u.active).mapped('partner_id').ids
                            if pomd_partners:
                                if is_company:
                                    pomd_subj = 'New Separation Request: %s' % emp_name
                                    pomd_body = 'A company-initiated separation (%s) has been submitted for %s (%s) and is awaiting HR Manager approval.' % (sep_type_name, emp_name, ref)
                                else:
                                    pomd_subj = 'New Resignation Request: %s' % emp_name
                                    pomd_body = '%s has submitted a resignation request (%s) and it is awaiting HR Manager approval.' % (emp_name, ref)
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
        if not self._is_user_acting_hr_manager(self.env.user):
            raise UserError(_('Only HR Manager or an authorized acting delegate can approve resignation requests.'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved.'))
            if not rec.rssa:
                try:
                    rec._compute_rssa_info()
                except Exception as e:
                    _logger.warning("Error computing RSSA on approval: %s", e)

            # Pre-separation checks: advisory only (displayed in red before approval, non-blocking)
            sep_type = rec.resignation_type_id
            if sep_type:
                approval_notes = []
                if sep_type.check_disciplinary and rec.warning_disciplinary_count > 0:
                    approval_notes.append(_("Notice: Approved with %d active disciplinary case(s).") % rec.warning_disciplinary_count)
                if sep_type.check_commitments and rec.warning_commitment_count > 0:
                    approval_notes.append(_("Notice: Approved with %d active training/educational commitment(s).") % rec.warning_commitment_count)
                if approval_notes:
                    rec.message_post(body="<br/>".join(approval_notes))

            rec.state = 'approved'

            # Post audit note if approved by an acting delegate
            acting_hr_del = rec._get_acting_hr_delegation(self.env.user)
            if acting_hr_del:
                rec.message_post(
                    body=_(
                        "<p><strong>Approved via HR Delegation</strong><br/>"
                        "Approved by acting delegate <strong>%(delegate)s</strong> on behalf of HR Manager <strong>%(manager)s</strong> "
                        "under Delegation Reference <strong>%(ref)s</strong>.</p>"
                    ) % {
                        'delegate': self.env.user.name,
                        'manager': acting_hr_del.employee_id.name,
                        'ref': acting_hr_del.name,
                    }
                )

            # Update the flag on the contract
            if rec.current_version_id and hasattr(rec.current_version_id, 'has_approved_resignation'):
                rec.current_version_id.has_approved_resignation = True

            emp_user = rec.employee_id.sudo().user_id
            emp_name = rec.employee_id.sudo().name or ''
            rec_name = rec.name or ''
            req_lines = []
            # Assign exit interview only for employee-initiated separations (excluded for company-initiated)
            if not rec.is_company_terminated:
                template = rec._get_active_exit_interview_template()
                if template:
                    if not rec.exit_interview_id:
                        interview = self.env['hr.exit.interview'].sudo().create({
                            'resignation_id': rec.id,
                            'employee_id': rec.employee_id.id,
                            'template_id': template.id,
                        })
                        rec.exit_interview_id = interview
                    if rec.exit_interview_id and not rec.exit_interview_waived:
                        # Schedule an activity for the employee to complete the exit interview
                        if emp_user:
                            rec.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=emp_user.id,
                                note=_('Please complete your exit interview.'),
                            )
                        req_lines.append(
                            _('Exit Interview: Please complete the exit interview as a mandatory part of the resignation process.')
                        )
                else:
                    # No active template configured -> automatically waive exit interview so employee is not asked and workflow is not blocked
                    rec.exit_interview_waived = True
            numbered_reqs = "\n".join(f"{idx}. {line}" for idx, line in enumerate(req_lines, start=1))
            body_msg = _(
                "Dear %(emp_name)s,\n\n"
                "This is to inform you that your resignation request (%(rec_name)s) has been formally approved by People Operation Management Directorate.\n\n"
                "To facilitate the completion of your separation process, please ensure that the following requirements are fulfilled:\n"
                "%(requirements)s"
            ) % {
                'emp_name': emp_name,
                'rec_name': rec_name,
                'requirements': numbered_reqs,
            }
            if emp_user and emp_user.partner_id:
                rec._send_notification(
                    partner_ids=emp_user.partner_id.ids,
                    subject=_('Your Resignation Has Been Approved: %s') % rec_name,
                    body=body_msg,
                )
            # Notify OD Guarantors & Guaranteed Borrowers upon HR Approval
            od_info = rec._get_od_guarantors_info()
            if od_info['guarantor_partners']:
                g_subj = _('Resignation Approved for OD/RSSA Loanee: %s') % emp_name
                g_body = _(
                    'Dear Guarantor,\n\n'
                    'The resignation request (%s) for %s has been formally approved by People Operation Management Directorate.\n\n'
                    'As an active OD/RSSA Guarantor for this employee, please be advised that the separation and clearance '
                    'process is now in progress. Outstanding OD balances and guarantee releases must be settled in '
                    'accordance with the Bank\'s procedures before final release.'
                ) % (rec_name, emp_name)
                rec._send_notification(
                    partner_ids=od_info['guarantor_partners'],
                    subject=g_subj,
                    body=g_body,
                )
                rec.message_post(
                    body=_('Approval notification sent to OD Guarantor(s): %s') % ', '.join(od_info['guarantor_names'])
                )

            if od_info['guaranteed_borrower_partners']:
                b_subj = _('Urgent: Guarantor Resignation Approved for %s — Replacement Required') % emp_name
                b_body = _(
                    'Dear Loanee,\n\n'
                    'The resignation request (%s) for %s has been formally approved by People Operation Management Directorate.\n\n'
                    'Since %s is an active guarantor for your OD/RSSA loan, you are required to immediately arrange '
                    'for a replacement guarantor in accordance with the Bank\'s procedures.'
                ) % (rec_name, emp_name, emp_name)
                rec._send_notification(
                    partner_ids=od_info['guaranteed_borrower_partners'],
                    subject=b_subj,
                    body=b_body,
                )
                rec.message_post(
                    body=_('Approval notification sent to Borrowers guaranteed by resigning employee: %s') % ', '.join(od_info['guaranteed_borrower_names'])
                )

            # Notify the direct manager & active delegate
            manager = rec.coach_id or (rec.employee_id and rec.employee_id.parent_id)
            manager_user = manager.sudo().user_id if manager else False
            if manager_user and manager_user.active:
                mgr_partners = list(manager_user.partner_id.ids)
                del_users = rec._get_active_delegates_for_employee(manager)
                if del_users:
                    mgr_partners.extend(del_users.mapped('partner_id').ids)
                rec._send_notification(
                    partner_ids=list(set(mgr_partners)),
                    subject=_('Resignation Approved — Please Complete Handover / Set Release Date: %s') % emp_name,
                    body=_(
                        'The resignation request (%s) for %s has been approved by HR. '
                        'Please open the record and proceed with Handover notes and Release Date.'
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

            if rec.bypass_handover:
                # Bypass the handover wait completely for separation types configured to bypass handover
                rec.action_complete_handover()
        rec = self[:1]
        ref = rec.name if rec else ''
        return self._show_success_message(_("Resignation request %(ref)s has been successfully approved! Next step: Handover & Clearance.") % {'ref': ref})

    def action_set_release_date(self):
        for rec in self:
            if not (rec.is_current_manager or rec.can_hr_approve or self.env.user.has_group('base.group_system')):
                raise UserError(_('Only the Direct Manager, an authorized delegate, or HR can set the Release Date.'))
            if rec.bypass_handover:
                raise UserError(_('Release Date for this separation type is set by HR/POMD during initiation.'))
            if rec.state != 'handover_completed':
                raise UserError(_('Can only set Release Date after the Handover is completed.'))
            if not rec.release_date:
                raise UserError(_('Please specify the Release Date before confirming.'))

            if rec.release_date < fields.Date.today():
                raise UserError(_('Release Date cannot be in the past. Backdating is invalid.'))

            # today = fields.Date.today()
            # if not rec.bypass_handover and rec.expected_last_day:
            #     if rec.release_date != rec.expected_last_day and not rec.release_date_justification:
            #         raise UserError(_('Because the Release Date differs from the Expected Last Day, you must provide a justification.'))
            #     if rec.release_date == rec.expected_last_day and today != rec.expected_last_day:
            #         raise UserError(_(
            #             'The Release Date can only be set to the Expected Last Day (%s) on that actual date. '
            #             'Current date must be that date.\n\n'
            #             'If the employee is being released on a different date, please set that specific date '
            #             'and provide the Release Date Justification.'
            #         ) % rec.expected_last_day)

            # Validation for exit interview at release date (only for employee-initiated)
            if not rec.is_company_terminated and rec.initiated_by != 'company' and not rec.exit_interview_waived and rec.has_active_exit_template and (not rec.exit_interview_id or rec.exit_interview_id.sudo().state != 'completed'):
                raise UserError(_('The employee must complete the exit interview before the Release Date can be set.'))

            rec.state = 'clearance_in_progress'

            # Audit trail if executed by acting delegate
            acting_mgr_del = rec._get_acting_delegation(self.env.user, rec.coach_id or (rec.employee_id and rec.employee_id.parent_id))
            if acting_mgr_del:
                rec.message_post(
                    body=_(
                        "<p><strong>Release Date Set via Delegation</strong><br/>"
                        "Release Date (%(date)s) set by acting delegate <strong>%(delegate)s</strong> on behalf of Direct Manager <strong>%(manager)s</strong> "
                        "under Delegation Reference <strong>%(ref)s</strong>.</p>"
                    ) % {
                        'date': rec.release_date,
                        'delegate': self.env.user.name,
                        'manager': acting_mgr_del.employee_id.name,
                        'ref': acting_mgr_del.name,
                    }
                )

            # Notify ONLY HR Officers and HR Manager (strictly no employee or general users)
            hr_partners = []
            hr_manager_ref = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
            if hr_manager_ref:
                hr_partners.extend(hr_manager_ref.sudo().user_ids.mapped('partner_id').ids)
            hr_group_ref = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
            if hr_group_ref:
                hr_partners.extend(hr_group_ref.sudo().user_ids.mapped('partner_id').ids)
            pomd_ref = self.env.ref('hr_resignation.group_pomd_officer', raise_if_not_found=False)
            if pomd_ref:
                hr_partners.extend(pomd_ref.sudo().user_ids.mapped('partner_id').ids)
            if hr_partners:
                rec._send_notification(
                    partner_ids=list(set(hr_partners)),
                    subject=_('Release Date Set for %s') % rec.employee_id.sudo().name,
                    body=_('The Release Date for %s has been set to %s. Handover and clearance processing can now proceed.')
                          % (rec.employee_id.sudo().name, rec.release_date)
                )

            # Create clearance lines
            rec._create_clearance_lines()

            # Notify clearance units & active delegates
            for line in rec.clearance_line_ids:
                if line.responsible_user and line.responsible_user.partner_id:
                    line_partners = list(line.responsible_user.partner_id.ids)
                    if line.responsible_user.employee_id:
                        del_users = rec._get_active_delegates_for_employee(line.responsible_user.employee_id)
                        if del_users:
                            line_partners.extend(del_users.mapped('partner_id').ids)
                    rec._send_notification(
                        partner_ids=list(set(line_partners)),
                        subject=_('Clearance Action Required: %s') % rec.employee_id.sudo().name,
                        body=_('The Release Date for %s is set to %s. You may now begin clearance processing.')
                             % (rec.employee_id.sudo().name, rec.release_date)
                    )
        return self._show_success_message(_("Release Date successfully recorded! Clearance processing is now in progress."))

    def action_complete_handover(self):
        for rec in self:
            if not (rec.is_current_manager or rec.can_hr_approve or self.env.user.has_group('base.group_system')):
                raise UserError(_('Only the Direct Manager, an authorized delegate, or HR can complete the handover.'))
            if rec.state != 'approved':
                raise UserError(_('Handover can only be completed after HR approval.'))

            # Just require the text field to have something in it (strip HTML tags)
            from odoo.tools import html2plaintext
            if not rec.bypass_handover and (not rec.handover_notes or not html2plaintext(rec.handover_notes).strip()):
                raise UserError(_('Handover Notes are required.'))

            rec.state = 'handover_completed'

            # Audit trail if executed by acting delegate
            acting_mgr_del = rec._get_acting_delegation(self.env.user, rec.coach_id or (rec.employee_id and rec.employee_id.parent_id))
            if acting_mgr_del:
                rec.message_post(
                    body=_(
                        "<p><strong>Handover Completed via Delegation</strong><br/>"
                        "Handover notes recorded and completed by acting delegate <strong>%(delegate)s</strong> on behalf of Direct Manager <strong>%(manager)s</strong> "
                        "under Delegation Reference <strong>%(ref)s</strong>.</p>"
                    ) % {
                        'delegate': self.env.user.name,
                        'manager': acting_mgr_del.employee_id.name,
                        'ref': acting_mgr_del.name,
                    }
                )

            # --- USER REQUEST: Create clearance lines & Notify on handover complete ---
            if not rec.clearance_line_ids:
                rec._create_clearance_lines()

            if rec.bypass_handover:
                # Bypass action_set_release_date validations for separation types where HR sets release date
                # since HR already set the release date during creation.
                rec.state = 'clearance_in_progress'
        return self._show_success_message(_("Handover has been marked as completed successfully!"))

    def action_complete_exit_interview(self):
        self.ensure_one()
        if not self.can_view_exit_interview:
            raise UserError(_('Exit interviews are strictly confidential and accessible only to HR, POMD, and the resigning employee.'))
        active_template = self._get_active_exit_interview_template()
        if not self.exit_interview_id:
            if not active_template:
                raise UserError(_('No active exit interview template is currently available in the system. Please contact HR.'))
            interview = self.env['hr.exit.interview'].sudo().create({
                'resignation_id': self.id,
                'employee_id': self.employee_id.id,
                'template_id': active_template.id,
            })
            self.exit_interview_id = interview
        else:
            # If the interview exists in draft state and the active template changed or was deactivated,
            # dynamically switch the draft interview to the currently active template so the employee answers the active questions!
            if self.exit_interview_id.state == 'draft' and active_template and self.exit_interview_id.template_id != active_template:
                self.exit_interview_id.sudo().write({'template_id': active_template.id})
            elif self.exit_interview_id.state == 'draft' and not active_template and not self.exit_interview_id.template_id.active:
                raise UserError(_('The exit interview template has been deactivated and no alternative active template is configured. Please contact HR.'))
        return self.exit_interview_id.action_open_interview()

    def action_mark_exit_interviewed(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Please wait for HR Approval first.'))

            rec._check_and_advance_cleared()
        return self._show_success_message(_('Exit interview marked as completed.'))

    def action_waive_exit_interview(self):
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_auditor = self.env.user.has_group('hr_resignation.group_resignation_auditor')
        if not (is_pomd or is_auditor or is_hr):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager (or authorized delegate) can waive the exit interview.'))
        for rec in self:
            if rec.state not in ('approved', 'release_date_set', 'clearance_in_progress'):
                raise UserError(_('Please wait for HR Approval first before waiving exit interview.'))
            rec.exit_interview_waived = True
            rec.message_post(body=_("Exit Interview has been waived."))
            rec._check_and_advance_cleared()
        return self._show_success_message(_('Exit interview successfully waived.'))

    def action_complete_clearance(self):
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_auditor = self.env.user.has_group('hr_resignation.group_resignation_auditor')
        if not (is_pomd or is_auditor or is_hr):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager (or authorized delegate) can complete clearance.'))
        for rec in self:
            if not rec.is_company_terminated and not rec.exit_interview_waived and rec.has_active_exit_template and (not rec.exit_interview_id or rec.exit_interview_id.sudo().state != 'completed'):
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
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_auditor = self.env.user.has_group('hr_resignation.group_resignation_auditor')
        if not (is_pomd or is_auditor or is_hr):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager (or authorized delegate) can process settlement.'))
        self.ensure_one()
        if not self.settlement_id:
            settlement = self.env['hr.resignation.settlement'].sudo().create({
                'resignation_id': self.id,
                'employee_id': self.employee_id.id,
                'settlement_date': self.release_date,
                'cbs_start_date': self.application_date,
                'cbs_end_date': self.release_date,
            })
            self.settlement_id = settlement
        else:
            vals_sync = {}
            if self.application_date and self.settlement_id.cbs_start_date != self.application_date:
                vals_sync['cbs_start_date'] = self.application_date
            if self.release_date and self.settlement_id.cbs_end_date != self.release_date:
                vals_sync['cbs_end_date'] = self.release_date
            if self.settlement_id.cbs_sync_status and any(w in (self.settlement_id.cbs_sync_status or '') for w in ['CBS Timeout', 'took >', '[Notice]', 'Connection Error', 'CBS HTTP', 'CBS 404', 'CBS Notice', 'Verified:']):
                vals_sync['cbs_sync_status'] = False
            if self.settlement_id.cbs_pf_sync_status and any(w in (self.settlement_id.cbs_pf_sync_status or '') for w in ['CBS Timeout', 'took >', '[Notice]', 'Connection Error', 'CBS HTTP', 'CBS 404', 'CBS Notice', 'Verified:']):
                vals_sync['cbs_pf_sync_status'] = False
            if vals_sync:
                self.settlement_id.sudo().write(vals_sync)
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
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        if not is_hr:
            raise UserError(_('Only an HR Manager or authorized delegate can mark a case as settled with no payment.'))
        for rec in self:
            if rec.state != 'cleared':
                raise UserError(_('Clearance must be completed before marking as settled.'))
            if not rec.has_no_payment_configured:
                raise UserError(_('This separation type has financial entitlements configured. Please process the final settlement.'))
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
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')
        is_auditor = self.env.user.has_group('hr_resignation.group_resignation_auditor')
        if not (is_pomd or is_auditor or is_hr):
            raise UserError(_('Only a POMD Officer, Auditor, or HR Manager (or authorized delegate) can confirm settlement.'))
        for rec in self:
            if rec.state != 'cleared':
                raise UserError(_('Clearance must be completed before settlement.'))
            rec.state = 'settled'
        return self._show_success_message(_('Settlement confirmed successfully.'))

    def action_issue_certificate(self):
        is_hr = self._is_user_acting_hr_manager(self.env.user)
        is_pomd = self.env.user.has_group('hr_resignation.group_pomd_officer')

        if not (is_hr or is_pomd):
            raise UserError(_('Only an HR Manager, POMD Officer, or authorized delegate can issue the Certificate of Release.'))
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

    def action_print_acceptance_letter(self):
        """Print / Download Resignation Acceptance Letter - strictly for HR after approval."""
        self.ensure_one()
        is_hr = self._is_user_acting_hr_manager(self.env.user) or self.env.user.has_group('hr_resignation.group_resignation_hr_manager') or self.env.user.has_group('base.group_system')
        if not is_hr:
            raise UserError(_('Only HR Managers or authorized delegates can print the Resignation Acceptance Letter.'))
        if self.state in ('draft', 'submitted', 'returned', 'revoked'):
            raise UserError(_('The Resignation Acceptance Letter is only available after the resignation is approved by HR.'))
        return self.env.ref('hr_resignation.action_report_resignation_acceptance').report_action(self)

    def action_approve(self):
        """Unified approval dispatcher compatible with Delegated Approvals hub."""
        for rec in self:
            if rec.state == 'submitted':
                rec.action_hr_approve()
            elif rec.state == 'approved':
                rec.action_complete_handover()
            elif rec.state == 'handover_completed':
                rec.action_set_release_date()

    def action_reject(self):
        """Unified rejection dispatcher compatible with Delegated Approvals hub."""
        for rec in self:
            if rec.state == 'submitted':
                return rec.action_hr_return()

    def _trigger_access_revocation(self):

        for rec in self:
            emp = rec.employee_id
            if emp:
                if emp.user_id and emp.user_id.active:
                    emp.user_id.sudo().write({'active': False})
                if emp.active:
                    emp.sudo().write({'active': False})

    def _show_success_message(self, message, sticky=False, next_action=None):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': sticky,
                'next': next_action or {'type': 'ir.actions.client', 'tag': 'reload'},
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

    def _get_certificate_data(self):
        self.ensure_one()
        emp = self.employee_id

        # Gender and Honorifics logic
        gender = emp.gender if hasattr(emp, 'gender') else 'male'
        marital = emp.marital if hasattr(emp, 'marital') else 'single'

        if gender == 'female':
            pronoun_sub = 'she'
            pronoun_obj = 'her'
            pronoun_pos = 'her'
            prefix = 'W/rt' if marital in ('single', 'single') else 'W/y'
        else:
            pronoun_sub = 'he'
            pronoun_obj = 'him'
            pronoun_pos = 'his'
            prefix = 'Ato'

        name_full = f"{prefix} {emp.name}"

        # Salary to Words
        basic_salary = self.basic_salary or 0.0
        # If there's an amount_to_text on currency, we can try to use it
        try:
            currency = self.env.company.currency_id
            if currency:
                salary_words = currency.amount_to_text(basic_salary)
                # Odoo often appends currency name, let's just title case it
                salary_words = salary_words.title().replace('Dollars', '').replace('Birr', '').strip()
            else:
                salary_words = str(basic_salary)
        except Exception:
            salary_words = str(basic_salary)

        # Get Job History from Employee Master
        job_history = []
        job_history_items = []
        if hasattr(emp, 'job_history_ids') and emp.job_history_ids:
            histories = emp.job_history_ids.sorted(lambda h: h.job_history_start_date or fields.Date.context_today(self))
            for h in histories:
                job_name = h.job_id.name if h.job_id else h.position
                if not job_name:
                    continue

                d_start = h.job_history_start_date.strftime('%Y-%m-%d') if getattr(h, 'job_history_start_date', False) else ''
                d_end = h.job_history_end_date.strftime('%Y-%m-%d') if getattr(h, 'job_history_end_date', False) else 'To date.'

                if d_start:
                    job_history.append(f"{job_name} from {d_start} - {d_end}")
                    job_history_items.append({
                        'job_name': job_name,
                        'start_date': d_start,
                        'end_date': d_end
                    })

        # Fallback to hr.version if no history
        if not job_history:
            versions = self.env['hr.version'].sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'not in', ['draft', 'cancel'])
            ])
            # Sort in python since date_start might be a non-stored field
            versions = versions.sorted(lambda v: v.date_start or v.contract_date_start or fields.Date.context_today(self))

            for v in versions:
                job_name = v.job_id.name if v.job_id else v.job_title
                if not job_name:
                    continue

                d_start = v.date_start.strftime('%Y-%m-%d') if getattr(v, 'date_start', False) else (v.contract_date_start.strftime('%Y-%m-%d') if getattr(v, 'contract_date_start', False) else '')
                d_end = v.date_end.strftime('%Y-%m-%d') if getattr(v, 'date_end', False) else (v.contract_date_end.strftime('%Y-%m-%d') if getattr(v, 'contract_date_end', False) else 'To date.')

                if d_start:
                    job_history.append(f"{job_name} from {d_start} - {d_end}")
                    job_history_items.append({
                        'job_name': job_name,
                        'start_date': d_start,
                        'end_date': d_end
                    })

        if not job_history:
            # Absolute fallback
            j_name = emp.job_id.name or getattr(emp, 'job_title', 'Employee')
            d_start = self.joined_date.strftime('%Y-%m-%d') if self.joined_date else ''
            d_end = self.release_date.strftime('%Y-%m-%d') if self.release_date else (self.expected_last_day.strftime('%Y-%m-%d') if self.expected_last_day else 'To date.')
            job_history.append(f"{j_name} from {d_start} - {d_end}")
            job_history_items.append({
                'job_name': j_name,
                'start_date': d_start,
                'end_date': d_end
            })
        hire_date = self.joined_date.strftime('%Y-%m-%d') if self.joined_date else 'Unknown'
        release_date = self.release_date.strftime('%Y-%m-%d') if self.release_date else (self.expected_last_day.strftime('%Y-%m-%d') if self.expected_last_day else 'Unknown')

        # Company Logo (taking directly from resignation static)
        company_logo_uri = False
        img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'src', 'img', 'bunna_cert_logo.jpeg')
        if not os.path.exists(img_path):
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'src', 'img', 'bunna_logo.png')
        if not os.path.exists(img_path):
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'description', 'photo_2026-10-19_15-50-44.jpg')
        if not os.path.exists(img_path):
            img_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'bunna_custom_web_page', 'static', 'src', 'img', 'bunna_logo.png')
        if os.path.exists(img_path):
            try:
                with open(img_path, 'rb') as f:
                    mime = 'image/jpeg' if img_path.lower().endswith(('.jpg', '.jpeg')) else 'image/png'
                    company_logo_uri = f"data:{mime};base64,{base64.b64encode(f.read()).decode('utf-8')}"
            except Exception:
                company_logo_uri = False

        if not company_logo_uri and emp.sudo().company_id.logo:
            from odoo.tools.image import image_data_uri
            company_logo_uri = image_data_uri(emp.sudo().company_id.logo)

        # Company and Signatory Details
        comp = emp.sudo().company_id or self.env.company
        signatory_name = (comp.signatory_employee_id.name if comp.signatory_employee_id else False) or comp.certificate_signatory_name or "Director, Human Resource Management"
        signatory_title = (comp.signatory_job_id.name if comp.signatory_job_id else False) or comp.certificate_signatory_title or "Human Resource Management Division"
        company_name = comp.name or "Bunna Bank S.C."

        # Determine signing mode (resignation override or company default)
        mode = self.certificate_signing_mode or (comp and comp.certificate_signing_mode) or 'digital'

        signature_uri = False
        stamp_uri = False

        if mode != 'manual':
            def _to_data_uri(raw_data):
                if not raw_data:
                    return False
                if isinstance(raw_data, str) and raw_data.startswith('data:image/'):
                    return raw_data
                try:
                    if isinstance(raw_data, str):
                        b_data = base64.b64decode(raw_data)
                    elif isinstance(raw_data, (bytes, bytearray)):
                        try:
                            b_data = base64.b64decode(raw_data)
                        except Exception:
                            b_data = bytes(raw_data)
                    else:
                        return False

                    if b_data.startswith(b'\x89PNG\r\n\x1a\n'):
                        mime = 'image/png'
                    elif b_data.startswith(b'\xff\xd8'):
                        mime = 'image/jpeg'
                    elif b_data.startswith(b'GIF8'):
                        mime = 'image/gif'
                    else:
                        return False
                    return f"data:{mime};base64,{base64.b64encode(b_data).decode('utf-8')}"
                except Exception:
                    return False

            if comp.certificate_signature:
                signature_uri = _to_data_uri(comp.certificate_signature)
            if comp.certificate_stamp:
                stamp_uri = _to_data_uri(comp.certificate_stamp)

        # Embed Barlow corporate fonts in base64
        module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        font_dir = os.path.join(module_dir, "static", "src", "fonts")
        medium_path = os.path.join(font_dir, "Barlow-Medium.ttf")
        reg_path = os.path.join(font_dir, "Barlow-Regular.ttf")
        bold_path = os.path.join(font_dir, "Barlow-Bold.ttf")

        if not os.path.exists(medium_path):
            medium_path = r"C:\Windows\Fonts\Barlow-Medium.ttf"
        if not os.path.exists(reg_path):
            reg_path = r"C:\Windows\Fonts\barlow.regular.ttf"
        if not os.path.exists(bold_path):
            bold_path = r"C:\Windows\Fonts\barlow.bold.ttf"

        medium_b64 = ""
        reg_b64 = ""
        bold_b64 = ""
        if os.path.exists(medium_path):
            try:
                with open(medium_path, "rb") as f:
                    medium_b64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass
        if os.path.exists(reg_path):
            try:
                with open(reg_path, "rb") as f:
                    reg_b64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass
        if os.path.exists(bold_path):
            try:
                with open(bold_path, "rb") as f:
                    bold_b64 = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass

        barlow_css = []
        if medium_b64:
            barlow_css.append(f"""
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{medium_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{bold_b64 or medium_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
        if reg_b64:
            barlow_css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{reg_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
""")
        if medium_b64:
            barlow_css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{medium_b64}') format('truetype');
    font-weight: 500;
    font-style: normal;
}}
""")
        if bold_b64:
            barlow_css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{bold_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
        barlow_css.append("""
body, div, p, span, strong, td, th, li, a, h1, h2, h3, h4, h5, h6, .page, .article {
    font-family: 'Barlow Medium', 'Barlow', Arial, sans-serif !important;
}
""")
        from markupsafe import Markup
        barlow_font_faces = Markup("".join(barlow_css))

        return {
            'prefix': prefix,
            'name_full': name_full,
            'pronoun_sub': pronoun_sub,
            'pronoun_obj': pronoun_obj,
            'pronoun_pos': pronoun_pos,
            'pronoun_sub_cap': pronoun_sub.capitalize(),
            'pronoun_obj_cap': pronoun_obj.capitalize(),
            'pronoun_pos_cap': pronoun_pos.capitalize(),
            'hire_date': hire_date,
            'release_date': release_date,
            'salary_words': salary_words,
            'job_history': job_history,
            'job_history_items': job_history_items,
            'company_logo': company_logo_uri,
            'signatory_name': signatory_name,
            'signatory_title': signatory_title,
            'company_name': company_name,
            'signature_uri': signature_uri,
            'stamp_uri': stamp_uri,
            'signing_mode': mode,
            'barlow_font_faces': barlow_font_faces,
        }

    def _get_acceptance_data(self):
        """Prepare data dictionary specifically formatted for Bunna Bank Resignation Acceptance Letter."""
        self.ensure_one()
        cert = self._get_certificate_data()
        # Override signing mode with acceptance-specific setting
        acc_mode = getattr(self, 'acceptance_signing_mode', 'digital') or 'digital'
        if acc_mode:
            cert['signing_mode'] = acc_mode
            # Reload signature/stamp based on correct mode
            comp = self.employee_id.sudo().company_id or self.env.company
            if acc_mode == 'manual':
                cert['signature_uri'] = False
                cert['stamp_uri'] = False
            else:
                def _to_uri(raw):
                    if not raw:
                        return False
                    if isinstance(raw, str) and raw.startswith('data:image/'):
                        return raw
                    try:
                        import base64 as _b64
                        b = _b64.b64decode(raw) if isinstance(raw, str) else (bytes(raw) if isinstance(raw, (bytes, bytearray)) else None)
                        if not b:
                            return False
                        mime = 'image/png' if b[:8] == b'\x89PNG\r\n\x1a\n' else ('image/jpeg' if b[:2] == b'\xff\xd8' else False)
                        if not mime:
                            return False
                        return f"data:{mime};base64,{_b64.b64encode(b).decode()}"
                    except Exception:
                        return False
                cert['signature_uri'] = _to_uri(comp.certificate_signature)
                cert['stamp_uri'] = _to_uri(comp.certificate_stamp)
        emp = self.employee_id

        # Format dates in Month DD, YYYY
        app_date = self.application_date.strftime('%B %d, %Y') if self.application_date else fields.Date.today().strftime('%B %d, %Y')
        joined = self.joined_date.strftime('%B %d, %Y') if self.joined_date else (self.contract_id.date_start.strftime('%B %d, %Y') if getattr(self, 'contract_id', False) and self.contract_id.date_start else 'Unknown')
        eff_date = (self.release_date or self.expected_last_day or self.application_date or fields.Date.today()).strftime('%B %d, %Y')

        # Salutation name: prefix + first name (e.g. "Ato Natan" or "W/y Etsegenet")
        name_parts = (emp.name or '').strip().split()
        first_name = name_parts[0] if name_parts else ''
        salutation_name = f"{cert.get('prefix', 'Ato')} {first_name}".strip()

        # City / Location
        city = "Addis Ababa"
        if emp.address_id and emp.address_id.city and "brisbane" not in emp.address_id.city.lower():
            city = emp.address_id.city
        elif getattr(emp, 'work_location_id', False) and emp.work_location_id.name and "brisbane" not in emp.work_location_id.name.lower():
            city = emp.work_location_id.name
        else:
            city = "Addis Ababa"

        # CC distribution list matching Bunna Bank official format
        cc_list = [
            "Credit Relationship Management Directorate",
            "IT Security Management Directorate",
        ]
        if self.department_id and self.department_id.name:
            cc_list.append(self.department_id.name)
        if self.coach_id and self.coach_id.name:
            coach_gender = getattr(self.coach_id, 'gender', 'male')
            coach_marital = getattr(self.coach_id, 'marital', 'single')
            c_prefix = ('W/rt' if coach_marital == 'single' else 'W/y') if coach_gender == 'female' else 'Ato'
            cc_list.append(f"{c_prefix} {self.coach_id.name}")

        # Reference number
        ref_no = self.name or f"{self.id}"
        if not ref_no.startswith("BB/") and not ref_no.startswith("Ref"):
            ref_no = f"BB/ POMD-PSR/{ref_no}"

        cert.update({
            'letter_date': fields.Date.today().strftime('%B %d, %Y'),
            'ref_no': ref_no,
            'salutation_name': salutation_name,
            'city': city,
            'application_date_str': app_date,
            'joined_date_str': joined,
            'effective_date_str': eff_date,
            'cc_list': cc_list,
        })
        return cert

    def _get_termination_notification_data(self):
        """Prepare data dictionary specifically formatted for Bunna Bank Notification of Termination Memo (Internal Memo)."""
        self.ensure_one()
        cert = self._get_certificate_data()
        emp = self.employee_id
        # Override signing mode with acceptance-specific setting if present
        acc_mode = getattr(self, 'acceptance_signing_mode', 'digital') or 'digital'
        if acc_mode:
            cert['signing_mode'] = acc_mode
            comp = self.employee_id.sudo().company_id or self.env.company
            if acc_mode == 'manual':
                cert['signature_uri'] = False
                cert['stamp_uri'] = False
            else:
                def _to_uri(raw):
                    if not raw:
                        return False
                    if isinstance(raw, str) and raw.startswith('data:image/'):
                        return raw
                    try:
                        import base64 as _b64
                        b = _b64.b64decode(raw) if isinstance(raw, str) else (bytes(raw) if isinstance(raw, (bytes, bytearray)) else None)
                        if not b:
                            return False
                        mime = 'image/png' if b[:8] == b'\x89PNG\r\n\x1a\n' else ('image/jpeg' if b[:2] == b'\xff\xd8' else False)
                        if not mime:
                            return False
                        return f"data:{mime};base64,{_b64.b64encode(b).decode()}"
                    except Exception:
                        return False
                cert['signature_uri'] = _to_uri(comp.certificate_signature)
                cert['stamp_uri'] = _to_uri(comp.certificate_stamp)
        # Base64 logo for memo
        memo_logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'src', 'img', 'bunna_memo_logo.png')
        memo_logo_uri = False
        if os.path.exists(memo_logo_path):
            try:
                import base64
                with open(memo_logo_path, 'rb') as lf:
                    memo_logo_uri = f"data:image/png;base64,{base64.b64encode(lf.read()).decode()}"
            except Exception:
                memo_logo_uri = False
        # Employee ID Number
        employee_id_no = emp.barcode or emp.identification_id or getattr(emp, 'employee_identification', '') or f"{emp.id}"
        # Workplace: Branch / Operating Unit / Department
        work_place = ""
        if getattr(emp, 'work_location_id', False) and emp.work_location_id.name:
            work_place = emp.work_location_id.name
        elif self.operating_unit_id and self.operating_unit_id.name:
            work_place = self.operating_unit_id.name
        elif self.department_id and self.department_id.name:
            work_place = self.department_id.name
        elif emp.department_id and emp.department_id.name:
            work_place = emp.department_id.name
        else:
            work_place = "Head Office"
        # Dates
        joined = self.joined_date.strftime('%B %d, %Y') if self.joined_date else (self.contract_id.date_start.strftime('%B %d, %Y') if getattr(self, 'contract_id', False) and self.contract_id.date_start else 'Unknown')
        eff_date = (self.release_date or self.expected_last_day or self.application_date or fields.Date.today()).strftime('%B %d, %Y')
        # Reference number: matching e.g. BB/POMD-PSR/1014/2026 or rec.name
        ref_no = self.name or f"{self.id}"
        if not ref_no.startswith("BB/") and not ref_no.startswith("Ref"):
            ref_no = f"BB/POMD-PSR/{ref_no}"
        # To: Recipient
        to_recipient = "People Performance and Development Directorate"
        # CC distribution list matching Bunna Bank official format
        cc_list = [
            "Credit Relationship Management Directorate",
            "IT Security Management Directorate",
        ]
        if self.operating_unit_id and self.operating_unit_id.name:
            cc_list.append(self.operating_unit_id.name)
        elif self.department_id and self.department_id.name and self.department_id.name not in cc_list:
            cc_list.append(self.department_id.name)
        if work_place and work_place not in cc_list and work_place != to_recipient:
            cc_list.append(work_place)
        if self.coach_id and self.coach_id.name:
            coach_gender = getattr(self.coach_id, 'gender', 'male')
            coach_marital = getattr(self.coach_id, 'marital', 'single')
            c_prefix = ('W/rt' if coach_marital == 'single' else 'W/y') if coach_gender == 'female' else 'Ato'
            cc_list.append(f"{c_prefix} {self.coach_id.name}")
        cert.update({
            'letter_date': fields.Date.today().strftime('%B %d, %Y'),
            'ref_no': ref_no,
            'to_recipient': to_recipient,
            'from_sender': 'People Operation Management Directorate',
            'cc_list': cc_list,
            'employee_id_no': employee_id_no,
            'work_place': work_place,
            'joined_date_str': joined,
            'effective_date_str': eff_date,
            'separation_reason': self.resignation_type_id.name.lower() if self.resignation_type_id else 'resignation',
            'memo_logo_uri': memo_logo_uri,
        })
        return cert

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

    def _send_notification(self, partner_ids, subject, body):
        self.ensure_one()
        if not partner_ids:
            return
        from markupsafe import Markup
        # Use the current user's profile so it shows their Avatar and Name, not OdooBot
        author_id = self.env.user.partner_id.id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        body_text = str(body) if body else ""
        body_formatted = Markup("<br/>").join(Markup.escape(line) for line in body_text.splitlines())
        discuss_body = Markup(f"<b>{Markup.escape(subject)}</b><br/><br/>{body_formatted}<br/><br/><a href='{record_url}'>Click here to view</a>")

        # Post the message as a Direct Message so it appears with the sender's Avatar
        author_user = self.env['res.users'].sudo().sudo().search([('partner_id', '=', author_id)], limit=1)
        if not author_user:
            author_user = self.env.user

        for partner_id in list(set(partner_ids)):
            try:
                if partner_id == author_id:
                    bot = self.env.ref('base.partner_root', raise_if_not_found=False)
                    sender_user = bot.user_ids[:1] if bot and bot.user_ids else author_user
                    channel = self.env['discuss.channel'].sudo().with_user(sender_user)._get_or_create_chat([partner_id])
                else:
                    channel = self.env['discuss.channel'].sudo().with_user(author_user)._get_or_create_chat([partner_id])
                if channel:
                    channel.sudo().with_context(mail_create_nosubscribe=True, mail_notify_force_send=False).message_post(
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
        """Daily scheduler to deactivate system user access and archive employee records
        when their release date arrives or passes, or if resignation is completed.
        """
        today = fields.Date.today()
        # 1. Resignations where release date has arrived or passed (and offboarding is in progress/completed)
        resignations_due = self.search([
            ('release_date', '!=', False),
            ('release_date', '<=', today),
            ('state', 'in', ('clearance_in_progress', 'cleared', 'settled', 'completed')),
            '|',
            ('employee_id.active', '=', True),
            ('employee_id.user_id.active', '=', True)
        ])

        # 2. Resignations that are marked completed where employee or user is still active
        completed_active = self.search([
            ('state', '=', 'completed'),
            '|',
            ('employee_id.active', '=', True),
            ('employee_id.user_id.active', '=', True)
        ])
        all_resignations = resignations_due | completed_active
        for rec in all_resignations:
            rec._trigger_access_revocation()
            rec.message_post(body=_(
                "Employee system access revoked and record archived automatically on release date / completion (%s) by scheduler."
            ) % (rec.release_date or today))
        return True
