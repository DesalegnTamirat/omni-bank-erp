/** @odoo-module **/

import { Component, onWillStart, useState, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class PerformanceDashboard extends Component {
    static template = "performance_management.PerformanceDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            filters: {
                fiscal_year_id: null,
                appraisal_period_id: null,
                tier: 'all',
                operating_unit_id: null,
                department_id: null,
            },
            data: null,
        });

        this.bellCurveCanvas = useRef("bellCurveChart");
        this.perspectiveCanvas = useRef("perspectiveChart");
        this.deptScoresCanvas = useRef("deptScoresChart");
        this.ouScoresCanvas = useRef("ouScoresChart");

        this.charts = {};

        onWillStart(async () => {
            await this.ensureChartJs();
            await this.loadData();
        });

        useEffect(
            () => {
                if (!this.state.loading && this.state.data) {
                    // Give DOM a frame to ensure canvases are mounted and sized
                    const timer = setTimeout(() => {
                        this.renderCharts();
                    }, 50);
                    return () => clearTimeout(timer);
                }
            },
            () => [this.state.loading, this.state.data]
        );
    }

    async ensureChartJs() {
        if (typeof Chart !== "undefined") return;
        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
        } catch (e) {
            console.warn("Chart.js loading fallback", e);
        }
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "performance.dashboard",
                "get_dashboard_data",
                [],
                { filters: this.state.filters }
            );
            this.state.data = data;
            if (data && data.filters) {
                if (!this.state.filters.fiscal_year_id && data.filters.selected_fiscal_year_id) {
                    this.state.filters.fiscal_year_id = data.filters.selected_fiscal_year_id;
                }
            }
        } catch (error) {
            console.error("Failed to load dashboard data", error);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefreshClick() {
        await this.ensureChartJs();
        await this.loadData();
    }

    async onFilterChange(filterKey, ev) {
        const value = ev.target.value;
        this.state.filters[filterKey] = (value === "" || value === "all") ? (filterKey === "tier" ? "all" : null) : (filterKey === "tier" ? value : parseInt(value));
        await this.loadData();
    }

    async renderCharts() {
        if (!this.state.data) return;
        await this.ensureChartJs();
        if (typeof Chart === "undefined") {
            console.warn("Chart.js is still not loaded");
            return;
        }

        // Destroy old chart instances
        Object.values(this.charts).forEach(chart => {
            if (chart && typeof chart.destroy === "function") {
                chart.destroy();
            }
        });
        this.charts = {};

        // 1. Bell Curve Chart (Doughnut)
        if (this.bellCurveCanvas.el) {
            const ctx = this.bellCurveCanvas.el.getContext("2d");
            const bc = this.state.data.charts.bell_curve;
            const totalRankings = (bc.data || []).reduce((a, b) => a + (Number(b) || 0), 0);

            const labels = totalRankings === 0 ? ['No Evaluated Records Yet'] : bc.labels;
            const data = totalRankings === 0 ? [1] : bc.data;
            const bgColors = totalRankings === 0 ? ['#e2e8f0'] : ['#2e7d32', '#0288d1', '#ed6c02', '#d32f2f'];

            this.charts.bellCurve = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: bgColors,
                        borderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: 'bottom' }
                    }
                }
            });
        }

        // 2. Perspective Chart (Bar)
        if (this.perspectiveCanvas.el) {
            const ctx = this.perspectiveCanvas.el.getContext("2d");
            const p = this.state.data.charts.perspective;
            const labels = (p.labels && p.labels.length) ? p.labels : ['Financial', 'Stakeholder', 'Internal Process', 'Learning & Growth'];
            const target = (p.target && p.target.length) ? p.target : [0, 0, 0, 0];
            const accomplished = (p.accomplished && p.accomplished.length) ? p.accomplished : [0, 0, 0, 0];

            this.charts.perspective = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Target Value',
                            data: target,
                            backgroundColor: 'rgba(66, 87, 39, 0.75)',
                            borderColor: '#425727',
                            borderWidth: 1,
                        },
                        {
                            label: 'Accomplished Value',
                            data: accomplished,
                            backgroundColor: 'rgba(84, 23, 24, 0.75)',
                            borderColor: '#541718',
                            borderWidth: 1,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, suggestedMax: 100 }
                    }
                }
            });
        }

        // 3. Department Scores Chart
        if (this.deptScoresCanvas.el) {
            const ctx = this.deptScoresCanvas.el.getContext("2d");
            const ds = this.state.data.charts.department_scores;
            const labels = (ds.labels && ds.labels.length) ? ds.labels : ['No Evaluated Departments'];
            const data = (ds.data && ds.data.length) ? ds.data : [0];

            this.charts.deptScores = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Avg Score (%)',
                        data: data,
                        backgroundColor: '#425727',
                        borderRadius: 4,
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { beginAtZero: true, max: 100 }
                    }
                }
            });
        }

        // 4. Operating Unit Scores Chart
        if (this.ouScoresCanvas.el) {
            const ctx = this.ouScoresCanvas.el.getContext("2d");
            const os = this.state.data.charts.ou_scores;
            const labels = (os.labels && os.labels.length) ? os.labels : ['No Evaluated Units'];
            const data = (os.data && os.data.length) ? os.data : [0];

            this.charts.ouScores = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Avg Score (%)',
                        data: data,
                        backgroundColor: '#541718',
                        borderRadius: 4,
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: { beginAtZero: true, max: 100 }
                    }
                }
            });
        }
    }

    openRecord(model, resId) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: model,
            res_id: resId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openFilteredList(model, domain, name) {
        this.action.doAction({
            name: name,
            type: 'ir.actions.act_window',
            res_model: model,
            domain: domain,
            views: [[false, 'list'], [false, 'kanban'], [false, 'form']],
            target: 'current',
        });
    }

    openScorecardsCard() {
        const tier = this.state.filters.tier;
        let model = 't3.scorecard';
        let name = 'Tier 3 Employee Scorecards';
        if (tier === 't1') {
            model = 'corporate.scorecard';
            name = 'Tier 1 Corporate Scorecards';
        } else if (tier === 't2') {
            model = 't2.scorecard';
            name = 'Tier 2 Division Scorecards';
        } else {
            if (this.state.data && this.state.data.tier_governance) {
                const tg = this.state.data.tier_governance;
                if (tg.planning.tier1.scorecards.total > 0 && tg.planning.tier2.scorecards.total === 0 && tg.hr.tier3.scorecards.total === 0) {
                    model = 'corporate.scorecard';
                    name = 'Tier 1 Corporate Scorecards';
                } else if (tg.planning.tier2.scorecards.total > 0 && tg.hr.tier3.scorecards.total === 0) {
                    model = 't2.scorecard';
                    name = 'Tier 2 Division Scorecards';
                }
            }
        }

        const domain = [];
        if (this.state.filters.fiscal_year_id) {
            domain.push(['fiscal_year_id', '=', this.state.filters.fiscal_year_id]);
        }
        if (this.state.filters.appraisal_period_id) {
            domain.push(['appraisal_period_id', '=', this.state.filters.appraisal_period_id]);
        }
        if (this.state.filters.operating_unit_id) {
            domain.push(['operating_unit_id', '=', this.state.filters.operating_unit_id]);
        }
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', this.state.filters.department_id]);
        }
        this.openFilteredList(model, domain, name);
    }

    openAppraisalsCard() {
        const tier = this.state.filters.tier;
        let model = 't3.appraisal';
        let name = 'Tier 3 Employee Appraisals';
        if (tier === 't1') {
            model = 'corporate.appraisal';
            name = 'Tier 1 Corporate Appraisals';
        } else if (tier === 't2') {
            model = 't2.appraisal';
            name = 'Tier 2 Division Appraisals';
        } else {
            if (this.state.data && this.state.data.tier_governance) {
                const tg = this.state.data.tier_governance;
                if (tg.planning.tier1.appraisals.total > 0 && tg.planning.tier2.appraisals.total === 0 && tg.hr.tier3.appraisals.total === 0) {
                    model = 'corporate.appraisal';
                    name = 'Tier 1 Corporate Appraisals';
                } else if (tg.planning.tier2.appraisals.total > 0 && tg.hr.tier3.appraisals.total === 0) {
                    model = 't2.appraisal';
                    name = 'Tier 2 Division Appraisals';
                }
            }
        }

        const domain = [];
        if (this.state.filters.fiscal_year_id) {
            domain.push(['fiscal_year_id', '=', this.state.filters.fiscal_year_id]);
        }
        if (this.state.filters.appraisal_period_id) {
            domain.push(['appraisal_period_id', '=', this.state.filters.appraisal_period_id]);
        }
        if (this.state.filters.operating_unit_id) {
            domain.push(['operating_unit_id', '=', this.state.filters.operating_unit_id]);
        }
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', this.state.filters.department_id]);
        }
        this.openFilteredList(model, domain, name);
    }

    openRejectionsOrPending(target) {
        const state = target || (this.state.data.kpis.rejected_count > 0 ? 'rejected' : 'notified');
        const tier = this.state.filters.tier;
        let model = 't3.appraisal';
        let name = state === 'rejected' ? 'Rejected Appraisals' : 'Pending Acceptance Appraisals';

        if (tier === 't1') {
            model = 'corporate.appraisal';
            name = state === 'rejected' ? 'T1 Corporate Rejections' : 'T1 Corporate Pending Appraisals';
        } else if (tier === 't2') {
            model = 't2.appraisal';
            name = state === 'rejected' ? 'T2 Division Rejections' : 'T2 Division Pending Appraisals';
        } else {
            if (this.state.data && this.state.data.tier_governance) {
                const tg = this.state.data.tier_governance;
                if (tg.hr.tier3.appraisals[state] > 0 || tg.hr.tier3.scorecards[state] > 0) {
                    model = 't3.appraisal';
                } else if (tg.planning.tier2.appraisals[state] > 0 || tg.planning.tier2.scorecards[state] > 0) {
                    model = 't2.appraisal';
                } else {
                    model = 'corporate.appraisal';
                }
            }
        }

        const domain = [['state', '=', state]];
        if (this.state.filters.fiscal_year_id) {
            domain.push(['fiscal_year_id', '=', this.state.filters.fiscal_year_id]);
        }
        if (this.state.filters.appraisal_period_id) {
            domain.push(['appraisal_period_id', '=', this.state.filters.appraisal_period_id]);
        }
        this.openFilteredList(model, domain, name);
    }

    openTierStatusList(model, state, title) {
        const domain = [];
        if (state && state !== 'all') {
            if (state === 'confirmed' && model.includes('scorecard')) {
                domain.push(['state', 'in', ['confirmed', 'appraisal_started']]);
            } else {
                domain.push(['state', '=', state]);
            }
        }
        if (this.state.filters.fiscal_year_id) {
            domain.push(['fiscal_year_id', '=', this.state.filters.fiscal_year_id]);
        }
        if (this.state.filters.appraisal_period_id) {
            domain.push(['appraisal_period_id', '=', this.state.filters.appraisal_period_id]);
        }
        if (this.state.filters.operating_unit_id) {
            domain.push(['operating_unit_id', '=', this.state.filters.operating_unit_id]);
        }
        if (this.state.filters.department_id) {
            domain.push(['department_id', '=', this.state.filters.department_id]);
        }
        this.openFilteredList(model, domain, title);
    }
}

registry.category("actions").add("performance_dashboard_client_action", PerformanceDashboard);
