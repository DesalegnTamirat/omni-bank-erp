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
            self._validate_no_duplicate_workunits(vals)
        records = super().create(vals_list)
        records._sync_leadership_to_project_team()
        return records

    def _validate_no_duplicate_workunits(self, vals):
        field_configs = [
            ('sponsor_ids', _('Project Sponsor(s)')),
            ('lead_office_ids', _('Lead Office(s)')),
            ('process_owner_ids', _('Process Owner(s)')),
        ]
        for field, label in field_configs:
            if field in vals and vals[field]:
                raw_ids = []
                for cmd in vals[field]:
                    if isinstance(cmd, (list, tuple)):
                        if cmd[0] == 6 and len(cmd) > 2 and isinstance(cmd[2], (list, tuple)):
                            raw_ids.extend(cmd[2])
                        elif cmd[0] == 4 and len(cmd) > 1:
                            raw_ids.append(cmd[1])
                # Check for duplicate IDs in the same command
                seen = set()
                for i in raw_ids:
                    if i in seen:
                        raise ValidationError(_(
                            "Validation Error: A work unit cannot be selected more than once in %s! "
                            "Duplicate work unit selection is not allowed in one place."
                        ) % label)
                    seen.add(i)
                # If adding with cmd 4, ensure not already on record
                if self:
                    for rec in self:
                        existing = set(rec[field].ids)
                        for cmd in vals[field]:
                            if isinstance(cmd, (list, tuple)) and cmd[0] == 4 and len(cmd) > 1:
                                if cmd[1] in existing:
                                    raise ValidationError(_(
                                        "Validation Error: A work unit cannot be selected more than once in %s! "
                                        "Duplicate work unit selection is not allowed in one place."
                                    ) % label)
    
    # Strategic context inherited from Initiative
    initiative_description = fields.Html(string='Initiative Description', related='initiative_id.description', readonly=True)
    strategic_source_id = fields.Many2one('pm.strategic.source', string='Strategic Source', tracking=True)
    strategic_objective_id = fields.Many2one('pm.strategic.objective', string='Strategic Objective', tracking=True)
    
    # Roles
    manager_id = fields.Many2one('res.users', string='Project Manager', default=lambda self: self.env.user, required=True, tracking=True)
    coordinator_id = fields.Many2one('res.users', string='Project Coordinator', tracking=True)
    member_ids = fields.Many2many(
        'res.users', 'pm_project_member_rel', 'project_id', 'user_id',
        string='Project Team Members', compute='_compute_member_ids', store=True, readonly=False
    )
    
    # Sponsor / Classification
    customer_id = fields.Many2one('res.partner', string='Sponsor')
    tag_type = fields.Selection([
        ('internal', 'Internal'),
        ('external', 'External'),
        ('both', 'Both (Internal & External)')
    ], string='Project Type', default='internal', tracking=True)
    
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
    
    color = fields.Integer(default=0)
    active = fields.Boolean(string='Active', default=True)
    
    # Enterprise Governance & Ownership (Boss Feedback)
    sponsor_ids = fields.Many2many(
        'pm.project.sponsor',
        'pm_project_sponsor_rel',
        'project_id',
        'sponsor_id',
        string='Project Sponsor(s)',
        tracking=True,
        help='Sponsoring work units / executive offices supporting this project from Configuration.'
    )
    sponsor_id = fields.Many2one(
        'pm.project.sponsor',
        string='Primary Project Sponsor',
        compute='_compute_sponsor_primary',
        store=True,
        readonly=False,
        tracking=True
    )
    sponsor_user_id = fields.Many2one(
        'res.users',
        string='Sponsor Executive User',
        compute='_compute_sponsor_primary',
        store=True,
        readonly=False,
        tracking=True
    )
    process_owner_ids = fields.Many2many(
        'pm.process.owner',
        'pm_project_process_owner_rel',
        'project_id',
        'process_owner_id',
        string='Process Owner(s)',
        tracking=True,
        help='Work units that own or are impacted by the processes in this project from Configuration.'
    )
    process_owner_id = fields.Many2one(
        'pm.process.owner',
        string='Primary Process Owner',
        compute='_compute_process_owner_primary',
        store=True,
        readonly=False,
        tracking=True
    )
    process_owner_user_id = fields.Many2one(
        'res.users',
        string='Process Owner Head',
        compute='_compute_process_owner_primary',
        store=True,
        readonly=False,
        tracking=True
    )
    lead_office_ids = fields.Many2many(
        'pm.lead.office',
        'pm_project_lead_office_rel',
        'project_id',
        'lead_office_id',
        string='Lead Office(s)',
        tracking=True,
        help='Lead implementing offices / directorates for this project from Configuration.'
    )
    lead_office_id = fields.Many2one(
        'pm.lead.office',
        string='Primary Lead Office',
        compute='_compute_lead_office_primary',
        store=True,
        readonly=False,
        tracking=True
    )
    project_type_id = fields.Many2one('pm.task.tag', string='Tag Category', tracking=False)
    team_ids = fields.One2many('pm.project.team', 'project_id', string='Project Team')

    @api.depends('team_ids.user_id', 'team_ids.status', 'manager_id', 'coordinator_id')
    def _compute_member_ids(self):
        for project in self:
            active_users = project.team_ids.filtered(lambda t: t.status == 'active' or not t.status).mapped('user_id')
            governance = self.env['res.users']
            if project.manager_id:
                governance |= project.manager_id
            if project.coordinator_id:
                governance |= project.coordinator_id
            project.member_ids = active_users | governance
    
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
    test_execution_ids = fields.One2many('pm.test.execution', 'project_id', string='Test Executions')
    
    # Statistics & Rollups
    deliverable_count = fields.Integer(string='Total Deliverables', compute='_compute_task_stats', store=True)
    milestone_count = fields.Integer(string='Milestones Count', compute='_compute_task_stats', store=True)
    task_count = fields.Integer(string='Total Tasks', compute='_compute_task_stats', store=True)
    closed_task_count = fields.Integer(string='Completed Tasks', compute='_compute_task_stats', store=True)
    open_task_count = fields.Integer(string='Open Tasks', compute='_compute_task_stats', store=True)
    progress_update_count = fields.Integer(string='Updates Count', compute='_compute_progress_update_count')
    test_execution_count = fields.Integer(string='Test Executions Count', compute='_compute_test_execution_count')
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
            if not self.strategic_objective_id and self.initiative_id.strategic_objective_ids:
                self.strategic_objective_id = self.initiative_id.strategic_objective_ids[0]
            if not self.strategic_source_id and self.initiative_id.strategic_source_ids:
                self.strategic_source_id = self.initiative_id.strategic_source_ids[0]
            if not self.date_start and self.initiative_id.date_start:
                self.date_start = self.initiative_id.date_start
            if not self.date_end and self.initiative_id.date_end:
                self.date_end = self.initiative_id.date_end

    # Work Unit Computations & Synchronizations
    @api.depends('sponsor_ids', 'sponsor_ids.head_id', 'sponsor_ids.user_id')
    def _compute_sponsor_primary(self):
        for rec in self:
            if rec.sponsor_ids:
                first = rec.sponsor_ids[0]
                rec.sponsor_id = first
                rec.sponsor_user_id = first.head_id or first.user_id or False
            elif not rec.sponsor_id:
                rec.sponsor_user_id = False

    @api.onchange('sponsor_ids')
    def _onchange_sponsor_ids(self):
        if self.sponsor_ids:
            # Check for duplicate selections in this field
            seen = set()
            duplicates = []
            for sp in self.sponsor_ids:
                if sp.id in seen:
                    duplicates.append(sp.display_name or sp.name)
                else:
                    seen.add(sp.id)
            if duplicates:
                unique_ids = list(dict.fromkeys(self.sponsor_ids.ids))
                self.sponsor_ids = [(6, 0, unique_ids)]
                return {
                    'warning': {
                        'title': _("Duplicate Work Unit"),
                        'message': _("The work unit '%s' is already selected in Project Sponsor(s). A work unit cannot be selected more than once in the same place.") % (', '.join(duplicates))
                    }
                }
            first = self.sponsor_ids[0]
            self.sponsor_id = first
            self.sponsor_user_id = first.head_id or first.user_id or False
        else:
            self.sponsor_id = False
            self.sponsor_user_id = False

    @api.onchange('sponsor_id')
    def _onchange_sponsor_id(self):
        if self.sponsor_id:
            leader = self.sponsor_id.head_id or self.sponsor_id.user_id
            if leader:
                self.sponsor_user_id = leader
            if self.sponsor_id not in self.sponsor_ids:
                self.sponsor_ids = [(4, self.sponsor_id.id)]

    @api.depends('lead_office_ids', 'lead_office_ids.head_id')
    def _compute_lead_office_primary(self):
        for rec in self:
            if rec.lead_office_ids:
                rec.lead_office_id = rec.lead_office_ids[0]
            elif not rec.lead_office_id:
                rec.lead_office_id = False

    @api.onchange('lead_office_ids')
    def _onchange_lead_office_ids(self):
        if self.lead_office_ids:
            seen = set()
            duplicates = []
            for lo in self.lead_office_ids:
                if lo.id in seen:
                    duplicates.append(lo.display_name or lo.name)
                else:
                    seen.add(lo.id)
            if duplicates:
                unique_ids = list(dict.fromkeys(self.lead_office_ids.ids))
                self.lead_office_ids = [(6, 0, unique_ids)]
                return {
                    'warning': {
                        'title': _("Duplicate Work Unit"),
                        'message': _("The work unit '%s' is already selected in Lead Office(s). A work unit cannot be selected more than once in the same place.") % (', '.join(duplicates))
                    }
                }
            self.lead_office_id = self.lead_office_ids[0]
        else:
            self.lead_office_id = False

    @api.onchange('lead_office_id')
    def _onchange_lead_office_id(self):
        if self.lead_office_id and self.lead_office_id not in self.lead_office_ids:
            self.lead_office_ids = [(4, self.lead_office_id.id)]

    @api.depends('process_owner_ids', 'process_owner_ids.head_id', 'process_owner_ids.user_id')
    def _compute_process_owner_primary(self):
        for rec in self:
            if rec.process_owner_ids:
                first = rec.process_owner_ids[0]
                rec.process_owner_id = first
                rec.process_owner_user_id = first.head_id or first.user_id or False
            elif not rec.process_owner_id:
                rec.process_owner_user_id = False

    @api.onchange('process_owner_ids')
    def _onchange_process_owner_ids(self):
        if self.process_owner_ids:
            seen = set()
            duplicates = []
            for po in self.process_owner_ids:
                if po.id in seen:
                    duplicates.append(po.display_name or po.name)
                else:
                    seen.add(po.id)
            if duplicates:
                unique_ids = list(dict.fromkeys(self.process_owner_ids.ids))
                self.process_owner_ids = [(6, 0, unique_ids)]
                return {
                    'warning': {
                        'title': _("Duplicate Work Unit"),
                        'message': _("The work unit '%s' is already selected in Process Owner(s). A work unit cannot be selected more than once in the same place.") % (', '.join(duplicates))
                    }
                }
            first = self.process_owner_ids[0]
            self.process_owner_id = first
            self.process_owner_user_id = first.head_id or first.user_id or False
        else:
            self.process_owner_id = False
            self.process_owner_user_id = False

    @api.onchange('process_owner_id')
    def _onchange_process_owner_id(self):
        if self.process_owner_id:
            leader = self.process_owner_id.head_id or self.process_owner_id.user_id
            if leader:
                self.process_owner_user_id = leader
            if self.process_owner_id not in self.process_owner_ids:
                self.process_owner_ids = [(4, self.process_owner_id.id)]

    @api.constrains('sponsor_ids', 'lead_office_ids', 'process_owner_ids')
    def _check_unique_workunit_selections(self):
        for rec in self:
            # Check duplicate sponsors in one place
            if len(rec.sponsor_ids) != len(rec.sponsor_ids.ids):
                raise ValidationError(_(
                    "Validation Error: A work unit cannot be selected more than once in Project Sponsor(s)! "
                    "Please ensure each work unit is unique."
                ))
            # Check duplicate lead offices in one place
            if len(rec.lead_office_ids) != len(rec.lead_office_ids.ids):
                raise ValidationError(_(
                    "Validation Error: A work unit cannot be selected more than once in Lead Office(s)! "
                    "Please ensure each work unit is unique."
                ))
            # Check duplicate process owners in one place
            if len(rec.process_owner_ids) != len(rec.process_owner_ids.ids):
                raise ValidationError(_(
                    "Validation Error: A work unit cannot be selected more than once in Process Owner(s)! "
                    "Please ensure each work unit is unique."
                ))

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

    @api.depends('milestone_ids', 'milestone_ids.progress_rate', 'milestone_ids.weight', 'milestone_ids.state',
                 'deliverable_ids', 'deliverable_ids.progress_rate', 'deliverable_ids.weight', 'deliverable_ids.state',
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
            if rec.milestone_ids:
                total_m_weight = sum(m.weight for m in rec.milestone_ids)
                if total_m_weight > 0:
                    rec.progress_rate = sum(m.progress_rate * m.weight for m in rec.milestone_ids) / total_m_weight
                else:
                    rec.progress_rate = sum(m.progress_rate for m in rec.milestone_ids) / len(rec.milestone_ids)
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

    @api.depends('task_count', 'closed_task_count', 'progress_rate', 'milestone_ids.state', 'milestone_ids.progress_rate')
    def _compute_project_status(self):
        for rec in self:
            # Preserve manually-set terminal states
            if rec.status in ('on_hold', 'cancelled'):
                continue
            if rec.progress_rate >= 100.0:
                rec.status = 'completed'
            elif rec.progress_rate > 0.0 or (
                rec.task_count > 0
                and any(not t.is_closed and (t.stage_id.name or '').strip().lower() != 'to do'
                        for t in rec.task_ids)
            ):
                rec.status = 'active'
            elif rec.status != 'active':
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
        self._validate_no_duplicate_workunits(vals)
        if 'health_state' in vals and 'is_health_manual' not in vals and not self.env.context.get('skip_health_manual'):
            vals['is_health_manual'] = True
        res = super().write(vals)
        if 'manager_id' in vals or 'coordinator_id' in vals:
            self._sync_leadership_to_project_team()
        return res

    def _sync_leadership_to_project_team(self):
        """Automatically synchronize Project Manager and Coordinator into Project Teams & Roles."""
        role_model = self.env['pm.project.role']
        team_model = self.env['pm.project.team']
        
        pm_role = role_model.search([('name', '=ilike', 'Project Manager')], limit=1)
        if not pm_role:
            pm_role = role_model.create({'name': 'Project Manager', 'sequence': 1})
            
        coord_role = role_model.search(['|', ('name', '=ilike', 'Project Coordinator'), ('name', '=ilike', 'Program Manager')], limit=1)
        if not coord_role:
            coord_role = role_model.create({'name': 'Project Coordinator', 'sequence': 2})
            
        for project in self:
            # Sync Project Manager
            if project.manager_id:
                existing_pm_team = team_model.search([
                    ('project_id', '=', project.id),
                    ('role_id', '=', pm_role.id)
                ], limit=1)
                if existing_pm_team:
                    if existing_pm_team.user_id != project.manager_id:
                        existing_pm_team.write({'user_id': project.manager_id.id})
                else:
                    team_entry = team_model.search([
                        ('project_id', '=', project.id),
                        ('user_id', '=', project.manager_id.id),
                        ('role_id', '=', pm_role.id)
                    ], limit=1)
                    if not team_entry:
                        team_model.create({
                            'project_id': project.id,
                            'user_id': project.manager_id.id,
                            'role_id': pm_role.id,
                            'status': 'active'
                        })

            # Sync Coordinator if set
            if project.coordinator_id:
                existing_coord_team = team_model.search([
                    ('project_id', '=', project.id),
                    ('role_id', '=', coord_role.id)
                ], limit=1)
                if existing_coord_team:
                    if existing_coord_team.user_id != project.coordinator_id:
                        existing_coord_team.write({'user_id': project.coordinator_id.id})
                else:
                    team_entry = team_model.search([
                        ('project_id', '=', project.id),
                        ('user_id', '=', project.coordinator_id.id),
                        ('role_id', '=', coord_role.id)
                    ], limit=1)
                    if not team_entry:
                        team_model.create({
                            'project_id': project.id,
                            'user_id': project.coordinator_id.id,
                            'role_id': coord_role.id,
                            'status': 'active'
                        })

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

    def _compute_test_execution_count(self):
        for rec in self:
            rec.test_execution_count = len(rec.test_execution_ids)

    def action_view_test_executions(self):
        self.ensure_one()
        return {
            'name': f'Test Executions: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'pm.test.execution',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    @api.model
    def get_dashboard_data(self, filters=None):
        return self.get_project_dashboard_data(filters)

    @api.model
    def get_project_dashboard_data(self, filters=None):
        filters = filters or {}
        initiative_id = filters.get('initiative_id')
        project_id = filters.get('project_id')
        lead_office_id = filters.get('lead_office_id')
        manager_id = filters.get('manager_id')
        process_owner_id = filters.get('process_owner_id')
        task_filter = filters.get('task_filter', 'all')
        
        # Build project domain based on filters (Lead office, Project manager, Process owner, Initiative, Project)
        proj_domain = []
        if project_id:
            proj_domain.append(('id', '=', int(project_id)))
        if initiative_id:
            proj_domain.append(('initiative_id', '=', int(initiative_id)))
        sponsor_id = filters.get('sponsor_id')
        if lead_office_id:
            proj_domain.extend(['|', ('lead_office_ids', 'in', [int(lead_office_id)]), ('lead_office_id', '=', int(lead_office_id))])
        if sponsor_id:
            proj_domain.extend(['|', ('sponsor_ids', 'in', [int(sponsor_id)]), ('sponsor_id', '=', int(sponsor_id))])
        if manager_id:
            proj_domain.append(('manager_id', '=', int(manager_id)))
        if process_owner_id:
            proj_domain.extend(['|', ('process_owner_ids', 'in', [int(process_owner_id)]), ('process_owner_id', '=', int(process_owner_id))])

        projects = self.search(proj_domain)
        project_ids = projects.ids

        # Feedback Line 54: Remove none project task - strictly project tasks
        task_domain = [('is_project_task', '=', True)]
        if project_ids:
            task_domain.append(('project_id', 'in', project_ids))
        elif proj_domain:
            task_domain.append(('id', '=', -1)) # No projects matched filters

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
            'owner_name': i.owner_id.exists().name if i.owner_id and i.owner_id.exists() else 'Unassigned',
            'strategic_source': ', '.join(i.strategic_source_ids.mapped('name')) if i.strategic_source_ids else 'Direct Initiative',
            'strategic_objective': ', '.join(i.strategic_objective_ids.mapped('name')) if i.strategic_objective_ids else 'Corporate Strategy',
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
        if project_ids:
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

        # Chart: Tasks by Stage
        stages = self.env['pm.task.stage'].search([], order='sequence asc')
        stage_chart = {
            'labels': [s.name for s in stages],
            'data': [len(tasks.filtered(lambda t: t.stage_id.id == s.id)) for s in stages],
            'ids': [s.id for s in stages],
        }

        # Chart: Team Workload
        all_users = set()
        for t in tasks:
            for u in t.user_ids.exists():
                all_users.add(u)
        user_list = list(all_users)[:6]
        team_workload_chart = {
            'labels': [u.name for u in user_list],
            'tasks': [len(tasks.filtered(lambda t: u in t.user_ids)) for u in user_list],
        }

        # Top Risks Table
        risk_table = [{
            'id': r.id,
            'name': r.name,
            'project_name': r.project_id.exists().name if r.project_id and r.project_id.exists() else 'General',
            'severity': r.severity,
            'probability': dict(r._fields['probability'].selection).get(r.probability, r.probability),
            'impact': dict(r._fields['impact'].selection).get(r.impact, r.impact),
            'mitigation': r.mitigation or 'None documented',
            'status': r.status,
            'owner_name': r.owner_id.exists().name if r.owner_id and r.owner_id.exists() else 'Unassigned'
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
            'project_name': t.project_id.exists().name if t.project_id and t.project_id.exists() else 'Non-Project',
            'date_deadline': str(t.date_deadline),
            'deadline_status': t.deadline_status,
            'progress_rate': round(t.progress_rate, 1),
            'assignees': ', '.join(t.user_ids.exists().mapped('name')) or 'Unassigned',
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
            'project_name': t.project_id.exists().name if t.project_id and t.project_id.exists() else 'Non-Project',
            'assignees': ', '.join(t.user_ids.exists().mapped('name')) or 'Unassigned',
            'stage': t.stage_id.name if t.stage_id else 'Blocked',
            'date_deadline': str(t.date_deadline or 'No deadline'),
            'priority': t.priority or '1',
            'is_overdue': bool(t.date_deadline and t.date_deadline < today)
        } for t in blocked_tasks_list]

        # Filter Selectors (Feedback Line 53: Lead office, Project manager, Process owner)
        initiatives = [{'id': i.id, 'name': i.name} for i in self.env['pm.initiative'].search([], order='name asc')]
        filter_projects = [{'id': p.id, 'name': p.name, 'initiative_id': p.initiative_id.id or False} for p in self.env['pm.project'].search([], order='name asc')]
        lead_offices = [{'id': o.id, 'name': o.name} for o in self.env['pm.lead.office'].search([], order='name asc')]
        managers = [{'id': u.id, 'name': u.name} for u in self.env['pm.project'].search([]).mapped('manager_id').exists() if u]
        process_owners = [{'id': po.id, 'name': po.name} for po in self.env['pm.process.owner'].search([], order='name asc')]

        return {
            'kpi': {
                # Feedback Line 52: Row one order: Objectives, Initiatives, Projects, Health, Milestone, Deliverables
                'total_strategic_objectives': self.env['pm.strategic.objective'].search_count([]),
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

                # Secondary row stats
                'todo_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('to do', 'todo') or t.state == 'pending')),
                'in_progress_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('in progress', 'progress') or t.state == 'in_progress')),
                'in_review_tasks': len(tasks.filtered(lambda t: (t.stage_id.name or '').strip().lower() in ('in review', 'review', 'pending review'))),
                'completed_tasks': closed_tasks,
                'total_tasks': total_tasks,
                'open_tasks': open_tasks,
                'blocked_tasks': blocked_tasks,
            },
            'charts': {
                'stage_chart': stage_chart,
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
                'projects': filter_projects,
                'lead_offices': lead_offices,
                'managers': managers,
                'process_owners': process_owners,
            }
        }

    # Feedback Lines 55-61: Dedicated Non-Project Task Dashboard Backend
    @api.model
    def get_non_project_dashboard_data(self, filters=None):
        filters = filters or {}
        customer_id = filters.get('customer_id')
        user_id = filters.get('user_id')
        tag_id = filters.get('tag_id')
        date_from = filters.get('date_from')
        date_to = filters.get('date_to')
        task_filter = filters.get('task_filter', 'all')

        domain = [('project_id', '=', False)]
        if customer_id:
            domain.append(('customer_id', '=', int(customer_id)))
        if user_id:
            domain.append(('user_ids', 'in', [int(user_id)]))
        if tag_id:
            domain.append(('tag_ids', 'in', [int(tag_id)]))
        if date_from:
            domain.append(('date_deadline', '>=', date_from))
        if date_to:
            domain.append(('date_deadline', '<=', date_to))

        today = date.today()
        if task_filter == 'open':
            domain.append(('is_closed', '=', False))
        elif task_filter == 'completed':
            domain.append(('is_closed', '=', True))
        elif task_filter == 'blocked':
            domain.extend([('is_blocked', '=', True), ('is_closed', '=', False)])
        elif task_filter == 'overdue':
            domain.extend([('is_closed', '=', False), ('date_deadline', '<', today)])

        # Support filtering by owner_id or assignees user_ids
        if user_id:
            domain.extend(['|', ('owner_id', '=', int(user_id)), ('user_ids', 'in', [int(user_id)])])

        tag_type = filters.get('tag_type')
        if tag_type:
            domain.append(('tag_type', '=', tag_type))

        tasks = self.env['pm.task'].search(domain)
        total_tasks = len(tasks)
        completed_tasks = len(tasks.filtered(lambda t: t.is_closed))
        open_tasks = total_tasks - completed_tasks
        overdue_tasks = len(tasks.filtered(lambda t: not t.is_closed and t.date_deadline and t.date_deadline < today))
        blocked_tasks = len(tasks.filtered(lambda t: t.is_blocked and not t.is_closed))
        in_progress_tasks = len(tasks.filtered(lambda t: not t.is_closed and ((t.stage_id.name or '').lower() in ('in progress', 'progress') or t.state == 'in_progress')))
        completion_rate = round((completed_tasks / total_tasks * 100), 1) if total_tasks else 0.0

        # Stages breakdown
        stages = self.env['pm.task.stage'].search([], order='sequence asc')
        stage_breakdown = [{
            'id': s.id,
            'name': s.name,
            'is_closed': s.is_closed,
            'count': len(tasks.filtered(lambda t: t.stage_id.id == s.id)),
            'percentage': round(len(tasks.filtered(lambda t: t.stage_id.id == s.id)) / total_tasks * 100, 1) if total_tasks else 0.0
        } for s in stages]

        stage_chart = {
            'labels': [s.name for s in stages],
            'data': [len(tasks.filtered(lambda t: t.stage_id.id == s.id)) for s in stages],
            'ids': [s.id for s in stages],
        }

        # Overdue tasks table
        overdue_list = self.env['pm.task'].search(
            [('id', 'in', tasks.ids), ('is_closed', '=', False), ('date_deadline', '<', today)],
            order='date_deadline asc',
            limit=10
        )
        overdue_table = [{
            'id': t.id,
            'name': t.name,
            'customer_name': t.customer_id.exists().name if t.customer_id and t.customer_id.exists() else 'General Request',
            'owner_name': t.owner_id.exists().name if t.owner_id and t.owner_id.exists() else 'Unassigned',
            'assignees': ', '.join(t.user_ids.exists().mapped('name')) or (t.owner_id.exists().name if t.owner_id else 'Unassigned'),
            'date_deadline': str(t.date_deadline),
            'stage': t.stage_id.name if t.stage_id else 'In Progress',
            'priority': t.priority or '1',
        } for t in overdue_list]

        # Blocked tasks table
        blocked_list = self.env['pm.task'].search(
            [('id', 'in', tasks.ids), ('is_blocked', '=', True), ('is_closed', '=', False)],
            order='priority desc, date_deadline asc',
            limit=10
        )
        blocked_table = [{
            'id': t.id,
            'name': t.name,
            'customer_name': t.customer_id.exists().name if t.customer_id and t.customer_id.exists() else 'General Request',
            'owner_name': t.owner_id.exists().name if t.owner_id and t.owner_id.exists() else 'Unassigned',
            'assignees': ', '.join(t.user_ids.exists().mapped('name')) or (t.owner_id.exists().name if t.owner_id else 'Unassigned'),
            'date_deadline': str(t.date_deadline or 'None'),
            'stage': t.stage_id.name if t.stage_id else 'Blocked',
            'priority': t.priority or '1',
        } for t in blocked_list]

        # Metadata for filters (Requester, Task owner, Task type)
        all_non_proj = self.env['pm.task'].search([('project_id', '=', False)])
        requesters = [{'id': p.id, 'name': p.name} for p in all_non_proj.mapped('customer_id').exists() if p]
        
        # Pull distinct task owners directly from owner_id or user_ids
        owner_users = set(all_non_proj.mapped('owner_id').exists()) | set(all_non_proj.mapped('user_ids').exists())
        task_owners = [{'id': u.id, 'name': u.name} for u in owner_users if u.exists()]
        task_owners.sort(key=lambda x: x['name'])

        tags = [{'id': tag.id, 'name': tag.name} for tag in self.env['pm.task.tag'].search([], order='name asc')]

        return {
            'kpi': {
                'total_tasks': total_tasks,
                'completed_tasks': completed_tasks,
                'open_tasks': open_tasks,
                'in_progress_tasks': in_progress_tasks,
                'overdue_tasks': overdue_tasks,
                'blocked_tasks': blocked_tasks,
                'completion_rate': completion_rate,
            },
            'stages': stage_breakdown,
            'charts': {
                'stage_chart': stage_chart,
            },
            'tables': {
                'overdue_table': overdue_table,
                'blocked_table': blocked_table,
            },
            'filters_data': {
                'requesters': requesters,
                'task_owners': task_owners,
                'tags': tags,
            }
        }

    def unlink(self):
        """Soft delete: archive project instead of permanent deletion."""
        return self.write({'active': False})


