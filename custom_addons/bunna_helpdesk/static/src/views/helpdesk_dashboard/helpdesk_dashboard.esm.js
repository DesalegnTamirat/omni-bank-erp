import {Component, onWillStart, onWillUnmount, useEffect, useRef, useState} from "@odoo/owl";
import {useService} from "@web/core/utils/hooks";
import {loadBundle} from "@web/core/assets";

export class HelpdeskDashboard extends Component {
    static template = "bunna_helpdesk.HelpdeskDashboard";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.trendChartCanvas = useRef("trendChartCanvas");
        this.barChartCanvas = useRef("barChartCanvas");
        this.pieChartCanvas = useRef("pieChartCanvas");

        this.trendChart = null;
        this.barChart = null;
        this.pieChart = null;

        this.state = useState({
            period: "all",
            groupingMode: "teams", // "teams" or "individual"
            teamId: 0,
            userId: 0,
            loading: false,
            collapsed: false,
            trendMetric: "all",    // "all", "created", "closed"
            barMode: "teams",      // "teams", "channels", "stages"
            pieMode: "case_types", // "case_types", "priorities", "customer_types", "channels"
            activeDropdown: null,  // "grouping", "team", "user", "barMode", "pieMode"
            data: {
                kpi: {
                    total: 0,
                    open: 0,
                    unassigned: 0,
                    unattended: 0,
                    urgent: 0,
                    sla_failed: 0,
                    nbe_complaints: 0,
                    escalated: 0,
                    internal: 0,
                    external: 0,
                    rating_avg: 5.0,
                    rating_count: 0,
                    total_hours: 0,
                },
                stages: [],
                priorities: [],
                teams: [{id: 0, name: "All Teams"}],
                users: [],
                recent_tickets: [],
                company_name: "Bunna Bank",
                trend: {
                    labels: [],
                    created: [],
                    closed: [],
                    breached: [],
                    total_created: 0,
                    total_closed: 0,
                    total_breached: 0,
                },
                bar_charts: {
                    teams: {labels: [], series_open: [], series_closed: [], ids: []},
                    channels: {labels: [], data: [], codes: []},
                    stages: {labels: [], data: [], ids: []},
                },
                pie_charts: {
                    case_types: {labels: [], data: [], codes: []},
                    priorities: {labels: [], data: [], codes: []},
                    customer_types: {labels: [], data: [], codes: []},
                    channels: {labels: [], data: [], codes: []},
                },
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

        useEffect(
            () => {
                if (!this.state.collapsed && !this.state.loading) {
                    this.renderCharts();
                }
            },
            () => [
                this.state.data,
                this.state.trendMetric,
                this.state.barMode,
                this.state.pieMode,
                this.state.collapsed,
                this.state.loading,
            ]
        );

        onWillUnmount(() => {
            this.destroyCharts();
            document.removeEventListener("click", this.onDocumentClick);
        });
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
                }
            );
            if (res) {
                this.state.data = res;
            }
        } catch (err) {
            console.error("Error loading Bunna Helpdesk dashboard:", err);
        } finally {
            this.state.loading = false;
        }
    }

    destroyCharts() {
        if (this.trendChart) {
            this.trendChart.destroy();
            this.trendChart = null;
        }
        if (this.barChart) {
            this.barChart.destroy();
            this.barChart = null;
        }
        if (this.pieChart) {
            this.pieChart.destroy();
            this.pieChart = null;
        }
    }

    renderCharts() {
        if (typeof window.Chart === "undefined") {
            return;
        }
        this.renderTrendChart();
        this.renderBarChart();
        this.renderPieChart();
    }

    /* ── 1. Line Chart: Trends & Changes Over Time ───────────────────────── */
    renderTrendChart() {
        if (!this.trendChartCanvas.el) return;
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

        if (this.state.trendMetric === "all") {
            datasets.push({
                label: "SLA Breaches",
                data: trend.breached,
                borderColor: "#c17540",
                backgroundColor: "transparent",
                borderWidth: 2,
                borderDash: [5, 4],
                fill: false,
                tension: 0.35,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: "#c17540",
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
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 12,
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
                        grid: { display: false },
                        ticks: { font: { size: 10, family: "Segoe UI, sans-serif" } },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0,
                            font: { size: 10, family: "Segoe UI, sans-serif" },
                        },
                        grid: {
                            color: "#f1f5f9",
                        },
                    },
                },
            },
        });
    }

    /* ── 2. Bar & Column Chart: Compare Values Across Categories ─────────── */
    renderBarChart() {
        if (!this.barChartCanvas.el) return;
        if (this.barChart) {
            this.barChart.destroy();
            this.barChart = null;
        }

        const barData = this.state.data.bar_charts?.[this.state.barMode];
        if (!barData || !barData.labels || !barData.labels.length) return;

        const ctx = this.barChartCanvas.el.getContext("2d");
        let datasets = [];

        if (this.state.barMode === "teams") {
            datasets = [
                {
                    label: "Active Open Tickets",
                    data: barData.series_open || [],
                    backgroundColor: "#541718",
                    borderRadius: 4,
                },
                {
                    label: "Resolved / Closed",
                    data: barData.series_closed || [],
                    backgroundColor: "#425727",
                    borderRadius: 4,
                },
            ];
        } else if (this.state.barMode === "channels") {
            const colors = [
                "#541718", "#C17540", "#425727", "#726732", "#1D2B32", "#1E2917",
            ];
            datasets = [
                {
                    label: "Tickets Received",
                    data: barData.data || [],
                    backgroundColor: barData.labels.map((_, i) => colors[i % colors.length]),
                    borderRadius: 4,
                },
            ];
        } else if (this.state.barMode === "stages") {
            const stageColors = [
                "#541718", "#C17540", "#726732", "#425727", "#1D2B32", "#1E2917",
            ];
            datasets = [
                {
                    label: "Tickets in Stage",
                    data: barData.data || [],
                    backgroundColor: barData.labels.map((_, i) => stageColors[i % stageColors.length]),
                    borderRadius: 4,
                },
            ];
        }

        this.barChart = new window.Chart(ctx, {
            type: "bar",
            data: {
                labels: barData.labels,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
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
                        grid: { display: false },
                        ticks: { font: { size: 10, family: "Segoe UI, sans-serif" } },
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0,
                            font: { size: 10, family: "Segoe UI, sans-serif" },
                        },
                        grid: {
                            color: "#f1f5f9",
                        },
                    },
                },
                onClick: (evt, elements) => {
                    if (!elements || !elements.length) return;
                    const index = elements[0].index;

                    if (this.state.barMode === "teams" && barData.ids) {
                        const teamId = barData.ids[index];
                        this.openTickets("team", teamId);
                    } else if (this.state.barMode === "channels" && barData.codes) {
                        const channelCode = barData.codes[index];
                        this.openTickets("channel", channelCode);
                    } else if (this.state.barMode === "stages" && barData.ids) {
                        const stageId = barData.ids[index];
                        this.openTickets("stage", stageId);
                    }
                },
            },
        });
    }

    /* ── 3. Pie & Donut Chart: Parts of a Whole / Proportions ────────────── */
    renderPieChart() {
        if (!this.pieChartCanvas.el) return;
        if (this.pieChart) {
            this.pieChart.destroy();
            this.pieChart = null;
        }

        const pieData = this.state.data.pie_charts?.[this.state.pieMode];
        if (!pieData || !pieData.labels || !pieData.labels.length) return;

        const ctx = this.pieChartCanvas.el.getContext("2d");
        const palette = [
            "#541718", // Bunna Maroon (Primary)
            "#C17540", // Bunna Terracotta (Secondary)
            "#425727", // Bunna Forest (Secondary)
            "#726732", // Bunna Bronze (Secondary)
            "#1D2B32", // Bunna Slate (Primary)
            "#1E2917", // Bunna Pine (Secondary)
        ];

        const chartColors = pieData.labels.map((_, i) => palette[i % palette.length]);

        this.pieChart = new window.Chart(ctx, {
            type: "doughnut",
            data: {
                labels: pieData.labels,
                datasets: [
                    {
                        data: pieData.data,
                        backgroundColor: chartColors,
                        borderColor: "#ffffff",
                        borderWidth: 2,
                        hoverOffset: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "58%",
                plugins: {
                    legend: {
                        position: "right",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, family: "Segoe UI, sans-serif" },
                            padding: 8,
                        },
                    },
                    tooltip: {
                        backgroundColor: "#1D2B32",
                        titleFont: { size: 12, weight: "bold" },
                        bodyFont: { size: 11 },
                        padding: 10,
                        cornerRadius: 6,
                        callbacks: {
                            label: function (context) {
                                const label = context.label || "";
                                const value = context.parsed || 0;
                                const dataset = context.dataset;
                                const total = dataset.data.reduce((acc, curr) => acc + curr, 0);
                                const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                                return ` ${label}: ${value} (${percentage}%)`;
                            },
                        },
                    },
                },
                onClick: (evt, elements) => {
                    if (!elements || !elements.length) return;
                    const index = elements[0].index;
                    const selectedCode = pieData.codes ? pieData.codes[index] : false;
                    if (selectedCode === undefined || selectedCode === false || selectedCode === "") return;

                    if (this.state.pieMode === "case_types") {
                        this.openTickets("case_type", selectedCode);
                    } else if (this.state.pieMode === "priorities") {
                        this.openTickets("priority", selectedCode);
                    } else if (this.state.pieMode === "customer_types") {
                        this.openTickets(selectedCode === "internal" ? "internal" : "external");
                    } else if (this.state.pieMode === "channels") {
                        this.openTickets("channel", selectedCode);
                    }
                },
            },
        });
    }

    /* ── Dropdown Controls (Official Bunna Maroon Hover) ─────────────────── */
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

    selectBarMode(mode) {
        this.state.activeDropdown = null;
        this.state.barMode = mode;
    }

    selectPieMode(mode) {
        this.state.activeDropdown = null;
        this.state.pieMode = mode;
    }

    get currentGroupingModeLabel() {
        return this.state.groupingMode === "individual" ? "Individual" : "All Teams";
    }

    get currentTeamOrUserLabel() {
        if (this.state.groupingMode === "teams") {
            const team = (this.state.data.teams || []).find((t) => t.id === this.state.teamId);
            return team ? team.name : "All Teams";
        } else {
            if (this.state.userId === 0) return "All Users";
            if (this.state.userId === -1) return "Unassigned Tickets";
            const user = (this.state.data.users || []).find((u) => u.id === this.state.userId);
            return user ? user.name : "Select User";
        }
    }

    get currentBarModeLabel() {
        switch (this.state.barMode) {
            case "teams": return "By Support Teams (Open vs Closed)";
            case "channels": return "By Omnichannel Source";
            case "stages": return "By Pipeline Stage";
            default: return "Select View";
        }
    }

    get currentPieModeLabel() {
        switch (this.state.pieMode) {
            case "case_types": return "By Case Type";
            case "channels": return "By Omnichannel Source";
            case "priorities": return "By Priority";
            case "customer_types": return "By Customer Type (Branch vs External)";
            default: return "Select View";
        }
    }

    onBarModeChange(ev) {
        this.state.barMode = ev.target.value;
    }

    onPieModeChange(ev) {
        this.state.pieMode = ev.target.value;
    }

    setTrendMetric(metric) {
        this.state.trendMetric = metric;
    }

    async setPeriod(period) {
        if (this.state.period === period) return;
        this.state.period = period;
        await this.loadData();
    }

    async onGroupingModeChange(ev) {
        this.state.groupingMode = ev.target.value;
        if (this.state.groupingMode === "teams") {
            this.state.userId = 0;
        } else {
            this.state.teamId = 0;
        }
        await this.loadData();
    }

    async onTeamChange(ev) {
        this.state.teamId = Number(ev.target.value) || 0;
        await this.loadData();
    }

    async onUserChange(ev) {
        this.state.userId = Number(ev.target.value) || 0;
        await this.loadData();
    }

    toggleCollapse() {
        this.state.collapsed = !this.state.collapsed;
    }

    _getBaseDomain() {
        const domain = [];
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
        return domain;
    }

    openTickets(filterType, param) {
        let domain = this._getBaseDomain();
        let title = "Helpdesk Tickets";

        switch (filterType) {
            case "total":
                title = "All Tickets";
                break;
            case "open":
                domain.push(["stage_id.closed", "=", false]);
                title = "Active Open Tickets";
                break;
            case "unassigned":
                domain.push(["user_id", "=", false]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Unassigned Tickets";
                break;
            case "unattended":
                domain.push(["unattended", "=", true]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Unattended Tickets";
                break;
            case "urgent":
                domain.push(["priority", "in", ["2", "3"]]);
                domain.push(["stage_id.closed", "=", false]);
                title = "Urgent / High Priority Tickets";
                break;
            case "sla_failed":
                domain.push(["sla_status", "=", "failed"]);
                title = "SLA Breached Tickets";
                break;
            case "nbe_complaints":
                domain.push(["is_nbe_complaint", "=", true]);
                title = "NBE Regulatory Complaints";
                break;
            case "escalated":
                domain.push(["is_escalated", "=", true]);
                title = "Escalated Cases (2nd Level)";
                break;
            case "internal":
                domain.push(["customer_type", "=", "internal"]);
                title = "Internal Branch / Staff Cases";
                break;
            case "external":
                domain.push(["customer_type", "!=", "internal"]);
                title = "External Customer Cases";
                break;
            case "team":
                if (param) {
                    domain.push(["team_id", "=", param]);
                    title = "Team Tickets";
                }
                break;
            case "case_type":
                if (param) {
                    domain.push(["case_type", "=", param]);
                    title = `${param.replace('_', ' ').toUpperCase()} Tickets`;
                }
                break;
            case "channel":
                if (param) {
                    domain.push(["channel_type", "=", param]);
                    title = `${param.replace('_', ' ').toUpperCase()} Channel Tickets`;
                }
                break;
            case "stage":
                if (param) {
                    domain.push(["stage_id", "=", param]);
                    title = "Tickets in Stage";
                }
                break;
            case "priority":
                if (param !== undefined) {
                    domain.push(["priority", "=", String(param)]);
                    domain.push(["stage_id.closed", "=", false]);
                    title = `Priority ${param} Tickets`;
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
