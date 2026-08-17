# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsCoachingPlan(models.Model):
    _name = 'eds.coaching.plan'
    _description = 'Executive & Performance Coaching Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Plan Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    coachee_id = fields.Many2one('hr.employee', string='Coachee Employee', required=True, tracking=True)
    coach_type = fields.Selection([
        ('internal', 'Internal Certified Coach'),
        ('external', 'External Professional Coach'),
    ], string='Coach Type', required=True, default='internal', tracking=True)
    
    internal_coach_id = fields.Many2one('hr.employee', string='Internal Coach', tracking=True)
    external_coach_name = fields.Char(string='External Coach / Vendor', tracking=True)
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='Target End Date', required=True, tracking=True)
    
    objectives = fields.Text(string='Coaching Objectives & Desired Outcomes', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    session_ids = fields.One2many('eds.coaching.session', 'coaching_plan_id', string='Coaching Sessions')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.coaching.plan') or _('New')
        return super().create(vals_list)

    def action_activate(self):
        for rec in self:
            rec.write({'state': 'active'})
            rec.message_post(body=_('Coaching plan activated.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('Coaching plan completed.'))


class EdsCoachingSession(models.Model):
    _name = 'eds.coaching.session'
    _description = 'Coaching Session Documentation'

    coaching_plan_id = fields.Many2one('eds.coaching.plan', string='Coaching Plan', required=True, ondelete='cascade')
    session_date = fields.Date(string='Session Date', default=fields.Date.context_today, required=True)
    duration_hours = fields.Float(string='Duration (Hours)', default=1.0, required=True)
    summary = fields.Text(string='Discussion Summary & Insights', required=True)
    action_items = fields.Text(string='Agreed Action Items')
    progress_rating = fields.Selection([
        ('1', 'Initial Phase'),
        ('2', 'Developing'),
        ('3', 'On Track'),
        ('4', 'Significant Progress'),
        ('5', 'Objective Achieved'),
    ], string='Progress Rating', default='3')
    next_session_date = fields.Date(string='Next Scheduled Session')
