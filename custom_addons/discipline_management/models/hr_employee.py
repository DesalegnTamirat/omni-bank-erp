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

    @api.depends('discipline_case_ids')
    def _compute_discipline_case_count(self):
        for emp in self:
            emp.discipline_case_count = len(emp.discipline_case_ids)

    def check_discipline_eligibility(self):
        """Check if employee is eligible for promotion, transfer, or internal recruitment."""
        self.ensure_one()
        if self.is_suspended:
            return (False, _('Employee is currently under active disciplinary suspension (%s).') % self.suspension_type)
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
        # Hand off to whatever transfer-request flow exists in the deployment (e.g. a
        # dedicated employee-portal wizard); this module only enforces the eligibility gate.
        return True

    def action_forced_transfer(self, new_department_id=False, new_job_id=False, reason=None):
        """FR-DIS-021.4: HR/Management-initiated Forced / Administrative Transfer.

        Unlike action_request_transfer, this deliberately bypasses the disciplinary
        eligibility gate — a forced transfer is often itself the disciplinary or
        operational reassignment action, so it must remain available even for an employee
        currently ineligible for a self-service transfer.
        """
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
        ineligible employee, block it with the required error message. Demotion enforcement
        (action_apply_demotion) bypasses this via context flag since that write IS the
        disciplinary action itself, not a promotion."""
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
