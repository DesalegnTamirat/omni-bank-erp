from odoo import models, fields, api, _
from odoo.exceptions import UserError


class BunnaPayrollJournalEntry(models.Model):
    """Stores generated Core Banking System (Finacle / CBS) journal entries
    for Bunna Bank payroll periods.
    """
    _name = 'bunna.payroll.journal.entry'
    _description = 'Bunna Payroll Journal Entry (CBS)'
    _order = 'period_id desc, group_code asc, sol_id asc, flag asc, account asc'

    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        required=True,
        ondelete='cascade',
        index=True
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit / Branch',
        index=True
    )
    is_ifb = fields.Boolean(
        string='Is IFB',
        related='operating_unit_id.is_ifb',
        store=True,
        index=True,
        help="Indicates whether the operating unit operates under Interest-Free Banking (IFB)."
    )
    banking_type_label = fields.Char(
        string='Banking',
        compute='_compute_banking_type_label',
        store=True,
        index=True,
        help="Conventional or IFB"
    )

    @api.depends('is_ifb')
    def _compute_banking_type_label(self):
        for rec in self:
            rec.banking_type_label = 'IFB' if rec.is_ifb else 'Conventional'

    work_unit_id = fields.Integer(string='Work Unit ID')
    ou_name = fields.Char(string='Branch / Work Unit')
    sol_id = fields.Char(string='SOL ID', index=True)
    report_code = fields.Char(string='Report Code', default='0')

    account = fields.Char(
        string='Account Number',
        required=True,
        index=True,
        help='CBS Account Number (SOL + GL Code for branches, or 13-digit Employee/Beneficiary Account)'
    )
    account_name = fields.Char(string='Account Name')
    amount = fields.Float(string='Amount', required=True, digits=(16, 2))
    particular = fields.Char(string='Particulars / Narrative')
    flag = fields.Selection([
        ('D', 'Debit (D)'),
        ('C', 'Credit (C)'),
    ], string='D / C', required=True, index=True)
    currency = fields.Char(string='Currency', default='ETB', required=True)

    group_code = fields.Selection([
        ('10', '10 - Base Payroll Entries'),
        ('20', '20 - Net Salary'),
        ('30', '30 - Overdraft (OD)'),
        ('40', '40 - Provident Fund (PF)'),
        ('50', '50 - Cash Indemnity (CIAB)'),
        ('60', '60 - ASBEZA'),
        ('70', '70 - Labour Union (LU)'),
        ('80', '80 - Court Deduction (COD)'),
        ('90', '90 - Other Deduction (OTHER)'),
    ], string='Group Code', required=True, index=True)

    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='set null')
    employee_identification = fields.Char(string='Staff ID')
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', ondelete='set null')
    date = fields.Date(string='Posting Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('exported', 'Exported'),
    ], string='Status', default='draft')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    salary_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Salary Rule',
        ondelete='set null',
        index=True,
        help='Salary rule that generated this CBS entry. Used for per-rule debit/credit balance '
             'verification to pinpoint which rule is causing an imbalance within a group.'
    )

    is_group_unbalanced = fields.Boolean(
        string='Group Unbalanced',
        compute='_compute_group_balance',
        store=True,
        index=True,
        help='True if total Debits do not equal total Credits for this Group Code in this Period.'
    )
    group_balance_diff = fields.Float(
        string='Group Diff (D - C)',
        compute='_compute_group_balance',
        store=True,
        digits=(16, 2),
        help='Total Debit minus Total Credit for this Group Code in this Period. Zero means balanced.'
    )



    @api.depends('period_id', 'group_code', 'amount', 'flag')
    def _compute_group_balance(self):
        period_ids = self.mapped('period_id').ids
        if not period_ids:
            for rec in self:
                rec.is_group_unbalanced = False
                rec.group_balance_diff = 0.0
            return

        self.env.cr.execute("""
            SELECT
                period_id,
                group_code,
                ROUND(COALESCE(SUM(CASE WHEN flag = 'D' THEN amount ELSE 0 END), 0)::numeric, 2) AS debit,
                ROUND(COALESCE(SUM(CASE WHEN flag = 'C' THEN amount ELSE 0 END), 0)::numeric, 2) AS credit
            FROM bunna_payroll_journal_entry
            WHERE period_id IN %s
            GROUP BY period_id, group_code
        """, (tuple(period_ids),))

        balance_map = {}
        for pid, grp, deb, cred in self.env.cr.fetchall():
            diff = round(float(deb - cred), 2)
            is_unbalanced = abs(diff) >= 0.01
            balance_map[(pid, grp)] = (is_unbalanced, diff)

        for rec in self:
            key = (rec.period_id.id, rec.group_code)
            is_unbal, diff = balance_map.get(key, (False, 0.0))
            rec.is_group_unbalanced = is_unbal
            rec.group_balance_diff = diff



