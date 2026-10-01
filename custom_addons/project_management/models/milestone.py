# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmMilestone(models.Model):
    _name = 'pm.milestone'
    _description = 'Project Milestone'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, date_deadline asc, id desc'

    name = fields.Char(string='Milestone Name', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    
    weight = fields.Float(string='Weight (%)', default=1.0, help='Weight of this milestone towards the overall project.', tracking=True)
    date_start = fields.Date(string='Start Date')
    date_deadline = fields.Date(string='Target Deadline', tracking=True)
    
    # Auto-computed state based on deliverable and task progress rollups
    state = fields.Selection([
        ('draft', 'Planned'),
        ('in_progress', 'In Progress'),
        ('at_risk', 'At Risk'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_milestone_state', store=True, readonly=False, default='draft', tracking=True)
    
    description = fields.Html(string='Milestone Scope & Objectives')
    color = fields.Integer(string='Color', default=0)

    deliverable_ids = fields.One2many('pm.deliverable', 'milestone_id', string='Deliverables')
    task_ids = fields.One2many('pm.task', 'milestone_id', string='Tasks')
    
    deliverable_count = fields.Integer(string='Total Deliverables', compute='_compute_task_stats', store=True)
    task_count = fields.Integer(string='Total Tasks', compute='_compute_task_stats', store=True)
    closed_task_count = fields.Integer(string='Completed Tasks', compute='_compute_task_stats', store=True)
    progress_rate = fields.Float(string='Progress (%)', compute='_compute_task_stats', store=True)

    @api.constrains('date_start', 'date_deadline', 'project_id', 'deliverable_ids')
    def _check_milestone_dates(self):
        for rec in self:
            if rec.date_start and rec.date_deadline and rec.date_deadline < rec.date_start:
                raise ValidationError(_("Milestone '%s': Target Deadline (%s) cannot be earlier than Start Date (%s)!") % (
                    rec.name, rec.date_deadline, rec.date_start
                ))
            if rec.project_id:
                if rec.project_id.date_start and rec.date_start and rec.date_start < rec.project_id.date_start:
                    raise ValidationError(_("Milestone '%s': Start Date (%s) cannot be earlier than the Project's Start Date (%s)!") % (
                        rec.name, rec.date_start, rec.project_id.date_start
                    ))
                if rec.project_id.date_end and rec.date_deadline and rec.date_deadline > rec.project_id.date_end:
                    raise ValidationError(_("Milestone '%s': Deadline (%s) cannot exceed the Project's Target End Date (%s)!") % (
                        rec.name, rec.date_deadline, rec.project_id.date_end
                    ))
            # Validate milestone bounds vs its child deliverables
            for deliv in rec.deliverable_ids:
                if rec.date_start and deliv.date_start and deliv.date_start < rec.date_start:
                    raise ValidationError(_(
                        "Milestone '%s': Start Date (%s) cannot be later than Deliverable '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, deliv.name, deliv.date_start))
                if rec.date_deadline and deliv.date_deadline and deliv.date_deadline > rec.date_deadline:
                    raise ValidationError(_(
                        "Milestone '%s': Target Deadline (%s) cannot be earlier than Deliverable '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_deadline, deliv.name, deliv.date_deadline))

    @api.constrains('weight', 'project_id', 'deliverable_ids')
    def _check_milestone_weight(self):
        for rec in self:
            if rec.weight <= 0:
                raise ValidationError(_(
                    "Milestone '%s': Weight must be greater than zero."
                ) % rec.name)
            if rec.project_id:
                milestones = self.env['pm.milestone'].search([('project_id', '=', rec.project_id.id)])
                total_weight = sum(m.weight for m in milestones)
                if round(total_weight, 2) > 100.0:
                    raise ValidationError(_(
                        "Milestone '%s': Total milestone weight under Project '%s' is %.2f%%, which exceeds 100%%!"
                    ) % (rec.name, rec.project_id.name, total_weight))
            if rec.deliverable_ids:
                total_deliv_weight = sum(d.weight for d in rec.deliverable_ids)
                if round(total_deliv_weight, 2) > round(rec.weight, 2):
                    raise ValidationError(_(
                        "Milestone '%s': Allocated weight (%.2f%%) cannot be less than the total weight of its deliverables (%.2f%%)!"
                    ) % (rec.name, rec.weight, total_deliv_weight))

    @api.depends('deliverable_ids', 'deliverable_ids.progress_rate', 'deliverable_ids.weight',
                 'task_ids', 'task_ids.is_closed', 'task_ids.progress_rate', 'task_ids.weight')
    def _compute_task_stats(self):
        for rec in self:
            total_tasks = len(rec.task_ids)
            closed_tasks = len(rec.task_ids.filtered(lambda t: t.is_closed))
            rec.task_count = total_tasks
            rec.closed_task_count = closed_tasks
            rec.deliverable_count = len(rec.deliverable_ids)
            
            # Weighted rollup: Deliverables -> Milestone
            if rec.deliverable_ids:
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
    def _compute_milestone_state(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if (rec.task_count > 0 and rec.closed_task_count == rec.task_count) or rec.progress_rate >= 100.0:
                rec.state = 'completed'
            elif rec.progress_rate > 0.0 or (rec.task_count > 0 and any(not t.is_closed and t.stage_id.name != 'To Do' for t in rec.task_ids)):
                rec.state = 'in_progress'
            elif rec.task_count == 0 or rec.closed_task_count == 0:
                if rec.state != 'in_progress':
                    rec.state = 'draft'
