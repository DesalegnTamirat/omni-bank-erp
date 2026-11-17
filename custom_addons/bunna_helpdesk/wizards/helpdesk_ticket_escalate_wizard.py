# -*- coding: utf-8 -*-

from odoo import api, fields, models, _

from odoo.exceptions import ValidationError







TARGET_STAGE_ROLES = {
    # Primary Track
    "contact_center_front_line": ("contact_center_front_line", "contact_center", "support", "admin"),
    "contact_center_back_line": ("contact_center_back_line", "back_line", "admin"),
    "contact_center_team_leader": ("contact_center_team_leader", "team_leader", "supervisor", "admin"),
    "contact_center_director": ("contact_center_director", "directorate", "director", "admin"),
    "contact_center": ("contact_center", "contact_center_front_line", "support", "admin"),
    "front_line": ("front_line", "contact_center_front_line", "frontend", "support", "officer", "admin"),
    "frontend": ("front_line", "contact_center_front_line", "frontend", "support", "officer", "admin"),
    "back_line": ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal", "admin"),
    "backend": ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal", "admin"),
    "peer_backend": ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal", "admin"),
    "team_leader": ("team_leader", "contact_center_team_leader", "supervisor", "manager", "admin"),
    "line_manager": ("team_leader", "contact_center_team_leader", "supervisor", "manager", "admin"),
    "manager": ("team_leader", "contact_center_team_leader", "supervisor", "manager", "admin"),
    "team_leader_to_deputy_chief": ("deputy_chief", "deputy_cto", "admin"),
    "directorate": ("directorate", "contact_center_director", "director", "admin"),
    "director": ("directorate", "contact_center_director", "director", "admin"),
    "deputy_chief": ("deputy_chief", "deputy_cto", "admin"),
    "chief": ("chief", "cido", "admin"),
    "ceo": ("ceo", "admin"),
    # Other Track
    "other_work": None,
    "other_officer": ("front_line", "contact_center_front_line", "frontend", "support", "officer", "admin"),
    "other_senior_principal": ("back_line", "contact_center_back_line", "backend", "fullstack", "database", "qa", "senior_principal", "admin"),
    "other_manager_team_leader": ("team_leader", "contact_center_team_leader", "supervisor", "manager", "admin"),
    "other_directorate": ("directorate", "contact_center_director", "director", "admin"),
    "other_deputy_chief_chief": ("deputy_chief", "deputy_cto", "chief", "cido", "admin"),
    "other_ceo": ("ceo", "admin"),
}