class HrPayrollPeriod(models.Model):
    _inherit = 'hr.payroll.period'

    journal_entry_ids = fields.One2many(
        'bunna.payroll.journal.entry',
        'period_id',
        string='CBS Journal Entries',
        readonly=True
    )
    journal_entry_count = fields.Integer(
        string='Journal Entries Count',
        compute='_compute_journal_entry_count'
    )
    total_journal_debit = fields.Float(
        string='Total Debit',
        compute='_compute_journal_totals',
        digits=(16, 2)
    )
    total_journal_credit = fields.Float(
        string='Total Credit',
        compute='_compute_journal_totals',
        digits=(16, 2)
    )
    journal_is_balanced = fields.Boolean(
        string='CBS Balanced',
        compute='_compute_journal_totals',
        help='True if all CBS journal entry group codes are balanced.'
    )
    unbalanced_group_summary = fields.Text(
        string='Unbalanced Groups Summary',
        compute='_compute_journal_totals',
        help='Detailed summary of debit vs credit for unbalanced groups.'
    )

    @api.depends('journal_entry_ids')
    def _compute_journal_entry_count(self):
        for rec in self:
            rec.journal_entry_count = len(rec.journal_entry_ids)

    @api.depends('journal_entry_ids.amount', 'journal_entry_ids.flag', 'journal_entry_ids.group_code')
    def _compute_journal_totals(self):
        for rec in self:
            entries = rec.journal_entry_ids
            debits = sum(entries.filtered(lambda e: e.flag == 'D').mapped('amount'))
            credits = sum(entries.filtered(lambda e: e.flag == 'C').mapped('amount'))
            rec.total_journal_debit = debits
            rec.total_journal_credit = credits

            unbalanced_list = []
            group_codes = set(entries.mapped('group_code'))
            for grp in sorted(group_codes):
                g_entries = entries.filtered(lambda e: e.group_code == grp)
                g_deb = round(sum(g_entries.filtered(lambda e: e.flag == 'D').mapped('amount')), 2)
                g_cred = round(sum(g_entries.filtered(lambda e: e.flag == 'C').mapped('amount')), 2)
                g_diff = round(g_deb - g_cred, 2)
                if abs(g_diff) >= 0.01:
                    grp_name = dict(g_entries._fields['group_code'].selection).get(grp, grp)
                    unbalanced_list.append(
                        f"• Group {grp_name}: Debit = {g_deb:,.2f}, Credit = {g_cred:,.2f} (Diff = {g_diff:+,.2f})"
                    )

            rec.journal_is_balanced = len(unbalanced_list) == 0 and len(entries) > 0
            rec.unbalanced_group_summary = "\n".join(unbalanced_list) if unbalanced_list else False

    def action_view_journal_entries(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_bunna_payroll_journal_entry')
        action['domain'] = [('period_id', '=', self.id)]
        action['context'] = {
            'default_period_id': self.id,
            'search_default_period_id': self.id,
            'search_default_group_by_group_code': 1,
        }
        return action


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    journal_entry_count = fields.Integer(
        string='CBS Entries',
        compute='_compute_journal_entry_count'
    )

    def _compute_journal_entry_count(self):
        for run in self:
            if run.period_id:
                run.journal_entry_count = len(run.period_id.journal_entry_ids)
            else:
                run.journal_entry_count = 0

    def action_view_journal_entries(self):
        self.ensure_one()
        if not self.period_id:
            raise UserError(_("Please assign a Payroll Period to this batch first."))
        return self.period_id.action_view_journal_entries()
