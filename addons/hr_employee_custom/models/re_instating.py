from odoo import api, models,fields,_
from odoo.exceptions import UserError
class re_instating_details(models.Model):
    _name = "re.instating"
    _description = "Re Instating Form"
    _rec_name = "ref_num"

    ref_num = fields.Char(string='Ref Num', help="Reference")
    employee_name = fields.Many2one('hr.employee', 'Employee Name')
    operating_unit = fields.Many2one('operating.unit', 'Operating Unit')
    department = fields.Many2one('hr.department', 'Department')
    new_job_title = fields.Many2one('hr.job', string='Job Position', help="Job Position")
    new_job_grade = fields.Many2one('employee.grade', 'Job Grade')
    salary = fields.Integer(string='Salary', help="Salary")
    new_salary = fields.Integer(string='Salary', help="Salary")
    date_re_instated = fields.Date(string='Date Re Instated', help="Date Re Instated")
    responsible = fields.Many2one('hr.employee', 'Responsible')
    reason = fields.Char(string='Reason ', help="Reason ")
    status = fields.Char(string='Status', help="Status")
    trial_date_end = fields.Date(string='Trial Date End', help="Trial Date End")
    wage = fields.Monetary('Wage', required=True, help="Employee's monthly gross wage.")
    currency_id = fields.Many2one(string="Currency", related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one('res.company', compute='_compute_employee_contract', store=True, readonly=False,
                                 default=lambda self: self.env.company, required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee',
                                  domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    def _get_contract_wage(self):
        self.ensure_one()
        return self[self._get_contract_wage_field()]

    def _get_contract_wage_field(self):
        self.ensure_one()
        return 'wage'
    @api.depends('employee_id')
    def _compute_employee_contract(self):
        for contract in self.filtered('employee_id'):
            contract.job_id = contract.employee_id.job_id
            contract.department_id = contract.employee_id.department_id
            contract.resource_calendar_id = contract.employee_id.resource_calendar_id
            contract.company_id = contract.employee_id.company_id

    def re_instate(self):
        salary_contract_list = []
        # print(self.job_grade.salary_contract_multi_id)

        for val in self.new_job_grade.salary_contract_multi_id:
            if not val.start_date:
                raise UserError(_("please Enter Start Date "))
            elif not val.end_date:
                raise UserError(_("please Enter end Date "))
            else:
                re_instating = self.env["re.instating"].search([("id", "=", self.id)])
                # print(re_instating)
                # PAYROLL MODULE NOT INSTALLED — "contract_salary_rule" (hr.contract.salary)
                # and val.salary_rule are both commented out elsewhere since they depend on
                # hr.salary.rule. Uncomment this block (and remove the placeholder below)
                # once the payroll module is installed.
                # my_json = {"contract_salary_rule": val.salary_rule.id, "contract_internal_name": val.internal_name,
                #            "contract_value": val.value, "contract_start_date": re_instating.date_re_instated,
                #            "contract_end_date": val.end_date}
                my_json = {"contract_value": val.value, "contract_start_date": re_instating.date_re_instated,
                           "contract_end_date": val.end_date}
            salary_contract_list.append((0, 0, my_json))
            contract_info = self.env["hr.contract"].search([('job_grade', '=', self.new_job_grade.id)])
            for job_val in contract_info:
                # if not job_val.contract_multi_id:
                for val3 in job_val.contract_multi_id:
                    val3.unlink()
                job_val.write({"contract_multi_id": salary_contract_list})

    def Approve(self):
        vals = {
            "name":self.ref_num,
            "employee_id": self.employee_name.id,
            "operating_unit_id": self.operating_unit.id,
            "department_id": self.department.id,
            "job_id": self.new_job_title.id,
            "job_grade": self.new_job_grade.id,
            "trial_date_end": self.trial_date_end,
            "wage": self.wage,
        }
        self.env["hr.contract"].create(vals)
        vals1={
            "employee_id":self.employee_name.id,
            "new_job_title":self.new_job_title.id,
            "new_job_grade":self.new_job_grade.id,
            "salary":self.salary,
            "date":self.date_re_instated,
        }
        history=self.env["re.instated.history"].create(vals1)
        vals2 = {
            "employee_name": self.employee_name.id,
            "status": "approved",
        }
        status = self.env["re.instating"].search([('employee_name', '=', self.employee_name.id)])
        status.write(vals2)



