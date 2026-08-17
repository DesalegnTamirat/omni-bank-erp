# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class EdsIndividualDevelopmentPlan(models.Model):
    _name = 'eds.individual.development.plan'
    _description = 'Individual Development Plan (IDP/PDP)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='IDP Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True)
    job_id = fields.Many2one('hr.job', string='Current Job Position', related='employee_id.job_id', store=True)
    target_job_id = fields.Many2one('hr.job', string='Target Succession Job Position', tracking=True)
    
    pip_reference = fields.Char(string='PIP Reference / Audit Link', tracking=True)
    competency_gap_notes = fields.Text(string='Competency Gap Assessment & Analysis', tracking=True)
    career_objectives = fields.Text(string='Career & Development Objectives', required=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    review_frequency = fields.Selection([
        ('monthly', 'Monthly Review'),
        ('quarterly', 'Quarterly Review'),
        ('semi_annual', 'Semi-Annual Review'),
    ], string='Review Frequency', default='quarterly', required=True, tracking=True)
    
    next_review_date = fields.Date(string='Next Scheduled Review Date', required=True, tracking=True)
    milestone_ids = fields.One2many('eds.idp.activity', 'idp_id', string='Planned Learning & Action Milestones')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.individual.development.plan') or _('New')
            if 'next_review_date' not in vals:
                vals['next_review_date'] = fields.Date.context_today(self) + timedelta(days=90)
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            rec.write({'state': 'submitted'})
            rec.message_post(body=_('IDP submitted for manager review.'))

    def action_approve(self):
        for rec in self:
            rec.write({'state': 'approved'})
            rec.message_post(body=_('IDP approved.'))

    def action_start(self):
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('IDP in progress.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('IDP completed.'))

    @api.model
    def _cron_idp_review_reminder(self):
        """Send automated activity and email reminders for upcoming IDP reviews."""
        today = fields.Date.today()
        due_idps = self.search([
            ('state', 'in', ['approved', 'in_progress']),
            ('next_review_date', '<=', today + timedelta(days=7))
        ])
        for idp in due_idps:
            idp.message_post(body=_('Reminder: IDP review is due on %s for %s.') % (idp.next_review_date, idp.employee_id.name))


class EdsIdpActivity(models.Model):
    _name = 'eds.idp.activity'
    _description = 'IDP Learning Activity & Milestone'

    idp_id = fields.Many2one('eds.individual.development.plan', string='IDP Reference', required=True, ondelete='cascade')
    name = fields.Char(string='Activity Title', required=True)
    activity_type = fields.Selection([
        ('training', 'Formal Training Course'),
        ('ojt', 'On-the-Job Project'),
        ('coaching', 'Coaching / Mentoring'),
        ('self_study', 'Self-Directed Study'),
        ('certification', 'Professional Certification'),
    ], string='Activity Type', required=True, default='training')
    target_date = fields.Date(string='Target Completion Date', required=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
    ], string='Status', default='planned')
    completion_date = fields.Date(string='Actual Completion Date')
