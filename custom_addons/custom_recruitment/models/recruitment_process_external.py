from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
import datetime


class RecruitmentProcessExternal(models.Model):
    _name = "employee.recruitment.external"
    _inherit = "mail.thread"
    _description = "external Recruitment process"
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
    vacancy_reference = fields.Char(string="Vacancy Reference")
    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    job_location = fields.Char(string="Work Unit")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id = fields.Integer(string="Work Unit Id")
    job_grade = fields.Char(string="Grade")
    job_category = fields.Char(string="Category")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    highest_cgpa = fields.Float(string="Highest CGPA")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    last_date_to_apply = fields.Date(string="Last Date To Apply")
    responsible = fields.Many2one('hr.employee', string="Responsible", required=True)
    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    status = fields.Selection([('notify', 'Notified')], string="Status")
    shortlisting_done = fields.Boolean(
        string="Shortlisting Done", default=False, copy=False, readonly=True,
        tracking=True,
        help="Set automatically when the Shortlist Candidates wizard completes. "
             "Hides the Shortlist button to prevent duplicate shortlisting."
    )
    eligible_emp_external = fields.One2many("external.recruitment.eligible.employees", "external_recruitment_id",
                                            string="External Recruitment")

    def notify(self):
        p_id = self.id
        self.env.cr.execute('SELECT external_applicant(%s)', (p_id,))
        self.status = 'notify'
        return self.status

    def action_open_shortlist_wizard(self):
        self.ensure_one()
        # Enforce: only HR Officer (group_hr_user) or HR Administrator (group_hr_manager) may shortlist
        hr_officer_group = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
        hr_admin_group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
        user_groups = self.env.user.group_ids  # Odoo 19: group_ids (not groups_id)
        if not ((hr_officer_group and hr_officer_group in user_groups) or
                (hr_admin_group and hr_admin_group in user_groups)):
            raise ValidationError(_(
                "Access Denied: Only HR Officers and HR Administrators can perform candidate shortlisting."
            ))
        # Open the choice wizard — HR can pick Default or Specific criteria
        return {
            'name': _('Shortlist Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'external.shortlist.choice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_recruitment_id': self.id,
            }
        }


