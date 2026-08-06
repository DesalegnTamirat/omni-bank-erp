from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError
import logging

# Initialize the logger
_logger = logging.getLogger(__name__)

class NewInternalRecruitmentSelected(models.Model):
    _name = "new.internal.recruitment.selected"
    _description = "New Internal Recruitment Selected"
    _inherit = "mail.thread"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.job_position.name or str(rec.id)

    job_position = fields.Many2one("hr.job", string="Job Position")
    job_location = fields.Char(string="Work Unit")
    job_grade = fields.Char(string="Grade")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id = fields.Integer(string="Work Unit Id")
    job_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    relevant_experience = fields.Integer(string="Relevant Experience")
    highest_cgpa = fields.Integer(string="Highest CGPA")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    minimum_number_years_in_company = fields.Integer(string="Minimum Number of Years in the Company")
    no_of_months_since_last_written_notice = fields.Integer(string="No of Months since last Written notice")
    no_of_months_since_last_promotion = fields.Integer(string="No of Months since last Promotion")
    minimum_pms_score = fields.Float(string="Minimum PMS Score")
    status = fields.Selection([('notify', 'Notified'), ('evaluate', 'Evaluate')], string="Status")
    vacancy_reference=fields.Char(string="Vacancy Reference")
    vacancy_id = fields.Integer(string="Vacancy ID")
    written_exam_date = fields.Datetime(string="Written Exam Date")
    exam_location=fields.Text(string="Exam Location")
    interview_accepted_count = fields.Float(string="Interview Accepted Count")
    exam_scheduled = fields.Selection([('Yes', 'Yes'),
                                            ('No', 'No')], string="Exam Scheduled", default='No')
    interview_scheduled = fields.Selection([('Yes', 'Yes'),
                                       ('No', 'No')], string="Interview Scheduled",default='No')
    interview_date = fields.Datetime(string="Interview Date")
    interview_location = fields.Text(string="Interview Location")
    status = fields.Selection([("notify", "notify"), ("evaluate", "Evaluate")])
    promotion_revocation_days=fields.Date(string="Promotion Revocation Days")
    new_int_rec_sel = fields.One2many("new.internal.recruitment.selected.candidates", "new_int_sel_cand", string="Selected candidates for Recruitment")
    new_int_rec_panel = fields.One2many("new.internal.recruitment.panel", "new_int_panel",string="Selected Panel for Recruitment")
    recr_selected_team_id = fields.One2many("new.recrt.delegation.team", "new_rec_del_id", string="Internal Recruitment Selected Delegation Team")

    def notify(self):
        p_id = self.id
        self.env.cr.execute('SELECT job_vacancy_minute(%s)', (p_id,))
        for com in self.recr_selected_team_id:
            if com.status == "active":
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.vacancy_reference, self.job_position)
            else:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)])
                if not usr:
                    raise ValidationError('Approver is not an Employee')
                else:
                    self.mail_channel_msgs(usr.id, self.vacancy_reference, self.job_position)
        self.status = "notify"

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
        for val in self.recr_selected_team_id:
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
        for vals in self.recr_selected_team_id:
            mem_cnt=mem_cnt+1
            if vals.approve==True:
                cnt=cnt+1
        if cnt==mem_cnt:
            self.status="evaluate"
			
    def mail_channel_msgs_exam(self, rec_id, emp, position, date, location):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear %s, <br>You have been shortlisted for the  Internal Recruitment of <b><u>%s</u></b> 
                         <br><br>Details of location and Place are as Follows<br><br>
                         Written Exam Date:  %s<br>
                         Written Exam Location: %s<br> 
                        <br><br> Please ensure that you arrive on time and bring all necessary documents<br><br>All The Best
                                """ % (emp, position, date, location)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
    def mail_channel_msgs_interview(self, rec_id, emp, position, date, location):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear %s, <br>You have been shortlisted for the  Internal Recruitment of <b><u>%s</u></b> 
                         <br><br>Details of location and Place are as Follows<br><br>
                         Interview Date:  %s<br>
                         Interview Location: %s<br> 
                        <br><br> Please ensure that you arrive on time and bring all necessary documents<br><br>All The Best
                                """ % (emp, position, date, location)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def notify_written_exam(self):
        p_id = self.id
        written_exam_date = fields.Date(string='Written Exam Date')
        if not self.written_exam_date:
            raise UserError('Please specify the Written Exam Date')
        else:
            if self.exam_scheduled == 'No':
                raise UserError('Please Schedule the Exam before sending the Exam Invite')
            else:
                for val in self.new_int_rec_sel:
                    if val.select_flag:
                        usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                        self.mail_channel_msgs_exam(usr.id, val.emp_name.name, self.job_position.name, str(self.written_exam_date), self.exam_location)

                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (p_id,))
                self.env.cr.execute('SELECT employee_notify_written_exam(%s)', (p_id,))
                self.env.cr.execute('SELECT populate_exam_evaluation_sheet(%s)', (p_id,))

	
    def fetch_exam_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT employee_exam_score(%s)', (p_id,))

    
    def notify_interview_panel(self):
        p_id = self.id
        interview_date = fields.Date(string='Interview Date')
        if not self.interview_date:
            raise UserError('Please specify the Interview Date')
        else:
            for val in self.new_int_rec_panel:
                if val.accepted:
                    usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, self.job_position.name, self.interview_date, self.interview_location)
            self.env.cr.execute('SELECT notify_panel_internal_interview(%s)', (p_id,))

    def mail_channel_msgs_panel(self, rec_id, emp, position, date, loc):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear %s <br>
			            You have been shortlisted as an Interview Panel Member for the  Recruitment of  <b><u>%s</u></b><br>
						.Please confirm your availability by mail. 
                        <br><br> 
						The Interview is on: %s
						The Interview will be held at:%s
                                """ % (emp, position, date, loc)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
	
    def notify_exam_panel(self):
        p_id = self.id
        # exam_date = fields.Date(string='Interview Date')
        if not self.written_exam_date:
            raise UserError('Please specify the Written exam Date')
        else:
            for val in self.new_int_rec_panel:
                if val.accepted:
                    usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                    self.mail_channel_msgs_exam_panel(usr.id, val.emp_name.name, self.job_position.name, self.written_exam_date, self.exam_location)
    def mail_channel_msgs_exam_panel(self, rec_id, emp, position, date, loc):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear %s <br>
			            You have been shortlisted as an Exam Panel Member for the  Recruitment of  <b><u>%s</u></b><br>
						.Please confirm your availability by mail. 
                        <br><br> 
						The Exam is on: %s
						The Exam will be held at:%s
                                """ % (emp, position, date, loc)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )


    def notify_interview(self):
        p_id = self.id
        interview_date = fields.Date(string='Interview Date')
        if not self.interview_date:
            raise UserError('Please specify the Interview Date')
        else:
            # self.env.cr.execute('SELECT get_panel_acceptance(%s)', (p_id,))
            _logger.info("Selection ID %s", p_id)
            self.env.cr.execute('SELECT update_interview_panel_acceptance(%s)', (p_id,))
            _logger.info("update_interview_panel_acceptance executed for ID %s", p_id)
            if self.interview_scheduled == 'No':
                raise UserError('Please Schedule the Interview before sending the Interview Invite')
            else:
                for val in self.new_int_rec_sel:
                    if val.select_flag:
                        _logger.info("Selected Employee: %s", val.emp_name)
                        usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                        self.mail_channel_msgs_interview(usr.id, val.emp_name.name, self.job_position.name, str(self.interview_date), self.interview_location)
                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (p_id,))
                _logger.info("internal_hr_applicant executed for ID %s", p_id)
                self.env.cr.execute('SELECT employee_notify_interview(%s)', (p_id,))
                _logger.info("employee_notify_interview executed for ID %s", p_id)
                self.env.cr.execute('SELECT populate_interview_evaluation_sheet(%s)', (p_id,))
                _logger.info("populate_interview_evaluation_sheet executed for ID %s", p_id)

    def fetch_interview_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT employee_interview_score(%s)', (p_id,))


    def compute_weighted_score(self):
        p_id = self.id
        self.env.cr.execute('SELECT employee_weighted_score(%s)', (p_id,))


    def notify_selection(self):
        p_id = self.id
        for val in self.new_int_rec_sel:
            if val.select_flag:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                if val.selection_type=="selected":
                   msg1="We are pleased to inform You that you have been Selected for the  Internal Recruitment of "
                   msg2="<br>Please Indicate your acceptance of the propmotion by clicking on the Accept Promotion button in the Internal Job Position form.<br><br>The Formalities relating to your promotion will be completed in due course."
                   self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name, msg2)
                if val.selection_type=="reserve":
                   msg1="We are pleased to inform You that you have been Selected for the  Internal Recruitment of " 
                   msg2=" as a reserve candidate.<br>Your promotion will be communicated to you in due course."
                   self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name, msg2)
                if val.selection_type=="rejected":  
                   msg1="We are Sorry to inform You that your application for the  Internal Recruitment of "
                   msg2=" has been rejected.<br>This is as per the HR policies of the Bank."
                   self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name, msg2)
        self.env.cr.execute('SELECT employee_notify_result(%s)', (p_id,))
    
    def mail_channel_msgs_selection(self, rec_id, emp, msg1, position, msg2):
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
            channel_id = channel
            message = channel_id = channel
            message = """Dear %s,<br>%s.%s%s
                                """ % (emp, msg1, position, msg2)
            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def notify_rejection(self):
        for val in self.new_int_rec_sel:
            if val.select_flag:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)])
                self.mail_channel_msgs_selection(usr.id, val.emp_name.name, "Rejected", self.job_position.name)
		
