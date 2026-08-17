# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsMentoringProgram(models.Model):
    _name = 'eds.mentoring.program'
    _description = 'Leadership & Career Mentoring Program'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Program Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    mentee_id = fields.Many2one('hr.employee', string='Mentee Employee', required=True, tracking=True)
    mentor_type = fields.Selection([
        ('internal', 'Internal Senior Leader'),
        ('external', 'External Industry Expert'),
    ], string='Mentor Type', required=True, default='internal', tracking=True)
    
    internal_mentor_id = fields.Many2one('hr.employee', string='Internal Mentor', tracking=True)
    external_mentor_name = fields.Char(string='External Mentor Name / Firm', tracking=True)
    target_position_id = fields.Many2one('hr.job', string='Target Succession Role', tracking=True)
    
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='Target Completion Date', required=True, tracking=True)
    objectives = fields.Text(string='Mentoring Objectives & Key Results', required=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('review', 'In Review'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    review_ids = fields.One2many('eds.mentoring.review', 'program_id', string='Periodic Progress Reviews')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.mentoring.program') or _('New')
        return super().create(vals_list)

    def action_activate(self):
        for rec in self:
            rec.write({'state': 'active'})
            rec.message_post(body=_('Mentoring program activated.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('Mentoring program completed.'))


class EdsMentoringReview(models.Model):
    _name = 'eds.mentoring.review'
    _description = 'Periodic Mentoring Review'

    program_id = fields.Many2one('eds.mentoring.program', string='Mentoring Program', required=True, ondelete='cascade')
    review_date = fields.Date(string='Review Date', default=fields.Date.context_today, required=True)
    mentor_feedback = fields.Text(string='Mentor Feedback', required=True)
    mentee_feedback = fields.Text(string='Mentee Feedback')
    milestones_achieved = fields.Text(string='Milestones & Capabilities Developed')
    overall_rating = fields.Selection([
        ('exceeds', 'Exceeds Expectations'),
        ('meets', 'Meets Expectations'),
        ('below', 'Needs Improvement'),
    ], string='Overall Rating', default='meets')
