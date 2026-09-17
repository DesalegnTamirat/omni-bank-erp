

from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
from datetime import timedelta



class HrResignationClearanceLineItem(models.Model):

    _name        = 'hr.resignation.clearance.line.item'
    _description = 'Clearance Line Checklist Item'
    _order       = 'sequence asc'

    clearance_line_id = fields.Many2one(
        'hr.resignation.clearance',
        required=True, ondelete='cascade', index=True)
    sequence     = fields.Integer(default=10)
    name         = fields.Char(required=True, string='Task')
    is_mandatory = fields.Boolean(default=True)
    is_done      = fields.Boolean(default=False, string='Done')
    can_clear    = fields.Boolean(compute='_compute_can_clear', string='Can Clear')

    @api.depends_context('uid')
    def _compute_can_clear(self):
        is_officer = self.env.user.has_group('hr_resignation.group_clearance_officer')
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            is_responsible = (rec.clearance_line_id.responsible_user == self.env.user)
            # Responsible user can only clear if they also hold the Clearance Officer role
            rec.can_clear = is_admin or (is_responsible and is_officer)

    done_by      = fields.Many2one('res.users', readonly=True)
    done_date    = fields.Datetime(readonly=True)
    note         = fields.Text(string='Guidance Note')

    def write(self, vals):
        if 'is_done' in vals:
            for rec in self:
                is_officer = self.env.user.has_group('hr_resignation.group_clearance_officer')
                is_admin = self.env.user.has_group('base.group_system')
                is_responsible = (rec.clearance_line_id.responsible_user == self.env.user)
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
            if rec.clearance_line_id.resignation_id.state not in ('clearance', 'cleared', 'settled', 'done'):
                raise UserError(_('You cannot mark tasks as cleared until the Release Date is set and Handover is completed.'))
            if rec.is_done:
                rec.write({'is_done': False})
            else:
                rec.write({'is_done': True})

    def action_mark_done(self):
        for rec in self:
            if rec.clearance_line_id.resignation_id.state not in ('clearance', 'cleared', 'settled', 'done'):
                raise UserError(_('You cannot mark tasks as cleared until the Release Date is set and Handover is completed.'))
            if not rec.can_clear:
                raise UserError(_('You are not authorized to clear this task. Only the assigned responsible user (with Clearance Officer role), the work unit manager, or Admin can clear tasks.'))
            rec.write({'is_done': True})

    def action_unmark_done(self):
        for rec in self:
            if rec.clearance_line_id.resignation_id.state not in ('clearance', 'cleared', 'settled', 'done'):
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
    _order       = 'sequence asc'

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

    @api.depends('work_unit_id.name', 'employee_id.name', 'resignation_id.name')
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

    notification_sent = fields.Boolean(
        default=False, readonly=True,
        string='Notified',
        help='True once the responsible user has been sent their task notification.')

    sdt_days = fields.Integer(string='SDT (Days)')
    pending_since = fields.Datetime(string='Pending Since', readonly=True)
    is_overdue = fields.Boolean(compute='_compute_is_overdue', store=True)

    @api.depends('state', 'pending_since', 'sdt_days', 'sla_deadline')
    def _compute_is_overdue(self):
        for rec in self:
            if rec.state == 'pending':
                if rec.sla_deadline:
                    rec.is_overdue = fields.Date.today() > rec.sla_deadline
                elif rec.pending_since and rec.sdt_days:
                    deadline = rec.pending_since + timedelta(days=rec.sdt_days)
                    rec.is_overdue = fields.Datetime.now() > deadline
                else:
                    rec.is_overdue = False
            else:
                rec.is_overdue = False

    can_approve = fields.Boolean(compute='_compute_can_approve', string='Can Approve')

    @api.depends_context('uid')
    def _compute_can_approve(self):
        is_hr = self.env.user.has_group('hr.group_hr_user')
        for rec in self:
            is_officer = (rec.responsible_user and rec.responsible_user.id == self.env.user.id)
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
    items_done         = fields.Integer(compute='_compute_item_counts', string='Done')
    items_progress     = fields.Char(compute='_compute_item_counts', string='Item Progress')
    mandatory_items_ok = fields.Boolean(
        compute='_compute_mandatory_items_ok', store=True,
        help='True when all mandatory checklist items are ticked.')

    # ── Related fields for display ────────────────────────────────────────────
    employee_id = fields.Many2one(
        related='resignation_id.employee_id', store=True, string='Employee')

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
            rec._check_clearance_permission()
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
            
            now  = fields.Datetime.now()
            vals = {
                'state':        'cleared',
                'cleared_by':   self.env.user.id,
                'cleared_date': now,
            }
            rec.write(vals)
            
            # Post a professional log to the chatter
            rec.message_post(
                body=_('Clearance completed successfully by %s.') % self.env.user.name,
                message_type='notification'
            )
            # Notify the responsible officer and HR group via Discuss popup
            # instead of posting to chatter.
            hr_group = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
            notify_partners = set()
            if hr_group:
                for u in hr_group.sudo().all_user_ids.filtered(lambda u: u.active):
                    notify_partners.add(u.partner_id.id)
            emp_user = rec.resignation_id.employee_id.sudo().user_id
            if emp_user and emp_user.active:
                notify_partners.add(emp_user.partner_id.id)
            wu_manager = rec.work_unit_id.sudo().manager_id.user_id
            if wu_manager and wu_manager.active:
                notify_partners.add(wu_manager.partner_id.id)
            if notify_partners:
                rec.resignation_id.message_notify(
                    partner_ids=list(notify_partners),
                    subject=_('Clearance Completed: %s — %s') % (
                        rec.resignation_id.employee_id.sudo().name,
                        rec.work_unit_id.name or _('Clearance'),
                    ),
                    body=_('Clearance item <strong>%s</strong> has been cleared by %s for %s (%s).') % (
                        rec.work_unit_id.name or _('Clearance'),
                        self.env.user.name,
                        rec.resignation_id.employee_id.sudo().name,
                        rec.resignation_id.name,
                    ),
                )
            try:
                rec._close_clearance_activities(
                    feedback=_('Cleared by %s.') % self.env.user.name)
            except Exception:
                pass

            rec.resignation_id._check_and_advance_cleared()



    # ═══════════════════════════════════════════════════════════════════════════
    #  PERMISSION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _check_clearance_permission(self):
        self.ensure_one()
        user           = self.env.user
        is_hr          = user.has_group('hr.group_hr_user')
        is_admin       = user.has_group('base.group_system')
        is_responsible = (self.responsible_user == user)
        if not (is_hr or is_responsible or is_admin):
            raise AccessError(_(
                'Only the responsible officer (%s), an HR user, or an administrator '
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
                    activities = self.env['mail.activity'].search([
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
                    activity_type = self.env['mail.activity.type'].search(
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
                    self.env['mail.activity'].create({
                        'res_model_id': self.env['ir.model']._get_id(
                            'hr.resignation.clearance'),
                        'res_id':           rec.id,
                        'activity_type_id': activity_type.id,
                        'summary':          _('Clearance task: %s') % (
                            rec.work_unit_id.name or ''),
                        'note':             note_body,
                        'user_id':          rec.responsible_user.id,
                        'date_deadline':    rec.release_date or fields.Date.today(),
                    })

            except Exception:
                # Never crash the clearance workflow due to notification failure.
                pass

    @api.model
    def _cron_check_overdue_clearances(self):
        overdue_lines = self.search([
            ('state', '=', 'pending'),
            ('is_overdue', '=', True)
        ])
        if not overdue_lines:
            return

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            activity_type = self.env['mail.activity.type'].search([], limit=1)

        # Get all HR users to notify
        hr_users = []
        for group_ref in ['hr_resignation.group_resignation_hr_manager', 'hr_resignation.group_hr_officer']:
            group = self.env.ref(group_ref, raise_if_not_found=False)
            if group:
                for user in group.user_ids:
                    if user.active and user not in hr_users:
                        hr_users.append(user)

        for rec in overdue_lines:
            # 1. Notify the Work Unit Manager
            wu_manager = rec.work_unit_id.sudo().manager_id.user_id
            if wu_manager and activity_type:
                self.env['mail.activity'].create({
                    'res_model_id': self.env['ir.model']._get_id('hr.resignation.clearance'),
                    'res_id': rec.id,
                    'activity_type_id': activity_type.id,
                    'summary': _('ESCALATION: Overdue Clearance Task'),
                    'note': _('The clearance task for %s is overdue.') % (rec.work_unit_id.name or ''),
                    'user_id': wu_manager.id,
                    'date_deadline': fields.Date.today(),
                })
            

            if activity_type:
                for hr_user in hr_users:
                    self.env['mail.activity'].create({
                        'res_model_id': self.env['ir.model']._get_id('hr.resignation.clearance'),
                        'res_id': rec.id,
                        'activity_type_id': activity_type.id,
                        'summary': _('SLA BREACH: Clearance Overdue for %s') % rec.employee_id.name,
                        'note': _('The clearance unit %s has failed to clear the employee before the SLA deadline.') % (rec.work_unit_id.name or ''),
                        'user_id': hr_user.id,
                        'date_deadline': fields.Date.today(),
                    })