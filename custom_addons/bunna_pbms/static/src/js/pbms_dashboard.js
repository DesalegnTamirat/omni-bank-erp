/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Bunna Bank S.C. Official Brand Colors
const BUNNA = {
    primaryMaroon: '#541718',      // Swatch 6: Primary
    deepPine: '#1E2917',           // Swatch 5: Secondary
    primarySlate: '#1D2B32',       // Swatch 4: Deep Slate
    forestGreen: '#425727',        // Swatch 1: Forest Olive
    bronzeOlive: '#726732',        // Swatch 2: Bronze Olive
    terracotta: '#C17540',         // Swatch 3: Terracotta
    primary: '#541718',
    secondary: '#1E2917',
};

const STAGE_LABELS = {
    draft: "Draft",
    submitted: "Submitted",
    info_requested: "Info Requested",
    returned: "Returned",
    rejected: "Rejected",
    district_approved: "District Approved",
    district_endorsed: "District Endorsed",
    chief_review: "Chief Review",
    people_solutions_review: "People Solutions Review",
    cpco_review: "CPCO Review",
    committee_review: "Committee Review",
    ceo_approval: "CEO Approval",
    ho_endorse: "HO Endorsement",
    cpco_endorse: "CPCO Endorsement",
    ho_reviewed: "Head Office Reviewed",
    approved: "Approved",
    closed: "Closed",
    in_review: "In Review",
    in_review_or_submitted: "In Review / Submitted",
    returned_rejected: "Revision / Rejected",
};

const IN_REVIEW_STAGES = [
    'district_approved', 'district_endorsed', 'chief_review',
    'people_solutions_review', 'cpco_review', 'committee_review',
    'ceo_approval', 'ho_endorse', 'cpco_endorse', 'ho_reviewed'
];

const STAGE_DOMAINS = {
    draft: [['state', '=', 'draft']],
    submitted: [['state', '=', 'submitted']],
    info_requested: [['state', '=', 'info_requested']],
    returned: [['state', '=', 'returned']],
    rejected: [['state', '=', 'rejected']],
    district_approved: [['state', '=', 'district_approved']],
    district_endorsed: [['state', '=', 'district_endorsed']],
    chief_review: [['state', '=', 'chief_review']],
    people_solutions_review: [['state', '=', 'people_solutions_review']],
    cpco_review: [['state', '=', 'cpco_review']],
    committee_review: [['state', '=', 'committee_review']],
    ceo_approval: [['state', '=', 'ceo_approval']],
    ho_endorse: [['state', '=', 'ho_endorse']],
    cpco_endorse: [['state', '=', 'cpco_endorse']],
    ho_reviewed: [['state', '=', 'ho_reviewed']],
    approved: [['state', '=', 'approved']],
    closed: [['state', '=', 'closed']],
    in_review: [['state', 'in', IN_REVIEW_STAGES]],
    in_review_or_submitted: [['state', 'in', ['submitted', ...IN_REVIEW_STAGES]]],
    returned_rejected: [['state', 'in', ['returned', 'rejected', 'info_requested']]],
};

const MODEL_CONFIG = {
    'deposit': { label: 'Deposit Mobilization', color: '#425727' },
    'customer_base': { label: 'Customer Base', color: '#726732' },
    'fx': { label: 'FX Mobilization', color: '#C17540' },
    'digital_banking': { label: 'Digital Banking', color: '#1D2B32' },
    'general_expense': { label: 'General Expense', color: '#541718' },
    'manpower': { label: 'Workforce', color: '#1E2917' },
    'fixed_asset': { label: 'Fixed Asset Requirement', color: '#8A7338' },
    'loan_disbursement_collection': { label: 'Loan Disbursement & Collection', color: '#2D5A27' },
    'loan_outstanding': { label: 'Loan & Advances Outstanding', color: '#9C5823' },
    'credit_portfolio': { label: 'Credit Portfolio', color: '#633215' },
    'initiative_budget': { label: 'Initiative Budget', color: '#2E4057' },
};

