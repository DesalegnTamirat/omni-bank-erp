# -*- coding: utf-8 -*-
import re
import logging
from datetime import date, datetime, timedelta

from odoo import api, fields, models, _

from odoo.exceptions import ValidationError, UserError

from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)
class SuccessionReadinessLevel(models.Model):
    _name = 'succession.readiness.level'
    _description = 'Succession Readiness Level'
    _order = 'sequence, id'

    name = fields.Char(string='Readiness Level', required=True, translate=True, index='trigram')
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    description = fields.Text(string='HR Guidance / Criteria')
    is_ready_for_deployment = fields.Boolean(
        string='Ready for Deployment', default=False,
        index=True,
        help="If checked, candidates in this tier can be deployed immediately to fill an active vacancy."
    )
    time_horizon = fields.Char(
        string='Time Horizon', compute='_compute_time_horizon', store=True,
        help="Target timeframe to achieve full operational readiness."
    )
    min_months = fields.Integer(string='Minimum Months', default=0)
    max_months = fields.Integer(string='Maximum Months', default=12)
    # Legacy fields retained for backwards-compatibility; not required as HR/PPDD assigns readiness
    min_match_percent = fields.Float(string='Minimum Match %', default=0.0)
    min_pms_score = fields.Float(string='Minimum PMS Score', default=0.0)
    max_grade_gap = fields.Integer(string='Max Grade Gap', default=1)
    active = fields.Boolean(default=True, index=True)

    @api.depends('min_months', 'max_months')
    def _compute_time_horizon(self):
        for rec in self:
            if rec.min_months == 0 and rec.max_months <= 12:
                rec.time_horizon = '0 - %d Months' % (rec.max_months or 6)
            elif rec.min_months >= 12 and rec.max_months >= 12:
                min_yr = rec.min_months // 12
                max_yr = rec.max_months // 12
                rec.time_horizon = '%d - %d Years' % (min_yr, max_yr)
            elif rec.min_months > 0 or rec.max_months > 0:
                rec.time_horizon = '%d - %d Months' % (rec.min_months, rec.max_months)
            else:
                rec.time_horizon = 'Immediate'



class SuccessionRiskLevel(models.Model):

    _name = 'succession.risk.level'

    _description = 'Succession Risk Level Configuration'

    _order = 'sequence, id'



    name = fields.Char(string='Risk Level Name', required=True, translate=True, index='trigram')

    sequence = fields.Integer(string='Sequence', default=10, index=True)

    color = fields.Integer(string='Color Index', default=0, help='Color for UI badges')

    code = fields.Char(string='Internal Code', index=True, help='Used for system filters (e.g. critical, high)')

    active = fields.Boolean(default=True, index=True)





class SuccessionTimeframe(models.Model):

    _name = 'succession.timeframe'

    _description = 'Target Succession Timeframe Configuration'

    _order = 'sequence, id'

    name = fields.Char(string='Timeframe Name', required=True, translate=True, index='trigram')

    sequence = fields.Integer(string='Sequence', default=10, index=True)

    active = fields.Boolean(default=True, index=True)





class SuccessionCriticalityCategory(models.Model):

    _name = 'succession.criticality.category'

    _description = 'Succession Criticality Category'

    _order = 'sequence, id'



    name = fields.Char(string='Category Name', required=True, translate=True, index='trigram')

    sequence = fields.Integer(string='Sequence', default=10, index=True)

    color = fields.Integer(string='Color Index', default=0)

    active = fields.Boolean(default=True, index=True)





class SuccessionReviewCycle(models.Model):

    _name = 'succession.review.cycle'

    _description = 'Succession Review Cycle'

    _order = 'months, id'



    name = fields.Char(string='Cycle Name', required=True, translate=True, index='trigram')

    months = fields.Integer(string='Interval (Months)', required=True, default=12)

    sequence = fields.Integer(string='Sequence', default=10, index=True)

    active = fields.Boolean(default=True, index=True)





class SuccessionCriticalPositionReviewLog(models.Model):
    _name = 'succession.critical.position.review.log'
    _description = 'Critical Position Periodic Review & Validation Log'
    _order = 'review_date desc, id desc'

    position_id = fields.Many2one(
        'succession.critical.position',
        string='Critical Position',
        required=True,
        ondelete='cascade',
        index=True,
    )
    job_id = fields.Many2one('hr.job', related='position_id.job_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', related='position_id.department_id', store=True, readonly=True)

    # 1. WHO CONDUCTED THE REVIEW
    reviewed_by_id = fields.Many2one(
        'res.users',
        string='Lead Reviewer',
        default=lambda self: self.env.user,
        required=True,
        index=True,
    )
    reviewer_role = fields.Selection([
        ('ppdd_officer', 'PPDD Talent Management Officer'),
        ('ppdd_director', 'PPD Directorate Director'),
        ('spmc_member', 'SPMC Committee Member / Chair'),
        ('dept_head', 'Department Director / Incumbent Supervisor'),
        ('joint_panel', 'Joint PPDD & Executive Review Panel'),
    ], string='Reviewer Capacity', default='ppdd_officer', required=True)
    reviewer_title = fields.Char(string='Reviewer Title', compute='_compute_reviewer_title', store=True)
    review_panel_ids = fields.Many2many(
        'res.users',
        'succ_crit_review_log_user_rel',
        'log_id', 'user_id',
        string='Review Panel / Co-Reviewers',
    )

    @api.depends('reviewed_by_id')
    def _compute_reviewer_title(self):
        for rec in self:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', rec.reviewed_by_id.id)], limit=1) if rec.reviewed_by_id else False
            rec.reviewer_title = emp.job_id.name if emp and emp.job_id else (rec.reviewed_by_id.name or '')

    # 2. WHEN & REVIEW CADENCE
    review_date = fields.Date(
        string='Review Date',
        default=fields.Date.context_today,
        required=True,
        index=True,
    )
    cycle_id = fields.Many2one(
        'succession.review.cycle',
        string='Review Cycle',
        index=True,
    )
    review_trigger = fields.Selection([
        ('annual_cycle', 'Scheduled Periodic Review (Annual Cycle)'),
        ('semi_annual', 'Mid-Year Calibration / Bench Health Check'),
        ('incumbent_turnover', 'Incumbent Flight Risk / Imminent Exit'),
        ('org_change', 'Organizational Realignment / Strategy Shift'),
        ('bench_deficit', 'Ad-hoc Emergency Review (Critical Bench Deficit)'),
    ], string='Review Trigger / Occasion', default='annual_cycle', required=True)
    next_review_date = fields.Date(string='Next Scheduled Review Date')

    # 3. WHAT WAS REVIEWED (Assessment Pillars)
    criticality_reconfirmed = fields.Boolean(
        string='Criticality Reconfirmed',
        default=True,
    )
    vacancy_risk_level = fields.Selection([
        ('low', 'Low Risk (Easily Replaceable)'),
        ('medium', 'Medium Risk (Moderate Disruption)'),
        ('high', 'High Risk (Significant Operational Disruption)'),
        ('critical', 'Severe / Critical Risk (Operations Halt)'),
    ], string='Vacancy Impact Risk', default='high')

    # Successor Bench Snapshot
    ready_now_count = fields.Integer(string='Ready Now')
    ready_1_2_yrs_count = fields.Integer(string='Ready 1-2 Yrs')
    ready_3_5_yrs_count = fields.Integer(string='Ready 3-5 Yrs')
    total_bench_count = fields.Integer(string='Total Bench')
    bench_strength_summary = fields.Char(string='Bench Health at Review')
    bench_health = fields.Selection([
        ('strong', 'Strong (Multiple Ready Now)'),
        ('adequate', 'Adequate (At least 1 Ready Now)'),
        ('at_risk', 'At Risk (No Ready Now)'),
        ('critical', 'Critical (Empty Bench)'),
    ], string='Bench Health Status')

    # Competency & Incumbent Risk
    competency_status = fields.Selection([
        ('aligned', 'Competencies Fully Aligned with Role'),
        ('needs_revision', 'Competencies Need Revision / Modernization'),
        ('emerging_skills_needed', 'Emerging Skills / Certifications Missing'),
    ], string='Competency Profile Currency', default='aligned')
    incumbent_id = fields.Many2one('hr.employee', string='Incumbent at Review')
    incumbent_departure_horizon = fields.Selection([
        ('immediate', '< 6 Months (Imminent Departure)'),
        ('short_term', '6 - 18 Months (Near-Term Transition)'),
        ('medium_term', '18 - 36 Months (Mid-Term Horizon)'),
        ('stable', '> 3 Years / Stable Horizon'),
        ('vacant', 'Position Vacant / Acting Only'),
    ], string='Incumbent Horizon', default='stable')

    # 4. AFTER REVIEWED (Governance Decision & Action Plan)
    outcome = fields.Selection([
        ('validated', 'Validated & Retained (No Profile Changes)'),
        ('updated', 'Profile & Requirements Updated'),
        ('action_required', 'Urgent Action Required (Bench Deficit)'),
        ('downgraded', 'Recommended for Declassification / Downgrade'),
    ], string='Review Outcome', default='validated', required=True)
    action_plan_type = fields.Selection([
        ('maintain', 'Maintain Current Succession Plan (Standard Monitoring)'),
        ('nomination_campaign', 'Launch Urgent Candidate Nomination / Sourcing Drive'),
        ('accelerate_idp', 'Accelerate Development Plans for Ready Soon Candidates'),
        ('revise_competencies', 'Update Job Description & Competency Role Mapping'),
        ('external_search', 'Authorize External Talent Mapping / Recruitment Contingency'),
        ('spmc_escalation', 'Escalate Empty Bench Risk to SPMC for Immediate Intervention'),
    ], string='Primary Action Plan', default='maintain', required=True)
    action_owner_id = fields.Many2one('res.users', string='Action Owner')
    action_deadline = fields.Date(string='Action Due Date')
    recommendations = fields.Text(string='Findings & Action Plan')


