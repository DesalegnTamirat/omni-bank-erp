/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, useEffect, useState, useRef } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

export class CompetencyDashboard extends Component {
    static template = "competency_management.CompetencyDashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.tnaCanvasRef = useRef("tnaChart");
        this.pillarCanvasRef = useRef("pillarChart");
        this.radarCanvasRef = useRef("radarChart");
        this.trendCanvasRef = useRef("trendChart");

        this.state = useState({
            persona: "executive",
            cycleId: false,
            departmentId: false,
            operatingUnitId: false,
            loading: true,
            error: false,
            alertDismissed: false,
            radarHasData: false,
            data: {
                is_dept_readonly: false,
                is_ou_readonly: false,
                user: { name: "", is_admin: false, is_supervisor: false },
                cycle: { id: false, name: "", deadline: "" },
                all_cycles: [],
                all_departments: [],
                all_operating_units: [],
                stats: { has_data: false, bank_avg_gap: 0.0, total_assessments: 0, below_cnt: 0, meets_cnt: 0, exceeds_cnt: 0 },
                charts: { tna_donut: {}, pillar_bar: {}, employee_radar: {}, employee_trend: {} },
                team_roster: [],
                heatmap_rows: [],
            }
        });

        this.tnaChartInstance = null;
        this.pillarChartInstance = null;
        this.radarChartInstance = null;
        this.trendChartInstance = null;

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });

        onMounted(async () => {
            await this.loadData();
        });

        useEffect(
            () => {
                if (!this.state.loading && !this.state.error) {
                    this.renderCharts();
                }
            },
            () => [this.state.loading, this.state.cycleId, this.state.departmentId, this.state.operatingUnitId]
        );
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const result = await this.orm.call(
                "competency.dashboard",
                "get_dashboard_data",
                [],
                {
                    cycle_id: this.state.cycleId || false,
                    department_id: this.state.departmentId || false,
                    operating_unit_id: this.state.operatingUnitId || false,
                }
            );

            this.state.data = result;
            this.state.persona = result.persona || "executive";
            if (!this.state.cycleId && result.cycle && result.cycle.id) {
                this.state.cycleId = result.cycle.id;
            } else if (!this.state.cycleId && result.all_cycles && result.all_cycles.length > 0) {
                this.state.cycleId = result.all_cycles[0].id;
            }
            if (result.is_dept_readonly || (!this.state.departmentId && result.selected_department_id)) {
                this.state.departmentId = result.selected_department_id;
            }
            if (result.is_ou_readonly || (!this.state.operatingUnitId && result.selected_operating_unit_id)) {
                this.state.operatingUnitId = result.selected_operating_unit_id;
            }

            this.state.loading = false;
        } catch (e) {
            console.error("Failed to load competency dashboard data:", e);
            this.state.error = true;
            this.state.loading = false;
            this.state.data = {
                is_dept_readonly: false,
                is_ou_readonly: false,
                user: { name: "", is_admin: false, is_supervisor: false },
                cycle: { id: false, name: "", deadline: "" },
                all_cycles: [],
                all_departments: [],
                all_operating_units: [],
                stats: { has_data: false, bank_avg_gap: 0.0, total_assessments: 0, below_cnt: 0, meets_cnt: 0, exceeds_cnt: 0 },
                charts: { tna_donut: {}, pillar_bar: {}, employee_radar: {}, employee_trend: {} },
                team_roster: [],
                heatmap_rows: [],
            };
        }
    }

    onCycleChange(ev) {
        this.state.cycleId = ev.target.value ? parseInt(ev.target.value) : (this.state.data.all_cycles && this.state.data.all_cycles[0] ? this.state.data.all_cycles[0].id : false);
        this.loadData();
    }

    onDepartmentChange(ev) {
        this.state.departmentId = ev.target.value ? parseInt(ev.target.value) : false;
        this.state.operatingUnitId = false;
        this.loadData();
    }

    onOperatingUnitChange(ev) {
        this.state.operatingUnitId = ev.target.value ? parseInt(ev.target.value) : false;
        this.loadData();
    }

    dismissAlert() {
        this.state.alertDismissed = true;
    }

    renderCharts() {
        const ChartLib = window.Chart;
        if (!ChartLib) return;

        // 1. TNA Donut Chart
        const tnaCanvas = document.getElementById("competencyTnaDonutChart");
        if (tnaCanvas) {
            if (this.tnaChartInstance) this.tnaChartInstance.destroy();
            const cdata = (this.state.data.charts && this.state.data.charts.tna_donut) || {};
            // Real counts only. An empty/undefined dataset (e.g. RPC error, or genuinely zero
            // assessment lines) must render as zeros, never as invented sample numbers — showing
            // fabricated bank-wide figures here would mislead executives making real decisions.
            const tnaValues = Array.isArray(cdata.data) ? cdata.data : [0, 0, 0];
            this.tnaChartInstance = new ChartLib(tnaCanvas, {
                type: 'doughnut',
                data: {
                    labels: cdata.labels || ['Underqualified', 'Fit', 'Overqualified'],
                    datasets: [{
                        data: tnaValues,
                        backgroundColor: cdata.colors || ['#541718', '#16a34a', '#c17540'],
                        borderWidth: 2,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom' } }
                }
            });
        }

        // 2. Pillar Bar Chart (Grouped Bar)
        const pillarCanvas = document.getElementById("competencyPillarBarChart");
        if (pillarCanvas) {
            if (this.pillarChartInstance) this.pillarChartInstance.destroy();
            const pdata = (this.state.data.charts && this.state.data.charts.pillar_bar) || {};
            this.pillarChartInstance = new ChartLib(pillarCanvas, {
                type: 'bar',
                data: {
                    labels: pdata.labels || ['Core Pillar', 'Leadership Pillar', 'Technical Pillar'],
                    datasets: pdata.datasets && pdata.datasets.length ? pdata.datasets : [
                        { label: 'Below Target', data: [0, 0, 0], backgroundColor: '#541718' },
                        { label: 'Meets Target', data: [0, 0, 0], backgroundColor: '#16a34a' },
                        { label: 'Exceeds Target', data: [0, 0, 0], backgroundColor: '#c17540' }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: 'top' } },
                    scales: { y: { beginAtZero: true } }
                }
            });
        }

        // 3. Radar Chart (Spider/Radar) — real per-competency data only, never fabricated samples.
        const radarCanvas = document.getElementById("competencyRadarChart");
        if (radarCanvas) {
            if (this.radarChartInstance) this.radarChartInstance.destroy();
            const rdata = (this.state.data.charts && this.state.data.charts.employee_radar) || {};
            const hasRadarData = !!rdata.has_data && Array.isArray(rdata.labels) && rdata.labels.length > 0;
            this.state.radarHasData = hasRadarData;
            if (hasRadarData) {
                this.radarChartInstance = new ChartLib(radarCanvas, {
                    type: 'radar',
                    data: {
                        labels: rdata.labels,
                        datasets: [
                            {
                                label: 'My Assessed Level',
                                data: rdata.assessed,
                                backgroundColor: 'rgba(84, 23, 24, 0.2)',
                                borderColor: '#541718',
                                pointBackgroundColor: '#541718',
                            },
                            {
                                label: 'Required Level',
                                data: rdata.required,
                                backgroundColor: 'rgba(193, 117, 64, 0.1)',
                                borderColor: '#c17540',
                                borderDash: [5, 5],
                                pointBackgroundColor: '#c17540',
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { r: { beginAtZero: true, max: 5 } }
                    }
                });
            }
        }
    }

    openTnaBelow() {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const domain = [
            ['is_primary_reporting_line', '=', true],
            ['achievement_status', '=', 'below'],
            ['employee_id', 'in', fullyAssessedEmpIds]
        ];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', parseInt(this.state.cycleId)]);
        }
        if (this.state.departmentId) {
            domain.push(['department_id', '=', parseInt(this.state.departmentId)]);
        }
        const context = {
            search_default_filter_primary_reporting: 1,
            search_default_filter_below: 1,
            create: false,
            edit: false,
            delete: false,
        };
        this.actionService.doAction({
            name: "Underqualified Competency Lines (Training Needed)",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }

    openTnaMeets() {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const domain = [
            ['is_primary_reporting_line', '=', true],
            ['achievement_status', '=', 'meets'],
            ['employee_id', 'in', fullyAssessedEmpIds]
        ];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', parseInt(this.state.cycleId)]);
        }
        if (this.state.departmentId) {
            domain.push(['department_id', '=', parseInt(this.state.departmentId)]);
        }
        const context = {
            search_default_filter_primary_reporting: 1,
            search_default_filter_meets: 1,
            create: false,
            edit: false,
            delete: false,
        };
        this.actionService.doAction({
            name: "Fit / Qualified Competency Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }

    openTnaExceeds() {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const domain = [
            ['is_primary_reporting_line', '=', true],
            ['achievement_status', '=', 'exceeds'],
            ['employee_id', 'in', fullyAssessedEmpIds]
        ];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', parseInt(this.state.cycleId)]);
        }
        if (this.state.departmentId) {
            domain.push(['department_id', '=', parseInt(this.state.departmentId)]);
        }
        const context = {
            search_default_filter_primary_reporting: 1,
            search_default_filter_exceeds: 1,
            create: false,
            edit: false,
            delete: false,
        };
        this.actionService.doAction({
            name: "Overqualified Competency Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }

    async openUnmappedPositions() {
        const action = await this.orm.call(
            "competency.dashboard",
            "action_open_unmapped_positions",
            []
        );
        this.actionService.doAction(action);
    }

    async openMissingSupervisors() {
        const action = await this.orm.call(
            "competency.dashboard",
            "action_open_missing_supervisors",
            []
        );
        this.actionService.doAction(action);
    }

    async openMatrixConfig() {
        const action = await this.orm.call(
            "competency.dashboard",
            "action_open_matrix_config",
            []
        );
        this.actionService.doAction(action);
    }

    openAssessedEmployees() {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const context = {
            search_default_group_by_employee: 1,
            search_default_filter_primary_reporting: 1,
            create: false,
            edit: false,
            delete: false,
        };
        const domain = [
            ['is_primary_reporting_line', '=', true],
            ['employee_id', 'in', fullyAssessedEmpIds],
            '|',
            ['weighted_current_level', '>', 0],
            ['achievement_status', '!=', false]
        ];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', parseInt(this.state.cycleId)]);
        }
        if (this.state.departmentId) {
            domain.push(['department_id', '=', parseInt(this.state.departmentId)]);
        }
        this.actionService.doAction({
            name: "Assessed Employees Competency Reporting",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }

    openTnaReport() {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const context = {
            search_default_group_by_employee: 1,
            search_default_filter_primary_reporting: 1,
            create: false,
            edit: false,
            delete: false,
        };
        const domain = [
            ['is_primary_reporting_line', '=', true],
            ['employee_id', 'in', fullyAssessedEmpIds],
        ];
        if (this.state.cycleId) {
            domain.push(['cycle_id', '=', parseInt(this.state.cycleId)]);
        }
        this.actionService.doAction({
            name: "Comprehensive TNA Report",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }

    openMyAssessment() {
        const asmId = this.state.data.stats.my_asm_id;
        if (asmId) {
            this.actionService.doAction({
                name: "My Competency Assessment",
                type: "ir.actions.act_window",
                res_model: "competency.assessment",
                res_id: asmId,
                views: [[false, "form"]],
            });
        } else {
            this.actionService.doAction({
                name: "Create My Assessment",
                type: "ir.actions.act_window",
                res_model: "competency.assessment",
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    openTeamMemberAssessment(asmId) {
        if (asmId) {
            this.actionService.doAction({
                name: "Team Member Assessment",
                type: "ir.actions.act_window",
                res_model: "competency.assessment",
                res_id: asmId,
                views: [[false, "form"]],
            });
        }
    }

    onHeatmapCellClick(deptId, pillarKey) {
        const fullyAssessedEmpIds = (this.state.data && this.state.data.fully_assessed_emp_ids) || [];
        const domain = [
            ["is_primary_reporting_line", "=", true],
            ["department_id", "=", deptId],
            ["employee_id", "in", fullyAssessedEmpIds]
        ];
        if (this.state.cycleId) {
            domain.push(["cycle_id", "=", parseInt(this.state.cycleId)]);
        }
        if (pillarKey !== "overall") {
            domain.push(["pillar", "=", pillarKey]);
        }
        const context = {
            search_default_filter_primary_reporting: 1,
            create: false,
            edit: false,
            delete: false,
        };
        this.actionService.doAction({
            name: "Filtered Heatmap Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
            context: context,
        });
    }
}

export const competencyDashboardWidget = {
    component: CompetencyDashboard,
};

registry.category("view_widgets").add("competency_dashboard_widget", competencyDashboardWidget);
registry.category("actions").add("competency_dashboard_action", CompetencyDashboard);
