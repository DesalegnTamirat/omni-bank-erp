from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ManpowerPlan(models.Model):
    _name = "manpower.plan.ou"
    _description = "Work Unit Procurement Plan"
    _rec_name = "work_unit"

    work_unit =fields.Many2one("operating.unit",string="Work Unit",required=True)
    reporting_unit = fields.Char(string="District/Area/Head Office",
         related="work_unit.parent_unit.name")
    # ACCOUNTING MODULE NOT INSTALLED — 'account.analytic.account' model does not exist ('account' is not in this module's dependencies)
    # department2 =fields.Many2one("account.analytic.account",string="Department")
    # plan_version =fields.Char(string="Plan Version")
    plan_version =fields.Many2one("manpower.plan", string="Plan Version")
    plan_version_detail = fields.Integer(string="Plan Version", required=True)
    fiscal_year=fields.Char(string="Fiscal Year" ,readonly=True)
    plan_start_date=fields.Date("Plan Start Date" ,readonly=True)
    plan_end_date=fields.Date("Plan End Date" ,readonly=True)
    status=fields.Char("Plan Status",readonly=True)
    populated_status=fields.Char("Populated Status" ,readonly=True)
    approve_status = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Approval Status", default="draft")
    requestor = fields.Char(string="Requestor")
    manpower_plan_id = fields.One2many('manpower.plan.ou.jobs','manpower_id','Work Unit Manpower')
    fin_imp_id = fields.One2many("financial.implications", "financial_implications_id", "Financial Implications")
	
    @api.constrains('work_unit')
    def _check_unique_work_unit(self):
        for record in self:
            if self.search_count([('work_unit', '=', record.work_unit.id), ('plan_version', '=', record.plan_version.id)]) > 1:
                raise ValidationError("Plan already exist with same Work Unit")
                
    def initiate_approval(self):
        for val in self:
            if val.work_unit:
               rec = self.env["planning.approval"].sudo().search([("operating_unit", "=", val.work_unit.name)])
               if rec:
                   usr = self.env["res.partner"].sudo().search([("name", "=", rec.authorized_approver.name)])
                   self.mail_channel_msgs(usr.id, usr.name, self.work_unit.name, self.plan_version.plan_version, self.fiscal_year)
                   val.requestor=self.env.user.name
                   val.approve_status='initiated'
				   
               else:
                   raise ValidationError('Approver is not defined for this work unit')
            else:
                raise ValidationError('Please select work unit')

    def mail_channel_msgs(self, rec_id, ref, arg1, arg2, arg3):
        print("*************")
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear %s <br>A Workunit Manpower Plan is created with following details <br><br>
                       Work Unit: %s <br>
                       Plan Version: %s <br>
                       Fiscal Year: %s <br>
                       Please approve""" % (ref, arg1, arg2, arg3)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
    def approve(self):
        stage="is Approved"
        for val in self:
            if val.work_unit:
                rec = self.env["planning.approval"].sudo().search([("operating_unit", "=", val.work_unit.name)])
                if rec.authorized_approver.sudo().name==self.env.user.name:
                    val.approve_status='approved'
                    usr = self.env["res.partner"].search([("name", "=", val.requestor)])
                    self.mail_channel_msgs1(usr.id, usr.name, self.work_unit.name, self.plan_version.plan_version, self.fiscal_year, stage)
                else:
                    raise ValidationError('Sorry! You can not Approve this work unit')
    def reject(self):
        stage="is Rejected"
        for val in self:
            if val.work_unit:
                rec = self.env["planning.approval"].sudo().search([("operating_unit", "=", val.work_unit.name)])
                if rec.authorized_approver.sudo().name==self.env.user.name:
                    val.approve_status='rejected'
                    usr = self.env["res.partner"].search([("name", "=", val.requestor)])
                    self.mail_channel_msgs1(usr.id, usr.name, self.work_unit.name, self.plan_version.plan_version, self.fiscal_year, stage)
                else:
                    raise ValidationError('Sorry! You can not reject this work unit') 
	
    def mail_channel_msgs1(self, rec_id, ref, arg1, arg2, arg3, arg4):
        print("*************")
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear %s <br>A Workunit Manpower Plan is created with following details <br><br>
                       Work Unit: %s <br>
                       Plan Version: %s <br>
                       Fiscal Year: %s  <b><u>%s</u></b><br>
                       """ % (ref, arg1, arg2, arg3, arg4)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
		
    def populate_ou_values(self):
        print("Updating Manpower  Plan")
        self.env.cr.execute('SELECT update_ou_manpower_planning_cost()')

    # def submit(self):
    #     print("self",self)
    # def approve(self):
    #     print(self)
    def unlink(self):
        for val in self.manpower_plan_id:
            val.unlink()
        return super(ManpowerPlan, self).unlink()
    def confirm(self):
        if self.approve_status == 'approved':
            rec = self.env["planning.approval"].sudo().search([("operating_unit", "=", self.sudo().work_unit.name)])
            if rec.authorized_approver.sudo().name == self.env.user.name:
                self.status = "confirmed"
                print("status", self.status)
                print("self=================", self.plan_version)
                # print("self=================",self.manpower_plan_id.position)
                company_manpower_info = self.env["manpower.plan"].search(
                    [("plan_version", "=", self.plan_version.plan_version)])
                my_list = []
                print("company_manpower_info======================", company_manpower_info.plan_version)
                #####################raghu code##################
                if company_manpower_info.company_manpower_plan_id:
                    for val in self.manpower_plan_id:
                        if val.position:
                            print("val1", val.position.name)
                            for val2 in company_manpower_info.company_manpower_plan_id:
                                print("val2", val2.position.name)
                                print("condition======", val.position.name == val2.position.name)
                                if val.position.id == val2.position.id:
                                    print("")
                                    val2.write({"july": val.july + val2.july,
                                                "august": val.august + val2.august, "september": val.september + val2.september,
                                                "october": val.october + val2.october, "november": val.november + val2.november,
                                                "december": val.december + val2.december,
                                                "january": val.january + val2.january, "february": val.february + val2.february,
                                                "march": val.march + val2.march,
                                                "april": val.april + val2.april, "may": val.may + val2.may,
                                                "june": val.june + val2.june
                                                })
                            found = all(
                                val.position.id != val3.position.id for val3 in company_manpower_info.company_manpower_plan_id)
                            # print( "position="+val.position.name+" status="+str(all_are_b))
                            if found:
                                self.env["manpower.plan.jobs"].create({"position": val.position.id, "grade": val.grade.id,
                                                                       "plan_version": self.plan_version.plan_version,
                                                                       "july": val.july,
                                                                       "august": val.august, "september": val.september,
                                                                       "october": val.october, "november": val.november,
                                                                       "december": val.december,
                                                                       "january": val.january, "february": val.february,
                                                                       "march": val.march,
                                                                       "april": val.april, "may": val.may, "june": val.june,
                                                                       "company_manpower_id": company_manpower_info.id})
    
                else:
                    for val in self.manpower_plan_id:
                        if val.position:
                            my_list.append((0, 0, ({"position": val.position.id, "grade": val.grade.id,
                                                    "plan_version": self.plan_version.plan_version, "july": val.july,
                                                    "august": val.august, "september": val.september,
                                                    "october": val.october, "november": val.november, "december": val.december,
                                                    "january": val.january, "february": val.february, "march": val.march,
                                                    "april": val.april, "may": val.may, "june": val.june}
                            )))
                    print("mylist=", my_list)
    
                    company_manpower_info.company_manpower_plan_id = my_list
            else:
                raise ValidationError('Sorry! you can not confirm this work unit.')
        else:
            raise ValidationError('Please finish the Approval Process before confirming')
