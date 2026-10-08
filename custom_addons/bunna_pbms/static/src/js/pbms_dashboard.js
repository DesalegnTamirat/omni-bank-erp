/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// ============ BUNNA BANK S.C. 6 OFFICIAL BRAND COLORS ============
// Primary Colors: Image 4 & 6
// Secondary Colors: Image 1, 2, 3, 5
const BUNNA = {
    primaryMaroon: '#541718',      // Swatch 6: Primary (C:39 M:89 Y:79 K:60 | R:84 G:24 B:24)
    deepPine: '#1E2917',           // Swatch 5: Secondary (C:73 M:56 Y:81 K:73 | R:30 G:41 B:23)
    primarySlate: '#1D2B32',       // Swatch 4: Deep Slate (C:83 M:67 Y:58 K:62 | R:29 G:43 B:50)
    forestGreen: '#425727',        // Swatch 1: Forest Olive (C:70 M:44 Y:100 K:39 | R:66 G:87 B:39)
    bronzeOlive: '#726732',        // Swatch 2: Bronze Olive (C:50 M:47 Y:92 K:26 | R:114 G:103 B:50)
    terracotta: '#C17540',         // Swatch 3: Terracotta (C:20 M:60 Y:84 K:5 | R:193 G:117 B:64)

    // Aliases
    primary: '#541718',
    secondary: '#1E2917',
    accent: '#1D2B32',
    success: '#425727',
    danger: '#541718',
    warning: '#C17540',
    info: '#726732',
    dark: '#1E2917',
    light: '#F4F6F7',
};

// Stage labels for display
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

// Stage colors based on Bunna Bank 6 official colors
const STAGE_COLORS = {
    draft: { bg: BUNNA.deepPine, light: '#EAECE8' },
    submitted: { bg: BUNNA.terracotta, light: '#FAF1EB' },
    info_requested: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    returned: { bg: BUNNA.primaryMaroon, light: '#F6EBEB' },
    rejected: { bg: BUNNA.primaryMaroon, light: '#F6EBEB' },
    district_approved: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    district_endorsed: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    chief_review: { bg: BUNNA.primarySlate, light: '#EAEFF2' },
    people_solutions_review: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    cpco_review: { bg: BUNNA.terracotta, light: '#FAF1EB' },
    committee_review: { bg: BUNNA.primarySlate, light: '#EAEFF2' },
    ceo_approval: { bg: BUNNA.primaryMaroon, light: '#F6EBEB' },
    ho_endorse: { bg: BUNNA.forestGreen, light: '#EDF3E8' },
    cpco_endorse: { bg: BUNNA.forestGreen, light: '#EDF3E8' },
    ho_reviewed: { bg: BUNNA.forestGreen, light: '#EDF3E8' },
    approved: { bg: BUNNA.forestGreen, light: '#EDF3E8' },
    closed: { bg: BUNNA.primarySlate, light: '#EAEFF2' },
    in_review: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    in_review_or_submitted: { bg: BUNNA.bronzeOlive, light: '#F6F4EB' },
    returned_rejected: { bg: BUNNA.primaryMaroon, light: '#F6EBEB' },
};

// Chart colors based on Bunna Bank 6 official colors
const CHART_COLORS = [
    BUNNA.primaryMaroon,    // #541718 (Primary Maroon)
    BUNNA.deepPine,         // #1E2917 (Secondary Pine)
    BUNNA.forestGreen,      // #425727 (Forest Olive)
    BUNNA.primarySlate,     // #1D2B32 (Slate)
    BUNNA.terracotta,       // #C17540 (Terracotta)
    BUNNA.bronzeOlive,      // #726732 (Bronze Olive)
    '#742526',              // Maroon Accent
    '#304123',              // Deep Pine Light
];

