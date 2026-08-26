from odoo import api, models, fields,_ 
from odoo import models, fields
from odoo.http import request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from lxml import etree
import logging
import smtplib
import base64
import mimetypes
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)



class LeaveRequestManagerApproval(models.Model):
    _name = "leave.request.manager.approval.team"

    employee_name = fields.Many2one("res.users", string="Employee Name" )
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    leave_req_appr_id = fields.Many2one("leave.request.manager", string="Leave Request Manager Approval Team")
    
   
class LeaveRequest(models.Model):
    _name = "leave.request.manager"
    _description = "Leave Request"
    _rec_name = "reference"

    reference = fields.Char(string='Reference', readonly=True)
    requester_name = fields.Char(string="Requester Name", readonly=True)
    delegated_name = fields.Many2one("hr.employee", "Delegated Employee" )
    leave_reason = fields.Selection(
        [('annual_leave', 'Annual Leave'), ('sick_leave', 'Sick Leave'), ('wedding_leave', 'Wedding Leave'),
         ('prenatal_leave', 'Prenatal Leave'), ('postnatal_leave', 'Postnatal Leave'),
         ('paternity_leave', 'Paternity Leave'), ('mourning_leave', 'Mourning Leave'),
         ('special_leave', 'Special Leave'), 
         ('on_duty', 'On Duty'),
         ('leave_without_pay', 'Leave Without Pay'),
         ('schedule_leave','Schedule Leave')], string='Leave Reason',
        default='annual_leave', readonly=True)
    comments = fields.Text(string="Comments", readonly=True)
    start_date = fields.Date(string="Start Date", readonly=True)
    end_date = fields.Date(string="End Date", readonly=True)
    start_half_day = fields.Boolean(string="Starting Half Day", help="Starting Half Day" )
    end_half_day = fields.Boolean(string="Ending Half Day", help="Ending Half Day" )
    job_grade = fields.Char(string='Job Grade', readonly=True)
    job_category = fields.Selection([('Managerial', 'Managerial'), ('Non Managerial', 'Non_Managerial')], string='Job Category', readonly=True)
    job_position = fields.Char(string="Job Position", readonly=True)
    operating_unit = fields.Char('Operating Unit', readonly=True)
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                              string='Gender', default='male', readonly=True)
    accrued = fields.Float(string="Accrued Leave Balance", readonly=True)
    state = fields.Selection([('reject', 'Rejected'), ('confirm_leave', 'Leave Confirmed')], string="State")
    requester_user_id =fields.Integer(string='Requester User Id')
    manager_user_id =fields.Integer(string='Manager User Id')
    req_appr_id = fields.Many2one('res.users', string='Approver')
    LeaveTypes_details = fields.One2many("leave.request.types", "request_id", string="Leave Request",
                                         help="Leave Request")
    leave_mngr_attachment_ids = fields.Many2many('ir.attachment', 'ir_leave_mngr_attachment_rel', 'lv_mng_attach_ids', string="Attachment")
    half_day = fields.Boolean(string="Half day" , readonly=True)
    details = fields.Selection([("morning", "Morning"), ("afternoon", "Afternoon")], string="Half Day Timings")
    no_of_days = fields.Integer(string="No of Leave Requested Days")
    computed_leave = fields.Float(string="Computed Leave", readonly=True)
    apr_state = fields.Selection(
        [('draft', 'Draft'), ("notify", "notify"), ("approve", "Approve")], string="State", default="draft")
    leave_req_manager_aprvl_id = fields.One2many("leave.request.manager.approval.team", "leave_req_appr_id", string="Leave Request Manager Approval Team") 
	
    
    def notify(self):
     for com in self.leave_req_manager_aprvl_id:
        if com:
            # Validate job grade
           # self.env.cr.execute("""
           #     SELECT COUNT(*) 
            #    FROM hr_employee 
             #   WHERE user_id = %s 
              #  AND job_grade = '53'
          #  """, (com.employee_name.id,))
            self.env.cr.execute("""
                 SELECT COUNT(*)
                 FROM hr_employee
                 WHERE user_id = %s
                 AND ((job_grade = '54' AND  department_id = '655')OR (job_grade = '53' AND department_id <> '655')) 
             """, (com.employee_name.id,))
            count = self.env.cr.fetchone()[0]
            
            if count == 0:
                raise ValidationError(
                    f"Approver '{com.employee_name.name}'can not be approver. "
                    f"Only employees chief or district directories can be selected as approvers."
                )
            
            usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
            if not usr:
                raise ValidationError('Approver is not an Employee')
            else:
                self.mail_channel_msgs(usr.id, self.reference, self.requester_name)
                n_id = self.id
                self.env.cr.execute('SELECT leave_requester_inform_approver(%s)', (n_id,))
                self.apr_state = "notify"
        else:
            raise ValidationError('Please Define Approvers')

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = channel_id = channel
        message = """Dear Committee<br>A Leave Request is created with following details.<br><br>
                            Reference: %s<br>
                            Requestor Name: %s<br>
                            <br><br>  Kindly approve.
                                   """ % (ref, arg1)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def approve(self):
        current_user = self.env.user
        # New: Check who can approve based on leave reason
        if self.leave_reason == 'leave_without_pay':
           if self.req_appr_id.id != current_user.id:
            raise ValidationError("For Leave Without Pay, only the assigned approver can approve")
        else:
           if self.manager_user_id.id != current_user.id:
            raise ValidationError("Only the assigned manager can approve")
        n = 0
        for val in self.leave_req_manager_aprvl_id:
           if val.employee_name.id == current_user.id:  # Changed to ID comparison
            n = n + 1
            val.approve = True
           break
    
        if n == 0:
           raise ValidationError("Sorry!! You are not assigned for this Approval")
    
        cnt = 0
        mem_cnt = 0
        for vals in self.leave_req_manager_aprvl_id:
            mem_cnt = mem_cnt + 1
        if vals.approve == True:
            cnt = cnt + 1
    
        if cnt == mem_cnt:
           self.apr_state = "approve"

    def fetch(self):
        pass

    def check_leave_balance(self):
        for record in self:
            self.env.cr.execute("SELECT get_eligible_leave(%s)", (record.requester_name.id,))
            val2 = self.env.cr.fetchone()  # Fetch the result
            accrued_leave = val2[0] if val2 else 0  # Extract the value from the fetched result
            record.accrued=accrued_leave
            return record.accrued

    def reject(self):
        self.state="reject"
        usr = self.env["res.partner"].search([("name", "=", self.requester_name)])
        msg="Sorry, Your leave request cannot be accepted at this moment. It is rejected"
        self.mail_channel_msgs1(usr.id, self.reference,
                                self.requester_name,
                                self.operating_unit, self.state, msg)
       
    
    def mail_channel_msgs1(self, rec_id, arg1, arg2, arg3, arg4, msg):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = """Leave request Notification<br> Reference Number: %s <br>
                        Requester Name: %s <br>
                        Operating Unit: %s <br>
                        Leave Request : %s <br><br>%s
                        """ % (arg1, arg2, arg3, arg4, msg)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
    def mail_channel_msgs_del(self, rec_id, arg1, arg2, arg4, arg5):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        channel_id = channel
        message = """Dear %s<br><br>You have been assigned in the place of <b><u>%s</u></b> to look after the activities associated with him/her.<br><br>
		                From Date: %s <br>
                        till To Date : %s <br><br>FYI.
                        """ % (arg1, arg2, arg4, arg5)
        channel_id.message_post(
            body=message,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
 

     





   # def confirm_leave(self):
   # from odoo.exceptions import ValidationError

    def confirm_leave(self):
        p_id = self.id
        current_user_id = self.env.user.id
    # Check for annual or schedule leave eligibility
        if self.leave_reason in ["annual_leave", "schedule_leave"]:
            self.env.cr.execute("""
                SELECT CASE
                    WHEN %s = 'annual_leave' AND computed_leave <= (get_eligible_leave(he.id) + he.scheduled)
                        THEN 1
                    WHEN %s = 'schedule_leave' AND computed_leave <= get_eligible_leave(he.id)
                        THEN 1
                    ELSE 0
                END AS result
                FROM leave_request_manager lrm
                JOIN hr_employee he ON he.name = lrm.requester_name
                WHERE lrm.id = %s
            """, (self.leave_reason, self.leave_reason, p_id))

            result = self.env.cr.fetchone()
            if not result or result[0] == 0:
                raise ValidationError("The leave request exceeds the eligible leave balance.")

    # Confirm leave for leave without pay
        if self.leave_reason == "leave_without_pay":
            if self.apr_state == "approve":
                if self.manager_user_id != current_user_id:
                 raise ValidationError("Only the manager can confirm this leave")
                self.env.cr.execute('SELECT populate_confirmed_leaves(%s)', (p_id,))
                self.state = "confirm_leave"
                if self.delegated_name:
                    usr = self.env["res.partner"].search([("name", "=", self.delegated_name.name)], limit=1)
                    self.mail_channel_msgs_del(
                        usr.id, self.delegated_name.name,
                        self.requester_name,
                        self.start_date, self.end_date
                    )
            else:
                raise ValidationError('Please complete Approval before confirming leave')
        else:
            self.env.cr.execute('SELECT populate_confirmed_leaves(%s)', (p_id,))
            self.state = "confirm_leave"
            if self.delegated_name:
                usr = self.env["res.partner"].search([("name", "=", self.delegated_name.name)], limit=1)
                self.mail_channel_msgs_del(
                    usr.id, self.delegated_name.name,
                    self.requester_name,
                    self.start_date, self.end_date
                )

#        p_id = self.id
#        self.env.cr.execute("""
#    SELECT CASE
#        WHEN %s = 'annual_leave' AND no_of_days <= (get_eligible_leave(he.id) + he.scheduled)
#            THEN 1
#        WHEN %s = 'schedule_leave' AND no_of_days <= get_eligible_leave(he.id)
#            THEN 1
#        ELSE 0
#    END AS result
#    FROM leave_request_manager lrm
#    JOIN hr_employee he ON he.name = lrm.requester_name
#    WHERE lrm.id = %s
#""", (self.leave_reason, self.leave_reason, p_id))

        
    # Check for annual or schedule leave eligibility
        #if self.leave_reason in ["annual_leave", "schedule_leave"]:
         #   self.env.cr.execute("""
          #      SELECT CASE
           #         WHEN lrm.leave_reason  = 'annual_leave' AND no_of_days <= (get_eligible_leave(he.id) + he.scheduled)
            #            THEN 1
             #       WHEN lrm.leave_reason  = 'schedule_leave' AND no_of_days <= get_eligible_leave(he.id)
              #          THEN 1
               #     ELSE 0
                #    END AS result
               # FROM leave_request_manager lrm
                #    JOIN hr_employee he ON he.name = lrm.requester_name
                #    WHERE lrm.id  = %s
                #) AS eligibility_check
                #LIMIT 1
           # """, (p_id, p_id))

#        result = self.env.cr.fetchone()
#        if not result or result[0] == 0:
#            raise ValidationError("The leave request exceeds the eligible leave balance.")
#
#            if self.leave_reason == "leave_without_pay":
#                if self.apr_state == "approve":
#                    print("User  ID is ************************ ", p_id)
#                    self.env.cr.execute('SELECT populate_confirmed_leaves(%s)', (p_id,))
#                    print("Confirming the Leave ************************ ", p_id)
#                    self.state = "confirm_leave"
#                    if self.delegated_name:
#                        usr = self.env["res.partner"].search([("name", "=", self.delegated_name.name)])
#                        self.mail_channel_msgs_del(usr.id, self.delegated_name.name,
#                                                   self.requester_name,
#                                                   self.start_date, self.end_date)
#                else:
#                    raise ValidationError('Please complete Approval before confirming leave')
#            else:
#                print("User  ID is ************************ ", p_id)
#                self.env.cr.execute('SELECT populate_confirmed_leaves(%s)', (p_id,))
#                print("Confirming the Leave ************************ ", p_id)
#                self.state = "confirm_leave"
#                if self.delegated_name:
#                    usr = self.env["res.partner"].search([("name", "=", self.delegated_name.name)])
#                    self.mail_channel_msgs_del(usr.id, self.delegated_name.name,
#                                               self.requester_name,
#                                               self.start_date, self.end_date)	
		
		# usr = self.env["res.partner"].search([("name", "=", self.requester_name)])
        # msg = "Your leave request is accepted."
        # self.mail_channel_msgs1(usr.id, self.reference,
                                # self.requester_name,
                                # self.operating_unit, self.state, msg)
        # for val in self.LeaveTypes_details:
            # # number_of_days = 0
            # print(val.leave_type.id)
            # print(val.start_date)
            # # leave_comment = val.request_id.leave_reason + " " + val.request_id.comments
            # d1 = datetime.strptime(str(val.start_date), '%Y-%m-%d')
            # d2 = datetime.strptime(str(val.end_date), '%Y-%m-%d')
            # d3 = d2 - d1
            # number_of_days = str(d3.days)
            # no_days = float(number_of_days)
            # print("********************days", no_days)
            # # number_of_days = val.end_date - val.start_date
            # get_id = self.env["hr.employee"].search([('name', "=", self.requester_name)])
            # get_employee = self.env["hr.employee"].search([('user_id', "=", self.env.user.id)])
            # print("details", self.requester_name, get_employee.name)
            # print("number_of_days", number_of_days)
            # val2 = {
                # 'date_from': val.start_date,
                # 'date_to': val.end_date,
                # 'holiday_status_id': val.leave_type.id,
                # 'job_position': self.job_position,
                # 'job_category': self.job_category,
                # # 'job_grade': self.job_grade.grade_code,
                # 'request_date_from': val.start_date,
                # # 'duration_display': no_days,
                # 'request_date_to': val.end_date,
                # 'name': self.reference,
                # 'employee_id': get_id.id,
                # # 'employee_id': get_employee.id,
                # 'leave_request_description': val.approver_comments
            # }
            # print("val2==============", val2)
            # history = self.env["hr.leave"].create(val2)
            # history.action_approve()
            # print("histryzzzzzzzzzzzzzzzzz", history)


class LeaveTypes(models.Model):
    _name = "leave.request.types"
    request_id = fields.Many2one("leave.request.manager", string="Leave", help="Leave Request", invisible="1")
    leave_type = fields.Many2one("hr.leave.type", "Leave Type")
    number_of_days = fields.Float('Duration in days',
                                  help='Number of days of the time off request according to your working schedule. Used for interface.')
    balance_days = fields.Float(string="Balance Days")
    start_date = fields.Date(string="Start Date", help="Start Date")
    end_date = fields.Date(string="End Date", help="End Date")
    approver_comments = fields.Char(string="Approver Comments", help="Approver Comments")
    half_day = fields.Boolean(string="Half day")
    details = fields.Selection([("morning", "Morning"), ("afternoon", "Afternoon")], string="Details")


class HrLeaveDetails(models.Model):
    _inherit = "hr.leave"
    leave_request_description = fields.Text(string="Leave Request Description", help="Leave Request Description")
    job_position = fields.Char(string="Job Position")
    job_category = fields.Char(string="Job Category")


# Add this class at the END of your file
#class ResUsers(models.Model):
 #   _inherit = 'res.users'
  #  
   # @api.model
    #def name_search(self, name='', args=None, operator='ilike', limit=100):
     #   """Filter users by employee's job_grade = '53' in our model"""
      #  if args is None:
       #     args = []
        
        # TEMPORARY: Use hardcoded IDs from your screenshot to test
        #user_ids = [
         #   17315
       # ]
        
        # Always filter by these IDs when in our model's context
        #args.append(('id', 'in', user_ids))
        
        #return super().name_search(name=name, args=args, operator=operator, limit=limit)

#class ResUsers(models.Model):
#    _inherit = 'res.users'
    
#    @api.model
#    def name_search(self, name='', args=None, operator='ilike', limit=100):
#        """Your working version - just make it dynamic"""
#        if args is None:
#            args = []
        
        # Your working query
#        self.env.cr.execute("""
#            select DISTINCT user_id
#            FROM hr_employee
#            WHERE job_grade ='54'
#            AND user_id IS NOT null
#            and department_id = '655'
#            union          
#            select DISTINCT user_id
#            from hr_employee he 
#            where job_grade = '53'
#            and user_id is not null
#            and department_id <> '655'

#        """)
#        result = self.env.cr.fetchall()
#        user_ids = [row[0] for row in result if row[0]]
        
        # Use the dynamic user_ids instead of hardcoded
#        args.append(('id', 'in', user_ids))
        
#        return super().name_search(name=name, args=args, operator=operator, limit=limit)


