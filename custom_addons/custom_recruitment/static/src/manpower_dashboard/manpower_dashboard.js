/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

export class ManpowerDashboard extends Component {
    static template = "custom_recruitment.ManpowerDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.donutChartRef = useRef("donutChart");
        this.barChartRef = useRef("barChart");

        this.donutChartInstance = null;
        this.barChartInstance = null;

        this.state = useState({
            level: "corporate", // corporate | department | workunit
            selectedDepartment: "",
            selectedWorkUnit: "",
            selectedCycle: "",
            searchTerm: "",
            loading: true,
            departments: [],
            workUnits: [],
            cycles: [],
            matchedOuIds: [],
            summary: {
                total_authorized: 0,
                total_baseline: 0,
                total_approved_plan: 0,
                total_active: 0,
                total_vacant: 0,
                total_inflight: 0,
                uninitiated_gap: 0,
                total_lateral: 0,
                total_replacement: 0,
                total_promotion: 0,
                total_resignation: 0,
                fulfillment_rate: 0,
                vacancy_rate: 0,
                total_positions_tracked: 0,
            },
            tableRows: [],
            currentPage: 1,
            pageSize: 15,
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this._loadFilterHierarchy();
        });

        onMounted(async () => {
            await this._fetchDashboardData();
        });
    }

    // ── Hierarchy Filters & Data Loading ──────────────────────────────────
    async _loadFilterHierarchy() {
        try {
            const data = await this.orm.call(
                "recruitment.manpower.dashboard.service",
                "get_filter_hierarchy",
                []
            );
            this.state.departments = data.departments || [];
            this.state.workUnits = data.work_units || [];
            this.state.cycles = data.cycles || [];

            const curCycle = this.state.cycles.find(c => c.is_current);
            if (curCycle) {
                this.state.selectedCycle = curCycle.id;
            }
        } catch (err) {
            console.error("Failed to load filter hierarchy:", err);
        }
    }

    async _fetchDashboardData() {
        this.state.loading = true;
        try {
            const res = await this.orm.call(
                "recruitment.manpower.dashboard.service",
                "get_dashboard_metrics",
                [],
                {
                    level: this.state.level,
                    department_id: this.state.selectedDepartment ? parseInt(this.state.selectedDepartment) : null,
                    workunit_id: this.state.selectedWorkUnit ? parseInt(this.state.selectedWorkUnit) : null,
                    cycle_id: this.state.selectedCycle ? parseInt(this.state.selectedCycle) : null,
                    search_term: this.state.searchTerm || "",
                }
            );

            this.state.matchedOuIds = res.matched_ou_ids || [];
            this.state.summary = res.summary || this.state.summary;
            this.state.tableRows = res.tableRows || [];
            this.state.currentPage = 1;
            this.state.loading = false;

            // Render Chart.js on mounted canvas DOM elements
            setTimeout(() => {
                this._renderCharts(res.charts);
            }, 50);
        } catch (err) {
            console.error("Failed to load dashboard metrics:", err);
            this.state.loading = false;
        }
    }

    // ── UI Filter Event Handlers ──────────────────────────────────────────
    async onLevelChange(ev) {
        const newLevel = ev.target.value;
        this.state.level = newLevel;
        this.state.selectedDepartment = "";
        this.state.selectedWorkUnit = "";
        await this._fetchDashboardData();
    }

    async onDepartmentChange(ev) {
        this.state.selectedDepartment = ev.target.value;
        await this._fetchDashboardData();
    }

    async onWorkUnitChange(ev) {
        this.state.selectedWorkUnit = ev.target.value;
        await this._fetchDashboardData();
    }

    async onCycleChange(ev) {
        this.state.selectedCycle = ev.target.value;
        await this._fetchDashboardData();
    }

    async onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
        await this._fetchDashboardData();
    }

    async onRefresh() {
        await this._fetchDashboardData();
    }

    // ── Pagination Helpers ────────────────────────────────────────────────
    get paginatedRows() {
        const start = (this.state.currentPage - 1) * this.state.pageSize;
        return this.state.tableRows.slice(start, start + this.state.pageSize);
    }

    get totalPages() {
        return Math.ceil(this.state.tableRows.length / this.state.pageSize) || 1;
    }

    prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
        }
    }

    nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
        }
    }

    // ── Chart Rendering (Chart.js with Official Bunna Colors) ──────────────
    _renderCharts(chartsData) {
        if (!chartsData || !window.Chart) return;

        // 1. Donut Chart: Staffing Fulfillment
        if (this.donutChartRef.el) {
            if (this.donutChartInstance) {
                this.donutChartInstance.destroy();
            }
            const donutCtx = this.donutChartRef.el.getContext("2d");
            this.donutChartInstance = new window.Chart(donutCtx, {
                type: "doughnut",
                data: {
                    labels: chartsData.fulfillment_donut.labels,
                    datasets: [{
                        data: chartsData.fulfillment_donut.data,
                        backgroundColor: ["#425727", "#c17540", "#541718"],
                        borderColor: ["#ffffff", "#ffffff", "#ffffff"],
                        borderWidth: 2,
                        hoverOffset: 6,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: "bottom",
                            labels: { boxWidth: 14, font: { size: 12, weight: "bold" }, color: "#1e2917" },
                        },
                        tooltip: {
                            callbacks: {
                                label: function (context) {
                                    const label = context.label || "";
                                    const value = context.parsed || 0;
                                    return ` ${label}: ${value} Headcount`;
                                },
                            },
                        },
                    },
                    cutout: "68%",
                },
            });
        }

        // 2. Bar Chart: Top Vacancies by Work Unit
        if (this.barChartRef.el) {
            if (this.barChartInstance) {
                this.barChartInstance.destroy();
            }
            const barCtx = this.barChartRef.el.getContext("2d");
            this.barChartInstance = new window.Chart(barCtx, {
                type: "bar",
                data: {
                    labels: chartsData.unit_comparison_bar.labels,
                    datasets: [
                        {
                            label: _t("Active Staff"),
                            data: chartsData.unit_comparison_bar.actives,
                            backgroundColor: "#425727",
                            borderRadius: 4,
                        },
                        {
                            label: _t("Vacant Posts (Gap)"),
                            data: chartsData.unit_comparison_bar.vacants,
                            backgroundColor: "#541718",
                            borderRadius: 4,
                        },
                        {
                            label: _t("Total Establishment"),
                            data: chartsData.unit_comparison_bar.totals,
                            backgroundColor: "#1d2b32",
                            borderRadius: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { font: { size: 11 }, color: "#1e2917" },
                        },
                        y: {
                            beginAtZero: true,
                            grid: { color: "#e3e7db" },
                            ticks: { precision: 0, color: "#1e2917" },
                        },
                    },
                    plugins: {
                        legend: {
                            position: "top",
                            labels: { boxWidth: 12, font: { size: 11, weight: "600" }, color: "#1e2917" },
                        },
                    },
                },
            });
        }
    }

    // ── Interactive KPI Card Drilldown Navigation Handlers ─────────────────
    onClickAuthorized() {
        const domain = [];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("Authorized Workforce Establishment"),
            type: "ir.actions.act_window",
            res_model: "operating.unit.job.position",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickBaseline() {
        const domain = [["baseline_count", ">", 0]];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("Baseline Headcount Positions"),
            type: "ir.actions.act_window",
            res_model: "operating.unit.job.position",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickActiveStaff() {
        const domain = [["active", "=", true]];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_ids", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("Active Employees on Duty"),
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickApprovedPlan() {
        const domain = [["approved_plan_count", ">", 0]];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("Approved PBMS Plan Additions"),
            type: "ir.actions.act_window",
            res_model: "operating.unit.job.position",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickVacantPosts() {
        const domain = [["vacant_position_count", ">", 0]];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("Vacant Positions (Staffing Gaps)"),
            type: "ir.actions.act_window",
            res_model: "operating.unit.job.position",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickInFlight() {
        const domain = [
            ["request_type", "=", "planned"],
            ["state", "in", ["submitted", "under_review", "approved"]],
        ];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: _t("In-Flight Recruitment Requests"),
            type: "ir.actions.act_window",
            res_model: "recruitment.request",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    onClickMovement(type) {
        const fieldMap = {
            lateral: "lateral_count",
            replacement: "replacement_count",
            promotion: "promotion_count",
            resignation: "resignation_count",
        };
        const titleMap = {
            lateral: _t("Lateral Transfer Tracked Positions"),
            replacement: _t("Replacement Tracked Positions"),
            promotion: _t("Promotion Tracked Positions"),
            resignation: _t("Resignation / Departure Tracked Positions"),
        };
        const field = fieldMap[type] || "total_headcount";
        const domain = [[field, ">", 0]];
        if (this.state.matchedOuIds && this.state.matchedOuIds.length > 0) {
            domain.push(["operating_unit_id", "in", this.state.matchedOuIds]);
        }
        this.actionService.doAction({
            name: titleMap[type] || _t("Tracked Establishment Positions"),
            type: "ir.actions.act_window",
            res_model: "operating.unit.job.position",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    // ── Table Row Direct Actions ──────────────────────────────────────────
    openRecruitmentRequests(row = null) {
        const domain = [["request_type", "=", "planned"]];
        if (row && row.operating_unit_id) {
            domain.push(["operating_unit_id", "=", row.operating_unit_id]);
        }
        if (row && row.job_position_id) {
            domain.push(["job_position_id", "=", row.job_position_id]);
        }

        this.actionService.doAction({
            name: _t("Recruitment Requests"),
            type: "ir.actions.act_window",
            res_model: "recruitment.request",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    createNewRecruitmentRequest(row) {
        this.actionService.doAction({
            name: _t("New Recruitment Request"),
            type: "ir.actions.act_window",
            res_model: "recruitment.request",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_request_type: "planned",
                default_operating_unit_id: row.operating_unit_id,
                default_job_position_id: row.job_position_id,
            },
        });
    }

    openOperatingUnit(row) {
        if (!row || !row.operating_unit_id) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "operating.unit",
            res_id: row.operating_unit_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("custom_recruitment.ManpowerDashboard", ManpowerDashboard);
