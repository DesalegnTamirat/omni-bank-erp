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
            charts: {}
        });
        
        this.pieChartCanvas = useRef("pieChartCanvas");
        this.barChartCanvas = useRef("barChartCanvas");

        onWillStart(async () => {
            try {
                const data = await this.orm.call("hr.resignation.dashboard", "get_dashboard_data", []);
                if (data) {
                    this.state.stats = data.stats || {};
                    this.state.charts = data.charts || {};
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
                            position: 'right'
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
                            }
                        },
                        y: {
                            beginAtZero: true,
                            suggestedMax: 5,
                            ticks: {
                                stepSize: 1
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
        } else if (type === 'hr_approved') {
            domain = [['state', 'in', ['hr_approved', 'release_date_set', 'handover_completed']]];
            name = "HR Approved Requests";
        } else if (type === 'clearing') {
            res_model = "hr.resignation";
            domain = [['state', '=', 'clearance']];
            name = "Clearances In Progress";
        } else if (type === 'cleared_awaiting_settlement') {
            domain = [['state', '=', 'cleared']];
            name = "Cleared (Awaiting Settlement)";
        } else if (type === 'completed') {
            domain = [['state', 'in', ['settled', 'done']]];
            name = "Completed Requests";
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
            target: "current",
        });
    }

    onKpiClick(ev) {
        const domain = ev.currentTarget.dataset.domain;
        this.openResignations(domain);
    }
}
HrResignationDashboard.template = "hr_resignation.Dashboard";
registry.category("actions").add("hr_resignation_dashboard_action", HrResignationDashboard);
