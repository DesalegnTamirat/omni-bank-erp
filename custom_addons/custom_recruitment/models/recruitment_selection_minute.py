import os
import re
import base64
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError, AccessError

_logger = logging.getLogger(__name__)

def gregorian_to_ethiopian(g_date):
    """Converts a Gregorian date/datetime or date string to Ethiopian Calendar string."""
    if not g_date:
        return ""
    import datetime
    if isinstance(g_date, str):
        try:
            g_date = datetime.datetime.strptime(g_date[:10], "%Y-%m-%d").date()
        except Exception:
            return str(g_date)
    elif isinstance(g_date, datetime.datetime):
        g_date = g_date.date()

    eth_months = [
        "", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት",
        "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"
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
    if not amount or amount <= 0:
        return ""

    units = ["", "አንድ", "ሁለት", "ሦስት", "አራት", "አምስት", "ስድስት", "ሰባት", "ስምንት", "ዘጠኝ"]
    teens = [
        "አስር", "አስራ አንድ", "አስራ ሁለት", "አስራ ሦስት", "አስራ አራት",
        "አስራ አምስት", "አስራ ስድስት", "አስራ ሰባት", "አስራ ስምንት", "አስራ ዘጠኝ"
    ]
    tens = ["", "አስር", "ሃያ", "ሰላሳ", "አርባ", "ሃምሳ", "ስድሳ", "ሰባ", "ሰማንያ", "ዘጠና"]

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

class RecruitmentSelectionMinute(models.Model):
    """
    Central selection minute document for both External and Internal Recruitment.
    Tracks candidate matrix, committee review signatures, auto-approval, and PDF generation.
    """
    _name = "recruitment.selection.minute"
    _description = "Recruitment Committee Selection Minute"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "meeting_date desc, id desc"

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
        string="Minute Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    vacancy_id = fields.Many2one(
        "job.vacancy",
        string="Target Vacancy",
        required=True,
        tracking=True,
    )
    recruitment_type = fields.Selection(
        [
            ("internal", "Internal Recruitment"),
            ("external", "External Recruitment"),
        ],
        string="Recruitment Type",
        compute="_compute_recruitment_type",
        store=True,
        readonly=True,
        default="internal",
        required=True,
    )

    @api.depends("vacancy_id", "vacancy_id.recruitment_type", "vacancy_id.sourcing_type", "vacancy_id.reference")
    def _compute_recruitment_type(self):
        for rec in self:
            vac = rec.vacancy_id
            if vac:
                r_type = str(vac.recruitment_type or '').lower()
                s_type = str(vac.sourcing_type or '').lower()
                ref = str(vac.reference or '').upper()
                if 'ext' in r_type or 'ext' in s_type or 'EXT' in ref:
                    rec.recruitment_type = 'external'
                    continue
            rec.recruitment_type = 'internal' 

    approval_hierarchy_type = fields.Selection(
        [
            ("ho_district_grade2_plus", "Head Office & District Grade II and above"),
            ("non_managerial_ho", "For all non-managerial head office"),
            ("non_managerial_district", "For all non-managerial district"),
        ],
        string="Approval Hierarchy Category",
        compute="_compute_hierarchy_type",
        store=True,
        readonly=False,
        tracking=True,
    )

    chairperson_id = fields.Many2one("res.users", string="Chairperson", tracking=True)
    panel_member_id = fields.Many2one("res.users", string="Panel Member", tracking=True)
    secretary_id = fields.Many2one("res.users", string="Panel Member & Secretary", tracking=True)
    observer_id = fields.Many2one(
        "res.users", string="Labor Representative (Observer)", tracking=True,
        help="Observer role (optional to sign)"
    )
    allowed_chairperson_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Chairperson Users",
    )
    allowed_panel_member_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Panel Member Users",
    )
    allowed_secretary_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Secretary Users",
    )
    allowed_observer_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_committee_users",
        string="Allowed Observer Users",
    )

    @api.depends("vacancy_id", "vacancy_id.operating_unit_id", "vacancy_id.employee_category", "vacancy_id.job_grade", "vacancy_id.job_position")
    def _compute_hierarchy_type(self):
        for rec in self:
            if not rec.vacancy_id:
                rec.approval_hierarchy_type = "ho_district_grade2_plus"
                continue

            vac = rec.vacancy_id
            grade = vac.job_grade or (vac.job_position.grade if vac.job_position else False)
            op_unit = vac.operating_unit_id
            category = vac.employee_category or ""

            # Check if grade is Grade II or above, or Managerial category
            grade_name = str(getattr(grade, "grade_name", "") or getattr(grade, "name", "") or "").lower()
            grade_level = str(getattr(grade, "grade_level", "") or "").lower()

            is_grade_2_plus_or_manager = (
                "managerial" in str(category).lower()
                or "grade 2" in grade_name or "grade ii" in grade_name
                or "grade 3" in grade_name or "grade iii" in grade_name
                or "grade 4" in grade_name or "grade iv" in grade_name
                or "grade 5" in grade_name or "grade v" in grade_name
                or "senior" in grade_level or "managerial" in grade_level
            )

            # Determine whether hiring workunit is Head Office or District
            is_head_office = False
            if op_unit:
                w_type = (op_unit.work_unit_type or "").lower()
                u_name = (op_unit.name or "").lower()
                if w_type == "head_office":
                    is_head_office = True
                elif w_type in ("district_office", "branch", "sub_branch"):
                    is_head_office = False
                elif op_unit.parent_unit and (op_unit.parent_unit.work_unit_type or "").lower() == "head_office":
                    is_head_office = True
                elif any(k in u_name for k in ["head office", "head", "directorate", "chief", "department"]):
                    is_head_office = True
                elif any(k in u_name for k in ["district", "branch"]):
                    is_head_office = False
                else:
                    is_head_office = True
            else:
                is_head_office = True

            if is_grade_2_plus_or_manager:
                rec.approval_hierarchy_type = "ho_district_grade2_plus"
            elif is_head_office:
                rec.approval_hierarchy_type = "non_managerial_ho"
            else:
                rec.approval_hierarchy_type = "non_managerial_district"

    meeting_date = fields.Date(
        string="Meeting Date",
        default=fields.Date.context_today,
        required=True,
    )

    meeting_place = fields.Char(
        string="Meeting Place",
        default="ፒፕል ኦፕሬሽን ማኔጅመንት ዳይሬክቶሬት ቢሮ",
    )
    meeting_time = fields.Char(
        string="Meeting Time",
        default="ከጠዋቱ በ3፡00 ሰዓት",
    )
    meeting_end_time = fields.Char(
        string="Meeting End Time",
        default="ከቀኑ በ 6፡00 ሰዓት",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_approval", "Pending Committee Approval"),
            ("approved", "Approved & Finalized"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        valid_rec_types = ("internal", "external")
        valid_states = ("draft", "pending_approval", "approved", "rejected")
        for r in res:
            if "recruitment_type" in r and r["recruitment_type"] not in valid_rec_types:
                r["recruitment_type"] = "internal"
            if "state" in r and r["state"] not in valid_states:
                r["state"] = "draft"
        return res

    ranking_line_ids = fields.One2many(
        "recruitment.selection.minute.line",
        "minute_id",
        string="Ranked Candidates",
        copy=True,
    )
    committee_signature_ids = fields.One2many(
        "recruitment.committee.signature",
        "minute_id",
        string="Committee Signatures",
    )

    decision_summary = fields.Text(
        string="Committee Decision & Selection Justification",
        required=True,
        help="Formal narrative explaining candidate selection, reserve pool, and rejection reasons.",
    )
    is_fully_signed = fields.Boolean(
        string="Fully Signed", compute="_compute_signature_status", store=True
    )
    panel_notified = fields.Boolean(
        string="Panel Notified", default=False
    )
    current_user_can_sign = fields.Boolean(
        string="Current User Can Sign", compute="_compute_current_user_can_sign", store=False
    )
    active = fields.Boolean(default=True)

    def _compute_current_user_can_sign(self):
        for rec in self:
            can_sign = False
            if rec.state in ('draft', 'pending_approval') and rec.committee_signature_ids:
                my_line = rec.committee_signature_ids.filtered(
                    lambda s: s.user_id == self.env.user and s.state == 'pending'
                )
                can_sign = bool(my_line)
            rec.current_user_can_sign = can_sign

    def action_sign_my_minute_line(self):
        self.ensure_one()
        my_line = self.committee_signature_ids.filtered(
            lambda s: s.user_id == self.env.user and s.state == 'pending'
        )
        if not my_line:
            raise UserError(_("You do not have any pending signature assignments on this Committee Minute."))
        return my_line[0].action_sign_digitally()

    def _auto_init(self):
        # 1. Invalidate stable cache so ir_model_fields lookups are never stale
        self.env.registry.clear_cache('stable')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    ALTER TABLE recruitment_selection_minute 
                    ADD COLUMN IF NOT EXISTS approval_hierarchy_type varchar,
                    ADD COLUMN IF NOT EXISTS chairperson_id int4,
                    ADD COLUMN IF NOT EXISTS panel_member_id int4,
                    ADD COLUMN IF NOT EXISTS secretary_id int4,
                    ADD COLUMN IF NOT EXISTS observer_id int4,
                    ADD COLUMN IF NOT EXISTS meeting_place varchar,
                    ADD COLUMN IF NOT EXISTS meeting_time varchar,
                    ADD COLUMN IF NOT EXISTS meeting_end_time varchar;

                    -- Pre-ensure ir_model_fields has approval_hierarchy_type registered
                    DO $$
                    DECLARE
                        m_id INT;
                    BEGIN
                        SELECT id INTO m_id FROM ir_model WHERE model = 'recruitment.selection.minute' LIMIT 1;
                        IF m_id IS NOT NULL THEN
                            INSERT INTO ir_model_fields (model_id, model, name, field_description, ttype, state, readonly, required, store, index, copied)
                            VALUES (m_id, 'recruitment.selection.minute', 'approval_hierarchy_type', '{"en_US": "Approval Hierarchy Category"}'::jsonb, 'selection', 'base', false, false, true, false, true)
                            ON CONFLICT (model, name) DO NOTHING;
                        END IF;

                        SELECT id INTO m_id FROM ir_model WHERE model = 'transfer.committee.minutes' LIMIT 1;
                        IF m_id IS NOT NULL THEN
                            INSERT INTO ir_model_fields (model_id, model, name, field_description, ttype, state, readonly, required, store, index, copied)
                            VALUES (m_id, 'transfer.committee.minutes', 'approval_hierarchy_type', '{"en_US": "Approval Hierarchy Category"}'::jsonb, 'selection', 'base', false, false, true, false, true)
                            ON CONFLICT (model, name) DO NOTHING;
                        END IF;
                    END $$;
                """)
        except Exception as e:
            _logger.warning("Pre-init on recruitment_selection_minute table columns: %s", e)

        res = super()._auto_init()
        self.env.registry.clear_cache('stable')
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    ALTER TABLE recruitment_selection_minute 
                    ADD COLUMN IF NOT EXISTS panel_notified boolean DEFAULT false;

                    UPDATE recruitment_selection_minute 
                    SET recruitment_type = CASE 
                        WHEN LOWER(recruitment_type) LIKE '%ext%' THEN 'external'
                        ELSE 'internal'
                    END
                    WHERE recruitment_type IS NULL OR recruitment_type = '' OR LOWER(recruitment_type) NOT IN ('internal', 'external');

                    -- Sanitize corrupted or unreadable meeting time strings in the database
                    UPDATE recruitment_selection_minute
                    SET meeting_time = 'ከጠዋቱ በ3፡00 ሰዓት'
                    WHERE meeting_time IS NULL
                       OR meeting_time LIKE '%CE%'
                       OR meeting_time LIKE '%ዕለት%'
                       OR meeting_time LIKE '%`%'
                       OR meeting_time ~ '[a-zA-Z]';

                    UPDATE recruitment_selection_minute
                    SET meeting_end_time = 'ከቀኑ በ 6፡00 ሰዓት'
                    WHERE meeting_end_time IS NULL
                       OR meeting_end_time LIKE '%CE%'
                       OR meeting_end_time LIKE '%ዕለት%'
                       OR meeting_end_time LIKE '%`%'
                       OR meeting_end_time ~ '[a-zA-Z]';

                    UPDATE recruitment_selection_minute_line 
                    SET selection_status = CASE
                        WHEN LOWER(selection_status) LIKE '%select%' THEN 'selected'
                        WHEN LOWER(selection_status) LIKE '%reser%' THEN 'reserve'
                        WHEN LOWER(selection_status) LIKE '%fail%' OR LOWER(selection_status) LIKE '%reject%' OR LOWER(selection_status) LIKE '%disqualif%' THEN 'failed'
                        ELSE 'reserve'
                    END
                    WHERE selection_status IS NULL OR selection_status = '';

                    UPDATE recruitment_committee_signature 
                    SET state = LOWER(state)
                    WHERE state IS NOT NULL AND LOWER(state) IN ('pending', 'signed', 'rejected');

                    -- Auto-grant group_recruitment_approval_committee to any user assigned to committee signatures or delegation teams
                    DO $$
                    DECLARE
                        grp_id INT;
                    BEGIN
                        SELECT res_id INTO grp_id FROM ir_model_data WHERE module = 'custom_recruitment' AND name = 'group_recruitment_approval_committee' LIMIT 1;
                        IF grp_id IS NOT NULL THEN
                            INSERT INTO res_groups_users_rel (gid, uid)
                            SELECT DISTINCT grp_id, user_id
                            FROM recruitment_committee_signature
                            WHERE user_id IS NOT NULL
                            ON CONFLICT DO NOTHING;

                            INSERT INTO res_groups_users_rel (gid, uid)
                            SELECT DISTINCT grp_id, employee_name
                            FROM new_recrt_delegation_team
                            WHERE employee_name IS NOT NULL
                            ON CONFLICT DO NOTHING;
                        END IF;

                        -- Remove Interviewer from Recruitment privilege dropdown
                        UPDATE res_groups 
                        SET privilege_id = NULL 
                        WHERE id = (SELECT res_id FROM ir_model_data WHERE module = 'hr_recruitment' AND name = 'group_hr_recruitment_interviewer');

                        -- Clear "No" placeholder for Recruitment privilege
                        UPDATE res_groups_privilege 
                        SET placeholder = '' 
                        WHERE id = (SELECT res_id FROM ir_model_data WHERE module = 'hr_recruitment' AND name = 'res_groups_privilege_recruitment');
                    END $$;
                """)
        except Exception as e:
            _logger.warning("Safe migration on recruitment_selection_minute: %s", e)
        return res

    @api.model
    def _get_fiscal_year_minute_prefix(self):
        """Computes current fiscal-year prefix BB/MIN/YY-YY/ (e.g. BB/MIN/26-27/)."""
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/MIN/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_minute_reference(self):
        """Auto-generates unique Selection Minute reference number (e.g. BB/MIN/26-27/00001)."""
        prefix = self._get_fiscal_year_minute_prefix()
        self.env.cr.execute("""
            SELECT name FROM recruitment_selection_minute
            WHERE name IS NOT NULL AND name != 'New' AND name NOT LIKE 'MIN/%%'
              AND name LIKE %s
            ORDER BY id DESC LIMIT 1
        """, (prefix + '%',))
        res = self.env.cr.fetchone()
        if res and res[0]:
            try:
                seq_num = int(res[0].replace(prefix, '')) + 1
            except ValueError:
                seq_num = 1
        else:
            seq_num = 1
        return f"{prefix}{seq_num:05d}"

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        valid_rec_types = ("internal", "external")
        valid_states = ("draft", "pending_approval", "approved", "rejected")
        for r in res:
            if "recruitment_type" in r and r["recruitment_type"] not in valid_rec_types:
                r["recruitment_type"] = "internal"
            if "state" in r and r["state"] not in valid_states:
                r["state"] = "draft"
            if "name" in r and (not r["name"] or r["name"] in ("New", _("New")) or str(r["name"]).startswith("MIN/")):
                new_ref = self._get_next_minute_reference()
                self.browse(r["id"]).sudo().write({"name": new_ref})
                r["name"] = new_ref

            if r.get("id") and r.get("vacancy_id"):
                rec = self.browse(r["id"])
                if rec.exists() and rec.state != "approved":
                    if not rec.ranking_line_ids:
                        rec.action_load_candidates_from_vacancy()
                    if not rec.committee_signature_ids:
                        rec.action_load_panel_members_from_vacancy()
        return res

    def unlink(self):
        """ Soft delete: archive instead of hard delete for compliance """
        for rec in self:
            if rec.state == "approved":
                raise UserError(_("Approved Selection Minutes cannot be deleted. You may archive them instead."))
            rec.write({"active": False})
        return True

    @api.depends("committee_signature_ids.state", "committee_signature_ids.is_mandatory")
    def _compute_signature_status(self):
        for rec in self:
            if not rec.committee_signature_ids:
                rec.is_fully_signed = False
            else:
                mandatory_sigs = rec.committee_signature_ids.filtered(lambda s: s.is_mandatory)
                if mandatory_sigs:
                    rec.is_fully_signed = all(
                        sig.state == "signed" for sig in mandatory_sigs
                    )
                else:
                    rec.is_fully_signed = all(
                        sig.state == "signed" for sig in rec.committee_signature_ids
                    )

    @api.model
    def check_access_rights(self, operation, raise_exception=True):
        if operation == 'create':
            user = self.env.user
            is_admin_recruitment = (
                user.has_group('custom_recruitment.group_recruitment_administrator')
                or user.has_group('custom_recruitment.group_recruitment_manager')
                or user.has_group('base.group_system')
                or self.env.is_superuser()
            )
            if not is_admin_recruitment:
                if raise_exception:
                    raise AccessError(_("Only recruitment administrators are authorized to create Digital Selection Minutes."))
                return False
        return super().check_access_rights(operation, raise_exception=raise_exception)

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('custom_recruitment.group_recruitment_administrator')
                or self.env.user.has_group('custom_recruitment.group_recruitment_manager')
                or self.env.is_admin() or self.env.su):
            raise AccessError(_("Only recruitment administrators are authorized to create Digital Selection Minutes."))
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") in (_("New"), "New") or str(vals.get("name")).startswith("MIN/"):
                vals["name"] = self._get_next_minute_reference()
            if not self._is_clean_amharic_time(vals.get("meeting_time")):
                vals["meeting_time"] = "ከጠዋቱ በ3፡00 ሰዓት"
            if not self._is_clean_amharic_time(vals.get("meeting_end_time")):
                vals["meeting_end_time"] = "ከቀኑ በ 6፡00 ሰዓት"
            if not self._is_clean_amharic(vals.get("meeting_place")):
                vals["meeting_place"] = "ፒፕል ኦፕሬሽን ማኔጅመንት ዳይሬክቶሬት ቢሮ"
        records = super().create(vals_list)
        for rec in records:
            if rec.vacancy_id:
                if not rec.ranking_line_ids:
                    rec.action_load_candidates_from_vacancy()
                if not rec.committee_signature_ids:
                    rec.action_load_panel_members_from_vacancy()
        return records

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id(self):
        if self.vacancy_id:
            # 1. Load Candidate Scores / Ranking Lines
            scores = self.env["recruitment.candidate.score"].search(
                [("vacancy_id", "=", self.vacancy_id.id), ("disqualified", "=", False)],
                order="rank asc, final_score desc",
            )
            ranking_cmds = [(5, 0, 0)]
            for score in scores:
                ranking_cmds.append(
                    (
                        0,
                        0,
                        {
                            "candidate_score_id": score.id,
                            "applicant_id": score.applicant_id.id
                            if self.recruitment_type == "external"
                            else False,
                            "employee_id": score.employee_id.id
                            if self.recruitment_type == "internal"
                            else False,
                            "candidate_name": score.candidate_name,
                            "pms_score": score.pms_score,
                            "written_score": score.written_score,
                            "interview_score": score.interview_score,
                            "final_score": score.final_score,
                            "rank": score.rank,
                            "selection_status": "selected"
                            if score.rank <= (self.vacancy_id.no_of_vacancies or 1)
                            else "reserve",
                        },
                    )
                )
            self.ranking_line_ids = ranking_cmds

            # 2. Populate signatures ONLY from explicitly configured Approval Committee members
            sig_cmds = [(5, 0, 0)]
            added_user_ids = set()

            int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
                '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
            ], limit=1)

            if int_sel and int_sel.recr_selected_team_id:
                for member in int_sel.recr_selected_team_id:
                    user = member.employee_name or getattr(member, 'alternate_committee_member', False)
                    if user and user.id not in added_user_ids:
                        added_user_ids.add(user.id)
                        role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                        is_mand = False if member.role == 'observer' else True
                        sig_cmds.append((0, 0, {
                            'user_id': user.id,
                            'role': role_label,
                            'role_label': role_label,
                            'is_mandatory': is_mand,
                            'state': 'pending',
                        }))

            if len(sig_cmds) == 1:
                ext_sel = self.env["external.recruitment.selected"].sudo().search([
                    '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
                ], limit=1)
                if ext_sel:
                    ext_team = getattr(ext_sel, 'recr_exter_selected_team_id', False) or getattr(ext_sel, 'recr_selected_team_id', False)
                    if ext_team:
                        for member in ext_team:
                            user = member.employee_name or getattr(member, 'alternate_committee_member', False)
                            if user and user.id not in added_user_ids:
                                added_user_ids.add(user.id)
                                role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                                is_mand = False if member.role == 'observer' else True
                                sig_cmds.append((0, 0, {
                                    'user_id': user.id,
                                    'role': role_label,
                                    'role_label': role_label,
                                    'is_mandatory': is_mand,
                                    'state': 'pending',
                                }))

            if len(sig_cmds) == 1 and self.vacancy_id.vac_del_team_id:
                for del_member in self.vacancy_id.vac_del_team_id:
                    user = del_member.employee_name or getattr(del_member, 'alternate_committee_member', False)
                    if user and user.id not in added_user_ids:
                        added_user_ids.add(user.id)
                        role_label = dict(del_member._fields['role'].selection).get(del_member.role, 'Committee Member') if del_member.role else 'Committee Member'
                        is_mand = False if del_member.role == 'observer' else True
                        sig_cmds.append((0, 0, {
                            'user_id': user.id,
                            'role': role_label,
                            'role_label': role_label,
                            'is_mandatory': is_mand,
                            'state': 'pending',
                        }))

            if len(sig_cmds) > 1:
                self.committee_signature_ids = sig_cmds

    def action_load_candidates_from_vacancy(self):
        """Auto-populate candidate score lines from internal/external process records or vacancy scoring records."""
        self.ensure_one()
        if not self.vacancy_id:
            return

        if self.id:
            self.ranking_line_ids.unlink()

        lines = []

        # 1. Search Internal Recruitment Process Selected records
        int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
            '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
        ], limit=1)

        if int_sel and int_sel.new_int_rec_sel:
            for cand in int_sel.new_int_rec_sel:
                if not cand.emp_name:
                    continue
                # Exclude disqualified or rejected candidates
                if cand.selection_type == 'rejected' or getattr(cand, 'is_disqualified', False) or not cand.rank:
                    continue
                status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else 'reserve'
                lines.append((0, 0, {
                    'employee_id': cand.emp_name.id,
                    'candidate_name': cand.emp_name.name,
                    'pms_score': cand.pms_score or 0.0,
                    'experience_score': getattr(cand, 'experience_score', 0.0) or 0.0,
                    'service_location_score': getattr(cand, 'location_score', 0.0) or 0.0,
                    'application_date_score': getattr(cand, 'app_date_score', 0.0) or 0.0,
                    'recommendation_score': getattr(cand, 'supervisor_recommendation_score', 0.0) or 0.0,
                    'written_score': cand.written_exam_score or 0.0,
                    'interview_score': cand.interview_score or 0.0,
                    'final_score': cand.weighted_score or 0.0,
                    'rank': cand.rank or 0,
                    'selection_status': status_val,
                }))

        # 2. Search External Recruitment Process Selected records
        if not lines:
            ext_sel = self.env["external.recruitment.selected"].sudo().search([
                '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
            ], limit=1)
            if ext_sel and ext_sel.ext_rec_sel:
                for cand in ext_sel.ext_rec_sel:
                    if cand.selection_type == 'rejected' or getattr(cand, 'disqualified', False) or not getattr(cand, 'rank', 0):
                        continue
                    cand_name = cand.applicant_name.partner_name if (cand.applicant_name and getattr(cand.applicant_name, 'partner_name', False)) else (cand.applicant_name.name if cand.applicant_name else cand.emp_name or 'Applicant')
                    status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else 'reserve'
                    lines.append((0, 0, {
                        'applicant_id': cand.applicant_name.id if cand.applicant_name else False,
                        'candidate_name': cand_name,
                        'written_score': cand.written_exam_score or 0.0,
                        'interview_score': cand.interview_score or 0.0,
                        'final_score': cand.weighted_score or 0.0,
                        'rank': getattr(cand, 'rank', 0) or 0,
                        'selection_status': status_val,
                    }))

        # 3. Fallback to candidate scoring table
        if not lines:
            scores = self.env["recruitment.candidate.score"].search(
                [("vacancy_id", "=", self.vacancy_id.id), ("disqualified", "=", False)],
                order="rank asc, final_score desc",
            )
            for score in scores:
                lines.append(
                    (
                        0,
                        0,
                        {
                            "candidate_score_id": score.id,
                            "applicant_id": score.applicant_id.id
                            if self.recruitment_type == "external"
                            else False,
                            "employee_id": score.employee_id.id
                            if self.recruitment_type == "internal"
                            else False,
                            "candidate_name": score.candidate_name,
                            "pms_score": score.pms_score,
                            "written_score": score.written_score,
                            "interview_score": score.interview_score,
                            "final_score": score.final_score,
                            "rank": score.rank,
                            "selection_status": "selected"
                            if score.rank <= (self.vacancy_id.no_of_vacancies or 1)
                            else "reserve",
                        },
                    )
                )

        if lines:
            self.write({"ranking_line_ids": lines})

    @api.depends("approval_hierarchy_type", "vacancy_id", "recruitment_type")
    def _compute_allowed_committee_users(self):
        ConfigModel = self.env["committee.role.config"]
        all_active_users = self.env["res.users"].search([("active", "=", True)])
        for rec in self:
            htype = rec.approval_hierarchy_type or "ho_district_grade2_plus"
            scope = rec.recruitment_type or "all"
            cfg = ConfigModel.get_config_for_hierarchy(htype, scope=scope)
            vac = rec.vacancy_id if rec.vacancy_id else False
            ou = getattr(vac, "operating_unit_id", False) or None
            dept = (getattr(ou, "department", False) or (vac.job_position.department_id if vac and vac.job_position else False)) if vac else None
            if cfg:
                c_users = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou, department=dept)
                p_users = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou, department=dept)
                s_users = cfg.get_allowed_users_for_role("secretary", operating_unit=ou, department=dept)
                o_users = cfg.get_allowed_users_for_role("observer", operating_unit=ou, department=dept)

                rec.allowed_chairperson_user_ids = c_users
                rec.allowed_panel_member_user_ids = p_users
                rec.allowed_secretary_user_ids = s_users
                rec.allowed_observer_user_ids = o_users
            else:
                rec.allowed_chairperson_user_ids = False
                rec.allowed_panel_member_user_ids = False
                rec.allowed_secretary_user_ids = False
                rec.allowed_observer_user_ids = False

    @api.onchange("approval_hierarchy_type", "vacancy_id")
    def _onchange_committee_hierarchy_roles(self):
        ConfigModel = self.env["committee.role.config"]
        htype = self.approval_hierarchy_type or "ho_district_grade2_plus"
        scope = self.recruitment_type or "all"
        cfg = ConfigModel.get_config_for_hierarchy(htype, scope=scope)
        vac = self.vacancy_id if self.vacancy_id else False
        ou = getattr(vac, "operating_unit_id", False) or None
        dept = (getattr(ou, "department", False) or (vac.job_position.department_id if vac and vac.job_position else False)) if vac else None

        if cfg:
            c_users = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou, department=dept)
            p_users = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou, department=dept)
            s_users = cfg.get_allowed_users_for_role("secretary", operating_unit=ou, department=dept)
            o_users = cfg.get_allowed_users_for_role("observer", operating_unit=ou, department=dept)

            self.allowed_chairperson_user_ids = c_users
            self.allowed_panel_member_user_ids = p_users
            self.allowed_secretary_user_ids = s_users
            self.allowed_observer_user_ids = o_users

            if c_users:
                if self.chairperson_id and self.chairperson_id.id not in c_users.ids:
                    self.chairperson_id = c_users[0] if len(c_users) == 1 else False
                elif not self.chairperson_id and len(c_users) == 1:
                    self.chairperson_id = c_users[0]

            if p_users:
                if self.panel_member_id and self.panel_member_id.id not in p_users.ids:
                    self.panel_member_id = p_users[0] if len(p_users) == 1 else False
                elif not self.panel_member_id and len(p_users) == 1:
                    self.panel_member_id = p_users[0]

            if s_users:
                if self.secretary_id and self.secretary_id.id not in s_users.ids:
                    self.secretary_id = s_users[0] if len(s_users) == 1 else False
                elif not self.secretary_id and len(s_users) == 1:
                    self.secretary_id = s_users[0]

            if o_users:
                if self.observer_id and self.observer_id.id not in o_users.ids:
                    self.observer_id = o_users[0] if len(o_users) == 1 else False
                elif not self.observer_id and len(o_users) == 1:
                    self.observer_id = o_users[0]

            return {
                "domain": {
                    "chairperson_id": [("id", "in", c_users.ids)] if c_users else [("id", "=", False)],
                    "panel_member_id": [("id", "in", p_users.ids)] if p_users else [("id", "=", False)],
                    "secretary_id": [("id", "in", s_users.ids)] if s_users else [("id", "=", False)],
                    "observer_id": [("id", "in", o_users.ids)] if o_users else [("id", "=", False)],
                }
            }
        else:
            self.allowed_chairperson_user_ids = False
            self.allowed_panel_member_user_ids = False
            self.allowed_secretary_user_ids = False
            self.allowed_observer_user_ids = False
            self.chairperson_id = False
            self.panel_member_id = False
            self.secretary_id = False
            self.observer_id = False
            return {
                "domain": {
                    "chairperson_id": [("id", "=", False)],
                    "panel_member_id": [("id", "=", False)],
                    "secretary_id": [("id", "=", False)],
                    "observer_id": [("id", "=", False)],
                }
            }

    def _get_hierarchy_role_labels(self, htype=None):
        htype = htype or self.approval_hierarchy_type or "ho_district_grade2_plus"
        if htype == "ho_district_grade2_plus":
            return {
                "chairperson": _("Chief People and Culture Officer (Chairperson)"),
                "panel_member": _("Respective Senior Management (Panel Member)"),
                "secretary": _("Director People Operation Management Directorate (Panel Member & Secretary)"),
                "observer": _("Labor Representative (Observer)"),
            }
        elif htype == "non_managerial_ho":
            return {
                "chairperson": _("Director People Operation Management Directorate (Chairperson)"),
                "panel_member": _("Head Office / District Director (Panel Member)"),
                "secretary": _("Principal HR (Panel Member & Secretary)"),
                "observer": _("Labor Representative (Observer)"),
            }
        else:  # non_managerial_district
            return {
                "chairperson": _("District Director (Chairperson)"),
                "panel_member": _("District Division Member (Panel Member)"),
                "secretary": _("Principal HR (Panel Member & Secretary)"),
                "observer": _("Labor Representative (Observer)"),
            }

    @api.onchange("approval_hierarchy_type", "chairperson_id", "panel_member_id", "secretary_id", "observer_id")
    def _onchange_hierarchy_roles(self):
        """Dynamic preview of digital signature slots when roles or hierarchy category are updated in draft."""
        if self.state == "draft" and (self.chairperson_id or self.panel_member_id or self.secretary_id):
            labels = self._get_hierarchy_role_labels()
            sig_cmds = [(5, 0, 0)]
            if self.chairperson_id:
                sig_cmds.append((0, 0, {
                    "user_id": self.chairperson_id.id,
                    "role": "Chairperson",
                    "role_label": labels["chairperson"],
                    "is_mandatory": True,
                    "state": "pending",
                }))
            if self.panel_member_id:
                sig_cmds.append((0, 0, {
                    "user_id": self.panel_member_id.id,
                    "role": "Panel Member",
                    "role_label": labels["panel_member"],
                    "is_mandatory": True,
                    "state": "pending",
                }))
            if self.secretary_id:
                sig_cmds.append((0, 0, {
                    "user_id": self.secretary_id.id,
                    "role": "Panel Member & Secretary",
                    "role_label": labels["secretary"],
                    "is_mandatory": True,
                    "state": "pending",
                }))
            if self.observer_id and self.approval_hierarchy_type != "ho_district_grade2_plus":
                sig_cmds.append((0, 0, {
                    "user_id": self.observer_id.id,
                    "role": "Observer",
                    "role_label": labels["observer"],
                    "is_mandatory": False,
                    "state": "pending",
                }))
            self.committee_signature_ids = sig_cmds

    def action_generate_signature_lines(self):
        """Persist digital signature lines based on assigned committee roles and hierarchy category."""
        for rec in self:
            existing_by_user = {}
            for s in rec.committee_signature_ids:
                if s.user_id:
                    existing_by_user[s.user_id.id] = {
                        'state': s.state,
                        'digital_signature': s.digital_signature,
                        'signature_img': s.signature_img,
                        'signed_date': s.signed_date,
                        'signed_on': s.signed_on if hasattr(s, 'signed_on') else False,
                        'comments': s.comments,
                        'remarks': s.remarks if hasattr(s, 'remarks') else False,
                    }
            rec.committee_signature_ids.unlink()
            labels = rec._get_hierarchy_role_labels()
            lines_to_create = []

            if rec.chairperson_id:
                prev = existing_by_user.get(rec.chairperson_id.id, {})
                lines_to_create.append({
                    "minute_id": rec.id,
                    "user_id": rec.chairperson_id.id,
                    "role": "Chairperson",
                    "role_label": labels["chairperson"],
                    "is_mandatory": True,
                    "state": prev.get("state", "pending"),
                    "digital_signature": prev.get("digital_signature", False),
                    "signature_img": prev.get("signature_img", False),
                    "signed_date": prev.get("signed_date", False),
                    "signed_on": prev.get("signed_on", False),
                    "comments": prev.get("comments", False),
                    "remarks": prev.get("remarks", False),
                })
            if rec.panel_member_id:
                prev = existing_by_user.get(rec.panel_member_id.id, {})
                lines_to_create.append({
                    "minute_id": rec.id,
                    "user_id": rec.panel_member_id.id,
                    "role": "Panel Member",
                    "role_label": labels["panel_member"],
                    "is_mandatory": True,
                    "state": prev.get("state", "pending"),
                    "digital_signature": prev.get("digital_signature", False),
                    "signature_img": prev.get("signature_img", False),
                    "signed_date": prev.get("signed_date", False),
                    "signed_on": prev.get("signed_on", False),
                    "comments": prev.get("comments", False),
                    "remarks": prev.get("remarks", False),
                })
            if rec.secretary_id:
                prev = existing_by_user.get(rec.secretary_id.id, {})
                lines_to_create.append({
                    "minute_id": rec.id,
                    "user_id": rec.secretary_id.id,
                    "role": "Panel Member & Secretary",
                    "role_label": labels["secretary"],
                    "is_mandatory": True,
                    "state": prev.get("state", "pending"),
                    "digital_signature": prev.get("digital_signature", False),
                    "signature_img": prev.get("signature_img", False),
                    "signed_date": prev.get("signed_date", False),
                    "signed_on": prev.get("signed_on", False),
                    "comments": prev.get("comments", False),
                    "remarks": prev.get("remarks", False),
                })
            if rec.observer_id and rec.approval_hierarchy_type != "ho_district_grade2_plus":
                prev = existing_by_user.get(rec.observer_id.id, {})
                lines_to_create.append({
                    "minute_id": rec.id,
                    "user_id": rec.observer_id.id,
                    "role": "Observer",
                    "role_label": labels["observer"],
                    "is_mandatory": False,
                    "state": prev.get("state", "pending"),
                    "digital_signature": prev.get("digital_signature", False),
                    "signature_img": prev.get("signature_img", False),
                    "signed_date": prev.get("signed_date", False),
                    "signed_on": prev.get("signed_on", False),
                    "comments": prev.get("comments", False),
                    "remarks": prev.get("remarks", False),
                })

            if lines_to_create:
                self.env["recruitment.committee.signature"].create(lines_to_create)

    def action_load_panel_members_from_vacancy(self):
        """Auto-populate committee signature slots strictly from explicitly assigned Approval Committee members."""
        self.ensure_one()
        if not self.vacancy_id:
            return

        # Synchronize hierarchy and committee roles from Vacancy or Selection record if set
        vac = self.vacancy_id
        int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
            '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
        ], limit=1)
        ext_sel = self.env["external.recruitment.selected"].sudo().search([
            '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
        ], limit=1)
        sel = int_sel or ext_sel

        htype = vac.approval_hierarchy_type or (sel.approval_hierarchy_type if sel else False) or self.approval_hierarchy_type
        if not htype and hasattr(vac, '_compute_hierarchy_type_recruitment'):
            try:
                htype = vac._compute_hierarchy_type_recruitment()
            except Exception:
                htype = 'ho_district_grade2_plus'
        chair = vac.chairperson_id or (sel.chairperson_id if sel else False) or self.chairperson_id
        panel = vac.panel_member_id or (sel.panel_member_id if sel else False) or self.panel_member_id
        sec = vac.secretary_id or (sel.secretary_id if sel else False) or self.secretary_id
        obs = vac.observer_id or (sel.observer_id if sel else False) or self.observer_id

        vals_to_write = {}
        if htype and self.approval_hierarchy_type != htype:
            vals_to_write['approval_hierarchy_type'] = htype
        if chair and self.chairperson_id != chair:
            vals_to_write['chairperson_id'] = chair.id
        if panel and self.panel_member_id != panel:
            vals_to_write['panel_member_id'] = panel.id
        if sec and self.secretary_id != sec:
            vals_to_write['secretary_id'] = sec.id
        if obs and self.observer_id != obs:
            vals_to_write['observer_id'] = obs.id
        if vals_to_write:
            self.write(vals_to_write)

        # If hierarchy roles are assigned, generate exact signature lines:
        if self.chairperson_id or self.panel_member_id or self.secretary_id:
            self.action_generate_signature_lines()
            return

        sig_lines = []
        added_user_ids = set()

        # 1. Search Internal Process Record Committee Members (recr_selected_team_id)

        if int_sel and int_sel.recr_selected_team_id:
            for member in int_sel.recr_selected_team_id:
                user = member.employee_name or getattr(member, 'alternate_committee_member', False)
                if user and user.id not in added_user_ids:
                    added_user_ids.add(user.id)
                    role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                    is_mand = False if member.role == 'observer' else True
                    sig_lines.append((0, 0, {
                        'user_id': user.id,
                        'role': role_label,
                        'role_label': role_label,
                        'is_mandatory': is_mand,
                        'state': 'pending',
                    }))

        # 2. Search External Process Record Committee Members (recr_exter_selected_team_id / recr_selected_team_id)
        if not sig_lines:
            ext_sel = self.env["external.recruitment.selected"].sudo().search([
                '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
            ], limit=1)
            if ext_sel:
                ext_team = getattr(ext_sel, 'recr_exter_selected_team_id', False) or getattr(ext_sel, 'recr_selected_team_id', False)
                if ext_team:
                    for member in ext_team:
                        user = member.employee_name or getattr(member, 'alternate_committee_member', False)
                        if user and user.id not in added_user_ids:
                            added_user_ids.add(user.id)
                            role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                            is_mand = False if member.role == 'observer' else True
                            sig_lines.append((0, 0, {
                                'user_id': user.id,
                                'role': role_label,
                                'role_label': role_label,
                                'is_mandatory': is_mand,
                                'state': 'pending',
                            }))

        # 3. Search Vacancy Approval / Delegation Team (vac_del_team_id)
        if not sig_lines and self.vacancy_id and self.vacancy_id.vac_del_team_id:
            for del_member in self.vacancy_id.vac_del_team_id:
                user = del_member.employee_name or getattr(del_member, 'alternate_committee_member', False)
                if user and user.id not in added_user_ids:
                    added_user_ids.add(user.id)
                    role_label = dict(del_member._fields['role'].selection).get(del_member.role, 'Committee Member') if del_member.role else 'Committee Member'
                    is_mand = False if del_member.role == 'observer' else True
                    sig_lines.append((0, 0, {
                        'user_id': user.id,
                        'role': role_label,
                        'role_label': role_label,
                        'is_mandatory': is_mand,
                        'state': 'pending',
                    }))

        # 4. If hierarchy committee roles are manually set directly on the minute:
        if not sig_lines and (self.chairperson_id or self.panel_member_id or self.secretary_id):
            labels = self._get_hierarchy_role_labels()
            if self.chairperson_id and self.chairperson_id.id not in added_user_ids:
                added_user_ids.add(self.chairperson_id.id)
                sig_lines.append((0, 0, {
                    'user_id': self.chairperson_id.id,
                    'role': 'Chairperson',
                    'role_label': labels['chairperson'],
                    'is_mandatory': True,
                    'state': 'pending',
                }))
            if self.panel_member_id and self.panel_member_id.id not in added_user_ids:
                added_user_ids.add(self.panel_member_id.id)
                sig_lines.append((0, 0, {
                    'user_id': self.panel_member_id.id,
                    'role': 'Panel Member',
                    'role_label': labels['panel_member'],
                    'is_mandatory': True,
                    'state': 'pending',
                }))
            if self.secretary_id and self.secretary_id.id not in added_user_ids:
                added_user_ids.add(self.secretary_id.id)
                sig_lines.append((0, 0, {
                    'user_id': self.secretary_id.id,
                    'role': 'Panel Member & Secretary',
                    'role_label': labels['secretary'],
                    'is_mandatory': True,
                    'state': 'pending',
                }))
            if self.observer_id and self.observer_id.id not in added_user_ids:
                added_user_ids.add(self.observer_id.id)
                sig_lines.append((0, 0, {
                    'user_id': self.observer_id.id,
                    'role': 'Observer',
                    'role_label': labels['observer'],
                    'is_mandatory': False,
                    'state': 'pending',
                }))

        if self.id:
            self.committee_signature_ids.unlink()
        if sig_lines:
            self.write({"committee_signature_ids": sig_lines})

    def action_load_from_vacancy(self):
        """Reload candidates and committee members from the selected vacancy."""
        for rec in self:
            if rec.vacancy_id:
                rec.action_load_candidates_from_vacancy()
                rec.action_load_panel_members_from_vacancy()
        return True

    def action_notify_panel_members(self):
        """
        Sends notifications exclusively to assigned panel/committee employees
        asking them to review and digitally sign the selection minute via notification message & activities.
        """
        model_id = self.env.ref('custom_recruitment.model_recruitment_selection_minute', raise_if_not_found=False)
        todo_act_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

        committee_group = self.env.ref('custom_recruitment.group_recruitment_approval_committee', raise_if_not_found=False)
        for rec in self:
            if not rec.ranking_line_ids:
                raise UserError(_("Cannot notify panel members without candidate rankings in the minute."))
            passed_candidates = rec.ranking_line_ids.filtered(
                lambda l: l.selection_status in ('selected', 'Selected', 'pass', 'Pass')
            )
            if not passed_candidates:
                raise UserError(
                    _("Cannot notify approval committee! No candidates in the minute are marked as passed or selected. Please ensure candidates have passed and are added to the minute before notifying the committee.")
                )
            if not rec.committee_signature_ids:
                raise UserError(_("No panel/committee members found to notify."))

            # Ensure all assigned committee members have group_recruitment_approval_committee so the menu appears under Employees
            if committee_group:
                current_uids = committee_group.user_ids.ids if hasattr(committee_group, 'user_ids') else []
                users_to_add = rec.committee_signature_ids.mapped('user_id').filtered(lambda u: u.id not in current_uids)
                if users_to_add:
                    try:
                        committee_group.sudo().write({'user_ids': [(4, u.id) for u in users_to_add]})
                    except Exception as e:
                        _logger.warning("Could not auto-assign group_recruitment_approval_committee to users: %s", e)

            notified_partners = []
            for sig in rec.committee_signature_ids:
                if sig.user_id and sig.state == 'pending':
                    if sig.user_id.partner_id:
                        notified_partners.append(sig.user_id.partner_id.id)

                    # Schedule Activity Task for Panel Member in Odoo Systray / Inbox
                    existing_act = self.env['mail.activity'].search([
                        ('res_model', '=', 'recruitment.selection.minute'),
                        ('res_id', '=', rec.id),
                        ('user_id', '=', sig.user_id.id)
                    ], limit=1)
                    if not existing_act and todo_act_type and model_id:
                        self.env['mail.activity'].create({
                            'activity_type_id': todo_act_type.id,
                            'note': _("Selection Minute %s for vacancy %s requires your digital signature.") % (
                                rec.name, rec.vacancy_id.display_name or rec.vacancy_id.name or ''
                            ),
                            'summary': _("Digitally Sign Selection Minute %s") % rec.name,
                            'user_id': sig.user_id.id,
                            'res_model_id': model_id.id,
                            'res_id': rec.id,
                            'date_deadline': fields.Date.context_today(self),
                        })

            # Subscribe partners as followers
            if notified_partners:
                try:
                    rec.message_subscribe(partner_ids=notified_partners)
                except Exception:
                    pass

            # Send targeted Odoo Discuss message notification ONLY to panel members' partners
            notif_msg = None
            if notified_partners:
                try:
                    notif_msg = rec.message_notify(
                        partner_ids=notified_partners,
                        subject=_("Pending Digital Signature: Selection Minute %s") % rec.name,
                        body=_(
                            "Dear Committee Member,\n\n"
                            "Selection Minute %s for vacancy %s is ready for your digital signature.\n\n"
                            "Please review the candidate matrix and provide your digital signature under Employees â†’ Digital Selection Minutes."
                        ) % (rec.name, rec.vacancy_id.display_name or rec.vacancy_id.name or ''),
                        email_layout_xmlid="mail.mail_notification_light",
                    )
                except Exception:
                    pass

            mentions_html = ' '.join([
                f'<a href="#" data-oe-model="res.partner" data-oe-id="{p.id}">@{p.name}</a>'
                for p in rec.committee_signature_ids.mapped('user_id.partner_id')
            ])
            posted_msg = rec.message_post(
                body=_(
                    "<p>Digital Signature notification dispatched to committee members: %s</p>"
                    "<p>Please review and sign under the Committee Signatures tab.</p>"
                ) % mentions_html,
                partner_ids=notified_partners,
                message_type='comment',
                subtype_xmlid="mail.mt_comment",
            )
            rec.write({'panel_notified': True})

            # Enforce Discuss Inbox delivery
            all_msg_ids = [m.id for m in (notif_msg, posted_msg) if m]
            if all_msg_ids and notified_partners:
                notifs = self.env['mail.notification'].search([
                    ('mail_message_id', 'in', all_msg_ids),
                    ('res_partner_id', 'in', notified_partners),
                ])
                if notifs:
                    notifs.write({
                        'notification_type': 'inbox',
                        'notification_status': 'sent',
                        'is_read': False,
                    })

            # Send 1-on-1 Discuss DM
            if 'discuss.channel' in self.env:
                for sig in rec.committee_signature_ids.filtered(lambda l: l.state == 'pending' and l.user_id):
                    user = sig.user_id
                    if user.partner_id and user.id != self.env.user.id:
                        try:
                            chat_channel = self.env['discuss.channel']._get_or_create_chat(
                                partners_to=[self.env.user.partner_id.id, user.partner_id.id]
                            )
                            if chat_channel:
                                dm_msg = chat_channel.message_post(
                                    body=_(
                                        "Hello %s, Selection Minute %s for vacancy %s is ready for your digital signature. "
                                        "Please review and sign under Employees â†’ Digital Selection Minutes."
                                    ) % (user.name, rec.name, rec.vacancy_id.display_name or rec.vacancy_id.name or ''),
                                    message_type='comment',
                                    subtype_xmlid='mail.mt_comment',
                                )
                                dm_notifs = self.env['mail.notification'].search([
                                    ('mail_message_id', '=', dm_msg.id),
                                    ('res_partner_id', '=', user.partner_id.id),
                                ])
                                if dm_notifs:
                                    dm_notifs.write({
                                        'notification_type': 'inbox',
                                        'notification_status': 'sent',
                                        'is_read': False,
                                    })
                        except Exception:
                            pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Panel Members Notified'),
                'message': _('Digital signature request notifications and activity tasks sent to panel members.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_submit_to_committee(self):
        self.ensure_one()
        if not self.ranking_line_ids:
            raise ValidationError(
                _("Cannot submit minute without candidate rankings.")
            )

        passed_candidates = self.ranking_line_ids.filtered(
            lambda l: l.selection_status in ('selected', 'Selected', 'pass', 'Pass')
        )
        if not passed_candidates:
            raise ValidationError(
                _("Cannot notify approval committee! No candidates in the minute are marked as passed or selected. Please ensure candidates have passed and are added to the minute before submitting.")
            )

        if not self.committee_signature_ids:
            if self.chairperson_id or self.panel_member_id or self.secretary_id:
                self.action_generate_signature_lines()
            else:
                self.action_load_panel_members_from_vacancy()

        if not self.committee_signature_ids:
            raise ValidationError(
                _("Please add committee members before submitting for approval.")
            )

        self.write({"state": "pending_approval", "panel_notified": True})
        self.action_notify_panel_members()

    def write(self, vals):
        if "meeting_time" in vals and not self._is_clean_amharic_time(vals.get("meeting_time")):
            vals["meeting_time"] = "ከጠዋቱ በ3፡00 ሰዓት"
        if "meeting_end_time" in vals and not self._is_clean_amharic_time(vals.get("meeting_end_time")):
            vals["meeting_end_time"] = "ከቀኑ በ 6፡00 ሰዓት"
        if "meeting_place" in vals and not self._is_clean_amharic(vals.get("meeting_place")):
            vals["meeting_place"] = "ፒፕል ኦፕሬሽን ማኔጅመንት ዳይሬክቶሬት ቢሮ"
        res = super(RecruitmentSelectionMinute, self.sudo() if not self.env.is_admin() else self).write(vals)
        for rec in self:
            rec._check_auto_approval()
        return res

    def _check_auto_approval(self):
        """Auto-triggers approval once all committee members sign and updates the selection process state to Approved."""
        for rec in self:
            if (rec.state == "pending_approval" and rec.is_fully_signed) or rec.state == "approved":
                if rec.state == "pending_approval":
                    rec.sudo().write({"state": "approved"})
                    rec.sudo().message_post(
                        body=_(
                            "All committee members have digitally signed. Selection Minute is officially APPROVED."
                        )
                    )
                    rec._generate_and_attach_pdf()

                # Sync approval status back to recruitment selection records
                if rec.vacancy_id:
                    vac_ref = rec.vacancy_id.reference
                    vac_id = rec.vacancy_id.id
                    rec.vacancy_id.sudo().write({'minute_signed': True})

                    # 1. Internal Recruitment Process Selected
                    int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
                        '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
                    ])
                    for s in int_sel:
                        s.sudo().write({'state': 'approved', 'status': 'approved'})
                        s.sudo().message_post(body=_(
                            "Selection Process officially APPROVED: All committee members have digitally signed Selection Minute <b>%s</b>."
                        ) % rec.name)

                    # 2. External Recruitment Process Selected
                    ext_sel = self.env["external.recruitment.selected"].sudo().search([
                        '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
                    ])
                    for s in ext_sel:
                        s.sudo().write({'state': 'approved', 'status': 'approved'})
                        s.sudo().message_post(body=_(
                            "Selection Process officially APPROVED: All committee members have digitally signed Selection Minute <b>%s</b>."
                        ) % rec.name)

                    # 3. Update PBMS Manpower Plan Line Fulfillment Count
                    selected_count = 0
                    if rec.ranking_line_ids:
                        selected_count = len(rec.ranking_line_ids.filtered(lambda l: l.selection_status in ('selected', 'Selected')))
                    if not selected_count:
                        selected_count = rec.vacancy_id.no_of_vacancies or 1

                    PbmsLine = self.env.get("pbms.plan.category.line")
                    if PbmsLine is not None and rec.vacancy_id and rec.vacancy_id.operating_unit_id:
                        ou_id = rec.vacancy_id.operating_unit_id.id
                        job_id = rec.vacancy_id.job_position.id if rec.vacancy_id.job_position else False
                        plan_domain = [
                            ("line_type", "=", "manpower"),
                            ("org_unit_id", "=", ou_id),
                        ]
                        if job_id:
                            plan_domain.append(("job_id", "=", job_id))
                        pbms_lines = PbmsLine.sudo().search(plan_domain, order="id desc", limit=1)
                        if pbms_lines:
                            for pl in pbms_lines:
                                curr_fulfilled = pl.fulfilled_quantity or 0
                                pl.sudo().write({"fulfilled_quantity": curr_fulfilled + selected_count})
                                pl.sudo()._compute_remaining_approved_annual_total()

    @api.model
    def verify_selection_minute_fully_approved(self, vacancy_id=None, vacancy_ref=None):
        """
        Validates that a recruitment selection minute exists for the vacancy (internal or external),
        that committee members are assigned, and that ALL committee members have approved and digitally signed.
        If any committee member has not signed or if the minute is not approved,
        raises a detailed UserError listing remaining members.
        """
        if vacancy_id and hasattr(vacancy_id, 'id'):
            vacancy_id = vacancy_id.id

        if vacancy_id and not vacancy_ref:
            vac = self.env["job.vacancy"].browse(vacancy_id)
            if vac.exists():
                vacancy_ref = vac.reference

        if not vacancy_id and vacancy_ref:
            vac = self.env["job.vacancy"].search([("reference", "=", vacancy_ref)], limit=1)
            if vac:
                vacancy_id = vac.id

        ref_str = vacancy_ref or str(vacancy_id or "")

        minute_rec = False
        if self and self._name == "recruitment.selection.minute" and len(self) == 1 and self.id:
            minute_rec = self
        else:
            domain = []
            if vacancy_id and vacancy_ref:
                domain = ["|", ("vacancy_id", "=", vacancy_id), ("vacancy_id.reference", "=", vacancy_ref)]
            elif vacancy_id:
                domain = [("vacancy_id", "=", vacancy_id)]
            elif vacancy_ref:
                domain = [("vacancy_id.reference", "=", vacancy_ref)]
            else:
                raise UserError(_("No vacancy reference found to check Selection Committee Minute."))

            minute_rec = self.search(domain, order="id desc", limit=1)

        # Fallback for lateral transfer vacancies: check transfer.committee.minutes
        if not minute_rec:
            tcm_domain = []
            if vacancy_id and vacancy_ref:
                tcm_domain = ["|", ("target_vacancy_id", "=", vacancy_id), ("target_vacancy_id.reference", "=", vacancy_ref)]
            elif vacancy_id:
                tcm_domain = [("target_vacancy_id", "=", vacancy_id)]
            elif vacancy_ref:
                tcm_domain = [("target_vacancy_id.reference", "=", vacancy_ref)]
            if tcm_domain:
                tcm = self.env["transfer.committee.minutes"].search(tcm_domain, order="id desc", limit=1)
                if tcm:
                    if not tcm.signature_line_ids:
                        raise UserError(_(
                            "Cannot notify selected candidates! No committee members are assigned to sign Committee Minute '%s' for vacancy '%s'.\n"
                            "Please ensure committee members are assigned and complete their digital signatures before notifying candidates."
                        ) % (tcm.name or "N/A", ref_str))
                    unsigned_tcm = tcm.signature_line_ids.filtered(
                        lambda s: s.is_mandatory and (s.state != 'signed' or not s.digital_signature)
                    )
                    if unsigned_tcm:
                        remaining = [
                            f"• {s.user_id.name or 'Unknown User'} ({s.role_label or s.role_type}) — Status: Pending Signature"
                            for s in unsigned_tcm
                        ]
                        raise UserError(_(
                            "Cannot notify selected candidates! All committee members must digitally sign the Committee Minute before candidates can be notified.\n\n"
                            "Transfer Committee Minute: %s (Vacancy: %s)\n\n"
                            "The following committee member(s) have not signed yet:\n%s"
                        ) % (tcm.name, ref_str, "\n".join(remaining)))
                    if tcm.state != 'approved':
                        raise UserError(_(
                            "Cannot notify selected candidates! Transfer Committee Minute '%s' is in status '%s'.\n"
                            "All committee members must sign and the minute must be approved before notifying candidates."
                        ) % (tcm.name, tcm.state))
                    return tcm

        if not minute_rec:
            raise UserError(_(
                "Cannot notify selected candidates! No Selection Committee Minute found for vacancy '%s'.\n"
                "Please first generate and complete the Selection Committee Minute and ensure all committee members digitally sign before notifying candidates."
            ) % ref_str)

        # Ensure committee signature slots are populated
        if not minute_rec.committee_signature_ids:
            minute_rec.action_load_panel_members_from_vacancy()

        if not minute_rec.committee_signature_ids:
            raise UserError(_(
                "Cannot notify selected candidates! No approval committee members are configured on Selection Committee Minute '%s' (Vacancy: %s).\n"
                "Please ensure committee members are assigned and complete their digital signatures."
            ) % (minute_rec.name or ref_str, ref_str))

        # Check for unsigned committee members
        unsigned_sigs = minute_rec.committee_signature_ids.filtered(
            lambda s: (s.is_mandatory or not s.is_mandatory) and (s.state != "signed" or not (s.digital_signature or s.signature_img))
        )
        if unsigned_sigs:
            remaining_members = []
            for sig in unsigned_sigs:
                member_name = sig.user_id.name or sig.user_id.login or _("Unknown User")
                role_title = sig.role_label or sig.role or _("Committee Member")
                state_val = sig.state or "pending"
                state_desc = dict(sig._fields['state'].selection).get(state_val, state_val.capitalize())
                if not (sig.digital_signature or sig.signature_img):
                    state_desc = _("Signature Pending")
                remaining_members.append(f"• {member_name} ({role_title}) — Status: {state_desc}")

            remaining_str = "\n".join(remaining_members)
            raise UserError(_(
                "Cannot notify selected candidates! All committee members must digitally sign the Selection Committee Minute before candidates can be notified.\n\n"
                "Selection Committee Minute: %s (Vacancy: %s)\n\n"
                "The following committee member(s) have not approved / signed yet:\n%s"
            ) % (minute_rec.name or ref_str, ref_str, remaining_str))

        if minute_rec.state != "approved":
            minute_rec._check_auto_approval()

        if minute_rec.state != "approved" or not minute_rec.is_fully_signed:
            state_label = dict(minute_rec._fields['state'].selection).get(minute_rec.state, minute_rec.state)
            raise UserError(_(
                "Cannot notify selected candidates! Selection Committee Minute '%s' is in status '%s'.\n"
                "All committee members must digitally sign and the minute must be approved before notifying candidates."
            ) % (minute_rec.name or ref_str, state_label))

        return minute_rec

    def _generate_and_attach_pdf(self):
        try:
            pdf_content, report_format = self.env["ir.actions.report"].sudo()._render_qweb_pdf(
                "custom_recruitment.action_report_selection_minute", [self.id]
            )
            rec_track = self.recruitment_type or "recruitment"
            filename = f"Selection_Minute_{rec_track}_{self.name.replace('/', '_')}.pdf"
            attachment = self.env["ir.attachment"].sudo().create(
                {
                    "name": filename,
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/pdf",
                }
            )
            self.sudo().message_post(
                body=_("Signed PDF Selection Minute has been generated and attached."),
                attachment_ids=[attachment.id],
            )
        except Exception as e:
            _logger.warning("PDF Minute Generation Warning: %s", e)

    def get_ethiopic_meeting_date(self):
        self.ensure_one()
        return gregorian_to_ethiopian(self.meeting_date or fields.Date.context_today(self))

    def get_meeting_place(self):
        self.ensure_one()
        if self.meeting_place:
            return self.meeting_place
        if self.vacancy_id and self.vacancy_id.interview_location:
            return self.vacancy_id.interview_location
        return "ፒፕል ኦፕሬሽን ማኔጅመንት ዳይሬክቶሬት ቢሮ"

    def get_meeting_time(self):
        self.ensure_one()
        val = self.meeting_time
        return val if self._is_clean_amharic_time(val) else "ከጠዋቱ በ3፡00 ሰዓት"

    def get_meeting_end_time(self):
        self.ensure_one()
        val = self.meeting_end_time
        return val if self._is_clean_amharic_time(val) else "ከቀኑ በ 6፡00 ሰዓት"

    def get_external_minute_number_display(self):
        self.ensure_one()
        name = self.name or "001"
        if "/" in name:
            parts = name.split("/")
            num_part = parts[-1]
            return f"{num_part}/ ({self._get_minute_fiscal_year_label()})"
        return f"{name}/ ({self._get_minute_fiscal_year_label()})"

    def _get_minute_fiscal_year_label(self):
        today = self.meeting_date or fields.Date.context_today(self)
        year = today.year
        start_year = year if today.month >= 7 else year - 1
        return f"{start_year}/{str(start_year + 1)[-2:]}"

    def get_job_grade_display(self):
        self.ensure_one()
        vac = self.vacancy_id
        if not vac:
            return ""
        if vac.job_grade:
            return getattr(vac.job_grade, 'grade_name', False) or getattr(vac.job_grade, 'display_name', '')
        if vac.job_position and getattr(vac.job_position, 'grade', False):
            return getattr(vac.job_position.grade, 'grade_name', False) or getattr(vac.job_position.grade, 'display_name', '')
        return ""

    def get_department_display(self):
        self.ensure_one()
        vac = self.vacancy_id
        if not vac:
            return ""
        if getattr(vac, 'operating_unit_id', False):
            return vac.operating_unit_id.name
        if getattr(vac, 'department_id', False):
            return vac.department_id.name
        if getattr(vac, 'job_position', False) and getattr(vac.job_position, 'department_id', False):
            return vac.job_position.department_id.name
        if getattr(vac, 'job_location', False):
            return vac.job_location
        return ""

    def get_external_weights(self):
        self.ensure_one()
        vac = self.vacancy_id
        w_exam = 50
        w_int = 50
        if vac:
            if vac.written_weight and vac.interview_weight:
                w_exam = int(round(vac.written_weight))
                w_int = int(round(vac.interview_weight))
            elif getattr(vac, 'ext_selected_recruitment_id', False):
                ext = vac.ext_selected_recruitment_id
                ew, iw = ext._get_external_weights()
                w_exam = int(round(ew))
                w_int = int(round(iw))
        return w_exam, w_int

    def get_written_weight_pct(self):
        w_exam, _ = self.get_external_weights()
        return str(w_exam)

    def get_interview_weight_pct(self):
        _, w_int = self.get_external_weights()
        return str(w_int)

    def get_amharic_role(self, role_str):
        r = str(role_str or '').lower()
        if 'chair' in r or 'ሰብሳቢ' in r:
            return "ሰብሳቢ"
        if 'sec' in r or 'ፀሐፊ' in r or 'ፀሀፊ' in r:
            return "አባል እና ፀሐፊ"
        if 'obs' in r or 'ታዛቢ' in r:
            return "ታዛቢ (የሰራተኛ ተወካይ)"
        return "አባል"

    def get_amharic_status(self, status, rank=0):
        s = str(status or '').lower()
        if 'select' in s:
            return "ተመርጠዋል"
        if 'reser' in s:
            return "ተጠባባቂ"
        return "አልተመረጡም"

    def get_external_table_data(self):
        self.ensure_one()
        res = []
        sorted_lines = self.ranking_line_ids.sorted(key=lambda l: (l.rank or 999, -(l.final_score or 0.0)))
        for idx, line in enumerate(sorted_lines, start=1):
            rank_str = f"{line.rank}ኛ" if line.rank else f"{idx}ኛ"
            status_str = self.get_amharic_status(line.selection_status, line.rank)
            
            # Resolve candidate branch/location
            branch_name = ""
            if line.applicant_id:
                branch_name = line.applicant_id.preferred_location or (
                    line.applicant_id.operating_unit_id.name if hasattr(line.applicant_id, 'operating_unit_id') and line.applicant_id.operating_unit_id else ""
                ) or (
                    line.applicant_id.app_reference.operating_unit_id.name if line.applicant_id.app_reference and line.applicant_id.app_reference.operating_unit_id else ""
                )
            if not branch_name and self.vacancy_id and self.vacancy_id.operating_unit_id:
                branch_name = self.vacancy_id.operating_unit_id.name or ""

            res.append({
                'num': idx,
                'name': line.candidate_name,
                'branch': branch_name or "-",
                'written': f"{line.written_score:.2f}" if line.written_score else "0.00",
                'interview': f"{line.interview_score:.2f}" if line.interview_score else "0.00",
                'total': f"{line.final_score:.2f}" if line.final_score else "0.00",
                'rank': rank_str,
                'status': status_str,
                'selection_status': line.selection_status,
                'remarks': line.remarks or status_str,
            })
        return res

    def get_external_decision_resolution(self):
        self.ensure_one()
        selected_lines = self.ranking_line_ids.filtered(lambda l: l.selection_status == 'selected').sorted(key=lambda l: (l.rank or 999, -(l.final_score or 0.0)))
        reserve_lines = self.ranking_line_ids.filtered(lambda l: l.selection_status in ('reserve', 'reserved')).sorted(key=lambda l: (l.rank or 999, -(l.final_score or 0.0)))
        
        if not selected_lines and self.decision_summary:
            return self.decision_summary
        
        dept = self.get_department_display() or "ባንኩ"
        pos = (self.vacancy_id.job_position.name if self.vacancy_id and self.vacancy_id.job_position else False) or (self.vacancy_id.name if self.vacancy_id else "የሥራ መደብ")
        grade = self.get_job_grade_display()
        grade_str = f"በሥራ ደረጃ {grade} " if grade else ""
        
        grade_rec = self.vacancy_id.job_grade or (self.vacancy_id.job_position.grade if self.vacancy_id and self.vacancy_id.job_position else False)
        salary = 0.0
        if grade_rec:
            salary = getattr(grade_rec, 'base_salary', 0.0) or getattr(grade_rec, 'basic_salary', 0.0) or 0.0
        if not salary and self.vacancy_id:
            salary = getattr(self.vacancy_id, 'starting_salary', 0.0) or getattr(self.vacancy_id, 'base_salary', 0.0) or getattr(self.vacancy_id, 'basic_salary', 0.0) or 0.0
        
        salary_str = f"{salary:,.2f}" if salary > 0 else ""
        salary_words = amount_to_words_amharic(salary) if salary > 0 else ""
        salary_part = f"መነሻ ደመወዝ ብር {salary_str} ({salary_words}) እየተከፈላቸው" if salary_str else "በተወሰነው መነሻ ደመወዝ"

        sel_parts = []
        for l in selected_lines:
            br = l.applicant_id.preferred_location if l.applicant_id and l.applicant_id.preferred_location else ""
            if br:
                sel_parts.append(f"ለ{br} {l.candidate_name}")
            else:
                sel_parts.append(l.candidate_name)
        selected_text = "፣ ".join(sel_parts) if sel_parts else "የተመረጡት ተወዳዳሪዎች"

        res_text = f"በዚሁ መሠረት {selected_text} በ{pos} የሥራ መደብ ላይ {grade_str}{salary_part} እንዲቀጠሩ ኮሚቴው ስምምነት ላይ ደርሷል፡፡"

        if reserve_lines:
            res_names = "፣ ".join([l.candidate_name for l in reserve_lines])
            res_text += f" በተጠባባቂነት የተቀመጡት ተወዳዳሪዎች {res_names} በአካባቢው ቢሮ ባሉት ቅርንጫፎች በ6 ወራት ውስጥ ክፍተት ሲኖር እንዲመደቡ ተወስኗል፡፡"

        return res_text

    def get_external_narrative_p1(self):
        self.ensure_one()
        vac = self.vacancy_id
        dept = self.get_department_display() or "ባንኩ"
        pos = (vac.job_position.name if vac and vac.job_position else False) or (vac.name if vac else "የሥራ መደብ")
        ref = vac.reference if vac else ""
        ann_date = getattr(vac, 'vacancy_announced_on', False) or getattr(vac, 'opening_date', False) or getattr(vac, 'date_announced', False)
        date_str = ann_date.strftime('%d/%m/%Y') if ann_date else (self.meeting_date.strftime('%d/%m/%Y') if self.meeting_date else "")

        total_applicants = 0
        shortlisted_count = 0
        exam_count = len(self.ranking_line_ids)

        ext_sel = self.env["external.recruitment.selected"].sudo().search([
            '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
        ], limit=1) if vac else False

        if ext_sel:
            if hasattr(ext_sel, 'applicant_count') and ext_sel.applicant_count:
                total_applicants = ext_sel.applicant_count
            if hasattr(ext_sel, 'shortlisted_count') and ext_sel.shortlisted_count:
                shortlisted_count = ext_sel.shortlisted_count
        if not total_applicants and vac:
            total_applicants = self.env['hr.applicant'].search_count([
                '|', ('app_reference', '=', vac.id), ('vacancy_reference', '=', vac.reference)
            ]) or (self.env['hr.applicant'].search_count([('job_id', '=', vac.job_position.id)]) if vac.job_position else exam_count)
        if not shortlisted_count:
            shortlisted_count = max(exam_count, total_applicants)
        if not total_applicants:
            total_applicants = exam_count or 1
        if not shortlisted_count:
            shortlisted_count = exam_count or 1

        interview_count = len(self.ranking_line_ids.filtered(lambda l: (l.interview_score or 0.0) > 0 or l.selection_status in ('selected', 'reserve', 'reserved', 'pass')))
        if not interview_count:
            interview_count = exam_count

        return (
            f"በ {dept} ስር ለሚገኙት ቅርንጫፎች በእድገት፣ በዝውውር እንዲሁም ከሥራ በለቀቁ ሠራተኞች ምትክ የሰው ኃይል ለመመደብ "
            f"ለውስጥ ሠራተኞች በዝውውር ማስታወቂያ ቢወጣም በቂ የሰው ኃይል አልተገኘም፡፡ በመሆኑም ከውጭ ቅጥር ለመፈፀም እንዲፈቀድልን "
            f"በተፈቀደው መሠረት የውጭ ማስታወቂያ በማውጣት {total_applicants} አመልካቾች የተመዘገቡ ሲሆን {shortlisted_count} አመልካቾች "
            f"ለጽሁፍ ፈተና ተጠርተው {exam_count} ተወዳዳሪዎች ተፈትነዋል፡፡ በመሆኑም የፅሁፍ ፈተና ያለፉ {interview_count} ተወዳዳሪዎች ለቃለ መጠይቅ ተጠርተዋል፡፡"
        )

    def get_external_narrative_p2(self):
        self.ensure_one()
        return (
            "ከላይ በተጠቀሰው የሥራ መደብ ቅጥር ለመፈፀም ስብሰባው ስለመጠራቱ በሰብሳቢው በኩል ተገልጿል፡፡ "
            "በዚሁ መሠረት አመልካቾች በግንባር ቀርበው ስለራሳቸው ገለጻ በማድረግ ያላቸውን አጠቃላይ የሥራ ልምድ፣ "
            "የትምህርት ዝግጅት እንዲሁም በተያያዥ ጉዳዮች ዙሪያ ከኮሚቴው ባቀረበላቸው ጥያቄ መነሻነት አስፈላጊው የመረጃ ልውውጥ ተደርጓል፡፡ "
            "ስለሆነም ኮሚቴው ለቃለ መጠይቅ የቀረቡትን ተወዳዳሪዎች ሁኔታ በመገምገም በሰንጠረዡ ውስጥ በተቀመጠው መሠረት የቅጥር ሂደታቸው እንዲከናወን ወስኗል፡፡"
        )

    # ==============================================================
    # TRANSFER / LATERAL VACANCY MINUTE HELPER METHODS (ዝውውር Min.docx)
    # ==============================================================
    def is_transfer_or_lateral(self):
        self.ensure_one()
        vac = self.vacancy_id
        if not vac:
            return False
        if getattr(vac, 'is_lateral_transfer', False):
            return True
        if getattr(vac, 'internal_movement_type', False) in ('lateral', 'transfer'):
            return True
        ref = (vac.reference or '').upper()
        if 'LAT' in ref or 'TRANS' in ref:
            return True
        return False

    def get_transfer_minute_number_display(self):
        self.ensure_one()
        ref = self.name or ""
        if "/" in ref:
            return ref.split("/")[-1]
        return ref or "001"

    def get_transfer_fiscal_year_display(self):
        self.ensure_one()
        d = self.meeting_date or fields.Date.context_today(self)
        year = d.year
        if d.month >= 7:
            return f"{year}/{str(year + 1)[-2:]}"
        else:
            return f"{year - 1}/{str(year)[-2:]}"

    def get_transfer_ethiopic_meeting_date(self):
        self.ensure_one()
        d = self.meeting_date or fields.Date.context_today(self)
        eth_m = ["", "መስከረም", "ጥቅምት", "ህዳር", "ታህሳስ", "ጥር", "የካቲት", "መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ"]
        try:
            year, month, day = d.year, d.month, d.day
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
                return f"{eth_m[eth_month]} {eth_day} ቀን {eth_year} ዓ.ም"
        except Exception:
            pass
        return str(d)

    @staticmethod
    def _is_clean_amharic(val):
        if not val or not isinstance(val, str):
            return False
        s = val.strip()
        if any(bad in s for bad in ('á', 'Ã', 'Â', 'â', '€', '™', '?', '`', '\x8d', '\x9d', '\xa0', '\xad')):
            return False
        if any(bad in s for bad in ('CE', 'ዕለትከእኩለ', 'ዕ`ለት')):
            return False
        return True

    @staticmethod
    def _is_clean_amharic_time(val):
        if not val or not isinstance(val, str):
            return False
        s = val.strip()
        if any(bad in s for bad in ('á', 'Ã', 'Â', 'â', '€', '™', '?', '`', '\x8d', '\x9d', '\xa0', '\xad')):
            return False
        if any(bad in s for bad in ('CE', 'ዕለት', 'እኩለ', '`')):
            return False
        if re.search(r'[a-zA-Z]', s):
            return False
        if not any(pref in s for pref in ('ከጠዋቱ', 'ከቀኑ', 'ከሰዓት', 'ከምሽቱ', 'ጠዋት', 'ቀን', 'ከሰአት')):
            return False
        return True

    def get_transfer_meeting_time_display(self):
        val = getattr(self, 'meeting_time', False)
        return val.strip() if self._is_clean_amharic_time(val) else "ከጠዋቱ በ3፡00 ሰዓት"

    def get_transfer_meeting_end_time_display(self):
        val = getattr(self, 'meeting_end_time', False)
        return val.strip() if self._is_clean_amharic_time(val) else "ከቀኑ በ 6፡00 ሰዓት"

    def get_transfer_job_position_name(self):
        self.ensure_one()
        vac = self.vacancy_id
        if vac and vac.job_position:
            return vac.job_position.name
        return vac.name if vac else ""

    def get_transfer_job_grade_name(self):
        self.ensure_one()
        vac = self.vacancy_id
        if vac:
            grade = getattr(vac, 'job_grade', False) or (getattr(vac.job_position, 'grade', False) if vac.job_position else False)
            if grade:
                return getattr(grade, 'grade_name', False) or getattr(grade, 'name', False) or str(grade)
        return self.get_job_grade_display() or "VIII"

    def get_transfer_work_unit_name(self):
        self.ensure_one()
        vac = self.vacancy_id
        if vac and vac.operating_unit_id:
            return vac.operating_unit_id.name
        return self.get_department_display() or ""

    @staticmethod
    def _format_name_with_gender_am(emp_or_user):
        if not emp_or_user:
            return ""
        emp = False
        if emp_or_user._name == 'hr.employee':
            emp = emp_or_user
        elif emp_or_user._name == 'res.users':
            emp = getattr(emp_or_user, 'employee_id', False) or (emp_or_user.employee_ids[0] if getattr(emp_or_user, 'employee_ids', False) else False)
            if not emp:
                emp = emp_or_user.env['hr.employee'].sudo().search([('user_id', '=', emp_or_user.id)], limit=1)
        gender = (getattr(emp, 'gender', '') or '').lower() if emp else ''
        sal = "ወ/ት" if gender in ('female', 'f') else "አቶ"
        name = (emp_or_user.name or "").strip()
        for p in ("አቶ", "ወ/ት", "ወ/ሮ", "ወ/ሪት", "Ato", "W/t", "W/ro", "W/rit", "Mr.", "Mrs.", "Ms."):
            if name.startswith(p + " ") or name.startswith(p + "."):
                name = name[len(p):].lstrip(". ")
                break
        return f"{sal} {name}"

    def get_transfer_committee_members_list(self):
        self.ensure_one()
        parts = []
        if self.chairperson_id:
            parts.append(f"{self._format_name_with_gender_am(self.chairperson_id)} --------------------- ሰብሳቢ ----------------------------")
        if self.panel_member_id:
            parts.append(f"{self._format_name_with_gender_am(self.panel_member_id)} ------------------------------ አባል -------------------------------")
        if self.secretary_id:
            parts.append(f"{self._format_name_with_gender_am(self.secretary_id)} ------------------------------- አባል እና ፀሐፊ ------------------------")
        if self.observer_id and self.approval_hierarchy_type != 'ho_district_grade2_plus':
            parts.append(f"{self._format_name_with_gender_am(self.observer_id)} ------------------------------- የሰራተኛ ተወካይ (ታዛቢ) -------------------")
        if not parts and self.committee_signature_ids:
            for sig in self.committee_signature_ids:
                u_name = self._format_name_with_gender_am(sig.user_id) if sig.user_id else ""
                r_am = self.get_amharic_role(sig.role_label or sig.role)
                parts.append(f"{u_name} --------------------- {r_am} ----------------------------")
        return parts

    def get_transfer_predecessor_narrative(self):
        return "ሲሰሩ የነበሩት ሰራተኛ በደረጃ እድገት / ዝውውር በማግኘታቸው ምክንያት"

    def get_transfer_vacancy_announcement_date_display(self):
        self.ensure_one()
        vac = self.vacancy_id
        if vac:
            d = getattr(vac, 'announcement_date', False) or getattr(vac, 'vacancy_announced_on', False) or getattr(vac, 'opening_date', False)
            if d:
                return d.strftime('%d/%m/%Y')
        d = self.meeting_date or fields.Date.context_today(self)
        return d.strftime('%d/%m/%Y')

    def get_transfer_vacancy_reference_display(self):
        self.ensure_one()
        vac = self.vacancy_id
        if vac and vac.reference:
            return vac.reference
        fy = self.get_transfer_fiscal_year_display().replace('/', '-')
        num = self.get_transfer_minute_number_display()
        return f"BB/LAT/{fy}/{num}"

    def get_transfer_candidate_count_amharic(self):
        self.ensure_one()
        return str(len(self.ranking_line_ids) or 1)

    def get_transfer_selection_adjective(self):
        self.ensure_one()
        if len(self.ranking_line_ids) <= 1:
            return "ብቸኛ ተወዳዳሪ የሆኑትን"
        return "ከፍተኛ ውጤት ያስመዘገቡት ተወዳዳሪ የሆኑትን"

    def get_transfer_selected_candidate_names(self):
        self.ensure_one()
        names = []
        selected_lines = self.ranking_line_ids.filtered(lambda l: l.selection_status in ('selected', 'Selected'))
        if not selected_lines:
            selected_lines = self.ranking_line_ids.sorted(key=lambda l: (l.rank or 999, -(l.final_score or 0.0)))[:1]
        for l in selected_lines:
            emp = l.employee_id
            if emp:
                names.append(self._format_name_with_gender_am(emp))
            elif l.candidate_name:
                names.append(l.candidate_name)
        return ", ".join(names) if names else "ተወዳዳሪውን"

    def get_transfer_table_data(self):
        self.ensure_one()
        res = []
        vac = self.vacancy_id
        int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
            '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
        ], limit=1) if vac else False

        int_cands_by_emp = {}
        if int_sel and int_sel.new_int_rec_sel:
            for c in int_sel.new_int_rec_sel:
                if c.emp_name:
                    int_cands_by_emp[c.emp_name.id] = c

        sorted_lines = self.ranking_line_ids.sorted(key=lambda l: (l.rank or 999, -(l.final_score or 0.0)))
        for idx, line in enumerate(sorted_lines, start=1):
            emp = line.employee_id
            name_str = self._format_name_with_gender_am(emp) if emp else line.candidate_name
            int_cand = int_cands_by_emp.get(emp.id if emp else None, False)

            # Scores:
            pms_raw = line.pms_score or (int_cand.pms_score if int_cand else 0.0) or 0.0
            pms_val = pms_raw * 0.30 if pms_raw > 30.0 else pms_raw

            exp_raw = getattr(line, 'experience_score', 0.0) or (int_cand.experience_score if int_cand else 0.0) or 0.0
            exp_val = exp_raw * 0.20 if exp_raw > 20.0 else exp_raw

            loc_raw = getattr(line, 'service_location_score', 0.0) or (int_cand.location_score if int_cand else 0.0) or 0.0
            loc_val = loc_raw * 0.20 if loc_raw > 20.0 else loc_raw

            app_raw = getattr(line, 'application_date_score', 0.0) or (int_cand.app_date_score if int_cand else 0.0) or 0.0
            app_val = app_raw * 0.20 if app_raw > 20.0 else app_raw

            rec_raw = getattr(line, 'recommendation_score', 0.0) or (int_cand.supervisor_recommendation_score if int_cand else 0.0) or 0.0
            rec_val = rec_raw * 0.10 if rec_raw > 10.0 else rec_raw

            total_val = line.final_score or (pms_val + exp_val + loc_val + app_val + rec_val)
            if total_val == 0.0:
                total_val = pms_val + exp_val + loc_val + app_val + rec_val

            is_selected = line.selection_status in ('selected', 'Selected') or (line.rank and line.rank <= (vac.no_of_vacancies or 1))
            decision_str = "ተመርጠዋል" if is_selected else "ተጠባባቂ"

            res.append({
                'rank': line.rank or idx,
                'name': name_str,
                'pms': f"{pms_val:.2f}",
                'exp': f"{exp_val:.2f}",
                'loc': f"{loc_val:.2f}",
                'app': f"{app_val:.2f}",
                'rec': f"{rec_val:.2f}",
                'total': f"{total_val:.2f}",
                'decision': decision_str,
            })
        return res


