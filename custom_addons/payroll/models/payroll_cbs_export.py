# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import base64
import csv
import io
import logging
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PayrollPaymentBatch(models.Model):
    """
    Core Banking System (CBS) Direct Credit Payment Batch Model.
    
    Generates structured electronic fund transfer files (CBS ACH / CSV / Flat Text / Telebirr)
    for automated bulk disbursement into employee accounts.
    """
    _name = 'payroll.payment.batch'
    _description = 'CBS Direct Credit Payment Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc, id desc'

    name = fields.Char(string='Batch Title', required=True, tracking=True)
    number = fields.Char(
        string='Batch Reference',
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('payroll.payment.batch') or _('New')
    )
    payrun_id = fields.Many2one('hr.payslip.run', string='Originating Payrun', required=True, tracking=True)
    payment_date = fields.Date(string='Disbursement Value Date', required=True, default=fields.Date.context_today, tracking=True)
    
    export_format = fields.Selection([
        ('cbs_csv', 'Bunna CBS Standard Direct Credit (CSV)'),
        ('cbs_txt', 'Core Banking Flat Fixed-Width (TXT)'),
        ('ach_format', 'National ACH Electronic Clearing Format'),
        ('telebirr_bulk', 'Telebirr Mobile Wallet Bulk Disbursement'),
    ], string='Export File Format', default='cbs_csv', required=True)

    line_ids = fields.One2many('payroll.payment.batch.line', 'batch_id', string='Payment Instructions')
    
    total_amount = fields.Float(string='Total Batch Amount (ETB)', compute='_compute_totals', store=True, digits=(16, 2))
    total_count = fields.Integer(string='Beneficiaries Count', compute='_compute_totals', store=True)

    # Exported Binary File
    export_file = fields.Binary(string='Generated Export File', readonly=True, copy=False)
    export_filename = fields.Char(string='Filename', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Draft Batch'),
        ('generated', 'File Generated'),
        ('transmitted', 'Transmitted to CBS'),
        ('reconciled', 'Reconciled / Settled'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    notes = fields.Text(string='Payment Remarks')

    @api.depends('line_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.total_amount = sum(line.amount for line in rec.line_ids)
            rec.total_count = len(rec.line_ids)

    @api.model
    def create_batch_from_payrun(self, payrun):
        """Create payment batch from an approved payrun."""
        batch = self.create({
            'name': f"CBS Payment - {payrun.name}",
            'payrun_id': payrun.id,
            'payment_date': fields.Date.today(),
        })

        lines_to_create = []
        for slip in payrun.slip_ids:
            if slip.net_wage <= 0:
                continue

            acc_no = slip.bank_account or getattr(slip.employee_id, 'salary_account', '') or ''
            lines_to_create.append({
                'batch_id': batch.id,
                'payslip_id': slip.id,
                'employee_id': slip.employee_id.id,
                'beneficiary_name': slip.employee_id.name,
                'bank_account_number': acc_no,
                'amount': slip.net_wage,
                'narrative': f"SALARY {payrun.name[:20]}",
            })

        self.env['payroll.payment.batch.line'].create(lines_to_create)
        return batch

    def action_generate_export_file(self):
        """Generate formatted export file based on chosen format."""
        self.ensure_one()
        missing_acc = self.line_ids.filtered(lambda l: not l.bank_account_number)
        if missing_acc:
            names = ", ".join(missing_acc.mapped('beneficiary_name')[:5])
            raise UserError(_("Cannot generate CBS payment file: %d employees missing bank account numbers: %s") % (len(missing_acc), names))

        output = io.StringIO()
        if self.export_format == 'cbs_csv':
            writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
            # Header
            writer.writerow(['RecordID', 'BeneficiaryName', 'AccountNumber', 'Amount', 'Currency', 'PaymentReference', 'ValueDate'])
            for idx, line in enumerate(self.line_ids, 1):
                writer.writerow([
                    idx,
                    line.beneficiary_name,
                    line.bank_account_number,
                    f"{line.amount:.2f}",
                    'ETB',
                    line.narrative,
                    self.payment_date.strftime('%Y-%m-%d')
                ])
            file_ext = 'csv'
        elif self.export_format == 'telebirr_bulk':
            writer = csv.writer(output, delimiter=',', quotechar='"')
            writer.writerow(['MobileNumber', 'Amount', 'Remarks'])
            for line in self.line_ids:
                mobile = getattr(line.employee_id, 'mobile_phone', '') or ''
                writer.writerow([mobile, f"{line.amount:.2f}", line.narrative])
            file_ext = 'csv'
        else:
            # Fixed width text format
            for idx, line in enumerate(self.line_ids, 1):
                record = f"{idx:06d}{line.bank_account_number:<20}{line.amount*100:012.0f}{line.beneficiary_name[:30]:<30}\n"
                output.write(record)
            file_ext = 'txt'

        content = output.getvalue().encode('utf-8')
        filename = f"CBS_PAYMENT_{self.number}_{self.payment_date}.{file_ext}"

        self.write({
            'export_file': base64.b64encode(content),
            'export_filename': filename,
            'state': 'generated'
        })
        self.message_post(body=_("CBS direct credit payment file [%s] successfully generated.") % filename)

    def action_mark_transmitted(self):
        """Mark as transmitted to Core Banking."""
        for rec in self:
            rec.write({'state': 'transmitted'})
            rec.payrun_id.write({'state': 'disbursed'})
            # Mark payslips as paid
            for line in rec.line_ids:
                line.payslip_id.write({'state': 'paid'})
            rec.message_post(body=_("Payment batch transmitted to Core Banking System for execution."))


class PayrollPaymentBatchLine(models.Model):
    """Individual direct credit payment instruction."""
    _name = 'payroll.payment.batch.line'
    _description = 'CBS Direct Credit Beneficiary Line'
    _order = 'id asc'

    batch_id = fields.Many2one('payroll.payment.batch', string='Payment Batch', required=True, ondelete='cascade')
    payslip_id = fields.Many2one('hr.payslip', string='Payslip')
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    beneficiary_name = fields.Char(string='Beneficiary Full Name', required=True)
    bank_account_number = fields.Char(string='Bank Account Number', required=True)
    amount = fields.Float(string='Disbursement Amount (ETB)', required=True, digits=(16, 2))
    narrative = fields.Char(string='Payment Narrative / Reference')
    status = fields.Selection([
        ('pending', 'Pending Transfer'),
        ('success', 'Credit Successful'),
        ('rejected', 'Transfer Rejected'),
    ], string='Status', default='pending')
