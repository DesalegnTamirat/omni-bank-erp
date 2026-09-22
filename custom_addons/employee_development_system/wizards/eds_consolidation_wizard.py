# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EdsTnaConsolidationWizard(models.TransientModel):
    """Consolidate a TNA cycle (optionally per work unit) into one register ()."""
    _name = 'eds.tna.consolidation.wizard'
    _description = 'TNA Consolidation Wizard'

    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', required=True, ondelete='cascade')
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit',
        help='Leave empty to consolidate the whole cycle bank-wide.')

    def action_consolidate(self):
        self.ensure_one()
        # Reuse an existing draft consolidation for the same cycle + work unit (dedup).
        consolidation = self.env['eds.tna.consolidation'].search([
            ('cycle_id', '=', self.cycle_id.id),
            ('work_unit_id', '=', self.work_unit_id.id or False),
            ('state', '=', 'draft'),
        ], limit=1)
        if not consolidation:
            consolidation = self.env['eds.tna.consolidation'].create({
                'cycle_id': self.cycle_id.id,
                'work_unit_id': self.work_unit_id.id or False,
            })
        consolidation.action_consolidate()
        consolidation.action_compute_priority()
        return {
            'name': _('TNA Consolidation'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.tna.consolidation',
            'res_id': consolidation.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.onchange('cycle_id')
    def _onchange_cycle_id(self):
        self.work_unit_id = False
