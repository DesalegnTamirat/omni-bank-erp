# -*- coding: utf-8 -*-
import base64
import logging
import os
from datetime import timedelta
from markupsafe import Markup
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
    - Official QWeb PDF matching Bunna Bank's official letterhead template & Barlow font.
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
        ('W/y', 'W/y'),
        ('Dr.', 'Dr.'),
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
        string='Authorized Signatory',
        default='Director, People Operation Management Directorate'
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

    # ── Font Injection for Barlow Typography ─────────────────────────
    @api.model
    def get_barlow_font_faces(self):
        """Loads and base64-embeds the official Barlow Medium font family."""
        module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        font_dir = os.path.join(module_dir, "static", "src", "fonts")

        medium_path = os.path.join(font_dir, "Barlow-Medium.ttf")
        reg_path = os.path.join(font_dir, "Barlow-Regular.ttf")
        bold_path = os.path.join(font_dir, "Barlow-Bold.ttf")

        if not os.path.exists(medium_path):
            medium_path = r"C:\Windows\Fonts\Barlow-Medium.ttf"
        if not os.path.exists(reg_path):
            reg_path = r"C:\Windows\Fonts\barlow.regular.ttf"
        if not os.path.exists(bold_path):
            bold_path = r"C:\Windows\Fonts\barlow.bold.ttf"

        medium_b64 = ""
        reg_b64 = ""
        bold_b64 = ""

        if os.path.exists(medium_path):
            with open(medium_path, "rb") as f:
                medium_b64 = base64.b64encode(f.read()).decode("utf-8")
        if os.path.exists(reg_path):
            with open(reg_path, "rb") as f:
                reg_b64 = base64.b64encode(f.read()).decode("utf-8")
        if os.path.exists(bold_path):
            with open(bold_path, "rb") as f:
                bold_b64 = base64.b64encode(f.read()).decode("utf-8")

        css = []
        if medium_b64:
            css.append(f"""
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{medium_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{bold_b64 or medium_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
        if reg_b64:
            css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{reg_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
""")
        if bold_b64:
            css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{bold_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
        css.append("""
body, table, td, p, div, span, strong, b, em, i, u, h1, h2, h3, h4, h5, h6 {
    font-family: 'Barlow Medium', 'Barlow', Arial, sans-serif !important;
}
""")
        return Markup("".join(css))

    # ── Onchange Handlers ─────────────────────────────────────────────
    @api.onchange('candidate_id')
    def _onchange_candidate_id(self):
        if self.candidate_id:
            cand = self.candidate_id
            if cand.applicant_name and not self.applicant_id:
                self.applicant_id = cand.applicant_name.id
            if not self.candidate_name:
                self.candidate_name = cand.emp_name or (cand.applicant_name.partner_name if cand.applicant_name else '')
            if cand.applicant_email and not self.candidate_email:
                self.candidate_email = cand.applicant_email
            if cand.preferred_location and not self.candidate_address:
                self.candidate_address = cand.preferred_location
            if cand.position_id and not self.job_id:
                self.job_id = cand.position_id
            if cand.emp_position and not self.job_position_name:
                self.job_position_name = cand.emp_position
            if cand.vacancy_id and not self.vacancy_id:
                self.vacancy_id = cand.vacancy_id
            if cand.emp_gender and cand.emp_gender.lower() in ['female', 'f']:
                self.candidate_title = 'W/y'
            if self.vacancy_id or self.job_id:
                self._onchange_vacancy_or_job()

    @api.onchange('applicant_id')
    def _onchange_applicant_id(self):
        if self.applicant_id:
            app = self.applicant_id
            if not self.candidate_name:
                self.candidate_name = app.partner_name or app.name
            if not self.candidate_email:
                self.candidate_email = app.email_from
            if not self.job_id and app.job_id:
                self.job_id = app.job_id.id
                self.job_position_name = app.job_id.name
            if not self.vacancy_id and hasattr(app, 'vacancy_id') and app.vacancy_id:
                self.vacancy_id = app.vacancy_id.id
            elif not self.vacancy_id and hasattr(app, 'app_reference') and app.app_reference:
                self.vacancy_id = app.app_reference.id

    @api.onchange('job_id')
    def _onchange_job_id(self):
        if self.job_id:
            self.job_position_name = self.job_id.name

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        if self.work_unit_id:
            self.work_unit_name = self.work_unit_id.name

    @api.onchange('vacancy_id', 'job_id')
    def _onchange_vacancy_or_job(self):
        vac = self.vacancy_id
        if vac:
            if not self.job_id and vac.job_position:
                self.job_id = vac.job_position.id
            if not self.job_position_name and vac.job_position:
                self.job_position_name = vac.job_position.name
            grade = self._resolve_grade_from_vacancy_or_job()
            if grade:
                self.job_grade_name = grade
            if not self.work_unit_id and getattr(vac, 'operating_unit_id', False):
                self.work_unit_id = vac.operating_unit_id.id
                self.work_unit_name = vac.operating_unit_id.name
            elif not self.work_unit_id and vac.hiring_details:
                for hd in vac.hiring_details:
                    if hd.work_unit:
                        self.work_unit_id = hd.work_unit.id
                        self.work_unit_name = hd.work_unit.name
                        break
            if not self.monthly_salary or self.monthly_salary <= 0:
                sal = 0.0
                min_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', vac.id)], order='id desc', limit=1)
                if min_rec and (vac.job_grade):
                    mg = vac.job_grade
                    sal = getattr(mg, 'base_salary', 0.0) or getattr(mg, 'basic_salary', 0.0) or 0.0
                if not sal and vac.job_grade:
                    sal = getattr(vac.job_grade, 'base_salary', 0.0) or getattr(vac.job_grade, 'basic_salary', 0.0) or 0.0
                if not sal and vac.job_position and getattr(vac.job_position, 'grade', False):
                    sal = getattr(vac.job_position.grade, 'base_salary', 0.0) or getattr(vac.job_position.grade, 'basic_salary', 0.0) or 0.0
                if not sal:
                    sal = getattr(vac, 'starting_salary', 0.0) or getattr(vac, 'base_salary', 0.0) or getattr(vac, 'basic_salary', 0.0) or 0.0
                self.monthly_salary = sal
        elif self.job_id:
            if not self.job_position_name:
                self.job_position_name = self.job_id.name
            grade = self._resolve_grade_from_vacancy_or_job()
            if grade and not self.job_grade_name:
                self.job_grade_name = grade
            if not self.monthly_salary or self.monthly_salary <= 0:
                g = getattr(self.job_id, 'grade', False) or getattr(self.job_id, 'job_grade_id', False)
                if g:
                    self.monthly_salary = getattr(g, 'base_salary', 0.0) or getattr(g, 'basic_salary', 0.0) or 0.0

    # ── Grade Resolution Helper ───────────────────────────────────────
    def _resolve_grade_from_vacancy_or_job(self):
        vac = self.vacancy_id
        if not vac and self.candidate_id and self.candidate_id.vacancy_id:
            vac = self.env['job.vacancy'].browse(self.candidate_id.vacancy_id)
        if not vac and self.applicant_id:
            if hasattr(self.applicant_id, 'vacancy_id') and self.applicant_id.vacancy_id:
                vac = self.applicant_id.vacancy_id
            elif hasattr(self.applicant_id, 'app_reference') and self.applicant_id.app_reference:
                vac = self.applicant_id.app_reference

        if vac and vac.exists():
            if getattr(vac, 'job_grade', False):
                g = vac.job_grade
                g_str = getattr(g, 'grade_name', False) or getattr(g, 'name', False) or (g if isinstance(g, str) else False)
                if g_str and not str(g_str).startswith('employee.grade'):
                    return str(g_str).strip()
            if getattr(vac, 'job_grade_id', False):
                g = vac.job_grade_id
                g_str = getattr(g, 'grade_name', False) or getattr(g, 'name', False) or (g if isinstance(g, str) else False)
                if g_str and not str(g_str).startswith('employee.grade'):
                    return str(g_str).strip()
            if vac.job_position:
                g = getattr(vac.job_position, 'grade', False) or getattr(vac.job_position, 'job_grade_id', False)
                if g:
                    g_str = getattr(g, 'grade_name', False) or getattr(g, 'name', False) or (g if isinstance(g, str) else False)
                    if g_str and not str(g_str).startswith('employee.grade'):
                        return str(g_str).strip()

        if self.candidate_id:
            cg = getattr(self.candidate_id, 'emp_grade', False)
            if cg and not str(cg).startswith('employee.grade'):
                return str(cg).strip()
        if self.job_id:
            g = getattr(self.job_id, 'grade', False) or getattr(self.job_id, 'job_grade_id', False)
            if g:
                g_str = getattr(g, 'grade_name', False) or getattr(g, 'name', False) or (g if isinstance(g, str) else False)
                if g_str and not str(g_str).startswith('employee.grade'):
                    return str(g_str).strip()
        return ""

    def get_clean_job_grade(self):
        """Resolves clean job grade (Roman numeral e.g. VI, VIII) avoiding model representations."""
        self.ensure_one()
        grade = self.job_grade_name or ''
        if not grade or 'employee.grade' in str(grade):
            grade = self._resolve_grade_from_vacancy_or_job()
        clean = str(grade).replace('employee.grade', '').strip('(), \'\"')
        return clean or self.job_grade_name or ''

    # ── Computations ──────────────────────────────────────────────────
    @api.depends('monthly_salary')
    def _compute_salary_words(self):
        for rec in self:
            if rec.monthly_salary and rec.monthly_salary > 0:
                words = amount_to_words_birr(rec.monthly_salary)
                # Strip "only" and "Birr" if template prefixes Birr before the figure
                words_clean = words.replace(" only", "").replace(" Birr", "").replace("birr", "").strip()
                rec.salary_words = words_clean
            else:
                rec.salary_words = ""

    def get_formatted_candidate_name(self):
        """Returns formatted recipient name: <Title> <Candidate Full Name>"""
        self.ensure_one()
        title = self.candidate_title or 'Ato'
        name = (self.candidate_name or '').strip()
        for t in ['Ato', 'W/ro', 'W/t', 'W/y', 'Dr.', 'Mr.', 'Mrs.', 'Ms.']:
            if name.lower().startswith(t.lower() + ' '):
                name = name[len(t):].strip()
                break
        return f"{title} {name}" if name else title

    def get_formatted_candidate_name_clean(self):
        """Returns candidate full name without any salutation prefix (for evaluation paragraph 6)."""
        self.ensure_one()
        name = (self.candidate_name or '').strip()
        for t in ['Ato', 'W/ro', 'W/t', 'W/y', 'Dr.', 'Mr.', 'Mrs.', 'Ms.']:
            if name.lower().startswith(t.lower() + ' '):
                name = name[len(t):].strip()
                break
        return name

    def get_salutation_title_and_first_name(self):
        """Returns: <Title> <First Name> e.g. W/y Rahel or Ato Abebe"""
        self.ensure_one()
        clean = self.get_formatted_candidate_name_clean()
        title = self.candidate_title or 'Ato'
        first_name = clean.split()[0] if clean else ''
        return f"{title} {first_name}".strip()

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

    def get_letter_signature_data(self):
        """Returns structured dictionary with separate signature & stamp base64 data URIs."""
        self.ensure_one()
        sig = self.signatory_config_id
        if not sig and 'recruitment.signatory.config' in self.env:
            sig = self.env['recruitment.signatory.config'].get_active_signatory('employment_letter')
        if sig and hasattr(sig, 'get_letter_signature_data'):
            data = sig.get_letter_signature_data()
            if self.signatory_name:
                data['signatory_name'] = self.signatory_name
            if self.signatory_title:
                data['signatory_title'] = self.signatory_title
            if self.signatory_company:
                data['signatory_company'] = self.signatory_company
            return data
        legacy = self.get_signatory_stamp_base64()
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': legacy,
            'signatory_name': self.signatory_name or 'Abayneh Markos',
            'signatory_title': self.signatory_title or 'People Operation Management Directorate',
            'signatory_company': self.signatory_company or 'Bunna Bank S.C.',
        }

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

    # ── District and CC Helper ────────────────────────────────────────
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
            # Head office directorates and departments do NOT belong to any district
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

    def get_employment_letter_cc_lines(self):
        """
        Returns list of CC recipients exactly matching Bunna Bank's official employment letter template:
        1. Respective District (only if assigned branch is under a district)
        2. IT Security Management Directorate
        3. Assigned Branch / Work Unit (e.g. Enterprise Application Development and Operation Directorate)
        4. People Operation Management Directorate
        """
        self.ensure_one()
        lines = []
        assigned_unit = (self.work_unit_name or '').strip()
        ou = self.work_unit_id or (self.env['operating.unit'].search([('name', '=ilike', assigned_unit)], limit=1) if assigned_unit else False)

        # Do not include district for Head Office work units / directorates
        is_ho = False
        if ou:
            if getattr(ou, 'work_unit_type', '') in ('head_office', 'head_office_unit') or 'directorate' in (ou.name or '').lower() or 'department' in (ou.name or '').lower():
                is_ho = True
        elif 'directorate' in assigned_unit.lower() or 'department' in assigned_unit.lower() or 'head office' in assigned_unit.lower():
            is_ho = True

        if not is_ho:
            district = self._get_district_for_unit(ou or assigned_unit)
            if district and district.strip().lower() != assigned_unit.lower():
                lines.append(district.strip())

        lines.append("IT Security Management Directorate")
        if assigned_unit:
            lines.append(assigned_unit)
        lines.append("People Operation Management Directorate")
        return lines

    # ── CRUD & Sequence ───────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        active_sig = self.env['recruitment.signatory.config'].get_active_signatory('employment_letter')
        for vals in vals_list:
            # Auto-populate candidate details from candidate_id, applicant_id, and vacancy_id
            if vals.get('candidate_id'):
                cand = self.env['external.recruitment.selected.candidates'].browse(vals['candidate_id'])
                if not vals.get('applicant_id') and cand.applicant_name:
                    vals['applicant_id'] = cand.applicant_name.id
                if not vals.get('candidate_name'):
                    vals['candidate_name'] = cand.emp_name or (cand.applicant_name.partner_name if cand.applicant_name else '')
                if not vals.get('job_position_name') and cand.emp_position:
                    vals['job_position_name'] = cand.emp_position
                if not vals.get('vacancy_id') and cand.vacancy_id:
                    vals['vacancy_id'] = cand.vacancy_id
                if not vals.get('candidate_title') and cand.emp_gender and cand.emp_gender.lower() in ['female', 'f']:
                    vals['candidate_title'] = 'W/y'

            if vals.get('applicant_id'):
                app = self.env['hr.applicant'].browse(vals['applicant_id'])
                if not vals.get('candidate_name'):
                    vals['candidate_name'] = app.partner_name or app.name
                if not vals.get('job_position_name') and app.job_id:
                    vals['job_position_name'] = app.job_id.name
                if not vals.get('vacancy_id') and hasattr(app, 'vacancy_id') and app.vacancy_id:
                    vals['vacancy_id'] = app.vacancy_id.id

            if vals.get('vacancy_id'):
                vac = self.env['job.vacancy'].browse(vals['vacancy_id'])
                if not vals.get('job_id') and vac.job_position:
                    vals['job_id'] = vac.job_position.id
                if not vals.get('job_position_name') and vac.job_position:
                    vals['job_position_name'] = vac.job_position.name
                if not vals.get('job_grade_name') and vac.job_grade:
                    vals['job_grade_name'] = getattr(vac.job_grade, 'grade_name', False) or getattr(vac.job_grade, 'name', '')
                if not vals.get('work_unit_id') and getattr(vac, 'operating_unit_id', False):
                    vals['work_unit_id'] = vac.operating_unit_id.id
                if not vals.get('work_unit_name'):
                    if getattr(vac, 'operating_unit_id', False):
                        vals['work_unit_name'] = vac.operating_unit_id.name
                    elif getattr(vac, 'department_id', False):
                        vals['work_unit_name'] = vac.department_id.name
                if not vals.get('monthly_salary') or vals.get('monthly_salary') <= 0:
                    sal = 0.0
                    min_rec = self.env['recruitment.selection.minute'].search([('vacancy_id', '=', vac.id)], order='id desc', limit=1)
                    if min_rec:
                        min_grade = vac.job_grade
                        if min_grade:
                            sal = getattr(min_grade, 'base_salary', 0.0) or getattr(min_grade, 'basic_salary', 0.0) or 0.0
                    if not sal and vac.job_grade:
                        sal = getattr(vac.job_grade, 'base_salary', 0.0) or getattr(vac.job_grade, 'basic_salary', 0.0) or 0.0
                    if not sal and vac.job_position and getattr(vac.job_position, 'grade', False):
                        sal = getattr(vac.job_position.grade, 'base_salary', 0.0) or getattr(vac.job_position.grade, 'basic_salary', 0.0) or 0.0
                    if not sal:
                        sal = getattr(vac, 'starting_salary', 0.0) or getattr(vac, 'base_salary', 0.0) or getattr(vac, 'basic_salary', 0.0) or 0.0
                    vals['monthly_salary'] = sal

            if not vals.get('candidate_name'):
                vals['candidate_name'] = 'Candidate'
            if not vals.get('job_grade_name'):
                vals['job_grade_name'] = 'VI'
            if not vals.get('signatory_config_id') and active_sig:
                vals['signatory_config_id'] = active_sig.id
            if active_sig:
                if not vals.get('signatory_name'):
                    vals['signatory_name'] = active_sig.signatory_name
                if not vals.get('signatory_title'):
                    vals['signatory_title'] = active_sig.signatory_title
                if not vals.get('signatory_company'):
                    vals['signatory_company'] = active_sig.signatory_company
            else:
                if not vals.get('signatory_title'):
                    vals['signatory_title'] = 'Director, People Operation Management Directorate'
                if not vals.get('signatory_company'):
                    vals['signatory_company'] = 'Bunna Bank S.C.'

            if vals.get('name', _('New')) == _('New'):
                seq_code = 'bunna.recruitment.employment.letter'
                seq_name = self.env['ir.sequence'].next_by_code(seq_code)
                if not seq_name:
                    year = fields.Date.today().year
                    seq_count = self.env['ir.sequence'].search_count([('code', '=', seq_code)]) + 1
                    seq_name = f"BB/POMD/{seq_count:04d}/{year}"
                vals['name'] = seq_name
        records = super().create(vals_list)
        # Link back to applicant & candidate
        for rec in records:
            if rec.applicant_id and hasattr(rec.applicant_id, 'employment_letter_id'):
                try:
                    rec.applicant_id.sudo().write({'employment_letter_id': rec.id})
                except Exception:
                    pass
            if rec.candidate_id and hasattr(rec.candidate_id, 'employment_letter_id'):
                try:
                    rec.candidate_id.sudo().write({'employment_letter_id': rec.id})
                except Exception:
                    pass
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

    def write(self, vals):
        if vals.get('job_id') and 'job_position_name' not in vals:
            job = self.env['hr.job'].browse(vals['job_id'])
            vals['job_position_name'] = job.name
        if vals.get('work_unit_id') and 'work_unit_name' not in vals:
            wu = self.env['operating.unit'].browse(vals['work_unit_id'])
            vals['work_unit_name'] = wu.name
        return super().write(vals)

    def _check_offer_and_employee_prerequisites(self):
        """
        Validates that the candidate has:
        1. Formally accepted the Employment Offer Letter (state == 'accepted' or job_offer_status == 'accepted').
        2. Been registered in the Employee Master (hr.employee).
        Otherwise raises ValidationError blocking printing or dispatching of the employment letter.
        """
        self.ensure_one()
        candidate_label = self.candidate_name or _("Selected Candidate")

        # 1. Check Offer Letter Acceptance
        offer_accepted = False
        if self.applicant_id and getattr(self.applicant_id, 'job_offer_status', False) == 'accepted':
            offer_accepted = True
        elif 'recruitment.offer.letter' in self.env:
            from odoo.osv import expression
            domain = [('state', '=', 'accepted')]
            or_conditions = []
            if self.applicant_id:
                or_conditions.append(('applicant_id', '=', self.applicant_id.id))
            if self.candidate_id:
                or_conditions.append(('ext_candidate_id', '=', self.candidate_id.id))
            email = (self.candidate_email or (self.applicant_id.email_from if self.applicant_id else False) or '').strip()
            if email:
                or_conditions.append(('candidate_email', '=ilike', email))
            if or_conditions:
                accepted_offer = self.env['recruitment.offer.letter'].sudo().search(
                    expression.AND([domain, expression.OR([[c] for c in or_conditions])]),
                    limit=1
                )
                if accepted_offer:
                    offer_accepted = True
                    if self.applicant_id and self.applicant_id.job_offer_status != 'accepted':
                        self.applicant_id.sudo().write({'job_offer_status': 'accepted'})

        if not offer_accepted:
            raise ValidationError(_(
                "Validation Error: Offer Letter Not Accepted!\n\n"
                "Cannot print or send the Employment Letter because candidate '%s' has not yet formally accepted the Employment Offer Letter.\n\n"
                "Please ensure the candidate has formally accepted their offer letter before printing or sending the employment letter."
            ) % candidate_label)

        # 2. Check Employee Master Registration
        emp = self.employee_id or (self.applicant_id.employee_id if self.applicant_id else False)
        if not emp and self.applicant_id and hasattr(self.applicant_id, 'emp_id'):
            emp = self.applicant_id.emp_id

        # Robust resolution: Find created employee across applicants for this vacancy / candidate
        if not emp:
            matching_app = self.env['hr.applicant'].sudo().search([
                ('employee_id', '!=', False),
                '|',
                ('app_reference', '=', self.vacancy_id.id if self.vacancy_id else 0),
                ('vacancy_reference', '=', self.vacancy_id.reference if self.vacancy_id else ''),
                '|',
                ('email_from', '=ilike', (self.candidate_email or '').strip()),
                ('partner_name', '=ilike', (self.candidate_name or '').strip())
            ], order='id desc', limit=1)
            if matching_app and matching_app.employee_id:
                emp = matching_app.employee_id
                self.sudo().write({
                    'applicant_id': matching_app.id,
                    'employee_id': emp.id,
                })

        # Also search hr.employee directly by email or name if still not linked
        if not emp:
            Emp = self.env['hr.employee'].sudo()
            if self.candidate_email:
                emp = Emp.search([
                    '|',
                    ('work_email', '=ilike', self.candidate_email.strip()),
                    ('private_email', '=ilike', self.candidate_email.strip())
                ], limit=1)
            if not emp and self.candidate_name:
                emp = Emp.search([('name', '=ilike', self.candidate_name.strip())], limit=1)
            if emp:
                self.sudo().write({'employee_id': emp.id})

        if not emp:
            raise ValidationError(_(
                "Validation Error: Employee Not Registered in Employee Master!\n\n"
                "Cannot print or send the Employment Letter because candidate '%s' has not yet been registered in the Employee Master (hr.employee).\n\n"
                "Please register the employee (e.g., click 'Create Employee' on the Applicant record) before printing or issuing the employment letter."
            ) % candidate_label)

        # Sync employee_id on this employment letter if not set
        if not self.employee_id and emp:
            self.sudo().write({'employee_id': emp.id})

    def action_print_employment_letter(self):
        self.ensure_one()
        self._check_offer_and_employee_prerequisites()
        return self.env.ref('custom_recruitment.action_report_recruitment_employment_letter').report_action(self)

    def action_send_letter(self):
        """Sends the employment letter with official PDF attachment to candidate email registered during ATS."""
        self.ensure_one()
        self._check_offer_and_employee_prerequisites()
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
            "<strong>Director, People Operation Management Directorate</strong><br>"
            "<strong>Bunna Bank S.C.</strong>"
            "</div>"
        ) % (salutation, pos_title, eff_date, work_unit)

        # 3. Create mail and dispatch
        mail_server = self.env['ir.mail_server'].sudo().search([], limit=1)
        email_from = mail_server.smtp_user if mail_server and mail_server.smtp_user else (self.env.user.email or 'recruitment@bunnabanksc.com')
        mail_values = {
            'subject': _("Official Employment Letter - %s - Bunna Bank S.C.") % pos_title,
            'body_html': message_body,
            'email_to': email_target,
            'email_from': f"Bunna Bank Recruitment <{email_from}>" if '<' not in email_from else email_from,
            'mail_server_id': mail_server.id if mail_server else False,
            'attachment_ids': [(6, 0, attachments)] if attachments else [],
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        try:
            mail.send(raise_exception=True)
        except Exception as mail_ex:
            _logger.warning("Employment letter email dispatch direct send warning: %s", mail_ex)

        # 3.5. Dispatch CC Notifications via Discuss & Work Email to Work Unit Managers
        cc_lines = self.get_employment_letter_cc_lines()
        if cc_lines:
            try:
                from .cc_dispatch_service import dispatch_letter_cc_notifications
                details_html = (
                    f"• Appointed Candidate: <b>{self.candidate_name}</b><br/>"
                    f"• Letter Reference: <b>{self.name}</b><br/>"
                    f"• Job Position: <b>{pos_title}</b><br/>"
                    f"• Assigned Work Unit: <b>{work_unit}</b><br/>"
                    f"• Effective Date: <b>{eff_date}</b>"
                )
                dispatch_letter_cc_notifications(
                    self,
                    cc_lines,
                    letter_title=_("Official Employment Letter"),
                    letter_subject=_("Employment of %s as %s") % (self.candidate_name, pos_title),
                    details_html=details_html,
                    attachment_ids=attachments,
                )
            except Exception as cc_err:
                _logger.warning("Error dispatching CC notifications for employment letter: %s", cc_err)

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