####################################raghu code################################
    @api.onchange('plan_version')
    def _onchange_plan_version(self):
        print("id================================================",self.plan_version.id)
        company_procruitment=self.env['manpower.plan'].search([("id","=",self.plan_version.id)])
        # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — manpower.plan.fiscal_year,
        # plan_start_date and plan_end_date are all commented out on that model
        # (they depend on account.fiscal.year). Restore these three lines once
        # that module is installed and the fields are uncommented.
        # self.fiscal_year=company_procruitment.fiscal_year.name
        # self.plan_start_date=company_procruitment.plan_start_date
        # self.plan_end_date=company_procruitment.plan_end_date

    # @api.onchange('plan_version')
    # def _onchange_plan_version(self):
	    # if self.plan_version:
           # company_procruitment=self.env['manpower.plan'].search([("plan_version","=",self.plan_version)])
           # self.fiscal_year=company_procruitment.fiscal_year.name
           # self.plan_start_date=company_procruitment.plan_start_date
           # self.plan_end_date=company_procruitment.plan_end_date

    # @api.model
    # def create(self, vals):
    #     print("vals2=", vals)
    #     mylist=[]
    #     if "manpower_plan_id" in vals:
    #         for val in vals["manpower_plan_id"]:
    #             mylist.append(val[2]["position"])
    #         for n, i in enumerate(mylist):
    #                 if i in mylist[:n]:
    #                     get_position=self.env["manpower.plan.jobs"].search([("id","=",i)])
    #                     raise ValidationError(get_position.position.name+"already exists")
    #
    #     return super(ManpowerPlan, self).create(vals)
    # def write(self,vals):
    #     for val in self.manpower_plan_id:
    #         if "manpower_plan_id" in vals:
    #             for val2 in vals["manpower_plan_id"]:
    #                 print("vals2=", val.position, val2)
    #                 if val2[2] and "position" in val2[2]:
    #                     if val.position.id==val2[2]["position"]:
    #                         raise ValidationError(val.position.position.name + "  Position Already Exists")
    #                 else:
    #                     if val2[1]:
    #                         get_position = self.env["manpower.plan.jobs"].search([("id", "=", val2[1])])
    #                         if val.position.id == get_position.id:
    #                             raise ValidationError(val.position.position.name + " Position Already Exists")
    #     return super(ManpowerPlan, self).write(vals)



