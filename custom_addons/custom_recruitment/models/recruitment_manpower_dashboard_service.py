# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class RecruitmentManpowerDashboardService(models.AbstractModel):
    _name = "recruitment.manpower.dashboard.service"
    _description = "Recruitment Request & Manpower Tracking Dashboard Service"

    @api.model
    def get_filter_hierarchy(self):
        """Return structured filter options for Bank-wide, Department (Head Office & Districts), and Work Units."""
        Cycle = self.env.get("pbms.planning.cycle")
        OU = self.env["operating.unit"]

        cycles = []
        if Cycle:
            active_cycles = Cycle.search([("active", "=", True)], order="id desc")
            cycles = [{"id": c.id, "name": c.name, "is_current": getattr(c, "is_current", False)} for c in active_cycles]

        # 1. Department List: Head Office Directorates + All District Offices
        dept_units = OU.search([
            ("active", "=", True),
            "|",
            ("work_unit_type", "in", ["district_office", "head_office", "department"]),
            ("parent_unit", "=", False),
        ], order="work_unit_type desc, name asc")

        departments = []
        for d in dept_units:
            type_label = "Head Office" if d.work_unit_type == "head_office" else ("District" if d.work_unit_type == "district_office" else "Department")
            departments.append({
                "id": d.id,
                "name": d.name,
                "code": d.code or d.sol_id or "",
                "type": type_label,
                "display_name": f"[{type_label}] {d.name}",
            })

        # 2. Work Unit List: All operational units / branches
        all_work_units = OU.search([("active", "=", True)], order="name asc")
        work_units = []
        for u in all_work_units:
            work_units.append({
                "id": u.id,
                "name": u.name,
                "sol_id": u.sol_id or "",
                "parent_id": u.parent_unit.id if u.parent_unit else False,
                "work_unit_type": u.work_unit_type or "",
                "display_name": f"{u.name} ({u.sol_id})" if u.sol_id else u.name,
            })

        return {
            "cycles": cycles,
            "departments": departments,
            "work_units": work_units,
        }

    @api.model
    def get_dashboard_metrics(self, level="corporate", department_id=None, workunit_id=None, cycle_id=None, search_term=""):
        """Calculate aggregated manpower & recruitment metrics based on the 2-level filter:
        - level='corporate' (Bank-wide): aggregates the whole bank across all work units.
        - level='department': aggregates all units under the selected Head Office Directorate or District.
        - level='workunit': aggregates specifically for the selected Work Unit / Branch.
        """
        OU = self.env["operating.unit"]
        OUJobPos = self.env["operating.unit.job.position"]
        RecRequest = self.env["recruitment.request"]

        # 1. Determine target operating unit IDs
        target_ou_domain = [("active", "=", True)]

        if level == "workunit" and workunit_id:
            target_ou_domain.append(("id", "=", int(workunit_id)))
        elif level == "department" and department_id:
            dept_id = int(department_id)
            target_ou_domain += [
                "|",
                ("id", "=", dept_id),
                ("parent_unit", "=", dept_id),
            ]
        # 'corporate' includes all units without extra filter

        matched_ous = OU.search(target_ou_domain)
        matched_ou_ids = matched_ous.ids

        if not matched_ou_ids:
            return self._empty_dashboard_response()

        # 2. Query operating.unit.job.position records
        pos_domain = [
            ("operating_unit_id", "in", matched_ou_ids),
            ("active", "=", True),
        ]
        if search_term:
            pos_domain.append("|")
            pos_domain.append(("job_position_id.name", "ilike", search_term))
            pos_domain.append(("operating_unit_id.name", "ilike", search_term))

        establishment_lines = OUJobPos.search(pos_domain, order="operating_unit_id, job_position_id")

        # 3. Query in-flight recruitment requests
        rec_req_domain = [
            ("operating_unit_id", "in", matched_ou_ids),
            ("request_type", "=", "planned"),
            ("state", "in", ["submitted", "under_review", "approved"]),
        ]
        rec_requests = RecRequest.search(rec_req_domain)
        inflight_map = {}
        for req in rec_requests:
            key = (req.operating_unit_id.id, req.job_position_id.id if req.job_position_id else False)
            inflight_map[key] = inflight_map.get(key, 0) + (req.required_headcount or 0)

        # 4. Process lines and compute aggregated metrics
        table_rows = []
        total_authorized = 0
        total_baseline = 0
        total_approved_plan = 0
        total_active = 0
        total_vacant = 0
        total_inflight = 0
        total_lateral = 0
        total_replacement = 0
        total_promotion = 0
        total_resignation = 0

        unit_summary = {}

        for line in establishment_lines:
            ou = line.operating_unit_id
            job = line.job_position_id
            grade = line.job_grade_id

            base = line.baseline_count or 0
            plan = line.approved_plan_count or 0
            tot = line.total_headcount or (base + plan)
            act = line.active_employee_count or 0
            vac = line.vacant_position_count or (tot - act)

            key = (ou.id, job.id if job else False)
            inflight = inflight_map.get(key, 0)

            lat = line.lateral_count or 0
            rep = line.replacement_count or 0
            prm = line.promotion_count or 0
            res = line.resignation_count or 0

            # Running totals
            total_authorized += tot
            total_baseline += base
            total_approved_plan += plan
            total_active += act
            if vac > 0:
                total_vacant += vac
            total_inflight += inflight
            total_lateral += lat
            total_replacement += rep
            total_promotion += prm
            total_resignation += res

            # Determine badge status
            if vac > 0:
                status_type = "danger"
                status_label = _("%s Vacant") % vac
            elif vac == 0:
                status_type = "success"
                status_label = _("Fully Staffed")
            else:
                status_type = "info"
                status_label = _("+%s Surplus") % abs(vac)

            table_rows.append({
                "id": line.id,
                "operating_unit_id": ou.id,
                "operating_unit_name": ou.name,
                "district_name": ou.parent_unit.name if ou.parent_unit else (ou.name if ou.work_unit_type in ["district_office", "head_office"] else "-"),
                "sol_id": ou.sol_id or "",
                "job_position_id": job.id if job else False,
                "job_position_name": job.name if job else _("Unassigned"),
                "grade_name": grade.grade_name if grade and hasattr(grade, "grade_name") else (grade.name if grade else "-"),
                "baseline_count": base,
                "approved_plan_count": plan,
                "total_headcount": tot,
                "active_employee_count": act,
                "vacant_position_count": vac,
                "inflight_recruitment": inflight,
                "status_type": status_type,
                "status_label": status_label,
                "lateral_count": lat,
                "replacement_count": rep,
                "promotion_count": prm,
                "resignation_count": res,
            })

            # Unit aggregation for bar chart
            if ou.name not in unit_summary:
                unit_summary[ou.name] = {"total": 0, "active": 0, "vacant": 0}
            unit_summary[ou.name]["total"] += tot
            unit_summary[ou.name]["active"] += act
            if vac > 0:
                unit_summary[ou.name]["vacant"] += vac

        # Sort top units with highest vacancies for chart (up to top 10)
        sorted_units = sorted(unit_summary.items(), key=lambda x: x[1]["vacant"], reverse=True)[:10]
        unit_labels = [u[0] for u in sorted_units]
        unit_totals = [u[1]["total"] for u in sorted_units]
        unit_actives = [u[1]["active"] for u in sorted_units]
        unit_vacants = [u[1]["vacant"] for u in sorted_units]

        # Calculate fulfillment rate
        fulfillment_rate = round((total_active / total_authorized * 100), 1) if total_authorized > 0 else 100.0
        vacancy_rate = round((total_vacant / total_authorized * 100), 1) if total_authorized > 0 else 0.0

        uninitiated_gap = max(0, total_vacant - total_inflight)

        return {
            "matched_ou_ids": matched_ou_ids,
            "summary": {
                "total_authorized": total_authorized,
                "total_baseline": total_baseline,
                "total_approved_plan": total_approved_plan,
                "total_active": total_active,
                "total_vacant": total_vacant,
                "total_inflight": total_inflight,
                "uninitiated_gap": uninitiated_gap,
                "total_lateral": total_lateral,
                "total_replacement": total_replacement,
                "total_promotion": total_promotion,
                "total_resignation": total_resignation,
                "fulfillment_rate": fulfillment_rate,
                "vacancy_rate": vacancy_rate,
                "total_positions_tracked": len(table_rows),
            },
            "table_rows": table_rows,
            "charts": {
                "fulfillment_donut": {
                    "labels": [_("Active Staff"), _("In-Flight Recruitment"), _("Uninitiated Vacancy Gap")],
                    "data": [total_active, total_inflight, uninitiated_gap],
                    "colors": ["#425727", "#c17540", "#541718"],
                },
                "unit_comparison_bar": {
                    "labels": unit_labels,
                    "totals": unit_totals,
                    "actives": unit_actives,
                    "vacants": unit_vacants,
                },
            },
        }

    @api.model
    def _empty_dashboard_response(self):
        return {
            "matched_ou_ids": [],
            "summary": {
                "total_authorized": 0, "total_baseline": 0, "total_approved_plan": 0,
                "total_active": 0, "total_vacant": 0, "total_inflight": 0, "uninitiated_gap": 0,
                "total_lateral": 0, "total_replacement": 0, "total_promotion": 0, "total_resignation": 0,
                "fulfillment_rate": 0.0, "vacancy_rate": 0.0, "total_positions_tracked": 0,
            },
            "table_rows": [],
            "charts": {
                "fulfillment_donut": {"labels": [], "data": [], "colors": []},
                "unit_comparison_bar": {"labels": [], "totals": [], "actives": [], "vacants": []},
            },
        }
