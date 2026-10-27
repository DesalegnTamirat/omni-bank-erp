from odoo import api, fields, models


class EdsTnaDemandInvalidateWizard(models.TransientModel):
    _name = 'eds.tna.demand.invalidate.wizard'
    _description = 'Invalidate Selected Course Candidates'

    demand_ids = fields.Many2many(
        'eds.tna.cycle.course.employee',
        'eds_tna_demand_invalidate_wizard_rel', 'wizard_id', 'demand_id',
        string='Selected Employees', required=True)
    employee_count = fields.Integer(
        string='Employees to Invalidate', compute='_compute_employee_count')
    reason = fields.Text(string='Reason', required=True)

    @api.depends('demand_ids')
    def _compute_employee_count(self):
        for wizard in self:
            wizard.employee_count = len(wizard.demand_ids)

    def action_confirm(self):
        self.ensure_one()
        return self.demand_ids.action_invalidate_with_reason(self.reason)
