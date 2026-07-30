/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

const KPI_COLORS = {
    present: "#2ecc71",
    late: "#f39c12",
    leave: "#f1c40f",
    absent: "#e74c3c",
};

/**
 * Attendance Dashboard client action.
 *
 * Ported from the Odoo 14 version of this module, which used the legacy
 * odoo.define / web.AbstractAction / jQuery / manually-vendored Chart.js 2.8
 * stack (all removed in Odoo 19). This rebuild:
 *   - is a plain OWL 2 component registered in the "actions" registry,
 *   - loads Chart.js through Odoo's own "web.chartjs_lib" asset bundle
 *     (Chart.js 4, already shipped with core and shared/cached across any
 *     other view - e.g. the Graph view - that also uses it) instead of
 *     shipping a second, older copy of the library, and
 *   - fetches all dashboard data with a single RPC call per filter change,
 *     same as before.
 */
export class AttendanceDashboard extends Component {
    static template = "attendance_dashboard.AttendanceDashboard";
    static props = ["*"];

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");

        this.pieRef = useRef("pieChart");
        this.lineRef = useRef("lineChart");
        this.barRef = useRef("barChart");

        this.state = useState({
            loading: true,
            filter: "today",
            today: "",
            kpi: { total: 0, present: 0, late: 0, leave: 0, absent: 0 },
        });

        // Chart.js instances, kept off the reactive state on purpose:
        // they're mutable third-party objects, not UI state to re-render on.
        this.charts = { pie: null, line: null, bar: null };

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
        });
        onWillStart(() => this.loadDashboard());

        onWillUnmount(() => {
            for (const chart of Object.values(this.charts)) {
                chart?.destroy();
            }
        });
    }

    async onFilterChange(ev) {
        this.state.filter = ev.target.value;
        await this.loadDashboard();
    }

    async loadDashboard() {
        let data;
        try {
            data = await this.orm.call("hr.attendance", "get_attendance_dashboard", [
                this.state.filter,
            ]);
        } catch {
            this.notification.add(_t("Could not load the attendance dashboard."), {
                title: _t("Attendance Dashboard"),
                type: "danger",
            });
            this.state.loading = false;
            return;
        }

        this.state.today = data.today;
        this.state.kpi = data.kpi;
        this.state.loading = false;

        this.renderPieChart(data.kpi);
        this.renderLineChart(data.progress);
        this.renderWorkUnitChart(data.workunit);
    }

    _renderChart(key, ref, config) {
        this.charts[key]?.destroy();
        if (!ref.el) {
            return;
        }
        this.charts[key] = new Chart(ref.el, config);
    }

    renderPieChart(kpi) {
        const total = kpi.total || 1;
        const pct = (n) => ((n / total) * 100).toFixed(1);

        this._renderChart("pie", this.pieRef, {
            type: "pie",
            data: {
                labels: [
                    _t("Present %s%%", pct(kpi.present)),
                    _t("Late %s%%", pct(kpi.late)),
                    _t("Leave %s%%", pct(kpi.leave)),
                    _t("Absent %s%%", pct(kpi.absent)),
                ],
                datasets: [
                    {
                        data: [kpi.present, kpi.late, kpi.leave, kpi.absent],
                        backgroundColor: [
                            KPI_COLORS.present,
                            KPI_COLORS.late,
                            KPI_COLORS.leave,
                            KPI_COLORS.absent,
                        ],
                    },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });
    }

    renderLineChart(progress) {
        this._renderChart("line", this.lineRef, {
            type: "line",
            data: {
                labels: progress.map((p) => p.label),
                datasets: [
                    {
                        label: _t("Presence"),
                        data: progress.map((p) => p.count),
                        borderColor: "#3498db",
                        backgroundColor: "rgba(52,152,219,0.1)",
                        fill: true,
                        tension: 0.3,
                    },
                ],
            },
            options: { responsive: true, maintainAspectRatio: false },
        });
    }

    renderWorkUnitChart(workunit) {
        this._renderChart("bar", this.barRef, {
            type: "bar",
            data: {
                labels: workunit.map((w) => w.unit),
                datasets: [
                    {
                        label: _t("Attendance"),
                        data: workunit.map((w) => w.count),
                        backgroundColor: "#8e44ad",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                // Chart.js 4 scale config (replaces the old v2 `scales.yAxes` array API).
                scales: { y: { beginAtZero: true } },
            },
        });
    }
}

registry.category("actions").add("attendance_dashboard.dashboard_action", AttendanceDashboard);
