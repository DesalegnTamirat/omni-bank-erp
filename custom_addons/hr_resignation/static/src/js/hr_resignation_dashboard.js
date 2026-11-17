/** @odoo-module **/

import { Component, onWillStart, onMounted, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

export class HrResignationDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            stats: {},
            charts: {},
            recent_resignations: [],
            clearance_bottlenecks: [],
        });
        
        this.pieChartCanvas = useRef("pieChartCanvas");
        this.barChartCanvas = useRef("barChartCanvas");

        onWillStart(async () => {
            try {
                const data = await this.orm.call("hr.resignation.dashboard", "get_dashboard_data", []);
                if (data) {
                    this.state.stats = data.stats || {};
                    this.state.charts = data.charts || {};
                    this.state.recent_resignations = data.recent_resignations || [];
                    this.state.clearance_bottlenecks = data.clearance_bottlenecks || [];
                }
            } catch (e) {
                console.error("Failed to load resignation dashboard data:", e);
            }

            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                console.error("Failed to load chart library bundle:", e);
            }
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    renderCharts() {
        if (this.pieChartCanvas.el && this.state.charts.pie && this.state.charts.pie.data.length > 0) {
            new Chart(this.pieChartCanvas.el, {
                type: 'doughnut',
                data: {
                    labels: this.state.charts.pie.labels,
                    datasets: [{
                        data: this.state.charts.pie.data,
                        backgroundColor: [
                            '#c17540', '#1d2b32', '#425727', '#726732', '#1e2917', '#541718'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                boxWidth: 12,
                                padding: 8,
                                font: {
                                    size: 12
                                }
                            }
                        }
                    }
                }
            });
        }

        if (this.barChartCanvas.el && this.state.charts.bar && this.state.charts.bar.data.length > 0) {
            let barLabels = [...this.state.charts.bar.labels];
            let barData = [...this.state.charts.bar.data];
            
            // Pad the chart so few items don't spread across the entire screen
            while (barLabels.length < 20) {
                barLabels.push('');
                barData.push(null);
            }

            new Chart(this.barChartCanvas.el, {
                type: 'bar',
                data: {
                    labels: barLabels,
                    datasets: [{
                        label: 'Resignations',
                        data: barData,
                        backgroundColor: [
                            '#c17540', '#1d2b32', '#425727', '#726732', '#1e2917', '#541718',
                            '#c17540', '#1d2b32', '#425727', '#726732', '#1e2917', '#541718'
                        ],
                        borderRadius: 4,
                        maxBarThickness: 30,
                        barPercentage: 1.0,
                        categoryPercentage: 0.95
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        x: {
                            grid: {
                                display: false
                            },
                            ticks: {
                                font: {
                                    size: 10
                                }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            suggestedMax: 5,
                            ticks: {
                                stepSize: 1,
                                font: {
                                    size: 10
                                }
                            }
                        }
                    }
                }
            });
        }

    }

    openResignations(type) {
        let domain = [];
        let name = "Resignation Requests";
        let res_model = "hr.resignation";

        if (type === 'draft') {
            domain = [['state', 'in', ['draft', 'submitted']]];
            name = "Draft / Submitted Requests";
        } else if (type === 'manager_approved') {
            domain = [['state', '=', 'manager_approved']];
            name = "Manager Approved Requests";
        } else if (type === 'approved') {
            domain = [['state', 'in', ['approved', 'release_date_set', 'handover_completed']]];
            name = "HR Approved Requests";
        } else if (type === 'clearance_in_progress') {
            domain = [['state', '=', 'clearance_in_progress']];
            name = "Clearance In Progress";
        } else if (type === 'cleared_awaiting_settlement') {
            domain = [['state', '=', 'cleared']];
            name = "Cleared (Awaiting Settlement)";
        } else if (type === 'settlement_in_progress') {
            res_model = "hr.resignation.settlement";
            domain = [['state', 'in', ['draft', 'waiting_audit']]];
            name = "Settlement In Progress";
        } else if (type === 'completed') {
            domain = [['state', '=', 'completed']];
            name = "Completed Requests";
        } else if (type === 'waiting_payment') {
            res_model = "hr.resignation.settlement";
            domain = [['state', '=', 'waiting_payment']];
            name = "Waiting Payment";
        } else if (type === 'overdue') {
            res_model = "hr.resignation.clearance";
            domain = [['state', '=', 'pending'], ['is_overdue', '=', true]];
            name = "Overdue Clearances";
        } else {
            domain = [];
            name = "All Requests";
        }

        this.action.doAction({
            type: "ir.actions.act_window",
            name: name,
            res_model: res_model,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: { create: false },
            target: "current",
        });
    }

    onKpiClick(ev) {
        const domain = ev.currentTarget.dataset.domain;
        this.openResignations(domain);
    }

    openResignationRecord(id) {
        if (!id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.resignation",
            res_id: id,
            views: [[false, "form"]],
            context: { create: false },
            target: "current",
        });
    }
}
HrResignationDashboard.template = "hr_resignation.Dashboard";
registry.category("actions").add("hr_resignation_dashboard_action", HrResignationDashboard);