# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineOffenseCategory(models.Model):
    _name = 'discipline.offense.category'
    _description = 'Disciplinary Offense Category'
    _order = 'name'

    name = fields.Char(string='Category Name', required=True)
    code = fields.Char(string='Category Code', required=True)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    offense_ids = fields.One2many('discipline.offense', 'category_id', string='Offenses')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Category Code must be unique!')
    ]


class DisciplineOffense(models.Model):
    _name = 'discipline.offense'
    _description = 'Disciplinary Offense Definition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'severity_level, name'

    name = fields.Char(string='Offense Title', required=True, tracking=True)
    category_id = fields.Many2one('discipline.offense.category', string='Offense Category', required=True, tracking=True)
    severity_level = fields.Selection([
        ('level_1', 'Level 1 (Critical - Dismissal)'),
        ('level_2', 'Level 2 (Very High - Final Written Warning + 20% Penalty)'),
        ('level_3', 'Level 3 (High - Second Written Warning + 10% Penalty)'),
        ('level_4', 'Level 4 (Moderate - First Written Warning + 5% Penalty)'),
        ('level_5', 'Level 5 (Minor - Recorded Verbal Warning)'),
    ], string='Severity Level', required=True, tracking=True)

    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Written Warning + 20% Salary Deduction'),
        ('second_warning_penalty', 'Second Written Warning + 10% Salary Deduction'),
        ('first_warning_penalty', 'First Written Warning + 5% Salary Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Applicable Punishment', required=True, default='first_warning_penalty', tracking=True)

    penalty_percentage = fields.Float(
        string='Penalty Percentage (%)',
        help='Monthly salary deduction percentage enforced by this offense level',
        tracking=True
    )
    approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager'),
        ('hr_manager', 'HR Manager'),
        ('executive', 'Executive HR / Disciplinary Committee'),
    ], string='Required Approval Authority', required=True, default='hr_manager', tracking=True)

    description = fields.Text(string='Offense Description & Guidelines')
    active = fields.Boolean(default=True, tracking=True)
    policy_version_id = fields.Many2one('discipline.policy.version', string='Policy Version', tracking=True)

    @api.onchange('severity_level')
    def _onchange_severity_level(self):
        """Auto-populate default standard penalties based on ."""
        if self.severity_level == 'level_1':
            self.punishment_type = 'dismissal'
            self.penalty_percentage = 0.0
            self.approval_authority = 'executive'
        elif self.severity_level == 'level_2':
            self.punishment_type = 'final_warning_penalty'
            self.penalty_percentage = 20.0
            self.approval_authority = 'hr_manager'
        elif self.severity_level == 'level_3':
            self.punishment_type = 'second_warning_penalty'
            self.penalty_percentage = 10.0
            self.approval_authority = 'hr_manager'
        elif self.severity_level == 'level_4':
            self.punishment_type = 'first_warning_penalty'
            self.penalty_percentage = 5.0
            self.approval_authority = 'direct_manager'
        elif self.severity_level == 'level_5':
            self.punishment_type = 'verbal_warning'
            self.penalty_percentage = 0.0
            self.approval_authority = 'direct_manager'

    @api.constrains('penalty_percentage')
    def _check_penalty_percentage(self):
        for rec in self:
            if rec.penalty_percentage < 0.0 or rec.penalty_percentage > 100.0:
                raise ValidationError(_('Penalty percentage must be between 0% and 100%.'))

    @api.model_create_multi
    def create(self, vals_list):
        # Modification Prevention - Only HR Admin can configure punishment rules
        if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
            raise UserError(_('Unauthorized modification: Only HR Administrators can create disciplinary offense configurations.'))
        return super().create(vals_list)

    def write(self, vals):
        # Modification Prevention
        sensitive_fields = {'severity_level', 'punishment_type', 'penalty_percentage', 'approval_authority'}
        if set(vals.keys()).intersection(sensitive_fields):
            if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
                raise UserError(_('Unauthorized modification: Only HR Administrators can update disciplinary punishment rules and severity levels.'))
        return super().write(vals)
