# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    _order = 'risk_level, job_id'
    _rec_name = 'display_name'

    # --- Core Identification ---
    job_id = fields.Many2one(
        'hr.job', string='Job Position', required=True,
        tracking=True, ondelete='restrict')
    department_id = fields.Many2one(
        'hr.department', string='Department',
        compute='_compute_department_id', store=True, readonly=False, precompute=True,
        tracking=True)
    display_name = fields.Char(
        string='Critical Position', compute='_compute_display_name', store=True)

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

    def _resolve_department_for_job(self, job):
        if not job:
            return False
        # 1. Direct job position department
        if job.department_id:
            return job.department_id
            
        # 2. Check department of active employees holding this job position
        emp = self.env['hr.employee'].search([('job_id', '=', job.id), ('department_id', '!=', False)], limit=1)
        if emp and emp.department_id:
            return emp.department_id
            
        # 3. Smart title keyword match against department directory
        job_name = job.name or ''
        stopwords = {'head', 'director', 'officer', 'manager', 'senior', 'junior', 'lead', 'chief', 'vp', 'executive', 'team', 'art', 'of', 'and', 'the', 'in', 'for', 'to'}
        words = [w for w in job_name.replace('(', ' ').replace(')', ' ').split() if len(w) > 2 and w.lower() not in stopwords]
        
        for word in words:
            dept = self.env['hr.department'].search([('name', 'ilike', word)], limit=1)
            if dept:
                return dept
                
        return False

    # --- Risk Classification (FR-SWP-002) ---
    risk_level = fields.Selection([
        ('critical', 'Critical (Highest Risk)'),
        ('high', 'High Risk'),
        ('medium', 'Medium Risk'),
    ], string='Risk Level', required=True, default='high', tracking=True)
    business_impact = fields.Text(
        string='Business Impact Statement',
        help='Describe the operational and strategic impact of this position being vacant.')
    vacancy_probability = fields.Selection([
        ('high', 'Immediate (Within 1 year)'),
        ('medium', 'Short-Term (1 to 2 years)'),
        ('low', 'Long-Term (Over 2 years)'),
    ], string='Target Succession Timeframe', default='medium', tracking=True)

    # --- Strategic Workforce Planning Inputs (FR-SWP-001) ---
    strategic_plan_review_outcome = fields.Html(
        string='Strategic Alignment',
        help="How this position aligns with the bank's long-term strategic goals.")
    future_capability_reqs = fields.Html(
        string='Future Capability Requirements',
        help='Capabilities needed for this role in the next 3-5 years.')
    emerging_business_needs = fields.Html(
        string='Emerging Business Needs',
        help='New products, markets, technologies, or regulatory changes impacting this role.')
    workforce_risk_notes = fields.Html(
        string='Workforce Risk Notes',
        help='Specific flight risks, retirement risks, or market scarcity for this role.')

    # --- Review Cycle (FR-SWP-004) ---
    next_review_date = fields.Date(string='Next Review Date', tracking=True)
    review_interval_months = fields.Integer(string='Review Interval (Months)', default=12)

    # --- Bench Strength Metrics (For Matrix Reporting) ---
    ready_now_count = fields.Integer(
        string='Ready Now', compute='_compute_bench_metrics', store=False)
    ready_1_2_yrs_count = fields.Integer(
        string='Ready in 1-2 Yrs', compute='_compute_bench_metrics', store=False)
    ready_3_5_yrs_count = fields.Integer(
        string='Ready in 3-5 Yrs', compute='_compute_bench_metrics', store=False)
    total_bench_count = fields.Integer(
        string='Total Bench', compute='_compute_bench_metrics', store=False)
    bench_health = fields.Selection([
        ('strong', 'Strong (Multiple Ready Now)'),
        ('adequate', 'Adequate (At least 1 Ready Now)'),
        ('at_risk', 'At Risk (No Ready Now)'),
        ('critical', 'Critical (Empty Bench)'),
    ], string='Bench Health', compute='_compute_bench_metrics', store=False)

    def _compute_bench_metrics(self):
        for rec in self:
            candidates = self.env['succession.candidate'].search([
                ('critical_position_id', '=', rec.id),
                ('state', 'in', ['assessed', 'approved', 'placed'])
            ])
            now_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_now'))
            soon_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_1_2_yrs'))
            later_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_3_5_yrs'))
            total = now_count + soon_count + later_count
            
            rec.ready_now_count = now_count
            rec.ready_1_2_yrs_count = soon_count
            rec.ready_3_5_yrs_count = later_count
            rec.total_bench_count = total
            
            if total == 0:
                rec.bench_health = 'critical'
            elif now_count >= 2:
                rec.bench_health = 'strong'
            elif now_count == 1:
                rec.bench_health = 'adequate'
            else:
                rec.bench_health = 'at_risk'

    # --- Competency Profile (FR-SWP-003) ---
    required_role_mapping_line_ids = fields.Many2many(
        'competency.role.mapping.line',
        string='Required Competencies',
        compute='_compute_required_role_mapping_line_ids',
        help='Core competencies and proficiency levels that successors must demonstrate for this position.'
    )

    @api.depends('job_id')
    def _compute_required_role_mapping_line_ids(self):
        for rec in self:
            if rec.job_id:
                mapping = self.env['competency.role.mapping'].search([
                    ('job_position_id', '=', rec.job_id.id),
                    ('state', '=', 'approved')
                ], limit=1)
                if mapping and mapping.line_ids:
                    rec.required_role_mapping_line_ids = mapping.line_ids
                else:
                    rec.required_role_mapping_line_ids = False
            else:
                rec.required_role_mapping_line_ids = False

    min_successor_count = fields.Integer(
        string='Minimum Successor Count',
        default=2,
        help='Minimum number of identified successors (bench strength target).')

    # --- Approval Workflow (FR-SWP-005) ---
    state = fields.Selection([
        ('draft', 'Draft (PPDD)'),
        ('ppdd_review', 'PPDD Review'),
        ('spmc_approval', 'Pending SPMC Approval'),
        ('approved', 'Approved & Active'),
        ('deactivated', 'Deactivated'),
    ], string='Status', default='draft', tracking=True)
    ppdd_reviewed_by_id = fields.Many2one('res.users', string='PPDD Reviewed By', readonly=True)
    ppdd_review_date = fields.Datetime(string='PPDD Review Date', readonly=True)
    spmc_approved_by_id = fields.Many2one('res.users', string='SPMC Approved By', readonly=True)
    spmc_approval_date = fields.Datetime(string='SPMC Approval Date', readonly=True)
    notes = fields.Text(string='Notes / Justification')

    # --- Succession Statistics ---
    talent_pool_ids = fields.One2many(
        'succession.talent.pool', 'critical_position_id',
        string='Talent Pools')
    candidate_ids = fields.One2many(
        'succession.candidate', 'critical_position_id',
        string='Successor Candidates')
    talent_pool_count = fields.Integer(
        string='Talent Pools', compute='_compute_succession_stats')
    candidate_count = fields.Integer(
        string='Total Candidates', compute='_compute_succession_stats')
    ready_now_count = fields.Integer(
        string='Ready Now', compute='_compute_succession_stats')
    ready_soon_count = fields.Integer(
        string='Ready Soon (1-2 Yrs)', compute='_compute_succession_stats')
    bench_strength = fields.Char(
        string='Bench Strength', compute='_compute_succession_stats')
    succession_risk = fields.Selection([
        ('draft', 'Draft (Pending Pipeline)'),
        ('low', 'Low Risk'),
        ('medium', 'Medium Risk'),
        ('high', 'High Risk'),
        ('critical', 'Critical — No Successors'),
    ], string='Succession Risk', compute='_compute_succession_risk', store=True)

    # --- Audit ---
    governance_log_ids = fields.One2many(
        'succession.governance.log', 'critical_position_id',
        string='Governance Audit Log')

    @api.depends('job_id', 'department_id')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.job_id.name] if rec.job_id else ['(No Position)']
            if rec.department_id:
                parts.append('— %s' % rec.department_id.name)
            rec.display_name = ' '.join(parts)

    @api.depends('candidate_ids', 'candidate_ids.readiness_level',
                 'candidate_ids.state', 'min_successor_count', 'talent_pool_ids')
    def _compute_succession_stats(self):
        for rec in self:
            rec.talent_pool_count = len(rec.talent_pool_ids)
            approved_candidates = rec.candidate_ids.filtered(
                lambda c: c.state in ('assessed', 'approved'))
            rec.candidate_count = len(approved_candidates)
            ready_now = approved_candidates.filtered(
                lambda c: c.readiness_level == 'ready_now')
            ready_soon = approved_candidates.filtered(
                lambda c: c.readiness_level == 'ready_1_2_yrs')
            rec.ready_now_count = len(ready_now)
            rec.ready_soon_count = len(ready_soon)
            rec.bench_strength = '%d / %d' % (
                len(approved_candidates), rec.min_successor_count or 0)

    @api.depends('candidate_ids', 'candidate_ids.readiness_level',
                 'candidate_ids.state', 'state', 'job_id')
    def _compute_succession_risk(self):
        for rec in self:
            if rec.state == 'draft' or not rec.job_id:
                rec.succession_risk = 'draft'
                continue
            approved_candidates = rec.candidate_ids.filtered(
                lambda c: c.state in ('assessed', 'approved'))
            ready_now_count = len(approved_candidates.filtered(lambda c: c.readiness_level == 'ready_now'))
            ready_soon_count = len(approved_candidates.filtered(lambda c: c.readiness_level == 'ready_1_2_yrs'))
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
            rec.with_context(force_write=True).write({
                'state': 'spmc_approval',
                'ppdd_reviewed_by_id': self.env.user.id,
                'ppdd_review_date': fields.Datetime.now(),
            })
            rec._log_governance('ppdd_approved', 'Prepared by PPDD — Submitted for SPMC Approval')
            rec.message_post(body=_('Critical position %s submitted by PPDD for SPMC approval.') % rec.display_name)

    def action_spmc_approve(self):
        """Final SPMC approval — position is now officially critical and active."""
        for rec in self:
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'spmc_approved_by_id': self.env.user.id,
                'spmc_approval_date': fields.Datetime.now(),
            })
            rec._log_governance('spmc_approved', 'SPMC Final Approval Granted')
            rec.message_post(
                body=_('Critical position %s officially approved by SPMC (%s). Succession pipeline is now active.') % (
                    rec.display_name, self.env.user.name))

    def action_auto_match_candidates(self):
        self.ensure_one()
        if not self.required_role_mapping_line_ids:
            raise ValidationError(_('Please define Required Competencies for this Critical Position first, or ensure the selected Job Position has an Approved Competency Role Mapping.'))

        # We will create a wizard record and open it.
        wizard = self.env['succession.auto.match.wizard'].create({
            'critical_position_id': self.id,
        })
        
        req_comps = self.required_role_mapping_line_ids.mapped('competency_id')
        req_comp_count = len(req_comps)
        req_comp_ids = set(req_comps.ids)
        
        # 1. Get all employees with completed / approved / verified / locked assessments
        assessments = self.env['competency.assessment'].search([
            ('state', 'in', ['approved', 'locked', 'hr_verified', 'submitted'])
        ], order='id desc')
        
        if not assessments:
            assessments = self.env['competency.assessment'].search([
                ('state', '!=', 'draft')
            ], order='id desc')

        if not assessments:
            assessments = self.env['competency.assessment'].search([], order='id desc')
        
        # Process each employee to find their latest assessment
        employee_latest_assessment = {}
        for a in assessments:
            emp_id = a.employee_id.id
            if emp_id and emp_id not in employee_latest_assessment:
                employee_latest_assessment[emp_id] = a
                
        # Read the global threshold from settings (fallback to 0 if not found)
        threshold = float(self.env['ir.config_parameter'].sudo().get_param('bunna_succession_management.succ_auto_match_min_score', 0.0))

        match_lines_data = []
        for emp_id, assessment in employee_latest_assessment.items():
            # Only count competencies where the employee meets or exceeds the required level
            achieved_comp_ids = set(assessment.line_ids.filtered(lambda l: l.tna_measure in ('meets', 'exceeds')).mapped('competency_id.id'))
            matched_comps = req_comp_ids.intersection(achieved_comp_ids)
            matched_count = len(matched_comps)
            
            if matched_count > 0 or req_comp_count == 0:
                match_percent = (matched_count / req_comp_count * 100.0) if req_comp_count > 0 else 0.0
                
                if match_percent >= threshold:
                    match_lines_data.append({
                        'employee_id': emp_id,
                        'matched_competency_count': matched_count,
                        'required_competency_count': req_comp_count,
                        'match_percent': match_percent,
                    })
                
        # Sort candidate lines by match percentage descending
        match_lines_data.sort(key=lambda x: x['match_percent'], reverse=True)
        
        match_lines = [(0, 0, line) for line in match_lines_data]
        wizard.write({'match_line_ids': match_lines})
        
        return {
            'name': _('Auto-Match Candidates'),
            'type': 'ir.actions.act_window',
            'res_model': 'succession.auto.match.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_new_candidate_form(self):
        self.ensure_one()
        return {
            'name': _('Nominate Candidate'),
            'type': 'ir.actions.act_window',
            'res_model': 'succession.candidate',
            'view_mode': 'form',
            'context': {'default_critical_position_id': self.id},
            'target': 'current',
        }

    def action_deactivate(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'deactivated'})
            rec._log_governance('deactivated', 'Position Deactivated')

    def action_view_talent_pools(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Talent Pools — %s') % self.display_name,
            'res_model': 'succession.talent.pool',
            'view_mode': 'list,form',
            'domain': [('critical_position_id', '=', self.id)],
            'context': {'default_critical_position_id': self.id},
        }

    def action_view_candidates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Candidates — %s') % self.display_name,
            'res_model': 'succession.candidate',
            'view_mode': 'list,form',
            'domain': [('critical_position_id', '=', self.id)],
            'context': {'default_critical_position_id': self.id},
        }

    def action_view_ready_now(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ready Now — %s') % self.display_name,
            'res_model': 'succession.candidate',
            'view_mode': 'list,form',
            'domain': [('critical_position_id', '=', self.id),
                       ('readiness_level', '=', 'ready_now')],
        }

    def _log_governance(self, action, comment):
        self.env['succession.governance.log'].create({
            'critical_position_id': self.id,
            'action': action,
            'comment': comment,
            'user_id': self.env.user.id,
        })

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state in ('approved',) and not force_write and not self.env.su:
                locked = {'job_id', 'department_id', 'risk_level'}
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
            existing = self.env['mail.activity'].search([
                ('res_id', '=', pos.id),
                ('res_model_id', '=', self.env['ir.model']._get_id('succession.critical.position')),
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
                ('readiness_level', '=', 'ready_now'),
                ('state', 'in', ['assessed', 'approved']),
            ])
            if ready_now == 0:
                # Send alert activity to all PPDD users
                for user in ppdd_group.user_ids:
                    existing = self.env['mail.activity'].search([
                        ('res_id', '=', pos.id),
                        ('res_model_id', '=', self.env['ir.model']._get_id(
                            'succession.critical.position')),
                        ('user_id', '=', user.id),
                        ('summary', 'ilike', 'No Ready-Now Successor'),
                    ], limit=1)
                    if not existing:
                        pos.activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=user.id,
                            summary='⚠️ No Ready-Now Successor: %s' % pos.display_name,
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
        ready_now_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_now'))
        ready_soon_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_1_2_yrs'))
        ready_later_count = len(candidates.filtered(lambda c: c.readiness_level == 'ready_3_5_yrs'))
        
        # Calculate percentages
        ready_now_percent = int((ready_now_count / total_candidates * 100)) if total_candidates else 0
        ready_soon_percent = int((ready_soon_count / total_candidates * 100)) if total_candidates else 0
        ready_later_percent = int((ready_later_count / total_candidates * 100)) if total_candidates else 0
        
        # 3. High Risk Critical Positions List
        critical_list = []
        for pos in positions.filtered(lambda p: p.succession_risk in ('high', 'critical', 'medium')):
            critical_list.append({
                'id': pos.id,
                'name': pos.display_name,
                'risk': pos.succession_risk,
                'bench_strength': pos.candidate_count
            })
            
        # 4. New Models Data
        talent_pools = self.env['succession.talent.pool'].search_count([('state', '=', 'active')])
        active_dev_plans = self.env['succession.development.plan'].search_count([('state', '=', 'active')])
        recent_discussions = self.env['succession.career.discussion'].search_count([])
        
        # 5. Career Pathing Data
        total_aspirations = self.env['hr.career.aspiration'].search_count([])
        total_idps = self.env['hr.career.idp'].search_count([])
        
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
            'critical_list': sorted(critical_list, key=lambda x: (x['risk'] == 'critical', x['risk'] == 'high', x['risk'] == 'medium'), reverse=True)[:5],
            'talent_pools_count': talent_pools,
            'active_dev_plans_count': active_dev_plans,
            'recent_discussions_count': recent_discussions,
            'total_aspirations_count': total_aspirations,
            'total_idps_count': total_idps,
        }




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
        required=True, ondelete='cascade')
    action = fields.Selection([
        ('submitted_ppdd', 'Submitted for PPDD Review'),
        ('ppdd_approved', 'PPDD Review Completed'),
        ('spmc_approved', 'SPMC Approved'),
        ('candidate_nominated', 'Candidate Nominated'),
        ('candidate_assessed', 'Candidate Assessed'),
        ('candidate_approved', 'Candidate Approved'),
        ('candidate_rejected', 'Candidate Rejected'),
        ('deactivated', 'Position Deactivated'),
        ('note', 'General Note'),
    ], string='Governance Action', required=True)
    comment = fields.Text(string='Comment / Justification')
    user_id = fields.Many2one(
        'res.users', string='Actor', default=lambda self: self.env.user, readonly=True)

    def unlink(self):
        raise ValidationError(
            _('Succession governance audit logs are immutable and cannot be deleted.'))

