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

    def _get_delegation_visible_employee_ids(self):
        emp = self.env.user.employee_id
        Delegation = self.env['hr.employee.delegation'].sudo()
        visible_ids = set()

        if emp:
            visible_ids.add(emp.id)

            # Direct and indirect subordinates of own employee
            subordinates = self.env['hr.employee'].sudo().search([
                '|',
                ('coach_id', '=', emp.id),
                ('parent_id', '=', emp.id)
            ])
            visible_ids.update(subordinates.ids)

            # Managers who delegated to me in submitted delegations
            my_delegations = Delegation.search([
                ('state', '=', 'submitted'),
                '|',
                ('delegate_id', '=', emp.id),
                ('notification_recipient_ids', 'in', [emp.id])
            ])
            visible_ids.update(my_delegations.mapped('employee_id.id'))

            # Subordinates of active delegating managers
            today = fields.Date.today()
            active_delegated_managers = my_delegations.filtered(
                lambda d: d.delegate_id.id == emp.id and d.start_date <= today and d.end_date >= today
            ).mapped('employee_id')
            if active_delegated_managers:
                delegated_subs = self.env['hr.employee'].sudo().search([
                    '|',
                    ('coach_id', 'in', active_delegated_managers.ids),
                    ('parent_id', 'in', active_delegated_managers.ids)
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
        default=lambda self: _('New'),
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
        related="employee_id.job_id",
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
    delegate_job_id = fields.Many2one(
        'hr.job',
        string="Delegate Job Position",
        related="delegate_id.job_id",
        compute_sudo=True,
        readonly=True
    )

    notification_recipient_ids = fields.Many2many(
        'hr.employee',
        'hr_delegation_notification_rel',
        'delegation_id',
        'employee_id',
        string="Notification Recipients",
        help="Adjustable list of employees to receive delegation notification"
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

    def _compute_is_requestor(self):
        current_uid = self.env.uid
        for rec in self:
            rec.is_requestor = bool(rec.employee_id and rec.employee_id.user_id.id == current_uid)

    def action_submit(self):
        for rec in self:
            if not rec.delegate_id:
                raise ValidationError(_("Please select a delegated staff member before submitting."))
            if not rec.is_manager_coach and not rec.leave_request_id:
                raise ValidationError(_("Only managerial employees with direct staff under them can submit delegation requests."))
            rec.write({'state': 'submitted'})
            rec._send_delegation_notifications()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Delegation Submitted"),
                'message': _("Delegation request submitted and notifications sent to selected recipients."),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_cancel_delegation(self):
        for rec in self:
            rec.write({'state': 'cancelled', 'active': False})
            model = self.env.ref('hr_employee_custom.model_hr_employee_delegation', raise_if_not_found=False)
            if model:
                activities = self.env['mail.activity'].sudo().search([
                    ('res_model_id', '=', model.id),
                    ('res_id', '=', rec.id)
                ])
                activities.unlink()
            rec.message_post(body=_("Delegation request has been cancelled and archived by manager. Delegation permissions are revoked."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Delegation Cancelled"),
                'message': _("Delegation request has been cancelled and archived."),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }



    # -------------------------------------------------------------------------
    # DEFAULTS & COMPUTES
    # -------------------------------------------------------------------------


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
            rec.manager_job_name = emp.job_id.name if (emp and emp.job_id) else ''
            rec.manager_department_name = emp.department_id.name if (emp and emp.department_id) else ''
            rec.delegate_job_name = delegate.job_id.name if (delegate and delegate.job_id) else ''

    @api.depends('notification_recipient_ids')
    def _compute_notification_recipients_display(self):
        for rec in self:
            recips = rec.notification_recipient_ids.sudo()
            if recips:
                rows = "".join([
                    f"<tr><td><b>{r.name}</b></td><td>{r.work_email or '-'}</td><td>{r.department_id.name or '-'}</td><td>{r.job_id.name or '-'}</td></tr>"
                    for r in recips
                ])
                rec.notification_recipients_display = Markup(f"""
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Employee Name</th>
                                <th>Work Email</th>
                                <th>Department</th>
                                <th>Job Position</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                """)
            else:
                rec.notification_recipients_display = Markup("<p class='text-muted'>No notification recipients assigned.</p>")



    @api.depends('employee_id', 'include_sub_level_staff', 'start_date', 'end_date')
    def _compute_allowed_delegate_ids(self):

        for rec in self:
            if not rec.employee_id:
                rec.allowed_delegate_ids = False
                continue


            # Fetch direct coachees/subordinates (sudo to avoid read access errors)
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

            # If dates are specified, exclude employees who are already serving as delegates or have delegated authority
            if rec.start_date and rec.end_date:
                rec_id = rec.id if isinstance(rec.id, int) else False
                busy_delegates = self.env['hr.employee.delegation'].sudo().search([
                    ('id', '!=', rec_id),
                    ('state', '!=', 'cancelled'),
                    ('start_date', '<=', rec.end_date),
                    ('end_date', '>=', rec.start_date),
                ])
                # Exclude employees currently acting as delegates
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
            self._set_default_notification_recipients()

    @api.onchange('include_sub_level_staff', 'employee_id', 'start_date', 'end_date')
    def _onchange_delegate_options(self):
        self._compute_allowed_delegate_ids()
        if self.delegate_id and self.delegate_id not in self.allowed_delegate_ids:
            self.delegate_id = False
        return {
            'domain': {
                'delegate_id': [('id', 'in', self.allowed_delegate_ids.ids)]
            }
        }



    def _get_default_notification_recipients(self):
        self.ensure_one()
        recipients = set()
        manager = self.employee_id.sudo()

        if not manager:
            return []

        # 1. Immediate Coach / Manager
        imm_coach = manager.coach_id or manager.parent_id
        if imm_coach:
            recipients.add(imm_coach.id)

            # 2. Coach of the immediate coach
            coach_of_coach = imm_coach.coach_id or imm_coach.parent_id
            if coach_of_coach:
                recipients.add(coach_of_coach.id)

        # 3. Direct employees under the requestor
        direct_staff = self.env['hr.employee'].sudo().search([
            '|',
            ('coach_id', '=', manager.id),
            ('parent_id', '=', manager.id)
        ])
        recipients.update(direct_staff.ids)

        # 4. People Operations Management Directorate
        people_ops_emp = self.env['hr.employee'].sudo().search([
            '|',
            ('job_id.name', 'ilike', 'People Operation'),
            ('department_id.name', 'ilike', 'People Operation')
        ])
        recipients.update(people_ops_emp.ids)

        # 5. Chief People and Culture Office
        cpc_emp = self.env['hr.employee'].sudo().search([
            ('job_id.name', 'ilike', 'Chief People and Culture')
        ])
        recipients.update(cpc_emp.ids)

        # Exclude delegating manager from notification list if present
        recipients.discard(manager.id)

        # Filter out system administrator user
        valid_recipients = self.env['hr.employee'].sudo().browse(list(recipients)).filtered(
            lambda e: e.user_id and e.user_id.login != 'admin' and e.active
        )
        return valid_recipients.ids

    def _set_default_notification_recipients(self):
        for rec in self:
            recipients = rec._get_default_notification_recipients()
            rec.sudo().write({'notification_recipient_ids': [(6, 0, recipients)]})

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
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.employee.delegation') or _('New')

        records = super().create(vals_list)
        for rec in records:
            if not rec.notification_recipient_ids:
                rec._set_default_notification_recipients()
        return records

    def write(self, vals):
        return super().write(vals)

    def _send_delegation_notifications(self):
        for rec in self:
            if rec.state != 'submitted':
                continue

            recip_employees = rec.notification_recipient_ids
            if rec.delegate_id and rec.delegate_id not in recip_employees:
                recip_employees |= rec.delegate_id

            if not recip_employees:
                continue


            partners = recip_employees.sudo().mapped('user_id.partner_id').filtered(lambda p: p)

            # Subscribe recipient partners as followers
            if partners:
                rec.sudo().message_subscribe(partner_ids=partners.ids)

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

            if partners:
                rec.sudo().message_post(
                    body=body,
                    partner_ids=partners.ids,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )

            # Create Odoo activity for each recipient user so they receive top navbar clock/activity alert
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            model = self.env.ref('hr_employee_custom.model_hr_employee_delegation', raise_if_not_found=False)
            if activity_type and model:
                for emp in recip_employees:
                    if emp.user_id:
                        existing_act = self.env['mail.activity'].sudo().search([
                            ('res_model_id', '=', model.id),
                            ('res_id', '=', rec.id),
                            ('user_id', '=', emp.user_id.id),
                        ], limit=1)
                        if not existing_act:
                            self.env['mail.activity'].sudo().create({
                                'activity_type_id': activity_type.id,
                                'summary': _("Manager Delegation Notice: %s") % rec.name,
                                'note': body,
                                'res_id': rec.id,
                                'res_model_id': model.id,
                                'user_id': emp.user_id.id,
                                'date_deadline': rec.start_date or fields.Date.today(),
                            })

            # Send Direct 1-on-1 Discuss Channel message per recipient
            for emp in recip_employees:
                partner = emp.user_id.partner_id if emp.user_id else False
                if not partner:
                    continue

                channel = rec._get_or_create_delegation_dm_channel(partner)
                if not channel:
                    _logger.error(
                        "Delegation %s: could not open/create a Discuss direct-message "
                        "channel with partner %s (id=%s); notification NOT delivered via Discuss.",
                        rec.name, partner.name, partner.id
                    )
                    continue

                if rec.delegate_id and emp.id == rec.delegate_id.id:
                    # Specific Template for Delegated Employee
                    msg_body = f"""
                        <p>Dear {emp.name},</p>
                        <p><b>{rec.employee_id.name}</b> has officially delegated you from <b>{rec.start_date}</b> to <b>{rec.end_date}</b>.</p>
                        <p><b>Delegation Details:</b></p>
                        <ul>
                            <li><b>Delegator:</b> {rec.employee_id.name}</li>
                            <li><b>Delegation Period:</b> {rec.start_date} to {rec.end_date}</li>
                            <li><b>Reason for Absence:</b> {rec.absence_reason or 'Official Mission / Managerial Operations'}</li>
                            <li><b>Status:</b> Active / Submitted</li>
                        </ul>
                        <p>During this period, you are authorized to act on behalf of {rec.employee_id.name} for approvals and managerial operations under their jurisdiction.</p>
                        <p>Kindly review the delegation request in Omni Bank ERP and process pending tasks accordingly.</p>
                        <p>Best regards,<br/>Omni Bank ERP</p>
                    """
                else:
                    # Specific Template for Notified Persons (Coaches, Directorate, Staff)
                    msg_body = f"""
                        <p>Dear {emp.name},</p>
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
                        <p>Best regards,<br/>Omni Bank ERP</p>
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
