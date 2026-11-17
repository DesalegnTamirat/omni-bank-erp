# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Font Awesome 4.7 icons offered for categories
ICON_CHOICES = [
    ('fa-newspaper-o', 'Newspaper (News)'),
    ('fa-bell', 'Bell (Notification)'),
    ('fa-bullhorn', 'Megaphone (Announcement)'),
    ('fa-info-circle', 'Information'),
    ('fa-exclamation-triangle', 'Warning'),
    ('fa-calendar', 'Calendar (Event)'),
    ('fa-briefcase', 'Briefcase (Jobs)'),
    ('fa-graduation-cap', 'Graduation cap (Training)'),
    ('fa-users', 'People (Staff)'),
    ('fa-gift', 'Gift'),
    ('fa-trophy', 'Trophy (Achievement)'),
    ('fa-heartbeat', 'Health'),
    ('fa-money', 'Money (Payroll)'),
    ('fa-file-text-o', 'Document (Policy)'),
    ('fa-gavel', 'Gavel (Legal)'),
    ('fa-star', 'Star'),
]

COLOR_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def _validate_config(records, label):
    """Shared checks: a name, a name that is not used twice, a real color."""
    for rec in records:
        name = (rec.name or '').strip()
        if not name:
            raise ValidationError(_("%s Name: please enter a name.", label))
        escaped = name.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        duplicates = records.sudo().with_context(active_test=False).search_count(
            [('id', '!=', rec.id), ('name', '=ilike', escaped)])
        if duplicates:
            raise ValidationError(_("%(label)s Name: '%(name)s' already exists (it may be archived).",
                                    label=label, name=name))
        if rec.color and not COLOR_RE.match(rec.color):
            raise ValidationError(_(
                "%(label)s Badge Color: '%(color)s' is not a valid color. Use a code like #1d2b32.",
                label=label, color=rec.color))


class BunnaAnnouncementCategory(models.Model):
    _name = 'bunna.announcement.category'
    _description = 'Announcement Category'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Char(string='Badge Color', default='#1d2b32')
    icon = fields.Selection(
        ICON_CHOICES, string='Icon', required=True, default='fa-newspaper-o',
        help="Shown on the website for posts of this category that have no cover image.")
    expiry_required = fields.Boolean(
        string='Expiry Date Required',
        help="Announcements of this category cannot be saved without an Expiry Date "
             "(useful for time-limited notices).")
    active = fields.Boolean(default=True)

    @api.constrains('name', 'color')
    def _check_config(self):
        _validate_config(self, _("Category"))

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not vals['active'] and not self.search_count([]):
            raise ValidationError(_("At least one active category is required."))
        return res

    def unlink(self):
        res = super().unlink()
        if not self.env.context.get('module_uninstall') and not self.search_count([]):
            raise ValidationError(_("At least one active category is required."))
        return res


class BunnaAnnouncementPriority(models.Model):
    _name = 'bunna.announcement.priority'
    _description = 'Announcement Priority'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    color = fields.Char(string='Badge Color', default='#b32d2e')
    is_highlighted = fields.Boolean(
        string='Highlight on Website',
        help="Posts with this priority get a colored accent and a priority badge on the website.")
    active = fields.Boolean(default=True)

    @api.constrains('name', 'color')
    def _check_config(self):
        _validate_config(self, _("Priority"))

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not vals['active'] and not self.search_count([]):
            raise ValidationError(_("At least one active priority is required."))
        return res

    def unlink(self):
        res = super().unlink()
        if not self.env.context.get('module_uninstall') and not self.search_count([]):
            raise ValidationError(_("At least one active priority is required."))
        return res
