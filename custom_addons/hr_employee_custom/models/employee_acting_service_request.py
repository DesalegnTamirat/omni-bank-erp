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


class EmployeeServiceRequest(models.Model):
    _name = "emp.service.request"
    _description = "Employee Service Request Form"
    _rec_name = "requestor_name"

    emp_service_req = fields.Char(string='Employee Service Request Form', required=True, copy=False, readonly=True,
                                  default=lambda self: _('New'))
    requestor_name = fields.Char(string="Requestor Name" , readonly=True)
    attachment = fields.Many2many('ir.attachment', 'ir_emp_ser_req_attachment_rel', 'emp_serv_req_attach_ids',
                                  string="Attachment")

    requesting_operating_unit = fields.Many2one("operating.unit", string="Requesting operating Unit")
    acting_position = fields.Many2one("hr.job", "Vacant Position")
    acting_employee = fields.Many2one("hr.employee", "Acting Employee")
    suggested_employee = fields.Many2one("hr.employee", "Suggested Employee")
    acting_job_position = fields.Char("Acting Job Position" , readonly=True)
    job_grade = fields.Many2one('employee.grade', string='Job Grade', help="Job Grade" , readonly=True)
    job_category = fields.Many2one('employee.job', readonly=True)
    acting_work_unit = fields.Char("Acting Work Unit" , readonly=True)
    acting_reason = fields.Char("Acting Reason")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")
    status=fields.Char("Status")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('emp_service_req') or vals.get('emp_service_req') == _('New'):
                vals['emp_service_req'] = self.env['ir.sequence'].next_by_code('emp.service.request') or _('New')
        return super().create(vals_list)

    def populate(self):
        for val in self:
            val.requestor_name = self.env.user.name
            #value = self.env["hr.employee"].search([("name", "=", self.env.user.name)])
            #val.job_grade = value.job_grade
            #val.job_category = value.job_position.employee_category
            #print("********", value, val.job_grade, val.job_category)
        p_id = self.id
        # self.env.cr.execute('SELECT notify_external_applicant(%s)', (p_id,))
        self.env.cr.execute('SELECT update_acting_sr_form(%s)', (p_id,))
        #self.status = 'notify'

    def request(self):
        rec = "Acting"
        val = self.env["service.request.type"].search(
            [("service_request_type", "=", rec)])
        usr = self.env["res.partner"].search([("name", "=", val.authorizer.name)])
        if not usr:
            raise ValidationError('Approver is not an Employee')
        else:
            self.mail_channel_msgs(usr.id, self.emp_service_req, self.requestor_name)
        p_id = self.id
        # self.env.cr.execute('SELECT notify_external_applicant(%s)', (p_id,))
        self.env.cr.execute('SELECT populate_acting_request(%s)', (p_id,))
        #self.status = 'notify'

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear Authorizer<br>A New Acting Service request is raised with following details.<br><br>
                         Reference No: %s<br>
                         Requestor Name: %s<br>
                         <br><br>  Kindly approve.
                                """ % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )


