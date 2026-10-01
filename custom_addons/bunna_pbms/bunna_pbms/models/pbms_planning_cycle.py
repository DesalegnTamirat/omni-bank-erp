# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PbmsPlanningCycle(models.Model):
    """Annual Planning Cycle, e.g. 'FY 2026/27 (Jul-Jun)'.

    Every planning line (deposit plan, expense plan, ...) belongs to a
    cycle. The cycle carries the submission deadlines used by the
    reminder cron and the state that gates whether branches/districts can
    still edit their lines (locking the cycle after Board approval avoids
    figures moving after the official plan is signed).
    """
    _name = "pbms.planning.cycle"
    _description = "Annual Planning Cycle"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "date_start desc"
    _mail_flat_thread = False

    name = fields.Char(required=True, index=True, help="e.g. FY 2026/27")
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)

    state = fields.Selection(
        [
            ("draft", "Not Opened"),
            ("budget_call", "Budget Call Issued"),
            ("open", "Open for Unit Input"),
            ("consolidation", "Consolidation & Hearing"),
            ("board_approval", "Board Approval"),
            ("approved", "Approved / Cascaded"),
            ("closed", "Closed"),
        ],
        default="draft", required=True, tracking=True, index=True,
    )

    branch_deadline = fields.Datetime(string="Branch Submission Deadline")
    district_deadline = fields.Datetime(string="District Endorsement Deadline")
    head_office_deadline = fields.Datetime(string="Head Office Review Deadline")
    board_deadline = fields.Datetime(string="Board Approval Deadline")

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "A planning cycle with this name already exists for this company."),
    ]

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for cycle in self:
            if cycle.date_start >= cycle.date_end:
                raise ValidationError("Cycle end date must be after the start date.")

    def action_open_for_input(self):
        self.write({"state": "open"})

    def action_start_consolidation(self):
        self.write({"state": "consolidation"})

    def action_send_to_board(self):
        self.write({"state": "board_approval"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_close(self):
        self.write({"state": "closed"})

    def is_editable(self):
        self.ensure_one()
        return self.state in ("budget_call", "open", "consolidation")

    # ---------------------------------------------------------------
    # Notifications (BRD 8.2 "Notifications and Alerts")
    # ---------------------------------------------------------------
    _REMINDER_MODELS = [
        "pbms.deposit.plan", "pbms.customer.base.plan", "pbms.fx.plan",
        "pbms.digital.banking.plan", "pbms.general.expense.plan",
        "pbms.manpower.plan", "pbms.fixed.asset.plan",
    ]

    @api.model
    def _cron_send_deadline_reminders(self):
        """One batched search per (model, deadline-stage) pair rather
        than iterating cycles/units one by one, so this stays cheap
        even with many concurrent cycles and hundreds of org units."""
        now = fields.Datetime.now()
        cycles = self.search([
            ("state", "in", ("budget_call", "open", "consolidation")),
        ])
        for cycle in cycles:
            self._remind_pending("submitted", cycle, "district_reviewer",
                                  cycle.district_deadline, now)
            self._remind_pending("district_endorsed", cycle, "ho_reviewer",
                                  cycle.head_office_deadline, now)
            self._remind_pending("draft", cycle, "unit_manager",
                                  cycle.branch_deadline, now)

    def _remind_pending(self, state, cycle, audience, deadline, now):
        if not deadline or deadline > now:
            return
        for model_name in self._REMINDER_MODELS:
            Model = self.env[model_name]
            pending = Model.search([("cycle_id", "=", cycle.id), ("state", "=", state)])
            if not pending:
                continue
            # Group once, notify each responsible user a single time
            # with the list of their pending units, instead of one
            # message per plan line.
            by_user = {}
            for line in pending:
                user = self._resolve_audience_user(line, audience)
                if user:
                    by_user.setdefault(user, []).append(line.org_unit_id.display_name)
            for user, unit_names in by_user.items():
                cycle.message_post(
                    body=_(
                        "Reminder: %(count)s unit(s) still pending at stage "
                        "'%(state)s' past the %(deadline)s deadline: %(units)s",
                        count=len(unit_names), state=state, deadline=deadline,
                        units=", ".join(unit_names[:20]),
                    ),
                    partner_ids=user.partner_id.ids,
                )

    def _resolve_audience_user(self, line, audience):
        if audience == "unit_manager":
            return line.org_unit_id.manager_user_id
        if audience == "district_reviewer":
            district = line.district_id
            return district.manager_user_id if district else False
        if audience == "ho_reviewer":
            return line.org_unit_id.manager_user_id
        return False

    def action_start_budget_call(self):
        """Start budget call - Button: 'Start Budget Call'"""
        self.ensure_one()
        self.refresh()

        if self.state == 'budget_call':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Notice'),
                    'message': _('Budget call has already been started for cycle "%s".') % self.name,
                    'type': 'warning',
                    'sticky': False,
                }
            }

        if self.state != 'draft':
            state_labels = dict(self._fields['state'].selection)
            current_state_label = state_labels.get(self.state, self.state or 'Unknown')
            raise ValidationError(_(
                "Cannot start budget call for cycle '%(name)s'. "
                "Current state: '%(state)s'. "
                "Cycle must be in 'Draft' state to start a new budget call.",
                name=self.name,
                state=current_state_label
            ))

        _logger.info("Starting budget call for cycle %s (ID: %s)", self.name, self.id)

        self.write({
            'state': 'budget_call',
        })

        self.message_post(
            body=_("Budget call started for cycle '%s'.") % self.name,
            subject=_("Budget Call Started"),
            subtype_xmlid="mail.mt_note",
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Budget call started for "%s".') % self.name,
                'type': 'success',
                'sticky': False,
            }
        }