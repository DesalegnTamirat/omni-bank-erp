from odoo import fields, models, api, _
from odoo.http import request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import base64
import mimetypes
from email.header import Header
from lxml import etree
from odoo.exceptions import ValidationError
from odoo.tools import float_round


class HrPayrollAdjustments(models.Model):
    _name = "hr.payroll.adjustments"
    _rec_name = "reference"

    reference = fields.Char(string='Ref', required=True, copy=False, readonly=True,
                            default=lambda self: _('New'))
    particulars = fields.Text(string="Particulars")
    transaction_date = fields.Date(string="Transcation Date")
    # commented out: 'hr.period' model does not exist in this module (belongs to an uninstalled payroll module)
    # payroll_period = fields.Many2one("hr.
    # period", string="Payroll Period")
    status = fields.Char(string="Status")
    state = fields.Selection([("notify", "Notify"), ("approve", "Approve"), ("upload_data", "Upload Data")],
                             string="state")
    adj_det_id = fields.One2many("adjustment.details", "adj_det", string="Adjustment Details")
    payroll_del_id = fields.One2many("payroll.adjust.delegation.team", "payroll_adj_delteam_id",
                                     string="Payroll Adjustment Delegation")

    @api.model
    def create(self, vals):
        if vals.get('reference', _('New')) == _('New'):
            vals['reference'] = self.env['ir.sequence'].next_by_code('hr.payroll.adjustments') or _('New')
            res = super().create(vals)
            return res

    def notify(self):
        for com in self.payroll_del_id:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.reference, self.particulars)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.reference, self.particulars)
        self.state = "notify"

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear Committee<br>Payroll Adjustment are raised with following details<br><br>
                         Reference No: %s<br>
                         Particulars: %s<br>
                         <br><br>  Kindly approve.
                                """ % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def evaluate(self):
        n = 0
        usr = self.env.user.name  # name of login user details
        for val in self.payroll_del_id:
            if val.status == "unavailable":
                if usr == val.employee_name:
                    raise ValidationError("Sorry!! you can not evaluate this bid")
                else:
                    n = n + 1
                    val.approve = True
                    break
            else:
                if val.employee_name.name == usr:
                    n = n + 1
                    val.approve = True
                    break
        if n == 0:
            raise ValidationError("Sorry!! You are not assigned for this Evaluation")
        cnt = 0
        mem_cnt = 0
        for vals in self.payroll_del_id:
            mem_cnt = mem_cnt + 1
            if vals.approve == True:
                cnt = cnt + 1
        if cnt == mem_cnt:
            self.status = "approve"

    def upload_data(self):
        p_id=self.id
        self.env.cr.execute('SELECT update_payroll_contract_details(%s)', (p_id,))
        self.state = "upload_data"


class AdjustmentDetails(models.Model):
    _name = "adjustment.details"

    employee_id = fields.Many2one("hr.employee", string="Employee Name")
    adjustment_nature = fields.Selection([("Amount Adjustment", "Amount Adjustment"),
                                          ("SALARY", "Salary Account"),
                                          ("PF", "PF Account"),
                                          ("OD", "OD Account"),
                                          ("INDEMNITY", "Cash Indemnity Account"),
                                          ("ASBEZA", "ASBEZA Account"),
										  ("COST SHARING", "Cost Sharing Balance"),]
                                          , string="Adjustment Type")
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # adjustment_type = fields.Many2one("hr.salary.rule", string="Salary Element", domain=[('adjust_amount_manually', '=', 'Yes')])
    bank_account = fields.Char(string="Employee Bank Account")
    #adjustment_amount = fields.Float(string="Adjustment Amount")
    #adjustment_amount = fields.float_round(value, precision_digits=2)
    adjustment_amount = fields.Float(string="Adjustment Amount", digits=(6, 2))
    adjustment_comments = fields.Text(string="Comments")
    adj_det = fields.Many2one("hr.payroll.adjustments", string="Adjustment Details")


class PayrollDelegation(models.Model):
    _name = "payroll.adjust.delegation.team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    payroll_adj_delteam_id = fields.Many2one("hr.payroll.adjustments", string="Payroll Adjustment Delegation")
