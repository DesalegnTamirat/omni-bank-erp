from random import randint

from odoo import api, fields, models


class DmsTag(models.Model):
    _name = 'dms.tag'
    _description = 'Document Tag'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=lambda self: randint(1, 11))
    active = fields.Boolean(
        string='Enabled', default=True,
        help="Disabled tags are hidden from the tag pickers and the filters. "
             "Documents keep them and they come back when the tag is enabled again.")
    status = fields.Selection(
        [('enabled', 'Enabled'), ('disabled', 'Disabled')], string='Status',
        compute='_compute_status', store=True, index=True)

    _name_uniq = models.Constraint('unique (name)', 'This tag already exists.')

    @api.depends('active')
    def _compute_status(self):
        for tag in self:
            tag.status = 'enabled' if tag.active else 'disabled'

    def action_disable(self):
        self.write({'active': False})
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_enable(self):
        self.write({'active': True})
        return {'type': 'ir.actions.client', 'tag': 'reload'}
