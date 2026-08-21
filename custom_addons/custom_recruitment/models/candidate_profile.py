# -*- coding: utf-8 -*-
"""
candidate_profile.py
====================
External Vacancy Application Tracking System (ATS) - Master Candidate Profile / Electronic CV.

Provides master candidate profile management, electronic CV data structure,
and automatic profile-to-application synchronization engine for external vacancies.
"""

import logging
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
    application_count = fields.Integer(
        string='Applications Count',
        compute='_compute_application_count',
    )

    @api.depends('experience_ids.duration_years', 'education_ids.qualification_name', 'education_ids.cgpa')
    def _compute_profile_summaries(self):
        for rec in self:
            rec.total_experience_years = sum(rec.experience_ids.mapped('duration_years'))
            highest_edu = rec.education_ids.sorted('end_date', reverse=True)
            rec.highest_education = highest_edu[0].qualification_name if highest_edu else 'None'
            rec.latest_cgpa = highest_edu[0].cgpa if highest_edu else 0.0

    @api.depends('application_ids')
    def _compute_application_count(self):
        for rec in self:
            rec.application_count = len(rec.application_ids)

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

        # 1. Sync Education Qualifications -> hr_qualification_info_job
        for edu in self.education_ids:
            rec_qual = self.env['recruitment.qualification'].search([('qualification', '=ilike', edu.qualification_name)], limit=1)
            if not rec_qual and edu.qualification_name:
                rec_qual = self.env['recruitment.qualification'].create({'qualification': edu.qualification_name})
            
            if rec_qual:
                existing_q = applicant.qualification_id.filtered(lambda q: q.qualification.id == rec_qual.id)
                if not existing_q:
                    self.env['hr_qualification_info_job'].create({
                        'applicant_id': applicant.id,
                        'qualification': rec_qual.id,
                        'requirement': 0.0,
                        'response': float(edu.cgpa or 0.0),
                    })

        # 2. Sync Experience -> hr_experience_info_job
        for exp in self.experience_ids:
            rec_exp = self.env['recruitment.experience'].search([('experience', '=ilike', exp.position)], limit=1)
            if not rec_exp and exp.position:
                rec_exp = self.env['recruitment.experience'].create({'experience': exp.position})
            
            if rec_exp:
                existing_e = applicant.experiance_id.filtered(lambda e: e.experience.id == rec_exp.id)
                if not existing_e:
                    self.env['hr_experience_info_job'].create({
                        'applicant_id': applicant.id,
                        'experience': rec_exp.id,
                        'requirement': 0.0,
                        'response': float(exp.duration_years or 0.0),
                    })

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

    def _auto_init(self):
        super()._auto_init()

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

        _logger.info("Master Candidate Profiles auto-synced %s unlinked applicant records.", count)
        return True



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
        self.env.cr.execute("""
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = %s AND column_name = 'graduation_year'
        """, (self._table,))
        res = self.env.cr.fetchone()
        if res and res[0] in ('integer', 'bigint', 'numeric', 'double precision'):
            self.env.cr.execute(f"""
                ALTER TABLE {self._table} 
                ALTER COLUMN graduation_year TYPE date 
                USING (
                    CASE 
                        WHEN graduation_year IS NULL OR graduation_year::text = '0' OR length(graduation_year::text) < 4 
                        THEN NULL 
                        ELSE (left(graduation_year::text, 4) || '-01-01')::date 
                    END
                );
            """)
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
