# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsSelfDevelopmentActivity(models.Model):
    _name = 'eds.self.development.activity'
    _description = 'Self-Directed Development Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'completion_date desc, id desc'

    name = fields.Char(string='Activity Title', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True)
    
    activity_type = fields.Selection([
        ('certification', 'Professional Certification'),
        ('online_course', 'Online / Self-Paced Course'),
        ('workshop', 'External Workshop'),
        ('conference', 'Industry Conference'),
        ('coaching', 'Coaching Received'),
        ('mentoring', 'Mentoring Received'),
        ('reading_research', 'Self-Directed Reading & Research'),
    ], string='Activity Category', required=True, default='online_course', tracking=True)
    
    completion_date = fields.Date(string='Completion Date', default=fields.Date.context_today, required=True, tracking=True)
    hours_spent = fields.Float(string='Hours Spent', default=1.0, required=True, tracking=True)
    description = fields.Text(string='Description & Key Learnings', required=True)
    evidence_file = fields.Binary(string='Supporting Evidence Document', attachment=True)
    evidence_filename = fields.Char(string='Evidence Filename')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Verification'),
        ('verified', 'Verified & Recorded'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    verified_by_id = fields.Many2one('res.users', string='Verified By', readonly=True, tracking=True)

    def action_submit(self):
        for rec in self:
            rec.write({'state': 'submitted'})
            rec.message_post(body=_('Self-development activity submitted for verification.'))

    def action_verify(self):
        for rec in self:
            rec.write({
                'state': 'verified',
                'verified_by_id': self.env.user.id
            })
            rec.message_post(body=_('Self-development activity verified.'))
