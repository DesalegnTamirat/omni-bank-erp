from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.http import request
from datetime import datetime, timedelta
from datetime import datetime
from datetime import date

class InheritedHRContract(models.Model):
    _inherit = 'hr.version'

    _rec_name = 'employee_id'


class EmployeeProbation(models.Model):
    _name = "emp.probation.criteria"
    _rec_name = "emp_evaluation_criteria"

    emp_evaluation_criteria = fields.Char(string="Evaluation Criteria")
    coefficient = fields.Integer(string="Coefficient")


class ProbationAssessmentForm(models.Model):
    _name = "probation.assessment.form"
    _rec_name = "name_of_probationer"

    prob_sequence = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                               default=lambda self: _('New'))
    name_of_probationer = fields.Many2one("hr.version", string="Name of Probationer", domain=[('state', '=', 'probation')])
    position_title = fields.Char(string="Position Title", readonly=True)
    place_of_assessment = fields.Char(string="Place of Assessment")
    employment_date = fields.Date(string="Employment Date", related="name_of_probationer.first_contract_date")
    from_date = fields.Date(string="From", related="name_of_probationer.contract_date_start")
    to_date = fields.Date(string="To", related="name_of_probationer.contract_date_end")
    pro_assess_form = fields.One2many("probation.assessment.form.criteria", "prob_cri", string="Probation Criteria")
    evaluation_period = fields.Char(string="Evaluation Period", compute="_compute_evaluation_period", store=True)
    in_charge = fields.Many2one("hr.employee", string="TDD In-charge Officer")
    sender = fields.Char(string="Sender")
    state = fields.Selection([("draft", "Draft"), ("notify", "Notified Hr"), ("evaluate", "Evaluated"), ("confirm_permenancy", "Confirmed"), ("reject", "Rejected"), ('terminate_contract', 'Terminated'),
                 ("inform_in_charge", "Informed")], string="State", default="draft")
    status = fields.Selection([("draft", "Draft"), ("notify_deligation", "Notify"), ("assess_evaluate", "Evaluate")], string="Status", default="draft")
    # status1 = fields.Selection([("draft", "Draft"), ("notify_deligation", "Notified Hr"), ("evaluate", "Evaluated"), ("Confirm Permenancy", "Confirmed"), ("reject", "Rejected"),
                              # ("inform_in_charge", "Informed)], string="Status", default="draft")
    total = fields.Integer(string="Total", compute="_compute_total")
    emp_prob_delig_team_id = fields.One2many("emp.probation.delegation.team", 'new_emp_prob_del_id', string="Employee probation Assesment Delegation Team")
    assessment_comments = fields.Text(string="Comments")
    
	
    def _compute_total(self):
        for rec in self:
            rec.total = sum(val.score for val in rec.pro_assess_form)
			
			
    def notify_deligation(self):
        for com in self.emp_prob_delig_team_id:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.prob_sequence, self.position_title)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.prob_sequence, self.position_title)
        self.status = "notify_deligation"
        self.state = "notify"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Sent'),
                'message': _('Delegation team notified successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear Committee<br>Please approve the Probation Assessment of following details <br>
             			 Reference number is <b>%s<b> <br>
						 Position: <b>%s<b>
                        <br><br>  Kindly approve.
                                """ % (ref, arg1)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
			
    def assess_evaluate(self):
        n=0
        usr = self.env.user.name #  name of login user details
        for val in self.emp_prob_delig_team_id:
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
        for vals in self.emp_prob_delig_team_id:
            mem_cnt=mem_cnt+1
            if vals.approve==True:
                cnt=cnt+1
        if cnt==mem_cnt:
            self.status="assess_evaluate"
            self.state = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Evaluation Recorded'),
                'message': _('Evaluation recorded.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


    @api.constrains('name_of_probationer')
    def set_position_title(self):
        for record in self:
            if record.name_of_probationer:
                probationer = self.env["hr.version"].search([("name", "=", record.name_of_probationer.name)])
                record.position_title = probationer.job_id.name

            else:
                record.position_title = False
            return record.position_title

    @api.constrains('name_of_probationer')
    def set_position_place(self):
        for record in self:
            if record.name_of_probationer:
                probationer = self.env["hr.version"].search([("name", "=", record.name_of_probationer.name)])
                record.place_of_assessment= probationer.operating_unit_id.name

            else:
                record.place_of_assessment = False
            return record.place_of_assessment

    @api.depends('from_date', 'to_date')
    def _compute_evaluation_period(self):
        for record in self:
            if record.from_date and record.to_date:
                record.evaluation_period = f"from {record.from_date.strftime('%Y-%m-%d')} to {record.to_date.strftime('%Y-%m-%d')}"
            else:
                record.evaluation_period = False

    def inform_in_charge(self):
        for rec in self:
            usr = self.env["res.partner"].search([("name", "=", rec.in_charge.name)])
            msg = "Dear Sir<br>Here are the details of Probation Assessment of <br>Employee:  "
            msg2 = "Please Look in to it"
            self.mail_channel_msgs1(usr.id, msg, rec.name_of_probationer.employee_id.name, rec.position_title,
                                    rec.place_of_assessment, msg2)
        self.state="inform_in_charge"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('In-charge Informed'),
                'message': _('TDD In-charge Officer has been informed.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


    # def inform_manager(self):
        # for rec in self:
            # rec.sender = self.env.user.name
            # mng = self.env["hr.employee"].search([("name", "=", rec.name_of_probationer.employee_id.name)])
            # print("*************parent_id", mng.parent_id)
            # mng_name = self.env["hr.employee"].search([("name", "=", mng.parent_id.name)])
            # print("************mng_name", mng_name)
            # usr = self.env["res.partner"].search([("name", "=", mng_name.name)])
            # msg = "Dear Sir<br>Here are the details of Probation Assessment of <br>Employee:  "
            # msg2 = "Please Approve"
            # self.mail_channel_msgs1(usr.id, msg, rec.name_of_probationer.name, rec.position_title,
                                    # rec.place_of_assessment, rec.evaluation_period, msg2)
        # self.state = "inform_manager"
    def confirm_permenancy(self):
        # for rec in self:
            # usr = self.env["res.partner"].search([("name", "=", rec.sender)])
            # msg = "Dear Team<br>Probation Assessment of <br>Employee:  "
            # msg2 = "is <b><u>Approved</u></b>"
            # self.mail_channel_msgs1(usr.id, msg, rec.name_of_probationer, rec.position_title,
                                    # rec.place_of_assessment, rec.evaluation_period, msg2)
       val = self.env["hr.version"].search([("employee_id", "=", self.name_of_probationer.employee_id.name)])
       value = {
                 "approval_status": "approved",
                 "state": "open"
	         }   
       yes = val.write(value)
       val.action_approve()
       self.state = "confirm_permenancy"
       return {
           'type': 'ir.actions.client',
           'tag': 'display_notification',
           'params': {
               'title': _('Permanency Confirmed'),
               'message': _('Employee confirmed as permanent.'),
               'type': 'success',
               'sticky': False,
               'next': {'type': 'ir.actions.client', 'tag': 'reload'},
           },
       }
	   
    def reject(self):
	    self.state = "reject"
	    return {
	        'type': 'ir.actions.client',
	        'tag': 'display_notification',
	        'params': {
	            'title': _('Probation Rejected'),
	            'message': _('Probation rejected.'),
	            'type': 'warning',
	            'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
	        },
	    }

    def terminate_contract(self):
        # for rec in self:
            # usr = self.env["res.partner"].search([("name", "=", rec.sender)])
            # msg = "Dear Team<br>Probation Assessment of <br>Employee:  "
            # msg2 = "is <b><u>Rejected</u></b>"
            # self.mail_channel_msgs1(usr.id, msg, rec.name_of_probationer, rec.position_title,
                                    # rec.place_of_assessment, rec.evaluation_period, msg2)
        self.state = "terminate_contract"
        val = self.env["hr.version"].search([("employee_id", "=", self.name_of_probationer.employee_id.name)])
        value = {
                  "state": "cancel"
        }
        val.write(value)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contract Terminated'),
                'message': _('Contract terminated.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def mail_channel_msgs1(self, rec_id, msg, ref, arg1, arg2, msg2):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """%s <br>%s<br>
                        Position: %s<br>
                        Work Unit: %s<br>
                        <br>%s
                                        """ % (msg, ref, arg1, arg2, msg2)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('prob_sequence') or vals.get('prob_sequence') == _('New'):
                vals['prob_sequence'] = self.env['ir.sequence'].next_by_code('probation.assessment.form') or _('New')
        return super().create(vals_list)


class ProbationAssessmentCriteriaForm(models.Model):
    _name = "probation.assessment.form.criteria"

    evaluation_criteria = fields.Many2one("emp.probation.criteria", string="Evaluation Criteria")
    rating = fields.Selection([("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5")], string="Rating")
    coefficient = fields.Integer(string="Coefficient", related="evaluation_criteria.coefficient")
    score = fields.Integer(string="Score", readonly=True, compute="_compute_score")
    prob_cri = fields.Many2one("probation.assessment.form", string="Probation Criteria")

    def _compute_score(self):
        for det in self:
            if det.rating and det.coefficient:
                det.score = int(det.rating) * det.coefficient
            else:
                det.score = 0
	
class EmpProbationDelegation(models.Model):
    _name = "emp.probation.delegation.team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    new_emp_prob_del_id = fields.Many2one("probation.assessment.form", string="Employee probation Assessment Delegation Team")