class SuccessionAutoMatchWizard(models.TransientModel):
    _name = 'succession.auto.match.wizard'
    _description = 'Succession Auto-Match Candidates Wizard'

    critical_position_id = fields.Many2one('succession.critical.position', string='Critical Position', readonly=True)
    job_id = fields.Many2one('hr.job', related='critical_position_id.job_id', string='Job Position', readonly=True)
    match_line_ids = fields.One2many('succession.auto.match.line', 'wizard_id', string='Matched Candidates')

class SuccessionAutoMatchLine(models.TransientModel):
    _name = 'succession.auto.match.line'
    _description = 'Succession Auto-Match Candidate Line'
    _order = 'match_percent desc, employee_id'

    wizard_id = fields.Many2one('succession.auto.match.wizard', string='Wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department')
    job_id = fields.Many2one('hr.job', related='employee_id.job_id', string='Current Job')
    
    match_percent = fields.Float(string='Competency Match (%)')
    matched_competency_count = fields.Integer(string='Matched Competencies')
    required_competency_count = fields.Integer(string='Required Competencies')
    
    def action_nominate(self):
        self.ensure_one()
        critical_pos = self.wizard_id.critical_position_id
        
        # Check if already a candidate
        existing = self.env['succession.candidate'].search([
            ('critical_position_id', '=', critical_pos.id),
            ('employee_id', '=', self.employee_id.id)
        ])
        if existing:
            raise ValidationError(_('%s is already nominated for this position.') % self.employee_id.name)
            
        candidate = self.env['succession.candidate'].create({
            'critical_position_id': critical_pos.id,
            'employee_id': self.employee_id.id,
            'nominated_by_id': self.env.user.id,
            'manager_justification': _('Auto-Nominated based on %s%% competency match.') % self.match_percent,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Successor Candidate'),
            'res_model': 'succession.candidate',
            'res_id': candidate.id,
            'view_mode': 'form',
            'target': 'current',
        }
