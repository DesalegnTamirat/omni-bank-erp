# -*- coding: utf-8 -*-
"""
candidate_profile.py
====================
External Vacancy Application Tracking System (ATS) - Master Candidate Profile / Electronic CV.

Provides master candidate profile management, electronic CV data structure,
and automatic profile-to-application synchronization engine for external vacancies.
"""

import logging
import re
_logger = logging.getLogger(__name__)

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date


class CandidateProfile(models.Model):
    _name = 'candidate.profile'
    _description = 'Master Candidate Profile / Electronic CV'
    _rec_name = 'name'
    _order = 'create_date desc'

    # ---------------------------------------------------------------
    # Authentication & User Link
    # ---------------------------------------------------------------
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact Partner',
        ondelete='cascade',
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='User Account',
        ondelete='set null',
        index=True,
    )
    cv_file = fields.Binary(
        string='Master CV Document',
        attachment=True,
    )
    cv_filename = fields.Char(
        string='CV Filename',
    )
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
    cover_letter_file = fields.Binary(string='Cover Letter Document', attachment=True)
    cover_letter_filename = fields.Char(string='Cover Letter Filename')
    linkedin_url = fields.Char(string='LinkedIn Profile URL')
    portfolio_url = fields.Char(string='Portfolio Website URL')
    github_url = fields.Char(string='GitHub / GitLab URL')
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    activation_token = fields.Char(
        string='Activation Token',
        index=True,
    )
    reset_token = fields.Char(
        string='Reset Token',
        index=True,
    )

    # ---------------------------------------------------------------
    # Personal & Contact Information
    # ---------------------------------------------------------------
    name = fields.Char(
        string='Full Name',
        required=True,
    )
    email = fields.Char(
        string='Email Address',
        required=True,
    )
    phone = fields.Char(
        string='Mobile Phone Number',
        required=True,
    )
    national_id = fields.Char(
        string='National ID',
    )
    secondary_id_type = fields.Selection([
        ('passport', 'Passport'),
        ('kebele_id', 'Kebele ID'),
        ('driver_id', 'Driver ID'),
    ], string='Personal Identification ID Type')
    secondary_id_number = fields.Char(
        string='Personal Identification ID',
    )

    # ── User Requested Personal Info Fields ──────────────────────────────────
    dob = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    place_of_birth = fields.Char(string='Place of Birth')
    father_name = fields.Char(string='Father Name')
    grand_father_name = fields.Char(string='Grand Father Name')
    mother_name = fields.Char(string='Mother Name')
    blood_group = fields.Char(string='Blood Group')
    house_number = fields.Char(string='House Number')
    sub_city = fields.Char(string='Sub City')
    region = fields.Char(string='Region')
    woreda = fields.Char(string='Woreda')
    kebele = fields.Char(string='Kebele')
    alternative_mobile = fields.Char(string='Alternate Mobile')

    # ── User Requested Bunna Bank Experience Fields ─────────────────────────
    worked_in_bunna_earlier = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Previously Worked in Bunna Bank?', default='no')
    last_position_held = fields.Char(string='Last Position Held')
    last_department = fields.Char(string='Last Department')
    reporting_manager = fields.Char(string='Reporting Manager')
    length_of_service = fields.Float(string='Length of Service (Years)')
    termination_reason = fields.Text(string='Reason for Leaving / Termination Reason')

    # ── User Requested Experience Computation Fields ──────────────────────
    banking_experience = fields.Float(string='Banking Experience (Years)', compute='_compute_experience_totals', store=True)
    non_banking_experience = fields.Float(string='Non-Banking Experience (Years)', compute='_compute_experience_totals', store=True)
    supervisory_experience = fields.Float(string='Supervisory Experience (Years)')
    total_experience = fields.Float(string='Total Experience (Years)', compute='_compute_experience_totals', store=True)

    # ── User Requested Application-Time Fields ────────────────────────────
    working_status = fields.Selection([
        ('employed', 'Active'),
        ('unemployed', 'Unemployed'),
        ('notice_period', 'Serving Notice Period'),
    ], string='Working Status', default='employed')
    current_company = fields.Char(string='Current Employer / Company')
    join_immediately = fields.Boolean(string='Willing to Join Immediately?', default=False)
    current_salary = fields.Float(string='Current Monthly Gross Salary (ETB)')

    @api.depends('dob', 'birth_date')
    def _compute_age(self):
        today = date.today()
        for rec in self:
            d = rec.dob or rec.birth_date
            if d:
                rec.age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
            else:
                rec.age = 0

    @api.depends('experience_ids.duration_years', 'experience_ids.sector_type', 'experience_ids.experience_type')
    def _compute_experience_totals(self):
        for rec in self:
            b_exp = 0.0
            nb_exp = 0.0
            for exp in rec.experience_ids:
                if exp.sector_type == 'banking' or exp.experience_type == 'banking':
                    b_exp += exp.duration_years
                else:
                    nb_exp += exp.duration_years
            rec.banking_experience = round(b_exp, 2)
            rec.non_banking_experience = round(nb_exp, 2)
            rec.total_experience = round(b_exp + nb_exp, 2)
            rec.total_experience_years = round(b_exp + nb_exp, 2)

    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender')
    birth_date = fields.Date(
        string='Date of Birth',
    )
    city = fields.Char(
        string='City / Town',
    )
    address = fields.Text(
        string='Current Address',
    )
    country_id = fields.Many2one(
        'res.country',
        string='Country',
    )
    state_id = fields.Many2one(
        'res.country.state',
        string='State / Region',
        domain="[('country_id', '=', country_id)]",
    )

    @api.constrains('name', 'email', 'phone')
    def _check_required_candidate_fields(self):
        for rec in self:
            missing = []
            if not rec.name or not rec.name.strip():
                missing.append(_("Full Name"))
            if not rec.email or not rec.email.strip():
                missing.append(_("Email Address"))
            if not rec.phone or not rec.phone.strip():
                missing.append(_("Mobile Phone Number"))
            if missing:
                raise ValidationError(_("Missing required information for Candidate Profile:\n• %s\n\nPlease fill all required fields.") % "\n• ".join(missing))


    # ---------------------------------------------------------------
    # Electronic CV Sub-tables (One2many)
    # ---------------------------------------------------------------
    education_ids = fields.One2many(
        'candidate.education',
        'candidate_id',
        string='Educational Qualifications',
    )
    experience_ids = fields.One2many(
        'candidate.experience',
        'candidate_id',
        string='Professional Experience',
    )
    certification_ids = fields.One2many(
        'candidate.certification',
        'candidate_id',
        string='Professional Certifications',
    )
    skill_ids = fields.One2many(
        'candidate.skill',
        'candidate_id',
        string='Skills & Competencies',
    )
    language_ids = fields.One2many(
        'candidate.language',
        'candidate_id',
        string='Languages',
    )
    reference_ids = fields.One2many(
        'candidate.reference',
        'candidate_id',
        string='References',
    )
    document_ids = fields.One2many(
        'candidate.document',
        'candidate_id',
        string='Supporting Documents',
    )
    application_ids = fields.One2many(
        'hr.applicant',
        'candidate_profile_id',
        string='Job Applications',
    )

    # ---------------------------------------------------------------
    # Computed Profile Summaries
    # ---------------------------------------------------------------
    banking_experience = fields.Float(
        string='Banking Experience (Years)',
        compute='_compute_profile_summaries',
        store=True,
    )
    non_banking_experience = fields.Float(
        string='Non-Banking Experience (Years)',
        compute='_compute_profile_summaries',
        store=True,
    )
    total_experience_years = fields.Float(
        string='Total Experience (Years)',
        compute='_compute_profile_summaries',
        store=True,
    )
    highest_education = fields.Char(
        string='Highest Education Obtained',
        compute='_compute_profile_summaries',
        store=True,
    )
    latest_cgpa = fields.Float(
        string='Latest CGPA',
        compute='_compute_profile_summaries',
        store=True,
    )
    profile_completeness = fields.Integer(
        string='Profile Completeness (%)',
        compute='_compute_profile_completeness',
        store=True,
    )
    application_count = fields.Integer(
        string='Applications Count',
        compute='_compute_application_count',
    )

    @api.depends('name', 'phone', 'gender', 'education_ids', 'cv_file')
    def _compute_profile_completeness(self):
        for rec in self:
            score = 0
            names = (rec.name or '').strip().split(' ')
            first_name = names[0] if len(names) > 0 else ''
            middle_name = names[1] if len(names) > 1 else ''
            if rec.name and first_name and middle_name and rec.phone and rec.gender:
                score += 34
            if rec.education_ids:
                score += 33
            if rec.cv_file:
                score += 33
            rec.profile_completeness = min(100, score)

    @api.depends(
        'experience_ids.duration_years',
        'experience_ids.sector_type',
        'experience_ids.experience_type',
        'education_ids.qualification_name',
        'education_ids.cgpa'
    )
    def _compute_profile_summaries(self):
        for rec in self:
            banking_exp = 0.0
            non_banking_exp = 0.0
            for exp in rec.experience_ids:
                is_bank = (getattr(exp, 'sector_type', '') == 'banking') or (getattr(exp, 'experience_type', '') == 'banking')
                if is_bank:
                    banking_exp += exp.duration_years
                else:
                    non_banking_exp += exp.duration_years
            rec.banking_experience = round(banking_exp, 2)
            rec.non_banking_experience = round(non_banking_exp, 2)
            rec.total_experience_years = round(banking_exp + non_banking_exp, 2)
            highest_edu = rec.education_ids.sorted('end_date', reverse=True)
            rec.highest_education = highest_edu[0].qualification_name if highest_edu else False
            rec.latest_cgpa = highest_edu[0].cgpa if highest_edu else 0.0

    @api.depends('application_ids')
    def _compute_application_count(self):
        for rec in self:
            rec.application_count = len(rec.application_ids)

    @api.depends('cv_file', 'cv_filename')
    def _compute_cv_preview_html(self):
        import html
        for rec in self:
            if rec.cv_file:
                fn = rec.cv_filename or 'CV_Document.pdf'
                url = f"/web/content?model=candidate.profile&id={rec.id}&field=cv_file&filename={html.escape(fn)}"
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
                    <p style="color: #6c757d; font-size: 13px; max-width: 450px; margin: 0 auto 15px auto;">The candidate profile was entered electronically or without an uploaded PDF attachment. You can review their full structured resume under the <strong>Electronic CV Summary</strong> tab.</p>
                </div>
                """

    @api.depends('education_ids', 'experience_ids', 'skill_ids', 'language_ids', 'name', 'email', 'phone', 'city', 'region')
    def _compute_profile_summary_html(self):
        import html
        for rec in self:
            edu_rows = ""
            for edu in rec.education_ids:
                edu_rows += f"""
                <div style="margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f0;">
                    <strong style="color: #2c3e50; font-size: 14px;">{html.escape(edu.qualification_name or '')}</strong>
                    <span style="color: #7f8c8d; font-size: 12px; float: right;">{edu.start_date or ''} - {edu.end_date or 'Present'}</span>
                    <div style="color: #34495e; font-size: 13px;">{html.escape(edu.institution or '')} {f'— {html.escape(edu.field_of_study)}' if edu.field_of_study else ''}</div>
                    {f'<div style="color: #8e44ad; font-size: 12px; font-weight: bold; margin-top:2px;">CGPA: {edu.cgpa}</div>' if edu.cgpa else ''}
                </div>
                """
            if not edu_rows:
                edu_rows = "<p style='color:#95a5a6; font-style:italic;'>No education history recorded.</p>"

            exp_rows = ""
            for exp in rec.experience_ids:
                exp_rows += f"""
                <div style="margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f0;">
                    <strong style="color: #2c3e50; font-size: 14px;">{html.escape(exp.position or '')}</strong>
                    <span style="color: #7f8c8d; font-size: 12px; float: right;">{exp.start_date or ''} - {exp.end_date or ('Present' if exp.is_current else '')} ({exp.duration_years} yrs)</span>
                    <div style="color: #34495e; font-size: 13px; font-weight: 500;">{html.escape(exp.organization or '')}</div>
                    {f'<span class="badge bg-info text-white" style="font-size:10px; margin-top:3px;">{html.escape(exp.experience_type or "General")}</span>' if exp.experience_type else ''}
                </div>
                """
            if not exp_rows:
                exp_rows = "<p style='color:#95a5a6; font-style:italic;'>No work experience history recorded.</p>"

            skills_badges = "".join([f"<span class='badge' style='background:#4a1515; color:#fff; font-size:12px; padding:6px 12px; margin:3px 4px; border-radius:12px;'>{html.escape(s.name or '')} ({html.escape(s.level or '')})</span>" for s in rec.skill_ids])
            if not skills_badges:
                skills_badges = "<span style='color:#95a5a6; font-style:italic;'>None</span>"

            lang_badges = "".join([f"<span class='badge' style='background:#b38b59; color:#fff; font-size:12px; padding:6px 12px; margin:3px 4px; border-radius:12px;'>{html.escape(l.name or '')} ({html.escape(l.proficiency or '')})</span>" for l in rec.language_ids])
            if not lang_badges:
                lang_badges = "<span style='color:#95a5a6; font-style:italic;'>None</span>"

            rec.profile_summary_html = f"""
            <div style="background:#ffffff; border:1px solid #e0e0e0; border-radius:12px; padding:30px; box-shadow:0 2px 10px rgba(0,0,0,0.05); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                <div style="border-bottom: 2px solid #4a1515; padding-bottom: 18px; margin-bottom: 20px; display:flex; justify-content:space-between; align-items:flex-start;">
                    <div>
                        <h2 style="color: #4a1515; margin:0 0 6px 0; font-weight:700;">{html.escape(rec.name or '')}</h2>
                        <div style="color: #555; font-size: 13px;">
                            <span><i class="fa fa-envelope" style="color:#b38b59;"></i> {html.escape(rec.email or '')}</span> &nbsp;|&nbsp; 
                            <span><i class="fa fa-phone" style="color:#b38b59;"></i> {html.escape(rec.phone or '')}</span> &nbsp;|&nbsp; 
                            <span><i class="fa fa-map-marker" style="color:#b38b59;"></i> {html.escape(rec.city or '')}, {html.escape(rec.region or '')}</span>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <span class="badge" style="background:#4a1515; color:#fff; font-size:12px; padding:6px 14px; border-radius:20px;">Total Exp: {rec.total_experience} Yrs</span>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 20px;">
                    <div>
                        <h4 style="color:#4a1515; border-bottom:1px solid #ddd; padding-bottom:6px; font-weight:600;"><i class="fa fa-graduation-cap"></i> Education &amp; Qualifications</h4>
                        {edu_rows}
                    </div>
                    <div>
                        <h4 style="color:#4a1515; border-bottom:1px solid #ddd; padding-bottom:6px; font-weight:600;"><i class="fa fa-briefcase"></i> Work Experience</h4>
                        {exp_rows}
                    </div>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 15px; padding-top: 15px; border-top: 1px solid #eee;">
                    <div>
                        <h5 style="color:#4a1515; font-weight:600;"><i class="fa fa-cogs"></i> Skills &amp; Competencies</h5>
                        <div style="margin-top:8px;">{skills_badges}</div>
                    </div>
                    <div>
                        <h5 style="color:#4a1515; font-weight:600;"><i class="fa fa-language"></i> Languages</h5>
                        <div style="margin-top:8px;">{lang_badges}</div>
                    </div>
                </div>
            </div>
            """

    def action_preview_cv(self):
        self.ensure_one()
        if not self.cv_file:
            raise UserError(_("No CV document file uploaded for candidate %s.") % self.name)
        fn = self.cv_filename or 'CV_Document.pdf'
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content?model=candidate.profile&id={self.id}&field=cv_file&filename={fn}",
            'target': 'new',
        }

    # ---------------------------------------------------------------
    # Soft Delete
    # ---------------------------------------------------------------
    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True

    # ---------------------------------------------------------------
    # Synchronization Engine: Profile -> Application Snapshot
    # ---------------------------------------------------------------
    def sync_to_application(self, applicant):
        """Automatically synchronizes & snapshots candidate's master profile onto hr.applicant."""
        self.ensure_one()
        applicant.write({
            'candidate_profile_id': self.id,
            'partner_name': self.name,
            'email_from': self.email,
            'partner_phone': self.phone,
        })
        applicant._sync_from_candidate_profile()

    def sync_from_application(self, applicant):
        """Populates master profile fields, education, and experience from hr.applicant if missing."""
        self.ensure_one()
        vals = {}
        if not self.email and applicant.email_from:
            vals['email'] = applicant.email_from.strip()
        if not self.phone and applicant.partner_phone:
            vals['phone'] = applicant.partner_phone.strip()
        if not self.gender and hasattr(applicant, 'gender') and applicant.gender:
            vals['gender'] = applicant.gender
        if not self.birth_date and hasattr(applicant, 'date_of_birth') and applicant.date_of_birth:
            vals['birth_date'] = applicant.date_of_birth
            vals['dob'] = applicant.date_of_birth
        if vals:
            self.write(vals)

        # Sync qualifications from applicant.qualification_id to candidate.education
        if hasattr(applicant, 'qualification_id'):
            for q_line in applicant.qualification_id:
                q_name = q_line.qualification.qualification if q_line.qualification else ''
                if q_name and not self.education_ids.filtered(lambda e: (e.qualification_name or '').lower() == q_name.lower()):
                    self.env['candidate.education'].create({
                        'candidate_id': self.id,
                        'qualification_name': q_name,
                        'field_of_study': q_name,
                        'institution': 'Unspecified',
                        'cgpa': float(q_line.response or 0.0) if hasattr(q_line, 'response') and str(q_line.response).replace('.','',1).isdigit() else 0.0,
                    })

        # Sync experience from applicant.experiance_id to candidate.experience
        if hasattr(applicant, 'experiance_id'):
            for e_line in applicant.experiance_id:
                e_name = e_line.experience.experience if e_line.experience else ''
                if e_name and not self.experience_ids.filtered(lambda ex: (ex.position or '').lower() == e_name.lower()):
                    dur = float(e_line.response or 0.0) if hasattr(e_line, 'response') and str(e_line.response).replace('.','',1).isdigit() else 0.0
                    self.env['candidate.experience'].create({
                        'candidate_id': self.id,
                        'position': e_name,
                        'organization': 'Unspecified',
                        'start_date': fields.Date.today(),
                    })

    # def _auto_init(self):
    #     super()._auto_init()
    #     try:
    #         self.env['candidate.profile'].sudo().action_sync_all_unlinked_applicants()
    #     except Exception as e:
    #         _logger.warning("Auto sync candidate profiles on init/startup failed: %s", str(e))

    def action_sync_all_unlinked_applicants(self, *args, **kwargs):
        """Retroactively finds or creates Master Candidate Profiles for all unlinked hr.applicant records."""
        unlinked_applicants = self.env['hr.applicant'].sudo().search([('candidate_profile_id', '=', False)])
        count = 0
        for app in unlinked_applicants:
            email = (app.email_from or '').strip().lower()
            name = app.partner_name or app.name or 'Unnamed Candidate'
            phone = (app.partner_phone or '').strip()

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
            count += 1

        # Also populate and compute all demographics, work status, and notebook tabs from CV profile for all applicants
        all_apps = self.env['hr.applicant'].sudo().search([])
        for app in all_apps:
            try:
                app._sync_from_candidate_profile()
                if app.employee_id:
                    app._populate_employee_from_applicant_and_profile(app.employee_id)
            except Exception as e:
                _logger.warning("Error syncing applicant %s from profile: %s", app.id, str(e))

        _logger.info("Master Candidate Profiles auto-synced %s unlinked applicant records.", count)
        return True

    @api.constrains('phone')
    def _check_phone_number(self):
        for record in self:
            if record.phone:
                cleaned = re.sub(r'[\s\-\(\)]', '', str(record.phone).strip())
                if not re.match(r'^(\+251|00251|251|0)(9|7)\d{8}$', cleaned):
                    raise ValidationError(_(
                        "Invalid Ethiopian phone number '%s'. "
                        "Please enter a valid Ethiopian mobile phone number starting with 09, 07, or +251 (e.g. 0911223344, 0711223344, or +251911223344)."
                    ) % record.phone)



