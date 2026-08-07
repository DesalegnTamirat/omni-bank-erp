from odoo import api, models, fields, _
import base64
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError

from odoo import models, fields, api
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



class EmployeeTransferServiceRequest(models.Model):
    _name = "emp.transfer.service.request"
    _description = "Employee Transfer Service Request Form"
    _rec_name = "requestor_name"

    emp_tra_service_req = fields.Char(string='Employee Service Request Form', required=True, copy=False, readonly=True,
                                      default=lambda self: _('New'))
    requestor_name = fields.Char(string="Requestor Name" , readonly=True)
    attachment = fields.Many2many('ir.attachment', 'ir_emp_ser_transfer_req_attachment_rel',
                                  'emp__transfer_serv_req_attach_ids',
                                  string="Attachment")
    operating_unit = fields.Many2one('operating.unit', help="Operating_unit", readonly=True)
    department = fields.Many2one('hr.department', 'Department', readonly=True)
    job_position = fields.Many2one('hr.job', string='Job Position', help="Job Position", readonly=True)
    job_grade_t = fields.Char(string='Job Grade', help="Job Grade", readonly=True)
    job_category_t = fields.Char(string='Job Category', help="Job Category", readonly=True)
    employee_category = fields.Many2one('hr.contract.type', string="Employee Category")
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              string='Gender', default='male', readonly=True)
    contract_start_date = fields.Date("Contract start date", readonly=True)
    active_phone_num = fields.Char("Active Phone Num", readonly=True)
    active_email_id = fields.Char("Active E-mail ID", readonly=True)
    transfer_requested_date = fields.Date(string='Transfer Requested Date', help="Transfer Requested Date")
    reason_for_transfer = fields.Text(string='Reason for Transfer', help="Reason for transfer")
    requested_operating_unit = fields.Many2one('operating.unit', string='Requested Operating Unit',
                                               help='Requested Operating Unit')
    location_preference_2 = fields.Many2one("operating.unit", string="Location Preference 2")
    location_preference_3 = fields.Many2one("operating.unit", string="Location Preference 3")
    status=fields.Char("Status")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('emp_tra_service_req') or vals.get('emp_tra_service_req') == _('New'):
                vals['emp_tra_service_req'] = self.env['ir.sequence'].next_by_code('emp.transfer.service.request') or _('New')
        return super().create(vals_list)

    def populate(self):
        for val in self:
            val.requestor_name = self.env.user.name
            vals = self.env["hr.version"].search([("employee_id.name", "=", self.env.user.name)])
            value = self.env["hr.employee"].search([("name", "=", self.env.user.name)])
            val.job_position = value.job_position
            val.job_grade_t = value.job_grade.grade_code
            val.job_category_t = value.job_position.employee_category
            val.operating_unit = value.default_operating_unit_id
            val.department = value.department_id
            val.gender = value.gender
            val.contract_start_date = vals.contract_date_start
            val.active_phone_num = value.personal_phone
            val.active_email_id = value.work_email
            # print("********", value, val.job_grade_t, val.job_grade_t)

    def request(self):
        rec = "Transfer Request"
        val = self.env["service.request.type"].search([("service_request_type", "=", rec)])
        usr = self.env["res.partner"].search([("name", "=", val.authorizer.name)])
        if not usr:
            raise ValidationError('Approver is not an Employee')
        else:
            self.mail_channel_msgs(usr.id, self.emp_tra_service_req, self.requestor_name)
        p_id = self.id
        # self.env.cr.execute('SELECT notify_external_applicant(%s)', (p_id,))
        self.env.cr.execute('SELECT populate_transfer_request(%s)', (p_id,))
        #self.status = 'notify'

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear Authorizer<br>A New Transfer Service request is raised with following details.<br><br>
                         Reference No: %s<br>
                         Requestor Name: %s<br>
                         <br><br>  Kindly approve.
                                """ % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
