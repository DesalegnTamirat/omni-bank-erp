/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

export class RecruitmentDashboard extends Component {
    static template = "custom_recruitment.RecruitmentDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            period: "today",
            recruitmentType: "all",   // all | internal | external
            dateFrom: "",
            dateTo: "",
            stats: {
                total: 0, draft: 0, published: 0, closed: 0,
                internal: 0, external: 0,
                probation_total: 0, probation_completed: 0, probation_pending: 0,
                transfer_total: 0, transfer_approved: 0, transfer_pending: 0,
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

    // ── Date helpers ──────────────────────────────────────────────────────
    _getDateRange() {
        const today = new Date();
        const fmt = d => d.toISOString().split("T")[0];

        if (this.state.period === "custom") {
            return [this.state.dateFrom || null, this.state.dateTo || null];
        }
        if (this.state.period === "today") {
            const f = fmt(today); return [f, f];
        }
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

    _buildDomain(dateField, extraDomain = []) {
        const [from, to] = this._getDateRange();
        const domain = [...extraDomain];
        if (from) domain.push([dateField, ">=", from]);
        if (to)   domain.push([dateField, "<=", to]);
        // Recruitment type filter — proper Odoo domain syntax
        if (this.state.recruitmentType === "internal") {
            domain.push("|");
            domain.push(["recruitment_type", "=", "Internal"]);
            domain.push(["sourcing_type", "in", ["internal", "both"]]);
        } else if (this.state.recruitmentType === "external") {
            domain.push("|");
            domain.push(["recruitment_type", "=", "External"]);
            domain.push(["sourcing_type", "in", ["external", "both"]]);
        }
        return domain;
    }

    // ── Data loading ──────────────────────────────────────────────────────
    async _loadData() {
        this.state.loading = true;

        const vacDomain = this._buildDomain("opening_date");
        const [from, to] = this._getDateRange();
        const cleanProbDomain = [];
        const cleanTranDomain = [];
        if (from) { cleanProbDomain.push(["probation_start_date",">=",from]); cleanTranDomain.push(["request_date",">=",from]); }
        if (to)   { cleanProbDomain.push(["probation_start_date","<=",to]);   cleanTranDomain.push(["request_date","<=",to]); }

        const [vacancies, probations, transfers] = await Promise.all([
            this.orm.searchRead("job.vacancy", vacDomain,
                ["vacancy_status", "recruitment_type", "sourcing_type",
                 "internal_movement_type", "source_channel"]),
            this.orm.searchRead("hr.employee.probation", cleanProbDomain, ["state"]),
            this.orm.searchRead("employee.transfer.request", cleanTranDomain, ["state"]),
        ]);

        const total     = vacancies.length;
        const draft     = vacancies.filter(v => v.vacancy_status === "draft").length;
        const published = vacancies.filter(v => v.vacancy_status === "published").length;
        const closed    = vacancies.filter(v => v.vacancy_status === "closed").length;
        const internal  = vacancies.filter(v =>
            (v.recruitment_type||"").toLowerCase()==="internal" ||
            ["internal","both"].includes(v.sourcing_type)).length;
        const external  = vacancies.filter(v =>
            (v.recruitment_type||"").toLowerCase()==="external" ||
            ["external","both"].includes(v.sourcing_type)).length;

        // Internal movement breakdown
        const promotion = vacancies.filter(v => v.internal_movement_type === "promotion").length;
        const lateral   = vacancies.filter(v => v.internal_movement_type === "lateral").length;

        // External source channel breakdown
        const linkedin  = vacancies.filter(v => v.source_channel === "linkedin").length;
        const telegram  = vacancies.filter(v => v.source_channel === "telegram").length;
        const website   = vacancies.filter(v => v.source_channel === "website").length;
        const newspaper = vacancies.filter(v => v.source_channel === "newspaper").length;
        const other     = vacancies.filter(v => v.source_channel === "other" || !v.source_channel).length;

        // Store for chart rendering
        this._chartData = { draft, published, closed, internal, external,
                            promotion, lateral,
                            linkedin, telegram, website, newspaper, other };

        Object.assign(this.state.stats, {
            total, draft, published, closed, internal, external,
            probation_total:     probations.length,
            probation_completed: probations.filter(p => p.state === "completed").length,
            probation_pending:   probations.filter(p => p.state !== "completed").length,
            transfer_total:    transfers.length,
            transfer_approved: transfers.filter(t => t.state === "approved").length,
            transfer_pending:  transfers.filter(t => ["draft","submitted","under_review"].includes(t.state)).length,
        });

        this.state.loading = false;
        await new Promise(resolve => setTimeout(resolve, 50));
        this._renderCharts();
    }

    _renderCharts() {
        const d = this._chartData || {};
        const type = this.state.recruitmentType;

        if (type === "internal") {
            // Internal: pie = Promotion vs Lateral; bar = draft/published/closed + breakdown
            this._renderPie(
                [d.promotion || 0, d.lateral || 0,
                 (d.internal||0) - (d.promotion||0) - (d.lateral||0)],
                ["Promotion", "Lateral Transfer", "Other Internal"],
                ["#1d2632", "#b47198", "#8a8a72"]
            );
            this._renderBar(
                ["Draft", "Published", "Closed", "Promotion", "Lateral"],
                [d.draft||0, d.published||0, d.closed||0, d.promotion||0, d.lateral||0],
                ["#8a8a72", "#c17b3f", "#b47198", "#1d2632", "#2a6d5e"]
            );
        } else if (type === "external") {
            // External: pie = source channels; bar = source channels
            this._renderPie(
                [d.linkedin||0, d.telegram||0, d.website||0, d.newspaper||0, d.other||0],
                ["LinkedIn", "Telegram", "Website", "Newspaper", "Other"],
                ["#0077b5", "#0088cc", "#1d2632", "#c17b3f", "#8a8a72"]
            );
            this._renderBar(
                ["LinkedIn", "Telegram", "Website", "Newspaper", "Other"],
                [d.linkedin||0, d.telegram||0, d.website||0, d.newspaper||0, d.other||0],
                ["#0077b5", "#0088cc", "#1d2632", "#c17b3f", "#8a8a72"]
            );
        } else {
            // All: standard draft/published/closed + internal/external
            this._renderPie(
                [d.draft||0, d.published||0, d.closed||0],
                ["Draft", "Published", "Closed"],
                ["#8a8a72", "#c17b3f", "#b47198"]
            );
            this._renderBar(
                ["Draft", "Published", "Closed", "Internal", "External"],
                [d.draft||0, d.published||0, d.closed||0, d.internal||0, d.external||0],
                ["#8a8a72", "#c17b3f", "#b47198", "#1d2632", "#2a6d5e"]
            );
        }
        this._renderTrend({ draft: d.draft||0, published: d.published||0, closed: d.closed||0 });
    }

    _getCanvas(id) { return document.getElementById(id); }

    _renderPie(values, labels, colors) {
        const canvas = this._getCanvas("recruitmentPieChart");
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
                            padding: 12, font: { size: 11 },
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
        const canvas = this._getCanvas("recruitmentBarChart");
        if (!canvas) return;
        if (this.barChart) { this.barChart.destroy(); this.barChart = null; }
        // eslint-disable-next-line no-undef
        this.barChart = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{ label: "Vacancies", data, backgroundColor: colors, borderRadius: 4 }],
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

    _renderTrend({ draft, published, closed }) {
        const canvas = this._getCanvas("recruitmentTrendChart");
        if (!canvas) return;
        if (this.trendChart) { this.trendChart.destroy(); this.trendChart = null; }
        // eslint-disable-next-line no-undef
        this.trendChart = new Chart(canvas, {
            type: "line",
            data: {
                labels: ["Draft", "Published", "Closed"],
                datasets: [{
                    label: "Vacancies",
                    data: [draft, published, closed],
                    fill: true,
                    backgroundColor: "rgba(180,113,152,0.18)",
                    borderColor: "#1d2632",
                    tension: 0.4,
                    pointBackgroundColor: "#b47198",
                    pointBorderColor: "#1d2632",
                    pointRadius: 6, pointHoverRadius: 8,
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

    // ── Event handlers ────────────────────────────────────────────────────
    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        if (this.state.period !== "custom") await this._loadData();
    }

    async onTypeChange(ev) {
        this.state.recruitmentType = ev.target.value;
        await this._loadData();
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

    // ── Navigation ────────────────────────────────────────────────────────
    openVacancies(ev) {
        const status = ev.currentTarget.dataset.status || "";
        const domain = status ? [["vacancy_status", "=", status]] : [];
        if (this.state.recruitmentType === "internal") {
            domain.push("|");
            domain.push(["recruitment_type", "=", "Internal"]);
            domain.push(["sourcing_type", "in", ["internal", "both"]]);
        }
        if (this.state.recruitmentType === "external") {
            domain.push("|");
            domain.push(["recruitment_type", "=", "External"]);
            domain.push(["sourcing_type", "in", ["external", "both"]]);
        }
        this.actionService.doAction({
            type: "ir.actions.act_window", name: "Job Vacancies",
            res_model: "job.vacancy", view_mode: "list,form",
            views: [[false,"list"],[false,"form"]], domain,
        });
    }

    openProbation(ev) {
        const state = ev.currentTarget.dataset.state || "";
        const domain = state ? [["state","=",state]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window", name: "Employee Probation",
            res_model: "hr.employee.probation", view_mode: "list,form",
            views: [[false,"list"],[false,"form"]], domain,
        });
    }

    openTransfer(ev) {
        const state = ev.currentTarget.dataset.state || "";
        const domain = state ? [["state","=",state]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window", name: "Transfer Requests",
            res_model: "employee.transfer.request", view_mode: "list,form",
            views: [[false,"list"],[false,"form"]], domain,
        });
    }
}

registry.category("actions").add("custom_recruitment.recruitment_dashboard", RecruitmentDashboard);
