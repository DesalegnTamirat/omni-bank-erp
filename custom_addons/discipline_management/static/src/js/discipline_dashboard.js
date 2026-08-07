/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

class DisciplineDashboard extends Component {
    static template = "discipline_management.DisciplineDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            stats: {
                total_cases: 0,
                active_cases: 0,
                pending_approval: 0,
                sla_breached: 0,
                investigations: 0,
                committee_meetings: 0,
                active_suspensions: 0,
                pending_appeals: 0,
                payroll_penalties: 0,
                enforced_this_month: 0,
                level1_cases: 0,
                revoked_cases: 0,
            },
            recent_cases: [],
            severity_breakdown: [],
            monthly_trend: [],
            top_departments: [],
        });

        this._refreshInterval = null;

        onMounted(async () => {
            await this._loadDashboardData();
            // Auto-refresh every 5 minutes
            this._refreshInterval = setInterval(async () => {
                await this._loadDashboardData();
            }, 5 * 60 * 1000);
        });

        onWillUnmount(() => {
            if (this._refreshInterval) {
                clearInterval(this._refreshInterval);
            }
        });
    }

    async _loadDashboardData() {
        this.state.isLoading = true;
        try {
            const result = await this.orm.call(
                "discipline.case",
                "get_dashboard_data",
                [],
                {}
            );
            if (result) {
                Object.assign(this.state, result);
            }
        } catch (e) {
            console.warn("Dashboard data load failed, using direct queries:", e);
            await this._loadDashboardDataFallback();
        } finally {
            this.state.isLoading = false;
        }
    }

    async _loadDashboardDataFallback() {
        try {
            const [
                allCases,
                activeCases,
                pendingApproval,
                slaBreached,
                investigations,
                committeeMeetings,
                activeSuspensions,
                pendingAppeals,
                payrollPenalties,
                level1Cases,
                revokedCases,
            ] = await Promise.all([
                this.orm.searchCount("discipline.case", []),
                this.orm.searchCount("discipline.case", [
                    ["state", "in", ["initiated", "investigating", "committee_review", "pending_approval"]],
                ]),
                this.orm.searchCount("discipline.case", [["state", "=", "pending_approval"]]),
                this.orm.searchCount("discipline.case", [["is_sla_exceeded", "=", true]]),
                this.orm.searchCount("discipline.investigation", [["state", "!=", "concluded"]]),
                this.orm.searchCount("discipline.committee.meeting", [["state", "not in", ["concluded", "cancelled"]]]),
                this.orm.searchCount("discipline.suspension", [["state", "in", ["active", "extended"]]]),
                this.orm.searchCount("discipline.appeal", [["state", "in", ["submitted", "under_review"]]]),
                this.orm.searchCount("discipline.payroll.penalty", [["state", "=", "pending"]]),
                this.orm.searchCount("discipline.case", [["severity_level", "=", "level_1"]]),
                this.orm.searchCount("discipline.case", [["state", "=", "revoked"]]),
            ]);

            // Recent cases
            const recentCaseIds = await this.orm.search(
                "discipline.case",
                [],
                { limit: 8, order: "incident_date desc" }
            );
            const recentCases = await this.orm.read(
                "discipline.case",
                recentCaseIds,
                ["name", "employee_id", "severity_level", "state", "incident_date", "sla_deadline", "is_sla_exceeded"]
            );

            this.state.stats = {
                total_cases: allCases,
                active_cases: activeCases,
                pending_approval: pendingApproval,
                sla_breached: slaBreached,
                investigations: investigations,
                committee_meetings: committeeMeetings,
                active_suspensions: activeSuspensions,
                pending_appeals: pendingAppeals,
                payroll_penalties: payrollPenalties,
                level1_cases: level1Cases,
                revoked_cases: revokedCases,
                enforced_this_month: 0,
            };
            this.state.recent_cases = recentCases;
        } catch (err) {
            console.error("Failed to load dashboard fallback data:", err);
        }
    }

    // --- Navigation Actions ---
    openAllCases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "All Disciplinary Cases",
            res_model: "discipline.case",
            views: [[false, "list"], [false, "form"]],
            domain: [],
        });
    }

    openActiveCases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Cases",
            res_model: "discipline.case",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["initiated", "investigating", "committee_review", "pending_approval"]]],
        });
    }

    openPendingApproval() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pending Approval",
            res_model: "discipline.case",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "=", "pending_approval"]],
        });
    }

    openSlaBreached() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "SLA Breached Cases",
            res_model: "discipline.case",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_sla_exceeded", "=", true]],
        });
    }

    openInvestigations() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Investigations",
            res_model: "discipline.investigation",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "!=", "concluded"]],
        });
    }

    openCommitteeMeetings() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Committee Meetings",
            res_model: "discipline.committee.meeting",
            views: [[false, "list"], [false, "form"]],
            domain: [],
        });
    }

    openActiveSuspensions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Active Suspensions",
            res_model: "discipline.suspension",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["active", "extended"]]],
        });
    }

    openPendingAppeals() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pending Appeals",
            res_model: "discipline.appeal",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "in", ["submitted", "under_review"]]],
        });
    }

    openPayrollPenalties() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Pending Payroll Penalties",
            res_model: "discipline.payroll.penalty",
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "=", "pending"]],
        });
    }

    openLevel1Cases() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Level 1 (Dismissal) Cases",
            res_model: "discipline.case",
            views: [[false, "list"], [false, "form"]],
            domain: [["severity_level", "=", "level_1"]],
        });
    }

    createNewCase() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Disciplinary Case",
            res_model: "discipline.case",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openCase(caseId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Disciplinary Case",
            res_model: "discipline.case",
            views: [[false, "form"]],
            res_id: caseId,
        });
    }

    getSeverityBadgeClass(level) {
        const classes = {
            level_1: "badge-critical",
            level_2: "badge-high",
            level_3: "badge-medium-high",
            level_4: "badge-medium",
            level_5: "badge-low",
        };
        return classes[level] || "badge-default";
    }

    getSeverityLabel(level) {
        const labels = {
            level_1: "L1 Critical",
            level_2: "L2 Very High",
            level_3: "L3 High",
            level_4: "L4 Moderate",
            level_5: "L5 Minor",
        };
        return labels[level] || level;
    }

    getStateLabel(state) {
        const labels = {
            draft: "Draft",
            initiated: "Initiated",
            investigating: "Investigating",
            committee_review: "Committee",
            pending_approval: "Pending Approval",
            enforced: "Enforced",
            appealed: "Appealed",
            revoked: "Revoked",
            closed: "Closed",
        };
        return labels[state] || state;
    }

    getStateBadgeClass(state) {
        const classes = {
            draft: "state-draft",
            initiated: "state-initiated",
            investigating: "state-investigating",
            committee_review: "state-committee",
            pending_approval: "state-pending",
            enforced: "state-enforced",
            appealed: "state-appealed",
            revoked: "state-revoked",
            closed: "state-closed",
        };
        return classes[state] || "state-draft";
    }

    async refreshDashboard() {
        await this._loadDashboardData();
        this.notification.add("Dashboard refreshed", { type: "success" });
    }
}

registry.category("actions").add("discipline_management.discipline_dashboard", DisciplineDashboard);

export { DisciplineDashboard };
