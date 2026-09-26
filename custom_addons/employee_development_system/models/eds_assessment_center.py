# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsAssessmentCenterBatch(models.Model):
    """Assessment Center exercise batch & candidate evaluation (FREDS060 - FREDS061)."""
    _name = 'eds.assessment.center.batch'
    _description = 'Assessment Center Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    title = fields.Char(string='Assessment Center Name', required=True, tracking=True)
    target_role_level = fields.Selection([
        ('leadership', 'Leadership / Executive Level'),
        ('management', 'Branch & Department Managerial Level'),
        ('professional', 'Senior Professional / Specialist Level'),
        ('graduate', 'Management Trainee / Graduate Level'),
    ], string='Target Role Level', default='management', required=True, tracking=True)
    date_start = fields.Date(string='Start Date', required=True, tracking=True)
    date_end = fields.Date(string='End Date', required=True, tracking=True)
    lead_assessor_id = fields.Many2one('hr.employee', string='Lead Assessor / Facilitator', tracking=True)
    candidate_line_ids = fields.One2many(
        'eds.assessment.center.candidate', 'batch_id', string='Assessed Candidates')
    candidate_count = fields.Integer(string='Candidate Count', compute='_compute_counts')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('ongoing', 'In Session'),
        ('evaluated', 'Evaluations Finalized'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    notes = fields.Text(string='Assessment Methodologies & Simulation Exercises')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('candidate_line_ids')
    def _compute_counts(self):
        for rec in self:
            rec.candidate_count = len(rec.candidate_line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.assessment.center.batch') or _('New')
        return super().create(vals_list)

    def action_schedule(self):
        for rec in self:
            rec.state = 'scheduled'

    def action_start(self):
        for rec in self:
            rec.state = 'ongoing'

    def action_finalize(self):
        for rec in self:
            rec.state = 'evaluated'
            rec.message_post(body=_("Assessment center ratings finalized."))


class EdsAssessmentCenterCandidate(models.Model):
    """Candidate scorecard within an Assessment Center batch."""
    _name = 'eds.assessment.center.candidate'
    _description = 'Assessment Center Candidate Scorecard'

    batch_id = fields.Many2one(
        'eds.assessment.center.batch', string='Assessment Center Batch', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Candidate Employee', required=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', readonly=True)
    job_id = fields.Many2one('hr.job', related='employee_id.job_id', readonly=True)
    overall_score = fields.Float(string='Overall Score (%)', default=0.0)
    readiness_rating = fields.Selection([
        ('ready_now', 'Ready Now (High Potential)'),
        ('ready_1yr', 'Ready in 1 Year with Development'),
        ('ready_2yr', 'Ready in 2-3 Years'),
        ('not_ready', 'Significant Gap / Not Ready'),
    ], string='Readiness Assessment', default='ready_1yr', required=True)
    strengths = fields.Text(string='Demonstrated Strengths')
    development_needs = fields.Text(string='Recommended Development Interventions')
    assessor_notes = fields.Text(string='Assessor Observations & Simulation Feedback')
