# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmTaskProgressLog(models.Model):
    _name = 'pm.task.progress.log'
    _description = 'Task Work & Progress Log'
    _order = 'date desc, id desc'

    task_id = fields.Many2one('pm.task', string='Task', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Team Member', default=lambda self: self.env.user, required=True)
    date = fields.Datetime(string='Date & Time', default=fields.Datetime.now, required=True)
    hours_spent = fields.Float(string='Hours Worked', default=0.0)
    progress_percent = fields.Float(string='Reported Progress (%)', default=0.0)
    summary = fields.Text(string='Work Accomplished / Summary', required=True)

    @api.constrains('progress_percent', 'hours_spent')
    def _check_log_values(self):
        for rec in self:
            if not (0.0 <= rec.progress_percent <= 100.0):
                raise ValidationError(_(
                    "Reported Progress must be between 0 and 100 (got %s)."
                ) % rec.progress_percent)
            if rec.hours_spent < 0:
                raise ValidationError(_(
                    "Hours Worked cannot be negative (got %s)."
                ) % rec.hours_spent)
