# -*- coding: utf-8 -*-
import logging
import os
from markupsafe import Markup
from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_is_zero

_logger = logging.getLogger(__name__)

ALLOWED_PBMS_ATTACHMENT_EXTENSIONS = (".pdf", ".doc", ".docx")

def _validate_pbms_attachment_filename(filename):
    if not filename:
        return
    _base, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_PBMS_ATTACHMENT_EXTENSIONS:
        raise ValidationError(_(
            "Invalid file format for '%(filename)s'. Only PDF (.pdf) and Word documents (.doc, .docx) are allowed as attachments in PBMS.",
            filename=filename,
        ))

class IrAttachmentPbms(models.Model):
    _inherit = "ir.attachment"

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("bypass_attachment_type_check"):
            for vals in vals_list:
                res_model = vals.get("res_model") or self.env.context.get("default_res_model") or ""
                if res_model and res_model.startswith("pbms."):
                    if vals.get("res_field") in ("excel_export", "export_file") or self.env.context.get("in_excel_export"):
                        continue
                    name = vals.get("name") or ""
                    _validate_pbms_attachment_filename(name)
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals and not self.env.context.get("bypass_attachment_type_check"):
            for att in self:
                if att.res_model and att.res_model.startswith("pbms."):
                    if vals.get("res_field") in ("excel_export", "export_file") or self.env.context.get("in_excel_export"):
                        continue
                    _validate_pbms_attachment_filename(vals["name"])
        return super().write(vals)

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

    @api.model
    def browse(self, ids=()):
        if isinstance(ids, (list, tuple)):
            if any(isinstance(item, dict) for item in ids):
                clean_ids = []
                for item in ids:
                    if isinstance(item, dict) and "id" in item:
                        try:
                            clean_ids.append(int(item["id"]))
                        except (ValueError, TypeError):
                            pass
                    else:
                        clean_ids.append(item)
                return super().browse(clean_ids)
        elif isinstance(ids, dict) and "id" in ids:
            try:
                return super().browse(int(ids["id"]))
            except (ValueError, TypeError):
                pass
        return super().browse(ids)

    cycle_id = fields.Many2one(
        "pbms.planning.cycle", string="FY(the Planning year)", required=True, index=True,
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
        "operating.unit", string="Work Unit", required=True, index=True,
        default=_default_org_unit_id,
        help="Branch / District Office / Head Office work unit, from the "
             "Bank's HR org structure (hr_employee_custom).",
    )
    org_unit_type = fields.Selection(related="org_unit_id.work_unit_type", store=True, index=True, string="Org Unit Type")
    is_district_unit = fields.Boolean(
        string="Is District Work Unit",
        compute="_compute_unit_type_flags",
        store=True,
        index=True,
    )
    is_head_office_unit = fields.Boolean(
        string="Is Head Office Work Unit",
        compute="_compute_unit_type_flags",
        store=True,
        index=True,
    )
    is_branch_unit = fields.Boolean(
        string="Is Branch Work Unit",
        compute="_compute_unit_type_flags",
        store=True,
        index=True,
    )
    is_consolidated_ho_plan = fields.Boolean(
        string="Is Bank-Wide Consolidated Plan",
        default=False,
        store=True,
        index=True,
        help="True if this plan is the Bank-Wide Head Office consolidated plan.",
    )
    is_consolidated_district_plan = fields.Boolean(
        string="Is District Consolidated Plan",
        default=False,
        store=True,
        index=True,
        help="True if this plan is the District-level consolidated plan aggregating branch plans.",
    )
    is_consolidated = fields.Boolean(
        string="Is Consolidated Plan",
        compute="_compute_is_consolidated",
        store=True,
        index=True,
        help="True if this plan is a consolidated overview record (district or bank-wide HO), rather than an actual planning request.",
    )

    @api.depends("is_consolidated_district_plan", "is_consolidated_ho_plan")
    def _compute_is_consolidated(self):
        for rec in self:
            rec.is_consolidated = bool(rec.is_consolidated_district_plan or rec.is_consolidated_ho_plan)

    @api.depends("org_unit_id", "org_unit_id.work_unit_type", "org_unit_id.name", "org_unit_type")
    def _compute_unit_type_flags(self):
        for rec in self:
            ou = rec.org_unit_id
            ou_type = rec.org_unit_type or (ou.work_unit_type if ou else False)
            ou_name = (ou.name or "").lower() if ou else ""
            is_ho = ou_type == "head_office" or "head office" in ou_name
            is_dist = (
                not is_ho and (
                    ou_type in ("district", "district_office", "regional_office")
                    or "district" in ou_name
                    or "regional" in ou_name
                )
            )
            rec.is_head_office_unit = is_ho
            rec.is_district_unit = is_dist
            rec.is_branch_unit = not is_ho and not is_dist

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
            ("chief_review", "Respective Chief Review"),
            ("submitted", "Submitted"),
            ("info_requested", "Information Requested"),
            ("returned", "Returned for Revision"),
            ("rejection_recommended", "Rejection Recommended"),
            ("rejected", "Rejected"),
            ("district_approved", "District Approved"),
            ("district_endorsed", "District Endorsed"),
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
    cpco_attachment_ids = fields.Many2many(
        "ir.attachment",
        "pbms_plan_cpco_attachment_rel",
        "plan_id",
        "attachment_id",
        string="CPCO Attachments / Supporting Documents",
        help="Upload supporting justification memos, committee notes, or CPCO review documents.",
    )

    @api.constrains("cpco_attachment_ids")
    def _check_cpco_attachment_extensions(self):
        for rec in self:
            for att in rec.cpco_attachment_ids:
                _validate_pbms_attachment_filename(att.name)
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

    latest_review_comment = fields.Text(
        string="Review Comment",
        compute="_compute_latest_review_comment",
        inverse="_inverse_latest_review_comment",
        compute_sudo=False,
    )

    @api.depends(
        "state",
        "district_comment",
        "chief_comment",
        "people_solutions_comment",
        "cpco_comment",
        "ho_comment",
        "committee_comment",
        "ceo_comment",
        "return_reason",
    )
    def _compute_latest_review_comment(self):
        for rec in self:
            val = False
            if rec.state == "people_solutions_review" and rec.people_solutions_comment:
                val = rec.people_solutions_comment
            elif rec.state in ("cpco_review", "hr_fulfillment", "cpco_endorse") and rec.cpco_comment:
                val = rec.cpco_comment
            elif rec.state == "committee_review" and rec.committee_comment:
                val = rec.committee_comment
            elif rec.state in ("ceo_approval", "board_ceo_approval") and rec.ceo_comment:
                val = rec.ceo_comment
            elif rec.state == "chief_review" and rec.chief_comment:
                val = rec.chief_comment
            elif rec.state == "submitted" and rec.district_comment:
                val = rec.district_comment
            if not val and hasattr(rec, "review_comment_ids") and rec.review_comment_ids:
                latest_audit = rec.review_comment_ids.filtered(lambda c: c.action_type == "review_comment")[:1] or rec.review_comment_ids[:1]
                if latest_audit and latest_audit.comment and latest_audit.comment != _("No remarks provided."):
                    val = latest_audit.comment
            if not val:
                val = (
                    rec.ceo_comment
                    or rec.committee_comment
                    or rec.cpco_comment
                    or rec.people_solutions_comment
                    or rec.ho_comment
                    or rec.chief_comment
                    or rec.district_comment
                    or rec.return_reason
                    or False
                )
            rec.latest_review_comment = val

    def _inverse_latest_review_comment(self):
        for rec in self:
            if not rec._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot add or edit review comments on this plan at its current workflow stage."))
            comment = (rec.latest_review_comment or "").strip()
            stage_vals = {}
            if self.env.user._pbms_is_people_solutions():
                stage_vals["people_solutions_comment"] = comment
            elif rec.state in ("cpco_review", "hr_fulfillment", "cpco_endorse") or self.env.user._pbms_is_cpco():
                stage_vals["cpco_comment"] = comment
            elif rec.state == "committee_review" or self.env.user._pbms_is_budget_hiring_committee():
                stage_vals["committee_comment"] = comment
            elif rec.state in ("ceo_approval", "board_ceo_approval") or self.env.user._pbms_is_ceo():
                stage_vals["ceo_comment"] = comment
            elif rec.state == "chief_review" or self.env.user._pbms_is_respective_chief():
                stage_vals["chief_comment"] = comment
            elif rec.state == "submitted" and rec._pbms_can_district_review_plan():
                stage_vals["district_comment"] = comment
            else:
                stage_vals["ho_comment"] = comment
            rec.with_context(bypass_plan_lock=True, in_review_comment_sync=True).write(stage_vals)
            if comment:
                rec._log_audit_action("review_comment", rec.state, rec.state, comment)
                rec.message_post(body=Markup(f"<b>Reviewer Comment:</b><br/>{comment}"))

    can_use_reviewer_actions = fields.Boolean(
        string="Can Use Reviewer Actions",
        compute="_compute_reviewer_actions_access",
        compute_sudo=False,
    )

    @api.depends("state", "org_unit_type", "category")
    def _compute_reviewer_actions_access(self):
        for rec in self:
            if getattr(rec, "category", False) == "fixed_asset" and rec.state in ("committee_review", "approved", "rejected"):
                rec.can_use_reviewer_actions = False
                continue
            is_branch = rec.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (rec.org_unit_type not in ("head_office", "district_office"))
            is_district_plan = bool(rec.is_district_unit or rec.org_unit_type in ("district_office", "regional_office") or rec._is_district_plan())
            if rec.state in ("draft", "approved", "rejected"):
                rec.can_use_reviewer_actions = False
            elif getattr(rec, "category", False) == "manpower" and rec.state in ("ho_endorse", "cpco_endorse", "approved"):
                rec.can_use_reviewer_actions = False
            elif is_branch and getattr(rec, "category", False) in ("deposit", "customer_base", "fx", "digital_banking") and rec.state in ("district_approved", "district_endorsed"):
                rec.can_use_reviewer_actions = False
            elif is_district_plan:
                # District Office plans:
                # A district reviewer does not review, comment, return or reject their own district office plan.
                # Once submitted or endorsed to Head Office (or chief/committee), reviewer actions are reserved strictly
                # for Head Office functional reviewers, SPPMD admins, or respective chiefs / budget committees at their stages.
                if rec.state in ("submitted", "district_approved", "district_endorsed", "chief_review", "committee_review", "ho_reviewed", "approved", "rejected"):
                    rec.can_use_reviewer_actions = bool(
                        rec._pbms_can_ho_review_plan()
                        or rec._pbms_can_sppmd_review_plan()
                        or (rec.state == "chief_review" and self.env.user._pbms_is_respective_chief())
                        or (rec.state == "committee_review" and self.env.user._pbms_is_budget_hiring_committee())
                    )
                else:
                    rec.can_use_reviewer_actions = rec._pbms_can_use_reviewer_wizards()
            else:
                rec.can_use_reviewer_actions = rec._pbms_can_use_reviewer_wizards()

    can_reset_to_draft = fields.Boolean(
        string="Can Reset to Draft",
        compute="_compute_can_reset_to_draft",
        compute_sudo=False,
    )

    @api.depends("state", "org_unit_id", "submitted_by", "district_reviewer_id", "ho_reviewer_id", "chief_approver_id")
    def _compute_can_reset_to_draft(self):
        user = self.env.user
        is_admin = (
            user.has_group("bunna_pbms.group_pbms_manager")
            or user.has_group("base.group_system")
            or self.env.is_admin()
            or self.env.su
            or (hasattr(user, "_pbms_is_sppmd_admin") and user._pbms_is_sppmd_admin())
        )
        for rec in self:
            if rec.state in ("draft", "closed", "rejected"):
                rec.can_reset_to_draft = False
                continue

            if rec.state == "approved":
                rec.can_reset_to_draft = bool(is_admin)
                continue

            if is_admin:
                rec.can_reset_to_draft = True
                continue

            is_own_unit = bool(
                rec._is_own_operating_unit_plan()
                or (hasattr(rec, "_pbms_can_submit_plan") and rec._pbms_can_submit_plan())
                or (rec.submitted_by and rec.submitted_by.id == user.id)
                or (hasattr(rec, "planner_id") and rec.planner_id and rec.planner_id.id == user.id)
            )
            is_dist_reviewer = hasattr(rec, "_pbms_can_district_review_plan") and rec._pbms_can_district_review_plan()
            is_ho_reviewer = hasattr(rec, "_pbms_can_ho_review_plan") and rec._pbms_can_ho_review_plan()
            is_chief = user.has_group("bunna_pbms.group_pbms_respective_chief")

            can_reset = False
            # 1. Branch plan submitted to District Reviewer:
            # Submitter can reset ONLY while state is 'submitted' (before District Reviewer takes any action)
            if rec.state == "submitted":
                if is_own_unit or is_dist_reviewer or is_ho_reviewer:
                    can_reset = True

            # 2. Plan submitted to Respective Chief for review:
            # Submitter can reset ONLY while state is 'chief_review' (before Chief takes any action)
            elif rec.state == "chief_review":
                has_chief_acted = bool(rec.chief_approver_id or rec.chief_approval_date)
                if not has_chief_acted and (is_own_unit or is_chief or is_ho_reviewer):
                    can_reset = True

            # 3. District plan submitted/endorsed to Head Office:
            # District user can reset ONLY before Head Office Reviewer takes action
            elif rec.state == "district_endorsed" and rec._is_district_plan():
                has_ho_acted = bool(rec.ho_reviewer_id or rec.ho_review_date or rec.approval_date)
                if not has_ho_acted and (is_own_unit or is_dist_reviewer or is_ho_reviewer):
                    can_reset = True

            # 4. District plan in district_approved (not yet reviewed by HO):
            elif rec.state == "district_approved" and rec._is_district_plan():
                has_ho_acted = bool(rec.ho_reviewer_id or rec.ho_review_date or rec.approval_date)
                if not has_ho_acted and (is_own_unit or is_dist_reviewer or is_ho_reviewer):
                    can_reset = True

            # 5. Plan submitted to Committee:
            elif rec.state == "committee_review":
                has_comm_acted = bool(rec.committee_approver_id or rec.committee_approval_date)
                if not has_comm_acted and (is_own_unit or is_chief or is_ho_reviewer):
                    can_reset = True

            # 6. Plan returned for revision:
            elif rec.state == "returned":
                if is_own_unit or is_dist_reviewer or is_ho_reviewer or is_chief:
                    can_reset = True

            rec.can_reset_to_draft = can_reset

    def _pbms_has_valid_planning_data(self):
        """Check if this planning category card has actual valid planning data entered."""
        self.ensure_one()
        cat = getattr(self, "category", False)
        lines = self._get_category_lines(cat) if hasattr(self, "_get_category_lines") and cat else self.line_ids
        if not lines and hasattr(self, "line_ids") and self.line_ids:
            lines = self.line_ids.filtered(lambda l: not cat or l.line_type == cat)
        if lines:
            for l in lines:
                l_type = getattr(l, "line_type", False) or cat
                if l_type in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "loan_disbursement_collection", "loan_outstanding", "credit_portfolio"):
                    has_val = any(not float_is_zero(getattr(l, m, 0.0) or 0.0, precision_digits=2) for m in PBMS_MONTH_FIELDS)
                    if has_val or not float_is_zero(getattr(l, "annual_total", 0.0) or 0.0, precision_digits=2) or not float_is_zero(getattr(l, "opening_balance", 0.0) or 0.0, precision_digits=2):
                        return True
                elif l_type == "manpower":
                    if (getattr(l, "quantity", 0) or 0) > 0 or (getattr(l, "annual_total", 0.0) or 0.0) > 0.0 or (getattr(l, "annual_total_cost", 0.0) or 0.0) > 0.0 or any((getattr(l, m, 0.0) or 0.0) > 0 for m in PBMS_MONTH_FIELDS):
                        return True
                elif l_type == "fixed_asset":
                    if (getattr(l, "quantity", 0) or 0) > 0 or (getattr(l, "fa_annual_total_cost", 0.0) or 0.0) > 0.0 or any((getattr(l, f"fa_q{q}", 0) or 0) > 0 for q in (1, 2, 3, 4)):
                        return True
                elif l_type == "initiative_budget":
                    if (getattr(l, "initiative_cost", 0.0) or 0.0) > 0.0 or (getattr(l, "annual_total", 0.0) or 0.0) > 0.0:
                        return True
                else:
                    if not float_is_zero(getattr(l, "annual_total", 0.0) or 0.0, precision_digits=2):
                        return True

        # Check plan-level monthly targets or annual total
        if any(not float_is_zero(getattr(self, m, 0.0) or 0.0, precision_digits=2) for m in PBMS_MONTH_FIELDS):
            return True
        if not float_is_zero(getattr(self, "annual_total", 0.0) or 0.0, precision_digits=2):
            return True
        return False

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
        """Lightweight static title lookup without database or line queries for maximum performance."""
        category_names = {
            "deposit": _("Deposit Mobilization Plan"),
            "customer_base": _("Customer Base Expansion Plan"),
            "fx": _("Foreign Exchange (FX) Mobilization Plan"),
            "digital_banking": _("Digital Banking Plan"),
            "loan_disbursement_collection": _("Loan Disbursement & Collection Plan"),
            "loan_outstanding": _("Loan & Advances Outstanding Plan"),
            "general_expense": _("General Expense Budget Plan"),
            "manpower": _("Workforce / Manpower Plan"),
            "fixed_asset": _("Fixed Asset Acquisition Plan"),
        }
        for rec in self:
            cat_field = getattr(rec, "category", False)
            rec.plan_category_title = category_names.get(cat_field, cat_field.replace("_", " ").title() if cat_field else "")
            rec.plan_summary_metrics_html = False

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
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">FY(the Planning year):</td>'
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
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">FY(the Planning year):</td>'
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
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">FY(the Planning year):</td>'
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
            dist = self._find_district_ancestor(unit)
            if not dist and unit and getattr(unit, "work_unit_type", False) == "head_office":
                dist = unit
            line.district_id = dist

    @api.model
    def _find_district_ancestor(self, unit):
        seen = self.env["operating.unit"]
        current = unit
        for _i in range(20):
            if not current or current in seen:
                return self.env["operating.unit"]
            if current.work_unit_type in ("district_office", "regional_office", "area_office", "district"):
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

    def _is_district_plan(self):
        """Check if this plan belongs to a District Office / Regional Office."""
        self.ensure_one()
        ou_type = (
            getattr(self, "org_unit_type", False)
            or (self.org_unit_id and getattr(self.org_unit_id, "work_unit_type", False))
            or getattr(self, "work_unit_type", False)
        )
        if ou_type == "head_office":
            return False
        if ou_type in ("district", "district_office", "regional_office"):
            return True
        ou = self.org_unit_id
        if ou:
            ou_name = (ou.name or "").lower()
            if "district" in ou_name or "regional" in ou_name:
                return True
        return False

    def _is_head_office_plan(self):
        """Check if this plan belongs to a Head Office operating unit."""
        self.ensure_one()
        ou_type = (
            getattr(self, "org_unit_type", False)
            or (self.org_unit_id and getattr(self.org_unit_id, "work_unit_type", False))
            or getattr(self, "work_unit_type", False)
        )
        return ou_type == "head_office"

    def _is_ho_functional_reviewer_plan(self, category):
        """Check if this plan is an own-unit plan of the Head Office Functional Reviewer
        for the given category."""
        self.ensure_one()
        submitter = self.submitted_by or self.create_uid
        if self.org_unit_type == "head_office":
            if submitter and submitter.has_group("bunna_pbms.group_pbms_ho_reviewer"):
                if hasattr(submitter, "_pbms_allowed_categories"):
                    if category in submitter._pbms_allowed_categories():
                        return True
                else:
                    return True
            if self.env.user.has_group("bunna_pbms.group_pbms_ho_reviewer"):
                if hasattr(self.env.user, "_pbms_allowed_categories"):
                    if category in self.env.user._pbms_allowed_categories():
                        return True
                else:
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
        visited_units = set()
        while curr and curr.id not in visited_units:
            visited_units.add(curr.id)
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

    def _get_plan_chief_user(self):
        """Memoised wrapper: while a permission compute is running (see
        ``_pbms_chief_memo_scope``) the same plan's chief is resolved only once instead
        of up to ~6 times, each of which walks the employee / unit hierarchy."""
        self.ensure_one()
        cache = getattr(self.env.cr, "cache", None)
        memo = cache.get("_pbms_chief_memo") if cache is not None else None
        if memo is None or not isinstance(self.id, int):
            return self._get_plan_chief_user_uncached()
        sudo_self = self.sudo()
        key = (
            self.id,
            sudo_self.org_unit_id.id,
            sudo_self.district_id.id if getattr(sudo_self, "district_id", False) else False,
            sudo_self.submitted_by.id,
            sudo_self.create_uid.id,
            sudo_self.org_unit_type,
            getattr(sudo_self, "category", False),
        )
        if key not in memo:
            user = self._get_plan_chief_user_uncached()
            memo[key] = user.id if user else False
        uid = memo[key]
        Users = self.env["res.users"].sudo()
        return Users.browse(uid) if uid else Users

    def _pbms_chief_memo_scope(self):
        """Context manager enabling the chief memo for the duration of a batch compute."""
        from contextlib import contextmanager

        @contextmanager
        def _scope():
            cache = getattr(self.env.cr, "cache", None)
            if cache is None or "_pbms_chief_memo" in cache:
                yield
                return
            cache["_pbms_chief_memo"] = {}
            try:
                yield
            finally:
                cache.pop("_pbms_chief_memo", None)
        return _scope()

    def _get_plan_chief_user_uncached(self):
        """Resolve the manager / Respective Chief user for this plan:
        - For Branch Workforce plans: strictly resolves to the District's Respective Chief.
        - For Head Office / District Office plans: follows the reporting hierarchy.
        """
        self.ensure_one()
        self = self.sudo()
        cat = getattr(self, "category", False)
        is_branch = self.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (self.org_unit_type not in ("head_office", "district_office"))

        # For branch workforce plans: resolve strictly the District's Respective Chief!
        if is_branch and cat == "manpower":
            district = self.district_id or self._find_district_ancestor(self.org_unit_id) or (self.org_unit_id and self.org_unit_id.parent_unit)
            reviewer_emp = False
            if self.district_reviewer_id:
                reviewer_emp = self.district_reviewer_id.employee_id or (self.district_reviewer_id.employee_ids and self.district_reviewer_id.employee_ids[0])
                if not reviewer_emp:
                    reviewer_emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.district_reviewer_id.id)], limit=1)

            dist_mgr = (district.sudo().manager_id if district and district.sudo().manager_id else False) or reviewer_emp
            if dist_mgr:
                curr = dist_mgr.parent_id
                visited_dm = {dist_mgr.id}
                while curr and curr.id not in visited_dm:
                    visited_dm.add(curr.id)
                    curr_user = curr.user_id or self.env["res.users"].sudo().search([("employee_id", "=", curr.id)], limit=1)
                    if curr_user and curr_user._pbms_is_respective_chief():
                        return curr_user
                    curr = curr.parent_id

            if district:
                district = district.sudo()
                # 2. Operating unit hierarchy above the District Office
                p_unit = district.parent_unit
                visited_pu = {district.id}
                while p_unit and p_unit.id not in visited_pu:
                    visited_pu.add(p_unit.id)
                    if p_unit.manager_id:
                        p_mgr = p_unit.manager_id.user_id or self.env["res.users"].sudo().search([("employee_id", "=", p_unit.manager_id.id)], limit=1)
                        if p_mgr and p_mgr._pbms_is_respective_chief():
                            return p_mgr
                    p_unit = p_unit.parent_unit

                # 3. Respective Chief directly assigned to this District Office
                chief_users = self._get_users_with_group("bunna_pbms.group_pbms_respective_chief")
                matching_district_chiefs = chief_users.filtered(
                    lambda u: district.id in u._pbms_operating_unit_ids()
                )
                if matching_district_chiefs:
                    return matching_district_chiefs[0]

                # 4. Respective Chief whose child operating units include the District Office
                matching_child_chiefs = chief_users.filtered(
                    lambda u: district.id in u._pbms_child_operating_unit_ids()
                )
                if matching_child_chiefs:
                    return matching_child_chiefs[0]

            # 5. Direct manager of District Director
            if dist_mgr and dist_mgr.parent_id:
                dist_chief_user = dist_mgr.parent_id.user_id or self.env["res.users"].sudo().search([("employee_id", "=", dist_mgr.parent_id.id)], limit=1)
                if dist_chief_user:
                    return dist_chief_user

            # 6. Respective Chief whose child operating units include the Branch
            if self.org_unit_id:
                chief_users = self._get_users_with_group("bunna_pbms.group_pbms_respective_chief")
                matching_branch_chiefs = chief_users.filtered(
                    lambda u: self.org_unit_id.id in u._pbms_child_operating_unit_ids()
                )
                if matching_branch_chiefs:
                    return matching_branch_chiefs[0]

            return False

        submitter = (self.submitted_by or self.create_uid or self.env.user).sudo()
        sub_emp = False
        if submitter:
            sub_emp = submitter.employee_id or (submitter.employee_ids and submitter.employee_ids[0])
            if not sub_emp:
                sub_emp = self.env["hr.employee"].sudo().search([("user_id", "=", submitter.id)], limit=1)
        if sub_emp:
            sub_emp = sub_emp.sudo()

        # 1. Search employee reporting chain upward for a designated Respective Chief
        if sub_emp and sub_emp.parent_id:
            curr = sub_emp.parent_id.sudo()
            visited_sub_emps = {sub_emp.id}
            while curr and curr.id not in visited_sub_emps:
                visited_sub_emps.add(curr.id)
                curr_user = curr.user_id or self.env["res.users"].sudo().search([("employee_id", "=", curr.id)], limit=1)
                if curr_user and curr_user._pbms_is_respective_chief() and not curr_user.has_group("bunna_pbms.group_pbms_manager") and not curr_user._is_admin():
                    return curr_user
                curr = curr.parent_id

        # 2. Operating unit manager's hierarchy
        unit_mgr = self.org_unit_id.sudo().manager_id.sudo() if (self.org_unit_id and self.org_unit_id.sudo().manager_id) else False
        if unit_mgr:
            curr = unit_mgr.parent_id.sudo() if (sub_emp and unit_mgr.id == sub_emp.id and unit_mgr.parent_id) else unit_mgr
            visited_unit_mgrs = {unit_mgr.id}
            while curr and curr.id not in visited_unit_mgrs:
                visited_unit_mgrs.add(curr.id)
                mgr_user = curr.user_id or self.env["res.users"].sudo().search([("employee_id", "=", curr.id)], limit=1)
                if mgr_user and mgr_user._pbms_is_respective_chief() and not mgr_user.has_group("bunna_pbms.group_pbms_manager") and not mgr_user._is_admin():
                    return mgr_user
                curr = curr.parent_id

        # 3. Parent unit's manager
        parent_unit = self.org_unit_id.sudo().parent_unit if self.org_unit_id else False
        visited_pus = {self.org_unit_id.id} if self.org_unit_id else set()
        while parent_unit and parent_unit.id not in visited_pus:
            visited_pus.add(parent_unit.id)
            if parent_unit.manager_id:
                p_mgr_user = parent_unit.manager_id.user_id or self.env["res.users"].sudo().search([("employee_id", "=", parent_unit.manager_id.id)], limit=1)
                if p_mgr_user and p_mgr_user._pbms_is_respective_chief() and not p_mgr_user.has_group("bunna_pbms.group_pbms_manager") and not p_mgr_user._is_admin():
                    return p_mgr_user
            parent_unit = parent_unit.parent_unit

        # 4. Search active dedicated Respective Chief users whose child units include self.org_unit_id
        if self.org_unit_id:
            chief_group = self.env.ref("bunna_pbms.group_pbms_respective_chief", raise_if_not_found=False)
            chief_users = chief_group.user_ids if chief_group else self._get_users_with_group("bunna_pbms.group_pbms_respective_chief")
            functional_chiefs = chief_users.filtered(
                lambda u: u.id != submitter.id and not u.has_group("bunna_pbms.group_pbms_manager") and not u._is_admin() and not u.has_group("base.group_system")
            )
            matching_chiefs = functional_chiefs.filtered(
                lambda u: self.org_unit_id.id in u._pbms_child_operating_unit_ids() or self.org_unit_id.id in u._pbms_operating_unit_ids()
            )
            if matching_chiefs:
                return matching_chiefs[0]
            if chief_users:
                matching_any = chief_users.filtered(
                    lambda u: u.id != submitter.id and self.org_unit_id.id in u._pbms_child_operating_unit_ids()
                )
                if matching_any:
                    return matching_any[0]

        # 5. Plans submitted by a Respective Chief: resolve to CEO
        if submitter and (submitter._pbms_is_respective_chief() or (sub_emp and sub_emp.user_id and sub_emp.user_id._pbms_is_respective_chief())):
            ceo_users = self._get_users_with_group("bunna_pbms.group_pbms_ceo")
            matching_ceo = ceo_users.filtered(lambda u: u.id != submitter.id)
            if matching_ceo:
                return matching_ceo[0]

        return False

    def _is_plan_manager_user(self, user=None):
        """Check if user is the direct manager of the planner for this plan."""
        self.ensure_one()
        user = user or self.env.user
        if not user or not self.org_unit_id:
            return False

        submitter = (self.submitted_by or self.create_uid).sudo()
        if submitter and submitter.id == user.id:
            return False  # Strictly prevent self-approval

        cat = getattr(self, "category", False)
        is_branch = self.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (self.org_unit_type not in ("head_office", "district_office"))
        chief_user = self._get_plan_chief_user()
        if is_branch and cat == "manpower":
            if chief_user and chief_user.id == user.id:
                return True
            if chief_user:
                chief_emp = chief_user.employee_id or (chief_user.employee_ids and chief_user.employee_ids[0])
                curr_mgr = chief_emp.parent_id if chief_emp else None
                visited_cm = {chief_emp.id} if chief_emp else set()
                while curr_mgr and curr_mgr.id not in visited_cm:
                    visited_cm.add(curr_mgr.id)
                    if curr_mgr.user_id and curr_mgr.user_id.id == user.id:
                        return True
                    curr_mgr = curr_mgr.parent_id
            return False

        if chief_user and chief_user.id == user.id:
            return True

        if user._pbms_is_ceo() and submitter and submitter.id != user.id:
            if submitter._pbms_is_respective_chief():
                return True

        user_emp = user.sudo().employee_id or (user.sudo().employee_ids and user.sudo().employee_ids[0])
        if not user_emp:
            user_emp = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        if user_emp:
            user_emp = user_emp.sudo()

        if user_emp:
            # 1. Check submitter's direct manager
            if submitter:
                sub_emp = submitter.employee_id or (submitter.employee_ids and submitter.employee_ids[0])
                if not sub_emp:
                    sub_emp = self.env["hr.employee"].sudo().search([("user_id", "=", submitter.id)], limit=1)
                if sub_emp:
                    sub_emp = sub_emp.sudo()
                    if sub_emp.id == user_emp.id:
                        return False
                    if sub_emp.parent_id and sub_emp.parent_id.id == user_emp.id:
                        return True

            # 2. Check operating unit manager's hierarchy
            unit_mgr = self.org_unit_id.sudo().manager_id.sudo() if (self.org_unit_id and self.org_unit_id.sudo().manager_id) else False
            if unit_mgr:
                if sub_emp and sub_emp.id == unit_mgr.id:
                    # Planner is the unit manager; only their supervisor (unit_mgr.parent_id) can approve
                    if unit_mgr.parent_id and unit_mgr.parent_id.id == user_emp.id:
                        return True
                else:
                    # Planner is a staff member; only the unit manager can approve, not the manager's manager
                    if unit_mgr.id == user_emp.id:
                        return True

        return False

    def _is_plan_self_submitted(self, user=None):
        """Check if user submitted or created this plan."""
        self.ensure_one()
        user = user or self.env.user
        if not user:
            return False
        return bool(
            (self.submitted_by and self.submitted_by.id == user.id)
            or (self.create_uid and self.create_uid.id == user.id)
        )

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
                if state in ("submitted", "district_approved", "district_endorsed", "info_requested"):
                    return True
                if self._is_own_operating_unit_plan() and state in PBMS_BRANCH_EDITABLE_STATES:
                    return True

        # Respective Chief / Manager during chief_review stage on Manpower, General Expense, and Fixed Asset plans
        is_applicable_chief_unit = (
            self._is_head_office_plan()
            or self._is_district_plan()
            or self.org_unit_type in ("head_office", "district_office")
            or (state == "chief_review")
        )
        if is_applicable_chief_unit and getattr(self, "category", False) in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking") and state == "chief_review":
            if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True
            chief_user = self._get_plan_chief_user()
            is_designated_chief = (chief_user and chief_user.id == user.id) or not chief_user or user._pbms_is_ceo()
            if (user._pbms_is_respective_chief() or user._pbms_is_ceo() or self._is_plan_manager_user(user)) and is_designated_chief and not self._is_plan_self_submitted(user):
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
        if user._pbms_is_budget_hiring_committee() and state == "committee_review" and getattr(self, "category", False) in ("manpower", "fixed_asset", "initiative_budget", "general_expense"):
            return True

        # HR Reviewer / CPCO / People Solutions during HR fulfillment stage
        if (user._pbms_is_people_solutions() or user._pbms_is_cpco() or user._pbms_is_ho_reviewer() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su) and state == "hr_fulfillment" and getattr(self, "category", False) == "manpower":
            return True

        # CEO during ceo_approval / board_ceo_approval stage
        if state in ("ceo_approval", "board_ceo_approval"):
            if user._pbms_is_ceo() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True

        # District Reviewer on child operating unit plans (only pending review) or own operating unit (only draft)
        if user._pbms_is_district_reviewer():
            if (self.org_unit_type != "head_office" or self._is_child_operating_unit_plan()) and state in PBMS_DISTRICT_REVIEW_STATES:
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
        allowed_states = PBMS_DISTRICT_REVIEW_STATES
        if self.state not in allowed_states:
            return False
        if self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return True
        if self.submitted_by and self.submitted_by.id == self.env.uid and not (self.is_district_unit or self._is_district_plan() or self.org_unit_type in ("district_office", "regional_office", "district")):
            return False
        if not self.env.user._pbms_is_district_reviewer():
            return False
        user_ous = self.env.user._pbms_operating_unit_ids()
        is_own = self.org_unit_id.id in user_ous
        is_child_branch = bool(
            (self.district_id and self.district_id.id in user_ous)
            or (self.org_unit_id and self.org_unit_id.parent_unit and self.org_unit_id.parent_unit.id in user_ous)
            or (self.org_unit_id and self.org_unit_id.id in self.env.user._pbms_child_operating_unit_ids())
        )
        if not (is_own or is_child_branch):
            return False
        return True

    def _pbms_can_ho_review_plan(self):
        self.ensure_one()
        user = self.env.user
        if user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return self.state in (PBMS_HO_REVIEW_STATES | {"hr_fulfillment", "ho_endorse", "ho_reviewed"})
        if self.submitted_by and self.submitted_by.id == self.env.uid and not (self.chief_approver_id or self.district_reviewer_id):
            return False

        cat = getattr(self, "category", False)
        if not user._pbms_is_ho_reviewer():
            return False
        if cat == "fixed_asset" and self.state == "committee_review":
            return False

        # HO functional reviewers review mobilization categories only at District Overview (or direct HO) level
        is_branch = self.org_unit_type in ("branch", "sub_branch", "service_center", "other")
        is_own_unit = self.org_unit_id.id in user._pbms_operating_unit_ids()
        if is_branch and not is_own_unit:
            # Branch mobilization categories roll up to District Overview and do NOT reach HO directly.
            # Only unit-level general expense, fixed asset, credit portfolio, initiative budget, and loan requests reach HO Functional Reviewer directly.
            if cat in ("general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding") and self.state in (
                "submitted", "district_approved", "district_endorsed", "committee_review",
                "board_ceo_approval", "ho_reviewed", "approved",
            ):
                pass  # allowed — fall through to state check below
            elif cat == "manpower" and self.state in ("ho_endorse", "cpco_endorse", "approved"):
                return True
            else:
                return False

        if cat == "manpower":
            if self.state in ("ho_endorse", "cpco_endorse", "approved"):
                return True
            if self.org_unit_type == "head_office" and self.state in PBMS_DISTRICT_REVIEW_STATES:
                return self._is_own_operating_unit_plan() or self._is_child_operating_unit_plan() or user._pbms_is_sppmd_admin()
            return False

        ho_cats = user._pbms_ho_review_categories() if hasattr(user, "_pbms_ho_review_categories") else user._pbms_allowed_categories()
        if cat and cat not in ho_cats:
            return False

        # District overview plans for mobilization categories are reviewable by HO Functional Reviewer strictly after District endorses them
        if self.org_unit_type in ("district_office", "regional_office") or self.is_district_unit:
            if cat in ("deposit", "customer_base", "fx", "digital_banking"):
                return self.state in ("district_endorsed", "ho_reviewed", "approved")

        # Head office units are reviewable directly
        if self.org_unit_type == "head_office" or self.is_head_office_unit:
            return self.state in (PBMS_HO_REVIEW_STATES | {"hr_fulfillment", "ho_endorse", "ho_reviewed"})

        # Branch plans for direct-pass categories
        if self.org_unit_type not in ("head_office", "district_office") and cat in ("general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding"):
            if self.state not in ("submitted", "district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed", "approved"):
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
        if getattr(self, "category", False) == "manpower" and self.state in ("ho_endorse", "cpco_endorse", "approved"):
            return False
        if self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
            return True
        cat = getattr(self, "category", False)
        if cat == "manpower" and self.state == "people_solutions_review" and self.env.user._pbms_is_people_solutions():
            return True
        if cat == "manpower" and self.state in ("cpco_review", "hr_fulfillment") and self.env.user._pbms_is_cpco():
            return True
        if cat in ("fixed_asset", "manpower", "initiative_budget") and self.state == "committee_review" and self.env.user._pbms_is_budget_hiring_committee():
            return True
        if cat == "manpower" and self.state in ("ceo_approval", "board_ceo_approval") and (self.env.user._pbms_is_ceo() or self.env.user._pbms_is_cpco()):
            return True
        if self.submitted_by and self.submitted_by.id == self.env.uid and not (self.chief_approver_id or self.district_reviewer_id):
            return False
        return (
            self._pbms_can_district_review_plan()
            or self._pbms_can_ho_review_plan()
            or self._pbms_can_sppmd_review_plan()
            or (
                (self._is_head_office_plan() or self._is_district_plan() or self.org_unit_type in ("head_office", "district_office") or self.state == "chief_review")
                and cat in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking")
                and self.state in ("chief_review", "district_approved", "district_endorsed")
                and (
                    (self.env.user._pbms_is_respective_chief() and ((self._get_plan_chief_user() and self._get_plan_chief_user().id == self.env.uid) or not self._get_plan_chief_user()))
                    or self.env.user._pbms_is_ceo()
                    or self._is_plan_manager_user(self.env.user)
                )
            )
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

                # 0. FY(the Planning year) not open for unit input
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
        if not is_admin_or_bypass and "people_solutions_comment" in vals:
            if not self.env.user._pbms_is_people_solutions():
                raise AccessError(_("Only People Solutions Directorate can edit People Solutions Review Remarks."))
        if not is_admin_or_bypass and protected and any(f in vals for f in protected):
            for line in self:
                if line.state in ("district_approved", "district_endorsed", "ho_reviewed", "approved"):
                    if not line._pbms_can_edit_plan_content():
                        raise UserError(_(
                            "This plan has already moved past your review stage. "
                            "You can view it but cannot change plan values."
                        ))
        res = super().write(vals)
        if not self.env.context.get("in_review_comment_sync") and "state" not in vals:
            for cfield in ("people_solutions_comment", "cpco_comment", "committee_comment", "ceo_comment", "chief_comment", "district_comment", "ho_comment"):
                if cfield in vals and vals[cfield]:
                    comment_str = str(vals[cfield]).strip()
                    if comment_str:
                        for rec in self:
                            rec._log_audit_action("review_comment", rec.state, rec.state, comment_str)
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
    @api.model
    @tools.ormcache("group_xmlid")
    def _get_users_with_group_ids(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return ()
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
        return tuple(users.ids)

    def _get_users_with_group(self, group_xmlid):
        """Find active users belonging to a group by xmlid in Odoo 19 (cached)."""
        user_ids = self._get_users_with_group_ids(group_xmlid)
        return self.env["res.users"].browse(user_ids)

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
        """Return partners who should receive alerts regarding this plan (Submitter, Manager, Creator),
        strictly restricted to users who possess active PBMS access rights.
        """
        self.ensure_one()
        partners = self.env["res.partner"]
        if self.submitted_by and self.submitted_by.partner_id and self.submitted_by._pbms_has_access():
            partners |= self.submitted_by.partner_id
        if self.org_unit_id:
            mgr_user = self._get_unit_manager_user(self.org_unit_id)
            if mgr_user and mgr_user.partner_id and mgr_user._pbms_has_access():
                partners |= mgr_user.partner_id
        if self.create_uid and self.create_uid.partner_id and self.create_uid._pbms_has_access():
            partners |= self.create_uid.partner_id
        return partners

    def _get_stage_reviewers(self, target_stage=False):
        """Find users responsible for reviewing at the given stage."""
        self.ensure_one()
        self = self.sudo()
        stage = target_stage or self.state
        reviewers = self.env["res.users"]

        if stage == "submitted":
            if (self.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (self.org_unit_type != "head_office" and self.org_unit_type != "district_office")) and not self.chief_approver_id:
                # Find District Reviewers for this branch's district (strictly district, not Head Office)
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
                if self.org_unit_type == "head_office" and cat == "manpower" and not self.chief_approver_id:
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
                elif self.org_unit_type == "district_office" and cat == "manpower" and not self.chief_approver_id:
                    # District Office's own workforce plan is reviewed by District Director
                    dist_users = self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer")
                    if self.org_unit_id:
                        reviewers |= dist_users.filtered(lambda u: self.org_unit_id.id in u._pbms_operating_unit_ids())
                    if not reviewers:
                        reviewers |= dist_users
                else:
                    # District Office, Head Office department, or Respective Chief endorsed plan
                    # Route to assigned Functional Reviewers for this category
                    ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
                    if cat == "general_expense":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                "general_expense" in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("finance", "account", "budget", "cost")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("finance", "account", "budget", "cost"))
                            )
                        )
                    elif cat == "fixed_asset":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                "fixed_asset" in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("property", "procurement", "facility", "admin", "asset")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("property", "procurement", "facility", "admin", "asset"))
                            )
                        )
                    elif cat in ("credit_portfolio", "loan_disbursement_collection", "loan_outstanding"):
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                cat in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("credit", "loan", "advance", "financing", "relationship", "portfolio")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("credit", "loan", "advance", "financing", "relationship", "portfolio"))
                            )
                        )
                    elif cat == "initiative_budget":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                "initiative_budget" in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("initiative", "strategy", "project", "pmo", "planning")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("initiative", "strategy", "project", "pmo", "planning"))
                            )
                        )
                    elif cat in ("deposit", "customer_base"):
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                cat in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("retail", "deposit", "branch")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("retail", "deposit", "branch"))
                            )
                        )
                    elif cat == "fx":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                "fx" in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("fx", "foreign", "trade", "international", "treasury")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("fx", "foreign", "trade", "international", "treasury"))
                            )
                        )
                    elif cat == "digital_banking":
                        reviewers |= ho_reviewers.filtered(
                            lambda u: (
                                "digital_banking" in u._pbms_ho_review_categories()
                                or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("digital", "e-banking", "electronic", "card", "channel")))
                                or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("digital", "e-banking", "electronic", "card", "channel"))
                            )
                        )
                    if not reviewers:
                        reviewers |= ho_reviewers.filtered(lambda u: cat in u._pbms_ho_review_categories()) or ho_reviewers

        elif stage in ("district_approved", "district_endorsed"):
            ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
            cat = getattr(self, "category", False)

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
                elif cat in ("credit_portfolio", "loan_disbursement_collection", "loan_outstanding"):
                    dept_credit = ho_reviewers.filtered(
                        lambda u: (
                            cat in u._pbms_ho_review_categories()
                            or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("credit", "loan", "advance", "financing", "relationship", "portfolio")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("credit", "loan", "advance", "financing", "relationship", "portfolio"))
                        )
                    )
                    reviewers |= dept_credit
                elif cat == "initiative_budget":
                    dept_init = ho_reviewers.filtered(
                        lambda u: (
                            "initiative_budget" in u._pbms_ho_review_categories()
                            or (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("initiative", "strategy", "project", "pmo", "planning")))
                            or any(w in (ou.name or "").lower() for ou in u.operating_unit_ids for w in ("initiative", "strategy", "project", "pmo", "planning"))
                        )
                    )
                    reviewers |= dept_init
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
                if not reviewers:
                    reviewers |= ho_reviewers.filtered(lambda u: cat in u._pbms_ho_review_categories()) or ho_reviewers

        elif stage == "ho_reviewed":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_approver")
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_manager")

        elif stage == "committee_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_budget_hiring_committee")

        elif stage == "hr_fulfillment":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")
            ho_reviewers = self._get_users_with_group("bunna_pbms.group_pbms_ho_reviewer")
            dept_hr_reviewers = ho_reviewers.filtered(
                lambda u: (
                    (u.employee_id and u.employee_id.department_id and any(w in (u.employee_id.department_id.name or "").lower() for w in ("hr", "human resource", "manpower", "talent")))
                    or any("hr" in (ou.name or "").lower() for ou in u.operating_unit_ids)
                )
            )
            reviewers |= dept_hr_reviewers or ho_reviewers

        elif stage == "ceo_approval":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_ceo")

        elif stage == "chief_review":
            chief_user = self._get_plan_chief_user()
            if chief_user:
                reviewers |= chief_user
                is_branch = self.org_unit_type in ("branch", "sub_branch", "service_center", "other") or (self.org_unit_type not in ("head_office", "district_office"))
                if is_branch and getattr(self, "category", False) == "manpower" and self.district_reviewer_id:
                    chief_emp = chief_user.employee_id or (chief_user.employee_ids and chief_user.employee_ids[0])
                    if chief_emp and chief_emp.parent_id:
                        mgr_user = chief_emp.parent_id.user_id or self.env["res.users"].sudo().search([("employee_id", "=", chief_emp.parent_id.id)], limit=1)
                        if mgr_user:
                            reviewers |= mgr_user
                else:
                    submitter = (self.submitted_by or self.create_uid).sudo() if (self.submitted_by or self.create_uid) else False
                    sub_emp = submitter.employee_id or (submitter.employee_ids and submitter.employee_ids[0]) if submitter else False
                    if sub_emp and sub_emp.parent_id:
                        mgr_user = sub_emp.parent_id.user_id or self.env["res.users"].sudo().search([("employee_id", "=", sub_emp.parent_id.id)], limit=1)
                        if mgr_user and mgr_user != submitter:
                            reviewers |= mgr_user
            else:
                reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_respective_chief")

        elif stage == "people_solutions_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_people_solutions")

        elif stage == "cpco_review":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")

        elif stage == "board_ceo_approval":
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_ceo")
            reviewers |= self._get_users_with_group("bunna_pbms.group_pbms_cpco")

        elif stage == "ho_endorse":
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

        # Also include any users directly assigned dynamic privileges for this workflow stage
        PrivAssign = self.env.get("pbms.privilege.assignment")
        if PrivAssign is not None:
            stage_action_map = {
                "submitted": ("district_review", "district_approve", "district_endorse"),
                "district_approved": ("ho_review", "ho_approve", "ho_endorse"),
                "district_endorsed": ("ho_review", "ho_approve", "ho_endorse"),
                "ho_reviewed": ("final_approve",),
                "chief_review": ("chief_review", "chief_approve"),
                "committee_review": ("committee_review", "committee_approve"),
                "ceo_approval": ("ceo_approval", "ceo_approve"),
                "people_solutions_review": ("people_solutions_review", "ps_approve"),
                "cpco_review": ("cpco_review", "cpco_approve"),
                "board_ceo_approval": ("ceo_approval", "ceo_approve"),
            }
            target_actions = stage_action_map.get(stage)
            if target_actions:
                dyn_assigns = PrivAssign.sudo().search([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                    ("privilege_id.action_type", "in", target_actions),
                    ("user_id", "!=", False),
                ])
                for a in dyn_assigns:
                    if a.user_id:
                        reviewers |= a.user_id

        return reviewers.filtered(lambda u: u.active and u._pbms_has_access())

    def _get_hr_recruitment_partners(self):
        """Return partners responsible for HR Recruitment & Talent Acquisition."""
        partners = self.env["res.partner"]
        for g_xmlid in (
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
        """Send notification to assigned users in ERP Discuss inbox and schedule activity in batch."""
        if not users:
            return
        # Strict security constraint: PBMS activities must ONLY be scheduled for users who have PBMS access rights
        users = users.filtered(lambda u: u.active and u._pbms_has_access())
        if not users:
            return
        from .pbms_access import send_pbms_inbox_notification
        act_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        act_type_id = act_type.id if act_type else False
        deadline = date_deadline or fields.Date.today()
        MailActivity = self.env["mail.activity"].sudo()

        for record in self:
            send_pbms_inbox_notification(self.env, record, users, summary, note)
            if act_type_id and hasattr(record, "activity_ids"):
                existing_user_ids = {a.user_id.id for a in record.activity_ids if a.activity_type_id.id == act_type_id}
                new_users = [u for u in users if u.id not in existing_user_ids]
                if new_users:
                    try:
                        vals_list = [{
                            "res_model": record._name,
                            "res_model_id": self.env["ir.model"]._get_id(record._name),
                            "res_id": record.id,
                            "activity_type_id": act_type_id,
                            "summary": summary,
                            "note": note,
                            "user_id": u.id,
                            "date_deadline": deadline,
                        } for u in new_users]
                        MailActivity.with_context(mail_activity_quick_update=True).create(vals_list)
                    except Exception:
                        for u in new_users:
                            try:
                                record.sudo().with_context(mail_activity_quick_update=True).activity_schedule(
                                    activity_type_id=act_type_id,
                                    summary=summary,
                                    note=note,
                                    user_id=u.id,
                                    date_deadline=deadline,
                                )
                            except Exception:
                                pass

    def _clear_pbms_activities(self, feedback=False):
        """Mark existing pending activities on this record as completed rapidly without chatter clutter."""
        for record in self:
            if not hasattr(record, "activity_ids"):
                continue
            activities = record.activity_ids
            if activities:
                try:
                    activities.sudo().unlink()
                except Exception:
                    pass

    def _send_pbms_mail_template(self, template_xmlid, partner_ids=None, email_values=None):
        """Send formatted HTML email template to specified partners directly without duplicating chatter."""
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not partner_ids:
            return

        # Strict security constraint: Only partners of users with active PBMS access rights receive PBMS emails
        valid_users = self.env["res.users"].sudo().search([
            ("partner_id", "in", partner_ids),
            ("active", "=", True),
        ]).filtered(lambda u: u._pbms_has_access())
        valid_partner_ids = valid_users.mapped("partner_id").ids
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
                self.env["mail.mail"].sudo().create(mail_vals)
            except Exception as e:
                _logger.warning("Failed sending mail template %s for %s ID %s: %s", template_xmlid, record._name, record.id, e)

    # -------------------------------------------------------------------------
    # Notification Dispatchers (FR-WP-052 through FR-WP-058)
    # -------------------------------------------------------------------------
    def _notify_submission(self):
        """Notify submitter and clear activities without heavy card or email overhead."""
        for line in self:
            line._clear_pbms_activities(feedback=_("Plan submitted."))

    def _notify_pending_approval(self, target_stage, stage_name):
        """Update activities and send Discuss inbox notification to next stage reviewers."""
        for line in self:
            line._clear_pbms_activities(feedback=_("Moved to stage: %s") % stage_name)
            reviewers = line._get_stage_reviewers(target_stage)
            if self.env.user:
                reviewers = reviewers.filtered(lambda u: u.id != self.env.uid)
            if reviewers:
                cat_label = dict(line._fields["category"].selection).get(line.category, line.category or "") if hasattr(line, "category") and "category" in line._fields else ""
                unit_name = line.org_unit_id.display_name if line.org_unit_id else ""
                subject = _("📋 Plan Pending Review: %s - %s") % (line.display_name, stage_name)
                body = Markup(
                    _("<p>The <b>%(category)s</b> plan for <b>%(unit)s</b> has been submitted to <b>%(stage)s</b> and is awaiting your review/endorsement.</p>"
                      "<p>• <b>Work Unit:</b> %(unit)s<br/>"
                      "• <b>Submitted / Escalated By:</b> %(user)s<br/>"
                      "• <b>Status:</b> %(stage)s</p>")
                ) % {
                    "category": cat_label or _("Planning"),
                    "unit": unit_name,
                    "stage": stage_name,
                    "user": self.env.user.name,
                }
                line._send_inbox_notification(reviewers, subject, body)

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
            recipients = target_users or target_partners
            if recipients:
                ret_subject = _("↩️ %s: %s") % (title, line.display_name)
                line._send_inbox_notification(recipients, ret_subject, Markup(msg))

    def _notify_approved(self, stage_label, is_final=False):
        """Notify submitters and stakeholders upon final approval."""
        for line in self:
            line._clear_pbms_activities(feedback=_("Approved at stage: %s") % stage_label)
            if is_final:
                # Update approved workforce establishment in operating.unit.job.position
                line._update_approved_workforce_establishment()
                stakeholders = line._get_plan_stakeholder_partners()
                if self.env.user and self.env.user.partner_id:
                    stakeholders = stakeholders.filtered(lambda p: p.id != self.env.user.partner_id.id)
                if stakeholders:
                    appr_subject = _("🎉 Plan Approved: %s") % line.display_name
                    appr_body = Markup(
                        _("<p>The plan <b>%(name)s</b> for <b>%(unit)s</b> has received <b>Final Approval</b>.</p>"
                          "<p>• <b>Approved By:</b> %(user)s<br/>"
                          "• <b>Stage:</b> %(stage)s</p>")
                    ) % {
                        "name": line.display_name,
                        "unit": line.org_unit_id.display_name if line.org_unit_id else "",
                        "user": self.env.user.name,
                        "stage": stage_label,
                    }
                    line._send_inbox_notification(stakeholders, appr_subject, appr_body)

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

            if stakeholders:
                cat_title = getattr(line, "plan_category_title", False) or _("Plan Request")
                req_no = getattr(line, "request_number", "") or "Plan"
                line._send_inbox_notification(
                    stakeholders,
                    _("%s Rejected: %s - %s") % (cat_title, req_no, unit_name),
                    f"<b>{cat_title} Status Update: Plan Rejected</b><br/>"
                    f"<b>Plan / Request:</b> {req_no}<br/>"
                    f"<b>Work Unit:</b> {unit_name}<br/>"
                    f"<b>Reason for Rejection:</b> {rej_reason}<br/>"
                    f"<p style='margin: 8px 0 0 0; color: #A82020;'>Your plan has been declined by the reviewing authority.</p>"
                )

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

            # People Operations & Management Directorate handles recruitment commencement for approved workforce plans
            po_users = self._get_users_with_group("bunna_pbms.group_pbms_people_operations")
            target_users = po_users
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
                    note=_(
                        "Workforce Plan endorsed by CPCO to People Operations & Management Directorate. "
                        "Please initiate candidate sourcing and recruitment per approved schedule."
                    ),
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

    def _validate_mandatory_monthly_targets(self):
        """Validate monthly targets for Customer Base, Deposit Mobilization, Digital Banking, and FX Mobilization
        during plan request creation and submission. Never runs during approval states.
        Deposit allows positive (> 0) and negative (< 0) values, rejecting only zero (0.0)."""
        CONSOLIDABLE_CATS = ("customer_base", "deposit", "digital_banking", "fx")
        MONTH_SEQUENCE = [
            ("m01", _("July")), ("m02", _("August")), ("m03", _("September")),
            ("m04", _("October")), ("m05", _("November")), ("m06", _("December")),
            ("m07", _("January")), ("m08", _("February")), ("m09", _("March")),
            ("m10", _("April")), ("m11", _("May")), ("m12", _("June")),
        ]
        CAT_NAMES = {
            "customer_base": _("Customer Base"),
            "deposit": _("Deposit Mobilization"),
            "digital_banking": _("Digital Banking"),
            "fx": _("FX Mobilization"),
        }
        for plan in self:
            # Strictly validate only during creating / editing request in draft / returned / info_requested
            if plan.state not in ("draft", "returned", "info_requested", False):
                continue
            cat = getattr(plan, "category", False)
            target_cats = set()
            if cat in CONSOLIDABLE_CATS:
                target_cats.add(cat)
            if hasattr(plan, "line_ids") and plan.line_ids:
                for l in plan.line_ids:
                    if l.line_type in CONSOLIDABLE_CATS:
                        target_cats.add(l.line_type)

            for c in target_cats:
                cat_label = CAT_NAMES.get(c, c.replace("_", " ").title())
                c_lines = plan.line_ids.filtered(lambda l: l.line_type == c) if hasattr(plan, "line_ids") else plan.env["pbms.plan.category.line"]
                if not c_lines and hasattr(plan, f"{c}_line_ids"):
                    c_lines = getattr(plan, f"{c}_line_ids")
                if c_lines:
                    for line in c_lines:
                        if c == "customer_base" and getattr(line, "base_type", False) == "dormant_reduction":
                            continue
                        prev_val = None
                        prev_m = None
                        for fname, m_label in MONTH_SEQUENCE:
                            val = getattr(line, fname, 0.0) or 0.0
                            if c == "deposit":
                                if float_is_zero(val, precision_digits=2):
                                    raise ValidationError(_(
                                        "%(category)s - %(month)s: Monthly plan cannot be zero. Each month must have a positive or negative target.",
                                        category=cat_label,
                                        month=m_label,
                                    ))
                            else:
                                if val <= 0.0:
                                    raise ValidationError(_(
                                        "%(category)s — %(month)s: Each month must have a value greater than zero.",
                                        category=cat_label,
                                        month=m_label,
                                    ))
                            if prev_val is not None and float(val) < float(prev_val):
                                raise ValidationError(_(
                                    "%(category)s: %(curr_month)s plan must not be below %(prev_month)s plan (%(curr_month)s: %(val)s, %(prev_month)s: %(prev_val)s). Each month's plan must be greater than or equal to the previous month.",
                                    category=cat_label,
                                    curr_month=m_label,
                                    prev_month=prev_m,
                                    val=val,
                                    prev_val=prev_val,
                                ))
                            prev_val = val
                            prev_m = m_label
                elif cat == c:
                    prev_val = None
                    prev_m = None
                    for fname, m_label in MONTH_SEQUENCE:
                        val = getattr(plan, fname, 0.0) or 0.0
                        if c == "deposit":
                            if float_is_zero(val, precision_digits=2):
                                raise ValidationError(_(
                                    "%(category)s - %(month)s: Monthly plan cannot be zero. Each month must have a positive or negative target.",
                                    category=cat_label,
                                    month=m_label,
                                ))
                        else:
                            if val <= 0.0:
                                raise ValidationError(_(
                                    "%(category)s — %(month)s: Each month must have a value greater than zero.",
                                    category=cat_label,
                                    month=m_label,
                                ))
                        if prev_val is not None and float(val) < float(prev_val):
                            raise ValidationError(_(
                                "%(category)s: %(curr_month)s plan must not be below %(prev_month)s plan (%(curr_month)s: %(val)s, %(prev_month)s: %(prev_val)s). Each month's plan must be greater than or equal to the previous month.",
                                category=cat_label,
                                curr_month=m_label,
                                prev_month=prev_m,
                                val=val,
                                prev_val=prev_val,
                            ))
                        prev_val = val
                        prev_m = m_label

    # =========================================================================
    # WORKFLOW ACTIONS
    # =========================================================================
    def action_submit(self):
        plans_to_submit = self.filtered(lambda p: p.state in ("draft", "returned", "info_requested"))
        if not plans_to_submit and all(p.state in ("submitted", "chief_review", "district_approved", "district_endorsed") for p in self):
            return True
        plans_to_submit._check_editable()
        if hasattr(plans_to_submit, "_realign_lines_to_matching_cards"):
            plans_to_submit._realign_lines_to_matching_cards()
        elif hasattr(plans_to_submit, "_sync_category_records"):
            plans_to_submit.with_context(bypass_plan_lock=True)._sync_category_records()

        # Collect all planning category records for the same work unit & cycle to submit
        Config = self.env.get("pbms.planning.config")
        candidate_plans = self.env[self._name]
        for rec in plans_to_submit:
            candidate_plans |= rec
            if self.env.context.get("submit_single_category"):
                continue
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                # Include sibling resource plans (manpower, general_expense, fixed_asset)
                # or all sibling plans for this unit & cycle so GE, FA, and Workforce submit together
                is_req = bool(self.env.context.get("is_planning_request") or getattr(rec, "is_planning_request", False))
                target_cats = False if is_req else (("manpower", "general_expense", "fixed_asset") if rec.category in ("manpower", "general_expense", "fixed_asset") else (rec.category,))
                domain = [
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),
                    ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),
                    ("active", "=", True),
                    ("state", "in", ("draft", "returned", "info_requested")),
                ]
                if target_cats:
                    domain.append(("category", "in", target_cats))
                siblings = self.env[rec._name].search(domain)
                candidate_plans |= siblings
                # Reactivate any inadvertently archived sibling cards for enabled categories that have data
                inactive_siblings = self.env[rec._name].with_context(active_test=False).search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("is_consolidated_district_plan", "=", bool(rec.is_consolidated_district_plan)),
                    ("is_consolidated_ho_plan", "=", bool(rec.is_consolidated_ho_plan)),
                    ("active", "=", False),
                ])
                for inact in inactive_siblings:
                    inact_has_data = bool(inact.line_ids) or any(getattr(inact, m, 0.0) for m in PBMS_MONTH_FIELDS) or ((getattr(inact, "annual_total", 0.0) or 0.0) > 0.0)
                    inact_enabled = Config.is_category_enabled(inact.category, inact.org_unit_id) if (Config is not None and inact.category and inact.org_unit_id) else True
                    if inact_has_data and inact_enabled:
                        inact.with_context(bypass_plan_lock=True).write({"active": True})
                        candidate_plans |= inact

        # A plan can ONLY be submitted if:
        # 1. Its category is active / enabled in Planning Configuration for its operating unit
        # 2. It has actual data (requirement lines or non-zero targets)
        all_plans = self.env[self._name]
        MOBILIZATION_CATS = {"deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"}
        for p in candidate_plans:
            unit_type = p.org_unit_type or (p.org_unit_id.work_unit_type if p.org_unit_id else False)
            is_dist_or_ho = unit_type in ("district_office", "head_office", "regional_office")
            if is_dist_or_ho and p.category in MOBILIZATION_CATS:
                is_enabled = True
            else:
                is_enabled = Config.is_category_enabled(p.category, p.org_unit_id) if (Config is not None and p.category and p.org_unit_id) else True
            has_data = p._pbms_has_valid_planning_data()
            if not is_enabled:
                # Clean up / deactivate any phantom draft plans whose category is disabled in config
                if p.state in ("draft", "returned", "info_requested"):
                    p.with_context(bypass_plan_lock=True).write({"active": False})
                continue
            if not has_data:
                continue
            all_plans |= p

        if not all_plans:
            raise ValidationError(_("You cannot submit an empty planning request. Please plan at least one planning category before submitting."))

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

        # 0. Ensure all lines and all category plans have their quarter targets, costs, and annual totals computed
        all_lines = all_plans.mapped("line_ids")
        if all_lines:
            if hasattr(all_lines, "_compute_quarter_targets"):
                all_lines._compute_quarter_targets()
            if hasattr(all_lines, "_compute_annual_total"):
                all_lines._compute_annual_total()
            if hasattr(all_lines, "_compute_annual_total_cost"):
                all_lines._compute_annual_total_cost()
            if hasattr(all_lines, "_compute_fa_quarter_costs"):
                all_lines._compute_fa_quarter_costs()
            if hasattr(all_lines, "_compute_fa_annual_total_cost"):
                all_lines._compute_fa_annual_total_cost()

        if hasattr(all_plans, "_compute_totals"):
            all_plans._compute_totals()
        if hasattr(all_plans, "_compute_category_summaries"):
            all_plans._compute_category_summaries()
        if hasattr(all_plans, "_compute_manpower_quarter_totals"):
            all_plans._compute_manpower_quarter_totals()
        if hasattr(all_plans, "_compute_fa_quarter_totals"):
            all_plans._compute_fa_quarter_totals()
        if hasattr(all_plans, "_compute_fa_quarter_quantities"):
            all_plans._compute_fa_quarter_quantities()
        if hasattr(all_plans, "_compute_total_fixed_asset_cost"):
            all_plans._compute_total_fixed_asset_cost()
        if hasattr(all_plans, "_compute_operating_unit_manpower_budget"):
            all_plans._compute_operating_unit_manpower_budget()
        all_plans.flush_recordset()

        # 1. Validate mandatory non-zero monthly values for Customer Base, Deposit, Digital Banking, FX
        all_plans._validate_mandatory_monthly_targets()
        if hasattr(all_plans, "_check_all_dropdowns_planned"):
            all_plans.with_context(force_validate_dropdowns=True)._check_all_dropdowns_planned()

        # 2. Snapshot all proposed targets in batch (ultra-fast single SQL query)
        all_lines = all_plans.mapped("line_ids")
        if all_lines and hasattr(all_lines, "_snapshot_proposed_targets"):
            all_lines.with_context(bypass_plan_lock=True)._snapshot_proposed_targets(force=True)

        # 3. Batch update state of plans grouped by target state for high performance
        old_states = {p.id: p.state for p in all_plans}
        plans_by_action = {}
        now = fields.Datetime.now()
        for line in all_plans:
            target_cat = getattr(line, "category", False)
            is_ho = line._is_head_office_plan() or line.org_unit_type == "head_office" or (line.org_unit_id and getattr(line.org_unit_id, "work_unit_type", False) == "head_office")
            is_dist = line._is_district_plan() or line.org_unit_type == "district_office"
            is_ho_cascade_cat = target_cat in (
                "manpower", "general_expense", "fixed_asset",
                "credit_portfolio", "initiative_budget",
                "loan_disbursement_collection", "loan_outstanding",
                "deposit", "customer_base", "fx", "digital_banking",
            )
            is_people_ops = self.env.user.has_group("bunna_pbms.group_pbms_people_operations") or (line.org_unit_id and "people" in (line.org_unit_id.name or "").lower() and "operation" in (line.org_unit_id.name or "").lower())

            if (is_ho and is_ho_cascade_cat) or is_people_ops:
                key = ("chief_review", False)
            elif is_dist and target_cat == "manpower":
                key = ("chief_review", False)
            elif is_dist:
                key = ("district_endorsed", True)
            else:
                key = ("submitted", False)
            plans_by_action.setdefault(key, self.env[self._name])
            plans_by_action[key] |= line

        for (next_state, is_dist_endorsed), plan_group in plans_by_action.items():
            write_vals = {
                "state": next_state,
                "submitted_by": self.env.uid,
                "submitted_date": now,
            }
            if is_dist_endorsed:
                write_vals["district_reviewer_id"] = self.env.uid
                write_vals["district_review_date"] = now
            plan_group.sudo().with_context(
                bypass_plan_lock=True,
                skip_sync_category_records=True,
                skip_split_mixed_lines=True,
                skip_dropdown_plan_check=True,
            ).write(write_vals)

            for line in plan_group:
                old_s = old_states.get(line.id, "draft")
                if next_state == "chief_review":
                    line._log_audit_action("submit", old_s, "chief_review", _("%s submitted to Respective Chief for review.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("chief_review", _("Respective Chief Review"))
                elif next_state == "district_endorsed":
                    line._log_audit_action("submit", old_s, "district_endorsed", _("District Office %s submitted/endorsed to Head Office Functional Reviewer.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("district_endorsed", _("Head Office Functional Review"))
                else:
                    line._log_audit_action("submit", old_s, "submitted", _("%s submitted for district review.") % (line.plan_category_title or _("Plan")))

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted Successfully'),
                'message': _('Plan has been submitted successfully for review.'),
                'type': 'success',
                'sticky': False,
            }
        }







    def _get_workflow_sibling_plans(self):
        """Return self, strictly acting on the records explicitly selected
        by the user without automatically expanding to or approving other plans."""
        clean_ids = [i for i in self._ids if isinstance(i, int)]
        return self.browse(clean_ids) if len(clean_ids) != len(self._ids) else self

    def action_district_approve(self):
        all_plans = self._get_workflow_sibling_plans()
        districts_to_consolidate = set()
        for line in all_plans:
            if line.state not in ("submitted", "info_requested"):
                # Plans already past district review are silently skipped (e.g. district_approved, chief_review)
                if line.state in ("district_approved", "district_endorsed", "chief_review", "people_solutions_review",
                                  "cpco_review", "committee_review", "ceo_approval", "board_ceo_approval",
                                  "ho_endorse", "cpco_endorse", "ho_reviewed", "approved", "rejected"):
                    continue
                raise UserError(_("Plan must be submitted before it can be district approved. Current state: %s") % line.state)
            if not line._pbms_can_district_review_plan():
                raise AccessError(_("Only District Reviewers can approve child work unit plans while they are under district review."))
            old_state = line.state
            target_cat = getattr(line, "category", False)
            if line.is_district_unit or line._is_district_plan() or line.org_unit_type in ("district_office", "regional_office", "district"):
                next_state = "district_endorsed"
                next_label = _("District Endorsed (Forwarded to Head Office)")
                next_msg = line.district_comment or _("Endorsed by District Office.")

                # Finalize District's proposed figures on District plan lines to reflect the district-edited amount
                for dist_line in line.line_ids:
                    dist_line_vals = {
                        "proposed_annual_total": dist_line.annual_total or 0.0,
                        "proposed_opening_balance": dist_line.opening_balance or 0.0,
                    }
                    for i in range(1, 13):
                        dist_line_vals[f"proposed_m{i:02d}"] = getattr(dist_line, f"m{i:02d}", 0.0) or 0.0
                    dist_line.with_context(bypass_plan_lock=True).write(dist_line_vals)

                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()
                if hasattr(line, "_compute_plan_proposed_approved_totals"):
                    line._compute_plan_proposed_approved_totals()
            elif target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                # Mobilization branch plans: remain strictly under District Reviewer once approved
                next_state = "district_approved"
                next_label = _("District Approved (Retained at District)")
                next_msg = line.district_comment or _("Approved by District Reviewer. Retained at District level.")
            elif target_cat == "manpower":
                # Branch Workforce: after District approves, routes strictly to District's Respective Chief Review
                next_state = "chief_review"
                next_label = _("Respective Chief Review (Workforce)")
                next_msg = line.district_comment or _("Approved by District. Forwarded to Respective Chief for Workforce review.")
            else:
                # Branch General Expense, Fixed Asset: after District approves, routes to Head Office Functional Reviewer
                next_state = "district_approved"
                next_label = _("District Approved (Forwarded to Head Office)")
                next_msg = line.district_comment or _("Approved by District. Forwarded to Head Office Functional Reviewer.")

            line.with_context(bypass_plan_lock=True).write({
                "state": next_state,
                "active": True,
                "district_reviewer_id": self.env.uid,
                "district_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("district_approve", old_state, next_state, next_msg)
            line._notify_pending_approval(next_state, next_label)

            # Collect district plans to consolidate once per district and category in batch
            if not line.is_district_unit and not line._is_district_plan():
                target_cat = getattr(line, "category", False)
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    district = line.district_id or line._find_district_ancestor(line.org_unit_id)
                    if district:
                        districts_to_consolidate.add((line.cycle_id.id, district.id, target_cat))

        # Run single consolidation pass per district/category after all lines are approved
        for cycle_id_val, district_id_val, target_cat_val in districts_to_consolidate:
            cycle = self.env["pbms.planning.cycle"].browse(cycle_id_val)
            dist_unit = self.env["operating.unit"].browse(district_id_val)
            sample_line = all_plans.filtered(lambda l: l.category == target_cat_val)[:1] or all_plans[:1]
            if hasattr(sample_line, "_consolidate_district_plan_data"):
                dist_plan = sample_line.sudo().with_context(
                    target_category=target_cat_val,
                    skip_sync_category_records=True,
                )._consolidate_district_plan_data(cycle, dist_unit)
                if dist_plan:
                    if dist_plan.state in ("draft", "returned", "info_requested"):
                        dist_plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({
                            "state": "district_endorsed",
                            "active": True,
                        })
                        dist_plan._notify_pending_approval("district_endorsed", _("Head Office Functional Review"))
                    elif not dist_plan.active:
                        dist_plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"active": True})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('District Approved Successfully'),
                'message': _('Plan has been approved by District Reviewer successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_district_endorse(self):
        self.action_district_approve()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('District Endorsed Successfully'),
                'message': _('Plan has been endorsed and forwarded to Head Office successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_ho_approve(self):
        """Final approval action by Head Office Functional Reviewer for Mobilization Categories
        (Deposit, Customer Base, FX, Digital Banking) and General Expense.
        When the HO Reviewer approves:
        1. For General Expense: marks the plan approved and populates approved expense totals.
        2. For Mobilization: marks district overview and attached branch plans as approved,
           and consolidates Bank-Wide Head Office overview.
        """
        all_plans = self._get_workflow_sibling_plans()
        ho_consolidate_keys = set()
        for line in all_plans:
            if not line._pbms_can_ho_review_plan():
                raise AccessError(_("Only Head Office Functional Reviewers can approve plans at this stage."))
            target_cat = getattr(line, "category", False)
            if target_cat not in ("deposit", "customer_base", "fx", "digital_banking", "general_expense", "credit_portfolio", "loan_disbursement_collection", "loan_outstanding"):
                raise UserError(_("This approval action is only applicable to Mobilization Categories, General Expense, Income Plan, and Loans."))
            if line.org_unit_type in ("district_office", "regional_office") or line.is_district_unit:
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    if line.state not in ("district_endorsed", "ho_reviewed"):
                        raise UserError(_("District plans must be endorsed by the District Reviewer before Head Office final approval."))
            elif line.org_unit_type == "head_office" or line.is_head_office_unit:
                if line.state not in ("submitted", "ho_reviewed"):
                    continue
            else:
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    raise UserError(_("Branch mobilization plans (%s) remain under District Reviewer. Head Office reviewers only review consolidated District plans.") % dict(line._fields["category"].selection).get(target_cat, target_cat))
                elif target_cat in ("general_expense", "credit_portfolio", "loan_disbursement_collection", "loan_outstanding"):
                    if line.state not in ("submitted", "district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed"):
                        continue
                else:
                    if line.state not in ("district_approved", "district_endorsed", "committee_review", "board_ceo_approval", "ho_reviewed"):
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

            # For General Expense, Credit Portfolio, and Loans: populate approved targets directly on lines
            if target_cat in ("general_expense", "credit_portfolio", "loan_disbursement_collection", "loan_outstanding"):
                cat_lines = (
                    line.expense_line_ids if target_cat == "general_expense"
                    else line.credit_portfolio_line_ids if target_cat == "credit_portfolio"
                    else line.loan_disbursement_line_ids if target_cat == "loan_disbursement_collection"
                    else line.loan_outstanding_line_ids if target_cat == "loan_outstanding"
                    else line.line_ids
                ) or line.line_ids
                if hasattr(cat_lines, "_populate_approved_targets_batch"):
                    cat_lines._populate_approved_targets_batch()
                else:
                    for pl in cat_lines:
                        m_appr = {}
                        for i in range(1, 13):
                            m_appr[f"approved_m{i:02d}"] = getattr(pl, f"approved_m{i:02d}", 0.0) or getattr(pl, f"m{i:02d}", 0.0) or 0.0

                        if getattr(pl, "line_type", False) == "credit_portfolio" and getattr(pl, "totals_basis", False) == "last_month":
                            appr_total = m_appr["approved_m12"]
                        else:
                            appr_total = (
                                getattr(pl, "approved_annual_total", 0.0)
                                or getattr(pl, "annual_total", 0.0)
                                or getattr(pl, "proposed_annual_total", 0.0)
                                or sum(m_appr.values())
                            )
                        if not appr_total and any(m_appr.values()):
                            appr_total = sum(m_appr.values())

                        vals = {
                            "approved_annual_total": appr_total,
                            "approved_opening_balance": getattr(pl, "approved_opening_balance", 0.0) or getattr(pl, "opening_balance", 0.0) or 0.0,
                            **m_appr,
                        }
                        pl.with_context(bypass_plan_lock=True).write(vals)

                cat_label = dict(line._fields["category"].selection).get(target_cat, target_cat)
                line._log_audit_action("ho_approve", old_state, "approved", line.ho_comment or _("%s plan finally approved by Head Office Functional Reviewer.") % cat_label)
                line._notify_approved(_("%s Plan") % cat_label, is_final=True)
                continue

            # Populate approved target fields ONLY for Head Office bank-wide overview plan.
            # For District and Branch plans, approved targets are ONLY populated when actually cascaded!
            if line.is_head_office_unit or line._is_head_office_plan() or line.org_unit_type == "head_office":
                # Finalize Head Office proposed figures to reflect the Head Office-edited amount
                for ho_line in line.line_ids:
                    ho_line_vals = {
                        "proposed_annual_total": ho_line.annual_total or 0.0,
                        "proposed_opening_balance": ho_line.opening_balance or 0.0,
                    }
                    for i in range(1, 13):
                        ho_line_vals[f"proposed_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                    ho_line.with_context(bypass_plan_lock=True).write(ho_line_vals)

                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()
                if hasattr(line, "_compute_plan_proposed_approved_totals"):
                    line._compute_plan_proposed_approved_totals()

                if hasattr(line.line_ids, "_populate_approved_from_annual_total_batch"):
                    line.line_ids._populate_approved_from_annual_total_batch()
                else:
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

            # If approving a District Overview Plan, only auto-approve branch plans for non-mobilization categories.
            # Branch mobilization plans (deposit, customer_base, fx, digital_banking) strictly remain under District Reviewer.
            if (line.is_district_unit or line._is_district_plan() or line.org_unit_type in ("district_office", "regional_office", "district")) and target_cat not in ("deposit", "customer_base", "fx", "digital_banking"):
                self.env[line._name].flush_model(["state", "district_id", "cycle_id", "category", "active", "org_unit_id"])
                branch_plans = self.env[line._name].sudo().search([
                    ("cycle_id", "=", line.cycle_id.id),
                    ("category", "=", target_cat),
                    ("active", "=", True),
                    ("org_unit_type", "not in", ("district_office", "regional_office", "district")),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed")),
                    "|",
                    ("district_id", "=", line.org_unit_id.id),
                    ("org_unit_id.parent_unit", "=", line.org_unit_id.id),
                ])
                if branch_plans:
                    branch_plans.with_context(
                        bypass_plan_lock=True,
                        skip_sync_category_records=True,
                        skip_split_mixed_lines=True,
                        skip_cleanup_district_cards=True,
                        skip_dropdown_plan_check=True,
                    ).write({
                        "state": "approved",
                        "ho_reviewer_id": self.env.uid,
                        "ho_review_date": now,
                        "approver_id": self.env.uid,
                        "approval_date": now,
                    })
                    # Ensure un-cascaded branch lines in the 4 consolidable categories strictly have 0.0 approved values
                    if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                        uncascaded_bp_lines = branch_plans.mapped("line_ids").filtered(
                            lambda l: not l.is_cascaded and l.line_type in ("deposit", "customer_base", "fx", "digital_banking")
                        )
                        if uncascaded_bp_lines:
                            uncascaded_bp_lines.with_context(
                                bypass_plan_lock=True,
                                skip_sync_category_records=True,
                                skip_split_mixed_lines=True,
                            ).write({
                                "approved_annual_total": 0.0,
                                "approved_opening_balance": 0.0,
                                **{f"approved_m{i:02d}": 0.0 for i in range(1, 13)},
                            })
                    if hasattr(branch_plans, "_compute_category_summaries"):
                        branch_plans._compute_category_summaries()

                # Ensure un-cascaded District lines in the 4 consolidable categories strictly have 0.0 approved values!
                # District approved values are ONLY populated when HO functional reviewer clicks 'Cascade Targets to Districts'!
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    uncascaded_dist_lines = line.line_ids.filtered(
                        lambda l: not l.is_cascaded and l.line_type in ("deposit", "customer_base", "fx", "digital_banking")
                    )
                    if uncascaded_dist_lines:
                        uncascaded_dist_lines.with_context(
                            bypass_plan_lock=True,
                            skip_sync_category_records=True,
                            skip_split_mixed_lines=True,
                        ).write({
                            "approved_annual_total": 0.0,
                            "approved_opening_balance": 0.0,
                            **{f"approved_m{i:02d}": 0.0 for i in range(1, 13)},
                        })
                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()

            # Collect cycle and category to consolidate Bank-Wide Head Office once in batch
            if target_cat in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"):
                ho_consolidate_keys.add((line.cycle_id.id, target_cat))

            # If line was already the Head Office plan, also ensure only endorsed district and approved branch plans are approved
            if line.org_unit_type == "head_office":
                sub_plans = self.env[line._name].search([
                    ("cycle_id", "=", line.cycle_id.id),
                    ("category", "=", target_cat),
                    ("active", "=", True),
                    ("org_unit_type", "!=", "head_office"),
                    ("state", "in", ("district_endorsed", "ho_reviewed")),
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
                        child_branch_plans = self.env[line._name].search([
                            ("cycle_id", "=", line.cycle_id.id),
                            ("category", "=", target_cat),
                            ("active", "=", True),
                            ("district_id", "=", sp.org_unit_id.id),
                            ("org_unit_type", "not in", ("head_office", "district_office", "regional_office")),
                            ("state", "in", ("district_approved", "district_endorsed")),
                        ])
                        if child_branch_plans:
                            child_branch_plans.with_context(bypass_plan_lock=True).write({
                                "state": "approved",
                                "ho_reviewer_id": self.env.uid,
                                "ho_review_date": now,
                                "approver_id": self.env.uid,
                                "approval_date": now,
                            })
                        all_approved_plans = sp | (child_branch_plans or self.env[line._name])
                        for plan_rec in all_approved_plans:
                            for pl in plan_rec.line_ids:
                                if not pl.approved_annual_total:
                                    pl_prop = getattr(pl, "proposed_annual_total", 0.0) or getattr(pl, "annual_total", 0.0) or 0.0
                                    m_vals = {
                                        f"approved_m{i:02d}": getattr(pl, f"proposed_m{i:02d}", 0.0) or getattr(pl, f"m{i:02d}", 0.0) or 0.0
                                        for i in range(1, 13)
                                    }
                                    pl.with_context(bypass_plan_lock=True).write({
                                        "approved_annual_total": pl_prop,
                                        "approved_opening_balance": getattr(pl, "proposed_opening_balance", 0.0) or getattr(pl, "opening_balance", 0.0) or 0.0,
                                        **m_vals,
                                    })
                            if hasattr(plan_rec, "_compute_category_summaries"):
                                plan_rec._compute_category_summaries()
                            if hasattr(plan_rec, "_compute_plan_proposed_approved_totals"):
                                plan_rec._compute_plan_proposed_approved_totals()

        # Consolidate all districts into Bank-Wide Head Office record once per cycle & category in batch
        if ho_consolidate_keys:
            ho_unit = self.env["operating.unit"].search([("work_unit_type", "=", "head_office")], limit=1)
            if ho_unit:
                for cycle_id_val, target_cat_val in ho_consolidate_keys:
                    cycle = self.env["pbms.planning.cycle"].browse(cycle_id_val)
                    sample_line = all_plans.filtered(lambda l: l.category == target_cat_val)[:1] or all_plans[:1]
                    if hasattr(sample_line, "_consolidate_ho_plan_data"):
                        ho_plan = sample_line.sudo().with_context(category=target_cat_val)._consolidate_ho_plan_data(cycle, ho_unit)
                        if ho_plan:
                            ho_old_state = ho_plan.state
                            ho_plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({
                                "state": "approved",
                                "ho_reviewer_id": self.env.uid,
                                "ho_review_date": now,
                                "approver_id": self.env.uid,
                                "approval_date": now,
                                "submitted_by": self.env.uid,
                                "submitted_date": now,
                            })
                            for ho_line in ho_plan.line_ids:
                                ho_line_vals = {
                                    "proposed_annual_total": ho_line.annual_total or 0.0,
                                    "proposed_opening_balance": ho_line.opening_balance or 0.0,
                                }
                                for i in range(1, 13):
                                    ho_line_vals[f"proposed_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                                ho_line.with_context(bypass_plan_lock=True).write(ho_line_vals)

                            if hasattr(ho_plan.line_ids, "_populate_approved_from_annual_total_batch"):
                                ho_plan.line_ids._populate_approved_from_annual_total_batch()
                            else:
                                for ho_line in ho_plan.line_ids:
                                    vals = {
                                        "approved_opening_balance": getattr(ho_line, "opening_balance", 0.0) or 0.0,
                                        "approved_annual_total": getattr(ho_line, "annual_total", 0.0) or 0.0,
                                    }
                                    for i in range(1, 13):
                                        vals[f"approved_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                                    ho_line.with_context(bypass_plan_lock=True).write(vals)

                            if hasattr(ho_plan, "_compute_category_summaries"):
                                ho_plan._compute_category_summaries()

                            ho_plan._log_audit_action("ho_approve", ho_old_state, "approved", _("Bank-Wide Head Office consolidated plan finally approved."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved Successfully'),
                'message': _('Plan has been approved successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_submit_to_committee(self):
        """Head Office Functional Reviewer reviews Fixed Asset / Initiative Budget
        and submits to the Review Committee."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("fixed_asset", "initiative_budget"):
                raise UserError(_("This action is only applicable to Fixed Asset and Initiative Budget categories."))
            if not (line._pbms_can_ho_review_plan() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only authorized Head Office Functional Reviewers or Administrators can submit to the Review Committee."))
            if line.state not in ("district_approved", "district_endorsed", "submitted", "returned", "info_requested", "ho_reviewed"):
                continue

            # Snapshot proposed targets so requested figures are preserved
            if hasattr(line, "line_ids") and line.line_ids:
                pass  # Preserved planner proposed targets intact

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted to Committee Successfully'),
                'message': _('Plan has been submitted to the Review Committee successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_committee_approve_resource(self):
        """Review Committee grants final approval for Fixed Asset and Initiative Budget plans.
        Directly moves state to 'approved' without HR fulfillment or CEO approval."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("fixed_asset", "initiative_budget"):
                raise UserError(_("This action is only applicable to Fixed Asset and Initiative Budget categories."))
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
            elif cat == "initiative_budget":
                for ib in (line.initiative_budget_line_ids or line.line_ids):
                    cost = getattr(ib, "initiative_cost", 0.0) or getattr(ib, "annual_total", 0.0) or 0.0
                    ib.with_context(bypass_plan_lock=True).write({
                        "approved_annual_total": cost,
                    })

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
            cat_name = "Fixed Asset" if cat == "fixed_asset" else "Initiative Budget"
            line._log_audit_action("committee_approve", old_state, "approved", line.committee_comment or _("Finally approved by Review Committee."))
            line._notify_approved(_("%s Plan") % cat_name, is_final=True)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved Successfully'),
                'message': _('Plan has been approved by the Review Committee successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_ho_review(self):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_ho_review_plan():
                raise AccessError(_("Only Head Office Functional Reviewers can review child work unit plans at this stage."))
            if line.state not in ("draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed"):
                continue

            # Snapshot proposed targets so the latest edited figures are locked and reflected
            if hasattr(line, "line_ids") and line.line_ids:
                pass  # Preserved planner proposed targets intact

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('HO Review Completed Successfully'),
                'message': _('Head office review completed successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

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
                pass  # Preserved planner proposed targets intact

            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "committee_review",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("hr_submit_committee", old_state, "committee_review", line.ho_comment or _("Submitted to Budget Hiring Committee for target approval."))
            line._notify_pending_approval("committee_review", _("Budget Hiring Committee Review"))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted to Committee Successfully'),
                'message': _('Workforce plan submitted to Budget Hiring Committee successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_committee_approve(self):
        """Budget Hiring Committee reviews, edits targets & sourcing, and endorses to CEO for final approval."""
        if any(getattr(p, "category", False) in ("fixed_asset", "initiative_budget") for p in self):
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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Committee Approved Successfully'),
                'message': _('Workforce plan approved by Budget Hiring Committee and forwarded to CEO.'),
                'type': 'success',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejected Successfully'),
                'message': _('Workforce plan rejected by Budget Hiring Committee.'),
                'type': 'warning',
                'sticky': False,
            }
        }

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
                line.sudo()._compute_category_summaries()

            old_state = line.state
            line.sudo().with_context(bypass_plan_lock=True).write({
                "state": "ho_endorse",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
            })
            line.sudo()._log_audit_action("ceo_approve", old_state, "ho_endorse", line.ceo_comment or _("Approved by Chief Executive Officer. Automatically forwarded to Head Office Functional Reviewer for endorsement."))
            line.sudo()._notify_pending_approval("ho_endorse", _("Head Office Functional Reviewer Verification & Endorsement"))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('CEO Approved Successfully'),
                'message': _('Workforce plan approved by CEO and forwarded for endorsement.'),
                'type': 'success',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('HO Endorsed Successfully'),
                'message': _('Plan verified and endorsed to CPCO successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

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
            line_ctx._log_audit_action("cpco_endorse_operations", old_state, "approved", line.cpco_comment or _("Endorsed by CPCO to People Operations & Management Directorate. Plan is fully approved."))
            line_ctx._update_approved_workforce_establishment()
            line_ctx._auto_initiate_annual_workforce_vacancies()
            line_ctx._notify_approved(_("Workforce Plan"), is_final=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Workforce Plan Endorsed & Approved"),
                "message": _("Plan successfully endorsed to People Operations & Management Directorate. Recruitment commencement initiated."),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            }
        }

    action_cpco_endorse_to_operations = action_cpco_endorse_to_solutions

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
            line.sudo().with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "ceo_approver_id": self.env.uid,
                "ceo_approval_date": fields.Datetime.now(),
                "return_reason": reason,
            })
            line.sudo()._log_audit_action("ceo_reject", old_state, "rejected", reason)
            line.sudo()._notify_rejected(reason)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejected Successfully'),
                'message': _('Plan has been rejected by CEO.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    # -------------------------------------------------------------------------
    # ANNUAL WORKFORCE PLAN WORKFLOW ACTIONS (ISOLATED TO MANPOWER CATEGORY)
    # -------------------------------------------------------------------------
    def action_district_approve_workforce(self):
        """District Director reviews and forwards branch workforce plan:
        - Branch plans: → Respective Chief Review (chief_review)
          (The Respective Chief then escalates to People Solutions Directorate)
        - District/HO plans that reach here: → People Solutions Directorate directly
          (Their chief review already happened at submit time)
        """
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
                raise AccessError(_("Only District Directors, Department Directors, or Administrators can review and endorse workforce plans at this stage."))
            if line.state not in ("submitted", "draft", "returned", "info_requested"):
                continue

            old_state = line.state
            is_branch = line.org_unit_type in ("branch", "sub_branch", "service_center")

            if is_branch:
                # Branch workforce: District approves → Respective Chief Review (chief_review)
                next_state = "chief_review"
                msg = line.district_comment or _("Approved by District. Forwarded to Respective Chief for Workforce review.")
                notify_label = _("Respective Chief Review")
                line.with_context(bypass_plan_lock=True).write({
                    "state": next_state,
                    "district_reviewer_id": self.env.uid,
                    "district_review_date": fields.Datetime.now(),
                })
            else:
                # District/HO workforce: goes directly to People Solutions (chief review happened at submit)
                next_state = "people_solutions_review"
                msg = line.district_comment or _("Reviewed by District Director and forwarded to People Solutions Directorate.")
                notify_label = _("People Solutions Directorate Review")
                line.with_context(bypass_plan_lock=True).write({
                    "state": next_state,
                    "district_reviewer_id": self.env.uid,
                    "district_review_date": fields.Datetime.now(),
                })

            line._log_audit_action("district_approve_workforce", old_state, next_state, msg)
            line._notify_pending_approval(next_state, notify_label)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('District Approved Successfully'),
                'message': _('Workforce plan approved by District and forwarded successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_chief_approve_escalate(self):
        """Respective Chief approves & escalates plan:
        - Workforce / Manpower: to People Solutions Directorate (people_solutions_review)
        - General Expense, Fixed Asset, Mobilization (Deposit, Customer Base, FX, Digital Banking), etc.:
          to Head Office Functional Reviewer (submitted)
        """
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking") and not line.line_ids.filtered(lambda l: l.line_type in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking")):
                raise UserError(_("This action is only applicable to enabled planning categories."))
            can_approve = (
                self.env.user._pbms_is_respective_chief()
                or self.env.user._pbms_is_ceo()
                or line._is_plan_manager_user(self.env.user)
                or self.env.user._pbms_is_sppmd_admin()
                or self.env.is_admin()
                or self.env.su
            )
            if not can_approve:
                raise AccessError(_("Only Respective Chiefs, Managers, or Administrators can approve and escalate plans at this stage."))
            if not (self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                if line._is_plan_self_submitted(self.env.user):
                    raise AccessError(_("You cannot approve or endorse your own submitted plan."))
                chief_user = line._get_plan_chief_user()
                if chief_user and chief_user.id != self.env.uid and not line._is_plan_manager_user(self.env.user) and not self.env.user._pbms_is_ceo():
                    raise AccessError(_("Only the designated Respective Chief, CEO, or Manager can approve this plan."))
            if line.state not in ("chief_review", "district_approved", "district_endorsed"):
                continue

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            now = fields.Datetime.now()

            if cat == "manpower":
                next_state = "people_solutions_review"
                audit_msg = line.chief_comment or _("Approved and escalated by Respective Chief to People Solutions Directorate.")
                notify_stage = _("People Solutions Directorate Review")
                line.sudo().with_context(bypass_plan_lock=True).write({
                    "state": next_state,
                    "chief_approver_id": self.env.uid,
                    "chief_approval_date": now,
                })
                line.sudo()._log_audit_action("chief_approve_escalate", old_state, next_state, audit_msg)
                line.sudo()._notify_pending_approval(next_state, notify_stage)
            elif cat in ("fixed_asset", "general_expense", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking"):
                next_state = "submitted"
                audit_msg = line.chief_comment or _("Endorsed by Respective Chief to Head Office Functional Reviewer.")
                notify_stage = _("Head Office Functional Review")
                line.sudo().with_context(bypass_plan_lock=True).write({
                    "state": next_state,
                    "chief_approver_id": self.env.uid,
                    "chief_approval_date": now,
                })
                line.sudo()._log_audit_action("chief_approve_escalate", old_state, next_state, audit_msg)
                line.sudo()._notify_pending_approval(next_state, notify_stage)
            else:
                next_state = "submitted"
                audit_msg = line.chief_comment or _("Endorsed by Respective Chief to Head Office Functional Reviewer.")
                notify_stage = _("Head Office Functional Review")
                line.sudo().with_context(bypass_plan_lock=True).write({
                    "state": next_state,
                    "chief_approver_id": self.env.uid,
                    "chief_approval_date": now,
                })
                line.sudo()._log_audit_action("chief_approve_escalate", old_state, next_state, audit_msg)
                line.sudo()._notify_pending_approval(next_state, notify_stage)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Chief Approved Successfully'),
                'message': _('Plan approved and escalated by Respective Chief successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_chief_endorse(self):
        """Respective Chief endorses General Expense / Fixed Asset / Credit / Loans / Initiative to Head Office Functional Reviewer."""
        return self.action_chief_approve_escalate()

    def action_chief_reject(self, comment=False):
        """Respective Chief rejects the plan."""
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            cat = getattr(line, "category", False)
            if cat not in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking") and not line.line_ids.filtered(lambda l: l.line_type in ("manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget", "loan_disbursement_collection", "loan_outstanding", "deposit", "customer_base", "fx", "digital_banking")):
                raise UserError(_("This action is only applicable to enabled planning categories."))
            can_reject = (
                self.env.user._pbms_is_respective_chief()
                or self.env.user._pbms_is_ceo()
                or line._is_plan_manager_user(self.env.user)
                or self.env.user._pbms_is_sppmd_admin()
                or self.env.is_admin()
                or self.env.su
            )
            if not can_reject:
                raise AccessError(_("Only Respective Chiefs, Managers, or Administrators can reject plans at this stage."))
            if not (self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                if line._is_plan_self_submitted(self.env.user):
                    raise AccessError(_("You cannot reject your own submitted plan."))
                chief_user = line._get_plan_chief_user()
                if chief_user and chief_user.id != self.env.uid and not line._is_plan_manager_user(self.env.user) and not self.env.user._pbms_is_ceo():
                    raise AccessError(_("Only the designated Respective Chief, CEO, or Manager can reject this plan."))
            if line.state not in ("chief_review", "district_approved", "district_endorsed"):
                continue

            old_state = line.state
            line.sudo().with_context(bypass_plan_lock=True).write({
                "state": "rejected",
                "chief_approver_id": self.env.uid,
                "chief_approval_date": fields.Datetime.now(),
                "return_reason": comment or line.chief_comment or _("Rejected by Respective Chief."),
            })
            line.sudo()._log_audit_action("chief_reject", old_state, "rejected", comment or line.chief_comment or _("Rejected by Respective Chief."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejected Successfully'),
                'message': _('Plan has been rejected by Respective Chief.'),
                'type': 'warning',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Escalated Successfully'),
                'message': _('Workforce plan assessed and escalated to CPCO successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted to Committee Successfully'),
                'message': _('Workforce plan submitted to Budget Hiring Committee successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejected Successfully'),
                'message': _('Workforce plan rejected by CPCO.'),
                'type': 'warning',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approval Recorded Successfully'),
                'message': _('CEO / Board approval recorded successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejection Recorded Successfully'),
                'message': _('CEO / Board rejection recorded successfully.'),
                'type': 'warning',
                'sticky': False,
            }
        }

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
                # Plans already fully processed are skipped silently
                if line.state in ("approved", "rejected"):
                    continue
                raise UserError(_("Plan must reach HO Review stage before final approval. Current state: %s") % line.state)
            old_state = line.state
            line.with_context(bypass_plan_lock=True).write({
                "state": "approved",
                "approver_id": self.env.uid,
                "approval_date": fields.Datetime.now(),
            })

            # Snapshot and record approved target totals in batch
            if hasattr(line, "line_ids") and line.line_ids:
                ou_type = line.org_unit_id.work_unit_type if line.org_unit_id else False
                is_ho = (ou_type == "head_office")
                # Preserved planner proposed targets intact
                ctx = {"bypass_plan_lock": True, "skip_sync_category_records": True, "skip_split_mixed_lines": True, "skip_dropdown_plan_check": True}
                if is_ho:
                    if hasattr(line.line_ids, "_populate_approved_from_annual_total_batch"):
                        line.line_ids._populate_approved_from_annual_total_batch()
                        line.line_ids.with_context(**ctx).write({"is_cascaded": True})
                    else:
                        for pl_line in line.line_ids:
                            vals = {
                                "approved_opening_balance": getattr(pl_line, "opening_balance", 0.0) or 0.0,
                                "approved_annual_total": getattr(pl_line, "annual_total", 0.0) or 0.0,
                                "is_cascaded": True,
                            }
                            for i in range(1, 13):
                                vals[f"approved_m{i:02d}"] = getattr(pl_line, f"m{i:02d}", 0.0) or 0.0
                            if pl_line.line_type == "fixed_asset":
                                vals["approved_quantity"] = pl_line.quantity or 0
                                vals["fa_approved_total_cost"] = pl_line.fa_annual_total_cost or 0.0
                                vals["approved_annual_total"] = pl_line.fa_annual_total_cost or 0.0
                            pl_line.with_context(**ctx).write(vals)
                else:
                    # General expense lines populate approved targets on final approval
                    ge_lines = line.line_ids.filtered(lambda l: l.line_type == "general_expense" or getattr(line, "category", False) == "general_expense")
                    for pl_line in ge_lines:
                        appr_total = getattr(pl_line, "approved_annual_total", 0.0) or getattr(pl_line, "annual_total", 0.0) or 0.0
                        vals = {
                            "approved_opening_balance": getattr(pl_line, "approved_opening_balance", 0.0) or getattr(pl_line, "opening_balance", 0.0) or 0.0,
                            "approved_annual_total": appr_total,
                        }
                        for i in range(1, 13):
                            vals[f"approved_m{i:02d}"] = getattr(pl_line, f"approved_m{i:02d}", 0.0) or getattr(pl_line, f"m{i:02d}", 0.0) or 0.0
                        pl_line.with_context(**ctx).write(vals)

                    # For mobilization categories: non-cascaded lines must strictly remain 0.0!
                    uncascaded_lines = line.line_ids.filtered(lambda l: not l.is_cascaded and l.line_type != "general_expense")
                    if uncascaded_lines:
                        zero_vals = {
                            "approved_opening_balance": 0.0,
                            "approved_annual_total": 0.0,
                            **{f"approved_m{i:02d}": 0.0 for i in range(1, 13)},
                        }
                        fa_uncascaded = uncascaded_lines.filtered(lambda l: l.line_type == "fixed_asset")
                        other_uncascaded = uncascaded_lines - fa_uncascaded
                        if other_uncascaded:
                            other_uncascaded.with_context(**ctx).write(zero_vals)
                        if fa_uncascaded:
                            fa_vals = dict(zero_vals)
                            fa_vals["approved_quantity"] = 0
                            fa_vals["fa_approved_total_cost"] = 0.0
                            fa_uncascaded.with_context(**ctx).write(fa_vals)

                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()

            line._log_audit_action("approve", old_state, "approved", _("Final approval granted."))
            line._notify_approved(_("Annual Business Plan"), is_final=True)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved Successfully'),
                'message': _('Plan has been approved successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_reject(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot reject this plan at its current workflow stage."))
            reason = comment or line.return_reason
            if not reason:
                raise UserError(_("Please provide a reason for rejecting the plan."))
            cleaned_reason = str(reason).strip().replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")
            if cleaned_reason and cleaned_reason.isdigit():
                raise ValidationError(_("Rejection reason cannot be purely numeric digits. Please provide a descriptive reason."))
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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejected Successfully'),
                'message': _('Plan has been rejected.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_return(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot return this plan at its current workflow stage."))
            reason = comment or line.return_reason
            if not reason:
                raise UserError(_("Please provide a reason before returning a plan."))
            cleaned_reason = str(reason).strip().replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")
            if cleaned_reason and cleaned_reason.isdigit():
                raise ValidationError(_("Return reason cannot be purely numeric digits. Please provide a descriptive reason."))
            if line.state not in ("submitted", "district_approved", "district_endorsed", "ho_reviewed", "info_requested", "rejection_recommended", "chief_review", "people_solutions_review", "cpco_review", "board_ceo_approval", "committee_review", "hr_fulfillment", "ceo_approval", "ho_endorse", "cpco_endorse"):
                continue
            
            old_state = line.state
            return_info = line._get_return_target_info(old_state)
            target_state = return_info["target_state"]

            line.write({"state": target_state, "return_reason": reason})
            line._log_audit_action("return", old_state, target_state, reason)
            line._notify_returned(reason, is_info_request=False, return_info=return_info)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Returned Successfully'),
                'message': _('Plan has been returned for revision.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_request_info(self, comment=False):
        all_plans = self._get_workflow_sibling_plans()
        for line in all_plans:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot request information on this plan at its current workflow stage."))
            if not comment:
                raise UserError(_("Please enter the specific information or details requested."))
            cleaned_comment = str(comment).strip().replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")
            if cleaned_comment and cleaned_comment.isdigit():
                raise ValidationError(_("Information request cannot be purely numeric digits. Please provide specific descriptive details."))
            old_state = line.state
            return_info = line._get_return_target_info(old_state)
            target_state = "info_requested"

            line.write({"state": target_state})
            line._log_audit_action("request_info", old_state, target_state, comment)
            line._notify_returned(comment, is_info_request=True, return_info=return_info)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Information Requested Successfully'),
                'message': _('Information request has been submitted.'),
                'type': 'info',
                'sticky': False,
            }
        }

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

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Rejection Recommended'),
                'message': _('Recommendation for rejection recorded.'),
                'type': 'warning',
                'sticky': False,
            }
        }


    def action_add_review_comment(self, comment=False):
        for line in self:
            if not line._pbms_can_use_reviewer_wizards():
                raise AccessError(_("You cannot add review comments on this plan at its current workflow stage."))
            if not comment:
                raise UserError(_("Please enter your review comment."))
            stage_vals = {}
            if self.env.user._pbms_is_people_solutions():
                stage_vals["people_solutions_comment"] = comment
            elif line.state in ("cpco_review", "hr_fulfillment", "cpco_endorse") or self.env.user._pbms_is_cpco():
                stage_vals["cpco_comment"] = comment
            elif line.state == "committee_review" or self.env.user._pbms_is_budget_hiring_committee():
                stage_vals["committee_comment"] = comment
            elif line.state in ("ceo_approval", "board_ceo_approval") or self.env.user._pbms_is_ceo():
                stage_vals["ceo_comment"] = comment
            elif line.state == "chief_review" or self.env.user._pbms_is_respective_chief():
                stage_vals["chief_comment"] = comment
            elif line.state == "submitted" and line._pbms_can_district_review_plan():
                stage_vals["district_comment"] = comment
            else:
                stage_vals["ho_comment"] = comment
            if stage_vals:
                line.with_context(bypass_plan_lock=True, in_review_comment_sync=True).write(stage_vals)
            line._log_audit_action("review_comment", line.state, line.state, comment)
            line.message_post(body=Markup(f"<b>Reviewer Comment:</b><br/>{comment or ''}"))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Review Comment Recorded'),
                'message': _('Review comment added successfully.'),
                'type': 'info',
                'sticky': False,
            }
        }

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
                cats_to_run = [rec.category] if rec.category in ("deposit", "customer_base", "fx", "digital_banking") else ["deposit", "customer_base", "fx", "digital_banking"]
                for cat in cats_to_run:
                    rec.with_context(category=cat, target_category=cat)._consolidate_district_plan_data(rec.cycle_id, district)
        
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
                if ho_plan.state in ("draft", "returned", "info_requested"):
                    ho_plan.with_context(bypass_plan_lock=True).write({
                        "state": "district_endorsed",
                        "active": True,
                    })
                elif not ho_plan.active:
                    ho_plan.with_context(bypass_plan_lock=True).write({"active": True})
                if hasattr(ho_plan, "_sync_category_records"):
                    ho_plan.with_context(bypass_plan_lock=True)._sync_category_records()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bank Consolidation Complete'),
                'message': _('Bank-wide Head Office overview plan updated from endorsed district plans.'),
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
            or (hasattr(self.env.user, "_pbms_is_sppmd_admin") and self.env.user._pbms_is_sppmd_admin())
        )
        all_plans = self
        for p in self:
            if hasattr(p, "org_unit_id") and hasattr(p, "cycle_id") and p.org_unit_id and p.cycle_id:
                domain = [
                    ("org_unit_id", "=", p.org_unit_id.id),
                    ("cycle_id", "=", p.cycle_id.id),
                    ("is_consolidated_district_plan", "=", bool(p.is_consolidated_district_plan)),
                    ("is_consolidated_ho_plan", "=", bool(p.is_consolidated_ho_plan)),
                    ("state", "in", ("submitted", "chief_review", "district_endorsed", "district_approved", "returned", "info_requested")),
                    ("active", "=", True),
                ]
                siblings = self.env[p._name].search(domain)
                all_plans |= siblings

        for line in all_plans:
            # 1. Once approved, only SPPMD Manager / Administrator can reset to draft
            if line.state in ("approved", "closed") and not is_admin:
                raise UserError(_(
                    "Locked Official Plan: You cannot reset a plan that has already been approved by the final approver. Only an SPPMD Administrator can reset an approved plan."
                ))

            # 2. Check if can_reset_to_draft
            if not is_admin:
                if hasattr(line, "can_reset_to_draft") and not line.can_reset_to_draft:
                    raise UserError(_(
                        "Plan Reset Locked: You cannot reset this plan to draft because the next reviewer has already taken action on it, or you do not have permission to reset this plan."
                    ))
                if not (line._is_own_operating_unit_plan() or line._pbms_can_district_review_plan() or line._pbms_can_ho_review_plan() or self.env.user.has_group("bunna_pbms.group_pbms_respective_chief") or (line.submitted_by and line.submitted_by.id == self.env.uid)):
                    raise AccessError(_("You can only reset plans for your own work unit or work units under your review."))
                if line.state not in ("submitted", "returned", "info_requested", "chief_review", "district_approved", "district_endorsed", "ho_reviewed", "committee_review"):
                    raise UserError(_("You can only reset plans that are pending review or returned for revision."))

        old_states = {p.id: p.state for p in all_plans}
        all_plans.sudo().with_context(bypass_plan_lock=True, skip_sync_category_records=True, skip_split_mixed_lines=True).write({
            "state": "draft",
            "return_reason": False,
        })

        for line in all_plans:
            line._log_audit_action("reset_draft", old_states.get(line.id, "submitted"), "draft", _("Plan reset to draft for further editing."))
            if hasattr(line, "_compute_totals"):
                line._compute_totals()
            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()
            if hasattr(line, "_compute_kanban_breakdown_html"):
                line._compute_kanban_breakdown_html()
            if hasattr(line, "_compute_plan_notification_details"):
                line._compute_plan_notification_details()
            if hasattr(line, "category") and line.category == "manpower" and hasattr(line, "_sync_existing_manpower_lines"):
                line._sync_existing_manpower_lines()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reset to Draft Successfully'),
                'message': _('Plan has been reset to draft successfully.'),
                'type': 'info',
                'sticky': False,
            }
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