// Model configurations with Bunna Bank colors (keyed by planning category id)
const MODEL_CONFIG = {
    'deposit': {
        label: 'Deposit Mobilization',
        icon: 'fa-university',
        color: BUNNA.forestGreen  // Swatch 1: #425727
    },
    'customer_base': {
        label: 'Customer Base',
        icon: 'fa-users',
        color: BUNNA.bronzeOlive  // Swatch 2: #726732
    },
    'fx': {
        label: 'FX Mobilization',
        icon: 'fa-exchange-alt',
        color: BUNNA.terracotta   // Swatch 3: #C17540
    },
    'digital_banking': {
        label: 'Digital Banking',
        icon: 'fa-mobile-alt',
        color: BUNNA.primarySlate // Swatch 4: #1D2B32
    },
    'loan_disbursement_collection': {
        label: 'Loan Disbursement & Collection',
        icon: 'fa-hand-holding-usd',
        color: BUNNA.forestGreen
    },
    'loan_outstanding': {
        label: 'Loan & Advances Outstanding',
        icon: 'fa-file-invoice-dollar',
        color: BUNNA.bronzeOlive
    },
    'general_expense': {
        label: 'General Expense',
        icon: 'fa-receipt',
        color: BUNNA.primaryMaroon// Swatch 6: #541718
    },
    'manpower': {
        label: 'Workforce',
        icon: 'fa-user-tie',
        color: BUNNA.deepPine     // Swatch 5: #1E2917
    },
    'fixed_asset': {
        label: 'Fixed Asset',
        icon: 'fa-building',
        color: BUNNA.bronzeOlive  // Swatch 2: #726732
    },
    'credit_portfolio': {
        label: 'Credit Portfolio',
        icon: 'fa-briefcase',
        color: BUNNA.terracotta
    },
    'initiative_budget': {
        label: 'Initiative Budget',
        icon: 'fa-lightbulb',
        color: BUNNA.primarySlate
    },
};

const IN_REVIEW_STAGES = [
    'district_approved', 'district_endorsed', 'chief_review',
    'people_solutions_review', 'cpco_review', 'committee_review',
    'ceo_approval', 'ho_endorse', 'cpco_endorse', 'ho_reviewed'
];

// Map stages to their filter domains
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

// Plan types for dropdown (category ids of the unified pbms.planning.category)
const PLAN_TYPES = [
    { id: 'all', name: 'All Plans' },
    { id: 'deposit', name: 'Deposit Mobilization' },
    { id: 'customer_base', name: 'Customer Base' },
    { id: 'fx', name: 'FX Mobilization' },
    { id: 'digital_banking', name: 'Digital Banking' },
    { id: 'loan_disbursement_collection', name: 'Loan Disbursement & Collection' },
    { id: 'loan_outstanding', name: 'Loan & Advances Outstanding' },
    { id: 'general_expense', name: 'General Expense' },
    { id: 'manpower', name: 'Workforce' },
    { id: 'fixed_asset', name: 'Fixed Asset' },
    { id: 'credit_portfolio', name: 'Credit Portfolio' },
    { id: 'initiative_budget', name: 'Initiative Budget' },
];

export class PbmsDashboard extends Component {
    static template = "bunna_pbms.PbmsDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.chartRef = useRef('chartCanvas');
        this.statusChartRef = useRef('statusChartCanvas');
        this.trendChartRef = useRef('trendChartCanvas');

        this.state = useState({
            loading: true,
            cycles: [],
            cycleId: false,
            selectedModel: 'all',
            cycleDropdownOpen: false,
            planTypeDropdownOpen: false,
            planTypes: PLAN_TYPES,
            submission: [],
            kpi: [],
            currentPage: 1,
            itemsPerPage: 12,
            chartsLoaded: false,
        });

        // Expose constants to template
        this.STAGE_LABELS = STAGE_LABELS;
        this.STAGE_COLORS = STAGE_COLORS;
        this.MODEL_CONFIG = MODEL_CONFIG;
        this.CHART_COLORS = CHART_COLORS;
        this.STAGE_DOMAINS = STAGE_DOMAINS;
        this.PLAN_TYPES = PLAN_TYPES;
        this.BUNNA = BUNNA;
        this.charts = {};

        this.onDocumentClick = (ev) => {
            // Close dropdowns when clicking outside
            if (this.state.cycleDropdownOpen || this.state.planTypeDropdownOpen) {
                this.state.cycleDropdownOpen = false;
                this.state.planTypeDropdownOpen = false;
            }
        };

        onWillStart(async () => {
            const data = await this.orm.call("pbms.dashboard", "get_dashboard_data", [this.state.cycleId || false]);
            this.state.cycles = data.cycles || [];
            this.state.cycleId = data.active_cycle_id || (data.cycles.length ? data.cycles[0].id : false);
            this.state.submission = data.submission || [];
            this.state.kpi = data.kpi || [];
            if (data.plan_types && data.plan_types.length) {
                this.state.planTypes = data.plan_types;
                if (!this.state.planTypes.some(p => p.id === this.state.selectedModel)) {
                    this.state.selectedModel = 'all';
                }
            }
            this.state.loading = false;
        });

        onMounted(() => {
            this.initCharts();
            window.addEventListener("click", this.onDocumentClick);
        });

