from odoo import api, models, fields, _


class TransformDetails(models.Model):
    _name = "transfer.form"	
    _description = "Transform Form"
    _rec_name = "ref_num"
    employee_id = fields.Many2one('hr.employee', string='Employee', help="Employee")
    # ref_num = fields.Char(string='Ref Num', help="Reference", required=True)
    ref_num = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    sr_ref = fields.Char(string='SR Reference', help="Reference" , readonly=True)
    employee_name = fields.Many2one('hr.employee', string='Employee Name', help="Employee", required=True)
    operating_unit = fields.Many2one('operating.unit', help="Operating_unit" , readonly=True)
    department = fields.Many2one('hr.department', 'Department' , readonly=True)
    job_position = fields.Many2one('hr.job', string='Job Position', help="Job Position" , readonly=True)
    job_grade = fields.Many2one('employee.grade', string='Job Grade', help="Job Grade" , readonly=True)
    job_category = fields.Many2one('employee.job', string='Job Category', help="Job Category" , readonly=True)
    employee_category = fields.Many2one('hr.contract.type', string="Employee Category" , readonly=True)
    employee_category1 = fields.Many2one('hr.contract.type', string="Employee Category", readonly=True)
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              string='Gender', default='male' , readonly=True)
    contract_start_date = fields.Date("Contract start date" , readonly=True)
    active_phone_num = fields.Char("Active Phone Num" , readonly=True)
    active_email_id = fields.Char("Active E-mail ID" , readonly=True)
    releiving_date = fields.Date("Releiving Date")
    reporting_date = fields.Date("Reporting Date")
    priority_transfer = fields.Selection([('yes', 'Yes'), ('no', 'No')], string="Priority Transfer")
    period_since_final_written_warning = fields.Float(string="Months Since Final Written Warning" , readonly=True)
    period_since_last_promotion = fields.Float(string="Months Since Last Promotion" , readonly=True)
    period_since_last_transfer = fields.Text(string="Months Since Last Transfer" , readonly=True)
    service_in_the_bank = fields.Char(string="Service in the Bank" , readonly=True)
    pms_score = fields.Float(string="PMS Score" , readonly=True)
    location_preference_2 = fields.Many2one("operating.unit", string="Location Preference 2" , readonly=True)
    location_preference_3 = fields.Many2one("operating.unit", string="Location Preference 3" , readonly=True)
    assigned_operating_unit = fields.Many2one("operating.unit", string="Assigned Operating Unit")
    # operating_unit = fields.Char(related="employee_id.operating_unit", related_sudo=False, readonly=False)
    # department = fields.Char(related="employee_id.department.id", related_sudo=False, readonly=False)
    # job_position = fields.Char(related="employee_id.job_position", related_sudo=False, readonly=False)
    # job_grade = fields.Char(related="employee_id.job_grade", related_sudo=False, readonly=False)
    # job_category = fields.Char(related="employee_id.job_category", related_sudo=False, readonly=False)
    requested_operating_unit = fields.Many2one('operating.unit', string='Requested Operating Unit',
                                               help='Requested Operating Unit', readonly=True)
    hardship_allowance = fields.Float(string="Hardship Allowance" , readonly=True)
    disturbance_allowance = fields.Float(string="Disturbance Allowance" , readonly=True)
    department1 = fields.Many2one('hr.department', 'Department' , readonly=True)
    job_title = fields.Many2one('hr.job', string='Job Position', help="Job Position")
    job_grade1 = fields.Many2one('employee.grade', 'Job Grade', readonly=True)
    hr_period=fields.Integer(string="hr_period")
    job_category1 = fields.Many2one('employee.job', 'Job Category', readonly=True)
    transfer_requested_date = fields.Date(string='Transfer Requested Date', help="Transfer Requested Date" )
    reason_for_transfer = fields.Text(string='Reason for Transfer', help="Reason for transfer" , readonly=True)
    responsible = fields.Many2one('hr.employee', string='Responsible ', help="Responsible ")
    authorized_by = fields.Many2one('hr.employee', string='Authorized By ', help="Authorized by ")
    authorized_date = fields.Date(string='Authorized Date', help="Authorized Date")
    approved_by = fields.Many2one('hr.employee', string='Approved By', help="Approved by")
    approved_date = fields.Date(string='Approved Date', help="Approved Date")
    status = fields.Char(string='Status', help="Status")
    transfer_initiated_by = fields.Selection(
        [('company', 'Company'), ('employee', 'Employee')],
        string='Transfer Initiated by', default='company')
    new_reporting_manager = fields.Many2one("hr.employee", "New Reporting Manager")
    status_del = fields.Selection([("notify", "notify"), ("evaluate", "Evaluate")])
    doc_attachment_id8 = fields.Many2many('ir.attachment', 'doc_attach_rel2', 'doc_id9', 'attach_id10',
                                          string="Attachment",
                                          help='You can attach the copy of your document', copy=False)
    transform_details = fields.One2many("hr.transform.salary", "transform_id", "Supplementary Salary Details")
    state = fields.Selection([('draft', 'Draft'), ('populate', 'Populated'), ('authorize', 'Authorized'), ('approve', 'Approved'), ('reject', 'Rejected')], string="State", default="draft")
    transform_del_id = fields.One2many("transfer.delegation.team", "trn_form_del_id", "Transfer form Delegation team")
    cc_workunits = fields.Many2many("operating.unit", string="CC To:", help="Enter the Workunits to be copied")

    def notify(self):
        for com in self.transform_del_id:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.ref_num, self.job_position.name)
					# self.mail_channel_msgs(usr.id, self.ref_num, self.job_position.name, self.type_of_employment)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.ref_num, self.job_position.name)
					# self.mail_channel_msgs(usr.id, self.ref_num, self.job_position.name, self.type_of_employment)
        self.status_del = "notify"