class SuccessionCriticalPosition(models.Model):

    """

    Critical Position Register (FR-SWP-002, FR-SWP-003, FR-SWP-005).

    A critical position is any role whose vacancy would significantly impact

    the bank's operations, strategy, or risk posture.

    PPDD registers and maintains this list; SPMC provides final approval.

    """

    _name = 'succession.critical.position'

    _description = 'Succession: Critical Position'

    _inherit = ['mail.thread', 'mail.activity.mixin']

    _order = 'create_date desc, id desc'

    def _register_hook(self):
        super()._register_hook()
        try:
            self.env['ir.config_parameter'].sudo().set_param('mail.mail.force.send.limit', '0')
        except Exception:
            pass

    _rec_name = 'display_name'

    def init(self):
        super().init()
        # Ensure any legacy rule_succession_hr_employee_ppdd is permanently purged from DB
        self.env.cr.execute("""
            DELETE FROM rule_group_rel WHERE rule_group_id IN (
                SELECT id FROM ir_rule WHERE name = 'PPDD: Read All HR Employees'
            );
            DELETE FROM ir_rule WHERE name = 'PPDD: Read All HR Employees';
            DELETE FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'rule_succession_hr_employee_ppdd';

            -- Ensure legacy group_succession_employee is completely purged from DB
            DELETE FROM rule_group_rel WHERE group_id IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            );
            DELETE FROM res_groups_implied_rel WHERE gid IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            ) OR hid IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            );
            DELETE FROM res_groups_users_rel WHERE gid IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            );
            DELETE FROM ir_model_access WHERE group_id IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            );
            DELETE FROM res_groups WHERE id IN (
                SELECT res_id FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee'
            );
            DELETE FROM ir_model_data WHERE module = 'bunna_succession_management' AND name = 'group_succession_employee';
        """)



    # --- Core Identification ---

    job_id = fields.Many2one(

        'hr.job', string='Job Position', required=True,

        tracking=True, ondelete='restrict', index=True)

    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit',
        compute='_compute_work_unit_id', store=True, readonly=False, precompute=True,
        tracking=True, index=True)

    department_id = fields.Many2one(

        'hr.department', string='Department',

        compute='_compute_department_id', store=True, readonly=False, precompute=True,

        tracking=True, index=True)

    display_name = fields.Char(
        string='Critical Position', compute='_compute_display_name', store=True)
    active = fields.Boolean(string='Active', default=True, tracking=True, index=True)



    @api.onchange('job_id')
    def _onchange_job_id_duplicate_warning(self):
        if self.job_id:
            domain = [
                ('job_id', '=', self.job_id.id),
                ('active', '=', True),
            ]
            if self._origin.id:
                domain.append(('id', '!=', self._origin.id))
            existing = self.search(domain, limit=1)
            if existing:
                return {
                    'warning': {
                        'title': _("Position Already Registered"),
                        'message': _(
                            "A Critical Position for '%s' already exists (Status: %s)! "
                            "Each Job Position can only be registered once in Succession Management."
                        ) % (self.job_id.display_name, existing.state.upper()),
                    }
                }

    @api.constrains('job_id', 'active')
    def _check_unique_job_position(self):
        for rec in self:
            if rec.job_id and rec.active:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('job_id', '=', rec.job_id.id),
                    ('active', '=', True),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "A Critical Position record for '%s' already exists! "
                        "Each Job Position can only be created once in Succession Management."
                    ) % rec.job_id.display_name)



    @api.depends('job_id', 'department_id', 'department_id.operating_unit_id')
    def _compute_work_unit_id(self):
        for rec in self:
            rec.work_unit_id = rec._resolve_work_unit_for_job(rec.job_id) or rec.work_unit_id

    @api.depends('job_id', 'job_id.department_id')

    def _compute_department_id(self):

        for rec in self:

            rec.department_id = rec._resolve_department_for_job(rec.job_id) or rec.department_id



    @api.onchange('job_id')

    def _onchange_job_id(self):
        if self.job_id:
            resolved_dept = self._resolve_department_for_job(self.job_id)
            if resolved_dept:
                self.department_id = resolved_dept
            resolved_wu = self._resolve_work_unit_for_job(self.job_id)
            if resolved_wu:
                self.work_unit_id = resolved_wu

    @api.onchange('department_id')
    def _onchange_department_id(self):
        if self.department_id and getattr(self.department_id, 'operating_unit_id', False) and not self.work_unit_id:
            self.work_unit_id = self.department_id.operating_unit_id

    def _resolve_work_unit_for_job(self, job):
        if not job:
            return False
        # 1. Direct from job position's department operating unit
        if job.department_id and getattr(job.department_id, 'operating_unit_id', False):
            return job.department_id.operating_unit_id

        # 2. Check operating unit of active employees holding this job position
        emp = self.env['hr.employee'].sudo().search([
            ('job_id', '=', job.id),
            ('operating_unit_id', '!=', False)
        ], limit=1)
        if emp and emp.operating_unit_id:
            return emp.operating_unit_id

        # 2b. Check default_operating_unit_id of active employees
        if hasattr(self.env['hr.employee'].sudo(), 'default_operating_unit_id'):
            emp_def = self.env['hr.employee'].sudo().search([
                ('job_id', '=', job.id),
                ('default_operating_unit_id', '!=', False)
            ], limit=1)
            if emp_def and emp_def.default_operating_unit_id:
                return emp_def.default_operating_unit_id

        # 3. Check operating.unit.job.position mapping
        if 'operating.unit.job.position' in self.env:
            ou_job = self.env['operating.unit.job.position'].sudo().search([
                ('job_position_id', '=', job.id),
                ('operating_unit_id', '!=', False)
            ], limit=1)
            if ou_job and ou_job.operating_unit_id:
                return ou_job.operating_unit_id

        # 4. Check recent job vacancy for this position
        if 'job.vacancy' in self.env:
            vac = self.env['job.vacancy'].sudo().search([
                ('job_position', '=', job.id),
                ('operating_unit_id', '!=', False)
            ], order='id desc', limit=1)
            if vac and vac.operating_unit_id:
                return vac.operating_unit_id

        # 5. Check if department can be resolved and has an operating unit
        resolved_dept = self._resolve_department_for_job(job)
        if resolved_dept and getattr(resolved_dept, 'operating_unit_id', False):
            return resolved_dept.operating_unit_id

        # 6. Default to Head Office / Main Operating Unit
        if 'operating.unit' in self.env:
            ho = self.env['operating.unit'].sudo().search([('name', 'ilike', 'Head Office')], limit=1)
            if ho:
                return ho
            main_ou = self.env['operating.unit'].sudo().search([('name', 'ilike', 'Main Operating Unit')], limit=1)
            if main_ou:
                return main_ou

        return False

    def _resolve_department_for_job(self, job):

        if not job:

            return False

        # 1. Direct job position department

        if job.department_id:

            return job.department_id

            

        # 2. Check department of active employees holding this job position

        emp = self.env['hr.employee'].sudo().search([('job_id', '=', job.id), ('department_id', '!=', False)], limit=1)

        if emp and emp.department_id:

            return emp.department_id

            

        # 2b. Check other jobs with same title having department set
        other_job = self.env['hr.job'].sudo().search([
            ('name', '=ilike', job.name),
            ('department_id', '!=', False),
            ('id', '!=', job.id)
        ], limit=1)
        if other_job and other_job.department_id:
            return other_job.department_id

        # 3. Smart title keyword match against department directory

        job_name = job.name or ''

        stopwords = {'head', 'director', 'officer', 'manager', 'senior', 'junior', 'lead', 'chief', 'vp', 'executive', 'team', 'art', 'of', 'and', 'the', 'in', 'for', 'to'}

        words = [w for w in job_name.replace('(', ' ').replace(')', ' ').split() if len(w) > 2 and w.lower() not in stopwords]

        

        for word in words:

            dept = self.env['hr.department'].sudo().search([('name', 'ilike', word)], limit=1)

            if dept:

                return dept

        return False

    # --- Risk Classification (FR-SWP-002) ---

    risk_level_id = fields.Many2one('succession.risk.level', string='Risk Level', required=True, tracking=True, index=True, domain="[('active', '=', True)]")

    criticality_category_id = fields.Many2one(
        'succession.criticality.category',
        string='Criticality Reason', required=True, tracking=True, index=True, domain="[('active', '=', True)]",
        help='Reason why this position is considered critical (e.g. Executive Leadership, High Regulatory Risk).')
    criticality_category_ids = fields.Many2many(
        'succession.criticality.category',
        relation='succ_crit_cat_rel',
        string='Criticality Reasons (Legacy)', tracking=False, domain="[('active', '=', True)]")

    business_impact = fields.Text(
        string='Business Impact Statement',
        help='Describe the operational and strategic impact of this position being vacant.')

    vacancy_timeframe_id = fields.Many2one(
        'succession.timeframe', string='Target Succession Timeframe',
        required=True, tracking=True, index=True, domain="[('active', '=', True)]",
        help='Expected timeframe within which succession is required (e.g. Immediate, Short-Term, Long-Term).')

    @api.constrains('criticality_category_id', 'vacancy_timeframe_id')
    def _check_criticality_and_timeframe(self):
        for rec in self:
            if not rec.criticality_category_id:
                raise ValidationError(_("Criticality Reason is mandatory. Please select a reason justifying why this position is critical."))
            if not rec.vacancy_timeframe_id:
                raise ValidationError(_("Target Succession Timeframe is mandatory. Please select the succession timeframe."))

    # --- Strategic Workforce Planning Inputs (FR-SWP-001) ---
    strategic_plan_review_outcome = fields.Text(
        string='Strategic Alignment',
        help="How this position aligns with the bank's long-term strategic goals.")
    future_capability_reqs = fields.Text(
        string='Future Capability Requirements',
        help='Capabilities needed for this role in the next 3-5 years.')
    emerging_business_needs = fields.Text(
        string='Emerging Business Needs',
        help='New products, markets, technologies, or regulatory changes impacting this role.')
    workforce_risk_notes = fields.Text(
        string='Workforce Risk Notes',
        help='Specific flight risks, retirement risks, or market scarcity for this role.')

    # --- Review Cycle (FR-SWP-004) ---

    current_incumbent_id = fields.Many2one(
        'hr.employee',
        string='Current Incumbent',
        compute='_compute_current_incumbent',
        compute_sudo=True,
        store=True,
        help='Active employee currently occupying this critical position.'
    )
    declassification_recommended = fields.Boolean(
        string='Declassification Recommended',
        default=False,
        tracking=True,
        help='Set to True when periodic review recommends declassifying this role from the critical position register.'
    )

    @api.depends('job_id', 'department_id')
    def _compute_current_incumbent(self):
        for rec in self.sudo():
            emp = False
            if rec.job_id:
                domain = [('job_id', '=', rec.job_id.id), ('active', '=', True)]
                if rec.department_id:
                    domain.append(('department_id', '=', rec.department_id.id))
                emp = self.env['hr.employee'].sudo().search(domain, limit=1)
                if not emp:
                    emp = self.env['hr.employee'].sudo().search([('job_id', '=', rec.job_id.id), ('active', '=', True)], limit=1)
            rec.current_incumbent_id = emp

    review_cycle_id = fields.Many2one(
        'succession.review.cycle',
        string='Review Cycle',
        default=lambda self: self.env['succession.review.cycle'].search([('months', '=', 12)], limit=1) or self.env['succession.review.cycle'].search([], limit=1),
        tracking=True,
        index=True,
        domain="[('active', '=', True)]",
    )

    last_review_date = fields.Date(string='Last Review Date', tracking=True, index=True)

    next_review_date = fields.Date(string='Next Review Date', tracking=True, index=True)

    review_status = fields.Selection([
        ('up_to_date', 'Up-to-Date'),
        ('due_soon', 'Review Due Soon'),
        ('overdue', 'Review Overdue'),
    ], string='Review Status', compute='_compute_review_status', store=True, index=True)

    review_history_ids = fields.One2many(
        'succession.critical.position.review.log',
        'position_id',
        string='Review History',
    )

    @api.depends('next_review_date', 'state')
    def _compute_review_status(self):
        today = fields.Date.today()
        from datetime import timedelta
        due_soon_threshold = today + timedelta(days=30)
        for rec in self:
            if rec.state != 'approved':
                rec.review_status = 'up_to_date'
            elif not rec.next_review_date:
                rec.review_status = 'due_soon'
            elif rec.next_review_date < today:
                rec.review_status = 'overdue'
            elif rec.next_review_date <= due_soon_threshold:
                rec.review_status = 'due_soon'
            else:
                rec.review_status = 'up_to_date'

    def action_open_periodic_review_wizard(self):
        return False

    @api.onchange('review_cycle_id', 'state')

    def _onchange_review_cycle(self):

        for rec in self:

            if rec.review_cycle_id and rec.review_cycle_id.months:

                # If approved, date might be based on approval date, otherwise from today

                base_date = rec.spmc_approval_date.date() if (rec.spmc_approval_date and rec.state == 'approved') else fields.Date.today()

                # A simple approximation of adding months:

                rec.next_review_date = base_date + relativedelta(months=rec.review_cycle_id.months)



    # --- Succession Pipeline & Coverage Metrics ---
    ready_1_2_yrs_count = fields.Integer(
        string='Ready in 1-2 Years', compute='_compute_succession_stats', store=True)

    ready_3_5_yrs_count = fields.Integer(
        string='Ready in 3-5 Years', compute='_compute_succession_stats', store=True)

    total_bench_count = fields.Integer(
        string='Total Nominated Successors', compute='_compute_succession_stats', store=True)

    bench_health = fields.Selection([
        ('strong', 'Target Met (2+ Ready Now)'),
        ('adequate', 'Target Met (1 Ready Now)'),
        ('deficit', 'Successor Required (Under Target)'),
        ('at_risk', 'No Immediate Successor (0 Ready Now)'),
        ('critical', 'No Successors Nominated'),
    ], string='Successor Pipeline Status', compute='_compute_succession_stats', store=True, index=True)

    bench_deficit = fields.Integer(
        string='Successors Needed', compute='_compute_succession_stats', store=True,
        help='Number of additional successors needed to meet the minimum required count.')

    bench_readiness_summary = fields.Char(
        string='Readiness Breakdown', compute='_compute_succession_stats', store=True)


    # --- Competency Profile (FR-SWP-003) ---

    required_role_mapping_line_ids = fields.Many2many(
        'competency.role.mapping.line',
        string='Required Competencies',
        compute='_compute_required_role_mapping_line_ids',
        compute_sudo=True,
        help='Core competencies and proficiency levels that successors must demonstrate for this position.'
    )

    @api.depends('job_id')
    def _compute_required_role_mapping_line_ids(self):
        for rec in self.sudo():
            if rec.job_id:
                mapping = self.env['competency.role.mapping'].sudo().search([
                    ('job_position_id', '=', rec.job_id.id),
                    ('state', '=', 'approved')
                ], limit=1)
                if mapping and mapping.line_ids:
                    rec.required_role_mapping_line_ids = mapping.line_ids.sudo()
                else:
                    rec.required_role_mapping_line_ids = False
            else:
                rec.required_role_mapping_line_ids = False

    # --- Explicit Role Requirements (Pulled from Master hr.job) ---

    required_grade_id = fields.Many2one(

        related='job_id.required_grade_id', readonly=True,

        string='Required Job Grade'

    )

    required_experience_years = fields.Float(

        related='job_id.required_experience_years', readonly=True,

        string='Required Total Experience (Years)'

    )

    required_certificate = fields.Selection(

        related='job_id.required_certificate', readonly=True,

        string='Required Education Level'

    )

    required_study_field = fields.Char(

        related='job_id.required_study_field', readonly=True,

        string='Required Field of Study'

    )



    @api.model

    def _default_min_successor_count(self):

        policy = self.env['succession.governance.policy'].get_policy()

        return policy.succ_min_successors_global or 2



    min_successor_count = fields.Integer(

        string='Minimum Successor Count',

        default=_default_min_successor_count,

        help='Minimum number of identified successors (bench strength target).')



    # --- Approval Workflow (FR-SWP-005) ---

    state = fields.Selection([
        ('draft', 'Draft (PPDD)'),
        ('ppdd_review', 'PPDD Review'),
        ('spmc_approval', 'Pending SPMC Approval'),
        ('approved', 'Approved & Active'),
        ('placed', 'Placed'),
        ('deactivated', 'Deactivated'),
    ], string='Status', default='draft', tracking=True, index=True)

    ppdd_reviewed_by_id = fields.Many2one('res.users', string='PPDD Reviewed By', readonly=True, index=True)

    ppdd_review_date = fields.Datetime(string='PPDD Review Date', readonly=True)

    spmc_approved_by_id = fields.Many2one('res.users', string='SPMC Approved By', readonly=True, index=True)

    spmc_approval_date = fields.Datetime(string='SPMC Approval Date', readonly=True)

    notes = fields.Text(string='Notes / Justification')

    # --- Succession Statistics ---

    candidate_ids = fields.One2many(

        'succession.candidate', 'critical_position_id',

        string='Successor Candidates')

    invitation_ids = fields.One2many(
        'succession.candidate.invitation', 'critical_position_id',
        string='Succession Invitations')

    invitation_count = fields.Integer(
        string='Total Invitations', compute='_compute_invitation_counts')

    accepted_invitation_count = fields.Integer(
        string='Accepted Invitations', compute='_compute_invitation_counts')

    @api.depends('invitation_ids.state')
    def _compute_invitation_counts(self):
        for rec in self:
            rec.invitation_count = len(rec.invitation_ids)
            rec.accepted_invitation_count = len(rec.invitation_ids.filtered(lambda i: i.state == 'accepted'))

    def action_view_invitations(self):
        self.ensure_one()
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Succession Invitations'),
                'message': _('Opening invitations for "%s"...') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'name': _('Succession Invitations - %s') % pos_name,
                    'type': 'ir.actions.act_window',
                    'res_model': 'succession.candidate.invitation',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'domain': [('critical_position_id', '=', self.id)],
                    'context': {'default_critical_position_id': self.id},
                    'target': 'current',
                },
            }
        }

    # --- Standardized Assessment Plan (Position-Level) ---
    assessment_scope = fields.Selection([
        ('manager_only', 'Manager Evaluation Only'),
        ('manager_self', 'Manager + Candidate Self-Assessment'),
        ('manager_spmc', 'Manager + SPMC Committee Evaluation'),
        ('full_360', 'Comprehensive Multi-Rater (Manager, Self & SPMC)'),
        ('custom', 'Custom Evaluator Selection'),
    ], string='Competency Assessment Scope', default='manager_spmc', tracking=True,
       help='Standard multi-rater competency evaluation scope for candidates nominated to this critical position.')
    plan_include_manager = fields.Boolean(
        string='Manager Evaluation', default=True, tracking=True,
        help='Include direct manager evaluation on role competencies.')
    plan_include_self = fields.Boolean(
        string='Candidate Self-Assessment', default=False, tracking=True,
        help='Include candidate self-reflection evaluation.')
    def _domain_spmc_users(self):
        group = self.env.ref('bunna_succession_management.group_succession_spmc', raise_if_not_found=False)
        return [('all_group_ids', 'in', [group.id])] if group else []

    plan_include_spmc = fields.Boolean(
        string='SPMC Committee Evaluation', default=True, tracking=True,
        help='Include executive committee deliberation rating.')
    spmc_assessor_ids = fields.Many2many(
        'res.users',
        'succession_crit_pos_spmc_user_rel',
        'crit_pos_id',
        'user_id',
        string='Assigned SPMC Assessors',
        domain=lambda self: self._domain_spmc_users(),
        tracking=True,
        help='Designated SPMC Committee Members who will evaluate candidates for this critical position.')
    competency_formula_notice = fields.Char(
        string='Calculation Method', compute='_compute_formula_notice')
    assessment_line_ids = fields.One2many(
        'succession.critical.position.assessment.line', 'critical_position_id',
        string='Assessment & Exam Components')
    plan_total_weight = fields.Float(
        string='Total Configured Weight (%)', compute='_compute_plan_total_weight', store=True)
    plan_status = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Synced to Employees'),
        ('reopened', 'Reopened'),
        ('disabled', 'Disabled / Waived'),
    ], string='Plan Status', default='draft', tracking=True, index=True,
       help='Governance lifecycle state of the position assessment plan.')
    plan_locked = fields.Boolean(
        string='Plan Locked', compute='_compute_plan_locked', store=True, tracking=True,
        help='Indicates whether this assessment plan is locked against unauthorized modifications.')
    plan_locked_by_id = fields.Many2one(
        'res.users', string='Locked By', readonly=True, tracking=True, index=True)
    plan_locked_date = fields.Datetime(
        string='Locked Date', readonly=True, tracking=True)

    # Assessment Plan Candidate Synchronization Tracking
    plan_last_synced_date = fields.Datetime(
        string='Plan Last Synced', readonly=True, copy=False, tracking=True,
        help='Timestamp when this assessment plan was last pushed to nominated candidate scorecards.')
    plan_last_synced_by_id = fields.Many2one(
        'res.users', string='Plan Last Synced By', readonly=True, copy=False, index=True,
        help='User who triggered the latest candidate synchronization.')
    plan_synced_candidate_count = fields.Integer(
        string='Last Synced Candidate Count', readonly=True, copy=False, default=0,
        help='Number of candidates updated during the most recent synchronization.')
    nominated_candidate_count = fields.Integer(
        string='Nominated Candidates', compute='_compute_plan_sync_status', store=True,
        help='Current count of active nominated candidates awaiting assessment for this position.')
    unsynced_candidate_count = fields.Integer(
        string='Unsynced Candidates', compute='_compute_plan_sync_status', store=True,
        help='Count of nominated candidates who have not yet had their criteria synchronized.')
    plan_sync_status = fields.Selection([
        ('draft', 'Draft'),
        ('reopened', 'Reopened'),
        ('no_candidates', 'No Nominees'),
        ('pending', 'Sync Pending'),
        ('synced', 'Synced'),
        ('disabled', 'Disabled'),
    ], string='Candidate Sync Status', compute='_compute_plan_sync_status', store=True, tracking=True, index=True,
       help='Current synchronization state between this position assessment plan and its nominated candidates.')
    plan_sync_status_display = fields.Char(
        string='Sync Status Notice', compute='_compute_plan_sync_status_display')

    candidate_count = fields.Integer(
        string='Total Candidates', compute='_compute_succession_stats', store=True)

    ready_now_count = fields.Integer(
        string='Ready Now', compute='_compute_succession_stats', store=True)

    ready_soon_count = fields.Integer(
        string='Ready Soon (1-2 Yrs)', compute='_compute_succession_stats', store=True)

    ready_future_count = fields.Integer(
        string='Future Ready (3-5 Yrs)', compute='_compute_succession_stats', store=True)

    bench_strength = fields.Char(
        string='Nominated / Required', compute='_compute_succession_stats', store=True)

    succession_risk = fields.Selection([

        ('draft', 'Draft (Pending Pipeline)'),

        ('low', 'Low Risk'),

        ('medium', 'Medium Risk'),

        ('high', 'High Risk'),

        ('critical', 'Critical - No Successors'),

    ], string='Succession Risk', compute='_compute_succession_risk', store=True, index=True)



    # --- Audit ---

    governance_log_ids = fields.One2many(

        'succession.governance.log', 'critical_position_id',

        string='Governance Audit Log')



    @api.depends('job_id')

    def _compute_display_name(self):

        for rec in self:

            rec.display_name = rec.job_id.name if rec.job_id else '(No Position)'



    @api.depends('candidate_ids', 'candidate_ids.readiness_level_id',
                 'candidate_ids.state', 'min_successor_count')
    def _compute_succession_stats(self):
        for rec in self:
            active_candidates = rec.candidate_ids.filtered(
                lambda c: c.state in ('nominated', 'assessed', 'approved'))

            ready_now = active_candidates.filtered(
                lambda c: c.readiness_level_id and (
                    c.readiness_level_id.is_ready_for_deployment or
                    'now' in (c.readiness_level_id.name or '').lower() or
                    c.readiness_level_id.sequence <= 10
                ))

            ready_soon = active_candidates.filtered(
                lambda c: c.readiness_level_id and not (c in ready_now) and (
                    '1-2' in (c.readiness_level_id.name or '') or
                    '1 to 2' in (c.readiness_level_id.name or '') or
                    c.readiness_level_id.sequence == 20 or
                    (c.readiness_level_id.max_months and c.readiness_level_id.max_months <= 24)
                ))

            ready_future = active_candidates.filtered(
                lambda c: c.readiness_level_id and not (c in ready_now or c in ready_soon))

            now_count = len(ready_now)
            soon_count = len(ready_soon)
            future_count = len(ready_future)
            total_count = len(active_candidates)

            rec.candidate_count = total_count
            rec.total_bench_count = total_count
            rec.ready_now_count = now_count
            rec.ready_soon_count = soon_count
            rec.ready_1_2_yrs_count = soon_count
            rec.ready_future_count = future_count
            rec.ready_3_5_yrs_count = future_count

            target = rec.min_successor_count or 1
            rec.bench_strength = f"{total_count} / {target}"
            deficit = max(0, target - total_count)
            rec.bench_deficit = deficit

            if total_count == 0:
                rec.bench_health = 'critical'
            elif now_count == 0:
                rec.bench_health = 'at_risk'
            elif deficit > 0:
                rec.bench_health = 'deficit'
            elif now_count >= 2:
                rec.bench_health = 'strong'
            else:
                rec.bench_health = 'adequate'

            rec.bench_readiness_summary = (
                f"{now_count} Ready Now | {soon_count} Ready 1-2 Yrs | {future_count} Ready 3-5 Yrs"
            )



    @api.depends('candidate_ids', 'candidate_ids.readiness_level_id',

                 'candidate_ids.state', 'state', 'job_id')

    def _compute_succession_risk(self):

        for rec in self:

            if rec.state == 'draft' or not rec.job_id:

                rec.succession_risk = 'draft'

                continue

            approved_candidates = rec.candidate_ids.filtered(

                lambda c: c.state in ('assessed', 'approved'))

            ready_now_count = len(approved_candidates.filtered(lambda c: c.readiness_level_id and c.readiness_level_id.is_ready_for_deployment))

            ready_soon_count = len(approved_candidates.filtered(lambda c: c.readiness_level_id and not c.readiness_level_id.is_ready_for_deployment))

            candidate_count = len(approved_candidates)

            # Succession Risk Logic

            if ready_now_count >= 1:

                rec.succession_risk = 'low'

            elif ready_soon_count >= 1:

                rec.succession_risk = 'medium'

            elif candidate_count >= 1:

                rec.succession_risk = 'high'

            else:

                rec.succession_risk = 'critical'



    # --- Workflow Actions ---

    def action_submit_for_spmc_approval(self):

        """PPDD prepares critical position and submits directly for SPMC approval."""

        for rec in self:

            if not rec.business_impact:

                raise ValidationError(

                    _('Provide a Business Impact Statement before submitting for SPMC approval.'))

            rec.with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({

                'state': 'spmc_approval',

                'ppdd_reviewed_by_id': self.env.user.id,

                'ppdd_review_date': fields.Datetime.now(),

            })

            rec._log_governance('ppdd_approved', 'Prepared by PPDD -   Submitted for SPMC Approval')

            rec.with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(body=_('Critical position %s submitted by PPDD for SPMC approval.') % rec.display_name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted for SPMC Approval'),
                'message': _('Critical Position "%s" has been successfully submitted for SPMC approval.') % self.display_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }



    def action_spmc_approve(self):
        """Final SPMC approval - position is now officially critical and active."""
        for rec in self:
            rec.sudo().with_context(force_write=True, mail_notify_force_send=False, mail_post_autofollow=False).write({
                'state': 'approved',
                'spmc_approved_by_id': self.env.user.id,
                'spmc_approval_date': fields.Datetime.now(),
            })
            rec.sudo()._log_governance('spmc_approved', 'SPMC Final Approval Granted')
            rec.sudo().with_context(mail_notify_force_send=False, mail_post_autofollow=False).message_post(
                body=_('Critical position %s officially approved by SPMC (%s). Succession pipeline is now active.') % (
                    rec.display_name, self.env.user.name))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Critical Position Approved'),
                'message': _('Critical Position "%s" officially approved by SPMC. Succession pipeline is now active.') % self.display_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }



    @api.model
    def _parse_grade_num(self, grade_rec):
        """
        Parses an employee.grade record (or string) into an integer level (1 to 20).
        Supports Roman numerals (I - XX), Arabic numerals (1 - 20), and compound labels (e.g. 'XI - Grade XI').
        """
        if not grade_rec:
            return None
        code = getattr(grade_rec, 'grade_code', '') or ''
        name = getattr(grade_rec, 'grade_name', '') or ''
        display = getattr(grade_rec, 'display_name', '') or ''
        text_to_check = f"{code} {name} {display}".strip().upper()

        roman_map = {
            'XX': 20, 'XIX': 19, 'XVIII': 18, 'XVII': 17, 'XVI': 16,
            'XV': 15, 'XIV': 14, 'XIII': 13, 'XII': 12, 'XI': 11,
            'X': 10, 'IX': 9, 'VIII': 8, 'VII': 7, 'VI': 6,
            'V': 5, 'IV': 4, 'III': 3, 'II': 2, 'I': 1
        }
        if code.strip().upper() in roman_map:
            return roman_map[code.strip().upper()]
        for token in text_to_check.replace('-', ' ').replace('/', ' ').replace('(', ' ').replace(')', ' ').split():
            clean_token = token.strip().strip(':,.')
            if clean_token in roman_map:
                return roman_map[clean_token]
        digit_match = re.search(r'\b([1-9]|1[0-9]|20)\b', text_to_check)
        if digit_match:
            try:
                return int(digit_match.group(1))
            except ValueError:
                pass
        digits = ''.join(filter(str.isdigit, text_to_check))
        if digits:
            try:
                val = int(digits)
                if 1 <= val <= 30:
                    return val
            except ValueError:
                pass
        return None

    def _get_employee_active_discipline_cases(self, employee):
        """Check for active disciplinary cases across Bunna Bank modules."""
        case_names = []
        if not employee:
            return case_names

        # 1. discipline.case (discipline_management module)
        if 'discipline.case' in self.env:
            try:
                cases = self.env['discipline.case'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', 'not in', ['revoked', 'closed']),
                ])
                for c in cases:
                    case_names.append(c.name or 'Disciplinary Case')
            except Exception:
                pass

        # 2. discipline.action (hr_employee_custom module)
        if 'discipline.action' in self.env:
            try:
                actions = self.env['discipline.action'].sudo().search([
                    ('employee_name', '=', employee.id),
                ])
                for a in actions:
                    case_names.append(getattr(a, 'ref_no', False) or getattr(a, 'name', False) or 'Disciplinary Action')
            except Exception:
                pass

        # 3. disciplinary.action (hr_employee_custom module)
        if 'disciplinary.action' in self.env:
            try:
                d_actions = self.env['disciplinary.action'].sudo().search([
                    ('employee_name', '=', employee.id),
                ])
                for da in d_actions:
                    case_names.append(getattr(da, 'ref_no', False) or getattr(da, 'name', False) or 'Disciplinary Action')
            except Exception:
                pass

        return case_names

    def _get_employee_location_years(self, employee):
        """
        Calculates employee's experience in their current location (operating unit / branch).
        Matches recruitment logic in recruitment_process_internal:
        1. Checks employee.current_location_exp if defined.
        2. Checks hr.employee.transfer.history for transfer to current operating unit.
        3. Checks hr.job.history for current operating unit.
        4. Fallbacks to position duration or hire date.
        """
        if not employee:
            return 0.0

        if hasattr(employee, 'current_location_exp') and employee.current_location_exp:
            return float(employee.current_location_exp)

        today = fields.Date.today()
        ou_id = employee.default_operating_unit_id.id if getattr(employee, 'default_operating_unit_id', False) else False
        loc_date = False

        if ou_id and 'hr.employee.transfer.history' in self.env:
            try:
                trans_hist = self.env['hr.employee.transfer.history'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('to_operating_unit_id', '=', ou_id),
                ], order='is_current desc, start_date desc, date desc, id desc', limit=1)
                if trans_hist and (trans_hist.start_date or trans_hist.date):
                    loc_date = trans_hist.start_date or trans_hist.date
            except Exception:
                pass

        if not loc_date and ou_id and 'hr.job.history' in self.env:
            try:
                job_hist = self.env['hr.job.history'].sudo().search([
                    ('employee_id', '=', employee.id),
                    '|', ('to_operating_unit_id', '=', ou_id), ('operating_unit_id', '=', ou_id),
                    '|', ('job_history_end_date', '=', False), ('job_history_end_date', '>=', today),
                ], order='is_current desc, job_history_start_date desc, id desc', limit=1)
                if job_hist and job_hist.job_history_start_date:
                    loc_date = job_hist.job_history_start_date
            except Exception:
                pass

        if not loc_date:
            hire_date = (
                getattr(employee, 'service_start_date', False)
                or getattr(employee, 'service_hire_date', False)
                or getattr(employee, 'first_contract_date', False)
                or getattr(employee, 'joining_date', False)
            )
            loc_date = hire_date

        return round((today - loc_date).days / 365.25, 2) if loc_date else 0.0

    def _get_employee_pms_score(self, employee, target_min_pms=0.0):
        """
        Retrieves the employee's PMS (Performance Management System) score.
        Checks:
        1. employee.pms_score
        2. employee.contract_id.pms_score
        3. hr.pms.result (latest final_score)
        4. hr.appraisal (latest rating)
        Normalizes 5-point rating scales to 100-point percentages if target is out of 100.
        """
        if not employee:
            return 0.0
        score = 0.0
        if hasattr(employee, 'pms_score') and employee.pms_score:
            score = float(employee.pms_score)
        elif hasattr(employee, 'contract_id') and employee.contract_id and hasattr(employee.contract_id, 'pms_score') and employee.contract_id.pms_score:
            score = float(employee.contract_id.pms_score)
        elif 'hr.pms.result' in self.env:
            try:
                res = self.env['hr.pms.result'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['done', 'approved', 'confirmed']),
                ], order='date desc, id desc', limit=1)
                if not res:
                    res = self.env['hr.pms.result'].sudo().search([
                        ('employee_id', '=', employee.id),
                    ], order='id desc', limit=1)
                if res and getattr(res, 'final_score', 0.0):
                    score = float(res.final_score)
            except Exception:
                pass
        if not score and 'hr.appraisal' in self.env:
            try:
                appr = self.env['hr.appraisal'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['done']),
                ], order='date_close desc, id desc', limit=1)
                if appr and getattr(appr, 'rating', 0.0):
                    score = float(appr.rating)
            except Exception:
                pass

        if target_min_pms > 5.0 and 0.0 < score <= 5.0:
            score = round((score / 5.0) * 100.0, 2)
        elif 0.0 < target_min_pms <= 5.0 and score > 5.0:
            score = round((score / 100.0) * 5.0, 2)
        return score

    @api.model
    def _check_employee_education_match(self, employee, target_edu_reqs):
        """
        Validates if employee meets at least one of the target educational qualifications
        configured on hr.job (Education Qualification tab) and meets the required CGPA.
        Returns: (is_matched, matched_qual_name, cand_cgpa, failure_reason)
        """
        if not target_edu_reqs:
            return True, '', 0.0, ''

        emp = employee.sudo()
        DEGREE_SYNONYMS = {
            'bsc': 'bachelor', 'b.sc': 'bachelor', 'bachelor': 'bachelor', 'bachelors': 'bachelor',
            'ba': 'bachelor', 'b.a': 'bachelor', 'bed': 'bachelor', 'llb': 'bachelor',
            'msc': 'master', 'm.sc': 'master', 'master': 'master', 'masters': 'master',
            'mba': 'master', 'ma': 'master', 'm.a': 'master', 'llm': 'master',
            'phd': 'doctorate', 'ph.d': 'doctorate', 'doctorate': 'doctorate',
            'diploma': 'diploma', 'tvet': 'tvet',
        }

        def _norm(text):
            if not text:
                return ""
            words = text.lower().replace('/', ' ').replace('.', ' ').replace(',', ' ').split()
            return " ".join([DEGREE_SYNONYMS.get(w, w) for w in words])

        emp_records = []

        # Source 1: hr_qualification_info_job (qualification_id)
        if hasattr(emp, 'qualification_id') and emp.qualification_id:
            for q in emp.qualification_id.sudo():
                if q.qualification:
                    name = getattr(q.qualification, 'qualification', '') or getattr(q.qualification, 'display_name', '') or ''
                    cgpa = max(float(q.requirement or 0.0), float(q.response or 0.0))
                    emp_records.append({
                        'id': getattr(q.qualification, 'id', None),
                        'name': name,
                        'norm': _norm(name),
                        'cgpa': cgpa,
                        'source': 'qualification_id',
                    })

        # Source 2: employee.education (education_detail_ids)
        if hasattr(emp, 'education_detail_ids') and emp.education_detail_ids:
            for edu in emp.education_detail_ids.sudo():
                q_name = getattr(edu, 'qualification', '') or ''
                field_name = getattr(edu, 'field', '') or ''
                type_name = getattr(edu, 'edu_type', '') or ''
                full_name = f"{q_name} {field_name}".strip() or type_name
                cgpa = float(getattr(edu, 'CGPA', 0.0) or getattr(edu, 'cgpa_percentage', 0.0) or 0.0)
                emp_records.append({
                    'id': None,
                    'name': full_name,
                    'norm': _norm(f"{q_name} {field_name} {type_name}"),
                    'cgpa': cgpa,
                    'source': 'education_detail_ids',
                })

        # Source 3: hr.employee.education (edu_ids or education_ids)
        for rel in ('edu_ids', 'education_ids'):
            if hasattr(emp, rel) and getattr(emp, rel):
                for edu in getattr(emp, rel).sudo():
                    q_name = getattr(edu, 'qualification', '') or ''
                    spec = getattr(edu, 'specialization', '') or ''
                    cgpa = float(getattr(edu, 'cgpa_percentage', 0.0) or 0.0)
                    emp_records.append({
                        'id': None,
                        'name': f"{q_name} {spec}".strip(),
                        'norm': _norm(f"{q_name} {spec}"),
                        'cgpa': cgpa,
                        'source': rel,
                    })

        # Source 4: employee.study_field / educational_qualification char fields
        for fld in ('study_field', 'educational_qualification'):
            val = getattr(emp, fld, False)
            if val:
                emp_records.append({
                    'id': None,
                    'name': str(val),
                    'norm': _norm(str(val)),
                    'cgpa': 0.0,
                    'source': fld,
                })

        best_cgpa = 0.0
        low_cgpa_failures = []

        for req in target_edu_reqs:
            req_id = req.get('id')
            req_name = req.get('name', '')
            req_norm = _norm(req_name)
            req_words = [w for w in req_norm.split() if len(w) > 2 and w not in ('and', 'for', 'the', 'with')]
            min_cgpa = req.get('min_cgpa', 0.0)

            for rec in emp_records:
                id_match = (req_id and rec.get('id') == req_id)
                text_match = (
                    req_norm == rec['norm']
                    or req_norm in rec['norm']
                    or rec['norm'] in req_norm
                    or (req_words and all(w in rec['norm'] for w in req_words))
                )

                if id_match or text_match:
                    cand_cgpa = rec['cgpa']
                    if cand_cgpa > 0:
                        best_cgpa = max(best_cgpa, cand_cgpa)

                    if min_cgpa > 0 and cand_cgpa > 0 and cand_cgpa < min_cgpa:
                        low_cgpa_failures.append((req_name, cand_cgpa, min_cgpa))
                        continue

                    # Success match!
                    return True, req_name, best_cgpa, ''

        if low_cgpa_failures:
            f_qual, f_cgpa, f_min = low_cgpa_failures[0]
            fail_msg = _('Education Qualification CGPA: Has %s with CGPA %.2f, but minimum required is %.2f.') % (f_qual, f_cgpa, f_min)
            return False, '', best_cgpa, fail_msg

        req_names_str = ", ".join([r['name'] for r in target_edu_reqs[:3]])
        cand_names_str = ", ".join([r['name'] for r in emp_records[:2]]) if emp_records else _('None recorded')
        fail_msg = _('Education Qualification: Does not hold any of the required qualifications (%s). Current education: %s.') % (req_names_str, cand_names_str)
        return False, '', best_cgpa, fail_msg

    def evaluate_employee_eligibility(self, employee):
        """
        Evaluates a single employee against the official Recruitment & Promotion criteria
        configured on this Critical Position's hr.job:
        1. Current Position assignment & not already holding target position.
        2. Eligible Feeder Positions (hr.job -> Eligible Position tab: position_id with status=True).
        3. Strict / Exact Grade Match (hr.job -> Eligible Grades tab: grade_recruitment_id with status=True).
        4. Minimum Company Tenure (hr.job -> HR Policies: minimum_number_years_in_company).
        5. Current Location Experience (hr.job -> HR Policies: current_location_exp).
        6. Promotion Timing (hr.job -> HR Policies: no_of_months_since_last_promotion).
        7. Minimum PMS Score (hr.job -> HR Policies: minimum_pms_score).
        8. Total & Supervisory Experience (hr.job -> Experience: required_experience_years & experiance_id).
        9. Disciplinary Policies (hr.job -> HR Policies: demoted_employee, promotion_revoked,
           no_of_months_since_last_written_notice, and active disciplinary cases).
        10. Educational Qualification & CGPA (hr.job -> Education Qualification tab: qualification_id).
        Returns a dict:
        {
            'is_eligible': bool,
            'failure_reasons': list of str,
            'match_data': dict (if eligible or partial),
            'is_already_nominated': bool,
            'invitation': browse_record or False,
        }
        """
        self.ensure_one()
        target_job = self.job_id.sudo()
        if not target_job:
            return {
                'is_eligible': False,
                'failure_reasons': [_('Critical Position has no Job Position configured.')],
                'match_data': {},
                'is_already_nominated': False,
                'invitation': False,
            }

        failure_reasons = []
        today = fields.Date.today()

        existing_candidate = self.env['succession.candidate'].search([
            ('critical_position_id', '=', self.id),
            ('employee_id', '=', employee.id),
        ], limit=1)
        is_already_nominated = bool(existing_candidate)

        inv = self.env['succession.candidate.invitation'].search([
            ('critical_position_id', '=', self.id),
            ('employee_id', '=', employee.id),
        ], limit=1)

        # 1. Check current position vs target position
        emp_job = employee.job_id or getattr(employee, 'job_position', False)
        emp_job_id = emp_job.id if emp_job else None
        if not emp_job:
            failure_reasons.append(_('Employee has no Job Position assigned in their profile.'))
        elif emp_job.id == target_job.id:
            failure_reasons.append(_('Employee currently holds this exact position (%s).') % target_job.name)

        # 2. Eligible Feeder Positions (Strictly from hr.job Eligible Position tab)
        target_eligible_job_ids = set()
        if hasattr(target_job, 'position_id') and target_job.position_id:
            target_eligible_job_ids = set(target_job.position_id.filtered(lambda p: p.status and p.position).mapped('position.id'))

        if target_eligible_job_ids:
            if not emp_job_id or emp_job_id not in target_eligible_job_ids:
                feeder_names = ', '.join(target_job.position_id.filtered(lambda p: p.status and p.position).mapped('position.name')[:3])
                emp_title = emp_job.name if emp_job else _('None')
                failure_reasons.append(_('Position: Current position "%s" is not in the eligible feeder positions (%s).') % (emp_title, feeder_names))
        else:
            is_feeder_or_eligible = (
                (emp_job_id == target_job.id)
                or bool(getattr(target_job, 'grade_recruitment_id', False))
            )
            if not is_feeder_or_eligible:
                failure_reasons.append(_('Position: Current position "%s" is not an eligible feeder position.') % (emp_job.name if emp_job else ''))

        # 3. Exact Grade Match (Strictly from hr.job Eligible Grades tab)
        target_eligible_grade_ids = set()
        if hasattr(target_job, 'grade_recruitment_id') and target_job.grade_recruitment_id:
            for el in target_job.grade_recruitment_id:
                if el.status and el.job_grade:
                    target_eligible_grade_ids.add(el.job_grade.id)

        target_grade = self.required_grade_id or target_job.required_grade_id or target_job.grade

        emp_grade = employee.job_grade or getattr(employee, 'grade_id', False)
        emp_grade_name = emp_grade.grade_code if emp_grade and getattr(emp_grade, 'grade_code', False) else (emp_grade.display_name if emp_grade else '')

        if not emp_grade:
            failure_reasons.append(_('Grade: Employee has no Job Grade assigned in their profile.'))
        elif target_eligible_grade_ids:
            if emp_grade.id not in target_eligible_grade_ids:
                allowed_grades = ', '.join([g.grade_code or g.display_name for g in target_job.grade_recruitment_id.filtered(lambda x: x.status and x.job_grade).mapped('job_grade')])
                failure_reasons.append(_('Grade: Current grade "%s" does not match the exact eligible grade required (%s).') % (emp_grade_name or 'N/A', allowed_grades))
        elif target_grade:
            if emp_grade.id != target_grade.id:
                failure_reasons.append(_('Grade: Current grade "%s" does not match exact target grade %s.') % (emp_grade_name, target_grade.name))

        # 4. Bank Service Tenure (hr.job -> HR Policies: minimum_number_years_in_company)
        target_min_company_years = getattr(target_job, 'minimum_number_years_in_company', 0) or 0
        hire_date = (
            getattr(employee, 'service_start_date', False)
            or getattr(employee, 'service_hire_date', False)
            or getattr(employee, 'first_contract_date', False)
            or getattr(employee, 'joining_date', False)
        )
        emp_service_years = round((today - hire_date).days / 365.25, 2) if hire_date else 0.0
        if not emp_service_years and getattr(employee, 'service_duration_years', False):
            emp_service_years = float(employee.service_duration_years)

        if target_min_company_years > 0 and emp_service_years < target_min_company_years:
            failure_reasons.append(_('Bank Service: Served %.1f years in the company, but minimum required is %.1f years.') % (emp_service_years, target_min_company_years))

        # 5. Current Location Experience (hr.job -> HR Policies: current_location_exp)
        target_min_loc_exp = getattr(target_job, 'current_location_exp', 0.0) or 0.0
        emp_loc_years = self._get_employee_location_years(employee)
        if target_min_loc_exp > 0 and emp_loc_years < target_min_loc_exp:
            failure_reasons.append(_('Current Location Experience: Has spent %.1f years in current location, but minimum required is %.1f years.') % (emp_loc_years, target_min_loc_exp))

        # 6. Promotion Timing (hr.job -> HR Policies: no_of_months_since_last_promotion)
        target_min_promo_months = getattr(target_job, 'no_of_months_since_last_promotion', 0) or 0
        actual_promo = False
        if 'hr.job.history' in self.env:
            try:
                actual_promo = self.env['hr.job.history'].sudo().search([
                    ('employee_id', '=', employee.id),
                    '|', ('reason_for_movement', 'in', ['promotion', 'lateral_transfer']),
                    ('job_id', '!=', emp_job_id if emp_job_id else False)
                ], order='job_history_start_date desc', limit=1)
            except Exception:
                pass

        if actual_promo and actual_promo.job_history_start_date:
            pdate = actual_promo.job_history_start_date
        else:
            pdate = hire_date

        last_promotion_months = round((today - pdate).days / 30.4375, 1) if pdate else 0.0
        if target_min_promo_months > 0 and last_promotion_months < target_min_promo_months:
            failure_reasons.append(_('Promotion Timing: Has spent %.1f months in current position, but minimum required is %.1f months.') % (last_promotion_months, target_min_promo_months))

        # 7. Minimum PMS Score (hr.job -> HR Policies: minimum_pms_score)
        target_min_pms = getattr(target_job, 'minimum_pms_score', 0.0) or 0.0
        emp_pms = self._get_employee_pms_score(employee, target_min_pms=target_min_pms)
        if target_min_pms > 0 and emp_pms < target_min_pms:
            failure_reasons.append(_('PMS Score: Employee latest PMS score is %.2f, but minimum required is %.2f.') % (emp_pms, target_min_pms))

        # 8. Total Experience & Supervisory Experience (hr.job -> Experience tab: required_experience_years & experiance_id)
        # ── 4. Experience Criteria from hr.job (Experience tab: Requirement column) ──
        target_req_exps = {}
        target_sup_exp = 0.0
        target_line_max_exp = 0.0
        if hasattr(target_job, 'experiance_id') and target_job.experiance_id:
            for ex in target_job.experiance_id:
                # Strictly take the numerical value typed in the 'Requirement' column
                req_val = float(ex.requirement or 0.0)
                ex_label = ''
                if ex.experience:
                    target_req_exps[ex.experience.id] = req_val
                    ex_label = (getattr(ex.experience, 'display_name', '') or getattr(ex.experience, 'experience', '') or '').lower()
                    if 'supervis' in ex_label:
                        target_sup_exp = max(target_sup_exp, req_val)
                if req_val > 0:
                    target_line_max_exp = max(target_line_max_exp, req_val)

        target_exp_years = max(
            getattr(target_job, 'required_experience_years', 0.0) or 0.0,
            target_line_max_exp,
            max(target_req_exps.values()) if target_req_exps else 0.0
        )

        # ── 4b. Education Qualification Criteria from hr.job (Education Qualification tab) ──
        target_edu_reqs = []
        if hasattr(target_job, 'qualification_id') and target_job.qualification_id:
            for q in target_job.qualification_id:
                if q.qualification:
                    q_name = (getattr(q.qualification, 'qualification', '') or getattr(q.qualification, 'display_name', '') or '').strip()
                    if q_name:
                        target_edu_reqs.append({
                            'id': q.qualification.id,
                            'name': q_name,
                            'min_cgpa': float(q.requirement or 0.0),
                        })

        prev_years = 0.0
        if hasattr(employee, 'previous_occupation_ids') and employee.previous_occupation_ids:
            for occ in employee.previous_occupation_ids:
                if occ.from_date and occ.to_date and occ.to_date > occ.from_date:
                    prev_years += (occ.to_date - occ.from_date).days / 365.25
        prev_years = round(prev_years, 2)
        emp_total_exp = round(emp_service_years + prev_years, 2)

        if target_exp_years > 0 and emp_total_exp < target_exp_years:
            failure_reasons.append(_('Total Experience: Total experience is %.1f years, but minimum required is %.1f years.') % (emp_total_exp, target_exp_years))

        if target_sup_exp > 0:
            emp_sup_exp = 0.0
            if hasattr(employee, 'experiance_id') and employee.experiance_id:
                for ex in employee.experiance_id:
                    ex_label = (getattr(ex.experience, 'display_name', '') or getattr(ex.experience, 'experience', '') or '').lower()
                    if 'supervis' in ex_label:
                        emp_sup_exp = max(emp_sup_exp, ex.requirement or 0.0, ex.response or 0.0)
            if not emp_sup_exp and hasattr(employee, 'previous_occupation_ids') and employee.previous_occupation_ids:
                for occ in employee.previous_occupation_ids:
                    occ_title = (getattr(occ, 'position', '') or getattr(occ, 'role', '') or '').lower()
                    if any(kw in occ_title for kw in ['supervis', 'manager', 'lead', 'head', 'director']):
                        if occ.from_date and occ.to_date and occ.to_date > occ.from_date:
                            emp_sup_exp += (occ.to_date - occ.from_date).days / 365.25
            if emp_sup_exp < target_sup_exp:
                failure_reasons.append(_('Supervisory Experience: Supervisory experience is %.1f years, but required is %.1f years.') % (emp_sup_exp, target_sup_exp))

        # 9. Disciplinary Checks (hr.job -> HR Policies: demoted_employee, promotion_revoked, no_of_months_since_last_written_notice)
        allow_demoted = getattr(target_job, 'demoted_employee', False)
        allow_revoked = getattr(target_job, 'promotion_revoked', True)
        written_notice_months = getattr(target_job, 'no_of_months_since_last_written_notice', 0) or 0

        is_demoted = bool(getattr(employee, 'is_demoted', False))
        if not is_demoted and 'employee.demotion' in self.env:
            try:
                demot_cnt = self.env['employee.demotion'].sudo().search_count([
                    ('employee_name', '=', employee.id),
                    ('state', '=', 'approve'),
                    '|', ('demoted_until', '=', False), ('demoted_until', '>=', today),
                ])
                if demot_cnt > 0:
                    is_demoted = True
            except Exception:
                pass

        if not allow_demoted and is_demoted:
            failure_reasons.append(_('Disciplinary: Employee has a recorded demotion.'))
        if getattr(employee, 'demoted_until', False) and employee.demoted_until > today:
            failure_reasons.append(_('Disciplinary: Employee demotion period active until %s.') % employee.demoted_until)
        if hasattr(employee, 'is_eligible_for_promotion') and employee.is_eligible_for_promotion is False:
            failure_reasons.append(_('Disciplinary: Marked not eligible for promotion in HR master.'))
        if not allow_revoked and getattr(employee, 'promotion_revoked', False):
            failure_reasons.append(_('Disciplinary: Employee promotion status has been revoked.'))
        if written_notice_months > 0:
            if hasattr(employee, 'months_since_last_written_notice') and employee.months_since_last_written_notice and employee.months_since_last_written_notice < written_notice_months:
                failure_reasons.append(_('Disciplinary: Received written notice within the last %d months.') % written_notice_months)

        active_discipline_cases = self._get_employee_active_discipline_cases(employee)
        if active_discipline_cases:
            failure_reasons.append(_('Disciplinary: Active disciplinary case(s) found: %s.') % ', '.join(active_discipline_cases))

        # 10. Education Qualification Criteria (hr.job -> Education Qualification tab)
        is_edu_matched = True
        edu_matched_name = ''
        cand_cgpa = 0.0
        if target_edu_reqs:
            is_edu_matched, edu_matched_name, cand_cgpa, edu_fail = self._check_employee_education_match(employee, target_edu_reqs)
            if not is_edu_matched:
                req_names = ', '.join([r['name'] for r in target_edu_reqs])
                failure_reasons.append(_('Education: Does not meet required qualification (%s). %s') % (req_names, edu_fail or ''))

        if target_edu_reqs and is_edu_matched and edu_matched_name:
            qual_summary = edu_matched_name
            qualification_desc = f"{edu_matched_name} (CGPA: {cand_cgpa:.2f})" if cand_cgpa > 0 else edu_matched_name
        else:
            emp_qual_names = set()
            if hasattr(employee, 'qualification_id') and employee.qualification_id:
                for q in employee.qualification_id:
                    if q.qualification:
                        name = getattr(q.qualification, 'display_name', '') or getattr(q.qualification, 'qualification', '') or getattr(q.qualification, 'name', '')
                        if name:
                            emp_qual_names.add(name.strip().lower())
            if hasattr(employee, 'education_detail_ids') and employee.education_detail_ids:
                for edu in employee.education_detail_ids:
                    q_name = getattr(edu, 'qualification', '') or ''
                    if q_name:
                        emp_qual_names.add(q_name.strip().lower())
            if hasattr(employee, 'edu_ids') and employee.edu_ids:
                for edu in employee.edu_ids:
                    if edu.qualification:
                        emp_qual_names.add(edu.qualification.strip().lower())

            qual_summary = ', '.join([q.title() for q in sorted(emp_qual_names)[:2]]) if emp_qual_names else ''
            if not qual_summary and hasattr(employee, 'education_detail_ids') and employee.education_detail_ids:
                quals = [getattr(e, 'qualification', '') or '' for e in employee.education_detail_ids if getattr(e, 'qualification', '')]
                if quals:
                    qual_summary = ', '.join(quals[:2])
            if not qual_summary:
                qual_summary = 'None'
            qualification_desc = qual_summary

        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        default_deadline = today + timedelta(days=expiry_days)
        acceptance_end_date = inv.deadline_date if inv and inv.deadline_date else default_deadline

        curr_loc = employee.default_operating_unit_id.name if employee.default_operating_unit_id else (
            employee.department_id.operating_unit_id.name if getattr(employee.department_id, 'operating_unit_id', False) else ''
        )
        curr_dept = employee.department_id.name if employee.department_id else ''

        if is_already_nominated:
            inv_status = 'already_in_pipeline'
        elif inv:
            if inv.state == 'invited' and inv.deadline_date and inv.deadline_date < today:
                inv_status = 'expired'
            else:
                inv_status = inv.state
        else:
            inv_status = 'none'

        match_data = {
            'employee_id': employee.id,
            'is_selected': True,
            'acceptance_end_date': acceptance_end_date,
            'app_date': acceptance_end_date,
            'grade_name': emp_grade_name or '',
            'job_title': emp_job.name if emp_job else '',
            'category': emp_job.employee_category if emp_job and hasattr(emp_job, 'employee_category') else (getattr(employee, 'job_category', '') or 'Non Managerial'),
            'employment_type': emp_job.type_of_employment if emp_job and hasattr(emp_job, 'type_of_employment') else (getattr(employee, 'type_of_employment', '') or 'Permanent'),
            'gender': employee.gender or '',
            'current_location': curr_loc or '',
            'current_department': curr_dept or '',
            'educational_qualification': qual_summary,
            'service_in_company': emp_service_years,
            'relevant_experience': emp_total_exp,
            'employment_experience': prev_years,
            'total_experience': emp_total_exp,
            'invitation_id': inv.id if inv else False,
            'invitation_status': inv_status,
            'already_nominated': is_already_nominated,
            'last_promotion_months': last_promotion_months,
            'qualification_desc': qual_summary,
            'eligibility_status': _('Eligible - Meets Promotion Criteria') if not failure_reasons else _('Ineligible'),
            'career_proximity': 'Promotion Feeder Role',
            'composite_score': 100.0 if not failure_reasons else 0.0,
            'tenure_years': emp_service_years,
            'total_exp_years': emp_total_exp,
            'latest_pms_score': emp_pms,
        }

        return {
            'is_eligible': len(failure_reasons) == 0,
            'failure_reasons': failure_reasons,
            'match_data': match_data,
            'is_already_nominated': is_already_nominated,
            'invitation': inv,
        }

    def get_auto_match_candidates_data(self):
        """
        Runs candidate matching strictly using Recruitment Module Job Position Criteria
        defined on hr.job (matching custom_recruitment logic and layout):
        1. Position Eligibility: Employee's current job position must be in Eligible Positions
           (position_id / employee.recruitment.position with status=True) configured on hr.job.
        2. Exact Grade Eligibility: Employee's current grade must exactly match an Eligible Grade
           (grade_recruitment_id / employee.recruitment.grade with status=True) configured on hr.job.
        3. Minimum Company Tenure: Employee's bank service years must meet or exceed
           minimum_number_years_in_company from hr.job HR Policies.
        4. Current Location Experience: Employee's experience in current operating unit must meet or exceed
           current_location_exp from hr.job HR Policies.
        5. Promotion Timing: Employee's months in current position must meet or exceed
           no_of_months_since_last_promotion from hr.job HR Policies.
        6. Minimum PMS Score: Employee's PMS score must meet or exceed minimum_pms_score from hr.job HR Policies.
        7. Total & Supervisory Experience: Total experience must meet required experience from
           experiance_id & required_experience_years, and supervisory experience must meet requirement.
        8. Disciplinary Knockout: Exclude demoted employees (if demoted_employee is False),
           employees with promotion revoked, employees with recent written notice within
           no_of_months_since_last_written_notice, and employees with active disciplinary cases.
        9. Educational Qualification & CGPA (hr.job -> Education Qualification tab: qualification_id).
        """
        self.ensure_one()
        target_job = self.job_id.sudo()
        if not target_job:
            return []

        # Existing nominated candidates for this critical position (in pipeline)
        existing_candidate_emp_ids = set(self.env['succession.candidate'].search([
            ('critical_position_id', '=', self.id),
            ('active', '=', True),
            ('state', 'in', ['draft', 'nominated', 'assessed', 'approved', 'placed']),
        ]).mapped('employee_id.id'))

        # Existing nominated invitations for this critical position
        existing_nominated_inv_emp_ids = set(self.env['succession.candidate.invitation'].search([
            ('critical_position_id', '=', self.id),
            ('state', '=', 'nominated'),
        ]).mapped('employee_id.id'))

        all_nominated_emp_ids = existing_candidate_emp_ids | existing_nominated_inv_emp_ids

        # Existing invitations for this critical position
        existing_invitations = {
            inv.employee_id.id: inv for inv in self.env['succession.candidate.invitation'].search([
                ('critical_position_id', '=', self.id)
            ])
        }

        today = fields.Date.today()

        # ── 1. Eligible Positions (Strictly from hr.job Recruitment Module) ──
        target_eligible_job_ids = set()
        if hasattr(target_job, 'position_id') and target_job.position_id:
            target_eligible_job_ids = set(target_job.position_id.filtered(lambda p: p.status and p.position).mapped('position.id'))

        # ── 2. Eligible Grades (Strictly from hr.job Recruitment Module) ────
        target_eligible_grade_ids = set()
        if hasattr(target_job, 'grade_recruitment_id') and target_job.grade_recruitment_id:
            for el in target_job.grade_recruitment_id:
                if el.status and el.job_grade:
                    target_eligible_grade_ids.add(el.job_grade.id)

        target_grade = self.required_grade_id or target_job.required_grade_id or target_job.grade

        # ── 3. HR Policies from hr.job ──────────────────────────────────────
        target_min_company_years = getattr(target_job, 'minimum_number_years_in_company', 0) or 0
        target_min_loc_exp = getattr(target_job, 'current_location_exp', 0.0) or 0.0
        target_min_promo_months = getattr(target_job, 'no_of_months_since_last_promotion', 0) or 0
        target_min_pms = getattr(target_job, 'minimum_pms_score', 0.0) or 0.0
        written_notice_months = getattr(target_job, 'no_of_months_since_last_written_notice', 0) or 0
        allow_demoted = getattr(target_job, 'demoted_employee', False)
        allow_revoked = getattr(target_job, 'promotion_revoked', True)

        # ── 4. Experience Criteria from hr.job ──────────────────────────────
        # ── 4. Experience Criteria from hr.job (Experience tab: Requirement column) ──
        target_req_exps = {}  # exp_id -> required years
        target_sup_exp = 0.0
        target_line_max_exp = 0.0
        if hasattr(target_job, 'experiance_id') and target_job.experiance_id:
            for ex in target_job.experiance_id:
                # Strictly take the numerical value typed in the 'Requirement' column
                req_val = float(ex.requirement or 0.0)
                ex_label = ''
                if ex.experience:
                    target_req_exps[ex.experience.id] = req_val
                    ex_label = (getattr(ex.experience, 'display_name', '') or getattr(ex.experience, 'experience', '') or '').lower()
                    if 'supervis' in ex_label:
                        target_sup_exp = max(target_sup_exp, req_val)
                if req_val > 0:
                    target_line_max_exp = max(target_line_max_exp, req_val)

        target_exp_years = max(
            getattr(target_job, 'required_experience_years', 0.0) or 0.0,
            target_line_max_exp,
            max(target_req_exps.values()) if target_req_exps else 0.0
        )
        # ── 4b. Education Qualification Criteria from hr.job (Education Qualification tab) ──
        target_edu_reqs = []
        if hasattr(target_job, 'qualification_id') and target_job.qualification_id:
            for q in target_job.qualification_id:
                if q.qualification:
                    q_name = (getattr(q.qualification, 'qualification', '') or getattr(q.qualification, 'display_name', '') or '').strip()
                    if q_name:
                        target_edu_reqs.append({
                            'id': q.qualification.id,
                            'name': q_name,
                            'min_cgpa': float(q.requirement or 0.0),
                        })

        # ── 5. Scoring Weights (40% Grade, 30% Position, 30% Experience & Tenure) ──
        w_grade, w_position, w_tenure = 40.0, 30.0, 30.0

        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'bunna_succession_management.succ_auto_match_min_score', 0.0))

        # ── 6. INSTANT SQL-LEVEL CANDIDATE POOL FILTERING ──
        # Filter candidate pool directly at PostgreSQL level using indexed fields:
        # 1) Must hold one of the eligible positions defined in Recruitment.
        # 2) Must hold exact eligible grade defined in Recruitment.
        # 3) Must not be already nominated or the current occupant of this role.
        emp_domain = [('active', '=', True)]

        if all_nominated_emp_ids:
            emp_domain.append(('id', 'not in', list(all_nominated_emp_ids)))

        emp_domain.append(('job_id', '!=', target_job.id))

        # CRITICAL: If no feeder positions AND no eligible grades are configured on the job,
        # return an empty list rather than dumping all employees (which is meaningless
        # and misleading). The position admin MUST configure recruitment criteria first.
        has_position_criteria = bool(target_eligible_job_ids)
        has_grade_criteria = bool(target_eligible_grade_ids) or bool(target_grade)

        if not has_position_criteria and not has_grade_criteria:
            # No recruitment criteria configured at all - return empty to signal misconfiguration
            return []

        if target_eligible_job_ids:
            emp_domain.append(('job_id', 'in', list(target_eligible_job_ids)))

        if target_eligible_grade_ids:
            emp_domain.extend(['|', ('job_grade', 'in', list(target_eligible_grade_ids)), ('grade_id', 'in', list(target_eligible_grade_ids))])
        elif target_grade:
            emp_domain.extend(['|', ('job_grade', '=', target_grade.id), ('grade_id', '=', target_grade.id)])

        employees = self.env['hr.employee'].sudo().search(emp_domain)
        if not employees:
            return []

        cand_ids = employees.ids

        # ── 7. HIGH-PERFORMANCE BATCH PRE-FETCHING (Zero N+1 Queries) ──
        demoted_emp_ids = set()
        if not allow_demoted and 'employee.demotion' in self.env:
            try:
                demoted_emp_ids = set(self.env['employee.demotion'].sudo().search([
                    ('employee_name', 'in', cand_ids),
                    ('state', '=', 'approve'),
                    '|', ('demoted_until', '=', False), ('demoted_until', '>=', today),
                ]).mapped('employee_name.id'))
            except Exception:
                pass

        active_discipline_emp_ids = set()
        if 'discipline.case' in self.env:
            try:
                active_discipline_emp_ids |= set(self.env['discipline.case'].sudo().search([
                    ('employee_id', 'in', cand_ids),
                    ('state', 'not in', ['revoked', 'closed']),
                ]).mapped('employee_id.id'))
            except Exception:
                pass
        if 'discipline.action' in self.env:
            try:
                active_discipline_emp_ids |= set(self.env['discipline.action'].sudo().search([
                    ('employee_name', 'in', cand_ids),
                ]).mapped('employee_name.id'))
            except Exception:
                pass
        if 'disciplinary.action' in self.env:
            try:
                active_discipline_emp_ids |= set(self.env['disciplinary.action'].sudo().search([
                    ('employee_name', 'in', cand_ids),
                ]).mapped('employee_name.id'))
            except Exception:
                pass

        pms_scores_map = {}
        for emp in employees:
            if getattr(emp, 'pms_score', False):
                pms_scores_map[emp.id] = float(emp.pms_score)
            elif hasattr(emp, 'contract_id') and emp.contract_id and getattr(emp.contract_id, 'pms_score', False):
                pms_scores_map[emp.id] = float(emp.contract_id.pms_score)

        missing_pms_emp_ids = [e.id for e in employees if e.id not in pms_scores_map]
        if missing_pms_emp_ids and 'hr.pms.result' in self.env:
            try:
                pms_records = self.env['hr.pms.result'].sudo().search([
                    ('employee_id', 'in', missing_pms_emp_ids),
                    ('state', 'in', ['done', 'approved', 'confirmed']),
                ], order='date desc, id desc')
                for pr in pms_records:
                    if pr.employee_id.id not in pms_scores_map and getattr(pr, 'final_score', False):
                        pms_scores_map[pr.employee_id.id] = float(pr.final_score)
            except Exception:
                pass

        last_promo_months_map = {}
        if 'hr.job.history' in self.env:
            try:
                job_histories = self.env['hr.job.history'].sudo().search([
                    ('employee_id', 'in', cand_ids),
                    ('reason_for_movement', 'in', ['promotion', 'lateral_transfer']),
                ], order='job_history_start_date desc')
                for jh in job_histories:
                    eid = jh.employee_id.id
                    if eid not in last_promo_months_map and jh.job_history_start_date:
                        last_promo_months_map[eid] = round((today - jh.job_history_start_date).days / 30.4375, 1)
            except Exception:
                pass

        loc_exp_map = {}
        for emp in employees:
            if getattr(emp, 'current_location_exp', False):
                loc_exp_map[emp.id] = float(emp.current_location_exp)

        missing_loc_emp_ids = [e.id for e in employees if e.id not in loc_exp_map]
        if missing_loc_emp_ids and 'hr.employee.transfer.history' in self.env:
            try:
                transfers = self.env['hr.employee.transfer.history'].sudo().search([
                    ('employee_id', 'in', missing_loc_emp_ids),
                ], order='is_current desc, start_date desc, date desc, id desc')
                for t in transfers:
                    eid = t.employee_id.id
                    if eid not in loc_exp_map:
                        ou_id = t.employee_id.default_operating_unit_id.id if getattr(t.employee_id, 'default_operating_unit_id', False) else False
                        if ou_id and t.to_operating_unit_id and t.to_operating_unit_id.id == ou_id:
                            t_date = t.start_date or t.date
                            if t_date:
                                loc_exp_map[eid] = round((today - t_date).days / 365.25, 2)
            except Exception:
                pass

        # Batch prefetch One2many relations to avoid N+1 queries in the evaluation loop
        for rel_name in ('previous_occupation_ids', 'experiance_id', 'qualification_id', 'education_detail_ids', 'edu_ids'):
            if hasattr(self.env['hr.employee'].sudo(), rel_name):
                try:
                    employees.mapped(rel_name)
                except Exception:
                    pass

        match_lines_data = []

        for employee in employees:
            emp_job = employee.job_id or getattr(employee, 'job_position', False)
            emp_job_id = emp_job.id if emp_job else None

            emp_grade = employee.job_grade or getattr(employee, 'grade_id', False)
            if not emp_grade:
                continue

            # 5. Minimum Company Tenure Knockout (Recruitment Module Policy)
            hire_date = (
                getattr(employee, 'service_start_date', False)
                or getattr(employee, 'service_hire_date', False)
                or getattr(employee, 'first_contract_date', False)
                or getattr(employee, 'joining_date', False)
            )
            emp_service_years = round((today - hire_date).days / 365.25, 2) if hire_date else 0.0
            if not emp_service_years and getattr(employee, 'service_duration_years', False):
                emp_service_years = float(employee.service_duration_years)

            if target_min_company_years > 0 and emp_service_years < target_min_company_years:
                continue

            # 6. Current Location Experience Knockout (Recruitment Module Policy)
            emp_loc_years = loc_exp_map.get(employee.id)
            if emp_loc_years is None:
                emp_loc_years = emp_service_years
            if target_min_loc_exp > 0 and emp_loc_years < target_min_loc_exp:
                continue

            # 7. Promotion Timing Knockout (Recruitment Module Policy)
            last_promotion_months = last_promo_months_map.get(employee.id)
            if last_promotion_months is None:
                pos_date = hire_date
                last_promotion_months = round((today - pos_date).days / 30.4375, 1) if pos_date else 0.0
            if target_min_promo_months > 0 and last_promotion_months < target_min_promo_months:
                continue

            # 8. Minimum PMS Score Knockout (Recruitment Module Policy)
            emp_pms = pms_scores_map.get(employee.id, 0.0)
            if target_min_pms > 5.0 and 0.0 < emp_pms <= 5.0:
                emp_pms = round((emp_pms / 5.0) * 100.0, 2)
            elif target_min_pms <= 5.0 and target_min_pms > 0.0 and emp_pms > 5.0:
                emp_pms = round((emp_pms / 100.0) * 5.0, 2)
            if target_min_pms > 0 and emp_pms < target_min_pms:
                continue

            # 9. Experience Knockout (Total Experience & Supervisory Experience)
            prev_years = 0.0
            if hasattr(employee, 'previous_occupation_ids') and employee.previous_occupation_ids:
                for occ in employee.previous_occupation_ids:
                    if occ.from_date and occ.to_date and occ.to_date > occ.from_date:
                        prev_years += (occ.to_date - occ.from_date).days / 365.25
            prev_years = round(prev_years, 2)
            emp_total_exp = round(emp_service_years + prev_years, 2)

            if target_exp_years > 0 and emp_total_exp < target_exp_years:
                continue

            if target_sup_exp > 0:
                emp_sup_exp = 0.0
                if hasattr(employee, 'experiance_id') and employee.experiance_id:
                    for ex in employee.experiance_id:
                        ex_label = (getattr(ex.experience, 'display_name', '') or getattr(ex.experience, 'experience', '') or '').lower()
                        if 'supervis' in ex_label:
                            emp_sup_exp = max(emp_sup_exp, ex.requirement or 0.0, ex.response or 0.0)
                if not emp_sup_exp and hasattr(employee, 'previous_occupation_ids') and employee.previous_occupation_ids:
                    for occ in employee.previous_occupation_ids:
                        occ_title = (getattr(occ, 'position', '') or getattr(occ, 'role', '') or '').lower()
                        if any(kw in occ_title for kw in ['supervis', 'manager', 'lead', 'head', 'director']):
                            if occ.from_date and occ.to_date and occ.to_date > occ.from_date:
                                emp_sup_exp += (occ.to_date - occ.from_date).days / 365.25
                if emp_sup_exp < target_sup_exp:
                    continue

            # 10. Disciplinary & Demotion Knockouts (Pre-fetched in batch!)
            if employee.id in demoted_emp_ids:
                continue
            if getattr(employee, 'demoted_until', False) and employee.demoted_until > today:
                continue
            if hasattr(employee, 'is_eligible_for_promotion') and employee.is_eligible_for_promotion is False:
                continue
            if not allow_revoked and getattr(employee, 'promotion_revoked', False):
                continue

            # Written warning check
            if written_notice_months > 0:
                if hasattr(employee, 'months_since_last_written_notice') and employee.months_since_last_written_notice and employee.months_since_last_written_notice < written_notice_months:
                    continue

            # Active disciplinary cases check
            if employee.id in active_discipline_emp_ids:
                continue

            # 11. Education Qualification Knockout (Recruitment Module Criteria)
            # Candidate MUST meet at least one required qualification configured on the job and CGPA threshold
            is_edu_matched = True
            edu_matched_name = ''
            cand_cgpa = 0.0
            if target_edu_reqs:
                is_edu_matched, edu_matched_name, cand_cgpa, _edu_fail = self._check_employee_education_match(employee, target_edu_reqs)
                if not is_edu_matched:
                    continue

            # ── 11. Scoring Qualified Candidates ───
            emp_id = employee.id
            is_already_nominated = emp_id in existing_candidate_emp_ids
            emp_grade_name = emp_grade.grade_code if emp_grade and getattr(emp_grade, 'grade_code', False) else (emp_grade.display_name if emp_grade else '')

            # (A) Grade Points (Exact match gets full grade weight)
            grade_pts = w_grade
            grade_match_desc = _('Exact Eligible Grade (%s)') % emp_grade_name

            # (B) Position Eligibility Points
            career_pts = w_position
            career_proximity = 'eligible_position'
            title_match_desc = _('Eligible Feeder Position (%s)') % (emp_job.name if emp_job else '')

            # (C) Experience & Company Tenure Points
            if target_exp_years > 0:
                exp_ratio = min(1.2, emp_total_exp / target_exp_years)
                tenure_pts = round(min(w_tenure, w_tenure * (exp_ratio / 1.0)), 1)
                exp_detail_str = _('Exp: %.1f/%.1f yrs') % (emp_total_exp, target_exp_years)
            elif target_min_company_years > 0:
                exp_ratio = min(1.2, emp_service_years / target_min_company_years)
                tenure_pts = round(min(w_tenure, w_tenure * (exp_ratio / 1.0)), 1)
                exp_detail_str = _('Tenure: %.1f/%.1f yrs') % (emp_service_years, target_min_company_years)
            else:
                tenure_pts = w_tenure
                exp_detail_str = _('Tenure: %.1f yrs') % emp_service_years

            edu_pts = 0.0
            criteria_match_desc = f"{grade_match_desc} | {title_match_desc} | {exp_detail_str}"
            composite_score = round(grade_pts + career_pts + tenure_pts, 1)
            if composite_score > 100.0:
                composite_score = 100.0

            if threshold and composite_score < threshold:
                continue

            # Educational qualification display (reflecting recruitment match)
            if target_edu_reqs and is_edu_matched and edu_matched_name:
                qual_summary = edu_matched_name
                qualification_desc = f"{edu_matched_name} (CGPA: {cand_cgpa:.2f})" if cand_cgpa > 0 else edu_matched_name
            else:
                emp_qual_names = set()
                emp_cgpa = 0.0
                if hasattr(employee, 'qualification_id') and employee.qualification_id:
                    for q in employee.qualification_id:
                        if q.qualification:
                            name = getattr(q.qualification, 'display_name', '') or getattr(q.qualification, 'qualification', '') or getattr(q.qualification, 'name', '')
                            if name:
                                emp_qual_names.add(name.strip().lower())
                            if q.requirement:
                                emp_cgpa = max(emp_cgpa, q.requirement)
                            if q.response:
                                emp_cgpa = max(emp_cgpa, q.response)

                if hasattr(employee, 'education_detail_ids') and employee.education_detail_ids:
                    for edu in employee.education_detail_ids:
                        q_name = getattr(edu, 'qualification', '') or ''
                        if q_name:
                            emp_qual_names.add(q_name.strip().lower())
                        if hasattr(edu, 'cgpa_percentage') and edu.cgpa_percentage:
                            emp_cgpa = max(emp_cgpa, edu.cgpa_percentage)
                        elif hasattr(edu, 'CGPA') and edu.CGPA:
                            emp_cgpa = max(emp_cgpa, edu.CGPA)

                if hasattr(employee, 'edu_ids') and employee.edu_ids:
                    for edu in employee.edu_ids:
                        if edu.qualification:
                            emp_qual_names.add(edu.qualification.strip().lower())

                qual_summary = ', '.join([q.title() for q in sorted(emp_qual_names)[:2]]) if emp_qual_names else ''
                if not qual_summary and hasattr(employee, 'education_detail_ids') and employee.education_detail_ids:
                    quals = [getattr(e, 'qualification', '') or '' for e in employee.education_detail_ids if getattr(e, 'qualification', '')]
                    if quals:
                        qual_summary = ', '.join(quals[:2])
                if not qual_summary:
                    qual_summary = 'None'

                if emp_cgpa > 0:
                    qualification_desc = f"{qual_summary} (CGPA: {emp_cgpa:.2f})"
                else:
                    qualification_desc = qual_summary

            # Location and Department
            curr_loc = employee.default_operating_unit_id.name if employee.default_operating_unit_id else (
                employee.department_id.operating_unit_id.name if getattr(employee.department_id, 'operating_unit_id', False) else ''
            )
            curr_dept = employee.department_id.name if employee.department_id else ''

            inv = existing_invitations.get(emp_id)
            inv_id = inv.id if inv else False
            policy = self.env['succession.governance.policy'].get_policy()
            expiry_days = policy.invitation_expiry_days or 3
            default_deadline = today + timedelta(days=expiry_days)

            if is_already_nominated:
                inv_status = 'already_in_pipeline'
            elif inv:
                if inv.state == 'invited' and inv.deadline_date and inv.deadline_date < today:
                    inv_status = 'expired'
                else:
                    inv_status = inv.state
            else:
                inv_status = 'none'

            if inv and inv.deadline_date:
                acceptance_end_date = inv.deadline_date
            else:
                acceptance_end_date = default_deadline

            relevant_exp = emp_total_exp

            match_lines_data.append({
                'employee_id': emp_id,
                'is_selected': False,
                'acceptance_end_date': acceptance_end_date,
                'app_date': acceptance_end_date,
                'grade_name': emp_grade_name,
                'job_title': employee.job_id.name or employee.job_title or (emp_job.name if emp_job else ''),
                'category': emp_job.employee_category if emp_job and hasattr(emp_job, 'employee_category') else (getattr(employee, 'job_category', '') or 'Non Managerial'),
                'employment_type': emp_job.type_of_employment if emp_job and hasattr(emp_job, 'type_of_employment') else (getattr(employee, 'type_of_employment', '') or 'Permanent'),
                'gender': employee.gender or '',
                'current_location': curr_loc or '',
                'current_department': curr_dept or '',
                'educational_qualification': qual_summary,
                'service_in_company': emp_service_years,
                'relevant_experience': relevant_exp,
                'employment_experience': prev_years,
                'total_experience': emp_total_exp,
                'latest_pms_score': emp_pms,

                # Succession Workflow & Tracking
                'invitation_id': inv_id,
                'invitation_status': inv_status,
                'already_nominated': is_already_nominated,
                'last_promotion_months': last_promotion_months,
                'qualification_desc': qualification_desc,
                'eligibility_status': _('Eligible - Meets Promotion Criteria'),
                'career_proximity': career_proximity,
                'grade_match_desc': grade_match_desc,
                'title_match_desc': title_match_desc,
                'criteria_match_desc': criteria_match_desc,
                'composite_score': composite_score,
                'grade_pts': round(grade_pts, 1),
                'career_pts': round(career_pts, 1),
                'tenure_pts': round(tenure_pts, 1),
                'edu_pts': round(edu_pts, 1),

                # Aliases for compatibility
                'job_id': emp_job_id,
                'tenure_years': emp_service_years,
                'total_exp_years': emp_total_exp,
            })

        # Sort by composite score descending, then service in company descending
        match_lines_data.sort(key=lambda x: (x['composite_score'], x['service_in_company']), reverse=True)
        return match_lines_data[:150]

    def action_auto_match_candidates(self):
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_(
                'Auto-Match cannot be run! Critical Position "%s" is not approved yet (Status: %s). '
                'Only officially approved critical positions can have candidates auto-matched.'
            ) % (self.display_name, self.state))
        if not self.job_id:
            raise ValidationError(_('Please configure a valid Job Position for this Critical Position first.'))

        wizard = self.env['succession.candidate.nomination.wizard'].sudo().create({
            'critical_position_id': self.id,
        })
        wizard._onchange_critical_position_id()

        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto-Match Initialized'),
                'message': _('Auto-Match candidates wizard opened successfully for "%s".') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'name': _('Auto-Match Candidates - Recruitment Criteria'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'succession.candidate.nomination.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                    'context': {
                        'default_critical_position_id': self.id,
                        'active_model': 'succession.candidate.nomination.wizard',
                        'succession_sudo_search': True,
                        'succession_employee_select': True,
                        'dialog_size': 'extra-large',
                    },
                },
            }
        }


    def action_open_new_candidate_form(self):

        self.ensure_one()

        return {

            'name': _('Nominate Candidate'),

            'type': 'ir.actions.act_window',

            'res_model': 'succession.candidate',

            'view_mode': 'form',

            'views': [(False, 'form')],

            'context': {'default_critical_position_id': self.id},

            'target': 'current',

        }



    def action_deactivate(self):

        for rec in self:

            rec.with_context(force_write=True).write({'state': 'deactivated'})

            rec._log_governance('deactivated', 'Position Deactivated')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Position Deactivated'),
                'message': _('Critical Position "%s" has been deactivated.') % self.display_name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }



    def action_view_candidates(self):
        self.ensure_one()
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Succession Candidates'),
                'message': _('Opening candidates pipeline for "%s"...') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Candidates - %s') % pos_name,
                    'res_model': 'succession.candidate',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'domain': [('critical_position_id', '=', self.id)],
                    'context': {'default_critical_position_id': self.id},
                },
            }
        }



    def action_view_ready_now(self):
        self.ensure_one()
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ready Now Candidates'),
                'message': _('Opening Ready Now candidates for "%s"...') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Ready Now - %s') % pos_name,
                    'res_model': 'succession.candidate',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'domain': [('critical_position_id', '=', self.id),
                               ('readiness_level_id.is_ready_for_deployment', '=', True)],
                },
            }
        }

    def action_view_ready_soon(self):
        self.ensure_one()
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ready Soon (1-2 Yrs) Candidates'),
                'message': _('Opening Ready in 1-2 Years candidates for "%s"...') % pos_name,
                'type': 'info',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Ready Soon (1-2 Yrs) - %s') % pos_name,
                    'res_model': 'succession.candidate',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'domain': [
                        ('critical_position_id', '=', self.id),
                        ('readiness_level_id.is_ready_for_deployment', '=', False),
                        '|', ('readiness_level_id.name', 'ilike', '1-2'),
                        ('readiness_level_id.sequence', '=', 20),
                    ],
                },
            }
        }



    def _log_governance(self, action, comment):
        action_field = self.env['succession.governance.log']._fields.get('action')
        valid_actions = dict(action_field.selection or []) if action_field else {}
        log_action = action
        if action not in valid_actions:
            if action == 'assessment_completed':
                log_action = 'candidate_assessed' if 'candidate_assessed' in valid_actions else 'note'
            else:
                log_action = 'note'
        self.env['succession.governance.log'].sudo().create({
            'critical_position_id': self.id,
            'action': log_action,
            'comment': comment,
            'user_id': self.env.user.id,
        })



    def write(self, vals):

        force_write = self.env.context.get('force_write')

        for rec in self:

            if rec.state in ('approved', 'placed') and not force_write and not self.env.su:

                locked = {'job_id', 'department_id', 'risk_level_id'}

                if set(vals.keys()) & locked:

                    raise ValidationError(

                        _("Critical position '%s' is SPMC-approved and cannot be structurally modified. "

                          "Please deactivate and create a new record.") % rec.display_name)

        return super().write(vals)



    @api.model

    def _cron_check_critical_position_reviews(self):

        """

        FR-SWP-004: Periodically review critical positions and generate reminders.

        """

        from datetime import timedelta

        target_date = fields.Date.today() + timedelta(days=30)

        positions = self.search([

            ('state', '=', 'approved'),

            ('next_review_date', '<=', target_date)

        ])

        for pos in positions:

            # check if an activity already exists to avoid duplicates

            existing = self.env['mail.activity'].sudo().search([

                ('res_id', '=', pos.id),

                ('res_model_id', '=', self.env['ir.model'].sudo()._get_id('succession.critical.position')),

                ('summary', '=', 'Critical Position Review Due')

            ])

            if not existing:

                pos.activity_schedule(

                    'mail.mail_activity_data_todo',

                    user_id=pos.spmc_approved_by_id.id or self.env.ref('base.user_admin').id,

                    date_deadline=pos.next_review_date,

                    summary='Critical Position Review Due',

                    note='Please review and validate this critical position and its successor requirements.'

                )



    @api.model

    def _cron_succession_risk_alert(self):

        """

        FR-NOT-006: Weekly alert to PPDD when a critical position has

        insufficient successors (zero Ready Now candidates).

        """

        ppdd_group = self.env.ref(

            'bunna_succession_management.group_succession_ppdd',

            raise_if_not_found=False)

        if not ppdd_group:

            return



        positions = self.search([('state', '=', 'approved')])

        for pos in positions:

            ready_now = self.env['succession.candidate'].search_count([

                ('critical_position_id', '=', pos.id),

                ('readiness_level_id.is_ready_for_deployment', '=', True),

                ('state', 'in', ['assessed', 'approved']),

            ])

            if ready_now == 0:

                # Send alert activity to all PPDD users

                for user in ppdd_group.user_ids:

                    existing = self.env['mail.activity'].sudo().search([

                        ('res_id', '=', pos.id),

                        ('res_model_id', '=', self.env['ir.model'].sudo()._get_id(

                            'succession.critical.position')),

                        ('user_id', '=', user.id),

                        ('summary', 'ilike', 'No Ready-Now Successor'),

                    ], limit=1)

                    if not existing:

                        pos.activity_schedule(

                            'mail.mail_activity_data_todo',

                            user_id=user.id,

                            summary='Ã¢Å¡Â Ã¯Â¸Â No Ready-Now Successor: %s' % pos.display_name,

                            note=_(

                                'SUCCESSION RISK ALERT: The critical position "%s" currently '

                                'has NO approved "Ready Now" successors. Immediate action is '

                                'required to identify, assess, and develop suitable candidates.'

                            ) % pos.display_name,

                        )





    @api.model

    def get_dashboard_data(self):

        # 1. Critical Positions Data

        positions = self.search([('state', 'in', ['approved'])])

        critical_positions_count = len(positions)

        high_risk_count = len(positions.filtered(lambda p: p.succession_risk in ('high', 'critical')))

        

        # 2. Candidate Data
        candidates = self.env['succession.candidate'].search([('state', 'in', ['assessed', 'approved'])])
        total_candidates = len(candidates)

        # Dynamic Readiness Pipeline from Configuration (succession.readiness.level)
        readiness_levels = self.env['succession.readiness.level'].search([('active', '=', True)], order='sequence asc, id asc')

        pipeline_labels = []
        pipeline_data = []
        pipeline_colors = []
        pipeline_levels = []

        default_palette = ['#17a2b8', '#ffc107', '#fd7e14', '#6f42c1', '#20c997', '#007bff']
        non_ready_idx = 0

        for lvl in readiness_levels:
            count = self.env['succession.candidate'].search_count([
                ('state', 'in', ['assessed', 'approved']),
                ('readiness_level_id', '=', lvl.id),
            ])
            pipeline_labels.append(lvl.name)
            pipeline_data.append(count)
            if lvl.is_ready_for_deployment:
                pipeline_colors.append('#28a745')
            else:
                pipeline_colors.append(default_palette[non_ready_idx % len(default_palette)])
                non_ready_idx += 1
            pipeline_levels.append({
                'id': lvl.id,
                'name': lvl.name,
                'count': count,
                'is_ready_for_deployment': lvl.is_ready_for_deployment,
            })

        if not readiness_levels:
            pipeline_labels = ['Ready Now', 'Ready Soon', 'Ready Later']
            pipeline_data = [0, 0, 0]
            pipeline_colors = ['#28a745', '#17a2b8', '#ffc107']

        ready_now_count = self.env['succession.candidate'].search_count([
            ('state', 'in', ['assessed', 'approved']),
            ('readiness_level_id.is_ready_for_deployment', '=', True),
        ])
        ready_soon_count = pipeline_data[1] if len(pipeline_data) > 1 else 0
        ready_later_count = pipeline_data[2] if len(pipeline_data) > 2 else 0

        # Calculate percentages
        ready_now_percent = int((ready_now_count / total_candidates * 100)) if total_candidates else 0
        ready_soon_percent = int((ready_soon_count / total_candidates * 100)) if total_candidates else 0
        ready_later_percent = int((ready_later_count / total_candidates * 100)) if total_candidates else 0

        # 3. High Risk Critical Positions List (Enriched for dashboard card)
        critical_list = []
        for pos in positions.filtered(lambda p: p.succession_risk in ('high', 'critical', 'medium')):
            critical_list.append({
                'id': pos.id,
                'name': pos.display_name,
                'department': pos.department_id.name or 'General',
                'work_unit': pos.work_unit_id.name or '',
                'risk': pos.succession_risk or 'medium',
                'bench_strength': pos.candidate_count,
                'target': pos.min_successor_count or 1,
            })
        risk_order = {'critical': 0, 'high': 1, 'medium': 2}
        critical_list.sort(key=lambda x: risk_order.get(x['risk'], 9))

        # 4. New Models Data
        active_dev_plans = self.env['succession.development.plan'].search_count([('state', 'in', ('active', 'extended', 'extension_pending'))])
        recent_discussions = self.env['succession.career.discussion'].search_count([])

        # 5. Career Pathing Data (optional models — may live in a separate module)
        total_aspirations = 0
        total_idps = 0
        if 'hr.career.aspiration' in self.env:
            try:
                total_aspirations = self.env['hr.career.aspiration'].sudo().search_count([])
            except Exception:
                total_aspirations = 0
        if 'hr.career.idp' in self.env:
            try:
                total_idps = self.env['hr.career.idp'].sudo().search_count([])
            except Exception:
                total_idps = 0

        # 6. Assessment Sessions Data (new structured assessment engine)
        total_sessions = 0
        validated_sessions = 0
        calibration_pending = 0
        if 'succession.assessment.session' in self.env:
            try:
                total_sessions = self.env['succession.assessment.session'].search_count(
                    [('state', '!=', 'cancelled')])
                validated_sessions = self.env['succession.assessment.session'].search_count(
                    [('state', '=', 'validated')])
                calibration_pending = self.env['succession.assessment.session'].search_count([
                    ('calibration_required', '=', True),
                    ('calibration_notes', '=', False),
                    ('state', 'in', ['completed', 'validated']),
                ])
            except Exception:
                pass

        return {
            'critical_positions_count': critical_positions_count,
            'high_risk_count': high_risk_count,
            'total_candidates': total_candidates,
            'ready_now_count': ready_now_count,
            'ready_soon_count': ready_soon_count,
            'ready_later_count': ready_later_count,
            'ready_now_percent': ready_now_percent,
            'ready_soon_percent': ready_soon_percent,
            'ready_later_percent': ready_later_percent,
            'readiness_pipeline': {
                'labels': pipeline_labels,
                'data': pipeline_data,
                'colors': pipeline_colors,
                'levels': pipeline_levels,
            },
            'critical_list': critical_list,
            'active_dev_plans_count': active_dev_plans,
            'recent_discussions_count': recent_discussions,
            'total_aspirations_count': total_aspirations,
            'total_idps_count': total_idps,
            'total_sessions_count': total_sessions,
            'validated_sessions_count': validated_sessions,
            'calibration_pending_count': calibration_pending,
        }


    @api.model
    def get_reports_hub_data(self):
        """Executive Reporting Hub dataset for By Job Position, Assessment, and Readiness horizons."""
        positions = self.search([('state', 'in', ['approved', 'placed'])], order='create_date desc, id desc')
        candidates = self.env['succession.candidate'].search([('state', 'in', ['assessed', 'approved', 'placed'])], order='create_date desc, id desc')

        # 1. Summary KPIs
        total_positions = len(positions)
        covered_positions = len(positions.filtered(lambda p: p.candidate_count >= (p.min_successor_count or 1)))
        uncovered_positions = len(positions.filtered(lambda p: p.candidate_count == 0))
        overall_bench_percent = int((covered_positions / total_positions * 100)) if total_positions else 0

        total_assessed = len(candidates)
        passed_candidates = candidates.filtered(lambda c: c.assessment_result == 'pass')
        failed_candidates = candidates.filtered(lambda c: c.assessment_result == 'fail')
        pass_rate = int((len(passed_candidates) / total_assessed * 100)) if total_assessed else 0

        ready_now_count = len(candidates.filtered(lambda c: c.readiness_level_id.is_ready_for_deployment))
        ready_soon_count = len(candidates.filtered(lambda c: c.readiness_level_id and '1-2' in c.readiness_level_id.name))
        ready_future_count = total_assessed - (ready_now_count + ready_soon_count)
        if ready_future_count < 0:
            ready_future_count = 0

        # 2. Job Position Coverage List
        job_list = []
        departments = set()
        for pos in positions:
            dept_name = pos.department_id.name or 'General'
            departments.add(dept_name)
            target = pos.min_successor_count or 1
            nominees = pos.candidate_count
            if nominees >= target:
                coverage_status = 'covered'
            elif nominees > 0:
                coverage_status = 'partial'
            else:
                coverage_status = 'uncovered'

            job_list.append({
                'id': pos.id,
                'name': pos.display_name,
                'department': dept_name,
                'work_unit': pos.work_unit_id.name or '',
                'risk_level': pos.risk_level_id.name or 'Medium',
                'risk_code': pos.succession_risk or 'medium',
                'target_bench': target,
                'nominees': nominees,
                'ready_now': pos.ready_now_count,
                'ready_soon': pos.ready_soon_count,
                'ready_future': pos.ready_future_count,
                'bench_strength': pos.bench_strength or f"{nominees}/{target}",
                'coverage_status': coverage_status,
            })

        # 3. Assessment Diagnostics List
        cand_list = []
        for cand in candidates:
            dept_name = cand.department_id.name or 'General'
            departments.add(dept_name)
            cand_list.append({
                'id': cand.id,
                'name': cand.employee_id.name or 'Unknown',
                'target_position': cand.critical_position_id.display_name or 'N/A',
                'current_job': cand.job_id.name or 'N/A',
                'department': dept_name,
                'final_score': round(cand.final_assessment_score, 1),
                'result': cand.assessment_result or 'pending',
                'pms_score': round(cand.latest_pms_score, 2),
                'readiness': cand.readiness_level_id.name or 'Not Assigned',
                'state': cand.state,
            })

        # 4. Readiness Horizon Lists
        horizons = {
            'ready_now': [],
            'ready_soon': [],
            'ready_future': [],
        }
        for cand in candidates:
            item = {
                'id': cand.id,
                'name': cand.employee_id.name or 'Unknown',
                'target_position': cand.critical_position_id.display_name or 'N/A',
                'current_job': cand.job_id.name or 'N/A',
                'department': cand.department_id.name or 'General',
                'score': round(cand.final_assessment_score, 1),
                'result': cand.assessment_result or 'pending',
                'readiness': cand.readiness_level_id.name or 'Not Assigned',
            }
            if cand.readiness_level_id.is_ready_for_deployment:
                horizons['ready_now'].append(item)
            elif cand.readiness_level_id and '1-2' in cand.readiness_level_id.name:
                horizons['ready_soon'].append(item)
            else:
                horizons['ready_future'].append(item)

        return {
            'kpis': {
                'total_positions': total_positions,
                'covered_positions': covered_positions,
                'uncovered_positions': uncovered_positions,
                'overall_bench_percent': overall_bench_percent,
                'total_assessed': total_assessed,
                'passed_count': len(passed_candidates),
                'failed_count': len(failed_candidates),
                'pass_rate': pass_rate,
                'ready_now_count': ready_now_count,
                'ready_soon_count': ready_soon_count,
                'ready_future_count': ready_future_count,
            },
            'job_positions': job_list,
            'assessment_candidates': cand_list,
            'horizons': horizons,
            'departments': sorted(list(departments)),
        }


    # --- Position-Level Assessment Plan Methods & Computes ---

    @api.depends('assessment_line_ids.weight', 'assessment_line_ids.enabled', 'assessment_line_ids.not_applicable')
    def _compute_plan_total_weight(self):
        for rec in self:
            active_lines = rec.assessment_line_ids.filtered(lambda l: l.enabled and not l.not_applicable)
            rec.plan_total_weight = round(sum(active_lines.mapped('weight')), 2)

    @api.depends('plan_status')
    def _compute_plan_locked(self):
        for rec in self:
            rec.plan_locked = False

    @api.depends('plan_status', 'plan_last_synced_date', 'plan_last_synced_by_id',
                 'candidate_ids.state', 'candidate_ids.assessment_criteria_synced', 'candidate_ids.assessment_done')
    def _compute_plan_sync_status(self):
        for rec in self:
            nominees = rec.candidate_ids.filtered(lambda c: c.state == 'nominated' and not c.assessment_done)
            total_nominees = len(nominees)
            rec.nominated_candidate_count = total_nominees
            unsynced = nominees.filtered(lambda c: not c.assessment_criteria_synced)
            rec.unsynced_candidate_count = len(unsynced)

            if rec.plan_status == 'disabled':
                rec.plan_sync_status = 'disabled'
            elif rec.plan_status == 'draft':
                rec.plan_sync_status = 'draft'
            elif rec.plan_status == 'reopened':
                rec.plan_sync_status = 'reopened'
            elif total_nominees == 0:
                rec.plan_sync_status = 'no_candidates'
            elif unsynced:
                rec.plan_sync_status = 'pending'
            else:
                rec.plan_sync_status = 'synced'

    @api.depends('plan_sync_status', 'nominated_candidate_count', 'unsynced_candidate_count')
    def _compute_plan_sync_status_display(self):
        for rec in self:
            total_nominees = rec.nominated_candidate_count or 0
            unsynced_count = rec.unsynced_candidate_count or 0
            synced_count = total_nominees - unsynced_count

            if rec.plan_sync_status == 'disabled':
                rec.plan_sync_status_display = _("Assessment requirements disabled for this critical position.")
            elif rec.plan_sync_status == 'draft':
                rec.plan_sync_status_display = _("Assessment Plan is in draft. Lock the plan to activate and synchronize.")
            elif rec.plan_sync_status == 'no_candidates':
                rec.plan_sync_status_display = _("Assessment & Exam Plan is locked. No candidates currently nominated.")
            elif rec.plan_sync_status == 'pending':
                if synced_count > 0:
                    rec.plan_sync_status_display = _("%d of %d candidates synced (%d new nominee(s) awaiting sync).") % (
                        synced_count, total_nominees, unsynced_count)
                else:
                    rec.plan_sync_status_display = _("Synchronization required for %d nominated candidate(s).") % unsynced_count
            else:
                rec.plan_sync_status_display = _("All %d nominated candidate(s) fully synchronized.") % total_nominees

    def action_view_synced_candidates(self):
        """View all active nominated candidates for this critical position."""
        self.ensure_one()
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Synced Candidates'),
                'message': _('Opening nominated candidates for "%s"...') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Nominated Candidates - %s') % pos_name,
                    'res_model': 'succession.candidate',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'domain': [('critical_position_id', '=', self.id), ('state', '=', 'nominated')],
                    'context': {'default_critical_position_id': self.id},
                    'target': 'current',
                },
            }
        }

    @api.depends('plan_include_manager', 'plan_include_self', 'plan_include_spmc', 'spmc_assessor_ids')
    def _compute_formula_notice(self):
        for rec in self:
            evaluators = []
            if rec.plan_include_manager:
                evaluators.append('Manager')
            if rec.plan_include_self:
                evaluators.append('Self-Assessment')
            if rec.plan_include_spmc:
                if rec.spmc_assessor_ids:
                    names = ', '.join(rec.spmc_assessor_ids.mapped('name'))
                    evaluators.append(f'SPMC Committee ({len(rec.spmc_assessor_ids)} Assessors: {names})')
                else:
                    evaluators.append('SPMC Committee')
            if not evaluators:
                rec.competency_formula_notice = "Warning: Select at least one evaluator."
            elif len(evaluators) == 1:
                rec.competency_formula_notice = f"Evaluation Method: 100% {evaluators[0]} Score"
            else:
                pct = round(100.0 / len(evaluators), 1)
                rec.competency_formula_notice = f"Evaluation Method: Equal Average across {', '.join(evaluators)} ({pct}% each)"

    @api.onchange('assessment_scope')
    def _onchange_assessment_scope(self):
        scope = self.assessment_scope
        if not scope or scope == 'custom':
            return
        if scope == 'manager_only':
            self.plan_include_manager = True
            self.plan_include_self = False
            self.plan_include_spmc = False
        elif scope == 'manager_self':
            self.plan_include_manager = True
            self.plan_include_self = True
            self.plan_include_spmc = False
        elif scope == 'manager_spmc':
            self.plan_include_manager = True
            self.plan_include_self = False
            self.plan_include_spmc = True
        elif scope == 'full_360':
            self.plan_include_manager = True
            self.plan_include_self = True
            self.plan_include_spmc = True

    @api.onchange('plan_include_manager', 'plan_include_self', 'plan_include_spmc')
    def _onchange_evaluator_checkboxes(self):
        if self.plan_include_manager and not self.plan_include_self and not self.plan_include_spmc:
            new_scope = 'manager_only'
        elif self.plan_include_manager and self.plan_include_self and not self.plan_include_spmc:
            new_scope = 'manager_self'
        elif self.plan_include_manager and not self.plan_include_self and self.plan_include_spmc:
            new_scope = 'manager_spmc'
        elif self.plan_include_manager and self.plan_include_self and self.plan_include_spmc:
            new_scope = 'full_360'
        else:
            new_scope = 'custom'
        if self.assessment_scope != new_scope:
            self.assessment_scope = new_scope

    @api.constrains('plan_include_spmc', 'spmc_assessor_ids', 'plan_status')
    def _check_spmc_assessors_mandatory(self):
        for rec in self:
            if rec.plan_include_spmc and not rec.spmc_assessor_ids and rec.plan_status in ('active', 'locked'):
                raise ValidationError(_(
                    "Designated SPMC Committee Assessors Required!\n\n"
                    "SPMC Committee Evaluation is enabled for '%(pos)s', but no Designated SPMC Committee Assessors have been assigned.\n\n"
                    "Please assign at least one SPMC Committee Member under 'Designated SPMC Committee Assessors' before synchronizing the assessment plan.",
                    pos=rec.job_id.name if rec.job_id else rec.display_name,
                ))

    def _ensure_assessment_lines(self):
        """Ensure all active components from succession.assessment.config exist on the critical position."""
        cfg = self.env['succession.assessment.config'].get_config()
        components = cfg.component_ids.filtered(lambda c: c.enabled and c.active)
        for rec in self:
            existing_components = rec.assessment_line_ids.mapped('component_id')
            missing_components = components - existing_components
            vals = []
            for comp in missing_components:
                vals.append({
                    'critical_position_id': rec.id,
                    'component_id': comp.id,
                    'sequence': comp.sequence,
                    'weight': comp.weight,
                    'max_score': comp.max_score or 100.0,
                    'enabled': True,
                })
            if vals:
                self.env['succession.critical.position.assessment.line'].sudo().create(vals)
                rec.invalidate_recordset(['assessment_line_ids'])

    def action_open_assessment_plan(self, skip_notification=False):
        """Open the dedicated Assessment & Exam Plan dialog for this critical position."""
        self.ensure_one()
        self._ensure_assessment_lines()
        view = self.env.ref('bunna_succession_management.view_succession_critical_position_assessment_plan_dialog', raise_if_not_found=False)
        view_id = view.id if view else False
        act = {
            'name': _('Assessment & Exam Plan - %s') % (self.display_name or self.job_id.name or 'Position'),
            'type': 'ir.actions.act_window',
            'res_model': 'succession.critical.position',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'current',
            'context': dict(self.env.context, in_assessment_plan_dialog=True),
        }
        if skip_notification:
            return act
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan'),
                'message': _('Opening Assessment Plan configuration for "%s"...') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': act,
            }
        }

    def action_save_assessment_plan(self):
        """Save and close the Assessment & Exam Plan dialog."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Saved'),
                'message': _('Assessment Plan configuration has been saved successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_reset_assessment_lines(self):
        """Reload default components and weights from Global Assessment Configuration."""
        self.ensure_one()
        if self.plan_locked:
            raise UserError(_("The Assessment Plan is locked and cannot be reset. Please unlock to make revisions."))
        self.assessment_line_ids.unlink()
        self._ensure_assessment_lines()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Lines Reset'),
                'message': _('Assessment Plan components and weights have been successfully reset from configuration.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_auto_balance_weights(self):
        """Auto-balance weights so active components sum to 100%, zeroing N/A components."""
        self.ensure_one()
        if self.plan_locked:
            raise UserError(_("The Assessment Plan is locked and cannot be modified. Please unlock to make revisions."))
        self._ensure_assessment_lines()

        # Step 1: Zero out all Not Applicable (N/A) or disabled lines
        na_lines = self.assessment_line_ids.filtered(lambda l: l.not_applicable or not l.enabled)
        if na_lines:
            for l in na_lines:
                self.env.cr.execute(
                    "UPDATE succession_critical_position_assessment_line SET weight = 0.0, enabled = FALSE, not_applicable = TRUE WHERE id = %s",
                    (l.id,)
                )
            na_lines.invalidate_recordset(['weight', 'enabled', 'not_applicable'])

        # Step 2: Get active components
        active_lines = self.assessment_line_ids.filtered(lambda l: l.enabled and not l.not_applicable)
        if not active_lines:
            raise UserError(_("Cannot auto-balance: All assessment components are marked as Not Applicable. At least one component must be active."))

        comp_lines = active_lines.filtered(lambda l: l.component_source == 'competency_eval')
        other_active = active_lines.filtered(lambda l: l.component_source != 'competency_eval')
        other_w = round(sum(other_active.mapped('weight')), 2)

        # Step 3: Balance to 100%
        if comp_lines and other_w < 100.0:
            # Competency evaluation absorbs residual weight
            comp = comp_lines[0]
            comp.write({'weight': round(100.0 - other_w, 2)})
        else:
            # Proportional redistribution across all active components
            total_current = sum(active_lines.mapped('weight'))
            if total_current > 0.0:
                accum = 0.0
                lines_list = list(active_lines)
                for line in lines_list[:-1]:
                    w = round((line.weight / total_current) * 100.0, 2)
                    line.write({'weight': w})
                    accum += w
                lines_list[-1].write({'weight': round(100.0 - accum, 2)})
            else:
                # Equal distribution if all active are 0.0
                n = len(active_lines)
                w_each = round(100.0 / n, 2)
                lines_list = list(active_lines)
                for line in lines_list[:-1]:
                    line.write({'weight': w_each})
                lines_list[-1].write({'weight': round(100.0 - (w_each * (n - 1)), 2)})

        self._compute_plan_total_weight()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Weights Auto-Balanced'),
                'message': _('Assessment Plan weights successfully balanced to 100.0%%.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }

    def action_lock_assessment_plan(self):
        """Lock the position assessment plan once configuration and 100% balancing is verified."""
        self.ensure_one()
        self._ensure_assessment_lines()
        if abs(self.plan_total_weight - 100.0) > 0.01:
            raise UserError(_(
                "Cannot lock Assessment Plan: The total weight of enabled components is %.2f%%, "
                "but must equal exactly 100.0%%. Please click 'Auto-Balance 100%%' or adjust component weights."
            ) % self.plan_total_weight)
        if not (self.plan_include_manager or self.plan_include_self or self.plan_include_spmc):
            raise UserError(_("Cannot lock Assessment Plan: At least one evaluator (Manager, Self, or SPMC Committee) must be selected."))

        if self.plan_include_spmc and not self.spmc_assessor_ids:
            raise UserError(_(
                "Cannot Lock & Sync Assessment Plan: Designated SPMC Committee Assessors Required!\n\n"
                "SPMC Committee Evaluation is enabled for '%(pos)s', but no Designated SPMC Committee Assessors have been assigned.\n\n"
                "Please assign at least one SPMC Committee Member under 'Designated SPMC Committee Assessors' before synchronizing the assessment plan.",
                pos=self.job_id.name if self.job_id else self.display_name,
            ))

        enabled_lines = self.assessment_line_ids.filtered(lambda l: l.enabled)
        if not enabled_lines:
            raise UserError(_("Cannot lock Assessment Plan: At least one assessment component must be enabled."))

        active_cands = self.candidate_ids.filtered(lambda c: c.state == 'nominated' and not c.assessment_done)
        if not active_cands:
            raise UserError(_(
                "No nominated candidates for the position.\n\n"
                "Please nominate candidates for this position first before locking and syncing the assessment plan."
            ))

        self.write({
            'plan_status': 'active',
            'plan_locked_by_id': self.env.user.id,
            'plan_locked_date': fields.Datetime.now(),
        })
        self._log_governance(
            'criteria_synced',
            _("Assessment & Exam Plan confirmed and locked by %s. Total weight: %.2f%%.") % (
                self.env.user.name, self.plan_total_weight)
        )
        self.message_post(body=_(
            "🔒 <b>Assessment & Exam Plan Confirmed & Locked:</b> Assessment & Exam Plan finalized with %d enabled component(s) summing to 100%%."
        ) % len(enabled_lines))

        # AUTO-POPULATE: When plan is locked, immediately populate ALL nominated candidates
        now = fields.Datetime.now()
        user_id = self.env.user.id
        if active_cands:
            for cand in active_cands:
                cand.with_context(force_write=True).write({
                    'assessment_criteria_synced': True,
                    'assessment_criteria_synced_date': now,
                    'assessment_criteria_synced_by_id': user_id,
                })
                self.with_context(force_write=True)._apply_position_plan_to_candidate(cand)
                cand._compute_has_competency_assessment()
                if cand.has_competency_assessment:
                    try:
                        cand.action_populate_competency_eval_lines()
                    except Exception:
                        pass
                else:
                    cand.eval_line_ids.unlink()

                # Dispatch notifications & activities if competency assessment is in plan
                pos_title = self.job_id.name if self.job_id else self.display_name
                emp = cand.employee_id
                if cand.has_competency_assessment:
                    if cand.plan_include_manager and not cand.manager_evaluation_submitted:
                        mgr_user = (emp.parent_id and emp.parent_id.user_id) or (emp.coach_id and emp.coach_id.user_id) or (cand.parent_id and cand.parent_id.user_id)
                        if mgr_user:
                            try:
                                act_summary = f"Evaluate Competencies: {emp.name}"
                                existing_act = self.env['mail.activity'].sudo().search([
                                    ('res_model', '=', 'succession.candidate'),
                                    ('res_id', '=', cand.id),
                                    ('user_id', '=', mgr_user.id),
                                    ('summary', '=', act_summary),
                                ], limit=1)
                                if not existing_act:
                                    cand.activity_schedule(
                                        'mail.mail_activity_data_todo',
                                        user_id=mgr_user.id,
                                        summary=act_summary,
                                        note=f"Assessment criteria synchronized for {emp.name} targeting {pos_title}. Please rate and submit the Manager Competency Evaluation.",
                                        date_deadline=fields.Date.today(),
                                    )
                            except Exception:
                                pass
                    if cand.plan_include_self and not cand.self_evaluation_submitted:
                        try:
                            cand.action_send_self_assessment_notification()
                        except Exception:
                            pass
                    if cand.plan_include_spmc and not cand.spmc_evaluation_submitted:
                        spmc_users = cand.spmc_assessor_ids or (cand.spmc_assigned_user_id and self.env['res.users'].sudo().browse([cand.spmc_assigned_user_id.id]))
                        for spmc_usr in spmc_users:
                            try:
                                act_summary = f"SPMC Evaluation: {emp.name}"
                                existing_act = self.env['mail.activity'].sudo().search([
                                    ('res_model', '=', 'succession.candidate'),
                                    ('res_id', '=', cand.id),
                                    ('user_id', '=', spmc_usr.id),
                                    ('summary', '=', act_summary),
                                ], limit=1)
                                if not existing_act:
                                    cand.activity_schedule(
                                        'mail.mail_activity_data_todo',
                                        user_id=spmc_usr.id,
                                        summary=act_summary,
                                        note=f"Assessment criteria synchronized for {emp.name} targeting {pos_title}. Please rate and submit the SPMC Committee Competency Evaluation.",
                                        date_deadline=fields.Date.today(),
                                    )
                            except Exception:
                                pass
            self.write({
                'plan_last_synced_date': now,
                'plan_last_synced_by_id': user_id,
                'plan_synced_candidate_count': len(active_cands),
            })
            self.message_post(body=_(
                "    Assessment plan automatically populated to %d nominated candidate(s). "
                "They can now record scores and evaluate competencies."
            ) % len(active_cands))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Confirmed & Locked'),
                'message': _('Assessment & Exam Plan finalized and locked (100%%). %d nominated candidate(s) synchronized.') % len(active_cands) if active_cands else _('Assessment & Exam Plan finalized and locked (100%%). Ready for candidate nomination.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_unlock_assessment_plan(self):
        """Unlock assessment plan for PPDD revision."""
        self.ensure_one()
        if not (self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.user.has_group('bunna_succession_management.group_succession_admin')):
            raise UserError(_("Only authorized PPDD Officers or System Administrators can unlock an active Assessment Plan."))

        assessed_cands = self.candidate_ids.filtered(lambda c: c.state in ('assessed', 'approved'))
        msg = _("Assessment & Exam Plan unlocked for revision by %s.") % self.env.user.name
        if assessed_cands:
            msg += _(" Note: %d candidate(s) have already completed evaluation under the previous plan.") % len(assessed_cands)

        self.write({
            'plan_status': 'reopened',
            'plan_locked': False,
        })
        self._log_governance('criteria_synced', msg)
        self.message_post(body=_("🔓 <b>Assessment & Exam Plan Reopened:</b> Plan reopened for revision.") + (" " + msg if assessed_cands else ""))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Reopened'),
                'message': _('Assessment Plan reopened successfully for revision.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_disable_assessment_plan(self):
        """Disable or waive assessment requirements for this position."""
        self.ensure_one()
        if not (self.env.user.has_group('bunna_succession_management.group_succession_ppdd') or self.env.user.has_group('bunna_succession_management.group_succession_admin')):
            raise UserError(_("Only authorized PPDD Officers or System Administrators can disable an Assessment Plan."))
        self.write({'plan_status': 'disabled'})
        self._log_governance('criteria_synced', _("Assessment & Exam Plan disabled/waived by %s.") % self.env.user.name)
        self.message_post(body=_("⛔ <b>Assessment & Exam Plan Disabled:</b> Standardized examination/assessment requirements waived or suspended for this critical position."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Disabled'),
                'message': _('Assessment & Exam Plan disabled successfully.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_enable_assessment_plan(self):
        """Re-enable a disabled assessment plan back into draft configuration."""
        self.ensure_one()
        self.write({'plan_status': 'draft'})
        self._log_governance('criteria_synced', _("Assessment & Exam Plan re-enabled into draft by %s.") % self.env.user.name)
        self.message_post(body=_("🔄 <b>Assessment & Exam Plan Re-Enabled:</b> Restored to draft configuration."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Enabled'),
                'message': _('Assessment Plan restored to draft configuration.'),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def _apply_position_plan_to_candidate(self, cand):
        """
        Apply this critical position's assessment plan to a candidate.
        Preserves candidate-level approved waivers (with justification),
        while updating weights and evaluators to match position assessment plan.
        """
        self.ensure_one()
        if self.plan_status == 'disabled':
            cand._ensure_assessment_results()
            for cand_res in cand.assessment_result_ids:
                cand_res.write({
                    'weight': 0.0,
                    'waived': True,
                    'waiver_reason': _('Assessment Plan Disabled for Position'),
                })
            cand.with_context(skip_apply_scope=True, force_write=True).write({
                'assessment_scope': self.assessment_scope,
                'plan_include_manager': False,
                'plan_include_self': False,
                'plan_include_spmc': False,
                'plan_include_pms': False,
                'plan_include_exam': False,
            })
            cand._refresh_assessment_scores()
            return

        self._ensure_assessment_lines()
        if self.plan_include_spmc and not self.spmc_assessor_ids:
            raise UserError(_(
                "Cannot Sync Assessment Plan: Designated SPMC Committee Assessors Required!\n\n"
                "SPMC Committee Evaluation is enabled for '%(pos)s', but no Designated SPMC Committee Assessors have been assigned.\n\n"
                "Please assign at least one SPMC Committee Member under 'Designated SPMC Committee Assessors' before synchronizing the assessment plan.",
                pos=self.job_id.name if self.job_id else self.display_name,
            ))
        _logger.warning(
            "SYNC_TO_CANDIDATE: pos=%s cand=%s plan_status=%s lines=%s",
            self.id, cand.id, self.plan_status, len(self.assessment_line_ids),
        )
        for l in self.assessment_line_ids:
            _logger.warning(
                "SYNC_TO_CANDIDATE: line comp=%s name=%s weight=%s enabled=%s",
                l.component_id.id, l.component_id.name, l.weight, l.enabled,
            )

        cfg = self.env['succession.assessment.config'].get_config()
        eff_self = bool(self.plan_include_self and cfg.enable_self_assessment)

        cand_vals = {
            'assessment_scope': self.assessment_scope,
            'plan_include_manager': self.plan_include_manager,
            'plan_include_self': eff_self,
            'plan_include_spmc': self.plan_include_spmc,
            'spmc_assessor_ids': [(6, 0, self.spmc_assessor_ids.ids)],
            'spmc_assigned_user_id': self.spmc_assessor_ids[0].id if self.spmc_assessor_ids else False,
            'assessment_plan_defined_by_id': self.env.user.id,
            'assessment_plan_defined_date': fields.Datetime.now(),
        }

        # Use ORM create/write — NOT raw SQL.
        # Raw SQL bypasses Odoo stored computed fields (sequence, component_source,
        # waivable) causing records to not appear in the ORM/view.
        ResultModel = self.env['succession.candidate.assessment.result'].sudo().with_context(force_write=True)

        # Remove any candidate result lines that are no longer in this position's assessment plan
        active_comp_ids = self.assessment_line_ids.mapped('component_id.id')
        obsolete_results = ResultModel.search([
            ('candidate_id', '=', cand.id),
            ('component_id', 'not in', active_comp_ids),
        ])
        if obsolete_results:
            obsolete_results.sudo().unlink()

        for line in self.assessment_line_ids:
            comp_id = line.component_id.id
            is_na = bool(line.not_applicable or not line.enabled)
            weight = line.weight if not is_na else 0.0
            max_score = line.max_score or 100.0
            justification = line.justification if is_na else False

            # Search for existing result line — avoids unique constraint violation
            existing = ResultModel.search([
                ('candidate_id', '=', cand.id),
                ('component_id', '=', comp_id),
            ], limit=1)

            if existing:
                update_vals = {
                    'weight': weight,
                    'max_score': max_score,
                    'waived': is_na,
                    'waiver_reason': justification,
                }
                if is_na:
                    update_vals['score'] = 0.0
                    update_vals['score_entered'] = False
                existing.with_context(force_write=True, skip_waiver_reason_check=True).write(update_vals)
                _logger.warning(
                    "SYNC_TO_CANDIDATE: Updated existing result id=%s comp=%s waived=%s justification=%s",
                    existing.id, comp_id, is_na, justification,
                )
            else:
                ResultModel.with_context(force_write=True, skip_waiver_reason_check=True).create({
                    'candidate_id': cand.id,
                    'component_id': comp_id,
                    'weight': weight,
                    'max_score': max_score,
                    'waived': is_na,
                    'waiver_reason': justification,
                    'score': 0.0,
                    'score_entered': False,
                })
                _logger.warning(
                    "SYNC_TO_CANDIDATE: Created new result for comp=%s waived=%s justification=%s",
                    comp_id, is_na, justification,
                )

        # Verify rows exist in database
        self.env.cr.execute(
            "SELECT COUNT(*) FROM succession_candidate_assessment_result WHERE candidate_id = %s",
            (cand.id,),
        )
        row_count = self.env.cr.fetchone()[0]
        _logger.warning(
            "SYNC_TO_CANDIDATE: Verification — %s rows in DB for candidate %s",
            row_count, cand.id,
        )

        cand.invalidate_recordset(['assessment_result_ids'])
        _logger.warning(
            "SYNC_TO_CANDIDATE: After invalidate — ORM count=%s",
            len(cand.assessment_result_ids),
        )

        # Update candidate legacy compatibility fields
        pms_line = self.assessment_line_ids.filtered(lambda l: l.component_source == 'pms')
        exam_line = self.assessment_line_ids.filtered(lambda l: 'exam' in (l.name or '').lower())
        if pms_line:
            is_pms_enabled = bool(pms_line[0].enabled and not pms_line[0].not_applicable)
            cand_vals['plan_include_pms'] = is_pms_enabled
            cand_vals['weight_pms'] = pms_line[0].weight if is_pms_enabled else 0.0
            if not is_pms_enabled:
                cand_vals['pms_exemption_reason'] = (
                    pms_line[0].justification or _('Excluded by Position Assessment Plan')
                )
            else:
                cand_vals['pms_exemption_reason'] = False
        if exam_line:
            is_exam_enabled = bool(exam_line[0].enabled and not exam_line[0].not_applicable)
            cand_vals['plan_include_exam'] = is_exam_enabled
            cand_vals['weight_exam'] = exam_line[0].weight if is_exam_enabled else 0.0
            if not is_exam_enabled:
                cand_vals['exam_exemption_reason'] = (
                    exam_line[0].justification or _('Excluded by Position Assessment Plan')
                )
            else:
                cand_vals['exam_exemption_reason'] = False

        cand.with_context(skip_apply_scope=True, force_write=True, skip_plan_validation=True).write(cand_vals)
        cand.with_context(skip_apply_scope=True, force_write=True, skip_plan_validation=True)._refresh_assessment_scores()

    def action_apply_plan_to_candidates(self):
        """Sync this critical position's assessment plan to ALL nominated candidates automatically."""
        self.ensure_one()
        if self.plan_status == 'disabled':
            raise UserError(_("Cannot sync plan: Assessment Plan is currently disabled. Please re-enable it first."))
        if not (self.plan_include_manager or self.plan_include_self or self.plan_include_spmc):
            raise UserError(_("At least one evaluator (Manager, Self, or SPMC Committee) must be selected."))

        if self.plan_include_spmc and not self.spmc_assessor_ids:
            raise UserError(_(
                "Cannot Sync Assessment Plan: Designated SPMC Committee Assessors Required!\n\n"
                "SPMC Committee Evaluation is enabled for '%(pos)s', but no Designated SPMC Committee Assessors have been assigned.\n\n"
                "Please assign at least one SPMC Committee Member under 'Designated SPMC Committee Assessors' before synchronizing the assessment plan.",
                pos=self.job_id.name if self.job_id else self.display_name,
            ))

        # Get ALL nominated candidates for this position
        candidates = self.candidate_ids.filtered(
            lambda c: c.state == 'nominated' and not c.assessment_done
        )

        if not candidates:
            raise UserError(_(
                "No nominated candidates found for this position.\n\n"
                "Please nominate accepted candidates first from:\n"
                "Succession Pipeline → Nominate Accepted Candidates"
            ))

        applied_count = 0
        names = []
        now = fields.Datetime.now()
        user_id = self.env.user.id

        for cand in candidates:
            # Mark as synced with audit timestamp and user first
            cand.with_context(force_write=True).write({
                'assessment_criteria_synced': True,
                'assessment_criteria_synced_date': now,
                'assessment_criteria_synced_by_id': user_id,
            })
            # Apply position plan to candidate (populates assessment results)
            self.with_context(force_write=True)._apply_position_plan_to_candidate(cand)
            cand._compute_has_competency_assessment()

            # Ensure competency evaluation lines are populated ONLY if plan includes competency assessment
            if cand.has_competency_assessment:
                try:
                    cand.action_populate_competency_eval_lines()
                except Exception:
                    pass
            else:
                cand.eval_line_ids.unlink()

            # --- Dispatch Notifications & Schedule Activities ---
            pos_title = self.job_id.name if self.job_id else self.display_name
            emp = cand.employee_id

            # Only dispatch competency evaluation activities if competency assessment is in plan
            if cand.has_competency_assessment:
                # 1. Line Manager / Coach evaluation activity
                if cand.plan_include_manager and not cand.manager_evaluation_submitted:
                    mgr_user = (emp.parent_id and emp.parent_id.user_id) or (emp.coach_id and emp.coach_id.user_id) or (cand.parent_id and cand.parent_id.user_id)
                    if mgr_user:
                        try:
                            act_summary = f"Evaluate Competencies: {emp.name}"
                            existing_act = self.env['mail.activity'].sudo().search([
                                ('res_model', '=', 'succession.candidate'),
                                ('res_id', '=', cand.id),
                                ('user_id', '=', mgr_user.id),
                                ('summary', '=', act_summary),
                            ], limit=1)
                            if not existing_act:
                                cand.activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    user_id=mgr_user.id,
                                    summary=act_summary,
                                    note=f"Assessment criteria synchronized for {emp.name} targeting {pos_title}. Please rate and submit the Manager Competency Evaluation.",
                                    date_deadline=fields.Date.today(),
                                )
                        except Exception:
                            pass

                # 2. Candidate self-assessment activity & email
                if cand.plan_include_self and not cand.self_evaluation_submitted:
                    try:
                        cand.action_send_self_assessment_notification()
                    except Exception:
                        pass

                # 3. SPMC evaluation activity for all assigned SPMC assessors
                if cand.plan_include_spmc and not cand.spmc_evaluation_submitted:
                    spmc_users = cand.spmc_assessor_ids or (cand.spmc_assigned_user_id and self.env['res.users'].sudo().browse([cand.spmc_assigned_user_id.id]))
                    for spmc_usr in spmc_users:
                        try:
                            act_summary = f"SPMC Evaluation: {emp.name}"
                            existing_act = self.env['mail.activity'].sudo().search([
                                ('res_model', '=', 'succession.candidate'),
                                ('res_id', '=', cand.id),
                                ('user_id', '=', spmc_usr.id),
                                ('summary', '=', act_summary),
                            ], limit=1)
                            if not existing_act:
                                cand.activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    user_id=spmc_usr.id,
                                    summary=act_summary,
                                    note=f"Assessment criteria synchronized for {emp.name} targeting {pos_title}. Please rate and submit the SPMC Committee Competency Evaluation.",
                                    date_deadline=fields.Date.today(),
                                )
                        except Exception:
                            pass

            names.append(cand.employee_id.name)
            applied_count += 1

        self.write({
            'plan_last_synced_date': now,
            'plan_last_synced_by_id': user_id,
            'plan_synced_candidate_count': applied_count,
        })

        msg = _(
            '    Assessment Plan successfully synced to %d nominated candidate(s):\n%s'
        ) % (applied_count, ', '.join(names))

        self.message_post(body=msg)
        self._log_governance(
            'criteria_synced',
            'Assessment Plan synced to %d nominated candidate(s): %s' % (
                applied_count, ', '.join(names))
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Plan Synchronized'),
                'message': _('Successfully synchronized official Assessment & Exam Plan to %d nominated candidate(s): %s.') % (
                    applied_count, ', '.join(names)),
                'type': 'success',
                'sticky': False,
                'next': self.action_open_assessment_plan(skip_notification=True) if self.env.context.get('in_assessment_plan_dialog') else {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }

    def web_read(self, specification):
        return super(SuccessionCriticalPosition, self.sudo()).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        return super(SuccessionCriticalPosition, self.sudo()).read(fields=fields, load=load)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            job_id = vals.get('job_id')
            if job_id and vals.get('active', True):
                existing = self.search([
                    ('job_id', '=', job_id),
                    ('active', '=', True),
                ], limit=1)
                if existing:
                    job = self.env['hr.job'].sudo().browse(job_id)
                    raise ValidationError(_(
                        "A Critical Position record for '%s' already exists! "
                        "Each Job Position can only be created once in Succession Management."
                    ) % job.display_name)
        records = super().create(vals_list)
        for rec in records:
            rec._ensure_assessment_lines()
        return records

    def action_delete_position(self):
        """Action button to delete/archive position with standard user confirmation."""
        pos_name = self.job_id.name or self.display_name or _('Critical Position')
        self.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Position Deleted'),
                'message': _('Critical Position "%s" has been deleted successfully.') % pos_name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def unlink(self):
        is_admin = self.env.is_admin() or self.env.user.has_group('base.group_system') or self.env.user.has_group('bunna_succession_management.group_succession_admin')
        is_ppdd = self.env.user.has_group('bunna_succession_management.group_succession_ppdd')

        to_hard_delete = self.env['succession.critical.position']
        to_archive = self.env['succession.critical.position']

        for rec in self:
            rec_sudo = rec.sudo()
            is_creator = (rec_sudo.create_uid == self.env.user)
            if rec_sudo.state == 'draft':
                if not (is_creator or is_ppdd or is_admin):
                    raise AccessError(_(
                        "You do not have permission to delete draft critical position '%s'. Only its creator, PPDD Officers, or Administrators can delete draft positions."
                    ) % rec_sudo.display_name)
                to_hard_delete |= rec
            else:
                if not (is_ppdd or is_admin):
                    raise AccessError(_(
                        "You do not have permission to delete this position. Only PPDD Officers and Administrators are authorized."
                    ))
                to_archive |= rec

        if to_archive:
            to_archive.write({'active': False})
            for rec in to_archive:
                rec.message_post(body=_("Position deleted and archived by %s.") % self.env.user.name)

        if to_hard_delete:
            super(SuccessionCriticalPosition, to_hard_delete.sudo()).unlink()

        return True


class SuccessionCriticalPositionAssessmentLine(models.Model):
    """
    Standardized Assessment & Exam Component Line for Critical Positions.
    Defines the baseline Assessment & Exam Plan (components, weights, max scores, and status)
    for evaluating succession candidates for this critical position.
    """
    _name = 'succession.critical.position.assessment.line'
    _description = 'Critical Position Assessment Plan Line'
    _order = 'sequence, id'

    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        required=True, ondelete='cascade', index=True)
    component_id = fields.Many2one(
        'succession.assessment.component', string='Component',
        required=True, ondelete='restrict', domain="[('active', '=', True), ('enabled', '=', True)]", index=True)
    name = fields.Char(related='component_id.name', string='Component Name', readonly=True)
    evaluation_type = fields.Selection(
        related='component_id.evaluation_type', string='Evaluation Type', readonly=True)
    component_source = fields.Selection(
        related='component_id.source', string='Source', readonly=True)
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    weight = fields.Float(string='Weight (%)', default=25.0)
    max_score = fields.Float(string='Max Score', default=100.0)
    not_applicable = fields.Boolean(
        string='Not Applicable (N/A)', default=False,
        help="Check to mark this component as Not Applicable (N/A) for this Critical Position. "
             "Sets weight to 0.0% and requires a documented justification.")
    justification = fields.Char(
        string='Justification / Exemption Reason',
        help="Mandatory business reason or justification if this assessment component is Not Applicable (N/A).")
    enabled = fields.Boolean(
        string='Enabled', default=True, index=True,
        help="If unchecked or Not Applicable, this component is excluded for candidates of this critical position.")
    waivable = fields.Boolean(
        related='component_id.waivable', string='Can be Waived (N/A)', readonly=True)
    description = fields.Text(
        related='component_id.description', string='Description', readonly=True)

    _uniq_position_component = models.Constraint(
        'unique(critical_position_id, component_id)',
        'This assessment component is already defined for this critical position.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('not_applicable') or ('enabled' in vals and not vals['enabled']):
                vals['weight'] = 0.0
                vals['enabled'] = False
                vals['not_applicable'] = True
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('not_applicable') or ('enabled' in vals and not vals['enabled']):
            vals['weight'] = 0.0
            vals['enabled'] = False
            vals['not_applicable'] = True
        res = super().write(vals)
        for rec in self:
            if (rec.not_applicable or not rec.enabled) and rec.weight > 0.0:
                self.env.cr.execute(
                    "UPDATE succession_critical_position_assessment_line SET weight = 0.0 WHERE id = %s",
                    (rec.id,)
                )
                rec.invalidate_recordset(['weight'])
        return res

    @api.onchange('not_applicable')
    def _onchange_not_applicable(self):
        for rec in self:
            if rec.not_applicable:
                rec.enabled = False
                rec.weight = 0.0
            else:
                rec.enabled = True

    @api.onchange('enabled')
    def _onchange_enabled(self):
        for rec in self:
            rec.not_applicable = not rec.enabled
            if not rec.enabled:
                rec.weight = 0.0

    @api.constrains('not_applicable', 'enabled', 'justification', 'weight')
    def _check_not_applicable_governance(self):
        for rec in self:
            is_na = bool(rec.not_applicable or not rec.enabled)
            if is_na:
                if not (rec.justification and rec.justification.strip()):
                    raise ValidationError(_(
                        "Justification Required: Component '%(comp)s' is marked as Not Applicable (N/A) in this Assessment Plan. "
                        "Please provide a written justification / exemption reason explaining why this component is not applicable."
                    ) % {'comp': rec.name or rec.component_id.name or 'Component'})
                if rec.weight > 0.0:
                    self.env.cr.execute(
                        "UPDATE succession_critical_position_assessment_line SET weight = 0.0 WHERE id = %s",
                        (rec.id,)
                    )
                    rec.invalidate_recordset(['weight'])

    @api.constrains('weight', 'max_score')
    def _check_values(self):
        for rec in self:
            if not 0.0 <= rec.weight <= 100.0:
                raise ValidationError(_('A component weight must be between 0 and 100%.'))
            if rec.max_score <= 0.0:
                raise ValidationError(_('The max score must be greater than zero.'))


class SuccessionGovernanceLog(models.Model):

    """

    Immutable Governance Audit Log (FR-GOV-004).

    Every state change, approval, and decision on a critical position

    is permanently recorded here and cannot be deleted.

    """

    _name = 'succession.governance.log'

    _description = 'Succession Governance Audit Log'

    _order = 'create_date desc'



    critical_position_id = fields.Many2one(

        'succession.critical.position', string='Critical Position',

        required=True, ondelete='cascade', index=True)

    action = fields.Selection(index=True, selection=[

        ('submitted_ppdd', 'Submitted for PPDD Review'),

        ('ppdd_approved', 'PPDD Review Completed'),

        ('spmc_approved', 'SPMC Approved'),

        ('candidate_nominated', 'Candidate Nominated'),

        ('candidate_assessed', 'Candidate Assessed'),
        ('assessment_completed', 'Assessment Completed / Readiness Finalized'),

        ('candidate_approved', 'Candidate Approved'),

        ('candidate_rejected', 'Candidate Rejected'),
        ('assessment_result', 'Assessment Result Entered'),
        ('assessment_waived', 'Assessment Component Waived'),
        ('assessment_reopened', 'Assessment Reopened'),
        ('criteria_synced', 'Assessment Criteria Synced'),

        ('deactivated', 'Position Deactivated'),
        ('development_completed_early', 'Development Plan Completed Ahead of Schedule'),
        ('development_extended', 'Development Plan Extended'),
        ('note', 'General Note'),
    ], string='Governance Action', required=True)

    candidate_id = fields.Many2one(
        'succession.candidate', string='Candidate', ondelete='set null', index=True)
    comment = fields.Text(string='Comment / Justification')

    user_id = fields.Many2one(

        'res.users', string='Actor', default=lambda self: self.env.user, readonly=True, index=True)



    def unlink(self):

        raise ValidationError(

            _('Succession governance audit logs are immutable and cannot be deleted.'))





