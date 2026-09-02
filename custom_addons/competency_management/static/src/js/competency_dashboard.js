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
            persona: "executive", // 'executive' | 'supervisor' | 'employee'
            cycleId: false,
            departmentId: false,
            loading: true,
            alertDismissed: false,
            data: {
                user: { name: "", is_admin: false, is_supervisor: false },
                cycle: { id: false, name: "", deadline: "" },
                all_cycles: [],
                all_departments: [],
                stats: { bank_avg_gap: 0.24, total_assessments: 1141, below_cnt: 266, meets_cnt: 1141, exceeds_cnt: 277 },
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
                if (!this.state.loading) {
                    this.renderCharts();
                }
            },
            () => [this.state.loading, this.state.persona, this.state.cycleId]
        );
    }

    async loadData() {
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "competency.dashboard",
                "get_dashboard_data",
                [],
                {
                    cycle_id: this.state.cycleId || false,
                    department_id: this.state.departmentId || false,
                    persona: this.state.persona,
                }
            );

            this.state.data = result;
            if (!this.state.cycleId && result.cycle && result.cycle.id) {
                this.state.cycleId = result.cycle.id;
            }

            this.state.loading = false;
        } catch (e) {
            console.error("Failed to load competency dashboard data:", e);
            this.state.loading = false;
        }
    }

    onPersonaChange(newPersona) {
        this.state.persona = newPersona;
        this.loadData();
    }

    onCycleChange(ev) {
        this.state.cycleId = ev.target.value;
        this.loadData();
    }

    onDepartmentChange(ev) {
        this.state.departmentId = ev.target.value;
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
            this.tnaChartInstance = new ChartLib(tnaCanvas, {
                type: 'doughnut',
                data: {
                    labels: cdata.labels || ['Underqualified', 'Fit', 'Overqualified'],
                    datasets: [{
                        data: cdata.data && cdata.data.length ? cdata.data : [266, 1141, 277],
                        backgroundColor: cdata.colors || ['#541718', '#726732', '#c17540'],
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
                        { label: 'Meets Target', data: [0, 0, 0], backgroundColor: '#726732' },
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

        // 3. Radar Chart (Spider/Radar)
        const radarCanvas = document.getElementById("competencyRadarChart");
        if (radarCanvas) {
            if (this.radarChartInstance) this.radarChartInstance.destroy();
            const rdata = (this.state.data.charts && this.state.data.charts.employee_radar) || {};
            this.radarChartInstance = new ChartLib(radarCanvas, {
                type: 'radar',
                data: {
                    labels: rdata.labels || ['Core Values', 'Execution', 'Communication', 'Technical Skills', 'Problem Solving'],
                    datasets: [
                        {
                            label: 'My Assessed Level',
                            data: rdata.assessed || [3, 2, 4, 3, 2],
                            backgroundColor: 'rgba(84, 23, 24, 0.2)',
                            borderColor: '#541718',
                            pointBackgroundColor: '#541718',
                        },
                        {
                            label: 'All Competencies Target',
                            data: rdata.required || [4, 3, 4, 4, 3],
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

    openTnaBelow() {
        this.actionService.doAction({
            name: "Underqualified Competency Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: [["achievement_status", "=", "below"]],
        });
    }

    openTnaMeets() {
        this.actionService.doAction({
            name: "Fit / Qualified Competency Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: [["achievement_status", "=", "meets"]],
        });
    }

    openTnaExceeds() {
        this.actionService.doAction({
            name: "Overqualified Competency Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: [["achievement_status", "=", "exceeds"]],
        });
    }

    openMatrixConfig() {
        this.actionService.doAction({
            name: "Proficiency Matrix Configuration",
            type: "ir.actions.act_window",
            res_model: "competency.matrix.config",
            views: [[false, "form"]],
            res_id: 1,
        });
    }

    openTnaReport() {
        this.actionService.doAction({
            name: "Comprehensive TNA Report",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
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
        const domain = [["department_id", "=", deptId]];
        if (pillarKey !== "overall") {
            domain.push(["pillar", "=", pillarKey]);
        }
        this.actionService.doAction({
            name: "Filtered Heatmap Lines",
            type: "ir.actions.act_window",
            res_model: "competency.assessment.line",
            views: [[false, "list"], [false, "graph"], [false, "pivot"], [false, "form"]],
            domain: domain,
        });
    }
}

export const competencyDashboardWidget = {
    component: CompetencyDashboard,
};

registry.category("view_widgets").add("competency_dashboard_widget", competencyDashboardWidget);
registry.category("actions").add("competency_dashboard_action", CompetencyDashboard);
