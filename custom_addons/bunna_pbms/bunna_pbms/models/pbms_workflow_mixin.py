# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
            [("state", "in", ("budget_call", "open"))], limit=1),
    )
    org_unit_id = fields.Many2one(
        "operating.unit", string="Org Unit", required=True, index=True,
        default=lambda self: self.env.user.default_operating_unit_id,
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
            ("returned", "Returned for Revision"),
            ("district_approved", "District Approved"),
            ("district_endorsed", "District Endorsed"),
            ("ho_reviewed", "Head Office Reviewed"),
            ("approved", "Approved"),
        ],
        default="draft", required=True, tracking=True, index=True,
    )

    submitted_by = fields.Many2one("res.users", readonly=True, copy=False)
    submitted_date = fields.Datetime(readonly=True, copy=False)
    district_reviewer_id = fields.Many2one("res.users", readonly=True, copy=False)
    district_review_date = fields.Datetime(readonly=True, copy=False)
    district_comment = fields.Text()
    ho_reviewer_id = fields.Many2one("res.users", readonly=True, copy=False)
    ho_review_date = fields.Datetime(readonly=True, copy=False)
    ho_comment = fields.Text()
    return_reason = fields.Text(copy=False)

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, index=True,
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
            if not line.cycle_id.is_editable():
                raise UserError(_(
                    "Planning cycle '%s' is not open for input.", line.cycle_id.name))

    def _protected_write_fields(self):
        return []

    def write(self, vals):
        protected = self._protected_write_fields()
        if protected and any(f in vals for f in protected):
            protected_states = ("district_approved", "district_endorsed", "ho_reviewed", "approved")
            for line in self:
                if line.state in protected_states and not self.env.user.has_group(
                        "bunna_pbms.group_pbms_manager"):
                    raise UserError(_(
                        "This plan has already been approved/endorsed. "
                        "Ask SPPMD to reopen it before editing values."))
        return super().write(vals)

    def action_submit(self):
        self._check_editable()
        for line in self:
            if line.state not in ("draft", "returned"):
                raise UserError(_("Only draft or returned plans can be submitted."))
        self.write({
            "state": "submitted",
            "submitted_by": self.env.uid,
            "submitted_date": fields.Datetime.now(),
        })
        self._notify_stage(_("submitted for review"))

    def action_district_approve(self):
        for line in self:
            if line.state != "submitted":
                raise UserError(_("Only submitted plans can be approved by District."))
            if line.org_unit_type == "district_office":
                # District's own overview plan gets submitted to Head Office
                line.write({
                    "state": "submitted",
                    "district_reviewer_id": self.env.uid,
                    "district_review_date": fields.Datetime.now(),
                })
                line._notify_stage(_("submitted to Head Office for review"))
            else:
                # Branch plan approved at District level (stops here, does not go to HO)
                line.write({
                    "state": "district_approved",
                    "district_reviewer_id": self.env.uid,
                    "district_review_date": fields.Datetime.now(),
                })
                line._notify_stage(_("approved by District"))

                # AUTOMATIC CONSOLIDATION: Aggregate branch plans into District Overview Plan and submit to HO!
                district = line.district_id or line.org_unit_id
                if district and district.work_unit_type != "district_office":
                    district = line._find_district_ancestor(line.org_unit_id)
                if district and hasattr(line, "_consolidate_district_plan_data"):
                    line._consolidate_district_plan_data(line.cycle_id, district)
                    # Automatically set District Overview plan to submitted state (to Head Office)
                    dist_plans = line.search([
                        ("cycle_id", "=", line.cycle_id.id),
                        ("org_unit_id", "=", district.id),
                        ("state", "in", ("draft", "returned")),
                    ])
                    if dist_plans:
                        dist_plans.write({
                            "state": "submitted",
                            "submitted_by": self.env.uid,
                            "submitted_date": fields.Datetime.now(),
                        })

    def action_district_endorse(self):
        return self.action_district_approve()

    def action_ho_review(self):
        for line in self:
            if line.state not in ("submitted", "district_endorsed"):
                raise UserError(_("Only submitted or endorsed District/HO plans can be head-office reviewed."))
            line.write({
                "state": "ho_reviewed",
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": fields.Datetime.now(),
            })
            line._notify_stage(_("reviewed by Head Office and ready for final approval"))

            # AUTOMATIC CONSOLIDATION: Aggregate reviewed District Overview Plans into Bank-Wide HO Plan!
            if line.org_unit_type == "district_office":
                ho_unit = self.env["operating.unit"].search([("work_unit_type", "=", "head_office")], limit=1)
                if ho_unit and hasattr(line, "_consolidate_ho_plan_data"):
                    line._consolidate_ho_plan_data(line.cycle_id, ho_unit)
                    # Automatically update Bank-Wide HO Plan to ho_reviewed state, ready for final approval
                    ho_plans = line.search([
                        ("cycle_id", "=", line.cycle_id.id),
                        ("org_unit_id", "=", ho_unit.id),
                        ("state", "in", ("draft", "submitted")),
                    ])
                    if ho_plans:
                        ho_plans.write({
                            "state": "ho_reviewed",
                            "ho_reviewer_id": self.env.uid,
                            "ho_review_date": fields.Datetime.now(),
                        })

    def action_approve(self):
        for line in self:
            if line.state != "ho_reviewed":
                raise UserError(_("Only head-office-reviewed plans can be given final approval."))
        self.write({"state": "approved"})
        self._notify_stage(_("approved as part of the official Annual Business Plan"))

    def action_return(self):
        for line in self:
            if not line.return_reason:
                raise UserError(_("Please provide a reason before returning a plan."))
            if line.state not in ("submitted", "district_approved", "district_endorsed", "ho_reviewed"):
                raise UserError(_("This plan is not currently under review."))
        self.write({"state": "returned"})
        self._notify_stage(_("returned for revision"))

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
            
            # Delegate model-specific consolidation if available
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
        """Action for Head Office / SPPMD Reviewers to consolidate all
        District Overview plans into the Head Office Bank-Wide Overview Plan."""
        for rec in self:
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

            if hasattr(rec, "_consolidate_ho_plan_data"):
                rec._consolidate_ho_plan_data(rec.cycle_id, ho_unit)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bank Consolidation Complete'),
                'message': _('Head Office bank-wide plan updated from district overview plans.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_reset_to_draft(self):
        if not self.env.user.has_group("bunna_pbms.group_pbms_manager"):
            raise UserError(_("Only SPPMD administrators can reopen a plan."))
        self.write({"state": "draft"})

    def _notify_stage(self, message):
        for line in self:
            line.message_post(body=_("Plan %s.", message))

    @api.constrains("cycle_id", "org_unit_id")
    def _check_duplicate(self):
        for line in self:
            domain = line._get_duplicate_domain() + [("id", "!=", line.id)]
            if self.search_count(domain) > 0:
                raise ValidationError(_(
                    "A plan for this org unit / cycle / account already exists. "
                    "Edit the existing line instead of creating a duplicate."))
