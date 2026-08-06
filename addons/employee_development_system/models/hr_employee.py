# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HrEmployeeEds(models.Model):
    """hr.employee extension: EDS training-needs smart button."""
    _inherit = 'hr.employee'

    eds_tna_entry_ids = fields.One2many('eds.tna.entry', 'employee_id', string='TNA Needs')
    eds_tna_entry_count = fields.Integer(string='Training Needs (TNA)', compute='_compute_eds_tna_entry_count')

    @api.depends('eds_tna_entry_ids')
    def _compute_eds_tna_entry_count(self):
        for rec in self:
            rec.eds_tna_entry_count = len(rec.eds_tna_entry_ids)

    def action_view_eds_tna_entries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Training Needs (TNA)',
            'res_model': 'eds.tna.entry',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }
