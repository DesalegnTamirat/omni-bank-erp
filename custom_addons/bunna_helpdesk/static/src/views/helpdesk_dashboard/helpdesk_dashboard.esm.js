import {Component, onMounted, onWillStart, onWillUnmount, useEffect, useRef, useState} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {loadBundle} from "@web/core/assets";
import {session} from "@web/session";

// Auto-refresh interval in milliseconds (60 seconds)
const AUTO_REFRESH_MS = 60_000;

export class HelpdeskDashboard extends Component {
    static template = "bunna_helpdesk.HelpdeskDashboard";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.topCasesChartCanvas = useRef("topCasesChartCanvas");
        this.caseStatusChartCanvas = useRef("caseStatusChartCanvas");
        this.caseResolutionChartCanvas = useRef("caseResolutionChartCanvas");
        this.workUnitChartCanvas = useRef("workUnitChartCanvas");
        this.csatChartCanvas = useRef("csatChartCanvas");
        this.trendChartCanvas = useRef("trendChartCanvas");
        this.teamAgentActivitiesChartCanvas = useRef("teamAgentActivitiesChartCanvas");

        this.topCasesChart = null;
        this.caseStatusChart = null;
        this.caseResolutionChart = null;
        this.workUnitChart = null;
        this.csatChart = null;
        this.trendChart = null;
        this.teamAgentActivitiesChart = null;

        // Auto-refresh interval handle
        this._autoRefreshTimer = null;

        this.state = useState({
            period: "all",
            dateFrom: "",
            dateTo: "",
            groupingMode: "teams", // "teams" or "individual"
            teamId: 0,
            userId: 0,
            roleView: "auto",      // "auto", "manager", "back_line", "front_line"
            loading: false,
            collapsed: false,
            trendMetric: "all",    // "all", "created", "closed"
            activeDropdown: null,  // "grouping", "team", "user"
            lastUpdated: "",       // HH:MM:SS timestamp of last successful data load
            autoRefreshEnabled: true, // toggle for auto-refresh
            data: {
                user_role: "manager",
                active_role: "manager",
                can_switch_role: false,
                can_view_frontline: true,
                can_view_backline: true,
                is_front_line: false,
                base_domain: [],
                team_agent_activities: false,
                case_status_kpi: {
                    total: 0,
                    reopen: 0,
                    unassigned: 0,
                    escalated: 0,
                    in_progress: 0,
                    new: 0,
                    resolved: 0,
                    closed: 0,
                    rejected: 0,
                },
                front_back_channels: [],
                manager_channels: [],
                critical_urgent: { count: 0, very_high: 0, high: 0, unassigned: 0, tickets: [] },
                top_cases: { labels: [], series_total: [], series_solved: [], series_in_progress: [], series_escalated: [], cases_list: [] },
                case_resolution: { labels: [], series_total: [], series_resolved: [], series_pending: [], l1_resolved: 0, l1_total: 0, l2_resolved: 0, l2_total: 0, pending_count: 0 },
                work_unit: { labels: [], series_total: [], series_open: [], series_solved: [], units_list: [] },
                sla_breached: { total_breached: 0, open_breached: 0, critical_breached: 0, unassigned_breached: 0, by_work_unit: [], by_service_type: [] },
                agent_performance: [],
                avg_response_time: [],
                csat: { rating_avg: 0.0, rating_count: 0, breakdown: [] },
                kpi: { total: 0, open: 0, unassigned: 0, unattended: 0, urgent: 0, sla_failed: 0, nbe_complaints: 0, escalated: 0, internal: 0, external: 0, rating_avg: 0.0, rating_count: 0, total_hours: 0 },
                teams: [{id: 0, name: "All Teams"}],
                users: [],
                case_status: { labels: [], data: [], colors: [] },
                trend: { labels: [], created: [], closed: [], breached: [], total_created: 0, total_closed: 0, total_breached: 0 },
            },
        });

        this.onDocumentClick = (ev) => {
            if (this.state.activeDropdown && !ev.target.closest(".bunna-dropdown")) {
                this.state.activeDropdown = null;
            }
        };
        document.addEventListener("click", this.onDocumentClick);

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });

        onMounted(() => {
            this._startAutoRefresh();
        });

        useEffect(
            () => {
                if (!this.state.collapsed && !this.state.loading) {
                    this.renderCharts();
                }
            },
            () => [
                this.state.data,
                this.state.roleView,
                this.state.trendMetric,
                this.state.collapsed,
                this.state.loading,
            ]
        );

        onWillUnmount(() => {
            this.destroyCharts();
            this._stopAutoRefresh();
            document.removeEventListener("click", this.onDocumentClick);
        });
    }

    /* ── Auto-refresh helpers ────────────────────────────────────────────── */
    _startAutoRefresh() {
        this._stopAutoRefresh();
        this._autoRefreshTimer = setInterval(async () => {
            if (!this.state.loading && this.state.autoRefreshEnabled && !this.state.collapsed) {
                await this.loadData();
            }
        }, AUTO_REFRESH_MS);
    }

    _stopAutoRefresh() {
        if (this._autoRefreshTimer) {
            clearInterval(this._autoRefreshTimer);
            this._autoRefreshTimer = null;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefreshEnabled = !this.state.autoRefreshEnabled;
        if (this.state.autoRefreshEnabled) {
            this._startAutoRefresh();
            this.notification.add("Auto-refresh enabled (every 60 s)", { type: "info" });
        } else {
            this._stopAutoRefresh();
            this.notification.add("Auto-refresh paused", { type: "warning" });
        }
    }

    async loadData() {
        this.state.loading = true;
        try {
            const teamIdParam = (this.state.groupingMode === "teams" && this.state.teamId) ? Number(this.state.teamId) : false;
            const userIdParam = (this.state.groupingMode === "individual" && this.state.userId) ? Number(this.state.userId) : false;
            const res = await this.orm.call(
                "helpdesk.ticket.team",
                "retrieve_dashboard",
                [],
                {
                    period: this.state.period,
                    team_id: teamIdParam,
                    user_id: userIdParam,
                    grouping_mode: this.state.groupingMode,
                    role_view: this.state.roleView,
                    date_from: this.state.period === "custom" ? (this.state.dateFrom || false) : false,
                    date_to: this.state.period === "custom" ? (this.state.dateTo || false) : false,
                }
            );
            if (res) {
                this.state.data = res;
                if (res.is_front_line) {
                    this.state.groupingMode = "individual";
                    this.state.userId = 0;
                    this.state.teamId = 0;
                }
                // Stamp the last-updated time
                const now = new Date();
                this.state.lastUpdated = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
            }
        } catch (err) {
            console.error("Error loading Bunna Helpdesk dashboard:", err);
        } finally {
            this.state.loading = false;
        }
    }

    destroyCharts() {
        if (this.topCasesChart) {
            this.topCasesChart.destroy();
            this.topCasesChart = null;
        }
        if (this.caseStatusChart) {
            this.caseStatusChart.destroy();
            this.caseStatusChart = null;
        }
        if (this.caseResolutionChart) {
            this.caseResolutionChart.destroy();
            this.caseResolutionChart = null;
        }
        if (this.workUnitChart) {
            this.workUnitChart.destroy();
            this.workUnitChart = null;
        }
        if (this.csatChart) {
            this.csatChart.destroy();
            this.csatChart = null;
        }
        if (this.trendChart) {
            this.trendChart.destroy();
            this.trendChart = null;
        }
        if (this.teamAgentActivitiesChart) {
            this.teamAgentActivitiesChart.destroy();
            this.teamAgentActivitiesChart = null;
        }
    }

    renderCharts() {
        if (typeof window.Chart === "undefined") {
            return;
        }
        const role = this.state.data.active_role || this.state.data.user_role || "manager";

        // Team Agent Activities Horizontal Bar Chart (when a team is selected)
        this.renderTeamAgentActivitiesChart();

        // Case status chart is available for all tiers
        this.renderCaseStatusChart();

        // Top 4 Cases & Case Resolution are available for Back Office and Manager
        if (role === "manager" || role === "back_line") {
            this.renderTopCasesChart();
            this.renderCaseResolutionChart();
            this.renderWorkUnitChart();
            this.renderTrendChart();
        }

        // CSAT Chart is available for Manager
        if (role === "manager") {
            this.renderCsatChart();
        }
    }

    /* ── Team Agent Activities (Horizontal Bar Chart) ────────────────────── */
    renderTeamAgentActivitiesChart() {
        if (!this.teamAgentActivitiesChartCanvas || !this.teamAgentActivitiesChartCanvas.el) return;
        if (this.teamAgentActivitiesChart) {
            this.teamAgentActivitiesChart.destroy();
            this.teamAgentActivitiesChart = null;
        }

        const actData = this.state.data.team_agent_activities;
        if (!actData || !actData.chart_labels || !actData.chart_labels.length) return;

        const ctx = this.teamAgentActivitiesChartCanvas.el.getContext("2d");
        this.teamAgentActivitiesChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: actData.chart_labels,
                datasets: [
                    {
                        label: "Total Case Handling",
                        data: actData.chart_series_total,
                        backgroundColor: "#541718", // Bunna Maroon
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "Solved",
                        data: actData.chart_series_solved,
                        backgroundColor: "#425727", // Forest Green
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "In Progress",
                        data: actData.chart_series_in_progress,
                        backgroundColor: "#C17540", // Terracotta
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "Escalated",
                        data: actData.chart_series_escalated,
                        backgroundColor: "#1D2B32", // Slate Navy
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 10,
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        titleFont: { size: 12, weight: "bold" },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "#f1f5f9" },
                        ticks: { precision: 0, font: { size: 10, family: "Segoe UI, sans-serif" } },
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 11, weight: "500", family: "Segoe UI, sans-serif" } },
                    },
                },
            },
        });
    }

    /* ── 1. Top 4 Case Handling (Horizontal Bar Chart) ───────────────────── */
    renderTopCasesChart() {
        if (!this.topCasesChartCanvas || !this.topCasesChartCanvas.el) return;
        if (this.topCasesChart) {
            this.topCasesChart.destroy();
            this.topCasesChart = null;
        }

        const topData = this.state.data.top_cases;
        if (!topData || !topData.labels || !topData.labels.length) return;

        const ctx = this.topCasesChartCanvas.el.getContext("2d");
        this.topCasesChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: topData.labels,
                datasets: [
                    {
                        label: "Total Case Handling",
                        data: topData.series_total,
                        backgroundColor: "#541718", // Bunna Maroon
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "Solved",
                        data: topData.series_solved,
                        backgroundColor: "#425727", // Forest Green
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "In Progress",
                        data: topData.series_in_progress,
                        backgroundColor: "#C17540", // Terracotta
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                    {
                        label: "Escalated",
                        data: topData.series_escalated,
                        backgroundColor: "#1D2B32", // Slate Navy
                        borderRadius: 3,
                        barPercentage: 0.8,
                        categoryPercentage: 0.85,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 10,
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        titleFont: { size: 12, weight: "bold" },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "#f1f5f9" },
                        ticks: { precision: 0, font: { size: 10, family: "Segoe UI, sans-serif" } },
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 11, weight: "500", family: "Segoe UI, sans-serif" } },
                    },
                },
            },
        });
    }

    /* ── 2. Case Status (Pie / Donut Chart) ──────────────────────────────── */
    renderCaseStatusChart() {
        if (!this.caseStatusChartCanvas || !this.caseStatusChartCanvas.el) return;
        if (this.caseStatusChart) {
            this.caseStatusChart.destroy();
            this.caseStatusChart = null;
        }

        const statusData = this.state.data.case_status;
        if (!statusData || !statusData.labels || !statusData.labels.length) return;

        const ctx = this.caseStatusChartCanvas.el.getContext("2d");
        this.caseStatusChart = new window.Chart(ctx, {
            type: "doughnut",
            data: {
                labels: statusData.labels,
                datasets: [
                    {
                        data: statusData.data,
                        backgroundColor: statusData.colors || ["#1877F2", "#C17540", "#DC3545", "#425727", "#541718", "#726732", "#6C757D"],
                        borderColor: "#ffffff",
                        borderWidth: 2,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "60%",
                plugins: {
                    legend: {
                        position: "right",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 8,
                            generateLabels: function (chart) {
                                const data = chart.data;
                                if (data.labels.length && data.datasets.length) {
                                    const dataset = data.datasets[0];
                                    const total = dataset.data.reduce((acc, val) => acc + val, 0);
                                    return data.labels.map((label, i) => {
                                        const value = dataset.data[i];
                                        const pct = total > 0 ? Math.round((value / total) * 100) : 0;
                                        return {
                                            text: `${label} (${value} - ${pct}%)`,
                                            fillStyle: dataset.backgroundColor[i],
                                            hidden: isNaN(dataset.data[i]) || chart.getDatasetMeta(0).data[i].hidden,
                                            index: i,
                                        };
                                    });
                                }
                                return [];
                            },
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        titleFont: { size: 12, weight: "bold" },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
            },
        });
    }

    /* ── 3. Case Resolution (Horizontal Bar Chart) ───────────────────────── */
    renderCaseResolutionChart() {
        if (!this.caseResolutionChartCanvas || !this.caseResolutionChartCanvas.el) return;
        if (this.caseResolutionChart) {
            this.caseResolutionChart.destroy();
            this.caseResolutionChart = null;
        }

        const resData = this.state.data.case_resolution;
        if (!resData || !resData.labels || !resData.labels.length) return;

        const ctx = this.caseResolutionChartCanvas.el.getContext("2d");
        this.caseResolutionChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: resData.labels,
                datasets: [
                    {
                        label: "Total Handled",
                        data: resData.series_total,
                        backgroundColor: "#541718", // Maroon
                        borderRadius: 3,
                        barPercentage: 0.7,
                        categoryPercentage: 0.8,
                    },
                    {
                        label: "Resolved",
                        data: resData.series_resolved,
                        backgroundColor: "#425727", // Green
                        borderRadius: 3,
                        barPercentage: 0.7,
                        categoryPercentage: 0.8,
                    },
                    {
                        label: "Pending",
                        data: resData.series_pending,
                        backgroundColor: "#1D2B32", // Slate
                        borderRadius: 3,
                        barPercentage: 0.7,
                        categoryPercentage: 0.8,
                    },
                ],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 10,
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        titleFont: { size: 12, weight: "bold" },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: "#f1f5f9" },
                        ticks: { precision: 0, font: { size: 10, family: "Segoe UI, sans-serif" } },
                    },
                    y: {
                        grid: { display: false },
                        ticks: { font: { size: 11, weight: "500", family: "Segoe UI, sans-serif" } },
                    },
                },
            },
        });
    }

    /* ── 4. Case Handling by Work Unit (Bar Chart) ───────────────────────── */
    renderWorkUnitChart() {
        if (!this.workUnitChartCanvas || !this.workUnitChartCanvas.el) return;
        if (this.workUnitChart) {
            this.workUnitChart.destroy();
            this.workUnitChart = null;
        }

        const wuData = this.state.data.work_unit;
        if (!wuData || !wuData.labels || !wuData.labels.length) return;

        const ctx = this.workUnitChartCanvas.el.getContext("2d");
        this.workUnitChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: wuData.labels,
                datasets: [
                    {
                        label: "Total Tickets",
                        data: wuData.series_total,
                        backgroundColor: "#541718",
                        borderRadius: 4,
                        barPercentage: 0.75,
                    },
                    {
                        label: "Solved",
                        data: wuData.series_solved,
                        backgroundColor: "#425727",
                        borderRadius: 4,
                        barPercentage: 0.75,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 12, font: { size: 11 } },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 10 } },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        grid: { color: "#f1f5f9" },
                    },
                },
            },
        });
    }

    /* ── 5. CSAT Rating Distribution Chart (Bar) ─────────────────────────── */
    renderCsatChart() {
        if (!this.csatChartCanvas || !this.csatChartCanvas.el) return;
        if (this.csatChart) {
            this.csatChart.destroy();
            this.csatChart = null;
        }

        const csat = this.state.data.csat;
        if (!csat || !csat.breakdown || !csat.breakdown.length) return;

        const labels = csat.breakdown.map((b) => b.rating);
        const data = csat.breakdown.map((b) => b.count);
        const colors = ["#425727", "#726732", "#c17540", "#d44638", "#541718", "#6c757d"];

        const ctx = this.csatChartCanvas.el.getContext("2d");
        this.csatChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Ratings Received",
                        data: data,
                        backgroundColor: colors,
                        borderRadius: 4,
                        barPercentage: 0.65,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        callbacks: {
                            label: function (context) {
                                return ` ${context.parsed.y} ratings`;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11, weight: "600" } },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        grid: { color: "#f1f5f9" },
                    },
                },
            },
        });
    }

    /* ── 6. Line Chart: Trends & Inflow vs Resolution ───────────────────── */
    renderTrendChart() {
        if (!this.trendChartCanvas || !this.trendChartCanvas.el) return;
        if (this.trendChart) {
            this.trendChart.destroy();
            this.trendChart = null;
        }

        const trend = this.state.data.trend;
        if (!trend || !trend.labels || !trend.labels.length) return;

        const ctx = this.trendChartCanvas.el.getContext("2d");
        const datasets = [];

        if (this.state.trendMetric === "all" || this.state.trendMetric === "created") {
            datasets.push({
                label: "Tickets Created (Inflow)",
                data: trend.created,
                borderColor: "#541718",
                backgroundColor: "rgba(84, 23, 24, 0.12)",
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: "#541718",
            });
        }

        if (this.state.trendMetric === "all" || this.state.trendMetric === "closed") {
            datasets.push({
                label: "Resolved / Closed",
                data: trend.closed,
                borderColor: "#425727",
                backgroundColor: "rgba(66, 87, 39, 0.12)",
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: "#425727",
            });
        }

        this.trendChart = new window.Chart(ctx, {
            type: "line",
            data: {
                labels: trend.labels,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: "index",
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 12, font: { size: 11, family: "Segoe UI, sans-serif" } },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 10 } },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                        grid: { color: "#f1f5f9" },
                    },
                },
            },
        });
    }

    /* ── Role Switching Controls (Manager / Admin privilege) ─────────────── */
    async selectRoleView(role) {
        if (this.state.roleView === role) return;
        this.state.roleView = role;
        await this.loadData();
    }

    /* ── Dropdown Controls ───────────────────────────────────────────────── */
    toggleDropdown(name, ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        this.state.activeDropdown = this.state.activeDropdown === name ? null : name;
    }

    async selectGroupingMode(mode) {
        this.state.activeDropdown = null;
        if (this.state.groupingMode === mode) return;
        this.state.groupingMode = mode;
        if (this.state.groupingMode === "teams") {
            this.state.userId = 0;
        } else {
            this.state.teamId = 0;
        }
        await this.loadData();
    }

    async selectTeam(teamId) {
        this.state.activeDropdown = null;
        this.state.teamId = Number(teamId) || 0;
        await this.loadData();
    }

    async selectUser(userId) {
        this.state.activeDropdown = null;
        this.state.userId = Number(userId) || 0;
        await this.loadData();
    }

    get currentGroupingModeLabel() {
        if (this.state.data.is_front_line) {
            return "My Tickets";
        }
        if (this.state.data.active_role === "back_line") {
            return this.state.groupingMode === "individual" ? "My Tickets" : "My Team";
        }
        return this.state.groupingMode === "individual" ? "Individual" : "All Teams";
    }

    get currentTeamOrUserLabel() {
        if (this.state.data.is_front_line) {
            return "My Tickets";
        }
        if (this.state.groupingMode === "teams") {
            const team = (this.state.data.teams || []).find((t) => t.id === this.state.teamId);
            if (this.state.data.active_role === "back_line") {
                return team ? team.name : (this.state.data.teams?.[0]?.name || "My Team");
            }
            return team ? team.name : "All Teams";
        } else {
            if (this.state.data.active_role === "back_line") {
                if (this.state.userId === 0) return "My Tickets";
                if (this.state.userId === -1) return "Unassigned Tickets";
                const user = (this.state.data.users || []).find((u) => u.id === this.state.userId);
                return user ? user.name : "My Tickets";
            }
            if (this.state.userId === 0) return "All Users";
            if (this.state.userId === -1) return "Unassigned Tickets";
            const user = (this.state.data.users || []).find((u) => u.id === this.state.userId);
            return user ? user.name : "Select User";
        }
    }

    setTrendMetric(metric) {
        this.state.trendMetric = metric;
    }

    async setPeriod(period) {
        if (this.state.period === period) return;
        this.state.period = period;
        if (period === "custom") {
            if (!this.state.dateFrom || !this.state.dateTo) {
                const now = new Date();
                const y = now.getFullYear();
                const m = String(now.getMonth() + 1).padStart(2, "0");
                const d = String(now.getDate()).padStart(2, "0");
                if (!this.state.dateFrom) this.state.dateFrom = `${y}-${m}-01`;
                if (!this.state.dateTo) this.state.dateTo = `${y}-${m}-${d}`;
            }
            await this.loadData();
        } else {
            await this.loadData();
        }
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
    }

    async applyCustomDateRange() {
        if (this.state.dateFrom && this.state.dateTo && this.state.dateFrom > this.state.dateTo) {
            this.notification.add("Start date cannot be greater than end date.", { type: "warning" });
            return;
        }
        await this.loadData();
    }

    async clearCustomDateRange() {
        this.state.dateFrom = "";
        this.state.dateTo = "";
        this.state.period = "all";
        await this.loadData();
    }

    openAgentTodayTickets(agentId, agentName, filterType = "all") {
        let domain = [];
        const today = new Date().toISOString().slice(0, 10);

        if (filterType === "created") {
            domain = [
                ["create_uid", "=", agentId],
                ["create_date", ">=", `${today} 00:00:00`],
                ["create_date", "<=", `${today} 23:59:59`],
            ];
        } else if (filterType === "resolved") {
            domain = [
                ["user_id", "=", agentId],
                ["stage_id.closed", "=", true],
                "|",
                ["closed_date", ">=", `${today} 00:00:00`],
                ["last_stage_update", ">=", `${today} 00:00:00`],
            ];
        } else if (filterType === "open") {
            domain = [
                ["user_id", "=", agentId],
                ["stage_id.closed", "=", false],
            ];
        } else {
            domain = [
                "|",
                ["user_id", "=", agentId],
                ["create_uid", "=", agentId],
            ];
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Today's Activities - ${agentName}`,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
            ],
            domain: domain,
            context: {
                default_user_id: agentId,
            },
        });
    }

    toggleCollapse() {
        this.state.collapsed = !this.state.collapsed;
    }

    _getBaseDomain() {
        if (this.state.data && this.state.data.base_domain && this.state.data.base_domain.length) {
            return [...this.state.data.base_domain];
        }
        const domain = [];
        if (this.state.data.active_role === "front_line" || this.state.data.active_role === "back_line") {
            const teamIds = (this.state.data.teams || []).map((t) => t.id).filter((id) => id > 0);
            if (this.state.groupingMode === "teams") {
                if (this.state.teamId) {
                    domain.push(["team_id", "=", this.state.teamId]);
                } else if (teamIds.length) {
                    domain.push(["team_id", "in", teamIds]);
                }
            } else if (this.state.groupingMode === "individual") {
                if (this.state.userId === -1) {
                    domain.push(["user_id", "=", false]);
                    if (teamIds.length) domain.push(["team_id", "in", teamIds]);
                } else if (this.state.userId > 0) {
                    domain.push("|");
                    domain.push("|");
                    domain.push("|");
                    domain.push(["user_id", "=", this.state.userId]);
                    domain.push(["create_uid", "=", this.state.userId]);
                    domain.push(["escalated_to_user_id", "=", this.state.userId]);
                    domain.push(["escalated_to_level_3_user_id", "=", this.state.userId]);
                } else {
                    const myUid = session.uid;
                    if (myUid) {
                        domain.push("|");
                        domain.push("|");
                        domain.push(["user_id", "=", myUid]);
                        domain.push(["escalated_to_user_id", "=", myUid]);
                        domain.push(["escalated_to_level_3_user_id", "=", myUid]);
                    }
                }
            }
        } else {
            if (this.state.groupingMode === "teams") {
                if (this.state.teamId) {
                    domain.push(["team_id", "=", this.state.teamId]);
                }
            } else if (this.state.groupingMode === "individual") {
                if (this.state.userId === -1) {
                    domain.push(["user_id", "=", false]);
                } else if (this.state.userId > 0) {
                    domain.push(["user_id", "=", this.state.userId]);
                }
            }
        }
        return domain;
    }

    /* ── Drill-Down Ticket Actions ───────────────────────────────────────── */
    openTickets(filterType, param) {
        let domain = this._getBaseDomain();
        let title = "Helpdesk Tickets";

        switch (filterType) {
            case "total":
                title = "All Tickets";
                break;
            case "reopen":
                domain.push(["is_reopened", "=", true]);
                title = "Reopened Tickets";
                break;
            case "unassigned":
                domain.push(["user_id", "=", false]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Unassigned Tickets";
                break;
            case "escalated":
                domain.push(["is_escalated", "=", true]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Escalated Cases (2nd Level)";
                break;
            case "in_progress":
                domain.push(["stage_id.name", "ilike", "Progress"]);
                domain.push(["stage_id.closed", "=", false]);
                title = "In Progress Tickets";
                break;
            case "new":
                domain.push(["stage_id.name", "=", "New"]);
                domain.push(["stage_id.closed", "=", false]);
                title = "New Tickets";
                break;
            case "review":
                domain.push(["stage_id.name", "in", ["Review", "Under Review"]]);
                title = "Tickets Under Review";
                break;
            case "resolved":
                domain.push(["stage_id.name", "in", ["Done", "Resolved", "Solved", "Resolve"]]);
                title = "Resolved Tickets";
                break;
            case "closed":
                domain.push(["stage_id.name", "in", ["Closed", "Close"]]);
                title = "Closed Tickets";
                break;
            case "rejected":
                domain.push(["stage_id.name", "in", ["Rejected", "Cancelled"]]);
                title = "Rejected Tickets";
                break;
            case "urgent":
                domain.push(["priority", "in", ["2", "3"]]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Critical / Urgent Tickets";
                break;
            case "very_high":
                domain.push(["priority", "=", "3"]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Very High Priority Tickets";
                break;
            case "high":
                domain.push(["priority", "=", "2"]);
                domain.push(["stage_id.closed", "=", false]);
                title = "High Priority Tickets";
                break;
            case "urgent_unassigned":
                domain.push(["priority", "in", ["2", "3"]]);
                domain.push(["stage_id.closed", "=", false]);
                domain.push(["user_id", "=", false]);
                title = "Unassigned Critical / Urgent Tickets";
                break;
            case "sla_failed":
                domain.push("|");
                domain.push(["sla_status", "=", "failed"]);
                domain.push(["ola_status", "=", "failed"]);
                title = "SLA & OLA Breached Tickets";
                break;
            case "sla_open_breached":
                domain.push("|");
                domain.push(["sla_status", "=", "failed"]);
                domain.push(["ola_status", "=", "failed"]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Open Breached Tickets";
                break;
            case "sla_critical_breached":
                domain.push("|");
                domain.push(["sla_status", "=", "failed"]);
                domain.push(["ola_status", "=", "failed"]);
                domain.push(["priority", "in", ["2", "3"]]);
                title = "Critical / Urgent Breached Tickets";
                break;
            case "sla_unassigned_breached":
                domain.push("|");
                domain.push(["sla_status", "=", "failed"]);
                domain.push(["ola_status", "=", "failed"]);
                domain.push(["user_id", "=", false]);
                title = "Unassigned Breached Tickets";
                break;
            case "work_unit":
                if (param) {
                    domain.push(["operating_unit_id.name", "=", param]);
                    title = `Tickets - ${param}`;
                }
                break;
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "pivot"],
            ],
            domain: domain,
            context: {
                default_team_id: (this.state.groupingMode === "teams" && this.state.teamId) || false,
                default_user_id: (this.state.groupingMode === "individual" && this.state.userId > 0 && this.state.userId) || false,
            },
        });
    }

    openTicketsByChannel(channelCode) {
        let domain = this._getBaseDomain();
        if (channelCode === "chatbot") {
            domain.push(["channel_type", "in", ["chatbot", "tidio_chat"]]);
        } else if (channelCode === "other") {
            domain.push(["channel_type", "in", ["other", "api", "mobile_banking", "branch_walkin", "instagram"]]);
        } else {
            domain.push(["channel_type", "=", channelCode]);
        }
        const titles = {
            phone: "Phone / IVR Tickets",
            telegram: "Telegram Tickets",
            whatsapp: "WhatsApp Tickets",
            facebook: "Facebook Messenger Tickets",
            email: "Email Helpdesk Tickets",
            web_portal: "Customer Web Portal Tickets",
            webportal: "Customer Web Portal Tickets",
            chatbot: "Chatbot & Live Chat Tickets",
            sms: "SMS / USSD Tickets",
            other: "Other Inflow Tickets",
        };
        const title = titles[channelCode] || `Tickets via ${channelCode}`;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "pivot"],
            ],
            domain: domain,
            context: {
                default_channel_type: channelCode === "chatbot" ? "chatbot" : (channelCode === "webportal" ? "web_portal" : channelCode),
            },
        });
    }

    openTicketsByWorkUnit(unitName) {
        let domain = this._getBaseDomain();
        domain.push("|");
        domain.push(["sla_status", "=", "failed"]);
        domain.push(["ola_status", "=", "failed"]);
        if (unitName) {
            domain.push(["operating_unit_id.name", "=", unitName]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `SLA & OLA Breached Tickets - ${unitName || 'All Units'}`,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "pivot"],
            ],
            domain: domain,
        });
    }

    openTicketsByService(serviceName) {
        let domain = this._getBaseDomain();
        domain.push("|");
        domain.push(["sla_status", "=", "failed"]);
        domain.push(["ola_status", "=", "failed"]);
        if (serviceName) {
            domain.push(["service_id.name", "=", serviceName]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `SLA & OLA Breached Tickets - ${serviceName || 'All Services'}`,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "pivot"],
            ],
            domain: domain,
        });
    }

    openTicketsByAgent(userId, userName) {
        let domain = [
            "|",
            ["create_uid", "=", userId],
            ["user_id", "=", userId],
        ];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Tickets Handled by ${userName}`,
            res_model: "helpdesk.ticket",
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
                [false, "pivot"],
            ],
            domain: domain,
            context: {
                default_user_id: userId,
            },
        });
    }

    openTicketRecord(ticketId) {
        if (!ticketId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "helpdesk.ticket",
            res_id: ticketId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    createTicket() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Support Ticket",
            res_model: "helpdesk.ticket",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_team_id: this.state.teamId || false,
            },
        });
    }

    openSlaAnalysis() {
        this.action.doAction("bunna_helpdesk.helpdesk_sla_analysis_action");
    }

    openSatisfactionAnalysis() {
        this.action.doAction("bunna_helpdesk.helpdesk_satisfaction_analysis_action");
    }

    async exportDashboardReport() {
        try {
            const teamIdParam = (this.state.groupingMode === "teams" && this.state.teamId) ? Number(this.state.teamId) : 0;
            const userIdParam = (this.state.groupingMode === "individual" && this.state.userId) ? Number(this.state.userId) : 0;
            const action = await this.orm.call(
                "helpdesk.ticket.team",
                "action_export_dashboard_excel",
                [],
                {
                    period: this.state.period,
                    team_id: teamIdParam,
                    user_id: userIdParam,
                    grouping_mode: this.state.groupingMode,
                    date_from: this.state.period === "custom" ? (this.state.dateFrom || false) : false,
                    date_to: this.state.period === "custom" ? (this.state.dateTo || false) : false,
                }
            );
            if (action && action.url) {
                this.action.doAction(action);
            }
        } catch (err) {
            console.error("Error exporting Bunna Dashboard report:", err);
            this.notification.add("Could not generate Excel report: " + (err.message || err), {
                type: "danger",
            });
        }
    }
}
