from datetime import timedelta
from odoo import api, fields, models
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
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Members",
        relation="helpdesk_ticket_team_res_users_rel",
        column1="helpdesk_ticket_team_id",
        column2="res_users_id",
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
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Work Unit / Branch",
        help="The Bank work unit, branch, district, or HO directorate associated with this team.",
    )
    alias_id = fields.Many2one(
        comodel_name="mail.alias",
        string="Email",
        ondelete="restrict",
        required=True,
        help="The email address associated with \
                               this channel. New emails received will \
                               automatically create new tickets assigned \
                               to the channel.",
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
        default=False,
        help="Send a satisfaction survey to the customer when a ticket is closed.",
    )
    rating_template_id = fields.Many2one(
        comodel_name="mail.template",
        string="Rating Email Template",
        domain="[('model', '=', 'helpdesk.ticket')]",
    )

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

        # Prioritize agents on-duty / available
        available_members = all_members.filtered(
            lambda u: getattr(u, "agent_duty_status", "available") == "available"
        )
        members = available_members if available_members else all_members

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
    def retrieve_dashboard(self, period="all", team_id=False, user_id=False):
        """Retrieve comprehensive dashboard data for Bunna Bank Helpdesk OWL Dashboard."""
        domain = [("company_id", "in", self.env.companies.ids)]
        if team_id:
            domain.append(("team_id", "=", int(team_id)))
        if user_id:
            if int(user_id) == -1:
                domain.append(("user_id", "=", False))
            else:
                domain.append(("user_id", "=", int(user_id)))

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

        ticket_model = self.env["helpdesk.ticket"]
        all_tickets = ticket_model.search(domain)
        open_tickets = all_tickets.filtered(lambda t: not t.closed)

        total_count = len(all_tickets)
        open_count = len(open_tickets)
        unassigned_count = len(open_tickets.filtered(lambda t: not t.user_id))
        unattended_count = len(open_tickets.filtered(lambda t: t.unattended))
        urgent_count = len(open_tickets.filtered(lambda t: t.priority in ("2", "3")))
        sla_failed_count = len(all_tickets.filtered(lambda t: t.sla_status == "failed"))
        nbe_complaints_count = len(all_tickets.filtered(lambda t: t.is_nbe_complaint))
        escalated_count = len(all_tickets.filtered(lambda t: t.is_escalated))
        internal_count = len(all_tickets.filtered(lambda t: t.customer_type == "internal"))
        external_count = total_count - internal_count

        # Ratings
        ratings = self.env["rating.rating"].search([
            ("res_model", "=", "helpdesk.ticket"),
            ("res_id", "in", all_tickets.ids),
            ("consumed", "=", True),
        ])
        avg_rating = round(sum(ratings.mapped("rating")) / len(ratings), 1) if ratings else 5.0
        rating_count = len(ratings)

        # Total hours spent
        total_hours = round(sum(all_tickets.mapped("total_hours_spent")), 1)

        # Case Type breakdown
        case_type_labels = {
            "complaint": "Complaint (NBE)",
            "inquiry": "Inquiry",
            "service_request": "Service Request",
            "incident": "Incident",
            "technical_issue": "Technical Issue",
            "fraud_alert": "Fraud Alert",
            "suggestion": "Suggestion",
        }
        case_types_data = []
        for code, label in case_type_labels.items():
            c_count = len(all_tickets.filtered(lambda t: t.case_type == code))
            if c_count > 0 or code in ("complaint", "inquiry", "service_request"):
                case_types_data.append({
                    "code": code,
                    "label": label,
                    "count": c_count,
                    "percentage": round((c_count / total_count * 100), 1) if total_count else 0,
                })

        # Channel breakdown
        channel_labels = {
            "phone": "Phone / IVR",
            "email": "Email",
            "tidio_chat": "Tidio Chat",
            "web_portal": "Web Portal",
            "telegram": "Telegram",
            "whatsapp": "WhatsApp",
            "facebook": "Facebook Messenger",
            "mobile_banking": "Mobile Banking",
            "branch_walkin": "Branch Walk-in",
        }
        channels_data = []
        for code, label in channel_labels.items():
            ch_count = len(all_tickets.filtered(lambda t: t.channel_type == code))
            if ch_count > 0 or code in ("phone", "email", "tidio_chat"):
                channels_data.append({
                    "code": code,
                    "label": label,
                    "count": ch_count,
                    "percentage": round((ch_count / total_count * 100), 1) if total_count else 0,
                })

        # Stages breakdown
        stages_data = []
        applicable_stages = self.env["helpdesk.ticket.stage"].search([])
        for stage in applicable_stages:
            count = len(all_tickets.filtered(lambda t: t.stage_id == stage))
            if count > 0 or not stage.closed:
                stages_data.append({
                    "id": stage.id,
                    "name": stage.name,
                    "count": count,
                    "closed": stage.closed,
                    "percentage": round((count / total_count * 100), 1) if total_count else 0,
                })

        # Priority breakdown
        priority_labels = {"0": "Low", "1": "Medium", "2": "High", "3": "Very High"}
        priorities_data = []
        for p_code in ["0", "1", "2", "3"]:
            count = len(open_tickets.filtered(lambda t: t.priority == p_code))
            priorities_data.append({
                "code": p_code,
                "label": priority_labels[p_code],
                "count": count,
                "percentage": round((count / open_count * 100), 1) if open_count else 0,
            })

        # Teams list for filter dropdown
        teams_data = [{"id": 0, "name": "All Teams"}]
        for team in self.search([("company_id", "in", self.env.companies.ids)]):
            teams_data.append({"id": team.id, "name": team.name})

        # Users list for individual filter dropdown
        all_candidate_users = self.env["res.users"].search([("share", "=", False)], order="name")
        users_data = [{"id": u.id, "name": u.name} for u in all_candidate_users]

        # Recent 5 urgent / open tickets
        recent_tickets_data = []
        urgent_recent = open_tickets.sorted(key=lambda t: (t.priority, t.create_date), reverse=True)[:5]
        for t in urgent_recent:
            recent_tickets_data.append({
                "id": t.id,
                "number": t.number,
                "name": t.name,
                "partner_name": t.partner_name or (t.partner_id.name if t.partner_id else "Guest"),
                "priority": t.priority,
                "priority_label": priority_labels.get(t.priority, "Normal"),
                "stage_name": t.stage_id.name if t.stage_id else "",
                "sla_status": t.sla_status or "in_progress",
                "assigned_user": t.user_id.name if t.user_id else "Unassigned",
            })

        # Structured Pie & Donut Chart data (Parts of a whole / Proportional breakdowns)
        pie_charts = {
            "case_types": {
                "title": "Tickets by Case Type",
                "labels": [ct["label"] for ct in case_types_data if ct["count"] > 0],
                "data": [ct["count"] for ct in case_types_data if ct["count"] > 0],
                "codes": [ct["code"] for ct in case_types_data if ct["count"] > 0],
            },
            "priorities": {
                "title": "Tickets by Priority / Severity",
                "labels": [pr["label"] for pr in priorities_data if pr["count"] > 0],
                "data": [pr["count"] for pr in priorities_data if pr["count"] > 0],
                "codes": [pr["code"] for pr in priorities_data if pr["count"] > 0],
            },
            "customer_types": {
                "title": "Branch vs External Customer Breakdown",
                "labels": ["Internal Branch / Staff", "External Client"],
                "data": [internal_count, external_count],
                "codes": ["internal", "external"],
            },
            "channels": {
                "title": "Tickets by Omnichannel Source",
                "labels": [ch["label"] for ch in channels_data if ch["count"] > 0],
                "data": [ch["count"] for ch in channels_data if ch["count"] > 0],
                "codes": [ch["code"] for ch in channels_data if ch["count"] > 0],
            },
        }

        # Structured Bar & Column Chart data (Compare values across categories)
        team_bar_labels = []
        team_bar_open = []
        team_bar_closed = []
        team_bar_ids = []
        for team in self.search([("company_id", "in", self.env.companies.ids)]):
            t_tickets = all_tickets.filtered(lambda t: t.team_id == team)
            t_open_cnt = len(t_tickets.filtered(lambda t: not t.closed))
            t_closed_cnt = len(t_tickets) - t_open_cnt
            team_bar_labels.append(team.name)
            team_bar_open.append(t_open_cnt)
            team_bar_closed.append(t_closed_cnt)
            team_bar_ids.append(team.id)

        bar_charts = {
            "teams": {
                "title": "Team Workload Comparison",
                "labels": team_bar_labels,
                "series_open": team_bar_open,
                "series_closed": team_bar_closed,
                "ids": team_bar_ids,
            },
            "channels": {
                "title": "Omnichannel Traffic Comparison",
                "labels": [ch["label"] for ch in channels_data if ch["count"] > 0],
                "data": [ch["count"] for ch in channels_data if ch["count"] > 0],
                "codes": [ch["code"] for ch in channels_data if ch["count"] > 0],
            },
            "stages": {
                "title": "Pipeline Stage Comparison",
                "labels": [st["name"] for st in stages_data if st["count"] > 0],
                "data": [st["count"] for st in stages_data if st["count"] > 0],
                "ids": [st["id"] for st in stages_data if st["count"] > 0],
            },
        }

        # Trend Analysis data
        trend_labels = []
        trend_created = []
        trend_closed = []
        trend_breached = []

        base_trend_domain = [("company_id", "in", self.env.companies.ids)]
        if team_id:
            base_trend_domain.append(("team_id", "=", int(team_id)))
        if user_id:
            if int(user_id) == -1:
                base_trend_domain.append(("user_id", "=", False))
            else:
                base_trend_domain.append(("user_id", "=", int(user_id)))

        if period == "today":
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(8):
                b_start = today_start + timedelta(hours=i * 3)
                b_end = b_start + timedelta(hours=3)
                trend_labels.append(b_start.strftime("%H:%M"))
                c_cnt = ticket_model.search_count(base_trend_domain + [
                    ("create_date", ">=", b_start),
                    ("create_date", "<", b_end),
                ])
                cl_cnt = ticket_model.search_count(base_trend_domain + [
                    ("stage_id.closed", "=", True),
                    ("last_stage_update", ">=", b_start),
                    ("last_stage_update", "<", b_end),
                ])
                br_cnt = ticket_model.search_count(base_trend_domain + [
                    ("sla_status", "=", "failed"),
                    ("create_date", ">=", b_start),
                    ("create_date", "<", b_end),
                ])
                trend_created.append(c_cnt)
                trend_closed.append(cl_cnt)
                trend_breached.append(br_cnt)
        elif period == "week":
            start_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(7):
                d_start = start_week + timedelta(days=i)
                d_end = d_start + timedelta(days=1)
                trend_labels.append(d_start.strftime("%a %d %b"))
                c_cnt = ticket_model.search_count(base_trend_domain + [
                    ("create_date", ">=", d_start),
                    ("create_date", "<", d_end),
                ])
                cl_cnt = ticket_model.search_count(base_trend_domain + [
                    ("stage_id.closed", "=", True),
                    ("last_stage_update", ">=", d_start),
                    ("last_stage_update", "<", d_end),
                ])
                br_cnt = ticket_model.search_count(base_trend_domain + [
                    ("sla_status", "=", "failed"),
                    ("create_date", ">=", d_start),
                    ("create_date", "<", d_end),
                ])
                trend_created.append(c_cnt)
                trend_closed.append(cl_cnt)
                trend_breached.append(br_cnt)
        elif period == "month":
            start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            cur = start_month
            while cur <= now:
                nxt = cur + timedelta(days=1)
                trend_labels.append(cur.strftime("%d %b"))
                c_cnt = ticket_model.search_count(base_trend_domain + [
                    ("create_date", ">=", cur),
                    ("create_date", "<", nxt),
                ])
                cl_cnt = ticket_model.search_count(base_trend_domain + [
                    ("stage_id.closed", "=", True),
                    ("last_stage_update", ">=", cur),
                    ("last_stage_update", "<", nxt),
                ])
                br_cnt = ticket_model.search_count(base_trend_domain + [
                    ("sla_status", "=", "failed"),
                    ("create_date", ">=", cur),
                    ("create_date", "<", nxt),
                ])
                trend_created.append(c_cnt)
                trend_closed.append(cl_cnt)
                trend_breached.append(br_cnt)
                cur = nxt
        else: # "all"
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            for i in range(13, -1, -1):
                d_start = today_start - timedelta(days=i)
                d_end = d_start + timedelta(days=1)
                trend_labels.append(d_start.strftime("%d %b"))
                c_cnt = ticket_model.search_count(base_trend_domain + [
                    ("create_date", ">=", d_start),
                    ("create_date", "<", d_end),
                ])
                cl_cnt = ticket_model.search_count(base_trend_domain + [
                    ("stage_id.closed", "=", True),
                    ("last_stage_update", ">=", d_start),
                    ("last_stage_update", "<", d_end),
                ])
                br_cnt = ticket_model.search_count(base_trend_domain + [
                    ("sla_status", "=", "failed"),
                    ("create_date", ">=", d_start),
                    ("create_date", "<", d_end),
                ])
                trend_created.append(c_cnt)
                trend_closed.append(cl_cnt)
                trend_breached.append(br_cnt)

        trend_data = {
            "labels": trend_labels,
            "created": trend_created,
            "closed": trend_closed,
            "breached": trend_breached,
            "total_created": sum(trend_created),
            "total_closed": sum(trend_closed),
            "total_breached": sum(trend_breached),
        }

        return {
            "kpi": {
                "total": total_count,
                "open": open_count,
                "unassigned": unassigned_count,
                "unattended": unattended_count,
                "urgent": urgent_count,
                "sla_failed": sla_failed_count,
                "nbe_complaints": nbe_complaints_count,
                "escalated": escalated_count,
                "internal": internal_count,
                "external": external_count,
                "rating_avg": avg_rating,
                "rating_count": rating_count,
                "total_hours": total_hours,
            },
            "stages": stages_data,
            "priorities": priorities_data,
            "case_types": case_types_data,
            "channels": channels_data,
            "teams": teams_data,
            "users": users_data,
            "recent_tickets": recent_tickets_data,
            "company_name": self.env.company.name or "Bunna Bank",
            "trend": trend_data,
            "pie_charts": pie_charts,
            "bar_charts": bar_charts,
        }

    @api.model
    def action_export_dashboard_excel(self, period="all", team_id=0, user_id=0):
        """Export comprehensive Helpdesk Dashboard executive metrics & ticket dataset to Bunna-branded Excel."""
        import base64
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))

        data = self.retrieve_dashboard(period=period, team_id=team_id or False, user_id=user_id or False)
        domain = [("company_id", "in", self.env.companies.ids)]
        if team_id:
            domain.append(("team_id", "=", int(team_id)))
        if user_id:
            if int(user_id) == -1:
                domain.append(("user_id", "=", False))
            else:
                domain.append(("user_id", "=", int(user_id)))

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
        tickets = self.env["helpdesk.ticket"].search(domain, order="id desc")

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
            "Case Type", "Service Family", "Service", "Assigned Team", "Assigned Agent",
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

