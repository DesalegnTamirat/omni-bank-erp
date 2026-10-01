# -*- coding: utf-8 -*-
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class PmTask(models.Model):
    _name = 'pm.task'
    _description = 'Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, sequence, date_deadline asc, id desc'

    name = fields.Char(string='Task Title', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    code = fields.Char(string='Task Ref', readonly=True, copy=False, default=lambda self: _('New'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.task') or _('New')
            # Auto-assign project_id from deliverable or milestone if missing
            if not vals.get('project_id'):
                if vals.get('deliverable_id'):
                    deliv = self.env['pm.deliverable'].browse(vals['deliverable_id'])
                    if deliv.project_id:
                        vals['project_id'] = deliv.project_id.id
                        vals['is_project_task'] = True
                elif vals.get('milestone_id'):
                    m = self.env['pm.milestone'].browse(vals['milestone_id'])
                    if m.project_id:
                        vals['project_id'] = m.project_id.id
                        vals['is_project_task'] = True
        return super().create(vals_list)
    
    # Task Category: Project Task vs Non-Project Task
    is_project_task = fields.Boolean(
        string='Is Project Task',
        compute='_compute_is_project_task',
        store=True,
        readonly=False,
        index=True
    )
    project_id = fields.Many2one('pm.project', string='Project', ondelete='cascade', tracking=True, index=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone',
                                  domain="[('project_id', '=', project_id)]", tracking=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable',
                                    domain="[('project_id', '=', project_id)]", tracking=True)
    weight = fields.Float(string='Weight (%)', default=1.0, help='Weight of this task towards deliverable progress.', tracking=True)
    
    # Governance & Assignees
    manager_id = fields.Many2one('res.users', string='Project Manager', related='project_id.manager_id', store=True, readonly=True)
    coordinator_id = fields.Many2one('res.users', string='Project Coordinator', related='project_id.coordinator_id', store=True, readonly=True)
    user_ids = fields.Many2many('res.users', 'pm_task_user_rel', 'task_id', 'user_id', string='Assignees', tracking=True)
    customer_id = fields.Many2one('res.partner', string='Sponsor')
    tag_type = fields.Selection([
        ('internal', 'Internal'),
        ('external', 'External'),
        ('both', 'Both')
    ], string='Type', default='internal')

    # Timelines
    date_start = fields.Date(string='Start Date', tracking=True)
    date_deadline = fields.Date(string='Deadline', tracking=True)
    deadline_status = fields.Char(string='Deadline Status', compute='_compute_deadline_status')
    
    # Stage & Completion
    stage_id = fields.Many2one('pm.task.stage', string='Stage', default=lambda self: self._default_stage_id(),
                              group_expand='_read_group_stage_ids', tracking=True, index=True)
    is_closed = fields.Boolean(string='Completed', related='stage_id.is_closed', store=True)
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority', default='1', tracking=True)
    
    color = fields.Integer(string='Color Index', default=0)
    tag_ids = fields.Many2many('pm.task.tag', string='Tags')
    description = fields.Html(string='Task Description')

    # Time & Progress
    allocated_hours = fields.Float(
        string='Allocated Time (Hours)',
        compute='_compute_allocated_hours',
        store=True,
        readonly=False,
        default=0.0
    )
    effective_hours = fields.Float(string='Time Spent (Hours)', compute='_compute_effective_hours', store=True)
    effort_variance = fields.Float(
        string='Effort Variance (%)',
        compute='_compute_effort_variance',
        store=True,
        help='(Time Logged - Allocated) / Allocated x 100. Positive = overrun; Negative = under-spent.'
    )
    
    progress_rate = fields.Float(
        string='Progress (%)',
        compute='_compute_progress_rate',
        store=True,
        readonly=False,
        tracking=True
    )

    # Subtasks & Timelines
    subtask_ids = fields.One2many('pm.task.subtask', 'task_id', string='Sub-tasks')
    subtask_count = fields.Integer(string='Sub-tasks Count', compute='_compute_subtask_stats', store=True)
    closed_subtask_count = fields.Integer(string='Completed Sub-tasks', compute='_compute_subtask_stats', store=True)

    # Work & Progress Logs
    progress_log_ids = fields.One2many('pm.task.progress.log', 'task_id', string='Progress Logs')

    # Dependencies (Blocked By / Blocking)
    blocked_by_ids = fields.Many2many('pm.task', 'pm_task_dependency_rel', 'task_id', 'blocked_by_id',
                                      string='Blocked By', help='Tasks that must be completed before this task.')
    blocking_ids = fields.Many2many('pm.task', 'pm_task_dependency_rel', 'blocked_by_id', 'task_id',
                                    string='Blocking', readonly=True)
    is_blocked = fields.Boolean(string='Is Blocked', compute='_compute_is_blocked', store=True)

    # Helper flags for workflow action buttons
    can_start_work = fields.Boolean(compute='_compute_stage_actions')
    can_submit_review = fields.Boolean(compute='_compute_stage_actions')
    can_approve_complete = fields.Boolean(compute='_compute_stage_actions')
    can_request_changes = fields.Boolean(compute='_compute_stage_actions')
    can_reopen = fields.Boolean(compute='_compute_stage_actions')

    @api.constrains('date_start', 'date_deadline', 'project_id', 'milestone_id', 'deliverable_id')
    def _check_task_dates(self):
        for rec in self:
            if rec.date_start and rec.date_deadline and rec.date_deadline < rec.date_start:
                raise ValidationError(_("Task '%s': Deadline (%s) cannot be earlier than Start Date (%s)!") % (
                    rec.name, rec.date_deadline, rec.date_start
                ))
            # 1. Deliverable (Immediate Parent - Highest Priority Boundary)
            if rec.deliverable_id:
                if rec.deliverable_id.date_start and rec.date_start and rec.date_start < rec.deliverable_id.date_start:
                    raise ValidationError(_(
                        "Task '%s': Start Date (%s) cannot be earlier than Deliverable '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, rec.deliverable_id.name, rec.deliverable_id.date_start))
                if rec.deliverable_id.date_deadline and rec.date_start and rec.date_start > rec.deliverable_id.date_deadline:
                    raise ValidationError(_(
                        "Task '%s': Start Date (%s) cannot be later than Deliverable '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_start, rec.deliverable_id.name, rec.deliverable_id.date_deadline))
                if rec.deliverable_id.date_deadline and rec.date_deadline and rec.date_deadline > rec.deliverable_id.date_deadline:
                    raise ValidationError(_(
                        "Task '%s': Deadline (%s) cannot exceed Deliverable '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_deadline, rec.deliverable_id.name, rec.deliverable_id.date_deadline))
            # 2. Milestone (Intermediate Parent Boundary)
            elif rec.milestone_id:
                if rec.milestone_id.date_start and rec.date_start and rec.date_start < rec.milestone_id.date_start:
                    raise ValidationError(_(
                        "Task '%s': Start Date (%s) cannot be earlier than Milestone '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, rec.milestone_id.name, rec.milestone_id.date_start))
                if rec.milestone_id.date_deadline and rec.date_start and rec.date_start > rec.milestone_id.date_deadline:
                    raise ValidationError(_(
                        "Task '%s': Start Date (%s) cannot be later than Milestone '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_start, rec.milestone_id.name, rec.milestone_id.date_deadline))
                if rec.milestone_id.date_deadline and rec.date_deadline and rec.date_deadline > rec.milestone_id.date_deadline:
                    raise ValidationError(_(
                        "Task '%s': Deadline (%s) cannot exceed Milestone '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_deadline, rec.milestone_id.name, rec.milestone_id.date_deadline))
            # 3. Project (Top Level Boundary)
            if rec.project_id:
                if rec.project_id.date_start and rec.date_start and rec.date_start < rec.project_id.date_start:
                    raise ValidationError(_("Task '%s': Start Date (%s) cannot be earlier than Project Start Date (%s)!") % (
                        rec.name, rec.date_start, rec.project_id.date_start
                    ))
                if rec.project_id.date_end and rec.date_start and rec.date_start > rec.project_id.date_end:
                    raise ValidationError(_("Task '%s': Start Date (%s) cannot be later than Project Target End Date (%s)!") % (
                        rec.name, rec.date_start, rec.project_id.date_end
                    ))
                if rec.project_id.date_end and rec.date_deadline and rec.date_deadline > rec.project_id.date_end:
                    raise ValidationError(_("Task '%s': Deadline (%s) cannot exceed Project Target End Date (%s)!") % (
                        rec.name, rec.date_deadline, rec.project_id.date_end
                    ))

    @api.constrains('weight', 'deliverable_id')
    def _check_weight(self):
        for rec in self:
            if rec.weight <= 0:
                raise ValidationError(_(
                    "Task '%s': Weight must be greater than zero."
                ) % rec.name)
            if rec.deliverable_id and rec.deliverable_id.weight > 0:
                tasks = self.env['pm.task'].search([('deliverable_id', '=', rec.deliverable_id.id)])
                total_weight = sum(t.weight for t in tasks)
                if round(total_weight, 2) > round(rec.deliverable_id.weight, 2):
                    raise ValidationError(_(
                        "Task '%s': Total task weight under Deliverable '%s' is %.2f%%, which exceeds the Deliverable's allocated weight of %.2f%%!"
                    ) % (rec.name, rec.deliverable_id.name, total_weight, rec.deliverable_id.weight))

    def _default_stage_id(self):
        return self.env['pm.task.stage'].search([], order='sequence asc', limit=1)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['pm.task.stage'].search([], order='sequence asc')

    @api.depends('project_id')
    def _compute_is_project_task(self):
        for rec in self:
            if rec.project_id:
                rec.is_project_task = True
            elif not rec.is_project_task:
                rec.is_project_task = False

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.is_project_task = True
            if self.project_id.customer_id:
                self.customer_id = self.project_id.customer_id
            if self.project_id.tag_type:
                self.tag_type = self.project_id.tag_type
        else:
            self.milestone_id = False
            self.deliverable_id = False

    @api.onchange('deliverable_id')
    def _onchange_deliverable_id(self):
        if self.deliverable_id:
            if self.deliverable_id.project_id:
                self.project_id = self.deliverable_id.project_id
            if self.deliverable_id.milestone_id:
                self.milestone_id = self.deliverable_id.milestone_id

    @api.onchange('subtask_ids')
    def _onchange_subtask_ids_assignees(self):
        for rec in self:
            subtask_users = rec.subtask_ids.mapped('user_ids')
            if subtask_users:
                rec.user_ids = rec.user_ids | subtask_users

    @api.depends('subtask_ids.allocated_hours')
    def _compute_allocated_hours(self):
        for rec in self:
            if rec.subtask_ids:
                rec.allocated_hours = sum(s.allocated_hours for s in rec.subtask_ids)

    @api.depends('date_deadline', 'is_closed')
    def _compute_deadline_status(self):
        today = date.today()
        for rec in self:
            if rec.is_closed:
                rec.deadline_status = 'Completed'
            elif not rec.date_deadline:
                rec.deadline_status = ''
            else:
                delta = (rec.date_deadline - today).days
                if delta > 1:
                    rec.deadline_status = f'In {delta} days'
                elif delta == 1:
                    rec.deadline_status = 'Tomorrow'
                elif delta == 0:
                    rec.deadline_status = 'Today'
                else:
                    rec.deadline_status = f'{abs(delta)} days overdue'

    @api.depends('progress_log_ids.hours_spent')
    def _compute_effective_hours(self):
        for rec in self:
            rec.effective_hours = sum(log.hours_spent for log in rec.progress_log_ids)

    @api.depends('effective_hours', 'allocated_hours')
    def _compute_effort_variance(self):
        for rec in self:
            if rec.allocated_hours > 0:
                rec.effort_variance = (
                    (rec.effective_hours - rec.allocated_hours) / rec.allocated_hours
                ) * 100.0
            else:
                rec.effort_variance = 0.0

    @api.depends('subtask_ids', 'subtask_ids.is_done', 'subtask_ids.weight')
    def _compute_subtask_stats(self):
        for rec in self:
            total = len(rec.subtask_ids)
            closed = len(rec.subtask_ids.filtered(lambda s: s.is_done))
            rec.subtask_count = total
            rec.closed_subtask_count = closed

    @api.depends(
        'stage_id.is_closed',
        'subtask_ids.is_done',
        'subtask_ids.weight',
        'allocated_hours',
        'effective_hours',
        'progress_log_ids.hours_spent',
        'progress_log_ids.progress_percent'
    )
    def _compute_progress_rate(self):
        for rec in self:
            if rec.is_closed:
                rec.progress_rate = 100.0
            elif rec.subtask_ids:
                total_weight = sum(s.weight for s in rec.subtask_ids)
                if total_weight > 0:
                    done_weight = sum(s.weight for s in rec.subtask_ids if s.is_done)
                    rec.progress_rate = min(100.0, (done_weight / total_weight) * 100.0)
                else:
                    total_sub = len(rec.subtask_ids)
                    done_sub = len(rec.subtask_ids.filtered(lambda s: s.is_done))
                    rec.progress_rate = min(100.0, (done_sub / total_sub * 100.0)) if total_sub > 0 else 0.0
            elif rec.allocated_hours > 0:
                rec.progress_rate = min(100.0, max(0.0, round((rec.effective_hours / rec.allocated_hours) * 100.0, 2)))
            elif rec.progress_log_ids:
                rec.progress_rate = min(100.0, max(0.0, rec.progress_log_ids[0].progress_percent))
            else:
                rec.progress_rate = 0.0

    @api.depends('blocked_by_ids', 'blocked_by_ids.is_closed')
    def _compute_is_blocked(self):
        for rec in self:
            rec.is_blocked = any(not dep.is_closed for dep in rec.blocked_by_ids)

    @api.depends('stage_id', 'stage_id.name', 'stage_id.is_closed')
    def _compute_stage_actions(self):
        for rec in self:
            stage_name = (rec.stage_id.name or '').strip().lower() if rec.stage_id else ''
            rec.can_start_work = (stage_name == 'to do' or not rec.stage_id) and not rec.is_closed
            rec.can_submit_review = False
            rec.can_approve_complete = not rec.is_closed and stage_name != 'to do'
            rec.can_request_changes = False
            rec.can_reopen = rec.is_closed

    # Workflow Action Methods with Business Rules
    def action_start_work(self):
        for rec in self:
            if rec.is_blocked:
                blocking_names = ", ".join(rec.blocked_by_ids.filtered(lambda b: not b.is_closed).mapped('name'))
                raise UserError(_("Cannot start work! This task is blocked by incomplete prerequisite tasks:\n%s") % blocking_names)
            stage_in_progress = self.env['pm.task.stage'].search([('name', '=ilike', 'In Progress')], limit=1)
            if stage_in_progress:
                rec.write({'stage_id': stage_in_progress.id})

    def action_approve_complete(self):
        stage_completed = self.env['pm.task.stage'].search([('is_closed', '=', True)], limit=1)
        if stage_completed:
            for rec in self:
                for sub in rec.subtask_ids.filtered(lambda s: not s.is_done):
                    sub.write({'is_done': True})
                rec.write({'stage_id': stage_completed.id, 'progress_rate': 100.0})

    def action_request_changes(self):
        stage_in_progress = self.env['pm.task.stage'].search([('name', '=ilike', 'In Progress')], limit=1)
        if stage_in_progress:
            self.write({'stage_id': stage_in_progress.id})

    def action_reopen_task(self):
        stage_in_progress = self.env['pm.task.stage'].search([('name', '=ilike', 'In Progress')], limit=1)
        if stage_in_progress:
            self.write({'stage_id': stage_in_progress.id, 'progress_rate': 50.0})
