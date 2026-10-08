# -*- coding: utf-8 -*-
from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmDeliverable(models.Model):
    _name = 'pm.deliverable'
    _description = 'Deliverable / Major Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, date_deadline asc, id desc'

    name = fields.Char(string='Deliverable / Major Activity Title', required=True, tracking=True)
    code = fields.Char(string='Code / ID', readonly=True, copy=False, default=lambda self: _('New'))
    sequence = fields.Integer(string='Sequence', default=10)
    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null', tracking=True,
                                  domain="[('project_id', '=', project_id)]")
    
    weight = fields.Float(string='Weight (%)', default=1.0, help='Weight of this deliverable towards overall project/milestone progress.', tracking=True)
    date_start = fields.Date(string='Start Date')
    date_deadline = fields.Date(string='Target Deadline', tracking=True)
    
    state = fields.Selection([
        ('draft', 'Planned'),
        ('in_progress', 'In Progress'),
        ('at_risk', 'At Risk'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_deliverable_state', store=True, readonly=False, default='draft', tracking=True)
    
    description = fields.Html(string='Deliverable Description & Notes')
    color = fields.Integer(string='Color', default=0)

    task_ids = fields.One2many('pm.task', 'deliverable_id', string='Tasks')
    task_count = fields.Integer(string='Total Tasks', compute='_compute_task_stats', store=True)
    closed_task_count = fields.Integer(string='Completed Tasks', compute='_compute_task_stats', store=True)
    progress_rate = fields.Float(string='Progress (%)', compute='_compute_task_stats', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.deliverable') or _('New')
            # Auto-infer project_id from milestone_id if not explicitly provided
            if vals.get('milestone_id') and not vals.get('project_id'):
                m = self.env['pm.milestone'].browse(vals['milestone_id'])
                if m.project_id:
                    vals['project_id'] = m.project_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('milestone_id') and not vals.get('project_id'):
            m = self.env['pm.milestone'].browse(vals['milestone_id'])
            if m.project_id:
                vals['project_id'] = m.project_id.id
        return super().write(vals)

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id and self.milestone_id.project_id:
            self.project_id = self.milestone_id.project_id

    @api.constrains('date_start', 'date_deadline', 'project_id', 'milestone_id')
    def _check_deliverable_dates(self):
        for rec in self:
            if rec.date_start and rec.date_deadline and rec.date_deadline < rec.date_start:
                raise ValidationError(_("Deliverable '%s': Target Deadline (%s) cannot be earlier than Start Date (%s)!") % (
                    rec.name, rec.date_deadline, rec.date_start
                ))
            if rec.project_id:
                if rec.project_id.date_start and rec.date_start and rec.date_start < rec.project_id.date_start:
                    raise ValidationError(_("Deliverable '%s': Start Date (%s) cannot be earlier than Project Start Date (%s)!") % (
                        rec.name, rec.date_start, rec.project_id.date_start
                    ))
                if rec.project_id.date_end and rec.date_deadline and rec.date_deadline > rec.project_id.date_end:
                    raise ValidationError(_("Deliverable '%s': Target Deadline (%s) cannot exceed Project Target End Date (%s)!") % (
                        rec.name, rec.date_deadline, rec.project_id.date_end
                    ))
            if rec.milestone_id:
                if rec.milestone_id.date_start and rec.date_start and rec.date_start < rec.milestone_id.date_start:
                    raise ValidationError(_(
                        "Deliverable '%s': Start Date (%s) cannot be earlier than Milestone '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, rec.milestone_id.name, rec.milestone_id.date_start))
                if rec.milestone_id.date_deadline and rec.date_deadline and rec.date_deadline > rec.milestone_id.date_deadline:
                    raise ValidationError(_(
                        "Deliverable '%s': Target Deadline (%s) cannot exceed Milestone '%s' Target Deadline (%s)!"
                    ) % (rec.name, rec.date_deadline, rec.milestone_id.name, rec.milestone_id.date_deadline))
            for task in rec.task_ids:
                if rec.date_start and task.date_start and task.date_start < rec.date_start:
                    raise ValidationError(_(
                        "Deliverable '%s': Start Date (%s) cannot be later than Task '%s' Start Date (%s)!"
                    ) % (rec.name, rec.date_start, task.name, task.date_start))
                if rec.date_deadline and task.date_deadline and task.date_deadline > rec.date_deadline:
                    raise ValidationError(_(
                        "Deliverable '%s': Target Deadline (%s) cannot be earlier than Task '%s' Deadline (%s)!"
                    ) % (rec.name, rec.date_deadline, task.name, task.date_deadline))

    @api.constrains('weight', 'milestone_id', 'task_ids')
    def _check_weight(self):
        for rec in self:
            if rec.weight <= 0:
                raise ValidationError(_(
                    "Deliverable '%s': Weight must be greater than zero."
                ) % rec.name)
            if rec.milestone_id and rec.milestone_id.weight > 0:
                deliverables = self.env['pm.deliverable'].search([('milestone_id', '=', rec.milestone_id.id)])
                total_weight = sum(d.weight for d in deliverables)
                if round(total_weight, 2) > round(rec.milestone_id.weight, 2):
                    raise ValidationError(_(
                        "Deliverable '%s': Total deliverable weight under Milestone '%s' is %.2f%%, which exceeds Milestone allocated weight of %.2f%%!"
                    ) % (rec.name, rec.milestone_id.name, total_weight, rec.milestone_id.weight))
            if rec.task_ids:
                total_task_weight = sum(t.weight for t in rec.task_ids)
                if round(total_task_weight, 2) > round(rec.weight, 2):
                    raise ValidationError(_(
                        "Deliverable '%s': Allocated weight (%.2f%%) cannot be less than the total weight of its tasks (%.2f%%)!"
                    ) % (rec.name, rec.weight, total_task_weight))

    @api.depends('task_ids', 'task_ids.is_closed', 'task_ids.progress_rate', 'task_ids.weight')
    def _compute_task_stats(self):
        for rec in self:
            total = len(rec.task_ids)
            closed = len(rec.task_ids.filtered(lambda t: t.is_closed))
            rec.task_count = total
            rec.closed_task_count = closed
            if total > 0:
                total_weight = sum(t.weight for t in rec.task_ids)
                if total_weight > 0:
                    rec.progress_rate = sum(t.progress_rate * t.weight for t in rec.task_ids) / total_weight
                else:
                    rec.progress_rate = sum(t.progress_rate for t in rec.task_ids) / total
            else:
                rec.progress_rate = 0.0

    @api.depends('task_count', 'closed_task_count', 'progress_rate', 'date_deadline')
    def _compute_deliverable_state(self):
        today = date.today()
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec.task_count > 0 and rec.closed_task_count == rec.task_count and rec.progress_rate >= 100.0:
                rec.state = 'completed'
            elif rec.progress_rate > 0.0 or (rec.task_count > 0 and any(not t.is_closed and t.stage_id.name != 'To Do' for t in rec.task_ids)):
                rec.state = 'in_progress'
            elif rec.task_count == 0:
                if rec.date_deadline and rec.date_deadline < today:
                    rec.state = 'at_risk'
                elif rec.state != 'in_progress':
                    rec.state = 'draft'
            elif rec.closed_task_count == 0:
                if rec.date_deadline and rec.date_deadline < today:
                    rec.state = 'at_risk'
                elif rec.state != 'in_progress':
                    rec.state = 'draft'