class EligibleEmployeesexternal(models.Model):
    _name = "external.recruitment.eligible.employees"
    _description = "Eligible External Applicants"

    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    # ── Personal Information ────────────────────────────────────────────────────
    applicant_email = fields.Char(string="E-Mail")
    applicant_phone = fields.Char(string="Phone")
    date_of_birth = fields.Date(
        string="Date of Birth",
        help="Entering date of birth auto-calculates age, and vice versa."
    )
    age = fields.Integer(
        string="Age",
        compute='_compute_age',
        inverse='_inverse_age',
        store=True,
        help="Age in years. Entering age auto-fills approximate date of birth."
    )
    applicant_age = fields.Char(string="Age (Display)")
    gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female')],
        string="Gender"
    )

    @api.depends('date_of_birth')
    def _compute_age(self):
        """Compute age from date_of_birth."""
        today = datetime.date.today()
        for rec in self:
            if rec.date_of_birth:
                dob = rec.date_of_birth
                rec.age = (today.year - dob.year
                           - ((today.month, today.day) < (dob.month, dob.day)))
            else:
                rec.age = 0

    def _inverse_age(self):
        """When age is set manually, compute approximate date of birth."""
        today = datetime.date.today()
        for rec in self:
            if rec.age and rec.age > 0:
                # Approximate: use January 1 of the birth year
                birth_year = today.year - rec.age
                rec.date_of_birth = datetime.date(birth_year, today.month, today.day)

    # ── Employment Status ───────────────────────────────────────────────────────
    working_status = fields.Selection(
        [('employed', 'Currently Employed'),
         ('unemployed', 'Unemployed'),
         ('self_employed', 'Self-Employed')],
        string="Working Status"
    )
    current_company = fields.Char(string="Current Employer")
    join_immediately = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')],
        string="Willing to Join Immediately"
    )
    date_of_availability = fields.Date(string="Available From")
    preferred_location = fields.Char(string="Preferred Location")
    ex_bunna = fields.Boolean(string="Ex-Bunna Employee")

    # ── Academic Qualifications (highest – kept for quick filter/search) ─────
    educational_qualification = fields.Selection(
        [('diploma', 'Diploma'),
         ('bachelor', "Bachelor's Degree"),
         ('master', "Master's Degree"),
         ('phd', 'PhD / Doctorate')],
        string="Highest Qualification",
        compute='_compute_highest_qualification', store=True
    )
    field_of_study = fields.Char(string="Field of Study",
                                 compute='_compute_highest_qualification', store=True)
    institution_name = fields.Char(string="Institution / University",
                                   compute='_compute_highest_qualification', store=True)
    graduation_date = fields.Date(string="Graduation Date",
                                  compute='_compute_highest_qualification', store=True)
    graduation_year = fields.Integer(string="Graduation Year",
                                     compute='_compute_highest_qualification', store=True)
    highest_cgpa = fields.Float(string="CGPA / GPA",
                                compute='_compute_highest_qualification', store=True)

    # ── Education list (multiple qualifications) ────────────────────────────
    education_ids = fields.One2many(
        "external.applicant.education", "applicant_record_id",
        string="Education Qualifications"
    )

    @api.depends('education_ids', 'education_ids.level', 'education_ids.cgpa')
    def _compute_highest_qualification(self):
        """Auto-populate the legacy single-qual fields from the highest degree row."""
        level_order = {'phd': 4, 'master': 3, 'bachelor': 2, 'diploma': 1}
        for rec in self:
            best = None
            best_rank = 0
            for edu in rec.education_ids:
                rank = level_order.get(edu.level, 0)
                if rank > best_rank:
                    best_rank = rank
                    best = edu
            if best:
                rec.educational_qualification = best.level
                rec.field_of_study = best.field_of_study
                rec.institution_name = best.institution_name
                rec.graduation_date = best.graduation_date
                rec.graduation_year = best.graduation_year
                rec.highest_cgpa = best.cgpa
            else:
                rec.educational_qualification = False
                rec.field_of_study = False
                rec.institution_name = False
                rec.graduation_date = False
                rec.graduation_year = 0
                rec.highest_cgpa = 0.0

    # ── Work Experience ─────────────────────────────────────────────────────────
    relevant_experience = fields.Float(string="Relevant Experience (Years)")
    banking_experience = fields.Float(string="Banking Experience (Years)")
    non_banking_experience = fields.Float(string="Non-Banking Experience (Years)")
    total_experience = fields.Float(string="Total Experience (Years)")
    supervisory_experience = fields.Float(string="Supervisory Experience (Years)")

    # ── Work History ────────────────────────────────────────────────────────────
    work_history_ids = fields.One2many(
        "external.applicant.work.history", "applicant_record_id",
        string="Work History"
    )

    # ── Certifications ──────────────────────────────────────────────────────────
    certification_ids = fields.One2many(
        "external.applicant.certification", "applicant_record_id",
        string="Certifications & Licenses"
    )

    # ── Skills ──────────────────────────────────────────────────────────────────
    skill_ids = fields.One2many(
        "external.applicant.skill", "applicant_record_id",
        string="Skills"
    )

    # ── Languages ───────────────────────────────────────────────────────────────
    language_ids = fields.One2many(
        "external.applicant.language", "applicant_record_id",
        string="Languages"
    )

    # ── Application Status ──────────────────────────────────────────────────────
    application_status = fields.Selection([
        ('submitted', 'Application Submitted'),
        ('under_review', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('selected', 'Selected'),
        ('roster', 'Retained in Talent Roster'),
        ('rejected', 'Rejected / Unsuccessful'),
    ], string="Application Status", default='submitted', copy=False)

    # ── Scoring / Selection ─────────────────────────────────────────────────────
    select_flag = fields.Boolean(string="Selected")
    recommendation = fields.Text(string="Notes / Recommendation")

    # ── Salary Information ──────────────────────────────────────────────────────
    current_salary = fields.Float(
        string="Current Salary",
        digits=(16, 2),
        help="Candidate's current monthly gross salary at their present employer."
    )
    expected_salary = fields.Float(
        string="Expected Salary",
        digits=(16, 2),
        help="Candidate's expected monthly gross salary for this position."
    )
    applicant_id = fields.Integer(string="Applicant ID")
    job_position = fields.Integer(string="Job Position ID")
    external_recruitment_id = fields.Many2one("employee.recruitment.external", string="External Recruitment")

    cv_attachment_id = fields.Many2one('ir.attachment', string='CV Attachment', compute='_compute_cv_attachment_id',
                                       store=False)

    def _compute_cv_attachment_id(self):
        for rec in self:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'external.recruitment.eligible.employees'),
                ('res_id', '=', rec.id)
            ], limit=1, order='id desc')
            if not att and rec.applicant_name:
                att = self.env['ir.attachment'].search([
                    ('res_model', '=', 'hr.applicant'),
                    ('res_id', '=', rec.applicant_name.id)
                ], limit=1, order='id desc')
            rec.cv_attachment_id = att.id if att else False

    def action_download_cv(self):
        self.ensure_one()
        att = self.cv_attachment_id
        if not att:
            raise ValidationError(_("No CV attachment found for candidate %s.") % (
                self.applicant_name.name if self.applicant_name else self.id))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{att.id}?download=true',
            'target': 'new',
        }

    def action_transfer_to_talent_roster(self):
        """Transfer selected external eligible candidates directly to Talent Roster."""
        Roster = self.env['talent.roster']
        count = 0
        for rec in self:
            existing = Roster.search([
                '|', ('eligible_candidate_id', '=', rec.id),
                ('email', '=ilike', rec.applicant_email)
            ], limit=1)
            if existing:
                continue

            name = (
                rec.applicant_name.partner_name or
                rec.applicant_name.display_name if rec.applicant_name else
                rec.applicant_email or _("External Candidate")
            )
            vacancy_id = rec.external_recruitment_id.vacancy_id.id if rec.external_recruitment_id and rec.external_recruitment_id.vacancy_id else False

            qual_val = rec.educational_qualification
            if qual_val and hasattr(rec._fields['educational_qualification'], 'selection'):
                qual_dict = dict(rec._fields['educational_qualification'].selection or [])
                qual_val = qual_dict.get(qual_val, qual_val)

            Roster.create({
                'name': name,
                'applicant_id': rec.applicant_name.id if rec.applicant_name else False,
                'eligible_candidate_id': rec.id,
                'source_vacancy_id': vacancy_id,
                'application_type': 'External',
                'email': rec.applicant_email,
                'phone': rec.applicant_phone,
                'gender': rec.gender,
                'educational_qualification': qual_val,
                'field_of_study': rec.field_of_study,
                'highest_cgpa': rec.highest_cgpa,
                'total_experience': rec.total_experience,
                'banking_experience': rec.banking_experience,
                'status': 'active',
                'notes': _("Transferred from External Recruitment Candidates."),
            })
            count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Successful'),
                'message': _('%d candidate(s) transferred to Talent Roster.') % count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }


