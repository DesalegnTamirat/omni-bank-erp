/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

// Official Bunna Bank Color Palette
const BUNNA_COLORS = {
    present: "#425727",       // Forest Green (On-Time Normal)
    preapproved: "#0284c7",   // Sky Blue (Pre-Approved Exceptions)
    late: "#c17540",          // Terracotta Gold (Unexcused Late)
    leave: "#726732",         // Olive Gold (On Leave)
    absent: "#541718",        // Crimson Maroon (Absent)
    navy: "#1d2b32",          // Deep Navy (Total Staff)
    darkForest: "#1e2917",    // Dark Forest
};

/**
 * Enterprise Attendance Command Center for Bunna Bank.
 * Supports hierarchical role-based access control (Admin, Chief, District Director, Directorate Director, Branch/Division Manager, Employee),
 * locked managed unit views, dynamic sub-unit filters, real-time drilldowns, and Bunna branding.
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
            currentTab: "corporate", // Defaults to corporate for managers, will auto-switch to personal if no corporate access
            filter: "today",
            specificDate: todayStr,
            personalPeriod: "this_month",
            personalStartDate: todayStr,
            personalEndDate: todayStr,
            filterOptions: {
                offices: [],
                operating_units: [],
                is_locked_unit: false,
                locked_unit_label: "",
                locked_unit_name: "",
                locked_office_name: false,
                sub_filter_label: "",
                sub_filter_type: "",
                sub_filter_options: [],
            },
            selectedOffice: "",
            selectedDeptOrDist: "",
            selectedOU: "",
            divisionEmpId: "",
            showLogsModal: false,
            today: "",
            kpi: {
                total: 0,
                present: 0,
                on_time_normal: 0,
                preapproved_count: 0,
                late_unexcused: 0,
                late: 0,
                leave: 0,
                absent: 0,
                pending_preapproval_count: 0,
                acknowledged_count: 0,
                force_checkout_count: 0,
                session_am_pct: 0,
                session_pm_pct: 0,
            },
            progress: [],
            workunit: [],
            personal: {},
            drilldown: {
                isOpen: false,
                loading: false,
                title: "",
                metricType: "",
                records: [],
            },
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
                this.state.divisionEmpId,
                this.state.kpi.total,
                this.state.kpi.present,
                this.state.kpi.on_time_normal,
                this.state.kpi.preapproved_count,
                this.state.kpi.late_unexcused,
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

    async onOfficeChange(ev) {
        this.state.selectedOffice = ev.target.value;
        this.state.selectedDeptOrDist = ev.target.value;
        this.state.selectedOU = "";
        this.state.divisionEmpId = "";
        await this.loadDashboard();
    }

    async onDeptOrDistChange(ev) {
        return this.onOfficeChange(ev);
    }

    async onOUChange(ev) {
        this.state.selectedOU = ev.target.value;
        this.state.divisionEmpId = "";
        await this.loadDashboard();
    }

    async onSubFilterChange(ev) {
        const val = ev.target.value;
        if (this.state.filterOptions && this.state.filterOptions.sub_filter_type === "division") {
            this.state.divisionEmpId = val;
            this.state.selectedOU = "";
        } else {
            this.state.selectedOU = val;
            this.state.divisionEmpId = "";
        }
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

    async openDrilldown(metricType, title) {
        this.state.drilldown.isOpen = true;
        this.state.drilldown.loading = true;
        this.state.drilldown.title = title || metricType.toUpperCase();
        this.state.drilldown.metricType = metricType;
        this.state.drilldown.records = [];

        try {
            const officeVal = this.state.selectedOffice || this.state.selectedDeptOrDist || false;
            const res = await this.orm.call("hr.attendance", "get_dashboard_drilldown", [
                metricType,
                this.state.filter,
                this.state.specificDate,
                officeVal,
                this.state.selectedOU ? parseInt(this.state.selectedOU) : false,
                this.state.divisionEmpId ? parseInt(this.state.divisionEmpId) : false,
            ]);
            if (res && res.records) {
                this.state.drilldown.records = res.records;
                if (res.title) {
                    this.state.drilldown.title = res.title;
                }
            } else if (Array.isArray(res)) {
                this.state.drilldown.records = res;
            } else {
                this.state.drilldown.records = [];
            }
        } catch (err) {
            console.error("Failed to load drilldown data:", err);
            this.notification.add(_t("Could not load attendance details."), {
                type: "danger",
            });
        } finally {
            this.state.drilldown.loading = false;
        }
    }

    closeDrilldown() {
        this.state.drilldown.isOpen = false;
        this.state.drilldown.records = [];
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            const officeVal = this.state.selectedOffice || this.state.selectedDeptOrDist || false;
            const data = await this.orm.call("hr.attendance", "get_attendance_dashboard", [
                this.state.filter,
                this.state.specificDate,
                officeVal,
                this.state.selectedOU ? parseInt(this.state.selectedOU) : false,
                this.state.personalPeriod,
                this.state.personalStartDate,
                this.state.personalEndDate,
                this.state.divisionEmpId ? parseInt(this.state.divisionEmpId) : false,
            ]);

            this.state.today = data.today || "";
            this.state.hasCorporateAccess = Boolean(data.has_corporate_access);
            this.state.accessLevel = data.access_level || "employee";
            this.state.userRoleLabel = data.user_role_label || "Employee";
            this.state.filterOptions = data.filter_options || {
                offices: [],
                operating_units: [],
                is_locked_unit: false,
                locked_unit_label: "",
                locked_unit_name: "",
                locked_office_name: false,
                sub_filter_label: "",
                sub_filter_type: "",
                sub_filter_options: [],
            };
            this.state.kpi = data.kpi || {
                total: 0,
                present: 0,
                on_time_normal: 0,
                preapproved_count: 0,
                late_unexcused: 0,
                late: 0,
                leave: 0,
                absent: 0,
                pending_preapproval_count: 0,
                acknowledged_count: 0,
                force_checkout_count: 0,
                session_am_pct: 0,
                session_pm_pct: 0,
            };
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
        const onTime = kpi.on_time_normal !== undefined ? kpi.on_time_normal : Math.max(0, kpi.present - kpi.late);
        const preapproved = kpi.preapproved_count || 0;
        const late = kpi.late_unexcused !== undefined ? kpi.late_unexcused : kpi.late;
        const leave = kpi.leave || 0;
        const absent = kpi.absent || 0;

        const onTimePct = ((onTime / total) * 100).toFixed(1);
        const preapprovedPct = ((preapproved / total) * 100).toFixed(1);
        const latePct = ((late / total) * 100).toFixed(1);
        const leavePct = ((leave / total) * 100).toFixed(1);
        const absentPct = ((absent / total) * 100).toFixed(1);

        this._renderChart("pie", this.pieRef, {
            type: "doughnut",
            data: {
                labels: [
                    _t(`On-Time (${onTimePct}%)`),
                    _t(`Pre-Approved (${preapprovedPct}%)`),
                    _t(`Unexcused Late (${latePct}%)`),
                    _t(`On Leave (${leavePct}%)`),
                    _t(`Absent (${absentPct}%)`),
                ],
                datasets: [
                    {
                        data: [onTime, preapproved, late, leave, absent],
                        backgroundColor: [
                            BUNNA_COLORS.present,
                            BUNNA_COLORS.preapproved,
                            BUNNA_COLORS.late,
                            BUNNA_COLORS.leave,
                            BUNNA_COLORS.absent,
                        ],
                        borderWidth: 2,
                        borderColor: "#ffffff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: {
                            boxWidth: 12,
                            font: { size: 11, weight: "bold" },
                            padding: 12,
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
                        label: _t("Active Headcount"),
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
                        grid: { color: "#f1f5f9" },
                    },
                    x: {
                        grid: { display: false },
                    },
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 12, font: { size: 11, weight: "bold" } },
                    },
                },
            },
        });
    }

    renderWorkUnitChart(workunit) {
        const items = workunit && workunit.length > 0 ? workunit : [
            { unit: "Managed Unit", count: 0 }
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
                        borderRadius: 6,
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
                        grid: { color: "#f1f5f9" },
                    },
                    x: {
                        ticks: {
                            maxRotation: 35,
                            minRotation: 0,
                            font: { size: 10, weight: "bold" },
                        },
                        grid: { display: false },
                    },
                },
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 12, font: { size: 11, weight: "bold" } },
                    },
                },
            },
        });
    }
}

// Register under both action keys for full backward compatibility
registry.category("actions").add("custom_hr_attendance.attendance_dashboard", AttendanceDashboard);
registry.category("actions").add("attendance_dashboard.dashboard_action", AttendanceDashboard);
