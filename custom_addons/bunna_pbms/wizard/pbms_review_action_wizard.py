# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PbmsReviewActionWizard(models.TransientModel):
    """Wizard for Reviewers to perform workflow actions and record permanent comments."""
    _name = "pbms.review.action.wizard"
    _description = "PBMS Review Action Wizard"

    plan_id = fields.Many2one(
        "pbms.planning.category",
        string="Planning Record",
        required=True,
        default=lambda self: self.env.context.get("active_id"),
    )
    action_type = fields.Selection(
        [
            ("review_comment", "Add Review Comment"),
            ("request_info", "Request Additional Information"),
            ("return", "Return for Revision"),
            ("recommend_rejection", "Recommend Rejection"),
            ("reject", "Reject Plan"),
        ],
        string="Action",
        required=True,
        default=lambda self: self.env.context.get("default_action_type", "review_comment"),
    )
    comment = fields.Text(
        string="Comments / Justification",
        required=True,
        help="Enter clear details or justification for this action.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id") or self.env.context.get("default_plan_id")
        if active_id and "plan_id" in fields_list and not res.get("plan_id"):
            res["plan_id"] = active_id
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.comment or not self.comment.strip():
            raise UserError(_("Please enter your comments before proceeding."))

        s = self.comment.strip()
        cleaned = s.replace(".", "").replace(",", "").replace("-", "").replace("+", "").replace(" ", "")
        if cleaned and cleaned.isdigit():
            raise UserError(_("Comments cannot be purely numeric digits. Please enter a meaningful text description."))

        plan = self.plan_id
        if not plan:
            raise UserError(_("No planning record found."))

        if self.action_type == "review_comment":
            plan.action_add_review_comment(self.comment.strip())
        elif self.action_type == "request_info":
            plan.action_request_info(self.comment.strip())
        elif self.action_type == "return":
            plan.action_return(self.comment.strip())
        elif self.action_type == "recommend_rejection":
            plan.action_recommend_rejection(self.comment.strip())
        elif self.action_type == "reject":
            plan.action_reject(self.comment.strip())

        return {"type": "ir.actions.act_window_close"}
