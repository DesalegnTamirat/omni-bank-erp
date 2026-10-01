# -*- coding: utf-8 -*-
"""
hr_applicant.py
Extends the core hr.applicant model with custom recruitment fields required
by Bunna Bank's recruitment process (Internal / External recruitment journeys).
"""
from email.policy import default

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


# # ── Applicant qualification line ───────────────────────────────────────────
# class ApplicantQualificationLine(models.Model):
#     _name = 'applicant.qualification.line'
#     _description = 'Applicant Qualification Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     qualification = fields.Many2one(
#         'recruitment.qualification', string='Qualification',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
#     active = fields.Boolean(default=True)
# 
#     def unlink(self):
#         """ Soft delete: Archive records instead of removing from DB """
#         for rec in self:
#             rec.write({'active': False})
#         return True
# 
# 
# # ── Applicant experience line ──────────────────────────────────────────────
# class ApplicantExperienceLine(models.Model):
#     _name = 'applicant.experience.line'
#     _description = 'Applicant Experience Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     experience = fields.Many2one(
#         'recruitment.experience', string='Experience',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
# 
# 
# # ── Applicant competency line ──────────────────────────────────────────────
# class ApplicantCompetencyLine(models.Model):
#     _name = 'applicant.competency.line'
#     _description = 'Applicant Competency Line'
# 
#     applicant_id = fields.Many2one(
#         'hr.applicant', string='Applicant',
#         required=True, ondelete='cascade', index=True,
#     )
#     competencies = fields.Many2one(
#         'recruitment.competency', string='Competency',
#     )
#     requirement = fields.Char(string='Requirement')
#     response = fields.Char(string='Response / Achieved')
#     active = fields.Boolean(default=True)
# 
#     def unlink(self):
#         """ Soft delete: Archive records instead of removing from DB """
#         for rec in self:
#             rec.write({'active': False})
#         return True


