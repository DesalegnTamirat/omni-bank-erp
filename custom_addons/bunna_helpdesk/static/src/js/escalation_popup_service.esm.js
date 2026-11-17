import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

export const escalationPopupService = {
    dependencies: ["notification", "action"],
    start(env, { notification, action }) {
        let isChecking = false;
        const shownPopupIds = new Set();

        async function checkPendingEscalations() {
            if (isChecking) {
                return;
            }
            isChecking = true;
            try {
                const popups = await rpc("/bunna_helpdesk/get_pending_escalations", {});
                if (popups && popups.length > 0) {
                    for (const item of popups) {
                        if (shownPopupIds.has(item.id)) {
                            continue;
                        }
                        shownPopupIds.add(item.id);

                        const messageContent = [
                            `📌 Ticket #: ${item.ticket_number}`,
                            `👤 Customer: ${item.customer_name} (${item.customer_phone})`,
                            `🏢 Unit: ${item.operating_unit_name || "Assigned Unit"}`,
                            `🚨 Stage: ${item.escalation_level_name}`,
                            `👤 Escalated By: ${item.escalated_by_name}`,
                            `🕒 Date: ${item.escalation_date}`,
                            item.issue_description ? `📝 Issue: ${item.issue_description}` : "",
                        ].filter(Boolean).join("\n");

                        notification.add(messageContent, {
                            title: _t("🚨 Action Required: New Ticket Escalated to You!"),
                            type: "warning",
                            sticky: true,
                            buttons: [
                                {
                                    name: _t("Open Ticket"),
                                    primary: true,
                                    onClick: async () => {
                                        await rpc("/bunna_helpdesk/acknowledge_escalation", { popup_id: item.id });
                                        action.doAction({
                                            type: "ir.actions.act_window",
                                            res_model: "helpdesk.ticket",
                                            res_id: item.ticket_id,
                                            views: [[false, "form"]],
                                            target: "current",
                                        });
                                    },
                                },
                                {
                                    name: _t("Acknowledge & Dismiss"),
                                    onClick: async () => {
                                        await rpc("/bunna_helpdesk/acknowledge_escalation", { popup_id: item.id });
                                    },
                                },
                            ],
                        });
                    }
                }
            } catch (err) {
                // Silently ignore network or offline issues during polling
            } finally {
                isChecking = false;
            }
        }

        // 1. Initial check when user opens desktop / PC web client
        setTimeout(checkPendingEscalations, 1500);

        // 2. Periodic background check every 30 seconds for live incoming escalations
        setInterval(checkPendingEscalations, 30000);
    },
};

registry.category("services").add("escalation_popup", escalationPopupService);
