# -*- coding: utf-8 -*-
from datetime import datetime, time
from markupsafe import Markup
from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.exceptions import UserError, ValidationError


class DisciplineAttendanceActionWizard(models.TransientModel):
    _name = 'discipline.attendance.action.wizard'
    _description = 'Attendance Case Action Wizard (Leave Adjustment, Coach Exoneration & Batch HR Refusal)'

    action_type = fields.Selection([
        ('adjust_leave', 'Convert / Adjust Absent Days by Leave'),
        ('coach_exonerate', 'Acknowledge / Exonerate with Justification (Coach)'),
        ('hr_refuse', 'Refuse Attendance Case(s) (HR / POMD)'),
    ], string='Action Type', required=True, default='coach_exonerate')

    attendance_case_ids = fields.Many2many(
        'discipline.attendance.case',
        'discipline_att_case_action_wiz_rel',
        'wizard_id',
        'case_id',
        string='Selected Attendance Cases',
        required=True,
    )
    case_count = fields.Integer(compute='_compute_case_count', string='Selected Cases Count')
    employee_id = fields.Many2one('hr.employee', string='Employee')

    # Leave Conversion Fields
    leave_mode = fields.Selection([
        ('create_new', 'Convert Absence by Leave (Auto-Compute & Submit)'),
        ('existing', 'Link Existing Approved Leave Record'),
        ('manual_adjust', 'Administrative Direct Adjustment (POMD / HR Admin Override)'),
    ], string='Adjustment Method', default='create_new')

    leave_id = fields.Many2one(
        'hr.leave',
        string='Existing Leave Record',
        domain="[('employee_id', '=', employee_id), ('state', 'in', ['validate', 'validate1'])]",
    )
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        help='Select the Leave / Time Off Type to cover the unexcused absent dates.',
    )
    leave_date_from = fields.Date(string='Leave Start Date', default=fields.Date.context_today)
    leave_date_to = fields.Date(string='Leave End Date', default=fields.Date.context_today)

    reason_notes = fields.Text(
        string='Justification / Refusal Reason',
        required=True,
        help='Provide detailed justification for leave adjustment, coach exoneration, or HR refusal.',
    )

    # Leave Balance & Verification Computations
    is_self_employee = fields.Boolean(compute='_compute_is_self_employee', string='Is Subject Employee')
    can_manual_adjust = fields.Boolean(compute='_compute_can_manual_adjust', string='Can Manually Adjust')
    available_leave_balance = fields.Float(compute='_compute_leave_balance', string='Available Leave Balance (Days)')
    balance_after_adjustment = fields.Float(compute='_compute_leave_balance', string='Balance After Adjustment (Days)')
    required_leave_days = fields.Float(compute='_compute_leave_balance', string='Required Leave Days')
    requires_allocation = fields.Boolean(compute='_compute_leave_balance', string='Requires Allocation')
    has_insufficient_allocation = fields.Boolean(compute='_compute_leave_balance', string='Has Insufficient Allocation')
    leave_balance_warning = fields.Char(compute='_compute_leave_balance', string='Leave Balance Status')

    @api.depends_context('uid')
    @api.depends('employee_id')
    def _compute_is_self_employee(self):
        user = self.env.user
        for rec in self:
            emp = rec.employee_id
            rec.is_self_employee = bool(
                emp and ((emp.user_id and emp.user_id.id == user.id) or emp.id in user.employee_ids.ids)
            )

    @api.depends_context('uid')
    def _compute_can_manual_adjust(self):
        user = self.env.user
        is_hr_authority = (
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_pomd_director') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('base.group_system') or
            user._is_admin()
        )
        for rec in self:
            rec.can_manual_adjust = is_hr_authority

    def _get_effective_employee_leave_balance(self, employee, leave_type):
        """Fetch real leave balance, supporting Bunna Bank's custom accrual waterfall (hr_leave_request_custom)
        as well as native Odoo hr.leave.allocation."""
        if not employee or not leave_type:
            return 0.0, False

        total_custom = 0.0
        custom_checked = False
        # 1. Bunna custom waterfall leave balance (hr_leave_request_custom) for accrual/annual/paid time off types
        lt_name = (leave_type.name or '').lower()
        is_accrual_type = (
            getattr(leave_type, 'check_accrual_balance', False) or
            getattr(leave_type, 'is_scheduled_leave', False) or
            any(w in lt_name for w in ['paid time off', 'annual', 'pto'])
        )
        if hasattr(self.env['hr.leave'], '_get_leave_balances'):
            try:
                balances = self.env['hr.leave'].sudo()._get_leave_balances(employee)
                accrued = float(balances.get('accrued', 0.0) or 0.0)
                scheduled = float(balances.get('scheduled', 0.0) or 0.0)
                total_custom = accrued + scheduled
                custom_checked = True
                if is_accrual_type and total_custom > 0.0:
                    return round(total_custom, 2), True
            except Exception:
                pass

        # 2. Native Odoo allocation fallback
        req_alloc = getattr(leave_type, 'requires_allocation', False)
        is_alloc_required = req_alloc in (True, 'yes')
        if is_alloc_required:
            lt_ctx = leave_type.with_context(employee_id=employee.id)
            avail = getattr(lt_ctx, 'virtual_remaining_leaves', 0.0) or 0.0
            if avail > 0.0:
                return round(avail, 2), True
            if custom_checked and total_custom > 0.0:
                return round(total_custom, 2), True
            return round(avail, 2), True

        if custom_checked and total_custom > 0.0:
            return round(total_custom, 2), True

        return 999.0, False

    @api.depends('employee_id', 'holiday_status_id', 'leave_date_from', 'leave_date_to', 'attendance_case_ids')
    def _compute_leave_balance(self):
        for rec in self:
            emp = rec.employee_id
            lt = rec.holiday_status_id

            # Calculate required days
            req_days = 0.0
            if rec.attendance_case_ids:
                req_days = float(sum(c.absent_days_count for c in rec.attendance_case_ids if c.absent_days_count))
            if not req_days and rec.leave_date_from and rec.leave_date_to and rec.leave_date_to >= rec.leave_date_from:
                req_days = float((rec.leave_date_to - rec.leave_date_from).days + 1)
            rec.required_leave_days = req_days

            # Calculate available balance via custom waterfall or native allocation
            if emp and lt:
                avail, is_alloc = rec._get_effective_employee_leave_balance(emp, lt)
                rec.requires_allocation = is_alloc
                rec.available_leave_balance = avail
                rec.balance_after_adjustment = max(0.0, round(avail - req_days, 2)) if is_alloc else avail
                if is_alloc:
                    if avail <= 0.0:
                        rec.has_insufficient_allocation = True
                        rec.leave_balance_warning = _(
                            "⚠️ Zero Allocation Balance: %s has 0.0 days remaining for '%s' (%.1f day(s) required)."
                        ) % (emp.name, lt.name, req_days)
                    elif avail < req_days:
                        rec.has_insufficient_allocation = True
                        rec.leave_balance_warning = _(
                            "⚠️ Insufficient Allocation: %s has only %.2f day(s) available for '%s', but %.1f day(s) are required."
                        ) % (emp.name, avail, lt.name, req_days)
                    else:
                        rec.has_insufficient_allocation = False
                        rec.leave_balance_warning = _(
                            "✅ Sufficient Allocation: %.2f day(s) available (%.1f required, %.2f remaining after adjustment)."
                        ) % (avail, req_days, avail - req_days)
                else:
                    rec.requires_allocation = False
                    rec.has_insufficient_allocation = False
                    rec.available_leave_balance = 999.0
                    rec.balance_after_adjustment = 999.0
                    rec.leave_balance_warning = _("ℹ️ '%s' does not require allocation.") % lt.name
            else:
                rec.requires_allocation = False
                rec.has_insufficient_allocation = False
                rec.available_leave_balance = 0.0
                rec.balance_after_adjustment = 0.0
                rec.leave_balance_warning = False

    @api.depends('attendance_case_ids')
    def _compute_case_count(self):
        for rec in self:
            rec.case_count = len(rec.attendance_case_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids')
        if active_ids and self.env.context.get('active_model') == 'discipline.attendance.case' and not res.get('attendance_case_ids'):
            res['attendance_case_ids'] = [(6, 0, active_ids)]
            cases = self.env['discipline.attendance.case'].browse(active_ids)
            if len(cases) == 1:
                res['employee_id'] = cases.employee_id.id
                res['leave_date_from'] = cases.date_from
                res['leave_date_to'] = cases.date_to
        if 'holiday_status_id' in fields_list and not res.get('holiday_status_id'):
            LeaveType = self.env.get('hr.leave.type')
            if LeaveType is not None:
                # Prefer Paid Time Off or Annual Leave
                lt = LeaveType.sudo().search([('name', 'ilike', 'Paid Time Off')], limit=1)
                if not lt:
                    lt = LeaveType.sudo().search([('name', 'ilike', 'Annual')], limit=1)
                if not lt:
                    lt = LeaveType.sudo().search([('requires_allocation', '=', True)], limit=1)
                if not lt:
                    lt = LeaveType.sudo().search([], limit=1)
                if lt:
                    res['holiday_status_id'] = lt.id
        return res

    def action_confirm(self):
        self.ensure_one()
        cases = self.attendance_case_ids
        if not cases:
            raise UserError(_('No attendance disciplinary cases selected.'))

        if self.action_type == 'hr_refuse':
            cases.action_hr_refuse(refusal_reason=self.reason_notes)
            return {'type': 'ir.actions.act_window_close'}

        if self.action_type == 'coach_exonerate':
            cases.action_coach_exonerate(justification=self.reason_notes)
            return {'type': 'ir.actions.act_window_close'}

        if self.action_type == 'adjust_leave':
            today = fields.Date.context_today(self)
            for case in cases:
                if case.state in ('enforced', 'leave_adjusted', 'exonerated', 'hr_refused'):
                    raise UserError(_('Case %s is already finalized and cannot be adjusted by leave.') % case.name)

                emp = case.employee_id
                if not emp:
                    raise UserError(_('Case %s has no subject employee assigned.') % case.name)

                # =============================================================
                # METHOD 1: DIRECT ADMINISTRATIVE MANUAL ADJUSTMENT
                # =============================================================
                if self.leave_mode == 'manual_adjust':
                    if not self.can_manual_adjust:
                        raise UserError(_(
                            'Permission Denied: Direct manual leave adjustment without an approved Time Off record '
                            'is restricted to POMD Officers and HR Administrators.'
                        ))
                    case.write({
                        'state': 'leave_adjusted',
                        'punishment_type': 'leave_adjusted',
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'covered_leave_days': case.absent_days_count,
                        'justification_reason': self.reason_notes,
                        'deduction_status': 'cancelled',
                        'exonerated_by_id': self.env.user.id,
                        'exonerated_date': today,
                    })
                    pending_pens = case.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
                    if pending_pens:
                        pending_pens.write({'state': 'cancelled'})
                    case.message_post(body=Markup(_(
                        '<strong>🛡️ Administrative Leave Adjustment (Manual Override):</strong><br/>'
                        '• <strong>Authorized By:</strong> %s (POMD / HR Admin)<br/>'
                        '• <strong>Justification:</strong> %s<br/>'
                        '• <strong>Outcome:</strong> Disciplinary case closed with zero penalty.'
                    ) % (self.env.user.name, self.reason_notes)))
                    continue

                # =============================================================
                # METHOD 2: LINK EXISTING APPROVED LEAVE RECORD
                # =============================================================
                linked_leave = False
                if self.leave_mode == 'existing':
                    if not self.leave_id:
                        raise UserError(_('Please select an existing Leave record.'))
                    if self.leave_id.employee_id.id != emp.id:
                        raise UserError(_(
                            'The selected Leave record belongs to %s, but this case is for %s.'
                        ) % (self.leave_id.employee_id.name, emp.name))
                    is_self_employee = bool(
                        (emp.user_id and emp.user_id.id == self.env.user.id) or
                        emp.id in self.env.user.employee_ids.ids
                    )
                    is_approved = self.leave_id.state in ('validate', 'validate1') or getattr(self.leave_id, 'leave_request_status', False) == 'approved'
                    if not is_approved and not is_self_employee:
                        state_label = dict(self.leave_id._fields['state'].selection).get(self.leave_id.state, self.leave_id.state)
                        raise UserError(_(
                            'The selected Time Off record "%s" is in "%s" state and has not been approved yet. '
                            'Only approved Time Off records can directly adjust disciplinary absences.'
                        ) % (self.leave_id.display_name, state_label))
                    linked_leave = self.leave_id

                # =============================================================
                # METHOD 3: CREATE NEW TIME OFF REQUEST (WITH ACCRUED BALANCE VALIDATION)
                # =============================================================
                elif self.leave_mode == 'create_new':
                    if not self.holiday_status_id:
                        raise UserError(_('Please select a Time Off Type to create the leave request.'))
                    if not self.leave_date_from or not self.leave_date_to or self.leave_date_from > self.leave_date_to:
                        raise UserError(_('Please specify a valid Leave Start Date and End Date.'))

                    lt = self.holiday_status_id
                    avail, is_alloc = self._get_effective_employee_leave_balance(emp, lt)
                    # Use actual absent working days, fallback to date range span
                    req_days = float(case.absent_days_count or ((self.leave_date_to - self.leave_date_from).days + 1))

                    # Strict Allocation & Accrual Check
                    if is_alloc:
                        if avail <= 0.0:
                            raise ValidationError(_(
                                'Cannot convert absence to leave: Employee %(employee)s has 0.0 remaining days for %(leave_type)s.\n\n'
                                'An active leave allocation or accrued balance must exist before this absence can be covered.'
                            ) % {'employee': emp.name, 'leave_type': lt.name})
                        if avail < req_days:
                            raise ValidationError(_(
                                'Insufficient Leave Allocation / Accrued Balance:\n'
                                '• Employee: %(employee)s\n'
                                '• Leave Type: %(leave_type)s\n'
                                '• Available Balance: %(avail).2f day(s)\n'
                                '• Required Working Days: %(req).1f day(s) (%(dfrom)s to %(dto)s)\n\n'
                                'The required absent days exceed the employee\'s available accrued balance.'
                            ) % {
                                'employee': emp.name,
                                'leave_type': lt.name,
                                'avail': avail,
                                'req': req_days,
                                'dfrom': self.leave_date_from,
                                'dto': self.leave_date_to,
                            })

                    # Role check: Is current user the subject employee or an authority?
                    is_self_employee = bool(
                        (emp.user_id and emp.user_id.id == self.env.user.id) or
                        emp.id in self.env.user.employee_ids.ids
                    )

                    LeaveModel = self.env['hr.leave'].sudo().with_user(SUPERUSER_ID).with_context(
                        leave_fast_create=True,
                        leave_skip_state_check=True,
                        leave_skip_date_check=True,
                        mail_create_nolog=True,
                        tracking_disable=True,
                    )
                    leave_vals = {
                        'name': _('Attendance Case %s Adjustment: %s') % (case.name, self.reason_notes or _('Unexcused absence adjustment')),
                        'employee_id': emp.id,
                        'holiday_status_id': lt.id,
                        'leave_start_date': self.leave_date_from,
                        'leave_end_date': self.leave_date_to,
                        'request_date_from': self.leave_date_from,
                        'request_date_to': self.leave_date_to,
                        'date_from': datetime.combine(self.leave_date_from, time(8, 0, 0)),
                        'date_to': datetime.combine(self.leave_date_to, time(17, 0, 0)),
                        'number_of_days': req_days,
                        'computed_leave': req_days,
                        'custom_saved': True,
                    }

                    if is_self_employee:
                        # Employee self-submission: Needs Coach approval
                        leave_vals.update({
                            'leave_request_status': 'notify',
                            'state': 'confirm',
                            'notified_date': fields.Datetime.now(),
                        })
                    else:
                        # Coach / Director / POMD / HR direct approval
                        leave_vals.update({
                            'leave_request_status': 'approved',
                            'state': 'validate',
                        })

                    try:
                        linked_leave = LeaveModel.create(leave_vals)
                        if not is_self_employee:
                            # Direct approval flow for Coach / Manager / HR
                            try:
                                linked_leave.with_user(SUPERUSER_ID).with_context(
                                    leave_fast_create=True,
                                    leave_skip_state_check=True,
                                    leave_skip_date_check=True,
                                ).action_approve()
                            except Exception:
                                linked_leave.with_user(SUPERUSER_ID).with_context(
                                    leave_fast_create=True,
                                ).write({
                                    'leave_request_status': 'approved',
                                    'state': 'validate',
                                })
                    except Exception as err:
                        raise UserError(_(
                            'Unable to create Time Off request for %s:\n%s'
                        ) % (emp.name, str(err)))

                # =============================================================
                # ATTACH LEAVE & PROCESS ACCORDING TO ROLE
                # =============================================================
                if linked_leave:
                    is_self_employee = bool(
                        (emp.user_id and emp.user_id.id == self.env.user.id) or
                        emp.id in self.env.user.employee_ids.ids
                    )
                    is_leave_pending = (
                        linked_leave.state in ('draft', 'confirm') or
                        getattr(linked_leave, 'leave_request_status', False) in ('draft', 'fetch', 'notify')
                    )

                    case.write({
                        'leave_id': linked_leave.id,
                        'justification_reason': self.reason_notes,
                    })

                    if is_self_employee and is_leave_pending:
                        # Case remains open pending Coach approval
                        case.message_post(body=Markup(_(
                            '<strong>📝 Time Off Request Submitted for Absence Adjustment:</strong><br/>'
                            '• <strong>Employee:</strong> %s<br/>'
                            '• <strong>Leave Request:</strong> %s (%.1f working day(s), %s to %s)<br/>'
                            '• <strong>Status:</strong> Pending Coach / Line Manager Approval.<br/>'
                            '• <strong>Justification:</strong> %s'
                        ) % (
                            emp.name,
                            linked_leave.display_name or f"LR-{linked_leave.id}",
                            case.absent_days_count or linked_leave.number_of_days,
                            self.leave_date_from,
                            self.leave_date_to,
                            self.reason_notes or 'None'
                        )))
                        # Schedule activity for coach
                        if case.coach_id and case.coach_id.user_id:
                            try:
                                case.activity_schedule(
                                    'mail.mail_activity_data_todo',
                                    summary=_('Approve Leave Adjustment: %s (%.1f days)') % (case.name, case.absent_days_count or linked_leave.number_of_days),
                                    note=_('%s has submitted Leave Request %s to adjust unexcused absence. Please review and approve.') % (emp.name, linked_leave.display_name),
                                    user_id=case.coach_id.user_id.id,
                                )
                            except Exception:
                                pass
                    else:
                        # Approved leave: run intelligent coverage recheck to close case
                        case.action_recheck_leave_coverage(silent=True)

            return {'type': 'ir.actions.act_window_close'}
