# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

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
    details = fields.Text(string='Transaction Details / Message')
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
            # Contract/Interface stub for LMS Sync
            rec.sync_state = 'synced'
            rec.last_sync_date = fields.Datetime.now()
            self.env['eds.integration.log'].create({
                'name': f"LMS-SYNC-{rec.course_id.code}",
                'system': 'lms',
                'direction': 'outbound',
                'status': 'success',
                'details': f"Course {rec.course_id.name} payload queued for LMS sync dispatch.",
            })

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
                'details': f"Cost recovery payload {rec.name} for {rec.employee_id.name} ({rec.amount}) transferred to Payroll queue.",
            })
