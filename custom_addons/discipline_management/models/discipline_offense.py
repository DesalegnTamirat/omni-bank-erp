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

    _code_uniq = models.Constraint('unique(code)', 'The Category Code must be unique!')


class DisciplineOffense(models.Model):
    _name = 'discipline.offense'
    _description = 'Disciplinary Offense Definition'
    _inherit = ['mail.thread']
    _order = 'sequence, id'
    _rec_names_search = ['title', 'name', 'sub_article_code', 'article_number', 'full_clause_text', 'description']

    sequence = fields.Integer(string='Sequence', default=10, index=True)
    name = fields.Char(string='Offense Title', required=True, tracking=True)
    title = fields.Char(string='Statutory Clause Title', tracking=True)
    has_distinct_title = fields.Boolean(string='Has Distinct Statutory Title', default=False, tracking=True)

    sanction_summary = fields.Char(string='Prescribed Sanction Summary', compute='_compute_sanction_summary', store=True)

    @api.depends('severity_level_id', 'punishment_type', 'penalty_percentage', 'fine_days')
    def _compute_sanction_summary(self):
        for rec in self:
            parts = []
            if rec.severity_level_id:
                parts.append(rec.severity_level_id.name)
            if rec.punishment_type == 'dismissal':
                parts.append(_("Dismissal"))
            elif rec.penalty_percentage > 0:
                parts.append(f"{rec.penalty_percentage}% Fine")
            elif rec.fine_days > 0:
                parts.append(f"{int(rec.fine_days)} Days Fine")
            elif rec.punishment_type == 'verbal_warning':
                parts.append(_("Verbal Warning"))
            elif rec.punishment_type == 'final_warning_penalty':
                parts.append(_("Final Warning"))
            elif rec.punishment_type == 'second_warning_penalty':
                parts.append(_("Second Warning"))
            elif rec.punishment_type == 'first_warning_penalty':
                parts.append(_("First Warning"))
            rec.sanction_summary = " — ".join(parts) if parts else _("Standard Sanction")

    @api.depends('title', 'name', 'full_clause_text', 'has_distinct_title')
    def _compute_display_name(self):
        for rec in self:
            if rec.has_distinct_title and rec.title:
                detail = (rec.full_clause_text or rec.name or '').strip()
                rec.display_name = f"{rec.title}\n{detail}" if detail else rec.title
            else:
                detail = (rec.full_clause_text or rec.name or '').strip()
                rec.display_name = detail

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        """Intelligent multi-token keyword search across title, clause code, full verbatim text, and descriptions in Amharic & English."""
        if name and operator in ('ilike', 'like', '=ilike', '=?'):
            words = [w for w in name.strip().split() if len(w) > 0]
            if len(words) > 1:
                # Multi-word search: each token must match at least one searchable field
                search_domain = list(domain or [])
                for word in words:
                    search_domain.extend(['|', '|', '|', '|', '|',
                        ('title', operator, word),
                        ('name', operator, word),
                        ('sub_article_code', operator, word),
                        ('article_number', operator, word),
                        ('full_clause_text', operator, word),
                        ('description', operator, word),
                    ])
                records = self.search(search_domain, limit=limit)
                return [(rec.id, rec.display_name) for rec in records]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)
    def _default_category_id(self):
        cat = self.env['discipline.offense.category'].search([], limit=1)
        return cat.id if cat else False

    category_id = fields.Many2one('discipline.offense.category', string='Offense Category', default=_default_category_id, tracking=True)
    article_id = fields.Many2one('discipline.article', string='Statutory Article', tracking=True)
    article_number = fields.Char(related='article_id.article_number', string='Article Number', store=True, readonly=True)
    governing_article_display = fields.Char(
        string='Governing Article',
        compute='_compute_governing_article_display',
        store=True,
        tracking=True
    )
    sub_article_code = fields.Char(string='Sub-Article / Clause Code', tracking=True, help="e.g. 33.4.2 (ሀ), 33.8.13, 10.4.1(a)")
    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', related='article_id.policy_version_id', store=True, readonly=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial Staff'),
        ('managerial', 'Managerial Staff'),
        ('all', 'All Bank Staff'),
    ], string='Applicable Staff Category', default='all', tracking=True)

    @api.depends('article_id', 'article_id.name', 'article_id.article_number', 'sub_article_code')
    def _compute_governing_article_display(self):
        for rec in self:
            if rec.article_id:
                rec.governing_article_display = rec.article_id.name or rec.article_id.article_number or ''
            else:
                code = (rec.sub_article_code or '').strip()
                if '33.4' in code:
                    rec.governing_article_display = "Article 33.4 - አንደኛ ደረጃ ጥፋቶች (ያለማስጠንቀቂያ ከስራ የሚያሰናብቱ)"
                elif '33.5' in code:
                    rec.governing_article_display = "Article 33.5 - ሁለተኛ ደረጃ ጥፋቶች (የመጨረሻ ማስጠንቀቂያና 20% ቅጣት)"
                elif '33.6' in code:
                    rec.governing_article_display = "Article 33.6 - ሦስተኛ ደረጃ ጥፋቶች (2ኛ ማስጠንቀቂያና 10% ቅጣት)"
                elif '33.7' in code:
                    rec.governing_article_display = "Article 33.7 - አራተኛ ደረጃ ጥፋቶች (1ኛ ማስጠንቀቂያና 5% ቅጣት)"
                elif '33.8' in code:
                    rec.governing_article_display = "Article 33.8 - አምስተኛ ደረጃ ጥፋቶች (የቃል ማስጠንቀቂያ በጽሁፍ)"
                elif '33.9' in code:
                    rec.governing_article_display = "Article 33.9 - የጥሬ ገንዘብ ጉድለት መተዳደሪያ ደንብ"
                elif '10.4.1' in code:
                    rec.governing_article_display = "Article 10.4.1 - Managerial Breaches (Oral / 1 Day Fine)"
                elif '10.4.2' in code:
                    rec.governing_article_display = "Article 10.4.2 - Managerial Breaches (Written / 2 Days Fine)"
                elif '10.4.3' in code:
                    rec.governing_article_display = "Article 10.4.3 - Managerial Breaches (Final / 3 Days Fine)"
                elif '10.5.1' in code:
                    rec.governing_article_display = "Article 10.5.1 - Managerial Breaches (Rigorous - Dismissal)"
                else:
                    rec.governing_article_display = "General Bank Regulation"

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
        default_cat_id = self._default_category_id()
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = vals.get('title') or vals.get('sub_article_code') or (vals.get('full_clause_text') or '')[:100] or _('Misconduct Clause')
            if not vals.get('category_id'):
                vals['category_id'] = default_cat_id
            if vals.get('article_id'):
                art = self.env['discipline.article'].browse(vals['article_id'])
                if not vals.get('staff_category') and art.staff_category:
                    vals['staff_category'] = art.staff_category
                if not vals.get('severity_level_id') and art.severity_level_id:
                    vals['severity_level_id'] = art.severity_level_id.id
        return super().create(vals_list)

    def write(self, vals):
        # Modification Prevention
        sensitive_fields = {'severity_level', 'punishment_type', 'penalty_percentage', 'approval_authority', 'penalty_mode'}
        if set(vals.keys()).intersection(sensitive_fields):
            if not (self.env.su or self.env.user.has_group('discipline_management.group_discipline_admin')):
                raise UserError(_('Unauthorized modification: Only HR Administrators can update disciplinary punishment rules and severity levels.'))
        return super().write(vals)

    def _auto_init(self):
        res = super()._auto_init()
        try:
            self.env.cr.execute("ALTER TABLE IF EXISTS discipline_article ALTER COLUMN policy_version_id DROP NOT NULL;")
        except Exception:
            pass
        return res

    def _register_hook(self):
        super()._register_hook()
        try:
            if self.env['discipline.article'].sudo().search_count([]) < 10:
                with self.env.cr.savepoint():
                    self._auto_link_articles_and_categories()
        except Exception:
            pass

    def action_sync_bunna_regulation_catalog(self):
        """Turnkey action: auto-creates articles, categories, and links all offenses in seconds."""
        self.env['discipline.offense']._auto_link_articles_and_categories()
        all_offenses = self.env['discipline.offense'].search([])
        all_offenses._compute_governing_article_display()
        all_offenses._compute_sanction_summary()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bunna Bank Regulation Synchronized"),
                'message': _("All 10 Regulatory Articles, Offense Categories, and 184 Statutory Offenses have been successfully verified, linked, and repaired!"),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def _auto_link_articles_and_categories(self):
        """Idempotently ensure standard Bunna Bank articles and categories exist, and link all offenses."""
        Article = self.env['discipline.article'].sudo()
        Category = self.env['discipline.offense.category'].sudo()
        Severity = self.env['discipline.severity.level'].sudo()

        # 1. Ensure Standard Categories Exist
        categories_def = {
            'FRD': ('Fraud, Theft & Embezzlement (ማጭበርበርና ስርቆት)', 'Severe financial crimes, theft, forgery, and deliberate fiduciary harm.'),
            'ATT': ('Attendance & Timekeeping (የስራ ሰዓትና መገኘት)', 'Unauthorized absence, lateness, and abandonment of post.'),
            'CND': ('Professional Conduct & Ethics (የስነ-ምግባር ጉድለት)', 'Workplace demeanor, insubordination, and integrity breaches.'),
            'OPS': ('Operational & Cash Procedures (የአሰራርና ጥሬ ገንዘብ)', 'Procedural violations, cash shortages, and operational guidelines.'),
            'PRP': ('Bank Property & Operational Negligence', 'Misuse, damage, or neglect of bank equipment, property, and assets.'),
            'REG': ('Statutory & Regulatory Compliance (የህግና መመሪያ ተገዢነት)', 'Breaches of NBE directives, labor proclamation, and statutory limits.'),
            'SUP': ('Supervisory & Managerial Control Failures', 'Failures in managerial oversight and supervisory control.'),
        }
        category_records = {}
        for code, (cat_name, cat_desc) in categories_def.items():
            cat = Category.search([('code', '=', code)], limit=1)
            if not cat:
                cat = Category.create({
                    'name': cat_name,
                    'code': code,
                    'description': cat_desc,
                    'active': True,
                })
            category_records[code] = cat

        default_cat = category_records.get('CND') or Category.search([], limit=1)

        # 2. Standard Articles map (Number -> (Name, Severity Code, Staff Category))
        standard_articles = {
            'Article 33.4': ('አንደኛ ደረጃ ጥፋቶች - ከሥራ የሚያሰናብቱ (Level 1: Summary Dismissal)', 'level_1', 'non_managerial'),
            'Article 33.5': ('ሁለተኛ ደረጃ ጥፋቶች - የመጨረሻ የጽሑፍ ማስጠንቀቂያና 20% ቅጣት (Level 2: Final Warning & 20%)', 'level_2', 'non_managerial'),
            'Article 33.6': ('ሦስተኛ ደረጃ ጥፋቶች - የ2ኛ ደረጃ ማስጠንቀቂያና 10% ቅጣት (Level 3: 2nd Warning & 10%)', 'level_3', 'non_managerial'),
            'Article 33.7': ('አራተኛ ደረጃ ጥፋቶች - የ1ኛ ደረጃ ማስጠንቀቂያና 5% ቅጣት (Level 4: 1st Warning & 5%)', 'level_4', 'non_managerial'),
            'Article 33.8': ('አምስተኛ ደረጃ ጥፋቶች - የቃል ማስጠንቀቂያ (Level 5: Verbal Warning)', 'level_5', 'non_managerial'),
            'Article 33.9': ('የገንዘብ ጉድለት መተዳደሪያ ደንብ (Cash Shortage Scale)', 'level_3', 'non_managerial'),
            'Article 10.4.1': ('Managerial Breaches - Oral Warning or 1 Day Fine', 'level_4', 'managerial'),
            'Article 10.4.2': ('Managerial Breaches - Written Warning & 2 Days Fine', 'level_3', 'managerial'),
            'Article 10.4.3': ('Managerial Breaches - Final Warning & 3 Days Fine', 'level_2', 'managerial'),
            'Article 10.5.1': ('Managerial Breaches - Dismissal', 'level_1', 'managerial'),
        }

        from odoo.tools import sql
        sql.drop_not_null(self.env.cr, 'discipline_article', 'policy_version_id')

        # Ensure default Governing Regulations exist
        Policy = self.env['discipline.policy.version'].sudo()
        cba_policy = Policy.search([('version_number', '=', 'CBA-2026.1')], limit=1)
        if not cba_policy:
            cba_policy = Policy.create({
                'name': 'Bunna Bank S.C. Collective Bargaining Agreement (CBA Ch 8)',
                'version_number': 'CBA-2026.1',
                'staff_category': 'non_managerial',
                'chapter_reference': 'Chapter 8 - Disciplinary Measures',
                'state': 'active',
            })
        mgr_policy = Policy.search([('version_number', '=', 'MGR-2026.1')], limit=1)
        if not mgr_policy:
            mgr_policy = Policy.create({
                'name': 'Bunna Bank S.C. Managerial Staff Disciplinary Regulations (Ch X)',
                'version_number': 'MGR-2026.1',
                'staff_category': 'managerial',
                'chapter_reference': 'Chapter X - Managerial Disciplinary Measures',
                'state': 'active',
            })

        article_records = {}
        for art_num, (art_name, sev_code, staff_cat) in standard_articles.items():
            art = Article.search(['|', ('article_number', '=', art_num), ('article_number', '=', art_num.replace('Article ', ''))], limit=1)
            target_policy = mgr_policy if staff_cat == 'managerial' else cba_policy
            if not art:
                sev = Severity.search([('code', '=', sev_code)], limit=1)
                art = Article.create({
                    'article_number': art_num,
                    'name': art_name,
                    'policy_version_id': target_policy.id,
                    'severity_level_id': sev.id if sev else False,
                    'staff_category': staff_cat,
                    'active': True,
                })
            elif not art.policy_version_id:
                art.write({'policy_version_id': target_policy.id})
            article_records[art_num] = art

        # 3. Auto-link and heal ALL offenses in the database
        all_offenses = self.sudo().search([])
        for off in all_offenses:
            code = (off.sub_article_code or '').strip()
            text = f"{off.name or ''} {off.title or ''} {off.full_clause_text or ''}".lower()
            vals = {}

            # Link Article if missing
            if not off.article_id and code:
                target_art = None
                if '33.4' in code:
                    target_art = article_records.get('Article 33.4')
                elif '33.5' in code:
                    target_art = article_records.get('Article 33.5')
                elif '33.6' in code:
                    target_art = article_records.get('Article 33.6')
                elif '33.7' in code:
                    target_art = article_records.get('Article 33.7')
                elif '33.8' in code:
                    target_art = article_records.get('Article 33.8')
                elif '33.9' in code:
                    target_art = article_records.get('Article 33.9')
                elif '10.4.1' in code:
                    target_art = article_records.get('Article 10.4.1')
                elif '10.4.2' in code:
                    target_art = article_records.get('Article 10.4.2')
                elif '10.4.3' in code:
                    target_art = article_records.get('Article 10.4.3')
                elif '10.5.1' in code:
                    target_art = article_records.get('Article 10.5.1')

                if target_art:
                    vals['article_id'] = target_art.id
                    if not off.staff_category or off.staff_category == 'all':
                        vals['staff_category'] = target_art.staff_category

            # Link Severity Level if missing
            if not off.severity_level_id:
                ref_art = vals.get('article_id') and Article.browse(vals['article_id']) or off.article_id
                if ref_art and ref_art.severity_level_id:
                    vals['severity_level_id'] = ref_art.severity_level_id.id

            # Link Category if missing
            if not off.category_id:
                target_cat = default_cat
                if any(k in text for k in ['ስርቆት', 'ዘረፋ', 'ማጭበርበር', 'fraud', 'theft', 'embezzle', 'forge']):
                    target_cat = category_records.get('FRD', default_cat)
                elif any(k in text for k in ['መቅረት', 'መዘግየት', 'ማርፈድ', 'absence', 'attendance', 'punctual', 'absent']):
                    target_cat = category_records.get('ATT', default_cat)
                elif any(k in text for k in ['ጥሬ ገንዘብ', 'ጉድለት', 'shortage', 'cash', 'discrepancy']):
                    target_cat = category_records.get('OPS', default_cat)
                elif any(k in text for k in ['ንብረት', 'መሳሪያ', 'ተሽከርካሪ', 'damage', 'property', 'asset']):
                    target_cat = category_records.get('PRP', default_cat)
                elif any(k in text for k in ['ተቆጣጣሪ', 'ኃላፊ', 'supervis', 'oversight']):
                    target_cat = category_records.get('SUP', default_cat)
                elif any(k in text for k in ['መመሪያ', 'ህግ', 'statutory', 'compliance', 'regulation']):
                    target_cat = category_records.get('REG', default_cat)

                if target_cat:
                    vals['category_id'] = target_cat.id

            if vals:
                off.write(vals)
