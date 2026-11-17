# -*- coding: utf-8 -*-
import re
from odoo import models, tools
from markupsafe import Markup

def format_notification_body_html(text):
    """
    Ensures notifications sent to users via Discuss / Chatter preserve line breaks,
    bullet points, and structured layout instead of collapsing into a single continuous line.
    """
    if not text:
        return text
    if isinstance(text, str):
        # If it already contains structured HTML with paragraphs/breaks/tables/lists, preserve it as Markup
        if any(tag in text for tag in ("<p>", "<br", "<div", "<ul>", "<ol>", "<li>", "<table>")):
            return Markup(text)
        # Escape raw HTML characters to prevent XSS
        escaped = tools.html_escape(text)
        # Format bullet points with bold keys: e.g. "• Reference No: 123" -> "• <b>Reference No:</b> 123"
        escaped = re.sub(r'([•*\-]\s*)([^:\r\n]+:)', r'\1<b>\2</b>', escaped)
        # Convert newlines to HTML line breaks
        html_str = escaped.replace("\r\n", "<br/>").replace("\n", "<br/>")
        return Markup(html_str)
    return text

class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def message_post(self, *args, **kwargs):
        if args:
            body = args[0]
            if body and isinstance(body, str) and '\n' in body and not any(tag in body for tag in ("<p>", "<br", "<div", "<ul>", "<ol>", "<li>", "<table>")):
                args = (format_notification_body_html(body),) + args[1:]
        elif 'body' in kwargs:
            body = kwargs['body']
            if body and isinstance(body, str) and '\n' in body and not any(tag in body for tag in ("<p>", "<br", "<div", "<ul>", "<ol>", "<li>", "<table>")):
                kwargs['body'] = format_notification_body_html(body)
        return super().message_post(*args, **kwargs)

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def message_post(self, *args, **kwargs):
        if args:
            body = args[0]
            if body and isinstance(body, str) and '\n' in body and not any(tag in body for tag in ("<p>", "<br", "<div", "<ul>", "<ol>", "<li>", "<table>")):
                args = (format_notification_body_html(body),) + args[1:]
        elif 'body' in kwargs:
            body = kwargs['body']
            if body and isinstance(body, str) and '\n' in body and not any(tag in body for tag in ("<p>", "<br", "<div", "<ul>", "<ol>", "<li>", "<table>")):
                kwargs['body'] = format_notification_body_html(body)
        return super().message_post(*args, **kwargs)
