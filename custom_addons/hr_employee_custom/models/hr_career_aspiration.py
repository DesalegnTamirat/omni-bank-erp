# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class HrCareerAspiration(models.Model):
    """
    Employee Career Aspiration (FR-CAR-001, FR-CAR-003, FR-CAR-004).
    Captures the employee's declared career aspiration towards a specific target
    career path node, and automatically computes the full gap analysis against
    all eligibility requirements (Competency, PMS, Tenure, Qualification, Certification).
    """
    _name = 'hr.career.aspiration'
    _description = 'Employee Career Aspiration & Gap Analysis'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False)

    # --- Core fields ---
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=lambda self: self.env.user.employee_id)


    target_job_id = fields.Many2one(
        'hr.job', string='Target Job Position', required=True, tracking=True,
        help='The specific role you are aspiring to reach.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('manager_review', 'Manager Review'),
        ('approved', 'Approved / Active'),
        ('on_hold', 'On Hold'),
        ('achieved', 'Achieved'),
        ('withdrawn', 'Withdrawn'),
    ], string='Status', default='draft', tracking=True)
    submission_date = fields.Date(string='Submission Date')
    manager_id = fields.Many2one(
        'hr.employee', string='Reviewing Manager',
        related='employee_id.parent_id', store=True, readonly=True)
    notes = fields.Text(string='Employee Notes / Motivation')
    manager_notes = fields.Text(string='Manager Feedback')
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)

    # --- Career Discussion Template (FR-CDP-004) ---
    career_discussion_date = fields.Date(string='Discussion Date')
    career_discussion_summary = fields.Text(string='Discussion Summary')
    key_strengths = fields.Text(string='Key Strengths')
    development_areas = fields.Text(string='Development Areas')
    next_steps = fields.Text(string='Action Items / Next Steps')

    idp_count = fields.Integer(string='IDPs', compute='_compute_idp_count')

    # Computed fields to control form access
    is_owner = fields.Boolean(compute='_compute_is_owner', string='Is Owner')
    is_manager_user = fields.Boolean(compute='_compute_is_manager_user', string='Is Manager User')

    @api.depends('employee_id')
    def _compute_is_owner(self):
        for rec in self:
            rec.is_owner = rec.employee_id and rec.employee_id.user_id == self.env.user

    @api.depends('manager_id', 'employee_id')
    def _compute_is_manager_user(self):
        for rec in self:
            is_mgr = rec.manager_id and rec.manager_id.user_id == self.env.user
            is_coach = rec.employee_id and rec.employee_id.coach_id and rec.employee_id.coach_id.user_id == self.env.user
            is_hr = self.env.user.has_group('hr_employee_custom.group_career_path_admin')
            rec.is_manager_user = bool(is_mgr or is_coach or is_hr)

    def _compute_idp_count(self):
        for rec in self:
            rec.idp_count = self.env['hr.career.idp'].search_count([('aspiration_id', '=', rec.id)])

    def action_view_idp(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_employee_custom.action_hr_career_idp')
        action['domain'] = [('aspiration_id', '=', self.id)]
        action['context'] = {'default_aspiration_id': self.id, 'default_employee_id': self.employee_id.id}
        return action

    # =========================================================================
    # GAP ANALYSIS ENGINE
    # Automatically pulls from competency_management and hr_employee_custom
    # to compute the full eligibility status of the employee for the target node.
    # =========================================================================

    # --- 1. Competency Gap Lines (computed from role mapping) ---
    # competency_gap_ids = fields.One2many(
    #     'hr.career.aspiration.competency.gap', 'aspiration_id',
    #     string='Competency Gap Analysis',
    #     help='Auto-computed comparison: Employee current skill vs. required skill for target role.')

    # --- 2. Tenure Check ---
    current_tenure_years = fields.Float(
        string='Current Experience (Years)', compute='_compute_tenure', store=True)
    required_tenure_years = fields.Float(
        string='Required Experience (Years)', compute='_compute_transition_requirements', store=True)
    tenure_gap = fields.Float(
        string='Experience Gap (Years)', compute='_compute_eligibility_flags', store=True)
    tenure_eligible = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='Experience Meets Requirement', compute='_compute_eligibility_flags', store=True)

    # --- 3. PMS Score Check ---
    latest_pms_score = fields.Float(
        string='Latest PMS Score', compute='_compute_pms_score', store=True,
        help='Fetched from the PMS module (hr_version).')
    required_pms_score = fields.Float(
        string='Required PMS Score', compute='_compute_transition_requirements', store=True)
    pms_eligible = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='PMS Meets Requirement', compute='_compute_eligibility_flags', store=True)

    # --- 4. Qualification & Certification Check ---
    required_qualification = fields.Char(
        string='Required Qualification', compute='_compute_transition_requirements', store=True)
    employee_qualification = fields.Char(
        string='Employee Qualification', compute='_compute_employee_profile', store=True)
    qualification_eligible = fields.Selection([
        ('yes', 'Meets'),
        ('no', 'Missing'),
        ('na', 'N/A (Not Required)'),
    ], string='Qualification Status', compute='_compute_eligibility_flags', store=True)

    # --- 5. Competency Summary ---
    # competency_gap_count = fields.Integer(
    #     string='Competency Gaps', compute='_compute_competency_summary', store=True)
    # competency_eligible = fields.Boolean(
    #     string='Competency Eligible', compute='_compute_competency_summary', store=True)
    # competency_match_percent = fields.Float(
    #     string='Competency Match (%)', compute='_compute_competency_summary', store=True)

    # --- 6. Overall Eligibility ---
    overall_eligible = fields.Selection([
        ('pending', 'Pending Evaluation'),
        ('eligible', 'Eligible'),
        ('not_eligible', 'Not Yet Eligible'),
        ('conditionally_eligible', 'Conditionally Eligible'),
    ], string='Overall Career Eligibility',
       compute='_compute_overall_eligibility', store=True, tracking=True)
    eligibility_summary = fields.Text(
        string='Eligibility Summary', compute='_compute_overall_eligibility', store=True)

    # =========================================================================
    # COMPUTE METHODS
    # =========================================================================

    @api.depends('target_job_id')
    def _compute_transition_requirements(self):
        for rec in self:
            if rec.target_job_id:
                job = rec.target_job_id
                rec.required_tenure_years = job.minimum_number_years_in_company if hasattr(job, 'minimum_number_years_in_company') else 0.0
                rec.required_pms_score = job.minimum_pms_score if hasattr(job, 'minimum_pms_score') else 0.0
                
                if hasattr(job, 'qualification_id') and job.qualification_id:
                    quals = job.qualification_id.filtered('qualification')
                    if quals and hasattr(quals[0].qualification, 'qualification'):
                        # The name field in recruitment.qualification is actually "qualification"
                        rec.required_qualification = quals[0].qualification.qualification
                    elif quals and hasattr(quals[0].qualification, 'name'):
                        rec.required_qualification = quals[0].qualification.name
                    elif quals:
                        rec.required_qualification = str(quals[0].qualification)
                    else:
                        rec.required_qualification = False
                else:
                    rec.required_qualification = False
            else:
                rec.required_tenure_years = 0.0
                rec.required_pms_score = 0.0
                rec.required_qualification = False

    # =========================================================================

    @api.depends('employee_id')
    def _compute_tenure(self):
        from dateutil.relativedelta import relativedelta
        from odoo.fields import Date
        for rec in self:
            emp = rec.employee_id
            start_date = False
            
            if emp:
                if 'hr.version' in self.env:
                    # Fetch the very first contract/version to get the true start date
                    contract = self.env['hr.version'].search([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['open', 'draft', 'close'])
                    ], order='create_date asc', limit=1)
                    if contract:
                        if hasattr(contract, 'date_start') and contract.date_start:
                            start_date = contract.date_start
                        elif hasattr(contract, 'contract_date_start') and contract.contract_date_start:
                            start_date = contract.contract_date_start

                if not start_date and hasattr(emp, 'service_start_date') and emp.service_start_date:
                    start_date = emp.service_start_date
                    
            if emp and start_date:
                end_date = emp.service_termination_date if hasattr(emp, 'service_termination_date') and emp.service_termination_date else Date.today()
                delta = relativedelta(end_date, start_date)
                rec.current_tenure_years = delta.years + (delta.months / 12.0)
            else:
                rec.current_tenure_years = 0.0

    @api.depends('employee_id')
    def _compute_pms_score(self):
        """
        Fetch the latest PMS score from hr.version (contract).
        """
        for rec in self:
            pms_score = 0.0
            if rec.employee_id:
                if 'hr.version' in self.env:
                    contract = self.env['hr.version'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('state', 'in', ['open', 'draft', 'close'])
                    ], order='create_date desc', limit=1)
                    if contract and hasattr(contract, 'pms_score'):
                        pms_score = contract.pms_score or 0.0
                if not pms_score and hasattr(rec.employee_id, 'pms_score'):
                    pms_score = rec.employee_id.pms_score or 0.0
            rec.latest_pms_score = pms_score


    @api.depends('employee_id', 'employee_id.qualification_id')
    def _compute_employee_profile(self):
        for rec in self:
            emp = rec.employee_id
            # Pull the highest qualification from the employee's education records
            if emp and emp.qualification_id:
                qualifications = emp.qualification_id.filtered('qualification')
                if qualifications:
                    rec.employee_qualification = qualifications[0].qualification
                else:
                    rec.employee_qualification = False
            else:
                rec.employee_qualification = False

    @api.depends('target_job_id', 'current_tenure_years', 'required_tenure_years',
                 'latest_pms_score', 'required_pms_score',
                 'required_qualification', 'employee_qualification')
    def _compute_eligibility_flags(self):
        for rec in self:
            # Tenure
            req_tenure = rec.required_tenure_years or 0.0
            curr_tenure = rec.current_tenure_years or 0.0
            rec.tenure_gap = max(0.0, req_tenure - curr_tenure)
            rec.tenure_eligible = 'yes' if curr_tenure >= req_tenure else 'no'

            # PMS
            rec.pms_eligible = 'yes' if (rec.latest_pms_score or 0.0) >= (rec.required_pms_score or 0.0) else 'no'

            # Qualification
            if not rec.required_qualification:
                rec.qualification_eligible = 'na'
            elif rec.employee_qualification:
                # Basic check: if employee has any qualification recorded, mark as 'yes'
                # HR/admin can review manually for exactness
                rec.qualification_eligible = 'yes'
            else:
                rec.qualification_eligible = 'no'

    @api.depends('competency_gap_ids', 'competency_gap_ids.gap',
                 'competency_gap_ids.achievement_status')
    def _compute_competency_summary(self):
        for rec in self:
            gaps = rec.competency_gap_ids
            if not gaps:
                rec.competency_gap_count = 0
                rec.competency_eligible = False
                rec.competency_match_percent = 0.0
                continue
            total = len(gaps)
            gap_count = len(gaps.filtered(lambda g: g.achievement_status == 'below'))
            rec.competency_gap_count = gap_count
            rec.competency_eligible = gap_count == 0
            met = total - gap_count
            rec.competency_match_percent = round((met / total) * 100, 1) if total else 0.0

    @api.depends('tenure_eligible', 'pms_eligible', 'qualification_eligible',
                 'target_job_id')
    def _compute_overall_eligibility(self):
        for rec in self:
            if not rec.target_job_id:
                rec.overall_eligible = 'pending'
                rec.eligibility_summary = _('Please select a Target Job Position to evaluate eligibility.')
                continue

            issues = []
            if rec.tenure_eligible == 'no':
                issues.append(_('Experience: %.1f years remaining') % (rec.tenure_gap or 0.0))
            if rec.pms_eligible == 'no':
                issues.append(_('Performance (PMS): Score %.1f < Required %.1f') % (
                    rec.latest_pms_score, rec.required_pms_score))
            if rec.qualification_eligible == 'no':
                issues.append(_('Qualification: Missing required qualification'))
            # if not rec.competency_eligible:
            #     issues.append(_('Competencies: %d gap(s) identified') % rec.competency_gap_count)

            if not issues:
                rec.overall_eligible = 'eligible'
                rec.eligibility_summary = _('✅ Employee meets all eligibility requirements for this role.')
            else:
                rec.overall_eligible = 'not_eligible'
                rec.eligibility_summary = _('❌ Not Yet Eligible. Gaps to close: %s') % '; '.join(issues)

    # =========================================================================
    # WORKFLOW ACTIONS
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name:
                rec.name = self.env['ir.sequence'].sudo().next_by_code('hr.career.aspiration') or \
                    'CASP-%s' % rec.id
        return records

    def action_submit(self):
        """Employee submits career aspiration for manager review."""
        for rec in self:
            if not rec.target_job_id:
                raise UserError(_('Please select a target role before submitting.'))
            rec.with_context(force_write=True).write({
                'state': 'submitted',
                'submission_date': fields.Date.today(),
            })
            rec.message_post(body=_('Career Aspiration %s submitted for manager review.') % rec.name)
            # Notify the manager
            manager = rec.employee_id.parent_id
            if manager and manager.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Career Aspiration Review: %s') % rec.employee_id.name,
                    note=_('%s has submitted a career aspiration for the role of %s. '
                           'Please review and provide feedback.') % (
                        rec.employee_id.name, rec.target_job_id.name or ''),
                    user_id=manager.user_id.id,
                )

    def action_manager_review(self):
        self.with_context(force_write=True).write({'state': 'manager_review'})

    def action_approve(self):
        """Manager/HR approves the career aspiration and auto-generates IDP."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'approved'})
            rec.message_post(body=_('Career Aspiration %s approved. ICDP development can now begin.') % rec.name)
            
            # Safe auto-generation of empty draft IDP
            # Create a blank IDP for the employee to fill out
            idp = self.env['hr.career.idp'].create({
                'employee_id': rec.employee_id.id,
                'aspiration_id': rec.id,
                'state': 'draft'
            })
            
            rec.message_post(body=_('Draft Individual Career Development Plan (IDP) %s automatically generated.') % idp.name)

            # Notify the employee
            if rec.employee_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Career Aspiration Approved!'),
                    note=_('Your career aspiration for the role of %s has been approved. '
                           'Please work with your manager to finalize your Individual Career Development Plan (ICDP).') % (
                        rec.target_job_id.name or ''),
                    user_id=rec.employee_id.user_id.id,
                )

    def action_put_on_hold(self):
        self.with_context(force_write=True).write({'state': 'on_hold'})

    def action_mark_achieved(self):
        self.with_context(force_write=True).write({'state': 'achieved'})
        for rec in self:
            rec.message_post(body=_('🎉 Congratulations! Career aspiration %s has been marked as Achieved.') % rec.name)

    def action_withdraw(self):
        self.with_context(force_write=True).write({'state': 'withdrawn'})

    def action_compute_gap_analysis(self):
        """
        Recompute the full competency gap analysis.
        Fetches the employee's latest approved competency assessment scores
        and compares them against the target node's required proficiency levels.
        """
        self.ensure_one()
        if not self.target_job_id:
            raise UserError(_('Please select a target role first.'))
        if not self.target_job_id.competency_target_ids:
            raise UserError(_('The selected target role has no competency requirements defined. '
                              'Please ask HR to configure the career path node competencies.'))

        # Clear existing gap lines
        self.competency_gap_ids.unlink()

        employee = self.employee_id
        gap_lines = []

        # Get the employee's latest APPROVED/LOCKED competency assessment
        assessment = self.env['competency.assessment'].search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ['approved', 'locked']),
        ], order='id desc', limit=1)

        for req in self.target_job_id.competency_target_ids:
            current_level_int = 0
            current_level_str = '0'
            # Try to find this competency in the employee's latest assessment
            if assessment:
                asm_line = assessment.line_ids.filtered(
                    lambda l: l.competency_id.id == req.competency_id.id
                )
                if asm_line:
                    current_level_str = asm_line[0].current_level or '1'
                    current_level_int = int(current_level_str)

            required_level_int = int(req.required_proficiency or '1')
            gap_val = required_level_int - current_level_int

            if gap_val < 0:
                achievement_status = 'exceeds'
            elif gap_val == 0:
                achievement_status = 'meets'
            else:
                achievement_status = 'below'

            gap_lines.append({
                'aspiration_id': self.id,
                'competency_id': req.competency_id.id,
                'required_proficiency': req.required_proficiency,
                'current_proficiency': current_level_str if current_level_int > 0 else '0',
                'gap': gap_val,
                'achievement_status': achievement_status,
            })

        self.env['hr.career.aspiration.competency.gap'].create(gap_lines)
        self.message_post(body=_('Gap analysis recomputed. %d competency requirements evaluated.') % len(gap_lines))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gap Analysis Updated'),
                'message': _('%d competency requirements evaluated. Overall eligibility: %s') % (
                    len(gap_lines), dict(self._fields['overall_eligible'].selection).get(self.overall_eligible, '')),
                'type': 'success' if self.overall_eligible == 'eligible' else 'warning',
                'sticky': False,
            },
        }


# class HrCareerAspirationCompetencyGap(models.Model):
#     """
#     Competency Gap Line for a Career Aspiration (FR-TCA-004, FR-CAR-004).
#     Stores the side-by-side comparison of Current vs Required proficiency
#     for each competency required by the target career node.
#     """
#     _name = 'hr.career.aspiration.competency.gap'
#     _description = 'Career Aspiration Competency Gap Line'
#     _order = 'achievement_status desc, competency_id'
#
#     aspiration_id = fields.Many2one(
#         'hr.career.aspiration', string='Career Aspiration',
#         required=True, ondelete='cascade')
#     competency_id = fields.Many2one(
#         'competency.competency', string='Competency', required=True, ondelete='restrict')
#     competency_pillar = fields.Selection(
#         related='competency_id.pillar', string='Pillar', store=True, readonly=True)
#     required_proficiency = fields.Selection([
#         ('1', 'Level 1 - Basic'),
#         ('2', 'Level 2 - Intermediate'),
#         ('3', 'Level 3 - Advanced'),
#         ('4', 'Level 4 - Expert'),
#     ], string='Required Level', required=True)
#     current_proficiency = fields.Selection([
#         ('0', 'Not Assessed'),
#         ('1', 'Level 1 - Basic'),
#         ('2', 'Level 2 - Intermediate'),
#         ('3', 'Level 3 - Advanced'),
#         ('4', 'Level 4 - Expert'),
#     ], string='Current Level')
#     gap = fields.Integer(
#         string='Gap',
#         help='Required minus Current proficiency. Positive value = development gap.')
#     achievement_status = fields.Selection([
#         ('exceeds', 'Exceeds'),
#         ('meets', 'Meets'),
#         ('below', 'Gap / Below Required'),
#     ], string='Status')
#     achievement_badge = fields.Char(
#         string='Status Badge', compute='_compute_badge')
#
#     @api.depends('achievement_status')
#     def _compute_badge(self):
#         map_ = {
#             'exceeds': '✓ Exceeds',
#             'meets': '✓ Meets',
#             'below': '✗ Gap',
#         }
#         for rec in self:
#             rec.achievement_badge = map_.get(rec.achievement_status, '?')

