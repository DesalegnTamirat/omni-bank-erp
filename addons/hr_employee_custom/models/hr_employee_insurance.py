from odoo import models, fields, api


class HrEmployeeInsurance(models.Model):
    _name = 'hr.employee.insurance'
    _description = 'Employee Insurance'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    name_of_insurance = fields.Char(string='Name of Insurance')
    insurance_type = fields.Char(string='Insurance Type')
    renewal_date = fields.Date(string='Renewal Date')
    policy = fields.Char(string='Policy')
    policy_coverage = fields.Char(string='Policy Coverage')
    sum_insured = fields.Float(string='Sum Insured')
    premium = fields.Float(string='Premium')
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')
    company_id = fields.Many2one('res.company', string='Company')


class HrEmployeeInsuranceSummary(models.Model):
    _inherit = 'hr.employee'

    company_percentage = fields.Float(string='Company Percentage')
    salary_deducted_per_year = fields.Float(string='Salary deduced per year',
                                            compute='_compute_salary_deductions')
    salary_deducted_per_month = fields.Float(string='Salary deduced per month',
                                             compute='_compute_salary_deductions')
    insurance_ids = fields.One2many('hr.employee.insurance', 'employee_id', string='Insurance Lines')

    @api.depends('company_percentage', 'contract_id')
    def _compute_salary_deductions(self):
        for rec in self:
            wage = rec.contract_id.wage if rec.contract_id else 0.0
            rec.salary_deducted_per_year = wage * (rec.company_percentage / 100) * 12
            rec.salary_deducted_per_month = wage * (rec.company_percentage / 100)