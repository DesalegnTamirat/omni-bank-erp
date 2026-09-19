# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class DisciplineInvestigation(models.Model):
    _name = 'discipline.investigation'
    _description = 'Disciplinary Investigation & Findings'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'investigation_date desc, id desc'

    name = fields.Char(string='Investigation Ref', required=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', store=True, readonly=True)
    investigator_id = fields.Many2one('res.users', string='Lead Investigator / Auditor', required=True, default=lambda self: self.env.user, tracking=True)
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)

    summary_findings = fields.Text(string='Summary of Findings', required=True, tracking=True)
    witness_statements = fields.Text(string='Witness Statements & Interviews')
    investigator_recommendation = fields.Text(string='Investigator Recommendation', required=True)

    # Document & Evidence Attachments (FR-DIS-014)
    report_file = fields.Binary(string='Investigation Report Document', attachment=True)
    report_filename = fields.Char(string='Report Filename')
    evidence_file = fields.Binary(string='Evidence File', attachment=True)
    evidence_filename = fields.Char(string='Evidence Filename')
    statement_file = fields.Binary(string='Witness Statement Document', attachment=True)
    statement_filename = fields.Char(string='Statement Filename')

    state = fields.Selection([
        ('draft', 'Draft Findings'),
        ('submitted', 'Submitted to Case'),
        ('approved', 'Reviewed & Accepted'),
    ], string='Status', default='draft', required=True, tracking=True)

    def action_submit_findings(self):
        for rec in self:
            rec.write({'state': 'submitted'})
            rec.case_id.message_post(body=_('Investigation findings submitted by investigator %s.') % rec.investigator_id.name)

    def action_accept_findings(self):
        for rec in self:
            rec.write({'state': 'approved'})
            rec.case_id.message_post(body=_('Investigation findings officially reviewed and accepted.'))
