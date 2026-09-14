# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .recruitment_offer_letter import amount_to_words_birr

_logger = logging.getLogger(__name__)


class RecruitmentEmploymentLetter(models.Model):
    """
    Official Employment Letter (Appointment Letter) for External Hires.
    Mandatory for external candidates prior to employee and contract creation.
    - 60 working days probation for Non-Managerial positions
    - 70 working days probation for Managerial positions
    - Official QWeb PDF matching Bunna Bank's official letterhead template
    """
    _name = 'recruitment.employment.letter'
    _description = 'External Recruitment Employment Letter'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'letter_date desc, id desc'

    name = fields.Char(
        string='Letter Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent to Candidate'),
        ('approved', 'Approved'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    # ── Linked Records ───────────────────────────────────────────────
    applicant_id = fields.Many2one(
        'hr.applicant', string='Applicant (External)',
        required=True, ondelete='restrict', tracking=True
    )
    vacancy_id = fields.Many2one(
        'job.vacancy', string='Vacancy Reference', tracking=True
    )
    candidate_id = fields.Many2one(
        'external.recruitment.selected.candidates',
        string='Selected Candidate', tracking=True
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Hired Employee Record', readonly=True, tracking=True
    )

    # ── Recipient Details ─────────────────────────────────────────────
    candidate_title = fields.Selection([
        ('Ato', 'Ato'),
        ('W/ro', 'W/ro'),
        ('W/t', 'W/t'),
    ], string='Salutation', default='Ato', required=True)
    candidate_name = fields.Char(
        string='Full Name', required=True, tracking=True
    )
    candidate_address = fields.Char(
        string='City / Address', default='Addis Ababa'
    )
    id_no = fields.Char(
        string='ID No',
        help='Candidate National ID or Bunna Bank Employee ID'
    )
    candidate_email = fields.Char(
        string='Candidate Email',
        compute='_compute_candidate_email',
        store=True,
        readonly=False,
        help='Candidate email address registered during ATS.'
    )

    # ── Placement & Dates ─────────────────────────────────────────────
    letter_date = fields.Date(
        string='Letter Date', default=fields.Date.context_today, required=True
    )
    effective_date = fields.Date(
        string='Effective Date', default=fields.Date.context_today, required=True,
        help='Official date employment commences.'
    )
    job_id = fields.Many2one('hr.job', string='Job Position')
    job_position_name = fields.Char(
        string='Job Title', required=True,
        help='Official job position title displayed on the letter.'
    )
    job_grade_name = fields.Char(
        string='Job Grade', required=True,
        help='Job grade displayed on the letter, e.g. VI.'
    )
    work_unit_id = fields.Many2one(
        'operating.unit', string='Assigned Work Unit'
    )
    work_unit_name = fields.Char(
        string='Assigned Work Unit / Branch', required=True,
        help='Specific work unit, department, or branch assigned.'
    )

    # ── Compensation ──────────────────────────────────────────────────
    monthly_salary = fields.Float(
        string='Monthly Salary (Birr)', digits=(16, 2), required=True, tracking=True
    )
    salary_words = fields.Char(
        string='Salary in Words', compute='_compute_salary_words', store=True, readonly=False
    )

    # ── Managerial vs Non-Managerial & Probation Period ───────────────
    is_managerial = fields.Boolean(
        string='Managerial Position',
        compute='_compute_is_managerial',
        store=True,
        readonly=False,
        help='True if vacancy or job category is Managerial.'
    )
    probation_days = fields.Integer(
        string='Probationary Period (Working Days)',
        compute='_compute_probation_days',
        store=True,
        readonly=False,
        help='60 working days for Non-Managerial positions; 70 working days for Managerial positions.'
    )
    probation_eval_days = fields.Integer(
        string='Evaluation Advance Days',
        default=5,
        help='Number of days before expiry that the work unit must evaluate performance.'
    )

    # ── Clauses & CC Distribution ─────────────────────────────────────
    signatory_config_id = fields.Many2one(
        'recruitment.signatory.config',
        string='Signatory & Stamp Configuration',
        help='Configuration providing the official signature, stamp, and executive name'
    )
    signatory_name = fields.Char(
        string='Signatory Name',
        tracking=True
    )
    signatory_title = fields.Char(
        string='Authorized Signatory'
    )
    signatory_company = fields.Char(
        string='Company', default='Bunna Bank S.C.'
    )
    cc_district_or_work_unit = fields.Char(
        string='CC Assigned Unit / District',
        compute='_compute_cc_district',
        store=True,
        readonly=False
    )

    # ── Computations ──────────────────────────────────────────────────
    @api.depends('monthly_salary')
    def _compute_salary_words(self):
        for rec in self:
            if rec.monthly_salary and rec.monthly_salary > 0:
                words = amount_to_words_birr(rec.monthly_salary)
                # Strip "only" and "Birr" if template prefixes Birr before the figure
                words_clean = words.replace(" only", "").replace(" Birr", "").strip()
                rec.salary_words = words_clean
            else:
                rec.salary_words = ""

    def get_formatted_candidate_name(self):
        self.ensure_one()
        title = self.candidate_title or 'Ato'
        name = (self.candidate_name or '').strip()
        for t in ['Ato', 'W/ro', 'W/t', 'Dr.', 'Mr.', 'Mrs.', 'Ms.']:
            if name.lower().startswith(t.lower() + ' '):
                name = name[len(t):].strip()
                break
        return f"{title} {name}" if name else title

    def get_salutation_title_and_first_name(self):
        self.ensure_one()
        formatted = self.get_formatted_candidate_name()
        parts = formatted.split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1]}"
        return formatted

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        import base64
        import os

        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    @api.depends('vacancy_id', 'vacancy_id.employee_category', 'job_id')
    def _compute_is_managerial(self):
        for rec in self:
            if rec.vacancy_id and rec.vacancy_id.employee_category:
                rec.is_managerial = (rec.vacancy_id.employee_category == 'Managerial')
            else:
                rec.is_managerial = False

    @api.depends('is_managerial')
    def _compute_probation_days(self):
        for rec in self:
            rec.probation_days = 70 if rec.is_managerial else 60

    @api.depends('work_unit_name')
    def _compute_cc_district(self):
        for rec in self:
            rec.cc_district_or_work_unit = rec.work_unit_name or ''

    @api.depends('applicant_id.email_from')
    def _compute_candidate_email(self):
        for rec in self:
            if rec.applicant_id and rec.applicant_id.email_from:
                rec.candidate_email = rec.applicant_id.email_from.strip()
            elif not rec.candidate_email:
                rec.candidate_email = False

    def get_signatory_stamp_base64(self):
        """Returns Base64 data URI of the authorized signature & Bunna Bank rubber stamp."""
        self.ensure_one()
        if self.signatory_config_id:
            b64 = self.signatory_config_id.get_signature_stamp_base64()
            if b64:
                return b64

        active_sig = self.env['recruitment.signatory.config'].get_active_signatory('employment_letter')
        if active_sig:
            b64 = active_sig.get_signature_stamp_base64()
            if b64:
                return b64

        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    # ── CRUD & Sequence ───────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        active_sig = self.env['recruitment.signatory.config'].get_active_signatory('employment_letter')
        for vals in vals_list:
            if not vals.get('signatory_config_id') and active_sig:
                vals['signatory_config_id'] = active_sig.id
            if active_sig:
                if not vals.get('signatory_name'):
                    vals['signatory_name'] = active_sig.signatory_name
                if not vals.get('signatory_title'):
                    vals['signatory_title'] = active_sig.signatory_title
                if not vals.get('signatory_company'):
                    vals['signatory_company'] = active_sig.signatory_company

            if vals.get('name', _('New')) == _('New'):
                seq_code = 'bunna.recruitment.employment.letter'
                seq_name = self.env['ir.sequence'].next_by_code(seq_code)
                if not seq_name:
                    year = fields.Date.today().year
                    seq_name = f"-BB/TAOD/{self.env['ir.sequence'].search_count([('code', '=', seq_code)]) + 1:02d}/{year}"
                vals['name'] = seq_name
        records = super().create(vals_list)
        # Link back to applicant
        for rec in records:
            if rec.applicant_id and not rec.applicant_id.employment_letter_id:
                rec.applicant_id.sudo().write({'employment_letter_id': rec.id})
        return records

    # ── Workflow Actions ───────────────────────────────────────────────
    def action_approve(self):
        for rec in self:
            rec.state = 'approved'

    def action_issue(self):
        for rec in self:
            rec.state = 'issued'

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_print_employment_letter(self):
        self.ensure_one()
        return self.env.ref('custom_recruitment.action_report_recruitment_employment_letter').report_action(self)

    def action_send_letter(self):
        """Sends the employment letter with official PDF attachment to candidate email registered during ATS."""
        self.ensure_one()
        email_target = (self.candidate_email or (self.applicant_id.email_from if self.applicant_id else False) or '').strip()
        if not email_target:
            raise UserError(_(
                "Candidate Email Address Missing!\n\n"
                "Cannot send Employment Letter because no email address was registered during ATS application.\n"
                "Please specify the candidate's email address in the 'Candidate Email' field before sending."
            ))

        # 1. Generate PDF attachment using QWeb report
        report = self.env.ref('custom_recruitment.action_report_recruitment_employment_letter', raise_if_not_found=False)
        attachments = []
        if report:
            pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
                'custom_recruitment.action_report_recruitment_employment_letter', [self.id]
            )
            candidate_clean_name = (self.candidate_name or 'Candidate').replace(' ', '_')
            attachment = self.env['ir.attachment'].sudo().create({
                'name': f"Employment_Letter_{candidate_clean_name}.pdf",
                'type': 'binary',
                'raw': pdf_content,
                'res_model': 'recruitment.employment.letter',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(attachment.id)

        # 2. Compose Email Content
        salutation = self.get_salutation_title_and_first_name()
        pos_title = self.job_position_name or 'Job Position'
        work_unit = self.work_unit_name or 'Assigned Work Unit'
        eff_date = self.effective_date.strftime('%B %d, %Y') if self.effective_date else 'Effective Date'

        message_body = _(
            "<div style='font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222222; line-height: 1.6; max-width: 650px;'>"
            "<p>Dear <strong>%s</strong>,</p>"
            "<p>We are pleased to inform you that your application for employment has been accepted by the Management of <strong>Bunna Bank S.C.</strong><br>"
            "You are employed as <strong>%s</strong> effective <strong>%s</strong> and assigned to work at <strong>%s</strong>.</p>"
            "<p>Please find attached your official <strong>Employment Letter</strong> containing the comprehensive terms of your appointment, monthly salary, probation duration, and company policies.</p>"
            "<p>Wishing you remarkable success in your career, and warmly welcome to the Bunna family!</p>"
            "<br>"
            "<p style='margin-bottom: 2px;'>Sincerely yours,</p>"
            "<strong>Talent Acquisition &amp; Organization Development Directorate</strong><br>"
            "<strong>Bunna Bank S.C.</strong>"
            "</div>"
        ) % (salutation, pos_title, eff_date, work_unit)

        # 3. Create mail and dispatch
        mail_values = {
            'subject': _("Official Employment Letter - %s - Bunna Bank S.C.") % pos_title,
            'body_html': message_body,
            'email_to': email_target,
            'attachment_ids': [(6, 0, attachments)] if attachments else [],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        try:
            mail.send()
        except Exception as mail_ex:
            _logger.warning("Employment letter email dispatch warning: %s", mail_ex)

        # 4. Update status and post in chatter
        self.write({'state': 'sent'})
        self.message_post(
            body=_(
                "Official Employment Letter dispatched to candidate email: <b>%s</b> with PDF attachment."
            ) % email_target,
            subject=_("Employment Letter Dispatched"),
            attachment_ids=attachments
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employment Letter Dispatched'),
                'message': _('Official Employment Letter has been successfully emailed to %s.') % email_target,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
