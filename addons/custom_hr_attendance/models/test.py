from odoo import models, fields, api
from odoo.exceptions import ValidationError
import math


class Mall(models.Model):
    _name = 'mall.shop'
    _description = 'Shop'

    name = fields.Char(string='Name')
    floor = fields.Char(string='Floor')
    closing_time = fields.Float(
        string='Closing Time',
        help='Time in hours (e.g., 9.5 for 9:30)',
        digits=(16, 4)  # Store with 4 decimal places for accuracy
    )

    @api.constrains('closing_time')
    def _check_closing_time(self):
        for record in self:
            if record.closing_time:
                decimal_prt = round((record.closing_time - int(record.closing_time)) * 100)
                print("closing time:",record.closing_time)
                print(("minutes",decimal_prt))
                if decimal_prt > 60:
                    raise ValidationError("Minutes must be less than 60")
