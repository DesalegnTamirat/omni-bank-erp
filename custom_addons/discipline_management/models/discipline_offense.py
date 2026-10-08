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
    _inherit = ['mail.thread']
    _order = 'article_number, sub_article_code, severity_level, name'
    _rec_names_search = ['name', 'sub_article_code', 'article_number', 'description']

    name = fields.Char(string='Offense Title', required=True, tracking=True)
    category_id = fields.Many2one('discipline.offense.category', string='Offense Category', required=True, tracking=True)
    article_id = fields.Many2one('discipline.article', string='Governing Article', tracking=True)
    article_number = fields.Char(related='article_id.article_number', string='Article Number', store=True, readonly=True)
    sub_article_code = fields.Char(string='Sub-Article / Clause Code', tracking=True, help="e.g. 33.4.2 (ሀ), 33.8.13, 10.4.1(a)")
    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', related='article_id.policy_version_id', store=True, readonly=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial Staff'),
        ('managerial', 'Managerial Staff'),
        ('all', 'All Bank Staff'),
    ], string='Applicable Staff Category', default='all', tracking=True)

    severity_level_id = fields.Many2one('discipline.severity.level', string='Default Severity Level', tracking=True)
    severity_level = fields.Char(string='Severity Level Code', compute='_compute_severity_level', store=True, readonly=True)

    @api.depends('severity_level_id', 'severity_level_id.code', 'article_id.severity_level_id', 'article_id.severity_level_id.code')
    def _compute_severity_level(self):
        for rec in self:
            rec.severity_level = rec.severity_level_id.code or (rec.article_id and rec.article_id.severity_level_id and rec.article_id.severity_level_id.code) or False

    description = fields.Text(string='Offense Description & Guidelines')
    full_clause_text = fields.Text(string='Verbatim Statutory Clause Text (Amharic / English)', tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    # Penalty Determination Model
    penalty_mode = fields.Selection([
        ('level_default', 'Standard Severity Level Default'),
        ('article_override', 'Custom Article / Clause Penalty Override'),
        ('repetition_escalation', 'Multi-Tier Progressive Repetition Ladder'),
    ], string='Penalty Determination Mode', default='level_default', required=True, tracking=True)

    # Custom Penalty Overrides
    custom_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine (Specific Days)'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Custom Prescribed Punishment', tracking=True)
    custom_fine_days = fields.Float(string='Custom Salary Fine (Days)', default=0.0, tracking=True)
    custom_penalty_percentage = fields.Float(string='Custom Penalty Percentage (%)', default=0.0, tracking=True)
    custom_warning_validity_months = fields.Integer(string='Warning Validity (Months)', default=0, tracking=True)

    # Standard / Default fallback
    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine (Specific Days)'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Default Applicable Punishment', default='first_warning_penalty', tracking=True)

    penalty_percentage = fields.Float(string='Default Penalty Percentage (%)', default=0.0, tracking=True)
    fine_days = fields.Float(string='Default Salary Fine (Days)', default=0.0, tracking=True)
    approval_authority = fields.Selection([
        ('direct_manager', 'Direct Manager / Coach'),
        ('hr_manager', 'HR Manager / Directorate'),
        ('executive', 'Executive HR / Disciplinary Committee'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Default Approval Authority', default='direct_manager', tracking=True)

    line_ids = fields.One2many('discipline.offense.line', 'offense_id', string='Repetition Escalation Lines', copy=True)

    @api.onchange('article_id')
    def _onchange_article_id(self):
        if self.article_id:
            if self.article_id.severity_level_id and not self.severity_level_id:
                self.severity_level_id = self.article_id.severity_level_id
            if self.article_id.staff_category:
                self.staff_category = self.article_id.staff_category

    @api.onchange('severity_level_id')
    def _onchange_severity_level_id(self):
        if self.severity_level_id:
            lvl = self.severity_level_id
            if not self.punishment_type or self.punishment_type == 'first_warning_penalty':
                self.punishment_type = lvl.default_punishment_type
            self.penalty_percentage = lvl.default_penalty_percentage
            self.fine_days = lvl.default_fine_days
            self.approval_authority = lvl.default_approval_authority

    @api.onchange('category_id')
    def _onchange_category_populate_lines(self):
        """Auto-populate all active Severity Levels as default escalation lines if grid is empty."""
        if self.penalty_mode == 'repetition_escalation' and not self.line_ids:
            self.action_populate_default_severity_lines()

    def action_populate_default_severity_lines(self):
        """Pre-fill offense escalation lines from all active Severity Levels."""
        levels = self.env['discipline.severity.level'].search([('active', '=', True)], order='sequence, id')
        lines = []
        for idx, lvl in enumerate(levels, start=1):
            lines.append((0, 0, {
                'severity_level_id': lvl.id,
                'occurrence_number': idx,
                'punishment_type': lvl.default_punishment_type,
                'fine_days': lvl.default_non_managerial_fine_days or lvl.default_fine_days,
                'penalty_percentage': lvl.default_non_managerial_penalty_pct or lvl.default_penalty_percentage,
                'non_managerial_penalty_pct': lvl.default_non_managerial_penalty_pct or lvl.default_penalty_percentage,
                'non_managerial_fine_days': lvl.default_non_managerial_fine_days or lvl.default_fine_days,
                'managerial_penalty_pct': lvl.default_managerial_penalty_pct or lvl.default_penalty_percentage,
                'managerial_fine_days': lvl.default_managerial_fine_days or lvl.default_fine_days,
                'warning_validity_months': lvl.default_reset_window_months or 3,
                'reset_window_months': lvl.default_reset_window_months or 3,
                'approval_authority': lvl.default_approval_authority,
            }))
        if lines:
            self.line_ids = [(5, 0, 0)] + lines

    def action_create_case(self):
        """Directly launch case creation form from this specific misconduct clause."""
        self.ensure_one()
        return {
            'name': _('New Disciplinary Case — %s') % (self.sub_article_code or self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_policy_version_id': self.article_id.policy_version_id.id if self.article_id else False,
                'default_article_id': self.article_id.id if self.article_id else False,
                'default_offense_id': self.id,
                'default_severity_level_id': self.severity_level_id.id if self.severity_level_id else False,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        # Modification Prevention - Only HR Admin can configure punishment rules
        if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
            raise UserError(_('Unauthorized modification: Only HR Administrators can create disciplinary offense configurations.'))
        return super().create(vals_list)

    def write(self, vals):
        # Modification Prevention
        sensitive_fields = {'severity_level', 'punishment_type', 'penalty_percentage', 'approval_authority', 'penalty_mode'}
        if set(vals.keys()).intersection(sensitive_fields):
            if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
                raise UserError(_('Unauthorized modification: Only HR Administrators can update disciplinary punishment rules and severity levels.'))
        return super().write(vals)
