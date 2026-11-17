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



_MINUTE_CSS_CACHE = None

def get_minute_font_faces_css():
    """Loads and base64-embeds the official Ethiopic Sadiss, Ebrima, and Barlow font families
    for 100% readable Amharic rendering across all operating systems (Linux & Windows).
    """
    global _MINUTE_CSS_CACHE
    if _MINUTE_CSS_CACHE:
        return _MINUTE_CSS_CACHE

    module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    font_dir = os.path.join(module_dir, "static", "src", "fonts")

    reg_path = os.path.join(font_dir, "Ethiopic Sadiss Regular.ttf")
    light_path = os.path.join(font_dir, "Ethiopic Sadiss Light.ttf")
    ebrima_reg_path = os.path.join(font_dir, "ebrima.ttf")
    ebrima_bd_path = os.path.join(font_dir, "ebrimabd.ttf")
    barlow_med_path = os.path.join(font_dir, "Barlow-Medium.ttf")
    barlow_bold_path = os.path.join(font_dir, "Barlow-Bold.ttf")

    if not os.path.exists(reg_path):
        reg_path = r"C:\Windows\Fonts\Ethiopic Sadiss Regular.ttf"
    if not os.path.exists(light_path):
        light_path = r"C:\Windows\Fonts\Ethiopic Sadiss Light.ttf"
    if not os.path.exists(ebrima_reg_path):
        ebrima_reg_path = r"C:\Windows\Fonts\ebrima.ttf"
    if not os.path.exists(ebrima_bd_path):
        ebrima_bd_path = r"C:\Windows\Fonts\ebrimabd.ttf"
    if not os.path.exists(barlow_med_path):
        barlow_med_path = r"C:\Windows\Fonts\Barlow-Medium.ttf"
    if not os.path.exists(barlow_bold_path):
        barlow_bold_path = r"C:\Windows\Fonts\barlow.bold.ttf"

    reg_b64 = ""
    light_b64 = ""
    ebrima_reg_b64 = ""
    ebrima_bd_b64 = ""
    barlow_med_b64 = ""
    barlow_bold_b64 = ""

    if os.path.exists(reg_path):
        with open(reg_path, "rb") as f:
            reg_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(light_path):
        with open(light_path, "rb") as f:
            light_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(ebrima_reg_path):
        with open(ebrima_reg_path, "rb") as f:
            ebrima_reg_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(ebrima_bd_path):
        with open(ebrima_bd_path, "rb") as f:
            ebrima_bd_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(barlow_med_path):
        with open(barlow_med_path, "rb") as f:
            barlow_med_b64 = base64.b64encode(f.read()).decode("utf-8")
    if os.path.exists(barlow_bold_path):
        with open(barlow_bold_path, "rb") as f:
            barlow_bold_b64 = base64.b64encode(f.read()).decode("utf-8")

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
body, div, p, span, strong, td, th, li, a, h1, h2, h3, h4, h5, h6, .page, .article {
    font-family: 'Ebrima', 'Nyala', 'Ethiopic Sadiss', Arial, sans-serif !important;
}
""")
    _MINUTE_CSS_CACHE = Markup("".join(css))
    return _MINUTE_CSS_CACHE


class IrActionsReportBarlowRecruitment(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()


class RecruitmentOfferLetterBarlow(models.Model):
    _inherit = 'recruitment.offer.letter'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()


class TransferLetterBarlow(models.Model):
    _inherit = 'transfer.letter'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()


class RecruitmentSelectionMinuteBarlow(models.Model):
    _inherit = 'recruitment.selection.minute'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()

    @api.model
    def get_minute_font_faces(self):
        return get_minute_font_faces_css()


class TransferCommitteeMinutesBarlow(models.Model):
    _inherit = 'transfer.committee.minutes'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()


class JobVacancyBarlow(models.Model):
    _inherit = 'job.vacancy'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()


class NewInternalRecruitmentSelectedBarlow(models.Model):
    _inherit = 'new.internal.recruitment.selected'

    @api.model
    def get_barlow_font_faces(self):
        return get_minute_font_faces_css()
