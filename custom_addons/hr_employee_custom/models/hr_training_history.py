from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


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

    @api.constrains('start_date', 'end_date')
    def _check_start_end_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                if rec.start_date > rec.end_date:
                    raise ValidationError(
                        _("Invalid Date Range: Start Date (%s) cannot be greater than End Date (%s). "
                          "End Date cannot be earlier than Start Date.")
                        % (rec.start_date, rec.end_date)
                    )

    @api.onchange('start_date', 'end_date')
    def _onchange_start_end_dates(self):
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                return {
                    'warning': {
                        'title': _("Invalid Date Range"),
                        'message': _("Start Date cannot be greater than End Date, and End Date cannot be earlier than Start Date."),
                    }
                }
