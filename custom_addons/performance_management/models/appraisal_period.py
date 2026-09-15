from odoo import models, fields, api


class AppraisalPeriod(models.Model):
    _name = 'appraisal.period'
    _description = 'Appraisal Period'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Selection(
        selection=[
            ('Q1', 'Q1'),
            ('H1', 'H1'),
            ('Q3', 'Q3'),
            ('H2', 'H2'),
        ],
        string='Period Code',
        required=True,
        help='Canonical period code used by the module to determine which '
             'target column (Q1/H1/Q3/H2) is editable on scorecards, '
             'independent of how this period is named/labeled.',
    )
    active = fields.Boolean(string='Active', default=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'An Appraisal Period with this code already exists.',
    )