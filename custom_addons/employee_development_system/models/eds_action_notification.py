"""Actionable EDS alerts: inbox history, a live popup, and a linked activity."""

from markupsafe import Markup, escape
from urllib.parse import urlsplit

from odoo import models, tools
from odoo.exceptions import UserError


def valid_google_maps_url(value):
    """Return a safe HTTPS Google Maps URL, or False for any other destination."""
    value = (value or '').strip()
    if not value:
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        return False
    if host in ('maps.app.goo.gl', 'maps.google.com'):
        return value
    if host in ('google.com', 'www.google.com') and parsed.path.startswith('/maps'):
        return value
    if host == 'goo.gl' and parsed.path.startswith('/maps/'):
        return value
    return False


def _record_google_maps_url(record, explicit_url=None):
    if explicit_url is None:
        if record._name == 'eds.enrollment':
            explicit_url = record.sudo().session_id.google_maps_url
        elif record._name == 'eds.session':
            explicit_url = record.sudo().google_maps_url
    return valid_google_maps_url(explicit_url)


class EdsInAppMailThread(models.AbstractModel):
    """Keep EDS chatter and action notices inside Odoo, regardless of user preference."""

    _inherit = 'mail.thread'

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        recipients = super()._notify_get_recipients(message, msg_vals=msg_vals, **kwargs)
        if not self._name.startswith('eds.'):
            return recipients
        internal = [dict(recipient, notif='inbox') for recipient in recipients
                    if recipient.get('uid') and not recipient.get('ushare')]
        # Odoo's activity assignment already has its own bell entry; the EDS
        # action notice sent before scheduling it supplies the human popup.
        if (internal and message.message_type != 'user_notification'
                and not self.env.context.get('eds_popup_managed')):
            self.ensure_one()
            users = self.env['res.users'].sudo().browse(
                list({recipient['uid'] for recipient in internal})).exists()
            body = tools.html2plaintext(message.body or '').strip()
            push_action_popup(
                self, users, self.display_name, body[:300] or self.display_name,
                author_partner=message.author_id)
        return internal


def role_users(record, role_xml_id, fallback_xml_id=None):
    """Find active review-role members with access to the record's company."""
    record.ensure_one()
    company = record.company_id if 'company_id' in record._fields else record.env.company
    for xml_id in (role_xml_id, fallback_xml_id):
        if not xml_id:
            continue
        group = record.env.ref('employee_development_system.' + xml_id,
                               raise_if_not_found=False)
        members = (group.sudo().user_ids if group else record.env['res.users']).filtered(
            lambda user: user.active and not user.share and company in user.company_ids
            and user.id != record.env.user.id)
        if members:
            return members
    return record.env['res.users']


def notify_role_action(record, role_xml_id, fallback_xml_id, title, message):
    users = role_users(record, role_xml_id, fallback_xml_id)
    if not users:
        raise UserError('No eligible EDS reviewer is available for %s.' % title)
    clear_action_activities(record)
    return notify_action(record, users, title, message)

def clear_action_activities(record):
    """Clear obsolete EDS tasks when the record moves to another stage."""
    activities = record.activity_ids.filtered(
        lambda activity: (activity.summary or '').startswith('EDS action:'))
    if activities:
        activities.sudo().unlink()


