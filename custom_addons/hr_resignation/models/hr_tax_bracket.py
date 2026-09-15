from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HrResignationTaxBracket(models.Model):
    _name = 'hr.resignation.tax.bracket'
    _description = 'Severance Income Tax Bracket'
    _order = 'min_amount asc'

    name = fields.Char(string='Bracket Name', required=True)
    min_amount = fields.Float(string='Minimum Amount', required=True, default=0.0)
    max_amount = fields.Float(string='Maximum Amount', required=True, help="Set to 0.0 for infinity/no limit.", default=0.0)
    tax_rate = fields.Float(string='Tax Rate (%)', required=True, default=0.0)
    deduction = fields.Float(string='Addback Deduction', required=True, default=0.0)
    
    @api.constrains('min_amount', 'max_amount')
    def _check_amounts(self):
        for bracket in self:
            if bracket.max_amount > 0 and bracket.min_amount >= bracket.max_amount:
                raise ValidationError(_("Maximum amount must be greater than Minimum amount (or 0 for infinity)."))
