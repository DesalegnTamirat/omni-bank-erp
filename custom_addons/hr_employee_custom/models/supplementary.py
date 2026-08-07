from odoo import api, models,fields,_

class Supplementary_details(models.Model):
    _name = "supplementary.role"
    _description = "Supplementary role"
    _rec_name = "reference"

    reference= fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    sr_ref = fields.Char(string="SR Reference" , readonly=True)
    requesting_operating_unit = fields.Many2one("operating.unit", string="Requesting operating Unit" , readonly=True)
    acting_employee = fields.Many2one("hr.employee","Acting Employee" , readonly=True )
    employee_name = fields.Many2one("hr.employee","Employee Name" )
    #employee_id = fields.Char(string="Employee Id")#="_compute_employee_id" )
    employee_id = fields.Char(string="Employee Id")
    acting_basic_per_month = fields.Float("Acting Basic per Month" )
    acting_basic=fields.Float("New Basic Salary" )
    base_salary=fields.Float("Base Salary" )
    step_increment_value=fields.Float("Step Increment Value" )
    existing_basic=fields.Float("Existing Basic Salary")
    acting_position = fields.Many2one("hr.job","Vacant Position" , readonly=True)
    current_job_position = fields.Many2one("hr.job","Current Job Position" , readonly=True)
    current_work_unit = fields.Many2one("operating.unit","Current Work Unit" , readonly=True)
    acting_job_position = fields.Many2one("hr.job","Acting Job Position" , readonly=True)
    acting_work_unit = fields.Char("Acting Work Unit" , readonly=True)
    acting_reason = fields.Char("Acting Reason" , readonly=True)
    basic_difference=fields.Float("Difference in Basic" , readonly=True)
    allowance_difference=fields.Float("Difference in Allowances" , readonly=True)
    start_date = fields.Date("Start Date" , readonly=True)
    end_date = fields.Date("End Date" , readonly=True)
    status = fields.Selection(
        [('draft', 'Draft'), ('approved', 'Approved'),
         ('revoked', 'Revoked')], string="Status", default='draft')
    first_month = fields.Float('First month',default=0.00 )
    second_month  = fields.Float('Second Month',default=0.25 )
    third_month = fields.Float('Third Month',default=0.25 )
    more_than_four = fields.Float('More Than Four',default=0.50 )
    job_grade = fields.Many2one('employee.grade', string='Job Grade', help="Job Grade" , readonly=True)
    job_category = fields.Many2one('employee.job', string='Job Category', readonly=True)
    #job_category = fields.Many2one(string='Job Category', readonly=1)
    job_grade1 = fields.Many2one('employee.grade', string='Job Grade', help="Job Grade" , readonly=True)
    job_category1 = fields.Many2one('employee.job', string='Job Category', help="Job Category" , readonly=True) 
    cc_workunits = fields.Many2many("operating.unit", string="CC To:", help="Enter the Workunits to be copied")
    state = fields.Selection(
        [('draft', 'Draft'),("notify", "notify"), ("evaluate", "Evaluate"), ('populate_benefits', 'Populated Benifits'),
         ('populate_acting_Allowance', 'Populated Acting Allowance'),
         ('approve', 'Approved'),
         ('close_acting_position', 'Close Acting Position')], string="State", default='draft')
    revoked_date= fields.Date("Revoked Date")
    # status1 = fields.Selection([])
    supplementary_details=fields.One2many("hr.supplementary.salary","supplementary_id2","Supplementary Salary Details")
    supplementary_payouts=fields.One2many("hr.supplementary.payout","supplementary_id3","Supplementary Salary Payouts")
    sup_delg_team=fields.One2many("supplementary.delegation.team","supp_role_del_id","Supplementary Delegation Team")
    
    def notify(self):
        for com in self.sup_delg_team:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.reference, self.employee_name.name)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.reference, self.employee_name.name)
        self.state = "notify"

    def mail_channel_msgs(self, rec_id, ref, arg1):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear Committee<br>A New Acting form is created with following details.<br><br>
                         Reference No: %s<br>
                         Empoyee Name: %s<br>
                         <br><br>  Kindly approve.
                                """ % (ref, arg1)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def evaluate(self):
        n=0
        usr = self.env.user.name #  name of login user details
        for val in self.sup_delg_team:
            if val.status=="unavailable":
                if usr==val.employee_name:
                    raise ValidationError("Sorry!! you can not evaluate this bid")
                else:
                    n=n+1
                    val.approve=True
                    break
            else:
                if val.employee_name.name==usr:
                    n=n+1
                    val.approve = True
                    break
        if n==0:
            raise ValidationError("Sorry!! You are not assigned for this Evaluation")
        cnt = 0
        mem_cnt = 0
        for vals in self.sup_delg_team:
            mem_cnt=mem_cnt+1
            if vals.approve==True:
                cnt=cnt+1
        if cnt==mem_cnt:
            self.status="evaluate"
			
    # def _compute_employee_id(self):
      # for vals in self:
        # if  vals.employee_name:
            # val = self.env["hr.employee"].search([("name", "=", vals.employee_name.name)])
            # vals.employee_id=val.employee_identification
            # return vals.employee_id
        # else:
           # return 0
    
    @api.onchange('employee_name')
    def _onchange_employee_name_info(self):
        # print("employee_name=====================", self.employee_name)
        # print("employee_name=====================", self.employee_name)
        #self.current_job_position = self.employee_name.job_position.name
        self.current_job_position = self.employee_name.job_position
       # self.current_work_unit = self.employee_name.default_operating_unit_id.name
        self.current_work_unit = self.employee_name.default_operating_unit_id
    #
    @api.onchange('acting_employee')
    def _onchange_acting_employee_info(self):
        self.acting_job_position = self.acting_employee.job_position.name
        self.acting_work_unit = self.acting_employee.default_operating_unit_id.name

    def close_acting_position(self):
        p_id = self.employee_name.id
        self.env.cr.execute('SELECT acting_job_history_end(%s)', (p_id,))
        self.state = "close_acting_position"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('supplementary.role') or _('New')
        return super().create(vals_list)

    def approve(self):
        p_id = self.employee_name.id
        self.env.cr.execute('SELECT acting_job_history_start(%s)', (p_id,))
        self.state = "approve"

    def populate_benefits(self):
        p_id = self.id
        self.env.cr.execute('SELECT populate_supplementary_role(%s)', (p_id,))
        # if self.acting_position:
        #     acting_position_info = self.env["acting.position.rule"].search([('position_id', '=',self.acting_position.id)])
        #     print("acting_position_info=======================", acting_position_info)
        #     for val in acting_position_info:
        #         supplementary_details = self.env['hr.supplementary.salary'].search([])
        #         for val3 in supplementary_details:
        #             val3.unlink()

        #     for val in acting_position_info:
        #         self.supplementary_details=[(0,0,{"salary_rule":val.salary_rule_id.id,
        #             "internal_name": val.internal_name,"value":val.contract_rule_value})]

        # if self.acting_employee:
        #     contract_salary = self.env['hr.contract'].search([('employee_id', '=', self.acting_employee.id)])
        #     print("contract_salary================================", contract_salary)

        #     salary_rule = self.env['hr.salary.rule'].search([("internal_name","=","wage")])
        #     print("salary_rule================================", contract_salary.wage)
        #     # print("internal_name================================", salary_rule.internal_name)
        #     # print("value================================", salary_rule.value)
        #     for val in contract_salary.contract_multi_id:
        #         supplementary_details = self.env['hr.supplementary.salary'].search([])
        #         for val3 in supplementary_details:
        #             val3.unlink()
        #     self.supplementary_details = [(0, 0,{"salary_rule": salary_rule.id, "internal_name": salary_rule.internal_name,"value":contract_salary.wage})]
        #     for val in contract_salary.contract_multi_id:
        #         self.supplementary_details = [(0, 0, {"salary_rule": val.contract_salary_rule.id,"internal_name": val.contract_internal_name,"value":val.contract_value})]
        self.state = "populate_benefits"
		
    def populate_acting_Allowance(self):
        p_id = self.id
        self.env.cr.execute('SELECT compute_acting_allowance(%s)', (p_id,))
        # self.acting_allowance_per_month=0
        # self.step_increment_value = 0
        # self.existing_allowance_total = 0
        # self.allowance_difference=0.0
        # for val in self.supplementary_details:
        #     self.acting_allowance_total += val.value
        # print("total_value=========================", self.acting_allowance_total)
        # employee_salary = self.env['hr.contract'].search([('employee_id', '=', self.employee_name.id)])
        # for val in employee_salary.contract_multi_id:
        #     print(val.contract_value)
        #     self.existing_allowance_total+=val.contract_value
        #     # self.existing_allowance_total+=employee_salary.wage
        # self.existing_allowance_total += employee_salary.wage
        # self.step_increment_value=employee_salary.wage*employee_salary.factor
        # print("existing_allowance_total++++++++++++++++++++++++++", self.existing_allowance_total)
        # self.allowance_difference=self.acting_allowance_total - self.existing_allowance_total
        # if self.allowance_difference>self.step_increment_value:
        #     self.acting_allowance_per_month=self.allowance_difference
        # else:
        #     self.acting_allowance_per_month =self.step_increment_value
        # print("acting_allowance_per_month==========================================================",self.allowance_difference)
        self.state="populate_acting_Allowance"



class job_multi_record(models.Model):
    _name = "hr.supplementary.salary"
    _description="Supplementary Salary  Details"
    # PAYROLL MODULE NOT INSTALLED — was _rec_name="salary_rule", but that field
    # is commented out below (depends on hr.salary.rule). Pointing at
    # internal_name instead so the model can still load. Revert once the
    # payroll module is installed and salary_rule is uncommented.
    _rec_name = "internal_name"
    supplementary_id2 = fields.Many2one('supplementary.role', string="Salary", help='Select corresponding Salary')
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
    internal_name = fields.Char(string='Internal Name',help='Internal Name')
    old_value = fields.Float("Old Value")
    new_value = fields.Float("New Value")

class job_multi_record(models.Model):
    _name = "hr.supplementary.payout"
    _description="Supplementary Salary Payout"
    # _rec_name="salary_payout"
    supplementary_id3 = fields.Many2one('supplementary.role', string="Salary", help='Select corresponding Salary')
    hr_period_id=fields.Integer(string="Period Id")
    hr_period_name=fields.Char(string="Payroll Period ")
    start_date=fields.Date(string="Start Date")
    end_date=fields.Date(string="End Date")
    effective_days=fields.Integer(string="Effective Days")
    factor=fields.Float(string="Factor")
    payout_value = fields.Float("Payout")
    status=fields.Boolean("Status")

class SupplementaryDelegation(models.Model):
    _name = "supplementary.delegation.team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    supp_role_del_id = fields.Many2one("supplementary.role", string="Supplementary Delegation Team")


class HrEmployeeSupplementaryInherit(models.Model):
    _inherit = 'hr.employee'

    supplementary_count = fields.Integer(
        string='Supplementary Count',
        compute='_compute_supplementary_count',
    )

    def _compute_supplementary_count(self):
        for employee in self:
            employee.supplementary_count = self.env['supplementary.role'].search_count(
                [('employee_name', '=', employee.id)]
            )
