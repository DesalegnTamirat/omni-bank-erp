# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PlanningWorkUnitManpower(models.Model):
    _name = 'planning.work.unit.manpower'
    _description = 'Work Unit Man Power'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    def _default_work_unit_id(self):
        employee = self.env.user.employee_id
        return employee.default_operating_unit_id.id if employee else False

    name = fields.Char(compute='_compute_name', store=True)

    work_unit_id = fields.Many2one(
        'operating.unit', string='Work Unit', required=True, tracking=True,
        default=_default_work_unit_id,
    )

    fiscal_year_id = fields.Many2one(
        'planning.fiscal.year', string='Fiscal Year', required=True, tracking=True)

    available_fiscal_year_ids = fields.Many2many(
        'planning.fiscal.year', compute='_compute_available_fiscal_year_ids',
        help="Technical field: Fiscal Years not already tied to an active "
             "(Draft/Initiated/Approved) plan for the selected Work Unit. "
             "Used to filter the Fiscal Year dropdown.")

    date_start = fields.Date(string='Start Date', compute='_compute_dates', store=True, readonly=True)
    date_end = fields.Date(string='End Date', compute='_compute_dates', store=True, readonly=True)

    # company_id = fields.Many2one(
    #     'res.company', string='Company', default=lambda self: self.env.company)

    manpower_line_ids = fields.One2many(
        'planning.manpower.line', 'work_unit_manpower_id', string='Man Power Details')

    total_headcount = fields.Integer(
        string='Total Head Count', compute='_compute_total_headcount', store=True)

    approver_id = fields.Many2one(
        'hr.employee', string='Approver', compute='_compute_approver_id',
        store=True, readonly=True,
        help="The employee, resolved from the parent Work Unit hierarchy, who "
             "is responsible for approving or rejecting this plan.")

    initiator_id = fields.Many2one(
        'hr.employee', string='Initiated By', readonly=True, copy=False, tracking=True,
        help="The employee who initiated (submitted) this plan. This person "
             "is not permitted to also approve or reject it, to enforce "
             "segregation of duties.")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('deleted', 'Deleted'),
    ], string='Status', default='draft', tracking=True, required=True)

    del_flg = fields.Selection([
        ('N', 'No'),
        ('Y', 'Yes'),
    ], string='Deleted', default='N', copy=False, tracking=True, required=True,
        help="Soft-delete marker. 'Y' means this record is deleted and is "
             "hidden from normal views by the associated record rule, but "
             "the row itself is kept in the database.")

    # NOTE: no longer a plain _sql_constraints unique(work_unit_id, fiscal_year_id).
    # A work unit + fiscal year combo IS allowed to repeat once the earlier
    # record is Rejected or soft-deleted (del_flg = 'Y'). Enforced instead by
    # _check_unique_active_fiscal_year below, since a flat SQL UNIQUE index
    # can't express that conditional logic.

    @api.depends('work_unit_id', 'fiscal_year_id')
    def _compute_name(self):
        for rec in self:
            rec.name = "%s / %s" % (
                rec.work_unit_id.name or '', rec.fiscal_year_id.name or '')

    @api.depends('manpower_line_ids.total_headcount')
    def _compute_total_headcount(self):
        for rec in self:
            rec.total_headcount = sum(rec.manpower_line_ids.mapped('total_headcount'))

    @api.depends('work_unit_id', 'work_unit_id.parent_unit')
    def _compute_approver_id(self):
        Employee = self.env['hr.employee']
        for rec in self:
            approver = Employee.browse()
            parent_unit = rec.work_unit_id.parent_unit if rec.work_unit_id else False
            # Walk up the operating unit hierarchy until we find an employee
            # whose default_operating_unit_id matches a parent unit.
            while parent_unit and not approver:
                approver = Employee.search([
                    ('default_operating_unit_id', '=', parent_unit.id)
                ], limit=1)
                parent_unit = parent_unit.parent_unit
            rec.approver_id = approver

    @api.depends('fiscal_year_id', 'fiscal_year_id.date_start', 'fiscal_year_id.date_end')
    def _compute_dates(self):
        for rec in self:
            rec.date_start = rec.fiscal_year_id.date_start if rec.fiscal_year_id else False
            rec.date_end = rec.fiscal_year_id.date_end if rec.fiscal_year_id else False

    @api.depends('work_unit_id')
    def _compute_available_fiscal_year_ids(self):
        FiscalYear = self.env['planning.fiscal.year']
        all_fiscal_years = FiscalYear.search([])
        for rec in self:
            if not rec.work_unit_id:
                rec.available_fiscal_year_ids = all_fiscal_years
                continue
            # "Active" = still blocking (Draft/Initiated/Approved) and not
            # soft-deleted. Rejected or soft-deleted rows free up their
            # fiscal year for reuse.
            blocking = self.search([
                ('work_unit_id', '=', rec.work_unit_id.id),
                ('del_flg', '=', 'N'),
                ('state', 'not in', ('rejected',)),
                ('id', '!=', rec._origin.id if rec._origin else rec.id),
            ])
            used_fiscal_year_ids = blocking.mapped('fiscal_year_id').ids
            # Always keep the currently-set fiscal year selectable too,
            # so an existing record doesn't appear to lose its own value.
            available = all_fiscal_years.filtered(
                lambda fy: fy.id not in used_fiscal_year_ids or fy == rec.fiscal_year_id
            )
            rec.available_fiscal_year_ids = available

    @api.constrains('work_unit_id', 'fiscal_year_id', 'state', 'del_flg')
    def _check_unique_active_fiscal_year(self):
        for rec in self:
            if not rec.work_unit_id or not rec.fiscal_year_id:
                continue
            if rec.del_flg == 'Y' or rec.state == 'rejected':
                continue
            conflict = self.search([
                ('id', '!=', rec.id),
                ('work_unit_id', '=', rec.work_unit_id.id),
                ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                ('del_flg', '=', 'N'),
                ('state', 'not in', ('rejected',)),
            ], limit=1)
            if conflict:
                raise ValidationError(_(
                    "A Man Power plan for Work Unit '%s' and Fiscal Year '%s' "
                    "already exists (status: %s) and is not Rejected or "
                    "Deleted. Please choose a different Fiscal Year."
                ) % (
                    rec.work_unit_id.name,
                    rec.fiscal_year_id.name,
                    dict(rec._fields['state'].selection).get(conflict.state),
                ))

    def _notify_via_chat(self, partner, body):
        """Post a message into a real Discuss direct-message conversation
        between the current user and `partner`, instead of the record's
        chatter. Opens/reuses the existing 1-to-1 DM channel."""
        self.ensure_one()
        if not partner:
            return
        Channel = self.env['discuss.channel']
        channel = Channel._get_or_create_chat(partners_to=[partner.id])
        if not channel:
            return
        channel.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )

    def action_initiate(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only records in Draft can be Initiated."))
            if not rec.manpower_line_ids:
                raise UserError(_("Please add at least one Man Power line before initiating."))
            rec.initiator_id = self.env.user.employee_id
            rec.state = 'initiated'

            # Notify the approver: schedule a To-Do activity AND send a
            # direct chat message (not a chatter log entry).
            if rec.approver_id and rec.approver_id.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Manpower Plan Approval Request'),
                    note=_('Please review and approve the manpower plan for %s.') % rec.name,
                    user_id=rec.approver_id.user_id.id
                )
                rec._notify_via_chat(
                    rec.approver_id.user_id.partner_id,
                    _("Manpower Plan '%s' has been initiated and is awaiting your approval.") % rec.name,
                )

    def action_approve(self):
        for rec in self:
            if rec.state != 'initiated':
                raise UserError(_("Only Initiated records can be Approved."))
            rec._check_approval_rights()
            rec.state = 'approved'

            rec.activity_feedback(['mail.mail_activity_data_todo'], feedback=_("Approved"))

            if rec.initiator_id and rec.initiator_id.user_id:
                rec._notify_via_chat(
                    rec.initiator_id.user_id.partner_id,
                    _("Your Manpower Plan '%s' has been approved by %s.") % (rec.name, self.env.user.name),
                )

    def action_reject(self):
        for rec in self:
            if rec.state != 'initiated':
                raise UserError(_("Only Initiated records can be Rejected."))
            rec._check_approval_rights()
            rec.state = 'rejected'

            rec.activity_feedback(['mail.mail_activity_data_todo'], feedback=_("Rejected"))

            if rec.initiator_id and rec.initiator_id.user_id:
                rec._notify_via_chat(
                    rec.initiator_id.user_id.partner_id,
                    _("Your Manpower Plan '%s' has been rejected by %s.") % (rec.name, self.env.user.name),
                )

    def action_reset_draft(self):
        for rec in self:
            rec.state = 'draft'

    def unlink(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    "'%s' cannot be deleted because it is no longer in "
                    "Draft (current status: %s). Only Draft records may be "
                    "deleted."
                ) % (rec.name, dict(rec._fields['state'].selection).get(rec.state)))
        # Soft delete: flag the row and mark it Deleted instead of
        # physically removing it.
        self.write({'del_flg': 'Y', 'state': 'deleted'})
        return True

    def _check_approval_rights(self):
        self.ensure_one()
        current_employee = self.env.user.employee_id

        # Segregation of duties: whoever initiated the plan cannot also
        # approve or reject it, even if they are a Planning Manager or
        # happen to also be the resolved approver_id.
        if self.initiator_id and current_employee == self.initiator_id:
            raise UserError(_(
                "You initiated this plan and cannot also approve or reject "
                "it. Approval must be performed by a different, designated "
                "approver."
            ))

        if self.env.user.has_group('custom_planning.group_planning_manager'):
            return True

        if not self.approver_id or current_employee != self.approver_id:
            raise UserError(_(
                "Only the designated approving manager (%s) for Work Unit '%s' "
                "can approve or reject this plan, based on the organizational hierarchy."
            ) % (self.approver_id.name or _('Not Set'), self.work_unit_id.name))
        return True
