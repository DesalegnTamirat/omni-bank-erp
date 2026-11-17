# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

GROUP_PUBLISHER = 'bunna_hr_announcement.group_announcement_publisher'

UPSERT_THROTTLE = """
    INSERT INTO bunna_announcement_throttle (key, bucket, hits) VALUES (%s, %s, 1)
    ON CONFLICT (key, bucket) DO UPDATE SET hits = bunna_announcement_throttle.hits + 1
    RETURNING hits
"""


def _notify(message, level='success', sticky=False):
    """A pop-up message; the screen behind it refreshes afterwards."""
    return {
        'type': 'ir.actions.client',
        'tag': 'display_notification',
        'params': {
            'title': _("Done") if level == 'success' else _("Please note"),
            'message': message,
            'type': level,
            'sticky': sticky,
            'next': {'type': 'ir.actions.act_window_close'},
        },
    }


class BunnaAnnouncementComment(models.Model):
    """A reader's comment. It is anonymous: no name, account, IP address or exact time is stored."""
    _name = 'bunna.announcement.comment'
    _description = 'Announcement Comment'
    _order = 'id desc'
    _rec_name = 'body'
    _log_access = False  # no create_uid / create_date: nothing that could identify or time the author

    announcement_id = fields.Many2one(
        'bunna.announcement', string='Announcement', required=True, ondelete='cascade',
        index=True, readonly=True)
    body = fields.Text(string='Comment', required=True, readonly=True)
    submitted_on = fields.Date(string='Received On', default=fields.Date.today, readonly=True)
    state = fields.Selection(
        [('pending', 'Waiting for Review'), ('approved', 'Approved'), ('hidden', 'Hidden')],
        string='Status', default='pending', required=True, index=True, readonly=True)
    report_count = fields.Integer(string='Reports', default=0, readonly=True,
                                  help="How many readers reported this comment.")
    moderated_by = fields.Many2one('res.users', string='Reviewed By', readonly=True)
    moderated_on = fields.Datetime(string='Reviewed On', readonly=True)
    hide_reason = fields.Char(string='Reason Hidden', readonly=True)

    # ---- Moderation (Publishers and Administrators) ----------------------
    def _check_moderator(self):
        if not (self.env.su or self.env.user.has_group(GROUP_PUBLISHER)):
            raise AccessError(_("Only Announcement Publishers and Administrators can review comments."))

    def action_approve(self):
        """Show the comment on the website (also used to restore a hidden comment)."""
        self._check_moderator()
        done, skipped = self.browse(), []
        for rec in self:
            if rec.state == 'approved':
                skipped.append(_("Comment #%s is already approved.", rec.id))
                continue
            was_hidden = rec.state == 'hidden'
            rec.sudo().write({
                'state': 'approved', 'moderated_by': self.env.uid,
                'moderated_on': fields.Datetime.now(), 'hide_reason': False})
            rec.announcement_id._log_event(
                'comment_restored' if was_hidden else 'comment_approved',
                _("Comment #%s %s", rec.id, _("restored") if was_hidden else _("approved")))
            done |= rec
        if not done:
            raise UserError(" ".join(skipped))
        message = (_("Comment #%s is now visible on the website.", done.id) if len(done) == 1
                   else _("%s comments are now visible on the website.", len(done)))
        return _notify(" ".join([message] + skipped), 'warning' if skipped else 'success', bool(skipped))

    def action_hide_wizard(self):
        self._check_moderator()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Hide Comment"),
            'res_model': 'bunna.announcement.comment.hide',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_comment_ids': [(6, 0, self.ids)]},
        }

    def _hide(self, reason):
        """Hide comments from the website, keeping them (and the reason) on record."""
        done = self.browse()
        for rec in self:
            if rec.state == 'hidden':
                continue
            rec.sudo().write({
                'state': 'hidden', 'hide_reason': reason, 'moderated_by': self.env.uid,
                'moderated_on': fields.Datetime.now()})
            rec.announcement_id._log_event(
                'comment_hidden', _("Comment #%(id)s hidden. Reason: %(reason)s", id=rec.id, reason=reason))
            done |= rec
        if not done:
            raise UserError(_("The selected comment is already hidden."))
        return _notify(_("%s comment(s) hidden from the website. The reason was recorded.", len(done)))

    def unlink(self):
        if self.env.context.get('module_uninstall'):
            return super().unlink()
        raise UserError(_("Comments cannot be deleted. Hide a comment instead; it stays on record."))


class BunnaAnnouncementCommentHide(models.TransientModel):
    _name = 'bunna.announcement.comment.hide'
    _description = 'Hide Comments'

    comment_ids = fields.Many2many('bunna.announcement.comment', string='Comments')
    reason = fields.Char(string='Reason', required=True,
                         help="Recorded with the comment and in the audit log. Readers do not see it.")

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("Please give a reason for hiding the comment."))
        return self.comment_ids._hide(reason)


class BunnaAnnouncementThrottle(models.Model):
    """Short-lived request counters used only to slow down spam.

    The key is a one-way code that changes every day; it is never stored with a comment,
    and rows are deleted after two hours.
    """
    _name = 'bunna.announcement.throttle'
    _description = 'Announcement Request Counter (anti-spam)'

    key = fields.Char(required=True, index=True)
    bucket = fields.Char(required=True)
    hits = fields.Integer(default=0)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS bunna_announcement_throttle_uniq
            ON bunna_announcement_throttle (key, bucket)
        """)

    @api.model
    def _hit(self, key):
        """Count one request for this key in the current hour and return the hourly total."""
        bucket = datetime.now(pytz.utc).strftime('%Y%m%d%H')
        try:
            with self.env.registry.cursor() as cr:
                cr.execute(UPSERT_THROTTLE, (key, bucket))
                return cr.fetchone()[0]
        except Exception:
            _logger.warning("bunna announcement: could not update the request counter", exc_info=True)
            return 0

    @api.model
    def _cron_purge_throttle(self):
        cutoff = (datetime.now(pytz.utc) - timedelta(hours=2)).strftime('%Y%m%d%H')
        self.env.cr.execute("DELETE FROM bunna_announcement_throttle WHERE bucket < %s", (cutoff,))
