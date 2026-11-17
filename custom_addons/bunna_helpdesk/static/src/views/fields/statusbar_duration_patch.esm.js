/**
 * bunna_helpdesk — statusbar_duration_patch.esm.js
 *
 * 1. Guard against "TypeError: this.specialData.data.map is not a function" during initial Owl render.
 * 2. Intercept stage clicks on helpdesk.ticket:
 *    - Clicking "Rejected" opens helpdesk.ticket.reject.wizard.
 *    - Clicking "Done" opens helpdesk.ticket.done.wizard (prompts for Agent Response & saves to KB).
 *    - Clicking "Reopen" opens helpdesk.ticket.reopen.wizard (prompts for Reopen Reason).
 *    - Clicking "Cancelled" opens helpdesk.ticket.cancel.wizard (prompts for Cancellation Reason).
 *
 * Note: StatusBarDurationField extends StatusBarField, so patching StatusBarField.prototype
 * applies cleanly to both standard statusbars and duration statusbars without recursion.
 */
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { patch } from "@web/core/utils/patch";

patch(StatusBarField.prototype, {
    getAllItems() {
        const data = this.specialData?.data;
        // Guard: during the first render the async searchRead hasn't resolved yet,
        // so data is still the initial `{}`. Return [] until data is an array.
        if (this.field?.type === "many2one" && !Array.isArray(data)) {
            return [];
        }
        return super.getAllItems(...arguments);
    },

    async selectItem(item) {
        const record = this.props?.record;
        if (record && record.resModel === "helpdesk.ticket" && this.props.name === "stage_id") {
            const label = String(item?.label || "").toLowerCase();
            const actionService = this.env?.services?.action;

            if (label.includes("reject") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Reject Ticket",
                    res_model: "helpdesk.ticket.reject.wizard",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_ticket_id: ticketId,
                    },
                }, {
                    onClose: async () => {
                        await record.load();
                        record.model?.notify();
                    },
                });
                return;
            }

            if (label.includes("done") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                const stageRaw = record.data?.stage_id;
                let stageName = "";
                if (Array.isArray(stageRaw) && stageRaw.length > 1) {
                    stageName = String(stageRaw[1] || "").toLowerCase();
                } else if (stageRaw && typeof stageRaw === "object") {
                    stageName = String(stageRaw.display_name || stageRaw.name || stageRaw.label || "").toLowerCase();
                } else if (stageRaw) {
                    stageName = String(stageRaw).toLowerCase();
                }
                const hasInitialResponse = Boolean(
                    record.data?.agent_action_taken && String(record.data.agent_action_taken).trim()
                );
                const isEscalated = Boolean(
                    record.data?.is_escalated ||
                    record.data?.is_reopened ||
                    hasInitialResponse ||
                    stageName.includes("escalat") ||
                    (record.data?.escalation_level && record.data.escalation_level > 1)
                );
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Ticket Done - Agent Response",
                    res_model: "helpdesk.ticket.done.wizard",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_ticket_id: ticketId,
                        default_target_stage_id: item?.value,
                        default_is_escalated: isEscalated,
                    },
                }, {
                    onClose: async () => {
                        await record.load();
                        record.model?.notify();
                    },
                });
                return;
            }

            if (label.includes("reopen") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Reopen Ticket",
                    res_model: "helpdesk.ticket.reopen.wizard",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_ticket_id: ticketId,
                        default_target_stage_id: item?.value,
                    },
                }, {
                    onClose: async () => {
                        await record.load();
                        record.model?.notify();
                    },
                });
                return;
            }

            if (label.includes("cancel") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Cancel Ticket",
                    res_model: "helpdesk.ticket.cancel.wizard",
                    views: [[false, "form"]],
                    target: "new",
                    context: {
                        default_ticket_id: ticketId,
                        default_target_stage_id: item?.value,
                    },
                }, {
                    onClose: async () => {
                        await record.load();
                        record.model?.notify();
                    },
                });
                return;
            }
        }

        return super.selectItem(...arguments);
    },
});
