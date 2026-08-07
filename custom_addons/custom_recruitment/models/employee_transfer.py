# -*- coding: utf-8 -*-


from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

DISCIPLINE_SELECTION = [
    ("none", "No Active Warning"),
    ("first_warning", "First Warning"),
    ("second_warning", "Second Warning"),
    ("last_written_warning", "Active Last Written Warning"),
]

DISCIPLINE_DEDUCTION = {
    "none": 0.0,
    "first_warning": 5.0,
    "second_warning": 10.0,
    "last_written_warning": 0.0,  # irrelevant – candidate is ineligible outright
}

MIN_SERVICE_YEARS = 1.0
MIN_PMS_SCORE = 75.0


class EmployeeTransferRequest(models.Model):
    _name = "employee.transfer.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Employee-Initiated Transfer Request"
    _rec_name = "name"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    _order = "request_date desc"

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    employee_id = fields.Many2one(
        "hr.employee", string="Requesting Employee", required=True, tracking=True,
        default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1),
    )
    request_date = fields.Date(string="Request Date", default=fields.Date.context_today, required=True)

    # Current situation, pulled from the employee record ------------
    current_job_position_id = fields.Many2one(
        "hr.job", string="Current Job Position", compute="_compute_current_info", store=True
    )
    current_job_grade_id = fields.Many2one(
        "employee.grade", string="Current Grade", compute="_compute_current_info", store=True
    )
    current_operating_unit_id = fields.Many2one(
        "operating.unit", string="Current Location", compute="_compute_current_info", store=True
    )
    date_in_current_position = fields.Date(
        string="Date Joined Current Position",
        compute="_compute_current_info", store=True, readonly=False,
        help="Used to validate the minimum 1-year-in-position service rule.",
    )
    date_in_current_location = fields.Date(
        string="Date Joined Current Location",
        compute="_compute_current_info", store=True, readonly=False,
        help="Used to validate the minimum 1-year-in-location service rule.",
    )

    # Target ------------------------------------
    target_vacancy_id = fields.Many2one(
        "job.vacancy", string="Target Vacancy", required=True,
        domain="[('vacancy_status', '=', 'published')]",
    )
    target_job_grade_id = fields.Many2one(
        "employee.grade", string="Target Grade", related="target_vacancy_id.job_grade", store=True,
    )
    target_job_position_id = fields.Many2one(
        "hr.job", string="Target Position", related="target_vacancy_id.job_position", store=True,
    )
    target_operating_unit_id = fields.Many2one(
        "operating.unit", string="Target Branch/Unit",
        related="target_vacancy_id.operating_unit_id", store=True,
    )

    #  Grade Restriction (strict exact same grade) ------------
    grade_restriction_ok = fields.Boolean(
        string="Grade Match OK", compute="_compute_eligibility", store=True,
        help="True only when the target vacancy job grade exactly matches the employee's current job grade.",
    )

    #  Service Rule -----------------------------
    service_years_current_position = fields.Float(
        string="Years in Current Position", compute="_compute_service_years", store=True
    )
    service_years_current_location = fields.Float(
        string="Years in Current Location", compute="_compute_service_years", store=True
    )
    service_rule_ok = fields.Boolean(string="Service Rule OK", compute="_compute_eligibility", store=True)

    #  Discipline Impact (linked to discipline.case severity_level) ---------
    disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Disciplinary Status", compute="_compute_disciplinary_status",
        store=True, readonly=False, tracking=True,
        help="Auto-populated from Discipline Management (discipline.case) based on case severity levels.",
    )
    discipline_deduction_percent = fields.Float(
        string="Discipline Deduction (%)", compute="_compute_discipline_deduction", store=True
    )

    #  Exchange / Mutual Transfer ---------------------
    is_exchange_transfer = fields.Boolean(string="Exchange Transfer")
    exchange_partner_employee_id = fields.Many2one("hr.employee", string="Exchange Partner Employee")
    exchange_partner_request_id = fields.Many2one(
        "employee.transfer.request", string="Matched Exchange Request",
        help="The other employee's transfer request that forms a mutual swap pair.",
    )
    exchange_partner_disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Exchange Partner Disciplinary Status",
        compute="_compute_exchange_partner_disciplinary_status", store=True, readonly=False,
        help="Auto-populated from Discipline Management (discipline.case) based on partner severity levels.",
    )
    exchange_transfer_ok = fields.Boolean(
        string="Exchange Transfer OK", compute="_compute_eligibility", store=True
    )


    #  Refusal Penalty ---------------------------
    ineligible_until_date = fields.Date(
        string="Ineligible Until Date",
        help="12-month ineligibility penalty applied when employee refuses an approved transfer."
    )

    # Overall eligibility -------------------------------
    eligibility_status = fields.Selection(
        [("eligible", "Eligible"), ("ineligible", "Ineligible")],
        string="Eligibility", compute="_compute_eligibility", store=True,
    )
    ineligibility_reason = fields.Text(string="Ineligibility Reason", compute="_compute_eligibility", store=True)

    #  Withdrawal / Pending expiry notification --------------
    pending_expiry_notified = fields.Boolean(
        string="1-Year Pending Expiry Notified", default=False, copy=False,
        help="Set to True once the system has notified the employee about their long-pending request.",
    )

    # Ranking inputs (used by transfer.committee.minutes,  --------
    total_experience_years = fields.Float(
        string="Total Experience (Years)", compute="_compute_total_experience", store=True, readonly=False
    )
    pms_score = fields.Float(
        string="PMS Score", compute="_compute_pms_score", store=True, readonly=False,
        help="Minimum 75% required for transfer eligibility ",
    )
    supervisor_recommendation_score = fields.Float(
        string="Supervisor Recommendation Score (0-100)",
        help="Supervisor recommendation score for ranking calculation (weighted 10%).",
    )
    transfer_suitability_score = fields.Float(
        string="Transfer Suitability Score", readonly=True, copy=False,
        help="Populated by the Transfer Committee Minutes ranking.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("withdrawn", "Withdrawn"),
            ("refused", "Refused by Employee"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    #  Refusal / HR Flag -------------------------
    is_flagged_for_hr = fields.Boolean(string="Flagged for HR", default=False, readonly=True, copy=False)
    refusal_reason = fields.Text(string="Refusal Reason")
    hr_notified_on_refusal = fields.Datetime(string="HR Notified On", readonly=True, copy=False)

    # ---------------------------------------
    # Sequence & Write Lock
    # ---------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("employee.transfer.request") or _("New")
        return super().create(vals_list)

    def write(self, vals):
        ALLOWED_POST_SUBMIT_FIELDS = {
            "state", "transfer_suitability_score", "is_flagged_for_hr",
            "refusal_reason", "hr_notified_on_refusal", "ineligible_until_date",
            "pending_expiry_notified", "exchange_partner_request_id",
            "message_ids", "message_follower_ids", "activity_ids", "active",
        }
        for rec in self:
            if rec.state != "draft" and not self.env.is_superuser:
                attempted_changes = set(vals.keys()) - ALLOWED_POST_SUBMIT_FIELDS
                if attempted_changes:
                    raise UserError(_("Transfer request fields cannot be modified once submitted."))
        return super().write(vals)

    # ---------------------------------------
    # Computations
    # ---------------------------------------
    @api.depends("employee_id")
    def _compute_current_info(self):
        for rec in self:
            emp = rec.employee_id
            rec.current_job_position_id = emp.job_position if emp else False
            rec.current_job_grade_id = emp.job_grade if emp else False
            rec.current_operating_unit_id = emp.default_operating_unit_id if emp else False
            # Auto-populate date fields from employee's contract/joining date
            if emp and not rec.date_in_current_position:
                joining = (
                    getattr(emp, 'joining_date', False)
                    or getattr(emp, 'first_contract_date', False)
                    or (emp._get_first_contract_date() if hasattr(emp, '_get_first_contract_date') and callable(getattr(emp, '_get_first_contract_date')) else False)
                )
                rec.date_in_current_position = joining or False
            if emp and not rec.date_in_current_location:
                joining = (
                    getattr(emp, 'joining_date', False)
                    or getattr(emp, 'first_contract_date', False)
                    or (emp._get_first_contract_date() if hasattr(emp, '_get_first_contract_date') and callable(getattr(emp, '_get_first_contract_date')) else False)
                )
                rec.date_in_current_location = joining or False

    @api.depends("employee_id")
    def _compute_total_experience(self):
        today = date.today()
        for rec in self:
            if not rec.total_experience_years and rec.employee_id:
                join_d = (
                    getattr(rec.employee_id, 'joining_date', False)
                    or getattr(rec.employee_id, 'first_contract_date', False)
                )
                if join_d:
                    rec.total_experience_years = round((today - join_d).days / 365.25, 2)
                else:
                    rec.total_experience_years = rec.total_experience_years or 0.0

    @api.depends("employee_id")
    def _compute_pms_score(self):
        for rec in self:
            try:
                rec.pms_score = rec.employee_id.contract_id.pms_score or 0.0
            except Exception:
                rec.pms_score = rec.pms_score or 0.0

    @api.depends("date_in_current_position", "date_in_current_location")
    def _compute_service_years(self):
        today = date.today()
        for rec in self:
            rec.service_years_current_position = (
                (today - rec.date_in_current_position).days / 365.25
                if rec.date_in_current_position else 0.0
            )
            rec.service_years_current_location = (
                (today - rec.date_in_current_location).days / 365.25
                if rec.date_in_current_location else 0.0
            )

    @api.depends(
        "disciplinary_status", "exchange_partner_disciplinary_status", "is_exchange_transfer",
        "current_job_grade_id",
        "target_job_grade_id", "target_job_position_id",
        "service_years_current_position", "service_years_current_location",
        "pms_score", "ineligible_until_date",
    )
    def _compute_eligibility(self):
        today = date.today()
        # Fetch config settings from ir.config_parameter
        ICPSudo = self.env["ir.config_parameter"].sudo()
        block_first = ICPSudo.get_param("custom_recruitment.transfer_discipline_blocks_first_warning", "False") == "True"
        block_second = ICPSudo.get_param("custom_recruitment.transfer_discipline_blocks_second_warning", "False") == "True"
        
        try:
            min_pms = float(ICPSudo.get_param("custom_recruitment.transfer_min_pms_score", "75.0"))
        except ValueError:
            min_pms = 75.0
            
        try:
            min_service = float(ICPSudo.get_param("custom_recruitment.transfer_min_service_years", "1.0"))
        except ValueError:
            min_service = 1.0

        for rec in self:
            reasons = []

            # : Check if employee is under a 12-month refusal penalty
            if rec.ineligible_until_date and rec.ineligible_until_date >= today:
                reasons.append(
                    _("Employee is ineligible for transfers until %s due to a previous transfer refusal.")
                    % rec.ineligible_until_date
                )

            # : STRICT same grade restriction – job grade must be exactly equal.
            grade_match = (
                bool(rec.current_job_grade_id)
                and bool(rec.target_job_grade_id)
                and rec.current_job_grade_id == rec.target_job_grade_id
            )
            rec.grade_restriction_ok = grade_match
            if not rec.grade_restriction_ok:
                reasons.append(
                    _("Target vacancy job grade (%s) does not match employee's current job grade (%s). "
                      "Transfer is only allowed to vacancies within the exact same job grade.")
                    % (
                        rec.target_job_grade_id.grade_name if rec.target_job_grade_id else _("Not Set"),
                        rec.current_job_grade_id.grade_name if rec.current_job_grade_id else _("Not Set"),
                    )
                )

            # : minimum service rule (configurable) in current position AND location
            rec.service_rule_ok = (
                rec.service_years_current_position >= min_service
                and rec.service_years_current_location >= min_service
            )
            if not rec.service_rule_ok:
                reasons.append(
                    _("Employee has less than %.2f years of service in current position "
                      "(%.2f yr) and/or location (%.2f yr). Minimum %.2f years required in both ")
                    % (min_service, rec.service_years_current_position, rec.service_years_current_location, min_service)
                )

            # : PMS Score hard gate (configurable minimum)
            if rec.pms_score < min_pms:
                reasons.append(
                    _("Employee PMS Score (%.1f%%) is below the mandatory minimum threshold of %.1f%% .")
                    % (rec.pms_score, min_pms)
                )

            #  / : active disciplinary warning check (flexible per config)
            if rec.disciplinary_status == "last_written_warning":
                reasons.append(
                    _("Employee has an active Last Written Warning. This blocks transfer eligibility.")
                )
            elif rec.disciplinary_status == "first_warning" and block_first:
                reasons.append(
                    _("Employee has an active First Warning, which is configured to block transfer eligibility.")
                )
            elif rec.disciplinary_status == "second_warning" and block_second:
                reasons.append(
                    _("Employee has an active Second Warning, which is configured to block transfer eligibility.")
                )

            # : exchange transfer requires zero active disciplinary records on BOTH sides
            if rec.is_exchange_transfer:
                rec.exchange_transfer_ok = (
                    rec.disciplinary_status == "none"
                    and rec.exchange_partner_disciplinary_status == "none"
                )
                if not rec.exchange_transfer_ok:
                    reasons.append(
                        _("Exchange Transfer requires both employees to have zero active "
                          "disciplinary records .")
                    )
            else:
                rec.exchange_transfer_ok = True

            rec.ineligibility_reason = "\n".join(reasons) if reasons else False
            rec.eligibility_status = "ineligible" if reasons else "eligible"

    @api.depends('employee_id')
    def _compute_disciplinary_status(self):
        for rec in self:
            if rec.employee_id and 'discipline.case' in self.env:
                active_cases = self.env['discipline.case'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'enforced'),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or 'final_warning_penalty' in punishments:
                        rec.disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.disciplinary_status = 'first_warning'
                    else:
                        rec.disciplinary_status = 'none'
                else:
                    rec.disciplinary_status = 'none'
            elif not rec.disciplinary_status:
                rec.disciplinary_status = 'none'

    @api.depends('exchange_partner_employee_id')
    def _compute_exchange_partner_disciplinary_status(self):
        for rec in self:
            if rec.exchange_partner_employee_id and 'discipline.case' in self.env:
                active_cases = self.env['discipline.case'].search([
                    ('employee_id', '=', rec.exchange_partner_employee_id.id),
                    ('state', '=', 'enforced'),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or 'final_warning_penalty' in punishments:
                        rec.exchange_partner_disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.exchange_partner_disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.exchange_partner_disciplinary_status = 'first_warning'
                    else:
                        rec.exchange_partner_disciplinary_status = 'none'
                else:
                    rec.exchange_partner_disciplinary_status = 'none'
            elif not rec.exchange_partner_disciplinary_status:
                rec.exchange_partner_disciplinary_status = 'none'

    @api.depends("disciplinary_status")
    def _compute_discipline_deduction(self):
        for rec in self:
            rec.discipline_deduction_percent = DISCIPLINE_DEDUCTION.get(rec.disciplinary_status, 0.0)


    # ---------------------------------------
    # Onchange helpers
    # ---------------------------------------
    @api.onchange("employee_id")
    def _onchange_employee_auto_dates(self):
        """Auto-populate date_in_current_position and date_in_current_location
        from the employee's contract/joining date if not yet filled."""
        for rec in self:
            if rec.employee_id and not rec.date_in_current_position:
                joining = (
                    getattr(rec.employee_id, 'joining_date', False)
                    or getattr(rec.employee_id, 'first_contract_date', False)
                )
                if joining:
                    rec.date_in_current_position = joining
            if rec.employee_id and not rec.date_in_current_location:
                joining = (
                    getattr(rec.employee_id, 'joining_date', False)
                    or getattr(rec.employee_id, 'first_contract_date', False)
                )
                if joining:
                    rec.date_in_current_location = joining

    # ---------------------------------------
    # Workflow Actions
    # ---------------------------------------
    def action_submit(self):
        """Submit the transfer request after eligibility validation."""
        for rec in self:
            if not rec.target_vacancy_id:
                raise ValidationError(_("Please select a Target Vacancy before submitting."))
            if rec.eligibility_status == "ineligible":
                raise ValidationError(
                    _("Cannot submit transfer request. Employee fails eligibility requirements:\n\n%s")
                    % (rec.ineligibility_reason or _("Unknown reason."))
                )
            rec.state = "submitted"
            rec.message_post(body=_("Transfer request submitted."))

            # Notify HR Officers that a new request has been submitted
            self._notify_hr_of_submission(rec)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Submitted'),
                'message': _('Transfer request submitted successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def _notify_hr_of_submission(self, rec):
        """Notify HR Officers when a new transfer request is submitted."""
        hr_group = self.env.ref("hr.group_hr_user", raise_if_not_found=False)
        if not hr_group:
            return
        body = _(
            "A new Employee Transfer Request <b>%(ref)s</b> has been submitted by "
            "<b>%(employee)s</b> (Current Grade: %(grade)s) for Vacancy: <b>%(vacancy)s</b>."
        ) % {
            "ref": rec.name,
            "employee": rec.employee_id.name,
            "grade": rec.current_job_grade_id.name if rec.current_job_grade_id else _("N/A"),
            "vacancy": rec.target_vacancy_id.reference if rec.target_vacancy_id else _("N/A"),
        }
        rec.message_post(body=body)

    def action_start_review(self):
        records = self.filtered(lambda r: r.state == "submitted")
        records.write({"state": "under_review"})
        for rec in records:
            rec.message_post(body=_("Transfer request is now under review."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Under Review'),
                'message': _('Transfer request is now under review.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_approve(self):
        """Approve the transfer request and execute Employee Master Data updates."""
        for rec in self:
            if rec.eligibility_status != "eligible":
                raise ValidationError(
                    _("This transfer request is not eligible and cannot be approved:\n%s")
                    % (rec.ineligibility_reason or _("Unknown reason."))
                )
            rec.state = "approved"
            rec.message_post(body=_("Transfer request approved."))

            # Update Employee Master Data & Contract


            try:
                emp = rec.employee_id
                target_ou = rec.target_vacancy_id.operating_unit_id if rec.target_vacancy_id else False
                target_pos = rec.target_job_position_id
                target_grade = rec.target_job_grade_id

                if emp:
                    emp_vals = {}
                    if target_ou:
                        emp_vals["default_operating_unit_id"] = target_ou.id
                    if target_pos:
                        emp_vals["job_position"] = target_pos.id
                    if emp_vals:
                        emp.write(emp_vals)

                    contract = getattr(emp, "contract_id", False)
                    if contract:
                        contract_vals = {}
                        if target_ou:
                            contract_vals["operating_unit_id"] = target_ou.id
                        if target_pos:
                            contract_vals["job_id"] = target_pos.id
                        if target_grade:
                            contract_vals["job_grade"] = target_grade.id
                        if contract_vals:
                            contract.write(contract_vals)

                    # : Log transfer history
                    if "transfer.history" in self.env:
                        self.env["transfer.history"].create({
                            "employee_id": emp.id,
                            "from_operating_unit2": rec.current_operating_unit_id.id if rec.current_operating_unit_id else False,
                            "from_position2": rec.current_job_position_id.id if rec.current_job_position_id else False,
                            "from_grade2": rec.current_job_grade_id.id if rec.current_job_grade_id else False,
                            "date2": fields.Date.today(),
                            "to_operting_unit2": target_ou.id if target_ou else False,
                            "to_position2": target_pos.id if target_pos else False,
                            "to_grade2": target_grade.id if target_grade else False,
                        })
            except Exception as e:
                rec.message_post(body=_("Master Data update notification: %s") % str(e))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Approved'),
                'message': _('Transfer request approved and employee data updated.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_reject(self):
        self.write({"state": "rejected"})
        for rec in self:
            rec.message_post(body=_("Transfer request rejected."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Rejected'),
                'message': _('Transfer request rejected.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_withdraw(self):
        """: employees may cancel a pending request via Self-Service."""
        for rec in self:
            if rec.state not in ("draft", "submitted", "under_review"):
                raise UserError(
                    _("Only pending requests (Draft, Submitted, or Under Review) can be withdrawn.")
                )
            rec.state = "withdrawn"
            rec.message_post(body=_("Transfer request withdrawn by employee."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Withdrawn'),
                'message': _('Transfer request withdrawn.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_refuse_transfer(self):
        """: if the employee refuses an Approved Transfer, flag the
        record, notify HR, and list the employee as ineligible for configured months."""
        ICPSudo = self.env["ir.config_parameter"].sudo()
        try:
            penalty_months = int(ICPSudo.get_param("custom_recruitment.transfer_refusal_penalty_months", "12"))
        except ValueError:
            penalty_months = 12
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only an Approved transfer can be refused."))
            rec.write({
                "state": "refused",
                "is_flagged_for_hr": True,
                "hr_notified_on_refusal": fields.Datetime.now(),
                "ineligible_until_date": date.today() + timedelta(days=penalty_months * 30),
            })
            rec._notify_hr_of_refusal()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Refused'),
                'message': _('Transfer refused. Employee flagged and HR notified. %d-month ineligibility applied.') % penalty_months,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def _notify_hr_of_refusal(self):
        """Notify HR Managers via Discuss when an approved transfer is refused."""
        self.ensure_one()
        hr_group = self.env.ref("hr.group_hr_manager", raise_if_not_found=False)
        hr_users = (
            self.env["res.users"].search([("group_ids", "in", [hr_group.id])])
            if hr_group else self.env["res.users"]
        )
        body = _(
            "Employee <b>%(employee)s</b> has refused the approved transfer to "
            "<b>%(position)s</b> (Vacancy: %(vacancy)s). Reason: %(reason)s. "
            "The employee is now flagged and ineligible for transfers until %(until)s."
        ) % {
            "employee": self.employee_id.name,
            "position": self.target_job_position_id.name or "",
            "vacancy": self.target_vacancy_id.reference if self.target_vacancy_id else "",
            "reason": self.refusal_reason or _("Not specified"),
            "until": self.ineligible_until_date,
        }
        self.message_post(body=body)
        partners = hr_users.mapped("partner_id")
        if partners:
            try:
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=partners.ids)
                channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
            except Exception:
                pass  # Don't break the refusal flow if messaging fails

    def action_find_exchange_matches(self):
        """ / : Mutual Exchange Transfer Matching Engine.
        Scans all pending transfer requests to find mutual swap pairs:
        - Employee A at Branch X wants Branch Y
        - Employee B at Branch Y wants Branch X
        - Both must share the same job grade and position
        - Both must have zero active disciplinary records
        Matched pairs are linked via exchange_partner_request_id.
        """
        self.ensure_one()
        if not self.current_operating_unit_id or not self.target_operating_unit_id:
            raise UserError(
                _("This request must have both a Current Location and a Target Branch/Unit set "
                  "before searching for exchange matches.")
            )

        # Find pending requests from the target location wanting THIS location
        domain = [
            ("id", "!=", self.id),
            ("state", "in", ("submitted", "under_review")),
            ("target_operating_unit_id", "=", self.current_operating_unit_id.id),
            ("current_operating_unit_id", "=", self.target_operating_unit_id.id),
            ("current_job_grade_id", "=", self.current_job_grade_id.id),
            ("disciplinary_status", "=", "none"),
            ("eligibility_status", "=", "eligible"),
        ]

        matches = self.env["employee.transfer.request"].search(domain)

        # Filter own discipline = none
        if self.disciplinary_status != "none":
            raise UserError(
                _("Exchange Transfer is only available when you have zero active disciplinary records .")
            )

        if not matches:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Exchange Matches Found'),
                    'message': _(
                        "No mutual exchange candidates found for a swap between "
                        "'%s' and '%s' with matching grade and zero discipline."
                    ) % (
                        self.current_operating_unit_id.name,
                        self.target_operating_unit_id.name,
                    ),
                    'type': 'warning',
                    'sticky': True,
                },
            }

        # Link first best match (earliest application date)
        best_match = matches.sorted(key=lambda r: r.request_date)[0]
        self.write({
            "is_exchange_transfer": True,
            "exchange_partner_employee_id": best_match.employee_id.id,
            "exchange_partner_request_id": best_match.id,
            "exchange_partner_disciplinary_status": best_match.disciplinary_status,
        })
        best_match.write({
            "is_exchange_transfer": True,
            "exchange_partner_employee_id": self.employee_id.id,
            "exchange_partner_request_id": self.id,
            "exchange_partner_disciplinary_status": self.disciplinary_status,
        })

        self.message_post(
            body=_(
                "Mutual Exchange Transfer match found: <b>%(partner)s</b> (%(partner_request)s) "
                "has been linked as exchange partner."
            ) % {
                "partner": best_match.employee_id.name,
                "partner_request": best_match.name,
            }
        )
        best_match.message_post(
            body=_(
                "Mutual Exchange Transfer match found: <b>%(partner)s</b> (%(partner_request)s) "
                "has been linked as exchange partner."
            ) % {
                "partner": self.employee_id.name,
                "partner_request": self.name,
            }
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exchange Match Found!'),
                'message': _(
                    "Mutual exchange partner found: %s. Both requests have been linked."
                ) % best_match.employee_id.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    # ---------------------------------------
    # Scheduled Actions / Cron Jobs
    # ---------------------------------------
    @api.model
    def _cron_check_pending_transfer_requests(self):
        """: Check for transfer requests pending for more than configured time.
        - Notify employees about their long-standing pending request (first run)
        - Auto-withdraw if still pending after notification and no response
        """
        today = date.today()
        ICPSudo = self.env["ir.config_parameter"].sudo()
        try:
            expiry_days = int(ICPSudo.get_param("custom_recruitment.transfer_pending_expiry_days", "365"))
        except ValueError:
            expiry_days = 365
        try:
            auto_withdraw_days = int(ICPSudo.get_param("custom_recruitment.transfer_pending_auto_withdraw_days", "7"))
        except ValueError:
            auto_withdraw_days = 7

        one_year_ago = today - timedelta(days=expiry_days)

        # Step 1: Find requests pending > expiry_days, not yet notified
        pending_not_notified = self.search([
            ("state", "in", ("submitted", "under_review")),
            ("request_date", "<=", one_year_ago),
            ("pending_expiry_notified", "=", False),
        ])

        for req in pending_not_notified:
            req.pending_expiry_notified = True
            req.message_post(
                body=_(
                    "Your transfer request <b>%(ref)s</b> (submitted on %(date)s) has been pending "
                    "for more than %(days)d days. Please confirm whether you wish to continue with this "
                    "request or withdraw it. If no response is received within %(withdraw)d days, the request "
                    "will be automatically cancelled ."
                ) % {
                    "ref": req.name,
                    "date": req.request_date,
                    "days": expiry_days,
                    "withdraw": auto_withdraw_days,
                },
                partner_ids=req.employee_id.user_id.partner_id.ids if req.employee_id.user_id else [],
            )

        # Step 2: Auto-withdraw requests that were notified > auto_withdraw_days ago and still pending
        seven_days_buffer = today - timedelta(days=expiry_days + auto_withdraw_days)
        pending_auto_withdraw = self.search([
            ("state", "in", ("submitted", "under_review")),
            ("request_date", "<=", seven_days_buffer),
            ("pending_expiry_notified", "=", True),
        ])

        for req in pending_auto_withdraw:
            req.write({"state": "withdrawn"})
            req.message_post(
                body=_(
                    "Transfer request <b>%(ref)s</b> has been automatically withdrawn after being "
                    "pending for more than %(days)d days with no response from the employee ."
                ) % {
                    "ref": req.name,
                    "days": expiry_days,
                }
            )
