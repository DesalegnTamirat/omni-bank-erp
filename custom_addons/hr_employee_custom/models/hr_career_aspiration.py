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

    active = fields.Boolean(string='Active', default=True, tracking=True)
    name = fields.Char(string='Reference', readonly=True, copy=False)

    # --- Core fields ---
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=lambda self: self.env.user.employee_id)
    current_job_id = fields.Many2one(
        'hr.job', string='Current Role', related='employee_id.job_id',
        store=True, readonly=True)
    current_department_id = fields.Many2one(
        'hr.department', string='Current Department', related='employee_id.department_id',
        store=True, readonly=True)
    current_grade_id = fields.Many2one(
        'employee.grade', string='Current Grade', compute='_compute_current_grade_id',
        store=True, readonly=True)

    target_job_id = fields.Many2one(
        'hr.job', string='Target Job Position', required=True, tracking=True,
        help='The specific role you are aspiring to reach.')
    target_department_id = fields.Many2one(
        'hr.department', string='Target Department', related='target_job_id.department_id',
        store=True, readonly=True)
    target_job_family = fields.Char(
        string='Job Family / Track', compute='_compute_target_job_family',
        store=True, readonly=True)

    career_interest_type = fields.Selection([
        ('promotion', 'Promotion (Leadership / Higher Grade)'),
        ('lateral', 'Lateral Move (Cross-Functional / Skill Expansion)'),
        ('specialist', 'Technical Specialist / Dual Career Track'),
    ], string='Aspiration Track', default='promotion', required=False, tracking=True)

    target_timeframe = fields.Selection([
        ('short', 'Short-Term (Within 1 Year)'),
        ('medium', 'Medium-Term (1 – 2 Years)'),
        ('long', 'Long-Term (3 – 5 Years)'),
    ], string='Target Time Horizon', default='medium', required=False, tracking=True,
    help='Expected timeframe to prepare for and achieve this career transition (BRD FR-CAR-003).')

    preferred_location = fields.Char(
        string='Preferred Work Location / District',
        help='Preferred geographical location, district, or work location (BRD FR-CAR-003).')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('manager_review', 'Manager Review'),
        ('approved', 'Approved / Active'),
        ('cancelled', 'Cancelled'),
        ('achieved', 'Achieved'),
        ('withdrawn', 'Withdrawn'),
    ], string='Status', default='draft', tracking=True)
    submission_date = fields.Date(string='Submission Date')
    manager_id = fields.Many2one(
        'hr.employee', string='Reviewing Manager',
        related='employee_id.parent_id', store=True, readonly=True)
    notes = fields.Text(string='Career Motivation & Goals', required=True)
    company_id = fields.Many2one('res.company', string='Company',
                                  default=lambda self: self.env.company)

    # --- Career Discussion Template (FR-CDP-004) ---
    career_discussion_date = fields.Date(string='Discussion Date')
    career_discussion_summary = fields.Text(string='Discussion Summary')

    # --- On Hold Tracking (Legacy - kept for data compatibility) ---
    hold_reason = fields.Text(string='Reason for Hold', tracking=True)
    hold_reason_category = fields.Selection([
        ('tenure', 'Tenure / Experience Requirement Not Met'),
        ('performance', 'Performance Improvement Needed (PMS)'),
        ('reorg', 'Organizational Restructuring / Department Readiness'),
        ('project', 'Priority Project Commitment in Current Role'),
        ('other', 'Other Reason'),
    ], string='Hold Category', tracking=True)
    hold_date = fields.Date(string='Date Placed on Hold', tracking=True)
    hold_by_user_id = fields.Many2one('res.users', string='Placed on Hold By', tracking=True)

    # --- Cancellation Tracking ---
    cancel_reason = fields.Selection([
        ('tenure', 'Tenure / Experience Requirement Not Met'),
        ('performance', 'Performance Improvement Needed (PMS)'),
        ('reorg', 'Organizational Restructuring / Department Readiness'),
        ('project', 'Priority Project Commitment in Current Role'),
        ('not_aligned', 'Career Goal No Longer Aligned with Organizational Needs'),
        ('other', 'Other Reason'),
    ], string='Cancellation Reason', tracking=True)
    cancel_justification = fields.Text(string='Cancellation Justification', tracking=True)
    cancel_date = fields.Date(string='Cancellation Date', tracking=True)
    cancel_by_user_id = fields.Many2one('res.users', string='Cancelled By', tracking=True)

    idp_count = fields.Integer(string='IDPs', compute='_compute_idp_count')

    # Computed fields to control form access
    is_owner = fields.Boolean(compute='_compute_is_owner', string='Is Owner')
    is_manager_user = fields.Boolean(compute='_compute_is_manager_user', string='Is Manager User')

    @api.depends('employee_id')
    @api.depends_context('uid')
    def _compute_is_owner(self):
        for rec in self:
            current_emp = self.env.user.employee_id
            rec.is_owner = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id) or
                (not rec.employee_id and not rec.id)
            )

    @api.depends('manager_id', 'employee_id')
    @api.depends_context('uid')
    def _compute_is_manager_user(self):
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        is_hr = (
            self.env.user.has_group('hr_employee_custom.group_career_path_admin') or
            self.env.user.has_group('hr_employee_custom.group_career_path_officer') or
            self.env.user.has_group('hr.group_hr_manager')
        )
        for rec in self:
            current_emp = self.env.user.employee_id
            # An employee viewing or creating their own aspiration is ALWAYS self
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id) or
                (not rec.employee_id and not rec.id)
            )
            if is_self:
                # An employee can NEVER see or edit the career discussion on their own aspiration
                rec.is_manager_user = False
                continue

            mgr_emp = rec.sudo().manager_id or (rec.employee_id and rec.sudo().employee_id.parent_id)
            is_mgr = bool(mgr_emp and mgr_emp.user_id == self.env.user)
            is_coach = bool(rec.employee_id and rec.sudo().employee_id.coach_id and rec.sudo().employee_id.coach_id.user_id == self.env.user)
            is_dept_mgr = bool(rec.employee_id and rec.sudo().employee_id.department_id and rec.sudo().employee_id.department_id.manager_id and rec.sudo().employee_id.department_id.manager_id.user_id == self.env.user)
            is_line_mgr_group = self.env.user.has_group('hr_employee_custom.group_career_path_manager')

            rec.is_manager_user = bool(is_mgr or is_coach or is_dept_mgr or is_hr or is_admin or is_line_mgr_group)

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

    @api.depends('employee_id')
    def _compute_current_grade_id(self):
        for rec in self:
            emp = rec.employee_id
            grade = False
            if emp:
                if hasattr(emp, 'job_grade') and emp.job_grade:
                    grade = emp.job_grade
                elif hasattr(emp, 'grade_id') and emp.grade_id:
                    if getattr(emp.grade_id, '_name', '') == 'employee.grade':
                        grade = emp.grade_id
                    else:
                        g_name = getattr(emp.grade_id, 'name', '') or getattr(emp.grade_id, 'display_name', '')
                        if g_name:
                            grade = self.env['employee.grade'].search([('grade_name', '=', g_name)], limit=1)
            rec.current_grade_id = grade

    @api.depends('target_job_id')
    def _compute_target_job_family(self):
        for rec in self:
            if rec.target_job_id:
                job = rec.target_job_id
                if hasattr(job, 'job_family_id') and job.job_family_id:
                    rec.target_job_family = job.job_family_id.name
                elif job.department_id:
                    rec.target_job_family = f"{job.department_id.name} Track"
                else:
                    rec.target_job_family = 'Banking Operations'
            else:
                rec.target_job_family = False

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
                if qualifications and qualifications[0].qualification:
                    q = qualifications[0].qualification
                    rec.employee_qualification = getattr(q, 'qualification', False) or getattr(q, 'name', False) or q.display_name or str(q)
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
                rec.eligibility_summary = _('Employee meets all eligibility requirements for this role.')
            else:
                rec.overall_eligible = 'not_eligible'
                rec.eligibility_summary = _('Gaps to close: %s') % '; '.join(issues)


    # =========================================================================
    # SUDO OVERRIDES — allow all employees to read Career Aspiration records
    # without being blocked by hr.employee record rules on related fields.
    # =========================================================================

    def read(self, fields=None, load='_classic_read'):
        return super(HrCareerAspiration, self.sudo()).read(fields, load)

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **kwargs):
        return super(HrCareerAspiration, self.sudo()).search_read(
            domain=domain, fields=fields, offset=offset, limit=limit, order=order, **kwargs)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        return super(HrCareerAspiration, self.sudo()).web_search_read(
            domain=domain, specification=specification,
            offset=offset, limit=limit, order=order, count_limit=count_limit)

    # =========================================================================
    # WORKFLOW ACTIONS
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('hr.career.aspiration') or '/'
        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name == '/':
                year = fields.Date.today().year
                rec.name = f"BB-CASP-{year}-{rec.id:04d}"
        return records

    def write(self, vals):
        discussion_fields = {'career_discussion_date', 'career_discussion_summary'}
        if discussion_fields & set(vals.keys()) and not self.env.su:
            is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
            if not is_admin:
                for rec in self:
                    if not rec.is_manager_user:
                        raise ValidationError(_("Only reviewing managers and HR administrators can record or update Career Discussion details."))
        return super().write(vals)

    def action_submit(self):
        """Employee submits career aspiration for manager review."""
        for rec in self:
            if not rec.target_job_id:
                raise UserError(_('Please select a target role before submitting.'))
            if not rec.notes or not rec.notes.strip():
                raise UserError(_('Career Motivation & Goals is mandatory. Please provide your career motivation and goals before submitting.'))
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
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        current_emp = self.env.user.employee_id
        for rec in self:
            # Maker-Checker Rule: Employee cannot approve their own aspiration
            is_self = bool(
                (rec.employee_id and rec.sudo().employee_id.user_id == self.env.user) or
                (rec.employee_id and current_emp and rec.employee_id.id == current_emp.id)
            )
            if is_self and not is_admin:
                raise ValidationError(_("Maker-Checker Violation: You cannot approve your own Career Aspiration. It must be reviewed and approved by your Direct Supervisor / Line Manager or HR."))
            rec.with_context(force_write=True).write({'state': 'approved'})
            rec.message_post(body=_('Career Aspiration %s approved. ICDP development can now begin.') % rec.name)
            
            # Safe auto-generation of empty draft IDP
            # Create a blank IDP for the employee to fill out
            idp = self.env['hr.career.idp'].create({
                'employee_id': rec.employee_id.id,
                'aspiration_id': rec.id,
                'target_job_id': rec.target_job_id.id,
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

    def action_cancel_aspiration(self):
        """Manager cancels the career aspiration with justification (via wizard)."""
        self.ensure_one()
        return {
            'name': _('Cancel Career Aspiration'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.career.aspiration.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_aspiration_id': self.id,
            }
        }

    def action_resume(self):
        """Resume aspiration from On Hold back to Submitted for review."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'submitted'})
            rec.message_post(body=_('Career Aspiration %s resumed from On Hold back to Submitted for Review.') % rec.name)

    def action_withdraw(self):
        self.with_context(force_write=True).write({'state': 'withdrawn'})

    def action_mark_achieved(self):
        """Mark career aspiration as achieved when employee reaches the target role."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'achieved'})
            rec.message_post(body=_('Career Aspiration %s marked as achieved!') % rec.name)

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

    def unlink(self):
        is_admin = self.env.is_admin() or self.env.user.has_group('base.group_system') or self.env.user.has_group('hr.group_hr_manager')
        for rec in self:
            rec_sudo = rec.sudo()
            if rec_sudo.state == 'draft':
                if not (rec_sudo.create_uid == self.env.user or is_admin):
                    raise UserError(_(
                        "Draft career aspiration '%s' can only be deleted by its creator (%s) or an HR Administrator."
                    ) % (rec_sudo.name, rec_sudo.create_uid.name or 'unknown'))
            else:
                state_label = dict(rec_sudo._fields['state'].selection).get(rec_sudo.state, rec_sudo.state)
                raise UserError(_(
                    "Career aspiration '%s' in state '%s' cannot be permanently deleted. "
                    "Please archive this record (Action > Archive) to maintain career history and audit compliance."
                ) % (rec_sudo.name, state_label))
        return super(HrCareerAspiration, self.sudo()).unlink()


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

