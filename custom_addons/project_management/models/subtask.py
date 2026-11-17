# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmTaskSubtask(models.Model):
    _name = 'pm.task.subtask'
    _description = 'Task Sub-task / Action Item'
    _order = 'sequence, date_deadline asc, id asc'

    name = fields.Char(string='Action / Sub-task Title', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    task_id = fields.Many2one('pm.task', string='Parent Task', required=True, ondelete='cascade')
    
    is_done = fields.Boolean(string='Done', default=False)
    weight = fields.Float(string='Weight (%)', default=1.0, help='Weight of this subtask towards parent task progress.')
    user_ids = fields.Many2many('res.users', 'pm_subtask_user_rel', 'subtask_id', 'user_id', string='Assignees')
    project_member_ids = fields.Many2many(
        'res.users',
        compute='_compute_project_member_ids',
        string='Available Project Team Members'
    )
    
    date_start = fields.Date(string='Start Date')
    date_deadline = fields.Date(string='Deadline')
    allocated_hours = fields.Float(string='Allocated Time (Hours)', default=0.0)
    active = fields.Boolean(string='Active', default=True)

    project_id = fields.Many2one('pm.project', string='Project', compute='_compute_hierarchy', store=True, readonly=False)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', compute='_compute_hierarchy', store=True, readonly=False)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable', compute='_compute_hierarchy', store=True, readonly=False)

    @api.depends('task_id', 'task_id.project_id', 'task_id.milestone_id', 'task_id.deliverable_id')
    def _compute_hierarchy(self):
        for rec in self:
            if rec.task_id:
                rec.project_id = rec.task_id.project_id
                rec.milestone_id = rec.task_id.milestone_id
                rec.deliverable_id = rec.task_id.deliverable_id
            else:
                rec.project_id = rec.project_id or False
                rec.milestone_id = rec.milestone_id or False
                rec.deliverable_id = rec.deliverable_id or False

    @api.depends('project_id', 'project_id.member_ids', 'project_id.manager_id', 'project_id.coordinator_id', 'task_id', 'task_id.project_id')
    def _compute_project_member_ids(self):
        internal_users = self.env['res.users'].search([('active', '=', True), ('share', '=', False)])
        for rec in self:
            proj = rec.project_id or (rec.task_id and rec.task_id.project_id)
            if proj:
                pool = proj.member_ids | proj.manager_id | proj.coordinator_id
                pool = pool.filtered(lambda u: u.id)
                rec.project_member_ids = pool if pool else internal_users
            else:
                rec.project_member_ids = internal_users

    @api.constrains('date_start', 'date_deadline', 'task_id')
    def _check_subtask_dates(self):
        for rec in self:
            if rec.date_start and rec.date_deadline and rec.date_deadline < rec.date_start:
                raise ValidationError(_("Sub-task '%s': Deadline (%s) cannot be earlier than Start Date (%s)!") % (
                    rec.name, rec.date_deadline, rec.date_start
                ))
            if rec.task_id:
                if rec.task_id.date_start and rec.date_start and rec.date_start < rec.task_id.date_start:
                    raise ValidationError(_("Sub-task '%s': Start Date (%s) cannot be earlier than parent Task Start Date (%s)!") % (
                        rec.name, rec.date_start, rec.task_id.date_start
                    ))
                if rec.task_id.date_deadline and rec.date_deadline and rec.date_deadline > rec.task_id.date_deadline:
                    raise ValidationError(_("Sub-task '%s': Deadline (%s) cannot exceed parent Task Deadline (%s)!") % (
                        rec.name, rec.date_deadline, rec.task_id.date_deadline
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.task_id and rec.user_ids:
                rec.task_id.write({'user_ids': [(4, u.id) for u in rec.user_ids]})
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'user_ids' in vals or 'task_id' in vals:
            for rec in self:
                if rec.task_id and rec.user_ids:
                    rec.task_id.write({'user_ids': [(4, u.id) for u in rec.user_ids]})
        return res

    def unlink(self):
        """Soft delete: archive subtask instead of permanent deletion."""
        return self.write({'active': False})

