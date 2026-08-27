/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

// Official Bunna Bank Color Palette
const BUNNA_COLORS = {
    present: "#425727",       // Forest Green
    late: "#c17540",          // Terracotta Gold
    leave: "#726732",         // Olive Gold
    absent: "#541718",        // Crimson Maroon
    navy: "#1d2b32",          // Deep Navy
    darkForest: "#1e2917",    // Dark Forest
};

/**
 * Enterprise Attendance Command Center for Bunna Bank.
 * Supports hierarchical role-based access control (Admin, Chief, District, Branch/OU, Employee),
 * dedicated tab switching, dynamic sub-unit filters, and Bunna branding.
 */
export class AttendanceDashboard extends Component {
    static template = "custom_hr_attendance.AttendanceDashboard";
    static props = ["*"];

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");

        this.pieRef = useRef("pieChart");
        this.lineRef = useRef("lineChart");
        this.barRef = useRef("barChart");

        const todayStr = new Date().toISOString().split("T")[0];

        this.state = useState({
            loading: true,
            hasCorporateAccess: false,
            accessLevel: "employee",
            userRoleLabel: "Employee",
            currentTab: "corporate", // "corporate" | "personal"
            filter: "today",
            specificDate: todayStr,
            personalPeriod: "this_month",
            personalStartDate: todayStr,
            personalEndDate: todayStr,
            filterOptions: { districts_and_directorates: [], operating_units: [] },
            selectedDeptOrDist: "",
            selectedOU: "",
            showLogsModal: false,
            today: "",
            kpi: { total: 0, present: 0, late: 0, leave: 0, absent: 0 },
            progress: [],
            workunit: [],
            personal: {},
        });

