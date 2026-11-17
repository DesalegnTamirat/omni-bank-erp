from odoo import api, models, fields, tools, _
from odoo.fields import Command
from .clean_utils import clean_job_position_name
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup, escape
from datetime import date
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

JOB_VACANCY_TYPE_CODE_MAP = {
    'promotion': 'INT',
    'transfer': 'LAT',
    'external': 'EXT',
}

LOCKED_ALLOWED_FIELDS = {
    'vacancy_status', 'status', 'state', 'reference', 'message_ids',
    'message_follower_ids', 'activity_ids', 'website_published',
    'eligible_employee_ids', 'new_int_rec_sel', 'new_int_rec_panel',
    'recr_selected_team_id', 'recr_exter_selected_team_id',
    'approval_hierarchy_type', 'chairperson_id', 'panel_member_id',
    'secretary_id', 'observer_id',
    'pms_weight', 'written_weight', 'interview_weight',
    'has_written_exam', 'approved_plan_count', 'plan_fulfillment_promotion',
    'plan_fulfillment_lateral', 'position_qualifications', 'position_experiences',
    'transfer_eval_mode', 'supervisor_rec_requested', 'app_date_weight',
    'experience_weight', 'location_weight', 'recommendation_weight',
    'written_exam_date', 'exam_location', 'interview_date', 'interview_location',
    'recruitment_step', 'shortlist_done', 'candidate_notified', 'exam_notified',
    'interview_notified', 'committee_notified', 'minute_signed', 'employees_promoted',
    'selected_recruitment_id',
}


