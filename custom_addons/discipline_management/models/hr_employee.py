# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Disciplinary History Smart Fields
    is_managerial = fields.Boolean(
        string='Is Managerial Staff',
        compute='_compute_is_managerial',
        store=True,
        readonly=False,
        help='Indicates whether employee belongs to Managerial Staff (uses managerial penalty rates)'
    )
    active_disciplinary_action = fields.Boolean(
        string='Has Active Disciplinary Action',
        default=False,
        help='Indicates whether employee has an active/enforced disciplinary warning or pending case',
        tracking=True
    )
    disciplinary_warning_count = fields.Integer(
        string='Total Disciplinary Warnings',
        default=0,
        readonly=True,
        tracking=True
    )
    last_disciplinary_date = fields.Date(
        string='Last Disciplinary Action Date',
        readonly=True,
        tracking=True
    )
    is_suspended = fields.Boolean(
        string='Currently Suspended',
        default=False,
        readonly=True,
        tracking=True
    )
    suspension_type = fields.Selection([
        ('with_pay', 'Suspension With Pay'),
        ('without_pay', 'Suspension Without Pay'),
    ], string='Active Suspension Type', readonly=True)

    is_ineligible_for_promotion_transfer = fields.Boolean(
        string='Ineligible for Promotion / Transfer',
        default=False,
        help='Automatically set to True when active disciplinary penalties (warnings, demotion) are enforced.',
        tracking=True
    )

    discipline_case_ids = fields.One2many(
        'discipline.case',
        'employee_id',
        string='Disciplinary Cases History'
    )
    discipline_case_count = fields.Integer(
        string='Disciplinary Cases Count',
        compute='_compute_discipline_case_count'
    )

    # -------------------------------------------------------------
    # Cross-Module Integration Fields
    # Consumable by assessment_system, custom_recruitment, EDS, etc.
    # -------------------------------------------------------------
    active_discipline_case_count = fields.Integer(
        string='Active Cases', compute='_compute_discipline_summary', store=True
    )
    has_active_disciplinary_action = fields.Boolean(
        string='Has Active Discipline Sanction', compute='_compute_discipline_summary', store=True,
        help="True if the employee has an ongoing investigation, active suspension, or active sanction."
    )
    is_discipline_suspended = fields.Boolean(
        string='Suspended by Discipline', compute='_compute_discipline_summary', store=True
    )
    latest_discipline_sanction = fields.Char(
        string='Latest Disciplinary Sanction', compute='_compute_discipline_summary', store=True
    )
    disciplinary_clearance_status = fields.Selection([
        ('cleared', 'Cleared / Good Standing'),
        ('under_investigation', 'Under Active Disciplinary Investigation'),
        ('suspended', 'Currently Suspended'),
        ('sanctioned', 'Active Sanction in Effect'),
        ('dismissed', 'Dismissed for Cause'),
    ], string='Disciplinary Clearance Status', compute='_compute_discipline_summary', store=True)

    @api.depends('discipline_case_ids', 'discipline_case_ids.state', 'discipline_case_ids.punishment_type', 'is_suspended')
    def _compute_discipline_summary(self):
        cutoff_date = fields.Date.context_today(self) - timedelta(days=365)
        for emp in self:
            cases = emp.discipline_case_ids
            active_cases = cases.filtered(lambda c: c.state not in ('draft', 'closed', 'cancelled', 'enforced'))
            emp.active_discipline_case_count = len(active_cases)

            is_suspended = emp.is_suspended or bool(cases.filtered(lambda c: getattr(c, 'is_suspended_action', False) and c.state == 'enforced'))
            emp.is_discipline_suspended = is_suspended

            is_dismissed = bool(cases.filtered(lambda c: c.punishment_type == 'dismissal' and c.state == 'enforced'))
            recent_sanctions = cases.filtered(
                lambda c: c.state == 'enforced' and c.punishment_type not in (False, 'dismissal') and (not c.final_decision_date or c.final_decision_date >= cutoff_date)
            )

            if is_dismissed:
                emp.disciplinary_clearance_status = 'dismissed'
                emp.has_active_disciplinary_action = True
            elif is_suspended:
                emp.disciplinary_clearance_status = 'suspended'
                emp.has_active_disciplinary_action = True
            elif active_cases:
                emp.disciplinary_clearance_status = 'under_investigation'
                emp.has_active_disciplinary_action = True
            elif recent_sanctions:
                emp.disciplinary_clearance_status = 'sanctioned'
                emp.has_active_disciplinary_action = True
            else:
                emp.disciplinary_clearance_status = 'cleared'
                emp.has_active_disciplinary_action = False

            last_case = cases.filtered(lambda c: c.state == 'enforced').sorted(key=lambda c: c.final_decision_date or fields.Date.today(), reverse=True)
            emp.latest_discipline_sanction = last_case[0].punishment_type if last_case else False

    @api.depends('discipline_case_ids')
    def _compute_discipline_case_count(self):
        for emp in self:
            emp.discipline_case_count = len(emp.discipline_case_ids)

    # -------------------------------------------------------------
    # Public Integration APIs for other modules
    # -------------------------------------------------------------
    def get_disciplinary_clearance(self):
        """Public API for assessment_system, promotion, and clearance workflows."""
        self.ensure_one()
        eligible, reason = self.check_discipline_eligibility()
        return {
            'is_cleared': eligible,
            'status': self.disciplinary_clearance_status or 'cleared',
            'active_cases_count': self.active_discipline_case_count,
            'latest_sanction': self.latest_discipline_sanction or False,
            'is_suspended': self.is_suspended or self.is_discipline_suspended,
            'is_ineligible_for_promotion_transfer': self.is_ineligible_for_promotion_transfer,
            'reason': reason,
        }

    @api.model
    def check_applicant_disciplinary_history(self, name=None, email=None, phone=None, national_id=None):
        """Public API for custom_recruitment: screen applicants against past dismissals and severe sanctions."""
        domain = [('state', '=', 'enforced')]
        sub_domain = []
        if email:
            sub_domain.append(('employee_id.work_email', '=ilike', email))
        if phone:
            sub_domain.append(('employee_id.mobile_phone', '=', phone))
        if national_id:
            sub_domain.append(('employee_id.barcode', '=', national_id))
        if name:
            sub_domain.append(('employee_id.name', '=ilike', name))

        if not sub_domain:
            return {'has_record': False, 'records': []}

        final_domain = domain + ['|'] * (len(sub_domain) - 1) + sub_domain
        matched_cases = self.env['discipline.case'].search(final_domain)
        is_dismissed = any(c.punishment_type == 'dismissal' for c in matched_cases)
        return {
            'has_record': bool(matched_cases),
            'record_count': len(matched_cases),
            'is_dismissed': is_dismissed,
            'cases': [{
                'case_reference': c.name,
                'offense': c.offense_id.name if c.offense_id else False,
                'punishment_type': c.punishment_type,
                'decision_date': c.final_decision_date,
            } for c in matched_cases]
        }

    def check_discipline_eligibility(self):
        """Check if employee is eligible for promotion, transfer, or internal recruitment."""
        self.ensure_one()
        if self.is_suspended or self.is_discipline_suspended:
            return (False, _('Employee is currently under active disciplinary suspension (%s).') % (self.suspension_type or 'without pay'))
        if self.is_ineligible_for_promotion_transfer:
            return (False, _('Employee is currently flagged as ineligible for promotion/transfer due to active disciplinary action.'))

        cutoff_date = fields.Date.context_today(self) - timedelta(days=365)
        active_cases = self.discipline_case_ids.filtered(
            lambda c: c.state == 'enforced' and c.final_decision_date and c.final_decision_date >= cutoff_date
        )
        if active_cases:
            case_names = ", ".join(active_cases.mapped('name'))
            return (False, _('Ineligible for promotion/recruitment due to active disciplinary record within 12 months (Cases: %s).') % case_names)

        return (True, _('Employee is eligible.'))

    @api.model
    def _cron_revert_ineligibility(self):
        """Cron job: automatically revert ineligibility flag once legal active penalty period (365 days) expires."""
        today = fields.Date.context_today(self)
        cutoff_date = today - timedelta(days=365)
        ineligible_employees = self.search([
            ('is_ineligible_for_promotion_transfer', '=', True),
            ('is_suspended', '=', False),
        ])
        for emp in ineligible_employees:
            active_recent_cases = emp.discipline_case_ids.filtered(
                lambda c: c.state == 'enforced' and c.final_decision_date and c.final_decision_date >= cutoff_date
            )
            if not active_recent_cases:
                emp.with_context(no_leave_resource_calendar_update=True).write({
                    'is_ineligible_for_promotion_transfer': False,
                    'active_disciplinary_action': False,
                })

    @api.depends('job_id', 'job_id.name')
    def _compute_is_managerial(self):
        for emp in self:
            job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
            if emp.job_id and getattr(emp.job_id, 'is_managerial', False):
                emp.is_managerial = True
            elif any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor', 'president', 'officer in charge']):
                emp.is_managerial = True
            else:
                emp.is_managerial = False

    def action_request_transfer(self):
        """FR-DIS-021.3: Self-Initiated Transfer Request must be blocked while the employee
        has an active disciplinary penalty. This is the method the employee-portal
        "Request Transfer" button should call; it either proceeds (returning an act_window
        to the standard transfer wizard/request, if installed) or raises the required
        blocking error message.
        """
        self.ensure_one()
        eligible, reason = self.check_discipline_eligibility()
        if not eligible:
            raise UserError(_(
                'Candidate is currently ineligible for transfer due to an active disciplinary penalty. %s'
            ) % reason)
        return True

    def action_forced_transfer(self, new_department_id=False, new_job_id=False, reason=None):
        """FR-DIS-021.4: HR/Management-initiated Forced / Administrative Transfer."""
        for emp in self:
            if not self.env.user.has_group('discipline_management.group_discipline_manager'):
                raise UserError(_('Only HR or Management can process a Forced / Administrative Transfer.'))
            vals = {}
            if new_department_id:
                vals['department_id'] = new_department_id
            if new_job_id:
                vals['job_id'] = new_job_id
            if vals:
                emp.sudo().with_context(no_leave_resource_calendar_update=True).write(vals)
            emp.message_post(body=_('Forced / Administrative Transfer processed by %s. %s') % (
                self.env.user.name, reason or ''
            ))
        return True

    @api.model
    def _get_promotion_ineligible_domain(self):
        """Domain fragment recruiters/hiring managers can AND into a candidate search to
        automatically filter out disciplinarily-ineligible employees (FR-DIS-021.2)."""
        return [('is_ineligible_for_promotion_transfer', '=', False), ('is_suspended', '=', False)]

    def write(self, vals):
        """FR-DIS-021.2: if an HR user manually attempts to promote (change job_id on) an
        ineligible employee, block it with the required error message."""
        if 'job_id' in vals and not self.env.context.get('discipline_demotion_in_progress'):
            for emp in self:
                new_job_id = vals.get('job_id')
                if emp.is_ineligible_for_promotion_transfer and new_job_id and new_job_id != emp.job_id.id:
                    raise ValidationError(_(
                        'Candidate is currently ineligible for promotion due to an active disciplinary '
                        'penalty. (Employee: %s)'
                    ) % emp.name)
        return super().write(vals)

    def action_view_discipline_cases(self):
        self.ensure_one()
        return {
            'name': _('Disciplinary Cases History'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id}
        }


class HrJob(models.Model):
    _inherit = 'hr.job'

    is_managerial = fields.Boolean(
        string='Is Managerial Position',
        default=False,
        help='Check if this job position belongs to Managerial Staff'
    )
