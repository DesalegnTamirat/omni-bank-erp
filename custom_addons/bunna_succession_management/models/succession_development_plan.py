# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, AccessError, UserError


class SuccessionDevelopmentPlan(models.Model):
    """
    Successor Development Plan (FR-SDP-002, FR-SDP-006).
    Targeted development interventions specifically for succession candidates
    to close their competency and readiness gaps and move towards 'Ready Now'.
    Separate from the general IDP in competency_management.
    """
    _name = 'succession.development.plan'
    _description = 'Succession: Successor Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    # Sudo Access Layer for Employee Relations (Preserves Bank-wide Privacy)
    def read(self, fields=None, load='_classic_read'):
        self.check_access('read')
        return super(SuccessionDevelopmentPlan, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification: dict[str, dict]) -> list[dict]:
        self.check_access('read')
        return super(SuccessionDevelopmentPlan, self.sudo()).web_read(specification)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        records = self.search_fetch(domain or [], (specification or {}).keys(), offset=offset, limit=limit, order=order)
        values_records = records.sudo().web_read(specification or {})
        return self._format_web_search_read_results(domain or [], values_records, offset, limit, count_limit)

    _rec_name = 'name'

    active = fields.Boolean(string='Active', default=True, tracking=True, index=True)
    name = fields.Char(string='Reference', readonly=True, copy=False, index=True)

    @api.model
    def _default_candidate_id(self):
        if self.env.context.get('default_candidate_id'):
            return self.env.context.get('default_candidate_id')
        user = self.env.user
        emp = user.employee_id
        if emp:
            direct_cands = self.env['succession.candidate'].sudo().search([
                '|', ('employee_id.parent_id', '=', emp.id), ('employee_id.coach_id', '=', emp.id),
                ('state', 'in', ['approved', 'placed']),
            ], order='id desc')
            if len(direct_cands) == 1:
                return direct_cands.id
        return False

    candidate_id = fields.Many2one(
        'succession.candidate', string='Succession Candidate',
        domain="[('state', 'in', ('approved', 'placed'))]",
        required=True, tracking=True, ondelete='cascade',
        index=True,
        default=_default_candidate_id)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        related='candidate_id.employee_id', store=True, readonly=True, index=True)

    has_succession_assessment = fields.Boolean(
        string='Has Succession Assessment',
        compute='_compute_has_succession_assessment', store=True,
        help='True if candidate has recorded competency assessment ratings in the Succession Module.')

    @api.depends(
        'candidate_id',
        'candidate_id.state',
        'candidate_id.eval_line_ids',
        'candidate_id.eval_line_ids.score',
        'candidate_id.eval_line_ids.manager_score',
        'candidate_id.eval_line_ids.self_score',
        'candidate_id.eval_line_ids.spmc_score',
        'candidate_id.competency_gap_ids',
        'candidate_id.competency_gap_ids.current_score'
    )
    def _compute_has_succession_assessment(self):
        for rec in self:
            cand = rec.candidate_id
            if not cand:
                rec.has_succession_assessment = False
                continue
            has_scores = bool(cand.eval_line_ids and any(l.score or l.manager_score or l.self_score or l.spmc_score for l in cand.eval_line_ids))
            is_assessed_state = bool(cand.assessment_status == 'finalized' or cand.state in ('assessed', 'approved', 'placed'))
            rec.has_succession_assessment = bool(has_scores or is_assessed_state)
    evaluating_manager_id = fields.Many2one(
        'hr.employee', string='Assigned Mentor / Evaluator',
        compute='_compute_evaluating_manager_id', store=True, readonly=False, tracking=True, index=True,
        help='Candidate manager, department director, or executive mentor assigned to follow up and evaluate activities.')
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Target Critical Position',
        related='candidate_id.critical_position_id', store=True, readonly=True, index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True, readonly=True, index=True)

    # --- Role & Initiation Tracking ---
    activated_by_id = fields.Many2one(
        'res.users', string='Activated By', readonly=True, copy=False, index=True)
    activation_date = fields.Date(
        string='Activated On', readonly=True, copy=False)
    completed_by_id = fields.Many2one(
        'res.users', string='Completed By', readonly=True, copy=False, index=True)
    achievement_level = fields.Selection([
        ('exceeded', 'Exceeded Expectations - Outstanding Leadership & Mastery'),
        ('met', 'Fully Met Objectives - Demonstrated Target Competencies'),
        ('partially_met', 'Partially Met - Minor Gaps Remaining'),
    ], string='Development Achievement', readonly=True, copy=False, tracking=True)

    # --- Plan Details ---
    plan_year = fields.Integer(
        string='Plan Year', default=lambda self: fields.Date.today().year, store=True)
    target_readiness_level_id = fields.Many2one(
        'succession.readiness.level', domain="[('active', '=', True)]",
        string='Target Readiness Level',
        compute='_compute_target_readiness_level_id',
        store=True, readonly=True,
        tracking=True,
        index=True,
        help="Official candidate readiness level determined and assigned by PPDD following assessment review."
    )
    target_readiness = fields.Selection([
        ('ready_now', 'Ready Now'),
        ('ready_1_2_yrs', 'Ready in 1-2 Years'),
    ], string='Target Readiness at End of Plan', compute='_compute_target_readiness', store=True, readonly=True, tracking=True)
    start_date = fields.Date(string='Plan Start Date', default=fields.Date.today, required=True, tracking=True, index=True)
    end_date = fields.Date(string='Plan End Date', required=True, tracking=True, index=True)

    @api.depends('candidate_id', 'candidate_id.readiness_level_id', 'candidate_id.system_readiness_suggestion_id')
    def _compute_target_readiness_level_id(self):
        for rec in self:
            cand = rec.candidate_id
            if cand and cand.readiness_level_id:
                rec.target_readiness_level_id = cand.readiness_level_id
            elif cand and cand.system_readiness_suggestion_id:
                rec.target_readiness_level_id = cand.system_readiness_suggestion_id
            elif not rec.target_readiness_level_id:
                rec.target_readiness_level_id = False

    @api.onchange('candidate_id')
    def _onchange_candidate_readiness(self):
        if self.candidate_id:
            self.target_readiness_level_id = (
                self.candidate_id.readiness_level_id or
                self.candidate_id.system_readiness_suggestion_id or
                False
            )
            if self.target_readiness_level_id:
                self.target_readiness = 'ready_now' if self.target_readiness_level_id.is_ready_for_deployment else 'ready_1_2_yrs'

    @api.depends('target_readiness_level_id', 'target_readiness_level_id.is_ready_for_deployment')
    def _compute_target_readiness(self):
        for rec in self:
            if rec.target_readiness_level_id:
                rec.target_readiness = 'ready_now' if rec.target_readiness_level_id.is_ready_for_deployment else 'ready_1_2_yrs'
            elif not rec.target_readiness:
                rec.target_readiness = 'ready_1_2_yrs'

    # --- Completion Tracking (FR-SDP-007) ---
    completion_type = fields.Selection([
        ('standard', 'Completed on Schedule'),
        ('early', 'Completed Ahead of Schedule'),
        ('extended', 'Completed after Extension'),
    ], string='Completion Type', readonly=True, copy=False, tracking=True)
    actual_completion_date = fields.Date(
        string='Actual Completion Date', readonly=True, copy=False, tracking=True)
    early_completion_reason = fields.Text(
        string='Ahead-of-Schedule Justification', readonly=True, copy=False)
    acceleration_category = fields.Selection([
        ('rapid_mastery', 'Accelerated Competency Acquisition / High Learning Agility'),
        ('prior_experience', 'Prior Experience / Cross-Functional Credit Recognized'),
        ('early_certification', 'Early Professional / Banking Certification Attained'),
        ('urgent_deployment', 'Urgent Strategic Vacancy / Accelerated Readiness Required'),
        ('other', 'Other Documented Business Reason'),
    ], string='Acceleration Reason', readonly=True, copy=False)
    days_ahead = fields.Integer(
        string='Days Ahead of Schedule', compute='_compute_days_ahead', store=True)

    # --- Extension Governance (FR-SDP-008) ---
    original_end_date = fields.Date(
        string='Baseline End Date', readonly=True, copy=False,
        help='Initial committed end date preserved for SLA variance analytics.')
    extension_count = fields.Integer(
        string='Extensions Granted', default=0, readonly=True, tracking=True)
    proposed_end_date = fields.Date(
        string='Proposed End Date', copy=False, readonly=True)
    extension_reason = fields.Text(
        string='Extension Justification', copy=False, readonly=True)
    extension_root_cause = fields.Selection([
        ('operational_workload', 'Heavy Operational / Project Workload'),
        ('training_postponed', 'External Training / Examination Postponed'),
        ('rotational_extension', 'Rotational Assignment Extended for Depth'),
        ('leave_of_absence', 'Medical / Extended Leave of Absence'),
        ('competency_reinforcement', 'Additional Mentoring / Coaching Required for Gaps'),
        ('other', 'Other Operational Justification'),
    ], string='Extension Root Cause', copy=False, readonly=True)
    extension_remedial_plan = fields.Text(
        string='Extension Remedial Action Plan', copy=False, readonly=True)
    extension_requested_by_id = fields.Many2one(
        'res.users', string='Extension Requested By', readonly=True, copy=False, index=True)
    extension_request_date = fields.Date(
        string='Extension Requested On', readonly=True, copy=False)
    extension_history_ids = fields.One2many(
        'succession.development.plan.extension.log', 'plan_id',
        string='Extension History')

    # --- Completion Evaluation (Manager Review) ---
    completion_notes = fields.Text(
        string='Completion Evaluation / Outcome', tracking=True,
        help='Mandatory manager evaluation notes detailing outcomes, competency improvements, and recommendations before marking the plan as completed.')
    is_eligible_for_completion = fields.Boolean(
        string='Eligible for Completion',
        compute='_compute_is_eligible_for_completion',
        help='True when current date is on or after the plan end date.')

    # --- Career Discussion (Aligned After Development Plan Creation) ---
    career_discussion_ids = fields.One2many(
        'succession.career.discussion', 'dev_plan_id',
        string='Career Discussions')
    career_discussion_count = fields.Integer(
        string='Career Discussions Count',
        compute='_compute_career_discussion_count')
    has_confirmed_career_discussion = fields.Boolean(
        string='Has Confirmed Career Discussion',
        compute='_compute_has_confirmed_career_discussion')

    @api.depends('career_discussion_ids.state', 'employee_id')
    def _compute_career_discussion_count(self):
        for rec in self:
            count = self.env['succession.career.discussion'].sudo().search_count([
                '|', ('dev_plan_id', '=', rec.id),
                '&', ('employee_id', '=', rec.employee_id.id), ('candidate_id', '=', rec.candidate_id.id)
            ])
            rec.career_discussion_count = count

    @api.depends('career_discussion_ids.state', 'employee_id')
    def _compute_has_confirmed_career_discussion(self):
        for rec in self:
            policy = self.env['succession.governance.policy'].sudo().get_policy()
            if not policy.succ_career_discussion_mandatory:
                rec.has_confirmed_career_discussion = True
            elif not rec.employee_id:
                rec.has_confirmed_career_discussion = False
            else:
                confirmed = self.env['succession.career.discussion'].sudo().search_count([
                    ('state', '=', 'confirmed'),
                    '|', ('dev_plan_id', '=', rec.id),
                    '&', ('employee_id', '=', rec.employee_id.id), ('candidate_id', '=', rec.candidate_id.id)
                ])
                rec.has_confirmed_career_discussion = bool(confirmed > 0)

    def action_log_career_discussion(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Career Discussion: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.career.discussion',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_candidate_id': self.candidate_id.id if self.candidate_id else False,
                'default_dev_plan_id': self.id,
                'default_discussion_type': 'career_review',
            },
        }

    def action_view_career_discussions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Career Discussions: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.career.discussion',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [
                '|', ('dev_plan_id', '=', self.id),
                '&', ('employee_id', '=', self.employee_id.id), ('candidate_id', '=', self.candidate_id.id)
            ],
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_candidate_id': self.candidate_id.id if self.candidate_id else False,
                'default_dev_plan_id': self.id,
            },
        }

    # --- Urgency Level ---
    urgency_level_id = fields.Many2one(
        'succession.development.urgency.level',
        string='Urgency Level',
        domain="[('active', '=', True)]",
        tracking=True,
        help='Select the urgency level for this successor development plan.'
    )
    urgency_level = fields.Char(
        string='Urgency Level Name',
        related='urgency_level_id.name',
        store=False,
        readonly=True
    )
    business_impact_score = fields.Integer(
        string='Business Impact Score (1-10)', default=5,
        help='Legacy score field retained for data integrity.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('active', 'In Progress'),
        ('extension_pending', 'Extension Requested'),
        ('extended', 'Extended'),
        ('completed', 'Completed'),
        ('completed_ahead', 'Completed Ahead of Schedule'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, index=True)

    def action_submit(self):
        today = fields.Date.today()
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.is_superuser()
        for rec in self:
            emp = rec.employee_id
            is_manager = bool(
                emp and (
                    (emp.parent_id and emp.parent_id.user_id == user) or
                    (emp.coach_id and emp.coach_id.user_id == user) or
                    (rec.evaluating_manager_id and rec.evaluating_manager_id.user_id == user)
                )
            )
            if not (is_manager or is_admin):
                raise AccessError(_("Only the candidate's direct Line Manager or Coach can submit this development plan for PPDD approval."))

            rec._compute_has_succession_assessment()
            if not rec.has_succession_assessment:
                raise ValidationError(_(
                    "Cannot Submit Succession Development Plan!\n\n"
                    "Candidate '%s' has not completed their Competency Assessment in the Succession Module for '%s'.\n\n"
                    "A Succession Development Plan cannot be submitted without finalized competency assessment results."
                ) % (rec.employee_id.name if rec.employee_id else '', rec.critical_position_id.display_name if rec.critical_position_id else ''))

            if not rec.start_date or not rec.end_date:
                raise ValidationError(_("Please set both Plan Start Date and Plan End Date before submitting the plan."))
            if rec.end_date < rec.start_date:
                raise ValidationError(_("Plan End Date cannot be earlier than Plan Start Date."))
            if rec.start_date < today:
                raise ValidationError(_("Back-dating is not allowed: Plan Start Date (%s) cannot be in the past.") % rec.start_date)

            if not rec.development_activity_ids:
                raise ValidationError(_("Development Activities are mandatory. Please add at least one Development Activity before submitting your Development Plan."))

            for act in rec.development_activity_ids:
                if not act.start_date or not act.target_date:
                    raise ValidationError(_("Every development activity must have a Start Date and a Target Completion Date."))
                if act.target_date < act.start_date:
                    desc = act.activity_description or (act.activity_type_id.name if act.activity_type_id else 'Activity')
                    raise ValidationError(_("Activity '%s': Target Completion Date cannot be earlier than Start Date.") % desc)
                if act.start_date < today:
                    desc = act.activity_description or (act.activity_type_id.name if act.activity_type_id else 'Activity')
                    raise ValidationError(_("Activity '%s': Back-dating is not allowed. Start Date cannot be in the past.") % desc)

            rec.write({'state': 'submitted'})
            rec.message_post(body=_("Succession Development Plan submitted by Manager %s for PPDD review and approval.") % user.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Submitted'),
                'message': _('Succession Development Plan %s has been successfully submitted for PPDD review and approval.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    notes = fields.Text(string='Development Focus / Notes')
    overall_progress = fields.Integer(
        string='Overall Progress (%)', compute='_compute_overall_progress', store=True)

    competency_gap_html = fields.Html(
        string='Competency Gap Analysis',
        compute='_compute_competency_gap_html'
    )

    @api.depends(
        'candidate_id',
        'candidate_id.eval_line_ids',
        'candidate_id.eval_line_ids.score',
        'candidate_id.eval_line_ids.manager_score',
        'candidate_id.competency_gap_ids',
        'candidate_id.competency_gap_ids.current_score',
        'candidate_id.competency_gap_ids.achievement_status',
    )
    def _compute_competency_gap_html(self):
        for rec in self:
            cand = rec.candidate_id
            if not cand or not cand.critical_position_id:
                rec.competency_gap_html = False
                continue

            rec._compute_has_succession_assessment()
            if not rec.has_succession_assessment:
                rec.competency_gap_html = False
                continue

            gaps = cand.competency_gap_ids
            evals = cand.eval_line_ids

            items = []
            if gaps:
                for g in gaps:
                    comp = g.competency_id
                    if not comp:
                        continue
                    items.append({
                        'comp': comp,
                        'pillar': g.competency_pillar or '',
                        'weight': g.weight or 1.0,
                        'current_score': g.current_score or 0.0,
                        'required_score': g.required_score or 0.0,
                        'gap_score': g.gap_score or 0.0,
                        'status': g.achievement_status,
                    })
            elif evals:
                for el in evals:
                    comp = el.competency_id
                    if not comp:
                        continue
                    req = float(el.required_proficiency or 0.0)
                    cur = float(el.score or el.manager_score or 0.0)
                    gap = cur - req
                    status = 'exceeds' if gap > 0 else ('meets' if gap == 0 else 'below')
                    pillar_str = dict(comp._fields['pillar'].selection).get(comp.pillar, '') if hasattr(comp, 'pillar') and comp.pillar else ''
                    items.append({
                        'comp': comp,
                        'pillar': pillar_str,
                        'weight': float(el.weight or 1.0),
                        'current_score': cur,
                        'required_score': req,
                        'gap_score': gap,
                        'status': status,
                    })

            if items:
                html = '<div class="table-responsive"><table class="table table-sm table-hover" style="margin-bottom: 0;">'
                html += '<thead><tr style="border-bottom: 2px solid #dee2e6;">'
                html += '<th>Competency</th>'
                html += '<th>Pillar</th>'
                html += '<th class="text-end">Weight</th>'
                html += '<th class="text-end">Assessment Score</th>'
                html += '<th class="text-end">Required Score</th>'
                html += '<th class="text-end">Gap Size</th>'
                html += '<th class="text-center">Status</th>'
                html += '</tr></thead><tbody>'

                for item in items:
                    comp = item['comp']
                    cur = item['current_score']
                    req = item['required_score']
                    w = item['weight']
                    gap = item['gap_score']
                    status = item['status']

                    if status in ('meets', 'exceeds'):
                        row_class = 'table-success'
                        badge_class = 'text-bg-success'
                        status_text = 'Meets' if status == 'meets' else 'Exceeds'
                        gap_display = "0.00" if status == 'meets' else f"+{gap:.2f}"
                    else:
                        row_class = 'table-danger'
                        badge_class = 'text-bg-danger'
                        status_text = 'Gap Detected'
                        gap_display = f"{abs(gap):.2f}"

                    c_name = getattr(comp, 'display_name', False) or getattr(comp, 'name', '') or str(comp.id)
                    html += f'<tr class="{row_class}">'
                    html += f'<td><span class="text-primary">{c_name}</span></td>'
                    html += f'<td>{item["pillar"]}</td>'
                    html += f'<td class="text-end">{w:.2f}</td>'
                    html += f'<td class="text-end">{cur:.2f}</td>'
                    html += f'<td class="text-end">{req:.2f}</td>'
                    html += f'<td class="text-end">{gap_display}</td>'
                    html += f'<td class="text-center"><span class="badge rounded-pill {badge_class}">{status_text}</span></td>'
                    html += '</tr>'

                html += '</tbody></table></div>'
            else:
                html = '<div class="alert alert-info" role="alert"><i class="fa fa-info-circle me-2"></i>No competency evaluation or gap records found for this candidate.</div>'

            rec.competency_gap_html = html

    def action_generate_activities_from_gaps(self):
        """Automatically create 70-20-10 development activities for identified competency gaps."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    "Cannot Generate Activities: Development Plan '%(plan)s' is in status '%(status)s'.\n\n"
                    "Activities can only be auto-generated when the plan is in Draft status.",
                    plan=rec.name or rec.display_name,
                    status=dict(rec._fields['state'].selection).get(rec.state, rec.state),
                ))
            cand = rec.candidate_id
            if not cand:
                raise ValidationError(_("No Candidate linked to this Development Plan."))

            rec._compute_has_succession_assessment()
            if not rec.has_succession_assessment:
                pos_title = cand.critical_position_id.display_name if cand.critical_position_id else ''
                raise UserError(_(
                    "Cannot Generate Activities: Competency Assessment Required!\n\n"
                    "Candidate '%s' has been nominated for '%s', but has NOT completed their Competency Assessment in the Succession Module yet.\n\n"
                    "Please complete and finalize the candidate competency evaluation in the Succession Module first."
                ) % (cand.employee_id.name, pos_title))

            # Ensure gap analysis is up to date
            if not cand.competency_gap_ids:
                try:
                    cand.action_compute_gap_analysis()
                except Exception:
                    pass

            gap_lines = cand.competency_gap_ids.filtered(lambda g: g.achievement_status == 'below')
            if not gap_lines and cand.eval_line_ids:
                gap_comps = [el.competency_id for el in cand.eval_line_ids if float(el.score or el.manager_score or 0.0) < float(el.required_proficiency or 0.0)]
            else:
                gap_comps = [g.competency_id for g in gap_lines if g.competency_id]

            if not gap_comps:
                rec.message_post(body=_("No competency gaps detected for this candidate."))
                return

            exp_cat = self.env['succession.development.activity.category'].search([('code', '=', 'experiential')], limit=1)
            exp_type = self.env['succession.development.activity.type'].search([('category_id', '=', exp_cat.id)], limit=1) if exp_cat else False

            existing_comps = set(rec.development_activity_ids.mapped('competency_id.id'))
            new_lines = []
            today = fields.Date.today()
            s_date = max(rec.start_date or today, today)
            e_date = max(rec.end_date or today, s_date)

            for comp in gap_comps:
                if comp.id in existing_comps:
                    continue
                c_name = getattr(comp, 'display_name', False) or getattr(comp, 'name', '') or str(comp.id)
                new_lines.append((0, 0, {
                    'competency_id': comp.id,
                    'category_id': exp_cat.id if exp_cat else False,
                    'activity_type_id': exp_type.id if exp_type else False,
                    'activity_description': _("Targeted intervention to close gap in %s") % c_name,
                    'start_date': s_date,
                    'target_date': e_date,
                    'status': 'planned',
                    'progress_percent': 0,
                }))

            if new_lines:
                rec.development_activity_ids = new_lines
                rec.message_post(body=_("Generated %d development activities for detected competency gaps.") % len(new_lines))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Activities Generated'),
                'message': _('Generated %d development activities for detected competency gaps.') % len(new_lines) if new_lines else _('No unaddressed competency gaps detected.'),
                'type': 'success' if new_lines else 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    development_activity_ids = fields.One2many(
        'succession.development.activity', 'plan_id',
        string='Development Activities')
    activity_count = fields.Integer(
        string='Development Activities Count', compute='_compute_activity_count')

    # --- 70-20-10 Leadership Framework Metrics ---
    count_experiential = fields.Integer(
        string='Experiential Activities (70%)', compute='_compute_702010_metrics', store=True)
    count_exposure = fields.Integer(
        string='Exposure Activities (20%)', compute='_compute_702010_metrics', store=True)
    count_education = fields.Integer(
        string='Education Activities (10%)', compute='_compute_702010_metrics', store=True)
    pct_experiential = fields.Float(
        string='Experiential (%)', compute='_compute_702010_metrics', store=True)
    pct_exposure = fields.Float(
        string='Exposure (%)', compute='_compute_702010_metrics', store=True)
    pct_education = fields.Float(
        string='Education (%)', compute='_compute_702010_metrics', store=True)
    balance_status = fields.Selection([
        ('balanced', 'Well-Balanced Development Plan'),
        ('needs_experiential', 'Needs Hands-on Experiential Learning (70%)'),
        ('needs_exposure', 'Needs Mentoring & Coaching Exposure (20%)'),
        ('unbalanced', 'Incomplete / Unbalanced Distribution'),
    ], string='Development Balance Status', compute='_compute_702010_metrics', store=True)

    @api.depends(
        'development_activity_ids',
        'development_activity_ids.category_id',
        'development_activity_ids.category_id.code',
        'development_activity_ids.learning_category'
    )
    def _compute_702010_metrics(self):
        for rec in self:
            acts = rec.development_activity_ids
            total = len(acts)
            c_exp = len(acts.filtered(lambda a: (a.category_id and a.category_id.code == 'experiential') or a.learning_category == 'experiential'))
            c_expo = len(acts.filtered(lambda a: (a.category_id and a.category_id.code == 'exposure') or a.learning_category == 'exposure'))
            c_edu = len(acts.filtered(lambda a: (a.category_id and a.category_id.code == 'education') or a.learning_category == 'education'))
            rec.count_experiential = c_exp
            rec.count_exposure = c_expo
            rec.count_education = c_edu
            if total > 0:
                rec.pct_experiential = round((c_exp / total) * 100.0, 1)
                rec.pct_exposure = round((c_expo / total) * 100.0, 1)
                rec.pct_education = round((c_edu / total) * 100.0, 1)
                if c_exp >= 1 and (c_expo >= 1 or c_edu >= 1):
                    rec.balance_status = 'balanced'
                elif c_exp == 0:
                    rec.balance_status = 'needs_experiential'
                elif c_expo == 0:
                    rec.balance_status = 'needs_exposure'
                else:
                    rec.balance_status = 'unbalanced'
            else:
                rec.pct_experiential = 0.0
                rec.pct_exposure = 0.0
                rec.pct_education = 0.0
                rec.balance_status = 'unbalanced'

    @api.depends('employee_id', 'employee_id.parent_id', 'employee_id.coach_id')
    def _compute_evaluating_manager_id(self):
        for rec in self:
            if not rec.evaluating_manager_id:
                rec.evaluating_manager_id = rec.employee_id.coach_id or rec.employee_id.parent_id or False

    @api.depends('end_date', 'actual_completion_date', 'state')
    def _compute_days_ahead(self):
        for rec in self:
            if rec.state == 'completed_ahead' and rec.end_date and rec.actual_completion_date:
                rec.days_ahead = max((rec.end_date - rec.actual_completion_date).days, 0)
            else:
                rec.days_ahead = 0

    @api.depends('end_date')
    def _compute_is_eligible_for_completion(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_eligible_for_completion = bool(rec.end_date and today >= rec.end_date)

    @api.constrains('start_date', 'end_date', 'state')
    def _check_plan_dates(self):
        today = fields.Date.today()
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_(
                    "Plan End Date (%(end)s) cannot be earlier than Plan Start Date (%(start)s).",
                    end=rec.end_date,
                    start=rec.start_date,
                ))
            if rec.state in ('draft', 'submitted'):
                if rec.start_date and rec.start_date < today:
                    raise ValidationError(_(
                        "Back-dating is not allowed: Plan Start Date (%(start)s) cannot be in the past (must be today %(today)s or later).",
                        start=rec.start_date,
                        today=today,
                    ))
                if rec.end_date and rec.end_date < today:
                    raise ValidationError(_(
                        "Plan End Date (%(end)s) cannot be in the past.",
                        end=rec.end_date,
                    ))

    @api.onchange('start_date', 'end_date')
    def _onchange_plan_dates(self):
        today = fields.Date.today()
        if self.start_date and self.start_date < today:
            warning = {
                'title': _('Invalid Start Date'),
                'message': _('Back-dating is not allowed. Plan Start Date cannot be earlier than today (%s).') % today
            }
            self.start_date = today
            return {'warning': warning}
        if self.start_date and self.end_date and self.end_date < self.start_date:
            warning = {
                'title': _('Invalid End Date'),
                'message': _('Plan End Date (%s) cannot be earlier than Plan Start Date (%s).') % (self.end_date, self.start_date)
            }
            self.end_date = self.start_date
            return {'warning': warning}
        if self.start_date and self.development_activity_ids:
            invalid_acts = self.development_activity_ids.filtered(lambda a: a.start_date and a.start_date < self.start_date)
            if invalid_acts:
                warning = {
                    'title': _('Activity Date Conflict'),
                    'message': _('Some activities have a Start Date earlier than the new Plan Start Date (%s). Please review your activity dates.') % self.start_date
                }
                return {'warning': warning}
        if self.end_date and self.development_activity_ids:
            invalid_acts = self.development_activity_ids.filtered(lambda a: a.target_date and a.target_date > self.end_date)
            if invalid_acts:
                warning = {
                    'title': _('Activity Date Conflict'),
                    'message': _('Some activities have a Target Completion Date later than the new Plan End Date (%s). Please adjust their dates or extend the plan end date.') % self.end_date
                }
                return {'warning': warning}

    @api.depends('development_activity_ids', 'development_activity_ids.progress_percent')
    def _compute_overall_progress(self):
        for rec in self:
            activities = rec.development_activity_ids
            if activities:
                rec.overall_progress = int(
                    sum(a.progress_percent for a in activities) / len(activities))
            else:
                rec.overall_progress = 0

    @api.depends('development_activity_ids')
    def _compute_activity_count(self):
        for rec in self:
            rec.activity_count = len(rec.development_activity_ids)

    @api.model_create_multi
    def create(self, vals_list):
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.is_superuser()
        for vals in vals_list:
            cand_id = vals.get('candidate_id')
            if not cand_id:
                cand_id = self._default_candidate_id()
                vals['candidate_id'] = cand_id

            if not cand_id:
                raise ValidationError(_("Please select a Succession Candidate before creating a Development Plan."))

            cand = self.env['succession.candidate'].sudo().browse(cand_id)
            emp = cand.employee_id

            # Creator authorization: Creator must be direct manager or coach of that employee (unless admin)
            if not is_admin:
                is_manager = bool(
                    emp and (
                        (emp.parent_id and emp.parent_id.user_id == user) or
                        (emp.coach_id and emp.coach_id.user_id == user) or
                        (cand.parent_id and cand.parent_id.user_id == user) or
                        (cand.coach_id and cand.coach_id.user_id == user)
                    )
                )
                if not is_manager:
                    mgr_name = emp.parent_id.name if emp.parent_id else (cand.parent_id.name if cand.parent_id else 'None')
                    raise ValidationError(_(
                        "Cannot Create Succession Development Plan!\n\n"
                        "The creator of a Succession Development Plan must be the direct Line Manager or Coach of the employee.\n\n"
                        "Candidate Employee: %(emp)s\n"
                        "Assigned Direct Manager: %(mgr)s\n"
                        "Current User: %(user)s\n\n"
                        "Please have the employee's Line Manager create the development plan.",
                        emp=emp.name,
                        mgr=mgr_name,
                        user=user.name,
                    ))

            if cand.state not in ('approved', 'placed'):
                pos_title = cand.critical_position_id.display_name if cand.critical_position_id else ''
                status_label = dict(cand._fields['state'].selection).get(cand.state, cand.state)
                raise ValidationError(_(
                    "Cannot Create Succession Development Plan: SPMC Approval Required!\n\n"
                    "Candidate '%(emp)s' (nominated for '%(pos)s') is currently in status '%(status)s'.\n\n"
                    "Development Plans can only be created and conducted after the SPMC Committee has officially reviewed and approved the candidate's assessment.",
                    emp=cand.employee_id.name or cand.display_name,
                    pos=pos_title,
                    status=status_label,
                ))

        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name in ('New', 'SDP-New') or rec.name.startswith('SDP-'):
                rec.name = self.env['ir.sequence'].sudo().next_by_code(
                    'succession.development.plan') or ('BB-IDP-%05d' % rec.id)
            if rec.end_date and not rec.original_end_date:
                rec.original_end_date = rec.end_date
        return records

    def action_activate(self):
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.is_superuser()
        if not (is_ppdd or is_admin):
            raise AccessError(_('Security Restriction: Only PPDD Officers or Administrators can approve and activate a Succession Development Plan.'))
        today = fields.Date.today()
        for rec in self:
            if rec.state not in ('submitted', 'draft'):
                raise ValidationError(_('Only draft or submitted development plans can be approved and activated.'))
            rec._compute_has_succession_assessment()
            if not rec.has_succession_assessment:
                raise ValidationError(_('Cannot activate plan: Candidate competency assessment is incomplete.'))
            if not rec.start_date or not rec.end_date:
                raise ValidationError(
                    _('Please set both Plan Start Date and Plan End Date before activating the development plan.'))
            if rec.end_date < rec.start_date:
                raise ValidationError(
                    _('Plan End Date cannot be earlier than Plan Start Date.'))
            if not rec.development_activity_ids:
                raise ValidationError(
                    _('Add at least one development activity before activating the plan.'))
            if not rec.original_end_date:
                rec.original_end_date = rec.end_date
            rec.with_context(force_write=True).write({
                'state': 'active',
                'activated_by_id': user.id,
                'activation_date': today,
            })
            rec.message_post(body=_('Succession Development Plan %s approved and activated by PPDD Officer %s.') % (rec.name, user.name))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Activated'),
                'message': _('Succession Development Plan %s has been approved and activated.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_return_to_draft(self):
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.is_superuser()
        if not (is_ppdd or is_admin):
            raise AccessError(_("Security Restriction: Only PPDD Officers or Administrators can return a plan for revision."))
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_("Only plans in 'Submitted for Review' state can be returned for revision."))
            rec.write({'state': 'draft'})
            rec.message_post(body=_("Succession Development Plan returned to Draft for revision by PPDD Officer %s.") % user.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Returned to Draft'),
                'message': _('Succession Development Plan %s has been returned to draft for revision.') % self.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_completion_wizard(self):
        self.ensure_one()
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin')
        emp = self.sudo().employee_id
        mgr = self.sudo().evaluating_manager_id
        is_manager = bool(emp and (emp.parent_id.user_id == user or emp.coach_id.user_id == user or (mgr and mgr.user_id == user)))
        if not (is_ppdd or is_admin or is_manager or self.env.is_superuser()):
            raise AccessError(_('Security Restriction: Only the candidate\'s direct Manager, PPDD Officers, or Administrators can formally complete a Succession Development Plan.'))
        if self.state not in ('active', 'extended'):
            raise ValidationError(_('Only active or extended development plans can be completed.'))
        return {
            'name': _('Final Evaluation & Plan Completion: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'succession.plan.completion.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def action_complete(self):
        today = fields.Date.today()
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin')
        for rec in self:
            emp = rec.sudo().employee_id
            mgr = rec.sudo().evaluating_manager_id
            is_manager = bool(emp and (emp.parent_id.user_id == user or emp.coach_id.user_id == user or (mgr and mgr.user_id == user)))
            if not (is_ppdd or is_admin or is_manager or self.env.is_superuser()):
                raise AccessError(_('Security Restriction: Only the candidate\'s direct Manager, PPDD Officers, or Administrators can complete a development plan.'))
            if rec.state not in ('active', 'extended'):
                raise ValidationError(_('Only active or extended development plans can be completed.'))
            if not rec.start_date or not rec.end_date:
                raise ValidationError(
                    _('Both Plan Start Date and Plan End Date must be set before completing the development plan.'))
            if not rec.completion_notes or not rec.completion_notes.strip():
                raise ValidationError(
                    _('Mandatory Completion Evaluation Required!\n'
                      'Please provide the final evaluation in the "Manager Completion Evaluation" field below before marking this development plan as completed.'))
            if len(rec.completion_notes.strip()) < 15:
                raise ValidationError(
                    _('Please provide a substantive evaluation (at least 15 characters) in the "Manager Completion Evaluation" field.'))

            # Determine completion type and target state
            is_early = (today < rec.end_date)
            comp_type = 'early' if is_early else ('extended' if rec.extension_count > 0 else 'standard')
            target_state = 'completed_ahead' if is_early else 'completed'

            # Auto-complete any remaining planned or in-progress activities
            for act in rec.development_activity_ids.filtered(lambda a: a.status in ('planned', 'in_progress')):
                act.write({
                    'status': 'completed',
                    'progress_percent': 100,
                    'outcome_notes': (act.outcome_notes or '') + '\n' + _('Completed on plan completion (%s).') % today,
                })

            rec.with_context(force_write=True).write({
                'state': target_state,
                'completion_type': comp_type,
                'actual_completion_date': today,
                'completed_by_id': self.env.user.id,
                'early_completion_reason': rec.completion_notes if is_early else rec.early_completion_reason,
            })

            rec.message_post(body=_(
                '<b>Successor Development Plan %(name)s marked as COMPLETED by %(user)s (%(role)s)</b><br/>'
                '<ul>'
                '<li><b>Actual Completion Date:</b> %(date)s</li>'
                '<li><b>Completion Type:</b> %(type)s</li>'
                '<li><b>Manager Evaluation:</b> %(notes)s</li>'
                '</ul>'
            ) % {
                'name': rec.name,
                'user': self.env.user.name,
                'role': 'Manager' if is_manager else 'PPDD Officer',
                'date': today,
                'type': dict(self._fields['completion_type'].selection).get(comp_type, ''),
                'notes': rec.completion_notes,
            })

            # Upgrade Candidate Readiness to Deployment Readiness upon successful plan completion
            if rec.candidate_id:
                policy = self.env['succession.governance.policy'].get_policy()
                target_level = policy.deployment_readiness_level_id or self.env['succession.readiness.level'].search([('is_ready_for_deployment', '=', True)], order='sequence asc', limit=1)
                if not target_level:
                    target_level = self.env['succession.readiness.level'].search([('code', '=', 'ready_now')], limit=1)
                if target_level and rec.candidate_id.readiness_level_id != target_level:
                    old_name = rec.candidate_id.readiness_level_id.name or 'N/A'
                    rec.candidate_id.write({'readiness_level_id': target_level.id})
                    rec.candidate_id.message_post(body=_(
                        'Readiness Level upgraded from "%s" to "%s" following completion of Development Plan %s.'
                    ) % (old_name, target_level.name, rec.name))

            if hasattr(rec.candidate_id, '_log_candidate_event'):
                rec.candidate_id._log_candidate_event(
                    'development_completed',
                    'Development Plan %s completed on %s. Evaluated by: %s.' % (rec.name, today, self.env.user.name)
                )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Development Plan Completed'),
                'message': _('Succession Development Plan %s has been marked as Completed.') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_early_completion_wizard(self):
        self.ensure_one()
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin')
        emp = self.sudo().employee_id
        mgr = self.sudo().evaluating_manager_id
        is_manager = bool(emp and (emp.parent_id.user_id == user or emp.coach_id.user_id == user or (mgr and mgr.user_id == user)))
        if not (is_ppdd or is_admin or is_manager or self.env.is_superuser()):
            raise AccessError(_(
                'Security Restriction: Only the candidate\'s Manager, '
                'PPDD Officers, or Administrators can authorize early plan completion.'))
        if self.state not in ('active', 'extended'):
            raise ValidationError(_('Only active or extended development plans can be completed ahead of schedule.'))
        return {
            'name': _('Complete Plan Ahead of Schedule: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'succession.plan.early.completion.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def action_open_extension_wizard(self):
        self.ensure_one()
        if self.state not in ('active', 'extended'):
            raise ValidationError(_('Only active or extended development plans can be extended.'))
        return {
            'name': _('Extend Plan Duration: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'succession.plan.extension.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_plan_id': self.id},
        }

    def action_approve_extension(self):
        self.ensure_one()
        if not (self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or
                self.env.user.has_group('bunna_succession_management.group_succession_admin') or
                self.env.is_superuser()):
            raise AccessError(_('Security Restriction: Only PPDD Officers or Administrators can approve plan extensions.'))
        if self.state != 'extension_pending':
            raise ValidationError(_('This plan has no pending extension request.'))
        if not self.proposed_end_date or self.proposed_end_date <= self.end_date:
            raise ValidationError(_('Proposed end date must be strictly after the current end date.'))

        prev_end = self.end_date
        if not self.original_end_date:
            self.original_end_date = prev_end

        new_count = self.extension_count + 1
        days_added = (self.proposed_end_date - prev_end).days

        # Log extension
        self.env['succession.development.plan.extension.log'].create({
            'plan_id': self.id,
            'extension_number': new_count,
            'old_end_date': prev_end,
            'new_end_date': self.proposed_end_date,
            'days_extended': days_added,
            'root_cause': self.extension_root_cause,
            'justification': self.extension_reason or '',
            'remedial_plan': self.extension_remedial_plan or '',
            'requested_by_id': self.extension_requested_by_id.id or self.env.user.id,
            'request_date': self.extension_request_date or fields.Date.today(),
            'approved_by_id': self.env.user.id,
            'approval_date': fields.Date.today(),
            'status': 'approved',
        })

        self.with_context(force_write=True).write({
            'end_date': self.proposed_end_date,
            'extension_count': new_count,
            'state': 'extended',
        })

        self.message_post(body=_(
            'Plan Extension Approved by %s.\n'
            'Revised End Date: %s (+%d days).\n'
            'Extension Cycle: #%d\n'
            'Root Cause: %s\n'
            'Justification: %s'
        ) % (self.env.user.name, self.end_date, days_added, new_count,
             dict(self._fields['extension_root_cause'].selection).get(self.extension_root_cause, ''),
             self.extension_reason or ''))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extension Approved'),
                'message': _('Plan Extension for %s approved. Revised End Date: %s (+%d days).') % (self.name, self.end_date, days_added),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_reject_extension(self):
        self.ensure_one()
        if not (self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or
                self.env.user.has_group('bunna_succession_management.group_succession_admin') or
                self.env.is_superuser()):
            raise AccessError(_('Security Restriction: Only PPDD Officers or Administrators can reject plan extensions.'))
        if self.state != 'extension_pending':
            raise ValidationError(_('This plan has no pending extension request.'))

        prev_state = 'extended' if self.extension_count > 0 else 'active'

        self.env['succession.development.plan.extension.log'].create({
            'plan_id': self.id,
            'extension_number': self.extension_count + 1,
            'old_end_date': self.end_date,
            'new_end_date': self.proposed_end_date or self.end_date,
            'days_extended': 0,
            'root_cause': self.extension_root_cause,
            'justification': self.extension_reason or '',
            'remedial_plan': self.extension_remedial_plan or '',
            'requested_by_id': self.extension_requested_by_id.id or self.env.user.id,
            'request_date': self.extension_request_date or fields.Date.today(),
            'approved_by_id': self.env.user.id,
            'approval_date': fields.Date.today(),
            'status': 'rejected',
            'rejection_reason': 'Extension request rejected by PPDD.',
        })

        self.with_context(force_write=True).write({
            'state': prev_state,
            'proposed_end_date': False,
        })

        self.message_post(body=_('Plan Extension Request was rejected by %s.') % self.env.user.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extension Rejected'),
                'message': _('Plan extension request for %s has been rejected.') % self.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_cancel(self):
        self.with_context(force_write=True).write({'state': 'cancelled'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Cancelled'),
                'message': _('Development Plan %s has been cancelled.') % self.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_view_activities(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Development Activities - %s') % self.display_name,
            'res_model': 'succession.development.activity',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }

    def write(self, vals):
        allowed_submitted_fields = {
            'state', 'active', 'message_follower_ids', 'message_ids', 'activity_ids',
            'activated_by_id', 'activation_date', 'has_succession_assessment',
            'competency_gap_html', 'overall_progress',
        }
        for rec in self:
            if rec.state == 'submitted' and not self.env.context.get('bypass_plan_lock'):
                restricted = set(vals.keys()) - allowed_submitted_fields
                if restricted:
                    field_labels = [rec._fields[f].string for f in restricted if f in rec._fields]
                    raise UserError(_(
                        "Cannot edit Development Plan '%(plan)s' while it is Submitted for Review!\n\n"
                        "The plan is currently under PPDD review and cannot be modified. "
                        "To make modifications, PPDD must return the plan to draft for revision.\n\n"
                        "Restricted field(s): %(fields)s",
                        plan=rec.name or rec.display_name,
                        fields=', '.join(field_labels) or ', '.join(restricted),
                    ))
            elif rec.state in ('completed', 'completed_ahead', 'cancelled') and not self.env.context.get('bypass_plan_lock'):
                restricted = set(vals.keys()) - {'active', 'message_follower_ids', 'message_ids', 'activity_ids'}
                if restricted:
                    raise UserError(_(
                        "Cannot edit Development Plan '%(plan)s' in '%(state)s' status.\n\n"
                        "Completed or cancelled development plans are immutable records.",
                        plan=rec.name or rec.display_name,
                        state=dict(rec._fields['state'].selection).get(rec.state, rec.state),
                    ))
        return super().write(vals)

    def unlink(self):
        is_admin = self.env.is_admin() or self.env.user.has_group('base.group_system') or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        for rec in self:
            rec_sudo = rec.sudo()
            if rec_sudo.state == 'draft':
                if not (rec_sudo.create_uid == self.env.user or is_admin):
                    raise UserError(_(
                        "Draft development plan '%s' can only be deleted by its creator (%s) or a Succession Administrator."
                    ) % (rec_sudo.display_name, rec_sudo.create_uid.name or 'unknown'))
            else:
                state_label = dict(rec_sudo._fields['state'].selection).get(rec_sudo.state, rec_sudo.state)
                raise UserError(_(
                    "Development plan '%s' in status '%s' cannot be permanently deleted. "
                    "Please archive this record (Action > Archive) to maintain compliance and development records."
                ) % (rec_sudo.display_name, state_label))
        return super(SuccessionDevelopmentPlan, self.sudo()).unlink()


class SuccessionDevelopmentPlanExtensionLog(models.Model):
    """
    Immutable audit log tracking all extension requests, approvals,
    rejections, and justifications for succession development plans.
    """
    _name = 'succession.development.plan.extension.log'
    _description = 'Succession Development Plan Extension Log'
    _order = 'id desc'

    plan_id = fields.Many2one(
        'succession.development.plan', string='Development Plan',
        required=True, ondelete='cascade', index=True)
    extension_number = fields.Integer(string='Extension #', default=1)
    old_end_date = fields.Date(string='Previous End Date', required=True)
    new_end_date = fields.Date(string='New End Date', required=True)
    days_extended = fields.Integer(string='Days Added')
    root_cause = fields.Selection([
        ('operational_workload', 'Heavy Operational / Project Workload'),
        ('training_postponed', 'External Training / Examination Postponed'),
        ('rotational_extension', 'Rotational Assignment Extended for Depth'),
        ('leave_of_absence', 'Medical / Extended Leave of Absence'),
        ('competency_reinforcement', 'Additional Mentoring / Coaching Required for Gaps'),
        ('other', 'Other Operational Justification'),
    ], string='Root Cause')
    justification = fields.Text(string='Justification / Reason', required=True)
    remedial_plan = fields.Text(string='Remedial Plan')
    requested_by_id = fields.Many2one('res.users', string='Requested By', index=True)
    request_date = fields.Date(string='Request Date')
    approved_by_id = fields.Many2one('res.users', string='Approved By', index=True)
    approval_date = fields.Date(string='Approval Date')
    status = fields.Selection([
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='approved', index=True)
    rejection_reason = fields.Text(string='Rejection Reason')


class SuccessionDevelopmentActivityCategory(models.Model):
    """
    Major Development Activity adhering to the 70-20-10 Learning Model (FR-BRD-70-20-10).
    The 3 Major Activities:
    1. Experiential Learning (70%)
    2. Exposure and Social Learning (20%)
    3. Education and Formal Learning (10%)
    Parent configuration holding child sub-activities.
    """
    _name = 'succession.development.activity.category'
    _description = 'Succession Development Major Activity'
    _order = 'sequence, id'

    name = fields.Char(string='Major Activity Name', required=True, translate=True, index='trigram')
    code = fields.Selection([
        ('experiential', 'Experiential Learning (70%)'),
        ('exposure', 'Exposure & Social Learning (20%)'),
        ('education', 'Education & Formal Learning (10%)'),
    ], string='Pillar Code', required=True, default='experiential', index=True)
    target_percentage = fields.Float(
        string='Target Share (%)', default=70.0,
        help='Target percentage in the 70-20-10 learning model (70% Experiential, 20% Exposure, 10% Education).')
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    description = fields.Text(
        string='Framework Guidance',
        help='Operational description and pedagogical rationale behind this 70-20-10 major activity.')
    child_sub_activity_ids = fields.One2many(
        'succession.development.activity.type', 'category_id',
        string='Child Sub-Activities')
    child_sub_activity_count = fields.Integer(
        string='Child Sub-Activities Count', compute='_compute_sub_activity_count')
    active = fields.Boolean(default=True, index=True)

    @api.depends('child_sub_activity_ids')
    def _compute_sub_activity_count(self):
        for rec in self:
            rec.child_sub_activity_count = len(rec.child_sub_activity_ids)


class SuccessionDevelopmentActivityType(models.Model):
    """
    Child Sub-Activity linked to a Major Development Activity.
    E.g. Acting Role, Job Rotation, Stretch Assignment under Experiential Learning.
    """
    _name = 'succession.development.activity.type'
    _description = 'Succession Development Child Sub-Activity'
    _order = 'category_id, sequence, name, id'

    name = fields.Char(string='Child Sub-Activity Name', required=True, translate=True, index='trigram')
    category_id = fields.Many2one(
        'succession.development.activity.category', domain="[('active', '=', True)]",
        string='Parent Major Activity',
        required=True,
        ondelete='cascade',
        index=True,
        help='The 70-20-10 Major Activity this child sub-activity belongs to.'
    )
    code = fields.Char(string='Code', index=True)
    learning_category = fields.Selection(
        related='category_id.code', string='Learning Pillar', store=True, readonly=True,
        help='70-20-10 Leadership development framework classification derived from parent major activity.')
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    description = fields.Text(string='Sub-Activity Guidance / Objectives')
    active = fields.Boolean(default=True, index=True)


class SuccessionDevelopmentActivity(models.Model):
    """
    A single development activity inside a Successor Development Plan.
    Categorized dynamically by Major Activity (70-20-10) and its cascading Child Sub-Activity.
    """
    _name = 'succession.development.activity'
    _description = 'Succession Development Activity'
    _order = 'target_date, id'

    @api.model
    def _default_category_id(self):
        return self.env['succession.development.activity.category'].search([('code', '=', 'experiential')], limit=1).id or \
               self.env['succession.development.activity.category'].search([], order='sequence asc', limit=1).id

    @api.model
    def _default_activity_type_id(self):
        cat = self._default_category_id()
        if cat:
            return self.env['succession.development.activity.type'].search([('category_id', '=', cat)], order='sequence asc', limit=1).id
        return self.env['succession.development.activity.type'].search([], order='sequence asc', limit=1).id

    plan_id = fields.Many2one(
        'succession.development.plan', string='Development Plan',
        required=True, ondelete='cascade', index=True)
    competency_id = fields.Many2one(
        'competency.competency', string='Target Competency / Gap',
        index=True,
        help='The specific competency gap this activity is designed to address.')
    category_id = fields.Many2one(
        'succession.development.activity.category', domain="[('active', '=', True)]",
        string='Major Activity',
        default=_default_category_id,
        required=True,
        index=True,
        help='Primary Major Activity: Experiential, Exposure, or Education.'
    )
    activity_type_id = fields.Many2one(
        'succession.development.activity.type',
        string='Child Sub-Activity',
        domain="[('category_id', '=', category_id), ('active', '=', True)]",
        default=_default_activity_type_id,
        required=True,
        ondelete='restrict',
        index=True,
        help='Child sub-activity displayed dynamically according to the selected Major Activity.'
    )
    activity_type = fields.Char(
        string='Child Sub-Activity Name',
        related='activity_type_id.name',
        readonly=True
    )
    learning_category = fields.Selection([
        ('experiential', 'Experiential Learning (70%)'),
        ('exposure', 'Exposure & Social Learning (20%)'),
        ('education', 'Education & Formal Learning (10%)'),
    ], string='Learning Pillar', compute='_compute_learning_category', store=True, readonly=False,
       help='70-20-10 Leadership pillar. Synchronized with the selected major activity.')
    activity_description = fields.Text(
        string='Specific Assignment / Task Details', required=True)
    mentor_id = fields.Many2one(
        'hr.employee', string='Assigned Mentor / Lead',
        index=True,
        help='Executive mentor, sponsor, or lead assigned to guide or evaluate this specific activity.')
    host_department_id = fields.Many2one(
        'hr.department', string='Host Department',
        index=True,
        help='Target branch or directorate for rotational or acting assignments.')
    deliverable = fields.Char(
        string='Expected Deliverable / Output',
        help='Tangible result, committee report, project delivery, or credential to produce.')
    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.today, index=True)
    target_date = fields.Date(string='Target Completion Date', required=True, index=True)
    progress_percent = fields.Integer(string='Progress (%)', default=0)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned', index=True)
    outcome_notes = fields.Text(string='Outcome / Evidence')

    @api.depends('category_id', 'category_id.code', 'activity_type_id', 'activity_type_id.category_id')
    def _compute_learning_category(self):
        for rec in self:
            if rec.category_id and rec.category_id.code:
                rec.learning_category = rec.category_id.code
            elif rec.activity_type_id and rec.activity_type_id.category_id:
                rec.learning_category = rec.activity_type_id.category_id.code
            elif not rec.learning_category:
                rec.learning_category = 'experiential'

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id and self.activity_type_id:
            if self.activity_type_id.category_id != self.category_id:
                self.activity_type_id = False

    @api.onchange('activity_type_id')
    def _onchange_activity_type_id(self):
        if self.activity_type_id and self.activity_type_id.category_id:
            self.category_id = self.activity_type_id.category_id
            self.learning_category = self.activity_type_id.category_id.code

    @api.constrains('progress_percent')
    def _check_progress(self):
        for rec in self:
            if not (0 <= rec.progress_percent <= 100):
                raise ValidationError(_('Progress must be between 0 and 100%.'))

    @api.constrains('start_date', 'target_date', 'status', 'plan_id')
    def _check_activity_dates(self):
        today = fields.Date.today()
        for rec in self:
            desc = rec.activity_description or (rec.activity_type_id.name if rec.activity_type_id else 'Activity')
            if rec.start_date and rec.target_date and rec.target_date < rec.start_date:
                raise ValidationError(_(
                    "Activity '%(name)s': Target Completion Date (%(target)s) cannot be earlier than Start Date (%(start)s).",
                    name=desc, target=rec.target_date, start=rec.start_date,
                ))
            if rec.status in ('planned', False) and rec.start_date and rec.start_date < today:
                raise ValidationError(_(
                    "Activity '%(name)s': Back-dating is not allowed. Start Date (%(start)s) cannot be in the past (must be today %(today)s or later).",
                    name=desc, start=rec.start_date, today=today,
                ))
            if rec.status in ('planned', False) and rec.target_date and rec.target_date < today:
                raise ValidationError(_(
                    "Activity '%(name)s': Target Completion Date (%(target)s) cannot be in the past.",
                    name=desc, target=rec.target_date,
                ))
            if rec.plan_id:
                if rec.plan_id.start_date and rec.start_date and rec.start_date < rec.plan_id.start_date:
                    raise ValidationError(_(
                        "Activity '%(name)s': Start Date (%(act_start)s) cannot be earlier than Plan Start Date (%(plan_start)s).",
                        name=desc, act_start=rec.start_date, plan_start=rec.plan_id.start_date,
                    ))
                if rec.plan_id.end_date and rec.target_date and rec.target_date > rec.plan_id.end_date:
                    raise ValidationError(_(
                        "Activity '%(name)s': Target Completion Date (%(act_target)s) cannot be later than Plan End Date (%(plan_end)s).",
                        name=desc, act_target=rec.target_date, plan_end=rec.plan_id.end_date,
                    ))

    @api.onchange('start_date', 'target_date')
    def _onchange_activity_dates(self):
        today = fields.Date.today()
        if self.start_date and self.start_date < today and self.status in ('planned', False):
            warning = {
                'title': _('Invalid Start Date'),
                'message': _('Back-dating is not allowed. Activity Start Date cannot be earlier than today (%s).') % today
            }
            self.start_date = today
            return {'warning': warning}
        if self.plan_id and self.plan_id.start_date and self.start_date and self.start_date < self.plan_id.start_date:
            warning = {
                'title': _('Invalid Start Date'),
                'message': _('Activity Start Date (%s) cannot be earlier than Plan Start Date (%s).') % (self.start_date, self.plan_id.start_date)
            }
            self.start_date = self.plan_id.start_date
            return {'warning': warning}
        if self.start_date and self.target_date and self.target_date < self.start_date:
            warning = {
                'title': _('Invalid Target Date'),
                'message': _('Activity Target Completion Date (%s) cannot be earlier than Start Date (%s).') % (self.target_date, self.start_date)
            }
            self.target_date = self.start_date
            return {'warning': warning}
        if self.plan_id and self.plan_id.end_date and self.target_date and self.target_date > self.plan_id.end_date:
            warning = {
                'title': _('Invalid Target Date'),
                'message': _('Activity Target Completion Date (%s) cannot be later than Plan End Date (%s).') % (self.target_date, self.plan_id.end_date)
            }
            self.target_date = self.plan_id.end_date
            return {'warning': warning}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('plan_id'):
                plan = self.env['succession.development.plan'].browse(vals['plan_id'])
                if plan.state != 'draft' and not self.env.context.get('bypass_activity_lock'):
                    raise UserError(_(
                        "Cannot add development activities to Development Plan '%(plan)s'!\n\n"
                        "Activities can only be added when the development plan is in Draft status.",
                        plan=plan.name or plan.display_name,
                    ))
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.plan_id and rec.plan_id.state == 'submitted' and not self.env.context.get('bypass_activity_lock'):
                raise UserError(_(
                    "Cannot modify activities for Development Plan '%(plan)s' while it is Submitted for Review!\n\n"
                    "The plan is currently under PPDD review. To make changes, PPDD must return the plan to draft for revision.",
                    plan=rec.plan_id.name or rec.plan_id.display_name,
                ))
            elif rec.plan_id and rec.plan_id.state in ('completed', 'completed_ahead', 'cancelled') and not self.env.context.get('bypass_activity_lock'):
                raise UserError(_(
                    "Cannot modify activities for Development Plan '%(plan)s' because the plan has been completed or cancelled.",
                    plan=rec.plan_id.name or rec.plan_id.display_name,
                ))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.plan_id and rec.plan_id.state != 'draft' and not self.env.context.get('bypass_activity_lock'):
                raise UserError(_(
                    "Cannot delete activity '%(name)s' from Development Plan '%(plan)s'!\n\n"
                    "Activities cannot be removed once the development plan has been submitted.",
                    name=rec.activity_description or (rec.activity_type_id.name if rec.activity_type_id else 'Activity'),
                    plan=rec.plan_id.name or rec.plan_id.display_name,
                ))
        return super().unlink()


class SuccessionDevelopmentUrgencyLevel(models.Model):
    _name = 'succession.development.urgency.level'
    _description = 'Succession Development Plan Urgency Level'
    _order = 'sequence, id'

    name = fields.Char(string='Urgency Level', required=True, translate=True, index='trigram')
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    min_score = fields.Integer(
        string='Min Score', default=1,
        help='Lowest Business Impact Score in this range (inclusive).')
    max_score = fields.Integer(
        string='Max Score', default=10,
        help='Highest Business Impact Score in this range (inclusive).')
    color = fields.Integer(string='Color Index', default=0, help='Color for UI badges')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True, index=True)
    policy_id = fields.Many2one(
        'succession.governance.policy',
        string='Governance Policy',
        default=lambda self: self.env['succession.governance.policy'].get_policy(),
        ondelete='cascade',
        index=True,
    )

    @api.constrains('min_score', 'max_score')
    def _check_scores(self):
        for rec in self:
            if rec.min_score > rec.max_score:
                raise ValidationError(_("Min Score (%s) cannot exceed Max Score (%s).") % (rec.min_score, rec.max_score))