class Requirements2(models.Model):
    _name = "manpower.plan.ou.jobs"
    _description = "Requirements"
    _rec_name = "grade"

    # vendor_name = fields.Many2one("res.partner","Vendor Name")
    manpower_id = fields.Many2one('manpower.plan.ou', 'Manpower Plan')
    work_unit2 = fields.Many2one("operating.unit",related="manpower_id.work_unit", string="Work Unit")
    # ACCOUNTING MODULE NOT INSTALLED — 'account.analytic.account' model does not exist, and its source field department2 above is also commented out
    # department2 = fields.Many2one("account.analytic.account",related="manpower_id.department2", string="Department")
    plan_version = fields.Integer(string="Plan Version",related="manpower_id.plan_version.plan_version")
    position = fields.Many2one("hr.job",string="Position")
    # position = fields.Many2one("manpower.plan.jobs",string="Position")
    job_name = fields.Many2one("employee.job",string="Job Name")

    # product  = fields.Char("Product")
    job_id =  fields.Many2one("hr.job","Position")
    grade = fields.Many2one("employee.grade","Grade")
    category = fields.Char(string="Category", compute="_compute_category", store=True)
    # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — 'account.fiscal.year' model
    # does not exist in this database. Uncomment once that module is installed.
    # fiscal_year = fields.Many2one("account.fiscal.year", "Fiscal Year")
    plan_start_date = fields.Date("Plan Start Date")
    plan_end_date = fields.Date("Plan End Date")
    status = fields.Char("Status")
    july = fields.Integer("July")
    august = fields.Integer("Aug")
    september = fields.Integer("Sep")
    october = fields.Integer("Oct")
    november = fields.Integer("Nov")
    december = fields.Integer("Dec")
    january = fields.Integer("Jan")
    february = fields.Integer("Feb")
    march = fields.Integer("Mar")
    april = fields.Integer("April")
    may = fields.Integer("May")
    june = fields.Integer("June")
    total = fields.Integer("Total", compute="_compute_total")
    position_cost = fields.Float("Grade Cost")
    estimated_cost = fields.Float("Estimated Cost")
  
  
    @api.depends('july', 'august', 'september', 'october', 'november', 'december', 'january', 'february', 'march',
                 'april', 'may', 'june')
    def _compute_total(self):
        for rec in self:
            rec.total = rec.july + rec.august + rec.september + rec.october + rec.november + rec.december + rec.january + rec.february + rec.march + rec.april + rec.may + rec.june
			
    @api.depends('job_id')
    def _compute_category(self):
        for val in self:
            print("******************************************")
            if val.position:
                print("**********************", val.position.name)
                rec = self.env["hr.job"].search([("name", "=", val.position.name)])
                val.category=rec.employee_category
                return val.category
            else:
                val.category=""
                return val.category
            
         
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

    # @api.onchange('product')
    # def _onchange_product(self):
    #     print("product=====================", self.product)
    #     print("employee_name=====================", self.product.description)
    #     self.description =  self.product
    #     self.category = self.product.categ_id

    @api.onchange('position')
    def _onchange_position(self):
        if self.position:
            # Assuming there is a field 'grade' in 'hr.jobs' that stores the related grade ID
            self.grade = self.position.grade.id
        else:
            self.grade = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            print("vals=", vals)
            # get_manpower=self.env["manpower.plan.ou"].search([("id","=",vals["manpower_id"])])
            # vals["work_unit2"] = get_manpower.work_unit.id
            # vals["department2"] = get_manpower.department.id
            # vals["plan_version"]=get_manpower.plan_version.plan_version
        return super().create(vals_list)

    def write(self, vals):
        # get_manpower = self.env["manpower.plan.ou"].search([("id", "=", vals["manpower_id"])])
        # vals["work_unit2"] = get_manpower.work_unit.id
        # vals["department2"] = get_manpower.department.id
        # vals["plan_version"] = get_manpower.plan_version.plan_version
        return super(Requirements2, self).write(vals)


    def save(self):
        print("procurement_plan_ou_products====================",self)
        text=0
        text1=0
        text2=0
        text3=0
        text4=0
        text5=0
        text6=0
        text7=0
        text8=0
        text9=0
        text10=0
        text11=0

        for val in self:
            print("positionnew===============",val.position)
            text=text+int(val.july)
            text1=text1+int(val.august)
            text2=text2+int(val.september)
            text3=text3+int(val.october)
            text4=text4+int(val.november)
            text5=text5+int(val.december)
            text6=text6+int(val.january)
            text7=text7+int(val.february)
            text8=text8+int(val.march)
            text9=text9+int(val.april)
            text10=text10+int(val.may)
            text11=text11+int(val.june)
            print("june============",text)
            # manpower_info = self.env["manpower.plan"].search([('plan_version',"=",int(self.manpower_id.plan_version.plan_version))])
            manpower_info = self.env["manpower.plan"].search([])
            print("manpower_info=",manpower_info)
            for val2 in manpower_info.company_manpower_plan_id:
                print("val2 position===============================",val2.position)
                if val.position == val2.position :
                    print("tesxt=====================",val2.july)
                    val2.write({"july": text, "august":text1 ,
                               "september": text2,
                               "october": text3 , "november": text4,
                               "december": text5 ,
                               "january": text6, "february": text7 ,
                               "march": text8,
                               "april": text9, "may": text10, "june": text11
                               })
	
class FinancialImplications(models.Model):
    _name = "financial.implications"
    _description = "Financial Implications"
    

    
    financial_implications_id = fields.Many2one('manpower.plan.ou', 'Financial Implications')
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

