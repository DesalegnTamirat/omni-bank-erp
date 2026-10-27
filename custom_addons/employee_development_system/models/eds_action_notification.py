"""Actionable EDS alerts: inbox history, a live popup, and a linked activity."""

from markupsafe import Markup, escape

from odoo import models, tools
from odoo.exceptions import UserError


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
                  action_id=None, form_view_id=None):
    """Notify each user once, with the real actor and a link to the record."""
    record.ensure_one()
    actor = record.env.user
    recipients = users.filtered(lambda user: user.active and not user.share
                                and user.id != actor.id and user.partner_id)
    if not recipients:
        return recipients
    link = ('/web#action=%s&amp;id=%s&amp;model=%s&amp;view_type=form' % (
        action_id, record.id, record._name) if action_id else
        '/web#id=%s&amp;model=%s&amp;view_type=form' % (record.id, record._name))
    readable_message = Markup('<br/>').join(
        escape(line) for line in str(message).split('\n'))
    body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
        readable_message, Markup(link), escape('Open record'))
    record.with_context(eds_popup_managed=True).message_post(
        body=body, message_type='comment', subtype_xmlid='mail.mt_comment',
        author_id=actor.partner_id.id, partner_ids=recipients.mapped('partner_id').ids,
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
        action_id=action_id, form_view_id=form_view_id)
    return recipients


def notify_employee_batch(record, employees, title, message, *, action_id=None):
    """Persist one announcement for a batch, then alert online employee users."""
    record.ensure_one()
    users = employees.mapped('user_id').filtered(
        lambda user: user.active and not user.share and user.partner_id)
    partners = users.mapped('partner_id')
    if not partners:
        return 0
    link = ('/web#action=%d' % action_id) if action_id else (
        '/web#id=%s&amp;model=%s&amp;view_type=form' % (record.id, record._name))
    body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
        escape(message), Markup(link), escape('Open training needs'))
    record.with_context(eds_popup_managed=True).message_post(
        body=body, message_type='comment', subtype_xmlid='mail.mt_comment',
        author_id=record.env.user.partner_id.id, partner_ids=partners.ids,
        notify_skip_followers=True)
    push_action_popup(record, users, title, message, action_id=action_id)
    return len(employees.filtered(lambda employee: employee.user_id in users))


def push_action_popup(record, users, title, message, *, action_required=False,
                      action_id=None, form_view_id=None, author_partner=None):
    """Show a live alert when another channel already persisted the message."""
    record.ensure_one()
    actor_partner = author_partner or record.env.user.partner_id
    actor_name = (record.env.ref('base.partner_root').name
                  if not actor_partner else actor_partner.name)
    if actor_partner == record.env.ref('base.partner_root'):
        actor_name = 'Employee Development'
    for user in users.filtered(lambda user: user.active and not user.share and user.partner_id
                               and user.partner_id != actor_partner):
        record.env['bus.bus'].sudo()._sendone(user.partner_id, 'eds.action_notification', {
            'title': title,
            'message': message,
            'actor': actor_name,
            'actor_partner_id': actor_partner.id or False,
            'model': record._name,
            'res_id': record.id,
            'action_required': action_required,
            'action_id': action_id,
            'form_view_id': form_view_id,
        })
