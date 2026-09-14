/** @odoo-module **/

import { TimeOffDashboard } from "@hr_holidays/dashboard/time_off_dashboard";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";

patch(TimeOffDashboard.prototype, {
    setup() {
        super.setup();
        this.state.accruedLeaveBalance = 0.0;
        this.state.scheduledLeaveBalance = 0.0;
        this.state.dailyAccrualRate = 0.0;
        this.state.annualEntitlement = 0.0;
        this.state.maxCarryoverCap = 0.0;
        this.state.remainingToCap = 0.0;
        this.state.capPercentage = 0.0;
        this.state.accrualStatus = "active";
        this.state.accrualStatusLabel = "Actively Accruing";
        this.state.employeeCategory = "";
        this.state.isRefreshing = false;
    },

    get capColor() {
        if (this.state.accrualStatus === "capped") {
            return "#dc3545";
        } else if (this.state.accrualStatus === "near_cap") {
            return "#c17540";
        }
        return "#28a745";
    },

    get capPercentageStyle() {
        return `color: ${this.capColor};`;
    },

    get capProgressStyle() {
        const pct = Math.min(100.0, Math.max(0.0, this.state.capPercentage || 0));
        return `width: ${pct}%; background-color: ${this.capColor};`;
    },

    get accruedLeaveBalanceFormatted() {
        const val = Number(this.state.accruedLeaveBalance) || 0.0;
        return val.toFixed(2);
    },

    get scheduledLeaveBalanceFormatted() {
        const val = Number(this.state.scheduledLeaveBalance) || 0.0;
        return val.toFixed(2);
    },

    get totalEarnedBalanceFormatted() {
        const acc = Number(this.state.accruedLeaveBalance) || 0.0;
        const sched = Number(this.state.scheduledLeaveBalance) || 0.0;
        return (acc + sched).toFixed(2);
    },

    get dailyAccrualRateFormatted() {
        const val = Number(this.state.dailyAccrualRate) || 0.0;
        return val.toFixed(4);
    },

    get maxCarryoverCapFormatted() {
        const val = Number(this.state.maxCarryoverCap) || 0.0;
        return val.toFixed(2);
    },

    get remainingToCapFormatted() {
        const val = Number(this.state.remainingToCap) || 0.0;
        return val.toFixed(2);
    },

    get capPercentageFormatted() {
        const val = Number(this.state.capPercentage) || 0.0;
        return val.toFixed(1);
    },

    getContext() {
        const context = { from_dashboard: true };
        if (this.props && this.props.employeeId) {
            context["employee_id"] = this.props.employeeId;
        }
        return context;
    },

    async loadDashboardData(date = false) {
        if (date) {
            this.state.date = date;
        }
        const context = this.getContext();

        // 1. Clear standard allocation cards so only our custom banner shows
        this.state.holidays = [];
        this.state.allocationRequests = 0;
        this.hasAccrualAllocation = false;

        // 2. Fetch live custom leave balances and accrual metrics directly from hr.leave
        try {
            const balances = await this.orm.call(
                "hr.leave",
                "get_dashboard_balances",
                [this.props.employeeId || false],
                { context }
            );
            if (balances) {
                this.state.accruedLeaveBalance = parseFloat(balances.accrued) || 0.0;
                this.state.scheduledLeaveBalance = parseFloat(balances.scheduled) || 0.0;
                this.state.dailyAccrualRate = parseFloat(balances.daily_rate) || 0.0;
                this.state.annualEntitlement = parseFloat(balances.annual_entitlement) || 0.0;
                this.state.maxCarryoverCap = parseFloat(balances.max_cap) || 0.0;
                this.state.remainingToCap = parseFloat(balances.remaining_to_cap) || 0.0;
                this.state.capPercentage = parseFloat(balances.cap_percentage) || 0.0;
                this.state.accrualStatus = balances.accrual_status || "active";
                this.state.accrualStatusLabel = balances.accrual_status_label || "Actively Accruing";
                this.state.employeeCategory = balances.employee_category || "";
            }
        } catch (err) {
            console.error("Error fetching hr.leave get_dashboard_balances:", err);
            // Fallback to hr.leave.dashboard
            try {
                const balances = await this.orm.call(
                    "hr.leave.dashboard",
                    "get_dashboard_balances",
                    [this.props.employeeId || false],
                    { context }
                );
                if (balances) {
                    this.state.accruedLeaveBalance = parseFloat(balances.accrued) || 0.0;
                    this.state.scheduledLeaveBalance = parseFloat(balances.scheduled) || 0.0;
                    this.state.dailyAccrualRate = parseFloat(balances.daily_rate) || 0.0;
                    this.state.annualEntitlement = parseFloat(balances.annual_entitlement) || 0.0;
                    this.state.maxCarryoverCap = parseFloat(balances.max_cap) || 0.0;
                    this.state.remainingToCap = parseFloat(balances.remaining_to_cap) || 0.0;
                    this.state.capPercentage = parseFloat(balances.cap_percentage) || 0.0;
                    this.state.accrualStatus = balances.accrual_status || "active";
                    this.state.accrualStatusLabel = balances.accrual_status_label || "Actively Accruing";
                    this.state.employeeCategory = balances.employee_category || "";
                }
            } catch (fallbackErr) {
                console.error("Error with fallback get_dashboard_balances:", fallbackErr);
            }
        }
    },

    async actionNewRequest() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "New Leave Request",
            res_model: "hr.leave",
            views: [[false, "form"]],
            target: "current",
        });
    },

    async actionOpenMyRequests() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "My Requests",
            res_model: "hr.leave",
            views: [
                [false, "list"],
                [false, "form"],
                [false, "kanban"],
            ],
            domain: [["user_id", "=", user.userId], ["custom_saved", "=", true]],
            target: "current",
        });
    },

    async actionOpenScheduledRequests() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "My Scheduled Requests",
            res_model: "hr.leave",
            views: [
                [false, "list"],
                [false, "form"],
                [false, "kanban"],
            ],
            domain: [
                ["user_id", "=", user.userId],
                ["custom_saved", "=", true],
                ["holiday_status_id.is_scheduled_leave", "=", true]
            ],
            target: "current",
        });
    },

    async actionRefreshDashboard() {
        this.state.isRefreshing = true;
        await this.loadDashboardData();
        if (this.env.timeOffBus) {
            this.env.timeOffBus.trigger("update_dashboard");
        }
        setTimeout(() => {
            this.state.isRefreshing = false;
        }, 500);
    },
});
