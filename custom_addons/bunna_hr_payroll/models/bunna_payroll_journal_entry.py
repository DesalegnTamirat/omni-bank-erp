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

    @api.depends('journal_entry_ids')
    def _compute_journal_entry_count(self):
        for rec in self:
            rec.journal_entry_count = len(rec.journal_entry_ids)

    @api.depends('journal_entry_ids.amount', 'journal_entry_ids.flag')
    def _compute_journal_totals(self):
        for rec in self:
            debits = sum(rec.journal_entry_ids.filtered(lambda e: e.flag == 'D').mapped('amount'))
            credits = sum(rec.journal_entry_ids.filtered(lambda e: e.flag == 'C').mapped('amount'))
            rec.total_journal_debit = debits
            rec.total_journal_credit = credits

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
