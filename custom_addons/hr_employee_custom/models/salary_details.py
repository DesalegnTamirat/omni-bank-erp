from odoo import api, models,fields,_
from odoo import _
from odoo.exceptions import UserError
class hr_contract_salary_details(models.Model):
    _inherit = "employee.grade"
    increment_date = fields.Date("Increment Date")
    increment_status = fields.Char("Increment Status")
    salary_contract_multi_id=fields.One2many("hr.grade.salary","grade_id","salary Details")
    grade_increment_details=fields.One2many("grade_increment","grade_id","salary Details")

    def approve_button(self):
        pass
    def propagate_button(self):
        increment_list = []
        # print(self.job_grade.salary_contract_multi_id)
        contract_info = self.env["hr.version"].search([('job_grade', '=', self.grade_code)])
        for increment_val in contract_info:
            for val in self.grade_increment_details:
                if not val.start_date:
                    raise UserError(_("please Enter Start Date "))
                elif not val.end_date:
                    raise UserError(_("please Enter end Date "))
                else:
                    increment=self.env['hr.contract.salary'].search([("contract_salary_id","=",increment_val.id),("contract_internal_name","=",val.internal_name)])
                    my_json = {"contract_value": val.value, "contract_start_date": val.start_date,
                               "contract_end_date": val.end_date}
                    increment.write(my_json)



class job_multi_record(models.Model):
    _name = "hr.grade.salary"
    _description="salary  Details"
    # PAYROLL MODULE NOT INSTALLED — was _rec_name="salary_rule"; that field is
    # commented out below. Pointing at internal_name instead. Revert once the
    # payroll module is installed.
    _rec_name = "internal_name"

    grade_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
    internal_name = fields.Char(string='Internal Name',help='Internal Name')
    value = fields.Float("Value")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")

class increment_details(models.Model):
    _name = "grade_increment"
    _description = "Grade  Increment Details"
    # PAYROLL MODULE NOT INSTALLED — was _rec_name="salary_rule"; that field is
    # commented out below. Pointing at internal_name instead. Revert once the
    # payroll module is installed.
    _rec_name = "internal_name"
    grade_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
    internal_name = fields.Char(string='Internal Name', help='Internal Name')
    value = fields.Float("Value")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
# @api.onchange('salary_rule')
    # def _onchange_salary_rule(self):
    #     self.internal_name=self.salary_rule.internal_name





# PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
# class salary_details(models.Model):
#     _inherit = "hr.salary.rule"
#     increment_date = fields.Date(string='Increment Date')
#     grade_rules = fields.One2many('grade.salary.rule', 'grade_id', string='Grade')
#     position_rules = fields.One2many('position.salary.rule', 'position_id', string='Grade')
#     increment_rules1 = fields.One2many('increment.grade.salary.rule', 'increment_id', string='Increment', copy=True)
#     increment_rules2 = fields.One2many('increment.position.salary.rule', 'increment_id2', string='Increment', copy=True)
#
#     def approve(self):
#         print("self", self)
#
#     def propagate(self):
#         print("self", self.grade_code)

class GradeSalaryRules(models.Model):
    _name='grade.salary.rule'
    _description = 'Grade'
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # grade_id = fields.Many2one('hr.salary.rule', string='Salary Rule Input', required=True)
    grade2=fields.Many2one('employee.grade',string='Grade')
    base_salary=fields.Integer(string='Base Salary')
    factor=fields.Integer(string='Factor')
    value=fields.Integer(string='Value')
    start_date=fields.Date(string='Start Date')
    end_date=fields.Date(string='End Date')
# #
class IncrementSalaryRules(models.Model):
    _name="increment.grade.salary.rule"
    _description = 'Increment'
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # increment_id = fields.Many2one('hr.salary.rule', string='Salary Rule Input', required=True)
    grade2=fields.Many2one("employee.grade","Grade")
    value=fields.Integer(string='Value')

    start_date=fields.Date(string='Start Date')
    end_date=fields.Date(string='End Date')



class PositionSalaryRules(models.Model):
    _name='position.salary.rule'
    _description = 'Position'
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # position_id = fields.Many2one('hr.salary.rule', string='Salary Rule Input', required=True)
    position=fields.Many2one('hr.job',string='Position Name')
    value=fields.Integer(string='Value')
    start_date=fields.Date(string='Start Date')
    end_date=fields.Date(string='End Date')

class IncrementSalaryRules(models.Model):
    _name="increment.position.salary.rule"
    _description = 'Increment'
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # increment_id2 = fields.Many2one('hr.salary.rule', string='Salary Rule Input', required=True)
    position_name=fields.Many2one("hr.job","Position Name")
    value=fields.Integer(string='Value')
    start_date=fields.Date(string='Start Date')
    end_date=fields.Date(string='End Date')