class RecruitmentSelectionMinuteLine(models.Model):
    """
    Candidate matrix line within a selection minute.
    Polymorphic link to Applicant (External) or Employee (Internal).
    """
    _name = "recruitment.selection.minute.line"
    _description = "Ranked Candidate Score Line"
    _order = "rank asc, final_score desc"

    minute_id = fields.Many2one(
        "recruitment.selection.minute", string="Minute", ondelete="cascade"
    )
    candidate_score_id = fields.Many2one(
        "recruitment.candidate.score", string="Source Score Record"
    )

    applicant_id = fields.Many2one("hr.applicant", string="Applicant (External)")
    employee_id = fields.Many2one("hr.employee", string="Employee (Internal)")
    candidate_name = fields.Char(string="Candidate Name", required=True)

    pms_score = fields.Float(string="PMS Score", digits=(5, 2))
    experience_score = fields.Float(string="Total Experience (20%)", digits=(5, 2))
    service_location_score = fields.Float(string="Service in Location (20%)", digits=(5, 2))
    application_date_score = fields.Float(string="Application Date (20%)", digits=(5, 2))
    recommendation_score = fields.Float(string="Recommendation (10%)", digits=(5, 2))
    written_score = fields.Float(string="Written Exam", digits=(5, 2))
    interview_score = fields.Float(string="Interview Exam", digits=(5, 2))
    final_score = fields.Float(string="Final Total Score", digits=(5, 2))
    rank = fields.Integer(string="Rank")
    remarks = fields.Char(string="Remarks")

    selection_status = fields.Selection(
        [
            ("selected", "Selected"),
            ("reserve", "Reserve Pool"),
            ("reserved", "Reserve Pool"),
            ("failed", "Failed / Rejected"),
            ("rejected", "Disqualified / Rejected"),
            ("disqualified", "Disqualified"),
            ("pending", "Pending"),
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("not_selected", "Not Selected"),
        ],
        string="Decision",
        default="reserve",
        required=True,
    )

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        valid_statuses = ("selected", "reserve", "reserved", "failed", "rejected", "disqualified", "pending", "pass",
                          "fail", "not_selected")
        for r in res:
            if "selection_status" in r and r["selection_status"] not in valid_statuses:
                r["selection_status"] = "reserve"
        return res


