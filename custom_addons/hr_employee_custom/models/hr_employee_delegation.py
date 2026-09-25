import logging
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)



class HrEmployee(models.Model):
    """Extend hr.employee with a helper used by the delegation visibility
    ir.rule (security/security_delegation.xml). Kept as a plain method
    (not a compute) so it can be called directly from a domain_force
    expression: user.env['hr.employee']._get_delegation_visible_employee_ids()
    """
    _inherit = 'hr.employee'

    def _get_delegated_subordinate_ids(self):
        if not self:
            return []
        today = fields.Date.today()
        active_delegations = self.env['hr.employee.delegation'].sudo().search([
            ('delegate_id', 'in', self.ids),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        if not active_delegations:
            return []
        delegators = active_delegations.mapped('employee_id')
        subs = self.env['hr.employee'].sudo().search([
            '|',
            ('coach_id', 'in', delegators.ids),
            ('parent_id', 'in', delegators.ids)
        ])
        return subs.ids

    def _get_delegation_visible_employee_ids(self):
        emp = self.env.user.employee_id
        Delegation = self.env['hr.employee.delegation'].sudo()
        visible_ids = set()

        if emp:
            visible_ids.add(emp.id)

            # Direct and recursive indirect subordinates/coachees of own employee
            direct_and_indirect = self.env['hr.employee'].sudo().search([
                '|',
                ('coach_id', '=', emp.id),
                ('parent_id', '=', emp.id)
            ])
            visible_ids.update(direct_and_indirect.ids)

            # Recursive subordinates traversing hierarchy downward
            current_level = direct_and_indirect
            visited = set(direct_and_indirect.ids)
            visited.add(emp.id)
            while current_level:
                sub_level = self.env['hr.employee'].sudo().search([
                    '|',
                    ('coach_id', 'in', current_level.ids),
                    ('parent_id', 'in', current_level.ids)
                ])
                new_subs = sub_level.filtered(lambda e: e.id not in visited)
                if not new_subs:
                    break
                visible_ids.update(new_subs.ids)
                visited.update(new_subs.ids)
                current_level = new_subs

            # Active delegations where this employee is acting as delegate
            today = fields.Date.today()
            active_as_delegate = Delegation.search([
                ('delegate_id', '=', emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            if active_as_delegate:
                delegating_managers = active_as_delegate.mapped('employee_id')
                visible_ids.update(delegating_managers.ids)
                # Delegated subordinates of active manager
                delegated_subs = self.env['hr.employee'].sudo().search([
                    '|',
                    ('coach_id', 'in', delegating_managers.ids),
                    ('parent_id', 'in', delegating_managers.ids)
                ])
                visible_ids.update(delegated_subs.ids)

        visible_ids.discard(False)
        return list(visible_ids)








class HrEmployeeDelegation(models.Model):
    _name = "hr.employee.delegation"
    _description = "Manager Employee Delegation"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'archive.mixin']
    _order = "id desc"
    _rec_name = "name"


    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Draft'),
        tracking=True
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string="Manager / Delegator",
        required=True,
        default=lambda self: self._default_employee_id(),
        tracking=True
    )
    manager_job_id = fields.Many2one(
        'hr.job',
        string="Job Position",
        related="employee_id.job_position",
        compute_sudo=True,
        readonly=True
    )
    manager_department_id = fields.Many2one(
        'hr.department',
        string="Department",
        related="employee_id.department_id",
        compute_sudo=True,
        readonly=True
    )

    absence_reason = fields.Char(
        string="Reason for Absence",
        help="Reason or details for delegation (e.g. Mission, Training, Leave)",
        tracking=True
    )
    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    include_sub_level_staff = fields.Boolean(
        string="Include Sub-level Staff",
        help="If enabled, indirect subordinates (subordinates of direct staff) will also be included in delegate options."
    )
    direct_coach_ids = fields.Many2many(
        'hr.employee',
        string="Direct Coaches",
        compute="_compute_direct_coach_ids",
        compute_sudo=True
    )
    filter_coach_id = fields.Many2one(
        'hr.employee',
        string="Filter by Direct Coach",
        domain="[('id', 'in', direct_coach_ids)]",
        help="Optional: Select a direct coach to narrow down sub-level staff to that specific team."
    )
    allowed_delegate_ids = fields.Many2many(
        'hr.employee',
        string="Allowed Delegates",
        compute="_compute_allowed_delegate_ids",
        compute_sudo=True
    )

    delegate_id = fields.Many2one(
        'hr.employee',
        string="Delegated Staff / Delegate",
        required=True,
        domain="[('id', 'in', allowed_delegate_ids)]",
        tracking=True
    )
    delegate_coach_name = fields.Char(
        string="Delegate's Direct Coach",
        compute="_compute_delegate_coach_name",
        store=True,
        compute_sudo=True,
        help="The direct manager/coach of the selected delegate."
    )
    delegate_job_id = fields.Many2one(
        'hr.job',
        string="Delegate Job Position",
        related="delegate_id.job_position",
        compute_sudo=True,
        readonly=True
    )


    notification_recipient_ids = fields.Many2many(
        'hr.employee',
        'hr_delegation_notification_rel',
        'delegation_id',
        'employee_id',
        string="The following employees will receive delegation notifications",
        help="Adjustable list of employees and leaders to receive delegation notice upon submission"
    )
    stakeholder_ids = fields.One2many(
        'hr.employee.delegation.stakeholder',
        'delegation_id',
        string="Employees to Notify",
        copy=True
    )


    is_active_delegation = fields.Boolean(
        string="Is Active Today",
        compute="_compute_is_active_delegation",
        search="_search_is_active_delegation"
    )
    is_manager_coach = fields.Boolean(
        string="Is Coach / Manager",
        compute="_compute_is_manager_coach",
        help="True if the selected delegating employee is a direct coach or manager of at least one staff member."
    )
    employee_display_name = fields.Char(
        string="Manager / Delegator",
        compute="_compute_display_names",
        compute_sudo=True,
        store=True
    )
    delegate_display_name = fields.Char(
        string="Delegated Staff / Delegate",
        compute="_compute_display_names",
        compute_sudo=True,
        store=True
    )
    manager_job_name = fields.Char(
        string="Job Position",
        compute="_compute_display_names",
        compute_sudo=True,
        store=True
    )
    manager_department_name = fields.Char(
        string="Department",
        compute="_compute_display_names",
        compute_sudo=True,
        store=True
    )
    delegate_job_name = fields.Char(
        string="Delegate Job Position",
        compute="_compute_display_names",
        compute_sudo=True,
        store=True
    )
    notification_recipients_display = fields.Html(
        string="Notification Recipients",
        compute="_compute_notification_recipients_display",
        compute_sudo=True,
        store=False
    )



    cancellation_reason = fields.Text(
        string="Cancellation Reason",
        readonly=True,
        copy=False,
        tracking=True
    )
    cancellation_date = fields.Date(
        string="Cancellation Date",
        readonly=True,
        copy=False,
        tracking=True
    )
    cancelled_by_id = fields.Many2one(
        'res.users',
        string="Cancelled By",
        readonly=True,
        copy=False,
        tracking=True
    )

    leave_request_id = fields.Many2one(
        'leave.request',
        string="Related Leave Request",
        ondelete='cascade',
        readonly=True
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('submitted', 'Submitted'), ('cancelled', 'Cancelled')],
        string="Status",
        default='draft',
        tracking=True
    )
    is_requestor = fields.Boolean(
        string="Is Requestor",
        compute="_compute_is_requestor"
    )
    delegated_approval_count = fields.Integer(
        string="Pending Approvals",
        compute="_compute_delegated_approval_count"
    )

    def _compute_delegated_approval_count(self):
        current_uid = self.env.uid
        today = fields.Date.today()
        for rec in self:
            count = 0
            if rec.state == 'submitted' and rec.start_date and rec.end_date and rec.start_date <= today <= rec.end_date:
                if rec.delegate_id and rec.delegate_id.user_id.id == current_uid:
                    mgr_user = rec.employee_id.user_id
                    if mgr_user:
                        count += self.env['mail.activity'].sudo().search_count([
                            ('user_id', '=', mgr_user.id),
                            ('res_model', 'not in', ['hr.employee', 'hr.employee.delegation', 'hr.attendance', 'mail.channel', 'mail.activity', 'discuss.channel'])
                        ])

                    # Also count attendance preapprovals
                    if 'attendance.preapproval' in self.env:
                        subs = self.env['hr.employee'].sudo().search([
                            '|', ('parent_id', '=', rec.employee_id.id), ('coach_id', '=', rec.employee_id.id)
                        ])
                        if subs:
                            count += self.env['attendance.preapproval'].sudo().search_count([
                                ('employee_id', 'in', subs.ids),
                                ('state', '=', 'requested')
                            ])
            rec.delegated_approval_count = count

    def action_view_delegated_approvals(self):
        self.ensure_one()
        self.env['hr.delegated.approval']._refresh_delegated_approvals(delegation_id=self.id)
        return {
            'name': _("Delegated Approvals: %s") % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.delegated.approval',
            'view_mode': 'list,form',
            'domain': [('delegation_id', '=', self.id)],
            'context': {'create': False, 'delete': False},
        }

    def _compute_is_requestor(self):
        current_uid = self.env.uid
        for rec in self:
            rec.is_requestor = bool(rec.employee_id and rec.employee_id.user_id.id == current_uid)


    def _ensure_mandatory_talent_director_notified(self):
        """Ensures that Director - Talent Management Directorate is present in stakeholder_ids."""
        for rec in self:
            has_talent_director = any(
                'Talent Management' in (s.job_name or '') or
                'Talent Management' in (s.department_name or '') or
                'Talent Management' in (s.category or '') or
                'People Operations Management' in (s.job_name or '') or
                'HR Director' in (s.job_name or '')
                for s in rec.stakeholder_ids
            )
            if not has_talent_director:
                director_emp = self.env['hr.employee'].sudo().search([
                    '|', '|', '|',
                    ('job_position.name', 'ilike', 'Talent Management'),
                    ('job_position.name', 'ilike', 'People Operations Management Director'),
                    ('job_position.name', 'ilike', 'HR Director'),
                    ('job_name', 'ilike', 'Talent Management')
                ], limit=1)
                if director_emp:
                    self.env['hr.employee.delegation.stakeholder'].sudo().create({
                        'delegation_id': rec.id,
                        'employee_id': director_emp.id,
                        'name': director_emp.name or _('Director - Talent Management Directorate'),
                        'work_email': director_emp.work_email or '',
                        'department_name': director_emp.department_id.name if director_emp.department_id else '',
                        'job_name': director_emp.job_position.name if director_emp.job_position else _('Director - Talent Management Directorate'),
                        'category': 'Talent Management Directorate',
                    })
                else:
                    self.env['hr.employee.delegation.stakeholder'].sudo().create({
                        'delegation_id': rec.id,
                        'name': _('Director - Talent Management Directorate'),
                        'job_name': _('Director - Talent Management Directorate'),
                        'category': 'Talent Management Directorate',
                    })

    def _sync_notification_recipients(self):
        for rec in self:
            emp_ids = rec.stakeholder_ids.mapped('employee_id').ids
            if emp_ids:
                rec.sudo().write({'notification_recipient_ids': [(6, 0, emp_ids)]})

    def action_submit(self):
        for rec in self:
            if not rec.delegate_id:
                raise ValidationError(_("Please select a delegated staff member before submitting."))
            if not rec.is_manager_coach and not rec.leave_request_id:
                raise ValidationError(_("Only managerial employees with direct staff under them can submit delegation requests."))

            # If stakeholder_ids is empty or only contains dummy blank rows, regenerate
            valid_stakeholders = rec.stakeholder_ids.filtered(
                lambda s: s.work_email or s.department_name or s.job_name or (s.name and s.name != _('Employee') and s.name != 'Employee')
            )
            if not valid_stakeholders and rec.employee_id:
                rec._set_default_notification_recipients()
            else:
                rec._ensure_mandatory_talent_director_notified()

            vals = {'state': 'submitted'}
            if not rec.name or rec.name in (_('New'), _('Draft'), 'New', 'Draft', '/'):
                seq = self.env['ir.sequence'].sudo().next_by_code('hr.employee.delegation')
                if seq:
                    vals['name'] = seq
            rec.write(vals)
            rec._sync_notification_recipients()
            rec._send_delegation_notifications()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Delegation Submitted"),
                'message': _("Delegation request submitted with reference %s and notifications sent to selected recipients.") % rec.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }


    def action_delete_draft(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft delegations can be deleted."))
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delegation Requests'),
            'res_model': 'hr.employee.delegation',
            'view_mode': 'list,form',
            'target': 'main',
        }

    def action_cancel_delegation(self):
        self.ensure_one()
        if self.state == 'draft':
            self._cancel_and_notify(
                reason=_("Draft request cancelled by delegator."),
                cancellation_date=fields.Date.today(),
                cancelled_by=self.env.user
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Delegation Cancelled"),
                    'message': _("Draft delegation request has been cancelled."),
                    'type': 'warning',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                }
            }

        # For submitted/active delegations: open cancellation wizard
        return {
            'name': _("Cancel Delegation"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.delegation.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_delegation_id': self.id,
                'active_id': self.id,
            }
        }

    def _cancel_and_notify(self, reason, cancellation_date, cancelled_by):
        for rec in self:
            was_submitted = (rec.state == 'submitted')
            rec.write({
                'state': 'cancelled',
                'active': False,
                'cancellation_reason': reason,
                'cancellation_date': cancellation_date,
                'cancelled_by_id': cancelled_by.id,
            })

            # Unlink prior active delegation activities
            model = self.env.ref('hr_employee_custom.model_hr_employee_delegation', raise_if_not_found=False)
            if model:
                activities = self.env['mail.activity'].sudo().search([
                    ('res_model_id', '=', model.id),
                    ('res_id', '=', rec.id)
                ])
                activities.unlink()

            if was_submitted:
                rec._send_cancellation_notifications(reason, cancellation_date, cancelled_by)
            else:
                rec.message_post(body=_("Draft delegation request has been cancelled by %s.") % cancelled_by.name)



    def _send_cancellation_notifications(self, reason, cancellation_date, cancelled_by):
        for rec in self:
            recip_employees = rec.notification_recipient_ids
            if rec.delegate_id and rec.delegate_id not in recip_employees:
                recip_employees |= rec.delegate_id

            if not recip_employees:
                continue

            partners = recip_employees.sudo().mapped('user_id.partner_id').filtered(lambda p: p)

            body = _(
                "<strong>Managerial Delegation Cancelled</strong><br/>"
                "<strong>Manager:</strong> %(manager)s<br/>"
                "<strong>Former Delegate:</strong> %(delegate)s<br/>"
                "<strong>Scheduled Period:</strong> %(start)s to %(end)s<br/>"
                "<strong>Effective Cancellation Date:</strong> %(cancel_date)s<br/>"
                "<strong>Cancelled By:</strong> %(cancelled_by)s<br/>"
                "<strong>Reason:</strong> %(reason)s<br/>"
                "<em>Delegated authority has been revoked and regular reporting hierarchy restored.</em>"
            ) % {
                'manager': rec.employee_id.name,
                'delegate': rec.delegate_id.name,
                'start': rec.start_date,
                'end': rec.end_date,
                'cancel_date': cancellation_date,
                'cancelled_by': cancelled_by.name,
                'reason': reason,
            }

            if partners:
                rec.sudo().message_post(
                    body=Markup(body),
                    partner_ids=partners.ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )


            # Create In-App activity / Clock notification for Delegate and Stakeholders
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            model = self.env.ref('hr_employee_custom.model_hr_employee_delegation', raise_if_not_found=False)
            if activity_type and model:
                for emp in recip_employees:
                    if emp.user_id:
                        is_delegate = (emp.id == rec.delegate_id.id)
                        if is_delegate:
                            summary = _("Delegation Revoked: %s") % rec.name
                            note = _(
                                "Your delegated authority from %s has ended as of %s. Reason: %s"
                            ) % (rec.employee_id.name, cancellation_date, reason)
                        else:
                            summary = _("Delegation Cancelled: %s") % rec.name
                            note = _(
                                "Delegation from %s to %s has been cancelled effective %s. Reason: %s"
                            ) % (rec.employee_id.name, rec.delegate_id.name, cancellation_date, reason)

                        self.env['mail.activity'].sudo().create({
                            'activity_type_id': activity_type.id,
                            'summary': summary,
                            'note': note,
                            'res_model_id': model.id,
                            'res_id': rec.id,
                            'user_id': emp.user_id.id,
                            'date_deadline': cancellation_date,
                        })





    # -------------------------------------------------------------------------
    # DEFAULTS & COMPUTES
    # -------------------------------------------------------------------------


    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        emp_id = res.get('employee_id')
        if not emp_id:
            emp = self.env.user.employee_id.sudo() if self.env.user.employee_id else False
            if emp:
                res['employee_id'] = emp.id
                emp_id = emp.id
        else:
            emp = self.env['hr.employee'].sudo().browse(emp_id)

        if emp and 'stakeholder_ids' in fields_list:
            lines = self._get_default_stakeholder_lines(emp)
            res['stakeholder_ids'] = [(0, 0, l) for l in lines]
        return res

    def _default_employee_id(self):
        return self.env.user.employee_id.id if self.env.user.employee_id else False

    @api.depends('employee_id')
    def _compute_is_manager_coach(self):
        for rec in self:
            if not rec.employee_id:
                rec.is_manager_coach = False
                continue
            count = self.env['hr.employee'].sudo().search_count([
                '|',
                ('coach_id', '=', rec.employee_id.id),
                ('parent_id', '=', rec.employee_id.id)
            ])
            rec.is_manager_coach = bool(count > 0)

    @api.depends('employee_id', 'delegate_id')
    def _compute_display_names(self):
        """Use sudo to safely read employee names regardless of the viewer's hierarchy access."""
        for rec in self:
            emp = self.env['hr.employee'].sudo().browse(rec.employee_id.id) if rec.employee_id else False
            delegate = self.env['hr.employee'].sudo().browse(rec.delegate_id.id) if rec.delegate_id else False
            rec.employee_display_name = emp.name if emp else ''
            rec.delegate_display_name = delegate.name if delegate else ''
            rec.manager_job_name = emp.job_position.name if (emp and emp.job_position) else (emp.job_name if emp else '')
            rec.manager_department_name = emp.department_id.name if (emp and emp.department_id) else ''
            rec.delegate_job_name = delegate.job_position.name if (delegate and delegate.job_position) else (delegate.job_name if delegate else '')

    @api.depends('stakeholder_ids', 'stakeholder_ids.name', 'stakeholder_ids.work_email', 'stakeholder_ids.department_name', 'stakeholder_ids.job_name', 'stakeholder_ids.category')
    def _compute_notification_recipients_display(self):
        for rec in self:
            stakeholders = rec.stakeholder_ids
            if stakeholders:
                rows = "".join([
                    f"<tr><td><b>{s.name}</b></td><td>{s.work_email or '-'}</td><td>{s.department_name or '-'}</td><td>{s.job_name or '-'}</td><td><span class='badge bg-light text-dark'>{s.category or '-'}</span></td></tr>"
                    for s in stakeholders
                ])
                rec.notification_recipients_display = Markup(f"""
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Employee Name</th>
                                <th>Work Email</th>
                                <th>Department</th>
                                <th>Job Position</th>
                                <th>Role / Category</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                """)
            else:
                rec.notification_recipients_display = Markup("<p class='text-muted'>No notification employees assigned.</p>")




    @api.depends('employee_id', 'state')
    def _compute_direct_coach_ids(self):
        for rec in self:
            if not rec.employee_id or rec.state != 'draft':
                rec.direct_coach_ids = False
                continue
            direct_coaches = self.env['hr.employee'].sudo().search([
                '|',
                ('coach_id', '=', rec.employee_id.id),
                ('parent_id', '=', rec.employee_id.id)
            ])
            rec.direct_coach_ids = direct_coaches

    @api.depends('delegate_id', 'delegate_id.coach_id', 'delegate_id.parent_id')
    def _compute_delegate_coach_name(self):
        for rec in self:
            if rec.delegate_id:
                coach = rec.delegate_id.sudo().coach_id or rec.delegate_id.sudo().parent_id
                rec.delegate_coach_name = coach.name if coach else False
            else:
                rec.delegate_coach_name = False

    @api.depends('employee_id', 'include_sub_level_staff', 'filter_coach_id', 'start_date', 'end_date', 'state')
    def _compute_allowed_delegate_ids(self):
        for rec in self:
            if not rec.employee_id or rec.state != 'draft':
                rec.allowed_delegate_ids = False
                continue


            # If user selected a specific direct coach to filter by
            if rec.include_sub_level_staff and rec.filter_coach_id:
                team_staff = self.env['hr.employee'].sudo().search([
                    '|',
                    ('coach_id', '=', rec.filter_coach_id.id),
                    ('parent_id', '=', rec.filter_coach_id.id)
                ])
                allowed_ids = set(team_staff.ids)
                allowed_ids.add(rec.filter_coach_id.id)
            else:
                # Fetch all direct coachees/subordinates
                direct_staff = self.env['hr.employee'].sudo().search([
                    '|',
                    ('coach_id', '=', rec.employee_id.id),
                    ('parent_id', '=', rec.employee_id.id)
                ])
                allowed_ids = set(direct_staff.ids)

                if rec.include_sub_level_staff and direct_staff:
                    # Recursively fetch indirect subordinates
                    current_level = direct_staff
                    visited = set(direct_staff.ids)
                    visited.add(rec.employee_id.id)

                    while current_level:
                        sub_staff = self.env['hr.employee'].sudo().search([
                            '|',
                            ('coach_id', 'in', current_level.ids),
                            ('parent_id', 'in', current_level.ids)
                        ])
                        new_sub_staff = sub_staff.filtered(lambda e: e.id not in visited)
                        if not new_sub_staff:
                            break
                        allowed_ids.update(new_sub_staff.ids)
                        visited.update(new_sub_staff.ids)
                        current_level = new_sub_staff

            # Exclude self
            allowed_ids.discard(rec.employee_id.id)

            # If dates are specified, exclude busy employees from active submitted delegations
            if rec.start_date and rec.end_date:
                rec_id = rec.id if isinstance(rec.id, int) else False
                busy_delegates = self.env['hr.employee.delegation'].sudo().search([
                    ('id', '!=', rec_id),
                    ('state', '=', 'submitted'),
                    ('start_date', '<=', rec.end_date),
                    ('end_date', '>=', rec.start_date),
                ])
                # Exclude employees currently acting as delegates in active submitted delegations
                allowed_ids.difference_update(busy_delegates.mapped('delegate_id.id'))
                # Exclude employees who have delegated their own authority
                allowed_ids.difference_update(busy_delegates.mapped('employee_id.id'))

            rec.allowed_delegate_ids = self.env['hr.employee'].sudo().browse(list(allowed_ids))



    @api.depends('start_date', 'end_date', 'state')
    def _compute_is_active_delegation(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_active_delegation = bool(
                rec.state == 'submitted' and rec.start_date and rec.end_date and rec.start_date <= today <= rec.end_date
            )

    def _search_is_active_delegation(self, operator, value):
        today = fields.Date.today()
        if (operator in ('=', '==') and value) or (operator in ('!=', '<>') and not value):
            return [('state', '=', 'submitted'), ('start_date', '<=', today), ('end_date', '>=', today)]
        else:
            return ['|', '|', ('state', '!=', 'submitted'), ('start_date', '>', today), ('end_date', '<', today)]


    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            lines = self._get_default_stakeholder_lines(self.employee_id)
            self.stakeholder_ids = [(5, 0, 0)] + [(0, 0, l) for l in lines]
            self.notification_recipient_ids = [(6, 0, [l['employee_id'] for l in lines if l.get('employee_id')])]

    @api.onchange('include_sub_level_staff', 'filter_coach_id', 'employee_id', 'start_date', 'end_date')
    def _onchange_delegate_options(self):
        if not self.include_sub_level_staff and self.filter_coach_id:
            self.filter_coach_id = False
        self._compute_allowed_delegate_ids()
        if self.delegate_id and self.delegate_id not in self.allowed_delegate_ids:
            self.delegate_id = False
        return {
            'domain': {
                'delegate_id': [('id', 'in', self.allowed_delegate_ids.ids)]
            }
        }

    def _get_default_stakeholder_lines(self, manager_employee):
        if not manager_employee:
            return []
        manager = manager_employee.sudo()
        lines = []

        # Fetch visible/accessible employee IDs for the current user environment
        accessible_emp_ids = set()
        if self.env.user and self.env.user.employee_id:
            accessible_emp_ids = set(self.env.user.employee_id._get_delegation_visible_employee_ids())

        def _emp_job_name(e):
            if not e:
                return ''
            if hasattr(e, 'job_position') and e.job_position:
                return e.job_position.name or ''
            if hasattr(e, 'job_id') and e.job_id:
                return e.job_id.name or ''
            if hasattr(e, 'job_name') and e.job_name:
                return e.job_name or ''
            return ''

        def _emp_dept_name(e):
            if not e or not e.department_id:
                return ''
            return e.department_id.name or ''

        # 1. Immediate Coach / Manager
        imm_coach = manager.coach_id or manager.parent_id
        if imm_coach and imm_coach.id != manager.id:
            emp_ref = imm_coach.id if imm_coach.id in accessible_emp_ids else False
            lines.append({
                'employee_id': emp_ref,
                'name': imm_coach.name or _('Direct Manager / Coach'),
                'work_email': imm_coach.work_email or '',
                'department_name': _emp_dept_name(imm_coach),
                'job_name': _emp_job_name(imm_coach),
                'category': 'Direct Manager / Coach',
            })

            # 2. Coach of Coach (Higher Leadership)
            coach_of_coach = imm_coach.coach_id or imm_coach.parent_id
            if coach_of_coach and coach_of_coach.id not in [manager.id, imm_coach.id]:
                emp_ref2 = coach_of_coach.id if coach_of_coach.id in accessible_emp_ids else False
                lines.append({
                    'employee_id': emp_ref2,
                    'name': coach_of_coach.name or _('Higher Leadership'),
                    'work_email': coach_of_coach.work_email or '',
                    'department_name': _emp_dept_name(coach_of_coach),
                    'job_name': _emp_job_name(coach_of_coach),
                    'category': 'Higher Leadership',
                })

        # 3. Direct Staff under manager
        direct_staff = self.env['hr.employee'].sudo().search([
            '|', ('coach_id', '=', manager.id), ('parent_id', '=', manager.id),
            ('id', '!=', manager.id)
        ])
        for st in direct_staff:
            emp_ref_st = st.id if st.id in accessible_emp_ids else False
            lines.append({
                'employee_id': emp_ref_st,
                'name': st.name or _('Direct Staff'),
                'work_email': st.work_email or '',
                'department_name': _emp_dept_name(st),
                'job_name': _emp_job_name(st),
                'category': 'Direct Staff',
            })

        # 4. Director - Talent Management Directorate / People Operations Management Director / HR Director
        talent_mgmt = self.env['hr.employee'].sudo().search([
            '|', '|', '|',
            ('job_position.name', 'ilike', 'Talent Management'),
            ('job_position.name', 'ilike', 'People Operations Management Director'),
            ('job_position.name', 'ilike', 'HR Director'),
            ('job_name', 'ilike', 'Talent Management')
        ])
        for tm in talent_mgmt:
            emp_ref_tm = tm.id if tm.id in accessible_emp_ids else False
            lines.append({
                'employee_id': emp_ref_tm,
                'name': tm.name or _('Director - Talent Management Directorate'),
                'work_email': tm.work_email or '',
                'department_name': _emp_dept_name(tm),
                'job_name': _emp_job_name(tm) or _('Director - Talent Management Directorate'),
                'category': 'Talent Management Directorate',
            })

        # 5. Chief People and Culture Officer
        cpc = self.env['hr.employee'].sudo().search([
            '|',
            ('job_position.name', 'ilike', 'Chief People and Culture'),
            ('job_name', 'ilike', 'Chief People and Culture')
        ])
        for c in cpc:
            emp_ref_c = c.id if c.id in accessible_emp_ids else False
            lines.append({
                'employee_id': emp_ref_c,
                'name': c.name or _('Chief People and Culture Officer'),
                'work_email': c.work_email or '',
                'department_name': _emp_dept_name(c),
                'job_name': _emp_job_name(c),
                'category': 'Corporate HR Leadership',
            })

        # Deduplicate lines by work_email or name + category
        seen_keys = set()
        unique_lines = []
        for l in lines:
            key = (l.get('employee_id'), (l.get('work_email') or '').strip().lower(), (l.get('name') or '').strip())
            if key not in seen_keys:
                seen_keys.add(key)
                unique_lines.append(l)
        return unique_lines

    def _get_default_notification_recipients(self):
        self.ensure_one()
        lines = self._get_default_stakeholder_lines(self.employee_id)
        return [l['employee_id'] for l in lines if l.get('employee_id')]

    def _set_default_notification_recipients(self):
        for rec in self:
            if not rec.employee_id:
                continue
            lines = self._get_default_stakeholder_lines(rec.employee_id)
            rec.stakeholder_ids.sudo().unlink()
            unique_lines = [(0, 0, l) for l in lines]
            recip_ids = [l['employee_id'] for l in lines if l.get('employee_id')]
            rec.sudo().write({
                'stakeholder_ids': unique_lines,
                'notification_recipient_ids': [(6, 0, recip_ids)]
            })

    def action_reset_default_recipients(self):
        for rec in self:
            rec._set_default_notification_recipients()




    # -------------------------------------------------------------------------
    # CONSTRAINS & VALIDATIONS
    # -------------------------------------------------------------------------
    @api.constrains('start_date', 'end_date')
    def _check_delegation_dates(self):
        today = fields.Date.today()
        for rec in self:
            if rec.end_date and rec.start_date and rec.end_date < rec.start_date:
                raise ValidationError(_("Delegation end date (%s) cannot be earlier than start date (%s).") % (rec.end_date, rec.start_date))

            # Validate start_date not in past for new manual records
            if rec.start_date and rec.start_date < today:
                if not rec.leave_request_id and (self.env.context.get('check_past_date', True)):
                    raise ValidationError(_("Delegation start date (%s) cannot be in the past.") % rec.start_date)

    @api.constrains('employee_id')
    def _check_employee_is_coach(self):
        for rec in self:
            if rec.employee_id and not rec.is_manager_coach and not rec.leave_request_id:
                raise ValidationError(_(
                    "Employee '%s' is not listed as a direct coach or manager of any staff members. "
                    "Only managerial employees with direct staff under them can create delegation requests."
                ) % rec.employee_id.name)

    @api.constrains('employee_id', 'delegate_id')
    def _check_self_delegation(self):
        for rec in self:
            if rec.employee_id and rec.delegate_id and rec.employee_id.id == rec.delegate_id.id:
                raise ValidationError(_("An employee cannot delegate their authority to themselves."))

    @api.constrains('employee_id', 'delegate_id', 'start_date', 'end_date', 'state', 'active')
    def _check_no_overlapping_delegation(self):
        """Validates:
        1. A delegating manager (employee_id) cannot have multiple active/overlapping delegations.
        2. A delegate (delegate_id) cannot have multiple delegations assigned to them in the same period (duplicate delegation).
        3. Chained/Sub-delegation prevention: An employee who is currently an active delegate cannot delegate someone else.
        4. Selected delegate cannot already be delegating their own authority during this period.
        """
        for rec in self:
            if not (rec.employee_id and rec.delegate_id and rec.start_date and rec.end_date):
                continue
            if rec.state == 'cancelled' or not rec.active:
                continue

            # 1. Prevent duplicate/overlapping delegation by the same manager
            overlapping_manager = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('state', '!=', 'cancelled'),
                ('start_date', '<=', rec.end_date),
                ('end_date', '>=', rec.start_date),
            ], limit=1)
            if overlapping_manager:
                raise ValidationError(_(
                    "Manager '%(manager)s' already has an active delegation (%(ref)s, %(start)s to %(end)s) "
                    "that overlaps this period. Duplicate active delegations are not allowed."
                ) % {
                    'manager': rec.employee_id.name,
                    'ref': overlapping_manager.name,
                    'start': overlapping_manager.start_date,
                    'end': overlapping_manager.end_date,
                })

            # 2. Prevent duplicate delegation where the delegate is already assigned in this period
            overlapping_delegate = self.search([
                ('id', '!=', rec.id),
                ('delegate_id', '=', rec.delegate_id.id),
                ('state', '!=', 'cancelled'),
                ('start_date', '<=', rec.end_date),
                ('end_date', '>=', rec.start_date),
            ], limit=1)
            if overlapping_delegate:
                raise ValidationError(_(
                    "Delegate '%(delegate)s' is already serving as a delegate in delegation (%(ref)s, %(start)s to %(end)s) "
                    "for '%(manager)s'. An employee cannot hold multiple overlapping active delegations."
                ) % {
                    'delegate': rec.delegate_id.name,
                    'ref': overlapping_delegate.name,
                    'start': overlapping_delegate.start_date,
                    'end': overlapping_delegate.end_date,
                    'manager': overlapping_delegate.employee_id.name,
                })

            # 3. Chained/Sub-delegation prevention: A delegated employee cannot delegate another person during their active delegation period
            serving_as_delegate = self.search([
                ('id', '!=', rec.id),
                ('delegate_id', '=', rec.employee_id.id),
                ('state', '!=', 'cancelled'),
                ('start_date', '<=', rec.end_date),
                ('end_date', '>=', rec.start_date),
            ], limit=1)
            if serving_as_delegate:
                raise ValidationError(_(
                    "Employee '%(employee)s' cannot delegate authority because they are currently serving as a delegate "
                    "in delegation (%(ref)s, %(start)s to %(end)s) delegated by '%(manager)s'. "
                    "Delegated employees cannot sub-delegate authority during an active delegation period."
                ) % {
                    'employee': rec.employee_id.name,
                    'ref': serving_as_delegate.name,
                    'start': serving_as_delegate.start_date,
                    'end': serving_as_delegate.end_date,
                    'manager': serving_as_delegate.employee_id.name,
                })

            # 4. A chosen delegate cannot have already delegated their own authority during this period
            delegate_is_delegator = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.delegate_id.id),
                ('state', '!=', 'cancelled'),
                ('start_date', '<=', rec.end_date),
                ('end_date', '>=', rec.start_date),
            ], limit=1)
            if delegate_is_delegator:
                raise ValidationError(_(
                    "Selected delegate '%(delegate)s' has delegated their own authority in delegation (%(ref)s, %(start)s to %(end)s). "
                    "An employee who has delegated their authority cannot be selected as a delegate during that period."
                ) % {
                    'delegate': rec.delegate_id.name,
                    'ref': delegate_is_delegator.name,
                    'start': delegate_is_delegator.start_date,
                    'end': delegate_is_delegator.end_date,
                })



    # -------------------------------------------------------------------------
    # CRUD HOOKS & NOTIFICATIONS
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        is_hr = (
            self.env.user.has_group('hr.group_hr_manager')
            or self.env.user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        for vals in vals_list:
            if not vals.get('name') or vals.get('name') in (_('New'), 'New'):
                vals['name'] = _('Draft')
            if vals.get('state') == 'submitted' and vals.get('name') in (_('Draft'), 'Draft', _('New'), 'New', '/', False):
                seq = self.env['ir.sequence'].sudo().next_by_code('hr.employee.delegation')
                if seq:
                    vals['name'] = seq

            # Prevent non-coaches from creating delegation requests manually
            emp_id = vals.get('employee_id') or (self.env.user.employee_id.id if self.env.user.employee_id else False)
            if emp_id and not vals.get('leave_request_id') and not is_hr:
                count = self.env['hr.employee'].sudo().search_count([
                    '|',
                    ('coach_id', '=', emp_id),
                    ('parent_id', '=', emp_id)
                ])
                if count == 0:
                    emp = self.env['hr.employee'].sudo().browse(emp_id)
                    raise ValidationError(_(
                        "Employee '%s' is not listed as a direct coach or manager of any staff members. "
                        "Only managerial employees with direct staff under them can create delegation requests."
                    ) % (emp.name or _('User')))

        records = super().create(vals_list)
        for rec in records:
            valid_stakeholders = rec.stakeholder_ids.filtered(
                lambda s: s.work_email or s.department_name or s.job_name or (s.name and s.name != _('Employee') and s.name != 'Employee')
            )
            if not valid_stakeholders and rec.employee_id:
                rec._set_default_notification_recipients()
        return records


    def write(self, vals):
        if vals.get('state') == 'submitted':
            for rec in self:
                if not vals.get('name') and (not rec.name or rec.name in (_('Draft'), 'Draft', _('New'), 'New', '/', False)):
                    seq = self.env['ir.sequence'].sudo().next_by_code('hr.employee.delegation')
                    if seq:
                        vals['name'] = seq
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state == 'submitted':
                raise UserError(_("You cannot delete a submitted active delegation. Please cancel it first."))
        return super().unlink()




    def _send_delegation_notifications(self):
        for rec in self:
            if rec.state != 'submitted':
                continue

            recip_tuples = []  # list of (emp_record_or_False, partner_record, display_name)
            seen_partner_ids = set()

            # Always notify delegate
            if rec.delegate_id:
                d_emp = rec.delegate_id.sudo()
                if d_emp.user_id and d_emp.user_id.partner_id:
                    p = d_emp.user_id.partner_id
                    seen_partner_ids.add(p.id)
                    recip_tuples.append((d_emp, p, d_emp.name))

            # Process stakeholder lines
            for st in rec.stakeholder_ids:
                emp = False
                partner = False
                display_name = st.name or _('Employee')
                if st.employee_id:
                    emp = st.employee_id.sudo()
                    display_name = emp.name
                    if emp.user_id and emp.user_id.partner_id:
                        partner = emp.user_id.partner_id
                elif st.work_email:
                    email_str = st.work_email.strip()
                    emp = self.env['hr.employee'].sudo().search([('work_email', '=ilike', email_str)], limit=1)
                    if emp:
                        display_name = emp.name
                        if emp.user_id and emp.user_id.partner_id:
                            partner = emp.user_id.partner_id
                    if not partner:
                        partner = self.env['res.partner'].sudo().search([('email', '=ilike', email_str)], limit=1)

                if partner and partner.id not in seen_partner_ids:
                    seen_partner_ids.add(partner.id)
                    recip_tuples.append((emp, partner, display_name))

            if not recip_tuples:
                continue

            all_partners = self.env['res.partner'].sudo().browse(list(seen_partner_ids))

            # Subscribe recipient partners as followers
            if all_partners:
                rec.sudo().message_subscribe(partner_ids=all_partners.ids)

            body = _(
                "<strong>Managerial Delegation Notice</strong><br/>"
                "<strong>Manager:</strong> %(manager)s<br/>"
                "<strong>Delegated Staff:</strong> %(delegate)s<br/>"
                "<strong>Period:</strong> %(start)s to %(end)s<br/>"
                "<strong>Reason:</strong> %(reason)s"
            ) % {
                'manager': rec.employee_id.name,
                'delegate': rec.delegate_id.name,
                'start': rec.start_date,
                'end': rec.end_date,
                'reason': rec.absence_reason or _('N/A'),
            }

            rec.sudo().message_post(
                body=Markup(body),
                partner_ids=all_partners.ids,
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )

            # Send Direct 1-on-1 Discuss Channel message per recipient
            for emp, partner, display_name in recip_tuples:
                channel = rec._get_or_create_delegation_dm_channel(partner)
                if not channel:
                    _logger.error(
                        "Delegation %s: could not open/create a Discuss direct-message "
                        "channel with partner %s (id=%s); notification NOT delivered via Discuss.",
                        rec.name, partner.name, partner.id
                    )
                    continue

                if rec.delegate_id and emp and emp.id == rec.delegate_id.id:
                    # Specific Template for Delegated Employee
                    msg_body = f"""
                        <p>Dear {display_name},</p>
                        <p><b>{rec.employee_id.name}</b> has officially delegated you from <b>{rec.start_date}</b> to <b>{rec.end_date}</b>.</p>
                        <p><b>Delegation Details:</b></p>
                        <ul>
                            <li><b>Delegator:</b> {rec.employee_id.name}</li>
                            <li><b>Delegation Period:</b> {rec.start_date} to {rec.end_date}</li>
                            <li><b>Reason for Absence:</b> {rec.absence_reason or 'Official Mission / Managerial Operations'}</li>
                            <li><b>Status:</b> Active / Submitted</li>
                        </ul>
                        <p>During this period, you are authorized to act on behalf of {rec.employee_id.name} for approvals and managerial operations under their jurisdiction.</p>
                        <p>Kindly review the delegation request in Bunna Bank ERP and process pending tasks accordingly.</p>
                        <p>Best regards,<br/>Bunna Bank</p>
                    """
                else:
                    # Specific Template for Notified Persons (Coaches, Directorate, Staff)
                    msg_body = f"""
                        <p>Dear {display_name},</p>
                        <p>Please be informed that <b>{rec.employee_id.name}</b> has officially delegated <b>{rec.delegate_id.name if rec.delegate_id else 'N/A'}</b> from <b>{rec.start_date}</b> to <b>{rec.end_date}</b>.</p>
                        <p><b>Delegation Details:</b></p>
                        <ul>
                            <li><b>Delegator:</b> {rec.employee_id.name}</li>
                            <li><b>Delegated Staff:</b> {rec.delegate_id.name if rec.delegate_id else 'N/A'}</li>
                            <li><b>Delegation Period:</b> {rec.start_date} to {rec.end_date}</li>
                            <li><b>Reason for Absence:</b> {rec.absence_reason or 'Official Mission / Managerial Operations'}</li>
                            <li><b>Status:</b> Submitted</li>
                        </ul>
                        <p>This is an automated notification for your records and operational awareness.</p>
                        <p>Best regards,<br/>Bunna Bank</p>
                    """

                try:
                    channel.message_post(
                        body=Markup(msg_body),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                except Exception as e:
                    _logger.error(
                        "Delegation %s: failed to post Discuss direct message to partner %s: %s",
                        rec.name, partner.id, e
                    )



    def _get_or_create_delegation_dm_channel(self, partner):
        """Return a discuss.channel recordset for a 1-on-1 conversation with
        `partner`, compatible across Odoo discuss.channel API versions
        (Odoo 17+ uses `_get_or_create_chat`, older versions used
        `channel_get`). Always executed with sudo so it works regardless of
        the acting user's own Discuss/channel access rights.
        """
        self.ensure_one()
        Channel = self.env['discuss.channel'].sudo()
        channel = self.env['discuss.channel']
        try:
            if hasattr(Channel, '_get_or_create_chat'):
                channel = Channel._get_or_create_chat(partner.ids)
            elif hasattr(Channel, 'channel_get'):
                channel_info = Channel.channel_get(partner.ids)
                if channel_info and channel_info.get('id'):
                    channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])
        except Exception as e:
            _logger.error(
                "Delegation %s: error opening Discuss DM channel with partner %s: %s",
                self.name, partner.id, e
            )
            return self.env['discuss.channel']
        return channel




    # -------------------------------------------------------------------------
    # TIME OFF / LEAVE HOOK
    # -------------------------------------------------------------------------
    @api.model
    def sync_delegation_from_leave(self, leave_record):
        """Creates or updates a delegation record automatically from a leave request."""
        if not leave_record or not leave_record.requester_name or not leave_record.delegated_name:
            return False

        start_dt = leave_record.start_date
        end_dt = leave_record.end_date
        if not start_dt or not end_dt:
            return False

        existing = self.search([
            ('leave_request_id', '=', leave_record.id)
        ], limit=1)

        vals = {
            'employee_id': leave_record.requester_name.id,
            'delegate_id': leave_record.delegated_name.id,
            'start_date': start_dt,
            'end_date': end_dt,
            'absence_reason': _("Leave (%s)") % (dict(leave_record._fields['leave_reason'].selection).get(leave_record.leave_reason, 'Leave') if hasattr(leave_record, 'leave_reason') and leave_record.leave_reason else 'Leave'),
            'leave_request_id': leave_record.id,
            'state': 'submitted',
        }


        # sudo(): this is a system-triggered sync (from a leave request that may be
        # created/approved by HR staff other than the delegating manager). The new
        # stricter create/write record rules on hr.employee.delegation only allow a
        # user to create/edit delegations where they are the delegator, so this
        # automated path must bypass those rules the same way it already bypasses
        # the "no past start date" check via context.
        if existing:
            existing.sudo().with_context(check_past_date=False).write(vals)
            return existing
        else:
            return self.sudo().with_context(check_past_date=False).create(vals)


