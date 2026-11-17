# -*- coding: utf-8 -*-
import logging
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError, AccessError

_logger = logging.getLogger(__name__)


class SuccessionCandidate(models.Model):
    """
    Successor Candidate (FR-SEL-001, FR-SEL-002, FR-TAR-006).
    Maps an employee to a critical position with:
    - Readiness level classification (Ready Now / 1-2 Yrs / 3-5 Yrs)
    - Full competency gap analysis vs. the critical position requirements
    - PMS score evaluation
    - Manager justification and PPDD/SPMC approval
    Employees have ZERO visibility into this model.
    """
    _name = 'succession.candidate'
    _description = 'Succession: Candidate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    # Sudo Access Layer for Employee Relations (Preserves Bank-wide Privacy)
    def read(self, fields=None, load='_classic_read'):
        self.check_access('read')
        return super(SuccessionCandidate, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification: dict[str, dict]) -> list[dict]:
        self.check_access('read')
        return super(SuccessionCandidate, self.sudo()).web_read(specification)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        records = self.search_fetch(domain or [], (specification or {}).keys(), offset=offset, limit=limit, order=order)
        values_records = records.sudo().web_read(specification or {})
        return self._format_web_search_read_results(domain or [], values_records, offset, limit, count_limit)

    @api.model
    def web_read_group(self, domain=None, *args, **kwargs):
        self.check_access('read')
        user_domain = self.env['ir.rule']._compute_domain(self._name, 'read')
        combined_domain = domain or []
        if user_domain:
            from odoo.fields import Domain
            combined_domain = Domain.AND([combined_domain, user_domain])
        return super(SuccessionCandidate, self.sudo()).web_read_group(combined_domain, *args, **kwargs)


    display_name = fields.Char(
        string='Candidate', compute='_compute_display_name', store=True)
    active = fields.Boolean(string='Active', default=True, tracking=True, index=True)

    # --- Core Identification ---
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        tracking=True, ondelete='restrict', index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True, readonly=True, index=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        related='employee_id.job_id', store=True, readonly=True, index=True)
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        required=True, tracking=True, ondelete='cascade',
        index=True,
        domain="[('state', '=', 'approved')]")

    # --- Nomination Info (FR-SEL-001) ---
    nominated_by_id = fields.Many2one(
        'res.users', string='Nominated By', tracking=True, index=True)
    nomination_date = fields.Date(
        string='Nomination Date', index=True)
    manager_justification = fields.Text(
        string='Manager Justification',
        help='Explain why this employee is a strong successor for this critical position.')

    # --- Readiness Classification (FR-TAR-006) ---
    readiness_level_id = fields.Many2one('succession.readiness.level', string='Readiness Level', tracking=True, index=True, domain="[('active', '=', True)]",
       help='Official candidate readiness level determined and assigned by PPDD following assessment review.')
    system_readiness_suggestion_id = fields.Many2one('succession.readiness.level', string='System Readiness Suggestion', domain="[('active', '=', True)]",
       compute='_compute_system_readiness_suggestion', store=True, readonly=True, index=True,
       help='Auto-computed multi-factor readiness based on Final Assessment Score, PMS, and 9-Box.')
    manager_override = fields.Boolean(
        string='Manager Override Applied', default=False,
        help='True when manager has manually overridden the system readiness suggestion.')

    # --- Exact Target Readiness & Career Proximity ---
    target_readiness_date = fields.Date(
        string='Target Readiness Date', compute='_compute_target_readiness_date',
        store=True, tracking=True, index=True,
        help='Estimated or planned date when the candidate is expected to reach deployment readiness.')
    target_readiness_year = fields.Integer(
        string='Target Readiness Year', compute='_compute_target_readiness_date',
        store=True, help='Calendar year of the candidate target readiness date (e.g. 2026, 2028).')
    target_readiness_display = fields.Char(
        string='Target Readiness Timeframe', compute='_compute_target_readiness_date',
        store=True, help='Formatted month and year (e.g., June 2028) or Ready Now.')
    grade_gap = fields.Integer(
        string='Job Grade Gap', compute='_compute_grade_gap', store=True,
        help='Difference between target critical position job grade and candidate current job grade.')
    grade_gap_display = fields.Char(
        string='Grade Proximity', compute='_compute_grade_gap', store=True)
    current_grade_display = fields.Char(
        string='Current Grade', compute='_compute_grade_gap', store=True)
    target_grade_display = fields.Char(
        string='Target Grade', compute='_compute_grade_gap', store=True)
    active_idp_id = fields.Many2one(
        'succession.development.plan', string='Active Development Plan',
        compute='_compute_active_idp_info', store=True, index=True)
    active_idp_progress = fields.Integer(
        string='Active Development Plan Progress (%)',
        compute='_compute_active_idp_info', store=True)

    # --- Position Succession Coverage Metrics (Inherited from Critical Position for Talent Pool) ---
    position_min_successors = fields.Integer(
        string='Required Successors for Role',
        related='critical_position_id.min_successor_count',
        store=True,
        readonly=True,
        help='Minimum successor count required for the target critical position.'
    )
    position_bench_strength = fields.Char(
        string='Nominated / Required',
        related='critical_position_id.bench_strength',
        store=True,
        readonly=True,
        help='Nominated vs Required successor count (e.g. 2 / 3).'
    )
    position_ready_now_count = fields.Integer(
        string='Ready Now for Role',
        related='critical_position_id.ready_now_count',
        store=True,
        readonly=True,
        help='Number of Ready Now successors for this position.'
    )
    position_ready_soon_count = fields.Integer(
        string='Ready in 1-2 Yrs for Role',
        related='critical_position_id.ready_soon_count',
        store=True,
        readonly=True,
        help='Number of Ready in 1-2 Years successors for this position.'
    )
    position_bench_deficit = fields.Integer(
        string='Successors Needed',
        related='critical_position_id.bench_deficit',
        store=True,
        readonly=True,
        help='Number of additional successors needed to reach the required count.'
    )
    position_bench_health = fields.Selection(
        related='critical_position_id.bench_health',
        string='Successor Pipeline Status',
        store=True,
        readonly=True
    )
    position_readiness_summary = fields.Char(
        string='Role Successor Breakdown',
        related='critical_position_id.bench_readiness_summary',
        store=True,
        readonly=True
    )

    # --- 9-Box Grid Integration (FR-TAL-005) ---
    # Performance sourced from employee's latest PMS score (PBMS/Competency module)
    # Potential sourced from employee's latest competency overall score
    # Both are READ from existing modules — NOT self-calculated here.
    performance_rating = fields.Selection([
        ('low', 'Low Performance'),
        ('medium', 'Medium Performance'),
        ('high', 'High Performance'),
    ], string='Performance Rating', compute='_compute_9box_ratings', store=True, readonly=False, tracking=True, index=True,
       help="Auto-sourced from employee's latest PMS score via matrix configuration. Can be adjusted during calibration.")
    potential_rating = fields.Selection([
        ('low', 'Low Potential'),
        ('medium', 'Medium Potential'),
        ('high', 'High Potential'),
    ], string='Potential Rating', compute='_compute_9box_ratings', store=True, readonly=False, tracking=True, index=True,
       help="Auto-calculated from Target Position Competency Match % vs configured thresholds. Can be manually adjusted during calibration.")
    nine_box_label = fields.Char(
        string='9-Box Position', compute='_compute_9box_label', store=True)
    is_high_potential = fields.Boolean(
        string='High Potential', compute='_compute_9box_label', store=True,
        help='True when employee is Star Performer (High Performance + High Potential).')

    # --- Approval Workflow ---
    state = fields.Selection([
        ('draft', 'Draft / Identified'),
        ('nominated', 'Nominated'),
        ('assessed', 'Assessed'),
        ('approved', 'SPMC Approved'),
        ('placed', 'Deployed'),
        ('resigned', 'Employee Resigned'),
        ('rejected', 'Rejected'),
        ('waitlisted', 'Waitlisted'),
    ], string='Status', default='draft', tracking=True, index=True)
    ppdd_notes = fields.Text(string='PPDD Assessment Notes')
    spmc_decision_notes = fields.Text(string='SPMC Decision Notes')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True, index=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True, index=True)

    # --- Critical Position Governance & Audit (Approval Tab) ---
    position_created_by_id = fields.Many2one(
        'res.users', string='Position Created By',
        related='critical_position_id.create_uid', readonly=True,
        help='User who created the Critical Position.'
    )
    position_create_date = fields.Datetime(
        string='Position Creation Date & Time',
        related='critical_position_id.create_date', readonly=True,
        help='Date and time when the Critical Position was created.'
    )
    position_approved_by_id = fields.Many2one(
        'res.users', string='Position Approved By',
        related='critical_position_id.spmc_approved_by_id', readonly=True,
        help='SPMC Member who approved the Critical Position.'
    )
    position_approval_date = fields.Datetime(
        string='Position Approval Date & Time',
        related='critical_position_id.spmc_approval_date', readonly=True,
        help='Date and time when the Critical Position was approved by SPMC.'
    )
    deployed_by_id = fields.Many2one('res.users', string='Deployed By', readonly=True, index=True)
    deployment_date = fields.Datetime(string='Deployment Date', readonly=True, index=True)
    resignation_detected_date = fields.Datetime(string='Resignation Recorded On', readonly=True, index=True)
    can_deploy_from_pool = fields.Boolean(
        string='Can Deploy from Pool',
        compute='_compute_can_deploy_from_pool',
    )

    # ==========================================================================
    # COMPETENCY GAP ANALYSIS (FR-SEL-002)
    # ==========================================================================
    competency_gap_ids = fields.One2many(
        'succession.candidate.competency.gap', 'candidate_id',
        string='Competency Gap Analysis')
    competency_gap_count = fields.Integer(
        string='Competency Gaps', compute='_compute_competency_summary', store=True)
    competency_match_percent = fields.Float(
        string='Competency Match (%)', compute='_compute_competency_summary', store=True)
    competency_eligible = fields.Boolean(
        string='Competency Eligible', compute='_compute_competency_summary', store=True)

    # --- Career Discussions & Development Plans Linkages ---
    career_discussion_ids = fields.One2many(
        'succession.career.discussion', 'candidate_id',
        string='Career Discussions')
    career_discussion_count = fields.Integer(
        string='Career Discussions Count',
        compute='_compute_career_discussion_count')
    has_confirmed_career_discussion = fields.Boolean(
        string='Has Confirmed Career Discussion',
        compute='_compute_has_confirmed_career_discussion')

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
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '=', 'confirmed')
                ])
                rec.has_confirmed_career_discussion = bool(confirmed > 0)

    def _check_confirmed_career_discussion(self, action_name="proceed"):
        """Career discussions are held with the Succession Development Plan (after assessment)."""
        return True

    dev_plan_ids = fields.One2many(
        'succession.development.plan', 'candidate_id',
        string='Development Plans')
    dev_plan_count = fields.Integer(
        string='Development Plans Count',
        compute='_compute_dev_plan_count')

    def _compute_career_discussion_count(self):
        for rec in self:
            rec.career_discussion_count = len(rec.sudo().career_discussion_ids)

    def _compute_dev_plan_count(self):
        for rec in self:
            rec.dev_plan_count = len(rec.sudo().dev_plan_ids)

    # --- PMS Score ---
    latest_pms_score = fields.Float(
        string='Latest PMS Score', compute='_compute_pms_score', inverse='_inverse_pms_score', store=True, readonly=True, tracking=True,
        help="Employee's PMS score. Auto-sourced from employee appraisal records.")

    def _inverse_pms_score(self):
        for rec in self:
            rec._compute_9box_ratings()
            rec._compute_9box_label()

    # --- Succession Competency Evaluation (Evaluated specifically for this Critical Position) ---
    eval_line_ids = fields.One2many(
        'succession.candidate.eval.line', 'candidate_id',
        string='Succession Competency Evaluation Lines',
        help='Manager/Evaluator ratings on target critical position competencies.')
    competency_eval_score = fields.Float(
        string='Competency Evaluation Score (%)',
        compute='_compute_competency_eval_score', store=True, digits=(16, 2),
        help='Average percentage score from manager ratings on required critical position competencies.')

    # --- Employee Coach and SPMC Assigned Assessor ---
    coach_id = fields.Many2one(
        'hr.employee', string='Employee Coach / Mentor',
        compute='_compute_supervisors', store=True, readonly=False,
        help="Employee's assigned Coach or Mentor from HR profile.")
    parent_id = fields.Many2one(
        'hr.employee', string='Line Manager',
        compute='_compute_supervisors', store=True, readonly=False,
        help="Employee's direct Line Manager from HR profile.")
    def _domain_spmc_users(self):
        group = self.env.ref('bunna_succession_management.group_succession_spmc', raise_if_not_found=False)
        return [('all_group_ids', 'in', [group.id])] if group else []

    spmc_assigned_user_id = fields.Many2one(
        'res.users', string='Assigned SPMC Assessor',
        readonly=True,
        tracking=True,
        index=True,
        help='Designated SPMC Committee Member who assessed this candidate.')
    spmc_assessor_ids = fields.Many2many(
        'res.users',
        'succession_candidate_spmc_user_rel',
        'candidate_id',
        'user_id',
        string='Assigned SPMC Assessors',
        domain=lambda self: self._domain_spmc_users(),
        tracking=True,
        help='Designated SPMC Committee Members who will evaluate this candidate.')
    spmc_eval_ids = fields.One2many(
        'succession.candidate.spmc.eval', 'candidate_id',
        string='SPMC Assessor Evaluations')
    spmc_assessor_summary_html = fields.Html(
        'SPMC Assessors Breakdown', compute='_compute_spmc_summary_html')

    @api.depends('employee_id', 'employee_id.coach_id', 'employee_id.parent_id')
    def _compute_supervisors(self):
        for rec in self:
            emp = rec.sudo().employee_id
            rec.coach_id = emp.coach_id if emp else False
            rec.parent_id = emp.parent_id if emp else False

    # --- Candidate Self-Assessment ---
    self_assessment_score = fields.Float(
        string='Self-Assessment Score (0–100)', tracking=True,
        compute='_compute_self_assessment_score', store=True, readonly=False,
        help='Candidate self-assessment rating or average competency score.')
    self_assessment_notes = fields.Text(
        string='Self-Assessment Notes / Reflections',
        help='Candidate self-reflection on strengths, readiness, and development areas.')

    # --- SPMC Committee Assessment ---
    spmc_score = fields.Float(
        string='SPMC Assessment Score (0–100)', tracking=True,
        compute='_compute_spmc_score', store=True, readonly=False,
        help='Executive committee assessment score determined during SPMC review.')
    spmc_recommendation = fields.Selection([
        ('strongly_recommend', 'Strongly Recommend'),
        ('recommend', 'Recommend'),
        ('develop', 'Recommend with Development'),
        ('not_recommend', 'Not Recommended at this Time'),
    ], string='SPMC Recommendation', tracking=True)
    spmc_deliberation_notes = fields.Text(
        string='SPMC Deliberation & Observations', tracking=True,
        help='Key discussion points, rationale, and committee recommendations.')

    @api.depends('eval_line_ids.manager_score', 'eval_line_ids.score',
                 'eval_line_ids.required_proficiency', 'eval_line_ids.weight')
    def _compute_competency_eval_score(self):
        for rec in self:
            lines = rec.eval_line_ids
            if not lines:
                rec.competency_eval_score = 0.0
                continue
            scored_lines = lines.filtered(lambda l: l.manager_score or l.score)
            if not scored_lines:
                rec.competency_eval_score = 0.0
                continue
            total_weight = sum(l.weight or 1.0 for l in lines)
            if not total_weight:
                rec.competency_eval_score = 0.0
                continue
            # Competencies where the evaluated level MEETS or EXCEEDS the required level earn full points
            earned_weight = sum(
                (l.weight or 1.0)
                for l in scored_lines
                if l.required_proficiency and int(l.manager_score or l.score) >= int(l.required_proficiency)
            )
            rec.competency_eval_score = round((earned_weight / total_weight) * 100.0, 2)

    @api.depends('eval_line_ids.self_score', 'eval_line_ids.required_proficiency',
                 'eval_line_ids.weight', 'plan_include_self')
    def _compute_self_assessment_score(self):
        for rec in self:
            if not rec.plan_include_self:
                rec.self_assessment_score = 0.0
                continue
            lines = rec.eval_line_ids
            scored_lines = lines.filtered(lambda l: l.self_score)
            if not scored_lines:
                rec.self_assessment_score = rec.self_assessment_score or 0.0
                continue
            total_weight = sum(l.weight or 1.0 for l in lines)
            if not total_weight:
                rec.self_assessment_score = 0.0
                continue
            earned_weight = sum(
                (l.weight or 1.0)
                for l in scored_lines
                if l.required_proficiency and int(l.self_score) >= int(l.required_proficiency)
            )
            rec.self_assessment_score = round((earned_weight / total_weight) * 100.0, 2)

    @api.depends('spmc_eval_ids.score', 'spmc_eval_ids.submitted',
                 'eval_line_ids.spmc_score', 'eval_line_ids.required_proficiency',
                 'eval_line_ids.weight', 'plan_include_spmc')
    def _compute_spmc_score(self):
        for rec in self:
            if not rec.plan_include_spmc:
                rec.spmc_score = 0.0
                continue
            if rec.spmc_eval_ids:
                scores = [e.score for e in rec.spmc_eval_ids if e.score > 0 or e.submitted]
                if scores:
                    rec.spmc_score = round(sum(scores) / len(scores), 2)
                    continue
                elif len(rec.spmc_eval_ids) > 0:
                    rec.spmc_score = 0.0
                    continue
            lines = rec.eval_line_ids
            scored_lines = lines.filtered(lambda l: l.spmc_score)
            if not scored_lines:
                rec.spmc_score = rec.spmc_score or 0.0
                continue
            total_weight = sum(l.weight or 1.0 for l in lines)
            if not total_weight:
                rec.spmc_score = 0.0
                continue
            earned_weight = sum(
                (l.weight or 1.0)
                for l in scored_lines
                if l.required_proficiency and int(l.spmc_score) >= int(l.required_proficiency)
            )
            rec.spmc_score = round((earned_weight / total_weight) * 100.0, 2)

    @api.depends('spmc_eval_ids.user_id.name', 'spmc_eval_ids.score', 'spmc_eval_ids.submitted', 'spmc_score', 'spmc_assessor_ids')
    def _compute_spmc_summary_html(self):
        for rec in self:
            if not rec.plan_include_spmc or not rec.spmc_eval_ids:
                rec.spmc_assessor_summary_html = False
                continue
            items = []
            for se in rec.spmc_eval_ids:
                name = se.user_id.name or "Assessor"
                if se.submitted:
                    badge = '<span class="badge bg-success ms-1"><i class="fa fa-check me-1"></i>Submitted</span>'
                else:
                    scored_lines = len(se.line_ids.filtered(lambda l: l.score))
                    total_lines = len(se.line_ids)
                    status_text = f"{scored_lines}/{total_lines}" if total_lines else "Pending"
                    badge = f'<span class="badge bg-warning text-dark ms-1"><i class="fa fa-clock-o me-1"></i>{status_text}</span>'
                score_badge = f'<strong class="text-primary">{se.score:.1f}%</strong>'
                items.append(f"""
                    <div class="col-12 col-sm-6 mb-1">
                        <div class="p-2 bg-light rounded border d-flex justify-content-between align-items-center">
                            <span class="small text-truncate" title="{name}">
                                <i class="fa fa-user-circle text-primary me-1"></i><strong>{name}</strong>
                            </span>
                            <div class="d-flex align-items-center gap-1">
                                {score_badge}
                                {badge}
                            </div>
                        </div>
                    </div>
                """)
            rec.spmc_assessor_summary_html = f'<div class="row g-1 mt-1">{"".join(items)}</div>'

    def _sync_spmc_eval_records(self):
        SpmcEval = self.env['succession.candidate.spmc.eval'].sudo()
        SpmcEvalLine = self.env['succession.candidate.spmc.eval.line'].sudo()
        for rec in self:
            if not rec.plan_include_spmc:
                continue
            assessors = rec.spmc_assessor_ids
            if not assessors and rec.spmc_assigned_user_id:
                assessors = self.env['res.users'].sudo().browse([rec.spmc_assigned_user_id.id])
            for assessor in assessors:
                eval_rec = SpmcEval.search([
                    ('candidate_id', '=', rec.id),
                    ('user_id', '=', assessor.id),
                ], limit=1)
                if not eval_rec:
                    eval_rec = SpmcEval.create({
                        'candidate_id': rec.id,
                        'user_id': assessor.id,
                    })
                existing_eval_line_ids = set(eval_rec.line_ids.mapped('eval_line_id.id'))
                new_spmc_lines = []
                for el in rec.eval_line_ids:
                    if el.id not in existing_eval_line_ids:
                        new_spmc_lines.append({
                            'spmc_eval_id': eval_rec.id,
                            'eval_line_id': el.id,
                        })
                if new_spmc_lines:
                    SpmcEvalLine.create(new_spmc_lines)

            # If any assigned assessor has not yet submitted, overall SPMC is NOT submitted
            if rec.spmc_eval_ids:
                all_sub = all(e.submitted for e in rec.spmc_eval_ids)
                if not all_sub and rec.spmc_evaluation_submitted:
                    rec.sudo().write({
                        'spmc_evaluation_submitted': False,
                        'spmc_evaluation_date': False,
                    })

    has_competency_mapping = fields.Boolean(
        string='Has Competency Mapping',
        compute='_compute_has_competency_mapping',
        compute_sudo=True,
        help='True if the critical position has approved competency mappings.')

    @api.depends('critical_position_id', 'critical_position_id.required_role_mapping_line_ids')
    def _compute_has_competency_mapping(self):
        for rec in self.sudo():
            rec.has_competency_mapping = bool(
                rec.critical_position_id and rec.critical_position_id.sudo().required_role_mapping_line_ids
            )

    @api.model
    def _notify_and_reload(self, title, message, notif_type='success', sticky=False):
        """Show a toast notification and soft-reload the active form view."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': sticky,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_populate_competency_eval_lines(self):
        """Populate evaluation lines for the target critical position's required competencies."""
        for rec in self:
            if not rec.critical_position_id:
                continue
            if not rec.assessment_criteria_synced or not rec.has_competency_assessment:
                if len(self) == 1:
                    if not rec.assessment_criteria_synced:
                        raise UserError(_(
                            "Assessment Plan has not been synchronized with this employee. "
                            "Please synchronize the Assessment Plan first."
                        ))
                    if not rec.has_competency_assessment:
                        raise UserError(_(
                            "Competency Assessment is not included in the synchronized Assessment Plan for this candidate."
                        ))
                continue

            # 1. Purge any corrupt/orphan lines without a competency
            invalid_lines = rec.eval_line_ids.filtered(lambda l: not l.competency_id)
            if invalid_lines:
                invalid_lines.unlink()

            req_lines = rec.critical_position_id.sudo().required_role_mapping_line_ids
            if not req_lines:
                if len(self) == 1:
                    raise UserError(_(
                        "No approved Competency Role Mapping found for position '%s'. "
                        "Please configure and approve competencies under 'Talent & Competency > Competency Role Mapping' first."
                    ) % rec.critical_position_id.display_name)
                continue

            existing_comp_ids = set(rec.eval_line_ids.mapped('competency_id.id'))
            new_lines = []
            seq = 10
            for req in req_lines:
                if req.competency_id and req.competency_id.id not in existing_comp_ids:
                    new_lines.append({
                        'candidate_id': rec.id,
                        'competency_id': req.competency_id.id,
                        'required_proficiency': getattr(req, 'required_proficiency', '3') or '3',
                        'weight': getattr(req, 'weight', 1.0) or 1.0,
                        'sequence': getattr(req, 'sequence', seq) or seq,
                    })
                    seq += 10
            if new_lines:
                self.env['succession.candidate.eval.line'].sudo().create(new_lines)
            rec._sync_spmc_eval_records()
        return self._notify_and_reload(
            _('Competencies Loaded'),
            _('Role competencies successfully loaded for evaluation.'),
        )

    def action_start_competency_evaluation(self):
        """Open the behavioral evaluation modal for the first pending competency for the current user's role."""
        self.ensure_one()
        if self.assessment_done or self.state != 'nominated':
            raise UserError(_("Competency evaluation is closed for this candidate."))
        if not self.assessment_criteria_synced or not self.has_competency_assessment:
            raise UserError(_("Competency evaluation is not available or not included in the synchronized Assessment Plan for this candidate."))
        if not self.can_evaluate_competencies:
            raise UserError(_("You are not configured or authorized as an evaluator for this candidate, or your evaluation has already been submitted."))
        if not self.critical_position_id:
            raise UserError(_("No critical position specified for this candidate."))

        if not self.eval_line_ids:
            if not self.critical_position_id.sudo().required_role_mapping_line_ids:
                raise UserError(_(
                    "No approved Competency Role Mapping is configured for position '%s'. "
                    "Please configure and approve competencies under 'Talent & Competency > Competency Role Mapping' first."
                ) % self.critical_position_id.display_name)
            self.action_populate_competency_eval_lines()
        if not self.eval_line_ids:
            raise UserError(_("No competencies found for this candidate's target critical position."))

        user = self.env.user
        emp = self.sudo().employee_id
        is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)
        is_coach_or_mgr = bool(emp and (
            (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
            (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
            (self.sudo().parent_id and self.sudo().parent_id.user_id and self.sudo().parent_id.user_id.id == user.id) or
            (self.sudo().coach_id and self.sudo().coach_id.user_id and self.sudo().coach_id.user_id.id == user.id)
        ))
        is_assigned_spmc = bool(
            (self.spmc_assigned_user_id and self.spmc_assigned_user_id.id == user.id) or
            (self.spmc_assessor_ids and user.id in self.spmc_assessor_ids.ids)
        )

        unscored = False
        if is_self and self.plan_include_self:
            unscored = self.eval_line_ids.filtered(lambda l: not l.self_score)
        elif is_assigned_spmc and self.plan_include_spmc and not (is_coach_or_mgr and self.plan_include_manager and not self.manager_evaluation_submitted):
            user_eval = self.spmc_eval_ids.filtered(lambda e: e.user_id.id == user.id)
            if user_eval:
                unrated_line_ids = set(user_eval.line_ids.filtered(lambda l: not l.score).mapped('eval_line_id.id'))
                unscored = self.eval_line_ids.filtered(lambda l: l.id in unrated_line_ids)
            else:
                unscored = self.eval_line_ids.filtered(lambda l: not l.spmc_score)
        elif self.plan_include_manager and is_coach_or_mgr:
            unscored = self.eval_line_ids.filtered(lambda l: not l.manager_score)
        else:
            unscored = self.eval_line_ids.filtered(lambda l: not l.score)

        target = unscored[0] if unscored else (self.eval_line_ids[0] if self.eval_line_ids else False)
        if target:
            return target.action_open_eval_modal()
        raise UserError(_("No competencies found for this candidate's target critical position."))

    def action_reset_competency_eval_lines(self):
        """Reset all competency evaluation lines to empty so assessors can evaluate fresh."""
        for rec in self:
            rec.eval_line_ids.sudo().write({
                'score': False, 'evidence': False,
                'manager_score': False, 'manager_evidence': False,
                'self_score': False, 'self_evidence': False,
                'spmc_score': False, 'spmc_evidence': False,
            })
            rec.sudo().write({
                'manager_evaluation_submitted': False,
                'manager_evaluation_date': False,
                'spmc_evaluation_submitted': False,
                'spmc_evaluation_date': False,
                'self_evaluation_submitted': False,
                'self_evaluation_date': False,
            })
            rec._compute_competency_eval_score()
            rec._compute_self_assessment_score()
            rec._compute_spmc_score()
            rec._compute_succession_competency_score()
            rec.assessment_result_ids._compute_line()
            rec._compute_assessment_scores()
        return self._notify_and_reload(
            _('Evaluations Reset'),
            _('Competency evaluations have been reset for fresh evaluation.'),
            notif_type='warning',
        )

    # ==========================================================================
    # CONFIGURABLE ASSESSMENT (components defined in Assessment Configuration)
    # ==========================================================================
    assessment_result_ids = fields.One2many(
        'succession.candidate.assessment.result', 'candidate_id',
        string='Assessment Results')
    final_assessment_score = fields.Float(
        string='Final Assessment Score', compute='_compute_assessment_scores',
        store=True, digits=(16, 2),
        help='Weighted score (0-100) of all applicable assessment components.')
    assessment_pass_mark = fields.Float(
        string='Pass Mark', compute='_compute_assessment_pass_mark')
    assessment_result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Below Pass Mark'),
        ('waived', 'All Components Not Applicable (N/A)'),
    ], string='Assessment Result', compute='_compute_assessment_scores', store=True, index=True)
    assessment_status = fields.Selection([
        ('pending', 'Awaiting Results'),
        ('partial', 'In Progress'),
        ('ready', 'Results Complete'),
        ('finalized', 'Assessed'),
    ], string='Assessment Status', compute='_compute_assessment_scores', store=True, index=True)
    assessment_breakdown_display = fields.Char(
        string='Calculation Breakdown', compute='_compute_assessment_scores', store=True,
        help='Formula breakdown showing how each component contributed to the final score.')
    assessment_done = fields.Boolean(string='Assessment Finalized', readonly=True, copy=False)
    assessment_criteria_synced = fields.Boolean(
        string='Assessment Criteria Synced', default=False, copy=False,
        help='Set to True once assessment components have been synced from position requirements. '
             'Record Assessment is only available after this step is completed.')
    criteria_sync_status = fields.Selection(
        [('synced', 'Synced'), ('pending', 'Pending')],
        string='Criteria Synced',
        compute='_compute_criteria_sync_status',
        store=True,
        help='Indicates whether assessment criteria have been synchronized from the position plan.'
    )

    @api.depends('assessment_criteria_synced')
    def _compute_criteria_sync_status(self):
        for rec in self:
            rec.criteria_sync_status = 'synced' if rec.assessment_criteria_synced else 'pending'

    has_competency_assessment = fields.Boolean(
        string='Has Competency Assessment in Plan',
        compute='_compute_has_competency_assessment',
        store=True,
        help='True if the synchronized Assessment Plan includes an active (non-waived) Competency Assessment component.',
    )

    @api.depends(
        'assessment_criteria_synced',
        'assessment_result_ids',
        'assessment_result_ids.component_id',
        'assessment_result_ids.component_id.evaluation_type',
        'assessment_result_ids.component_id.source',
        'assessment_result_ids.component_id.name',
        'assessment_result_ids.waived',
        'assessment_result_ids.weight',
    )
    def _compute_has_competency_assessment(self):
        for rec in self:
            if not rec.assessment_criteria_synced:
                rec.has_competency_assessment = False
                continue
            has_comp = False
            for res in rec.assessment_result_ids:
                etype = res.component_id.evaluation_type or res.component_id.source or ''
                name = (res.component_id.name or '').lower()
                if (etype == 'competency_eval' or 'competency' in name) and not res.waived and res.weight > 0:
                    has_comp = True
                    break
            rec.has_competency_assessment = has_comp
    assessment_criteria_synced_date = fields.Datetime(
        string='Criteria Synced On', readonly=True, copy=False,
        help='Date and time when evaluation criteria were synchronized from position assessment plan.')
    assessment_criteria_synced_by_id = fields.Many2one(
        'res.users', string='Criteria Synced By', readonly=True, copy=False, index=True,
        help='User who synchronized evaluation criteria from the critical position plan.')
    assessment_date = fields.Datetime(string='Assessed On', readonly=True, copy=False, index=True)
    assessment_by_id = fields.Many2one('res.users', string='Assessed By', readonly=True, copy=False, index=True)
    candidate_log_ids = fields.One2many(
        'succession.governance.log', 'candidate_id', string='Audit Trail', readonly=True)

    assessment_scope = fields.Selection([
        ('manager_only', 'Manager Evaluation Only'),
        ('manager_self', 'Manager + Candidate Self-Assessment'),
        ('manager_spmc', 'Manager + SPMC Committee Evaluation'),
        ('full_360', 'Comprehensive Multi-Rater (Manager, Self & SPMC)'),
        ('custom', 'Custom Evaluator Selection'),
    ], string='Competency Assessment Scope', default='manager_spmc', tracking=True, index=True,
       help='Defines the multi-rater competency evaluation scope.')

    # Explicit Pillar Inclusions
    plan_include_exam = fields.Boolean(
        string='Written Examination', default=True, tracking=True,
        help='Include the written domain exam in this candidate assessment.')
    exam_exemption_reason = fields.Char(
        string='Exam Exemption Justification', tracking=True,
        help='Mandatory justification if Written Examination is not applicable for this candidate.')
    plan_include_pms = fields.Boolean(
        string='Annual PMS Appraisal', default=True, tracking=True,
        help="Whether candidate's verified annual Performance Management System (PMS) score is included as an assessment pillar.")
    pms_exemption_reason = fields.Char(
        string='PMS Exemption Justification', tracking=True,
        help='Mandatory justification if Annual PMS Appraisal is not applicable for this candidate.')
    plan_include_manager = fields.Boolean(
        string='Manager Evaluation', default=True,
        help='Include manager competency rating in this candidate assessment.')
    def _default_plan_include_self(self):
        try:
            return bool(self.env['succession.assessment.config'].get_config().enable_self_assessment)
        except Exception:
            return False

    plan_include_self = fields.Boolean(
        string='Candidate Self-Assessment', default=_default_plan_include_self, tracking=True,
        help='Include candidate self-reflection evaluation in this candidate assessment.')
    plan_include_spmc = fields.Boolean(
        string='SPMC Committee Evaluation', default=True, tracking=True,
        help='Include executive committee deliberation score in this candidate assessment.')

    # --- Assessment Plan Weights & Max Scores (Configured per Plan) ---
    weight_pms = fields.Float(
        string='PMS Appraisal Weight (%)', default=20.0, tracking=True,
        help='Weight percentage allocated to Annual PMS Appraisal.')
    max_score_pms = fields.Float(
        string='PMS Max Score', default=100.0,
        help='Maximum score for Annual PMS Appraisal.')

    weight_competency = fields.Float(
        string='Competency Assessment Weight (%)',
        compute='_compute_weight_competency', store=True,
        help='Weight percentage allocated to Succession Competency Assessment.')
    max_score_competency = fields.Float(
        string='Competency Max Score', default=100.0,
        help='Maximum score for Succession Competency Assessment.')

    weight_exam = fields.Float(
        string='Written Exam Weight (%)', default=20.0, tracking=True,
        help='Weight percentage allocated to Written Examination.')
    max_score_exam = fields.Float(
        string='Written Exam Max Score', default=100.0,
        help='Maximum score for Written Examination.')

    plan_total_weight = fields.Float(
        string='Total Plan Weight (%)', compute='_compute_plan_total_weight', store=True,
        help='Sum of weights of all active assessment components (must equal 100%).')

    has_config_pms = fields.Boolean(
        string='PMS in Global Config', compute='_compute_config_pillars')
    has_config_exam = fields.Boolean(
        string='Exam in Global Config', compute='_compute_config_pillars')

    def _compute_config_pillars(self):
        cfg = self.env['succession.assessment.config'].get_config()
        active_comps = cfg.component_ids.filtered(lambda c: c.enabled and c.active)
        comp_names = [(c.name or '').lower() for c in active_comps]
        comp_sources = [c.source for c in active_comps]
        has_pm = ('pms' in comp_sources or any('pms' in n for n in comp_names))
        has_ex = any('exam' in n or 'written' in n for n in comp_names)
        for rec in self:
            rec.has_config_pms = has_pm
            rec.has_config_exam = has_ex

    @api.depends('assessment_result_ids.weight', 'assessment_result_ids.component_id.source')
    def _compute_weight_competency(self):
        for rec in self:
            comp_lines = rec.assessment_result_ids.filtered(lambda l: l.component_id.source == 'competency_eval')
            rec.weight_competency = comp_lines[0].weight if comp_lines else 40.0

    assessment_plan_components_display = fields.Char(
        string='Testing & Appraisal Plan Summary',
        compute='_compute_assessment_plan_components_display',
    )

    @api.depends('assessment_result_ids.weight', 'assessment_result_ids.waived',
                 'assessment_result_ids.component_id.name', 'assessment_result_ids.component_id.source')
    def _compute_assessment_plan_components_display(self):
        for rec in self:
            parts = []
            for line in rec.assessment_result_ids.filtered(lambda l: l.component_id.source != 'competency_eval'):
                if line.waived:
                    parts.append(f"{line.component_id.name}: N/A (Exempt)")
                else:
                    parts.append(f"{line.component_id.name}: {line.weight:.0f}%")
            rec.assessment_plan_components_display = " | ".join(parts) if parts else "No independent testing components configured"

    # Computed Competency Score (Average of active evaluators: Manager, Self, SPMC)
    succession_competency_score = fields.Float(
        string='Succession Competency Assessment Score (%)',
        compute='_compute_succession_competency_score', store=True, digits=(16, 2),
        help='Average percentage score across all active competency evaluators (Manager, Self, SPMC).')
    competency_eval_method_display = fields.Char(
        string='Evaluation Method', compute='_compute_succession_competency_score', store=True)
    competency_breakdown_display = fields.Char(
        string='Competency Formula Breakdown',
        compute='_compute_succession_competency_score', store=True,
        help='Formula breakdown showing how individual evaluator scores are averaged.')
    competency_rater_weight_display = fields.Char(
        string='Rater Share in Competency',
        compute='_compute_succession_competency_score', store=True,
        help='Percentage weight of each active evaluator within the Competency pillar.')
    competency_eval_status_display = fields.Char(
        string='Manager Rating Status',
        compute='_compute_competency_eval_status_display',
        help='Indicates how many required competencies have been rated by the manager.')
    manager_eval_status_display = fields.Char(
        string='Manager Status', compute='_compute_competency_eval_status_display')
    self_eval_status_display = fields.Char(
        string='Self Status', compute='_compute_competency_eval_status_display')
    spmc_eval_status_display = fields.Char(
        string='SPMC Status', compute='_compute_competency_eval_status_display')

    @api.depends('eval_line_ids.manager_score',
                 'eval_line_ids.spmc_score', 'eval_line_ids.score',
                 'plan_include_manager', 'plan_include_spmc')
    def _compute_competency_eval_status_display(self):
        for rec in self:
            total_cnt = len(rec.eval_line_ids)
            if not total_cnt:
                rec.competency_eval_status_display = "No competencies mapped"
                rec.manager_eval_status_display = "No competencies mapped"
                rec.self_eval_status_display = "No competencies mapped"
                rec.spmc_eval_status_display = "No competencies mapped"
                continue

            mgr_scored = len(rec.eval_line_ids.filtered(lambda l: l.manager_score or l.score))
            self_scored = len(rec.eval_line_ids.filtered(lambda l: l.self_score))
            spmc_scored = len(rec.eval_line_ids.filtered(lambda l: l.spmc_score))

            if mgr_scored == total_cnt:
                if rec.manager_evaluation_submitted:
                    rec.manager_eval_status_display = f"Manager Rating Submitted (Score: {rec.competency_eval_score:.1f}%)"
                else:
                    rec.manager_eval_status_display = f"All {total_cnt} role competencies rated ({rec.competency_eval_score:.1f}%) - Ready to Submit"
            elif mgr_scored > 0:
                rec.manager_eval_status_display = f"In Progress: {mgr_scored} of {total_cnt} rated ({rec.competency_eval_score:.1f}%)"
            else:
                rec.manager_eval_status_display = f"Pending manager rating (0 of {total_cnt})"

            if self_scored == total_cnt:
                if rec.self_evaluation_submitted:
                    rec.self_eval_status_display = f"Self-Assessment Submitted (Score: {rec.self_assessment_score:.1f}%)"
                else:
                    rec.self_eval_status_display = f"All {total_cnt} self-assessments completed ({rec.self_assessment_score:.1f}%) - Ready to Submit"
            elif self_scored > 0:
                rec.self_eval_status_display = f"In Progress: {self_scored} of {total_cnt} rated ({rec.self_assessment_score:.1f}%)"
            else:
                rec.self_eval_status_display = f"Pending candidate self-rating (0 of {total_cnt})"

            if rec.spmc_eval_ids:
                total_assessors = len(rec.spmc_eval_ids)
                submitted_assessors = len(rec.spmc_eval_ids.filtered(lambda e: e.submitted))
                if submitted_assessors == total_assessors and total_assessors > 0:
                    rec.spmc_eval_status_display = f"All {total_assessors} Committee Submissions Complete ({rec.spmc_score:.1f}%)"
                else:
                    rec.spmc_eval_status_display = f"{submitted_assessors}/{total_assessors} Committee Members Submitted ({rec.spmc_score:.1f}%)"
            elif spmc_scored == total_cnt:
                if rec.spmc_evaluation_submitted:
                    rec.spmc_eval_status_display = f"SPMC Evaluation Submitted (Score: {rec.spmc_score:.1f}%)"
                else:
                    rec.spmc_eval_status_display = f"All {total_cnt} committee ratings completed ({rec.spmc_score:.1f}%) - Ready to Submit"
            elif spmc_scored > 0:
                rec.spmc_eval_status_display = f"In Progress: {spmc_scored} of {total_cnt} rated ({rec.spmc_score:.1f}%)"
            else:
                rec.spmc_eval_status_display = f"Pending committee review (0 of {total_cnt})"

            active_pending = []
            if rec.plan_include_manager and mgr_scored < total_cnt:
                active_pending.append(f"Manager ({mgr_scored}/{total_cnt})")
            if rec.plan_include_spmc and spmc_scored < total_cnt:
                active_pending.append(f"SPMC ({spmc_scored}/{total_cnt})")

            if not active_pending:
                rec.competency_eval_status_display = f"All {total_cnt} role competencies rated ({rec.succession_competency_score:.1f}%)"
            else:
                rec.competency_eval_status_display = f"Pending: {', '.join(active_pending)}"

    @api.depends('assessment_result_ids.weight', 'assessment_result_ids.waived')
    def _compute_plan_total_weight(self):
        for rec in self:
            active_lines = rec.assessment_result_ids.filtered(lambda l: not l.waived)
            if active_lines:
                rec.plan_total_weight = round(sum(active_lines.mapped('weight')), 2)
            else:
                cfg = self.env['succession.assessment.config'].get_config()
                rec.plan_total_weight = round(sum(cfg.component_ids.filtered(lambda c: c.enabled and c.active).mapped('weight')), 2)

    @api.depends('plan_include_manager', 'plan_include_spmc',
                 'competency_eval_score', 'spmc_score',
                 'weight_competency', 'eval_line_ids.score', 'eval_line_ids.manager_score',
                 'eval_line_ids.spmc_score')
    def _compute_succession_competency_score(self):
        for rec in self:
            evaluators = []
            scores = []
            breakdown_parts = []
            lines = rec.eval_line_ids
            total_cnt = len(lines)

            # Direct Manager
            if rec.plan_include_manager:
                mgr_scored = len(lines.filtered(lambda l: l.score or l.manager_score))
                if total_cnt and mgr_scored == total_cnt:
                    evaluators.append('Manager')
                    scores.append(rec.competency_eval_score or 0.0)
                    breakdown_parts.append(f"Manager: {rec.competency_eval_score or 0.0:.1f}%")
                elif mgr_scored > 0:
                    evaluators.append('Manager (Partial)')
                    scores.append(rec.competency_eval_score or 0.0)
                    breakdown_parts.append(f"Manager ({mgr_scored}/{total_cnt}): {rec.competency_eval_score or 0.0:.1f}%")
                else:
                    breakdown_parts.append("Manager: Pending")

            # SPMC Committee Evaluation
            if rec.plan_include_spmc:
                spmc_scored = len(lines.filtered(lambda l: l.spmc_score))
                has_submitted_spmc = bool(rec.spmc_eval_ids and any(e.submitted for e in rec.spmc_eval_ids))
                if (total_cnt and spmc_scored == total_cnt) or has_submitted_spmc:
                    evaluators.append('SPMC')
                    scores.append(rec.spmc_score or 0.0)
                    breakdown_parts.append(f"SPMC: {rec.spmc_score or 0.0:.1f}%")
                elif spmc_scored > 0:
                    evaluators.append('SPMC (Partial)')
                    scores.append(rec.spmc_score or 0.0)
                    breakdown_parts.append(f"SPMC ({spmc_scored}/{total_cnt}): {rec.spmc_score or 0.0:.1f}%")
                else:
                    breakdown_parts.append("SPMC: Pending")

            count = len(scores)
            if count > 0:
                rec.succession_competency_score = round(sum(scores) / count, 2)
                pct = round(100.0 / count, 1)
                rec.competency_rater_weight_display = f"{pct}% each" if count > 1 else "100%"
                comp_weight = rec.weight_competency or 0.0
                pts = round((rec.succession_competency_score / 100.0) * comp_weight, 2)
                if count == 1:
                    rec.competency_eval_method_display = f"{evaluators[0]} ({rec.succession_competency_score:.1f}%)"
                    rec.competency_breakdown_display = f"{' | '.join(breakdown_parts)} = {rec.succession_competency_score:.2f}% (Weighted: {pts:.2f} / {comp_weight:.1f} pts)"
                else:
                    rec.competency_eval_method_display = f"Multi-Rater Average: {', '.join(evaluators)} ({pct}% each)"
                    rec.competency_breakdown_display = f"{' | '.join(breakdown_parts)} = {rec.succession_competency_score:.2f}% (Weighted: {pts:.2f} / {comp_weight:.1f} pts)"
            else:
                rec.succession_competency_score = 0.0
                rec.competency_rater_weight_display = "Pending"
                rec.competency_eval_method_display = "Evaluations Pending"
                rec.competency_breakdown_display = "Pending Evaluator Ratings" if not breakdown_parts else ' | '.join(breakdown_parts)

    # Plan Governance & Audit Metadata
    assessment_plan_defined_by_id = fields.Many2one(
        'res.users', string='Plan Defined By', readonly=True, copy=False, index=True)
    assessment_plan_defined_date = fields.Datetime(
        string='Plan Defined On', readonly=True, copy=False)
    assessment_plan_locked = fields.Boolean(
        string='Assessment Plan Locked', compute='_compute_assessment_plan_locked', store=True)
    is_ppdd_user = fields.Boolean(
        string='Is PPDD User', compute='_compute_is_ppdd_user')

    def _compute_is_ppdd_user(self):
        is_ppdd = self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        for rec in self:
            rec.is_ppdd_user = is_ppdd

    # Multi-Rater Submission & Sign-off Tracking
    manager_evaluation_submitted = fields.Boolean(
        string='Manager Rating Submitted', default=False, readonly=True, copy=False, tracking=True)
    manager_evaluation_date = fields.Datetime(
        string='Manager Rating Submitted On', readonly=True, copy=False)
    spmc_evaluation_submitted = fields.Boolean(
        string='SPMC Deliberation Submitted', default=False, readonly=True, copy=False, tracking=True)
    spmc_evaluation_date = fields.Datetime(
        string='SPMC Deliberation Submitted On', readonly=True, copy=False)
    self_evaluation_submitted = fields.Boolean(
        string='Self Assessment Submitted', default=False, readonly=True, copy=False, tracking=True)
    self_evaluation_date = fields.Datetime(
        string='Self Assessment Submitted On', readonly=True, copy=False)

    is_direct_manager = fields.Boolean(compute='_compute_current_user_roles')
    is_spmc_user = fields.Boolean(compute='_compute_current_user_roles')
    is_self_user = fields.Boolean(compute='_compute_current_user_roles')
    can_submit_manager_eval = fields.Boolean(compute='_compute_current_user_roles')
    can_submit_spmc_eval = fields.Boolean(compute='_compute_current_user_roles')
    can_submit_self_eval = fields.Boolean(compute='_compute_current_user_roles')
    can_evaluate_competencies = fields.Boolean(
        string='Can Evaluate Competencies',
        compute='_compute_current_user_roles',
        help='True if the current user has an active, unsubmitted competency evaluation role for this candidate.'
    )
    is_current_user_eval_submitted = fields.Boolean(
        string='Evaluation Submitted for Current Viewer',
        compute='_compute_current_user_roles',
        help='True only when the relevant competency evaluation(s) have actually been formally submitted.'
    )
    can_set_readiness = fields.Boolean(
        string='Can Complete Readiness',
        compute='_compute_current_user_roles',
        help='True if current user is authorized to complete assessment and set readiness (PPDD / Admin, excluding SPMC and Line Managers).'
    )
    # Per-assessor SPMC tracking for the currently logged-in user
    my_spmc_eval_id = fields.Many2one(
        'succession.candidate.spmc.eval',
        string='My SPMC Evaluation',
        compute='_compute_my_spmc_eval',
        help='The SPMC evaluation record assigned to the current user.'
    )
    my_spmc_eval_progress = fields.Char(
        string='My Rating Progress',
        compute='_compute_my_spmc_eval',
        help='Number of competencies rated by the current SPMC assessor out of total.'
    )
    my_spmc_eval_submitted = fields.Boolean(
        string='My Evaluation Submitted',
        compute='_compute_my_spmc_eval',
        help='True if the current SPMC assessor has already submitted their evaluation.'
    )
    can_rate_spmc_competencies = fields.Boolean(
        string='Can Rate SPMC Competencies',
        compute='_compute_my_spmc_eval',
        help='True if the current user is an assigned SPMC assessor and has not yet submitted.'
    )

    @api.depends_context('uid')
    @api.depends('spmc_eval_ids', 'spmc_eval_ids.submitted', 'spmc_eval_ids.line_ids',
                 'spmc_eval_ids.line_ids.score', 'spmc_assessor_ids', 'plan_include_spmc',
                 'state', 'assessment_done')
    def _compute_my_spmc_eval(self):
        user = self.env.user
        for rec in self:
            is_assigned = bool(
                (rec.spmc_assessor_ids and user.id in rec.spmc_assessor_ids.ids) or
                (rec.spmc_assigned_user_id and rec.spmc_assigned_user_id.id == user.id)
            )
            my_eval = rec.spmc_eval_ids.filtered(lambda e: e.user_id.id == user.id)
            if my_eval:
                rated = len(my_eval.line_ids.filtered(lambda l: l.score))
                total = len(my_eval.line_ids)
                rec.my_spmc_eval_id = my_eval[0]
                rec.my_spmc_eval_submitted = my_eval[0].submitted
                rec.my_spmc_eval_progress = _('%s / %s rated') % (rated, total) if total else _('No competencies')
                rec.can_rate_spmc_competencies = bool(
                    is_assigned and
                    rec.plan_include_spmc and
                    rec.state == 'nominated' and
                    not rec.assessment_done and
                    not my_eval[0].submitted
                )
            else:
                rec.my_spmc_eval_id = False
                rec.my_spmc_eval_submitted = False
                rec.my_spmc_eval_progress = _('0 / %s rated') % len(rec.eval_line_ids) if is_assigned and rec.eval_line_ids else _('Not assigned')
                rec.can_rate_spmc_competencies = bool(
                    is_assigned and
                    rec.plan_include_spmc and
                    rec.state == 'nominated' and
                    not rec.assessment_done
                )

    @api.depends_context('uid')
    @api.depends('state', 'assessment_done', 'manager_evaluation_submitted', 'spmc_evaluation_submitted',
                 'plan_include_manager', 'plan_include_spmc', 'spmc_assessor_ids',
                 'spmc_eval_ids', 'spmc_eval_ids.submitted', 'spmc_eval_ids.line_ids.score',
                 'eval_line_ids', 'eval_line_ids.manager_score', 'eval_line_ids.spmc_score')
    def _compute_current_user_roles(self):
        user = self.env.user
        is_admin = bool(user.has_group('bunna_succession_management.group_succession_admin') or user.id == 1)
        is_spmc = bool(user.has_group('bunna_succession_management.group_succession_spmc'))
        is_ppdd = bool(user.has_group('bunna_succession_management.group_succession_ppdd'))
        is_manager_group = bool(user.has_group('bunna_succession_management.group_succession_line_manager'))
        for rec in self:
            emp = rec.sudo().employee_id
            # Direct Coach or Line Manager
            is_coach_or_mgr = bool(emp and (
                (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
                (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
                (rec.sudo().parent_id and rec.sudo().parent_id.user_id and rec.sudo().parent_id.user_id.id == user.id) or
                (rec.sudo().coach_id and rec.sudo().coach_id.user_id and rec.sudo().coach_id.user_id.id == user.id)
            ))
            # Assigned SPMC Assessor or member of SPMC committee
            is_assigned_spmc = bool(
                (rec.spmc_assigned_user_id and rec.spmc_assigned_user_id.id == user.id) or
                (rec.spmc_assessor_ids and user.id in rec.spmc_assessor_ids.ids)
            )
            is_authorized_spmc = bool(is_spmc or is_assigned_spmc)
            is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)

            rec.is_direct_manager = is_coach_or_mgr
            rec.is_spmc_user = is_authorized_spmc
            rec.is_self_user = is_self

            # Readiness Authority: Strictly PPDD Officers and Admins.
            # SPMC members and candidate line managers cannot complete assessment / set readiness.
            if is_admin:
                rec.can_set_readiness = True
            elif is_spmc or is_coach_or_mgr or is_manager_group or is_self:
                rec.can_set_readiness = False
            else:
                rec.can_set_readiness = bool(is_ppdd)

            if not rec.assessment_criteria_synced or not rec.has_competency_assessment:
                rec.can_submit_manager_eval = False
                rec.can_submit_spmc_eval = False
                rec.can_submit_self_eval = False
                rec.can_evaluate_competencies = False
                rec.is_current_user_eval_submitted = False
                continue

            all_lines = rec.eval_line_ids
            has_lines = bool(all_lines)
            all_mgr_rated = has_lines and all(bool(l.manager_score) for l in all_lines)
            all_spmc_rated = has_lines and all(bool(l.spmc_score) for l in all_lines)
            all_self_rated = has_lines and all(bool(l.self_score) for l in all_lines)

            rec.can_submit_manager_eval = bool(
                rec.state == 'nominated' and
                rec.plan_include_manager and
                not rec.manager_evaluation_submitted and
                (is_coach_or_mgr or is_admin or is_ppdd) and
                all_mgr_rated
            )

            user_spmc_eval = rec.spmc_eval_ids.filtered(lambda e: e.user_id.id == user.id)
            if user_spmc_eval:
                user_all_rated = bool(user_spmc_eval.line_ids and all(bool(l.score) for l in user_spmc_eval.line_ids))
                rec.can_submit_spmc_eval = bool(
                    rec.state == 'nominated' and
                    rec.plan_include_spmc and
                    is_assigned_spmc and
                    not user_spmc_eval[0].submitted and
                    user_all_rated
                )
            else:
                rec.can_submit_spmc_eval = bool(
                    rec.state == 'nominated' and
                    rec.plan_include_spmc and
                    is_assigned_spmc and
                    not rec.spmc_evaluation_submitted and
                    all_spmc_rated
                )

            rec.can_submit_self_eval = False

            # Determine whether current user can still evaluate or edit competencies.
            # Strictly restricted to evaluators configured in the assessment plan:
            # - Manager: if plan_include_manager and user is Coach / Line Manager and not yet submitted
            # - Assigned SPMC: if plan_include_spmc and user is an assigned SPMC assessor and not yet submitted
            # - Candidate: if plan_include_self and user is the candidate and not yet submitted
            user_can_eval = False
            if rec.state == 'nominated' and not rec.assessment_done:
                can_eval_as_mgr = bool(
                    rec.plan_include_manager and
                    is_coach_or_mgr and
                    not rec.manager_evaluation_submitted
                )

                can_eval_as_spmc = False
                if rec.plan_include_spmc and is_assigned_spmc:
                    if user_spmc_eval:
                        can_eval_as_spmc = not user_spmc_eval[0].submitted
                    else:
                        can_eval_as_spmc = True

                can_eval_as_self = bool(
                    rec.plan_include_self and
                    is_self and
                    not rec.self_evaluation_submitted
                )

                user_can_eval = can_eval_as_mgr or can_eval_as_spmc or can_eval_as_self

            rec.can_evaluate_competencies = user_can_eval

            # Lock banner: display only to the assigned evaluator whose evaluation is submitted
            if is_coach_or_mgr and rec.plan_include_manager:
                rec.is_current_user_eval_submitted = bool(rec.manager_evaluation_submitted)
            elif is_assigned_spmc and rec.plan_include_spmc:
                if user_spmc_eval:
                    rec.is_current_user_eval_submitted = bool(user_spmc_eval[0].submitted)
                else:
                    rec.is_current_user_eval_submitted = False
            elif is_self and rec.plan_include_self:
                rec.is_current_user_eval_submitted = bool(rec.self_evaluation_submitted)
            else:
                rec.is_current_user_eval_submitted = False

    def action_submit_manager_evaluation(self):
        """Direct Manager formally signs off and submits competency ratings."""
        self.ensure_one()
        user = self.env.user
        emp = self.sudo().employee_id
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_coach_or_mgr = bool(emp and (
            (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
            (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
            (self.sudo().parent_id and self.sudo().parent_id.user_id and self.sudo().parent_id.user_id.id == user.id) or
            (self.sudo().coach_id and self.sudo().coach_id.user_id and self.sudo().coach_id.user_id.id == user.id)
        ))

        if not (is_coach_or_mgr or is_ppdd or is_admin):
            coach_mgr_name = emp.coach_id.name or (emp.parent_id.name if emp and emp.parent_id else 'Coach / Manager')
            raise AccessError(_("Security Restriction: Only the candidate's Coach or Line Manager (%s), PPDD Officers, or Administrators can submit the coach/manager evaluation.") % coach_mgr_name)

        if not self.eval_line_ids:
            raise UserError(_("No competencies found to evaluate."))

        unrated = self.eval_line_ids.filtered(lambda l: not l.manager_score)
        if unrated:
            names = ', '.join(unrated.mapped('competency_id.name'))
            raise UserError(_("Incomplete Manager Evaluation! Please rate all competencies before submitting. Missing: %s") % names)

        self.sudo().write({
            'manager_evaluation_submitted': True,
            'manager_evaluation_date': fields.Datetime.now(),
        })
        self.sudo()._compute_competency_eval_score()
        self.sudo()._compute_succession_competency_score()
        self.sudo()._refresh_assessment_scores()

        # Mark pending manager To-Do activity as completed
        try:
            self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).activity_feedback(['mail.mail_activity_data_todo'], user_id=user.id)
        except Exception:
            pass

        self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_(
            "<b>Direct Manager Competency Evaluation Submitted</b><br/>"
            "<ul>"
            "<li><b>Evaluated By:</b> %s</li>"
            "<li><b>Submission Date:</b> %s</li>"
            "<li><b>Manager Competency Score:</b> %.1f%%</li>"
            "</ul>"
        ) % (user.name, fields.Date.today(), self.competency_eval_score))

        return self._notify_and_reload(
            _('Manager Evaluation Submitted'),
            _('Direct Manager evaluation for %s successfully submitted (Score: %.1f%%).') % (self.employee_id.name, self.competency_eval_score),
        )

    def action_submit_spmc_evaluation(self):
        """SPMC Executive Committee formally signs off and submits consensus ratings."""
        self.ensure_one()
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        is_assigned_spmc = bool(
            (self.spmc_assigned_user_id and self.spmc_assigned_user_id.id == user.id) or
            (self.spmc_assessor_ids and user.id in self.spmc_assessor_ids.ids)
        )

        if not (is_spmc or is_assigned_spmc or is_admin):
            raise AccessError(_("Security Restriction: Only the assigned SPMC Assessor or SPMC Executive Committee members can submit committee deliberations."))

        if not self.eval_line_ids:
            raise UserError(_("No competencies found to evaluate."))

        # Ensure every assigned SPMC assessor has an individual evaluation record before checking completion
        self._sync_spmc_eval_records()
        user_spmc_eval = self.spmc_eval_ids.filtered(lambda e: e.user_id.id == user.id)
        if user_spmc_eval:
            unrated = user_spmc_eval.line_ids.filtered(lambda l: not l.score)
            if unrated:
                names = ', '.join(unrated.mapped('competency_id.name'))
                raise UserError(_("Incomplete SPMC Evaluation! Please rate all competencies before submitting. Missing: %s") % names)
            user_spmc_eval.write({
                'submitted': True,
                'submitted_date': fields.Datetime.now(),
            })
            all_submitted = all(e.submitted for e in self.spmc_eval_ids)
            if all_submitted:
                self.sudo().write({
                    'spmc_evaluation_submitted': True,
                    'spmc_evaluation_date': fields.Datetime.now(),
                    'spmc_assigned_user_id': user.id,
                })
            else:
                self.sudo().write({
                    'spmc_evaluation_submitted': False,
                    'spmc_evaluation_date': False,
                    'spmc_assigned_user_id': user.id,
                })
        else:
            unrated = self.eval_line_ids.filtered(lambda l: not l.spmc_score)
            if unrated:
                names = ', '.join(unrated.mapped('competency_id.name'))
                raise UserError(_("Incomplete SPMC Evaluation! Please record committee ratings for all competencies before submitting. Missing: %s") % names)
            if not self.spmc_eval_ids or all(e.submitted for e in self.spmc_eval_ids):
                self.sudo().write({
                    'spmc_evaluation_submitted': True,
                    'spmc_evaluation_date': fields.Datetime.now(),
                    'spmc_assigned_user_id': user.id,
                })
        self.sudo()._compute_spmc_score()
        self.sudo()._compute_succession_competency_score()
        self.sudo()._refresh_assessment_scores()

        # Mark pending SPMC To-Do activity as completed
        try:
            self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).activity_feedback(['mail.mail_activity_data_todo'], user_id=user.id)
        except Exception:
            pass

        total_evals = len(self.spmc_eval_ids)
        submitted_evals = len(self.spmc_eval_ids.filtered(lambda e: e.submitted))

        if user_spmc_eval:
            if all_submitted:
                body_msg = _(
                    "<b>SPMC Committee Competency Evaluation — Final Submission Complete</b><br/>"
                    "All %d assigned committee members have submitted their separate evaluations.<br/>"
                    "<ul>"
                    "<li><b>Last Submitted By:</b> %s</li>"
                    "<li><b>Submission Date:</b> %s</li>"
                    "<li><b>Combined Committee Score:</b> %.1f%%</li>"
                    "</ul>"
                ) % (total_evals, user.name, fields.Date.today(), self.spmc_score)
                notif_msg = _('All %d committee evaluations for %s have been submitted (Combined Score: %.1f%%).') % (total_evals, self.employee_id.name, self.spmc_score)
            else:
                body_msg = _(
                    "<b>SPMC Committee Member Evaluation Submitted</b><br/>"
                    "<ul>"
                    "<li><b>Assessor:</b> %s</li>"
                    "<li><b>Progress:</b> %d of %d committee evaluations submitted</li>"
                    "<li><b>Assessor Score:</b> %.1f%%</li>"
                    "<li><b>Current Average:</b> %.1f%%</li>"
                    "</ul>"
                ) % (user.name, submitted_evals, total_evals, user_spmc_eval[0].score, self.spmc_score)
                notif_msg = _('Your individual SPMC evaluation for %s was submitted (%d of %d committee members submitted).') % (self.employee_id.name, submitted_evals, total_evals)
        else:
            body_msg = _(
                "<b>SPMC Committee Competency Evaluation Submitted</b><br/>"
                "<ul>"
                "<li><b>Submitted By:</b> %s</li>"
                "<li><b>Submission Date:</b> %s</li>"
                "<li><b>Committee Score:</b> %.1f%%</li>"
                "</ul>"
            ) % (user.name, fields.Date.today(), self.spmc_score)
            notif_msg = _('SPMC committee evaluation for %s successfully submitted (Score: %.1f%%).') % (self.employee_id.name, self.spmc_score)

        self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=body_msg)

        return self._notify_and_reload(
            _('SPMC Evaluation Submitted'),
            notif_msg,
        )

    def action_open_my_spmc_evaluation(self):
        """Open the competency rating modal for the current SPMC assessor's individual evaluation.

        Each assigned committee member submits their evaluation independently.
        This opens the first unrated (or first) competency in the current user's
        succession.candidate.spmc.eval.line sequence.
        """
        self.ensure_one()
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        is_assigned_spmc = bool(
            (self.spmc_assigned_user_id and self.spmc_assigned_user_id.id == user.id) or
            (self.spmc_assessor_ids and user.id in self.spmc_assessor_ids.ids)
        )

        if not (is_spmc or is_assigned_spmc or is_admin):
            raise AccessError(_(
                "Security Restriction: Only assigned SPMC committee members can rate competencies."
            ))

        if not self.eval_line_ids:
            raise UserError(_("No competencies found to evaluate. Please ensure role competency mapping is configured."))

        # Ensure the assessor has an spmc_eval record and competency lines
        my_eval = self.spmc_eval_ids.filtered(lambda e: e.user_id.id == user.id)
        if not my_eval:
            my_eval = self.env['succession.candidate.spmc.eval'].sudo().create({
                'candidate_id': self.id,
                'user_id': user.id,
            })
            if user.id not in self.spmc_assessor_ids.ids:
                self.sudo().write({'spmc_assessor_ids': [(4, user.id)]})
        else:
            my_eval = my_eval[0]

        if my_eval.submitted and not is_admin:
            raise UserError(_(
                "You have already submitted your SPMC evaluation for this candidate. "
                "Contact an administrator to reopen if corrections are required."
            ))

        # Sync missing eval lines for this assessor
        existing_eval_line_ids = set(my_eval.line_ids.mapped('eval_line_id.id'))
        new_lines = []
        for el in self.eval_line_ids:
            if el.id not in existing_eval_line_ids:
                new_lines.append({'spmc_eval_id': my_eval.id, 'eval_line_id': el.id})
        if new_lines:
            self.env['succession.candidate.spmc.eval.line'].sudo().create(new_lines)
            my_eval.invalidate_recordset()

        # Open the first unrated competency line (or first if all rated)
        unrated = my_eval.line_ids.filtered(lambda l: not l.score)
        # We navigate via the eval_line_id (succession.candidate.eval.line) for the shared modal
        eval_line_to_open = unrated[0].eval_line_id if unrated else my_eval.line_ids[0].eval_line_id if my_eval.line_ids else False

        if not eval_line_to_open:
            raise UserError(_("No competency lines to evaluate. Please contact PPDD to load role competencies."))

        return eval_line_to_open.action_open_eval_modal()

    def action_submit_self_evaluation(self):
        """Candidate formally signs off and submits their self-assessment."""
        self.ensure_one()
        user = self.env.user
        emp = self.sudo().employee_id
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_self = bool(emp and emp.user_id and emp.user_id.id == user.id)

        if not (is_self or is_admin):
            raise AccessError(_("Security Restriction: Only the candidate (%s) or an Administrator can submit this self-assessment.") % (emp.name or 'Employee'))

        if not self.eval_line_ids:
            raise UserError(_("No competencies found to evaluate."))

        unrated = self.eval_line_ids.filtered(lambda l: not l.self_score)
        if unrated:
            names = ', '.join(unrated.mapped('competency_id.name'))
            raise UserError(_("Incomplete Self-Assessment! Please complete ratings for all competencies before submitting. Missing: %s") % names)

        self.sudo().write({
            'self_evaluation_submitted': True,
            'self_evaluation_date': fields.Datetime.now(),
        })
        self.sudo()._compute_self_assessment_score()
        self.sudo()._compute_succession_competency_score()
        self.sudo()._refresh_assessment_scores()

        # Mark pending self-assessment To-Do activity as completed
        try:
            self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).activity_feedback(['mail.mail_activity_data_todo'], user_id=user.id)
        except Exception:
            pass

        self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_(
            "<b>Candidate Self-Assessment Submitted</b><br/>"
            "<ul>"
            "<li><b>Submitted By:</b> %s</li>"
            "<li><b>Submission Date:</b> %s</li>"
            "<li><b>Self Score:</b> %.1f%%</li>"
            "</ul>"
        ) % (user.name, fields.Date.today(), self.self_assessment_score))

        return self._notify_and_reload(
            _('Self-Assessment Submitted'),
            _('Your self-assessment for %s has been submitted successfully.') % (self.critical_position_id.job_id.name or 'Critical Role'),
        )

    def send_self_assessment_notification(self):
        """Send notification (Discuss chat, to-do activity, email) to candidate requesting self-assessment."""
        for rec in self:
            emp = rec.sudo().employee_id
            if not emp:
                continue
            user = emp.user_id
            pos_title = rec.critical_position_id.job_id.name or rec.critical_position_id.name or _('Critical Position')
            dept_name = rec.critical_position_id.department_id.name or ''

            message = (
                f"Dear {emp.name},\n\n"
                f"You have been officially nominated as a candidate for the succession role '{pos_title}'"
                + (f" in {dept_name}" if dept_name else "") + ".\n\n"
                f"As part of the Bunna Bank succession readiness process, candidate self-assessment is required. "
                f"Please log in and open 'Employees > My Succession Assessment' to review the required competencies "
                f"and record your self-assessment ratings.\n\n"
                f"Target Position: {pos_title}\n"
                f"Department: {dept_name or 'N/A'}\n\n"
                f"Best regards,\n"
                f"Bunna Bank Succession Planning Team"
            )

            # 1. Discuss chat channel notification
            if user and user.partner_id:
                try:
                    channel = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[user.partner_id.id])
                    channel.message_post(
                        body=message,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception:
                    pass

                # 2. To-Do Activity
                try:
                    existing_act = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'succession.candidate'),
                        ('res_id', '=', rec.id),
                        ('user_id', '=', user.id),
                        ('summary', '=', f'Succession Self-Assessment: {pos_title}')
                    ], limit=1)
                    if not existing_act:
                        rec.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=user.id,
                            summary=f'Succession Self-Assessment: {pos_title}',
                            note=message,
                            date_deadline=fields.Date.today(),
                        )
                except Exception:
                    pass

            # 3. Email notification
            emp_email = emp.work_email or emp.private_email or (user.email if user else False)
            if emp_email:
                try:
                    mail_vals = {
                        'subject': _('Action Required: Succession Self-Assessment for %s') % pos_title,
                        'body_html': f"""
                            <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333; line-height: 1.5;">
                                <p>Dear <b>{emp.name}</b>,</p>
                                <p>You have been officially nominated as a candidate for the succession role <b>{pos_title}</b> at Bunna Bank.</p>
                                <p>As part of the succession evaluation process, candidate self-assessment is mandatory. Please log in to Odoo and complete your self-assessment under <b>Employees &gt; My Succession Assessment</b>.</p>
                                <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #541718; border-radius: 6px; padding: 12px 16px; margin: 15px 0;">
                                    <b>Target Critical Position:</b> {pos_title}<br/>
                                    <b>Department:</b> {dept_name or 'N/A'}<br/>
                                    <b>Nomination Date:</b> {rec.nomination_date or fields.Date.today()}
                                </div>
                                <p>Best regards,<br/><b>Bunna Bank Succession Planning Team</b></p>
                            </div>
                        """,
                        'email_to': emp_email,
                    }
                    self.env['mail.mail'].sudo().create(mail_vals)
                except Exception:
                    pass

            # Chatter log
            try:
                rec.message_post(body=_("Self-assessment notification sent to candidate %s.") % emp.name)
            except Exception:
                pass

    def action_send_self_assessment_notification(self):
        """Manual trigger by PPDD/Admin to send or resend self-assessment notification."""
        for rec in self:
            if not rec.plan_include_self:
                raise UserError(_("Self-assessment is not included in the assessment plan for candidate %s.") % rec.employee_id.name)
            if not rec.eval_line_ids:
                try:
                    rec.action_populate_competency_eval_lines()
                except Exception:
                    pass
            rec.send_self_assessment_notification()
        return self._notify_and_reload(
            _('Notification Sent'),
            _('Self-assessment notification sent to candidate.'),
        )


    # --- Tenure ---
    current_tenure_months = fields.Integer(
        string='Experience (Months)', compute='_compute_tenure', store=True)

    # ==========================================================================
    # COMPUTE METHODS
    # ==========================================================================

    @api.depends('employee_id', 'critical_position_id')
    def _compute_display_name(self):
        for rec in self:
            emp_sudo = rec.sudo().employee_id
            emp = emp_sudo.name if emp_sudo else '?'
            pos = rec.critical_position_id.display_name if rec.critical_position_id else '?'
            rec.display_name = '%s → %s' % (emp, pos)

    @api.depends('employee_id')
    def _compute_tenure(self):
        from dateutil.relativedelta import relativedelta
        from odoo.fields import Date
        for rec in self:
            emp = rec.employee_id
            if emp:
                # Find the earliest contract start date for this employee
                oldest_contract = self.env['hr.version'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('contract_date_start', '!=', False)
                ], order='contract_date_start asc', limit=1)
                
                if oldest_contract:
                    start_date = oldest_contract.contract_date_start
                    end_date = Date.today()
                    # Try to get termination date if it exists
                    if hasattr(emp, 'service_termination_date') and getattr(emp, 'service_termination_date'):
                        end_date = emp.service_termination_date
                    elif hasattr(emp, 'departure_date') and getattr(emp, 'departure_date'):
                        end_date = emp.departure_date
                        
                    delta = relativedelta(end_date, start_date)
                    rec.current_tenure_months = delta.years * 12 + delta.months
                else:
                    rec.current_tenure_months = 0
            else:
                rec.current_tenure_months = 0

    @api.depends('employee_id')
    def _compute_pms_score(self):
        for rec in self:
            if rec.latest_pms_score and not self.env.context.get('force_recompute_pms'):
                # Preserve existing PMS score if already set
                continue
            pms_score = 0.0
            if rec.employee_id:
                if hasattr(rec.employee_id, 'pms_score') and rec.employee_id.pms_score:
                    pms_score = float(rec.employee_id.pms_score)
                elif hasattr(rec.employee_id, 'contract_id') and rec.employee_id.contract_id and hasattr(rec.employee_id.contract_id, 'pms_score') and rec.employee_id.contract_id.pms_score:
                    pms_score = float(rec.employee_id.contract_id.pms_score)
                elif 'hr.version' in self.env:
                    ver = self.env['hr.version'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                    ], order='id desc', limit=1)
                    if ver and hasattr(ver, 'pms_score') and ver.pms_score:
                        pms_score = float(ver.pms_score)
                if not pms_score and 'hr.pms.result' in self.env:
                    result = self.env['hr.pms.result'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                    ], order='id desc', limit=1)
                    if result:
                        pms_score = getattr(result, 'final_score', 0.0) or 0.0
                if not pms_score and 'hr.appraisal' in self.env:
                    appraisal = self.env['hr.appraisal'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('state', '=', 'done'),
                    ], order='date_close desc', limit=1)
                    if appraisal:
                        pms_score = getattr(appraisal, 'rating', 0.0) or 0.0
            rec.latest_pms_score = pms_score

    @api.depends('eval_line_ids.score', 'eval_line_ids.manager_score',
                 'eval_line_ids.required_proficiency', 'eval_line_ids.achievement_status',
                 'competency_gap_ids', 'competency_gap_ids.achievement_status')
    def _compute_competency_summary(self):
        for rec in self:
            # 1. Primary: Compute directly from Succession Competency Evaluation lines
            if rec.eval_line_ids:
                total = len(rec.eval_line_ids)
                gap_lines = rec.eval_line_ids.filtered(lambda l: l.achievement_status == 'below')
                rec.competency_gap_count = len(gap_lines)
                rec.competency_eligible = (rec.competency_gap_count == 0)
                met = total - rec.competency_gap_count
                rec.competency_match_percent = round((met / total) * 100, 1) if total else 0.0
            # 2. Fallback to competency_gap_ids if populated
            elif rec.competency_gap_ids:
                total = len(rec.competency_gap_ids)
                gap_count = len(rec.competency_gap_ids.filtered(lambda g: g.achievement_status == 'below'))
                rec.competency_gap_count = gap_count
                rec.competency_eligible = (gap_count == 0)
                met = total - gap_count
                rec.competency_match_percent = round((met / total) * 100, 1) if total else 0.0
            else:
                rec.competency_gap_count = 0
                rec.competency_match_percent = 0.0
                rec.competency_eligible = False

    @api.depends('employee_id', 'latest_pms_score', 'competency_match_percent')
    def _compute_9box_ratings(self):
        """
        Dynamically determine candidate 9-box ratings based on the
        score ranges defined directly on each 9-box cell configuration.
        """
        cells = self.env['succession.ninebox.cell'].search([])
        for rec in self:
            pms = rec.latest_pms_score or 0.0
            pot_pct = rec.competency_match_percent or 0.0

            # 1. Determine Performance Rating based on configured PMS ranges
            # Normalize PMS to cell range scale (typically 0-100)
            max_cell_pms = max(cells.mapped('max_pms_score')) if cells else 100.0
            if max_cell_pms > 5.0 and 0.0 < pms <= 5.0:
                pms_for_cell = (pms / 5.0) * 100.0
            elif max_cell_pms <= 5.0 and pms > 5.0:
                pms_for_cell = (pms / 100.0) * 5.0
            else:
                pms_for_cell = pms

            perf_rating = False
            for pr in ['high', 'medium', 'low']:
                pr_cells = cells.filtered(lambda c: c.performance_rating == pr)
                if pr_cells:
                    min_p = min(pr_cells.mapped('min_pms_score'))
                    max_p = max(pr_cells.mapped('max_pms_score'))
                    if min_p <= pms_for_cell <= max_p:
                        perf_rating = pr
                        break

            # Fallback / boundary handling for performance
            if not perf_rating and cells:
                high_cells = cells.filtered(lambda c: c.performance_rating == 'high')
                if high_cells and pms_for_cell >= min(high_cells.mapped('min_pms_score')):
                    perf_rating = 'high'
                else:
                    med_cells = cells.filtered(lambda c: c.performance_rating == 'medium')
                    if med_cells and pms_for_cell >= min(med_cells.mapped('min_pms_score')):
                        perf_rating = 'medium'
                    else:
                        perf_rating = 'low'
            elif not perf_rating:
                perf_rating = 'high' if pms_for_cell >= 85.0 else ('medium' if pms_for_cell >= 70.0 else 'low')

            # 2. Determine Potential Rating based on configured Competency Match ranges
            pot_rating = False
            for pot in ['high', 'medium', 'low']:
                pot_cells = cells.filtered(lambda c: c.potential_rating == pot)
                if pot_cells:
                    min_cm = min(pot_cells.mapped('min_potential_match'))
                    max_cm = max(pot_cells.mapped('max_potential_match'))
                    if min_cm <= pot_pct <= max_cm:
                        pot_rating = pot
                        break

            # Fallback / boundary handling for potential
            if not pot_rating and cells:
                high_pot_cells = cells.filtered(lambda c: c.potential_rating == 'high')
                if high_pot_cells and pot_pct >= min(high_pot_cells.mapped('min_potential_match')):
                    pot_rating = 'high'
                else:
                    med_pot_cells = cells.filtered(lambda c: c.potential_rating == 'medium')
                    if med_pot_cells and pot_pct >= min(med_pot_cells.mapped('min_potential_match')):
                        pot_rating = 'medium'
                    else:
                        pot_rating = 'low'
            elif not pot_rating:
                pot_rating = 'high' if pot_pct >= 80.0 else ('medium' if pot_pct >= 60.0 else 'low')

            rec.performance_rating = perf_rating
            rec.potential_rating = pot_rating

            # 3. Match the exact 9-box cell corresponding to (performance_rating, potential_rating)
            matched_cell = cells.filtered(
                lambda c: c.performance_rating == perf_rating and c.potential_rating == pot_rating
            )
            if matched_cell:
                rec.nine_box_label = matched_cell[0].name
                rec.is_high_potential = (pot_rating == 'high' and perf_rating == 'high')
            else:
                rec.nine_box_label = 'Not Assessed'
                rec.is_high_potential = False

    @api.depends('performance_rating', 'potential_rating', 'latest_pms_score', 'competency_match_percent')
    def _compute_9box_label(self):
        """Compute human-readable 9-box cell label dynamically from configured cell definitions."""
        cells = self.env['succession.ninebox.cell'].search([])
        for rec in self:
            if rec.performance_rating and rec.potential_rating:
                coord_match = cells.filtered(
                    lambda c: c.performance_rating == rec.performance_rating and
                              c.potential_rating == rec.potential_rating
                )
                if coord_match:
                    rec.nine_box_label = coord_match[0].name
                    rec.is_high_potential = (coord_match[0].potential_rating == 'high' and coord_match[0].performance_rating == 'high')
                    continue
            rec.nine_box_label = 'Not Assessed'
            rec.is_high_potential = False

    @api.depends('employee_id', 'critical_position_id', 'critical_position_id.required_grade_id')
    def _compute_grade_gap(self):
        for rec in self:
            emp = rec.sudo().employee_id
            cp = rec.critical_position_id

            target_grade_code = None
            target_name = ''
            if cp and cp.required_grade_id:
                target_name = getattr(cp.required_grade_id, 'name', '') or getattr(cp.required_grade_id, 'grade_name', '') or getattr(cp.required_grade_id, 'display_name', '') or ''
                raw_code = getattr(cp.required_grade_id, 'code', '') or getattr(cp.required_grade_id, 'grade_code', '') or target_name
                try:
                    target_grade_code = int(''.join(filter(str.isdigit, raw_code))) or None
                except Exception:
                    target_grade_code = None

            emp_grade_code = None
            emp_grade_name = ''
            emp_grade_obj = getattr(emp, 'job_grade', False) or getattr(emp, 'grade_id', False)
            if emp_grade_obj:
                emp_grade_name = getattr(emp_grade_obj, 'grade_name', '') or getattr(emp_grade_obj, 'name', '') or getattr(emp_grade_obj, 'display_name', '') or getattr(emp_grade_obj, 'code', '') or ''
                raw_code = getattr(emp_grade_obj, 'grade_code', '') or getattr(emp_grade_obj, 'code', '') or emp_grade_name
                try:
                    emp_grade_code = int(''.join(filter(str.isdigit, raw_code))) or None
                except Exception:
                    emp_grade_code = None

            gap = 0
            if target_grade_code is not None and emp_grade_code is not None:
                gap = max(target_grade_code - emp_grade_code, 0)
                if gap == 0:
                    disp = _('Same Grade / Direct Feeder')
                elif gap == 1:
                    disp = _('Feeder Grade (1 Step Below)')
                elif gap == 2:
                    disp = _('Feeder Grade (2 Steps Below)')
                else:
                    disp = _('Seniority Gap (%d Steps Below)') % gap
            elif emp_grade_name and target_name:
                disp = f"{emp_grade_name} -> {target_name}"
            else:
                disp = _('Grade Aligned')

            rec.grade_gap = gap
            rec.grade_gap_display = disp
            rec.current_grade_display = emp_grade_name or 'N/A'
            rec.target_grade_display = target_name or 'N/A'

    @api.depends('dev_plan_ids', 'dev_plan_ids.state', 'dev_plan_ids.overall_progress', 'dev_plan_ids.end_date')
    def _compute_active_idp_info(self):
        for rec in self:
            plans = rec.dev_plan_ids.filtered(lambda p: p.state not in ('cancelled',))
            active_plan = plans.filtered(lambda p: p.state in ('active', 'under_review'))
            if not active_plan and plans:
                active_plan = plans.filtered(lambda p: p.state in ('completed', 'completed_ahead')) or plans

            selected = active_plan[0] if active_plan else False
            rec.active_idp_id = selected
            if selected:
                rec.active_idp_progress = selected.overall_progress or 0
            elif 'hr.career.idp' in self.env and rec.employee_id:
                job_id = rec.critical_position_id.job_id.id if rec.critical_position_id and rec.critical_position_id.job_id else False
                career_idp = self.env['hr.career.idp'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('target_job_id', '=', job_id),
                    ('state', 'not in', ['cancelled']),
                ], order='id desc', limit=1)
                if not career_idp:
                    career_idp = self.env['hr.career.idp'].sudo().search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('state', 'not in', ['cancelled']),
                    ], order='id desc', limit=1)
                if career_idp and career_idp.line_ids:
                    total_lines = len(career_idp.line_ids)
                    done_lines = len(career_idp.line_ids.filtered(lambda l: l.status == 'completed'))
                    rec.active_idp_progress = int((done_lines / total_lines) * 100) if total_lines else 0
                else:
                    rec.active_idp_progress = 0
            else:
                rec.active_idp_progress = 0

    @api.depends('readiness_level_id', 'nomination_date', 'active_idp_id',
                 'active_idp_id.end_date', 'active_idp_id.actual_completion_date',
                 'active_idp_id.state')
    def _compute_target_readiness_date(self):
        today = fields.Date.today()
        for rec in self:
            target_date = False
            active_plan = rec.active_idp_id

            # Priority 1: Completed IDP (Ready Now!)
            if active_plan and active_plan.state in ('completed', 'completed_ahead'):
                target_date = active_plan.actual_completion_date or today

            # Priority 2: Ready for Deployment Level (Ready Now!)
            elif rec.readiness_level_id and rec.readiness_level_id.is_ready_for_deployment:
                target_date = today

            # Priority 3: Active IDP scheduled End Date
            elif active_plan and active_plan.end_date:
                target_date = active_plan.end_date

            # Priority 4: Calculated from Readiness Level Month Horizon
            elif rec.readiness_level_id:
                base_date = rec.nomination_date or today
                months = rec.readiness_level_id.max_months or 12
                target_date = base_date + relativedelta(months=months)

            # Fallback
            if not target_date:
                target_date = today + relativedelta(years=1)

            rec.target_readiness_date = target_date
            rec.target_readiness_year = target_date.year

            # Format human-friendly display
            if rec.readiness_level_id and rec.readiness_level_id.is_ready_for_deployment:
                rec.target_readiness_display = _("Ready Now (Immediate)")
            else:
                rec.target_readiness_display = target_date.strftime("%B %Y")

    @api.depends('final_assessment_score', 'assessment_status', 'competency_match_percent',
                 'latest_pms_score', 'nine_box_label', 'is_high_potential', 'grade_gap')
    def _compute_system_readiness_suggestion(self):
        """
        Intelligent Multi-Factor Readiness Determination (BRD FR-TAR-002, FR-TAR-006, FR-SEL-005).
        Combines:
        1. Succession Final Assessment Score (Exam + Manager + SPMC + PMS).
        2. Role Competency Match % from Gap Analysis (if competencies mapped).
        3. 9-Box Grid Position & PMS Performance Consistency.
        4. Career Job Grade Gap.
        """
        levels = self.env['succession.readiness.level'].search([('active', '=', True)], order='sequence asc, id asc')
        ready_now = levels[0] if levels else False
        ready_soon = levels[1] if len(levels) > 1 else ready_now
        ready_later = levels[-1] if levels else False

        for rec in self:
            if not levels:
                rec.system_readiness_suggestion_id = False
                continue

            final_score = rec.final_assessment_score or 0.0
            comp_match = rec.competency_match_percent or 0.0
            pms = rec.latest_pms_score or 0.0
            if 0.0 < pms <= 5.0:
                pms = (pms / 5.0) * 100.0
            nine_box = (rec.nine_box_label or '').lower()
            is_star = bool(rec.is_high_potential or 'star' in nine_box or 'high potential' in nine_box)
            is_assessed = bool(rec.assessment_status in ('ready', 'finalized') and final_score > 0)
            gg = rec.grade_gap or 0

            # Advisory Recommendation derived from holistic multi-rater assessment and 9-Box
            # (HR/PPDD holds explicit authority to set official candidate readiness level)

            # Standard Rule 1: Succession Assessment has been scored (Multi-Rater, Exam, PMS)
            if is_assessed:
                if final_score >= 80.0 and (pms >= 75.0 or is_star) and gg <= 1:
                    rec.system_readiness_suggestion_id = ready_now
                elif final_score >= 60.0 or is_star or pms >= 80.0:
                    rec.system_readiness_suggestion_id = ready_soon
                else:
                    rec.system_readiness_suggestion_id = ready_later

            # Standard Rule 2: Competency Gap Analysis has been evaluated with mapped competencies (> 0%)
            elif comp_match > 0:
                if comp_match >= 85.0 and (pms >= 75.0 or is_star) and gg <= 1:
                    rec.system_readiness_suggestion_id = ready_now
                elif comp_match >= 60.0 or is_star or pms >= 80.0:
                    rec.system_readiness_suggestion_id = ready_soon
                else:
                    rec.system_readiness_suggestion_id = ready_later

            # Standard Rule 3: Baseline Nomination stage (Evaluated on PMS Appraisal & 9-Box position)
            else:
                if is_star and pms >= 85.0:
                    rec.system_readiness_suggestion_id = ready_soon
                elif pms >= 75.0 or 'solid' in nine_box:
                    rec.system_readiness_suggestion_id = ready_soon
                else:
                    rec.system_readiness_suggestion_id = ready_later


    # ==========================================================================
    # WORKFLOW ACTIONS
    # ==========================================================================

    # ==========================================================================
    # ASSESSMENT ENGINE
    # ==========================================================================

    _ASSESSED_STATES = ('assessed', 'approved', 'placed')

    def _compute_assessment_pass_mark(self):
        cfg = self.env['succession.assessment.config'].get_config()
        for rec in self:
            rec.assessment_pass_mark = cfg.pass_mark

    def _assessment_lines(self):
        self.ensure_one()
        return self.assessment_result_ids.filtered(lambda l: l.component_id.enabled)

    @api.depends('state', 'assessment_done', 'latest_pms_score', 'competency_eval_score',
                 'self_assessment_score', 'spmc_score',
                 'assessment_result_ids.score', 'assessment_result_ids.score_entered',
                 'assessment_result_ids.waived', 'assessment_result_ids.waiver_reason',
                 'assessment_result_ids.component_id', 'assessment_result_ids.contribution')
    def _compute_assessment_scores(self):
        cfg = self.env['succession.assessment.config'].get_config()
        has_components = bool(cfg.component_ids.filtered('enabled'))
        for rec in self:
            if not rec.assessment_criteria_synced:
                rec.assessment_status = 'pending'
                rec.final_assessment_score = 0.0
                rec.assessment_result = False
                rec.assessment_breakdown_display = _('Assessment Plan not synchronized with employee.')
                continue
            lines = rec._assessment_lines()
            all_waived = bool(lines and all(l.waived for l in lines))
            final = round(sum(lines.mapped('contribution')), 2)
            missing = lines.filtered(
                lambda l: l.component_id.mandatory and not l.waived and not l.is_scored)
            touched = lines.filtered(lambda l: l.waived or l.is_scored)
            if rec.assessment_done or rec.state in rec._ASSESSED_STATES:
                status = 'finalized'
            elif not lines:
                status = 'pending' if has_components else 'ready'
            elif not missing:
                status = 'ready'
            elif touched:
                status = 'partial'
            else:
                status = 'pending'
            rec.assessment_status = status
            rec.final_assessment_score = final if lines else 0.0
            if all_waived:
                rec.assessment_result = 'waived'
            elif status in ('ready', 'finalized') and lines.filtered('is_applicable'):
                rec.assessment_result = 'pass' if final >= cfg.pass_mark else 'fail'
            else:
                rec.assessment_result = False
            rec.assessment_breakdown_display = rec._format_breakdown_display()

    def _format_breakdown_display(self):
        self.ensure_one()
        lines = self._assessment_lines()
        if not lines:
            return _('No active assessment components.')
        if all(l.waived for l in lines):
            return _('All assessment components marked Not Applicable (N/A) with recorded justification.')
        parts = []
        for l in lines:
            cname = l.component_id.name
            if l.waived:
                reason = (' [%s]' % l.waiver_reason) if l.waiver_reason else ''
                parts.append('%s: N/A%s' % (cname, reason))
            elif l.is_scored or l.component_id.source == 'pms':
                if l.component_id.source == 'pms' and 0.0 < (self.latest_pms_score or 0.0) <= 5.0 and l.max_score > 5.0:
                    parts.append('%s (%.1f%% wt): %.2f/5.0 (%.0f%%) (%.2f pts)' % (
                        cname, l.effective_weight, self.latest_pms_score, l.normalized_score, l.contribution))
                else:
                    parts.append('%s (%.1f%% wt): %.1f/%.0f (%.2f pts)' % (
                        cname, l.effective_weight, l.effective_score, l.max_score, l.contribution))
            else:
                if l.component_id.source == 'competency_eval' and l.effective_score > 0:
                    parts.append('%s (%.1f%% wt): In Progress (%.1f pts)' % (
                        cname, l.effective_weight, l.contribution))
                else:
                    parts.append('%s (%.1f%% wt): Pending' % (cname, l.effective_weight))
        cfg = self.env['succession.assessment.config'].get_config()
        label = "Average Score" if cfg.scoring_method == 'average' else "Total Score"
        if self.assessment_status in ('ready', 'finalized'):
            return ' | '.join(parts) + (' | %s: %.2f%% (Pass Mark: %.2f%%)' % (label, self.final_assessment_score, cfg.pass_mark))
        else:
            return ' | '.join(parts) + (' | Current Progress: %.2f%% (Pass Mark: %.2f%% - Assessment In Progress)' % (self.final_assessment_score, cfg.pass_mark))

    def _refresh_assessment_scores(self):
        cands = self.sudo().with_context(force_write=True)
        for fname in ('competency_eval_score', 'self_assessment_score', 'spmc_score',
                      'succession_competency_score', 'competency_breakdown_display',
                      'final_assessment_score', 'assessment_result', 'assessment_status',
                      'assessment_breakdown_display'):
            field = cands._fields.get(fname)
            if field and field.store and field.compute:
                cands.env.add_to_compute(field, cands)
        cands.assessment_result_ids._compute_line()
        cands.assessment_result_ids._compute_source_type_display()
        cands.mapped('final_assessment_score')

    def _ensure_assessment_results(self):
        """Create or update a result line for every enabled component using ORM upsert."""
        cfg = self.env['succession.assessment.config'].get_config()
        components = cfg.component_ids.filtered(lambda c: c.enabled and c.active)

        ResultModel = self.env['succession.candidate.assessment.result'].sudo()

        for rec in self:
            if rec.assessment_done and rec.state in ('assessed', 'approved', 'placed'):
                continue
            if not rec.id:
                continue
            if not rec.assessment_criteria_synced:
                continue

            pos = rec.critical_position_id
            if pos and not pos.assessment_line_ids:
                pos._ensure_assessment_lines()

            pos_lines = pos.assessment_line_ids if pos else self.env['succession.critical.position.assessment.line'].browse()

            for comp in components:
                comp_id = comp.id
                pl = pos_lines.filtered(lambda l, cid=comp_id: l.component_id.id == cid)
                if pl:
                    weight = pl[0].weight if pl[0].enabled else 0.0
                    max_score = pl[0].max_score or 100.0
                    is_disabled = not pl[0].enabled
                else:
                    weight = comp.weight or 0.0
                    max_score = comp.max_score or 100.0
                    is_disabled = False

                # In-memory lookup and selective write to avoid redundant queries and compute triggers
                existing = rec.assessment_result_ids.filtered(lambda r, cid=comp_id: r.component_id.id == cid)[:1]
                if existing:
                    update_vals = {}
                    if existing.max_score != max_score:
                        update_vals['max_score'] = max_score
                    if not existing.score_entered and existing.weight != weight:
                        update_vals['weight'] = weight
                    if update_vals:
                        existing.with_context(force_write=True).write(update_vals)
                else:
                    ResultModel.create({
                        'candidate_id': rec.id,
                        'component_id': comp_id,
                        'weight': weight,
                        'max_score': max_score,
                        'waived': is_disabled,
                        'score': 0.0,
                        'score_entered': False,
                    })

            rec.invalidate_recordset(['assessment_result_ids'])

    def _check_assessment_ready(self):
        self.ensure_one()
        if self.state != 'nominated':
            raise UserError(_('Only candidates in "Nominated" status can be marked as Assessed.'))

        if not self.assessment_criteria_synced:
            raise UserError(_(
                'Assessment criteria must be synced first before marking as Assessed. '
                'Please click "Sync Assessment Criteria" in the header toolbar.'
            ))

        # Check Testing & Appraisal Components
        missing = self._assessment_lines().filtered(
            lambda l: l.component_id.mandatory and not l.waived and not l.is_scored)
        if missing:
            raise UserError(_(
                'Cannot mark as Assessed! Please record the assessment scores '
                '(click "Record Assessment Scores" above) before completing the assessment.\n\n'
                'Pending Assessment Components: %s'
            ) % ', '.join(missing.mapped('component_id.name')))

        # Check Multi-Rater Competency Evaluation
        comp_res = self.assessment_result_ids.filtered(
            lambda l: l.component_id.source == 'competency_eval')
        if not (comp_res and comp_res[0].waived):
            if not self.eval_line_ids:
                raise UserError(_(
                    'Cannot mark as Assessed! No competencies are loaded for this candidate. '
                    'Please click "Load Role Competencies" in the Competency Evaluation Matrix.'
                ))

            pending_raters = []
            if self.plan_include_manager:
                if not self.manager_evaluation_submitted:
                    mgr_missing = self.eval_line_ids.filtered(lambda l: not (l.manager_score or l.score))
                    if mgr_missing:
                        pending_raters.append(
                            _("• Direct Manager Evaluation: %d competencies pending (%s)") % (
                                len(mgr_missing), ', '.join(mgr_missing.mapped('competency_id.name'))
                            )
                        )
                    else:
                        pending_raters.append(_("• Direct Manager Evaluation: Pending submission"))
            if self.plan_include_spmc:
                if self.spmc_eval_ids:
                    unsubmitted = self.spmc_eval_ids.filtered(lambda e: not e.submitted)
                    if unsubmitted:
                        names = ', '.join(unsubmitted.mapped('user_id.name'))
                        pending_raters.append(
                            _("• SPMC Committee Evaluation: Pending separate submission from %d assessor(s) (%s)") % (
                                len(unsubmitted), names
                            )
                        )
                elif not self.spmc_evaluation_submitted:
                    spmc_missing = self.eval_line_ids.filtered(lambda l: not l.spmc_score)
                    if spmc_missing:
                        pending_raters.append(
                            _("• SPMC Committee Evaluation: %d competencies pending (%s)") % (
                                len(spmc_missing), ', '.join(spmc_missing.mapped('competency_id.name'))
                            )
                        )
                    else:
                        pending_raters.append(_("• SPMC Committee Evaluation: Pending submission"))

            if pending_raters:
                raise UserError(_(
                    "Cannot mark as Assessed! According to the active Assessment Plan, all configured evaluators must complete their ratings before the assessment can be finalized.\n\n"
                    "Pending Evaluations:\n%s"
                ) % '\n'.join(pending_raters))

        if not self.readiness_level_id:
            raise UserError(_('Please assign an Official Readiness Level before marking this candidate as Assessed.'))

    def _assessment_breakdown_text(self):
        self.ensure_one()
        out = []
        for l in self._assessment_lines():
            if l.waived:
                out.append('%s: N/A (%s)' % (l.component_id.name, l.waiver_reason or '-'))
            elif l.is_applicable:
                out.append('%s: %.2f/%.0f x %.2f%% = %.2f pts' % (
                    l.component_id.name, l.effective_score, l.max_score,
                    l.effective_weight, l.contribution))
            else:
                out.append('%s: not applicable' % l.component_id.name)
        return '; '.join(out)

    def _log_candidate_event(self, action, comment):
        """Immutable governance log entry linked to this candidate."""
        self.ensure_one()
        valid_actions = dict(self.env['succession.governance.log']._fields['action'].selection or [])
        log_action = action if action in valid_actions else 'note'
        self.env['succession.governance.log'].sudo().create({
            'critical_position_id': self.critical_position_id.id,
            'candidate_id': self.id,
            'action': log_action,
            'comment': comment,
            'user_id': self.env.user.id,
        })

    @api.depends('assessment_done', 'state')
    def _compute_assessment_plan_locked(self):
        for rec in self:
            rec.assessment_plan_locked = bool(rec.assessment_done or rec.state in ('assessed', 'approved', 'placed', 'rejected'))

    def _get_plan_booleans_from_scope(self, scope):
        """Return dict of multi-rater competency boolean values for a given scope (Decoupled from exams)."""
        scope = scope or 'manager_only'
        if scope == 'manager_only':
            return {
                'plan_include_manager': True,
                'plan_include_self': False,
                'plan_include_spmc': False,
            }
        elif scope == 'manager_self':
            return {
                'plan_include_manager': True,
                'plan_include_self': True,
                'plan_include_spmc': False,
            }
        elif scope == 'manager_spmc':
            return {
                'plan_include_manager': True,
                'plan_include_self': False,
                'plan_include_spmc': True,
            }
        elif scope == 'full_360':
            return {
                'plan_include_manager': True,
                'plan_include_self': True,
                'plan_include_spmc': True,
            }
        return {}

    def _sync_plan_booleans_from_scope(self):
        """Synchronize multi-rater competency checkboxes based on the chosen assessment scope."""
        for rec in self:
            vals = rec._get_plan_booleans_from_scope(rec.assessment_scope)
            if not vals:
                continue
            if not isinstance(rec.id, int):
                for k, v in vals.items():
                    rec[k] = v
            else:
                diffs = {k: v for k, v in vals.items() if rec[k] != v}
                if diffs:
                    rec.with_context(skip_apply_scope=True).write(diffs)

    def _apply_assessment_scope(self):
        """Configure which components are active or waived and sync plan weights to result lines."""
        for rec in self:
            if rec.assessment_done or not rec.assessment_result_ids:
                continue

            # Update governance metadata if not already defined or locked
            if not rec.assessment_plan_locked and not rec.assessment_plan_defined_by_id:
                if not isinstance(rec.id, int):
                    rec.assessment_plan_defined_by_id = self.env.user
                    rec.assessment_plan_defined_date = fields.Datetime.now()
                else:
                    rec.with_context(skip_apply_scope=True).write({
                        'assessment_plan_defined_by_id': self.env.user.id,
                        'assessment_plan_defined_date': fields.Datetime.now(),
                    })

            # Derive assessment scope name from active multi-rater toggles
            if rec.plan_include_manager and not rec.plan_include_self and not rec.plan_include_spmc:
                computed_scope = 'manager_only'
            elif rec.plan_include_manager and rec.plan_include_self and not rec.plan_include_spmc:
                computed_scope = 'manager_self'
            elif rec.plan_include_manager and not rec.plan_include_self and rec.plan_include_spmc:
                computed_scope = 'manager_spmc'
            elif rec.plan_include_manager and rec.plan_include_self and rec.plan_include_spmc:
                computed_scope = 'full_360'
            else:
                computed_scope = 'custom'
            if rec.assessment_scope != computed_scope:
                if not isinstance(rec.id, int):
                    rec.assessment_scope = computed_scope
                else:
                    rec.with_context(skip_apply_scope=True).write({'assessment_scope': computed_scope})

            rec._refresh_assessment_scores()

    @api.onchange('assessment_scope')
    def _onchange_assessment_scope(self):
        if self.assessment_scope:
            self._sync_plan_booleans_from_scope()
            self._apply_assessment_scope()

    @api.onchange('plan_include_manager', 'plan_include_spmc')
    def _onchange_competency_plan_checkboxes(self):
        if self.plan_include_manager and not self.plan_include_spmc:
            self.assessment_scope = 'manager_only'
        elif self.plan_include_manager and self.plan_include_spmc:
            self.assessment_scope = 'manager_spmc'
        else:
            self.assessment_scope = 'custom'
        self._apply_assessment_scope()

    @api.onchange('plan_include_pms', 'plan_include_exam', 'weight_pms', 'weight_exam')
    def _onchange_exam_checkboxes(self):
        if not self.plan_include_pms:
            self.weight_pms = 0.0
        elif not self.weight_pms:
            self.weight_pms = 20.0

        if not self.plan_include_exam:
            self.weight_exam = 0.0
        elif not self.weight_exam:
            self.weight_exam = 20.0

        self._apply_assessment_scope()

    @api.constrains('plan_include_pms', 'pms_exemption_reason', 'weight_pms',
                    'plan_include_manager', 'plan_include_self', 'plan_include_spmc',
                    'plan_include_exam', 'exam_exemption_reason', 'weight_exam',
                    'spmc_assessor_ids')
    def _check_candidate_assessment_plan(self):
        for rec in self:
            # Only validate if the assessment plan has been explicitly defined via wizard and not skipping
            if not rec.assessment_plan_defined_date or self.env.context.get('skip_plan_validation'):
                continue
            if not (rec.plan_include_manager or rec.plan_include_spmc):
                raise ValidationError(_(
                    "At least one evaluator (Manager or SPMC Committee) must be enabled for Succession Competency Assessment."
                ))
            if rec.plan_include_spmc and not rec.spmc_assessor_ids:
                raise ValidationError(_(
                    "Designated SPMC Committee Assessors Required!\n\n"
                    "SPMC Committee Evaluation is enabled for candidate '%(cand)s', but no Designated SPMC Committee Assessors have been assigned.\n\n"
                    "Please assign at least one SPMC Committee Member under 'Assigned SPMC Assessors'.",
                    cand=rec.display_name,
                ))

            total_weight = rec.plan_total_weight
            if abs(total_weight - 100.0) > 0.01:
                # Provide informational notice rather than hard crash on draft
                pass

    def _sync_evaluator_scope_from_position(self):
        """Synchronize multi-rater evaluator flags and assigned SPMC assessors from the critical position."""
        for rec in self:
            pos = rec.critical_position_id
            if not pos or pos.plan_status not in ('active', 'draft', 'reopened'):
                continue
            if not (pos.plan_include_manager or pos.plan_include_self or pos.plan_include_spmc):
                continue
            inc_mgr = bool(pos.plan_include_manager)
            inc_spmc = bool(pos.plan_include_spmc)
            inc_self = bool(pos.plan_include_self and rec._default_plan_include_self())
            if inc_mgr and inc_spmc and inc_self:
                scope = 'full_360'
            elif inc_mgr and inc_spmc:
                scope = 'manager_spmc'
            elif inc_mgr and inc_self:
                scope = 'manager_self'
            elif inc_mgr:
                scope = 'manager_only'
            else:
                scope = 'custom'
            vals = {
                'assessment_scope': scope,
                'plan_include_manager': inc_mgr,
                'plan_include_self': inc_self,
                'plan_include_spmc': inc_spmc,
                'spmc_assessor_ids': [(6, 0, pos.spmc_assessor_ids.ids)],
                'spmc_assigned_user_id': pos.spmc_assessor_ids[0].id if pos.spmc_assessor_ids else False,
            }
            if isinstance(rec.id, int):
                rec.with_context(force_write=True, skip_apply_scope=True).write(vals)
                if inc_spmc:
                    rec._sync_spmc_eval_records()
            else:
                for k, v in vals.items():
                    rec[k] = v

    @api.onchange('critical_position_id')
    def _onchange_critical_position_id_plan(self):
        self._sync_evaluator_scope_from_position()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('plan_include_exam', True)
            vals.setdefault('weight_exam', 20.0)
            vals.setdefault('plan_include_pms', True)
            vals.setdefault('weight_pms', 20.0)
            vals.setdefault('plan_include_manager', True)
            vals.setdefault('plan_include_spmc', True)
        recs = super().create(vals_list)

        # Auto-populate assessment scope from critical position on creation
        for rec in recs:
            try:
                rec._sync_evaluator_scope_from_position()
            except Exception:
                pass
        return recs

    def write(self, vals):
        user = self.env.user
        is_admin_or_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd') or \
                           user.has_group('bunna_succession_management.group_succession_admin') or \
                           self.env.is_superuser()
        if not is_admin_or_ppdd and not self.env.context.get('force_write'):
            restricted_fields = {
                'critical_position_id', 'employee_id', 'readiness_level_id', 'state',
                'plan_include_exam', 'plan_include_pms', 'plan_include_manager',
                'plan_include_self', 'plan_include_spmc', 'assessment_scope',
                'weight_pms', 'weight_exam', 'weight_competency', 'spmc_assigned_user_id', 'spmc_assessor_ids',
            }
            attempted = restricted_fields.intersection(vals.keys())
            if attempted:
                raise AccessError(_("You do not have permission to modify restricted candidate fields: %s") % ', '.join(attempted))

        if 'readiness_level_id' in vals and not self.env.context.get('force_write'):
            vals['manager_override'] = True
        res = super().write(vals)
        if 'spmc_assessor_ids' in vals or 'plan_include_spmc' in vals:
            self._sync_spmc_eval_records()
        if self.env.context.get('skip_apply_scope'):
            return res

        scope_fields = {'assessment_scope', 'plan_include_exam',
                        'plan_include_pms', 'plan_include_self', 'plan_include_spmc',
                        'plan_include_manager'}
        if any(f in vals for f in scope_fields):
            self.with_context(skip_apply_scope=True)._apply_assessment_scope()
        return res

    def action_load_assessment_components(self):
        """Load or refresh assessment component rows for nominated candidates.

        Uses upsert logic: updates weights on existing rows and only creates
        rows for components that are not yet present. This means:
          - Existing scores are NEVER wiped
          - The unique (candidate_id, component_id) constraint is never violated
          - Safe to call multiple times
        """
        ResultModel = self.env['succession.candidate.assessment.result'].sudo()
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_(
                    'Nomination must come first! Please click "Nominate Candidate" '
                    'to officially nominate this candidate before syncing assessment criteria.'
                ))

            pos = rec.critical_position_id
            _logger.warning('=== SYNC DEBUG: candidate=%s pos=%s plan_status=%s assessment_lines=%s components=%s',
                rec.id, pos.id if pos else None,
                pos.plan_status if pos else None,
                len(pos.assessment_line_ids) if pos else 0,
                len(self.env['succession.assessment.config'].get_config().component_ids.filtered(lambda c: c.enabled and c.active))
            )

            # Step 1: Sync evaluator scope & assigned SPMC assessors from critical position plan
            rec._sync_evaluator_scope_from_position()

            # Step 2: Ensure position has assessment lines (create from global config if missing)
            if pos and not pos.assessment_line_ids:
                pos._ensure_assessment_lines()

            # Step 3: Get global config components
            cfg = self.env['succession.assessment.config'].get_config()
            components = cfg.component_ids.filtered(lambda c: c.enabled and c.active)
            pos_lines = pos.assessment_line_ids if pos else self.env['succession.critical.position.assessment.line'].browse()

            # Step 4: Delete existing results via ORM (preserves audit, triggers computes)
            if rec.id and not rec.assessment_done:
                existing_results = ResultModel.search([('candidate_id', '=', rec.id)])
                if existing_results:
                    existing_results.sudo().unlink()
                rec.invalidate_recordset(['assessment_result_ids'])

            # Step 5: Insert fresh lines for all components
            for comp in components:
                comp_id = comp.id
                pl = pos_lines.filtered(lambda l, cid=comp_id: l.component_id.id == cid)
                if pl:
                    weight = pl[0].weight if pl[0].enabled else 0.0
                    max_score = pl[0].max_score or 100.0
                    is_disabled = not pl[0].enabled
                    waiver_reason = _('Excluded by Position Assessment Plan') if is_disabled else False
                else:
                    weight = comp.weight or 0.0
                    max_score = comp.max_score or 100.0
                    is_disabled = False
                    waiver_reason = False

                ResultModel.create({
                    'candidate_id': rec.id,
                    'component_id': comp_id,
                    'weight': weight,
                    'max_score': max_score,
                    'waived': is_disabled,
                    'waiver_reason': waiver_reason,
                    'score': 0.0,
                    'score_entered': False,
                })

            rec.invalidate_recordset(['assessment_result_ids'])

            # Step 5: Apply scope and refresh scores
            rec._apply_assessment_scope()
            rec._refresh_assessment_scores()

            # Step 6: Mark as synced
            rec.with_context(force_write=True).write({
                'assessment_criteria_synced': True,
                'assessment_criteria_synced_date': fields.Datetime.now(),
                'assessment_criteria_synced_by_id': self.env.user.id,
            })

            rec._log_candidate_event(
                'criteria_synced',
                'Assessment criteria synced from Critical Position plan (%s). '
                'Evaluator scope: Manager=%s, Self=%s, SPMC=%s. '
                'Record Assessment is now unlocked.' % (
                    pos.display_name if pos else 'N/A',
                    rec.plan_include_manager,
                    rec.plan_include_self,
                    rec.plan_include_spmc,
                )
            )
            rec.message_post(
                body=_('    Assessment criteria synced by %s.<br/>'
                       'Components: %d loaded.<br/>'
                       'Evaluator Scope: Manager=%s | Self=%s | SPMC=%s') % (
                    self.env.user.name,
                    len(components),
                    rec.plan_include_manager,
                    rec.plan_include_self,
                    rec.plan_include_spmc,
                )
            )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'succession.candidate',
            'res_id': self[0].id if self else False,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }


    def action_open_assessment_plan_wizard(self):
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_(
                'Candidate nomination must be completed first! Please click "Nominate Candidate" '
                'before configuring the assessment plan.'
            ))
        if self.assessment_plan_locked:
            raise UserError(_("The Assessment Plan is locked and cannot be modified."))
        self._ensure_assessment_results()
        self.invalidate_recordset(['assessment_result_ids'])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configure Assessment Plan & Evaluators: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.candidate.plan.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    def action_open_assessment_entry_wizard(self):
        self.ensure_one()
        if self.state == 'draft':
            raise UserError(_(
                'Nomination must come first! Please click "Nominate Candidate" '
                'before recording assessment scores.'
            ))
        if not self.assessment_criteria_synced:
            raise UserError(_(
                "Assessment Plan has not been synchronized with this employee. "
                "Please synchronize the Assessment Plan from the Critical Position before recording scores."
            ))
        if not self.assessment_result_ids:
            raise UserError(_(
                "No assessment components found for this candidate. "
                "Please synchronize the Assessment Plan from the Critical Position."
            ))
        self._ensure_assessment_results()
        self.invalidate_recordset(['assessment_result_ids'])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Assessment Results: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.candidate.assessment.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    @api.model
    def _repair_missing_spmc_plans(self):
        """Backfill SPMC evaluation flags on unsubmitted positions and open candidates created before defaults."""
        draft_positions = self.env['succession.critical.position'].sudo().search([
            ('plan_status', '=', 'draft'),
            ('plan_include_spmc', '=', False),
            ('assessment_scope', '=', 'manager_self'),
        ])
        if draft_positions:
            draft_positions.write({
                'plan_include_spmc': True,
                'plan_include_self': False,
                'assessment_scope': 'manager_spmc',
            })

        open_cands = self.sudo().search([
            ('state', 'in', ('draft', 'nominated')),
            ('assessment_done', '=', False),
            ('critical_position_id', '!=', False),
        ])
        for cand in open_cands:
            pos = cand.critical_position_id
            if not cand.spmc_evaluation_submitted and pos.plan_include_spmc and not cand.plan_include_spmc:
                cand._sync_evaluator_scope_from_position()
                cand._apply_assessment_scope()
            if cand.plan_include_spmc and cand.eval_line_ids and cand.spmc_assessor_ids:
                cand._sync_spmc_eval_records()

    def action_reopen_assessment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reopen Assessment'),
            'res_model': 'succession.assessment.reopen.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    def _reopen_assessment(self, reason):
        if not self.env.user.has_group('bunna_succession_management.group_succession_spmc'):
            raise AccessError(_('Only SPMC members can reopen an assessment.'))
        for rec in self:
            if rec.state != 'assessed':
                raise UserError(_(
                    'Only candidates in "Assessed" status (before SPMC approval) '
                    'can have their assessment reopened.'))
            rec.with_context(force_write=True).write({
                'state': 'nominated',
                'assessment_done': False,
                'assessment_date': False,
                'assessment_by_id': False,
                'assessment_criteria_synced': False,
                'assessment_criteria_synced_date': False,
                'assessment_criteria_synced_by_id': False,
                'spmc_evaluation_submitted': False,
                'spmc_evaluation_date': False,
                'manager_evaluation_submitted': False,
                'manager_evaluation_date': False,
            })
            if rec.spmc_eval_ids:
                rec.spmc_eval_ids.sudo().write({
                    'submitted': False,
                    'submitted_date': False,
                })
            rec._log_candidate_event('assessment_reopened', 'Assessment reopened. Reason: %s' % reason)
            rec.message_post(body=_('Assessment reopened by %s. Reason: %s') % (self.env.user.name, reason))

    def action_view_career_discussions(self):
        self.ensure_one()
        if self.state not in ('approved', 'placed'):
            status_label = dict(self._fields['state'].selection).get(self.state, self.state)
            raise UserError(_(
                "Cannot Conduct Career Discussion: SPMC Approval Required!\n\n"
                "Candidate '%s' is in status '%s'. Career Discussions can only be conducted after the SPMC Committee has approved the candidate's assessment."
            ) % (self.employee_id.name or self.display_name, status_label))
        action = self.env['ir.actions.act_window']._for_xml_id('bunna_succession_management.action_career_discussion')
        action['domain'] = [('candidate_id', '=', self.id)]
        action['context'] = {
            'default_candidate_id': self.id,
            'default_employee_id': self.employee_id.id,
        }
        return action

    def action_view_development_plans(self):
        self.ensure_one()
        if self.state not in ('approved', 'placed'):
            status_label = dict(self._fields['state'].selection).get(self.state, self.state)
            raise UserError(_(
                "Cannot View Development Plans: SPMC Approval Required!\n\n"
                "Candidate '%s' is in status '%s'. Development Plans can only be conducted after the SPMC Committee has approved the candidate's assessment."
            ) % (self.employee_id.name or self.display_name, status_label))
        action = self.env['ir.actions.act_window']._for_xml_id('bunna_succession_management.action_succession_dev_plan')
        action['domain'] = [('candidate_id', '=', self.id)]
        action['context'] = {
            'default_candidate_id': self.id,
        }
        return action

    def action_create_development_plan(self):
        self.ensure_one()
        if self.state not in ('approved', 'placed'):
            status_label = dict(self._fields['state'].selection).get(self.state, self.state)
            raise UserError(_(
                "Cannot Create Development Plan: SPMC Approval Required!\n\n"
                "Candidate '%s' is in status '%s'. A Development Plan can only be created and conducted after the SPMC Committee has approved the candidate's assessment."
            ) % (self.employee_id.name or self.display_name, status_label))

        existing = self.dev_plan_ids.filtered(lambda p: p.active and p.state not in ('cancelled', 'completed'))
        if existing:
            action = self.action_view_development_plans()
            action['views'] = [(self.env.ref('bunna_succession_management.view_succession_dev_plan_form').id, 'form')]
            action['res_id'] = existing[0].id
            return action
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Development Plan: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.development.plan',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_candidate_id': self.id,
            },
        }

    def action_nominate(self):
        """Move candidate from Draft to Nominated."""
        if not (self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or
                self.env.user.has_group('bunna_succession_management.group_succession_admin')):
            raise AccessError(_('Only PPDD Officers or Succession Administrators can nominate candidates.'))

        for rec in self:
            if rec.critical_position_id.state != 'approved':
                raise UserError(_(
                    'Cannot nominate candidate! Critical Position "%s" is not approved yet (Status: %s). '
                    'Only approved critical positions can have succession candidates nominated.'
                ) % (rec.critical_position_id.display_name, rec.critical_position_id.state))

            rec.with_context(force_write=True).write({
                'state': 'nominated',
                'nomination_date': fields.Date.today(),
                'nominated_by_id': self.env.user.id,
                'plan_include_self': False,  # Self-assessment disabled
                'assessment_criteria_synced': False,  # Scorecard and matrix remain empty until synced
            })

            # Score Card and Competency Evaluation Matrix remain empty
            # until the Assessment Plan is officially synchronized with the employee.

            # Also auto-run gap analysis if possible
            if rec.critical_position_id.sudo().required_role_mapping_line_ids and not rec.competency_gap_ids:
                try:
                    rec.action_compute_gap_analysis()
                except Exception:
                    pass

            rec.critical_position_id._log_governance(
                'candidate_nominated',
                'Candidate %s nominated for %s' % (
                    rec.employee_id.name, rec.critical_position_id.job_id.name)
            )

            # Send self-assessment notification if candidate self-assessment is enabled
            if rec.plan_include_self:
                try:
                    rec.send_self_assessment_notification()
                except Exception:
                    pass

        names = ", ".join(self.mapped('employee_id.name'))
        count = len(self)
        if count == 1:
            title = _('Candidate Successfully Nominated')
            msg = _('Candidate %s was successfully nominated to the Succession Pipeline! Assessment scorecards and evaluation plan initialized.') % names
        else:
            title = _('Candidates Successfully Nominated')
            msg = _('Successfully nominated %d candidates (%s) to the Succession Pipeline! Assessment scorecards and evaluation plans initialized.') % (count, names)

        return self._notify_and_reload(title, msg)

    def _validate_assessment_complete(self):
        """Validate that all assessment components and multi-rater evaluations are filled before submitting for approval."""
        self.ensure_one()
        cand = self.sudo()
        # 1. SPMC committee evaluations
        if cand.plan_include_spmc:
            if cand.spmc_eval_ids:
                unsubmitted = cand.spmc_eval_ids.filtered(lambda e: not e.submitted)
                if unsubmitted:
                    names = ', '.join(unsubmitted.mapped('user_id.name'))
                    raise UserError(_(
                        "Cannot submit assessment for approval! All %d assigned SPMC committee assessors must submit their evaluations separately before readiness can be calibrated.\n\n"
                        "Pending submissions from: %s"
                    ) % (len(cand.spmc_eval_ids), names))
            elif not cand.spmc_evaluation_submitted:
                raise UserError(_(
                    "Cannot submit assessment for approval! SPMC committee evaluation must be submitted before readiness can be calibrated."
                ))

        # 2. Manager evaluation
        if cand.plan_include_manager and not cand.manager_evaluation_submitted:
            raise UserError(_(
                "Cannot submit assessment for approval! Manager competency evaluation must be submitted before readiness can be calibrated."
            ))

        # 3. Scorecard initialization
        cand._ensure_assessment_results()
        if not cand.assessment_criteria_synced or not cand.assessment_result_ids:
            raise UserError(_(
                "Cannot submit assessment for approval! Assessment scorecard has not been initialized. Please configure the assessment plan and sync criteria first."
            ))

        # 4. Check all applicable scorecard components are filled / scored
        pending_lines = cand.assessment_result_ids.filtered(lambda l: l.is_applicable and not l.is_scored)
        if pending_lines:
            pending_names = '\n'.join([f"• {l.component_id.name} (Weight: {l.effective_weight:.1f}%, Status: {l.status_label})" for l in pending_lines])
            raise UserError(_(
                "Cannot submit assessment for approval! All applicable assessment scorecard components must be completed and filled.\n\n"
                "The following scorecard components are still pending:\n%s\n\n"
                "Please enter the scores or mark non-applicable components before submitting."
            ) % pending_names)

    def action_open_set_readiness_wizard(self):
        """Opens the PPDD Talent Calibration Wizard to assign readiness level and finalize assessment."""
        self.ensure_one()
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        emp = self.sudo().employee_id
        is_coach_or_mgr = bool(emp and (
            (emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
            (emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
            (self.sudo().parent_id and self.sudo().parent_id.user_id and self.sudo().parent_id.user_id.id == user.id) or
            (self.sudo().coach_id and self.sudo().coach_id.user_id and self.sudo().coach_id.user_id.id == user.id)
        ))
        is_mgr_group = user.has_group('bunna_succession_management.group_succession_line_manager')

        if not is_admin:
            if is_spmc:
                raise AccessError(_("Security Restriction: SPMC committee members cannot complete assessment or set readiness. This action is reserved for PPDD Officers."))
            if is_coach_or_mgr or is_mgr_group:
                raise AccessError(_("Security Restriction: Line Managers cannot complete assessment or set readiness. This action is reserved for PPDD Officers."))
            if not user.has_group('bunna_succession_management.group_succession_ppdd'):
                raise AccessError(_("Security Restriction: Only PPDD Officers or Succession Administrators can complete assessment and set readiness."))

        # Validate that all evaluations and scorecard lines are completed
        self._validate_assessment_complete()

        self._ensure_assessment_results()
        self._refresh_assessment_scores()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Complete Assessment & Set Readiness: %s') % (self.employee_id.name or ''),
            'res_model': 'succession.candidate.set.readiness.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
                'default_readiness_level_id': self.readiness_level_id.id if self.readiness_level_id else (self.system_readiness_suggestion_id.id if self.system_readiness_suggestion_id else False),
            },
        }

    def action_assess(self):
        """
        PPDD marks candidate as Assessed.
        If readiness_level_id is not yet set, opens the PPDD Readiness Decision Wizard.
        """
        user = self.env.user
        is_admin = user.has_group('bunna_succession_management.group_succession_admin') or self.env.is_superuser()
        is_spmc = user.has_group('bunna_succession_management.group_succession_spmc')
        is_mgr_group = user.has_group('bunna_succession_management.group_succession_line_manager')

        if not is_admin:
            if is_spmc:
                raise AccessError(_("Security Restriction: SPMC committee members cannot mark candidates as Assessed. This action is reserved for PPDD Officers."))
            if is_mgr_group:
                raise AccessError(_("Security Restriction: Line Managers cannot mark candidates as Assessed. This action is reserved for PPDD Officers."))
            if not user.has_group('bunna_succession_management.group_succession_ppdd'):
                raise AccessError(_("Only PPDD Officers or Succession Administrators can mark candidates as Assessed."))

        for rec in self:
            rec._ensure_assessment_results()
            rec._validate_assessment_complete()
            rec._check_assessment_ready()

            if not rec.competency_gap_ids:
                try:
                    rec.action_compute_gap_analysis()
                except Exception:
                    pass

            rec._refresh_assessment_scores()

            # If PPDD has not set readiness level yet, open the Calibration Wizard
            if not rec.readiness_level_id:
                return rec.action_open_set_readiness_wizard()

            cfg = self.env['succession.assessment.config'].get_config()
            final = rec.final_assessment_score
            below_pass = rec.assessment_result == 'fail'
            breakdown = rec._assessment_breakdown_text()

            rec.with_context(force_write=True).write({
                'assessment_done': True,
                'assessment_date': fields.Datetime.now(),
                'assessment_by_id': self.env.user.id,
            })

            require_spmc = rec.env['succession.governance.policy'].get_policy().succ_require_spmc_approval
            can_auto_approve = (not require_spmc) and not (below_pass and cfg.enforce_pass_mark)
            summary = _(
                'Final assessment score: %.2f (pass mark %.2f) - %s\n%s\n'
                'Match: %.1f%% | Readiness: %s') % (
                    final, cfg.pass_mark,
                    dict(rec._fields['assessment_result'].selection).get(rec.assessment_result, _('n/a')),
                    breakdown, rec.competency_match_percent, rec.readiness_level_id.name)
            if can_auto_approve:
                rec.with_context(force_write=True).write({'state': 'approved'})
                rec.message_post(body=_(
                    'Candidate marked as Assessed and automatically Approved '
                    '(SPMC Approval is disabled in Settings).\n') + summary)
            else:
                rec.with_context(force_write=True).write({'state': 'assessed'})
                rec.message_post(body=_('Candidate assessed. Awaiting SPMC Approval.\n') + summary)
                # Schedule To-Do activity for SPMC committee members
                spmc_group = self.env.ref('bunna_succession_management.group_succession_spmc', raise_if_not_found=False)
                if spmc_group and spmc_group.users:
                    for spmc_usr in spmc_group.users:
                        try:
                            act_summary = f"SPMC Candidate Approval: {rec.employee_id.name}"
                            existing_act = self.env['mail.activity'].sudo().search([
                                ('res_model', '=', 'succession.candidate'),
                                ('res_id', '=', rec.id),
                                ('user_id', '=', spmc_usr.id),
                                ('summary', '=', act_summary),
                            ], limit=1)
                            if not existing_act:
                                rec.sudo().activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    user_id=spmc_usr.id,
                                    summary=act_summary,
                                    note=f"Candidate {rec.employee_id.name} has been assessed for {rec.critical_position_id.display_name} (Score: {final:.1f}%). Please review and grant SPMC approval.",
                                    date_deadline=fields.Date.today(),
                                )
                        except Exception:
                            pass

            rec._log_candidate_event(
                'candidate_assessed',
                'Candidate %s assessed for %s. Final score %.2f (pass mark %.2f). %s' % (
                    rec.employee_id.name, rec.critical_position_id.display_name,
                    final, cfg.pass_mark, breakdown))

        return self._notify_and_reload(
            _('Candidate Assessed'),
            _('Candidate %s has been assessed. %s') % (
                self.employee_id.name,
                _('Automatically Approved.') if can_auto_approve else _('Awaiting SPMC Approval.')
            ),
        )

    def action_spmc_approve(self):
        """SPMC final approval of the successor candidate."""
        from odoo.exceptions import ValidationError
        if not (self.env.user.has_group('bunna_succession_management.group_succession_spmc') or
                self.env.user.has_group('bunna_succession_management.group_succession_admin')):
            raise AccessError(_('Only SPMC members or Succession Administrators can grant final candidate approval.'))

        for rec in self:
            rec._validate_assessment_complete()
            cfg = self.env['succession.assessment.config'].get_config()
            if cfg.enforce_pass_mark and rec.assessment_result == 'fail':
                raise ValidationError(_(
                    'Approval Blocked! The final assessment score (%.2f) is below the '
                    'pass mark (%.2f).') % (rec.final_assessment_score, cfg.pass_mark))


            # Mandatory Development Plan constraint removed per bank policy
                    
            rec.sudo().with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })

            # Mark pending SPMC approval activities done
            try:
                rec.sudo().with_context(mail_notify_force_send=False, mail_post_autofollow=False).activity_feedback(['mail.mail_activity_data_todo'])
            except Exception:
                pass

            rec.critical_position_id.sudo()._log_governance('candidate_approved', 'SPMC approved candidate %s' % rec.employee_id.name)
            rec.sudo().with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_(
                "<b>🎉 Candidate Officially Approved by SPMC</b><br/>"
                "Candidate <b>%s</b> has been approved as a qualified successor for <b>%s</b>.<br/>"
                "<ul>"
                "<li><b>Approved By:</b> %s</li>"
                "<li><b>Readiness Level:</b> %s</li>"
                "<li><b>Competency Match:</b> %.1f%%</li>"
                "<li><b>Final Score:</b> %.2f</li>"
                "</ul>"
            ) % (
                rec.employee_id.name,
                rec.critical_position_id.display_name,
                self.env.user.name,
                rec.readiness_level_id.name if rec.readiness_level_id else 'N/A',
                rec.competency_match_percent,
                rec.final_assessment_score
            ))
            if rec.is_high_potential and rec.employee_id:
                if hasattr(rec.employee_id, 'is_high_potential'):
                    rec.employee_id.sudo().write({'is_high_potential': True})

            # Prompt activity for line manager to conduct post-approval Career Discussion & Development Plan
            mgr_user = (rec.employee_id.parent_id and rec.employee_id.parent_id.user_id) or (rec.employee_id.coach_id and rec.employee_id.coach_id.user_id) or (rec.parent_id and rec.parent_id.user_id)
            if mgr_user:
                try:
                    act_summary = f"Conduct Career Discussion & Development Plan: {rec.employee_id.name}"
                    existing_act = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'succession.candidate'),
                        ('res_id', '=', rec.id),
                        ('user_id', '=', mgr_user.id),
                        ('summary', '=', act_summary),
                    ], limit=1)
                    if not existing_act:
                        rec.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=mgr_user.id,
                            summary=act_summary,
                            note=f"Candidate {rec.employee_id.name} has been officially approved by SPMC for {rec.critical_position_id.display_name}. Please conduct the post-approval Career Discussion and initiate their Succession Development Plan.",
                            date_deadline=fields.Date.today(),
                        )
                except Exception:
                    pass

        return self._notify_and_reload(
            _('Candidate Approved'),
            _('Candidate %s has been officially approved by SPMC as a qualified successor.') % self.employee_id.name,
        )


    def action_reject(self):
        for rec in self:
            rec.sudo().with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({'state': 'rejected'})
            rec.critical_position_id.sudo()._log_governance(
                'candidate_rejected',
                'Candidate %s rejected for %s' % (
                    rec.employee_id.name, rec.critical_position_id.display_name))
        return self._notify_and_reload(
            _('Candidate Rejected'),
            _('Candidate %s has been marked as Rejected.') % self.employee_id.name,
            notif_type='warning',
        )

    def action_waitlist(self):
        for rec in self:
            rec.sudo().with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({'state': 'waitlisted'})
            rec.sudo().with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_('Candidate %s moved to Waitlist.') % rec.employee_id.name)
        return self._notify_and_reload(
            _('Candidate Waitlisted'),
            _('Candidate %s has been moved to the Waitlist.') % self.employee_id.name,
            notif_type='info',
        )

    def action_reactivate(self):
        for rec in self:
            if rec.state != 'waitlisted':
                continue
            rec.sudo().with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({'state': 'nominated'})
            rec.critical_position_id.sudo()._log_governance(
                'candidate_nominated',
                'Candidate %s reactivated from Waitlist into active pipeline for %s' % (
                    rec.employee_id.name, rec.critical_position_id.display_name))
            rec.sudo().with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_('Candidate %s reactivated from Waitlist back into the active succession pipeline.') % rec.employee_id.name)
        return self._notify_and_reload(
            _('Candidate Reactivated'),
            _('Candidate %s reactivated from Waitlist back into active pipeline.') % self.employee_id.name,
        )

    _RESIGNED_EMPLOYEE_STATUSES = (
        'approved',
        'release_date_set',
        'handover_completed',
        'clearance_in_progress',
        'cleared',
        'settled',
        'completed',
    )
    _RESIGNATION_ELIGIBLE_CANDIDATE_STATES = (
        'draft',
        'nominated',
        'assessed',
        'approved',
        'waitlisted',
    )
    _POOL_DEPLOYABLE_STATES = (
        'approved',
    )

    @staticmethod
    def _is_ready_now_level(level):
        if not level:
            return False
        return bool(
            level.is_ready_for_deployment
            or 'now' in (level.name or '').lower()
            or (level.sequence and level.sequence <= 10)
        )

    @classmethod
    def _is_employee_resigned(cls, employee):
        if not employee:
            return False
        emp_sudo = employee.sudo()
        if not emp_sudo.active:
            return True
        if getattr(emp_sudo, 'resignation_status', False) in cls._RESIGNED_EMPLOYEE_STATUSES:
            return True
        if getattr(emp_sudo, 'departure_date', False) or getattr(emp_sudo, 'departure_reason_id', False):
            return True
        return False

    @api.depends(
        'state',
        'readiness_level_id',
        'readiness_level_id.is_ready_for_deployment',
        'readiness_level_id.name',
        'readiness_level_id.sequence',
    )
    @api.depends_context('uid')
    def _compute_can_deploy_from_pool(self):
        can_deploy_role = (
            self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        )
        for rec in self:
            rec.can_deploy_from_pool = bool(
                can_deploy_role
                and rec.state in self._POOL_DEPLOYABLE_STATES
                and rec._is_ready_now_level(rec.readiness_level_id)
            )

    def action_deploy_candidate(self):
        """Deploy a Ready Now candidate from the Talent Pool (HR Manager or Succession Administrator)."""
        if not (
            self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        ):
            raise AccessError(_('Only HR Manager role users or Succession Administrators can deploy candidates from the Talent Pool.'))
        now = fields.Datetime.now()
        for rec in self:
            rec_sudo = rec.sudo()
            if rec_sudo.state == 'resigned' or self._is_employee_resigned(rec_sudo.employee_id):
                raise UserError(_("Cannot deploy '%s' because the employee has resigned from the bank.") % (rec_sudo.employee_id.name or rec_sudo.display_name))
            if rec_sudo.state == 'placed':
                raise UserError(_("Candidate '%s' is already Deployed.") % (rec_sudo.employee_id.name or rec_sudo.display_name))
            if rec_sudo.state not in self._POOL_DEPLOYABLE_STATES:
                state_label = dict(rec_sudo._fields['state'].selection).get(rec_sudo.state, rec_sudo.state)
                raise UserError(_(
                    "Cannot Deploy Candidate: SPMC Approval Required!\n\n"
                    "Candidate '%(emp)s' is currently in status '%(status)s'.\n\n"
                    "Candidates can only be deployed after the SPMC Committee has officially reviewed and approved their assessment.",
                    emp=rec_sudo.employee_id.name or rec_sudo.display_name,
                    status=state_label,
                ))
            if not rec._is_ready_now_level(rec_sudo.readiness_level_id):
                readiness_name = rec_sudo.readiness_level_id.name if rec_sudo.readiness_level_id else 'None'
                raise UserError(_(
                    "Cannot Deploy Candidate: 'Ready Now' Status Required!\n\n"
                    "Candidate '%(emp)s' has readiness level '%(readiness)s'.\n\n"
                    "Only candidates evaluated and categorized as 'Ready Now' can be deployed into critical positions.",
                    emp=rec_sudo.employee_id.name or rec_sudo.display_name,
                    readiness=readiness_name,
                ))

            rec_sudo.with_context(mail_notify_force_send=False, mail_post_autofollow=False).write({
                'state': 'placed',
                'deployed_by_id': self.env.user.id,
                'deployment_date': now,
            })
            rec_sudo.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(
                body=_(
                    "<b>Candidate Deployed from Talent Pool</b><br/>"
                    "Deployed by <b>%s</b> on %s. Status updated to <b>Deployed</b>."
                ) % (self.env.user.name, fields.Datetime.to_string(now))
            )
            pos = rec_sudo.critical_position_id
            if pos:
                pos._compute_succession_stats()
                pos._log_governance(
                    'placed',
                    _("Successor Deployed from Pool: %s (Remaining Pool: %s, Successors Needed: %s)")
                    % (rec_sudo.employee_id.name or 'Candidate', pos.bench_strength, pos.bench_deficit),
                )
                pos.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(
                    body=_(
                        "<b>Successor Deployed from Pool</b><br/>"
                        "Candidate <b>%s</b> was deployed by <b>%s</b>.<br/>"
                        "Active Pool Coverage: <b>%s</b> | Successors Needed: <b>%s</b>."
                    ) % (rec_sudo.employee_id.name or 'Candidate', self.env.user.name, pos.bench_strength, pos.bench_deficit)
                )

        if len(self) == 1:
            rec_sudo = self.sudo()
            pos = rec_sudo.critical_position_id
            deficit_msg = _(" Successors needed for %s: %s.") % (pos.display_name, pos.bench_deficit) if pos else ""
            return self._notify_and_reload(
                _('Candidate Deployed'),
                _('%s status updated to Deployed.%s') % (rec_sudo.employee_id.name or 'Candidate', deficit_msg),
            )
        return self._notify_and_reload(
            _('Candidates Deployed'),
            _('%d candidate(s) status updated to Deployed.') % len(self),
        )

    @api.model
    def _mark_resigned_for_employees(self, employees):
        """Transition active succession candidates for resigned/departed employees to 'resigned'."""
        if not employees:
            return self.env['succession.candidate']
        resigned_emps = employees.sudo().filtered(lambda e: self._is_employee_resigned(e))
        if not resigned_emps:
            return self.env['succession.candidate']
        candidates = self.with_context(active_test=False).sudo().search([
            ('employee_id', 'in', resigned_emps.ids),
            ('state', 'in', self._RESIGNATION_ELIGIBLE_CANDIDATE_STATES),
        ])
        if not candidates:
            return candidates
        now = fields.Datetime.now()
        affected_positions = candidates.mapped('critical_position_id')
        candidates.with_context(mail_notify_force_send=False, mail_post_autofollow=False).write({
            'state': 'resigned',
            'resignation_detected_date': now,
        })
        for cand in candidates:
            cand.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(
                body=_(
                    "<b>Employee Resigned from the Bank</b><br/>"
                    "Employee <b>%s</b> has resigned or separated from the bank. "
                    "Candidate status updated to <b>Employee Resigned</b> and removed from active pool count."
                ) % (cand.employee_id.name or 'Employee')
            )
        if affected_positions:
            affected_positions.sudo()._compute_succession_stats()
            for pos in affected_positions.sudo():
                pos._log_governance(
                    'note',
                    _("Candidate Resigned: Active Pool Coverage %s, Successors Needed: %s")
                    % (pos.bench_strength, pos.bench_deficit),
                )
        return candidates

    @api.model
    def _repair_resigned_candidates(self):
        """Upgrade-safe sync: mark active candidates whose employees already resigned."""
        candidates = self.with_context(active_test=False).sudo().search([
            ('state', 'in', self._RESIGNATION_ELIGIBLE_CANDIDATE_STATES),
        ])
        if not candidates:
            return True
        self._mark_resigned_for_employees(candidates.mapped('employee_id'))
        return True

    @api.model
    def _repair_legacy_deployment_states(self):
        """Upgrade-safe cleanup: reset candidates in removed deployment_* states back to SPMC Approved."""
        legacy_states = ('deployment_lm', 'deployment_po', 'deployment_ppdd', 'deployment_spmc')
        candidates = self.with_context(active_test=False).sudo().search([
            ('state', 'in', legacy_states),
        ])
        if not candidates:
            return True
        positions = candidates.mapped('critical_position_id')
        candidates.with_context(mail_notify_force_send=False, mail_post_autofollow=False).write({
            'state': 'approved',
        })
        if positions:
            positions.sudo()._compute_succession_stats()
        return True

    def action_compute_gap_analysis(self):
        """
        Pull the employee's latest approved competency assessment and compare
        against the Critical Position's required competencies (FR-SEL-002).
        Auto-suggests readiness level based on match percentage and PMS score.
        """
        self.ensure_one()
        if not self.critical_position_id.sudo().required_role_mapping_line_ids:
            raise UserError(
                _('The critical position has no required competencies configured. '
                  'Please ask HR to update the critical position profile.'))

        # Clear existing gap lines
        self.competency_gap_ids.unlink()

        employee = self.employee_id
        gap_lines = []

        # Derive competency gaps directly from Succession Competency Evaluation (eval_line_ids)
        eval_lines_by_comp = {l.competency_id.id: l for l in self.eval_line_ids if l.competency_id}

        for mapping_line in self.critical_position_id.sudo().required_role_mapping_line_ids:
            competency = mapping_line.competency_id
            required_score = float(mapping_line.required_proficiency or '3.0')
            weight = mapping_line.weight or 1.0

            current_score = 0.0
            eval_line = eval_lines_by_comp.get(competency.id)
            if eval_line and (eval_line.score or eval_line.manager_score):
                current_score = float(eval_line.score or eval_line.manager_score)
            else:
                # Check external competency.assessment as secondary fallback
                asm = self.env['competency.assessment'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['approved', 'locked']),
                ], order='id desc', limit=1) if 'competency.assessment' in self.env else False
                if asm:
                    asm_line = asm.line_ids.filtered(lambda l: l.competency_id.id == competency.id)
                    if asm_line:
                        current_score = asm_line[0].weighted_current_level or float(asm_line[0].current_level or '1.0')

            gap_val = current_score - required_score
            if gap_val > 0.0:
                status = 'exceeds'
            elif gap_val == 0.0:
                status = 'meets'
            else:
                status = 'below'

            gap_lines.append({
                'candidate_id': self.id,
                'competency_id': competency.id,
                'weight': weight,
                'required_score': required_score,
                'current_score': current_score,
                'gap_score': gap_val,
                'achievement_status': status,
                '_req': required_score,
                '_cur': current_score,
            })

        # Calculate weighted match percentage based on Assessment Score and Required Weight
        total_req_weighted = 0.0
        total_cur_weighted = 0.0
        
        for g in gap_lines:
            w = g['weight']
            req = g.pop('_req')
            cur = g.pop('_cur')
            
            # Cap current score at required score so overachieving in one doesn't hide failing in another
            cur_capped = min(cur, req)
            
            total_req_weighted += (req * w)
            total_cur_weighted += (cur_capped * w)

        self.env['succession.candidate.competency.gap'].create(gap_lines)

        match_pct = round((total_cur_weighted / total_req_weighted) * 100, 1) if total_req_weighted > 0.0 else 0.0
        pms = self.latest_pms_score or 0.0

        # Gap analysis computed notification
        self.invalidate_recordset(['competency_match_percent'])
        
        self.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(
            body=_('Gap analysis computed. Match: %s%%. PMS: %.1f.') % (
                match_pct, pms))

        return self._notify_and_reload(
            _('Gap Analysis Complete'),
            _('Competency match: %s%%.') % match_pct,
            notif_type='info',
        )

    def unlink(self):
        is_admin = self.env.is_admin() or self.env.user.has_group('base.group_system') or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        for rec in self:
            rec_sudo = rec.sudo()
            if rec_sudo.state == 'draft':
                if not (rec_sudo.create_uid == self.env.user or is_admin):
                    raise UserError(_(
                        "Draft candidate record '%s' can only be deleted by its creator (%s) or a Succession Administrator."
                    ) % (rec_sudo.display_name, rec_sudo.create_uid.name or 'unknown'))
            else:
                state_label = dict(rec_sudo._fields['state'].selection).get(rec_sudo.state, rec_sudo.state)
                raise UserError(_(
                    "Candidate '%s' in state '%s' cannot be permanently deleted. "
                    "Please archive this candidate record (Action > Archive) to preserve succession history and audit compliance."
                ) % (rec_sudo.display_name, state_label))
        return super(SuccessionCandidate, self.sudo()).unlink()

    _employee_position_uniq = models.Constraint(
        'unique(employee_id, critical_position_id)',
        'This employee is already a candidate for this critical position!',
    )


