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
    ('comments_opened', 'Comments Opened'),
    ('comments_closed', 'Comments Closed'),
    ('comment_approved', 'Comment Approved'),
    ('comment_restored', 'Comment Restored'),
    ('comment_hidden', 'Comment Hidden'),
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
    line_ids = fields.One2many(
        'bunna.announcement.log.line', 'log_id', string='What Changed', readonly=True)

    def write(self, vals):
        if self.env.context.get('module_uninstall'):
            return super().write(vals)
        raise UserError(_("The audit log cannot be changed."))

    def unlink(self):
        if self.env.context.get('module_uninstall'):
            return super().unlink()
        raise UserError(_("The audit log cannot be deleted."))


class BunnaAnnouncementLogLine(models.Model):
    """One changed value: which field, what it was, what it became."""
    _name = 'bunna.announcement.log.line'
    _description = 'Announcement Audit Change'
    _order = 'id'

    log_id = fields.Many2one(
        'bunna.announcement.log', string='Log Entry', required=True, ondelete='cascade',
        index=True, readonly=True)
    field_label = fields.Char(string='Field', readonly=True)
    old_value = fields.Text(string='Old Value', readonly=True)
    new_value = fields.Text(string='New Value', readonly=True)
    # copied from the log entry so the changes can be searched, grouped and exported on their own
    date = fields.Datetime(related='log_id.date', store=True, index=True)
    user_id = fields.Many2one(related='log_id.user_id', string='Done By', store=True, index=True)
    action = fields.Selection(related='log_id.action', string='Action', store=True)
    announcement_id = fields.Many2one(related='log_id.announcement_id', string='Announcement', store=True)
    announcement_title = fields.Char(related='log_id.announcement_title', string='Title', store=True)

    def write(self, vals):
        if self.env.context.get('module_uninstall'):
            return super().write(vals)
        raise UserError(_("The audit log cannot be changed."))

    def unlink(self):
        if self.env.context.get('module_uninstall') or self.env.context.get('bunna_log_cascade'):
            return super().unlink()
        raise UserError(_("The audit log cannot be deleted."))
