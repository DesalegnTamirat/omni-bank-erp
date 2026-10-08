from odoo import api, fields, models
from odoo.exceptions import UserError


class HelpdeskTicketMergeWizard(models.TransientModel):
    _name = "helpdesk.ticket.merge.wizard"
    _description = "Merge Helpdesk Tickets"

    target_ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Merge Into",
        required=True,
        help="All source tickets will be merged into this ticket.",
    )
    source_ticket_ids = fields.Many2many(
        comodel_name="helpdesk.ticket",
        string="Tickets to Merge",
        help="These tickets will be archived after their content is moved to the target.",
    )
    merge_descriptions = fields.Boolean(
        string="Append Descriptions",
        default=False,
        help="If checked, the HTML descriptions from all source tickets will be appended to the target's description.",
    )

    @api.model
    def default_get(self, flds):
        defaults = super().default_get(flds)
        active_ids = self.env.context.get("active_ids", [])
        target_id = self.env.context.get("default_target_ticket_id")
        source_ids = [t for t in active_ids if t != target_id]
        if "source_ticket_ids" in flds and source_ids:
            defaults["source_ticket_ids"] = [fields.Command.set(source_ids)]
        return defaults

    def action_merge(self):
        self.ensure_one()
        target = self.target_ticket_id
        sources = self.source_ticket_ids.filtered(lambda t: t != target)

        if not sources:
            raise UserError(self.env._("Please select at least one source ticket to merge."))

        for source in sources:
            # 1. Move chatter messages to target
            source.message_ids.sudo().write({
                "res_id": target.id,
                "record_name": target.display_name,
            })
            # 2. Re-link attachments
            self.env["ir.attachment"].sudo().search([
                ("res_model", "=", "helpdesk.ticket"),
                ("res_id", "=", source.id),
            ]).write({"res_id": target.id})
            # 3. Merge tags
            target.tag_ids |= source.tag_ids
            # 4. Optionally append description
            if self.merge_descriptions and source.description:
                separator = "<hr/><p><em>— Merged from %s —</em></p>" % source.display_name
                target.description = (target.description or "") + separator + source.description
            # 5. Mark source as duplicate of target and archive it
            source.write({
                "duplicate_id": target.id,
                "active": False,
            })
            source.message_post(
                body=self.env._("This ticket was merged into %s and archived.") % target.display_name
            )

        target.message_post(
            body=self.env._("Tickets %s were merged into this ticket.") % ", ".join(sources.mapped("display_name"))
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket",
            "res_id": target.id,
            "view_mode": "form",
            "target": "current",
        }