export class PbmsDashboard extends Component {
    static template = "bunna_pbms.PbmsDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.chartRef = useRef('chartCanvas');
        this.statusChartRef = useRef('statusChartCanvas');

        this.state = useState({
            loading: true,
            cycles: [],
            cycleId: false,
            selectedModel: 'all',
            cycleDropdownOpen: false,
            planTypeDropdownOpen: false,
            planTypes: [{ id: 'all', name: 'All Plans' }],
            submission: [],
            chartsLoaded: false,
        });

        this.charts = {};

        this.onDocumentClick = (ev) => {
            if (this.state.cycleDropdownOpen || this.state.planTypeDropdownOpen) {
                this.state.cycleDropdownOpen = false;
                this.state.planTypeDropdownOpen = false;
            }
        };

        onWillStart(async () => {
            try {
                const data = await this.orm.call("pbms.dashboard", "get_dashboard_data", [this.state.cycleId || false]);
                this.state.cycles = data.cycles || [];
                this.state.cycleId = data.active_cycle_id || (data.cycles.length ? data.cycles[0].id : false);
                this.state.submission = data.submission || [];
                if (data.plan_types && data.plan_types.length) {
                    this.state.planTypes = data.plan_types;
                }
            } catch (err) {
                console.error("Error loading PBMS dashboard data:", err);
            } finally {
                this.state.loading = false;
            }
        });

        onMounted(() => {
            this.initCharts();
            window.addEventListener("click", this.onDocumentClick);
        });

        onWillUnmount(() => {
            this.destroyCharts();
            window.removeEventListener("click", this.onDocumentClick);
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("pbms.dashboard", "get_dashboard_data", [this.state.cycleId]);
            if (data.cycles && (!this.state.cycles || !this.state.cycles.length)) {
                this.state.cycles = data.cycles;
            }
            this.state.submission = data.submission || [];
            if (data.plan_types && data.plan_types.length) {
                this.state.planTypes = data.plan_types;
                if (!this.state.planTypes.some(p => p.id === this.state.selectedModel)) {
                    this.state.selectedModel = 'all';
                }
            }
        } catch (err) {
            console.error("Error refreshing PBMS dashboard data:", err);
        } finally {
            this.state.loading = false;
            setTimeout(() => this.initCharts(), 100);
        }
    }

    toggleCycleDropdown(ev) {
        if (ev) ev.stopPropagation();
        this.state.cycleDropdownOpen = !this.state.cycleDropdownOpen;
        this.state.planTypeDropdownOpen = false;
    }

    togglePlanTypeDropdown(ev) {
        if (ev) ev.stopPropagation();
        this.state.planTypeDropdownOpen = !this.state.planTypeDropdownOpen;
        this.state.cycleDropdownOpen = false;
    }

    async selectCycle(cycleId) {
        this.state.cycleId = cycleId;
        this.state.cycleDropdownOpen = false;
        await this.loadData();
    }

    async selectPlanType(planId) {
        this.state.selectedModel = planId;
        this.state.planTypeDropdownOpen = false;
        this.render();
        setTimeout(() => this.initCharts(), 100);
    }

    getSelectedCycleName() {
        const cycle = this.state.cycles.find(c => c.id === this.state.cycleId);
        return cycle ? `${cycle.name} (${cycle.state})` : "Select Cycle";
    }

    getSelectedPlanTypeName() {
        const plan = this.state.planTypes.find(p => p.id === this.state.selectedModel);
        return plan ? plan.name : "All Plans";
    }

    initCharts() {
        this.destroyCharts();
        this.createDonutChart();
        this.createStatusChart();
        this.state.chartsLoaded = true;
    }

    destroyCharts() {
        Object.values(this.charts).forEach(chart => {
            if (chart) {
                chart.destroy();
            }
        });
        this.charts = {};
    }

    getFilteredData() {
        if (this.state.selectedModel === 'all') {
            return this.state.submission;
        }
        return this.state.submission.filter(
            item => item.model === this.state.selectedModel
        );
    }

