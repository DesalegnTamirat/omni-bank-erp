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
    
    date_start = fields.Date(string='Start Date')
    date_deadline = fields.Date(string='Deadline')
    allocated_hours = fields.Float(string='Allocated Time (Hours)', default=0.0)

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
