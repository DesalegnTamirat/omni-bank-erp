from odoo import api, models, fields, _
from odoo.exceptions import UserError
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
from odoo.exceptions import ValidationError


class ExternalRecruitmentSelected(models.Model):
    _name = "external.recruitment.selected"
    _inherit = "mail.thread"
    _rec_name = "job_position"

    job_position = fields.Many2one("hr.job", string="Job Position")
    job_location = fields.Char(string="Work Unit")
    job_grade = fields.Char(string="Grade")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id = fields.Integer(string="Work Unit Id")
    job_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    vacancy_reference = fields.Char(string="Vacancy Reference")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    written_exam_date = fields.Datetime(string="Written Exam Date")
    exam_location = fields.Text(string="Exam Location")
    interview_accepted_count = fields.Float(string="Interview Accepted Count")
    interview_date = fields.Datetime(string="Interview Date")
    interview_location = fields.Text(string="Interview Location")
    exam_scheduled = fields.Selection([('Yes', 'Yes'),
                                       ('No', 'No')], string="Exam Scheduled", default='No')
    interview_scheduled = fields.Selection([('Yes', 'Yes'),
                                            ('No', 'No')], string="Interview Scheduled", default='No')
    relevant_experience = fields.Integer(string="Relevant Experience")
    highest_cgpa = fields.Integer(string="Highest CGPA")
    vacancy_id = fields.Integer(string="Vacancy ID")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('notify', 'Notified')], string="Status")
    state = fields.Selection([("notify_approver", "Notify Approvers"), ("evaluate", "Approve")])
    ext_rec_sel = fields.One2many("external.recruitment.selected.candidates", "ext_rec_sel_cand",
                                      string="Selected candidates for External Recruitment")
    ext_rec_panel = fields.One2many("external.recruitment.panel", "ext_panel",
                                        string="Selected Panel for Recruitment")
    recr_exter_selected_team_id = fields.One2many("external.recrt.delegation.team", "exter_rec_del_id", string="External Recruitment Selected Delegation Team")

    def notify_approver(self):
        p_id = self.id
        self.env.cr.execute('SELECT job_vacancy_minute_external(%s)', (p_id,))	
        for com in self.recr_exter_selected_team_id:
            if com.status == "active":
                # usr = self.env["res.users"].search([("id", "=", com.res_users.id)])
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.vacancy_reference, self.job_position)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                # usr = self.env["res.users"].search([("id", "=", res_users.id)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.vacancy_reference, self.job_position)
            # else:
                # raise ValidationError('Please check again')
        self.state = "notify_approver"

    def mail_channel_msgs(self, rec_id, ref, arg1):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear Committee<br>This is to inform you that candidates have been shorlisted for the position: <b>%s<b> and its reference number is <b>%s<b>
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
        for val in self.recr_exter_selected_team_id:
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
        for vals in self.recr_exter_selected_team_id:
            mem_cnt=mem_cnt+1
            if vals.approve==True:
                cnt=cnt+1

        if cnt==mem_cnt:
            self.status="evaluate"


    def send_mail(self, email, subject_column, comments):

        mail_content = comments

        # The mail addresses and password
        sender_address = 'cortex.workflow@gmail.com'
        sender_pass = 'zktuxyepwxpkzbtv'
        receiver_address = email
        # Setup the MIME
        message = MIMEMultipart()
        message['From'] = sender_address
        message['To'] = receiver_address
        message['Subject'] = Header(subject_column, 'utf-8')
        # The body and the attachments for the mail
        message.attach(MIMEText(mail_content, 'plain'))
        # Create SMTP session for sending the mail
        session = smtplib.SMTP('smtp.gmail.com', 587)  # use gmail with port
        session.starttls()  # enable security
        session.login(sender_address, sender_pass)  # login with mail_id and password
        text = message.as_string()

        session.sendmail(sender_address, receiver_address, text)
        session.quit()

    def notify_written_exam(self):
        p_id = self.id
        written_exam_date = fields.Date(string='Written Exam Date')
        if not self.written_exam_date:
            raise UserError('Please specify the Written Exam Date')
        else:
            for app in self.ext_rec_sel:
                if app.select_flag == True:
                    e_mail = app.applicant_email
                    # applicant = app.applicant_name
                    message = "Greetings!! \n Miss/Mr/Mrs. " + str(app.applicant_name.name) + "\nJob Reference: " + str(
                        self.job_position.name) + \
                              "\nWe are inviting you for the written exam conducted as the next level of assessment \n Exam Conducted on:" + str(
                        self.written_exam_date) + \
                              "\n Location of Exam:" + str(
                        self.exam_location) + "\n Please be on location half an hour before the Exam time\nAll the Best!!\n\n\n\n\n\n Best Regards\n Bunna Bank"
                    subject = "Written Exam Notification Reg. " + str(self.job_position.name)
                    self.send_mail(e_mail, subject, message)
            # self.env.cr.execute('SELECT employee_notify_written_exam(%s)', (p_id,))
            self.env.cr.execute('SELECT populate_external_exam_evaluation_sheet(%s)', (p_id,))

    def fetch_exam_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT applicant_exam_score(%s)', (p_id,))


    def notify_interview_panel(self):
        p_id = self.id
        interview_date = fields.Date(string='Interview Date')
        if not self.interview_date:
            raise UserError('Please specify the Interview Date')
        else:

            self.env.cr.execute('SELECT notify_panel_external_interview(%s)', (p_id,))

    def notify_interview(self):
        p_id = self.id
        interview_date = fields.Date(string='Interview Date')
        if not self.interview_date:
            raise UserError('Please specify the Interview Date')
        else:
            if self.interview_scheduled == 'No':
                raise UserError('Please Schedule the Interview before sending the Interview Invite')
            else:
                for app in self.ext_rec_sel:
                    if app.select_flag == True:
                        e_mail = app.applicant_email
                        # applicant = app.applicant_name
                        message = "Greetings!! \n Miss/Mr/Mrs. " + str(
                            app.applicant_name.name) + "\nJob Reference: " + str(self.job_position.name) + \
                                  "\nYour application for the" + str(self.job_position.name) + \
                                  "position stood out to us and we would like to invite you for an interview at  our office[s] " \
                                  "to get to know you a bit better.\n Interview Date :" + str(self.interview_date) + \
                                  "\n Interview location:" + self.interview_location + "\n Please be on location half an hour before the interview time.\n" \
                                                                                       " All the Best!!\n\n\n\n\n\n Best Regards\n Bunna Bank"
                        subject = "Call for Interview Reg. " + str(self.job_position.name)
                        self.send_mail(e_mail, subject, message)
                # self.env.cr.execute('SELECT employee_notify_interview(%s)', (p_id,))
                self.env.cr.execute('SELECT populate_external_interview_evaluation_sheet(%s)', (p_id,))

    def fetch_interview_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT applicant_interview_score(%s)', (p_id,))

    def compute_weighted_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT applicant_weighted_score(%s)', (p_id,))

    def notify_selection(self):
        p_id = self.id
        self.env.cr.execute('SELECT applicant_update_status(%s)', (p_id,))
        for app in self.ext_rec_sel:
            if app.selection_type == "Selected":
                e_mail = app.applicant_email
                # applicant = app.applicant_name
                message = "Greetings!! \n Miss/Mr/Mrs. " + str(app.applicant_name.name) + "\nJob Reference: " + str(
                    self.job_position.name) + "Congratulations!! You are selected for the position " + str(
                    self.job_position.name) + \
                          "\nWe are Glad to inform you that you stood out in all the levels of interview. " \
                          "We are happy to Welcome you into our company \n We will update you about further formalities soon\n All the Best!!\n\n\n\n\n\n Best Regards\n Bunna Bank"

                subject = "Congratulations!! You are selected for the job" + str(self.job_position.name)
                self.send_mail(e_mail, subject, message)

    def notify_rejection(self):
        for app in self.ext_rec_sel:
            if app.selection_type == "Rejected":
                e_mail = app.applicant_email
                message = (
                    "Greetings!! \n Miss/Mr/Mrs. %(name)s\nJob Reference: %(job)s\n"
                    "We are sorry to inform you that you are not selected for the job position.\n"
                    "We hope you will do better next time.\nAll the Best!!"
                ) % {'name': app.applicant_name.name, 'job': self.job_position.name}
                subject = "Rejection notification Reg. " + str(self.job_position.name)
                try:
                    self.send_mail(e_mail, subject, message)
                except Exception:
                    pass


