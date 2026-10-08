/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

// Official Bunna Bank Corporate Color Palette
export const BUNNA_BRAND = {
    maroon: "#541718",       // Bunna Primary Deep Maroon
    pine: "#1E2917",         // Bunna Secondary Deep Pine
    green: "#425727",        // Bunna Forest Green (On Track / Primary CTA)
    bronze: "#C17540",       // Bunna Terracotta Bronze (In Progress / At Risk)
    olive: "#726732",        // Bunna Olive Gold (Milestones / Strategic Pillars)
    navy: "#1D2B32",         // Bunna Deep Slate Navy (Headers / Accents)
    maroonLight: "#742526",  // Bunna Maroon Light
    greenLight: "#597435",   // Bunna Forest Olive Light
    bronzeLight: "#A85E2B",  // Bunna Terracotta Light
    slateLight: "#2E3F48",   // Bunna Deep Slate Light
    warmBg: "#F7F9F5",       // Bunna Soft Brand Tint
};

export class PmExecutiveDashboard extends Component {
    static template = "project_management.ExecutiveDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        
        this.stageChartRef = useRef("stageChart");
        this.healthChartRef = useRef("healthChart");
        this.workloadChartRef = useRef("workloadChart");

        this.chartInstances = {};

        this.state = useState({
            loading: true,
            fullscreenCard: null,
            filters: {
                initiative_id: "",
                project_id: "",
                task_filter: "all",
            },
            data: {
                kpi: {
                    total_strategic_issues: 0,
                    total_initiatives: 0,
                    active_initiatives: 0,
                    achieved_initiatives: 0,
                    initiative_avg_progress: 0,
                    total_projects: 0,
                    portfolio_progress: 0,
                    health_counts: { on_track: 0, at_risk: 0, overdue: 0 },
                    total_deliverables: 0,
                    completed_deliverables: 0,
                    total_milestones: 0,
                    completed_milestones: 0,
                    total_strategic_objectives: 0,
                    todo_tasks: 0,
                    in_progress_tasks: 0,
                    in_review_tasks: 0,
                    completed_tasks: 0,
                    total_tasks: 0,
                    open_tasks: 0,
                    blocked_tasks: 0,
                    total_allocated_hours: 0,
                    total_logged_hours: 0,
                    effort_variance: 0,
                },
                charts: {
                    stage_chart: { labels: [], data: [] },
                    team_workload_chart: { labels: [], tasks: [], hours: [] },
                    health_counts: { on_track: 0, at_risk: 0, overdue: 0 },
                },
                tables: {
                    initiatives: [],
                    top_risks: [],
                    deadline_table: [],
                    blocked_table: [],
                },
                filters_data: {
                    initiatives: [],
                    projects: [],
                },
            },
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadData();
        });

        // Re-render Chart.js graphs whenever loading finishes or filters change
        useEffect(
            () => {
                if (!this.state.loading) {
                    this.renderCharts();
                }
            },
            () => [
                this.state.loading,
                this.state.filters.initiative_id,
                this.state.filters.project_id,
                this.state.filters.task_filter,
            ]
        );

