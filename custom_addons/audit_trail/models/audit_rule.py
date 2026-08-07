# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AuditRule(models.Model):
    """
    Defines which models (and which operations) should be audited.
    Admins enable auditing per model from the Audit > Configuration menu.
    """
    _name = 'audit.rule'
    _description = 'Audit Rule'
    _order = 'model_id'

    name = fields.Char(string='Rule Name', required=True)
    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade',
        help='The Odoo model to audit (e.g. res.partner, sale.order)'
    )
    model_name = fields.Char(
        related='model_id.model', string='Technical Model Name', store=True, readonly=True
    )
    module = fields.Char(
        string='Module', compute='_compute_module', store=True,
        help='The Odoo module that owns this model'
    )
    active = fields.Boolean(default=True, string='Active')

    # Which operations to log
    log_create = fields.Boolean(string='Log Create', default=True)
    log_write  = fields.Boolean(string='Log Write',  default=True)
    log_unlink = fields.Boolean(string='Log Unlink', default=True)

    # Optional: restrict auditing to specific fields only (blank = all fields)
    field_ids = fields.Many2many(
        'ir.model.fields', string='Fields to Audit',
        domain="[('model_id', '=', model_id)]",
        help='Leave empty to audit ALL fields on the model'
    )

    _sql_constraints = [
        ('model_unique', 'UNIQUE(model_id)', 'An audit rule already exists for this model.')
    ]

    @api.depends('model_id')
    def _compute_module(self):
        for rule in self:
            if rule.model_id:
                # Derive module from ir.model_data
                data = self.env['ir.model.data'].search(
                    [('model', '=', 'ir.model'), ('res_id', '=', rule.model_id.id)],
                    limit=1
                )
                rule.module = data.module if data else 'base'
            else:
                rule.module = False

    @api.model
    def get_rules(self):
        """Return a dict keyed by model name for fast runtime lookup."""
        rules = self.search([('active', '=', True)])
        return {r.model_name: r for r in rules}

    @api.constrains('model_id', 'log_create', 'log_write', 'log_unlink')
    def _check_duplicate_rule(self):
        """
        Validates that no other active audit rule exists for this model
        with the exact same operation settings.
        """
        for record in self:
            domain = [
                ('id', '!=', record.id),
                ('model_id', '=', record.model_id.id),
                ('log_create', '=', record.log_create),
                ('log_write', '=', record.log_write),
                ('log_unlink', '=', record.log_unlink)
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_(
                    "An audit rule with these exact settings already exists for the model '%s'."
                ) % record.model_id.name)