# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsLearningEvent(models.Model):
    _name = 'eds.learning.event'
    _description = 'Knowledge Sharing Event & Workshop'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_datetime desc, id desc'

    name = fields.Char(string='Event Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    topic = fields.Char(string='Event Topic / Title', required=True, tracking=True)
    initiator_type = fields.Selection([
        ('ppdd', 'PPDD / L&D Initiated'),
        ('business_unit', 'Business Unit Initiated'),
    ], string='Initiating Body', required=True, default='business_unit', tracking=True)
    
    event_type = fields.Selection([
        ('workshop', 'Interactive Workshop'),
        ('seminar', 'Seminar / Webinar'),
        ('conference', 'Conference'),
        ('knowledge_sharing', 'Internal Knowledge Sharing Session'),
    ], string='Event Type', required=True, default='knowledge_sharing', tracking=True)
    
    start_datetime = fields.Datetime(string='Start Date & Time', required=True, tracking=True)
    end_datetime = fields.Datetime(string='End Date & Time', required=True, tracking=True)
    location = fields.Char(string='Venue / Virtual Link', required=True)
    
    facilitator_ids = fields.Many2many('hr.employee', 'eds_event_facilitator_rel', 'event_id', 'employee_id', string='Facilitators / Presenters')
    attendee_ids = fields.Many2many('hr.employee', 'eds_event_attendee_rel', 'event_id', 'employee_id', string='Enrolled Participants')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('conducted', 'Conducted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    outcomes_summary = fields.Text(string='Key Learning Outcomes & Takeaways')
    attachment_ids = fields.Many2many('ir.attachment', 'eds_event_attachment_rel', 'event_id', 'attachment_id', string='Learning Materials')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.learning.event') or _('New')
        return super().create(vals_list)

    def action_schedule(self):
        for rec in self:
            rec.write({'state': 'scheduled'})
            rec.message_post(body=_('Learning event scheduled.'))

    def action_conduct(self):
        for rec in self:
            rec.write({'state': 'conducted'})
            rec.message_post(body=_('Learning event conducted.'))