        // Chart.js instances (non-reactive)
        this.charts = { pie: null, line: null, bar: null };

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadDashboard();
        });

        // Render Chart.js graphs AFTER DOM is mounted or updated
        useEffect(
            () => {
                if (!this.state.loading && this.state.hasCorporateAccess && this.state.currentTab === "corporate") {
                    this.renderAllCharts();
                }
            },
            () => [
                this.state.loading,
                this.state.hasCorporateAccess,
                this.state.currentTab,
                this.state.today,
                this.state.selectedDeptOrDist,
                this.state.selectedOU,
                this.state.kpi.total,
                this.state.kpi.present,
                this.state.kpi.late,
                this.state.kpi.leave,
                this.state.kpi.absent,
            ]
        );

        onWillUnmount(() => {
            this.destroyCharts();
        });
    }

    destroyCharts() {
        for (const chart of Object.values(this.charts)) {
            if (chart) {
                chart.destroy();
            }
        }
        this.charts = { pie: null, line: null, bar: null };
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

    async onDeptOrDistChange(ev) {
        this.state.selectedDeptOrDist = ev.target.value;
        this.state.selectedOU = "";
        await this.loadDashboard();
    }

    async onOUChange(ev) {
        this.state.selectedOU = ev.target.value;
        await this.loadDashboard();
    }

    async onFilterChange(ev) {
        this.state.filter = ev.target.value;
        if (this.state.filter !== "specific" || this.state.specificDate) {
            await this.loadDashboard();
        }
    }

    async onSpecificDateChange(ev) {
        this.state.specificDate = ev.target.value;
        if (this.state.specificDate) {
            await this.loadDashboard();
        }
    }

    async onPersonalPeriodChange(ev) {
        this.state.personalPeriod = ev.target.value;
        if (this.state.personalPeriod !== "custom" || (this.state.personalStartDate && this.state.personalEndDate)) {
            await this.loadDashboard();
        }
    }

    async onPersonalStartChange(ev) {
        this.state.personalStartDate = ev.target.value;
        if (this.state.personalStartDate && this.state.personalEndDate) {
            await this.loadDashboard();
        }
    }

    async onPersonalEndChange(ev) {
        this.state.personalEndDate = ev.target.value;
        if (this.state.personalStartDate && this.state.personalEndDate) {
            await this.loadDashboard();
        }
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("hr.attendance", "get_attendance_dashboard", [
                this.state.filter,
                this.state.specificDate,
                this.state.selectedDeptOrDist ? this.state.selectedDeptOrDist : false,
                this.state.selectedOU ? parseInt(this.state.selectedOU) : false,
                this.state.personalPeriod,
                this.state.personalStartDate,
                this.state.personalEndDate,
            ]);

            this.state.today = data.today || "";
            this.state.hasCorporateAccess = Boolean(data.has_corporate_access);
            this.state.accessLevel = data.access_level || "employee";
            this.state.userRoleLabel = data.user_role_label || "Employee";
            this.state.filterOptions = data.filter_options || { districts_and_directorates: [], operating_units: [] };
            this.state.kpi = data.kpi || { total: 0, present: 0, late: 0, leave: 0, absent: 0 };
            this.state.progress = data.progress || [];
            this.state.workunit = data.workunit || [];
            this.state.personal = data.personal_summary || {};
            if (data.target_date) {
                this.state.specificDate = data.target_date;
            }

            // If user has no corporate access, force tab to personal
            if (!this.state.hasCorporateAccess) {
                this.state.currentTab = "personal";
            }
        } catch (err) {
            console.error("Failed to load attendance dashboard:", err);
            this.notification.add(_t("Could not load the attendance dashboard."), {
                title: _t("Attendance Dashboard"),
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    renderAllCharts() {
        this.renderPieChart(this.state.kpi);
        this.renderLineChart(this.state.progress);
        this.renderWorkUnitChart(this.state.workunit);
    }

    _renderChart(key, ref, config) {
        if (this.charts[key]) {
            this.charts[key].destroy();
            this.charts[key] = null;
        }
        if (!ref.el) {
            return;
        }
        try {
            this.charts[key] = new Chart(ref.el, config);
        } catch (e) {
            console.error(`Error rendering ${key} chart:`, e);
        }
    }

    renderPieChart(kpi) {
        const total = kpi.total || 1;
        const onTime = Math.max(0, kpi.present - kpi.late);
        const late = kpi.late;
        const leave = kpi.leave;
        const absent = kpi.absent;

        const presentPct = ((kpi.present / total) * 100).toFixed(1);
        const latePct = ((late / total) * 100).toFixed(1);
        const leavePct = ((leave / total) * 100).toFixed(1);
        const absentPct = ((absent / total) * 100).toFixed(1);

        this._renderChart("pie", this.pieRef, {
            type: "pie",
            data: {
                labels: [
                    _t(`Present ${presentPct}%`),
                    _t(`Late ${latePct}%`),
                    _t(`Leave ${leavePct}%`),
                    _t(`Absent ${absentPct}%`),
                ],
                datasets: [
                    {
                        data: [onTime, late, leave, absent],
                        backgroundColor: [
                            BUNNA_COLORS.present,
                            BUNNA_COLORS.late,
                            BUNNA_COLORS.leave,
                            BUNNA_COLORS.absent,
                        ],
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        labels: {
                            boxWidth: 14,
                            font: { size: 11 },
                        },
                    },
                },
            },
        });
    }

    renderLineChart(progress) {
        const items = progress && progress.length > 0 ? progress : [
            { label: "06:00", count: 0 },
            { label: "08:00", count: 0 },
            { label: "10:00", count: 0 },
            { label: "12:00", count: 0 },
            { label: "14:00", count: 0 },
            { label: "17:00", count: 0 },
        ];

        this._renderChart("line", this.lineRef, {
            type: "line",
            data: {
                labels: items.map((p) => p.label),
                datasets: [
                    {
                        label: _t("Attendance Presence"),
                        data: items.map((p) => p.count),
                        borderColor: BUNNA_COLORS.present,
                        backgroundColor: "rgba(66, 87, 39, 0.15)",
                        fill: true,
                        tension: 0.35,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: BUNNA_COLORS.present,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                    },
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 14 },
                    },
                },
            },
        });
    }

    renderWorkUnitChart(workunit) {
        const items = workunit && workunit.length > 0 ? workunit : [
            { unit: "Head Office", count: 0 }
        ];

        this._renderChart("bar", this.barRef, {
            type: "bar",
            data: {
                labels: items.map((w) => w.unit),
                datasets: [
                    {
                        label: _t("Present Workforce"),
                        data: items.map((w) => w.count),
                        backgroundColor: BUNNA_COLORS.absent,
                        borderRadius: 4,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: { precision: 0 },
                    },
                    x: {
                        ticks: {
                            maxRotation: 45,
                            minRotation: 25,
                            font: { size: 10 },
                        },
                    },
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 14 },
                    },
                },
            },
        });
    }
}

// Register under both action keys for full backward compatibility
registry.category("actions").add("custom_hr_attendance.attendance_dashboard", AttendanceDashboard);
registry.category("actions").add("attendance_dashboard.dashboard_action", AttendanceDashboard);


