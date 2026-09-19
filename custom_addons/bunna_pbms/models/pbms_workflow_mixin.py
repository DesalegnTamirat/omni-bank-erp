# -*- coding: utf-8 -*-
import logging
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

from .pbms_access import (
    PBMS_BRANCH_EDITABLE_STATES,
    PBMS_DISTRICT_REVIEW_STATES,
    PBMS_HO_REVIEW_STATES,
    PBMS_SPPMD_REVIEW_STATES,
    PBMS_WORKFLOW_ONLY_FIELDS,
    PBMS_CONTENT_FIELDS,
    PBMS_MONTH_FIELDS,
)


class PbmsWorkflowMixin(models.AbstractModel):
    """Org-unit + cycle + 4-stage approval workflow shared by *every*
    planning format, whether it's a monthly-target grid (Deposit,
    General Expense, ...) or an itemized request list (Manpower, Fixed
    Asset). Kept separate from the monthly-grid fields
    (pbms.plan.line.mixin) so itemized formats don't inherit a grid of
    12 Monetary fields they don't use.
    """
    _name = "pbms.workflow.mixin"
    _description = "PBMS Approval Workflow (abstract)"

    cycle_id = fields.Many2one(
        "pbms.planning.cycle", required=True, index=True,
        default=lambda self: self.env["pbms.planning.cycle"].search(
            [("state", "=", "open")], limit=1),
    )
    cycle_state = fields.Selection(
        related="cycle_id.state",
        string="Cycle Status",
        store=True,
        readonly=True,
        index=True,
    )
    is_cycle_open = fields.Boolean(
        string="Cycle Open for Input",
        compute="_compute_is_cycle_open",
        store=True,
        index=True,
        help="True if the associated planning cycle is officially open for unit input.",
    )

    @api.depends("cycle_id.state")
    def _compute_is_cycle_open(self):
        for rec in self:
            rec.is_cycle_open = bool(rec.cycle_id and rec.cycle_id.state == "open")
    @api.model
    def _default_org_unit_id(self):
        user = self.env.user
        if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
            return user.default_operating_unit_id
        ou_ids = user._pbms_operating_unit_ids() if hasattr(user, "_pbms_operating_unit_ids") else []
        if ou_ids:
            return ou_ids[0]
        return False

    org_unit_id = fields.Many2one(
        "operating.unit", string="Org Unit", required=True, index=True,
        default=_default_org_unit_id,
        help="Branch / District Office / Head Office work unit, from the "
             "Bank's HR org structure (hr_employee_custom).",
    )
    org_unit_type = fields.Selection(related="org_unit_id.work_unit_type", store=True, index=True)
    district_id = fields.Many2one(
        "operating.unit", string="District", store=True, index=True,
        compute="_compute_district_id",
        help="Nearest ancestor operating unit whose Work Unit Type is "
             "'District Office', found by walking up parent_unit. Stored "
             "purely so dashboard/consolidation queries can filter/group "
             "on it directly instead of joining through parent_unit at "
             "read time.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("info_requested", "Information Requested"),
            ("returned", "Returned for Revision"),
            ("rejection_recommended", "Rejection Recommended"),
            ("rejected", "Rejected"),
            ("district_approved", "District Approved"),
            ("district_endorsed", "District Endorsed"),
            ("chief_review", "Respective Chief Review"),
            ("people_solutions_review", "People Solutions Review"),
            ("cpco_review", "CPCO Review"),
            ("board_ceo_approval", "Pending CEO / Board Approval"),
            ("committee_review", "Budget Hiring Committee Review"),
            ("hr_fulfillment", "HR Sourcing & Fulfillment"),
            ("ceo_approval", "Pending CEO Approval"),
            ("ho_reviewed", "Head Office Reviewed"),
            ("ho_endorse", "HO Verification / Endorsement"),
            ("cpco_endorse", "CPCO Final Endorsement"),
            ("approved", "Approved"),
        ],
        default="draft", required=True, tracking=True, index=True,
    )

    submitted_by = fields.Many2one("res.users", string="Submitted By", readonly=True, copy=False)
    submitted_date = fields.Datetime(string="Submitted Date", readonly=True, copy=False)
    district_reviewer_id = fields.Many2one("res.users", string="District Reviewer", readonly=True, copy=False)
    district_review_date = fields.Datetime(string="District Review Date", readonly=True, copy=False)
    district_approval_date = fields.Datetime(related="district_review_date", string="District Approval Date", readonly=True)
    district_comment = fields.Text(string="District Comment")
    chief_approver_id = fields.Many2one("res.users", string="Respective Chief Approver", readonly=True, copy=False)
    chief_approval_date = fields.Datetime(string="Chief Approval Date", readonly=True, copy=False)
    chief_comment = fields.Text(string="Chief Comment")
    people_solutions_reviewer_id = fields.Many2one("res.users", string="People Solutions Reviewer", readonly=True, copy=False)
    people_solutions_review_date = fields.Datetime(string="People Solutions Review Date", readonly=True, copy=False)
    people_solutions_comment = fields.Text(string="People Solutions Comment")
    cpco_reviewer_id = fields.Many2one("res.users", string="CPCO Reviewer", readonly=True, copy=False)
    cpco_submission_date = fields.Datetime(string="CPCO Submission Date", readonly=True, copy=False)
    cpco_comment = fields.Text(string="CPCO Comment")
    ho_reviewer_id = fields.Many2one("res.users", string="Head Office Reviewer", readonly=True, copy=False)
    ho_review_date = fields.Datetime(string="HO Review Date", readonly=True, copy=False)
    ho_comment = fields.Text(string="HO Comment")
    committee_approver_id = fields.Many2one("res.users", string="Committee Approver", readonly=True, copy=False)
    committee_approval_date = fields.Datetime(string="Committee Approval Date", readonly=True, copy=False)
    committee_comment = fields.Text(string="Committee Comment")
    ceo_approver_id = fields.Many2one("res.users", string="CEO Approver", readonly=True, copy=False)
    ceo_approval_date = fields.Datetime(string="CEO Approval Date", readonly=True, copy=False)
    ceo_comment = fields.Text(string="CEO Comment")
    ho_endorser_id = fields.Many2one("res.users", string="HO Endorser", readonly=True, copy=False)
    ho_endorse_date = fields.Datetime(string="HO Endorsement Date", readonly=True, copy=False)
    cpco_endorser_id = fields.Many2one("res.users", string="CPCO Endorser", readonly=True, copy=False)
    cpco_endorse_date = fields.Datetime(string="CPCO Endorsement Date", readonly=True, copy=False)
    approver_id = fields.Many2one("res.users", string="SPPMD Approver", readonly=True, copy=False)
    approval_date = fields.Datetime(string="Approval Date", readonly=True, copy=False)
    return_reason = fields.Text(string="Return Reason", copy=False)


    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, index=True,
    )

    is_my_unit = fields.Boolean(
        string="My Work Unit Plan",
        compute="_compute_is_my_unit",
        search="_search_is_my_unit",
    )

    def _compute_is_my_unit(self):
        user_unit_ids = self.env.user._pbms_operating_unit_ids()
        for line in self:
            line.is_my_unit = bool(line.org_unit_id and line.org_unit_id.id in user_unit_ids)

    def _search_is_my_unit(self, operator, value):
        user_unit_ids = self.env.user._pbms_operating_unit_ids()
        if (operator in ("=", "!=") and value) or (operator in ("in", "not in") and True in value):
            op = "in" if operator in ("=", "in") else "not in"
            return [("org_unit_id", op, user_unit_ids)]
        return [("org_unit_id", "not in", user_unit_ids)]

    can_use_reviewer_actions = fields.Boolean(
        string="Can Use Reviewer Actions",
        compute="_compute_reviewer_actions_access",
        compute_sudo=False,
    )

    @api.depends("state")
    def _compute_reviewer_actions_access(self):
        for rec in self:
            if rec.state in ("draft", "approved", "rejected"):
                rec.can_use_reviewer_actions = False
            else:
                rec.can_use_reviewer_actions = rec._pbms_can_use_reviewer_wizards()

    plan_category_title = fields.Char(
        string="Plan Category Title",
        compute="_compute_plan_notification_details",
        store=False,
    )
    plan_summary_metrics_html = fields.Html(
        string="Plan Summary Metrics HTML",
        compute="_compute_plan_notification_details",
        store=False,
        sanitize=False,
    )

    def _compute_plan_notification_details(self):
        category_names = {
            "deposit": _("Deposit Mobilization Plan"),
            "customer_base": _("Customer Base Expansion Plan"),
            "fx": _("Foreign Exchange (FX) Mobilization Plan"),
            "digital_banking": _("Digital Banking Plan"),
            "general_expense": _("General Expense Budget Plan"),
            "manpower": _("Workforce / Manpower Plan"),
            "fixed_asset": _("Fixed Asset Acquisition Plan"),
        }

        for rec in self:
            currency = rec.currency_id.name if (hasattr(rec, "currency_id") and rec.currency_id) else "ETB"
            cat_field = getattr(rec, "category", False)

            # Determine which categories actually have planned lines or data
            present_line_types = []
            if hasattr(rec, "line_ids") and rec.line_ids:
                for c in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"):
                    if any(l.line_type == c for l in rec.line_ids):
                        present_line_types.append(c)

            if not present_line_types:
                for c in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"):
                    has_data = False
                    if c == "deposit" and (getattr(rec, "deposit_line_ids", False) or (getattr(rec, "deposit_annual_total", 0.0) or 0.0) > 0):
                        has_data = True
                    elif c == "customer_base" and (getattr(rec, "customer_base_line_ids", False) or (getattr(rec, "customer_base_annual_total", 0.0) or 0.0) > 0):
                        has_data = True
                    elif c == "fx" and (getattr(rec, "fx_line_ids", False) or (getattr(rec, "fx_annual_total", 0.0) or 0.0) > 0):
                        has_data = True
                    elif c == "digital_banking" and (getattr(rec, "digital_banking_line_ids", False) or (getattr(rec, "digital_banking_annual_total", 0.0) or 0.0) > 0):
                        has_data = True
                    elif c == "general_expense" and (getattr(rec, "expense_line_ids", False) or (getattr(rec, "expense_annual_total", 0.0) or 0.0) > 0):
                        has_data = True
                    elif c == "manpower" and (getattr(rec, "manpower_line_ids", False) or (getattr(rec, "manpower_total_headcount", 0) or 0) > 0):
                        has_data = True
                    elif c == "fixed_asset" and (getattr(rec, "fixed_asset_line_ids", False) or (getattr(rec, "fixed_asset_total_quantity", 0) or 0) > 0):
                        has_data = True
                    if has_data:
                        present_line_types.append(c)

            # Determine dynamic title and active categories
            ctx_cat = self.env.context.get("notification_category")
            if ctx_cat and ctx_cat in category_names:
                rec.plan_category_title = category_names[ctx_cat]
                active_categories = [ctx_cat]
            elif cat_field and not self.env.context.get("is_planning_request"):
                # On a dedicated category card, title and metrics strictly reflect this card's category!
                rec.plan_category_title = category_names.get(cat_field, cat_field.replace("_", " ").title())
                active_categories = [cat_field]
            elif len(present_line_types) == 1:
                cat_key = present_line_types[0]
                rec.plan_category_title = category_names.get(cat_key, cat_key.replace("_", " ").title())
                active_categories = [cat_key]
            elif len(present_line_types) > 1:
                rec.plan_category_title = _("Annual Business Plan")
                active_categories = present_line_types
            elif cat_field and cat_field in category_names:
                rec.plan_category_title = category_names[cat_field]
                active_categories = [cat_field]
            elif cat_field:
                sel_dict = dict(rec._fields["category"].selection) if hasattr(rec, "_fields") and "category" in rec._fields else {}
                rec.plan_category_title = sel_dict.get(cat_field, cat_field.replace("_", " ").title())
                active_categories = [cat_field]
            else:
                rec.plan_category_title = _("Planning Request")
                active_categories = []

            # 2. Build HTML rows strictly for the card's own category
            rows = []
            for cat_key in active_categories:
                if cat_key == "deposit":
                    is_monetary = getattr(rec, "is_deposit_monetary", True)
                    total = getattr(rec, "deposit_annual_total", 0.0) or 0.0
                    cnt = getattr(rec, "deposit_line_count", 0) or len(getattr(rec, "deposit_line_ids", []))
                    formatted_total = f"{total:,.2f} {currency}" if is_monetary else f"{int(total):,}"
                    rows.append((_("Annual Deposit Target"), f"{formatted_total} ({cnt} Products Planned)", "#425727"))
                elif cat_key == "customer_base":
                    total = getattr(rec, "customer_base_annual_total", 0.0) or 0.0
                    cnt = getattr(rec, "customer_base_line_count", 0) or len(getattr(rec, "customer_base_line_ids", []))
                    rows.append((_("Annual Customer Target"), f"{int(total):,} Accounts ({cnt} Segments)", "#726732"))
                elif cat_key == "fx":
                    total = getattr(rec, "fx_annual_total", 0.0) or 0.0
                    cnt = getattr(rec, "fx_line_count", 0) or len(getattr(rec, "fx_line_ids", []))
                    rows.append((_("Annual FX Target"), f"{total:,.2f} USD ({cnt} Sources Planned)", "#C17540"))
                elif cat_key == "digital_banking":
                    total = getattr(rec, "digital_banking_annual_total", 0.0) or 0.0
                    cnt = getattr(rec, "digital_banking_line_count", 0) or len(getattr(rec, "digital_banking_line_ids", []))
                    rows.append((_("Annual Digital Target"), f"{total:,.2f} ({cnt} Channels Planned)", "#541718"))
                elif cat_key == "general_expense":
                    total = getattr(rec, "expense_annual_total", 0.0) or 0.0
                    cnt = getattr(rec, "expense_line_count", 0) or len(getattr(rec, "expense_line_ids", []))
                    rows.append((_("Total Expense Budget"), f"{total:,.2f} {currency} ({cnt} Accounts)", "#541718"))
                elif cat_key == "manpower":
                    headcount = getattr(rec, "manpower_total_headcount", 0) or 0
                    cost = getattr(rec, "total_manpower_cost", 0.0) or 0.0
                    rows.append((_("Requested Workforce Headcount"), f"{headcount} Positions (Estimated Cost: {cost:,.2f} {currency})", "#1E2917"))
                    if rec.state in ("hr_fulfillment", "ceo_approval", "approved"):
                        app_hc = getattr(rec, "manpower_approved_headcount", 0) or 0
                        if app_hc:
                            rows.append((_("Committee Approved Headcount"), f"{app_hc} Positions", "#425727"))
                    if rec.state in ("ceo_approval", "approved") and getattr(rec, "manpower_external_vacancy_total", 0):
                        rows.append((_("External Vacancy Planned"), f"{rec.manpower_external_vacancy_total} Positions (Requires CEO Approval)", "#B45309"))
                elif cat_key == "fixed_asset":
                    items = getattr(rec, "fixed_asset_total_quantity", 0) or 0
                    cost = getattr(rec, "total_fixed_asset_cost", 0.0) or 0.0
                    rows.append((_("Fixed Asset Items Requested"), f"{items} Items (Estimated Cost: {cost:,.2f} {currency})", "#726732"))

            html_parts = []
            for label, val, color in rows:
                html_parts.append(
                    f'<tr style="border-bottom: 1px solid #EEEEEE;">'
                    f'<td style="padding: 10px; font-weight: bold; width: 40%; color: #555555;">{label}:</td>'
                    f'<td style="padding: 10px; font-weight: bold; color: {color};">{val}</td>'
                    f'</tr>'
                )
            rec.plan_summary_metrics_html = Markup("".join(html_parts))

    def _get_plan_notification_summary_text(self):
        self.ensure_one()
        currency = self.currency_id.name if (hasattr(self, "currency_id") and self.currency_id) else "ETB"
        cat_field = getattr(self, "category", False)

        present_line_types = []
        if hasattr(self, "line_ids") and self.line_ids:
            for c in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"):
                if any(l.line_type == c for l in self.line_ids):
                    present_line_types.append(c)

        if not present_line_types:
            for c in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"):
                has_data = False
                if c == "deposit" and (getattr(self, "deposit_line_ids", False) or (getattr(self, "deposit_annual_total", 0.0) or 0.0) > 0):
                    has_data = True
                elif c == "customer_base" and (getattr(self, "customer_base_line_ids", False) or (getattr(self, "customer_base_annual_total", 0.0) or 0.0) > 0):
                    has_data = True
                elif c == "fx" and (getattr(self, "fx_line_ids", False) or (getattr(self, "fx_annual_total", 0.0) or 0.0) > 0):
                    has_data = True
                elif c == "digital_banking" and (getattr(self, "digital_banking_line_ids", False) or (getattr(self, "digital_banking_annual_total", 0.0) or 0.0) > 0):
                    has_data = True
                elif c == "general_expense" and (getattr(self, "expense_line_ids", False) or (getattr(self, "expense_annual_total", 0.0) or 0.0) > 0):
                    has_data = True
                elif c == "manpower" and (getattr(self, "manpower_line_ids", False) or (getattr(self, "manpower_total_headcount", 0) or 0) > 0):
                    has_data = True
                elif c == "fixed_asset" and (getattr(self, "fixed_asset_line_ids", False) or (getattr(self, "fixed_asset_total_quantity", 0) or 0) > 0):
                    has_data = True
                if has_data:
                    present_line_types.append(c)

        ctx_cat = self.env.context.get("notification_category")
        if ctx_cat:
            active_categories = [ctx_cat]
        elif cat_field and not self.env.context.get("is_planning_request"):
            active_categories = [cat_field]
        elif len(present_line_types) == 1:
            active_categories = [present_line_types[0]]
        elif len(present_line_types) > 1:
            active_categories = present_line_types
        elif cat_field:
            active_categories = [cat_field]
        else:
            active_categories = []

        lines = []
        for cat_key in active_categories:
            if cat_key == "deposit":
                is_monetary = getattr(self, "is_deposit_monetary", True)
                total = getattr(self, "deposit_annual_total", 0.0) or 0.0
                cnt = getattr(self, "deposit_line_count", 0) or len(getattr(self, "deposit_line_ids", []))
                val = f"{total:,.2f} {currency}" if is_monetary else f"{int(total):,}"
                lines.append(f"<b>Annual Deposit Target:</b> {val} ({cnt} Products Planned)")
            elif cat_key == "customer_base":
                total = getattr(self, "customer_base_annual_total", 0.0) or 0.0
                cnt = getattr(self, "customer_base_line_count", 0) or len(getattr(self, "customer_base_line_ids", []))
                lines.append(f"<b>Annual Customer Target:</b> {int(total):,} Accounts ({cnt} Segments Planned)")
            elif cat_key == "fx":
                total = getattr(self, "fx_annual_total", 0.0) or 0.0
                cnt = getattr(self, "fx_line_count", 0) or len(getattr(self, "fx_line_ids", []))
                lines.append(f"<b>Annual FX Target:</b> {total:,.2f} USD ({cnt} Sources Planned)")
            elif cat_key == "digital_banking":
                total = getattr(self, "digital_banking_annual_total", 0.0) or 0.0
                cnt = getattr(self, "digital_banking_line_count", 0) or len(getattr(self, "digital_banking_line_ids", []))
                lines.append(f"<b>Annual Digital Target:</b> {total:,.2f} ({cnt} Channels Planned)")
            elif cat_key == "general_expense":
                total = getattr(self, "expense_annual_total", 0.0) or 0.0
                cnt = getattr(self, "expense_line_count", 0) or len(getattr(self, "expense_line_ids", []))
                lines.append(f"<b>Total Expense Budget:</b> {total:,.2f} {currency} ({cnt} Accounts Planned)")
            elif cat_key == "manpower":
                headcount = getattr(self, "manpower_total_headcount", 0) or 0
                cost = getattr(self, "total_manpower_cost", 0.0) or 0.0
                lines.append(f"<b>Requested Workforce Headcount:</b> {headcount} Position(s) (Est. Cost: {cost:,.2f} {currency})")
                if self.state in ("hr_fulfillment", "ceo_approval", "approved"):
                    app_hc = getattr(self, "manpower_approved_headcount", 0) or 0
                    if app_hc:
                        lines.append(f"<b>Committee Approved Headcount:</b> {app_hc} Position(s)")
                if self.state in ("ceo_approval", "approved") and getattr(self, "manpower_external_vacancy_total", 0):
                    lines.append(f"<b>External Vacancy Planned:</b> {self.manpower_external_vacancy_total} Position(s) (Requires CEO Approval)")
            elif cat_key == "fixed_asset":
                items = getattr(self, "fixed_asset_total_quantity", 0) or 0
                cost = getattr(self, "total_fixed_asset_cost", 0.0) or 0.0
                lines.append(f"<b>Fixed Asset Items Requested:</b> {items} Item(s) (Est. Cost: {cost:,.2f} {currency})")

        return "<br/>".join(lines)

    def _get_plan_submission_email_body(self):
        self.ensure_one()
        self._compute_plan_notification_details()
        cat_title = self.plan_category_title or _("Plan & Budget Request")
        req_no = getattr(self, "request_number", "") or "N/A"
        unit_name = self.org_unit_id.display_name if self.org_unit_id else "N/A"
        cycle_name = self.cycle_id.name if self.cycle_id else "N/A"
        submitter = self.submitted_by.name if self.submitted_by else (self.env.user.name or "N/A")
        metrics_html = self.plan_summary_metrics_html or ""
        rec_id = self.id
        model_name = self._name

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #541718;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #425727; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">{cat_title} Submission Notification</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Reviewer / Colleague,</p>'
            f'<p>A new <b>{cat_title}</b> has been successfully submitted and is now pending your review and endorsement.</p>'
            f'<table style="width: 100%; border-collapse: collapse; margin: 16px 0; background-color: #FAFAFA; border-radius: 6px;">'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; width: 35%; color: #555555;">Request Number:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #541718;">{req_no}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Plan Category / Scope:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #425727;">{cat_title}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Work Unit:</td>'
            f'<td style="padding: 10px;">{unit_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Planning Cycle:</td>'
            f'<td style="padding: 10px;">{cycle_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Submitted By:</td>'
            f'<td style="padding: 10px;">{submitter}</td></tr>'
            f'{metrics_html}'
            f'</table>'
            f'<p style="margin-top: 20px;">Please log in to the PBMS portal to review the proposed targets, justifications, and quarterly distributions.</p>'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="/web#id={rec_id}&amp;model={model_name}&amp;view_type=form" '
            f'style="background-color: #541718; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'Review {cat_title}'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | Strategic Planning &amp; Performance Management Directorate (SPPMD)<br/>'
            f'This is an automated system notification from Bunna PBMS.'
            f'</td></tr>'
            f'</table>'
            f'</td></tr></table></div>'
        )

    def _get_plan_review_email_body(self, stage_name):
        self.ensure_one()
        self._compute_plan_notification_details()
        cat_title = self.plan_category_title or _("Plan & Budget Request")
        req_no = getattr(self, "request_number", "") or "N/A"
        unit_name = self.org_unit_id.display_name if self.org_unit_id else "N/A"
        cycle_name = self.cycle_id.name if self.cycle_id else "N/A"
        metrics_html = self.plan_summary_metrics_html or ""
        rec_id = self.id
        model_name = self._name

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #C17540;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #C17540; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">Action Required: {cat_title} Pending Review ({stage_name})</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Reviewer,</p>'
            f'<p>A <b>{cat_title}</b> has progressed to stage <b>{stage_name}</b> and requires your review and endorsement.</p>'
            f'<table style="width: 100%; border-collapse: collapse; margin: 16px 0; background-color: #FAFAFA; border-radius: 6px;">'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; width: 35%; color: #555555;">Request Number:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #541718;">{req_no}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Work Unit:</td>'
            f'<td style="padding: 10px;">{unit_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Planning Cycle:</td>'
            f'<td style="padding: 10px;">{cycle_name}</td></tr>'
            f'{metrics_html}'
            f'</table>'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="/web#id={rec_id}&amp;model={model_name}&amp;view_type=form" '
            f'style="background-color: #C17540; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'Review {cat_title}'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | Strategic Planning &amp; Performance Management Directorate (SPPMD)'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    def _get_plan_approved_email_body(self, stage_label, is_final=False):
        self.ensure_one()
        self._compute_plan_notification_details()
        cat_title = self.plan_category_title or _("Plan & Budget Request")
        req_no = getattr(self, "request_number", "") or "N/A"
        unit_name = self.org_unit_id.display_name if self.org_unit_id else "N/A"
        cycle_name = self.cycle_id.name if self.cycle_id else "N/A"
        metrics_html = self.plan_summary_metrics_html or ""
        status_text = _("Final Executive Approval Granted (Official ABP)") if is_final else _("Approved (%s)") % stage_label
        rec_id = self.id
        model_name = self._name

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #425727;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #425727; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">{cat_title} Approval Notification</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Submitter / Stakeholder,</p>'
            f'<p>Your <b>{cat_title}</b> has been successfully approved ({status_text}).</p>'
            f'<table style="width: 100%; border-collapse: collapse; margin: 16px 0; background-color: #EDF3E8; border: 1px solid #C8DCB8; border-radius: 6px;">'
            f'<tr style="border-bottom: 1px solid #C8DCB8;">'
            f'<td style="padding: 10px; font-weight: bold; width: 35%; color: #555555;">Request Number:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #541718;">{req_no}</td></tr>'
            f'<tr style="border-bottom: 1px solid #C8DCB8;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Work Unit:</td>'
            f'<td style="padding: 10px;">{unit_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #C8DCB8;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Planning Cycle:</td>'
            f'<td style="padding: 10px;">{cycle_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #C8DCB8;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Status:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #425727;">{status_text}</td></tr>'
            f'{metrics_html}'
            f'</table>'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="/web#id={rec_id}&amp;model={model_name}&amp;view_type=form" '
            f'style="background-color: #425727; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'View Approved {cat_title}'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | Strategic Planning &amp; Performance Management Directorate (SPPMD)'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    @api.depends("org_unit_id", "org_unit_id.parent_unit", "org_unit_id.work_unit_type")
    def _compute_district_id(self):
        for line in self:
            unit = line.org_unit_id
            line.district_id = self._find_district_ancestor(unit)

    @api.model
    def _find_district_ancestor(self, unit):
        seen = self.env["operating.unit"]
        current = unit
        for _i in range(20):
            if not current or current in seen:
                return self.env["operating.unit"]
            if current.work_unit_type == "district_office":
                return current
            seen |= current
            current = current.parent_unit
        return self.env["operating.unit"]

    def _get_duplicate_domain(self):
        self.ensure_one()
        return [("cycle_id", "=", self.cycle_id.id), ("org_unit_id", "=", self.org_unit_id.id)]

    def _check_editable(self):
        for line in self:
            if not line.cycle_id or line.cycle_id.state != "open":
                cycle_label = dict(line.cycle_id._fields["state"].selection).get(line.cycle_id.state, line.cycle_id.state) if line.cycle_id else _("Unknown")
                raise UserError(_(
                    "Planning cycle '%s' is not open for unit input (current status: %s). "
                    "Branch users cannot input or submit plan data until the cycle is officially opened.",
                    line.cycle_id.name if line.cycle_id else "",
                    cycle_label
                ))

    def _protected_write_fields(self):
        return []

    def _is_own_operating_unit_plan(self):
        self.ensure_one()
        if not self.org_unit_id:
            return True
        user = self.env.user
        if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return True
        user_units = user._pbms_operating_unit_ids()
        if self.org_unit_id.id in user_units:
            return True
        # If user has no operating units configured, allow editing their own draft plans
        if not user_units and self.state in PBMS_BRANCH_EDITABLE_STATES:
            if (self.create_uid and self.create_uid == user) or (self.submitted_by and self.submitted_by == user):
                return True
        return False

    def _is_people_solutions_plan(self):
        """Check if this workforce plan belongs to or was initiated by People Solutions Directorate."""
        self.ensure_one()
        user = self.env.user

        # 1. Operating unit matches People Solutions / HR
        if self.org_unit_id:
            ou_name = (self.org_unit_id.name or "").lower()
            if ou_name in ("hr", "people solutions", "people solutions directorate", "human resources", "people & culture"):
                return True
            if "people" in ou_name and "solution" in ou_name:
                return True
            ps_users = self._get_users_with_group("bunna_pbms.group_pbms_people_solutions")
            mgr_users = self._get_users_with_group("bunna_pbms.group_pbms_manager")
            direct_ps_users = ps_users - mgr_users
            if any(u in direct_ps_users for u in self.org_unit_id.user_ids):
                return True

        # 2. Submitter is directly in People Solutions group (and not manager/admin)
        if user.has_group("bunna_pbms.group_pbms_people_solutions"):
            if not user.has_group("bunna_pbms.group_pbms_manager") and not user._is_admin():
                return True

        # 3. Creator is in People Solutions group (and not manager/admin)
        if self.create_uid and self.create_uid.has_group("bunna_pbms.group_pbms_people_solutions"):
            if not self.create_uid.has_group("bunna_pbms.group_pbms_manager") and not self.create_uid._is_admin():
                return True

        return False

    def _is_child_operating_unit_plan(self):
        """True when the plan's operating unit belongs to the user's district or parent operating unit."""
        self.ensure_one()
        user = self.env.user
        if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su or user._pbms_is_ho_reviewer():
            return True
        user_unit_ids = set(user._pbms_operating_unit_ids())
        if not user_unit_ids or not self.org_unit_id:
            # If district reviewer has no explicit operating units configured, allow reviewing child branches
            if user._pbms_is_district_reviewer() and self.org_unit_id.work_unit_type in ("branch", "sub_branch", "service_center"):
                return True
            if user.has_group("bunna_pbms.group_pbms_respective_chief"):
                return bool(self.org_unit_id and self.org_unit_id.id in user._pbms_child_operating_unit_ids())
            return False

        # Respective Chief scoping is strictly BY MANAGER, not by parent operating unit!
        if user.has_group("bunna_pbms.group_pbms_respective_chief") and not user.has_group("bunna_pbms.group_pbms_district_reviewer"):
            return bool(self.org_unit_id and self.org_unit_id.id in user._pbms_child_operating_unit_ids())

        # 1. Direct parent check
        if self.org_unit_id.parent_unit and self.org_unit_id.parent_unit.id in user_unit_ids:
            return True

        # 2. District ancestor check
        district = self.district_id or self._find_district_ancestor(self.org_unit_id)
        if district and district.id in user_unit_ids:
            return True

        # 3. Hierarchy walk
        curr = self.org_unit_id.parent_unit
        while curr:
            if curr.id in user_unit_ids:
                return True
            curr = curr.parent_unit

        # 4. If district reviewer has a district office in assigned units and plan is a branch
        if user._pbms_is_district_reviewer():
            user_ous = self.env["operating.unit"].browse(list(user_unit_ids))
            if any(ou.work_unit_type == "district_office" for ou in user_ous):
                if district and district.id in user_unit_ids:
                    return True
                if any(ou == district for ou in user_ous):
                    return True

        # 5. Descendant check via _pbms_child_operating_unit_ids()
        if hasattr(user, "_pbms_child_operating_unit_ids") and self.org_unit_id.id in user._pbms_child_operating_unit_ids():
            return True

        return False

    def _pbms_can_edit_plan_content(self):
        """Whether the current user may change plan figures / requirement lines.
        Strict view-only enforcement: once an actor takes their workflow action
        (submit, endorse, approve, escalate), the plan becomes strictly view-only."""
        self.ensure_one()
        user = self.env.user
        state = self.state

        if self.env.context.get("pbms_target_cascade") or self.env.context.get("bypass_plan_lock"):
            return True

        if state in ("approved", "rejected"):
            return False

        # Once approved by CEO, workforce plan records and lines are strictly frozen (read-only)
        if getattr(self, "category", False) == "manpower" and state in ("ho_endorse", "cpco_endorse"):
            return False

        # SPPMD Administrator / System Administrator can edit any non-finalized plan across all units
        if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return True

        # SPPMD Approver can edit Head Office plans before final approval
        if (
            user._pbms_is_sppmd_approver()
            and self.org_unit_type == "head_office"
            and state in ("ho_reviewed", "submitted", "info_requested")
        ):
            return True

        # Own operating unit plan before submission (branch, head office, or reviewer editing own unit's draft plan)
        if self._is_own_operating_unit_plan() and state in PBMS_BRANCH_EDITABLE_STATES:
            if self.cycle_id and self.cycle_id.state != "open":
                return False
            return True

        # Head Office Functional Reviewer during HO review stage on authorized category plans
        if user._pbms_is_ho_reviewer():
            cat = getattr(self, "category", False)
            if not cat or cat in user._pbms_allowed_categories():
                # On branch plans after district endorsement:
                if self._is_child_operating_unit_plan() or self.org_unit_type != "head_office":
                    if state in ("district_approved", "district_endorsed"):
                        return True
                # On direct head office unit plans:
                else:
                    if self._is_own_operating_unit_plan() and state in PBMS_BRANCH_EDITABLE_STATES:
                        return True
                    if state in ("submitted", "info_requested"):
                        return True

        # Respective Chief during chief_review stage on Manpower plans (can reduce headcount on child units)
        if getattr(self, "category", False) == "manpower" and state == "chief_review":
            if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True
            if user._pbms_is_respective_chief() and (
                self._is_child_operating_unit_plan()
                or (self.org_unit_id and self.org_unit_id.id in user._pbms_child_operating_unit_ids())
            ):
                return True

        # People Solutions Directorate during people_solutions_review stage on Manpower plans
        if getattr(self, "category", False) == "manpower" and state == "people_solutions_review":
            if user._pbms_is_people_solutions() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True

        # CPCO during cpco_review stage on Manpower plans
        if getattr(self, "category", False) == "manpower" and state == "cpco_review":
            if user._pbms_is_cpco() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True

        # Budget Hiring / Review Committee during committee review stage
        if user._pbms_is_budget_hiring_committee() and state == "committee_review" and getattr(self, "category", False) in ("manpower", "general_expense", "fixed_asset"):
            return True

        # HR Reviewer / CPCO / People Solutions during HR fulfillment stage
        if (user._pbms_is_people_solutions() or user._pbms_is_cpco() or user._pbms_is_ho_reviewer() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su) and state == "hr_fulfillment" and getattr(self, "category", False) == "manpower":
            return True

        # CEO during ceo_approval / board_ceo_approval stage on Manpower plans
        if getattr(self, "category", False) == "manpower" and state in ("ceo_approval", "board_ceo_approval"):
            if user._pbms_is_ceo() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True

        # District Reviewer on direct child operating unit plans (only pending review) or own operating unit (only draft)
        if user._pbms_is_district_reviewer():
            if self._is_child_operating_unit_plan() and state in PBMS_DISTRICT_REVIEW_STATES:
                return True
            if self._is_own_operating_unit_plan() and state in PBMS_BRANCH_EDITABLE_STATES:
                return True

        # Branch / Head Office User on own operating unit before submission (draft, returned, info_requested)
        if state in PBMS_BRANCH_EDITABLE_STATES:
            # Branch users cannot input or edit data unless the planning cycle is officially open!
            if self.cycle_id and self.cycle_id.state != "open":
                return False
            if self._is_own_operating_unit_plan():
                return True

        return False

    def _pbms_can_delete_plan(self):
        self.ensure_one()
        user = self.env.user
        # SPPMD Administrator / System Administrator / Superuser can delete plans from any workflow state
        if self.env.is_admin() or user._pbms_is_sppmd_admin() or self.env.su:
            return True

        # Regular users can only delete their own draft plans before submission
        return self._is_own_operating_unit_plan() and self.state == "draft"

    def _pbms_can_submit_plan(self):
        self.ensure_one()
        user = self.env.user
        if self.cycle_id and self.cycle_id.state != "open":
            return False
        if self.state not in PBMS_BRANCH_EDITABLE_STATES:
            return False
        if self.env.is_admin() or user._pbms_is_sppmd_admin() or self.env.su:
            return True
        return self._is_own_operating_unit_plan()


    def _pbms_can_district_review_plan(self):
        self.ensure_one()
        if self.env.user._pbms_is_sppmd_admin() or self.env.is_admin():
            return self.state in PBMS_DISTRICT_REVIEW_STATES
        if not self.env.user._pbms_is_district_reviewer():
            return False
        if self.state not in PBMS_DISTRICT_REVIEW_STATES:
            return False
        return self._is_child_operating_unit_plan() or self._is_own_operating_unit_plan()

    def _pbms_can_ho_review_plan(self):
        self.ensure_one()
        user = self.env.user
        if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return self.state in (PBMS_HO_REVIEW_STATES | {"hr_fulfillment", "ho_endorse"})

        cat = getattr(self, "category", False)
        # Check if user is designated reviewer for this category and plan in Planning Config
        is_designated = False
        ConfigModel = self.env.get("pbms.planning.config")
        if ConfigModel is not None and cat:
            info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
            if user in info.get("users", self.env["res.users"]):
                is_designated = True
            elif info.get("ou") and info["ou"].id in user._pbms_operating_unit_ids():
                is_designated = True
            elif info.get("dept") and user.employee_id and user.employee_id.department_id and user.employee_id.department_id.id == info["dept"].id:
                is_designated = True

        if not (user._pbms_is_ho_reviewer() or is_designated):
            return False

        if cat == "manpower":
            if self.state == "ho_endorse":
                return True
            if self.org_unit_type == "head_office" and self.state in PBMS_DISTRICT_REVIEW_STATES:
                return self._is_own_operating_unit_plan() or self._is_child_operating_unit_plan() or user._pbms_is_sppmd_admin()
            return False

        if cat and cat not in user._pbms_allowed_categories() and not is_designated:
            return False

        # Branch plans for general expense and fixed asset must be approved by district first (unless reviewed directly by designated reviewer)
        if self.org_unit_type not in ("head_office", "district_office") and cat in ("general_expense", "fixed_asset") and not is_designated:
            if self.state not in ("district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed", "approved"):
                return False

        if self.state not in (PBMS_HO_REVIEW_STATES | {"hr_fulfillment", "ho_endorse", "ho_reviewed"}):
            return False
        return True

    def _pbms_can_sppmd_review_plan(self):
        self.ensure_one()
        return (
            (self.env.user._pbms_is_sppmd_approver() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin())
            and (self.org_unit_type in ("district_office", "head_office", "regional_office") or getattr(self, "category", False) in ("manpower", "general_expense", "fixed_asset"))
            and self.state in PBMS_SPPMD_REVIEW_STATES
        )

    def _pbms_can_use_reviewer_wizards(self):
        self.ensure_one()
        if self.env.user._pbms_is_sppmd_admin() or self.env.is_admin():
            return True
        return (
            self._pbms_can_district_review_plan()
            or self._pbms_can_ho_review_plan()
            or self._pbms_can_sppmd_review_plan()
            or (getattr(self, "category", False) in ("manpower", "general_expense", "fixed_asset") and self.state == "committee_review" and self.env.user._pbms_is_budget_hiring_committee())
            or (getattr(self, "category", False) == "manpower" and self.state in ("ceo_approval", "board_ceo_approval") and (self.env.user._pbms_is_ceo() or self.env.user._pbms_is_cpco()))
            or (
                getattr(self, "category", False) == "manpower"
                and self.state in ("chief_review", "district_approved", "district_endorsed")
                and self.env.user._pbms_is_respective_chief()
                and (
                    self._is_child_operating_unit_plan()
                    or (self.org_unit_id and self.org_unit_id.id in self.env.user._pbms_child_operating_unit_ids())
                )
            )
            or (getattr(self, "category", False) == "manpower" and self.state == "people_solutions_review" and self.env.user._pbms_is_people_solutions())
            or (getattr(self, "category", False) == "manpower" and self.state in ("cpco_review", "hr_fulfillment") and self.env.user._pbms_is_cpco())
            or (getattr(self, "category", False) == "manpower" and self.state == "ho_endorse" and self._pbms_can_ho_review_plan())
            or (getattr(self, "category", False) == "manpower" and self.state == "cpco_endorse" and self.env.user._pbms_is_cpco())
        )

    def _pbms_check_content_write_access(self, vals):
        if (
            self.env.is_admin()
            or self.env.user._pbms_is_sppmd_admin()
            or self.env.user._pbms_is_sppmd_approver()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
            or "state" in vals
        ):
            return
        # If no budget / financial target content fields are being modified in vals, allow write
        has_content_fields = any(k in PBMS_CONTENT_FIELDS for k in vals)
        if not has_content_fields:
            return

        for record in self:
            if not record._pbms_can_edit_plan_content():
                user = self.env.user
                state_label = dict(record._fields["state"].selection).get(record.state, record.state) if "state" in record._fields else record.state
                unit_name = record.org_unit_id.display_name if record.org_unit_id else _("another Operating Unit")

                # 0. Planning Cycle not open for unit input
                if record.cycle_id and record.cycle_id.state != "open":
                    cycle_label = dict(record.cycle_id._fields["state"].selection).get(record.cycle_id.state, record.cycle_id.state)
                    raise AccessError(_(
                        "Planning cycle '%s' is currently '%s' and is not open for unit input. "
                        "Branch users cannot input or modify plan data until the cycle is officially opened for input."
                    ) % (record.cycle_id.name, cycle_label))

                # 1. Operating Unit mismatch: User does not belong to this operating unit
                if not record._is_own_operating_unit_plan() and not user._pbms_is_sppmd_admin() and not self.env.is_admin():
                    raise AccessError(_(
                        "Operating Unit Access Restriction: You cannot edit this plan because it belongs to '%s', "
                        "which is not assigned to your user account (%s). "
                        "Users can only prepare and edit plans for their own operating unit."
                    ) % (unit_name, user.name))

                # 2. Workflow Stage locking: Operating unit is valid, but plan is under review or approved
                if record.state not in PBMS_BRANCH_EDITABLE_STATES:
                    raise AccessError(_(
                        "Workflow Stage Locked: You cannot modify this plan at the '%s' stage. "
                        "The plan has already been submitted to reviewers. "
                        "Editing is only permitted before submission (Draft), or when returned by a reviewer for revision."
                    ) % state_label)

                # 3. Fallback message
                raise AccessError(_(
                    "You do not have permission to edit this plan at its current workflow stage (%s). "
                    "Editing is allowed before submission (Branch / Head Office User), "
                    "while under review (District / Head Office Reviewer), "
                    "or during SPPMD review."
                ) % state_label)

    def _consolidation_search_domain(self):
        """Extra search domain applied when the workflow auto-consolidates /
        auto-submits consolidated plans. The unified plan model overrides this
        to restrict the follow-up search to the same planning category."""
        return []

    def write(self, vals):
        self._pbms_check_content_write_access(vals)
        protected = self._protected_write_fields()
        is_admin_or_bypass = (
            self.env.is_admin()
            or self.env.user._pbms_is_sppmd_admin()
            or self.env.user._pbms_is_sppmd_approver()
            or self.env.su
            or self.env.context.get("pbms_target_cascade")
            or self.env.context.get("bypass_plan_lock")
            or "state" in vals
        )
        if not is_admin_or_bypass and protected and any(f in vals for f in protected):
            for line in self:
                if line.state in ("district_approved", "district_endorsed", "ho_reviewed", "approved"):
                    if not line._pbms_can_edit_plan_content():
                        raise UserError(_(
                            "This plan has already moved past your review stage. "
                            "You can view it but cannot change plan values."
                        ))
        res = super().write(vals)
        if vals.get("state") == "approved":
            self._update_approved_workforce_establishment()
        return res


    def _log_audit_action(self, action_type, stage_from, stage_to, comment):
        """Permanently record review comments and workflow stage transitions."""
        if "pbms.review.comment" not in self.env:
            return
        AuditModel = self.env["pbms.review.comment"].sudo()
        for line in self:
            if hasattr(line, "review_comment_ids"):
                AuditModel.create({
                    "plan_id": line.id,
                    "user_id": self.env.uid,
                    "date": fields.Datetime.now(),
                    "stage_from": stage_from or (line.state if hasattr(line, "state") else ""),
                    "stage_to": stage_to or (line.state if hasattr(line, "state") else ""),
                    "action_type": action_type or "review_comment",
                    "comment": comment or _("No remarks provided."),
                })

    # =========================================================================
    # AUDIENCE & NOTIFICATION HELPERS (FR-WP-052 to FR-WP-059)
    # =========================================================================
    @api.model
    def _get_users_with_group(self, group_xmlid):
        """Find active users belonging to a group by xmlid in Odoo 19."""
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        users = self.env["res.users"]
        if hasattr(group, "user_ids") and group.user_ids:
            users |= group.user_ids.filtered(lambda u: u.active)
        if hasattr(group, "users") and group.users:
            users |= group.users.filtered(lambda u: u.active)
        if not users:
            try:
                users = self.env["res.users"].search([
                    ("all_group_ids", "in", group.id),
                    ("active", "=", True),
                ])
            except Exception:
                users = self.env["res.users"].search([("active", "=", True)]).filtered(lambda u: u.has_group(group_xmlid))
        return users

    @api.model
    def _get_unit_manager_user(self, unit):
        """Safely resolve user for operating unit manager (manager_id.user_id / user_ids)."""
        if not unit:
            return False
        unit_sudo = unit.sudo()
        if hasattr(unit_sudo, "manager_id") and unit_sudo.manager_id and unit_sudo.manager_id.user_id:
            return unit_sudo.manager_id.user_id
        if hasattr(unit_sudo, "manager_user_id") and unit_sudo.manager_user_id:
            return unit_sudo.manager_user_id
        if hasattr(unit_sudo, "user_ids") and unit_sudo.user_ids:
            return unit_sudo.user_ids[0]
        return False

    @api.model
    def _get_unit_manager_partner(self, unit):
        """Safely resolve partner for operating unit manager."""
        user = self._get_unit_manager_user(unit)
        if user and user.partner_id:
            return user.partner_id
        if unit:
            unit_sudo = unit.sudo()
            if hasattr(unit_sudo, "manager_id") and unit_sudo.manager_id and unit_sudo.manager_id.address_home_id:
                return unit_sudo.manager_id.address_home_id
        return False

    def _get_plan_stakeholder_partners(self):
        """Return partners who should receive alerts regarding this plan (Submitter, Manager, Creator)."""
        self.ensure_one()
        partners = self.env["res.partner"]
        if self.submitted_by and self.submitted_by.partner_id:
            partners |= self.submitted_by.partner_id
        if self.org_unit_id:
            mgr_partner = self._get_unit_manager_partner(self.org_unit_id)
            if mgr_partner:
                partners |= mgr_partner
        if self.create_uid and self.create_uid.partner_id:
            partners |= self.create_uid.partner_id
        return partners

    def _get_stage_reviewers(self, target_stage=False):
        """Find users responsible for reviewing at the given stage."""
        self.ensure_one()
        stage = target_stage or self.state
        reviewers = self.env["res.users"]

        if stage == "submitted":
            cat = getattr(self, "category", False)
            if cat in ("general_expense", "fixed_asset"):
                ConfigModel = self.env.get("pbms.planning.config")
                ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                if ConfigModel is not None:
                    info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
                    if info.get("users"):
                        reviewers |= info["users"]
                    ou_rec = info.get("operating_unit") or info.get("ou")
                    if ou_rec:
                        reviewers |= ho_reviewers.filtered(lambda u: ou_rec.id in u._pbms_operating_unit_ids())
                    dept_rec = info.get("department") or info.get("dept")
                    if dept_rec:
                        reviewers |= ho_reviewers.filtered(lambda u: u.employee_id and u.employee_id.department_id and u.employee_id.department_id.id == dept_rec.id)
                if not reviewers:
                    if cat == "general_expense":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("finance", "account", "budget", "cost")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("finance", "account", "budget", "cost"))
                            )
                        )
                    elif cat == "fixed_asset":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("property", "procurement", "facility", "admin", "asset")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("property", "procurement", "facility", "admin", "asset"))
                            )
                        )
                if not reviewers:
                    reviewers |= ho_reviewers
                return reviewers

            if self.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (self.org_unit_type != "head_office" and self.org_unit_type != "district_office"):
                # Find District Reviewers for this branch's district
                district = self.district_id or self._find_district_ancestor(self.org_unit_id)
                if district:
                    dist_mgr = self._get_unit_manager_user(district)
                    if dist_mgr:
                        reviewers |= dist_mgr
                # Search all district reviewers assigned to this district
                dist_users = self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer")
                for user in dist_users:
                    if district and district.id in user._pbms_operating_unit_ids():
                        reviewers |= user
                if not reviewers:
                    reviewers |= dist_users
            else:
                cat = getattr(self, "category", False)
                if self.org_unit_type == "head_office" and cat == "manpower":
                    # Head Office department workforce plan is reviewed by Head Office Department Director
                    ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                    if self.org_unit_id:
                        reviewers |= ho_reviewers.filtered(lambda u: self.org_unit_id.id in u._pbms_operating_unit_ids())
                    if not reviewers:
                        dept_mgr = self._get_unit_manager_user(self.org_unit_id)
                        if dept_mgr:
                            reviewers |= dept_mgr
                        else:
                            reviewers |= ho_reviewers
                elif self.org_unit_type == "district_office" and cat == "manpower":
                    # District Office's own workforce plan is reviewed by District Director
                    dist_users = self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer")
                    if self.org_unit_id:
                        reviewers |= dist_users.filtered(lambda u: self.org_unit_id.id in u._pbms_operating_unit_ids())
                    if not reviewers:
                        reviewers |= dist_users
                else:
                    # District Office or Head Office department submits General Expense, Fixed Asset, etc.
                    # Route to assigned Functional Reviewers for this category
                    ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                    ConfigModel = self.env.get("pbms.planning.config")
                    if ConfigModel is not None and cat:
                        info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
                        if info.get("users"):
                            reviewers |= info["users"]
                        if info.get("ou"):
                            reviewers |= ho_reviewers.filtered(lambda u: info["ou"].id in u._pbms_operating_unit_ids())
                        if info.get("dept"):
                            reviewers |= ho_reviewers.filtered(lambda u: u.employee_id and u.employee_id.department_id and u.employee_id.department_id.id == info["dept"].id)
                    if not reviewers:
                        if cat == "general_expense":
                            reviewers |= ho_reviewers.filtered(
                                lambda u: (
                                    (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("finance", "account", "budget", "cost")))
                                    or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("finance", "account", "budget", "cost"))
                                )
                            )
                        elif cat == "fixed_asset":
                            reviewers |= ho_reviewers.filtered(
                                lambda u: (
                                    (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("property", "procurement", "facility", "admin", "asset")))
                                    or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("property", "procurement", "facility", "admin", "asset"))
                                )
                            )
                    if not reviewers:
                        reviewers |= ho_reviewers

        elif stage in ("district_approved", "district_endorsed"):
            ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
            cat = getattr(self, "category", False)
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None and cat:
                info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
                if info.get("users"):
                    reviewers |= info["users"]
                if info.get("ou"):
                    ou_revs = ho_reviewers.filtered(lambda u: info["ou"].id in u._pbms_operating_unit_ids())
                    reviewers |= ou_revs
                if info.get("dept"):
                    reviewers |= ho_reviewers.filtered(lambda u: u.employee_id and u.employee_id.department_id and u.employee_id.department_id.id == info["dept"].id)

            if not reviewers:
                if cat == "manpower":
                    dept_hr_reviewers = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("hr", "human resource", "manpower", "talent")))
                            or any("hr" in (ou.name or "").lower() for ou in u.operating_unit_ids)
                        )
                    )
                    reviewers |= dept_hr_reviewers
                elif cat in ("deposit", "customer_base"):
                    dept_retail = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("retail", "operation", "deposit", "branch")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("retail", "operation", "deposit", "branch"))
                        )
                    )
                    reviewers |= dept_retail
                elif cat == "fx":
                    dept_fx = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("fx", "foreign", "trade", "international", "treasury")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("fx", "foreign", "trade", "international", "treasury"))
                        )
                    )
                    reviewers |= dept_fx
                elif cat == "digital_banking":
                    dept_digital = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("digital", "e-banking", "electronic", "card", "channel")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("digital", "e-banking", "electronic", "card", "channel"))
                        )
                    )
                    reviewers |= dept_digital
                elif cat == "general_expense":
                    dept_fin = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("finance", "account", "budget", "cost")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("finance", "account", "budget", "cost"))
                        )
                    )
                    reviewers |= dept_fin
                elif cat == "fixed_asset":
                    dept_prop = ho_reviewers.filtered(
                        lambda u: (
                            (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("property", "procurement", "facility", "admin", "asset")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("property", "procurement", "facility", "admin", "asset"))
                        )
                    )
                    reviewers |= dept_prop

        elif stage == "ho_reviewed":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_approver")
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_manager")

        elif stage == "committee_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_budget_hiring_committee")
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None:
                cfg = ConfigModel.sudo().search([("config_type", "=", "work_unit_type")], limit=1)
                if cfg and hasattr(cfg, "budget_hiring_committee_user_ids") and cfg.budget_hiring_committee_user_ids:
                    reviewers |= cfg.budget_hiring_committee_user_ids

        elif stage == "hr_fulfillment":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")
            cat = getattr(self, "category", False)
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None and cat:
                info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
                if info.get("users"):
                    reviewers |= info["users"]
                if info.get("ou"):
                    ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                    reviewers |= ho_reviewers.filtered(lambda u: info["ou"].id in u._pbms_operating_unit_ids())
            if not reviewers:
                ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                dept_hr_reviewers = ho_reviewers.filtered(
                    lambda u: (
                        (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("hr", "human resource", "manpower", "talent")))
                        or any("hr" in (ou.name or "").lower() for ou in u.operating_unit_ids)
                    )
                )
                reviewers |= dept_hr_reviewers

        elif stage == "ceo_approval":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_ceo")
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None:
                cfg = ConfigModel.sudo().search([("config_type", "=", "work_unit_type")], limit=1)
                if cfg and hasattr(cfg, "ceo_user_id") and cfg.ceo_user_id:
                    reviewers |= cfg.ceo_user_id

        elif stage == "chief_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_respective_chief")

        elif stage == "people_solutions_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_people_solutions")

        elif stage == "cpco_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")

        elif stage == "board_ceo_approval":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_ceo")
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")

        elif stage == "ho_endorse":
            cat = getattr(self, "category", False)
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None and cat:
                info = ConfigModel.sudo().get_category_review_info(cat, self.org_unit_id)
                if info.get("users"):
                    cfg_ho_users = info["users"].filtered(lambda u: u.has_group("bunna_pbms.group_pbms_ho_reviewer"))
                    if cfg_ho_users:
                        reviewers |= cfg_ho_users
            if not reviewers:
                ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                dept_hr_reviewers = ho_reviewers.filtered(
                    lambda u: (
                        (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("hr", "human resource", "manpower", "talent")))
                        or any("hr" in (ou.name or "").lower() for ou in u.operating_unit_ids)
                    )
                )
                reviewers |= (dept_hr_reviewers or ho_reviewers)

        elif stage == "cpco_endorse":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")

        return reviewers

    def _get_hr_recruitment_partners(self):
        """Return partners responsible for HR Recruitment & Talent Acquisition."""
        partners = self.env["res.partner"]
        for g_xmlid in (
            "bunna_pbms.group_pbms_people_solutions",
            "bunna_pbms.group_pbms_people_operations",
            "hr.group_hr_user",
            "hr.group_hr_manager",
            "bunna_pbms.group_pbms_ho_reviewer",
        ):
            users = self._get_users_with_group(g_xmlid)
            if users:
                partners |= users.mapped("partner_id")
        for rec in self:
            if rec.org_unit_id:
                mgr_partner = rec._get_unit_manager_partner(rec.org_unit_id)
                if mgr_partner:
                    partners |= mgr_partner
            if rec.submitted_by and rec.submitted_by.partner_id:
                partners |= rec.submitted_by.partner_id
        return partners

    def _send_inbox_notification(self, users_or_partners, subject, body):
        """Send direct in-app inbox notification into Discuss [Notifications] tab (chat bubble)."""
        from .pbms_access import send_pbms_inbox_notification
        for rec in self:
            send_pbms_inbox_notification(self.env, rec, users_or_partners, subject, body)

    def _schedule_pbms_activity(self, users, summary, note, date_deadline=False):
        """Send notification to assigned users in ERP Discuss inbox."""
        if not users:
            return
        from .pbms_access import send_pbms_inbox_notification
        for record in self:
            send_pbms_inbox_notification(self.env, record, users, summary, note)

    def _clear_pbms_activities(self, feedback=False):
        """Mark existing pending activities on this record as completed."""
        for record in self:
            if not hasattr(record, "activity_ids"):
                continue
            activities = record.activity_ids
            if activities:
                try:
                    activities.action_feedback(feedback=feedback or _("Action completed."))
                except Exception:
                    activities.unlink()

    def _send_pbms_mail_template(self, template_xmlid, partner_ids=None, email_values=None):
        """Send formatted HTML email template to specified partners directly without duplicating chatter."""
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not partner_ids:
            return

        valid_partner_ids = list({pid for pid in partner_ids if pid})
        if not valid_partner_ids:
            return

        for record in self:
            try:
                subject = (email_values and email_values.get("subject")) or ""
                body_html = (email_values and email_values.get("body_html")) or ""
                if not subject and template:
                    subject = template._render_field("subject", [record.id])[record.id]
                if not body_html and template:
                    body_html = template._render_field("body_html", [record.id])[record.id]

                mail_vals = {
                    "subject": subject or _("PBMS Notification"),
                    "body_html": body_html,
                    "recipient_ids": [(6, 0, valid_partner_ids)],
                    "auto_delete": False,
                }
                self.env["mail.mail"].sudo().create(mail_vals).send()
            except Exception as e:
                _logger.warning("Failed sending mail template %s for %s ID %s: %s", template_xmlid, record._name, record.id, e)

    # -------------------------------------------------------------------------
    # Notification Dispatchers (FR-WP-052 through FR-WP-058)
    # -------------------------------------------------------------------------
    def _notify_submission(self):
        """Notify reviewers and submitter when a planning category or unified plan is submitted."""
        for line in self:
            line._compute_plan_notification_details()
            req_no = getattr(line, "request_number", "") or ""
            unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
            cycle_name = line.cycle_id.name if line.cycle_id else ""
            submitter_name = line.submitted_by.name if line.submitted_by else self.env.user.name
            cat_title = line.plan_category_title or _("Plan & Budget Request")

            # Find next stage reviewers
            reviewers = line._get_stage_reviewers("submitted")
            stakeholders = line._get_plan_stakeholder_partners()
            all_partners = stakeholders | reviewers.mapped("partner_id")

            # 1. Post Bunna Bank branded template card to chatter (Image 1)
            card_html = line._get_plan_submission_email_body()
            subject = _("%s Submitted: %s - %s (%s)") % (cat_title, req_no or "Plan", unit_name, cycle_name)
            line.message_post(
                subject=subject,
                body=Markup(card_html),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

            # 2. Email Delivery via mail.template directly to all_partners
            email_vals = {
                "subject": subject,
                "body_html": card_html,
            }
            line._send_pbms_mail_template("bunna_pbms.mail_template_workforce_plan_submitted", partner_ids=all_partners.ids, email_values=email_vals)

            # 3. Schedule Mail Activity (Pending Approval - FR-WP-053)
            deadline = line.cycle_id.branch_deadline.date() if (line.cycle_id and line.cycle_id.branch_deadline) else fields.Date.today()
            line._schedule_pbms_activity(
                users=reviewers,
                summary=_("Review %s: %s (%s)") % (cat_title, req_no or unit_name, unit_name),
                note=_("%s submitted by %s is pending your review and endorsement.") % (cat_title, submitter_name),
                date_deadline=deadline,
            )

    def _notify_pending_approval(self, target_stage, stage_name):
        """FR-WP-053: Notify next-level approver/reviewer that a plan is pending approval."""
        for line in self:
            line._compute_plan_notification_details()
            line._clear_pbms_activities(feedback=_("Moved to stage: %s") % stage_name)
            reviewers = line._get_stage_reviewers(target_stage)
            target_reviewers = reviewers.filtered(lambda u: u.id != self.env.uid) or reviewers
            target_partners = target_reviewers.mapped("partner_id")

            req_no = getattr(line, "request_number", "") or ""
            unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
            cycle_name = line.cycle_id.name if line.cycle_id else ""
            cat_title = line.plan_category_title or _("Plan & Budget Request")

            # 1. Post Bunna Bank branded template card to chatter (Image 1)
            card_html = line._get_plan_review_email_body(stage_name)
            subject = _("Action Required: %s Pending Review (%s) - %s") % (cat_title, stage_name, unit_name)
            line.message_post(
                subject=subject,
                body=Markup(card_html),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

            # 2. Send single branded email to next stage reviewers
            email_vals = {
                "subject": subject,
                "body_html": card_html,
            }
            line._send_pbms_mail_template("bunna_pbms.mail_template_plan_pending_approval", partner_ids=target_partners.ids, email_values=email_vals)

            # Schedule Activity for new reviewers
            line._schedule_pbms_activity(
                users=target_reviewers,
                summary=_("Action Required: Review %s (%s)") % (cat_title, stage_name),
                note=_("Please review %s for %s at stage '%s'.") % (cat_title, unit_name, stage_name),
            )

    def _get_return_target_info(self, old_state):
        """Determine whether the return destination is the District Reviewer or the original Work Unit Submitter."""
        self.ensure_one()
        if old_state == "cpco_endorse":
            ho_reviewers = self._get_stage_reviewers("ho_endorse")
            return {
                "target_state": "ho_endorse",
                "target_level": "ho_reviewer",
                "assigned_users": ho_reviewers,
                "partner_ids": ho_reviewers.mapped("partner_id"),
                "level_label": _("Head Office Functional Reviewer"),
            }
        elif old_state == "ho_endorse":
            ceo_reviewers = self._get_stage_reviewers("ceo_approval")
            return {
                "target_state": "ceo_approval",
                "target_level": "ceo",
                "assigned_users": ceo_reviewers,
                "partner_ids": ceo_reviewers.mapped("partner_id"),
                "level_label": _("Chief Executive Officer"),
            }
        elif old_state == "ceo_approval":
            comm_reviewers = self._get_stage_reviewers("committee_review")
            return {
                "target_state": "committee_review",
                "target_level": "committee",
                "assigned_users": comm_reviewers,
                "partner_ids": comm_reviewers.mapped("partner_id"),
                "level_label": _("Budget Hiring Committee"),
            }
        elif old_state == "hr_fulfillment":
            comm_reviewers = self._get_stage_reviewers("committee_review")
            return {
                "target_state": "committee_review",
                "target_level": "committee",
                "assigned_users": comm_reviewers,
                "partner_ids": comm_reviewers.mapped("partner_id"),
                "level_label": _("Budget Hiring Committee"),
            }
        elif old_state == "committee_review":
            if getattr(self, "category", False) == "manpower":
                cpco_reviewers = self._get_stage_reviewers("cpco_review")
                return {
                    "target_state": "cpco_review",
                    "target_level": "cpco",
                    "assigned_users": cpco_reviewers,
                    "partner_ids": cpco_reviewers.mapped("partner_id"),
                    "level_label": _("CPCO (Chief of People & Culture Office)"),
                }
            else:
                ho_reviewers = self._get_stage_reviewers("district_approved")
                return {
                    "target_state": "district_approved",
                    "target_level": "ho_reviewer",
                    "assigned_users": ho_reviewers,
                    "partner_ids": ho_reviewers.mapped("partner_id"),
                    "level_label": _("Head Office Reviewer"),
                }
        elif old_state == "cpco_review":
            ps_reviewers = self._get_stage_reviewers("people_solutions_review")
            return {
                "target_state": "people_solutions_review",
                "target_level": "people_solutions",
                "assigned_users": ps_reviewers,
                "partner_ids": ps_reviewers.mapped("partner_id"),
                "level_label": _("People Solutions Directorate"),
            }
        elif old_state == "people_solutions_review":
            if self._is_people_solutions_plan():
                return {
                    "target_state": "draft",
                    "target_level": "planner",
                    "assigned_users": self.create_uid or self.submitted_by or self.env.user,
                    "partner_ids": (self.create_uid or self.submitted_by or self.env.user).mapped("partner_id"),
                    "level_label": _("Work Unit Submitter"),
                }
            chief_reviewers = self._get_stage_reviewers("chief_review")
            return {
                "target_state": "chief_review",
                "target_level": "chief",
                "assigned_users": chief_reviewers,
                "partner_ids": chief_reviewers.mapped("partner_id"),
                "level_label": _("Respective Chief"),
            }

        is_returning_from_ho = old_state in ("district_approved", "district_endorsed", "ho_reviewed", "chief_review", "people_solutions_review", "cpco_review", "board_ceo_approval", "committee_review", "hr_fulfillment", "ceo_approval")
        district = self.district_id or self._find_district_ancestor(self.org_unit_id)
        has_district = bool(district or self.district_reviewer_id or (self.org_unit_id and self.org_unit_id.work_unit_type == "branch"))

        if is_returning_from_ho and has_district:
            # Plan returned from Head Office level back to District
            target_state = "submitted"
            district_users = self.env["res.users"]
            if self.district_reviewer_id:
                district_users |= self.district_reviewer_id
            if district:
                dist_mgr = self._get_unit_manager_user(district)
                if dist_mgr:
                    district_users |= dist_mgr
                for u in self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer"):
                    if district.id in u._pbms_operating_unit_ids():
                        district_users |= u
            if not district_users:
                district_users |= self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer")

            return {
                "target_state": target_state,
                "target_level": "district",
                "assigned_users": district_users,
                "partner_ids": district_users.mapped("partner_id"),
                "level_label": _("District Office (%s)") % (district.display_name if district else _("District")),
            }
        else:
            # Plan returned back to Branch / Work Unit Submitter
            target_state = "returned"
            submitter_users = self.env["res.users"]
            if self.submitted_by:
                submitter_users |= self.submitted_by
            if self.org_unit_id:
                mgr = self._get_unit_manager_user(self.org_unit_id)
                if mgr:
                    submitter_users |= mgr
            if not submitter_users:
                submitter_users |= self.create_uid

            return {
                "target_state": target_state,
                "target_level": "branch",
                "assigned_users": submitter_users,
                "partner_ids": submitter_users.mapped("partner_id"),
                "level_label": _("Work Unit Submitter (%s)") % (self.org_unit_id.display_name if self.org_unit_id else _("Submitter")),
            }

    def _notify_returned(self, reason, is_info_request=False, return_info=None):
        """FR-WP-054: Notify appropriate reviewer/submitter when plan is returned for revision or info is requested."""
        for line in self:
            line._clear_pbms_activities(feedback=_("Returned for revision / info requested."))

            info = return_info or line._get_return_target_info(line.state)
            target_users = info.get("assigned_users", self.env["res.users"])
            target_partners = info.get("partner_ids", self.env["res.partner"])
            level_label = info.get("level_label", _("Submitter"))
            is_district_target = (info.get("target_level") == "district")

            title = _("Information Requested from %s") % level_label if is_info_request else _("Plan Returned to %s for Revision") % level_label
            route_desc = _("Returned from Head Office to District Reviewer") if is_district_target else _("Returned to Branch / Work Unit")

            msg = (
                f"<b>{title}</b><br/>"
                f"<b>Workflow Stage:</b> {route_desc}<br/>"
                f"<b>Reviewer Remarks / Reason:</b> {reason or _('Please review and adjust.')}<br/>"
                f"<b>Work Unit:</b> {line.org_unit_id.display_name if line.org_unit_id else ''}<br/>"
                f"<b>Action:</b> Please review the reviewer feedback and take necessary action."
            )

            line.message_post(body=Markup(msg), message_type="notification", subtype_xmlid="mail.mt_note")
            line._send_pbms_mail_template("bunna_pbms.mail_template_plan_returned", partner_ids=target_partners.ids)

            line._schedule_pbms_activity(
                users=target_users,
                summary=_("Revision Required (%s): %s") % (level_label, line.request_number or line.org_unit_id.display_name),
                note=reason or _("Please review feedback and adjust/resubmit."),
            )

    def _notify_approved(self, stage_label, is_final=False):
        """FR-WP-055: Notify submitter and stakeholders of plan approval."""
        for line in self:
            line._compute_plan_notification_details()
            line._clear_pbms_activities(feedback=_("Approved at stage: %s") % stage_label)
            stakeholders = line._get_plan_stakeholder_partners()
            cat_title = line.plan_category_title or _("Plan & Budget Request")
            req_no = getattr(line, "request_number", "") or "N/A"
            unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
            cycle_name = line.cycle_id.name if line.cycle_id else ""
            approval_label = _("Final Approval Granted (Official ABP)") if is_final else _("Approved (%s)") % stage_label

            # 1. Post Bunna Bank branded template card to chatter (Image 1)
            card_html = line._get_plan_approved_email_body(stage_label, is_final)
            subject = _("%s Approved: %s - %s (%s)") % (cat_title, req_no, unit_name, cycle_name)
            line.message_post(
                subject=subject,
                body=Markup(card_html),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

            # 2. Email Delivery via mail.template directly to stakeholders
            email_vals = {
                "subject": subject,
                "body_html": card_html,
            }
            line._send_pbms_mail_template("bunna_pbms.mail_template_plan_approved", partner_ids=stakeholders.ids, email_values=email_vals)

            if is_final:
                # Update approved workforce establishment in operating.unit.job.position
                line._update_approved_workforce_establishment()
                # Trigger Recruitment Commencement Notification (FR-WP-058)
                line._notify_recruitment_commencement()

    def _notify_rejected(self, reason):
        """FR-WP-056: Notify submitter of plan rejection."""
        for line in self:
            line._clear_pbms_activities(feedback=_("Plan rejected."))
            stakeholders = line._get_plan_stakeholder_partners()
            unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
            rej_reason = reason or _("Rejected by reviewer.")

            msg = (
                f"<b>Plan Rejected</b><br/>"
                f"<b>Reason for Rejection:</b> {rej_reason}<br/>"
                f"<b>Work Unit:</b> {unit_name}"
            )

            line.message_post(body=Markup(msg), message_type="notification", subtype_xmlid="mail.mt_note")
            line._send_pbms_mail_template("bunna_pbms.mail_template_plan_rejected", partner_ids=stakeholders.ids)

    def _notify_recruitment_commencement(self):
        """FR-WP-058: Notify HR Recruitment team and Work Unit Manager following final workforce approval."""
        for line in self:
            mp_lines = getattr(line, "manpower_line_ids", False) or line.line_ids.filtered(lambda l: l.line_type == "manpower")
            if not mp_lines:
                continue

            hr_partners = line._get_hr_recruitment_partners()

            # Build positions table HTML for chatter
            rows_html = ""
            for l in mp_lines:
                pos_title = l.job_id.name if l.job_id else l.new_job_title or _("New Position")
                pos_type = l.position_type_id.name if l.position_type_id else (l.position_type or "N/A")

                # Extract quarterly headcount from months (m01..m12 / hc_m01..hc_m12 / quarter totals / q1..q4)
                q1 = int(
                    (getattr(l, "m01", 0) or 0) + (getattr(l, "m02", 0) or 0) + (getattr(l, "m03", 0) or 0)
                    or (getattr(l, "hc_m01", 0) or 0) + (getattr(l, "hc_m02", 0) or 0) + (getattr(l, "hc_m03", 0) or 0)
                    or getattr(l, "quarter1_total", 0)
                    or getattr(l, "q1", 0)
                    or 0
                )
                q2 = int(
                    (getattr(l, "m04", 0) or 0) + (getattr(l, "m05", 0) or 0) + (getattr(l, "m06", 0) or 0)
                    or (getattr(l, "hc_m04", 0) or 0) + (getattr(l, "hc_m05", 0) or 0) + (getattr(l, "hc_m06", 0) or 0)
                    or getattr(l, "quarter2_total", 0)
                    or getattr(l, "q2", 0)
                    or 0
                )
                q3 = int(
                    (getattr(l, "m07", 0) or 0) + (getattr(l, "m08", 0) or 0) + (getattr(l, "m09", 0) or 0)
                    or (getattr(l, "hc_m07", 0) or 0) + (getattr(l, "hc_m08", 0) or 0) + (getattr(l, "hc_m09", 0) or 0)
                    or getattr(l, "quarter3_total", 0)
                    or getattr(l, "q3", 0)
                    or 0
                )
                q4 = int(
                    (getattr(l, "m10", 0) or 0) + (getattr(l, "m11", 0) or 0) + (getattr(l, "m12", 0) or 0)
                    or (getattr(l, "hc_m10", 0) or 0) + (getattr(l, "hc_m11", 0) or 0) + (getattr(l, "hc_m12", 0) or 0)
                    or getattr(l, "quarter4_total", 0)
                    or getattr(l, "q4", 0)
                    or 0
                )
                total_qty = int(l.quantity or l.annual_total or (q1 + q2 + q3 + q4) or 0)
                appr_target = int(l.approved_annual_total or total_qty)
                prom = int(l.fulfillment_promotion or 0)
                trans = int(l.fulfillment_transfer or 0)
                lat = int(l.fulfillment_lateral or 0)
                ext = int(l.fulfillment_external or 0)

                rows_html += (
                    f"<tr>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd;'><b>{pos_title}</b></td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd;'>{pos_type}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{q1}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{q2}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{q3}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{q4}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center; font-weight:bold; color:#425727;'>{appr_target}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{prom}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{trans}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center;'>{lat}</td>"
                    f"<td style='padding:6px 10px; border:1px solid #ddd; text-align:center; font-weight:bold; color:#85144b;'>{ext}</td>"
                    f"</tr>"
                )

            # Clean up unit name to avoid raw model repr like [hr.report.code(2,)]
            unit_name = line.org_unit_id.name or (line.org_unit_id.display_name if line.org_unit_id else "")
            import re
            unit_clean = re.sub(r"\[hr\.report\.code\(\d+,\)\]\s*", "", unit_name).strip()
            unit_display = unit_clean or unit_name
            cycle_name = line.cycle_id.name if line.cycle_id else ""

            msg = (
                f"<b>Recruitment Commencement Authorized</b><br/>"
                f"Final executive approval granted for Workforce Plan of <b>{unit_display}</b> ({cycle_name}). "
                f"Recruitment and onboarding activities may now commence for the following approved positions and sourcing allocations:<br/><br/>"
                f"<table style='width:100%; border-collapse:collapse; font-size:13px;'>"
                f"<tr style='background-color:#EDF3E8; color:#541718; font-weight:bold; border:1px solid #C8DCB8;'>"
                f"<th style='padding:6px 10px; text-align:left;'>Position / Title</th>"
                f"<th style='padding:6px 10px; text-align:left;'>Request Type</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Q1</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Q2</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Q3</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Q4</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Approved</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Promotion</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Transfer</th>"
                f"<th style='padding:6px 10px; text-align:center;'>Lateral</th>"
                f"<th style='padding:6px 10px; text-align:center;'>External</th>"
                f"</tr>"
                f"{rows_html}"
                f"</table>"
            )

            line.message_post(body=Markup(msg), message_type="notification", subtype_xmlid="mail.mt_note")
            line._send_pbms_mail_template("bunna_pbms.mail_template_recruitment_commencement", partner_ids=hr_partners.ids)

            # People Solutions Directorate is the opener of recruitment for approved plans
            ps_users = self._get_users_with_group("bunna_pbms.group_pbms_people_solutions")
            po_users = self._get_users_with_group("bunna_pbms.group_pbms_people_operations")
            target_users = ps_users | po_users
            if not target_users:
                for g_xmlid in ("hr.group_hr_manager", "hr.group_hr_user", "bunna_pbms.group_pbms_ho_reviewer"):
                    target_users |= self._get_users_with_group(g_xmlid)

            # Exclude current user (CPCO endorser/approver) so they don't notify themselves
            filtered_users = target_users.filtered(lambda u: u.id != self.env.uid and u.active)
            if not filtered_users:
                filtered_users = target_users.filtered(lambda u: u.active)

            if filtered_users:
                line._schedule_pbms_activity(
                    users=filtered_users,
                    summary=_("Commence Recruitment: %s") % unit_display,
                    note=_("Workforce Plan approved. Please initiate candidate sourcing and recruitment per approved schedule."),
                )

    def _update_approved_workforce_establishment(self):
        """Update or create approved_plan_count in operating.unit.job.position when a manpower plan is approved."""
        if "operating.unit.job.position" not in self.env:
            return
        OUJobPos = self.env["operating.unit.job.position"].sudo()
        HrJob = self.env["hr.job"].sudo() if "hr.job" in self.env else False

        for plan in self:
            if not plan.org_unit_id:
                continue
            mp_lines = (getattr(plan, "manpower_line_ids", False) or plan.line_ids.filtered(lambda l: l.line_type == "manpower")).with_context(bypass_plan_lock=True)
            for line in mp_lines:
                qty = line.quantity or 0
                if qty <= 0:
                    continue
                job = line.job_id
                if not job and line.new_job_title and HrJob:
                    job = HrJob.search([("name", "=ilike", line.new_job_title.strip())], limit=1)
                    if not job:
                        job = HrJob.create({"name": line.new_job_title.strip()})
                    line.job_id = job.id

                if job and plan.org_unit_id:
                    # Idempotently compute total approved plan additions for this job and unit
                    approved_domain = [
                        ("line_type", "=", "manpower"),
                        ("job_id", "=", job.id),
                        ("plan_id.org_unit_id", "=", plan.org_unit_id.id),
                        ("plan_id.state", "=", "approved"),
                    ]
                    if hasattr(plan, "cycle_id") and plan.cycle_id:
                        approved_domain.append(("plan_id.cycle_id", "=", plan.cycle_id.id))
                    appr_lines = self.env["pbms.plan.category.line"].sudo().search(approved_domain)
                    total_approved_qty = int(sum(
                        l.approved_annual_total or l.quantity or 0 for l in appr_lines
                    ))
                    if not total_approved_qty:
                        total_approved_qty = int(line.approved_annual_total or line.quantity or 0)

                    ou_pos = OUJobPos.search([
                        ("job_position_id", "=", job.id),
                        ("operating_unit_id", "=", plan.org_unit_id.id),
                    ], limit=1)
                    if ou_pos:
                        ou_pos.approved_plan_count = total_approved_qty
                        ou_pos._compute_total_headcount()
                        ou_pos._compute_vacant_position_count()
                    else:
                        OUJobPos.create({
                            "job_position_id": job.id,
                            "operating_unit_id": plan.org_unit_id.id,
                            "approved_plan_count": total_approved_qty,
                        })
                    _logger.info(
                        "Updated approved establishment for job '%s' at unit '%s' to %s",
                        job.name, plan.org_unit_id.display_name, total_approved_qty,
                    )
            if hasattr(mp_lines, "_compute_workforce_establishment"):
                mp_lines._compute_workforce_establishment()
            if hasattr(mp_lines, "_compute_total_establishment"):
                mp_lines._compute_total_establishment()

    # =========================================================================
    # WORKFLOW ACTIONS
    # =========================================================================
    def action_submit(self):
        self._check_editable()
        if hasattr(self, "_realign_lines_to_matching_cards"):
            self._realign_lines_to_matching_cards()
        elif hasattr(self, "_sync_category_records"):
            self.with_context(bypass_plan_lock=True)._sync_category_records()

        # Collect all planning category records for the same work unit & cycle to submit
        Config = self.env.get("pbms.planning.config")
        candidate_plans = self.env[self._name]
        for rec in self:
            candidate_plans |= rec
            if rec.category and not getattr(rec, "is_planning_request", False):
                # Dedicated category card: submit strictly this category!
                continue
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                siblings = self.env[rec._name].search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                    ("state", "in", ("draft", "returned", "info_requested")),
                ])
                candidate_plans |= siblings

        # A plan can ONLY be submitted if:
        # 1. Its category is active / enabled in Planning Configuration for its operating unit
        # 2. It has actual data (requirement lines or non-zero targets)
        all_plans = self.env[self._name]
        for p in candidate_plans:
            is_enabled = Config.is_category_enabled(p.category, p.org_unit_id) if (Config is not None and p.category and p.org_unit_id) else True
            p_lines = p._get_category_lines(p.category) if hasattr(p, "_get_category_lines") else p.line_ids
            has_data = bool(p.line_ids) or bool(p_lines) or any(getattr(p, m, 0.0) for m in PBMS_MONTH_FIELDS) or ((getattr(p, "annual_total", 0.0) or 0.0) > 0.0)
            if not is_enabled:
                # Clean up / remove any phantom draft plans whose category is disabled in config and have no lines
                if not bool(p.line_ids) and p.state in ("draft", "returned", "info_requested"):
                    try:
                        p.with_context(bypass_plan_lock=True).unlink()
                    except Exception:
                        p.with_context(bypass_plan_lock=True).write({"active": False})
                continue
            if not has_data:
                continue
            all_plans |= p

        if not all_plans:
            raise UserError(_("Cannot submit a plan with no requirement lines or targets. Please add requirement lines for enabled planning categories before submitting."))

        for line in all_plans:
            if not (line._pbms_can_submit_plan() or self.env.su or self.env.is_admin() or self.env.user._pbms_is_sppmd_admin()):
                raise AccessError(_("You can only submit plans for your own work unit before they enter review."))

            # Validate business justification before submission for manpower/workforce lines
            target_cat = getattr(line, "category", False)
            if target_cat == "manpower":
                mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
                if not mp_lines and hasattr(line, "_get_category_lines"):
                    mp_lines = line._get_category_lines("manpower")
                if mp_lines:
                    if hasattr(line, "business_justification") and not line.business_justification and hasattr(line, "justification_category_id") and not line.justification_category_id:
                        has_line_justification = any(l.justification_category_id for l in mp_lines)
                        if not has_line_justification and not line.business_justification:
                            raise ValidationError(_("A Business Justification is required before submitting the Workforce / Manpower Plan."))
                    for l in mp_lines:
                        if not l.justification_category_id:
                            raise ValidationError(_("Please specify a Justification Category for all requested positions."))
                        if l.justification_category_id.requires_remarks and not l.other_justification:
                            raise ValidationError(_("Additional remarks are required for position '%s' because '%s' is selected as justification.") % (
                                l.job_id.name if l.job_id else l.new_job_title or _("New Position"),
                                l.justification_category_id.name
                            ))

        # 1. Snapshot all proposed targets in batch (ultra-fast single SQL query)
        all_lines = all_plans.mapped("line_ids")
        if all_lines and hasattr(all_lines, "_snapshot_proposed_targets"):
            all_lines.with_context(bypass_plan_lock=True)._snapshot_proposed_targets()

        # 2. Batch update state of plans
        old_states = {p.id: p.state for p in all_plans}
        for line in all_plans:
            target_cat = getattr(line, "category", False)
            if target_cat == "manpower" and line._is_people_solutions_plan():
                # For People Solutions Directorate workforce plan: submitted directly to People Solutions Review
                line.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
                    "state": "people_solutions_review",
                    "submitted_by": self.env.uid,
                    "submitted_date": fields.Datetime.now(),
                })
                line._log_audit_action("submit", old_states.get(line.id, "draft"), "people_solutions_review", _("Workforce plan submitted directly to People Solutions Review."))
                line._notify_pending_approval("people_solutions_review", _("People Solutions Directorate Review"))
            elif target_cat == "manpower" and line.org_unit_type == "head_office":
                # For other Head Office workforce plans: no district review needed, submitted directly to Respective Chief
                line.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
                    "state": "chief_review",
                    "submitted_by": self.env.uid,
                    "submitted_date": fields.Datetime.now(),
                })
                line._log_audit_action("submit", old_states.get(line.id, "draft"), "chief_review", _("Workforce plan submitted directly to Respective Chief."))
                line._notify_pending_approval("chief_review", _("Respective Chief Review"))
            elif target_cat in ("general_expense", "fixed_asset") and (
                line.org_unit_type == "head_office"
                or self.env.user.has_group("bunna_pbms.group_pbms_ho_reviewer")
            ):
                # For Head Office general expense and fixed asset plans: no district review, submitted directly to Budget Hiring Committee Review
                line.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
                    "state": "committee_review",
                    "submitted_by": self.env.uid,
                    "submitted_date": fields.Datetime.now(),
                })
                line._log_audit_action("submit", old_states.get(line.id, "draft"), "committee_review", _("%s submitted directly to Budget Hiring Committee Review.") % (line.plan_category_title or _("Plan")))
                line._notify_pending_approval("committee_review", _("Budget Hiring Committee Review"))
            else:
                line.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
                    "state": "submitted",
                    "submitted_by": self.env.uid,
                    "submitted_date": fields.Datetime.now(),
                })
                line._log_audit_action("submit", old_states.get(line.id, "draft"), "submitted", _("%s submitted for review.") % (line.plan_category_title or _("Plan")))

        # 3. Dispatch dynamic submission notification for each active category plan that entered 'submitted'
        for plan in all_plans.filtered(lambda p: p.state == "submitted"):
            has_data = (
                bool(plan.line_ids)
                or bool(plan._get_category_lines(plan.category) if hasattr(plan, "_get_category_lines") else False)
                or any(getattr(plan, m, 0.0) for m in PBMS_MONTH_FIELDS)
                or (getattr(plan, "annual_total", 0.0) > 0.0)
            )
            if has_data:
                plan._notify_submission()







    def _get_workflow_sibling_plans(self):
        """Return all active sibling planning category plans of the exact same category
        for the same operating unit and cycle."""
        all_plans = self.env[self._name]
        for rec in self:
            all_plans |= rec
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                target_cat = getattr(rec, "category", False)
                domain = [
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                    ("state", "=", rec.state),
                ]
                if target_cat:
                    domain.append(("category", "=", target_cat))

                siblings = self.env[rec._name].search(domain)
                all_plans |= siblings
        return all_plans

    def action_district_approve(self):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_district_review_plan():
                raise AccessError(_("Only District Reviewers can approve child work unit plans while they are under district review."))
            if line.state not in ("submitted", "info_requested"):
                continue
            old_state = line.state
            if getattr(line, "category", False) == "manpower":
                next_state = "chief_review"
                next_label = _("Respective Chief Review")
                next_msg = line.district_comment or _("Reviewed by District and escalated to Respective Chief.")
            elif line.org_unit_type == "district_office":
                next_state = "district_endorsed"
                next_label = _("District Endorsed (Forwarded to Head Office)")
                next_msg = line.district_comment or _("Endorsed by District Office.")
            else:
                next_state = "district_approved"
                next_label = _("District Approved (Forwarded to Head Office)")
                next_msg = line.district_comment or _("Approved by District.")

            line.write({
                "state": next_state,
                "district_reviewer_id": self.env.uid,
                "district_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("district_approve", old_state, next_state, next_msg)
            line._notify_pending_approval(next_state, next_label)

            # Consolidate into District Overview Plan ONLY when approving child branch plans in Mobilization Categories
            if line.org_unit_type != "district_office":
                target_cat = getattr(line, "category", False)
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    district = line.district_id or line._find_district_ancestor(line.org_unit_id)
                    if district and hasattr(line, "_consolidate_district_plan_data"):
                        dist_plan = line.sudo()._consolidate_district_plan_data(line.cycle_id, district)
                        if dist_plan:
                            dist_plan.with_context(bypass_plan_lock=True).write({
                                "state": "submitted",
                                "district_reviewer_id": self.env.uid,
                                "district_review_date": fields.Datetime.now(),
                                "submitted_by": self.env.uid,
                                "submitted_date": fields.Datetime.now(),
                            })
                            if hasattr(dist_plan, "_sync_category_records"):
                                dist_plan.with_context(bypass_plan_lock=True)._sync_category_records()

    def action_district_endorse(self):
        return self.action_district_approve()

    def action_ho_approve(self):
        """Final approval action by Head Office Functional Reviewer for Mobilization Categories
        (Deposit, Customer Base, FX, Digital Banking).
        When the HO Reviewer approves:
        1. It marks the district overview plan(s) as approved.
        2. It marks all attached branch plans under those districts as approved.
        3. It creates/updates the Bank-Wide Head Office consolidated record of all districts.
        4. It marks the Bank-Wide Head Office record as finally approved.
        5. Populates approved targets across all levels."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_ho_review_plan():
                raise AccessError(_("Only Head Office Functional Reviewers can approve plans at this stage."))
            target_cat = getattr(line, "category", False)
            if target_cat not in ("deposit", "customer_base", "fx", "digital_banking"):
                raise UserError(_("This approval action is only applicable to Mobilization Categories (Deposit, Customer Base, FX, Digital Banking)."))
            if line.state not in ("draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed", "ho_reviewed"):
                continue

            # Refresh calculated category totals
            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            now = fields.Datetime.now()

            # Mark this plan approved
            line.with_context(bypass_plan_lock=True).write({
                "state": "approved",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": now,
                "approver_id": self.env.uid,
                "approval_date": now,
            })

            # Populate approved target fields ONLY for Head Office bank-wide overview plan.
            # For District and Branch plans, approved targets are ONLY populated when actually cascaded!
            if line.org_unit_type == "head_office":
                for pl in line.line_ids:
                    vals = {
                        "approved_opening_balance": getattr(pl, "opening_balance", 0.0) or 0.0,
                        "approved_annual_total": getattr(pl, "annual_total", 0.0) or 0.0,
                    }
                    for i in range(1, 13):
                        vals[f"approved_m{i:02d}"] = getattr(pl, f"m{i:02d}", 0.0) or 0.0
                    pl.with_context(bypass_plan_lock=True).write(vals)

            line._log_audit_action("ho_approve", old_state, "approved", line.ho_comment or _("Finally approved by Head Office Functional Reviewer."))
            line._notify_approved(_("Annual Mobilization Plan"), is_final=True)

            # If approving a District Overview Plan, also approve all its attached branch plans
            if line.org_unit_type == "district_office":
                self.env[line._name].flush_model(["state", "district_id", "cycle_id", "category", "active", "org_unit_id"])
                branch_plans = self.env[line._name].sudo().search([
                    ("cycle_id", "=", line.cycle_id.id),
                    ("category", "=", target_cat),
                    ("active", "=", True),
                    ("org_unit_type", "!=", "district_office"),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed")),
                    "|",
                    ("district_id", "=", line.org_unit_id.id),
                    ("org_unit_id.parent_unit", "=", line.org_unit_id.id),
                ])
                if branch_plans:
                    for bp in branch_plans:
                        bp.with_context(bypass_plan_lock=True).write({
                            "state": "approved",
                            "ho_reviewer_id": self.env.uid,
                            "ho_review_date": now,
                            "approver_id": self.env.uid,
                            "approval_date": now,
                        })
                        if hasattr(bp, "_compute_category_summaries"):
                            bp._compute_category_summaries()

            # Consolidate all districts into Bank-Wide Head Office record and finally approve it
            ho_unit = False
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None and target_cat:
                info = ConfigModel.sudo().get_category_review_info(target_cat, line.org_unit_id)
                ho_unit = info.get("ou")
            if not ho_unit:
                ho_unit = self.env["operating.unit"].search([("work_unit_type", "=", "head_office")], limit=1)

            if ho_unit and hasattr(line, "_consolidate_ho_plan_data"):
                ho_plan = line.sudo()._consolidate_ho_plan_data(line.cycle_id, ho_unit)
                if ho_plan:
                    ho_old_state = ho_plan.state
                    ho_plan.with_context(bypass_plan_lock=True).write({
                        "state": "approved",
                        "ho_reviewer_id": self.env.uid,
                        "ho_review_date": now,
                        "approver_id": self.env.uid,
                        "approval_date": now,
                        "submitted_by": self.env.uid,
                        "submitted_date": now,
                    })
                    for ho_line in ho_plan.line_ids:
                        if hasattr(ho_line, "_snapshot_proposed_targets"):
                            ho_line._snapshot_proposed_targets()
                        vals = {
                            "approved_opening_balance": getattr(ho_line, "opening_balance", 0.0) or 0.0,
                            "approved_annual_total": getattr(ho_line, "annual_total", 0.0) or 0.0,
                        }
                        for i in range(1, 13):
                            vals[f"approved_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                        ho_line.with_context(bypass_plan_lock=True).write(vals)

                    if hasattr(ho_plan, "_sync_category_records"):
                        ho_plan.with_context(bypass_plan_lock=True)._sync_category_records()
                    if hasattr(ho_plan, "_compute_category_summaries"):
                        ho_plan._compute_category_summaries()

                    ho_plan._log_audit_action("ho_approve", ho_old_state, "approved", _("Bank-Wide Head Office consolidated plan finally approved."))

            # If line was already the Head Office plan, also ensure all district and branch plans are approved
            if line.org_unit_type == "head_office":
                sub_plans = self.env[line._name].search([
                    ("cycle_id", "=", line.cycle_id.id),
                    ("category", "=", target_cat),
                    ("active", "=", True),
                    ("org_unit_type", "!=", "head_office"),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed")),
                ])
                if sub_plans:
                    for sp in sub_plans:
                        sp.with_context(bypass_plan_lock=True).write({
                            "state": "approved",
                            "ho_reviewer_id": self.env.uid,
                            "ho_review_date": now,
                            "approver_id": self.env.uid,
                            "approval_date": now,
                        })
                        if hasattr(sp, "_compute_category_summaries"):
                            sp._compute_category_summaries()

    def action_submit_to_committee(self):
        """Head Office Functional Reviewer reviews General Expense or Fixed Asset
        and submits to the Review Committee."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("general_expense", "fixed_asset"):
                raise UserError(_("This action is only applicable to General Expense and Fixed Asset categories."))
            if not (line._pbms_can_ho_review_plan() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only authorized Head Office Functional Reviewers or Administrators can submit to the Review Committee."))
            if line.org_unit_type not in ("head_office", "district_office") and line.state not in ("district_approved", "district_endorsed", "submitted"):
                raise UserError(_("Branch plans must be approved by the District Reviewer before submitting to the Review Committee."))
            if line.state not in ("district_approved", "district_endorsed", "submitted", "draft", "returned", "info_requested", "ho_reviewed"):
                continue

            # Snapshot proposed targets so requested figures are preserved
            if hasattr(line, "line_ids") and line.line_ids:
                if hasattr(line.line_ids, "_snapshot_proposed_targets"):
                    line.line_ids.with_context(bypass_plan_lock=True)._snapshot_proposed_targets()

            # Refresh calculated category totals
            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "committee_review",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("submit_committee", old_state, "committee_review", line.ho_comment or _("Submitted to Review Committee for target approval."))
            line._notify_pending_approval("committee_review", _("Review Committee Target Review"))

    def action_committee_approve_resource(self):
        """Review Committee grants final approval for General Expense and Fixed Asset plans.
        Directly moves state to 'approved' without HR fulfillment or CEO approval."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("general_expense", "fixed_asset"):
                raise UserError(_("This action is only applicable to General Expense and Fixed Asset categories."))
            if not (self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only members of the Review Committee or Administrators can grant final approval at this stage."))
            if line.state != "committee_review":
                continue

            # For fixed asset lines, approve quantities and costs
            if cat == "fixed_asset":
                for fl in line.fixed_asset_line_ids:
                    qty = fl.quantity or 0
                    unit_price = fl.estimated_unit_price or 0.0
                    cost = qty * unit_price
                    fl.with_context(bypass_plan_lock=True).write({
                        "approved_quantity": qty,
                        "fa_approved_total_cost": cost,
                        "approved_annual_total": cost,
                    })
            elif cat == "general_expense":
                for el in line.expense_line_ids:
                    appr_total = el.approved_annual_total or el.annual_total or 0.0
                    vals = {
                        "approved_annual_total": appr_total,
                        "approved_opening_balance": getattr(el, "approved_opening_balance", 0.0) or getattr(el, "opening_balance", 0.0) or 0.0,
                    }
                    for i in range(1, 13):
                        vals[f"approved_m{i:02d}"] = getattr(el, f"approved_m{i:02d}", 0.0) or getattr(el, f"m{i:02d}", 0.0) or 0.0
                    el.with_context(bypass_plan_lock=True).write(vals)

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            now = fields.Datetime.now()
            line.with_context(bypass_plan_lock=True).write({
                "state": "approved",
                "committee_approver_id": self.env.uid,
                "committee_approval_date": now,
                "approver_id": self.env.uid,
                "approval_date": now,
            })
            line._log_audit_action("committee_approve", old_state, "approved", line.committee_comment or _("Finally approved by Review Committee."))
            line._notify_approved(_("Resource Plan"), is_final=True)

    def action_ho_review(self):
        # Dispatch based on category
        target_cats = set(self.mapped("category"))
        if target_cats and target_cats.issubset({"deposit", "customer_base", "fx", "digital_banking"}):
            return self.action_ho_approve()
        elif any(c in ("general_expense", "fixed_asset") for c in target_cats):
            return self.action_submit_to_committee()

        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_ho_review_plan():
                raise AccessError(_("Only Head Office Functional Reviewers can review child work unit plans at this stage."))
            if line.state not in ("draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed"):
                continue

            # Snapshot proposed targets so the latest edited figures are locked and reflected
            if hasattr(line, "line_ids") and line.line_ids:
                if hasattr(line.line_ids, "_snapshot_proposed_targets"):
                    line.line_ids.with_context(bypass_plan_lock=True)._snapshot_proposed_targets()

            # Refresh calculated category totals
            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "ho_reviewed",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": fields.Datetime.now(),
                "submitted_by": line.submitted_by.id if line.submitted_by else self.env.uid,
                "submitted_date": line.submitted_date or fields.Datetime.now(),
            })
            line._log_audit_action("ho_review", old_state, "ho_reviewed", line.ho_comment or _("Reviewed and submitted to SPPMD Final Approver."))
            line._notify_pending_approval("ho_reviewed", _("Head Office Reviewed (Ready for Final Approval)"))

    # -------------------------------------------------------------------------
    # MANPOWER PLANNING WORKFLOW ACTIONS (ISOLATED TO MANPOWER CATEGORY)
    # -------------------------------------------------------------------------
    def action_hr_submit_to_committee(self):
        """HR Operating Unit reviews requested manpower and submits to Budget Hiring Committee."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (line._pbms_can_ho_review_plan() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only HR Reviewers or Administrators can submit manpower plans to the Budget Hiring Committee."))
            if line.state not in ("district_approved", "district_endorsed", "submitted", "draft", "returned", "info_requested"):
                continue

            # Snapshot proposed targets so requested figures are preserved
            if hasattr(line, "line_ids") and line.line_ids:
                if hasattr(line.line_ids, "_snapshot_proposed_targets"):
                    line.line_ids.with_context(bypass_plan_lock=True)._snapshot_proposed_targets()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "committee_review",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("hr_submit_committee", old_state, "committee_review", line.ho_comment or _("Submitted to Budget Hiring Committee for target approval."))
            line._notify_pending_approval("committee_review", _("Budget Hiring Committee Review"))

    def action_committee_approve(self):
        """Budget Hiring Committee reviews, edits targets & sourcing, and endorses to CEO for final approval."""
        if any(getattr(p, "category", False) in ("general_expense", "fixed_asset") for p in self):
            return self.action_committee_approve_resource()

        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only members of the Budget Hiring Committee or Administrators can endorse workforce plans at this stage."))
            if line.state != "committee_review":
                continue

            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    ml._auto_balance_manpower_sourcing()
                    target = int(ml.annual_total or ml.quantity or 0)
                    tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    pos_name = ml.job_id.name or ml.new_job_title or (ml.position_type_id.name if ml.position_type_id else _("Position"))
                    raise ValidationError(_(
                        "Sourcing Allocation Mismatch for '%s':\n"
                        "• Headcount Target: %d\n"
                        "• Sourced Total: %d (Promotion: %d, Transfer: %d, Lateral: %d, External Vacancy: %d)\n\n"
                        "Please adjust sourcing allocations so the total exactly equals the headcount target (%d)."
                    ) % (pos_name, target, tot_sourced, ml.fulfillment_promotion or 0, ml.fulfillment_transfer or 0, ml.fulfillment_lateral or 0, ml.fulfillment_external or 0, target))

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "ceo_approval",
                "committee_approver_id": self.env.uid,
                "committee_approval_date": fields.Datetime.now(),
            })
            line._log_audit_action("committee_approve", old_state, "ceo_approval", line.committee_comment or _("Approved by Budget Hiring Committee and endorsed to CEO for final approval."))
            line._notify_pending_approval("ceo_approval", _("CEO Final Approval"))

    def action_committee_reject(self, comment=False):
        """Budget Hiring Committee rejects the workforce plan."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_budget_hiring_committee() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only members of the Budget Hiring Committee or Administrators can reject workforce plans at this stage."))
            if line.state != "committee_review":
                continue

            old_state = line.state
            reason = comment or line.committee_comment or _("Rejected by Budget Hiring Committee.")
            line.with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "committee_approver_id": self.env.uid,
                "committee_approval_date": fields.Datetime.now(),
                "return_reason": reason,
            })
            line._log_audit_action("committee_reject", old_state, "rejected", reason)
            line._notify_rejected(reason)

    def action_hr_submit_sourcing(self):
        """Backward compatibility: redirects to CPCO submit to committee."""
        return self.action_cpco_submit_to_committee()

    action_cpco_submit_fulfillment = action_hr_submit_sourcing

    def action_ceo_approve(self):
        """Chief Executive Officer grants final approval and automatically forwards to Head Office Functional Reviewer for endorsement."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_ceo() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only the Chief Executive Officer (CEO) or Administrators can grant executive approval at this stage."))
            if line.state != "ceo_approval":
                continue

            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    ml._auto_balance_manpower_sourcing()
                    target = int(ml.annual_total or ml.quantity or 0)
                    tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    pos_name = ml.job_id.name or ml.new_job_title or (ml.position_type_id.name if ml.position_type_id else _("Position"))
                    raise ValidationError(_(
                        "Sourcing Allocation Mismatch for '%s':\n"
                        "• CEO Approved Headcount: %d\n"
                        "• Sourced Total: %d (Promotion: %d, Transfer: %d, Lateral: %d, External Vacancy: %d)\n\n"
                        "Please adjust sourcing allocations so the total exactly equals the approved headcount (%d)."
                    ) % (pos_name, target, tot_sourced, ml.fulfillment_promotion or 0, ml.fulfillment_transfer or 0, ml.fulfillment_lateral or 0, ml.fulfillment_external or 0, target))

                ml.sudo().with_context(bypass_plan_lock=True).write({
                    "approved_annual_total": target,
                })

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "ho_endorse",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
            })
            line._log_audit_action("ceo_approve", old_state, "ho_endorse", line.ceo_comment or _("Approved by Chief Executive Officer. Automatically forwarded to Head Office Functional Reviewer for endorsement."))
            line._notify_pending_approval("ho_endorse", _("Head Office Functional Reviewer Verification & Endorsement"))

    def action_ho_endorse_to_cpco(self):
        """Head Office Functional Reviewer verifies plan (view-only) and endorses to CPCO."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (line._pbms_can_ho_review_plan() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only Head Office Functional Reviewers or Administrators can endorse workforce plans at this stage."))
            if line.state != "ho_endorse":
                continue

            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    ml._auto_balance_manpower_sourcing()
                    target = int(ml.annual_total or ml.quantity or 0)
                ml.sudo().with_context(bypass_plan_lock=True).write({
                    "approved_annual_total": target,
                })

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            now = fields.Datetime.now()
            line.sudo().with_context(bypass_plan_lock=True).write({
                "state": "cpco_endorse",
                "ho_endorser_id": self.env.uid,
                "ho_endorse_date": now,
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": now,
            })
            line._log_audit_action("ho_endorse_cpco", old_state, "cpco_endorse", line.ho_comment or _("Endorsed by Head Office Functional Reviewer to CPCO."))
            line._notify_pending_approval("cpco_endorse", _("CPCO Final Endorsement"))

    def action_cpco_endorse_to_solutions(self):
        """CPCO verifies and endorses to People Solutions Directorate.
        Final approved state: establishment updated & annual vacancies auto-initiated."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_cpco() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only CPCO (Chief of People & Culture Office) or Administrators can endorse workforce plans at this stage."))
            if line.state != "cpco_endorse":
                continue

            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    ml._auto_balance_manpower_sourcing()
                    target = int(ml.annual_total or ml.quantity or 0)
                ml.sudo().with_context(bypass_plan_lock=True).write({
                    "approved_annual_total": target,
                })

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            now = fields.Datetime.now()
            line_ctx = line.sudo().with_context(bypass_plan_lock=True)
            line_ctx.write({
                "state": "approved",
                "cpco_endorser_id": self.env.uid,
                "cpco_endorse_date": now,
                "approver_id": self.env.uid,
                "approval_date": now,
            })
            line_ctx._log_audit_action("cpco_endorse_solutions", old_state, "approved", line.cpco_comment or _("Endorsed by CPCO to People Solutions Directorate. Plan is fully approved."))
            line_ctx._update_approved_workforce_establishment()
            line_ctx._auto_initiate_annual_workforce_vacancies()
            line_ctx._notify_approved(_("Workforce Plan"), is_final=True)

    def action_ceo_reject(self, comment=False):
        """Chief Executive Officer rejects the workforce plan."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_ceo() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only the Chief Executive Officer (CEO) or Administrators can reject workforce plans at this stage."))
            if line.state != "ceo_approval":
                continue

            old_state = line.state
            reason = comment or line.ceo_comment or _("Rejected by Chief Executive Officer.")
            line.with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
                "return_reason": reason,
            })
            line._log_audit_action("ceo_reject", old_state, "rejected", reason)
            line._notify_rejected(reason)

    # -------------------------------------------------------------------------
    # ANNUAL WORKFORCE PLAN WORKFLOW ACTIONS (ISOLATED TO MANPOWER CATEGORY)
    # -------------------------------------------------------------------------
    def action_district_approve_workforce(self):
        """District Director / Department Director reviews and escalates plan to Respective Chief."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            can_review = (
                line._pbms_can_district_review_plan()
                or (
                    line.org_unit_type == "head_office"
                    and line._pbms_can_ho_review_plan()
                )
                or self.env.user._pbms_is_sppmd_admin()
                or self.env.is_admin()
                or self.env.su
            )
            if not can_review:
                raise AccessError(_("Only District Directors, Department Directors, or Administrators can review and escalate workforce plans at this stage."))
            if line.state not in ("submitted", "draft", "returned", "info_requested"):
                continue

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "chief_review",
                "district_reviewer_id": self.env.uid,
                "district_review_date": fields.Datetime.now(),
            })
            msg = line.district_comment or (_("Reviewed by Department Director and escalated to Respective Chief.") if line.org_unit_type == "head_office" else _("Reviewed by District Director and escalated to Respective Chief."))
            line._log_audit_action("district_approve_workforce", old_state, "chief_review", msg)
            line._notify_pending_approval("chief_review", _("Respective Chief Review"))

    def action_chief_approve_escalate(self):
        """Respective Chief approves & escalates plan (with reduced headcount if modified) to People Solutions Directorate."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_respective_chief() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only Respective Chiefs or Administrators can approve and escalate workforce plans at this stage."))
            if not (self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                is_child = line._is_child_operating_unit_plan() or (line.org_unit_id and line.org_unit_id.id in self.env.user._pbms_child_operating_unit_ids())
                if not is_child:
                    raise AccessError(_("You can only approve and escalate workforce plans for your own child work units."))
            if line.state not in ("chief_review", "district_approved", "district_endorsed"):
                continue

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "people_solutions_review",
                "chief_approver_id": self.env.uid,
                "chief_approval_date": fields.Datetime.now(),
            })
            line._log_audit_action("chief_approve_escalate", old_state, "people_solutions_review", line.chief_comment or _("Approved and escalated by Respective Chief to People Solutions Directorate."))
            line._notify_pending_approval("people_solutions_review", _("People Solutions Directorate Review"))

    def action_chief_reject(self, comment=False):
        """Respective Chief rejects the workforce plan."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_respective_chief() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only Respective Chiefs or Administrators can reject workforce plans at this stage."))
            if not (self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                is_child = line._is_child_operating_unit_plan() or (line.org_unit_id and line.org_unit_id.id in self.env.user._pbms_child_operating_unit_ids())
                if not is_child:
                    raise AccessError(_("You can only reject workforce plans for your own child work units."))
            if line.state not in ("chief_review", "district_approved", "district_endorsed"):
                continue

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "chief_approver_id": self.env.uid,
                "chief_approval_date": fields.Datetime.now(),
                "return_reason": comment or line.chief_comment or _("Rejected by Respective Chief."),
            })
            line._log_audit_action("chief_reject", old_state, "rejected", comment or line.chief_comment or _("Rejected by Respective Chief."))

    def action_people_solutions_escalate_cpco(self):
        """People Solutions Directorate reviews/assesses consolidated plan, establishes sourcing fulfillment, and escalates to CPCO."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_people_solutions() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only People Solutions Directorate officers or Administrators can assess and escalate workforce plans."))
            if line.state != "people_solutions_review":
                continue

            # Ensure sourcing fulfillment is allocated for each position before escalating to CPCO
            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    ml._auto_balance_manpower_sourcing()
                    target = int(ml.annual_total or ml.quantity or 0)
                    tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    pos_name = ml.job_id.name or ml.new_job_title or (ml.position_type_id.name if ml.position_type_id else _("Position"))
                    raise ValidationError(_(
                        "Sourcing Allocation Mismatch for '%s':\n"
                        "• Headcount Target: %d\n"
                        "• Sourced Total: %d (Promotion: %d, Transfer: %d, Lateral: %d, External Vacancy: %d)\n\n"
                        "Please adjust sourcing allocations in People Solutions Directorate so the total equals the requested headcount (%d)."
                    ) % (pos_name, target, tot_sourced, ml.fulfillment_promotion or 0, ml.fulfillment_transfer or 0, ml.fulfillment_lateral or 0, ml.fulfillment_external or 0, target))

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "cpco_review",
                "people_solutions_reviewer_id": self.env.uid,
                "people_solutions_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("people_solutions_escalate", old_state, "cpco_review", line.people_solutions_comment or _("Sourcing & fulfillment allocated by People Solutions Directorate and escalated to CPCO."))
            line._notify_pending_approval("cpco_review", _("CPCO Review (Sourcing Strategy Fulfilled)"))

    def action_cpco_submit_to_committee(self):
        """CPCO reviews/edits Annual Workforce Plan and submits to PBMS Budget Hiring Committee."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_cpco() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only CPCO (Chief of People & Culture Office) or Administrators can submit workforce plans to the Budget Hiring Committee."))
            if line.state != "cpco_review":
                continue

            mp_lines = line.line_ids.filtered(lambda l: l.line_type == "manpower")
            for ml in mp_lines:
                target = int(ml.annual_total or ml.quantity or 0)
                tot_sourced = int((ml.fulfillment_promotion or 0) + (ml.fulfillment_transfer or 0) + (ml.fulfillment_lateral or 0) + (ml.fulfillment_external or 0))
                if target != tot_sourced:
                    pos_name = ml.job_id.name or ml.new_job_title or (ml.position_type_id.name if ml.position_type_id else _("Position"))
                    raise ValidationError(_(
                        "Sourcing Allocation Mismatch for '%s':\n"
                        "• Headcount Target: %d\n"
                        "• Sourced Total: %d (Promotion: %d, Transfer: %d, Lateral: %d, External Vacancy: %d)\n\n"
                        "Please adjust sourcing allocations so the total exactly equals the target headcount (%d)."
                    ) % (pos_name, target, tot_sourced, ml.fulfillment_promotion or 0, ml.fulfillment_transfer or 0, ml.fulfillment_lateral or 0, ml.fulfillment_external or 0, target))

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "committee_review",
                "cpco_reviewer_id": self.env.uid,
                "cpco_submission_date": fields.Datetime.now(),
            })
            line._log_audit_action("cpco_submit_committee", old_state, "committee_review", line.cpco_comment or _("Workforce plan reviewed by CPCO and submitted to Budget Hiring Committee for target approval."))
            line._notify_pending_approval("committee_review", _("Budget Hiring Committee Review"))

    def action_cpco_submit_to_board_ceo(self):
        """Backward-compatibility wrapper: routes to Budget Hiring Committee."""
        return self.action_cpco_submit_to_committee()

    def action_cpco_reject(self, comment=False):
        """CPCO rejects the workforce plan."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_cpco() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only CPCO or Administrators can reject workforce plans at this stage."))
            if line.state not in ("cpco_review", "hr_fulfillment"):
                continue

            old_state = line.state
            reason = comment or line.cpco_comment or _("Rejected by CPCO.")
            line.with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "cpco_reviewer_id": self.env.uid,
                "cpco_submission_date": fields.Datetime.now(),
                "return_reason": reason,
            })
            line._log_audit_action("cpco_reject", old_state, "rejected", reason)
            line._notify_rejected(reason)

    def action_record_board_ceo_approval(self, comment=False):
        """CPCO records CEO / Board approval decision in the system (or CEO directly approves).
        Auto-initiates vacancy requests and routes them for recruitment action.
        """
        if any(p.state == "ceo_approval" for p in self):
            return self.action_ceo_approve()

        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_cpco() or self.env.user._pbms_is_ceo() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only CPCO, CEO, or Administrators can record CEO / Board approval."))
            if line.state != "board_ceo_approval":
                continue

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "approved",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
                "approver_id": self.env.uid,
                "approval_date": fields.Datetime.now(),
            })
            line._log_audit_action("record_board_ceo_approval", old_state, "approved", comment or line.ceo_comment or _("CEO / Board approval recorded by CPCO."))
            line._update_approved_workforce_establishment()
            line._auto_initiate_annual_workforce_vacancies()

    def action_record_board_ceo_rejection(self, comment=False):
        """CPCO records CEO / Board rejection decision in the system (or CEO directly rejects)."""
        if any(p.state == "ceo_approval" for p in self):
            return self.action_ceo_reject(comment=comment)

        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if getattr(line, "category", False) != "manpower" and not line.line_ids.filtered(lambda l: l.line_type == "manpower"):
                raise UserError(_("This action is only applicable to the Manpower Planning Category."))
            if not (self.env.user._pbms_is_cpco() or self.env.user._pbms_is_ceo() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only CPCO, CEO, or Administrators can record CEO / Board rejection."))
            if line.state != "board_ceo_approval":
                continue

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
                "return_reason": comment or line.ceo_comment or _("Rejected by CEO / Board."),
            })
            line._log_audit_action("record_board_ceo_rejection", old_state, "rejected", comment or line.ceo_comment or _("Rejected by CEO / Board."))

    def _auto_initiate_annual_workforce_vacancies(self):
        """Auto-initiates vacancy requests for all approved positions and routes them for recruitment action."""
        for plan in self:
            mp_lines = getattr(plan, "manpower_line_ids", False) or plan.line_ids.filtered(lambda l: l.line_type == "manpower")
            RecruitmentRequest = self.env.get("recruitment.request")
            created_count = 0

            for ml in mp_lines:
                qty = int(ml.approved_annual_total or ml.quantity or 0)
                if qty <= 0 or not ml.job_id:
                    continue

                if RecruitmentRequest is not None:
                    try:
                        req_by = False
                        if plan.submitted_by and plan.submitted_by.employee_id:
                            req_by = plan.submitted_by.employee_id.id
                        elif self.env.user.employee_id:
                            req_by = self.env.user.employee_id.id

                        dept_id = False
                        if hasattr(plan.org_unit_id, "department_id") and plan.org_unit_id.department_id:
                            dept_id = plan.org_unit_id.department_id.id
                        if not dept_id:
                            default_dept = self.env["hr.department"].search([], limit=1)
                            if default_dept:
                                dept_id = default_dept.id

                        sourcing = "external" if getattr(ml, "fulfillment_external", 0) > 0 else "internal"
                        req = RecruitmentRequest.sudo().create({
                            "request_type": "planned",
                            "workforce_plan_id": plan.id,
                            "operating_unit_id": plan.org_unit_id.id,
                            "department_id": dept_id,
                            "job_position_id": ml.job_id.id,
                            "job_grade_id": ml.job_grade_id.id if ml.job_grade_id else (ml.job_id.grade.id if hasattr(ml.job_id, "grade") and ml.job_id.grade else False),
                            "required_headcount": qty,
                            "sourcing_type": sourcing,
                            "justification": _("[Approved Annual Workforce Plan %s] %s") % (getattr(plan, "request_number", plan.display_name), ml.other_justification or ml.reason or _("Annual planned establishment")),
                            "requested_by": req_by,
                            "state": "under_review",
                        })
                        created_count += 1
                    except Exception as e:
                        _logger.warning("Error auto-creating planned recruitment.request: %s", str(e))

                # Route notification/activity to People Operations & Management Directorate
                users = plan._get_users_with_group("bunna_pbms.group_pbms_people_operations")
                if not users:
                    users = plan._get_users_with_group("bunna_pbms.group_pbms_manager")
                summary = _("Annual Plan Vacancy Action: %s (%s)") % (ml.job_id.name, qty)
                note = _(
                    "Annual Workforce Plan %s approved by CEO / Board.<br/>"
                    "• Position: %s<br/>"
                    "• Headcount: %s<br/>"
                    "• Work Unit: %s<br/>"
                    "Please initiate recruitment / vacancy posting per approved annual plan."
                ) % (getattr(plan, "request_number", plan.display_name), ml.job_id.name, qty, plan.org_unit_id.display_name)
                plan._send_inbox_notification(users, summary, note)

            if created_count > 0:
                plan.message_post(
                    body=_("<b>People Operations &amp; Management Directorate:</b> %d planned vacancy requests auto-initiated and routed for recruitment action.") % created_count
                )

    def action_approve(self):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_sppmd_review_plan():
                raise AccessError(_("Only SPPMD Plan Approvers or Administrators can give final approval on Head Office reviewed plans."))
            if line.state != "ho_reviewed":
                continue
            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "approved",
                "approver_id": self.env.uid,
                "approval_date": fields.Datetime.now(),
            })

            # Snapshot and record approved target totals
            if hasattr(line, "line_ids") and line.line_ids:
                ou_type = line.org_unit_id.work_unit_type if line.org_unit_id else False
                is_ho = (ou_type == "head_office")
                for pl_line in line.line_ids:
                    if hasattr(pl_line, "_snapshot_proposed_targets"):
                        pl_line._snapshot_proposed_targets()
                    if is_ho:
                        vals = {
                            "approved_opening_balance": getattr(pl_line, "opening_balance", 0.0) or 0.0,
                            "approved_annual_total": getattr(pl_line, "annual_total", 0.0) or 0.0,
                        }
                        for i in range(1, 13):
                            m_field = f"m{i:02d}"
                            vals[f"approved_{m_field}"] = getattr(pl_line, m_field, 0.0) or 0.0
                        if pl_line.line_type == "fixed_asset":
                            vals["approved_quantity"] = pl_line.quantity or 0
                            vals["fa_approved_total_cost"] = pl_line.fa_annual_total_cost or 0.0
                            vals["approved_annual_total"] = pl_line.fa_annual_total_cost or 0.0
                        pl_line.write(vals)
                    elif pl_line.line_type == "general_expense" or getattr(line, "category", False) == "general_expense":
                        # General expense is not a cascaded mobilization target; populate approved targets on final approval
                        appr_total = getattr(pl_line, "approved_annual_total", 0.0) or getattr(pl_line, "annual_total", 0.0) or 0.0
                        vals = {
                            "approved_opening_balance": getattr(pl_line, "approved_opening_balance", 0.0) or getattr(pl_line, "opening_balance", 0.0) or 0.0,
                            "approved_annual_total": appr_total,
                        }
                        for i in range(1, 13):
                            vals[f"approved_m{i:02d}"] = getattr(pl_line, f"approved_m{i:02d}", 0.0) or getattr(pl_line, f"m{i:02d}", 0.0) or 0.0
                        pl_line.write(vals)
                    elif not pl_line.is_cascaded:
                        # For District and Branch plans, approved targets are ONLY populated when actually cascaded!
                        vals = {
                            "approved_opening_balance": 0.0,
                            "approved_annual_total": 0.0,
                        }
                        for i in range(1, 13):
                            vals[f"approved_m{i:02d}"] = 0.0
                        if pl_line.line_type == "fixed_asset":
                            vals["approved_quantity"] = 0
                            vals["fa_approved_total_cost"] = 0.0
                            vals["approved_annual_total"] = 0.0
                        pl_line.write(vals)
                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()

            line._log_audit_action("approve", old_state, "approved", _("Final approval granted."))
            line._notify_approved(_("Annual Business Plan"), is_final=True)

    def action_reject(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot reject this plan at its current workflow stage."))
            reason = comment or line.return_reason
            if not reason:
                raise UserError(_("Please provide a reason for rejecting the plan."))
            if line.state not in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested", "rejection_recommended", "chief_review", "people_solutions_review", "cpco_review", "board_ceo_approval", "committee_review", "hr_fulfillment", "ceo_approval", "ho_endorse", "cpco_endorse"):
                continue
            old_state = line.state
            vals = {"state": "rejected", "return_reason": reason}
            if line.state in ("chief_review", "district_approved", "district_endorsed"):
                vals.update({"chief_approver_id": self.env.uid, "chief_approval_date": fields.Datetime.now()})
            elif line.state == "committee_review":
                vals.update({"committee_approver_id": self.env.uid, "committee_approval_date": fields.Datetime.now()})
            elif line.state in ("ceo_approval", "board_ceo_approval"):
                vals.update({"ceo_approver_id": self.env.uid, "ceo_approval_date": fields.Datetime.now()})
            elif line.state == "ho_reviewed":
                vals.update({"approver_id": self.env.uid, "approval_date": fields.Datetime.now()})
            line.write(vals)
            line._log_audit_action("reject", old_state, "rejected", reason)
            line._notify_rejected(reason)

    def action_return(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot return this plan at its current workflow stage."))
            reason = comment or line.return_reason
            if not reason:
                raise UserError(_("Please provide a reason before returning a plan."))
            if line.state not in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested", "rejection_recommended", "chief_review", "people_solutions_review", "cpco_review", "board_ceo_approval", "committee_review", "hr_fulfillment", "ceo_approval", "ho_endorse", "cpco_endorse"):
                continue
            
            old_state = line.state
            return_info = line._get_return_target_info(old_state)
            target_state = return_info["target_state"]

            line.write({"state": target_state, "return_reason": reason})
            line._log_audit_action("return", old_state, target_state, reason)
            line._notify_returned(reason, is_info_request=False, return_info=return_info)

    def action_request_info(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot request information on this plan at its current workflow stage."))
            if not comment:
                raise UserError(_("Please enter the specific information or details requested."))
            old_state = line.state
            return_info = line._get_return_target_info(old_state)
            target_state = "info_requested"

            line.write({"state": target_state})
            line._log_audit_action("request_info", old_state, target_state, comment)
            line._notify_returned(comment, is_info_request=True, return_info=return_info)

    def action_recommend_rejection(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot recommend rejection on this plan at its current workflow stage."))
            if not comment:
                raise UserError(_("Please enter the reason / recommendation for rejection."))
            old_state = line.state
            line.write({"state": "rejection_recommended"})
            line._log_audit_action("recommend_rejection", old_state, "rejection_recommended", comment)
            line.message_post(body=Markup(f"<b>Rejection Recommended by Reviewer:</b><br/>{comment or ''}"))


    def action_add_review_comment(self, comment=False):
        for line in self:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot add review comments on this plan at its current workflow stage."))
            if not comment:
                raise UserError(_("Please enter your review comment."))
            line._log_audit_action("review_comment", line.state, line.state, comment)
            line.message_post(body=Markup(f"<b>Reviewer Comment:</b><br/>{comment or ''}"))

    def action_consolidate_district_overview(self):
        """Action for District Reviewers to consolidate all district_approved
        branch plans into the District Office's overview plan for the current cycle."""
        for rec in self:
            district = rec.district_id or rec.org_unit_id
            if district.work_unit_type != "district_office":
                unit_ancestor = self._find_district_ancestor(rec.org_unit_id)
                if unit_ancestor:
                    district = unit_ancestor
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('District Consolidation'),
                            'message': _('District consolidation is only applicable to District Offices or branches attached to a District Office. Unit "%s" is not attached to a District Office.') % rec.org_unit_id.display_name,
                            'type': 'warning',
                            'sticky': False,
                        }
                    }
            
            if hasattr(rec, "_consolidate_district_plan_data"):
                rec._consolidate_district_plan_data(rec.cycle_id, district)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consolidation Complete'),
                'message': _('District overview plan updated from approved branch plans.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_consolidate_bank_overview(self):
        """Action for Head Office Functional Reviewers to consolidate all
        District Overview plans and Branch plans into the Bank-Wide Overview Plan,
        and automatically submit it directly to the SPPMD Final Approver."""
        for rec in self:
            target_cat = getattr(rec, "category", False)
            ho_unit = rec.org_unit_id if rec.org_unit_type == "head_office" else False
            if not ho_unit:
                ConfigModel = self.env.get("pbms.planning.config")
                if ConfigModel is not None and target_cat:
                    info = ConfigModel.sudo().get_category_review_info(target_cat, rec.org_unit_id)
                    ho_unit = info.get("ou")
            if not ho_unit:
                ho_unit = self.env["operating.unit"].search([("work_unit_type", "=", "head_office")], limit=1)
            if not ho_unit:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Bank Consolidation'),
                        'message': _('No Head Office operating unit found to consolidate bank-wide plan into. Please ensure a Head Office unit is configured in Operating Units.'),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

            ho_plan = rec
            if hasattr(rec, "_consolidate_ho_plan_data"):
                ho_plan = rec._consolidate_ho_plan_data(rec.cycle_id, ho_unit)

            if ho_plan:
                old_state = ho_plan.state
                ho_plan.with_context(bypass_plan_lock=True).write({
                    "state": "ho_reviewed",
                    "ho_reviewer_id": self.env.uid,
                    "ho_review_date": fields.Datetime.now(),
                })
                ho_plan._log_audit_action("ho_review", old_state, "ho_reviewed", _("Bank-wide plan consolidated and directly submitted to SPPMD Final Approver."))
                ho_plan._notify_pending_approval("ho_reviewed", _("Head Office Consolidated (Pending Final Approval)"))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bank Consolidation & Submission Complete'),
                'message': _('Bank-wide plan successfully consolidated and submitted directly to the SPPMD Final Approver.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_reset_to_draft(self):
        is_admin = (
            self.env.user.has_group("bunna_pbms.group_pbms_manager")
            or self.env.user.has_group("base.group_system")
            or self.env.is_admin()
            or self.env.su
        )
        for line in self:
            # 1. Once approved, NO ONE (including admin or any privilege) can reset to draft
            if line.state in ("approved", "closed"):
                raise UserError(_(
                    "Locked Official Plan: You cannot reset a plan that has already been approved by the final approver."
                ))

            # 2. Once approved/endorsed by the next-level approver/reviewer (District or Head Office):
            # The submitter/lower privilege cannot reset to draft because the plan is already approved/endorsed.
            if line.state in ("district_approved", "district_endorsed", "ho_reviewed"):
                raise UserError(_(
                    "Plan Approval / Endorsement Locked: You cannot reset this plan to draft because it has already been approved / endorsed by the reviewer (District Office or Head Office). "
                    "Once a higher level approves or endorses a plan, it cannot be reset to draft. If adjustments are required, the reviewer must Return the plan for Revision."
                ))

            if not is_admin:
                if not line._is_own_operating_unit_plan():
                    raise AccessError(_("You can only reset plans for your own work unit."))
                if line.state not in ("submitted", "returned", "info_requested"):
                    raise UserError(_("You can only reset plans that are pending review (Submitted) or returned for revision."))

        all_plans = self
        for rec in self:
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                siblings = self.env[rec._name].search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                    ("state", "!=", "approved"),
                ])
                all_plans |= siblings

        old_states = {p.id: p.state for p in all_plans}
        all_plans.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
            "state": "draft",
            "return_reason": False,
        })

        # Consolidate and preserve all category lines on the primary plan so all tabs keep their details
        for rec in all_plans:
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                primary = self.env[rec._name].search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                ], order="id asc", limit=1)
                if primary:
                    unit_lines = self.env["pbms.plan.category.line"].sudo().search([
                        ("plan_id.org_unit_id", "=", rec.org_unit_id.id),
                        ("plan_id.cycle_id", "=", rec.cycle_id.id),
                    ])
                    detached = unit_lines.filtered(lambda l: l.plan_id.id != primary.id)
                    if detached:
                        detached.with_context(bypass_plan_lock=True).write({"plan_id": primary.id})



        for line in all_plans:
            line._log_audit_action("reset_draft", old_states.get(line.id, "submitted"), "draft", _("Plan reset to draft for further editing."))
            if hasattr(line, "_compute_totals"):
                line._compute_totals()
            if hasattr(line, "_compute_kanban_breakdown_html"):
                line._compute_kanban_breakdown_html()
            if hasattr(line, "_compute_plan_notification_details"):
                line._compute_plan_notification_details()
            if hasattr(line, "category") and line.category == "manpower" and hasattr(line, "_sync_existing_manpower_lines"):
                line._sync_existing_manpower_lines()

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }




    def _notify_stage(self, message):
        for line in self:
            line.message_post(body=_("Plan %s.") % message)

    @api.constrains("cycle_id", "org_unit_id")
    def _check_duplicate(self):
        for line in self:
            domain = line._get_duplicate_domain() + [("id", "!=", line.id)]
            if self.search_count(domain) > 0:
                cat_label = ""
                if hasattr(line, "category") and line.category:
                    cat_label = dict(line._fields["category"].selection).get(line.category, line.category) + " "
                unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
                cycle_name = line.cycle_id.name if line.cycle_id else ""
                raise ValidationError(_(
                    "A %(cat)splan for %(unit)s in budget cycle '%(cycle)s' already exists. "
                    "Please edit or use the existing plan instead of creating a duplicate. "
                    "(If you wish to create a new plan, please archive or delete the existing plan first).",
                    cat=cat_label,
                    unit=unit_name,
                    cycle=cycle_name,
                ))

