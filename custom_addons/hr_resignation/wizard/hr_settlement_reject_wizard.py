# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HrSettlementRejectWizard(models.TransientModel):
    _name = 'hr.settlement.reject.wizard'
    _description = 'Settlement Reject Wizard'

    settlement_id = fields.Many2one('hr.resignation.settlement', string='Settlement', required=True)
    reason = fields.Text(string='Reason for Revision', required=True)

    def action_reject(self):
        for rec in self:
            settlement = rec.settlement_id
            pomd_officer = settlement.processed_by_id
            
            # Post reason to chatter
            msg = f"<b>Sent Back for Revision:</b><br/>{rec.reason}"
            settlement.message_post(body=msg, message_type='notification')
            
            # Notify the POMD officer
            if pomd_officer:
                settlement.resignation_id._send_notification([pomd_officer.partner_id.id], 'Settlement Returned', "The settlement has been sent back for revision.")
            
            # Reset settlement to draft
            settlement.write({
                'state': 'draft',
                'is_processed': False,
                'processed_by_id': False,
                'processed_date': False,
                'confirmed_by_id': False,
                'confirmed_date': False
            })
            
        return {'type': 'ir.actions.act_window_close'}
