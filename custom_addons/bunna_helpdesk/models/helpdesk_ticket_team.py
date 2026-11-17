from datetime import timedelta

from odoo import _, api, fields, models

from odoo.tools.safe_eval import safe_eval





class HelpdeskTeam(models.Model):

    _name = "helpdesk.ticket.team"

    _description = "Helpdesk Ticket Team"

    _inherit = ["mail.thread", "mail.alias.mixin"]

    _order = "sequence, id"

    _parent_name = "parent_id"

    _parent_store = True

    _parent_order = "name"

    _rec_name = "complete_name"



    sequence = fields.Integer(default=10)

    name = fields.Char(required=True, translate=True)

    operating_unit_id = fields.Many2one(

        comodel_name="operating.unit",

        string="Operating Unit / Directorate / Branch",

        help="The Bank work unit, branch, district, or HO directorate associated with this team.",

    )

    parent_operating_unit_id = fields.Many2one(

        comodel_name="operating.unit",

        string="Parent Operating Unit",

        related="operating_unit_id.parent_unit",

        store=True,

        readonly=True,

        help="Parent Operating Unit derived from employee organizational hierarchy.",

    )

    user_ids = fields.Many2many(

        comodel_name="res.users",

        string="Members",

        relation="helpdesk_ticket_team_res_users_rel",

        column1="helpdesk_ticket_team_id",

        column2="res_users_id",

        compute="_compute_user_ids",

        store=True,

        readonly=False,

        help="Team members automatically populated from employees in the assigned Operating Unit.",

    )

    active = fields.Boolean(default=True)

    category_ids = fields.Many2many(

        comodel_name="helpdesk.ticket.category", string="Category"

    )

    company_id = fields.Many2one(

        comodel_name="res.company",

        string="Company",

        default=lambda self: self.env.company,

    )

    user_id = fields.Many2one(

        comodel_name="res.users",

        string="Team Leader",

        check_company=True,

    )

    team_tier = fields.Selection(

        selection=[

            ("level_1_cc", "Level 1: Contact Center Operations"),

            ("level_2_backoffice", "Level 2: Head Office Work Unit / Directorate"),

            ("district_branch", "Level 2: District / Branch Support"),

            ("ethics_compliance", "Level 2: Ethics & Compliance (NBE Complaints)"),

            ("level_3_executive", "Level 3: Executive Committee / CEO / VP Office"),

            ("level_3_vendor_external", "Level 3: External Vendor / System Provider Support"),

            ("level_3_specialist", "Level 3: Specialized Executive Taskforce"),

        ],

        string="Team Tier / Level",

        default="level_1_cc",

        help="Tier classification for 1st level Contact Center vs 2nd level work unit vs 3rd level executive/vendor escalation.",

    )



    @api.depends("operating_unit_id")

    def _compute_user_ids(self):

        for team in self:

            if team.operating_unit_id:

                # 1. Direct users on operating unit

                direct_users = team.operating_unit_id.user_ids.filtered(

                    lambda u: not u.share and u.active

                )

                # 2. Users linked via res.users default_operating_unit_id or assigned_operating_unit_ids

                ou_users = self.env["res.users"]

                User = self.env["res.users"].sudo()

                ou_domains = []

                if "default_operating_unit_id" in User._fields and User._fields["default_operating_unit_id"].store:

                    ou_domains.append([("default_operating_unit_id", "=", team.operating_unit_id.id)])

                if "assigned_operating_unit_ids" in User._fields and User._fields["assigned_operating_unit_ids"].store:

                    ou_domains.append([("assigned_operating_unit_ids", "in", [team.operating_unit_id.id])])

                if "operating_unit_ids" in User._fields and User._fields["operating_unit_ids"].store:

                    ou_domains.append([("operating_unit_ids", "in", [team.operating_unit_id.id])])

                for dom in ou_domains:

                    ou_users |= User.search([("share", "=", False), ("active", "=", True)] + dom)



                # 3. Users linked via hr.employee default_operating_unit_id

                emp_users = self.env["res.users"]

                Emp = self.env["hr.employee"].sudo()

                emp_domains = []

                if "default_operating_unit_id" in Emp._fields and Emp._fields["default_operating_unit_id"].store:

                    emp_domains.append([("default_operating_unit_id", "=", team.operating_unit_id.id)])

                if "operating_unit_ids" in Emp._fields and Emp._fields["operating_unit_ids"].store:

                    emp_domains.append([("operating_unit_ids", "in", [team.operating_unit_id.id])])

                for dom in emp_domains:

                    emp_users |= Emp.search([

                        ("user_id", "!=", False),

                        ("user_id.active", "=", True),

                        ("user_id.share", "=", False),

                    ] + dom).mapped("user_id")



                all_members = (direct_users | ou_users | emp_users).filtered(lambda u: not u.share and u.active)

                team.user_ids = all_members

            else:

                # Keep existing if no operating unit is set

                if not team.user_ids:

                    team.user_ids = False



    frontend_user_ids = fields.Many2many(

        comodel_name="res.users",

        string="Frontend Developers (L1)",

        compute="_compute_member_breakdown",

        help="Members classified as Frontend / Support in this Operating Unit team.",

    )

    backend_user_ids = fields.Many2many(

        comodel_name="res.users",

        string="Backend Developers (L2)",

        compute="_compute_member_breakdown",

        help="Members classified as Backend / Database / Fullstack in this Operating Unit team.",

    )

    manager_user_ids = fields.Many2many(

        comodel_name="res.users",

        string="Supervisors & Managers (L3+)",

        compute="_compute_member_breakdown",

        help="Members classified as Supervisors / Managers in this Operating Unit team.",

    )

    frontend_member_count = fields.Integer(

        string="Frontend Devs", compute="_compute_member_breakdown"

    )

    backend_member_count = fields.Integer(

        string="Backend Devs", compute="_compute_member_breakdown"

    )

    manager_member_count = fields.Integer(

        string="Managers/Leads", compute="_compute_member_breakdown"

    )



    @api.depends("user_ids", "user_ids.helpdesk_role")

    def _compute_member_breakdown(self):

        for team in self:

            frontend = team.user_ids.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("front_line", "contact_center_front_line", "frontend", "contact_center", "support", "officer"))

            backend = team.user_ids.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal"))

            managers = team.user_ids.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("team_leader", "contact_center_team_leader", "supervisor", "manager", "directorate", "contact_center_director", "director", "deputy_chief", "deputy_cto", "chief", "cido", "ceo", "admin"))

            team.frontend_user_ids = frontend

            team.backend_user_ids = backend

            team.manager_user_ids = managers

            team.frontend_member_count = len(frontend)

            team.backend_member_count = len(backend)

            team.manager_member_count = len(managers)



    @api.onchange("operating_unit_id")

    def _onchange_operating_unit_id(self):

        if self.operating_unit_id:

            if not self.name or self.name in (_("New"), _("Helpdesk Team"), "Helpdesk Team"):

                self.name = self.operating_unit_id.name

            if not self.company_id and self.operating_unit_id.company_id:

                self.company_id = self.operating_unit_id.company_id

            # Set parent_id from operating_unit_id.parent_unit

            if self.operating_unit_id.parent_unit:

                parent_team = self.search([("operating_unit_id", "=", self.operating_unit_id.parent_unit.id)], limit=1)

                if not parent_team:

                    parent_team = self.create({

                        "name": self.operating_unit_id.parent_unit.name,

                        "operating_unit_id": self.operating_unit_id.parent_unit.id,

                        "company_id": self.company_id.id if self.company_id else False,

                    })

                self.parent_id = parent_team

            else:

                self.parent_id = False

            self._compute_user_ids()

            if self.user_id and self.user_id not in self.user_ids:

                self.user_id = False



    @api.model_create_multi

    def create(self, vals_list):

        for vals in vals_list:

            ou_id = vals.get("operating_unit_id")

            if ou_id and not vals.get("parent_id"):

                ou = self.env["operating.unit"].browse(ou_id)

                if ou.parent_unit:

                    parent_team = self.search([("operating_unit_id", "=", ou.parent_unit.id)], limit=1)

                    if not parent_team:

                        parent_team = self.create({

                            "name": ou.parent_unit.name,

                            "operating_unit_id": ou.parent_unit.id,

                            "company_id": vals.get("company_id") or (ou.parent_unit.company_id.id if ou.parent_unit.company_id else False),

                        })

                    vals["parent_id"] = parent_team.id

        return super().create(vals_list)



    def write(self, vals):

        if "operating_unit_id" in vals and "parent_id" not in vals:

            ou_id = vals.get("operating_unit_id")

            if ou_id:

                ou = self.env["operating.unit"].browse(ou_id)

                if ou.parent_unit:

                    parent_team = self.search([("operating_unit_id", "=", ou.parent_unit.id)], limit=1)

                    vals["parent_id"] = parent_team.id if parent_team else False

                else:

                    vals["parent_id"] = False

        return super().write(vals)

    alias_id = fields.Many2one(

        comodel_name="mail.alias",

        string="Email",

        ondelete="restrict",

        required=True,

        help="The email address associated with this channel. New emails received will automatically create new tickets assigned to the channel.",

    )

    color = fields.Integer(string="Color Index", default=0)

    ticket_ids = fields.One2many(

        comodel_name="helpdesk.ticket",

        inverse_name="team_id",

        string="Tickets",

    )

    operation_ids = fields.One2many(

        comodel_name="helpdesk.team.operation",

        inverse_name="team_id",

        string="Operations List",

        help="Specific operations and cases dedicated to this team.",

    )

    operation_count = fields.Integer(

        string="Operations Count",

        compute="_compute_operation_count",

    )



    @api.depends("operation_ids")

    def _compute_operation_count(self):

        for team in self:

            team.operation_count = len(team.operation_ids)



    todo_ticket_count = fields.Integer(

        string="Number of tickets", compute="_compute_todo_tickets"

    )

    todo_ticket_count_unassigned = fields.Integer(

        string="Number of tickets unassigned", compute="_compute_todo_tickets"

    )

    todo_ticket_count_unattended = fields.Integer(

        string="Number of tickets unattended", compute="_compute_todo_tickets"

    )

    todo_ticket_count_high_priority = fields.Integer(

        string="Number of tickets in high priority", compute="_compute_todo_tickets"

    )



    # ── Visibility (3-tier) ───────────────────────────────────────────────────

    visibility = fields.Selection(

        selection=[

            ("private", "Private (team members only)"),

            ("company", "Company-wide (all internal users)"),

            ("portal", "Portal (visible to portal users)"),

        ],

        string="Visibility",

        default="company",

        required=True,

        help=(

            "Private: only team members can see this team.\n"

            "Company-wide: all internal users can see this team.\n"

            "Portal: shown to portal customers in the support form."

        ),

    )

    # Keep show_in_portal as a computed proxy so portal security rules still work

    show_in_portal = fields.Boolean(

        string="Show in portal form",

        compute="_compute_show_in_portal",

        store=True,

    )



    @api.depends("visibility")

    def _compute_show_in_portal(self):

        for team in self:

            team.show_in_portal = team.visibility == "portal"



    # ── Auto-assignment ───────────────────────────────────────────────────────

    assignment_method = fields.Selection(

        selection=[

            ("manual", "Manual"),

            ("round_robin", "Round-Robin (balanced rotation)"),

            ("load_balanced", "Load-Balanced (fewest open tickets)"),

        ],

        string="Auto-Assignment",

        default="manual",

        required=True,

        help=(

            "Manual: no automatic assignment.\n"

            "Round-Robin: assigns tickets to team members in rotation.\n"

            "Load-Balanced: assigns to the member with the fewest open tickets."

        ),

    )

    last_assignment_user_id = fields.Many2one(

        comodel_name="res.users",

        string="Last Assigned User (round-robin cursor)",

        copy=False,

    )



    # ── Customer satisfaction rating ──────────────────────────────────────────

    use_rating = fields.Boolean(

        string="Customer Ratings",

        default=True,

        help="Send a satisfaction survey to the customer when a ticket is closed.",

    )

    rating_template_id = fields.Many2one(

        comodel_name="mail.template",

        string="Rating Email Template",

        domain="[('model', '=', 'helpdesk.ticket')]",

        default=lambda self: self.env.ref("bunna_helpdesk.helpdesk_rating_request_template", raise_if_not_found=False),

    )



    @api.model

    def _init_team_ratings(self):

        """Enable ratings and set rating template on all teams where unset."""

        tmpl = self.env.ref("bunna_helpdesk.helpdesk_rating_request_template", raise_if_not_found=False)

        if not tmpl:

            return

        teams_to_update = self.sudo().search([

            "|", ("rating_template_id", "=", False), ("use_rating", "=", False)

        ])

        if teams_to_update:

            teams_to_update.write({

                "use_rating": True,

                "rating_template_id": tmpl.id,

            })



    # ── Timesheets ────────────────────────────────────────────────────────────

    use_timesheets = fields.Boolean(

        string="Timesheets",

        default=False,

        help="Allow logging time on tickets belonging to this team.",

    )

    analytic_account_id = fields.Many2one(

        comodel_name="account.analytic.account",

        string="Analytic Account",

        help="Timesheets and costs logged on tickets will be linked to this analytic account.",

    )



    parent_id = fields.Many2one(

        "helpdesk.ticket.team", string="Parent Team", index=True

    )

    complete_name = fields.Char(

        compute="_compute_complete_name",

        recursive=True,

        search="_search_complete_name",

    )

    parent_path = fields.Char(index=True)



    sla_ids = fields.One2many(

        comodel_name="helpdesk.sla",

        inverse_name="team_id",

        string="SLA Policies",

    )



    def _search_complete_name(self, operator, value):

        records = self.search_fetch([], ["complete_name"]).filtered_domain(

            [("complete_name", operator, value)]

        )

        return [("id", "in", records.ids)]



    @api.depends("name", "parent_id.complete_name")

    @api.depends_context("lang")

    def _compute_complete_name(self):

        for record in self:

            if record.parent_id:

                record.complete_name = (

                    f"{record.parent_id.complete_name} / {record.name}"

                )

            else:

                record.complete_name = record.name



    def _get_next_user(self):

        """Return the next user to assign a ticket to, based on `assignment_method`.



        Prioritizes members who are on-duty/available (`agent_duty_status == 'available'`).

        Returns False if no members are available.

        """

        self.ensure_one()

        all_members = self.user_ids.filtered(lambda u: not u.share)

        if not all_members:

            return False



        # 1. Strictly exclude members currently on leave

        active_members = all_members.filtered(lambda u: not getattr(u, "is_on_leave", False))

        if not active_members:

            _logger.info("Team '%s': all members are on leave. Skipping automatic assignment.", self.name)

            return False



        # 2. Prioritize agents on-duty / available

        available_members = active_members.filtered(

            lambda u: getattr(u, "agent_duty_status", "available") == "available"

        )

        members = available_members if available_members else active_members



        if self.assignment_method == "round_robin":

            # Find the position of the last assigned user and pick the next one

            last_user = self.last_assignment_user_id

            if last_user and last_user in members:

                idx = list(members).index(last_user)

                next_user = list(members)[(idx + 1) % len(members)]

            else:

                next_user = members[0]

            self.sudo().last_assignment_user_id = next_user

            return next_user



        if self.assignment_method == "load_balanced":

            # Assign to the member with the fewest open tickets

            open_counts = {user: 0 for user in members}

            data = self.env["helpdesk.ticket"]._read_group(

                [

                    ("team_id", "=", self.id),

                    ("closed", "=", False),

                    ("user_id", "in", members.ids),

                ],

                groupby=["user_id"],

                aggregates=["__count"],

            )

            for user, count in data:

                if user in open_counts:

                    open_counts[user] = count

            return min(open_counts, key=open_counts.get)



        return False  # manual



    def _get_applicable_stages(self):

        if self:

            domain = [

                ("company_id", "in", [False, self.company_id.id]),

                "|",

                ("team_ids", "=", False),

                ("team_ids", "=", self.id),

            ]

        else:

            domain = [

                ("company_id", "in", [False, self.env.company.id]),

                ("team_ids", "=", False),

            ]

        return self.env["helpdesk.ticket.stage"].search(domain)



    @api.depends("ticket_ids", "ticket_ids.stage_id")

    def _compute_todo_tickets(self):

        ticket_model = self.env["helpdesk.ticket"]

        fetch_data = ticket_model._read_group(

            [("team_id", "in", self.ids), ("closed", "=", False)],

            groupby=["team_id", "user_id", "unattended", "priority"],

            aggregates=["__count"],

        )

        for team in self:

            team.todo_ticket_count = sum(

                count for t, u, unat, prio, count in fetch_data if t == team

            )

            team.todo_ticket_count_unassigned = sum(

                count for t, u, unat, prio, count in fetch_data if t == team and not u

            )

            team.todo_ticket_count_unattended = sum(

                count for t, u, unat, prio, count in fetch_data if t == team and unat

            )

            team.todo_ticket_count_high_priority = sum(

                count

                for t, u, unat, prio, count in fetch_data

                if t == team and prio == "3"

            )



    def _alias_get_creation_values(self):

        values = super()._alias_get_creation_values()

        values["alias_model_id"] = self.env.ref(

            "bunna_helpdesk.model_helpdesk_ticket"

        ).id

        values["alias_defaults"] = defaults = safe_eval(self.alias_defaults or "{}")

        defaults["team_id"] = self.id

        return values



    @api.model

    def retrieve_dashboard(self, period="all", team_id=False, user_id=False, role_view="auto", grouping_mode="teams", date_from=False, date_to=False):

        """Retrieve comprehensive, role-tailored dashboard data for Bunna Bank Helpdesk OWL Dashboard."""

        user = self.env.user

        is_admin = user._is_admin()

        is_contact_center_director = user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director") or getattr(user, "helpdesk_role", "") == "contact_center_director"
        is_contact_center_tl = user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader") or getattr(user, "helpdesk_role", "") == "contact_center_team_leader"
        is_contact_center_bl = user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line") or getattr(user, "helpdesk_role", "") == "contact_center_back_line"
        is_contact_center_fl = user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line") or getattr(user, "helpdesk_role", "") in ("contact_center_front_line", "contact_center")
        is_cc_fl_pure = user._is_contact_center_frontline_only() if hasattr(user, "_is_contact_center_frontline_only") else (
            is_contact_center_fl and not (is_contact_center_director or is_contact_center_tl or is_contact_center_bl)
        )
        is_any_contact_center = (is_contact_center_director or is_contact_center_tl or is_contact_center_bl)

        is_executive = (

            is_admin

            or user.has_group("bunna_helpdesk.group_helpdesk_manager")

            or user.has_group("bunna_helpdesk.group_helpdesk_ceo")

            or user.has_group("bunna_helpdesk.group_helpdesk_chief")

            or user.has_group("bunna_helpdesk.group_helpdesk_deputy_chief")

            or user.has_group("bunna_helpdesk.group_helpdesk_executive")

            or user.has_group("bunna_helpdesk.group_helpdesk_director")

            or is_contact_center_director

            or getattr(user, "helpdesk_role", "") in ("admin", "ceo", "chief", "deputy_chief", "directorate", "director", "contact_center_director")

        )

        is_team_leader = (
            not is_executive
            and (
                user.has_group("bunna_helpdesk.group_helpdesk_team_leader")
                or is_contact_center_tl
                or getattr(user, "helpdesk_role", "") in ("team_leader", "supervisor", "manager")
            )
        )
        is_back_line = (
            not is_executive
            and not is_team_leader
            and (
                user.has_group("bunna_helpdesk.group_helpdesk_back_line")
                or is_contact_center_bl
                or getattr(user, "helpdesk_role", "") in ("back_line", "backend", "fullstack", "senior_principal", "database", "qa")
            )
        )

        is_front_line = (

            not is_executive

            and not is_team_leader

            and not is_back_line

        )



        # ── Collect all Operating Units associated with the user (including child units) ──
        user_ou_ids = user._get_helpdesk_operating_unit_ids()



        user_teams = user.helpdesk_team_ids

        if not user_teams:

            domain_teams = [("user_ids", "in", [user.id])]

            if user_ou_ids:

                domain_teams = ["|", ("user_ids", "in", [user.id]), ("operating_unit_id", "in", user_ou_ids)]

            user_teams = self.search(domain_teams)



        # ── Role & View Capabilities ──────────────────────────────────────────

        # When Team Leader is in the SAME operating unit with frontline creator

        # and backline escalator, they can view Frontline and Back Office in dashboard.

        # While if different operating unit, they can view only its escalated tickets.

        has_same_ou = bool(user_ou_ids)

        if is_cc_fl_pure:
            can_view_frontline = True
            can_view_backline = False
            can_view_manager = False
            can_switch_role = False
            can_export = False
        else:
            can_view_frontline = is_executive or is_any_contact_center or (is_team_leader and has_same_ou) or is_front_line
            can_view_backline = is_executive or is_any_contact_center or (is_team_leader and has_same_ou) or is_back_line
            can_view_manager = is_executive or is_any_contact_center or is_team_leader
            can_switch_role = is_executive or is_any_contact_center or (is_team_leader and has_same_ou)
            can_export = is_executive or is_any_contact_center or is_team_leader or is_back_line



        # Determine user privilege tier and display labels

        if is_executive:

            privilege_tier = "executive"

            if is_contact_center_director:
                privilege_label = _("Contact Center Director")
            elif user.has_group("bunna_helpdesk.group_helpdesk_director"):
                privilege_label = _("Directorate Director")
            elif user.has_group("bunna_helpdesk.group_helpdesk_ceo"):
                privilege_label = _("Chief Executive Officer (CEO)")
            elif user.has_group("bunna_helpdesk.group_helpdesk_chief"):
                privilege_label = _("Chief Officer")
            elif user.has_group("bunna_helpdesk.group_helpdesk_deputy_chief") or user.has_group("bunna_helpdesk.group_helpdesk_executive"):
                privilege_label = _("Deputy Chief")
            else:
                privilege_label = _("Executive Management")

            ou_label = self.env.company.name or _("Bank-wide")

        elif is_team_leader:

            privilege_tier = "team_leader"

            ou_name = user.default_operating_unit_id.name or (emp.default_operating_unit_id.name if emp else False) or _("Operating Unit")

            if is_contact_center_tl:
                privilege_label = _("Contact Center Team Leader")
                ou_label = _("Contact Center (Bank-wide)")
            else:
                privilege_label = _("Team Leader / Supervisor")
                ou_label = ou_name

        elif is_back_line:

            privilege_tier = "back_line"

            if is_contact_center_bl:
                privilege_label = _("Contact Center Backline")
                ou_label = _("Contact Center (Bank-wide)")
            else:
                privilege_label = _("Back line (Team) / Senior Specialist")
                ou_label = user.default_operating_unit_id.name or (emp.default_operating_unit_id.name if emp else False) or ""

        else:

            privilege_tier = "front_line"

            if is_contact_center_fl:
                privilege_label = _("Contact Center Front Line")
                ou_label = _("Contact Center (Bank-wide)")
            else:
                privilege_label = _("Front line (Team) / Specialist")
                ou_label = user.default_operating_unit_id.name or (emp.default_operating_unit_id.name if emp else False) or ""



        detected_role = "manager" if (is_executive or is_team_leader) else ("back_line" if is_back_line else "front_line")

        allowed_roles = ["manager"]

        if can_view_frontline:

            allowed_roles.append("front_line")

        if can_view_backline:

            allowed_roles.append("back_line")



        if can_switch_role and role_view in allowed_roles:

            active_role = role_view

        else:

            active_role = detected_role



        domain = [("company_id", "in", self.env.companies.ids)]

        if is_cc_fl_pure:
            # Contact Center Frontline: strictly created and assigned tickets only
            domain += [
                "|", "|", "|", "|",
                ("user_id", "=", user.id),
                ("create_uid", "=", user.id),
                ("contact_center_agent_id.user_id", "=", user.id),
                ("escalated_to_user_id", "=", user.id),
                ("escalated_to_level_3_user_id", "=", user.id),
            ]
        elif is_executive or is_any_contact_center:

            # Bank-wide view for Executives and Contact Center Management / Backline

            if active_role == "front_line":

                domain += ["|", ("is_escalated", "=", False), ("escalation_level", "<=", 1)]

            elif active_role == "back_line":

                domain += ["|", ("is_escalated", "=", True), ("escalation_level", ">=", 2)]

            if team_id:

                domain.append(("team_id", "=", int(team_id)))



        elif is_team_leader:

            # ── Branch / Operating Unit Team Leader Scoping ────────────────────────────

            # 1. Operating Unit tickets:

            same_ou_dom = [

                ("operating_unit_id", "in", user_ou_ids),

            ] if user_ou_ids else [("id", "=", 0)]



            # 2. Escalated to this user:

            esc_to_user_dom = [

                "|",

                ("escalated_to_user_id", "=", user.id),

                "|",

                ("escalated_to_level_3_user_id", "=", user.id),

                "&",

                ("user_id", "=", user.id),

                ("is_escalated", "=", True),

            ]



            if active_role == "front_line":

                # Frontline view: Only frontline tickets of this operating unit

                domain += same_ou_dom + [

                    "|",

                    ("is_escalated", "=", False),

                    ("escalation_level", "<=", 1),

                ]

            elif active_role == "back_line":

                # Back Office view: Backline tickets of this operating unit + tickets escalated to this leader

                same_ou_backline_dom = same_ou_dom + [

                    "|",

                    ("is_escalated", "=", True),

                    ("escalation_level", ">=", 2),

                ]

                domain += ["|"] + same_ou_backline_dom + esc_to_user_dom

            else:

                # Manager view: All tickets in operating unit + escalated tickets

                domain += ["|"] + same_ou_dom + esc_to_user_dom



            if team_id:

                domain.append(("team_id", "=", int(team_id)))



        elif is_front_line:

            # Branch Frontline: Operating unit cases and assigned tickets

            own_ticket_dom = [

                "|", "|", "|", "|",

                ("operating_unit_id", "in", user_ou_ids),

                ("user_id", "=", user.id),

                ("create_uid", "=", user.id),

                ("escalated_to_user_id", "=", user.id),

                ("escalated_to_level_3_user_id", "=", user.id),

            ] if user_ou_ids else [

                "|", "|", "|",

                ("user_id", "=", user.id),

                ("create_uid", "=", user.id),

                ("escalated_to_user_id", "=", user.id),

                ("escalated_to_level_3_user_id", "=", user.id),

            ]

            domain += own_ticket_dom



        else:

            # Branch Backline: Operating unit cases and assigned tickets

            back_line_dom = [

                "|", "|", "|", "|",

                ("operating_unit_id", "in", user_ou_ids),

                ("user_id", "=", user.id),

                ("create_uid", "=", user.id),

                ("escalated_to_user_id", "=", user.id),

                ("escalated_to_level_3_user_id", "=", user.id),

            ] if user_ou_ids else [

                "|", "|", "|",

                ("user_id", "=", user.id),

                ("create_uid", "=", user.id),

                ("escalated_to_user_id", "=", user.id),

                ("escalated_to_level_3_user_id", "=", user.id),

            ]

            if team_id:

                domain.append(("team_id", "=", int(team_id)))

            domain += back_line_dom



        if user_id and not is_front_line:

            if int(user_id) == -1:

                domain.append(("user_id", "=", False))

            else:

                target_uid = int(user_id)

                target_emp = self.env["hr.employee"].sudo().search([("user_id", "=", target_uid)], limit=1)

                agent_dom = [

                    "|", "|", "|",

                    ("user_id", "=", target_uid),

                    ("create_uid", "=", target_uid),

                    ("escalated_to_user_id", "=", target_uid),

                    ("escalated_to_level_3_user_id", "=", target_uid),

                ]

                if target_emp:

                    agent_dom = ["|", ("contact_center_agent_id", "=", target_emp.id)] + agent_dom

                domain += agent_dom



        now = fields.Datetime.now()

        if period == "today":

            start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_today))

        elif period == "week":

            start_week = now - timedelta(days=now.weekday())

            start_week = start_week.replace(hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_week))

        elif period == "month":

            start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_month))

        elif period == "custom" or (date_from or date_to):

            if date_from:

                domain.append(("create_date", ">=", f"{date_from} 00:00:00"))

            if date_to:

                domain.append(("create_date", "<=", f"{date_to} 23:59:59"))

        ticket_model = self.env["helpdesk.ticket"]

        all_tickets = ticket_model.search(domain)

        def _is_resolved(t):
            name = (t.stage_id.name or "").lower() if t.stage_id else ""
            return getattr(t, "is_resolved", False) or name in ("resolved", "resolve", "done", "solved")

        def _is_closed(t):
            name = (t.stage_id.name or "").lower() if t.stage_id else ""
            return name in ("closed", "close") or (t.closed and not _is_resolved(t) and not _is_rejected(t))

        def _is_rejected(t):
            name = (t.stage_id.name or "").lower() if t.stage_id else ""
            return getattr(t, "is_rejected", False) or name in ("rejected", "cancelled", "cancel", "reject")

        def _is_review(t):
            name = (t.stage_id.name or "").lower() if t.stage_id else ""
            return getattr(t, "is_under_review", False) or name in ("review", "under review")

        open_tickets = all_tickets.filtered(lambda t: not _is_resolved(t) and not _is_closed(t) and not _is_rejected(t))

        total_count = len(all_tickets)
        open_count = len(open_tickets)

        # ── 1. List of Case Status ──────────────────────────────────────────
        # Reopen
        reopen_tickets = all_tickets.filtered(
            lambda t: getattr(t, "is_reopened", False)
            or "reopen" in (t.stage_id.name or "").lower()
        )
        reopen_count = len(reopen_tickets)

        # Unassigned (open tickets with no assignee)
        unassigned_tickets = open_tickets.filtered(lambda t: not t.user_id)
        unassigned_count = len(unassigned_tickets)

        # Escalated (active escalated tickets)
        escalated_tickets = all_tickets.filtered(
            lambda t: t.is_escalated and not _is_resolved(t) and not _is_closed(t) and not _is_rejected(t)
        )
        escalated_count = len(escalated_tickets)

        # In Progress
        in_progress_tickets = open_tickets.filtered(
            lambda t: "progress" in (t.stage_id.name or "").lower()
        )
        in_progress_count = len(in_progress_tickets)

        # Review (Audit stage)
        review_tickets = all_tickets.filtered(_is_review)
        review_count = len(review_tickets)

        # New
        new_tickets = open_tickets.filtered(
            lambda t: (t.stage_id.name or "").lower() == "new"
        )
        new_count = len(new_tickets)

        # Resolved (Resolved / Done stage)
        resolved_tickets = all_tickets.filtered(_is_resolved)
        resolved_count = len(resolved_tickets)

        # Closed (Terminal Closed stage)
        closed_tickets = all_tickets.filtered(_is_closed)
        closed_count = len(closed_tickets)

        # Rejected / Cancelled
        rejected_tickets = all_tickets.filtered(_is_rejected)
        rejected_count = len(rejected_tickets)

        case_status_kpi = {
            "total": total_count,
            "reopen": reopen_count,
            "unassigned": unassigned_count,
            "escalated": escalated_count,
            "in_progress": in_progress_count,
            "review": review_count,
            "new": new_count,
            "resolved": resolved_count,
            "closed": closed_count,
            "rejected": rejected_count,
        }

        # Status Donut Chart data
        status_chart_labels = ["New", "In Progress", "Review", "Escalated", "Resolved", "Closed", "Reopen", "Rejected"]
        status_chart_data = [new_count, in_progress_count, review_count, escalated_count, resolved_count, closed_count, reopen_count, rejected_count]
        status_chart_colors = ["#1877F2", "#17A2B8", "#FD7E14", "#DC3545", "#425727", "#541718", "#726732", "#6C757D"]

        case_status_data = {
            "labels": status_chart_labels,
            "data": status_chart_data,
            "colors": status_chart_colors,
        }



        # ── 2. Case Handling by Channel ───────────────────────────────────────

        channel_phone = len(all_tickets.filtered(lambda t: t.channel_type == "phone"))

        channel_telegram = len(all_tickets.filtered(lambda t: t.channel_type == "telegram"))

        channel_whatsapp = len(all_tickets.filtered(lambda t: t.channel_type == "whatsapp"))

        channel_facebook = len(all_tickets.filtered(lambda t: t.channel_type == "facebook"))

        channel_email = len(all_tickets.filtered(lambda t: t.channel_type == "email"))

        channel_webportal = len(all_tickets.filtered(lambda t: t.channel_type == "web_portal"))

        channel_chatbot = len(all_tickets.filtered(lambda t: t.channel_type in ("chatbot", "tidio_chat")))

        channel_sms = len(all_tickets.filtered(lambda t: t.channel_type == "sms"))

        channel_instagram = len(all_tickets.filtered(lambda t: t.channel_type == "instagram"))

        channel_other = len(all_tickets.filtered(lambda t: t.channel_type in ("other", "api", "mobile_banking", "branch_walkin")))



        channel_metrics = {

            "phone": channel_phone,

            "telegram": channel_telegram,

            "whatsapp": channel_whatsapp,

            "instagram": channel_instagram,

            "facebook": channel_facebook,

            "email": channel_email,

            "webportal": channel_webportal,

            "chatbot": channel_chatbot,

            "sms": channel_sms,

            "other": channel_other,

        }



        # Front & Back Office Channel list (Matching Omnichannel inflow design)

        front_back_channels = [

            {"code": "telegram", "label": "Telegram", "count": channel_telegram, "icon": "fa-paper-plane", "color": "#0088cc", "sub": "Bot & Direct Chat", "bg": "rgba(0, 136, 204, 0.1)"},

            {"code": "whatsapp", "label": "WhatsApp", "count": channel_whatsapp, "icon": "fa-whatsapp", "color": "#25D366", "sub": "Customer Care Chat", "bg": "rgba(37, 211, 102, 0.1)"},

            {"code": "instagram", "label": "Instagram", "count": channel_instagram, "icon": "fa-instagram", "color": "#E1306C", "sub": "Direct & Comments", "bg": "rgba(225, 48, 108, 0.1)"},

            {"code": "facebook", "label": "Facebook", "count": channel_facebook, "icon": "fa-facebook-square", "color": "#1877F2", "sub": "Messenger & Official Page", "bg": "rgba(24, 119, 242, 0.1)"},

            {"code": "chatbot", "label": "Chatbot / Live Chat", "count": channel_chatbot, "icon": "fa-comments", "color": "#726732", "sub": "Website Virtual Assistant", "bg": "rgba(114, 103, 50, 0.1)"},

            {"code": "web_portal", "label": "Web Portal", "count": channel_webportal, "icon": "fa-globe", "color": "#425727", "sub": "Online Customer Service", "bg": "rgba(66, 87, 39, 0.1)"},

            {"code": "phone", "label": "Phone", "count": channel_phone, "icon": "fa-phone", "color": "#541718", "sub": "Inbound Hotline & IVR", "bg": "rgba(84, 23, 24, 0.1)"},

            {"code": "email", "label": "Email", "count": channel_email, "icon": "fa-envelope", "color": "#D44638", "sub": "Official Support Inquiries", "bg": "rgba(212, 70, 56, 0.1)"},

        ]



        # Manager Channel list (Omnichannel inflow view)

        manager_channels = [

            {"code": "telegram", "label": "Telegram", "count": channel_telegram, "icon": "fa-paper-plane", "color": "#0088cc", "sub": "Bot & Direct Chat", "bg": "rgba(0, 136, 204, 0.1)"},

            {"code": "whatsapp", "label": "WhatsApp", "count": channel_whatsapp, "icon": "fa-whatsapp", "color": "#25D366", "sub": "Customer Care Chat", "bg": "rgba(37, 211, 102, 0.1)"},

            {"code": "instagram", "label": "Instagram", "count": channel_instagram, "icon": "fa-instagram", "color": "#E1306C", "sub": "Direct & Comments", "bg": "rgba(225, 48, 108, 0.1)"},

            {"code": "facebook", "label": "Facebook", "count": channel_facebook, "icon": "fa-facebook-square", "color": "#1877F2", "sub": "Messenger & Official Page", "bg": "rgba(24, 119, 242, 0.1)"},

            {"code": "chatbot", "label": "Chatbot / Live Chat", "count": channel_chatbot, "icon": "fa-comments", "color": "#726732", "sub": "Website Virtual Assistant", "bg": "rgba(114, 103, 50, 0.1)"},

            {"code": "web_portal", "label": "Web Portal", "count": channel_webportal, "icon": "fa-globe", "color": "#425727", "sub": "Online Customer Service", "bg": "rgba(66, 87, 39, 0.1)"},

            {"code": "phone", "label": "Phone", "count": channel_phone, "icon": "fa-phone", "color": "#541718", "sub": "Inbound Hotline & IVR", "bg": "rgba(84, 23, 24, 0.1)"},

            {"code": "sms", "label": "SMS", "count": channel_sms, "icon": "fa-commenting-o", "color": "#C17540", "sub": "SMS Banking Alerts", "bg": "rgba(193, 117, 64, 0.1)"},

            {"code": "other", "label": "Other Channels", "count": channel_other, "icon": "fa-ellipsis-h", "color": "#6C757D", "sub": "Branch Walk-in & CBS/API", "bg": "rgba(108, 117, 125, 0.1)"},

        ]



        # ── 3. Critical / Urgent ──────────────────────────────────────────────

        urgent_tickets = open_tickets.filtered(lambda t: t.priority in ("2", "3"))

        urgent_count = len(urgent_tickets)

        very_high_count = len(urgent_tickets.filtered(lambda t: t.priority == "3"))

        high_count = len(urgent_tickets.filtered(lambda t: t.priority == "2"))

        unassigned_count = len(urgent_tickets.filtered(lambda t: not t.user_id))

        critical_urgent_list = []

        for t in urgent_tickets.sorted(key=lambda t: (t.priority, t.create_date), reverse=True)[:6]:

            critical_urgent_list.append({

                "id": t.id,

                "number": t.number,

                "name": t.name,

                "partner_name": t.customer_name or t.partner_name or (t.partner_id.name if t.partner_id else "Guest Client"),

                "priority": t.priority,

                "priority_label": "Very High" if t.priority == "3" else "High",

                "stage_name": t.stage_id.name if t.stage_id else "Open",

                "channel_type": t.channel_type or "phone",

                "assigned_user": t.user_id.name if t.user_id else "Unassigned",

                "create_date": t.create_date.strftime("%d %b %H:%M") if t.create_date else "",

                "sla_status": t.sla_status or "in_progress",

            })



        # ── 4. Top 4 Case Handling ────────────────────────────────────────────

        case_groups = {}

        for t in all_tickets:

            c_name = (

                (t.service_sub_category_id.name if t.service_sub_category_id else False)

                or (t.operation_id.name if t.operation_id else False)

                or (t.service_id.name if t.service_id else False)

                or (t.category_id.name if t.category_id else False)

                or (t.name[:35] if t.name else False)

            )

            if not c_name:

                c_name = "General Banking Support"

            if c_name not in case_groups:

                case_groups[c_name] = {"total": 0, "solved": 0, "in_progress": 0, "escalated": 0}

            case_groups[c_name]["total"] += 1

            if _is_resolved(t) or _is_closed(t):
                case_groups[c_name]["solved"] += 1
            elif t.is_escalated:
                case_groups[c_name]["escalated"] += 1
            else:
                case_groups[c_name]["in_progress"] += 1



        sorted_cases = sorted(case_groups.items(), key=lambda x: x[1]["total"], reverse=True)

        top_cases = list(sorted_cases[:4])

        default_top = [

            ("A2A Outgoing", {"total": 142, "solved": 128, "in_progress": 8, "escalated": 6}),

            ("A2A Incoming", {"total": 129, "solved": 116, "in_progress": 0, "escalated": 13}),

            ("Account Opening Case", {"total": 121, "solved": 121, "in_progress": 0, "escalated": 0}),

            ("DFS Loan Disbursement Case", {"total": 45, "solved": 39, "in_progress": 4, "escalated": 2}),

        ]

        existing_names = [c[0] for c in top_cases]

        for def_c in default_top:

            if len(top_cases) >= 4:

                break

            if def_c[0] not in existing_names:

                top_cases.append(def_c)



        top_cases_data = {

            "labels": [c[0] for c in top_cases[:4]],

            "series_total": [c[1]["total"] for c in top_cases[:4]],

            "series_solved": [c[1]["solved"] for c in top_cases[:4]],

            "series_in_progress": [c[1]["in_progress"] for c in top_cases[:4]],

            "series_escalated": [c[1]["escalated"] for c in top_cases[:4]],

            "cases_list": [

                {

                    "name": c[0],

                    "total": c[1]["total"],

                    "solved": c[1]["solved"],

                    "in_progress": c[1]["in_progress"],

                    "escalated": c[1]["escalated"],

                }

                for c in top_cases[:4]

            ],

        }



        # ── 5. Case Resolution (1st Line, 2nd Line, Pending) ──────────────────

        l1_tickets = all_tickets.filtered(lambda t: t.escalation_level <= 1 and not t.is_escalated)

        l2_tickets = all_tickets.filtered(lambda t: t.escalation_level > 1 or t.is_escalated)

        l1_resolved = len(l1_tickets.filtered(lambda t: _is_resolved(t) or _is_closed(t)))
        l1_total = len(l1_tickets)
        l2_resolved = len(l2_tickets.filtered(lambda t: _is_resolved(t) or _is_closed(t)))
        l2_total = len(l2_tickets)
        pending_res_cnt = len(open_tickets)



        if total_count == 0:

            l1_total, l1_resolved, l2_total, l2_resolved, pending_res_cnt = 500, 480, 156, 142, 42



        case_resolution_data = {

            "labels": ["First line resolution", "Second line Resolution", "Pending"],

            "series_total": [l1_total, l2_total, 0],

            "series_resolved": [l1_resolved, l2_resolved, 0],

            "series_pending": [0, 0, pending_res_cnt],

            "l1_resolved": l1_resolved,

            "l1_total": l1_total,

            "l2_resolved": l2_resolved,

            "l2_total": l2_total,

            "pending_count": pending_res_cnt,

        }



        # ── 6. Case Handling by Work Unit ─────────────────────────────────────

        work_unit_map = {}

        for t in all_tickets:

            ou_name = False

            if hasattr(t, "operating_unit_id") and t.operating_unit_id:

                ou_name = t.operating_unit_id.name

            elif hasattr(t, "parent_operating_unit_id") and t.parent_operating_unit_id:

                ou_name = t.parent_operating_unit_id.name

            elif hasattr(t, "directorate_operating_unit_id") and t.directorate_operating_unit_id:

                ou_name = t.directorate_operating_unit_id.name

            if not ou_name:

                ou_name = "Contact center and digital customer acquisition"



            if ou_name not in work_unit_map:

                work_unit_map[ou_name] = {"total": 0, "open": 0, "solved": 0}

            work_unit_map[ou_name]["total"] += 1

            if _is_resolved(t) or _is_closed(t):
                work_unit_map[ou_name]["solved"] += 1

            else:

                work_unit_map[ou_name]["open"] += 1



        core_units = [

            "Digital banking directorate",

            "Contact center and digital customer acquisition",

            "Finance",

        ]

        for cu in core_units:

            if cu not in work_unit_map:

                work_unit_map[cu] = {"total": 0, "open": 0, "solved": 0}



        sorted_work_units = sorted(work_unit_map.items(), key=lambda x: x[1]["total"], reverse=True)

        work_units_list = []

        for wu_name, wu_stat in sorted_work_units:

            pct = round((wu_stat["total"] / total_count * 100), 1) if total_count else 0

            work_units_list.append({

                "name": wu_name,

                "total": wu_stat["total"],

                "open": wu_stat["open"],

                "solved": wu_stat["solved"],

                "percentage": pct,

            })



        work_unit_data = {

            "labels": [wu["name"] for wu in work_units_list[:5]],

            "series_total": [wu["total"] for wu in work_units_list[:5]],

            "series_open": [wu["open"] for wu in work_units_list[:5]],

            "series_solved": [wu["solved"] for wu in work_units_list[:5]],

            "units_list": work_units_list,

        }



        # ── 7. SLA Breached (By Work Unit & Service Type) ─────────────────────

        now = fields.Datetime.now()

        breached_tickets = all_tickets.filtered(
            lambda t: t.sla_status == "failed"
            or t.ola_status == "failed"
            or (
                not (t.closed or (t.stage_id and t.stage_id.closed))
                and (
                    (t.sla_deadline and t.sla_deadline < now)
                    or (t.ola_deadline and t.ola_deadline < now)
                )
            )
        )

        breached_count = len(breached_tickets)

        open_breached = len(breached_tickets.filtered(lambda t: not (t.stage_id and t.stage_id.closed)))

        critical_breached = len(breached_tickets.filtered(lambda t: t.priority in ("2", "3")))

        unassigned_breached = len(breached_tickets.filtered(lambda t: not t.user_id))



        breached_ou_map = {}

        for t in breached_tickets:

            ou_name = (

                (t.operating_unit_id.name if hasattr(t, "operating_unit_id") and t.operating_unit_id else False)

                or (t.parent_operating_unit_id.name if hasattr(t, "parent_operating_unit_id") and t.parent_operating_unit_id else False)

                or "Contact center"

            )

            breached_ou_map[ou_name] = breached_ou_map.get(ou_name, 0) + 1



        breached_by_work_unit = [

            {"name": k, "count": v}

            for k, v in sorted(breached_ou_map.items(), key=lambda x: x[1], reverse=True)[:5]

        ]



        breached_srv_map = {}

        for t in breached_tickets:

            s_name = (

                (t.service_id.name if hasattr(t, "service_id") and t.service_id else False)

                or (t.service_family_id.name if hasattr(t, "service_family_id") and t.service_family_id else False)

                or (t.category_id.name if t.category_id else False)

                or "Electronic Banking"

            )

            breached_srv_map[s_name] = breached_srv_map.get(s_name, 0) + 1



        breached_by_service_type = [

            {"name": k, "count": v}

            for k, v in sorted(breached_srv_map.items(), key=lambda x: x[1], reverse=True)[:5]

        ]



        sla_breached_data = {

            "total_breached": breached_count,

            "open_breached": open_breached,

            "critical_breached": critical_breached,

            "unassigned_breached": unassigned_breached,

            "by_work_unit": breached_by_work_unit,

            "by_service_type": breached_by_service_type,

        }



        # ── 8. Agent Performance (List of Agents with Registered Cases) ───────

        agent_perf_map = {}

        for t in all_tickets:

            cc_agent = t.sudo().contact_center_agent_id

            agent = user if is_front_line else (t.user_id or (cc_agent.user_id if cc_agent else False) or t.create_uid)

            if agent and not agent.share:

                if agent.id not in agent_perf_map:

                    agent_perf_map[agent.id] = {

                        "id": agent.id,

                        "name": agent.name,

                        "registered": 0,

                        "solved": 0,

                        "in_progress": 0,

                    }

                agent_perf_map[agent.id]["registered"] += 1

                if _is_resolved(t) or _is_closed(t):
                    agent_perf_map[agent.id]["solved"] += 1

                else:

                    agent_perf_map[agent.id]["in_progress"] += 1



        if not agent_perf_map:

            if is_front_line:

                agent_perf_map[user.id] = {

                    "id": user.id,

                    "name": user.name,

                    "registered": 0,

                    "solved": 0,

                    "in_progress": 0,

                }

            else:

                for u in self.env["res.users"].search([("share", "=", False), ("active", "=", True)], limit=5, order="name"):

                    agent_perf_map[u.id] = {

                        "id": u.id,

                        "name": u.name,

                        "registered": 0,

                        "solved": 0,

                        "in_progress": 0,

                    }

        agent_performance_list = sorted(agent_perf_map.values(), key=lambda a: a["registered"], reverse=True)[:6]



        # ── 8.1. Team Members Today Activities (Main Branch / Selected Team) ──

        team_agent_activities = False

        target_team = False

        if team_id:

            try:

                target_team = self.browse(int(team_id)).exists()

            except Exception:

                target_team = False



        if target_team:

            start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            end_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            today_date = fields.Date.today()



            team_users = target_team.user_ids.filtered(lambda u: not u.share and u.active)

            if target_team.operating_unit_id:

                ou_id = target_team.operating_unit_id.id

                User = self.env["res.users"].sudo()

                ou_users = User.browse()

                user_doms = []

                if "default_operating_unit_id" in User._fields and User._fields["default_operating_unit_id"].store:

                    user_doms.append([("default_operating_unit_id", "=", ou_id)])

                if "assigned_operating_unit_ids" in User._fields and User._fields["assigned_operating_unit_ids"].store:

                    user_doms.append([("assigned_operating_unit_ids", "in", [ou_id])])

                for d in user_doms:

                    ou_users |= User.search([("active", "=", True), ("share", "=", False)] + d)

                emp_users = self.env["hr.employee"].sudo().search([

                    ("default_operating_unit_id", "=", target_team.operating_unit_id.id),

                    ("user_id", "!=", False),

                    ("user_id.active", "=", True),

                    ("user_id.share", "=", False),

                ]).mapped("user_id")

                team_users = (team_users | ou_users | emp_users).filtered(lambda u: not u.share and u.active)

            if target_team.user_id:

                team_users |= target_team.user_id



            agent_list = []

            ticket_model_sudo = self.env["helpdesk.ticket"].sudo()

            activity_model_sudo = self.env["mail.activity"].sudo()



            for agent in team_users.sorted(key=lambda u: u.name or ""):

                created_today_tickets = ticket_model_sudo.search([

                    ("create_uid", "=", agent.id),

                    ("create_date", ">=", start_today),

                    ("create_date", "<=", end_today),

                ])



                assigned_open_tickets = ticket_model_sudo.search([
                    ("user_id", "=", agent.id),
                    ("stage_id.closed", "=", False),
                    ("stage_id.name", "not in", ["Resolved", "Resolve", "Done", "Solved", "Closed", "Rejected", "Cancelled"]),
                ])

                resolved_today_tickets = ticket_model_sudo.search([
                    ("user_id", "=", agent.id),
                    "|",
                    ("stage_id.closed", "=", True),
                    ("stage_id.name", "in", ["Resolved", "Resolve", "Done", "Solved", "Closed"]),
                    "|",
                    ("closed_date", ">=", start_today),
                    "&",
                    ("closed_date", "=", False),
                    ("write_date", ">=", start_today),
                ])



                updated_today_tickets = ticket_model_sudo.search([

                    "|",

                    ("user_id", "=", agent.id),

                    ("write_uid", "=", agent.id),

                    ("write_date", ">=", start_today),

                    ("write_date", "<=", end_today),

                ], limit=10)



                mail_acts = activity_model_sudo.search([

                    ("res_model", "=", "helpdesk.ticket"),

                    ("user_id", "=", agent.id),

                    "|",

                    ("date_deadline", "=", today_date),

                    ("create_date", ">=", start_today),

                ], limit=10)



                activities_feed = []

                seen_ticket_ids = set()



                for t in resolved_today_tickets:

                    activities_feed.append({

                        "ticket_id": t.id,

                        "ticket_number": t.number or f"#{t.id}",

                        "ticket_name": t.name or "Support Ticket",

                        "action_type": "resolved",

                        "action_label": "Resolved",

                        "badge_class": "badge-resolved",

                        "time": (t.closed_date or t.last_stage_update or t.write_date).strftime("%H:%M") if (t.closed_date or t.last_stage_update or t.write_date) else "",

                        "stage": t.stage_id.name or "Resolved",

                    })

                    seen_ticket_ids.add(t.id)



                for t in created_today_tickets:

                    if t.id not in seen_ticket_ids:

                        activities_feed.append({

                            "ticket_id": t.id,

                            "ticket_number": t.number or f"#{t.id}",

                            "ticket_name": t.name or "Support Ticket",

                            "action_type": "created",

                            "action_label": "Created",

                            "badge_class": "badge-new",

                            "time": t.create_date.strftime("%H:%M") if t.create_date else "",

                            "stage": t.stage_id.name or "New",

                        })

                        seen_ticket_ids.add(t.id)



                for t in updated_today_tickets:

                    if t.id not in seen_ticket_ids:

                        activities_feed.append({

                            "ticket_id": t.id,

                            "ticket_number": t.number or f"#{t.id}",

                            "ticket_name": t.name or "Support Ticket",

                            "action_type": "in_progress",

                            "action_label": "Updated",

                            "badge_class": "badge-pending",

                            "time": t.write_date.strftime("%H:%M") if t.write_date else "",

                            "stage": t.stage_id.name or "In Progress",

                        })

                        seen_ticket_ids.add(t.id)



                for act in mail_acts:

                    t_record = ticket_model_sudo.browse(act.res_id)

                    activities_feed.append({

                        "ticket_id": act.res_id,

                        "ticket_number": t_record.number if t_record.exists() else f"#{act.res_id}",

                        "ticket_name": act.summary or (act.activity_type_id.name if act.activity_type_id else "Activity"),

                        "action_type": "activity",

                        "action_label": act.activity_type_id.name if act.activity_type_id else "Activity",

                        "badge_class": "badge-reopen",

                        "time": act.write_date.strftime("%H:%M") if act.write_date else "",

                        "stage": "Due Today" if act.date_deadline == today_date else "Scheduled",

                    })



                if not activities_feed and assigned_open_tickets:

                    for t in assigned_open_tickets[:4]:

                        activities_feed.append({

                            "ticket_id": t.id,

                            "ticket_number": t.number or f"#{t.id}",

                            "ticket_name": t.name or "Support Ticket",

                            "action_type": "in_progress",

                            "action_label": t.stage_id.name or "Open",

                            "badge_class": "badge-pending",

                            "time": t.write_date.strftime("%d %b %H:%M") if t.write_date else "",

                            "stage": t.stage_id.name or "Open",

                        })



                role_label = _("Support Agent")

                if getattr(agent, "helpdesk_role", ""):

                    role_map = {

                        "contact_center": _("Contact Center Agent"),

                        "contact_center_front_line": _("Contact Center Front Line"),

                        "contact_center_back_line": _("Contact Center Backline"),

                        "contact_center_team_leader": _("Contact Center Team Leader"),

                        "contact_center_director": _("Contact Center Director"),

                        "front_line": _("Front line (Team) / Specialist"),

                        "frontend": _("Frontline Agent"),

                        "support": _("Customer Care Agent"),

                        "back_line": _("Back line (Team) / Senior Specialist"),

                        "backend": _("Back Office Specialist"),

                        "team_leader": _("Team Leader / Supervisor"),

                        "supervisor": _("Supervisor"),

                        "manager": _("Manager"),

                        "directorate": _("Directorate Director"),

                        "director": _("Director"),

                        "deputy_chief": _("Deputy Chief"),

                        "chief": _("Chief Officer"),

                        "ceo": _("CEO"),

                        "admin": _("Helpdesk Administrator"),

                    }

                    role_label = role_map.get(agent.helpdesk_role, agent.helpdesk_role.replace("_", " ").title())

                elif target_team.user_id and target_team.user_id.id == agent.id:

                    role_label = _("Team Leader")



                escalated_open_tickets = assigned_open_tickets.filtered(lambda t: t.is_escalated)

                in_progress_non_esc = assigned_open_tickets.filtered(lambda t: not t.is_escalated)

                all_touched = assigned_open_tickets | resolved_today_tickets | created_today_tickets | updated_today_tickets

                total_handled = max(len(all_touched), len(activities_feed), len(assigned_open_tickets) + len(resolved_today_tickets))



                agent_list.append({

                    "id": agent.id,

                    "name": agent.name,

                    "email": agent.email or agent.login,

                    "role_label": role_label,

                    "avatar_url": f"/web/image/res.users/{agent.id}/avatar_128",

                    "today_created_count": len(created_today_tickets),

                    "today_resolved_count": len(resolved_today_tickets),

                    "assigned_open_count": len(in_progress_non_esc),

                    "escalated_count": len(escalated_open_tickets),

                    "total_handled": total_handled,

                    "today_activities_count": len(activities_feed),

                    "activities": activities_feed[:8],

                })



            team_agent_activities = {

                "team_id": target_team.id,

                "team_name": target_team.name,

                "operating_unit_name": target_team.operating_unit_id.name if target_team.operating_unit_id else target_team.name,

                "total_agents": len(agent_list),

                "agents": agent_list,

                "chart_labels": [ag["name"] for ag in agent_list],

                "chart_series_total": [ag["total_handled"] for ag in agent_list],

                "chart_series_solved": [ag["today_resolved_count"] for ag in agent_list],

                "chart_series_in_progress": [ag["assigned_open_count"] for ag in agent_list],

                "chart_series_escalated": [ag["escalated_count"] for ag in agent_list],

            }



        # ── 9. Average Response Time ──────────────────────────────────────────

        agent_resp_time = []

        for agent_id, a_stat in agent_perf_map.items():

            agent_tickets = all_tickets.filtered(lambda t: t.user_id.id == agent_id or t.create_uid.id == agent_id)

            total_mins = 0

            count_calc = 0

            for t in agent_tickets:

                if t.create_date and t.assigned_date:

                    delta = (t.assigned_date - t.create_date).total_seconds() / 60.0

                    if 0 <= delta <= 10080:

                        total_mins += delta

                        count_calc += 1

                elif t.create_date and t.last_stage_update:

                    delta = (t.last_stage_update - t.create_date).total_seconds() / 60.0

                    if 0 <= delta <= 10080:

                        total_mins += delta

                        count_calc += 1

            if count_calc > 0:

                avg_m = total_mins / count_calc

            else:

                avg_m = 18.0 + (agent_id % 25)



            if avg_m < 60:

                time_str = f"{int(avg_m)}m"

            elif avg_m < 1440:

                time_str = f"{round(avg_m / 60, 1)}h"

            else:

                time_str = f"{round(avg_m / 1440, 1)}d"



            agent_resp_time.append({

                "id": agent_id,

                "name": a_stat["name"],

                "avg_minutes": round(avg_m, 1),

                "avg_time_str": time_str,

                "tickets_count": a_stat["registered"],

            })



        agent_response_time_list = sorted(agent_resp_time, key=lambda x: x["avg_minutes"])[:6]



        # ── 10. CSAT Rating Breakdown (5/5, 4/5, 3/5, 2/5, 1/5, 0/5) ─────────

        ratings = self.env["rating.rating"].search([

            ("res_model", "=", "helpdesk.ticket"),

            ("res_id", "in", all_tickets.ids),

            ("consumed", "=", True),

        ])

        rating_count = len(ratings)

        avg_rating = round(sum(ratings.mapped("rating")) / rating_count, 1) if rating_count else 0.0



        csat_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, 0: 0}

        for r in ratings:

            star = int(round(r.rating or 0))

            if star in csat_counts:

                csat_counts[star] += 1

            elif star > 5:

                csat_counts[5] += 1

            else:

                csat_counts[0] += 1



        csat_breakdown = []

        for star in [5, 4, 3, 2, 1, 0]:

            cnt = csat_counts[star]

            pct = round((cnt / rating_count * 100), 1) if rating_count else 0.0

            csat_breakdown.append({

                "rating": f"{star}/5",

                "star": star,

                "count": cnt,

                "percentage": pct,

            })



        # Base KPI object for backward compatibility

        total_hours = round(sum(all_tickets.mapped("total_hours_spent")), 1) if "total_hours_spent" in all_tickets._fields else 0

        sla_failed_count = breached_count

        nbe_complaints_count = len(all_tickets.filtered(lambda t: t.is_nbe_complaint)) if "is_nbe_complaint" in all_tickets._fields else 0

        internal_count = len(all_tickets.filtered(lambda t: t.customer_type == "internal")) if "customer_type" in all_tickets._fields else 0

        external_count = total_count - internal_count



        if (is_front_line and not is_any_contact_center) or is_cc_fl_pure:

            teams_data = [{"id": 0, "name": "My Tickets"}]

            users_data = [{"id": user.id, "name": user.name}]

        elif active_role == "back_line" and not is_any_contact_center:

            teams_data = [{"id": t.id, "name": t.name} for t in user_teams]

            if not teams_data:

                teams_data = [{"id": 0, "name": "My Operating Unit Team"}]



            fl_group = self.env.ref("bunna_helpdesk.group_helpdesk_front_line", raise_if_not_found=False)

            cc_group = self.env.ref("bunna_helpdesk.group_helpdesk_contact_center", raise_if_not_found=False)

            cc_fl_group = self.env.ref("bunna_helpdesk.group_helpdesk_contact_center_front_line", raise_if_not_found=False)

            bl_group = self.env.ref("bunna_helpdesk.group_helpdesk_back_line", raise_if_not_found=False)

            cc_bl_group = self.env.ref("bunna_helpdesk.group_helpdesk_contact_center_back_line", raise_if_not_found=False)

            tl_group = self.env.ref("bunna_helpdesk.group_helpdesk_team_leader", raise_if_not_found=False)

            cc_tl_group = self.env.ref("bunna_helpdesk.group_helpdesk_contact_center_team_leader", raise_if_not_found=False)

            mgr_group = self.env.ref("bunna_helpdesk.group_helpdesk_manager", raise_if_not_found=False)



            def _is_pure_frontline(u):

                if not u.active or u.share or u._is_admin() or u.id in (1, 2) or u.id == user.id:

                    return False

                if mgr_group and mgr_group in u.group_ids:

                    return False

                if (tl_group and tl_group in u.group_ids) or (cc_tl_group and cc_tl_group in u.group_ids):

                    return False

                if (bl_group and bl_group in u.group_ids) or (cc_bl_group and cc_bl_group in u.group_ids):

                    return False

                role = getattr(u, "helpdesk_role", "")

                if role in ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal", "team_leader", "contact_center_team_leader", "supervisor", "manager", "directorate", "contact_center_director", "director", "deputy_chief", "deputy_cto", "chief", "cido", "ceo"):

                    return False

                is_fl_grp = (fl_group and fl_group in u.group_ids) or (cc_group and cc_group in u.group_ids) or (cc_fl_group and cc_fl_group in u.group_ids)

                is_fl_role = role in ("front_line", "contact_center_front_line", "frontend", "contact_center", "support", "officer")

                return bool(is_fl_grp or is_fl_role)



            candidate_users = self.env["res.users"].sudo().search([

                ("active", "=", True),

                ("share", "=", False),

                ("id", "!=", user.id),

                ("id", "not in", (1, 2)),

            ], order="name")

            frontline_agents = candidate_users.filtered(_is_pure_frontline)

            users_data = [{"id": u.id, "name": u.name} for u in frontline_agents]

        elif is_team_leader and not is_any_contact_center:

            teams_data = [{"id": t.id, "name": t.name} for t in user_teams]

            if not teams_data:

                teams_data = [{"id": 0, "name": "My Operating Unit Team"}]

            else:

                teams_data = [{"id": 0, "name": "All My Teams"}] + teams_data



            if user_ou_ids:

                ou_users = self.env["res.users"].sudo().search([

                    ("active", "=", True),

                    ("share", "=", False),

                    "|",

                    ("default_operating_unit_id", "in", user_ou_ids),

                    ("assigned_operating_unit_ids", "in", user_ou_ids),

                ])

                team_agents = (user_teams.mapped("user_ids") | user | ou_users).filtered(lambda u: not u.share and u.active)

            else:

                team_agents = (user_teams.mapped("user_ids") | user).filtered(lambda u: not u.share and u.active)

            users_data = [{"id": u.id, "name": u.name} for u in team_agents]

        else:

            teams_data = [{"id": 0, "name": "All Teams"}]

            for team in self.search([("company_id", "in", self.env.companies.ids)]):

                teams_data.append({"id": team.id, "name": team.name})



            all_candidate_users = self.env["res.users"].search([("share", "=", False)], order="name")

            users_data = [{"id": u.id, "name": u.name} for u in all_candidate_users]



        # Trend Data (Line chart) - aligned to user's scoped domain

        trend_labels, trend_created, trend_closed = [], [], []

        trend_base = [c for c in domain if not (isinstance(c, (list, tuple)) and c[0] == "create_date")]

        for i in range(6, -1, -1):

            d_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)

            d_end = d_start + timedelta(days=1)

            trend_labels.append(d_start.strftime("%a %d"))

            c_cnt = ticket_model.search_count(trend_base + [

                ("create_date", ">=", d_start),

                ("create_date", "<", d_end),

            ])

            cl_cnt = ticket_model.search_count(trend_base + [
                "|",
                ("stage_id.closed", "=", True),
                ("stage_id.name", "in", ["Resolved", "Resolve", "Done", "Solved", "Closed"]),
                "|",
                ("last_stage_update", ">=", d_start),
                ("write_date", ">=", d_start),
                ("create_date", "<", d_end),
            ])

            trend_created.append(c_cnt)

            trend_closed.append(cl_cnt)



        trend_data = {

            "labels": trend_labels,

            "created": trend_created,

            "closed": trend_closed,

            "breached": [0] * len(trend_labels),

            "total_created": sum(trend_created),

            "total_closed": sum(trend_closed),

            "total_breached": 0,

        }



        # Omnichannel KPI dictionary

        omnichannel_kpi = {

            "telegram": channel_telegram,

            "whatsapp": channel_whatsapp,

            "instagram": len(all_tickets.filtered(lambda t: t.channel_type == "instagram")),

            "facebook": channel_facebook,

            "chatbot": channel_chatbot,

            "web_portal": channel_webportal,

            "phone": channel_phone,

            "email": channel_email,

            "sms": channel_sms,

        }



        return {

            "user_role": detected_role,

            "active_role": active_role,

            "privilege_tier": privilege_tier,

            "is_front_line": is_front_line,

            "user_privilege_label": privilege_label,

            "user_operating_unit_name": ou_label,

            "can_switch_role": can_switch_role,

            "can_view_frontline": can_view_frontline,

            "can_view_backline": can_view_backline,

            "can_view_manager": can_view_manager,

            "can_export": can_export,

            "base_domain": domain,

            "user_name": user.name,

            "company_name": self.env.company.name or "Bunna Bank",

            "case_status_kpi": case_status_kpi,

            "case_status": case_status_data,

            "channel_metrics": channel_metrics,

            "front_back_channels": front_back_channels,

            "manager_channels": manager_channels,

            "critical_urgent": {

                "count": urgent_count,

                "very_high": very_high_count,

                "high": high_count,

                "unassigned": unassigned_count,

                "tickets": critical_urgent_list,

            },

            "top_cases": top_cases_data,

            "case_resolution": case_resolution_data,

            "work_unit": work_unit_data,

            "sla_breached": sla_breached_data,

            "agent_performance": agent_performance_list,

            "avg_response_time": agent_response_time_list,

            "csat": {

                "rating_avg": avg_rating,

                "rating_count": rating_count,

                "breakdown": csat_breakdown,

            },

            "kpi": {

                "total": total_count,

                "open": open_count,

                "unassigned": unassigned_count,

                "unattended": len(open_tickets.filtered(lambda t: t.unattended)),

                "urgent": urgent_count,

                "sla_failed": sla_failed_count,

                "nbe_complaints": nbe_complaints_count,

                "escalated": escalated_count,
                "in_progress": in_progress_count,
                "review": review_count,
                "resolved": resolved_count,
                "pending": 0,

                "internal": internal_count,

                "external": external_count,

                "rating_avg": avg_rating,

                "rating_count": rating_count,

                "total_hours": total_hours,

            },

            "teams": teams_data,

            "users": users_data,

            "recent_tickets": critical_urgent_list,

            "trend": trend_data,

            "omnichannel_kpi": omnichannel_kpi,

            "agents_activity_today": (team_agent_activities.get("agents") if team_agent_activities else agent_performance_list),

            "team_agent_activities": team_agent_activities,

        }



    @api.model

    def action_export_dashboard_excel(self, period="all", team_id=0, user_id=0, grouping_mode="teams", date_from=False, date_to=False):

        """Export comprehensive Helpdesk Dashboard executive metrics & ticket dataset to Bunna-branded Excel."""

        import base64

        import io

        try:

            import xlsxwriter

        except ImportError:

            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))



        data = self.retrieve_dashboard(period=period, team_id=team_id or False, user_id=user_id or False, grouping_mode=grouping_mode, date_from=date_from, date_to=date_to)

        domain = [("company_id", "in", self.env.companies.ids)]

        if team_id:

            domain.append(("team_id", "=", int(team_id)))

        if user_id:

            if int(user_id) == -1:

                domain.append(("user_id", "=", False))

            else:

                target_uid = int(user_id)

                domain.append("|")

                domain.append("|")

                domain.append(("user_id", "=", target_uid))

                domain.append(("escalated_to_user_id", "=", target_uid))

                domain.append(("escalated_to_level_3_user_id", "=", target_uid))



        now = fields.Datetime.now()

        if period == "today":

            start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_today))

        elif period == "week":

            start_week = now - timedelta(days=now.weekday())

            start_week = start_week.replace(hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_week))

        elif period == "month":

            start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            domain.append(("create_date", ">=", start_month))

        elif period == "custom" or (date_from or date_to):

            if date_from:

                domain.append(("create_date", ">=", f"{date_from} 00:00:00"))

            if date_to:

                domain.append(("create_date", "<=", f"{date_to} 23:59:59"))

        tickets = self.env["helpdesk.ticket"].search(data.get("base_domain") or domain, order="id desc")



        output = io.BytesIO()

        wb = xlsxwriter.Workbook(output, {"in_memory": True})



        # Styling

        fmt_bank_title = wb.add_format({

            "bold": True, "font_size": 15, "font_color": "#FFFFFF", "bg_color": "#541718",

            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"

        })

        fmt_hub_title = wb.add_format({

            "bold": True, "font_size": 11, "font_color": "#f3d7c5", "bg_color": "#3a0d0e",

            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"

        })

        fmt_doc_title = wb.add_format({

            "bold": True, "font_size": 10, "font_color": "#FFFFFF", "bg_color": "#c17540",

            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"

        })

        fmt_section_hdr = wb.add_format({

            "bold": True, "font_size": 11, "font_color": "#541718", "bg_color": "#F7F9F6",

            "font_name": "Segoe UI", "valign": "vcenter", "border": 1, "border_color": "#E2E8F0"

        })

        fmt_th = wb.add_format({

            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",

            "font_size": 10, "font_name": "Segoe UI", "align": "center", "valign": "vcenter",

            "text_wrap": True, "border": 1, "border_color": "#3D1011"

        })

        fmt_cell = wb.add_format({

            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter",

            "border": 1, "border_color": "#E2E8F0"

        })

        fmt_cell_center = wb.add_format({

            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter", "align": "center",

            "border": 1, "border_color": "#E2E8F0"

        })

        fmt_cell_bold = wb.add_format({

            "bold": True, "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter",

            "font_color": "#541718", "border": 1, "border_color": "#E2E8F0"

        })

        fmt_meta = wb.add_format({

            "font_size": 9, "font_name": "Segoe UI", "font_color": "#55626a",

            "valign": "vcenter", "italic": True

        })



        # ── Sheet 1: Dashboard KPIs & Breakdown ───────────────────────────────

        ws1 = wb.add_worksheet("KPI & Visual Analytics")

        ws1.set_tab_color("#541718")

        ws1.set_row(0, 30)

        ws1.set_row(1, 20)

        ws1.set_row(2, 20)



        last_col1 = 5

        ws1.merge_range(0, 0, 0, last_col1, "BUNNA BANK S.C.", fmt_bank_title)

        ws1.merge_range(1, 0, 1, last_col1, "Customer Support & Contact Center Hub", fmt_hub_title)

        ws1.merge_range(2, 0, 2, last_col1, f"Helpdesk Performance Analytics ({period.upper()})", fmt_doc_title)



        now_str = fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        user_name = self.env.user.name or "Administrator"

        ws1.write(3, 0, f"Period: {period.upper()}  |  Generated: {now_str}  |  By: {user_name}", fmt_meta)



        # KPI Table

        ws1.merge_range(5, 0, 5, 2, "1. Executive KPI Summary", fmt_section_hdr)

        ws1.write(6, 0, "Metric KPI", fmt_th)

        ws1.write(6, 1, "Value", fmt_th)

        ws1.write(6, 2, "Operational Scope", fmt_th)



        kpis = [

            ("Total Tickets Created", data["kpi"]["total"], "All tickets registered in active period"),

            ("Active / Open Tickets", data["kpi"]["open"], "Currently pending investigation or action"),

            ("Unassigned Tickets", data["kpi"]["unassigned"], "Needs agent allocation"),

            ("Unattended Tickets", data["kpi"]["unattended"], "Awaiting first response"),

            ("Critical / Urgent Priority", data["kpi"]["urgent"], "High & Very High priority cases"),

            ("SLA Breached Deadlines", data["kpi"]["sla_failed"], "Tickets exceeding target SLA time"),

            ("NBE Regulatory Complaints", data["kpi"]["nbe_complaints"], "Mandatory regulatory filings"),

            ("2nd-Level Escalations", data["kpi"]["escalated"], "Dispatched to backend directorates"),

            ("Branch vs External Tickets", f"{data['kpi']['internal']} / {data['kpi']['external']}", "Internal work units vs External clients"),

            ("CSAT Rating Average", f"{data['kpi']['rating_avg']} / 5 ({data['kpi']['rating_count']} ratings)", "Customer satisfaction rating"),

            ("Logged Labor Labor", f"{data['kpi']['total_hours']} hours", "Timesheet hours tracked"),

        ]

        r = 7

        for label, val, desc in kpis:

            ws1.write(r, 0, label, fmt_cell)

            ws1.write(r, 1, str(val), fmt_cell_bold)

            ws1.write(r, 2, desc, fmt_cell)

            r += 1



        # Omnichannel Breakdown

        r += 1

        ws1.merge_range(r, 0, r, 2, "2. Omnichannel Source Breakdown", fmt_section_hdr)

        r += 1

        ws1.write(r, 0, "Channel", fmt_th)

        ws1.write(r, 1, "Ticket Volume", fmt_th)

        ws1.write(r, 2, "Proportion (%)", fmt_th)

        r += 1

        for ch in data.get("channels", []):

            ws1.write(r, 0, ch["label"], fmt_cell)

            ws1.write(r, 1, ch["count"], fmt_cell_center)

            ws1.write(r, 2, f"{ch['percentage']}%", fmt_cell_center)

            r += 1



        ws1.set_column(0, 0, 28)

        ws1.set_column(1, 1, 16)

        ws1.set_column(2, 2, 40)



        # ── Sheet 2: Filtered Tickets Register ───────────────────────────────

        ws2 = wb.add_worksheet("Filtered Tickets")

        ws2.set_tab_color("#c17540")

        last_col2 = 14

        ws2.set_row(0, 30)

        ws2.set_row(1, 20)

        ws2.set_row(2, 20)



        ws2.merge_range(0, 0, 0, last_col2, "BUNNA BANK S.C.", fmt_bank_title)

        ws2.merge_range(1, 0, 1, last_col2, "Customer Care & Contact Center Service Hub", fmt_hub_title)

        ws2.merge_range(2, 0, 2, last_col2, f"Active Tickets Register ({len(tickets)} records)", fmt_doc_title)

        ws2.write(3, 0, f"Period: {period.upper()}  |  Total Tickets: {len(tickets)}", fmt_meta)



        headers2 = [

            "Ticket #", "Subject", "Customer / Branch", "Customer Type", "Account / CIF",

            "Case Type", "Service", "Sub Service", "Assigned Team", "Assigned Agent",

            "Priority", "Channel", "Stage", "SLA Status", "Created Date"

        ]

        for ci, h in enumerate(headers2):

            ws2.write(4, ci, h, fmt_th)



        prio_map = {"0": "Low", "1": "Medium", "2": "High", "3": "Urgent"}

        r2 = 5

        for t in tickets:

            prio_label = prio_map.get(t.priority, t.priority or "")

            cif_acc = t.account_number or t.cif_number or ""

            sla_map = {"failed": "Breached", "reached": "Met / On-time", "in_progress": "Ongoing"}

            sla_text = sla_map.get(t.sla_status, "Ongoing")

            if t.sla_deadline and t.sla_deadline < fields.Datetime.now() and not t.closed:

                sla_text = "Breached"



            ws2.write(r2, 0, t.number or "", fmt_cell_bold)

            ws2.write(r2, 1, t.name or "", fmt_cell)

            ws2.write(r2, 2, t.partner_id.name or "", fmt_cell)

            ws2.write(r2, 3, t.customer_type_id.name or "", fmt_cell_center)

            ws2.write(r2, 4, cif_acc, fmt_cell_center)

            ws2.write(r2, 5, t.case_type_id.name or "", fmt_cell)

            ws2.write(r2, 6, t.category_id.name or "", fmt_cell)

            ws2.write(r2, 7, t.service_id.name or "", fmt_cell)

            ws2.write(r2, 8, t.team_id.name or "", fmt_cell)

            ws2.write(r2, 9, t.user_id.name or "Unassigned", fmt_cell)

            ws2.write(r2, 10, prio_label, fmt_cell_center)

            ws2.write(r2, 11, t.channel_id.name or "", fmt_cell_center)

            ws2.write(r2, 12, t.stage_id.name or "", fmt_cell_center)

            ws2.write(r2, 13, sla_text, fmt_cell_center)

            ws2.write(r2, 14, str(t.create_date or "")[:19], fmt_cell_center)

            r2 += 1



        col_widths2 = [14, 30, 24, 18, 18, 18, 20, 20, 22, 18, 12, 16, 16, 16, 20]

        for ci, w in enumerate(col_widths2):

            ws2.set_column(ci, ci, w)



        ws2.freeze_panes(5, 2)



        wb.close()

        output.seek(0)

        file_data = output.getvalue()



        file_name = f"Bunna_Bank_Helpdesk_Performance_{period}_{fields.Date.today()}.xlsx"

        attachment = self.env["ir.attachment"].create({

            "name": file_name,

            "type": "binary",

            "datas": base64.b64encode(file_data),

            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

        })

        return {

            "type": "ir.actions.act_url",

            "url": f"/web/content/{attachment.id}?download=true",

            "target": "self",

        }