# def mail_channel_msgs(self, rec_id, ref, arg1, arg2):
    def mail_channel_msgs(self, rec_id, ref, arg1):
            # print("*************")
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear Committee<br>A New Job vacancy form is created with following details.<br><br>
                         Reference No: %s<br>
                         Job: %s<br>
                            """ % (ref, arg1)
								 # Type of Employment: %s<br><br>  Kindly approve.
								# """ % (ref, arg1, arg2)
								
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def evaluate(self):
        # print("**************vacancy evaluate")
        n=0
        usr = self.env.user.name #  name of login user details
        # print("******************usr", usr)
        for val in self.transform_del_id:
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
        for vals in self.transform_del_id:
            mem_cnt=mem_cnt+1
            if vals.approve==True:
                cnt=cnt+1
        if cnt==mem_cnt:
            self.status_del="evaluate"
				
    @api.onchange('employee_name')
    def _onchange_employee_info(self):
        self.department = self.employee_name.department_id
        self.job_position = self.employee_name.contract_id.job_id.id
        self.job_title = self.employee_name.contract_id.job_id.id
        self.operating_unit = self.employee_name.contract_id.operating_unit_id.id
        self.job_grade = self.employee_name.contract_id.job_grade.id
        self.job_grade1 = self.employee_name.contract_id.job_grade.id
        self.job_category = self.employee_name.contract_id.job_category.id
        self.job_category1 = self.employee_name.contract_id.job_category.id
        self.contract_start_date = self.employee_name.contract_id.contract_date_start

    @api.onchange('requested_operating_unit')
    def _onchange_requested_operating_unit(self):
        pass

    def authorize(self):
        self.state="authorize"

    def populate(self):
        p_id=self.id
        # print("Populate Button")
        # print("Transfer Id is=========", p_id)
        self.env.cr.execute('SELECT populate_transfer_details(%s)', (p_id,))
        self.env.cr.execute('SELECT compute_hardship_allowance_at_transfer(%s)', (p_id,))

        
        self.state = "populate"

    def reject(self):
        self.state="reject"

    def approve(self):
        p_id=self.id
        contract_info = self.env["hr.version"].search([('employee_id', '=', self.employee_name.id)])

        vals = {
            "employee_id": self.employee_name.id,
            "operating_unit_id": self.assigned_operating_unit.id,
            "department_id": self.department1.id,
            "job_id": self.job_title.id,
            "job_grade": self.job_grade1.id,
            "job_category": self.job_category1.id,
        }
        contract_info.write(vals)

        vals2 = {
            "employee_id": self.employee_id,
            "status": "approved",
            'approved_date': self.transfer_requested_date
        }
        status = self.env["transfer.form"].search([('employee_name', '=', self.employee_name.id)])
        status.write(vals2)

        vals3 = {
            "employee_id": self.employee_name.id,
            "from_operating_unit2": self.operating_unit.id,
            "from_department2": self.department.id,
            "from_position2": self.job_position.id,
            "from_grade2": self.job_grade.id,
            "date2": self.approved_date,
            "to_operting_unit2": self.assigned_operating_unit.id,
            "to_department2": self.department1.id,
            "to_position2": self.job_title.id,
            "to_grade2": self.job_grade1.id
        }
        history = self.env["transfer.history"].create(vals3)
        emp_det = self.env["hr.employee"].search([('name', '=', self.employee_name.name)])
        val4 = {
           "default_operating_unit_id": self.assigned_operating_unit.id,
           "job_position": self.job_title
        }
        emp_det.write(val4)
        self.env.cr.execute('SELECT update_reporting_manager(%s)', (p_id,))
        self.state = "approve"
        

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ref_num') or vals.get('ref_num') == _('New'):
                vals['ref_num'] = self.env['ir.sequence'].next_by_code('transfer.form') or _('New')
        return super().create(vals_list)


