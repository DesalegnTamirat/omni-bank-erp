import base64
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class RecruitmentSelectionMinute(models.Model):
    """
    Central selection minute document for both External and Internal Recruitment.
    Tracks candidate matrix, committee review signatures, auto-approval, and PDF generation.
    """
    _name = "recruitment.selection.minute"
    _description = "Recruitment Committee Selection Minute"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "meeting_date desc, id desc"

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

    @api.depends("vacancy_id", "vacancy_id.recruitment_type")
    def _compute_recruitment_type(self):
        for rec in self:
            if rec.vacancy_id and rec.vacancy_id.recruitment_type:
                raw_val = str(rec.vacancy_id.recruitment_type).strip().lower()
                rec.recruitment_type = "external" if "ext" in raw_val else "internal"
            else:
                rec.recruitment_type = "internal"

    meeting_date = fields.Date(
        string="Meeting Date",
        default=fields.Date.context_today,
        required=True,
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
    active = fields.Boolean(default=True)

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            ALTER TABLE recruitment_selection_minute 
            ADD COLUMN IF NOT EXISTS panel_notified boolean DEFAULT false;

            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'recruitment_selection_minute' AND column_name = 'recruitment_type') THEN
                    UPDATE recruitment_selection_minute 
                    SET recruitment_type = CASE 
                        WHEN LOWER(recruitment_type) LIKE '%ext%' THEN 'external'
                        ELSE 'internal'
                    END
                    WHERE recruitment_type IS NULL OR recruitment_type = '' OR LOWER(recruitment_type) NOT IN ('internal', 'external');
                END IF;

                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'recruitment_selection_minute_line') THEN
                    UPDATE recruitment_selection_minute_line 
                    SET selection_status = CASE
                        WHEN LOWER(selection_status) LIKE '%select%' THEN 'selected'
                        WHEN LOWER(selection_status) LIKE '%reser%' THEN 'reserve'
                        WHEN LOWER(selection_status) LIKE '%fail%' OR LOWER(selection_status) LIKE '%reject%' OR LOWER(selection_status) LIKE '%disqualif%' THEN 'failed'
                        ELSE 'reserve'
                    END
                    WHERE selection_status IS NULL OR selection_status = '';
                END IF;

                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'recruitment_committee_signature') THEN
                    UPDATE recruitment_committee_signature 
                    SET state = LOWER(state)
                    WHERE state IS NOT NULL AND LOWER(state) IN ('pending', 'signed', 'rejected');
                END IF;
            END $$;
        """)
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

    @api.depends("committee_signature_ids.state")
    def _compute_signature_status(self):
        for rec in self:
            if not rec.committee_signature_ids:
                rec.is_fully_signed = False
            else:
                rec.is_fully_signed = all(
                    sig.state == "signed" for sig in rec.committee_signature_ids
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") in (_("New"), "New") or str(vals.get("name")).startswith("MIN/"):
                vals["name"] = self._get_next_minute_reference()
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

            # 2. Load Panel Members / Committee Signature Slots
            sig_cmds = [(5, 0, 0)]
            added_user_ids = set()

            # Panel members from vacancy (memb_panel_vac)
            for pm in self.vacancy_id.memb_panel_vac:
                u_id = pm.user_id.id if pm.user_id else (pm.employee_id.user_id.id if pm.employee_id and pm.employee_id.user_id else False)
                if not u_id and pm.panel_member_name:
                    emp = self.env['hr.employee'].search([('name', '=ilike', pm.panel_member_name)], limit=1)
                    u_id = emp.user_id.id if emp and emp.user_id else False

                if u_id and u_id not in added_user_ids:
                    added_user_ids.add(u_id)
                    role_desc = pm.role or pm.panel_type or "Panel Member"
                    sig_cmds.append(
                        (
                            0,
                            0,
                            {
                                "user_id": u_id,
                                "role": role_desc,
                                "state": "pending",
                            },
                        )
                    )

            # Vacancy Delegation team
            for del_member in self.vacancy_id.vac_del_team_id:
                u_id = del_member.employee_name.id if del_member.employee_name else False
                if u_id and u_id not in added_user_ids:
                    added_user_ids.add(u_id)
                    role_desc = del_member.role or "Delegated Committee Member"
                    sig_cmds.append(
                        (
                            0,
                            0,
                            {
                                "user_id": u_id,
                                "role": role_desc,
                                "state": "pending",
                            },
                        )
                    )

            # Vacancy Responsible employee
            if self.vacancy_id.responsible and self.vacancy_id.responsible.user_id:
                resp_u_id = self.vacancy_id.responsible.user_id.id
                if resp_u_id not in added_user_ids:
                    added_user_ids.add(resp_u_id)
                    sig_cmds.append(
                        (
                            0,
                            0,
                            {
                                "user_id": resp_u_id,
                                "role": "Recruitment Responsible / HR",
                                "state": "pending",
                            },
                        )
                    )

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
        int_sel = self.env["new.internal.recruitment.selected"].search([
            '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
        ], limit=1)

        if int_sel and int_sel.new_int_rec_sel:
            for cand in int_sel.new_int_rec_sel:
                if cand.emp_name:
                    status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else ('reserve' if cand.selection_type in ('reserve', 'Reserved') else 'failed')
                    lines.append((0, 0, {
                        'employee_id': cand.emp_name.id,
                        'candidate_name': cand.emp_name.name,
                        'pms_score': cand.pms_score or 0.0,
                        'written_score': cand.written_exam_score or 0.0,
                        'interview_score': cand.interview_score or 0.0,
                        'final_score': cand.weighted_score or 0.0,
                        'rank': cand.rank or 0,
                        'selection_status': status_val,
                    }))

        # 2. Search External Recruitment Process Selected records
        if not lines:
            ext_sel = self.env["external.recruitment.selected"].search([
                '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
            ], limit=1)
            if ext_sel and ext_sel.ext_rec_sel:
                for cand in ext_sel.ext_rec_sel:
                    cand_name = cand.applicant_name.partner_name if (cand.applicant_name and getattr(cand.applicant_name, 'partner_name', False)) else (cand.applicant_name.name if cand.applicant_name else cand.emp_name or 'Applicant')
                    status_val = 'selected' if cand.selection_type in ('selected', 'Selected') else ('reserve' if cand.selection_type in ('reserved', 'Reserve') else 'failed')
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

    def action_load_panel_members_from_vacancy(self):
        """Auto-populate committee signature slots from assigned process panel members or vacancy panel members."""
        self.ensure_one()
        if not self.vacancy_id:
            return

        if self.id:
            self.committee_signature_ids.unlink()

        sig_lines = []
        added_user_ids = set()

        # 1. Search Internal Process Record Panel Members (checking approved delegation)
        int_sel = self.env["new.internal.recruitment.selected"].search([
            '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
        ], limit=1)

        if int_sel:
            if int_sel.new_int_rec_panel:
                for panel in int_sel.new_int_rec_panel:
                    emp = panel.delegate_employee_id if (panel.delegation_state == 'approved' and panel.delegate_employee_id) else panel.emp_name
                    user = emp.user_id if (emp and getattr(emp, 'user_id', False)) else False
                    if not user and emp:
                        user = self.env['res.users'].search([('employee_id', '=', emp.id)], limit=1)
                    if user and user.id not in added_user_ids:
                        added_user_ids.add(user.id)
                        sig_lines.append((0, 0, {
                            'user_id': user.id,
                            'role': panel.selection_criteria or 'Panel Member',
                            'state': 'pending',
                        }))

            if int_sel.recr_selected_team_id:
                for member in int_sel.recr_selected_team_id:
                    user = member.employee_name or member.alternate_committee_member
                    if user and user.id not in added_user_ids:
                        added_user_ids.add(user.id)
                        role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                        sig_lines.append((0, 0, {
                            'user_id': user.id,
                            'role': role_label,
                            'state': 'pending',
                        }))

        # 2. Search External Process Record Panel Members
        if not sig_lines:
            ext_sel = self.env["external.recruitment.selected"].search([
                '|', ('vacancy_id', '=', self.vacancy_id.id), ('vacancy_reference', '=', self.vacancy_id.reference)
            ], limit=1)
            if ext_sel:
                if ext_sel.ext_rec_panel:
                    for panel in ext_sel.ext_rec_panel:
                        emp = panel.delegate_employee_id if (panel.delegation_state == 'approved' and panel.delegate_employee_id) else panel.emp_name
                        user = emp.user_id if (emp and getattr(emp, 'user_id', False)) else False
                        if not user and emp:
                            user = self.env['res.users'].search([('employee_id', '=', emp.id)], limit=1)
                        if user and user.id not in added_user_ids:
                            added_user_ids.add(user.id)
                            sig_lines.append((0, 0, {
                                'user_id': user.id,
                                'role': panel.selection_criteria or 'Panel Member',
                                'state': 'pending',
                            }))
                ext_team = getattr(ext_sel, 'recr_exter_selected_team_id', False) or getattr(ext_sel, 'recr_selected_team_id', False)
                if ext_team:
                    for member in ext_team:
                        user = member.employee_name or member.alternate_committee_member
                        if user and user.id not in added_user_ids:
                            added_user_ids.add(user.id)
                            role_label = dict(member._fields['role'].selection).get(member.role, 'Committee Member') if member.role else 'Committee Member'
                            sig_lines.append((0, 0, {
                                'user_id': user.id,
                                'role': role_label,
                                'state': 'pending',
                            }))

        # 3. Search Vacancy Panel Members
        if not sig_lines and self.vacancy_id:
            for pm in self.vacancy_id.memb_panel_vac:
                u_id = pm.user_id.id if pm.user_id else (pm.employee_id.user_id.id if pm.employee_id and pm.employee_id.user_id else False)
                if not u_id and pm.panel_member_name:
                    emp = self.env['hr.employee'].search([('name', '=ilike', pm.panel_member_name)], limit=1)
                    u_id = emp.user_id.id if emp and emp.user_id else False

                if u_id and u_id not in added_user_ids:
                    added_user_ids.add(u_id)
                    role_desc = pm.role or pm.panel_type or "Panel Member"
                    sig_lines.append((0, 0, {
                        "user_id": u_id,
                        "role": role_desc,
                        "state": "pending",
                    }))

            for del_member in self.vacancy_id.vac_del_team_id:
                u_id = del_member.employee_name.id if del_member.employee_name else False
                if u_id and u_id not in added_user_ids:
                    added_user_ids.add(u_id)
                    role_desc = del_member.role or "Delegated Committee Member"
                    sig_lines.append((0, 0, {
                        "user_id": u_id,
                        "role": role_desc,
                        "state": "pending",
                    }))

            if self.vacancy_id.responsible and self.vacancy_id.responsible.user_id:
                resp_u_id = self.vacancy_id.responsible.user_id.id
                if resp_u_id not in added_user_ids:
                    added_user_ids.add(resp_u_id)
                    sig_lines.append((0, 0, {
                        "user_id": resp_u_id,
                        "role": "Recruitment Responsible / HR",
                        "state": "pending",
                    }))

        if sig_lines:
            self.write({"committee_signature_ids": sig_lines})

    def action_load_from_vacancy(self):
        """Reload candidates and panel members from the selected vacancy."""
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

        for rec in self:
            if not rec.committee_signature_ids:
                raise UserError(_("No panel/committee members found to notify."))

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
                            'note': _("<p>Selection Minute <b>%s</b> for vacancy <b>%s</b> requires your digital signature.</p>") % (
                                rec.name, rec.vacancy_id.display_name or rec.vacancy_id.name or ''
                            ),
                            'summary': _("Digitally Sign Selection Minute %s") % rec.name,
                            'user_id': sig.user_id.id,
                            'res_model_id': model_id.id,
                            'res_id': rec.id,
                            'date_deadline': fields.Date.context_today(self),
                        })

            # Send targeted Odoo Discuss message notification ONLY to panel members' partners
            if notified_partners:
                rec.message_notify(
                    partner_ids=notified_partners,
                    subject=_("Pending Digital Signature: Selection Minute %s") % rec.name,
                    body=_(
                        "<p>Dear Committee Member,</p>"
                        "<p>Selection Minute <b>%s</b> for vacancy <b>%s</b> is ready for your digital signature.</p>"
                        "<p>Please review the candidate matrix and digitally sign the minute.</p>"
                    ) % (rec.name, rec.vacancy_id.display_name or rec.vacancy_id.name or ''),
                    email_layout_xmlid="mail.mail_notification_light",
                )

            rec.message_post(
                body=_(
                    "Digital Signature notification and activity tasks dispatched to %s panel/committee member(s)."
                ) % len(notified_partners or rec.committee_signature_ids),
                partner_ids=notified_partners,
                subtype_xmlid="mail.mt_comment",
            )
            rec.write({'panel_notified': True})

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
        if not self.committee_signature_ids:
            raise ValidationError(
                _("Please add committee members before submitting for approval.")
            )

        self.write({"state": "pending_approval", "panel_notified": True})
        self.action_notify_panel_members()

    def _check_auto_approval(self):
        """Auto-triggers approval once all committee members sign and updates the selection process state to Approved."""
        for rec in self:
            if rec.state == "pending_approval" and rec.is_fully_signed:
                rec.write({"state": "approved"})
                rec.message_post(
                    body=_(
                        "All committee members have digitally signed. Selection Minute is officially APPROVED."
                    )
                )
                rec._generate_and_attach_pdf()

                # Sync approval status back to recruitment selection records
                if rec.vacancy_id:
                    vac_ref = rec.vacancy_id.reference
                    vac_id = rec.vacancy_id.id

                    # 1. Internal Recruitment Process Selected
                    int_sel = self.env["new.internal.recruitment.selected"].search([
                        '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
                    ])
                    for s in int_sel:
                        s.write({'state': 'approved', 'status': 'approved'})
                        s.message_post(body=_(
                            "Selection Process officially APPROVED: All committee members have digitally signed Selection Minute <b>%s</b>."
                        ) % rec.name)

                    # 2. External Recruitment Process Selected
                    ext_sel = self.env["external.recruitment.selected"].search([
                        '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
                    ])
                    for s in ext_sel:
                        s.write({'state': 'approved', 'status': 'approved'})
                        s.message_post(body=_(
                            "Selection Process officially APPROVED: All committee members have digitally signed Selection Minute <b>%s</b>."
                        ) % rec.name)

    def _generate_and_attach_pdf(self):
        try:
            pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
                "custom_recruitment.action_report_selection_minute", [self.id]
            )
            rec_track = self.recruitment_type or "recruitment"
            filename = f"Selection_Minute_{rec_track}_{self.name.replace('/', '_')}.pdf"
            attachment = self.env["ir.attachment"].create(
                {
                    "name": filename,
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/pdf",
                }
            )
            self.message_post(
                body=_("Signed PDF Selection Minute has been generated and attached."),
                attachment_ids=[attachment.id],
            )
        except Exception as e:
            _logger.warning("PDF Minute Generation Warning: %s", e)


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
    written_score = fields.Float(string="Written Exam", digits=(5, 2))
    interview_score = fields.Float(string="Interview Exam", digits=(5, 2))
    final_score = fields.Float(string="Final Total Score", digits=(5, 2))
    rank = fields.Integer(string="Rank")

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

    minute_id = fields.Many2one(
        "recruitment.selection.minute", string="Selection Minute", ondelete="cascade"
    )
    user_id = fields.Many2one("res.users", string="Committee Member", required=True)
    role = fields.Char(
        string="Committee Role", help="e.g. Committee Chair, HR Officer, Technical Examiner"
    )
    state = fields.Selection(
        [
            ("pending", "Pending Signature"),
            ("signed", "Signed"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
        tracking=True,
    )

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        valid_states = ("pending", "signed", "rejected")
        for r in res:
            if "state" in r and r["state"] not in valid_states:
                r["state"] = "pending"
        return res

    signature_img = fields.Binary(
        string="Digital Signature", help="Draw or upload digital signature"
    )
    signed_date = fields.Datetime(string="Signed On", readonly=True)
    remarks = fields.Text(string="Remarks / Comments")

    def _generate_digital_signature_badge(self):
        name = self.user_id.name or "Committee Member"
        role = self.role or "Committee Member"
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

    def action_sign_minute(self):
        self.ensure_one()
        if self.user_id != self.env.user:
            raise UserError(_("You can only sign your own assigned signature slot."))

        req = (
            self.env["ir.http"]._request
            if hasattr(self.env["ir.http"], "_request")
            else None
        )
        ip_addr = req.remote_addr if req else "127.0.0.1"
        now_dt = fields.Datetime.now()

        vals = {
            "state": "signed",
            "signed_date": now_dt,
        }

        # If user did NOT draw or upload an image, auto-generate official digital signature badge
        if not self.signature_img:
            vals["signature_img"] = self._generate_digital_signature_badge()

        self.write(vals)
        self.minute_id._check_auto_approval()
