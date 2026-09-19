from odoo import api, fields, models

class HrSettlementReturnWizard(models.TransientModel):
    _name = 'hr.settlement.return.wizard'
    _description = 'Return Settlement to Draft Wizard'

    settlement_id = fields.Many2one('hr.resignation.settlement', string='Settlement', required=True)
    reason = fields.Text(string='Reason for Return', required=True)

    def action_return_settlement(self):
        self.ensure_one()
        self.settlement_id.action_return_to_draft(self.reason)