class transform_multi_record(models.Model):
    _name = "hr.transform.salary"
    _description = "salary  Details"
    # PAYROLL MODULE NOT INSTALLED — was _rec_name="salary_rule"; that field is
    # commented out below. Pointing at internal_name instead. Revert once the
    # payroll module is installed.
    _rec_name = "internal_name"
    transform_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # salary_rule = fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
    internal_name = fields.Char(string='Internal Name', help='Internal Name')
    value = fields.Float("Value")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")


# class HrEmployee(models.Model):
#     _inherit = 'hr.employee'
#     #


# class HrEmployeeDocument(models.Model):
#     _inherit = 'hr.employee.document'
#     _description = 'HR Employee Documents'
#
# class HrEmployee(models.Model):
#     _inherit = 'hr.employee'
#
#     def _document_count(self):
#         for each in self:
#             document_ids = self.env['transfer_form'].sudo().search([('employee_ref', '=', each.id)])
#             each.document_count = len(document_ids)
#     # def _document_count(self):
#     #     for each in self:
#     #         document_ids = self.env['transfer_form'].sudo().search([('employee_ref', '=', each.id)])
#     #         each.document_count = len(document_ids)
#
#     def document_view(self):
#         self.ensure_one()
#         domain = [
#             ('employee_ref', '=', self.id)]
#         return {
#             'name': _('Documents'),
#             'domain': domain,
#             'res_model': 'transfer_form',
#             'type': 'ir.actions.act_window',
#             'view_id': False,
#             'view_mode': 'tree,form',
#             'help': _('''<p class="oe_view_nocontent_create">
#                            Click to Create for New Documents
#                         </p>'''),
#             'limit': 80,
#             'context': "{'default_employee_ref': %s}" % self.id
#         }
#
#     document_count = fields.Integer(compute='_document_count', string='# Documents')
# #
class HrEmployeeAttachment_data(models.Model):
    _inherit = 'ir.attachment'

    doc_attach_rel2 = fields.Many2many('transfer.form', 'doc_attachment_id8', 'attach_id10', 'doc_id9',
                                       string="Attachment")
    # DOCUMENT MANAGEMENT MODULE NOT INSTALLED — 'hr.document' model does not
    # exist in this database. Uncomment once that module is installed.
    # attach_rel = fields.Many2many('hr.document', 'attach_id', 'attachment_id3', 'document_id',
    #                               string="Attachment")

class SupplementaryDelegation(models.Model):
    _name = "transfer.delegation.team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    trn_form_del_id = fields.Many2one("transfer.form", string="Transfer form Delegation team")
