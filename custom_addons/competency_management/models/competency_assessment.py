# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyAssessmentCycle(models.Model):
    """Scheduled competency assessment cycle /010,."""
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
        """Draft -> Open with notifications (FR-COM-045)."""
        self.with_context(force_write=True).write({'state': 'open'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s opened. Deadline: %s.') % (rec.name, rec.assessment_deadline or 'Not set'))
            # Schedule activity notifications for supervisors and employees in scope
            assessments = rec.assessment_ids
            for asm in assessments:
                if asm.employee_id and asm.employee_id.user_id:
                    asm.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('New Assessment Cycle Started: %s') % rec.name,
                        note=_('Assessment cycle %s is now open. Deadline is %s.') % (rec.name, rec.assessment_deadline or 'N/A'),
                        user_id=asm.employee_id.user_id.id,
                        date_deadline=rec.assessment_deadline or fields.Date.context_today(self),
                    )

    def action_start_review(self):
        self.with_context(force_write=True).write({'state': 'in_review'})

    def action_close(self):
        self.with_context(force_write=True).write({'state': 'closed'})
        for rec in self:
            rec.message_post(body=_('Assessment cycle %s closed.') % rec.name)

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'closed' and not force_write and not self.env.su:
                locked_fields = {'name', 'period_start', 'period_end', 'assessment_deadline'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("This assessment cycle (%s) is closed and cannot be edited.") % rec.name)
        return super().write(vals)


class CompetencyAssessment(models.Model):
    """A single employee assessment within a cycle (FR-COM-011, FR-COM-012)."""
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

    # 360 Multi-Rater extension fields (FR-COM-012, FR-ASM-002, FR-ASM-005)
    parent_assessment_id = fields.Many2one('competency.assessment', string='Parent 360 Assessment', ondelete='cascade', tracking=True)
    child_assessment_ids = fields.One2many('competency.assessment', 'parent_assessment_id', string='Rater Assessments')
    is_rater_assessment = fields.Boolean(string='Is Child Rater Assessment', default=False)
    rater_type = fields.Selection([
        ('self', 'Self'),
        ('peer', 'Peer'),
        ('subordinate', 'Subordinate'),
        ('supervisor', 'Supervisor'),
        ('other', 'Other'),
    ], string='Rater Type')
    rater_id = fields.Many2one('res.users', string='Rater User')
    is_anonymous = fields.Boolean(string='Anonymize 360 Feedback', default=False,
                                   help='Hide rater name from line managers for peer/subordinate 360 reviews (FR-ASM-002).')
    anonymized_rater_label = fields.Char(string='Display Rater Label', compute='_compute_anonymized_rater_label')

    @api.depends('is_anonymous', 'rater_type', 'rater_id')
    def _compute_anonymized_rater_label(self):
        for rec in self:
            if rec.is_anonymous and rec.rater_type in ('peer', 'subordinate'):
                rec.anonymized_rater_label = _("Anonymous 360 Rater (%s)") % (rec.rater_type.capitalize() if rec.rater_type else 'Peer')
            elif rec.rater_id:
                rec.anonymized_rater_label = rec.rater_id.name
            else:
                rec.anonymized_rater_label = _("Unassigned")

    def action_consolidate_multi_source(self):
        """Consolidate Self, Manager, 360 Feedback, and Skills Test scores into one achievement determination (FR-ASM-005)."""
        for parent in self:
            if not parent.employee_id:
                continue
            
            competency_scores = {}
            competency_reqs = {}
            
            # 1. Child 360 raters
            for child in parent.child_assessment_ids.filtered(lambda c: c.state in ('submitted', 'supervisor_review', 'hr_verified', 'approved', 'locked')):
                for line in child.line_ids:
                    cid = line.competency_id.id
                    competency_scores.setdefault(cid, []).append(int(line.current_level or 1))
                    competency_reqs[cid] = line.required_level
                    
            # 2. Skills Tests (FR-ASM-003)
            skills_tests = self.env['competency.skills.test'].search([('employee_id', '=', parent.employee_id.id)])
            for test in skills_tests:
                if test.verified_level:
                    cid = test.competency_id.id
                    competency_scores.setdefault(cid, []).append(int(test.verified_level))

            # Update line ratings
            for cid, score_list in competency_scores.items():
                avg_score = round(sum(score_list) / len(score_list))
                lvl_str = str(max(1, min(4, avg_score)))
                existing_line = parent.line_ids.filtered(lambda l: l.competency_id.id == cid)
                if existing_line:
                    existing_line.write({'current_level': lvl_str})
                else:
                    self.env['competency.assessment.line'].create({
                        'assessment_id': parent.id,
                        'competency_id': cid,
                        'current_level': lvl_str,
                        'required_level': competency_reqs.get(cid, '2'),
                    })
            parent.message_post(body=_("Multi-source assessment scores (360 feedback + Skills Tests) consolidated into final achievement levels."))

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
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = self.env['ir.sequence'].sudo().next_by_code('competency.assessment') or \
                    'CMP-A-%s' % record.id
        return records

    def action_auto_fill_lines(self):
        """Populate rating lines from the employee's approved role-competency mapping."""
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
        lines = []
        for mline in mapping.line_ids:
            lines.append((0, 0, {
                'competency_id': mline.competency_id.id,
                'current_level': '1',
                'required_level': mline.required_proficiency,
            }))
        self.write({'line_ids': lines})
        self.message_post(body=_('Rating lines auto-filled from approved role mapping %s.') % mapping.mapping_name)
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

    def compute_aggregate_360_ratings(self):
        return self.action_consolidate_multi_source()

    def _check_segregation_of_duties(self):
        """Segregation of duties guard: Block self-approval by subject, assessor, or creator (FR-COM-055)."""
        for rec in self:
            subject_user = rec.employee_id.user_id if rec.employee_id else False
            assessor_user = rec.assessor_id or False
            creator_user = rec.create_uid or False
            current_user = self.env.user
            
            if not self.env.su:
                if (subject_user and current_user == subject_user) or \
                   (assessor_user and current_user == assessor_user) or \
                   (creator_user and current_user == creator_user):
                    raise ValidationError(_("You cannot approve your own assessment/IDP. This action must be performed by a different authorized user (FR-COM-055)."))

    def action_submit(self):
        """Draft -> Submitted workflow with employee confirmation (FR-COM-047)."""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Add at least one competency rating line before submitting.'))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Assessment %s submitted for review.') % rec.name)
            
            if rec.employee_id and rec.employee_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Assessment Submitted: %s') % rec.name,
                    note=_('Your competency assessment %s has been submitted successfully.') % rec.name,
                    user_id=rec.employee_id.user_id.id,
                )

    def action_supervisor_review(self):
        """Submitted -> Supervisor Review with supervisor activity notification (FR-COM-048)."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'supervisor_review'})
            supervisor_user = rec.employee_id.parent_id.user_id if (rec.employee_id and rec.employee_id.parent_id) else False
            if supervisor_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Supervisor Review Needed: Assessment %s') % rec.name,
                    note=_('Please review and complete assessment for %s.') % rec.employee_id.name,
                    user_id=supervisor_user.id,
                    date_deadline=rec.cycle_id.assessment_deadline or fields.Date.context_today(self),
                )

    def action_hr_verify(self):
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'hr_verified'})

    def action_approve(self):
        """Approved -> final approval with Segregation of Duties guard (FR-COM-055)."""
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({'state': 'approved'})
            rec.message_post(body=_('Assessment %s approved.') % rec.name)

    def action_lock(self):
        """Lock finalized assessment against further modification."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'locked'})
            rec.message_post(body=_('Assessment %s locked.') % rec.name)

    def action_unlock(self):
        """Authorized override with justification."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('competency_management.group_competency_admin')):
            raise UserError(_('Only Competency Administrators can unlock finalized assessments.'))
        if not self.notes:
            raise UserError(_('Provide a justification in Notes before unlocking.'))
        self.with_context(force_write=True).write({'state': 'approved'})
        self.message_post(body=_('Assessment %s unlocked by %s.') % (self.name, self.env.user.name))

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'locked' and not force_write and not self.env.su:
                locked_fields = {'employee_id', 'cycle_id', 'assessment_type', 'assessor_id', 'line_ids', 'notes'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("Assessment %s is locked. Only Competency Administrators can unlock finalized assessments using the Unlock action.") % rec.name)
        return super().write(vals)

    @api.model
    def _cron_pending_assessment_reminders(self):
        """Daily cron: pending assessment reminders & overdue notifications (FR-COM-046, FR-COM-048)."""
        today = fields.Date.context_today(self)
        pending_assessments = self.search([
            ('state', 'in', ['draft', 'submitted', 'supervisor_review']),
            ('cycle_id.assessment_deadline', '!=', False),
            ('cycle_id.assessment_deadline', '<=', today)
        ])
        for asm in pending_assessments:
            target_user = False
            if asm.state in ('draft', 'submitted') and asm.employee_id.user_id:
                target_user = asm.employee_id.user_id
            elif asm.state == 'supervisor_review' and asm.employee_id.parent_id and asm.employee_id.parent_id.user_id:
                target_user = asm.employee_id.parent_id.user_id
                
            if target_user:
                asm.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('REMINDER: Overdue Competency Assessment %s') % asm.name,
                    note=_('Assessment %s is pending/overdue (Deadline: %s).') % (asm.name, asm.cycle_id.assessment_deadline),
                    user_id=target_user.id,
                )


class CompetencyAssessmentLine(models.Model):
    """One competency rating inside an assessment (FR-ASM-006, FR-GAP-005)."""
    _name = 'competency.assessment.line'
    _description = 'Competency Assessment Line'

    assessment_id = fields.Many2one(
        'competency.assessment', string='Assessment', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade',
        domain="[('approved_framework_ids', '!=', False)]")
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
    achievement_status = fields.Selection([
        ('exceeds', 'Exceeds Required Level'),
        ('meets', 'Meets Required Level'),
        ('below', 'Below Required Level'),
    ], string='Achievement Status', compute='_compute_achievement_status_and_priority', store=True)
    gap_priority = fields.Selection([
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low Priority / No Gap'),
    ], string='Gap Priority', compute='_compute_achievement_status_and_priority', store=True)
    comments = fields.Text(string='Comments')
    evidence_attachment_ids = fields.Many2many('ir.attachment', string='Supporting Evidence')

    @api.constrains('competency_id')
    def _check_competency_on_approved_framework(self):
        for line in self:
            if line.competency_id and not line.competency_id.approved_framework_ids:
                raise ValidationError(_("The competency '%s' does not belong to any Approved Competency Framework. Only framework-approved competencies can be assessed.") % line.competency_id.name)

    @api.depends('current_level', 'required_level')
    def _compute_gap(self):
        for rec in self:
            rec.gap = int(rec.required_level or 0) - int(rec.current_level or 0)

    @api.depends('gap', 'current_level', 'required_level')
    def _compute_achievement_status_and_priority(self):
        for rec in self:
            gap_val = rec.gap or 0
            if gap_val < 0:
                rec.achievement_status = 'exceeds'
                rec.gap_priority = 'low'
            elif gap_val == 0:
                rec.achievement_status = 'meets'
                rec.gap_priority = 'low'
            elif gap_val == 1:
                rec.achievement_status = 'below'
                rec.gap_priority = 'medium'
            else:
                rec.achievement_status = 'below'
                rec.gap_priority = 'high'

    _sql_constraints = [
        ('assessment_competency_uniq', 'unique(assessment_id, competency_id)',
         'This competency is already rated in the assessment!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot add rating lines to locked assessment %s.") % line.assessment_id.name)
        return lines

    def write(self, vals):
        res = super().write(vals)
        for line in self:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify rating lines on locked assessment %s.") % line.assessment_id.name)
        return res

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_locked(self):
        for line in self:
            if line.assessment_id and line.assessment_id.state == 'locked' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete rating lines from locked assessment %s.") % line.assessment_id.name)