class ExternalApplicantWorkHistory(models.Model):
    _name = "external.applicant.work.history"
    _description = "External Applicant Work History"
    _order = "start_date desc"

    applicant_record_id = fields.Many2one(
        "external.recruitment.eligible.employees",
        string="Applicant",
        ondelete="cascade",
        required=True,
    )
    company_name = fields.Char(string="Company / Employer Name", required=True)
    job_title = fields.Char(string="Job Title / Position")
    employment_type = fields.Selection(
        [('full_time', 'Full Time'),
         ('part_time', 'Part Time'),
         ('contract', 'Contract'),
         ('internship', 'Internship')],
        string="Employment Type"
    )
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    is_current = fields.Boolean(string="Currently Working Here")
    responsibilities = fields.Text(string="Key Responsibilities")


# ── Education (multi-row) ────────────────────────────────────────────────────

class ExternalApplicantEducation(models.Model):
    _name = "external.applicant.education"
    _description = "External Applicant Education Qualification"
    _order = "level desc, graduation_year desc"

    applicant_record_id = fields.Many2one(
        "external.recruitment.eligible.employees",
        string="Applicant", ondelete="cascade", required=True,
    )
    level = fields.Selection(
        [('diploma', 'Diploma'),
         ('bachelor', "Bachelor's Degree"),
         ('master', "Master's Degree"),
         ('phd', 'PhD / Doctorate')],
        string="Qualification Level", required=True,
    )
    field_of_study = fields.Char(string="Field of Study / Major")
    institution_name = fields.Char(string="University / Institution")
    graduation_date = fields.Date(string="Graduation Date")
    graduation_year = fields.Integer(string="Graduation Year", compute='_compute_graduation_year', store=True)
    cgpa = fields.Float(string="CGPA / GPA", digits=(4, 2))

    @api.depends('graduation_date')
    def _compute_graduation_year(self):
        for rec in self:
            rec.graduation_year = rec.graduation_date.year if rec.graduation_date else 0

    def _compute_display_name(self):
        level_labels = dict(self._fields['level'].selection)
        for rec in self:
            level_label = level_labels.get(rec.level, '')
            parts = [p for p in [level_label, rec.field_of_study] if p]
            rec.display_name = ' - '.join(parts) if parts else _('Education #%s') % rec.id


