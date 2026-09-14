/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

export class OnboardingDashboard extends Component {
    static template = "custom_onboarding_induction.OnboardingDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            period: "today",
            dateFrom: "",
            dateTo: "",
            stats: {
                ob_total: 0, ob_draft: 0, ob_preboard: 0,
                ob_gate: 0, ob_workunit: 0, ob_midterm: 0,
                ob_completed: 0, ob_escalated: 0,
                ind_total: 0, ind_progress: 0, ind_completed: 0,
                task_total: 0, task_done: 0, task_overdue: 0,
            },
            loading: true,
        });

        this.pieChart   = null;
        this.barChart   = null;
        this.trendChart = null;

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });

        onMounted(async () => {
            await this._loadData();
        });
    }

    _getDateRange() {
        const today = new Date();
        const fmt = d => d.toISOString().split("T")[0];
        if (this.state.period === "custom") {
            return [this.state.dateFrom || null, this.state.dateTo || null];
        }
        if (this.state.period === "today") { const f = fmt(today); return [f, f]; }
        if (this.state.period === "week") {
            const day = today.getDay();
            const mon = new Date(today); mon.setDate(today.getDate() - ((day + 6) % 7));
            const sun = new Date(mon);   sun.setDate(mon.getDate() + 6);
            return [fmt(mon), fmt(sun)];
        }
        if (this.state.period === "month") {
            const from = new Date(today.getFullYear(), today.getMonth(), 1);
            const to   = new Date(today.getFullYear(), today.getMonth() + 1, 0);
            return [fmt(from), fmt(to)];
        }
        if (this.state.period === "year") {
            return [`${today.getFullYear()}-01-01`, `${today.getFullYear()}-12-31`];
        }
        return [null, null];
    }

    async _loadData() {
        this.state.loading = true;
        const [from, to] = this._getDateRange();

        const obDomain  = [];
        const indDomain = [];
        if (from) { obDomain.push(["start_date", ">=", from]); indDomain.push(["start_date", ">=", from]); }
        if (to)   { obDomain.push(["start_date", "<=", to]);   indDomain.push(["start_date", "<=", to]); }

        const [obPlans, indPlans, tasks] = await Promise.all([
            this.orm.searchRead("hr.onboarding.plan", obDomain,  ["state"]),
            this.orm.searchRead("hr.induction.plan",  indDomain, ["state"]),
            this.orm.searchRead("hr.onboarding.task", [],        ["state", "is_overdue"]),
        ]);

        Object.assign(this.state.stats, {
            ob_total:     obPlans.length,
            ob_draft:     obPlans.filter(p => p.state === "draft").length,
            ob_preboard:  obPlans.filter(p => p.state === "pre_boarding").length,
            ob_gate:      obPlans.filter(p => p.state === "induction_gate").length,
            ob_workunit:  obPlans.filter(p => p.state === "work_unit_onboarding").length,
            ob_midterm:   obPlans.filter(p => p.state === "midterm_review").length,
            ob_completed: obPlans.filter(p => p.state === "completed").length,
            ob_escalated: obPlans.filter(p => p.state === "escalated").length,
            ind_total:    indPlans.length,
            ind_progress: indPlans.filter(p => p.state === "in_progress").length,
            ind_completed:indPlans.filter(p => p.state === "completed").length,
            task_total:   tasks.length,
            task_done:    tasks.filter(t => t.state === "done").length,
            task_overdue: tasks.filter(t => t.is_overdue).length,
        });

        this.state.loading = false;
        await new Promise(r => setTimeout(r, 50));
        this._renderCharts();
    }

    _renderCharts() {
        const s = this.state.stats;

        // Pie: onboarding plans by stage
        this._renderPie(
            [s.ob_draft, s.ob_preboard, s.ob_gate, s.ob_workunit, s.ob_midterm, s.ob_completed],
            ["Draft", "Pre-Boarding", "Induction Gate", "Work Unit", "Mid-Term", "Completed"],
            ["#8a8a72", "#C17540", "#1d2b32", "#1e6b7a", "#8B6914", "#425707"]
        );

        // Bar: induction plans
        this._renderBar(
            ["Draft", "In Progress", "Completed"],
            [s.ind_total - s.ind_progress - s.ind_completed, s.ind_progress, s.ind_completed],
            ["#8a8a72", "#C17540", "#425707"]
        );

        // Line: task completion
        this._renderTrend(
            s.task_done,
            s.task_total - s.task_done - s.task_overdue,
            s.task_overdue
        );
    }

    _getCanvas(id) { return document.getElementById(id); }

    _renderPie(values, labels, colors) {
        const canvas = this._getCanvas("obPieChart");
        if (!canvas) return;
        if (this.pieChart) { this.pieChart.destroy(); this.pieChart = null; }
        // eslint-disable-next-line no-undef
        this.pieChart = new Chart(canvas, {
            type: "pie",
            data: {
                labels,
                datasets: [{ data: values, backgroundColor: colors, borderWidth: 2, borderColor: "#fff" }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            padding: 10, font: { size: 10 },
                            generateLabels: chart => chart.data.labels.map((lbl, i) => ({
                                text: `${lbl}: ${chart.data.datasets[0].data[i]}`,
                                fillStyle: chart.data.datasets[0].backgroundColor[i],
                                strokeStyle: "#fff", lineWidth: 2, index: i,
                            })),
                        },
                    },
                    tooltip: { callbacks: { label: ctx => ` ${ctx.label}: ${ctx.parsed}` } },
                },
                animation: { duration: 600 },
            },
        });
    }

    _renderBar(labels, data, colors) {
        const canvas = this._getCanvas("obBarChart");
        if (!canvas) return;
        if (this.barChart) { this.barChart.destroy(); this.barChart = null; }
        // eslint-disable-next-line no-undef
        this.barChart = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{ label: "Plans", data, backgroundColor: colors, borderRadius: 4 }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                    x: { grid: { display: false } },
                },
                animation: { duration: 600 },
            },
        });
    }

    _renderTrend(done, pending, overdue) {
        const canvas = this._getCanvas("obTrendChart");
        if (!canvas) return;
        if (this.trendChart) { this.trendChart.destroy(); this.trendChart = null; }
        // eslint-disable-next-line no-undef
        this.trendChart = new Chart(canvas, {
            type: "bar",
            data: {
                labels: ["Done", "Pending", "Overdue"],
                datasets: [{
                    label: "Tasks",
                    data: [done, pending, overdue],
                    backgroundColor: ["#425707", "#726732", "#7A1F3D"],
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 } },
                    x: { grid: { display: false } },
                },
                animation: { duration: 600 },
            },
        });
    }

    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        if (this.state.period !== "custom") await this._loadData();
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; }
    onDateToChange(ev)   { this.state.dateTo   = ev.target.value; }

    async applyCustomRange() {
        if (!this.state.dateFrom || !this.state.dateTo) {
            alert("Please select both From and To dates."); return;
        }
        if (this.state.dateFrom > this.state.dateTo) {
            alert("From date must be before To date."); return;
        }
        await this._loadData();
    }

    openOnboardingPlans(ev) {
        const state = ev.currentTarget.dataset.state || "";
        const domain = state ? [["state", "=", state]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Workplace Onboarding Plans",
            res_model: "hr.onboarding.plan",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openInductionPlans(ev) {
        const state = ev.currentTarget.dataset.state || "";
        const domain = state ? [["state", "=", state]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Corporate Induction Plans",
            res_model: "hr.induction.plan",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openTasks(ev) {
        const stateKey = ev.currentTarget.dataset.state || "";
        let domain = [];
        if (stateKey === "done")    domain = [["state", "=", "done"]];
        if (stateKey === "overdue") domain = [["is_overdue", "=", true]];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Onboarding Tasks",
            res_model: "hr.onboarding.task",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }
}

registry.category("actions").add(
    "custom_onboarding_induction.onboarding_dashboard",
    OnboardingDashboard
);