    getStatusCounts(planData) {
        const counts = {};
        let total = 0;
        for (const stage in STAGE_LABELS) {
            let count = 0;
            for (const uType in planData.counts) {
                count += planData.counts[uType][stage] || 0;
            }
            counts[stage] = count;
            total += count;
        }
        counts.in_review = (
            (counts.district_approved || 0) +
            (counts.district_endorsed || 0) +
            (counts.chief_review || 0) +
            (counts.people_solutions_review || 0) +
            (counts.cpco_review || 0) +
            (counts.committee_review || 0) +
            (counts.ceo_approval || 0) +
            (counts.ho_endorse || 0) +
            (counts.cpco_endorse || 0) +
            (counts.ho_reviewed || 0)
        );
        counts.returned_rejected = (counts.returned || 0) + (counts.rejected || 0) + (counts.info_requested || 0);
        counts.total = total;
        return counts;
    }

    stageTotalFor(formatEntry, stageKey) {
        if (stageKey === 'in_review') {
            return this.getStatusCounts(formatEntry).in_review;
        }
        if (stageKey === 'in_review_or_submitted') {
            const counts = this.getStatusCounts(formatEntry);
            return (counts.submitted || 0) + (counts.in_review || 0);
        }
        if (stageKey === 'returned_rejected') {
            return this.getStatusCounts(formatEntry).returned_rejected;
        }
        let total = 0;
        for (const uType in formatEntry.counts) {
            total += formatEntry.counts[uType][stageKey] || 0;
        }
        return total;
    }

    getModelColor(modelName) {
        return MODEL_CONFIG[modelName]?.color || BUNNA.primaryMaroon;
    }

    getTotalSubmissions() {
        let total = 0;
        for (const plan of this.getFilteredData()) {
            total += this.getStatusCounts(plan).total;
        }
        return total;
    }

    getTotalByStatus(status) {
        if (status === 'in_review') {
            let total = 0;
            for (const plan of this.getFilteredData()) {
                total += this.getStatusCounts(plan).in_review;
            }
            return total;
        }
        if (status === 'in_review_or_submitted') {
            let total = 0;
            for (const plan of this.getFilteredData()) {
                const counts = this.getStatusCounts(plan);
                total += (counts.submitted || 0) + (counts.in_review || 0);
            }
            return total;
        }
        if (status === 'returned_rejected') {
            let total = 0;
            for (const plan of this.getFilteredData()) {
                total += this.getStatusCounts(plan).returned_rejected;
            }
            return total;
        }
        let total = 0;
        for (const plan of this.getFilteredData()) {
            total += this.stageTotalFor(plan, status);
        }
        return total;
    }

    openKPIView(stage = null) {
        const domain = [];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', this.state.cycleId]);
        }
        if (this.state.selectedModel && this.state.selectedModel !== 'all') {
            domain.push(['category', '=', this.state.selectedModel]);
        } else if (this.state.planTypes && this.state.planTypes.length) {
            const allowedCats = this.state.planTypes.filter(p => p.id !== 'all').map(p => p.id);
            if (allowedCats.length) {
                domain.push(['category', 'in', allowedCats]);
            }
        }
        if (stage && STAGE_DOMAINS[stage]) {
            domain.push(...STAGE_DOMAINS[stage]);
        }

        const actionContext = {
            'default_cycle_id': this.state.cycleId,
        };
        if (this.state.selectedModel && this.state.selectedModel !== 'all') {
            actionContext['default_category'] = this.state.selectedModel;
        }

