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
        """Submission/approval progress per org-unit type and state,
        for the four monthly-grid + two itemized formats, in one call
        each (read_group), instead of one query per branch."""
        domain = [("cycle_id", "=", cycle_id)] if cycle_id else []
        models_to_check = [
            ("pbms.deposit.plan", "Deposit Mobilization"),
            ("pbms.customer.base.plan", "Customer Base"),
            ("pbms.fx.plan", "FX Mobilization"),
            ("pbms.digital.banking.plan", "Digital Banking"),
            ("pbms.general.expense.plan", "General Expense"),
            ("pbms.manpower.plan", "Manpower"),
            ("pbms.fixed.asset.plan", "Fixed Asset"),
        ]
        result = []
        for model_name, label in models_to_check:
            groups = self.env[model_name].read_group(
                domain, ["state"], ["org_unit_type", "state"], lazy=False,
            )
            counts = {}
            for g in groups:
                unit_type = g.get("org_unit_type") or "unknown"
                counts.setdefault(unit_type, {})[g["state"]] = g["__count"]
            result.append({"model": model_name, "label": label, "counts": counts})
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
