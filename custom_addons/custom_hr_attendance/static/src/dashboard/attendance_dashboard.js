/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class AttendanceDashboard extends Component {
    static template = "custom_hr_attendance.AttendanceDashboard";

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");

        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            loading: true,
            currentTab: "admin",
            dateRange: "this_month",
            startDate: todayStr,
            endDate: todayStr,
            showLogsModal: false,
            data: {},
        });

        this.initialTabSet = false;

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        this.state.loading = true;
        try {
            const params = {
                date_range: this.state.dateRange,
            };
            if (this.state.dateRange === "custom") {
                params.start_date = this.state.startDate;
                params.end_date = this.state.endDate;
            }

            const res = await rpc("/custom_hr_attendance/dashboard_analytics", params);
            this.state.data = res;

            if (res.user_info && !this.initialTabSet) {
                if (res.user_info.is_admin) {
                    this.state.currentTab = "admin";
                } else if (res.user_info.is_coach) {
                    this.state.currentTab = "coach";
                } else {
                    this.state.currentTab = "employee";
                }
                this.initialTabSet = true;
            }
        } catch (err) {
            console.error("Dashboard Analytics RPC Error:", err);
        } finally {
            this.state.loading = false;
        }
    }

    async onDateRangeChange(ev) {
        this.state.dateRange = ev.target.value;
        if (this.state.dateRange !== "custom") {
            await this.loadDashboardData();
        }
    }

    async onStartDateChange(ev) {
        this.state.startDate = ev.target.value;
        if (this.state.startDate && this.state.endDate) {
            await this.loadDashboardData();
        }
    }

    async onEndDateChange(ev) {
        this.state.endDate = ev.target.value;
        if (this.state.startDate && this.state.endDate) {
            await this.loadDashboardData();
        }
    }

    switchTab(tabName) {
        this.state.currentTab = tabName;
    }

    openLogsModal() {
        this.state.showLogsModal = true;
    }

    closeLogsModal() {
        this.state.showLogsModal = false;
    }
}

registry.category("actions").add("custom_hr_attendance.attendance_dashboard", AttendanceDashboard);
