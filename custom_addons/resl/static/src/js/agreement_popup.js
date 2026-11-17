/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";

/**
 * "Agreement" opens as a popup on the current page (an iframe on the agreement
 * page) instead of a new tab.
 *
 * The page posts a message to us:
 *   resl_agreement_saved -> something was saved (remember to refresh)
 *   resl_agreement_done  -> "Save and continue" was pressed: close the popup
 * Whenever the popup closes after something was saved, the page is reloaded so
 * the loan form shows the new state (buttons, banners, status).
 */
class ReslAgreementDialog extends Component {
    static template = "resl.AgreementDialog";
    static components = { Dialog };
    static props = ["*"];

    setup() {
        this.onMessage = (ev) => {
            if (ev.origin !== window.location.origin) {
                return;
            }
            const type = ev.data && ev.data.type;
            if (type === "resl_agreement_saved") {
                this.props.onSaved();
            } else if (type === "resl_agreement_done") {
                this.props.onSaved();
                this.props.close();
            }
        };
        onMounted(() => window.addEventListener("message", this.onMessage));
        onWillUnmount(() => window.removeEventListener("message", this.onMessage));
    }
}

registry.category("actions").add("resl_agreement_popup", async (env, action) => {
    const params = action.params || {};
    let dirty = false;
    env.services.dialog.add(
        ReslAgreementDialog,
        {
            url: params.url,
            title: params.title || "Loan Agreement",
            onSaved: () => {
                dirty = true;
            },
        },
        {
            onClose: () => {
                // Always reload: just opening the agreement counts as "viewed"
                // (mandatory before requesting / doing the disbursement).
                if (dirty || true) {
                    env.services.action.doAction({ type: "ir.actions.client", tag: "reload" });
                }
            },
        }
    );
});