        let stageName = "All Submissions";
        if (stage === 'draft') stageName = "Draft Plans";
        else if (stage === 'in_review_or_submitted') stageName = "In Review / Submitted Plans";
        else if (stage === 'approved') stageName = "Approved Plans";
        else if (stage && STAGE_LABELS[stage]) stageName = `${STAGE_LABELS[stage]} Plans`;

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pbms.planning.category",
            name: stageName,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            target: "current",
            domain: domain,
            context: actionContext,
        });
    }

    openChartSegment(modelName) {
        const domain = [];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', this.state.cycleId]);
        }
        if (modelName && modelName !== 'all') {
            domain.push(['category', '=', modelName]);
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pbms.planning.category",
            name: MODEL_CONFIG[modelName]?.label || modelName,
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            target: "current",
            domain: domain,
            context: { 'default_cycle_id': this.state.cycleId, 'default_category': modelName },
        });
    }

    openPlanByStatus(modelName, stage) {
        const domain = [];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', this.state.cycleId]);
        }
        if (modelName && modelName !== 'all') {
            domain.push(['category', '=', modelName]);
        }
        if (stage && STAGE_DOMAINS[stage]) {
            domain.push(...STAGE_DOMAINS[stage]);
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pbms.planning.category",
            name: `${MODEL_CONFIG[modelName]?.label || modelName} - ${STAGE_LABELS[stage] || stage}`,
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
            context: { 'default_cycle_id': this.state.cycleId, 'default_category': modelName },
        });
    }

    createDonutChart() {
        const canvas = this.chartRef?.el;
        if (!canvas || typeof Chart === 'undefined') return;

        const ctx = canvas.getContext('2d');
        const filteredData = this.getFilteredData();

        if (filteredData.length === 0) return;

        const labels = filteredData.map(p => p.label);
        const data = filteredData.map(p => this.getStatusCounts(p).total);
        const colors = filteredData.map(p => this.getModelColor(p.model));

        this.charts.donut = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors,
                    borderColor: '#ffffff',
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                resizeDelay: 100,
                onClick: (event, elements) => {
                    if (elements.length > 0) {
                        const index = elements[0].index;
                        const modelName = filteredData[index].model;
                        this.openChartSegment(modelName);
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 12,
                            boxWidth: 10,
                            boxHeight: 10,
                            font: { size: 11, weight: '500' },
                            usePointStyle: true,
                            pointStyle: 'circle',
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = total > 0 ? Math.round((context.parsed / total) * 100) : 0;
                                return ` ${context.label}: ${context.parsed} (${percentage}%) - Click to view`;
                            }
                        }
                    }
                },
                cutout: '65%',
            }
        });
    }

    createStatusChart() {
        const canvas = this.statusChartRef?.el;
        if (!canvas || typeof Chart === 'undefined') return;

        const ctx = canvas.getContext('2d');
        const filteredData = this.getFilteredData();

        if (filteredData.length === 0) return;

        const stages = [
            'draft',
            'submitted',
            'chief_review',
            'district_endorsed',
            'ho_reviewed',
            'approved',
            'returned',
        ];
        const stageLabels = stages.map(s => STAGE_LABELS[s] || s);

        const datasets = filteredData.map((plan) => {
            const color = this.getModelColor(plan.model);
            const counts = stages.map(stage => this.stageTotalFor(plan, stage));
            return {
                label: plan.label,
                data: counts,
                backgroundColor: color,
                borderColor: color,
                borderWidth: 1,
                borderRadius: 2,
            };
        });

        this.charts.status = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: stageLabels,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                resizeDelay: 100,
                onClick: (event, elements) => {
                    if (elements.length > 0) {
                        const element = elements[0];
                        const datasetIndex = element.datasetIndex;
                        const dataIndex = element.index;
                        const modelName = filteredData[datasetIndex]?.model;
                        const stage = stages[dataIndex];
                        if (modelName && stage) {
                            this.openPlanByStatus(modelName, stage);
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            boxWidth: 10,
                            boxHeight: 10,
                            font: { size: 10, weight: '500' },
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 10,
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return ` ${context.dataset.label}: ${context.parsed.y} - Click to view`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 2,
                            precision: 0,
                        },
                        grid: {
                            color: 'rgba(0,0,0,0.06)',
                        }
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 45,
                            font: { size: 10 },
                        },
                        grid: {
                            display: false,
                        }
                    }
                },
                barPercentage: 0.7,
                categoryPercentage: 0.8,
            }
        });
    }
}

registry.category("actions").add("pbms_dashboard", PbmsDashboard);