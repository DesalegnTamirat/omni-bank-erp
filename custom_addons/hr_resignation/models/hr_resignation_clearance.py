from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
from datetime import timedelta
import logging
import time

_logger = logging.getLogger(__name__)

class HrResignationClearanceLineItem(models.Model):
    _name = 'hr.resignation.clearance.line.item'
    _description = 'Clearance Line Checklist Item'
    _order = 'sequence asc'

    clearance_line_id = fields.Many2one(
        'hr.resignation.clearance',
        required=True, ondelete='cascade', index=True)
    sequence     = fields.Integer(default=10)
    name         = fields.Char(required=True, string='Task')
    is_mandatory = fields.Boolean(default=True)
    is_done      = fields.Boolean(default=False, string='completed')
    can_clear    = fields.Boolean(compute='_compute_can_clear', string='Can Clear')

    @api.depends_context('uid')
    def _compute_can_clear(self):
        is_officer = self.env.user.has_group('hr_resignation.group_clearance_officer')
        is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
        for rec in self:
            resp_user = rec.clearance_line_id.responsible_user
            is_responsible = (resp_user == self.env.user)
            is_delegate = False
            if not is_responsible and resp_user and resp_user.employee_id:
                is_delegate = rec.clearance_line_id.resignation_id._is_user_acting_delegate(self.env.user, resp_user.employee_id)
                if is_delegate:
                    is_responsible = True
            # Responsible user or their acting delegate (inheriting officer role) can clear
            rec.can_clear = is_admin or (is_responsible and (is_officer or is_delegate))

    done_by      = fields.Many2one('res.users', readonly=True)
    done_date    = fields.Datetime(readonly=True)
    note         = fields.Text(string='Guidance Note')

    @api.model
    def _get_delegation_visible_item_ids(self):
        emp = self.env.user.employee_id
        if not emp:
            return []
        today = fields.Date.today()
        active_delegations = self.env['hr.employee.delegation'].sudo().search([
            ('delegate_id', '=', emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        if not active_delegations:
            return []
        delegator_emps = active_delegations.mapped('employee_id')
        delegator_users = delegator_emps.mapped('user_id').filtered(lambda u: u)

        hr_manager_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        if hr_manager_group and any(u in hr_manager_group.sudo().user_ids for u in delegator_users):
            return self.sudo().search([]).ids

        domain = ['|', ('clearance_line_id.responsible_user', 'in', delegator_users.ids), ('clearance_line_id.resignation_id.coach_id', 'in', delegator_emps.ids)]
        return self.sudo().search(domain).ids

    def action_dummy_cleared(self):
        from odoo.exceptions import UserError
        raise UserError("This task is already cleared and cannot be undone.")

    def action_toggle_cleared(self):
        from odoo.exceptions import UserError
        for rec in self:
            if not rec.can_clear:
                raise UserError("You are not authorized to clear this task. Only the assigned responsible user or system administrator can clear this task.")
            rec.is_done = not rec.is_done

    def write(self, vals):
        if 'is_done' in vals:
            for rec in self:
                is_officer = self.env.user.has_group('hr_resignation.group_clearance_officer')
                is_admin = self.env.user.has_group('base.group_system') or self.env.user.has_group('hr_resignation.group_resignation_admin')
                resp_user = rec.clearance_line_id.responsible_user
                is_responsible = (resp_user == self.env.user)
                if not is_responsible and resp_user and resp_user.employee_id:
                    if rec.clearance_line_id.resignation_id._is_user_acting_delegate(self.env.user, resp_user.employee_id):
                        is_responsible = True
                if not (is_officer or is_admin or is_responsible):
                    raise AccessError(_("You are not authorized to check or uncheck clearance items."))

                if vals.get('is_done'):
                    vals['done_by'] = self.env.user.id
                    vals['done_date'] = fields.Datetime.now()
                else:
                    vals['done_by'] = False
                    vals['done_date'] = False
        return super().write(vals)

    def action_toggle_done(self):
        for rec in self:
            if rec.clearance_line_id.resignation_id.state not in ('clearance_in_progress', 'cleared', 'settled', 'completed'):
                raise UserError(_('You cannot mark tasks as cleared until the Release Date is set and Handover is completed.'))
            if rec.is_done:
                rec.write({'is_done': False})
            else:
                rec.write({'is_done': True})

    def action_mark_done(self):
        for rec in self:
            if rec.clearance_line_id.resignation_id.state not in ('clearance_in_progress', 'cleared', 'settled', 'completed'):
                raise UserError(_('You cannot mark tasks as cleared until the Release Date is set and Handover is completed.'))
            if not rec.can_clear:
                raise UserError(_('You are not authorized to clear this task. Only the assigned responsible user (with Clearance Officer role), the work unit manager, or Admin can clear tasks.'))
            rec.write({'is_done': True})

    def action_unmark_done(self):
        for rec in self:
            if rec.clearance_line_id.resignation_id.state not in ('clearance_in_progress', 'cleared', 'settled', 'completed'):
                raise UserError(_('You cannot unmark tasks until the Release Date is set and Handover is completed.'))
            if not rec.can_clear:
                raise UserError(_('You are not authorized to unmark this task. Only the assigned responsible user, work unit manager, or Admin can unmark tasks.'))
            rec.write({'is_done': False})


# ─────────────────────────────────────────────────────────────────────────────
#  RUNTIME — Clearance Line (one row per work unit per resignation)
# ─────────────────────────────────────────────────────────────────────────────

class HrResignationClearance(models.Model):

    _name        = 'hr.resignation.clearance'
    _description = 'Resignation Clearance Line'
    _inherit     = ['mail.thread', 'mail.activity.mixin']
    _rec_name    = 'display_name'
    _order       = 'state_sort asc, id desc'   # <-- CHANGED: pending first, then newest

    # ── Parent ────────────────────────────────────────────────────────────────
    resignation_id = fields.Many2one(
        'hr.resignation', required=True, ondelete='cascade', index=True)
    release_date = fields.Date(
        related='resignation_id.release_date', store=True, string='Release Date', readonly=True)
    sla_deadline = fields.Date(
        string='SLA Deadline',
        compute='_compute_sla_deadline',
        store=True,
        help='Deadline for work unit to clear this task')

    @api.depends('release_date', 'sdt_days')
    def _compute_sla_deadline(self):
        from dateutil.relativedelta import relativedelta
        for rec in self:
            if rec.release_date and rec.sdt_days:
                rec.sla_deadline = rec.release_date + relativedelta(days=rec.sdt_days)
            else:
                rec.sla_deadline = False

    # ── Display Name ──────────────────────────────────────────────────────────
    display_name = fields.Char(
        compute='_compute_display_name', store=True, string='Title')

    @api.depends('work_unit_id', 'employee_id', 'resignation_id')
    def _compute_display_name(self):
        for rec in self:
            work_unit = rec.work_unit_id.name or _('Clearance Task')
            emp       = rec.employee_id.sudo().name or ''
            res_ref   = rec.resignation_id.name or ''
            if emp and res_ref:
                rec.display_name = f"{work_unit} - {emp} ({res_ref})"
            elif emp:
                rec.display_name = f"{work_unit} - {emp}"
            else:
                rec.display_name = work_unit

    # ── Template link (informational) ─────────────────────────────────────────
    template_id = fields.Many2one(
        'hr.resignation.clearance.template',
        string='Source Template', readonly=True, ondelete='set null')

    # ── Work unit identity ────────────────────────────────────────────────────
    sequence         = fields.Integer(default=10)
    work_unit_id     = fields.Many2one(
        'operating.unit', required=True, string='Operating Unit')
    responsible_user = fields.Many2one(
        'res.users', required=True, string='Responsible User')

    is_mandatory     = fields.Boolean(default=True)

    # ── State ─────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('waiting',  'Waiting'),
        ('pending',  'Pending'),
        ('cleared',  'Cleared'),
    ], default='pending', required=True)
    state_sort = fields.Integer(
        compute='_compute_state_sort', store=True, index=True)

    @api.depends('state')
    def _compute_state_sort(self):
        order = {'pending': 0, 'waiting': 1, 'cleared': 2}
        for rec in self:
            rec.state_sort = order.get(rec.state, 9)

    notification_sent = fields.Boolean(
        default=False, readonly=True,
        string='Notified',
        help='True once the responsible user has been sent their task notification.')

    sdt_days = fields.Integer(string='SDT (Days)')
    pending_since = fields.Datetime(string='Pending Since', readonly=True)
    is_overdue = fields.Boolean(compute='_compute_is_overdue', store=True)

    @api.depends('state', 'pending_since', 'sdt_days', 'sla_deadline', 'resignation_id.release_date')
    def _compute_is_overdue(self):
        for rec in self:
            if rec.state == 'pending':
                if rec.sla_deadline:
                    rec.is_overdue = fields.Date.today() > rec.sla_deadline
                elif rec.resignation_id.release_date and rec.sdt_days:
                    deadline = rec.resignation_id.release_date + timedelta(days=rec.sdt_days)
                    rec.is_overdue = fields.Date.today() > deadline
                elif rec.pending_since and rec.sdt_days:
                    deadline = rec.pending_since + timedelta(days=rec.sdt_days)
                    rec.is_overdue = fields.Datetime.now() > deadline
                else:
                    rec.is_overdue = False
            else:
                rec.is_overdue = False

    can_approve = fields.Boolean(compute='_compute_can_approve', string='Can Approve')

    is_my_clearance_task = fields.Boolean(
        string='Is My Clearance Task',
        compute='_compute_is_my_clearance_task',
        search='_search_is_my_clearance_task'
    )

    def _compute_is_my_clearance_task(self):
        current_user = self.env.user
        current_emp = current_user.employee_id
        today = fields.Date.today()
        delegator_user_ids = set()
        if current_emp:
            delegations = self.env['hr.employee.delegation'].sudo().search([
                ('delegate_id', '=', current_emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            delegator_user_ids = set(delegations.mapped('employee_id.user_id.id'))
        for rec in self:
            rec.is_my_clearance_task = (
                rec.responsible_user.id == current_user.id or
                rec.responsible_user.id in delegator_user_ids
            )

    def _search_is_my_clearance_task(self, operator, value):
        current_user = self.env.user
        current_emp = current_user.employee_id
        today = fields.Date.today()
        delegator_user_ids = []
        if current_emp:
            delegations = self.env['hr.employee.delegation'].sudo().search([
                ('delegate_id', '=', current_emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            delegator_user_ids = delegations.mapped('employee_id.user_id.id')

        is_positive = False
        if operator in ('=', '=='):
            is_positive = bool(value)
        elif operator in ('!=', '<>'):
            is_positive = not bool(value)
        elif operator == 'in':
            is_positive = any(value) if hasattr(value, '__iter__') else bool(value)
        elif operator == 'not in':
            is_positive = not any(value) if hasattr(value, '__iter__') else not bool(value)

        if is_positive:
            if delegator_user_ids:
                return ['|', ('responsible_user', '=', current_user.id), ('responsible_user', 'in', delegator_user_ids)]
            return [('responsible_user', '=', current_user.id)]
        else:
            if delegator_user_ids:
                return ['&', ('responsible_user', '!=', current_user.id), ('responsible_user', 'not in', delegator_user_ids)]
            return [('responsible_user', '!=', current_user.id)]

    @api.model
    def _get_delegation_visible_clearance_ids(self):
        emp = self.env.user.employee_id
        if not emp:
            return []
        today = fields.Date.today()
        active_delegations = self.env['hr.employee.delegation'].sudo().search([
            ('delegate_id', '=', emp.id),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        if not active_delegations:
            return []
        delegator_emps = active_delegations.mapped('employee_id')
        delegator_users = delegator_emps.mapped('user_id').filtered(lambda u: u)

        hr_manager_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        if hr_manager_group and any(u in hr_manager_group.sudo().user_ids for u in delegator_users):
            return self.sudo().search([]).ids

        domain = ['|', ('responsible_user', 'in', delegator_users.ids), ('resignation_id.coach_id', 'in', delegator_emps.ids)]
        return self.sudo().search(domain).ids

    @api.depends_context('uid')
    def _compute_can_approve(self):
        user = self.env.user
        for rec in self:
            is_hr = rec.resignation_id._is_user_acting_hr_manager(user) or user.has_group('hr.group_hr_user')
            resp_user = rec.responsible_user
            is_officer = (resp_user and resp_user.id == user.id)
            if not is_officer and resp_user and resp_user.employee_id:
                is_officer = rec.resignation_id._is_user_acting_delegate(user, resp_user.employee_id)
            rec.can_approve = is_hr or is_officer

    # ── Approval metadata ─────────────────────────────────────────────────────
    cleared_by   = fields.Many2one('res.users', readonly=True, string='Cleared By')
    cleared_date = fields.Datetime(readonly=True, string='Cleared On')
    notes        = fields.Text(string='Clearance Notes / Remarks')

    # ── Checklist sub-items ───────────────────────────────────────────────────
    item_ids           = fields.One2many(
        'hr.resignation.clearance.line.item', 'clearance_line_id',
        string='Checklist Items')
    items_total        = fields.Integer(compute='_compute_item_counts', string='Items')
    items_done         = fields.Integer(compute='_compute_item_counts', string='completed')
    items_progress     = fields.Char(compute='_compute_item_counts', string='Item Progress')
    mandatory_items_ok = fields.Boolean(
        compute='_compute_mandatory_items_ok', store=True,
        help='True when all mandatory checklist items are ticked.')

    # ── Related fields for display ────────────────────────────────────────────
    employee_id = fields.Many2one(
        related='resignation_id.employee_id', store=True, string='Employee')

    employee_sudo_name = fields.Char(
        string='Employee',
        compute='_compute_employee_sudo_name',
        search='_search_employee_sudo_name',
        help='Bypasses strict hierarchy rules to display employee name.'
    )

    def _search_employee_sudo_name(self, operator, value):
        employees = self.env['hr.employee'].sudo().search([('name', operator, value)])
        return [('employee_id', 'in', employees.ids)]

    @api.depends('employee_id')
    def _compute_employee_sudo_name(self):
        for rec in self:
            rec.employee_sudo_name = rec.employee_id.sudo().name if rec.employee_id else ''


    # Separation type as a Many2one relation (via the parent resignation)
    resignation_type_id = fields.Many2one(
        related='resignation_id.resignation_type_id',
        store=True,
        string='Separation Type')

    release_date = fields.Date(
        related='resignation_id.release_date', store=True)

    # ═══════════════════════════════════════════════════════════════════════════
    #  COMPUTES
    # ═══════════════════════════════════════════════════════════════════════════

    @api.depends('item_ids.is_done', 'item_ids.is_mandatory')
    def _compute_item_counts(self):
        for rec in self:
            items    = rec.item_ids
            done_all = items.filtered('is_done')
            rec.items_total    = len(items)
            rec.items_done     = len(done_all)
            rec.items_progress = f'{len(done_all)} / {len(items)}' if items else '—'

    @api.depends('item_ids.is_done', 'item_ids.is_mandatory')
    def _compute_mandatory_items_ok(self):
        for rec in self:
            mandatory = rec.item_ids.filtered('is_mandatory')
            done_mand = mandatory.filtered('is_done')
            rec.mandatory_items_ok = (not mandatory) or (len(done_mand) == len(mandatory))

    # ═══════════════════════════════════════════════════════════════════════════
    #  WORKFLOW ACTIONS
    # ═══════════════════════════════════════════════════════════════════════════

    def action_clear(self):
        """Mark clearance as cleared. Lean approach: Executed directly by the Clearance Officer."""
        for rec in self:
            rec = rec.with_context(mail_notify_force_send=False)
            _t0 = _t = time.time()
            rec._check_clearance_permission()
            _logger.warning("CLEAR TIMING permission: %.2fs", time.time() - _t); _t = time.time()
            if not rec.release_date:
                raise UserError(_('Cannot complete clearance: Release Date has not been set by the Manager.'))
            if rec.state != 'pending':
                raise UserError(_("Only pending tasks can be cleared. Current state: %s") % rec._get_state_label())
            if not rec.mandatory_items_ok:
                pending_items = rec.item_ids.filtered(
                    lambda i: i.is_mandatory and not i.is_done).mapped('name')
                raise UserError(_(
                    'The following mandatory checklist items must be '
                    'completed first:\n• %s') % '\n• '.join(pending_items))

            acting_delegation = False
            if rec.responsible_user != self.env.user and rec.responsible_user and rec.responsible_user.employee_id:
                acting_delegation = rec.resignation_id._get_acting_delegation(self.env.user, rec.responsible_user.employee_id)

            now  = fields.Datetime.now()
            vals = {
                'state':        'cleared',
                'cleared_by':   self.env.user.id,
                'cleared_date': now,
            }
            rec.write(vals)
            _logger.warning("CLEAR TIMING write: %.2fs", time.time() - _t); _t = time.time()

            # Post a professional log to the chatter
            if acting_delegation:
                audit_msg = _(
                    'Clearance completed by delegate <strong>%s</strong> on behalf of <strong>%s</strong> (Delegation Ref: %s).'
                ) % (
                    self.env.user.name,
                    rec.responsible_user.name,
                    acting_delegation.name or str(acting_delegation.id)
                )
            else:
                audit_msg = _('Clearance completed successfully by %s.') % self.env.user.name

            rec.message_post(
                body=audit_msg,
                message_type='notification'
            )
            # Log an internal audit note to the resignation chatter without slow broadcast notifies
            if rec.resignation_id:
                try:
                    rec.resignation_id.message_post(
                        body=_('Clearance task <strong>%s</strong> marked Cleared by %s.') % (
                            rec.work_unit_id.name or _('Clearance Item'),
                            self.env.user.name,
                        ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                    )
                except Exception:
                    pass

            try:
                rec._close_clearance_activities(
                    feedback=_('Cleared by %s.') % self.env.user.name)
            except Exception:
                pass

            rec.resignation_id._check_and_advance_cleared()

    def action_approve(self):
        """Standard approval entry point used by Delegated Approvals hub."""
        return self.action_clear()

    # ═══════════════════════════════════════════════════════════════════════════
    #  PERMISSION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _check_clearance_permission(self):
        self.ensure_one()
        user           = self.env.user
        is_hr          = user.has_group('hr.group_hr_user') or self.resignation_id._is_user_acting_hr_manager(user)
        is_admin       = user.has_group('base.group_system')
        is_responsible = (self.responsible_user == user)
        if not is_responsible and self.responsible_user and self.responsible_user.employee_id:
            is_responsible = self.resignation_id._is_user_acting_delegate(user, self.responsible_user.employee_id)
        if not (is_hr or is_responsible or is_admin):
            raise AccessError(_(
                'Only the responsible officer (%s) or their authorized delegate, an HR user, or an administrator '
                'can update clearance line "%s".')
                % (self.responsible_user.name, self.work_unit_id.name))

    # ═══════════════════════════════════════════════════════════════════════════
    #  UTILITIES
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_state_label(self):
        self.ensure_one()
        labels = dict(self._fields['state'].selection)
        return labels.get(self.state, self.state)

    def _close_clearance_activities(self, feedback=None):
        for rec in self:
            try:
                if 'mail.activity' in self.env:
                    activities = self.env['mail.activity'].sudo().search([
                        ('res_model', '=', 'hr.resignation.clearance'),
                        ('res_id', '=', rec.id),
                    ])
                    if activities:
                        activities.action_feedback(feedback=feedback)
            except Exception:
                pass

    def action_open_form(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      _('Clearance — %s') % self.work_unit_id.name,
            'res_model': 'hr.resignation.clearance',
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
            'flags':     {'mode': 'readonly'},
        }

    # ═══════════════════════════════════════════════════════════════════════════
    #  NOTIFICATION HELPER
    # ═══════════════════════════════════════════════════════════════════════════

    def _notify_responsible_user(self):
        for rec in self:
            if rec.notification_sent:
                continue
            if rec.state == 'waiting':
                rec.state = 'pending'
                rec.pending_since = fields.Datetime.now()
            rec.notification_sent = True

            try:
                activity_type = self.env.ref(
                    'mail.mail_activity_data_todo', raise_if_not_found=False
                )
                if not activity_type:
                    activity_type = self.env['mail.activity.type'].sudo().search(
                        [], limit=1)

                if activity_type and rec.responsible_user:
                    emp_name  = rec.employee_id.sudo().name or _('an employee')
                    sep_type  = rec.resignation_type_id.name or ''
                    note_body = _(
                        'Clearance required for <strong>%s</strong> '
                        '(<em>%s</em>, Ref: %s).<br/>'
                        'Please review and submit '
                        'your clearance items.'
                    ) % (
                        emp_name,
                        sep_type,
                        rec.resignation_id.name or '',
                    )
                    users_to_notify = [rec.responsible_user]
                    if rec.responsible_user.employee_id:
                        delegates = rec.resignation_id._get_active_delegates_for_employee(rec.responsible_user.employee_id)
                        for d in delegates:
                            if d.user_id and d.user_id not in users_to_notify:
                                users_to_notify.append(d.user_id)

                    for u in users_to_notify:
                        self.env['mail.activity'].sudo().create({
                            'res_model_id': self.env['ir.model'].sudo()._get_id(
                                'hr.resignation.clearance'),
                            'res_id':           rec.id,
                            'activity_type_id': activity_type.id,
                            'summary':          _('Clearance task: %s') % (
                                rec.work_unit_id.name or ''),
                            'note':             note_body,
                            'user_id':          u.id,
                            'date_deadline':    rec.release_date or fields.Date.today(),
                        })

            except Exception:
                # Never crash the clearance workflow due to notification failure.
                pass

    @api.model
    def _cron_check_overdue_clearances(self):
        # Force a dynamic check for all pending items so we don't rely on cached boolean states
        pending_lines = self.search([('state', '=', 'pending')])
        if not pending_lines:
            return
        pending_lines._compute_is_overdue()

        overdue_lines = pending_lines.filtered(lambda r: r.is_overdue)
        if not overdue_lines:
            return

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].sudo().search([], limit=1)

        # Get all HR and POMD users to notify
        hr_users = []
        for group_ref in ['hr_resignation.group_resignation_hr_manager', 'hr_resignation.group_hr_officer', 'hr_resignation.group_pomd_officer']:
            group = self.env.ref(group_ref, raise_if_not_found=False)
            if group:
                for user in group.user_ids:
                    if user.active and user not in hr_users:
                        hr_users.append(user)

        for rec in overdue_lines:
            # 1. Notify the Work Unit Manager
            wu_manager = rec.work_unit_id.sudo().manager_id.user_id
            if wu_manager and activity_type:
                self.env['mail.activity'].sudo().create({
                    'res_model_id': self.env['ir.model'].sudo()._get_id('hr.resignation.clearance'),
                    'res_id': rec.id,
                    'activity_type_id': activity_type.id,
                    'summary': _('ESCALATION: Overdue Clearance Task'),
                    'note': _('The clearance task for %s is overdue.') % (rec.work_unit_id.name or ''),
                    'user_id': wu_manager.id,
                    'date_deadline': fields.Date.today(),
                })

            if activity_type:
                for hr_user in hr_users:
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env['ir.model'].sudo()._get_id('hr.resignation.clearance'),
                        'res_id': rec.id,
                        'activity_type_id': activity_type.id,
                        'summary': _('SLA BREACH: Clearance Overdue for %s') % rec.employee_id.sudo().name,
                        'note': _('The clearance unit %s has failed to clear the employee before the SLA deadline.') % (rec.work_unit_id.name or ''),
                        'user_id': hr_user.id,
                        'date_deadline': fields.Date.today(),
                    })