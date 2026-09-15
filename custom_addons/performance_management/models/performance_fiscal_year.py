# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceFiscalYear(models.Model):
    _name = 'performance.fiscal.year'
    _description = 'Fiscal Year'
    _order = 'date_start desc'

    name = fields.Char(required=True, string='Fiscal Year')
    date_start = fields.Date(required=True, string='Start Date')
    date_end = fields.Date(required=True, string='End Date')
    active = fields.Boolean(default=True)
    company_id =  fields.Many2one(
        "res.company", default=lambda self: self.env.company, string="Company")

    line_ids = fields.One2many(
        'fiscal.year.line',
        'year_id',
        string='Fiscal Year Details',
        copy=True,
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        'A Fiscal Year with this name already exists.',
    )

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError('The Start Date must be before the End Date.')

class FiscalYearLine(models.Model):
    _name = "fiscal.year.line"
    _description = "Fiscal Year Line"

    year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        required=True,
        ondelete='cascade',
    )
    appraisal_period = fields.Many2one('appraisal.period',
                                       string='Appraisal Period' ,required=True)

    date_start = fields.Date(required=True, string='Start Date')

    date_end =  fields.Date(required=True, string='End Date')

