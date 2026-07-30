from odoo import api, models,fields,_
class job_form_details(models.Model):
    _name = "job.form"
    _description = "Job Form With Job History"
    _rec_name = "ref_num"

    ref_num = fields.Char(string='Ref Num', help="Reference")
    employee_name = fields.Many2one('hr.employee', string='Employee', help="Employee")
    job_name = fields.Many2one('employee.job', string='Job Name')
    job_grade = fields.Many2one('employee.grade', string='Grade')
    new_job_title = fields.Many2one('hr.job', string='Position', help="Position")
    job_history_start_date = fields.Date(string='Job History Start Date', help="Job History Start Date")
    job_history_end_date = fields.Date(string='Job History End Date', help="Job History End Date")
    reason = fields.Char(string='Reason for Change ', help="Reason for Change ")
    status= fields.Char(string='Status', help="Status")
    salary_details = fields.One2many("salary.detail.changes", 'details_id', string="Salary Details Changes")
    def approve(self):
        contract_info = self.env["hr.contract"].search([('employee_id', '=', self.employee_name.id)])

        vals = {
            "employee_id": self.employee_name.id,
            # "job_name": self.department1.id,
            "job_id": self.new_job_title.id,
            "job_grade": self.job_grade.id,
            "job_category": self.job_name.id,
        }
        contract_info.write(vals)

        vals2 = {
            "employee_name": self.employee_name.id,
            "status": "approved",
        }
        status = self.env["job.form"].search([('employee_name', '=', self.employee_name.id)])
        status.write(vals2)

        vals3 = {
            "employee_id": self.employee_name.id,
            "job_name": self.job_name.id,
            "job_grade": self.job_grade.id,
            "new_job_title": self.new_job_title.id,
            "job_history_start_date": self.job_history_start_date,
            "job_history_end_date": self.job_history_end_date,
            "reason": self.reason,

        }
        history = self.env["department.history"].create(vals3)

class SalaryDetailChanges(models.Model):
    _name = "salary.detail.changes"

    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one('hr.salary.rule', string="Salary Rule")
    value = fields.Float(string="Value")
    end_date = fields.Date(string="End Date")
    revised_value = fields.Float(string="Revised Value")
    start_date = fields.Date(string="Start Date")
    total_value = fields.Float(string="Payroll Value")
    payroll_period_id=fields.Integer(string="Payroll Period Id")
    employee_id = fields.Integer(string="Employee Id")
    details_id = fields.Many2one('job.form', string="Salary Details Changes")
