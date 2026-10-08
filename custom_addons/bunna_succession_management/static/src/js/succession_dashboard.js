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

    renderCharts() {
        if (!this.state.dashboardData) return;
        const ctx = document.getElementById("readinessChart");
        if (ctx) {
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['Ready Now', 'Ready Soon (1-3 yrs)', 'Ready Later (3-5 yrs)'],
                    datasets: [{
                        label: 'Candidates',
                        data: [
                            this.state.dashboardData.ready_now_count,
                            this.state.dashboardData.ready_soon_count,
                            this.state.dashboardData.ready_later_count
                        ],
                        backgroundColor: ['#28a745', '#17a2b8', '#ffc107'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    legend: { display: false },
                    scales: {
                        yAxes: [{ ticks: { beginAtZero: true, precision: 0 } }]
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
            name: "High Risk Vacancies",
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
            domain: [['state', 'in', ['assessed', 'approved']], ['readiness_level', '=', 'ready_now']],
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
        this.action.doAction({
            name: "Career Aspirations",
            type: "ir.actions.act_window",
            res_model: "hr.career.aspiration",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            target: "current",
        });
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

    openTalentPools() {
        this.action.doAction({
            name: "Active Talent Pools",
            type: "ir.actions.act_window",
            res_model: "succession.talent.pool",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [['state', '=', 'active']],
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
