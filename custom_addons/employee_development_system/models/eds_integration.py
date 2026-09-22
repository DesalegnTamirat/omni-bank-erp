# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import csv
import io

class EdsIntegrationLog(models.Model):
    _name = 'eds.integration.log'
    _description = 'EDS External System Integration Audit Log'
    _order = 'create_date desc'

    name = fields.Char(string='Transaction ID', required=True, default=lambda self: _('New'))
    system = fields.Selection([
        ('lms', 'Learning Management System (LMS)'),
        ('pms', 'Performance Management System (PMS)'),
        ('finance', 'Core Finance & Accounting'),
        ('payroll', 'Payroll Module'),
    ], string='Target System', required=True)
    direction = fields.Selection([
        ('inbound', 'Inbound to EDS'),
        ('outbound', 'Outbound from EDS'),
    ], string='Direction', required=True)
    payload_hash = fields.Char(string='Payload Hash / Ref')
    status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('retry', 'Retry Queued'),
    ], string='Status', required=True, default='success')
    error_message = fields.Text(string='Error Details')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)

class EdsLmsRouting(models.Model):
    _name = 'eds.lms.routing'
    _description = 'EDS E-Learning Course Routing to LMS'
    _inherit = ['mail.thread']

    course_id = fields.Many2one('eds.course', string='EDS Course', required=True, ondelete='cascade')
    session_id = fields.Many2one('eds.session', string='Training Session')
    delivery_mode = fields.Selection([
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended (Classroom + E-Learning)'),
    ], string='Delivery Mode', required=True, default='e_learning')
    lms_ref = fields.Char(string='LMS External Course ID / Ref')
    sync_state = fields.Selection([
        ('pending', 'Pending Sync'),
        ('synced', 'Synced to LMS'),
        ('error', 'Sync Error'),
    ], string='Sync State', default='pending', tracking=True)
    lms_completion_pct = fields.Float(string='LMS Completion Rate (%)', default=0.0)
    last_sync_date = fields.Datetime(string='Last Sync Date')

    def action_sync_to_lms(self):
        for rec in self:
            # Stubs/Contract for LMS Sync
            rec.sync_state = 'synced'
            rec.last_sync_date = fields.Datetime.now()
            self.env['eds.integration.log'].create({
                'name': f"LMS-SYNC-{rec.course_id.code}",
                'system': 'lms',
                'direction': 'outbound',
                'status': 'success',
                'error_message': f"Course {rec.course_id.name} payload dispatched to LMS shell API.",
            })

class EdsPmsGapImport(models.TransientModel):
    _name = 'eds.pms.gap.import'
    _description = 'Import Competency Gaps from PMS'

    cycle_id = fields.Many2one('eds.tna.cycle', string='Target TNA Cycle', required=True)
    csv_file = fields.Binary(string='PMS Gap Export File (CSV)', required=True)
    filename = fields.Char(string='File Name')

    def action_import_gaps(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please attach a CSV file to import."))

        data = base64.b64decode(self.csv_file)
        file_input = io.StringIO(data.decode('utf-8'))
        reader = csv.DictReader(file_input)

        count = 0
        for row in reader:
            emp_code = row.get('employee_code') or row.get('employee_id')
            comp_code = row.get('competency_code') or row.get('competency_id')
            severity = row.get('severity', 'high').lower()

            emp = self.env['hr.employee'].search([('registration_number', '=', emp_code)], limit=1) or \
                  self.env['hr.employee'].search([('name', '=', emp_code)], limit=1)
            comp = self.env['competency.competency'].search([('code', '=', comp_code)], limit=1) or \
                   self.env['competency.competency'].search([('name', '=', comp_code)], limit=1)

            if emp and comp:
                self.env['eds.tna.entry'].create({
                    'cycle_id': self.cycle_id.id,
                    'employee_id': emp.id,
                    'work_unit_id': emp.operating_unit_id.id if hasattr(emp, 'operating_unit_id') else False,
                    'competency_id': comp.id,
                    'gap_severity': severity if severity in ['critical', 'high', 'medium', 'low'] else 'high',
                    'source': 'pms',
                    'delivery_mode': 'classroom',
                    'justification': _("Imported from PMS Performance Appraisal Gap Assessment."),
                })
                count += 1

        self.env['eds.integration.log'].create({
            'name': f"PMS-GAP-IMPORT-{self.cycle_id.name}",
            'system': 'pms',
            'direction': 'inbound',
            'status': 'success',
            'error_message': f"Imported {count} TNA gap entries from PMS file.",
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('PMS Import Complete'),
                'message': _('Successfully imported %d gap records into TNA cycle %s.') % (count, self.cycle_id.name),
                'sticky': False,
            }
        }

class EdsPayrollPayload(models.Model):
    _name = 'eds.payroll.payload'
    _description = 'EDS Payroll Cost Recovery / Deduction Payload'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Payload Reference', required=True, default=lambda self: _('New'))
    payload_type = fields.Selection([
        ('cost_recovery', 'Training Cost Recovery'),
        ('sponsorship_recovery', 'Sponsorship Bond Breach Recovery'),
    ], string='Payload Type', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Recovery Amount', currency_field='currency_id', required=True, tracking=True)
    effective_date = fields.Date(string='Effective Payroll Date', default=fields.Date.context_today, required=True)
    source_ref = fields.Char(string='Source Record Ref (Sponsorship / Course)', required=True)
    waiver_authority = fields.Text(string='CEO Waiver Authority Notes')
    state = fields.Selection([
        ('pending', 'Pending Transfer to Payroll'),
        ('transferred', 'Transferred to Payroll'),
        ('processed', 'Processed / Deducted'),
    ], string='Status', default='pending', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.payroll.payload') or _('New')
        return super(EdsPayrollPayload, self).create(vals_list)

    def action_transfer_to_payroll(self):
        for rec in self:
            rec.state = 'transferred'
            self.env['eds.integration.log'].create({
                'name': f"PAYROLL-PAYLOAD-{rec.name}",
                'system': 'payroll',
                'direction': 'outbound',
                'status': 'success',
                'error_message': f"Cost recovery payload {rec.name} for {rec.employee_id.name} ({rec.amount}) transferred to Payroll queue.",
            })
