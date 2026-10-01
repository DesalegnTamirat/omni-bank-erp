# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyIDP(models.Model):
    """Individual Development Plan derived from assessment gaps ."""
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
        help='Auto-flagged when a competency gap exists .')
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
        # sudo: employee-created IDPs  must not depend on the user
        # having ir.sequence access.
        records = super().create(vals_list)
        for record in records:
            if not record.name:
                record.name = self.env['ir.sequence'].sudo().next_by_code('competency.idp') or \
                    'IDP-%s' % record.id
        return records

    def _check_segregation_of_duties(self):
        """Segregation of duties guard: Block self-approval of IDP (FR-COM-055)."""
        for rec in self:
            subject_user = rec.employee_id.user_id if rec.employee_id else False
            creator_user = rec.create_uid or False
            current_user = self.env.user
            
            if not self.env.su:
                if (subject_user and current_user == subject_user) or (creator_user and current_user == creator_user):
                    raise ValidationError(_("You cannot approve your own assessment/IDP. This action must be performed by a different authorized user (FR-COM-055)."))

    def action_submit(self):
        for rec in self:
            if not rec.goal_ids:
                raise ValidationError(_('Add at least one development activity before submitting.'))
            rec.with_context(force_write=True).write({'state': 'submitted'})
            
            supervisor_user = rec.employee_id.parent_id.user_id if (rec.employee_id and rec.employee_id.parent_id) else False
            if supervisor_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('IDP Approval Required: %s') % rec.name,
                    note=_('Please review and approve IDP for %s.') % rec.employee_id.name,
                    user_id=supervisor_user.id,
                )

    def action_approve(self):
        """Supervisor approval with Segregation of Duties guard (FR-COM-055)."""
        for rec in self:
            rec._check_segregation_of_duties()
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('IDP %s approved.') % rec.name)

    def action_start(self):
        self.with_context(force_write=True).write({'state': 'active'})

    def action_complete(self):
        self.with_context(force_write=True).write({'state': 'completed'})
        for rec in self:
            rec.message_post(body=_('IDP %s completed.') % rec.name)

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state == 'completed' and not force_write and not self.env.su:
                locked_fields = {'employee_id', 'assessment_id', 'goal_ids', 'checkpoint_ids', 'notes'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("Individual Development Plan %s is completed and finalized. It cannot be edited.") % rec.name)
        return super().write(vals)

    @api.model
    def _cron_idp_checkpoint_reminders(self):
        """Daily cron: IDP checkpoint reminders (FR-COM-050)."""
        today = fields.Date.context_today(self)
        checkpoints = self.env['competency.idp.checkpoint'].search([
            ('status', '=', 'scheduled'),
            ('scheduled_date', '<=', today)
        ])
        for cp in checkpoints:
            if cp.idp_id and cp.idp_id.employee_id and cp.idp_id.employee_id.user_id:
                cp.idp_id.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('IDP Review Checkpoint Due: %s') % cp.idp_id.name,
                    note=_('Review checkpoint scheduled for %s is now due.') % cp.scheduled_date,
                    user_id=cp.idp_id.employee_id.user_id.id,
                )

    @api.model
    def _cron_escalate_draft_idps_14_days(self):
        """Cron action: Escalates draft IDPs unapproved > 14 days to HR Officers/Admins."""
        today = fields.Date.context_today(self)
        cutoff_date = today - timedelta(days=14)
        overdue_drafts = self.search([
            ('state', '=', 'draft'),
            ('create_date', '<=', cutoff_date)
        ])
        hr_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
        hr_users = hr_group.users if hr_group else self.env['res.users']
        for idp in overdue_drafts:
            for hr_user in hr_users:
                idp.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('ESCALATION: Unapproved Draft IDP Overdue (%s)') % idp.name,
                    note=_('Individual Development Plan %s for %s has been in draft state for over 14 days.') % (idp.name, idp.employee_id.name),
                    user_id=hr_user.id,
                )


    def action_recommend_lms_courses(self):
        """Recommend matching LMS/EDS courses based on assessment development gaps (FR-CBT-003, FR-ELN-002)."""
        for idp in self:
            if not idp.assessment_id:
                continue
            gaps = idp.assessment_id.line_ids.filtered(lambda l: l.gap > 0)
            if not gaps:
                continue
            
            Course = self.env['eds.course'] if 'eds.course' in self.env else False
            if not Course:
                continue
                
            added_count = 0
            for line in gaps:
                matching_courses = Course.search([
                    ('competency_id', '=', line.competency_id.id),
                    ('state', '=', 'approved')
                ], limit=2)
                for crs in matching_courses:
                    self.env['competency.idp.activity'].create({
                        'idp_id': idp.id,
                        'goal': _("LMS Recommended Course for %s (Gap: %s)") % (line.competency_id.name, line.gap),
                        'activity_type': 'training',
                        'course_name': crs.name,
                        'gap_priority': line.gap_priority or 'high',
                        'status': 'planned',
                    })
                    added_count += 1
            if added_count:
                idp.message_post(body=_("%s LMS/EDS training courses recommended automatically from competency gaps.") % added_count)


class CompetencyIDPActivity(models.Model):
    """A development activity inside an IDP (FR-COM-022, FR-GAP-004, FR-GAP-005)."""
    _name = 'competency.idp.activity'
    _description = 'IDP Development Activity'

    idp_id = fields.Many2one('competency.idp', string='IDP', required=True, ondelete='cascade')
    goal = fields.Text(string='Development Goal', required=True)
    activity_type = fields.Selection([
        ('training', 'Formal Training Program / LMS'),
        ('coaching', 'Coaching'),
        ('mentoring', 'Mentoring'),
        ('job_rotation', 'Job Rotation'),
        ('reassignment', 'Role Reassignment'),
        ('stretch_assignment', 'Stretch Assignment'),
        ('ojt', 'On-the-Job Learning'),
        ('self_study', 'Self-Study'),
        ('formal_education', 'Formal Education'),
    ], string='Activity Type', required=True, default='training')
    gap_priority = fields.Selection([
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low Priority'),
    ], string='Priority', default='high')
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

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot add activities to completed IDP %s.") % line.idp_id.name)
        return lines

    def write(self, vals):
        res = super().write(vals)
        for line in self:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify activities on completed IDP %s.") % line.idp_id.name)
        return res

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_completed(self):
        for line in self:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete activities from completed IDP %s.") % line.idp_id.name)


class CompetencyIDPCheckpoint(models.Model):
    """Scheduled review checkpoint (FR-COM-025)."""
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

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot add checkpoints to completed IDP %s.") % line.idp_id.name)
        return lines

    def write(self, vals):
        res = super().write(vals)
        for line in self:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify checkpoints on completed IDP %s.") % line.idp_id.name)
        return res

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_completed(self):
        for line in self:
            if line.idp_id and line.idp_id.state == 'completed' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete checkpoints from completed IDP %s.") % line.idp_id.name)