class ExternalRecruitmentSelectedCandidates(models.Model):
    _name = "external.recruitment.selected.candidates"
    _description = "Eligible Applicants"

    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    applicant_email = fields.Char(string="Email")
    emp_name = fields.Char(string="emp name")
    emp_grade = fields.Char(string="Grade")
    emp_position = fields.Char(string="Position")
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
    emp_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    emp_gender = fields.Char(string="Gender")
    current_work_unit = fields.Char(string="Current Location")
    service_in_company = fields.Float(string="Service in Company")
    educational_qualification = fields.Char(string="Educational Qualification")
    cgpa = fields.Float(string="CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(string="PMS Score")
    preferred_location = fields.Char(string="Preferred Location")
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    written_exam_score = fields.Float(string="Written Exam Score")
    interview_score = fields.Float(string="Interview Score")
    weighted_score = fields.Float(string="Weighted Score")
    exam_notified = fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([('selected', 'Selected'),
	                                   ('reserved', 'Reserved'),
                                       ('rejected', 'Rejected')], string="Result", default='selected')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    ext_rec_sel_cand = fields.Many2one("external.recruitment.selected",
                                           string="Selected candidates for External Recruitment")


class InternalRecruitmentPanel(models.Model):
    _name = "external.recruitment.panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    emp_position = fields.Char(string="Position")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    selection_criteria = fields.Selection([('Exam', 'Exam'),
                                       ('Interview', 'Interview')], string="Assessment Type",default='Exam')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    accepted = fields.Boolean(string="Accepted", default=False)
    panel_status = fields.Char(string="panel_status")
    ext_panel = fields.Many2one("external.recruitment.selected", string="Select Panel for Recruitment")


class ExternalRecruitmentSelectedDelegation(models.Model):
    _name = "external.recrt.delegation.team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    exter_rec_del_id = fields.Many2one("external.recruitment.selected", string="External Recruitment Selected Delegation Team")


class NewExternalRecruitmentSelected(models.Model):
    _name = "new.external.recruitment.selected"

    emp_name = fields.Char(string="Emp Name")

class NewExternalRecruitmentSelectedDelegation(models.Model):
    _name = "new.external.recrt.delegation.team"
	
    emp_name = fields.Char(string="Emp Name")
	
class NewInternalRecruitmentPanel(models.Model):
    _name = "new.external.recruitment.panel"
	
    emp_name = fields.Char(string="Emp Name")
	
class NewExternalRecruitmentSelectedCandidates(models.Model):
    _name = "new.external.recruitment.selected.candidates"
	
    emp_name = fields.Char(string="Emp Name")