class HelpdeskTicketEscalateWizard(models.TransientModel):

    TYPE_ALIASES = {

        "peer_backend": "back_line",

        "backend": "back_line",

        "frontend": "front_line",

        "line_manager": "team_leader",

        "manager": "team_leader",

        "director": "directorate",

        "deputy_cto": "deputy_chief",

        "cido": "chief",

    }



    @api.model_create_multi

    def create(self, vals_list):

        for vals in vals_list:

            if "escalation_type" in vals:

                raw_type = vals["escalation_type"]

                mapped_primary = self.TYPE_ALIASES.get(raw_type, raw_type)

                journey = vals.get("escalation_journey", "primary_journey")

                if journey == "primary_journey" and "escalation_type_primary" not in vals:

                    if mapped_primary in dict(self.PRIMARY_ESCALATION_SELECTION):

                        vals["escalation_type_primary"] = mapped_primary

                elif journey == "other_work_journey" and "escalation_type_other" not in vals:

                    if raw_type in dict(self.OTHER_ESCALATION_SELECTION):

                        vals["escalation_type_other"] = raw_type

            elif "escalation_type_primary_frontline" in vals and vals.get("escalation_journey", "primary_journey") == "primary_journey":

                vals["escalation_type"] = vals["escalation_type_primary_frontline"]

                vals["escalation_type_primary"] = vals["escalation_type_primary_frontline"]

            elif "escalation_type_primary" in vals and vals.get("escalation_journey") == "primary_journey":

                vals["escalation_type"] = vals["escalation_type_primary"]

            elif "escalation_type_other" in vals and vals.get("escalation_journey") == "other_work_journey":

                vals["escalation_type"] = vals["escalation_type_other"]

        return super().create(vals_list)



    _name = "helpdesk.ticket.escalate.wizard"

    _description = "Escalate Ticket Hierarchically (Bunna Journey Map)"



    ticket_id = fields.Many2one(

        comodel_name="helpdesk.ticket",

        string="Ticket",

        required=True,

    )

    current_user_id = fields.Many2one(

        comodel_name="res.users",

        string="Current Assignee",

        compute="_compute_current_assignee",

        readonly=True,

    )

    current_assignee_name = fields.Char(

        string="Current Assignee Display",

        compute="_compute_current_assignee",

        readonly=True,

    )

    current_role = fields.Char(

        string="Current Assignee Role",

        compute="_compute_current_assignee",

        readonly=True,

    )



    @api.depends("ticket_id", "ticket_id.user_id", "ticket_id.contact_center_agent_id")

    def _compute_current_assignee(self):

        for wiz in self:

            t = wiz.ticket_id.sudo() if wiz.ticket_id else False

            user = False

            role_str = ""

            name_str = ""

            if t:

                if t.user_id:

                    user = t.user_id

                    name_str = t.user_id.name

                    role_code = t.user_id.helpdesk_role

                    role_str = dict(self.env["res.users"]._fields["helpdesk_role"].selection).get(role_code, role_code or "Specialist / Officer")

                elif t.contact_center_agent_id:

                    cc_user = t.contact_center_agent_id.user_id or False

                    user = cc_user

                    name_str = f"{t.contact_center_agent_id.name} (Contact Center Agent)"

                    role_code = cc_user.helpdesk_role if cc_user else False

                    role_str = dict(self.env["res.users"]._fields["helpdesk_role"].selection).get(role_code, "Front line / Contact Center Agent") if role_code else "Front line / Contact Center Agent"

                elif t.create_uid and not t.create_uid.share:

                    user = t.create_uid

                    name_str = t.create_uid.name

                    role_code = t.create_uid.helpdesk_role

                    role_str = dict(self.env["res.users"]._fields["helpdesk_role"].selection).get(role_code, role_code or "Front line (Team)")

            if not user and not name_str:

                user = self.env.user

                name_str = self.env.user.name

                role_code = self.env.user.helpdesk_role

                role_str = dict(self.env["res.users"]._fields["helpdesk_role"].selection).get(role_code, role_code or "Front line (Team)")



            wiz.current_user_id = user

            wiz.current_assignee_name = name_str

            wiz.current_role = role_str

    operating_unit_id = fields.Many2one(

        comodel_name="operating.unit",

        string="Responsible Operating Unit",

        related="ticket_id.operating_unit_id",

        readonly=True,

    )

    escalation_journey = fields.Selection(

        selection=[

            ("primary_journey", "1. Primary Operating Unit Journey Track"),

            ("other_work_journey", "2. Other Operating Unit Journey Track (Cross-Unit Transfer)"),

        ],

        string="Escalation Journey Track",

        default="primary_journey",

        required=True,

        help="Choose between Primary Operating Unit escalation path or transferring to another Operating Unit / Department.",

    )

    hide_other_journey = fields.Boolean(

        string="Hide Other Operating Unit Journey",

        compute="_compute_hide_other_journey",

    )



    @api.depends("ticket_id", "is_frontline")

    def _compute_hide_other_journey(self):

        for wiz in self:

            # Frontline users are strictly restricted to the Primary Operating Unit Journey Track

            # and are not able to escalate to other operating units.

            wiz.hide_other_journey = bool(wiz.is_frontline)



    PRIMARY_ESCALATION_SELECTION = [

        ("contact_center_front_line", "Contact Center Front Line"),

        ("contact_center_back_line", "Contact Center Backline"),

        ("contact_center_team_leader", "Contact Center Team Leader"),

        ("contact_center_director", "Contact Center Director"),

        ("contact_center", "Contact Center (Tier 1)"),

        ("front_line", "Front line (Tier 1)"),

        ("back_line", "Back line (Tier 2)"),

        ("team_leader", "Team Leader (Tier 3)"),

        ("team_leader_to_deputy_chief", "Team Leader ➔ Deputy Chief (Direct Bypass)"),

        ("directorate", "Directorate"),

        ("deputy_chief", "Deputy Chief"),

        ("chief", "Chief"),

        ("ceo", "CEO"),

    ]



    PRIMARY_ESCALATION_SELECTION_NON_DIRECTOR = [

        ("contact_center_front_line", "Contact Center Front Line"),

        ("contact_center_back_line", "Contact Center Backline"),

        ("contact_center_team_leader", "Contact Center Team Leader"),

        ("contact_center_director", "Contact Center Director"),

        ("contact_center", "Contact Center (Tier 1)"),

        ("front_line", "Front line (Tier 1)"),

        ("back_line", "Back line (Tier 2)"),

        ("team_leader", "Team Leader (Tier 3)"),

        ("directorate", "Directorate"),

    ]



    FRONTLINE_PRIMARY_ESCALATION_SELECTION = [

        ("back_line", "Back line (Tier 2)"),

        ("team_leader", "Team Leader (Tier 3)"),

    ]



    OTHER_ESCALATION_SELECTION = [

        ("other_work", "Other Operating Unit / Transfer (Bridge)"),

        ("other_officer", "Other Operating Unit: Tier 1"),

        ("other_senior_principal", "Other Operating Unit: Tier 2"),

        ("other_manager_team_leader", "Other Operating Unit: Tier 3"),

        ("other_directorate", "Other Operating Unit: Directorate"),

        ("other_deputy_chief_chief", "Other Operating Unit: Deputy Chief / Chief"),

        ("other_ceo", "Other Operating Unit: CEO"),

    ]



    OTHER_ESCALATION_SELECTION_NON_DIRECTOR = [

        ("other_work", "Other Operating Unit / Transfer (Bridge)"),

        ("other_officer", "Other Operating Unit: Tier 1"),

        ("other_senior_principal", "Other Operating Unit: Tier 2"),

        ("other_manager_team_leader", "Other Operating Unit: Tier 3"),

        ("other_directorate", "Other Operating Unit: Directorate"),

    ]



    is_frontline = fields.Boolean(

        string="Is Frontline Privilege",

        compute="_compute_is_frontline",

    )



    @api.depends("ticket_id")

    def _compute_is_frontline(self):
        user = self.env.user
        is_admin_or_mgr = (
            user.has_group("bunna_helpdesk.group_helpdesk_manager")
            or user.has_group("base.group_erp_manager")
            or user.has_group("base.group_system")
            or getattr(user, "helpdesk_role", "") in ("admin", "manager")
            or self.env.is_admin()
        )
        BACKLINE_PLUS_ROLES = (
            "back_line", "backend", "fullstack", "database", "qa", "senior_principal",
            "team_leader", "supervisor", "manager", "directorate", "director",
            "deputy_chief", "deputy_cto", "chief", "cido", "ceo",
            "contact_center_back_line", "contact_center_team_leader", "contact_center_director",
        )
        for wiz in self:
            if is_admin_or_mgr:
                wiz.is_frontline = False
                continue

            t = wiz.ticket_id
            ticket_role = (t.user_id.helpdesk_role if t and t.user_id else "") or ""
            user_role = getattr(user, "helpdesk_role", "") or ""

            # Check if user is backline+ by role or explicit groups first
            if user_role in BACKLINE_PLUS_ROLES:
                wiz.is_frontline = False
            elif (
                user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")
                or user.has_group("bunna_helpdesk.group_helpdesk_back_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_team_leader")
                or user.has_group("bunna_helpdesk.group_helpdesk_director")
            ):
                wiz.is_frontline = False
            elif user_role in ("contact_center_front_line", "front_line", "frontend", "support", "officer", "contact_center"):
                wiz.is_frontline = True
            elif ticket_role in BACKLINE_PLUS_ROLES:
                wiz.is_frontline = False
            elif (
                user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_front_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center")
            ):
                wiz.is_frontline = True
            elif not t or not t.user_id or ticket_role in ("contact_center_front_line", "contact_center", "front_line", "frontend", "support", "officer"):
                wiz.is_frontline = True
            else:
                wiz.is_frontline = False



    is_director = fields.Boolean(

        string="Is Directorate Privilege",

        compute="_compute_is_director",

    )



    @api.depends("ticket_id")

    def _compute_is_director(self):

        user = self.env.user

        emp_obj = self.env["hr.employee"].sudo()

        user_emp = emp_obj.search([("user_id", "=", user.id)], limit=1)

        user_role = getattr(user, "helpdesk_role", "") or (user_emp.helpdesk_role if user_emp and hasattr(user_emp, "helpdesk_role") else "") or ""

        for wiz in self:

            t = wiz.ticket_id

            assignee = t.user_id if t else False

            assignee_role = getattr(assignee, "helpdesk_role", "") if assignee else ""

            # STRICT: Only users with Directorate / Director role have Directorate privilege.

            # Helpdesk Administrators and other roles do NOT see or escalate to Deputy Chief / Chief / CEO.

            if (
                user_role in ("directorate", "director", "contact_center_director")
                or assignee_role in ("directorate", "director", "contact_center_director")
                or user.has_group("bunna_helpdesk.group_helpdesk_director")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")
            ):
                wiz.is_director = True
            else:
                wiz.is_director = False



    escalation_type_primary_frontline = fields.Selection(

        selection=FRONTLINE_PRIMARY_ESCALATION_SELECTION,

        string="Escalation Target / Stage",

        default="back_line",

    )



    @api.onchange("escalation_type_primary_frontline")

    def _onchange_escalation_type_primary_frontline(self):

        if self.escalation_type_primary_frontline:

            self.escalation_type = self.escalation_type_primary_frontline

            self.escalation_type_primary = self.escalation_type_primary_frontline

            self._compute_operating_unit_user_ids()

            self._onchange_escalation_type_and_targets()

            if self.target_user_id and self.target_user_id not in self.operating_unit_user_ids and self.target_user_id.id not in self.operating_unit_user_ids.ids:

                self.target_user_id = False



    escalation_type_primary_non_director = fields.Selection(

        selection=PRIMARY_ESCALATION_SELECTION_NON_DIRECTOR,

        string="Escalation Target / Stage",

        default="team_leader",

    )



    @api.onchange("escalation_type_primary_non_director")

    def _onchange_escalation_type_primary_non_director(self):

        if self.escalation_type_primary_non_director:

            self.escalation_type = self.escalation_type_primary_non_director

            self.escalation_type_primary = self.escalation_type_primary_non_director

            self._compute_operating_unit_user_ids()

            self._onchange_escalation_type_and_targets()

            if self.target_user_id and self.target_user_id not in self.operating_unit_user_ids and self.target_user_id.id not in self.operating_unit_user_ids.ids:

                self.target_user_id = False



    escalation_type_primary = fields.Selection(

        selection=PRIMARY_ESCALATION_SELECTION,

        string="Escalation Target / Stage",

        default="team_leader",

    )



    @api.onchange("escalation_type_primary")

    def _onchange_escalation_type_primary(self):

        if self.escalation_type_primary:

            self.escalation_type = self.escalation_type_primary

            self._compute_operating_unit_user_ids()

            self._onchange_escalation_type_and_targets()

            if self.target_user_id and self.target_user_id not in self.operating_unit_user_ids and self.target_user_id.id not in self.operating_unit_user_ids.ids:

                self.target_user_id = False



    escalation_type_other_non_director = fields.Selection(

        selection=OTHER_ESCALATION_SELECTION_NON_DIRECTOR,

        string="Escalation Target / Stage",

        default="other_work",

    )



    @api.onchange("escalation_type_other_non_director")

    def _onchange_escalation_type_other_non_director(self):

        if self.escalation_type_other_non_director:

            self.escalation_type = self.escalation_type_other_non_director

            self.escalation_type_other = self.escalation_type_other_non_director

            self._compute_operating_unit_user_ids()

            self._onchange_escalation_type_and_targets()

            if self.target_user_id and self.target_user_id not in self.operating_unit_user_ids and self.target_user_id.id not in self.operating_unit_user_ids.ids:

                self.target_user_id = False



    escalation_type_other = fields.Selection(

        selection=OTHER_ESCALATION_SELECTION,

        string="Escalation Target / Stage",

        default="other_work",

    )



    @api.onchange("escalation_type_other")

    def _onchange_escalation_type_other(self):

        if self.escalation_type_other:

            self.escalation_type = self.escalation_type_other

            self._compute_operating_unit_user_ids()

            self._onchange_escalation_type_and_targets()

            if self.target_user_id and self.target_user_id not in self.operating_unit_user_ids and self.target_user_id.id not in self.operating_unit_user_ids.ids:

                self.target_user_id = False

    @api.model

    def _default_escalation_type(self):

        ticket_id = self.env.context.get("default_ticket_id") or self.env.context.get("active_id")

        if ticket_id:

            ticket = self.env["helpdesk.ticket"].browse(ticket_id)

            if not ticket:
                return "back_line"
            t_sudo = ticket.sudo()

            cc_emp = t_sudo.contact_center_agent_id

            cc_user = cc_emp.user_id if cc_emp else False

            role = (ticket.user_id.helpdesk_role if ticket.user_id else False) or (cc_user.helpdesk_role if cc_user else False) or getattr(self.env.user, "helpdesk_role", False) or ""

            if role in ("contact_center", "support"):

                return "front_line"

            elif not ticket.user_id or role in ("front_line", "frontend", "officer"):

                return "back_line"

            elif role in ("back_line", "backend", "senior_principal", "fullstack", "database", "qa"):

                return "team_leader"

            elif role in ("team_leader", "supervisor", "manager"):

                return "directorate"

            elif role in ("directorate", "director"):

                return "deputy_chief"

            elif role in ("deputy_chief", "deputy_cto"):

                return "chief"

            elif role in ("chief", "cido"):

                return "ceo"

        role = getattr(self.env.user, "helpdesk_role", False) or ""

        if role in ("contact_center", "support"):

            return "front_line"

        return "back_line"



    escalation_type = fields.Selection(

        selection=[

            # Left Track: Primary Operating Unit Journey Map

            ("contact_center_front_line", "Contact Center Front Line"),

            ("contact_center_back_line", "Contact Center Backline"),

            ("contact_center_team_leader", "Contact Center Team Leader"),

            ("contact_center_director", "Contact Center Director"),

            ("contact_center", "Contact Center (Tier 1)"),

            ("front_line", "Front line (Tier 1)"),

            ("back_line", "Back line (Tier 2)"),

            ("team_leader", "Team Leader (Tier 3)"),

            ("team_leader_to_deputy_chief", "Team Leader ➔ Deputy Chief (Direct Bypass)"),

            ("directorate", "Directorate"),

            ("deputy_chief", "Deputy Chief"),

            ("chief", "Chief"),

            ("ceo", "CEO"),



            # Bridge & Right Track: Other Operating Unit Escalation Journey

            ("other_work", "Other Operating Unit / Transfer (Bridge)"),

            ("other_officer", "Other Operating Unit: Tier 1"),

            ("other_senior_principal", "Other Operating Unit: Tier 2"),

            ("other_manager_team_leader", "Other Operating Unit: Tier 3"),

            ("other_directorate", "Other Operating Unit: Directorate"),

            ("other_deputy_chief_chief", "Other Operating Unit: Deputy Chief / Chief"),

            ("other_ceo", "Other Operating Unit: CEO"),



            # Legacy aliases

            ("peer_backend", "Back line (Tier 2) / Specialist"),

            ("line_manager", "Team Leader (Tier 3) / Division Manager"),

            ("manager", "Manager / Team Leader"),

            ("director", "Directorate Director"),

            ("deputy_cto", "Deputy Chief"),

            ("cido", "Chief"),

            ("team_transfer", "Other Operating Unit Transfer"),

        ],

        string="Escalation Target",

        default=lambda self: self._default_escalation_type(),

        required=True,

    )

    target_operating_unit_id = fields.Many2one(

        comodel_name="operating.unit",

        string="Target Responsible Operating Unit",

        help="Operating Unit from HR Employee to transfer this ticket to.",

    )

    target_team_id = fields.Many2one(

        comodel_name="helpdesk.ticket.team",

        string="Target Unit Team",

        compute="_compute_target_team_id",

        store=True,

        readonly=False,

    )

    operating_unit_user_ids = fields.Many2many(

        comodel_name="res.users",

        string="Operating Unit Users",

        compute="_compute_operating_unit_user_ids",

    )

    target_user_id = fields.Many2one(

        comodel_name="res.users",

        string="Assign To",

        domain="[('share', '=', False), ('id', 'in', operating_unit_user_ids)]",

        help="Designated team member, specialist, manager, director, or executive from the Operating Unit.",

    )



    @api.depends("operating_unit_id", "target_operating_unit_id", "escalation_journey", "escalation_type", "escalation_type_primary", "escalation_type_primary_non_director", "escalation_type_primary_frontline", "is_frontline", "is_director", "escalation_type_other", "escalation_type_other_non_director", "ticket_id", "ticket_id.contact_center_agent_ids", "ticket_id.contact_center_agent_id", "ticket_id.create_uid")

    def _get_escalater_operating_units(self, user=None, ticket=None):
        """
        Identify the operating unit(s) of the person performing / initiating the escalation.
        Inspects:
        - Contact Center Agent on ticket if applicable
        - hr.employee operating units of the escalater user (operating_unit_ids and default_operating_unit_id)
        - User operating unit records (operating_unit_ids, default_operating_unit_id, assigned_operating_unit_ids)
        - Excludes generic Main Operating Unit (id=1) if specific units are assigned
        """
        emp_obj = self.env["hr.employee"].sudo()
        ou_obj = self.env["operating.unit"].sudo()
        ous = ou_obj.browse()

        users_to_check = self.env["res.users"].browse()
        if user:
            users_to_check |= user
        if self.env.user:
            users_to_check |= self.env.user
        if ticket:
            if ticket.user_id:
                users_to_check |= ticket.user_id
            if ticket.contact_center_agent_id and ticket.contact_center_agent_id.user_id:
                users_to_check |= ticket.contact_center_agent_id.user_id
            if ticket.sudo().contact_center_agent_id:
                cc_emp = ticket.sudo().contact_center_agent_id
                if hasattr(cc_emp, "operating_unit_ids") and cc_emp.operating_unit_ids:
                    ous |= cc_emp.operating_unit_ids
                if hasattr(cc_emp, "default_operating_unit_id") and cc_emp.default_operating_unit_id:
                    ous |= cc_emp.default_operating_unit_id

        non_admin_users = users_to_check.filtered(lambda u: u.id not in (1, 2) and not u.share)
        target_users = non_admin_users if non_admin_users else users_to_check.filtered(lambda u: not u.share)

        for u in target_users:
            emp = emp_obj.search([("user_id", "=", u.id), ("active", "=", True)], limit=1)
            if emp:
                if hasattr(emp, "operating_unit_ids") and emp.operating_unit_ids:
                    ous |= emp.operating_unit_ids
                if hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id:
                    ous |= emp.default_operating_unit_id
            if hasattr(u, "operating_unit_ids") and u.operating_unit_ids:
                ous |= u.operating_unit_ids
            if hasattr(u, "default_operating_unit_id") and u.default_operating_unit_id:
                ous |= u.default_operating_unit_id
            if hasattr(u, "assigned_operating_unit_ids") and u.assigned_operating_unit_ids:
                ous |= u.assigned_operating_unit_ids

        if not ous and ticket and ticket.create_uid and not ticket.create_uid.share:
            c_emp = emp_obj.search([("user_id", "=", ticket.create_uid.id), ("active", "=", True)], limit=1)
            if c_emp:
                ous |= c_emp.operating_unit_ids or c_emp.default_operating_unit_id
            if hasattr(ticket.create_uid, "default_operating_unit_id") and ticket.create_uid.default_operating_unit_id:
                ous |= ticket.create_uid.default_operating_unit_id

        specific_ous = ous.filtered(lambda o: o.id != 1)
        if specific_ous:
            return specific_ous
        if ous:
            return ous
        cc_fallback = ou_obj.search([("name", "ilike", "Contact Center")], limit=1)
        if cc_fallback:
            return cc_fallback
        return ticket.operating_unit_id if ticket and ticket.operating_unit_id else ou_obj.browse()

    def _get_ou_users(self, ou):
        if not ou:
            return self.env["res.users"]
        User = self.env["res.users"].sudo()
        emp_obj = self.env["hr.employee"].sudo()
        ou_ids = ou.ids if hasattr(ou, "ids") else [ou.id]

        # Combined user search in single query
        user_or_parts = []
        if "default_operating_unit_id" in User._fields and User._fields["default_operating_unit_id"].store:
            user_or_parts.append(("default_operating_unit_id", "in", ou_ids))
        if "assigned_operating_unit_ids" in User._fields and User._fields["assigned_operating_unit_ids"].store:
            user_or_parts.append(("assigned_operating_unit_ids", "in", ou_ids))

        users = self.env["res.users"]
        if user_or_parts:
            base_u_dom = [("active", "=", True), ("share", "=", False), ("id", "not in", (1, 2))]
            if len(user_or_parts) == 1:
                u_dom = base_u_dom + [user_or_parts[0]]
            else:
                u_dom = ["|"] + [user_or_parts[0], user_or_parts[1]] + base_u_dom
            users = User.search(u_dom)

        # Combined employee search in single query
        emp_or_parts = []
        if "default_operating_unit_id" in emp_obj._fields and emp_obj._fields["default_operating_unit_id"].store:
            emp_or_parts.append(("default_operating_unit_id", "in", ou_ids))
        if "operating_unit_ids" in emp_obj._fields and emp_obj._fields["operating_unit_ids"].store:
            emp_or_parts.append(("operating_unit_ids", "in", ou_ids))

        emp_users = self.env["res.users"]
        if emp_or_parts:
            base_e_dom = [
                ("active", "=", True),
                ("user_id", "!=", False),
                ("user_id.active", "=", True),
                ("user_id.share", "=", False),
                ("user_id.id", "not in", (1, 2)),
            ]
            if len(emp_or_parts) == 1:
                e_dom = base_e_dom + [emp_or_parts[0]]
            else:
                e_dom = ["|"] + [emp_or_parts[0], emp_or_parts[1]] + base_e_dom
            emp_users = emp_obj.search(e_dom).mapped("user_id")

        direct_users = self.env["res.users"]
        if hasattr(ou, "mapped") and hasattr(ou, "user_ids"):
            direct_users = ou.mapped("user_ids").filtered(lambda u: not u.share and u.active and u.id not in (1, 2))
        elif hasattr(ou, "user_ids") and ou.user_ids:
            direct_users = ou.user_ids.filtered(lambda u: not u.share and u.active and u.id not in (1, 2))

        return (users | emp_users | direct_users).filtered(lambda u: not u.share and u.active and u.id not in (1, 2))

    def _compute_operating_unit_user_ids(self):
        """
        Compute eligible users for the escalation target:
        - Primary Journey: Filtered strictly by the escalater's Operating Unit.
        - Other Journey: Filtered strictly by the target Operating Unit.
        - Filtered strictly by the selected Escalation Target / Stage role (with fallback to OU members).
        """
        for wiz in self:
            ticket = wiz.ticket_id
            if wiz.escalation_journey == "primary_journey":
                # Primary Journey Track: Strictly within the escalater's operating unit.
                escalater_user = wiz.current_user_id or self.env.user
                primary_ous = wiz._get_escalater_operating_units(escalater_user, ticket)
                base_users = wiz._get_ou_users(primary_ous)
                if wiz.is_frontline and wiz.escalation_type_primary_frontline:
                    eff_type = wiz.escalation_type_primary_frontline
                elif not wiz.is_director and wiz.escalation_type_primary_non_director:
                    eff_type = wiz.escalation_type_primary_non_director
                else:
                    eff_type = wiz.escalation_type_primary or wiz.escalation_type or "team_leader"
            else:
                # Other Operating Unit Journey Track -> Destination Operating Unit employees/users
                div_ou = wiz.target_operating_unit_id or wiz.operating_unit_id or (ticket.operating_unit_id if ticket else False)
                base_users = wiz._get_ou_users(div_ou)
                if not wiz.is_director and wiz.escalation_type_other_non_director:
                    eff_type = wiz.escalation_type_other_non_director
                else:
                    eff_type = wiz.escalation_type_other or wiz.escalation_type or "other_work"

            # If escalating to Contact Center, include Contact Center Operating Unit users
            if eff_type and eff_type.startswith("contact_center"):
                cc_ou = self.env["operating.unit"].sudo().search([("name", "ilike", "Contact Center")], limit=1)
                if cc_ou:
                    base_users = base_users | wiz._get_ou_users(cc_ou)

            # Filter base_users strictly by stage role
            allowed_roles = TARGET_STAGE_ROLES.get(eff_type)
            if allowed_roles:
                filtered_users = base_users.filtered(
                    lambda u: getattr(u, "helpdesk_role", False) in allowed_roles or getattr(u, "helpdesk_role", False) == "admin" or u.has_group("bunna_helpdesk.group_helpdesk_manager")
                )
            else:
                filtered_users = base_users

            # Fallback: if no role-matched user found, try cross-OU global search for senior and contact center roles
            if not filtered_users and (eff_type in ("team_leader", "line_manager", "manager", "directorate", "director", "deputy_chief", "chief", "ceo") or (eff_type and eff_type.startswith("contact_center"))):
                _all_users = self.env["res.users"].sudo().search([
                    ("share", "=", False),
                    ("active", "=", True),
                    ("id", "not in", [1, 2]),
                ])
                _target_roles = allowed_roles or (eff_type,)
                filtered_users = _all_users.filtered(
                    lambda u: getattr(u, "helpdesk_role", False) in _target_roles
                    or (eff_type == "contact_center_front_line" and u.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line"))
                    or (eff_type == "contact_center_back_line" and u.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line"))
                    or (eff_type == "contact_center_team_leader" and u.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader"))
                    or (eff_type == "contact_center_director" and u.has_group("bunna_helpdesk.group_helpdesk_contact_center_director"))
                )
            # Final fallback to base_users in escalater's operating unit
            if not filtered_users:
                filtered_users = base_users

            # Always exclude current assignee / user so ticket is not escalated to oneself
            if ticket and ticket.user_id:
                filtered_users = filtered_users.filtered(lambda u: u.id != ticket.user_id.id)
            if wiz.current_user_id:
                filtered_users = filtered_users.filtered(lambda u: u.id != wiz.current_user_id.id)
            if self.env.user:
                filtered_users = filtered_users.filtered(lambda u: u.id != self.env.user.id)

            wiz.operating_unit_user_ids = filtered_users


    target_user_position = fields.Char(
        string="Current Position",
        compute="_compute_target_user_info",
        readonly=True,
        help="Current job title or role of the selected assignee.",
    )
    target_user_phone = fields.Char(
        string="Phone Number",
        compute="_compute_target_user_info",
        readonly=True,
        help="Registered contact number of the selected assignee.",
    )
    target_user_status = fields.Char(
        string="Status",
        compute="_compute_target_user_info",
        readonly=True,
        help="Active or inactive status of the selected assignee.",
    )

    @api.depends("target_user_id")
    def _compute_target_user_info(self):
        for wiz in self:
            if not wiz.target_user_id:
                wiz.target_user_position = False
                wiz.target_user_phone = False
                wiz.target_user_status = False
                continue
            user = wiz.target_user_id
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
            if not emp:
                emp = self.env["hr.employee"].sudo().search([("name", "=ilike", user.name)], limit=1)

            # 1. Position from HR Employee
            pos = False
            if emp:
                pos = (
                    emp.job_title
                    or (emp.job_id.name if emp.job_id else False)
                    or (getattr(emp.job_position, "name", False) if hasattr(emp, "job_position") and emp.job_position else False)
                    or (getattr(emp, "job_name", False))
                    or (getattr(emp.job_category, "name", False) if hasattr(emp, "job_category") and emp.job_category else False)
                    or (f"{emp.department_id.name} Officer" if emp.department_id else False)
                )
            if not pos:
                role_dict = dict(user._fields["helpdesk_role"].selection) if "helpdesk_role" in user._fields else {}
                pos = role_dict.get(user.helpdesk_role) or getattr(user.partner_id, "function", False) or _("Staff / Specialist")

            # 2. Phone from HR Employee
            phone = False
            if emp:
                phone = (
                    getattr(emp, "work_phone", False)
                    or getattr(emp, "mobile_phone", False)
                    or getattr(emp, "phone", False)
                    or getattr(emp, "phone_num", False)
                    or getattr(emp, "personal_phone", False)
                    or getattr(emp, "private_phone", False)
                    or getattr(emp, "alternative_mobile", False)
                )
            if not phone:
                phone = getattr(user.partner_id, "phone", False) or getattr(user.partner_id, "mobile", False) or _("N/A")

            # 3. Status from HR Employee
            status = _("Active")
            if emp:
                is_leave = (
                    getattr(emp, "is_on_leave", False)
                    or getattr(user, "is_on_leave", False)
                    or bool(getattr(emp, "current_leave_id", False))
                )
                if is_leave:
                    leave_label = getattr(user, "leave_status_text", False) or _("On Leave")
                    status = f"On Leave ({leave_label})"
                elif not emp.active or not user.active:
                    status = _("Inactive")
                else:
                    presence = getattr(emp, "hr_presence_state", False)
                    attendance = getattr(emp, "attendance_state", False)
                    if presence in ("present", "online") or attendance == "checked_in":
                        status = _("Active (Online)")
                    else:
                        status = _("Active")
            else:
                status = _("Active") if user.active else _("Inactive")

            wiz.target_user_position = pos
            wiz.target_user_phone = phone or _("N/A")
            wiz.target_user_status = status

    target_user_is_on_leave = fields.Boolean(

        related="target_user_id.is_on_leave",

        string="Target User is on Leave",

    )

    target_user_leave_status = fields.Char(

        related="target_user_id.leave_status_text",

        string="Target User Leave Status",

    )

    suggested_recipient_name = fields.Char(

        string="Auto-Detected Candidate",

        compute="_compute_suggested_recipient",

    )

    reason = fields.Text(

        string="Escalation Reason",

        required=False,

        help="Explain findings, root cause, and reason why this case requires higher-level or cross-unit resolution.",

    )
    notify_customer = fields.Boolean(
        string="Notify Customer",
        default=False,
        help="Button ON/OFF: If enabled, dispatches an SMS or Email notification to the customer informing them that their issue has been registered, accepted, and is being processed.",
    )
    notification_channel = fields.Selection(
        selection=[
            ("sms", "SMS"),
            ("email", "Email"),
        ],
        string="Notification Channel",
        default="sms",
        help="Drop-down SMS and email: Select whether to dispatch notification via SMS or Email.",
    )



    @api.depends("target_operating_unit_id", "ticket_id")

    def _compute_target_team_id(self):

        for wiz in self:

            ou = wiz.target_operating_unit_id or (wiz.ticket_id.operating_unit_id if wiz.ticket_id else False)

            if ou:

                team = self.env["helpdesk.ticket.team"].search([("operating_unit_id", "=", ou.id)], limit=1)

                wiz.target_team_id = team.id if team else (wiz.ticket_id.team_id.id if wiz.ticket_id else False)

            else:

                wiz.target_team_id = wiz.ticket_id.team_id.id if wiz.ticket_id else False



    @api.model

    def default_get(self, fields_list):

        res = super().default_get(fields_list)

        ticket_id = res.get("ticket_id") or self.env.context.get("default_ticket_id") or self.env.context.get("active_id")

        ticket = self.env["helpdesk.ticket"].browse(ticket_id) if ticket_id else False

        ctx_def_type = self.env.context.get("default_escalation_type")



        if ticket and ticket.exists():

            res["ticket_id"] = ticket.id



            t_sudo = ticket.sudo()

            cc_emp = t_sudo.contact_center_agent_id

            cc_user = cc_emp.user_id if cc_emp else False

            current_assignee = ticket.user_id or cc_user or False

            role = (ticket.user_id.helpdesk_role if ticket.user_id else False) or (cc_user.helpdesk_role if cc_user else False) or getattr(self.env.user, "helpdesk_role", False) or ""



            if ctx_def_type:

                def_type = ctx_def_type

            else:

                user_is_dir = (

                    role in ("directorate", "director")

                    or getattr(self.env.user, "helpdesk_role", "") in ("directorate", "director")

                )

                if role in ("contact_center", "support"):

                    def_type = "front_line"

                elif not current_assignee or role in ("front_line", "frontend", "officer"):

                    def_type = "back_line"

                elif role in ("back_line", "backend", "senior_principal", "fullstack", "database", "qa"):

                    def_type = "team_leader"

                elif role in ("team_leader", "supervisor", "manager"):

                    def_type = "directorate"

                elif role in ("directorate", "director"):

                    def_type = "deputy_chief" if user_is_dir else "directorate"

                elif role in ("deputy_chief", "deputy_cto"):

                    def_type = "chief" if user_is_dir else "directorate"

                elif role in ("chief", "cido"):

                    def_type = "ceo" if user_is_dir else "directorate"

                else:

                    def_type = "team_leader" if current_assignee else "back_line"



            res["escalation_type"] = def_type

            if def_type.startswith("other_") or def_type == "team_transfer":

                res["escalation_journey"] = "other_work_journey"

                res["escalation_type_other"] = def_type if any(def_type == k for k, _ in self.OTHER_ESCALATION_SELECTION) else "other_work"

                res["escalation_type_other_non_director"] = def_type if any(def_type == k for k, _ in self.OTHER_ESCALATION_SELECTION_NON_DIRECTOR) else "other_directorate"

                res["escalation_type_primary"] = False

                res["escalation_type_primary_non_director"] = False

                res["escalation_type_primary_frontline"] = False

            else:

                res["escalation_journey"] = "primary_journey"

                res["escalation_type_primary"] = def_type if any(def_type == k for k, _ in self.PRIMARY_ESCALATION_SELECTION) else "team_leader"

                res["escalation_type_primary_non_director"] = def_type if any(def_type == k for k, _ in self.PRIMARY_ESCALATION_SELECTION_NON_DIRECTOR) else "directorate"

                res["escalation_type_primary_frontline"] = def_type if def_type in ("back_line", "team_leader") else "back_line"

                res["escalation_type_other"] = False

                res["escalation_type_other_non_director"] = False



            # Enforce frontline restriction: frontline users can never default to other operating unit
        user = self.env.user
        is_admin_or_mgr = (
            user.has_group("bunna_helpdesk.group_helpdesk_manager")
            or user.has_group("base.group_erp_manager")
            or user.has_group("base.group_system")
            or getattr(user, "helpdesk_role", "") in ("admin", "manager")
            or self.env.is_admin()
        )
        user_role = getattr(user, "helpdesk_role", "") or ""
        ticket_role = (ticket.user_id.helpdesk_role if ticket and ticket.user_id else "") or ""
        is_fl_user = False
        BACKLINE_PLUS_ROLES = (
            "back_line", "backend", "fullstack", "database", "qa", "senior_principal",
            "team_leader", "supervisor", "manager", "directorate", "director",
            "deputy_chief", "deputy_cto", "chief", "cido", "ceo",
            "contact_center_back_line", "contact_center_team_leader", "contact_center_director",
        )
        if not is_admin_or_mgr:
            if user_role in BACKLINE_PLUS_ROLES:
                is_fl_user = False
            elif (
                user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")
                or user.has_group("bunna_helpdesk.group_helpdesk_back_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_team_leader")
                or user.has_group("bunna_helpdesk.group_helpdesk_director")
            ):
                is_fl_user = False
            elif user_role in ("contact_center_front_line", "front_line", "frontend", "support", "officer", "contact_center"):
                is_fl_user = True
            elif ticket_role in BACKLINE_PLUS_ROLES:
                is_fl_user = False
            elif (
                user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_front_line")
                or user.has_group("bunna_helpdesk.group_helpdesk_contact_center")
            ):
                is_fl_user = True
            elif not ticket or not ticket.user_id or ticket_role in ("contact_center_front_line", "contact_center", "front_line", "frontend", "support", "officer"):
                is_fl_user = True

        if is_fl_user:
            res["escalation_journey"] = "primary_journey"
            res["hide_other_journey"] = True
            def_type = "back_line"
            res["escalation_type"] = def_type
            res["escalation_type_primary_frontline"] = def_type
            res["escalation_type_other"] = False
            res["escalation_type_other_non_director"] = False
            res["target_operating_unit_id"] = False

        # Pre-populate suggested user and operating unit based on resolved type and journey track

            journey = res.get("escalation_journey", "primary_journey")

            if ticket:
                suggested_user, suggested_team, suggested_ou = self._resolve_target(ticket, def_type, journey=journey)
            else:
                suggested_user, suggested_team, suggested_ou = False, False, False

            if suggested_user:

                res["target_user_id"] = suggested_user.id

            if suggested_team:

                res["target_team_id"] = suggested_team.id

            elif ticket and ticket.team_id:

                res["target_team_id"] = ticket.team_id.id

            if suggested_ou and res.get("escalation_journey") != "other_work_journey":

                res["target_operating_unit_id"] = suggested_ou.id

            elif ticket and ticket.operating_unit_id and res.get("escalation_journey") != "other_work_journey":

                res["target_operating_unit_id"] = ticket.operating_unit_id.id

            else:

                res["target_operating_unit_id"] = False



        return res



    @api.onchange("escalation_journey")

    def _onchange_escalation_journey(self):

        if self.is_frontline and self.escalation_journey == "other_work_journey":

            self.escalation_journey = "primary_journey"

            return {

                "warning": {

                    "title": _("Restricted Escalation"),

                    "message": _("Frontline users are not permitted to escalate to other operating units. Frontline escalation is restricted to the Primary Operating Unit Journey Track (Tier 2 Back line or Tier 3 Team Leader)."),

                }

            }

        role = ""

        if self.ticket_id and self.ticket_id.user_id and self.ticket_id.user_id.helpdesk_role:

            role = self.ticket_id.user_id.helpdesk_role

        elif getattr(self.env.user, "helpdesk_role", False):

            role = self.env.user.helpdesk_role



        if self.escalation_journey == "primary_journey":

            self.target_operating_unit_id = False

            if role in ("contact_center_front_line", "contact_center", "support"):
                self.escalation_type = "contact_center_back_line"
            elif not self.ticket_id.user_id or role in ("front_line", "frontend", "officer"):
                self.escalation_type = "back_line"
            elif role in ("contact_center_back_line", "back_line", "backend", "senior_principal", "fullstack", "database", "qa"):
                self.escalation_type = "contact_center_team_leader" if "contact_center" in role else "team_leader"
            elif role in ("contact_center_team_leader", "team_leader", "supervisor", "manager"):
                self.escalation_type = "contact_center_director" if "contact_center" in role else "directorate"
            elif role in ("contact_center_director", "directorate", "director"):
                self.escalation_type = "deputy_chief" if self.is_director else "directorate"
            elif role in ("deputy_chief", "deputy_cto"):
                self.escalation_type = "chief" if self.is_director else "directorate"
            elif role in ("chief", "cido"):
                self.escalation_type = "ceo" if self.is_director else "directorate"
            else:
                self.escalation_type = "team_leader"
            self.escalation_type_primary = self.escalation_type
            self.escalation_type_primary_non_director = self.escalation_type if any(self.escalation_type == k for k, _ in self.PRIMARY_ESCALATION_SELECTION_NON_DIRECTOR) else "directorate"
            self.escalation_type_primary_frontline = self.escalation_type if self.escalation_type in ("back_line", "team_leader") else "back_line"
            self.escalation_type_other = False
            self.escalation_type_other_non_director = False

        elif self.escalation_journey == "other_work_journey":
            self.target_operating_unit_id = False
            self.target_user_id = False
            if role in ("contact_center_front_line", "contact_center", "support"):
                self.escalation_type = "other_officer"
            elif role in ("front_line", "frontend", "officer"):
                self.escalation_type = "other_senior_principal"
            elif role in ("contact_center_back_line", "back_line", "backend", "senior_principal", "fullstack", "database", "qa"):
                self.escalation_type = "other_manager_team_leader"
            elif role in ("contact_center_team_leader", "team_leader", "supervisor", "manager"):
                self.escalation_type = "other_directorate"
            elif role in ("contact_center_director", "directorate", "director"):
                self.escalation_type = "other_deputy_chief_chief" if self.is_director else "other_directorate"
            elif role in ("deputy_chief", "deputy_cto", "chief", "cido"):
                self.escalation_type = "other_ceo" if self.is_director else "other_directorate"
            else:
                self.escalation_type = "other_work"

            self.escalation_type_other = self.escalation_type

            self.escalation_type_other_non_director = self.escalation_type if any(self.escalation_type == k for k, _ in self.OTHER_ESCALATION_SELECTION_NON_DIRECTOR) else "other_directorate"

            self.escalation_type_primary = False

            self.escalation_type_primary_non_director = False

            self.escalation_type_primary_frontline = False



        self.target_user_id = False

        self._compute_operating_unit_user_ids()

        self._onchange_escalation_type_and_targets()



    @api.depends("escalation_type", "escalation_type_primary", "escalation_type_primary_non_director", "escalation_type_primary_frontline", "is_frontline", "is_director", "escalation_type_other", "escalation_type_other_non_director", "escalation_journey", "ticket_id", "target_operating_unit_id")

    def _compute_suggested_recipient(self):

        for wiz in self:

            eff_type = wiz.escalation_type

            if wiz.escalation_journey == "primary_journey":

                if wiz.is_frontline and wiz.escalation_type_primary_frontline:

                    eff_type = wiz.escalation_type_primary_frontline

                elif not wiz.is_director and wiz.escalation_type_primary_non_director:

                    eff_type = wiz.escalation_type_primary_non_director

                else:

                    eff_type = wiz.escalation_type_primary or wiz.escalation_type

            elif wiz.escalation_journey == "other_work_journey":

                if not wiz.is_director and wiz.escalation_type_other_non_director:

                    eff_type = wiz.escalation_type_other_non_director

                else:

                    eff_type = wiz.escalation_type_other or wiz.escalation_type



            if wiz.ticket_id and eff_type:

                user, team, ou = wiz._resolve_target(

                    wiz.ticket_id,

                    eff_type,

                    target_ou=wiz.target_operating_unit_id,

                    journey=wiz.escalation_journey,

                )

                parts = []

                if user and (user in wiz.operating_unit_user_ids or user.id in wiz.operating_unit_user_ids.ids):

                    parts.append(user.name)

                    if ou:

                        parts.append(f"[{ou.name}]")

                wiz.suggested_recipient_name = " ".join(parts) if parts else _("None identified")

            else:

                wiz.suggested_recipient_name = ""



    @api.onchange("target_user_id")

    def _onchange_target_user_id(self):

        if self.target_user_id and getattr(self.target_user_id, "is_on_leave", False):

            leave_status = getattr(self.target_user_id, "leave_status_text", "") or _("Currently on Leave")

            return {

                "warning": {

                    "title": _("Agent Currently on Leave"),

                    "message": _(

                        "Warning: %s is %s.\n"

                        "If you proceed with escalation to this user, ticket resolution may be delayed. "

                        "Please consider assigning to an active and available colleague instead."

                    ) % (self.target_user_id.name, leave_status),

                }

            }



    @api.onchange("escalation_type", "target_operating_unit_id")

    def _onchange_escalation_type_and_targets(self):

        if self.ticket_id and self.escalation_type:

            self._compute_operating_unit_user_ids()

            user, team, ou = self._resolve_target(

                self.ticket_id,

                self.escalation_type,

                target_ou=self.target_operating_unit_id,

                journey=self.escalation_journey,

            )

            if user and (user in self.operating_unit_user_ids or user.id in self.operating_unit_user_ids.ids):

                self.target_user_id = user

            else:

                self.target_user_id = False

            if team:

                self.target_team_id = team

            if ou and self.escalation_journey == "other_work_journey" and not self.target_operating_unit_id:

                self.target_operating_unit_id = ou



    def _resolve_target(self, ticket, escalation_type, target_ou=None, target_team=None, journey=None):

        """

        Resolve target user, team, and operating unit according to the Escalation Journey Map:

        - Primary Path: Contact Center ➔ Front line ➔ Back line ➔ Team Leader ➔ Directorate ➔ Deputy Chief ➔ Chief ➔ CEO

          Candidates resolved from the Contact Center Operating Unit.

        - Other Operating Unit Path: Other OU ➔ Officer ➔ Senior/Principal ➔ Manager/Team Leader ➔ Directorate ➔ Deputy Chief/Chief ➔ CEO

          Candidates resolved from the Division Operating Unit (or target_ou).

        Always prioritizes candidates who are not currently on leave.

        """

        if not ticket:
            return False, False, False
        t_sudo = ticket.sudo()

        cc_emp = t_sudo.contact_center_agent_id

        cc_user = cc_emp.user_id if cc_emp else False

        current_user = ticket.user_id or cc_user or self.env.user

        emp_obj = self.env["hr.employee"].sudo()

        current_emp = emp_obj.search([("user_id", "=", current_user.id)], limit=1) if current_user else False



        params = self.env["ir.config_parameter"].sudo()

        ceo_param = params.get_param("bunna_helpdesk.ceo_user_id")

        ceo_user = False

        if ceo_param and str(ceo_param).isdigit():

            ceo_user = self.env["res.users"].sudo().browse(int(ceo_param))

            if not ceo_user.exists() or not ceo_user.active:

                ceo_user = False



        is_primary = (journey == "primary_journey") or (not journey and not (escalation_type.startswith("other_") or escalation_type == "team_transfer"))
        if is_primary:
            # Primary Journey Track operates strictly within the escalater's operating unit.
            escalater_ous = self._get_escalater_operating_units(current_user, ticket)
            ou = escalater_ous[:1] if escalater_ous else (
                (ticket.sudo().contact_center_agent_id.default_operating_unit_id if ticket.sudo().contact_center_agent_id else False)
                or (ticket.create_uid.default_operating_unit_id if ticket.create_uid else False)
                or self.env["operating.unit"].sudo().search([("name", "ilike", "contact center")], limit=1)
                or ticket.operating_unit_id
            )
            team = self.env["helpdesk.ticket.team"].search([("operating_unit_id", "in", (escalater_ous.ids if escalater_ous else [ou.id]))], limit=1) if ou else ticket.team_id
        else:
            ou = target_ou or ticket.operating_unit_id
            team = self.env["helpdesk.ticket.team"].search([("operating_unit_id", "=", ou.id)], limit=1) if ou else ticket.team_id



        # Helper to get users from operating unit via hr.employee and direct links

        def _get_ou_users(operating_unit):

            if not operating_unit:

                return self.env["res.users"]

            User = self.env["res.users"].sudo()

            users = self.env["res.users"]

            # Safely check stored fields on res.users

            user_domains = []

            if "default_operating_unit_id" in User._fields and User._fields["default_operating_unit_id"].store:

                user_domains.append([("default_operating_unit_id", "=", operating_unit.id)])

            if "assigned_operating_unit_ids" in User._fields and User._fields["assigned_operating_unit_ids"].store:

                user_domains.append([("assigned_operating_unit_ids", "in", [operating_unit.id])])



            for dom in user_domains:

                users |= User.search([

                    ("active", "=", True),

                    ("share", "=", False),

                    ("id", "not in", (1, 2)),

                ] + dom)



            # Safely check stored fields on hr.employee

            emp_users = self.env["res.users"]

            emp_domains = []

            if "default_operating_unit_id" in emp_obj._fields and emp_obj._fields["default_operating_unit_id"].store:

                emp_domains.append([("default_operating_unit_id", "=", operating_unit.id)])

            if "operating_unit_ids" in emp_obj._fields and emp_obj._fields["operating_unit_ids"].store:

                emp_domains.append([("operating_unit_ids", "in", [operating_unit.id])])



            for dom in emp_domains:

                emp_users |= emp_obj.search([

                    ("active", "=", True),

                    ("user_id", "!=", False),

                    ("user_id.active", "=", True),

                    ("user_id.share", "=", False),

                    ("user_id.id", "not in", (1, 2)),

                ] + dom).mapped("user_id")



            direct_users = self.env["res.users"]

            if hasattr(operating_unit, "user_ids") and operating_unit.user_ids:

                direct_users = operating_unit.user_ids.filtered(lambda u: not u.share and u.active and u.id not in (1, 2))



            return (users | emp_users | direct_users).filtered(lambda u: not u.share and u.active)



        ou_users = self._get_ou_users(escalater_ous if is_primary and escalater_ous else ou)



        def _pick_best(recordset):

            if not recordset:

                return False

            valid_set = recordset.filtered(lambda u: u.id != current_user.id and u.id != self.env.user.id)

            if not valid_set:

                valid_set = recordset.filtered(lambda u: u.id != current_user.id)

            if not valid_set:

                return False

            avail = valid_set.filtered(lambda u: not getattr(u, "is_on_leave", False))

            pool = avail if avail else valid_set

            regular = pool.filtered(lambda u: u.id not in (1, 2) and not getattr(u, "is_admin", lambda: False)())

            return regular[0] if regular else pool[0]



        # ── Primary Track ─────────────────────────────────────────────────────

        if escalation_type in ("contact_center", "contact_center_front_line"):

            cc_ou = self.env["operating.unit"].sudo().search([("name", "ilike", "Contact Center")], limit=1)

            target_pool = ou_users | self._get_ou_users(cc_ou)

            cc_users = target_pool.filtered(

                lambda u: u.id != current_user.id and (

                    getattr(u, "helpdesk_role", "") in ("contact_center_front_line", "contact_center", "support")

                    or u.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")

                )

            )

            return _pick_best(cc_users), team, ou



        elif escalation_type == "contact_center_back_line":

            cc_ou = self.env["operating.unit"].sudo().search([("name", "ilike", "Contact Center")], limit=1)

            target_pool = ou_users | self._get_ou_users(cc_ou)

            cc_users = target_pool.filtered(

                lambda u: u.id != current_user.id and (

                    getattr(u, "helpdesk_role", "") in ("contact_center_back_line", "back_line")

                    or u.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")

                )

            )

            return _pick_best(cc_users), team, ou



        elif escalation_type == "contact_center_team_leader":

            cc_ou = self.env["operating.unit"].sudo().search([("name", "ilike", "Contact Center")], limit=1)

            target_pool = ou_users | self._get_ou_users(cc_ou)

            cc_users = target_pool.filtered(

                lambda u: u.id != current_user.id and (

                    getattr(u, "helpdesk_role", "") in ("contact_center_team_leader", "team_leader", "supervisor")

                    or u.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")

                )

            )

            return _pick_best(cc_users), team, ou



        elif escalation_type == "contact_center_director":

            cc_ou = self.env["operating.unit"].sudo().search([("name", "ilike", "Contact Center")], limit=1)

            target_pool = ou_users | self._get_ou_users(cc_ou)

            cc_users = target_pool.filtered(

                lambda u: u.id != current_user.id and (

                    getattr(u, "helpdesk_role", "") in ("contact_center_director", "directorate", "director")

                    or u.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")

                )

            )

            return _pick_best(cc_users), team, ou



        elif escalation_type in ("front_line", "frontend"):

            users = ou_users.filtered(

                lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("front_line", "frontend", "support", "officer")

            )

            return _pick_best(users), team, ou



        elif escalation_type in ("back_line", "backend", "peer_backend"):

            backend_users = ou_users.filtered(

                lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("back_line", "backend", "fullstack", "database", "qa", "senior_principal")

            )

            return (_pick_best(backend_users) or _pick_best(ou_users.filtered(lambda u: u.id != current_user.id))), team, ou



        elif escalation_type in ("team_leader", "line_manager", "manager"):

            # 1. Check direct manager in hr.employee hierarchy if in target operating unit and not current assignee

            if current_emp and current_emp.parent_id and current_emp.parent_id.user_id:

                mgr = current_emp.parent_id.user_id

                if mgr != current_user and mgr in ou_users and not getattr(mgr, "is_on_leave", False):

                    return mgr, team, ou

            # 2. Check operating unit users with team leader / manager role

            leaders = ou_users.filtered(

                lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("team_leader", "supervisor", "manager")

            )

            best_leader = _pick_best(leaders)

            if best_leader:

                return best_leader, team, ou

            # 3. Check operating unit users with admin role or manager privileges

            admin_leaders = ou_users.filtered(

                lambda u: u.id != current_user.id and (getattr(u, "helpdesk_role", "") == "admin" or u.has_group("bunna_helpdesk.group_helpdesk_manager"))

            )

            best_admin = _pick_best(admin_leaders)

            if best_admin:

                return best_admin, team, ou

            # 4. Fallback to direct parent manager if in operating unit

            if current_emp and current_emp.parent_id and current_emp.parent_id.user_id:

                mgr = current_emp.parent_id.user_id

                if mgr != current_user and mgr in ou_users:

                    return mgr, team, ou

            return False, team, ou



        elif escalation_type in ("directorate", "director"):

            # Manager-based hierarchy: Director = Team Leader's actual manager (parent_id)

            _emp, mgr_user, _rel, err = ticket._get_manager_escalation_target(current_emp, "directorate")

            if err:

                return False, team, ou

            if mgr_user and not getattr(mgr_user, "is_on_leave", False):

                return mgr_user, team, ou

            # Fallback: walk up 1 level from current assignee

            if current_emp and current_emp.parent_id and current_emp.parent_id.user_id:

                parent_user = current_emp.parent_id.user_id

                if parent_user != current_user:

                    return parent_user, team, ou

            return False, team, ou



        elif escalation_type in ("team_leader_to_deputy_chief", "deputy_chief", "deputy_cto"):

            # Manager-based hierarchy: Deputy Chief / Chief = Director's actual manager

            esc_key = "team_leader_to_deputy_chief" if escalation_type == "team_leader_to_deputy_chief" else "deputy_chief"

            _emp, mgr_user, _rel, err = ticket._get_manager_escalation_target(current_emp, esc_key)

            if err:

                return False, team, ou

            if mgr_user and not getattr(mgr_user, "is_on_leave", False):

                return mgr_user, team, ou

            # Fallback: walk up hierarchy

            if current_emp:

                curr = current_emp

                steps = 2 if esc_key == "team_leader_to_deputy_chief" else 1

                for _step in range(steps):

                    if curr and curr.parent_id:

                        curr = curr.parent_id

                if curr and curr.user_id and curr.user_id != current_user:

                    return curr.user_id, team, ou

            return False, team, ou



        elif escalation_type in ("chief", "cido"):

            # Manager-based hierarchy: Chief = Director's or Deputy Chief's actual manager

            _emp, mgr_user, _rel, err = ticket._get_manager_escalation_target(current_emp, "chief")

            if err:

                return False, team, ou

            if mgr_user and not getattr(mgr_user, "is_on_leave", False):

                return mgr_user, team, ou

            # Fallback: walk up 1 level

            if current_emp and current_emp.parent_id and current_emp.parent_id.user_id:

                parent_user = current_emp.parent_id.user_id

                if parent_user != current_user:

                    return parent_user, team, ou

            return False, team, ou



        elif escalation_type in ("ceo", "other_ceo"):

            if ceo_user and not getattr(ceo_user, "is_on_leave", False):

                return ceo_user, team, ou

            if current_emp:

                curr = current_emp

                while curr and curr.parent_id:

                    curr = curr.parent_id

                if curr and curr.user_id and not getattr(curr.user_id, "is_on_leave", False):

                    return curr.user_id, team, ou

            ceo_role_users = self.env["res.users"].sudo().search([("helpdesk_role", "=", "ceo"), ("active", "=", True)])

            return (_pick_best(ceo_role_users) or ceo_user or False), team, ou



        # ── Cross-Operating Unit Track ────────────────────────────────────────

        elif escalation_type in ("other_work", "team_transfer"):

            target_o = ou

            if not target_ou and ticket.service_id and ticket.service_id.operating_unit_id:

                target_o = ticket.service_id.operating_unit_id

            target_ou_users = _get_ou_users(target_o)

            target_u = _pick_best(target_ou_users)

            target_t = self.env["helpdesk.ticket.team"].search([("operating_unit_id", "=", target_o.id)], limit=1) if target_o else team

            return target_u, target_t, target_o



        elif escalation_type == "other_officer":

            officers = ou_users.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("officer", "front_line", "frontend", "support"))

            return (_pick_best(officers) or _pick_best(ou_users)), team, ou



        elif escalation_type == "other_senior_principal":

            seniors = ou_users.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("senior_principal", "back_line", "backend", "fullstack"))

            return (_pick_best(seniors) or _pick_best(ou_users)), team, ou



        elif escalation_type == "other_manager_team_leader":

            managers = ou_users.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("team_leader", "manager", "supervisor"))

            target_u = _pick_best(managers) or (team.user_id if team and team.user_id else False)

            return target_u, team, ou



        elif escalation_type == "other_directorate":

            # 1. Check director users in the target operating unit

            dir_users = ou_users.filtered(lambda u: getattr(u, "helpdesk_role", "") in ("directorate", "director"))

            if dir_users:

                return _pick_best(dir_users), team, ou

            # 2. Check parent operating unit (e.g. Directorate OU above a Branch/District)

            dir_ou = ou.parent_unit if ou and ou.parent_unit else ticket.directorate_operating_unit_id

            if dir_ou and dir_ou != ou:

                parent_dir_users = _get_ou_users(dir_ou).filtered(lambda u: getattr(u, "helpdesk_role", "") in ("directorate", "director"))

                if parent_dir_users:

                    return _pick_best(parent_dir_users), team, dir_ou

            # 3. Manager-based hierarchy fallback: director = team leader's actual manager

            _emp, mgr_user, _rel, err = ticket._get_manager_escalation_target(current_emp, "other_directorate")

            if not err and mgr_user and not getattr(mgr_user, "is_on_leave", False):

                return mgr_user, team, ou

            return False, team, ou



        elif escalation_type == "other_deputy_chief_chief":

            # Manager-based: Chief = Director's actual manager in the other OU journey

            _emp, mgr_user, _rel, err = ticket._get_manager_escalation_target(current_emp, "other_deputy_chief_chief")

            if err:

                dep_chief_users = self.env["res.users"].sudo().search([("helpdesk_role", "in", ("deputy_chief", "deputy_cto")), ("active", "=", True)])

                return (_pick_best(dep_chief_users) or False), team, ou

            if mgr_user and not getattr(mgr_user, "is_on_leave", False):

                return mgr_user, team, ou

            return False, team, ou



        return False, team, ou



    def action_escalate(self):
        self.ensure_one()
        # Creator of a rejected ticket can re-escalate to re-route it
        if self.ticket_id.is_rejected or (self.ticket_id.stage_id and "reject" in (self.ticket_id.stage_id.name or "").lower()):
            if self.ticket_id.create_uid.id != self.env.uid and not self.env.user.has_group("bunna_helpdesk.group_helpdesk_manager"):
                raise ValidationError(_("Only the ticket creator or a Helpdesk Administrator can escalate a rejected ticket."))
        # Synchronize escalation_type from active journey proxy field
        if self.is_frontline and self.escalation_journey == "primary_journey" and self.escalation_type_primary_frontline:
            self.escalation_type = self.escalation_type_primary_frontline
        elif not self.is_director and self.escalation_journey == "primary_journey" and self.escalation_type_primary_non_director:
            self.escalation_type = self.escalation_type_primary_non_director
        elif not self.is_director and self.escalation_journey == "other_work_journey" and self.escalation_type_other_non_director:
            self.escalation_type = self.escalation_type_other_non_director
        elif self.is_director and self.escalation_journey == "primary_journey" and self.escalation_type_primary:
            self.escalation_type = self.escalation_type_primary
        elif self.is_director and self.escalation_journey == "other_work_journey" and self.escalation_type_other:
            self.escalation_type = self.escalation_type_other

        # Frontline restriction: Frontline users are not permitted to escalate to other operating units
        if self.is_frontline and (self.escalation_journey == "other_work_journey" or (self.target_operating_unit_id and self.ticket_id.operating_unit_id and self.target_operating_unit_id.id != self.ticket_id.operating_unit_id.id)):
            raise ValidationError(_("Frontline users are not permitted to escalate to other operating units. Frontline escalation is strictly restricted to the Primary Operating Unit Track (Back line Tier 2 or Team Leader Tier 3)."))

        # Strict security enforcement: Only users with Directorate privilege can escalate to Deputy Chief / Chief / CEO
        director_only_types = ("deputy_chief", "chief", "ceo", "team_leader_to_deputy_chief", "other_deputy_chief_chief", "other_ceo")
        if self.escalation_type in director_only_types:
            if not self.is_director:
                raise ValidationError(_("Only users with Directorate privilege can escalate to Deputy Chief, Chief Officer, or CEO."))

        if not self.reason:
            stage_name = dict(self.PRIMARY_ESCALATION_SELECTION).get(self.escalation_type, self.escalation_type) or "Next Stage"
            self.reason = _("Escalated to %s") % stage_name

        if self.escalation_journey == "other_work_journey" or (self.escalation_type and self.escalation_type.startswith("other_")):
            if not self.target_operating_unit_id:
                raise ValidationError(_("Please select the Target Responsible Work Unit before escalating to another Work Unit."))
            if not self.target_user_id:
                raise ValidationError(_("Please select an Assigned User (team member) in the target Work Unit before escalating."))

        # ── Server-side validation: ensure target user is in the eligible OU users ──
        if self.target_user_id and self.operating_unit_user_ids:
            if self.target_user_id not in self.operating_unit_user_ids:
                if self.escalation_journey == "primary_journey":
                    escalater_ous = self._get_escalater_operating_units(self.current_user_id or self.env.user, self.ticket_id)
                    ou_name = escalater_ous[:1].name if escalater_ous else _("the primary operating unit")
                else:
                    ou_name = (
                        self.target_operating_unit_id.name
                        if (self.escalation_journey == "other_work_journey" and self.target_operating_unit_id)
                        else (self.operating_unit_id.name or _("the responsible division operating unit"))
                    )
                raise ValidationError(_(
                    "The selected assignee '%s' is not a member of %s. "
                    "Please select a valid team member from the operating unit."
                ) % (self.target_user_id.name, ou_name))

        target_ou = self.target_operating_unit_id
        if self.escalation_journey == "primary_journey":
            escalater_ous = self._get_escalater_operating_units(self.current_user_id or self.env.user, self.ticket_id)
            if escalater_ous:
                target_ou = escalater_ous[:1]

        self.ticket_id.sudo().action_perform_hierarchical_escalation(
            escalation_type=self.escalation_type,
            target_user_id=self.target_user_id,
            target_team_id=self.target_team_id,
            target_operating_unit_id=target_ou,
            reason=self.reason,
            escalation_journey=self.escalation_journey,
        )

        if self.notify_customer:
            try:
                self.ticket_id.with_context(mail_notrack=True, bunna_skip_notifications=True).sudo().write({
                    "acceptance_sms_sent": False,
                    "acceptance_email_sent": False,
                })
                self.ticket_id._bunna_manual_notify("acceptance", channels=(self.notification_channel or "sms",))
            except Exception as exc:
                _logger.warning("Could not dispatch escalation customer notification: %s", exc)

        return {"type": "ir.actions.act_window_close"}
