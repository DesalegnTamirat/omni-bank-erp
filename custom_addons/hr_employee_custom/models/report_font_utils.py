# -*- coding: utf-8 -*-
import base64
import os
import logging
from markupsafe import Markup
from odoo import api, models

_logger = logging.getLogger(__name__)

_BARLOW_CSS_CACHE = None


def get_barlow_font_faces_css():
    """Loads and base64-embeds the official Barlow font family."""
    global _BARLOW_CSS_CACHE
    if _BARLOW_CSS_CACHE:
        return _BARLOW_CSS_CACHE

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
    if medium_b64:
        css.append(f"""
@font-face {{
    font-family: 'Barlow';
    src: url('data:font/truetype;charset=utf-8;base64,{medium_b64}') format('truetype');
    font-weight: 500;
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
body, div, p, span, strong, td, th, li, a, h1, h2, h3, h4, h5, h6, .page, .article {
    font-family: 'Barlow Medium', 'Barlow', Arial, sans-serif !important;
}
""")
    _BARLOW_CSS_CACHE = Markup("".join(css))
    return _BARLOW_CSS_CACHE


def get_bunna_logo_data_uri():
    import base64
    import os
    try:
        curr_dir = os.path.dirname(os.path.abspath(__file__))
        module_dir = os.path.dirname(curr_dir)
        logo_path = os.path.join(module_dir, 'static', 'src', 'img', 'bunna_logo.jpg')
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
                return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        pass
    return "/hr_employee_custom/static/src/img/bunna_logo.jpg"


class BaseLetterUtils(models.AbstractModel):
    _inherit = 'base'

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()

    def get_letter_signatory_name(self, doc_type='all'):
        """Universal helper to fetch authorized signatory full name."""
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type=doc_type)
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and sig.signatory_name:
                    return sig.signatory_name
            except Exception:
                pass
        return 'Melesse Leykun'

    def get_letter_signatory_title(self, doc_type='all'):
        """Universal helper to fetch authorized signatory title."""
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type=doc_type)
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and sig.signatory_title:
                    return sig.signatory_title
            except Exception:
                pass
        return 'Manager, People Services and Reward Division'

    def get_letter_signature_stamp(self, doc_type='all'):
        """Universal helper to fetch authorized signature and stamp base64 data URI."""
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type=doc_type)
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and hasattr(sig, 'get_signature_stamp_base64'):
                    b64 = sig.get_signature_stamp_base64()
                    if b64:
                        return b64
            except Exception:
                pass

        # Fallback to static asset
        import os, base64
        static_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'default_signatory_stamp.png')
        )
        if os.path.exists(static_path):
            with open(static_path, 'rb') as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"
        return ""

    def get_letter_signature_data(self, doc_type='all'):
        """Universal helper to fetch split signature & stamp data dictionary."""
        if 'recruitment.signatory.config' in self.env:
            try:
                sig = self.env['recruitment.signatory.config'].sudo().get_active_signatory(doc_type=doc_type)
                if not sig:
                    sig = self.env['recruitment.signatory.config'].sudo().search([('active', '=', True)], limit=1)
                if sig and hasattr(sig, 'get_letter_signature_data'):
                    return sig.get_letter_signature_data()
            except Exception:
                pass
        legacy_b64 = self.get_letter_signature_stamp(doc_type=doc_type)
        return {
            'has_split': False,
            'signature_b64': '',
            'stamp_b64': '',
            'stamp_position': 'right',
            'legacy_b64': legacy_b64,
            'signatory_name': self.get_letter_signatory_name(doc_type=doc_type),
            'signatory_title': self.get_letter_signatory_title(doc_type=doc_type),
            'signatory_company': 'Bunna Bank S.C.',
        }



def get_bunna_logo_data_uri():
    import base64
    import os
    try:
        curr_dir = os.path.dirname(os.path.abspath(__file__))
        module_dir = os.path.dirname(curr_dir)
        logo_path = os.path.join(module_dir, 'static', 'src', 'img', 'bunna_logo.jpg')
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
                return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        pass
    return "/hr_employee_custom/static/src/img/bunna_logo.jpg"


class IrActionsReportBarlow(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()


class HrEmployeeBarlow(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()


class HrApplicantBarlow(models.Model):
    _inherit = 'hr.applicant'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()


class TransferFormBarlow(models.Model):
    _inherit = 'transfer.form'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()


class HrVersionBarlow(models.Model):
    _inherit = 'hr.version'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()


class SupplementaryRoleBarlow(models.Model):
    _inherit = 'supplementary.role'

    @api.model
    def get_barlow_font_faces(self):
        return get_barlow_font_faces_css()

    @api.model
    def get_experience_letter_logo_data_uri(self):
        return get_bunna_logo_data_uri()
