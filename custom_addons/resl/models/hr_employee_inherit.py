from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Remove the compute from field definition - let it be a regular field
    months_of_service = fields.Integer(
        string='Months of Service',
        compute='_compute_months_of_service',
        store=True,
        # Add depends to ensure it recomputes when needed
    )

    loan_ids = fields.One2many('resl.loan', 'employee_id', string='Loans')

    guarantee_count = fields.Integer(
        compute='_compute_guarantee_count',
        string='Active Guarantee Count',
        store=True
    )

    guaranteed_loan_ids = fields.One2many(
        'resl.loan.guarantee', 'guarantor_id',
        string='Loans Guaranteed',
        help='Loans for which this employee is a guarantor.'
    )

    @api.depends('contract_id', 'contract_ids', 'contract_ids.date_start', 'start_date')
    def _compute_months_of_service(self):
        """Compute months of service based on available date fields."""
        for rec in self:
            start_date = None

            # Try to get start date from various sources
            # Method 1: Check contract_id (current contract)
            if rec.contract_id:
                if hasattr(rec.contract_id, 'date_start') and rec.contract_id.date_start:
                    start_date = rec.contract_id.date_start

            # Method 2: Check contract_ids (all contracts)
            if not start_date and rec.contract_ids:
                # Get active/running contracts first
                active_contracts = rec.contract_ids.filtered(
                    lambda c: c.state in ['open', 'running'] if hasattr(c, 'state') else True
                )
                if active_contracts:
                    # Sort by date_start (oldest first)
                    sorted_contracts = active_contracts.sorted(
                        key=lambda c: c.date_start or False
                    )
                    if sorted_contracts and sorted_contracts[0].date_start:
                        start_date = sorted_contracts[0].date_start
                else:
                    # If no active contracts, use the oldest one
                    sorted_contracts = rec.contract_ids.sorted(
                        key=lambda c: c.date_start or False
                    )
                    if sorted_contracts and sorted_contracts[0].date_start:
                        start_date = sorted_contracts[0].date_start

            # Method 2b: Odoo 19 - hr.contract was merged into hr.version.
            # contract_id/contract_ids may exist but be disconnected legacy
            # fields; the real current data is on version_id/version_ids
            # (confirmed field names: contract_date_start, date_start).
            # getattr keeps this safe even if field names differ on this build.
            if not start_date:
                version = getattr(rec, 'version_id', False) or getattr(rec, 'current_version_id', False)
                if version:
                    for date_fld in ('contract_date_start', 'date_start'):
                        v_date = getattr(version, date_fld, False)
                        if v_date:
                            start_date = v_date
                            break
                if not start_date:
                    versions = getattr(rec, 'version_ids', False)
                    if versions:
                        date_fld = 'contract_date_start' if hasattr(versions, 'contract_date_start') else (
                            'date_start' if hasattr(versions, 'date_start') else None
                        )
                        if date_fld:
                            try:
                                dated_versions = versions.filtered(lambda v: getattr(v, date_fld, False))
                                sorted_versions = dated_versions.sorted(key=lambda v: getattr(v, date_fld))
                                if sorted_versions:
                                    start_date = getattr(sorted_versions[0], date_fld)
                            except Exception:
                                pass

            # Method 3: Use start_date field (if exists on employee)
            if not start_date and hasattr(rec, 'start_date') and rec.start_date:
                start_date = rec.start_date

            # Method 4: Use hire_date (if available)
            if not start_date and hasattr(rec, 'hire_date') and rec.hire_date:
                start_date = rec.hire_date

            # Method 5: Check for any date field in contract history
            if not start_date and rec.contract_ids:
                for contract in rec.contract_ids.sorted(key=lambda c: c.date_start or False):
                    if contract.date_start:
                        start_date = contract.date_start
                        break

            if not start_date:
                rec.months_of_service = 0
                continue

            # Convert to date if needed
            if isinstance(start_date, str):
                start_date = fields.Date.from_string(start_date)

            today = fields.Date.context_today(self)
            if isinstance(today, str):
                today = fields.Date.from_string(today)

            # Calculate months
            months = (today.year - start_date.year) * 12 + (today.month - start_date.month)
            if today.day < start_date.day:
                months -= 1
            rec.months_of_service = max(0, months)

    @api.depends('loan_ids')
    def _compute_guarantee_count(self):
        """Count unique borrowers where this employee is an accepted guarantor of an approved loan."""
        Guarantee = self.env['resl.loan.guarantee']
        for rec in self:
            try:
                guarantees = Guarantee.search([
                    ('guarantor_id', '=', rec.id),
                    ('state', '=', 'accepted'),
                    ('loan_id.status', '=', 'approved'),
                ])
                rec.guarantee_count = len(set(guarantees.mapped('loan_id.employee_id.id')))
            except Exception as e:
                _logger.warning(f"Could not compute guarantee_count for employee {rec.id}: {e}")
                rec.guarantee_count = 0

    def _handle_employee_separation(self):
        """
        Handle employee separation (BRD FR-RESL-013 & FR-RESL-014):
        1. FR-RESL-013: Outstanding loan balances recovered during separation/clearance.
           Notify HR/POMD and flag loan for settlement.
        2. FR-RESL-014: Mandatory guarantor replacement when guarantor separates.
           Mark guarantee as separated and flag loan for replacement.
        """
        Loan = self.env['resl.loan'].sudo()
        Guarantee = self.env['resl.loan.guarantee'].sudo()

        for emp in self:
            # 1. Employee as Borrower: FR-RESL-013
            active_borrower_loans = Loan.search([
                ('employee_id', '=', emp.id),
                ('status', 'in', ['approved', 'manager_review']),
                ('settlement_status', '!=', 'settled'),
            ])
            for b_loan in active_borrower_loans:
                b_loan.write({'settlement_status': 'pending_clearance'})
                b_loan.message_post(
                    body=_(
                        "⚠️ Employee %s is separating from the Bank. Outstanding loan balance must be "
                        "recovered during employee clearance (FR-RESL-013)."
                    ) % emp.name
                )
                # Notify POMD / HR users
                hr_group = self.env.ref('resl.group_resl_hr', raise_if_not_found=False)
                if hr_group:
                    for u in hr_group.all_user_ids:
                        try:
                            b_loan.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=u.id,
                                note=_(
                                    "Separation Clearance: Recover outstanding RSSA loan %s balance for %s."
                                ) % (b_loan.name, emp.name)
                            )
                        except Exception:
                            pass

            # 2. Employee as Guarantor: FR-RESL-014
            guarantees = Guarantee.search([
                ('guarantor_id', '=', emp.id),
                ('state', '=', 'accepted'),
                ('loan_id.status', 'in', ['approved', 'manager_review'])
            ])
            for g in guarantees:
                loan = g.loan_id
                g.write({
                    'state': 'separated',
                    'replaced_at': fields.Datetime.now(),
                })
                loan.write({'needs_guarantor_replacement': True})
                try:
                    loan._notify_guarantor_separation(g)
                except Exception:
                    pass

        try:
            emp_ids = [r.id for r in self]
            if emp_ids:
                self.env['hr.employee'].sudo().recompute_all_guarantee_counts(emp_ids)
        except Exception:
            _logger.exception('Failed to recompute guarantee_count after separation')

    # Fields that decide which work unit(s) a manager / approver may see loans
    # for. Odoo caches the evaluated record-rule domain per user, so when any
    # of these change the cache must be cleared or the old scope keeps applying.
    _RESL_SCOPE_FIELDS = {
        'user_id', 'job_id', 'job_title',
        'default_operating_unit_id', 'operating_unit_ids', 'operating_unit_id',
    }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(self._RESL_SCOPE_FIELDS & set(v) for v in vals_list):
            self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self._RESL_SCOPE_FIELDS & set(vals):
            self.env.registry.clear_cache()
        # FR-RESL-013 & FR-RESL-014: Trigger separation handler on archive or departure
        if vals.get('active') is False or vals.get('departure_date') or vals.get('departure_reason_id'):
            try:
                self._handle_employee_separation()
            except Exception as e:
                _logger.exception("Error in RESL separation handler: %s", e)
        return res

    @api.model
    def recompute_all_guarantee_counts(self, employee_ids=None):
        """Recompute stored guarantee_count for hr.employee records."""
        Guarantee = self.env['resl.loan.guarantee'].sudo()
        Employee = self.env['hr.employee'].sudo()
        if employee_ids:
            employees = Employee.search([('id', 'in', list(map(int, employee_ids)))])
        else:
            employees = Employee.search([])
        for emp in employees:
            try:
                guarantees = Guarantee.search([
                    ('guarantor_id', '=', emp.id),
                    ('state', '=', 'accepted'),
                    ('loan_id.status', '=', 'approved'),
                ])
                count = len(set(guarantees.mapped('loan_id.employee_id.id')))
                emp.sudo().write({'guarantee_count': count})
            except Exception:
                _logger.exception('Failed to write guarantee_count for employee %s', emp.id)
        return True

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """sudo-backed name_search when context contains resl_sudo_search."""
        ctx = dict(self.env.context or {})
        if ctx.get('resl_sudo_search'):
            search_domain = list(domain or [])
            if name:
                search_domain = [('name', operator, name)] + search_domain
            recs = self.env['hr.employee'].sudo().search(search_domain, limit=limit)
            return [(rec.id, rec.display_name) for rec in recs]
        return super().name_search(name, domain=domain, operator=operator, limit=limit)

    def action_view_employee_guarantees(self):
        self.ensure_one()
        try:
            action_ref = self.env.ref(
                'resl.action_resl_employee_guarantee_lines',
                raise_if_not_found=False
            )
            if action_ref:
                action = action_ref.read()[0]
                action['domain'] = [('guarantor_id', '=', self.id)]
                action['context'] = dict(
                    self.env.context or {},
                    default_guarantor_id=self.id
                )
                return action
        except Exception:
            pass
        return {
            'type': 'ir.actions.act_window',
            'name': 'Guarantees for %s' % (self.name or ''),
            'res_model': 'resl.loan.guarantee',
            'view_mode': 'list,form',
            'domain': [('guarantor_id', '=', self.id)],
            'context': dict(self.env.context or {}, default_guarantor_id=self.id),
            'target': 'current',
        }