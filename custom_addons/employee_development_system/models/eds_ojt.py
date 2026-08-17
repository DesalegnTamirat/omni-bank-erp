# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class EdsOjtAssignment(models.Model):
    _name = 'eds.ojt.assignment'
    _description = 'On-the-Job Training Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Assignment Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Trainee Employee', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', store=True)
    assignment_type = fields.Selection([
        ('new_hire', 'New Hire Onboarding'),
        ('transfer', 'Internal Transfer'),
        ('promotion', 'Promotion Reassignment'),
        ('reassignment', 'Role Reassignment'),
    ], string='Assignment Reason', required=True, default='new_hire', tracking=True)
    
    supervisor_id = fields.Many2one('hr.employee', string='OJT Supervisor / Buddy', required=True, tracking=True)
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='Planned End Date', required=True, tracking=True)
    duration_months = fields.Integer(string='Duration (Months)', compute='_compute_duration', store=True)
    
    competency_id = fields.Many2one('competency.competency', string='Target Competency', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('evaluated', 'Evaluated'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    notes = fields.Text(string='Objectives & Notes')
    progress_ids = fields.One2many('eds.ojt.progress', 'assignment_id', string='Checklist & Progress')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.ojt.assignment') or _('New')
            if 'end_date' not in vals and vals.get('start_date'):
                start = fields.Date.from_string(vals['start_date'])
                vals['end_date'] = start + timedelta(days=90)
        return super().create(vals_list)

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                days = (rec.end_date - rec.start_date).days
                rec.duration_months = max(1, round(days / 30))
            else:
                rec.duration_months = 3

    def action_start(self):
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('OJT assignment started.'))

    def action_evaluate(self):
        for rec in self:
            rec.write({'state': 'evaluated'})
            rec.message_post(body=_('OJT supervisor evaluation submitted.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('OJT assignment completed successfully.'))


class EdsOjtProgress(models.Model):
    _name = 'eds.ojt.progress'
    _description = 'OJT Progress & Supervisor Evaluation'

    assignment_id = fields.Many2one('eds.ojt.assignment', string='OJT Assignment', required=True, ondelete='cascade')
    date = fields.Date(string='Evaluation Date', default=fields.Date.context_today, required=True)
    checklist_item = fields.Char(string='Checklist / Learning Module', required=True)
    is_completed = fields.Boolean(string='Completed', default=False)
    trainee_feedback = fields.Text(string='Trainee Self-Assessment')
    supervisor_evaluation = fields.Selection([
        ('exceeds', 'Exceeds Expectations'),
        ('meets', 'Meets Expectations'),
        ('below', 'Needs Improvement'),
    ], string='Supervisor Rating', default='meets')
    comments = fields.Text(string='Supervisor Comments')
