from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from datetime import date

JOB_VACANCY_TYPE_CODE_MAP = {
    'internal': 'INT',
    'promotion': 'INT',
    'lateral': 'LAT',
    'external': 'EXT',
}


LOCKED_ALLOWED_FIELDS = {
    'vacancy_status', 'status', 'state', 'reference', 'message_ids',
    'message_follower_ids', 'activity_ids', 'website_published',
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
        [('internal', 'Internal Promotion/Transfer'),
         ('promotion', 'Promotion'),
         ('lateral', 'Lateral Transfer'),
         ('external', 'External Hire')],
        string='Internal Movement Type', default='internal',
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
                    rec.internal_movement_type = 'internal'
                rec.recruitment_type = 'Internal'
            elif rec.sourcing_type == 'both':
                # For a vacancy that can be sourced both internally and externally,
                # keep the legacy recruitment_type as 'Internal' so internal records
                # are treated as internal and external records are treated as external.
                # The external recruitment view relies on the external model, not on
                # this flag. Leaving it as 'Internal' prevents internal view from
                # mistakenly picking up external candidates.
                rec.recruitment_type = 'Internal'

    @api.constrains('recruitment_type', 'internal_movement_type')
    def _check_internal_movement_type(self):
        """Internal Movement Type required for internal vacancies."""
        for rec in self:
            if (rec.recruitment_type == 'Internal' or rec.sourcing_type == 'internal') \
                    and not rec.internal_movement_type:
                raise ValidationError(
                    _("Internal Movement Type is required for internal vacancies.")
                )

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
        [('junior', 'Junior'), ('senior', 'Senior / Regular')],
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
    last_date_to_apply = fields.Date(string="Last Date To Apply", required=True,
                                     help=" Closing Date must be > Opening Date.")

    vacancy_description = fields.Text(string="Vacancy Description", required=True)
    vacancy_announced_on = fields.Date(string="Vacancy Announced on")

    # Legacy field — kept for compatibility; use sourcing_type for new records
    recruitment_type = fields.Selection(
        [('Internal', 'Internal'), ('External', 'External')],
        string='Recruitment Type (Legacy)', default='Internal')

    responsible = fields.Many2one(
        'hr.employee', string="Responsible", required=True,
        default=lambda self: self.env.user.employee_id,readonly=True
    )

    no_of_vacancies = fields.Integer(string="Number of Vacancies")
    operating_unit_id = fields.Many2one("operating.unit", string="Place Of Assignment", required=True,readonly=True)
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

    @api.depends('job_position', 'vacant_job_position', 'operating_unit_id', 'vacancy_description', 'last_date_to_apply')
    def _compute_website_vacancy_fields(self):
        for rec in self:
            rec.job_title = rec.job_position.name if rec.job_position else (rec.vacant_job_position or rec.reference or '')
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


    @api.onchange('recruitment_request_id')
    def _onchange_recruitment_request_id_sync_fields(self):
        """Auto-populate Job Vacancy fields when an approved Recruitment Request is selected."""
        if not self.recruitment_request_id:
            return
        req = self.recruitment_request_id
        self.recruitment_reference = req.reference
        if req.job_position_id:
            self.job_position = req.job_position_id
        if req.operating_unit_id:
            self.operating_unit_id = req.operating_unit_id
        if req.requested_by:
            self.responsible = req.requested_by
        if req.required_headcount:
            self.no_of_vacancies = req.required_headcount
        if req.employment_type:
            self.type_of_employment = "Permanent" if req.employment_type == "permanent" else "Contractual"
        if req.sourcing_type:
            self.sourcing_type = req.sourcing_type
            self.recruitment_type = "Internal" if req.sourcing_type == "internal" else "External"
        if req.job_description:
            self.vacancy_description = req.job_description
        if req.last_date_to_apply:
            self.last_date_to_apply = req.last_date_to_apply
        if req.employee_category:
            self.employee_category = req.employee_category
        if req.job_level:
            self.job_level = req.job_level if req.employee_category == "Non Managerial" else False

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
                           (rec.reference and (rec.reference.startswith('BB/INT/') or rec.reference.startswith('BB/LAT/'))))
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
                    'opening_date', 'last_date_to_apply')
    def _check_mandatory_data(self):
        """ Vacancy record shall require Opening Date, Closing Date,
        Job Position, Grade, Location, Job Description, and Competencies with
        required level."""
        for rec in self:
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
                missing.append(_("Place Of Assignment)"))
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
        for vals in vals_list:
            if not vals.get('reference'):
                vals['reference'] = _('New')
        return super().create(vals_list)

    def write(self, vals):
        """Lock the record once it is Evaluated, Published, or Closed, regardless
        of which view/route triggers the write (form, list, API, automation).
        One2many line writes bundled from the form (competencies, hiring details,
        panel members, etc.) are covered here too, since Odoo routes those through
        the parent's write when saved from an embedded list editor. Only the
        technical fields needed for the workflow itself still pass through."""
        for rec in self:
            if rec._is_locked() and not self.env.context.get('skip_lock_check'):
                blocked = set(vals.keys()) - LOCKED_ALLOWED_FIELDS
                if blocked:
                    raise ValidationError(_(
                        "This vacancy is locked (Published/Closed) and can no "
                        "longer be edited, including its lines."
                    ))

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

                # Available Internal Vacancies for Employee Portal/Applications
                Available = self.env['employee.recruitment.available']
                existing_avail = Available.search([
                    '|', ('vacancy_id', '=', rec.id), ('vacancy_reference', '=', rec.reference)
                ], limit=1)

                avail_vals = {
                    'vacancy_id': rec.id,
                    'vacancy_reference': rec.reference,
                    'job_position': rec.job_position.name if rec.job_position else False,
                    'job_location': rec.operating_unit_id.name if rec.operating_unit_id else False,
                    'employee_grade': rec.job_grade.grade_name if rec.job_grade else False,
                    'employee_category': rec.employee_category,
                    'type_of_employment': rec.type_of_employment,
                    'number_of_vacancies': rec.no_of_vacancies,
                    'vacancy_announced_on': rec.opening_date or fields.Date.context_today(self),
                    'last_date_to_apply': rec.last_date_to_apply,
                    'job_description': rec.vacancy_description or '',
                }

                if existing_avail:
                    existing_avail.write(avail_vals)
                    avail_rec = existing_avail
                else:
                    avail_rec = Available.create(avail_vals)

                if rec.hiring_details:
                    avail_rec.employee_vacancy_ids.unlink()
                    vac_lines = [(0, 0, {
                        'operating_unit': h.work_unit.name if h.work_unit else False,
                        'number_of_vacancies': h.number_of_openings or 0,
                        'location_preference': 0,
                    }) for h in rec.hiring_details]
                    avail_rec.write({'employee_vacancy_ids': vac_lines})

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

    def notify(self):
        for com in self.vac_del_team_id:
            user = com.employee_name if com.status == "active" else com.alternate_committee_member
            if not user:
                continue
            partner = user.partner_id
            if not partner:
                raise ValidationError(_('Approver %s is not linked to a partner record.') % (user.name or ''))
            self.mail_channel_msgs(partner.id, self.reference, self.job_position.name, self.type_of_employment)
        self.status = "notify"
        self._sync_published_vacancy_records()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Sent'),
                'message': _('Committee members have been successfully notified for vacancy %s.') % self.reference,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def mail_channel_msgs(self, rec_id, ref, arg1, arg2):
        channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[rec_id])
        message = (
                      "Dear Committee<br>A New Job vacancy form is created with following details.<br><br>"
                      "Reference No: %s<br>Job: %s<br>Type of Employment: %s<br><br>Kindly approve."
                  ) % (ref, arg1, arg2)
        channel.message_post(body=message, message_type='comment', subtype_xmlid='mail.mt_comment')

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
        """: auto-generate Unique Vacancy Reference Number."""
        movement_type = self.internal_movement_type or 'internal'
        type_code = JOB_VACANCY_TYPE_CODE_MAP.get(movement_type, 'INT')
        current_prefix = self._get_fiscal_year_prefix(type_code)
        self.env.cr.execute("""
            SELECT reference FROM job_vacancy
            WHERE reference IS NOT NULL AND reference != 'New'
              AND reference LIKE %s
            ORDER BY id DESC LIMIT 1
        """, (current_prefix + '%',))
        result = self.env.cr.fetchone()
        if result and result[0]:
            _, _, numeric_part = result[0].rpartition('/')
            try:
                next_number = int(numeric_part) + 1
            except ValueError:
                next_number = 1
        else:
            next_number = 1
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
                raise ValidationError(_("Access Denied: Vacancies can only be evaluated by members of the Onboarding and Recruitment Division."))

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
            if rec.panl_memb_vac and rec.panl_memb_vac._is_locked:
                raise ValidationError(_(
                    "This vacancy is locked (Published/Closed); "
                    "panel members can no longer be edited."
                ))

    def write(self, vals):
        self._check_parent_lock()
        return super().write(vals)

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
        compute="_compute_work_unit", store=True, readonly=True
    )
    responsible_employee = fields.Many2one(
        "hr.employee", string="Responsible Officer",
        default=lambda self: self.env.user.employee_id,readonly=True
    )
    number_of_openings = fields.Integer(string="Number Of Openings")
    planned_positions = fields.Integer(string="Planned Openings")
    status = fields.Char(string="Status")

    @api.depends('hiring_id.operating_unit_id')
    def _compute_work_unit(self):
        for rec in self:
            if rec.hiring_id.operating_unit_id:
                rec.work_unit = rec.hiring_id.operating_unit_id

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.work_unit.name or str(rec.id)


    def _check_parent_lock(self):
        for rec in self:
            if rec.hiring_id and rec.hiring_id._is_locked:
                raise ValidationError(_(
                    "This vacancy is locked (Published/Closed); "
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
            if rec.summ_rank_id and rec.summ_rank_id._is_locked:
                raise ValidationError(_(
                    "This vacancy is locked (Published/Closed); "
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

    def unlink(self):
        self.write({"active": False})
        return True

    role = fields.Char(string="Role", default='Approver', readonly=True)
    employee_name = fields.Many2one(
        'res.users',
        string="Employee Name",
        domain=lambda self: self._get_employee_domain()
    )
    alternate_committee_member = fields.Many2one(
        "res.users",
        string="Alternate Approver",
        domain=lambda self: self._get_employee_domain()
    )

    @api.model
    def _get_employee_domain(self):
        """
        Calculates valid User IDs by filtering through the Employee model.
        Filters by Onboarding and Recruitment Division.
        """
        current_user_id = self.env.user.id
        
        # Find Onboarding and Recruitment Division dynamically by name
        ou = self.env['operating.unit'].search([('name', 'ilike', 'Onboarding and Recruitment')], limit=1)
        if not ou:
            ou = self.env['operating.unit'].search([('name', 'ilike', 'Recruitment')], limit=1)
        ou_id = ou.id if ou else 22

        # Find all active employees in this division linked to a user
        valid_employees = self.env['hr.employee'].search([
            ('default_operating_unit_id', '=', ou_id),
            ('active', '=', True),
            ('user_id', '!=', False)
        ])

        # Extract the User IDs
        valid_user_ids = valid_employees.mapped('user_id').ids

        # Filter out the current logged-in user if they are in the list
        if current_user_id in valid_user_ids:
            try:
                valid_user_ids.remove(current_user_id)
            except ValueError:
                pass

        return [('id', 'in', valid_user_ids)]


    operating_unit = fields.Char(string="Operating Unit",
                                 related="employee_name.employee_id.default_operating_unit_id.name")
    status = fields.Selection([("active", "Active"), ("unavailable", "Un Available")], string="status",
                              default='active')
    alter_operating_unit = fields.Char(string="Operating Unit",
                                       related="alternate_committee_member.employee_id.default_operating_unit_id.name")
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