class RecruitmentCommitteeSignature(models.Model):
    """
    Committee member digital signature slot.
    Tracks user, role, state, signature image, timestamp, and IP address for audit integrity.
    """
    _name = "recruitment.committee.signature"
    _description = "Committee Member Digital Signature Slot"
    _order = "id"

    minute_id = fields.Many2one(
        "recruitment.selection.minute", string="Selection Minute", ondelete="cascade"
    )
    user_id = fields.Many2one("res.users", string="Signatory User", required=True)
    role_label = fields.Char(string="Role Title")
    role = fields.Char(
        string="Committee Role", help="e.g. Committee Chair, HR Officer, Technical Examiner"
    )
    is_mandatory = fields.Boolean(
        string="Mandatory?", default=True,
        help="If True, approval cannot complete without this signature. Labor Representatives / Observers are optional."
    )
    digital_signature = fields.Binary(
        string="Digital Signature", copy=False, help="Draw or upload digital signature"
    )
    signature_img = fields.Binary(
        string="Signature Image", copy=False
    )
    signed_on = fields.Datetime(string="Signed Date & Time", readonly=True, copy=False)
    signed_date = fields.Datetime(string="Signed Date", readonly=True, copy=False)
    state = fields.Selection(
        [
            ("pending", "Pending Signature"),
            ("signed", "Signed"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
    )
    remarks = fields.Text(string="Remarks / Comments")
    comments = fields.Text(string="Comments")

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        valid_states = ("pending", "signed", "rejected")
        for r in res:
            if "state" in r and r["state"] not in valid_states:
                r["state"] = "pending"
        return res

    def _generate_digital_signature_badge(self):
        name = self.user_id.name or "Committee Member"
        role = self.role_label or self.role or "Committee Member"
        date_str = fields.Datetime.to_string(fields.Datetime.now())
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100" viewBox="0 0 300 100">
            <rect width="100%" height="100%" fill="#f8f9fa" rx="6" stroke="#4A2E1A" stroke-width="2"/>
            <text x="15" y="32" font-family="'Brush Script MT', 'Dancing Script', cursive, Arial" font-size="22" font-weight="bold" fill="#003366">{name}</text>
            <line x1="15" y1="42" x2="285" y2="42" stroke="#003366" stroke-width="1.5" stroke-dasharray="4"/>
            <text x="15" y="60" font-family="Helvetica, Arial, sans-serif" font-size="11" font-weight="bold" fill="#4A2E1A">Digitally Signed &amp; Authenticated</text>
            <text x="15" y="76" font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#444444">Role: {role} | Date: {date_str}</text>
            <text x="15" y="90" font-family="Helvetica, Arial, sans-serif" font-size="9" font-weight="bold" fill="#28a745">âœ” Verified ERP Digital Signature</text>
        </svg>'''
        return base64.b64encode(svg.encode('utf-8'))

    def write(self, vals):
        """
        Strict signature enforcement:
        1. Only the assigned user (user_id) can sign or modify their signature line.
        2. Automatically change state to 'signed' and set timestamp whenever digital_signature or signature_img is saved.
        """
        has_sig = bool(vals.get("digital_signature") or vals.get("signature_img"))

        # 1. Authorization check: prevent unauthorized users from signing or modifying other members' signature slots
        if (has_sig or "digital_signature" in vals or "signature_img" in vals or vals.get("state") == "signed") and not self.env.su:
            for line in self:
                if line.user_id and line.user_id != self.env.user:
                    raise UserError(_(
                        "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "
                        "You are logged in as '%s'. Only '%s' can digitally sign this line."
                    ) % (line.role_label or line.role or 'Committee Member', line.user_id.name, self.env.user.name, line.user_id.name))

        # 2. Auto-mark state as 'signed' and set timestamp when signature data is entered
        if has_sig and vals.get("state") != "signed":
            now_dt = fields.Datetime.now()
            vals["state"] = "signed"
            if not vals.get("signed_on"):
                vals["signed_on"] = now_dt
            if not vals.get("signed_date"):
                vals["signed_date"] = now_dt

        # Ensure both digital_signature and signature_img fields are kept in sync
        if vals.get("digital_signature") and not vals.get("signature_img"):
            vals["signature_img"] = vals["digital_signature"]
        elif vals.get("signature_img") and not vals.get("digital_signature"):
            vals["digital_signature"] = vals["signature_img"]

        res = super().write(vals)

        # 3. Post-write sync and auto-approval check
        if has_sig or vals.get("state") == "signed":
            for line in self:
                line._sync_signature_to_recruitment_delegation()
                if line.minute_id:
                    line.minute_id._check_auto_approval()

        return res

    @api.onchange('digital_signature', 'signature_img')
    def _onchange_digital_signature(self):
        """Immediately update state to signed in the UI when signature is drawn or uploaded."""
        if self.digital_signature or self.signature_img:
            if self.user_id and self.user_id != self.env.user and not self.env.su:
                raise UserError(_(
                    "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "
                    "You are logged in as '%s'. Only '%s' is authorized to digitally sign this line."
                ) % (self.role_label or self.role or 'Committee Member', self.user_id.name, self.env.user.name, self.user_id.name))
            self.state = 'signed'
            now_dt = fields.Datetime.now()
            self.signed_on = now_dt
            self.signed_date = now_dt
            if self.digital_signature and not self.signature_img:
                self.signature_img = self.digital_signature
            elif self.signature_img and not self.digital_signature:
                self.digital_signature = self.signature_img

    def _apply_signature(self, signature_data=None):
        """Record digital signature and sync to recruitment committee delegation."""
        for line in self:
            if line.user_id and line.user_id != self.env.user and not self.env.su:
                raise UserError(_(
                    "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "
                    "You are logged in as '%s'. Only '%s' is authorized to sign their name on this line."
                ) % (line.role_label or line.role or 'Committee Member', line.user_id.name, self.env.user.name, line.user_id.name))

            now_dt = fields.Datetime.now()
            vals = {
                "state": "signed",
                "signed_on": now_dt,
                "signed_date": now_dt,
            }
            if signature_data:
                vals["digital_signature"] = signature_data
                vals["signature_img"] = signature_data
            elif not line.digital_signature and not line.signature_img:
                sig_badge = line._generate_digital_signature_badge()
                vals["digital_signature"] = sig_badge
                vals["signature_img"] = sig_badge
            elif line.digital_signature and not line.signature_img:
                vals["signature_img"] = line.digital_signature
            elif line.signature_img and not line.digital_signature:
                vals["digital_signature"] = line.signature_img

            line.sudo().write(vals)

            # Sync signature to Job Vacancy / Selection Delegation Team
            line._sync_signature_to_recruitment_delegation()

            if line.minute_id:
                line.minute_id.sudo().message_post(
                    body=_("Digital signature recorded for %s (%s).") % (line.role_label or line.role or 'Committee Member', line.user_id.name)
                )
                line.minute_id._check_auto_approval()
        return True

    def action_sign_digitally(self):
        """Open the Digital Signature Modal Wizard strictly for the designated signatory user."""
        self.ensure_one()
        if self.user_id and self.user_id != self.env.user and not self.env.is_superuser():
            raise UserError(_(
                "Unauthorized Signature Access: The signature line for '%s' is strictly designated for '%s'. "
                "You are currently logged in as '%s'. Only '%s' can digitally sign this line."
            ) % (self.role_label or self.role or 'Committee Member', self.user_id.name, self.env.user.name, self.user_id.name))

        return {
            'name': _('Committee Digital Signature - %s') % (self.role_label or self.role or 'Sign'),
            'type': 'ir.actions.act_window',
            'res_model': 'committee.minute.sign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': self._name,
                'active_id': self.id,
            }
        }

    def action_sign_minute(self):
        return self.action_sign_digitally()

    def _sync_signature_to_recruitment_delegation(self):
        for sig in self:
            if not sig.minute_id or not sig.minute_id.vacancy_id or not sig.user_id:
                continue
            vac = sig.minute_id.vacancy_id.sudo()
            sig_data = sig.digital_signature or sig.signature_img
            dt = sig.signed_on or sig.signed_date or fields.Datetime.now()

            # 1. Sync to Vacancy Delegation Team
            if vac.vac_del_team_id:
                vac_lines = vac.vac_del_team_id.sudo().filtered(
                    lambda m: (m.employee_name.id == sig.user_id.id) or (m.alternate_committee_member.id == sig.user_id.id)
                )
                for vl in vac_lines:
                    vl_vals = {'approve': True}
                    if hasattr(vl, 'digital_signature'):
                        vl_vals['digital_signature'] = sig_data
                    if hasattr(vl, 'signed_on'):
                        vl_vals['signed_on'] = dt
                    vl.sudo().write(vl_vals)

            # 2. Sync to Internal Selection Process Delegation Team
            int_sel = self.env["new.internal.recruitment.selected"].sudo().search([
                '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
            ])
            for s in int_sel:
                for dl in s.recr_selected_team_id.sudo():
                    if dl.employee_name.id == sig.user_id.id or dl.alternate_committee_member.id == sig.user_id.id:
                        dl_vals = {'approve': True}
                        if hasattr(dl, 'digital_signature'):
                            dl_vals['digital_signature'] = sig_data
                        if hasattr(dl, 'signed_on'):
                            dl_vals['signed_on'] = dt
                        dl.sudo().write(dl_vals)

            # 3. Sync to External Selection Process Delegation Team
            ext_sel = self.env["external.recruitment.selected"].sudo().search([
                '|', ('vacancy_id', '=', vac.id), ('vacancy_reference', '=', vac.reference)
            ])
            for s in ext_sel:
                ext_team = getattr(s, 'recr_exter_selected_team_id', False) or getattr(s, 'recr_selected_team_id', False)
                if ext_team:
                    for dl in ext_team.sudo():
                        if dl.employee_name.id == sig.user_id.id or dl.alternate_committee_member.id == sig.user_id.id:
                            dl_vals = {'approve': True}
                            if hasattr(dl, 'digital_signature'):
                                dl_vals['digital_signature'] = sig_data
                            if hasattr(dl, 'signed_on'):
                                dl_vals['signed_on'] = dt
                            dl.sudo().write(dl_vals)