        onWillUnmount(() => {
            this.destroyCharts();
        });
    }

    get availableProjects() {
        const initId = this.state.filters.initiative_id;
        const allProjs = this.state.data?.filters_data?.projects || [];
        if (!initId) {
            return allProjs;
        }
        return allProjs.filter((p) => p.initiative_id === parseInt(initId));
    }

    async loadData() {
        this.state.loading = true;
        try {
            const filtersPayload = {
                initiative_id: this.state.filters.initiative_id ? parseInt(this.state.filters.initiative_id) : null,
                project_id: this.state.filters.project_id === "non_project" ? "non_project" : (this.state.filters.project_id ? parseInt(this.state.filters.project_id) : null),
                task_filter: this.state.filters.task_filter || "all",
            };
            const result = await this.orm.call("pm.project", "get_dashboard_data", [filtersPayload]);
            this.state.data = result;
        } catch (error) {
            console.error("Error loading PM Executive Dashboard data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    async onInitiativeChange(ev) {
        const newInitId = ev.target.value;
        this.state.filters.initiative_id = newInitId;
        
        // If an initiative is chosen and Non-Project Tasks was selected, reset project
        if (newInitId && this.state.filters.project_id === "non_project") {
            this.state.filters.project_id = "";
        } else if (newInitId && this.state.filters.project_id) {
            // Verify if current project belongs to the selected initiative
            const stillValid = this.availableProjects.some(
                (p) => String(p.id) === String(this.state.filters.project_id)
            );
            if (!stillValid) {
                this.state.filters.project_id = "";
            }
        }
        await this.loadData();
    }

    async onProjectChange(ev) {
        const newProjId = ev.target.value;
        this.state.filters.project_id = newProjId;
        // Non-project tasks do not belong to any initiative
        if (newProjId === "non_project" && this.state.filters.initiative_id) {
            this.state.filters.initiative_id = "";
        }
        await this.loadData();
    }

    async onTaskFilterChange(ev) {
        this.state.filters.task_filter = ev.target.value;
        await this.loadData();
    }

    toggleFullscreen(cardName) {
        if (this.state.fullscreenCard === cardName) {
            this.state.fullscreenCard = null;
        } else {
            this.state.fullscreenCard = cardName;
        }
    }

    closeFullscreen() {
        this.state.fullscreenCard = null;
    }

    destroyCharts() {
        for (const key in this.chartInstances) {
            if (this.chartInstances[key]) {
                try {
                    this.chartInstances[key].destroy();
                } catch (e) {
                    console.warn("Chart destroy error:", e);
                }
                delete this.chartInstances[key];
            }
        }
    }

    renderCharts() {
        this.destroyCharts();
        if (typeof window.Chart === "undefined") {
            console.warn("Chart.js not loaded yet");
            return;
        }

        const charts = this.state.data.charts;

        // 1. Stage Distribution Chart (Bar) - Bunna Brand Palette
        if (this.stageChartRef.el && charts.stage_chart) {
            const ctx = this.stageChartRef.el.getContext("2d");
            const stageColors = [
                BUNNA_BRAND.olive,      // To Do: Bunna Olive Gold
                BUNNA_BRAND.green,      // In Progress: Bunna Forest Green
                BUNNA_BRAND.bronze,     // In Review: Bunna Terracotta Bronze
                BUNNA_BRAND.maroon,     // Blocked: Bunna Deep Maroon
                BUNNA_BRAND.navy,       // Completed: Bunna Deep Slate Navy
            ];
            const bgColors = charts.stage_chart.labels.map((_, i) => stageColors[i % stageColors.length]);

            this.chartInstances.stageChart = new window.Chart(ctx, {
                type: "bar",
                data: {
                    labels: charts.stage_chart.labels || [],
                    datasets: [{
                        label: "Tasks",
                        data: charts.stage_chart.data || [],
                        backgroundColor: bgColors,
                        borderRadius: 6,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: BUNNA_BRAND.navy,
                            titleFont: { weight: "bold" },
                        },
                    },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        // 2. Health Distribution (Doughnut) - Bunna Health Palette
        if (this.healthChartRef.el && charts.health_counts) {
            const ctx = this.healthChartRef.el.getContext("2d");
            const hc = charts.health_counts;
            this.chartInstances.healthChart = new window.Chart(ctx, {
                type: "doughnut",
                data: {
                    labels: ["On Track", "At Risk", "Overdue"],
                    datasets: [{
                        data: [hc.on_track || 0, hc.at_risk || 0, hc.overdue || 0],
                        backgroundColor: [BUNNA_BRAND.green, BUNNA_BRAND.bronze, BUNNA_BRAND.maroon],
                        borderWidth: 2,
                        borderColor: "#ffffff",
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (item) => ` ${item.label}: ${item.raw} Projects`,
                            },
                        },
                    },
                    cutout: "68%",
                },
            });
        }

        // 3. Team Workload Chart (Horizontal Bar) - Bunna Brand Palette
        if (this.workloadChartRef.el && charts.team_workload_chart) {
            const ctx = this.workloadChartRef.el.getContext("2d");
            const tw = charts.team_workload_chart;
            this.chartInstances.workloadChart = new window.Chart(ctx, {
                type: "bar",
                data: {
                    labels: tw.labels || [],
                    datasets: [
                        {
                            label: "Tasks Assigned",
                            data: tw.tasks || [],
                            backgroundColor: BUNNA_BRAND.maroon,
                            borderRadius: 4,
                        },
                    ],
                },
                options: {
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                afterLabel: (item) => {
                                    const hours = tw.hours && tw.hours[item.dataIndex] !== undefined ? tw.hours[item.dataIndex] : 0;
                                    return `Logged Hours: ${hours}h`;
                                },
                            },
                        },
                    },
                    scales: {
                        x: { beginAtZero: true, ticks: { precision: 0 } },
                        y: { grid: { display: false } },
                    },
                },
            });
        }
    }

    // Contextual Filter Domains for Smart Drilldowns
    get currentDomainContext() {
        const filters = this.state.filters;
        const projectDomain = [];
        const taskDomain = [];
        const deliverableDomain = [];
        const milestoneDomain = [];

        if (filters.initiative_id) {
            const initId = parseInt(filters.initiative_id);
            projectDomain.push(["initiative_id", "=", initId]);
            const childProjs = (this.state.data?.filters_data?.projects || [])
                .filter((p) => p.initiative_id === initId)
                .map((p) => p.id);
            taskDomain.push(["project_id", "in", childProjs]);
            deliverableDomain.push(["project_id", "in", childProjs]);
            milestoneDomain.push(["project_id", "in", childProjs]);
        }

        if (filters.project_id === "non_project") {
            taskDomain.length = 0; // clear project filter
            taskDomain.push(["project_id", "=", false]);
        } else if (filters.project_id) {
            const pId = parseInt(filters.project_id);
            projectDomain.push(["id", "=", pId]);
            taskDomain.length = 0;
            taskDomain.push(["project_id", "=", pId]);
            deliverableDomain.length = 0;
            deliverableDomain.push(["project_id", "=", pId]);
            milestoneDomain.length = 0;
            milestoneDomain.push(["project_id", "=", pId]);
        }

        return { projectDomain, taskDomain, deliverableDomain, milestoneDomain };
    }

    // Action Drilldowns
    openInitiatives(domain = []) {
        const finalDomain = [...domain];
        if (this.state.filters.initiative_id && finalDomain.length === 0) {
            finalDomain.push(["id", "=", parseInt(this.state.filters.initiative_id)]);
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Strategic Issues",
            res_model: "pm.initiative",
            views: [[false, "list"], [false, "form"]],
            domain: finalDomain,
        });
    }

    openActiveInitiatives() {
        this.openInitiatives([["state", "=", "in_progress"]]);
    }

    openAchievedInitiatives() {
        this.openInitiatives([["state", "=", "achieved"]]);
    }

    openInitiativeForm(initiativeId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Strategic Issue",
            res_model: "pm.initiative",
            res_id: initiativeId,
            views: [[false, "form"]],
        });
    }

    openProjects(extraDomain = []) {
        if (this.state.filters.project_id === "non_project") {
            this.openNonProjectTasks();
            return;
        }
        const domain = [...this.currentDomainContext.projectDomain, ...extraDomain];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Projects",
            res_model: "pm.project",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    openDeliverables() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Deliverables / Major Activities",
            res_model: "pm.deliverable",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: this.currentDomainContext.deliverableDomain,
        });
    }

    openMilestones() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Milestones",
            res_model: "pm.milestone",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: this.currentDomainContext.milestoneDomain,
        });
    }

    openStrategicObjectives() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Strategic Objectives",
            res_model: "pm.strategic.objective",
            views: [[false, "list"], [false, "form"]],
        });
    }

    openTasks(extraDomain = []) {
        if (this.state.filters.project_id === "non_project") {
            this.openNonProjectTasks(extraDomain);
            return;
        }
        const domain = [...this.currentDomainContext.taskDomain, ...extraDomain];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Tasks",
            res_model: "pm.task",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    openNonProjectTasks(extraDomain = []) {
        const domain = [["is_project_task", "=", false], ...extraDomain];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Non-Project Tasks",
            res_model: "pm.task",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: domain,
            context: { default_is_project_task: false, default_project_id: false },
        });
    }

    openTodoTasks() {
        this.openTasks([["state", "in", ["pending", "draft"]]]);
    }

    openInProgressTasks() {
        this.openTasks([["state", "=", "in_progress"]]);
    }

    openInReviewTasks() {
        this.openTasks([["stage_id.name", "ilike", "review"]]);
    }

    openOpenTasks() {
        this.openTasks([["is_closed", "=", false]]);
    }

    openCompletedTasks() {
        this.openTasks([["is_closed", "=", true]]);
    }

    openBlockedTasks() {
        this.openTasks([["is_blocked", "=", true], ["is_closed", "=", false]]);
    }

    openHoursLogged() {
        this.openTasks([["effective_hours", ">", 0]]);
    }

    openRiskForm(riskId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Project Risk Escalation",
            res_model: "pm.project.risk",
            res_id: riskId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openTaskForm(taskId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Task",
            res_model: "pm.task",
            res_id: taskId,
            views: [[false, "form"]],
        });
    }

    openProjectForm(projectId) {
        if (!projectId) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Project",
            res_model: "pm.project",
            res_id: projectId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("pm_executive_dashboard", PmExecutiveDashboard);
