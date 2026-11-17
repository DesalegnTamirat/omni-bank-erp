# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class OperatingUnit(models.Model):
    _inherit = "operating.unit"

    helpdesk_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Helpdesk Team / Service Provider",
        compute="_compute_helpdesk_team_id",
        store=False,
        help="Helpdesk team automatically created and maintained for this Operating Unit.",
    )
    helpdesk_team_count = fields.Integer(
        string="Helpdesk Teams Count",
        compute="_compute_helpdesk_team_count",
    )
    child_unit_ids = fields.One2many(
        comodel_name="operating.unit",
        inverse_name="parent_unit",
        string="Child Operating Units",
        help="Subordinate divisions, districts, or branch units under this Operating Unit.",
    )

    @api.depends("name")
    def _compute_helpdesk_team_id(self):
        Team = self.env["helpdesk.ticket.team"].sudo()
        for ou in self:
            team = Team.search([("operating_unit_id", "=", ou.id)], limit=1)
            ou.helpdesk_team_id = team.id if team else False

    def _compute_helpdesk_team_count(self):
        Team = self.env["helpdesk.ticket.team"].sudo()
        for ou in self:
            ou.helpdesk_team_count = Team.search_count([("operating_unit_id", "=", ou.id)])

    def init(self):
        super().init()
        try:
            self.env.cr.execute("ALTER TABLE operating_unit ADD COLUMN IF NOT EXISTS helpdesk_team_id integer;")
        except Exception:
            pass
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_helpdesk_teams()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("name", "active", "company_id", "work_unit_type", "user_ids", "parent_unit")):
            self._sync_helpdesk_teams()
        return res

    def _sync_helpdesk_teams(self):
        """Automatically create or update a corresponding helpdesk.ticket.team for each Operating Unit and link parent hierarchy."""
        Team = self.env["helpdesk.ticket.team"].sudo()
        
        # Pass 1: Ensure teams exist for all units in self and their parent units
        all_units_to_sync = self.env["operating.unit"]
        for ou in self:
            curr = ou
            visited = set()
            while curr and curr.id not in visited:
                visited.add(curr.id)
                all_units_to_sync |= curr
                curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False

        for ou in all_units_to_sync:
            if not ou.name:
                continue
            team = Team.search([("operating_unit_id", "=", ou.id)], limit=1)
            if not team:
                # Check if an unlinked team with matching name already exists
                team = Team.search([("operating_unit_id", "=", False), ("name", "=", ou.name)], limit=1)
                if team:
                    team.operating_unit_id = ou.id

            tier = "level_2_backoffice"
            work_type = getattr(ou, "work_unit_type", False)
            if work_type in ("branch", "sub_branch"):
                tier = "district_branch"
            elif ou.name and any(kw in ou.name.lower() for kw in ("contact center", "call center", "cc")):
                tier = "level_1_cc"
            elif ou.name and any(kw in ou.name.lower() for kw in ("ethics", "compliance", "nbe")):
                tier = "ethics_compliance"
            elif ou.name and any(kw in ou.name.lower() for kw in ("ceo", "president", "vp", "executive")):
                tier = "level_3_executive"

            target_company_id = ou.company_id.id if ou.company_id else self.env.company.id

            if not team:
                team = Team.create({
                    "name": ou.name,
                    "operating_unit_id": ou.id,
                    "company_id": target_company_id,
                    "active": ou.active,
                    "team_tier": tier,
                })
            else:
                vals = {}
                if team.name != ou.name:
                    vals["name"] = ou.name
                if target_company_id and team.company_id.id != target_company_id:
                    vals["company_id"] = target_company_id
                if team.active != ou.active:
                    vals["active"] = ou.active
                if vals:
                    team.write(vals)

            # Ensure members are synchronized from Operating Unit
            team._compute_user_ids()

        # Pass 2: Link parent_id for each team matching ou.parent_unit
        for ou in all_units_to_sync:
            team = Team.search([("operating_unit_id", "=", ou.id)], limit=1)
            if not team:
                continue
            if ou.parent_unit:
                parent_team = Team.search([("operating_unit_id", "=", ou.parent_unit.id)], limit=1)
                if not parent_team:
                    parent_team = Team.create({
                        "name": ou.parent_unit.name,
                        "operating_unit_id": ou.parent_unit.id,
                        "company_id": ou.parent_unit.company_id.id if ou.parent_unit.company_id else self.env.company.id,
                        "active": ou.parent_unit.active,
                    })
                if team.parent_id != parent_team:
                    team.parent_id = parent_team
            else:
                if team.parent_id and team.parent_id.operating_unit_id:
                    team.parent_id = False

    @api.model
    def sync_all_employee_operating_units(self):
        """Ensure all operating units assigned to HR employees, plus all their parent units, exist and have linked teams."""
        emp_model = self.env["hr.employee"].sudo()
        emp_ous = emp_model.search([]).mapped("default_operating_unit_id")
        if hasattr(emp_model, "operating_unit_ids"):
            emp_ous |= emp_model.search([]).mapped("operating_unit_ids")
        if hasattr(emp_model, "operating_unit_id"):
            emp_ous |= emp_model.search([]).mapped("operating_unit_id")

        all_units = self.env["operating.unit"]
        for ou in emp_ous.filtered(lambda o: o.active):
            curr = ou
            visited = set()
            while curr and curr.id not in visited:
                visited.add(curr.id)
                all_units |= curr
                curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False

        if all_units:
            all_units._sync_helpdesk_teams()
        return True
