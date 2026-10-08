# -*- coding: utf-8 -*-
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmProject(models.Model):
    _name = 'pm.project'
    _description = 'Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, date_start desc, id desc'

    name = fields.Char(string='Project Name', required=True, tracking=True)
    code = fields.Char(string='Project Code / Reference', readonly=True, copy=False, default=lambda self: _('New'))
    sequence = fields.Integer(string='Sequence', default=10)
    initiative_id = fields.Many2one('pm.initiative', string='Initiative / Program', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.project') or _('New')
        return super().create(vals_list)
    
    # Strategic context inherited from Initiative
    initiative_description = fields.Html(string='Initiative Description', related='initiative_id.description', readonly=True)
    strategic_source_id = fields.Many2one('pm.strategic.source', string='Strategic Source', tracking=True)
    strategic_objective_id = fields.Many2one('pm.strategic.objective', string='Strategic Objective', tracking=True)
    
    # Roles
    manager_id = fields.Many2one('res.users', string='Project Manager', default=lambda self: self.env.user, required=True, tracking=True)
    coordinator_id = fields.Many2one('res.users', string='Project Coordinator', tracking=True)
    member_ids = fields.Many2many('res.users', 'pm_project_member_rel', 'project_id', 'user_id', string='Project Team Members')
    
    # Sponsor / Classification
    customer_id = fields.Many2one('res.partner', string='Sponsor')
    tag_type = fields.Selection([
        ('internal', 'Internal'),
        ('external', 'External'),
        ('both', 'Both')
    ], string='Project Scope Nature', default='internal', tracking=True)
    
    # Budget & Staffing Capacity
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    estimated_cost = fields.Monetary(string='Estimated Cost / Budget', currency_field='currency_id', tracking=True)
    staff_required = fields.Integer(string='Staff Required (Headcount)', default=1, tracking=True)
    
    # Timeline
    date_start = fields.Date(string='Start Date', tracking=True)
    date_end = fields.Date(string='Target End Date', tracking=True)
    
    # Dynamic Lifecycle Status Engine
    status = fields.Selection([
        ('draft', 'Planning'),
        ('active', 'In Progress'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_project_status', store=True, readonly=False, default='draft', tracking=True)

    health_state = fields.Selection([
        ('initiation', 'Initiation'),
        ('planning', 'Planning'),
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('off_track', 'Off Track'),
        ('on_hold', 'On Hold'),
        ('done', 'Done'),
    ], string='Project Health', default='planning', compute='_compute_health_state', store=True, readonly=False, tracking=True)
    is_health_manual = fields.Boolean(string='Manual Health Override', default=False)

    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority', default='1')
    
    color = fields.Integer(string='Color Index', default=0)
    
    # Enterprise Governance & Ownership (Boss Feedback)
    sponsor_user_id = fields.Many2one('res.users', string='Project Sponsor', tracking=True)
    process_owner_id = fields.Many2one('res.users', string='Process Owner', tracking=True)
    lead_office_id = fields.Many2one('pm.lead.office', string='Lead Office', tracking=True)
    project_type_id = fields.Many2one('pm.task.tag', string='Project Type', tracking=True)
    team_ids = fields.One2many('pm.project.team', 'project_id', string='Project Team')
    
    # Kanban Summary Stats
    milestones_summary = fields.Char(string='Milestones (Reached/Total)', compute='_compute_kanban_stats', store=True)
    deliverables_summary = fields.Char(string='Deliverables (Reached/Total)', compute='_compute_kanban_stats', store=True)

    # Project Scope, Deliverables Overview & Narrative Tabs
    deliverables_description = fields.Html(string='Deliverables Summary & Strategy')
    description = fields.Html(string='Project Description & Scope')
    assumption_ids = fields.One2many('pm.project.assumption', 'project_id', string='Assumptions')
    skill_ids = fields.One2many('pm.project.skill', 'project_id', string='Required Skills')
    
    # Relations: Deliverables, Milestones, Tasks
    deliverable_ids = fields.One2many('pm.deliverable', 'project_id', string='Deliverables')
    milestone_ids = fields.One2many('pm.milestone', 'project_id', string='Milestones')
    task_ids = fields.One2many('pm.task', 'project_id', string='Tasks')
    
    # Governance Relations: Risks, Dependencies, Dynamic Tabs
    risk_ids = fields.One2many('pm.project.risk', 'project_id', string='Risks')
    dependency_ids = fields.One2many('pm.project.dependency', 'project_id', string='Dependencies')
    custom_tab_ids = fields.One2many('pm.project.custom.tab', 'project_id', string='Custom Sections')
    progress_update_ids = fields.One2many('pm.project.progress.update', 'project_id', string='Progress Updates')
    
    # Statistics & Rollups
    deliverable_count = fields.Integer(string='Total Deliverables', compute='_compute_task_stats', store=True)
    milestone_count = fields.Integer(string='Milestones Count', compute='_compute_task_stats', store=True)
    task_count = fields.Integer(string='Total Tasks', compute='_compute_task_stats', store=True)
    closed_task_count = fields.Integer(string='Completed Tasks', compute='_compute_task_stats', store=True)
    open_task_count = fields.Integer(string='Open Tasks', compute='_compute_task_stats', store=True)
    progress_update_count = fields.Integer(string='Updates Count', compute='_compute_progress_update_count')
    progress_rate = fields.Float(string='Progress (%)', compute='_compute_task_stats', store=True)
    effort_variance = fields.Float(
        string='Effort Variance (%)',
        compute='_compute_effort_variance',
        store=True,
        help='(Time Logged - Allocated) / Allocated × 100. Positive = overrun; Negative = under-spent.'
    )

    @api.onchange('initiative_id')
    def _onchange_initiative_id(self):
        if self.initiative_id:
            if not self.strategic_objective_id and self.initiative_id.strategic_objective_id:
                self.strategic_objective_id = self.initiative_id.strategic_objective_id
            if not self.strategic_source_id and self.initiative_id.strategic_source_id:
                self.strategic_source_id = self.initiative_id.strategic_source_id

    @api.constrains('date_start', 'date_end', 'initiative_id')
    def _check_project_dates(self):
        for rec in self:
            # Basic: end must be >= start
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_(
                    "Project '%s': Target End Date (%s) cannot be earlier than Start Date (%s)!"
                ) % (rec.name, rec.date_end, rec.date_start))
            # Cross-level: project window must fit within parent initiative window
            if rec.initiative_id:
                init = rec.initiative_id
                if init.date_start and rec.date_start and rec.date_start < init.date_start:
                    raise ValidationError(_(
                        "Project '%s': Start Date (%s) cannot be earlier than "
                        "Initiative '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, init.name, init.date_start))
                if init.date_end and rec.date_end and rec.date_end > init.date_end:
                    raise ValidationError(_(
                        "Project '%s': End Date (%s) cannot exceed "
                        "Initiative '%s' End Date (%s)!"
                    ) % (rec.name, rec.date_end, init.name, init.date_end))

    @api.constrains('estimated_cost')
    def _check_budget(self):
        for rec in self:
            if rec.estimated_cost and rec.estimated_cost < 0:
                raise ValidationError(_(
                    "Project '%s': Budget / Estimated Cost cannot be negative."
                ) % rec.name)

    @api.constrains('staff_required')
    def _check_staff_required(self):
        for rec in self:
            if rec.staff_required < 0:
                raise ValidationError(_(
                    "Project '%s': Staff Required cannot be negative."
                ) % rec.name)

    @api.depends('task_ids.allocated_hours', 'task_ids.effective_hours')
    def _compute_effort_variance(self):
        for rec in self:
            total_allocated = sum(t.allocated_hours for t in rec.task_ids)
            total_logged = sum(t.effective_hours for t in rec.task_ids)
            if total_allocated > 0:
                rec.effort_variance = (
                    (total_logged - total_allocated) / total_allocated
                ) * 100.0
            else:
                rec.effort_variance = 0.0

    @api.depends('milestone_ids', 'milestone_ids.progress_rate', 'milestone_ids.weight',
                 'deliverable_ids', 'deliverable_ids.progress_rate', 'deliverable_ids.weight',
                 'task_ids', 'task_ids.is_closed', 'task_ids.progress_rate', 'task_ids.weight')
    def _compute_task_stats(self):
        for rec in self:
            total_tasks = len(rec.task_ids)
            closed_tasks = len(rec.task_ids.filtered(lambda t: t.is_closed))
            rec.task_count = total_tasks
            rec.closed_task_count = closed_tasks
            rec.open_task_count = total_tasks - closed_tasks
            rec.milestone_count = len(rec.milestone_ids)
            rec.deliverable_count = len(rec.deliverable_ids)
            
            # Hierarchical weighted rollup: Milestones -> Project
            # Only count milestones that actually have tasks/deliverables
            active_milestones = rec.milestone_ids.filtered(
                lambda m: m.task_count > 0 or m.deliverable_count > 0
            )
            if active_milestones:
                total_m_weight = sum(m.weight for m in active_milestones)
                if total_m_weight > 0:
                    rec.progress_rate = sum(m.progress_rate * m.weight for m in active_milestones) / total_m_weight
                else:
                    rec.progress_rate = sum(m.progress_rate for m in active_milestones) / len(active_milestones)
            elif rec.deliverable_ids:
                total_d_weight = sum(d.weight for d in rec.deliverable_ids)
                if total_d_weight > 0:
                    rec.progress_rate = sum(d.progress_rate * d.weight for d in rec.deliverable_ids) / total_d_weight
                else:
                    rec.progress_rate = sum(d.progress_rate for d in rec.deliverable_ids) / len(rec.deliverable_ids)
            elif total_tasks > 0:
                total_t_weight = sum(t.weight for t in rec.task_ids)
                if total_t_weight > 0:
                    rec.progress_rate = sum(t.progress_rate * t.weight for t in rec.task_ids) / total_t_weight
                else:
                    rec.progress_rate = sum(t.progress_rate for t in rec.task_ids) / total_tasks
            else:
                rec.progress_rate = 0.0

    @api.depends('task_count', 'closed_task_count', 'progress_rate')
    def _compute_project_status(self):
        for rec in self:
            # Preserve manually-set terminal states
            if rec.status in ('on_hold', 'cancelled'):
                continue
            if rec.task_count > 0 and rec.closed_task_count == rec.task_count and rec.progress_rate >= 100.0:
                rec.status = 'completed'
            elif rec.progress_rate > 0.0 or (
                rec.task_count > 0
                and any(not t.is_closed and (t.stage_id.name or '').strip().lower() != 'to do'
                        for t in rec.task_ids)
            ):
                rec.status = 'active'
            # Do NOT revert active → draft; only set draft on fresh records
            elif rec.status not in ('active', 'completed'):
                rec.status = 'draft'

    @api.depends('milestone_ids.state', 'milestone_ids.progress_rate', 'deliverable_ids.state', 'deliverable_ids.progress_rate')
    def _compute_kanban_stats(self):
        for rec in self:
            m_done = len(rec.milestone_ids.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed'))
            m_total = len(rec.milestone_ids)
            rec.milestones_summary = f"{m_done}/{m_total}" if m_total else "0/0"
            d_done = len(rec.deliverable_ids.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed'))
            d_total = len(rec.deliverable_ids)
            rec.deliverables_summary = f"{d_done}/{d_total}" if d_total else "0/0"

    @api.depends('date_end', 'progress_rate', 'status', 'is_health_manual', 'task_ids.is_blocked', 'task_ids.is_closed')
    def _compute_health_state(self):
        today = date.today()
        for rec in self:
            if rec.status == 'completed' or rec.progress_rate >= 100.0:
                rec.health_state = 'done'
            elif rec.is_health_manual and rec.health_state:
                # PM manually set health state; preserve it unless project completes
                continue
            elif rec.status == 'on_hold':
                rec.health_state = 'on_hold'
            elif not rec.date_end:
                # Check if any tasks are blocked even without a deadline
                blocked_open = any(t.is_blocked and not t.is_closed for t in rec.task_ids)
                rec.health_state = 'at_risk' if blocked_open else 'on_track'
            elif rec.date_end < today and rec.progress_rate < 100.0:
                rec.health_state = 'off_track'
            elif (rec.date_end - today).days <= 7 and rec.progress_rate < 70.0:
                rec.health_state = 'at_risk'
            elif any(t.is_blocked and not t.is_closed for t in rec.task_ids):
                rec.health_state = 'at_risk'
            else:
                rec.health_state = 'on_track'

    def action_reset_health_auto(self):
        self.with_context(skip_health_manual=True).write({'is_health_manual': False})
        self.with_context(skip_health_manual=True)._compute_health_state()

    def write(self, vals):
        if 'health_state' in vals and 'is_health_manual' not in vals and not self.env.context.get('skip_health_manual'):
            vals['is_health_manual'] = True
        return super().write(vals)

    # Workflow Actions
    def action_start_project(self):
        self.write({'status': 'active'})

    def action_complete_project(self):
        self.write({'status': 'completed'})

    def action_hold_project(self):
        self.write({'status': 'on_hold'})

    def action_reopen_project(self):
        self.write({'status': 'active'})

    def action_cancel_project(self):
        self.write({'status': 'cancelled'})

    def action_view_deliverables(self):
        self.ensure_one()
        return {
            'name': f'Deliverables: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pm.deliverable',
            'view_mode': 'list,kanban,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'name': f'Tasks: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pm.task',
            'view_mode': 'kanban,list,form,calendar',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id, 'default_is_project_task': True},
        }

    def action_view_milestones(self):
        self.ensure_one()
        return {
            'name': f'Milestones: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pm.milestone',
            'view_mode': 'list,kanban,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def _compute_progress_update_count(self):
        for rec in self:
            rec.progress_update_count = len(rec.progress_update_ids)

    def action_view_progress_updates(self):
        self.ensure_one()
        return {
            'name': f'Progress Updates: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pm.project.progress.update',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        initiative_id = filters.get('initiative_id')
        project_id = filters.get('project_id')
        task_filter = filters.get('task_filter', 'all')
        
        # Build project & task domains
        is_non_project = (project_id == 'non_project')
        if is_non_project:
            projects = self.browse([])
            project_ids = []
            task_domain = [('project_id', '=', False)]
        elif project_id:
            projects = self.search([('id', '=', int(project_id))])
            project_ids = projects.ids
            task_domain = [('project_id', 'in', project_ids)]
        elif initiative_id:
            projects = self.search([('initiative_id', '=', int(initiative_id))])
            project_ids = projects.ids
            task_domain = [('project_id', 'in', project_ids)]
        else:
            projects = self.search([])
            project_ids = projects.ids
            task_domain = []  # Includes all tasks (both project tasks and non-project tasks)

        # Strategic Initiatives Data
        init_domain = [('id', '=', int(initiative_id))] if initiative_id else []
        dashboard_initiatives = self.env['pm.initiative'].search(init_domain, order='date_start desc, id desc')
        total_initiatives = len(dashboard_initiatives)
        active_initiatives = len(dashboard_initiatives.filtered(lambda i: i.state == 'in_progress'))
        achieved_initiatives = len(dashboard_initiatives.filtered(lambda i: i.state == 'achieved'))
        initiative_avg_progress = round(sum(i.progress_rate for i in dashboard_initiatives) / total_initiatives, 1) if total_initiatives else 0.0

        initiative_table = [{
            'id': i.id,
            'name': i.name,
            'code': i.code or 'New',
            'state': i.state,
            'owner_name': i.owner_id.name if i.owner_id else 'Unassigned',
            'strategic_source': i.strategic_source_id.name or 'Direct Initiative',
            'strategic_objective': i.strategic_objective_id.name or 'Corporate Strategy',
            'project_count': i.project_count,
            'progress_rate': round(i.progress_rate, 1),
            'date_start': str(i.date_start or ''),
            'date_end': str(i.date_end or ''),
        } for i in dashboard_initiatives]

        # Apply Task Filter
        today = date.today()
        if task_filter == 'open':
            task_domain.append(('is_closed', '=', False))
        elif task_filter == 'completed':
            task_domain.append(('is_closed', '=', True))
        elif task_filter == 'blocked':
            task_domain.extend([('is_blocked', '=', True), ('is_closed', '=', False)])
        elif task_filter == 'overdue':
            task_domain.extend([('is_closed', '=', False), ('date_deadline', '<', today)])

        tasks = self.env['pm.task'].search(task_domain)
        if is_non_project:
            deliverables = self.env['pm.deliverable'].browse([])
            milestones = self.env['pm.milestone'].browse([])
            risks = self.env['pm.project.risk'].browse([])
        elif project_ids:
            deliverables = self.env['pm.deliverable'].search([('project_id', 'in', project_ids)])
            milestones = self.env['pm.milestone'].search([('project_id', 'in', project_ids)])
            risks = self.env['pm.project.risk'].search([('project_id', 'in', project_ids)], order='severity desc, id desc', limit=6)
        else:
            deliverables = self.env['pm.deliverable'].search([])
            milestones = self.env['pm.milestone'].search([])
            risks = self.env['pm.project.risk'].search([], order='severity desc, id desc', limit=6)

        total_projects = len(projects)
        portfolio_progress = round(sum(p.progress_rate for p in projects) / total_projects, 1) if total_projects else 0.0

        health_counts = {
            'on_track': len(projects.filtered(lambda p: p.health_state in ('on_track', 'done'))),
            'at_risk': len(projects.filtered(lambda p: p.health_state == 'at_risk')),
            'overdue': len(projects.filtered(lambda p: p.health_state in ('off_track', 'overdue'))),
        }

        total_tasks = len(tasks)
        closed_tasks = len(tasks.filtered(lambda t: t.is_closed))
        open_tasks = total_tasks - closed_tasks
        blocked_tasks = len(tasks.filtered(lambda t: t.is_blocked and not t.is_closed))

        total_allocated = sum(t.allocated_hours for t in tasks)
        total_logged = sum(t.effective_hours for t in tasks)
        effort_variance = round(total_allocated - total_logged, 1)

        # Chart: Tasks by Stage
        stages = self.env['pm.task.stage'].search([], order='sequence asc')
        stage_chart = {
            'labels': [s.name for s in stages],
            'data': [len(tasks.filtered(lambda t: t.stage_id.id == s.id)) for s in stages]
        }

        # Chart: Effort Variance by Project (Top 6 projects)
        display_projects = projects[:6]
        effort_chart = {
            'labels': [p.name[:25] + ('...' if len(p.name) > 25 else '') for p in display_projects],
            'allocated': [sum(t.allocated_hours for t in p.task_ids) for p in display_projects],
            'logged': [sum(t.effective_hours for t in p.task_ids) for p in display_projects]
        }

        # Chart: Team Workload (Top 6 team members)
        all_users = set()
        for t in tasks:
            for u in t.user_ids:
                all_users.add(u)
        user_list = list(all_users)[:6]
        team_workload_chart = {
            'labels': [u.name for u in user_list],
            'tasks': [len(tasks.filtered(lambda t: u in t.user_ids)) for u in user_list],
            'hours': [round(sum(log.hours_spent for t in tasks.filtered(lambda t: u in t.user_ids) for log in t.progress_log_ids.filtered(lambda l: l.user_id == u)), 1) for u in user_list]
        }

        # Top Risks Table
        risk_table = [{
            'id': r.id,
            'name': r.name,
            'project_name': r.project_id.name if r.project_id else 'General',
            'severity': r.severity,
            'probability': dict(r._fields['probability'].selection).get(r.probability, r.probability),
            'impact': dict(r._fields['impact'].selection).get(r.impact, r.impact),
            'mitigation': r.mitigation or 'None documented',
            'status': r.status,
            'owner_name': r.owner_id.name if r.owner_id else 'Unassigned'
        } for r in risks]

        # Upcoming & Overdue Tasks/Deliverables Table
        urgent_tasks = self.env['pm.task'].search(
            [('id', 'in', tasks.ids), ('is_closed', '=', False), ('date_deadline', '!=', False)],
            order='date_deadline asc',
            limit=6
        )
        deadline_table = [{
            'id': t.id,
            'name': t.name,
            'project_name': t.project_id.name if t.project_id else 'Non-Project',
            'date_deadline': str(t.date_deadline),
            'deadline_status': t.deadline_status,
            'progress_rate': round(t.progress_rate, 1),
            'assignees': ', '.join(t.user_ids.mapped('name')) or 'Unassigned',
            'is_overdue': bool(t.date_deadline and t.date_deadline < today)
        } for t in urgent_tasks]

        # Blocked Tasks Table
        blocked_tasks_list = self.env['pm.task'].search(
            [('id', 'in', tasks.ids), ('is_blocked', '=', True), ('is_closed', '=', False)],
            order='priority desc, date_deadline asc, id desc',
            limit=6
        )
        blocked_table = [{
            'id': t.id,
            'name': t.name,
            'project_name': t.project_id.name if t.project_id else 'Non-Project',
            'assignees': ', '.join(t.user_ids.mapped('name')) or 'Unassigned',
            'stage': t.stage_id.name if t.stage_id else 'Blocked',
            'date_deadline': str(t.date_deadline or 'No deadline'),
            'priority': t.priority or '1',
            'is_overdue': bool(t.date_deadline and t.date_deadline < today)
        } for t in blocked_tasks_list]

        # Filter Selectors
        initiatives = [{'id': i.id, 'name': i.name} for i in self.env['pm.initiative'].search([], order='name asc')]
        filter_projects = [{'id': p.id, 'name': p.name, 'initiative_id': p.initiative_id.id or False} for p in self.env['pm.project'].search([], order='name asc')]

        return {
            'kpi': {
                # Row 1: Strategic & Portfolio Governance
                'total_strategic_issues': total_initiatives,
                'total_initiatives': total_initiatives,
                'active_initiatives': active_initiatives,
                'achieved_initiatives': achieved_initiatives,
                'initiative_avg_progress': initiative_avg_progress,
                'total_projects': total_projects,
                'portfolio_progress': portfolio_progress,
                'health_counts': health_counts,
                'total_milestones': len(milestones),
                'completed_milestones': len(milestones.filtered(lambda m: m.progress_rate >= 100.0 or m.state == 'completed')),
                'total_deliverables': len(deliverables),
                'completed_deliverables': len(deliverables.filtered(lambda d: d.progress_rate >= 100.0 or d.state == 'completed')),
                'total_strategic_objectives': self.env['pm.strategic.objective'].search_count([]),

                # Row 2: Task Execution Pipeline
                'todo_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('to do', 'todo') or t.state == 'pending')),
                'in_progress_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('in progress', 'progress') or t.state == 'in_progress')),
                'in_review_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('in review', 'review', 'pending review'))),
                'completed_tasks': closed_tasks,
                'total_tasks': total_tasks,
                'open_tasks': open_tasks,
                'blocked_tasks': blocked_tasks,
                'total_allocated_hours': total_allocated,
                'total_logged_hours': total_logged,
                'effort_variance': effort_variance
            },
            'charts': {
                'stage_chart': stage_chart,
                'effort_chart': effort_chart,
                'team_workload_chart': team_workload_chart,
                'health_counts': health_counts
            },
            'tables': {
                'initiatives': initiative_table,
                'top_risks': risk_table,
                'deadline_table': deadline_table,
                'blocked_table': blocked_table,
            },
            'filters_data': {
                'initiatives': initiatives,
                'projects': filter_projects
            }
        }

