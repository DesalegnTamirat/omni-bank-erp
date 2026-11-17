# -*- coding: utf-8 -*-
import os
import base64
import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def amount_to_words_birr(amount):
    """Convert float amount to English words for Birr."""
    if not amount or amount <= 0:
        return ""
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    thousands = ["", "Thousand", "Million", "Billion"]

    def _convert_hundreds(n):
        res = []
        if n >= 100:
            res.append(units[n // 100] + " Hundred")
            n %= 100
        if 10 <= n <= 19:
            res.append(teens[n - 10])
        elif n >= 20:
            ten_str = tens[n // 10]
            unit_str = units[n % 10]
            res.append(f"{ten_str}-{unit_str}" if unit_str else ten_str)
        elif n > 0:
            res.append(units[n])
        return " ".join(res)

    int_part = int(amount)
    cents_part = int(round((amount - int_part) * 100))

    if int_part == 0:
        words = "Zero"
    else:
        chunks = []
        chunk_idx = 0
        while int_part > 0:
            chunk = int_part % 1000
            if chunk > 0:
                chunk_words = _convert_hundreds(chunk)
                if thousands[chunk_idx]:
                    chunk_words += " " + thousands[chunk_idx]
                chunks.insert(0, chunk_words)
            int_part //= 1000
            chunk_idx += 1
        words = " ".join(chunks)

    if cents_part > 0:
        cents_words = _convert_hundreds(cents_part)
        return f"{words} Birr and {cents_words} Cents only"
    return f"{words} Birr only"


class RecruitmentOfferLetter(models.Model):
    """
    Extends recruitment.offer.letter for External Recruitment Offer Management:
    - Filter vacancy_id for External Vacancies only.
    - Dynamically filter selected candidates for the chosen vacancy reference.
    - Auto-populates candidate title, name, address, job grade, position, and work unit.
    - Managerial vs Non-Managerial representation allowance rule (10% for managerial, 0% for non-managerial).
    - HR fills blank compensation fields (Base salary, Housing allowance, Fuel allowance liters, Other benefits).
    - Configurable deadline date (defaults to +3 calendar days, directly editable by HR).
    - Dispatches email with official Bunna Bank QWeb PDF Report.
    - Syncs with ATS Candidate Portal sidebar (/my/candidate/offers).
    - Auto-escalation to next Reserve Candidate upon decline/expiry.
    """
    _name = 'recruitment.offer.letter'
    _description = 'Employment Offer Letter'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'offer_date desc, id desc'

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    name = fields.Char(
        string='Offer Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    reference = fields.Char(
        string='Reference Number',
        related='name',
        store=True,
        readonly=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    response_date = fields.Date(string='Response Date', readonly=True)

    vacancy_id = fields.Many2one(
        'job.vacancy', string='Vacancy Reference', required=True, tracking=True,
        domain="[('reference', 'ilike', 'EXT')]"
    )
    vacancy_reference = fields.Char(
        related='vacancy_id.reference', string='Vacancy Reference String', store=True
    )

    eligible_vacancy_ids = fields.Many2many(
        'job.vacancy',
        compute='_compute_eligible_vacancy_ids',
        default=lambda self: self._get_eligible_vacancy_ids(),
        string='Eligible Vacancies',
        help="External vacancies that have selected candidates not yet registered in Employee Master (hr.employee)."
    )

    @api.model
    def _get_eligible_vacancy_ids(self):
        """Returns recordset of external job.vacancy that have at least one selected candidate
        who is NOT yet registered in Employee Master (hr.employee).
        If all selected candidates for a vacancy are created in Employee Master,
        that vacancy is completed and excluded.
        """
        SelectedCand = self.env['external.recruitment.selected.candidates'].sudo()
        selected_cands = SelectedCand.search([
            ('selection_type', 'in', ['selected', 'Selected']),
            ('active', '=', True)
        ])
        unprocessed_cands = selected_cands.filtered(
            lambda c: not (c.applicant_name and c.applicant_name.employee_id)
        )
        parents = unprocessed_cands.mapped('ext_rec_sel_cand')
        vac_ids = set()
        for p in parents:
            if p.vacancy_id:
                vac_ids.add(p.vacancy_id)
            if p.vacancy_reference:
                v = self.env['job.vacancy'].sudo().search([('reference', '=', p.vacancy_reference)], limit=1)
                if v:
                    vac_ids.add(v.id)

        return self.env['job.vacancy'].browse(list(vac_ids)).filtered(
            lambda v: 'EXT' in (v.reference or '')
        )

    @api.depends('vacancy_id')
    def _compute_eligible_vacancy_ids(self):
        eligible = self._get_eligible_vacancy_ids()
        for rec in self:
            if rec.vacancy_id:
                rec.eligible_vacancy_ids = eligible | rec.vacancy_id
            else:
                rec.eligible_vacancy_ids = eligible
    
    ext_candidate_id = fields.Many2one(
        'external.recruitment.selected.candidates',
        string='Candidate Name',
        required=True,
        tracking=True,
        domain="[('selection_type', 'in', ['selected', 'Selected'])]",
        help="Selected candidate from external recruitment whose Result is Selected."
    )

    applicant_id = fields.Many2one(
        'hr.applicant', string='Applicant (External)'
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee (Internal)'
    )

    # Candidate Profile Details
    candidate_title = fields.Selection([
        ('ato', 'Ato'),
        ('wro', 'W/ro'),
        ('wt', 'W/t'),
        ('dr', 'Dr.'),
    ], string='Title', default='ato', tracking=True)
    
    candidate_name = fields.Char(string='Candidate Full Name', tracking=True)
    candidate_address = fields.Char(string='Candidate Address', default='Addis Ababa, Ethiopia')
    candidate_email = fields.Char(string="Candidate Email")
    # ── Position & Work Unit Classification ──────────────────────────────────
    # All three are stored related fields directly from the Vacancy.
    # Using `related` (not onchange) ensures they auto-populate for:
    #   • New records: as soon as vacancy_id is chosen in the UI
    #   • Existing records: recomputed automatically on module upgrade
    job_position_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='vacancy_id.job_position',
        store=True,
        readonly=True,
        tracking=True,
        help="Auto-populated from the selected Job Vacancy's job position."
    )
    # Backward-compat Char alias used in QWeb report / portal templates
    job_position_name = fields.Char(
        string='Job Position Name',
        related='job_position_id.name',
        store=False,
        readonly=True,
    )

    job_grade = fields.Many2one(
        'employee.grade',
        string='Job Grade',
        related='vacancy_id.job_position.grade',
        store=True,
        readonly=True,
        tracking=True,
        help="Auto-populated from the Job Grade set on the Job Vacancy's position (job_position.grade)."
    )
    # Backward-compat Char alias used in QWeb report / portal templates
    job_grade_name = fields.Char(
        string='Job Grade Name',
        related='job_grade.grade_name',
        store=True,
        readonly=True,
    )

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Work Unit',
        related='vacancy_id.operating_unit_id',
        store=True,
        readonly=True,
        tracking=True,
        help="Operating Unit (Work Unit) auto-populated from the Vacancy's Place of Assignment."
    )
    # Backward-compat Char alias used in QWeb report / portal templates
    work_unit = fields.Char(
        string='Work Unit Name',
        related='operating_unit_id.name',
        store=True,
        readonly=True,
    )
    job_category = fields.Selection(
        related='vacancy_id.employee_category',
        string='Job Category',
        store=True,
        readonly=True,
        help="Job category from vacancy: Managerial or Non Managerial."
    )
    is_managerial = fields.Boolean(
        string='Is Managerial Position?',
        compute='_compute_is_managerial',
        store=True,
        readonly=True,
        tracking=True,
        help="Automatically determined from Vacancy Job Category: True if Managerial, False if Non Managerial."
    )

    # Compensation Breakdown (HR Manual Blanks + Smart Computed)
    salary_figure = fields.Float(string='Base Salary (ETB)', tracking=True)
    salary_words = fields.Char(string='Salary in Words', compute='_compute_salary_words', store=True, readonly=False)
    housing_allowance = fields.Float(string='Housing Allowance (ETB)', default=0.0, tracking=True)
    fuel_allowance_liters = fields.Float(string='Fuel Allowance (Liters of Benzene)', default=0.0, tracking=True)
    representation_allowance = fields.Float(
        string='Representation Allowance (10%)',
        compute='_compute_representation_allowance',
        store=True,
        readonly=False,
        tracking=True
    )
    other_benefits = fields.Text(string='Other Benefits & Remarks')

    # Date & Deadline Configuration
    offer_date = fields.Date(
        string='Offer Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    deadline_date = fields.Date(
        string='Deadline (Auto-Decline Date)',
        compute='_compute_deadline_date',
        store=True,
        readonly=False,
        tracking=True,
        help="Date by which the candidate must respond before the offer auto-expires."
    )
    expiry_date = fields.Date(
        string='Offer Expiry Date',
        related='deadline_date', store=True, readonly=False
    )
    response_deadline = fields.Date(
        string='Response Deadline',
        related='deadline_date', store=True, readonly=False
    )
    ref_no = fields.Char(string='Letter Reference Number', tracking=True)
    signatory_config_id = fields.Many2one(
        'recruitment.signatory.config',
        string='Signatory & Stamp Configuration',
        default=lambda self: self.env['recruitment.signatory.config'].get_active_signatory('all') if 'recruitment.signatory.config' in self.env else False,
        help='Configuration providing authorized signature, rubber stamp, and executive title for offer letters'
    )
    signatory_name = fields.Char(string='Signatory Title/Name', default='Human Resources Management Department')
    cc_chief_office = fields.Char(string='CC: Chief Office', default='Respective Chief Offices')
    cc_work_unit = fields.Char(string='CC: Work Unit', default='Respective Work Units')

    rejection_reason = fields.Text(string='Rejection / Decline Reason')
    notes = fields.Text(string='Internal Notes')

    @api.depends('salary_figure')
    def _compute_salary_words(self):
        for rec in self:
            if rec.salary_figure:
                rec.salary_words = amount_to_words_birr(rec.salary_figure)
            else:
                rec.salary_words = ""

    @api.depends('vacancy_id', 'vacancy_id.employee_category')
    def _compute_is_managerial(self):
        for rec in self:
            rec.is_managerial = bool(rec.vacancy_id and rec.vacancy_id.employee_category == 'Managerial')

    @api.depends('salary_figure', 'is_managerial')
    def _compute_representation_allowance(self):
        for rec in self:
            if rec.is_managerial and rec.salary_figure:
                rec.representation_allowance = round(rec.salary_figure * 0.10, 2)
            else:
                rec.representation_allowance = 0.0

    @api.depends('offer_date')
    def _compute_deadline_date(self):
        for rec in self:
            if rec.offer_date:
                if not rec.deadline_date or rec.deadline_date <= rec.offer_date:
                    rec.deadline_date = rec.offer_date + timedelta(days=3)
            else:
                rec.deadline_date = fields.Date.today() + timedelta(days=3)

    def _resolve_base_salary(self):
        """Resolves the base salary from the Selection Minute and Job Grade."""
        sal = 0.0
        vac = self.vacancy_id
        if not vac and self.ext_candidate_id and self.ext_candidate_id.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.ext_candidate_id.vacancy_id)
        if vac:
            grade_rec = vac.job_grade or (vac.job_position.grade if vac.job_position else False)
            if grade_rec:
                sal = getattr(grade_rec, 'base_salary', 0.0) or getattr(grade_rec, 'basic_salary', 0.0) or 0.0
            if not sal:
                min_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', vac.id)], order='id desc', limit=1)
                if min_rec:
                    sal = getattr(min_rec, 'starting_salary', 0.0) or getattr(min_rec, 'base_salary', 0.0) or 0.0
            if not sal:
                sal = getattr(vac, 'starting_salary', 0.0) or getattr(vac, 'base_salary', 0.0) or getattr(vac, 'basic_salary', 0.0) or 0.0
        return sal

    @api.onchange('vacancy_id')
    def _onchange_vacancy_id_filter_candidates(self):
        """
        BRD Offer Letter Requirement:
        1. Fetch candidates from external.recruitment.selected.candidates for the selected vacancy ONLY.
        2. Filter candidates whose Result is SELECTED ONLY ('selection_type in [selected, Selected]').
        3. Exclude candidates who ALREADY have an active offer letter created.
        """
        if not self.vacancy_id:
            self.ext_candidate_id = False
            return {'domain': {'ext_candidate_id': [('selection_type', 'in', ['selected', 'Selected'])]}}

        vac_ref = self.vacancy_id.reference
        
        # 1. Search parent external.recruitment.selected records for this vacancy reference
        sel_records = self.env['external.recruitment.selected'].search([
            '|', ('vacancy_reference', '=', vac_ref), ('vacancy_id', '=', self.vacancy_id.id)
        ])
        
        # 2. Search ONLY candidates for this specific vacancy where selection_type is 'selected' / 'Selected'
        selected_candidates = self.env['external.recruitment.selected.candidates'].search([
            ('ext_rec_sel_cand', 'in', sel_records.ids),
            ('selection_type', 'in', ['selected', 'Selected'])
        ])

        # 3. Exclude candidates who already have an active offer letter
        existing_offers = self.search([
            ('vacancy_id', '=', self.vacancy_id.id),
            ('state', 'not in', ['declined', 'expired'])
        ])
        offered_candidate_ids = existing_offers.mapped('ext_candidate_id').ids

        remaining_candidates = selected_candidates.filtered(lambda c: c.id not in offered_candidate_ids and not (c.applicant_name and c.applicant_name.employee_id))

        self.ext_candidate_id = False

        # Auto-set is_managerial from vacancy's employee_category (Job Category)
        if self.vacancy_id:
            self.is_managerial = (self.vacancy_id.employee_category == 'Managerial')
            if not self.salary_figure or self.salary_figure <= 0:
                self.salary_figure = self._resolve_base_salary()

        return {
            'domain': {
                'ext_candidate_id': [('id', 'in', remaining_candidates.ids)]
            }
        }

    @api.onchange('ext_candidate_id')
    def _onchange_ext_candidate_id(self):
        """Auto-populate candidate profile from selected external candidate record.
        Position, Grade, Work Unit, and Managerial flag are auto-set from vacancy_id.
        """
        if self.ext_candidate_id:
            cand = self.ext_candidate_id
            self.applicant_id = cand.applicant_name.id if cand.applicant_name else False
            self.candidate_name = cand.emp_name or (cand.applicant_name.partner_name if cand.applicant_name else '')
            self.candidate_email = (cand.applicant_name.email_from if cand.applicant_name and cand.applicant_name.email_from else False) or cand.applicant_email or ''

            # Auto-populate Candidate Address
            if cand.applicant_name and cand.applicant_name.partner_id and cand.applicant_name.partner_id.contact_address:
                self.candidate_address = cand.applicant_name.partner_id.contact_address.replace('\n', ', ')
            else:
                self.candidate_address = 'Addis Ababa, Ethiopia'

            # Ensure is_managerial matches vacancy_id.employee_category
            if self.vacancy_id:
                self.is_managerial = (self.vacancy_id.employee_category == 'Managerial')
            if not self.salary_figure or self.salary_figure <= 0:
                self.salary_figure = self._resolve_base_salary()

    def get_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        sig = self.get_offer_signatory()
        if sig and hasattr(sig, 'get_letter_signature_data'):
            return sig.get_letter_signature_data()
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': sig.get_signature_stamp_base64() if (sig and hasattr(sig, 'get_signature_stamp_base64')) else '',
            'signatory_name': sig.signatory_name if sig else 'Abayneh Markos',
            'signatory_title': sig.signatory_title if sig else 'People Operation Management Directorate',
            'signatory_company': sig.signatory_company if sig else 'Bunna Bank S.C.',
        }

    def get_offer_signatory(self):
        """Returns the configured or active authorized signatory record for the offer letter."""
        self.ensure_one()
        if hasattr(self, 'signatory_config_id') and self.signatory_config_id:
            return self.signatory_config_id
        if 'recruitment.signatory.config' in self.env:
            return self.env['recruitment.signatory.config'].get_active_signatory('all')
        return False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('recruitment.offer.letter') or _('New')
            if not vals.get('signatory_config_id') and 'recruitment.signatory.config' in self.env:
                active_sig = self.env['recruitment.signatory.config'].get_active_signatory('all')
                if active_sig:
                    vals['signatory_config_id'] = active_sig.id
            if not vals.get('salary_figure') or vals.get('salary_figure') <= 0:
                vac_id = vals.get('vacancy_id')
                if vac_id:
                    vac = self.env['job.vacancy'].browse(vac_id)
                    grade_rec = vac.job_grade or (vac.job_position.grade if vac.job_position else False)
                    if grade_rec:
                        vals['salary_figure'] = getattr(grade_rec, 'base_salary', 0.0) or getattr(grade_rec, 'basic_salary', 0.0) or 0.0

            if vals.get('ext_candidate_id') and not vals.get('applicant_id'):
                ext_cand = self.env['external.recruitment.selected.candidates'].browse(vals['ext_candidate_id'])
                if ext_cand.applicant_name:
                    vals['applicant_id'] = ext_cand.applicant_name.id
                    if not vals.get('candidate_email'):
                        vals['candidate_email'] = ext_cand.applicant_name.email_from or ext_cand.applicant_email
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('ext_candidate_id') and not vals.get('applicant_id'):
            ext_cand = self.env['external.recruitment.selected.candidates'].browse(vals['ext_candidate_id'])
            if ext_cand.applicant_name:
                vals['applicant_id'] = ext_cand.applicant_name.id
        return super().write(vals)

    def _get_district_for_unit(self, unit_name_or_rec):
        """Resolves the parent or associated District for a given operating unit or unit name."""
        if not unit_name_or_rec:
            return ""
        ou = False
        if isinstance(unit_name_or_rec, str):
            ou = self.env['operating.unit'].search([('name', '=ilike', unit_name_or_rec.strip())], limit=1)
            if not ou and 'branch' in unit_name_or_rec.lower():
                clean_name = unit_name_or_rec.lower().replace('branch', '').strip()
                ou = self.env['operating.unit'].search([('name', '=ilike', clean_name)], limit=1)
        elif hasattr(unit_name_or_rec, 'name'):
            ou = unit_name_or_rec

        if ou:
            if getattr(ou, 'work_unit_type', '') in ('head_office', 'head_office_unit'):
                return ""
            ou_name_lower = (ou.name or '').lower()
            if 'directorate' in ou_name_lower or 'department' in ou_name_lower or 'head office' in ou_name_lower:
                return ""
            if getattr(ou, 'work_unit_type', '') == 'district_office' or 'district' in ou_name_lower:
                return ou.name
            curr = getattr(ou, 'parent_unit', False)
            while curr and curr.exists():
                if getattr(curr, 'work_unit_type', '') in ('head_office', 'head_office_unit'):
                    return ""
                if getattr(curr, 'work_unit_type', '') == 'district_office' or 'district' in (curr.name or '').lower():
                    return curr.name
                curr = getattr(curr, 'parent_unit', False)
            d_field = getattr(ou, 'district', False)
            if d_field:
                d_str = str(d_field).strip()
                if d_str and 'district' in d_str.lower():
                    return d_str
        return ""

    def get_offer_letter_cc_lines(self):
        """
        Returns list of CC lines for offer letter:
        - If hiring work unit is Head Office: ONLY hiring work unit.
        - If hiring work unit is out of Head Office: hiring work unit AND their respective district.
        """
        self.ensure_one()
        lines = []
        ou = self.operating_unit_id
        if not ou and self.vacancy_id and hasattr(self.vacancy_id, 'operating_unit_id') and self.vacancy_id.operating_unit_id:
            ou = self.vacancy_id.operating_unit_id

        assigned_unit = (ou.name if ou else (self.work_unit or '')).strip()

        # Check if hiring work unit is Head Office
        is_ho = False
        if ou:
            if getattr(ou, 'work_unit_type', '') in ('head_office', 'head_office_unit') or 'directorate' in (ou.name or '').lower() or 'department' in (ou.name or '').lower():
                is_ho = True
            elif ou.parent_unit and getattr(ou.parent_unit, 'work_unit_type', '') in ('head_office', 'head_office_unit'):
                is_ho = True
        elif 'directorate' in assigned_unit.lower() or 'department' in assigned_unit.lower() or 'head office' in assigned_unit.lower():
            is_ho = True

        if not is_ho and assigned_unit:
            district = self._get_district_for_unit(ou or assigned_unit)
            if district and district.strip().lower() != assigned_unit.lower():
                lines.append(district.strip())

        if assigned_unit:
            lines.append(assigned_unit)

        return lines

    def action_send(self):
        """Send offer letter to candidate, generate PDF attachment, and set deadline."""
        for rec in self:
            rec.write({'state': 'sent'})
            if not rec.offer_date:
                rec.offer_date = fields.Date.today()
            if not rec.deadline_date:
                rec.deadline_date = rec.offer_date + timedelta(days=3)
            rec.expiry_date = rec.deadline_date
            
            # Send notification email if email exists
            email_target = (rec.candidate_email or (rec.applicant_id.email_from if rec.applicant_id else False) or (rec.ext_candidate_id.applicant_email if hasattr(rec, 'ext_candidate_id') and rec.ext_candidate_id else False) or '').strip()
            
            # Resolve authorized sender for outgoing SMTP server
            mail_server = self.env['ir.mail_server'].sudo().search([('active', '=', True)], order='sequence, id', limit=1)
            cfg_from = self.env['ir.config_parameter'].sudo().get_param('mail.default.from')
            sender_email = (cfg_from or (mail_server.smtp_user if mail_server else False) or 'natnael.negussie@bunnabanksc.com').strip()
            sender_formatted = f'"Bunna Bank Recruitment" <{sender_email}>'

            pos_str = rec.job_position_name or (rec.vacancy_id.job_position.name if rec.vacancy_id and rec.vacancy_id.job_position else 'Position')
            cand_title_str = dict(rec._fields['candidate_title'].selection).get(rec.candidate_title, 'Ato/W/ro/W/t')
            cand_display_name = f"{cand_title_str} {rec.candidate_name or 'Candidate'}"
            deadline_str = rec.deadline_date.strftime('%B %d, %Y') if rec.deadline_date else 'within 3 calendar days'

            attachments = []
            try:
                # Generate PDF report attachment
                report = self.env.ref('custom_recruitment.action_report_recruitment_offer_letter', raise_if_not_found=False)
                if report:
                    pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf('custom_recruitment.action_report_recruitment_offer_letter', [rec.id])
                    attachment = self.env['ir.attachment'].sudo().create({
                        'name': f"Employment_Offer_Letter_{rec.candidate_name or 'Candidate'}.pdf",
                        'type': 'binary',
                        'raw': pdf_content,
                        'res_model': 'recruitment.offer.letter',
                        'res_id': rec.id,
                        'mimetype': 'application/pdf',
                    })
                    attachments.append(attachment.id)
            except Exception as pdf_err:
                _logger.warning("Failed to render offer letter PDF: %s", pdf_err)

            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            portal_offer_url = f"{base_url.rstrip('/')}/my/candidate/offers" if base_url else "/my/candidate/offers"
            if email_target:
                message_body = _(
                    "Dear %s,<br><br>"
                    "We are pleased to extend a formal Offer Letter of Employment for the position of <b>%s</b> at Bunna Bank S.C.<br>"
                    "Please review the attached official Offer Letter and submit your response via the Bunna ATS Candidate Portal on or before <b>%s</b>.<br><br>"
                    "<div style='margin: 20px 0;'>"
                    "<a href='%s' target='_blank' style='background-color: #541718; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;'>Review &amp; Respond in ATS Portal</a>"
                    "</div>"
                    "Best Regards,<br><b>Human Resources Management Department</b><br>Bunna Bank S.C."
                ) % (cand_display_name, pos_str, deadline_str, portal_offer_url)
                
                try:
                    mail_values = {
                        'subject': _("Official Employment Offer Letter - %s - Bunna Bank S.C.") % pos_str,
                        'body_html': message_body,
                        'email_to': email_target,
                        'email_from': sender_formatted,
                        'attachment_ids': [(6, 0, attachments)] if attachments else [],
                    }
                    mail = self.env['mail.mail'].sudo().create(mail_values)
                    mail.send(raise_exception=False)
                except Exception as ex:
                    _logger.warning("Failed to dispatch offer letter email: %s", ex)

            # Dispatch CC Discuss notifications and emails to work unit managers
            cc_lines = rec.get_offer_letter_cc_lines()
            if cc_lines:
                try:
                    from .cc_dispatch_service import dispatch_letter_cc_notifications
                    details_html = (
                        f"• Candidate: <b>{rec.candidate_name or 'Candidate'}</b><br/>"
                        f"• Offeree Position: <b>{pos_str}</b><br/>"
                        f"• Response Deadline: <b>{deadline_str}</b>"
                    )
                    dispatch_letter_cc_notifications(
                        rec,
                        cc_lines,
                        letter_title=_("Employment Offer Letter"),
                        letter_subject=_("Offer Letter for %s - %s") % (rec.candidate_name or 'Candidate', pos_str),
                        details_html=details_html,
                        attachment_ids=attachments,
                        target_ou=rec.operating_unit_id,
                    )
                except Exception as cc_err:
                    _logger.warning("Error dispatching CC notifications for offer letter: %s", cc_err)

            rec.message_post(body=_("Offer Letter sent to candidate %s. Response Deadline: %s.") % (
                rec.candidate_name or (rec.ext_candidate_id.emp_name if rec.ext_candidate_id else 'Candidate'),
                rec.deadline_date
            ))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offer Sent'),
                'message': _('Offer letter dispatched to candidate email with official PDF attachment and published to ATS Portal.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_accept(self):
        """Candidate accepts offer."""
        for rec in self:
            today = fields.Date.today()
            rec.write({'state': 'accepted', 'response_date': today})
            rec.message_post(body=_("Offer Letter successfully ACCEPTED by candidate on %s.") % today)
            
            # Sync external selected candidate record
            if rec.ext_candidate_id:
                rec.ext_candidate_id.write({
                    'selection_type': 'selected',
                    'remarks': _("Offer Accepted on %s") % today
                })
            
            # Sync hr.applicant record
            app = rec.applicant_id or (rec.ext_candidate_id.applicant_name if rec.ext_candidate_id else False)
            if not app and rec.candidate_email:
                app = self.env['hr.applicant'].search([('email_from', '=ilike', rec.candidate_email.strip())], limit=1)
            if app:
                app.write({'job_offer_status': 'accepted'})

    def action_decline(self):
        """Candidate declines offer — open popup wizard to require decline reason if not filled."""
        self.ensure_one()
        if not self.rejection_reason:
            return {
                'name': _('Reason for Declining Offer'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.offer.decline.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_offer_letter_id': self.id,
                }
            }
        
        today = fields.Date.today()
        self.write({'state': 'declined', 'response_date': today})
        
        # Sync external selected candidate record
        if self.ext_candidate_id:
            self.ext_candidate_id.write({
                'selection_type': 'rejected',
                'remarks': _("Offer Declined: %s") % self.rejection_reason
            })
        
        # Sync hr.applicant record
        app = self.applicant_id or (self.ext_candidate_id.applicant_name if self.ext_candidate_id else False)
        if not app and self.candidate_email:
            app = self.env['hr.applicant'].search([('email_from', '=ilike', self.candidate_email.strip())], limit=1)
        if app:
            app.write({
                'job_offer_status': 'declined',
                'rejection_reason': self.rejection_reason
            })
        
        self.message_post(body=_("Offer Letter DECLINED by candidate (%s). Escalating to Reserve Pool...") % self.rejection_reason)
        self._cascade_to_next_reserve_candidate()

    def _cascade_to_next_reserve_candidate(self):
        """
        Auto-Escalation Engine (3-Day Expiry / Decline Rule):
        Finds the top-ranked Reserve Candidate ('reserved') for this vacancy,
        automatically promotes them to 'selected', updates their remarks, and
        dispatches notification to HR to create their offer letter.
        """
        self.ensure_one()
        if not self.vacancy_id:
            return

        vac_ref = self.vacancy_id.reference
        
        # Search candidate roster for this vacancy
        sel_records = self.env['external.recruitment.selected'].search([
            '|', ('vacancy_reference', '=', vac_ref), ('vacancy_id', '=', self.vacancy_id.id)
        ])

        if not sel_records:
            return

        # Find reserve candidates sorted by weighted score desc
        reserve_candidates = self.env['external.recruitment.selected.candidates'].search([
            ('ext_rec_sel_cand', 'in', sel_records.ids),
            ('selection_type', 'in', ['reserved', 'Reserve', 'Reserved'])
        ], order='weighted_score desc')

        if reserve_candidates:
            top_reserve = reserve_candidates[0]
            top_reserve.write({
                'selection_type': 'selected',
                'remarks': _("Automatically promoted from Reserve Pool on %s .") % fields.Date.today()
            })
            
            msg = _(
                "<b>AUTO-PROMOTION ALERT:</b><br>"
                "Candidate <b>%s</b> has been automatically promoted from the Reserve Pool "
                "to <b>SELECTED</b> status for vacancy <b>%s</b> due to decline/expiry of the previous candidate.<br>"
                "Weighted Score: <b>%.2f%%</b>"
            ) % (
                top_reserve.applicant_name.partner_name if top_reserve.applicant_name else (top_reserve.emp_name or 'Reserve Candidate'),
                vac_ref,
                top_reserve.weighted_score or 0.0
            )

            # Log on selection process and offer letter chatter
            if hasattr(self.vacancy_id, 'message_post'):
                self.vacancy_id.message_post(body=msg)
            for s in sel_records:
                if hasattr(s, 'message_post'):
                    s.message_post(body=msg)
                
            # Create a draft offer letter for the newly promoted reserve candidate
            new_offer = self.create({
                'vacancy_id': self.vacancy_id.id,
                'ext_candidate_id': top_reserve.id,
                'applicant_id': top_reserve.applicant_name.id if top_reserve.applicant_name else False,
                'candidate_email': top_reserve.applicant_email,
                'notes': _("Auto-created for promoted reserve candidate %s.") % (top_reserve.emp_name or 'Candidate')
            })
            new_offer.message_post(body=_("Draft offer letter automatically created following reserve candidate promotion."))
        else:
            msg = _("No more reserve candidates available in the pool for vacancy %s.") % vac_ref
            if hasattr(self.vacancy_id, 'message_post'):
                self.vacancy_id.message_post(body=msg)
            self.message_post(body=msg)

    @api.model
    def _cron_expire_pending_offers(self):
        """
        Automated Cron Task (Runs Daily):
        Expires offers that have exceeded their configured response deadline_date without candidate response,
        and automatically escalates/promotes the top Reserve Candidate!
        """
        today = fields.Date.today()
        expired_offers = self.search([
            ('state', '=', 'sent'),
            '|',
            ('deadline_date', '<', today),
            '&', ('deadline_date', '=', False), ('expiry_date', '<', today)
        ])
        for rec in expired_offers:
            deadline_val = rec.deadline_date or rec.expiry_date
            rec.write({
                'state': 'expired',
                'rejection_reason': _("Auto-expired: Candidate failed to respond within deadline (%s).") % deadline_val
            })
            if rec.ext_candidate_id:
                rec.ext_candidate_id.write({
                    'selection_type': 'rejected',
                    'remarks': _("Offer Expired (Deadline %s exceeded)") % deadline_val
                })
            # Sync hr.applicant
            app = rec.applicant_id or (rec.ext_candidate_id.applicant_name if rec.ext_candidate_id else False)
            if not app and rec.candidate_email:
                app = self.env['hr.applicant'].search([('email_from', '=ilike', rec.candidate_email.strip())], limit=1)
            if app:
                app.write({
                    'job_offer_status': 'declined',
                    'rejection_reason': _("Auto-expired: Response deadline exceeded (%s).") % deadline_val
                })

            rec.message_post(body=_("Offer Letter EXPIRED (Deadline %s elapsed without response). Escalating to Reserve Pool...") % deadline_val)
            rec._cascade_to_next_reserve_candidate()


class RecruitmentOfferDeclineWizard(models.TransientModel):
    _name = 'recruitment.offer.decline.wizard'
    _description = 'Decline Offer Letter Wizard'

    offer_letter_id = fields.Many2one('recruitment.offer.letter', string='Offer Letter', required=True)
    reason = fields.Text(string='Reason for Declining', required=True)

    def action_confirm_decline(self):
        self.ensure_one()
        offer = self.offer_letter_id
        offer.rejection_reason = self.reason
        offer.write({'state': 'declined', 'response_date': fields.Date.today()})
        
        if offer.ext_candidate_id:
            offer.ext_candidate_id.write({
                'selection_type': 'rejected',
                'remarks': _("Declined Offer Letter: %s") % self.reason
            })
        
        # Sync hr.applicant
        app = offer.applicant_id or (offer.ext_candidate_id.applicant_name if offer.ext_candidate_id else False)
        if not app and offer.candidate_email:
            app = self.env['hr.applicant'].search([('email_from', '=ilike', offer.candidate_email.strip())], limit=1)
        if app:
            app.write({
                'job_offer_status': 'declined',
                'rejection_reason': self.reason
            })
        
        offer.message_post(body=_("Offer Letter DECLINED by candidate (%s). Escalating to Reserve Pool...") % self.reason)
        offer._cascade_to_next_reserve_candidate()
        return {'type': 'ir.actions.act_window_close'}
