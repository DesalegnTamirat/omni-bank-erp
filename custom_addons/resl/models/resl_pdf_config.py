# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

DEFAULT_PAGES = [
    "/resl/static/agreement/page1.png",
    "/resl/static/agreement/page2.png",
    "/resl/static/agreement/page3.png",
    "/resl/static/agreement/page4.png",
    "/resl/static/agreement/page5.png",
    "/resl/static/agreement/page6.png",
]

DEFAULT_SLOTS_A = [
    {"p": "1", "r": [[158, 140, 257, 154]], "t": "{a_date}"},
    {"p": "1", "r": [[258, 140, 383, 154]], "t": "{a_name}"},
    {"p": "1", "r": [[446, 140, 520, 154], [72, 156, 407, 168]], "t": "ከተማ\u00a0{a_city} ክፍለ\u00a0ከተማ፤\u00a0{a_subcity} ወረዳ\u00a0{a_woreda} ቤት.ቁጥር-\u00a0{a_house} ቁጥር\u00a0{a_phone}"},
    {"p": "1", "r": [[528, 156, 580, 168]], "t": "{a_tax}"},
    {"p": "1", "r": [[248, 170, 352, 183]], "t": "መታወቂያ\u00a0ቁጥር-\u00a0{a_emp}"},
    {"p": "2", "r": [[221, 122, 540, 134]], "t": "{a_amt} ({a_amtw})"},
    {"p": "2", "r": [[165, 249, 540, 262], [126, 268, 204, 280]], "t": "{a_start} ጀምሮ በየወሩ {a_inst} ({a_instw})"},
]

DEFAULT_SLOTS_B = [
    {"p": "4", "r": [[135, 154, 236, 168]], "t": "{b_date}"},
    {"p": "4", "r": [[237, 154, 362, 168]], "t": "{b_name}"},
    {"p": "4", "r": [[427, 154, 540, 168], [72, 168, 257, 180]], "t": "{b_address} የቤት. ቁጥር {b_house}"},
    {"p": "4", "r": [[498, 168, 540, 180], [72, 180, 209, 192]], "t": "{b_tax}፤ የ.መ.ቁ {b_emp} ፤ስ.ቁጥር {b_phone}"},
    {"p": "4", "r": [[302, 221, 433, 234]], "t": "{b_borrower}"},
    {"p": "4", "r": [[440, 221, 540, 234]], "t": "{b_bdate}"},
    {"p": "4", "r": [[253, 241, 540, 254], [72, 260, 107, 272]], "t": "{b_amt} ({b_amtw})"},
    {"p": "4", "r": [[423, 382, 540, 395], [144, 401, 350, 413]], "t": "{b_amt} ({b_amtw})"},
    {"p": "5", "r": [[529, 485, 541, 497]], "t": ""},
    {"p": "5", "r": [[144, 503, 266, 516]], "t": "{b_branch1}/ዳይሬክቶሬት)እና("},
    {"p": "5", "r": [[271, 503, 376, 516]], "t": "{b_branch2}/ዳይሬክቶሬት)"},
]

DEFAULT_SIGS_A = [
    {"id": "sig_bank_a", "p": "3", "r": [100, 440, 205, 479]},
    {"id": "sig_borrower", "p": "3", "r": [385, 440, 495, 479]},
]

DEFAULT_SIGS_B = [
    {"id": "sig_bank_b", "p": "5", "r": [78, 536, 206, 557]},
    {"id": "sig_guarantor", "p": "5", "r": [389, 536, 514, 557]},
]


