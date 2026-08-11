# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyAssessmentCycle(models.Model):
    """Scheduled competency assessment cycle (/010, )."""
    _name = 'competency.assessment.cycle'
    _description = 'Competency Assessment Cycle'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Cycle Name', required=True)
    period_start = fields.Date(string='Period Start', required=True, default=fields.Date.context_today)
    period_end = fields.Date(string='Period End')
    assessment_deadline = fields.Date(string='Assessment Deadline')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('in_review', 'In Review'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True)
    assessment_ids = fields.One2many('competency.assessment', 'cycle_id', string='Assessments')
    assessment_count = fields.Integer(string='Assessments', compute='_compute_assessment_count')
    notes = fields.Text(string='Notes')

    @api.depends('assessment_ids')
    def _compute_assessment_count(self):
        for rec in self:
            rec.assessment_count = len(rec.assessment_ids)

    @api.constrains('period_start', 'period_end')
    def _check_periods(self):
        for rec in self:
            if rec.period_end and rec.period_start and rec.period_end < rec.period_start:
                raise ValidationError(_('Period End cannot be before Period Start.'))

    def action_start(self):
        """Draft -> Open."""
        self.write({'state': 'open'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s opened.') % rec.name)

    def action_start_review(self):
        self.write({'state': 'in_review'})

    def action_close(self):
        self.write({'state': 'closed'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s closed.') % rec.name)


class CompetencyAssessment(models.Model):
    """A single employee assessment within a cycle (..019, ..006)."""
    _name = 'competency.assessment'
    _description = 'Competency Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Cycle', required=True,
        ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    assessor_id = fields.Many2one('res.users', string='Assessor', default=lambda self: self.env.user)
    assessment_type = fields.Selection([
        ('self', 'Self-Assessment'),
        ('supervisor', 'Supervisor Assessment'),
        ('multi_rater', 'Multi-Rater (360)'),
        ('skills_test', 'Skills Test / Examination'),
    ], string='Assessment Type', default='self', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('supervisor_review', 'Supervisor Review'),
        ('hr_verified', 'HR Verified'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', tracking=True)
    line_ids = fields.One2many('competency.assessment.line', 'assessment_id', string='Competency Ratings')
    average_gap = fields.Float(string='Average Gap', compute='_compute_average_gap', store=True)
    is_locked = fields.Boolean(string='Locked', compute='_compute_is_locked')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids', 'line_ids.gap')
    def _compute_average_gap(self):
        for rec in self:
            gaps = [line.gap for line in rec.line_ids if line.gap is not None]
            rec.average_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

    @api.depends('state')
    def _compute_is_locked(self):
        for rec in self:
            rec.is_locked = rec.state == 'locked'

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): self-assessment creation (/012) must not depend on the
        # employee having ir.sequence access.
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = self.env['ir.sequence'].sudo().next_by_code('competency.assessment') or \
                    'CMP-A-%s' % record.id
        return records

    def action_auto_fill_lines(self):
        """Populate rating lines from the employee's approved role-competency mapping ."""
        self.ensure_one()
        if self.line_ids:
            raise UserError(_('This assessment already has rating lines.'))
        employee = self.employee_id
        if not employee or not employee.job_position:
            raise UserError(_('The employee has no Job Position set; auto-fill is not possible.'))
        mapping = self.env['competency.role.mapping'].search([
            ('job_position_id', '=', employee.job_position.id),
            ('state', '=', 'approved'),
        ], limit=1)
        if not mapping:
            raise UserError(_('No approved role-competency mapping found for job %s.') % employee.job_position.name)
        Line = self.env['competency.assessment.line']
        lines = []
        for mline in mapping.line_ids:
            lines.append((0, 0, {
                'competency_id': mline.competency_id.id,
                'current_level': '1',
                'required_level': mline.required_proficiency,
            }))
        self.write({'line_ids': lines})
        self.message_post(
            body=_('Rating lines auto-filled from approved role mapping %s.') % mapping.mapping_name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lines Added'),
                'message': _('%s competency lines were added.') % len(mapping.line_ids),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_submit(self):
        """Draft -> Submitted ( workflow)."""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one competency rating line before submitting.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Assessment %s submitted for review.') % rec.name)

    def action_supervisor_review(self):
        self.write({'state': 'supervisor_review'})

    def action_hr_verify(self):
        self.write({'state': 'hr_verified'})

    def action_approve(self):
        """Approved -> final approval ."""
        for rec in self:
            rec.state = 'approved'
            rec.message_post(body=_('Assessment %s approved.') % rec.name)

    def action_lock(self):
        """Lock finalized assessment against further modification ."""
        for rec in self:
            rec.state = 'locked'
            rec.message_post(body=_('Assessment %s locked.') % rec.name)

    def action_unlock(self):
        """Authorized override with justification ."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('competency_management.group_competency_admin')):
            raise UserError(_('Only Competency Administrators can unlock finalized assessments.'))
        if not self.notes:
            raise UserError(_('Provide a justification in Notes before unlocking .'))
        self.state = 'approved'
        self.message_post(body=_('Assessment %s unlocked by %s.') % (self.name, self.env.user.name))


class CompetencyAssessmentLine(models.Model):
    """One competency rating inside an assessment (..017)."""
    _name = 'competency.assessment.line'
    _description = 'Competency Assessment Line'

    assessment_id = fields.Many2one(
        'competency.assessment', string='Assessment', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    current_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Current Proficiency', required=True, default='1')
    required_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    gap = fields.Integer(string='Gap', compute='_compute_gap', store=True,
                         help='Required minus Current proficiency (positive = development gap).')
    comments = fields.Text(string='Comments')
    evidence_attachment_ids = fields.Many2many('ir.attachment', string='Supporting Evidence')

    @api.depends('current_level', 'required_level')
    def _compute_gap(self):
        for rec in self:
            rec.gap = int(rec.required_level or 0) - int(rec.current_level or 0)

    _sql_constraints = [
        ('assessment_competency_uniq', 'unique(assessment_id, competency_id)',
         'This competency is already rated in the assessment!'),
    ]
