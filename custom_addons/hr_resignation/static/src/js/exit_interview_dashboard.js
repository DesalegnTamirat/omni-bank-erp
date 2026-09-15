/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
const { Component, onWillStart, onMounted, onPatched, useState } = owl;

const COLORS = ['#2F5D50', '#B98A3D', '#6B8F71', '#A85341', '#4C5B55', '#D4A843', '#5A8C6E', '#C0614E'];

export class ExitInterviewDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            dataLoaded: false,
            data: {
                meta: { total: 0, avg_rating: '-', avg_rating_raw: 0, this_month: 0, dept_count: 0 },
                charts: [],
                likerts: [],
                themes: []
            }
        });
        this._chartInstances = {};

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            try {
                const result = await this.orm.call("hr.exit.interview", "get_dashboard_data", []);
                this.state.data = result;
            } catch (e) {
                console.error("Dashboard data load error:", e);
            }
            this.state.dataLoaded = true;
        });

        onMounted(() => this._renderCharts());
        onPatched(() => this._renderCharts());
    }

    openRecords(domain, title) {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: 'hr.exit.interview',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
        });
    }

    _renderCharts() {
        if (!this.state.dataLoaded || !this.state.data.charts) return;
        
        Chart.defaults.font.family = '"Inter", -apple-system, "Segoe UI", sans-serif';
        Chart.defaults.font.size = 12;
        Chart.defaults.color = '#4C5B55';

        this.state.data.charts.forEach(chartData => {
            const canvasId = 'eid_chart_' + chartData.id;
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            if (this._chartInstances[canvasId]) {
                this._chartInstances[canvasId].destroy();
            }

            let config;
            if (chartData.type === 'doughnut') {
                config = {
                    type: 'doughnut',
                    data: {
                        labels: chartData.labels,
                        datasets: [{
                            data: chartData.data,
                            backgroundColor: COLORS.slice(0, chartData.data.length),
                            borderWidth: 0
                        }]
                    },
                    options: {
                        maintainAspectRatio: false,
                        cutout: '62%',
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: { boxWidth: 10, padding: 12, usePointStyle: true, pointStyle: 'circle' }
                            }
                        }
                    }
                };
            } else {
                config = {
                    type: 'bar',
                    data: {
                        labels: chartData.labels,
                        datasets: [{
                            data: chartData.data,
                            backgroundColor: '#2F5D50',
                            borderRadius: 4,
                            barThickness: 20
                        }]
                    },
                    options: {
                        maintainAspectRatio: false,
                        indexAxis: 'y', // Always horizontal for readability like mock
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { grid: { color: '#EFEBE0' }, ticks: { precision: 0 } },
                            y: { grid: { display: false } }
                        }
                    }
                };
            }
            this._chartInstances[canvasId] = new Chart(canvas, config);
        });
    }
}

ExitInterviewDashboard.template = "hr_resignation.ExitInterviewDashboard";
registry.category("actions").add("hr_resignation.exit_interview_dashboard", ExitInterviewDashboard);
