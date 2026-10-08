from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    helpdesk_ticket_ids = fields.One2many(
        comodel_name="helpdesk.ticket",
        inverse_name="partner_id",
        string="Related tickets",
    )

    helpdesk_ticket_count = fields.Integer(
        compute="_compute_helpdesk_ticket_count", string="Ticket count"
    )

    helpdesk_ticket_active_count = fields.Integer(
        compute="_compute_helpdesk_ticket_count", string="Ticket active count"
    )

    helpdesk_ticket_count_string = fields.Char(
        compute="_compute_helpdesk_ticket_count", string="Tickets"
    )
    account_number = fields.Char(string="Bank Account Number", index=True)
    cif_number = fields.Char(string="CIF Number", index=True)
    fayda_number = fields.Char(string="Fayda / National ID", index=True)
    account_type = fields.Char(string="Account Type / Product", default="Savings Account")
    account_status = fields.Selection(
        selection=[
            ("active", "Active"),
            ("dormant", "Dormant"),
            ("frozen", "Frozen / Inactive"),
            ("closed", "Closed"),
        ],
        string="Account Status",
        default="active",
    )
    customer_segment = fields.Selection(
        selection=[
            ("retail", "Retail Banking"),
            ("sme", "SME / Commercial"),
            ("corporate", "Corporate"),
            ("vip", "VIP / High Net Worth"),
            ("youth", "Youth / Student"),
            ("staff", "Bunna Bank Staff"),
        ],
        string="Customer Segment",
        default="retail",
    )
    preferred_language = fields.Selection(
        selection=[
            ("amharic", "Amharic"),
            ("english", "English"),
            ("afan_oromo", "Afan Oromo"),
            ("tigrigna", "Tigrigna"),
            ("somali", "Somali"),
        ],
        string="Preferred Language",
        default="amharic",
    )
    branch_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Account Branch",
    )
    branch_name = fields.Char(string="Branch Name")
    district_name = fields.Char(string="District Name")
    age = fields.Integer(string="Age")
    customer_type = fields.Char(string="Customer Type")

    def _compute_helpdesk_ticket_count(self):
        for record in self:
            ticket_ids = self.env["helpdesk.ticket"].search(
                [("partner_id", "child_of", record.id)]
            )
            record.helpdesk_ticket_count = len(ticket_ids)
            record.helpdesk_ticket_active_count = len(
                ticket_ids.filtered(lambda ticket: not ticket.stage_id.closed)
            )
            count_active = record.helpdesk_ticket_active_count
            count = record.helpdesk_ticket_count
            record.helpdesk_ticket_count_string = f"{count_active} / {count}"

    def action_view_helpdesk_tickets(self):
        return {
            "name": self.name,
            "view_mode": "list,form",
            "res_model": "helpdesk.ticket",
            "type": "ir.actions.act_window",
            "domain": [("partner_id", "child_of", self.id)],
            "context": self.env.context,
        }
