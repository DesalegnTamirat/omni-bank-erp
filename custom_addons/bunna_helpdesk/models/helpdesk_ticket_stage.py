from odoo import api, fields, models


class HelpdeskTicketStage(models.Model):
    _name = "helpdesk.ticket.stage"
    _description = "Helpdesk Ticket Stage"
    _order = "sequence, id"

    name = fields.Char(string="Stage Name", required=True, translate=True)
    description = fields.Html(translate=True, sanitize_style=True)
    sequence = fields.Integer(default=1)
    active = fields.Boolean(default=True)
    unattended = fields.Boolean()
    closed = fields.Boolean()
    close_from_portal = fields.Boolean(
        help="Display button in portal ticket form to allow closing ticket "
        "with this stage as target."
    )
    mail_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Email Template",
        domain=[("model", "=", "helpdesk.ticket")],
        help="If set an email will be sent to the "
        "customer when the ticket"
        "reaches this step.",
    )
    fold = fields.Boolean(
        string="Folded in Kanban",
        help="This stage is folded in the kanban view "
        "when there are no records in that stage "
        "to display.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    team_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.team",
        string="Helpdesk Teams",
        help="Specific Operating Unit teams that use this stage. If empty, all teams can use this stage.",
    )
    enable_sms = fields.Boolean(
        string="Customer Notification Active",
        default=False,
        help="Button ON/OFF: Enable automatic SMS or Email notification to the customer when a ticket enters this stage.",
    )
    notification_channel = fields.Selection(
        selection=[
            ("sms", "SMS"),
            ("email", "Email"),
        ],
        string="Notification Channel",
        default="sms",
        help="Drop-down SMS and email: Select whether to dispatch notification via SMS or Email.",
    )
    sms_template_type = fields.Selection(
        selection=[
            ("escalated", "Escalated Stage (Registered & In Progress)"),
            ("resolved", "Resolved Stage (Successfully Resolved)"),
        ],
        string="Notification Template Type",
        help="Select which notification message template to send when tickets reach this stage.",
    )

    @api.onchange("closed")
    def _onchange_closed(self):
        if not self.closed:
            self.close_from_portal = False
