/** @odoo-module **/

import { Component, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class EdsActionHeads extends Component {
    static template = "employee_development_system.EdsActionHeads";
    static props = {};

    setup() {
        this.bus = useService("bus_service");
        this.action = useService("action");
        this.state = useState({ alerts: [], activeActor: null });
        this.onAlert = (alert) => {
            const key = String(alert.actor_partner_id || alert.actor || "eds");
            this.state.alerts.unshift({
                ...alert, key, uid: `${Date.now()}-${Math.random()}`,
            });
            // The Odoo inbox stores the full history; keep this live panel bounded.
            this.state.alerts.splice(40);
        };
        this.bus.subscribe("eds.action_notification", this.onAlert);
        this.bus.start();
        onWillUnmount(() => this.bus.unsubscribe("eds.action_notification", this.onAlert));
    }

    get heads() {
        const groups = new Map();
        for (const alert of this.state.alerts) {
            if (!groups.has(alert.key)) {
                groups.set(alert.key, {
                    key: alert.key,
                    actor: alert.actor || "Employee Development",
                    initial: (alert.actor || "E").trim().charAt(0).toUpperCase(),
                    count: 0,
                });
            }
            groups.get(alert.key).count++;
        }
        return [...groups.values()];
    }

    get activeAlerts() {
        return this.state.alerts.filter(
            (alert) => alert.key === this.state.activeActor
        );
    }

    get activeActorName() {
        return this.activeAlerts[0]?.actor || "Notifications";
    }

    toggle(key) {
        this.state.activeActor = this.state.activeActor === key ? null : key;
    }

    close() {
        this.state.activeActor = null;
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
        if (!this.state.alerts.some((item) => item.key === this.state.activeActor)) {
            this.state.activeActor = null;
        }
    }
}

registry.category("main_components").add("eds_action_heads", { Component: EdsActionHeads });
