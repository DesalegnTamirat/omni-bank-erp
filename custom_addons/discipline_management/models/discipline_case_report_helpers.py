# -*- coding: utf-8 -*-
import base64
import io
import os
import re
from datetime import timedelta
from PIL import Image
from odoo import models, fields, api, _
from odoo.exceptions import UserError


def gregorian_to_ethiopian(g_date):
    """
    Converts Gregorian date or datetime to Ethiopian Calendar.
    Returns tuple: (short_format_str, long_format_str, (year, month, day))
    Example: 2026-11-07 -> ('28/02/2019 ዓ.ም.', 'ጥቅምት 28 ቀን 2019 ዓ.ም.', (2019, 2, 28))
    """
    if not g_date:
        return '', '', (0, 0, 0)
    if hasattr(g_date, 'date'):
        g_date = g_date.date()
    gy, gm, gd = g_date.year, g_date.month, g_date.day

    amharic_months = [
        '', 'መስከረም', 'ጥቅምት', 'ኅዳር', 'ታኅሣሥ', 'ጥር', 'የካቲት',
        'መጋቢት', 'ሚያዝያ', 'ግንቦት', 'ሰኔ', 'ሐምሌ', 'ነሐሴ', 'ጳጉሜን'
    ]

    g_leap = 1 if (gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)) else 0
    g_days = [0, 31, 28 + g_leap, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day_of_year = sum(g_days[:gm]) + gd

    new_year_day = 255 if (gy % 4 == 0) else 254
    if ((gy - 1) % 4 == 3):
        new_year_day += 1

    if day_of_year >= new_year_day:
        ey = gy - 7
        diff = day_of_year - new_year_day
        em = (diff // 30) + 1
        ed = (diff % 30) + 1
    else:
        ey = gy - 8
        prev_gy = gy - 1
        prev_g_leap = 1 if (prev_gy % 4 == 0 and (prev_gy % 100 != 0 or prev_gy % 400 == 0)) else 0
        prev_total_days = 366 if prev_g_leap else 365
        prev_new_year = 255 if ((prev_gy - 1) % 4 == 3) else (255 if prev_g_leap else 254)
        diff = (prev_total_days - prev_new_year) + day_of_year
        em = (diff // 30) + 1
        ed = (diff % 30) + 1

    m_name = amharic_months[em] if 1 <= em <= 13 else str(em)
    short_str = f"{ed:02d}/{em:02d}/{ey} ዓ.ም."
    long_str = f"{m_name} {ed} ቀን {ey} ዓ.ም."
    return short_str, long_str, (ey, em, ed)


class DisciplineCaseReportHelpers(models.Model):
    _inherit = 'discipline.case'

    def action_print_warning_letter(self):
        """Print the formal Disciplinary Sanction / Decision Notice Letter."""
        self.ensure_one()
        if self.is_exonerated_case:
            raise UserError(_("Cannot Print Warning Letter: This case has been Exonerated with no disciplinary penalty. Please print the 'Clearance Certificate' instead."))
        return self.env.ref('discipline_management.action_report_disciplinary_warning_letter').report_action(self)

    def action_print_exoneration_certificate(self):
        """Print the official Exoneration & Clearance Certificate."""
        self.ensure_one()
        if not self.is_exonerated_case:
            raise UserError(_("Cannot Print Clearance Certificate: This case resulted in an active disciplinary penalty. Please print the 'Disciplinary Decision Notice' instead."))
        return self.env.ref('discipline_management.action_report_exoneration_certificate').report_action(self)

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        """Loads and base64-embeds the official Ethiopic Sadiss, Ebrima, and Barlow font families for wkhtmltopdf PDF rendering."""
        from .report_font_utils import get_minute_font_faces_css
        return get_minute_font_faces_css()

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def get_formatted_employee_name(self):
        """Returns formatted full recipient employee name with salutation."""
        self.ensure_one()
        emp = self.sudo().employee_id
        emp_name = emp.name if emp else _('Employee')
        salutation = self.get_salutation_label()
        return f"{salutation} {emp_name}"

    def get_salutation_title_and_first_name(self):
        """Returns formal salutation and first name for letter opening."""
        self.ensure_one()
        emp = self.sudo().employee_id
        emp_name = emp.name if emp else _('Employee')
        salutation = self.get_salutation_label()
        first_name = emp_name.split()[0] if emp_name else _('Employee')
        return f"{salutation} {first_name}"

    def get_sanction_display_text(self):
        """Returns clean human-readable sanction and financial penalty description."""
        self.ensure_one()
        sanction_name = dict(self._fields['punishment_type'].selection).get(
            self.punishment_type, str(self.punishment_type or '')
        )
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(f"{self.penalty_percentage}% monthly basic salary deduction")
        if self.fine_days > 0.0:
            penalty_details.append(f"{int(self.fine_days)} day(s) salary fine")

        if penalty_details:
            return f"{sanction_name} with {' and '.join(penalty_details)}"
        return sanction_name

    def get_signatory_name(self):
        """Returns the formal signatory name based on action track and appeal lifecycle."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            return decided_appeals[0].reviewer_id.name or self.approver_id.name or self.env.user.name
        if self.case_action_track == 'direct_enforce':
            return self.initiator_id.name or self.reported_by_id.name or self.approver_id.name or self.env.user.name
        return self.approver_id.name or self.env.user.name

    @api.model
    def _localize_job_position_amharic(self, job_name):
        """Translates or formats bank job positions into natural Amharic professional titles."""
        if not job_name:
            return ""
        name = str(job_name).strip()
        replacements = [
            (r'\b(Chief Executive Officer(\s*\([A-Za-z]+\))?|CEO)\b', 'ዋና ሥራ አስፈፃሚ (CEO)'),
            (r'\b(Chief People\s*(&|and)\s*Culture Officer(\s*\([A-Za-z]+\))?|CPCO)\b', 'የሰው እና ባህል ዋና መኮንን (CPCO)'),
            (r'\bActing Senior Director\s*-\s*', 'ተጠባባቂ ሲኒየር ዳይሬክተር '),
            (r'\bActing Director\s*II\s*-\s*', 'ተጠባባቂ ዳይሬክተር '),
            (r'\bActing Director\s*I\s*-\s*', 'ተጠባባቂ ዳይሬክተር '),
            (r'\bActing Director\s*-\s*', 'ተጠባባቂ ዳይሬክተር '),
            (r'\bActing Director\b', 'ተጠባባቂ ዳይሬክተር'),
            (r'\bDirector\s*II\s*-\s*', 'ዳይሬክተር '),
            (r'\bDirector\s*I\s*-\s*', 'ዳይሬክተር '),
            (r'\bDirector\s*-\s*', 'ዳይሬክተር '),
            (r'\bDirector\b', 'ዳይሬክተር'),
            (r'\bDessie District Office\b', 'ደሴ ዲስትሪክት'),
            (r'\bDessie District\b', 'ደሴ ዲስትሪክት'),
            (r'\bBahir Dar District Office\b', 'ባህር ዳር ዲስትሪክት'),
            (r'\bBahir Dar District\b', 'ባህር ዳር ዲስትሪክት'),
            (r'\bHawassa District Office\b', 'ሐዋሳ ዲስትሪክት'),
            (r'\bHawassa District\b', 'ሐዋሳ ዲስትሪክት'),
            (r'\bDire Dawa District Office\b', 'ድሬዳዋ ዲስትሪክት'),
            (r'\bDire Dawa District\b', 'ድሬዳዋ ዲስትሪክት'),
            (r'\bAdama District Office\b', 'አዳማ ዲስትሪክት'),
            (r'\bAdama District\b', 'አዳማ ዲስትሪክት'),
            (r'\bJimma District Office\b', 'ጅማ ዲስትሪክት'),
            (r'\bJimma District\b', 'ጅማ ዲስትሪክት'),
            (r'\bMekelle District Office\b', 'መቀሌ ዲስትሪክት'),
            (r'\bMekelle District\b', 'መቀሌ ዲስትሪክት'),
            (r'\bEnterprise Application Development and Operation Directorate\b', 'ኢንተርፕራይዝ አፕሊኬሽን ልማት እና ኦፕሬሽን ዳይሬክቶሬት'),
            (r'\bCorporate Planning and Change Management Directorate\b', 'ኮርፖሬት ፕላኒንግ እና ለውጥ አመራር ዳይሬክቶሬት'),
            (r'\bDigital Banking Application Directorate\b', 'ዲጂታል ባንኪንግ አፕሊኬሽን ዳይሬክቶሬት'),
            (r'\bDomestic Banking Operation Directorate\b', 'የሀገር ውስጥ የባንክ ሥራዎች ዳይሬክቶሬት'),
            (r'\bHuman Resource Management Directorate\b', 'የሰው ኃይል አስተዳደር ዳይሬክቶሬት'),
            (r'\bInfrastructure And Security Directorate\b', 'ኢንፍራስትራክቸር እና ደህንነት ዳይሬክቶሬት'),
            (r'\bInternational Banking Directorate\b', 'አለም አቀፍ የባንክ አገልግሎት ዳይሬክቶሬት'),
            (r'\bProperty and Facilities Management Directorate\b', 'የንብረት እና ፋሲሊቲ አስተዳደር ዳይሬክቶሬት'),
            (r'\bAudit Directorate\b', 'ኦዲት ዳይሬክቶሬት'),
            (r'\bRisk Management and Compliance Directorate\b', 'ስጋት አመራር እና ተገዢነት ዳይሬክቶሬት'),
            (r'\bBranch Banking & Quality Assurance Directorate\b', 'የቅርንጫፍ ባንኪንግ እና ጥራት ማረጋገጫ ዳይሬክቶሬት'),
            (r'\bBranch Banking and Quality Assurance Directorate\b', 'የቅርንጫፍ ባንኪንግ እና ጥራት ማረጋገጫ ዳይሬክቶሬት'),
            (r'\bBusiness Customers Relationship Directorate\b', 'የንግድ ደንበኞች ግንኙነት ዳይሬክቶሬት'),
            (r'\bCore Application Directorate\b', 'ኮር አፕሊኬሽን ዳይሬክቶሬት'),
            (r'\bDirectorate\b', 'ዳይሬክቶሬት'),
            (r'\bDistrict\b', 'ዲስትሪክት'),
            (r'\bDepartment\b', 'መምሪያ'),
            (r'\bDivision\b', 'ክፍል'),
            (r'\bBranch\b', 'ቅርንጫፍ'),
            (r'\bManager\b', 'ሥራ አስኪያጅ'),
            (r'\bOfficer\b', 'ኦፊሰር'),
            (r'\bSupervisor\b', 'ተቆጣጣሪ'),
        ]
        for pattern, repl in replacements:
            name = re.sub(pattern, repl, name, flags=re.IGNORECASE)
        name = re.sub(r'ዋና ሥራ አስፈ[ፃጻ]ሚ\s*\(\s*ዋና ሥራ አስፈ[ፃጻ]ሚ\s*\(CEO\)\s*\)', 'ዋና ሥራ አስፈፃሚ (CEO)', name)
        name = re.sub(r'የሰው እና ባህል ዋና መኮንን\s*\(\s*የሰው እና ባህል ዋና መኮንን\s*\(CPCO\)\s*\)', 'የሰው እና ባህል ዋና መኮንን (CPCO)', name)
        name = re.sub(r'\s+', ' ', name).strip()
        return name

    def get_signatory_title(self):
        """Returns formal signatory job / authority title based on action track and appeal lifecycle."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            reviewer = last_app.reviewer_id or last_app.designated_reviewer_id
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', reviewer.id)], limit=1) if reviewer else False
            if emp and emp.job_id and emp.job_id.name:
                return emp.job_id.name
            if last_app.appeal_target_authority == 'ceo' or (reviewer and reviewer.has_group('discipline_management.group_discipline_ceo')):
                return _("Chief Executive Officer (CEO)")
            elif last_app.appeal_target_authority == 'chief' or (reviewer and (reviewer.has_group('discipline_management.group_discipline_cpco') or reviewer.has_group('discipline_management.group_discipline_chief'))):
                return _("Chief People & Culture Officer (CPCO)")
            elif last_app.appeal_target_authority == 'directorate' or (reviewer and reviewer.has_group('discipline_management.group_discipline_director')):
                return _("Director")
            elif last_app.appeal_target_authority == 'secretary' or (reviewer and reviewer.has_group('discipline_management.group_discipline_pomd')):
                return _("POMD / Disciplinary Authority")
            return _("Designated Appeal Authority")

        if self.case_action_track == 'direct_enforce':
            return _("Line Manager / Direct Coach")
        if self.approver_id and hasattr(self.approver_id, 'has_group') and self.approver_id.has_group('discipline_management.group_discipline_ceo'):
            return _("Chief Executive Officer")
        return _("Chief People & Culture Officer / Authorized Executive")

    def get_decision_authority_narrative(self):
        """Returns formal narrative of the deciding authority for the official notice body."""
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            rev_name = last_app.reviewer_id.name or _("the Appeal Authority")
            title = self.get_signatory_title()
            if last_app.decision_outcome == 'penalty_reduced':
                return _("following executive appeal review by %s (%s), the Bank has resolved to reduce and enforce a revised measure of") % (rev_name, title)
            elif last_app.decision_outcome == 'upheld':
                return _("following executive appeal review by %s (%s), the Bank has upheld the disciplinary finding and enforced a measure of") % (rev_name, title)
            return _("following executive appeal review by %s (%s), the Bank has resolved to enforce a measure of") % (rev_name, title)

        if self.case_action_track == 'direct_enforce':
            return _("your reporting coach / line management has enforced a")
        return _("the Disciplinary Authority has resolved to enforce a")

    def is_appeal_final_and_exhausted(self):
        """Returns True if all appeal levels are concluded or appeal window is definitively closed."""
        self.ensure_one()
        if any(a.appeal_level == 'third' and a.state == 'decided' for a in self.appeal_ids):
            return True
        if self.initiator_type in ('chief', 'committee') and any(a.state == 'decided' for a in self.appeal_ids):
            return True
        if self.initiator_type == 'director' and any(a.appeal_level == 'second' and a.state == 'decided' for a in self.appeal_ids):
            return True
        if not self.is_appeal_window_open and any(a.state == 'decided' for a in self.appeal_ids):
            return True
        return False

    def get_payroll_month_display(self):
        """Returns clean formatted payroll month name (e.g. 'October 2026' or 'October')."""
        self.ensure_one()
        if not self.payroll_month:
            return ''
        month_dict = dict(self._fields['payroll_month'].selection) if 'payroll_month' in self._fields else {}
        month_name = month_dict.get(self.payroll_month, str(self.payroll_month))
        year = self.final_decision_date.year if self.final_decision_date else (self.incident_date.year if self.incident_date else fields.Date.today().year)
        return f"{month_name} {year}"

    def get_ethiopian_date_short(self, g_date=None):
        """Returns short Ethiopian calendar date string e.g. '28/02/2019 ዓ.ም.'."""
        self.ensure_one()
        d = g_date or self.final_decision_date or self.incident_date or fields.Date.today()
        short_d, _, _ = gregorian_to_ethiopian(d)
        return short_d

    def get_ethiopian_date_long(self, g_date=None):
        """Returns full long Ethiopian calendar date string e.g. 'ጥቅምት 28 ቀን 2019 ዓ.ም.'."""
        self.ensure_one()
        d = g_date or self.final_decision_date or self.incident_date or fields.Date.today()
        _, long_d, _ = gregorian_to_ethiopian(d)
        return long_d

    def get_ethiopian_payroll_month(self):
        """Returns localized Ethiopian payroll deduction month name e.g. 'ኅዳር 2019 ዓ.ም. (November 2026)'."""
        self.ensure_one()
        if not self.payroll_month:
            return ''
        amharic_months = {
            '1': ('ጥር', 'January'), '2': ('የካቲት', 'February'), '3': ('መጋቢት', 'March'), '4': ('ሚያዝያ', 'April'),
            '5': ('ግንቦት', 'May'), '6': ('ሰኔ', 'June'), '7': ('ሐምሌ', 'July'), '8': ('ነሐሴ', 'August'),
            '9': ('መስከረም', 'September'), '10': ('ጥቅምት', 'October'), '11': ('ኅዳር', 'November'), '12': ('ታኅሣሥ', 'December'),
            'january': ('ጥር', 'January'), 'february': ('የካቲት', 'February'), 'march': ('መጋቢት', 'March'),
            'april': ('ሚያዝያ', 'April'), 'may': ('ግንቦት', 'May'), 'june': ('ሰኔ', 'June'),
            'july': ('ሐምሌ', 'July'), 'august': ('ነሐሴ', 'August'), 'september': ('መስከረም', 'September'),
            'october': ('ጥቅምት', 'October'), 'november': ('ኅዳር', 'November'), 'december': ('ታኅሣሥ', 'December'),
        }
        val = str(self.payroll_month).strip().lower()
        pair = amharic_months.get(val, ('', str(self.payroll_month)))
        year = self.final_decision_date.year if self.final_decision_date else (self.incident_date.year if self.incident_date else fields.Date.today().year)
        ey = year - 7
        if pair[0]:
            return f"{pair[0]} {ey} ዓ.ም. ({pair[1]} {year})"
        return f"{pair[1]} {year}"

    def _get_coach_of_coach(self):
        """Finds the executive authority directly above the line manager (e.g. Directorate Director)."""
        self.ensure_one()
        emp = self.employee_id.sudo() if self.employee_id else False
        direct_coach = emp.coach_id if emp and emp.coach_id else (emp.parent_id if emp else False)
        if direct_coach:
            coach_of_coach = direct_coach.coach_id or direct_coach.parent_id
            if coach_of_coach and coach_of_coach != direct_coach:
                return coach_of_coach
            chain = direct_coach.get_supervisor_chain() if hasattr(direct_coach, 'get_supervisor_chain') else []
            for superior in chain:
                if superior and superior != direct_coach:
                    return superior
        # Fallback to department director / manager if different from direct coach
        if emp and emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id != direct_coach:
            return emp.department_id.manager_id
        return False

    def get_prior_active_cases_details_amharic(self):
        """Returns list of active prior penalties on the employee's record for progressive escalation citations."""
        self.ensure_one()
        inc_date = self.incident_date or fields.Date.context_today(self)
        emp = self.employee_id.sudo() if self.employee_id else False
        all_prior = self.env['discipline.case'].sudo().search([
            ('employee_id', '=', emp.id),
            ('id', '!=', self._origin.id if self._origin else (self.id or 0)),
            ('state', 'in', ['enforced', 'closed', 'appealed']),
        ]) if emp else self.env['discipline.case']

        prior_cases = all_prior.filtered(
            lambda c: (c.active_penalty_end_date and c.active_penalty_end_date >= inc_date) or
                      (not c.active_penalty_end_date and (c.final_decision_date or c.incident_date) and 
                       ((c.final_decision_date or c.incident_date) + timedelta(days=c.active_duration_days or 365)) >= inc_date)
        )

        results = []
        amharic_punish_map = {
            'verbal_warning': 'የቃል ማስጠንቀቂያ',
            'first_warning_penalty': 'የመጀመሪያ የጽሑፍ ማስጠንቀቂያ',
            'second_warning_penalty': 'የሁለተኛ የጽሑፍ ማስጠንቀቂያ',
            'final_warning_penalty': 'የመጨረሻ የጽሑፍ ማስጠንቀቂያ',
            'demotion': 'የሥራ መደብ እና ደረጃ ዝቅጠት',
            'dismissal': 'ከሥራ ማሰናበት',
        }
        for pc in prior_cases.sorted('final_decision_date'):
            p_name = amharic_punish_map.get(pc.punishment_type, str(pc.punishment_type or 'የዲሲፕሊን ቅጣት'))
            if pc.penalty_percentage > 0:
                p_name += f" ከ {pc.penalty_percentage}% ቅጣት ጋር"
            elif pc.fine_days > 0:
                p_name += f" ከ {int(pc.fine_days)} ቀን ቅጣት ጋር"
            dec_date = pc.final_decision_date or pc.incident_date
            short_eth, _, _ = gregorian_to_ethiopian(dec_date)
            results.append({
                'name': pc.name,
                'punishment': p_name,
                'date': short_eth,
            })
        return results

    def get_signatory_company(self):
        return _("Bunna Bank S.C.")

    @api.model
    def _clean_stamp_image_data(self, b64_stamp):
        """Processes a stamp image to remove opaque scan background and make it appear authentically stamped on paper."""
        if not b64_stamp:
            return ""
        try:
            raw_bytes = base64.b64decode(b64_stamp)
            im = Image.open(io.BytesIO(raw_bytes)).convert('RGBA')
            cleaned = Image.new('RGBA', im.size, (0, 0, 0, 0))
            pixels = im.load()
            out = cleaned.load()

            needs_clean = False
            for y in range(0, im.height, 4):
                for x in range(0, im.width, 4):
                    r, g, b, a = pixels[x, y]
                    if a > 0 and 170 <= (r * 299 + g * 587 + b * 114) / 1000 <= 220:
                        needs_clean = True
                        break
                if needs_clean:
                    break

            if not needs_clean:
                return b64_stamp if isinstance(b64_stamp, str) else b64_stamp.decode('utf-8')

            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, a = pixels[x, y]
                    if a == 0:
                        continue
                    brightness = (r * 299 + g * 587 + b * 114) / 1000
                    if brightness >= 178:
                        continue
                    elif brightness <= 135:
                        out[x, y] = (r, g, b, 245)
                    else:
                        alpha = int(245 * (178 - brightness) / (178 - 135))
                        out[x, y] = (r, g, b, alpha)
            buf = io.BytesIO()
            cleaned.save(buf, format='PNG')
            return base64.b64encode(buf.getvalue()).decode('utf-8')
        except Exception:
            return b64_stamp if isinstance(b64_stamp, str) else b64_stamp.decode('utf-8')

    def get_official_bank_stamp_image(self):
        """Returns base64 string of the official Bunna Bank circular seal stamp."""
        self.ensure_one()
        # 1. First check company configuration (uploaded once in Settings)
        company = self.company_id or self.env.company
        stamp = False
        if company and hasattr(company, 'discipline_bank_stamp') and company.discipline_bank_stamp:
            stamp = company.discipline_bank_stamp
        elif self.bank_stamp:
            stamp = self.bank_stamp

        if stamp:
            b64_str = stamp.decode('utf-8') if isinstance(stamp, bytes) else stamp
            return self._clean_stamp_image_data(b64_str)

        # Check static clean stamp
        stamp_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_signature_stamp_clean.png')
        )
        if os.path.exists(stamp_path):
            with open(stamp_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_signatory_signature_image(self):
        """Returns base64 string of the authorized signatory digital signature.
        For appeal decision notices, strictly uses the appeal decider's signature.
        """
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            # 1. Check if appeal record itself has a specific reviewer signature
            if hasattr(last_app, 'reviewer_signature') and last_app.reviewer_signature:
                sig = last_app.reviewer_signature
                return sig.decode('utf-8') if isinstance(sig, bytes) else sig

            # 2. Check the appeal reviewer user / employee profile
            signatory_user = last_app.reviewer_id or last_app.designated_reviewer_id
            if signatory_user:
                emp = self.env['hr.employee'].sudo().search([('user_id', '=', signatory_user.id)], limit=1)
                for target in [emp, signatory_user]:
                    if not target:
                        continue
                    for fld in ['discipline_digital_signature', 'digital_signature', 'signature', 'sign_signature']:
                        val = getattr(target, fld, False)
                        if val:
                            return val.decode('utf-8') if isinstance(val, bytes) else val

            # 3. Check if reviewer signed any other case
            if signatory_user:
                prev_case = self.env['discipline.case'].sudo().search([
                    ('signatory_signature', '!=', False),
                    '|', ('initiator_id', '=', signatory_user.id), ('create_uid', '=', signatory_user.id)
                ], order='id desc', limit=1)
                if prev_case and prev_case.signatory_signature:
                    val = prev_case.signatory_signature
                    return val.decode('utf-8') if isinstance(val, bytes) else val

            # Never use the initial coach's signature for an appeal decision notice
            return ""

        # Non-appeal initial notice: Use direct coach / enforcing manager signature
        if self.signatory_signature:
            return self.signatory_signature.decode('utf-8') if isinstance(self.signatory_signature, bytes) else self.signatory_signature

        # Locate signatory user / employee
        signatory_user = False
        if self.case_action_track == 'direct_enforce':
            signatory_user = self.initiator_id or (self.reported_by_id and self.reported_by_id.user_id) or self.approver_id
        else:
            signatory_user = self.approver_id

        if signatory_user:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', signatory_user.id)], limit=1)
            for target in [emp, signatory_user]:
                if not target:
                    continue
                for fld in ['discipline_digital_signature', 'digital_signature', 'signature', 'sign_signature']:
                    val = getattr(target, fld, False)
                    if val:
                        return val.decode('utf-8') if isinstance(val, bytes) else val

        return ""

    def get_salutation_label_amharic(self):
        self.ensure_one()
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'አቶ'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            return 'ወ/ሪት' if marital == 'single' else 'ወ/ሮ'
        return 'አቶ / ወ/ሮ'

    def get_formatted_employee_name_amharic(self):
        self.ensure_one()
        salut = self.get_salutation_label_amharic()
        emp_name = (self.employee_name_amharic or '').strip()
        if not emp_name:
            emp = self.sudo().employee_id
            emp_name = (getattr(emp, 'name_amharic', False) or (emp.name if emp else '')).strip()
        if emp_name.startswith(('አቶ ', 'ወ/ሮ ', 'ወ/ሪት ', 'ዶ/ር ')):
            return emp_name
        return f"{salut} {emp_name}" if emp_name else salut

    def get_sanction_display_text_amharic(self):
        self.ensure_one()
        amharic_punish_map = {
            'verbal_warning': 'የቃል ማስጠንቀቂያ',
            'first_warning_penalty': 'የመጀመሪያ የጽሑፍ ማስጠንቀቂያ',
            'second_warning_penalty': 'የሁለተኛ የጽሑፍ ማስጠንቀቂያ',
            'final_warning_penalty': 'የመጨረሻ የጽሑፍ ማስጠንቀቂያ',
            'demotion': 'የሥራ መደብ እና የደመወዝ ቅነሳ (ደረጃ ዝቅጠት)',
            'dismissal': 'ያለ ምንም ቅድመ ማስጠንቀቂያ ከሥራ ማሰናበት',
            'exonerate': 'ከቀረበበት ክስ ሙሉ በሙሉ ነፃ መሆን',
        }
        sanction_name = amharic_punish_map.get(self.punishment_type, str(self.punishment_type or ''))
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(f"{self.penalty_percentage}% ወርሃዊ ደመወዝ ቅጣት")
        if self.fine_days > 0.0:
            penalty_details.append(f"{int(self.fine_days)} ቀን የደመወዝ ቅጣት")

        if penalty_details:
            return f"{sanction_name} ከ {' እና '.join(penalty_details)} ጋር"
        return sanction_name

    def get_signatory_title_amharic(self):
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            reviewer_user = last_app.reviewer_id or last_app.designated_reviewer_id
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', reviewer_user.id)], limit=1) if reviewer_user else False
            if emp and emp.job_id and emp.job_id.name:
                localized = self._localize_job_position_amharic(emp.job_id.name)
                if localized:
                    return localized

            if last_app.appeal_target_authority == 'ceo':
                return 'ዋና ሥራ አስፈፃሚ (CEO)'
            elif last_app.appeal_target_authority == 'chief':
                return 'የሰው እና ባህል ዋና መኮንን (CPCO)'
            elif last_app.appeal_target_authority == 'directorate':
                return 'ዳይሬክተር'
            return 'የይግባኝ ውሳኔ ሰጪ አካል'

        if self.case_action_track == 'direct_enforce':
            return 'የቅርብ ኃላፊ / ተቆጣጣሪ'
        if self.approver_id and hasattr(self.approver_id, 'has_group') and self.approver_id.has_group('discipline_management.group_discipline_ceo'):
            return 'ዋና ሥራ አስፈፃሚ'
        return 'የሰው እና ባህል ዋና መኮንን (CPCO) / የዲሲፕሊን ኮሚቴ ሰብሳቢ'

    def get_decision_authority_narrative_amharic(self):
        self.ensure_one()
        decided_appeals = self.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
            lambda a: (a.review_date or fields.Date.today(), a.id or 0), reverse=True
        )
        if decided_appeals:
            last_app = decided_appeals[0]
            rev_name = last_app.reviewer_id.name or 'የይግባኝ ሰሚው አካል'
            title = self.get_signatory_title_amharic()
            if last_app.decision_outcome == 'penalty_reduced':
                return f"በ{rev_name} ({title}) የተካሄደውን የይግባኝ ግምገማ ተከትሎ ባንኩ ቅጣቱን በማሻሻል"
            elif last_app.decision_outcome == 'upheld':
                return f"በ{rev_name} ({title}) የተካሄደውን የይግባኝ ግምገማ ተከትሎ ባንኩ ውሳኔውን በማጽናት"
            return f"በ{rev_name} ({title}) የተካሄደውን የይግባኝ ግምገማ ተከትሎ ባንኩ"

        if self.case_action_track == 'direct_enforce':
            return 'የቅርብ ኃላፊዎ / ተቆጣጣሪዎ'
        return 'የባንኩ የበላይ ማኔጅመንት እና የዲሲፕሊን ኮሚቴ በወሰነው መሰረት'

    def get_discipline_letter_cc_lines_amharic(self):
        self.ensure_one()
        lines = [
            'ለሰው ኃይል ኦፕሬሽንስ አስተዳደር ዳይሬክቶሬት (POMD) - ለግል ማህደር',
        ]
        coach_of_coach = self._get_coach_of_coach()
        if coach_of_coach:
            job_title = coach_of_coach.job_id.name if coach_of_coach.job_id else 'ዳይሬክተር'
            lines.append(f'ለ{coach_of_coach.name} ({job_title})')
        elif self.department_id:
            dept_name = self.department_id.name
            if 'Head Office' in dept_name or dept_name == 'Head Office':
                dept_name = 'ዋናው መ/ቤት'
            lines.append(f'ለ{dept_name} / ለሚመለከተው ዳይሬክቶሬት')

        # Only add Internal Audit for committee / escalated cases, never for direct enforcement
        if self.case_action_track != 'direct_enforce':
            lines.append('ለውስጥ ኦዲት ዳይሬክቶሬት')

        return lines

    def get_discipline_letter_cc_lines(self):
        """Returns formatted CC distribution lines for the official letter."""
        self.ensure_one()
        lines = [
            _("People Operations Management Directorate (POMD) - Personnel File"),
        ]
        coach_of_coach = self._get_coach_of_coach()
        if coach_of_coach:
            job_title = coach_of_coach.job_id.name if coach_of_coach.job_id else 'Director'
            lines.append(f"{coach_of_coach.name} ({job_title})")
        elif self.department_id:
            lines.append(f"{self.department_id.name} / Respective Directorate")
        else:
            lines.append(_("Respective Directorate / Branch Management"))

        # Only add Internal Audit for committee / escalated cases
        if self.case_action_track != 'direct_enforce':
            lines.append(_("Internal Audit Directorate"))

        return lines

    @api.model
    def get_discipline_analytics_payload(self, date_from=None, date_to=None):
        """Public API method returning aggregated disciplinary statistics for external HR Analytics integration."""
        domain = []
        if date_from:
            domain.append(('incident_date', '>=', date_from))
        if date_to:
            domain.append(('incident_date', '<=', date_to))

        cases = self.search(domain)
        by_state, by_severity, by_department, by_punishment = {}, {}, {}, {}

        for c in cases:
            st = c.state or 'unknown'
            by_state[st] = by_state.get(st, 0) + 1
            sev = c.severity_level or 'unclassified'
            by_severity[sev] = by_severity.get(sev, 0) + 1
            dept = c.department_id.name if c.department_id else 'Unassigned'
            by_department[dept] = by_department.get(dept, 0) + 1
            pish = c.punishment_type or 'none'
            by_punishment[pish] = by_punishment.get(pish, 0) + 1

        return {
            'total_cases': len(cases),
            'cases_by_state': by_state,
            'cases_by_severity': by_severity,
            'cases_by_department': by_department,
            'cases_by_punishment': by_punishment,
        }


class ReportSuspensionLetter(models.AbstractModel):
    _name = 'report.discipline_management.report_suspension_letter_template'
    _description = 'Official Suspension Letter Report'
    _table = 'report_disc_susp_letter'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.suspension'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.suspension',
            'docs': docs,
        }


class ReportDisciplinaryWarningLetter(models.AbstractModel):
    _name = 'report.discipline_management.report_disciplinary_warning_letter_template'
    _description = 'Disciplinary Warning Letter Report'
    _table = 'report_disc_warn_letter'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.case'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.case',
            'docs': docs,
        }


class ReportExonerationCertificate(models.AbstractModel):
    _name = 'report.discipline_management.report_exoneration_certificate_template'
    _description = 'Official Exoneration Certificate Report'
    _table = 'report_disc_exon_cert'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.case'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.case',
            'docs': docs,
        }


class ReportCommitteeResolution(models.AbstractModel):
    _name = 'report.discipline_management.report_committee_resolution_template'
    _description = 'Disciplinary Committee Hearing Minutes & Resolution Report'
    _table = 'report_disc_comm_res'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['discipline.committee.meeting'].sudo().browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'discipline.committee.meeting',
            'docs': docs,
        }


