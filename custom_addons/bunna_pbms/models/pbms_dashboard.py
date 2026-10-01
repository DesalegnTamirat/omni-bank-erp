# -*- coding: utf-8 -*-
from odoo import models, api


class PbmsDashboard(models.AbstractModel):
    """RPC surface for the OWL dashboard. Deliberately thin: every
    method is one or two read_group calls (SQL-side GROUP BY), never a
    browse-and-loop over full recordsets, so the dashboard stays fast
    regardless of how many branches/lines exist.
    """
    _name = "pbms.dashboard"
    _description = "PBMS Dashboard Data Provider"

    @api.model
    def get_submission_status(self, cycle_id):
        """Submission/approval progress per planning category and org-unit
        type, aggregated from the single unified model in one read_group."""
        domain = [("cycle_id", "=", cycle_id)] if cycle_id else []
        category_labels = dict(self.env["pbms.planning.category"]._fields["category"].selection)
        groups = self.env["pbms.planning.category"].read_group(
            domain, ["state"], ["category", "org_unit_type", "state"], lazy=False,
        )
        result = []
        per_category = {}
        for g in groups:
            cat = g.get("category") or "unknown"
            unit_type = g.get("org_unit_type") or "unknown"
            per_category.setdefault(cat, {}).setdefault(unit_type, {})[g["state"]] = g["__count"]
        for cat, label in category_labels.items():
            result.append({
                "model": cat,
                "label": label,
                "counts": per_category.get(cat, {}),
            })
        return result

    @api.model
    def get_kpi_summary(self, cycle_id):
        """Bank-level annual-total by format and state, from the
        consolidation SQL view - a single indexed GROUP BY, no Python
        aggregation of individual plan lines."""
        domain = [("cycle_id", "=", cycle_id)] if cycle_id else []
        groups = self.env["pbms.consolidation.line"].read_group(
            domain, ["annual_total:sum"], ["source_model", "state"], lazy=False,
        )
        return [{
            "source_model": g["source_model"],
            "state": g["state"],
            "annual_total": g["annual_total"],
        } for g in groups]

    @api.model
    def get_cycles(self):
        cycles = self.env["pbms.planning.cycle"].search_read(
            [], ["id", "name", "state"], order="date_start desc", limit=10,
        )
        return cycles

    @api.model
    def get_dashboard_data(self, cycle_id=None):
        """Batched RPC endpoint for OWL dashboard:
        Fetches cycles, resolves active cycle, submission status, and KPI summary
        in a single client-server network round-trip.
        """
        cycles = self.get_cycles()
        active_cycle_id = cycle_id
        if not active_cycle_id and cycles:
            open_cycle = next((c for c in cycles if c.get("state") in ("budget_call", "open")), None)
            active_cycle_id = open_cycle["id"] if open_cycle else cycles[0]["id"]

        submission = self.get_submission_status(active_cycle_id) if active_cycle_id else []
        kpi = self.get_kpi_summary(active_cycle_id) if active_cycle_id else []
        return {
            "cycles": cycles,
            "active_cycle_id": active_cycle_id,
            "submission": submission,
            "kpi": kpi,
        }

