# -*- coding: utf-8 -*-
import calendar
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsTnaCycle(models.Model):
    """Annual Bank-wide Training Needs Assessment cycle (/002/009).

    Default start 1 April, submission window 10 working days,
    approval deadline 31 May - all configurable in EDS settings.
    """
    _name = 'eds.tna.cycle'
    _description = 'TNA Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default=lambda self: _('New'))
    year = fields.Char(string='Assessment Year', required=True, default=lambda self: str(date.today().year), tracking=True)
    start_date = fields.Date(string='Cycle Start Date', required=True, default=lambda self: self._default_start_date(), tracking=True)
    submission_end_date = fields.Date(
        string='Submission End Date', compute='_compute_dates', store=True, readonly=False, tracking=True)
    approval_deadline = fields.Date(
        string='Approval Deadline', compute='_compute_dates', store=True, readonly=False, tracking=True)
    methodology = fields.Text(string='Assessment Methodology')
    responsible_team_id = fields.Many2one('hr.department', string='Responsible Team')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('collecting', 'Collecting Needs'),
        ('consolidating', 'Consolidating'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', tracking=True)
    entry_ids = fields.One2many('eds.tna.entry', 'cycle_id', string='Training Needs')
    entry_count = fields.Integer(string='Training Needs', compute='_compute_entry_count')
    competency_gap_count = fields.Integer(string='Competency Gaps', compute='_compute_source_breakdown')
    pms_gap_count = fields.Integer(string='PMS Gaps', compute='_compute_source_breakdown')
    employee_sub_count = fields.Integer(string='Self-Submissions', compute='_compute_source_breakdown')
    manager_sub_count = fields.Integer(string='Manager Requests', compute='_compute_source_breakdown')
    days_until_deadline = fields.Integer(
        string='Days Until Approval Deadline', compute='_compute_days_until_deadline')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # Task 2: consolidations per cycle (-010)
    consolidation_ids = fields.One2many(
        'eds.tna.consolidation', 'cycle_id', string='Consolidations')
    consolidation_count = fields.Integer(
        string='Consolidations', compute='_compute_consolidation_count')
    last_reminder_date = fields.Date(string='Last Deadline Reminder', readonly=True)

    @api.depends('entry_ids.source')
    def _compute_source_breakdown(self):
        for rec in self:
            rec.competency_gap_count = len(rec.entry_ids.filtered(lambda e: e.source == 'competency_gap'))
            rec.pms_gap_count = len(rec.entry_ids.filtered(lambda e: e.source == 'pms'))
            rec.employee_sub_count = len(rec.entry_ids.filtered(lambda e: e.source == 'manual' and e.submitted_by.id == e.employee_id.user_id.id))
            rec.manager_sub_count = len(rec.entry_ids.filtered(lambda e: e.source == 'manual' and e.submitted_by.id != e.employee_id.user_id.id))

    def action_pull_competency_gaps(self):
        """Auto-pull diagnosed gaps from the Competency Assessment framework into this TNA cycle."""
        self.ensure_one()
        if self.state not in ('draft', 'collecting'):
            raise UserError(_('Competency gaps can only be pulled into Draft or Collecting cycles.'))

        if 'competency.assessment.line' not in self.env:
            raise UserError(_('Competency Management module is not installed.'))

        AssessmentLine = self.env['competency.assessment.line']

        # Query all active assessment lines with below proficiency
        gap_lines = AssessmentLine.search([
            '|',
            ('tna_measure', '=', 'below'),
            ('gap', '>', 0),
            ('employee_id.active', '=', True),
        ])

        created_count = 0
        existing_keys = set(
            self.entry_ids.filtered(lambda e: e.employee_id and e.competency_id).mapped(
                lambda e: (e.employee_id.id, e.competency_id.id)
            )
        )

        new_entries = []
        for line in gap_lines:
            if not line.employee_id or not line.competency_id:
                continue
            key = (line.employee_id.id, line.competency_id.id)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            gap_val = line.gap or (int(line.required_level or 2) - int(line.current_level or 1))
            if gap_val <= 0:
                continue
            severity = 'critical' if gap_val >= 3 else ('high' if gap_val == 2 else 'medium')

            emp = line.employee_id
            new_entries.append({
                'cycle_id': self.id,
                'employee_id': emp.id,
                'work_unit_id': getattr(emp, 'default_operating_unit_id', False) and emp.default_operating_unit_id.id or False,
                'department_id': emp.department_id.id if emp.department_id else False,
                'job_position_id': emp.job_position.id if getattr(emp, 'job_position', False) else (emp.job_id.id if emp.job_id else False),
                'competency_id': line.competency_id.id,
                'competency_gap_level_diff': gap_val,
                'gap_severity': severity,
                'source': 'competency_gap',
                'delivery_mode': 'classroom',
                'proposed_program': _("%s Mastery Program") % line.competency_id.name,
                'justification': _(
                    "Automated diagnostic from Competency Assessment (%s). Required Level: %s, Current Level: %s (Gap: %d)."
                ) % (line.assessment_id.name if line.assessment_id else 'Direct Assessment', line.required_level or '2', line.current_level or '1', gap_val),
                'state': 'submitted',
            })

        if new_entries:
            self.env['eds.tna.entry'].create(new_entries)
            created_count = len(new_entries)

        self.message_post(body=_(
            "Diagnostic sync: Successfully ingested %d competency assessment gaps into cycle %s."
        ) % (created_count, self.name))

        if created_count == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Competency Scan Complete'),
                    'message': _('Scan completed. No new competency assessment gaps found to ingest into cycle %s (or all diagnosed gaps already exist).') % self.name,
                    'type': 'warning',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Competency Gaps Ingested'),
                'message': _('Successfully pulled %d diagnosed competency gaps into TNA Cycle %s.') % (created_count, self.name),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.depends('consolidation_ids')
    def _compute_consolidation_count(self):
        for rec in self:
            rec.consolidation_count = len(rec.consolidation_ids)

    @api.model
    def _cron_tna_deadline_reminder(self):
        """remind pending approvers before the approval deadline; escalate if breached.

        Runs daily (eds.cron_tna_deadline_reminder). Notifies the L&D Manager group via chatter
        once per 7-day window; once the deadline is breached the escalation text is used.
        """
        today = date.today()
        cycles = self.search([
            ('state', 'in', ('collecting', 'consolidating', 'under_approval')),
            ('approval_deadline', '!=', False),
        ])
        manager_group = self.env.ref('employee_development_system.group_eds_manager', raise_if_not_found=False)
        recipients = manager_group.user_ids if manager_group else self.env['res.users']
        partner_ids = recipients.filtered('partner_id').mapped('partner_id').ids
        for cycle in cycles:
            days_left = (cycle.approval_deadline - today).days
            if days_left > 14:
                continue
            if cycle.last_reminder_date and (today - cycle.last_reminder_date).days < 7:
                continue
            if days_left >= 0:
                body = _('Reminder (): TNA cycle %s must be approved by %s - %d days left.'
                         ' Pending approvers: PPDD Validation, Director PPDD, CPCO, SMC.') % (
                    cycle.name, cycle.approval_deadline, days_left)
            else:
                body = _('DEADLINE BREACHED (): TNA cycle %s approval deadline (%s) has been'
                         ' missed by %d days. Escalated for senior management review.') % (
                    cycle.name, cycle.approval_deadline, -days_left)
            cycle.message_post(body=body, partner_ids=partner_ids)
            cycle.last_reminder_date = today
        return True

    @api.model
    def _default_start_date(self):
        """Default: 1st of the configured TNA start month (BRD: 1 April)."""
        month = int(self.env['ir.config_parameter'].sudo().get_param('eds.tna_cycle_start_month', '4'))
        try:
            return date(date.today().year, month, 1)
        except ValueError:
            return date.today()

    @api.depends('start_date')
    def _compute_dates(self):
        for rec in self:
            rec.submission_end_date = rec._add_working_days(
                rec.start_date, rec._get_int_param('eds.tna_submission_days', 10))
            month = rec._get_int_param('eds.tna_approval_deadline_month', 5)
            day = rec._get_int_param('eds.tna_approval_deadline_day', 31)
            try:
                rec.approval_deadline = date(rec.start_date.year, month, day)
            except ValueError:
                # e.g. 31 February - clamp to the last valid day of the month
                last_day = calendar.monthrange(rec.start_date.year, month)[1]
                rec.approval_deadline = date(rec.start_date.year, month, last_day)

    @api.depends('entry_ids')
    def _compute_entry_count(self):
        for rec in self:
            rec.entry_count = len(rec.entry_ids)

    @api.depends('approval_deadline')
    def _compute_days_until_deadline(self):
        today = date.today()
        for rec in self:
            rec.days_until_deadline = (rec.approval_deadline - today).days if rec.approval_deadline else 0

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model
    def _add_working_days(self, d, days):
        """Add N working days (Mon-Fri) to a date - used for submission windows/SLAs."""
        if not d or not days:
            return d
        current = d
        added = 0
        while added < days:
            current += timedelta(days=1)
            if current.weekday() < 5:
                added += 1
        return current

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): base security denies plain users direct ir.sequence access, which
        # would break self-service record creation .
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.tna.cycle') or _('New')
        return super().create(vals_list)

    # ── Workflow (/008/009/010) ──────────────────────────────────────
    def action_start_collection(self):
        """Draft -> Collecting (opens the submission window, /002)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft TNA cycles can start collection.'))
            rec.state = 'collecting'
            rec.message_post(body=_('TNA cycle %s opened for collection. Submission window: %s to %s.')
                             % (rec.name, rec.start_date, rec.submission_end_date))

    def action_finish_collection(self):
        """Collecting -> Consolidating ()."""
        for rec in self:
            if not rec.entry_ids:
                raise UserError(_('No training needs were submitted for this cycle.'))
            rec.state = 'consolidating'
            rec.message_post(body=_('TNA cycle %s moved to consolidation.') % rec.name)

    def action_submit_for_approval(self):
        """Consolidating -> Under Approval (PPDD validation -> Director review ->
        CPCO endorsement -> SMC final approval; stages are tracked via chatter/approval log)."""
        for rec in self:
            if rec.state != 'consolidating':
                raise UserError(_('Only consolidating TNA cycles can be submitted for approval.'))
            rec.state = 'under_approval'
            rec.message_post(
                body=_('TNA %s submitted for approval (PPDD Validation -> Director PPDD -> CPCO -> SMC).')
                % rec.name)

    def action_approve(self):
        """Under Approval -> Approved (approved TNA becomes the official source)."""
        for rec in self:
            if rec.state != 'under_approval':
                raise UserError(_('Only cycles under approval can be approved.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            for entry in rec.entry_ids.filtered(lambda e: e.state == 'validated'):
                entry.state = 'approved'
            rec.message_post(body=_('TNA cycle %s approved. Approved needs are locked for curriculum planning.')
                             % rec.name)

    def action_lock(self):
        """Approved -> Locked ( control)."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved TNA cycles can be locked.'))
            rec.state = 'locked'
            rec.message_post(body=_('TNA cycle %s locked. Modifications require a documented change request.')
                             % rec.name)

    def action_unlock(self):
        """Locked -> Approved (admin only, documented change request)."""
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Only EDS Administrators can unlock a locked TNA cycle.'))
        self.state = 'approved'
        self.message_post(body=_('TNA cycle %s unlocked with a documented change request.') % self.name)


