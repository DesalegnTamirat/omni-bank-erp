# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class DisciplineOffenseLine(models.Model):
    _name = 'discipline.offense.line'
    _description = 'Offense Repetition / Breach Escalation Line'
    _order = 'occurrence_number, sequence, id'

    offense_id = fields.Many2one('discipline.offense', string='Offense Type', required=True, ondelete='cascade')
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=False)
    sequence = fields.Integer(related='severity_level_id.sequence', store=True)
    occurrence_number = fields.Integer(string='Breach Occurrence Tier', default=1, required=True, help="1 for 1st breach, 2 for 2nd breach, 3 for 3rd breach, etc.")
    occurrence_label = fields.Char(string='Breach Label', compute='_compute_occurrence_label', store=True)

    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Prescribed Punishment', required=True, default='first_warning_penalty')

    fine_days = fields.Float(string='Salary Fine (Days)', default=0.0)
    penalty_percentage = fields.Float(string='Penalty Percentage (%)', default=0.0)

    non_managerial_penalty_pct = fields.Float(string='Non-Managerial Penalty (%)', default=0.0)
    non_managerial_fine_days = fields.Float(string='Non-Managerial Fine (Days)', default=0.0)

    managerial_penalty_pct = fields.Float(string='Managerial Penalty (%)', default=0.0)
    managerial_fine_days = fields.Float(string='Managerial Fine (Days)', default=0.0)

    warning_validity_months = fields.Integer(string='Warning Validity (Months)', default=3, help="Validity period in months before warning count resets")
    reset_window_months = fields.Integer(string='Reset Window (Months)', default=3)
    approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager / Coach'),
        ('hr_manager', 'HR Manager / Directorate'),
        ('executive', 'Executive HR / Disciplinary Committee'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Approval Authority', default='hr_manager')
    notes = fields.Text(string='Repetition Notes & Conditions')

    @api.depends('occurrence_number')
    def _compute_occurrence_label(self):
        ordinal_map = {
            1: _('1st Breach / የመጀመሪያ ጊዜ ጥፋት'),
            2: _('2nd Breach / የሁለተኛ ጊዜ ጥፋት'),
            3: _('3rd Breach / የሶስተኛ ጊዜ ጥፋት'),
            4: _('4th Breach / የአራተኛ ጊዜ ጥፋት'),
            5: _('5th Breach / የአምስተኛ ጊዜ ጥፋት'),
        }
        for rec in self:
            rec.occurrence_label = ordinal_map.get(rec.occurrence_number, _('%sth Breach / የ%sኛ ጊዜ ጥፋት') % (rec.occurrence_number, rec.occurrence_number))

    @api.onchange('severity_level_id')
    def _onchange_severity_level_id(self):
        if self.severity_level_id:
            lvl = self.severity_level_id
            self.punishment_type = lvl.default_punishment_type
            self.fine_days = lvl.default_fine_days
            self.penalty_percentage = lvl.default_penalty_percentage
            self.non_managerial_penalty_pct = lvl.default_non_managerial_penalty_pct or lvl.default_penalty_percentage
            self.non_managerial_fine_days = lvl.default_non_managerial_fine_days or lvl.default_fine_days
            self.managerial_penalty_pct = lvl.default_managerial_penalty_pct or lvl.default_penalty_percentage
            self.managerial_fine_days = lvl.default_managerial_fine_days or lvl.default_fine_days
            self.warning_validity_months = lvl.default_reset_window_months or 3
            self.reset_window_months = lvl.default_reset_window_months or 3
            self.approval_authority = lvl.default_approval_authority
