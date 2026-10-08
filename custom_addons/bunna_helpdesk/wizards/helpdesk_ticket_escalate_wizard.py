# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskTicketEscalateWizard(models.TransientModel):
    _name = "helpdesk.ticket.escalate.wizard"
    _description = "Escalate Ticket to 2nd / 3rd Level Work Unit"

    ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Ticket",
        required=True,
    )
    escalation_target_level = fields.Selection(
        selection=[
            ("level_2", "2nd Level: Head Office Work Unit / Directorate"),
            ("level_3", "3rd Level: Executive Authority / External Vendor Support"),
        ],
        string="Escalation Target Level",
        default="level_2",
        required=True,
    )
    target_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Target Escalation Team",
        required=True,
        help="Select the 2nd level work unit or 3rd level executive/vendor team responsible for this case.",
    )
    target_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assign to Specialist",
        domain="[('share', '=', False)]",
        help="Optional specialist or executive user to assign within the target team.",
    )
    reason = fields.Text(
        string="Escalation Reason & Findings",
        required=True,
        help="Explain why this case requires higher-level intervention and summary of findings.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id")
        target_lvl = self.env.context.get("default_escalation_target_level") or "level_2"
        res["escalation_target_level"] = target_lvl

        if active_id and not res.get("ticket_id"):
            ticket = self.env["helpdesk.ticket"].browse(active_id)
            res["ticket_id"] = ticket.id

            # Pre-fill designated team from Service Catalogue or OLA if level 2
            if target_lvl == "level_2":
                target_team = False
                if ticket.service_id and ticket.service_id.responsible_team_id:
                    target_team = ticket.service_id.responsible_team_id
                elif ticket.operation_id and ticket.operation_id.service_id and ticket.operation_id.service_id.responsible_team_id:
                    target_team = ticket.operation_id.service_id.responsible_team_id

                if target_team and target_team != ticket.team_id:
                    res["target_team_id"] = target_team.id

        return res

    def action_escalate(self):
        self.ensure_one()
        if self.escalation_target_level == "level_3":
            self.ticket_id.action_escalate_to_level_3(
                target_team_id=self.target_team_id,
                target_user_id=self.target_user_id,
                reason=self.reason,
            )
        else:
            self.ticket_id.action_escalate_to_level_2(
                target_team_id=self.target_team_id,
                target_user_id=self.target_user_id,
                reason=self.reason,
            )
        return {"type": "ir.actions.act_window_close"}
