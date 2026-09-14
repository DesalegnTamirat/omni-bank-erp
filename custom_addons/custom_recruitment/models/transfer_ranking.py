# -*- coding: utf-8 -*-
# Transfer Ranking Engine – Fixed for Direct & Vacancy Transfers

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TransferCommitteeMinutes(models.Model):
    _name = "transfer.committee.minutes"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Transfer Committee Minutes"
    _rec_name = "name"
    active = fields.Boolean(default=True)

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
        help="Optional. Leave empty for committees reviewing direct transfer "
             "requests that are not linked to a specific vacancy.",
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

    signature_line_ids = fields.One2many(
        "transfer.committee.signature", "minutes_id", string="Digital Signatures"
    )

    is_fully_signed = fields.Boolean(
        string="All Mandatory Signatures Obtained",
        compute="_compute_is_fully_signed", store=True,
    )

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
                grade = rec.target_vacancy_id.job_grade_id
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
        """Validate required committee role assignments, generate signature lines, and set state to waiting_signature."""
        for rec in self:
            if not rec.chairperson_id or not rec.secretary_id or not rec.panel_member_id:
                raise UserError(_(
                    "Please assign all mandatory committee roles (Chairperson, Panel Member, and Secretary) "
                    "before submitting for digital signatures."
                ))
            rec.action_generate_signature_lines()
            rec.state = "waiting_signature"
            partner_ids = rec.signature_line_ids.mapped("user_id.partner_id").ids
            rec.message_post(
                body=_("Transfer Committee Minutes ranking finalized and submitted for digital signatures."),
                partner_ids=partner_ids
            )
        return True

    @api.onchange('target_vacancy_id')
    def _onchange_target_vacancy_id(self):
        """Auto-populate transfer_request_ids with all eligible requests matching
        the current vacancy setting (or direct transfers if left empty), and keep
        the picker domain in sync for any manual adjustments afterward."""
        if self.target_vacancy_id:
            domain = [
                ('target_vacancy_id', '=', self.target_vacancy_id.id),
                ('state', 'in', ['under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]
        else:
            domain = [
                ('target_vacancy_id', '=', False),
                ('state', 'in', ['under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]

        matching_requests = self.env['employee.transfer.request'].search(domain)
        self.transfer_request_ids = matching_requests

        return {'domain': {'transfer_request_ids': domain}}

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
        the current Target Vacancy (or direct transfers if empty)."""
        for rec in self:
            domain = [
                ('state', 'in', ['under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]
            if rec.target_vacancy_id:
                domain.append(('target_vacancy_id', '=', rec.target_vacancy_id.id))
            else:
                domain.append(('target_vacancy_id', '=', False))

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
                raise UserError(_(
                    "No transfer requests have been added to this committee yet. "
                    "Select at least one request under 'Transfer Requests Considered' "
                    "before computing the ranking."
                ))

            # Strict Reviewer Approval Check: Verify all transfer requests have been reviewed and approved by the initial reviewer
            unapproved_by_reviewer = rec.transfer_request_ids.filtered(
                lambda r: r.state in ("draft", "submitted")
            )
            if unapproved_by_reviewer:
                unapproved_names = ", ".join("%s (%s)" % (r.name, r.state) for r in unapproved_by_reviewer)
                raise ValidationError(_(
                    "Cannot compute ranking! The initial reviewer/manager has not reviewed and approved the following transfer request(s) yet: %s. "
                    "All transfer requests must be under review and approved by the initial reviewer before committee ranking."
                ) % unapproved_names)

            eligible_requests = rec.transfer_request_ids.filtered(
                lambda r: r.eligibility_status == "eligible"
            )
            if not eligible_requests:
                status_summary = ", ".join(
                    "%s (%s)" % (r.name, r.eligibility_status or _("unknown"))
                    for r in rec.transfer_request_ids
                )
                raise UserError(_(
                    "None of the %d transfer request(s) added to this committee are "
                    "marked eligible. Current status: %s"
                ) % (len(rec.transfer_request_ids), status_summary))

            rec.ranking_line_ids.unlink()

            # --- Determine number of open slots for auto-selection ---------
            if rec.target_vacancy_id:
                slots = rec.target_vacancy_id.no_of_vacancies or 1
            else:
                slots = 1

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

                recommendation_score = req.supervisor_recommendation_score if req.supervisor_recommendation_score is not False and req.supervisor_recommendation_score > 0 else 100.0
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

            # Process approval and complete transfer for selected candidates (without swallowing validation errors)
            for line in selected_lines:
                transfer_req = line.transfer_request_id
                if not transfer_req:
                    continue
                if transfer_req.state in ("submitted", "under_review"):
                    transfer_req.action_approve()
                if transfer_req.state == "approved":
                    transfer_req.action_complete_transfer()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Minutes Approved'),
                'message': _('Transfer Committee Minutes approved and selected candidate transfers completed.'),
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

    def write(self, vals):
        """Strict signature enforcement: Only the assigned user (user_id) can sign or modify their signature."""
        if ("digital_signature" in vals or vals.get("state") == "signed") and not self.env.su:
            for line in self:
                if line.user_id and line.user_id != self.env.user:
                    raise UserError(_(
                        "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "
                        "You are logged in as '%s'. Only '%s' can digitally sign this line."
                    ) % (line.role_label, line.user_id.name, self.env.user.name, line.user_id.name))
        return super().write(vals)

    def action_sign_digitally(self):
        """Record signature strictly for the assigned user."""
        for line in self:
            if line.user_id != self.env.user:
                raise UserError(_(
                    "Unauthorized Signature Error: The signature line for '%s' is strictly assigned to '%s'. "
                    "You are logged in as '%s'. Only '%s' is authorized to sign their name on this line."
                ) % (line.role_label, line.user_id.name, self.env.user.name, line.user_id.name))
            if not line.digital_signature:
                raise UserError(_("Please draw or upload a digital signature before confirming."))
            line.write({
                "signed_on": fields.Datetime.now(),
                "state": "signed",
            })
            line.minutes_id.message_post(
                body=_("Digital signature recorded for %s (%s).") % (line.role_label, line.user_id.name)
            )
        return True


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
            if line.minutes_id.state == "approved":
                raise ValidationError(_("Cannot modify candidate rankings or decisions on approved Transfer Committee Minutes!"))
            if line.minutes_id.state == "waiting_signature" and "selection_decision" in vals:
                raise ValidationError(_("Selection decisions cannot be modified once committee minutes are submitted for digital signatures!"))
        return super().write(vals)
    _order = "rank"

    minutes_id = fields.Many2one("transfer.committee.minutes", string="Minutes", required=True, ondelete="cascade")
    rank = fields.Integer(string="Rank")
    transfer_request_id = fields.Many2one("employee.transfer.request", string="Transfer Request", required=True)
    employee_id = fields.Many2one(related="transfer_request_id.employee_id", string="Employee", store=True)
    employee_gender = fields.Selection(
        related="transfer_request_id.employee_id.gender",
        string="Gender", store=True,
    )

    application_date_score = fields.Float(string="Application Date Score (20%)")
    experience_score = fields.Float(string="Total Experience Score (20%)")
    service_location_score = fields.Float(string="Service in Location Score (20%)")
    pms_score = fields.Float(string="PMS Score (30%)", compute="_compute_pms_score", store=True, readonly=False)
    recommendation_score = fields.Float(string="Recommendation Score (10%)")
    discipline_deduction_percent = fields.Float(string="Discipline Deduction (%)")
    final_score = fields.Float(string="Final Transfer Suitability Score")

    selection_decision = fields.Selection(
        [("selected", "Selected"), ("not_selected", "Not Selected")],
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