# -----------------------------------------------------------------------
# Candidate Education
# -----------------------------------------------------------------------
class CandidateEducation(models.Model):
    _name = 'candidate.education'
    _description = 'Candidate Educational Qualification'
    _order = 'end_date desc, id desc'

    education_level = fields.Selection([
        ('highschool', 'High School'),
        ('diploma', 'Diploma'),
        ('ba', 'Bachelor of Arts (BA)'),
        ('bsc', 'Bachelor of Science (BSc)'),
        ('ma_msc', 'Master Degree (MA/MSc)'),
        ('phd', 'Doctorate (PhD)'),
        ('other', 'Other'),
    ], string='Education Level', default='bsc')
    other_field_of_study = fields.Char(string='Custom Field of Study')
    other_institution = fields.Char(string='Custom Institution')
    program_type = fields.Selection([
        ('regular', 'Regular'),
        ('extension', 'Extension / Evening'),
        ('distance', 'Distance / Online'),
        ('weekend', 'Weekend'),
        ('summer', 'Summer'),
    ], string='Program Type', default='regular')
    has_cost_sharing = fields.Boolean(string='Have Cost Sharing?', default=False)
    cost_sharing_file = fields.Binary(string='Cost Sharing Agreement Document', attachment=True)
    cost_sharing_filename = fields.Char(string='Cost Sharing Filename')
    education_doc_file = fields.Binary(string='Education Certificate Document', attachment=True)
    education_doc_filename = fields.Char(string='Education Doc Filename')
    graduation_year = fields.Date(string='Graduation Year')

    def _auto_init(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    SELECT data_type FROM information_schema.columns 
                    WHERE table_name = %s AND column_name = 'graduation_year'
                """, (self._table,))
                res = self.env.cr.fetchone()
                if res and res[0].lower() != 'date':
                    self.env.cr.execute(f"""
                        ALTER TABLE {self._table} 
                        ALTER COLUMN graduation_year TYPE date 
                        USING (
                            CASE 
                                WHEN graduation_year IS NULL THEN NULL 
                                WHEN graduation_year::text ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' THEN substring(graduation_year::text from 1 for 10)::date 
                                WHEN graduation_year::text ~ '^\\d{{4}}' THEN (substring(graduation_year::text from 1 for 4) || '-01-01')::date 
                                ELSE NULL 
                            END
                        );
                    """)
        except Exception as e:
            _logger.warning("Safe migration on %s.graduation_year: %s", self._table, e)
        super()._auto_init()

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    qualification_name = fields.Char(
        string='Qualification / Degree',
        required=True,
        help='e.g. Bachelor\'s Degree, Master\'s Degree, Diploma, PhD',
    )
    field_of_study = fields.Char(
        string='Field of Study / Major',
        required=True,
        help='e.g. Computer Science, Accounting, Finance, Management',
    )
    institution = fields.Char(
        string='School / College / University',
        required=True,
    )
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='Graduation Date')
    cgpa = fields.Float(
        string='CGPA / Percentage',
        digits=(5, 2),
    )
    active = fields.Boolean(default=True)

    @api.constrains('field_of_study', 'institution')
    def _check_required_education_fields(self):
        for rec in self:
            missing = []
            if not rec.field_of_study or not str(rec.field_of_study).strip():
                missing.append(_("Field of Study / Major"))
            if not rec.institution or not str(rec.institution).strip():
                missing.append(_("School / College / University"))
            if missing:
                raise ValidationError(_("Missing required information for Education Entry:\n• %s\n\nPlease specify all required education details.") % "\n• ".join(missing))

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Experience
# -----------------------------------------------------------------------
class CandidateExperience(models.Model):
    sector_type = fields.Selection([('banking', 'Banking Sector'), ('non_banking', 'Non Banking Sector')], string='Company Sector', default='banking', required=True)
    _name = 'candidate.experience'
    _description = 'Candidate Professional Experience'
    _order = 'start_date desc, id desc'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    position = fields.Char(string='Job Title / Position', required=True)
    organization = fields.Char(string='Company / Organization', required=True)
    employment_type = fields.Selection([
        ('full_time', 'Full Time'),
        ('permanent', 'Permanent'),
        ('contract', 'Contract'),
        ('internship', 'Internship'),
        ('part_time', 'Part Time'),
        ('freelance', 'Freelance / Temporary'),
    ], string='Employment Type', default='full_time', required=True)

    experience_type = fields.Selection([
        ('banking', 'Banking Sector'),
        ('non_banking_accountable', 'Non Banking - Accountable'),
        ('government', 'Government'),
        ('ngo', 'NGO / International'),
        ('other', 'Other'),
    ], string='Experience Type', default='banking')

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date')
    is_current = fields.Boolean(string='Currently Working Here', default=False)
    exp_file = fields.Binary(string='Experience Attachment', attachment=True)
    exp_filename = fields.Char(string='Experience Filename')

    duration_years = fields.Float(
        string='Duration (Years)',
        compute='_compute_duration_years',
        store=True,
    )
    responsibilities = fields.Text(string='Key Responsibilities')
    active = fields.Boolean(default=True)

    @api.depends('start_date', 'end_date', 'is_current')
    def _compute_duration_years(self):
        for rec in self:
            if rec.start_date:
                stop = fields.Date.today() if rec.is_current or not rec.end_date else rec.end_date
                days = (stop - rec.start_date).days
                rec.duration_years = max(0.0, round(days / 365.25, 2))
            else:
                rec.duration_years = 0.0

    @api.constrains('position', 'organization', 'start_date')
    def _check_required_experience_fields(self):
        for rec in self:
            missing = []
            if not rec.position or not str(rec.position).strip():
                missing.append(_("Job Title / Position"))
            if not rec.organization or not str(rec.organization).strip():
                missing.append(_("Company / Organization"))
            if not rec.start_date:
                missing.append(_("Start Date"))
            if missing:
                raise ValidationError(_("Missing required information for Experience Entry:\n• %s\n\nPlease specify all required experience details.") % "\n• ".join(missing))

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Certification
# -----------------------------------------------------------------------
class CandidateCertification(models.Model):
    _name = 'candidate.certification'
    _description = 'Candidate Certification'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Certification Title', required=True)
    issuing_organization = fields.Char(string='Issuing Organization')
    issue_date = fields.Date(string='Issue Date')
    has_expiry = fields.Boolean(string='Has Expiry Date', default=False)
    expiry_date = fields.Date(string='Expiration Date')
    cert_file = fields.Binary(string='Certificate Attachment', attachment=True)
    cert_filename = fields.Char(string='Certificate Filename')
    cert_url = fields.Char(string='Verification Link / URL')
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Skill
# -----------------------------------------------------------------------
class CandidateSkill(models.Model):
    _name = 'candidate.skill'
    _description = 'Candidate Skill & Competency'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Skill Name', required=True)
    level = fields.Selection([
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ], string='Proficiency Level', default='intermediate')
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Language
# -----------------------------------------------------------------------
class CandidateLanguage(models.Model):
    _name = 'candidate.language'
    _description = 'Candidate Language Proficiency'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Language', required=True)
    proficiency = fields.Selection([
        ('basic', 'Basic'),
        ('fluent', 'Fluent'),
        ('native', 'Native / Mother Tongue'),
    ], string='Proficiency', default='fluent')
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Reference
# -----------------------------------------------------------------------
class CandidateReference(models.Model):
    _name = 'candidate.reference'
    _description = 'Candidate Referee'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Referee Name', required=True)
    position = fields.Char(string='Position / Title')
    organization = fields.Char(string='Organization')
    phone = fields.Char(string='Phone Number')
    email = fields.Char(string='Email Address')
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Candidate Document
# -----------------------------------------------------------------------
class CandidateDocument(models.Model):
    _name = 'candidate.document'
    _description = 'Candidate Supporting Document'

    candidate_id = fields.Many2one(
        'candidate.profile',
        string='Candidate',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Document Title', required=True)
    attachment = fields.Binary(string='File Content', attachment=False)
    filename = fields.Char(string='Filename')
    document_url = fields.Char(string='Document Link / URL')
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            rec.write({'active': False})
        return True
