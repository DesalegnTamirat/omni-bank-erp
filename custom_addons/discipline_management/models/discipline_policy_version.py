# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class DisciplinePolicyVersion(models.Model):
    _name = 'discipline.policy.version'
    _description = 'Disciplinary Policy Version Control'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, name desc'

    name = fields.Char(string='Policy Version Title', required=True, tracking=True)
    version_number = fields.Char(string='Version Code (e.g. v2.0)', required=True, tracking=True)
    effective_date = fields.Date(string='Effective Date', required=True, default=fields.Date.context_today, tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', tracking=True)
    description = fields.Text(string='Policy Summary / Changes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)

    offense_ids = fields.One2many('discipline.offense', 'policy_version_id', string='Associated Offenses')

    def action_activate(self):
        for rec in self:
            # Deactivate older active policies
            older = self.search([('id', '!=', rec.id), ('state', '=', 'active')])
            older.write({'state': 'archived'})
            rec.write({'state': 'active'})