class SuccessionCandidateCompetencyGap(models.Model):
    """
    Competency Gap Line for a Succession Candidate (FR-SEL-002).
    Side-by-side comparison of Current vs Required proficiency
    for each competency required by the Critical Position.
    """
    _name = 'succession.candidate.competency.gap'
    _description = 'Succession Candidate Competency Gap'
    _order = 'achievement_status desc, competency_id'

    candidate_id = fields.Many2one(
        'succession.candidate', string='Candidate',
        required=True, ondelete='cascade', index=True)
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        related='candidate_id.critical_position_id', store=True, readonly=True, index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='candidate_id.department_id', store=True, readonly=True, index=True)
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        required=True, ondelete='restrict', index=True)
    competency_pillar = fields.Selection(
        related='competency_id.pillar', string='Pillar', store=True, readonly=True, index=True)
    weight = fields.Float(string='Weight', default=1.0)
    required_score = fields.Float(string='Required Score', required=True)
    current_score = fields.Float(string='Assessment Score', required=True, default=0.0)
    gap_score = fields.Float(string='Variance (+/-)', readonly=True)
    
    variance_display = fields.Char(string='Variance', compute='_compute_variance_display')

    @api.depends('gap_score')
    def _compute_variance_display(self):
        for rec in self:
            if rec.gap_score == 0.0:
                rec.variance_display = 'Match'
            else:
                # User specifically requested all positive numbers for better UX
                rec.variance_display = f"{abs(rec.gap_score):.2f}"
                
    # DEPRECATED FIELDS: Kept temporarily to prevent browser cache crashes (RPC_ERROR)
    # The client might still request these until a hard refresh is performed.
    required_proficiency = fields.Char(string='(Deprecated) Req', compute='_compute_deprecated', store=False)
    current_proficiency = fields.Char(string='(Deprecated) Cur', compute='_compute_deprecated', store=False)
    gap = fields.Integer(string='(Deprecated) Gap', compute='_compute_deprecated', store=False)

    def _compute_deprecated(self):
        for rec in self:
            rec.required_proficiency = str(rec.required_score)
            rec.current_proficiency = str(rec.current_score)
            rec.gap = int(rec.gap_score)
    achievement_status = fields.Selection([
        ('exceeds', 'Exceeds'),
        ('meets', 'Meets'),
        ('below', 'Gap / Below Required'),
    ], string='Status', index=True)