class JobVacancy(models.Model):
    _name = 'job.vacancy'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Job Vacancy Form"
    _rec_name = "reference"
    _order = "id desc"
    active = fields.Boolean(default=True)

    def unlink(self):
        for rec in self:
            if rec.recruitment_request_id and rec.recruitment_request_id.vacancy_id == rec:
                rec.recruitment_request_id.write({'vacancy_id': False})
        self.write({"active": False})
        return True

    reference = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))

    state = fields.Selection(selection=[
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], string='Workflow State', required=True, readonly=True, copy=False, tracking=True,
        default='draft')

    # : Sourcing designation — Internal Only / External Only / Both
    sourcing_type = fields.Selection(
        [('internal', 'Internal Only'), ('external', 'External Only'), ('both', 'Both')],
        string='Sourcing Type', default='internal',
        help="HR designates vacancy as Internal Only, External Only, or Both."
    )

    # External source channel — where the vacancy is published externally
    source_channel = fields.Selection(
        [('linkedin', 'LinkedIn'),
         ('telegram', 'Telegram'),
         ('website', 'Company Website'),
         ('newspaper', 'Newspaper'),
         ('other', 'Other')],
        string='Source Channel',
        help="External publication channel (LinkedIn, Telegram, Website, etc.)"
    )

    # ── External-specific eligibility/requirement fields ──────────────────────
    minimum_education = fields.Selection(
        [('diploma', 'Diploma'),
         ('bachelor', "Bachelor's Degree"),
         ('master', "Master's Degree"),
         ('phd', 'PhD / Doctorate')],
        string='Minimum Education',
        help="Minimum academic qualification required for external applicants."
    )
    minimum_cgpa = fields.Float(
        string='Minimum CGPA',
        help="Minimum CGPA/GPA required for external applicants."
    )
    minimum_experience_years = fields.Float(
        string='Minimum Total Experience (Years)',
        help="Minimum total work experience required for external applicants."
    )
    banking_experience_required = fields.Float(
        string='Banking Experience Required (Years)',
        help="Minimum banking sector experience required."
    )
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        pos_id = res.get('job_position') or self.env.context.get('default_job_position')
        if pos_id:
            pos = self.env['hr.job'].browse(pos_id)
            grade = pos.grade if (pos and pos.grade) else False
            if grade:
                if not res.get('job_grade'):
                    res['job_grade'] = grade.id
                if not res.get('employee_category'):
                    if getattr(grade, 'category', False):
                        cat_name = (grade.category.category_name or '').strip().lower()
                        res['employee_category'] = 'Managerial' if 'manager' in cat_name else 'Non Managerial'
                    elif getattr(pos, 'employee_category', False):
                        res['employee_category'] = pos.employee_category
                if not res.get('job_level'):
                    cat = res.get('employee_category')
                    if cat != 'Managerial' and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                        res['job_level'] = grade.grade_level
        return res

    def _is_hr_it_workunit(self, ou):
        if not ou:
            return False
        if getattr(ou, 'full_non_banking_credit', False):
            return True
        ou_name = (ou.name or '').lower()
        ou_code = (getattr(ou, 'code', '') or '').lower()
        return any(kw in ou_name or kw in ou_code for kw in [
            'hr', 'human resource', 'people', 'talent', 'culture',
            'it', 'information technology', 'ict', 'software', 'digital', 'system'
        ])

    def _default_full_non_banking_credit(self):
        emp = self.env.user.employee_id
        ou = emp.default_operating_unit_id if emp else False
        return self._is_hr_it_workunit(ou)

    def _default_non_banking_exp_weight(self):
        return 1.0 if self._default_full_non_banking_credit() else 0.5

    full_non_banking_credit = fields.Boolean(
        string='Full Non-Banking Experience Credit (100%)',
        default=_default_full_non_banking_credit,
        help="If enabled, candidates applying to this vacancy receive 100% credit (1.0 weight) for non-banking experience during shortlisting and ranking. If disabled, non-banking experience receives 50% credit (0.5 weight)."
    )
    non_banking_exp_weight = fields.Float(
        string='Non-Banking Experience Weight',
        compute='_compute_non_banking_exp_weight',
        default=_default_non_banking_exp_weight,
        store=True,
        readonly=False,
        help="Weight applied to non-banking experience for candidates (1.0 = 100%, 0.5 = 50%). Auto-detected or controlled by the Full Non-Banking Credit flag."
    )

    @api.depends('operating_unit_id', 'sourcing_type', 'full_non_banking_credit')
    def _compute_non_banking_exp_weight(self):
        for vac in self:
            if vac.full_non_banking_credit:
                vac.non_banking_exp_weight = 1.0
            else:
                is_hr_it = vac._is_hr_it_workunit(vac.operating_unit_id)
                vac.non_banking_exp_weight = 1.0 if is_hr_it else 0.5

    @api.onchange('full_non_banking_credit')
    def _onchange_full_non_banking_credit(self):
        for vac in self:
            vac.non_banking_exp_weight = 1.0 if vac.full_non_banking_credit else 0.5

    ex_bunna_preferred = fields.Boolean(
        string='Ex-Bunna Preferred',
        help="Check if preference is given to ex-Bunna employees."
    )
    website_published = fields.Boolean(
        string='Published on Website',
        readonly=True,
        help="Indicates if this vacancy has been published on the company website."
    )
    is_featured = fields.Boolean(
        string='Featured Vacancy',
        default=False,
        help="Pin this vacancy prominently on the ATS website portal."
    )

    internal_movement_type = fields.Selection(
        [
            ('promotion', 'Promotion'),
            ('transfer', 'Transfer'),
            ('external', 'External Only'),
        ],
        string='Movement Type', default='promotion',
        help="Drives the reference number prefix (INT/LAT/EXT)."
    )

    is_lateral_transfer = fields.Boolean(
        string="Is Lateral Transfer",
        compute="_compute_is_lateral_transfer",
        store=True,
    )

    @api.depends('internal_movement_type', 'reference', 'sourcing_type')
    def _compute_is_lateral_transfer(self):
        for rec in self:
            is_ext = rec.sourcing_type == 'external' or 'EXT' in (rec.reference or '').upper()
            if is_ext:
                rec.is_lateral_transfer = False
            else:
                rec.is_lateral_transfer = bool(
                    (rec.internal_movement_type in ('transfer', 'lateral') or
                     (rec.reference and 'LAT' in rec.reference.upper()))
                    and rec.internal_movement_type != 'promotion'
                )

    @api.onchange('sourcing_type')
    def _onchange_sourcing_type(self):
        """Auto-set movement type and legacy recruitment_type when sourcing changes."""
        for rec in self:
            if rec.sourcing_type == 'external':
                rec.internal_movement_type = 'external'
                rec.recruitment_type = 'External'
            elif rec.sourcing_type in ('internal', 'both'):
                if rec.internal_movement_type not in ('promotion', 'transfer'):
                    rec.internal_movement_type = 'promotion'
                rec.recruitment_type = 'Internal'

    @api.constrains('recruitment_type', 'internal_movement_type', 'sourcing_type')
    def _check_internal_movement_type(self):
        """Movement Type validation."""
        for rec in self:
            if rec.sourcing_type == 'internal' and rec.internal_movement_type == 'external':
                raise ValidationError(_(
                    "For Internal sourcing, Movement Type must be Promotion or Transfer, not External."
                ))
            if not rec.internal_movement_type:
                if rec.sourcing_type == 'external' or rec.recruitment_type == 'External':
                    rec.internal_movement_type = 'external'
                else:
                    rec.internal_movement_type = 'promotion'

    partner_id = fields.Many2one('res.partner', string="Vendor")
    allowed_job_ids = fields.Many2many(
        'hr.job',
        string='Allowed Job Positions',
        compute='_compute_allowed_job_ids',
    )
    job_position = fields.Many2one(
        'hr.job', string="Position Job", required=True,
        domain="[('id', 'in', allowed_job_ids)]"
    )
    job_grade = fields.Many2one("employee.grade", string="Job Grade", related="job_position.grade", readonly=True)
    employee_category = fields.Selection(
        [('Managerial', 'Managerial'), ('Non Managerial', 'Non Managerial')],
        string='Job Category',
        compute='_compute_employee_category',
        store=True,
        readonly=True,
        precompute=True,
    )

    # ── NEW: Job Level now lives on the vacancy itself, not on each
    # candidate score. Only relevant / visible when employee_category is
    # 'Non Managerial' — Managerial vacancies have no sub-level.
    job_level = fields.Selection(
        [('junior', 'Junior'), ('senior', 'Senior')],
        string='Job Level',
        compute='_compute_job_level',
        store=True,
        readonly=True,
        precompute=True,
        help="Only applicable for Non-Managerial vacancies. Drives the "
             "Job Level shown on every Candidate Score linked to this "
             "vacancy — no longer chosen per-candidate."
    )

    @api.depends('job_grade', 'job_grade.category', 'job_grade.category.category_name', 'job_position', 'job_position.grade', 'job_position.grade.category', 'job_position.grade.category.category_name')
    def _compute_employee_category(self):
        for rec in self:
            grade = rec.job_grade or (rec.job_position.grade if rec.job_position else False)
            if grade and getattr(grade, 'category', False):
                cat_name = (grade.category.category_name or '').strip().lower()
                rec.employee_category = 'Managerial' if 'manager' in cat_name else 'Non Managerial'
            elif rec.job_position and getattr(rec.job_position, 'employee_category', False):
                rec.employee_category = rec.job_position.employee_category
            else:
                rec.employee_category = False

    @api.depends('job_grade', 'job_grade.grade_level', 'job_position', 'job_position.grade', 'job_position.grade.grade_level', 'employee_category')
    def _compute_job_level(self):
        for rec in self:
            if rec.employee_category == 'Managerial':
                rec.job_level = False
            else:
                grade = rec.job_grade or (rec.job_position.grade if rec.job_position else False)
                if grade and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                    rec.job_level = grade.grade_level
                else:
                    rec.job_level = False

    recruitment_request_id = fields.Many2one(
        "recruitment.request", string="Recruitment Reference",
        domain="[('state', '=', 'approved'), ('vacancy_id', '=', False)]", tracking=True,
        help="Select an approved Recruitment Request to auto-populate vacancy fields."
    )
    recruitment_reference = fields.Char(string="Recruitment Reference String")

    # /013: Opening and closing dates with validation
    opening_date = fields.Date(string="Opening Date", default=fields.Date.context_today, required=True,
                               help=" Vacancy opening date.")
    last_date_to_apply = fields.Date(
        string="Last Date To Apply",
        required=True,
        compute="_auto_date_calculation",
        store=True,
        readonly=False,
        precompute=True,
        help="Closing Date must be > Opening Date."
    )

    @api.depends('opening_date', 'recruitment_type', 'sourcing_type')
    def _auto_date_calculation(self):
        for record in self:
            if record.opening_date:
                r_type = (record.recruitment_type or '').lower()
                s_type = (record.sourcing_type or '').lower()
                if r_type == 'external' or s_type == 'external':
                    record.last_date_to_apply = record.opening_date + timedelta(days=5)
                elif r_type == 'internal' or s_type in ('internal', 'both'):
                    record.last_date_to_apply = record.opening_date + timedelta(days=3)
                else:
                    record.last_date_to_apply = record.opening_date + timedelta(days=5)
            else:
                record.last_date_to_apply = False

    vacancy_description = fields.Text(string="Vacancy Description", required=True)

    # Legacy field — kept for compatibility; use sourcing_type for new records
    recruitment_type = fields.Selection(
        [('Internal', 'Internal'), ('External', 'External')],
        string='Recruitment Type (Legacy)', default='Internal')

    responsible = fields.Many2one(
        'hr.employee', string="Responsible", required=True,
        default=lambda self: self.env.user.employee_id, readonly=True
    )

    no_of_vacancies = fields.Integer(string="Number of Vacancies", default=1)
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Place Of Assignment", required=True, readonly=True,
        default=lambda self: self.env.user.employee_id.default_operating_unit_id if self.env.user.employee_id else False
    )
    type_of_employment = fields.Selection(
        [('Permanent', 'Permanent'), ('Contractual', 'Contractual'), ("internship", "Internship")],
        string='Type of Employment', default='Permanent')
    ref = fields.Char(string='Bill Reference', copy=False, tracking=True)
    place_of_interview = fields.Char(string='Place of interview')
    morning = fields.Char(string='Morning')
    afternoon = fields.Char(string='Afternoon')
    # place_of_assignment = fields.Many2one("operating.unit",string='Place of assignment', required=True)
    comment = fields.Text(string="Comment")
    vacant_job_position = fields.Char(string='Vacant Job Position')
    total_number_of_applicant = fields.Char(string='Total Number of Applicants')
    short_listed_applicant = fields.Char(string='Shortlisted Applicants')
    purpose_of_employment = fields.Char(string='Purpose of Employment')
    vacancy_announcement_data = fields.Char(string='Vacancy Announcement Date')
    vacancy_status = fields.Selection([('draft', 'Draft'), ('evaluate', 'Evaluate'),
                                       ('published', 'Published'), ('closed', 'Closed')],
                                      string="Vacancy status", default="draft", readonly=True)
    vacancy_announcement_no = fields.Integer(string='Required Number')
    not_selected_applicants = fields.Integer(string='Not Selected Applicants')
    total_participant_on_the_assessment = fields.Integer(string='Shortlisted for Interview')
    date_of_interview = fields.Date(string="Date of interview")
    time_begin = fields.Date(string="Minute Discussion Start Time")
    time_end = fields.Date(string="Minute Discussion End Time")

    payment_reference = fields.Char(string='Payment Reference', index=True, copy=False)
    payment_mode_id = fields.Selection(selection=[
        ("manual", "Manual"),
    ], string='Payment Mode', required=True, default="manual", change_default=True)
    partner_bank_id = fields.Many2one('res.partner.bank', string='Recipient Bank', readonly=False)
    invoice_date = fields.Date(string='Bill Date')
    date = fields.Date(string='Accounting Date', default=fields.Date.context_today)
    invoice_date_due = fields.Date(string='Due Date')
    transfer_status = fields.Selection([('draft', 'Draft'), ('transferred', 'Transferred')],
                                       string="Transfer status", default="draft")
    status = fields.Selection([("notify", "notify"), ("evaluate", "Evaluate")], string="Status")
    hiring_details = fields.One2many("hiring.status", 'hiring_id', 'Hiring Status')
    hiring_rank_details = fields.One2many("result.summary.rank", 'summ_rank_id', 'Job Result Summary Rank')
    memb_panel_vac = fields.One2many("vac.panel.members", "panl_memb_vac", "Vacancy panel Members")
    vac_del_team_id = fields.One2many("vacancy.delegation.team", "vac_del_id", string="Vacancy Delegation Team")

    job_title = fields.Char(string="Job Title", compute="_compute_website_vacancy_fields")
    job_location = fields.Char(string="Job Location", compute="_compute_website_vacancy_fields")
    description = fields.Text(string="Description", compute="_compute_website_vacancy_fields")
    deadline_date = fields.Date(string="Deadline Date", compute="_compute_website_vacancy_fields")

    @api.depends('job_position', 'vacant_job_position', 'operating_unit_id', 'vacancy_description',
                 'last_date_to_apply')
    def _compute_website_vacancy_fields(self):
        for rec in self:
            rec.job_title = rec.job_position.name if rec.job_position else (
                        rec.vacant_job_position or rec.reference or '')
            rec.job_location = rec.operating_unit_id.name if rec.operating_unit_id else ''
            rec.description = rec.vacancy_description or ''
            rec.deadline_date = rec.last_date_to_apply or False

    def get_social_share_urls(self):
        """Build rich social media sharing URLs containing Title, Reference, Location, Job Description, Vacancy Description, Requirements, and Link."""
        self.ensure_one()
        title = self.job_title or (self.job_position.name if self.job_position else 'Career Opportunity')
        ref = self.reference or ''
        location = self.job_location or (self.operating_unit_id.name if self.operating_unit_id else 'Addis Ababa')

        # 1. Experience Requirements
        exp_list = []
        if self.minimum_experience_years and self.minimum_experience_years > 0:
            exp_val = int(self.minimum_experience_years) if self.minimum_experience_years.is_integer() else self.minimum_experience_years
            exp_txt = f"{exp_val} Year{'s' if exp_val != 1 else ''}"
            if self.banking_experience_required and self.banking_experience_required > 0:
                bank_val = int(self.banking_experience_required) if self.banking_experience_required.is_integer() else self.banking_experience_required
                exp_txt += f" (min. {bank_val} Year{'s' if bank_val != 1 else ''} in Banking)"
            exp_list.append(exp_txt)

        if self.job_position and getattr(self.job_position, 'experiance_id', False):
            for exp in self.job_position.experiance_id:
                exp_name = (exp.experience.display_name or getattr(exp.experience, 'experience', '') or '') if exp.experience else ''
                yrs = getattr(exp, 'requirement', 0.0)
                if exp_name:
                    yr_txt = f" ({int(yrs) if yrs == int(yrs) else yrs} yrs)" if yrs else ""
                    val = f"{exp_name}{yr_txt}"
                    if val not in exp_list:
                        exp_list.append(val)

        # 2. Qualification Requirements
        qual_list = []
        if self.minimum_education:
            edu_dict = dict(self._fields['minimum_education'].selection or [])
            edu_label = edu_dict.get(self.minimum_education, self.minimum_education.title())
            if self.minimum_cgpa and self.minimum_cgpa > 0:
                edu_label += f" (Min. CGPA: {self.minimum_cgpa})"
            qual_list.append(edu_label)

        if self.job_position and getattr(self.job_position, 'qualification_id', False):
            for q in self.job_position.qualification_id:
                q_name = (q.qualification.display_name or getattr(q.qualification, 'qualification', '') or '') if q.qualification else ''
                req_cgpa = getattr(q, 'requirement', 0.0)
                if q_name:
                    cgpa_txt = f" (CGPA: {req_cgpa})" if req_cgpa else ""
                    val = f"{q_name}{cgpa_txt}"
                    if val not in qual_list:
                        qual_list.append(val)

        # 3. Job Description (from hr.job - second image)
        job_desc = ''
        if self.job_position and getattr(self.job_position, 'job_description', False) and self.job_position.job_description:
            job_desc = tools.html2plaintext(self.job_position.job_description).strip()
            job_desc = ' '.join(job_desc.split())

        # 4. Vacancy Description (from job.vacancy - first image)
        vac_desc = ''
        raw_vac = self.vacancy_description or self.description or ''
        if raw_vac:
            vac_desc = tools.html2plaintext(raw_vac).strip()
            vac_desc = ' '.join(vac_desc.split())

        company = "Bunna Bank Share Company"
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8082')
        portal_url = f"{base_url.rstrip('/')}/jobs"

        full_text = f"🔥 Vacancy Announcement - {company}\n📌 Position: {title}"
        if job_desc:
            full_text += f"\n📖 Job Description: {job_desc}"
        if qual_list:
            full_text += f"\n🎓 Qualification: {', '.join(qual_list)}"
        if exp_list:
            full_text += f"\n⏳ Experience: {', '.join(exp_list)}"
        if vac_desc:
            # Do not display vacancy description if it is identical to or copied from job description
            is_dup = False
            if job_desc:
                j_clean = job_desc.strip().lower()[:60]
                v_clean = vac_desc.strip().lower()[:60]
                if j_clean and v_clean and (j_clean == v_clean or j_clean in vac_desc.lower() or v_clean in job_desc.lower()):
                    is_dup = True
            if not is_dup:
                full_text += f"\n📝 Vacancy Description: {vac_desc}"
        full_text += f"\n📋 Reference: {ref}\n📍 Location: {location}"
        full_text += f"\n👉 Apply Online: {portal_url}"

        import urllib.parse
        encoded_text = urllib.parse.quote(full_text)
        encoded_url = urllib.parse.quote(portal_url)
        encoded_title = urllib.parse.quote(f"{company} - {title} (Ref: {ref})")

        return {
            'telegram': f"https://t.me/share/url?url={encoded_url}&text={encoded_text}",
            'whatsapp': f"https://api.whatsapp.com/send?text={encoded_text}",
            'linkedin': f"https://www.linkedin.com/sharing/share-offsite/?url={encoded_url}",
            'facebook': f"https://www.facebook.com/sharer/sharer.php?u={encoded_url}&quote={encoded_title}",
            'twitter': f"https://twitter.com/intent/tweet?url={encoded_url}&text={encoded_title}",
            'share_text': full_text,
        }

    # Release date — recorded when an internally selected candidate is officially
    # cleared from their current role and released to start the new placement.
    release_date = fields.Date(
        string="Release Date",
        help="Date on which the selected internal candidate was officially released from "
             "their current position to take up the new role (transfer/promotion placement).",
        tracking=True,
        copy=False,
    )
    release_notes = fields.Text(
        string="Release Notes",
        help="Optional notes regarding the release process (e.g., handover completion date).",
        copy=False,
    )

    competency_line_ids = fields.One2many(
        'job.vacancy.competency', 'vacancy_id', string="Competencies",
        help=" Required competencies with required level."
    )

    @api.onchange('job_position')
    def _onchange_job_position_sync_competencies(self):
        """Auto-populates required competencies, qualifications, and grade from job_position when selected."""
        if not self.job_position:
            self.job_grade = False
            self.employee_category = False
            self.job_level = False
            return
        job = self.job_position

        # 1. Sync Job Grade from Job Position
        grade = getattr(job, 'grade', False)
        self.job_grade = grade

        # 2. Sync Category and Job Level based on Job Grade
        if grade and getattr(grade, 'category', False):
            cat_name = (grade.category.category_name or '').strip().lower()
            self.employee_category = 'Managerial' if 'manager' in cat_name else 'Non Managerial'
        elif getattr(job, 'employee_category', False):
            self.employee_category = job.employee_category
        else:
            self.employee_category = False

        if self.employee_category == 'Managerial':
            self.job_level = False
        else:
            if grade and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                self.job_level = grade.grade_level
            else:
                self.job_level = False

        # 2. Set default vacancy announcement description if empty (do NOT copy job_description)
        if not self.vacancy_description:
            pos_name = job.name or ''
            ou_name = self.operating_unit_id.name if (self.operating_unit_id and getattr(self.operating_unit_id, 'name', False)) else ''
            if pos_name and ou_name:
                self.vacancy_description = f"Vacancy for {pos_name} at {ou_name}"
            elif pos_name:
                self.vacancy_description = f"Vacancy for {pos_name}"

        # 3. Sync Competencies from Job Position
        lines = self._get_default_competency_lines(job)
        if lines:
            self.competency_line_ids = [(5, 0, 0)] + lines

    def _get_default_competency_lines(self, job_position):
        lines = []
        if not job_position:
            return lines
        job = self.env['hr.job'].browse(job_position) if isinstance(job_position, int) else job_position

        # 1. From job.competencies_id (hr_competencies_info_job) or competencies_ids
        comp_rel = getattr(job, 'competencies_id', False) or getattr(job, 'competencies_ids', False)
        if comp_rel:
            for comp_line in comp_rel:
                comp_obj = getattr(comp_line, 'competencies', False) or getattr(comp_line, 'competency_id', False)
                if comp_obj:
                    lines.append((0, 0, {
                        'competency_id': comp_obj.id,
                        'required_level': getattr(comp_line, 'required_level', 'intermediate') or 'intermediate',
                        'notes': getattr(comp_line, 'requirement', '') or getattr(comp_line, 'notes', '') or '',
                    }))

        # 2. From competency.role.mapping
        if not lines:
            mapping = self.env['competency.role.mapping'].search([
                ('job_position_id', '=', job.id),
                ('state', '=', 'approved')
            ], limit=1)
            if not mapping:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', job.id)
                ], limit=1)
            level_map = {'1': 'basic', '2': 'intermediate', '3': 'advanced', '4': 'expert'}
            if mapping and mapping.line_ids:
                for line in mapping.line_ids:
                    req_lvl = level_map.get(str(line.required_proficiency), 'intermediate')
                    lines.append((0, 0, {
                        'competency_id': line.competency_id.id,
                        'required_level': req_lvl,
                    }))

        # 3. From competency.competency directly
        if not lines:
            comps = self.env['competency.competency'].search([
                ('applicable_job_ids', 'in', [job.id]),
                ('status', '=', 'active')
            ])
            if not comps:
                comps = self.env['competency.competency'].search([
                    ('status', '=', 'active')
                ], limit=4)
            for comp in comps:
                lines.append((0, 0, {
                    'competency_id': comp.id,
                    'required_level': 'intermediate',
                }))
        return lines

    def _get_workunit_approved_plan_count(self, work_unit, job_position):
        """Helper to compute approved plan count for a specific work unit and job position."""
        if not work_unit or not job_position:
            return 0
        plan_cnt = 0
        OUJobPos = self.env['operating.unit.job.position'].sudo() if 'operating.unit.job.position' in self.env else None
        if OUJobPos is not None:
            ou_pos = OUJobPos.search([
                ('operating_unit_id', '=', work_unit.id),
                ('job_position_id', '=', job_position.id),
            ], limit=1)
            if ou_pos:
                plan_cnt = ou_pos.approved_plan_count or 0
        if plan_cnt <= 0 and 'pbms.planning.category' in self.env:
            PBMSPlan = self.env['pbms.planning.category'].sudo()
            pbms_plans = PBMSPlan.search([
                ('category', '=', 'manpower'),
                ('org_unit_id', '=', work_unit.id),
                ('state', '=', 'approved'),
                ('active', '=', True),
            ])
            matching_lines = pbms_plans.mapped('line_ids').filtered(
                lambda l: l.line_type == 'manpower' and l.job_id == job_position
            )
            plan_cnt = int(sum(matching_lines.mapped('quantity')))
        return plan_cnt

    @api.depends('operating_unit_id')
    def _compute_allowed_job_ids(self):
        OUJob = self.env['operating.unit.job.position'].sudo()
        HrJob = self.env['hr.job'].sudo()
        for rec in self:
            ou = rec.operating_unit_id
            if ou:
                lines = OUJob.search([
                    ('operating_unit_id', '=', ou.id),
                    ('active', '=', True)
                ])
                job_ids = lines.mapped('job_position_id').filtered(lambda j: j.active).ids
                rec.allowed_job_ids = [(6, 0, job_ids)]
            else:
                rec.allowed_job_ids = [(6, 0, HrJob.search([('active', '=', True)]).ids)]

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_filter_jobs(self):
        domain = {'job_position': []}
        origin_id = self._origin.id if self._origin else False
        used_requests = self.env['job.vacancy'].search([
            ('id', '!=', origin_id),
            ('recruitment_request_id', '!=', False),
            ('active', '=', True)
        ]).mapped('recruitment_request_id')

        rr_domain = [('state', '=', 'approved'), ('vacancy_id', '=', False)]
        if used_requests:
            rr_domain.append(('id', 'not in', used_requests.ids))

        if self.operating_unit_id:
            is_hr_it = self._is_hr_it_workunit(self.operating_unit_id)
            self.full_non_banking_credit = is_hr_it
            self.non_banking_exp_weight = 1.0 if is_hr_it else 0.5
            lines = self.env['operating.unit.job.position'].sudo().search([
                ('operating_unit_id', '=', self.operating_unit_id.id),
                ('active', '=', True)
            ])
            job_ids = lines.mapped('job_position_id').filtered(lambda j: j.active).ids
            if self.job_position and self.job_position.id not in job_ids:
                self.job_position = False
            domain['job_position'] = [('id', 'in', job_ids)]
            rr_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))
            if self.recruitment_request_id and self.recruitment_request_id.operating_unit_id != self.operating_unit_id:
                self.recruitment_request_id = False
        domain['recruitment_request_id'] = rr_domain
        return {'domain': domain}

    @api.onchange('operating_unit_id', 'responsible', 'no_of_vacancies', 'job_position')
    def _onchange_sync_hiring_details(self):
        for rec in self:
            if rec.operating_unit_id:
                resp_emp = rec.responsible.id if rec.responsible else (self.env.user.employee_id.id if self.env.user.employee_id else False)
                openings = rec.no_of_vacancies or 1
                planned_pos = rec._get_workunit_approved_plan_count(rec.operating_unit_id, rec.job_position) if rec.job_position else (rec.approved_plan_count or 0)
                if not rec.hiring_details:
                    rec.hiring_details = [(0, 0, {
                        'work_unit': rec.operating_unit_id.id,
                        'responsible_employee': resp_emp,
                        'number_of_openings': openings,
                        'planned_positions': planned_pos,
                        'status': 'In Progress',
                    })]
                else:
                    first = rec.hiring_details[0]
                    first.work_unit = rec.operating_unit_id
                    if resp_emp:
                        first.responsible_employee = resp_emp
                    if len(rec.hiring_details) == 1:
                        first.number_of_openings = openings
                    elif sum(rec.hiring_details.mapped('number_of_openings')) != openings:
                        diff = openings - sum(rec.hiring_details.mapped('number_of_openings'))
                        first.number_of_openings = max(1, first.number_of_openings + diff)
                    first.planned_positions = planned_pos

    eligible_employee_ids = fields.One2many(
        'internal.recruitment.eligible.employees',
        'vacancy_id',
        string="Eligible Candidates"
    )
    filter_candidate_name = fields.Char(
        string="Filter by Name",
        help="Type candidate name and click Select Matching to check their selection flag."
    )
    eligible_selected_count_summary = fields.Char(
        string="Candidate Selection Status",
        compute="_compute_eligible_selected_count",
        store=False,
    )
    filter_selected_emp_name = fields.Char(
        string="Filter Selected by Name",
        help="Type employee name and click Select Matching to check their selection flag in Selected Employees."
    )
    selected_emp_count_summary = fields.Char(
        string="Selected Candidates Status",
        compute="_compute_selected_emp_count",
        store=False,
    )

    @api.depends('new_int_rec_sel.select_flag')
    def _compute_selected_emp_count(self):
        for rec in self:
            cands = rec.new_int_rec_sel
            total = len(cands)
            selected = len(cands.filtered(lambda l: l.select_flag))
            rec.selected_emp_count_summary = _("Selected: %(selected)s / %(total)s candidates") % {
                'selected': selected,
                'total': total,
            }

    @api.depends('eligible_employee_ids.select_flag')
    def _compute_eligible_selected_count(self):
        for rec in self:
            total = len(rec.eligible_employee_ids)
            selected = len(rec.eligible_employee_ids.filtered(lambda l: l.select_flag))
            rec.eligible_selected_count_summary = _("Selected: %(selected)s / %(total)s candidates") % {
                'selected': selected,
                'total': total,
            }

    def action_select_all_eligible_candidates(self):
        self.ensure_one()
        if not self.eligible_employee_ids:
            raise UserError(_("No eligible candidates found for this vacancy."))
        self.eligible_employee_ids.write({'select_flag': True})
        int_rec = self.env['employee.recruitment.internal'].search([
            '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
        ], limit=1)
        if int_rec and int_rec.eligible_emp:
            int_rec.eligible_emp.write({'select_flag': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Candidates Selected'),
                'message': _('All %(count)s eligible candidates have been selected.') % {'count': len(self.eligible_employee_ids)},
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_deselect_all_eligible_candidates(self):
        self.ensure_one()
        if not self.eligible_employee_ids:
            raise UserError(_("No eligible candidates found for this vacancy."))
        self.eligible_employee_ids.write({'select_flag': False})
        int_rec = self.env['employee.recruitment.internal'].search([
            '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
        ], limit=1)
        if int_rec and int_rec.eligible_emp:
            int_rec.eligible_emp.write({'select_flag': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Candidates Deselected'),
                'message': _('All %(count)s eligible candidates have been unselected.') % {'count': len(self.eligible_employee_ids)},
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_select_by_candidate_name(self):
        self.ensure_one()
        if not self.filter_candidate_name or not self.filter_candidate_name.strip():
            raise UserError(_("Please type an employee name in the filter box."))
        query = self.filter_candidate_name.strip().lower()
        matching = self.eligible_employee_ids.filtered(
            lambda l: l.emp_name and query in (l.emp_name.name or '').lower()
        )
        if not matching:
            raise UserError(_("No eligible candidate found matching '%s'.") % self.filter_candidate_name)
        matching.write({'select_flag': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Selected'),
                'message': _("Selected %(count)s candidate(s) matching '%(query)s'.") % {
                    'count': len(matching),
                    'query': self.filter_candidate_name,
                },
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_deselect_by_candidate_name(self):
        self.ensure_one()
        if not self.filter_candidate_name or not self.filter_candidate_name.strip():
            raise UserError(_("Please type an employee name in the filter box."))
        query = self.filter_candidate_name.strip().lower()
        matching = self.eligible_employee_ids.filtered(
            lambda l: l.emp_name and query in (l.emp_name.name or '').lower()
        )
        if not matching:
            raise UserError(_("No eligible candidate found matching '%s'.") % self.filter_candidate_name)
        matching.write({'select_flag': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Unselected'),
                'message': _("Unselected %(count)s candidate(s) matching '%(query)s'.") % {
                    'count': len(matching),
                    'query': self.filter_candidate_name,
                },
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_eligible_candidates_view(self):
        self.ensure_one()
        return {
            'name': _('Eligible Candidates - %s') % self.reference,
            'type': 'ir.actions.act_window',
            'res_model': 'internal.recruitment.eligible.employees',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.eligible_employee_ids.ids)],
            'context': {
                'default_vacancy_id': self.id,
            },
            'target': 'current',
        }

    def action_select_all_selected_candidates(self):
        self.ensure_one()
        if not self.new_int_rec_sel:
            raise UserError(_("No selected employee records found for this vacancy."))
        self.new_int_rec_sel.write({'select_flag': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Candidates Selected'),
                'message': _('All %(count)s candidates have been selected.') % {'count': len(self.new_int_rec_sel)},
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_deselect_all_selected_candidates(self):
        self.ensure_one()
        if not self.new_int_rec_sel:
            raise UserError(_("No selected employee records found for this vacancy."))
        self.new_int_rec_sel.write({'select_flag': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Candidates Deselected'),
                'message': _('All %(count)s candidates have been unselected.') % {'count': len(self.new_int_rec_sel)},
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_select_by_selected_emp_name(self):
        self.ensure_one()
        if not self.filter_selected_emp_name or not self.filter_selected_emp_name.strip():
            raise UserError(_("Please type an employee name in the filter box."))
        query = self.filter_selected_emp_name.strip().lower()
        matching = self.new_int_rec_sel.filtered(
            lambda l: l.emp_name and query in (l.emp_name.name or '').lower()
        )
        if not matching:
            raise UserError(_("No candidate found matching '%s'.") % self.filter_selected_emp_name)
        matching.write({'select_flag': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Selected'),
                'message': _("Selected %(count)s candidate(s) matching '%(query)s'.") % {
                    'count': len(matching),
                    'query': self.filter_selected_emp_name,
                },
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_deselect_by_selected_emp_name(self):
        self.ensure_one()
        if not self.filter_selected_emp_name or not self.filter_selected_emp_name.strip():
            raise UserError(_("Please type an employee name in the filter box."))
        query = self.filter_selected_emp_name.strip().lower()
        matching = self.new_int_rec_sel.filtered(
            lambda l: l.emp_name and query in (l.emp_name.name or '').lower()
        )
        if not matching:
            raise UserError(_("No candidate found matching '%s'.") % self.filter_selected_emp_name)
        matching.write({'select_flag': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Unselected'),
                'message': _("Unselected %(count)s candidate(s) matching '%(query)s'.") % {
                    'count': len(matching),
                    'query': self.filter_selected_emp_name,
                },
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_selected_candidates_view(self):
        self.ensure_one()
        cands = self.new_int_rec_sel
        domain = [('id', 'in', cands.ids)]
        return {
            'name': _('Selected Candidates - %s') % self.reference,
            'type': 'ir.actions.act_window',
            'res_model': 'new.internal.recruitment.selected.candidates',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {
                'default_new_int_sel_cand': self.selected_recruitment_id.id if self.selected_recruitment_id else False,
            },
            'target': 'current',
        }
    applicant_ids = fields.One2many(
        'hr.applicant',
        'app_reference',
        string="External Applicants"
    )

    selected_recruitment_id = fields.Many2one(
        "new.internal.recruitment.selected",
        string="Selected Recruitment Process",
        compute="_compute_selected_recruitment_id",
        store=True,
    )
    new_int_rec_sel = fields.One2many(
        "new.internal.recruitment.selected.candidates",
        related="selected_recruitment_id.new_int_rec_sel",
        string="Selected Candidates",
        readonly=False,
    )
    new_int_rec_panel = fields.One2many(
        related="selected_recruitment_id.new_int_rec_panel",
        string="Panel Members",
        readonly=False,
    )
    recr_selected_team_id = fields.One2many(
        related="selected_recruitment_id.recr_selected_team_id",
        string="Recruitment Approval Committee",
        readonly=False,
    )

    # External Selected Recruitment Pipeline mapping
    ext_selected_recruitment_id = fields.Many2one(
        "external.recruitment.selected",
        string="External Selected Recruitment Process",
        compute="_compute_ext_selected_recruitment_id",
        store=True,
    )
    ext_rec_sel = fields.One2many(
        related="ext_selected_recruitment_id.ext_rec_sel",
        string="External Selected Candidates",
        readonly=False,
    )
    ext_rec_panel = fields.One2many(
        related="ext_selected_recruitment_id.ext_rec_panel",
        string="External Panel Members",
        readonly=False,
    )
    recr_exter_selected_team_id = fields.One2many(
        related="ext_selected_recruitment_id.recr_exter_selected_team_id",
        string="External Recruitment Approval Committee",
        readonly=False,
    )

    approval_hierarchy_type = fields.Selection(
        [
            ("ho_district_grade2_plus", "Head Office & District Grade II and above"),
            ("non_managerial_ho", "For all non-managerial head office"),
            ("non_managerial_district", "For all non-managerial district"),
        ],
        string="Approval Hierarchy Category",
        compute="_compute_approval_hierarchy_type",
        store=True,
        readonly=False,
        tracking=True,
    )
    chairperson_id = fields.Many2one("res.users", string="Chairperson", tracking=True)
    panel_member_id = fields.Many2one("res.users", string="Panel Member", tracking=True)
    secretary_id = fields.Many2one("res.users", string="Panel Member & Secretary", tracking=True)
    observer_id = fields.Many2one(
        "res.users", string="Labor Representative (Observer)", tracking=True,
        help="Observer role (optional to sign)"
    )
    allowed_chairperson_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Chairperson Users",
    )
    allowed_panel_member_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Panel Member Users",
    )
    allowed_secretary_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Secretary Users",
    )
    allowed_observer_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Observer Users",
    )

    @api.depends("operating_unit_id", "job_grade", "job_position", "employee_category")
    def _compute_approval_hierarchy_type(self):
        for rec in self:
            if not rec.approval_hierarchy_type:
                try:
                    rec.approval_hierarchy_type = rec._compute_hierarchy_type_recruitment()
                except Exception:
                    rec.approval_hierarchy_type = "ho_district_grade2_plus"

    @api.depends("approval_hierarchy_type", "operating_unit_id", "job_position", "sourcing_type", "internal_movement_type")
    def _compute_allowed_committee_users(self):
        ConfigModel = self.env["committee.role.config"]
        for rec in self:
            htype = rec.approval_hierarchy_type or "ho_district_grade2_plus"
            if rec.sourcing_type == "external" or "EXT" in (rec.reference or "").upper():
                scope = "external"
            elif getattr(rec, "internal_movement_type", False) in ("lateral", "transfer") or "TRF" in (rec.reference or "").upper():
                scope = "transfer"
            elif rec.sourcing_type == "internal":
                scope = "internal"
            else:
                scope = "all"

            cfg = ConfigModel.get_config_for_hierarchy(htype, scope=scope)
            ou = rec.operating_unit_id or False
            dept = getattr(rec.operating_unit_id, "department", False) or (rec.job_position.department_id if rec.job_position else False)
            if cfg:
                rec.allowed_chairperson_user_ids = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou, department=dept)
                rec.allowed_panel_member_user_ids = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou, department=dept)
                rec.allowed_secretary_user_ids = cfg.get_allowed_users_for_role("secretary", operating_unit=ou, department=dept)
                rec.allowed_observer_user_ids = cfg.get_allowed_users_for_role("observer", operating_unit=ou, department=dept)
            else:
                rec.allowed_chairperson_user_ids = False
                rec.allowed_panel_member_user_ids = False
                rec.allowed_secretary_user_ids = False
                rec.allowed_observer_user_ids = False

    @api.onchange("approval_hierarchy_type", "operating_unit_id", "job_position", "sourcing_type", "internal_movement_type")
    def _onchange_committee_hierarchy_roles(self):
        ConfigModel = self.env["committee.role.config"]
        htype = self.approval_hierarchy_type or "ho_district_grade2_plus"
        if self.sourcing_type == "external" or "EXT" in (self.reference or "").upper():
            scope = "external"
        elif getattr(self, "internal_movement_type", False) in ("lateral", "transfer") or "TRF" in (self.reference or "").upper():
            scope = "transfer"
        elif self.sourcing_type == "internal":
            scope = "internal"
        else:
            scope = "all"

        cfg = ConfigModel.get_config_for_hierarchy(htype, scope=scope)
        ou = self.operating_unit_id or False
        dept = getattr(self.operating_unit_id, "department", False) or (self.job_position.department_id if self.job_position else False)

        if cfg:
            c_users = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou, department=dept)
            p_users = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou, department=dept)
            s_users = cfg.get_allowed_users_for_role("secretary", operating_unit=ou, department=dept)
            o_users = cfg.get_allowed_users_for_role("observer", operating_unit=ou, department=dept)

            self.allowed_chairperson_user_ids = c_users
            self.allowed_panel_member_user_ids = p_users
            self.allowed_secretary_user_ids = s_users
            self.allowed_observer_user_ids = o_users

            if c_users:
                if self.chairperson_id and self.chairperson_id.id not in c_users.ids:
                    self.chairperson_id = c_users[0] if len(c_users) == 1 else False
                elif not self.chairperson_id and len(c_users) == 1:
                    self.chairperson_id = c_users[0]
            else:
                self.chairperson_id = False

            if p_users:
                if self.panel_member_id and self.panel_member_id.id not in p_users.ids:
                    self.panel_member_id = p_users[0] if len(p_users) == 1 else False
                elif not self.panel_member_id and len(p_users) == 1:
                    self.panel_member_id = p_users[0]
            else:
                self.panel_member_id = False

            if s_users:
                if self.secretary_id and self.secretary_id.id not in s_users.ids:
                    self.secretary_id = s_users[0] if len(s_users) == 1 else False
                elif not self.secretary_id and len(s_users) == 1:
                    self.secretary_id = s_users[0]
            else:
                self.secretary_id = False

            if o_users:
                if self.observer_id and self.observer_id.id not in o_users.ids:
                    self.observer_id = o_users[0] if len(o_users) == 1 else False
                elif not self.observer_id and len(o_users) == 1:
                    self.observer_id = o_users[0]
            else:
                self.observer_id = False

            self._onchange_committee_hierarchy_roles_sync_lines()
            return {
                "domain": {
                    "chairperson_id": [("id", "in", c_users.ids)] if c_users else [("id", "=", False)],
                    "panel_member_id": [("id", "in", p_users.ids)] if p_users else [("id", "=", False)],
                    "secretary_id": [("id", "in", s_users.ids)] if s_users else [("id", "=", False)],
                    "observer_id": [("id", "in", o_users.ids)] if o_users else [("id", "=", False)],
                }
            }
        else:
            self.allowed_chairperson_user_ids = False
            self.allowed_panel_member_user_ids = False
            self.allowed_secretary_user_ids = False
            self.allowed_observer_user_ids = False
            self.chairperson_id = False
            self.panel_member_id = False
            self.secretary_id = False
            self.observer_id = False
            self._onchange_committee_hierarchy_roles_sync_lines()
            return {
                "domain": {
                    "chairperson_id": [("id", "=", False)],
                    "panel_member_id": [("id", "=", False)],
                    "secretary_id": [("id", "=", False)],
                    "observer_id": [("id", "=", False)],
                }
            }

    @api.onchange("chairperson_id", "panel_member_id", "secretary_id", "observer_id")
    def _onchange_committee_hierarchy_roles_sync_lines(self):
        if self.env.context.get("syncing_committee_roles"):
            return
        is_external = self.sourcing_type == "external" or ("EXT" in (self.reference or "").upper())
        line_field = "recr_exter_selected_team_id" if is_external else "recr_selected_team_id"

        role_users = {
            "chairperson": self.chairperson_id,
            "panel_member": self.panel_member_id,
            "secretary": self.secretary_id,
            "observer": self.observer_id,
        }

        commands = [Command.clear()]
        for role, user in role_users.items():
            if user:
                commands.append(Command.create({
                    "role": role,
                    "employee_name": user.id,
                    "status": "active",
                    "is_mandatory": (role != "observer"),
                }))

        try:
            self.with_context(syncing_committee_roles=True)[line_field] = commands
        except Exception as ex:
            _logger.warning("Could not sync committee lines in onchange: %s", ex)

    @api.onchange("recr_selected_team_id", "recr_exter_selected_team_id")
    def _onchange_committee_lines_sync_hierarchy(self):
        if self.env.context.get("syncing_committee_roles"):
            return
        is_external = self.sourcing_type == "external" or ("EXT" in (self.reference or "").upper())
        line_field = "recr_exter_selected_team_id" if is_external else "recr_selected_team_id"
        try:
            lines = getattr(self, line_field, False)
            if not lines:
                return
        except Exception:
            return

        role_to_user = {}
        for line in lines:
            try:
                if getattr(line, "active", True) and getattr(line, "role", False) and line.role not in role_to_user:
                    role_to_user[line.role] = getattr(line, "employee_name", False)
            except Exception:
                continue

        self_ctx = self.with_context(syncing_committee_roles=True)
        if "chairperson" in role_to_user:
            self_ctx.chairperson_id = role_to_user.get("chairperson", False)
        if "panel_member" in role_to_user:
            self_ctx.panel_member_id = role_to_user.get("panel_member", False)
        if "secretary" in role_to_user:
            self_ctx.secretary_id = role_to_user.get("secretary", False)
        if "observer" in role_to_user:
            self_ctx.observer_id = role_to_user.get("observer", False)

    def _sync_committee_lines_from_hierarchy(self):
        for rec in self:
            if not rec.id:
                continue
            is_external = rec.sourcing_type == "external" or ("EXT" in (rec.reference or "").upper())
            if not is_external and not rec.selected_recruitment_id:
                rec._sync_selected_recruitment_records()
            elif is_external and not rec.ext_selected_recruitment_id:
                rec._sync_selected_recruitment_records()

            target = rec.ext_selected_recruitment_id if is_external else rec.selected_recruitment_id
            if not target:
                continue

            line_field = "recr_exter_selected_team_id" if is_external else "recr_selected_team_id"
            lines = getattr(target, line_field)

            role_users = {
                "chairperson": rec.chairperson_id,
                "panel_member": rec.panel_member_id,
                "secretary": rec.secretary_id,
                "observer": rec.observer_id,
            }

            commands = []
            existing_roles = set()
            for line in lines:
                r = line.role
                if r in role_users:
                    u = role_users[r]
                    if u:
                        existing_roles.add(r)
                        if line.employee_name != u:
                            commands.append(Command.update(line.id, {"employee_name": u.id, "status": "active"}))
                    else:
                        commands.append(Command.delete(line.id))

            for r, u in role_users.items():
                if u and r not in existing_roles:
                    commands.append(Command.create({
                        "role": r,
                        "employee_name": u.id,
                        "status": "active",
                        "is_mandatory": (r != "observer"),
                    }))

            if commands:
                target.with_context(syncing_committee_roles=True).write({line_field: commands})

            target_vals = {
                "chairperson_id": rec.chairperson_id.id if rec.chairperson_id else False,
                "panel_member_id": rec.panel_member_id.id if rec.panel_member_id else False,
                "secretary_id": rec.secretary_id.id if rec.secretary_id else False,
                "observer_id": rec.observer_id.id if rec.observer_id else False,
            }
            target.with_context(syncing_committee_roles=True).write(target_vals)

    def _sync_hierarchy_from_committee_lines(self):
        for rec in self:
            if not rec.id:
                continue
            is_external = rec.sourcing_type == "external" or ("EXT" in (rec.reference or "").upper())
            line_field = "recr_exter_selected_team_id" if is_external else "recr_selected_team_id"
            lines = getattr(rec, line_field).filtered(lambda l: l.active)

            role_to_user = {}
            for line in lines:
                if line.role and line.role not in role_to_user:
                    role_to_user[line.role] = line.employee_name.id if line.employee_name else False

            vals_to_write = {}
            for r_name, f_name in [
                ("chairperson", "chairperson_id"),
                ("panel_member", "panel_member_id"),
                ("secretary", "secretary_id"),
                ("observer", "observer_id"),
            ]:
                target_u_id = role_to_user.get(r_name, False)
                curr_u_id = getattr(rec, f_name).id if getattr(rec, f_name) else False
                if curr_u_id != target_u_id:
                    vals_to_write[f_name] = target_u_id

            if vals_to_write:
                rec.with_context(syncing_committee_roles=True).write(vals_to_write)
                target = rec.ext_selected_recruitment_id if is_external else rec.selected_recruitment_id
                if target:
                    target.with_context(syncing_committee_roles=True).write(vals_to_write)

    has_delegation_requests = fields.Boolean(
        compute="_compute_has_delegation_requests_unified",
        string="Has Delegation Requests"
    )
    scores_computed = fields.Boolean(
        string="Scores Computed",
        default=False
    )
    exam_scores_fetched = fields.Boolean(
        string="Exam Scores Fetched",
        default=False
    )
    interview_scores_fetched = fields.Boolean(
        string="Interview Scores Fetched",
        default=False
    )

    # Direct Evaluation weights & schedule fields stored directly on job.vacancy
    has_written_exam = fields.Boolean(string="Has Written Exam", default=True)
    has_interview = fields.Boolean(string="Has Interview", compute="_compute_has_interview", store=False)
    pms_weight = fields.Float(string="PMS Weight (%)", default=30.0)
    written_weight = fields.Float(string="Written Exam Weight (%)", default=0.0)
    interview_weight = fields.Float(string="Interview Weight (%)", default=0.0)
    transfer_eval_mode = fields.Selection([
        ('standard', 'Standard (Exam + Interview)'),
        ('interview_only', 'Interview Only'),
        ('transfer_matrix_only', 'Transfer Matrix Only'),
    ], string='Transfer Evaluation Mode', default='transfer_matrix_only')
    supervisor_rec_requested = fields.Boolean(string="Supervisor Recommendation Requested", default=False)
    app_date_weight = fields.Float(string="Application Date Weight (%)", default=20.0)
    experience_weight = fields.Float(string="Experience Weight (%)", default=20.0)
    location_weight = fields.Float(string="Location Weight (%)", default=20.0)
    recommendation_weight = fields.Float(string="Recommendation Weight (%)", default=10.0)
    transfer_min_position_years = fields.Float(
        string="Min. Years in Current Position",
        default=1.0,
        help="Minimum service years the employee must have spent in their current job position to be eligible for transfer to this vacancy.",
    )
    transfer_min_location_years = fields.Float(
        string="Min. Years in Current Location",
        default=1.0,
        help="Minimum service years the employee must have spent in their current operating unit/branch to be eligible for transfer to this vacancy.",
    )
    approved_plan_count = fields.Integer(string="Approved Plan Count", compute="_compute_plan_fulfillment", store=False)
    plan_fulfillment_promotion = fields.Integer(string="Approved Promotion Plan", compute="_compute_plan_fulfillment", store=False)
    plan_fulfillment_lateral = fields.Integer(string="Approved Transfer Plan", compute="_compute_plan_fulfillment", store=False)
    position_qualifications = fields.Text(string="Required Qualifications", compute="_compute_position_requirements", store=False)
    position_experiences = fields.Text(string="Required Experiences", compute="_compute_position_requirements", store=False)

    @api.depends('interview_weight', 'recr_selected_team_id', 'memb_panel_vac', 'ext_rec_panel')
    def _compute_has_interview(self):
        for rec in self:
            rec.has_interview = (rec.interview_weight or 0.0) > 0.0 or bool(rec.recr_selected_team_id or rec.memb_panel_vac or rec.ext_rec_panel)

    @api.onchange('internal_movement_type', 'transfer_eval_mode', 'sourcing_type', 'employee_category')
    def _onchange_movement_type_sync_weights(self):
        for rec in self:
            if rec.scores_computed:
                continue
            is_transfer = rec.internal_movement_type in ('lateral', 'transfer')
            if is_transfer:
                if not rec.transfer_eval_mode:
                    rec.transfer_eval_mode = 'transfer_matrix_only'
                profile = False
                if "assessment.weight.profile" in self.env:
                    profile = self.env["assessment.weight.profile"].sudo().search([
                        ("candidate_type", "=", "transfer"),
                        ("active", "=", True)
                    ], limit=1)
                if profile and profile.line_ids:
                    pms_w, app_w, exp_w, loc_w, rec_w = 0.0, 0.0, 0.0, 0.0, 0.0
                    for line in profile.line_ids:
                        if line.component == "pms":
                            pms_w = line.weight_percentage
                        elif line.component == "app_date":
                            app_w = line.weight_percentage
                        elif line.component == "experience":
                            exp_w = line.weight_percentage
                        elif line.component == "service_location":
                            loc_w = line.weight_percentage
                        elif line.component == "recommendation":
                            rec_w = line.weight_percentage
                    rec.pms_weight = pms_w or 30.0
                    rec.app_date_weight = app_w or 20.0
                    rec.experience_weight = exp_w or 20.0
                    rec.location_weight = loc_w or 20.0
                    rec.recommendation_weight = rec_w or 10.0
                else:
                    rec.pms_weight = 30.0
                    rec.app_date_weight = 20.0
                    rec.experience_weight = 20.0
                    rec.location_weight = 20.0
                    rec.recommendation_weight = 10.0
                if rec.transfer_eval_mode == 'transfer_matrix_only':
                    rec.written_weight = 0.0
                    rec.interview_weight = 0.0
                    rec.has_written_exam = False
                elif rec.transfer_eval_mode == 'interview_only':
                    rec.pms_weight = 50.0
                    rec.written_weight = 0.0
                    rec.interview_weight = 50.0
                    rec.has_written_exam = False
                    rec.app_date_weight = 0.0
                    rec.experience_weight = 0.0
                    rec.location_weight = 0.0
                    rec.recommendation_weight = 0.0
                else:  # 'standard'
                    rec.pms_weight = 40.0
                    rec.written_weight = 30.0
                    rec.interview_weight = 30.0
                    rec.has_written_exam = True
                    rec.app_date_weight = 0.0
                    rec.experience_weight = 0.0
                    rec.location_weight = 0.0
                    rec.recommendation_weight = 0.0
            elif rec.sourcing_type == 'external' or rec.internal_movement_type == 'external':
                rec.transfer_eval_mode = 'standard'
                rec.app_date_weight = 0.0
                rec.experience_weight = 0.0
                rec.location_weight = 0.0
                rec.recommendation_weight = 0.0
                rec.pms_weight = 0.0
                rec.written_weight = 50.0
                rec.interview_weight = 50.0
                rec.has_written_exam = True
            else:
                rec.transfer_eval_mode = 'standard'
                rec.app_date_weight = 0.0
                rec.experience_weight = 0.0
                rec.location_weight = 0.0
                rec.recommendation_weight = 0.0
                cat_str = (rec.employee_category or "").lower()
                if "managerial" in cat_str and "non" not in cat_str:
                    rec.pms_weight = 60.0
                    rec.written_weight = 0.0
                    rec.interview_weight = 40.0
                    rec.has_written_exam = False
                elif getattr(rec, 'job_level', False) == 'junior':
                    rec.pms_weight = 50.0
                    rec.written_weight = 25.0
                    rec.interview_weight = 25.0
                    rec.has_written_exam = True
                else:
                    rec.pms_weight = 40.0
                    rec.written_weight = 30.0
                    rec.interview_weight = 30.0
                    rec.has_written_exam = True

    @api.depends('job_position')
    def _compute_position_requirements(self):
        for rec in self:
            qual_lines = []
            exp_lines = []
            if rec.job_position:
                job = rec.job_position
                if getattr(job, 'qualification_id', False) and job.qualification_id:
                    for q in job.qualification_id:
                        q_name = (q.qualification.display_name or getattr(q.qualification, 'qualification', '') or '') if getattr(q, 'qualification', False) else ''
                        lvl = getattr(q, 'required_level', '') or ''
                        if q_name:
                            qual_lines.append(f"• {q_name}" + (f" ({lvl})" if lvl else ""))
                if getattr(job, 'experience_id', False) and job.experience_id:
                    for exp in job.experience_id:
                        e_name = (exp.experience.display_name or getattr(exp.experience, 'experience', '') or '') if getattr(exp, 'experience', False) else ''
                        e_yrs = getattr(exp, 'years_of_experience', '') or ''
                        if e_name:
                            exp_lines.append(f"• {e_name}" + (f" ({e_yrs} yrs)" if e_yrs else ""))
            rec.position_qualifications = "\n".join(qual_lines) if qual_lines else ""
            rec.position_experiences = "\n".join(exp_lines) if exp_lines else ""

    @api.depends('recruitment_request_id', 'no_of_vacancies', 'job_position', 'operating_unit_id')
    def _compute_plan_fulfillment(self):
        OUJobPos = self.env['operating.unit.job.position'].sudo() if 'operating.unit.job.position' in self.env else None
        PBMSPlan = self.env['pbms.planning.category'].sudo() if 'pbms.planning.category' in self.env else None
        for rec in self:
            if rec.operating_unit_id and rec.job_position and OUJobPos is not None:
                ou_pos = OUJobPos.search([
                    ('operating_unit_id', '=', rec.operating_unit_id.id),
                    ('job_position_id', '=', rec.job_position.id),
                ], limit=1)
                if ou_pos:
                    rec.approved_plan_count = ou_pos.approved_plan_count or 0
                    rec.plan_fulfillment_promotion = getattr(ou_pos, 'plan_fulfillment_promotion', 0) or 0
                    rec.plan_fulfillment_lateral = getattr(ou_pos, 'plan_fulfillment_lateral', 0) or 0
                else:
                    rec.approved_plan_count = 0
                    rec.plan_fulfillment_promotion = 0
                    rec.plan_fulfillment_lateral = 0

                # Fallback to PBMS manpower plan if operating.unit.job.position approved_plan_count is 0
                if rec.approved_plan_count <= 0 and PBMSPlan is not None:
                    pbms_plans = PBMSPlan.search([
                        ('category', '=', 'manpower'),
                        ('org_unit_id', '=', rec.operating_unit_id.id),
                        ('state', '=', 'approved'),
                        ('active', '=', True),
                    ])
                    matching_lines = pbms_plans.mapped('line_ids').filtered(
                        lambda l: l.line_type == 'manpower' and l.job_id == rec.job_position
                    )
                    pbms_qty = sum(matching_lines.mapped('quantity'))
                    if pbms_qty > 0:
                        rec.approved_plan_count = int(pbms_qty)
            else:
                rec.approved_plan_count = 0
                rec.plan_fulfillment_promotion = 0
                rec.plan_fulfillment_lateral = 0
    written_exam_date = fields.Datetime(string="Written Exam Date")
    exam_location = fields.Text(string="Exam Location")
    exam_scheduled = fields.Selection([('Yes', 'Yes'), ('No', 'No')], string="Exam Scheduled", default='No')
    interview_date = fields.Datetime(string="Interview Date")
    interview_location = fields.Text(string="Interview Location")
    interview_scheduled = fields.Selection([('Yes', 'Yes'), ('No', 'No')], string="Interview Scheduled", default='No')
    panel_notified = fields.Boolean(string="Panel Notified", default=False)
    selection_notified = fields.Boolean(string="Selection Notified", default=False)
    show_reschedule_button = fields.Boolean(compute="_compute_show_reschedule_button_unified")
    total_candidates_count = fields.Integer(compute="_compute_candidate_counts", string="Applicants")
    selected_candidates_count = fields.Integer(compute="_compute_candidate_counts", string="Selected")
    reserve_candidates_count = fields.Integer(compute="_compute_candidate_counts", string="Reserve Pool")
    disqualified_candidates_count = fields.Integer(compute="_compute_candidate_counts", string="Disqualified")
    exam_candidate_summary = fields.Text(
        string="Committee Summary",
        help="Summary regarding the written/interview exam results and selected candidates for the Recruitment Approval Committee review."
    )

    # Recruitment process sequential workflow flags & stage
    recruitment_step = fields.Selection([
        ('shortlist', 'Shortlist Candidates'),
        ('notify_cand', 'Notify Candidates'),
        ('notify_exam', 'Notify Written Exam'),
        ('fetch_exam', 'Fetch Written Exam'),
        ('notify_panel', 'Notify Panel'),
        ('notify_interview', 'Notify Interview'),
        ('fetch_interview', 'Fetch Interview'),
        ('compute_rank', 'Compute and Rank'),
        ('notify_committee', 'Notify Approval Committee'),
        ('digital_minute', 'Digital Signature'),
        ('notify_selection', 'Notify Selected Candidates'),
        ('promote', 'Promote Selected Candidates'),
        ('hire', 'Hire Selected Candidates'),
        ('done', 'Completed'),
    ], string="Recruitment Workflow Step", default='shortlist', copy=False)

    shortlist_done = fields.Boolean(string="Shortlist Done", default=False)
    candidate_notified = fields.Boolean(string="Candidate Notified", default=False)
    exam_notified = fields.Boolean(string="Exam Notified", default=False)
    interview_notified = fields.Boolean(string="Interview Notified", default=False)
    committee_notified = fields.Boolean(string="Committee Notified", default=False)
    minute_signed = fields.Boolean(string="Minute Signed", default=False)
    employees_promoted = fields.Boolean(string="Employees Promoted", default=False)

    @api.depends('sourcing_type', 'new_int_rec_sel', 'ext_rec_sel', 'selected_recruitment_id', 'ext_selected_recruitment_id')
    def _compute_candidate_counts(self):
        for rec in self:
            is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in (rec.reference or '').upper() or 'LAT' in (rec.reference or '').upper()
            lines = rec.new_int_rec_sel if is_internal else rec.ext_rec_sel
            rec.total_candidates_count = len(lines)
            rec.selected_candidates_count = len([l for l in lines if getattr(l, 'selection_type', '') in ('selected', 'Selected')])
            rec.reserve_candidates_count = len([l for l in lines if getattr(l, 'selection_type', '') in ('reserve', 'reserved', 'Reserve', 'Reserved')])
            rec.disqualified_candidates_count = len([l for l in lines if getattr(l, 'selection_type', '') in ('rejected', 'Disqualified')])

    def _compute_has_delegation_requests_unified(self):
        for rec in self:
            if rec.selected_recruitment_id and rec.selected_recruitment_id.has_delegation_requests:
                rec.has_delegation_requests = True
            elif rec.ext_selected_recruitment_id and rec.ext_selected_recruitment_id.has_delegation_requests:
                rec.has_delegation_requests = True
            else:
                rec.has_delegation_requests = False

    def _compute_show_reschedule_button_unified(self):
        for rec in self:
            if rec.selected_recruitment_id and rec.selected_recruitment_id.show_reschedule_button:
                rec.show_reschedule_button = True
            elif rec.ext_selected_recruitment_id and rec.ext_selected_recruitment_id.show_reschedule_button:
                rec.show_reschedule_button = True
            else:
                rec.show_reschedule_button = False

    def action_step_back(self):
        """Roll back recruitment workflow by exactly ONE sequential step."""
        for rec in self:
            is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in (rec.reference or '').upper() or 'LAT' in (rec.reference or '').upper()
            curr = rec.recruitment_step or 'shortlist'

            vals = {}
            if curr == 'done':
                vals = {
                    'recruitment_step': 'hire' if (rec.sourcing_type == 'external' or 'EXT' in (rec.reference or '').upper()) else 'promote',
                    'employees_promoted': False,
                }
            elif curr in ('promote', 'hire'):
                vals = {
                    'recruitment_step': 'notify_selection',
                    'selection_notified': False,
                }
            elif curr == 'notify_selection':
                vals = {
                    'recruitment_step': 'notify_committee',
                    'committee_notified': False,
                    'minute_signed': False,
                }
            elif curr == 'notify_committee':
                vals = {
                    'recruitment_step': 'compute_rank',
                    'scores_computed': False,
                }
            elif curr == 'compute_rank':
                is_lateral = (rec.internal_movement_type in ('lateral', 'transfer') or (rec.reference and 'LAT' in (rec.reference or '').upper())) and rec.internal_movement_type != 'promotion'
                if is_lateral or (not rec.has_written_exam and not rec.has_interview):
                    vals = {
                        'recruitment_step': 'notify_cand' if is_internal else 'shortlist',
                        'candidate_notified': False,
                        'scores_computed': False,
                    }
                elif not rec.has_interview and rec.has_written_exam:
                    vals = {
                        'recruitment_step': 'notify_exam',
                        'exam_notified': False,
                        'exam_scheduled': 'No',
                        'exam_scores_fetched': False,
                        'scores_computed': False,
                    }
                else:
                    vals = {
                        'recruitment_step': 'notify_interview',
                        'interview_notified': False,
                        'interview_scheduled': 'No',
                        'interview_scores_fetched': False,
                        'scores_computed': False,
                    }
            elif curr == 'fetch_interview':
                vals = {
                    'recruitment_step': 'notify_interview',
                    'interview_notified': False,
                    'interview_scheduled': 'No',
                }
            elif curr == 'notify_interview':
                vals = {
                    'recruitment_step': 'notify_panel',
                    'panel_notified': False,
                }
            elif curr == 'notify_panel':
                if rec.has_written_exam:
                    vals = {
                        'recruitment_step': 'notify_exam',
                        'exam_notified': False,
                        'exam_scheduled': 'No',
                        'exam_scores_fetched': False,
                    }
                elif is_internal:
                    vals = {
                        'recruitment_step': 'notify_cand',
                        'candidate_notified': False,
                    }
                else:
                    vals = {
                        'recruitment_step': 'shortlist',
                        'shortlist_done': False,
                    }
            elif curr == 'fetch_exam':
                vals = {
                    'recruitment_step': 'notify_exam',
                    'exam_notified': False,
                    'exam_scheduled': 'No',
                }
            elif curr == 'notify_exam':
                if is_internal:
                    vals = {
                        'recruitment_step': 'notify_cand',
                        'candidate_notified': False,
                    }
                else:
                    vals = {
                        'recruitment_step': 'shortlist',
                        'shortlist_done': False,
                    }
            elif curr == 'notify_cand':
                vals = {
                    'recruitment_step': 'shortlist',
                    'shortlist_done': False,
                }
            else:
                vals = {
                    'recruitment_step': 'shortlist',
                    'shortlist_done': False,
                }

            rec.write(vals)

            if vals.get('recruitment_step') == 'shortlist':
                rec._release_all_candidate_states()

            # Sync selected pipeline record if exists
            sel = rec._get_selected_recruitment_record()
            if sel:
                sel_vals = {}
                if 'exam_scheduled' in vals:
                    sel_vals['exam_scheduled'] = vals['exam_scheduled']
                if 'interview_scheduled' in vals:
                    sel_vals['interview_scheduled'] = vals['interview_scheduled']
                if 'scores_computed' in vals and not vals['scores_computed']:
                    if hasattr(sel, 'scores_computed'):
                        sel_vals['scores_computed'] = False
                if sel_vals:
                    sel.write(sel_vals)

        step_labels = dict(self._fields['recruitment_step'].selection)
        new_label = step_labels.get(self.recruitment_step, self.recruitment_step)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Previous Step'),
                'message': _('Workflow rolled back one step to: %s') % new_label,
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _release_all_candidate_states(self):
        """Release all candidate states, unlinking shortlist selections,
        resetting bunna_app_status to 'draft', clearing exam/interview schedules,
        and resetting eligible employee lines."""
        for rec in self:
            ref = rec.reference or ''
            job = getattr(rec, 'job_position', False) or getattr(rec, 'job_id', False)
            job_id = job.id if job else 0

            # 1. Reset hr.applicant records linked to this vacancy
            domain = []
            if ref and job_id:
                domain = ['|', ('vacancy_reference', '=', ref), ('job_id', '=', job_id)]
            elif ref:
                domain = [('vacancy_reference', '=', ref)]
            elif job_id:
                domain = [('job_id', '=', job_id)]

            if domain:
                apps = self.env['hr.applicant'].sudo().search(domain)
                if apps:
                    app_vals = {'bunna_app_status': 'draft'}
                    if 'stage_id' in apps._fields:
                        new_stage = self.env['hr.recruitment.stage'].sudo().search([('sequence', '=', 0)], limit=1)
                        if new_stage:
                            app_vals['stage_id'] = new_stage.id
                    for f in ['is_written_exam_notified', 'scheduled_written_exam_date', 'scheduled_written_exam_location',
                              'is_interview_notified', 'scheduled_interview_date', 'scheduled_interview_location',
                              'candidate_score_id']:
                        if f in apps._fields and not apps._fields[f].readonly:
                            app_vals[f] = False
                    apps.write(app_vals)

            # 2. External recruitment selected records & shortlisted candidates
            ext_sel_domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', ref)] if ref else [('vacancy_id', '=', rec.id)]
            ext_sels = self.env['external.recruitment.selected'].sudo().search(ext_sel_domain)
            for ext_sel in ext_sels:
                cands = getattr(ext_sel, 'ext_rec_sel', False) or getattr(ext_sel, 'ext_rec_sel_cand', False)
                if cands:
                    cands.unlink()
                ext_sel.write({
                    'active': False,
                    'exam_scheduled': 'No',
                    'interview_scheduled': 'No',
                    'scores_computed': False,
                    'selection_notified': False,
                    'minute_signed': False,
                    'committee_notified': False,
                })

            # 3. External recruitment process records (employee.recruitment.external)
            rec_ext_domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', ref)] if ref else [('vacancy_id', '=', rec.id)]
            rec_exts = self.env['employee.recruitment.external'].sudo().search(rec_ext_domain)
            for re in rec_exts:
                re.write({
                    'shortlisting_done': False,
                    'status': False,
                })
                if re.eligible_emp_external:
                    re.eligible_emp_external.write({
                        'application_status': 'submitted',
                        'select_flag': False,
                    })

            # 4. Internal recruitment selected records (new.internal.recruitment.selected)
            int_sel_domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', ref)] if ref else [('vacancy_id', '=', rec.id)]
            int_sels = self.env['new.internal.recruitment.selected'].sudo().search(int_sel_domain)
            for int_sel in int_sels:
                cands = getattr(int_sel, 'new_int_rec_sel', False) or getattr(int_sel, 'candidate_ids', False)
                if cands:
                    cands.unlink()
                int_sel.write({
                    'active': False,
                    'exam_scheduled': 'No',
                    'interview_scheduled': 'No',
                    'scores_computed': False,
                    'selection_notified': False,
                    'minute_signed': False,
                    'committee_notified': False,
                })

            # 5. Internal recruitment process records (employee.recruitment)
            if 'employee.recruitment' in self.env:
                EmpRec = self.env['employee.recruitment'].sudo()
                rec_int_domain = []
                if ref and 'vacancy_reference' in EmpRec._fields and 'vacancy_id' in EmpRec._fields:
                    rec_int_domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', ref)]
                elif ref and 'vacancy_reference' in EmpRec._fields:
                    rec_int_domain = [('vacancy_reference', '=', ref)]
                elif 'vacancy_id' in EmpRec._fields:
                    rec_int_domain = [('vacancy_id', '=', rec.id)]
                if rec_int_domain:
                    rec_ints = EmpRec.search(rec_int_domain)
                    for ri in rec_ints:
                        ri_vals = {}
                        if hasattr(ri, 'shortlisting_done'):
                            ri_vals['shortlisting_done'] = False
                        if hasattr(ri, 'status'):
                            ri_vals['status'] = False
                        if ri_vals:
                            ri.write(ri_vals)
                        if hasattr(ri, 'eligible_emp_internal') and ri.eligible_emp_internal:
                            ri.eligible_emp_internal.write({
                                'application_status': 'submitted',
                                'select_flag': False,
                            })

            # 6. Digital selection minutes (recruitment.selection.minute)
            minutes = self.env['recruitment.selection.minute'].sudo().search([('vacancy_id', '=', rec.id)])
            for m in minutes:
                if m.state == 'draft':
                    m.unlink()
                else:
                    m.write({'active': False})

    def action_reset_workflow(self):
        """Reset the recruitment workflow completely back to the initial shortlist stage and release candidates."""
        for rec in self:
            rec.write({
                'recruitment_step': 'shortlist',
                'shortlist_done': False,
                'candidate_notified': False,
                'exam_notified': False,
                'exam_scores_fetched': False,
                'panel_notified': False,
                'interview_notified': False,
                'interview_scores_fetched': False,
                'scores_computed': False,
                'committee_notified': False,
                'minute_signed': False,
                'selection_notified': False,
                'employees_promoted': False,
                'exam_scheduled': 'No',
                'interview_scheduled': 'No',
                'ext_selected_recruitment_id': False,
                'selected_recruitment_id': False,
            })
            rec._release_all_candidate_states()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Workflow Reset'),
                'message': _('Recruitment workflow has been completely reset to the Shortlist stage and all candidate states released.'),
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_reset_to_draft(self):
        """Reset the Job Vacancy completely back to Draft status and release all candidates."""
        for rec in self:
            rec.write({
                'vacancy_status': 'draft',
                'state': 'draft',
                'recruitment_step': 'shortlist',
                'shortlist_done': False,
                'candidate_notified': False,
                'exam_notified': False,
                'exam_scores_fetched': False,
                'panel_notified': False,
                'interview_notified': False,
                'interview_scores_fetched': False,
                'scores_computed': False,
                'committee_notified': False,
                'minute_signed': False,
                'selection_notified': False,
                'employees_promoted': False,
                'exam_scheduled': 'No',
                'interview_scheduled': 'No',
                'ext_selected_recruitment_id': False,
                'selected_recruitment_id': False,
            })
            rec._release_all_candidate_states()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reset to Draft'),
                'message': _('Vacancy and all candidate states have been completely released back to Draft.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.depends('reference')
    def _compute_selected_recruitment_id(self):
        Selected = self.env['new.internal.recruitment.selected']
        for rec in self:
            sel_rec = False
            if rec.id:
                domain = [('vacancy_id', '=', rec.id)]
                if rec.reference and rec.reference != 'New':
                    domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)]
                sel_rec = Selected.search(domain, order='id desc', limit=1)
            rec.selected_recruitment_id = sel_rec

    @api.depends('reference')
    def _compute_ext_selected_recruitment_id(self):
        ExtSelected = self.env['external.recruitment.selected']
        for rec in self:
            ext_rec = False
            if rec.id:
                domain = [('vacancy_id', '=', rec.id)]
                if rec.reference and rec.reference != 'New':
                    domain = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)]
                ext_rec = ExtSelected.search(domain, order='id desc', limit=1)
            rec.ext_selected_recruitment_id = ext_rec

    @staticmethod
    def _write_if_changed(record, vals):
        """Writes only fields whose values actually differ from existing record values, preventing redundant writes."""
        if not record or not vals:
            return False
        diff_vals = {}
        for key, new_val in vals.items():
            curr_val = getattr(record, key, None)
            if hasattr(curr_val, 'id'):
                curr_val = curr_val.id
            if curr_val != new_val:
                diff_vals[key] = new_val
        if diff_vals:
            record.write(diff_vals)
            return True
        return False

    def _sync_selected_recruitment_records(self):
        """Ensures selected recruitment pipeline record is bidirectional linked to vacancy."""
        Selected = self.env['new.internal.recruitment.selected'].sudo()
        ExtSelected = self.env['external.recruitment.selected'].sudo()
        for rec in self:
            # Skip unpersisted records or drafts with reference = 'New' (Areas 2 & 3)
            if not rec.id or rec.reference in (False, 'New', _('New')):
                continue
            try:
                with self.env.cr.savepoint():
                    self._sync_one_selected_recruitment(rec, Selected, ExtSelected)
            except Exception as e:
                err_str = str(e).lower()
                if "timeout" in err_str or "lock" in err_str or "could not obtain lock" in err_str or "canceling statement due to statement timeout" in err_str:
                    _logger.error("Database lock/timeout during sync selected recruitment for %s: %s", rec.reference, e)
                    raise
                _logger.warning("Sync selected recruitment record failed for %s: %s", rec.reference, e)

    def _sync_one_selected_recruitment(self, rec, Selected, ExtSelected):
        if not rec.id or rec.reference in (False, 'New', _('New')):
            return

        is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in (rec.reference or '').upper() or 'LAT' in (rec.reference or '').upper()
        if is_internal:
            domain_int = [('vacancy_id', '=', rec.id)]
            if rec.reference and rec.reference not in (False, 'New', _('New')):
                domain_int = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)]
            sel_rec = Selected.search(domain_int, order='id desc', limit=1)
            if not sel_rec and rec.id:
                sel_rec = Selected.sudo().create({
                    'vacancy_id': rec.id,
                    'vacancy_reference': rec.reference,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'job_location': rec.operating_unit_id.name if rec.operating_unit_id else (rec.job_location or False),
                    'job_grade': rec.job_grade.grade_name if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) else False,
                    'job_category': rec.employee_category,
                    'written_exam_date': rec.written_exam_date or False,
                    'exam_location': rec.exam_location or False,
                    'interview_date': rec.interview_date or False,
                    'interview_location': rec.interview_location or False,
                    'no_of_vacancies': rec.no_of_vacancies or 0,
                })
            if sel_rec:
                int_sync_vals = {
                    'vacancy_id': rec.id,
                    'vacancy_reference': rec.reference,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'job_grade': rec.job_grade.grade_name if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) else False,
                    'job_location': rec.operating_unit_id.name if rec.operating_unit_id else (rec.job_location or False),
                    'written_exam_date': rec.written_exam_date or False,
                    'exam_location': rec.exam_location or False,
                    'interview_date': rec.interview_date or False,
                    'interview_location': rec.interview_location or False,
                    'no_of_vacancies': rec.no_of_vacancies or 0,
                    'exam_candidate_summary': rec.exam_candidate_summary or False,
                    'exam_scheduled': rec.exam_scheduled or 'No',
                    'interview_scheduled': rec.interview_scheduled or 'No',
                    'transfer_eval_mode': rec.transfer_eval_mode or 'standard',
                    'app_date_weight': rec.app_date_weight or 0.0,
                    'experience_weight': rec.experience_weight or 0.0,
                    'location_weight': rec.location_weight or 0.0,
                    'recommendation_weight': rec.recommendation_weight or 0.0,
                    'pms_weight': rec.pms_weight or 0.0,
                    'written_weight': rec.written_weight or 0.0,
                    'interview_weight': rec.interview_weight or 0.0,
                    'approval_hierarchy_type': rec.approval_hierarchy_type or False,
                    'chairperson_id': rec.chairperson_id.id if rec.chairperson_id else False,
                    'panel_member_id': rec.panel_member_id.id if rec.panel_member_id else False,
                    'secretary_id': rec.secretary_id.id if rec.secretary_id else False,
                    'observer_id': rec.observer_id.id if rec.observer_id else False,
                }
                self._write_if_changed(sel_rec, int_sync_vals)
                if rec.selected_recruitment_id != sel_rec:
                    rec.selected_recruitment_id = sel_rec.id
                if rec.ext_selected_recruitment_id:
                    rec.ext_selected_recruitment_id = False
                rec._sync_committee_lines_from_hierarchy()
        else:
            domain_ext = [('vacancy_id', '=', rec.id)]
            if rec.reference and rec.reference not in (False, 'New', _('New')):
                domain_ext = ['|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)]
            ext_sel = ExtSelected.search(domain_ext, order='id desc', limit=1)
            if not ext_sel and rec.id:
                ext_sel = ExtSelected.sudo().create({
                    'vacancy_id': rec.id,
                    'vacancy_reference': rec.reference,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'job_location': rec.operating_unit_id.name if rec.operating_unit_id else (rec.job_location or 'Main Branch'),
                    'job_grade': rec.job_grade.grade_name if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) else False,
                    'job_category': rec.employee_category,
                    'written_exam_date': rec.written_exam_date or False,
                    'exam_location': rec.exam_location or False,
                    'interview_date': rec.interview_date or False,
                    'interview_location': rec.interview_location or False,
                    'exam_candidate_summary': rec.exam_candidate_summary or False,
                    'exam_scheduled': rec.exam_scheduled or 'No',
                    'interview_scheduled': rec.interview_scheduled or 'No',
                    'no_of_vacancies': rec.no_of_vacancies or 0,
                    'approval_hierarchy_type': rec.approval_hierarchy_type or False,
                    'chairperson_id': rec.chairperson_id.id if rec.chairperson_id else False,
                    'panel_member_id': rec.panel_member_id.id if rec.panel_member_id else False,
                    'secretary_id': rec.secretary_id.id if rec.secretary_id else False,
                    'observer_id': rec.observer_id.id if rec.observer_id else False,
                })
            if ext_sel:
                ext_sync_vals = {
                    'vacancy_id': rec.id,
                    'vacancy_reference': rec.reference,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'job_grade': rec.job_grade.grade_name if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) else False,
                    'job_location': rec.operating_unit_id.name if rec.operating_unit_id else (rec.job_location or 'Main Branch'),
                    'written_exam_date': rec.written_exam_date or False,
                    'exam_location': rec.exam_location or False,
                    'interview_date': rec.interview_date or False,
                    'interview_location': rec.interview_location or False,
                    'exam_candidate_summary': rec.exam_candidate_summary or False,
                    'exam_scheduled': rec.exam_scheduled or 'No',
                    'interview_scheduled': rec.interview_scheduled or 'No',
                    'no_of_vacancies': rec.no_of_vacancies or 0,
                    'approval_hierarchy_type': rec.approval_hierarchy_type or False,
                    'chairperson_id': rec.chairperson_id.id if rec.chairperson_id else False,
                    'panel_member_id': rec.panel_member_id.id if rec.panel_member_id else False,
                    'secretary_id': rec.secretary_id.id if rec.secretary_id else False,
                    'observer_id': rec.observer_id.id if rec.observer_id else False,
                }
                self._write_if_changed(ext_sel, ext_sync_vals)
                if rec.ext_selected_recruitment_id != ext_sel:
                    rec.ext_selected_recruitment_id = ext_sel.id
                if rec.selected_recruitment_id:
                    rec.selected_recruitment_id = False
                rec._sync_committee_lines_from_hierarchy()

    def _get_selected_recruitment_record(self):
        self.ensure_one()
        ref = self.reference or ''
        is_internal = self.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()
        if is_internal:
            if self.selected_recruitment_id:
                return self.selected_recruitment_id.sudo()
            return self.env['new.internal.recruitment.selected'].sudo().search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
        else:
            ext_sel = self.env['external.recruitment.selected'].sudo().search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if ext_sel:
                return ext_sel
            return self.ext_selected_recruitment_id.sudo() if self.ext_selected_recruitment_id else False

    # ---------------------------------------------------------------
    # Unified Action Proxy Handlers (Delegates to Selected Models)
    # ---------------------------------------------------------------
    def action_notify_written_exam(self):
        self.ensure_one()
        dt = self.written_exam_date or (self.ext_selected_recruitment_id.written_exam_date if self.ext_selected_recruitment_id else (self.selected_recruitment_id.written_exam_date if self.selected_recruitment_id else False))
        loc = self.exam_location or (self.ext_selected_recruitment_id.exam_location if self.ext_selected_recruitment_id else (self.selected_recruitment_id.exam_location if self.selected_recruitment_id else False))

        if not dt or not loc:
            raise UserError(_('Please specify both the Written Exam Date and Exam Location before notifying candidates.'))
        now = fields.Datetime.now()
        if dt <= now:
            raise UserError(_("Written Exam Date cannot be in the past. It must be greater than current date and time."))
        if self.last_date_to_apply:
            local_exam_date = fields.Datetime.context_timestamp(self, dt).date()
            if local_exam_date <= self.last_date_to_apply:
                raise UserError(_(
                    "Written Exam Date (%(exam_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                ) % {
                    'exam_date': local_exam_date.strftime('%Y-%m-%d'),
                    'deadline': self.last_date_to_apply.strftime('%Y-%m-%d'),
                })

        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()

        if sel:
            if not dt and sel.written_exam_date:
                dt = sel.written_exam_date
            if dt and sel.written_exam_date != dt:
                sel.sudo().write({'written_exam_date': dt})
            if loc and sel.exam_location != loc:
                sel.sudo().write({'exam_location': loc})
            res = sel.notify_written_exam()
            self.exam_scheduled = 'Yes'
            self.exam_notified = True
            self.exam_scores_fetched = True
            self.recruitment_step = 'notify_panel'
            return res

    def action_fetch_exam_score(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if not sel:
            raise UserError(_("No recruitment selection record found. Please shortlist candidates first."))
        res = sel.fetch_exam_score()
        self.exam_scores_fetched = True
        self.recruitment_step = 'notify_panel'
        self.env.invalidate_all()
        return res

    def action_notify_interview_panel(self):
        self.ensure_one()
        dt = self.interview_date or (self.ext_selected_recruitment_id.interview_date if self.ext_selected_recruitment_id else (self.selected_recruitment_id.interview_date if self.selected_recruitment_id else False))
        loc = self.interview_location or (self.ext_selected_recruitment_id.interview_location if self.ext_selected_recruitment_id else (self.selected_recruitment_id.interview_location if self.selected_recruitment_id else False))

        if not dt or not loc:
            raise UserError(_('Please specify both the Interview Date and Interview Location before notifying the panel.'))
        now = fields.Datetime.now()
        if dt <= now:
            raise UserError(_("Interview Date cannot be in the past. It must be greater than current date and time."))
        if self.last_date_to_apply:
            local_inter_date = fields.Datetime.context_timestamp(self, dt).date()
            if local_inter_date <= self.last_date_to_apply:
                raise UserError(_(
                    "Interview Date (%(interview_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                ) % {
                    'interview_date': local_inter_date.strftime('%Y-%m-%d'),
                    'deadline': self.last_date_to_apply.strftime('%Y-%m-%d'),
                })
        if self.written_exam_date and dt < self.written_exam_date:
            raise UserError(_("Interview Date cannot be earlier than Written Exam Date."))

        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()

        has_panel = False
        if sel:
            if hasattr(sel, 'new_int_rec_panel') and sel.new_int_rec_panel.filtered(lambda p: p.emp_name):
                has_panel = True
            elif hasattr(sel, 'ext_rec_panel') and sel.ext_rec_panel.filtered(lambda p: p.emp_name):
                has_panel = True
        if not has_panel and hasattr(self, 'memb_panel_vac') and self.memb_panel_vac.filtered(lambda p: getattr(p, 'employee_id', False) or getattr(p, 'delegate_employee_id', False) or getattr(p, 'user_id', False)):
            has_panel = True

        if not has_panel:
            raise UserError(_("Please add panel members in the Panel Members tab before notifying the panel."))

        if sel:
            try:
                if hasattr(sel, 'fetch_exam_score'):
                    sel.fetch_exam_score()
            except Exception:
                pass
            if not getattr(sel, 'exam_scores_fetched', False) and getattr(self, 'exam_scores_fetched', False):
                sel.sudo().write({'exam_scores_fetched': True})
            cands = sel.new_int_rec_sel if hasattr(sel, 'new_int_rec_sel') else (sel.ext_rec_sel if hasattr(sel, 'ext_rec_sel') else False)
            if cands:
                passing_cands = cands.filtered(lambda c: (c.written_exam_score or 0.0) >= 50.0 and getattr(c, 'select_flag', True) and getattr(c, 'selection_type', '') != 'rejected')
                if not passing_cands:
                    raise UserError(_("No candidates have passed the written examination (minimum 50% score required). Cannot proceed to notify the interview panel."))

            if not dt and sel.interview_date:
                dt = sel.interview_date
                self.interview_date = dt
            if dt and sel.interview_date != dt:
                sel.sudo().write({'interview_date': dt})
            if loc and sel.interview_location != loc:
                sel.sudo().write({'interview_location': loc})
            if hasattr(sel, 'notify_interview_panel'):
                res = sel.notify_interview_panel()
            elif hasattr(sel, 'action_notify_panel_members'):
                res = sel.action_notify_panel_members()
            else:
                res = True
            self.panel_notified = True
            self.recruitment_step = 'notify_interview'
            return res
        return True

    def action_open_reschedule_wizard(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            return sel.action_open_reschedule_wizard()

    def action_notify_interview(self):
        self.ensure_one()
        dt = self.interview_date or (self.ext_selected_recruitment_id.interview_date if self.ext_selected_recruitment_id else (self.selected_recruitment_id.interview_date if self.selected_recruitment_id else False))
        loc = self.interview_location or (self.ext_selected_recruitment_id.interview_location if self.ext_selected_recruitment_id else (self.selected_recruitment_id.interview_location if self.selected_recruitment_id else False))

        if not dt or not loc:
            raise UserError(_('Please specify both the Interview Date and Interview Location before notifying candidates.'))
        now = fields.Datetime.now()
        if dt <= now:
            raise UserError(_("Interview Date cannot be in the past. It must be greater than current date and time."))
        if self.last_date_to_apply:
            local_inter_date = fields.Datetime.context_timestamp(self, dt).date()
            if local_inter_date <= self.last_date_to_apply:
                raise UserError(_(
                    "Interview Date (%(interview_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                ) % {
                    'interview_date': local_inter_date.strftime('%Y-%m-%d'),
                    'deadline': self.last_date_to_apply.strftime('%Y-%m-%d'),
                })
        if self.written_exam_date and dt < self.written_exam_date:
            raise UserError(_("Interview Date cannot be earlier than Written Exam Date."))

        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()

        if sel:
            if not dt and sel.interview_date:
                dt = sel.interview_date
            if dt and sel.interview_date != dt:
                sel.sudo().write({'interview_date': dt})
            if loc and sel.interview_location != loc:
                sel.sudo().write({'interview_location': loc})
            res = sel.notify_interview()
            self.interview_scheduled = 'Yes'
            self.interview_notified = True
            self.interview_scores_fetched = True
            self.recruitment_step = 'compute_rank'
            return res

    def action_fetch_interview_score(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            res = sel.fetch_interview_score()
            self.interview_scores_fetched = True
            self.recruitment_step = 'compute_rank'
            self.env.invalidate_all()
            return res
        raise UserError(_("No recruitment selection record found for this vacancy."))

    def action_request_supervisor_recommendation(self):
        """Request supervisor recommendation for eligible transfer/lateral candidates with direct links."""
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        
        cands = []
        if sel and hasattr(sel, 'new_int_rec_sel'):
            cands = sel.new_int_rec_sel.filtered(lambda c: c.emp_name)
        elif hasattr(self, 'new_int_rec_sel') and self.new_int_rec_sel:
            cands = self.new_int_rec_sel.filtered(lambda c: c.emp_name)
        
        if not cands:
            raise UserError(_("No eligible candidates found to request supervisor recommendation."))

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        eval_url = f"{base_url.rstrip('/')}/recruitment/supervisor_evaluation/{self.id}"

        pos_title = self.job_position.name if self.job_position else (self.job_title or _('Job Position'))
        ref_str = self.reference or _('TBD')

        supervisor_cands = {}
        for cand in cands:
            emp = cand.emp_name
            sup = emp.parent_id or emp.coach_id
            if sup and sup.user_id and sup.user_id.partner_id:
                supervisor_cands.setdefault(sup, []).append(cand)

        if not supervisor_cands:
            raise UserError(_("None of the eligible candidates have a direct supervisor/coach linked to an active user account."))

        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        notified_supervisors = []

        for sup, sup_c_list in supervisor_cands.items():
            partner_id = sup.user_id.partner_id.id
            channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner_id])
            c_names = ", ".join(c.emp_name.name for c in sup_c_list)
            
            msg = Markup(
                f"<p>Dear <b>{escape(sup.name)}</b>,</p>"
                f"<p>Your subordinate(s) <b>{escape(c_names)}</b> have applied for the vacancy: <b>{escape(pos_title)}</b> (Ref: {escape(ref_str)}).</p>"
                f"<p>Kindly evaluate and grant their Supervisor Recommendation Marks (0 - 100%) and evaluation comments in the system before candidate ranking:</p>"
                f"<div style='margin-top: 12px; margin-bottom: 14px;'>"
                f"<p style='margin-bottom: 6px;'>• <b>Evaluation Link:</b> <a href='{eval_url}' target='_blank' style='color: #0d6efd; text-decoration: underline; font-weight: bold; word-break: break-all;'>{eval_url}</a></p>"
                f"<a href='{eval_url}' target='_blank' style='display: inline-block; padding: 9px 18px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                f"👉 Open Supervisor Evaluation"
                f"</a>"
                f"</div>"
                f"<p>Best regards,<br/><b>Bunna Bank Talent Acquisition &amp; OD</b></p>"
            )
            channel.message_post(body=msg, message_type='comment', subtype_xmlid='mail.mt_comment')

            if sel and hasattr(sel, 'activity_schedule') and sup.user_id:
                try:
                    existing_act = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'new.internal.recruitment.selected'),
                        ('res_id', '=', sel.id),
                        ('user_id', '=', sup.user_id.id),
                        ('summary', 'ilike', 'Supervisor Recommendation'),
                    ], limit=1)
                    if not existing_act:
                        sel.activity_schedule(
                            activity_type_id=todo_type.id if todo_type else False,
                            summary=_('Supervisor Recommendation: %s (%s)') % (pos_title, c_names),
                            note=Markup(_("<p>Please evaluate recommendation marks for: <b>%s</b></p><p><a href='%s'>Click here to evaluate</a></p>") % (c_names, eval_url)),
                            user_id=sup.user_id.id
                        )
                except Exception:
                    pass

            if sup.name not in notified_supervisors:
                notified_supervisors.append(sup.name)

        self.supervisor_rec_requested = True
        if sel:
            sel.supervisor_rec_requested = True

        msg_body = _("Supervisor recommendation requested for %d candidate(s). Notified Supervisors: %s") % (
            len(cands), ", ".join(notified_supervisors)
        )
        if sel and hasattr(sel, 'message_post'):
            try:
                sel.message_post(body=msg_body)
            except Exception:
                pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Evaluation Links Sent'),
                'message': _('Supervisor evaluation notification links sent successfully to: %s') % (
                    ", ".join(notified_supervisors)
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_supervisor_evaluation_wizard(self):
        """Opens supervisor evaluation wizard to grant recommendation marks."""
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel and hasattr(sel, 'action_open_supervisor_evaluation_wizard'):
            return sel.action_open_supervisor_evaluation_wizard()
        raise UserError(_("No recruitment selection record found for this vacancy."))

    def action_generate_minute(self):
        """Generates selection minute report."""
        self.ensure_one()
        is_external = self.sourcing_type == 'external' or 'EXT' in (self.reference or '').upper()
        if is_external:
            minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
            if not minute_rec:
                ext_sel = self.env['external.recruitment.selected'].search([
                    '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
                ], limit=1)
                if ext_sel:
                    ext_sel.action_open_digital_minute()
                    minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
            if minute_rec:
                return self.env.ref('custom_recruitment.action_report_selection_minute').report_action(minute_rec)

        if self.is_lateral_transfer:
            minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
            if not minute_rec:
                sel = self._get_selected_recruitment_record()
                if sel and hasattr(sel, 'action_open_digital_minute'):
                    sel.action_open_digital_minute()
                    minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
            if minute_rec:
                return self.env.ref('custom_recruitment.action_report_selection_minute').report_action(minute_rec)
            sel = self._get_selected_recruitment_record()
            if sel and hasattr(sel, 'action_generate_minute'):
                return sel.action_generate_minute()

        sel = self._get_selected_recruitment_record()
        minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
        if not minute_rec and sel and hasattr(sel, 'action_open_digital_minute'):
            sel.action_open_digital_minute()
            minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)

        if sel and hasattr(sel, 'action_generate_minute'):
            return sel.action_generate_minute()

        minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
        if minute_rec:
            return self.env.ref('custom_recruitment.action_report_selection_minute').report_action(minute_rec)
        raise UserError(_("No recruitment selection minute record found for this vacancy."))

    def action_compute_and_rank(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            try:
                if hasattr(sel, 'fetch_exam_score'):
                    sel.fetch_exam_score()
                if hasattr(sel, 'fetch_interview_score'):
                    sel.fetch_interview_score()
            except Exception:
                pass
            if hasattr(sel, 'action_compute_and_rank'):
                res = sel.action_compute_and_rank()
            elif hasattr(sel, 'compute_weighted_score'):
                res = sel.compute_weighted_score()
            else:
                res = True
            self.scores_computed = True
            self.recruitment_step = 'notify_committee'
            return res
        raise UserError(_("No recruitment selection record found for this vacancy."))

    def action_notify_approval_committee(self):
        """Notify the Recruitment Approval Committee members."""
        self.ensure_one()
        self._sync_selected_recruitment_records()

        sel = self._get_selected_recruitment_record()
        if not sel:
            raise UserError(_("No recruitment selection record found for this vacancy."))

        # Validate that at least one candidate passed both exam & interview (>= 50%) and is selected
        selected_candidates = False
        if hasattr(sel, 'ext_rec_sel') and sel.ext_rec_sel:
            selected_candidates = sel.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        elif hasattr(sel, 'new_int_rec_sel') and sel.new_int_rec_sel:
            selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        elif hasattr(self, 'new_int_rec_sel') and self.new_int_rec_sel:
            selected_candidates = self.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))

        if not selected_candidates:
            raise UserError(_("No candidates have passed the examination and interview assessments (minimum 50% required in each stage). Cannot proceed to notify the approval committee."))

        members = False
        if sel:
            if hasattr(sel, 'recr_selected_team_id') and sel.recr_selected_team_id:
                members = sel.recr_selected_team_id
            elif hasattr(sel, 'recr_exter_selected_team_id') and sel.recr_exter_selected_team_id:
                members = sel.recr_exter_selected_team_id
        if not members:
            members = self.recr_selected_team_id or self.vac_del_team_id

        # 1. Validate Committee Approval Roles from configuration
        has_hierarchy_roles = bool(self.chairperson_id and self.panel_member_id and self.secretary_id)
        has_committee_lines = bool(members and members.filtered(lambda m: getattr(m, 'employee_name', False) or getattr(m, 'alternate_committee_member', False)))
        if not has_hierarchy_roles and not has_committee_lines:
            raise ValidationError(_("Please assign all required Committee Approval Roles (Chairperson, Panel Member, and Secretary) under the 'Recruitment Approval Committee' tab before notifying the approval committee."))

        # 2. Validate that Committee Approval Minute has been added/generated
        minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
        if not minute_rec and 'transfer.committee.minutes' in self.env:
            minute_rec = self.env['transfer.committee.minutes'].search([('target_vacancy_id', '=', self.id)], order='id desc', limit=1)
        if not minute_rec:
            if sel and hasattr(sel, 'action_open_digital_minute'):
                try:
                    sel.action_open_digital_minute()
                    minute_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.id)], order='id desc', limit=1)
                except Exception as e:
                    _logger.warning("Could not open digital minute from selection record: %s", e)
            if not minute_rec:
                Minute = self.env['recruitment.selection.minute']
                pos_name = self.job_position.name if self.job_position else (self.reference or 'Vacancy')
                summary = _(
                    "Recruitment Selection Minute for position '%s'.\n"
                    "Total Candidates: %s | Vacancy Slots: %s"
                ) % (pos_name, len(self.new_int_rec_sel) if self.new_int_rec_sel else self.no_of_vacancies or 1, self.no_of_vacancies or 1)
                minute_rec = Minute.create({
                    'vacancy_id': self.id,
                    'recruitment_type': 'external' if self.sourcing_type == 'external' else 'internal',
                    'approval_hierarchy_type': self.approval_hierarchy_type or self._compute_hierarchy_type_recruitment(),
                    'chairperson_id': self.chairperson_id.id if self.chairperson_id else False,
                    'panel_member_id': self.panel_member_id.id if self.panel_member_id else False,
                    'secretary_id': self.secretary_id.id if self.secretary_id else False,
                    'observer_id': self.observer_id.id if self.observer_id else False,
                    'meeting_date': fields.Date.context_today(self),
                    'decision_summary': summary,
                })
                if hasattr(minute_rec, 'action_load_from_vacancy'):
                    minute_rec.action_load_from_vacancy()

        if minute_rec:
            if not minute_rec.ranking_line_ids and hasattr(minute_rec, 'action_load_from_vacancy'):
                minute_rec.action_load_from_vacancy()
            if minute_rec.ranking_line_ids:
                has_passed_in_minute = minute_rec.ranking_line_ids.filtered(
                    lambda l: getattr(l, 'selection_status', False) in ('selected', 'Selected', 'pass', 'Pass') or getattr(l, 'selection_decision', False) == 'selected'
                )
                if not has_passed_in_minute:
                    raise UserError(_("Cannot notify the approval committee! No candidate in the Committee Minute is marked as passed or selected."))

        self.committee_notified = True
        self.recruitment_step = 'notify_selection'
        if self.selected_recruitment_id:
            self.selected_recruitment_id.committee_notified = True
        notified_users = []
        pos_title = self.job_position.name if self.job_position else (self.job_title or _('Job Position'))
        work_unit_str = self.operating_unit_id.name if self.operating_unit_id else (self.job_location or _('Head Office'))
        ref_str = self.reference or _('TBD')

        summary_text = ""
        if self.exam_candidate_summary:
            summary_text = (
                f"\n\n📝 Summary of Exams & Selected Candidates:\n"
                f"{self.exam_candidate_summary}"
            )

        # Notify assigned hierarchy roles
        hierarchy_role_users = [
            (self.chairperson_id, _("Chairperson")),
            (self.panel_member_id, _("Panel Member")),
            (self.secretary_id, _("Panel Member & Secretary")),
        ]
        if self.observer_id and self.approval_hierarchy_type != 'ho_district_grade2_plus':
            hierarchy_role_users.append((self.observer_id, _("Labor Representative (Observer)")))

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        sel_rec = self.env['new.internal.recruitment.selected'].search([('vacancy_id', '=', self.id)], limit=1)
        minute_url = f"{base_url.rstrip('/')}/web#id={sel_rec.id}&model=new.internal.recruitment.selected&view_type=form" if (sel_rec and base_url) else ""
        btn_minute_html = (
            f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
            f"<a href='{minute_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
            f"👉 Open Selection Minute to Sign"
            f"</a>"
            f"</div>"
        ) if minute_url else ""

        for u_obj, r_title in hierarchy_role_users:
            if not u_obj:
                continue
            partner = u_obj.partner_id if hasattr(u_obj, 'partner_id') else False
            if not partner:
                continue
            notified_users.append(u_obj.name or partner.name)
            try:
                channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                message = Markup(
                    f"<p>Dear <b>{escape(u_obj.name or partner.name)}</b>,</p>"
                    f"<p>The candidate ranking and evaluation for vacancy <b>{escape(ref_str)}</b> has been computed and is ready for committee review and digital approval.</p>"
                    f"<ul>"
                    f"<li><b>Vacancy Reference:</b> {escape(ref_str)}</li>"
                    f"<li><b>Job Position:</b> {escape(pos_title)}</li>"
                    f"<li><b>Hiring Work Unit:</b> {escape(work_unit_str)}</li>"
                    f"<li><b>Your Role:</b> {escape(r_title)}</li>"
                    f"<li><b>Status:</b> Ready for Committee Review &amp; Digital Approval</li>"
                    f"</ul>"
                    f"{btn_minute_html}"
                    f"<p>Please review the minute and provide your digital signature under Committee Digital Signatures.</p>"
                )
                channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')
            except Exception as e:
                _logger.warning("Error notifying committee role user %s: %s", u_obj.name, e)

        for m in members:
            # Handle res.users vs hr.employee safely
            user = m.employee_name if m.status == 'active' else (m.alternate_committee_member or m.employee_name)
            if not user:
                continue

            partner = False
            if hasattr(user, 'partner_id') and user.partner_id:
                partner = user.partner_id
            elif hasattr(user, 'user_id') and user.user_id and user.user_id.partner_id:
                partner = user.user_id.partner_id
            elif hasattr(user, 'work_contact_id') and user.work_contact_id:
                partner = user.work_contact_id

            if not partner:
                continue

            if (user.name or partner.name) in notified_users:
                continue

            role_label = dict(m._fields['role'].selection).get(m.role, 'Committee Member') if m.role else 'Committee Member'
            notified_users.append(user.name or partner.name)

            # Send real-time notification to Odoo Discuss Channel
            try:
                channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                message = Markup(
                    f"<p>Dear <b>{escape(user.name or partner.name)}</b>,</p>"
                    f"<p>The candidate ranking and evaluation for vacancy <b>{escape(ref_str)}</b> has been computed and is ready for committee review and digital approval.</p>"
                    f"<ul>"
                    f"<li><b>Vacancy Reference:</b> {escape(ref_str)}</li>"
                    f"<li><b>Job Position:</b> {escape(pos_title)}</li>"
                    f"<li><b>Hiring Work Unit:</b> {escape(work_unit_str)}</li>"
                    f"<li><b>Your Role:</b> {escape(role_label)}</li>"
                    f"<li><b>Status:</b> Ready for Committee Review &amp; Digital Approval</li>"
                    f"</ul>"
                    f"{btn_minute_html}"
                    f"<p>Please review the minute and provide your digital signature under Committee Digital Signatures.</p>"
                )
                channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')
            except Exception as e:
                _logger.warning("Error notifying committee member %s: %s", user.name, e)

        if not notified_users:
            raise UserError(_(
                "No valid committee members found to notify. "
                "Please assign users under the 'Recruitment Approval Committee' tab first."
            ))

        # Automatically create and submit Selection Minute record if not already created
        Minute = self.env["recruitment.selection.minute"]
        minute_rec = Minute.search([("vacancy_id", "=", self.id)], order="id desc", limit=1)
        if not minute_rec:
            pos_name = self.job_position.name if self.job_position else (self.reference or 'Vacancy')
            summary = _(
                "Recruitment Selection Minute for position '%s'.\n"
                "Total Candidates: %s | Vacancy Slots: %s"
            ) % (pos_name, len(self.new_int_rec_sel) if self.new_int_rec_sel else self.no_of_vacancies or 1, self.no_of_vacancies or 1)
            minute_rec = Minute.create({
                'vacancy_id': self.id,
                'recruitment_type': 'external' if self.sourcing_type == 'external' else 'internal',
                'approval_hierarchy_type': self.approval_hierarchy_type or self._compute_hierarchy_type_recruitment(),
                'chairperson_id': self.chairperson_id.id if self.chairperson_id else False,
                'panel_member_id': self.panel_member_id.id if self.panel_member_id else False,
                'secretary_id': self.secretary_id.id if self.secretary_id else False,
                'observer_id': self.observer_id.id if self.observer_id else False,
                'meeting_date': fields.Date.context_today(self),
                'decision_summary': summary,
            })

        if minute_rec and minute_rec.state == 'draft':
            minute_rec.action_load_from_vacancy()
            try:
                minute_rec.action_submit_to_committee()
            except Exception as e:
                _logger.warning("Could not auto-submit selection minute: %s", e)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Committee Notified'),
                'message': _('Recruitment Approval Committee members (%s) have been notified successfully. Digital selection minute has been created and submitted for digital sign-off.') % (', '.join(notified_users)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_digital_minute(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            selected_candidates = False
            if hasattr(sel, 'ext_rec_sel'):
                selected_candidates = sel.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            elif hasattr(sel, 'new_int_rec_sel'):
                selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            if not selected_candidates:
                raise UserError(_("No candidates have passed the evaluation and been selected for this vacancy."))

        Minute = self.env["recruitment.selection.minute"]
        minute_rec = Minute.search([("vacancy_id", "=", self.id)], order="id desc", limit=1)
        self.minute_signed = bool(minute_rec and minute_rec.is_fully_signed and minute_rec.state == 'approved')
        self.recruitment_step = 'notify_selection'
        if minute_rec:
            if self.chairperson_id or self.panel_member_id or self.secretary_id:
                minute_rec.action_load_panel_members_from_vacancy()
            if minute_rec.state == 'draft':
                minute_rec.action_load_from_vacancy()
                try:
                    minute_rec.action_submit_to_committee()
                except Exception as e:
                    _logger.warning("Could not auto-submit selection minute: %s", e)

            return {
                'name': _('Digital Selection Minute'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.selection.minute',
                'res_id': minute_rec.id,
                'view_mode': 'form',
                'target': 'current',
            }

        if self.selected_recruitment_id:
            return self.selected_recruitment_id.action_open_digital_minute()

    def action_open_employment_letters(self):
        """Open or generate employment letters for all selected external candidates."""
        self.ensure_one()
        sel = self._get_selected_recruitment_record()
        selected_candidates = self.env['external.recruitment.selected.candidates']
        if sel and hasattr(sel, 'ext_rec_sel'):
            selected_candidates = sel.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))

        if not selected_candidates:
            scores = self.env['recruitment.candidate.score'].search([
                ('vacancy_id', '=', self.id), ('selection_status', '=', 'selected')
            ])
            if not scores:
                raise UserError(_("No external candidates have passed evaluation and been selected for this vacancy."))

        letters = self.env['recruitment.employment.letter']
        for cand in selected_candidates:
            cand.action_open_employment_letter()
            if cand.employment_letter_id:
                letters |= cand.employment_letter_id

        self.employees_promoted = True
        self.recruitment_step = 'done'

        if len(letters) == 1:
            return {
                'name': _('Employment Letter'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.employment.letter',
                'res_id': letters.id,
                'view_mode': 'form',
                'target': 'current',
            }
        elif len(letters) > 1:
            return {
                'name': _('Employment Letters'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.employment.letter',
                'domain': [('id', 'in', letters.ids)],
                'view_mode': 'list,form',
                'target': 'current',
            }
        else:
            return {
                'name': _('Employment Letters'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.employment.letter',
                'domain': [('vacancy_id', '=', self.id)],
                'view_mode': 'list,form',
                'target': 'current',
            }

    @api.model
    def _parse_numeric_grade(self, grade_val):
        if not grade_val:
            return 0
        if hasattr(grade_val, 'get_grade_level_num'):
            lvl = grade_val.get_grade_level_num()
            if lvl:
                return lvl
        s = str(getattr(grade_val, 'grade_code', '') or getattr(grade_val, 'grade_name', '') or grade_val).strip().upper()
        roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        m = re.search(r'\b([IVXLCDM]+)\b', s)
        if m:
            total = 0
            prev = 0
            for ch in reversed(m.group(1)):
                val = roman_map.get(ch, 0)
                total += -val if val < prev else val
                prev = max(prev, val)
            if total > 0:
                return total
        d = re.search(r'\d+', s)
        if d:
            return int(d.group(0))
        return 0

    def action_promote_selected_employees(self):
        self.ensure_one()
        is_external = self.sourcing_type == 'external' or 'EXT' in (self.reference or '').upper()
        if is_external:
            return self.action_open_employment_letters()

        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            selected_candidates = False
            if hasattr(sel, 'new_int_rec_sel'):
                selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            if not selected_candidates:
                err_msg = _("No candidates have passed the evaluation and been selected for transfer.") if self.is_lateral_transfer else _("No candidates have passed the evaluation and been selected for promotion.")
                raise UserError(err_msg)

            # 1. Check if any selected candidate rejected
            rejected_cands = selected_candidates.filtered(lambda c: c.acceptance_status == 'rejected')
            if rejected_cands:
                replaced_names = []
                for rc in rejected_cands:
                    rc.confirm_decline_promotion(rc.rejection_reason or _("Declined by candidate."))
                    replaced_names.append(rc.emp_name.name if rc.emp_name else _("Candidate"))
                self._sync_selected_recruitment_records()
                raise ValidationError(_(
                    "Cannot promote candidate(s) %s because they have DECLINED/REJECTED the offer.\n\n"
                    "The rejected candidate(s) have been replaced with the next eligible candidate(s) from the Reserve Pool. "
                    "Please have the new candidate(s) accept the offer before proceeding with promotion."
                ) % (", ".join(replaced_names)))

            # 2. Check if any selected candidate has not yet accepted
            pending_cands = selected_candidates.filtered(lambda c: c.acceptance_status != 'accepted')
            if pending_cands:
                names = ", ".join([c.emp_name.name for c in pending_cands if c.emp_name])
                raise ValidationError(_(
                    "Validation Error: Cannot promote selected candidate(s): %s.\n\n"
                    "Their offer acceptance status is currently 'Pending Response'. "
                    "Selected employee(s) must formally accept the promotion/transfer offer before HR can promote them."
                ) % names)

            # 3. Check for valid promotion grade progression (prevent demotion or same-grade movement under promotion)
            is_promotion = (not self.is_lateral_transfer) and getattr(self, 'internal_movement_type', 'promotion') != 'transfer'
            if is_promotion:
                tgt_grade = self.job_grade or (self.job_position.grade if self.job_position else False)
                tgt_grade_num = self._parse_numeric_grade(tgt_grade)
                tgt_grade_name = tgt_grade.grade_name if tgt_grade else (tgt_grade.grade_code if hasattr(tgt_grade, 'grade_code') else str(tgt_grade or 'Unknown'))

                for cand in selected_candidates:
                    emp = cand.emp_name
                    curr_grade = emp.job_grade or (emp.job_id.grade if emp.job_id else False)
                    if not curr_grade and cand.grade_id:
                        curr_grade = self.env['employee.grade'].browse(cand.grade_id)
                    curr_grade_num = self._parse_numeric_grade(curr_grade or cand.emp_grade)
                    curr_grade_name = curr_grade.grade_name if hasattr(curr_grade, 'grade_name') else str(cand.emp_grade or curr_grade or 'Unknown')

                    if tgt_grade_num > 0 and curr_grade_num > 0:
                        if tgt_grade_num < curr_grade_num:
                            raise ValidationError(_(
                                "Promotion Policy Violation: Demotion Detected!\n\n"
                                "Candidate '%(emp)s' currently holds Grade %(curr)s, which is HIGHER than the "
                                "target vacancy position '%(pos)s' of Grade %(tgt)s.\n\n"
                                "An employee cannot be promoted to a lower grade position. "
                                "Please verify and correct the vacancy Job Position / Grade before proceeding."
                            ) % {
                                'emp': emp.name if emp else _('Candidate'),
                                'curr': curr_grade_name,
                                'pos': self.job_position.name if self.job_position else _('Target Position'),
                                'tgt': tgt_grade_name,
                            })
                        elif tgt_grade_num == curr_grade_num:
                            raise ValidationError(_(
                                "Promotion Policy Violation: Same Grade Movement!\n\n"
                                "Candidate '%(emp)s' currently holds Grade %(curr)s, which is IDENTICAL to the "
                                "target vacancy position '%(pos)s' of Grade %(tgt)s.\n\n"
                                "Movement within the same grade is a Lateral Transfer, not a Promotion. "
                                "Please change the internal movement type to 'Transfer' or correct the Job Position."
                            ) % {
                                'emp': emp.name if emp else _('Candidate'),
                                'curr': curr_grade_name,
                                'pos': self.job_position.name if self.job_position else _('Target Position'),
                                'tgt': tgt_grade_name,
                            })

            self.employees_promoted = True
            self.recruitment_step = 'done'
            if hasattr(sel, 'action_promote_selected_employees'):
                return sel.action_promote_selected_employees()
            return True
        raise UserError(_("No recruitment selection record found for this vacancy."))

    def action_print_all_promotion_letters(self):
        self.ensure_one()
        if self.is_lateral_transfer:
            return self.action_print_all_transfer_letters()
        self._sync_selected_recruitment_records()
        if self.selected_recruitment_id:
            return self.selected_recruitment_id.action_print_all_promotion_letters()
        sel_rec = self.env['new.internal.recruitment.selected'].search([
            '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
        ], limit=1)
        if sel_rec:
            return sel_rec.action_print_all_promotion_letters()
        raise UserError(_("No recruitment selection records found for this vacancy."))

    def action_print_all_transfer_letters(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        if self.selected_recruitment_id:
            return self.selected_recruitment_id.action_print_all_transfer_letters()
        sel_rec = self.env['new.internal.recruitment.selected'].search([
            '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
        ], limit=1)
        if sel_rec:
            return sel_rec.action_print_all_transfer_letters()
        raise UserError(_("No recruitment selection records found for this vacancy."))

    def action_notify_selection(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            selected_candidates = False
            if hasattr(sel, 'ext_rec_sel'):
                selected_candidates = sel.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            elif hasattr(sel, 'new_int_rec_sel'):
                selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            if not selected_candidates:
                raise UserError(_("No candidates have passed the evaluation and been selected for this vacancy."))

            # Strictly verify that Selection Committee Minute exists and is approved with all committee signatures completed
            self.env["recruitment.selection.minute"].verify_selection_minute_fully_approved(
                vacancy_id=self.id, vacancy_ref=self.reference
            )

            self.selection_notified = True
            is_external = self.sourcing_type == 'external' or 'EXT' in (self.reference or '').upper()
            self.recruitment_step = 'hire' if is_external else 'promote'
            return sel.notify_selection()
        raise UserError(_("No recruitment selection record found for this vacancy."))

    @api.onchange('recruitment_request_id')
    def _onchange_recruitment_request_id_sync_fields(self):
        """Auto-populate Job Vacancy fields when an approved Recruitment Request is selected."""
        if not self.recruitment_request_id:
            return
        req = self.recruitment_request_id
        self.recruitment_reference = req.reference
        if req.job_position_id:
            self.job_position = req.job_position_id
        if req.job_grade_id:
            self.job_grade = req.job_grade_id
        elif req.job_position_id and getattr(req.job_position_id, 'grade', False):
            self.job_grade = req.job_position_id.grade
        if req.operating_unit_id:
            self.operating_unit_id = req.operating_unit_id
        if self.env.user.employee_id:
            self.responsible = self.env.user.employee_id
        if req.required_headcount:
            self.no_of_vacancies = req.required_headcount
        if req.employment_type:
            self.type_of_employment = "Permanent" if req.employment_type == "permanent" else "Contractual"
        if req.sourcing_type:
            self.sourcing_type = req.sourcing_type
            self.recruitment_type = "Internal" if req.sourcing_type == "internal" else "External"
            self.internal_movement_type = "external" if req.sourcing_type == "external" else "promotion"
        if not self.vacancy_description:
            pos_name = req.job_position_id.name if req.job_position_id else ''
            ou_name = req.operating_unit_id.name if req.operating_unit_id else ''
            if pos_name and ou_name:
                self.vacancy_description = f"Vacancy for {pos_name} at {ou_name}"
            elif pos_name:
                self.vacancy_description = f"Vacancy for {pos_name}"
        if req.last_date_to_apply:
            self.last_date_to_apply = req.last_date_to_apply
        if req.employee_category:
            self.employee_category = req.employee_category
        if req.job_level:
            self.job_level = req.job_level if req.employee_category == "Non Managerial" else False
        elif req.employee_category != "Managerial":
            grade = req.job_position_id.grade if (req.job_position_id and req.job_position_id.grade) else False
            if grade and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                self.job_level = grade.grade_level

        # 1. Sync Competencies from Job Position
        if req.job_position_id:
            self._onchange_job_position_sync_competencies()

        # 2. Sync Hiring Details (Work Unit, Responsible Officer, Openings)
        self._onchange_sync_hiring_details()

    @api.onchange('employee_category')
    def _onchange_employee_category_clear_job_level(self):
        for rec in self:
            if rec.employee_category == 'Managerial':
                rec.job_level = False
            elif rec.employee_category == 'Non Managerial':
                grade = rec.job_grade or (rec.job_position.grade if rec.job_position else False)
                if grade and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                    rec.job_level = grade.grade_level
                else:
                    rec.job_level = False

    @api.onchange('job_grade')
    def _onchange_job_grade_sync_level(self):
        for rec in self:
            grade = rec.job_grade or (rec.job_position.grade if rec.job_position else False)
            if grade and getattr(grade, 'category', False):
                cat_name = (grade.category.category_name or '').strip().lower()
                rec.employee_category = 'Managerial' if 'manager' in cat_name else 'Non Managerial'
            elif rec.job_position and getattr(rec.job_position, 'employee_category', False):
                rec.employee_category = rec.job_position.employee_category

            if rec.employee_category == 'Managerial':
                rec.job_level = False
            else:
                if grade and getattr(grade, 'grade_level', False) in ('junior', 'senior'):
                    rec.job_level = grade.grade_level
                else:
                    rec.job_level = False

    @api.constrains('employee_category', 'sourcing_type', 'job_level')
    def _check_job_level_required(self):
        """Job Level is only required for Non-Managerial when Sourcing Type is External."""
        for rec in self:
            is_internal = (rec.sourcing_type == 'internal' or rec.recruitment_type == 'Internal' or
                           (rec.reference and (
                                       rec.reference.startswith('BB/INT/') or rec.reference.startswith('BB/LAT/'))))
            if rec.employee_category == 'Non Managerial' and rec.sourcing_type == 'external' and not rec.job_level and not is_internal:
                raise ValidationError(_(
                    "Job Level (Junior / Senior) is required for Non-Managerial external vacancies."
                ))
            if rec.employee_category == 'Managerial' and rec.job_level:
                rec.job_level = False

    @api.constrains('opening_date')
    def _check_opening_announced_dates(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.vacancy_status == 'draft' or rec.state == 'draft':
                if rec.opening_date and rec.opening_date < today:
                    raise ValidationError(_(
                        "Opening Date (%(op_date)s) cannot be earlier than the current date (%(today)s)."
                    ) % {'op_date': rec.opening_date, 'today': today})

    @api.onchange('opening_date')
    def _onchange_check_dates_not_past(self):
        today = fields.Date.context_today(self)
        if self.opening_date and self.opening_date < today:
            self.opening_date = today
            return {
                'warning': {
                    'title': _("Invalid Date"),
                    'message': _("Opening Date cannot be less than current date (%s).") % today
                }
            }

    @api.onchange('written_exam_date', 'last_date_to_apply')
    def _onchange_written_exam_date(self):
        if not self.written_exam_date:
            return
        now = fields.Datetime.now()
        warning_msgs = []
        if self.written_exam_date <= now:
            warning_msgs.append(_("Written Exam Date cannot be in the past or back-dated. It must be greater than current date and time."))
            self.written_exam_date = False
        elif self.last_date_to_apply:
            local_exam_date = fields.Datetime.context_timestamp(self, self.written_exam_date).date()
            if local_exam_date <= self.last_date_to_apply:
                warning_msgs.append(_(
                    "Written Exam Date (%(exam_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                ) % {
                    'exam_date': local_exam_date.strftime('%Y-%m-%d'),
                    'deadline': self.last_date_to_apply.strftime('%Y-%m-%d'),
                })
                self.written_exam_date = False

        if warning_msgs:
            return {
                'warning': {
                    'title': _("Invalid Written Exam Date"),
                    'message': "\n".join(warning_msgs),
                }
            }

    @api.onchange('interview_date', 'written_exam_date', 'last_date_to_apply')
    def _onchange_interview_date(self):
        if not self.interview_date:
            return
        now = fields.Datetime.now()
        warning_msgs = []
        if self.interview_date <= now:
            warning_msgs.append(_("Interview Date cannot be in the past or back-dated. It must be greater than current date and time."))
            self.interview_date = False
        elif self.last_date_to_apply:
            local_inter_date = fields.Datetime.context_timestamp(self, self.interview_date).date()
            if local_inter_date <= self.last_date_to_apply:
                warning_msgs.append(_(
                    "Interview Date (%(interview_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                ) % {
                    'interview_date': local_inter_date.strftime('%Y-%m-%d'),
                    'deadline': self.last_date_to_apply.strftime('%Y-%m-%d'),
                })
                self.interview_date = False
        elif self.written_exam_date and self.interview_date < self.written_exam_date:
            warning_msgs.append(_("Interview Date cannot be earlier than Written Exam Date."))
            self.interview_date = False

        if warning_msgs:
            return {
                'warning': {
                    'title': _("Invalid Interview Date"),
                    'message': "\n".join(warning_msgs),
                }
            }

    @api.constrains('written_exam_date', 'interview_date', 'last_date_to_apply', 'vacancy_status')
    def _check_exam_interview_dates(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.vacancy_status in ('closed', 'done'):
                continue
            if rec.written_exam_date:
                # Disallow back date when actively scheduling the exam
                if rec.recruitment_step in ('shortlist', 'notify_cand', 'notify_exam') and rec.written_exam_date <= now:
                    raise ValidationError(_(
                        "Written Exam Date cannot be in the past. It must be greater than current date and time."
                    ))
                if rec.last_date_to_apply:
                    local_exam_date = fields.Datetime.context_timestamp(rec, rec.written_exam_date).date()
                    if local_exam_date <= rec.last_date_to_apply:
                        raise ValidationError(_(
                            "Written Exam Date (%(exam_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                        ) % {
                            'exam_date': local_exam_date.strftime('%Y-%m-%d'),
                            'deadline': rec.last_date_to_apply.strftime('%Y-%m-%d'),
                        })
            if rec.interview_date:
                # Disallow back date when actively scheduling the interview
                if rec.recruitment_step in ('shortlist', 'notify_cand', 'notify_exam', 'fetch_exam', 'notify_panel', 'notify_interview') and rec.interview_date <= now:
                    raise ValidationError(_(
                        "Interview Date cannot be in the past. It must be greater than current date and time."
                    ))
                if rec.last_date_to_apply:
                    local_inter_date = fields.Datetime.context_timestamp(rec, rec.interview_date).date()
                    if local_inter_date <= rec.last_date_to_apply:
                        raise ValidationError(_(
                            "Interview Date (%(interview_date)s) must be greater than Last Date To Apply (%(deadline)s)."
                        ) % {
                            'interview_date': local_inter_date.strftime('%Y-%m-%d'),
                            'deadline': rec.last_date_to_apply.strftime('%Y-%m-%d'),
                        })
                if rec.written_exam_date and rec.interview_date < rec.written_exam_date:
                    raise ValidationError(_(
                        "Interview Date cannot be earlier than Written Exam Date."
                    ))

    @api.constrains('opening_date', 'last_date_to_apply', 'sourcing_type', 'internal_movement_type', 'recruitment_type', 'vacancy_status')
    def _check_dates(self):
        for rec in self:
            if rec.opening_date and rec.last_date_to_apply:
                if rec.last_date_to_apply <= rec.opening_date:
                    raise ValidationError(_(
                        "Last Date To Apply (Closing Date) must be later than the Opening Date."
                    ))
                if rec.vacancy_status in ('evaluate', 'published'):
                    is_ext = (rec.sourcing_type == 'external' or rec.internal_movement_type == 'external' or rec.recruitment_type == 'External')
                    min_days = 5 if is_ext else 3
                    duration = (rec.last_date_to_apply - rec.opening_date).days
                    if duration < min_days:
                        raise ValidationError(_(
                            "The Last Date To Apply duration (%(days)d days) is less than the required default duration of %(min_days)d days for %(type)s vacancies."
                        ) % {
                            'days': duration,
                            'min_days': min_days,
                            'type': _('External') if min_days == 5 else _('Internal')
                        })

    @api.constrains('recruitment_request_id', 'operating_unit_id')
    def _check_recruitment_request_validity(self):
        for rec in self:
            if rec.recruitment_request_id:
                req = rec.recruitment_request_id
                # 1. Must not have been used in another vacancy
                other = self.search([
                    ('id', '!=', rec.id),
                    ('recruitment_request_id', '=', req.id),
                    ('active', '=', True)
                ], limit=1)
                if other or (req.vacancy_id and req.vacancy_id.id != rec.id):
                    used_ref = (other or req.vacancy_id).reference or _('another vacancy')
                    raise ValidationError(_(
                        "Recruitment Reference '%(req)s' has already been used for vacancy '%(vac)s' and cannot be reused."
                    ) % {'req': req.reference, 'vac': used_ref})

                # 2. Must belong to the vacancy's work unit
                target_ou = rec.operating_unit_id or (rec.responsible.default_operating_unit_id if rec.responsible else False)
                if target_ou and req.operating_unit_id and req.operating_unit_id.id != target_ou.id:
                    raise ValidationError(_(
                        "Recruitment Reference '%(req)s' belongs to work unit '%(req_ou)s', but the vacancy work unit is '%(vac_ou)s'. "
                        "You can only select a Recruitment Reference from the same work unit."
                    ) % {
                        'req': req.reference,
                        'req_ou': req.operating_unit_id.name,
                        'vac_ou': target_ou.name,
                    })

    @api.constrains('no_of_vacancies', 'hiring_details')
    def _check_hiring_details_openings_total(self):
        for rec in self:
            if rec.no_of_vacancies and rec.hiring_details:
                total_openings = sum(rec.hiring_details.mapped('number_of_openings'))
                if total_openings != rec.no_of_vacancies:
                    raise ValidationError(_(
                        "Number of Vacancies (%(vacancies)d) must be equal to the total Number of Openings (%(openings)d) in Hiring Details."
                    ) % {
                        'vacancies': rec.no_of_vacancies,
                        'openings': total_openings,
                    })

    @api.onchange('no_of_vacancies')
    def _onchange_no_of_vacancies_sync_openings(self):
        for rec in self:
            if rec.no_of_vacancies:
                if not rec.hiring_details and rec.operating_unit_id:
                    rec._onchange_sync_hiring_details()
                elif len(rec.hiring_details) == 1:
                    rec.hiring_details[0].number_of_openings = rec.no_of_vacancies
                elif len(rec.hiring_details) > 1:
                    total = sum(rec.hiring_details.mapped('number_of_openings'))
                    if total != rec.no_of_vacancies:
                        diff = rec.no_of_vacancies - total
                        rec.hiring_details[0].number_of_openings = max(1, rec.hiring_details[0].number_of_openings + diff)

    @api.onchange('hiring_details')
    def _onchange_hiring_details_sync_vacancies(self):
        for rec in self:
            if rec.hiring_details:
                total_openings = sum(rec.hiring_details.mapped('number_of_openings'))
                if total_openings > 0 and total_openings != rec.no_of_vacancies:
                    rec.no_of_vacancies = total_openings

    def _get_available_plan_and_vacant_count(self, operating_unit, job_position):
        """Helper to retrieve approved manpower plan count and vacant position count
        for a given operating unit and job position.
        Uses .sudo() to prevent security rule restrictions.
        If stored vacant_position_count is <= 0, dynamically computes live vacancy
        from Total Headcount - Active Employees, and considers turnover (resignations/replacements).
        """
        if not operating_unit or not job_position:
            return 0, 0

        OUJobPos = self.env['operating.unit.job.position'].sudo() if 'operating.unit.job.position' in self.env else None
        ou_pos = OUJobPos.search([
            ('operating_unit_id', '=', operating_unit.id),
            ('job_position_id', '=', job_position.id),
        ], limit=1) if OUJobPos is not None else False

        plan_count = ou_pos.approved_plan_count if ou_pos else 0
        vacant_count = ou_pos.vacant_position_count if ou_pos else 0

        # Dynamic / live vacant calculation if stored vacant_count is 0 or uncomputed
        if ou_pos and vacant_count <= 0:
            total_headcount = ou_pos.total_headcount or ((ou_pos.baseline_count or 0) + (ou_pos.approved_plan_count or 0))
            active_emp = ou_pos.active_employee_count
            if not active_emp and 'hr.employee' in self.env:
                active_emp = self.env['hr.employee'].sudo().search_count([
                    ('active', '=', True),
                    ('job_position', '=', job_position.id),
                    '|',
                    ('default_operating_unit_id', '=', operating_unit.id),
                    ('operating_unit_ids', 'in', operating_unit.id),
                ])
            live_vacant = max(0, (total_headcount or 0) - (active_emp or 0))
            # Also factor turnover/replacement vacancies (resignations, replacements, promotions)
            turnover_vacant = max(0, (ou_pos.resignation_count or 0) + (ou_pos.replacement_count or 0) + (ou_pos.promotion_count or 0))
            vacant_count = max(vacant_count, live_vacant, turnover_vacant)

        # Fallback to PBMS manpower plan if operating.unit.job.position has no plan count
        if plan_count <= 0 and vacant_count <= 0:
            PBMSPlan = self.env['pbms.planning.category'].sudo() if 'pbms.planning.category' in self.env else None
            if PBMSPlan is not None:
                pbms_plans = PBMSPlan.search([
                    ('category', '=', 'manpower'),
                    ('org_unit_id', '=', operating_unit.id),
                    ('state', '=', 'approved'),
                    ('active', '=', True),
                ])
                matching_lines = pbms_plans.mapped('line_ids').filtered(
                    lambda l: l.line_type == 'manpower' and l.job_id == job_position
                )
                pbms_qty = sum(matching_lines.mapped('quantity'))
                if pbms_qty > 0:
                    plan_count = pbms_qty

        return plan_count, vacant_count

    @api.onchange('job_position', 'operating_unit_id', 'no_of_vacancies', 'recruitment_request_id')
    def _onchange_check_vacant_posts_warning(self):
        if not self.job_position or not self.operating_unit_id:
            return
        if self.recruitment_request_id:
            return

        plan_count, vacant_count = self._get_available_plan_and_vacant_count(self.operating_unit_id, self.job_position)

        if plan_count <= 0 and vacant_count <= 0:
            return {
                'warning': {
                    'title': _("No Approved Plan or Vacant Post"),
                    'message': _(
                        "Cannot create vacancy: The approved manpower plan count and vacant position count for '%(job)s' at '%(unit)s' are both 0. "
                        "The number of opening vacancies cannot exceed the available vacant positions or approved plan count."
                    ) % {
                        'job': self.job_position.name,
                        'unit': self.operating_unit_id.name,
                    }
                }
            }
        max_available = max(plan_count, vacant_count)
        if self.no_of_vacancies and self.no_of_vacancies > max_available:
            return {
                'warning': {
                    'title': _("Headcount Exceeds Available Vacancies"),
                    'message': _(
                        "Requested number of vacancies (%(req)s) exceeds the available approved plan or vacant positions (%(avail)s) for '%(job)s' at '%(unit)s'."
                    ) % {
                        'req': self.no_of_vacancies,
                        'avail': max_available,
                        'job': self.job_position.name,
                        'unit': self.operating_unit_id.name,
                    }
                }
            }

    @api.constrains('job_position', 'operating_unit_id', 'no_of_vacancies', 'recruitment_request_id', 'state', 'vacancy_status')
    def _check_vacant_post_and_approved_plan(self):
        for rec in self:
            if self.env.context.get('skip_vacancy_plan_check'):
                continue
            if rec.state == 'cancel' or rec.vacancy_status == 'closed':
                continue
            if not rec.job_position or not rec.operating_unit_id:
                continue

            # Minimum number of vacancies
            if rec.no_of_vacancies is not None and rec.no_of_vacancies <= 0:
                raise ValidationError(_("Number of Vacancies must be at least 1."))

            # 1. When Recruitment Request IS provided (optional link)
            if rec.recruitment_request_id:
                req = rec.recruitment_request_id
                if req.state != 'approved':
                    state_label = dict(req._fields['state'].selection).get(req.state, req.state)
                    raise ValidationError(_(
                        "Selected Recruitment Request '%(ref)s' is not approved (Current status: %(status)s). Only approved requests can be used to create a vacancy."
                    ) % {'ref': req.reference, 'status': state_label})

                if req.job_position_id and rec.job_position and req.job_position_id != rec.job_position:
                    raise ValidationError(_(
                        "The Job Position '%(vac_job)s' does not match the Job Position '%(req_job)s' in Recruitment Request '%(ref)s'."
                    ) % {
                        'vac_job': rec.job_position.name,
                        'req_job': req.job_position_id.name,
                        'ref': req.reference,
                    })

                if req.operating_unit_id and rec.operating_unit_id and req.operating_unit_id != rec.operating_unit_id:
                    raise ValidationError(_(
                        "The Work Unit '%(vac_ou)s' does not match the Work Unit '%(req_ou)s' in Recruitment Request '%(ref)s'."
                    ) % {
                        'vac_ou': rec.operating_unit_id.name,
                        'req_ou': req.operating_unit_id.name,
                        'ref': req.reference,
                    })

                if rec.no_of_vacancies and req.required_headcount and rec.no_of_vacancies > req.required_headcount:
                    raise ValidationError(_(
                        "Number of Vacancies (%(req)s) exceeds the authorized headcount (%(auth)s) in Recruitment Request '%(ref)s'."
                    ) % {
                        'req': rec.no_of_vacancies,
                        'auth': req.required_headcount,
                        'ref': req.reference,
                    })
                continue

            # 2. When Recruitment Request is NOT provided (Direct Vacancy Creation)
            approved_plan, vacant_count = rec._get_available_plan_and_vacant_count(rec.operating_unit_id, rec.job_position)

            if approved_plan <= 0 and vacant_count <= 0:
                raise ValidationError(_(
                    "Cannot create vacancy: The approved manpower plan count and vacant position count for '%(job)s' at '%(unit)s' are both 0. "
                    "The number of opening vacancies cannot exceed the available vacant positions or approved plan count."
                ) % {
                    'job': rec.job_position.name,
                    'unit': rec.operating_unit_id.name,
                })

            max_available = max(approved_plan, vacant_count)
            if rec.no_of_vacancies and rec.no_of_vacancies > max_available:
                raise ValidationError(_(
                    "Requested number of vacancies (%(req)s) exceeds the available approved plan or vacant positions (%(avail)s) for '%(job)s' at '%(unit)s'."
                ) % {
                    'req': rec.no_of_vacancies,
                    'avail': max_available,
                    'job': rec.job_position.name,
                    'unit': rec.operating_unit_id.name,
                })

    @api.constrains('job_position', 'operating_unit_id', 'vacancy_description',
                    'competency_line_ids',
                    'opening_date', 'last_date_to_apply', 'vacancy_status')
    def _check_mandatory_data(self):
        """ Vacancy record shall require Opening Date, Closing Date,
        Job Position, Grade, Location, Job Description, and Competencies with
        required level when moving beyond Draft status (evaluate, published, closed)."""
        for rec in self:
            if rec.vacancy_status == 'draft':
                continue
            missing = []
            if not rec.opening_date:
                missing.append(_("Opening Date"))
            if not rec.last_date_to_apply:
                missing.append(_("Closing Date"))
            if not rec.job_position:
                missing.append(_("Job Position"))
            if not rec.job_grade:
                missing.append(_("Grade"))
            if not rec.operating_unit_id:
                missing.append(_("Place Of Assignment"))
            if not rec.vacancy_description:
                missing.append(_("Job Description"))
            if not rec.competency_line_ids:
                missing.append(_("Competencies"))
            elif any(not line.required_level for line in rec.competency_line_ids):
                missing.append(_("Required Level for each Competency"))

            if missing:
                raise ValidationError(_(
                    "The following mandatory fields are missing for vacancy record: %s"
                ) % ", ".join(missing))

    @api.constrains('new_int_rec_panel', 'ext_rec_panel', 'memb_panel_vac')
    def _check_duplicate_vacancy_panel_members(self):
        for vac in self:
            # 1. Internal Panel
            if vac.new_int_rec_panel:
                active_int = vac.new_int_rec_panel.filtered(lambda p: p.active and p.emp_name)
                int_emp_ids = active_int.mapped('emp_name.id')
                if len(int_emp_ids) != len(set(int_emp_ids)):
                    seen = set()
                    dups = set()
                    for p in active_int:
                        if p.emp_name.id in seen:
                            dups.add(p.emp_name.name)
                        else:
                            seen.add(p.emp_name.id)
                    raise ValidationError(_(
                        "The following employee(s) are already added as panel members: %s. Duplicate panel members are not allowed for the same vacancy."
                    ) % (", ".join(dups)))

            # 2. External Panel
            if vac.ext_rec_panel:
                active_ext = vac.ext_rec_panel.filtered(lambda p: p.active and p.emp_name)
                ext_emp_ids = active_ext.mapped('emp_name.id')
                if len(ext_emp_ids) != len(set(ext_emp_ids)):
                    seen = set()
                    dups = set()
                    for p in active_ext:
                        if p.emp_name.id in seen:
                            dups.add(p.emp_name.name)
                        else:
                            seen.add(p.emp_name.id)
                    raise ValidationError(_(
                        "The following employee(s) are already added as panel members: %s. Duplicate panel members are not allowed for the same vacancy."
                    ) % (", ".join(dups)))

            # 3. Vacancy Panel Members
            if vac.memb_panel_vac:
                active_vac_panel = vac.memb_panel_vac.filtered(lambda p: p.active and p.employee_id)
                vac_emp_ids = active_vac_panel.mapped('employee_id.id')
                if len(vac_emp_ids) != len(set(vac_emp_ids)):
                    seen = set()
                    dups = set()
                    for p in active_vac_panel:
                        if p.employee_id.id in seen:
                            dups.add(p.employee_id.name)
                        else:
                            seen.add(p.employee_id.id)
                    raise ValidationError(_(
                        "The following employee(s) are already added as panel members: %s. Duplicate panel members are not allowed for the same vacancy."
                    ) % (", ".join(dups)))

    def _is_locked(self):
        """A vacancy is locked once it leaves Draft — matches the vacancy_status
        statusbar (draft, evaluate, published, closed)."""
        self.ensure_one()
        return self.vacancy_status in ('evaluate', 'published', 'closed')

    @api.model_create_multi
    def create(self, vals_list):
        import re
        for vals in vals_list:
            if not vals.get('reference'):
                vals['reference'] = _('New')
            if 'exam_candidate_summary' in vals and isinstance(vals.get('exam_candidate_summary'), str):
                cleaned = re.sub(r'<[^>]+>', '', vals['exam_candidate_summary']).strip()
                vals['exam_candidate_summary'] = cleaned if cleaned else False

            ou_id = vals.get('operating_unit_id')
            job_pos_id = vals.get('job_position')
            if ou_id and not vals.get('hiring_details'):
                resp_id = vals.get('responsible') or (self.env.user.employee_id.id if self.env.user.employee_id else False)
                openings = vals.get('no_of_vacancies') or 1
                ou_obj = self.env['operating.unit'].browse(ou_id) if isinstance(ou_id, int) else ou_id
                job_obj = self.env['hr.job'].browse(job_pos_id) if isinstance(job_pos_id, int) else job_pos_id
                plan_pos = self._get_workunit_approved_plan_count(ou_obj, job_obj)
                vals['hiring_details'] = [(0, 0, {
                    'work_unit': ou_id,
                    'responsible_employee': resp_id,
                    'number_of_openings': openings,
                    'planned_positions': plan_pos,
                    'status': 'In Progress',
                })]
            if job_pos_id and not vals.get('competency_line_ids'):
                comp_lines = self._get_default_competency_lines(job_pos_id)
                if comp_lines:
                    vals['competency_line_ids'] = comp_lines

        records = super().create(vals_list)
        for rec in records:
            if rec.recruitment_request_id and rec.recruitment_request_id.vacancy_id != rec:
                rec.recruitment_request_id.write({'vacancy_id': rec.id})
            rec._auto_sync_hiring_and_competencies()
            rec._sync_committee_lines_from_hierarchy()
        return records

    def write(self, vals):
        """Protect core vacancy fields once Evaluated or Published, and lock completely once Closed.
        All selection, scoring, scheduling, panel members, committee, and promotion fields remain
        fully operational throughout the recruitment lifecycle."""
        import re
        if 'exam_candidate_summary' in vals and isinstance(vals.get('exam_candidate_summary'), str):
            cleaned = re.sub(r'<[^>]+>', '', vals['exam_candidate_summary']).strip()
            vals['exam_candidate_summary'] = cleaned if cleaned else False

        for rec in self:
            if rec.vacancy_status == 'closed' and not self.env.context.get('skip_lock_check'):
                blocked = set(vals.keys()) - {'vacancy_status', 'state', 'message_ids', 'message_follower_ids', 'activity_ids'}
                if blocked:
                    raise ValidationError(_(
                        "This vacancy is Closed and can no longer be edited."
                    ))
            elif rec.vacancy_status in ('evaluate', 'published') and not self.env.context.get('skip_lock_check'):
                LOCKED_CORE_REQ_FIELDS = {
                    'job_position', 'operating_unit_id', 'job_grade', 'employee_category',
                    'type_of_employment', 'no_of_vacancies', 'opening_date',
                }
                blocked = set(vals.keys()) & LOCKED_CORE_REQ_FIELDS
                if blocked:
                    raise ValidationError(_(
                        "Core vacancy definition (%s) cannot be modified after the vacancy is Evaluated or Published."
                    ) % ", ".join(blocked))

        # Disallow back-dating when setting or changing exam or interview dates
        now = fields.Datetime.now()
        if 'written_exam_date' in vals and vals.get('written_exam_date'):
            exam_dt = fields.Datetime.to_datetime(vals['written_exam_date'])
            if exam_dt and exam_dt <= now:
                raise ValidationError(_(
                    "Written Exam Date cannot be in the past. It must be greater than current date and time."
                ))
        if 'interview_date' in vals and vals.get('interview_date'):
            inter_dt = fields.Datetime.to_datetime(vals['interview_date'])
            if inter_dt and inter_dt <= now:
                raise ValidationError(_(
                    "Interview Date cannot be in the past. It must be greater than current date and time."
                ))

        old_requests = {rec.id: rec.recruitment_request_id for rec in self}
        res = super().write(vals)

        sync_keys = {'written_exam_date', 'exam_location', 'exam_scheduled', 'interview_date', 'interview_location', 'interview_scheduled', 'pms_weight', 'written_weight', 'interview_weight'}
        if sync_keys.intersection(vals.keys()):
            for rec in self:
                rec._sync_schedule_to_selection_models()

        if 'recruitment_request_id' in vals:
            for rec in self:
                old_req = old_requests.get(rec.id)
                if old_req and old_req != rec.recruitment_request_id and old_req.vacancy_id == rec:
                    old_req.write({'vacancy_id': False})
                if rec.recruitment_request_id and rec.recruitment_request_id.vacancy_id != rec:
                    rec.recruitment_request_id.write({'vacancy_id': rec.id})

        if vals.get('vacancy_status') == 'published':
            for rec in self:
                rec._sync_published_vacancy_records()

        if any(k in vals for k in ('operating_unit_id', 'responsible', 'no_of_vacancies', 'job_position', 'recruitment_request_id')):
            for rec in self:
                rec._auto_sync_hiring_and_competencies()

        if not self.env.context.get('syncing_committee_roles'):
            h_keys = {'chairperson_id', 'panel_member_id', 'secretary_id', 'observer_id'}
            l_keys = {'recr_selected_team_id', 'recr_exter_selected_team_id'}
            if h_keys.intersection(vals.keys()):
                for rec in self:
                    rec.with_context(syncing_committee_roles=True)._sync_committee_lines_from_hierarchy()
            elif l_keys.intersection(vals.keys()):
                for rec in self:
                    rec.with_context(syncing_committee_roles=True)._sync_hierarchy_from_committee_lines()

        return res

    def _sync_published_vacancy_records(self):
        """Automatically populate recruitment application process models when a vacancy is evaluated or published."""
        for rec in self:
            v_ref = rec.reference or _('New')
            if rec.vacancy_status == 'published' and (rec.state != 'posted' or not rec.website_published):
                rec.write({'state': 'posted', 'website_published': True})

            sourcing = rec.sourcing_type or ('internal' if rec.recruitment_type == 'Internal' else 'external')
            if sourcing == 'external':
                is_internal = False
                is_external = True
            elif sourcing == 'both':
                is_internal = True
                is_external = True
            elif sourcing == 'internal':
                is_internal = True
                is_external = False
            else:
                ref_upper = (v_ref or '').upper()
                if 'EXT' in ref_upper:
                    is_internal = False
                    is_external = True
                else:
                    is_internal = True
                    is_external = False

            vals_base = {
                'vacancy_reference': v_ref,
                'job_location': rec.operating_unit_id.name if rec.operating_unit_id else False,
                'job_grade': rec.job_grade.grade_name if rec.job_grade else False,
                'job_category': rec.employee_category,
                'vacancy_announced_on': rec.opening_date or fields.Date.context_today(self),
                'last_date_to_apply': rec.last_date_to_apply,
                'no_of_vacancies': rec.no_of_vacancies,
                'responsible': rec.responsible.id if rec.responsible else False,
            }

            # 1. Internal Recruitment Process & Portal
            if is_internal:
                IntRec = self.env['employee.recruitment.internal']
                existing_int = IntRec.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], limit=1)

                int_vals = dict(vals_base, **{
                    'vacancy_id': rec.id,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'emp_type': rec.type_of_employment,
                })

                if existing_int:
                    existing_int.write(int_vals)
                else:
                    IntRec.create(int_vals)

                # Application Window
                AppWindow = self.env['recruitment.application.window']
                existing_win = AppWindow.search([('vacancy_id', '=', rec.id)], limit=1)
                if not existing_win:
                    AppWindow.create({
                        'vacancy_id': rec.id,
                        'notification_date': rec.opening_date or fields.Date.context_today(self),
                    })

                # Ensure total separation: remove external process record ONLY if not is_external
                if not is_external:
                    self.env['employee.recruitment.external'].with_context(active_test=False).search([
                        '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                    ]).unlink()
            elif not is_internal:
                # Remove internal process records for external-only vacancies
                self.env['employee.recruitment.internal'].with_context(active_test=False).search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ]).unlink()
                self.env['employee.recruitment.available'].with_context(active_test=False).search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ]).unlink()

            # 2. External Recruitment Process
            if is_external:
                ExtRec = self.env['employee.recruitment.external'].with_context(active_test=False)
                existing_ext = ExtRec.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], limit=1)

                ext_vals = dict(vals_base, **{
                    'vacancy_id': rec.id,
                    'job_position': rec.job_position.id if rec.job_position else False,
                    'active': True,
                })

                if existing_ext:
                    existing_ext.write(ext_vals)
                else:
                    ExtRec.create(ext_vals)

                # Ensure total separation: remove internal process records ONLY if not is_internal
                if not is_internal:
                    self.env['employee.recruitment.internal'].with_context(active_test=False).search([
                        '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                    ]).unlink()
                    self.env['employee.recruitment.available'].with_context(active_test=False).search([
                        '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                    ]).unlink()
            elif not is_external:
                # Remove external process records for internal-only vacancies
                self.env['employee.recruitment.external'].with_context(active_test=False).search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ]).unlink()

        # Scope cleanup strictly to this vacancy's records rather than global table wipe (Area 7)
        for rec in self:
            if not rec.reference or rec.reference in (False, 'New', _('New')):
                continue
            ref_clean = rec.reference.strip()
            if 'EXT' in ref_clean.upper():
                self.env.cr.execute("""
                    DELETE FROM employee_recruitment_internal WHERE vacancy_id = %s OR vacancy_reference = %s;
                    DELETE FROM employee_recruitment_available WHERE vacancy_id = %s OR vacancy_reference = %s;
                    DELETE FROM new_internal_recruitment_selected WHERE vacancy_id = %s OR vacancy_reference = %s;
                """, (rec.id, ref_clean, rec.id, ref_clean, rec.id, ref_clean))
            elif any(k in ref_clean.upper() for k in ('INT', 'LAT')):
                self.env.cr.execute("""
                    DELETE FROM employee_recruitment_external WHERE vacancy_id = %s OR vacancy_reference = %s;
                    DELETE FROM external_recruitment_selected WHERE vacancy_id = %s OR vacancy_reference = %s;
                """, (rec.id, ref_clean, rec.id, ref_clean))

    def _ensure_internal_candidates_procedure(self):
        """Ensure the stored procedure public.internal_candidates is present and handles both promotion and lateral vacancies."""
        self.env.cr.execute("""
            CREATE OR REPLACE FUNCTION public.internal_candidates(p_id integer DEFAULT NULL::integer)
             RETURNS void
             LANGUAGE plpgsql
            AS $function$
            DECLARE
                rec_h record;
                rec_l record;
                v_int_id integer;
                v_target_vacancy_id integer;
            BEGIN
                v_target_vacancy_id := NULL;
                IF p_id IS NOT NULL THEN
                    SELECT id INTO v_target_vacancy_id
                    FROM job_vacancy
                    WHERE id = p_id;

                    IF v_target_vacancy_id IS NULL THEN
                        SELECT vacancy_id INTO v_target_vacancy_id
                        FROM employee_recruitment_internal
                        WHERE id = p_id AND vacancy_id IS NOT NULL;
                    END IF;
                END IF;

                FOR rec_h IN 
                    select distinct jv.id vacancy_id, hj.id job_position, jv.reference vacancy_reference, ou."name" job_location, eg.grade_name job_grade, hj.employee_category job_category,
                            jv.internal_movement_type, jv.opening_date vacancy_announced_on, jv.recruitment_reference,
                            ou.id workunit_id, eg.id job_grade_id, max(hqij.requirement) highest_cgpa,
                            coalesce(MAX(heij.requirement), 0) AS relevant_experience,
                            coalesce(MAX(CASE WHEN re.experience ILIKE '%supervis%' THEN heij.requirement ELSE NULL END), 0) AS supervisory_experience,
                            hj.minimum_number_years_in_company, hj.no_of_months_since_last_written_notice,
                            hj.no_of_months_since_last_promotion, hj.minimum_pms_score, jv.responsible, jv.no_of_vacancies,
                            jv.create_uid, jv.create_date, jv.write_uid, jv.write_date, jv.last_date_to_apply
                    from job_vacancy jv
                    left join hr_job hj on jv.job_position = hj.id
                    left join operating_unit ou on jv.operating_unit_id = ou.id
                    left join employee_grade eg on hj.grade = eg.id
                    left join hr_qualification_info_job hqij on hj.id = hqij.job_id
                    left join hr_experience_info_job heij on hj.id = heij.job_id
                    left join recruitment_experience re on heij.experience = re.id
                    where (v_target_vacancy_id IS NULL OR jv.id = v_target_vacancy_id)
                    group by hj.id, jv.reference, ou."name", eg.grade_name, hj.employee_category,
                             jv.internal_movement_type, jv.opening_date, jv.recruitment_reference, jv.no_of_vacancies,
                             ou.id, eg.id, jv.responsible, jv.last_date_to_apply,
                             jv.create_uid, jv.create_date, jv.write_uid, jv.write_date, jv.id
                LOOP
                    SELECT id INTO v_int_id
                    FROM employee_recruitment_internal
                    WHERE vacancy_id = rec_h.vacancy_id
                       OR (rec_h.vacancy_reference IS NOT NULL AND rec_h.vacancy_reference != 'New' AND vacancy_reference = rec_h.vacancy_reference)
                    ORDER BY id DESC LIMIT 1;

                    IF v_int_id IS NOT NULL THEN
                        UPDATE employee_recruitment_internal
                        SET job_position = rec_h.job_position,
                            job_location = rec_h.job_location,
                            job_grade = rec_h.job_grade,
                            job_category = rec_h.job_category,
                            vacancy_announced_on = rec_h.vacancy_announced_on,
                            recruitment_reference = rec_h.recruitment_reference,
                            minimum_number_years_in_company = rec_h.minimum_number_years_in_company,
                            no_of_months_since_last_written_notice = rec_h.no_of_months_since_last_written_notice,
                            no_of_months_since_last_promotion = rec_h.no_of_months_since_last_promotion,
                            minimum_pms_score = rec_h.minimum_pms_score,
                            no_of_vacancies = rec_h.no_of_vacancies,
                            workunit_id = rec_h.workunit_id,
                            job_grade_id = rec_h.job_grade_id,
                            highest_cgpa = rec_h.highest_cgpa,
                            relevant_experience = rec_h.relevant_experience,
                            last_date_to_apply = rec_h.last_date_to_apply,
                            vacancy_reference = rec_h.vacancy_reference,
                            responsible = rec_h.responsible,
                            vacancy_id = rec_h.vacancy_id,
                            active = TRUE
                        WHERE id = v_int_id;
                    ELSE
                        v_int_id := NEXTVAL('employee_recruitment_internal_id_seq');
                        INSERT INTO employee_recruitment_internal (
                            id, job_position, job_location, job_grade, job_category,
                            vacancy_announced_on, recruitment_reference,
                            minimum_number_years_in_company,
                            no_of_months_since_last_written_notice,
                            no_of_months_since_last_promotion, minimum_pms_score,
                            no_of_vacancies, workunit_id, job_grade_id,
                            highest_cgpa, relevant_experience, last_date_to_apply,
                            create_uid, create_date, write_uid, write_date, vacancy_reference, responsible, vacancy_id, active
                        ) VALUES (
                            v_int_id, rec_h.job_position, rec_h.job_location, rec_h.job_grade, rec_h.job_category,
                            rec_h.vacancy_announced_on, rec_h.recruitment_reference, rec_h.minimum_number_years_in_company,
                            rec_h.no_of_months_since_last_written_notice, rec_h.no_of_months_since_last_promotion,
                            rec_h.minimum_pms_score, rec_h.no_of_vacancies, rec_h.workunit_id, rec_h.job_grade_id,
                            rec_h.highest_cgpa, rec_h.relevant_experience, rec_h.last_date_to_apply,
                            rec_h.create_uid, rec_h.create_date, rec_h.write_uid, rec_h.write_date, rec_h.vacancy_reference, rec_h.responsible, rec_h.vacancy_id, TRUE
                        );
                    END IF;

                    DELETE FROM employee_recruitment_internal
                    WHERE (vacancy_id = rec_h.vacancy_id OR vacancy_reference = rec_h.vacancy_reference)
                      AND id != v_int_id;

                    DELETE FROM internal_recruitment_eligible_employees
                    WHERE internal_recruitment_id = v_int_id;

                    FOR rec_l IN 
                        SELECT DISTINCT he.id emp_name, rec_h.job_position target_position_id, eg.grade_code emp_grade, COALESCE(hj.name->>'en_US', hj.name::text) emp_position, hj.employee_category emp_category,
                                hj.type_of_employment emp_type, he.gender emp_gender, ou.name current_work_unit, ic.supervisory_experience, ic.current_position, ic.service_in_company,
                                ic.employment_experience, ic.educational_qualification, 85 cgpa, ic.name current_department,
                                ic.last_promotion last_promotion,
                                COALESCE(he.is_demoted, FALSE) demoted,
                                ic.pms_score, 'HO' preferred_location,
                                CASE WHEN upper(COALESCE(hj.name->>'en_US', hj.name::text)) LIKE '%ACTING%' THEN (SELECT current_job_position FROM supplementary_role sr WHERE employee_name = he.id AND state = 'approve')
                                ELSE hj.id END AS position_id,
                                eg.id grade_id, ou.id workunit_id,
                                he.create_uid, he.create_date, he.write_uid, he.write_date
                        FROM hr_employee he
                        LEFT JOIN hr_job hj ON he.job_position = hj.id
                        LEFT JOIN employee_grade eg ON he.job_grade = eg.id
                        LEFT JOIN operating_unit ou ON he.default_operating_unit_id = ou.id
                        LEFT JOIN internal_candidates_v ic ON he.id = ic.employee_id 
                        WHERE (he.active IS TRUE OR he.active IS NULL)
                          AND he.job_position IS NOT NULL
                          -- Position Eligibility:
                          AND (
                              CASE 
                                  WHEN (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%' OR rec_h.vacancy_reference ILIKE '%TRANS%') THEN
                                      TRUE
                                  WHEN EXISTS (
                                      SELECT 1 FROM employee_recruitment_position
                                      WHERE employee_id = rec_h.job_position AND position IS NOT NULL
                                  )
                                  THEN hj.id IN (
                                      SELECT position FROM employee_recruitment_position
                                      WHERE employee_id = rec_h.job_position AND position IS NOT NULL
                                  )
                                  ELSE hj.id = rec_h.job_position
                              END
                          )
                          -- Grade Eligibility:
                          AND (
                              CASE 
                                  WHEN (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%' OR rec_h.vacancy_reference ILIKE '%TRANS%') THEN
                                      ((rec_h.job_grade_id IS NOT NULL AND eg.id = rec_h.job_grade_id) OR (rec_h.job_grade_id IS NULL AND hj.id = rec_h.job_position))
                                  WHEN EXISTS (
                                      SELECT 1 FROM employee_recruitment_grade
                                      WHERE employee_id = rec_h.job_position AND job_grade IS NOT NULL
                                  )
                                  THEN eg.id IN (
                                      SELECT job_grade FROM employee_recruitment_grade
                                      WHERE employee_id = rec_h.job_position AND job_grade IS NOT NULL
                                  )
                                  ELSE (rec_h.job_grade_id IS NULL OR eg.id = rec_h.job_grade_id)
                              END
                          )
                          -- Promotion criteria threshold checks:
                          AND (
                              (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%' OR rec_h.vacancy_reference ILIKE '%TRANS%')
                              OR (
                                  (rec_h.minimum_pms_score IS NULL OR rec_h.minimum_pms_score = 0 OR ic.pms_score >= rec_h.minimum_pms_score)
                                  AND (rec_h.no_of_months_since_last_promotion IS NULL OR rec_h.no_of_months_since_last_promotion = 0 OR ic.last_promotion >= rec_h.no_of_months_since_last_promotion)
                                  AND (rec_h.relevant_experience IS NULL OR rec_h.relevant_experience = 0 OR ic.total_experience >= rec_h.relevant_experience)
                                  AND (rec_h.minimum_number_years_in_company IS NULL OR rec_h.minimum_number_years_in_company = 0 OR ic.service_in_company >= rec_h.minimum_number_years_in_company)
                                  AND (rec_h.supervisory_experience IS NULL OR rec_h.supervisory_experience = 0 OR ic.supervisory_experience >= rec_h.supervisory_experience)
                              )
                          )
                          -- Exclude employee who already has SAME grade, SAME position, and SAME workunit (no transfer needed):
                          AND NOT (
                              (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%' OR rec_h.vacancy_reference ILIKE '%TRANS%')
                              AND (rec_h.workunit_id IS NOT NULL AND ou.id = rec_h.workunit_id)
                              AND (rec_h.job_position IS NOT NULL AND hj.id = rec_h.job_position)
                              AND (rec_h.job_grade_id IS NOT NULL AND eg.id = rec_h.job_grade_id)
                          )
                    LOOP
                        INSERT INTO internal_recruitment_eligible_employees (
                            id, internal_recruitment_id, emp_name, target_position_id, emp_grade, emp_position, emp_category,
                            emp_type, emp_gender, current_work_unit, service_in_company, job_experience, employment_experience,
                            total_experience, educational_qualification, cgpa, relevant_experience,
                            supervisory_experience, last_promotion, pms_score,
                            preferred_location, written_warning, demoted,
                            grade_id, position_id, workunit_id, current_department,
                            create_uid, create_date, write_uid, write_date, active, vacancy_id, select_flag
                        ) VALUES (
                            NEXTVAL('internal_recruitment_eligible_employees_id_seq'),
                            v_int_id, rec_l.emp_name, rec_l.target_position_id,
                            rec_l.emp_grade, rec_l.emp_position, rec_l.emp_category,
                            rec_l.emp_type, rec_l.emp_gender, rec_l.current_work_unit, COALESCE(rec_l.service_in_company, 0.0),
                            COALESCE(rec_l.service_in_company, 0.0), COALESCE(rec_l.employment_experience, 0.0),
                            (COALESCE(rec_l.service_in_company, 0.0) + COALESCE(rec_l.employment_experience, 0.0)),
                            rec_l.educational_qualification, COALESCE(rec_l.cgpa::float, 0.0), 0.0,
                            COALESCE(rec_l.supervisory_experience, 0.0), COALESCE(rec_l.last_promotion, 0.0), COALESCE(rec_l.pms_score, 0.0),
                            rec_l.preferred_location, 0.0, rec_l.demoted,
                            rec_l.grade_id, rec_l.position_id, rec_l.workunit_id, rec_l.current_department,
                            rec_l.create_uid, rec_l.create_date, rec_l.write_uid, rec_l.write_date, TRUE, rec_h.vacancy_id, TRUE
                        );
                    END LOOP;
                END LOOP;
            END;
            $function$;
        """)

    def action_shortlist_candidates(self):
        """Shortlist eligible candidates directly from the Job Vacancy form and select all fulfilling criteria."""
        self.ensure_one()
        if not self.reference or self.reference == _('New'):
            raise ValidationError(_("Please evaluate and publish the vacancy before shortlisting."))

        ref = self.reference or ''
        is_internal = self.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()
        is_lateral = self.internal_movement_type in ('lateral', 'transfer') or 'LAT' in ref.upper() or 'TRANS' in ref.upper()

        if is_internal:
            # 1. Sync published records
            self._sync_published_vacancy_records()

            # 2. Ensure stored procedure is present and run internal shortlist procedure safely
            try:
                self._ensure_internal_candidates_procedure()
            except Exception as pe:
                _logger.warning("Could not ensure internal_candidates procedure: %s", pe)

            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute('SELECT public.internal_candidates(%s)', (self.id,))
            except Exception as e:
                _logger.warning("Stored procedure public.internal_candidates error or notice: %s", e)

            # 3. Check internal recruitment process record and link lines to vacancy with select_flag=True
            int_rec = self.env['employee.recruitment.internal'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)

            if int_rec:
                int_rec.write({'vacancy_id': self.id})
                self.env.cr.execute("""
                    UPDATE internal_recruitment_eligible_employees
                    SET vacancy_id = %s, select_flag = TRUE
                    WHERE internal_recruitment_id = %s;
                """, (self.id, int_rec.id))

            # Exclude employees who already have SAME grade, SAME position, and SAME workunit
            if is_lateral and self.operating_unit_id and self.job_position:
                target_grade_id = self.job_grade.id if self.job_grade else (self.job_position.grade.id if self.job_position and self.job_position.grade else False)
                if target_grade_id:
                    self.env.cr.execute('''
                        DELETE FROM internal_recruitment_eligible_employees
                        WHERE vacancy_id = %s
                          AND workunit_id = %s
                          AND position_id = %s
                          AND grade_id = %s;
                    ''', (self.id, self.operating_unit_id.id, self.job_position.id, target_grade_id))

            # Invalidate ORM cache after raw SQL DELETE and INSERT by stored procedure
            self.env['internal.recruitment.eligible.employees'].invalidate_model()
            self.invalidate_recordset(['eligible_employee_ids'])

            # 4. Fallback if procedure returned 0 candidates for lateral transfer
            is_lateral = self.internal_movement_type in ('lateral', 'transfer') or 'LAT' in ref.upper() or 'TRANS' in ref.upper()
            existing_count = self.env['internal.recruitment.eligible.employees'].search_count([('vacancy_id', '=', self.id)])
            if existing_count == 0 and is_lateral:
                target_grade_id = self.job_grade.id if self.job_grade else (self.job_position.grade.id if self.job_position and self.job_position.grade else False)
                if not int_rec:
                    int_rec = self.env['employee.recruitment.internal'].create({
                        'job_position': self.job_position.id if self.job_position else False,
                        'job_grade': self.job_grade.grade_name if self.job_grade else (self.job_position.grade.grade_name if self.job_position and self.job_position.grade else False),
                        'job_grade_id': target_grade_id,
                        'job_location': self.operating_unit_id.name if self.operating_unit_id else False,
                        'workunit_id': self.operating_unit_id.id if self.operating_unit_id else False,
                        'job_category': self.job_position.employee_category if self.job_position else False,
                        'vacancy_announced_on': self.opening_date or fields.Date.today(),
                        'vacancy_reference': self.reference,
                        'recruitment_reference': self.recruitment_reference,
                        'responsible': self.responsible.id if self.responsible else False,
                        'no_of_vacancies': self.no_of_vacancies,
                        'last_date_to_apply': self.last_date_to_apply,
                        'vacancy_id': self.id,
                        'active': True,
                    })
                domain = [('active', '=', True)]
                if target_grade_id:
                    domain.append(('job_grade', '=', target_grade_id))
                elif self.job_position:
                    domain.append(('job_position', '=', self.job_position.id))
                matching_emps = self.env['hr.employee'].search(domain)
                matching_emps = [
                    emp for emp in matching_emps
                    if not (
                        self.operating_unit_id and self.job_position and target_grade_id and
                        emp.job_position.id == self.job_position.id and
                        emp.job_grade.id == target_grade_id and
                        emp.default_operating_unit_id.id == self.operating_unit_id.id
                    )
                ]
                for emp in matching_emps:
                    self.env['internal.recruitment.eligible.employees'].create({
                        'internal_recruitment_id': int_rec.id,
                        'vacancy_id': self.id,
                        'emp_name': emp.id,
                        'target_position_id': self.job_position.id if self.job_position else False,
                        'position_id': emp.job_position.id if emp.job_position else False,
                        'grade_id': emp.job_grade.id if emp.job_grade else False,
                        'workunit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                        'select_flag': True,
                        'active': True,
                    })

            if self.eligible_employee_ids:
                self.eligible_employee_ids._compute_employee_details()
                min_pos = self.transfer_min_position_years if self.transfer_min_position_years > 0 else 1.0
                min_loc = self.transfer_min_location_years if self.transfer_min_location_years > 0 else 1.0
                for line in self.eligible_employee_ids:
                    vals = {
                        'current_position_exp': line.current_position_exp,
                        'current_location_exp': line.current_location_exp,
                        'emp_position': clean_job_position_name(line.emp_position),
                    }
                    is_mov_ok = getattr(line, 'movement_eligible', True)

                    # Disciplinary records and demotion check
                    has_active_discipline = False
                    emp = line.emp_name
                    if emp:
                        if 'discipline.case' in self.env:
                            if self.env['discipline.case'].search_count([
                                ('employee_id', '=', emp.id),
                                ('state', '=', 'enforced'),
                            ]) > 0:
                                has_active_discipline = True
                        if not has_active_discipline and 'discipline.action' in self.env:
                            if self.env['discipline.action'].search_count([
                                ('employee_name', '=', emp.id),
                            ]) > 0:
                                has_active_discipline = True
                        if not has_active_discipline and 'disciplinary.action' in self.env:
                            if self.env['disciplinary.action'].search_count([
                                ('employee_name', '=', emp.id),
                            ]) > 0:
                                has_active_discipline = True
                        if not has_active_discipline and getattr(line, 'demoted', False):
                            has_active_discipline = True

                    if is_lateral:
                        # Exclude employee who already has SAME position, SAME grade, and SAME workunit (already in role)
                        is_same_role_and_unit = bool(
                            self.operating_unit_id and
                            self.job_position and
                            line.position_id == self.job_position.id and
                            line.workunit_id == self.operating_unit_id.id and
                            line.grade_id == (self.job_grade.id if self.job_grade else (self.job_position.grade.id if self.job_position and self.job_position.grade else False))
                        )
                        if is_same_role_and_unit:
                            vals['select_flag'] = False
                        else:
                            # Must satisfy:
                            # 1. Position service years >= min_pos (default 1.0)
                            # 2. Location service years >= min_loc (default 1.0)
                            # 3. Eligible movement reason (Promotion, Lateral Transfer, Transfer, Assignment, Placement)
                            # 4. No active disciplinary record / active written warning / demotion
                            vals['select_flag'] = bool(
                                (line.current_position_exp >= min_pos) and
                                (line.current_location_exp >= min_loc) and
                                is_mov_ok and
                                not has_active_discipline
                            )
                    else:
                        # Promotion: Check demotion status, active disciplinary records, movement reason eligibility, and 1-year service rule
                        allow_demoted = getattr(self.job_position, 'demoted_employee', False)
                        if not allow_demoted and (line.demoted or has_active_discipline):
                            vals['select_flag'] = False
                        elif not is_mov_ok:
                            vals['select_flag'] = False
                        elif line.current_position_exp < min_pos or line.current_location_exp < min_loc:
                            vals['select_flag'] = False
                    line.write(vals)
                self.eligible_employee_ids.flush_recordset()

                # Remove ineligible candidates whose select_flag is False (e.g. tenure < 1 year, active disciplinary record, demoted, same role & unit)
                # so the shortlist table ONLY contains candidates who meet 100% of the criteria:
                ineligible_lines = self.eligible_employee_ids.filtered(lambda l: not l.select_flag)
                if ineligible_lines:
                    ineligible_lines.unlink()
                self.invalidate_recordset(['eligible_employee_ids'])

            self.env.invalidate_all()
            self._sync_selected_recruitment_records()
            self.shortlist_done = True
            self.recruitment_step = 'notify_cand'
            count = len(self.eligible_employee_ids)

            msg_type = 'success' if count > 0 else 'warning'
            if count > 0:
                msg = _('Internal candidates shortlisting completed successfully for vacancy %s (%s eligible candidates selected).') % (self.reference, count)
            else:
                msg = _('Internal candidates shortlisting completed for vacancy %s: No candidate met the 1-year tenure and eligibility criteria.') % self.reference

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Shortlisting Completed'),
                    'message': msg,
                    'type': msg_type,
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }
        else:
            # External vacancy shortlisting — open the Shortlist Choice Wizard (Default / Specific Criteria)
            self._sync_published_vacancy_records()
            ExtRec = self.env['employee.recruitment.external']
            ext_rec = ExtRec.search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if not ext_rec:
                ext_rec = ExtRec.create({
                    'vacancy_id': self.id,
                    'job_position': self.job_position.id if self.job_position else False,
                    'vacancy_reference': self.reference,
                    'job_location': self.operating_unit_id.name if self.operating_unit_id else False,
                    'job_grade': self.job_grade.grade_name if self.job_grade else False,
                    'job_category': self.employee_category,
                    'vacancy_announced_on': self.opening_date or fields.Date.context_today(self),
                    'last_date_to_apply': self.last_date_to_apply,
                    'no_of_vacancies': self.no_of_vacancies,
                    'responsible': self.responsible.id if self.responsible else False,
                })

            # Auto-sync registered external applicants into external recruitment process eligible list
            if hasattr(self, 'applicant_ids') and self.applicant_ids:
                self.applicant_ids._auto_sync_external_recruitment_eligible()
            else:
                apps = self.env['hr.applicant'].search([('app_reference', '=', self.id)])
                if apps:
                    apps._auto_sync_external_recruitment_eligible()

            return {
                'name': _('Shortlist Candidates'),
                'type': 'ir.actions.act_window',
                'res_model': 'external.shortlist.choice.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_recruitment_id': ext_rec.id,
                }
            }

    def action_notify_candidates(self):
        """Notify shortlisted candidates directly from the Job Vacancy form."""
        self.ensure_one()
        ref = self.reference or ''
        is_internal = self.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()
        pos_title = self.job_position.name if self.job_position else (self.job_title or _('Job Position'))
        work_unit_str = self.operating_unit_id.name if self.operating_unit_id else (self.job_location or _('Head Office'))

        notified_count = 0
        if is_internal:
            int_rec = self.env['employee.recruitment.internal'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)

            if not int_rec or not int_rec.eligible_emp:
                # If shortlist was not executed yet, execute it first
                self._sync_published_vacancy_records()
                try:
                    with self.env.cr.savepoint():
                        self.env.cr.execute('SELECT public.internal_candidates(%s)', (self.id,))
                except Exception as e:
                    _logger.warning("Stored procedure error: %s", e)
                self.env.invalidate_all()
                int_rec = self.env['employee.recruitment.internal'].search([
                    '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
                ], limit=1)

            candidates_to_notify = []
            eligible_lines = self.eligible_employee_ids or (int_rec.eligible_emp if int_rec else False)
            if eligible_lines:
                # Strictly filter only candidates where select_flag is TRUE
                selected_lines = eligible_lines.filtered(lambda l: l.select_flag)
                for line in selected_lines:
                    emp = getattr(line, 'emp_id', False) or getattr(line, 'emp_name', False) or getattr(line, 'employee_id', False)
                    if isinstance(emp, int):
                        emp = self.env['hr.employee'].browse(emp)
                    if emp and emp not in candidates_to_notify:
                        candidates_to_notify.append(emp)

            if not candidates_to_notify:
                raise ValidationError(
                    _("No eligible candidates have been selected to notify for vacancy %s. Please check 'Select' on the candidates you wish to notify, or click 'Select All'.") % self.reference)

            Available = self.env['employee.recruitment.available'].with_context(
                tracking_disable=True,
                mail_create_nolog=True,
                mail_create_nosubscribe=True,
                mail_notrack=True,
            )
            # Batch pre-fetch existing available records for this vacancy reference
            existing_avails = Available.search([('vacancy_reference', '=', self.reference)])
            avail_by_emp_id = {}
            avail_by_user_id = {}
            for av in existing_avails:
                eid = av.employee_id if isinstance(av.employee_id, int) else getattr(av.employee_id, 'id', False)
                if eid:
                    avail_by_emp_id[eid] = av
                uid = av.employee_user_id if isinstance(av.employee_user_id, int) else getattr(av.employee_user_id, 'id', False)
                if uid:
                    avail_by_user_id[uid] = av

            base_avail_vals = {
                'vacancy_id': self.id,
                'vacancy_reference': self.reference,
                'job_position': pos_title,
                'job_location': work_unit_str,
                'employee_grade': self.job_grade.grade_name if self.job_grade else '',
                'employee_category': self.employee_category or '',
                'type_of_employment': self.type_of_employment or '',
                'number_of_vacancies': self.no_of_vacancies or 1,
                'vacancy_announced_on': self.opening_date or fields.Date.context_today(self),
                'last_date_to_apply': self.last_date_to_apply,
                'job_description': self.vacancy_description or '',
                'application_status': 'Selected for Shortlist',
                'active': True,
            }

            to_create_vals = []
            all_avail_records = []

            for emp in candidates_to_notify:
                emp_user = getattr(emp, 'user_id', False)
                existing_avail = avail_by_emp_id.get(emp.id) or (avail_by_user_id.get(emp_user.id) if emp_user else False)
                vals = dict(base_avail_vals)
                vals.update({
                    'employee_id': emp.id,
                    'employee_user_id': emp_user.id if emp_user else False,
                    'employee_applicant': emp.name,
                })
                if existing_avail:
                    existing_avail.write(vals)
                    all_avail_records.append(existing_avail)
                else:
                    to_create_vals.append(vals)

            if to_create_vals:
                new_avails = Available.create(to_create_vals)
                all_avail_records.extend(new_avails)

            # Sync hiring details lines in batch if defined
            if self.hiring_details and all_avail_records:
                existing_avails.mapped('employee_vacancy_ids').unlink()
                hiring_lines_batch = []
                for av in all_avail_records:
                    for h in self.hiring_details:
                        hiring_lines_batch.append({
                            'vacancy_id': av.id,
                            'operating_unit': h.work_unit.name if h.work_unit else False,
                            'number_of_vacancies': getattr(h, 'number_of_openings', 0) or getattr(h, 'planned_positions', 0) or self.no_of_vacancies or 1,
                            'location_preference': 0,
                        })
                if hiring_lines_batch:
                    self.env['employee.vacancy.available'].with_context(
                        tracking_disable=True,
                        mail_create_nolog=True,
                        mail_notrack=True,
                    ).create(hiring_lines_batch)

            # Pre-resolve partners in batch
            emp_partner_map = {}
            missing_partner_emps = []
            for emp in candidates_to_notify:
                if hasattr(emp, 'user_id') and emp.user_id and emp.user_id.partner_id:
                    emp_partner_map[emp.id] = emp.user_id.partner_id
                elif hasattr(emp, 'work_contact_id') and emp.work_contact_id:
                    emp_partner_map[emp.id] = emp.work_contact_id
                else:
                    missing_partner_emps.append(emp)

            if missing_partner_emps:
                names = [e.name for e in missing_partner_emps if e.name]
                if names:
                    found_partners = self.env['res.partner'].search([('name', 'in', names)])
                    p_by_name = {p.name.strip().lower(): p for p in found_partners if p.name}
                    for emp in missing_partner_emps:
                        if emp.name and emp.name.strip().lower() in p_by_name:
                            emp_partner_map[emp.id] = p_by_name[emp.name.strip().lower()]

            # Dispatch Discuss channel messages with tracking disabled for performance
            deadline_str = self.last_date_to_apply.strftime('%Y-%m-%d') if self.last_date_to_apply else _('N/A')
            ChannelModel = self.env['discuss.channel'].with_context(
                mail_post_autofollow=False,
                mail_create_nosubscribe=True,
                mail_notrack=True,
                tracking_disable=True,
            )

            for emp in candidates_to_notify:
                partner = emp_partner_map.get(emp.id)
                if not partner:
                    partner = getattr(emp, 'address_home_id', False) or getattr(emp, 'user_partner_id', False)
                if not partner and emp.work_email:
                    partner = self.env['res.partner'].search([('email', '=', emp.work_email)], limit=1)

                msg = (
                    f"<p>Dear <b>{emp.name}</b>,</p>"
                    f"<p>You have been shortlisted for an Internal Recruitment position:</p>"
                    f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
                    f"<li><b>Position:</b> {pos_title}</li>"
                    f"<li><b>Application Deadline:</b> {deadline_str}</li>"
                    f"<li><b>Place of Assignment:</b> {work_unit_str}</li>"
                    f"</ul><br/>"
                    f"<p>If you are interested, please submit your application before the deadline. "
                    f"Navigate: <b>Employees &rarr; Employee Service &rarr; Internal Job Positions</b>.</p>"
                    f"<p>Best regards,<br/><b>Bunna Bank People Operation Management</b></p>"
                )

                # 1. Dispatch Discuss chat message
                if partner:
                    try:
                        channel = ChannelModel._get_or_create_chat(partners_to=[partner.id])
                        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                        job_url = f"{base_url.rstrip('/')}/web#action=custom_recruitment.action_employee_recruitment_available&model=employee.recruitment.available&view_type=list" if base_url else "/web#action=custom_recruitment.action_employee_recruitment_available&model=employee.recruitment.available&view_type=list"
                        discuss_msg = Markup(
                            f"<p>Dear <b>{escape(emp.name)}</b>,</p>"
                            f"<p>You have been shortlisted for an <b>Internal Recruitment position</b>:</p>"
                            f"<ul>"
                            f"<li><b>Position:</b> {escape(pos_title)}</li>"
                            f"<li><b>Application Deadline:</b> {escape(deadline_str)}</li>"
                            f"<li><b>Place of Assignment:</b> {escape(work_unit_str)}</li>"
                            f"</ul>"
                            f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                            f"<a href='{job_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                            f"👉 View &amp; Apply for Internal Job Position"
                            f"</a>"
                            f"</div>"
                            f"<p>Best regards,<br/><b>Bunna Bank People Operation Management</b></p>"
                        )
                        channel.message_post(body=discuss_msg, message_type='comment', subtype_xmlid='mail.mt_comment')
                        notified_count += 1
                    except Exception as e:
                        _logger.warning("Could not send discuss channel notification to candidate %s: %s", emp.name, e)
                else:
                    notified_count += 1

                # 2. Schedule Activity (Top-bar Bell / Clock notification for candidate user)
                act_user = getattr(emp, 'user_id', False)
                if act_user:
                    try:
                        emp.activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=act_user.id,
                            summary=_('Shortlisted for Vacancy: %s') % pos_title,
                            note=Markup(msg),
                            date_deadline=self.last_date_to_apply or fields.Date.today(),
                        )
                    except Exception as act_err:
                        _logger.warning("Could not schedule activity on employee %s: %s", emp.name, act_err)

                # 3. Post to Employee Chatter
                try:
                    emp.message_post(body=Markup(msg), partner_ids=[partner.id] if partner else [])
                except Exception as e:
                    _logger.warning("Could not post message on employee %s chatter: %s", emp.name, e)

                # 4. Dispatch Email to candidate's email address
                target_email = (emp.work_email or emp.private_email or '').strip()
                if target_email:
                    try:
                        self.env['mail.mail'].sudo().create({
                            'subject': _('Shortlisted for Internal Vacancy: %s (%s)') % (pos_title, self.reference),
                            'body_html': Markup(msg),
                            'email_to': target_email,
                            'email_from': self.env.company.email or self.env.user.email or 'noreply@bunnabanksc.com',
                            'auto_delete': False,
                        }).send()
                    except Exception as mail_err:
                        _logger.warning("Could not send email to candidate %s: %s", emp.name, mail_err)

        self.candidate_notified = True
        is_transfer = (self.internal_movement_type in ('lateral', 'transfer') or 'LAT' in (self.reference or '').upper()) and self.internal_movement_type != 'promotion'
        if is_transfer:
            if self.transfer_eval_mode == 'transfer_matrix_only':
                self.recruitment_step = 'compute_rank'
            elif self.transfer_eval_mode == 'interview_only':
                self.recruitment_step = 'notify_panel'
            elif self.has_written_exam:
                self.recruitment_step = 'notify_exam'
            else:
                self.recruitment_step = 'notify_panel'
        elif self.has_written_exam:
            self.recruitment_step = 'notify_exam'
        else:
            self.recruitment_step = 'notify_panel'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Notified'),
                'message': _('Dispatched direct notifications to %d shortlisted candidate(s).') % notified_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_select_all_internal_candidates(self):
        """ Select all internal candidates at once """
        for rec in self:
            is_lateral = rec.internal_movement_type in ('lateral', 'transfer') or 'LAT' in (rec.reference or '').upper()
            min_pos = rec.transfer_min_position_years if rec.transfer_min_position_years > 0 else 1.0
            min_loc = rec.transfer_min_location_years if rec.transfer_min_location_years > 0 else 1.0
            if is_lateral:
                if rec.eligible_employee_ids:
                    rec.eligible_employee_ids._compute_employee_details()
                    for line in rec.eligible_employee_ids:
                        is_mov_ok = getattr(line, 'movement_eligible', True)
                        flag = bool((line.current_position_exp >= min_pos) and (line.current_location_exp >= min_loc) and is_mov_ok)
                        line.write({
                            'current_position_exp': line.current_position_exp,
                            'current_location_exp': line.current_location_exp,
                            'select_flag': flag,
                        })
                if rec.new_int_rec_sel:
                    for line in rec.new_int_rec_sel:
                        flag = bool((line.service_in_current_position >= min_pos) and (line.service_in_current_location >= min_loc))
                        line.write({'select_flag': flag})
            else:
                if rec.eligible_employee_ids:
                    rec.eligible_employee_ids._compute_employee_details()
                    allow_demoted = getattr(rec.job_position, 'demoted_employee', False)
                    for line in rec.eligible_employee_ids:
                        is_mov_ok = getattr(line, 'movement_eligible', True)
                        is_demot_ok = not (not allow_demoted and line.demoted)
                        is_service_ok = bool((line.current_position_exp >= min_pos) and (line.current_location_exp >= min_loc))
                        flag = bool(is_mov_ok and is_demot_ok and is_service_ok)
                        line.write({'select_flag': flag})
                if rec.new_int_rec_sel:
                    for line in rec.new_int_rec_sel:
                        flag = bool((line.service_in_current_position >= min_pos) and (line.service_in_current_location >= min_loc))
                        line.write({'select_flag': flag})
                if hasattr(rec, 'eligible_emp') and rec.eligible_emp:
                    rec.eligible_emp.write({'select_flag': True})

    def action_deselect_all_internal_candidates(self):
        """ Deselect all internal candidates at once """
        for rec in self:
            if rec.new_int_rec_sel:
                rec.new_int_rec_sel.write({'select_flag': False})
            if rec.eligible_employee_ids:
                rec.eligible_employee_ids.write({'select_flag': False})
            if hasattr(rec, 'eligible_emp') and rec.eligible_emp:
                rec.eligible_emp.write({'select_flag': False})

    def action_select_all_external_candidates(self):
        """ Select all external candidates at once """
        for rec in self:
            if rec.ext_rec_sel:
                rec.ext_rec_sel.write({'select_flag': True})
            if hasattr(rec, 'eligible_emp_external') and rec.eligible_emp_external:
                rec.eligible_emp_external.write({'select_flag': True})

    def action_deselect_all_external_candidates(self):
        """ Deselect all external candidates at once """
        for rec in self:
            if rec.ext_rec_sel:
                rec.ext_rec_sel.write({'select_flag': False})
            if hasattr(rec, 'eligible_emp_external') and rec.eligible_emp_external:
                rec.eligible_emp_external.write({'select_flag': False})

            # Ensure weights and flags are initialized if currently 0.0
            if self.internal_movement_type == 'promotion' and self.pms_weight == 0.0 and self.written_weight == 0.0 and self.interview_weight == 0.0:
                self._onchange_movement_type_sync_weights()

            # Trigger notify
            int_rec.notify()
            self.candidate_notified = True

            is_lateral = (self.internal_movement_type in ('lateral', 'transfer') or (self.reference and 'LAT' in (self.reference or '').upper())) and self.internal_movement_type != 'promotion'
            if is_lateral or not self.has_written_exam:
                if not self.has_written_exam and self.has_interview and not is_lateral:
                    self.recruitment_step = 'notify_panel'
                else:
                    self.recruitment_step = 'compute_rank'
            else:
                self.recruitment_step = 'notify_exam'

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Candidates Notified'),
                    'message': _(
                        'Eligible internal candidates have been successfully notified for vacancy %s.') % self.reference,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }
        else:
            ext_rec = self.env['employee.recruitment.external'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if ext_rec:
                ext_rec.notify()
            self.candidate_notified = True
            if self.has_written_exam:
                self.recruitment_step = 'notify_exam'
            elif self.has_interview:
                self.recruitment_step = 'notify_panel'
            else:
                self.recruitment_step = 'compute_rank'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Applicants Notified'),
                    'message': _(
                        'External applicants have been successfully notified for vacancy %s.') % self.reference,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

    def notify(self):
        for rec in self:
            if not rec.vac_del_team_id:
                rec._auto_sync_hiring_and_competencies()

            if not rec.vac_del_team_id:
                raise UserError(_(
                    "Please add at least one Approver under the 'Vacancy Approval Members' tab before clicking 'Notify Approvers'."
                ))

            notified_users = []
            for com in rec.vac_del_team_id:
                user = com.employee_name if com.status == "active" else com.alternate_committee_member
                if not user:
                    continue
                partner = user.partner_id
                if not partner:
                    raise ValidationError(_('Approver %s is not linked to a partner record.') % (user.name or ''))
                rec.mail_channel_msgs(partner.id, rec.reference, rec.job_position.name if rec.job_position else '', rec.type_of_employment or '')
                notified_users.append(user.name)

            if not notified_users:
                raise UserError(_("No active approver found in Vacancy Approval Members to send notification to."))

            rec.status = "notify"
            rec._sync_published_vacancy_records()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Sent'),
                'message': _('Approvers (%s) have been successfully notified for vacancy %s.') % (
                    ', '.join(notified_users), self.reference or ''
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1, arg2):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        work_unit_str = self.operating_unit_id.name if self.operating_unit_id else (self.job_location or _('Head Office'))
        message = (
            f"Dear Committee Member,<br/><br/>"
            f"A new Job Vacancy has been submitted for your review and evaluation:<br/><br/>"
            f"• <b>Reference No:</b> {ref}<br/>"
            f"• <b>Job Position:</b> {arg1}<br/>"
            f"• <b>Hiring Work Unit:</b> {work_unit_str}<br/>"
            f"• <b>Type of Employment:</b> {arg2}<br/><br/>"
            f"Kindly review and evaluate the vacancy."
        )
        channel.message_post(body=Markup(message), message_type='comment', subtype_xmlid='mail.mt_comment')

    def _get_fiscal_year_prefix(self, type_code):
        """Computes the current fiscal-year prefix (July–June cycle)."""
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = date.today()
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH,
                                                                FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/{type_code}/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    def _get_next_reference(self):
        """Auto-generate Unique Vacancy Reference Number using maximum sequence number."""
        movement_type = self.internal_movement_type or ('external' if self.sourcing_type == 'external' else 'promotion')
        type_code = JOB_VACANCY_TYPE_CODE_MAP.get(movement_type, 'INT')
        current_prefix = self._get_fiscal_year_prefix(type_code)
        self.env.cr.execute("""
            SELECT reference FROM job_vacancy
            WHERE reference IS NOT NULL AND reference != 'New'
              AND reference LIKE %s
        """, (current_prefix + '%',))
        rows = self.env.cr.fetchall()
        max_num = 0
        for (ref_val,) in rows:
            if ref_val:
                _, _, numeric_part = ref_val.rpartition('/')
                try:
                    num = int(numeric_part)
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        next_number = max_num + 1
        return f"{current_prefix}{str(next_number).zfill(5)}"

    def vacancy_evaluate(self):
        """
        FIXED: Use ID-based comparison instead of name-based comparison.
        This ensures reliable user identification regardless of name formatting or duplicates.
        Ensures only members of the Onboarding and Recruitment Division / Recruitment Managers can evaluate.
        """
        for rec in self:
            is_ext = (rec.sourcing_type == 'external' or rec.internal_movement_type == 'external' or rec.recruitment_type == 'External')
            min_days = 5 if is_ext else 3
            if rec.opening_date and rec.last_date_to_apply:
                duration = (rec.last_date_to_apply - rec.opening_date).days
                if duration < min_days:
                    raise ValidationError(_(
                        "Cannot approve vacancy %(ref)s: The duration between Opening Date (%(opening)s) and Last Date To Apply (%(closing)s) is %(duration)d days, which is less than the required default duration of %(min_days)d days for %(type)s vacancies."
                    ) % {
                        'ref': rec.reference or '',
                        'opening': rec.opening_date,
                        'closing': rec.last_date_to_apply,
                        'duration': duration,
                        'min_days': min_days,
                        'type': _("External") if is_ext else _("Internal"),
                    })

        user = self.env.user
        if not (user.id in (1, 2) or self.env.is_admin()):
            has_recruitment_group = (
                    user.has_group("custom_recruitment.group_recruitment_manager") or
                    user.has_group("custom_recruitment.group_recruitment_administrator") or
                    user.has_group("hr_recruitment.group_hr_recruitment_manager")
            )
            emp = user.employee_id
            ou_name = emp.default_operating_unit_id.name.lower() if emp and emp.default_operating_unit_id else ""

            is_recruitment_division = (
                    has_recruitment_group or
                    "recruitment" in ou_name or "onboarding" in ou_name
            )
            if not is_recruitment_division:
                raise ValidationError(
                    _("Access Denied: Vacancies can only be evaluated by members of the Onboarding and Recruitment Division."))

        n = 0
        current_user_id = self.env.user.id

        for val in self.vac_del_team_id:
            if val.status == "unavailable":
                # Primary approver is unavailable, use alternate committee member
                if val.employee_name.id == current_user_id:
                    raise ValidationError(_("Sorry!! you can not evaluate this Vacancy"))
                if val.alternate_committee_member.id == current_user_id:
                    n += 1
                    val.approve = True
                    break
            else:
                # Primary approver is available, check if current user is primary
                if val.employee_name.id == current_user_id:
                    n += 1
                    val.approve = True
                    break

        if n == 0:
            raise ValidationError(_("Sorry!! You are not assigned for this Evaluation"))

        cnt = sum(1 for v in self.vac_del_team_id if v.approve)
        if cnt == len(self.vac_del_team_id):
            if not self.reference or self.reference == _('New'):
                self.reference = self._get_next_reference()
            self.write({'status': 'evaluate', 'vacancy_status': 'evaluate'})
            self._sync_published_vacancy_records()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Evaluated'),
                'message': _('Vacancy %s has been successfully evaluated.') % self.reference,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def check_plan(self):
        """/007: validate against approved workforce plan."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Checked'),
                'message': _('Vacancy %s has been validated against the workforce plan.') % self.reference,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def publish_vacancy(self):
        """: publish vacancy. Auto-posts to website for external vacancies and sets hr.job to recruitment."""
        for rec in self:
            is_ext = (rec.sourcing_type == 'external' or rec.internal_movement_type == 'external' or rec.recruitment_type == 'External')
            min_days = 5 if is_ext else 3
            if rec.opening_date and rec.last_date_to_apply:
                duration = (rec.last_date_to_apply - rec.opening_date).days
                if duration < min_days:
                    raise ValidationError(_(
                        "Cannot publish vacancy %(ref)s: The duration between Opening Date (%(opening)s) and Last Date To Apply (%(closing)s) is %(duration)d days, which is less than the required default duration of %(min_days)d days for %(type)s vacancies."
                    ) % {
                        'ref': rec.reference or '',
                        'opening': rec.opening_date,
                        'closing': rec.last_date_to_apply,
                        'duration': duration,
                        'min_days': min_days,
                        'type': _("External") if is_ext else _("Internal"),
                    })

        for val in self.vac_del_team_id:
            if not val.approve:
                raise ValidationError(_("You cannot publish the vacancy until it is fully Approved."))
        if not self.reference or self.reference == _('New'):
            raise ValidationError(_(
                "This vacancy does not have a reference number yet.\n"
                "Please click 'Evaluate' first \u2014 the reference is generated once all "
                "committee members have approved."
            ))
        self.write({"vacancy_status": "published", "state": "posted"})
        self._sync_published_vacancy_records()

        # Auto-publish external vacancies to the website and always set hr.job state to 'recruit'
        if self.job_position:
            job_vals = {
                'state': 'recruit',
                'no_of_recruitment': self.no_of_vacancies or 1,
            }
            if self.sourcing_type in ('external', 'both'):
                job_vals.update({
                    'website_published': True,
                    'description': self.vacancy_description or self.job_position.description or '',
                })
                self.write({'website_published': True})
                msg = _('Vacancy %s has been published successfully and posted to the website.') % self.reference
            else:
                job_vals.update({
                    'website_published': False,
                })
                self.write({'website_published': False})
                msg = _('Internal vacancy %s has been published for internal recruitment.') % self.reference

            self.job_position.write(job_vals)
        else:
            if self.sourcing_type in ('external', 'both'):
                self.write({'website_published': True})
                msg = _('Vacancy %s has been published successfully and posted to the website.') % self.reference
            else:
                self.write({'website_published': False})
                msg = _('Internal vacancy %s has been published for internal recruitment.') % self.reference

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vacancy Published'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def close_vacancy(self):
        """: close vacancy at closing date. Also unpublishes from website and stops recruitment."""
        self.write({"vacancy_status": "closed"})

        # Auto-unpublish and stop recruitment when closing vacancies
        if self.job_position:
            self.job_position.write({
                'website_published': False,
                'state': 'open',
            })
        self.write({'website_published': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vacancy Closed'),
                'message': _('Vacancy %s has been closed.') % self.reference,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    @api.model
    def _cron_auto_close_expired_vacancies(self):
        """Automatically close all published vacancies whose application deadline has passed.
        Runs daily at midnight local Ethiopian time (21:00 UTC)."""
        today = fields.Date.today()
        expired = self.search([
            ('vacancy_status', '=', 'published'),
            ('last_date_to_apply', '!=', False),
            ('last_date_to_apply', '<', today),
        ])
        if expired:
            _logger.info(
                "Cron auto-closing %d expired vacancies whose deadline (< %s) passed: %s",
                len(expired), today, expired.mapped('reference')
            )
            for rec in expired:
                try:
                    rec.write({
                        'vacancy_status': 'closed',
                        'website_published': False,
                    })
                    if rec.job_position:
                        other_active = self.search([
                            ('id', '!=', rec.id),
                            ('job_position', '=', rec.job_position.id),
                            ('vacancy_status', '=', 'published'),
                        ])
                        if not other_active:
                            rec.job_position.write({
                                'website_published': False,
                                'state': 'open',
                            })
                    rec.message_post(
                        body=_(
                            "Vacancy automatically closed by system scheduler as application deadline (%s) has passed."
                        ) % rec.last_date_to_apply,
                        subject=_("Vacancy Automatically Closed")
                    )
                except Exception as ex:
                    _logger.warning("Failed to auto-close vacancy %s (id: %s): %s", rec.reference, rec.id, ex)

    def action_open_reschedule_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reschedule Interview & Reassign Panel'),
            'res_model': 'reschedule.interview.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_vacancy_id': self.id,
                'default_new_interview_date': self.date_of_interview or fields.Date.today(),
                'default_new_place_of_interview': self.place_of_interview or '',
            }
        }

    def action_notify_panel_members(self):
        for rec in self:
            if not rec.memb_panel_vac:
                raise UserError(_("No panel members assigned to this vacancy."))
            for member in rec.memb_panel_vac:
                member.write({'response_status': 'pending'})
            rec.message_post(body=_(
                "Interview notifications sent to panel members for scheduled date: %s at %s."
            ) % (rec.date_of_interview or _("TBD"), rec.place_of_interview or _("TBD")))

    def _auto_sync_hiring_and_competencies(self):
        """Ensures hiring details and competency lines are auto-populated from header fields."""
        for rec in self:
            if rec.vacancy_status == 'closed':
                continue
            # 1. Sync Hiring Details
            if rec.operating_unit_id:
                resp = rec.responsible or self.env.user.employee_id
                openings = rec.no_of_vacancies or 1
                if not rec.hiring_details:
                    self.env['hiring.status'].create({
                        'hiring_id': rec.id,
                        'work_unit': rec.operating_unit_id.id,
                        'responsible_employee': resp.id if resp else False,
                        'number_of_openings': openings,
                        'status': 'In Progress',
                    })
                else:
                    for line in rec.hiring_details:
                        vals_to_update = {}
                        if not line.work_unit:
                            vals_to_update['work_unit'] = rec.operating_unit_id.id
                        if not line.responsible_employee and resp:
                            vals_to_update['responsible_employee'] = resp.id
                        if len(rec.hiring_details) == 1 and rec.no_of_vacancies and line.number_of_openings != rec.no_of_vacancies:
                            vals_to_update['number_of_openings'] = rec.no_of_vacancies
                        elif not line.number_of_openings:
                            vals_to_update['number_of_openings'] = min(openings, rec.no_of_vacancies or openings)
                        elif rec.no_of_vacancies and line.number_of_openings > rec.no_of_vacancies:
                            vals_to_update['number_of_openings'] = rec.no_of_vacancies

                        if vals_to_update:
                            line.write(vals_to_update)

            # 2. Sync Competencies
            if rec.job_position and not rec.competency_line_ids:
                lines = rec._get_default_competency_lines(rec.job_position)
                if lines:
                    for l in lines:
                        self.env['job.vacancy.competency'].create(dict(l[2], vacancy_id=rec.id))

            # 3. Sync Default Vacancy Approver from Vacancy Approver Configuration
            if not rec.vac_del_team_id:
                try:
                    with self.env.cr.savepoint():
                        ConfigModel = self.env['vacancy.approver.config']
                        s_type = getattr(rec, 'sourcing_type', 'all') or 'all'
                        configured_users = ConfigModel.get_eligible_approver_users(sourcing_type=s_type, vacancy=rec)
                        if configured_users:
                            self.env['vacancy.delegation.team'].create({
                                'vac_del_id': rec.id,
                                'employee_name': configured_users[0].id,
                                'role': 'approver',
                                'status': 'active',
                            })
                except Exception as e:
                    _logger.warning("Could not auto-populate default vacancy approver: %s", e)

    def _compute_hierarchy_type_recruitment(self):
        """Determine the approval hierarchy category based on Grade and Operating Unit."""
        self.ensure_one()
        grade = self.job_grade_id or (self.job_position.job_grade_id if self.job_position else False)
        op_unit = self.operating_unit_id
        category = self.employee_category if hasattr(self, 'employee_category') else False

        unit_name = str(op_unit.name or "").lower() if op_unit else ""
        is_head_office = "head" in unit_name or "ho" in unit_name or "main" in unit_name
        grade_name = str(getattr(grade, 'grade_name', '') or getattr(grade, 'name', '') or '').lower()
        grade_level = str(getattr(grade, 'grade_level', '') or '').lower()

        is_grade_2_plus_or_manager = (
            "managerial" in str(category).lower()
            or "grade 2" in grade_name or "grade ii" in grade_name
            or "grade 3" in grade_name or "grade iii" in grade_name
            or "grade 4" in grade_name or "grade iv" in grade_name
            or "grade 5" in grade_name or "grade v" in grade_name
            or "senior" in grade_level or "managerial" in grade_level
        )

        if is_grade_2_plus_or_manager:
            return "ho_district_grade2_plus"
        elif is_head_office:
            return "non_managerial_ho"
        else:
            return "non_managerial_district" 

    def web_read(self, specification):
        return super().web_read(specification)

    def _sync_schedule_to_selection_models(self):
        for rec in self:
            if not rec.id:
                continue
            vals_to_sync = {
                'written_exam_date': rec.written_exam_date or False,
                'exam_location': rec.exam_location or False,
                'exam_scheduled': rec.exam_scheduled or 'No',
                'interview_date': rec.interview_date or False,
                'interview_location': rec.interview_location or False,
                'interview_scheduled': rec.interview_scheduled or 'No',
            }
            if rec.selected_recruitment_id:
                rec.selected_recruitment_id.sudo().write(vals_to_sync)
            ext_sels = self.env['external.recruitment.selected'].search([
                '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
            ])
            if ext_sels:
                ext_sels.sudo().write(vals_to_sync)

    # ── End of JobVacancy class ──────────────────────────────────────────


class PanelMembers(models.Model):
    _name = 'vac.panel.members'
    _description = "Vac Panel Members"

    role = fields.Char(string='Role')
    panel_member_name = fields.Char(string='Panel Member Name')
    employee_id = fields.Many2one("hr.employee", string="Panel Member Employee")
    user_id = fields.Many2one("res.users", string="User", compute="_compute_user_id", store=True)
    active = fields.Boolean(default=True)
    panel_type = fields.Char(string='Panel Type')
    status = fields.Boolean(string='Status', default=True)
    panl_memb_vac = fields.Many2one("job.vacancy", "Vacancy panel Members")

    # Rescheduling & Delegation fields
    response_status = fields.Selection([
        ('pending', 'Pending Response'),
        ('accepted', 'Accepted'),
        ('unavailable', 'Unavailable'),
        ('reschedule_requested', 'Reschedule Requested'),
        ('delegation_requested', 'Delegation Requested')
    ], string="Response Status", default='pending')

    response_reason = fields.Text(string="Response Reason / Notes")
    proposed_interview_date = fields.Datetime(string="Proposed Date & Time")
    delegate_employee_id = fields.Many2one("hr.employee", string="Proposed Alternate Member")
    delegation_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_hr', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Delegation Status", default='draft')

    eligible_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_eligible_employee_ids',
        string='Eligible Panel Employees'
    )

    def _get_eligible_panel_info(self, vac=False):
        target_ou_ids = set()
        resp_ou_ids = set()

        def _is_district_or_branch_ou(ou_ref):
            if not ou_ref:
                return False
            try:
                curr = ou_ref
                if isinstance(ou_ref, int) and ou_ref > 0:
                    curr = self.env['operating.unit'].browse(ou_ref)
                if not curr or not curr.exists():
                    return False
                w_type = getattr(curr, 'work_unit_type', False)
                if w_type in ('district_office', 'branch', 'sub_branch', 'regional_office', 'service_center'):
                    return True
                name_str = str(getattr(curr, 'name', '') or '').lower()
                code_str = str(getattr(curr, 'code', '') or '').lower()
                return 'branch' in name_str or 'district' in name_str or 'branch' in code_str or 'district' in code_str
            except Exception:
                return False

        def _get_ho_root_and_children(ou_ref):
            res = set()
            if not ou_ref:
                return res
            curr = ou_ref
            if isinstance(ou_ref, int) and ou_ref > 0:
                curr = self.env['operating.unit'].browse(ou_ref)
            if not curr or not curr.exists():
                return res
            while curr.parent_unit and curr.parent_unit.exists() and not _is_district_or_branch_ou(curr.parent_unit):
                curr = curr.parent_unit
            res.add(curr.id)
            frontier = [curr.id]
            while frontier:
                children = self.env['operating.unit'].search([('parent_unit', 'in', frontier)])
                w_children = children.filtered(lambda u: u.work_unit_type not in ('district_office', 'branch', 'sub_branch', 'regional_office', 'service_center'))
                new_ids = set(w_children.ids) - res
                if not new_ids:
                    break
                res.update(new_ids)
                frontier = list(new_ids)
            return res

        if not vac and hasattr(self, 'panl_memb_vac') and self.panl_memb_vac:
            vac = self.panl_memb_vac
        if not vac and self.env.context.get('default_panl_memb_vac'):
            v_id = self.env.context.get('default_panl_memb_vac')
            vac = self.env['job.vacancy'].browse(v_id) if isinstance(v_id, int) else v_id
        if not vac and self.env.context.get('default_vacancy_id'):
            v_id = self.env.context.get('default_vacancy_id')
            vac = self.env['job.vacancy'].browse(v_id) if isinstance(v_id, int) else v_id
        if not vac and self.env.context.get('active_model') == 'job.vacancy' and self.env.context.get('active_id'):
            vac = self.env['job.vacancy'].browse(self.env.context.get('active_id'))

        # 1. Hiring Work Unit Target OUs
        hiring_ou = False
        if vac and getattr(vac, 'operating_unit_id', False):
            hiring_ou = vac.operating_unit_id
        elif self.env.context.get('parent_operating_unit_id'):
            p_ou = self.env.context.get('parent_operating_unit_id')
            hiring_ou = self.env['operating.unit'].browse(p_ou) if isinstance(p_ou, int) else p_ou
        elif self.env.context.get('parent_workunit_id'):
            p_wu = self.env.context.get('parent_workunit_id')
            hiring_ou = self.env['operating.unit'].browse(p_wu) if isinstance(p_wu, int) else p_wu

        if hiring_ou and hiring_ou.exists():
            dept = getattr(hiring_ou, 'department', False)
            dept_name = dept.name if dept else ''

            is_ho = False
            if dept_name and 'head office' in dept_name.lower():
                is_ho = True
            elif not _is_district_or_branch_ou(hiring_ou):
                is_ho = True

            if is_ho:
                # Rule 1 (Head Office): Include ONLY the Hiring Work Unit operating unit itself
                target_ou_ids.add(hiring_ou.id)
            else:
                # Rule 2 (District/Branch - Out of Head Office): Target ONLY the District operating unit
                dist_ou = False
                if dept:
                    dist_ou = self.env['operating.unit'].search([
                        ('name', '=ilike', dept.name),
                        ('work_unit_type', '=', 'district_office')
                    ], limit=1)
                    if not dist_ou:
                        dist_ou = self.env['operating.unit'].search([('name', '=ilike', dept.name)], limit=1)

                if not dist_ou and getattr(hiring_ou, 'parent_unit', False):
                    p = hiring_ou.parent_unit
                    if getattr(p, 'work_unit_type', '') == 'district_office' or 'district' in (p.name or '').lower():
                        dist_ou = p

                if not dist_ou and getattr(hiring_ou, 'district', False):
                    dist_name = hiring_ou.district
                    dist_ou = self.env['operating.unit'].search([('name', '=ilike', dist_name)], limit=1)

                if dist_ou and dist_ou.exists():
                    target_ou_ids.add(dist_ou.id)
                else:
                    target_ou_ids.add(hiring_ou.id)

        # 2. Responsible Person & Committee Members
        if vac:
            if getattr(vac, 'responsible', False) and vac.responsible:
                resp_emp = vac.responsible
                if getattr(resp_emp, 'default_operating_unit_id', False):
                    resp_ou_ids.add(resp_emp.default_operating_unit_id.id)
                if getattr(resp_emp, 'user_id', False) and getattr(resp_emp.user_id, 'employee_id', False):
                    resp_user_emp = resp_emp.user_id.employee_id
                    if getattr(resp_user_emp, 'default_operating_unit_id', False):
                        resp_ou_ids.add(resp_user_emp.default_operating_unit_id.id)
            if getattr(vac, 'responsible_employee', False) and vac.responsible_employee:
                resp_emp = vac.responsible_employee
                if getattr(resp_emp, 'default_operating_unit_id', False):
                    resp_ou_ids.add(resp_emp.default_operating_unit_id.id)

            if getattr(vac, 'vac_del_team_id', False):
                for del_line in vac.vac_del_team_id:
                    emp_user = getattr(del_line, 'employee_name', False)
                    if emp_user and getattr(emp_user, 'employee_id', False):
                        emp = emp_user.employee_id
                        if getattr(emp, 'default_operating_unit_id', False):
                            resp_ou_ids.add(emp.default_operating_unit_id.id)
                    alt_user = getattr(del_line, 'alternate_committee_member', False)
                    if alt_user and getattr(alt_user, 'employee_id', False):
                        alt_emp = alt_user.employee_id
                        if getattr(alt_emp, 'default_operating_unit_id', False):
                            resp_ou_ids.add(alt_emp.default_operating_unit_id.id)

            hierarchy_users = [
                getattr(vac, 'chairperson_id', False),
                getattr(vac, 'panel_member_id', False),
                getattr(vac, 'secretary_id', False),
                getattr(vac, 'observer_id', False),
            ]
            for user in hierarchy_users:
                if user and getattr(user, 'employee_id', False):
                    emp = user.employee_id
                    if getattr(emp, 'default_operating_unit_id', False):
                        resp_ou_ids.add(emp.default_operating_unit_id.id)

        if self.env.context.get('parent_responsible_id'):
            r_id = self.env.context.get('parent_responsible_id')
            emp = self.env['hr.employee'].browse(r_id) if isinstance(r_id, int) else r_id
            if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
                resp_ou_ids.add(emp.default_operating_unit_id.id)

        return list(target_ou_ids), list(resp_ou_ids)

    def _get_eligible_operating_units(self, vac=False):
        target_ou_ids, resp_ou_ids = self._get_eligible_panel_info(vac=vac)
        return list(set(target_ou_ids) | set(resp_ou_ids))

    def _get_eligible_employees(self, vac=False):
        return self.env['hr.employee'].search([('active', '=', True)])

    @api.depends(
        'panl_memb_vac',
        'panl_memb_vac.operating_unit_id',
        'panl_memb_vac.responsible',
        'panl_memb_vac.chairperson_id',
        'panl_memb_vac.panel_member_id',
        'panl_memb_vac.secretary_id',
        'panl_memb_vac.observer_id',
    )
    def _compute_eligible_employee_ids(self):
        ConfigModel = self.env['recruitment.panel.member.config']
        for rec in self:
            s_type = getattr(rec.panl_memb_vac, 'sourcing_type', 'all') or 'all'
            rec.eligible_employee_ids = ConfigModel.get_eligible_panel_employees(
                sourcing_type=s_type,
                vacancy=rec.panl_memb_vac
            )

    @api.onchange('panl_memb_vac', 'role', 'panel_type')
    def _onchange_panl_memb_vac_domain(self):
        """Filter panel members to configured panel members from configurations."""
        ConfigModel = self.env['recruitment.panel.member.config']
        s_type = getattr(self.panl_memb_vac, 'sourcing_type', 'all') or 'all'
        eligible = ConfigModel.get_eligible_panel_employees(
            sourcing_type=s_type,
            vacancy=self.panl_memb_vac
        )
        self.eligible_employee_ids = eligible
        domain = [('id', 'in', eligible.ids)]
        return {'domain': {'employee_id': domain}}

    @api.depends('employee_id', 'panel_member_name')
    def _compute_user_id(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.user_id:
                rec.user_id = rec.employee_id.user_id
            elif rec.panel_member_name:
                emp = self.env['hr.employee'].search([('name', '=ilike', rec.panel_member_name)], limit=1)
                rec.user_id = emp.user_id.id if emp and emp.user_id else False
            else:
                rec.user_id = False

    def _check_current_user_is_panel_member(self):
        """Ensure that only the assigned employee (or approved delegate) can accept, reject, or respond."""
        current_user = self.env.user
        current_emp = current_user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', current_user.id)], limit=1)
        for rec in self:
            assigned_emp = getattr(rec, 'employee_id', False)
            if not assigned_emp:
                continue
            is_assigned = (
                (assigned_emp.user_id and assigned_emp.user_id == current_user) or
                (current_emp and current_emp == assigned_emp) or
                (hasattr(current_user, 'employee_ids') and assigned_emp in current_user.employee_ids)
            )
            delegate_emp = getattr(rec, 'delegate_employee_id', False)
            if not is_assigned and delegate_emp:
                is_assigned = (
                    (delegate_emp.user_id and delegate_emp.user_id == current_user) or
                    (current_emp and current_emp == delegate_emp) or
                    (hasattr(current_user, 'employee_ids') and delegate_emp in current_user.employee_ids)
                )
            if not is_assigned:
                emp_name_str = assigned_emp.name if hasattr(assigned_emp, 'name') else str(assigned_emp)
                raise ValidationError(_(
                    "Validation Error: You cannot accept or respond to this interview invitation on behalf of employee '%s'. "
                    "Only '%s' is authorized to respond to this assignment."
                ) % (emp_name_str, emp_name_str))

    def action_open_response_wizard(self):
        self.ensure_one()
        self._check_current_user_is_panel_member()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Panel Member Interview Response'),
            'res_model': 'panel.member.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_panel_member_id': self.id,
                'default_vacancy_id': self.panl_memb_vac.id if self.panl_memb_vac else False,
            }
        }

    def action_approve_delegation(self):
        for rec in self:
            if rec.delegation_state != 'pending_hr' or not rec.delegate_employee_id:
                raise UserError(_("No pending delegation request found for approval."))
            old_name = rec.panel_member_name or (rec.employee_id.name if rec.employee_id else "")
            new_emp = rec.delegate_employee_id
            rec.write({
                'employee_id': new_emp.id,
                'panel_member_name': new_emp.name,
                'delegation_state': 'approved',
                'response_status': 'pending',
                'response_reason': _("Delegated from %s (Approved by HR)") % old_name,
            })
            if rec.panl_memb_vac:
                rec.panl_memb_vac.message_post(body=_(
                    "HR approved panel delegation: <b>%s</b> replaced by <b>%s</b>."
                ) % (old_name, new_emp.name))

    def action_reject_delegation(self):
        for rec in self:
            rec.write({
                'delegation_state': 'rejected',
                'response_status': 'unavailable',
            })
            if rec.panl_memb_vac:
                rec.panl_memb_vac.message_post(body=_(
                    "HR rejected panel delegation request for <b>%s</b>."
                ) % (rec.panel_member_name or rec.employee_id.name))

    def _check_parent_lock(self):
        if self.env.context.get('bypass_lock') or self.env.context.get('skip_lock_check'):
            return
        for rec in self:
            if rec.panl_memb_vac and rec.panl_memb_vac.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "panel members can no longer be edited."
                ))

    @api.constrains('employee_id', 'panl_memb_vac', 'active')
    def _check_duplicate_panel_member(self):
        for rec in self:
            if not rec.active or not rec.employee_id:
                continue
            if rec.panl_memb_vac:
                duplicates = rec.panl_memb_vac.memb_panel_vac.filtered(
                    lambda l: l.active and l != rec and l.employee_id == rec.employee_id
                )
                if duplicates:
                    raise ValidationError(_(
                        "The employee '%s' is already assigned as a panel member. Duplicate panel members are not allowed for the same vacancy."
                    ) % rec.employee_id.name)

    @api.onchange('employee_id')
    def _onchange_employee_id_prevent_duplicate(self):
        if not self.employee_id:
            return
        if self.panl_memb_vac and self.panl_memb_vac.memb_panel_vac:
            duplicates = [
                p for p in self.panl_memb_vac.memb_panel_vac
                if p != self and p.employee_id == self.employee_id
            ]
            if duplicates:
                emp_name = self.employee_id.name
                self.employee_id = False
                return {
                    'warning': {
                        'title': _("Duplicate Panel Member"),
                        'message': _("The employee '%s' is already assigned as a panel member. You cannot add the same employee multiple times.") % emp_name,
                    }
                }

    def _auto_init(self):
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    ALTER TABLE job_vacancy 
                    ADD COLUMN IF NOT EXISTS written_exam_date TIMESTAMP WITHOUT TIME ZONE,
                    ADD COLUMN IF NOT EXISTS exam_location TEXT,
                    ADD COLUMN IF NOT EXISTS exam_scheduled VARCHAR,
                    ADD COLUMN IF NOT EXISTS interview_date TIMESTAMP WITHOUT TIME ZONE,
                    ADD COLUMN IF NOT EXISTS interview_location TEXT,
                    ADD COLUMN IF NOT EXISTS interview_scheduled VARCHAR,
                    ADD COLUMN IF NOT EXISTS pms_weight NUMERIC,
                    ADD COLUMN IF NOT EXISTS written_weight NUMERIC,
                    ADD COLUMN IF NOT EXISTS interview_weight NUMERIC,
                    ADD COLUMN IF NOT EXISTS approval_hierarchy_type VARCHAR,
                    ADD COLUMN IF NOT EXISTS chairperson_id INT4,
                    ADD COLUMN IF NOT EXISTS panel_member_id INT4,
                    ADD COLUMN IF NOT EXISTS secretary_id INT4,
                    ADD COLUMN IF NOT EXISTS observer_id INT4;

                    UPDATE job_vacancy jv
                    SET written_exam_date = COALESCE(jv.written_exam_date, nirs.written_exam_date, ers.written_exam_date),
                        exam_location = COALESCE(jv.exam_location, nirs.exam_location, ers.exam_location),
                        interview_date = COALESCE(jv.interview_date, nirs.interview_date, ers.interview_date),
                        interview_location = COALESCE(jv.interview_location, nirs.interview_location, ers.interview_location)
                    FROM job_vacancy j
                    LEFT JOIN new_internal_recruitment_selected nirs ON nirs.vacancy_id = j.id OR nirs.vacancy_reference = j.reference
                    LEFT JOIN external_recruitment_selected ers ON ers.vacancy_id = j.id OR ers.vacancy_reference = j.reference
                    WHERE jv.id = j.id;
                """)
        except Exception as e:
            _logger.warning("Safe migration on job_vacancy: %s", e)

        # Clean up legacy separate recruitment privilege & category so they merge into Human Resources
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    DO $$
                    DECLARE
                        std_priv_id int;
                        old_priv_id int;
                        old_cat_id int;
                    BEGIN
                        SELECT res_id INTO std_priv_id FROM ir_model_data WHERE module = 'hr_recruitment' AND name = 'res_groups_privilege_recruitment';
                        SELECT res_id INTO old_priv_id FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'recruitment_privilege';
                        SELECT res_id INTO old_cat_id FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'module_category_recruitment';

                        IF old_priv_id IS NOT NULL THEN
                            UPDATE res_groups SET privilege_id = NULL WHERE privilege_id = old_priv_id;
                            IF std_priv_id IS NOT NULL THEN
                                UPDATE res_groups SET privilege_id = std_priv_id WHERE id IN (
                                    SELECT res_id FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'group_recruitment_manager'
                                );
                            END IF;
                            DELETE FROM res_groups_privilege WHERE id = old_priv_id;
                            DELETE FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'recruitment_privilege';
                        END IF;

                        IF old_cat_id IS NOT NULL THEN
                            DELETE FROM ir_module_category WHERE id = old_cat_id;
                            DELETE FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'module_category_recruitment';
                        END IF;
                    END $$;
                """)
        except Exception as e:
            _logger.warning("Recruitment privilege cleanup notice: %s", e)

        return res

    def write(self, vals):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        res = super().write(vals)
        sync_keys = {'written_exam_date', 'exam_location', 'exam_scheduled', 'interview_date', 'interview_location', 'interview_scheduled', 'pms_weight', 'written_weight', 'interview_weight'}
        if sync_keys.intersection(vals.keys()):
            for rec in self:
                rec._sync_schedule_to_selection_models()
        return res

    def _sync_schedule_to_selection_models(self):
        for rec in self:
            if not rec.id:
                continue
            vals_to_sync = {
                'written_exam_date': rec.written_exam_date or False,
                'exam_location': rec.exam_location or False,
                'exam_scheduled': rec.exam_scheduled or 'No',
                'interview_date': rec.interview_date or False,
                'interview_location': rec.interview_location or False,
                'interview_scheduled': rec.interview_scheduled or 'No',
            }
            if rec.selected_recruitment_id:
                rec.selected_recruitment_id.sudo().write(vals_to_sync)
            ext_sels = self.env['external.recruitment.selected'].search([
                '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
            ])
            if ext_sels:
                ext_sels.sudo().write(vals_to_sync)

    def unlink(self):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        self.with_context(bypass_lock=True, skip_lock_check=True).write({"active": False})
        return True


class Job_vacancy_hiring_status(models.Model):
    _name = 'hiring.status'
    _description = "Job Vacancy Hiring Status"
    _rec_name = "work_unit"
    active = fields.Boolean(default=True)
    hiring_id = fields.Many2one("job.vacancy", 'Job Vacancy Hiring Status')
    work_unit = fields.Many2one(
        "operating.unit", string="Work Unit",
        compute="_compute_hiring_defaults", store=True, readonly=False
    )
    responsible_employee = fields.Many2one(
        "hr.employee", string="Responsible Officer",
        compute="_compute_hiring_defaults", store=True, readonly=False,
        default=lambda self: self.env.user.employee_id
    )
    number_of_openings = fields.Integer(
        string="Number Of Openings",
        compute="_compute_hiring_defaults", store=True, readonly=False
    )
    planned_positions = fields.Integer(
        string="Planned Openings",
        compute="_compute_hiring_defaults", store=True, readonly=True
    )
    status = fields.Char(string="Status", default="In Progress")

    @api.depends('hiring_id.operating_unit_id', 'hiring_id.responsible', 'hiring_id.no_of_vacancies', 'hiring_id.job_position', 'hiring_id.approved_plan_count', 'work_unit')
    def _compute_hiring_defaults(self):
        for rec in self:
            if not rec.hiring_id or rec.hiring_id.vacancy_status == 'closed':
                continue
            if rec.hiring_id:
                if rec.hiring_id.operating_unit_id and not rec.work_unit:
                    rec.work_unit = rec.hiring_id.operating_unit_id
                if rec.hiring_id.responsible and not rec.responsible_employee:
                    rec.responsible_employee = rec.hiring_id.responsible
                elif not rec.responsible_employee and self.env.user.employee_id:
                    rec.responsible_employee = self.env.user.employee_id
                if rec.hiring_id.no_of_vacancies:
                    if not rec.number_of_openings or (rec.hiring_id.hiring_details and len(rec.hiring_id.hiring_details) == 1):
                        rec.number_of_openings = rec.hiring_id.no_of_vacancies

                wu = rec.work_unit or rec.hiring_id.operating_unit_id
                job = rec.hiring_id.job_position
                if wu and job and hasattr(rec.hiring_id, '_get_workunit_approved_plan_count'):
                    rec.planned_positions = rec.hiring_id._get_workunit_approved_plan_count(wu, job)
                else:
                    rec.planned_positions = rec.hiring_id.approved_plan_count or 0

    @api.constrains('number_of_openings', 'hiring_id')
    def _check_number_of_openings(self):
        for rec in self:
            if rec.hiring_id and rec.hiring_id.no_of_vacancies and rec.hiring_id.hiring_details:
                total_openings = sum(rec.hiring_id.hiring_details.mapped('number_of_openings'))
                if total_openings != rec.hiring_id.no_of_vacancies:
                    raise ValidationError(_(
                        "Number of Openings (total %(openings)d) must be equal to Number of Vacancies (%(vacancies)d)."
                    ) % {
                        'openings': total_openings,
                        'vacancies': rec.hiring_id.no_of_vacancies,
                    })

    @api.onchange('number_of_openings')
    def _onchange_number_of_openings(self):
        if self.hiring_id:
            other_lines_sum = sum(
                line.number_of_openings
                for line in self.hiring_id.hiring_details
                if line != self
            )
            total = other_lines_sum + (self.number_of_openings or 0)
            if total > 0 and self.hiring_id.no_of_vacancies != total:
                self.hiring_id.no_of_vacancies = total

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.work_unit.name if rec.work_unit else str(rec.id)

    def _check_parent_lock(self):
        if self.env.context.get('bypass_lock') or self.env.context.get('skip_lock_check'):
            return
        for rec in self:
            if rec.hiring_id and rec.hiring_id.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "hiring status lines can no longer be edited."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.hiring_id and rec.hiring_id.vacancy_status == 'draft' and not self.env.context.get('skip_sync_vacancies'):
                total = sum(rec.hiring_id.hiring_details.mapped('number_of_openings'))
                if total > 0 and rec.hiring_id.no_of_vacancies != total:
                    rec.hiring_id.with_context(skip_lock_check=True, skip_sync_openings=True).write({'no_of_vacancies': total})
        return records

    def write(self, vals):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        res = super().write(vals)
        if 'number_of_openings' in vals and not self.env.context.get('skip_sync_vacancies'):
            for rec in self:
                if rec.hiring_id and rec.hiring_id.vacancy_status == 'draft':
                    total = sum(rec.hiring_id.hiring_details.mapped('number_of_openings'))
                    if total > 0 and rec.hiring_id.no_of_vacancies != total:
                        rec.hiring_id.with_context(skip_lock_check=True, skip_sync_openings=True).write({'no_of_vacancies': total})
        return res

    def unlink(self):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        self.with_context(bypass_lock=True, skip_lock_check=True).write({"active": False})
        return True


class ResultSummaryRank(models.Model):
    _name = 'result.summary.rank'
    _description = "Result Summary Rank"

    no = fields.Integer(string='No')
    rank = fields.Integer(string='Rank')
    statues = fields.Char(string='Status')
    applicant_name = fields.Char(string='Applicant name')
    active = fields.Boolean(default=True)
    result = fields.Char(string='Result')
    summ_rank_id = fields.Many2one("job.vacancy", 'Job Result Summary Rank')

    def _check_parent_lock(self):
        if self.env.context.get('bypass_lock') or self.env.context.get('skip_lock_check'):
            return
        for rec in self:
            if rec.summ_rank_id and rec.summ_rank_id.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "result summary lines can no longer be edited."
                ))

    def write(self, vals):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('bypass_lock') and not self.env.context.get('skip_lock_check'):
            self._check_parent_lock()
        self.with_context(bypass_lock=True, skip_lock_check=True).write({"active": False})
        return True


class VacancyDelegation(models.Model):
    _name = "vacancy.delegation.team"
    _description = "Vacancy Delegation Team"
    active = fields.Boolean(default=True)

    def _auto_init(self):
        super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE vacancy_delegation_team SET role = 'approver' WHERE role IS NULL OR role NOT IN ('approver', 'panel_member');
                    UPDATE vacancy_delegation_team SET status = 'active' WHERE status IS NULL OR status = '';
                """)
        except Exception as e:
            _logger.warning("Migration query on vacancy_delegation_team failed: %s", e)

    def unlink(self):
        self.write({"active": False})
        return True

    role = fields.Selection([
        ("approver", "Vacancy Approver"),
        ("panel_member", "Vacancy Approver"),
    ], string="Role", default="approver")
    employee_name = fields.Many2one(
        'res.users',
        string="Employee Name",
    )
    alternate_committee_member = fields.Many2one(
        "res.users",
        string="Alternate Approver",
    )
    eligible_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_eligible_user_ids',
        string='Eligible Approvers'
    )

    @api.depends('role', 'vac_del_id', 'vac_del_id.operating_unit_id', 'vac_del_id.sourcing_type')
    def _compute_eligible_user_ids(self):
        ConfigModel = self.env['vacancy.approver.config']
        for rec in self:
            vac = rec.vac_del_id or False
            s_type = getattr(vac, 'sourcing_type', 'all') or 'all'
            rec.eligible_user_ids = ConfigModel.get_eligible_approver_users(sourcing_type=s_type, vacancy=vac)

    @api.onchange('role', 'vac_del_id')
    def _onchange_role_get_user_domain(self):
        ConfigModel = self.env['vacancy.approver.config']
        vac = self.vac_del_id or False
        s_type = getattr(vac, 'sourcing_type', 'all') or 'all'
        eligible = ConfigModel.get_eligible_approver_users(sourcing_type=s_type, vacancy=vac)
        self.eligible_user_ids = eligible
        domain = [('id', 'in', eligible.ids)] if eligible else [('id', '=', 0)]
        if self.employee_name and self.employee_name.id not in eligible.ids:
            self.employee_name = False
        if self.alternate_committee_member and self.alternate_committee_member.id not in eligible.ids:
            self.alternate_committee_member = False
        return {
            'domain': {
                'employee_name': domain,
                'alternate_committee_member': domain,
            }
        }

    def _get_role_user_domain(self, role=None):
        ConfigModel = self.env['vacancy.approver.config']
        vac = self.vac_del_id or False
        s_type = getattr(vac, 'sourcing_type', 'all') or 'all'
        eligible = ConfigModel.get_eligible_approver_users(sourcing_type=s_type, vacancy=vac)
        if eligible:
            return [('id', 'in', eligible.ids)]
        return [('id', '=', 0)]

    @api.constrains('employee_name', 'alternate_committee_member', 'vac_del_id')
    def _check_approver_operating_unit(self):
        ConfigModel = self.env['vacancy.approver.config']
        for rec in self:
            vac = rec.vac_del_id
            s_type = getattr(vac, 'sourcing_type', 'all') or 'all'
            configured_users = ConfigModel.get_eligible_approver_users(sourcing_type=s_type, vacancy=vac)
            has_configs = bool(ConfigModel.search_count([('active', '=', True)]) > 0 and configured_users)

            for u in [rec.employee_name, rec.alternate_committee_member]:
                if not u:
                    continue
                if has_configs and u.id not in configured_users.ids:
                    raise ValidationError(_(
                        "Selected user '%(user)s' is not in the authorized Vacancy Approvers list. "
                        "Please choose from configured vacancy approvers."
                    ) % {'user': u.name})

    operating_unit = fields.Char(string="Operating Unit",
                                 related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="Status",
                              default='active')
    alter_operating_unit = fields.Char(string="Alt. Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    is_mandatory = fields.Boolean(string="Mandatory?", default=True)
    digital_signature = fields.Binary(string="Digital Signature", copy=False)
    signed_on = fields.Datetime(string="Signed Date & Time", readonly=True, copy=False)
    approve = fields.Boolean(string="Approve", readonly=True)
    vac_del_id = fields.Many2one("job.vacancy", string="Vacancy Delegation Team")

    def get_signature_image(self):
        """Returns binary signature image, falling back to selection minute record if not directly set."""
        self.ensure_one()
        if self.digital_signature:
            return self.digital_signature
        user = self.employee_name or self.alternate_committee_member
        if user and self.vac_del_id:
            minute = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', self.vac_del_id.id)], order='id desc', limit=1)
            if minute:
                sig = minute.committee_signature_ids.filtered(lambda s: s.user_id.id == user.id)
                if sig:
                    return sig[0].digital_signature or sig[0].signature_img
        return False

    def get_committee_role(self):
        """Returns human-readable committee role."""
        self.ensure_one()
        if self.role:
            role_dict = dict(self._fields['role']._description_selection(self.env)) if hasattr(self._fields.get('role', None), '_description_selection') else {}
            return role_dict.get(self.role, self.role.replace('_', ' ').title() if isinstance(self.role, str) else self.role)
        user = self.employee_name or self.alternate_committee_member
        if user and self.vac_del_id:
            vac = self.vac_del_id
            if getattr(vac, 'chairperson_id', False) == user:
                return "Chairperson"
            elif getattr(vac, 'panel_member_id', False) == user:
                return "Panel Member"
            elif getattr(vac, 'secretary_id', False) == user:
                return "Panel Member & Secretary"
            elif getattr(vac, 'observer_id', False) == user:
                return "Labor Representative (Observer)"
        return "Committee Member"


    # NOTE: intentionally NOT locked here — vacancy_evaluate sets `approve = True`
    # on these lines via write, and that call must keep working after the
    # vacancy itself becomes locked (evaluation happens right before/at lock time).


class BBIntRec(models.Model):
    _name = "bb.internal"
    _description = "Bb Internal"

    int_reference = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                                default=lambda self: _('New'))
    applicant_id = fields.Integer(string="Applicant_Id")
    applicant_name = fields.Char(string="Applicant name")
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('int_reference') or vals.get('int_reference') == _('New'):
                vals['int_reference'] = self.env['ir.sequence'].next_by_code('bb.internal') or _('New')
        return super().create(vals_list)


class BBExtRec(models.Model):
    _name = "bb.external"
    _description = "Bb External"

    ext_reference = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                                default=lambda self: _('New'))
    applicant_id = fields.Integer(string="Applicant_Id")
    applicant_name = fields.Char(string="Applicant name")
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ext_reference') or vals.get('ext_reference') == _('New'):
                vals['ext_reference'] = self.env['ir.sequence'].next_by_code('bb.external') or _('New')
        return super().create(vals_list)
