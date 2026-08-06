import base64
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError
from psycopg2 import errors as pg_errors

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
from odoo import api, models, fields, _
from odoo import models, fields
from odoo.http import request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import base64
import mimetypes

import logging

_logger = logging.getLogger(__name__)

class LeaveRequest(models.Model):
    _name = "leave.request"
    _description = "Leave Request"
    _rec_name = "reference"

    reference = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    requester_name = fields.Many2one("hr.employee", "Requester Name" )
    delegated_name = fields.Many2one("hr.employee", "Delegated Employee" )
    leave_reason = fields.Selection(
        [('annual_leave', 'Annual Leave'), ('sick_leave', 'Sick Leave'), ('wedding_leave', 'Wedding Leave'),
         ('prenatal_leave', 'Prenatal Leave'),('postnatal_leave', 'Postnatal Leave'),
         ('paternity_leave', 'Paternity Leave'), ('mourning_leave', 'Mourning Leave'),
         ('on_duty', 'On Duty'),
         ('leave_without_pay', 'Leave Without Pay'),
         ('schedule_leave', 'Schedule Leave')], string='Leave Reason')
    comments = fields.Text(string="Comments")
    start_date = fields.Date(string="Start Date", help="Start Date" )
    end_date = fields.Date(string="End Date", help="End Date", store=True )
    start_half_day = fields.Boolean(string="Starting Half Day", help="Starting Half Day", readonly=True  )
    end_half_day = fields.Boolean(string="Ending Half Day", help="Ending Half Day", readonly=True  )
    #start_half_day = fields.Boolean(string="Starting Half Day", help="Starting Half Day" )
    #end_half_day = fields.Boolean(string="Ending Half Day", help="Ending Half Day" )
    job_grade = fields.Char(string='Job Grade')
    #job_category = fields.Char(string='Job Category')
    #job_grade = fields.Many2one("employee.grade",string='Job Grade')
    job_category = fields.Selection([('Managerial', 'Managerial'), ('Non Managerial', 'Non_Managerial')], string='Job Category')
    job_position = fields.Many2one("hr.job", string="Job Position", help="Job Position")
    operating_unit = fields.Many2one('operating.unit', 'Operating Unit')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              string='Gender', default='male')
    accrued = fields.Float(string="Accrued Leave Balance", readonly=True)
    # state = fields.Selection([('notify', 'Notify'), ('confirm_leave', 'Confirm Leave')], string="State")
    status = fields.Selection([('fetch', 'Fetch'), ('notification', 'Notify')], string="Status")
    #LeaveTypes_details =fields.Integer(string='LeaveTypes_details')
    # no_of_days = fields.Integer(string="No of days", compute="_compute_no_of_days")
    requester_user_id =fields.Integer(string='Requester User Id')
    manager_user_id =fields.Integer(string='Manager User Id')
    manager_partner_id =fields.Integer(string='Manager Partner Id')
    leave_attachment_ids = fields.Many2many('ir.attachment', 'ir_leave_attachment_rel', 'lv_attach_ids', string="Attachment")
    no_of_days = fields.Integer(string="No of Leave Requested Days", compute='_compute_leave_days', store=True)
    half_day = fields.Boolean(string="Half day", readonly=True )
    #half_day = fields.Boolean(string="Half day")
    details = fields.Selection([("morning", "Morning"), ("afternoon", "Afternoon")], string="Details")
    computed_leave = fields.Float(string="Computed Leave", readonly=True)


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('leave.request') or _('New')
        return super().create(vals_list)
    # def _compute_no_of_days(self):
        # for val in self:
            # d1 = datetime.strptime(str(val.start_date), '%Y-%m-%d')
            # d2 = datetime.strptime(str(val.end_date), '%Y-%m-%d')
            # d3 = d2 - d1
            # val.no_of_days= str(d3.days)
            # return val.no_of_days

    #@api.onchange('start_date', 'leave_reason')
    #def _onchange_start_date(self):
        #if self.leave_reason in ['wedding_leave', 'maternity_leave', 'paternity_leave', 'mourning_leave']:
        #    if self.start_date:
        #        self.end_date = self.start_date + timedelta(days=5)
        #    else:
        #        self.end_date = False  
        #else:
            #self.end_date = False  

   # @api.depends('start_date', 'leave_reason')
    #def _compute_end_date(self):
        #for rec in self:
            #if rec.leave_reason in ['wedding_leave','maternity_leave','paternity_leave','mourning_leave']:
                #if rec.start_date:
                    #rec.end_date = rec.start_date + timedelta(days=5)
                #else:
                    #rec.end_date = False
            #else:
                #rec.end_date = False



    @api.depends('start_date', 'end_date')
    def _compute_leave_days(self):
        for record in self:
            if record.start_date and record.end_date:
                # Calculate the number of days between start_date and end_date
                total_days = (record.end_date - record.start_date).days + 1  # Including both start and end dates
                record.no_of_days = total_days
            else:
                record.no_of_days = 0
				
    @api.onchange('requester_name')
    def _onchange_requester_name(self):
        self.job_grade = self.requester_name.job_grade.id
        self.job_category = self.requester_name.contract_id.job_category.id
        self.job_position = self.requester_name.job_position.id
        self.operating_unit = self.requester_name.default_operating_unit_id.id

    def action_fetch_leave(self):
        p_id = self.env.user.id
        n_id = self.id
        _logger.info("User ID: %s | Request ID: %s", p_id, n_id)
        self.env.cr.execute('SELECT update_alternate_parent(%s)', (p_id,))
        self.env.cr.execute('SELECT fetch_leave_requester(%s,%s)', (n_id,p_id,))
        self.env.cr.execute('SELECT populate_leave_request_accrued_leave(%s)', (n_id,))

    def n_compute_leave(self):
      for record in self:
        p_id = self.env.user.id
        n_id = record.id

        if record.leave_reason in ["annual_leave","wedding_leave","paternity_leave","schedule_leave","mourning_leave"]:
            try:
                # Call stored procedure for annual leave (savepoint so a
                # missing function does not abort the whole transaction).
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT populate_computed_actual_leaves(%s)', (n_id,))
                record.invalidate_recordset(['computed_leave'])
                continue
            except pg_errors.UndefinedFunction:
                # Stored procedure not installed - fall back to manual count.
                pass
        # Calculate total leave days manually (including weekends)
        if record.start_date and record.end_date:
            total_days = (record.end_date - record.start_date).days + 1
            record.computed_leave = total_days
        else:
            record.computed_leave = 0


       
    # def calling_accure_function(self):
        # print("*******************requester_name", self.requester_name, self.reference)
        # val = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
        # print("*****************employee details", val.name, val.id)
        # self.env["hr.leave"].update_leave_accrual(val.id, self.reference)


    def check_leave_balance(self):
        for record in self:
            self.env.cr.execute("SELECT get_eligible_leave(%s)", (record.requester_name.id,))
            val2 = self.env.cr.fetchone()  # Fetch the result
            accrued_leave = val2[0] if val2 else 0  # Extract the value from the fetched result
            record.accrued=accrued_leave
            return record.accrued
    
    def notification(self):
        if self.leave_reason and self.start_date and self.end_date and self.accrued and self.computed_leave:
            
            if self.leave_reason in ["annual_leave"]:
                if self.accrued + self.scheduled > self.computed_leave:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
                else:
                    raise ValidationError('You are not eligible to apply for leave beyond your accrued leave balance.')

            elif self.leave_reason in [ "schedule_leave"]:
                if self.accrued > self.computed_leave:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
                else:
                    raise ValidationError('You are not eligible to apply for leave beyond your accrued leave balance.')

            elif self.leave_reason in [ "leave_without_pay"]:
             if self.computed_leave == 30:
               if self.accrued <= 1  and  self.scheduled <= 1:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
               else:
                    raise ValidationError('You are not eligible to apply for leave without pay when you have accrued or scheduled leave balance greater than 1')
             else:
                   raise ValidationError('You are not eligible to apply for leave without pay beyond or below 30 days')
            elif self.leave_reason in [ "prenatal_leave"]:
                if self.computed_leave <= 30:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
                else:
                    raise ValidationError('You are not eligible to apply for prenatal leave beyond 30 working days')
            elif self.leave_reason in [ "postnatal_leave"]:
                if self.computed_leave <= 90:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
                else:
                    raise ValidationError('You are not eligible to apply for postnatal leave beyond 90 working days.')
            elif self.leave_reason in [ "mourning_leave","wedding_leave","paternity_leave"]:
                if self.computed_leave <= 3:
                    self.status = "notification"
                    rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    if rec.alternate_parent:
                        self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    else:
                        mgr = self.manager_partner_id
                        # print("Notification")
                        ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                        # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                        # print("************************", prn)
                        # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                        # print("************************", usr)
                        self.mail_channel_msgs1(mgr, self.reference,
                                                self.requester_name.name,
                                                self.operating_unit.name, self.job_category)
                    n_id = self.id
                    self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                    self.copy_attachments_from_leave_request()
                else:
                    raise ValidationError(f'You are not eligible to apply for {self.leave_reason} beyond 3 working days.')

            else:
                self.status = "notification"
                rec = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                if rec.alternate_parent:
                    self.mail_channel_msgs1(rec.alternate_parent, self.reference,
                                            self.requester_name.name,
                                            self.operating_unit.name, self.job_category)
                else:
                    mgr = self.manager_partner_id
                    # print("Notification")
                    ref = self.env["hr.employee"].search([("name", "=", self.requester_name.name)])
                    # prn = self.env["hr.employee"].search([("name", "=", ref.parent_id.name)])
                    # print("************************", prn)
                    # usr = self.env["res.partner"].search([("name", "=", prn.name)])
                    # print("************************", usr)
                    self.mail_channel_msgs1(mgr, self.reference,
                                            self.requester_name.name,
                                            self.operating_unit.name, self.job_category)
                n_id = self.id
                self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
                self.copy_attachments_from_leave_request()
        else:
            raise ValidationError('Please fill all relevant information before notifying the manager')
	
	
    def copy_attachments_from_leave_request(self):
        leave_request_managers = self.env['leave.request.manager'].sudo().search([('reference', '=', self.reference)])
        for leave_request_manager in leave_request_managers:
            leave_request_manager.write({
                'leave_mngr_attachment_ids': [(4, attachment.id) for attachment in self.leave_attachment_ids]
            })


    # def notify1(self):
        # print("notify")
        #n_id = self.id
		#p_id = self.env.user.id
        #print("Fetching Requester Details")
        # print("User  ID is ************************ ",p_id)
        # print("Request  ID is ************************ ",n_id)
        #self.env.cr.execute('SELECT leave_requester_inform_manager(%s)', (n_id,))
        
    def mail_channel_msgs1(self, rec_id, arg1, arg2, arg3, arg4):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = """Leave request Notification<br> Reference Number: %s <br>
                        Requester Name: %s <br>
                        Operating Unit: %s <br>
                        Job Category: %s <br>
                        Please approve""" % (arg1, arg2, arg3, arg4)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

	
	# def confirm_leave(self):
        # self.call_func_approval2()
        # # for val in self.LeaveTypes_details:
            # # number_of_days = 0
            # print(val.leave_type.id)
            # print(val.start_date)
            # # leave_comment = val.request_id.leave_reason + " " + val.request_id.comments
            # d1 = datetime.strptime(str(val.start_date), '%Y-%m-%d')
            # d2 = datetime.strptime(str(val.end_date), '%Y-%m-%d')
            # d3 = d2 - d1
            # number_of_days = str(d3.days)

            # # number_of_days = val.end_date - val.start_date
            # get_employee = self.env["hr.employee"].search([('user_id', "=", self.env.user.id)])
            # print("details", self.requester_name.name, get_employee.name)
            # print("number_of_days", number_of_days)
            # val2 = {
                # 'date_from': val.start_date,
                # 'date_to': val.end_date,
                # 'holiday_status_id': val.leave_type.id,
                # 'job_position': self.job_position.name,
                # 'job_category': self.job_category.job_name,
                # # 'job_grade': self.job_grade.grade_code,
                # 'request_date_from': val.start_date,
                # 'number_of_days': float(number_of_days),
                # 'request_date_to': val.end_date,
                # 'name': self.reference,
                # 'employee_id': self.requester_name.id,
                # # 'employee_id': get_employee.id,
                # 'leave_request_description': val.approver_comments
            # }
            # print("val2==============", val2)
            # history = self.env["hr.leave"].create(val2)
            # history.action_approve()
            # print("histryzzzzzzzzzzzzzzzzz", history)
        # self.state = "confirm_leave"


# class LeaveTypes(models.Model):
#     _name = "leave.request.types"
#     # request_id = fields.Many2one("leave.request", string="Leave", help="Leave Request", invisible="1")
#     leave_type = fields.Many2one("hr.leave.type", "Leave Type")
#     number_of_days = fields.Float('Duration in days',
#                                   help='Number of days of the time off request according to your working schedule. Used for interface.')
#     start_date = fields.Date(string="Start Date", help="Start Date")
#     end_date = fields.Date(string="End Date", help="End Date")
#     approver_comments = fields.Char(string="Approver Comments", help="Approver Comments")


# class HrLeaveDetails(models.Model):
#     _inherit = "hr.leave"
#     leave_request_description = fields.Text(string="Leave Request Description", help="Leave Request Description")
#     job_position = fields.Char(string="Job Position")
#     job_category = fields.Char(string="Job Category")


