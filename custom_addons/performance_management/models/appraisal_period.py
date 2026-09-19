from odoo import models, fields, api


class AppraisalPeriod(models.Model):
    _name = 'appraisal.period'
    _description = 'Appraisal Period'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Selection(
        selection=[
            ('Q1', 'Q1'),
            ('Q2', 'Q2'),
            ('H1', 'H1'),
            ('Q3', 'Q3'),
            ('Q4', 'Q4'),
            ('H2', 'H2'),
            ('ANNUAL', 'Annual'),
        ],
        string='Period Code',
        required=True,
        default='H1',
        help='Canonical period code used by the module to determine which '
             'target column (Q1/H1/Q3/H2/Annual) is editable on scorecards.',
    )
    active = fields.Boolean(string='Active', default=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'An Appraisal Period with this code already exists.',
    )

    @api.onchange('name')
    def _onchange_name(self):
        if self.name and not self.code:
            n = self.name.upper()
            if 'H1' in n or 'FIRST HALF' in n or 'SEMI-ANNUAL 1' in n:
                self.code = 'H1'
            elif 'H2' in n or 'SECOND HALF' in n or 'SEMI-ANNUAL 2' in n:
                self.code = 'H2'
            elif 'Q1' in n or 'QUARTER 1' in n:
                self.code = 'Q1'
            elif 'Q2' in n or 'QUARTER 2' in n:
                self.code = 'Q2'
            elif 'Q3' in n or 'QUARTER 3' in n:
                self.code = 'Q3'
            elif 'Q4' in n or 'QUARTER 4' in n:
                self.code = 'Q4'
            elif 'ANNUAL' in n:
                self.code = 'ANNUAL'