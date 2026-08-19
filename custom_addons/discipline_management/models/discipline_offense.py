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
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=True, tracking=True)
    severity_level = fields.Char(related='severity_level_id.code', string='Severity Level Code', store=True, readonly=True)

    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Written Warning + 20% Salary Deduction'),
        ('second_warning_penalty', 'Second Written Warning + 10% Salary Deduction'),
        ('first_warning_penalty', 'First Written Warning + 5% Salary Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Applicable Punishment', compute='_compute_severity_defaults', store=True, readonly=True, tracking=True)

    penalty_percentage = fields.Float(
        string='Penalty Percentage (%)',
        compute='_compute_severity_defaults',
        store=True,
        readonly=True,
        help='Monthly salary deduction percentage driven by the selected Severity Level',
        tracking=True
    )
    approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager'),
        ('hr_manager', 'HR Manager'),
        ('executive', 'Executive HR / Disciplinary Committee'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Approval Authority', compute='_compute_severity_defaults', store=True, readonly=True, tracking=True)

    description = fields.Text(string='Offense Description & Guidelines')
    active = fields.Boolean(default=True, tracking=True)
    policy_version_id = fields.Many2one('discipline.policy.version', string='Policy Version', tracking=True)

    @api.depends('severity_level_id', 'severity_level_id.default_punishment_type', 'severity_level_id.default_penalty_percentage', 'severity_level_id.default_approval_authority')
    def _compute_severity_defaults(self):
        """Driven directly from the selected Severity Level master configuration."""
        for rec in self:
            if rec.severity_level_id:
                rec.punishment_type = rec.severity_level_id.default_punishment_type
                rec.penalty_percentage = rec.severity_level_id.default_penalty_percentage
                rec.approval_authority = rec.severity_level_id.default_approval_authority
            else:
                rec.punishment_type = False
                rec.penalty_percentage = 0.0
                rec.approval_authority = 'hr_manager'

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
