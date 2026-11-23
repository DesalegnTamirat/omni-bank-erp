/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

const REFRESH_EVENT = "BUNNA:REFRESH_CURRENT_FORM";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        useBus(this.env.bus, REFRESH_EVENT, ({ detail: request }) => {
            const record = this.model.root;
            if (
                request.claimed ||
                !record ||
                (request.resModel && record.resModel !== request.resModel) ||
                (request.resId && Number(record.resId) !== Number(request.resId))
            ) {
                return;
            }
            // Reload the mounted form model. Owl keeps the current notebook
            // page and patches the changed row/table DOM.
            request.claimed = true;
            request.promise = this.model.load({ resId: record.resId });
        });
    },
});

/**
 * Refresh a saved form in place after an object button changes its child rows.
 * The server action can include params.title/message for a completion toast.
 */
async function refreshCurrentForm(env, action) {
    const params = action.params || {};
    const request = {
        resModel: params.res_model || action.context?.active_model,
        resId: params.res_id || action.context?.active_id,
        claimed: false,
        promise: null,
    };
    env.bus.trigger(REFRESH_EVENT, request);
    if (request.claimed) {
        await request.promise;
    } else {
        // A button may run outside a mounted form (for example from a list or modal).
        // If a form controller is open, try reloading its model first to preserve tabs.
        const controller = env.services.action.currentController;
        if (controller && controller.view && controller.view.type === "form" && controller.model && controller.model.root) {
            try {
                await controller.model.load({ resId: controller.model.root.resId });
            } catch (e) {
                await env.services.action.restore(controller.jsId);
            }
        } else if (controller) {
            await env.services.action.restore(controller.jsId);
        }
    }
    if (params.message) {
        env.services.notification.add(params.message, {
            title: params.title,
            type: params.type || "success",
            sticky: false,
        });
    }
}

registry.category("actions").add("bunna_refresh_form", refreshCurrentForm);