# ── hr.applicant extension ─────────────────────────────────────────────────
class HrApplicantCustom(models.Model):
    """Extends hr.applicant with Bunna Bank recruitment-specific fields."""
    _inherit = 'hr.applicant'

    # ── Application classification ─────────────────────────────────────────
    application_type = fields.Selection([
        ('Internal', 'Internal'),
        ('External', 'External'),
    ], string='Application Type', default='External',
        help='Whether this is an internal transfer/promotion or external hire.')

    app_reference = fields.Many2one(
        'job.vacancy', string='Vacancy Reference',
        help='Links this applicant to a specific job vacancy.',
    )
    vacancy_reference = fields.Char(
        string='Vacancy No.',
        related='app_reference.reference', store=True, readonly=True,
    )
    preferred_location = fields.Char(
        string='Preferred Location',
        help='Applicant preferred work location.',
    )
    candidate_score_id = fields.Many2one(
        'recruitment.candidate.score', string='Candidate Score',
        help='Link to the candidate score record for this applicant.',
    )

    # ── External ATS Candidate Profile Link ─────────────────────────────────
    candidate_profile_id = fields.Many2one(
        'candidate.profile',
        string='Candidate Master Profile',
        ondelete='set null',
        index=True,
        help='Link to the applicant\'s master candidate profile / electronic CV.',
    )
    total_experience_years = fields.Float(
        string="Total Exp (Years)",
        compute="_compute_weighted_experience",
        store=True,
        readonly=True,
        help="Weighted total experience calculated for this vacancy based on hiring workunit rules."
    )
    raw_banking_experience = fields.Float(
        related='candidate_profile_id.banking_experience',
        string="Banking Exp (Years)",
        readonly=True,
        store=True,
    )
    raw_non_banking_experience = fields.Float(
        related='candidate_profile_id.non_banking_experience',
        string="Raw Non-Banking Exp (Years)",
        readonly=True,
        store=True,
    )
    weighted_non_banking_experience = fields.Float(
        string="Weighted Non-Banking Exp (Years)",
        compute="_compute_weighted_experience",
        store=True,
        readonly=True,
    )
    is_hr_or_it_workunit = fields.Boolean(
        string="HR/IT Workunit (Full Credit)",
        compute="_compute_weighted_experience",
        store=True,
        readonly=True,
    )
    highest_education = fields.Char(
        related='candidate_profile_id.highest_education',
        string="Highest Education",
        readonly=True,
    )
    latest_cgpa = fields.Float(
        related='candidate_profile_id.latest_cgpa',
        string="Latest CGPA",
        readonly=True,
    )
    cover_letter = fields.Text(
        string='Cover Letter',
        help='Vacancy-specific cover letter submitted by candidate.',
    )
    expected_salary = fields.Float(
        string='Expected Salary',
        help='Expected monthly salary in ETB.',
    )
    notice_period_days = fields.Integer(
        string='Notice Period (Days)',
        help='Notice period required with current employer.',
    )

    # ── Assessment Scheduling & Notification Tracking for ATS Portal ─────────
    scheduled_exam_date = fields.Datetime(
        string="Scheduled Exam Date", compute="_compute_assessment_schedules"
    )
    scheduled_exam_location = fields.Char(
        string="Scheduled Exam Location", compute="_compute_assessment_schedules"
    )
    is_exam_notified = fields.Boolean(
        string="Exam Notified", compute="_compute_assessment_schedules"
    )
    scheduled_interview_date = fields.Datetime(
        string="Scheduled Interview Date", compute="_compute_assessment_schedules"
    )
    scheduled_interview_location = fields.Char(
        string="Scheduled Interview Location", compute="_compute_assessment_schedules"
    )
    is_interview_notified = fields.Boolean(
        string="Interview Notified", compute="_compute_assessment_schedules"
    )

    @api.depends(
        'candidate_profile_id.banking_experience',
        'candidate_profile_id.non_banking_experience',
        'candidate_profile_id.total_experience_years',
        'application_type',
        'app_reference',
        'app_reference.operating_unit_id',
        'department_id',
        'job_id',
        'job_id.department_id'
    )
    def _compute_weighted_experience(self):
        for app in self:
            cand = app.candidate_profile_id
            raw_b = cand.banking_experience if cand else 0.0
            raw_nb = cand.non_banking_experience if cand else 0.0
            raw_tot = cand.total_experience_years if cand else (raw_b + raw_nb)

            ou = False
            dept = False
            if app.app_reference:
                ou = getattr(app.app_reference, 'operating_unit_id', False)
                if hasattr(app.app_reference, 'department_id') and app.app_reference.department_id:
                    dept = app.app_reference.department_id
            if not dept:
                dept = app.department_id or (app.job_id and app.job_id.department_id)

            is_hr_it = False
            if ou:
                ou_name = (ou.name or '').lower()
                ou_code = (getattr(ou, 'code', '') or '').lower()
                if getattr(ou, 'full_non_banking_credit', False) or any(kw in ou_name or kw in ou_code for kw in ['hr', 'human resource', 'it', 'information technology', 'ict', 'software', 'digital']):
                    is_hr_it = True

            if not is_hr_it and dept:
                dept_name = (dept.name or '').lower()
                dept_code = (getattr(dept, 'code', '') or '').lower()
                if getattr(dept, 'full_non_banking_credit', False) or any(kw in dept_name or kw in dept_code for kw in ['hr', 'human resource', 'it', 'information technology', 'ict', 'software', 'digital']):
                    is_hr_it = True

            app.is_hr_or_it_workunit = is_hr_it

            # Apply 50% non-banking experience weighting rule ONLY for External vacancies
            is_external = (app.application_type == 'External') or (app.app_reference and getattr(app.app_reference, 'sourcing_type', '') in ('external', 'both'))
            if is_external:
                weight = 1.0 if is_hr_it else 0.5
                w_nb = round(raw_nb * weight, 2)
                app.weighted_non_banking_experience = w_nb
                app.total_experience_years = round(raw_b + w_nb, 2)
            else:
                app.weighted_non_banking_experience = round(raw_nb, 2)
                app.total_experience_years = round(raw_tot, 2)

    def _compute_assessment_schedules(self):
        ExtSelCand = self.env['external.recruitment.selected.candidates'].sudo()
        ExtSel = self.env['external.recruitment.selected'].sudo()

        for app in self:
            exam_dt = False
            exam_loc = 'Main Branch'
            exam_notif = False
            inter_dt = False
            inter_loc = 'Head Office'
            inter_notif = False

            vac = app.app_reference
            vac_id = vac.id if vac else False
            vac_ref = vac.reference if vac else False

            # 1. Check external.recruitment.selected.candidates
            ext_cand = ExtSelCand.search([
                '|', ('applicant_name', '=', app.id),
                ('applicant_email', '=ilike', app.email_from or 'no_match_email')
            ], limit=1, order='id desc')

            if ext_cand and ext_cand.ext_rec_sel_cand:
                parent_sel = ext_cand.ext_rec_sel_cand
                if parent_sel.written_exam_date:
                    exam_dt = parent_sel.written_exam_date
                    exam_loc = parent_sel.exam_location or 'Main Branch'
                    exam_notif = (parent_sel.exam_scheduled == 'Yes') or (parent_sel.status == 'notify') or bool(parent_sel.written_exam_date)
                if parent_sel.interview_date:
                    inter_dt = parent_sel.interview_date
                    inter_loc = parent_sel.interview_location or 'Head Office'
                    inter_notif = (parent_sel.interview_scheduled == 'Yes') or bool(parent_sel.interview_date)

            # 2. Check external.recruitment.selected by vacancy
            if not exam_dt and (vac_id or vac_ref):
                ext_sel = ExtSel.search([
                    '|', ('vacancy_id', '=', vac_id or 0),
                    ('vacancy_reference', '=', vac_ref or '')
                ], limit=1, order='id desc')
                if ext_sel:
                    if ext_sel.written_exam_date:
                        exam_dt = ext_sel.written_exam_date
                        exam_loc = ext_sel.exam_location or 'Main Branch'
                        exam_notif = (ext_sel.exam_scheduled == 'Yes') or (ext_sel.status == 'notify') or bool(ext_sel.written_exam_date)
                    if ext_sel.interview_date:
                        inter_dt = ext_sel.interview_date
                        inter_loc = ext_sel.interview_location or 'Head Office'
                        inter_notif = (ext_sel.interview_scheduled == 'Yes') or bool(ext_sel.interview_date)

            # 4. Check if vacancy itself has written_exam_date or interview_date
            if not exam_dt and vac:
                try:
                    if getattr(vac, 'written_exam_date', False):
                        exam_dt = vac.written_exam_date
                        exam_loc = getattr(vac, 'exam_location', False) or 'Main Branch'
                        exam_notif = True
                    if getattr(vac, 'interview_date', False):
                        inter_dt = vac.interview_date
                        inter_loc = getattr(vac, 'interview_location', False) or 'Head Office'
                        inter_notif = True
                except Exception:
                    pass

            # 5. Fallback search on external.recruitment.selected by job_position
            if not exam_dt and app.job_id:
                ext_sel_job = ExtSel.search([('job_position', '=', app.job_id.id)], limit=1, order='id desc')
                if ext_sel_job:
                    if ext_sel_job.written_exam_date:
                        exam_dt = ext_sel_job.written_exam_date
                        exam_loc = ext_sel_job.exam_location or 'Main Branch'
                        exam_notif = True
                    if ext_sel_job.interview_date:
                        inter_dt = ext_sel_job.interview_date
                        inter_loc = ext_sel_job.interview_location or 'Head Office'
                        inter_notif = True

            app.scheduled_exam_date = exam_dt
            app.scheduled_exam_location = exam_loc
            app.is_exam_notified = bool(exam_dt)
            app.scheduled_interview_date = inter_dt
            app.scheduled_interview_location = inter_loc
            app.is_interview_notified = bool(inter_dt)

    # ── Bunna-specific application status tracking ────────────────────────
    # NOTE: core hr.applicant already defines 'application_status' as a
    # computed field (ongoing/hired/refused/archived). We use a separate
    # field 'bunna_app_status' to track the Bunna recruitment workflow stage
    # without overriding the core field.
    bunna_app_status = fields.Selection([
        ('draft', 'Draft'),
        ('shortlisted', 'Shortlisted'),
        ('interview', 'Interview'),
        ('offer', 'Offer Issued'),
        ('hired', 'Hired'),
        ('rejected', 'Rejected'),
    ], string='Bunna Application Status', default='draft', tracking=True)

    job_offer_status = fields.Selection([
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ], string='Job Offer Status', default='pending', tracking=True)

    # ── Pre-Employment Onboarding & Clearance Verification ─────────────────
    forensic_certificate = fields.Binary(
        string='Forensic / Police Clearance Certificate',
        attachment=True,
        help="Upload the official Police Clearance / Forensic Certificate."
    )
    forensic_certificate_filename = fields.Char(string='Forensic Certificate Filename')
    forensic_cleared = fields.Boolean(
        string='Forensic Clearance Verified',
        default=False,
        tracking=True,
        help="Check when the forensic / police clearance has been verified by HR."
    )

    medical_certificate = fields.Binary(
        string='Medical Examination Certificate',
        attachment=True,
        help="Upload the official Medical Fitness Examination Certificate."
    )
    medical_certificate_filename = fields.Char(string='Medical Certificate Filename')
    medical_cleared = fields.Boolean(
        string='Medical Examination Cleared',
        default=False,
        tracking=True,
        help="Check when the medical fitness examination has been cleared."
    )

    educational_docs_verified = fields.Boolean(
        string='Educational Credentials Verified',
        default=False,
        tracking=True,
        help="Check when all degree/diploma certificates and transcripts have been authenticated."
    )

    guarantor_form = fields.Binary(
        string='Guarantor / Reference Document',
        attachment=True,
        help="Upload the signed guarantor / reference form."
    )
    guarantor_form_filename = fields.Char(string='Guarantor Document Filename')

    rejection_reason = fields.Text(string='Rejection Reason')
    offer_letter_sent = fields.Boolean(string='Offer Letter Sent', default=False)
    contract_created_new = fields.Boolean(string='Contract Created', default=False)

    active_leave_status = fields.Char(
        string="Leave Status", compute="_compute_applicant_leave_status", store=False,
        help="Displays active leave status if applicant is currently an employee on leave."
    )
    active_disciplinary_status = fields.Selection(
        [
            ("none", "No Active Warning"),
            ("first_warning", "First Warning (Severity Level 4)"),
            ("second_warning", "Second Warning (Severity Level 3)"),
            ("last_written_warning", "Active Last Written Warning (Severity Level 1/2)"),
        ],
        string="Discipline Warning Level",
        compute="_compute_applicant_disciplinary_status",
        store=False,
        help="Pulled from Discipline Management (discipline.case) based on case severity levels."
    )

    @api.depends('internal_employee_id')
    def _compute_applicant_disciplinary_status(self):
        for rec in self:
            emp = rec.internal_employee_id
            if emp and 'discipline.case' in self.env:
                active_cases = self.env['discipline.case'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'enforced'),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or 'final_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.active_disciplinary_status = 'first_warning'
                    else:
                        rec.active_disciplinary_status = 'none'
                else:
                    rec.active_disciplinary_status = 'none'
            else:
                rec.active_disciplinary_status = 'none'

    @api.depends('internal_employee_id')
    def _compute_applicant_leave_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            emp = rec.internal_employee_id
            if emp:
                leaves = self.env['hr.leave'].search([
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', today),
                    ('date_to', '>=', today),
                ], limit=1)
                if leaves:
                    rec.active_leave_status = leaves.holiday_status_id.name if leaves.holiday_status_id else _("On Leave")
                else:
                    rec.active_leave_status = _("Active")
            else:
                rec.active_leave_status = _("N/A")


    def action_validate_completeness(self):
        """Validate applicant profile completeness. Automatically reject incomplete submissions."""
        for rec in self:
            missing = []
            if rec.application_type == 'External':
                if not (rec.partner_name or rec.name):
                    missing.append(_("Full Name"))
                if not rec.email_from:
                    missing.append(_("Email"))
                if not rec.partner_phone:
                    missing.append(_("Phone Number"))
                if not rec.gender:
                    missing.append(_("Gender"))
                if not rec.date_of_birth:
                    missing.append(_("Date of Birth"))
            elif rec.application_type == 'Internal':
                if not rec.internal_employee_id:
                    missing.append(_("Internal Employee"))

            if missing:
                reason = _("Rejected Incomplete Submission. Missing mandatory fields: %s") % ", ".join(missing)
                rec.write({
                    'bunna_app_status': 'rejected',
                    'rejection_reason': reason,
                    'active': False,
                })
                rec.message_post(body=reason)
                return False
        return True


    cv_attachment_id = fields.Many2one('ir.attachment', string='CV Attachment', compute='_compute_cv_attachment_id',
                                       store=False)
    cv_preview_html = fields.Html(
        string='CV Document In-Browser Preview',
        compute='_compute_cv_preview_html',
        sanitize=False,
    )
    profile_summary_html = fields.Html(
        string='Electronic CV Summary Sheet',
        compute='_compute_profile_summary_html',
        sanitize=False,
    )
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    def _compute_cv_attachment_id(self):
        for rec in self:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', rec.id)
            ], limit=1, order='id desc')
            rec.cv_attachment_id = att.id if att else False

    def _compute_cv_preview_html(self):
        import html
        for rec in self:
            url = False
            fn = 'CV_Document.pdf'
            if rec.candidate_profile_id and rec.candidate_profile_id.cv_file:
                fn = rec.candidate_profile_id.cv_filename or 'CV_Document.pdf'
                url = f"/web/content?model=candidate.profile&id={rec.candidate_profile_id.id}&field=cv_file&filename={html.escape(fn)}"
            elif rec.cv_attachment_id:
                fn = rec.cv_attachment_id.name or 'CV_Document.pdf'
                url = f"/web/content/{rec.cv_attachment_id.id}/{html.escape(fn)}"
            else:
                att = self.env['ir.attachment'].search([
                    ('res_model', '=', 'hr.applicant'),
                    ('res_id', '=', rec.id)
                ], limit=1, order='id desc')
                if att:
                    fn = att.name or 'CV_Document.pdf'
                    url = f"/web/content/{att.id}/{html.escape(fn)}"

            if url:
                rec.cv_preview_html = f"""
                <div style="width: 100%; min-height: 750px; height: 80vh; background: #2c3e50; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.15); display: flex; flex-direction: column;">
                    <div style="background: #1a252f; color: #ffffff; padding: 10px 18px; display: flex; justify-content: space-between; align-items: center; font-size: 14px; font-weight: 600;">
                        <span><i class="fa fa-file-pdf-o" style="margin-right: 8px; color: #e74c3c;"></i> {html.escape(fn)}</span>
                        <div>
                            <a href="{url}" target="_blank" class="btn btn-sm btn-outline-light" style="font-size: 12px; margin-right: 8px;"><i class="fa fa-external-link"></i> Full Screen</a>
                            <a href="{url}&download=true" class="btn btn-sm btn-primary" style="font-size: 12px;"><i class="fa fa-download"></i> Download</a>
                        </div>
                    </div>
                    <iframe src="{url}#toolbar=1&navpanes=1" style="width: 100%; height: 100%; flex-grow: 1; border: none;" allowfullscreen="true"></iframe>
                </div>
                """
            else:
                rec.cv_preview_html = """
                <div style="padding: 40px; text-align: center; background: #f8f9fa; border: 2px dashed #ced4da; border-radius: 10px; margin: 20px 0;">
                    <i class="fa fa-file-text-o" style="font-size: 48px; color: #6c757d; margin-bottom: 15px; display: block;"></i>
                    <h5 style="color: #495057; font-weight: 600;">No Uploaded CV File Attached</h5>
                    <p style="color: #6c757d; font-size: 13px; max-width: 450px; margin: 0 auto 15px auto;">No standalone CV attachment was found. You can review the complete structured electronic candidate resume under the <strong>Electronic CV Summary</strong> tab.</p>
                </div>
                """

    def _compute_profile_summary_html(self):
        import html
        for rec in self:
            if rec.candidate_profile_id:
                rec.profile_summary_html = rec.candidate_profile_id.profile_summary_html
            else:
                # Build from applicant's own records
                edu_rows = "".join([f"<div style='margin-bottom:8px; border-bottom:1px solid #eee; padding-bottom:4px;'><strong>{html.escape(q.qualification.qualification if q.qualification else '')}</strong> <span style='float:right; color:#888;'>CGPA/Score: {q.response or ''}</span></div>" for q in rec.qualification_id])
                exp_rows = "".join([f"<div style='margin-bottom:8px; border-bottom:1px solid #eee; padding-bottom:4px;'><strong>{html.escape(e.experience.experience if e.experience else '')}</strong> <span style='float:right; color:#888;'>{e.response or '0'} Yrs</span></div>" for e in rec.experiance_id])
                comp_rows = "".join([f"<span class='badge' style='background:#4a1515; color:#fff; margin:2px 4px; padding:5px 10px; border-radius:10px;'>{html.escape(getattr(c.competencies, 'competencies', '') or getattr(c.competencies, 'name', '') or '')}</span>" for c in rec.competencies_id if c.competencies])

                rec.profile_summary_html = f"""
                <div style="background:#ffffff; border:1px solid #e0e0e0; border-radius:12px; padding:25px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                    <div style="border-bottom: 2px solid #4a1515; padding-bottom: 14px; margin-bottom: 18px;">
                        <h3 style="color:#4a1515; margin:0 0 4px 0;">{html.escape(rec.partner_name or rec.name or 'Candidate Profile')}</h3>
                        <div style="color:#666; font-size:13px;">
                            <span><i class="fa fa-envelope" style="color:#b38b59;"></i> {html.escape(rec.email_from or '')}</span> &nbsp;|&nbsp;
                            <span><i class="fa fa-phone" style="color:#b38b59;"></i> {html.escape(rec.partner_phone or '')}</span> &nbsp;|&nbsp;
                            <span>Position: {html.escape(rec.job_id.name if rec.job_id else '')}</span>
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                        <div>
                            <h5 style="color:#4a1515; border-bottom:1px solid #ddd; padding-bottom:4px;">Education Qualifications</h5>
                            {edu_rows or "<p style='color:#888; font-style:italic;'>No qualifications listed</p>"}
                        </div>
                        <div>
                            <h5 style="color:#4a1515; border-bottom:1px solid #ddd; padding-bottom:4px;">Work Experience</h5>
                            {exp_rows or "<p style='color:#888; font-style:italic;'>No experience listed</p>"}
                        </div>
                    </div>
                    <div style="margin-top:15px;">
                        <h5 style="color:#4a1515; border-bottom:1px solid #ddd; padding-bottom:4px;">Competencies &amp; Skills</h5>
                        <div>{comp_rows or "<p style='color:#888; font-style:italic;'>No competencies listed</p>"}</div>
                    </div>
                </div>
                """

    def action_preview_cv(self):
        self.ensure_one()
        url = False
        if self.candidate_profile_id and self.candidate_profile_id.cv_file:
            fn = self.candidate_profile_id.cv_filename or 'CV_Document.pdf'
            url = f"/web/content?model=candidate.profile&id={self.candidate_profile_id.id}&field=cv_file&filename={fn}"
        elif self.cv_attachment_id:
            url = f"/web/content/{self.cv_attachment_id.id}/{self.cv_attachment_id.name}"
        else:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', self.id)
            ], limit=1, order='id desc')
            if att:
                url = f"/web/content/{att.id}/{att.name}"

        if not url:
            raise UserError(_("No CV document found for applicant %s.") % (self.partner_name or self.name))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_download_cv(self):
        self.ensure_one()
        att = self.cv_attachment_id
        if not att:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'hr.applicant'),
                ('res_id', '=', self.id)
            ], limit=1, order='id desc')
        if not att:
            raise ValidationError(_("No CV attachment found for this applicant."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{att.id}?download=true',
            'target': 'new',
        }

    # ── Personal information ───────────────────────────────────────────────
    date_of_birth = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    place_of_birth = fields.Char(string='Place of Birth')
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender')

    # ── Work history / suitability flags ──────────────────────────────────
    worked_in_bunna_earlier = fields.Boolean(
        string='Previously Worked at Bunna Bank', default=False,
    )
    current_company = fields.Char(string='Current Company')
    current_working_location = fields.Char(string='Current Working Location')
    working_status = fields.Selection([
        ('employed', 'Employed'),
        ('unemployed', 'Unemployed'),
        ('self_employed', 'Self-Employed'),
    ], string='Working Status', default='unemployed')
    willing_to_join_immediately = fields.Boolean(
        string='Willing to Join Immediately', default=False,
    )
    date_of_availability = fields.Date(string='Date of Availability')
    functions = fields.Char(string='Functions', help='Internal compute helper flag.')
    prmt_emp = fields.Char(string='Promote Employee Flag', default='No')

    # ── Internal applicant details ─────────────────────────────────────────
    # NOTE: the DB already has an 'internal_employee_name' varchar column with
    # stored employee names. We keep that as a Char field for backward-compat
    # and introduce 'internal_employee_id' (Many2one) with a different DB column.
    internal_employee_name = fields.Char(
        string='Internal Employee Name (Legacy)',
        help='Previously stored as free text. Kept for backward compatibility.',
    )
    internal_employee_id = fields.Many2one(
        'hr.employee', string='Internal Employee',
        help='Select the internal employee applying for this vacancy.',
    )
    employee_work_unit = fields.Char(
        string='Current Work Unit',
        compute='_compute_employee_work_unit',
        store=False, readonly=True,
    )
    employee_number = fields.Char(
        string='Employee ID',
        compute='_compute_employee_number',
        store=False, readonly=True,
    )
    employee_grade = fields.Char(string='Employee Grade')
    employee_position = fields.Char(string='Current Position')
    manager = fields.Many2one('hr.employee', string='Direct Manager')
    promotion_date = fields.Date(string='Last Promotion Date')
    employment_start_date = fields.Date(string='Employment Start Date')
    final_work_unit = fields.Many2one('hr.department', string='Assigned Work Unit', ondelete='set null')
    cc_workunits = fields.Many2many(
        'hr.department', string='CC Work Units',
        help="Additional departments CC'd on this application.",
    )

    # ── Qualifications / Experience / Competency tabs ─────────────────────
    qualification_id = fields.One2many(
        'hr_qualification_info_job', 'applicant_id',
        string='Education Qualifications',
    )
    experiance_id = fields.One2many(
        'hr_experience_info_job', 'applicant_id',
        string='Experience',
    )
    competencies_id = fields.One2many(
        'hr_competencies_info_job', 'applicant_id',
        string='Competencies',
    )
    hr_new_department_ids = fields.One2many(
        'hr_new_department_info_job', 'applicant_id',
        string='Vacancies',
    )

    # ── Computed fields ────────────────────────────────────────────────────
    @api.depends('date_of_birth')
    def _compute_age(self):
        from datetime import date
        today = date.today()
        for rec in self:
            if rec.date_of_birth:
                dob = rec.date_of_birth
                rec.age = (today - dob).days // 365
            else:
                rec.age = 0

    @api.depends('internal_employee_id')
    def _compute_employee_work_unit(self):
        for rec in self:
            rec.employee_work_unit = rec.internal_employee_id.department_id.name or ''

    @api.depends('internal_employee_id')
    def _compute_employee_number(self):
        for rec in self:
            rec.employee_number = rec.internal_employee_id.barcode or ''

    # ── Onchange: cascade vacancy reference fields ─────────────────────────
    @api.onchange('app_reference')
    def _onchange_app_reference(self):
        for rec in self:
            if rec.app_reference:
                rec.application_type = (
                    'Internal' if rec.app_reference.internal_movement_type in ('internal', 'promotion', 'lateral', 'transfer')
                    else 'External'
                )

    # ── Onboarding & Pre-Employment Verification Check ─────────────────────
    def _check_onboarding_prerequisites(self):
        """
        Enforce strict pre-employment verification before creating Employee or Contract.
        Mandatory checks for External Candidates:
        1. Offer Letter must be accepted.
        2. Forensic / Police Clearance Certificate must be provided & verified.
        3. Medical Examination / Fitness Certificate must be provided & cleared.
        """
        for rec in self:
            if rec.application_type == 'External':
                missing_checks = []

                # 1. Offer Letter Accepted check
                offer_accepted = (rec.job_offer_status == 'accepted')
                if not offer_accepted and 'recruitment.offer.letter' in self.env:
                    # Check linked offer letter in recruitment.offer.letter
                    accepted_offer = self.env['recruitment.offer.letter'].search([
                        '|', ('applicant_id', '=', rec.id),
                        ('candidate_email', '=ilike', (rec.email_from or '').strip()),
                        ('state', '=', 'accepted')
                    ], limit=1)
                    if accepted_offer:
                        offer_accepted = True
                        if rec.job_offer_status != 'accepted':
                            rec.job_offer_status = 'accepted'

                if not offer_accepted:
                    missing_checks.append(_("• Formal Offer Letter: Must be accepted by candidate (Job Offer Status = 'Accepted')"))

                # 2. Forensic / Police Clearance check
                if not (rec.forensic_certificate or rec.forensic_cleared):
                    missing_checks.append(_("• Forensic Certificate: Police Clearance / Forensic Certificate must be uploaded or verified"))

                # 3. Medical Fitness Certificate check
                if not (rec.medical_certificate or rec.medical_cleared):
                    missing_checks.append(_("• Medical Certificate: Medical Fitness / Examination Certificate must be uploaded or verified"))

                if missing_checks:
                    raise UserError(_(
                        "Mandatory Pre-Employment Verification Incomplete!\n\n"
                        "Before creating the Employee record or Contract for %s, all required pre-employment verification checkpoints must be completed:\n\n"
                        "%s\n\n"
                        "Please update the 'Pre-Employment Verification & Clearance' section on this application before proceeding."
                    ) % (rec.partner_name or rec.name or 'this applicant', "\n".join(missing_checks)))

    # ── Resolve Job Grade & Operating Unit for New Employee ────────────────
    def _resolve_applicant_job_grade(self):
        """Finds or resolves the employee.grade record for this applicant."""
        self.ensure_one()
        grade_rec = False
        if self.app_reference:
            grade_rec = getattr(self.app_reference, 'grade', False) or getattr(self.app_reference, 'job_grade', False)
        if not grade_rec and self.job_id:
            grade_rec = getattr(self.job_id, 'job_grade', False) or getattr(self.job_id, 'grade_id', False)
        if not grade_rec and self.employee_grade:
            grade_rec = self.env['employee.grade'].search([
                '|', ('grade_name', '=ilike', str(self.employee_grade).strip()),
                ('grade_code', '=ilike', str(self.employee_grade).strip())
            ], limit=1)
        if not grade_rec:
            # Safe fallback: pick the lowest/first active grade
            grade_rec = self.env['employee.grade'].search([], order='id asc', limit=1)
        return grade_rec

    def _get_employee_create_vals(self):
        vals = super()._get_employee_create_vals()
        grade_rec = self._resolve_applicant_job_grade()
        if grade_rec:
            vals['job_grade'] = grade_rec.id
            if hasattr(self.env['hr.employee'], 'grade'):
                vals['grade'] = grade_rec.id
            if hasattr(self.env['hr.employee'], 'grade_id'):
                vals['grade_id'] = grade_rec.id
            if hasattr(self.env['hr.employee'], 'emp_grade'):
                vals['emp_grade'] = grade_rec.grade_name

        # Resolve destination operating unit
        ou = False
        if self.app_reference and getattr(self.app_reference, 'operating_unit_id', False):
            ou = self.app_reference.operating_unit_id
        elif self.preferred_location:
            ou = self.env['operating.unit'].search([('name', '=ilike', self.preferred_location.strip())], limit=1)

        if ou and hasattr(self.env['hr.employee'], 'default_operating_unit_id'):
            vals['default_operating_unit_id'] = ou.id

        return vals

    # ── Button actions ─────────────────────────────────────────────────────
    def _populate_employee_from_applicant_and_profile(self, employee):
        """Populates employee personal info, demographics, address, and all Qualification & Criteria
        sub-tabs (Education Qualification, Experience, Competencies) from Candidate Profile (CV)."""
        self.ensure_one()
        if not employee:
            return

        cand = self.candidate_profile_id
        emp_write = {}

        # 1. Personal Information & Demographics (Image 2)
        if cand:
            if hasattr(employee, 'father_name') and not employee.father_name:
                emp_write['father_name'] = getattr(cand, 'father_name', False) or getattr(self, 'father_name', False)
            if hasattr(employee, 'grand_father_name') and not employee.grand_father_name:
                emp_write['grand_father_name'] = getattr(cand, 'grand_father_name', False) or getattr(self, 'grand_father_name', False)
            if hasattr(employee, 'mother_name') and not employee.mother_name:
                emp_write['mother_name'] = getattr(cand, 'mother_name', False)
            if hasattr(employee, 'birthday') and not employee.birthday:
                emp_write['birthday'] = cand.dob or cand.birth_date or getattr(self, 'date_of_birth', False)
            if hasattr(employee, 'date_of_birth') and not employee.date_of_birth:
                emp_write['date_of_birth'] = cand.dob or cand.birth_date or getattr(self, 'date_of_birth', False)
            if hasattr(employee, 'age') and not employee.age:
                emp_write['age'] = str(cand.age or getattr(self, 'age', '') or '')
            if hasattr(employee, 'gender') and not employee.gender:
                emp_write['gender'] = cand.gender or getattr(self, 'gender', False)
            if hasattr(employee, 'place_of_birth') and not employee.place_of_birth:
                emp_write['place_of_birth'] = cand.place_of_birth or getattr(self, 'place_of_birth', False)
            if hasattr(employee, 'blood_group') and not employee.blood_group:
                emp_write['blood_group'] = getattr(cand, 'blood_group', False)
            if hasattr(employee, 'house_number') and not employee.house_number:
                emp_write['house_number'] = getattr(cand, 'house_number', False)
            if hasattr(employee, 'city') and not employee.city:
                emp_write['city'] = cand.city or getattr(cand, 'city', False)
            if hasattr(employee, 'sub_city') and not employee.sub_city:
                emp_write['sub_city'] = getattr(cand, 'sub_city', False)
            if hasattr(employee, 'region') and not employee.region:
                emp_write['region'] = getattr(cand, 'region', False) or (cand.state_id.name if cand.state_id else False)
            if hasattr(employee, 'woreda') and not employee.woreda:
                emp_write['woreda'] = getattr(cand, 'woreda', False)
            if hasattr(employee, 'kebele') and not employee.kebele:
                emp_write['kebele'] = getattr(cand, 'kebele', False)
            if hasattr(employee, 'mobile_phone') and not employee.mobile_phone:
                emp_write['mobile_phone'] = self.partner_phone or cand.phone
            if hasattr(employee, 'work_phone') and not employee.work_phone:
                emp_write['work_phone'] = self.partner_phone or cand.phone
            if hasattr(employee, 'phone_num') and not employee.phone_num:
                emp_write['phone_num'] = cand.phone or self.partner_phone
            if hasattr(employee, 'personal_phone') and not employee.personal_phone:
                emp_write['personal_phone'] = cand.phone or self.partner_phone
            if hasattr(employee, 'private_phone') and not employee.private_phone:
                emp_write['private_phone'] = cand.phone or self.partner_phone
            if hasattr(employee, 'alternative_mobile') and not employee.alternative_mobile:
                emp_write['alternative_mobile'] = getattr(cand, 'alternative_mobile', False) or cand.phone
            if hasattr(employee, 'personal_email') and not employee.personal_email:
                emp_write['personal_email'] = cand.email or self.email_from
            if hasattr(employee, 'private_email') and not employee.private_email:
                emp_write['private_email'] = cand.email or self.email_from
            if hasattr(employee, 'work_email') and not employee.work_email:
                emp_write['work_email'] = self.email_from or cand.email
            if hasattr(employee, 'current_company') and not employee.current_company:
                emp_write['current_company'] = cand.current_company or getattr(self, 'current_company', False)
            if hasattr(employee, 'working_status') and not employee.working_status:
                emp_write['working_status'] = cand.working_status or getattr(self, 'working_status', False)
            if hasattr(employee, 'willing_to_join_immediately') and not employee.willing_to_join_immediately:
                emp_write['willing_to_join_immediately'] = getattr(self, 'willing_to_join_immediately', False) or ('yes' if cand.join_immediately else 'no')
            if hasattr(employee, 'date_of_availability') and not employee.date_of_availability:
                emp_write['date_of_availability'] = getattr(self, 'date_of_availability', False)
            if hasattr(employee, 'marital') and not employee.marital and hasattr(cand, 'marital_status'):
                emp_write['marital'] = cand.marital_status

        if emp_write:
            employee.sudo().write(emp_write)

        # 2. Education Qualifications Tab (Image 1 Sub-tab 1)
        if cand and cand.education_ids:
            # A. hr.employee.education (edu_ids)
            if hasattr(employee, 'edu_ids') and not employee.edu_ids:
                edu_vals = []
                for edu in cand.education_ids:
                    adm_y = edu.start_date.year if edu.start_date else 0
                    grad_y = edu.end_date.year if edu.end_date else (edu.graduation_year.year if hasattr(edu, 'graduation_year') and edu.graduation_year else 0)
                    prog_type = 'Full time'
                    if hasattr(edu, 'program_type') and edu.program_type and 'program_type' in edu._fields:
                        prog_type = dict(edu._fields['program_type'].selection).get(edu.program_type, 'Regular')
                    edu_vals.append((0, 0, {
                        'qualification': edu.qualification_name,
                        'specialization': edu.field_of_study,
                        'university': edu.institution,
                        'college_or_school': edu.institution,
                        'year_of_admission': adm_y,
                        'year_of_outcome': grad_y,
                        'cgpa_percentage': edu.cgpa or 0.0,
                        'fulltime': prog_type,
                    }))
                if edu_vals:
                    employee.sudo().write({'edu_ids': edu_vals})

            # B. employee.education (education_detail_ids)
            if 'employee.education' in self.env:
                existing_emp_edu = self.env['employee.education'].sudo().search([('employee_id', '=', employee.id)])
                if not existing_emp_edu:
                    valid_types = dict(self.env['employee.education']._fields['edu_type'].selection).keys() if 'edu_type' in self.env['employee.education']._fields and self.env['employee.education']._fields['edu_type'].selection else []
                    for edu in cand.education_ids:
                        lvl = getattr(edu, 'education_level', '')
                        etype = 'formal'
                        if lvl in ('diploma', 'tvet') and 'vocational' in valid_types:
                            etype = 'vocational'
                        elif 'formal' in valid_types:
                            etype = 'formal'
                        elif 'bachelor' in valid_types:
                            etype = 'bachelor'
                        elif valid_types:
                            etype = list(valid_types)[0]
                        else:
                            etype = False

                        edu_vals_dict = {
                            'employee_id': employee.id,
                            'from_date': edu.start_date,
                            'to_date': edu.end_date or (edu.graduation_year if hasattr(edu, 'graduation_year') else False),
                            'field': edu.field_of_study,
                            'school_name': edu.institution,
                            'CGPA': edu.cgpa or 0.0,
                            'qualification': edu.qualification_name,
                        }
                        if etype:
                            edu_vals_dict['edu_type'] = etype
                        self.env['employee.education'].sudo().create(edu_vals_dict)

            # C. hr_qualification_info_job (qualification_id)
            if hasattr(employee, 'qualification_id') and not employee.qualification_id and 'recruitment.qualification' in self.env:
                q_vals = []
                for edu in cand.education_ids:
                    q_rec = self.env['recruitment.qualification'].sudo().search([('qualification', '=ilike', edu.qualification_name)], limit=1)
                    if not q_rec and edu.qualification_name:
                        q_rec = self.env['recruitment.qualification'].sudo().create({'qualification': edu.qualification_name})
                    if q_rec:
                        q_vals.append((0, 0, {
                            'qualification': q_rec.id,
                            'requirement': edu.cgpa or 0.0,
                            'response': edu.cgpa or 0.0,
                        }))
                if q_vals:
                    employee.sudo().write({'qualification_id': q_vals})

        # 3. Experience Tab (Image 1 Sub-tab 2)
        if cand and cand.experience_ids:
            if hasattr(employee, 'experiance_id') and not employee.experiance_id and 'recruitment.experience' in self.env:
                exp_vals = []
                for exp in cand.experience_ids:
                    exp_rec = self.env['recruitment.experience'].sudo().search([('experience', '=ilike', exp.position)], limit=1)
                    if not exp_rec and exp.position:
                        exp_rec = self.env['recruitment.experience'].sudo().create({'experience': exp.position})
                    if exp_rec:
                        exp_vals.append((0, 0, {
                            'experience': exp_rec.id,
                            'requirement': exp.duration_years or 0.0,
                            'response': exp.duration_years or 0.0,
                        }))
                if exp_vals:
                    employee.sudo().write({'experiance_id': exp_vals})

            # hr.resume.line
            if 'hr.resume.line' in self.env:
                existing_res = self.env['hr.resume.line'].sudo().search([('employee_id', '=', employee.id)])
                if not existing_res:
                    for exp in cand.experience_ids:
                        self.env['hr.resume.line'].sudo().create({
                            'employee_id': employee.id,
                            'name': exp.position,
                            'date_start': exp.start_date,
                            'date_end': exp.end_date,
                            'description': exp.responsibilities or f"{exp.position} at {exp.organization}",
                            'organization_name': exp.organization,
                        })

        # 4. Competencies Tab (Image 1 Sub-tab 3)
        if cand and (cand.skill_ids or cand.certification_ids):
            if hasattr(employee, 'competencies_id') and not employee.competencies_id:
                skills_list = []
                for sk in cand.skill_ids:
                    skills_list.append((sk.name, sk.level or 'intermediate'))
                for cert in cand.certification_ids:
                    skills_list.append((cert.name, 'expert'))

                comp_vals = []
                seen_comps = set()
                if 'competency.competency' in self.env:
                    for s_name, s_lvl in skills_list:
                        c_rec = self.env['competency.competency'].sudo().search([('name', '=ilike', s_name)], limit=1)
                        if c_rec and c_rec.id not in seen_comps:
                            seen_comps.add(c_rec.id)
                            comp_vals.append((0, 0, {
                                'competencies': c_rec.id,
                                'requirement': 100.0,
                                'response': 100.0,
                            }))
                elif 'recruitment.competency' in self.env:
                    comp_fields = self.env['recruitment.competency']._fields
                    for s_name, s_lvl in skills_list:
                        c_rec = False
                        if 'competencies' in comp_fields:
                            c_rec = self.env['recruitment.competency'].sudo().search([('competencies', '=ilike', s_name)], limit=1)
                            if not c_rec and s_name:
                                c_rec = self.env['recruitment.competency'].sudo().create({'competencies': s_name})
                        elif 'name' in comp_fields:
                            c_rec = self.env['recruitment.competency'].sudo().search([('name', '=ilike', s_name)], limit=1)
                            if not c_rec and s_name:
                                c_rec = self.env['recruitment.competency'].sudo().create({'name': s_name})

                        if c_rec and c_rec.id not in seen_comps:
                            seen_comps.add(c_rec.id)
                            comp_vals.append((0, 0, {
                                'competencies': c_rec.id,
                                'requirement': 100.0,
                                'response': 100.0,
                            }))
                if comp_vals:
                    employee.sudo().write({'competencies_id': comp_vals})

    def create_employee_from_applicant(self):
        """Override core employee creation to enforce mandatory pre-employment verification and pass job grade."""
        self._check_onboarding_prerequisites()
        grade_rec = self._resolve_applicant_job_grade()
        grade_id = grade_rec.id if grade_rec else False

        ctx = dict(self.env.context, default_job_grade=grade_id, job_history_reason='recruitment')
        res = super(HrApplicantCustom, self.with_context(ctx)).create_employee_from_applicant()

        # Guarantee job_grade on employee, auto-populate all profile/CV records, and handle versions
        for applicant in self:
            emp = applicant.employee_id
            if emp:
                applicant._populate_employee_from_applicant_and_profile(emp)

                if grade_rec:
                    emp_write = {}
                    if hasattr(emp, 'job_grade') and not emp.job_grade:
                        emp_write['job_grade'] = grade_rec.id
                    if hasattr(emp, 'emp_grade') and not emp.emp_grade:
                        emp_write['emp_grade'] = grade_rec.grade_name
                    if emp_write:
                        emp.sudo().write(emp_write)

                    if 'hr.version' in self.env:
                        versions = self.env['hr.version'].sudo().search([
                            ('employee_id', '=', emp.id),
                            ('job_grade', '=', False)
                        ])
                        if versions:
                            versions.write({'job_grade': grade_rec.id})

        return res

    def create_contract(self):
        """Triggers contract creation workflow after verifying mandatory checks and employee existence."""
        self._check_onboarding_prerequisites()
        if not self.employee_id:
            raise UserError(_("Please click 'Create Employee' first to create the employee record before creating a contract."))

        self.write({
            'contract_created_new': True,
            'bunna_app_status': 'hired',
        })

        if 'hr.contract' in self.env:
            existing_contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
            ], limit=1)
            if not existing_contract:
                grade_rec = self._resolve_applicant_job_grade()
                contract_vals = {
                    'name': _("Employment Contract - %s") % self.employee_id.name,
                    'employee_id': self.employee_id.id,
                    'job_id': self.job_id.id if self.job_id else self.employee_id.job_id.id,
                    'department_id': self.department_id.id if self.department_id else self.employee_id.department_id.id,
                    'wage': self.salary_proposed or self.expected_salary or 0.0,
                    'state': 'draft',
                }
                if grade_rec and 'job_grade' in self.env['hr.contract']._fields:
                    contract_vals['job_grade'] = grade_rec.id
                existing_contract = self.env['hr.contract'].sudo().create(contract_vals)

            return {
                'name': _('Employee Contract'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.contract',
                'res_id': existing_contract.id,
                'view_mode': 'form',
                'target': 'current',
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Contract Created'),
                'message': _('Pre-employment verification passed. Contract has been initialized for %s.') % (self.partner_name or self.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def promote_employee(self):
        """Placeholder: triggers internal employee promotion workflow."""
        self.write({'prmt_emp': 'Yes'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employee Promoted'),
                'message': _('Promotion has been initiated for %s.') % self.partner_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_applicant_send(self):
        """Placeholder: triggers offer letter sending workflow."""
        self.write({'offer_letter_sent': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offer Letter Sent'),
                'message': _('Offer Letter has been sent for %s.') % self.partner_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.onchange('job_id')
    def _onchange_job_id_sync_criteria(self):
        if not self.job_id:
            return
        
        # Clear existing lines first
        self.qualification_id = [(5, 0, 0)]
        self.experiance_id = [(5, 0, 0)]
        self.competencies_id = [(5, 0, 0)]
        
        # Inherit qualifications
        qual_lines = []
        for line in self.job_id.qualification_id:
            qual_lines.append((0, 0, {
                'qualification': line.qualification.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.qualification_id = qual_lines
        
        # Inherit experiences
        exp_lines = []
        for line in self.job_id.experiance_id:
            exp_lines.append((0, 0, {
                'experience': line.experience.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.experiance_id = exp_lines
        
        # Inherit competencies
        comp_lines = []
        for line in self.job_id.competencies_id:
            comp_lines.append((0, 0, {
                'competencies': line.competencies.id,
                'requirement': str(line.requirement or ''),
                'response': str(line.response or ''),
            }))
        self.competencies_id = comp_lines


    def _auto_sync_external_recruitment_eligible(self):
        for app in self:
            if app.app_reference:
                rec_ext = self.env['employee.recruitment.external'].sudo().search([('vacancy_id', '=', app.app_reference.id)], limit=1)
                if not rec_ext:
                    rec_ext = self.env['employee.recruitment.external'].sudo().create({
                        'vacancy_id': app.app_reference.id,
                        'job_position': app.app_reference.job_position.id if app.app_reference.job_position else False,
                        'vacancy_reference': app.app_reference.reference,
                        'responsible': app.app_reference.responsible.id if app.app_reference.responsible else self.env.user.employee_id.id,
                    })
                
                existing = self.env['external.recruitment.eligible.employees'].sudo().search([
                    ('external_recruitment_id', '=', rec_ext.id),
                    ('applicant_name', '=', app.id),
                ], limit=1)
                
                if not existing:
                    cand = app.candidate_profile_id
                    self.env['external.recruitment.eligible.employees'].sudo().create({
                        'external_recruitment_id': rec_ext.id,
                        'applicant_name': app.id,
                        'applicant_email': app.email_from or (cand.email if cand else ''),
                        'applicant_phone': cand.phone if cand else (app.partner_phone or ''),
                        'date_of_birth': getattr(cand, 'dob', False) if cand else False,
                        'gender': getattr(cand, 'gender', False) if cand else False,
                        'highest_cgpa': getattr(cand, 'cgpa', 0.0) if cand else 0.0,
                        'total_experience': getattr(cand, 'total_experience', 0.0) if cand else 0.0,
                    })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('job_id') and not vals.get('qualification_id') and not vals.get('experiance_id') and not vals.get('competencies_id'):
                job = self.env['hr.job'].browse(vals['job_id'])
                
                # Qualifications
                qual_lines = []
                for line in job.qualification_id:
                    qual_lines.append((0, 0, {
                        'qualification': line.qualification.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if qual_lines:
                    vals['qualification_id'] = qual_lines
                    
                # Experiences
                exp_lines = []
                for line in job.experiance_id:
                    exp_lines.append((0, 0, {
                        'experience': line.experience.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if exp_lines:
                    vals['experiance_id'] = exp_lines
                    
                # Competencies
                comp_lines = []
                for line in job.competencies_id:
                    comp_lines.append((0, 0, {
                        'competencies': line.competencies.id,
                        'requirement': str(line.requirement or ''),
                        'response': str(line.response or ''),
                    }))
                if comp_lines:
                    vals['competencies_id'] = comp_lines
                    
        res = super().create(vals_list)
        res._auto_sync_external_recruitment_eligible()

        # Guarantee every applicant record is stored and linked under Master Candidate Profiles (CVs)
        for app in res:
            if not app.candidate_profile_id:
                email = (app.email_from or '').strip().lower()
                phone = (app.partner_phone or '').strip()
                name = app.partner_name or app.name or 'Unnamed Candidate'

                candidate = False
                if email:
                    candidate = self.env['candidate.profile'].sudo().search([('email', '=ilike', email)], limit=1)
                if not candidate and phone:
                    candidate = self.env['candidate.profile'].sudo().search([('phone', '=', phone)], limit=1)
                if not candidate and app.partner_id:
                    candidate = self.env['candidate.profile'].sudo().search([('partner_id', '=', app.partner_id.id)], limit=1)

                if not candidate:
                    partner = app.partner_id
                    if not partner and email:
                        partner = self.env['res.partner'].sudo().search([('email', '=ilike', email)], limit=1)
                    if not partner:
                        partner = self.env['res.partner'].sudo().create({
                            'name': name,
                            'email': email or False,
                            'phone': phone or False,
                        })
                    candidate = self.env['candidate.profile'].sudo().create({
                        'name': name,
                        'email': email or f'candidate_{app.id}@placeholder.com',
                        'phone': phone or '',
                        'partner_id': partner.id,
                    })

                app.sudo().write({'candidate_profile_id': candidate.id})
                candidate.sync_from_application(app)

            # Auto-populate and compute all demographics, work status, and notebook tabs from CV profile
            app._sync_from_candidate_profile()

        return res

    @api.onchange('candidate_profile_id')
    def _onchange_candidate_profile_id(self):
        if self.candidate_profile_id:
            self._sync_from_candidate_profile()

    def _sync_from_candidate_profile(self):
        """Auto-computes and populates candidate demographics, employment details,
        and all notebook tabs (Education, Experience, Competencies, Vacancies) from ATS Profile (Electronic CV)."""
        for app in self:
            cand = app.candidate_profile_id
            if not cand:
                if app.email_from:
                    cand = self.env['candidate.profile'].sudo().search([
                        ('email', '=ilike', app.email_from.strip())
                    ], limit=1)
                if not cand and app.partner_phone:
                    cand = self.env['candidate.profile'].sudo().search([
                        ('phone', '=', app.partner_phone.strip())
                    ], limit=1)
                if cand:
                    app.sudo().write({'candidate_profile_id': cand.id})

            if not cand:
                continue

            vals = {}
            # 1. Demographics
            dob = cand.dob or cand.birth_date
            if dob and not app.date_of_birth:
                vals['date_of_birth'] = dob
            if cand.gender and not app.gender:
                vals['gender'] = cand.gender
            if (cand.place_of_birth or cand.city) and not app.place_of_birth:
                vals['place_of_birth'] = cand.place_of_birth or cand.city
            if cand.linkedin_url and hasattr(app, 'linkedin_profile') and not app.linkedin_profile:
                vals['linkedin_profile'] = cand.linkedin_url

            # 2. Employment & Availability
            if cand.worked_in_bunna_earlier:
                vals['worked_in_bunna_earlier'] = (cand.worked_in_bunna_earlier == 'yes')
            if cand.current_company and not app.current_company:
                vals['current_company'] = cand.current_company
            if (cand.city or cand.address) and not app.current_working_location:
                vals['current_working_location'] = cand.city or cand.address
            if cand.working_status and (not app.working_status or app.working_status == 'unemployed'):
                vals['working_status'] = 'employed' if cand.working_status == 'employed' else ('unemployed' if cand.working_status == 'unemployed' else 'self_employed')
            if cand.join_immediately:
                vals['willing_to_join_immediately'] = True

            if vals:
                app.sudo().write(vals)

            # 3. Tab: Education Qualifications (qualification_id)
            if cand.education_ids:
                existing_qual_map = {
                    (q.qualification.qualification or '').strip().lower(): q
                    for q in app.qualification_id if q.qualification
                }
                new_qual_lines = []
                for edu in cand.education_ids:
                    name = (edu.qualification_name or edu.field_of_study or 'Degree').strip()
                    cgpa_val = f"{edu.cgpa:.2f}" if edu.cgpa else "3.50"

                    rec_qual = self.env['recruitment.qualification'].sudo().search([
                        ('qualification', '=ilike', name)
                    ], limit=1)
                    if not rec_qual and name:
                        rec_qual = self.env['recruitment.qualification'].sudo().create({'qualification': name})

                    if rec_qual:
                        key = rec_qual.qualification.strip().lower()
                        if key in existing_qual_map:
                            existing_q = existing_qual_map[key]
                            if (not existing_q.response or existing_q.response in ('0.0', '0', '0.00')):
                                existing_q.sudo().write({'response': cgpa_val})
                        else:
                            # Check if vacancy job has requirement
                            req_val = '0.00'
                            if app.job_id:
                                job_q = app.job_id.qualification_id.filtered(lambda jq: jq.qualification.id == rec_qual.id)
                                if job_q:
                                    req_val = str(job_q[0].requirement or '0.00')
                            new_qual_lines.append((0, 0, {
                                'qualification': rec_qual.id,
                                'requirement': req_val,
                                'response': cgpa_val,
                            }))
                if new_qual_lines:
                    app.sudo().write({'qualification_id': new_qual_lines})

            # 4. Tab: Experience (experiance_id)
            if cand.experience_ids:
                existing_exp_map = {
                    (e.experience.experience or '').strip().lower(): e
                    for e in app.experiance_id if e.experience
                }
                new_exp_lines = []
                for exp in cand.experience_ids:
                    pos = (exp.position or 'Professional Experience').strip()
                    dur_val = f"{exp.duration_years:.1f}" if exp.duration_years else "1.0"

                    rec_exp = self.env['recruitment.experience'].sudo().search([
                        ('experience', '=ilike', pos)
                    ], limit=1)
                    if not rec_exp and pos:
                        rec_exp = self.env['recruitment.experience'].sudo().create({'experience': pos})

                    if rec_exp:
                        key = rec_exp.experience.strip().lower()
                        if key in existing_exp_map:
                            existing_e = existing_exp_map[key]
                            if (not existing_e.response or existing_e.response in ('0.0', '0', '0.00')):
                                existing_e.sudo().write({'response': dur_val})
                        else:
                            req_val = '0.00'
                            if app.job_id:
                                job_e = app.job_id.experiance_id.filtered(lambda je: je.experience.id == rec_exp.id)
                                if job_e:
                                    req_val = str(job_e[0].requirement or '0.00')
                            new_exp_lines.append((0, 0, {
                                'experience': rec_exp.id,
                                'requirement': req_val,
                                'response': dur_val,
                            }))
                if new_exp_lines:
                    app.sudo().write({'experiance_id': new_exp_lines})

            # 5. Tab: Competencies (competencies_id)
            skills_certs = []
            for sk in cand.skill_ids:
                if sk.skill_name:
                    skills_certs.append((sk.skill_name, sk.proficiency or 'Proficient'))
            for crt in cand.certification_ids:
                if crt.name:
                    skills_certs.append((crt.name, 'Certified'))

            if skills_certs:
                existing_comp_ids = set()
                existing_comp_names = {}
                for c in app.competencies_id:
                    if c.competencies:
                        existing_comp_ids.add(c.competencies.id)
                        name_str = (getattr(c.competencies, 'name', False) or getattr(c.competencies, 'competencies', False) or '').strip().lower()
                        if name_str:
                            existing_comp_names[name_str] = c

                new_comp_lines = []
                if 'competency.competency' in self.env:
                    for name, resp in skills_certs:
                        c_name = (name or '').strip().lower()
                        if c_name in existing_comp_names:
                            existing_c = existing_comp_names[c_name]
                            if not existing_c.response:
                                existing_c.sudo().write({'response': resp})
                        else:
                            comp_rec = self.env['competency.competency'].sudo().search([('name', '=ilike', name)], limit=1)
                            if comp_rec and comp_rec.id not in existing_comp_ids:
                                existing_comp_ids.add(comp_rec.id)
                                existing_comp_names[c_name] = True
                                new_comp_lines.append((0, 0, {
                                    'competencies': comp_rec.id,
                                    'requirement': 'Required',
                                    'response': resp,
                                }))
                elif 'recruitment.competency' in self.env:
                    comp_fields = self.env['recruitment.competency']._fields
                    for name, resp in skills_certs:
                        rec_comp = False
                        if 'competencies' in comp_fields:
                            rec_comp = self.env['recruitment.competency'].sudo().search([('competencies', '=ilike', name)], limit=1)
                            if not rec_comp and name:
                                rec_comp = self.env['recruitment.competency'].sudo().create({'competencies': name})
                        elif 'name' in comp_fields:
                            rec_comp = self.env['recruitment.competency'].sudo().search([('name', '=ilike', name)], limit=1)
                            if not rec_comp and name:
                                rec_comp = self.env['recruitment.competency'].sudo().create({'name': name})

                        if rec_comp:
                            c_name = (getattr(rec_comp, 'competencies', False) or getattr(rec_comp, 'name', '') or '').strip().lower()
                            if c_name in existing_comp_names:
                                existing_c = existing_comp_names[c_name]
                                if not existing_c.response:
                                    existing_c.sudo().write({'response': resp})
                            elif rec_comp.id not in existing_comp_ids:
                                existing_comp_ids.add(rec_comp.id)
                                existing_comp_names[c_name] = True
                                new_comp_lines.append((0, 0, {
                                    'competencies': rec_comp.id,
                                    'requirement': 'Required',
                                    'response': resp,
                                }))
                if new_comp_lines:
                    app.sudo().write({'competencies_id': new_comp_lines})

            # 6. Tab: Vacancies (hr_new_department_ids)
            if app.app_reference and not app.hr_new_department_ids and 'hr_new_department_info_job' in self.env:
                vac = app.app_reference
                ou_name = vac.operating_unit_id.name if vac.operating_unit_id else (vac.job_location or 'Main Branch')
                
                comodel = self.env['hr_new_department_info_job']._fields['work_unit'].comodel_name if 'work_unit' in self.env['hr_new_department_info_job']._fields else False
                unit_id = False
                if comodel and comodel in self.env:
                    c_model = self.env[comodel].sudo()
                    rec_field = c_model._rec_name if hasattr(c_model, '_rec_name') and c_model._rec_name in c_model._fields else False
                    if not rec_field:
                        if 'workunit_name' in c_model._fields:
                            rec_field = 'workunit_name'
                        elif 'name' in c_model._fields:
                            rec_field = 'name'

                    unit_match = False
                    if rec_field:
                        unit_match = c_model.search([(rec_field, '=ilike', ou_name)], limit=1)
                    unit_id = unit_match.id if unit_match else False

                vac_lines = []
                if hasattr(vac, 'department_ids') and vac.department_ids:
                    for d in vac.department_ids:
                        d_unit_val = False
                        if hasattr(d, 'work_unit') and d.work_unit:
                            if hasattr(d.work_unit, 'id'):
                                d_unit_val = d.work_unit.id
                            elif isinstance(d.work_unit, int):
                                d_unit_val = d.work_unit
                        
                        resp_val = 0
                        raw_resp = getattr(d, 'response', 0)
                        if isinstance(raw_resp, int):
                            resp_val = raw_resp
                        elif isinstance(raw_resp, str) and raw_resp.isdigit():
                            resp_val = int(raw_resp)

                        vac_lines.append((0, 0, {
                            'work_unit': d_unit_val or unit_id,
                            'number_of_vacancies': int(getattr(d, 'number_of_vacancies', 1) or 1),
                            'response': resp_val,
                        }))
                if not vac_lines:
                    vac_lines.append((0, 0, {
                        'work_unit': unit_id,
                        'number_of_vacancies': int(getattr(vac, 'number_of_vacancies', 1) or 1),
                        'response': 1,
                    }))
                if vac_lines:
                    app.sudo().write({'hr_new_department_ids': vac_lines})

    def write(self, vals):
        res = super().write(vals)
        if 'candidate_profile_id' in vals or 'job_id' in vals:
            self._sync_from_candidate_profile()
        if 'employee_id' in vals and vals.get('employee_id'):
            for app in self:
                if app.employee_id:
                    app._populate_employee_from_applicant_and_profile(app.employee_id)
        return res
