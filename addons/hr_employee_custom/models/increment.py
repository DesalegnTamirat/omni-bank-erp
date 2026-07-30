from odoo import api, models,fields,_

class Increment_details(models.Model):
    _name = "employee.increment"
    _description = "Employee Increment"
    _rec_name = "employee_name"

    # reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_name = fields.Many2one("hr.employee","Employee Name", required=True)
    reference = fields.Char(string='Reference', required=True)
    job_position = fields.Many2one('hr.job', string='Job Position', help="Job Position", readonly=True)
    job_grade = fields.Many2one('employee.grade', string='Job Grade', help="Job Grade", readonly=True)
    job_category = fields.Char(string='Job Category', readonly=True)
    work_unit = fields.Many2one('operating.unit', string='Work Unit', readonly=True)
    salary_account = fields.Char(string="Salary Account", help="salary_account")
    pf_account = fields.Char(string="PF Account", help="pf_account")
    existing_basic = fields.Float("Existing Basic Salary")
    salary_factor = fields.Float("Salary Factor", digits=(16, 3))
    increment_factor = fields.Float("Increment Factor", readonly=True)
    new_basic = fields.Float("New Basic Salary")
    increment_effective_date = fields.Date("Increment Effective Date")
    # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — 'account.fiscal.year' model
    # does not exist in this database. Uncomment once that module is installed.
    # fiscal_year = fields.Many2one('account.fiscal.year', string='Fiscal Year', readonly=1)
    assessment_end_date = fields.Date("Assessment End Date")
    arrear_days = fields.Integer("Arrear Days")
    arrear_original_basic = fields.Float("Arrear Original Basic")
    arrear_new_basic = fields.Float("Arrear New Basic")
    arrear_difference = fields.Float("Arrear Difference")
    tax_original_arrear= fields.Float("Tax on Original Arrear")
    tax_revised_arrear = fields.Float("Tax on Revised Arrear")
    tax_difference = fields.Float("Tax Difference")
    net_arrear_payout = fields.Float("Net Increment Payout")
    pension_fund_payable_bank = fields.Float("Pension Fund Payable - Bank 11%")
    provident_fund = fields.Float("Provident Fund 2%")
    pension_fund_payable_emp = fields.Float("Pension Fund Payable - Employee 7%")
    pension_fund_gl_account = fields.Char(string="Pension Fund GL Account", help="pension_fund_gl_account")

    state = fields.Selection(
        [('draft', 'Draft'), ('populated', 'Populated'),
         ('computed', 'Computed')], string="Status", default='draft')



    def populate_details(self):
        p_id = self.id
        self.env.cr.execute('SELECT populate_increment_details(%s)', (p_id,))
        self.state = "populated"

    def compute_payout(self):
        p_id = self.id
        self.env.cr.execute('SELECT compute_increment_net_payout(%s)', (p_id,))
        self.state = "computed"