# ── Certification ────────────────────────────────────────────────────────────

class ExternalApplicantCertification(models.Model):
    _name = "external.applicant.certification"
    _description = "External Applicant Certification / License"
    _order = "issue_date desc"

    applicant_record_id = fields.Many2one(
        "external.recruitment.eligible.employees",
        string="Applicant", ondelete="cascade", required=True,
    )
    name = fields.Char(string="Certification Name", required=True)
    issuing_institution = fields.Char(string="Issuing Institution / Body")
    issue_date = fields.Date(string="Issue Date")
    expiry_date = fields.Date(string="Expiry Date")
    has_expiry = fields.Boolean(string="Has Expiry Date", default=True)
    is_expired = fields.Boolean(
        string="Expired", compute='_compute_is_expired', store=True
    )

    @api.depends('expiry_date', 'has_expiry')
    def _compute_is_expired(self):
        today = datetime.date.today()
        for rec in self:
            if rec.has_expiry and rec.expiry_date:
                rec.is_expired = rec.expiry_date < today
            else:
                rec.is_expired = False

    def _compute_attachment(self):
        for rec in self:
            att = self.env['ir.attachment'].search([
                ('res_model', '=', 'external.applicant.certification'),
                ('res_id', '=', rec.id),
            ], limit=1, order='id desc')
            rec.attachment_id = att.id if att else False
            rec.attachment_filename = att.name if att else False

    attachment_id = fields.Many2one(
        'ir.attachment', string='Certificate File',
        compute='_compute_attachment', store=False
    )

    attachment_filename = fields.Char(
        string='Certificate File',
        compute='_compute_attachment', store=False,
        help='Name of the uploaded certificate file (read-only display).'
    )

    certificate_url = fields.Char(
        string='Certificate URL',
        help='Link to the certificate hosted online (e.g. LinkedIn, Coursera, Google, etc.).'
    )

    def action_download_cert(self):
        self.ensure_one()
        att = self.attachment_id
        if not att and not self.certificate_url:
            from odoo.exceptions import ValidationError
            raise ValidationError(
                _("No certificate file or URL found for '%s'.") % self.name
            )
        if att:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{att.id}?download=true',
                'target': 'new',
            }
        # Fall back to URL
        return {
            'type': 'ir.actions.act_url',
            'url': self.certificate_url,
            'target': 'new',
        }

    def action_open_certificate_url(self):
        self.ensure_one()
        if not self.certificate_url:
            from odoo.exceptions import ValidationError
            raise ValidationError(_("No URL configured for certificate '%s'.") % self.name)
        return {
            'type': 'ir.actions.act_url',
            'url': self.certificate_url,
            'target': 'new',
        }


