from odoo import fields, models
class AutomaticScorecardNotifyWizard(models.TransientModel):
    _name = 'automatic.scorecard.notify.wizard'
    _description = 'Automatic Scorecard Wizard'
    fiscal_year = fields.Many2one('performance.fiscal.year', string='Fiscal Year', required=True)
    planning_name = fields.Many2one('corporate.scorecard', string='Planning Name', required=True)
    appraisal_period = fields.Selection(
        selection=[
            ('Q1', 'Q1'),
            ('H1', 'H1'),
            ('Q3', 'Q3'),
            ('H2', 'H2'),
        ], string='Appraisal Period', required=True
    )
    def action_populate(self):
        # logic will be add later
        pass