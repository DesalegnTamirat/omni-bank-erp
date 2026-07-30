from odoo import models,fields,api

class OverTimeConsumption(models.Model):
    _name = 'over.time.consumption'
    _description = 'Over Time Consumption'

    over_time_id = fields.Many2one(
        'over.time',
        required=True,
        ondelete='cascade'
    )

    leave_request_id = fields.Many2one(
        'leave.request.manager',
        required=True,
        ondelete='cascade'
    )

    hours = fields.Float(required=True)
