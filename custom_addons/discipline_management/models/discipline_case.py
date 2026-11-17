# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from datetime import timedelta, date
from markupsafe import Markup
from odoo.tools import html_escape


class DisciplineCase(models.Model):
    _name = 'discipline.case'
    _description = 'Disciplinary Case Record'
    _inherit = ['mail.thread']
    _order = 'incident_date desc, id desc'

    name = fields.Char(string='Case Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    employee_name_amharic = fields.Char(
        string='Subject Employee Name (Amharic / የአጥፊው ሠራተኛ ስም በአማርኛ)',
        tracking=True,
        help="Official employee name in Amharic script used for legal notice letters and formal bank memos."
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        compute='_compute_operating_unit_id',
        store=True,
        readonly=True,
    )
    department_id = fields.Many2one('hr.department', string='Department', compute='_compute_employee_profile_fields', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', compute='_compute_employee_profile_fields', store=True, readonly=True)
    work_location_id = fields.Many2one('hr.work.location', string='Work Location', compute='_compute_employee_profile_fields', store=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    @api.depends('employee_id')
    def _compute_operating_unit_id(self):
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            if emp:
                ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id and getattr(emp.department_id, 'operating_unit_id', False))
                rec.operating_unit_id = ou.id if ou else False
            else:
                rec.operating_unit_id = False

    @api.depends('employee_id')
    def _compute_employee_profile_fields(self):
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            rec.department_id = emp.department_id.id if (emp and emp.department_id) else False
            rec.job_id = emp.job_id.id if (emp and emp.job_id) else False
            rec.work_location_id = emp.work_location_id.id if (emp and emp.work_location_id) else False
            if emp and not rec.employee_name_amharic:
                rec.employee_name_amharic = getattr(emp, 'name_amharic', False) or emp.name

    @api.onchange('employee_id')
    def _onchange_employee_id_amharic_name(self):
        for rec in self:
            if rec.employee_id:
                emp = rec.employee_id.sudo()
                if hasattr(emp, 'name_amharic') and emp.name_amharic:
                    rec.employee_name_amharic = emp.name_amharic
                elif not rec.employee_name_amharic:
                    rec.employee_name_amharic = emp.name

    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', tracking=True)
    article_id = fields.Many2one('discipline.article', string='Regulatory Article', tracking=True)
    article_display = fields.Char(string='Article Citation', compute='_compute_article_display', store=True)
    offense_id = fields.Many2one('discipline.offense', string='Offense Type / Clause', required=True, tracking=True)
    offense_detail_html = fields.Html(string='Misconduct Full Detail', compute='_compute_offense_detail_html', sanitize=False)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='offense_id.category_id', store=True, readonly=True)
    sub_article_code = fields.Char(related='offense_id.sub_article_code', string='Clause Code', store=True, readonly=True)
    legal_article_display = fields.Char(string='Statutory Legal Citation', compute='_compute_legal_citation', store=True)
    legal_clause_text = fields.Text(string='Verbatim Statutory Clause Text', compute='_compute_legal_citation', store=True)

    occurrence_count = fields.Integer(string='Breach Occurrence Tier', default=1, compute='_compute_punishment_details', store=True, readonly=False, tracking=True)
    is_escalated_by_active_warning = fields.Boolean(string='Escalated by Prior Active Warning (Art 33.1.4)', compute='_compute_punishment_details', store=True, readonly=False, tracking=True)
    auto_applied_rule_summary = fields.Text(string='Rule Application Summary', compute='_compute_punishment_details', store=True)

    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=False, tracking=True)
    severity_level = fields.Char(string='Severity Code', related='severity_level_id.code', store=True, readonly=True)
    PUNISHMENT_SELECTION = [
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
        ('exonerate', 'Exonerated / Overturned'),
    ]

    punishment_type = fields.Selection(
        PUNISHMENT_SELECTION, string='Applicable Punishment',
        compute='_compute_punishment_details', store=True, readonly=False, tracking=True
    )
    original_punishment_type = fields.Selection(
        PUNISHMENT_SELECTION, string='Original Standard Punishment',
        compute='_compute_punishment_details', store=True, readonly=True
    )
    original_penalty_percentage = fields.Float(string='Original Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True)
    original_fine_days = fields.Float(string='Original Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True)

    decided_punishment_type = fields.Selection(
        PUNISHMENT_SELECTION, string='Final Committee Decided Punishment', tracking=True
    )

    decided_penalty_percentage = fields.Float(string='Final Decided Penalty (%)', tracking=True)
    decided_fine_days = fields.Float(string='Final Decided Salary Fine (Days)', tracking=True)
    is_punishment_modified_by_committee = fields.Boolean(string='Punishment Modified by Committee', compute='_compute_is_punishment_modified', store=True)

    supporting_attachment = fields.Binary(
        string='Supporting Evidence / Document',
        attachment=True,
        help="Optional supporting document or evidence file for this disciplinary case."
    )
    attachment_filename = fields.Char(
        string='Attachment Filename',
        help="Filename of the uploaded supporting evidence."
    )

    @api.depends('article_id', 'offense_id', 'offense_id.sub_article_code', 'offense_id.full_clause_text', 'article_id.article_number', 'article_id.name')
    def _compute_legal_citation(self):
        for rec in self:
            citations = []
            art_rec = rec.article_id or (rec.offense_id and rec.offense_id.article_id)
            art_val = (art_rec and (art_rec.article_number or art_rec.name)) or ''
            if art_val:
                art_clean = art_val.strip()
                if art_clean.lower().startswith('article'):
                    citations.append(art_clean)
                else:
                    citations.append(_('Article %s') % art_clean)
            if rec.offense_id and rec.offense_id.sub_article_code:
                sub_clean = str(rec.offense_id.sub_article_code).strip()
                if sub_clean.lower().startswith('sub') or sub_clean.lower().startswith('art') or sub_clean.lower().startswith('clause'):
                    citations.append(sub_clean)
                else:
                    citations.append(_('Sub-Article %s') % sub_clean)
            rec.legal_article_display = ' - '.join(citations) if citations else False
            rec.legal_clause_text = (rec.offense_id and rec.offense_id.full_clause_text) or (rec.article_id and rec.article_id.description) or False

    @api.depends('article_id', 'article_id.article_number', 'offense_id', 'offense_id.sub_article_code')
    def _compute_article_display(self):
        for rec in self:
            art_code = ''
            if rec.article_id and rec.article_id.article_number:
                art_code = rec.article_id.article_number.replace('Article', '').strip()
            elif rec.offense_id and rec.offense_id.article_id and rec.offense_id.article_id.article_number:
                art_code = rec.offense_id.article_id.article_number.replace('Article', '').strip()
            
            sub_code = rec.offense_id.sub_article_code.strip() if (rec.offense_id and rec.offense_id.sub_article_code) else ''
            
            if art_code and sub_code:
                rec.article_display = f"{art_code} - {sub_code}"
            elif sub_code:
                rec.article_display = sub_code
            elif art_code:
                rec.article_display = art_code
            else:
                rec.article_display = False

    @api.depends('offense_id', 'offense_id.full_clause_text', 'offense_id.name', 'offense_id.title')
    def _compute_offense_detail_html(self):
        for rec in self:
            if rec.offense_id and (rec.offense_id.full_clause_text or rec.offense_id.name):
                text = rec.offense_id.full_clause_text or rec.offense_id.name
                escaped_text = html_escape(text)
                title_html = f'<div style="font-weight: 700; color: #111827; margin-bottom: 4px;">{html_escape(rec.offense_id.title)}</div>' if rec.offense_id.title else ''
                rec.offense_detail_html = Markup(
                    f'<details open="open" style="margin-top: 4px; font-size: 13px;">'
                    f'<summary style="cursor: pointer; color: #017e84; font-weight: 600; font-size: 12px; outline: none; margin-bottom: 4px;">'
                    f'▾ Show full definition / ዝርዝር ድንጋጌ (Click to collapse/expand)'
                    f'</summary>'
                    f'<div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-left: 3px solid #017e84; border-radius: 4px; padding: 8px 12px; white-space: pre-wrap; line-height: 1.5; color: #212529;">'
                    f'{title_html}'
                    f'{escaped_text}'
                    f'</div>'
                    f'</details>'
                )
            else:
                rec.offense_detail_html = False

    @api.depends('original_punishment_type', 'punishment_type', 'original_penalty_percentage', 'penalty_percentage', 'original_fine_days', 'fine_days')
    def _compute_is_punishment_modified(self):
        for rec in self:
            rec.is_punishment_modified_by_committee = (
                (rec.punishment_type and rec.original_punishment_type and rec.punishment_type != rec.original_punishment_type) or
                (rec.penalty_percentage != rec.original_penalty_percentage) or
                (rec.fine_days != rec.original_fine_days)
            )

    cash_shortage_amount = fields.Float(string='Cash Shortage Amount (ETB)', tracking=True)
    is_cash_shortage = fields.Boolean(string='Is Cash Shortage Misconduct', compute='_compute_is_cash_shortage', store=True)
    is_statutory_mitigation_applied = fields.Boolean(string='Apply Statutory Mitigation (-1 Grade)', tracking=True)
    mitigation_justification = fields.Text(string='Mitigation Legal Justification', tracking=True)
    payroll_month = fields.Selection([
        ('1', 'January'),
        ('2', 'February'),
        ('3', 'March'),
        ('4', 'April'),
        ('5', 'May'),
        ('6', 'June'),
        ('7', 'July'),
        ('8', 'August'),
        ('9', 'September'),
        ('10', 'October'),
        ('11', 'November'),
        ('12', 'December'),
    ], string='Payroll Deduction Month', default=lambda self: str(fields.Date.context_today(self).month), tracking=True, help="Target payroll cycle / month in which salary penalty deductions shall be executed.")
    is_payroll_deductible = fields.Boolean(string='Has Payroll Deduction', compute='_compute_is_payroll_deductible', store=True, help="Indicates whether this disciplinary sanction incurs a salary fine or percentage deduction.")
    statutory_deadline_date = fields.Date(string='Legal Decision Deadline', compute='_compute_statutory_deadline', store=True)
    is_deadline_exceeded = fields.Boolean(string='Legal Deadline Exceeded', compute='_compute_statutory_deadline', store=True)

    # Notice Letter Customization & Branding (Amharic & Official Sign-off)
    @api.model
    def _default_notice_language(self):
        return self.env['ir.config_parameter'].sudo().get_param('discipline.default_notice_language', 'amharic')

    @api.model
    def _default_signatory_signature(self):
        user = self.env.user
        sig = getattr(user, 'discipline_digital_signature', False) or getattr(user, 'digital_signature', False)
        if not sig:
            # Fall back to the user's latest signed case
            prev_case = self.search([
                ('signatory_signature', '!=', False),
                '|', ('initiator_id', '=', user.id), ('create_uid', '=', user.id)
            ], order='id desc', limit=1)
            if prev_case and prev_case.signatory_signature:
                sig = prev_case.signatory_signature
                try:
                    user.sudo().write({'discipline_digital_signature': sig})
                except Exception:
                    pass
        return sig or False

    def _get_notice_language_selection(self):
        return [
            ('amharic', 'Amharic (አማርኛ)'),
            ('english', 'English'),
        ]

    notice_language = fields.Selection(
        selection='_get_notice_language_selection',
        string='Notice Letter Language',
        default=_default_notice_language,
        required=True,
        tracking=True,
        help='Language format for the formal disciplinary notice letter. Amharic is the official standard for Bunna Bank.'
    )
    signatory_signature = fields.Binary(string='Signatory Digital Signature', copy=False, default=_default_signatory_signature, help='Authorized signatory signature image rendered on the notice letter.')
    signatory_id = fields.Many2one(
        'res.users',
        string='Authorized Signatory',
        readonly=True,
        tracking=True,
        help='The authorized user who digitally signed and enforced this disciplinary decision notice.'
    )
    bank_stamp = fields.Binary(string='Bank Official Stamp', related='company_id.discipline_bank_stamp', readonly=True, help='Official circular Bunna Bank seal stamp rendered on the notice letter.')

    # Executive SLA & Expiration Tracking (Secretary & Executive Monitoring)
    stage_entry_date = fields.Datetime(string='Stage Entry Date', default=fields.Datetime.now, copy=False)
    stage_target_days = fields.Integer(string='Stage SLA Target (Days)', compute='_compute_stage_sla_tracking', store=True)
    days_in_stage = fields.Integer(string='Days in Current Stage', compute='_compute_stage_sla_live')
    stage_deadline = fields.Date(string='Stage Target Deadline', compute='_compute_stage_sla_tracking', store=True)
    prescription_deadline = fields.Date(string='Statutory Prescription Date', compute='_compute_stage_sla_tracking', store=True)
    def _get_sla_status_selection(self):
        return [
            ('on_track', 'On Track'),
            ('warning', 'Approaching Deadline'),
            ('overdue', 'Overdue / Expiring'),
        ]

    sla_status = fields.Selection(
        selection='_get_sla_status_selection',
        string='SLA / Prescription Status',
        compute='_compute_stage_sla_tracking',
        store=True,
        tracking=True
    )
    sla_countdown_display = fields.Char(
        string='SLA Countdown',
        compute='_compute_stage_sla_live',
        help='Human-readable SLA countdown or expiration urgency.'
    )

    current_stage_authority_user_id = fields.Many2one(
        'res.users',
        string='Current Reviewing Authority',
        compute='_compute_current_stage_authority',
        store=True,
        index=True,
        help='The exact system user currently responsible for taking review/approval action in this stage.'
    )
    current_stage_authority_name = fields.Char(
        string='Current Reviewer / Authority',
        compute='_compute_current_stage_authority',
        store=True,
        help='Name and title of the executive currently responsible for taking action in this stage.'
    )
    is_my_executive_case = fields.Boolean(
        string="Pending My Executive",
        compute='_compute_is_my_executive_case',
        search='_search_is_my_executive_case',
        help="True if this case is currently awaiting action by the logged-in secretary's executive."
    )
    last_secretary_reminder_date = fields.Datetime(
        string='Last Reminder Sent',
        readonly=True,
        copy=False,
        help='Timestamp of the last reminder sent by the Executive Office / Secretary.'
    )

    # Executive Summary Fields for CEO and Chiefs
    executive_summary_misconduct = fields.Text(string='Misconduct Summary', compute='_compute_executive_summary', store=True)
    executive_summary_sanction = fields.Char(string='Sanction & Penalty Summary', compute='_compute_executive_summary', store=True)
    executive_summary_financial = fields.Char(string='Financial Exposure / Recovery', compute='_compute_executive_summary', store=True)
    executive_summary_committee = fields.Char(string='Investigation & Committee Status', compute='_compute_executive_summary', store=True)
    executive_flow_step = fields.Integer(
        string='Executive Flow Step',
        compute='_compute_executive_summary',
        store=True,
        help='1: Initiated, 2: Investigation/Hearing, 3: Executive Review, 4: Enforced/Closed'
    )

    @api.depends('punishment_type', 'penalty_percentage', 'fine_days', 'decided_punishment_type', 'decided_penalty_percentage', 'decided_fine_days')
    def _compute_is_payroll_deductible(self):
        for rec in self:
            eff_pct = rec.decided_penalty_percentage if rec.decided_penalty_percentage > 0 else rec.penalty_percentage
            eff_days = rec.decided_fine_days if rec.decided_fine_days > 0 else rec.fine_days
            eff_punish = rec.decided_punishment_type or rec.punishment_type
            rec.is_payroll_deductible = bool(
                eff_pct > 0.0 or
                eff_days > 0.0 or
                eff_punish in ['first_warning_penalty', 'second_warning_penalty', 'final_warning_penalty', 'fine', 'suspension_without_pay']
            )

    @api.depends('offense_id', 'article_id', 'cash_shortage_amount')
    def _compute_is_cash_shortage(self):
        for rec in self:
            is_csh = False
            if rec.cash_shortage_amount > 0:
                is_csh = True
            elif rec.offense_id and rec.offense_id.category_id and rec.offense_id.category_id.code == 'CSH':
                is_csh = True
            elif rec.article_id and '33.9' in (rec.article_id.article_number or ''):
                is_csh = True
            elif rec.offense_id and '33.9' in (rec.offense_id.sub_article_code or ''):
                is_csh = True
            rec.is_cash_shortage = is_csh

    @api.depends('incident_date', 'create_date', 'punishment_type', 'severity_level', 'state')
    def _compute_statutory_deadline(self):
        today = fields.Date.context_today(self)
        for rec in self:
            inc_date = rec.incident_date or (rec.create_date and rec.create_date.date()) or today
            if rec.punishment_type == 'verbal_warning' or rec.severity_level == 'level_5':
                # 7 days per Article 33.11.2
                deadline = inc_date + timedelta(days=7)
            elif rec.punishment_type == 'dismissal' or rec.severity_level == 'level_1':
                # 30 days per Article 33.11.1 & 10.8.2
                deadline = inc_date + timedelta(days=30)
            else:
                # 15 days per Article 33.11.3 & 10.8.1
                deadline = inc_date + timedelta(days=15)
            rec.statutory_deadline_date = deadline
            rec.is_deadline_exceeded = (today > deadline) if rec.state not in ['enforced', 'closed', 'revoked'] else False

    @api.depends('state', 'stage_entry_date', 'incident_date', 'create_date', 'punishment_type', 'severity_level')
    def _compute_stage_sla_tracking(self):
        today = fields.Date.context_today(self)
        now_dt = fields.Datetime.now()
        stage_sla_map = {
            'draft': 5,
            'initiated': 5,
            'coach_review': 5,
            'director_review': 3,
            'submitted_director': 3,
            'chief_review': 5,
            'submitted_chief': 5,
            'ceo_review': 3,
            'investigating': 10,
            'under_investigation': 10,
            'chairman_review': 3,
            'committee_review': 7,
            'pending_approval': 3,
            'enforced': 10,
            'appealed': 10,
        }
        for rec in self:
            entry_dt = rec.stage_entry_date or rec.create_date or now_dt
            entry_d = entry_dt.date() if hasattr(entry_dt, 'date') else today
            target_days = stage_sla_map.get(rec.state, 5)
            rec.stage_target_days = target_days

            # Stage target deadline
            s_deadline = entry_d + timedelta(days=target_days)
            rec.stage_deadline = s_deadline

            # Statutory prescription deadline (Labor proclamation / Article 33.11)
            inc_date = rec.incident_date or (rec.create_date and rec.create_date.date()) or today
            if rec.punishment_type == 'verbal_warning' or rec.severity_level == 'level_5':
                presc_days = 7
            elif rec.punishment_type == 'dismissal' or rec.severity_level == 'level_1':
                presc_days = 30
            else:
                presc_days = 15
            p_deadline = inc_date + timedelta(days=presc_days)
            rec.prescription_deadline = p_deadline

            # SLA Status determination
            if rec.state in ['closed', 'revoked', 'enforced']:
                rec.sla_status = 'on_track'
            else:
                critical_deadline = min(s_deadline, p_deadline)
                days_left = (critical_deadline - today).days
                if days_left < 0:
                    rec.sla_status = 'overdue'
                elif days_left <= 3:
                    rec.sla_status = 'warning'
                else:
                    rec.sla_status = 'on_track'

    @api.depends('stage_entry_date', 'create_date', 'stage_deadline', 'prescription_deadline', 'state')
    def _compute_stage_sla_live(self):
        today = fields.Date.context_today(self)
        now_dt = fields.Datetime.now()
        for rec in self:
            entry_dt = rec.stage_entry_date or rec.create_date or now_dt
            elapsed = (now_dt - entry_dt).total_seconds() / 86400.0 if entry_dt else 0.0
            rec.days_in_stage = max(0, int(elapsed))

            if rec.state in ['closed', 'revoked', 'enforced']:
                rec.sla_countdown_display = _('Completed')
            else:
                s_deadline = rec.stage_deadline or today
                p_deadline = rec.prescription_deadline or today
                critical_deadline = min(s_deadline, p_deadline)
                days_left = (critical_deadline - today).days
                if days_left < 0:
                    rec.sla_countdown_display = _('⚠️ Overdue (%d d)') % abs(days_left)
                elif days_left == 0:
                    rec.sla_countdown_display = _('⏰ Due Today!')
                elif days_left <= 3:
                    rec.sla_countdown_display = _('⏰ %d d left') % days_left
                else:
                    rec.sla_countdown_display = _('✅ %d d left') % days_left

    @api.depends(
        'state', 'employee_id', 'incident_date', 'legal_article_display',
        'description', 'punishment_type', 'penalty_percentage', 'fine_days',
        'cash_shortage_amount', 'investigation_ids', 'investigation_ids.finding_outcome',
        'investigation_ids.state', 'committee_meeting_ids', 'committee_meeting_ids.state',
        'committee_meeting_ids.final_recommendation'
    )
    def _compute_executive_summary(self):
        for rec in self:
            # 1. Misconduct summary - clean description without redundant prefix
            rec.executive_summary_misconduct = rec.description or _('No incident details recorded.')

            # 2. Sanction summary
            pish_dict = dict(rec._fields['punishment_type'].selection) if 'punishment_type' in rec._fields else {}
            sanction_label = pish_dict.get(rec.punishment_type, str(rec.punishment_type or 'Pending Determination'))
            penalties = []
            if rec.penalty_percentage > 0:
                penalties.append(f"{rec.penalty_percentage}% salary deduction")
            if rec.fine_days > 0:
                penalties.append(f"{int(rec.fine_days)} fine day(s)")
            if penalties:
                sanction_label += f" ({', '.join(penalties)})"
            rec.executive_summary_sanction = sanction_label

            # 3. Financial exposure
            if rec.cash_shortage_amount > 0:
                rec.executive_summary_financial = _("ETB %s") % f"{rec.cash_shortage_amount:,.2f}"
            else:
                rec.executive_summary_financial = _("None (No direct cash loss)")

            # 4. Committee / Investigation status
            inv_texts = []
            if rec.investigation_ids:
                last_inv = rec.investigation_ids[-1]
                outcome = dict(last_inv._fields['finding_outcome'].selection).get(last_inv.finding_outcome, last_inv.finding_outcome) if 'finding_outcome' in last_inv._fields else last_inv.finding_outcome
                inv_texts.append(f"Audit: {last_inv.state} ({outcome})")
            if rec.committee_meeting_ids:
                last_mtg = rec.committee_meeting_ids[-1]
                recom = dict(last_mtg._fields['final_recommendation'].selection).get(last_mtg.final_recommendation, last_mtg.final_recommendation) if 'final_recommendation' in last_mtg._fields else last_mtg.final_recommendation
                inv_texts.append(f"Committee: {last_mtg.state} (Recom: {recom})")
            rec.executive_summary_committee = " | ".join(inv_texts) if inv_texts else _("Direct Line Management Review")

            # 5. Executive Lifecycle Flow Step
            if rec.state in ['draft', 'initiated']:
                rec.executive_flow_step = 1
            elif rec.state in ['investigating', 'chairman_review', 'committee_review']:
                rec.executive_flow_step = 2
            elif rec.state in ['submitted_director', 'submitted_chief', 'ceo_review', 'pending_approval']:
                rec.executive_flow_step = 3
            elif rec.state in ['enforced', 'appealed', 'revoked', 'closed']:
                rec.executive_flow_step = 4
            else:
                rec.executive_flow_step = 1

    @api.depends(
        'severity_level_id',
        'severity_level_id.default_punishment_type',
        'offense_id',
        'offense_id.penalty_mode',
        'offense_id.custom_punishment_type',
        'offense_id.custom_fine_days',
        'offense_id.custom_penalty_percentage',
        'offense_id.severity_level_id',
        'offense_id.article_id.severity_level_id',
        'article_id',
        'article_id.severity_level_id',
        'employee_id',
        'incident_date',
        'decided_punishment_type',
        'decided_penalty_percentage',
        'decided_fine_days',
        'cash_shortage_amount',
        'is_statutory_mitigation_applied',
        'appeal_outcome_type',
        'appeal_ids',
        'appeal_ids.state',
        'appeal_ids.decision_outcome',
        'appeal_ids.revised_punishment_type',
        'appeal_ids.revised_penalty_percentage',
        'appeal_ids.revised_fine_days',
        'appeal_ids.review_date',
    )
    def _compute_punishment_details(self):
        rank_order = {
            'verbal_warning': 1,
            'first_warning_penalty': 2,
            'second_warning_penalty': 3,
            'final_warning_penalty': 4,
            'dismissal': 5,
        }
        rank_to_punish = {
            1: 'verbal_warning',
            2: 'first_warning_penalty',
            3: 'second_warning_penalty',
            4: 'final_warning_penalty',
            5: 'dismissal',
        }
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            is_managerial = (rec.staff_category == 'managerial') if rec.staff_category else rec._is_employee_managerial(emp)

            # 1. Count active prior penalties within validity window
            inc_date = rec.incident_date or fields.Date.context_today(rec)
            all_prior = self.env['discipline.case'].sudo().search([
                ('employee_id', '=', emp.id),
                ('id', '!=', rec._origin.id if rec._origin else (rec.id or 0)),
                ('state', 'in', ['enforced', 'closed', 'appealed']),
            ]) if emp else self.env['discipline.case']

            prior_cases = all_prior.filtered(
                lambda c: (c.active_penalty_end_date and c.active_penalty_end_date >= inc_date) or
                          (not c.active_penalty_end_date and (c.final_decision_date or c.incident_date) and 
                           ((c.final_decision_date or c.incident_date) + timedelta(days=c.active_duration_days or 365)) >= inc_date)
            )

            has_active_prior_warning = bool(prior_cases)
            if rec.is_attendance_case:
                same_offense_cases = prior_cases.filtered(
                    lambda c: (c.offense_id and rec.offense_id and c.offense_id == rec.offense_id) or
                              (c.article_id and rec.article_id and c.article_id == rec.article_id) or
                              (c.is_attendance_case and c.attendance_violation_type and c.attendance_violation_type == rec.attendance_violation_type)
                )
            else:
                same_offense_cases = prior_cases.filtered(
                    lambda c: (c.offense_id and rec.offense_id and c.offense_id == rec.offense_id) or
                              (c.article_id and rec.article_id and c.article_id == rec.article_id)
                ) if (rec.offense_id or rec.article_id) else self.env['discipline.case']

            occurrence = len(same_offense_cases) + 1
            rec.occurrence_count = occurrence

            punish = False
            pct = 0.0
            days = 0.0
            rule_notes = []

            off = rec.offense_id
            lvl = rec.severity_level_id or (off and off.severity_level_id) or (off and off.article_id and off.article_id.severity_level_id)

            # Cash Shortage Matrix Handling (Article 33.9)
            is_csh_calc = rec.cash_shortage_amount > 0 or (off and off.category_id and off.category_id.code == 'CSH') or (off and '33.9' in (off.sub_article_code or '')) or (rec.article_id and '33.9' in (rec.article_id.article_number or ''))
            if is_csh_calc and rec.cash_shortage_amount > 0:
                csh_amt = rec.cash_shortage_amount
                if csh_amt <= 500:
                    if occurrence == 1:
                        punish = 'verbal_warning'
                        pct = 0.0
                    elif occurrence == 2:
                        punish = 'first_warning_penalty'
                        pct = 0.0
                    elif occurrence == 3:
                        punish = 'second_warning_penalty'
                        pct = 10.0
                    else:
                        punish = 'final_warning_penalty'
                        pct = 20.0
                elif csh_amt <= 5000:
                    if occurrence == 1:
                        punish = 'first_warning_penalty'
                        pct = 0.0
                    elif occurrence in (2, 3):
                        punish = 'second_warning_penalty'
                        pct = 10.0
                    else:
                        punish = 'final_warning_penalty'
                        pct = 20.0
                elif csh_amt <= 10000:
                    if occurrence == 1:
                        punish = 'second_warning_penalty'
                        pct = 10.0
                    elif occurrence == 2:
                        punish = 'final_warning_penalty'
                        pct = 20.0
                    else:
                        punish = 'demotion'
                        pct = 0.0
                elif csh_amt <= 20000:
                    if occurrence == 1:
                        punish = 'second_warning_penalty'
                        pct = 10.0
                    elif occurrence == 2:
                        punish = 'final_warning_penalty'
                        pct = 20.0
                    else:
                        punish = 'dismissal'
                        pct = 0.0
                else:  # > 20,000 ETB
                    if occurrence == 1:
                        punish = 'final_warning_penalty'
                        pct = 20.0
                    else:
                        punish = 'dismissal'
                        pct = 0.0
                rule_notes.append(_('Applied Article 33.9 Cash Shortage Matrix (Amount: ETB %s, Recurrence Tier: %s)') % (csh_amt, occurrence))

            elif off:
                if off.penalty_mode == 'repetition_escalation' and off.line_ids:
                    # Match repetition line
                    match_line = off.line_ids.filtered(lambda l: l.occurrence_number == occurrence)
                    if not match_line:
                        # If occurrence exceeds max lines, pick highest tier
                        sorted_lines = off.line_ids.sorted('occurrence_number')
                        match_line = sorted_lines[-1:] if sorted_lines else False
                    if match_line:
                        line = match_line[0]
                        punish = line.punishment_type
                        if is_managerial:
                            pct = line.managerial_penalty_pct or 0.0
                            days = line.managerial_fine_days if line.managerial_fine_days else (line.fine_days or (3.0 if punish == 'final_warning_penalty' else (2.0 if punish == 'second_warning_penalty' else (1.0 if punish == 'first_warning_penalty' else 0.0))))
                        else:
                            pct = line.non_managerial_penalty_pct if line.non_managerial_penalty_pct else (line.penalty_percentage or (20.0 if punish == 'final_warning_penalty' else (10.0 if punish == 'second_warning_penalty' else (5.0 if punish == 'first_warning_penalty' else 0.0))))
                            days = 0.0
                        rule_notes.append(_('Applied Repetition Escalation Ladder (Tier %s / %s)') % (occurrence, line.occurrence_label or ''))
                elif off.penalty_mode == 'article_override':
                    punish = off.custom_punishment_type or getattr(off, 'punishment_type', False) or (lvl and lvl.default_punishment_type)
                    if is_managerial or off.staff_category == 'managerial' or (off.custom_fine_days and not off.custom_penalty_percentage):
                        pct = off.custom_penalty_percentage or 0.0
                        days = off.custom_fine_days or getattr(off, 'fine_days', 0.0) or (3.0 if punish == 'final_warning_penalty' else (2.0 if punish == 'second_warning_penalty' else (1.0 if punish == 'first_warning_penalty' else 0.0)))
                    else:
                        pct = off.custom_penalty_percentage or getattr(off, 'penalty_percentage', 0.0) or (20.0 if punish == 'final_warning_penalty' else (10.0 if punish == 'second_warning_penalty' else (5.0 if punish == 'first_warning_penalty' else 0.0)))
                        days = 0.0
                    if not punish and days > 0:
                        punish = 'fine'
                    rule_notes.append(_('Applied Custom Article Penalty Override (%s, %s days fine, %s%% deduction)') % (punish, days, pct))

            if not punish and lvl:
                punish = lvl.default_punishment_type
                if is_managerial:
                    pct = getattr(lvl, 'default_managerial_penalty_pct', 0.0)
                    days = getattr(lvl, 'default_managerial_fine_days', 0.0) or getattr(lvl, 'default_fine_days', 0.0) or (3.0 if lvl.code == 'level_2' else (2.0 if lvl.code == 'level_3' else (1.0 if lvl.code == 'level_4' else 0.0)))
                else:
                    pct = getattr(lvl, 'default_non_managerial_penalty_pct', 0.0) or getattr(lvl, 'default_penalty_percentage', 0.0) or (20.0 if lvl.code == 'level_2' else (10.0 if lvl.code == 'level_3' else (5.0 if lvl.code == 'level_4' else 0.0)))
                    days = 0.0
                rule_notes.append(_('Prescribed by Severity Standard (%s)') % lvl.name)

            # Check Article 33.1.4 1-grade escalation if active prior warning exists and not already dismissal
            is_escalated = False
            escalated_msg = False
            if has_active_prior_warning and punish and punish != 'dismissal' and off and off.penalty_mode != 'repetition_escalation' and not is_csh_calc:
                curr_rank = rank_order.get(punish, 2)
                next_rank = min(curr_rank + 1, 5)
                if next_rank > curr_rank:
                    punish = rank_to_punish.get(next_rank, punish)
                    is_escalated = True
                    # Update penalty rate to match the escalated rank
                    pct, days = self._get_standard_rate_for_punishment(punish, is_managerial)
                    punish_display = dict(rec._fields['punishment_type'].selection).get(punish, punish)
                    prior_count = len(prior_cases)
                    warning_text = _('%d active prior disciplinary warning') % prior_count if prior_count == 1 else _('%d active prior disciplinary warnings') % prior_count
                    escalated_msg = _('Sanction elevated to %s due to %s on the employee\'s record.') % (punish_display, warning_text)

            # Store unmitigated standard catalog baseline
            standard_catalog_punish = punish
            standard_catalog_pct = pct
            standard_catalog_days = days

            # Check Article 33.13 Statutory Mitigation (Multi-Level Step-Down Allowed)
            mitigated_msg = False
            if rec.is_statutory_mitigation_applied and standard_catalog_punish:
                mitigation_rank_map = {
                    'dismissal': 'final_warning_penalty',
                    'demotion': 'second_warning_penalty',
                    'final_warning_penalty': 'second_warning_penalty',
                    'second_warning_penalty': 'first_warning_penalty',
                    'first_warning_penalty': 'verbal_warning',
                }
                default_mitigated = mitigation_rank_map.get(standard_catalog_punish, 'verbal_warning')
                catalog_rank = rank_order.get(standard_catalog_punish, 0)
                chosen_punish = rec.punishment_type
                chosen_rank = rank_order.get(chosen_punish, 0)

                # If user selected an allowable lower sanction (multi-level mitigation), honor it
                if chosen_punish and 0 < chosen_rank < catalog_rank:
                    punish = chosen_punish
                else:
                    punish = default_mitigated

                pct, days = self._get_standard_rate_for_punishment(punish, is_managerial, prev_pct=pct, prev_days=days)
                mitigated_display = dict(rec._fields['punishment_type'].selection).get(punish, punish)
                mitigated_msg = _('Sanction mitigated to %s in consideration of clean service record and mitigating factors.') % mitigated_display

            # Final enforcement of staff category segregation
            if not is_managerial:
                days = 0.0
            else:
                pct = 0.0

            rec.is_escalated_by_active_warning = is_escalated
            if escalated_msg and mitigated_msg:
                rec.auto_applied_rule_summary = f"{escalated_msg} {mitigated_msg}"
            elif escalated_msg:
                rec.auto_applied_rule_summary = escalated_msg
            elif mitigated_msg:
                rec.auto_applied_rule_summary = mitigated_msg
            elif rule_notes:
                rec.auto_applied_rule_summary = ' '.join(rule_notes)
            else:
                rec.auto_applied_rule_summary = False

            rec.original_punishment_type = standard_catalog_punish
            rec.original_penalty_percentage = standard_catalog_pct
            rec.original_fine_days = standard_catalog_days

            # Check decided appeals first
            decided_appeals = rec.appeal_ids.filtered(lambda a: a.state == 'decided').sorted(
                lambda a: (a.review_date or (a.write_date.date() if a.write_date else fields.Date.today()), a.id or 0),
                reverse=True
            )
            if decided_appeals:
                last_app = decided_appeals[0]
                if last_app.decision_outcome == 'overturned' or last_app.revised_punishment_type == 'exonerate':
                    rec.punishment_type = 'exonerate'
                    rec.penalty_percentage = 0.0
                    rec.fine_days = 0.0
                elif last_app.decision_outcome == 'penalty_reduced':
                    rec.punishment_type = last_app.revised_punishment_type or punish
                    rec.penalty_percentage = last_app.revised_penalty_percentage
                    rec.fine_days = last_app.revised_fine_days
                elif last_app.decision_outcome == 'upheld':
                    rec.punishment_type = rec.decided_punishment_type or punish
                    rec.penalty_percentage = rec.decided_penalty_percentage if rec.decided_penalty_percentage > 0 else pct
                    rec.fine_days = rec.decided_fine_days if rec.decided_fine_days > 0 else days
            elif rec.appeal_outcome_type == 'exonerated' or (rec.state in ('enforced', 'closed', 'appealed') and rec.punishment_type == 'exonerate'):
                rec.punishment_type = 'exonerate'
                rec.penalty_percentage = 0.0
                rec.fine_days = 0.0
            else:
                rec.punishment_type = rec.decided_punishment_type or punish
                rec.penalty_percentage = rec.decided_penalty_percentage if rec.decided_penalty_percentage > 0 else pct
                rec.fine_days = rec.decided_fine_days if rec.decided_fine_days > 0 else days

    @api.model
    def _get_standard_rate_for_punishment(self, punish, is_managerial, prev_pct=0.0, prev_days=0.0):
        """Return standard (penalty_percentage, fine_days) tuple for a given punishment and staff category."""
        if punish == 'verbal_warning':
            return 0.0, 0.0
        elif punish == 'first_warning_penalty':
            return (0.0, 1.0) if is_managerial else (5.0, 0.0)
        elif punish == 'second_warning_penalty':
            return (0.0, 2.0) if is_managerial else (10.0, 0.0)
        elif punish == 'final_warning_penalty':
            return (0.0, 3.0) if is_managerial else (20.0, 0.0)
        elif punish in ('demotion', 'dismissal', 'exonerate'):
            return 0.0, 0.0
        return prev_pct, prev_days

    @api.model
    def _get_coach_max_authority(self):
        """
        Returns tuple: (max_punishment_key, max_rank_int, allowed_severity_codes_list)
        Punishment Ranks:
        1: verbal_warning (Level 5)
        2: first_warning_penalty (Level 4)
        3: second_warning_penalty (Level 3)
        4: final_warning_penalty (Level 2)
        6: dismissal (Level 1)
        """
        punish_to_rank = {
            'verbal_warning': (1, ['level_5']),
            'first_warning_penalty': (2, ['level_5', 'level_4']),
            'second_warning_penalty': (3, ['level_5', 'level_4', 'level_3']),
            'final_warning_penalty': (4, ['level_5', 'level_4', 'level_3', 'level_2']),
            'dismissal': (6, ['level_5', 'level_4', 'level_3', 'level_2', 'level_1']),
        }
        ICP = self.env['ir.config_parameter'].sudo()
        cfg_punish = ICP.get_param('discipline.coach_max_punishment', 'final_warning_penalty')
        rank, allowed_levels = punish_to_rank.get(cfg_punish, (4, ['level_5', 'level_4', 'level_3', 'level_2']))
        return cfg_punish, rank, allowed_levels

    @api.onchange('employee_id', 'case_action_track')
    def _onchange_employee_id_filter_regulations(self):
        if self.employee_id:
            emp = self.employee_id.sudo()
            is_mgr = self._is_employee_managerial(emp)
            cat = 'managerial' if is_mgr else 'non_managerial'
            self.is_managerial = is_mgr
            self.staff_category = cat
            self.staff_category_display = _('Managerial') if is_mgr else _('Non-Managerial')

            cfg_punish, max_rank, allowed_levels_codes = self._get_coach_max_authority()
            is_direct = (self.case_action_track == 'direct_enforce')

            self._compute_allowed_offense_ids()
            allowed_offense_ids = self.allowed_offense_ids.ids

            article_domain = [('staff_category', 'in', [cat, 'all'])]
            if is_direct:
                article_domain.append(('severity_level_id.code', 'in', allowed_levels_codes + [False]))

            if self.article_id and self.article_id.staff_category not in [cat, 'all']:
                self.article_id = False
                self.offense_id = False
                self.severity_level_id = False
            elif is_direct and self.article_id and self.article_id.severity_level_id and self.article_id.severity_level_id.code not in allowed_levels_codes:
                self.article_id = False
                self.offense_id = False
                self.severity_level_id = False

            if self.offense_id and (self.offense_id.staff_category not in [cat, 'all'] or self.offense_id.id not in allowed_offense_ids):
                self.offense_id = False
                self.severity_level_id = False

            return {
                'domain': {
                    'policy_version_id': [('staff_category', 'in', [cat, 'all'])],
                    'article_id': article_domain,
                    'offense_id': [('id', 'in', allowed_offense_ids)],
                }
            }
        else:
            self.is_managerial = False
            self.staff_category = False
            self.staff_category_display = False
            return {
                'domain': {
                    'policy_version_id': [],
                    'article_id': [],
                    'offense_id': [],
                }
            }

    @api.onchange('severity_level_id')
    def _onchange_severity_level_id(self):
        cat = self.staff_category or 'non_managerial'
        res = {'domain': {}}
        self._compute_allowed_offense_ids()
        allowed_ids = self.allowed_offense_ids.ids
        if self.severity_level_id:
            if self.offense_id and self.offense_id.severity_level_id and self.offense_id.severity_level_id != self.severity_level_id:
                self.offense_id = False
            matching_article = self.env['discipline.article'].search([
                ('severity_level_id', '=', self.severity_level_id.id),
                ('staff_category', 'in', [cat, 'all']),
            ], limit=1)
            if matching_article:
                self.article_id = matching_article
                if not self.policy_version_id:
                    self.policy_version_id = matching_article.policy_version_id
            offense_domain = [
                ('staff_category', 'in', [cat, 'all']),
                ('id', 'in', allowed_ids),
                '|',
                ('severity_level_id', '=', self.severity_level_id.id),
                ('article_id.severity_level_id', '=', self.severity_level_id.id),
            ]
            res['domain']['offense_id'] = offense_domain
        else:
            res['domain']['offense_id'] = [('id', 'in', allowed_ids)]
        self._compute_punishment_details()
        return res

    @api.onchange('article_id')
    def _onchange_article_id(self):
        if self.article_id:
            if not self.policy_version_id:
                self.policy_version_id = self.article_id.policy_version_id
            if self.article_id.severity_level_id:
                self.severity_level_id = self.article_id.severity_level_id
            if self.offense_id and self.offense_id.article_id and self.offense_id.article_id != self.article_id:
                self.offense_id = False
            self._compute_allowed_offense_ids()
            return {
                'domain': {
                    'offense_id': [('article_id', '=', self.article_id.id), ('id', 'in', self.allowed_offense_ids.ids)]
                }
            }

    @api.onchange('offense_id')
    def _onchange_offense_id(self):
        if self.offense_id:
            if self.offense_id.article_id:
                self.article_id = self.offense_id.article_id
                if not self.policy_version_id:
                    self.policy_version_id = self.offense_id.article_id.policy_version_id
            if self.offense_id.severity_level_id:
                self.severity_level_id = self.offense_id.severity_level_id
            elif self.offense_id.article_id and self.offense_id.article_id.severity_level_id:
                self.severity_level_id = self.offense_id.article_id.severity_level_id
            
            art_code = ''
            if self.article_id and self.article_id.article_number:
                art_code = self.article_id.article_number.replace('Article', '').strip()
            sub_code = self.offense_id.sub_article_code.strip() if self.offense_id.sub_article_code else ''
            self.article_display = f"{art_code} - {sub_code}" if (art_code and sub_code) else (sub_code or art_code or False)
            self._compute_legal_citation()

            text = self.offense_id.full_clause_text or self.offense_id.name
            if text:
                escaped_text = html_escape(text)
                title_html = f'<div style="font-weight: 700; color: #111827; margin-bottom: 4px;">{html_escape(self.offense_id.title)}</div>' if self.offense_id.title else ''
                self.offense_detail_html = Markup(
                    f'<details open="open" style="margin-top: 4px; font-size: 13px;">'
                    f'<summary style="cursor: pointer; color: #017e84; font-weight: 600; font-size: 12px; outline: none; margin-bottom: 4px;">'
                    f'▾ Show full definition / ዝርዝር ድንጋጌ (Click to collapse/expand)'
                    f'</summary>'
                    f'<div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-left: 3px solid #017e84; border-radius: 4px; padding: 8px 12px; white-space: pre-wrap; line-height: 1.5; color: #212529;">'
                    f'{title_html}'
                    f'{escaped_text}'
                    f'</div>'
                    f'</details>'
                )
            else:
                self.offense_detail_html = False
            self.legal_clause_text = self.offense_id.full_clause_text
            # If Level 5 (Verbal Warning), reset statutory mitigation since it is already the minimum sanction
            if self.severity_level_id and self.severity_level_id.code == 'level_5':
                self.is_statutory_mitigation_applied = False
                self.mitigation_justification = False
        else:
            self.severity_level_id = False
            self.article_id = False
            self.article_display = False
            self.offense_detail_html = False
            self.legal_clause_text = False
            self.is_statutory_mitigation_applied = False
            self.mitigation_justification = False
        self._compute_punishment_details()
        is_dismissal = (
            (self.severity_level_id and self.severity_level_id.code == 'level_1') or
            (self.offense_id and (self.offense_id.severity_level == 'level_1' or self.offense_id.custom_punishment_type == 'dismissal')) or
            self.punishment_type == 'dismissal'
        )
        can_escalate = bool(self.is_director_user or self.is_hr_admin or self.is_auditor_user)
        if is_dismissal and can_escalate and self.case_action_track == 'direct_enforce':
            self.case_action_track = 'committee_escalation'

    @api.onchange('severity_level_id', 'offense_id', 'employee_id', 'cash_shortage_amount', 'is_statutory_mitigation_applied')
    def _onchange_offense_severity_resolve_rules(self):
        """Re-trigger rule resolution immediately when severity level, offense, employee, cash shortage, or mitigation changes."""
        self._compute_punishment_details()

    @api.onchange('punishment_type')
    def _onchange_mitigated_punishment_type(self):
        """Update penalty percentages and fine days when initiator selects a mitigated punishment."""
        if self.is_statutory_mitigation_applied and self.punishment_type:
            is_mgr = (self.staff_category == 'managerial')
            self.penalty_percentage, self.fine_days = self._get_standard_rate_for_punishment(
                self.punishment_type, is_mgr, prev_pct=self.penalty_percentage, prev_days=self.fine_days
            )

    penalty_percentage = fields.Float(string='Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    fine_days = fields.Float(string='Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    property_repair_cost = fields.Float(string='Property Repair / Replacement Cost (ETB)', tracking=True)
    is_managerial = fields.Boolean(string='Is Managerial Employee', compute='_compute_staff_category', store=True, readonly=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial'),
        ('managerial', 'Managerial'),
    ], string='Staff Category', compute='_compute_staff_category', store=True)
    staff_category_display = fields.Char(string='Staff Category Display', compute='_compute_staff_category', store=True)

    def _is_employee_managerial(self, emp):
        """Determine whether an employee belongs to Managerial Staff based on hr.job.employee_category or job title."""
        if not emp:
            return False
        emp_sudo = emp.sudo()
        job = emp_sudo.job_id or getattr(emp_sudo, 'job_position', False)
        job_name = (job.name or '').lower() if job else ''
        job_cat = getattr(job, 'employee_category', False) if job else False
        if getattr(emp_sudo, 'is_managerial', False) or (job and getattr(job, 'is_managerial', False)):
            return True
        if job_cat == 'Managerial':
            return True
        if job_cat == 'Non Managerial':
            if any(kw in job_name for kw in ['acting manager', 'acting director', 'acting branch manager', 'acting chief']):
                return True
            return False
        if any(kw in job_name for kw in ['manager', 'director', 'chief', 'team leader', 'head', 'vp', 'supervisor', 'president', 'officer in charge']) and 'relationship manager' not in job_name:
            return True
        return False

    @api.depends('employee_id')
    def _compute_staff_category(self):
        for rec in self:
            if rec.state in ('hearing', 'pending_approval', 'enforced', 'appealed', 'closed') and rec.staff_category:
                rec.is_managerial = (rec.staff_category == 'managerial')
                rec.staff_category_display = _('Managerial') if rec.staff_category == 'managerial' else _('Non-Managerial')
                continue
            emp = rec.employee_id.sudo() if rec.employee_id else False
            if not emp:
                rec.is_managerial = False
                rec.staff_category = False
                rec.staff_category_display = False
                continue
            if rec._is_employee_managerial(emp):
                rec.is_managerial = True
                rec.staff_category = 'managerial'
                rec.staff_category_display = _('Managerial')
            else:
                rec.is_managerial = False
                rec.staff_category = 'non_managerial'
                rec.staff_category_display = _('Non-Managerial')

    def _default_initiator_type(self):
        user = self.env.user
        emp = user.employee_id if user else False
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
        exec_lvl = getattr(emp, 'executive_level', False) if emp else False

        if user.has_group('discipline_management.group_discipline_auditor'):
            return 'audit'
        user_dept_name = (emp.department_id.name or '').lower() if emp and emp.department_id else ''
        if 'audit' in user_dept_name or 'compliance' in user_dept_name:
            return 'audit'
        if (exec_lvl in ('director', 'chief', 'ceo') or
            user.has_group('discipline_management.group_discipline_director') or
            any(k in job_name for k in ['director', 'regional manager', 'deputy chief', 'chief', 'vp'])):
            return 'director'
        return 'manager'

    @api.depends('reported_by_id')
    def _compute_initiator_type(self):
        for rec in self:
            emp = rec.reported_by_id or (rec.create_uid and rec.create_uid.employee_id) or self.env.user.employee_id
            user = (emp and emp.user_id) or rec.create_uid or self.env.user
            job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
            exec_lvl = getattr(emp, 'executive_level', False) if emp else False

            if user and user.has_group('discipline_management.group_discipline_auditor'):
                rec.initiator_type = 'audit'
                continue
            user_dept_name = (emp.department_id.name or '').lower() if emp and emp.department_id else ''
            if 'audit' in user_dept_name or 'compliance' in user_dept_name:
                rec.initiator_type = 'audit'
                continue
            if (exec_lvl in ('director', 'chief', 'ceo') or
                (user and user.has_group('discipline_management.group_discipline_director')) or
                any(k in job_name for k in ['director', 'regional manager', 'deputy chief', 'chief', 'vp'])):
                rec.initiator_type = 'director'
                continue
            rec.initiator_type = 'manager'

    case_action_track = fields.Selection([
        ('direct_enforce', 'Direct Action (Coach / Minor Misconduct)'),
        ('committee_escalation', 'Formal Escalation (Chief / Committee / Major Misconduct)'),
    ], string='Disciplinary Action Track', default='direct_enforce', required=True, tracking=True)

    initiator_type = fields.Selection([
        ('manager', 'Coach / Line Manager'),
        ('director', 'Directorate Director'),
        ('audit', 'Internal Audit / Compliance'),
    ], string='Case Initiator Source', compute='_compute_initiator_type', default=_default_initiator_type, store=True, readonly=False, tracking=True)

    coach_id = fields.Many2one(
        'hr.employee',
        string='Direct Coach / Line Manager',
        related='employee_id.coach_id',
        store=True,
        readonly=True
    )

    director_id = fields.Many2one(
        'res.users',
        string='Directorate Director',
        compute='_compute_hierarchy_stakeholders',
        store=True,
        readonly=False,
        tracking=True
    )

    chief_id = fields.Many2one(
        'res.users',
        string='Respective Executive / Chief Officer',
        compute='_compute_hierarchy_stakeholders',
        store=True,
        readonly=False,
        tracking=True
    )

    def _resolve_case_hierarchy_stakeholders(self):
        """
        Traverse the supervisor/coach hierarchy chain to locate:
        1. Directorate Director
        2. Immediate Executive Authority above Director (Deputy Chief / Chief Officer) without skipping levels.
        """
        self.ensure_one()
        director_user = False
        chief_user = False

        rep_emp = self.reported_by_id or (self.create_uid and self.create_uid.employee_id) or self.env.user.employee_id
        rep_user = (rep_emp and rep_emp.user_id) or self.create_uid or self.env.user
        rep_job = (rep_emp.job_id.name or '').lower() if rep_emp and rep_emp.job_id else ''
        rep_is_dir_or_above = rep_emp and (
            getattr(rep_emp, 'executive_level', False) in ('director', 'chief', 'ceo') or
            any(k in rep_job for k in ['director', 'regional manager', 'deputy chief', 'chief', 'vp'])
        )

        # Case 1: Initiator is already a Directorate Director (or above)
        if rep_is_dir_or_above:
            director_user = rep_user
            # Find the immediate executive supervisor directly above the initiator in their reporting line
            for mgr in rep_emp.sudo().get_supervisor_chain():
                m_job = (mgr.job_id.name or '').lower() if mgr.job_id else ''
                m_exec = getattr(mgr, 'executive_level', False)
                if mgr.user_id and (
                    m_exec in ('director', 'chief', 'ceo') or
                    any(k in m_job for k in ['deputy chief', 'chief', 'vp', 'cio', 'cdo', 'cpco', 'cfo', 'coo', 'ceo', 'president', 'director'])
                ):
                    chief_user = mgr.user_id
                    break
        else:
            # Case 2: Initiator is a Coach / Line Manager or other staff
            subject_emp = self.employee_id.sudo() if self.employee_id else False
            emp_chain = subject_emp.get_supervisor_chain() if subject_emp else []
            for idx, mgr in enumerate(emp_chain):
                m_job = (mgr.job_id.name or '').lower() if mgr.job_id else ''
                m_exec = getattr(mgr, 'executive_level', False)
                if not director_user and (
                    m_exec in ('director', 'chief', 'ceo') or
                    any(k in m_job for k in ['director', 'regional manager', 'deputy chief', 'chief', 'vp'])
                ):
                    if mgr.user_id:
                        director_user = mgr.user_id
                        # The executive reviewer is the immediate executive authority above the director in the chain
                        for next_mgr in emp_chain[idx + 1:]:
                            nm_job = (next_mgr.job_id.name or '').lower() if next_mgr.job_id else ''
                            nm_exec = getattr(next_mgr, 'executive_level', False)
                            if next_mgr.user_id and (
                                nm_exec in ('director', 'chief', 'ceo') or
                                any(k in nm_job for k in ['deputy chief', 'chief', 'vp', 'cio', 'cdo', 'cpco', 'cfo', 'coo', 'ceo', 'president'])
                            ):
                                chief_user = next_mgr.user_id
                                break
                        break

        # Fallback for Chief Officer if not in direct reporting line
        if not chief_user:
            chief_emp = self.env['hr.employee'].sudo().search([
                ('executive_level', '=', 'chief'),
                ('user_id', '!=', False)
            ], limit=1)
            if chief_emp and chief_emp.user_id:
                chief_user = chief_emp.user_id
            else:
                chief_user = self.env['hr.employee'].sudo().get_cpco_user()

        return director_user, chief_user

    @api.depends('employee_id', 'reported_by_id', 'case_action_track')
    def _compute_hierarchy_stakeholders(self):
        for rec in self:
            dir_u, chief_u = rec._resolve_case_hierarchy_stakeholders()
            rec.director_id = dir_u or False
            rec.chief_id = chief_u or False

    def _get_next_escalation_supervisor(self):
        """
        Dynamically determine the next supervisory authority in the chain above the current executive reviewer.
        Returns: (next_user, is_ceo, next_role_label)
        """
        self.ensure_one()
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        current_reviewer_user = self.chief_id or self.director_id or self.env.user
        
        current_emp = current_reviewer_user.employee_id.sudo() if current_reviewer_user and current_reviewer_user.employee_id else False
        if not current_emp:
            return ceo_user, True, _("Chief Executive Officer (CEO)")
            
        sup_chain = current_emp.get_supervisor_chain()
        next_user = False
        next_emp = False
        
        for sup in sup_chain:
            if sup.user_id and sup.user_id.id != current_reviewer_user.id:
                next_user = sup.user_id
                next_emp = sup
                break
                
        # If no supervisor in chain, or next_user is CEO
        if not next_user or (ceo_user and next_user.id == ceo_user.id) or next_user.has_group('discipline_management.group_discipline_ceo'):
            return ceo_user, True, _("Chief Executive Officer (CEO)")
            
        next_job = (next_emp.job_id.name or _("Executive Authority")) if next_emp and next_emp.job_id else _("Executive Authority")
        return next_user, False, f"{next_job} ({next_user.name})"

    next_escalation_target_name = fields.Char(
        string='Next Escalation Target',
        compute='_compute_next_escalation_target',
        compute_sudo=True,
        help='Name and title of the next executive authority in the supervisory chain.'
    )

    case_flow_from_display = fields.Char(
        string='Escalated From (Originator)',
        compute='_compute_case_governance_flow',
        compute_sudo=True,
        help='The official or department who initiated this case.'
    )
    case_flow_to_display = fields.Char(
        string='Routes Next To (Target Authority)',
        compute='_compute_case_governance_flow',
        compute_sudo=True,
        help='The destination authority or body that will receive the case after this stage.'
    )
    case_flow_stepper_html = fields.Html(
        string='Case Routing Flow',
        compute='_compute_case_governance_flow',
        compute_sudo=True,
        sanitize=False
    )
    case_flow_verbal_briefing = fields.Html(
        string='In-Person Briefing for Boss',
        compute='_compute_case_governance_flow',
        compute_sudo=True,
        sanitize=False
    )

    @api.depends('chief_id', 'director_id', 'state', 'escalation_target', 'case_action_track')
    def _compute_next_escalation_target(self):
        for rec in self:
            case_sudo = rec.sudo()
            if case_sudo.state in ('draft', 'initiated'):
                rec.next_escalation_target_name = case_sudo.director_id.name if case_sudo.director_id else _("Directorate Director")
            elif case_sudo.state in ('submitted_director', 'director_review'):
                rec.next_escalation_target_name = case_sudo.chief_id.name if case_sudo.chief_id else _("Respective Chief Officer")
            elif case_sudo.state in ('submitted_chief', 'chief_review'):
                if case_sudo.escalation_target == 'audit':
                    rec.next_escalation_target_name = _("Internal Audit Directorate")
                elif case_sudo.case_action_track == 'committee_escalation':
                    rec.next_escalation_target_name = _("Discipline Committee / CPCO Review")
                else:
                    next_usr, is_ceo, target_label = case_sudo._get_next_escalation_supervisor()
                    rec.next_escalation_target_name = target_label or _("Chief Executive Officer (CEO)")
            elif case_sudo.state in ('investigating', 'under_investigation'):
                rec.next_escalation_target_name = case_sudo.chief_id.name if case_sudo.chief_id else _("Respective Executive / CPCO")
            elif case_sudo.state in ('committee_review', 'chairman_review'):
                rec.next_escalation_target_name = _("Chief Executive Officer (CEO)")
            elif case_sudo.state in ('ceo_review', 'pending_approval'):
                rec.next_escalation_target_name = _("HR Operations & POMD (Enforcement)")
            elif case_sudo.state in ('enforced', 'closed'):
                rec.next_escalation_target_name = _("Final Enforcement Complete")
            elif case_sudo.state == 'appealed':
                rec.next_escalation_target_name = _("Discipline Appeal Review Panel")
            else:
                rec.next_escalation_target_name = _("Next Review Authority")

    @api.depends(
        'reported_by_id', 'initiator_id', 'initiator_type', 'create_uid', 'employee_id',
        'operating_unit_id', 'department_id', 'state', 'current_stage_authority_name',
        'next_escalation_target_name', 'sla_countdown_display', 'stage_deadline',
        'days_in_stage', 'stage_target_days', 'sla_status'
    )
    def _compute_case_governance_flow(self):
        st_dict = dict(self._fields['state'].selection) if 'state' in self._fields else {}
        for rec in self:
            case_sudo = rec.sudo()
            # 1. From (Originator) via sudo
            rep_emp = case_sudo.reported_by_id or (case_sudo.create_uid and case_sudo.create_uid.employee_id)
            from_name = ""
            from_role = ""
            if rep_emp:
                rep_sudo = rep_emp.sudo()
                from_name = rep_sudo.name or ""
                rep_job = (rep_sudo.job_id.name if rep_sudo.job_id else getattr(rep_sudo, 'job_name', False)) or ''
                if not rep_job and getattr(rep_sudo, 'job_position', False):
                    rep_job = rep_sudo.job_position.name or ''
                init_type_lbl = dict(rec._fields['initiator_type'].selection).get(case_sudo.initiator_type, '')
                from_role = rep_job or init_type_lbl or _("Case Initiator")
            elif case_sudo.initiator_id:
                from_name = case_sudo.initiator_id.sudo().name or ""
                from_role = _("Case Initiator")
            else:
                from_name = case_sudo.create_uid.sudo().name or _("Initiator")
                from_role = _("Reporting Authority")

            rec.case_flow_from_display = f"{from_name} ({from_role})" if from_role else from_name

            # 2. Current Desk / Boss via sudo
            curr_name = case_sudo.current_stage_authority_name or _("Pending Assignment")
            curr_stage_lbl = st_dict.get(case_sudo.state, case_sudo.state or _("Under Review"))

            # 3. Next Destination via sudo
            next_target = case_sudo.next_escalation_target_name or _("Supervisory Authority / Enforcement")
            rec.case_flow_to_display = next_target

            # 4. In-Person Verbal Briefing Script for Secretary to Boss via sudo
            emp_sudo = case_sudo.employee_id.sudo() if case_sudo.employee_id else False
            emp_name = emp_sudo.name if emp_sudo else _("The Employee")
            ou_sudo = case_sudo.operating_unit_id.sudo() if case_sudo.operating_unit_id else False
            dept_sudo = case_sudo.department_id.sudo() if case_sudo.department_id else False
            ou_name = ou_sudo.name if ou_sudo else (dept_sudo.name if dept_sudo else _("Operating Unit"))
            deadline_str = case_sudo.stage_deadline.strftime('%b %d, %Y') if case_sudo.stage_deadline else _("within target SLA")
            sla_text = case_sudo.sla_countdown_display or f"{case_sudo.days_in_stage}d in stage"

            is_active_desk = case_sudo.state not in ('enforced', 'closed', 'appealed', 'revoked')

            if is_active_desk:
                briefing_html = (
                    '<div class="alert alert-light border border-warning shadow-sm rounded-3 p-3 my-2" style="border-left: 5px solid #f59e0b !important; background-color: #fffdf5;">'
                    '  <div class="d-flex align-items-center mb-1">'
                    '    <i class="fa fa-bullhorn text-warning fs-5 me-2"></i>'
                    '    <strong class="text-dark" style="font-size: 0.95rem; letter-spacing: 0.5px;">IN-PERSON BRIEFING TALKING POINTS (FOR YOUR BOSS)</strong>'
                    '  </div>'
                    f'  <p class="mb-0 text-dark" style="font-size: 1.02rem; line-height: 1.6;">'
                    f'    "Boss, this case <strong>{case_sudo.name or ""}</strong> concerns employee <strong>{emp_name}</strong> from <strong>{ou_name}</strong>. '
                    f'    It was escalated from <strong>{from_name}</strong> ({from_role}) and is currently on your desk for <strong>{curr_stage_lbl}</strong> '
                    f'    (<strong>{sla_text}</strong>, deadline <strong>{deadline_str}</strong>). '
                    f'    Once you complete your review and endorsement, it will route next to <strong>{next_target}</strong>."'
                    '  </p>'
                    '</div>'
                )
            else:
                briefing_html = (
                    '<div class="alert alert-light border border-success shadow-sm rounded-3 p-3 my-2" style="border-left: 5px solid #10b981 !important; background-color: #f0fdf4;">'
                    '  <div class="d-flex align-items-center mb-1">'
                    '    <i class="fa fa-check-circle text-success fs-5 me-2"></i>'
                    '    <strong class="text-dark" style="font-size: 0.95rem; letter-spacing: 0.5px;">CASE STATUS BRIEFING</strong>'
                    '  </div>'
                    f'  <p class="mb-0 text-dark" style="font-size: 1.02rem; line-height: 1.6;">'
                    f'    "Boss, case <strong>{case_sudo.name or ""}</strong> for employee <strong>{emp_name}</strong> ({ou_name}) has reached <strong>{curr_stage_lbl}</strong>. '
                    f'    Active executive review is complete."'
                    '  </p>'
                    '</div>'
                )
            rec.case_flow_verbal_briefing = briefing_html

            # 5. Visual Horizontal Stepper
            st = case_sudo.state or 'draft'
            if st in ('draft', 'initiated'):
                s1_cls = "border-primary bg-primary-subtle shadow-sm"
                s1_badge = '<span class="badge bg-primary text-white mt-1">Initiating</span>'
                s2_cls = "border bg-light text-muted"
                s2_badge = '<span class="badge bg-light text-muted border mt-1">Next Desk</span>'
                s3_cls = "border bg-light text-muted"
                s3_badge = '<span class="badge bg-light text-muted border mt-1">Pending</span>'
                s4_cls = "border bg-light text-muted"
                s4_badge = '<span class="badge bg-light text-muted border mt-1">Pending</span>'
            elif st in ('director_review', 'submitted_director', 'chief_review', 'submitted_chief', 'investigating', 'under_investigation'):
                s1_cls = "border-success bg-white"
                s1_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Completed</span>'
                s2_cls = "border-warning bg-warning-subtle shadow-sm"
                s2_badge = f'<span class="badge bg-warning text-dark border border-warning fw-bold mt-1"><i class="fa fa-clock-o me-1"></i>Active: {sla_text}</span>'
                s3_cls = "border bg-light text-muted"
                s3_badge = '<span class="badge bg-light text-muted border mt-1">Next Desk</span>'
                s4_cls = "border bg-light text-muted"
                s4_badge = '<span class="badge bg-light text-muted border mt-1">Pending</span>'
            elif st in ('committee_review', 'chairman_review', 'ceo_review', 'pending_approval'):
                s1_cls = "border-success bg-white"
                s1_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Completed</span>'
                s2_cls = "border-success bg-white"
                s2_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Reviewed</span>'
                s3_cls = "border-warning bg-warning-subtle shadow-sm"
                s3_badge = f'<span class="badge bg-warning text-dark border border-warning fw-bold mt-1"><i class="fa fa-gavel me-1"></i>Active: {curr_stage_lbl}</span>'
                s4_cls = "border bg-light text-muted"
                s4_badge = '<span class="badge bg-light text-muted border mt-1">Pending</span>'
            else:
                s1_cls = "border-success bg-white"
                s1_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Completed</span>'
                s2_cls = "border-success bg-white"
                s2_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Completed</span>'
                s3_cls = "border-success bg-white"
                s3_badge = '<span class="badge bg-success-subtle text-success border border-success mt-1"><i class="fa fa-check me-1"></i>Completed</span>'
                s4_cls = "border-success bg-success-subtle shadow-sm"
                s4_badge = f'<span class="badge bg-success text-white mt-1"><i class="fa fa-flag-checkered me-1"></i>{curr_stage_lbl}</span>'

            stepper_html = (
                '<div class="card border-0 shadow-sm bg-white rounded-3 p-3 mb-2">'
                '  <div class="row g-2 align-items-center text-center">'
                '    <!-- Step 1: Originator -->'
                f'    <div class="col-12 col-md">'
                f'      <div class="p-2 rounded {s1_cls}">'
                f'        <div class="small text-muted text-uppercase fw-bold"><i class="fa fa-paper-plane me-1"></i>1. Escalated From</div>'
                f'        <div class="fw-bold text-dark mt-1 text-truncate" title="{from_name}" style="font-size: 0.95rem;">{from_name}</div>'
                f'        <div class="small text-secondary text-truncate" title="{from_role}">{from_role}</div>'
                f'        {s1_badge}'
                '      </div>'
                '    </div>'
                '    <!-- Arrow 1 -->'
                '    <div class="col-12 col-md-auto text-muted d-none d-md-block fs-4">➔</div>'
                '    <!-- Step 2: Current Reviewer / Boss Desk -->'
                f'    <div class="col-12 col-md">'
                f'      <div class="p-2 rounded {s2_cls}">'
                f'        <div class="small text-uppercase fw-bold text-primary"><i class="fa fa-user-circle me-1"></i>2. Current Desk (Boss)</div>'
                f'        <div class="fw-bold text-dark mt-1 text-truncate" title="{curr_name}" style="font-size: 0.95rem;">{curr_name}</div>'
                f'        <div class="small text-secondary text-truncate" title="{curr_stage_lbl}">{curr_stage_lbl}</div>'
                f'        {s2_badge}'
                '      </div>'
                '    </div>'
                '    <!-- Arrow 2 -->'
                '    <div class="col-12 col-md-auto text-muted d-none d-md-block fs-4">➔</div>'
                '    <!-- Step 3: Flows Next To -->'
                f'    <div class="col-12 col-md">'
                f'      <div class="p-2 rounded {s3_cls}">'
                f'        <div class="small text-muted text-uppercase fw-bold"><i class="fa fa-share me-1"></i>3. Flows Next To</div>'
                f'        <div class="fw-bold text-dark mt-1 text-truncate" title="{next_target}" style="font-size: 0.95rem;">{next_target}</div>'
                f'        <div class="small text-secondary text-truncate">Next Governance Review</div>'
                f'        {s3_badge}'
                '      </div>'
                '    </div>'
                '    <!-- Arrow 3 -->'
                '    <div class="col-12 col-md-auto text-muted d-none d-md-block fs-4">➔</div>'
                '    <!-- Step 4: Final Enforcement -->'
                f'    <div class="col-12 col-md">'
                f'      <div class="p-2 rounded {s4_cls}">'
                f'        <div class="small text-muted text-uppercase fw-bold"><i class="fa fa-balance-scale me-1"></i>4. Final Resolution</div>'
                f'        <div class="fw-bold text-dark mt-1 text-truncate" style="font-size: 0.95rem;">HR POMD Enforcement</div>'
                f'        <div class="small text-secondary text-truncate">Statutory Implementation</div>'
                f'        {s4_badge}'
                '      </div>'
                '    </div>'
                '  </div>'
                '</div>'
            )
            rec.case_flow_stepper_html = stepper_html

    escalation_target = fields.Selection([
        ('audit', 'Audit Directorate'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Chief Escalation Target', tracking=True)
    ceo_assignment_notes = fields.Text(string='CEO Assignment Remarks', tracking=True)
    delivery_receipt_date = fields.Date(string='Decision Letter Delivery / Receipt Date', tracking=True)

    appeal_ids = fields.One2many(
        'discipline.appeal', 'case_id', string='Appeals'
    )
    appeal_count = fields.Integer(
        string='Appeal Count', compute='_compute_appeal_stats'
    )
    has_active_appeal = fields.Boolean(
        string='Has Active Appeal', compute='_compute_appeal_stats'
    )
    latest_appeal_id = fields.Many2one(
        'discipline.appeal', string='Latest Appeal', compute='_compute_appeal_stats'
    )
    appeal_outcome_type = fields.Selection([
        ('none', 'No Appeal'),
        ('pending', 'Appeal in Progress'),
        ('exonerated', 'Exonerated on Appeal'),
        ('reduced', 'Penalty Reduced on Appeal'),
        ('upheld', 'Original Decision Upheld'),
    ], string='Appeal Outcome Status', compute='_compute_appeal_outcome', store=True)
    appeal_outcome_display = fields.Text(
        string='Appeal Decision Summary', compute='_compute_appeal_outcome', store=True
    )

    @api.depends('appeal_ids', 'appeal_ids.state', 'appeal_ids.submission_date')
    def _compute_appeal_stats(self):
        for rec in self:
            appeals = rec.appeal_ids.sorted(lambda a: (a.submission_date or fields.Date.today(), a.id or 0), reverse=True)
            rec.appeal_count = len(appeals)
            rec.latest_appeal_id = appeals[0] if appeals else False
            rec.has_active_appeal = any(a.state in ('draft', 'submitted', 'under_review') for a in appeals)

    @api.depends('appeal_ids', 'appeal_ids.state', 'appeal_ids.decision_outcome', 'appeal_ids.revised_punishment_type', 'appeal_ids.revised_penalty_percentage', 'appeal_ids.revised_fine_days', 'appeal_ids.review_date', 'state')
    def _compute_appeal_outcome(self):
        for rec in self:
            appeals = rec.appeal_ids.sorted(lambda a: (a.submission_date or fields.Date.today(), a.id or 0), reverse=True)
            if not appeals:
                rec.appeal_outcome_type = 'none'
                rec.appeal_outcome_display = False
                continue

            has_pending = any(a.state in ('submitted', 'under_review') for a in appeals) and rec.state == 'appealed'
            decided_appeals = appeals.filtered(lambda a: a.state == 'decided')

            if has_pending:
                rec.appeal_outcome_type = 'pending'
                pending_apps = appeals.filtered(lambda a: a.state in ('submitted', 'under_review'))
                if pending_apps:
                    p_app = pending_apps[0]
                    lvl_label = dict(p_app._fields['appeal_level'].selection).get(p_app.appeal_level, p_app.appeal_level)
                    reviewer = p_app.reviewer_id.name or dict(p_app._fields['appeal_target_authority'].selection).get(p_app.appeal_target_authority, 'Designated Authority')
                    rec.appeal_outcome_display = _("A %s level appeal (%s) has been submitted and is currently under active review by %s.") % (lvl_label, p_app.name, reviewer)
                else:
                    rec.appeal_outcome_display = _("An appeal has been submitted and is currently under review.")
            elif decided_appeals:
                last_decision = decided_appeals[0]
                outcome = last_decision.decision_outcome
                rev_punish = last_decision.revised_punishment_type
                reviewer = last_decision.reviewer_id.name or 'Executive Reviewer'
                d_date = last_decision.review_date or last_decision.submission_date or fields.Date.today()

                if outcome == 'overturned' or rev_punish == 'exonerate' or (outcome == 'penalty_reduced' and last_decision.revised_fine_days == 0.0 and last_decision.revised_penalty_percentage == 0.0 and rev_punish in ('exonerate', False)):
                    rec.appeal_outcome_type = 'exonerated'
                    rec.appeal_outcome_display = _(
                        "Fully Exonerated on Appeal by %s on %s. All penalties, records, and active warning durations have been completely voided."
                    ) % (reviewer, d_date)
                elif outcome == 'penalty_reduced':
                    rec.appeal_outcome_type = 'reduced'
                    punish_label = dict(last_decision._fields['revised_punishment_type'].selection).get(rev_punish, rev_punish) if rev_punish else 'Reduced Sanction'
                    rec.appeal_outcome_display = _(
                        "Disciplinary Penalty Reduced on Appeal by %s on %s. Revised Measure: %s (Salary Fine: %s Days, Deduction: %s%%)."
                    ) % (reviewer, d_date, punish_label, last_decision.revised_fine_days, last_decision.revised_penalty_percentage)
                elif outcome == 'upheld':
                    rec.appeal_outcome_type = 'upheld'
                    rec.appeal_outcome_display = _(
                        "Original Disciplinary Decision Upheld on Appeal by %s on %s."
                    ) % (reviewer, d_date)
                else:
                    rec.appeal_outcome_type = 'none'
                    rec.appeal_outcome_display = False
            else:
                rec.appeal_outcome_type = 'none'
                rec.appeal_outcome_display = False

    active_duration_days = fields.Integer(string='Penalty Active Duration (Days)', compute='_compute_active_duration_days', store=True, readonly=True)
    active_penalty_end_date = fields.Date(string='Penalty Active Expiration Date', compute='_compute_active_penalty_end_date', store=True, tracking=True)

    @api.depends('punishment_type', 'decided_punishment_type', 'severity_level_id', 'severity_level_id.active_duration_days', 'offense_id', 'offense_id.custom_warning_validity_months', 'appeal_outcome_type', 'state', 'committee_meeting_ids.recommended_warning_validity_days', 'committee_meeting_ids.state')
    def _compute_active_duration_days(self):
        for rec in self:
            if rec.appeal_outcome_type == 'exonerated' or rec.punishment_type == 'exonerate' or rec.decided_punishment_type == 'exonerate':
                rec.active_duration_days = 0
                continue
            punish = rec.decided_punishment_type or rec.punishment_type or (rec.severity_level_id and rec.severity_level_id.default_punishment_type)
            if hasattr(punish, 'default_punishment_type'):
                punish = punish.default_punishment_type or False
            elif not isinstance(punish, str):
                punish = str(punish) if punish else False

            # Dismissal has NO warning active validity duration (0 days)
            if punish == 'dismissal':
                rec.active_duration_days = 0
                continue

            # Check if committee recommended specific validity days
            completed_meeting = rec.committee_meeting_ids.filtered(lambda m: m.state in ('chair_review', 'completed') and m.recommended_warning_validity_days > 0)
            if completed_meeting:
                rec.active_duration_days = completed_meeting[0].recommended_warning_validity_days
                continue

            if rec.offense_id and rec.offense_id.custom_warning_validity_months and rec.offense_id.custom_warning_validity_months > 0 and rec.offense_id.penalty_mode == 'article_override' and not rec.is_cash_shortage:
                rec.active_duration_days = rec.offense_id.custom_warning_validity_months * 30
            elif punish == 'verbal_warning':
                rec.active_duration_days = 30  # 1 month per Art. 33.10.1.1
            elif punish == 'first_warning_penalty':
                rec.active_duration_days = 90  # 3 months per Art. 33.10.1.2 & 10.3.1
            elif punish == 'second_warning_penalty':
                rec.active_duration_days = 180  # 6 months per Art. 33.10.1.3 & 10.3.2
            elif punish in ('final_warning_penalty', 'demotion'):
                rec.active_duration_days = 365  # 1 year per Art. 33.10.1.4 & 10.3.3
            elif rec.severity_level_id and rec.severity_level_id.active_duration_days:
                rec.active_duration_days = rec.severity_level_id.active_duration_days
            else:
                rec.active_duration_days = 0

    @api.depends('final_decision_date', 'active_duration_days', 'state', 'appeal_outcome_type', 'incident_date', 'create_date', 'punishment_type', 'decided_punishment_type')
    def _compute_active_penalty_end_date(self):
        for rec in self:
            if rec.appeal_outcome_type == 'exonerated' or rec.active_duration_days <= 0 or rec.punishment_type in ('exonerate', 'dismissal') or rec.decided_punishment_type in ('exonerate', 'dismissal'):
                rec.active_penalty_end_date = False
            elif rec.state in ('enforced', 'closed', 'appealed'):
                base_date = rec.final_decision_date or rec.incident_date or (rec.create_date and rec.create_date.date()) or fields.Date.context_today(rec)
                rec.active_penalty_end_date = base_date + timedelta(days=rec.active_duration_days or 365)
            else:
                rec.active_penalty_end_date = False

    is_coach_or_manager = fields.Boolean(string='Is Coach or Line Manager', compute='_compute_is_coach_or_manager')
    is_case_direct_supervisor = fields.Boolean(string='Is Case Direct Supervisor', compute='_compute_is_coach_or_manager')
    is_case_director_user = fields.Boolean(string='Is Case Director User', compute='_compute_is_coach_or_manager')
    is_case_chief_user = fields.Boolean(string='Is Case Chief User', compute='_compute_is_coach_or_manager')
    is_exonerated_case = fields.Boolean(string='Is Exonerated Case', compute='_compute_is_exonerated_case')

    @api.depends('punishment_type', 'decided_punishment_type', 'appeal_outcome_type', 'state', 'fine_days', 'penalty_percentage')
    def _compute_is_exonerated_case(self):
        for rec in self:
            effective_punish = rec.decided_punishment_type or rec.punishment_type
            rec.is_exonerated_case = bool(
                effective_punish == 'exonerate' or
                rec.appeal_outcome_type == 'exonerated' or
                (rec.state == 'closed' and not effective_punish and (rec.fine_days or 0.0) == 0.0 and (rec.penalty_percentage or 0.0) == 0.0)
            )

    @api.depends_context('uid')
    def _compute_is_coach_or_manager(self):
        current_user = self.env.user
        current_emp = current_user.employee_id
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
        for rec in self:
            # 1. Contextual Direct Supervisor check (strict hierarchy)
            is_direct_sub = False
            emp_sudo = rec.employee_id.sudo() if rec.employee_id else False
            rep_sudo = rec.reported_by_id.sudo() if rec.reported_by_id else False
            if current_emp and emp_sudo:
                is_direct_sub = bool(
                    emp_sudo.coach_id.id == current_emp.id or
                    emp_sudo.parent_id.id == current_emp.id or
                    (emp_sudo.department_id and emp_sudo.department_id.manager_id and emp_sudo.department_id.manager_id.id == current_emp.id) or
                    (rep_sudo and rep_sudo.id == current_emp.id)
                )
            rec.is_case_direct_supervisor = is_direct_sub or bool(rec.create_uid and rec.create_uid.id == current_user.id) or is_admin
            rec.is_coach_or_manager = rec.is_case_direct_supervisor

            # 2. Contextual Directorate Director check
            is_dir = bool(rec.director_id and rec.director_id.id == current_user.id)
            if not is_dir and current_emp and emp_sudo:
                dept = emp_sudo.department_id
                if dept and dept.parent_id and dept.parent_id.manager_id and dept.parent_id.manager_id.id == current_emp.id:
                    is_dir = True
            rec.is_case_director_user = is_dir or is_admin

            # 3. Contextual Chief Officer check
            rec.is_case_chief_user = bool(rec.chief_id and rec.chief_id.id == current_user.id) or is_admin

    is_coach_enforce_allowed = fields.Boolean(
        string='Is Coach Enforcement Allowed',
        compute='_compute_is_coach_enforce_allowed'
    )
    can_user_sign_notice = fields.Boolean(
        string='Can Current User Sign Notice',
        compute='_compute_can_user_sign_notice'
    )

    @api.depends_context('uid')
    @api.depends('state', 'case_action_track', 'initiator_id', 'reported_by_id', 'employee_id',
                 'is_case_direct_supervisor', 'is_cpco_user', 'is_ceo_user', 'is_hr_admin',
                 'is_exonerated_case', 'signatory_signature', 'appeal_ids.state', 'appeal_ids.designated_reviewer_id')
    def _compute_can_user_sign_notice(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        ceo_user = EmpModel.get_ceo_user()
        sec_user = EmpModel.get_secretary_user()

        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user._is_superuser()
        is_ceo = bool((ceo_user and current_user.id == ceo_user.id) or current_user.has_group('discipline_management.group_discipline_ceo'))
        is_cpco = bool((cpco_user and current_user.id == cpco_user.id) or current_user.has_group('discipline_management.group_discipline_cpco'))
        is_pomd = bool((sec_user and current_user.id == sec_user.id) or current_user.has_group('discipline_management.group_discipline_pomd_director') or current_user.has_group('discipline_management.group_discipline_pomd'))
        is_general_appeal_authority = is_admin or is_ceo or is_cpco or is_pomd

        for rec in self:
            # If exonerated, neither warning notice nor signature configuration is relevant
            if rec.is_exonerated_case:
                rec.can_user_sign_notice = False
                continue

            # 1. During Active Appeal Process:
            # Visible ONLY in readonly/audit mode to designated appeal authorities
            has_active_appeal = rec.state == 'appealed' or any(a.state in ('draft', 'submitted', 'under_review') for a in rec.appeal_ids)
            if has_active_appeal:
                is_designated_reviewer = any(
                    a.designated_reviewer_id and a.designated_reviewer_id.id == current_user.id
                    for a in rec.appeal_ids if a.state in ('draft', 'submitted', 'under_review')
                )
                rec.can_user_sign_notice = bool(rec.signatory_signature and (is_general_appeal_authority or is_designated_reviewer))
                continue

            # 2. Post-Enforcement (enforced, closed, revoked):
            # The notice has already been finalized into the official PDF memo.
            # In regular operation, this section is completely invisible for ALL users (including signatory & subject).
            if rec.state in ('enforced', 'closed', 'appealed', 'revoked'):
                rec.can_user_sign_notice = False
                continue

            # 3. Pre-Enforcement:
            # Track A: Direct Enforcement (Manager initiates and enforces)
            if rec.case_action_track == 'direct_enforce':
                is_manager = bool(
                    rec.is_case_direct_supervisor or
                    (rec.initiator_id and rec.initiator_id.id == current_user.id) or
                    (rec.reported_by_id and rec.reported_by_id.user_id and rec.reported_by_id.user_id.id == current_user.id) or
                    is_admin
                )
                rec.can_user_sign_notice = is_manager and rec.state in ('draft', 'initiated')

            # Track B: Committee Escalation (CPCO or CEO enforces at pending_approval)
            elif rec.case_action_track == 'committee_escalation':
                is_exec_enforcing_auth = bool(is_cpco or is_ceo or is_admin)
                rec.can_user_sign_notice = is_exec_enforcing_auth and rec.state == 'pending_approval'

            else:
                rec.can_user_sign_notice = False

    @api.depends('case_action_track', 'severity_level_id', 'offense_id', 'punishment_type', 'decided_punishment_type')
    def _compute_is_coach_enforce_allowed(self):
        cfg_punish, max_rank, allowed_levels = self._get_coach_max_authority()
        punish_ranks = {
            'verbal_warning': 1,
            'first_warning_penalty': 2,
            'second_warning_penalty': 3,
            'final_warning_penalty': 4,
            'demotion': 5,
            'dismissal': 6,
        }
        sev_ranks = {
            'level_5': 1,
            'level_4': 2,
            'level_3': 3,
            'level_2': 4,
            'level_1': 6,
        }
        for rec in self:
            if rec.case_action_track != 'direct_enforce' or (not rec.offense_id and not rec.severity_level_id):
                rec.is_coach_enforce_allowed = True
                continue
            punish = rec.punishment_type or rec.decided_punishment_type
            if punish == 'fine':
                days = rec.decided_fine_days or rec.fine_days or 0.0
                if days > 3.0:
                    case_punish_rank = 5
                elif days > 2.0:
                    case_punish_rank = 4
                elif days > 1.0:
                    case_punish_rank = 3
                else:
                    case_punish_rank = 2
            else:
                case_punish_rank = punish_ranks.get(punish, 1)
            case_sev_rank = sev_ranks.get(rec.severity_level or (rec.severity_level_id and rec.severity_level_id.code), 1)
            rec.is_coach_enforce_allowed = (case_punish_rank <= max_rank) and (case_sev_rank <= max_rank)

    allowed_severity_level_ids = fields.Many2many(
        'discipline.severity.level',
        compute='_compute_allowed_severity_level_ids',
        string='Allowed Severity Levels'
    )

    allowed_article_ids = fields.Many2many(
        'discipline.article',
        compute='_compute_allowed_article_ids',
        string='Allowed Articles'
    )

    @api.depends('staff_category', 'employee_id', 'case_action_track')
    @api.depends_context('uid')
    def _compute_allowed_article_ids(self):
        cfg_punish, max_rank, allowed_levels_codes = self._get_coach_max_authority()
        for rec in self:
            cat = rec.staff_category or (
                rec.employee_id and ('managerial' if rec._is_employee_managerial(rec.employee_id.sudo()) else 'non_managerial')
            )
            domain = [('staff_category', 'in', [cat, 'all'])] if cat else []
            all_articles = self.env['discipline.article'].search(domain)
            is_direct = (rec.case_action_track == 'direct_enforce')
            if is_direct:
                rec.allowed_article_ids = all_articles.filtered(
                    lambda a: not a.severity_level_id or a.severity_level_id.code in allowed_levels_codes
                )
            else:
                rec.allowed_article_ids = all_articles

    allowed_offense_ids = fields.Many2many(
        'discipline.offense',
        compute='_compute_allowed_offense_ids',
        string='Allowed Offenses'
    )

    @api.depends('staff_category', 'employee_id', 'case_action_track', 'article_id')
    @api.depends_context('uid')
    def _compute_allowed_offense_ids(self):
        cfg_punish, max_rank, allowed_levels_codes = self._get_coach_max_authority()
        can_dismiss = 'level_1' in allowed_levels_codes or cfg_punish == 'dismissal'
        for rec in self:
            cat = rec.staff_category or (
                rec.employee_id and ('managerial' if rec._is_employee_managerial(rec.employee_id.sudo()) else 'non_managerial')
            )
            domain = [('staff_category', 'in', [cat, 'all'])] if cat else []
            if rec.article_id:
                domain.append(('article_id', '=', rec.article_id.id))
            all_offenses = self.env['discipline.offense'].search(domain)

            is_direct = (rec.case_action_track == 'direct_enforce')
            if is_direct:
                filtered_offenses = all_offenses.filtered(
                    lambda o: (
                        (o.severity_level in allowed_levels_codes or
                         (o.severity_level_id and o.severity_level_id.code in allowed_levels_codes) or
                         (not o.severity_level and (can_dismiss or (o.custom_punishment_type or o.punishment_type) != 'dismissal')))
                        and (can_dismiss or (o.custom_punishment_type or o.punishment_type) != 'dismissal')
                    )
                )
                rec.allowed_offense_ids = filtered_offenses
            else:
                rec.allowed_offense_ids = all_offenses

    subordinate_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_subordinate_employee_ids',
        string='Subordinate Employees'
    )

    @api.model
    def _get_accessible_case_employee_ids(self):
        """Deprecated: discipline access is self-contained and does not alter hr.employee access rules."""
        return []

    @api.depends_context('uid')
    def _compute_subordinate_employee_ids(self):
        user = self.env.user
        emp = user.sudo().employee_id
        is_privileged = (
            user.has_group('hr.group_hr_user') or
            user.has_group('hr.group_hr_manager') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system') or
            user._is_admin()
        )
        for rec in self:
            if rec.state != 'draft' or is_privileged or not emp:
                rec.subordinate_employee_ids = self.env['hr.employee']
            else:
                visible_ids = set()
                if hasattr(self.env['hr.employee'], '_get_delegation_visible_employee_ids'):
                    try:
                        visible_ids.update(self.env['hr.employee'].with_user(user)._get_delegation_visible_employee_ids())
                    except Exception:
                        pass
                child_subs = self.env['hr.employee'].search([
                    '|', ('parent_id', '=', emp.id),
                    ('coach_id', '=', emp.id)
                ])
                visible_ids.update(child_subs.ids)
                rec.subordinate_employee_ids = self.env['hr.employee'].browse(list(visible_ids))

    @api.depends('offense_id', 'offense_id.line_ids', 'case_action_track')
    def _compute_allowed_severity_level_ids(self):
        all_levels = self.env['discipline.severity.level'].search([])
        cfg_p, max_rank, allowed_levels_codes = self._get_coach_max_authority()
        for rec in self:
            if rec.case_action_track == 'direct_enforce':
                levels = all_levels.filtered(lambda l: l.code in allowed_levels_codes)
                if rec.offense_id and rec.offense_id.line_ids:
                    rec.allowed_severity_level_ids = rec.offense_id.line_ids.mapped('severity_level_id').filtered(lambda l: l.code in allowed_levels_codes)
                else:
                    rec.allowed_severity_level_ids = levels
            else:
                if rec.offense_id and rec.offense_id.line_ids:
                    rec.allowed_severity_level_ids = rec.offense_id.line_ids.mapped('severity_level_id')
                else:
                    rec.allowed_severity_level_ids = all_levels

    # Demotion fields
    is_demotion_decided = fields.Boolean(
        string='Demotion Sanction Included',
        default=False,
        tracking=True,
        help='When enabled, demotion is applied alongside the primary warning sanction. A draft Employee Demotion record is created in Employee Service for HR placement.'
    )
    demotion_id = fields.Many2one('employee.demotion', string='Employee Demotion Record', readonly=True, copy=False, tracking=True)
    new_job_id = fields.Many2one('hr.job', string='Demotion Target Job Position (Legacy)', tracking=True)
    previous_job_id = fields.Many2one('hr.job', string='Pre-Demotion Job Position', tracking=True)
    new_grade_id = fields.Char(string='Demotion Target Grade Scale', tracking=True)

    def action_view_demotion(self):
        self.ensure_one()
        if not self.demotion_id:
            raise UserError(_("No Employee Demotion record has been generated for this case."))
        return {
            'name': _('Employee Demotion — %s') % (self.demotion_id.ref_num or self.employee_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.demotion',
            'res_id': self.demotion_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # Automatic routing & authority
    required_final_authority = fields.Selection([
        ('direct_manager', 'Coach / Line Manager'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Final Approval Authority', compute='_compute_required_final_authority', store=True, tracking=True)

    incident_date = fields.Date(string='Incident Date', required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(string='Detailed Description of Misconduct', required=False)
    is_system_generated = fields.Boolean(string='System Generated', default=False, readonly=True)
    is_attendance_case = fields.Boolean(
        string='Is Attendance Case',
        default=False,
        index=True,
        tracking=True,
        help='Indicates whether this disciplinary case was automatically generated from biometric attendance and timekeeping.'
    )
    attendance_violation_type = fields.Selection([
        ('late', 'Cumulative Late Arrival'),
        ('absence_minor', 'Unexcused Absence (1–2 Days)'),
        ('absence_prolonged', 'Prolonged Unexcused Absence (3–4 Consecutive Days)'),
        ('absence_dismissal', 'Dismissal Absence (≥ 5 Consecutive Working Days)'),
        ('force_checkout', 'Force Check-Out Violation'),
    ], string='Attendance Breach Type', tracking=True)
    absent_days_count = fields.Integer(string='Total Unexcused Absent Days', default=0, tracking=True)
    max_consecutive_days = fields.Integer(string='Max Consecutive Absent Days', default=0, tracking=True)
    late_minutes_total = fields.Float(string='Cumulative Late Time (Minutes)', default=0.0, tracking=True)
    late_occurrences_count = fields.Integer(string='Late Check-In Count', default=0)
    force_checkout_count = fields.Integer(string='Force Check-Out Count', default=0)
    absent_dates_summary = fields.Char(string='Unexcused Absent Dates', tracking=True)
    is_shift_worker = fields.Boolean(string='Shift / Roster Worker', default=False)
    shift_schedule_summary = fields.Char(string='Applied Working Schedule')
    attendance_date_from = fields.Date(string='Attendance Evaluation From')
    attendance_date_to = fields.Date(string='Attendance Evaluation To')
    leave_id = fields.Many2one('hr.leave', string='Covering Time Off / Leave Record', tracking=True)
    covered_leave_days = fields.Float(string='Days Covered by Leave', default=0.0, tracking=True)
    attendance_justification_reason = fields.Text(string='Attendance Justification / Leave Notes', tracking=True)
    is_locked_for_committee = fields.Boolean(string='Locked for Committee Review', default=False, tracking=True)

    # Workflow Roles (Segregation of Duties)
    initiator_id = fields.Many2one('res.users', string='Initiator', default=lambda self: self.env.user, readonly=True, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer / Investigator', tracking=True)
    approver_id = fields.Many2one('res.users', string='Final Approver', tracking=True)

    def _default_reported_by_id(self):
        return self.env.user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)

    reported_by_id = fields.Many2one(
        'hr.employee', 
        string='Reported By', 
        default=_default_reported_by_id,
        readonly=True
    )
    
    reference = fields.Char(string='Reference')
    active = fields.Boolean(string='Active', default=True, tracking=True)
    chief_review_notes = fields.Text(string='Executive Remark', tracking=True)
    # State Machine
    state = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated'),
        ('submitted_director', 'Director Review'),
        ('submitted_chief', 'Executive Review'),
        ('ceo_review', 'CEO Review'),
        ('investigating', 'Investigation'),
        ('chairman_review', 'Committee Routing'),
        ('committee_review', 'Hearing'),
        ('pending_approval', 'Final Approval'),
        ('enforced', 'Enforced'),
        ('appealed', 'Appealed'),
        ('revoked', 'Revoked'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', required=True, tracking=True)

    def _default_sla_target_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        val = ICP.get_param('discipline.sla_target_days') or ICP.get_param('discipline_management.sla_target_days')
        try:
            return int(val) if val else 10
        except (ValueError, TypeError):
            return 10

    # SLA Tracking
    sla_deadline = fields.Date(string='SLA Resolution Deadline', compute='_compute_sla_deadline', store=True)
    is_sla_exceeded = fields.Boolean(string='SLA Breached', compute='_compute_is_sla_exceeded', store=True, tracking=True)
    sla_target_days = fields.Integer(string='SLA Target (Days)', default=_default_sla_target_days, readonly=True, help='Target resolution days per policy')

    # Associated Records
    investigation_ids = fields.One2many('discipline.investigation', 'case_id', string='Investigations')
    committee_meeting_ids = fields.One2many('discipline.committee.meeting', 'case_id', string='Committee Meetings')
    suspension_ids = fields.One2many('discipline.suspension', 'case_id', string='Suspensions')
    payroll_penalty_ids = fields.One2many('discipline.payroll.penalty', 'case_id', string='Payroll Penalties')
    deduction_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('appeal_pending', 'Pending Appeal Window Expiry'),
        ('scheduled', 'Scheduled for Payroll'),
        ('transferred', 'Transmitted to Payroll'),
        ('deducted', 'Deducted in Payslip'),
        ('refund_pending_acceptance', 'Reimbursement Pending Acceptance'),
        ('refund_scheduled', 'Reimbursement Scheduled (Next Payroll)'),
        ('refunded', 'Reimbursed in Payslip'),
        ('cancelled', 'Cancelled / Waived on Appeal'),
    ], string='Financial Deduction Status', default='not_applicable', tracking=True)
    computed_deduction_month = fields.Char(string='Target Payroll Month (Computed)', readonly=True)

    # Flags & Decision Summary
    has_exonerated_investigation = fields.Boolean(
        string='Has Exonerated Investigation',
        compute='_compute_has_exonerated_investigation'
    )
    has_completed_investigation = fields.Boolean(
        string='Has Completed Investigation',
        compute='_compute_has_completed_investigation'
    )

    @api.depends('investigation_ids.state', 'investigation_ids.finding_outcome')
    def _compute_has_exonerated_investigation(self):
        for rec in self:
            rec.has_exonerated_investigation = any(
                inv.state in ('submitted', 'submitted_ceo', 'forwarded_cpco', 'approved') and inv.finding_outcome == 'exonerated'
                for inv in rec.investigation_ids.sudo()
            )

    @api.depends('investigation_ids', 'investigation_ids.state')
    def _compute_has_completed_investigation(self):
        for rec in self:
            rec.has_completed_investigation = any(
                inv.state in ('approved', 'submitted', 'submitted_ceo', 'forwarded_cpco')
                for inv in rec.investigation_ids.sudo()
            )

    final_decision_date = fields.Date(string='Final Decision Date', readonly=True, tracking=True)
    decision_summary = fields.Text(string='Final Decision Summary', tracking=True)
    appeal_deadline = fields.Date(string='Appeal Deadline', compute='_compute_appeal_deadline', store=True, tracking=True)
    is_appeal_window_open = fields.Boolean(string='Appeal Window Open', compute='_compute_is_appeal_window_open')
    
    # Revocation Data
    is_revoked = fields.Boolean(string='Is Revoked', default=False, readonly=True, tracking=True)
    revocation_reason = fields.Text(string='Revocation Justification', readonly=True, tracking=True)
    revoked_by_id = fields.Many2one('res.users', string='Revoked By', readonly=True, tracking=True)
    revocation_date = fields.Date(string='Revocation Date', readonly=True, tracking=True)

    # CEO/CPCO authority split — stores who authorised the dismissal
    dismissal_authority_id = fields.Many2one(
        'res.users',
        string='Dismissal Authority (CEO/CPCO)',
        tracking=True,
        help='For Level 1 Dismissals and executive cases, records the CEO or CPCO who provided final authority.'
    )

    # Computed counts for smart buttons
    suspension_count = fields.Integer(string='Suspension Count', compute='_compute_related_record_counts')
    investigation_count = fields.Integer(string='Investigation Count', compute='_compute_related_record_counts')
    committee_meeting_count = fields.Integer(string='Meeting Count', compute='_compute_related_record_counts')

    has_completed_committee_meeting = fields.Boolean(
        string='Has Completed Committee Meeting',
        compute='_compute_committee_meeting_state',
        store=True
    )
    has_active_committee_meeting = fields.Boolean(
        string='Has Active Committee Meeting',
        compute='_compute_committee_meeting_state',
        store=True
    )
    active_committee_meeting_state = fields.Selection([
        ('draft', 'Draft / Setup'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Session'),
        ('chair_review', 'Chair Review'),
        ('submitted_to_ceo', 'Submitted to CEO'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Active Committee Meeting Stage', compute='_compute_committee_meeting_state', store=True)

    # Stage-Gated Confidentiality Visibility Flags
    can_user_see_investigations = fields.Boolean(
        string='Can Current User See Audit Investigations',
        compute='_compute_confidentiality_visibility'
    )
    can_user_see_committee_meetings = fields.Boolean(
        string='Can Current User See Committee Meetings',
        compute='_compute_confidentiality_visibility'
    )
    can_user_see_committee_verdict = fields.Boolean(
        string='Can Current User See Committee Verdict',
        compute='_compute_confidentiality_visibility'
    )

    @api.depends(
        'state',
        'employee_id',
        'investigation_ids.state',
        'committee_meeting_ids.state',
        'committee_meeting_ids.member_ids',
        'committee_meeting_ids.committee_chair_id',
        'committee_meeting_ids.pomd_secretary_id',
        'committee_meeting_ids.legal_director_id',
        'committee_meeting_ids.respective_director_id',
        'committee_meeting_ids.labour_union_rep_id',
    )
    @api.depends_context('uid')
    def _compute_confidentiality_visibility(self):
        current_user = self.env.user
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user._is_superuser()
        is_auditor = current_user.has_group('discipline_management.group_discipline_auditor')
        is_ceo = current_user.has_group('discipline_management.group_discipline_ceo')
        is_cpco = current_user.has_group('discipline_management.group_discipline_cpco')
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd')
        is_legal = current_user.has_group('discipline_management.group_discipline_legal')

        for rec in self:
            is_subject_employee = bool(rec.employee_id and rec.employee_id.sudo().user_id == current_user)
            invs = rec.investigation_ids.sudo()
            meetings = rec.committee_meeting_ids.sudo()

            panel_user_ids = set()
            for m in meetings:
                panel_user_ids.update(m.member_ids.ids)
                for role_u in (m.committee_chair_id, m.pomd_secretary_id, m.legal_director_id, m.respective_director_id, m.labour_union_rep_id):
                    if role_u:
                        panel_user_ids.add(role_u.id)
            is_panel_member = current_user.id in panel_user_ids

            # 1. Audit Investigation Confidentiality (Auditor -> CEO -> CPCO -> POMD/Committee; NEVER Subject Employee or non-panel Line Manager)
            if is_admin or is_auditor:
                rec.can_user_see_investigations = True
            elif is_subject_employee:
                rec.can_user_see_investigations = False
            elif is_ceo or rec.is_ceo_user:
                rec.can_user_see_investigations = any(inv.state in ('submitted_ceo', 'forwarded_cpco', 'approved') for inv in invs)
            elif is_cpco or rec.is_cpco_user:
                rec.can_user_see_investigations = any(inv.state in ('forwarded_cpco', 'approved') for inv in invs)
            elif is_pomd or is_legal or is_panel_member:
                rec.can_user_see_investigations = any(inv.state == 'approved' for inv in invs) or rec.state in ('committee_review', 'pending_approval', 'enforced', 'closed', 'appealed')
            else:
                rec.can_user_see_investigations = False

            # 2. Committee Meeting Deliberations Confidentiality (Hidden from Subject Employee & non-panel Managers)
            if is_admin:
                rec.can_user_see_committee_meetings = True
            elif is_subject_employee:
                rec.can_user_see_committee_meetings = False
            elif is_ceo or rec.is_ceo_user or is_cpco or rec.is_cpco_user or is_pomd or is_legal or is_auditor or is_panel_member:
                rec.can_user_see_committee_meetings = True
            else:
                rec.can_user_see_committee_meetings = False

            # 3. Committee Recommended Verdict Confidentiality (Hidden before CEO Enforcement from Subject Employee & non-panel Managers)
            if rec.state in ('enforced', 'closed', 'appealed'):
                rec.can_user_see_committee_verdict = True
            elif is_admin:
                rec.can_user_see_committee_verdict = True
            elif is_subject_employee:
                rec.can_user_see_committee_verdict = False
            elif is_ceo or rec.is_ceo_user or is_cpco or rec.is_cpco_user or is_pomd or is_legal or is_panel_member:
                rec.can_user_see_committee_verdict = True
            else:
                rec.can_user_see_committee_verdict = False

    @api.depends('committee_meeting_ids', 'committee_meeting_ids.state')
    def _compute_committee_meeting_state(self):
        for rec in self:
            meetings = rec.committee_meeting_ids.sudo()
            completed = meetings.filtered(lambda m: m.state == 'completed')
            # Active notified committee meeting: must be scheduled by POMD or in session/chair review (not draft)
            active = meetings.filtered(lambda m: m.state in ('scheduled', 'in_progress', 'chair_review', 'submitted_to_ceo'))
            rec.has_completed_committee_meeting = bool(completed)
            rec.has_active_committee_meeting = bool(active)
            active_m = active[:1]
            rec.active_committee_meeting_state = active_m.state if active_m else False

    @api.depends('severity_level', 'punishment_type', 'case_action_track')
    def _compute_required_final_authority(self):
        for rec in self:
            rec.required_final_authority = 'ceo'

    @api.depends('suspension_ids', 'investigation_ids', 'committee_meeting_ids')
    def _compute_related_record_counts(self):
        for rec in self:
            rec.suspension_count = len(rec.suspension_ids)
            rec.investigation_count = len(rec.investigation_ids)
            rec.committee_meeting_count = len(rec.committee_meeting_ids)

    @api.depends('create_date', 'incident_date', 'sla_target_days')
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.create_date:
                base_date = rec.create_date.date()
            elif rec.incident_date:
                base_date = rec.incident_date
            else:
                base_date = fields.Date.context_today(self)
            rec.sla_deadline = base_date + timedelta(days=rec.sla_target_days or 10)

    @api.depends('sla_deadline', 'state')
    def _compute_is_sla_exceeded(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state not in ['enforced', 'closed', 'revoked'] and rec.sla_deadline and today > rec.sla_deadline:
                rec.is_sla_exceeded = True
            else:
                rec.is_sla_exceeded = False

    def _get_case_origin_type(self):
        """Determine origin hierarchy for appeal escalation."""
        self.ensure_one()
        if (
            self.initiator_type == 'audit' or
            self.case_action_track == 'committee_escalation' or
            getattr(self, 'has_completed_committee_meeting', False) or
            bool(self.committee_meeting_ids)
        ):
            return 'committee'
        initiator_emp = self.reported_by_id.sudo() if self.reported_by_id else (self.env.user.employee_id.sudo() if self.env.user.employee_id else False)
        if not initiator_emp and self.employee_id:
            initiator_emp = self.employee_id.sudo().coach_id or self.employee_id.sudo().parent_id
        level = getattr(initiator_emp, 'executive_level', False) if initiator_emp else False
        if not level and initiator_emp:
            job_name = (initiator_emp.job_id.sudo().name or '').lower() if initiator_emp.job_id else ''
            if any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                level = 'chief'
            elif any(k in job_name for k in ['director', 'directorate']):
                level = 'director'
            else:
                level = 'manager'
        if level == 'chief':
            return 'chief'
        elif level == 'director':
            return 'director'
        return 'manager'

    @api.model
    def _add_working_days(self, start_date, num_days):
        """Adds business working days (Monday-Friday) to start_date."""
        if not start_date or num_days <= 0:
            return start_date
        current = start_date
        added = 0
        while added < num_days:
            current += timedelta(days=1)
            if current.weekday() < 5:  # Monday to Friday
                added += 1
        return current

    def get_appeal_window_days(self):
        """Returns the configured appeal submission window in working days."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        val = ICP.get_param('discipline_management.appeal_window_days') or ICP.get_param('discipline.appeal_window_days')
        try:
            days = int(val) if val else 5
            return days if days > 0 else 5
        except (ValueError, TypeError):
            return 5

    def get_effective_appeal_deadline(self):
        """Dynamically computes the effective appeal deadline using the currently configured appeal window days."""
        self.ensure_one()
        appeal_days = self.get_appeal_window_days()
        first_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
        second_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
        origin_type = self._get_case_origin_type()

        if not first_appeal:
            base_date = self.final_decision_date or self.delivery_receipt_date or (self.write_date.date() if self.write_date else fields.Date.today())
            return self._add_working_days(base_date, appeal_days) if base_date else False
        elif first_appeal and not second_appeal:
            if origin_type in ('committee', 'chief'):
                return False
            f_app = first_appeal[0]
            if f_app.state == 'decided' and f_app.decision_outcome in ('upheld', 'penalty_reduced'):
                base_date = f_app.review_date or f_app.submission_date or self.final_decision_date
                return self._add_working_days(base_date, appeal_days) if base_date else False
            return False
        return self.appeal_deadline or self._add_working_days(self.final_decision_date or fields.Date.today(), appeal_days)

    @api.depends('delivery_receipt_date', 'final_decision_date', 'state', 'appeal_ids', 'appeal_ids.state', 'appeal_ids.appeal_level', 'appeal_ids.review_date', 'appeal_ids.submission_date', 'appeal_ids.decision_outcome', 'appeal_outcome_type', 'initiator_type', 'case_action_track', 'committee_meeting_ids')
    def _compute_appeal_deadline(self):
        ICP = self.env['ir.config_parameter'].sudo()
        val = ICP.get_param('discipline_management.appeal_window_days') or ICP.get_param('discipline.appeal_window_days')
        try:
            appeal_days = int(val) if val else 5
        except (ValueError, TypeError):
            appeal_days = 5
        if appeal_days <= 0:
            appeal_days = 5
        for rec in self:
            if rec.state not in ('enforced', 'appealed', 'closed') or rec.appeal_outcome_type == 'exonerated':
                rec.appeal_deadline = False
                continue

            origin_type = rec._get_case_origin_type()
            first_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
            second_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
            third_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'third')

            # 1. No appeal filed yet -> deadline based on initial decision
            if not first_appeal:
                base_date = rec.final_decision_date or rec.delivery_receipt_date
                rec.appeal_deadline = rec._add_working_days(base_date, appeal_days) if base_date else False

            # 2. First appeal exists
            elif first_appeal and not second_appeal:
                # If committee or chief case: 1st appeal was directly to CEO and is final. No further appeal window.
                if origin_type in ('committee', 'chief'):
                    rec.appeal_deadline = False
                else:
                    # Manager / Director track: 2nd level window from 1st appeal decision
                    f_app = first_appeal[0]
                    if f_app.state == 'decided' and f_app.decision_outcome in ('upheld', 'penalty_reduced'):
                        base_date = f_app.review_date or f_app.submission_date or rec.final_decision_date
                        rec.appeal_deadline = rec._add_working_days(base_date, appeal_days) if base_date else False
                    else:
                        rec.appeal_deadline = False

            # 3. Second appeal exists
            elif second_appeal and not third_appeal:
                # If director case: 2nd appeal was to CEO and is final. No further appeal window.
                if origin_type in ('committee', 'chief', 'director'):
                    rec.appeal_deadline = False
                else:
                    # Manager track: 3rd level window from 2nd appeal decision
                    s_app = second_appeal[0]
                    if s_app.state == 'decided' and s_app.decision_outcome in ('upheld', 'penalty_reduced'):
                        base_date = s_app.review_date or s_app.submission_date or rec.final_decision_date
                        rec.appeal_deadline = rec._add_working_days(base_date, appeal_days) if base_date else False
                    else:
                        rec.appeal_deadline = False

            # 4. Third appeal exists or all appeals exhausted
            else:
                rec.appeal_deadline = False

    @api.depends('appeal_deadline', 'state', 'appeal_outcome_type', 'appeal_ids', 'appeal_ids.state', 'appeal_ids.acceptance_state')
    def _compute_is_appeal_window_open(self):
        today = fields.Date.context_today(self)
        for rec in self:
            has_pending = any(a.state in ('draft', 'submitted', 'under_review') for a in rec.appeal_ids)
            has_accepted = any(a.acceptance_state in ('accepted', 'window_closed') for a in rec.appeal_ids)
            if (
                rec.state == 'enforced' and
                rec.appeal_deadline and
                today <= rec.appeal_deadline and
                not has_pending and
                not has_accepted and
                rec.appeal_outcome_type != 'exonerated'
            ):
                rec.is_appeal_window_open = True
            else:
                rec.is_appeal_window_open = False

    is_hr_admin = fields.Boolean(compute='_compute_is_hr_admin', string='Is HR Admin User')

    @api.depends_context('uid')
    def _compute_is_hr_admin(self):
        is_admin = self.env.user.has_group('discipline_management.group_discipline_admin') or self.env.user.has_group('base.group_system')
        for rec in self:
            rec.is_hr_admin = is_admin

    is_current_user_employee = fields.Boolean(
        string='Is Current User Subject Employee',
        compute='_compute_current_user_roles'
    )
    can_accept_appeal_decision_on_case = fields.Boolean(
        string='Can Accept Appeal Decision',
        compute='_compute_current_user_roles'
    )
    can_submit_appeal = fields.Boolean(
        string='Can Submit Appeal',
        compute='_compute_current_user_roles'
    )
    can_submit_first_appeal = fields.Boolean(
        string='Can Submit 1st Level Appeal',
        compute='_compute_current_user_roles'
    )
    can_submit_second_appeal = fields.Boolean(
        string='Can Submit 2nd Level Appeal',
        compute='_compute_current_user_roles'
    )
    can_submit_third_appeal = fields.Boolean(
        string='Can Submit 3rd Level Appeal',
        compute='_compute_current_user_roles'
    )
    can_submit_fourth_appeal = fields.Boolean(
        string='Can Submit 4th Level Appeal',
        compute='_compute_current_user_roles'
    )
    can_lodge_appeal_on_behalf = fields.Boolean(
        string='Can Lodge Appeal On Behalf',
        compute='_compute_current_user_roles'
    )
    can_lodge_first_appeal_on_behalf = fields.Boolean(
        string='Can Lodge 1st Level Appeal (On Behalf)',
        compute='_compute_current_user_roles'
    )
    can_lodge_second_appeal_on_behalf = fields.Boolean(
        string='Can Lodge 2nd Level Appeal (On Behalf)',
        compute='_compute_current_user_roles'
    )
    can_lodge_third_appeal_on_behalf = fields.Boolean(
        string='Can Lodge 3rd Level Appeal (On Behalf)',
        compute='_compute_current_user_roles'
    )
    can_lodge_fourth_appeal_on_behalf = fields.Boolean(
        string='Can Lodge 4th Level Appeal (On Behalf)',
        compute='_compute_current_user_roles'
    )
    next_appeal_level = fields.Selection([
        ('first', '1st Level Appeal'),
        ('second', '2nd Level Appeal'),
        ('third', '3rd Level Appeal'),
        ('fourth', '4th Level Appeal (Final to CEO)'),
    ], string='Next Eligible Appeal Stage', compute='_compute_current_user_roles')
    is_pomd_user = fields.Boolean(
        string='Is POMD User',
        compute='_compute_current_user_roles'
    )
    is_auditor_user = fields.Boolean(
        string='Is Auditor User',
        compute='_compute_current_user_roles'
    )
    is_director_user = fields.Boolean(
        string='Is Director User',
        compute='_compute_current_user_roles'
    )
    is_chief_user = fields.Boolean(
        string='Is Chief User',
        compute='_compute_current_user_roles'
    )
    is_ceo_user = fields.Boolean(
        string='Is CEO User',
        compute='_compute_current_user_roles'
    )
    is_cpco_user = fields.Boolean(
        string='Is CPCO User',
        compute='_compute_current_user_roles'
    )
    is_discipline_secretary = fields.Boolean(
        string='Is Discipline Secretary / Follow-up Assistant',
        compute='_compute_current_user_roles'
    )
    is_discipline_secretary_only = fields.Boolean(
        string='Is Secretary Only (Restricted to Flow & Deadlines)',
        compute='_compute_current_user_roles'
    )

    @api.depends_context('uid')
    def _compute_current_user_roles(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee']
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        audit_user = EmpModel.get_audit_director_user()
        ceo_user = EmpModel.get_ceo_user()
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
        emp = current_user.sudo().employee_id
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''

        # 1. CEO User
        is_ceo = bool(
            (ceo_user and current_user.id == ceo_user.id) or
            current_user.has_group('discipline_management.group_discipline_ceo') or
            is_admin
        )

        # 2. CPCO / Committee Chairman User
        is_cpco = bool(
            (cpco_user and current_user.id == cpco_user.id) or
            (current_user.has_group('discipline_management.group_discipline_cpco') and not is_ceo) or
            is_admin
        )

        # 3. POMD / Committee Secretary User
        is_pomd = bool(
            (sec_user and current_user.id == sec_user.id) or
            current_user.has_group('discipline_management.group_discipline_pomd_director') or
            current_user.has_group('discipline_management.group_discipline_pomd') or
            is_admin
        )

        is_aud = bool(
            (audit_user and current_user.id == audit_user.id) or
            current_user.has_group('discipline_management.group_discipline_auditor') or
            is_admin
        )

        is_sec = current_user.has_group('discipline_management.group_discipline_secretary')
        is_sec_only = bool(is_sec and not is_admin and not is_ceo and not is_cpco and not is_pomd and not is_aud)

        for rec in self:
            rec.is_pomd_user = is_pomd
            rec.is_auditor_user = is_aud
            rec.is_ceo_user = is_ceo
            rec.is_cpco_user = is_cpco
            rec.is_discipline_secretary = is_sec
            rec.is_discipline_secretary_only = is_sec_only

            # Directorate Director / Executive Authority evaluation
            emp_sup_chain = rec.sudo().employee_id.get_supervisor_chain() if rec.employee_id else []
            is_dir_in_chain = any(
                s.user_id and s.user_id.id == current_user.id and (
                    getattr(s, 'executive_level', False) in ('director', 'chief', 'ceo') or
                    any(k in ((s.job_id.name or '') if s.job_id else '').lower() for k in ['director', 'deputy chief', 'chief', 'vp', 'regional manager'])
                )
                for s in emp_sup_chain
            )
            is_dept_manager = bool(
                rec.department_id and rec.department_id.manager_id and rec.department_id.manager_id.user_id.id == current_user.id and (
                    getattr(rec.department_id.manager_id, 'executive_level', False) in ('director', 'chief', 'ceo') or
                    any(k in ((rec.department_id.manager_id.job_id.name or '') if rec.department_id.manager_id.job_id else '').lower() for k in ['director', 'deputy chief', 'chief', 'vp'])
                )
            )
            is_case_dir = bool(rec.director_id and rec.director_id.id == current_user.id)
            is_case_chf = bool(rec.chief_id and rec.chief_id.id == current_user.id)
            is_user_director_rank = bool(
                emp and (
                    getattr(emp, 'executive_level', False) in ('director', 'chief', 'ceo') or
                    any(k in job_name for k in ['director', 'regional manager', 'deputy chief', 'chief', 'cpco', 'cfo', 'cio', 'cdo', 'cido', 'coo', 'vp', 'president'])
                )
            )

            rec.is_director_user = bool(
                is_admin or
                is_case_dir or
                is_dir_in_chain or
                is_dept_manager or
                is_user_director_rank or
                current_user.has_group('discipline_management.group_discipline_director')
            )
            rec.is_chief_user = bool(
                is_admin or
                is_case_chf or
                is_cpco or
                is_ceo or
                current_user.has_group('discipline_management.group_discipline_chief') or
                (emp and (getattr(emp, 'executive_level', False) in ('chief', 'ceo') or any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'cido', 'coo', 'vp', 'president'])))
            )

            # Check if current user is the employee under this case
            rec_emp = rec.sudo().employee_id
            is_emp = bool(
                rec_emp and (
                    (rec_emp.user_id and rec_emp.user_id.id == current_user.id) or
                    (current_user.sudo().employee_id and current_user.sudo().employee_id.id == rec_emp.id) or
                    (hasattr(current_user, 'employee_ids') and rec_emp.id in current_user.sudo().employee_ids.ids)
                )
            )
            rec.is_current_user_employee = is_emp

            has_pending_appeal = any(a.state in ('draft', 'submitted', 'under_review') for a in rec.appeal_ids)
            is_dismissal = rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal'
            is_emp_inactive = bool(
                rec_emp and (
                    not rec_emp.active or
                    (rec_emp.user_id and not rec_emp.user_id.active)
                )
            )
            is_pomd_eligible = (
                is_pomd and
                is_dismissal and
                is_emp_inactive and
                rec.state in ('enforced', 'closed')
            )

            # Determine case origin track for appeal escalation hierarchy
            origin_type = rec._get_case_origin_type()

            first_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
            second_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
            third_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'third')
            fourth_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'fourth')

            is_exonerated = (
                rec.appeal_outcome_type == 'exonerated' or
                rec.punishment_type == 'exonerate'
            )

            # If an appeal decision was formally accepted by the employee, further appeals are barred
            has_accepted_appeal = any(a.acceptance_state in ('accepted', 'window_closed') for a in rec.appeal_ids)

            # 1st Level Appeal Eligibility
            eligible_first = (
                not first_appeal and
                rec.state == 'enforced' and
                rec.is_appeal_window_open and
                not has_pending_appeal and
                not has_accepted_appeal and
                not is_exonerated
            )

            # 2nd Level Appeal Eligibility
            eligible_second = False
            if first_appeal and not second_appeal and not has_pending_appeal and not has_accepted_appeal and rec.state in ('enforced', 'closed') and not is_exonerated:
                f_app = first_appeal[0]
                if f_app.state == 'decided' and f_app.decision_outcome in ('upheld', 'penalty_reduced') and f_app.acceptance_state == 'pending':
                    f_exonerated = (
                        f_app.decision_outcome == 'overturned' or
                        f_app.revised_punishment_type == 'exonerate' or
                        (f_app.decision_outcome == 'penalty_reduced' and f_app.revised_penalty_percentage == 0.0 and f_app.revised_fine_days == 0.0 and f_app.revised_punishment_type in ('exonerate', False))
                    )
                    if not f_exonerated and origin_type in ('manager', 'director'):
                        eligible_second = True

            # 3rd Level Appeal Eligibility (Manager track only)
            eligible_third = False
            if second_appeal and not third_appeal and not has_pending_appeal and not has_accepted_appeal and rec.state in ('enforced', 'closed') and not is_exonerated:
                s_app = second_appeal[0]
                if s_app.state == 'decided' and s_app.decision_outcome in ('upheld', 'penalty_reduced') and s_app.acceptance_state == 'pending':
                    s_exonerated = (
                        s_app.decision_outcome == 'overturned' or
                        s_app.revised_punishment_type == 'exonerate' or
                        (s_app.decision_outcome == 'penalty_reduced' and s_app.revised_penalty_percentage == 0.0 and s_app.revised_fine_days == 0.0 and s_app.revised_punishment_type in ('exonerate', False))
                    )
                    if not s_exonerated and origin_type == 'manager':
                        eligible_third = True

            # 4th Level Appeal Eligibility (Final to CEO if 3rd level appeal was decided by Chief Officer)
            eligible_fourth = False
            if third_appeal and not fourth_appeal and not has_pending_appeal and not has_accepted_appeal and rec.state in ('enforced', 'closed') and not is_exonerated:
                t_app = third_appeal[0]
                if t_app.state == 'decided' and t_app.decision_outcome in ('upheld', 'penalty_reduced') and t_app.acceptance_state == 'pending':
                    t_exonerated = (
                        t_app.decision_outcome == 'overturned' or
                        t_app.revised_punishment_type == 'exonerate' or
                        (t_app.decision_outcome == 'penalty_reduced' and t_app.revised_penalty_percentage == 0.0 and t_app.revised_fine_days == 0.0 and t_app.revised_punishment_type in ('exonerate', False))
                    )
                    is_third_ceo = (t_app.appeal_target_authority == 'ceo' or (ceo_user and t_app.reviewer_id and t_app.reviewer_id.id == ceo_user.id))
                    if not t_exonerated and not is_third_ceo and origin_type == 'manager':
                        eligible_fourth = True

            rec.can_submit_first_appeal = is_emp and eligible_first
            rec.can_submit_second_appeal = is_emp and eligible_second
            rec.can_submit_third_appeal = is_emp and eligible_third
            rec.can_submit_fourth_appeal = is_emp and eligible_fourth
            rec.can_submit_appeal = rec.can_submit_first_appeal or rec.can_submit_second_appeal or rec.can_submit_third_appeal or rec.can_submit_fourth_appeal

            rec.can_lodge_first_appeal_on_behalf = is_pomd_eligible and eligible_first
            rec.can_lodge_second_appeal_on_behalf = is_pomd_eligible and eligible_second
            rec.can_lodge_third_appeal_on_behalf = is_pomd_eligible and eligible_third
            rec.can_lodge_fourth_appeal_on_behalf = is_pomd_eligible and eligible_fourth
            rec.can_lodge_appeal_on_behalf = rec.can_lodge_first_appeal_on_behalf or rec.can_lodge_second_appeal_on_behalf or rec.can_lodge_third_appeal_on_behalf or rec.can_lodge_fourth_appeal_on_behalf

            if eligible_first:
                rec.next_appeal_level = 'first'
            elif eligible_second:
                rec.next_appeal_level = 'second'
            elif eligible_third:
                rec.next_appeal_level = 'third'
            elif eligible_fourth:
                rec.next_appeal_level = 'fourth'
            else:
                rec.next_appeal_level = False

            # Direct Appeal Acceptance:
            # An appeal can only be accepted by the subject employee if it has a pending intermediate decision
            # (i.e. NOT exonerated, and NOT rendered by the final authority like CEO).
            acceptable_appeals = rec.appeal_ids.filtered(
                lambda a: getattr(a, 'can_employee_accept_decision', False)
            )
            rec.can_accept_appeal_decision_on_case = bool(is_emp and acceptable_appeals)

    def action_accept_appeal_decision_from_case(self):
        self.ensure_one()
        acceptable_appeals = self.appeal_ids.filtered(
            lambda a: getattr(a, 'can_employee_accept_decision', False)
        )
        if not acceptable_appeals:
            raise UserError(_("No pending appeal decision found to accept. Decisions that are exonerated or rendered by the final authority do not require employee acceptance."))
        return acceptable_appeals[0].action_employee_accept_decision()

    @api.onchange('reported_by_id', 'employee_id', 'initiator_type')
    def _onchange_employee_id(self):
        self.reviewer_id = False
        if self.initiator_type == 'manager':
            # Approver is inferred from the REPORTER (the Line Manager initiating the case), NOT the employee under case!
            reporter_emp = (self.reported_by_id or self.env.user.employee_id).sudo()
            if reporter_emp:
                dept_mgr = reporter_emp.department_id.manager_id.user_id if reporter_emp.department_id and reporter_emp.department_id.manager_id else False
                if dept_mgr and dept_mgr != self.env.user:
                    self.approver_id = dept_mgr
                elif reporter_emp.parent_id and reporter_emp.parent_id.user_id and reporter_emp.parent_id.user_id != self.env.user:
                    self.approver_id = reporter_emp.parent_id.user_id
                elif reporter_emp.coach_id and reporter_emp.coach_id.user_id and reporter_emp.coach_id.user_id != self.env.user:
                    self.approver_id = reporter_emp.coach_id.user_id
                else:
                    # Fallback to HR Manager / CPCO if the reporter is already the Department Director
                    hr_mgr = self.env['res.users'].sudo().search([('name', 'ilike', 'Marta Bekele')], limit=1)
                    self.approver_id = hr_mgr or self.env.user
            else:
                self.approver_id = False
        else:
            self.approver_id = False

        if self.severity_level_id:
            self._onchange_offense_severity_resolve_rules()

    @api.constrains('case_action_track')
    def _check_case_action_track_authority(self):
        """Prevent Line Managers and non-executive supervisors from selecting Formal Committee Escalation."""
        for rec in self:
            if rec.case_action_track == 'committee_escalation':
                # Allow if case carries a sanction exceeding coach direct authority (mandated escalation to director)
                # or if already escalated/submitted to director/chief, or during system workflow transition
                if self.env.su or self.env.context.get('force_write') or self.env.context.get('force_escalate'):
                    continue
                if not rec.is_coach_enforce_allowed or rec.state in ('submitted_director', 'submitted_chief'):
                    continue
                user = self.env.user
                is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
                if is_admin:
                    continue
                emp = user.employee_id
                job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
                is_user_director_rank = bool(
                    emp and (
                        getattr(emp, 'executive_level', False) in ('director', 'chief', 'ceo') or
                        any(k in job_name for k in ['director', 'regional manager', 'deputy chief', 'chief', 'cpco', 'cfo', 'cio', 'cdo', 'cido', 'coo', 'vp', 'president'])
                    )
                )
                is_authorized = bool(
                    rec.is_director_user or
                    rec.is_chief_user or
                    rec.is_ceo_user or
                    rec.is_cpco_user or
                    rec.is_pomd_user or
                    rec.is_hr_admin or
                    rec.is_auditor_user or
                    is_user_director_rank or
                    (rec.director_id and rec.director_id.id == user.id) or
                    (rec.chief_id and rec.chief_id.id == user.id) or
                    user.has_group('discipline_management.group_discipline_director') or
                    user.has_group('discipline_management.group_discipline_chief') or
                    user.has_group('discipline_management.group_discipline_cpco') or
                    user.has_group('discipline_management.group_discipline_ceo') or
                    user.has_group('discipline_management.group_discipline_auditor')
                )
                if not is_authorized:
                    raise ValidationError(_(
                        "Unauthorized Action Pathway: Formal Escalation to Committee is restricted to Directorate Directors and above. "
                        "Line Managers / Coaches are restricted to Direct Action within their supervisory authority."
                    ))

    @api.constrains('employee_id', 'reported_by_id')
    def _check_self_initiation(self):
        """Prevent employees from raising a disciplinary case against themselves."""
        for rec in self:
            emp = rec.sudo().employee_id
            rep = rec.sudo().reported_by_id
            if emp and rep:
                if emp.id == rep.id:
                    raise ValidationError(_("Self-Initiation Prohibited: You cannot initiate a disciplinary case against yourself."))
                if emp.user_id and emp.user_id.id == self.env.uid and not self.env.user.has_group('base.group_system'):
                    raise ValidationError(_("Self-Initiation Prohibited: You cannot initiate a disciplinary case against yourself."))

    @api.constrains('is_statutory_mitigation_applied', 'punishment_type', 'original_punishment_type', 'mitigation_justification', 'state')
    def _check_mitigation_validity(self):
        """Validate statutory mitigation rules pursuant to CBA Art. 33.13."""
        rank_order = {
            'verbal_warning': 1,
            'first_warning_penalty': 2,
            'second_warning_penalty': 3,
            'final_warning_penalty': 4,
            'demotion': 5,
            'dismissal': 6,
            'fine': 2,
            'custom': 1,
            'exonerate': 0,
            False: 0,
        }
        for rec in self:
            if rec.is_statutory_mitigation_applied and rec.state not in ('revoked', 'appealed'):
                if not rec.mitigation_justification:
                    raise ValidationError(_("Mitigation Grounds & Justification is required when applying statutory mitigation."))
                orig_rank = rank_order.get(rec.original_punishment_type, 0)
                curr_rank = rank_order.get(rec.punishment_type, 0)
                if orig_rank > 1 and curr_rank >= orig_rank:
                    raise ValidationError(_("Invalid Mitigated Sanction: The mitigated disciplinary measure must be strictly less severe than the standard catalog penalty."))

    @api.constrains('incident_date')
    def _check_incident_date_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.incident_date and rec.incident_date > today:
                raise ValidationError(_(
                    'Invalid Misconduct Incident Date: The incident date (%s) cannot be in the future. '
                    'Please select today (%s) or a prior date.'
                ) % (rec.incident_date, today))

    @api.onchange('incident_date')
    def _onchange_incident_date(self):
        today = fields.Date.context_today(self)
        if self.incident_date and self.incident_date > today:
            invalid_date = self.incident_date
            self.incident_date = today
            return {
                'warning': {
                    'title': _('Invalid Incident Date'),
                    'message': _(
                        'The Misconduct Incident Date cannot be in the future (%s). '
                        'It has been automatically reset to today (%s).'
                    ) % (invalid_date, today),
                }
            }

    @api.constrains('employee_id', 'incident_date', 'offense_id')
    def _check_duplicate_case(self):
        for rec in self:
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('incident_date', '=', rec.incident_date),
                ('offense_id', '=', rec.offense_id.id),
                ('state', '!=', 'revoked')
            ])
            if duplicate:
                raise ValidationError(_(
                    'Duplicate Case Prevention: A disciplinary case already exists for Employee %s '
                    'on incident date %s for offense "%s" (Case Reference: %s).'
                ) % (rec.sudo().employee_id.name if rec.sudo().employee_id else '', rec.incident_date, rec.offense_id.name, duplicate[0].name))

            if rec.offense_id and rec.severity_level:
                same_severity = self.search([
                    ('id', '!=', rec.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('incident_date', '=', rec.incident_date),
                    ('severity_level', '=', rec.severity_level),
                    ('state', 'not in', ['revoked', 'closed']),
                ])
                if same_severity:
                    raise ValidationError(_(
                        'Duplicate Severity Prevention: Employee %s already has an open %s case '
                        'on incident date %s (Case Ref: %s). Consolidate into the existing case instead.'
                    ) % (rec.sudo().employee_id.name if rec.sudo().employee_id else '', rec.severity_level_id.name if rec.severity_level_id else (rec.severity_level or ''),
                         rec.incident_date, same_severity[0].name))

    def _validate_segregation_of_duties(self):
        for rec in self:
            current_user = self.env.user
            cfg_p, max_rank, allowed_levels = self._get_coach_max_authority()
            is_direct_mgr_enforcement = (
                rec.case_action_track == 'direct_enforce' and
                ((rec.severity_level != 'level_1' and rec.punishment_type != 'dismissal') or max_rank >= 6)
            )
            if not is_direct_mgr_enforcement:
                if rec.initiator_id and rec.reviewer_id and rec.initiator_id == rec.reviewer_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Reviewer must be different individuals.'))
                if rec.initiator_id and rec.approver_id and rec.initiator_id == rec.approver_id and rec.case_action_track != 'direct_enforce':
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Approver must be different individuals for escalated cases.'))
                if rec.reviewer_id and rec.approver_id and rec.reviewer_id == rec.approver_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Reviewer and Approver must be different individuals.'))

            if (rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal') and not is_direct_mgr_enforcement:
                if (not current_user.has_group('discipline_management.group_discipline_admin') and
                    not current_user.has_group('discipline_management.group_discipline_ceo') and
                    not current_user.has_group('discipline_management.group_discipline_cpco')):
                    raise ValidationError(_(
                        'Approval Restriction: Decisions requiring Dismissal / Separation are restricted '
                        'exclusively to authorized executive approvers (CEO / CPCO / Disciplinary Committee).'
                    ))
                if not rec.dismissal_authority_id:
                    rec.dismissal_authority_id = current_user
            elif (rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal') and is_direct_mgr_enforcement:
                if not rec.dismissal_authority_id:
                    rec.dismissal_authority_id = current_user

    @api.model_create_multi
    def create(self, vals_list):
        user = self.env.user
        is_privileged = (
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system') or
            user._is_admin() or
            self.env.su
        )
        if not is_privileged:
            emp = user.sudo().employee_id
            if not emp:
                raise ValidationError(_("Permission Denied: You do not have supervisory authority to initiate disciplinary cases."))
            child_subs = self.env['hr.employee'].sudo().search([
                '|', ('parent_id', '=', emp.id),
                ('coach_id', '=', emp.id)
            ])
            delegated_ids = []
            if hasattr(self.env['hr.employee'], '_get_delegation_visible_employee_ids'):
                try:
                    delegated_ids = self.env['hr.employee'].with_user(user)._get_delegation_visible_employee_ids()
                except Exception:
                    delegated_ids = []
            all_allowed_sub_ids = set(child_subs.ids) | set(delegated_ids or [])
            if not all_allowed_sub_ids:
                raise ValidationError(_("Permission Denied: You do not have supervisory authority to initiate disciplinary cases."))
            for vals in vals_list:
                subj_emp_id = vals.get('employee_id')
                if subj_emp_id and subj_emp_id not in all_allowed_sub_ids:
                    raise ValidationError(_("Permission Denied: You can only initiate disciplinary cases for your direct subordinates."))

        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('discipline.case') or _('New')
            if vals.get('offense_id'):
                off = self.env['discipline.offense'].browse(vals['offense_id'])
                if not vals.get('article_id') and off.article_id:
                    vals['article_id'] = off.article_id.id
                if not vals.get('policy_version_id') and off.policy_version_id:
                    vals['policy_version_id'] = off.policy_version_id.id
                if not vals.get('severity_level_id'):
                    severity = off.severity_level_id or (off.article_id and off.article_id.severity_level_id)
                    if severity:
                        vals['severity_level_id'] = severity.id
        cases = super().create(vals_list)
        cases._compute_is_cash_shortage()
        cases._compute_punishment_details()
        cases._compute_legal_citation()
        cases._compute_active_duration_days()
        cases._compute_statutory_deadline()
        return cases


    @api.depends('state', 'coach_id', 'coach_id.user_id', 'director_id', 'chief_id')
    def _compute_current_stage_authority(self):
        Emp = self.env['hr.employee'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        audit_uid = ICP.get_param('discipline.audit_user_id')
        audit_user = self.env['res.users'].browse(int(audit_uid)) if audit_uid and str(audit_uid).isdigit() else False
        cpco = Emp.get_cpco_user()
        ceo = Emp.get_ceo_user()
        st_dict = dict(self._fields['state'].selection) if 'state' in self._fields else {}

        for rec in self:
            user = False
            label = False
            if rec.state in ['draft', 'initiated']:
                user = rec.coach_id.user_id if rec.coach_id else False
                label = rec.coach_id.name if rec.coach_id else _('Coach / Line Manager')
            elif rec.state in ['director_review', 'submitted_director']:
                user = rec.director_id
                label = rec.director_id.name if rec.director_id else _('Directorate Director')
            elif rec.state in ['chief_review', 'submitted_chief']:
                user = rec.chief_id
                label = rec.chief_id.name if rec.chief_id else _('Respective Chief')
            elif rec.state in ['investigating', 'under_investigation']:
                user = audit_user
                label = audit_user.name if audit_user else _('Internal Audit Directorate')
            elif rec.state in ['committee_review', 'chairman_review']:
                user = cpco
                label = cpco.name if cpco else _('CPCO / Committee Chairman')
            elif rec.state in ['ceo_review', 'pending_approval']:
                user = ceo
                label = ceo.name if ceo else _('Chief Executive Officer (CEO)')
            elif rec.state in ['enforced', 'closed', 'revoked', 'appealed']:
                user = False
                label = st_dict.get(rec.state, rec.state)
            else:
                user = False
                label = st_dict.get(rec.state, rec.state)

            rec.current_stage_authority_user_id = user
            rec.current_stage_authority_name = label

    _compute_current_stage_authority_name = _compute_current_stage_authority

    @api.depends('current_stage_authority_user_id', 'state')
    def _compute_is_my_executive_case(self):
        user = self.env.user
        exec_user = user.discipline_effective_boss_id
        for rec in self:
            if exec_user:
                rec.is_my_executive_case = bool(rec.current_stage_authority_user_id and rec.current_stage_authority_user_id.id == exec_user.id)
            else:
                rec.is_my_executive_case = False

    def _search_is_my_executive_case(self, operator, value):
        user = self.env.user
        exec_user = user.discipline_effective_boss_id
        if not exec_user:
            return [('id', '=', 0)] if value else [(1, '=', 1)]

        if operator in ('=', '!=') and value:
            op = '=' if operator == '=' else '!='
            return [('current_stage_authority_user_id', op, exec_user.id)]
        elif operator in ('=', '!=') and not value:
            op = '!=' if operator == '=' else '='
            return [('current_stage_authority_user_id', op, exec_user.id)]
        return []

    @api.model
    def action_open_disciplinary_cases(self):
        """Action handler for Disciplinary Cases menu.
        Restricts secretaries to only their own cases in the standard menu,
        while maintaining full follow-up tracking in the dedicated Follow-up menu & Dashboard.
        """
        user = self.env.user
        action = self.env['ir.actions.act_window']._for_xml_id('discipline_management.action_discipline_case')
        domain = [('is_attendance_case', '=', False)]

        is_secretary = user.has_group('discipline_management.group_discipline_secretary')
        is_governance = (
            user.has_group('discipline_management.group_discipline_pomd')
            or user.has_group('discipline_management.group_discipline_pomd_director')
            or user.has_group('discipline_management.group_discipline_cpco')
            or user.has_group('discipline_management.group_discipline_ceo')
            or user.has_group('discipline_management.group_discipline_auditor')
            or user.has_group('discipline_management.group_discipline_legal')
            or user.has_group('discipline_management.group_discipline_admin')
            or user.has_group('discipline_management.group_discipline_director')
        )
        if is_secretary and not is_governance:
            domain.append(('employee_id.user_id', '=', user.id))

        action['domain'] = domain
        return action



    def action_load_saved_signature(self):
        """Load the user's previously saved signature into this case."""
        self.ensure_one()
        if not self.can_user_sign_notice:
            raise UserError(_("Access Restriction: You are not authorized to provide or modify the digital signature for this case."))
        if self.state in ('enforced', 'closed', 'appealed', 'revoked'):
            raise UserError(_("Case is already finalized and enforced. Digital signature cannot be modified."))
        user = self.env.user
        sig = getattr(user, 'discipline_digital_signature', False) or getattr(user, 'digital_signature', False)
        if not sig:
            # Fall back to the user's latest signed case
            prev_case = self.search([
                ('signatory_signature', '!=', False),
                '|', ('initiator_id', '=', user.id), ('create_uid', '=', user.id)
            ], order='id desc', limit=1)
            if prev_case and prev_case.signatory_signature:
                sig = prev_case.signatory_signature
                try:
                    user.sudo().write({'discipline_digital_signature': sig})
                except Exception:
                    pass
        if not sig:
            raise UserError(_("No saved signature found for %s. Please draw your signature on the canvas and it will be remembered automatically for future cases.") % user.name)
        self.signatory_signature = sig
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Signature Loaded'),
                'message': _('Your saved signature has been loaded onto this case.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_save_as_default_signature(self):
        """Save the signature currently on the case into the user profile for future cases."""
        self.ensure_one()
        if not self.can_user_sign_notice:
            raise UserError(_("Access Restriction: You are not authorized to update digital signatures on this case."))
        if not self.signatory_signature:
            raise UserError(_("Please draw or upload a signature on the canvas first."))
        self.env.user.sudo().write({'discipline_digital_signature': self.signatory_signature})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Default Signature Saved'),
                'message': _('Your digital signature has been saved to your profile and will be available for future cases.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_secretary_remind_boss(self):
        """Allow Executive Secretaries to dispatch an urgent deadline reminder to their direct executive."""
        self.ensure_one()
        user = self.env.user
        exec_boss = user.discipline_effective_boss_id
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()

        # Non-admin secretaries are strictly confined to their assigned executive boss
        if not is_admin:
            if not exec_boss:
                raise UserError(_("Access Restriction: You are not assigned as an executive secretary to any executive officer."))
            if not self.is_my_executive_case or (self.current_stage_authority_user_id and self.current_stage_authority_user_id.id != exec_boss.id):
                raise UserError(_(
                    "Authority Boundary: You are designated as secretary for %(boss)s. "
                    "You can only dispatch urgent reminders for cases currently awaiting their direct review and action."
                ) % {'boss': exec_boss.name})

        target_user = exec_boss if (not is_admin and exec_boss) else self.current_stage_authority_user_id
        if not target_user:
            Emp = self.env['hr.employee'].sudo()
            if self.state in ['draft', 'initiated']:
                target_user = self.coach_id.user_id if self.coach_id else False
            elif self.state in ['director_review', 'submitted_director']:
                target_user = self.director_id
            elif self.state in ['chief_review', 'submitted_chief']:
                target_user = self.chief_id
            elif self.state in ['investigating', 'under_investigation']:
                ICP = self.env['ir.config_parameter'].sudo()
                audit_uid = ICP.get_param('discipline.audit_user_id')
                if audit_uid and str(audit_uid).isdigit():
                    target_user = self.env['res.users'].browse(int(audit_uid))
            elif self.state in ['committee_review', 'chairman_review']:
                target_user = Emp.get_cpco_user()
            elif self.state in ['ceo_review', 'pending_approval']:
                target_user = Emp.get_ceo_user()

        if not target_user:
            target_user = self.approver_id or self.reviewer_id

        if not target_user:
            raise UserError(_("No responsible executive could be resolved for Case %s in stage '%s'.") % (self.name, self.state))

        # Cooldown: prevent accidental double-reminder within 4 hours
        if self.last_secretary_reminder_date and not self.env.context.get('force_remind'):
            elapsed_hours = (fields.Datetime.now() - self.last_secretary_reminder_date).total_seconds() / 3600.0
            if elapsed_hours < 4.0:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Reminder Already Sent'),
                        'message': _('A follow-up was already dispatched to %s %.1f hour(s) ago. To prevent spamming, please allow sufficient time for executive action.') % (target_user.name, elapsed_hours),
                        'type': 'warning',
                        'sticky': False,
                    }
                }

        sender = self.env.user
        st_dict = dict(self._fields['state'].selection) if 'state' in self._fields else {}
        stage_name = st_dict.get(self.state, self.state)
        deadline_str = self.stage_deadline.strftime('%B %d, %Y') if self.stage_deadline else _('Immediate')
        presc_str = self.prescription_deadline.strftime('%B %d, %Y') if self.prescription_deadline else _('Imminent')

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        action_url = f"{base_url}/web#id={self.id}&model=discipline.case&view_type=form" if base_url else f"/web#id={self.id}&model=discipline.case&view_type=form"

        msg = Markup(
            f"<div style='font-family: Arial, sans-serif;'>"
            f"<p style='color: #856404; font-weight: bold; font-size: 14px;'>🔔 URGENT SLA FOLLOW-UP FROM EXECUTIVE OFFICE ({sender.name})</p>"
            f"<p>Dear {target_user.name},</p>"
            f"<p>This is a formal follow-up regarding active Disciplinary Case <strong>{self.name}</strong> currently awaiting your review/action in stage <strong>{stage_name}</strong>.</p>"
            f"<table style='width: 100%; border: 1px solid #dee2e6; border-collapse: collapse; font-size: 13px; margin: 10px 0;'>"
            f"  <tr style='background: #f8f9fa; border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Current Stage</td><td style='padding: 6px;'>{stage_name}</td></tr>"
            f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Days in Stage</td><td style='padding: 6px;'>{self.days_in_stage} day(s) (Target: {self.stage_target_days} days)</td></tr>"
            f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Stage Target Deadline</td><td style='padding: 6px;'>{deadline_str}</td></tr>"
            f"  <tr style='border-bottom: 1px solid #dee2e6;'><td style='padding: 6px; font-weight: bold;'>Statutory Prescription Deadline</td><td style='padding: 6px; color: #dc3545; font-weight: bold;'>{presc_str}</td></tr>"
            f"  <tr><td style='padding: 6px; font-weight: bold;'>Urgency Status</td><td style='padding: 6px;'>{self.sla_countdown_display or ''}</td></tr>"
            f"</table>"
            f"<p style='margin-top: 15px;'>"
            f"  <a href='{action_url}' style='background-color: #795548; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;'>"
            f"      👉 Open Case {self.name} for Immediate Action"
            f"  </a>"
            f"</p>"
            f"<p style='color: #6c757d; font-size: 12px; margin-top: 10px;'>"
            f"  <em>Please process promptly to comply with Bank Policy and avoid statutory forfeiture.</em>"
            f"</p>"
            f"</div>"
        )

        self._post_discuss_dm(sender, target_user, msg, subscribe_case=False)
        self.sudo().write({'last_secretary_reminder_date': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reminder Dispatched'),
                'message': _('Urgent deadline reminder successfully sent to %s.') % target_user.name,
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def _cron_case_expiration_followup_alerts(self):
        """
        Daily automated expiration follow-up cron:
        1. Finds all active disciplinary cases that are in 'warning' or 'overdue' SLA status.
        2. Groups cases by responsible executive (current_stage_authority_user_id).
        3. Sends a consolidated executive morning digest via Discuss DM to the executive and their secretary.
        """
        active_cases = self.search([
            ('state', 'not in', ['closed', 'revoked', 'enforced']),
            ('sla_status', 'in', ['warning', 'overdue']),
        ])
        if not active_cases:
            return

        cases_by_user = {}
        for case in active_cases:
            exec_user = case.current_stage_authority_user_id
            if not exec_user:
                continue
            cases_by_user.setdefault(exec_user, self.env['discipline.case'])
            cases_by_user[exec_user] |= case

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        admin_user = self.env.ref('base.user_root') or self.env.user

        for exec_user, cases in cases_by_user.items():
            overdue_cases = cases.filtered(lambda c: c.sla_status == 'overdue')
            warning_cases = cases.filtered(lambda c: c.sla_status == 'warning')

            items_html = ""
            for c in cases:
                urgency_badge = (
                    "<span style='background-color: #dc3545; color: white; padding: 2px 6px; border-radius: 3px; font-weight: bold;'>OVERDUE</span>"
                    if c.sla_status == 'overdue'
                    else "<span style='background-color: #ffc107; color: black; padding: 2px 6px; border-radius: 3px; font-weight: bold;'>APPROACHING</span>"
                )
                link = f"{base_url}/web#id={c.id}&model=discipline.case&view_type=form" if base_url else f"/web#id={c.id}&model=discipline.case&view_type=form"
                st_dict = dict(c._fields['state'].selection) if 'state' in c._fields else {}
                st_name = st_dict.get(c.state, c.state)
                items_html += f"""
                <tr style='border-bottom: 1px solid #dee2e6;'>
                    <td style='padding: 6px;'><a href='{link}'><strong>{c.name}</strong></a></td>
                    <td style='padding: 6px;'>{c.department_id.name or '-'}</td>
                    <td style='padding: 6px;'>{st_name}</td>
                    <td style='padding: 6px;'>{c.days_in_stage} d</td>
                    <td style='padding: 6px;'>{c.prescription_deadline.strftime('%b %d, %Y') if c.prescription_deadline else '-'}</td>
                    <td style='padding: 6px;'>{urgency_badge} {c.sla_countdown_display or ''}</td>
                    <td style='padding: 6px;'><a href='{link}' style='color: #007bff; text-decoration: underline;'>Review 👉</a></td>
                </tr>
                """

            body = Markup(f"""
            <div style='font-family: Arial, sans-serif; max-width: 800px;'>
                <h3 style='color: #894b15; margin-bottom: 5px;'>⚖️ Executive Disciplinary SLA &amp; Expiration Digest</h3>
                <p>Dear {exec_user.name},</p>
                <p>The system has identified <strong>{len(cases)} active case(s)</strong> awaiting your direct review that are near statutory prescription or exceeding SLA targets:</p>
                <ul>
                    <li style='color: #dc3545;'><strong>{len(overdue_cases)} Overdue Case(s)</strong> (Immediate action required to avoid statutory expiration)</li>
                    <li style='color: #856404;'><strong>{len(warning_cases)} Case(s) Approaching Deadline</strong></li>
                </ul>
                <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px;'>
                    <thead>
                        <tr style='background-color: #f8f9fa; text-align: left; border-bottom: 2px solid #dee2e6;'>
                            <th style='padding: 6px;'>Case Ref</th>
                            <th style='padding: 6px;'>Department</th>
                            <th style='padding: 6px;'>Stage</th>
                            <th style='padding: 6px;'>In Stage</th>
                            <th style='padding: 6px;'>Prescription Deadline</th>
                            <th style='padding: 6px;'>Status</th>
                            <th style='padding: 6px;'>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>
                <p style='margin-top: 15px; color: #666; font-size: 12px;'>
                    <em>Bunna Bank Disciplinary Governance System. Decisions delayed beyond statutory prescription periods risk legal forfeiture.</em>
                </p>
            </div>
            """)

            # Send Discuss DM to Executive
            cases[0]._post_discuss_dm(admin_user, exec_user, body, subscribe_case=False)

            # Also notify any secretary assigned strictly to this executive
            sec_users = exec_user.get_assigned_secretary_users()
            for sec in sec_users:
                if sec.id != exec_user.id:
                    cases[0]._post_discuss_dm(admin_user, sec, body, subscribe_case=False)

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        if 'state' in vals and 'stage_entry_date' not in vals:
            vals['stage_entry_date'] = fields.Datetime.now()
        if 'employee_id' in vals and not force_write and not self.env.su:
            for rec in self:
                if rec.state != 'draft' and rec.employee_id.id != vals['employee_id']:
                    raise UserError(_('The Subject Employee cannot be modified once the case has been initiated.'))
        if 'incident_date' in vals and not force_write and not self.env.su:
            for rec in self:
                if rec.state != 'draft' and str(rec.incident_date) != str(vals['incident_date']):
                    raise UserError(_('The Misconduct Incident Date cannot be modified once the case has been initiated.'))
        if 'signatory_signature' in vals and not force_write and not self.env.su:
            for rec in self:
                if rec.state in ('enforced', 'closed', 'appealed', 'revoked'):
                    raise UserError(_('Tamper Protection: The digital signature cannot be modified after the decision has been enforced.'))
                if not rec.can_user_sign_notice:
                    raise UserError(_('Access Restriction: You are not authorized to provide or edit the digital signature on this case.'))
        if ('employee_name_amharic' in vals or 'notice_language' in vals) and not force_write and not self.env.su:
            for rec in self:
                if rec.state in ('enforced', 'closed', 'appealed', 'revoked'):
                    raise UserError(_('Tamper Protection: Official notice configuration cannot be altered after decision enforcement.'))
        if not force_write and not self.env.su:
            whitelisted_fields = {
                'state', 'revocation_reason', 'revocation_date', 'revoked_by_id', 'is_revoked',
                'message_follower_ids', 'message_ids', 'activity_ids', 'is_locked_for_committee',
                'approver_id', 'final_decision_date', 'delivery_receipt_date', 'chief_id',
                'escalation_target', 'ceo_assignment_notes', 'occurrence_count',
                'is_escalated_by_active_warning', 'auto_applied_rule_summary',
                'original_punishment_type', 'original_penalty_percentage', 'original_fine_days',
                'punishment_type', 'penalty_percentage', 'fine_days',
                'decided_punishment_type', 'decided_penalty_percentage', 'decided_fine_days',
                'dismissal_authority_id', 'enforced_by_id', 'enforcement_date', 'executive_decision_notes',
                'is_punishment_modified_by_committee', 'is_cash_shortage',
                'statutory_deadline_date', 'is_deadline_exceeded', 'active_penalty_end_date',
                'active_duration_days', 'legal_article_display', 'legal_clause_text',
                'appeal_outcome_type', 'appeal_outcome_display', 'appeal_ids',
                'deduction_status', 'computed_deduction_month', 'payroll_month', 'active',
                'chief_review_notes', 'notice_language', 'signatory_signature', 'bank_stamp',
                'stage_entry_date', 'stage_target_days', 'days_in_stage', 'stage_deadline',
                'prescription_deadline', 'sla_status', 'executive_summary_misconduct', 'executive_summary_sanction', 'executive_summary_financial', 'executive_summary_committee', 'current_stage_authority_name', 'last_secretary_reminder_date',
                'employee_name_amharic',
                'is_attendance_case', 'attendance_violation_type', 'absent_days_count', 'max_consecutive_days', 'late_minutes_total', 'late_occurrences_count', 'force_checkout_count', 'absent_dates_summary', 'is_shift_worker', 'shift_schedule_summary', 'attendance_date_from', 'attendance_date_to', 'leave_id', 'covered_leave_days', 'attendance_justification_reason'
            }
            # Only enforce immutability on manually edited, non-computed user fields
            explicit_user_fields = {
                k for k in vals.keys()
                if k in self._fields and not self._fields[k].compute
            }
            for rec in self:
                if rec.state in ('enforced', 'closed', 'appealed'):
                    if explicit_user_fields - whitelisted_fields:
                        raise UserError(_('Enforced, closed, or appealed disciplinary cases are immutable and cannot be edited. Use formal revocation if required.'))
                if rec.is_locked_for_committee:
                    if explicit_user_fields - whitelisted_fields:
                        raise UserError(_('Case %s is currently locked for committee review and cannot be edited.') % rec.name)
        res = super().write(vals)
        if vals.get('employee_name_amharic'):
            for rec in self:
                emp = rec.employee_id.sudo() if rec.employee_id else False
                if emp and getattr(emp, 'name_amharic', None) != vals['employee_name_amharic']:
                    emp.write({'name_amharic': vals['employee_name_amharic']})
        return res

    def unlink(self):
        for rec in self:
            # 1. Enforced, closed, appealed, or revoked cases CAN NEVER BE DELETED under any circumstances
            if rec.state in ['enforced', 'closed', 'appealed', 'revoked']:
                state_label = dict(rec._fields['state'].selection).get(rec.state, rec.state)
                raise UserError(_(
                    'Preservation Policy Violation: Case %s is %s and cannot be deleted. '
                    'Enforced or finalized disciplinary records are legally protected and immutable for statutory compliance. '
                    'Use formal Revocation if required.'
                ) % (rec.name, state_label))

            # 2. Advanced workflow protection: Cases past initiation must follow formal workflow
            if rec.state not in ['draft', 'initiated']:
                state_label = dict(rec._fields['state'].selection).get(rec.state, rec.state)
                raise UserError(_(
                    'Active Workflow Protection: Case %s is currently in stage "%s". '
                    'Cases that have advanced to executive or committee review cannot be deleted.'
                ) % (rec.name, state_label))

            # 3. Role-based authorization: Only case creator, reporting manager, direct supervisor, or HR Admin
            user = self.env.user
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
            is_creator = bool(rec.create_uid and rec.create_uid.id == user.id)
            is_rep_manager = bool(rec.reported_by_id and rec.reported_by_id.user_id and rec.reported_by_id.user_id.id == user.id)
            is_supervisor = bool(rec.is_case_direct_supervisor or rec.is_director_user)

            if not (is_admin or is_creator or is_rep_manager or is_supervisor or self.env.su):
                raise UserError(_(
                    'Permission Denied: You are not authorized to delete case %s. '
                    'Only the case initiator, reporting supervisor, or an HR Administrator can delete it.'
                ) % rec.name)

        if self.env.context.get('force_unlink'):
            return super().unlink()

        # Soft delete (archive) all cases to maintain full auditability and historical integrity
        self.with_context(force_write=True).write({'active': False})
        for rec in self:
            rec.message_post(
                body=Markup(_('Case <strong>%s</strong> was soft-deleted / archived by %s.') % (rec.name, self.env.user.name))
            )

        return True

    def action_view_full_offense_clause(self):
        """Open the complete verbatim statutory definition of the selected misconduct offense clause."""
        self.ensure_one()
        if not self.offense_id:
            return False
        return {
            'name': _('Statutory Legal Provision & Misconduct Definition'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.offense',
            'res_id': self.offense_id.id,
            'view_mode': 'form',
            'view_id': self.env.ref('discipline_management.view_discipline_offense_dialog_form').id,
            'target': 'new',
            'flags': {'form': {'action_buttons': False}},
        }

    def action_open_misconduct_explorer(self):
        """Open the interactive Misconduct Catalog & Legal Clause Explorer wizard."""
        self.ensure_one()
        return {
            'name': _('Misconduct Catalog & Statutory Clause Explorer'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.misconduct.selector.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_staff_category': self.staff_category or 'all',
                'default_selected_offense_id': self.offense_id.id if self.offense_id else False,
                'default_severity_level_id': self.severity_level_id.id if self.severity_level_id else False,
                'default_article_id': self.article_id.id if self.article_id else False,
            }
        }

