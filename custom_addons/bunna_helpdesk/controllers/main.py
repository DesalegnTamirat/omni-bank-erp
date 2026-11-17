import base64
import logging

import werkzeug

import odoo.http as http
from odoo.http import request
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)


class HelpdeskTicketController(http.Controller):
    @http.route("/ticket/close", type="http", auth="user")
    def support_ticket_close(self, **kw):
        """Close the support ticket"""
        values = {}
        for field_name, field_value in kw.items():
            if field_name.endswith("_id"):
                values[field_name] = int(field_value)
            else:
                values[field_name] = field_value
        ticket = (
            http.request.env["helpdesk.ticket"]
            .sudo()
            .search([("id", "=", values["ticket_id"])])
        )
        stage = http.request.env["helpdesk.ticket.stage"].browse(values.get("stage_id"))
        if stage.close_from_portal:  # protect against invalid target stage request
            ticket.stage_id = values.get("stage_id")

        return werkzeug.utils.redirect("/my/ticket/" + str(ticket.id))

    def _get_teams(self):
        return (
            http.request.env["helpdesk.ticket.team"]
            .with_company(request.env.company.id)
            .search([("active", "=", True), ("show_in_portal", "=", True)])
            if http.request.env.user.company_id.helpdesk_mgmt_portal_select_team
            else False
        )

    def _get_categories(self, **kw):
        company = request.env.company
        category_model = http.request.env["helpdesk.ticket.category"]
        domain = [("active", "=", True), ("show_in_portal", "=", True)]
        return (
            category_model.with_company(company.id).search(domain)
            if http.request.env.user.company_id.helpdesk_mgmt_portal_select_category
            else category_model
        )

    @http.route("/new/ticket", type="http", auth="user", website=True)
    def create_new_ticket(self, **kw):
        values = self._get_create_new_ticket_values(**kw)
        return http.request.render("bunna_helpdesk.portal_create_ticket", values)

    def _get_create_new_ticket_values(self, **kw):
        session_info = http.request.env["ir.http"].session_info()
        company = request.env.company
        email = http.request.env.user.email
        name = http.request.env.user.name
        company = request.env.company
        return {
            "categories": self._get_categories(**kw),
            "teams": self._get_teams(),
            "email": email,
            "name": name,
            "ticket_team_id_required": (company.helpdesk_mgmt_portal_team_id_required),
            "ticket_category_id_required": (
                company.helpdesk_mgmt_portal_category_id_required
            ),
            "max_upload_size": session_info["max_file_upload_size"],
        }

    def _prepare_submit_ticket_vals(self, **kw):
        category = http.request.env["helpdesk.ticket.category"].browse(
            int(kw.get("category") or 0)
        )
        company = category.company_id or http.request.env.company
        vals = {
            "company_id": company.id,
            "category_id": category.id,
            "description": plaintext2html(kw.get("description")),
            "name": kw.get("subject"),
            "attachment_ids": False,
            "channel_id": request.env.ref(
                "bunna_helpdesk.helpdesk_ticket_channel_web", False
            ).id,
            "partner_id": request.env.user.partner_id.id,
            "partner_name": request.env.user.partner_id.name,
            "partner_email": request.env.user.partner_id.email,
            "user_id": False,
        }
        team = http.request.env["helpdesk.ticket.team"]
        if company.helpdesk_mgmt_portal_select_team and kw.get("team"):
            team = (
                http.request.env["helpdesk.ticket.team"]
                .sudo()
                .search(
                    [("id", "=", int(kw.get("team"))), ("show_in_portal", "=", True)]
                )
            )
            vals["team_id"] = team.id
        # Need to set stage_id so that the _track_template() method is called
        # and the mail is sent automatically if applicable
        vals["stage_id"] = team._get_applicable_stages()[:1].id
        return vals

    @http.route("/submitted/ticket", type="http", auth="user", website=True, csrf=True)
    def submit_ticket(self, **kw):
        vals = self._prepare_submit_ticket_vals(**kw)
        new_ticket = request.env["helpdesk.ticket"].sudo().create(vals)
        new_ticket.message_subscribe(partner_ids=request.env.user.partner_id.ids)
        if kw.get("attachment"):
            for c_file in request.httprequest.files.getlist("attachment"):
                data = c_file.read()
                if c_file.filename:
                    request.env["ir.attachment"].sudo().create(
                        {
                            "name": c_file.filename,
                            "datas": base64.b64encode(data),
                            "res_model": "helpdesk.ticket",
                            "res_id": new_ticket.id,
                        }
                    )
        return werkzeug.utils.redirect(f"/my/ticket/{new_ticket.id}")



from odoo.tools.translate import _
from odoo.tools.misc import get_lang
from odoo.addons.rating.controllers.main import Rating


class BunnaRatingController(Rating):
    """Extend core Odoo rating controller to support full 1-5 CSAT scale for Bunna Helpdesk."""

    @http.route('/rate/<string:token>/<int:rate>', type='http', auth="public", website=True)
    def action_open_rating(self, token, rate, **kwargs):
        if rate in (1, 2, 3, 4, 5):
            rating, record_sudo = self._get_rating_and_record(token)
            if not request.env.user._is_public() and \
                    request.env.user.partner_id.commercial_partner_id != rating.partner_id.commercial_partner_id:
                return request.render('rating.rating_external_page_invalid_partner', {
                    'model_name': request.env['ir.model']._get(rating.res_model).display_name,
                    'name': record_sudo.display_name,
                    'web_base_url': rating.get_base_url(),
                })
            lang = rating.partner_id.lang or get_lang(request.env).code
            # Map 4 to 5 and 2 to 1 for the 3 SVG icons (1, 3, 5) supported by core template
            display_rate = 5 if rate in (4, 5) else (1 if rate in (1, 2) else 3)
            return request.env['ir.ui.view'].with_context(lang=lang)._render_template('rating.rating_external_page_submit', {
                'rating': rating,
                'token': token,
                'rate_names': {
                    5: _("Happy / Satisfied"),
                    3: _("Neutral / Fair"),
                    1: _("Unhappy / Poor"),
                },
                'rate': display_rate,
            })
        return super().action_open_rating(token, rate, **kwargs)

    @http.route(['/rate/<string:token>/submit_feedback'], type="http", auth="public", methods=['post', 'get'], website=True, csrf=False)
    def action_submit_rating(self, token, rate=0, **kwargs):
        rating, record_sudo = self._get_rating_and_record(token)
        if request.httprequest.method == "POST":
            try:
                rate_val = float(rate)
            except (ValueError, TypeError):
                rate_val = 5.0
            if rate_val < 1.0 or rate_val > 5.0:
                rate_val = max(1.0, min(5.0, rate_val))
            record_sudo.rating_apply(
                rate_val,
                rating=rating,
                feedback=kwargs.get('feedback'),
                subtype_xmlid=None,
            )
        lang = rating.partner_id.lang or get_lang(request.env).code
        return request.env['ir.ui.view'].with_context(lang=lang)._render_template('rating.rating_external_page_view', {
            'web_base_url': rating.get_base_url(),
            'rating': rating,
        })
