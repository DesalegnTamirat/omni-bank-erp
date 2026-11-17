/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount, useRef, useEffect } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

class DisciplineDashboard extends Component {
    static template = "discipline_management.DisciplineDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        // Canvas references for Chart.js
        this.severityCanvas = useRef("severityChart");
        this.categoryCanvas = useRef("categoryChart");
        this.misconductCanvas = useRef("misconductChart");

        this.charts = {};

        this.state = useState({
            isLoading: true,
            isRefreshing: false,
            lastUpdated: "Just now",
            selectedPeriod: "month", // Default: This Month
            isCustomDate: false,
            level: "corporate",
            selectedEntityId: "",
            selectedSubUnitId: "",
            searchTerm: "",
            allowedLevels: [],
            chiefOffices: [],
            directCeoDirectorates: [],
            directoratesByChief: {},
            districtOffices: [],
            branchesByDistrict: {},
            districtBranches: [],
            user_district_key: "",
            user_district_name: "",
            is_district_dir: false,
            is_chief_retail: false,
            directorates: [],
            workUnits: [],
            is_governance_user: true,
            is_executive: true,
            is_secretary: false,
            executive_boss_name: "",
            executive_boss_title: "",
            secretary_followup: null,
            is_auditor: false,
            is_manager_only: false,
            selectedHierarchyScope: "all_hierarchy",
            show_hierarchy_filter: false,
            hierarchy_team_count: 0,
            direct_reports_count: 0,
            user_role: "employee",
            user_title: "",
            user_department: "",
            date_from: "",
            date_to: "",
            active_date_from: false,
            active_date_to: false,
            selectedDepartment: "",
            selected_unit_id: "",
            show_unit_filter: false,
            unit_label: "Organizational Unit",
            unit_groups: [],
            unit_options: [],
            is_employee_only: false,
            kpis: {
                total_cases: 0,
                active_cases: 0,
                pending_approval: 0,
                enforced_cases: 0,
                closed_cases: 0,
                sla_breached: 0,
                sla_compliance_rate: 100.0,
                active_suspensions: 0,
                suspensions_with_pay: 0,
                suspensions_without_pay: 0,
                pending_appeals: 0,
                active_investigations: 0,
                active_committee_meetings: 0,
                payroll_pending_count: 0,
                payroll_pending_amount: 0.0,
                payroll_total_recovery: 0.0,
                payroll_total_sanctions: 0.0,
                managerial_cases: 0,
                managerial_pct: 0.0,
                non_managerial_cases: 0,
                non_managerial_pct: 0.0,
                coach_track_cases: 0,
                coach_track_pct: 0.0,
                committee_track_cases: 0,
                committee_track_pct: 0.0,
            },
            pipeline_stages: {
                initiated: 0,
                investigation: 0,
                committee_review: 0,
                pending_approval: 0,
                enforced: 0,
                appealed: 0,
                closed: 0,
            },
            investigation_stages: {
                draft: 0,
                assigned: 0,
                manager_review: 0,
                director_review: 0,
                executive_submitted: 0,
                approved: 0,
                total: 0,
            },
            appeal_stages: {
                draft: 0,
                submitted: 0,
                under_review: 0,
                committee_review: 0,
                decided: 0,
                total: 0,
            },
            committee_stages: {
                draft: 0,
                scheduled: 0,
                in_progress: 0,
                completed: 0,
                total: 0,
            },
            upcoming_meetings: [],
            sla_aging: {
                under_7: 0,
                from_7_to_15: 0,
                from_16_to_30: 0,
                over_30_breached: 0,
                active_total: 0,
            },
            severity_matrix: [],
            misconduct_breakdown: [],
            department_hotspots: [],
            appeal_audit: {
                total_decided: 0,
                upheld_count: 0,
                upheld_pct: 0.0,
                reduced_count: 0,
                reduced_pct: 0.0,
                overturned_count: 0,
                overturned_pct: 0.0,
            },
            payroll_governance: {
                pending_count: 0,
                pending_amount: 0.0,
                transmitted_count: 0,
                transmitted_amount: 0.0,
                deducted_count: 0,
                deducted_amount: 0.0,
                cancelled_count: 0,
                cancelled_amount: 0.0,
                refund_count: 0,
                refund_amount: 0.0,
                total_recovery: 0.0,
                total_penalties_count: 0,
            },
            department_options: [],
            chart_data: null,
            velocity_trend: null,
            action_watchlist: [],
            directorate_risk_matrix: [],
            employee_cases: [],
            employee_standing: null,
        });

