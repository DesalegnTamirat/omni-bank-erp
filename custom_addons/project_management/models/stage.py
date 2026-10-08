# -*- coding: utf-8 -*-
from odoo import fields, models

class PmTaskStage(models.Model):
    _name = 'pm.task.stage'
    _description = 'Task Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    is_closed = fields.Boolean(string='Is Done/Closed', default=False,
                               help='Tasks in this stage will be considered completed.')
    fold = fields.Boolean(string='Folded in Kanban', default=False,
                         help='This stage will appear collapsed in Kanban view.')
