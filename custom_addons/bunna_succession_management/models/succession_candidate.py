# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


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
    _order = 'readiness_level, employee_id'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Candidate', compute='_compute_display_name', store=True)

    # --- Core Identification ---
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        tracking=True, ondelete='restrict')
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True, readonly=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        related='employee_id.job_id', store=True, readonly=True)
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        required=True, tracking=True, ondelete='cascade',
        domain="[('state', '=', 'approved')]")
    talent_pool_id = fields.Many2one(
        'succession.talent.pool', string='Talent Pool',
        tracking=True, ondelete='set null',
        domain="[('critical_position_id', '=', critical_position_id)]")

    # --- Nomination Info (FR-SEL-001) ---
    nominated_by_id = fields.Many2one(
        'res.users', string='Nominated By',
        default=lambda self: self.env.user, tracking=True)
    nomination_date = fields.Date(
        string='Nomination Date', default=fields.Date.today)
    manager_justification = fields.Text(
        string='Manager Justification',
        help='Explain why this employee is a strong successor for this critical position.')

    # --- Readiness Classification (FR-TAR-006) ---
    readiness_level = fields.Selection([
        ('ready_now', 'Ready Now'),
        ('ready_1_2_yrs', 'Ready in 1-2 Years'),
        ('ready_3_5_yrs', 'Ready in 3-5 Years'),
    ], string='Readiness Level', tracking=True,
       help='System-suggested based on gap analysis; can be overridden by manager.')
    system_readiness_suggestion = fields.Selection([
        ('ready_now', 'Ready Now'),
        ('ready_1_2_yrs', 'Ready in 1-2 Years'),
        ('ready_3_5_yrs', 'Ready in 3-5 Years'),
    ], string='System Readiness Suggestion', readonly=True,
       help='Auto-computed based on competency match % and PMS score.')
    manager_override = fields.Boolean(
        string='Manager Override Applied', default=False,
        help='True when manager has manually overridden the system readiness suggestion.')

    # --- 9-Box Grid Integration (FR-TAL-005) ---
    # Performance sourced from employee's latest PMS score (PBMS/Competency module)
    # Potential sourced from employee's latest competency overall score
    # Both are READ from existing modules — NOT self-calculated here.
    performance_rating = fields.Selection([
        ('low', 'Low Performance'),
        ('medium', 'Medium Performance'),
        ('high', 'High Performance'),
    ], string='Performance Rating', compute='_compute_9box_ratings', store=True,
       help="Auto-sourced from employee's latest PMS score via the Competency module.")
    potential_rating = fields.Selection([
        ('low', 'Low Potential'),
        ('medium', 'Medium Potential'),
        ('high', 'High Potential'),
    ], string='Potential Rating', compute='_compute_9box_ratings', store=True, readonly=False, tracking=True,
       help="Auto-calculated from Target Position Competency Match % vs configured thresholds. Can be manually adjusted during calibration.")
    nine_box_label = fields.Char(
        string='9-Box Position', compute='_compute_9box_label', store=True)
    is_high_potential = fields.Boolean(
        string='High Potential', compute='_compute_9box_label', store=True,
        help='True when employee is Star Performer (High Performance + High Potential).')

    # --- Approval Workflow ---
    state = fields.Selection([
        ('nominated', 'Nominated'),
        ('assessed', 'Assessed'),
        ('approved', 'SPMC Approved'),
        ('deployment_lm', 'Deployment: Line Manager Approval'),
        ('deployment_po', 'Deployment: Principal Officer Approval'),
        ('deployment_ppdd', 'Deployment: PPD Director Approval'),
        ('deployment_spmc', 'Deployment: SPMC Final Approval'),
        ('placed', 'Placed / Deployed'),
        ('rejected', 'Rejected'),
        ('waitlisted', 'Waitlisted'),
    ], string='Status', default='nominated', tracking=True)
    ppdd_notes = fields.Text(string='PPDD Assessment Notes')
    spmc_decision_notes = fields.Text(string='SPMC Decision Notes')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

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

    # --- PMS Score ---
    latest_pms_score = fields.Float(
        string='Latest PMS Score', compute='_compute_pms_score', store=True)

    # --- Tenure ---
    current_tenure_months = fields.Integer(
        string='Experience (Months)', compute='_compute_tenure', store=True)

    # ==========================================================================
    # COMPUTE METHODS
    # ==========================================================================

    @api.depends('employee_id', 'critical_position_id')
    def _compute_display_name(self):
        for rec in self:
            emp = rec.employee_id.name if rec.employee_id else '?'
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
                oldest_contract = self.env['hr.version'].search([
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
            pms_score = 0.0
            if rec.employee_id:
                if hasattr(rec.employee_id, 'pms_score'):
                    pms_score = rec.employee_id.pms_score or 0.0
                elif 'hr.pms.result' in self.env:
                    result = self.env['hr.pms.result'].search([
                        ('employee_id', '=', rec.employee_id.id),
                    ], order='id desc', limit=1)
                    if result:
                        pms_score = getattr(result, 'final_score', 0.0) or 0.0
                elif 'hr.appraisal' in self.env:
                    appraisal = self.env['hr.appraisal'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('state', '=', 'done'),
                    ], order='date_close desc', limit=1)
                    if appraisal:
                        pms_score = getattr(appraisal, 'rating', 0.0) or 0.0
            rec.latest_pms_score = pms_score

    @api.depends('competency_gap_ids', 'competency_gap_ids.achievement_status')
    def _compute_competency_summary(self):
        for rec in self:
            gaps = rec.competency_gap_ids
            if not gaps:
                rec.competency_gap_count = 0
                rec.competency_match_percent = 0.0
                rec.competency_eligible = False
                continue
            total = len(gaps)
            gap_count = len(gaps.filtered(lambda g: g.achievement_status == 'below'))
            rec.competency_gap_count = gap_count
            rec.competency_eligible = gap_count == 0
            met = total - gap_count
            rec.competency_match_percent = round((met / total) * 100, 1) if total else 0.0

    @api.depends('employee_id', 'latest_pms_score', 'competency_match_percent')
    def _compute_9box_ratings(self):
        """
        FR-TAL-005 + FR-TAR-003: Configurable 9-Box Grid Thresholds.

        Performance Rating → Sourced from latest PMS score vs configured Company PMS thresholds.
        Potential Rating → Sourced from Target Competency Match % vs configured Company Potential thresholds.
        """
        for rec in self:
            company = self.env.company

            # ── PERFORMANCE: from PMS score ──────────────────────────────────
            pms = rec.latest_pms_score or 0.0
            if pms >= company.succ_high_perf_threshold:
                rec.performance_rating = 'high'
            elif pms >= company.succ_med_perf_threshold:
                rec.performance_rating = 'medium'
            else:
                rec.performance_rating = 'low'

            # ── POTENTIAL: from Target Competency Match % ─────────────────────
            pot_pct = rec.competency_match_percent or 0.0
            if pot_pct >= company.succ_high_pot_threshold:
                rec.potential_rating = 'high'
            elif pot_pct >= company.succ_med_pot_threshold:
                rec.potential_rating = 'medium'
            else:
                rec.potential_rating = 'low'

    # Fallback 9-Box label mapping if DB cells not seeded yet
    _FALLBACK_NINE_BOX_LABELS = {
        ('high',   'high'):   'Star Performer',
        ('medium', 'high'):   'High Potential',
        ('low',    'high'):   'Rough Diamond',
        ('high',   'medium'): 'High Performer',
        ('medium', 'medium'): 'Core Employee',
        ('low',    'medium'): 'Inconsistent',
        ('high',   'low'):    'Solid Professional',
        ('medium', 'low'):    'Solid Contributor',
        ('low',    'low'):    'Underperformer',
    }

    @api.depends('performance_rating', 'potential_rating')
    def _compute_9box_label(self):
        """Compute human-readable 9-box cell label and high-potential flag from configured cell definitions."""
        cell_model = self.env['succession.ninebox.cell']
        for rec in self:
            if not rec.performance_rating or not rec.potential_rating:
                rec.nine_box_label = 'Not Assessed'
                rec.is_high_potential = False
                continue

            cell = cell_model.search([
                ('performance_rating', '=', rec.performance_rating),
                ('potential_rating', '=', rec.potential_rating)
            ], limit=1)

            if cell:
                rec.nine_box_label = cell.name
                rec.is_high_potential = cell.is_high_potential
            else:
                key = (rec.performance_rating, rec.potential_rating)
                rec.nine_box_label = self._FALLBACK_NINE_BOX_LABELS.get(key, 'Not Assessed')
                rec.is_high_potential = (rec.performance_rating == 'high' and rec.potential_rating == 'high')


    # ==========================================================================
    # WORKFLOW ACTIONS
    # ==========================================================================

    def action_assess(self):
        """PPDD moves candidate from Nominated to Assessed after reviewing gap analysis."""
        for rec in self:
            if not rec.competency_gap_ids:
                raise UserError(
                    _('Run the competency gap analysis first before marking as Assessed.'))
            
            require_spmc = rec.env.company.succ_require_spmc_approval
            if not require_spmc:
                rec.with_context(force_write=True).write({'state': 'approved'})
                rec.message_post(body=_('Candidate marked as Assessed and automatically Approved (SPMC Approval is disabled in Settings).'))
            else:
                rec.with_context(force_write=True).write({'state': 'assessed'})
                rec.message_post(body=_('Candidate assessed. Awaiting SPMC Approval.'))
                
            rec.critical_position_id._log_governance('candidate_assessed', 'Candidate %s assessed for %s' % (rec.employee_id.name, rec.critical_position_id.display_name))

    def action_spmc_approve(self):
        """SPMC final approval of the successor candidate."""
        from odoo.exceptions import ValidationError
        for rec in self:
            # Check Mandatory IDP setting (Skip if candidate is already 'Ready Now')
            if rec.env.company.succ_idp_mandatory and rec.readiness_level != 'ready_now':
                idp = self.env['succession.development.plan'].search([
                    ('candidate_id', '=', rec.id)
                ], limit=1)
                if not idp:
                    raise ValidationError(_("Approval Blocked! The Global Settings require a Mandatory Development Plan (IDP) for candidates who are not 'Ready Now'. Please create an IDP to address this candidate's gaps first."))
                    
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.critical_position_id._log_governance('candidate_approved', 'SPMC approved candidate %s' % rec.employee_id.name)
            rec.message_post(body=_('Candidate %s officially approved as successor.') % rec.employee_id.name)
            if rec.is_high_potential and rec.employee_id:
                if hasattr(rec.employee_id, 'is_high_potential'):
                    rec.employee_id.sudo().write({'is_high_potential': True})


    def action_reject(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'rejected'})
            rec.critical_position_id._log_governance(
                'candidate_rejected',
                'Candidate %s rejected for %s' % (
                    rec.employee_id.name, rec.critical_position_id.display_name))

    def action_waitlist(self):
        self.with_context(force_write=True).write({'state': 'waitlisted'})

    def action_initiate_deployment(self):
        for rec in self:
            if rec.readiness_level != 'ready_now':
                raise ValidationError(_(
                    'Deployment Blocked! You cannot deploy a candidate who still has competency gaps. '
                    'Their Readiness Level must be "Ready Now" before you can initiate deployment.'))
            rec.write({'state': 'deployment_lm'})
            rec.message_post(body=_('Deployment workflow initiated. Awaiting Line Manager approval.'))

    def action_deployment_lm_approve(self):
        for rec in self:
            rec.write({'state': 'deployment_po'})
            rec.message_post(body=_('Line Manager approved deployment. Awaiting Principal Officer approval.'))

    def action_deployment_po_approve(self):
        for rec in self:
            rec.write({'state': 'deployment_ppdd'})
            rec.message_post(body=_('Principal Officer approved deployment. Awaiting PPD Director approval.'))

    def action_deployment_ppdd_approve(self):
        for rec in self:
            rec.write({'state': 'deployment_spmc'})
            rec.message_post(body=_('PPD Director approved deployment. Awaiting SPMC final approval.'))

    def action_execute_placement(self):
        """
        FR-RDY-004 & FR-RDY-005
        Final SPMC approval for deployment. Updates employee job_id and notifies POMD.
        """
        for rec in self:
            rec.write({'state': 'placed'})
            
            # Update HR Profile
            if rec.employee_id and rec.critical_position_id.job_id:
                rec.employee_id.sudo().write({
                    'job_id': rec.critical_position_id.job_id.id,
                    'department_id': rec.critical_position_id.department_id.id,
                })
            
            # Notify POMD
            rec.message_post(
                body=_('SPMC approved final placement. Employee HR profile updated automatically. POMD notified.')
            )
            pomd_group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
            if pomd_group:
                for user in pomd_group.user_ids:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=user.id,
                        summary='Succession Placement Executed',
                        note='Please complete administrative placement tasks for %s.' % rec.employee_id.name
                    )

    def action_compute_gap_analysis(self):
        """
        Pull the employee's latest approved competency assessment and compare
        against the Critical Position's required competencies (FR-SEL-002).
        Auto-suggests readiness level based on match percentage and PMS score.
        """
        self.ensure_one()
        if not self.critical_position_id.required_role_mapping_line_ids:
            raise UserError(
                _('The critical position has no required competencies configured. '
                  'Please ask HR to update the critical position profile.'))

        # Clear existing gap lines
        self.competency_gap_ids.unlink()

        employee = self.employee_id
        gap_lines = []

        # Get employee's latest approved assessment
        assessment = self.env['competency.assessment'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['approved', 'locked']),
        ], order='id desc', limit=1)

        for mapping_line in self.critical_position_id.required_role_mapping_line_ids:
            competency = mapping_line.competency_id
            required_score = float(mapping_line.required_proficiency or '3.0')
            weight = mapping_line.weight or 1.0

            current_score = 0.0
            if assessment:
                asm_line = assessment.line_ids.filtered(
                    lambda l: l.competency_id.id == competency.id)
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
                # Store these floats temporarily for calculating the weighted percentage below
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

        ready_now_min = self.env.company.succ_ready_now_min_match or 90.0
        ready_soon_min = self.env.company.succ_ready_soon_min_match or 70.0

        if match_pct >= ready_now_min and pms >= 4.0:
            suggestion = 'ready_now'
        elif match_pct >= ready_soon_min and pms >= 3.5:
            suggestion = 'ready_1_2_yrs'
        else:
            suggestion = 'ready_3_5_yrs'

        vals = {'system_readiness_suggestion': suggestion}
        if not self.manager_override:
            vals['readiness_level'] = suggestion

        self.with_context(force_write=True).write(vals)
        self.message_post(
            body=_('Gap analysis computed. Match: %s%%. PMS: %.1f. System Readiness Suggestion: %s') % (
                match_pct, pms,
                dict(self._fields['readiness_level'].selection).get(suggestion, '')))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gap Analysis Complete'),
                'message': _('Competency match: %s%%. Suggested readiness: %s') % (
                    match_pct,
                    dict(self._fields['readiness_level'].selection).get(suggestion, '')),
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_set_readiness_override(self):
        """Mark that manager has manually overridden the system readiness suggestion."""
        self.write({'manager_override': True})

    _sql_constraints = [
        ('employee_position_uniq', 'unique(employee_id, critical_position_id)',
         'This employee is already a candidate for this critical position!'),
    ]


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
        required=True, ondelete='cascade')
    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        related='candidate_id.critical_position_id', store=True, readonly=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='candidate_id.department_id', store=True, readonly=True)
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        required=True, ondelete='restrict')
    competency_pillar = fields.Selection(
        related='competency_id.pillar', string='Pillar', store=True, readonly=True)
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
    ], string='Status')
