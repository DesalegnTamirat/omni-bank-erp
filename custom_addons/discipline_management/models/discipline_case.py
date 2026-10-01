# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class DisciplineCase(models.Model):
    _name = 'discipline.case'
    _description = 'Disciplinary Case Record'
    _inherit = ['mail.thread']
    _order = 'incident_date desc, id desc'

    name = fields.Char(string='Case Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', store=True, readonly=True)
    work_location_id = fields.Many2one('hr.work.location', string='Work Location', related='employee_id.work_location_id', store=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    policy_version_id = fields.Many2one('discipline.policy.version', string='Governing Regulation', tracking=True)
    article_id = fields.Many2one('discipline.article', string='Regulatory Article', tracking=True)
    offense_id = fields.Many2one('discipline.offense', string='Offense Type / Clause', required=True, tracking=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='offense_id.category_id', store=True, readonly=True)
    sub_article_code = fields.Char(related='offense_id.sub_article_code', string='Clause Code', store=True, readonly=True)
    legal_article_display = fields.Char(string='Statutory Legal Citation', compute='_compute_legal_citation', store=True)
    legal_clause_text = fields.Text(string='Verbatim Statutory Clause Text', compute='_compute_legal_citation', store=True)

    occurrence_count = fields.Integer(string='Breach Occurrence Tier', default=1, compute='_compute_punishment_details', store=True, readonly=False, tracking=True)
    is_escalated_by_active_warning = fields.Boolean(string='Escalated by Prior Active Warning (Art 33.1.4)', compute='_compute_punishment_details', store=True, readonly=False, tracking=True)
    auto_applied_rule_summary = fields.Text(string='Rule Application Summary', compute='_compute_punishment_details', store=True)

    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=False, tracking=True)
    severity_level = fields.Char(string='Severity Code', related='severity_level_id.code', store=True, readonly=True)
    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
        ('exonerate', 'Exonerated / Overturned'),
    ], string='Applicable Punishment', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)

    original_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
        ('exonerate', 'Exonerated / Overturned'),
    ], string='Original Standard Punishment', compute='_compute_punishment_details', store=True, readonly=True)

    original_penalty_percentage = fields.Float(string='Original Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True)
    original_fine_days = fields.Float(string='Original Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True)

    decided_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('fine', 'Salary Fine Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
        ('exonerate', 'Exonerated / Overturned'),
    ], string='Final Committee Decided Punishment', tracking=True)

    decided_penalty_percentage = fields.Float(string='Final Decided Penalty (%)', tracking=True)
    decided_fine_days = fields.Float(string='Final Decided Salary Fine (Days)', tracking=True)
    is_punishment_modified_by_committee = fields.Boolean(string='Punishment Modified by Committee', compute='_compute_is_punishment_modified', store=True)

    @api.depends('article_id', 'offense_id', 'offense_id.sub_article_code', 'article_id.article_number')
    def _compute_legal_citation(self):
        for rec in self:
            citations = []
            if rec.article_id and rec.article_id.article_number:
                citations.append(_('Article %s') % rec.article_id.article_number)
            if rec.offense_id and rec.offense_id.sub_article_code:
                citations.append(_('Clause %s') % rec.offense_id.sub_article_code)
            rec.legal_article_display = ' - '.join(citations) if citations else False
            rec.legal_clause_text = (rec.offense_id and rec.offense_id.full_clause_text) or (rec.article_id and rec.article_id.description) or False

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
    statutory_deadline_date = fields.Date(string='Statutory Decision Deadline', compute='_compute_statutory_deadline', store=True)
    is_deadline_exceeded = fields.Boolean(string='Statutory SLA Exceeded', compute='_compute_statutory_deadline', store=True)

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
        'appeal_outcome_type'
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
            emp = rec.employee_id
            job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
            is_managerial = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor'])

            # 1. Count active prior penalties within validity window
            inc_date = rec.incident_date or fields.Date.context_today(rec)
            prior_cases = self.env['discipline.case'].sudo().search([
                ('employee_id', '=', emp.id),
                ('id', '!=', rec._origin.id if rec._origin else (rec.id or 0)),
                ('state', 'in', ['enforced', 'closed', 'appealed']),
                ('active_penalty_end_date', '>=', inc_date),
            ]) if emp else self.env['discipline.case']

            has_active_prior_warning = bool(prior_cases)
            same_offense_cases = prior_cases.filtered(lambda c: c.offense_id == rec.offense_id or (c.article_id and c.article_id == rec.article_id)) if rec.offense_id else self.env['discipline.case']
            
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
                    if is_managerial:
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
                rule_notes.append(_('Applied Severity Level Standard Baseline (%s)') % lvl.name)

            # Check Article 33.1.4 1-grade escalation if active prior warning exists and not already dismissal
            is_escalated = False
            if has_active_prior_warning and punish and punish != 'dismissal' and off and off.penalty_mode != 'repetition_escalation' and not is_csh_calc:
                curr_rank = rank_order.get(punish, 2)
                next_rank = min(curr_rank + 1, 5)
                if next_rank > curr_rank:
                    punish = rank_to_punish.get(next_rank, punish)
                    is_escalated = True
                    rule_notes.append(_('Escalated by 1 Rank pursuant to CBA Art. 33.1.4 / Management Policy Art. 10.3 due to %d active prior unexpired warning(s).') % len(prior_cases))

            # Check Article 33.13 Statutory Mitigation (-1 Grade Reduction)
            if rec.is_statutory_mitigation_applied and punish:
                mitigation_rank_map = {
                    'dismissal': 'final_warning_penalty',
                    'demotion': 'second_warning_penalty',
                    'final_warning_penalty': 'second_warning_penalty',
                    'second_warning_penalty': 'first_warning_penalty',
                    'first_warning_penalty': 'verbal_warning',
                }
                new_punish = mitigation_rank_map.get(punish)
                if new_punish:
                    punish = new_punish
                    if punish == 'verbal_warning':
                        pct = 0.0
                        days = 0.0
                    elif punish == 'first_warning_penalty':
                        pct = 5.0 if not is_managerial else 0.0
                        days = 1.0 if is_managerial else 0.0
                    elif punish == 'second_warning_penalty':
                        pct = 10.0 if not is_managerial else 0.0
                        days = 2.0 if is_managerial else 0.0
                    elif punish == 'final_warning_penalty':
                        pct = 20.0 if not is_managerial else 0.0
                        days = 3.0 if is_managerial else 0.0
                    rule_notes.append(_('Mitigated by 1 Rank pursuant to CBA Art. 33.13 (Good faith / clean record / performance factor).'))

            # Final enforcement of staff category segregation
            if not is_managerial:
                days = 0.0
            else:
                pct = 0.0

            rec.is_escalated_by_active_warning = is_escalated
            rec.auto_applied_rule_summary = ' | '.join(rule_notes) if rule_notes else False

            rec.original_punishment_type = punish
            rec.original_penalty_percentage = pct
            rec.original_fine_days = days

            if rec.appeal_outcome_type == 'exonerated' or (rec.state in ('enforced', 'closed', 'appealed') and rec.punishment_type == 'exonerate'):
                rec.punishment_type = 'exonerate'
                rec.penalty_percentage = 0.0
                rec.fine_days = 0.0
            elif rec.appeal_outcome_type == 'reduced' and rec.latest_appeal_id and rec.latest_appeal_id.state == 'decided':
                last_app = rec.latest_appeal_id
                rec.punishment_type = last_app.revised_punishment_type or punish
                rec.penalty_percentage = last_app.revised_penalty_percentage
                rec.fine_days = last_app.revised_fine_days
            else:
                rec.punishment_type = rec.decided_punishment_type or punish
                rec.penalty_percentage = rec.decided_penalty_percentage if rec.decided_penalty_percentage > 0 else pct
                rec.fine_days = rec.decided_fine_days if rec.decided_fine_days > 0 else days

    @api.model
    def _get_coach_max_authority(self):
        """
        Returns tuple: (max_punishment_key, max_rank_int, allowed_severity_codes_list)
        Punishment Ranks:
        1: verbal_warning (Level 5)
        2: first_warning_penalty (Level 4)
        3: second_warning_penalty (Level 3)
        4: final_warning_penalty (Level 2)
        """
        punish_to_rank = {
            'verbal_warning': (1, ['level_5']),
            'first_warning_penalty': (2, ['level_5', 'level_4']),
            'second_warning_penalty': (3, ['level_5', 'level_4', 'level_3']),
            'final_warning_penalty': (4, ['level_5', 'level_4', 'level_3', 'level_2']),
        }
        ICP = self.env['ir.config_parameter'].sudo()
        cfg_punish = ICP.get_param('discipline.coach_max_punishment', 'final_warning_penalty')
        rank, allowed_levels = punish_to_rank.get(cfg_punish, (4, ['level_5', 'level_4', 'level_3', 'level_2']))
        return cfg_punish, rank, allowed_levels

    @api.onchange('employee_id', 'case_action_track')
    def _onchange_employee_id_filter_regulations(self):
        if self.employee_id:
            emp = self.employee_id
            job_name = (emp.job_id.name or '').lower() if emp.job_id else ''
            is_mgr = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor'])
            cat = 'managerial' if is_mgr else 'non_managerial'
            self.staff_category = cat
            self.staff_category_display = _('Managerial Staff') if is_mgr else _('Non-Managerial Staff')
            if self.article_id and self.article_id.staff_category not in [cat, 'all']:
                self.article_id = False
                self.offense_id = False
                self.severity_level_id = False
            if self.offense_id and self.offense_id.staff_category not in [cat, 'all']:
                self.offense_id = False
                self.severity_level_id = False

            offense_domain = [('staff_category', 'in', [cat, 'all'])]
            if self.case_action_track == 'direct_enforce':
                _, _, allowed_levels = self._get_coach_max_authority()
                offense_domain.append(('severity_level', 'in', allowed_levels))

            return {
                'domain': {
                    'policy_version_id': [('staff_category', 'in', [cat, 'all'])],
                    'article_id': [('staff_category', 'in', [cat, 'all'])],
                    'offense_id': offense_domain,
                }
            }

    @api.onchange('severity_level_id')
    def _onchange_severity_level_id(self):
        cat = self.staff_category or 'non_managerial'
        res = {'domain': {}}
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
                '|',
                ('severity_level_id', '=', self.severity_level_id.id),
                ('article_id.severity_level_id', '=', self.severity_level_id.id),
                ('staff_category', 'in', [cat, 'all'])
            ]
            if self.case_action_track == 'direct_enforce':
                offense_domain.append(('severity_level', '!=', 'level_1'))
            res['domain']['offense_id'] = offense_domain
        else:
            offense_domain = [('staff_category', 'in', [cat, 'all'])]
            if self.case_action_track == 'direct_enforce':
                offense_domain.append(('severity_level', '!=', 'level_1'))
            res['domain']['offense_id'] = offense_domain
        self._compute_punishment_details()
        return res

    @api.onchange('article_id')
    def _onchange_article_id(self):
        if self.article_id:
            if not self.policy_version_id:
                self.policy_version_id = self.article_id.policy_version_id
            if self.article_id.severity_level_id:
                self.severity_level_id = self.article_id.severity_level_id
            return {
                'domain': {
                    'offense_id': [('article_id', '=', self.article_id.id)]
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
            # If Level 5 (Verbal Warning), reset statutory mitigation since it is already the minimum sanction
            if self.severity_level_id and self.severity_level_id.code == 'level_5':
                self.is_statutory_mitigation_applied = False
                self.mitigation_justification = False
        else:
            self.severity_level_id = False
            self.article_id = False
            self.is_statutory_mitigation_applied = False
            self.mitigation_justification = False
        self._compute_punishment_details()

    @api.onchange('severity_level_id', 'offense_id', 'employee_id', 'cash_shortage_amount', 'is_statutory_mitigation_applied')
    def _onchange_offense_severity_resolve_rules(self):
        """Re-trigger rule resolution immediately when severity level, offense, employee, cash shortage, or mitigation changes."""
        self._compute_punishment_details()

    penalty_percentage = fields.Float(string='Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    fine_days = fields.Float(string='Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    property_repair_cost = fields.Float(string='Property Repair / Replacement Cost (ETB)', tracking=True)
    is_managerial = fields.Boolean(string='Is Managerial Employee', related='employee_id.is_managerial', store=True, readonly=True)
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial Staff'),
        ('managerial', 'Managerial Staff'),
    ], string='Staff Category', compute='_compute_staff_category', store=True)
    staff_category_display = fields.Char(string='Staff Category', compute='_compute_staff_category', store=True)

    @api.depends('employee_id', 'employee_id.is_managerial', 'employee_id.job_id')
    def _compute_staff_category(self):
        for rec in self:
            emp = rec.employee_id
            if not emp:
                rec.staff_category = 'non_managerial'
                rec.staff_category_display = _('Non-Managerial Staff')
                continue
            job_name = (emp.job_id.name or '').lower() if emp.job_id else ''
            is_mgr = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor'])
            if is_mgr:
                rec.staff_category = 'managerial'
                rec.staff_category_display = _('Managerial Staff')
            else:
                rec.staff_category = 'non_managerial'
                rec.staff_category_display = _('Non-Managerial Staff')

    def _default_initiator_type(self):
        user = self.env.user
        if user.has_group('discipline_management.group_discipline_auditor'):
            return 'audit'
        user_dept_name = (user.employee_id.department_id.name or '').lower() if user.employee_id and user.employee_id.department_id else ''
        if 'audit' in user_dept_name or 'compliance' in user_dept_name:
            return 'audit'
        if user.has_group('discipline_management.group_discipline_director'):
            return 'director'
        return 'manager'

    case_action_track = fields.Selection([
        ('direct_enforce', 'Direct Action (Coach / Minor Misconduct)'),
        ('committee_escalation', 'Formal Escalation (Chief / Committee / Major Misconduct)'),
    ], string='Disciplinary Action Track', default='direct_enforce', required=True, tracking=True)

    initiator_type = fields.Selection([
        ('manager', 'Coach / Line Manager'),
        ('director', 'Directorate Director'),
        ('audit', 'Internal Audit / Compliance'),
    ], string='Case Initiator Source', default=_default_initiator_type, store=True, readonly=False, tracking=True)

    chief_id = fields.Many2one(
        'res.users',
        string='Respective Chief Officer',
        compute='_compute_chief_id',
        store=True,
        readonly=False,
        tracking=True
    )

    def _find_respective_chief_user(self):
        """Locate the respective Chief Officer by traversing the supervisor/coach hierarchy chain."""
        self.ensure_one()
        # 1. Start from Initiator / Reporter employee if available, or subject employee
        start_emp = (self.reported_by_id and self.reported_by_id.employee_id) or (self.create_uid and self.create_uid.employee_id) or self.employee_id
        
        curr = start_emp
        visited = set()
        while curr and curr.id not in visited:
            visited.add(curr.id)
            mgr = curr.coach_id or curr.parent_id or (curr.department_id and curr.department_id.manager_id)
            if not mgr or mgr.id == curr.id:
                break
            
            job_name = (mgr.job_id.name or '').lower() if mgr.job_id else ''
            exec_lvl = getattr(mgr, 'executive_level', False)
            if exec_lvl in ('chief', 'ceo') or any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                if mgr.user_id:
                    return mgr.user_id
            curr = mgr

        # 2. If not found via reporter, try subject employee hierarchy
        if self.employee_id and self.employee_id != start_emp:
            curr = self.employee_id
            visited = set()
            while curr and curr.id not in visited:
                visited.add(curr.id)
                mgr = curr.coach_id or curr.parent_id or (curr.department_id and curr.department_id.manager_id)
                if not mgr or mgr.id == curr.id:
                    break
                job_name = (mgr.job_id.name or '').lower() if mgr.job_id else ''
                exec_lvl = getattr(mgr, 'executive_level', False)
                if exec_lvl in ('chief', 'ceo') or any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']):
                    if mgr.user_id:
                        return mgr.user_id
                curr = mgr

        # 3. Fallback: Search for an employee with executive_level='chief' or CPCO
        chief_emp = self.env['hr.employee'].sudo().search([
            ('executive_level', '=', 'chief'),
            ('user_id', '!=', False)
        ], limit=1)
        if chief_emp and chief_emp.user_id:
            return chief_emp.user_id
        
        cpco_user = self.env['hr.employee'].get_cpco_user()
        if cpco_user:
            return cpco_user
            
        return False

    @api.depends('employee_id', 'reported_by_id', 'case_action_track')
    def _compute_chief_id(self):
        for rec in self:
            if not rec.chief_id or rec.case_action_track == 'committee_escalation':
                chief_u = rec._find_respective_chief_user()
                if chief_u:
                    rec.chief_id = chief_u
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
            rec.has_active_appeal = any(a.state in ('submitted', 'under_review') for a in appeals)

    @api.depends('appeal_ids', 'appeal_ids.state', 'appeal_ids.decision_outcome', 'appeal_ids.revised_punishment_type', 'appeal_ids.revised_penalty_percentage', 'appeal_ids.revised_fine_days', 'appeal_ids.review_date')
    def _compute_appeal_outcome(self):
        for rec in self:
            appeals = rec.appeal_ids.sorted(lambda a: (a.submission_date or fields.Date.today(), a.id or 0), reverse=True)
            if not appeals:
                rec.appeal_outcome_type = 'none'
                rec.appeal_outcome_display = False
                continue

            has_pending = any(a.state in ('submitted', 'under_review') for a in appeals)
            decided_appeals = appeals.filtered(lambda a: a.state == 'decided')
            if decided_appeals:
                last_decision = decided_appeals[0]
                outcome = last_decision.decision_outcome
                rev_punish = last_decision.revised_punishment_type
                reviewer = last_decision.reviewer_id.name or 'Executive Reviewer'
                d_date = last_decision.review_date or last_decision.submission_date or fields.Date.today()

                if outcome == 'overturned' or rev_punish == 'exonerate' or (last_decision.revised_fine_days == 0.0 and last_decision.revised_penalty_percentage == 0.0 and rev_punish in ('exonerate', False)):
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
                    rec.appeal_outcome_type = 'pending' if has_pending else 'none'
                    rec.appeal_outcome_display = False
            elif has_pending:
                rec.appeal_outcome_type = 'pending'
                rec.appeal_outcome_display = _("An appeal has been submitted and is currently under review.")
            else:
                rec.appeal_outcome_type = 'none'
                rec.appeal_outcome_display = False

    active_duration_days = fields.Integer(string='Penalty Active Duration (Days)', compute='_compute_active_duration_days', store=True, readonly=True)
    active_penalty_end_date = fields.Date(string='Penalty Active Expiration Date', compute='_compute_active_penalty_end_date', store=True, tracking=True)

    @api.depends('punishment_type', 'decided_punishment_type', 'severity_level_id', 'severity_level_id.active_duration_days', 'offense_id', 'offense_id.custom_warning_validity_months', 'appeal_outcome_type', 'state')
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
                rec.active_duration_days = 90

    @api.depends('final_decision_date', 'active_duration_days', 'state', 'appeal_outcome_type')
    def _compute_active_penalty_end_date(self):
        for rec in self:
            if rec.appeal_outcome_type == 'exonerated' or rec.active_duration_days == 0:
                rec.active_penalty_end_date = False
            elif rec.final_decision_date and rec.state == 'enforced':
                rec.active_penalty_end_date = rec.final_decision_date + timedelta(days=rec.active_duration_days or 365)
            else:
                rec.active_penalty_end_date = False

    is_coach_or_manager = fields.Boolean(string='Is Coach or Line Manager', compute='_compute_is_coach_or_manager')

    def _compute_is_coach_or_manager(self):
        current_emp = self.env.user.employee_id
        for rec in self:
            if not current_emp or not rec.employee_id:
                rec.is_coach_or_manager = (
                    self.env.user.has_group('discipline_management.group_discipline_admin') or
                    self.env.user.has_group('discipline_management.group_discipline_manager') or
                    self.env.user.has_group('discipline_management.group_discipline_director') or
                    self.env.user.has_group('discipline_management.group_discipline_chief') or
                    self.env.user.has_group('discipline_management.group_discipline_ceo')
                )
                continue
            is_sub = (
                rec.employee_id.parent_id.id == current_emp.id or
                rec.employee_id.coach_id.id == current_emp.id or
                rec.employee_id.department_id.manager_id.id == current_emp.id or
                rec.employee_id.id in self.env['hr.employee'].search([('id', 'child_of', current_emp.id)]).ids
            )
            rec.is_coach_or_manager = (
                is_sub or
                self.env.user.has_group('discipline_management.group_discipline_manager') or
                self.env.user.has_group('discipline_management.group_discipline_director') or
                self.env.user.has_group('discipline_management.group_discipline_chief') or
                self.env.user.has_group('discipline_management.group_discipline_ceo') or
                self.env.user.has_group('discipline_management.group_discipline_admin')
            )

    is_coach_enforce_allowed = fields.Boolean(
        string='Is Coach Enforcement Allowed',
        compute='_compute_is_coach_enforce_allowed'
    )

    @api.depends('case_action_track', 'severity_level_id', 'punishment_type', 'decided_punishment_type')
    def _compute_is_coach_enforce_allowed(self):
        _, max_rank, allowed_levels = self._get_coach_max_authority()
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
            if rec.case_action_track != 'direct_enforce':
                rec.is_coach_enforce_allowed = False
                continue
            case_punish_rank = punish_ranks.get(rec.punishment_type or rec.decided_punishment_type, 1)
            case_sev_rank = sev_ranks.get(rec.severity_level or (rec.severity_level_id and rec.severity_level_id.code), 1)
            rec.is_coach_enforce_allowed = (case_punish_rank <= max_rank) and (case_sev_rank <= max_rank)

    allowed_severity_level_ids = fields.Many2many(
        'discipline.severity.level',
        compute='_compute_allowed_severity_level_ids',
        string='Allowed Severity Levels'
    )

    subordinate_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_subordinate_employee_ids',
        compute_sudo=True,
        string='Subordinate Employees'
    )

    @api.depends('reported_by_id', 'create_uid')
    def _compute_subordinate_employee_ids(self):
        user = self.env.user
        emp = user.sudo().employee_id
        is_admin_or_officer = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('discipline_management.group_discipline_audit') or
            user.has_group('discipline_management.group_discipline_legal') or
            user.has_group('base.group_system')
        )
        for rec in self:
            if is_admin_or_officer:
                rec.subordinate_employee_ids = self.env['hr.employee'].sudo().search([])
            elif emp:
                subs = self.env['hr.employee'].sudo().search([
                    '|', '|',
                    ('parent_id', '=', emp.id),
                    ('coach_id', '=', emp.id),
                    ('department_id.manager_id', '=', emp.id)
                ])
                rec.subordinate_employee_ids = subs | emp
            else:
                rec.subordinate_employee_ids = self.env['hr.employee']

    @api.depends('offense_id', 'offense_id.line_ids', 'case_action_track')
    def _compute_allowed_severity_level_ids(self):
        all_levels = self.env['discipline.severity.level'].search([])
        _, _, allowed_levels_codes = self._get_coach_max_authority()
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

    @api.depends('employee_id', 'employee_id.is_managerial')
    def _compute_staff_category_display(self):
        for rec in self:
            if rec.employee_id:
                rec.staff_category_display = _('Managerial Staff') if rec.employee_id.is_managerial else _('Non-Managerial Staff')
            else:
                rec.staff_category_display = _('Non-Managerial Staff')

    # Demotion fields
    new_job_id = fields.Many2one('hr.job', string='Demotion Target Job Position', tracking=True)
    new_grade_id = fields.Char(string='Demotion Target Grade Scale', tracking=True)

    # Automatic routing & authority
    required_final_authority = fields.Selection([
        ('direct_manager', 'Coach / Line Manager'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Final Approval Authority', compute='_compute_required_final_authority', store=True, tracking=True)

    incident_date = fields.Date(string='Incident Date', required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(string='Detailed Description of Misconduct', required=True)
    is_system_generated = fields.Boolean(string='System Generated', default=False, readonly=True)
    is_locked_for_committee = fields.Boolean(string='Locked for Committee Review', default=False, tracking=True)

    # Workflow Roles (Segregation of Duties)
    initiator_id = fields.Many2one('res.users', string='Initiator', default=lambda self: self.env.user, readonly=True, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer / Investigator', tracking=True)
    approver_id = fields.Many2one('res.users', string='Final Approver', tracking=True)

    def _default_reported_by_id(self):
        return self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

    reported_by_id = fields.Many2one(
        'hr.employee', 
        string='Reported By', 
        default=_default_reported_by_id,
        readonly=True
    )
    
    reference = fields.Char(string='Reference')
    # State Machine
    state = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated'),
        ('submitted_chief', 'Submitted to Respective Chief'),
        ('ceo_review', 'Under CEO Review'),
        ('investigating', 'Under Audit Investigation'),
        ('chairman_review', 'Committee Chairman Review'),
        ('committee_review', 'Committee Review'),
        ('pending_approval', 'Pending Final Approval'),
        ('enforced', 'Enforced / Finalized'),
        ('appealed', 'Appealed'),
        ('revoked', 'Revoked'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', required=True, tracking=True)

    def _default_sla_target_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.sla_target_days', 10))

    # SLA Tracking
    sla_deadline = fields.Date(string='SLA Resolution Deadline', compute='_compute_sla_deadline', store=True)
    is_sla_exceeded = fields.Boolean(string='SLA Breached', compute='_compute_is_sla_exceeded', store=True, tracking=True)
    sla_target_days = fields.Integer(string='SLA Target (Days)', default=_default_sla_target_days, help='Target resolution days per policy')

    # Associated Records
    investigation_ids = fields.One2many('discipline.investigation', 'case_id', string='Investigations')
    committee_meeting_ids = fields.One2many('discipline.committee.meeting', 'case_id', string='Committee Meetings')
    suspension_ids = fields.One2many('discipline.suspension', 'case_id', string='Suspensions')
    appeal_ids = fields.One2many('discipline.appeal', 'case_id', string='Appeals')
    payroll_penalty_ids = fields.One2many('discipline.payroll.penalty', 'case_id', string='Payroll Penalties')
    deduction_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('appeal_pending', 'Pending Appeal Window Expiry'),
        ('scheduled', 'Scheduled for Payroll'),
        ('transferred', 'Transmitted to Payroll'),
        ('cancelled', 'Cancelled on Appeal'),
    ], string='Financial Deduction Status', default='not_applicable', tracking=True)
    computed_deduction_month = fields.Char(string='Target Payroll Month (Computed)', readonly=True)

    # Flags & Decision Summary
    has_exonerated_investigation = fields.Boolean(
        string='Has Exonerated Investigation',
        compute='_compute_has_exonerated_investigation'
    )

    @api.depends('investigation_ids.state', 'investigation_ids.finding_outcome')
    def _compute_has_exonerated_investigation(self):
        for rec in self:
            rec.has_exonerated_investigation = any(
                inv.state in ('submitted', 'approved') and inv.finding_outcome == 'exonerated'
                for inv in rec.investigation_ids
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
    appeal_count = fields.Integer(string='Appeal Count', compute='_compute_appeal_count')
    suspension_count = fields.Integer(string='Suspension Count', compute='_compute_suspension_count')
    investigation_count = fields.Integer(string='Investigation Count', compute='_compute_investigation_count')
    committee_meeting_count = fields.Integer(string='Meeting Count', compute='_compute_committee_meeting_count')

    has_completed_committee_meeting = fields.Boolean(
        string='Has Completed Committee Meeting',
        compute='_compute_committee_meeting_state'
    )
    has_active_committee_meeting = fields.Boolean(
        string='Has Active Committee Meeting',
        compute='_compute_committee_meeting_state'
    )

    @api.depends('committee_meeting_ids', 'committee_meeting_ids.state')
    def _compute_committee_meeting_state(self):
        for rec in self:
            completed = rec.committee_meeting_ids.filtered(lambda m: m.state == 'completed')
            active = rec.committee_meeting_ids.filtered(lambda m: m.state not in ('completed', 'cancelled'))
            rec.has_completed_committee_meeting = bool(completed)
            rec.has_active_committee_meeting = bool(active)

    @api.depends('employee_id', 'employee_id.job_id', 'severity_level', 'punishment_type')
    def _compute_required_final_authority(self):
        for rec in self:
            job_name = (rec.employee_id.job_id.name or '').lower() if rec.employee_id and rec.employee_id.job_id else ''
            is_executive = any(kw in job_name for kw in ['manager', 'director', 'chief', 'vp', 'executive', 'head'])
            if is_executive or rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                rec.required_final_authority = 'ceo'
            else:
                rec.required_final_authority = 'cpco'

    def _compute_appeal_count(self):
        for rec in self:
            rec.appeal_count = len(rec.appeal_ids)

    def _compute_suspension_count(self):
        for rec in self:
            rec.suspension_count = len(rec.suspension_ids)

    def _compute_investigation_count(self):
        for rec in self:
            rec.investigation_count = len(rec.investigation_ids)

    def _compute_committee_meeting_count(self):
        for rec in self:
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

    @api.depends('delivery_receipt_date', 'final_decision_date', 'state')
    def _compute_appeal_deadline(self):
        ICP = self.env['ir.config_parameter'].sudo()
        appeal_days = int(ICP.get_param('discipline.appeal_window_days', 10))
        for rec in self:
            base_date = rec.delivery_receipt_date or rec.final_decision_date
            if base_date and rec.state in ('enforced', 'appealed', 'closed'):
                rec.appeal_deadline = base_date + timedelta(days=appeal_days)
            else:
                rec.appeal_deadline = False

    @api.depends('appeal_deadline', 'state')
    def _compute_is_appeal_window_open(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state == 'enforced' and rec.appeal_deadline and today <= rec.appeal_deadline:
                rec.is_appeal_window_open = True
            else:
                rec.is_appeal_window_open = False

    is_hr_admin = fields.Boolean(compute='_compute_is_hr_admin', string='Is HR Admin User')

    def _compute_is_hr_admin(self):
        is_admin = self.env.user.has_group('discipline_management.group_discipline_admin') or self.env.user.has_group('base.group_system')
        for rec in self:
            rec.is_hr_admin = is_admin

    is_current_user_employee = fields.Boolean(
        string='Is Current User Subject Employee',
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
    next_appeal_level = fields.Selection([
        ('first', '1st Level Appeal'),
        ('second', '2nd Level Appeal'),
        ('third', '3rd Level Appeal (Final to CEO)'),
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

    def _compute_current_user_roles(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee']
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        audit_user = EmpModel.get_audit_director_user()
        ceo_user = EmpModel.get_ceo_user()
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
        emp = current_user.employee_id
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''

        # 1. CEO User
        is_ceo = bool(
            (ceo_user and current_user.id == ceo_user.id) or
            (emp and (emp.executive_level == 'ceo' or any(k in job_name for k in ['ceo', 'president', 'chief executive']))) or
            current_user.has_group('discipline_management.group_discipline_ceo') or
            is_admin
        )

        # 2. CPCO / Committee Chairman User (Strictly Chairman, not CEO)
        is_cpco = bool(
            (cpco_user and current_user.id == cpco_user.id) or
            (current_user.has_group('discipline_management.group_discipline_cpco') and not (ceo_user and current_user.id == ceo_user.id) and not current_user.has_group('discipline_management.group_discipline_ceo')) or
            is_admin
        )

        # 3. POMD / Committee Secretary User (Strictly Secretary, not CPCO or CEO)
        is_pomd = bool(
            (sec_user and current_user.id == sec_user.id) or
            (current_user.has_group('discipline_management.group_discipline_pomd') and not current_user.has_group('discipline_management.group_discipline_cpco') and not current_user.has_group('discipline_management.group_discipline_ceo')) or
            is_admin
        )

        is_aud = bool((audit_user and current_user.id == audit_user.id) or current_user.has_group('discipline_management.group_discipline_auditor') or is_admin)
        is_dir = bool((emp and (emp.executive_level in ('director', 'chief', 'ceo') or any(k in job_name for k in ['director', 'chief', 'ceo', 'president', 'vp']))) or current_user.has_group('discipline_management.group_discipline_director') or is_admin)
        is_chf_base = bool((emp and (emp.executive_level in ('chief', 'ceo') or any(k in job_name for k in ['chief', 'cpco', 'cfo', 'cio', 'cdo', 'coo', 'vp']))) or (cpco_user and current_user.id == cpco_user.id) or current_user.has_group('discipline_management.group_discipline_chief') or is_admin)

        for rec in self:
            rec.is_pomd_user = is_pomd
            rec.is_auditor_user = is_aud
            rec.is_director_user = is_dir
            rec.is_chief_user = is_chf_base or bool(rec.chief_id and rec.chief_id.id == current_user.id)
            rec.is_ceo_user = is_ceo
            rec.is_cpco_user = is_cpco

            # Check if current user is the employee under this case
            is_emp = bool(
                rec.employee_id and (
                    (rec.employee_id.user_id and rec.employee_id.user_id.id == current_user.id) or
                    (current_user.employee_id and current_user.employee_id.id == rec.employee_id.id) or
                    (hasattr(current_user, 'employee_ids') and rec.employee_id.id in current_user.employee_ids.ids)
                )
            )
            rec.is_current_user_employee = is_emp

            has_pending_appeal = any(a.state in ('draft', 'submitted', 'under_review') for a in rec.appeal_ids)
            is_dismissal = rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal'
            is_emp_inactive = bool(
                rec.employee_id and (
                    not rec.employee_id.active or
                    (rec.employee_id.user_id and not rec.employee_id.user_id.active)
                )
            )
            is_pomd_eligible = (
                is_pomd and
                is_dismissal and
                is_emp_inactive and
                rec.state in ('enforced', 'closed')
            )

            # Determine case origin track for appeal escalation hierarchy
            if rec.initiator_type == 'audit' or rec.case_action_track == 'committee_escalation':
                origin_type = 'committee'
            else:
                initiator_emp = rec.reported_by_id.sudo().employee_id if rec.reported_by_id else False
                if not initiator_emp and rec.employee_id:
                    initiator_emp = rec.employee_id.sudo().coach_id or rec.employee_id.sudo().parent_id
                
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
                    origin_type = 'chief'
                elif level == 'director':
                    origin_type = 'director'
                else:
                    origin_type = 'manager'

            first_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
            second_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
            third_appeal = rec.appeal_ids.filtered(lambda a: a.appeal_level == 'third')

            is_exonerated = (
                rec.appeal_outcome_type == 'exonerated' or
                rec.punishment_type == 'exonerate'
            )

            # 1st Level Appeal Eligibility
            eligible_first = (
                not first_appeal and
                rec.state == 'enforced' and
                rec.is_appeal_window_open and
                not has_pending_appeal and
                not is_exonerated
            )

            # 2nd Level Appeal Eligibility
            eligible_second = False
            if first_appeal and not second_appeal and not has_pending_appeal and rec.state in ('enforced', 'closed') and not is_exonerated:
                f_app = first_appeal[0]
                if f_app.state == 'decided' and f_app.decision_outcome in ('upheld', 'penalty_reduced'):
                    f_exonerated = (
                        f_app.decision_outcome == 'overturned' or
                        f_app.revised_punishment_type == 'exonerate' or
                        (f_app.revised_penalty_percentage == 0.0 and f_app.revised_fine_days == 0.0 and f_app.revised_punishment_type in ('exonerate', False))
                    )
                    if not f_exonerated and origin_type in ('manager', 'director', 'committee'):
                        eligible_second = True

            # 3rd Level Appeal Eligibility (Manager track only)
            eligible_third = False
            if second_appeal and not third_appeal and not has_pending_appeal and rec.state in ('enforced', 'closed') and not is_exonerated:
                s_app = second_appeal[0]
                if s_app.state == 'decided' and s_app.decision_outcome in ('upheld', 'penalty_reduced'):
                    s_exonerated = (
                        s_app.decision_outcome == 'overturned' or
                        s_app.revised_punishment_type == 'exonerate' or
                        (s_app.revised_penalty_percentage == 0.0 and s_app.revised_fine_days == 0.0 and s_app.revised_punishment_type in ('exonerate', False))
                    )
                    if not s_exonerated and origin_type == 'manager':
                        eligible_third = True

            rec.can_submit_first_appeal = is_emp and eligible_first
            rec.can_submit_second_appeal = is_emp and eligible_second
            rec.can_submit_third_appeal = is_emp and eligible_third
            rec.can_submit_appeal = rec.can_submit_first_appeal or rec.can_submit_second_appeal or rec.can_submit_third_appeal

            rec.can_lodge_first_appeal_on_behalf = is_pomd_eligible and eligible_first
            rec.can_lodge_second_appeal_on_behalf = is_pomd_eligible and eligible_second
            rec.can_lodge_third_appeal_on_behalf = is_pomd_eligible and eligible_third
            rec.can_lodge_appeal_on_behalf = rec.can_lodge_first_appeal_on_behalf or rec.can_lodge_second_appeal_on_behalf or rec.can_lodge_third_appeal_on_behalf

            if eligible_first:
                rec.next_appeal_level = 'first'
            elif eligible_second:
                rec.next_appeal_level = 'second'
            elif eligible_third:
                rec.next_appeal_level = 'third'
            else:
                rec.next_appeal_level = False

    @api.onchange('reported_by_id', 'employee_id', 'initiator_type')
    def _onchange_employee_id(self):
        self.reviewer_id = False
        if self.initiator_type == 'manager':
            # Approver is inferred from the REPORTER (the Line Manager initiating the case), NOT the employee under case!
            reporter_emp = self.reported_by_id or self.env.user.employee_id
            if reporter_emp:
                dept_mgr = reporter_emp.department_id.manager_id.user_id if reporter_emp.department_id and reporter_emp.department_id.manager_id else False
                if dept_mgr and dept_mgr != self.env.user:
                    self.approver_id = dept_mgr
                elif reporter_emp.parent_id and reporter_emp.parent_id.user_id and reporter_emp.parent_id.user_id != self.env.user:
                    self.approver_id = reporter_emp.parent_id.user_id
                else:
                    # Fallback to HR Manager / CPCO if the reporter is already the Department Director
                    hr_mgr = self.env['res.users'].search([('name', 'ilike', 'Marta Bekele')], limit=1)
                    self.approver_id = hr_mgr or self.env.user
            else:
                self.approver_id = False
        else:
            self.approver_id = False

        if self.severity_level_id:
            self._onchange_offense_severity_resolve_rules()

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
                ) % (rec.employee_id.name, rec.incident_date, rec.offense_id.name, duplicate[0].name))

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
                    ) % (rec.employee_id.name, rec.severity_level_id.name if rec.severity_level_id else (rec.severity_level or ''),
                         rec.incident_date, same_severity[0].name))

    def _validate_segregation_of_duties(self):
        for rec in self:
            current_user = self.env.user
            # Coach / Line Manager direct enforcement on subordinates for Levels 2-5 is permitted
            is_direct_mgr_enforcement = (
                rec.case_action_track == 'direct_enforce' and
                rec.severity_level != 'level_1' and
                rec.punishment_type != 'dismissal'
            )
            if not is_direct_mgr_enforcement:
                if rec.initiator_id and rec.reviewer_id and rec.initiator_id == rec.reviewer_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Reviewer must be different individuals.'))
                if rec.initiator_id and rec.approver_id and rec.initiator_id == rec.approver_id and rec.case_action_track != 'direct_enforce':
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Approver must be different individuals for escalated cases.'))
                if rec.reviewer_id and rec.approver_id and rec.reviewer_id == rec.approver_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Reviewer and Approver must be different individuals.'))

            if rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                if (not current_user.has_group('discipline_management.group_discipline_admin') and
                    not current_user.has_group('discipline_management.group_discipline_ceo') and
                    not current_user.has_group('discipline_management.group_discipline_cpco')):
                    raise ValidationError(_(
                        'Approval Restriction: Decisions requiring Dismissal / Separation are restricted '
                        'exclusively to authorized executive approvers (CEO / CPCO / Disciplinary Committee).'
                    ))
                if not rec.dismissal_authority_id:
                    rec.dismissal_authority_id = current_user

    @api.model_create_multi
    def create(self, vals_list):
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

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        if not force_write and not self.env.su:
            whitelisted_fields = {
                'state', 'revocation_reason', 'revocation_date', 'revoked_by_id', 'is_revoked',
                'message_follower_ids', 'message_ids', 'activity_ids', 'is_locked_for_committee',
                'approver_id', 'final_decision_date', 'delivery_receipt_date', 'chief_id',
                'escalation_target', 'ceo_assignment_notes', 'occurrence_count',
                'is_escalated_by_active_warning', 'auto_applied_rule_summary',
                'original_punishment_type', 'original_penalty_percentage', 'original_fine_days',
                'punishment_type', 'penalty_percentage', 'fine_days',
                'is_punishment_modified_by_committee', 'is_cash_shortage',
                'statutory_deadline_date', 'is_deadline_exceeded', 'active_penalty_end_date',
                'active_duration_days', 'legal_article_display', 'legal_clause_text',
                'appeal_outcome_type', 'appeal_outcome_display', 'appeal_ids',
                'deduction_status', 'computed_deduction_month', 'payroll_month'
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
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ['enforced', 'closed', 'appealed']:
                raise UserError(_('Preservation Policy Violation: Enforced or finalized disciplinary records cannot be deleted. Use formal Revocation if required.'))
        return super().unlink()

    def action_initiate(self):
        for rec in self:
            if not rec.description:
                raise UserError(_('Detailed Description is mandatory before initiating a case.'))
            rec.with_context(force_write=True).write({'state': 'initiated'})
            rec.message_post(body=_('Disciplinary case initiated for employee %s.') % rec.employee_id.name)

    def _get_group_users(self, xml_id):
        """Retrieve active users belonging to an XML-defined group in modern Odoo 19."""
        group = self.env.ref(xml_id, raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        return group.all_user_ids or group.user_ids or self.env['res.users']

    def action_submit_to_chief(self):
        """Submit the initiated disciplinary case to the respective Chief Officer for review and escalation routing."""
        for rec in self:
            if not rec.chief_id:
                rec.chief_id = rec._find_respective_chief_user()
            rec.with_context(force_write=True).write({
                'state': 'submitted_chief',
                'chief_id': rec.chief_id.id if rec.chief_id else False
            })
            rec.message_post(body=_('Case submitted to Respective Chief (%s) for review.') % (rec.chief_id.name if rec.chief_id else 'Chief Officer'))

    def action_chief_escalate_to_audit(self):
        """Escalate the case to the Audit Directorate for investigation, notifying the CEO simultaneously."""
        for rec in self:
            rec.escalation_target = 'audit'
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('Chief reviewed case and escalated to Audit Directorate for investigation.'))
            
            # 1. Ensure Investigation record exists
            if not rec.investigation_ids:
                self.env['discipline.investigation'].create({
                    'case_id': rec.id,
                    'title': _('Audit Investigation: %s (%s)') % (rec.name, rec.employee_id.name),
                    'applicable_policy': rec.offense_id.name if rec.offense_id else _('Bank Disciplinary Policy'),
                    'summary_findings': rec.description or _('Escalated by Chief for Audit Investigation.'),
                    'investigator_recommendation': _('Pending audit investigation and findings.'),
                })

    def action_chief_escalate_to_ceo(self):
        """Escalate the case directly to the Chief Executive Officer for review."""
        for rec in self:
            rec.escalation_target = 'ceo'
            rec.with_context(force_write=True).write({'state': 'ceo_review'})
            rec.message_post(body=_('Chief escalated case directly to CEO for executive review.'))

    def action_ceo_announce_audit_and_suspend(self):
        """CEO action: formally announce case to Audit Directorate for investigation and instruct Committee Secretary (POMD) to suspend the employee."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_(
                '<strong>CEO Executive Directive:</strong><br/>'
                '1. Case officially assigned to Audit Directorate for formal investigation.<br/>'
                '2. Disciplinary Committee Secretary (POMD) instructed to execute employee precautionary suspension.'
            ))

            # 1. Create linked Investigation record if none exists
            if not rec.investigation_ids:
                self.env['discipline.investigation'].create({
                    'case_id': rec.id,
                    'title': _('Audit Investigation: %s (%s)') % (rec.name, rec.employee_id.name),
                    'applicable_policy': rec.offense_id.name if rec.offense_id else _('Bank Disciplinary Policy'),
                    'summary_findings': rec.description or _('Initiated via Executive Escalation.'),
                    'investigator_recommendation': _('Pending audit investigation and findings.'),
                    'investigator_id': False,
                })

            # 2. Create Precautionary Suspension Record for Committee Secretary (POMD)
            existing_suspension = rec.suspension_ids.filtered(lambda s: s.state != 'revoked')
            if not existing_suspension:
                start_dt = fields.Date.context_today(self)
                end_dt = start_dt + timedelta(days=30)
                self.env['discipline.suspension'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'suspension_type': 'without_pay',
                    'start_date': start_dt,
                    'end_date': end_dt,
                    'reason': _('Precautionary suspension pending audit investigation per CEO directive.'),
                    'initiating_unit': 'directorate',
                    'state': 'draft',
                })

    def action_ceo_assign_to_audit(self):
        """Backward compatibility alias for action_ceo_announce_audit_and_suspend."""
        return self.action_ceo_announce_audit_and_suspend()

    def action_ceo_forward_to_committee_chair(self):
        """CEO reviews audit report and forwards case to Disciplinary Committee Chairman (CPCO)."""
        for rec in self:
            if not (rec.is_ceo_user or rec.is_hr_admin):
                raise UserError(_('Authority Restriction: Only the Chief Executive Officer (CEO) can forward cases to the Disciplinary Committee Chairman.'))
            rec.with_context(force_write=True).write({
                'state': 'chairman_review',
            })
            cpco_user = self.env['hr.employee'].sudo().get_cpco_user()
            cpco_name = cpco_user.name if cpco_user else _('Chief People & Culture Officer')
            rec.message_post(body=_(
                'Case forwarded by Chief Executive Officer (CEO: %s) to Disciplinary Committee Chairman (CPCO: %s) for committee review.'
            ) % (self.env.user.name, cpco_name))

    def action_chair_forward_to_secretary(self):
        """Disciplinary Committee Chairman (CPCO) reviews case and forwards to Committee Secretary (POMD) for scheduling hearing."""
        for rec in self:
            if not (rec.is_cpco_user or rec.is_hr_admin):
                raise UserError(_('Authority Restriction: Only the Disciplinary Committee Chairman (CPCO) can forward cases to the Committee Secretary for meeting scheduling.'))
            rec.with_context(force_write=True).write({
                'state': 'committee_review',
                'is_locked_for_committee': True,
            })
            sec_user = self.env['hr.employee'].sudo().get_secretary_user()
            sec_name = sec_user.name if sec_user else _('People Operations Management Director')
            rec.message_post(body=_(
                'Case referred by Disciplinary Committee Chairman (%s) to Committee Secretary (%s) to schedule the committee hearing.'
            ) % (self.env.user.name, sec_name))

    def action_ceo_forward_to_committee(self):
        """Forward directly to committee chair."""
        return self.action_ceo_forward_to_committee_chair()

    def action_ceo_endorse_exoneration(self):
        """CEO Executive Action: officially endorse Audit Directorate Exoneration findings and instruct POMD to revoke suspension and reinstate employee."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'closed'})
            rec.message_post(body=_(
                '<strong>CEO Executive Action — Exoneration Endorsed:</strong><br/>'
                'The CEO has reviewed and officially endorsed the Audit Directorate investigation findings concluding no disciplinary liability. '
                'The case is formally closed as Exonerated with immediate effect.'
            ))
            
            # Revoke linked suspensions
            for suspension in rec.suspension_ids.filtered(lambda s: s.state != 'revoked'):
                suspension.action_revoke_exonerated()

    def action_start_investigation(self):
        for rec in self:
            rec.reviewer_id = self.env.user
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('Investigation process started by %s.') % self.env.user.name)

    def action_send_to_committee(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'committee_review', 'is_locked_for_committee': True})
            rec.message_post(body=_('Case submitted for Disciplinary Committee Review and locked for feedback.'))

    def action_committee_feedback_received(self):
        """Unlock case when committee feedback is received and notify HR officer."""
        for rec in self:
            rec.with_context(force_write=True).write({'is_locked_for_committee': False})
            rec.message_post(body=_('Committee feedback received. Case unlocked for review.'))

    def action_schedule_committee_meeting(self):
        """Open form to schedule a Disciplinary Committee Meeting pre-populated with panel members."""
        self.ensure_one()
        EmpModel = self.env['hr.employee'].sudo()
        emp = self.employee_id
        
        # 1. Chairperson: CPCO
        cpco_user = EmpModel.get_cpco_user()
        
        # 2. Respective Director
        resp_dir_user = False
        if emp and emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
            resp_dir_user = emp.department_id.manager_id.user_id
        elif emp:
            for sup in emp.get_supervisor_chain():
                if sup.executive_level in ('director', 'chief', 'ceo') and sup.user_id:
                    resp_dir_user = sup.user_id
                    break

        # 3. Legal Member
        legal_user = EmpModel.get_legal_user()
        
        # 4. Secretary: POMD
        sec_user = EmpModel.get_secretary_user()
        
        # 5. Union Rep
        union_user = EmpModel.get_union_user()

        member_ids = []
        for u in [cpco_user, resp_dir_user, legal_user, sec_user, union_user]:
            if u:
                member_ids.append(u.id)

        default_vals = {
            'default_case_id': self.id,
            'default_committee_chair_id': cpco_user.id if cpco_user else False,
            'default_respective_director_id': resp_dir_user.id if resp_dir_user else False,
            'default_legal_director_id': legal_user.id if legal_user else False,
            'default_pomd_secretary_id': sec_user.id if sec_user else False,
            'default_labour_union_rep_id': union_user.id if union_user else False,
            'default_member_ids': [(6, 0, member_ids)],
            'default_present_members_count': len(member_ids),
        }

        return {
            'name': _('Schedule Committee Meeting — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'view_mode': 'form',
            'target': 'current',
            'context': default_vals,
        }

    def action_open_active_committee_meeting(self):
        """Open the active/in-progress committee meeting linked to this case."""
        self.ensure_one()
        meeting = self.committee_meeting_ids.filtered(lambda m: m.state not in ('completed', 'cancelled'))[:1]
        if not meeting:
            meeting = self.committee_meeting_ids[:1]
        if not meeting:
            return self.action_schedule_committee_meeting()
        return {
            'name': _('Committee Meeting — %s') % meeting.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'res_id': meeting.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_submit_for_approval(self):
        recom_to_punishment = {
            'dismissal': 'dismissal',
            'final_warning': 'final_warning_penalty',
            'second_warning': 'second_warning_penalty',
            'first_warning': 'first_warning_penalty',
            'verbal_warning': 'verbal_warning',
            'demotion': 'demotion',
            'exonerate': 'exonerate',
            'custom': 'custom',
        }
        for rec in self:
            completed_meeting = rec.committee_meeting_ids.filtered(lambda m: m.state == 'completed' and m.final_recommendation)
            if not completed_meeting and not rec.decided_punishment_type:
                raise UserError(_('A completed Committee Meeting with a finalized recommendation is required before submitting for approval.'))
            if not rec.decided_punishment_type and not rec.punishment_type:
                if completed_meeting:
                    punish_val = recom_to_punishment.get(completed_meeting[-1].final_recommendation, completed_meeting[-1].final_recommendation)
                    rec.with_context(force_write=True).write({
                        'decided_punishment_type': punish_val,
                        'punishment_type': punish_val,
                    })
                else:
                    raise UserError(_('Please assign the Committee Decided Punishment before submitting for final executive approval.'))
            rec.with_context(force_write=True).write({'state': 'pending_approval', 'is_locked_for_committee': False})
            rec.message_post(body=_('Disciplinary case and decided punishment submitted for final executive approval.'))

    def action_return_revision(self):
        """Return case to Initiator / Line Manager for revision."""
        for rec in self:
            if rec.state not in ['pending_approval', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Only cases under review/pending approval can be returned for revision.'))
            rec.with_context(force_write=True).write({'state': 'draft'})
            rec.message_post(body=_('Case returned to Initiator for revision by %s.') % self.env.user.name)

    def action_reject(self):
        """Reject disciplinary case."""
        for rec in self:
            if rec.state not in ['pending_approval', 'initiated', 'investigating', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Case cannot be rejected in its current state.'))
            rec.with_context(force_write=True).write({'state': 'closed'})
            rec.message_post(body=_('Disciplinary case rejected and closed by %s.') % self.env.user.name)

    def action_acknowledge_receipt(self):
        """Record official delivery and acknowledgment of the disciplinary notice, starting the appeal window."""
        for rec in self:
            rec.delivery_receipt_date = fields.Date.context_today(self)
            rec.message_post(body=_('Disciplinary decision letter delivery acknowledged on %s. 10-day appeal countdown is active.') % rec.delivery_receipt_date)

    def action_approve_and_enforce(self):
        """Enforces the disciplinary penalty (Coach/Manager direct enforcement for Levels 2-5, or Committee/Executive enforcement)."""
        for rec in self:
            current_user = self.env.user
            # For Coach Direct Enforcement track (not formal escalation)
            if rec.case_action_track == 'direct_enforce':
                if not rec.severity_level_id:
                    raise UserError(_('Severity Level is required for Coach Direct Enforcement.'))
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
                case_punish_rank = punish_ranks.get(rec.punishment_type or rec.decided_punishment_type, 1)
                case_sev_rank = sev_ranks.get(rec.severity_level or (rec.severity_level_id and rec.severity_level_id.code), 1)

                is_exceeded = (case_punish_rank > max_rank) or (case_sev_rank > max_rank)
                if is_exceeded:
                    if (not current_user.has_group('discipline_management.group_discipline_admin') and 
                        not current_user.has_group('discipline_management.group_discipline_ceo') and 
                        not current_user.has_group('discipline_management.group_discipline_cpco')):
                        
                        cfg_display = dict(self.env['res.config.settings']._fields['discipline_coach_max_punishment'].selection).get(cfg_punish, cfg_punish) if 'discipline_coach_max_punishment' in self.env['res.config.settings']._fields else cfg_punish
                        raise UserError(_(
                            'Coach Direct Enforcement Authority Limit Exceeded:\n\n'
                            'Per Bank Disciplinary Governance Configuration, Direct Coaches / Line Managers are authorized to directly enforce sanctions up to: %s.\n\n'
                            'This disciplinary case involves: %s (%s), which exceeds your direct enforcement authority.\n'
                            'Please route/escalate this case to the Respective Chief / Executive Disciplinary Committee.'
                        ) % (cfg_display, rec.severity_level_id.name or rec.severity_level, rec.punishment_type or rec.decided_punishment_type))
            else:
                if not rec.severity_level_id and not rec.decided_punishment_type and not rec.punishment_type:
                    raise UserError(_('Severity Level and Final Decided Punishment must be assigned before enforcing this case.'))

            rec.approver_id = current_user
            rec._validate_segregation_of_duties()

            # Verify linked committee meetings are completed with quorum and signoff (only if committee route)
            if rec.committee_meeting_ids:
                for meeting in rec.committee_meeting_ids:
                    if meeting.state != 'completed' or not meeting.director_signed_off or not meeting.is_quorum_met:
                        raise UserError(_('Cannot enforce case decision. Linked committee meeting (%s) must be in Completed state with director sign-off and valid quorum.') % meeting.name)

            rec.final_decision_date = fields.Date.context_today(self)
            if not rec.delivery_receipt_date:
                rec.delivery_receipt_date = rec.final_decision_date
            rec.with_context(force_write=True).write({'state': 'enforced'})

            # Update employee disciplinary record and set internal mobility restrictions
            is_ineligible = (
                rec.severity_level in ['level_1', 'level_2'] or
                rec.punishment_type in ['dismissal', 'demotion', 'final_warning_penalty']
            )
            rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                'active_disciplinary_action': True,
                'is_ineligible_for_promotion_transfer': is_ineligible,
                'disciplinary_warning_count': rec.employee_id.disciplinary_warning_count + 1,
                'last_disciplinary_date': rec.final_decision_date,
            })

            # Demotion handling (preserves basic salary while downgrading position scale/allowances)
            if rec.punishment_type == 'demotion' or rec.decided_punishment_type == 'demotion':
                rec.action_apply_demotion()

            # Appeal-Aware Deduction Lock: Financial penalties are held in abeyance during the 10-day appeal window
            has_financial_penalty = (
                (not rec.is_managerial and rec.penalty_percentage > 0.0) or
                (rec.is_managerial and rec.fine_days > 0.0) or
                bool(rec.suspension_ids.filtered(lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed']))
            )
            if has_financial_penalty:
                rec.with_context(force_write=True).write({'deduction_status': 'appeal_pending'})
                rec.message_post(body=_(
                    'Financial deductions (salary fine / percentage deduction) are held in abeyance pending expiration of the 10-calendar-day statutory appeal window (Appeal Deadline: %s).'
                ) % (rec.appeal_deadline or _('10 days from receipt')))
            else:
                rec.with_context(force_write=True).write({'deduction_status': 'not_applicable'})

            # Dismissal Handling & Separation Workflow
            if rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                rec.action_approve_dismissal()

            # Auto-attach the official warning letter PDF and notify employee
            rec._attach_warning_letter()

    @api.model
    def _compute_target_payroll_month(self, closure_date):
        """
        Computes target payroll month based on closure date and mid-month (15th) cutoff rule:
        - Closure Day < 15: Current Month
        - Closure Day >= 15: Next Month (handles Dec -> Jan year transition)
        Returns tuple: (month_str '01'-'12', target_year int)
        """
        if not closure_date:
            closure_date = fields.Date.today()
        if closure_date.day < 15:
            target_month = closure_date.month
            target_year = closure_date.year
        else:
            if closure_date.month == 12:
                target_month = 1
                target_year = closure_date.year + 1
            else:
                target_month = closure_date.month + 1
                target_year = closure_date.year
        return str(target_month), target_year

    def action_process_appeal_window_deductions(self):
        """
        Evaluates and generates scheduled payroll deductions for cases whose appeal window has passed or concluded.
        Applies the mid-month cutoff rule (Day 15) to determine the target payroll month.
        """
        from datetime import date
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state not in ('enforced', 'closed', 'appealed') or rec.deduction_status not in ('appeal_pending', 'scheduled'):
                continue

            # If an active appeal is in progress, deductions remain deferred
            active_appeals = rec.appeal_ids.filtered(lambda a: a.state not in ('decided', 'revoked', 'closed', 'cancelled'))
            if active_appeals:
                continue

            # Check if 10-day appeal window is still open
            if rec.state == 'enforced' and rec.appeal_deadline and today <= rec.appeal_deadline and not rec.appeal_ids:
                continue

            has_financial_penalty = (
                (not rec.is_managerial and rec.penalty_percentage > 0.0) or
                (rec.is_managerial and rec.fine_days > 0.0) or
                bool(rec.suspension_ids.filtered(lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed']))
            )
            if not has_financial_penalty:
                rec.deduction_status = 'not_applicable'
                continue

            # Determine closure date
            if rec.appeal_ids:
                decided_appeals = rec.appeal_ids.filtered(lambda a: a.state in ('decided', 'closed'))
                latest_decision = decided_appeals.sorted('decision_date', reverse=True)
                closure_date = latest_decision[0].decision_date if (latest_decision and latest_decision[0].decision_date) else (rec.appeal_deadline or today)
            else:
                closure_date = rec.appeal_deadline or today

            target_month, target_year = self._compute_target_payroll_month(closure_date)
            deduction_date = date(target_year, int(target_month), 1)

            rec.payroll_month = target_month
            rec.computed_deduction_month = target_month

            existing_penalties = self.env['discipline.payroll.penalty'].search([('case_id', '=', rec.id)])
            month_dict = dict(rec._fields['payroll_month'].selection) if 'payroll_month' in rec._fields else {}
            month_display = month_dict.get(target_month, str(target_month))

            if existing_penalties:
                existing_penalties.filtered(lambda p: p.state == 'pending').write({
                    'effective_date': deduction_date,
                    'payroll_month': target_month,
                })
            else:
                # 1. Percentage deduction for non-managerial staff
                if not rec.is_managerial and rec.penalty_percentage > 0.0:
                    self.env['discipline.payroll.penalty'].create({
                        'case_id': rec.id,
                        'employee_id': rec.employee_id.id,
                        'penalty_type': 'percentage',
                        'penalty_percentage': rec.penalty_percentage,
                        'effective_date': deduction_date,
                        'payroll_month': target_month,
                        'state': 'pending',
                        'notes': _('Scheduled percentage penalty of %s%% for Case %s (Target Payroll Month: %s - Post Appeal Window).') % (
                            rec.penalty_percentage, rec.name, month_display
                        )
                    })
                # 2. Daily wage unit deduction for managerial staff
                elif rec.is_managerial and rec.fine_days > 0.0:
                    self.env['discipline.payroll.penalty'].create({
                        'case_id': rec.id,
                        'employee_id': rec.employee_id.id,
                        'penalty_type': 'managerial',
                        'managerial_days': int(rec.fine_days),
                        'effective_date': deduction_date,
                        'payroll_month': target_month,
                        'state': 'pending',
                        'notes': _('Scheduled managerial penalty of %d day(s) for Case %s (Target Payroll Month: %s - Post Appeal Window).') % (
                            int(rec.fine_days), rec.name, month_display
                        )
                    })

                # 3. Unpaid suspension deductions
                active_swp = rec.suspension_ids.filtered(
                    lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed']
                )
                for susp in active_swp:
                    self.env['discipline.payroll.penalty'].create({
                        'case_id': rec.id,
                        'employee_id': rec.employee_id.id,
                        'penalty_type': 'suspension_without_pay',
                        'suspension_id': susp.id,
                        'suspension_days': susp.working_days_count,
                        'effective_date': deduction_date,
                        'payroll_month': target_month,
                        'state': 'pending',
                        'notes': _('Scheduled without-pay suspension deduction for %d days for Case %s (Target Payroll Month: %s - Post Appeal Window).') % (
                            susp.working_days_count, rec.name, month_display
                        )
                    })

            rec.deduction_status = 'scheduled'
            rec.message_post(
                body=_('Appeal window closed on %s. In accordance with the mid-month cutoff rule (Day 15), disciplinary financial deduction is scheduled for <b>%s</b> payroll.') % (
                    closure_date, month_display
                )
            )

    _process_appeal_window_deductions = action_process_appeal_window_deductions

    @api.model
    def _cron_process_appeal_window_deductions(self):
        """Ultra-lightweight off-peak daily cron: sweeps enforced cases whose appeal window has expired and schedules deductions."""
        today = fields.Date.today()
        cases = self.search([
            ('state', 'in', ['enforced', 'closed']),
            ('deduction_status', '=', 'appeal_pending'),
            ('appeal_deadline', '<', today),
        ])
        if cases:
            cases._process_appeal_window_deductions()

    def action_coach_exonerate_attendance(self):
        """Allows direct coach / manager to exonerate an auto-initiated attendance case upon reviewing valid justification."""
        self.ensure_one()
        if not self.is_system_generated:
            raise UserError(_('Only system-generated attendance cases can be exonerated directly by the coach.'))
        if self.state not in ('draft', 'initiated'):
            raise UserError(_('Case cannot be exonerated in current state.'))
        
        self.write({
            'state': 'closed',
            'is_revoked': True,
            'revocation_reason': _('Exonerated by Direct Coach / Manager upon review of attendance justification.'),
            'revocation_date': fields.Date.context_today(self),
            'revoked_by_id': self.env.user.id,
            'deduction_status': 'cancelled',
            'punishment_type': 'exonerate',
            'penalty_percentage': 0.0,
            'fine_days': 0.0,
        })
        self.message_post(body=_('Attendance disciplinary case exonerated and closed by Direct Coach (%s). Zero penalty applied.') % self.env.user.name)

    def action_print_warning_letter(self):
        """Direct action to print or download the official disciplinary warning / decision letter."""
        self.ensure_one()
        return self.env.ref('discipline_management.action_report_disciplinary_warning_letter').report_action(self)

    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official Bunna Bank logo for reliable QWeb PDF rendering."""
        import base64
        import os

        # First check local module static directory
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        gender = getattr(self.employee_id, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(self.employee_id, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def get_formatted_employee_name(self):
        """Returns formatted full recipient employee name with salutation."""
        self.ensure_one()
        emp_name = self.employee_id.name or _('Employee')
        salutation = self.get_salutation_label()
        return f"{salutation} {emp_name}"

    def get_salutation_title_and_first_name(self):
        """Returns formal salutation and first name for letter opening."""
        self.ensure_one()
        emp_name = self.employee_id.name or _('Employee')
        salutation = self.get_salutation_label()
        first_name = emp_name.split()[0] if emp_name else _('Employee')
        return f"{salutation} {first_name}"

    def get_sanction_display_text(self):
        """Returns clean human-readable sanction and financial penalty description."""
        self.ensure_one()
        sanction_name = dict(self._fields['punishment_type'].selection).get(
            self.punishment_type, str(self.punishment_type or '')
        )
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(f"{self.penalty_percentage}% monthly basic salary deduction")
        if self.fine_days > 0.0:
            penalty_details.append(f"{int(self.fine_days)} day(s) salary fine")
        
        if penalty_details:
            return f"{sanction_name} with {' and '.join(penalty_details)}"
        return sanction_name

    def get_signatory_name(self):
        """Returns the formal signatory name based on action track."""
        self.ensure_one()
        if self.case_action_track == 'direct_enforce':
            return (self.initiator_id.name or self.reported_by_id.name or self.approver_id.name or self.env.user.name)
        return (self.approver_id.name or self.env.user.name)

    def get_signatory_title(self):
        """Returns formal signatory job / authority title."""
        self.ensure_one()
        if self.case_action_track == 'direct_enforce':
            return _("Line Manager / Direct Coach")
        if self.approver_id and hasattr(self.approver_id, 'has_group') and self.approver_id.has_group('discipline_management.group_discipline_ceo'):
            return _("Chief Executive Officer")
        return _("Chief People & Culture Officer / Authorized Executive")

    def get_signatory_company(self):
        return _("Bunna Bank S.C.")

    def get_discipline_letter_cc_lines(self):
        """Returns formatted CC distribution lines for the official letter."""
        self.ensure_one()
        lines = [
            _("People Operations Management Directorate (POMD) - Personnel File"),
        ]
        if self.department_id:
            lines.append(f"{self.department_id.name} / Respective Directorate")
        else:
            lines.append(_("Respective Directorate / Branch Management"))
        lines.append(_("Internal Audit Directorate"))
        if self.employee_id:
            lines.append(f"{self.employee_id.name} (Subject Employee)")
        return lines

    def _attach_warning_letter(self):
        """Generate and auto-attach the official warning letter PDF and send targeted notification to the employee."""
        self.ensure_one()
        report_ref = 'discipline_management.action_report_disciplinary_warning_letter'
        attachment = False
        try:
            report = self.env.ref(report_ref, raise_if_not_found=True)
            pdf_content, _unused_format = self.env['ir.actions.report']._render_qweb_pdf(
                report, [self.id]
            )
            filename = 'Official_Warning_Letter_%s.pdf' % self.name.replace('/', '_')
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': pdf_content,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
        except Exception:
            import base64
            body_text = (
                'OFFICIAL DISCIPLINARY WARNING NOTICE\n'
                '====================================\n'
                'Case Reference : %s\n'
                'Employee       : %s\n'
                'Decision Date  : %s\n'
                'Offense        : %s\n'
                'Penalty        : %s\n\n'
                'Please refer to the official signed copy in the personnel file.'
            ) % (self.name, self.employee_id.name, self.final_decision_date,
                 self.offense_id.name if self.offense_id else 'N/A', self.punishment_type)
            attachment = self.env['ir.attachment'].create({
                'name': 'Official_Warning_Letter_%s.txt' % self.name.replace('/', '_'),
                'type': 'binary',
                'datas': base64.b64encode(body_text.encode('utf-8')),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'text/plain',
            })

        # Determine issuance track and role
        is_direct = self.case_action_track == 'direct_enforce'
        issuer_name = (self.initiator_id.name or self.reported_by_id.name or self.approver_id.name or self.env.user.name) if is_direct else (self.approver_id.name or self.env.user.name)
        issuer_role = _('Line Manager / Coach') if is_direct else _('Disciplinary Committee / Authorized Executive Approver')
        
        sanction_name = dict(self._fields['punishment_type'].selection).get(self.punishment_type, str(self.punishment_type or ''))
        penalty_details = []
        if self.penalty_percentage > 0.0:
            penalty_details.append(_('%s%% Salary Deduction') % self.penalty_percentage)
        if self.fine_days > 0.0:
            penalty_details.append(_('%d Day(s) Salary Fine') % int(self.fine_days))
        penalty_sub = (' (' + ', '.join(penalty_details) + ')') if penalty_details else ''

        body_html = _(
            '<p><strong>Official Disciplinary Decision &amp; Warning Notice</strong></p>'
            '<p>A formal disciplinary action has been enforced by <strong>%s</strong> (%s).</p>'
            '<ul>'
            '<li><strong>Case Reference:</strong> %s</li>'
            '<li><strong>Employee:</strong> %s</li>'
            '<li><strong>Misconduct Clause:</strong> %s</li>'
            '<li><strong>Enforced Sanction:</strong> %s%s</li>'
            '<li><strong>Decision Date:</strong> %s</li>'
            '<li><strong>Statutory Appeal Deadline:</strong> %s (10-calendar-day window)</li>'
            '</ul>'
            '<p>The official warning letter has been generated and attached. You can view, download, or print the document directly from this case.</p>'
        ) % (
            issuer_name,
            issuer_role,
            self.name,
            self.employee_id.name,
            self.offense_id.name if self.offense_id else _('Misconduct Clause'),
            sanction_name,
            penalty_sub,
            self.final_decision_date or fields.Date.context_today(self),
            self.appeal_deadline or _('10 days from receipt')
        )

        partner_ids = []
        if self.employee_id.user_id and self.employee_id.user_id.partner_id:
            partner_ids.append(self.employee_id.user_id.partner_id.id)
        if self.reported_by_id and self.reported_by_id.user_id and self.reported_by_id.user_id.partner_id:
            partner_ids.append(self.reported_by_id.user_id.partner_id.id)

        self.message_post(
            body=body_html,
            partner_ids=list(set(partner_ids)),
            attachment_ids=[attachment.id] if attachment else [],
            subtype_xmlid='mail.mt_comment'
        )
        return attachment

    def action_apply_demotion(self):
        """Execute demotion by reassigning job position while preserving basic salary scale."""
        for rec in self:
            if rec.new_job_id:
                rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({'job_id': rec.new_job_id.id})
                VersionModel = self.env.get('hr.version')
                if VersionModel:
                    versions = VersionModel.sudo().search([('employee_id', '=', rec.employee_id.id)])
                    if versions:
                        versions.write({'job_id': rec.new_job_id.id})
                rec.message_post(body=_('Demotion enforced: Reassigned to position %s. Basic wage/salary scale preserved.') % rec.new_job_id.name)

    def action_approve_dismissal(self):
        """Execute final approval of Level 1 Dismissal, triggering separation and revoking system access."""
        for rec in self:
            rec._process_employee_dismissal()

    def _process_employee_dismissal(self):
        """Handle separation and access revocation with extensible hook."""
        for rec in self:
            emp = rec.employee_id
            write_vals = {'active': False}
            departure_reason = self.env.ref('hr.departure_fired', raise_if_not_found=False)
            if departure_reason and 'departure_reason_id' in emp._fields:
                write_vals['departure_reason_id'] = departure_reason.id
            if 'departure_date' in emp._fields:
                write_vals['departure_date'] = rec.final_decision_date
            if 'departure_description' in emp._fields:
                write_vals['departure_description'] = _('Dismissed under Disciplinary Case %s on %s.') % (rec.name, rec.final_decision_date)
            emp.sudo().with_context(no_leave_resource_calendar_update=True).write(write_vals)
            if emp.user_id:
                emp.user_id.sudo().write({'active': False})
                rec.message_post(body=_('System user access for user %s disabled due to dismissal.') % emp.user_id.name)
            
            rec._on_employee_dismissed(emp)

    def _on_employee_dismissed(self, employee):
        """Extensible event hook for separation management module integration."""
        Separation = self.env.get('hr.separation') or self.env.get('employee.separation')
        if Separation:
            Separation.sudo().create({
                'employee_id': employee.id,
                'separation_type': 'dismissal',
                'case_id': self.id,
                'reason': _('Disciplinary dismissal under Case %s.') % self.name,
            })

    def action_open_revocation_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Revocation Authority Violation: Only HR Administrators can initiate case revocation.'))
        return {
            'name': _('Revoke Disciplinary Case'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.revocation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id}
        }

    def _action_open_appeal_wizard(self, level='first', is_on_behalf=False):
        self.ensure_one()
        parent_appeal = False
        if level == 'second':
            first_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'first')
            if not first_appeal:
                raise UserError(_('A 1st Level Appeal must exist before submitting a 2nd Level Appeal.'))
            parent_appeal = first_appeal[0]
            title = _('Submit 2nd Level Appeal for Case %s') % self.name
        elif level == 'third':
            second_appeal = self.appeal_ids.filtered(lambda a: a.appeal_level == 'second')
            if not second_appeal:
                raise UserError(_('A 2nd Level Appeal must exist before submitting a 3rd Level Appeal.'))
            parent_appeal = second_appeal[0]
            title = _('Submit 3rd Level Appeal (To CEO) for Case %s') % self.name
        else:
            title = _('Submit Appeal for Case %s') % self.name

        if is_on_behalf:
            title = _('Lodge %s Level Appeal on Behalf of %s') % (level.capitalize(), self.employee_id.name)

        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_parent_appeal_id': parent_appeal.id if parent_appeal else False,
                'default_appeal_level': level,
                'default_is_submitted_on_behalf': is_on_behalf,
                'default_submitted_by_id': self.env.user.id if is_on_behalf else False,
                'default_submission_date': fields.Date.context_today(self),
            }
        }

    def action_create_appeal(self):
        self.ensure_one()
        current_user = self.env.user
        is_emp = bool(
            (self.employee_id.user_id and self.employee_id.user_id.id == current_user.id) or
            (current_user.employee_id and current_user.employee_id.id == self.employee_id.id) or
            (hasattr(current_user, 'employee_ids') and self.employee_id.id in current_user.employee_ids.ids)
        )
        if not is_emp:
            raise UserError(_('Appeal Access Restriction: Direct appeals can only be submitted by the employee (%s) subject to this disciplinary case.') % self.employee_id.name)
        
        if self.can_submit_third_appeal:
            return self.action_create_third_appeal()
        elif self.can_submit_second_appeal:
            return self.action_create_second_appeal()
        
        if not self.is_appeal_window_open:
            raise UserError(_(
                'Appeal Window Closed: The 10-calendar-day appeal submission window has expired. '
                'Appeal deadline was %s.'
            ) % (self.appeal_deadline or 'N/A'))
        
        return self._action_open_appeal_wizard(level='first', is_on_behalf=False)

    def action_create_second_appeal(self):
        self.ensure_one()
        current_user = self.env.user
        is_emp = bool(
            (self.employee_id.user_id and self.employee_id.user_id.id == current_user.id) or
            (current_user.employee_id and current_user.employee_id.id == self.employee_id.id) or
            (hasattr(current_user, 'employee_ids') and self.employee_id.id in current_user.employee_ids.ids)
        )
        if not is_emp:
            raise UserError(_('Appeal Access Restriction: Direct appeals can only be submitted by the employee (%s) subject to this disciplinary case.') % self.employee_id.name)
        return self._action_open_appeal_wizard(level='second', is_on_behalf=False)

    def action_create_third_appeal(self):
        self.ensure_one()
        current_user = self.env.user
        is_emp = bool(
            (self.employee_id.user_id and self.employee_id.user_id.id == current_user.id) or
            (current_user.employee_id and current_user.employee_id.id == self.employee_id.id) or
            (hasattr(current_user, 'employee_ids') and self.employee_id.id in current_user.employee_ids.ids)
        )
        if not is_emp:
            raise UserError(_('Appeal Access Restriction: Direct appeals can only be submitted by the employee (%s) subject to this disciplinary case.') % self.employee_id.name)
        return self._action_open_appeal_wizard(level='third', is_on_behalf=False)

    def action_create_appeal_on_behalf(self):
        self.ensure_one()
        current_user = self.env.user
        if not current_user.has_group('discipline_management.group_discipline_pomd') and not current_user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Authority Restriction: Only the People Operations Management Directorate (POMD) or HR Administrator can lodge an appeal on behalf of an employee.'))
        if self.can_lodge_third_appeal_on_behalf:
            return self.action_create_third_appeal_on_behalf()
        elif self.can_lodge_second_appeal_on_behalf:
            return self.action_create_second_appeal_on_behalf()
        return self._action_open_appeal_wizard(level='first', is_on_behalf=True)

    def action_create_second_appeal_on_behalf(self):
        self.ensure_one()
        current_user = self.env.user
        if not current_user.has_group('discipline_management.group_discipline_pomd') and not current_user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Authority Restriction: Only the People Operations Management Directorate (POMD) or HR Administrator can lodge an appeal on behalf of an employee.'))
        return self._action_open_appeal_wizard(level='second', is_on_behalf=True)

    def action_create_third_appeal_on_behalf(self):
        self.ensure_one()
        current_user = self.env.user
        if not current_user.has_group('discipline_management.group_discipline_pomd') and not current_user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Authority Restriction: Only the People Operations Management Directorate (POMD) or HR Administrator can lodge an appeal on behalf of an employee.'))
        return self._action_open_appeal_wizard(level='third', is_on_behalf=True)

    def action_view_appeals(self):
        self.ensure_one()
        return {
            'name': _('Appeals — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def action_view_investigations(self):
        self.ensure_one()
        return {
            'name': _('Audit Investigations — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.investigation',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {
                'default_case_id': self.id,
                'default_employee_id': self.employee_id.id if self.employee_id else False,
                'default_offense_id': self.offense_id.id if self.offense_id else False,
            },
        }

    def action_view_committee_meetings(self):
        self.ensure_one()
        return {
            'name': _('Committee Meetings — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.meeting',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def action_view_suspensions(self):
        self.ensure_one()
        return {
            'name': _('Suspensions — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.suspension',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def action_audit_submit_to_ceo(self):
        """Internal Audit Directorate submits audit-initiated case directly to CEO."""
        for rec in self:
            rec.write({
                'state': 'ceo_review',
                'case_action_track': 'audit_referral',
            })
            rec.message_post(body=_('Case %s submitted by Internal Audit Directorate directly to Chief Executive Officer (CEO) for executive review.') % rec.name)

    @api.model
    def get_discipline_analytics_payload(self, date_from=None, date_to=None):
        """Public API method returning aggregated disciplinary statistics for external HR Analytics integration."""
        domain = []
        if date_from:
            domain.append(('incident_date', '>=', date_from))
        if date_to:
            domain.append(('incident_date', '<=', date_to))
            
        cases = self.search(domain)
        total_cases = len(cases)
        
        by_state = {}
        by_severity = {}
        by_department = {}
        by_punishment = {}
        
        for c in cases:
            st = c.state or 'unknown'
            by_state[st] = by_state.get(st, 0) + 1
            
            sev = c.severity_level or 'unclassified'
            by_severity[sev] = by_severity.get(sev, 0) + 1
            
            dept = c.department_id.name if c.department_id else 'Unassigned'
            by_department[dept] = by_department.get(dept, 0) + 1
            
            pish = c.punishment_type or 'none'
            by_punishment[pish] = by_punishment.get(pish, 0) + 1
            
        return {
            'total_cases': total_cases,
            'cases_by_state': by_state,
            'cases_by_severity': by_severity,
            'cases_by_department': by_department,
            'cases_by_punishment': by_punishment,
        }

    @api.model
    def _cron_check_sla_escalations(self):
        today = fields.Date.context_today(self)
        breached_cases = self.search([
            ('state', 'in', ['initiated', 'investigating', 'committee_review', 'pending_approval']),
            ('sla_deadline', '<', today),
            ('is_sla_exceeded', '=', True)
        ])
        for case in breached_cases:
            case.message_post(
                body=_('SLA BREACH ALERT: Disciplinary Case %s has exceeded its resolution SLA deadline of %s.') % (case.name, case.sla_deadline),
                message_type='notification'
            )

    @api.model
    def _cron_check_appeal_window_expiry(self):
        today = fields.Date.context_today(self)
        expired_cases = self.search([
            ('state', '=', 'enforced'),
            ('appeal_deadline', '<', today)
        ])
        for case in expired_cases:
            case.message_post(body=_('Appeal submission window of 10 calendar days has expired for Case %s.') % case.name)
