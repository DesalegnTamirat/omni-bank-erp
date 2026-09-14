/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

export class AssessmentDashboard extends Component {
    static template = "assessment_system.AssessmentDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            period: "today",
            assessmentType: "all",   // all | exam | interview | transfer
            dateFrom: "",
            dateTo: "",
            stats: {
                total_sittings: 0,
                draft_exam_sessions: 0,
                active_sittings: 0,
                completed_sittings: 0,
                passed_sittings: 0,
                failed_sittings: 0,
                disqualified_sittings: 0,
                pending_grading_tasks: 0,
                overdue_grading_tasks: 0,
                my_grading_tasks: 0,
                total_exam_sessions: 0,
                interview_total: 0,
                interview_completed: 0,
                interview_pending: 0,
                my_pending_evaluations: 0,
                total_interview_sessions: 0,
                transfer_total: 0,
                transfer_approved: 0,
                transfer_pending: 0,
                total_publications: 0,
            },
            my_action_evals: [],
            user_name: "",
            loading: true,
        });

        this.pieChart   = null;
        this.barChart   = null;
        this.trendChart = null;

        onWillStart(async () => {
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                console.warn("ChartJS bundle not available", e);
            }
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

    // ── Filter Event Handlers ─────────────────────────────────────────────
    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        if (this.state.period !== "custom") {
            await this._loadData();
        }
    }

    async onTypeChange(ev) {
        this.state.assessmentType = ev.target.value;
        await this._loadData();
    }

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
    }

    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
    }

    async applyCustomRange() {
        if (this.state.dateFrom && this.state.dateTo) {
            await this._loadData();
        }
    }

    // ── Data loading ──────────────────────────────────────────────────────
    async _loadData() {
        this.state.loading = true;
        const [from, to] = this._getDateRange();

        try {
            const data = await this.orm.call(
                "assessment.dashboard",
                "get_dashboard_data",
                [],
                {
                    date_from: from,
                    date_to: to,
                    assessment_type: this.state.assessmentType,
                }
            );
            Object.assign(this.state.stats, data.stats || {});
            this.state.my_action_evals = data.my_action_evals || [];
            this.state.user_name = data.user_name || "";
        } catch (error) {
            console.error("Failed to load assessment dashboard data:", error);
        } finally {
            this.state.loading = false;
        }

        await new Promise(resolve => setTimeout(resolve, 60));
        this._renderCharts();
    }

    // ── Chart Rendering (Chart.js) ─────────────────────────────────────────
    _renderCharts() {
        const s = this.state.stats;
        const type = this.state.assessmentType;

        if (type === "exam") {
            // Exam view: Distribution of sittings
            this._renderPie(
                [s.passed_sittings || 0, s.failed_sittings || 0, s.active_sittings || 0, s.disqualified_sittings || 0],
                ["Passed (>= 50%)", "Failed (< 50%)", "In Progress", "Disqualified"],
                ["#2a6d5e", "#c17540", "#726732", "#541718"]
            );
            this._renderBar(
                ["Total Sittings", "Completed", "Passed", "Failed", "Disqualified", "Grading Queue"],
                [s.total_sittings || 0, s.completed_sittings || 0, s.passed_sittings || 0, s.failed_sittings || 0, s.disqualified_sittings || 0, s.pending_grading_tasks || 0],
                ["#425727", "#2a6d5e", "#1d2b32", "#c17540", "#541718", "#726732"]
            );
        } else if (type === "interview") {
            // Interview view: Completed vs Pending evaluations
            this._renderPie(
                [s.interview_completed || 0, s.interview_pending || 0],
                ["Completed Evaluations", "Pending Evaluations"],
                ["#425727", "#c17540"]
            );
            this._renderBar(
                ["Total Candidates", "Evaluations Completed", "Evaluations Pending"],
                [s.interview_total || 0, s.interview_completed || 0, s.interview_pending || 0],
                ["#425727", "#2a6d5e", "#c17540"]
            );
        } else if (type === "transfer") {
            // Transfer view: Approved vs Pending
            this._renderPie(
                [s.transfer_approved || 0, s.transfer_pending || 0],
                ["Approved", "In Progress / Pending"],
                ["#425727", "#726732"]
            );
            this._renderBar(
                ["Total Requests", "Approved", "In Progress"],
                [s.transfer_total || 0, s.transfer_approved || 0, s.transfer_pending || 0],
                ["#425727", "#2a6d5e", "#c17540"]
            );
        } else {
            // All assessments overview
            this._renderPie(
                [s.completed_sittings || 0, s.interview_completed || 0, s.transfer_approved || 0],
                ["Exams Completed", "Interviews Done", "Transfers Approved"],
                ["#726732", "#c17540", "#425727"]
            );
            this._renderBar(
                ["Exam Sittings", "Exams Passed", "Interviews", "Transfers", "Grading Queue"],
                [s.total_sittings || 0, s.passed_sittings || 0, s.interview_total || 0, s.transfer_total || 0, s.pending_grading_tasks || 0],
                ["#726732", "#c17540", "#1d2b32", "#425727", "#541718"]
            );
        }

        // Trend line chart: stages progression
        this._renderTrend(
            ["Total Registered", "Active / Live", "Completed", "Passed / Approved"],
            [
                (s.total_sittings || 0) + (s.interview_total || 0) + (s.transfer_total || 0),
                (s.active_sittings || 0) + (s.interview_pending || 0) + (s.transfer_pending || 0),
                (s.completed_sittings || 0) + (s.interview_completed || 0),
                (s.passed_sittings || 0) + (s.transfer_approved || 0),
            ]
        );
    }

    _renderPie(data, labels, colors) {
        const ctx = document.getElementById("assessmentPieChart");
        if (!ctx || typeof Chart === "undefined") return;
        if (this.pieChart) { this.pieChart.destroy(); }

        const allZero = data.every(v => v === 0);
        const plotData = allZero ? [1] : data;
        const plotColors = allZero ? ["#dcdfd8"] : colors;
        const plotLabels = allZero ? ["No Data"] : labels;

        this.pieChart = new Chart(ctx, {
            type: "pie",
            data: {
                labels: plotLabels,
                datasets: [{
                    data: plotData,
                    backgroundColor: plotColors,
                    borderWidth: 2,
                    borderColor: "#ffffff",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { boxWidth: 12, font: { size: 10 } },
                    },
                },
            },
        });
    }

    _renderBar(labels, data, colors) {
        const ctx = document.getElementById("assessmentBarChart");
        if (!ctx || typeof Chart === "undefined") return;
        if (this.barChart) { this.barChart.destroy(); }

        this.barChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    data,
                    backgroundColor: colors,
                    borderRadius: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, precision: 0 },
                        grid: { color: "#f0f2eb" },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 9 }, maxRotation: 20 },
                    },
                },
            },
        });
    }

    _renderTrend(labels, data) {
        const ctx = document.getElementById("assessmentTrendChart");
        if (!ctx || typeof Chart === "undefined") return;
        if (this.trendChart) { this.trendChart.destroy(); }

        this.trendChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    data,
                    borderColor: "#541718",
                    backgroundColor: "rgba(84, 23, 24, 0.12)",
                    fill: true,
                    tension: 0.4,
                    pointBackgroundColor: "#726732",
                    pointRadius: 5,
                    pointHoverRadius: 7,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { stepSize: 1, precision: 0 },
                        grid: { color: "#f0f2eb" },
                    },
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 9 } },
                    },
                },
            },
        });
    }

    // ── Navigation Action Shortcuts ──
    openSittingsAll() {
        this.openCandidateSittings([]);
    }

    openSessionsDraft() {
        this.openExamSessions([["state", "=", "draft"]]);
    }

    openSittingsLive() {
        this.openCandidateSittings([["state", "=", "in_progress"]]);
    }

    openSittingsCompleted() {
        this.openCandidateSittings([["state", "=", "completed"]]);
    }

    openSittingsPassed() {
        this.openCandidateSittings([["state", "=", "completed"], ["passed", "=", true]]);
    }

    openSittingsDisqualified() {
        this.openCandidateSittings([["state", "=", "disqualified"]]);
    }

    openCandidateSittings(domain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Candidate Exam Sittings",
            res_model: "exam.candidate.attempt",
            views: [[false, "list"], [false, "form"]],
            domain: Array.isArray(domain) ? domain : [],
        });
    }

    openExamSessions(domain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Exam Sessions",
            res_model: "exam.session",
            views: [[false, "list"], [false, "form"]],
            domain: Array.isArray(domain) ? domain : [],
        });
    }

    openGradingQueue() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Manual Grading Queue",
            res_model: "exam.grading.task",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "=", "pending"]],
        });
    }

    openInterviewsAll() {
        this.openInterviewSessions();
    }

    openMyEvaluationsDone() {
        this.openMyEvaluations([["state", "=", "submitted"]]);
    }

    openMyEvaluationsPending() {
        this.openMyEvaluations([["state", "=", "draft"]]);
    }

    openInterviewSessions() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "CBIS Interview Sessions",
            res_model: "cbis.interview.session",
            views: [[false, "list"], [false, "form"]],
        });
    }

    openMyEvaluations(extraDomain = []) {
        const domain = [["interviewer_user_id", "=", this.env.services.user?.userId || 1], ...extraDomain];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "My Assigned Interview Evaluations",
            res_model: "cbis.interviewer.evaluation",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    openTransfersAll() {
        this.openTransferRecords([]);
    }

    openTransfersApproved() {
        this.openTransferRecords([["state", "=", "approved"]]);
    }

    openTransfersPending() {
        this.openTransferRecords([["state", "in", ["draft", "submitted", "under_review"]]]);
    }

    openTransferRecords(domain = []) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Transfer Assessments",
            res_model: "transfer.assessment.record",
            views: [[false, "list"], [false, "form"]],
            domain: Array.isArray(domain) ? domain : [],
        });
    }

    openSpecificEvaluation(ev) {
        const evalId = typeof ev === "number" ? ev : parseInt(ev?.currentTarget?.dataset?.evalId || ev?.currentTarget?.getAttribute("data-eval-id"));
        if (!evalId) return;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Evaluation Sheet",
            res_model: "cbis.interviewer.evaluation",
            res_id: evalId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("assessment_system.assessment_dashboard", AssessmentDashboard);
