# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SuccessionDevelopmentPlan(models.Model):
    """
    Successor Development Plan (FR-SDP-002, FR-SDP-006).
    Targeted development interventions specifically for succession candidates
    to close their competency and readiness gaps and move towards 'Ready Now'.
    Separate from the general IDP in competency_management.
    """
    _name = 'succession.development.plan'
    _description = 'Succession: Successor Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    candidate_id = fields.Many2one(
        'succession.candidate', string='Succession Candidate',
        required=True, tracking=True, ondelete='cascade')
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        related='candidate_id.employee_id', store=True, readonly=True)
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Target Critical Position',
        related='candidate_id.critical_position_id', store=True, readonly=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True, readonly=True)

    # --- Plan Details ---
    plan_year = fields.Integer(
        string='Plan Year', default=lambda self: fields.Date.today().year, store=True)
    target_readiness = fields.Selection([
        ('ready_now', 'Ready Now'),
        ('ready_1_2_yrs', 'Ready in 1-2 Years'),
    ], string='Target Readiness at End of Plan', default='ready_1_2_yrs', tracking=True)
    start_date = fields.Date(string='Plan Start Date')
    end_date = fields.Date(string='Plan End Date')

    # --- Global Prioritization (FR-SDP-004) ---
    business_impact_score = fields.Integer(
        string='Business Impact Score (1-10)', default=5, tracking=True,
        help='Score used to prioritize this intervention across the bank.')
    urgency_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical (Immediate action)'),
    ], string='Urgency Level', default='medium', tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    notes = fields.Text(string='Development Focus / Notes')
    overall_progress = fields.Integer(
        string='Overall Progress (%)', compute='_compute_overall_progress', store=True)

    development_activity_ids = fields.One2many(
        'succession.development.activity', 'plan_id',
        string='Development Activities')
    activity_count = fields.Integer(
        string='Activities', compute='_compute_activity_count')

    @api.depends('development_activity_ids', 'development_activity_ids.progress_percent')
    def _compute_overall_progress(self):
        for rec in self:
            activities = rec.development_activity_ids
            if activities:
                rec.overall_progress = int(
                    sum(a.progress_percent for a in activities) / len(activities))
            else:
                rec.overall_progress = 0

    @api.depends('development_activity_ids')
    def _compute_activity_count(self):
        for rec in self:
            rec.activity_count = len(rec.development_activity_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name:
                rec.name = self.env['ir.sequence'].sudo().next_by_code(
                    'succession.development.plan') or 'SDP-%s' % rec.id
        return records

    def action_activate(self):
        for rec in self:
            if not rec.development_activity_ids:
                raise ValidationError(
                    _('Add at least one development activity before activating the plan.'))
            rec.with_context(force_write=True).write({'state': 'active'})
            rec.message_post(body=_('Successor Development Plan %s activated.') % rec.name)

    def action_complete(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'completed'})
            rec.message_post(body=_('Successor Development Plan %s marked as completed.') % rec.name)

    def action_cancel(self):
        self.with_context(force_write=True).write({'state': 'cancelled'})


class SuccessionDevelopmentActivity(models.Model):
    """
    A single development activity inside a Successor Development Plan.
    Mirrors the structure of competency.idp.activity but scoped
    strictly to succession development.
    """
    _name = 'succession.development.activity'
    _description = 'Succession Development Activity'
    _order = 'target_date, id'

    plan_id = fields.Many2one(
        'succession.development.plan', string='Development Plan',
        required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Target Competency / Gap',
        help='The specific competency gap this activity is designed to address.')
    activity_description = fields.Text(
        string='Development Activity', required=True)
    activity_type = fields.Selection([
        ('training', 'Formal Training / LMS'),
        ('mentoring', 'Mentoring by Senior Leader'),
        ('coaching', 'Executive Coaching'),
        ('stretch_assignment', 'Stretch / Acting Assignment'),
        ('job_rotation', 'Job Rotation'),
        ('formal_education', 'Formal Education / Certification'),
        ('conference', 'Conference / Networking'),
        ('self_study', 'Self-Study / Research'),
    ], string='Activity Type', required=True, default='training')
    start_date = fields.Date(string='Start Date', required=True)
    target_date = fields.Date(string='Target Completion Date', required=True)
    progress_percent = fields.Integer(string='Progress (%)', default=0)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned')

    # --- FR-SDP-005: Annual Development Plan Integration ---
    outcome_notes = fields.Text(string='Outcome / Evidence')

    @api.constrains('progress_percent')
    def _check_progress(self):
        for rec in self:
            if not (0 <= rec.progress_percent <= 100):
                raise ValidationError(_('Progress must be between 0 and 100%.'))