class HrEmployeeDelegationStakeholder(models.Model):
    _name = "hr.employee.delegation.stakeholder"
    _description = "Delegation Notification Employee"
    _order = "id asc"

    delegation_id = fields.Many2one('hr.employee.delegation', string="Delegation", ondelete='cascade', required=True)
    employee_id = fields.Many2one('hr.employee', string="Employee Reference", ondelete='set null')
    name = fields.Char(string="Employee Name", required=True, default=lambda self: _('Employee'))
    work_email = fields.Char(string="Work Email")
    department_name = fields.Char(string="Department")
    job_name = fields.Char(string="Job Position")
    category = fields.Char(string="Role / Category", default="Direct Staff")

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            emp = self.employee_id.sudo()
            self.name = emp.name or _('Employee')
            self.work_email = emp.work_email or ''
            self.department_name = emp.department_id.name if emp.department_id else ''
            self.job_name = emp.job_position.name if (hasattr(emp, 'job_position') and emp.job_position) else (emp.job_name or '')
            self.category = "Selected Employee"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('employee_id'):
                emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
                if not vals.get('name'):
                    vals['name'] = emp.name or _('Employee')
                if not vals.get('work_email'):
                    vals['work_email'] = emp.work_email or ''
                if not vals.get('department_name') and emp.department_id:
                    vals['department_name'] = emp.department_id.name or ''
                if not vals.get('job_name'):
                    vals['job_name'] = emp.job_position.name if (hasattr(emp, 'job_position') and emp.job_position) else (emp.job_name or '')
            elif not vals.get('name'):
                vals['name'] = _('Employee')
        return super().create(vals_list)

    def write(self, vals):
        if 'employee_id' in vals and vals.get('employee_id'):
            emp = self.env['hr.employee'].sudo().browse(vals['employee_id'])
            if 'name' not in vals or not vals.get('name'):
                vals['name'] = emp.name or _('Employee')
            if 'work_email' not in vals:
                vals['work_email'] = emp.work_email or ''
            if 'department_name' not in vals and emp.department_id:
                vals['department_name'] = emp.department_id.name or ''
            if 'job_name' not in vals:
                vals['job_name'] = emp.job_position.name if (hasattr(emp, 'job_position') and emp.job_position) else (emp.job_name or '')
        elif 'name' in vals and not vals.get('name'):
            vals['name'] = _('Employee')
        return super().write(vals)

