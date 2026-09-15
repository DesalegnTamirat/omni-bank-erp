# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollCbsExportWizard(models.TransientModel):
    """
    Direct Credit CBS Payment File Exporter Wizard.
    """
    _name = 'payroll.cbs.export.wizard'
    _description = 'Export CBS Direct Credit File Wizard'

    batch_id = fields.Many2one('payroll.payment.batch', string='Payment Batch', required=True)
    export_format = fields.Selection([
        ('cbs_csv', 'Bunna CBS Standard Direct Credit (CSV)'),
        ('cbs_txt', 'Core Banking Flat Fixed-Width (TXT)'),
        ('ach_format', 'National ACH Electronic Clearing Format'),
        ('telebirr_bulk', 'Telebirr Mobile Wallet Bulk Disbursement'),
    ], string='Export Format', default='cbs_csv', required=True)

    def action_export(self):
        """Execute export file generation."""
        self.ensure_one()
        self.batch_id.write({'export_format': self.export_format})
        self.batch_id.action_generate_export_file()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.payment.batch',
            'res_id': self.batch_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
