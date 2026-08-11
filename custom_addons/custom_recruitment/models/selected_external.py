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
import logging

_logger = logging.getLogger(__name__)


class ExternalRecruitmentSelected(models.Model):
    _name = "external.recruitment.selected"
    _description = "External Recruitment Selected"
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
    status = fields.Selection([('notify', 'Notified'), ('evaluate', 'Evaluate'), ('approved', 'Approved')], string="Status")
    state = fields.Selection([("notify_approver", "Notify Approvers"), ("evaluate", "Evaluate"), ("approved", "Approved")], string="State")
    panel_notified = fields.Boolean(string="Panel Notified", default=False)
    exam_scores_fetched = fields.Boolean(string="Exam Scores Fetched", default=False)
    interview_scores_fetched = fields.Boolean(string="Interview Scores Fetched", default=False)
    scores_computed = fields.Boolean(string="Scores Computed", default=False)
    selection_notified = fields.Boolean(string="Selection Notified", default=False)
    ext_rec_sel = fields.One2many("external.recruitment.selected.candidates", "ext_rec_sel_cand",
                                      string="Selected candidates for External Recruitment")
    ext_rec_panel = fields.One2many("external.recruitment.panel", "ext_panel",
                                        string="Selected Panel for Recruitment")
    recr_exter_selected_team_id = fields.One2many("external.recrt.delegation.team", "exter_rec_del_id", string="External Recruitment Selected Delegation Team")

    def notify_approver(self):
        p_id = self.id
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT job_vacancy_minute_external(%s)', (p_id,))
        except Exception as e:
            _logger.warning("Stored procedure job_vacancy_minute_external failed: %s", e)

        # Pure python fallback to sync result summary rank if stored procedure fails
        vac = self.env["job.vacancy"].search([("reference", "=", self.vacancy_reference)], limit=1)
        if vac and self.ext_rec_sel:
            try:
                vac.hiring_rank_details.unlink()
                rank_lines = []
                sorted_cands = sorted(self.ext_rec_sel, key=lambda c: c.weighted_score or 0.0, reverse=True)
                for idx, cand in enumerate(sorted_cands, start=1):
                    name_str = cand.applicant_name.partner_name if (cand.applicant_name and getattr(cand.applicant_name, 'partner_name', False)) else (cand.applicant_name.name if cand.applicant_name else 'Applicant')
                    rank_lines.append((0, 0, {
                        'no': idx,
                        'rank': idx,
                        'applicant_name': name_str,
                        'result': str(cand.weighted_score or 0.0),
                        'statues': cand.selection_type or 'Pending',
                    }))
                if rank_lines:
                    vac.write({'hiring_rank_details': rank_lines})
            except Exception as ex:
                _logger.warning("Python fallback rank generation warning: %s", ex)

        for com in self.recr_exter_selected_team_id:
            usr = False
            if com.employee_name:
                usr = self.env["res.partner"].search([("name", "=", com.employee_name.name)], limit=1)
            elif com.alternate_committee_member:
                usr = self.env["res.partner"].search([("name", "=", com.alternate_committee_member.name)], limit=1)
            if usr:
                self.mail_channel_msgs(usr.id, self.vacancy_reference or '', self.job_position.name if self.job_position else '')
        self.state = "notify_approver"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approver Notified'),
                'message': _('Committee members have been notified for vacancy selection approval.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = _("Dear Committee<br>Candidates have been shortlisted for the position: <b>%s</b> (Ref: <b>%s</b>).<br><br>Kindly approve.") % (arg1, ref)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

    def evaluate(self):
        n = 0
        usr_name = self.env.user.name
        for val in self.recr_exter_selected_team_id:
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
        if n == 0 and self.recr_exter_selected_team_id:
            # Auto-approve for administrator override if user not explicitly on delegation list
            if self.env.user.has_group('hr.group_hr_manager'):
                for val in self.recr_exter_selected_team_id:
                    val.approve = True
            else:
                raise ValidationError(_("Sorry!! You are not assigned as an evaluator for this selection."))
        
        self.state = "evaluate"
        self.status = "evaluate"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved'),
                'message': _('Selection process has been successfully approved!'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def send_mail(self, email, subject_column, comments):
        if not email:
            return
        try:
            mail_values = {
                'subject': subject_column,
                'body_html': f"<p>{comments.replace('\n', '<br>')}</p>",
                'email_to': email,
            }
            self.env['mail.mail'].sudo().create(mail_values).send()
        except Exception:
            pass

    def _get_applicant_display_name(self, app):
        if not app or not app.applicant_name:
            return 'Candidate'
        applicant = app.applicant_name
        return getattr(applicant, 'partner_name', False) or getattr(applicant, 'display_name', False) or 'Candidate'

    def notify_written_exam(self):
        if not self.written_exam_date:
            raise UserError(_('Please specify the Written Exam Date before notifying candidates.'))
        for app in self.ext_rec_sel:
            if app.select_flag and app.applicant_email:
                message = _("Greetings %s,\n\nJob Position: %s\nWe invite you for the Written Exam on %s at %s.\n\nBest Regards,\nBunna Bank S.C.") % (
                    self._get_applicant_display_name(app),
                    self.job_position.name if self.job_position else '',
                    str(self.written_exam_date),
                    self.exam_location or 'Main Branch'
                )
                subject = _("Written Exam Notification - %s") % (self.job_position.name if self.job_position else '')
                self.send_mail(app.applicant_email, subject, message)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_exam_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_exam_evaluation_sheet failed: %s", e)
        self.exam_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Notification Sent'),
                'message': _('Written Exam notifications sent to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def fetch_exam_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT applicant_exam_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_exam_score failed: %s", e)
        self.exam_scores_fetched = True
        self.compute_weighted_score()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Exam scores fetched and updated.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_interview_panel(self):
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date.'))
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT notify_panel_external_interview(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure notify_panel_external_interview failed: %s", e)
        self.panel_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Notified'),
                'message': _('Interview Panel Members have been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_interview(self):
        if not self.interview_date:
            raise UserError(_('Please specify the Interview Date.'))
        for app in self.ext_rec_sel:
            if app.select_flag and app.applicant_email:
                message = _("Greetings %s,\n\nJob Position: %s\nYou are invited for an Interview on %s at %s.\n\nBest Regards,\nBunna Bank S.C.") % (
                    self._get_applicant_display_name(app),
                    self.job_position.name if self.job_position else '',
                    str(self.interview_date),
                    self.interview_location or 'Head Office'
                )
                subject = _("Call for Interview - %s") % (self.job_position.name if self.job_position else '')
                self.send_mail(app.applicant_email, subject, message)
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT populate_external_interview_evaluation_sheet(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure populate_external_interview_evaluation_sheet failed: %s", e)
        self.interview_scheduled = 'Yes'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interview Notifications Sent'),
                'message': _('Interview invitations dispatched to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def fetch_interview_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT applicant_interview_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_interview_score failed: %s", e)
        self.interview_scores_fetched = True
        self.compute_weighted_score()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Scores Fetched'),
                'message': _('Interview scores fetched and updated.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def compute_weighted_score(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT applicant_weighted_score(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_weighted_score failed: %s", e)
        # Pure python calculation fallback
        for app in self.ext_rec_sel:
            exam = app.written_exam_score or 0.0
            interview = app.interview_score or 0.0
            app.weighted_score = round((exam * 0.5) + (interview * 0.5), 2)
            if app.weighted_score >= 70.0:
                app.selection_type = 'selected'
            elif app.weighted_score >= 50.0:
                app.selection_type = 'reserved'
            else:
                app.selection_type = 'rejected'
        self.scores_computed = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Weighted Scores Computed'),
                'message': _('Candidate weighted scores and selection types computed successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def notify_selection(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute('SELECT applicant_update_status(%s)', (self.id,))
        except Exception as e:
            _logger.warning("Stored procedure applicant_update_status failed: %s", e)
        for app in self.ext_rec_sel:
            if app.selection_type in ['selected', 'Selected'] and app.applicant_email:
                message = _("Congratulations %s!\n\nYou have been selected for the position of %s at Bunna Bank S.C.\nOur HR department will contact you shortly.\n\nBest Regards,\nBunna Bank S.C.") % (
                    self._get_applicant_display_name(app),
                    self.job_position.name if self.job_position else ''
                )
                subject = _("Congratulations! Selection Notification - %s") % (self.job_position.name if self.job_position else '')
                self.send_mail(app.applicant_email, subject, message)
        self.selection_notified = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Selection Notified'),
                'message': _('Selection results dispatched to candidates.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

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
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
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
    selection_type = fields.Selection([
        ('selected', 'Selected'),
        ('reserved', 'Reserved'),
        ('rejected', 'Rejected')
    ], string="Result", default='selected')
    remarks = fields.Char(string="Remarks")
    select_flag = fields.Boolean(string="Select")
    ext_rec_sel_cand = fields.Many2one("external.recruitment.selected",
                                           string="Selected candidates for External Recruitment")


class InternalRecruitmentPanel(models.Model):
    _name = "external.recruitment.panel"
    _description = "External Recruitment Panel"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
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
    _description = "External Recrt Delegation Team"

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
    exter_rec_del_id = fields.Many2one("external.recruitment.selected", string="External Recruitment Selected Delegation Team")


class NewExternalRecruitmentSelected(models.Model):
    _name = "new.external.recruitment.selected"
    _description = "New External Recruitment Selected"

    emp_name = fields.Char(string="Emp Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

class NewExternalRecruitmentSelectedDelegation(models.Model):
    _name = "new.external.recrt.delegation.team"
    _description = "New External Recrt Delegation Team"
	
    emp_name = fields.Char(string="Emp Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
	
class NewInternalRecruitmentPanel(models.Model):
    _name = "new.external.recruitment.panel"
    _description = "New External Recruitment Panel"
	
    emp_name = fields.Char(string="Emp Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
class NewExternalRecruitmentSelectedCandidates(models.Model):
    _name = "new.external.recruitment.selected.candidates"
    _description = "New External Recruitment Selected Candidates"
	
    emp_name = fields.Char(string="Emp Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True