        onMounted(async () => {
            await Promise.all([
                this._ensureChartJs(),
                this._loadFilterHierarchy(),
                this._loadDashboardData(true)
            ]);
        });

        useEffect(
            () => {
                if (!this.state.isLoading && this.state.chart_data) {
                    const timer = setTimeout(() => {
                        this._renderCharts();
                    }, 60);
                    return () => clearTimeout(timer);
                }
            },
            () => [this.state.isLoading, this.state.chart_data, this.state.velocity_trend]
        );

        onWillUnmount(() => {
            this._destroyCharts();
        });
    }

    async _ensureChartJs() {
        if (typeof Chart !== "undefined") return;
        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
        } catch (e) {
            console.warn("Chart.js loading fallback:", e);
        }
    }

    _destroyCharts() {
        Object.values(this.charts).forEach(c => {
            if (c && typeof c.destroy === "function") {
                c.destroy();
            }
        });
        this.charts = {};
    }

    _renderCharts() {
        if (typeof Chart === "undefined") {
            console.warn("Chart.js library is not available, skipping charts.");
            return;
        }

        this._destroyCharts();
        const cd = this.state.chart_data;
        if (!cd) return;

        // 1. Sanction Severity Matrix (Donut Chart)
        if (this.severityCanvas.el && cd.severity && cd.severity.data.length > 0) {
            const ctx = this.severityCanvas.el.getContext("2d");
            this.charts.severity = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: cd.severity.labels,
                    datasets: [{
                        data: cd.severity.data,
                        backgroundColor: cd.severity.colors,
                        borderWidth: 2,
                        borderColor: "#ffffff",
                        hoverOffset: 6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "68%",
                    plugins: {
                        legend: {
                            display: true,
                            position: "bottom",
                            labels: {
                                boxWidth: 12,
                                padding: 12,
                                font: { size: 11, family: "Segoe UI, sans-serif" },
                                color: "#334155",
                            }
                        },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => {
                                    const val = ctx.parsed || 0;
                                    const total = cd.severity.total || 1;
                                    const pct = Math.round((val / total) * 100);
                                    return ` ${ctx.label}: ${val} cases (${pct}%)`;
                                }
                            }
                        }
                    }
                }
            });
        }

        // 2. Staff Categories & Action Tracks (Segmented Donut)
        if (this.categoryCanvas.el && cd.categories && cd.categories.data.length > 0) {
            const ctx = this.categoryCanvas.el.getContext("2d");
            this.charts.categories = new Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: cd.categories.labels,
                    datasets: [{
                        data: cd.categories.data,
                        backgroundColor: cd.categories.colors,
                        borderWidth: 2,
                        borderColor: "#ffffff",
                        hoverOffset: 6,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "64%",
                    plugins: {
                        legend: {
                            display: true,
                            position: "bottom",
                            labels: {
                                boxWidth: 12,
                                padding: 12,
                                font: { size: 11, family: "Segoe UI, sans-serif" },
                                color: "#334155",
                            }
                        },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => ` ${ctx.label}: ${ctx.parsed} cases`
                            }
                        }
                    }
                }
            });
        }

        // 3. Top Misconduct Infractions & Policy Clauses (Chart.js Pareto Horizontal Bar)
        if (this.misconductCanvas.el && cd.misconduct && cd.misconduct.data.length > 0) {
            const ctx = this.misconductCanvas.el.getContext("2d");
            const fullLabels = cd.misconduct.labels;
            this.charts.misconduct = new Chart(ctx, {
                type: "bar",
                data: {
                    labels: fullLabels.map(l => l && l.length > 25 ? l.substring(0, 23) + "..." : l),
                    datasets: [{
                        label: "Infractions",
                        data: cd.misconduct.data,
                        backgroundColor: cd.misconduct.colors,
                        borderRadius: 6,
                        maxBarThickness: 20,
                    }]
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => {
                                    if (items && items.length > 0) {
                                        return fullLabels[items[0].dataIndex] || "";
                                    }
                                    return "";
                                },
                                label: (ctx) => ` Infractions: ${ctx.parsed.x} cases`
                            }
                        }
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            grid: { color: "rgba(0,0,0,0.05)" },
                            ticks: { precision: 0, font: { size: 10 } }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { font: { size: 10.5, weight: "500" }, color: "#334155" }
                        }
                    }
                }
            });
        }
    }

    async onPeriodSelectChange(ev) {
        const val = ev.target.value;
        this.state.selectedPeriod = val;
        if (val === "custom") {
            this.state.isCustomDate = true;
            if (!this.state.date_from || !this.state.date_to) {
                const today = new Date();
                const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);
                const format = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
                this.state.date_from = format(firstDay);
                this.state.date_to = format(today);
            }
        } else {
            this.state.isCustomDate = false;
            this.state.date_from = "";
            this.state.date_to = "";
        }
        await this._loadDashboardData(true);
    }

    async onCustomDateFromChange(ev) {
        this.state.date_from = ev.target.value;
        await this._loadDashboardData(true);
    }

    async onCustomDateToChange(ev) {
        this.state.date_to = ev.target.value;
        await this._loadDashboardData(true);
    }

    get currentDistrictBranches() {
        if (this.state.is_district_dir || this.state.level === 'district_branch') {
            return this.state.districtBranches || [];
        }
        const distId = this.state.selectedEntityId;
        if (distId && this.state.branchesByDistrict && this.state.branchesByDistrict[distId]) {
            return this.state.branchesByDistrict[distId];
        }
        return [];
    }

    get currentChiefDirectorates() {
        const chiefId = this.state.selectedEntityId;
        if (chiefId && this.state.directoratesByChief && this.state.directoratesByChief[chiefId]) {
            return this.state.directoratesByChief[chiefId];
        }
        return [];
    }

    async _loadFilterHierarchy() {
        try {
            const data = await this.orm.call(
                "discipline.case",
                "get_filter_hierarchy",
                []
            );
            if (data) {
                this.state.allowedLevels = data.allowed_levels || [];
                this.state.chiefOffices = data.chief_offices || [];
                this.state.directCeoDirectorates = data.direct_ceo_directorates || [];
                this.state.directoratesByChief = data.directorates_by_chief || {};
                this.state.districtOffices = data.district_offices || [];
                this.state.branchesByDistrict = data.branches_by_district || {};
                this.state.districtBranches = data.district_branches || [];
                this.state.user_district_key = data.user_district_key || "";
                this.state.user_district_name = data.user_district_name || "";
                this.state.is_district_dir = data.is_district_dir || false;
                this.state.is_chief_retail = data.is_chief_retail || false;
                this.state.directorates = data.directorates || [];
                this.state.workUnits = data.work_units || [];

                if (data.allowed_levels && data.allowed_levels.length > 0) {
                    if (!this.state.allowedLevels.some(l => l.id === this.state.level)) {
                        this.state.level = data.allowed_levels[0].id;
                    }
                }
            }
        } catch (e) {
            console.error("Failed to load discipline filter hierarchy:", e);
        }
    }

    async onLevelChange(ev) {
        this.state.level = ev.target.value;
        this.state.selectedEntityId = "";
        this.state.selectedSubUnitId = "";
        await this._loadDashboardData(true);
    }

    async onEntityChange(ev) {
        this.state.selectedEntityId = ev.target.value;
        this.state.selectedSubUnitId = "";
        await this._loadDashboardData(true);
    }

    async onSubUnitChange(ev) {
        this.state.selectedSubUnitId = ev.target.value;
        await this._loadDashboardData(true);
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
        if (this._searchDebounceTimer) {
            clearTimeout(this._searchDebounceTimer);
        }
        this._searchDebounceTimer = setTimeout(async () => {
            await this._loadDashboardData(false);
        }, 300);
    }

    async onDepartmentChange(ev) {
        this.state.selectedDepartment = ev.target.value;
        this.state.selected_unit_id = ev.target.value;
        this.state.selectedEntityId = ev.target.value;
        await this._loadDashboardData(true);
    }

    async onUnitChange(ev) {
        this.state.selected_unit_id = ev.target.value;
        this.state.selectedDepartment = ev.target.value;
        this.state.selectedEntityId = ev.target.value;
        await this._loadDashboardData(true);
    }

    async onHierarchyScopeChange(ev) {
        this.state.selectedHierarchyScope = ev.target.value;
        await this._loadDashboardData(true);
    }

    async manualRefresh() {
        this.state.isRefreshing = true;
        await this._loadDashboardData(false);
        this.state.isRefreshing = false;
        this.notification.add("Live metrics refreshed successfully", { type: "success" });
    }

    async _loadDashboardData(showOverlay = false) {
        if (showOverlay) {
            this.state.isLoading = true;
        }
        try {
            const effectiveUnit = this.state.selectedEntityId || this.state.selected_unit_id || this.state.selectedDepartment || false;
            const isNumericId = effectiveUnit && (/^\d+$/).test(String(effectiveUnit));
            const params = {
                period: this.state.selectedPeriod,
                date_from: this.state.isCustomDate ? (this.state.date_from || false) : false,
                date_to: this.state.isCustomDate ? (this.state.date_to || false) : false,
                level: this.state.level || "corporate",
                entity_id: this.state.selectedEntityId || "",
                sub_unit_id: this.state.selectedSubUnitId || "",
                search_term: this.state.searchTerm || "",
                unit_id: isNumericId ? parseInt(effectiveUnit) : false,
                department_id: isNumericId ? parseInt(effectiveUnit) : false,
                hierarchy_scope: this.state.selectedHierarchyScope || "all_hierarchy",
            };
            const result = await this.orm.call(
                "discipline.case",
                "get_dashboard_data",
                [],
                params
            );
            if (result) {
                this.state.kpis = result.kpis || this.state.kpis;
                this.state.pipeline_stages = result.pipeline_stages || this.state.pipeline_stages;
                this.state.investigation_stages = result.investigation_stages || this.state.investigation_stages;
                this.state.appeal_stages = result.appeal_stages || this.state.appeal_stages;
                this.state.committee_stages = result.committee_stages || this.state.committee_stages;
                this.state.upcoming_meetings = result.upcoming_meetings || [];
                this.state.sla_aging = result.sla_aging || this.state.sla_aging;
                this.state.severity_matrix = result.severity_matrix || [];
                this.state.misconduct_breakdown = result.misconduct_breakdown || [];
                this.state.department_hotspots = result.department_hotspots || [];
                this.state.appeal_audit = result.appeal_audit || this.state.appeal_audit;
                this.state.payroll_governance = result.payroll_governance || this.state.payroll_governance;
                this.state.chart_data = result.chart_data || null;
                this.state.velocity_trend = result.velocity_trend || null;
                this.state.action_watchlist = result.action_watchlist || [];
                this.state.directorate_risk_matrix = result.directorate_risk_matrix || [];
                this.state.employee_cases = result.employee_cases || [];
                this.state.employee_standing = result.employee_standing || null;
                this.state.active_date_from = result.active_date_from || false;
                this.state.active_date_to = result.active_date_to || false;
                this.state.is_governance_user = result.is_governance_user !== undefined ? result.is_governance_user : true;
                this.state.is_executive = result.is_executive !== undefined ? result.is_executive : true;
                this.state.is_secretary = result.is_secretary !== undefined ? result.is_secretary : false;
                this.state.executive_boss_name = result.executive_boss_name || "";
                this.state.executive_boss_title = result.executive_boss_title || "";
                this.state.secretary_followup = result.secretary_followup || null;
                this.state.is_auditor = result.is_auditor !== undefined ? result.is_auditor : false;
                this.state.is_manager_only = result.is_manager_only !== undefined ? result.is_manager_only : false;
                this.state.is_employee_only = result.is_employee_only !== undefined ? result.is_employee_only : false;
                this.state.show_hierarchy_filter = result.show_hierarchy_filter !== undefined ? result.show_hierarchy_filter : false;
                this.state.show_unit_filter = result.show_unit_filter !== undefined ? result.show_unit_filter : false;
                this.state.level = result.level || this.state.level;
                this.state.selectedEntityId = result.selected_entity_id !== undefined ? result.selected_entity_id : this.state.selectedEntityId;
                this.state.selectedSubUnitId = result.selected_sub_unit_id !== undefined ? result.selected_sub_unit_id : this.state.selectedSubUnitId;
                this.state.searchTerm = result.search_term !== undefined ? result.search_term : this.state.searchTerm;
                this.state.unit_label = result.unit_label || "Organizational Unit";
                this.state.unit_groups = result.unit_groups || [];
                this.state.unit_options = result.unit_options || [];
                this.state.selected_unit_id = result.selected_unit_id || this.state.selected_unit_id;
                this.state.selectedHierarchyScope = result.selectedHierarchyScope || this.state.selectedHierarchyScope;
                this.state.hierarchy_team_count = result.hierarchy_team_count || 0;
                this.state.direct_reports_count = result.direct_reports_count || 0;
                this.state.user_role = result.user_role || "employee";
                this.state.user_title = result.user_title || "";
                this.state.user_department = result.user_department || "";
                if (result.unit_options && result.unit_options.length) {
                    this.state.department_options = result.unit_options;
                } else if (result.department_options && result.department_options.length) {
                    this.state.department_options = result.department_options;
                }
                const now = new Date();
                this.state.lastUpdated = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            }
        } catch (e) {
            console.error("Enterprise Dashboard API failed:", e);
        } finally {
            if (showOverlay) {
                this.state.isLoading = false;
            }
        }
    }

    openCaseRecord(caseId) {
        if (!caseId) return;
        if (this.state.is_secretary) {
            this.openCaseTrackerRecord(caseId);
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "discipline.case",
            res_id: caseId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCaseTracker(filter = null) {
        const additionalContext = {
            discipline_scope: true,
            is_tracker_followup: true,
        };
        if (filter === "boss_desk") {
            additionalContext.search_default_filter_my_executive = 1;
            additionalContext.search_default_filter_active_cases = 1;
        } else if (filter === "active") {
            additionalContext.search_default_filter_my_executive = 0;
            additionalContext.search_default_filter_active_cases = 1;
        } else if (filter === "warning") {
            additionalContext.search_default_filter_my_executive = 0;
            additionalContext.search_default_filter_warning = 1;
        } else if (filter === "overdue") {
            additionalContext.search_default_filter_my_executive = 0;
            additionalContext.search_default_filter_overdue = 1;
        } else if (filter === "all") {
            additionalContext.search_default_filter_my_executive = 0;
            additionalContext.search_default_filter_active_cases = 0;
        }
        this.action.doAction("discipline_management.action_discipline_case_followup", {
            additionalContext: additionalContext,
        });
    }

    openCaseTrackerRecord(caseId) {
        if (!caseId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Case Expiration Tracking & Follow-up",
            res_model: "discipline.case",
            res_id: caseId,
            views: [[false, "form"]],
            view_mode: "form",
            context: {
                discipline_scope: true,
                is_tracker_followup: true,
                form_view_ref: "discipline_management.view_discipline_case_tracker_form",
            },
            target: "current",
        });
    }

    // ── Helper Domain & Label Resolvers for Drill-Down Consistency ──
    _getPeriodLabel() {
        const labels = {
            today: "Today",
            week: "This Week",
            month: "This Month",
            quarter: "This Quarter",
            ytd: "This Year",
            all: "All Time",
            custom: "Custom Range",
        };
        return labels[this.state.selectedPeriod] || "Filtered";
    }

    _getBaseCaseDomain() {
        const domain = [];
        if (this.state.active_date_from) {
            domain.push(["incident_date", ">=", this.state.active_date_from]);
        }
        if (this.state.active_date_to) {
            domain.push(["incident_date", "<=", this.state.active_date_to]);
        }
        if (this.state.level === "district" && this.state.selectedEntityId) {
            const did = parseInt(this.state.selectedEntityId, 10);
            domain.push("|", ["department_id", "=", did], ["employee_id.department_id", "=", did]);
        } else if (this.state.level === "directorate" && this.state.selectedEntityId) {
            const ouid = parseInt(this.state.selectedEntityId, 10);
            domain.push(["operating_unit_id", "=", ouid]);
        } else if (this.state.level === "workunit" && this.state.selectedEntityId) {
            const bid = parseInt(this.state.selectedEntityId, 10);
            domain.push("|", ["employee_id.operating_unit_id", "=", bid], ["operating_unit_id", "=", bid]);
        } else {
            const unit = this.state.selected_unit_id || this.state.selectedDepartment;
            if (unit) {
                const unitStr = String(unit).trim();
                if (unitStr.startsWith("ou_")) {
                    domain.push(["operating_unit_id", "=", parseInt(unitStr.replace("ou_", ""), 10)]);
                } else if (unitStr.startsWith("dept_")) {
                    domain.push("|", ["department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)], ["employee_id.department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)]);
                } else if (!isNaN(parseInt(unitStr, 10))) {
                    domain.push(["department_id", "=", parseInt(unitStr, 10)]);
                }
            }
        }
        if (this.state.searchTerm && this.state.searchTerm.trim()) {
            const s = this.state.searchTerm.trim();
            domain.push("|", "|", ["name", "ilike", s], ["employee_id.name", "ilike", s], ["description", "ilike", s]);
        }
        return domain;
    }

    _getBaseAppealDomain() {
        const domain = [];
        if (this.state.active_date_from) {
            domain.push(["submission_date", ">=", this.state.active_date_from]);
        }
        if (this.state.active_date_to) {
            domain.push(["submission_date", "<=", this.state.active_date_to]);
        }
        const unit = this.state.selected_unit_id || this.state.selectedDepartment;
        if (unit) {
            const unitStr = String(unit).trim();
            if (unitStr.startsWith("ou_")) {
                domain.push(["case_id.operating_unit_id", "=", parseInt(unitStr.replace("ou_", ""), 10)]);
            } else if (unitStr.startsWith("dept_")) {
                domain.push(["case_id.department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)]);
            } else if (!isNaN(parseInt(unitStr, 10))) {
                domain.push(["case_id.department_id", "=", parseInt(unitStr, 10)]);
            }
        }
        return domain;
    }

    _getBaseSuspensionDomain(liveActiveOnly = false) {
        const domain = [];
        if (!liveActiveOnly) {
            if (this.state.active_date_from) {
                domain.push(["end_date", ">=", this.state.active_date_from]);
            }
            if (this.state.active_date_to) {
                domain.push(["start_date", "<=", this.state.active_date_to]);
            }
        }
        const unit = this.state.selected_unit_id || this.state.selectedDepartment;
        if (unit) {
            const unitStr = String(unit).trim();
            if (unitStr.startsWith("ou_")) {
                domain.push(["case_id.operating_unit_id", "=", parseInt(unitStr.replace("ou_", ""), 10)]);
            } else if (unitStr.startsWith("dept_")) {
                domain.push(["department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)]);
            } else if (!isNaN(parseInt(unitStr, 10))) {
                domain.push(["department_id", "=", parseInt(unitStr, 10)]);
            }
        }
        return domain;
    }

    _getBaseInvestigationDomain() {
        const domain = [];
        if (this.state.active_date_from) {
            domain.push(["investigation_date", ">=", this.state.active_date_from]);
        }
        if (this.state.active_date_to) {
            domain.push(["investigation_date", "<=", this.state.active_date_to]);
        }
        const unit = this.state.selected_unit_id || this.state.selectedDepartment;
        if (unit) {
            const unitStr = String(unit).trim();
            if (unitStr.startsWith("ou_")) {
                domain.push(["case_id.operating_unit_id", "=", parseInt(unitStr.replace("ou_", ""), 10)]);
            } else if (unitStr.startsWith("dept_")) {
                domain.push(["case_id.department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)]);
            } else if (!isNaN(parseInt(unitStr, 10))) {
                domain.push(["case_id.department_id", "=", parseInt(unitStr, 10)]);
            }
        }
        return domain;
    }

    _getBaseCommitteeDomain() {
        const domain = [];
        if (this.state.active_date_from) {
            domain.push(["meeting_date", ">=", `${this.state.active_date_from} 00:00:00`]);
        }
        if (this.state.active_date_to) {
            domain.push(["meeting_date", "<=", `${this.state.active_date_to} 23:59:59`]);
        }
        const unit = this.state.selected_unit_id || this.state.selectedDepartment;
        if (unit) {
            const unitStr = String(unit).trim();
            if (unitStr.startsWith("ou_")) {
                domain.push(["case_id.operating_unit_id", "=", parseInt(unitStr.replace("ou_", ""), 10)]);
            } else if (unitStr.startsWith("dept_")) {
                domain.push(["department_id", "=", parseInt(unitStr.replace("dept_", ""), 10)]);
            } else if (!isNaN(parseInt(unitStr, 10))) {
                domain.push(["department_id", "=", parseInt(unitStr, 10)]);
            }
        }
        return domain;
    }

    // Interactive Drill-Down Navigation Handlers
    openAllCases() {
        const domain = [...this._getBaseCaseDomain()];
        const label = this._getPeriodLabel();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.state.selectedPeriod === "all" ? "All Disciplinary Cases" : `Disciplinary Cases (${label})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openActiveCases() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["state", "in", [
                "initiated", "submitted_director", "submitted_chief", "ceo_review",
                "investigating", "chairman_review", "committee_review",
                "pending_approval", "appealed"
            ]],
        ];
        const label = this._getPeriodLabel();
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `In Progress Disciplinary Cases (${label})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openManagerialCases() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["is_managerial", "=", true],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Managerial Staff Cases (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openNonManagerialCases() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["is_managerial", "=", false],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Non-Managerial Staff Cases (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openCoachTrackCases() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["case_action_track", "in", ["direct_enforce", "direct_line_manager"]],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Direct Line Manager / Coach Track Cases (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openCommitteeTrackCases() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["case_action_track", "=", "committee_escalation"],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Disciplinary Committee Track Cases (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openPipelineStage(stageKey) {
        const domainMap = {
            initiated: [["state", "in", ["draft", "submitted", "initiated"]]],
            investigation: [["state", "in", ["investigating", "hearing"]]],
            committee_review: [["state", "=", "committee_review"]],
            pending_approval: [["state", "=", "pending_approval"]],
            enforced: [["state", "=", "enforced"]],
            appealed: [["state", "=", "appealed"]],
            closed: [["state", "=", "closed"]],
        };
        const titleMap = {
            initiated: "Cases Initiated / Pre-Hearing",
            investigation: "Cases Under Investigation / Hearing",
            committee_review: "Cases in Committee Review",
            pending_approval: "Cases Awaiting Executive Approval",
            enforced: "Enforced Disciplinary Cases",
            appealed: "Cases Under Active Appeal",
            closed: "Closed Disciplinary Cases",
        };
        const stageDomain = domainMap[stageKey] || [];
        const domain = [...this._getBaseCaseDomain(), ...stageDomain];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${titleMap[stageKey] || "Disciplinary Cases"} (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openEnforcedCases() {
        this.openPipelineStage("enforced");
    }

    openClosedCases() {
        this.openPipelineStage("closed");
    }

    openAllSuspensions() {
        this.openSuspensions("all");
    }

    openSuspensionsWithoutPay() {
        this.openSuspensions("without_pay");
    }

    openSuspensionsWithPay() {
        this.openSuspensions("with_pay");
    }

    openPendingApproval() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["state", "=", "pending_approval"],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Cases Pending Executive Approval (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openSlaBreached() {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["is_sla_exceeded", "=", true],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `SLA Breached Cases (Article 33.11) (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openSuspensions(type = "all") {
        let domain = [
            ...this._getBaseSuspensionDomain(true),
            ["state", "in", ["active", "extended"]],
        ];
        if (type === "with_pay") {
            domain.push(["suspension_type", "=", "with_pay"]);
        } else if (type === "without_pay") {
            domain.push(["suspension_type", "=", "without_pay"]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: type === "without_pay" ? "Suspensions Without Pay" : (type === "with_pay" ? "Suspensions With Pay" : "Active Precautionary Suspensions"),
            res_model: "discipline.suspension",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openAllAppeals() {
        this.openAppeals("all");
    }

    openUnderReviewAppeals() {
        this.openAppeals("pending");
    }

    openDecidedAppeals() {
        this.openAppeals("decided");
    }

    openAppeals(state = "pending") {
        let domain = [...this._getBaseAppealDomain()];
        let name = `All Appeals (${this._getPeriodLabel()})`;
        if (state === "pending") {
            domain.push(["state", "in", ["submitted", "under_review", "committee_review"]]);
            name = `Appeals Under Review (${this._getPeriodLabel()})`;
        } else if (state === "committee_review") {
            domain.push(["state", "=", "committee_review"]);
            name = `Appeals Under Committee Review (${this._getPeriodLabel()})`;
        } else if (state === "under_review") {
            domain.push(["state", "=", "under_review"]);
            name = `Appeals Under Executive Review (${this._getPeriodLabel()})`;
        } else if (state === "decided") {
            domain.push(["state", "=", "decided"]);
            name = `Finalized Decided Appeals (${this._getPeriodLabel()})`;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: "discipline.appeal",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openAllInvestigations() {
        this.openInvestigations("all");
    }

    openActiveInvestigations() {
        this.openInvestigations("active");
    }

    openApprovedInvestigations() {
        this.openInvestigations("approved");
    }

    openInvestigations(stage = "active") {
        let domain = [...this._getBaseInvestigationDomain()];
        let name = "All Investigations";
        if (stage === "active") {
            domain.push(["state", "not in", ["approved", "cancelled"]]);
            name = "Active Internal Audit Investigations";
        } else if (stage === "draft") {
            domain.push(["state", "=", "draft"]);
            name = "Audit Referrals / Received";
        } else if (stage === "assigned") {
            domain.push(["state", "=", "assigned"]);
            name = "Investigations in Fact-Finding";
        } else if (stage === "review") {
            domain.push(["state", "in", ["manager_review", "director_review"]]);
            name = "Investigations Under Audit Review";
        } else if (stage === "approved") {
            domain.push(["state", "=", "approved"]);
            name = "Concluded & Approved Investigations";
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: "discipline.investigation",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openAllCommittees() {
        this.openCommittees("all");
    }

    openScheduledCommittees() {
        this.openCommittees("scheduled");
    }

    openInProgressCommittees() {
        this.openCommittees("in_progress");
    }

    openCompletedCommittees() {
        this.openCommittees("completed");
    }

    openCommittees(stage = "all") {
        let domain = [...this._getBaseCommitteeDomain()];
        let name = `All Disciplinary Committee Meetings (${this._getPeriodLabel()})`;
        if (stage === "active") {
            domain.push(["state", "in", ["scheduled", "in_progress"]]);
            name = `Active Scheduled & In-Session Hearings (${this._getPeriodLabel()})`;
        } else if (stage === "scheduled") {
            domain.push(["state", "=", "scheduled"]);
            name = `Hearings Scheduled (${this._getPeriodLabel()})`;
        } else if (stage === "in_progress") {
            domain.push(["state", "=", "in_progress"]);
            name = `In-Progress Committee Hearings (${this._getPeriodLabel()})`;
        } else if (stage === "completed") {
            domain.push(["state", "=", "completed"]);
            name = `Concluded Committee Hearings (${this._getPeriodLabel()})`;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: "discipline.committee.meeting",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openMeeting(meetingId) {
        if (!meetingId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Disciplinary Committee Hearing",
            res_model: "discipline.committee.meeting",
            res_id: meetingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCase(caseId) {
        if (!caseId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Disciplinary Case",
            res_model: "discipline.case",
            res_id: caseId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPayrollDeductions(state = "pending") {
        let domain = [];
        let name = "All Payroll Deductions";
        if (state === "pending") {
            domain = [["transaction_type", "=", "deduction"], ["state", "=", "pending"]];
            name = "Pending Payroll Deductions";
        } else if (state === "deducted") {
            domain = [["transaction_type", "=", "deduction"], ["state", "in", ["transferred", "deducted"]]];
            name = "Processed & Collected Payroll Deductions";
        } else if (state === "refund") {
            domain = [["transaction_type", "=", "refund"]];
            name = "Appellate Refunds & Reimbursements";
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: "discipline.payroll.penalty",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }

    openSeverityLevel(levelCode) {
        const domain = [
            ...this._getBaseCaseDomain(),
            ["severity_level", "=", levelCode],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Cases — ${levelCode.toUpperCase()} (${this._getPeriodLabel()})`,
            res_model: "discipline.case",
            domain: domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("discipline_management.discipline_dashboard", DisciplineDashboard);
registry.category("actions").add("discipline_dashboard_tag", DisciplineDashboard);
