# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class RecruitmentManpowerDashboardService(models.AbstractModel):
    _name = "recruitment.manpower.dashboard.service"
    _description = "Recruitment Request & Manpower Tracking Dashboard Service"

    @api.model
    def get_filter_hierarchy(self):
        """Return structured filter options for Bank-wide, Department (Head Office & Districts), and Work Units."""
        Cycle = self.env["pbms.planning.cycle"] if "pbms.planning.cycle" in self.env else None
        OU = self.env["operating.unit"]

        cycles = []
        if Cycle is not None:
            active_cycles = Cycle.search([("active", "=", True)], order="id desc")
            for c in active_cycles:
                is_curr = getattr(c, "is_current", False) or (getattr(c, "state", "") == "open")
                cycles.append({
                    "id": c.id,
                    "name": c.name,
                    "is_current": is_curr,
                })
            # Ensure at least the top active cycle is flagged current if none had state open
            if cycles and not any(c["is_current"] for c in cycles):
                cycles[0]["is_current"] = True

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
                "code": (getattr(d.code, "name", False) or getattr(d.code, "code", False) or "") if d.code else (d.sol_id or ""),
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
    def _ensure_operating_unit_positions(self, matched_ou_ids):
        """Ensure operating.unit.job.position exists for all active employees
        and approved manpower plan lines within the matched operating units."""
        if not matched_ou_ids:
            return
        OUJobPos = self.env["operating.unit.job.position"]
        existing = OUJobPos.search([("operating_unit_id", "in", matched_ou_ids)])
        existing_pairs = {(p.operating_unit_id.id, p.job_position_id.id) for p in existing}

        ou_tuple = tuple(matched_ou_ids)
        self.env.cr.execute("""
            SELECT DISTINCT
                v.operating_unit_id AS ou_id,
                v.job_id AS job_id
            FROM hr_version v
            WHERE v.active = true
              AND v.operating_unit_id IN %s
              AND v.operating_unit_id IS NOT NULL
              AND v.job_id IS NOT NULL
        """, (ou_tuple,))

        all_pairs = self.env.cr.fetchall()
        to_create = [
            {"operating_unit_id": ou_id, "job_position_id": job_id, "active": True}
            for ou_id, job_id in all_pairs
            if ou_id in matched_ou_ids and (ou_id, job_id) not in existing_pairs
        ]

        if to_create:
            OUJobPos.sudo().create(to_create)

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
            selected_ou = OU.browse(dept_id)
            if selected_ou and selected_ou.department:
                target_ou_domain += [
                    "|", "|",
                    ("id", "=", dept_id),
                    ("parent_unit", "=", dept_id),
                    ("department", "=", selected_ou.department.id),
                ]
            else:
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

        # Ensure operating.unit.job.position exists for all active employees and approved plans
        self._ensure_operating_unit_positions(matched_ou_ids)

        # 2. Query operating.unit.job.position records
        pos_domain = [
            ("operating_unit_id", "in", matched_ou_ids),
            ("active", "=", True),
        ]
        if search_term:
            pos_domain.append("|")
            pos_domain.append(("job_position_id.name", "ilike", search_term))
            pos_domain.append(("operating_unit_id.name", "ilike", search_term))

        raw_lines = OUJobPos.search(pos_domain, order="operating_unit_id, job_position_id")
        seen_keys = set()
        establishment_lines = []
        for line in raw_lines:
            k = (line.operating_unit_id.id, line.job_position_id.id if line.job_position_id else False)
            if k not in seen_keys:
                seen_keys.add(k)
                establishment_lines.append(line)

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

        # 4. Fetch Approved Plan from pbms_plan_category_line (display_approved_annual_total)
        # Default cycle must be active cycle if no cycle selected
        Cycle = self.env["pbms.planning.cycle"] if "pbms.planning.cycle" in self.env else None
        eff_cycle_id = int(cycle_id) if cycle_id else False
        if not eff_cycle_id and Cycle is not None:
            active_c = Cycle.search([("active", "=", True)], order="id desc")
            open_c = active_c.filtered(lambda c: getattr(c, "state", "") == "open")
            target_c = open_c[:1] or active_c[:1]
            if target_c:
                eff_cycle_id = target_c.id

        PbmsPlanLine = self.env["pbms.plan.category.line"] if "pbms.plan.category.line" in self.env else None
        approved_plan_map = {}
        if PbmsPlanLine is not None:
            plan_domain = [
                ("line_type", "=", "manpower"),
                ("org_unit_id", "in", matched_ou_ids),
            ]
            if eff_cycle_id:
                plan_domain.append(("cycle_id", "=", eff_cycle_id))
            plan_lines = PbmsPlanLine.search(plan_domain)
            if not plan_lines and eff_cycle_id:
                # Fallback to lines across cycles if current active cycle has no specific entries
                plan_lines = PbmsPlanLine.search([
                    ("line_type", "=", "manpower"),
                    ("org_unit_id", "in", matched_ou_ids),
                ])
            for pl in plan_lines:
                if pl.org_unit_id and pl.job_id:
                    k = (pl.org_unit_id.id, pl.job_id.id)
                    val = getattr(pl, "display_approved_annual_total", None)
                    if val is None:
                        val = getattr(pl, "approved_annual_total", 0.0) or (pl.quantity or 0.0)
                    approved_plan_map[k] = approved_plan_map.get(k, 0.0) + (val or 0.0)

        # 5. Fetch Active Employees strictly from hr_version (v.active = true)
        ou_tuple = tuple(matched_ou_ids)
        self.env.cr.execute("""
            SELECT 
                v.operating_unit_id AS ou_id,
                v.job_id AS job_id,
                COUNT(DISTINCT v.id) AS active_cnt
            FROM hr_version v
            WHERE v.active = true
              AND v.operating_unit_id IN %s
              AND v.operating_unit_id IS NOT NULL
              AND v.job_id IS NOT NULL
            GROUP BY 1, 2
        """, (ou_tuple,))
        active_emp_map = {(r[0], r[1]): r[2] for r in self.env.cr.fetchall()}

        # Direct scope total active employee count strictly from hr_version where active = true
        self.env.cr.execute("""
            SELECT COUNT(DISTINCT v.id)
            FROM hr_version v
            WHERE v.active = true
              AND v.operating_unit_id IN %s
        """, (ou_tuple,))
        scope_total_active = self.env.cr.fetchone()[0] or 0

        # 6. Process establishment lines and compute aggregated metrics
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

            key = (ou.id, job.id if job else False)

            # 1) Active employee fetched strictly from hr_version (v.active = true)
            act = active_emp_map.get(key, 0)
            # 2) Approved plan fetched from pbms_plan_category_line (display_approved_annual_total)
            plan = int(round(approved_plan_map.get(key, line.approved_plan_count or 0)))
            # Baseline: active employee count + approved plan additions
            base = act + plan
            # 3) Headcount: baseline count (which includes approved plan additions)
            tot = base
            # 4) Vacant: headcount - active
            vac = max(0, tot - act)

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
                "district_name": ou.department.name if ou.department else (ou.parent_unit.name if ou.parent_unit else (ou.name if ou.work_unit_type in ["district_office", "head_office"] else "-")),
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

        # Ensure total_active reflects all active employees in scope
        total_active = max(total_active, scope_total_active)
        total_authorized = total_baseline

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
            "tableRows": table_rows,
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
