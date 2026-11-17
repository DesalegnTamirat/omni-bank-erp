/**
 * bunna_helpdesk — statusbar_duration_patch.esm.js
 *
 * 1. Guard against "TypeError: this.specialData.data.map is not a function" during initial Owl render.
 * 2. Intercept stage clicks on helpdesk.ticket:
 *    - Clicking "Rejected" opens helpdesk.ticket.reject.wizard.
 *    - Clicking "Resolve" / "Resolved" opens helpdesk.ticket.done.wizard (prompts for Agent Response & saves to KB).
 *    - Clicking "Reopen" opens helpdesk.ticket.reopen.wizard (prompts for Reopen Reason).
 *    - Clicking "Cancelled" opens helpdesk.ticket.cancel.wizard (prompts for Cancellation Reason).
 *    - Clicking "In Progress" opens helpdesk.ticket.inprogress.wizard (agent acceptance notes).
 *
 * Note: StatusBarDurationField extends StatusBarField, so patching StatusBarField.prototype
 * applies cleanly to both standard statusbars and duration statusbars without recursion.
 */
import { Component, useEffect } from "@odoo/owl";
import { StatusBarField } from "@web/views/fields/statusbar/statusbar_field";
import { patch } from "@web/core/utils/patch";

patch(StatusBarField.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(() => {
            const root = this.rootRef?.el;
            const record = this.props?.record;
            if (root && record && record.resModel === "helpdesk.ticket" && this.props.name === "stage_id" && !this.props.isDisabled) {
                const currentStageRaw = record.data?.stage_id;
                let currentStageName = "";
                if (Array.isArray(currentStageRaw) && currentStageRaw.length > 1) {
                    currentStageName = String(currentStageRaw[1] || "").toLowerCase();
                } else if (currentStageRaw && typeof currentStageRaw === "object") {
                    currentStageName = String(currentStageRaw.display_name || currentStageRaw.name || currentStageRaw.label || "").toLowerCase();
                } else if (currentStageRaw) {
                    currentStageName = String(currentStageRaw).toLowerCase();
                }
                const isTerminal = currentStageName.includes("done") || currentStageName.includes("resolved") || currentStageName.includes("resolve") || currentStageName.includes("close") || currentStageName.includes("reject") || record.data?.closed || record.data?.is_rejected;

                const arrowButtons = root.querySelectorAll(".o_arrow_button");
                for (const btn of arrowButtons) {
                    const txt = (btn.textContent || "").toLowerCase();
                    if (txt.includes("escalat") && !isTerminal) {
                        btn.removeAttribute("disabled");
                        btn.classList.remove("disabled");
                        btn.style.cursor = "pointer";
                        btn.style.pointerEvents = "auto";
                    }
                }
            }
        });
    },

    getDropdownItemClassNames(item) {
        const record = this.props?.record;
        if (record && record.resModel === "helpdesk.ticket" && this.props.name === "stage_id") {
            const label = String(item?.label || "").toLowerCase();
            if (label.includes("escalat")) {
                const classNames = ["o_helpdesk_stage_escalated"];
                if (item.isSelected) {
                    classNames.push("active");
                }
                if (this.props.isDisabled) {
                    classNames.push("disabled");
                }
                return classNames.join(" ");
            }
        }
        return super.getDropdownItemClassNames(...arguments);
    },

    getAllItems() {
        const data = this.specialData?.data;
        // Guard: during the first render the async searchRead hasn't resolved yet,
        // so data is still the initial `{}`. Return [] until data is an array.
        if (this.field?.type === "many2one" && !Array.isArray(data)) {
            return [];
        }
        const items = super.getAllItems(...arguments);
        const record = this.props?.record;
        if (record && record.resModel === "helpdesk.ticket" && this.props.name === "stage_id") {
            const isTicketEscalated = Boolean(record.data?.is_escalated);
            return items
                .filter((item) => {
                    const lower = String(item.label || "").toLowerCase();
                    // Completely remove redundant "Done" and "Pending" stages
                    return lower !== "done" && !lower.startsWith("done ") && lower !== "pending" && !lower.startsWith("pending");
                })
                .map((item) => {
                    const lower = String(item.label || "").toLowerCase();
                    if (lower.includes("escalat")) {
                        return {
                            ...item,
                            label: (item.isSelected || isTicketEscalated) ? "Escalated" : "Escalate",
                        };
                    }
                    return item;
                });
        }
        return items;
    },

    async selectItem(item) {
        const record = this.props?.record;
        if (record && record.resModel === "helpdesk.ticket" && this.props.name === "stage_id") {
            const label = String(item?.label || "").toLowerCase();
            const actionService = this.env?.services?.action;

            // Check if ticket is currently Resolved / Done: Resolved tickets can only transition to Reopen, Closed, or Escalate
            const currentStageRaw = record.data?.stage_id;
            let currentStageName = "";
            if (Array.isArray(currentStageRaw) && currentStageRaw.length > 1) {
                currentStageName = String(currentStageRaw[1] || "").toLowerCase();
            } else if (currentStageRaw && typeof currentStageRaw === "object") {
                currentStageName = String(currentStageRaw.display_name || currentStageRaw.name || currentStageRaw.label || "").toLowerCase();
            } else if (currentStageRaw) {
                currentStageName = String(currentStageRaw).toLowerCase();
            }

            const currentStageId = Array.isArray(currentStageRaw) ? currentStageRaw[0] : (currentStageRaw?.id || currentStageRaw);
            const isCurrentlyResolved = currentStageName.includes("done") || currentStageName.includes("resolved") || currentStageName.includes("resolve");
            const isCurrentlyClosed = currentStageName.includes("close") || Boolean(record.data?.closed);
            const isCurrentlyRejected = currentStageName.includes("reject") || Boolean(record.data?.is_rejected);
            const notification = this.env?.services?.notification;

            // 1. Resolved tickets can only transition to Reopen or Closed
            if (isCurrentlyResolved && item?.value && item.value !== currentStageId) {
                const isTargetAllowed = label.includes("reopen") || label.includes("close") || label.includes("closed");
                if (!isTargetAllowed) {
                    if (notification) {
                        notification.add(
                            "This ticket is marked as Resolved. Once resolved, it can only be Closed or Reopened. To change its stage to '" + (item?.label || "another stage") + "', please click 'Reopen' first.",
                            { type: "warning", title: "Ticket is Resolved" }
                        );
                    }
                    return;
                }
            }

            // 2. Closed tickets can only transition to Reopen
            if (isCurrentlyClosed && item?.value && item.value !== currentStageId) {
                const isTargetAllowed = label.includes("reopen");
                if (!isTargetAllowed) {
                    if (notification) {
                        notification.add(
                            "This ticket is Closed. Once closed, it can only be Reopened. To change its stage to '" + (item?.label || "another stage") + "', please click 'Reopen' first.",
                            { type: "warning", title: "Ticket is Closed" }
                        );
                    }
                    return;
                }
            }

            // 3. Rejected tickets can only transition to Reopen
            if (isCurrentlyRejected && item?.value && item.value !== currentStageId) {
                const isTargetAllowed = label.includes("reopen");
                if (!isTargetAllowed) {
                    if (notification) {
                        notification.add(
                            "This ticket is Rejected. Once rejected, it can only be Reopened. To change its stage to '" + (item?.label || "another stage") + "', please click 'Reopen' first.",
                            { type: "warning", title: "Ticket is Rejected" }
                        );
                    }
                    return;
                }
            }

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

            if (label.includes("escalat") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                const action = await record.model.orm.call(
                    "helpdesk.ticket",
                    "action_open_escalate_wizard",
                    [[ticketId]],
                    { context: record.context }
                );
                if (action) {
                    if (!action.views || !Array.isArray(action.views) || !action.views.length) {
                        action.views = [[false, "form"]];
                    }
                    await actionService.doAction(action, {
                        onClose: async () => {
                            await record.load();
                            record.model?.notify();
                        },
                    });
                }
                return;
            }

            if ((label.includes("resolve") || label.includes("done")) && actionService) {
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
                    name: "Resolve Ticket - Case Resolution",
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

            if (label.includes("in progress") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Accept Ticket — In Progress",
                    res_model: "helpdesk.ticket.inprogress.wizard",
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

            if (label.includes("pending") && actionService) {
                if (record.isDirty) {
                    await record.save();
                }
                const ticketId = record.resId;
                if (!ticketId) {
                    return;
                }
                await actionService.doAction({
                    type: "ir.actions.act_window",
                    name: "Ticket Pending - Escalated Pending Resolution",
                    res_model: "helpdesk.ticket.pending.wizard",
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
