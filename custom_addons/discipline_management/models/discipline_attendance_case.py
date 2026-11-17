# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta
from markupsafe import Markup
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError
from .discipline_case_report_helpers import gregorian_to_ethiopian


class DisciplineAttendanceCase(models.Model):
    _name = 'discipline.attendance.case'
    _description = 'Attendance & Absence Disciplinary Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'incident_date desc, id desc'

    PUNISHMENT_SELECTION = [
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / Acknowledged'),
        ('leave_adjusted', 'Adjusted by Approved Leave'),
    ]

    name = fields.Char(
        string='Case Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    # Employee & Organizational Profile
    employee_id = fields.Many2one(
        'hr.employee',
        string='Subject Employee',
        required=True,
        tracking=True,
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        compute='_compute_org_profile',
        store=True,
        readonly=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True,
        readonly=True,
    )
    is_managerial = fields.Boolean(
        string='Is Managerial',
        compute='_compute_org_profile',
        store=True,
    )
    staff_category = fields.Selection([
        ('non_managerial', 'Non-Managerial'),
        ('managerial', 'Managerial'),
    ], string='Employment Category Code', compute='_compute_org_profile', store=True)
    staff_category_display = fields.Char(
        string='Employment Category',
        compute='_compute_org_profile',
        store=True,
    )
    coach_id = fields.Many2one(
        'res.users',
        string='Direct Coach / Line Manager',
        compute='_compute_org_profile',
        store=True,
        readonly=False,
        tracking=True,
    )
    director_id = fields.Many2one(
        'res.users',
        string='Directorate Director',
        compute='_compute_org_profile',
        store=True,
        readonly=False,
        tracking=True,
    )

    # Violation & Period Details
    violation_type = fields.Selection([
        ('late', 'Cumulative Late Arrival'),
        ('absence_minor', 'Unexcused Absence (1–2 Days)'),
        ('absence_prolonged', 'Prolonged Unexcused Absence (3–4 Consecutive Days)'),
        ('absence_dismissal', 'Dismissal Absence (≥ 5 Consecutive Working Days)'),
        ('force_checkout', 'Force Check-Out Violation'),
    ], string='Attendance Breach Type', required=True, default='absence_minor', tracking=True)

    # Backward compatibility alias
    attendance_violation_type = fields.Selection(
        related='violation_type',
        string='Attendance Breach Type (Alias)',
        readonly=True,
    )
    is_attendance_case = fields.Boolean(
        string='Is Attendance Case',
        default=True,
        readonly=True,
    )

    incident_date = fields.Date(
        string='Evaluation / Incident Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_from = fields.Date(string='Period Start Date', required=True, default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Period End Date', required=True, default=fields.Date.context_today)

    absent_dates_summary = fields.Char(
        string='Unexcused Absent Dates',
        help='Comma-separated list of unexcused working dates detected in the period.',
        tracking=True,
    )
    absent_days_count = fields.Integer(string='Total Unexcused Absent Days', default=0, tracking=True)
    max_consecutive_days = fields.Integer(string='Max Consecutive Unexcused Working Days', default=0, tracking=True)
    late_minutes_total = fields.Float(string='Cumulative Late Time (Minutes)', default=0.0, tracking=True)
    late_occurrences_count = fields.Integer(string='Late Check-In Count', default=0)
    force_checkout_count = fields.Integer(string='Force Check-Out Count', default=0)

    is_shift_worker = fields.Boolean(string='Shift / Roster Worker (Sunday Eligible)', default=False)
    shift_schedule_summary = fields.Char(
        string='Applied Working Schedule',
        default='Standard Mon–Sat Working Schedule',
    )
    description = fields.Text(string='Violation Summary & Audit Details')

    # Regulatory & Sanction Details
    offense_id = fields.Many2one(
        'discipline.offense',
        string='Misconduct Clause / Offense',
        tracking=True,
    )
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Classification', tracking=True)
    severity_level = fields.Char(related='severity_level_id.code', string='Severity Code', store=True)
    occurrence_count = fields.Integer(
        string='Breach Occurrence (Tier)',
        compute='_compute_occurrence_count',
        store=True,
        readonly=False,
        default=1,
        tracking=True,
        help='Progressive disciplinary tier for this breach based on active prior enforced history within the reset period.'
    )
    def _get_notice_language_selection(self):
        return [
            ('amharic', 'Amharic (አማርኛ)'),
            ('english', 'English'),
        ]

    notice_language = fields.Selection(
        selection='_get_notice_language_selection',
        string='Notice Letter Language',
        default='amharic',
        required=True,
        tracking=True,
        help='Language format for the formal disciplinary notice letter. Amharic is the official standard for Bunna Bank.'
    )

    punishment_type = fields.Selection(
        PUNISHMENT_SELECTION,
        string='Prescribed Measure',
        compute='_compute_sanction_details',
        store=True,
        readonly=False,
        tracking=True,
    )
    penalty_percentage = fields.Float(
        string='Salary Deduction Rate (%)',
        compute='_compute_sanction_details',
        store=True,
        readonly=False,
        tracking=True,
    )
    fine_days = fields.Float(
        string='Salary Fine (Days)',
        compute='_compute_sanction_details',
        store=True,
        readonly=False,
        tracking=True,
    )

    # Leave Conversion / Adjustment & Justification
    leave_id = fields.Many2one(
        'hr.leave',
        string='Covering Time Off / Leave Record',
        tracking=True,
        help='Approved or submitted leave record covering the absent dates prior to enforcement.',
    )
    covered_leave_days = fields.Float(
        string='Days Covered by Leave',
        default=0.0,
        tracking=True,
    )
    remaining_unexcused_days = fields.Integer(
        string='Remaining Unexcused Days',
        compute='_compute_remaining_unexcused_days',
        store=True,
    )
    justification_reason = fields.Text(
        string='Coach / Leave Justification Notes',
        tracking=True,
    )
    has_pending_leave_approval = fields.Boolean(
        string='Has Pending Leave Approval',
        compute='_compute_pending_leave_approval',
        store=True,
        tracking=True,
        help='True when an attached leave request is awaiting approval by the Coach/Manager.',
    )
    can_coach_approve_leave = fields.Boolean(
        string='Can Coach Approve Leave Adjustment',
        compute='_compute_access_flags',
    )

    # HR Refusal & Enforcement Audit Fields
    hr_refusal_reason = fields.Text(string='HR / POMD Refusal Reason', tracking=True)
    refused_by_id = fields.Many2one('res.users', string='Refused By (HR/POMD)', readonly=True, tracking=True)
    refused_date = fields.Date(string='Refused Date', readonly=True, tracking=True)

    enforced_by_id = fields.Many2one('res.users', string='Enforced By', readonly=True, tracking=True)
    enforced_date = fields.Date(string='Enforced Date', readonly=True, tracking=True)
    active_duration_days = fields.Integer(string='Warning Active Validity (Days)', default=180, tracking=True)
    active_penalty_end_date = fields.Date(string='Warning Active End Date', compute='_compute_active_penalty_dates', store=True, tracking=True)

    signatory_id = fields.Many2one(
        'res.users',
        string='Authorized Signatory',
        compute='_compute_signatory_id',
        store=True,
        tracking=True,
        help='Authorized executive / line manager who signed and enforced this attendance decision.'
    )
    signatory_signature = fields.Binary(
        string='Signatory Signature',
        compute='_compute_signatory_signature',
        help='Authorized digital signature image rendered on the notice letter.'
    )

    exonerated_by_id = fields.Many2one('res.users', string='Exonerated / Adjusted By', readonly=True, tracking=True)
    exonerated_date = fields.Date(string='Exonerated / Adjusted Date', readonly=True, tracking=True)

    # Payroll Integration
    payroll_month = fields.Selection([
        ('1', 'January'), ('2', 'February'), ('3', 'March'), ('4', 'April'),
        ('5', 'May'), ('6', 'June'), ('7', 'July'), ('8', 'August'),
        ('9', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December')
    ], string='Payroll Deduction Month', default=lambda self: str(fields.Date.context_today(self).month))
    deduction_status = fields.Selection([
        ('not_applicable', 'No Financial Deduction'),
        ('scheduled', 'Scheduled for Immediate Payroll'),
        ('transferred', 'Transmitted to Payroll'),
        ('deducted', 'Deducted in Payslip'),
        ('cancelled', 'Cancelled / Refused / Exonerated'),
    ], string='Payroll Deduction Status', default='not_applicable', tracking=True)
    payroll_penalty_ids = fields.One2many(
        'discipline.payroll.penalty',
        'attendance_case_id',
        string='Payroll Penalty Lines',
    )
    payroll_penalty_count = fields.Integer(
        string='Payroll Penalties',
        compute='_compute_payroll_penalty_count',
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('coach_review', 'Pending Coach Action'),
        ('director_review', 'Pending Director Review (≥5 Days)'),
        ('pomd_review', 'Pending POMD Dismissal Enforcement'),
        ('leave_adjusted', 'Adjusted by Leave'),
        ('exonerated', 'Acknowledged / Exonerated'),
        ('enforced', 'Enforced'),
        ('hr_refused', 'Refused by HR'),
    ], string='Status', default='coach_review', required=True, tracking=True)

    # Dynamic Role & Button Visibility Flags
    is_case_employee = fields.Boolean(compute='_compute_access_flags')
    is_case_coach = fields.Boolean(compute='_compute_access_flags')
    is_case_director = fields.Boolean(compute='_compute_access_flags')
    is_pomd_or_admin = fields.Boolean(compute='_compute_access_flags')
    can_adjust_by_leave = fields.Boolean(compute='_compute_access_flags')
    can_coach_act = fields.Boolean(compute='_compute_access_flags')
    can_director_act = fields.Boolean(compute='_compute_access_flags')
    can_pomd_enforce = fields.Boolean(compute='_compute_access_flags')
    can_hr_refuse = fields.Boolean(compute='_compute_access_flags')

    @api.constrains('incident_date')
    def _check_incident_date_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.incident_date and rec.incident_date > today:
                raise ValidationError(_(
                    'Invalid Incident Date: The Attendance Incident Date (%s) cannot be in the future. '
                    'Please select today (%s) or a prior date.'
                ) % (rec.incident_date, today))

    @api.constrains('employee_id', 'violation_type', 'date_from', 'date_to', 'state')
    def _check_no_duplicate_active_case(self):
        """Prevent double active attendance disciplinary cases for the same employee
        covering overlapping dates."""
        for rec in self:
            if rec.state in ('leave_adjusted', 'exonerated', 'hr_refused'):
                continue
            if not rec.employee_id or not rec.date_from or not rec.date_to:
                continue
            duplicates = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'not in', ['leave_adjusted', 'exonerated', 'hr_refused']),
                ('date_from', '<=', rec.date_to),
                ('date_to', '>=', rec.date_from),
            ], limit=1)
            if duplicates:
                raise ValidationError(_(
                    "Duplicate Attendance Case Detected!\n"
                    "An active attendance disciplinary case (%s, Status: %s) already exists for employee '%s' "
                    "covering the period %s to %s.\n"
                    "Duplicate active disciplinary records for the same employee and period are not permitted."
                ) % (duplicates.name, duplicates.state, rec.employee_id.name, rec.date_from, rec.date_to))



    @api.onchange('incident_date')
    def _onchange_incident_date(self):
        today = fields.Date.context_today(self)
        if self.incident_date and self.incident_date > today:
            invalid_date = self.incident_date
            self.incident_date = today
            return {
                'warning': {
                    'title': _('Invalid Incident Date'),
                    'message': _(
                        'The Attendance Incident Date cannot be in the future (%s). '
                        'It has been automatically reset to today (%s).'
                    ) % (invalid_date, today),
                }
            }

    @api.depends('employee_id', 'employee_id.department_id', 'employee_id.job_id', 'employee_id.coach_id', 'employee_id.parent_id')
    def _compute_org_profile(self):
        CaseModel = self.env['discipline.case']
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            if not emp:
                rec.operating_unit_id = False
                rec.is_managerial = False
                rec.staff_category = False
                rec.staff_category_display = False
                rec.coach_id = False
                rec.director_id = False
                continue

            ou = getattr(emp, 'default_operating_unit_id', False) or (emp.department_id and getattr(emp.department_id, 'operating_unit_id', False))
            rec.operating_unit_id = ou.id if ou else False

            is_mgr = CaseModel._is_employee_managerial(emp)
            rec.is_managerial = is_mgr
            rec.staff_category = 'managerial' if is_mgr else 'non_managerial'
            rec.staff_category_display = _('Managerial') if is_mgr else _('Non-Managerial')

            # Resolve Direct Coach
            coach_emp = emp.coach_id or emp.parent_id or (emp.department_id and emp.department_id.manager_id)
            rec.coach_id = coach_emp.user_id.id if (coach_emp and coach_emp.user_id) else False

            # Resolve Directorate Director (Coach of Coach or first Director/Chief in supervisor chain)
            director_user = False
            for sup in emp.get_supervisor_chain():
                if sup.executive_level in ('director', 'chief') and sup.user_id:
                    director_user = sup.user_id
                    break
            if not director_user and coach_emp:
                upper_sup = coach_emp.coach_id or coach_emp.parent_id
                if upper_sup and upper_sup.user_id:
                    director_user = upper_sup.user_id
            if not director_user and emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
                director_user = emp.department_id.manager_id.user_id
            rec.director_id = director_user.id if director_user else rec.coach_id.id

    @api.depends('absent_days_count', 'covered_leave_days')
    def _compute_remaining_unexcused_days(self):
        for rec in self:
            rem = max(0, int(round((rec.absent_days_count or 0) - (rec.covered_leave_days or 0.0))))
            rec.remaining_unexcused_days = rem

    @api.depends('payroll_penalty_ids')
    def _compute_payroll_penalty_count(self):
        for rec in self:
            rec.payroll_penalty_count = len(rec.payroll_penalty_ids)

    @api.depends('employee_id', 'violation_type', 'incident_date', 'date_from')
    def _compute_occurrence_count(self):
        for rec in self:
            emp = rec.employee_id
            if not emp:
                rec.occurrence_count = 1
                continue
            inc_date = rec.incident_date or rec.date_from or fields.Date.context_today(rec)
            prior_cases = self.search([
                ('id', '!=', rec._origin.id if rec._origin else (rec.id or 0)),
                ('employee_id', '=', emp.id),
                ('state', '=', 'enforced'),
                ('enforced_date', '!=', False),
            ])
            active_priors = prior_cases.filtered(
                lambda c: (c.active_penalty_end_date and c.active_penalty_end_date >= inc_date) or
                          (c.enforced_date and (c.enforced_date + timedelta(days=c.active_duration_days or 180)) >= inc_date)
            )
            if rec.violation_type in ('absence_minor', 'absence_prolonged'):
                same_type = active_priors.filtered(lambda c: c.violation_type in ('absence_minor', 'absence_prolonged'))
            else:
                same_type = active_priors.filtered(lambda c: c.violation_type == rec.violation_type)
            rec.occurrence_count = len(same_type) + 1

    @api.depends('enforced_date', 'active_duration_days', 'punishment_type', 'state')
    def _compute_active_penalty_dates(self):
        for rec in self:
            if rec.state == 'enforced' and rec.enforced_date and rec.punishment_type != 'dismissal':
                duration = rec.active_duration_days or 180
                rec.active_penalty_end_date = rec.enforced_date + timedelta(days=duration)
            else:
                rec.active_penalty_end_date = False

    @api.depends('enforced_by_id', 'coach_id', 'director_id', 'state')
    def _compute_signatory_id(self):
        for rec in self:
            if rec.enforced_by_id:
                rec.signatory_id = rec.enforced_by_id
            elif rec.state == 'pomd_review':
                sec_user = self.env['hr.employee'].sudo().get_secretary_user()
                rec.signatory_id = sec_user or self.env.user
            elif rec.state == 'director_review':
                rec.signatory_id = rec.director_id or self.env.user
            else:
                rec.signatory_id = rec.coach_id or self.env.user

    @api.depends('signatory_id')
    def _compute_signatory_signature(self):
        for rec in self:
            sig = False
            if rec.signatory_id and rec.signatory_id.employee_ids:
                emp = rec.signatory_id.employee_ids[0]
                sig = getattr(emp, 'digital_signature', False) or getattr(emp, 'signature', False)
            rec.signatory_signature = sig

    @api.depends('violation_type', 'severity_level_id', 'is_managerial', 'occurrence_count')
    def _compute_sanction_details(self):
        for rec in self:
            v_type = rec.violation_type
            is_mgr = rec.is_managerial
            occ = max(1, rec.occurrence_count or 1)

            if v_type == 'absence_dismissal':
                rec.punishment_type = 'dismissal'
                rec.penalty_percentage = 0.0
                rec.fine_days = 0.0
            elif v_type == 'absence_prolonged':
                if occ >= 2:
                    # Repeated prolonged unexcused absence within active window escalates to dismissal
                    rec.punishment_type = 'dismissal'
                    rec.penalty_percentage = 0.0
                    rec.fine_days = 0.0
                else:
                    rec.punishment_type = 'final_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 20.0
                    rec.fine_days = 3.0 if is_mgr else 0.0
            elif v_type == 'absence_minor':
                if occ == 1:
                    rec.punishment_type = 'first_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 5.0
                    rec.fine_days = 1.0 if is_mgr else 0.0
                elif occ == 2:
                    rec.punishment_type = 'second_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 10.0
                    rec.fine_days = 2.0 if is_mgr else 0.0
                else:
                    rec.punishment_type = 'final_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 20.0
                    rec.fine_days = 3.0 if is_mgr else 0.0
            else:
                # late or force_checkout
                if occ == 1:
                    rec.punishment_type = 'verbal_warning'
                    rec.penalty_percentage = 0.0
                    rec.fine_days = 0.0
                elif occ == 2:
                    rec.punishment_type = 'first_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 5.0
                    rec.fine_days = 1.0 if is_mgr else 0.0
                elif occ == 3:
                    rec.punishment_type = 'second_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 10.0
                    rec.fine_days = 2.0 if is_mgr else 0.0
                else:
                    rec.punishment_type = 'final_warning_penalty'
                    rec.penalty_percentage = 0.0 if is_mgr else 20.0
                    rec.fine_days = 3.0 if is_mgr else 0.0

    @api.depends('leave_id', 'leave_id.state', 'state')
    def _compute_pending_leave_approval(self):
        for rec in self:
            if not rec.leave_id or rec.state in ('leave_adjusted', 'exonerated', 'enforced', 'hr_refused'):
                rec.has_pending_leave_approval = False
            else:
                lv = rec.leave_id
                lv_status = getattr(lv, 'leave_request_status', False)
                is_pending = lv.state in ('draft', 'confirm') or lv_status in ('draft', 'fetch', 'notify')
                rec.has_pending_leave_approval = is_pending

    def _compute_access_flags(self):
        user = self.env.user
        is_pomd_admin = (
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_pomd_director') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('base.group_system')
        )
        for rec in self:
            emp = rec.employee_id.sudo() if rec.employee_id else False
            is_emp = bool(emp and emp.user_id and emp.user_id.id == user.id)
            sup_chain_user_ids = [s.user_id.id for s in emp.get_supervisor_chain() if s.user_id] if emp else []

            is_coach = bool(
                (rec.coach_id and rec.coach_id.id == user.id) or
                (emp and emp.coach_id and emp.coach_id.user_id and emp.coach_id.user_id.id == user.id) or
                (emp and emp.parent_id and emp.parent_id.user_id and emp.parent_id.user_id.id == user.id) or
                user.id in sup_chain_user_ids
            )
            is_dir = bool(
                (rec.director_id and rec.director_id.id == user.id) or
                (emp and emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id and emp.department_id.manager_id.user_id.id == user.id) or
                user.id in sup_chain_user_ids
            )

            rec.is_case_employee = is_emp
            rec.is_case_coach = is_coach
            rec.is_case_director = is_dir
            rec.is_pomd_or_admin = is_pomd_admin

            # Employee, Coach, Director, or POMD can convert/adjust absent days to leave BEFORE enforcement
            rec.can_adjust_by_leave = bool(
                rec.state in ('coach_review', 'director_review', 'pomd_review') and
                (is_emp or is_coach or is_dir or is_pomd_admin)
            )
            rec.can_coach_act = bool(
                rec.state == 'coach_review' and (is_coach or is_dir or is_pomd_admin) and not is_emp
            )
            rec.can_director_act = bool(
                rec.state == 'director_review' and (is_dir or is_pomd_admin) and not is_emp
            )
            rec.can_pomd_enforce = bool(
                rec.state == 'pomd_review' and is_pomd_admin and not is_emp
            )
            rec.can_hr_refuse = bool(
                rec.state in ('coach_review', 'director_review', 'pomd_review', 'enforced') and
                is_pomd_admin and
                rec.deduction_status not in ('deducted',)
            )
            rec.can_coach_approve_leave = bool(
                rec.has_pending_leave_approval and
                (is_coach or is_dir or is_pomd_admin) and
                not is_emp
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('discipline.attendance.case') or _('New')
            if 'violation_type' in vals and vals['violation_type'] == 'absence_dismissal' and 'state' not in vals:
                vals['state'] = 'director_review'
        records = super().create(vals_list)
        for rec in records:
            rec._notify_initial_routing()
        return records

    def _post_discuss_dm_to_user(self, recipient_user, html_body):
        """Send an instant Odoo Discuss DM and subscribe the recipient to the attendance case."""
        self.ensure_one()
        if not recipient_user or not recipient_user.partner_id:
            return
        try:
            self.sudo().message_subscribe(partner_ids=[recipient_user.partner_id.id])
            sender_partner = self.env.user.partner_id
            target_partner = recipient_user.partner_id
            ChannelModel = self.env['discuss.channel'].sudo() if 'discuss.channel' in self.env else self.env['mail.channel'].sudo()
            p_ids = list({sender_partner.id, target_partner.id})
            channel = False
            if hasattr(ChannelModel, 'channel_get'):
                ch_info = ChannelModel.channel_get(partners_to=p_ids)
                ch_id = ch_info.get('id') if isinstance(ch_info, dict) else getattr(ch_info, 'id', False)
                if ch_id:
                    channel = ChannelModel.browse(ch_id)
            if channel:
                channel.message_post(
                    body=Markup(html_body),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_partner.id,
                )
        except Exception:
            pass

    def _notify_initial_routing(self):
        """Send Discuss and Chatter notifications upon attendance case creation."""
        for rec in self:
            emp = rec.sudo().employee_id
            emp_user = emp.user_id if emp else False
            if rec.violation_type == 'absence_dismissal' or rec.state == 'director_review':
                partners = [u.partner_id.id for u in (rec.director_id, rec.coach_id, emp_user) if u and u.partner_id]
                msg = Markup(_(
                    '<strong>🚨 Dismissal Absence Detected (≥ 5 Consecutive Working Days) — Director Review Required:</strong><br/>'
                    '• <strong>Case Ref:</strong> %s<br/>'
                    '• <strong>Employee:</strong> %s<br/>'
                    '• <strong>Unexcused Consecutive Working Days:</strong> %d days (%s)<br/>'
                    '• <strong>Applied Schedule:</strong> %s<br/>'
                    '• <strong>Next Step:</strong> Directorate Director (%s) shall review and forward to POMD for enforcement. '
                    '<em>Note: Prior to POMD enforcement, the employee may convert/cover these absent dates with approved leave.</em>'
                ) % (
                    rec.name,
                    emp.name if emp else _('Staff'),
                    rec.max_consecutive_days,
                    rec.absent_dates_summary or _('See period'),
                    rec.shift_schedule_summary or _('Standard'),
                    rec.director_id.name if rec.director_id else _('Director'),
                ))
                rec.message_post(body=msg, partner_ids=list(set(partners)) if partners else False)
                if rec.director_id:
                    rec._post_discuss_dm_to_user(rec.director_id, msg)
                if emp_user:
                    rec._post_discuss_dm_to_user(emp_user, msg)
            else:
                partners = [u.partner_id.id for u in (rec.coach_id, emp_user) if u and u.partner_id]
                v_label = dict(self._fields['violation_type'].selection).get(rec.violation_type, rec.violation_type)
                msg = Markup(_(
                    '<strong>📋 Attendance Breach Initiated — Direct Coach Review Required:</strong><br/>'
                    '• <strong>Case Ref:</strong> %s<br/>'
                    '• <strong>Employee:</strong> %s<br/>'
                    '• <strong>Violation Type:</strong> %s<br/>'
                    '• <strong>Period:</strong> %s to %s<br/>'
                    '• <strong>Action Required:</strong> Direct Coach (%s) may <strong>Enforce Penalty</strong>, '
                    '<strong>Adjust by Leave</strong>, or <strong>Acknowledge / Exonerate</strong> with valid justification.'
                ) % (
                    rec.name,
                    emp.name if emp else _('Staff'),
                    v_label,
                    rec.date_from,
                    rec.date_to,
                    rec.coach_id.name if rec.coach_id else _('Direct Coach'),
                ))
                rec.message_post(body=msg, partner_ids=list(set(partners)) if partners else False)
                if rec.coach_id:
                    rec._post_discuss_dm_to_user(rec.coach_id, msg)
                if emp_user:
                    rec._post_discuss_dm_to_user(emp_user, msg)

    # =========================================================================
    # WORKFLOW ACTIONS: >= 5 CONSECUTIVE DAYS DISMISSAL TRACK (Director -> POMD)
    # =========================================================================

    def action_director_send_to_pomd(self):
        """Director reviews >=5 consecutive days unexcused absence and sends it to POMD for dismissal enforcement."""
        for rec in self:
            if rec.state != 'director_review':
                raise UserError(_('Only cases in Pending Director Review can be forwarded to POMD.'))
            # Re-verify leave coverage before sending to POMD
            rec.action_recheck_leave_coverage(silent=True)
            if rec.state == 'leave_adjusted':
                return

            rec.write({'state': 'pomd_review'})
            sec_user = self.env['hr.employee'].sudo().get_secretary_user()
            partners = []
            if sec_user and sec_user.partner_id:
                partners.append(sec_user.partner_id.id)
            emp = rec.sudo().employee_id
            if emp and emp.user_id and emp.user_id.partner_id:
                partners.append(emp.user_id.partner_id.id)

            msg = Markup(_(
                '<strong>📤 Forwarded by Director to POMD for Dismissal Enforcement:</strong><br/>'
                '• <strong>Case Ref:</strong> %s<br/>'
                '• <strong>Employee:</strong> %s<br/>'
                '• <strong>Unexcused Consecutive Working Days:</strong> %d days (%s)<br/>'
                '• <strong>Forwarded By:</strong> %s (Directorate Director)<br/>'
                '• <strong>Action Required:</strong> POMD (%s) to verify leave status and execute dismissal enforcement.'
            ) % (
                rec.name,
                emp.name if emp else _('Staff'),
                rec.max_consecutive_days,
                rec.absent_dates_summary or 'N/A',
                self.env.user.name,
                sec_user.name if sec_user else _('POMD Director'),
            ))
            rec.message_post(body=msg, partner_ids=list(set(partners)) if partners else False)
            if sec_user:
                rec._post_discuss_dm_to_user(sec_user, msg)

    def action_pomd_enforce_dismissal(self):
        """POMD enforces dismissal for >= 5 consecutive working days unexcused absence after verifying no leave covers the absence."""
        for rec in self:
            if rec.state not in ('pomd_review', 'director_review'):
                raise UserError(_('Case must be in Pending POMD Enforcement to enforce dismissal.'))
            if not rec.is_pomd_or_admin:
                raise UserError(_('Authority Restriction: Only POMD or HR Administrator can enforce attendance dismissal.'))

            # Check if employee covered the absence with leave before enforcement
            rec.action_recheck_leave_coverage(silent=True)
            if rec.state != 'pomd_review' and rec.max_consecutive_days < 5:
                raise UserError(_(
                    'Leave Coverage Detected: The employee has covered absent days with leave, reducing consecutive unexcused days below the 5-day dismissal threshold.'
                ))

            today = fields.Date.context_today(self)
            rec.write({
                'state': 'enforced',
                'punishment_type': 'dismissal',
                'enforced_by_id': self.env.user.id,
                'enforced_date': today,
                'deduction_status': 'not_applicable',
            })

            # Execute employee dismissal & separation
            emp = rec.employee_id.sudo()
            if emp:
                write_vals = {
                    'active': False,
                    'active_disciplinary_action': True,
                    'is_ineligible_for_promotion_transfer': True,
                    'last_disciplinary_date': today,
                }
                departure_reason = self.env.ref('hr.departure_fired', raise_if_not_found=False)
                if departure_reason and 'departure_reason_id' in emp._fields:
                    write_vals['departure_reason_id'] = departure_reason.id
                if 'departure_date' in emp._fields:
                    write_vals['departure_date'] = today
                if 'departure_description' in emp._fields:
                    write_vals['departure_description'] = _(
                        'Dismissed under Attendance Disciplinary Case %s (≥5 consecutive unexcused working days) on %s.'
                    ) % (rec.name, today)
                emp.with_context(no_leave_resource_calendar_update=True).write(write_vals)
                if emp.user_id:
                    emp.user_id.sudo().write({'active': False})

                Separation = self.env.get('hr.separation') or self.env.get('employee.separation')
                if Separation:
                    Separation.sudo().create({
                        'employee_id': emp.id,
                        'separation_type': 'dismissal',
                        'reason': _('Attendance Dismissal (≥5 consecutive unexcused working days) under Case %s.') % rec.name,
                    })

            msg = Markup(_(
                '<strong>⚖️ Attendance Dismissal Enforced by POMD:</strong><br/>'
                '• <strong>Case Ref:</strong> %s<br/>'
                '• <strong>Employee:</strong> %s<br/>'
                '• <strong>Enforced By:</strong> %s (POMD)<br/>'
                '• <strong>Decision:</strong> Summary Dismissal for ≥ 5 consecutive working days unexcused absence. Employee profile archived and system access deactivated.'
            ) % (rec.name, rec.sudo().employee_id.name if rec.sudo().employee_id else _('Staff'), self.env.user.name))
            rec.message_post(body=msg)

    # =========================================================================
    # LEAVE CONVERSION / ADJUSTMENT (Employee / Coach / Director / POMD)
    # =========================================================================

    def action_open_leave_adjustment_wizard(self):
        """Open wizard to convert absent days to leave or link an approved/submitted hr.leave record prior to enforcement."""
        self.ensure_one()
        if self.state in ('enforced', 'leave_adjusted', 'exonerated', 'hr_refused'):
            raise UserError(_('Leave adjustment is only available before the case is enforced or closed.'))
        return {
            'name': _('Convert / Adjust Absent Days by Leave — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.attendance.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_action_type': 'adjust_leave',
                'default_attendance_case_ids': [(6, 0, self.ids)],
                'default_employee_id': self.employee_id.id,
                'default_leave_date_from': self.date_from,
                'default_leave_date_to': self.date_to,
                'default_leave_id': self.leave_id.id if self.leave_id else False,
            },
        }

    def action_recheck_leave_coverage(self, silent=False):
        """Cross-check Attendance Management for manager acknowledgments and Time Off for approved leaves.
        Automatically exonerates or converts the case if the absent dates are verified as cleared.
        """
        Leave = self.env['hr.leave'].sudo()
        AttModel = self.env['hr.attendance'].sudo()
        notification = None

        for rec in self:
            if rec.state in ('enforced', 'leave_adjusted', 'exonerated', 'hr_refused'):
                continue
            emp = rec.employee_id.sudo()
            if not emp:
                continue

            # Check if linked leave is still pending approval
            if rec.leave_id:
                lv = rec.leave_id
                lv_status = getattr(lv, 'leave_request_status', False)
                if lv.state not in ('validate', 'validate1') and lv_status != 'approved':
                    if not silent:
                        raise UserError(_(
                            'Linked Leave Request "%s" is pending Coach/Manager approval. '
                            'The attendance case will close automatically once the Coach approves it.'
                        ) % lv.display_name)
                    continue

            # Find validated or linked leaves overlapping the period
            domain = [
                ('employee_id', '=', emp.id),
                ('date_from', '<=', rec.date_to + timedelta(days=1)),
                ('date_to', '>=', rec.date_from),
            ]
            if rec.leave_id:
                domain = [('id', '=', rec.leave_id.id)]
            else:
                domain.append(('state', 'in', ['validate', 'validate1']))

            leaves = Leave.search(domain)
            leave_dates = set()
            for lv in leaves:
                l_start = max(rec.date_from, lv.date_from.date() if hasattr(lv.date_from, 'date') else lv.date_from)
                l_end = min(rec.date_to, lv.date_to.date() if hasattr(lv.date_to, 'date') else lv.date_to)
                cur_d = l_start
                while cur_d <= l_end:
                    leave_dates.add(cur_d)
                    cur_d += timedelta(days=1)

            # Recompute unexcused dates using shift-aware schedule
            work_days, _is_shift, _sched_label = AttModel._get_employee_scheduled_work_days(emp, rec.date_from, rec.date_to)
            
            # Query attendance records in the window
            dt_from_min = datetime.combine(rec.date_from, time.min)
            dt_to_max = datetime.combine(rec.date_to, time.max)
            atts = AttModel.search([
                ('employee_id', '=', emp.id),
                '|',
                '&', ('check_in', '>=', dt_from_min), ('check_in', '<=', dt_to_max),
                '&', ('work_date', '>=', rec.date_from), ('work_date', '<=', rec.date_to),
            ])

            checkin_dates = set()
            ack_dates = set()
            for a in atts:
                d = a.check_in.date() if a.check_in else getattr(a, 'work_date', False)
                if d:
                    is_ack = bool(
                        getattr(a, 'is_acknowledged', False) or
                        getattr(a, 'in_mode', '') == 'acknowledged' or
                        getattr(a, 'out_mode', '') == 'acknowledged' or
                        getattr(a, 'acknowledged_by', False) or
                        getattr(a, 'check_in_status', '') == 'Acknowledged Lateness'
                    )
                    has_real_checkin = bool(a.check_in and getattr(a, 'in_mode', '') != 'absent')
                    if is_ack:
                        ack_dates.add(d)
                    if has_real_checkin:
                        checkin_dates.add(d)

            # Cleared dates include valid punches, manager-acknowledged dates, and approved leaves
            cleared_dates = checkin_dates | ack_dates | leave_dates
            remaining_absent = [d for d in work_days if d not in cleared_dates]
            max_consec = AttModel._compute_max_consecutive_work_days(remaining_absent, work_days)

            covered_count = max(0, (rec.absent_days_count or len(work_days)) - len(remaining_absent))
            if leaves:
                rec.write({
                    'leave_id': leaves[0].id,
                    'covered_leave_days': covered_count,
                })

            today = fields.Date.context_today(rec)

            if not remaining_absent or (rec.violation_type == 'late' and (rec.leave_id or ack_dates)):
                # Distinguish between Manager Attendance Acknowledgment vs Leave Adjustment
                if ack_dates and not leave_dates and not rec.leave_id:
                    # 100% Cleared via Manager Attendance Acknowledgment
                    rec.write({
                        'state': 'exonerated',
                        'punishment_type': 'exonerate',
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'covered_leave_days': 0,
                        'deduction_status': 'cancelled',
                        'exonerated_by_id': self.env.user.id,
                        'exonerated_date': today,
                        'justification_reason': _(
                            'Automated Exoneration: All absent dates (%s to %s) verified as officially acknowledged by Manager in Attendance Management.'
                        ) % (rec.date_from.strftime('%b %d, %Y') if rec.date_from else '', rec.date_to.strftime('%b %d, %Y') if rec.date_to else ''),
                    })
                    rec.message_post(body=Markup(_(
                        '<strong>🛡️ Case Automatically Exonerated by Manager Attendance Acknowledgment:</strong><br/>'
                        '• <strong>Verified Acknowledged Dates:</strong> %s<br/>'
                        '• <strong>Acknowledged By:</strong> %s<br/>'
                        '• <strong>Outcome:</strong> Closed with zero disciplinary penalty.'
                    ) % (
                        ', '.join(d.strftime('%b %d, %Y') for d in sorted(ack_dates or work_days)),
                        self.env.user.name,
                    )))
                    notification = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Case Automatically Exonerated'),
                            'message': _('Manager attendance acknowledgment verified for all dates. Case exonerated with 0 penalty.'),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                elif leaves or leave_dates:
                    # Cleared via Approved Leave
                    rec.write({
                        'state': 'leave_adjusted',
                        'punishment_type': 'leave_adjusted',
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'covered_leave_days': covered_count or rec.absent_days_count,
                        'deduction_status': 'cancelled',
                        'exonerated_by_id': self.env.user.id,
                        'exonerated_date': today,
                    })
                    rec.message_post(body=Markup(_(
                        '<strong>✅ Case Adjusted by Leave &amp; Closed:</strong><br/>'
                        'Absent dates are fully covered by Leave record <strong>%s</strong>. Zero disciplinary penalty applied.'
                    ) % (leaves[0].display_name if leaves else 'Approved Time Off',)))
                    notification = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Converted to Leave'),
                            'message': _('Approved leave verified for all dates. Case converted to leave with 0 penalty.'),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    # Cleared via existing punches / attendance
                    rec.write({
                        'state': 'exonerated',
                        'punishment_type': 'exonerate',
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'covered_leave_days': 0,
                        'deduction_status': 'cancelled',
                        'exonerated_by_id': self.env.user.id,
                        'exonerated_date': today,
                        'justification_reason': _('Absence dates regularized by verified Attendance records.'),
                    })
                    rec.message_post(body=Markup(_(
                        '<strong>🛡️ Case Regularized by Attendance Records &amp; Closed:</strong><br/>'
                        'Attendance verified for all previously flagged dates. Zero disciplinary penalty applied.'
                    )))
                    notification = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Case Regularized & Closed'),
                            'message': _('Attendance verified for all dates. Case regularized with 0 penalty.'),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                # Cancel pending payroll penalty lines
                pending_pens = rec.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
                if pending_pens:
                    pending_pens.write({'state': 'cancelled'})

            elif rec.violation_type == 'absence_dismissal' and max_consec < 5:
                new_vtype = 'absence_prolonged' if max_consec >= 3 else 'absence_minor'
                rec.write({
                    'violation_type': new_vtype,
                    'max_consecutive_days': max_consec,
                    'absent_days_count': len(remaining_absent),
                    'absent_dates_summary': ', '.join(d.strftime('%Y-%m-%d') for d in remaining_absent),
                    'state': 'coach_review',
                })
                rec._compute_sanction_details()
                clear_src = _('Leave record %s') % leaves[0].display_name if leaves else _('Manager Attendance Acknowledgment')
                msg = _(
                    '<strong>🔄 Partial Coverage Applied — Downgraded to Coach Review:</strong><br/>'
                    '%s reduced consecutive unexcused days to <strong>%d day(s)</strong> (below the 5-day dismissal threshold). '
                    'Routed to Direct Coach (%s) for review.'
                ) % (clear_src, max_consec, rec.coach_id.name if rec.coach_id else _('Coach'))
                rec.message_post(body=Markup(msg))
                notification = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Partial Coverage — Downgraded'),
                        'message': _('Consecutive unexcused days reduced to %d. Downgraded to Coach Review.') % max_consec,
                        'type': 'info',
                        'sticky': False,
                    }
                }

            elif rec.violation_type == 'absence_dismissal' and max_consec >= 5:
                rec.write({
                    'max_consecutive_days': max_consec,
                    'absent_days_count': len(remaining_absent),
                    'absent_dates_summary': ', '.join(d.strftime('%Y-%m-%d') for d in remaining_absent),
                })
                target_stage = 'Directorate Director' if rec.state == 'director_review' else 'POMD'
                clear_src = _('Leave record %s') % leaves[0].display_name if leaves else _('Attendance Regularization')
                msg = _(
                    '<strong>⚠️ Partial Coverage Applied — Dismissal Threshold Still Exceeded:</strong><br/>'
                    '%s was applied, but <strong>%d consecutive unexcused working day(s)</strong> remain '
                    '(still meeting or exceeding the 5-day dismissal threshold). Case remains in %s review.'
                ) % (clear_src, max_consec, target_stage)
                rec.message_post(body=Markup(msg))
                notification = {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Dismissal Threshold Still Exceeded'),
                        'message': _('%d consecutive unexcused days remain. Case remains in %s review.') % (max_consec, target_stage),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            else:
                initial_count = rec.absent_days_count or len(work_days)
                rec.write({
                    'max_consecutive_days': max_consec,
                    'absent_days_count': len(remaining_absent),
                    'absent_dates_summary': ', '.join(d.strftime('%Y-%m-%d') for d in remaining_absent),
                })
                rec._compute_sanction_details()
                if len(remaining_absent) < initial_count:
                    clear_src = _('Leave record %s') % leaves[0].display_name if leaves else _('Manager Attendance Acknowledgment')
                    msg = _(
                        '<strong>ℹ️ Partial Coverage Applied:</strong><br/>'
                        '%s was applied. Remaining unexcused days: <strong>%d day(s)</strong>.'
                    ) % (clear_src, len(remaining_absent))
                    rec.message_post(body=Markup(msg))
                    notification = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Partial Coverage Applied'),
                            'message': _('Remaining unexcused days reduced to %d.') % len(remaining_absent),
                            'type': 'info',
                            'sticky': False,
                        }
                    }
                else:
                    # 0 dates acknowledged and 0 leaves
                    notification = {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('No Acknowledgment or Leave Found'),
                            'message': _(
                                'No manager attendance acknowledgment or approved leave was found for the absent dates (%s to %s). '
                                'To exonerate this case, the manager must first acknowledge the attendance record in Attendance Management or approve a leave request.'
                            ) % (
                                rec.date_from.strftime('%b %d, %Y') if rec.date_from else '',
                                rec.date_to.strftime('%b %d, %Y') if rec.date_to else ''
                            ),
                            'type': 'warning',
                            'sticky': True,
                        }
                    }

        if not silent and len(self) == 1 and notification:
            return notification

    def action_coach_approve_leave_adjustment(self):
        """Allow Direct Coach / Line Manager / Director / POMD to approve the employee's submitted leave request directly from the attendance case."""
        self.ensure_one()
        user = self.env.user
        emp = self.employee_id
        is_emp = bool(emp and (emp.user_id == user or emp.id in user.employee_ids.ids))
        if is_emp and not (user.has_group('discipline_management.group_discipline_admin') or user._is_admin()):
            raise UserError(_("You cannot approve your own leave adjustment. Your Direct Coach or Line Manager must approve it."))

        if not self.leave_id:
            raise UserError(_("No linked leave request found to approve."))

        leave = self.leave_id.sudo().with_user(SUPERUSER_ID).with_context(
            leave_fast_create=True,
            leave_skip_state_check=True,
            leave_skip_date_check=True,
            mail_create_nolog=True,
            tracking_disable=True,
        )
        try:
            if hasattr(leave, 'action_approve') and leave.state not in ('validate', 'validate1'):
                leave.action_approve()
            if leave.state not in ('validate', 'validate1') or getattr(leave, 'leave_request_status', False) != 'approved':
                leave.write({
                    'leave_request_status': 'approved',
                    'state': 'validate',
                })
        except Exception:
            leave.write({
                'leave_request_status': 'approved',
                'state': 'validate',
            })

        # Mark any pending approval activities on this case as done
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        case_activities = getattr(self, 'activity_ids', self.env['mail.activity'])
        if case_activities:
            pending = case_activities.filtered(lambda a: (activity_type and a.activity_type_id == activity_type) or (a.summary and 'Leave Adjustment' in a.summary))
            if pending:
                try:
                    pending.action_feedback(feedback=_("Leave adjustment approved by %s.") % user.name)
                except Exception:
                    pass

        # Close the case with zero penalty
        self.write({
            'state': 'leave_adjusted',
            'punishment_type': 'leave_adjusted',
            'penalty_percentage': 0.0,
            'fine_days': 0.0,
            'covered_leave_days': self.absent_days_count,
            'deduction_status': 'cancelled',
            'exonerated_by_id': user.id,
            'exonerated_date': fields.Date.context_today(self),
        })
        pending_pens = self.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
        if pending_pens:
            pending_pens.write({'state': 'cancelled'})

        self.message_post(body=Markup(_(
            '<strong>✅ Leave Adjustment Approved by Coach (%s):</strong><br/>'
            '• Leave Request <strong>%s</strong> approved.<br/>'
            '• %.1f absent days covered and deducted from leave balance.<br/>'
            '• Attendance case closed with zero penalty.'
        ) % (user.name, leave.display_name or f"LR-{leave.id}", self.absent_days_count)))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Leave Adjustment Approved'),
                'message': _('Leave Request %s approved successfully. Case closed with zero penalty.') % (leave.display_name or f"LR-{leave.id}"),
                'type': 'success',
                'sticky': False,
            }
        }

    # =========================================================================
    # DIRECT COACH ACTIONS (Minor / Prolonged Attendance Cases)
    # =========================================================================

    def action_open_exonerate_wizard(self):
        """Open wizard for Direct Coach to acknowledge/exonerate one or more attendance cases with justification."""
        for rec in self:
            if rec.state not in ('coach_review', 'director_review'):
                raise UserError(_('Only pending attendance cases can be exonerated.'))
        return {
            'name': _('Acknowledge / Exonerate Attendance Case(s)'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.attendance.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_action_type': 'coach_exonerate',
                'default_attendance_case_ids': [(6, 0, self.ids)],
            },
        }

    def action_coach_exonerate(self, justification=None):
        """Direct Coach acknowledges/exonerates the attendance breach with valid justification."""
        today = fields.Date.context_today(self)
        for rec in self:
            reason = justification or rec.justification_reason
            if not reason:
                raise UserError(_('Please provide a valid justification reason before exonerating the attendance case.'))
            rec.write({
                'state': 'exonerated',
                'punishment_type': 'exonerate',
                'penalty_percentage': 0.0,
                'fine_days': 0.0,
                'justification_reason': reason,
                'deduction_status': 'cancelled',
                'exonerated_by_id': self.env.user.id,
                'exonerated_date': today,
            })
            # Cancel any pending payroll penalty lines
            pending_pens = rec.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
            if pending_pens:
                pending_pens.write({'state': 'cancelled'})
            rec.message_post(body=Markup(_(
                '<strong>✅ Attendance Case Acknowledged / Exonerated by Direct Coach (%s):</strong><br/>'
                '• <strong>Justification:</strong> %s<br/>'
                '• <strong>Outcome:</strong> Closed with zero penalty.'
            ) % (self.env.user.name, reason)))

    def action_coach_enforce(self):
        """Direct Coach enforces the attendance disciplinary sanction and schedules immediate payroll deduction if applicable."""
        today = fields.Date.context_today(self)
        target_month = str(today.month)
        for rec in self:
            if rec.violation_type == 'absence_dismissal':
                raise UserError(_(
                    'Dismissal Absence (≥5 Consecutive Working Days) cannot be enforced by the Direct Coach. '
                    'It must be reviewed by the Director and enforced by POMD.'
                ))
            if rec.state not in ('coach_review', 'director_review'):
                raise UserError(_('Only pending attendance cases can be enforced.'))

            has_financial = (not rec.is_managerial and rec.penalty_percentage > 0.0) or (rec.is_managerial and rec.fine_days > 0.0)
            validity_map = {
                'verbal_warning': 30,
                'first_warning_penalty': 90,
                'second_warning_penalty': 180,
                'final_warning_penalty': 365,
            }
            v_duration = validity_map.get(rec.punishment_type, 180)
            rec.write({
                'state': 'enforced',
                'enforced_by_id': self.env.user.id,
                'enforced_date': today,
                'payroll_month': target_month,
                'active_duration_days': v_duration,
                'deduction_status': 'scheduled' if has_financial else 'not_applicable',
            })

            emp = rec.sudo().employee_id
            if emp:
                emp.with_context(no_leave_resource_calendar_update=True).write({
                    'active_disciplinary_action': True,
                    'disciplinary_warning_count': emp.disciplinary_warning_count + 1,
                    'last_disciplinary_date': today,
                })

            if has_financial:
                rec._schedule_attendance_payroll_penalty()

            emp_user = emp.user_id if emp else False
            p_label = dict(self._fields['punishment_type'].selection).get(rec.punishment_type, rec.punishment_type)
            msg = Markup(_(
                '<strong>⚠️ Attendance Disciplinary Sanction Enforced by Direct Coach:</strong><br/>'
                '• <strong>Case Ref:</strong> %s<br/>'
                '• <strong>Employee:</strong> %s<br/>'
                '• <strong>Enforced Measure:</strong> %s<br/>'
                '• <strong>Enforced By:</strong> %s'
            ) % (rec.name, emp.name if emp else _('Staff'), p_label, self.env.user.name))
            rec.message_post(
                body=msg,
                partner_ids=[emp_user.partner_id.id] if (emp_user and emp_user.partner_id) else False,
            )
            if emp_user:
                rec._post_discuss_dm_to_user(emp_user, msg)

    def _schedule_attendance_payroll_penalty(self):
        """Create or update discipline.payroll.penalty line for an enforced attendance case."""
        PenaltyModel = self.env['discipline.payroll.penalty'].sudo()
        today = fields.Date.context_today(self)
        for rec in self:
            existing = rec.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
            month_str = rec.payroll_month or str(today.month)
            vals = {
                'attendance_case_id': rec.id,
                'employee_id': rec.employee_id.id,
                'transaction_type': 'deduction',
                'effective_date': rec.enforced_date or today,
                'payroll_month': month_str,
                'state': 'pending',
            }
            if not rec.is_managerial and rec.penalty_percentage > 0.0:
                vals.update({
                    'penalty_type': 'percentage',
                    'penalty_percentage': rec.penalty_percentage,
                    'managerial_days': 0,
                    'notes': _('Attendance breach penalty (%s%%) for %s.') % (rec.penalty_percentage, rec.name),
                })
            elif rec.is_managerial and rec.fine_days > 0.0:
                vals.update({
                    'penalty_type': 'managerial',
                    'penalty_percentage': 0.0,
                    'managerial_days': int(rec.fine_days),
                    'notes': _('Managerial attendance fine (%d days) for %s.') % (int(rec.fine_days), rec.name),
                })
            else:
                continue

            if existing:
                existing[0].write(vals)
            else:
                PenaltyModel.create(vals)

    # =========================================================================
    # HR / POMD INDIVIDUAL & BATCH REFUSAL
    # =========================================================================

    def action_open_hr_refuse_wizard(self):
        """Open wizard for HR / POMD to refuse attendance case(s) individually or in batch."""
        if not (
            self.env.user.has_group('discipline_management.group_discipline_pomd') or
            self.env.user.has_group('discipline_management.group_discipline_cpco') or
            self.env.user.has_group('discipline_management.group_discipline_ceo') or
            self.env.user.has_group('discipline_management.group_discipline_admin') or
            self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Authority Restriction: Only HR (POMD / CPCO / Admin) can refuse attendance disciplinary cases.'))
        return {
            'name': _('HR Refuse Attendance Case(s) — %d Selected') % len(self),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.attendance.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_action_type': 'hr_refuse',
                'default_attendance_case_ids': [(6, 0, self.ids)],
            },
        }

    def action_hr_refuse(self, refusal_reason=None):
        """Refuse attendance case(s) individually or in batch, cancelling any pending payroll deduction."""
        if not (
            self.env.user.has_group('discipline_management.group_discipline_pomd') or
            self.env.user.has_group('discipline_management.group_discipline_cpco') or
            self.env.user.has_group('discipline_management.group_discipline_ceo') or
            self.env.user.has_group('discipline_management.group_discipline_admin') or
            self.env.user.has_group('base.group_system')
        ):
            raise UserError(_('Authority Restriction: Only HR (POMD / CPCO / Admin) can refuse attendance disciplinary cases.'))
        today = fields.Date.context_today(self)
        for rec in self:
            reason = refusal_reason or rec.hr_refusal_reason
            if not reason:
                raise UserError(_('Please provide an HR Refusal Reason.'))
            if rec.deduction_status == 'deducted':
                raise UserError(_('Cannot refuse Case %s because its payroll penalty has already been deducted in a payslip.') % rec.name)

            # Cancel pending/transferred payroll penalties
            active_pens = rec.payroll_penalty_ids.sudo().filtered(lambda p: p.state in ('pending', 'transferred'))
            if active_pens:
                active_pens.write({'state': 'cancelled'})

            rec.write({
                'state': 'hr_refused',
                'hr_refusal_reason': reason,
                'refused_by_id': self.env.user.id,
                'refused_date': today,
                'deduction_status': 'cancelled',
            })
            emp = rec.sudo().employee_id
            emp_user = emp.user_id if emp else False
            partners = [u.partner_id.id for u in (rec.coach_id, rec.director_id, emp_user) if u and u.partner_id]
            msg = Markup(_(
                '<strong>🚫 Attendance Case Refused by HR / POMD (%s):</strong><br/>'
                '• <strong>Refusal Reason:</strong> %s<br/>'
                '• <strong>Effect:</strong> Case refused and any scheduled payroll penalty cancelled.'
            ) % (self.env.user.name, reason))
            rec.message_post(body=msg, partner_ids=list(set(partners)) if partners else False)

    def action_view_payroll_penalties(self):
        self.ensure_one()
        return {
            'name': _('Payroll Penalties — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.payroll.penalty',
            'view_mode': 'list,form',
            'domain': [('attendance_case_id', '=', self.id)],
            'context': {'default_attendance_case_id': self.id, 'default_employee_id': self.employee_id.id},
        }

    @api.model
    def action_run_attendance_scan(self):
        """Action invoked from UI button to trigger violation scan."""
        cases = self.env['hr.attendance'].sudo().scan_and_initiate_attendance_cases()
        new_count = len(cases) if cases else 0
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attendance Scan Executed'),
                'message': _('Attendance scan finished successfully. %d new disciplinary case(s) evaluated/generated.') % new_count,
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    # =========================================================================
    # OFFICIAL NOTICE LETTER & REPORT HELPERS
    # =========================================================================

    def action_print_notice_letter(self):
        """Download and print the official Bunna Bank Disciplinary Notice / Warning Letter PDF."""
        self.ensure_one()
        if self.state in ('draft', 'leave_adjusted', 'exonerated', 'hr_refused'):
            raise UserError(_("Notice letters cannot be printed for draft, exonerated, or refused cases."))
        return self.env.ref('discipline_management.action_report_attendance_warning_letter').report_action(self)

    def get_ethiopic_sadiss_font_css(self):
        """Loads and base64-embeds Ethiopic Sadiss font family for wkhtmltopdf."""
        return self.env['discipline.case'].get_ethiopic_sadiss_font_css()

    def get_official_bunna_logo_base64(self):
        """Returns base64 string of official Bunna Bank logo for PDF rendering."""
        return self.env['discipline.case'].get_official_bunna_logo_base64()

    def get_ethiopian_date_short(self, g_date=None):
        """Returns short Ethiopian calendar date string e.g. '28/02/2019 ዓ.ም.'."""
        self.ensure_one()
        d = g_date or self.enforced_date or self.incident_date or fields.Date.today()
        short_d, _, _ = gregorian_to_ethiopian(d)
        return short_d

    def get_ethiopian_date_long(self, g_date=None):
        """Returns full long Ethiopian calendar date string e.g. 'ጥቅምት 28 ቀን 2019 ዓ.ም.'."""
        self.ensure_one()
        d = g_date or self.enforced_date or self.incident_date or fields.Date.today()
        _, long_d, _ = gregorian_to_ethiopian(d)
        return long_d

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'አቶ' if self.notice_language != 'english' else 'Ato'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            if self.notice_language != 'english':
                return 'ወ/ሪት' if marital == 'single' else 'ወ/ሮ'
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'አቶ/ወ/ሮ' if self.notice_language != 'english' else 'Ato/W/ro'

    def get_formatted_employee_name(self):
        """Returns formatted full recipient employee name with formal salutation."""
        self.ensure_one()
        sal = self.get_salutation_label()
        emp_name = self.employee_id.name if self.employee_id else _('Staff')
        return f"{sal} {emp_name}"

    def get_punishment_display_text_amharic(self):
        """Returns clean Amharic description of the enforced sanction and financial penalty."""
        self.ensure_one()
        labels = {
            'verbal_warning': 'የቃል ማስጠንቀቂያ',
            'first_warning_penalty': 'የመጀመሪያ የጽሁፍ ማስጠንቀቂያ',
            'second_warning_penalty': 'የሁለተኛ የጽሁፍ ማስጠንቀቂያ',
            'final_warning_penalty': 'የመጨረሻ የጽሁፍ ማስጠንቀቂያ',
            'dismissal': 'ከስራ ማሰናበት (የስራ ውል መቋረጥ)',
        }
        base = labels.get(self.punishment_type, dict(self._fields['punishment_type'].selection).get(self.punishment_type, ''))
        pen_parts = []
        if self.penalty_percentage > 0.0:
            pen_parts.append(f"የ{self.penalty_percentage}% የአንድ ወር ደመወዝ ቅጣት")
        if self.fine_days > 0.0:
            pen_parts.append(f"የ{int(self.fine_days)} ቀናት የደመወዝ ቅጣት")
        if pen_parts:
            return f"{base} ከ{' እና '.join(pen_parts)} ጋር"
        return base

    def get_notice_subject_amharic(self):
        """Returns subject line in Amharic."""
        self.ensure_one()
        if self.violation_type == 'absence_dismissal' or self.punishment_type == 'dismissal':
            return "ጉዳዩ፡- ያለፈቃድ የስራ ገበታን በመተው የስራ ውል መቋረጥ (ስንብት) ውሳኔ ማሳወቂያ"
        elif self.violation_type == 'absence_prolonged':
            return "ጉዳዩ፡- በተከታታይ የስራ ቀናት ያለፈቃድ በመቅረት የተሰጠ የዲሲፕሊን ማስጠንቀቂያ እና የደመወዝ ቅጣት ውሳኔ ማሳወቂያ"
        elif self.violation_type == 'absence_minor':
            return "ጉዳዩ፡- ያለፈቃድ ከስራ ገበታ መቅረት የተሰጠ የዲሲፕሊን ማስጠንቀቂያ ማሳወቂያ"
        elif self.violation_type == 'late':
            return "ጉዳዩ፡- በተደጋጋሚ የስራ ሰዓት አለማክበር (ማርፈድ) የተሰጠ የዲሲፕሊን ማስጠንቀቂያ ማሳወቂያ"
        return "ጉዳዩ፡- የስራ ሰዓትና መገኘት የዲሲፕሊን ውሳኔ ማሳወቂያ"

    def get_notice_subject_english(self):
        """Returns subject line in English."""
        self.ensure_one()
        if self.violation_type == 'absence_dismissal' or self.punishment_type == 'dismissal':
            return "Subject: Disciplinary Decision Notice — Contract Termination / Dismissal for Job Abandonment"
        elif self.violation_type == 'absence_prolonged':
            return "Subject: Disciplinary Decision Notice — Final Written Warning & Salary Deduction for Prolonged Absence"
        elif self.violation_type == 'absence_minor':
            return "Subject: Disciplinary Decision Notice — Written Warning for Unexcused Absence"
        elif self.violation_type == 'late':
            return "Subject: Disciplinary Decision Notice — Warning for Repeated Lateness Violation"
        return "Subject: Attendance Disciplinary Decision Notice"

    def get_signatory_title(self):
        """Returns formal reviewer/signatory title."""
        self.ensure_one()
        if self.state in ('pomd_review', 'enforced') and (self.violation_type == 'absence_dismissal' or self.punishment_type == 'dismissal'):
            return "የሰው ኃይል እና ድርጅታዊ አስተዳደር ዳይሬክቶሬት (POMD) / People & Organization Management"
        elif self.state == 'director_review' or (self.signatory_id and self.signatory_id == self.director_id):
            return "የተመለከተው ዳይሬክቶሬት ዳይሬክተር / Directorate Director"
        return "የቅርብ ኃላፊ (Direct Coach / Line Manager)"
