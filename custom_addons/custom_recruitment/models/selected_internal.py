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
        """ Prohibit hard deletion of recruitment selection records for compliance """
        raise UserError(_("Deletion of recruitment selection records is strictly prohibited for audit integrity. You may archive records instead."))

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
    status = fields.Selection([('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status")
    state = fields.Selection([('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="State")
    panel_notified = fields.Boolean(string="Panel Notified", default=False)
    exam_scores_fetched = fields.Boolean(string="Exam Scores Fetched", default=False)
    interview_scores_fetched = fields.Boolean(string="Interview Scores Fetched", default=False)
    scores_computed = fields.Boolean(string="Scores Computed", default=False)
    selection_notified = fields.Boolean(string="Selection Notified", default=False)
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
    promotion_revocation_days=fields.Date(string="Promotion Revocation Days")
    new_int_rec_sel = fields.One2many("new.internal.recruitment.selected.candidates", "new_int_sel_cand", string="Selected candidates for Recruitment")
    new_int_rec_panel = fields.One2many("new.internal.recruitment.panel", "new_int_panel",string="Selected Panel for Recruitment")
    recr_selected_team_id = fields.One2many("new.recrt.delegation.team", "new_rec_del_id", string="Internal Recruitment Selected Delegation Team")

    def notify(self):
        p_id = self.id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT job_vacancy_minute(%s)', (p_id,))
        except Exception as e:
            _logger.warning("Stored procedure job_vacancy_minute failed: %s", e)
        for com in self.recr_selected_team_id:
            usr = False
            if com.employee_name:
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)], limit=1)
            elif com.alternate_committee_member:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)], limit=1)
            if usr:
                self.mail_channel_msgs(usr.id, self.vacancy_reference or '', self.job_position.name if self.job_position else '')
        self.status = "notify"
        self.state = "notify"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approvers Notified'),
                'message': _('Committee members have been notified for internal vacancy selection approval.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear Committee<br>Candidates have been shortlisted for internal selection: <b>%s</b> (Ref: <b>%s</b>).<br><br>Kindly approve.") % (arg1, ref)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def evaluate(self):
        n = 0
        usr_name = self.env.user.name
        for val in self.recr_selected_team_id:
            if val.status == "unavailable":
                if val.alternate_committee_member and val.alternate_committee_member.name == usr_name:
                    n += 1
                    val.approve = True
                    break
            else:
                if val.employee_name and val.employee_name.name == usr_name:
                    n += 1
                    val.approve = True
                    break
        if n == 0 and self.recr_selected_team_id:
            if self.env.user.has_group('hr.group_hr_manager'):
                for val in self.recr_selected_team_id:
                    val.approve = True
            else:
                raise ValidationError(_("Sorry!! You are not assigned as an evaluator for this selection."))
        self.status = "evaluate"
        self.state = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved'),
                'message': _('Internal selection process has been successfully approved!'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs_exam(self, rec_id, emp, position, date, location):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear %s,<br>You have been shortlisted for the Written Exam for position <b>%s</b>.<br>Date: %s<br>Location: %s<br><br>All The Best!") % (emp, position, date, location)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def mail_channel_msgs_interview(self, rec_id, emp, position, date, location):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear %s,<br>You have been shortlisted for the Interview for position <b>%s</b>.<br>Date: %s<br>Location: %s<br><br>All The Best!") % (emp, position, date, location)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_written_exam(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date before sending notifications.'))
        for val in self.new_int_rec_sel:
            if val.select_flag and val.emp_name:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)], limit=1)
                if usr:
                    self.mail_channel_msgs_exam(usr.id, val.emp_name.name, self.job_position.name if self.job_position else '', str(self.written_exam_date), self.exam_location or 'Main Office')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (self.id,))
                self.env.cr.execute('SELECT employee_notify_written_exam(%s)', (self.id,))
                self.env.cr.execute('SELECT populate_exam_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedures for written exam failed: %s", e)
        self.exam_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Notification Sent'),
                'message': _('Written Exam notifications dispatched to internal candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def fetch_exam_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT employee_exam_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_exam_score failed: %s", e)
        self.exam_scores_fetched = True
        self.compute_weighted_score()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Scores Fetched'),
                'message': _('Exam scores fetched and updated.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_interview_panel(self):
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date.'))
        for val in self.new_int_rec_panel:
            if val.accepted and val.emp_name:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)], limit=1)
                if usr:
                    self.mail_channel_msgs_panel(usr.id, val.emp_name.name, self.job_position.name if self.job_position else '', self.interview_date, self.interview_location or 'Head Office')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT notify_panel_internal_interview(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure notify_panel_internal_interview failed: %s", e)
        self.panel_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Notified'),
                'message': _('Interview Panel members have been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs_panel(self, rec_id, emp, position, date, loc):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear %s,<br>You are selected as an Interview Panel Member for position <b>%s</b>.<br>Date: %s<br>Location: %s") % (emp, position, date, loc)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_exam_panel(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date.'))
        for val in self.new_int_rec_panel:
            if val.accepted and val.emp_name:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)], limit=1)
                if usr:
                    self.mail_channel_msgs_exam_panel(usr.id, val.emp_name.name, self.job_position.name if self.job_position else '', self.written_exam_date, self.exam_location or 'Main Office')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Panel Notified'),
                'message': _('Exam Panel members notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs_exam_panel(self, rec_id, emp, position, date, loc):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear %s,<br>You are selected as an Exam Panel Member for position <b>%s</b>.<br>Date: %s<br>Location: %s") % (emp, position, date, loc)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def notify_interview(self):
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date.'))
        for val in self.new_int_rec_sel:
            if val.select_flag and val.emp_name:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)], limit=1)
                if usr:
                    self.mail_channel_msgs_interview(usr.id, val.emp_name.name, self.job_position.name if self.job_position else '', str(self.interview_date), self.interview_location or 'Head Office')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT update_interview_panel_acceptance(%s)', (self.id,))
                self.env.cr.execute('SELECT internal_hr_applicant(%s)', (self.id,))
                self.env.cr.execute('SELECT employee_notify_interview(%s)', (self.id,))
                self.env.cr.execute('SELECT populate_interview_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedures for interview failed: %s", e)
        self.interview_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Notifications Sent'),
                'message': _('Interview notifications dispatched to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def fetch_interview_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT employee_interview_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_interview_score failed: %s", e)
        self.interview_scores_fetched = True
        self.compute_weighted_score()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Scores Fetched'),
                'message': _('Interview scores fetched and updated.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def compute_weighted_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT employee_weighted_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_weighted_score failed: %s", e)
        # Pure python calculation fallback
        for app in self.new_int_rec_sel:
            pms = app.pms_score or 0.0
            exam = app.written_exam_score or 0.0
            interview = app.interview_score or 0.0
            app.weighted_score = round((pms * 0.4) + (exam * 0.3) + (interview * 0.3), 2)
            if app.weighted_score >= 70.0:
                app.selection_type = 'selected'
            elif app.weighted_score >= 50.0:
                app.selection_type = 'reserve'
            else:
                app.selection_type = 'rejected'
        self.scores_computed = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Weighted Scores Computed'),
                'message': _('Internal candidate weighted scores and selection types computed successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_selection(self):
        for val in self.new_int_rec_sel:
            if val.select_flag and val.emp_name:
                usr = self.env["res.partner"].search([("name", "=", val.emp_name.name)], limit=1)
                if usr:
                    if val.selection_type in ['selected', 'Selected']:
                        msg1 = _("We are pleased to inform you that you have been Selected for position ")
                        msg2 = _("<br>Please indicate your acceptance of promotion in the system.<br><br>Congratulations!")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
                    elif val.selection_type in ['reserve', 'reserved', 'Reserve', 'Reserved']:
                        msg1 = _("We are pleased to inform you that you have been placed in the Reserve Pool for position ")
                        msg2 = _("<br>Your status is valid for 6 months.")
                        self.mail_channel_msgs_selection(usr.id, val.emp_name.name, msg1, self.job_position.name if self.job_position else '', msg2)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT employee_notify_result(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure employee_notify_result failed: %s", e)
        self.selection_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Selection Notified'),
                'message': _('Selection results dispatched to internal candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
    
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

    # FR-REC-056: Leave Status — cross-reference with Time Off module (hr.leave)
    # Displays on Written Exam Selection Table and Interview Evaluation Dashboard.
    # No new model; reads directly from hr.leave for the linked employee.
    active_leave_status = fields.Char(
        string="Leave Status",
        compute="_compute_leave_status",
        store=False,
        help="Cross-references the Time Off module. Shows leave type (Annual, Medical, Maternity, etc.) "
             "if the employee has an approved leave covering today's date.",
    )

    @api.depends('emp_name')
    def _compute_leave_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            emp = rec.emp_name
            if emp:
                leave = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leave:
                    rec.active_leave_status = leave.holiday_status_id.name if leave.holiday_status_id else _("On Leave")
                else:
                    rec.active_leave_status = _("Active")
            else:
                rec.active_leave_status = _("N/A")
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
    selection_type = fields.Selection([
        ('selected', 'Selected'),
        ('reserve', 'Reserved'),
        ('rejected', 'Rejected')
    ], string="Result", default='selected')
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




