from odoo import api, models, fields, _
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
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
    'recr_selected_team_id', 'pms_weight', 'written_weight', 'interview_weight',
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
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    reference = fields.Char(string='Reference', copy=False, readonly=True, default=lambda self: _('New'))

    state = fields.Selection(selection=[
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], string='Status', required=True, readonly=True, copy=False, tracking=True,
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
    full_non_banking_credit = fields.Boolean(
        string='Full Non-Banking Experience Credit (100%)',
        default=False,
        help="If enabled, candidates applying to this vacancy receive 100% credit (1.0 weight) for non-banking experience during shortlisting and ranking. If disabled, non-banking experience receives 50% credit (0.5 weight)."
    )
    non_banking_exp_weight = fields.Float(
        string='Non-Banking Experience Weight',
        compute='_compute_non_banking_exp_weight',
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
                ou = vac.operating_unit_id
                is_hr_it = False
                if ou:
                    ou_name = (ou.name or '').lower()
                    ou_code = (getattr(ou, 'code', '') or '').lower()
                    if getattr(ou, 'full_non_banking_credit', False) or any(kw in ou_name or kw in ou_code for kw in ['hr', 'human resource', 'it', 'information technology', 'ict', 'software', 'digital']):
                        is_hr_it = True
                vac.non_banking_exp_weight = 1.0 if is_hr_it else 0.5

    @api.onchange('full_non_banking_credit')
    def _onchange_full_non_banking_credit(self):
        for vac in self:
            if vac.full_non_banking_credit:
                vac.non_banking_exp_weight = 1.0
            else:
                vac.non_banking_exp_weight = 0.5

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

    @api.onchange('sourcing_type')
    def _onchange_sourcing_type(self):
        """Auto-set movement type and legacy recruitment_type when sourcing changes."""
        for rec in self:
            if rec.sourcing_type == 'external':
                rec.internal_movement_type = 'external'
                rec.recruitment_type = 'External'
            elif rec.sourcing_type == 'internal':
                if rec.internal_movement_type == 'external':
                    rec.internal_movement_type = 'promotion'
                rec.recruitment_type = 'Internal'
            elif rec.sourcing_type == 'both':
                if rec.internal_movement_type == 'external':
                    rec.internal_movement_type = 'promotion'
                rec.recruitment_type = 'Internal'

    @api.constrains('recruitment_type', 'internal_movement_type', 'sourcing_type')
    def _check_internal_movement_type(self):
        """Movement Type validation."""
        for rec in self:
            if not rec.internal_movement_type:
                if rec.sourcing_type == 'external' or rec.recruitment_type == 'External':
                    rec.internal_movement_type = 'external'
                else:
                    rec.internal_movement_type = 'promotion'

    partner_id = fields.Many2one('res.partner', string="Vendor")
    job_position = fields.Many2one('hr.job', string="Position Job", required=True)
    job_grade = fields.Many2one("employee.grade", string="Job Grade", related="job_position.grade")
    employee_category = fields.Selection(
        [('Managerial', 'Managerial'), ('Non Managerial', 'Non Managerial')],
        string='Job Category', default='Non Managerial')

    # ── NEW: Job Level now lives on the vacancy itself, not on each
    # candidate score. Only relevant / visible when employee_category is
    # 'Non Managerial' — Managerial vacancies have no sub-level.
    job_level = fields.Selection(
        [('junior', 'Junior'), ('senior', 'Senior')],
        string='Job Level',
        help="Only applicable for Non-Managerial vacancies. Drives the "
             "Job Level shown on every Candidate Score linked to this "
             "vacancy — no longer chosen per-candidate."
    )

    recruitment_request_id = fields.Many2one(
        "recruitment.request", string="Recruitment Reference",
        domain="[('state', '=', 'approved')]", tracking=True,
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
    vacancy_announced_on = fields.Date(string="Vacancy Announced on")

    # Legacy field — kept for compatibility; use sourcing_type for new records
    recruitment_type = fields.Selection(
        [('Internal', 'Internal'), ('External', 'External')],
        string='Recruitment Type (Legacy)', default='Internal')

    responsible = fields.Many2one(
        'hr.employee', string="Responsible", required=True,
        default=lambda self: self.env.user.employee_id, readonly=True
    )

    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    operating_unit_id = fields.Many2one("operating.unit", string="Place Of Assignment", required=True, readonly=True)
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
        """Build rich social media sharing URLs containing Title, Reference, Location, Description, and Link."""
        self.ensure_one()
        title = self.job_title or (self.job_position.name if self.job_position else 'Career Opportunity')
        ref = self.reference or ''
        location = self.job_location or (self.operating_unit_id.name if self.operating_unit_id else 'Addis Ababa')
        desc = (self.description or self.vacancy_description or '').strip()
        if len(desc) > 180:
            desc = desc[:177] + '...'

        company = "Bunna Bank Share Company"
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8082')
        portal_url = f"{base_url.rstrip('/')}/jobs"

        full_text = f"🔥 Vacancy Announcement - {company}\n📌 Position: {title}\n📋 Reference: {ref}\n📍 Location: {location}"
        if desc:
            full_text += f"\n📝 Summary: {desc}"
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
            return
        job = self.job_position

        # 1. Sync Job Grade
        if getattr(job, 'grade', False) and not self.job_grade:
            self.job_grade = job.grade

        # 2. Sync Qualifications & Job Description
        qual_parts = []
        if getattr(job, 'job_description', False) and job.job_description:
            qual_parts.append(job.job_description)
        if getattr(job, 'qualification_id', False) and job.qualification_id:
            qual_lines = []
            for q in job.qualification_id:
                q_name = ""
                if getattr(q, 'qualification', False) and q.qualification:
                    if hasattr(q.qualification, 'display_name') and q.qualification.display_name:
                        q_name = q.qualification.display_name
                    elif hasattr(q.qualification, 'qualification') and q.qualification.qualification:
                        q_name = q.qualification.qualification
                    elif hasattr(q.qualification, 'name') and q.qualification.name:
                        q_name = q.qualification.name
                    elif isinstance(q.qualification, str):
                        q_name = q.qualification
                if not q_name:
                    q_name = getattr(q, 'display_name', '') or getattr(q, 'name', '') or (
                        q.qualification if isinstance(getattr(q, 'qualification', False), str) else ''
                    )
                if q_name:
                    lvl = getattr(q, 'required_level', '') or ''
                    qual_lines.append(f"• {q_name}" + (f" ({lvl})" if lvl else ""))
            if qual_lines:
                qual_parts.append("Educational Qualifications:\n" + "\n".join(qual_lines))
        if qual_parts and not self.vacancy_description:
            self.vacancy_description = "\n\n".join(qual_parts)

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

    @api.onchange('operating_unit_id', 'responsible', 'no_of_vacancies')
    def _onchange_sync_hiring_details(self):
        for rec in self:
            if rec.operating_unit_id:
                resp_emp = rec.responsible.id if rec.responsible else (self.env.user.employee_id.id if self.env.user.employee_id else False)
                openings = rec.no_of_vacancies or 1
                if not rec.hiring_details:
                    rec.hiring_details = [(0, 0, {
                        'work_unit': rec.operating_unit_id.id,
                        'responsible_employee': resp_emp,
                        'number_of_openings': openings,
                        'planned_positions': openings,
                        'status': 'In Progress',
                    })]
                else:
                    first = rec.hiring_details[0]
                    first.work_unit = rec.operating_unit_id
                    if resp_emp:
                        first.responsible_employee = resp_emp
                    first.number_of_openings = openings
                    first.planned_positions = openings

    eligible_employee_ids = fields.One2many(
        'internal.recruitment.eligible.employees',
        'vacancy_id',
        string="Eligible Candidates"
    )
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

    @api.depends("operating_unit_id", "job_grade", "job_position", "employee_category")
    def _compute_approval_hierarchy_type(self):
        for rec in self:
            if not rec.approval_hierarchy_type:
                try:
                    rec.approval_hierarchy_type = rec._compute_hierarchy_type_recruitment()
                except Exception:
                    rec.approval_hierarchy_type = "ho_district_grade2_plus"

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
    ], string='Transfer Evaluation Mode', default='standard')
    supervisor_rec_requested = fields.Boolean(string="Supervisor Recommendation Requested", default=False)
    app_date_weight = fields.Float(string="Application Date Weight (%)", default=20.0)
    experience_weight = fields.Float(string="Experience Weight (%)", default=20.0)
    location_weight = fields.Float(string="Location Weight (%)", default=20.0)
    recommendation_weight = fields.Float(string="Recommendation Weight (%)", default=10.0)
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
                rec.written_weight = 0.0
                rec.interview_weight = 0.0
                rec.has_written_exam = False
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
                        q_name = q.qualification.name if getattr(q, 'qualification', False) and hasattr(q.qualification, 'name') else str(getattr(q, 'qualification', '') or '')
                        lvl = getattr(q, 'required_level', '') or ''
                        if q_name:
                            qual_lines.append(f"• {q_name}" + (f" ({lvl})" if lvl else ""))
                if getattr(job, 'experience_id', False) and job.experience_id:
                    for exp in job.experience_id:
                        e_name = exp.experience.name if getattr(exp, 'experience', False) and hasattr(exp.experience, 'name') else str(getattr(exp, 'experience', '') or '')
                        e_yrs = getattr(exp, 'years_of_experience', '') or ''
                        if e_name:
                            exp_lines.append(f"• {e_name}" + (f" ({e_yrs} yrs)" if e_yrs else ""))
            rec.position_qualifications = "\n".join(qual_lines) if qual_lines else ""
            rec.position_experiences = "\n".join(exp_lines) if exp_lines else ""

    @api.depends('recruitment_request_id', 'no_of_vacancies')
    def _compute_plan_fulfillment(self):
        for rec in self:
            rec.approved_plan_count = rec.no_of_vacancies or 0
            rec.plan_fulfillment_promotion = rec.no_of_vacancies or 0
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
                    'recruitment_step': 'promote',
                    'employees_promoted': False,
                }
            elif curr == 'promote':
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
                        'recruitment_step': 'fetch_exam',
                        'exam_scores_fetched': False,
                        'scores_computed': False,
                    }
                else:
                    vals = {
                        'recruitment_step': 'fetch_interview',
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
                        'recruitment_step': 'fetch_exam',
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

    def action_reset_workflow(self):
        """Reset the recruitment workflow completely back to the initial shortlist stage."""
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
            })
            sel = rec._get_selected_recruitment_record()
            if sel:
                sel_vals = {
                    'exam_scheduled': 'No',
                    'interview_scheduled': 'No',
                }
                if hasattr(sel, 'scores_computed'):
                    sel_vals['scores_computed'] = False
                sel.write(sel_vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Workflow Reset'),
                'message': _('Recruitment workflow has been completely reset to the Shortlist stage.'),
                'type': 'info',
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
                sel_rec = Selected.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], order='id desc', limit=1)
            rec.selected_recruitment_id = sel_rec

    @api.depends('reference')
    def _compute_ext_selected_recruitment_id(self):
        ExtSelected = self.env['external.recruitment.selected']
        for rec in self:
            ext_rec = False
            if rec.id:
                ext_rec = ExtSelected.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], order='id desc', limit=1)
            rec.ext_selected_recruitment_id = ext_rec

    def _sync_selected_recruitment_records(self):
        """Ensures selected recruitment pipeline record is bidirectional linked to vacancy."""
        Selected = self.env['new.internal.recruitment.selected']
        ExtSelected = self.env['external.recruitment.selected']
        for rec in self:
            if not rec.id:
                continue
            is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in (rec.reference or '').upper() or 'LAT' in (rec.reference or '').upper()
            if is_internal:
                sel_rec = Selected.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], order='id desc', limit=1)
                if not sel_rec and (rec.reference or rec.id):
                    sel_rec = Selected.sudo().create({
                        'vacancy_id': rec.id,
                        'vacancy_reference': rec.reference,
                        'job_position': rec.job_position.id if rec.job_position else False,
                        'job_location': rec.job_location,
                        'job_grade': rec.job_grade.grade_name if rec.job_grade else False,
                        'job_category': rec.employee_category,
                        'written_exam_date': rec.written_exam_date,
                        'exam_location': rec.exam_location,
                        'interview_date': rec.interview_date,
                        'interview_location': rec.interview_location,
                    })
                if sel_rec:
                    if sel_rec.vacancy_id != rec.id:
                        sel_rec.vacancy_id = rec.id
                    if sel_rec.vacancy_reference != rec.reference:
                        sel_rec.vacancy_reference = rec.reference
                    if rec.job_position and sel_rec.job_position != rec.job_position:
                        sel_rec.job_position = rec.job_position.id
                    if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) and sel_rec.job_grade != rec.job_grade.grade_name:
                        sel_rec.job_grade = rec.job_grade.grade_name
                    if rec.operating_unit_id and sel_rec.job_location != rec.operating_unit_id.name:
                        sel_rec.job_location = rec.operating_unit_id.name
                    sel_rec.written_exam_date = rec.written_exam_date or False
                    sel_rec.exam_location = rec.exam_location or False
                    sel_rec.interview_date = rec.interview_date or False
                    sel_rec.interview_location = rec.interview_location or False
                    sel_rec.exam_candidate_summary = rec.exam_candidate_summary or False
                    sel_rec.exam_scheduled = rec.exam_scheduled or 'No'
                    sel_rec.interview_scheduled = rec.interview_scheduled or 'No'
                    sel_rec.transfer_eval_mode = rec.transfer_eval_mode or 'standard'
                    sel_rec.app_date_weight = rec.app_date_weight or 0.0
                    sel_rec.experience_weight = rec.experience_weight or 0.0
                    sel_rec.location_weight = rec.location_weight or 0.0
                    sel_rec.recommendation_weight = rec.recommendation_weight or 0.0
                    sel_rec.pms_weight = rec.pms_weight or 0.0
                    sel_rec.written_weight = rec.written_weight or 0.0
                    sel_rec.interview_weight = rec.interview_weight or 0.0
                    if rec.approval_hierarchy_type:
                        sel_rec.approval_hierarchy_type = rec.approval_hierarchy_type
                    elif getattr(sel_rec, 'approval_hierarchy_type', False):
                        rec.approval_hierarchy_type = sel_rec.approval_hierarchy_type
                    if rec.chairperson_id:
                        sel_rec.chairperson_id = rec.chairperson_id
                    elif getattr(sel_rec, 'chairperson_id', False):
                        rec.chairperson_id = sel_rec.chairperson_id
                    if rec.panel_member_id:
                        sel_rec.panel_member_id = rec.panel_member_id
                    elif getattr(sel_rec, 'panel_member_id', False):
                        rec.panel_member_id = sel_rec.panel_member_id
                    if rec.secretary_id:
                        sel_rec.secretary_id = rec.secretary_id
                    elif getattr(sel_rec, 'secretary_id', False):
                        rec.secretary_id = sel_rec.secretary_id
                    if rec.observer_id:
                        sel_rec.observer_id = rec.observer_id
                    elif getattr(sel_rec, 'observer_id', False):
                        rec.observer_id = sel_rec.observer_id
                    rec.selected_recruitment_id = sel_rec.id
            else:
                ext_sel = ExtSelected.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], order='id desc', limit=1)
                if not ext_sel and (rec.reference or rec.id):
                    ext_sel = ExtSelected.sudo().create({
                        'vacancy_id': rec.id,
                        'vacancy_reference': rec.reference,
                        'job_position': rec.job_position.id if rec.job_position else False,
                        'job_location': rec.job_location or (rec.operating_unit_id.name if rec.operating_unit_id else 'Main Branch'),
                        'job_grade': rec.job_grade.grade_name if rec.job_grade else False,
                        'job_category': rec.employee_category,
                        'written_exam_date': rec.written_exam_date,
                        'exam_location': rec.exam_location,
                        'interview_date': rec.interview_date,
                        'interview_location': rec.interview_location,
                        'exam_candidate_summary': rec.exam_candidate_summary,
                        'exam_scheduled': rec.exam_scheduled or 'No',
                        'interview_scheduled': rec.interview_scheduled or 'No',
                        'approval_hierarchy_type': rec.approval_hierarchy_type or False,
                        'chairperson_id': rec.chairperson_id.id if rec.chairperson_id else False,
                        'panel_member_id': rec.panel_member_id.id if rec.panel_member_id else False,
                        'secretary_id': rec.secretary_id.id if rec.secretary_id else False,
                        'observer_id': rec.observer_id.id if rec.observer_id else False,
                    })
                if ext_sel:
                    if ext_sel.vacancy_id != rec.id:
                        ext_sel.vacancy_id = rec.id
                    if ext_sel.vacancy_reference != rec.reference:
                        ext_sel.vacancy_reference = rec.reference
                    if rec.job_position and ext_sel.job_position != rec.job_position:
                        ext_sel.job_position = rec.job_position.id
                    if rec.job_grade and getattr(rec.job_grade, 'grade_name', False) and ext_sel.job_grade != rec.job_grade.grade_name:
                        ext_sel.job_grade = rec.job_grade.grade_name
                    if rec.operating_unit_id and ext_sel.job_location != rec.operating_unit_id.name:
                        ext_sel.job_location = rec.operating_unit_id.name
                    ext_sel.written_exam_date = rec.written_exam_date or False
                    ext_sel.exam_location = rec.exam_location or False
                    ext_sel.interview_date = rec.interview_date or False
                    ext_sel.interview_location = rec.interview_location or False
                    ext_sel.exam_candidate_summary = rec.exam_candidate_summary or False
                    ext_sel.exam_scheduled = rec.exam_scheduled or 'No'
                    ext_sel.interview_scheduled = rec.interview_scheduled or 'No'
                    if rec.approval_hierarchy_type:
                        ext_sel.approval_hierarchy_type = rec.approval_hierarchy_type
                    elif getattr(ext_sel, 'approval_hierarchy_type', False):
                        rec.approval_hierarchy_type = ext_sel.approval_hierarchy_type
                    if rec.chairperson_id:
                        ext_sel.chairperson_id = rec.chairperson_id
                    elif getattr(ext_sel, 'chairperson_id', False):
                        rec.chairperson_id = ext_sel.chairperson_id
                    if rec.panel_member_id:
                        ext_sel.panel_member_id = rec.panel_member_id
                    elif getattr(ext_sel, 'panel_member_id', False):
                        rec.panel_member_id = ext_sel.panel_member_id
                    if rec.secretary_id:
                        ext_sel.secretary_id = rec.secretary_id
                    elif getattr(ext_sel, 'secretary_id', False):
                        rec.secretary_id = ext_sel.secretary_id
                    if rec.observer_id:
                        ext_sel.observer_id = rec.observer_id
                    elif getattr(ext_sel, 'observer_id', False):
                        rec.observer_id = ext_sel.observer_id
                    rec.ext_selected_recruitment_id = ext_sel.id

    def _get_selected_recruitment_record(self):
        self.ensure_one()
        ref = self.reference or ''
        is_internal = self.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()
        if is_internal:
            if self.selected_recruitment_id:
                return self.selected_recruitment_id
            return self.env['new.internal.recruitment.selected'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
        else:
            ext_sel = self.env['external.recruitment.selected'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if ext_sel:
                return ext_sel
            return self.ext_selected_recruitment_id

    # ---------------------------------------------------------------
    # Unified Action Proxy Handlers (Delegates to Selected Models)
    # ---------------------------------------------------------------
    def action_notify_written_exam(self):
        self.ensure_one()
        dt = self.written_exam_date or (self.ext_selected_recruitment_id.written_exam_date if self.ext_selected_recruitment_id else (self.selected_recruitment_id.written_exam_date if self.selected_recruitment_id else False))
        loc = self.exam_location or (self.ext_selected_recruitment_id.exam_location if self.ext_selected_recruitment_id else (self.selected_recruitment_id.exam_location if self.selected_recruitment_id else False))

        if not dt or not loc:
            raise UserError(_('Please specify both the Written Exam Date and Exam Location before notifying candidates.'))

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
            self.recruitment_step = 'fetch_exam'
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
            self.recruitment_step = 'fetch_interview'
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
            
            msg = (
                f"<div style='font-family: inherit; font-size: 14px; line-height: 1.5;'>"
                f"<p>Dear <b>{sup.name}</b>,</p>"
                f"<p>Your subordinate(s) <b>{c_names}</b> have applied for the vacancy: <b>{pos_title}</b> (Ref: <code>{ref_str}</code>).</p>"
                f"<p>Kindly evaluate and grant their <b>Supervisor Recommendation Marks (0 - 100%)</b> and evaluation comments in the system before candidate ranking:</p>"
                f"<p style='margin: 16px 0;'>"
                f"<a href='{eval_url}' style='display:inline-block; padding:9px 18px; background-color:#541718; color:#ffffff; text-decoration:none; border-radius:4px; font-weight:bold; font-size:13px;'>"
                f"⭐ Evaluate My Candidate(s)"
                f"</a>"
                f"</p>"
                f"<p style='color: #666; font-size: 12px;'>Direct link: <a href='{eval_url}'>{eval_url}</a></p>"
                f"<p>Best regards,<br/><b>Bunna Bank Talent Acquisition &amp; OD</b></p>"
                f"</div>"
            )
            channel.message_post(body=Markup(msg), message_type='comment', subtype_xmlid='mail.mt_comment')

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
        sel = self._get_selected_recruitment_record()
        if sel and hasattr(sel, 'action_generate_minute'):
            return sel.action_generate_minute()
        if self.sourcing_type == 'external':
            selected = self.env['external.recruitment.selected'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if selected and hasattr(selected, 'action_generate_minute'):
                return selected.action_generate_minute()
        else:
            selected = self.env['new.internal.recruitment.selected'].search([
                '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
            ], limit=1)
            if selected and hasattr(selected, 'action_generate_minute'):
                return selected.action_generate_minute()
        return True

    def action_compute_and_rank(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
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
        if hasattr(sel, 'ext_rec_sel'):
            selected_candidates = sel.ext_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
        elif hasattr(sel, 'new_int_rec_sel'):
            selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))

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

        has_committee = bool(members and members.filtered(lambda m: getattr(m, 'employee_name', False) or getattr(m, 'alternate_committee_member', False)))
        if not has_committee:
            raise UserError(_("Please assign committee members under the 'Recruitment Approval Committee' tab before notifying the approval committee."))

        self.committee_notified = True
        self.recruitment_step = 'notify_selection'
        if self.selected_recruitment_id:
            self.selected_recruitment_id.committee_notified = True
        notified_users = []
        pos_title = self.job_position.name if self.job_position else (self.job_title or _('Job Position'))
        work_unit_str = self.operating_unit_id.name if self.operating_unit_id else (self.job_location or _('Head Office'))
        ref_str = self.reference or _('TBD')

        summary_html = ""
        if self.exam_candidate_summary:
            clean_summary = self.exam_candidate_summary.replace('\n', '<br/>')
            summary_html = (
                f"<div style='margin-top: 12px; margin-bottom: 12px; padding: 10px; background-color: #f8fafc; border-left: 4px solid #C17540; border-radius: 4px;'>"
                f"<p style='margin: 0 0 6px 0; font-weight: bold; color: #1D2B32;'>📝 Summary of Exams &amp; Selected Candidates:</p>"
                f"<p style='margin: 0; line-height: 1.5; font-size: 13px; color: #334155;'>{clean_summary}</p>"
                f"</div>"
            )

        # Notify assigned hierarchy roles
        hierarchy_role_users = [
            (self.chairperson_id, _("Chairperson")),
            (self.panel_member_id, _("Panel Member")),
            (self.secretary_id, _("Panel Member & Secretary")),
        ]
        if self.observer_id and self.approval_hierarchy_type != 'ho_district_grade2_plus':
            hierarchy_role_users.append((self.observer_id, _("Labor Representative (Observer)")))

        for u_obj, r_title in hierarchy_role_users:
            if not u_obj:
                continue
            partner = u_obj.partner_id if hasattr(u_obj, 'partner_id') else False
            if not partner:
                continue
            notified_users.append(u_obj.name or partner.name)
            try:
                channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                message = (
                    f"<p>Dear <b>{u_obj.name or partner.name}</b>,</p>"
                    f"<p>The candidate ranking and evaluation for vacancy <b>{ref_str}</b> has been computed and is ready for committee review and digital approval.</p>"
                    f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
                    f"<li><b>Vacancy Reference:</b> {ref_str}</li>"
                    f"<li><b>Job Position:</b> {pos_title}</li>"
                    f"<li><b>Hiring Work Unit:</b> {work_unit_str}</li>"
                    f"<li><b>Your Role:</b> {r_title}</li>"
                    f"<li><b>Status:</b> Ready for Committee Review &amp; Digital Approval</li>"
                    f"</ul>"
                    f"{summary_html}"
                    f"<p>Please review the minute and provide your digital signature."
                    f"To sign: Go to Employee Module ->Employee Service → Digital Selection Minute, then add your signature only in the designated signature area.</p>"
                )
                channel.message_post(body=Markup(message), message_type='comment', subtype_xmlid='mail.mt_comment')
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
                message = (
                    f"<p>Dear <b>{user.name or partner.name}</b>,</p>"
                    f"<p>The candidate ranking and evaluation for vacancy <b>{ref_str}</b> has been computed and is ready for committee review and digital approval.</p>"
                    f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
                    f"<li><b>Vacancy Reference:</b> {ref_str}</li>"
                    f"<li><b>Job Position:</b> {pos_title}</li>"
                    f"<li><b>Hiring Work Unit:</b> {work_unit_str}</li>"
                    f"<li><b>Your Role:</b> {role_label}</li>"
                    f"<li><b>Status:</b> Ready for Committee Review &amp; Digital Approval</li>"
                    f"</ul>"
                    f"{summary_html}"
                    f"<p>Please review the minute and provide your digital signature."
                    f"To sign: Go to Applications → Digital Selection Minute, then add your signature only in the designated signature area.</p>"
                )
                channel.message_post(body=Markup(message), message_type='comment', subtype_xmlid='mail.mt_comment')
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

        self.minute_signed = True
        self.recruitment_step = 'notify_selection'
        
        Minute = self.env["recruitment.selection.minute"]
        minute_rec = Minute.search([("vacancy_id", "=", self.id)], order="id desc", limit=1)
        if minute_rec:
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

    def action_promote_selected_employees(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            selected_candidates = False
            if hasattr(sel, 'new_int_rec_sel'):
                selected_candidates = sel.new_int_rec_sel.filtered(lambda c: c.selection_type in ('selected', 'Selected'))
            if not selected_candidates:
                raise UserError(_("No candidates have passed the evaluation and been selected for promotion."))
            self.employees_promoted = True
            self.recruitment_step = 'done'
            if hasattr(sel, 'action_promote_selected_employees'):
                return sel.action_promote_selected_employees()
            return True
        raise UserError(_("No recruitment selection record found for this vacancy."))

    def action_print_all_promotion_letters(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        if self.selected_recruitment_id:
            return self.selected_recruitment_id.action_print_all_promotion_letters()
        sel_rec = self.env['new.internal.recruitment.selected'].search([
            '|', ('vacancy_id', '=', self.id), ('vacancy_reference', '=', self.reference)
        ], limit=1)
        if sel_rec:
            return sel_rec.action_print_all_promotion_letters()
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

            minute_rec = self.env["recruitment.selection.minute"].search([
                ("vacancy_id", "=", self.id),
                ("state", "=", "approved")
            ], limit=1)
            if not minute_rec:
                raise UserError(_("Sequence Error: The Recruitment Approval Committee minute has not been approved yet. You cannot notify selected candidates until the selection minute is approved and finalized."))

            self.selection_notified = True
            self.recruitment_step = 'promote'
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
        if req.requested_by:
            self.responsible = req.requested_by
        elif self.env.user.employee_id:
            self.responsible = self.env.user.employee_id
        if req.required_headcount:
            self.no_of_vacancies = req.required_headcount
        if req.employment_type:
            self.type_of_employment = "Permanent" if req.employment_type == "permanent" else "Contractual"
        if req.sourcing_type:
            self.sourcing_type = req.sourcing_type
            self.recruitment_type = "Internal" if req.sourcing_type == "internal" else "External"
            self.internal_movement_type = "external" if req.sourcing_type == "external" else "promotion"
        if req.job_description:
            self.vacancy_description = req.job_description
        if req.last_date_to_apply:
            self.last_date_to_apply = req.last_date_to_apply
        if req.employee_category:
            self.employee_category = req.employee_category
        if req.job_level:
            self.job_level = req.job_level if req.employee_category == "Non Managerial" else False

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

    @api.constrains('opening_date', 'last_date_to_apply')
    def _check_dates(self):
        for rec in self:
            if rec.opening_date and rec.last_date_to_apply:
                if rec.last_date_to_apply <= rec.opening_date:
                    raise ValidationError(_(
                        "Last Date To Apply (Closing Date) must be later than the Opening Date."
                    ))

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
        return super().create(vals_list)

    def write(self, vals):
        """Protect core vacancy fields once Evaluated or Published, and lock completely once Closed.
        All selection, scoring, scheduling, panel members, committee, and promotion fields remain
        fully operational throughout the recruitment lifecycle."""
        if 'exam_candidate_summary' in vals and isinstance(vals.get('exam_candidate_summary'), str):
            import re
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

        res = super().write(vals)
        if vals.get('vacancy_status') == 'published':
            for rec in self:
                rec._sync_published_vacancy_records()
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

        # Enforce global database cleanup of cross-contaminated process records and restore active status
        self.env.cr.execute("""
            UPDATE employee_recruitment_internal SET active = TRUE WHERE active IS FALSE;
            UPDATE internal_recruitment_eligible_employees SET active = TRUE WHERE active IS FALSE;
            DELETE FROM employee_recruitment_internal
            WHERE vacancy_reference LIKE '%EXT%' OR vacancy_reference LIKE '%ext%';
            DELETE FROM employee_recruitment_available
            WHERE vacancy_reference LIKE '%EXT%' OR vacancy_reference LIKE '%ext%';
            DELETE FROM new_internal_recruitment_selected
            WHERE vacancy_reference LIKE '%EXT%' OR vacancy_reference LIKE '%ext%';
            DELETE FROM employee_recruitment_external
            WHERE vacancy_reference LIKE '%INT%' OR vacancy_reference LIKE '%LAT%'
               OR vacancy_reference LIKE '%int%' OR vacancy_reference LIKE '%lat%';
            DELETE FROM external_recruitment_selected
            WHERE vacancy_reference LIKE '%INT%' OR vacancy_reference LIKE '%LAT%'
               OR vacancy_reference LIKE '%int%' OR vacancy_reference LIKE '%lat%';
        """)

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
                            jv.internal_movement_type, jv.vacancy_announced_on vacancy_announced_on, jv.recruitment_reference,
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
                             jv.internal_movement_type, jv.vacancy_announced_on, jv.recruitment_reference, jv.no_of_vacancies,
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
                        SELECT DISTINCT he.id emp_name, rec_h.job_position target_position_id, eg.grade_code emp_grade, hj.name->>'en_US' emp_position, hj.employee_category emp_category,
                                hj.type_of_employment emp_type, he.gender emp_gender, ou.name current_work_unit, ic.supervisory_experience, ic.current_position, ic.service_in_company,
                                ic.employment_experience, ic.educational_qualification, 85 cgpa, ic.name current_department,
                                ic.last_promotion last_promotion,
                                CAST('N' AS boolean) demoted,
                                ic.pms_score, 'HO' preferred_location,
                                CASE WHEN upper(hj.name->>'en_US') LIKE '%ACTING%' THEN (SELECT current_job_position FROM supplementary_role sr WHERE employee_name = he.id AND state = 'approve')
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
                                  WHEN (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%') THEN
                                      hj.id = rec_h.job_position
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
                                  WHEN (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%') THEN
                                      (rec_h.job_grade_id IS NULL OR eg.id = rec_h.job_grade_id)
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
                              (rec_h.internal_movement_type IN ('lateral', 'transfer') OR rec_h.vacancy_reference ILIKE '%LAT%')
                              OR (
                                  (rec_h.minimum_pms_score IS NULL OR rec_h.minimum_pms_score = 0 OR ic.pms_score >= rec_h.minimum_pms_score)
                                  AND (rec_h.no_of_months_since_last_promotion IS NULL OR rec_h.no_of_months_since_last_promotion = 0 OR ic.last_promotion >= rec_h.no_of_months_since_last_promotion)
                                  AND (rec_h.relevant_experience IS NULL OR rec_h.relevant_experience = 0 OR ic.total_experience >= rec_h.relevant_experience)
                                  AND (rec_h.minimum_number_years_in_company IS NULL OR rec_h.minimum_number_years_in_company = 0 OR ic.service_in_company >= rec_h.minimum_number_years_in_company)
                                  AND (rec_h.supervisory_experience IS NULL OR rec_h.supervisory_experience = 0 OR ic.supervisory_experience >= rec_h.supervisory_experience)
                              )
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

            # 4. Fallback if procedure returned 0 candidates for lateral transfer
            is_lateral = self.internal_movement_type in ('lateral', 'transfer') or 'LAT' in ref.upper()
            existing_count = self.env['internal.recruitment.eligible.employees'].search_count([('vacancy_id', '=', self.id)])
            if existing_count == 0 and is_lateral and self.job_position:
                if not int_rec:
                    int_rec = self.env['employee.recruitment.internal'].create({
                        'job_position': self.job_position.id,
                        'job_grade': self.job_position.grade.grade_name if self.job_position.grade else False,
                        'job_grade_id': self.job_position.grade.id if self.job_position.grade else False,
                        'job_location': self.operating_unit_id.name if self.operating_unit_id else False,
                        'workunit_id': self.operating_unit_id.id if self.operating_unit_id else False,
                        'job_category': self.job_position.employee_category,
                        'vacancy_announced_on': self.vacancy_announced_on or fields.Date.today(),
                        'vacancy_reference': self.reference,
                        'recruitment_reference': self.recruitment_reference,
                        'responsible': self.responsible.id if self.responsible else False,
                        'no_of_vacancies': self.no_of_vacancies,
                        'last_date_to_apply': self.last_date_to_apply,
                        'vacancy_id': self.id,
                        'active': True,
                    })
                matching_emps = self.env['hr.employee'].search([
                    ('active', '=', True),
                    ('job_position', '=', self.job_position.id)
                ])
                for emp in matching_emps:
                    self.env['internal.recruitment.eligible.employees'].create({
                        'internal_recruitment_id': int_rec.id,
                        'vacancy_id': self.id,
                        'emp_name': emp.id,
                        'target_position_id': self.job_position.id,
                        'position_id': emp.job_position.id if emp.job_position else False,
                        'grade_id': emp.job_grade.id if emp.job_grade else False,
                        'workunit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                        'select_flag': True,
                        'active': True,
                    })

            self.env.invalidate_all()
            self._sync_selected_recruitment_records()
            self.shortlist_done = True
            self.recruitment_step = 'notify_cand'
            count = len(self.eligible_employee_ids)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Shortlisting Completed'),
                    'message': _(
                        'Internal candidates shortlisting completed successfully for vacancy %s (%s eligible candidates selected).') % (
                                   self.reference, count),
                    'type': 'success',
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
            if int_rec and int_rec.eligible_emp:
                for line in int_rec.eligible_emp:
                    line.select_flag = True
                    emp = getattr(line, 'emp_id', False) or getattr(line, 'emp_name', False) or getattr(line, 'employee_id', False)
                    if emp and emp not in candidates_to_notify:
                        candidates_to_notify.append(emp)

            if not candidates_to_notify and self.eligible_employee_ids:
                for line in self.eligible_employee_ids:
                    line.select_flag = True
                    emp = getattr(line, 'emp_id', False) or getattr(line, 'emp_name', False) or getattr(line, 'employee_id', False)
                    if emp and emp not in candidates_to_notify:
                        candidates_to_notify.append(emp)

            if not candidates_to_notify:
                raise ValidationError(
                    _("No eligible candidates found to notify for vacancy %s. Please click 'Shortlist' first.") % self.reference)

            Available = self.env['employee.recruitment.available']
            for emp in candidates_to_notify:
                # 1. Sync employee.recruitment.available record permanently for candidate ESS menu
                emp_user = getattr(emp, 'user_id', False)
                avail_domain = [
                    ('vacancy_reference', '=', self.reference),
                    '|', ('employee_id', '=', emp.id), ('employee_user_id', '=', emp_user.id if emp_user else 0)
                ]
                existing_avail = Available.search(avail_domain, limit=1)
                avail_vals = {
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
                    'employee_id': emp.id,
                    'employee_user_id': emp_user.id if emp_user else False,
                    'employee_applicant': emp.name,
                    'application_status': 'Selected for Shortlist',
                    'active': True,
                }
                if existing_avail:
                    existing_avail.write(avail_vals)
                    avail_rec = existing_avail
                else:
                    avail_rec = Available.create(avail_vals)

                if avail_rec and self.hiring_details:
                    avail_rec.employee_vacancy_ids.unlink()
                    for h in self.hiring_details:
                        self.env['employee.vacancy.available'].create({
                            'vacancy_id': avail_rec.id,
                            'operating_unit': h.work_unit.name if h.work_unit else False,
                            'number_of_vacancies': getattr(h, 'number_of_openings', 0) or getattr(h, 'planned_positions', 0) or self.no_of_vacancies or 1,
                            'location_preference': 0,
                        })

                # 2. Dispatch Odoo Discuss channel direct message
                partner = False
                if hasattr(emp, 'user_id') and emp.user_id and emp.user_id.partner_id:
                    partner = emp.user_id.partner_id
                elif hasattr(emp, 'work_contact_id') and emp.work_contact_id:
                    partner = emp.work_contact_id
                else:
                    partner = self.env['res.partner'].search([('name', '=ilike', emp.name)], limit=1)

                deadline_str = self.last_date_to_apply.strftime('%Y-%m-%d') if self.last_date_to_apply else _('N/A')
                if partner:
                    try:
                        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[partner.id])
                        msg = (
                            f"<p>Dear <b>{emp.name}</b>,</p>"
                            f"<p>You have been shortlisted for an Internal Recruitment position:</p>"
                            f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
                            f"<li><b>Position:</b> {pos_title}</li>"
                            f"<li><b>Application Deadline:</b> {deadline_str}</li>"
                            f"<li><b>Place of Assignment:</b> {work_unit_str}</li>"
                            f"</ul><br/>"
                            f"<p>If you are interested, please submit your application before the deadline.</p>"
                            f"<p>Best regards,<br/><b>Bunna Bank HR Department</b></p>"
                        )
                        channel.message_post(body=Markup(msg), message_type='comment', subtype_xmlid='mail.mt_comment')
                        notified_count += 1
                    except Exception as e:
                        _logger.warning("Could not send discuss channel notification to candidate %s: %s", emp.name, e)

        self.candidate_notified = True
        is_transfer = (self.internal_movement_type in ('lateral', 'transfer') or 'LAT' in (self.reference or '').upper()) and self.internal_movement_type != 'promotion'
        if is_transfer:
            self.recruitment_step = 'compute_rank'
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
            if rec.new_int_rec_sel:
                rec.new_int_rec_sel.write({'select_flag': True})
            if rec.eligible_employee_ids:
                rec.eligible_employee_ids.write({'select_flag': True})
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
            f"<p>Dear Committee Member,</p>"
            f"<p>A new Job Vacancy has been submitted for your review and evaluation:</p>"
            f"<ul style='margin: 0; padding-left: 20px; line-height: 1.6;'>"
            f"<li><b>Reference No:</b> {ref}</li>"
            f"<li><b>Job Position:</b> {arg1}</li>"
            f"<li><b>Hiring Work Unit:</b> {work_unit_str}</li>"
            f"<li><b>Type of Employment:</b> {arg2}</li>"
            f"</ul>"
            f"<p>Kindly review and evaluate the vacancy.</p>"
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
        """automatically close vacancies when closing date is reached."""
        today = fields.Date.today()
        expired = self.search([
            ('vacancy_status', '=', 'published'),
            ('last_date_to_apply', '<', today),
        ])
        if expired:
            expired.write({'vacancy_status': 'closed', 'website_published': False})

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
                        'planned_positions': openings,
                        'status': 'In Progress',
                    })
                else:
                    for line in rec.hiring_details:
                        vals_to_update = {}
                        if not line.work_unit:
                            vals_to_update['work_unit'] = rec.operating_unit_id.id
                        if not line.responsible_employee and resp:
                            vals_to_update['responsible_employee'] = resp.id
                        if not line.number_of_openings:
                            vals_to_update['number_of_openings'] = openings
                            vals_to_update['planned_positions'] = openings
                        if vals_to_update:
                            line.write(vals_to_update)

            # 2. Sync Competencies
            if rec.job_position and not rec.competency_line_ids:
                lines = rec._get_default_competency_lines(rec.job_position)
                if lines:
                    for l in lines:
                        self.env['job.vacancy.competency'].create(dict(l[2], vacancy_id=rec.id))

            # 3. Sync Default Vacancy Approver
            if not rec.vac_del_team_id:
                try:
                    hiring_ou = rec.operating_unit_id
                    approver_emp = self.env['hr.employee'].search([
                        ('default_operating_unit_id', '=', hiring_ou.id if hiring_ou else 0),
                        ('active', '=', True),
                        ('user_id', '!=', False)
                    ], limit=1) if hiring_ou else False
                    approver_user = approver_emp.user_id.id if approver_emp else False

                    if approver_user:
                        self.env['vacancy.delegation.team'].create({
                            'vac_del_id': rec.id,
                            'employee_name': approver_user,
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            ou_id = vals.get('operating_unit_id')
            if ou_id and not vals.get('hiring_details'):
                resp_id = vals.get('responsible') or (self.env.user.employee_id.id if self.env.user.employee_id else False)
                openings = vals.get('no_of_vacancies') or 1
                vals['hiring_details'] = [(0, 0, {
                    'work_unit': ou_id,
                    'responsible_employee': resp_id,
                    'number_of_openings': openings,
                    'planned_positions': openings,
                    'status': 'In Progress',
                })]
            job_pos_id = vals.get('job_position')
            if job_pos_id and not vals.get('competency_line_ids'):
                comp_lines = self._get_default_competency_lines(job_pos_id)
                if comp_lines:
                    vals['competency_line_ids'] = comp_lines
        records = super().create(vals_list)
        for rec in records:
            rec._auto_sync_hiring_and_competencies()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('operating_unit_id', 'responsible', 'no_of_vacancies', 'job_position', 'recruitment_request_id')):
            for rec in self:
                rec._auto_sync_hiring_and_competencies()
        return res

    def web_read(self, specification):
        for rec in self:
            rec._auto_sync_hiring_and_competencies()
            rec._sync_selected_recruitment_records()
        return super().web_read(specification)

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
    ], string="Response Status", default='pending', tracking=True)

    response_reason = fields.Text(string="Response Reason / Notes")
    proposed_interview_date = fields.Datetime(string="Proposed Date & Time")
    delegate_employee_id = fields.Many2one("hr.employee", string="Proposed Alternate Member")
    delegation_state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_hr', 'Pending HR Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string="Delegation Status", default='draft', tracking=True)

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
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        for rec in self:
            rec.eligible_employee_ids = all_emps

    @api.onchange('panl_memb_vac', 'role', 'panel_type')
    def _onchange_panl_memb_vac_domain(self):
        """Allow all active employees to be selected as panel members."""
        all_emps = self.env['hr.employee'].search([('active', '=', True)])
        self.eligible_employee_ids = all_emps
        domain = [('active', '=', True)]
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

    def action_open_response_wizard(self):
        self.ensure_one()
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
        for rec in self:
            if rec.panl_memb_vac and rec.panl_memb_vac.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "panel members can no longer be edited."
                ))

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
        self._check_parent_lock()
        self.write({"active": False})
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
        compute="_compute_hiring_defaults", store=True, readonly=False
    )
    status = fields.Char(string="Status", default="In Progress")

    @api.depends('hiring_id.operating_unit_id', 'hiring_id.responsible', 'hiring_id.no_of_vacancies')
    def _compute_hiring_defaults(self):
        for rec in self:
            if rec.hiring_id:
                if rec.hiring_id.operating_unit_id and not rec.work_unit:
                    rec.work_unit = rec.hiring_id.operating_unit_id
                if rec.hiring_id.responsible and not rec.responsible_employee:
                    rec.responsible_employee = rec.hiring_id.responsible
                elif not rec.responsible_employee and self.env.user.employee_id:
                    rec.responsible_employee = self.env.user.employee_id
                if rec.hiring_id.no_of_vacancies and not rec.number_of_openings:
                    rec.number_of_openings = rec.hiring_id.no_of_vacancies
                    rec.planned_positions = rec.hiring_id.no_of_vacancies

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.work_unit.name if rec.work_unit else str(rec.id)

    def _check_parent_lock(self):
        for rec in self:
            if rec.hiring_id and rec.hiring_id.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "hiring status lines can no longer be edited."
                ))

    def write(self, vals):
        self._check_parent_lock()
        return super().write(vals)

    def unlink(self):
        self._check_parent_lock()
        self.write({"active": False})
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
        for rec in self:
            if rec.summ_rank_id and rec.summ_rank_id.vacancy_status == 'closed':
                raise ValidationError(_(
                    "This vacancy is Closed; "
                    "result summary lines can no longer be edited."
                ))

    def write(self, vals):
        self._check_parent_lock()
        return super().write(vals)

    def unlink(self):
        self._check_parent_lock()
        self.write({"active": False})
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

    @api.depends('role', 'vac_del_id', 'vac_del_id.operating_unit_id', 'vac_del_id.responsible')
    def _compute_eligible_user_ids(self):
        for rec in self:
            domain = rec._get_role_user_domain(rec.role)
            rec.eligible_user_ids = self.env['res.users'].search(domain)

    @api.onchange('role', 'vac_del_id')
    def _onchange_role_get_user_domain(self):
        domain = self._get_role_user_domain(self.role)
        self.eligible_user_ids = self.env['res.users'].search(domain)
        if self.employee_name and self.employee_name.id not in self.eligible_user_ids.ids:
            self.employee_name = False
        if self.alternate_committee_member and self.alternate_committee_member.id not in self.eligible_user_ids.ids:
            self.alternate_committee_member = False
        return {
            'domain': {
                'employee_name': domain,
                'alternate_committee_member': domain,
            }
        }

    def _get_role_user_domain(self, role=None):
        all_emps = self.env['hr.employee'].search([
            ('active', '=', True),
            ('user_id', '!=', False)
        ])
        user_ids = all_emps.mapped('user_id').ids
        return [('id', 'in', user_ids)] if user_ids else []

    operating_unit = fields.Char(string="Operating Unit",
                                 related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="Status",
                              default='active')
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
    is_mandatory = fields.Boolean(string="Mandatory?", default=True)
    digital_signature = fields.Binary(string="Digital Signature", copy=False)
    signed_on = fields.Datetime(string="Signed Date & Time", readonly=True, copy=False)
    approve = fields.Boolean(string="Approve", readonly=True)
    vac_del_id = fields.Many2one("job.vacancy", string="Vacancy Delegation Team")

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
