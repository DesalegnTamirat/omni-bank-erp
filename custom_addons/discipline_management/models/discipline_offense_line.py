# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class DisciplineOffenseLine(models.Model):
    _name = 'discipline.offense.line'
    _description = 'Offense Severity Escalation Line'
    _order = 'occurrence_number, sequence, id'

    offense_id = fields.Many2one('discipline.offense', string='Offense Type', required=True, ondelete='cascade')
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=True)
    sequence = fields.Integer(related='severity_level_id.sequence', store=True)
    occurrence_number = fields.Integer(string='Breach Count / Occurrence', default=1, help="1 for 1st breach, 2 for 2nd breach, etc.")

    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Applicable Punishment', required=True, default='first_warning_penalty')

    non_managerial_penalty_pct = fields.Float(string='Non-Managerial Penalty (%)', default=0.0)
    non_managerial_fine_days = fields.Float(string='Non-Managerial Fine (Days)', default=0.0)

    managerial_penalty_pct = fields.Float(string='Managerial Penalty (%)', default=0.0)
    managerial_fine_days = fields.Float(string='Managerial Fine (Days)', default=0.0)

    reset_window_months = fields.Integer(string='Reset Window (Months)', default=3, help="Validity period in months before warning count resets")
    approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager'),
        ('hr_manager', 'HR Manager'),
        ('executive', 'Executive HR / Disciplinary Committee'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Approval Authority', default='hr_manager')

    @api.onchange('severity_level_id')
    def _onchange_severity_level_id(self):
        if self.severity_level_id:
            lvl = self.severity_level_id
            self.punishment_type = lvl.default_punishment_type
            self.non_managerial_penalty_pct = lvl.default_non_managerial_penalty_pct or lvl.default_penalty_percentage
            self.non_managerial_fine_days = lvl.default_non_managerial_fine_days or lvl.default_fine_days
            self.managerial_penalty_pct = lvl.default_managerial_penalty_pct or lvl.default_penalty_percentage
            self.managerial_fine_days = lvl.default_managerial_fine_days or lvl.default_fine_days
            self.reset_window_months = lvl.default_reset_window_months or 3
            self.approval_authority = lvl.default_approval_authority
