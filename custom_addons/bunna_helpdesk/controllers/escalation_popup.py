# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class HelpdeskEscalationPopupController(http.Controller):

    @http.route("/bunna_helpdesk/get_pending_escalations", type="json", auth="user")
    def get_pending_escalations(self):
        """Fetch unacknowledged escalation pop-up notifications for current logged-in user."""
        user = request.env.user
        popups = request.env["helpdesk.ticket.escalation.popup"].sudo().search([
            ("user_id", "=", user.id),
            ("is_acknowledged", "=", False),
        ], order="escalation_date desc", limit=5)

        data = []
        for p in popups:
            ticket = p.ticket_id
            if not ticket or not ticket.exists():
                p.unlink()
                continue
            data.append({
                "id": p.id,
                "ticket_id": ticket.id,
                "ticket_number": p.ticket_number or ticket.name,
                "ticket_name": p.ticket_name or "",
                "customer_name": p.customer_name or "N/A",
                "customer_phone": p.customer_phone or "N/A",
                "customer_account": p.customer_account or "",
                "issue_description": (p.issue_description or "")[:150],
                "escalation_level_name": p.escalation_level_name or "Escalation",
                "escalated_by_name": p.escalated_by_id.name if p.escalated_by_id else "System",
                "escalation_date": p.escalation_date.strftime("%Y-%m-%d %H:%M:%S") if p.escalation_date else "",
                "operating_unit_name": p.operating_unit_id.name if p.operating_unit_id else "",
            })
        return data

    @http.route("/bunna_helpdesk/acknowledge_escalation", type="json", auth="user")
    def acknowledge_escalation(self, popup_id=None):
        """Mark escalation pop-up as acknowledged."""
        if popup_id:
            popup = request.env["helpdesk.ticket.escalation.popup"].sudo().browse(popup_id)
            if popup.exists():
                popup.action_acknowledge()
        return {"status": "ok"}