        onWillUnmount(() => {
            window.removeEventListener("click", this.onDocumentClick);
        });
    }

    async loadData() {
        this.state.loading = true;
        this.state.currentPage = 1;
        const data = await this.orm.call("pbms.dashboard", "get_dashboard_data", [this.state.cycleId]);
        if (data.cycles && (!this.state.cycles || !this.state.cycles.length)) {
            this.state.cycles = data.cycles;
        }
        this.state.submission = data.submission || [];
        this.state.kpi = data.kpi || [];
        if (data.plan_types && data.plan_types.length) {
            this.state.planTypes = data.plan_types;
            if (!this.state.planTypes.some(p => p.id === this.state.selectedModel)) {
                this.state.selectedModel = 'all';
            }
        }
        this.state.loading = false;

        setTimeout(() => this.initCharts(), 300);
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
        this.state.currentPage = 1;
        this.render();
        setTimeout(() => this.initCharts(), 300);
    }

    getSelectedCycleName() {
        const cycle = this.state.cycles.find(c => c.id === this.state.cycleId);
        return cycle ? `${cycle.name} (${cycle.state})` : "Select Cycle";
    }

    getSelectedPlanTypeName() {
        const types = this.state.planTypes || this.PLAN_TYPES;
        const plan = types.find(p => p.id === this.state.selectedModel);
        return plan ? plan.name : "All Plans";
    }

    async onCycleChange(ev) {
        this.state.cycleId = parseInt(ev.target.value, 10) || false;
        await this.loadData();
    }

    async onPlanTypeChange(ev) {
        this.state.selectedModel = ev.target.value;
        this.state.currentPage = 1;
        this.render();
        setTimeout(() => this.initCharts(), 300);
    }

    initCharts() {
        this.destroyCharts();
        this.createDonutChart();
        this.createStatusChart();
        this.createTrendChart();
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

    // ========== DATA METHODS ==========

    getFilteredData() {
        if (this.state.selectedModel === 'all') {
            return this.state.submission;
        }
        return this.state.submission.filter(
            item => item.model === this.state.selectedModel
        );
    }

    getPaginatedData() {
        const filtered = this.getFilteredData();
        const start = (this.state.currentPage - 1) * this.state.itemsPerPage;
        const end = start + this.state.itemsPerPage;
        return filtered.slice(start, end);
    }

    getTotalPages() {
        return Math.ceil(this.getFilteredData().length / this.state.itemsPerPage);
    }

    getPageNumbers() {
        const totalPages = this.getTotalPages();
        const current = this.state.currentPage;
        const pages = [];

        if (totalPages <= 7) {
            for (let i = 1; i <= totalPages; i++) {
                pages.push(i);
            }
        } else {
            pages.push(1);
            if (current > 3) {
                pages.push('...');
            }
            for (let i = Math.max(2, current - 1); i <= Math.min(totalPages - 1, current + 1); i++) {
                pages.push(i);
            }
            if (current < totalPages - 2) {
                pages.push('...');
            }
            pages.push(totalPages);
        }
        return pages;
    }

    goToPage(page) {
        if (page === '...') return;
        const totalPages = this.getTotalPages();
        if (page >= 1 && page <= totalPages) {
            this.state.currentPage = page;
            this.render();
            setTimeout(() => this.initCharts(), 300);
        }
    }

    previousPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
            this.render();
            setTimeout(() => this.initCharts(), 300);
        }
    }

    nextPage() {
        if (this.state.currentPage < this.getTotalPages()) {
            this.state.currentPage++;
            this.render();
            setTimeout(() => this.initCharts(), 300);
        }
    }

    getStatusCounts(planData) {
        const counts = {};
        let total = 0;
        for (const stage in STAGE_LABELS) {
            const count = this.stageTotalFor(planData, stage);
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
        let total = 0;
        for (const uType in formatEntry.counts) {
            total += formatEntry.counts[uType][stageKey] || 0;
        }
        return total;
    }

    kpiTotalFor(sourceModel) {
        return this.state.kpi
            .filter((row) => row.source_model === sourceModel)
            .reduce((sum, row) => sum + row.annual_total, 0);
    }

    kpiSourceModels() {
        const models = [...new Set(this.state.kpi.map((row) => row.source_model))];
        if (this.state.selectedModel !== 'all') {
            return models.filter(m => m === this.state.selectedModel);
        }
        return models;
    }

    formatAmount(value) {
        return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value || 0);
    }

    // ========== CLICK HANDLERS ==========

    openModelView(modelName, stage = null, viewType = "kanban") {
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

        const actionContext = {
            'default_cycle_id': this.state.cycleId,
        };
        if (modelName && modelName !== 'all') {
            actionContext['default_category'] = modelName;
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pbms.planning.category",
            name: this.MODEL_CONFIG[modelName]?.label || "Plan",
            views: [[false, viewType], [false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
            context: actionContext,
        });
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

        const actionContext = {
            'default_cycle_id': this.state.cycleId,
        };
        if (modelName && modelName !== 'all') {
            actionContext['default_category'] = modelName;
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "pbms.planning.category",
            name: `${this.MODEL_CONFIG[modelName]?.label || modelName} - ${STAGE_LABELS[stage] || stage}`,
            views: [[false, "list"], [false, "form"]],
            target: "current",
            domain: domain,
            context: actionContext,
        });
    }

    openChartSegment(modelName) {
        this.openModelView(modelName, null, "list");
    }

    // ========== GETTER METHODS ==========

    getModelLabel(modelName) {
        return this.MODEL_CONFIG[modelName]?.label || modelName;
    }

    getModelIcon(modelName) {
        return this.MODEL_CONFIG[modelName]?.icon || 'fa-file';
    }

    getModelColor(modelName) {
        return this.MODEL_CONFIG[modelName]?.color || BUNNA.primary;
    }

    getStatusColor(status) {
        return this.STAGE_COLORS[status]?.bg || '#6c757d';
    }

    getStatusLightColor(status) {
        return this.STAGE_COLORS[status]?.light || '#e9ecef';
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

    // ========== CHART METHODS ==========

    createDonutChart() {
        const canvas = this.chartRef.el;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const filteredData = this.getFilteredData();

        if (filteredData.length === 0) {
            return;
        }

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
                            padding: 15,
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
                                return `${context.label}: ${context.parsed} (${percentage}%) - Click to view`;
                            }
                        }
                    }
                },
                cutout: '65%',
            }
        });
    }

    createStatusChart() {
        const canvas = this.statusChartRef.el;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const filteredData = this.getFilteredData();

        if (filteredData.length === 0) {
            return;
        }

        const stages = Object.keys(STAGE_LABELS);
        const stageLabels = stages.map(s => STAGE_LABELS[s]);

        const datasets = filteredData.slice(0, 8).map((plan) => {
            const color = this.getModelColor(plan.model);
            const counts = stages.map(stage => this.stageTotalFor(plan, stage));
            return {
                label: plan.label,
                data: counts,
                backgroundColor: color + '80',
                borderColor: color,
                borderWidth: 2,
                borderRadius: 4,
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
                            font: { size: 10, weight: '500' },
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 15,
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.parsed.y} - Click to view`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                        },
                        grid: {
                            color: 'rgba(0,0,0,0.05)',
                        }
                    },
                    x: {
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

    createTrendChart() {
        const canvas = this.trendChartRef.el;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const filteredData = this.getFilteredData();

        if (filteredData.length === 0) {
            return;
        }

        const months = ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'];

        const datasets = filteredData.slice(0, 5).map((plan, index) => {
            const color = this.CHART_COLORS[index % this.CHART_COLORS.length];
            const total = this.getStatusCounts(plan).total;
            const baseValue = Math.max(1, Math.round(total / 12));
            const trendData = months.map((_, i) => {
                const seasonal = 1 + 0.3 * Math.sin((i / 12) * 2 * Math.PI);
                const growth = 1 + (i / 12) * 0.2;
                return Math.round(baseValue * seasonal * growth);
            });

            return {
                label: plan.label,
                data: trendData,
                borderColor: color,
                backgroundColor: color + '15',
                fill: true,
                tension: 0.4,
                pointBackgroundColor: color,
                pointBorderColor: '#ffffff',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 7,
                borderWidth: 3,
            };
        });

        this.charts.trend = new Chart(ctx, {
            type: 'line',
            data: {
                labels: months,
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: (event, elements) => {
                    if (elements.length > 0) {
                        const element = elements[0];
                        const datasetIndex = element.datasetIndex;
                        const modelName = filteredData[datasetIndex]?.model;
                        if (modelName) {
                            this.openModelView(modelName, null, "list");
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            font: { size: 10, weight: '500' },
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 15,
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.parsed.y} - Click to view`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                        },
                        grid: {
                            color: 'rgba(0,0,0,0.05)',
                        }
                    },
                    x: {
                        grid: {
                            display: false,
                        }
                    }
                },
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
            }
        });
    }
}

registry.category("actions").add("pbms_dashboard", PbmsDashboard);