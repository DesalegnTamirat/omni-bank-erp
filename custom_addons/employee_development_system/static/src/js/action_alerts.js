/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class EdsActionHeads extends Component {
    static template = "employee_development_system.EdsActionHeads";
    static props = {};

    setup() {
        this.bus = useService("bus_service");
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ alerts: [], isOpen: false });
        this.onAlert = (alert) => {
            // Replace a replayed reminder when the live notification arrives.
            const replayIndex = this.state.alerts.findIndex(
                (item) => item.replayed && item.model === alert.model && item.res_id === alert.res_id
            );
            if (replayIndex >= 0) this.state.alerts.splice(replayIndex, 1);
            const key = String(alert.actor_partner_id || alert.actor || "eds");
            this.state.alerts.unshift({
                ...alert, key, uid: `${Date.now()}-${Math.random()}`,
            });
            // The Odoo inbox stores the full history; keep this live panel bounded.
            this.state.alerts.splice(40);
        };
        this.bus.subscribe("eds.action_notification", this.onAlert);
        this.bus.start();
        onMounted(() => { void this.loadPendingActions(); });
        onWillUnmount(() => this.bus.unsubscribe("eds.action_notification", this.onAlert));
    }

    async loadPendingActions() {
        try {
            const pending = await this.orm.call(
                "eds.enrollment", "get_my_pending_action_alerts", []
            );
            for (const alert of pending) {
                if (this.state.alerts.some(
                    (item) => item.model === alert.model && item.res_id === alert.res_id
                )) continue;
                const key = String(alert.actor_partner_id || alert.actor || "eds");
                this.state.alerts.push({
                    ...alert, key, replayed: true,
                    uid: alert.notification_key || `pending-${alert.res_id}`,
                });
            }
            // Keep the live panel bounded even after an offline absence.
            this.state.alerts.splice(40);
        } catch {
            // The inbox remains available if this optional reminder cannot load.
        }
    }

    get totalCount() {
        return this.state.alerts.length;
    }

    get activeAlerts() {
        return this.state.alerts;
    }

    toggle() {
        this.state.isOpen = !this.state.isOpen;
    }

    close() {
        this.state.isOpen = false;
    }

    async open(alert) {
        await this.action.doAction(alert.form_view_id ? {
            type: "ir.actions.act_window",
            res_model: alert.model,
            res_id: alert.res_id,
            views: [[alert.form_view_id, "form"]],
            target: "current",
        } : alert.action_id || {
            type: "ir.actions.act_window",
            res_model: alert.model,
            res_id: alert.res_id,
            views: [[false, "form"]],
            target: "current",
        });
        this.dismiss(alert);
    }

    dismiss(alert) {
        const index = this.state.alerts.findIndex((item) => item.uid === alert.uid);
        if (index >= 0) this.state.alerts.splice(index, 1);
        if (this.state.alerts.length === 0) {
            this.state.isOpen = false;
        }
    }
}

registry.category("main_components").add("eds_action_heads", { Component: EdsActionHeads });
