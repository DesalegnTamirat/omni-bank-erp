# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsInductionProgram(models.Model):
    _name = 'eds.induction.program'
    _description = 'Induction & Onboarding Program'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Program Title', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    program_type = fields.Selection([
        ('blended', 'Blended (Classroom + E-Learning)'),
        ('classroom', 'Classroom Workshop'),
        ('elearning', 'Digital / E-Learning'),
    ], string='Delivery Format', required=True, default='blended', tracking=True)
    
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='End Date', required=True, tracking=True)
    coordinator_id = fields.Many2one('hr.employee', string='Induction Coordinator', required=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    participant_ids = fields.One2many('eds.induction.participant', 'program_id', string='Enrolled New Hires')
    checklist_ids = fields.One2many('eds.induction.checklist', 'program_id', string='Line Manager Onboarding Checklist')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.induction.program') or _('New')
        return super().create(vals_list)

    def action_schedule(self):
        for rec in self:
            rec.write({'state': 'scheduled'})
            rec.message_post(body=_('Induction program scheduled.'))

    def action_start(self):
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('Induction program in progress.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('Induction program completed.'))


class EdsInductionParticipant(models.Model):
    _name = 'eds.induction.participant'
    _description = 'Induction Program Participant'

    program_id = fields.Many2one('eds.induction.program', string='Induction Program', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='New Hire Employee', required=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True)
    completion_date = fields.Date(string='Completion Date')
    status = fields.Selection([
        ('enrolled', 'Enrolled'),
        ('completed', 'Completed'),
        ('failed', 'Incomplete / Pending'),
    ], string='Completion Status', default='enrolled')


class EdsInductionChecklist(models.Model):
    _name = 'eds.induction.checklist'
    _description = 'Line Manager Onboarding Checklist Task'

    program_id = fields.Many2one('eds.induction.program', string='Induction Program', required=True, ondelete='cascade')
    task_name = fields.Char(string='Onboarding Task', required=True)
    assigned_to = fields.Selection([
        ('line_manager', 'Line Manager'),
        ('hr_officer', 'HR Officer'),
        ('it_support', 'IT & Systems Support'),
        ('buddy', 'Assigned Buddy'),
    ], string='Responsible Role', default='line_manager', required=True)
    is_done = fields.Boolean(string='Completed', default=False)
    done_date = fields.Date(string='Completion Date')
