from odoo import api, fields, models
from odoo.exceptions import UserError


class HelpdeskTicketConvertWizard(models.TransientModel):
    _name = "helpdesk.ticket.convert.wizard"
    _description = "Convert Helpdesk Ticket"

    ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Source Ticket",
        required=True,
    )
    action_type = fields.Selection(
        selection=[
            ("crm_lead", "CRM Lead / Opportunity"),
            ("repair_order", "Repair Order"),
            ("coupon", "Discount Coupon"),
        ],
        string="Convert To",
        required=True,
        default="crm_lead",
    )
    # CRM fields
    crm_name = fields.Char(string="Lead Name")
    crm_partner_id = fields.Many2one(comodel_name="res.partner", string="Customer")
    crm_description = fields.Text(string="Notes")

    # Repair fields
    repair_name = fields.Char(string="Description")
    repair_partner_id = fields.Many2one(comodel_name="res.partner", string="Customer")
    repair_product_name = fields.Char(string="Product / Item to Repair")

    # Coupon / loyalty fields
    coupon_program_name = fields.Char(
        string="Coupon Program",
        help="Optional coupon program name to match. If omitted, defaults to first available coupon program.",
    )
    coupon_partner_id = fields.Many2one(comodel_name="res.partner", string="Customer")

    @api.model
    def default_get(self, flds):
        defaults = super().default_get(flds)
        ticket_id = self.env.context.get("default_ticket_id")
        if ticket_id:
            ticket = self.env["helpdesk.ticket"].browse(ticket_id)
            defaults["ticket_id"] = ticket.id
            defaults["crm_name"] = ticket.name
            defaults["crm_partner_id"] = ticket.partner_id.id
            defaults["crm_description"] = ticket.description
            defaults["repair_name"] = ticket.name
            defaults["repair_partner_id"] = ticket.partner_id.id
            defaults["coupon_partner_id"] = ticket.partner_id.id
        return defaults

    def action_convert(self):
        self.ensure_one()
        ticket = self.ticket_id

        if self.action_type == "crm_lead":
            if "crm.lead" not in self.env:
                raise UserError(self.env._("The CRM module is not installed."))
            lead = self.env["crm.lead"].create({
                "name": self.crm_name or ticket.name,
                "partner_id": self.crm_partner_id.id if self.crm_partner_id else False,
                "description": self.crm_description or ticket.description,
                "user_id": ticket.user_id.id if ticket.user_id else False,
                "team_id": False,
            })
            ticket.message_post(
                body=self.env._("Ticket converted to CRM Lead: %s") % lead.name
            )
            return {
                "type": "ir.actions.act_window",
                "res_model": "crm.lead",
                "res_id": lead.id,
                "view_mode": "form",
                "target": "current",
            }

        if self.action_type == "repair_order":
            if "repair.order" not in self.env:
                raise UserError(self.env._("The Repair module is not installed."))
            repair_vals = {
                "name": self.repair_name or ticket.name,
                "partner_id": self.repair_partner_id.id if self.repair_partner_id else False,
                "user_id": ticket.user_id.id if ticket.user_id else False,
            }
            if self.repair_product_name and "product.product" in self.env:
                prod = self.env["product.product"].search(
                    [("name", "ilike", self.repair_product_name)], limit=1
                )
                if prod:
                    repair_vals["product_id"] = prod.id
            repair = self.env["repair.order"].create(repair_vals)
            ticket.message_post(
                body=self.env._("Ticket converted to Repair Order: %s") % repair.name
            )
            return {
                "type": "ir.actions.act_window",
                "res_model": "repair.order",
                "res_id": repair.id,
                "view_mode": "form",
                "target": "current",
            }

        if self.action_type == "coupon":
            if "loyalty.card" not in self.env:
                raise UserError(self.env._("The Loyalty module is not installed."))
            program = False
            if "loyalty.program" in self.env:
                if self.coupon_program_name:
                    program = self.env["loyalty.program"].search(
                        [("name", "ilike", self.coupon_program_name)], limit=1
                    )
                if not program:
                    program = self.env["loyalty.program"].search(
                        [("program_type", "=", "coupon")], limit=1
                    )
            if not program:
                raise UserError(self.env._("No active coupon program found."))
            coupon = self.env["loyalty.card"].create({
                "program_id": program.id,
                "partner_id": self.coupon_partner_id.id if self.coupon_partner_id else False,
            })
            ticket.message_post(
                body=self.env._("Coupon %s generated for customer.") % coupon.code
            )
            return {
                "type": "ir.actions.act_window",
                "res_model": "loyalty.card",
                "res_id": coupon.id,
                "view_mode": "form",
                "target": "current",
            }

        raise UserError(self.env._("Unknown conversion type."))