# ── Skill ────────────────────────────────────────────────────────────────────

class ExternalApplicantSkill(models.Model):
    _name = "external.applicant.skill"
    _description = "External Applicant Skill"
    _rec_name = "skill_name"

    applicant_record_id = fields.Many2one(
        "external.recruitment.eligible.employees",
        string="Applicant", ondelete="cascade", required=True,
    )
    skill_category = fields.Selection(
        [('business', 'Business Related'),
         ('technology', 'Technology Related')],
        string="Category", required=True,
    )
    skill_name = fields.Char(string="Skill", required=True)
    proficiency = fields.Selection(
        [('beginner', 'Beginner'),
         ('intermediate', 'Intermediate'),
         ('advanced', 'Advanced'),
         ('expert', 'Expert')],
        string="Proficiency Level", default='intermediate',
    )


# ── Language ─────────────────────────────────────────────────────────────────

class ExternalApplicantLanguage(models.Model):
    _name = "external.applicant.language"
    _description = "External Applicant Language Proficiency"

    applicant_record_id = fields.Many2one(
        "external.recruitment.eligible.employees",
        string="Applicant", ondelete="cascade", required=True,
    )
    language = fields.Selection(
        [('english', 'English'),
         ('amharic', 'Amharic'),
         ('afaan_oromo', 'Afaan Oromo'),
         ('tigrinya', 'Tigrinya'),
         ('somali', 'Somali (Afaan Soomaali)'),
         ('sidama', 'Sidama'),
         ('wolaytta', 'Wolaytta'),
         ('hadiya', 'Hadiya'),
         ('guragigna', 'Guragigna'),
         ('afar', 'Afar'),
         ('bench', 'Bench'),
         ('dawro', 'Dawro'),
         ('awngi', 'Awngi'),
         ('gamo', 'Gamo'),
         ('konso', 'Konso'),
         ('arabic', 'Arabic'),
         ('french', 'French'),
         ('other', 'Other')],
        string="Language", required=True,
    )
    proficiency = fields.Selection(
        [('basic', 'Basic'),
         ('conversational', 'Conversational'),
         ('professional', 'Professional / Working'),
         ('fluent', 'Fluent'),
         ('native', 'Native / Mother Tongue')],
        string="Proficiency", required=True, default='professional',
    )
    is_primary = fields.Boolean(string="Primary Language")


class ExternalSelectedCandidates(models.Model):
    _name = "external.selected"
    _inherit = "mail.thread"
    _description = "External candidates Selection"
    _rec_name = "job_position"
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
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
    status = fields.Selection([('notify', 'Notified')], string="Status")
    eligible_sel_emp_external = fields.One2many("external.recruitment.selected.employees", "external_emp_selected_id",
                                                string="External Selected Candidates for Recruitment")

    def notify(self):
        p_id = self.job_position.id
        self.env.cr.execute('SELECT internal_applicant(%s)', (p_id,))
        self.status = 'notify'
        return self.status


class ExternalEligibleEmployees(models.Model):
    _name = "external.recruitment.selected.employees"
    _description = "Eligible Employees"

    emp_name = fields.Many2one("hr.employee", string="Name")
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    emp_grade = fields.Char(string="Grade")
    emp_position = fields.Char(string="Position")
    grade_id = fields.Integer(string="Grade Id")
    position_id = fields.Integer(string="Position Id")
    workunit_id = fields.Integer(string="Workunit Id")
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
    select_flag = fields.Boolean(string="Select")
    external_emp_selected_id = fields.Many2one("external.selected",
                                               string="External Selected Candidates for Recruitment")
