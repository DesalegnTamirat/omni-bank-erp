# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EdsTnaConsolidationWizard(models.TransientModel):
    """Consolidate a TNA cycle (optionally per work unit) into one register."""
    _name = 'eds.tna.consolidation.wizard'
    _description = 'TNA Consolidation Wizard'

    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', required=True, ondelete='cascade')
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit',
        help='Leave empty to consolidate the whole cycle bank-wide.')
    department_id = fields.Many2one(
        'hr.department', string='Department',
        help='Leave empty to consolidate all departments in the work unit.')

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Top of hierarchy: Department -> Operating Unit.
        - If department selected:
          work_unit_id domain restricted to operating units belonging to this department.
          If selected work_unit_id doesn't belong to the department, clear it.
        - If no department selected:
          All operating units are available.
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_id)
        if self.department_id and self.work_unit_id and not self.env['eds.hr.compat'].is_operating_unit_in_departments(self.work_unit_id, self.department_id):
            self.work_unit_id = False
        return {'domain': {'work_unit_id': ou_domain}}

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        """Middle of hierarchy: sync department if unset and known from operating unit."""
        if self.work_unit_id and not self.department_id:
            if hasattr(self.work_unit_id, 'department') and self.work_unit_id.department:
                self.department_id = self.work_unit_id.department
            elif 'operating_unit_id' in self.env['hr.department']._fields:
                linked_dept = self.env['hr.department'].search([('operating_unit_id', '=', self.work_unit_id.id)], limit=1)
                if linked_dept:
                    self.department_id = linked_dept

    def action_consolidate(self):
        self.ensure_one()
        # Reuse an existing draft consolidation for the same cycle + work unit + department (dedup).
        consolidation = self.env['eds.tna.consolidation'].search([
            ('cycle_id', '=', self.cycle_id.id),
            ('work_unit_id', '=', self.work_unit_id.id or False),
            ('department_id', '=', self.department_id.id or False),
            ('state', '=', 'draft'),
        ], limit=1)
        if not consolidation:
            consolidation = self.env['eds.tna.consolidation'].create({
                'cycle_id': self.cycle_id.id,
                'work_unit_id': self.work_unit_id.id or False,
                'department_id': self.department_id.id or False,
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
        self.department_id = False
