# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from markupsafe import Markup


class DisciplineMisconductSelectorWizard(models.TransientModel):
    _name = 'discipline.misconduct.selector.wizard'
    _description = 'Interactive Misconduct Catalog & Legal Clause Explorer'

    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', readonly=True)
    staff_category = fields.Selection([
        ('all', 'All Bank Staff'),
        ('non_managerial', 'Non-Managerial Staff (Collective Agreement)'),
        ('managerial', 'Managerial Staff (Code of Conduct)'),
    ], string='Applicable Staff Category', default='all')

    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level')
    article_id = fields.Many2one('discipline.article', string='Governing Article')
    category_id = fields.Many2one('discipline.offense.category', string='Offense Category')
    search_query = fields.Char(string='Keyword Search', help='Search by Amharic or English keywords across title, article, and verbatim legal text.')

    offense_ids = fields.Many2many(
        'discipline.offense',
        string='Matching Misconduct Clauses',
        compute='_compute_offense_ids',
    )
    matching_count = fields.Integer(string='Matches Count', compute='_compute_offense_ids')

    selected_offense_id = fields.Many2one(
        'discipline.offense',
        string='Select Misconduct Clause',
        required=True,
    )

    preview_html = fields.Html(
        string='Verbatim Statutory Clause & Legal Sanction Preview',
        compute='_compute_preview_html',
        sanitize=False,
    )

    @api.depends('staff_category', 'severity_level_id', 'article_id', 'category_id', 'search_query')
    def _compute_offense_ids(self):
        for rec in self:
            domain = [('active', '=', True)]
            if rec.staff_category and rec.staff_category != 'all':
                domain.append(('staff_category', 'in', [rec.staff_category, 'all']))
            if rec.severity_level_id:
                domain.append(('severity_level_id', '=', rec.severity_level_id.id))
            if rec.article_id:
                domain.append(('article_id', '=', rec.article_id.id))
            if rec.category_id:
                domain.append(('category_id', '=', rec.category_id.id))
            if rec.search_query:
                words = [w for w in rec.search_query.strip().split() if len(w) > 0]
                for word in words:
                    domain.extend(['|', '|', '|', '|',
                        ('name', 'ilike', word),
                        ('sub_article_code', 'ilike', word),
                        ('article_number', 'ilike', word),
                        ('full_clause_text', 'ilike', word),
                        ('description', 'ilike', word),
                    ])
            records = self.env['discipline.offense'].search(domain, order='article_number, sub_article_code, name')
            rec.offense_ids = records
            rec.matching_count = len(records)

    @api.onchange('offense_ids')
    def _onchange_offense_ids(self):
        if self.offense_ids and self.selected_offense_id not in self.offense_ids:
            self.selected_offense_id = self.offense_ids[0]
        elif not self.offense_ids:
            self.selected_offense_id = False

    @api.depends('selected_offense_id', 'selected_offense_id.full_clause_text', 'selected_offense_id.name',
                 'selected_offense_id.severity_level_id', 'selected_offense_id.punishment_type')
    def _compute_preview_html(self):
        for rec in self:
            if not rec.selected_offense_id:
                rec.preview_html = Markup("""
                    <div class="alert alert-info text-center my-3 p-4" role="status" style="border-radius: 8px;">
                        <i class="fa fa-info-circle fa-2x mb-2 text-primary d-block" title="Information"></i>
                        <h5>No Misconduct Clause Selected</h5>
                        <p class="text-muted mb-0">Use the filters or search bar above to find a clause, then select one from the dropdown to preview its complete verbatim statutory text and prescribed sanction.</p>
                    </div>
                """)
                continue

            offense = rec.selected_offense_id
            level_code = offense.severity_level or (offense.severity_level_id and offense.severity_level_id.code) or ''
            level_name = (offense.severity_level_id and offense.severity_level_id.name) or _('Standard Severity')

            if level_code == 'level_1':
                badge_style = "background-color: #dc3545; color: #ffffff;"
                card_border = "border: 2px solid #dc3545;"
                header_bg = "background-color: #fdf2f2;"
            elif level_code in ('level_2', 'level_3'):
                badge_style = "background-color: #e07a00; color: #ffffff;"
                card_border = "border: 2px solid #fd7e14;"
                header_bg = "background-color: #fef8f0;"
            elif level_code == 'level_4':
                badge_style = "background-color: #0d8abc; color: #ffffff;"
                card_border = "border: 2px solid #0dcaf0;"
                header_bg = "background-color: #f0fbfe;"
            elif level_code == 'level_5':
                badge_style = "background-color: #6c757d; color: #ffffff;"
                card_border = "border: 2px solid #6c757d;"
                header_bg = "background-color: #f8f9fa;"
            else:
                badge_style = "background-color: #0d6efd; color: #ffffff;"
                card_border = "border: 1px solid #dee2e6;"
                header_bg = "background-color: #f8f9fa;"

            sanction_items = []
            if offense.punishment_type == 'dismissal':
                sanction_items.append("<strong>ከስራ ማሰናበት / Dismissal &amp; Termination</strong>")
            elif offense.punishment_type == 'final_warning_penalty':
                sanction_items.append("<strong>የመጨረሻ ደረጃ የጽሁፍ ማስጠንቀቂያ / Final Written Warning</strong>")
            elif offense.punishment_type == 'second_warning_penalty':
                sanction_items.append("<strong>ሁለተኛ ደረጃ የጽሁፍ ማስጠንቀቂያ / Second Written Warning</strong>")
            elif offense.punishment_type == 'first_warning_penalty':
                sanction_items.append("<strong>የመጀመሪያ ደረጃ የፅሁፍ ማስጠንቀቂያ / First Written Warning</strong>")
            elif offense.punishment_type == 'verbal_warning':
                sanction_items.append("<strong>የቃል ማስጠንቀቂያ በጽሁፍ / Recorded Verbal Warning</strong>")
            elif offense.punishment_type:
                punishment_label = dict(offense._fields['punishment_type'].selection).get(offense.punishment_type, offense.punishment_type)
                sanction_items.append(f"<strong>{Markup.escape(punishment_label)}</strong>")

            if offense.penalty_percentage > 0:
                sanction_items.append(f"<span style='color: #b02a37; font-weight: bold;'>{offense.penalty_percentage}% የደመወዝ ቅጣት (Salary Deduction)</span>")
            elif offense.fine_days > 0:
                sanction_items.append(f"<span style='color: #b02a37; font-weight: bold;'>{int(offense.fine_days)} የቀን ደመወዝ ቅጣት (Days Salary Fine)</span>")

            sanction_html = " + ".join(sanction_items) if sanction_items else "Standard Policy Disciplinary Measure"

            raw_text = offense.full_clause_text or offense.description or offense.name or ''
            text_lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
            formatted_paragraphs = "".join([f"<p style='margin-bottom: 8px; line-height: 1.65;'>{Markup.escape(l)}</p>" for l in text_lines])

            clause_code = offense.sub_article_code or offense.article_number or ''
            clause_title = Markup.escape(offense.name or '')
            citation = Markup.escape((offense.article_id and (offense.article_id.article_number or offense.article_id.name)) or '')
            regulation_name = Markup.escape((offense.article_id and offense.article_id.policy_version_id and offense.article_id.policy_version_id.name) or 'Bunna Bank Policy')

            card = f"""
            <div class="statutory-preview-card" style="border-radius: 8px; {card_border} background-color: #ffffff; box-shadow: 0 3px 8px rgba(0,0,0,0.08); overflow: hidden;">
                <div class="px-3 py-2 d-flex justify-content-between align-items-center flex-wrap" style="{header_bg} border-bottom: 1px solid #dee2e6;">
                    <div>
                        <span class="fw-bold fs-6 text-dark" style="letter-spacing: 0.3px;">
                            📜 {citation} {f'— ንዑስ አንቀጽ / Clause {clause_code}' if clause_code else ''}
                        </span>
                        <div class="small text-muted">{regulation_name}</div>
                    </div>
                    <div>
                        <span class="badge rounded-pill px-3 py-2" style="{badge_style} font-size: 13px; font-weight: 600;">
                            {level_name}
                        </span>
                    </div>
                </div>
                <div class="p-3">
                    <div class="mb-3">
                        <h5 class="fw-bold text-primary mb-2">
                            {clause_title}
                        </h5>
                        <div class="p-2 mb-2 rounded" style="background-color: #f1f5f9; border-left: 4px solid #0284c7; font-size: 14px;">
                            <strong>ሕጋዊ የቅጣት እርምጃ (Prescribed Statutory Measure):</strong> {sanction_html}
                        </div>
                    </div>
                    <div class="p-3 rounded" style="background-color: #fafbfc; border: 1px solid #e2e8f0; font-family: 'Segoe UI', Tahoma, 'Nyala', 'Abyssinica SIL', sans-serif; font-size: 14.5px; color: #1e293b;">
                        <div class="text-muted small fw-bold mb-2 text-uppercase" style="letter-spacing: 0.5px;">የጥፋቱ ሙሉ የሕግ ትርጓሜ (Full Statutory Legal Text):</div>
                        {formatted_paragraphs}
                    </div>
                </div>
            </div>
            """
            rec.preview_html = Markup(card)

    def action_apply_to_case(self):
        """Apply the selected misconduct clause to the disciplinary case."""
        self.ensure_one()
        if not self.selected_offense_id:
            raise UserError(_("Please select a misconduct clause from the catalog."))
        if not self.case_id:
            raise UserError(_("No active disciplinary case found to update."))

        vals = {
            'offense_id': self.selected_offense_id.id,
        }
        if self.selected_offense_id.article_id:
            vals['article_id'] = self.selected_offense_id.article_id.id
            if self.selected_offense_id.article_id.policy_version_id:
                vals['policy_version_id'] = self.selected_offense_id.article_id.policy_version_id.id
        if self.selected_offense_id.severity_level_id:
            vals['severity_level_id'] = self.selected_offense_id.severity_level_id.id

        self.case_id.write(vals)
        # Re-trigger case rule resolution and cards
        self.case_id._compute_punishment_details()
        self.case_id._compute_legal_citation()
        self.case_id._compute_statutory_clause_card_html()
        return {'type': 'ir.actions.act_window_close'}