class EdsTnaEntry(models.Model):
    """A single training need within a cycle (/004, ..005, )."""
    _name = 'eds.tna.entry'
    _description = 'TNA Training Need Entry'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _rec_name = 'name'

    def _default_employee_id(self):
        return self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)

    def _default_work_unit_id(self):
        emp = self._default_employee_id()
        if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id:
            return emp.default_operating_unit_id
        return getattr(self.env.user, 'default_operating_unit_id', False)

    def _default_department_id(self):
        emp = self._default_employee_id()
        return emp.department_id if emp else False

    def _default_job_position_id(self):
        emp = self._default_employee_id()
        return emp.job_position if emp else False

    name = fields.Char(string='Reference', readonly=True, copy=False)
    cycle_id = fields.Many2one(
        'eds.tna.cycle', string='TNA Cycle', required=True, ondelete='cascade', tracking=True)
    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit', default=_default_work_unit_id, tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', default=_default_department_id, tracking=True)
    job_position_id = fields.Many2one(
        'hr.job', string='Job Position', default=_default_job_position_id, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', default=_default_employee_id, tracking=True)
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        help='Linked to the approved competency framework .', tracking=True)
    gap_severity = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], string='Gap Severity', default='medium', required=True, tracking=True)
    source = fields.Selection([
        ('manual', 'Manual Entry'),
        ('competency_gap', 'Competency Gap Assessment'),
        ('pms', 'Performance Management (PMS)'),
        ('succession', 'Succession Planning'),
        ('audit', 'Audit Finding'),
        ('regulatory', 'Regulatory / Compliance'),
        ('customer_feedback', 'Customer Feedback'),
        ('industry_trend', 'Industry Trend'),
    ], string='Source', default='manual', required=True, tracking=True)
    delivery_mode = fields.Selection([
        ('classroom', 'Classroom'),
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended'),
    ], string='Delivery Mode', default='classroom', required=True, tracking=True,
        help='Decided at TNA stage : only Classroom (and the classroom part of '
             'Blended) are actioned within EDS; E-Learning routes to the LMS.')
    priority_score = fields.Float(string='Priority Score', compute='_compute_priority_score', store=True)
    justification = fields.Text(string='Justification', required=True)
    proposed_program = fields.Char(string='Proposed Program / Course')
    estimated_cost = fields.Monetary(string='Estimated Cost', currency_field='company_currency_id')
    # Diagnostic Gap Details (Competency & PMS)
    competency_gap_level_diff = fields.Integer(string='Competency Gap (Levels)', default=0,
                                               help='Difference between job required proficiency and employee current rating.')
    pms_kpi_reference = fields.Char(string='PMS KPI / Objective Ref', help='Performance evaluation objective or KPI code.')
    pms_appraisal_score = fields.Float(string='PMS Performance Score', help='Employee appraisal score for the evaluation period.')

    # Intelligent Catalog Matching Engine
    recommended_course_id = fields.Many2one(
        'eds.course', string='Catalog Matching Course', compute='_compute_recommended_course', store=True,
        help='Automatically matched course from the Course Catalog addressing this diagnosed competency.')
    course_match_status = fields.Selection([
        ('exact', 'Catalog Exact Match'),
        ('higher', 'Related Tier Match'),
        ('no_course', 'New Course Development Required'),
    ], string='Catalog Match Status', compute='_compute_recommended_course', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('validated', 'Validated'),
        ('approved', 'Approved'),
        ('converted', 'Converted to Program'),
        ('excluded', 'Excluded'),
    ], string='Status', default='draft', tracking=True)
    submitted_by = fields.Many2one(
        'res.users', string='Submitted By', default=lambda self: self.env.user, readonly=True, copy=False)
    validated_by = fields.Many2one('res.users', string='Validated By', readonly=True)
    validation_date = fields.Datetime(string='Validation Date', readonly=True)
    excluded_reason = fields.Text(string='Exclusion Reason')
    converted_course_ref = fields.Char(string='Converted Program Reference')
    company_currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # ── Task 2: Consolidation & Prioritization (/007) ────────────────
    consolidation_id = fields.Many2one(
        'eds.tna.consolidation', string='Consolidation',
        ondelete='set null', index=True, copy=False, tracking=True)
    is_duplicate = fields.Boolean(
        string='Duplicate Need', default=False, tracking=True,
        help='Auto-flagged during consolidation when the same employee+competency need appears '
             'from multiple sources ().')
    duplicate_of_id = fields.Many2one('eds.tna.entry', string='Duplicate Of', ondelete='set null')
    exclusion_type = fields.Selection([
        ('process', 'Process Issue'),
        ('system', 'System Issue'),
        ('structural', 'Structural Issue'),
    ], string='Non-Training Item Type', tracking=True,
        help='Flagged as a non-training item (process/system/structural) for review & exclusion ().')

    # Priority scoring criteria () - each scored 0-100, weighted by eds.tna.priority.rule
    score_strategic_alignment = fields.Float(string='Strategic Alignment Score', default=50.0)
    score_tom_impact = fields.Float(string='TOM Impact Score', default=50.0)
    score_gap_severity = fields.Float(
        string='Gap Severity Score', compute='_compute_score_gap_severity', store=True)
    score_risk_level = fields.Float(string='Risk Level Score', default=50.0)
    score_regulatory = fields.Float(
        string='Regulatory Score', compute='_compute_score_regulatory', store=True)
    score_future_capability = fields.Float(string='Future Capability Score', default=50.0)

    @api.depends('gap_severity')
    def _compute_score_gap_severity(self):
        """Map the gap severity selection onto the 0-100 scoring scale ()."""
        weights = {'critical': 100.0, 'high': 75.0, 'medium': 50.0, 'low': 25.0}
        for rec in self:
            rec.score_gap_severity = weights.get(rec.gap_severity, 50.0)

    @api.depends('source')
    def _compute_score_regulatory(self):
        """Regulatory/compliance-sourced needs score 100 on the regulatory criterion."""
        for rec in self:
            rec.score_regulatory = 100.0 if rec.source == 'regulatory' else 0.0

    def _criterion_score(self, criteria):
        """Return the 0-100 score for a priority criterion code ()."""
        mapping = {
            'strategic_alignment': 'score_strategic_alignment',
            'tom_impact': 'score_tom_impact',
            'gap_severity': 'score_gap_severity',
            'risk_level': 'score_risk_level',
            'regulatory': 'score_regulatory',
            'future_capability': 'score_future_capability',
        }
        return self[mapping[criteria]] or 0.0

    @api.depends('competency_id', 'proposed_program')
    def _compute_recommended_course(self):
        Course = self.env['eds.course']
        for rec in self:
            if not rec.competency_id:
                rec.recommended_course_id = False
                rec.course_match_status = 'no_course'
                continue

            course_line = self.env['eds.course.competency.line'].search([
                ('competency_id', '=', rec.competency_id.id),
                ('course_id.status', 'in', ('active', 'draft'))
            ], limit=1)

            if course_line:
                rec.recommended_course_id = course_line.course_id.id
                rec.course_match_status = 'exact'
            else:
                c_search = Course.search([
                    '|',
                    ('name', 'ilike', rec.competency_id.name),
                    ('name', 'ilike', rec.proposed_program or '')
                ], limit=1)
                if c_search:
                    rec.recommended_course_id = c_search.id
                    rec.course_match_status = 'higher'
                else:
                    rec.recommended_course_id = False
                    rec.course_match_status = 'no_course'

    def action_view_recommended_course(self):
        self.ensure_one()
        if not self.recommended_course_id:
            raise UserError(_("No matching catalog course found for this competency need."))
        return {
            'name': _('Catalog Matching Course'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': self.recommended_course_id.id,
            'view_mode': 'form',
        }

    @api.depends('score_strategic_alignment', 'score_tom_impact', 'score_gap_severity',
                 'score_risk_level', 'score_regulatory', 'score_future_capability')
    def _compute_priority_score(self):
        """Weighted priority engine (): weighted average of the active rule weights.

        score = sum(weight_i * score_i) / sum(weight_i), capped at 100.
        """
        for rec in self:
            rec.priority_score = rec._get_weighted_priority_score()

    def _get_weighted_priority_score(self):
        """Pure weighted-score computation () - shared by the ORM compute and by the
        priority-rule model so changing a rule weight re-scores every consolidated entry."""
        rules = self.env['eds.tna.priority.rule'].search([('active', '=', True)])
        total_weight = sum(rules.mapped('weight'))
        if not rules or total_weight <= 0:
            return 0.0
        weighted = sum(rule.weight * self._criterion_score(rule.criteria) for rule in rules)
        return round(min(weighted / total_weight, 100.0), 2)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.job_position_id = self.employee_id.job_position
            self.department_id = self.employee_id.department_id
            if not self.work_unit_id:
                self.work_unit_id = self.employee_id.default_operating_unit_id \
                    if hasattr(self.employee_id, 'default_operating_unit_id') else False

    @api.constrains('cycle_id', 'employee_id', 'competency_id', 'delivery_mode')
    def _check_duplicate_need(self):
        for rec in self:
            if not rec.employee_id:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('cycle_id', '=', rec.cycle_id.id),
                ('employee_id', '=', rec.employee_id.id),
                ('delivery_mode', '=', rec.delivery_mode),
            ]
            if rec.competency_id:
                domain.append(('competency_id', '=', rec.competency_id.id))
            if self.search(domain, limit=1):
                raise ValidationError(
                    _('A training need for this employee/competency already exists in this cycle.'))

    @api.model_create_multi
    def create(self, vals_list):
        # sudo(): see EdsTnaCycle.create - self-service entry creation must not
        # depend on the user having ir.sequence access.
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.tna.entry') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        # a locked consolidation freezes its needs; edits require a documented
        # change request (unlock first). The state transition itself and the consolidation
        # engine (which flips flags on its own records) are allowed through sudo context.
        if self.env.context.get('eds_allow_locked_edit'):
            return super().write(vals)
        for rec in self:
            if rec.consolidation_id and rec.consolidation_id.state == 'locked':
                raise UserError(_(
                    'Training need %s belongs to the locked consolidation %s. Unlock the '
                    'consolidation with a documented change request before editing ().')
                    % (rec.name, rec.consolidation_id.name))
        return super().write(vals)

    # ── Workflow (manager review; exclusion) ───────────
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft entries can be submitted.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Training need %s submitted.') % rec.name)

    def action_validate(self):
        """PPDD validation of a submitted entry ()."""
        for rec in self:
            if rec.state not in ('submitted', 'validated'):
                raise UserError(_('Only submitted entries can be validated.'))
            rec.write({
                'state': 'validated',
                'validated_by': self.env.user.id,
                'validation_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Training need %s validated.') % rec.name)

    def action_exclude(self):
        """Flag duplicate/invalid/non-training items for exclusion ()."""
        for rec in self:
            if not rec.excluded_reason:
                raise UserError(_('An exclusion reason is required ().'))
            rec.state = 'excluded'
            rec.message_post(body=_('Training need %s excluded: %s') % (rec.name, rec.excluded_reason))

    def action_reopen_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_create_development_request(self):
        """kick off course development for an approved need - opens a pre-filled
        development request (pre-created so the wizard-less flow is instant)."""
        self.ensure_one()
        if self.state not in ('approved', 'converted'):
            raise UserError(_('Only approved training needs can be converted to a course '
                              'development request ().'))
        existing = self.env['eds.course.development.request'].search(
            [('tna_entry_ids', 'in', [self.id])], limit=1)
        if existing:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.course.development.request',
                'res_id': existing.id,
                'view_mode': 'form',
            }
        request = self.env['eds.course.development.request'].create({
            'tna_entry_ids': [(6, 0, [self.id])],
            'competency_gap_ids': [(6, 0, self.competency_id.ids)] if self.competency_id else False,
            'target_job_ids': [(6, 0, self.job_position_id.ids)] if self.job_position_id else False,
            'expected_outcomes': self.justification,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course.development.request',
            'res_id': request.id,
            'view_mode': 'form',
        }
