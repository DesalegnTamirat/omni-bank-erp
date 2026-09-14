# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError


class PbmsExceptionalWorkforceWizard(models.TransientModel):
    """Wizard for reviewing authorities to return for revision or reject exceptional workforce requests with mandatory feedback."""
    _name = "pbms.exceptional.workforce.wizard"
    _description = "Exceptional Workforce Action Wizard"

    request_id = fields.Many2one(
        "pbms.exceptional.workforce.request",
        string="Exceptional Request",
        required=True,
        default=lambda self: self.env.context.get("active_id") or self.env.context.get("default_request_id"),
    )
    action_type = fields.Selection(
        [
            ("return", "Return for Revision"),
            ("reject", "Reject Request"),
        ],
        string="Action",
        required=True,
        default=lambda self: self.env.context.get("default_action_type", "return"),
    )
    reason = fields.Text(
        string="Reason / Feedback",
        required=True,
        help="Enter specific justification, revision instructions, or rejection reason.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id") or self.env.context.get("default_request_id")
        if active_id and "request_id" in fields_list and not res.get("request_id"):
            res["request_id"] = active_id
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_("Please provide a reason before proceeding."))

        req = self.request_id
        if not req:
            raise UserError(_("No exceptional workforce request found."))

        reason = self.reason.strip()

        if self.action_type == "return":
            if req.state == "people_solutions":
                req.action_people_solutions_return(reason)
            elif req.state == "cpco_review":
                req.action_cpco_return(reason)
            else:
                req.action_return(reason)
        elif self.action_type == "reject":
            if req.state == "people_solutions":
                req.action_people_solutions_reject(reason)
            elif req.state == "cpco_review":
                req.action_cpco_reject(reason)
            elif req.state == "ceo_review":
                req.action_ceo_reject(reason)
            else:
                req.action_reject(reason)

        return {"type": "ir.actions.act_window_close"}
