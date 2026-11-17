/** @odoo-module **/

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class SuccessionDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            dashboardData: null,
            loading: true,
            riskFilter: 'all',
            searchQuery: '',
        });

        onWillStart(async () => {
            this.state.dashboardData = await this.orm.call(
                "succession.critical.position",
                "get_dashboard_data",
                []
            );
            this.state.loading = false;
        });

        onMounted(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.renderCharts();
        });
    }


    get filteredCriticalList() {
        if (!this.state.dashboardData || !this.state.dashboardData.critical_list) return [];
        let list = this.state.dashboardData.critical_list;
        if (this.state.riskFilter !== 'all') {
            list = list.filter(p => p.risk === this.state.riskFilter);
        }
        if (this.state.searchQuery && this.state.searchQuery.trim()) {
            const q = this.state.searchQuery.toLowerCase().trim();
            list = list.filter(p => (p.name && p.name.toLowerCase().includes(q)) || (p.department && p.department.toLowerCase().includes(q)));
        }
        return list;
    }

    setRiskFilter(filter) {
        this.state.riskFilter = filter;
    }

    openPosition(positionId) {
        if (!positionId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "succession.critical.position",
            res_id: positionId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    renderCharts() {
        if (!this.state.dashboardData) return;
        const ctx = document.getElementById("readinessChart");
        if (ctx) {
            if (this.chartInstance) {
                this.chartInstance.destroy();
                this.chartInstance = null;
            }

            const pipeline = this.state.dashboardData.readiness_pipeline || {
                labels: ['Ready Now', 'Ready Soon (1-3 yrs)', 'Ready Later (3-5 yrs)'],
                data: [
                    this.state.dashboardData.ready_now_count,
                    this.state.dashboardData.ready_soon_count,
                    this.state.dashboardData.ready_later_count
                ],
                colors: ['#28a745', '#17a2b8', '#ffc107'],
                levels: []
            };

            this.chartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: pipeline.labels,
                    datasets: [{
                        label: 'Candidates',
                        data: pipeline.data,
                        backgroundColor: pipeline.colors,
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    legend: { display: false },
                    scales: {
                        yAxes: [{ ticks: { beginAtZero: true, precision: 0 } }]
                    },
                    onClick: (evt, elements) => {
                        if (elements && elements.length > 0 && pipeline.levels && pipeline.levels.length > 0) {
                            const index = elements[0]._index;
                            const level = pipeline.levels[index];
                            if (level) {
                                this.action.doAction({
                                    name: `${level.name} Candidates`,
                                    type: "ir.actions.act_window",
                                    res_model: "succession.candidate",
                                    view_mode: "list,form",
                                    views: [[false, "list"], [false, "form"]],
                                    domain: [['state', 'in', ['assessed', 'approved']], ['readiness_level_id', '=', level.id]],
                                    target: "current",
                                });
                            }
                        }
                    }
                }
            });
        }
    }

    openCriticalPositions() {
        this.action.doAction({
            name: "Critical Positions",
            type: "ir.actions.act_window",
            res_model: "succession.critical.position",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', 'in', ['approved']]],
            target: "current",
        });
    }

    openHighRisk() {
        this.action.doAction({
            name: "Priority Critical Positions",
            type: "ir.actions.act_window",
            res_model: "succession.critical.position",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', 'in', ['approved']], ['succession_risk', 'in', ['high', 'critical']]],
            target: "current",
        });
    }
    
    openCandidates() {
        this.action.doAction({
            name: "Total Candidates",
            type: "ir.actions.act_window",
            res_model: "succession.candidate",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', 'in', ['assessed', 'approved']]],
            target: "current",
        });
    }

    openReadyNow() {
        this.action.doAction({
            name: "Ready Now Successors",
            type: "ir.actions.act_window",
            res_model: "succession.candidate",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', 'in', ['assessed', 'approved']], ['readiness_level_id.is_ready_for_deployment', '=', true]],
            target: "current",
        });
    }

    openDevPlans() {
        this.action.doAction({
            name: "Active Development Plans",
            type: "ir.actions.act_window",
            res_model: "succession.development.plan",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', '=', 'active']],
            target: "current",
        });
    }

    openAspirations() {
        this.action.doAction("bunna_succession_management.action_view_career_aspiration_readonly");
    }

    openIDPs() {
        this.action.doAction({
            name: "Individual Development Plans",
            type: "ir.actions.act_window",
            res_model: "hr.career.idp",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
    }


    openDiscussions() {
        this.action.doAction({
            name: "Career Discussions",
            type: "ir.actions.act_window",
            res_model: "succession.career.discussion",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [],
            target: "current",
        });
    }
}
SuccessionDashboard.template = "bunna_succession_management.SuccessionDashboard";
registry.category("actions").add("succession_dashboard", SuccessionDashboard);
