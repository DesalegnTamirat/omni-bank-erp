# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmStrategicObjective(models.Model):
    _name = 'pm.strategic.objective'
    _description = 'Strategic Objective'
    _order = 'name asc'

    name = fields.Char(string='Strategic Objective', required=True)
    code = fields.Char(string='ID / Code', readonly=True, copy=False, default=lambda self: _('New'))
    description = fields.Text(string='Description & Scope')
    active = fields.Boolean(string='Active', default=True)

    # Strategic Issue alignment (Feedback Line 88)
    strategic_issue_id = fields.Many2one('pm.strategic.issue', string='Strategic Issue', index=True)

    # Strategic Sources list (Feedback Line 02: one strategic objective may have more than one strategic sources)
    strategic_source_ids = fields.Many2many(
        'pm.strategic.source',
        'pm_strategic_objective_source_rel',
        'objective_id',
        'source_id',
        string='Strategic Sources'
    )
    available_strategic_source_ids = fields.Many2many(
        'pm.strategic.source',
        compute='_compute_available_strategic_source_ids',
        string='Available Strategic Sources'
    )

    @api.depends('strategic_issue_id', 'strategic_issue_id.strategic_source_ids')
    def _compute_available_strategic_source_ids(self):
        all_sources = self.env['pm.strategic.source'].search([])
        for rec in self:
            if rec.strategic_issue_id and rec.strategic_issue_id.strategic_source_ids:
                rec.available_strategic_source_ids = rec.strategic_issue_id.strategic_source_ids
            else:
                rec.available_strategic_source_ids = all_sources

    @api.onchange('strategic_issue_id')
    def _onchange_strategic_issue_id(self):
        if self.strategic_issue_id:
            if self.strategic_issue_id.strategic_source_ids:
                # Autofill the strategic sources aligned with this issue
                if not self.strategic_source_ids:
                    self.strategic_source_ids = self.strategic_issue_id.strategic_source_ids
                return {'domain': {'strategic_source_ids': [('id', 'in', self.strategic_issue_id.strategic_source_ids.ids)]}}
        return {'domain': {'strategic_source_ids': []}}

    # Aligned Initiatives (Feedback Line 03-11 & Line 89: Strategic objective may be addressed by one or multiple initiative)
    initiative_ids = fields.Many2many(
        'pm.initiative',
        'pm_strategic_objective_initiative_rel',
        'objective_id',
        'initiative_id',
        string='Aligned Initiatives'
    )
    initiative_count = fields.Integer(string='Initiatives Count', compute='_compute_initiative_count', store=True)

    @api.depends('initiative_ids')
    def _compute_initiative_count(self):
        for rec in self:
            rec.initiative_count = len(rec.initiative_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.strategic.objective') or _('New')
        return super().create(vals_list)

    def unlink(self):
        """Soft delete: archive strategic objective instead of permanent deletion."""
        return self.write({'active': False})

