# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyIDP(models.Model):
    """Individual Development Plan derived from assessment gaps (FR-COM-020..028)."""
    _name = 'competency.idp'
    _description = 'Competency Individual Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    assessment_id = fields.Many2one('competency.assessment', string='Source Assessment', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('active', 'Active'),
        ('completed', 'Completed'),
    ], string='Status', default='draft', tracking=True)
    goal_ids = fields.One2many('competency.idp.activity', 'idp_id', string='Development Activities')
    checkpoint_ids = fields.One2many('competency.idp.checkpoint', 'idp_id', string='Review Checkpoints')
    mandatory = fields.Boolean(
        string='Mandatory IDP', compute='_compute_mandatory', store=True,
        help='Auto-flagged when a competency gap exists (FR-COM-027).')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('assessment_id', 'assessment_id.average_gap')
    def _compute_mandatory(self):
        for rec in self:
            rec.mandatory = bool(rec.assessment_id and rec.assessment_id.average_gap > 0)

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): employee-created IDPs (FR-COM-020) must not depend on the user
        # having ir.sequence access.
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = self.env['ir.sequence'].sudo().next_by_code('competency.idp') or \
                    'IDP-%s' % record.id
        return records

    def action_submit(self):
        for rec in self:
            if not rec.goal_ids:
                raise ValidationError(_('Add at least one development activity before submitting.'))
            rec.state = 'submitted'
            rec.message_post(body=_('IDP %s submitted for approval.') % rec.name)

    def action_approve(self):
        """Supervisor approval (FR-COM-026)."""
        for rec in self:
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('IDP %s approved.') % rec.name)

    def action_start(self):
        self.write({'state': 'active'})

    def action_complete(self):
        self.write({'state': 'completed'})
        for rec in self:
            rec.message_post(body=_('IDP %s completed.') % rec.name)


class CompetencyIDPActivity(models.Model):
    """A development activity inside an IDP (FR-COM-021/022)."""
    _name = 'competency.idp.activity'
    _description = 'IDP Development Activity'

    idp_id = fields.Many2one('competency.idp', string='IDP', required=True, ondelete='cascade')
    goal = fields.Text(string='Development Goal', required=True)
    activity_type = fields.Selection([
        ('training', 'Training Program'),
        ('coaching', 'Coaching'),
        ('mentoring', 'Mentoring'),
        ('job_shadowing', 'Job Shadowing'),
        ('stretch_assignment', 'Stretch Assignment'),
        ('ojt', 'On-the-Job Learning'),
        ('self_study', 'Self-Study'),
        ('formal_education', 'Formal Education'),
    ], string='Activity Type', required=True, default='training')
    course_name = fields.Char(string='Course / Program')
    start_date = fields.Date(string='Start Date')
    target_end_date = fields.Date(string='Target End Date')
    progress_percent = fields.Integer(string='Progress (%)', default=0)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ], string='Status', default='planned')
    outcome = fields.Text(string='Outcome / Results')

    @api.constrains('progress_percent')
    def _check_progress(self):
        for rec in self:
            if rec.progress_percent < 0 or rec.progress_percent > 100:
                raise ValidationError(_('Progress must be between 0 and 100%.'))


class CompetencyIDPCheckpoint(models.Model):
    """Scheduled review checkpoint (FR-COM-024/025)."""
    _name = 'competency.idp.checkpoint'
    _description = 'IDP Review Checkpoint'

    idp_id = fields.Many2one('competency.idp', string='IDP', required=True, ondelete='cascade')
    scheduled_date = fields.Date(string='Scheduled Review Date', required=True)
    status = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('missed', 'Missed'),
    ], string='Status', default='scheduled')
    completed_date = fields.Date(string='Completed Date')
    notes = fields.Text(string='Review Notes')
