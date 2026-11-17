# -*- coding: utf-8 -*-
import base64
import os
import logging
from markupsafe import Markup
from odoo import api, models

_logger = logging.getLogger(__name__)

_BARLOW_CSS_CACHE = None
_MINUTE_CSS_CACHE = None


def _find_font(filename, win_fallback=None):
    """Universal font resolver looking in current module, recruitment, hr_employee_custom, and system fonts."""
    module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    search_dirs = [
        os.path.join(module_dir, "static", "src", "fonts"),
        os.path.abspath(os.path.join(module_dir, "..", "custom_recruitment", "static", "src", "fonts")),
        os.path.abspath(os.path.join(module_dir, "..", "hr_employee_custom", "static", "src", "fonts")),
        "/usr/share/fonts/truetype",
        "/usr/local/share/fonts",
    ]
    for d in search_dirs:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p
    if win_fallback and os.path.exists(win_fallback):
        return win_fallback
    return None


def _load_base64(path):
    if path and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            _logger.warning("Failed to read font file %s: %s", path, e)
    return ""


def get_barlow_font_faces_css():
    """Loads and base64-embeds the official Barlow font family (Recruitment style)."""
    global _BARLOW_CSS_CACHE
    if _BARLOW_CSS_CACHE:
        return _BARLOW_CSS_CACHE

    medium_b64 = _load_base64(_find_font("Barlow-Medium.ttf", r"C:\Windows\Fonts\Barlow-Medium.ttf"))
    reg_b64 = _load_base64(_find_font("Barlow-Regular.ttf", r"C:\Windows\Fonts\barlow.regular.ttf"))
    bold_b64 = _load_base64(_find_font("Barlow-Bold.ttf", r"C:\Windows\Fonts\barlow.bold.ttf"))

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
body, div, p, span, strong, td, th, li, a, h1, h2, h3, h4, h5, h6, .page, .article {
    font-family: 'Barlow Medium', 'Barlow', Arial, sans-serif !important;
}
""")
    _BARLOW_CSS_CACHE = Markup("".join(css))
    return _BARLOW_CSS_CACHE


def get_minute_font_faces_css():
    """Loads and base64-embeds the official Ethiopic Sadiss, Ebrima, and Barlow font families
    for 100% readable Amharic rendering across all operating systems (Linux Docker & Windows).
    Identical to custom_recruitment report_font_utils.
    """
    global _MINUTE_CSS_CACHE
    if _MINUTE_CSS_CACHE:
        return _MINUTE_CSS_CACHE

    reg_b64 = _load_base64(_find_font("Ethiopic Sadiss Regular.ttf", r"C:\Windows\Fonts\Ethiopic Sadiss Regular.ttf"))
    light_b64 = _load_base64(_find_font("Ethiopic Sadiss Light.ttf", r"C:\Windows\Fonts\Ethiopic Sadiss Light.ttf"))
    ebrima_reg_b64 = _load_base64(_find_font("ebrima.ttf", r"C:\Windows\Fonts\ebrima.ttf"))
    ebrima_bd_b64 = _load_base64(_find_font("ebrimabd.ttf", r"C:\Windows\Fonts\ebrimabd.ttf"))
    barlow_med_b64 = _load_base64(_find_font("Barlow-Medium.ttf", r"C:\Windows\Fonts\Barlow-Medium.ttf"))
    barlow_bold_b64 = _load_base64(_find_font("Barlow-Bold.ttf", r"C:\Windows\Fonts\barlow.bold.ttf"))

    css = []
    if reg_b64:
        css.append(f"""
@font-face {{
    font-family: 'Ethiopic Sadiss';
    src: url('data:font/truetype;charset=utf-8;base64,{reg_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: 'Ethiopic Sadiss';
    src: url('data:font/truetype;charset=utf-8;base64,{reg_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
    if light_b64:
        css.append(f"""
@font-face {{
    font-family: 'Ethiopic Sadiss Light';
    src: url('data:font/truetype;charset=utf-8;base64,{light_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: 'Ethiopic Sadiss Light';
    src: url('data:font/truetype;charset=utf-8;base64,{light_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
    if ebrima_reg_b64:
        css.append(f"""
@font-face {{
    font-family: 'Ebrima';
    src: url('data:font/truetype;charset=utf-8;base64,{ebrima_reg_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
""")
    if ebrima_bd_b64:
        css.append(f"""
@font-face {{
    font-family: 'Ebrima';
    src: url('data:font/truetype;charset=utf-8;base64,{ebrima_bd_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
    if barlow_med_b64:
        css.append(f"""
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{barlow_med_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
@font-face {{
    font-family: 'Barlow Medium';
    src: url('data:font/truetype;charset=utf-8;base64,{barlow_bold_b64 or barlow_med_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
    css.append("""
body, div, p, span, strong, td, th, li, a, h1, h2, h3, h4, h5, h6, .page, .article, .article * {
    font-family: 'Ebrima', 'Nyala', 'Ethiopic Sadiss', Arial, sans-serif !important;
}
""")
    _MINUTE_CSS_CACHE = Markup("".join(css))
    return _MINUTE_CSS_CACHE


class IrActionsReportDiscipline(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        return get_minute_font_faces_css()


class DisciplineCaseFontUtils(models.Model):
    _inherit = 'discipline.case'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        return get_minute_font_faces_css()


class DisciplineAttendanceCaseFontUtils(models.Model):
    _inherit = 'discipline.attendance.case'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        return get_minute_font_faces_css()


class DisciplineSuspensionFontUtils(models.Model):
    _inherit = 'discipline.suspension'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        return get_minute_font_faces_css()


class DisciplineCommitteeFontUtils(models.Model):
    _inherit = 'discipline.committee.meeting'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        return get_minute_font_faces_css()
