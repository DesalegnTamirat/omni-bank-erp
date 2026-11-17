# -*- coding: utf-8 -*-

# Transfer Ranking Engine – Fixed for Direct & Vacancy Transfers



import os

import base64

import logging

from odoo import api, fields, models, _
from markupsafe import Markup, escape


from .recruitment_selection_minute import gregorian_to_ethiopian

from odoo.exceptions import UserError, ValidationError



_logger = logging.getLogger(__name__)





class TransferCommitteeMinutes(models.Model):

    _name = "transfer.committee.minutes"

    _inherit = ["mail.thread", "mail.activity.mixin"]

    _description = "Transfer Committee Minutes"

    _rec_name = "name"

    active = fields.Boolean(default=True)



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

    def get_barlow_font_faces(self):

        """Embeds Ethiopic Sadiss, Ebrima, and Barlow fonts for 100% Amharic PDF rendering."""

        from .report_font_utils import get_minute_font_faces_css
        return get_minute_font_faces_css()



    def get_minute_number_display(self):

        self.ensure_one()

        ref = self.name or ""

        if "/" in ref:

            return ref.split("/")[-1]

        return ref or "001"



    def get_fiscal_year_display(self):

        self.ensure_one()

        d = self.meeting_date or fields.Date.context_today(self)

        year = d.year

        if d.month >= 7:

            return f"{year}/{str(year + 1)[-2:]}"

        else:

            return f"{year - 1}/{str(year)[-2:]}"



    def get_ethiopic_meeting_date(self):

        self.ensure_one()

        return gregorian_to_ethiopian(self.meeting_date or fields.Date.context_today(self))



    def get_meeting_time_display(self):

        return "ከጠዋቱ በ3፡00 ሰዓት"



    def get_meeting_end_time_display(self):

        return "ከቀኑ በ 6፡00 ሰዓት"



    def get_target_job_grade_name(self):

        self.ensure_one()

        pos = self.target_job_position_id

        if pos:

            grade = getattr(pos, 'job_grade_id', False) or getattr(pos, 'grade', False) or getattr(pos, 'grade_id', False)

            if grade:

                return getattr(grade, 'grade_name', False) or getattr(grade, 'name', False) or str(grade)

        req = self.transfer_request_ids[:1]

        if req and req.target_job_grade_id:

            return req.target_job_grade_id.grade_name or req.target_job_grade_id.name or "VIII"

        return "VIII"



    @staticmethod
    def _get_employee_from_user_or_emp(obj):
        if not obj:
            return False
        if obj._name == 'hr.employee':
            return obj
        elif obj._name == 'res.users':
            if hasattr(obj, 'employee_id') and obj.employee_id:
                return obj.employee_id
            elif hasattr(obj, 'employee_ids') and obj.employee_ids:
                return obj.employee_ids[0]
            return obj.env['hr.employee'].sudo().search([('user_id', '=', obj.id)], limit=1)
        return False

    @classmethod
    def _get_amharic_salutation(cls, obj):
        emp = cls._get_employee_from_user_or_emp(obj)
        gender = (getattr(emp, 'gender', '') or '').lower() if emp else ''
        if gender in ('female', 'f'):
            return "ወ/ት"
        return "አቶ"

    @classmethod
    def _format_name_with_gender(cls, obj):
        if not obj:
            return ""
        name = (obj.name or "").strip()
        sal = cls._get_amharic_salutation(obj)
        for p in ("አቶ", "ወ/ት", "ወ/ሮ", "ወ/ሪት", "Ato", "W/t", "W/ro", "W/rit", "Mr.", "Mrs.", "Ms."):
            if name.startswith(p + " ") or name.startswith(p + "."):
                name = name[len(p):].lstrip(". ")
                break
        return f"{sal} {name}"

    def get_committee_members_list(self):
        self.ensure_one()
        parts = []
        if self.chairperson_id:
            c_name = self._format_name_with_gender(self.chairperson_id)
            parts.append(f"{c_name} --------------------- ሰብሳቢ ----------------------------")
        if self.panel_member_id:
            p_name = self._format_name_with_gender(self.panel_member_id)
            parts.append(f"{p_name} ------------------------------ አባል -------------------------------")
        if self.secretary_id:
            s_name = self._format_name_with_gender(self.secretary_id)
            parts.append(f"{s_name} ------------------------------- አባል እና ፀሐፊ ------------------------")
        if self.observer_id:
            o_name = self._format_name_with_gender(self.observer_id)
            parts.append(f"{o_name} ------------------------------- የሰራተኛ ተወካይ (ታዛቢ) -------------------")
        return parts

    def get_committee_members_formatted(self):
        self.ensure_one()
        return "\n".join(self.get_committee_members_list())



    def get_predecessor_narrative(self):

        return "ሲሰሩ የነበሩት ሰራተኛ በደረጃ እድገት / ዝውውር በማግኘታቸው ምክንያት"



    def get_vacancy_announcement_date_display(self):

        self.ensure_one()

        if self.target_vacancy_id and getattr(self.target_vacancy_id, 'announcement_date', False):

            return self.target_vacancy_id.announcement_date.strftime('%d/%m/%Y')

        d = self.meeting_date or fields.Date.context_today(self)

        return d.strftime('%d/%m/%Y')



    def get_vacancy_reference_display(self):

        self.ensure_one()

        if self.target_vacancy_id:

            ref = getattr(self.target_vacancy_id, 'reference', False) or getattr(self.target_vacancy_id, 'name', '')

            if ref:

                return ref

        fy = self.get_fiscal_year_display().replace('/', '-')

        num = self.get_minute_number_display()

        return f"BB/LAT/{fy}/{num}"



    def get_candidate_count_amharic(self):

        self.ensure_one()

        return str(len(self.ranking_line_ids) or len(self.transfer_request_ids) or 1)



    def get_selection_adjective(self):

        self.ensure_one()

        total = len(self.ranking_line_ids) or len(self.transfer_request_ids)

        if total <= 1:

            return "ብቸኛ ተወዳዳሪ የሆኑትን"

        return "አሸናፊ ተወዳዳሪ የሆኑትን"



    def get_selected_candidate_names(self):

        self.ensure_one()

        names = []

        selected_lines = self.ranking_line_ids.filtered(lambda l: l.selection_decision == 'selected')

        for l in selected_lines:

            n = l.get_formatted_employee_name()

            if n:

                names.append(n)

        return ", ".join(names) if names else "ተወዳዳሪውን"



    def action_print_minutes(self):

        """Print the official Ethiopian Amharic Transfer Committee Minutes (ቃለ-ጉባዔ) PDF."""

        self.ensure_one()

        return self.env.ref("custom_recruitment.action_report_transfer_minute").report_action(self)



    def _send_candidate_acceptance_offer(self, transfer_req):
        """Dispatches lateral transfer offer to selected candidate's work email, creates systray activity, sends Discuss DM, and posts chatter note."""
        emp = transfer_req.employee_id
        active_email = getattr(transfer_req, 'active_email_address', '') or ''
        email = (emp.work_email or active_email or (emp.user_id and emp.user_id.email) or "").strip()
        ou_name = self.target_operating_unit_id.name or (transfer_req.target_operating_unit_id and transfer_req.target_operating_unit_id.name) or "Target Branch"
        job_name = self.target_job_position_id.name or (transfer_req.target_job_position_id and transfer_req.target_job_position_id.name) or "Target Position"
        emp_name = emp.name or transfer_req.employee_name or "Employee"

        subject = _("Lateral Transfer Selection Offer - %s (%s)") % (ou_name, job_name)
        body_html = _(
            "<div style='font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #222; line-height: 1.6;'>"
            "<p>Dear <strong>%s</strong>,</p>"
            "<p>Congratulations! Following the deliberations of the Transfer Committee (Minutes Ref: <strong>%s</strong>), "
            "you have been <strong>Selected</strong> for lateral transfer to:</p>"
            "<ul>"
            "<li><strong>Target Operating Unit / Branch:</strong> %s</li>"
            "<li><strong>Target Job Position:</strong> %s</li>"
            "</ul>"
            "<p>Please Navigate to: <b>Employee Service</b> &gt; <b>Transfer Request Form</b> (Record: <strong>%s</strong>) "
            "and click <b>Respond to Offer</b> to officially <strong>Accept</strong> or <strong>Decline</strong> this transfer offer.</p>"
            "<p><em>Note: If you accept, your lateral transfer letter will be finalized and sent to your manager for release. If declined, the opportunity will be offered to the next reserved candidate.</em></p>"
            "<br/>"
            "<p>Best regards,<br/><strong>Bunna Bank People Operation Management / Transfer Committee</strong></p>"
            "</div>"
        ) % (emp_name, self.name, ou_name, job_name, transfer_req.name)

        if email:
            try:
                mail_vals = {
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': email,
                    'auto_delete': False,
                }
                self.env['mail.mail'].sudo().create(mail_vals).send(raise_exception=False)
            except Exception as mail_err:
                _logger.warning("Could not send candidate acceptance offer email: %s", mail_err)

        partner_ids = []
        if emp.user_id and emp.user_id.partner_id:
            partner_ids.append(emp.user_id.partner_id.id)

        # 1. Create Systray Activity (To-Do) for candidate
        if emp.user_id:
            model_id = self.env['ir.model'].sudo().search([('model', '=', 'employee.transfer.request')], limit=1)
            todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if model_id and todo_type:
                existing_act = self.env['mail.activity'].sudo().search([
                    ('res_model', '=', 'employee.transfer.request'),
                    ('res_id', '=', transfer_req.id),
                    ('user_id', '=', emp.user_id.id),
                ], limit=1)
                if not existing_act:
                    self.env['mail.activity'].sudo().create({
                        'activity_type_id': todo_type.id,
                        'summary': _("Review and Respond to Transfer Offer"),
                        'note': _("You have been selected for lateral transfer to %s (%s). Please Accept or Decline the offer.") % (ou_name, job_name),
                        'res_model_id': model_id.id,
                        'res_id': transfer_req.id,
                        'user_id': emp.user_id.id,
                        'date_deadline': fields.Date.context_today(self),
                    })

        # 2. Post Chatter Notification with @mention
        mention_html = f'<a href="#" data-oe-model="res.partner" data-oe-id="{emp.user_id.partner_id.id}">@{emp.user_id.partner_id.name}</a>' if (emp.user_id and emp.user_id.partner_id) else emp_name
        transfer_req.sudo().message_post(
            body=_(
                "<p>🎉 <b>Transfer Selection Offer Dispatched:</b> Candidate %s has been selected for lateral transfer to <b>%s</b> (<b>%s</b>).</p>"
                "<p>Action Required: Please open this transfer request and click <b>Respond to Offer (Accept / Decline)</b> to submit your decision via the response wizard.</p>"
            ) % (mention_html, ou_name, job_name),
            partner_ids=partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

        # 3. Discuss 1-on-1 DM to Candidate with Discuss Inbox delivery
        if 'discuss.channel' in self.env and emp.user_id and emp.user_id.partner_id and emp.user_id.id != self.env.user.id:
            try:
                chat_channel = self.env['discuss.channel'].sudo()._get_or_create_chat(
                    partners_to=[self.env.user.partner_id.id, emp.user_id.partner_id.id]
                )
                if chat_channel:
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                    req_url = f"{base_url.rstrip('/')}/web#id={transfer_req.id}&model=transfer.request&view_type=form" if base_url else f"/web#id={transfer_req.id}&model=transfer.request&view_type=form"
                    dm_msg = chat_channel.sudo().message_post(
                        body=Markup(
                            f"<p>Dear <b>{escape(emp.user_id.partner_id.name)}</b>, Congratulations!</p>"
                            f"<p>Following the Transfer Committee deliberations (Minutes: <b>{escape(self.name or '')}</b>), "
                            f"you have been <b>Selected for lateral transfer</b> to <b>{escape(ou_name)}</b> ({escape(job_name)}).</p>"
                            f"<p>Please review and submit your decision to Accept or Decline this transfer offer:</p>"
                            f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                            f"<p style='margin-bottom: 5px;'><a href='{req_url}' target='_blank' style='color: #0d6efd; text-decoration: underline; font-weight: bold;'>{req_url}</a></p>"
                            f"<a href='{req_url}' target='_blank' style='display: inline-block; padding: 9px 18px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                            f"👉 Open Transfer Request ({escape(transfer_req.name or 'Offer')})"
                            f"</a>"
                            f"</div>"
                        ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                    dm_notifs = self.env['mail.notification'].sudo().search([
                        ('mail_message_id', '=', dm_msg.id),
                        ('res_partner_id', '=', emp.user_id.partner_id.id),
                    ])
                    if dm_notifs:
                        dm_notifs.sudo().write({
                            'notification_type': 'inbox',
                            'notification_status': 'sent',
                            'is_read': False,
                        })
            except Exception as dm_err:
                _logger.warning("Could not send Discuss DM to candidate %s: %s", emp_name, dm_err)

    def unlink(self):

        """ Soft delete: Archive records instead of removing from DB """

        for rec in self:

            rec.write({'active': False})

        return True



    _order = "meeting_date desc"



    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))



    target_vacancy_id = fields.Many2one(

        "job.vacancy",

        string="Target Vacancy",

        tracking=True,

        required=False,

        help="Optional vacancy reference.",

    )

    target_operating_unit_id = fields.Many2one(

        "operating.unit",

        string="Target Operating Unit",

        required=True,

        tracking=True,

    )

    target_job_position_id = fields.Many2one(

        "hr.job",

        string="Target Job Position",

        required=True,

        tracking=True,

    )

    allowed_target_operating_unit_ids = fields.Many2many(

        "operating.unit",

        compute="_compute_allowed_target_units_and_positions",

        string="Allowed Target Operating Units",

    )

    allowed_target_job_position_ids = fields.Many2many(

        "hr.job",

        compute="_compute_allowed_target_units_and_positions",

        string="Allowed Target Job Positions",

    )

    available_slots = fields.Integer(

        string="Available Slots",

        default=1,

        help="Number of candidates to be selected.",

    )



    meeting_date = fields.Date(string="Meeting Date", default=fields.Date.context_today, required=True)

    state = fields.Selection(

        [

            ("draft", "Draft"),

            ("ranked", "Ranked"),

            ("waiting_signature", "Waiting Signatures"),

            ("approved", "Approved"),

        ],

        string="Status", default="draft", tracking=True, copy=False,

    )



    approval_hierarchy_type = fields.Selection(

        [

            ("ho_district_grade2_plus", "Head Office & District Grade II and above"),

            ("non_managerial_ho", "For all non-managerial head office"),

            ("non_managerial_district", "For all non-managerial district"),

        ],

        string="Approval Hierarchy Category",

        compute="_compute_hierarchy_type", store=True, readonly=False, tracking=True,

    )



    chairperson_id = fields.Many2one("res.users", string="Chairperson", tracking=True)

    secretary_id = fields.Many2one("res.users", string="Panel Member & Secretary", tracking=True)

    panel_member_id = fields.Many2one("res.users", string="Panel Member", tracking=True)

    observer_id = fields.Many2one("res.users", string="Labor Representative (Observer)", tracking=True)

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



    signature_line_ids = fields.One2many(

        "transfer.committee.signature", "minutes_id", string="Digital Signatures"

    )



    is_fully_signed = fields.Boolean(

        string="All Mandatory Signatures Obtained",

        compute="_compute_is_fully_signed", store=True,

    )

    current_user_can_sign = fields.Boolean(
        string="Current User Can Sign", compute="_compute_current_user_can_sign", store=False
    )

    def _compute_current_user_can_sign(self):
        for rec in self:
            can_sign = False
            if rec.state == 'waiting_signature' and rec.signature_line_ids:
                my_line = rec.signature_line_ids.filtered(
                    lambda s: s.user_id == self.env.user and s.state == 'pending'
                )
                can_sign = bool(my_line)
            rec.current_user_can_sign = can_sign

    def action_sign_my_minute_line(self):
        self.ensure_one()
        my_line = self.signature_line_ids.filtered(
            lambda s: s.user_id == self.env.user and s.state == 'pending'
        )
        if not my_line:
            raise UserError(_("You do not have any pending signature assignments on this Transfer Committee Minute."))
        return my_line[0].action_sign_digitally()



    transfer_request_ids = fields.Many2many(

        "employee.transfer.request", string="Transfer Requests Considered",

    )

    ranking_line_ids = fields.One2many(

        "transfer.committee.minutes.line", "minutes_id", string="Ranked Candidates"

    )

    selection_decision = fields.Text(string="Selection Decision / Committee Notes")



    @api.depends("target_vacancy_id", "transfer_request_ids")

    def _compute_hierarchy_type(self):

        for rec in self:

            req = rec.transfer_request_ids[:1]

            if not req and rec.target_vacancy_id:

                grade = getattr(rec.target_vacancy_id, 'job_grade', False) or getattr(rec.target_vacancy_id, 'job_grade_id', False) or (getattr(rec.target_vacancy_id.job_position, 'grade', False) if rec.target_vacancy_id.job_position else False)

                op_unit = rec.target_vacancy_id.operating_unit_id

                category = rec.target_vacancy_id.employee_category

            elif req:

                grade = req.current_job_grade_id

                op_unit = req.current_operating_unit_id

                category = req.current_job_category

            else:

                grade = False

                op_unit = False

                category = False



            unit_name = str(op_unit.name or "").lower() if op_unit else ""

            is_head_office = "head" in unit_name or "ho" in unit_name or "main" in unit_name

            grade_name = str(getattr(grade, 'grade_name', '') or getattr(grade, 'name', '') or '').lower()

            grade_level = str(getattr(grade, 'grade_level', '') or '').lower()



            is_grade_2_plus_or_manager = (

                "managerial" in str(category).lower()

                or "grade 2" in grade_name or "grade ii" in grade_name

                or "grade 3" in grade_name or "grade iii" in grade_name

                or "grade 4" in grade_name or "grade iv" in grade_name

                or "grade 5" in grade_name or "grade v" in grade_name

                or "senior" in grade_level or "managerial" in grade_level

            )



            if is_grade_2_plus_or_manager:

                rec.approval_hierarchy_type = "ho_district_grade2_plus"

            elif is_head_office:

                rec.approval_hierarchy_type = "non_managerial_ho"

            else:

                rec.approval_hierarchy_type = "non_managerial_district"



    @api.depends("signature_line_ids.state", "signature_line_ids.is_mandatory")

    def _compute_is_fully_signed(self):

        for rec in self:

            mandatory_lines = rec.signature_line_ids.filtered(lambda l: l.is_mandatory)

            if mandatory_lines and all(l.state == "signed" for l in mandatory_lines):

                rec.is_fully_signed = True

            else:

                rec.is_fully_signed = False



    @api.depends("approval_hierarchy_type", "target_operating_unit_id")

    def _compute_allowed_committee_users(self):

        ConfigModel = self.env["committee.role.config"]

        all_active_users = self.env["res.users"].search([("active", "=", True)])

        for rec in self:

            htype = rec.approval_hierarchy_type or "ho_district_grade2_plus"

            cfg = ConfigModel.get_config_for_hierarchy(htype, scope="transfer")

            ou = rec.target_operating_unit_id

            if cfg:

                c_users = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou)

                p_users = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou)

                s_users = cfg.get_allowed_users_for_role("secretary", operating_unit=ou)

                o_users = cfg.get_allowed_users_for_role("observer", operating_unit=ou)



                rec.allowed_chairperson_user_ids = c_users

                rec.allowed_panel_member_user_ids = p_users

                rec.allowed_secretary_user_ids = s_users

                rec.allowed_observer_user_ids = o_users

            else:

                rec.allowed_chairperson_user_ids = False

                rec.allowed_panel_member_user_ids = False

                rec.allowed_secretary_user_ids = False

                rec.allowed_observer_user_ids = False



    @api.onchange("approval_hierarchy_type", "target_operating_unit_id")

    def _onchange_committee_hierarchy_roles(self):

        """When approval hierarchy or target OU changes, update allowed committee members."""

        ConfigModel = self.env["committee.role.config"]

        htype = self.approval_hierarchy_type or "ho_district_grade2_plus"

        cfg = ConfigModel.get_config_for_hierarchy(htype, scope="transfer")

        ou = self.target_operating_unit_id



        if cfg:

            c_users = cfg.get_allowed_users_for_role("chairperson", operating_unit=ou)

            p_users = cfg.get_allowed_users_for_role("panel_member", operating_unit=ou)

            s_users = cfg.get_allowed_users_for_role("secretary", operating_unit=ou)

            o_users = cfg.get_allowed_users_for_role("observer", operating_unit=ou)



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



    @api.onchange("approval_hierarchy_type", "chairperson_id", "panel_member_id", "secretary_id", "observer_id")

    def _onchange_committee_approver_roles_sync_signatures(self):

        """Immediately populate or update the signature lines in the UI when committee roles change."""

        if self.state in ("waiting_signature", "approved"):

            return

        htype = self.approval_hierarchy_type or "ho_district_grade2_plus"

        sig_cmds = [(5, 0, 0)]



        if htype == "ho_district_grade2_plus":

            c_lbl = _("Chief People and Culture Officer (Chairperson)")

            p_lbl = _("Respective Senior Management (Panel Member)")

            s_lbl = _("Director People Operation Management Directorate (Panel Member & Secretary)")

            o_lbl = _("Labor Representative (Observer)")

        elif htype == "non_managerial_ho":

            c_lbl = _("Director People Operation Management Directorate (Chairperson)")

            p_lbl = _("Head Office / District Director (Panel Member)")

            s_lbl = _("Principal HR (Panel Member & Secretary)")

            o_lbl = _("Labor Representative (Observer)")

        else:

            c_lbl = _("District Director (Chairperson)")

            p_lbl = _("District Division Member (Panel Member)")

            s_lbl = _("Principal HR (Panel Member & Secretary)")

            o_lbl = _("Labor Representative (Observer)")



        if self.chairperson_id:

            sig_cmds.append((0, 0, {

                "user_id": self.chairperson_id.id,

                "role_label": c_lbl,

                "role_type": "chairperson",

                "is_mandatory": True,

                "state": "pending",

            }))

        if self.panel_member_id:

            sig_cmds.append((0, 0, {

                "user_id": self.panel_member_id.id,

                "role_label": p_lbl,

                "role_type": "panel_member",

                "is_mandatory": True,

                "state": "pending",

            }))

        if self.secretary_id:

            sig_cmds.append((0, 0, {

                "user_id": self.secretary_id.id,

                "role_label": s_lbl,

                "role_type": "secretary",

                "is_mandatory": True,

                "state": "pending",

            }))

        if self.observer_id:

            sig_cmds.append((0, 0, {

                "user_id": self.observer_id.id,

                "role_label": o_lbl,

                "role_type": "observer",

                "is_mandatory": False,

                "state": "pending",

            }))



        if len(sig_cmds) > 1:

            self.signature_line_ids = sig_cmds

        else:

            self.signature_line_ids = [(5, 0, 0)]





    @api.onchange("signature_line_ids")
    def _onchange_signature_lines_sync_hierarchy(self):
        if self.env.context.get("syncing_committee_roles") or self.state in ("waiting_signature", "approved"):
            return
        role_to_user = {}
        for line in self.signature_line_ids:
            if line.role_type and line.role_type not in role_to_user:
                role_to_user[line.role_type] = line.user_id

        self.chairperson_id = role_to_user.get("chairperson", False)
        self.panel_member_id = role_to_user.get("panel_member", False)
        self.secretary_id = role_to_user.get("secretary", False)
        self.observer_id = role_to_user.get("observer", False)
    @api.model_create_multi

    def create(self, vals_list):

        records = super().create(vals_list)

        for rec in records:

            if not rec.signature_line_ids and (rec.chairperson_id or rec.panel_member_id or rec.secretary_id):

                rec.action_generate_signature_lines()

            if not rec.transfer_request_ids and rec.target_operating_unit_id and rec.target_job_position_id:

                try:

                    rec.action_refresh_eligible_requests()

                except Exception:

                    pass

        return records



    def write(self, vals):

        is_recruitment_user = (

            self.env.user.has_group('custom_recruitment.group_recruitment_officer') or

            self.env.user.has_group('custom_recruitment.group_recruitment_manager') or

            self.env.user.has_group('custom_recruitment.group_recruitment_administrator') or

            self.env.is_admin()

        )

        for rec in self:

            if rec.state in ('waiting_signature', 'approved') and not self.env.su:

                # Once submitted to digital committee, all fields are locked except committee signatures and committee summary/notes

                allowed_fields = {'signature_line_ids', 'selection_decision', 'message_follower_ids'}

                modified_fields = set(vals.keys())

                if not modified_fields.issubset(allowed_fields) and not (is_recruitment_user and set(vals.keys()).issubset({'state'})):

                    raise UserError(_(

                        "Record is locked: This minutes record has been submitted for digital signatures. "

                        "All settings and committee roles are locked. Only committee signatures and committee notes can be updated."

                    ))



        if not is_recruitment_user and not self.env.su:

            # Committee members are strictly allowed to modify only signature lines and committee notes

            forbidden_fields = set(vals.keys()) - {'signature_line_ids', 'selection_decision'}

            if forbidden_fields:

                raise UserError(_("You are only authorized to provide your digital signature and committee notes on this record."))



        res = super(TransferCommitteeMinutes, self.sudo() if not self.env.is_admin() else self).write(vals)

        role_fields = {"chairperson_id", "panel_member_id", "secretary_id", "observer_id", "approval_hierarchy_type"}

        if role_fields.intersection(vals.keys()):

            for rec in self:

                if rec.state in ("draft", "ranked"):

                    rec.action_generate_signature_lines()

        if "signature_line_ids" in vals and not self.env.context.get("syncing_committee_roles"):

            for rec in self:

                if rec.state in ("draft", "ranked"):

                    role_to_user = {}

                    for line in rec.signature_line_ids:

                        if line.role_type and line.role_type not in role_to_user:

                            role_to_user[line.role_type] = line.user_id.id if line.user_id else False

                    h_vals = {

                        "chairperson_id": role_to_user.get("chairperson", False),

                        "panel_member_id": role_to_user.get("panel_member", False),

                        "secretary_id": role_to_user.get("secretary", False),

                        "observer_id": role_to_user.get("observer", False),

                    }

                    rec.with_context(syncing_committee_roles=True).write(h_vals)

        return res



    def action_generate_signature_lines(self):

        """Populate digital signature lines based on selected approval hierarchy."""

        for rec in self:

            rec.signature_line_ids.unlink()

            htype = rec.approval_hierarchy_type or "ho_district_grade2_plus"

            lines_to_create = []



            if htype == "ho_district_grade2_plus":

                if rec.chairperson_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.chairperson_id.id,

                        "role_label": _("Chief People and Culture Officer (Chairperson)"),

                        "role_type": "chairperson",

                        "is_mandatory": True,

                    })

                if rec.panel_member_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.panel_member_id.id,

                        "role_label": _("Respective Senior Management (Panel Member)"),

                        "role_type": "panel_member",

                        "is_mandatory": True,

                    })

                if rec.secretary_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.secretary_id.id,

                        "role_label": _("Director People Operation Management Directorate (Panel Member & Secretary)"),

                        "role_type": "secretary",

                        "is_mandatory": True,

                    })



            elif htype == "non_managerial_ho":

                if rec.chairperson_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.chairperson_id.id,

                        "role_label": _("Director People Operation Management Directorate (Chairperson)"),

                        "role_type": "chairperson",

                        "is_mandatory": True,

                    })

                if rec.panel_member_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.panel_member_id.id,

                        "role_label": _("Head Office / District Director (Panel Member)"),

                        "role_type": "panel_member",

                        "is_mandatory": True,

                    })

                if rec.secretary_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.secretary_id.id,

                        "role_label": _("Principal HR (Panel Member & Secretary)"),

                        "role_type": "secretary",

                        "is_mandatory": True,

                    })

                if rec.observer_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.observer_id.id,

                        "role_label": _("Labor Representative (Observer)"),

                        "role_type": "observer",

                        "is_mandatory": False,  # Optional to sign

                    })



            elif htype == "non_managerial_district":

                if rec.chairperson_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.chairperson_id.id,

                        "role_label": _("District Director (Chairperson)"),

                        "role_type": "chairperson",

                        "is_mandatory": True,

                    })

                if rec.panel_member_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.panel_member_id.id,

                        "role_label": _("District Division Member (Panel Member)"),

                        "role_type": "panel_member",

                        "is_mandatory": True,

                    })

                if rec.secretary_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.secretary_id.id,

                        "role_label": _("Principal HR (Panel Member & Secretary)"),

                        "role_type": "secretary",

                        "is_mandatory": True,

                    })

                if rec.observer_id:

                    lines_to_create.append({

                        "minutes_id": rec.id,

                        "user_id": rec.observer_id.id,

                        "role_label": _("Labor Representative (Observer)"),

                        "role_type": "observer",

                        "is_mandatory": False,  # Optional to sign

                    })



            if lines_to_create:

                self.env["transfer.committee.signature"].create(lines_to_create)



    def action_submit_for_signatures(self):

        """Validate required committee role assignments, generate signature lines,

        dispatch notifications via Chatter, Email, Discuss DM, and schedule Systray activities."""

        model_id = self.env.ref('custom_recruitment.model_transfer_committee_minutes', raise_if_not_found=False)

        if not model_id:

            model_id = self.env['ir.model'].search([('model', '=', 'transfer.committee.minutes')], limit=1)

        todo_act_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

        committee_group = self.env.ref('custom_recruitment.group_recruitment_approval_committee', raise_if_not_found=False)



        for rec in self:

            if not rec.chairperson_id or not rec.secretary_id or not rec.panel_member_id:

                raise UserError(_(

                    "Please assign all mandatory committee roles (Chairperson, Panel Member, and Secretary) "

                    "before submitting for digital signatures."

                ))

            if not rec.ranking_line_ids:
                raise UserError(_("Cannot submit Transfer Committee Minutes without candidate rankings."))

            selected = rec.ranking_line_ids.filtered(lambda l: l.selection_decision == 'selected')
            if not selected:
                raise UserError(_("Cannot submit Transfer Committee Minutes! No candidate is selected or passed. Please evaluate and rank candidates before submitting."))

            rec.action_generate_signature_lines()

            rec.state = "waiting_signature"



            # Auto-assign committee security group to assigned users so they have access

            assigned_users = rec.signature_line_ids.mapped('user_id')

            if committee_group and assigned_users:

                current_uids = committee_group.user_ids.ids if hasattr(committee_group, 'user_ids') else []

                users_to_add = assigned_users.filtered(lambda u: u.id not in current_uids)

                if users_to_add:

                    try:

                        committee_group.sudo().write({'user_ids': [(4, u.id) for u in users_to_add]})

                    except Exception as e:

                        _logger.warning("Could not auto-assign group_recruitment_approval_committee: %s", e)



            notified_partners = []

            for sig in rec.signature_line_ids:

                if sig.user_id and sig.state == 'pending':

                    if sig.user_id.partner_id:

                        notified_partners.append(sig.user_id.partner_id.id)



                    # Schedule Activity Task for Committee Member in Odoo Systray / Inbox

                    existing_act = self.env['mail.activity'].sudo().search([

                        ('res_model', '=', 'transfer.committee.minutes'),

                        ('res_id', '=', rec.id),

                        ('user_id', '=', sig.user_id.id)

                    ], limit=1)

                    if not existing_act and todo_act_type and model_id:

                        self.env['mail.activity'].sudo().create({

                            'activity_type_id': todo_act_type.id,

                            'note': _("Transfer Committee Minutes %s requires your digital signature.") % rec.name,

                            'summary': _("Digitally Sign Transfer Minutes %s") % rec.name,

                            'user_id': sig.user_id.id,

                            'res_model_id': model_id.id,

                            'res_id': rec.id,

                            'date_deadline': fields.Date.context_today(self),

                        })



            # Subscribe partners as followers

            if notified_partners:

                try:

                    rec.sudo().message_subscribe(partner_ids=notified_partners)

                except Exception:

                    pass



            # Send targeted Odoo Discuss message notification ONLY to committee members' partners

            notif_msg = None

            if notified_partners:

                try:

                    notif_msg = rec.sudo().message_notify(

                        partner_ids=notified_partners,

                        subject=_("Pending Digital Signature: Transfer Committee Minutes %s") % rec.name,

                        body=_(

                            "Dear Committee Member,\n\n"

                            "Transfer Committee Minutes %s is ready for your digital signature.\n\n"

                            "Please review the transfer ranking matrix and provide your digital signature under Committee Digital Signatures."

                        ) % rec.name,

                        email_layout_xmlid="mail.mail_notification_light",

                    )

                except Exception:

                    pass



            mentions_html = ' '.join([

                f'<a href="#" data-oe-model="res.partner" data-oe-id="{p.id}">@{p.name}</a>'

                for p in rec.signature_line_ids.mapped('user_id.partner_id')

            ])

            posted_msg = rec.sudo().message_post(

                body=_(

                    "Digital Signature notification dispatched to committee members: %s"

                    "Transfer Committee Minutes ranking finalized and submitted for digital signatures. "

                    "Please review and sign under the Committee Digital Signatures tab."

                ) % mentions_html,

                partner_ids=notified_partners,

                message_type='comment',

                subtype_xmlid="mail.mt_comment",

            )



            # Enforce Discuss Inbox delivery

            all_msg_ids = [m.id for m in (notif_msg, posted_msg) if m]

            if all_msg_ids and notified_partners:

                notifs = self.env['mail.notification'].sudo().search([

                    ('mail_message_id', 'in', all_msg_ids),

                    ('res_partner_id', 'in', notified_partners),

                ])

                if notifs:

                    notifs.sudo().write({

                        'notification_type': 'inbox',

                        'notification_status': 'sent',

                        'is_read': False,

                    })



            # Send 1-on-1 Discuss DM

            if 'discuss.channel' in self.env:

                for sig in rec.signature_line_ids.filtered(lambda l: l.state == 'pending' and l.user_id):

                    user = sig.user_id

                    if user.partner_id and user.id != self.env.user.id:

                        try:

                            chat_channel = self.env['discuss.channel'].sudo()._get_or_create_chat(

                                partners_to=[self.env.user.partner_id.id, user.partner_id.id]

                            )

                            if chat_channel:
                                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                                min_url = f"{base_url.rstrip('/')}/web#id={rec.id}&model=transfer.committee.minutes&view_type=form" if base_url else f"/web#id={rec.id}&model=transfer.committee.minutes&view_type=form"
                                dm_msg = chat_channel.sudo().message_post(
                                    body=Markup(
                                        f"<p>Dear <b>{escape(user.name)}</b> Greetings,</p>"
                                        f"<p>The Transfer Committee Minutes <b>{escape(rec.name or '')}</b> is ready for you to put your digital signature.</p>"
                                        f"<p>Please review the ranking and submit your signature under Committee Digital Signatures:</p>"
                                        f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                                        f"<a href='{min_url}' target='_blank' style='display: inline-block; padding: 9px 18px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                                        f"👉 Open Transfer Minute to Sign"
                                        f"</a>"
                                        f"</div>"
                                    ),
                                    message_type='comment',
                                    subtype_xmlid='mail.mt_comment',
                                )

                                dm_notifs = self.env['mail.notification'].sudo().search([

                                    ('mail_message_id', '=', dm_msg.id),

                                    ('res_partner_id', '=', user.partner_id.id),

                                ])

                                if dm_notifs:

                                    dm_notifs.sudo().write({

                                        'notification_type': 'inbox',

                                        'notification_status': 'sent',

                                        'is_read': False,

                                    })

                        except Exception as e:

                            _logger.warning("Could not send Discuss DM to %s: %s", user.name, e)



        return {

            'type': 'ir.actions.client',

            'tag': 'display_notification',

            'params': {

                'title': _('Digital Signatures Dispatched'),

                'message': _('Digital signature requests and notifications have been dispatched to all committee members via Discuss, Systray, and Email.'),

                'type': 'success',

                'sticky': False,

                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            }

        }



    def action_dispatch_digital_signatures(self):

        """Dispatch digital signature requests to all committee members via Discuss, Systray, and Email."""

        return self.action_submit_for_signatures()



    @api.depends("target_operating_unit_id", "target_job_position_id")

    def _compute_allowed_target_units_and_positions(self):

        """Compute allowed Target Operating Units and Target Job Positions based on

        active, eligible, unfinalized transfer requests."""

        TransferRequest = self.env["employee.transfer.request"]

        base_domain = [

            ("state", "in", ["under_review", "approved"]),

            ("status_group", "=", "active"),

            ("eligibility_status", "=", "eligible"),

            ("is_committee_selected", "=", False),

        ]

        all_requests = TransferRequest.search(base_domain)



        for rec in self:

            # 1. Allowed Target Operating Units

            if rec.target_job_position_id:

                pos_reqs = all_requests.filtered(

                    lambda r: r.target_job_position_id.id == rec.target_job_position_id.id

                )

                rec.allowed_target_operating_unit_ids = pos_reqs.mapped("requested_operating_unit_id")

            else:

                rec.allowed_target_operating_unit_ids = all_requests.mapped("requested_operating_unit_id")



            # 2. Allowed Target Job Positions

            if rec.target_operating_unit_id:

                ou_reqs = all_requests.filtered(

                    lambda r: r.requested_operating_unit_id.id == rec.target_operating_unit_id.id

                )

                rec.allowed_target_job_position_ids = ou_reqs.mapped("target_job_position_id")

            else:

                rec.allowed_target_job_position_ids = all_requests.mapped("target_job_position_id")



    @api.onchange("target_operating_unit_id", "target_job_position_id")

    def _onchange_target_ou_position(self):

        """Auto-populate transfer_request_ids and dynamically update selection domains

        between Target Operating Unit and Target Job Position bidirectionally."""

        base_domain = [

            ("state", "in", ["under_review", "approved"]),

            ("status_group", "=", "active"),

            ("eligibility_status", "=", "eligible"),

            ("is_committee_selected", "=", False),

        ]

        all_requests = self.env["employee.transfer.request"].search(base_domain)



        # Dynamic domains for OU and Job Position

        if self.target_job_position_id:

            valid_ou_ids = all_requests.filtered(

                lambda r: r.target_job_position_id.id == self.target_job_position_id.id

            ).mapped("requested_operating_unit_id").ids

            if self.target_operating_unit_id and self.target_operating_unit_id.id not in valid_ou_ids:

                self.target_operating_unit_id = False

        else:

            valid_ou_ids = all_requests.mapped("requested_operating_unit_id").ids



        if self.target_operating_unit_id:

            valid_job_ids = all_requests.filtered(

                lambda r: r.requested_operating_unit_id.id == self.target_operating_unit_id.id

            ).mapped("target_job_position_id").ids

            if self.target_job_position_id and self.target_job_position_id.id not in valid_job_ids:

                self.target_job_position_id = False

        else:

            valid_job_ids = all_requests.mapped("target_job_position_id").ids



        # Re-evaluate allowed fields

        self.allowed_target_operating_unit_ids = self.env["operating.unit"].browse(valid_ou_ids)

        self.allowed_target_job_position_ids = self.env["hr.job"].browse(valid_job_ids)



        # Auto-populate transfer_request_ids when both OU and Job are selected

        req_domain = [

            ("state", "in", ["under_review", "approved"]),

            ("status_group", "=", "active"),

            ("eligibility_status", "=", "eligible"),

            ("is_committee_selected", "=", False),

        ]

        if self.target_operating_unit_id and self.target_job_position_id:

            req_domain.extend([

                ("requested_operating_unit_id", "=", self.target_operating_unit_id.id),

                ("target_job_position_id", "=", self.target_job_position_id.id),

            ])

            self.transfer_request_ids = self.env["employee.transfer.request"].search(req_domain)

        else:

            self.transfer_request_ids = self.env["employee.transfer.request"].browse()



        return {

            "domain": {

                "target_operating_unit_id": [("id", "in", valid_ou_ids)],

                "target_job_position_id": [("id", "in", valid_job_ids)],

                "transfer_request_ids": req_domain,

            }

        }



    @api.model_create_multi

    def create(self, vals_list):

        for vals in vals_list:

            if not vals.get("name") or vals.get("name") == _("New"):

                vals["name"] = self.env["ir.sequence"].next_by_code("transfer.committee.minutes") or _("New")

            if 'target_vacancy_id' not in vals:

                vals['target_vacancy_id'] = False

        return super().create(vals_list)



    @api.constrains('target_vacancy_id', 'transfer_request_ids')

    def _check_vacancy_consistency(self):

        """Validate that transfer requests match the vacancy setting"""

        for rec in self:

            if rec.transfer_request_ids:

                vacancy_requests = rec.transfer_request_ids.filtered(

                    lambda r: r.target_vacancy_id

                )

                direct_requests = rec.transfer_request_ids.filtered(

                    lambda r: not r.target_vacancy_id

                )

                if vacancy_requests and direct_requests:

                    pass  # Allow mixing both types



    def action_refresh_eligible_requests(self):

        """Manually re-sync transfer_request_ids with all eligible requests matching

        the current Target Operating Unit and Target Job Position."""

        for rec in self:

            if not rec.target_operating_unit_id or not rec.target_job_position_id:

                raise UserError(_("Please select both Target Operating Unit and Target Job Position first."))

            domain = [

                ('state', 'in', ['under_review', 'approved']),

                ('status_group', '=', 'active'),

                ('eligibility_status', '=', 'eligible'),

                ('is_committee_selected', '=', False),

                ('requested_operating_unit_id', '=', rec.target_operating_unit_id.id),

                ('target_job_position_id', '=', rec.target_job_position_id.id),

            ]

            matching_requests = self.env['employee.transfer.request'].search(domain)

            rec.transfer_request_ids = matching_requests



        return {

            'type': 'ir.actions.client',

            'tag': 'display_notification',

            'params': {

                'title': _('Requests Refreshed'),

                'message': _('Eligible transfer requests have been reloaded.'),

                'type': 'success',

                'sticky': False,

                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },

        }



    def action_compute_ranking(self):

        """ Compute the weighted Transfer Suitability Score for every eligible transfer request,

        apply discipline deduction, and populate the ranked list.

        """

        ICPSudo = self.env["ir.config_parameter"].sudo()

        try:

            w_pms = float(ICPSudo.get_param("custom_recruitment.transfer_weight_pms", "30.0")) / 100.0

        except ValueError:

            w_pms = 0.30

        try:

            w_app = float(ICPSudo.get_param("custom_recruitment.transfer_weight_application_date", "20.0")) / 100.0

        except ValueError:

            w_app = 0.20

        try:

            w_exp = float(ICPSudo.get_param("custom_recruitment.transfer_weight_experience", "20.0")) / 100.0

        except ValueError:

            w_exp = 0.20

        try:

            w_loc = float(ICPSudo.get_param("custom_recruitment.transfer_weight_service_location", "20.0")) / 100.0

        except ValueError:

            w_loc = 0.20

        try:

            w_rec = float(ICPSudo.get_param("custom_recruitment.transfer_weight_recommendation", "10.0")) / 100.0

        except ValueError:

            w_rec = 0.10



        for rec in self:

            if not rec.transfer_request_ids:

                if rec.target_operating_unit_id and rec.target_job_position_id:

                    domain = [

                        ('state', 'in', ['under_review', 'approved']),

                        ('status_group', '=', 'active'),

                        ('eligibility_status', '=', 'eligible'),

                        ('is_committee_selected', '=', False),

                        ('requested_operating_unit_id', '=', rec.target_operating_unit_id.id),

                        ('target_job_position_id', '=', rec.target_job_position_id.id),

                    ]

                    matching_requests = self.env['employee.transfer.request'].search(domain)

                    rec.transfer_request_ids = matching_requests



            if not rec.transfer_request_ids:

                unit_name = rec.target_operating_unit_id.name or _('Selected Unit')

                pos_name = rec.target_job_position_id.name or _('Selected Position')

                raise UserError(_(

                    "No transfer requests found for Target Operating Unit '%s' and Job Position '%s'. "

                    "Please ensure at least one eligible transfer request is available under 'Transfer Requests Considered' "

                    "before computing the ranking."

                ) % (unit_name, pos_name))



            # Filter eligible requests that have been reviewed (in 'under_review' or 'approved' state)

            eligible_requests = rec.transfer_request_ids.filtered(

                lambda r: r.eligibility_status == "eligible"

                and r.state in ("under_review", "approved")

                and not r.is_committee_selected

            )

            if not eligible_requests:

                draft_or_submitted = rec.transfer_request_ids.filtered(lambda r: r.state in ("draft", "submitted"))

                if draft_or_submitted:

                    names = ", ".join(draft_or_submitted.mapped("name"))

                    raise UserError(_(

                        "Cannot compute ranking yet! The following transfer request(s) must be reviewed first: %s. "

                        "Please advance them to 'Under Review' or 'Approved' before committee ranking."

                    ) % names)

                unit_name = rec.target_operating_unit_id.name or _('Selected Unit')

                pos_name = rec.target_job_position_id.name or _('Selected Position')

                raise UserError(_(

                    "None of the transfer requests added to this committee are eligible and reviewed for Target Operating Unit '%s' and Job Position '%s'."

                ) % (unit_name, pos_name))



            rec.ranking_line_ids.unlink()



            # --- Determine number of open slots for auto-selection ---------

            slots = rec.available_slots or 1



            # --- Normalize each factor across the pool (0-100 scale) ---------

            dates = eligible_requests.mapped("request_date")

            min_date = min(dates)

            max_date = max(dates)

            date_span = (max_date - min_date).days or 1



            max_experience = max(eligible_requests.mapped("total_experience_years")) or 1.0

            max_location_years = max(eligible_requests.mapped("service_years_current_location")) or 1.0



            scored = []

            for req in eligible_requests:

                days_from_earliest = (req.request_date - min_date).days

                application_score = 100.0 * (1 - (days_from_earliest / date_span))



                experience_score = (

                    100.0 * (req.total_experience_years / max_experience)

                    if max_experience else 0.0

                )

                location_score = (

                    100.0 * (req.service_years_current_location / max_location_years)

                    if max_location_years else 0.0

                )                # Auto-fetch PMS score from hr.version table for this employee

                ver = self.env["hr.version"].search([("employee_id", "=", req.employee_id.id)], order="id desc", limit=1)

                pms_score = ver.pms_score if (ver and ver.pms_score) else (req.pms_score or 0.0)



                recommendation_score = req.supervisor_recommendation_score or 0.0

                deduction = req.discipline_deduction_percent or 0.0



                weighted_total = (

                        application_score * w_app

                        + experience_score * w_exp

                        + location_score * w_loc

                        + pms_score * w_pms

                        + recommendation_score * w_rec

                )

                final_score = max(0.0, weighted_total - deduction)



                scored.append((

                    req,                    # [0]

                    application_score,      # [1]

                    experience_score,       # [2]

                    location_score,         # [3]

                    pms_score,              # [4]

                    recommendation_score,   # [5]

                    deduction,              # [6]

                    final_score,            # [7]

                ))



            scored.sort(

                key=lambda t: (

                    round(t[7], 4),

                    1 if getattr(t[0].employee_id, "gender", "") == "female" else 0,

                    -((t[0].request_date - min_date).days),

                    t[0].total_experience_years or 0.0,

                    t[4] or 0.0,

                ),

                reverse=True,

            )



            for idx, (req, app_s, exp_s, loc_s, pms_s, rec_s, deduction, final_s) in enumerate(scored, start=1):

                self.env["transfer.committee.minutes.line"].create({

                    "minutes_id": rec.id,

                    "rank": idx,

                    "transfer_request_id": req.id,

                    "application_date_score": round(app_s, 2),

                    "experience_score": round(exp_s, 2),

                    "service_location_score": round(loc_s, 2),

                    "pms_score": round(pms_s, 2),

                    "recommendation_score": round(rec_s, 2),

                    "discipline_deduction_percent": round(deduction, 2),

                    "final_score": round(final_s, 2),

                    "selection_decision": "selected" if idx <= slots else "not_selected",

                })

                req.transfer_suitability_score = round(final_s, 2)



            rec.state = "ranked"

            rec.message_post(

                body=_("Transfer ranking computed. %d candidates ranked. "

                       "Top %d auto-marked as Selected based on %d open slot(s).")

                     % (len(scored), min(slots, len(scored)), slots)

            )



        return {

            'type': 'ir.actions.client',

            'tag': 'display_notification',

            'params': {

                'title': _('Ranking Computed'),

                'message': _('Transfer candidates have been ranked successfully.'),

                'type': 'success',

                'sticky': False,

                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },

        }



    def action_approve_minutes(self):

        """Approve the minutes and auto-approve all transfer requests for selected candidates,

        STRICTLY validating that all mandatory digital signatures have been obtained."""

        for rec in self:

            if rec.state not in ("ranked", "waiting_signature"):

                raise UserError(_("Please compute the ranking and collect signatures before approving the minutes."))



            # Strict Digital Approval Constraint: Check mandatory signatures

            unsigned_mandatory = rec.signature_line_ids.filtered(

                lambda l: l.is_mandatory and l.state != "signed"

            )

            if unsigned_mandatory or not rec.signature_line_ids:

                pending_details = ", ".join(

                    "%s (%s)" % (l.role_label, l.user_id.name or _("Unassigned")) for l in unsigned_mandatory

                ) if unsigned_mandatory else _("No signature lines initialized")

                raise ValidationError(_(

                    "Cannot approve transfer committee minutes! Digital signatures are pending for mandatory roles: %s. "

                    "All required committee members must digitally sign before HR can complete the transfer."

                ) % pending_details)



            rec.state = "approved"

            rec.message_post(body=_("Transfer Committee Minutes digitally approved by all mandatory committee members."))



            selected_lines = rec.ranking_line_ids.filtered(

                lambda l: l.selection_decision == "selected"

            )



            # Strict Segregation of Duties Check: Ensure the user approving committee minutes did NOT perform the initial review for any selected request

            for line in selected_lines:

                transfer_req = line.transfer_request_id

                if not transfer_req:

                    continue

                if transfer_req.reviewed_by_user_id and transfer_req.reviewed_by_user_id.id == self.env.user.id:

                    raise ValidationError(_(

                        "Segregation of Duties Violation: You ('%s') clicked 'Start Review' for transfer request '%s' (Candidate: %s). "

                        "You are strictly prohibited from approving committee minutes selecting this candidate. "

                        "To enforce Segregation of Duties in the approval hierarchy, another committee member / HR user must finalize and approve the minutes."

                    ) % (self.env.user.name, transfer_req.name, transfer_req.employee_name))

                if transfer_req.employee_id.user_id and transfer_req.employee_id.user_id.id == self.env.user.id:

                    raise ValidationError(_(

                        "Segregation of Duties Violation: You ('%s') are the requesting employee for '%s'. "

                        "You cannot approve committee minutes selecting your own transfer."

                    ) % (self.env.user.name, transfer_req.name))



            # Approve selected requests and dispatch acceptance offers (without prematurely completing the transfer)

            for line in selected_lines:

                transfer_req = line.transfer_request_id

                if not transfer_req:

                    continue

                if transfer_req.state in ("draft", "submitted", "under_review"):

                    transfer_req.sudo().write({

                        "state": "approved",

                        "acceptance_status": "pending",

                        "is_committee_selected": True,

                    })

                elif transfer_req.state == "approved":

                    transfer_req.sudo().write({

                        "acceptance_status": "pending",

                        "is_committee_selected": True,

                    })



                # Ensure lateral transfer letter is initialized in draft

                letter = transfer_req.sudo()._ensure_transfer_letter()

                if letter and not letter.minutes_id:

                    letter.sudo().write({"minutes_id": rec.id})

                if letter:

                    letter.sudo().write({

                        "acceptance_status": "pending",

                        "state": "draft",

                    })



                # Dispatch acceptance offer email & portal activity to selected candidate

                rec._send_candidate_acceptance_offer(transfer_req)



            # Mark all unselected eligible candidates as reserved

            reserve_lines = rec.ranking_line_ids.filtered(lambda l: l.selection_decision == "not_selected")

            if reserve_lines:

                reserve_lines.with_context(allow_reserve_replacement=True).sudo().write({

                    "selection_decision": "reserved"

                })



            # Return QWeb PDF report action for the official Ethiopian Amharic Minute (ቃለ-ጉባዔ)

            report_act = self.env.ref("custom_recruitment.action_report_transfer_minute", raise_if_not_found=False)

            if report_act:

                return report_act.report_action(rec)



        return {

            'type': 'ir.actions.client',

            'tag': 'display_notification',

            'params': {

                'title': _('Minutes Approved'),

                'message': _('Transfer Committee Minutes approved, Minute document generated, and acceptance offers dispatched.'),

                'type': 'success',

                'sticky': False,

                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },

        }



    def action_generate_all_transfer_letters(self):

        """Generates Lateral Transfer Letters in batch for all selected transfer candidates."""

        self.ensure_one()

        selected_lines = self.ranking_line_ids.filtered(lambda l: l.selection_decision == 'selected')

        if not selected_lines:

            raise UserError(_("No selected candidates found in this committee minute to generate transfer letters for."))



        letters_created = 0

        letter_ids = []

        for line in selected_lines:

            req = line.transfer_request_id

            if req:

                letter = req._ensure_transfer_letter()

                if not letter.minutes_id:

                    letter.minutes_id = self.id

                letters_created += 1

                letter_ids.append(letter.id)



        self.message_post(

            body=_("%d Lateral Transfer Letter(s) generated for selected candidates.") % letters_created

        )



        return {

            'name': _('Lateral Transfer Letters'),

            'type': 'ir.actions.act_window',

            'res_model': 'transfer.letter',

            'view_mode': 'list,form',

            'domain': [('id', 'in', letter_ids)],

            'target': 'current',

        }





