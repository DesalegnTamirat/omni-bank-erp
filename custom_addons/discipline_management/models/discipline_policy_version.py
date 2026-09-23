# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplinePolicyVersion(models.Model):
    _name = 'discipline.policy.version'
    _description = 'Disciplinary Regulation & Policy Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, name desc'

    name = fields.Char(string='Regulation / Document Title', required=True, tracking=True)
    version_number = fields.Char(string='Version Code (e.g. CBA-2026.1)', required=True, tracking=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial Staff (የማኔጅመንት አባል ላልሆኑ)'),
        ('managerial', 'Managerial Staff (የማኔጅመንት አባላት)'),
        ('all', 'All Bank Staff (ለሁሉም ሠራተኞች)'),
    ], string='Applicable Staff Category', default='all', required=True, tracking=True)
    chapter_reference = fields.Char(string='Chapter / Section Reference', tracking=True)
    effective_date = fields.Date(string='Effective Date', required=True, default=fields.Date.context_today, tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', tracking=True)
    description = fields.Text(string='Regulation Summary & Scope')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)

    article_ids = fields.One2many('discipline.article', 'policy_version_id', string='Regulatory Articles')
    article_count = fields.Integer(string='Articles Count', compute='_compute_counts', store=True)
    offense_count = fields.Integer(string='Total Clauses Count', compute='_compute_counts', store=True)
    document_file = fields.Binary(string='Regulation Document File (PDF / Word)', attachment=True)
    document_filename = fields.Char(string='Document Filename')

    @api.depends('article_ids', 'article_ids.offense_ids')
    def _compute_counts(self):
        for rec in self:
            rec.article_count = len(rec.article_ids)
            rec.offense_count = sum(len(a.offense_ids) for a in rec.article_ids)

    def action_activate(self):
        for rec in self:
            rec.write({'state': 'active'})

    def action_archive_policy(self):
        for rec in self:
            rec.write({'state': 'archived'})


class DisciplineArticle(models.Model):
    _name = 'discipline.article'
    _description = 'Disciplinary Regulation Article'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'article_number, name'

    name = fields.Char(string='Article Title (Amharic / English)', required=True, tracking=True)
    article_number = fields.Char(string='Article Number', required=True, tracking=True, help="e.g. 33.4, 33.5, 10.4.1, 10.5.1")
    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', required=True, ondelete='cascade', tracking=True)
    staff_category = fields.Selection(related='policy_version_id.staff_category', string='Staff Category', store=True, readonly=True)
    severity_level_id = fields.Many2one('discipline.severity.level', string='Default Severity Level', tracking=True)
    severity_level = fields.Char(related='severity_level_id.code', string='Severity Code', store=True, readonly=True)
    description = fields.Text(string='Article Summary & Scope')
    statutory_text = fields.Text(string='Full Statutory / Legal Provision')
    active = fields.Boolean(default=True, tracking=True)

    offense_ids = fields.One2many('discipline.offense', 'article_id', string='Sub-Articles / Misconduct Clauses')
    offense_count = fields.Integer(string='Sub-Articles Count', compute='_compute_offense_count', store=True)

    @api.depends('offense_ids')
    def _compute_offense_count(self):
        for rec in self:
            rec.offense_count = len(rec.offense_ids)

    def action_create_case(self):
        """Directly launch case creation form from this regulation article."""
        self.ensure_one()
        return {
            'name': _('New Disciplinary Case — Article %s') % self.article_number,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_policy_version_id': self.policy_version_id.id,
                'default_article_id': self.id,
                'default_severity_level_id': self.severity_level_id.id if self.severity_level_id else False,
            }
        }
