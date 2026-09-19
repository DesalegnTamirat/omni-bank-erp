from odoo import api, models, fields, _
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
from datetime import date
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

JOB_VACANCY_TYPE_CODE_MAP = {
    'internal': 'INT',
    'promotion': 'INT',
    'lateral': 'LAT',
    'transfer': 'LAT',
    'external': 'EXT',
}

LOCKED_ALLOWED_FIELDS = {
    'vacancy_status', 'status', 'state', 'reference', 'message_ids',
    'message_follower_ids', 'activity_ids', 'website_published',
    'eligible_employee_ids', 'new_int_rec_sel', 'new_int_rec_panel',
    'recr_selected_team_id', 'pms_weight', 'written_weight', 'interview_weight', 'has_written_exam', 'transfer_eval_mode',
    'app_date_weight', 'experience_weight', 'location_weight', 'recommendation_weight',
    'written_exam_date', 'exam_location', 'interview_date', 'interview_location',
    'recruitment_step', 'shortlist_done', 'candidate_notified', 'exam_notified',
    'interview_notified', 'committee_notified', 'minute_signed', 'employees_promoted',
    'selected_recruitment_id',
}


class JobVacancy(models.Model):
    _name = 'job.vacancy'
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

    has_written_exam = fields.Boolean(
        string="Requires Written Exam",
        default=True,
        compute="_compute_has_written_exam",
        store=True,
        readonly=False,
        help="If enabled, candidates undergo a written exam before interview notification. If disabled, written exam steps are skipped."
    )

    transfer_eval_mode = fields.Selection([
        ('standard', 'Full Assessment (PMS + Exam + Interview)'),
        ('interview_only', 'Interview & PMS Only (No Written Exam)'),
        ('transfer_matrix_only', 'Pure Transfer Matrix (No Exam & No Interview)'),
    ], string="Transfer Evaluation Mode", default='standard', tracking=True,
       help="Determines assessment requirements for Transfer and Lateral vacancies.")

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

    @api.depends('employee_category', 'internal_movement_type', 'transfer_eval_mode')
    def _compute_has_written_exam(self):
        for rec in self:
            if rec.employee_category == 'Managerial':
                rec.has_written_exam = False
            elif rec.transfer_eval_mode in ('interview_only', 'transfer_matrix_only'):
                rec.has_written_exam = False
            elif not rec.has_written_exam and not rec.id:
                rec.has_written_exam = True

    @api.onchange('employee_category', 'sourcing_type', 'job_level', 'internal_movement_type', 'transfer_eval_mode')
    def _onchange_category_or_sourcing_sync_weights(self):
        """When profile category/sourcing/transfer mode changes, fetch defaults from DB profile."""
        self._sync_weights_from_assessment_profile(force_reset=True)

    @api.onchange('has_written_exam')
    def _onchange_has_written_exam_adjust_weights(self):
        """When exam toggle changes, recalculate weights based on current weights or profile."""
        self._sync_weights_from_assessment_profile(force_reset=False)

    def _sync_weights_from_assessment_profile(self, force_reset=False):
        for rec in self:
            is_transfer = rec.sourcing_type in ('internal', 'both') and rec.internal_movement_type in ('transfer', 'lateral')
            
            if is_transfer and rec.transfer_eval_mode == 'transfer_matrix_only':
                cand_type = "transfer"
            else:
                cand_type = "internal" if rec.sourcing_type in ('internal', 'both') else "external"
            
            existing_pms = rec.pms_weight
            existing_int = rec.interview_weight
            existing_exam = rec.written_weight

            if is_transfer and rec.transfer_eval_mode == 'transfer_matrix_only':
                pms_w = existing_pms if (existing_pms and not force_reset and existing_pms != 100.0) else 30.0
                exam_w = 0.0
                int_w = 0.0
                if force_reset or not rec.app_date_weight: rec.app_date_weight = 20.0
                if force_reset or not rec.experience_weight: rec.experience_weight = 20.0
                if force_reset or not rec.location_weight: rec.location_weight = 20.0
                if force_reset or not rec.recommendation_weight: rec.recommendation_weight = 10.0
            elif is_transfer and rec.transfer_eval_mode == 'interview_only':
                pms_w = existing_pms if (existing_pms and not force_reset) else 50.0
                exam_w = 0.0
                int_w = existing_int if (existing_int and not force_reset) else 50.0
            else:
                pms_w = existing_pms if (existing_pms and not force_reset) else (40.0 if cand_type == "internal" else 0.0)
                exam_w = existing_exam if (existing_exam and not force_reset) else (30.0 if cand_type == "internal" else 60.0)
                int_w = existing_int if (existing_int and not force_reset) else (30.0 if cand_type == "internal" else 40.0)

            if force_reset and "assessment.weight.profile" in self.env:
                role_lvl = "managerial" if rec.employee_category == 'Managerial' else ("junior" if rec.job_level == 'junior' else "non_managerial")
                profile = self.env["assessment.weight.profile"].sudo().get_profile_for_candidate(cand_type, role_lvl)
                if profile and profile.line_ids:
                    pms_w, exam_w, int_w = 0.0, 0.0, 0.0
                    for line in profile.line_ids:
                        if line.component == "pms":
                            pms_w = line.weight_percentage
                        elif line.component == "exam":
                            exam_w = line.weight_percentage
                        elif line.component == "interview":
                            int_w = line.weight_percentage
                        elif line.component == "app_date":
                            rec.app_date_weight = line.weight_percentage
                        elif line.component == "experience":
                            rec.experience_weight = line.weight_percentage
                        elif line.component == "service_location":
                            rec.location_weight = line.weight_percentage
                        elif line.component == "recommendation":
                            rec.recommendation_weight = line.weight_percentage

            if is_transfer and rec.transfer_eval_mode == 'transfer_matrix_only':
                exam_w = 0.0
                int_w = 0.0
                if not rec.app_date_weight: rec.app_date_weight = 20.0
                if not rec.experience_weight: rec.experience_weight = 20.0
                if not rec.location_weight: rec.location_weight = 20.0
                if not rec.recommendation_weight: rec.recommendation_weight = 10.0
                if pms_w == 100.0 or not pms_w: pms_w = 30.0

            elif not rec.has_written_exam:
                exam_w = 0.0
                rec.written_exam_date = False
                rec.exam_location = False
                rec.exam_scheduled = 'No'
                if rec.transfer_eval_mode != 'interview_only':
                    total_rem = pms_w + int_w
                    if total_rem > 0:
                        pms_w = round((pms_w / total_rem) * 100.0, 2)
                        int_w = round(100.0 - pms_w, 2)
                    else:
                        if cand_type == "internal":
                            pms_w, int_w = 60.0, 40.0
                        else:
                            pms_w, int_w = 0.0, 100.0

            rec.pms_weight = pms_w
            rec.written_weight = exam_w
            rec.interview_weight = int_w

    def _sync_to_assessment_weight_profile(self):
        """
        Reverse-sync evaluation weights from job.vacancy to assessment.weight.profile
        so changes in Recruitment module immediately update Assessment System Management profiles.
        """
        if "assessment.weight.profile" not in self.env or self.env.context.get('skip_profile_sync'):
            return

        for rec in self:
            cand_type = "internal" if rec.sourcing_type in ('internal', 'both') else "external"
            role_lvl = "managerial" if rec.employee_category == 'Managerial' else ("junior" if rec.job_level == 'junior' else "non_managerial")
            
            Profile = self.env["assessment.weight.profile"].sudo()
            profile = Profile.get_profile_for_candidate(cand_type, role_lvl)
            if not profile:
                profile = Profile.with_context(skip_profile_sync=True).create({
                    "candidate_type": cand_type,
                    "role_level": role_lvl,
                    "name": f"{cand_type.capitalize()} Applicant - {role_lvl.replace('_', ' ').title()} Weight Profile",
                })

            pms_val = round(rec.pms_weight or 0.0, 2)
            exam_val = round(rec.written_weight if rec.has_written_exam else 0.0, 2)
            int_val = round(rec.interview_weight or 0.0, 2)

            lines = profile.line_ids
            pms_line = lines.filtered(lambda l: l.component == 'pms')
            exam_line = lines.filtered(lambda l: l.component == 'exam')
            int_line = lines.filtered(lambda l: l.component == 'interview')

            line_commands = []
            if pms_line:
                line_commands.append((1, pms_line.id, {'weight_percentage': pms_val}))
            elif pms_val > 0:
                line_commands.append((0, 0, {'component': 'pms', 'weight_percentage': pms_val, 'minimum_pass_score': 50.0}))

            if exam_line:
                line_commands.append((1, exam_line.id, {'weight_percentage': exam_val}))
            elif rec.has_written_exam or exam_val > 0:
                line_commands.append((0, 0, {'component': 'exam', 'weight_percentage': exam_val, 'minimum_pass_score': 50.0}))

            if int_line:
                line_commands.append((1, int_line.id, {'weight_percentage': int_val}))
            elif int_val > 0:
                line_commands.append((0, 0, {'component': 'interview', 'weight_percentage': int_val, 'minimum_pass_score': 50.0}))

            if line_commands:
                profile.with_context(skip_profile_sync=True).sudo().write({'line_ids': line_commands})

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
    request_type = fields.Selection(
        [("planned", "Planned"), ("unplanned", "Unplanned")],
        string="Request Type",
        compute="_compute_request_type",
        store=True,
        readonly=False,
        default="planned",
        help="Planned requests validate against approved manpower plan. Unplanned requests bypass approved plan validation."
    )

    @api.depends('recruitment_request_id', 'recruitment_request_id.request_type')
    def _compute_request_type(self):
        for rec in self:
            if rec.recruitment_request_id and rec.recruitment_request_id.request_type:
                rec.request_type = rec.recruitment_request_id.request_type
            elif not rec.request_type:
                rec.request_type = 'planned'
    approved_plan_count = fields.Integer(
        string='Approved Plan Headcount',
        compute='_compute_approved_plan_count',
        help="Approved manpower plan count for this position and work unit.",
    )
    plan_fulfillment_promotion = fields.Integer(
        string='Approved Promotion Plan',
        compute='_compute_approved_plan_count',
        help="Approved manpower plan count earmarked for promotion.",
    )
    plan_fulfillment_lateral = fields.Integer(
        string='Approved Lateral/Transfer Plan',
        compute='_compute_approved_plan_count',
        help="Approved manpower plan count earmarked for lateral transfer.",
    )
    plan_fulfillment_external = fields.Integer(
        string='Approved External Plan',
        compute='_compute_approved_plan_count',
        help="Approved manpower plan count earmarked for external vacancy.",
    )

    @api.depends('job_position', 'operating_unit_id')
    def _compute_approved_plan_count(self):
        if 'operating.unit.job.position' not in self.env:
            for rec in self:
                rec.approved_plan_count = 0
                rec.plan_fulfillment_promotion = 0
                rec.plan_fulfillment_lateral = 0
                rec.plan_fulfillment_external = 0
            return
        OUJobPosition = self.env['operating.unit.job.position']
        for rec in self:
            if rec.job_position and rec.operating_unit_id:
                ou_id = rec.operating_unit_id._origin.id or rec.operating_unit_id.id
                job_id = rec.job_position._origin.id or rec.job_position.id
                ou_job = OUJobPosition.search([
                    ('operating_unit_id', '=', ou_id),
                    ('job_position_id', '=', job_id),
                ], limit=1)
                if ou_job:
                    rec.approved_plan_count = ou_job.approved_plan_count or 0
                    rec.plan_fulfillment_promotion = ou_job.plan_fulfillment_promotion or 0
                    rec.plan_fulfillment_lateral = ou_job.plan_fulfillment_lateral or 0
                    rec.plan_fulfillment_external = ou_job.plan_fulfillment_external or 0
                else:
                    rec.approved_plan_count = 0
                    rec.plan_fulfillment_promotion = 0
                    rec.plan_fulfillment_lateral = 0
                    rec.plan_fulfillment_external = 0
            else:
                rec.approved_plan_count = 0
                rec.plan_fulfillment_promotion = 0
                rec.plan_fulfillment_lateral = 0
                rec.plan_fulfillment_external = 0

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
        seen_comp_ids = set()
        if comp_rel:
            for comp_line in comp_rel:
                comp_obj = getattr(comp_line, 'competencies', False) or getattr(comp_line, 'competency_id', False)
                if comp_obj and comp_obj.id not in seen_comp_ids:
                    seen_comp_ids.add(comp_obj.id)
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
                    if line.competency_id and line.competency_id.id not in seen_comp_ids:
                        seen_comp_ids.add(line.competency_id.id)
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
                if comp.id not in seen_comp_ids:
                    seen_comp_ids.add(comp.id)
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
    pms_weight = fields.Float(string="PMS Weight (%)", default=0.0)
    written_weight = fields.Float(string="Written Exam Weight (%)", default=0.0)
    interview_weight = fields.Float(string="Interview Weight (%)", default=0.0)
    app_date_weight = fields.Float(string="Application Date Weight (%)", default=20.0)
    experience_weight = fields.Float(string="Total Experience Weight (%)", default=20.0)
    location_weight = fields.Float(string="Location Service Weight (%)", default=20.0)
    recommendation_weight = fields.Float(string="Supervisor Recommendation Weight (%)", default=10.0)
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
    ], string="Recruitment Workflow Step", compute="_compute_recruitment_step", inverse="_inverse_recruitment_step", store=True)

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

    @api.depends('shortlist_done', 'candidate_notified', 'exam_notified',
                 'exam_scores_fetched', 'panel_notified', 'interview_notified', 'interview_scores_fetched',
                 'scores_computed', 'committee_notified', 'minute_signed',
                 'selection_notified', 'employees_promoted', 'eligible_employee_ids', 'ext_rec_sel', 'sourcing_type', 'has_written_exam', 'transfer_eval_mode')
    def _compute_recruitment_step(self):
        for rec in self:
            is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in (rec.reference or '').upper() or 'LAT' in (rec.reference or '').upper()
            if rec.transfer_eval_mode == 'transfer_matrix_only':
                if rec.employees_promoted:
                    rec.recruitment_step = 'done'
                elif rec.selection_notified:
                    rec.recruitment_step = 'promote'
                elif rec.minute_signed or rec.committee_notified:
                    rec.recruitment_step = 'notify_selection'
                elif rec.scores_computed:
                    rec.recruitment_step = 'notify_committee'
                elif rec.candidate_notified or rec.shortlist_done or (is_internal and rec.eligible_employee_ids and len(rec.eligible_employee_ids) > 0):
                    rec.recruitment_step = 'compute_rank'
                else:
                    rec.recruitment_step = 'shortlist'
                continue

            if rec.employees_promoted:
                rec.recruitment_step = 'done'
            elif rec.selection_notified:
                rec.recruitment_step = 'promote'
            elif rec.minute_signed or rec.committee_notified:
                rec.recruitment_step = 'notify_selection'
            elif rec.scores_computed:
                rec.recruitment_step = 'notify_committee'
            elif rec.interview_scores_fetched:
                rec.recruitment_step = 'compute_rank'
            elif rec.interview_notified:
                rec.recruitment_step = 'fetch_interview'
            elif rec.panel_notified:
                rec.recruitment_step = 'notify_interview'
            elif rec.has_written_exam and rec.exam_scores_fetched:
                rec.recruitment_step = 'notify_panel'
            elif rec.has_written_exam and rec.exam_notified:
                rec.recruitment_step = 'fetch_exam'
            elif is_internal and rec.candidate_notified:
                if rec.has_written_exam:
                    rec.recruitment_step = 'notify_exam'
                else:
                    rec.recruitment_step = 'notify_panel'
            elif rec.shortlist_done or (is_internal and rec.eligible_employee_ids and len(rec.eligible_employee_ids) > 0) or (not is_internal and rec.ext_rec_sel and len(rec.ext_rec_sel) > 0):
                if is_internal:
                    rec.recruitment_step = 'notify_cand'
                else:
                    # External applicants applied directly via portal, bypass invitation notification
                    if rec.has_written_exam:
                        rec.recruitment_step = 'notify_exam'
                    else:
                        rec.recruitment_step = 'notify_panel'
            else:
                rec.recruitment_step = 'shortlist'

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

    def _inverse_recruitment_step(self):
        pass

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
                    if rec.written_exam_date and not sel_rec.written_exam_date:
                        sel_rec.written_exam_date = rec.written_exam_date
                    elif sel_rec.written_exam_date and not rec.written_exam_date:
                        rec.written_exam_date = sel_rec.written_exam_date
                    if rec.exam_location and not sel_rec.exam_location:
                        sel_rec.exam_location = rec.exam_location
                    elif sel_rec.exam_location and not rec.exam_location:
                        rec.exam_location = sel_rec.exam_location
                    if rec.interview_date and not sel_rec.interview_date:
                        sel_rec.interview_date = rec.interview_date
                    elif sel_rec.interview_date and not rec.interview_date:
                        rec.interview_date = sel_rec.interview_date
                    if rec.interview_location and not sel_rec.interview_location:
                        sel_rec.interview_location = rec.interview_location
                    elif sel_rec.interview_location and not rec.interview_location:
                        rec.interview_location = sel_rec.interview_location
                    if rec.exam_candidate_summary and not sel_rec.exam_candidate_summary:
                        sel_rec.exam_candidate_summary = rec.exam_candidate_summary
                    elif sel_rec.exam_candidate_summary and not rec.exam_candidate_summary:
                        rec.exam_candidate_summary = sel_rec.exam_candidate_summary
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
                    })
                if ext_sel:
                    if ext_sel.vacancy_id != rec.id:
                        ext_sel.vacancy_id = rec.id
                    if ext_sel.vacancy_reference != rec.reference:
                        ext_sel.vacancy_reference = rec.reference
                    if rec.written_exam_date and not ext_sel.written_exam_date:
                        ext_sel.written_exam_date = rec.written_exam_date
                    elif ext_sel.written_exam_date and not rec.written_exam_date:
                        rec.written_exam_date = ext_sel.written_exam_date
                    if rec.exam_location and not ext_sel.exam_location:
                        ext_sel.exam_location = rec.exam_location
                    elif ext_sel.exam_location and not rec.exam_location:
                        rec.exam_location = ext_sel.exam_location
                    if rec.interview_date and not ext_sel.interview_date:
                        ext_sel.interview_date = rec.interview_date
                    elif ext_sel.interview_date and not rec.interview_date:
                        rec.interview_date = ext_sel.interview_date
                    if rec.interview_location and not ext_sel.interview_location:
                        ext_sel.interview_location = rec.interview_location
                    elif ext_sel.interview_location and not rec.interview_location:
                        rec.interview_location = ext_sel.interview_location
                    if rec.exam_candidate_summary and not ext_sel.exam_candidate_summary:
                        ext_sel.exam_candidate_summary = rec.exam_candidate_summary
                    elif ext_sel.exam_candidate_summary and not rec.exam_candidate_summary:
                        rec.exam_candidate_summary = ext_sel.exam_candidate_summary

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
        self._sync_selected_recruitment_records()
        self.exam_notified = True
        self.recruitment_step = 'fetch_exam'
        sel = self._get_selected_recruitment_record()

        dt = self.written_exam_date or (self.selected_recruitment_id.written_exam_date if self.selected_recruitment_id else False)
        loc = self.exam_location or (self.selected_recruitment_id.exam_location if self.selected_recruitment_id else False) or 'Head Office'

        if sel:
            if not dt and sel.written_exam_date:
                dt = sel.written_exam_date
            if dt and sel.written_exam_date != dt:
                sel.sudo().write({'written_exam_date': dt})
            if loc and sel.exam_location != loc:
                sel.sudo().write({'exam_location': loc})
            return sel.notify_written_exam()

    def action_fetch_exam_score(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        self.exam_scores_fetched = True
        self.recruitment_step = 'notify_panel'
        sel = self._get_selected_recruitment_record()
        if sel:
            res = sel.fetch_exam_score()
            self.env.invalidate_all()
            return res

    def action_notify_interview_panel(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()

        has_panel = False
        if sel:
            if hasattr(sel, 'new_int_rec_panel') and sel.new_int_rec_panel:
                has_panel = any(line.emp_name for line in sel.new_int_rec_panel)
            elif hasattr(sel, 'ext_rec_panel') and sel.ext_rec_panel:
                has_panel = any(line.emp_name for line in sel.ext_rec_panel)

        if not has_panel and hasattr(self, 'panl_memb_vac') and self.panl_memb_vac:
            has_panel = any(getattr(line, 'employee_id', False) or getattr(line, 'panel_member_name', False) for line in self.panl_memb_vac)

        if not has_panel:
            raise UserError(_("No panel members have been added for this vacancy. Please add interview panel members before notifying the panel."))

        self.panel_notified = True
        self.recruitment_step = 'notify_interview'

        dt = self.interview_date or (self.selected_recruitment_id.interview_date if self.selected_recruitment_id else False)
        loc = self.interview_location or (self.selected_recruitment_id.interview_location if self.selected_recruitment_id else False) or 'Head Office'

        if sel:
            if not dt and sel.interview_date:
                dt = sel.interview_date
            if dt and sel.interview_date != dt:
                sel.sudo().write({'interview_date': dt})
            if loc and sel.interview_location != loc:
                sel.sudo().write({'interview_location': loc})
            return sel.notify_interview_panel()

    def action_open_reschedule_wizard(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        sel = self._get_selected_recruitment_record()
        if sel:
            return sel.action_open_reschedule_wizard()

    def action_notify_interview(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        self.interview_notified = True
        self.recruitment_step = 'fetch_interview'
        sel = self._get_selected_recruitment_record()

        dt = self.interview_date or (self.selected_recruitment_id.interview_date if self.selected_recruitment_id else False)
        loc = self.interview_location or (self.selected_recruitment_id.interview_location if self.selected_recruitment_id else False) or 'Head Office'

        if sel:
            if not dt and sel.interview_date:
                dt = sel.interview_date
            if dt and sel.interview_date != dt:
                sel.sudo().write({'interview_date': dt})
            if loc and sel.interview_location != loc:
                sel.sudo().write({'interview_location': loc})
            return sel.notify_interview()

    def action_fetch_interview_score(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        self.interview_scores_fetched = True
        self.recruitment_step = 'compute_rank'
        sel = self._get_selected_recruitment_record()
        if sel:
            res = sel.fetch_interview_score()
            self.env.invalidate_all()
            return res

    def action_compute_and_rank(self):
        self.ensure_one()
        self._sync_selected_recruitment_records()
        self.scores_computed = True
        self.recruitment_step = 'notify_committee'
        sel = self._get_selected_recruitment_record()
        if sel:
            return sel.action_compute_and_rank()

    def action_notify_approval_committee(self):
        """Notify the Recruitment Approval Committee members."""
        self.ensure_one()
        self._sync_selected_recruitment_records()
        self.committee_notified = True
        self.recruitment_step = 'notify_selection'
        if self.selected_recruitment_id:
            self.selected_recruitment_id.committee_notified = True

        members = self.recr_selected_team_id or self.vac_del_team_id
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

        # Log on Process Chatter if available
        if hasattr(self, 'message_post'):
            try:
                self.message_post(body=chatter_msg, partner_ids=partner_ids if partner_ids else None)
            except Exception:
                pass
        elif self.selected_recruitment_id and hasattr(self.selected_recruitment_id, 'message_post'):
            try:
                self.selected_recruitment_id.message_post(body=chatter_msg, partner_ids=partner_ids if partner_ids else None)
            except Exception:
                pass

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
        self.employees_promoted = True
        self.recruitment_step = 'done'
        if self.selected_recruitment_id:
            return self.selected_recruitment_id.action_promote_selected_employees()

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
        self.selection_notified = True
        self.recruitment_step = 'promote'
        if self.selected_recruitment_id:
            return self.selected_recruitment_id.notify_selection()

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

    @api.constrains('no_of_vacancies', 'job_position', 'operating_unit_id', 'internal_movement_type', 'sourcing_type', 'hiring_details', 'recruitment_request_id', 'request_type')
    def _check_no_of_vacancies_vs_approved_plan(self):
        if 'operating.unit.job.position' not in self.env:
            return
        OUJobPosition = self.env['operating.unit.job.position']
        for rec in self:
            # Skip approved plan validation for unplanned requests!
            is_unplanned = (rec.recruitment_request_id and rec.recruitment_request_id.request_type == 'unplanned') or getattr(rec, 'request_type', '') == 'unplanned' or self.env.context.get('default_request_type') == 'unplanned' or self.env.context.get('unplanned')
            if is_unplanned:
                continue
            if not rec.job_position or not rec.operating_unit_id:
                continue
            ou_id = rec.operating_unit_id._origin.id or rec.operating_unit_id.id
            job_id = rec.job_position._origin.id or rec.job_position.id
            ou_job = OUJobPosition.search([
                ('operating_unit_id', '=', ou_id),
                ('job_position_id', '=', job_id),
            ], limit=1)
            if not ou_job:
                continue

            plan_count = ou_job.approved_plan_count or 0
            prom_plan = ou_job.plan_fulfillment_promotion or 0
            lat_plan = ou_job.plan_fulfillment_lateral or 0
            ext_plan = ou_job.plan_fulfillment_external or 0
            has_breakdown = (prom_plan > 0 or lat_plan > 0 or ext_plan > 0)

            # Movement type and sourcing validation against PBMS fulfillment plan
            m_type = rec.internal_movement_type or ('external' if rec.sourcing_type == 'external' else 'promotion')

            if has_breakdown:
                if m_type == 'promotion':
                    if prom_plan <= 0:
                        breakdown_desc = []
                        if lat_plan > 0:
                            breakdown_desc.append(_("Transfer (%s)") % lat_plan)
                        if ext_plan > 0:
                            breakdown_desc.append(_("External (%s)") % ext_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("other sourcing channels")
                        raise ValidationError(_(
                            "Cannot create a Promotion vacancy for '%(job)s' at '%(unit)s'. "
                            "There is no approved plan for Promotion (Approved Promotion Plan: 0). "
                            "The approved plan is earmarked for %(earmarked)s."
                        ) % {
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                            'earmarked': earmarked_str,
                        })
                    if rec.no_of_vacancies and rec.no_of_vacancies > prom_plan:
                        raise ValidationError(_(
                            "The number of opening vacancies (%(openings)s) cannot exceed the "
                            "approved Promotion plan count (%(plan)s) for '%(job)s' at '%(unit)s'."
                        ) % {
                            'openings': rec.no_of_vacancies,
                            'plan': prom_plan,
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                        })
                elif m_type in ('lateral', 'transfer'):
                    if lat_plan <= 0:
                        breakdown_desc = []
                        if prom_plan > 0:
                            breakdown_desc.append(_("Promotion (%s)") % prom_plan)
                        if ext_plan > 0:
                            breakdown_desc.append(_("External (%s)") % ext_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("other sourcing channels")
                        raise ValidationError(_(
                            "Cannot create a Transfer/Lateral vacancy for '%(job)s' at '%(unit)s'. "
                            "There is no approved plan for Transfer/Lateral (Approved Lateral/Transfer Plan: 0). "
                            "The approved plan is earmarked for %(earmarked)s."
                        ) % {
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                            'earmarked': earmarked_str,
                        })
                    if rec.no_of_vacancies and rec.no_of_vacancies > lat_plan:
                        raise ValidationError(_(
                            "The number of opening vacancies (%(openings)s) cannot exceed the "
                            "approved Transfer/Lateral plan count (%(plan)s) for '%(job)s' at '%(unit)s'."
                        ) % {
                            'openings': rec.no_of_vacancies,
                            'plan': lat_plan,
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                        })
                elif m_type == 'external' or rec.sourcing_type == 'external':
                    if ext_plan <= 0:
                        breakdown_desc = []
                        if prom_plan > 0:
                            breakdown_desc.append(_("Promotion (%s)") % prom_plan)
                        if lat_plan > 0:
                            breakdown_desc.append(_("Transfer (%s)") % lat_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("internal sourcing channels")
                        raise ValidationError(_(
                            "Cannot create an External vacancy for '%(job)s' at '%(unit)s'. "
                            "There is no approved plan for External Vacancy (Approved External Plan: 0). "
                            "The approved plan is earmarked for %(earmarked)s."
                        ) % {
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                            'earmarked': earmarked_str,
                        })
                    if rec.no_of_vacancies and rec.no_of_vacancies > ext_plan:
                        raise ValidationError(_(
                            "The number of opening vacancies (%(openings)s) cannot exceed the "
                            "approved External plan count (%(plan)s) for '%(job)s' at '%(unit)s'."
                        ) % {
                            'openings': rec.no_of_vacancies,
                            'plan': ext_plan,
                            'job': rec.job_position.name,
                            'unit': rec.operating_unit_id.name,
                        })

            if rec.no_of_vacancies and rec.no_of_vacancies > plan_count:
                raise ValidationError(_(
                    "The number of opening vacancies (%(openings)s) cannot exceed the "
                    "approved plan count (%(plan)s) for '%(job)s' at '%(unit)s'."
                ) % {
                    'openings': rec.no_of_vacancies,
                    'plan': plan_count,
                    'job': rec.job_position.name,
                    'unit': rec.operating_unit_id.name,
                })

            if rec.hiring_details:
                total_hiring_openings = sum(
                    h.number_of_openings for h in rec.hiring_details
                    if (h.work_unit._origin.id or h.work_unit.id) == ou_id
                )
                cap = plan_count
                if has_breakdown:
                    if m_type == 'promotion':
                        cap = prom_plan
                    elif m_type in ('lateral', 'transfer'):
                        cap = lat_plan
                    elif m_type == 'external' or rec.sourcing_type == 'external':
                        cap = ext_plan
                if total_hiring_openings > cap:
                    raise ValidationError(_(
                        "The total openings in hiring details (%(openings)s) cannot exceed the "
                        "approved plan count (%(plan)s) for '%(job)s' at '%(unit)s'."
                    ) % {
                        'openings': total_hiring_openings,
                        'plan': cap,
                        'job': rec.job_position.name,
                        'unit': rec.operating_unit_id.name,
                    })

    @api.onchange('no_of_vacancies', 'job_position', 'operating_unit_id', 'internal_movement_type', 'sourcing_type', 'recruitment_request_id', 'request_type')
    def _onchange_check_no_of_vacancies_plan(self):
        if 'operating.unit.job.position' not in self.env:
            return
        OUJobPosition = self.env['operating.unit.job.position']
        for rec in self:
            # Skip approved plan warning for unplanned requests!
            is_unplanned = (rec.recruitment_request_id and rec.recruitment_request_id.request_type == 'unplanned') or getattr(rec, 'request_type', '') == 'unplanned' or self.env.context.get('default_request_type') == 'unplanned' or self.env.context.get('unplanned')
            if is_unplanned:
                continue
            if rec.job_position and rec.operating_unit_id:
                ou_id = rec.operating_unit_id._origin.id or rec.operating_unit_id.id
                job_id = rec.job_position._origin.id or rec.job_position.id
                ou_job = OUJobPosition.search([
                    ('operating_unit_id', '=', ou_id),
                    ('job_position_id', '=', job_id),
                ], limit=1)
                if not ou_job:
                    continue

                plan_count = ou_job.approved_plan_count or 0
                prom_plan = ou_job.plan_fulfillment_promotion or 0
                lat_plan = ou_job.plan_fulfillment_lateral or 0
                ext_plan = ou_job.plan_fulfillment_external or 0
                has_breakdown = (prom_plan > 0 or lat_plan > 0 or ext_plan > 0)
                m_type = rec.internal_movement_type or ('external' if rec.sourcing_type == 'external' else 'promotion')

                # If movement type has not been explicitly switched yet, auto-select the available one
                if has_breakdown and not self.env.context.get('default_internal_movement_type'):
                    if lat_plan > 0 and prom_plan <= 0 and m_type == 'promotion':
                        rec.internal_movement_type = 'lateral'
                        m_type = 'lateral'
                    elif prom_plan > 0 and lat_plan <= 0 and m_type in ('lateral', 'transfer'):
                        rec.internal_movement_type = 'promotion'
                        m_type = 'promotion'

                if has_breakdown:
                    if m_type == 'promotion' and prom_plan <= 0:
                        breakdown_desc = []
                        if lat_plan > 0:
                            breakdown_desc.append(_("Transfer (%s)") % lat_plan)
                        if ext_plan > 0:
                            breakdown_desc.append(_("External (%s)") % ext_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("other sourcing channels")
                        return {
                            'warning': {
                                'title': _('No Approved Promotion Plan'),
                                'message': _(
                                    "The approved plan for Promotion is 0 for '%s' at '%s'. "
                                    "The approved plan is earmarked for %s."
                                ) % (rec.job_position.name, rec.operating_unit_id.name, earmarked_str)
                            }
                        }
                    elif m_type in ('lateral', 'transfer') and lat_plan <= 0:
                        breakdown_desc = []
                        if prom_plan > 0:
                            breakdown_desc.append(_("Promotion (%s)") % prom_plan)
                        if ext_plan > 0:
                            breakdown_desc.append(_("External (%s)") % ext_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("other sourcing channels")
                        return {
                            'warning': {
                                'title': _('No Approved Transfer/Lateral Plan'),
                                'message': _(
                                    "The approved plan for Transfer/Lateral is 0 for '%s' at '%s'. "
                                    "The approved plan is earmarked for %s."
                                ) % (rec.job_position.name, rec.operating_unit_id.name, earmarked_str)
                            }
                        }
                    elif (m_type == 'external' or rec.sourcing_type == 'external') and ext_plan <= 0:
                        breakdown_desc = []
                        if prom_plan > 0:
                            breakdown_desc.append(_("Promotion (%s)") % prom_plan)
                        if lat_plan > 0:
                            breakdown_desc.append(_("Transfer (%s)") % lat_plan)
                        earmarked_str = ", ".join(breakdown_desc) or _("internal sourcing channels")
                        return {
                            'warning': {
                                'title': _('No Approved External Plan'),
                                'message': _(
                                    "The approved plan for External Vacancy is 0 for '%s' at '%s'. "
                                    "The approved plan is earmarked for %s."
                                ) % (rec.job_position.name, rec.operating_unit_id.name, earmarked_str)
                            }
                        }

                    # Check exceeding movement type allocation
                    cap = prom_plan if m_type == 'promotion' else (lat_plan if m_type in ('lateral', 'transfer') else ext_plan)
                    if rec.no_of_vacancies and rec.no_of_vacancies > cap:
                        return {
                            'warning': {
                                'title': _('Approved Plan Limit Exceeded'),
                                'message': _(
                                    "The entered vacancies (%s) exceeds the approved %s plan count (%s) for %s at %s."
                                ) % (rec.no_of_vacancies, m_type.capitalize(), cap, rec.job_position.name, rec.operating_unit_id.name)
                            }
                        }

                if rec.no_of_vacancies and rec.no_of_vacancies > plan_count:
                    return {
                        'warning': {
                            'title': _('Approved Plan Limit Exceeded'),
                            'message': _(
                                "The entered vacancies (%s) exceeds the approved "
                                "plan count (%s) for %s at %s."
                            ) % (
                                rec.no_of_vacancies,
                                plan_count,
                                rec.job_position.name,
                                rec.operating_unit_id.name,
                            )
                        }
                    }

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
        records = super().create(vals_list)
        if not self.env.context.get('skip_profile_sync'):
            records._sync_to_assessment_weight_profile()
        return records

    def write(self, vals):
        """Protect core vacancy fields once Evaluated or Published, and lock completely once Closed.
        All selection, scoring, scheduling, panel members, committee, and promotion fields remain
        fully operational throughout the recruitment lifecycle."""
        self._check_parent_lock()
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

        sync_keys = {'written_exam_date', 'exam_location', 'exam_scheduled', 'interview_date', 'interview_location', 'interview_scheduled', 'pms_weight', 'written_weight', 'interview_weight'}
        if sync_keys.intersection(vals.keys()):
            for rec in self:
                rec._sync_schedule_to_selection_models()

        weight_keys = {'pms_weight', 'written_weight', 'interview_weight', 'has_written_exam', 'sourcing_type', 'employee_category', 'job_level'}
        if weight_keys.intersection(vals.keys()) and not self.env.context.get('skip_profile_sync'):
            self._sync_to_assessment_weight_profile()

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

    def _sync_selected_recruitment_records(self):
        """Ensure new.internal.recruitment.selected header and lines are synced with Job Vacancy."""
        Selected = self.env['new.internal.recruitment.selected']
        SelectedCand = self.env['new.internal.recruitment.selected.candidates']

        for rec in self:
            if not rec.reference or rec.reference == _('New'):
                continue
            is_internal = rec.sourcing_type in ('internal', 'both') or 'INT' in rec.reference.upper() or 'LAT' in rec.reference.upper()
            if not is_internal:
                continue

            sel_rec = Selected.search([
                '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
            ], limit=1)

            vals = {
                'vacancy_id': rec.id,
                'vacancy_reference': rec.reference,
                'job_position': rec.job_position.id if rec.job_position else False,
                'job_location': rec.operating_unit_id.name if rec.operating_unit_id else False,
                'job_grade': rec.job_grade.grade_name if rec.job_grade else False,
                'job_category': rec.employee_category,
                'emp_type': rec.type_of_employment,
                'no_of_vacancies': rec.no_of_vacancies,
                'vacancy_announced_on': rec.opening_date or fields.Date.context_today(self),
                'recruitment_reference': rec.recruitment_reference,
            }

            if sel_rec:
                sel_rec.write(vals)
            else:
                delegation_lines = []
                for member in rec.vac_del_team_id:
                    role_val = (member.role or 'panel_member').lower()
                    if 'chair' in role_val:
                        mapped_role = 'chairperson'
                    elif 'sec' in role_val:
                        mapped_role = 'secretary'
                    elif 'observer' in role_val or 'labor' in role_val:
                        mapped_role = 'observer'
                    elif role_val in ('chairperson', 'panel_member', 'secretary', 'observer'):
                        mapped_role = role_val
                    else:
                        mapped_role = 'panel_member'

                    status_val = (member.status or 'active').lower()
                    mapped_status = status_val if status_val in ('active', 'unavailable') else 'active'

                    delegation_lines.append((0, 0, {
                        'role': mapped_role,
                        'employee_name': member.employee_name.id if member.employee_name else False,
                        'alternate_committee_member': member.alternate_committee_member.id if member.alternate_committee_member else False,
                        'status': mapped_status,
                        'approve': False,
                    }))
                vals['recr_selected_team_id'] = delegation_lines
                sel_rec = Selected.create(vals)

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

            # 2. Run internal shortlist procedure safely
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

            # 4. Filter / populate candidates for Transfer / Lateral movement
            if self.internal_movement_type in ('transfer', 'lateral'):
                self._filter_and_populate_transfer_candidates(int_rec)

            self.env.invalidate_all()
            self._sync_selected_recruitment_records()
            self.shortlist_done = True
            if self.transfer_eval_mode == 'transfer_matrix_only':
                self.recruitment_step = 'compute_rank'
            else:
                self.recruitment_step = 'notify_cand'

            count = len(self.eligible_employee_ids.filtered(lambda r: r.select_flag))

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

    def _filter_and_populate_transfer_candidates(self, int_rec=None):
        """
        For Transfer/Lateral vacancies, fetch and shortlist all active employees who have:
        1. Same Job Position or Job Grade
        2. DIFFERENT location (Operating Unit) from the vacancy's Place of Assignment.
        """
        self.ensure_one()
        vac_position = self.job_position
        vac_grade = self.job_grade or (self.job_position.grade if self.job_position else False)
        vac_ou = self.operating_unit_id

        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        transfer_eligible_employees = self.env['hr.employee']

        for emp in all_employees:
            emp_pos = getattr(emp, 'job_id', False) or getattr(emp, 'job_position', False)
            pos_match = bool(emp_pos and vac_position and emp_pos.id == vac_position.id)

            emp_grade = getattr(emp, 'job_grade', False) or getattr(emp, 'grade', False) or (emp_pos.grade if emp_pos and hasattr(emp_pos, 'grade') else False)
            grade_match = bool(emp_grade and vac_grade and emp_grade.id == vac_grade.id)

            emp_ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False)
            diff_location = bool(not emp_ou or not vac_ou or emp_ou.id != vac_ou.id)

            if (pos_match or grade_match) and diff_location:
                transfer_eligible_employees |= emp

        EligibleLine = self.env['internal.recruitment.eligible.employees']
        existing_emp_ids = set(self.eligible_employee_ids.mapped('emp_name').ids)

        for emp in transfer_eligible_employees:
            contract_pms = emp.contract_id.pms_score if hasattr(emp, 'contract_id') and emp.contract_id else 0.0
            emp_pos_name = emp.job_id.name if emp.job_id else (emp.job_position.name if hasattr(emp, 'job_position') and emp.job_position else '')
            emp_grade_name = emp.job_grade.grade_name if hasattr(emp, 'job_grade') and emp.job_grade else (emp.job_id.grade.grade_name if emp.job_id and emp.job_id.grade else '')
            emp_unit_name = emp.default_operating_unit_id.name if hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id else ''

            if emp.id not in existing_emp_ids:
                vals = {
                    'vacancy_id': self.id,
                    'internal_recruitment_id': int_rec.id if int_rec else False,
                    'emp_name': emp.id,
                    'select_flag': True,
                    'emp_position': emp_pos_name,
                    'emp_grade': emp_grade_name,
                    'current_work_unit': emp_unit_name,
                    'pms_score': contract_pms,
                }
                EligibleLine.create(vals)
            else:
                lines = self.eligible_employee_ids.filtered(lambda r: r.emp_name.id == emp.id)
                lines.write({'select_flag': True})

        same_loc_lines = self.eligible_employee_ids.filtered(
            lambda r: r.emp_name.default_operating_unit_id and vac_ou and r.emp_name.default_operating_unit_id.id == vac_ou.id
        )
        if same_loc_lines:
            same_loc_lines.write({'select_flag': False})

    def action_request_supervisor_recommendation(self):
        """Send supervisor recommendation request activities & emails to coaches/managers of shortlisted candidates."""
        self.ensure_one()
        if not self.new_int_rec_sel:
            raise UserError(_("No candidate lines found on this vacancy to request supervisor recommendation for."))

        HrTask = self.env['mail.activity']
        ActivityType = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        count = 0

        for line in self.new_int_rec_sel:
            emp = line.emp_name
            if not emp:
                continue
            coach = getattr(emp, 'coach_id', False) or getattr(emp, 'parent_id', False) or (emp.department_id.manager_id if emp.department_id else False)
            if coach and coach.user_id and 'transfer.assessment.record' in self.env:
                TransferAssess = self.env['transfer.assessment.record'].sudo()
                existing = TransferAssess.search([
                    ('employee_id', '=', emp.id),
                    '|',
                    ('vacancy_id', '=', self.id),
                    ('target_job_id', '=', self.job_position.id if self.job_position else False)
                ], limit=1)
                if not existing:
                    existing = TransferAssess.create({
                        'vacancy_id': self.id,
                        'employee_id': emp.id,
                        'target_job_id': self.job_position.id if self.job_position else False,
                        'target_branch_id': self.operating_unit_id.name if self.operating_unit_id else '',
                        'assessment_mode': 'criteria_only',
                        'pms_score': line.pms_score or (emp.contract_id.pms_score if hasattr(emp, 'contract_id') and emp.contract_id else 85.0),
                    })
                
                if ActivityType:
                    HrTask.sudo().create({
                        'activity_type_id': ActivityType.id,
                        'note': _("Action Required: Please submit the Supervisor Recommendation Score (0-100%) for employee <b>%s</b> for vacancy <b>%s</b>.") % (emp.name, self.reference),
                        'res_id': existing.id,
                        'res_model_id': self.env['ir.model']._get('transfer.assessment.record').id,
                        'user_id': coach.user_id.id,
                        'summary': _("Submit Supervisor Recommendation Score for Transfer"),
                    })
                count += 1

        self.recruitment_step = 'compute_rank'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Recommendations Requested'),
                'message': _('Successfully sent recommendation requests to %s candidate supervisors.') % count,
                'type': 'success',
                'sticky': False,
            }
        }


    def action_notify_candidates(self):
        """Notify shortlisted candidates directly from the Job Vacancy form."""
        self.ensure_one()
        ref = self.reference or ''
        is_internal = self.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()

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

            if not int_rec or not int_rec.eligible_emp:
                raise ValidationError(
                    _("No eligible candidates found to notify for vacancy %s. Please click 'Shortlist' first.") % self.reference)

            # Mark all as selected if none is selected yet so they all receive notification
            has_selected = any(line.select_flag for line in int_rec.eligible_emp)
            if not has_selected:
                for line in int_rec.eligible_emp:
                    line.select_flag = True

            # Trigger notify
            int_rec.notify()
            self.candidate_notified = True
            if not self.has_written_exam:
                self.exam_notified = True
                self.exam_scores_fetched = True
                self.recruitment_step = 'notify_panel'
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
            if not self.has_written_exam:
                self.exam_notified = True
                self.exam_scores_fetched = True
                self.recruitment_step = 'notify_panel'
            else:
                self.recruitment_step = 'notify_exam'
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

            # 3. Sync Default Approval Committee Members
            if not rec.vac_del_team_id:
                try:
                    htype = rec._compute_hierarchy_type_recruitment()
                    hiring_ou = rec.operating_unit_id
                    resp_ou = rec.responsible.default_operating_unit_id if (rec.responsible and rec.responsible.default_operating_unit_id) else False
                    if not resp_ou:
                        ou = self.env['operating.unit'].search([('name', 'ilike', 'Onboarding and Recruitment')], limit=1)
                        if not ou:
                            ou = self.env['operating.unit'].search([('name', 'ilike', 'Recruitment')], limit=1)
                        resp_ou = ou

                    # Find Panel Member User (from Hiring Work Unit)
                    p_emp = self.env['hr.employee'].search([
                        ('default_operating_unit_id', '=', hiring_ou.id if hiring_ou else 0),
                        ('active', '=', True),
                        ('user_id', '!=', False)
                    ], limit=1) if hiring_ou else False
                    panel_user = p_emp.user_id.id if p_emp else False

                    # Find Secretary User (from HR / Responsible Work Unit)
                    s_emp = self.env['hr.employee'].search([
                        ('default_operating_unit_id', '=', resp_ou.id if resp_ou else 0),
                        ('active', '=', True),
                        ('user_id', '!=', False)
                    ], limit=1) if resp_ou else False
                    sec_user = s_emp.user_id.id if s_emp else False

                    # Find Chairperson User
                    chair_emp = self.env['hr.employee'].search([
                        ('active', '=', True),
                        ('user_id', '!=', False),
                        '|', ('job_title', 'ilike', 'Director'), ('job_title', 'ilike', 'Chief')
                    ], limit=1)
                    chair_user = chair_emp.user_id.id if chair_emp else False

                    # Find Observer User
                    obs_emp = self.env['hr.employee'].search([
                        ('active', '=', True),
                        ('user_id', '!=', False),
                        ('id', 'not in', [p_emp.id if p_emp else 0, s_emp.id if s_emp else 0, chair_emp.id if chair_emp else 0])
                    ], limit=1)
                    obs_user = obs_emp.user_id.id if obs_emp else False

                    if htype == "ho_district_grade2_plus":
                        committee_configs = [
                            ("chairperson", chair_user),
                            ("panel_member", panel_user),
                            ("secretary", sec_user),
                        ]
                    else:
                        committee_configs = [
                            ("chairperson", chair_user),
                            ("panel_member", panel_user),
                            ("secretary", sec_user),
                            ("observer", obs_user),
                        ]

                    for role_key, u_id in committee_configs:
                        self.env['vacancy.delegation.team'].create({
                            'vac_del_id': rec.id,
                            'employee_name': u_id,
                            'role': role_key,
                            'status': 'active',
                        })
                except Exception as e:
                    _logger.warning("Could not auto-populate default approval team: %s", e)

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

    @api.depends('panl_memb_vac', 'panl_memb_vac.operating_unit_id')
    def _compute_eligible_employee_ids(self):
        for rec in self:
            hiring_ou = False
            if rec.panl_memb_vac and rec.panl_memb_vac.operating_unit_id:
                hiring_ou = rec.panl_memb_vac.operating_unit_id.id
            elif self.env.context.get('parent_operating_unit_id'):
                p_ou = self.env.context.get('parent_operating_unit_id')
                hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)

            if hiring_ou:
                rec.eligible_employee_ids = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', hiring_ou),
                    ('active', '=', True)
                ])
            else:
                rec.eligible_employee_ids = self.env['hr.employee'].search([('active', '=', True)])

    @api.onchange('panl_memb_vac', 'role', 'panel_type')
    def _onchange_panl_memb_vac_domain(self):
        """Filter panel members strictly to the Vacancy's Hiring Work Unit."""
        hiring_ou = False
        if self.panl_memb_vac and self.panl_memb_vac.operating_unit_id:
            hiring_ou = self.panl_memb_vac.operating_unit_id.id
        elif self.env.context.get('parent_operating_unit_id'):
            p_ou = self.env.context.get('parent_operating_unit_id')
            hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)

        if hiring_ou:
            domain = [('default_operating_unit_id', '=', hiring_ou), ('active', '=', True)]
            self.eligible_employee_ids = self.env['hr.employee'].search(domain)
            if self.employee_id and self.employee_id.id not in self.eligible_employee_ids.ids:
                self.employee_id = False
            return {'domain': {'employee_id': domain}}

        domain = [('active', '=', True)]
        self.eligible_employee_ids = self.env['hr.employee'].search(domain)
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
                    ADD COLUMN IF NOT EXISTS has_written_exam BOOLEAN DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS transfer_eval_mode VARCHAR DEFAULT 'standard',
                    ADD COLUMN IF NOT EXISTS app_date_weight NUMERIC DEFAULT 20.0,
                    ADD COLUMN IF NOT EXISTS experience_weight NUMERIC DEFAULT 20.0,
                    ADD COLUMN IF NOT EXISTS location_weight NUMERIC DEFAULT 20.0,
                    ADD COLUMN IF NOT EXISTS recommendation_weight NUMERIC DEFAULT 10.0,
                    ADD COLUMN IF NOT EXISTS written_exam_date TIMESTAMP WITHOUT TIME ZONE,
                    ADD COLUMN IF NOT EXISTS exam_location TEXT,
                    ADD COLUMN IF NOT EXISTS exam_scheduled VARCHAR,
                    ADD COLUMN IF NOT EXISTS interview_date TIMESTAMP WITHOUT TIME ZONE,
                    ADD COLUMN IF NOT EXISTS interview_location TEXT,
                    ADD COLUMN IF NOT EXISTS interview_scheduled VARCHAR,
                    ADD COLUMN IF NOT EXISTS pms_weight NUMERIC,
                    ADD COLUMN IF NOT EXISTS written_weight NUMERIC,
                    ADD COLUMN IF NOT EXISTS interview_weight NUMERIC;

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


    def _sync_schedule_to_selection_models(self):
        for rec in self:
            if not rec.id:
                continue
            vals_to_sync = {}
            if rec.written_exam_date:
                vals_to_sync['written_exam_date'] = rec.written_exam_date
            if rec.exam_location:
                vals_to_sync['exam_location'] = rec.exam_location
            if rec.interview_date:
                vals_to_sync['interview_date'] = rec.interview_date
            if rec.interview_location:
                vals_to_sync['interview_location'] = rec.interview_location

            if vals_to_sync:
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
                    UPDATE vacancy_delegation_team SET role = 'chairperson' WHERE role ILIKE '%chair%';
                    UPDATE vacancy_delegation_team SET role = 'secretary' WHERE role ILIKE '%sec%';
                    UPDATE vacancy_delegation_team SET role = 'observer' WHERE role ILIKE '%observer%' OR role ILIKE '%labor%';
                    UPDATE vacancy_delegation_team SET role = 'panel_member' WHERE role NOT IN ('chairperson', 'secretary', 'observer') OR role IS NULL;
                    UPDATE vacancy_delegation_team SET status = 'active' WHERE status IS NULL OR status = '';
                """)
        except Exception as e:
            _logger.warning("Migration query on vacancy_delegation_team failed: %s", e)

    def unlink(self):
        self.write({"active": False})
        return True

    role = fields.Selection([
        ("chairperson", "Chairperson"),
        ("panel_member", "Panel Member"),
        ("secretary", "Panel Member & Secretary"),
        ("observer", "Labor Representative (Observer)"),
    ], string="Role", default="panel_member")
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
        """
        Dynamically filters employee_name and alternate_committee_member based on the role:
        - 'panel_member': Strictly from Vacancy's Hiring Work Unit.
        - 'secretary': Strictly from Vacancy Responsible Officer's Work Unit (HR / Recruitment).
        - 'chairperson' / 'observer': Across company.
        """
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
        role_val = role or self.role or 'panel_member'
        vac = self.vac_del_id

        # 1. Panel Member: Strictly from Vacancy's Hiring Work Unit
        if role_val == 'panel_member':
            hiring_ou = False
            if vac and hasattr(vac, 'operating_unit_id') and vac.operating_unit_id:
                hiring_ou = vac.operating_unit_id.id
            elif self.env.context.get('parent_operating_unit_id'):
                p_ou = self.env.context.get('parent_operating_unit_id')
                hiring_ou = p_ou if isinstance(p_ou, int) else (p_ou.id if hasattr(p_ou, 'id') else False)

            if hiring_ou:
                employees = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', hiring_ou),
                    ('active', '=', True),
                    ('user_id', '!=', False)
                ])
                user_ids = employees.mapped('user_id').ids
                if user_ids:
                    return [('id', 'in', user_ids)]

        # 2. Panel Member & Secretary: Strictly from Vacancy Responsible Officer's Work Unit (HR / Recruitment)
        elif role_val == 'secretary':
            resp_ou = False
            if vac and hasattr(vac, 'responsible') and vac.responsible and vac.responsible.default_operating_unit_id:
                resp_ou = vac.responsible.default_operating_unit_id.id
            elif self.env.context.get('parent_responsible_id'):
                r_id = self.env.context.get('parent_responsible_id')
                emp = self.env['hr.employee'].browse(r_id) if isinstance(r_id, int) else r_id
                if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
                    resp_ou = emp.default_operating_unit_id.id
            if not resp_ou:
                ou = self.env['operating.unit'].search([('name', 'ilike', 'Onboarding and Recruitment')], limit=1)
                if not ou:
                    ou = self.env['operating.unit'].search([('name', 'ilike', 'Recruitment')], limit=1)
                if ou:
                    resp_ou = ou.id
            if resp_ou:
                employees = self.env['hr.employee'].search([
                    ('default_operating_unit_id', '=', resp_ou),
                    ('active', '=', True),
                    ('user_id', '!=', False)
                ])
                user_ids = employees.mapped('user_id').ids
                if user_ids:
                    return [('id', 'in', user_ids)]

        # 3. Chairperson / Observer / Default: All active employees linked to users
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