class NewInternalRecruitmentSelectedDelegation(models.Model):
    _name = "new.recrt.delegation.team"
    _description = "New Recrt Delegation Team"

    role = fields.Selection([("chair_person", "Chair Person"), ("member", "Member"), ("secretary", "Secretary"),
                             ("member_secretary", "Member & Secretary")], string="Role")
    employee_name = fields.Many2one("res.users", string="Employee Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    operating_unit = fields.Char(string="Operating Unit", related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    approve = fields.Boolean(string="Approve", readonly=True)
    new_rec_del_id = fields.Many2one("new.internal.recruitment.selected", string="Internal Recruitment Selected Delegation Team")
	


class InternalRecruitmentSelectedCandidates(models.Model):
    _name = "new.internal.recruitment.selected.candidates"
    _description = "New Internal Recruitment Selected Candidates"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    emp_grade = fields.Char(string="Grade")
    emp_position = fields.Char(string="Position",compute="_compute_employee_details", 
                    store=True)
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
    emp_category = fields.Char(string="Category")
    emp_type = fields.Char(string="Employment Type")
    emp_gender = fields.Char(string="Gender")
    current_work_unit = fields.Char(string="Current Location",compute="_compute_employee_details", 
                    store=True)
    current_department = fields.Char(string="Current Department",compute="_compute_employee_details", 
                    store=True)
    service_in_company = fields.Float(string="Service in Company")
    educational_qualification = fields.Char(string="Educational Qualification")
    cgpa = fields.Float(string="CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(string="PMS Score", readonly=True,compute="_compute_employee_details",
                                store=True)
    preferred_location=fields.Char(string="Preferred Location")
    #preferred_location = fields.Many2one( "operating.unit",  string="Preferred Location")
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    written_exam_score = fields.Float(string="Written Exam Score")
    interview_score = fields.Float(string="Interview Score")
    # pms_score = fields.Float(string="PMS Score")
    weighted_score = fields.Float(string="Weighted Score")
    # selection_type = fields.Char(string="Selection Type")
    exam_notified =fields.Char(string="exam_notified")
    interview_notified = fields.Char(string="interview_notified")
    decision_notified = fields.Char(string="decision_notified")
    selection_type = fields.Selection([('selected', 'Selected'),
                                       ('reserve', 'Reserved'),
                                       ('rejected', 'Rejected')], string="Result",default='selected')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select",default=True)
    new_int_sel_cand = fields.Many2one("new.internal.recruitment.selected", string="Selected candidates for Recruitment")
    
    @api.depends('emp_name')
    def _compute_employee_details(self):
        for record in self:
            if record.emp_name:
                # Direct ORM access instead of SQL joins
                record.emp_position = record.emp_name.job_position.name
                record.current_department = record.emp_name.department_id.name
                
                record.current_work_unit = record.emp_name.default_operating_unit_id.name
                record.pms_score=record.emp_name.contract_id.pms_score
               
            else:
                record.emp_position = False
                record.current_department = False
                record.current_work_unit = False
class InternalRecruitmentPanel(models.Model):
    _name = "new.internal.recruitment.panel"
    _description = "New Internal Recruitment Panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    emp_position = fields.Char(string="Position")
    position_id = fields.Integer(string="Position Id")
    vacancy_id = fields.Integer(string="Vacancy ID")
    workunit_id = fields.Integer(string="Workunit Id")
    selection_criteria = fields.Selection([('Exam', 'Exam'),
                                       ('Interview', 'Interview')], string="Assessment Type",default='Exam')
    accepted = fields.Boolean(string="Accepted" ,default=False)
    panel_status= fields.Char(string="panel_status")
    select_flag = fields.Boolean(string="Select")
    new_int_panel = fields.Many2one("new.internal.recruitment.selected", string="Select Panel for Recruitment")




