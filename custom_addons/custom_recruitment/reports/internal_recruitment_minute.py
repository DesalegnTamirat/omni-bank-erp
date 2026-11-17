# -*- coding: utf-8 -*-
import base64
import os
import datetime
from markupsafe import Markup
from odoo import api, fields, models


def gregorian_to_ethiopian(g_date):
    """Converts a Gregorian date/datetime or date string to Ethiopian Calendar string."""
    if not g_date:
        return ""
    if isinstance(g_date, str):
        try:
            g_date = datetime.datetime.strptime(g_date[:10], "%Y-%m-%d").date()
        except Exception:
            return str(g_date)
    elif isinstance(g_date, datetime.datetime):
        g_date = g_date.date()

    eth_months = [
        "", "መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት",
        "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜን"
    ]

    year = g_date.year
    month = g_date.month
    day = g_date.day

    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045

    r = (jdn - 1723856) % 1461
    n = (r % 365) + 365 * (r // 1460)
    eth_year = 4 * ((jdn - 1723856) // 1461) + (r // 365) - (r // 1460)
    eth_month = (n // 30) + 1
    eth_day = (n % 30) + 1

    if 1 <= eth_month <= 13:
        return f"{eth_months[eth_month]} {eth_day:02d} ቀን {eth_year} ዓ.ም"
    return str(g_date)


def amount_to_words_amharic(amount):
    """Convert float/int monetary amount to spelled-out formal Amharic words."""
    if not amount or amount <= 0:
        return ""

    units = ["", "አንድ", "ሁለት", "ሦስት", "አራት", "አምስት", "ስድስት", "ሰባት", "ስምንት", "ዘጠኝ"]
    teens = [
        "አስር", "አስራ አንድ", "አስራ ሁለት", "አስራ ሦስት", "አስራ አራት",
        "አስራ አምስት", "አስራ ስድስት", "አስራ ሰባት", "አስራ ስምንት", "አስራ ዘጠኝ"
    ]
    tens = ["", "አስር", "ሀያ", "ሰላሳ", "አርባ", "ሃምሳ", "ስድሳ", "ሰባ", "ሰማንያ", "ዘጠና"]

    def _convert_hundreds(n):
        res = []
        if n >= 100:
            h = n // 100
            if h == 1:
                res.append("አንድ መቶ")
            else:
                res.append(units[h] + " መቶ")
            n %= 100
        if 10 <= n <= 19:
            res.append(teens[n - 10])
        elif n >= 20:
            t = n // 10
            u = n % 10
            if u > 0:
                res.append(tens[t] + " " + units[u])
            else:
                res.append(tens[t])
        elif n > 0:
            res.append(units[n])
        return " ".join(res)

    int_part = int(round(amount))
    if int_part == 0:
        return "ዜሮ"

    billions = int_part // 1000000000
    int_part %= 1000000000
    millions = int_part // 1000000
    int_part %= 1000000
    thousands = int_part // 1000
    hundreds = int_part % 1000

    parts = []
    if billions > 0:
        parts.append(_convert_hundreds(billions) + " ቢሊዮን")
    if millions > 0:
        parts.append(_convert_hundreds(millions) + " ሚሊዮን")
    if thousands > 0:
        parts.append(_convert_hundreds(thousands) + " ሺህ")
    if hundreds > 0:
        parts.append(_convert_hundreds(hundreds))

    return " ".join(parts).strip()


def format_ethiopian_time(dt, is_end=False):
    """Formats datetime to Ethiopian traditional clock description (e.g. ከሰአት በ8፡00 ሰዓት)."""
    if not dt:
        return "ከምሽቱ በ1፡00 ሰዓት" if is_end else "ከሰአት በ8፡00 ሰዓት"
    if isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt

    # In EAT (UTC+3)
    hour = (dt.hour + 3) % 24
    minute = dt.minute
    if is_end:
        hour = min(23, hour + 5) if hour <= 18 else hour

    eth_hour = (hour - 6) % 12
    if eth_hour == 0:
        eth_hour = 12

    if 6 <= hour < 12:
        period = "ከጠዋቱ"
    elif 12 <= hour < 18:
        period = "ከሰአት"
    elif 18 <= hour < 23:
        period = "ከምሽቱ"
    else:
        period = "ከሌሊቱ"

    if minute > 0:
        return f"{period} በ{eth_hour}፡{minute:02d} ሰዓት"
    return f"{period} በ{eth_hour}፡00 ሰዓት"


def get_amharic_salutation(gender):
    if not gender:
        return ""
    g = str(gender).strip().lower()
    if g in ("female", "f", "woman", "w"):
        return "ወ/ይ"
    elif g in ("male", "m", "man"):
        return "አቶ"
    return ""


def format_cand_name_amharic(cand):
    if not cand or not cand.emp_name:
        return "____________"
    name = cand.emp_name.name.strip()
    if name.startswith(("አቶ", "ወ/ይ", "ወ/ሮ", "ወ/ሪት", "ዶ/ር", "Ato", "W/o", "W/rt", "Dr.")):
        return name
    gender = cand.emp_gender or (cand.emp_name.gender if hasattr(cand.emp_name, "gender") else False)
    salut = get_amharic_salutation(gender)
    if salut:
        return f"{salut} {name}"
    return name


def get_cand_workplace(cand):
    """Retrieves candidate workplace / branch name for District ranking table."""
    if not cand:
        return ""
    if cand.current_work_unit:
        return cand.current_work_unit
    if cand.preferred_location:
        return cand.preferred_location
    if cand.emp_name:
        if getattr(cand.emp_name, "branch_id", False) and cand.emp_name.branch_id:
            return cand.emp_name.branch_id.name
        if getattr(cand.emp_name, "operating_unit_id", False) and cand.emp_name.operating_unit_id:
            return cand.emp_name.operating_unit_id.name
        if getattr(cand.emp_name, "department_id", False) and cand.emp_name.department_id:
            return cand.emp_name.department_id.name
    return ""


def get_amharic_role(role_code):
    if not role_code:
        return "አባል"
    r = str(role_code).strip().lower()
    if "chair" in r or "ሰብሳቢ" in r:
        return "ሰብሳቢ"
    elif "sec" in r or "ፀሐፊ" in r or "ጸሐፊ" in r:
        return "አባል እና ፀሐፊ"
    elif "obs" in r or "union" in r or "labor" in r or "labour" in r or "ተወካይ" in r:
        return "ከሰራተኛ ማህበር የተገኙ ተወካይ"
    elif "member" in r or "panel" in r or "አባል" in r:
        return "አባል"
    return "አባል"


class InternalRecruitmentMinuteReport(models.AbstractModel):
    _name = "report.custom_recruitment.report_internal_rec_minute"
    _description = "Internal Recruitment Selection Committee Minute Report"

    def _get_bunna_logo_data_uri(self):
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            module_dir = os.path.dirname(curr_dir)
            logo_path = os.path.join(module_dir, "bunna_logo.jpg")
            if not os.path.exists(logo_path):
                logo_path = os.path.join(module_dir, "static", "src", "img", "bunna_logo.jpg")
            if os.path.exists(logo_path):
                with open(logo_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                    return f"data:image/jpeg;base64,{encoded}"
        except Exception:
            pass
        return False

    def _get_ethiopic_sadiss_font_faces(self):
        """Loads and base64-embeds the official Ethiopic Sadiss font family from Head office mini.docx & District min.docx."""
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            module_dir = os.path.dirname(curr_dir)
            font_dir = os.path.join(module_dir, "static", "src", "fonts")

            reg_path = os.path.join(font_dir, "Ethiopic Sadiss Regular.ttf")
            light_path = os.path.join(font_dir, "Ethiopic Sadiss Light.ttf")
            ebrima_reg_path = os.path.join(font_dir, "ebrima.ttf")
            ebrima_bd_path = os.path.join(font_dir, "ebrimabd.ttf")

            if not os.path.exists(reg_path):
                reg_path = r"C:\Windows\Fonts\Ethiopic Sadiss Regular.ttf"
            if not os.path.exists(light_path):
                light_path = r"C:\Windows\Fonts\Ethiopic Sadiss Light.ttf"
            if not os.path.exists(ebrima_reg_path):
                ebrima_reg_path = r"C:\Windows\Fonts\ebrima.ttf"
            if not os.path.exists(ebrima_bd_path):
                ebrima_bd_path = r"C:\Windows\Fonts\ebrimabd.ttf"

            reg_b64 = ""
            light_b64 = ""
            ebrima_reg_b64 = ""
            ebrima_bd_b64 = ""

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

            css_rules = []
            if ebrima_reg_b64:
                css_rules.append(f"""
@font-face {{
    font-family: 'Ebrima';
    src: url('data:font/truetype;charset=utf-8;base64,{ebrima_reg_b64}') format('truetype');
    font-weight: normal;
    font-style: normal;
}}
""")
            if ebrima_bd_b64:
                css_rules.append(f"""
@font-face {{
    font-family: 'Ebrima';
    src: url('data:font/truetype;charset=utf-8;base64,{ebrima_bd_b64}') format('truetype');
    font-weight: bold;
    font-style: normal;
}}
""")
            if reg_b64:
                css_rules.append(f"""
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
                css_rules.append(f"""
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
            css_rules.append("""
body, .page, table, td, th, p, span, h4, h5, div {
    font-family: 'Ebrima', 'Ethiopic Sadiss', 'Nyala', sans-serif !important;
}
""")
            from ..models.report_font_utils import get_barlow_font_faces_css
            barlow_css = get_barlow_font_faces_css()
            return Markup(str(barlow_css) + "".join(css_rules))
        except Exception:
            return Markup("""
body, .page, table, td, th, p, span, h4, h5, div {
    font-family: 'Ebrima', 'Ethiopic Sadiss', 'Nyala', sans-serif !important;
}
""")

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["new.internal.recruitment.selected"].browse(docids)
        doc_stats = {}
        doc_selected_candidates = {}
        doc_all_candidates = {}
        doc_committee_members = {}
        bunna_logo_data_uri = self._get_bunna_logo_data_uri()
        ethiopic_font_css = self._get_ethiopic_sadiss_font_faces()

        for doc in docs:
            all_cands = doc.new_int_rec_sel.filtered(lambda c: c.emp_name)

            selected_cands = all_cands.filtered(
                lambda c: c.selection_type in ("selected", "Selected")
            ).sorted(key=lambda c: c.rank or 9999)

            reserve_cands = all_cands.filtered(
                lambda c: c.selection_type in ("reserve", "Reserved")
            ).sorted(key=lambda c: c.rank or 9999)

            rejected_cands = all_cands.filtered(
                lambda c: c.selection_type in ("rejected", "Disqualified", "Rejected")
            )

            total_applicants = len(all_cands)
            shortlisted_applicants = len([c for c in all_cands if c.select_flag or c.select_flag is None])
            written_participants = len([c for c in all_cands if (c.written_exam_score or 0.0) > 0])
            written_absents = len([c for c in all_cands if not c.written_exam_score])
            written_passed = len([c for c in all_cands if (c.written_exam_score or 0.0) >= 50.0])
            interview_participants = len([c for c in all_cands if (c.interview_score or 0.0) > 0])
            interview_absents = len([c for c in all_cands if not c.interview_score])
            not_selected = len(rejected_cands)

            pms_w = int(doc.pms_weight) if doc.pms_weight else 40
            written_w = int(doc.written_weight) if doc.written_weight else 30
            interview_w = int(doc.interview_weight) if doc.interview_weight else 30

            # Dates and Times
            meeting_dt = doc.interview_date or fields.Datetime.now()
            meeting_date_et = gregorian_to_ethiopian(meeting_dt)
            meeting_time_et = format_ethiopian_time(doc.interview_date, is_end=False)
            meeting_time_end_et = format_ethiopian_time(doc.interview_date, is_end=True)

            # Fiscal Year calculation
            m_year = meeting_dt.year if hasattr(meeting_dt, "year") else datetime.date.today().year
            fiscal_year = f"{m_year}/{m_year + 1}"

            # Vacancy announced date formatting
            vac_announced = doc.vacancy_announced_on
            if not vac_announced and hasattr(doc, "vacancy_id") and getattr(doc.vacancy_id, "vacancy_announced_on", False):
                vac_announced = doc.vacancy_id.vacancy_announced_on
            if not vac_announced and doc.create_date:
                vac_announced = doc.create_date.date()

            if vac_announced:
                if isinstance(vac_announced, str):
                    try:
                        vac_announced = datetime.datetime.strptime(vac_announced[:10], "%Y-%m-%d").date()
                    except Exception:
                        pass
                vacancy_date_str = f"እ.ኤ.አ {vac_announced.strftime('%d/%m/%Y')}" if hasattr(vac_announced, 'strftime') else str(vac_announced)
            else:
                vacancy_date_str = "በቅርቡ"

            # Vacancy reference and minute number
            vac_ref = (doc.vacancy_reference or (doc.vacancy_id.reference if hasattr(doc, "vacancy_id") and getattr(doc.vacancy_id, "reference", False) else "") or "").strip()
            rec_ref = (doc.recruitment_reference or "").strip()

            minute_no = rec_ref or vac_ref or f"005/ ({m_year}/{m_year + 1})"
            if not minute_no.startswith("ቃለ"):
                minute_number_display = minute_no
            else:
                minute_number_display = minute_no.replace("ቃለ-ጉባዔ ቁጥር", "").strip()

            # Location / Unit
            vac_obj = self.env["job.vacancy"].browse(doc.vacancy_id) if isinstance(doc.vacancy_id, int) else doc.vacancy_id
            if doc.job_location:
                top_cand_unit = doc.job_location
            elif vac_obj and getattr(vac_obj, "operating_unit_id", False):
                top_cand_unit = vac_obj.operating_unit_id.name
            else:
                if doc.approval_hierarchy_type == "non_managerial_district":
                    top_cand_unit = "በአካባቢ ቢሮ ስር ለሚገኙ ቅርንጫፎች"
                else:
                    top_cand_unit = "Program management and innovation Directorate"

            # Exam venue
            exam_venue = doc.interview_location or (getattr(vac_obj, "interview_location", False) if vac_obj else False) or "በስራ ክፍሉ በተዘጋጀው ቦታ"

            # Candidates Amharic data & names & converted weighted scores
            cand_names = {}
            cand_ranks = {}
            cand_workplaces = {}
            cand_scores = {}
            for c in all_cands:
                cand_names[c.id] = format_cand_name_amharic(c)
                cand_ranks[c.id] = f"{c.rank}ኛ" if (c.rank and c.selection_type != 'rejected' and not getattr(c, 'is_disqualified', False)) else "-"
                cand_workplaces[c.id] = get_cand_workplace(c)

                pms_v = c.pms_score or 0.0
                exam_v = c.written_exam_score or 0.0
                intv_v = c.interview_score or 0.0

                pms_w_val = round(pms_v * (pms_w / 100.0), 2)
                exam_w_val = round(exam_v * (written_w / 100.0), 2)
                intv_w_val = round(intv_v * (interview_w / 100.0), 2)

                s_type = str(c.selection_type or '').strip().lower()
                is_disq = getattr(c, 'is_disqualified', False)
                remarks = "አልተመረጡም"
                if s_type in ('selected',):
                    remarks = "ተመርጠዋል"
                elif s_type in ('reserve', 'reserved'):
                    remarks = "ተጠባባቂ"
                elif getattr(c, 'is_absent', False) or (intv_v == 0.0 and getattr(c, 'remarks', '') and 'absent' in str(c.remarks).lower()):
                    remarks = "በቃለ መጠይቁ ላይ ያልተገኙ"
                elif exam_v == 0.0 and getattr(c, 'remarks', '') and 'absent' in str(c.remarks).lower():
                    remarks = "በፈተናው ላይ ያልተገኙ"
                elif s_type in ('rejected', 'disqualified') or is_disq:
                    remarks = "አልተመረጡም"

                cand_scores[c.id] = {
                    'pms_weighted': f"{pms_w_val:.2f}",
                    'written_weighted': f"{exam_w_val:.2f}",
                    'interview_weighted': f"{intv_w_val:.2f}",
                    'total_score': f"{(c.weighted_score or 0.0):.2f}",
                    'rank': cand_ranks[c.id],
                    'remarks': remarks,
                    'is_interview_absent': 'በቃለ መጠይቁ' in remarks,
                }

            top_cand = selected_cands[0] if selected_cands else False
            top_cand_name = format_cand_name_amharic(top_cand) if top_cand else "____________"

            # Multi-candidate selected information list
            selected_info_list = []
            for sc in selected_cands:
                sc_name = format_cand_name_amharic(sc)
                sal = 0.0
                if hasattr(sc, "get_promoted_salary_figure"):
                    try:
                        sal = sc.get_promoted_salary_figure()
                    except Exception:
                        sal = 0.0
                if not sal and hasattr(sc, "promoted_salary"):
                    sal = sc.promoted_salary or 0.0

                sc_salary_figure = f"{sal:,.2f}" if sal and sal > 0 else ""
                sc_salary_words = amount_to_words_amharic(sal) if sal and sal > 0 else ""
                sc_salary_step = "1ኛ እርከን"
                if hasattr(sc, "get_promoted_salary_step_amharic"):
                    sc_salary_step = sc.get_promoted_salary_step_amharic()

                current_wage = 0.0
                emp = sc.emp_name
                if emp:
                    if hasattr(emp, 'version_id') and emp.version_id and getattr(emp.version_id, 'wage', False):
                        current_wage = float(emp.version_id.wage or 0.0)
                    if not current_wage and 'hr.version' in self.env:
                        ver = self.env['hr.version'].sudo().search([('employee_id', '=', emp.id)], limit=1)
                        if ver and getattr(ver, 'wage', False):
                            current_wage = float(ver.wage or 0.0)
                    if not current_wage and hasattr(emp, 'contract_id') and emp.contract_id and getattr(emp.contract_id, 'wage', False):
                        current_wage = float(emp.contract_id.wage or 0.0)
                    if not current_wage and hasattr(emp, 'wage') and emp.wage:
                        current_wage = float(emp.wage or 0.0)

                base_sal = 0.0
                if hasattr(sc, '_get_grade_base_salary'):
                    try:
                        base_sal = float(sc._get_grade_base_salary() or 0.0)
                    except Exception:
                        base_sal = 0.0

                if (current_wage > 0 and base_sal > 0 and current_wage >= base_sal) or (sc_salary_step and sc_salary_step != "1ኛ እርከን"):
                    sc_clause = "የሚከፈላቸው ደመወዝ ከመነሻ በላይ በመሆኑ በደንቡ መሰረት"
                else:
                    sc_clause = "በባንኩ የደመወዝ ስኬል መመሪያ መሰረት"

                selected_info_list.append({
                    "id": sc.id,
                    "name": sc_name,
                    "rank": f"{sc.rank}ኛ" if sc.rank else "1ኛ",
                    "salary_fig": sc_salary_figure,
                    "salary_words": sc_salary_words,
                    "salary_step": sc_salary_step or "1ኛ እርከን",
                    "salary_clause": sc_clause,
                    "work_unit": get_cand_workplace(sc) or top_cand_unit,
                })

            top_cand_salary_figure = selected_info_list[0]["salary_fig"] if selected_info_list else ""
            top_cand_salary_words = selected_info_list[0]["salary_words"] if selected_info_list else ""
            top_cand_salary_step = selected_info_list[0]["salary_step"] if selected_info_list else "1ኛ እርከን"
            if selected_info_list and selected_info_list[0]["salary_step"] != "1ኛ እርከን":
                salary_clause_amharic = "ተወዳዳሪው የሚከፈላቸው ደመወዝ ከመነሻ በላይ በመሆኑ በደንቡ መሰረት"
            else:
                salary_clause_amharic = "በባንኩ የደመወዝ ስኬል መመሪያ መሰረት"

            # Reserve range in Amharic (Head Office)
            reserve_ranks = [c.rank for c in reserve_cands if c.rank]
            if reserve_ranks:
                min_r = min(reserve_ranks)
                max_r = max(reserve_ranks)
                if min_r == max_r:
                    res_range_amharic = f"በ{min_r}ኛ ደረጃ"
                else:
                    res_range_amharic = f"ከ{min_r}ኛ እስከ {max_r}ኛ ደረጃ"
            else:
                res_range_amharic = "በተጠባባቂነት የተመደቡትን"

            # Selected ranks text
            sel_ranks = [c.rank for c in selected_cands if c.rank]
            if sel_ranks:
                min_sel = min(sel_ranks)
                max_sel = max(sel_ranks)
                if min_sel == max_sel:
                    sel_ranks_text = f"{min_sel}ኛ ደረጃ"
                else:
                    sel_ranks_text = f"ከ{min_sel}ኛ እስከ {max_sel}ኛ ደረጃ"
            else:
                sel_ranks_text = f"ከ1ኛ እስከ {len(selected_cands)}ኛ ደረጃ"

            # District specific metrics
            selected_count = len(selected_cands) if selected_cands else len(all_cands)
            selected_count_words = amount_to_words_amharic(selected_count)
            district_ranks_text = sel_ranks_text

            # Committee Members formatted list with hierarchy ordering
            committee_list_raw = (
                doc.recr_selected_team_id
                or getattr(doc, "recr_exter_selected_team_id", False)
                or (getattr(doc, "vacancy_id", False) and getattr(doc.vacancy_id, "vac_del_team_id", False))
            )
            
            formatted_committee = []
            if committee_list_raw:
                role_priority = {
                    "chairperson": 1,
                    "chair_person": 1,
                    "panel_member": 2,
                    "member": 2,
                    "secretary": 3,
                    "member_secretary": 3,
                    "observer": 4,
                    "labor_representative": 4,
                }
                sorted_raw = sorted(
                    committee_list_raw,
                    key=lambda m: role_priority.get(str(m.role).lower(), 5)
                )
                for member in sorted_raw:
                    m_user = member.employee_name or member.alternate_committee_member
                    m_name = ""
                    if m_user:
                        m_name = m_user.name
                    elif hasattr(member, "emp_name") and member.emp_name:
                        m_name = member.emp_name.name
                    
                    if not m_name:
                        continue

                    if not m_name.startswith(("አቶ", "ወ/ይ", "ወ/ሮ", "ወ/ሪት", "ዶ/ር", "Ato", "W/o", "W/rt", "Dr.")):
                        emp_obj = getattr(m_user, "employee_id", False)
                        gender = getattr(emp_obj, "gender", False) if emp_obj else False
                        salut = get_amharic_salutation(gender)
                        if salut:
                            m_name = f"{salut} {m_name}"

                    m_role = member.role
                    if not m_role and hasattr(member, "get_committee_role"):
                        m_role = member.get_committee_role()
                    amharic_role = get_amharic_role(m_role)

                    sig_raw = (
                        member.digital_signature
                        or (member.get_signature_image() if hasattr(member, "get_signature_image") else False)
                    )

                    formatted_committee.append({
                        "name": m_name,
                        "role": amharic_role,
                        "signature": sig_raw,
                    })

            # If committee table is empty, check direct fields
            if not formatted_committee:
                direct_roles = [
                    (doc.chairperson_id, "ሰብሳቢ"),
                    (doc.panel_member_id, "አባል"),
                    (doc.secretary_id, "አባል እና ፀሐፊ"),
                    (doc.observer_id, "ከሰራተኛ ማህበር የተገኙ ተወካይ"),
                ]
                for user, amh_role in direct_roles:
                    if user:
                        u_name = user.name
                        emp_obj = getattr(user, "employee_id", False)
                        gender = getattr(emp_obj, "gender", False) if emp_obj else False
                        salut = get_amharic_salutation(gender)
                        if salut and not u_name.startswith(("አቶ", "ወ/ይ", "ወ/ሮ", "ወ/ሪት", "ዶ/ር")):
                            u_name = f"{salut} {u_name}"
                        sig = getattr(user, "digital_signature", False)
                        formatted_committee.append({
                            "name": u_name,
                            "role": amh_role,
                            "signature": sig,
                        })

            doc_committee_members[doc.id] = formatted_committee

            doc_stats[doc.id] = {
                "minute_number_display": minute_number_display,
                "meeting_date_et": meeting_date_et,
                "meeting_time_et": meeting_time_et,
                "meeting_time_end_et": meeting_time_end_et,
                "fiscal_year": fiscal_year,
                "vacancy_date_str": vacancy_date_str,
                "vacancy_reference": vac_ref or "BB/INT/2023/00109",
                "work_unit": top_cand_unit,
                "exam_venue": exam_venue,
                "total_applicants": total_applicants,
                "shortlisted_applicants": shortlisted_applicants,
                "written_participants": written_participants,
                "written_absents": written_absents,
                "written_passed": written_passed,
                "interview_participants": interview_participants,
                "interview_absents": interview_absents,
                "not_selected": not_selected,
                "pms_weight": pms_w,
                "written_weight": written_w,
                "interview_weight": interview_w,
                "top_cand_name": top_cand_name,
                "top_cand_salary_figure": top_cand_salary_figure,
                "top_cand_salary_words": top_cand_salary_words,
                "top_cand_salary_step": top_cand_salary_step,
                "salary_clause_amharic": salary_clause_amharic,
                "res_range_amharic": res_range_amharic,
                "selected_count": selected_count,
                "selected_count_words": selected_count_words,
                "district_ranks_text": district_ranks_text,
                "cand_names": cand_names,
                "cand_ranks": cand_ranks,
                "cand_workplaces": cand_workplaces,
                "cand_scores": cand_scores,
                "selected_info_list": selected_info_list,
                "sel_ranks_text": sel_ranks_text,
                "has_reserve": bool(reserve_cands),
            }
            doc_selected_candidates[doc.id] = selected_cands
            # Candidate list for minute table: all evaluated / ranked candidates sorted by rank and status
            ranked_minute_cands = all_cands.sorted(
                key=lambda c: (
                    0 if c.selection_type in ("selected", "Selected") else (1 if c.selection_type in ("reserve", "Reserved") else 2),
                    c.rank or 9999,
                    -(c.weighted_score or 0.0),
                    c.id
                )
            )
            doc_all_candidates[doc.id] = ranked_minute_cands

        return {
            "doc_ids": docids,
            "doc_model": "new.internal.recruitment.selected",
            "docs": docs,
            "doc_stats": doc_stats,
            "doc_selected_candidates": doc_selected_candidates,
            "doc_all_candidates": doc_all_candidates,
            "doc_committee_members": doc_committee_members,
            "bunna_logo_data_uri": bunna_logo_data_uri,
            "ethiopic_font_css": ethiopic_font_css,
            "data": data,
        }
