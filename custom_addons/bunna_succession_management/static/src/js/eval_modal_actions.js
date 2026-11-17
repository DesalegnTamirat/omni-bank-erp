/** @odoo-module **/

import { registry } from "@web/core/registry";

/**
 * Remove any active ActionDialog / ViewDialog overlays cleanly before
 * opening another modal or exiting back to the underlying form view.
 * This prevents Odoo's action service dialog reference from being
 * overwritten mid-transition and leaving earlier modal frames stacked.
 */
async function closeOpenDialogOverlays(env) {
    const overlays = env.services.overlay?.overlays || {};
    const dialogEntries = Object.values(overlays).filter(
        (ov) => ov?.props?.subComponent
    );
    for (const ov of dialogEntries) {
        try {
            await ov.remove();
        } catch (_) {
            // Overlay was already detaching; continue closing remaining layers.
        }
    }
}

async function switchEvalModalAction(env, action) {
    await closeOpenDialogOverlays(env);
    const windowAction = action?.params?.window_action;
    if (windowAction) {
        return env.services.action.doAction(windowAction);
    }
}

async function closeEvalModalsAction(env, action) {
    await closeOpenDialogOverlays(env);
    const currentController = env.services.action.currentController;
    if (currentController) {
        await env.services.action.restore(currentController.jsId);
    }
    await env.services.action.doAction({ type: "ir.actions.client", tag: "soft_reload" });
    const notif = action?.params?.notification;
    if (notif) {
        env.services.notification.add(notif.message || "", {
            title: notif.title,
            type: notif.type || "success",
            sticky: Boolean(notif.sticky),
        });
    }
}

registry.category("actions").add("bunna_switch_eval_modal", switchEvalModalAction);
registry.category("actions").add("bunna_close_eval_modals", closeEvalModalsAction);
