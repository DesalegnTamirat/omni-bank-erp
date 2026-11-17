# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

ACTIONS = [
    ('created', 'Created'),
    ('published', 'Published'),
    ('revoked', 'Revoked'),
    ('set_draft', 'Set to Draft'),
    ('expired_now', 'Expired Now'),
    ('edited', 'Edited While Published'),
    ('archived', 'Archived'),
    ('unarchived', 'Unarchived'),
]


class BunnaAnnouncementLog(models.Model):
    """Append-only audit trail: who did what to which announcement, and when."""
    _name = 'bunna.announcement.log'
    _description = 'Announcement Audit Log'
    _order = 'date desc, id desc'
    _rec_name = 'announcement_title'

    announcement_id = fields.Many2one(
        'bunna.announcement', string='Announcement', ondelete='set null', index=True, readonly=True)
    announcement_title = fields.Char(string='Title', readonly=True)
    action = fields.Selection(ACTIONS, string='Action', required=True, index=True, readonly=True)
    user_id = fields.Many2one('res.users', string='Done By', required=True, index=True, readonly=True)
    date = fields.Datetime(
        string='Date', required=True, index=True, readonly=True, default=fields.Datetime.now)
    state_after = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('revoked', 'Revoked')],
        string='Status After', readonly=True)
    details = fields.Char(string='Details', readonly=True)

    def write(self, vals):
        if self.env.context.get('module_uninstall'):
            return super().write(vals)
        raise UserError(_("The audit log cannot be changed."))

    def unlink(self):
        if self.env.context.get('module_uninstall'):
            return super().unlink()
        raise UserError(_("The audit log cannot be deleted."))