def notify_action(record, users, title, message, *, action_required=True,
                  action_id=None, form_view_id=None, map_url=None,
                  action_label=None, allow_self=False, author_partner=None):
    """Notify each user once, with the real actor and a link to the record."""
    record.ensure_one()
    actor_partner = author_partner or record.env.user.partner_id
    actor = record.env.user
    recipients = users.filtered(lambda user: user.active and not user.share
                                and (allow_self or user.id != actor.id or (author_partner and user.partner_id != author_partner)) and user.partner_id)
    if not recipients:
        return recipients
    link = ('/web#action=%s&amp;id=%s&amp;model=%s&amp;view_type=form' % (
        action_id, record.id, record._name) if action_id else
        '/web#id=%s&amp;model=%s&amp;view_type=form' % (record.id, record._name))
    readable_message = Markup('<br/>').join(
        escape(line) for line in str(message).split('\n'))
    body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
        readable_message, Markup(link), escape('Open record'))
    map_url = _record_google_maps_url(record, map_url)
    if map_url:
        body += Markup(
            '<p><a href="%s" target="_blank" rel="noopener noreferrer">%s</a></p>'
        ) % (escape(map_url), escape('Open Google Maps'))
    record.with_context(eds_popup_managed=True).message_post(
        body=body, message_type='comment', subtype_xmlid='mail.mt_comment',
        author_id=actor_partner.id if actor_partner else actor.partner_id.id, partner_ids=recipients.mapped('partner_id').ids,
        notify_skip_followers=True)
    for user in recipients:
        if action_required:
            summary = 'EDS action: %s' % title
            if not record.activity_ids.filtered(
                    lambda activity: activity.user_id == user and activity.summary == summary):
                record.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=summary, note=message)
    push_action_popup(
        record, recipients, title, message, action_required=action_required,
        action_id=action_id, form_view_id=form_view_id, author_partner=actor_partner,
        map_url=map_url, action_label=action_label, allow_self=allow_self)
    return recipients


def notify_employee_batch(record, employees, title, message, *, action_id=None,
                          link_label=None):
    """Persist one inbox notice per batch and queue email for staff without a login."""
    record.ensure_one()
    users = employees.mapped('user_id').filtered(
        lambda user: user.active and not user.share and user.partner_id
        and (not record.company_id or record.company_id in user.company_ids))
    partners = users.mapped('partner_id')
    link = ('/web#action=%d' % action_id) if action_id else (
        '/web#id=%s&amp;model=%s&amp;view_type=form' % (record.id, record._name))
    body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
        escape(message), Markup(link), escape(link_label or 'Open training needs'))
    if partners:
        record.with_context(eds_popup_managed=True).message_post(
            body=body, message_type='comment', subtype_xmlid='mail.mt_comment',
            author_id=record.env.user.partner_id.id, partner_ids=partners.ids,
            notify_skip_followers=True)
        push_action_popup(record, users, title, message, action_id=action_id,
                          action_label=link_label)

    user_ids = set(users.ids)
    fallback_emails = {
        email for employee in employees if employee.user_id.id not in user_ids
        if (email := (employee.work_email or employee.work_contact_id.email
                      or '').strip().lower())
    }
    fallback_emails.difference_update(
        (user.partner_id.email or '').strip().lower() for user in users)
    if fallback_emails:
        absolute_link = record.get_base_url().rstrip('/') + link.replace('&amp;', '&')
        mail_body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
            escape(message), escape(absolute_link),
            escape(link_label or 'Open training needs'))
        record.env['mail.mail'].sudo().create([{
            'subject': title,
            'body_html': str(mail_body),
            'email_to': email,
        } for email in sorted(fallback_emails)])
    return len(users) + len(fallback_emails)


def push_action_popup(record, users, title, message, *, action_required=False,
                      action_id=None, form_view_id=None, author_partner=None,
                      map_url=None, action_label=None, allow_self=False):
    """Show a live alert when another channel already persisted the message."""
    record.ensure_one()
    actor_partner = author_partner or record.env.user.partner_id
    map_url = _record_google_maps_url(record, map_url)
    actor_name = (record.env.ref('base.partner_root').name
                  if not actor_partner else actor_partner.name)
    if actor_partner == record.env.ref('base.partner_root'):
        actor_name = 'Employee Development'
    for user in users.filtered(lambda user: user.active and not user.share and user.partner_id
                               and (allow_self or user.partner_id != actor_partner)):
        record.env['bus.bus'].sudo()._sendone(user.partner_id, 'eds.action_notification', {
            'title': title,
            'message': message,
            'actor': actor_name,
            'actor_partner_id': actor_partner.id or False,
            'model': record._name,
            'res_id': record.id,
            'action_required': action_required,
            'action_id': action_id,
            'action_label': action_label or False,
            'form_view_id': form_view_id,
            'map_url': map_url or False,
        })
