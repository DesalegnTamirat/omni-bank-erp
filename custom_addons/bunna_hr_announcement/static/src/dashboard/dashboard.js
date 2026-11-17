/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const BADGE = {
    live: "text-bg-success",
    scheduled: "text-bg-info",
    expired: "text-bg-warning",
    revoked: "text-bg-danger",
    draft: "text-bg-secondary",
};

const KPI_ICON = {
    live: "fa-bullhorn",
    scheduled: "fa-clock-o",
    draft: "fa-pencil",
    expired: "fa-hourglass-end",
    revoked: "fa-ban",
    expiring: "fa-exclamation-triangle",
    pending_comments: "fa-comments",
    reported_comments: "fa-flag",
    views: "fa-eye",
    archived: "fa-archive",
    edited: "fa-edit",
};

const LIST_ICON = {
    expiring: "fa-exclamation-triangle",
    drafts: "fa-pencil",
    scheduled: "fa-clock-o",
};

export class BunnaAnnouncementDashboard extends Component {
    static template = "bunna_hr_announcement.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call("bunna.announcement.dashboard", "get_data", []);
        } catch (error) {
            this.state.error = true;
            console.error("Announcement dashboard failed to load", error);
        }
        this.state.loading = false;
    }

    badgeClass(status) {
        return "badge rounded-pill " + (BADGE[status] || "text-bg-secondary");
    }

    barHeight(value) {
        const max = this.state.data.chart.max || 1;
        return Math.max(value ? 4 : 0, Math.round((value / max) * 100));
    }

    topWidth(value) {
        const top = this.state.data.top.length ? this.state.data.top[0].value : 1;
        return Math.max(4, Math.round((value / (top || 1)) * 100));
    }

    // KPI cards always fill exactly two rows: half the cards per row, and when the
    // count is odd the last card is stretched so the second row has no gap.
    get kpiCols() {
        return Math.max(1, Math.ceil(this.state.data.kpis.length / 2));
    }

    get kpiOdd() {
        return this.state.data.kpis.length % 2 === 1;
    }

    kpiIcon(key) {
        return KPI_ICON[key] || "fa-circle";
    }

    listIcon(key) {
        return LIST_ICON[key] || "fa-list";
    }

    openKpi(kpi) {
        if (kpi.action) {
            return this.action.doAction("bunna_hr_announcement." + kpi.action);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: kpi.label,
            res_model: kpi.res_model || "bunna.announcement",
            views: [[false, "list"], [false, "form"]],
            domain: kpi.domain || [],
        });
    }

    openLink(link) {
        return this.action.doAction("bunna_hr_announcement." + link.action);
    }

    openRecord(id) {
        if (!id) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "bunna.announcement",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    createAnnouncement() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "New announcement",
            res_model: "bunna.announcement",
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("bunna_announcement_dashboard", BunnaAnnouncementDashboard);
