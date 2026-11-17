# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_datetime, format_date
from markupsafe import Markup
import base64
import os
import logging

_logger = logging.getLogger(__name__)


class DisciplineCommitteeAttendance(models.Model):
    """Structured Attendance Line for Committee Panel Members during Hearing."""
    _name = 'discipline.committee.attendance'
    _description = 'Disciplinary Committee Member Attendance'
    _order = 'role_order asc, id asc'

    meeting_id = fields.Many2one('discipline.committee.meeting', string='Meeting', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Committee Member', required=True)
    role = fields.Selection([
        ('chair', 'Committee Chairperson (CPCO)'),
        ('secretary', 'Committee Secretary (POMD)'),
        ('legal', 'Legal Directorate Member'),
        ('director', 'Respective Directorate Director'),
        ('union', 'Labour Union Representative'),
        ('ad_hoc', 'Ad-hoc / Designated Member'),
    ], string='Panel Role', required=True, default='ad_hoc')
    role_order = fields.Integer(string='Sort Order', default=10)
    is_present = fields.Boolean(string='Present', default=False)
    attendance_status = fields.Selection([
        ('present', 'Present in Person'),
        ('absent', 'Absent (Unexcused)'),
        ('excused', 'Excused / Prior Notice'),
        ('represented', 'Represented by Alternate'),
    ], string='Attendance Status', default='absent')
    remarks = fields.Char(string='Remarks / Representation Note')

    @api.onchange('is_present')
    def _onchange_is_present(self):
        if self.is_present:
            self.attendance_status = 'present'
        elif self.attendance_status == 'present':
            self.attendance_status = 'absent'


class DisciplineCommitteeMeeting(models.Model):
    _name = 'discipline.committee.meeting'
    _description = 'Disciplinary Committee Meeting & Hearing'
    _inherit = ['mail.thread']
    _order = 'meeting_date desc, id desc'

    name = fields.Char(string='Meeting Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one(
        'discipline.case',
        string='Disciplinary Case',
        required=True,
        ondelete='cascade',
        tracking=True,
        domain="[('state', '=', 'committee_review'), ('has_active_committee_meeting', '=', False), ('has_completed_committee_meeting', '=', False)]"
    )
    is_case_readonly = fields.Boolean(
        string='Is Case Readonly',
        default=lambda self: bool(self.env.context.get('default_case_id')),
        help='Indicates if the case field should be readonly (e.g. when launched from a case).'
    )
    is_case_enforced = fields.Boolean(
        string='Is Case Enforced',
        compute='_compute_is_case_enforced',
        help='Indicates whether the linked disciplinary case is already enforced.'
    )
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', related='case_id.employee_id', store=True, readonly=True)

    @api.depends('case_id', 'case_id.state')
    def _compute_is_case_enforced(self):
        for rec in self:
            rec.is_case_enforced = bool(rec.case_id and rec.case_id.state in ('enforced', 'closed', 'appealed'))
    
    # Case & Misconduct Context (Read-Only Brief)
    job_id = fields.Many2one('hr.job', string='Job Title', related='case_id.job_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department / Branch', related='case_id.department_id', store=True, readonly=True)
    staff_category = fields.Selection(string='Staff Category', related='case_id.staff_category', store=True, readonly=True)
    offense_id = fields.Many2one('discipline.offense', string='Misconduct Clause / Offense', related='case_id.offense_id', store=True, readonly=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='case_id.offense_category_id', store=True, readonly=True)
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', related='case_id.severity_level_id', store=True, readonly=True)
    severity_level = fields.Char(string='Severity Classification', related='case_id.severity_level', store=True, readonly=True)
    incident_date = fields.Date(string='Misconduct Incident Date', related='case_id.incident_date', store=True, readonly=True)
    
    # Audit Investigation Brief
    investigation_id = fields.Many2one('discipline.investigation', string='Audit Investigation Reference', compute='_compute_investigation_brief', store=True)
    investigation_outcome = fields.Selection(string='Audit Finding Outcome', related='investigation_id.finding_outcome', readonly=True)
    financial_loss_amount = fields.Float(string='Financial Loss Amount (ETB)', related='investigation_id.financial_loss_amount', readonly=True)

    @api.depends('case_id', 'case_id.investigation_ids')
    def _compute_investigation_brief(self):
        for rec in self:
            rec.investigation_id = rec.case_id.investigation_ids[:1].id if rec.case_id and rec.case_id.investigation_ids else False

    # Meeting Schedule & Logistics (In-Person Hearing)
    meeting_date = fields.Date(string='Meeting Date', required=True, tracking=True)
    location = fields.Char(string='Hearing Room / In-Person Venue', required=True, tracking=True)
    is_rescheduled = fields.Boolean(string='Is Rescheduled', default=False, tracking=True)
    is_meeting_day_reached = fields.Boolean(
        string='Is Meeting Day Reached',
        compute='_compute_is_meeting_day_reached',
        help='Indicates whether today is on or after the scheduled meeting date.'
    )

    # Designated Statutory Panel Roles
    @api.model
    def _default_committee_chair_id(self):
        EmpModel = self.env['hr.employee'].sudo()
        u = EmpModel.get_cpco_user()
        return u.id if u else False

    @api.model
    def _default_pomd_secretary_id(self):
        EmpModel = self.env['hr.employee'].sudo()
        u = EmpModel.get_secretary_user()
        return u.id if u else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        EmpModel = self.env['hr.employee'].sudo()
        if 'committee_chair_id' in fields_list and not res.get('committee_chair_id'):
            cpco = EmpModel.get_cpco_user()
            if cpco:
                res['committee_chair_id'] = cpco.id
        if 'pomd_secretary_id' in fields_list and not res.get('pomd_secretary_id'):
            sec = EmpModel.get_secretary_user()
            if sec:
                res['pomd_secretary_id'] = sec.id
        if 'is_case_readonly' in fields_list:
            res['is_case_readonly'] = bool(self.env.context.get('default_case_id'))
        return res

    committee_chair_id = fields.Many2one('res.users', string='Committee Chair Man', default=_default_committee_chair_id, required=True, tracking=True)
    can_begin_hearing = fields.Boolean(
        string='Can Begin Hearing',
        compute='_compute_can_begin_hearing',
        help='Only the Committee Chair Man (CPCO) or Administrator has the statutory mandate to begin the hearing session.'
    )
    can_schedule_hearing = fields.Boolean(
        string='Can Schedule/Reschedule Hearing',
        compute='_compute_can_schedule_hearing',
        help='Scheduling and rescheduling committee hearings is the statutory mandate of the Committee Secretary (POMD Director).'
    )
    can_submit_to_chair = fields.Boolean(
        string='Can Submit to Chair',
        compute='_compute_can_submit_to_chair',
        help='The Committee Secretary has the statutory mandate to record minutes and submit proceedings to the Chair Man.'
    )
    can_submit_to_ceo = fields.Boolean(
        string='Can Submit to CEO',
        compute='_compute_can_submit_to_ceo',
        help='Only the Committee Chair Man (CPCO) or Administrator has the mandate to review and submit the recommendation to the CEO.'
    )
    can_return_to_secretary = fields.Boolean(
        string='Can Return to Secretary',
        compute='_compute_can_return_to_secretary',
        help='Only the Committee Chair Man (CPCO) or Administrator has the authority to return proceedings for revision.'
    )
    respective_director_id = fields.Many2one('res.users', string='Director of Respective Office', tracking=True)
    legal_director_id = fields.Many2one('res.users', string='Legal Directorate Member', tracking=True)
    pomd_secretary_id = fields.Many2one('res.users', string='Committee Secretary', default=_default_pomd_secretary_id, tracking=True)
    include_labour_union = fields.Boolean(
        string='Include Labour Union Representative',
        default=False,
        tracking=True,
        help='Indicates whether a Labour Union Representative is included in this committee hearing. Defaults based on employee union membership, and can be toggled by the Secretary.'
    )
    labour_union_rep_id = fields.Many2one('res.users', string='Labour Union Representative', tracking=True)
    member_ids = fields.Many2many('res.users', 'discipline_committee_members_rel', 'meeting_id', 'user_id', string='Committee Members', required=True)

    # Attendance & Quorum Requirements
    attendance_ids = fields.One2many('discipline.committee.attendance', 'meeting_id', string='Panel Attendance')
    total_expected_members = fields.Integer(string='Total Expected Members', compute='_compute_quorum', store=True)
    present_members_count = fields.Integer(string='Members Present Count', compute='_compute_quorum', store=True, tracking=True)
    required_quorum_percentage = fields.Float(string='Required Quorum (%)', default=50.0, required=True, help='Minimum percentage of members present required for valid decision')
    is_quorum_met = fields.Boolean(string='Quorum Validated', compute='_compute_quorum', store=True, tracking=True)

    # Deliberations, Minutes & Employee Defense (Recorded by Secretary / Chairman)
    agenda = fields.Html(string='Meeting Agenda & Points of Order')
    employee_defense_summary = fields.Html(string='Summary of Employee Defense & Statements')
    meeting_minutes = fields.Html(string='Official Hearing Deliberations & Findings')

    # Document & Evidence Attachments
    signed_minutes_file = fields.Binary(string='Official Signed Meeting Minutes (PDF)', attachment=True)
    signed_minutes_filename = fields.Char(string='Signed Minutes Filename')
    attendance_sheet_file = fields.Binary(string='Signed Attendance Sheet (PDF)', attachment=True)
    attendance_sheet_filename = fields.Char(string='Attendance Sheet Filename')
    employee_statement_file = fields.Binary(string='Employee Written Defense / Statement', attachment=True)
    employee_statement_filename = fields.Char(string='Statement Filename')

    # Recommendation & Sanction Decision
    final_recommendation = fields.Selection([
        ('dismissal', 'Recommend Dismissal'),
        ('final_warning', 'Recommend Final Written Warning'),
        ('second_warning', 'Recommend Second Written Warning'),
        ('first_warning', 'Recommend First Written Warning'),
        ('verbal_warning', 'Recommend Verbal Warning'),
        ('demotion', 'Recommend Demotion'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
        ('further_investigation', 'Require Further Investigation'),
    ], string='Committee Recommendation (Summary)', tracking=True)

    recommended_penalty_type = fields.Selection([
        ('verbal_warning', 'Verbal Warning'),
        ('first_warning_penalty', '1st Written Warning'),
        ('second_warning_penalty', '2nd Written Warning'),
        ('final_warning_penalty', 'Final Written Warning'),
        ('dismissal', 'Dismissal / Termination of Employment'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
    ], string='Recommended Disciplinary Measure', tracking=True)

    is_demotion_recommended = fields.Boolean(
        string='Include Demotion in Recommendation',
        default=False,
        tracking=True,
        help='When enabled, the committee recommends demotion as an auxiliary sanction in addition to the warning measure. Applicable strictly to managerial staff.'
    )

    @api.constrains('is_demotion_recommended', 'staff_category')
    def _check_demotion_managerial_only(self):
        for rec in self:
            if rec.is_demotion_recommended and rec.staff_category != 'managerial':
                raise ValidationError(_(
                    "Demotion Restriction: Demotion is strictly applicable only to managerial staff positions per Bank policy. "
                    "Non-managerial staff are not eligible for demotion sanctions."
                ))

    demotion_target_job_id = fields.Many2one(
        'hr.job',
        string='Demotion Target Job Position (Legacy)',
        tracking=True,
        help='Target job position when demotion is recommended.'
    )

    recommended_penalty_percentage = fields.Float(string='Recommended Salary Deduction Rate (%)', tracking=True)
    recommended_fine_days = fields.Integer(string='Recommended Salary Fine (Days)', tracking=True)
    recommended_warning_validity_days = fields.Integer(string='Warning Active Validity (Days)', default=0, tracking=True)

    @api.model
    def get_normal_scenario_values(self, pen_type, staff_category, case=None):
        """Calculate standard statutory policy values for validity days, deduction rate, and fine days."""
        is_managerial = (staff_category == 'managerial')
        validity_days = 0
        penalty_pct = 0.0
        fine_days = 0

        if not pen_type or pen_type in ('dismissal', 'exonerate'):
            return {
                'recommended_warning_validity_days': 0,
                'recommended_penalty_percentage': 0.0,
                'recommended_fine_days': 0,
            }

        # 1. Standard statutory policy defaults
        if pen_type == 'verbal_warning':
            validity_days = 30
            penalty_pct = 0.0
            fine_days = 0
        elif pen_type == 'first_warning_penalty':
            validity_days = 90
            penalty_pct = 0.0 if is_managerial else 5.0
            fine_days = 1 if is_managerial else 0
        elif pen_type == 'second_warning_penalty':
            validity_days = 180
            penalty_pct = 0.0 if is_managerial else 10.0
            fine_days = 2 if is_managerial else 0
        elif pen_type == 'final_warning_penalty':
            validity_days = 365
            penalty_pct = 0.0 if is_managerial else 20.0
            fine_days = 3 if is_managerial else 0

        # 2. Check case offense rules / repetition line overrides if configured
        if case and case.offense_id:
            off = case.offense_id
            if off.penalty_mode == 'repetition_escalation' and off.line_ids:
                match_line = off.line_ids.filtered(lambda l: l.punishment_type == pen_type)
                if not match_line and case.occurrence_count:
                    match_line = off.line_ids.filtered(lambda l: l.occurrence_number == case.occurrence_count)
                if match_line:
                    line = match_line[0]
                    if is_managerial:
                        fine_days = int(line.managerial_fine_days if line.managerial_fine_days else (line.fine_days or fine_days))
                        penalty_pct = line.managerial_penalty_pct or 0.0
                    else:
                        penalty_pct = line.non_managerial_penalty_pct if line.non_managerial_penalty_pct else (line.penalty_percentage or penalty_pct)
                        fine_days = 0
                    if line.warning_validity_months:
                        validity_days = line.warning_validity_months * 30
            elif off.penalty_mode == 'article_override':
                if is_managerial or off.staff_category == 'managerial':
                    fine_days = int(off.custom_fine_days or getattr(off, 'fine_days', 0.0) or fine_days)
                    penalty_pct = off.custom_penalty_percentage or 0.0
                else:
                    penalty_pct = off.custom_penalty_percentage or getattr(off, 'penalty_percentage', 0.0) or penalty_pct
                    fine_days = 0
                if off.custom_warning_validity_months:
                    validity_days = off.custom_warning_validity_months * 30
            elif not validity_days and off.severity_level_id and off.severity_level_id.active_duration_days:
                validity_days = off.severity_level_id.active_duration_days

        # Strict segregation
        if is_managerial:
            penalty_pct = 0.0
        else:
            fine_days = 0

        return {
            'recommended_warning_validity_days': validity_days,
            'recommended_penalty_percentage': penalty_pct,
            'recommended_fine_days': fine_days,
        }

    @api.onchange('recommended_penalty_type', 'staff_category')
    def _onchange_recommended_penalty_type(self):
        """Auto-sync normal policy scenario for warning validity, salary deduction rate, and fine days."""
        if self.staff_category != 'managerial' or self.recommended_penalty_type in ('dismissal', 'exonerate'):
            self.is_demotion_recommended = False

        if self.recommended_penalty_type:
            vals = self.get_normal_scenario_values(self.recommended_penalty_type, self.staff_category, self.case_id)
            self.recommended_warning_validity_days = vals['recommended_warning_validity_days']
            self.recommended_penalty_percentage = vals['recommended_penalty_percentage']
            self.recommended_fine_days = vals['recommended_fine_days']
        else:
            self.recommended_warning_validity_days = 0
            self.recommended_penalty_percentage = 0.0
            self.recommended_fine_days = 0

    def action_sync_policy_defaults(self):
        """Re-sync Warning Validity and Deduction/Fine rates to statutory policy defaults."""
        for rec in self:
            if rec.recommended_penalty_type:
                vals = self.get_normal_scenario_values(rec.recommended_penalty_type, rec.staff_category, rec.case_id)
                rec.write(vals)
        return True
    recommendation_rationale = fields.Html(string='Deliberation Verdict Rationale & Policy Justification')
    chairman_review_notes = fields.Html(
        string='Chairman Endorsement Remarks',
        tracking=True,
        help='Official comments or endorsement notes recorded by the Committee Chair Man prior to CEO submission.'
    )
    chair_signature = fields.Binary(
        string='Chairperson Digital Signature',
        attachment=True,
        tracking=False,
        help='Digital signature of the Disciplinary Committee Chairperson / Enforcing Executive.'
    )

    # Member Voting
    vote_ids = fields.One2many('discipline.committee.vote', 'meeting_id', string='Member Votes')
    in_favor_count = fields.Integer(string='Votes In Favor', compute='_compute_vote_counts', store=True)
    against_count = fields.Integer(string='Votes Against', compute='_compute_vote_counts', store=True)
    abstain_count = fields.Integer(string='Abstentions', compute='_compute_vote_counts', store=True)

    # Streamlined 5-Stage Lifecycle
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Session'),
        ('chair_review', 'Chairman Review'),
        ('completed', 'Submitted to CEO'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.depends_context('uid')
    @api.depends('committee_chair_id', 'pomd_secretary_id')
    def _compute_can_begin_hearing(self):
        current_user = self.env.user
        is_cpco = current_user.has_group('discipline_management.group_discipline_cpco')
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system') or self.env.su
        for rec in self:
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == current_user)
            # Chairman (CPCO) has exclusive mandate to begin meeting; Secretary is excluded
            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == current_user)
            if is_admin:
                rec.can_begin_hearing = True
            elif is_chair:
                rec.can_begin_hearing = True
            elif is_cpco and not is_sec:
                rec.can_begin_hearing = True
            else:
                rec.can_begin_hearing = False

    @api.depends_context('uid')
    @api.depends('pomd_secretary_id', 'committee_chair_id')
    def _compute_can_schedule_hearing(self):
        current_user = self.env.user
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system') or self.env.su
        for rec in self:
            if is_admin:
                rec.can_schedule_hearing = True
                continue

            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == current_user)
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == current_user)
            is_pomd = (current_user.has_group('discipline_management.group_discipline_pomd') or 
                       current_user.has_group('discipline_management.group_discipline_pomd_director'))
            is_cpco = current_user.has_group('discipline_management.group_discipline_cpco')

            # The Chairman (CPCO) is strictly forbidden from scheduling/rescheduling
            if is_chair:
                rec.can_schedule_hearing = False
            elif is_sec:
                rec.can_schedule_hearing = True
            elif is_pomd and not is_cpco:
                rec.can_schedule_hearing = True
            else:
                rec.can_schedule_hearing = False

    @api.depends_context('uid')
    @api.depends('state', 'pomd_secretary_id', 'committee_chair_id')
    def _compute_can_submit_to_chair(self):
        current_user = self.env.user
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system') or self.env.su
        for rec in self:
            if rec.state != 'in_progress':
                rec.can_submit_to_chair = False
                continue
            if is_admin:
                rec.can_submit_to_chair = True
                continue
            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == current_user)
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == current_user)
            is_pomd = (current_user.has_group('discipline_management.group_discipline_pomd') or 
                       current_user.has_group('discipline_management.group_discipline_pomd_director'))
            if is_chair:
                rec.can_submit_to_chair = False
            elif is_sec or is_pomd:
                rec.can_submit_to_chair = True
            else:
                rec.can_submit_to_chair = False

    @api.depends_context('uid')
    @api.depends('state', 'committee_chair_id', 'pomd_secretary_id')
    def _compute_can_submit_to_ceo(self):
        current_user = self.env.user
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system') or self.env.su
        is_cpco = current_user.has_group('discipline_management.group_discipline_cpco')
        for rec in self:
            if rec.state != 'chair_review':
                rec.can_submit_to_ceo = False
                continue
            if is_admin:
                rec.can_submit_to_ceo = True
                continue
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == current_user)
            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == current_user)
            if is_chair:
                rec.can_submit_to_ceo = True
            elif is_cpco and not is_sec:
                rec.can_submit_to_ceo = True
            else:
                rec.can_submit_to_ceo = False

    @api.depends_context('uid')
    @api.depends('state', 'committee_chair_id', 'pomd_secretary_id')
    def _compute_can_return_to_secretary(self):
        current_user = self.env.user
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system') or self.env.su
        is_cpco = current_user.has_group('discipline_management.group_discipline_cpco')
        for rec in self:
            if rec.state != 'chair_review':
                rec.can_return_to_secretary = False
                continue
            if is_admin:
                rec.can_return_to_secretary = True
                continue
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == current_user)
            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == current_user)
            if is_chair:
                rec.can_return_to_secretary = True
            elif is_cpco and not is_sec:
                rec.can_return_to_secretary = True
            else:
                rec.can_return_to_secretary = False

    @api.depends('meeting_date')
    def _compute_is_meeting_day_reached(self):
        for rec in self:
            today = fields.Date.context_today(rec)
            rec.is_meeting_day_reached = bool(rec.meeting_date and today >= rec.meeting_date)

    @api.depends('signed_minutes_file', 'state', 'member_ids', 'attendance_ids.is_present')
    def _compute_quorum(self):
        for rec in self:
            expected = len(rec.member_ids) or 5
            rec.total_expected_members = expected
            # Panel member signatures on official meeting minutes serve as formal attendance and quorum
            if rec.signed_minutes_file or rec.state in ('chair_review', 'completed'):
                rec.is_quorum_met = True
                rec.present_members_count = expected
            elif rec.attendance_ids:
                present_count = len(rec.attendance_ids.filtered(lambda a: a.is_present))
                rec.present_members_count = present_count
                rec.is_quorum_met = (present_count / expected * 100.0 >= rec.required_quorum_percentage) if expected else False
            else:
                rec.present_members_count = expected if rec.state not in ('draft', 'scheduled') else 0
                rec.is_quorum_met = (rec.state not in ('draft', 'scheduled'))

    @api.depends('vote_ids.vote')
    def _compute_vote_counts(self):
        for rec in self:
            rec.in_favor_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'in_favor'))
            rec.against_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'against'))
            rec.abstain_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'abstain'))

    @api.onchange('case_id')
    def _onchange_case_id_populate_committee(self):
        """Auto-populate the 5 mandatory committee roles and attendance matrix."""
        if self.case_id and self.case_id.sudo().employee_id:
            case = self.case_id.sudo()
            emp = case.employee_id
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            ceo_user_id = ceo_user.id if ceo_user else False
            
            # 1. Chairperson: CPCO
            self.committee_chair_id = EmpModel.get_cpco_user()

            # 2. Member: Respective Directorate Director (Case Initiator / Reporting Director who escalated, never CEO)
            resp_dir_user = False
            if case.director_id and case.director_id.id != ceo_user_id:
                resp_dir_user = case.director_id
            elif case.reported_by_id and case.reported_by_id.sudo().user_id and case.reported_by_id.sudo().user_id.id != ceo_user_id:
                resp_dir_user = case.reported_by_id.sudo().user_id
            elif emp and emp.department_id and emp.department_id.sudo().manager_id and emp.department_id.sudo().manager_id.sudo().user_id:
                mgr_u = emp.department_id.sudo().manager_id.sudo().user_id
                if mgr_u.id != ceo_user_id:
                    resp_dir_user = mgr_u
            if not resp_dir_user and emp:
                for sup in emp.sudo().get_supervisor_chain():
                    if sup.sudo().user_id and sup.sudo().user_id.id != ceo_user_id:
                        if sup.sudo().executive_level in ('director', 'chief') or 'director' in (sup.sudo().job_id.name or '').lower():
                            resp_dir_user = sup.sudo().user_id
                            break
            self.respective_director_id = resp_dir_user or False

            # 3. Member: Legal Directorate Representative
            self.legal_director_id = EmpModel.get_legal_user()

            # 4. Member & Secretary: POMD
            self.pomd_secretary_id = EmpModel.get_secretary_user()

            # 5. Member: Labour Union Representative (Auto-ticked if employee is a union member; Secretary can toggle)
            is_union = bool(getattr(emp, 'member_of_labour_union', False) or getattr(emp, 'union_member', False))
            self.include_labour_union = is_union
            self.labour_union_rep_id = EmpModel.get_union_user() if is_union else False

            self._sync_panel_attendance_matrix()

            # Auto-sync recommendation and normal scenario values from Case
            if not self.recommended_penalty_type:
                case_punish = case.punishment_type or case.original_punishment_type
                if case_punish in dict(self._fields['recommended_penalty_type'].selection):
                    self.recommended_penalty_type = case_punish

            if self.recommended_penalty_type:
                norm_vals = self.get_normal_scenario_values(self.recommended_penalty_type, self.staff_category or case.staff_category, case)
                self.recommended_warning_validity_days = norm_vals['recommended_warning_validity_days']
                self.recommended_penalty_percentage = norm_vals['recommended_penalty_percentage']
                self.recommended_fine_days = norm_vals['recommended_fine_days']

    @api.onchange('include_labour_union')
    def _onchange_include_labour_union(self):
        """Toggle Labour Union Representative inclusion dynamically based on checkbox."""
        EmpModel = self.env['hr.employee'].sudo()
        if self.include_labour_union:
            if not self.labour_union_rep_id:
                self.labour_union_rep_id = EmpModel.get_union_user()
        else:
            self.labour_union_rep_id = False
        self._sync_panel_attendance_matrix()

    @api.onchange('committee_chair_id', 'pomd_secretary_id', 'respective_director_id', 'legal_director_id', 'labour_union_rep_id')
    def _onchange_panel_officers(self):
        """Dynamically update attendance matrix whenever any panel officer is modified."""
        self._sync_panel_attendance_matrix()

    def _sync_panel_attendance_matrix(self):
        """Synchronize the panel officers into member_ids and attendance lines without duplicate users."""
        for rec in self:
            role_map = [
                ('chair', 1, rec.committee_chair_id),
                ('secretary', 2, rec.pomd_secretary_id),
                ('legal', 3, rec.legal_director_id),
                ('director', 4, rec.respective_director_id),
            ]
            if rec.include_labour_union and rec.labour_union_rep_id:
                role_map.append(('union', 5, rec.labour_union_rep_id))

            members = []
            att_lines = []
            seen_user_ids = set()
            for r_code, r_order, u in role_map:
                if u and u.id not in seen_user_ids:
                    seen_user_ids.add(u.id)
                    members.append(u.id)
                    att_lines.append((0, 0, {
                        'user_id': u.id,
                        'role': r_code,
                        'role_order': r_order,
                        'is_present': False,
                        'attendance_status': 'absent',
                    }))
            rec.sudo().member_ids = [(6, 0, members)]
            rec.sudo().attendance_ids = [(5, 0, 0)] + att_lines

    @api.model_create_multi
    def create(self, vals_list):
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        ceo_user_id = ceo_user.id if ceo_user else False

        def _to_id(obj):
            if not obj:
                return False
            if isinstance(obj, int):
                return obj
            if hasattr(obj, 'id'):
                return obj.id
            return False

        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.committee.meeting') or _('New')
            
            case_id = vals.get('case_id')
            case = self.env['discipline.case'].browse(case_id).sudo() if case_id else False
            emp = case.employee_id if case else False

            if not vals.get('committee_chair_id'):
                vals['committee_chair_id'] = _to_id(EmpModel.get_cpco_user())
            else:
                vals['committee_chair_id'] = _to_id(vals.get('committee_chair_id'))

            if not vals.get('pomd_secretary_id'):
                vals['pomd_secretary_id'] = _to_id(EmpModel.get_secretary_user())
            else:
                vals['pomd_secretary_id'] = _to_id(vals.get('pomd_secretary_id'))

            if not vals.get('legal_director_id'):
                vals['legal_director_id'] = _to_id(EmpModel.get_legal_user())
            else:
                vals['legal_director_id'] = _to_id(vals.get('legal_director_id'))

            if 'include_labour_union' not in vals:
                is_union = bool(emp and (getattr(emp, 'member_of_labour_union', False) or getattr(emp, 'union_member', False)))
                vals['include_labour_union'] = is_union
            else:
                is_union = vals.get('include_labour_union')

            if is_union:
                if not vals.get('labour_union_rep_id'):
                    vals['labour_union_rep_id'] = _to_id(EmpModel.get_union_user())
                else:
                    vals['labour_union_rep_id'] = _to_id(vals.get('labour_union_rep_id'))
            else:
                vals['labour_union_rep_id'] = False

            if not vals.get('respective_director_id'):
                resp_dir_id = False
                if case:
                    if case.director_id and case.director_id.id != ceo_user_id:
                        resp_dir_id = case.director_id.id
                    elif case.reported_by_id and case.reported_by_id.sudo().user_id and case.reported_by_id.sudo().user_id.id != ceo_user_id:
                        resp_dir_id = case.reported_by_id.sudo().user_id.id
                if not resp_dir_id and emp:
                    if emp.department_id and emp.department_id.sudo().manager_id and emp.department_id.sudo().manager_id.sudo().user_id:
                        dept_mgr_uid = emp.department_id.sudo().manager_id.sudo().user_id.id
                        if dept_mgr_uid != ceo_user_id:
                            resp_dir_id = dept_mgr_uid
                    if not resp_dir_id:
                        for sup in emp.sudo().get_supervisor_chain():
                            if sup.sudo().user_id and sup.sudo().user_id.id != ceo_user_id:
                                if sup.sudo().executive_level in ('director', 'chief') or 'director' in (sup.sudo().job_id.name or '').lower():
                                    resp_dir_id = sup.sudo().user_id.id
                                    break
                vals['respective_director_id'] = resp_dir_id
            else:
                vals['respective_director_id'] = _to_id(vals.get('respective_director_id'))

            if not vals.get('member_ids'):
                raw_ids = [vals.get('committee_chair_id'), vals.get('pomd_secretary_id'),
                           vals.get('legal_director_id'), vals.get('labour_union_rep_id'),
                           vals.get('respective_director_id')]
                seen = set()
                m_ids = []
                for uid in raw_ids:
                    if uid and uid not in seen:
                        seen.add(uid)
                        m_ids.append(uid)
                if m_ids:
                    vals['member_ids'] = [(6, 0, m_ids)]

            if case and not vals.get('recommended_penalty_type'):
                case_punish = case.punishment_type or case.original_punishment_type
                if case_punish in dict(self._fields['recommended_penalty_type'].selection):
                    vals['recommended_penalty_type'] = case_punish

            if vals.get('recommended_penalty_type'):
                staff_cat = vals.get('staff_category') or (case.staff_category if case else False)
                norm_vals = self.get_normal_scenario_values(vals.get('recommended_penalty_type'), staff_cat, case)
                if not vals.get('recommended_warning_validity_days'):
                    vals['recommended_warning_validity_days'] = norm_vals['recommended_warning_validity_days']
                if not vals.get('recommended_penalty_percentage') and staff_cat != 'managerial':
                    vals['recommended_penalty_percentage'] = norm_vals['recommended_penalty_percentage']
                if not vals.get('recommended_fine_days') and staff_cat == 'managerial':
                    vals['recommended_fine_days'] = norm_vals['recommended_fine_days']

        records = super().create(vals_list)
        for rec in records:
            if not rec.attendance_ids:
                rec._create_default_attendance_lines()
        return records

    def _create_default_attendance_lines(self):
        """Create structured attendance lines for all designated panel members without duplicates."""
        self.ensure_one()
        role_map = [
            ('chair', 1, self.committee_chair_id),
            ('secretary', 2, self.pomd_secretary_id),
            ('legal', 3, self.legal_director_id),
            ('director', 4, self.respective_director_id),
        ]
        if self.include_labour_union and self.labour_union_rep_id:
            role_map.append(('union', 5, self.labour_union_rep_id))
        seen_user_ids = set()
        for r_code, r_order, u in role_map:
            if u and u.id not in seen_user_ids:
                seen_user_ids.add(u.id)
                self.env['discipline.committee.attendance'].create({
                    'meeting_id': self.id,
                    'user_id': u.id,
                    'role': r_code,
                    'role_order': r_order,
                    'is_present': False,
                    'attendance_status': 'absent',
                })

    def _send_discuss_direct_message(self, sender_user, target_partner, msg_html):
        """Safely dispatch 1-on-1 Odoo Discuss direct chat message."""
        if not target_partner or not sender_user:
            return
        try:
            channel = self.env['discuss.channel'].sudo().with_user(sender_user)._get_or_create_chat(
                partners_to=[target_partner.id]
            )
            if channel:
                channel.sudo().with_user(sender_user).message_post(
                    body=Markup(msg_html),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_user.partner_id.id,
                )
        except Exception as e:
            _logger.warning("Failed to dispatch Discuss direct message to partner %s: %s", target_partner.id, str(e))

    def action_confirm_schedule_and_send_summons(self):
        """Confirm schedule and dispatch hearing notice to designated committee panel members (Secretary Mandate)."""
        for rec in self:
            if not (rec.can_schedule_hearing or self.env.su):
                raise UserError(_(
                    "Mandate Restriction: Scheduling the disciplinary committee hearing is the exclusive statutory "
                    "mandate of the Committee Secretary (People Operations Director). The Committee Chair Man does not possess this mandate."
                ))
            if not rec.meeting_date:
                raise UserError(_('Please specify the Meeting Date before confirming the schedule.'))
            if not rec.location:
                raise UserError(_('Please specify the Hearing Room / In-Person Venue before confirming the schedule.'))
            rec.write({'state': 'scheduled'})
            
            # Collect recipient panel members (employee is not notified at this stage; they are notified after final decision)
            recipient_partners = []
            recipient_users = []
            
            panel_users = [
                rec.committee_chair_id,
                rec.pomd_secretary_id,
                rec.respective_director_id,
                rec.legal_director_id,
                rec.labour_union_rep_id,
            ]
            for m in rec.member_ids:
                if m not in panel_users:
                    panel_users.append(m)
            
            for u in panel_users:
                if u and u.partner_id:
                    recipient_users.append(u)
                    recipient_partners.append(u.partner_id)
            
            formatted_date = format_date(rec.env, rec.meeting_date) if rec.meeting_date else 'N/A'
            header_title = _('🔄 Rescheduled Hearing Session Summons — Disciplinary Committee') if rec.is_rescheduled else _('⚖️ Hearing Session Schedule — Disciplinary Committee')
            rescheduled_banner = ''
            if rec.is_rescheduled:
                rescheduled_banner = (
                    '<div style="background-color: #d1ecf1; border-left: 4px solid #17a2b8; padding: 8px 12px; border-radius: 4px; font-size: 12px; color: #0c5460; margin-bottom: 10px;">'
                    '🔄 <strong>RESCHEDULED NOTICE:</strong> Please note that this disciplinary hearing session has been rescheduled. The updated meeting date and in-person venue are detailed below.'
                    '</div>'
                )

            msg = _(
                '<div style="font-family: inherit; line-height: 1.6;">'
                '<div style="background-color: #f8f9fa; border-left: 4px solid #714B67; padding: 10px 15px; margin-bottom: 10px; border-radius: 4px;">'
                '<h4 style="margin: 0 0 5px 0; color: #714B67; font-weight: bold;">%s</h4>'
                '<div style="font-size: 13px; color: #555;">Hearing Ref: <strong>%s</strong> | Linked Case: <strong>%s</strong></div>'
                '</div>'
                '%s'
                '<table style="width: 100%%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px;">'
                '<tr><td style="padding: 4px 0; width: 35%%; color: #666;"><strong>Subject Employee:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Meeting Date:</strong></td><td style="padding: 4px 0; font-weight: bold; color: #714B67;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Physical Hearing Venue:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Chair Man:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Secretary:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                '</table>'
                '<div style="background-color: #fff3cd; border: 1px solid #ffeeba; padding: 8px 12px; border-radius: 4px; font-size: 12px; color: #856404;">'
                '⚠️ <strong>Mandatory Panel Attendance Notice:</strong> This is an official notice to designated committee members. All designated panel members are required to attend the hearing session in person at the scheduled time and venue.'
                '</div>'
                '</div>'
            ) % (
                header_title,
                rec.name,
                rec.case_id.name if rec.case_id else 'N/A',
                rescheduled_banner,
                rec.sudo().employee_id.name if rec.sudo().employee_id else 'N/A',
                formatted_date,
                rec.location or _('Designated Hearing Room'),
                rec.committee_chair_id.name if rec.committee_chair_id else 'N/A',
                rec.pomd_secretary_id.name if rec.pomd_secretary_id else 'N/A',
            )

            p_ids = [p.id for p in recipient_partners if p]
            if p_ids:
                rec.sudo().message_subscribe(partner_ids=list(set(p_ids)))

            rec.message_post(
                body=Markup(msg),
                partner_ids=list(set(p_ids)) if p_ids else False,
                subtype_xmlid='mail.mt_comment'
            )

            # Dispatch Direct 1-on-1 Chat in Odoo Discuss to each committee member
            sender = self.env.user
            for target_partner in recipient_partners:
                if target_partner:
                    self._send_discuss_direct_message(sender, target_partner, msg)

    def unlink(self):
        for rec in self:
            if rec.state in ('in_progress', 'chair_review', 'completed'):
                raise UserError(_('Hearing Record Protection: Active or finalized committee hearing records cannot be deleted.'))
            user = self.env.user
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
            is_creator = bool(rec.create_uid and rec.create_uid.id == user.id)
            if not (is_admin or is_creator or self.env.su):
                raise UserError(_('Permission Denied: You are not authorized to delete committee hearing record %s.') % rec.name)
        return super().unlink()

    def action_begin_hearing_session(self):
        """Begin the active hearing session on the meeting day (Exclusive Mandate of Committee Chair Man / CPCO)."""
        for rec in self:
            user = self.env.user
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == user)
            is_cpco = user.has_group('discipline_management.group_discipline_cpco')
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system') or self.env.su
            if not (is_chair or is_cpco or is_admin):
                raise UserError(_(
                    "Mandate Restriction: Only the Committee Chair Man has the statutory mandate to call the disciplinary committee to order and begin the hearing session."
                ))

            # Validate Meeting Date (Cannot commence prior to scheduled meeting date)
            today = fields.Date.context_today(rec)
            if rec.meeting_date and today < rec.meeting_date:
                raise UserError(_(
                    "Premature Hearing Commencement:\n"
                    "The hearing session cannot be commenced before the scheduled Meeting Date (%(meeting_date)s).\n"
                    "Today's date is %(today)s.\n\n"
                    "If the hearing needs to be held earlier, the Committee Secretary must reschedule the meeting first."
                ) % {
                    'meeting_date': format_date(rec.env, rec.meeting_date),
                    'today': format_date(rec.env, today),
                })

            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('Disciplinary Hearing session officially commenced by Committee Chair Man %s. Panel is now in session.') % user.name)

    def action_sync_panel_from_config(self):
        """Synchronize statutory panel officers from configuration and case reporting hierarchy."""
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        ceo_user_id = ceo_user.id if ceo_user else False

        for rec in self:
            case = rec.case_id.sudo() if rec.case_id else False
            emp = case.employee_id if case else False

            # 1. Committee Chair Man (CPCO)
            cpco_user = EmpModel.get_cpco_user()
            # 2. Committee Secretary (POMD Director)
            sec_user = EmpModel.get_secretary_user()
            # 3. Legal Directorate Member
            legal_user = EmpModel.get_legal_user()

            # 4. Director of Respective Office
            resp_dir_user = False
            if case:
                if case.director_id and case.director_id.id != ceo_user_id:
                    resp_dir_user = case.director_id
                elif case.reported_by_id and case.reported_by_id.sudo().user_id and case.reported_by_id.sudo().user_id.id != ceo_user_id:
                    resp_dir_user = case.reported_by_id.sudo().user_id
            if not resp_dir_user and emp:
                if emp.department_id and emp.department_id.sudo().manager_id and emp.department_id.sudo().manager_id.sudo().user_id:
                    dept_mgr_uid = emp.department_id.sudo().manager_id.sudo().user_id
                    if dept_mgr_uid.id != ceo_user_id:
                        resp_dir_user = dept_mgr_uid
                if not resp_dir_user:
                    for sup in emp.sudo().get_supervisor_chain():
                        if sup.sudo().user_id and sup.sudo().user_id.id != ceo_user_id:
                            if sup.sudo().executive_level in ('director', 'chief') or 'director' in (sup.sudo().job_id.name or '').lower():
                                resp_dir_user = sup.sudo().user_id
                                break

            # 5. Labour Union Representative
            union_user = False
            if rec.include_labour_union:
                union_user = EmpModel.get_union_user()

            rec.sudo().write({
                'committee_chair_id': cpco_user.id if cpco_user else False,
                'pomd_secretary_id': sec_user.id if sec_user else False,
                'legal_director_id': legal_user.id if legal_user else False,
                'respective_director_id': resp_dir_user.id if resp_dir_user else False,
                'labour_union_rep_id': union_user.id if union_user else False,
            })
            rec._sync_panel_attendance_matrix()

    def action_reset_to_draft(self):
        """Reset meeting to draft for rescheduling and re-synchronize statutory panel officers from configuration (Secretary Mandate)."""
        for rec in self:
            if rec.state in ('in_progress', 'chair_review', 'completed'):
                raise UserError(_(
                    "Rescheduling Forbidden: The disciplinary hearing session has already commenced (or finalized). "
                    "Active or concluded hearing sessions cannot be rescheduled."
                ))
            if rec.state != 'scheduled':
                raise UserError(_("Only scheduled committee meetings can be rescheduled."))

            if not (rec.can_schedule_hearing or self.env.su):
                raise UserError(_(
                    "Mandate Restriction: Rescheduling the disciplinary committee hearing is the exclusive statutory "
                    "mandate of the Committee Secretary (People Operations Director). The Committee Chair Man does not possess this mandate."
                ))

            # Reset state to draft and mark as rescheduled so the date and location become editable
            rec.write({
                'state': 'draft',
                'is_rescheduled': True,
            })
            rec.action_sync_panel_from_config()
            rec.message_post(body=_(
                'Disciplinary Hearing session reset to draft for rescheduling by Committee Secretary %s. '
                'Panel members will be notified upon confirmation of the updated schedule.'
            ) % self.env.user.name)

    action_reschedule_meeting = action_reset_to_draft

    def action_cancel_meeting(self):
        """Cancel the scheduled hearing."""
        for rec in self:
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Disciplinary Committee Meeting cancelled by %s.') % self.env.user.name)

    def action_mark_all_present(self):
        """Quick action for Secretary to mark all designated panel members present."""
        for rec in self:
            for att in rec.attendance_ids:
                att.write({'is_present': True, 'attendance_status': 'present'})

    def action_submit_to_chairman(self):
        """Submit recorded hearing proceedings and minutes to Committee Chair Man for review (Secretary Mandate)."""
        for rec in self:
            user = self.env.user
            is_sec = bool(rec.pomd_secretary_id and rec.pomd_secretary_id == user)
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system') or self.env.su
            is_pomd = (user.has_group('discipline_management.group_discipline_pomd') or 
                       user.has_group('discipline_management.group_discipline_pomd_director'))
            is_cpco = user.has_group('discipline_management.group_discipline_cpco')
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == user)

            if not (is_admin or is_sec or (is_pomd and not is_chair)):
                raise UserError(_(
                    "Mandate Restriction: Submitting hearing deliberations and minutes to the Committee Chair Man is the "
                    "exclusive statutory mandate of the Committee Secretary."
                ))

            # Mandatory Signed Minutes Check
            if not rec.signed_minutes_file:
                raise UserError(_(
                    "Official Signed Meeting Minutes (PDF) is required before submitting to the Chair Man.\n"
                    "The committee members' physical signatures on the uploaded minutes serve as statutory proof of panel attendance and quorum."
                ))

            # Mandatory Recommended Disciplinary Measure
            verdict = rec.recommended_penalty_type or rec.final_recommendation
            if not verdict:
                raise UserError(_('Please select a Recommended Disciplinary Measure before submitting to the Chair Man.'))

            rec.write({
                'state': 'chair_review',
                'is_quorum_met': True,
            })

            rec.message_post(
                body=_('Hearing proceedings and signed minutes submitted by Committee Secretary %s for Chairman review and endorsement.') % user.name
            )

            chair_user = rec.committee_chair_id
            if chair_user and chair_user.partner_id:
                msg_html = _(
                    '<p>⚖️ <strong>Disciplinary Hearing Submitted for Review</strong></p>'
                    '<p>Hearing Ref: <strong>%s</strong> | Case: <strong>%s</strong></p>'
                    '<p>The Committee Secretary has concluded recording the deliberations, minutes, and recommended verdict. '
                    'Please review the record, provide your endorsement remarks, and submit to the CEO.</p>'
                ) % (rec.name, rec.case_id.name if rec.case_id else '')
                rec._send_discuss_direct_message(user, chair_user.partner_id, msg_html)

    def action_return_to_secretary(self):
        """Committee Chair Man returns the hearing proceedings to the Secretary for revision or amendment."""
        for rec in self:
            user = self.env.user
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == user)
            is_cpco = user.has_group('discipline_management.group_discipline_cpco')
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system') or self.env.su

            if not (is_chair or is_cpco or is_admin):
                raise UserError(_(
                    "Mandate Restriction: Only the Committee Chair Man has the statutory authority to return hearing proceedings for revision."
                ))

            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('Hearing proceedings returned to Committee Secretary by Committee Chair Man %s for revision.') % user.name)

            sec_user = rec.pomd_secretary_id
            if sec_user and sec_user.partner_id:
                msg_html = _(
                    '<p>↩️ <strong>Hearing Proceedings Returned for Revision</strong></p>'
                    '<p>Hearing Ref: <strong>%s</strong> | Case: <strong>%s</strong></p>'
                    '<p>Committee Chair Man %s has returned the hearing record for revision. Please review the Chairman remarks and resubmit.</p>'
                ) % (rec.name, rec.case_id.name if rec.case_id else '', user.name)
                rec._send_discuss_direct_message(user, sec_user.partner_id, msg_html)

    # Backward compatibility aliases
    action_start_hearing_and_notify = action_confirm_schedule_and_send_summons
    action_schedule_and_notify = action_confirm_schedule_and_send_summons

    def action_conclude_and_submit_recommendation(self):
        """Conclude Hearing & Deliberations, sync sanction to Case, advance Case to pending_approval, and submit exclusively to CEO for enforcement."""
        recom_to_punishment = {
            'dismissal': 'dismissal',
            'final_warning': 'final_warning_penalty',
            'second_warning': 'second_warning_penalty',
            'first_warning': 'first_warning_penalty',
            'verbal_warning': 'verbal_warning',
            'exonerate': 'exonerate',
        }
        for rec in self:
            user = self.env.user
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == user)
            is_cpco = user.has_group('discipline_management.group_discipline_cpco')
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system') or self.env.su

            if not (is_chair or is_cpco or is_admin):
                raise UserError(_(
                    "Mandate Restriction: Only the Committee Chair Man has the statutory mandate to review and submit the committee's recommendation to the CEO."
                ))

            # 1. Mandatory Signed Minutes Check (Signatures on minutes confirm attendance & quorum)
            if not rec.signed_minutes_file:
                raise UserError(_(
                    "Official Signed Meeting Minutes (PDF) is required to submit the recommendation to the CEO.\n"
                    "The committee members' physical signatures on the minutes serve as statutory proof of panel attendance and quorum."
                ))

            # 2. Resolve selected recommendation
            verdict = rec.recommended_penalty_type or rec.final_recommendation
            if not verdict:
                raise UserError(_('Please select a Recommended Disciplinary Measure before submitting.'))

            punish_val = recom_to_punishment.get(verdict, verdict)

            rec.write({
                'state': 'completed',
                'is_quorum_met': True,
                'recommended_penalty_type': punish_val,
                'final_recommendation': verdict if verdict in dict(rec._fields['final_recommendation'].selection) else False,
            })

            # 3. Auto-populate decided punishment on Parent Case and advance directly to pending_approval for CEO enforcement
            if rec.case_id:
                case_vals = {
                    'decided_punishment_type': punish_val,
                    'punishment_type': punish_val,
                    'is_demotion_decided': bool(rec.is_demotion_recommended and rec.staff_category == 'managerial'),
                    'state': 'pending_approval',
                    'is_locked_for_committee': False,
                }
                if rec.recommended_penalty_percentage:
                    case_vals['decided_penalty_percentage'] = rec.recommended_penalty_percentage
                if rec.recommended_fine_days:
                    case_vals['decided_fine_days'] = rec.recommended_fine_days
                if rec.demotion_target_job_id:
                    case_vals['new_job_id'] = rec.demotion_target_job_id.id

                rec.case_id.sudo().with_context(force_write=True).write(case_vals)

                # 5. All Committee decisions are sent exclusively to CEO for approval & enforcement
                EmpModel = self.env['hr.employee'].sudo()
                ceo_user = EmpModel.get_ceo_user()
                cpco_user = EmpModel.get_cpco_user()
                pomd_user = EmpModel.get_pomd_user()
                
                target_exec_user = ceo_user
                target_role = _('Chief Executive Officer (CEO)')
                target_name = target_exec_user.name if target_exec_user else target_role

                verdict_label = dict(rec._fields['recommended_penalty_type'].selection).get(punish_val, punish_val)

                notification_body = _(
                    '<div style="font-family: inherit; line-height: 1.6;">'
                    '<div style="background-color: #e8f4fd; border-left: 4px solid #0056b3; padding: 10px 15px; margin-bottom: 10px; border-radius: 4px;">'
                    '<h4 style="margin: 0 0 5px 0; color: #0056b3; font-weight: bold;">⚖️ Hearing Concluded &amp; Recommendation Submitted to CEO</h4>'
                    '<div style="font-size: 13px; color: #555;">Hearing Ref: <strong>%s</strong> | Status: <strong>Pending CEO Approval &amp; Enforcement</strong></div>'
                    '</div>'
                    '<table style="width: 100%%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px;">'
                    '<tr><td style="padding: 4px 0; width: 35%%; color: #666;"><strong>Subject Employee:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Recommended Verdict:</strong></td><td style="padding: 4px 0; font-weight: bold; color: #c0392b;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Designated Approving &amp; Enforcing Authority:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s (CEO)</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Endorsed &amp; Submitted By Chair Man:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                    '</table>'
                    '</div>'
                ) % (
                    rec.name,
                    rec.sudo().employee_id.name if rec.sudo().employee_id else _('Employee'),
                    verdict_label,
                    target_name,
                    self.env.user.name,
                )

                # Strictly restrict pre-enforcement verdict notifications to CEO, CPCO, and POMD
                partners_to_notify = []
                if ceo_user and ceo_user.partner_id:
                    partners_to_notify.append(ceo_user.partner_id.id)
                if cpco_user and cpco_user.partner_id:
                    partners_to_notify.append(cpco_user.partner_id.id)
                if pomd_user and pomd_user.partner_id:
                    partners_to_notify.append(pomd_user.partner_id.id)

                rec.message_post(
                    body=Markup(notification_body),
                    partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                )
                if rec.case_id:
                    rec.case_id.sudo().message_post(
                        body=Markup(_(
                            'Disciplinary Committee Hearing <strong>%s</strong> has concluded and submitted its recommendation to <strong>%s (CEO)</strong> for final approval and enforcement.'
                        ) % (rec.name, target_name)),
                        partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                    )

                # Dispatch Direct 1-on-1 Chat in Odoo Discuss to CEO, CPCO, and POMD
                sender = self.env.user
                for pid in set(partners_to_notify):
                    p_obj = self.env['res.partner'].browse(pid)
                    if p_obj.exists():
                        self._send_discuss_direct_message(sender, p_obj, notification_body)

    action_submit_to_ceo = action_conclude_and_submit_recommendation
    action_finalize_meeting = action_conclude_and_submit_recommendation
    action_finalize_and_submit_for_approval = action_conclude_and_submit_recommendation

    def action_load_saved_signature(self):
        """Load Chairperson's saved digital signature into this committee meeting."""
        self.ensure_one()
        user = self.env.user
        is_chair = bool(self.committee_chair_id and self.committee_chair_id == user)
        is_cpco = user.has_group('discipline_management.group_discipline_cpco')
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()
        if not (is_chair or is_cpco or is_admin):
            raise UserError(_("Access Restriction: Only the Committee Chairperson or Administrator can provide the Chairperson digital signature."))
        if self.state == 'completed':
            raise UserError(_("This committee hearing is already completed. Digital signature cannot be modified."))
        sig = getattr(user, 'discipline_digital_signature', False) or getattr(user, 'digital_signature', False)
        if not sig:
            # Check previously signed meeting or case
            prev_meeting = self.search([('chair_signature', '!=', False), ('committee_chair_id', '=', user.id)], order='id desc', limit=1)
            if prev_meeting and prev_meeting.chair_signature:
                sig = prev_meeting.chair_signature
            else:
                prev_case = self.env['discipline.case'].sudo().search([('signatory_signature', '!=', False), ('signatory_id', '=', user.id)], order='id desc', limit=1)
                if prev_case and prev_case.signatory_signature:
                    sig = prev_case.signatory_signature
        if not sig:
            raise UserError(_("No saved signature found for %s. Please draw your signature on the canvas and it will be remembered automatically.") % user.name)
        self.chair_signature = sig
        try:
            if not getattr(user, 'discipline_digital_signature', False):
                user.sudo().write({'discipline_digital_signature': sig})
        except Exception:
            pass
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Signature Loaded'),
                'message': _('Chairperson signature loaded successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_chair_enforce_and_notify_ceo(self):
        """Chairperson officially approves and enforces the Disciplinary Committee resolution directly and notifies the CEO."""
        recom_to_punishment = {
            'dismissal': 'dismissal',
            'final_warning': 'final_warning_penalty',
            'second_warning': 'second_warning_penalty',
            'first_warning': 'first_warning_penalty',
            'verbal_warning': 'verbal_warning',
            'exonerate': 'exonerate',
        }
        for rec in self:
            user = self.env.user
            is_chair = bool(rec.committee_chair_id and rec.committee_chair_id == user)
            is_cpco = user.has_group('discipline_management.group_discipline_cpco')
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user._is_superuser()

            if not (is_chair or is_cpco or is_admin):
                raise UserError(_(
                    "Mandate Restriction: Only the Committee Chairperson (CPCO) or Administrator has the statutory mandate to approve and enforce the committee resolution."
                ))

            # 1. Mandatory Signed Minutes Check
            if not rec.signed_minutes_file:
                raise UserError(_(
                    "Official Signed Meeting Minutes (PDF) is required before enforcing the decision.\n"
                    "The committee members' physical signatures on the minutes serve as statutory proof of panel attendance and quorum."
                ))

            # 2. Mandatory Digital Signature Check
            if not rec.chair_signature or len(rec.chair_signature) < 50:
                user_saved_sig = getattr(user, 'discipline_digital_signature', False) or getattr(user, 'digital_signature', False)
                if user_saved_sig and len(user_saved_sig) >= 50:
                    rec.chair_signature = user_saved_sig
                else:
                    raise UserError(_(
                        "Mandatory Digital Signature Required:\n\n"
                        "Enforcing without signature is prevented. As the Committee Chairperson approving and enforcing this "
                        "disciplinary resolution, you must draw or load your digital signature under 'Chairperson Endorsement & Digital Sign-off' before enforcing the decision."
                    ))

            # Auto-persist signature to user profile
            if rec.chair_signature and not getattr(user, 'discipline_digital_signature', False):
                try:
                    user.sudo().write({'discipline_digital_signature': rec.chair_signature})
                except Exception:
                    pass

            # 3. Resolve selected recommendation
            verdict = rec.recommended_penalty_type or rec.final_recommendation
            if not verdict:
                raise UserError(_('Please select a Recommended Disciplinary Measure before enforcing.'))

            punish_val = recom_to_punishment.get(verdict, verdict)

            # Mark meeting as completed
            rec.write({
                'state': 'completed',
                'is_quorum_met': True,
                'recommended_penalty_type': punish_val,
                'final_recommendation': verdict if verdict in dict(rec._fields['final_recommendation'].selection) else False,
            })

            # Sync to Parent Case and Enforce
            if rec.case_id:
                case = rec.case_id
                case_vals = {
                    'decided_punishment_type': punish_val,
                    'punishment_type': punish_val,
                    'is_demotion_decided': bool(rec.is_demotion_recommended and rec.staff_category == 'managerial'),
                    'signatory_signature': rec.chair_signature,
                    'signatory_id': user.id,
                    'is_locked_for_committee': False,
                    'state': 'pending_approval',
                }
                if rec.recommended_penalty_percentage:
                    case_vals['decided_penalty_percentage'] = rec.recommended_penalty_percentage
                    case_vals['penalty_percentage'] = rec.recommended_penalty_percentage
                if rec.recommended_fine_days:
                    case_vals['decided_fine_days'] = rec.recommended_fine_days
                    case_vals['fine_days'] = rec.recommended_fine_days
                if rec.demotion_target_job_id:
                    case_vals['new_job_id'] = rec.demotion_target_job_id.id

                case.sudo().with_context(force_write=True).write(case_vals)

                # Now execute case approval & enforcement
                case.with_user(user).action_approve_and_enforce()

                # Dispatch official CEO notification
                EmpModel = self.env['hr.employee'].sudo()
                ceo_user = EmpModel.get_ceo_user()
                verdict_label = dict(rec._fields['recommended_penalty_type'].selection).get(punish_val, punish_val)

                notification_body = _(
                    '<div style="font-family: inherit; line-height: 1.6;">'
                    '<div style="background-color: #d4edda; border-left: 4px solid #28a745; padding: 10px 15px; margin-bottom: 10px; border-radius: 4px;">'
                    '<h4 style="margin: 0 0 5px 0; color: #155724; font-weight: bold;">⚖️ Disciplinary Resolution Enforced &amp; Notified to CEO</h4>'
                    '<div style="font-size: 13px; color: #155724;">Hearing Ref: <strong>%s</strong> | Status: <strong>Enforced by Committee Chairperson</strong></div>'
                    '</div>'
                    '<table style="width: 100%%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px;">'
                    '<tr><td style="padding: 4px 0; width: 35%%; color: #666;"><strong>Subject Employee:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Enforced Verdict:</strong></td><td style="padding: 4px 0; font-weight: bold; color: #c0392b;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Enforcing Authority:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s (Committee Chairperson)</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>CEO Notification Status:</strong></td><td style="padding: 4px 0; color: #28a745; font-weight: bold;">Delivered</td></tr>'
                    '</table>'
                    '</div>'
                ) % (
                    rec.name,
                    rec.sudo().employee_id.name if rec.sudo().employee_id else _('Employee'),
                    verdict_label,
                    user.name,
                )

                ceo_partners = [ceo_user.partner_id.id] if ceo_user and ceo_user.partner_id else []
                rec.message_post(
                    body=Markup(notification_body),
                    partner_ids=ceo_partners or False,
                )
                if ceo_user and ceo_user.partner_id:
                    rec._send_discuss_direct_message(user, ceo_user.partner_id, notification_body)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Resolution Enforced'),
                'message': _('Disciplinary Committee Resolution has been enforced and the CEO has been notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    # Helper methods for PDF Report
    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official logo for QWeb PDF rendering."""
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
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def action_print_hearing_report(self):
        """Print official Disciplinary Committee Hearing Minutes & Resolution Report PDF."""
        self.ensure_one()
        return self.env.ref('discipline_management.action_report_committee_resolution').report_action(self)

    @api.constrains('case_id', 'state')
    def _check_case_meeting_integrity(self):
        for rec in self:
            if not rec.case_id or rec.state == 'cancelled':
                continue

            # 1. Maturity Check: Case must be in committee_review stage to schedule or hold a meeting
            if rec.state in ('draft', 'scheduled') and rec.case_id.state != 'committee_review':
                state_label = dict(rec.case_id._fields['state'].selection).get(rec.case_id.state, rec.case_id.state)
                raise ValidationError(_(
                    "Disciplinary Case %(case)s is not mature for committee hearing scheduling. "
                    "A committee meeting can only be created when the case is in the 'Committee Review / Hearing' stage (current state: '%(state)s')."
                ) % {
                    'case': rec.case_id.name,
                    'state': state_label,
                })

            # 2. Duplicate Meeting Check: Prevent duplicate active or completed meetings for the same case
            duplicate_meetings = self.sudo().search([
                ('case_id', '=', rec.case_id.id),
                ('id', '!=', rec.id),
                ('state', 'not in', ('cancelled',))
            ])
            if duplicate_meetings:
                active_dupes = duplicate_meetings.filtered(lambda m: m.state != 'completed')
                if active_dupes:
                    raise ValidationError(_(
                        "Disciplinary Case %(case)s already has an active or scheduled committee meeting (%(meeting)s). "
                        "Duplicate meetings cannot be scheduled for the same case."
                    ) % {
                        'case': rec.case_id.name,
                        'meeting': active_dupes[0].name,
                    })
                else:
                    raise ValidationError(_(
                        "Disciplinary Case %(case)s already has a completed committee meeting (%(meeting)s). "
                        "A case cannot have duplicate committee hearings."
                    ) % {
                        'case': rec.case_id.name,
                        'meeting': duplicate_meetings[0].name,
                    })

    @api.constrains('meeting_date', 'case_id', 'state')
    def _check_meeting_date_integrity(self):
        for rec in self:
            if not rec.meeting_date or rec.state not in ('draft', 'scheduled'):
                continue

            local_meeting_date = rec.meeting_date
            today_local = fields.Date.context_today(rec)

            # 1. Backdate Prevention: Cannot be earlier than today
            if local_meeting_date < today_local:
                raise ValidationError(_(
                    "Meeting Date cannot be earlier than today (%(today)s). "
                    "Selected date: %(selected)s. Please select today or a future date for the committee meeting."
                ) % {
                    'today': today_local.strftime('%Y-%m-%d'),
                    'selected': local_meeting_date.strftime('%Y-%m-%d'),
                })

            # 2. Chronological Check against Misconduct Incident Date
            if rec.case_id and rec.case_id.incident_date:
                if local_meeting_date < rec.case_id.incident_date:
                    raise ValidationError(_(
                        "Meeting Date (%(meeting_date)s) cannot precede the Misconduct Incident Date (%(incident_date)s)."
                    ) % {
                        'meeting_date': local_meeting_date.strftime('%Y-%m-%d'),
                        'incident_date': rec.case_id.incident_date.strftime('%Y-%m-%d'),
                    })

            # 3. Chronological Check against Disciplinary Case Registration Date
            if rec.case_id and rec.case_id.create_date:
                local_case_created = fields.Datetime.context_timestamp(rec, rec.case_id.create_date).date()
                if local_meeting_date < local_case_created:
                    raise ValidationError(_(
                        "Meeting Date (%(meeting_date)s) cannot precede the Case Registration Date (%(create_date)s)."
                    ) % {
                        'meeting_date': local_meeting_date.strftime('%Y-%m-%d'),
                        'create_date': local_case_created.strftime('%Y-%m-%d'),
                    })


class DisciplineCommitteeVote(models.Model):
    _name = 'discipline.committee.vote'
    _description = 'Disciplinary Committee Member Vote'

    meeting_id = fields.Many2one('discipline.committee.meeting', string='Meeting', required=True, ondelete='cascade')
    member_id = fields.Many2one('res.users', string='Committee Member', required=True, default=lambda self: self.env.user)
    vote = fields.Selection([
        ('in_favor', 'In Favor of Proposed Action'),
        ('against', 'Against Proposed Action'),
        ('abstain', 'Abstain'),
    ], string='Vote', required=True)
    comments = fields.Text(string='Vote Justification / Remarks')

    _uniq_member_vote = models.Constraint('unique(meeting_id, member_id)', 'A committee member can only vote once per meeting!')
