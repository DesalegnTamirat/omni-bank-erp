# -*- coding: utf-8 -*-
"""Automatic customer SMS + email notifications for ticket Acceptance / Done.

Workflow
--------
stage -> "In Progress" (xmlid helpdesk_ticket_stage_in_progress)  => ACCEPTED
stage -> "Done"        (xmlid helpdesk_ticket_stage_done)         => COMPLETED

Each notification (event x channel) is sent once, tracked by a boolean flag.
A failure never blocks or rolls back the ticket transition.
"""
import logging
import re

from odoo import _, api, fields, models, tools

_logger = logging.getLogger(__name__)

EVENTS = {
    "acceptance": {
        "stage_xmlid": "bunna_helpdesk.helpdesk_ticket_stage_in_progress",
        "stage_name": "In Progress",
        "template_xmlid": "bunna_helpdesk.email_template_service_request_accepted",
        "sms_param": "bunna_helpdesk.bunna_sms_acceptance_template",
        "sms_default": (
            "Dear {first_name}\n"
            "Your Bunna Bank request {number} has been registered and accepted by {team_name}. We are currently processing it. For inquiries, call 8501.\n"
            "Bunna Bank S.C."
        ),
        "label": "Acceptance",
    },
    "completion": {
        "stage_xmlid": "bunna_helpdesk.helpdesk_ticket_stage_done",
        "stage_name": "Resolve",
        "template_xmlid": "bunna_helpdesk.email_template_service_request_completed",
        "sms_param": "bunna_helpdesk.bunna_sms_done_template",
        "sms_default": (
            "Dear {first_name}\n"
            "Your Bunna Bank ticket {number} has been successfully resolved. Thank you for banking with Bunna Bank! Inquiries: 8501.\n"
            "Bunna Bank S.C."
        ),
        "label": "Completion",
    },
}


