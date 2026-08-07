from odoo import api, models,fields,_
class EmployeeDemotion(models.Model):
    _name = "employee.demotion"
    _rec_name = "ref_num"

    ref_num = fields.Char(string='Ref Num', help="Reference", required=True)
    employee_name = fields.Many2one('hr.employee', string='Employee', help="Employee", required=True)
    current_work_unit = fields.Char("Current Work Unit")
    job_name = fields.Many2one('employee.job', string='Job Name')
    job_grade = fields.Char("Current Grade")
    job_position = fields.Char("Current Job Position")
    new_job_grade = fields.Many2one('employee.grade', string='New Grade')
    new_job_title = fields.Many2one('hr.job', string='New Position', help="Position",required=True)
    new_work_unit = fields.Many2one('operating.unit', string='New Work Unit', help="New Work Unit")
    change_date = fields.Date(string='Demotion Start Date', help="Demotion Start Date",required=True)
    job_history_start_date = fields.Date(string='Job History Start Date', help="Job History Start Date")
    job_history_end_date = fields.Date(string='Job History End Date', help="Job History End Date")
    reason = fields.Char(string='Reason for Change ', help="Reason for Change ")
    status= fields.Char(string='Status', help="Status")
    state = fields.Selection(
        [('draft', 'Draft'), ('populate_benefits', 'Populated Benifits'),
         ('populate_payout', 'Populated Payout'),
         ('approve', 'Approved')], string="State", default='draft')
    salary_det_demotion = fields.One2many("salary.detail.demotion", 'emp_demotion_id', string="Demotion Employee Salary Details")
    
    @api.onchange('employee_name')
    def _onchange_employee_name_info(self):
        self.job_position = self.employee_name.job_position.name
        self.job_grade = self.employee_name.job_grade.grade_name
        self.current_work_unit = self.employee_name.default_operating_unit_id.name
    
    def approve(self):
        p_id = self.id
        self.env.cr.execute('SELECT change_position_demoted_employee(%s)', (p_id,))
        self.env.cr.execute('SELECT job_history_demotion(%s)', (p_id,))
        self.state = "Update Employee"
        self.state = "approve"

    def populate_benefits(self):
        p_id = self.id
        self.env.cr.execute('SELECT compute_demotion_values(%s)', (p_id,))
        self.state = "populate_benefits"

    def populate_payout(self):
        p_id = self.id
        self.env.cr.execute('SELECT demotion_salary_computation(%s)', (p_id,))
        self.state="populate_payout"

class EmployeeDemotionSalary(models.Model):
    _name = "salary.detail.demotion"

    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one('hr.salary.rule', string="Salary Rule")
    value = fields.Float(string="Value")
    end_date = fields.Date(string="End Date")
    revised_value = fields.Float(string="Revised Value")
    start_date = fields.Date(string="Start Date")
    total_value = fields.Float(string="Payroll Value")
    payroll_period_id=fields.Integer(string="Payroll Period Id")
    employee_id = fields.Integer(string="Employee Id")
    emp_demotion_id = fields.Many2one('employee.demotion', string="Demotion Employee Salary Details")
