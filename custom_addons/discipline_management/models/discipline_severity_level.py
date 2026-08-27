# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineSeverityLevel(models.Model):
    _name = 'discipline.severity.level'
    _description = 'Disciplinary Severity Level'
    _order = 'sequence, id'

    name = fields.Char(string='Severity Level Name', required=True, tracking=True)
    code = fields.Char(string='Level Code', required=True, tracking=True, help="Unique identifier, e.g. level_1, level_2")
    sequence = fields.Integer(string='Sequence / Rank', default=10, help="Lower number indicates higher severity")
    
    is_dismissal = fields.Boolean(string='Triggers Dismissal / Termination', default=False, help="Check if this severity level mandates dismissal")
    
    default_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Default Punishment Type', default='first_warning_penalty', tracking=True)

    default_penalty_percentage = fields.Float(string='Default Penalty Percentage (%)', default=0.0)
    default_fine_days = fields.Float(string='Default Salary Fine (Days)', default=0.0)

    default_non_managerial_penalty_pct = fields.Float(string='Default Non-Managerial Penalty (%)', default=0.0)
    default_non_managerial_fine_days = fields.Float(string='Default Non-Managerial Fine (Days)', default=0.0)
    
    default_managerial_penalty_pct = fields.Float(string='Default Managerial Penalty (%)', default=0.0)
    default_managerial_fine_days = fields.Float(string='Default Managerial Fine (Days)', default=0.0)

    default_reset_window_months = fields.Integer(string='Default Reset Window (Months)', default=3, help="Validity period in months before warning count resets")

    default_approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager'),
        ('hr_manager', 'HR Manager'),
        ('executive', 'Executive HR / Disciplinary Committee'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Default Approval Authority', default='hr_manager', tracking=True)

    description = fields.Text(string='Description & Guidelines')
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Severity Level Code must be unique!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
            raise UserError(_('Unauthorized modification: Only HR Administrators can configure disciplinary severity levels.'))
        return super().create(vals_list)

    def write(self, vals):
        if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
            raise UserError(_('Unauthorized modification: Only HR Administrators can edit disciplinary severity levels.'))
        return super().write(vals)
