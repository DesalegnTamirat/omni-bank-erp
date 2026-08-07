from odoo import models, fields


class HrTrainingHistory(models.Model):
    _name = 'hr.training.history'
    _description = 'Employee Training History'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    training_name = fields.Char(string='Training Name')
    training_type = fields.Char(string='Training Type')
    institution_name = fields.Char(string='Name of Institution')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    status = fields.Selection([
        ('completed', 'Completed'),
        ('in_progress', 'In Progress'),
        ('cancelled', 'Cancelled'),
        ('planned', 'Planned'),
    ], string='Status')
    comments = fields.Text(string='Comments')