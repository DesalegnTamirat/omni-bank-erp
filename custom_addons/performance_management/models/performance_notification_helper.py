# -*- coding: utf-8 -*-
import logging
from markupsafe import Markup

_logger = logging.getLogger(__name__)


def build_performance_card(
    title,
    badge_text,
    badge_bg="#c17540",
    border_color="#c17540",
    intro_text="",
    details=None,
    action_url="",
    action_btn_text="🎯 Open Performance Document",
    action_btn_color="#541718",
    footer_note="",
):
    """
    Builds a beautifully styled HTML card matching the Bunna Bank theme / hr_leave_request_custom design system.
    """
    details = details or []
    rows_html = ""
    for label, val in details:
        if val is None or val is False or val == '':
            continue
        rows_html += f"""
        <tr>
            <td style="padding: 5px 0; color: #726732; width: 160px; font-weight: 600; vertical-align: top;">{label}:</td>
            <td style="padding: 5px 0; color: #1d2b32; vertical-align: top;">{val}</td>
        </tr>"""

    intro_html = f'<p style="margin: 0 0 10px 0; font-size: 13.5px; color: #1d2b32; line-height: 1.5;">{intro_text}</p>' if intro_text else ''

    btn_html = ""
    if action_url:
        btn_html = f"""
    <div style="margin-top: 15px; text-align: center;">
        <a href="{action_url}" style="background-color: {action_btn_color}; color: #ffffff; padding: 8px 18px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 13px; display: inline-block;">
            {action_btn_text}
        </a>
    </div>"""

    footer_html = ""
    if footer_note:
        footer_html = f"""
    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e2d2c5; font-size: 12px; color: #726732;">
        {footer_note}
    </div>"""

    card_html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 13px; color: #1d2b32; background: #fffcf9; border: 1px solid #ebdcd0; border-left: 5px solid {border_color}; border-radius: 8px; padding: 16px 20px; margin: 6px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #f0e6dd; padding-bottom: 8px;">
        <span style="font-size: 15px; font-weight: bold; color: #541718;">
            {title}
        </span>
        <span style="background-color: {badge_bg}; color: #ffffff; padding: 3px 12px; border-radius: 12px; font-weight: bold; font-size: 12px; letter-spacing: 0.5px;">
            {badge_text}
        </span>
    </div>
    {intro_html}
    <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        {rows_html}
    </table>
    {btn_html}
    {footer_html}
</div>
"""
    return Markup(card_html)


def send_performance_notification(
    record,
    title,
    badge_text,
    badge_bg="#c17540",
    border_color="#c17540",
    intro_text="",
    details=None,
    action_btn_text="🎯 Open Performance Document",
    action_btn_color="#541718",
    footer_note="",
    recipient_partner_ids=None,
    activity_user_id=None,
    activity_summary=None,
    activity_deadline=None,
    activity_note=None,
    subject=None,
):
    """
    Unified helper to post the styled HTML card to chatter, send message_notify, and schedule activity.
    """
    recipient_partner_ids = [pid for pid in (recipient_partner_ids or []) if pid]
    
    base_url = ""
    try:
        base_url = record.get_base_url()
    except Exception:
        pass
    action_url = f"{base_url}/web#id={record.id}&model={record._name}&view_type=form" if base_url else f"/web#id={record.id}&model={record._name}&view_type=form"

    body_html = build_performance_card(
        title=title,
        badge_text=badge_text,
        badge_bg=badge_bg,
        border_color=border_color,
        intro_text=intro_text,
        details=details,
        action_url=action_url,
        action_btn_text=action_btn_text,
        action_btn_color=action_btn_color,
        footer_note=footer_note,
    )

    doc_name = (
        getattr(record, 'planning_name', False)
        or getattr(record, 'name', False)
        or getattr(record, 'display_name', False)
        or 'Performance Document'
    )
    notif_subject = subject or f"{title} - {doc_name}"

    # 1. Post to chatter (creates tracking and notifies followers/recipients)
    try:
        record.sudo().message_post(
            body=body_html,
            subject=notif_subject,
            partner_ids=recipient_partner_ids,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
    except Exception as e:
        _logger.warning("Could not message_post in performance notification: %s", e)

    # 2. Direct message_notify so it pops up in Discuss & Systray preview
    if recipient_partner_ids:
        try:
            record.sudo().message_notify(
                partner_ids=recipient_partner_ids,
                body=body_html,
                subject=notif_subject,
                record_name=doc_name,
            )
        except Exception as e:
            _logger.warning("Could not message_notify in performance notification: %s", e)

    # 3. Schedule activity if user provided
    if activity_user_id:
        try:
            act_note = activity_note or body_html
            record.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=activity_user_id,
                summary=activity_summary or notif_subject,
                note=act_note,
                date_deadline=activity_deadline,
            )
        except Exception as e:
            _logger.warning("Could not activity_schedule in performance notification: %s", e)
