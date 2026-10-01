# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.mail.tools.discuss import Store
from .pbms_access import send_pbms_inbox_notification

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

    # Workforce Submission Window (Managed by People Solutions Directorate)
    workforce_window_start = fields.Date(
        string="Workforce Window Start Date",
        tracking=True,
        help="Start date of the submission window for Annual Workforce Plan requests set by People Solutions Directorate."
    )
    workforce_window_end = fields.Date(
        string="Workforce Window Closing Date",
        tracking=True,
        help="Closing date of the submission window for Annual Workforce Plan requests set by People Solutions Directorate."
    )
    is_workforce_window_open = fields.Boolean(
        string="Workforce Window Open",
        compute="_compute_is_workforce_window_open",
        help="True if today falls within the Workforce Window Start and Closing dates."
    )
    workforce_window_notified = fields.Boolean(
        string="Workforce Window Notified",
        default=False,
        copy=False,
    )
    workforce_window_notified_date = fields.Datetime(
        string="Notification Sent On",
        readonly=True,
        copy=False,
    )

    @api.depends("workforce_window_start", "workforce_window_end")
    def _compute_is_workforce_window_open(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.workforce_window_start and rec.workforce_window_end:
                rec.is_workforce_window_open = bool(rec.workforce_window_start <= today <= rec.workforce_window_end)
            else:
                rec.is_workforce_window_open = True

    def action_notify_workforce_window(self):
        """People Solutions Directorate sets the submission window and notifies all Branches/Departments."""
        self.ensure_one()
        if not (self.env.user._pbms_is_people_solutions() or self.env.user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
            raise AccessError(_("Only People Solutions Directorate officers or Administrators can notify the workforce submission window."))
        if not self.workforce_window_start or not self.workforce_window_end:
            raise ValidationError(_("Please specify both Workforce Window Start Date and Closing Date before notifying."))
        if self.workforce_window_start > self.workforce_window_end:
            raise ValidationError(_("Workforce Window Start Date cannot be after Closing Date."))

        target_users = self._get_users_with_group("bunna_pbms.group_pbms_branch_user")
        target_users |= self._get_users_with_group("bunna_pbms.group_pbms_district_reviewer")

        summary = _("Annual Workforce Plan Submission Window: %s") % self.name
        note = _(
            "<b>People Solutions Directorate Announcement:</b><br/>"
            "The submission window for the Annual Workforce Plan (%s) has been officially set:<br/>"
            "• <b>Start Date:</b> %s<br/>"
            "• <b>Closing Date:</b> %s<br/>"
            "All Branch Managers and Department Directors are required to initiate and submit their Annual Workforce Plan requests before the closing date."
        ) % (self.name, self.workforce_window_start, self.workforce_window_end)

        self.message_post(body=note, subject=summary)
        self._send_inbox_notification(target_users, summary, note)

        self.write({
            "workforce_window_notified": True,
            "workforce_window_notified_date": fields.Datetime.now(),
        })

    def _send_inbox_notification(self, users_or_partners, subject, body):
        """Send direct in-app inbox notification into Discuss [Notifications] tab (chat bubble)."""
        for cycle in self:
            send_pbms_inbox_notification(self.env, cycle, users_or_partners, subject, body)

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True,
    )
    active = fields.Boolean(default=True)

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)",
        "A planning cycle with this name already exists for this company.",
    )
    _name_date_start_date_end_uniq = models.Constraint(
        "unique(name, date_start, date_end, company_id)",
        "A planning cycle with this name, start date, and end date already exists for this company.",
    )

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for cycle in self:
            if cycle.date_start >= cycle.date_end:
                raise ValidationError("Cycle end date must be after the start date.")

    @api.constrains("name", "date_start", "date_end", "company_id")
    def _check_unique_cycle(self):
        for cycle in self:
            existing = self.search([
                ("name", "=", cycle.name),
                ("date_start", "=", cycle.date_start),
                ("date_end", "=", cycle.date_end),
                ("company_id", "=", cycle.company_id.id),
                ("id", "!=", cycle.id),
            ])
            if existing:
                raise ValidationError(_(
                    "A planning cycle with the name '%(name)s', start date '%(start)s', "
                    "and end date '%(end)s' already exists for this company.\n"
                    "Please use a different name or date range.",
                    name=cycle.name,
                    start=cycle.date_start,
                    end=cycle.date_end
                ))

    def _to_local_date(self, dt):
        """Convert a UTC Datetime to date for deadline comparisons."""
        if not dt:
            return False
        try:
            return fields.Datetime.context_timestamp(self, dt).date()
        except Exception:
            return dt.date()

    @api.constrains("date_start", "date_end", "branch_deadline", "district_deadline", "head_office_deadline", "board_deadline")
    def _check_submission_deadlines(self):
        for cycle in self:
            start = cycle.date_start
            end = cycle.date_end

            branch_dt = cycle.branch_deadline
            dist_dt = cycle.district_deadline
            ho_dt = cycle.head_office_deadline
            board_dt = cycle.board_deadline

            branch_d = cycle._to_local_date(branch_dt)
            dist_d = cycle._to_local_date(dist_dt)
            ho_d = cycle._to_local_date(ho_dt)
            board_d = cycle._to_local_date(board_dt)

            # 1. Branch Submission Deadline must be after Planning Cycle Start Date and on/before End Date
            if branch_dt:
                if start and branch_d < start:
                    raise ValidationError(_(
                        "Branch Submission Deadline (%(deadline)s) cannot be before the Planning Cycle Start Date (%(start)s). "
                        "The branch input deadline must be after the planning cycle start date."
                    ) % {
                        "deadline": fields.Datetime.to_string(branch_dt),
                        "start": fields.Date.to_string(start),
                    })
                if end and branch_d > end:
                    raise ValidationError(_(
                        "Branch Submission Deadline (%(deadline)s) cannot be after the Planning Cycle End Date (%(end)s)."
                    ) % {
                        "deadline": fields.Datetime.to_string(branch_dt),
                        "end": fields.Date.to_string(end),
                    })

            # 2. District Endorsement Deadline must be after Branch Submission Deadline
            if dist_dt:
                if branch_dt and dist_dt <= branch_dt:
                    raise ValidationError(_(
                        "District Endorsement Deadline (%(dist)s) must be after the Branch Submission Deadline (%(branch)s)."
                    ) % {
                        "dist": fields.Datetime.to_string(dist_dt),
                        "branch": fields.Datetime.to_string(branch_dt),
                    })
                if start and dist_d < start:
                    raise ValidationError(_(
                        "District Endorsement Deadline (%(dist)s) cannot be before the Planning Cycle Start Date (%(start)s)."
                    ) % {
                        "dist": fields.Datetime.to_string(dist_dt),
                        "start": fields.Date.to_string(start),
                    })
                if end and dist_d > end:
                    raise ValidationError(_(
                        "District Endorsement Deadline (%(dist)s) cannot be after the Planning Cycle End Date (%(end)s)."
                    ) % {
                        "dist": fields.Datetime.to_string(dist_dt),
                        "end": fields.Date.to_string(end),
                    })

            # 3. Head Office Review Deadline must be after District Endorsement Deadline
            if ho_dt:
                if dist_dt and ho_dt <= dist_dt:
                    raise ValidationError(_(
                        "Head Office Review Deadline (%(ho)s) must be after the District Endorsement Deadline (%(dist)s)."
                    ) % {
                        "ho": fields.Datetime.to_string(ho_dt),
                        "dist": fields.Datetime.to_string(dist_dt),
                    })
                elif branch_dt and ho_dt <= branch_dt:
                    raise ValidationError(_(
                        "Head Office Review Deadline (%(ho)s) must be after the Branch Submission Deadline (%(branch)s)."
                    ) % {
                        "ho": fields.Datetime.to_string(ho_dt),
                        "branch": fields.Datetime.to_string(branch_dt),
                    })
                if start and ho_d < start:
                    raise ValidationError(_(
                        "Head Office Review Deadline (%(ho)s) cannot be before the Planning Cycle Start Date (%(start)s)."
                    ) % {
                        "ho": fields.Datetime.to_string(ho_dt),
                        "start": fields.Date.to_string(start),
                    })
                if end and ho_d > end:
                    raise ValidationError(_(
                        "Head Office Review Deadline (%(ho)s) cannot be after the Planning Cycle End Date (%(end)s)."
                    ) % {
                        "ho": fields.Datetime.to_string(ho_dt),
                        "end": fields.Date.to_string(end),
                    })

            # 4. Board Approval Deadline must be after Head Office Review Deadline and on/before End Date
            if board_dt:
                if ho_dt and board_dt <= ho_dt:
                    raise ValidationError(_(
                        "Board Approval Deadline (%(board)s) must be after the Head Office Review Deadline (%(ho)s)."
                    ) % {
                        "board": fields.Datetime.to_string(board_dt),
                        "ho": fields.Datetime.to_string(ho_dt),
                    })
                elif dist_dt and board_dt <= dist_dt:
                    raise ValidationError(_(
                        "Board Approval Deadline (%(board)s) must be after the District Endorsement Deadline (%(dist)s)."
                    ) % {
                        "board": fields.Datetime.to_string(board_dt),
                        "dist": fields.Datetime.to_string(dist_dt),
                    })
                elif branch_dt and board_dt <= branch_dt:
                    raise ValidationError(_(
                        "Board Approval Deadline (%(board)s) must be after the Branch Submission Deadline (%(branch)s)."
                    ) % {
                        "board": fields.Datetime.to_string(board_dt),
                        "branch": fields.Datetime.to_string(branch_dt),
                    })
                if start and board_d < start:
                    raise ValidationError(_(
                        "Board Approval Deadline (%(board)s) cannot be before the Planning Cycle Start Date (%(start)s)."
                    ) % {
                        "board": fields.Datetime.to_string(board_dt),
                        "start": fields.Date.to_string(start),
                    })
                if end and board_d > end:
                    raise ValidationError(_(
                        "Board Approval Deadline (%(deadline)s) cannot be after the Planning Cycle End Date (%(end)s). "
                        "The board approval deadline must be on or before the end date."
                    ) % {
                        "deadline": fields.Datetime.to_string(board_dt),
                        "end": fields.Date.to_string(end),
                    })

    @api.onchange("date_start", "date_end", "branch_deadline", "district_deadline", "head_office_deadline", "board_deadline")
    def _onchange_submission_deadlines(self):
        try:
            self._check_submission_deadlines()
        except ValidationError as e:
            return {
                "warning": {
                    "title": _("Invalid Deadline Sequence"),
                    "message": str(e.args[0] if e.args else e),
                }
            }

    # =========================================================================
    # FR-WP-057: BUDGET YEAR STATUS NOTIFICATIONS
    # =========================================================================
    @api.model
    def _get_users_with_group(self, group_xmlid):
        """Find active users belonging to a group by xmlid in Odoo 19."""
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        try:
            return self.env["res.users"].search([
                ("all_group_ids", "in", group.id),
                ("active", "=", True),
            ])
        except Exception:
            return self.env["res.users"].search([("active", "=", True)]).filtered(lambda u: u.has_group(group_xmlid))

    def _get_all_planning_users(self):
        """Find all active users across all Branches, Districts, and Head Offices,
        as well as all PBMS planning role group members.
        """
        users = self.env["res.users"]

        # 1. PBMS Role Groups (Branch Users, District Reviewers, HO Reviewers, Approvers, SPPMD Managers, etc.)
        group_xmlids = (
            "bunna_pbms.group_pbms_branch_user",
            "bunna_pbms.group_pbms_district_reviewer",
            "bunna_pbms.group_pbms_ho_reviewer",
            "bunna_pbms.group_pbms_approver",
            "bunna_pbms.group_pbms_manager",
            "bunna_pbms.group_pbms_budget_hiring_committee",
            "bunna_pbms.group_pbms_ceo",
            "bunna_pbms.group_pbms_respective_chief",
            "bunna_pbms.group_pbms_people_solutions",
            "bunna_pbms.group_pbms_cpco",
            "bunna_pbms.group_pbms_people_operations",
        )
        group_ids = []
        for g_xmlid in group_xmlids:
            g = self.env.ref(g_xmlid, raise_if_not_found=False)
            if g:
                group_ids.append(g.id)
        if group_ids:
            try:
                users |= self.env["res.users"].search([
                    ("all_group_ids", "in", group_ids),
                    ("active", "=", True),
                ])
            except Exception:
                try:
                    users |= self.env["res.users"].search([
                        ("groups_id", "in", group_ids),
                        ("active", "=", True),
                    ])
                except Exception:
                    for g_xmlid in group_xmlids:
                        users |= self._get_users_with_group(g_xmlid)

        # 2. Operating Units: All Branches, Districts, Departments, and Head Offices
        if "operating.unit" in self.env:
            target_ous = self.env["operating.unit"].search([
                ("active", "=", True),
            ])
            if hasattr(target_ous, "user_ids"):
                users |= target_ous.mapped("user_ids").filtered(lambda u: u.active)
            if hasattr(target_ous, "manager_id"):
                users |= target_ous.mapped("manager_id.user_id").filtered(lambda u: u.active)

            # Department managers
            if "hr.department" in self.env:
                depts = self.env["hr.department"].search([("active", "=", True)])
                if hasattr(depts, "manager_id"):
                    users |= depts.mapped("manager_id.user_id").filtered(lambda u: u.active)

            if hasattr(self.env["res.users"], "assigned_operating_unit_ids"):
                ou_assigned = self.env["res.users"].search([
                    ("active", "=", True),
                    ("assigned_operating_unit_ids", "in", target_ous.ids),
                ])
                if ou_assigned:
                    users |= ou_assigned

            if hasattr(self.env["res.users"], "default_operating_unit_id"):
                ou_default = self.env["res.users"].search([
                    ("active", "=", True),
                    ("default_operating_unit_id", "in", target_ous.ids),
                ])
                if ou_default:
                    users |= ou_default

        root_user = self.env.ref("base.user_root", raise_if_not_found=False)
        if root_user:
            users -= root_user
        return users.filtered(lambda u: u.active)

    def _get_all_planning_partners(self):
        """Find all users involved in plan & budget preparation and review across all branches, districts, and head offices."""
        return self._get_all_planning_users().mapped("partner_id")

    def _notify_cycle_status_change(self, status_title, message):
        """FR-WP-057: Broadcast notification across ERP Inbox and Email when budget year opens/closes."""
        for cycle in self:
            partners = cycle._get_all_planning_partners()
            msg = _(
                "<b>Planning Cycle Status Update: %s</b><br/>"
                "<b>Planning Cycle:</b> %s (Period: %s to %s)<br/>"
                "<b>Status:</b> %s<br/>"
                "%s"
            ) % (
                status_title,
                cycle.name,
                cycle.date_start,
                cycle.date_end,
                dict(cycle._fields['state'].selection).get(cycle.state, cycle.state),
                message,
            )

            cycle._send_inbox_notification(partners, _("Planning Cycle: %s") % status_title, msg)

            # Send Email Template
            template = self.env.ref("bunna_pbms.mail_template_cycle_status_changed", raise_if_not_found=False)
            if template:
                try:
                    template.send_mail(cycle.id, force_send=False, raise_exception=False, email_values={
                        "recipient_ids": [(4, pid) for pid in partners.ids],
                    })
                except Exception as e:
                    _logger.warning("Failed to send cycle status email: %s", e)

    def action_start_budget_call(self):
        """Start budget call - Button: 'Start Budget Call'"""
        self.ensure_one()

        if self.state == 'budget_call':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Notice'),
                    'message': _('Budget call has already been started for cycle "%s".') % self.name,
                    'type': 'warning',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
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
        self.write({'state': 'budget_call'})

        deadline_lines = []
        if self.branch_deadline:
            deadline_lines.append(_("• <b>Branch Submission Deadline:</b> %s") % fields.Datetime.to_string(self.branch_deadline))
        if self.district_deadline:
            deadline_lines.append(_("• <b>District Endorsement Deadline:</b> %s") % fields.Datetime.to_string(self.district_deadline))
        if self.head_office_deadline:
            deadline_lines.append(_("• <b>Head Office Review Deadline:</b> %s") % fields.Datetime.to_string(self.head_office_deadline))
        if self.board_deadline:
            deadline_lines.append(_("• <b>Board Approval Deadline:</b> %s") % fields.Datetime.to_string(self.board_deadline))
        deadlines_text = "<br/>".join(deadline_lines) if deadline_lines else _("Submission deadlines will be announced shortly.")

        budget_call_msg = _(
            "The annual Budget Call for <b>%s</b> has officially started.<br/>"
            "All relevant Line Managers and Work Unit Heads are required to prepare and submit their plan and budget requests within the specified deadlines:<br/>"
            "%s"
        ) % (self.name, deadlines_text)

        self._notify_cycle_status_change(
            _("Budget Call Issued"),
            budget_call_msg,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Budget call started for "%s".') % self.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_open_for_input(self):
        self.write({"state": "open"})
        for cycle in self:
            deadline_info = _(
                "<b>Submission Deadlines:</b><br/>"
                "- Branch Submission: %s<br/>"
                "- District Endorsement: %s<br/>"
                "- Head Office Review: %s<br/>"
                "- Board Approval: %s"
            ) % (
                cycle.branch_deadline or _("TBA"),
                cycle.district_deadline or _("TBA"),
                cycle.head_office_deadline or _("TBA"),
                cycle.board_deadline or _("TBA"),
            )
            cycle._notify_cycle_status_change(
                _("Budget Year Opened for Unit Input"),
                _("Planning cycle '%s' is now open for plan and budget input.<br/>%s") % (cycle.name, deadline_info),
            )

    def action_start_consolidation(self):
        self.write({"state": "consolidation"})
        self._notify_cycle_status_change(
            _("Consolidation & Hearings Started"),
            _("Unit submissions closed. District and Bank-wide consolidation is now in progress."),
        )

    def action_send_to_board(self):
        self.write({"state": "board_approval"})
        self._notify_cycle_status_change(
            _("Submitted for Board Approval"),
            _("Consolidated Annual Business Plan & Budget submitted for Board of Directors review."),
        )

    def action_approve(self):
        self.write({"state": "approved"})
        self._notify_cycle_status_change(
            _("Annual Business Plan Approved & Cascaded"),
            _("Official Board approval granted. Approved targets and budgets are now cascaded to all operating units."),
        )

    def action_close(self):
        self.write({"state": "closed"})
        self._notify_cycle_status_change(
            _("Budget Year Closed"),
            _("Planning cycle '%s' is now officially closed and locked.") % self.name,
        )

    def is_editable(self):
        self.ensure_one()
        return self.state == "open"

    # ---------------------------------------------------------------
    # Notifications (BRD 8.2 "Notifications and Alerts")
    # ---------------------------------------------------------------
    _REMINDER_MODELS = [
        "pbms.planning.category",
    ]

    @api.model
    def _cron_send_deadline_reminders(self):
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
        if not line or not line.org_unit_id:
            return False
        unit = line.org_unit_id
        if audience == "unit_manager":
            if hasattr(unit, "manager_id") and unit.manager_id and unit.manager_id.user_id:
                return unit.manager_id.user_id
            if hasattr(unit, "user_ids") and unit.user_ids:
                return unit.user_ids[0]
            return False
        if audience == "district_reviewer":
            district = line.district_id or (self.env["pbms.workflow.mixin"]._find_district_ancestor(unit) if hasattr(self.env["pbms.workflow.mixin"], "_find_district_ancestor") else False)
            if district:
                if hasattr(district, "manager_id") and district.manager_id and district.manager_id.user_id:
                    return district.manager_id.user_id
                if hasattr(district, "user_ids") and district.user_ids:
                    return district.user_ids[0]
            return False
        if audience == "ho_reviewer":
            if hasattr(unit, "manager_id") and unit.manager_id and unit.manager_id.user_id:
                return unit.manager_id.user_id
            if hasattr(unit, "user_ids") and unit.user_ids:
                return unit.user_ids[0]
            return False
        return False

    def _thread_to_store(self, store: Store, fields, *, request_list=None):
        """Override to ensure regular users only see activities assigned to/created by themselves in Chatter.
        SPPMD administrators / PBMS managers retain full visibility over all bank-wide activities.
        """
        is_admin = (
            self.env.user._pbms_is_sppmd_admin()
            or self.env.user._pbms_is_manager()
            or self.env.is_admin()
            or self.env.su
        )
        if request_list and "activities" in request_list and not is_admin:
            req_list = [r for r in request_list if r != "activities"]
            super()._thread_to_store(store, fields, request_list=req_list)
            for cycle in self:
                user_activities = cycle.activity_ids.filtered(
                    lambda a: a.user_id == self.env.user or a.create_uid == self.env.user
                )
                store.add(cycle, {"activities": Store.Many(user_activities)}, as_thread=True)
            return
        super()._thread_to_store(store, fields, request_list=request_list)
