# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = "res.users"

    # Records come from user_ids field of helpdesk.ticket.team.
    helpdesk_team_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.team",
        relation="helpdesk_ticket_team_res_users_rel",
        column1="res_users_id",
        column2="helpdesk_ticket_team_id",
        string="Helpdesk Teams",
    )
    agent_manual_duty_status = fields.Selection(
        selection=[
            ("available", "Available / On Duty"),
            ("busy", "Busy / Handling Call"),
            ("on_break", "On Break"),
            ("offline", "Offline / Absent"),
        ],
        string="Agent Manual Preference",
        default="available",
        help="Manual status preference set by agent or supervisor while checked in.",
    )
    agent_duty_status = fields.Selection(
        selection=[
            ("available", "Available / On Duty"),
            ("busy", "Busy / Handling Call"),
            ("on_break", "On Break"),
            ("offline", "Offline / Absent"),
        ],
        string="Agent Duty Status",
        compute="_compute_agent_duty_status",
        inverse="_inverse_agent_duty_status",
        search="_search_agent_duty_status",
        help="Dynamically checked against Time Off (hr.leave) and Attendance (hr.attendance).",
    )
    agent_duty_status_reason = fields.Char(
        string="Duty Status Reason",
        compute="_compute_agent_duty_status",
        help="Explanation of current duty status derived from Time Off and Attendance.",
    )
    is_on_leave = fields.Boolean(
        string="Is on Leave",
        compute="_compute_is_on_leave",
        search="_search_is_on_leave",
        help="Indicates whether the agent is currently on approved Time Off.",
    )
    leave_status_text = fields.Char(
        string="Leave Status",
        compute="_compute_is_on_leave",
        help="Description of leave status and end date.",
    )
    cc_phone_extension = fields.Char(string="CC Phone / Extension")
    helpdesk_role = fields.Selection(
        selection=[
            # Primary Journey Roles
            ("admin", "Helpdesk Administrator"),
            ("contact_center", "Contact Center Agent (Tier 1)"),
            ("contact_center_front_line", "Contact Center Front Line"),
            ("contact_center_back_line", "Contact Center Backline"),
            ("contact_center_team_leader", "Contact Center Team Leader"),
            ("contact_center_director", "Contact Center Director"),
            ("front_line", "Front line (Team) / Specialist"),
            ("back_line", "Back line (Team) / Senior Specialist"),
            ("team_leader", "Team Leader / Supervisor"),
            ("directorate", "Directorate Director"),
            ("deputy_chief", "Deputy Chief"),
            ("chief", "Chief Officer"),
            ("ceo", "Chief Executive Officer (CEO)"),
            # Cross-Workunit Roles
            ("officer", "Officer"),
            ("senior_principal", "Senior / Principal Officer"),
            ("manager", "Manager / Team Leader"),
            # Technical / Specialty Roles (Aliases)
            ("frontend", "Front line / Frontend Developer"),
            ("backend", "Back line / Backend Developer"),
            ("fullstack", "Fullstack Developer / Specialist"),
            ("database", "Database Administrator / Developer"),
            ("qa", "QA / Tester"),
            ("support", "Support Officer / Specialist"),
            ("supervisor", "Supervisor / Team Lead"),
            ("director", "Directorate Director"),
            ("deputy_cto", "Deputy CTO / Deputy Chief"),
            ("cido", "Chief Information & Digital Officer (CIDO)"),
        ],
        string="Helpdesk Role / Specialization",
        compute="_compute_helpdesk_role",
        inverse="_inverse_helpdesk_role",
        store=True,
        help="Role in Helpdesk Escalation Journey synchronized with Helpdesk Access Rights.",
    )

    @api.depends("group_ids")
    def _compute_helpdesk_role(self):
        for user in self:
            if user.has_group("bunna_helpdesk.group_helpdesk_manager"):
                user.helpdesk_role = "admin"
            elif user.has_group("bunna_helpdesk.group_helpdesk_ceo"):
                user.helpdesk_role = "ceo"
            elif user.has_group("bunna_helpdesk.group_helpdesk_chief"):
                user.helpdesk_role = "chief"
            elif user.has_group("bunna_helpdesk.group_helpdesk_deputy_chief") or user.has_group("bunna_helpdesk.group_helpdesk_executive"):
                user.helpdesk_role = "deputy_chief"
            elif user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director"):
                user.helpdesk_role = "contact_center_director"
            elif user.has_group("bunna_helpdesk.group_helpdesk_director"):
                user.helpdesk_role = "directorate"
            elif user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader"):
                user.helpdesk_role = "contact_center_team_leader"
            elif user.has_group("bunna_helpdesk.group_helpdesk_team_leader"):
                user.helpdesk_role = "team_leader"
            elif user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line"):
                user.helpdesk_role = "contact_center_back_line"
            elif user.has_group("bunna_helpdesk.group_helpdesk_back_line"):
                user.helpdesk_role = "back_line"
            elif user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line"):
                user.helpdesk_role = "contact_center_front_line"
            elif user.has_group("bunna_helpdesk.group_helpdesk_front_line"):
                user.helpdesk_role = "front_line"
            elif user.has_group("bunna_helpdesk.group_helpdesk_contact_center"):
                user.helpdesk_role = "contact_center"
            else:
                user.helpdesk_role = False

    def _inverse_helpdesk_role(self):
        role_to_group = {
            "admin": "bunna_helpdesk.group_helpdesk_manager",
            "contact_center": "bunna_helpdesk.group_helpdesk_contact_center_front_line",
            "contact_center_front_line": "bunna_helpdesk.group_helpdesk_contact_center_front_line",
            "contact_center_back_line": "bunna_helpdesk.group_helpdesk_contact_center_back_line",
            "contact_center_team_leader": "bunna_helpdesk.group_helpdesk_contact_center_team_leader",
            "contact_center_director": "bunna_helpdesk.group_helpdesk_contact_center_director",
            "front_line": "bunna_helpdesk.group_helpdesk_front_line",
            "frontend": "bunna_helpdesk.group_helpdesk_front_line",
            "support": "bunna_helpdesk.group_helpdesk_front_line",
            "officer": "bunna_helpdesk.group_helpdesk_front_line",
            "back_line": "bunna_helpdesk.group_helpdesk_back_line",
            "backend": "bunna_helpdesk.group_helpdesk_back_line",
            "fullstack": "bunna_helpdesk.group_helpdesk_back_line",
            "database": "bunna_helpdesk.group_helpdesk_back_line",
            "qa": "bunna_helpdesk.group_helpdesk_back_line",
            "senior_principal": "bunna_helpdesk.group_helpdesk_back_line",
            "team_leader": "bunna_helpdesk.group_helpdesk_team_leader",
            "supervisor": "bunna_helpdesk.group_helpdesk_team_leader",
            "manager": "bunna_helpdesk.group_helpdesk_manager",
            "directorate": "bunna_helpdesk.group_helpdesk_director",
            "director": "bunna_helpdesk.group_helpdesk_director",
            "deputy_chief": "bunna_helpdesk.group_helpdesk_deputy_chief",
            "deputy_cto": "bunna_helpdesk.group_helpdesk_deputy_chief",
            "chief": "bunna_helpdesk.group_helpdesk_chief",
            "cido": "bunna_helpdesk.group_helpdesk_chief",
            "ceo": "bunna_helpdesk.group_helpdesk_ceo",
        }
        for user in self:
            xmlid = role_to_group.get(user.helpdesk_role)
            if xmlid:
                group = self.env.ref(xmlid, raise_if_not_found=False)
                if group and group not in user.group_ids:
                    user.group_ids = [(4, group.id)]

    @api.depends("agent_manual_duty_status")
    def _compute_is_on_leave(self):
        now = fields.Datetime.now()
        today = fields.Date.today()
        leave_model = self.env.get("hr.leave")
        for user in self:
            emp = getattr(user.sudo(), "employee_id", False) or (user.sudo().employee_ids[0] if getattr(user.sudo(), "employee_ids", False) else False)
            on_leave = False
            leave_desc = ""

            # 1. Direct standard Odoo user.leave_date_to
            user_leave_to = getattr(user, "leave_date_to", False)
            if user_leave_to and user_leave_to >= today:
                on_leave = True
                leave_desc = _("On Leave until %s") % user_leave_to.strftime("%Y-%m-%d")

            # 2. Check linked employee
            if emp:
                if getattr(emp, "is_absent", False):
                    on_leave = True
                emp_leave_to = getattr(emp, "leave_date_to", False)
                if emp_leave_to and emp_leave_to >= today:
                    on_leave = True
                    leave_desc = _("On Leave until %s") % emp_leave_to.strftime("%Y-%m-%d")

                # 3. Check hr.leave directly
                if leave_model and getattr(emp, "id", None) and not on_leave:
                    active_leave = leave_model.sudo().search([
                        ("employee_id", "=", emp.id),
                        ("date_from", "<=", now),
                        ("date_to", ">=", now),
                        ("state", "in", ("validate", "validate1")),
                    ], limit=1)
                    if active_leave:
                        on_leave = True
                        h_name = active_leave.holiday_status_id.name if active_leave.holiday_status_id else _("Leave")
                        to_date = active_leave.date_to.strftime("%Y-%m-%d") if active_leave.date_to else ""
                        leave_desc = f"{h_name} (until {to_date})" if to_date else h_name

            user.is_on_leave = on_leave
            user.leave_status_text = leave_desc or (_("On Leave") if on_leave else "")

    def _search_is_on_leave(self, operator, value):
        now = fields.Datetime.now()
        today = fields.Date.today()
        leave_model = self.env.get("hr.leave")
        user_ids = set()
        if leave_model:
            active_leaves = leave_model.sudo().search([
                ("date_from", "<=", now),
                ("date_to", ">=", now),
                ("state", "in", ("validate", "validate1")),
            ])
            for l in active_leaves:
                l_emp = l.sudo().employee_id
                if l_emp and l_emp.user_id:
                    user_ids.add(l_emp.user_id.id)

        users_with_leave = self.sudo().search([("leave_date_to", ">=", today)])
        user_ids |= set(users_with_leave.ids)
        user_ids.discard(False)

        is_true = (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value)
        if is_true:
            return [("id", "in", list(user_ids))]
        else:
            return [("id", "not in", list(user_ids))]

    @api.depends("is_on_leave", "leave_status_text")
    def _compute_display_name(self):
        super()._compute_display_name()
        # Only customize display_name in Helpdesk contexts so other modules (HR, Accounting, Project, etc.) are never affected
        ctx = self.env.context
        is_helpdesk_ctx = (
            ctx.get("is_helpdesk")
            or ctx.get("helpdesk_ticket_id")
            or ctx.get("default_helpdesk_team_id")
            or ctx.get("params", {}).get("model") in ("helpdesk.ticket", "helpdesk.ticket.team", "helpdesk.service")
        )
        if not is_helpdesk_ctx:
            return

        for user in self:
            if user.is_on_leave:
                desc = user.leave_status_text or _("On Leave")
                user.display_name = f"{user.display_name} ({desc})"

    @api.depends("agent_manual_duty_status", "is_on_leave")
    def _compute_agent_duty_status(self):
        self._compute_is_on_leave()
        for user in self:
            # 1. Leave check takes top precedence
            if user.is_on_leave:
                user.agent_duty_status = "offline"
                user.agent_duty_status_reason = _("On Time Off: %s") % (user.leave_status_text or _("Leave"))
                continue

            emp = getattr(user.sudo(), "employee_id", None) or (user.sudo().employee_ids[0] if getattr(user.sudo(), "employee_ids", None) else None)
            if not emp:
                user.agent_duty_status = user.agent_manual_duty_status or "available"
                user.agent_duty_status_reason = _("No employee record linked")
                continue

            # 2. Check Attendance (Check-in / Check-out)
            att_state = getattr(emp, "attendance_state", "checked_out")
            if att_state == "checked_out":
                user.agent_duty_status = "offline"
                user.agent_duty_status_reason = _("Offline (Checked Out in Attendance)")
                continue

            if att_state == "checked_in":
                last_att = getattr(emp, "last_attendance_id", None)
                check_in = getattr(last_att, "check_in", None) if last_att else None
                check_in_str = check_in.strftime("%H:%M") if check_in else ""
                manual = user.agent_manual_duty_status or "available"
                if manual == "busy":
                    user.agent_duty_status = "busy"
                    user.agent_duty_status_reason = _("Busy / Handling Call (Checked In)")
                elif manual == "on_break":
                    user.agent_duty_status = "on_break"
                    user.agent_duty_status_reason = _("On Break (Checked In)")
                elif manual == "offline":
                    user.agent_duty_status = "offline"
                    user.agent_duty_status_reason = _("Manually Offline (Checked In)")
                else:
                    user.agent_duty_status = "available"
                    user.agent_duty_status_reason = _("Available / On Duty%s") % (
                        f" (Checked In at {check_in_str})" if check_in_str else ""
                    )
                continue

            # Fallback if employee has no attendance tracking configured
            user.agent_duty_status = user.agent_manual_duty_status or "available"
            user.agent_duty_status_reason = _("Active Duty")

    def _inverse_agent_duty_status(self):
        for user in self:
            user.agent_manual_duty_status = user.agent_duty_status

    def _search_agent_duty_status(self, operator, value):
        users = self.search([("share", "=", False)])
        if operator in ("=", "=="):
            matched = users.filtered(lambda u: u.agent_duty_status == value)
        elif operator in ("!=", "<>"):
            matched = users.filtered(lambda u: u.agent_duty_status != value)
        elif operator == "in":
            matched = users.filtered(lambda u: u.agent_duty_status in value)
        elif operator == "not in":
            matched = users.filtered(lambda u: u.agent_duty_status not in value)
        else:
            matched = users.filtered(lambda u: u.agent_duty_status == value)
        return [("id", "in", matched.ids)]

    def _is_contact_center_frontline_only(self):
        """Returns True if user is exclusively Contact Center Frontline (no higher management or branch roles)."""
        self.ensure_one()
        is_cc_fl = (
            self.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")
            or getattr(self, "helpdesk_role", "") in ("contact_center_front_line", "contact_center")
        )
        if not is_cc_fl:
            return False
        has_higher = (
            self.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")
            or self.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")
            or self.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")
            or self.has_group("bunna_helpdesk.group_helpdesk_back_line")
            or self.has_group("bunna_helpdesk.group_helpdesk_team_leader")
            or self.has_group("bunna_helpdesk.group_helpdesk_director")
            or self.has_group("bunna_helpdesk.group_helpdesk_manager")
            or self.has_group("bunna_helpdesk.group_helpdesk_executive")
            or self._is_admin()
            or getattr(self, "helpdesk_role", "") in (
                "contact_center_back_line", "contact_center_team_leader", "contact_center_director",
                "back_line", "team_leader", "directorate", "director", "admin", "manager"
            )
        )
        is_branch_fl = (
            getattr(self, "helpdesk_role", "") == "front_line"
            and not (self.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line") and getattr(self, "helpdesk_role", "") == "contact_center_front_line")
        )
        return not has_higher and not is_branch_fl

    def _get_helpdesk_operating_unit_ids(self, include_children=True):
        """Returns all Operating Unit IDs assigned to this user and their linked employee,
        including all child operating units down the hierarchy."""
        ous = self.env["operating.unit"]
        for u in self:
            # Contact Center Frontline agents view strictly their own created and assigned tickets,
            # not operating unit tickets.
            if u._is_contact_center_frontline_only():
                continue
            ous |= u.assigned_operating_unit_ids | u.default_operating_unit_id | u.operating_unit_ids
            emp = getattr(u, "employee_id", None) or (u.employee_ids[0] if getattr(u, "employee_ids", None) else None)
            if emp:
                if hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id:
                    ous |= emp.default_operating_unit_id
                if hasattr(emp, "operating_unit_ids") and emp.operating_unit_ids:
                    ous |= emp.operating_unit_ids

        if not include_children or not ous:
            return ous.ids

        all_ous = ous
        current = ous
        while current:
            children = self.env["operating.unit"].sudo().search([
                ("parent_unit", "in", current.ids),
                ("id", "not in", all_ous.ids)
            ])
            if not children:
                break
            all_ous |= children
            current = children

        return all_ous.ids





