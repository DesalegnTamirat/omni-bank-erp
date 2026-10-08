from odoo import api, fields, models


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    timesheet_ids = fields.One2many(
        comodel_name="account.analytic.line",
        inverse_name="helpdesk_ticket_id",
        string="Timesheets",
    )
    total_hours_spent = fields.Float(
        string="Hours Spent",
        compute="_compute_total_hours_spent",
        store=True,
    )

    @api.depends("timesheet_ids.unit_amount")
    def _compute_total_hours_spent(self):
        for ticket in self:
            ticket.total_hours_spent = sum(
                ticket.sudo().timesheet_ids.mapped("unit_amount")
            )
