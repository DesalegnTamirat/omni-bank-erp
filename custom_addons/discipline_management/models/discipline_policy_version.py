# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplinePolicyVersion(models.Model):
    _name = 'discipline.policy.version'
    _description = 'Disciplinary Regulation & Policy Document'
    _inherit = ['mail.thread']
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

    def action_view_articles(self):
        self.ensure_one()
        return {
            'name': _('Regulatory Articles — %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.article',
            'view_mode': 'list,form',
            'domain': [('policy_version_id', '=', self.id)],
            'context': {
                'default_policy_version_id': self.id,
                'default_staff_category': self.staff_category,
            },
        }

    def action_view_offenses(self):
        self.ensure_one()
        return {
            'name': _('Misconduct Clauses — %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.offense',
            'view_mode': 'list,form',
            'domain': [('policy_version_id', '=', self.id)],
            'context': {
                'default_policy_version_id': self.id,
                'default_staff_category': self.staff_category,
            },
        }


class DisciplineArticle(models.Model):
    _name = 'discipline.article'
    _description = 'Disciplinary Regulation Article'
    _inherit = ['mail.thread']
    _order = 'article_number, name'
    _rec_names_search = ['name', 'article_number']

    name = fields.Char(string='Article Title (Amharic / English)', required=True, tracking=True)
    article_number = fields.Char(string='Article Number', required=True, tracking=True, help="e.g. 33.4, 33.5, 10.4.1, 10.5.1")
    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', required=False, ondelete='set null', tracking=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial Staff'),
        ('managerial', 'Managerial Staff'),
        ('all', 'All Bank Staff'),
    ], string='Staff Category', default='all', tracking=True)
    severity_level_id = fields.Many2one('discipline.severity.level', string='Default Severity Level', tracking=True)
    severity_level = fields.Char(related='severity_level_id.code', string='Severity Code', store=True, readonly=True)
    description = fields.Text(string='Article Summary & Scope')
    statutory_text = fields.Text(string='Full Statutory / Legal Provision')
    active = fields.Boolean(default=True, tracking=True)

    offense_ids = fields.One2many('discipline.offense', 'article_id', string='Sub-Articles / Misconduct Clauses')
    offense_count = fields.Integer(string='Sub-Articles Count', compute='_compute_offense_count', store=True)

    def _auto_init(self):
        res = super()._auto_init()
        try:
            self.env.cr.execute("ALTER TABLE IF EXISTS discipline_article ALTER COLUMN policy_version_id DROP NOT NULL;")
        except Exception:
            pass
        return res

    @api.depends('offense_ids')
    def _compute_offense_count(self):
        for rec in self:
            rec.offense_count = len(rec.offense_ids)

    @api.depends('article_number', 'name')
    def _compute_display_name(self):
        for rec in self:
            art_num = (rec.article_number or '').strip()
            rec.display_name = art_num or rec.name or ''

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        if name:
            clean_name = name.strip()
            variants = {
                clean_name,
                clean_name.replace('Article', '').strip(),
                f"Article {clean_name}".strip(),
            }
            if ' - ' in clean_name:
                for part in clean_name.split(' - '):
                    p = part.strip()
                    if p:
                        variants.add(p)
                        variants.add(p.replace('Article', '').strip())
                        variants.add(f"Article {p}".strip())

            domain_clauses = []
            for v in variants:
                if v:
                    domain_clauses.append(('article_number', operator, v))
                    domain_clauses.append(('name', operator, v))

            if domain_clauses:
                search_domain = list(domain or [])
                for _ in range(len(domain_clauses) - 1):
                    search_domain.append('|')
                search_domain.extend(domain_clauses)
                records = self.search(search_domain, limit=limit)
                if records:
                    return [(rec.id, rec.display_name) for rec in records]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)

    @api.model
    def name_create(self, name):
        name_str = (name or '').strip()
        article_number = ''
        article_title = name_str

        # Parse "Article 33.4 - Title..." or "Article 10.4.1 - Title..."
        if ' - ' in name_str:
            parts = name_str.split(' - ', 1)
            article_number = parts[0].strip()
            article_title = parts[1].strip()
        elif ': ' in name_str:
            parts = name_str.split(': ', 1)
            article_number = parts[0].strip()
            article_title = parts[1].strip()
        else:
            article_number = name_str

        if article_number and not article_number.startswith('Article ') and any(c.isdigit() for c in article_number):
            article_number = f"Article {article_number}"

        is_managerial = '10.' in (article_number or name_str)
        policy = self.env['discipline.policy.version'].search([
            ('staff_category', 'in', [('managerial' if is_managerial else 'non_managerial'), 'all'])
        ], limit=1)
        if not policy:
            policy = self.env['discipline.policy.version'].create({
                'name': 'Standard Disciplinary Policy',
                'version_number': 'POL-01',
                'staff_category': 'all',
                'state': 'active',
            })

        sev_code = False
        if '33.4' in article_number or '10.5.1' in article_number:
            sev_code = 'level_1'
        elif '33.5' in article_number or '10.4.3' in article_number:
            sev_code = 'level_2'
        elif '33.6' in article_number or '10.4.2' in article_number:
            sev_code = 'level_3'
        elif '33.7' in article_number or '10.4.1' in article_number:
            sev_code = 'level_4'
        elif '33.8' in article_number or '33.9' in article_number:
            sev_code = 'level_5'

        sev_id = False
        if sev_code:
            sev = self.env['discipline.severity.level'].search([('code', '=', sev_code)], limit=1)
            sev_id = sev.id if sev else False

        article = self.create({
            'article_number': article_number or name_str,
            'name': article_title or name_str,
            'policy_version_id': policy.id,
            'severity_level_id': sev_id,
        })
        return (article.id, article.display_name)

    def action_view_offenses(self):
        self.ensure_one()
        return {
            'name': _('Sub-Articles / Clauses — %s', self.article_number),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.offense',
            'view_mode': 'list,form',
            'domain': [('article_id', '=', self.id)],
            'context': {
                'default_article_id': self.id,
                'default_policy_version_id': self.policy_version_id.id,
                'default_staff_category': self.staff_category,
                'default_severity_level_id': self.severity_level_id.id if self.severity_level_id else False,
            },
        }

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
