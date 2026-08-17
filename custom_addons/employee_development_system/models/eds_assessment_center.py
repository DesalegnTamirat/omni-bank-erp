# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EdsAssessmentCenter(models.Model):
    _name = 'eds.assessment.center'
    _description = 'Assessment Center Program'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Program Title', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    target_job_id = fields.Many2one('hr.job', string='Target Role / Job Position', required=True, tracking=True)
    assessment_tool = fields.Selection([
        ('simulation', 'Role-Play & Simulation Exercise'),
        ('case_study', 'Business Case Study'),
        ('in_tray', 'In-Tray / E-Tray Exercise'),
        ('presentation', 'Executive Presentation'),
        ('psychometric', 'Psychometric Battery'),
        ('blended', 'Blended Assessment Suite'),
    ], string='Assessment Tool Format', default='blended', required=True, tracking=True)
    
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='End Date', required=True, tracking=True)
    assessor_ids = fields.Many2many('hr.employee', 'eds_ac_assessor_rel', 'ac_id', 'employee_id', string='Assigned Assessors', required=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    session_ids = fields.One2many('eds.assessment.center.session', 'ac_id', string='Assessment Sessions')
    result_ids = fields.One2many('eds.assessment.center.result', 'ac_id', string='Candidate Evaluations & Scores')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.assessment.center') or _('New')
        return super().create(vals_list)

    def action_schedule(self):
        for rec in self:
            rec.write({'state': 'scheduled'})
            rec.message_post(body=_('Assessment center program scheduled.'))

    def action_start(self):
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('Assessment center program in progress.'))

    def action_complete(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('Assessment center program completed.'))

    @api.model
    def get_assessment_center_results(self, employee_id):
        """Public API returning candidate assessment center score history for recruitment/promotion."""
        results = self.env['eds.assessment.center.result'].search([('candidate_id', '=', employee_id)])
        return [{
            'id': res.id,
            'ac_name': res.ac_id.name,
            'target_job': res.ac_id.target_job_id.name,
            'score': res.overall_score,
            'recommendation': res.recommendation,
            'evaluation_date': res.evaluation_date,
        } for res in results]


class EdsAssessmentCenterSession(models.Model):
    _name = 'eds.assessment.center.session'
    _description = 'Assessment Center Session Scheduling'

    ac_id = fields.Many2one('eds.assessment.center', string='Assessment Center Program', required=True, ondelete='cascade')
    name = fields.Char(string='Session Title', required=True)
    session_datetime = fields.Datetime(string='Session Date & Time', required=True)
    location = fields.Char(string='Venue / Room', required=True)
    exercise_summary = fields.Text(string='Exercise Instructions')


class EdsAssessmentCenterResult(models.Model):
    _name = 'eds.assessment.center.result'
    _description = 'Assessment Center Confidential Result'
    _inherit = ['mail.thread']

    ac_id = fields.Many2one('eds.assessment.center', string='Assessment Center Program', required=True, ondelete='cascade')
    candidate_id = fields.Many2one('hr.employee', string='Candidate Employee', required=True, tracking=True)
    evaluation_date = fields.Date(string='Evaluation Date', default=fields.Date.context_today, required=True)
    
    overall_score = fields.Float(string='Consensus Overall Score (%)', required=True, tracking=True)
    recommendation = fields.Selection([
        ('recommended', 'Ready for Appointment / Promotion'),
        ('recommended_with_dev', 'Recommended with Development Plan'),
        ('not_recommended', 'Not Recommended at Present'),
    ], string='Consensus Decision', default='recommended_with_dev', required=True, tracking=True)
    
    strengths = fields.Text(string='Key Strengths Observed')
    development_areas = fields.Text(string='Key Development Needs')
    confidential_notes = fields.Text(string='Confidential Assessor Notes')