class HelpdeskTicketNotification(models.Model):
    _inherit = "helpdesk.ticket"

    acceptance_sms_sent = fields.Boolean(copy=False, readonly=True)
    acceptance_email_sent = fields.Boolean(copy=False, readonly=True)
    completion_sms_sent = fields.Boolean(copy=False, readonly=True)
    completion_email_sent = fields.Boolean(copy=False, readonly=True)
    done_notification_date = fields.Datetime(
        string="Done / Notification Sent Date",
        readonly=True,
        copy=False,
        help="Timestamp when the ticket reached Done stage and notification was dispatched.",
    )

    acceptance_channel = fields.Selection(
        [("sms", "SMS"), ("email", "Email")],
        string="Acceptance Notification Channel",
        default="sms",
        help="Select whether to notify the customer via SMS or Email upon ticket acceptance. Once sent, the alternative channel is deactivated.",
    )
    acceptance_sent_channel = fields.Selection(
        [("sms", "SMS"), ("email", "Email")],
        string="Accepted Via Channel",
        readonly=True,
        copy=False,
    )
    done_channel = fields.Selection(
        [("sms", "SMS"), ("email", "Email")],
        string="Done Notification Channel",
        default="sms",
        help="Select whether to notify the customer via SMS or Email upon resolution/done. Once sent, the alternative channel is deactivated.",
    )
    done_sent_channel = fields.Selection(
        [("sms", "SMS"), ("email", "Email")],
        string="Done Via Channel",
        readonly=True,
        copy=False,
    )

    header_action = fields.Selection(
        selection=[
            ("escalated", "Escalated Stage (Register & In Progress)"),
            ("done", "Resolved Stage (Mark as Resolved)"),
        ],
        string="Stage Action",
        default="escalated",
        help="Select case management stage for notification (Escalated or Resolved).",
    )
    header_notify_toggle = fields.Boolean(
        string="Notify Customer",
        default=False,
        help="Button ON/OFF: Toggle customer SMS or Email notification on or off.",
    )
    header_channel = fields.Selection(
        selection=[
            ("sms", "SMS"),
            ("email", "Email"),
        ],
        string="Notification Channel",
        default="sms",
        help="Drop-down SMS and email: Select delivery channel.",
    )

    display_header_notification = fields.Boolean(
        string="Display Header Notification",
        compute="_compute_display_header_notification",
    )

    @api.depends("stage_id", "acceptance_sms_sent", "acceptance_email_sent", "completion_sms_sent", "completion_email_sent")
    def _compute_display_header_notification(self):
        for ticket in self:
            if not ticket.id:
                ticket.display_header_notification = False
                continue
            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""
            is_done_stage = bool(ticket.stage_id and (stage_name in ("done", "resolve", "resolved") or ticket.stage_id.closed))
            if is_done_stage:
                # When ticket status is Resolved / Done, keep header controls visible until the completion notification is actually sent
                ticket.display_header_notification = not (ticket.completion_sms_sent or ticket.completion_email_sent)
            else:
                # In New or In Progress stages, keep header controls visible
                ticket.display_header_notification = not (ticket.acceptance_sms_sent and ticket.completion_sms_sent)

    @api.onchange("stage_id", "acceptance_sms_sent", "acceptance_email_sent")
    def _onchange_stage_header_action(self):
        for ticket in self:
            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""
            if ticket.stage_id and (stage_name in ("done", "resolve", "resolved") or ticket.stage_id.closed):
                ticket.header_action = "done"
            elif ticket.stage_id and stage_name == "in progress":
                ticket.header_action = "done"
            elif ticket.acceptance_sms_sent or ticket.acceptance_email_sent:
                ticket.header_action = "done"
            else:
                ticket.header_action = "escalated"

    acceptance_notification_status = fields.Char(
        string="Acceptance Status",
        compute="_compute_notification_statuses",
    )
    done_notification_status = fields.Char(
        string="Done Status",
        compute="_compute_notification_statuses",
    )
    is_acceptance_sent = fields.Boolean(
        string="Acceptance Fulfilled",
        compute="_compute_notification_statuses",
    )
    is_done_sent = fields.Boolean(
        string="Done Fulfilled",
        compute="_compute_notification_statuses",
    )

    @api.depends(
        "acceptance_sms_sent", "acceptance_email_sent", "acceptance_sent_channel",
        "completion_sms_sent", "completion_email_sent", "done_sent_channel"
    )
    def _compute_notification_statuses(self):
        for ticket in self:
            # Acceptance Status
            if ticket.acceptance_sent_channel == "sms" or (ticket.acceptance_sms_sent and not ticket.acceptance_sent_channel):
                ticket.acceptance_notification_status = _("Accepted via SMS (Email inactive)")
                ticket.is_acceptance_sent = True
            elif ticket.acceptance_sent_channel == "email":
                ticket.acceptance_notification_status = _("Accepted via Email (SMS inactive)")
                ticket.is_acceptance_sent = True
            elif ticket.acceptance_sms_sent or ticket.acceptance_email_sent:
                ticket.acceptance_notification_status = _("Accepted (Alternative inactive)")
                ticket.is_acceptance_sent = True
            else:
                ticket.acceptance_notification_status = _("Pending (Select SMS or Email)")
                ticket.is_acceptance_sent = False

            # Done Status
            if ticket.done_sent_channel == "sms" or (ticket.completion_sms_sent and not ticket.done_sent_channel):
                ticket.done_notification_status = _("Resolved via SMS (Email inactive)")
                ticket.is_done_sent = True
            elif ticket.done_sent_channel == "email":
                ticket.done_notification_status = _("Resolved via Email (SMS inactive)")
                ticket.is_done_sent = True
            elif ticket.completion_sms_sent or ticket.completion_email_sent:
                ticket.done_notification_status = _("Resolved (Alternative inactive)")
                ticket.is_done_sent = True
            else:
                ticket.done_notification_status = _("Pending (Select SMS or Email)")
                ticket.is_done_sent = False

    notification_channel_sent = fields.Char(
        string="Notification Channel Sent",
        compute="_compute_notification_channel_sent",
        store=True,
        help="Captures whether notification was dispatched by SMS or by Email for acceptance and resolution.",
    )

    @api.depends("acceptance_sent_channel", "done_sent_channel", "acceptance_sms_sent", "acceptance_email_sent", "completion_sms_sent", "completion_email_sent")
    def _compute_notification_channel_sent(self):
        for ticket in self:
            parts = []
            if ticket.acceptance_sent_channel:
                parts.append(_("Accepted: %s") % ticket.acceptance_sent_channel.upper())
            elif ticket.acceptance_sms_sent:
                parts.append(_("Accepted: SMS"))
            elif ticket.acceptance_email_sent:
                parts.append(_("Accepted: EMAIL"))

            if ticket.done_sent_channel:
                parts.append(_("Resolved: %s") % ticket.done_sent_channel.upper())
            elif ticket.completion_sms_sent:
                parts.append(_("Resolved: SMS"))
            elif ticket.completion_email_sent:
                parts.append(_("Resolved: EMAIL"))

            ticket.notification_channel_sent = " | ".join(parts) if parts else _("Not Dispatched")

    # ── stage helpers ────────────────────────────────────────────────────────

    def _bunna_get_stage(self, event):
        """Stage that represents ``event`` (xmlid first, name as fallback)."""
        conf = EVENTS[event]
        stage = self.env.ref(conf["stage_xmlid"], raise_if_not_found=False)
        if not stage:
            if event == "completion":
                stage = self.env["helpdesk.ticket.stage"].search(
                    ["|", ("name", "ilike", "resolve"), ("name", "ilike", "resolved")], limit=1
                )
            if not stage:
                stage = self.env["helpdesk.ticket.stage"].search(
                    [("name", "ilike", conf["stage_name"])], limit=1
                )
        return stage

    def _bunna_stage_event(self, stage):
        """Return 'acceptance' / 'completion' / False for a stage record."""
        if not stage:
            return False
        if getattr(stage, "sms_template_type", False):
            if stage.sms_template_type == "escalated":
                return "acceptance"
            elif stage.sms_template_type == "resolved":
                return "completion"
        for event in EVENTS:
            if stage == self._bunna_get_stage(event):
                return event
        stage_name = (stage.name or "").lower()
        if any(w in stage_name for w in ("in progress", "escalat", "escalated")):
            return "acceptance"
        if any(w in stage_name for w in ("resolve", "resolved", "done")):
            return "completion"
        return False

    # ── write hook ───────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("header_action") == "accept":
                vals["header_action"] = "escalated"
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("header_action") == "accept":
            vals["header_action"] = "escalated"
        if "stage_id" not in vals:
            return super().write(vals)
        old_stages = {t.id: t.stage_id for t in self}
        res = super().write(vals)
        for ticket in self:
            old, new = old_stages.get(ticket.id), ticket.stage_id
            if old == new:
                continue  # unrelated update / same stage: nothing to send
            if old and (old.name == "Done" or old.closed) and new and not new.closed and new.name != "Done":
                # re-opened: a later completion is a new completion
                ticket.with_context(mail_notrack=True).sudo().write(
                    {
                        "completion_sms_sent": False,
                        "completion_email_sent": False,
                        "done_sent_channel": False,
                        "done_notification_date": False,
                    }
                )
            elif new and new.name == "Done" and not ticket.done_notification_date:
                ticket.with_context(mail_notrack=True).sudo().write({
                    "done_notification_date": fields.Datetime.now(),
                })
            # Automatic notification if stage has enable_sms configured
            if new and getattr(new, "enable_sms", False) and not self.env.context.get("bunna_skip_notifications"):
                evt = ticket._bunna_stage_event(new)
                if evt:
                    ch = getattr(new, "notification_channel", "sms") or "sms"
                    ticket._bunna_send_notifications(evt, channels=(ch,))
        return res

    def _track_template(self, tracking):
        res = super()._track_template(tracking)
        # Prevent automated mail tracking templates on acceptance/completion stages
        if "stage_id" in res and self and self._bunna_stage_event(self[0].stage_id) in ("acceptance", "completion"):
            res.pop("stage_id", None)
        return res

    # ── SMS ──────────────────────────────────────────────────────────────────

    def _bunna_get_notification_operating_unit_name(self):
        """Resolve the current or escalated operating unit responsible for this ticket."""
        self.ensure_one()
        # 1. Check current operating unit on ticket (Sub Service Provider / Escalated OU)
        if self.operating_unit_id:
            return self.operating_unit_id.name
        # 2. If ticket was escalated and OU not set, check latest escalation history destination OU
        if self.escalation_history_ids:
            latest_history = self.escalation_history_ids.sorted("id", reverse=True)[:1]
            if latest_history.current_operating_unit_id:
                return latest_history.current_operating_unit_id.name
        # 3. Check escalated assignee's operating unit
        if self.escalated_to_user_id and self.escalated_to_user_id.default_operating_unit_id:
            return self.escalated_to_user_id.default_operating_unit_id.name
        # 4. Check team's operating unit if configured
        if self.team_id and hasattr(self.team_id, "operating_unit_id") and self.team_id.operating_unit_id:
            return self.team_id.operating_unit_id.name
        # 5. Fallback to team name or Support Team
        return self.team_id.name or "Bunna Bank Support Team"

    def _bunna_sms_body(self, event):
        self.ensure_one()
        conf = EVENTS[event]
        template = (
            self.env["ir.config_parameter"].sudo().get_param(conf["sms_param"]) or conf["sms_default"]
        )
        full_name = (self.partner_id.name or self.partner_name or _("Customer")).strip()
        first_name = full_name.split()[0] if full_name else _("Customer")

        # Strip any HTML/XML tags or residual angle brackets from title
        clean_name = self.name or ""
        if "<" in clean_name and ">" in clean_name:
            clean_name = tools.html2plaintext(clean_name)
            clean_name = re.sub(r"<[^>]+>", "", clean_name)
        clean_name = " ".join(clean_name.split()).strip()

        # Resolve responsible / escalated operating unit name
        ou_name = self._bunna_get_notification_operating_unit_name()

        values = {
            "reference": self.number or "",
            "number": self.number or "",
            "name": clean_name,
            "partner_name": full_name,
            "first_name": first_name,
            "partner_first_name": first_name,
            "team_name": ou_name,
            "operating_unit_name": ou_name,
            "escalated_operating_unit": ou_name,
            "bank_hotline": "8501",
        }
        # plain placeholder replacement: no attribute access / format-spec tricks
        body = re.sub(
            r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template
        ).strip()
        # Clean up any leftover double spaces
        body = re.sub(r" +", " ", body)
        return body

    def _bunna_sms_phone(self):
        """First usable mobile among: ticket phone, partner phone, partner mobile.

        Returns (raw_number_or_False, normalized_number_or_False). The ticket
        number always wins, but an invalid ticket number no longer blocks a
        valid number stored on the customer record.
        """
        self.ensure_one()
        sms_service = self.env["bunna.sms.service"]
        partner = self.partner_id
        candidates = [
            self.partner_phone,
            partner and partner.phone,
            partner and "mobile" in partner._fields and partner.mobile,
        ]
        first_raw = False
        for raw in candidates:
            if not raw:
                continue
            first_raw = first_raw or raw
            normalized = sms_service.normalize_mobile(raw)
            if normalized:
                return raw, normalized
        return first_raw, False

    def _bunna_do_sms(self, event):
        """Returns dict(success, skipped, detail)."""
        self.ensure_one()
        raw, normalized = self._bunna_sms_phone()
        if not self.partner_id and not raw:
            _logger.warning("Ticket %s: no customer, SMS skipped.", self.number)
            return {"success": False, "skipped": True, "detail": _("No customer on the ticket.")}
        if not raw:
            _logger.warning("Ticket %s: customer has no mobile number, SMS skipped.", self.number)
            return {"success": False, "skipped": True, "detail": _("Customer mobile number is missing.")}
        result = self.env["bunna.sms.service"].send_sms(normalized or raw, self._bunna_sms_body(event))
        if not result["success"] and not result["mobile"]:
            result["skipped"] = True  # invalid number -> skipped, not a gateway failure
        result.setdefault("skipped", False)
        return result

    # ── Email ────────────────────────────────────────────────────────────────

    def _bunna_do_email(self, event):
        """Returns dict(success, skipped, detail). Uses Bunna In-House Notification API Gateway with template fallback."""
        self.ensure_one()
        # ticket email first (same rule as the phone), customer record as fallback
        email = False
        for candidate in (self.partner_email, self.partner_id.email):
            email = tools.email_normalize(candidate or "")
            if email:
                break
        if not email:
            _logger.warning("Ticket %s: customer has no valid email, email skipped.", self.number)
            return {"success": False, "skipped": True, "detail": _("Customer email is missing or invalid.")}
        template = self.env.ref(EVENTS[event]["template_xmlid"], raise_if_not_found=False)
        if not template:
            _logger.error("Email template %s not found.", EVENTS[event]["template_xmlid"])
            return {"success": False, "skipped": False, "detail": _("Email template not found.")}
        _logger.info("Email notification (%s) initiated for ticket %s.", event, self.number)

        recipient_name = self.partner_id.name or self.partner_name or "Customer"
        try:
            subject = template._render_field("subject", [self.id])[self.id]
            body = template._render_field("body_html", [self.id])[self.id]
        except Exception:
            subject = f"Service Request {self.number} Update"
            body = f"<p>Dear {recipient_name}, your request {self.number} has been updated.</p>"

        # 1. Dispatch via Bunna In-House Notification REST API Gateway
        res = self.env["bunna.sms.service"].send_email(
            to_email=email,
            subject=subject,
            body=body,
            recipient_name=recipient_name,
        )
        if res.get("success"):
            return res

        # 2. Fallback to standard Odoo SMTP mail framework if Gateway returned failure
        _logger.info("In-House Email Gateway returned (%s), attempting Odoo mail fallback.", res.get("detail"))
        mail_ref = template.sudo().send_mail(
            self.id,
            force_send=True,
            raise_exception=False,
            email_values={"email_to": email, "recipient_ids": [(5, 0, 0)]},
        )
        mail = self.env["mail.mail"].sudo().browse(getattr(mail_ref, "id", mail_ref)).exists()
        if mail and mail.state == "exception":
            detail = _("Outgoing mail server error: %s") % (mail.failure_reason or "")[:200]
            _logger.error("Email failed for ticket %s: %s", self.number, detail)
            return {"success": False, "skipped": False, "detail": detail}
        _logger.info("Email successfully sent/queued for ticket %s via fallback.", self.number)
        return {"success": True, "skipped": False, "detail": _("Email sent to %s.") % email}

    # ── orchestration ────────────────────────────────────────────────────────

    def _bunna_send_notifications(self, event, channels=("sms", "email")):
        """Send missing notifications of ``event``. Never raises; never resends
        a channel that is already flagged as sent.

        :return: {ticket_id: {channel: result_dict | None}} (None = already sent)
        """
        summary = {}
        label = EVENTS[event]["label"]
        for ticket in self:
            summary[ticket.id] = {}
            lines, flags = [], {}
            for channel in channels:
                flag = f"{event}_{channel}_sent"
                if ticket[flag]:
                    summary[ticket.id][channel] = None
                    continue
                try:
                    with self.env.cr.savepoint():
                        result = (
                            ticket._bunna_do_sms(event) if channel == "sms"
                            else ticket._bunna_do_email(event)
                        )
                except Exception as exc:
                    _logger.exception("%s %s failed for ticket %s", label, channel, ticket.number)
                    result = {"success": False, "skipped": False,
                              "detail": _("Unexpected error (%s).") % exc.__class__.__name__}
                summary[ticket.id][channel] = result
                if result["success"]:
                    flags[flag] = True
                    state = _("sent")
                elif result.get("skipped"):
                    state = _("skipped")
                else:
                    state = _("FAILED")
                lines.append("%s %s: %s - %s" % (
                    label, channel.upper(), state, tools.html_escape(result["detail"] or "")))
            if flags:
                ticket.with_context(mail_notrack=True, bunna_skip_notifications=True).sudo().write(flags)
            if lines:
                _logger.info("Notification dispatch result for ticket %s: %s", ticket.number, " | ".join(lines))
        return summary

    # ── buttons & wizards ───────────────────────────────────────────────────

    def action_open_accept_wizard(self):
        """Open popup modal to choose either SMS or Email for ticket Acceptance."""
        self.ensure_one()
        return {
            "name": _("Accept Ticket (Send SMS or Email)"),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.notify.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ticket_id": self.id,
                "default_notification_type": "acceptance",
            },
        }

    def action_open_done_wizard(self):
        """Open popup modal to choose either SMS or Email for ticket Resolution (Done)."""
        self.ensure_one()
        return {
            "name": _("Resolve Ticket & Mark as Done"),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.notify.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ticket_id": self.id,
                "default_notification_type": "completion",
                "default_resolution_notes": self.agent_action_taken or "",
            },
        }

    def _bunna_manual_notify(self, event, channels=("sms", "email")):
        stage = self._bunna_get_stage(event)
        summary = {}
        for ticket in self:
            # 1. Transition ticket status to the target stage (e.g. Done) before sending notification
            if stage and ticket.stage_id != stage:
                ticket.with_context(bunna_skip_notifications=True).write({"stage_id": stage.id})

            # 2. Check and verify ticket status is in the expected stage before dispatching
            current_event = ticket._bunna_stage_event(ticket.stage_id)
            if current_event != event:
                _logger.warning(
                    "Ticket %s status check: stage '%s' does not match event '%s'. Notification skipped.",
                    ticket.number, ticket.stage_id.name if ticket.stage_id else "None", event
                )
                continue

            # 3. Send notification AFTER ticket status is confirmed in the target stage
            summary.update(ticket._bunna_send_notifications(event, channels=channels))

            # 4. Enforce single channel rule: mark flags and record sent channel
            chosen = channels[0] if channels else "sms"
            if event == "acceptance":
                ticket.with_context(mail_notrack=True, bunna_skip_notifications=True).sudo().write({
                    "acceptance_sms_sent": True,
                    "acceptance_email_sent": True,
                    "acceptance_sent_channel": chosen,
                })
            elif event == "completion":
                ticket.with_context(mail_notrack=True, bunna_skip_notifications=True).sudo().write({
                    "completion_sms_sent": True,
                    "completion_email_sent": True,
                    "done_sent_channel": chosen,
                    "done_notification_date": fields.Datetime.now(),
                })

        failed, sent, already = [], [], []
        for tid, chans in summary.items():
            for channel, res in chans.items():
                if res is None:
                    already.append(channel)
                elif res["success"]:
                    sent.append(channel)
                elif not res.get("skipped"):
                    failed.append("%s (%s)" % (channel.upper(), res["detail"]))
        parts = []
        if sent:
            parts.append(_("Sent: %s.") % ", ".join(sorted(set(c.upper() for c in sent))))
        if already:
            parts.append(_("Already sent earlier: %s.") % ", ".join(sorted(set(c.upper() for c in already))))
        if failed:
            parts.append(_("Failed: %s.") % "; ".join(failed))
        if not parts:
            parts.append(_("Nothing was sent (missing mobile number / email)."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("%s notification") % EVENTS[event]["label"],
                "message": " ".join(parts),
                "type": "warning" if failed or not sent else "success",
                "sticky": bool(failed),
            },
        }

    def action_execute_header_notification(self):
        """Execute selected header action (Escalated or Resolved) with selected channel (SMS or Email) and toggle ON/OFF."""
        self.ensure_one()
        action = self.header_action or "escalated"
        channel = self.header_channel or "sms"
        event = "acceptance" if action in ("escalated", "accept") else "completion"

        if not self.header_notify_toggle:
            stage = self._bunna_get_stage(event)
            if stage and self.stage_id != stage:
                self.with_context(bunna_skip_notifications=True).write({"stage_id": stage.id})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Stage Updated"),
                    "message": _("Ticket status updated (Customer notification turned OFF)."),
                    "type": "info",
                    "sticky": False,
                },
            }

        if event == "acceptance":
            self.acceptance_channel = channel
            self.acceptance_sent_channel = channel
        else:
            self.done_channel = channel
            self.done_sent_channel = channel

        res = self._bunna_manual_notify(event, channels=(channel,))
        self.with_context(mail_notrack=True).write({"header_notify_toggle": False})
        return res

    def action_accept_ticket_channel(self):
        """Accept ticket (-> In Progress) and notify customer via selected acceptance_channel (SMS or Email)."""
        self.ensure_one()
        ch = self.acceptance_channel or "sms"
        return self._bunna_manual_notify("acceptance", channels=(ch,))

    def action_done_ticket_channel(self):
        """Complete ticket (-> Done) and notify customer via selected done_channel (SMS or Email)."""
        self.ensure_one()
        ch = self.done_channel or "sms"
        return self._bunna_manual_notify("completion", channels=(ch,))

    def action_send_acceptance_sms(self):
        """Accept the ticket (-> In Progress) and notify the customer via SMS (Email deactivated)."""
        return self._bunna_manual_notify("acceptance", channels=("sms",))

    def action_send_acceptance_email(self):
        """Accept the ticket (-> In Progress) and notify the customer via Email (SMS deactivated)."""
        return self._bunna_manual_notify("acceptance", channels=("email",))

    def action_send_done_sms(self):
        """Complete the ticket (-> Done) and notify the customer via SMS (Email deactivated)."""
        return self._bunna_manual_notify("completion", channels=("sms",))

    def action_send_done_email(self):
        """Complete the ticket (-> Done) and notify the customer via Email (SMS deactivated)."""
        return self._bunna_manual_notify("completion", channels=("email",))