class ReslPdfConfig(models.Model):
    _name = 'resl.pdf.config'
    _description = 'RESL Loan Agreement PDF Configuration'

    name = fields.Char(string="Configuration Name", default="Default Agreement Template", required=True)
    is_active = fields.Boolean(string="Active Configuration", default=True)

    # ── Uploadable Full PDF Template (Replaces Agreement Template) ──────────
    agreement_pdf = fields.Binary(
        string="Upload Agreement PDF Template",
        attachment=True,
        help="Upload a single PDF file to replace the agreement template with your official contract document."
    )
    agreement_pdf_filename = fields.Char(string="PDF Filename")
    has_uploaded_pdf = fields.Boolean(string="Has Uploaded PDF", compute='_compute_has_uploaded_pdf')
    page_count = fields.Integer(string="PDF Page Count", compute='_compute_page_count')

    @api.depends('agreement_pdf')
    def _compute_has_uploaded_pdf(self):
        for rec in self:
            rec.has_uploaded_pdf = bool(rec.agreement_pdf)

    @api.depends('agreement_pdf')
    def _compute_page_count(self):
        import io
        import PyPDF2
        for rec in self:
            if rec.agreement_pdf:
                try:
                    pdf_bytes = base64.b64decode(rec.agreement_pdf)
                    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
                    rec.page_count = len(reader.pages)
                except Exception as e:
                    _logger.warning("Could not read PDF page count: %s", e)
                    rec.page_count = 0
            else:
                rec.page_count = 6

    # ── Uploadable Page Images (Every Page Can Be Changed) ───────────────────
    page_1_image = fields.Binary(string="Page 1 Image (Cover & Details)", attachment=True)
    page_2_image = fields.Binary(string="Page 2 Image (Articles 1-7)", attachment=True)
    page_3_image = fields.Binary(string="Page 3 Image (Articles 8-12 & Borrower Signatures)", attachment=True)
    page_4_image = fields.Binary(string="Page 4 Image (Part B - Guarantee Agreement)", attachment=True)
    page_5_image = fields.Binary(string="Page 5 Image (Part B - Articles 9-13 & Guarantor Signatures)", attachment=True)
    page_6_image = fields.Binary(string="Page 6 Image (Back / Final Page)", attachment=True)

    # ── Part A: Borrower Detailed Words & Clauses ───────────────────────────
    a_date_slot = fields.Char(string="Date Format", default="{a_date}")
    a_name_slot = fields.Char(string="Borrower Name Format", default="{a_name}")
    a_city_label = fields.Char(string="City Word (ከተማ)", default="ከተማ")
    a_subcity_label = fields.Char(string="Sub-City Word (ክፍለ ከተማ)", default="ክፍለ ከተማ፤")
    a_woreda_label = fields.Char(string="Woreda Word (ወረዳ)", default="ወረዳ")
    a_house_label = fields.Char(string="House No. Word (ቤት.ቁጥር-)", default="ቤት.ቁጥር-")
    a_phone_label = fields.Char(string="Phone Word (ቁጥር)", default="ቁጥር")
    a_tax_slot = fields.Char(string="Tax ID Format", default="{a_tax}")
    a_emp_label = fields.Char(string="Employee ID Word (መታወቂያ ቁጥር-)", default="መታወቂያ ቁጥር-")
    a_article_6_text = fields.Char(string="Article 6 (Loan Amount Clause)", default="{a_amt} ({a_amtw})")
    a_article_7_prefix = fields.Char(string="Article 7 (Start Date Clause)", default="{a_start} ጀምሮ በየወሩ")
    a_article_7_inst = fields.Char(string="Article 7 (Installment Clause)", default="{a_inst} ({a_instw})")

    # ── Part B: Guarantor Detailed Words & Clauses ──────────────────────────
    b_date_slot = fields.Char(string="Date Format", default="{b_date}")
    b_name_slot = fields.Char(string="Guarantor Name Format", default="{b_name}")
    b_house_label = fields.Char(string="House No. Word (የቤት. ቁጥር)", default="የቤት. ቁጥር")
    b_tax_label = fields.Char(string="Tax ID Word (የግብር ከፋይ መለያ ቁጥር)", default="{b_tax}፤")
    b_emp_label = fields.Char(string="Employee ID Word (የ.መ.ቁ)", default="የ.መ.ቁ")
    b_phone_label = fields.Char(string="Phone Word (ስ.ቁጥር)", default="፤ስ.ቁጥር")
    b_borrower_slot = fields.Char(string="Borrower Name Reference", default="{b_borrower}")
    b_bdate_slot = fields.Char(string="Borrower Agreement Date Reference", default="{b_bdate}")
    b_article_loan_amt = fields.Char(string="Loan Amount Clause (Guarantor)", default="{b_amt} ({b_amtw})")
    b_branch1_suffix = fields.Char(string="Article 11 Borrower Branch Clause", default="/ዳይሬክቶሬት)እና(")
    b_branch2_suffix = fields.Char(string="Article 11 Guarantor Branch Clause", default="/ዳይሬክቶሬት)")

    # ── Advanced Raw JSON Fields (Pre-populated) ─────────────────────────────
    pages_json = fields.Text(
        string="Pages (JSON list of URLs)",
        default=lambda self: json.dumps(DEFAULT_PAGES, indent=2, ensure_ascii=False)
    )
    slots_a_json = fields.Text(
        string="Part A Slots Coordinates & Format",
        default=lambda self: json.dumps(DEFAULT_SLOTS_A, indent=2, ensure_ascii=False)
    )
    slots_b_json = fields.Text(
        string="Part B Slots Coordinates & Format",
        default=lambda self: json.dumps(DEFAULT_SLOTS_B, indent=2, ensure_ascii=False)
    )
    sigs_a_json = fields.Text(
        string="Part A Signatures",
        default=lambda self: json.dumps(DEFAULT_SIGS_A, indent=2, ensure_ascii=False)
    )
    sigs_b_json = fields.Text(
        string="Part B Signatures",
        default=lambda self: json.dumps(DEFAULT_SIGS_B, indent=2, ensure_ascii=False)
    )

    def init(self):
        """Auto-populate the default agreement configuration record on install/upgrade."""
        super().init()
        if not self.sudo().search_count([]):
            self.sudo().create({
                'name': 'Standard Staff Loan Agreement Template',
                'is_active': True,
            })

    def _compile_slots_from_fields(self):
        """Assemble the active slot wording from individual fields."""
        self.ensure_one()
        nb = "\u00a0"
        slots_a = [
            {"p": "1", "r": [[158, 140, 257, 154]], "t": self.a_date_slot or "{a_date}"},
            {"p": "1", "r": [[258, 140, 383, 154]], "t": self.a_name_slot or "{a_name}"},
            {"p": "1", "r": [[446, 140, 520, 154], [72, 156, 407, 168]],
             "t": f"{self.a_city_label or 'ከተማ'}{nb}{{a_city}} {self.a_subcity_label or 'ክፍለ ከተማ፤'}{nb}{{a_subcity}} {self.a_woreda_label or 'ወረዳ'}{nb}{{a_woreda}} {self.a_house_label or 'ቤት.ቁጥር-'}{nb}{{a_house}} {self.a_phone_label or 'ቁጥር'}{nb}{{a_phone}}"},
            {"p": "1", "r": [[528, 156, 580, 168]], "t": self.a_tax_slot or "{a_tax}"},
            {"p": "1", "r": [[248, 170, 352, 183]], "t": f"{self.a_emp_label or 'መታወቂያ ቁጥር-'}{nb}{{a_emp}}"},
            {"p": "2", "r": [[221, 122, 540, 134]], "t": self.a_article_6_text or "{a_amt} ({a_amtw})"},
            {"p": "2", "r": [[165, 249, 540, 262], [126, 268, 204, 280]],
             "t": f"{self.a_article_7_prefix or '{a_start} ጀምሮ በየወሩ'} {self.a_article_7_inst or '{a_inst} ({a_instw})'}"},
        ]
        slots_b = [
            {"p": "4", "r": [[135, 154, 236, 168]], "t": self.b_date_slot or "{b_date}"},
            {"p": "4", "r": [[237, 154, 362, 168]], "t": self.b_name_slot or "{b_name}"},
            {"p": "4", "r": [[427, 154, 540, 168], [72, 168, 257, 180]],
             "t": f"{{b_address}} {self.b_house_label or 'የቤት. ቁጥር'} {{b_house}}"},
            {"p": "4", "r": [[498, 168, 540, 180], [72, 180, 209, 192]],
             "t": f"{self.b_tax_label or '{b_tax}፤'} {self.b_emp_label or 'የ.መ.ቁ'} {{b_emp}} {self.b_phone_label or '፤ስ.ቁጥር'} {{b_phone}}"},
            {"p": "4", "r": [[302, 221, 433, 234]], "t": self.b_borrower_slot or "{b_borrower}"},
            {"p": "4", "r": [[440, 221, 540, 234]], "t": self.b_bdate_slot or "{b_bdate}"},
            {"p": "4", "r": [[253, 241, 540, 254], [72, 260, 107, 272]],
             "t": self.b_article_loan_amt or "{b_amt} ({b_amtw})"},
            {"p": "4", "r": [[423, 382, 540, 395], [144, 401, 350, 413]],
             "t": self.b_article_loan_amt or "{b_amt} ({b_amtw})"},
            {"p": "5", "r": [[529, 485, 541, 497]], "t": ""},
            {"p": "5", "r": [[144, 503, 266, 516]],
             "t": f"{{b_branch1}}{self.b_branch1_suffix or '/ዳይሬክቶሬት)እና('}"},
            {"p": "5", "r": [[271, 503, 376, 516]],
             "t": f"{{b_branch2}}{self.b_branch2_suffix or '/ዳይሬክቶሬት)'}"},
        ]
        return slots_a, slots_b

    def _get_pages_list(self):
        """Build page URLs, preferring uploaded image attachments over defaults."""
        self.ensure_one()
        pages = []
        for i in range(1, 7):
            fld = f"page_{i}_image"
            if getattr(self, fld, False):
                pages.append(f"/resl/agreement/page_img/{self.id}/{i}")
            else:
                pages.append(f"/resl/static/agreement/page{i}.png")
        return pages

    @api.model
    def get_active_config(self):
        """Returns the dictionary used by the agreement frontend."""
        rec = self.search([('is_active', '=', True)], limit=1)
        if not rec:
            rec = self.search([], limit=1)
        if not rec:
            return {
                'pdf_url': None,
                'pdf_filename': '',
                'page_count': 6,
                'pages': DEFAULT_PAGES,
                'slots_a': DEFAULT_SLOTS_A,
                'slots_b': DEFAULT_SLOTS_B,
                'sigs_a': DEFAULT_SIGS_A,
                'sigs_b': DEFAULT_SIGS_B,
            }
        pages = rec._get_pages_list()
        slots_a, slots_b = rec._compile_slots_from_fields()

        def _parse(text_val, fallback):
            try:
                return json.loads(text_val) if text_val else fallback
            except Exception:
                return fallback

        # If user explicitly customized raw JSON, use it; otherwise use compiled fields
        final_slots_a = slots_a if slots_a else _parse(rec.slots_a_json, DEFAULT_SLOTS_A)
        final_slots_b = slots_b if slots_b else _parse(rec.slots_b_json, DEFAULT_SLOTS_B)

        pdf_url = f"/resl/agreement/config_pdf/{rec.id}" if rec.agreement_pdf else None

        return {
            'pdf_url': pdf_url,
            'pdf_filename': rec.agreement_pdf_filename or '',
            'page_count': rec.page_count or 6,
            'pages': pages,
            'slots_a': final_slots_a,
            'slots_b': final_slots_b,
            'sigs_a': _parse(rec.sigs_a_json, DEFAULT_SIGS_A),
            'sigs_b': _parse(rec.sigs_b_json, DEFAULT_SIGS_B),
        }

    @api.model
    def action_open_active_config(self):
        """Called by the menu item to immediately open the agreement form."""
        rec = self.search([('is_active', '=', True)], limit=1)
        if not rec:
            rec = self.search([], limit=1)
        if not rec:
            rec = self.create({
                'name': 'Standard Staff Loan Agreement Template',
                'is_active': True,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agreement PDF Configuration'),
            'res_model': 'resl.pdf.config',
            'view_mode': 'form',
            'res_id': rec.id,
            'target': 'current',
        }

    def action_preview_agreement(self):
        """Open the agreement preview in a new browser tab."""
        self.ensure_one()
        loan = self.env['resl.loan'].search([], limit=1)
        loan_id = loan.id if loan else 1
        return {
            'type': 'ir.actions.act_url',
            'url': f'/resl/agreement/{loan_id}',
            'target': 'new',
        }

    def action_download_pdf(self):
        """Download or view the currently uploaded PDF template."""
        self.ensure_one()
        if not self.agreement_pdf:
            raise ValidationError(_("No PDF file has been uploaded yet."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/resl/agreement/config_pdf/{self.id}',
            'target': 'new',
        }

    def action_clear_pdf(self):
        """Remove the uploaded PDF template to revert to the default agreement."""
        self.ensure_one()
        self.write({
            'agreement_pdf': False,
            'agreement_pdf_filename': False,
        })

