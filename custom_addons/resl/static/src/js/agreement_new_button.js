/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { FormController } from "@web/views/form/form_controller";
import { ReslAgreementDialog } from "./agreement_popup";

/**
 * "Agreement (Borrower)" for a NEW request that is not in the database yet.
 *
 * It is a plain button with its own onClick (not a native header button), so it
 * never forces Odoo to save the form: opening the agreement creates nothing.
 * The request is only created by Save or by picking a guarantor. When the
 * requester presses "Agree and continue" the page tells us, and we remember it
 *   - in the form (agr_pre_agreed, a non-stored field), and
 *   - in this browser (localStorage, for TODAY only), so closing the popup,
 *     refreshing the page or coming back to the New form keeps the agreement.
 * The server records the agreement on the request at the moment it is created;
 * the browser memory is cleared as soon as that request exists.
 *
 * Once the request is saved this widget disappears and the normal
 * "Agreement" buttons of the saved request take over.
 */
const storageKey = () => "resl_pre_agreed_" + user.userId;
const today = () => new Date().toISOString().slice(0, 10);

export function isPreAgreedStored() {
    try {
        return window.localStorage.getItem(storageKey()) === today();
    } catch (e) {
        return false;
    }
}
export function storePreAgreed() {
    try {
        window.localStorage.setItem(storageKey(), today());
    } catch (e) {
        // browser storage blocked: the agreement then only lives in the form
    }
}
export function clearPreAgreed() {
    try {
        window.localStorage.removeItem(storageKey());
    } catch (e) {
        // ignore
    }
}

export class ReslAgreementNewButton extends Component {
    static template = "resl.AgreementNewButton";
    static props = ["*"];

    setup() {
        this.dialog = useService("dialog");
        let wasNew = !this.props.record.resId;
        useEffect(
            () => {
                const record = this.props.record;
                if (!record.resId) {
                    wasNew = true;
                    // restore the agreement after a refresh / coming back to New
                    if (!record.data.agr_pre_agreed && isPreAgreedStored()) {
                        record.update({ agr_pre_agreed: true });
                    }
                } else if (wasNew) {
                    // the request was just created (Save): the agreement now
                    // lives on it, forget the browser copy
                    wasNew = false;
                    clearPreAgreed();
                }
            },
            () => [this.props.record.resId, this.props.record.data.agr_pre_agreed]
        );
    }

    get isVisible() {
        // New flow: the requester must find guarantors FIRST.
        // The borrower agrees only on a saved request after all guarantors
        // agreed. Hide this button entirely.
        return false;
    }

    get agreed() {
        return !!this.props.record.data.agr_pre_agreed;
    }

    onClick() {
        const record = this.props.record;
        const data = record.data;
        // A New form has no requested amount yet: create() stores the net
        // eligible amount, so that is the amount the agreement must show now.
        const amount = data.requested_amount || data.net_eligible_amount || 0;
        const url = "/resl/agreement/new?amt=" + encodeURIComponent(amount)
            + "&term=24"
            + (this.agreed ? "&agreed=1" : "");
        this.dialog.add(ReslAgreementDialog, {
            url,
            title: "Loan Agreement – Borrower",
            onPreAgreed: () => {
                storePreAgreed();
                record.update({ agr_pre_agreed: true });
            },
        });
    }
}

registry.category("view_widgets").add("resl_agreement_new_button", {
    component: ReslAgreementNewButton,
});

/**
 * Pressing New (list or form) first asks the server whether this user may
 * start a request. If not, the validation message is shown right there and no
 * form is opened and nothing is created.
 */
patch(ListController.prototype, {
    async createRecord(...args) {
        if (this.props.resModel === "resl.loan") {
            await (this.orm || this.model.orm).call("resl.loan", "resl_check_new_allowed", []);
        }
        return super.createRecord(...args);
    },
});
patch(FormController.prototype, {
    async create(...args) {
        if (this.props.resModel === "resl.loan") {
            await (this.orm || this.model.orm).call("resl.loan", "resl_check_new_allowed", []);
        }
        return super.create(...args);
    },
});