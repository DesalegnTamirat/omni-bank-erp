from odoo import api, models,fields,_

class InternalRecruitment(models.Model):
    _name = "employee.recruitment"
    _description = "Internal Recruitment"
    _rec_name = "job_position"

    job_position = fields.Char("Job Position")
    job_location = fields.Char("Work Unit")
    job_position_id=fields.Integer("Job Position Id")

    employee_grade=fields.Char("Grade")
    employee_category=fields.Char("Employee Category")
    vacancy_announced_on = fields.Date("Vacancy Announced On")
    eligible_employees_details = fields.One2many("employee.recruitment.job", 'recruitment_job_id',"Eligible Employees")

    def notify(self):
        p_id = self.job_position
        #self.env.cr.execute('SELECT internal_applicant(%s)', (p_id,))


class EligibleEmployees(models.Model):
    _name = "employee.recruitment.job"
    _description="Eligible Employees"

    recruitment_job_id = fields.Many2one('employee.recruitment', string="Internal Recruitment", help='Select corresponding Employee')
    emp_name = fields.Char(string="Employee Name", help='Salary Rule')
    emp_number = fields.Char(string='Employee Number',help='Internal Name')
    emp_grade = fields.Char("Employee Grade")
    emp_position = fields.Char("Employee Position")
    emp_location = fields.Char("Employee Location")
    emp_category = fields.Char("Employee Category")
    employment_type = fields.Char("Type of Employment")
    job_position_id = fields.Integer("Job Position Id")
    hr_employee_id= fields.Integer("Job Position Id")
    informed_employee_status=fields.Char("Informed Employee Status",default='New')
    select_flag =fields.Boolean("Select",default='Y')
