# -*- coding: utf-8 -*-

from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup

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
    "last_written_warning": 0.0,
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
        for rec in self:
            rec.write({'active': False})
        return True

    _order = "request_date desc"
    def _auto_init(self):
        res = super()._auto_init()
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    UPDATE employee_transfer_request 
                    SET state = CASE 
                            WHEN state ILIKE 'draft' THEN 'draft'
                            WHEN state ILIKE 'submitted' THEN 'submitted'
                            WHEN state ILIKE '%under%' THEN 'under_review'
                            WHEN state ILIKE 'approved' THEN 'approved'
                            WHEN state ILIKE 'transferred' THEN 'transferred'
                            WHEN state ILIKE 'rejected' THEN 'rejected'
                            WHEN state ILIKE 'withdrawn' THEN 'withdrawn'
                            WHEN state ILIKE 'refused' THEN 'refused'
                            ELSE 'draft'
                        END,
                        acceptance_status = CASE 
                            WHEN acceptance_status ILIKE 'accepted' THEN 'accepted'
                            WHEN acceptance_status ILIKE 'rejected' OR acceptance_status ILIKE 'refused' OR acceptance_status ILIKE 'declined' THEN 'rejected'
                            ELSE 'pending'
                        END,
                        eligibility_status = CASE 
                            WHEN eligibility_status ILIKE 'ineligible' THEN 'ineligible'
                            ELSE 'eligible'
                        END,
                        current_job_category = CASE 
                            WHEN current_job_category ILIKE '%non%' THEN 'Non Managerial'
                            WHEN current_job_category ILIKE '%manag%' THEN 'Managerial'
                            ELSE 'Non Managerial'
                        END,
                        disciplinary_status = CASE 
                            WHEN disciplinary_status ILIKE '%last%' THEN 'last_written_warning'
                            WHEN disciplinary_status ILIKE '%second%' THEN 'second_warning'
                            WHEN disciplinary_status ILIKE '%first%' THEN 'first_warning'
                            ELSE 'none'
                        END;
                """)
        except Exception as e:
            pass
        return res


    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    employee_id = fields.Many2one(
        "hr.employee", string="Requesting Employee", required=True, tracking=True,
        default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1),
    )
    request_date = fields.Date(string="Request Date", default=fields.Date.context_today, required=True)

    current_job_position_id = fields.Many2one(
        "hr.job", string="Current Job Position", compute="_compute_current_info",
        store=True, readonly=False,
    )
    current_job_grade_id = fields.Many2one(
        "employee.grade", string="Current Grade", compute="_compute_current_info",
        store=True, readonly=False,
    )

    current_job_level = fields.Selection(
        related='current_job_grade_id.grade_level',
        string='Job Level', store=True, readonly=True,
        help="Mirrors Current Grade's Job Level (Junior/Senior), set on the "
             "employee.grade record itself. Required by job.vacancy when the "
             "vacancy's Employee Category is Non Managerial.",
    )

    target_job_level = fields.Selection(
        related='target_job_grade_id.grade_level',
        string='Target Job Level', store=True, readonly=True,
    )

    current_operating_unit_id = fields.Many2one(
        "operating.unit", string="Current Location", compute="_compute_current_info",
        store=True, readonly=False,
    )
    date_in_current_position = fields.Date(
        string="Date Joined Current Position",
        compute="_compute_current_info", store=True, readonly=False,
    )
    date_in_current_location = fields.Date(
        string="Date Joined Current Location",
        compute="_compute_current_info", store=True, readonly=False,
    )

    target_vacancy_id = fields.Many2one(
        "job.vacancy", string="Target Vacancy",
        domain="[('vacancy_status', '=', 'published')]",
    )
    target_job_grade_id = fields.Many2one(
        "employee.grade", string="Target Grade", compute="_compute_target_info", store=True,
    )
    target_job_position_id = fields.Many2one(
        "hr.job", string="Target Position", compute="_compute_target_info", store=True,
    )

    target_operating_unit_id = fields.Many2one(
        "operating.unit", string="Target Branch/Unit",
        compute="_compute_target_info", store=True,
    )

    requested_operating_unit_id = fields.Many2one(
        "operating.unit", string="Requested Operating Unit",
    )
    alternate_location_preference_id = fields.Many2one(
        "operating.unit", string="Alternate Location Preference (Optional)",
    )
    reason_for_transfer = fields.Text(string="Reason for Transfer")
    additional_remarks = fields.Text(string="Additional Remarks (Optional)")
    transfer_letter_id = fields.Many2one(
        "transfer.letter", string="Lateral Transfer Letter", readonly=True, copy=False,
    )

    employee_name = fields.Char(related="employee_id.name", string="Employee Name", store=True, readonly=True)
    department_id = fields.Many2one(
        related="employee_id.department_id", string="Department", store=True, readonly=True,
    )
    current_job_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Job Category",
        compute="_compute_current_info",
        store=True,
        readonly=True,
    )
    employment_type = fields.Selection(
        related="employee_id.employee_type", string="Employment Type", store=True, readonly=True,
    )
    contract_start_date = fields.Date(
        string="Contract Start Date", compute="_compute_current_info", store=True,
    )
    gender = fields.Selection(related="employee_id.gender", string="Gender", store=True, readonly=True)
    active_phone_number = fields.Char(
        related="employee_id.work_phone", string="Active Phone Number", store=True, readonly=True,
    )
    active_email_address = fields.Char(
        related="employee_id.work_email", string="Active Email Address", store=True, readonly=True,
    )

    final_assessment_score = fields.Float(
        string="Final Assessment Score", compute="_compute_final_assessment_score",
    )
    current_ranking = fields.Integer(
        string="Current Ranking", compute="_compute_final_assessment_score",
    )

    grade_restriction_ok = fields.Boolean(
        string="Grade Match OK", compute="_compute_eligibility", store=True,
    )

    service_years_current_position = fields.Float(
        string="Years in Current Position", compute="_compute_service_years", store=True
    )
    service_years_current_location = fields.Float(
        string="Years in Current Location", compute="_compute_service_years", store=True
    )
    service_rule_ok = fields.Boolean(string="Service Rule OK", compute="_compute_eligibility", store=True)

    disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Disciplinary Status", compute="_compute_disciplinary_status",
        store=True, readonly=True, tracking=True,
    )
    discipline_deduction_percent = fields.Float(
        string="Discipline Deduction (%)", compute="_compute_discipline_deduction", store=True
    )

    is_exchange_transfer = fields.Boolean(string="Exchange Transfer")
    exchange_partner_employee_id = fields.Many2one("hr.employee", string="Exchange Partner Employee")
    exchange_partner_request_id = fields.Many2one(
        "employee.transfer.request", string="Matched Exchange Request",
    )
    exchange_partner_disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Exchange Partner Disciplinary Status",
        compute="_compute_exchange_partner_disciplinary_status", store=True, readonly=True,
    )
    exchange_transfer_ok = fields.Boolean(
        string="Exchange Transfer OK", compute="_compute_eligibility", store=True
    )

    ineligible_until_date = fields.Date(
        string="Ineligible Until Date",
    )

    eligibility_status = fields.Selection(
        [("eligible", "Eligible"), ("ineligible", "Ineligible")],
        string="Eligibility", compute="_compute_eligibility", store=True,
    )
    ineligibility_reason = fields.Text(string="Ineligibility Reason", compute="_compute_eligibility", store=True)

    pending_expiry_notified = fields.Boolean(
        string="1-Year Pending Expiry Notified", default=False, copy=False,
    )

    total_experience_years = fields.Float(
        string="Total Experience (Years)", compute="_compute_total_experience", store=True, readonly=False
    )
    pms_score = fields.Float(
        string="PMS Score", compute="_compute_pms_score", store=True, readonly=False,
    )
    supervisor_recommendation_score = fields.Float(
        string="Supervisor Recommendation Score (0-100)",
        default=100.0,
    )
    transfer_suitability_score = fields.Float(
        string="Transfer Suitability Score", readonly=True, copy=False,
    )

    reporting_manager_id = fields.Many2one(
        "hr.employee", string="Reporting Manager (New Position)",
        help="Manager the employee will report to after the transfer. "
             "Used in the Employee Transfer Selection Notification letter.",
    )
    effective_transfer_date = fields.Date(
        string="Effective Transfer Date",
        help="Date the employee is expected to report to the new position. "
             "Used in the Employee Transfer Selection Notification letter.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("transferred", "Transfer Completed"),
            ("rejected", "Rejected"),
            ("withdrawn", "Withdrawn"),
            ("refused", "Refused by Employee"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    is_flagged_for_hr = fields.Boolean(string="Flagged for HR", default=False, readonly=True, copy=False)
    refusal_reason = fields.Text(string="Refusal Reason")
    hr_notified_on_refusal = fields.Datetime(string="HR Notified On", readonly=True, copy=False)

    acceptance_status = fields.Selection([
        ('pending', 'Pending Acceptance'),
        ('accepted', 'Accepted'),
        ('rejected', 'Refused / Declined'),
    ], string="Transfer Acceptance Status", default='pending')
    acceptance_date = fields.Datetime(string="Acceptance / Response Date", readonly=True)

    def action_accept_transfer(self):
        """Requesting employee or HR accepts the transfer offer."""
        for rec in self:
            now = fields.Datetime.now()
            rec.write({
                'acceptance_status': 'accepted',
                'acceptance_date': now,
            })
            rec.message_post(
                body=_("Employee transfer offer ACCEPTED on %s.") % fields.Date.today()
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Accepted'),
                'message': _('Transfer offer has been marked as ACCEPTED.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_decline_transfer(self):
        """Opens the decline wizard to capture refusal reason for transfer."""
        self.ensure_one()
        return {
            'name': _('Decline / Refuse Transfer Offer'),
            'type': 'ir.actions.act_window',
            'res_model': 'internal.selection.decline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transfer_request_id': self.id,
            }
        }

    def confirm_decline_transfer(self, reason):
        """Executed by decline wizard to refuse transfer."""
        for rec in self:
            now = fields.Datetime.now()
            rec.write({
                'acceptance_status': 'rejected',
                'acceptance_date': now,
                'state': 'refused',
                'refusal_reason': reason,
                'is_flagged_for_hr': True,
                'hr_notified_on_refusal': now,
            })
            rec.message_post(
                body=_("Employee DECLINED / REFUSED transfer offer.<br/><b>Reason:</b> %s") % reason
            )
        return True

    submitted_by_user_id = fields.Many2one("res.users", string="Submitted By User", readonly=True, copy=False)
    reviewed_by_user_id = fields.Many2one("res.users", string="Reviewer User (Started Review)", readonly=True, copy=False, tracking=True)
    approved_by_user_id = fields.Many2one("res.users", string="Approved By User", readonly=True, copy=False, tracking=True)

    is_requesting_employee = fields.Boolean(
        string="Is Requesting Employee",
        compute="_compute_user_roles",
    )
    is_hr_user = fields.Boolean(
        string="Is HR User",
        compute="_compute_user_roles",
    )

    @api.depends_context("uid")
    @api.depends("employee_id")
    def _compute_user_roles(self):
        user = self.env.user
        is_hr = (
            user.has_group("custom_recruitment.group_recruitment_officer")
            or user.has_group("custom_recruitment.group_recruitment_manager")
            or user.has_group("custom_recruitment.group_recruitment_administrator")
            or user.has_group("hr.group_hr_user")
            or user.has_group("hr.group_hr_manager")
        )
        for rec in self:
            rec.is_hr_user = is_hr
            rec.is_requesting_employee = bool(rec.employee_id and rec.employee_id.user_id and rec.employee_id.user_id.id == user.id)

    def _get_employee_active_discipline_cases(self, employee):
        case_names = []
        if not employee:
            return case_names

        # 1. Search discipline.case model (discipline_management module)
        if 'discipline.case' in self.env:
            cases = self.env['discipline.case'].search([
                ('employee_id', '=', employee.id),
                ('state', 'not in', ['revoked', 'closed']),
            ])
            for c in cases:
                sel = c._fields['punishment_type'].selection if 'punishment_type' in c._fields else False
                if callable(sel):
                    try:
                        sel = sel(c.env[c._name])
                    except Exception:
                        sel = False
                p_label = dict(sel).get(c.punishment_type, c.punishment_type or 'Active Offense') if sel and isinstance(sel, (list, tuple)) else (c.punishment_type or 'Active Offense')
                case_names.append("%s (%s - state: %s)" % (c.name or 'Case', p_label, c.state))

        # 2. Search discipline.action model (hr_employee_custom module)
        if 'discipline.action' in self.env:
            actions = self.env['discipline.action'].search([
                ('employee_name', '=', employee.id),
            ])
            for a in actions:
                a_name = getattr(a, 'ref_no', False) or getattr(a, 'name', False) or 'Disciplinary Action'
                case_names.append("Action: %s" % a_name)

        # 3. Search disciplinary.action model (hr_employee_custom module)
        if 'disciplinary.action' in self.env:
            d_actions = self.env['disciplinary.action'].search([
                ('employee_name', '=', employee.id),
            ])
            for da in d_actions:
                da_name = getattr(da, 'name', False) or 'Disciplinary Action'
                case_names.append("Disciplinary Action: %s" % da_name)

        return case_names

    @api.constrains("employee_id")
    def _check_employee_discipline_constraints(self):
        for rec in self:
            if rec.employee_id:
                active_cases = rec._get_employee_active_discipline_cases(rec.employee_id)
                if active_cases:
                    case_names = ", ".join(active_cases)
                    raise ValidationError(_(
                        "Cannot create or process transfer request for employee '%s'. "
                        "The employee has active disciplinary record(s): %s. "
                        "Employees with active disciplinary cases are strictly prohibited from requesting transfers."
                    ) % (rec.employee_id.name, case_names))

    @api.onchange("employee_id")
    def _onchange_employee_id_discipline_warning(self):
        if self.employee_id:
            active_cases = self._get_employee_active_discipline_cases(self.employee_id)
            if active_cases:
                case_names = ", ".join(active_cases)
                return {
                    "warning": {
                        "title": _("Active Disciplinary Record Detected"),
                        "message": _(
                            "Employee '%s' has active disciplinary case(s): %s. "
                            "Transfer requests are strictly prohibited for employees with active disciplinary records."
                        ) % (self.employee_id.name, case_names)
                    }
                }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("employee.transfer.request") or _("New")
            emp_id = vals.get("employee_id")
            if emp_id:
                emp = self.env["hr.employee"].browse(emp_id)
                active_cases = self._get_employee_active_discipline_cases(emp)
                if active_cases:
                    case_names = ", ".join(active_cases)
                    raise ValidationError(_(
                        " You Cannot create transfer request for employee '%s'. "
                        "The employee has active disciplinary record(s): %s. "
                        "Employees with active disciplinary cases are strictly prohibited from applying for transfers."
                    ) % (emp.name, case_names))
        records = super().create(vals_list)
        records._compute_current_info()
        return records

    def write(self, vals):
        ALLOWED_POST_SUBMIT_FIELDS = {
            "state", "transfer_suitability_score", "is_flagged_for_hr",
            "refusal_reason", "hr_notified_on_refusal", "ineligible_until_date",
            "pending_expiry_notified", "exchange_partner_request_id",
            "message_ids", "message_follower_ids", "activity_ids", "active",
            "target_vacancy_id", "target_job_grade_id", "target_job_position_id",
            "target_job_level", "target_operating_unit_id",
            "supervisor_recommendation_score",
            "reporting_manager_id", "effective_transfer_date",
            "submitted_by_user_id", "reviewed_by_user_id", "approved_by_user_id",
        }
        computed_fields = {
            fname for fname, field in self._fields.items() if field.compute
        }
        protected_fields = set(vals.keys()) - ALLOWED_POST_SUBMIT_FIELDS - computed_fields
        for rec in self:
            if rec.state != "draft" and not self.env.su and protected_fields:
                raise UserError(_("Transfer request fields cannot be modified once submitted."))
        return super().write(vals)

    @api.depends(
        "employee_id",
        "employee_id.job_position",
        "employee_id.job_position.employee_category",
        "employee_id.job_id",
        "employee_id.job_id.employee_category",
        "employee_id.job_grade",
        "employee_id.default_operating_unit_id",
        "employee_id.contract_id",
        "employee_id.contract_id.date_start",
    )
    def _compute_current_info(self):
        for rec in self:
            emp = rec.employee_id
            rec.current_job_position_id = emp.job_position if emp else False
            rec.current_job_grade_id = emp.job_grade if emp else False
            rec.current_operating_unit_id = emp.default_operating_unit_id if emp else False

            job = getattr(emp, "job_position", False) or getattr(emp, "job_id", False) if emp else False
            cat = False
            if job and hasattr(job, "employee_category") and job.employee_category:
                raw_cat = str(job.employee_category).strip()
                if "non" in raw_cat.lower():
                    cat = "Non Managerial"
                elif "manag" in raw_cat.lower():
                    cat = "Managerial"
                else:
                    cat = raw_cat
            elif emp and emp.job_grade and hasattr(emp.job_grade, "job_category") and emp.job_grade.job_category:
                cat = emp.job_grade.job_category

            rec.current_job_category = cat or False

            if emp and not rec.date_in_current_position:
                joining = (
                        getattr(emp, 'joining_date', False)
                        or getattr(emp, 'first_contract_date', False)
                        or (emp._get_first_contract_date() if hasattr(emp, '_get_first_contract_date') and callable(
                    getattr(emp, '_get_first_contract_date')) else False)
                )
                rec.date_in_current_position = joining or False
            if emp and not rec.date_in_current_location:
                joining = (
                        getattr(emp, 'joining_date', False)
                        or getattr(emp, 'first_contract_date', False)
                        or (emp._get_first_contract_date() if hasattr(emp, '_get_first_contract_date') and callable(
                    getattr(emp, '_get_first_contract_date')) else False)
                )
                rec.date_in_current_location = joining or False

            contract = getattr(emp, 'contract_id', False) if emp else False
            rec.contract_start_date = getattr(contract, 'date_start', False) if contract else False

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
            if rec.employee_id:
                ver = self.env["hr.version"].search([("employee_id", "=", rec.employee_id.id)], order="id desc", limit=1)
                if ver and ver.pms_score:
                    rec.pms_score = ver.pms_score
                elif rec.employee_id.contract_id and getattr(rec.employee_id.contract_id, "pms_score", False):
                    rec.pms_score = rec.employee_id.contract_id.pms_score
                else:
                    rec.pms_score = rec.pms_score or 0.0
            else:
                rec.pms_score = 0.0

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
        ICPSudo = self.env["ir.config_parameter"].sudo()
        block_first = ICPSudo.get_param("custom_recruitment.transfer_discipline_blocks_first_warning",
                                        "False") == "True"
        block_second = ICPSudo.get_param("custom_recruitment.transfer_discipline_blocks_second_warning",
                                         "False") == "True"

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

            if rec.ineligible_until_date and rec.ineligible_until_date >= today:
                reasons.append(
                    _("Employee is ineligible for transfers until %s due to a previous transfer refusal.")
                    % rec.ineligible_until_date
                )

            grade_match = (
                    bool(rec.current_job_grade_id)
                    and bool(rec.target_job_grade_id)
                    and rec.current_job_grade_id == rec.target_job_grade_id
            )
            rec.grade_restriction_ok = grade_match
            if not rec.grade_restriction_ok:
                reasons.append(
                    _("Target vacancy job grade (%s) does not match employee's current job grade (%s).")
                    % (
                        rec.target_job_grade_id.grade_name if rec.target_job_grade_id else _("Not Set"),
                        rec.current_job_grade_id.grade_name if rec.current_job_grade_id else _("Not Set"),
                    )
                )

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

            if rec.pms_score < min_pms:
                reasons.append(
                    _("Employee PMS Score (%.1f%%) is below the mandatory minimum threshold of %.1f%% .")
                    % (rec.pms_score, min_pms)
                )

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

            if rec.is_exchange_transfer:
                rec.exchange_transfer_ok = (
                        rec.disciplinary_status == "none"
                        and rec.exchange_partner_disciplinary_status == "none"
                )
                if not rec.exchange_transfer_ok:
                    reasons.append(
                        _("Exchange Transfer requires both employees to have zero active disciplinary records.")
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
                    ('state', 'not in', ['revoked', 'closed']),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or {'dismissal', 'final_warning_penalty'} & punishments:
                        rec.disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.disciplinary_status = 'first_warning'
                    else:
                        rec.disciplinary_status = 'last_written_warning'
                else:
                    rec.disciplinary_status = 'none'
            else:
                rec.disciplinary_status = 'none'

    @api.depends('exchange_partner_employee_id')
    def _compute_exchange_partner_disciplinary_status(self):
        for rec in self:
            if rec.exchange_partner_employee_id and 'discipline.case' in self.env:
                active_cases = self.env['discipline.case'].search([
                    ('employee_id', '=', rec.exchange_partner_employee_id.id),
                    ('state', 'not in', ['revoked', 'closed']),
                ])
                if active_cases:
                    severities = set(active_cases.mapped('severity_level'))
                    punishments = set(active_cases.mapped('punishment_type'))
                    if {'level_1', 'level_2'} & severities or {'dismissal', 'final_warning_penalty'} & punishments:
                        rec.exchange_partner_disciplinary_status = 'last_written_warning'
                    elif 'level_3' in severities or 'second_warning_penalty' in punishments:
                        rec.exchange_partner_disciplinary_status = 'second_warning'
                    elif 'level_4' in severities or 'first_warning_penalty' in punishments:
                        rec.exchange_partner_disciplinary_status = 'first_warning'
                    else:
                        rec.exchange_partner_disciplinary_status = 'last_written_warning'
                else:
                    rec.exchange_partner_disciplinary_status = 'none'
            else:
                rec.exchange_partner_disciplinary_status = 'none'

    @api.depends("disciplinary_status")
    def _compute_discipline_deduction(self):
        for rec in self:
            rec.discipline_deduction_percent = DISCIPLINE_DEDUCTION.get(rec.disciplinary_status, 0.0)

    @api.depends(
        "target_vacancy_id", "target_vacancy_id.job_grade", "target_vacancy_id.job_position",
        "target_vacancy_id.operating_unit_id",
        "current_job_grade_id",
        "requested_operating_unit_id", "current_job_position_id",
    )
    def _compute_target_info(self):
        for rec in self:
            if rec.target_vacancy_id:
                rec.target_job_grade_id = rec.target_vacancy_id.job_grade
                rec.target_job_position_id = rec.target_vacancy_id.job_position
                rec.target_operating_unit_id = rec.target_vacancy_id.operating_unit_id
            else:
                rec.target_job_grade_id = rec.current_job_grade_id
                rec.target_job_position_id = rec.current_job_position_id
                rec.target_operating_unit_id = rec.requested_operating_unit_id

    def _compute_final_assessment_score(self):
        ICPSudo = self.env["ir.config_parameter"].sudo()

        def _weight(param, default):
            try:
                return float(ICPSudo.get_param(param, str(default))) / 100.0
            except ValueError:
                return default / 100.0

        w_pms = _weight("custom_recruitment.transfer_weight_pms", 30.0)
        w_app = _weight("custom_recruitment.transfer_weight_application_date", 20.0)
        w_exp = _weight("custom_recruitment.transfer_weight_experience", 20.0)
        w_loc = _weight("custom_recruitment.transfer_weight_service_location", 20.0)
        w_rec = _weight("custom_recruitment.transfer_weight_recommendation", 10.0)

        pools = {}
        for rec in self:
            key = (rec.requested_operating_unit_id.id or rec.target_operating_unit_id.id or False,
                   rec.current_job_grade_id.id or rec.target_job_grade_id.id or False)
            pools.setdefault(key, self.env["employee.transfer.request"])
            pools[key] |= rec

        for (ou_id, grade_id), batch in pools.items():
            domain = [
                ("state", "in", ("submitted", "under_review")),
                ("eligibility_status", "=", "eligible"),
            ]
            if ou_id:
                domain.append(("requested_operating_unit_id", "=", ou_id))
            if grade_id:
                domain.append(("current_job_grade_id", "=", grade_id))
            pool_requests = self.env["employee.transfer.request"].search(domain) | batch

            eligible_pool = pool_requests.filtered(lambda r: r.eligibility_status == "eligible")
            if not eligible_pool:
                for rec in batch:
                    rec.final_assessment_score = 0.0
                    rec.current_ranking = 0
                continue

            dates = eligible_pool.mapped("request_date")
            min_date = min(dates)
            date_span = (max(dates) - min_date).days or 1
            max_experience = max(eligible_pool.mapped("total_experience_years")) or 1.0
            max_location_years = max(eligible_pool.mapped("service_years_current_location")) or 1.0

            scored = []
            for req in eligible_pool:
                days_from_earliest = (req.request_date - min_date).days
                application_score = 100.0 * (1 - (days_from_earliest / date_span))
                experience_score = (
                    100.0 * (req.total_experience_years / max_experience) if max_experience else 0.0
                )
                location_score = (
                    100.0 * (req.service_years_current_location / max_location_years)
                    if max_location_years else 0.0
                )
                pms_score = req.pms_score or 0.0
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
                scored.append((req, final_score))

            scored.sort(key=lambda t: round(t[1], 4), reverse=True)

            for idx, (req, score) in enumerate(scored, start=1):
                if req in batch:
                    req.final_assessment_score = round(score, 2)
                    req.transfer_suitability_score = round(score, 2)
                    req.current_ranking = idx
            for rec in batch:
                if rec.eligibility_status != "eligible":
                    rec.final_assessment_score = 0.0
                    rec.transfer_suitability_score = 0.0
                    rec.current_ranking = 0

    @api.onchange("employee_id")
    def _onchange_employee_auto_dates(self):
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

    def action_submit(self):
        for rec in self:
            if rec.target_vacancy_id:
                raise ValidationError(
                    _("A Target Vacancy cannot be selected at submission time.")
                )
            missing = []
            if not rec.requested_operating_unit_id:
                missing.append(_("Requested Operating Unit"))
            if not rec.reason_for_transfer:
                missing.append(_("Reason for Transfer"))
            if not rec.current_job_category:
                missing.append(_("Job Category"))
            if missing:
                raise ValidationError(
                    _("Please complete the following before submitting:\n- %s")
                    % "\n- ".join(missing)
                )
            if rec.eligibility_status == "ineligible":
                raise ValidationError(
                    _("Cannot submit transfer request. Employee fails eligibility requirements:\n\n%s")
                    % (rec.ineligibility_reason or _("Unknown reason."))
                )
            duplicate = self.env["employee.transfer.request"].search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "in", ("submitted", "under_review", "approved")),
                ("id", "!=", rec.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    _("You already have an active transfer request (%s).") % duplicate.name
                )
            rec.write({
                "state": "submitted",
                "submitted_by_user_id": self.env.user.id,
            })
            rec.message_post(body=_("Transfer request submitted by %s.") % self.env.user.name)
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
        hr_group = self.env.ref("hr.group_hr_user", raise_if_not_found=False)
        if not hr_group:
            return
        body = _(
            "A new Employee Transfer Request <b>%(ref)s</b> has been submitted by "
            "<b>%(employee)s</b> (Current Grade: %(grade)s)."
        ) % {
                   "ref": rec.name,
                   "employee": rec.employee_id.name,
                   "grade": rec.current_job_grade_id.grade_name if rec.current_job_grade_id else _("N/A"),
               }
        rec.message_post(body=body)

    def _notify_manager_of_under_review(self, rec):
        # Identify manager: coach_id under hr.employee table (fallback parent_id)
        manager = rec.employee_id.coach_id or rec.employee_id.parent_id
        if not manager:
            return

        body = _(
            "Transfer request %(name)s for employee %(employee)s is now Under Review. "
            "As the direct manager/supervisor (coach), please open the request and provide the "
            "Supervisor Recommendation Score (0-100%%)."
        ) % {
            "name": rec.name,
            "employee": rec.employee_id.name,
        }

        # 1. Post to Chatter & In-App Discuss / Inbox Notification
        if manager.user_id and manager.user_id.partner_id:
            partner = manager.user_id.partner_id
            rec.message_post(
                body=body,
                partner_ids=[partner.id],
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )
            try:
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
                channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
            except Exception:
                pass
            try:
                self.env['bus.bus']._sendone(
                    partner,
                    'notification',
                    {
                        'type': 'warning',
                        'title': _('Action Required: Provide Supervisor Recommendation Score'),
                        'message': body,
                        'sticky': True,
                    }
                )
            except Exception:
                pass
        else:
            rec.message_post(body=body)

        # 2. Direct Email to Manager
        manager_email = manager.work_email or (manager.user_id.email if manager.user_id else False)
        if manager_email:
            email_from = self.env.company.email or self.env.user.email_formatted or "noreply@bunnabank.com"
            try:
                mail_values = {
                    "subject": _("Action Required: Provide Supervisor Recommendation Score - %s (%s)") % (rec.name, rec.employee_id.name),
                    "body_html": Markup("<div><p>%s</p></div>") % body,
                    "email_to": manager_email,
                    "email_from": email_from,
                }
                mail = self.env["mail.mail"].sudo().create(mail_values)
                try:
                    mail.send()
                except Exception:
                    pass
            except Exception:
                pass

        # 3. Create Activity Task for Manager
        if manager.user_id:
            try:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Provide Supervisor Recommendation Score for Transfer Request'),
                    note=body,
                    user_id=manager.user_id.id,
                    date_deadline=date.today() + timedelta(days=3),
                )
            except Exception:
                pass

    def action_start_review(self):
        records = self.filtered(lambda r: r.state == "submitted")
        records.write({
            "state": "under_review",
            "reviewed_by_user_id": self.env.user.id,
        })
        for rec in records:
            rec.message_post(body=_("Transfer request is now under review by %s.") % self.env.user.name)
            self._notify_manager_of_under_review(rec)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Under Review'),
                'message': _('Transfer request is now under review and notification sent to manager/coach.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_search_matching_vacancies(self):
        self.ensure_one()
        if self.target_vacancy_id:
            raise UserError(_("A target vacancy is already linked to this request."))
        if not self.requested_operating_unit_id:
            raise UserError(_("Set a Requested Operating Unit before searching."))

        domain = [
            ("vacancy_status", "=", "published"),
            ("operating_unit_id", "=", self.requested_operating_unit_id.id),
            ("sourcing_type", "in", ("internal", "both")),
        ]
        if self.current_job_grade_id:
            domain.append(("job_grade", "=", self.current_job_grade_id.id))
        if self.current_job_category:
            domain.append(("employee_category", "=", self.current_job_category))

        matches = self.env["job.vacancy"].search(domain)
        if not matches:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Matching Vacancy Found'),
                    'message': _(
                        "No published vacancy currently matches '%s'.") % self.requested_operating_unit_id.name,
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Matching Vacancies for %s') % self.name,
            'res_model': 'job.vacancy',
            'view_mode': 'list,form',
            'domain': [('id', 'in', matches.ids)],
            'target': 'current',
        }

    def action_create_lateral_vacancy(self):
        self.ensure_one()
        if self.target_vacancy_id:
            raise UserError(_("A target vacancy is already linked to this request."))
        if not self.requested_operating_unit_id:
            raise UserError(_("Set a Requested Operating Unit first."))
        if not self.current_job_position_id:
            raise UserError(_("This request has no current job position."))

        category = self.current_job_category or "Non Managerial"

        responsible_employee = self.env.user.employee_id
        vacancy_vals = {
            "job_position": self.current_job_position_id.id,
            "operating_unit_id": self.requested_operating_unit_id.id,
            "sourcing_type": "internal",
            "internal_movement_type": "lateral",
            "employee_category": category,
            "responsible": responsible_employee.id if responsible_employee else False,
            "opening_date": fields.Date.today(),
            "last_date_to_apply": fields.Date.today() + timedelta(days=30),
            "no_of_vacancies": 1,
            "vacancy_description": _(
                "Lateral Transfer Vacancy for transfer request %(ref)s."
            ) % {"ref": self.name},
            "vacancy_status": "published",
        }

        if self.current_job_level and "job_level" in self.env["job.vacancy"]._fields:
            vacancy_vals["job_level"] = self.current_job_level

        template_vacancy = self.env["job.vacancy"].search([
            ("job_position", "=", self.current_job_position_id.id),
            ("competency_line_ids", "!=", False),
        ], order="id desc", limit=1)

        competency_commands = [
            (0, 0, {
                "competency_id": line.competency_id.id,
                "required_level": line.required_level,
                "notes": line.notes,
            })
            for line in template_vacancy.competency_line_ids
        ] if template_vacancy else []

        if competency_commands:
            vacancy_vals["competency_line_ids"] = competency_commands
        else:
            vacancy_vals["vacancy_status"] = "draft"

        vacancy = self.env["job.vacancy"].create(vacancy_vals)
        self.target_vacancy_id = vacancy.id

        if competency_commands:
            self.message_post(
                body=_(
                    "Lateral Transfer Vacancy %(ref)s created and linked. "
                    "Competencies were copied from a previous vacancy for this "
                    "job position (%(src)s) — please review before publishing."
                ) % {"ref": vacancy.reference, "src": template_vacancy.reference}
            )
        else:
            self.message_post(
                body=_(
                    "Lateral Transfer Vacancy %(ref)s created as Draft and linked. "
                    "No previous vacancy was found for this job position to copy "
                    "competencies from — please add required competencies manually "
                    "before publishing."
                ) % {"ref": vacancy.reference}
            )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Lateral Transfer Vacancy'),
            'res_model': 'job.vacancy',
            'res_id': vacancy.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Lateral Transfer Letter Actions ──────────────────────────────
    def _ensure_transfer_letter(self):
        """Ensures a lateral transfer letter exists for this transfer request, creating it if needed."""
        self.ensure_one()
        if self.transfer_letter_id:
            return self.transfer_letter_id

        emp = self.employee_id
        title = 'Ato'
        gender = (emp.gender or '').lower() if emp else ''
        if gender in ['female', 'f']:
            title = 'W/ro'

        cur_unit = self.current_operating_unit_id.name if self.current_operating_unit_id else (emp.operating_unit.name if emp and emp.operating_unit else _('Current Branch'))
        cur_pos = self.current_job_position_id.name if self.current_job_position_id else (emp.job_title or (emp.job_id.name if emp and emp.job_id else _('Current Position')))
        new_unit = self.target_operating_unit_id.name if self.target_operating_unit_id else (self.requested_operating_unit_id.name if self.requested_operating_unit_id else _('Target Branch'))
        new_pos = self.target_job_position_id.name if self.target_job_position_id else cur_pos
        grade_name = self.current_job_grade_id.grade_name if self.current_job_grade_id else (getattr(emp, 'emp_grade', False) and emp.emp_grade.grade_name or 'Grade')
        salary = emp.contract_id.wage if (emp and emp.contract_id and emp.contract_id.wage) else (getattr(emp, 'monthly_salary', 0.0) or 0.0)

        eff_date = getattr(self, 'effective_transfer_date', False) or getattr(self, 'reporting_date', False) or fields.Date.today()
        id_num = getattr(emp, 'identification_id', False) or getattr(emp, 'employee_id_number', False) or getattr(emp, 'barcode', '') or ''

        letter_vals = {
            'transfer_request_id': self.id,
            'employee_id': emp.id,
            'employee_name': emp.name,
            'employee_title': title,
            'employee_email': (emp.work_email or emp.private_email or '').strip(),
            'employee_id_number': id_num,
            'employee_address': cur_unit or _('Addis Ababa'),
            'letter_date': fields.Date.today(),
            'effective_date': eff_date,
            'current_work_unit_name': cur_unit,
            'current_position_name': cur_pos,
            'new_work_unit_name': new_unit,
            'new_position_name': new_pos,
            'job_grade_name': grade_name,
            'monthly_salary': salary,
            'signatory_title': 'Talent Management Directorate',
            'signatory_company': 'Bunna Bank S.C.',
            'state': 'draft',
        }
        letter = self.env['transfer.letter'].create(letter_vals)
        self.transfer_letter_id = letter.id
        return letter

    def action_generate_transfer_letter(self):
        """Generates or opens the Lateral Transfer Letter."""
        self.ensure_one()
        letter = self._ensure_transfer_letter()
        return {
            'name': _('Lateral Transfer Letter'),
            'type': 'ir.actions.act_window',
            'res_model': 'transfer.letter',
            'res_id': letter.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_transfer_letter(self):
        """Prints the Lateral Transfer Letter directly from the transfer request."""
        self.ensure_one()
        letter = self._ensure_transfer_letter()
        return letter.action_print_transfer_letter()

    def action_send_transfer_letter(self):
        """Sends the Lateral Transfer Letter by email with PDF attached directly from the transfer request."""
        self.ensure_one()
        letter = self._ensure_transfer_letter()
        return letter.action_send_transfer_letter()

    def action_view_transfer_letter(self):
        """Opens the linked Lateral Transfer Letter."""
        self.ensure_one()
        if not self.transfer_letter_id:
            raise UserError(_("No Lateral Transfer Letter has been generated yet."))
        return {
            'name': _('Lateral Transfer Letter'),
            'type': 'ir.actions.act_window',
            'res_model': 'transfer.letter',
            'res_id': self.transfer_letter_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_selection_notification_html(self):
        self.ensure_one()
        emp = self.employee_id
        html = _(
            """
            <p>Date: %(today)s</p>
            <p>
                To: %(employee_name)s<br/>
                Employee ID: %(employee_id)s
            </p>
            <p><b>Subject: Employee Transfer Request Status</b></p>
            <p>Dear %(employee_name)s,</p>
            <p>
                Your request has been accepted by the HR team and is awaiting
                successful completion.
            </p>
            <p>
                Sincerely,<br/>
                Human Resources Department
            </p>
            """
        ) % {
                   "today": fields.Date.today().strftime("%B %d, %Y"),
                   "employee_name": emp.name or "",
                   "employee_id": emp.id,
               }
        return Markup(html)

    def _send_selection_notification(self):
        self.ensure_one()
        body = self._get_selection_notification_html()

        self.message_post(
            body=Markup("<b>Selection Notification sent to employee:</b>") + body,
            subtype_xmlid="mail.mt_note",
        )

        if self.active_email_address:
            try:
                mail_values = {
                    "subject": _("Transfer Request Accepted - %s") % self.name,
                    "body_html": body,
                    "email_to": self.active_email_address,
                    "auto_delete": True,
                }
                self.env["mail.mail"].sudo().create(mail_values).send()
            except Exception as e:
                self.message_post(
                    body=_("Could not email the Selection Notification to %s: %s")
                         % (self.active_email_address, str(e))
                )
        else:
            self.message_post(
                body=_("No work email on file for %s — Selection Notification was "
                       "only logged here, not emailed.") % self.employee_id.name
            )

    def action_approve(self):
        """HR administrative approval only. Confirms the request is valid
        and eligible. Does NOT change the employee's job/grade/operating
        unit — that only happens when this employee is selected via
        Transfer Committee Minutes (see action_complete_transfer)."""
        for rec in self:
            current_user = self.env.user

            if rec.state in ("draft", "submitted"):
                raise ValidationError(_(
                    "Cannot approve transfer request '%s'! The initial reviewer/manager has not reviewed and approved this request yet (Current Status: %s). "
                    "The request must be under review before HR approval."
                ) % (rec.name, rec.state))

            # STRICT Segregation of Duties Check 1: The user who clicked 'Start Review' CANNOT approve the request
            if rec.reviewed_by_user_id and rec.reviewed_by_user_id.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') clicked 'Start Review' for transfer request '%s'. "
                    "You are strictly prohibited from approving a request you reviewed. "
                    "To ensure segregation of duties in the approval hierarchy, the request MUST be approved by a DIFFERENT user."
                ) % (current_user.name, rec.name))

            # STRICT Segregation of Duties Check 2: The requesting employee cannot approve their own request
            if rec.employee_id.user_id and rec.employee_id.user_id.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') are the requesting employee for '%s'. "
                    "You are strictly prohibited from approving your own transfer request."
                ) % (current_user.name, rec.name))

            # STRICT Segregation of Duties Check 3: The user who submitted the request cannot approve it
            if rec.submitted_by_user_id and rec.submitted_by_user_id.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') submitted transfer request '%s'. "
                    "You are strictly prohibited from approving a request you submitted."
                ) % (current_user.name, rec.name))

            if rec.eligibility_status != "eligible":
                raise ValidationError(
                    _("This transfer request is not eligible:\n%s")
                    % (rec.ineligibility_reason or _("Unknown reason."))
                )
            rec.write({
                "state": "approved",
                "approved_by_user_id": current_user.id,
            })
            rec.message_post(
                body=_("Transfer request approved by HR (%s). The transfer will "
                       "take effect once this employee is selected through "
                       "the Transfer Committee Minutes ranking process.") % current_user.name
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Approved'),
                'message': _('Approved. Transfer completes after Committee Minutes selection.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_complete_transfer(self):
        """Executes the actual transfer: updates the employee's job
        position/grade/operating unit, updates the contract, logs job
        history and transfer history, and sends the selection
        notification. Called ONLY from
        TransferCommitteeMinutes.action_approve_minutes() for requests
        marked 'Selected' in the ranking — never from the request form
        directly."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_(
                    "Only requests already Approved by HR can be "
                    "completed. Current status: %s"
                ) % rec.state)

            emp = rec.employee_id
            target_ou = rec.target_operating_unit_id
            target_pos = rec.target_job_position_id
            target_grade = rec.target_job_grade_id
            target_level = rec.current_job_level

            try:
                if emp:
                    emp_vals = {}
                    if target_ou:
                        emp_vals["default_operating_unit_id"] = target_ou.id
                    if target_pos:
                        emp_vals["job_position"] = target_pos.id
                    if target_level and "job_level" in emp._fields:
                        emp_vals["job_level"] = target_level
                    if emp_vals:
                        emp.with_context(job_history_reason='transfer').write(emp_vals)

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

                    self.env["hr.employee.transfer.history"].create({
                        "employee_id": emp.id,
                        "date": fields.Date.today(),
                        "transfer_reason": rec.reason_for_transfer or False,
                        "from_operating_unit_id": rec.current_operating_unit_id.id if rec.current_operating_unit_id else False,
                        "from_department_id": rec.department_id.id if rec.department_id else False,
                        "from_job_id": rec.current_job_position_id.id if rec.current_job_position_id else False,
                        "from_grade_id": rec.current_job_grade_id.id if rec.current_job_grade_id else False,
                        "to_operating_unit_id": target_ou.id if target_ou else False,
                        "to_department_id": emp.department_id.id if emp.department_id else False,
                        "to_job_id": target_pos.id if target_pos else False,
                        "to_grade_id": target_grade.id if target_grade else False,
                    })
            except Exception as e:
                rec.message_post(body=_("Master Data update notification: %s") % str(e))

            rec.state = "transferred"
            rec.message_post(
                body=_("Transfer completed. Employee position updated per "
                       "Committee Minutes selection.")
            )
            rec._send_selection_notification()

        return True

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
        for rec in self:
            if rec.state not in ("draft", "submitted", "under_review"):
                raise UserError(
                    _("Only pending requests can be withdrawn.")
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

    def action_reconfirm_interest(self):
        for rec in self:
            rec.write({
                'pending_expiry_notified': False,
                'request_date': date.today(),
            })
            rec.message_post(body=_("Employee re-confirmed interest in transfer request. Expiry timer reset."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Interest Re-confirmed'),
                'message': _('Your interest in this transfer request has been re-confirmed and active cycle reset.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_refuse_transfer(self):
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
                'message': _('Transfer refused. Employee flagged and HR notified.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def _notify_hr_of_refusal(self):
        self.ensure_one()
        hr_group = self.env.ref("hr.group_hr_manager", raise_if_not_found=False)
        hr_users = (
            self.env["res.users"].search([("group_ids", "in", [hr_group.id])])
            if hr_group else self.env["res.users"]
        )
        body = _(
            "Employee <b>%(employee)s</b> has refused the approved transfer."
        ) % {
                   "employee": self.employee_id.name,
               }
        self.message_post(body=body)
        partners = hr_users.mapped("partner_id")
        if partners:
            try:
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=partners.ids)
                channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
            except Exception:
                pass

    def action_find_exchange_matches(self):
        self.ensure_one()
        if not self.current_operating_unit_id or not self.target_operating_unit_id:
            raise UserError(
                _("Both Current Location and Target Branch/Unit must be set.")
            )

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

        if self.disciplinary_status != "none":
            raise UserError(
                _("Exchange Transfer requires zero active disciplinary records.")
            )

        if not matches:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Exchange Matches Found'),
                    'message': _("No mutual exchange candidates found."),
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                },
            }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exchange Match Found!'),
                'message': _("Mutual exchange partner found: %s.") % best_match.employee_id.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    @api.model
    def _cron_check_pending_transfer_requests(self):
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

        pending_not_notified = self.search([
            ("state", "in", ("draft", "submitted", "under_review")),
            ("request_date", "<=", one_year_ago),
            ("pending_expiry_notified", "=", False),
        ])

        for req in pending_not_notified:
            req.pending_expiry_notified = True
            body = _(
                "Your transfer request (%(name)s) has been pending for more than %(days)d days. "
                "Please open your transfer request and click 'Re-confirm Interest' within 7 days, "
                "otherwise the request will be automatically withdrawn."
            ) % {"name": req.name, "days": expiry_days}
            
            # 1. Post to Chatter & In-App Discuss / Inbox Notification
            partner = req.employee_id.user_id.partner_id if req.employee_id and req.employee_id.user_id else False
            if partner:
                req.message_post(
                    body=body,
                    partner_ids=[partner.id],
                    message_type="notification",
                    subtype_xmlid="mail.mt_comment",
                )
                # In-App Discuss Chat Notification
                try:
                    channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
                    channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
                except Exception:
                    pass
                # In-App Bus Toast Alert (Pop-up alert in Odoo UI)
                try:
                    self.env['bus.bus']._sendone(
                        partner,
                        'notification',
                        {
                            'type': 'warning',
                            'title': _('Transfer Request Pending Confirmation'),
                            'message': body,
                            'sticky': True,
                        }
                    )
                except Exception:
                    pass
            else:
                req.message_post(body=body)

            # 2. Send Direct Email to Applicant Address
            if req.active_email_address:
                email_from = self.env.company.email or self.env.user.email_formatted or "noreply@bunnabank.com"
                try:
                    mail_values = {
                        "subject": _("Action Required: Transfer Request Pending Confirmation - %s") % req.name,
                        "body_html": Markup("<div><p>%s</p></div>") % body,
                        "email_to": req.active_email_address,
                        "email_from": email_from,
                    }
                    mail = self.env["mail.mail"].sudo().create(mail_values)
                    try:
                        mail.send()
                    except Exception:
                        pass
                except Exception:
                    pass

            # 3. Create Systray Activity Task
            if req.employee_id and req.employee_id.user_id:
                try:
                    req.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Transfer Request Pending Confirmation'),
                        note=body,
                        user_id=req.employee_id.user_id.id,
                        date_deadline=today + timedelta(days=auto_withdraw_days),
                    )
                except Exception:
                    pass

        seven_days_buffer = today - timedelta(days=expiry_days + auto_withdraw_days)
        pending_auto_withdraw = self.search([
            ("state", "in", ("draft", "submitted", "under_review")),
            ("request_date", "<=", seven_days_buffer),
            ("pending_expiry_notified", "=", True),
        ])

        for req in pending_auto_withdraw:
            req.write({"state": "withdrawn"})
            body = _("Transfer request automatically withdrawn after being pending for too long.")
            req.message_post(body=body)
            if req.active_email_address:
                email_from = self.env.company.email or self.env.user.email_formatted or "noreply@bunnabank.com"
                try:
                    mail_values = {
                        "subject": _("Transfer Request Automatically Withdrawn - %s") % req.name,
                        "body_html": Markup("<div><p>%s</p></div>") % body,
                        "email_to": req.active_email_address,
                        "email_from": email_from,
                    }
                    mail = self.env["mail.mail"].sudo().create(mail_values)
                    try:
                        mail.send()
                    except Exception:
                        pass
                except Exception:
                    pass
            if req.employee_id and req.employee_id.user_id:
                try:
                    req.activity_feedback(
                        ['mail.mail_activity_data_todo'],
                        feedback=_("Request automatically withdrawn due to non-response.")
                    )
                except Exception:
                    pass
