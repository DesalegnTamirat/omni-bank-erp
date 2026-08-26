from odoo import api, models,fields,_
class employee_job(models.Model):
    _name = "employee.job"
    _description = "Employee Job  Details"
    _rec_name = "job_name"
    job_code = fields.Char("Job Code")
    job_name = fields.Char("Job Name")
    job_category = fields.Char("Job Category")
    start_date = fields.Date("Start date")
    end_date = fields.Date("End Date")
    # status = fields.Selection(selection=[
    #     ('active', 'Active'),
    #     ('inactive', 'Inactive'),
    # ], string='Status', required=True, readonly=True, copy=False, tracking=True)
    status = fields.Boolean('Status')
    grade_multi_record=fields.One2many("job_multi_record",'employee_id','grade_multi_record Details')

class grade_multi_record(models.Model):
    _name = "job_multi_record"
    _description="Grade Info Details"
    _rec_name="grade_code"
    employee_id = fields.Many2one('employee.job', string="Employee", help='Select corresponding Employee')
    grade_code = fields.Many2one("employee.grade", "Grade Code")
    parent_grade = fields.Char("Parent Grade")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")