class TransferCommitteeSignature(models.Model):

    def get_formatted_name(self):
        self.ensure_one()
        user = self.user_id
        emp = False
        if hasattr(user, 'employee_id') and user.employee_id:
            emp = user.employee_id
        elif hasattr(user, 'employee_ids') and user.employee_ids:
            emp = user.employee_ids[0]
        gender = (getattr(emp, 'gender', '') or '').lower() if emp else ''
        sal = "ወ/ት" if gender in ('female', 'f') else "አቶ"
        name = (user.name or "").strip()
        for p in ("አቶ", "ወ/ት", "ወ/ሮ", "ወ/ሪት", "Ato", "W/t", "W/ro", "W/rit", "Mr.", "Mrs.", "Ms."):
            if name.startswith(p + " ") or name.startswith(p + "."):
                name = name[len(p):].lstrip(". ")
                break
        return f"{sal} {name}"

    def get_role_amharic(self):

        self.ensure_one()

        mapping = {

            "chairperson": "ሰብሳቢ",

            "panel_member": "አባል",

            "secretary": "አባል እና ፀሐፊ",

            "observer": "የሰራተኛ ተወካይ (ታዛቢ)",

        }

        if self.role_type in mapping:

            return mapping[self.role_type]

        lbl = (self.role_label or "").lower()

        if "chair" in lbl or "ሰብሳቢ" in lbl:

            return "ሰብሳቢ"

        elif "secretary" in lbl or "ፀሐፊ" in lbl:

            return "አባል እና ፀሐፊ"

        elif "observer" in lbl or "ታዛቢ" in lbl:

            return "የሰራተኛ ተወካይ (ታዛቢ)"

        return "አባል"



    _name = "transfer.committee.signature"

    _description = "Transfer Committee Digital Signature"

    _order = "id"



    minutes_id = fields.Many2one(

        "transfer.committee.minutes", string="Committee Minutes",

        required=True, ondelete="cascade"

    )

    user_id = fields.Many2one("res.users", string="Signatory User", required=True)

    role_label = fields.Char(string="Role Title", required=True)

    role_type = fields.Selection([

        ("chairperson", "Chairperson"),

        ("panel_member", "Panel Member"),

        ("secretary", "Panel Member & Secretary"),

        ("observer", "Labor Representative (Observer)"),

    ], string="Role Type", required=True)



    is_mandatory = fields.Boolean(

        string="Mandatory Signature", default=True,

        help="If True, approval cannot complete without this signature. "

             "Labor Representatives / Observers are optional."

    )

    digital_signature = fields.Binary(string="Digital Signature", copy=False)

    signed_on = fields.Datetime(string="Signed Date & Time", readonly=True, copy=False)

    state = fields.Selection([

        ("pending", "Pending Signature"),

        ("signed", "Signed"),

    ], string="Status", default="pending", required=True, copy=False)

    comments = fields.Text(string="Remarks / Comments")



    def _generate_digital_signature_badge(self):

        name = self.user_id.name or "Committee Member"

        role = self.role_label or self.role_type or "Committee Member"

        date_str = fields.Datetime.to_string(fields.Datetime.now())

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="300" height="100" viewBox="0 0 300 100">

            <rect width="100%" height="100%" fill="#f8f9fa" rx="6" stroke="#4A2E1A" stroke-width="2"/>

            <text x="15" y="32" font-family="'Brush Script MT', 'Dancing Script', cursive, Arial" font-size="22" font-weight="bold" fill="#003366">{name}</text>

            <line x1="15" y1="42" x2="285" y2="42" stroke="#003366" stroke-width="1.5" stroke-dasharray="4"/>

            <text x="15" y="60" font-family="Helvetica, Arial, sans-serif" font-size="11" font-weight="bold" fill="#4A2E1A">Digitally Signed &amp; Authenticated</text>

            <text x="15" y="76" font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#444444">Role: {role} | Date: {date_str}</text>

            <text x="15" y="90" font-family="Helvetica, Arial, sans-serif" font-size="9" font-weight="bold" fill="#28a745">✔ Verified ERP Digital Signature</text>

        </svg>'''

        return base64.b64encode(svg.encode('utf-8'))



    def write(self, vals):

        """Strict signature enforcement: Only the assigned user (user_id) can sign or modify their signature."""

        has_sig = bool(vals.get("digital_signature"))

        if (has_sig or "digital_signature" in vals or vals.get("state") == "signed") and not self.env.su:

            for line in self:

                if line.user_id and line.user_id != self.env.user:

                    raise UserError(_(

                        "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "

                        "You are logged in as '%s'. Only '%s' can digitally sign this line."

                    ) % (line.role_label, line.user_id.name, self.env.user.name, line.user_id.name))



        if has_sig and vals.get("state") != "signed":

            vals["state"] = "signed"

            vals["signed_on"] = fields.Datetime.now()



        res = super(TransferCommitteeSignature, self.sudo()).write(vals)



        # If signed, complete activity and log chatter using sudo

        if has_sig or vals.get("state") == "signed":

            for line in self:

                activities = self.env['mail.activity'].sudo().search([

                    ('res_model', '=', 'transfer.committee.minutes'),

                    ('res_id', '=', line.minutes_id.id),

                    ('user_id', '=', line.user_id.id),

                ])

                for act in activities:

                    try:

                        act.sudo().action_feedback(feedback=_("Digitally signed as %s") % line.role_label)

                    except Exception as e:

                        _logger.warning("Could not close activity: %s", e)



                try:

                    line.minutes_id.sudo().message_post(

                        body=_("Digital signature recorded for %s (%s).") % (line.role_label, line.user_id.name),

                        message_type='comment',

                        subtype_xmlid='mail.mt_comment',

                    )

                except Exception as e:

                    _logger.warning("Could not post chatter: %s", e)



                # Check if all mandatory signatures are now signed

                unsigned_mandatory = line.minutes_id.signature_line_ids.filtered(

                    lambda l: l.is_mandatory and l.state != 'signed'

                )

                if not unsigned_mandatory:

                    try:

                        line.minutes_id.sudo().message_post(

                            body=_(

                                "<p><b>All mandatory digital signatures obtained!</b></p>"

                                "<p>The Transfer Committee Minutes record is now ready for final approval.</p>"

                            ),

                            message_type='comment',

                            subtype_xmlid='mail.mt_comment',

                        )

                    except Exception as e:

                        _logger.warning("Could not post all-signed message: %s", e)

        return res



    def action_sign_digitally(self):

        """Open the Digital Signature Modal Wizard strictly for the designated signatory user."""

        self.ensure_one()

        if self.user_id != self.env.user and not self.env.su:

            raise UserError(_(

                "Unauthorized Signature Access: The signature line for '%s' is strictly designated for '%s'. "

                "You are currently logged in as '%s'. Only '%s' can digitally sign this line."

            ) % (self.role_label, self.user_id.name, self.env.user.name, self.user_id.name))

        return {
            'name': _('Committee Digital Signature - %s') % (self.role_label or 'Sign'),
            'type': 'ir.actions.act_window',
            'res_model': 'committee.minute.sign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': self._name,
                'active_id': self.id,
            }
        }


class TransferCommitteeMinutesLine(models.Model):

    _name = "transfer.committee.minutes.line"

    _description = "Transfer Committee Minutes - Ranked Candidate"

    _order = "rank"



    active = fields.Boolean(default=True)



    @api.model_create_multi

    def create(self, vals_list):

        for vals in vals_list:

            if vals.get("minutes_id"):

                minutes = self.env["transfer.committee.minutes"].browse(vals["minutes_id"])

                if minutes.state in ("waiting_signature", "approved"):

                    raise ValidationError(_("Cannot add candidates to Transfer Committee Minutes that are waiting for signatures or already approved!"))

        return super().create(vals_list)



    def write(self, vals):

        for line in self:

            if line.minutes_id.state == "approved" and not self.env.context.get("allow_reserve_replacement"):

                raise ValidationError(_("Cannot modify candidate rankings or decisions on approved Transfer Committee Minutes!"))

            if line.minutes_id.state == "waiting_signature" and "selection_decision" in vals and not self.env.context.get("allow_reserve_replacement"):

                raise ValidationError(_("Selection decisions cannot be modified once committee minutes are submitted for digital signatures!"))

        return super().write(vals)



    def get_formatted_employee_name(self):
        self.ensure_one()
        emp = self.employee_id or (self.transfer_request_id and self.transfer_request_id.employee_id)
        if not emp:
            return ""
        name = (emp.name or "").strip()
        gender = (getattr(emp, 'gender', '') or '').lower()
        sal = "ወ/ት" if gender in ('female', 'f') else "አቶ"
        for p in ("አቶ", "ወ/ት", "ወ/ሮ", "ወ/ሪት", "Ato", "W/t", "W/ro", "W/rit", "Mr.", "Mrs.", "Ms."):
            if name.startswith(p + " ") or name.startswith(p + "."):
                name = name[len(p):].lstrip(". ")
                break
        return f"{sal} {name}"

    def get_decision_amharic(self):

        self.ensure_one()

        if self.selection_decision == 'selected':

            return "ተመርጠዋል"

        elif self.selection_decision == 'reserved':

            return "ተጠባባቂ"

        elif self.selection_decision == 'declined':

            return "ውድቅ አድርገዋል"

        elif self.selection_decision == 'not_selected':

            return "ተጠባባቂ" if self.rank and self.rank > (self.minutes_id.available_slots or 1) else "አልተመረጡም"

        return ""

    _order = "rank"



    minutes_id = fields.Many2one("transfer.committee.minutes", string="Minutes", required=True, ondelete="cascade")

    rank = fields.Integer(string="Rank")

    transfer_request_id = fields.Many2one("employee.transfer.request", string="Transfer Request", required=True)

    employee_id = fields.Many2one(related="transfer_request_id.employee_id", string="Employee", store=True)

    employee_gender = fields.Selection(

        related="transfer_request_id.employee_id.gender",

        string="Gender", store=True,

    )

    service_years_current_position = fields.Float(

        related="transfer_request_id.service_years_current_position",

        string="Years in Current Position",

        readonly=True,

    )

    service_years_current_location = fields.Float(

        related="transfer_request_id.service_years_current_location",

        string="Years in Current Location",

        readonly=True,

    )



    application_date_score = fields.Float(string="Application Date Score (20%)")

    experience_score = fields.Float(string="Total Experience Score (20%)")

    service_location_score = fields.Float(string="Service in Location Score (20%)")

    pms_score = fields.Float(string="PMS Score (30%)", compute="_compute_pms_score", store=True, readonly=False)

    recommendation_score = fields.Float(string="Recommendation Score (10%)")

    discipline_deduction_percent = fields.Float(string="Discipline Deduction (%)")

    final_score = fields.Float(string="Final Transfer Suitability Score")



    selection_decision = fields.Selection(

        [

            ("selected", "Selected"),

            ("reserved", "Reserved / Waiting List"),

            ("not_selected", "Not Selected"),

            ("declined", "Declined / Refused"),

        ],

        string="Decision", default="not_selected",

    )



    @api.depends("transfer_request_id", "employee_id")

    def _compute_pms_score(self):

        for line in self:

            emp = line.employee_id or (line.transfer_request_id and line.transfer_request_id.employee_id)

            if emp:

                ver = self.env["hr.version"].search([("employee_id", "=", emp.id)], order="id desc", limit=1)

                if ver and ver.pms_score:

                    line.pms_score = ver.pms_score

                elif line.transfer_request_id and line.transfer_request_id.pms_score:

                    line.pms_score = line.transfer_request_id.pms_score

                else:

                    line.pms_score = line.pms_score or 0.0

            else:

                line.pms_score = 0.0