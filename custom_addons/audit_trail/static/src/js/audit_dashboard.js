/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class AuditDashboard extends Component {
    static template = "audit_trail.AuditDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            total: 0,
            creates: 0,
            writes: 0,
            unlinks: 0,
            createPct: 0,
            writePct: 0,
            unlinkPct: 0,
            byModule: [],
            byUser: [],
            loading: true,
            dateFilter: "today",
        });

        onWillStart(() => this.loadData());
    }

    _getDateFilter() {
        const now = new Date();
        if (this.state.dateFilter === "today") {
            const start = new Date(now); start.setHours(0, 0, 0, 0);
            return [["create_date", ">=", this._fmt(start)]];
        }
        if (this.state.dateFilter === "yesterday") {
            const start = new Date(now); start.setDate(start.getDate() - 1); start.setHours(0, 0, 0, 0);
            const end   = new Date(now); end.setHours(0, 0, 0, 0);
            return [["create_date", ">=", this._fmt(start)], ["create_date", "<", this._fmt(end)]];
        }
        if (this.state.dateFilter === "week") {
            const start = new Date(now); start.setDate(start.getDate() - 6); start.setHours(0, 0, 0, 0);
            return [["create_date", ">=", this._fmt(start)]];
        }
        if (this.state.dateFilter === "month") {
            const start = new Date(now.getFullYear(), now.getMonth(), 1);
            return [["create_date", ">=", this._fmt(start)]];
        }
        return [];
    }

    _fmt(date) {
        return date.toISOString().replace("T", " ").slice(0, 19);
    }

    setFilter(filter) {
        this.state.dateFilter = filter;
        this.loadData();
    }

    async loadData() {
        this.state.loading = true;
        const dateDomain = this._getDateFilter();

        try {
            // ── counts ───────────────────────────────────────────────
            const total   = await this.orm.searchCount("audit.log", dateDomain);
            const creates = await this.orm.searchCount("audit.log", [...dateDomain, ["operation", "=", "create"]]);
            const writes  = await this.orm.searchCount("audit.log", [...dateDomain, ["operation", "=", "write"]]);
            const unlinks = await this.orm.searchCount("audit.log", [...dateDomain, ["operation", "=", "unlink"]]);

            this.state.total     = total;
            this.state.creates   = creates;
            this.state.writes    = writes;
            this.state.unlinks   = unlinks;
            this.state.createPct = total ? Math.round(creates / total * 100) : 0;
            this.state.writePct  = total ? Math.round(writes  / total * 100) : 0;
            this.state.unlinkPct = total ? Math.round(unlinks / total * 100) : 0;

            // ── group by module ──────────────────────────────────────
            const modRaw = await this.orm.webReadGroup(
                "audit.log", dateDomain, ["module"], ["module:count"], { limit: 10 }
            );
            const byModule = (Array.isArray(modRaw) ? modRaw : (modRaw.groups || []))
                .sort((a, b) => b["module:count"] - a["module:count"])
                .slice(0, 6);

            const maxMod = byModule.length ? Math.max(...byModule.map(m => m["module:count"])) : 1;
            byModule.forEach(m => {
                m.module_count = m["module:count"];
                m._pct = Math.round(m["module:count"] / maxMod * 100);
            });
            this.state.byModule = byModule;

            // ── group by user ────────────────────────────────────────
            const userRaw = await this.orm.webReadGroup(
                "audit.log", dateDomain, ["user_id"], ["user_id:count"], { limit: 20 }
            );
            const byUser = (Array.isArray(userRaw) ? userRaw : (userRaw.groups || []))
                .sort((a, b) => b["user_id:count"] - a["user_id:count"])
                .slice(0, 5);

            const maxUser = byUser.length ? Math.max(...byUser.map(u => u["user_id:count"])) : 1;
            byUser.forEach(u => {
                u.user_id_count = u["user_id:count"];
                u._pct = Math.round(u["user_id:count"] / maxUser * 100);
                u._initials = (u.user_id[1] || "NA")
                    .split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
            });
            this.state.byUser = byUser;

        } catch (e) {
            console.error("[AuditDashboard] ERROR:", e);
        } finally {
            this.state.loading = false;
        }
    }

    openLogs(domain, name) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "Audit Logs",
            res_model: "audit.log",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain || [],
            target: "current",
        });
    }
}

registry.category("actions").add("audit_trail.audit_dashboard", AuditDashboard);