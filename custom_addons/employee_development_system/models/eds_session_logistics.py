"""Coordinator assignment and shareable training location on sessions."""

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .eds_action_notification import notify_action, valid_google_maps_url


def _check_google_maps_url(records):
    for record in records:
        if record.google_maps_url and not valid_google_maps_url(record.google_maps_url):
            raise ValidationError(_(
                'Paste an HTTPS Google Maps share link, such as '
                'https://maps.app.goo.gl/... or https://www.google.com/maps/...'))


class EdsVenueLogistics(models.Model):
    _inherit = 'eds.venue'

    google_maps_url = fields.Char(
        string='Google Maps Link', tracking=True,
        help='Paste an HTTPS Google Maps share link. New sessions copy this link and can edit it.')

    @api.constrains('google_maps_url')
    def _check_google_maps_url(self):
        _check_google_maps_url(self)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if 'google_maps_url' in vals:
                vals['google_maps_url'] = (vals['google_maps_url'] or '').strip() or False
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if 'google_maps_url' in vals:
            vals['google_maps_url'] = (vals['google_maps_url'] or '').strip() or False
        return super().write(vals)


class EdsSessionLogistics(models.Model):
    _inherit = 'eds.session'

    coordinator_id = fields.Many2one(
        'hr.employee', string='Training Coordinator', tracking=True,
        ondelete='set null',
        help='Any active employee may coordinate this session. An Odoo user gets '
             'an in-app notice; otherwise the notice is queued to their work email.')
    google_maps_url = fields.Char(
        string='Google Maps Link', tracking=True,
        help='Copied from the selected venue. You may edit it for this session.')

    @api.constrains('google_maps_url')
    def _check_google_maps_url(self):
        _check_google_maps_url(self)

    @api.onchange('venue_id', 'is_virtual')
    def _onchange_venue_google_maps_url(self):
        for session in self:
            session.google_maps_url = (
                session.venue_id.google_maps_url
                if session.venue_id and not session.is_virtual else False)

    @api.onchange('awarded_venue_id')
    def _onchange_awarded_google_maps_url(self):
        for session in self:
            if session.awarded_venue_id and not session.is_virtual:
                session.google_maps_url = session.awarded_venue_id.google_maps_url or False

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if 'google_maps_url' in vals:
                vals['google_maps_url'] = (vals['google_maps_url'] or '').strip() or False
        sessions = super().create(vals_list)
        for session, vals in zip(sessions, vals_list):
            if 'google_maps_url' not in vals and session.venue_id:
                session.with_context(eds_logistics_internal=True).write({
                    'google_maps_url': session.venue_id.google_maps_url or False,
                })
            if session.coordinator_id:
                session._notify_coordinator(_('You have been assigned as training coordinator.'))
        return sessions

    def write(self, vals):
        vals = dict(vals)
        if 'google_maps_url' in vals:
            vals['google_maps_url'] = (vals['google_maps_url'] or '').strip() or False
        before = {
            session.id: (session.coordinator_id.id, session.venue_id.id,
                         session.google_maps_url)
            for session in self
        }
        result = super().write(vals)
        if self.env.context.get('eds_logistics_internal'):
            return result
        for session in self:
            previous_coordinator, previous_venue, previous_map = before[session.id]
            if 'google_maps_url' not in vals and session.venue_id.id != previous_venue:
                session.with_context(eds_logistics_internal=True).write({
                    'google_maps_url': session.venue_id.google_maps_url or False,
                })
            map_changed = session.google_maps_url != previous_map
            coordinator_changed = session.coordinator_id.id != previous_coordinator
            if map_changed and session.status in ('scheduled', 'ongoing'):
                session._notify_participants(_(
                    'The Google Maps location link for session %s has changed. '
                    'Please review the updated training location.') % session.name)
            elif coordinator_changed and session.coordinator_id:
                session._notify_coordinator(_(
                    'You have been assigned as training coordinator.'))
        return result

    def _coordinator_notice(self, introduction, recipient):
        self.ensure_one()
        timezone = (recipient.tz if recipient else self.env.user.tz) or 'UTC'
        local_record = self.with_context(tz=timezone)
        lines = [str(introduction),
                 _('Session: %s') % self.name,
                 _('Course: %s') % self.course_id.name]
        for label, date in ((_('Starts'), self.date_start), (_('Ends'), self.date_end)):
            if date:
                local_date = fields.Datetime.context_timestamp(local_record, date)
                lines.append(_('%s: %s') % (
                    label, local_date.strftime('%Y-%m-%d %H:%M %Z')))
        if self.venue_id:
            lines.append(_('Venue: %s') % self.venue_id.name)
        if self.google_maps_url:
            lines.append(_('Google Maps: %s') % self.google_maps_url)
        return '\n'.join(lines)

    def _notify_coordinator(self, introduction):
        self.ensure_one()
        coordinator = self.coordinator_id.sudo()
        if not coordinator:
            return
        user = coordinator.user_id
        title = _('Training coordinator update')
        message = self._coordinator_notice(introduction, user)
        if user and user.active and not user.share:
            notify_action(self.sudo(), user, title, message,
                          action_required=False, map_url=self.google_maps_url)
            return
        email = (coordinator.work_email or coordinator.work_contact_id.email or '').strip()
        if email:
            body = Markup('<p>%s</p>') % (
                Markup('<br/>').join(escape(line) for line in message.split('\n')))
            if self.google_maps_url:
                body += Markup('<p><a href="%s">%s</a></p>') % (
                    escape(self.google_maps_url), escape('Open Google Maps'))
            self.env['mail.mail'].sudo().create({
                'subject': title,
                'body_html': body,
                'email_to': email,
            })
            return
        # Keep the missing delivery address visible to L&D without blocking a
        # valid coordinator selection or widening HR profile access.
        self.with_context(eds_popup_managed=True).message_post(
            body=escape(_(
                'Coordinator %s has no linked Odoo user or work email; '
                'the assignment notice could not be delivered.') % coordinator.name),
            subtype_xmlid='mail.mt_note', notify_skip_followers=True)

    def _notify_participants(self, message, *, remind_invited=False):
        result = super()._notify_participants(message, remind_invited=remind_invited)
        if not self.env.context.get('eds_coordinator_defer'):
            self._notify_coordinator(message)
        return result

    def action_confirm(self):
        # Source synchronization can emit a participant notice during confirm;
        # send one final schedule notice to the coordinator afterward.
        result = super(EdsSessionLogistics, self.with_context(
            eds_coordinator_defer=True)).action_confirm()
        for session in self.filtered(lambda row: row.status == 'scheduled'):
            session._notify_coordinator(_('The training schedule is confirmed.'))
        return result

    def action_reschedule(self):
        result = super().action_reschedule()
        for session in self.filtered(lambda row: row.status == 'rescheduled'):
            session._notify_coordinator(_('The training schedule is being revised.'))
        return result

    def action_confirm_reschedule(self):
        result = super(EdsSessionLogistics, self.with_context(
            eds_coordinator_defer=True)).action_confirm_reschedule()
        for session in self.filtered(lambda row: row.status == 'scheduled'):
            session._notify_coordinator(_('The revised training schedule is confirmed.'))
        return result


class EdsEnrollmentLocation(models.Model):
    _inherit = 'eds.enrollment'

    google_maps_url = fields.Char(
        string='Google Maps Link', related='session_id.google_maps_url', readonly=True)
