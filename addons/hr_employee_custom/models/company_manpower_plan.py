from odoo import models, fields, api
from datetime import datetime
from odoo.exceptions import UserError

class CompanyManpowerPlan(models.Model):
    _name = "manpower.plan"
    _description = "Company manpower Plan"
    _rec_name = "plan_version"

    plan_version=fields.Integer(string="Plan Version")
    # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — 'account.fiscal.year' model
    # does not exist in this database. Uncomment once that module is
    # installed (the two related fields below depend on this field too).
    # fiscal_year = fields.Many2one("account.fiscal.year", string="Fiscal year")
    # plan_start_date=fields.Date("Plan Start Date", related="fiscal_year.date_from")
    # plan_end_date=fields.Date("Plan End Date", related="fiscal_year.date_to")
    status = fields.Selection([('Pending', 'Pending'), ('Running', 'Running'), ('Archived', 'Archived')], string="Plan Status", default="Pending", readonly=True)
    # status = fields.Char(string = "Status")
    state = fields.Selection(
        [('draft', 'Draft'), ("notify", "notify"), ("approve", "Approve")], string="State", default="draft")
    company_manpower_plan_id = fields.One2many('manpower.plan.jobs','company_manpower_id','Company Manpower')
    com_fin_imp_id = fields.One2many("company.financial.implications", "com_financial_implications_id", "Financial Implications")
    company_manpwr_del_id = fields.One2many("company.manpower.plan.delegation.team", "comp_manpwr_plan_appr_id", string="Company Manpower Plan Delegation Team")

    def notify(self):
        for com in self.company_manpwr_del_id:
            if com:
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — self.fiscal_year is
                    # commented out above. Passing None as a placeholder; restore
                    # self.fiscal_year once the account.fiscal.year model is available.
                    self.mail_channel_msgs(usr.id, self.plan_version, None)

                self.state = "notify"
            else:
                raise ValidationError('Please Define Approvers')

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear Committee<br>A Company Manpower Plan  is created with following details.<br><br>
                            Plan Version: %s<br>
                            Fiscal Year: %s<br>
                            <br><br>  Kindly approve.
                                   """ % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def approve(self):
        n = 0
        usr = self.env.user.name  # name of login user details
        for val in self.company_manpwr_del_id:
            if val.employee_name.name == usr:
                n = n + 1
                val.approve = True
                break
        if n == 0:
            raise ValidationError("Sorry!! You are not assigned for this Evaluation")
        cnt = 0
        mem_cnt = 0
        for vals in self.company_manpwr_del_id:
            mem_cnt = mem_cnt + 1
            if vals.approve == True:
                cnt = cnt + 1
        if cnt == mem_cnt:
            self.state= "approve"
			
    def populate_values(self):
        self.env.cr.execute('SELECT update_co_manpower_planning_cost()')

    # def populate_procurement_plan(self):
    #     print("Updating Prurement  Plan")
    #     self.env.cr.execute('SELECT update_manpower_procurement_plan()')

    def populate_recruitment(self):
        self.env.cr.execute('SELECT update_manpower_recruitment_plan()')
    #@api.model
    # def name_create(self, name):
    #     return self.create({'name': name}).name_get()[0]
    def unlink(self):
        for val in self.company_manpower_plan_id:
            val.unlink()
        return super(CompanyManpowerPlan,self).unlink()

class Requirements(models.Model):
    _name = "manpower.plan.jobs"
    _description = "Requirements Summary"
    _rec_name = "position"

    # vendor_name = fields.Many2one("res.partner","Vendor Name")

    job_name = fields.Many2one("employee.job","Job Name")
    # product = fields.Many2one("product.template","Product")
    job_id =  fields.Many2one("hr.job","position")
    company_manpower_id = fields.Many2one('manpower.plan', 'Company Manpower Plan')
    position  = fields.Many2one("hr.job","Position")
    grade=fields.Many2one("employee.grade","Grade")
    job_grade=fields.Many2one("employee.grade","Grade")
    category = fields.Char(string="Category", compute="_compute_category", store=True)
    # work_unit = fields.Many2one("operating.unit",string="Work Unit", required=True)
    # department =fields.Many2one("account.analytic.account",string="Department")
    plan_version = fields.Integer(string="Plan Version",related="company_manpower_id.plan_version")
    plan_start_date = fields.Date("Plan Start Date")
    plan_end_date = fields.Date("Plan End Date")
    status = fields.Char("Status")
    # category=fields.Many2one("product.category","Product Category")
    july = fields.Integer("July")
    august = fields.Integer("Aug")
    september = fields.Integer("Sept")
    october = fields.Integer("Oct")
    november = fields.Integer("Nov")
    december = fields.Integer("Dec")
    january = fields.Integer("Jan")
    february = fields.Integer("Feb")
    march = fields.Integer("Mar")
    april = fields.Integer("Apr")
    may = fields.Integer("May")
    june = fields.Integer("June")
    total = fields.Integer("Total", compute="_compute_total")
    position_cost= fields.Float("Grade Cost")
    estimated_cost= fields.Float("Estimated Cost")

    @api.depends('july', 'august', 'september', 'october', 'november', 'december', 'january', 'february', 'march',
                 'april', 'may', 'june')
    def _compute_total(self):
        for rec in self:
            rec.total = rec.july + rec.august + rec.september + rec.october + rec.november + rec.december + rec.january + rec.february + rec.march + rec.april + rec.may + rec.june
    @api.depends('job_id')
    def _compute_category(self):
        # Batch lookup to avoid N+1 queries
        job_names = self.mapped('position.name')
        if job_names:
            jobs = self.env["hr.job"].search([("name", "in", job_names)])
            job_map = {j.name: j.employee_category for j in jobs}
        else:
            job_map = {}
        for val in self:
            val.category = job_map.get(val.position.name, "") if val.position else ""
    # @api.depends('total', 'position_cost')
    # def _compute_estimated_cost(self):
        # for val in self:
            # if val.total and val.position_cost:
                # val.estimated_cost= val.total*val.position_cost
                # return val.estimated_cost
            # else:
              # val.estimated_cost= 0.0
              # return val.estimated_cost
    # def _compute_total(self):
    #     self.total=self.july+self.august+self.september+self.october+self.november+self.december+self.january+self.february+self.march+self.april+self.may+self.june
    #     return self.total
    # # @api.model
    # def create(self, vals):
    #     print("vals=",vals)
    #     get_manpower=self.env["manpower.plan"].search([("id","=",vals["company_manpower_id"])])
    #     vals["plan_version"]=get_manpower.plan_version
    #     return super(Requirements, self).create(vals)

    # @api.onchange("position")
    # def _onchange_position(self):
    #     print("grade",self.position.grade.grade_name)
    #     self.grade = False
    #     if self.position:
    #         domain = [('grade', "=", self.position.grade.grade_name)]
    #         return {'domain': {'grade': domain}}

    # @api.model
    # def name_create(self, name):
    #     return self.create({'name': name}).name_get()[0]
    def unlink(self):
        return super(Requirements, self).unlink()

    def details(self):

        return {
            'name': "Manpower Plan Ou Jobs",
            'type': 'ir.actions.act_window',
            'view_mode': 'tree',
            'res_model': "manpower.plan.ou.jobs",
            'domain': [("manpower_id.status", "=", "confirmed"), ("position","=",self.position.id),('manpower_id.plan_version',"=",str(self.company_manpower_id.plan_version))],
            "target":"new"
        }

    #
    # @api.onchange('product')
    # def _onchange_product(self):
    #     print("product=====================", self.product)
    #     print("employee_name=====================", self.product.categ_id)
    #     self.description =  self.product.description
    #     self.category = self.product.categ_id


class CompanyManpowerDelegation(models.Model):
    _name = "company.manpower.plan.delegation.team"

    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    comp_manpwr_plan_appr_id = fields.Many2one("manpower.plan", string="Company Manpower Plan Delegation Team")

class CompanyFinancialImplications(models.Model):
    _name = "company.financial.implications"
    _description = "Financial Implications"
    

    
    com_financial_implications_id = fields.Many2one('manpower.plan.ou', 'Financial Implications')
    work_unit2 = fields.Char(string="Work Unit")
    department2 = fields.Char(string="Department")
    plan_version = fields.Integer(string="Plan Version")
    position = fields.Char(string="Position")
    job_name = fields.Char(string="Job Name")
    job_id =  fields.Char(string="Position")
    grade = fields.Char(string="Grade")
    category = fields.Char(string="Category")
    fiscal_year = fields.Char(string="Fiscal Year")
    plan_start_date = fields.Date("Plan Start Date")
    plan_end_date = fields.Date("Plan End Date")
    status = fields.Char("Status")
    july = fields.Float("July")
    august = fields.Float("Aug")
    september = fields.Float("Sep")
    october = fields.Float("Oct")
    november = fields.Float("Nov")
    december = fields.Float("Dec")
    january = fields.Float("Jan")
    february = fields.Float("Feb")
    march = fields.Float("Mar")
    april = fields.Float("April")
    may = fields.Float("May")
    june = fields.Float("June")
    total = fields.Float("Total")
    position_cost = fields.Float("Grade Cost")
    estimated_cost = fields.Float("Estimated Cost")
