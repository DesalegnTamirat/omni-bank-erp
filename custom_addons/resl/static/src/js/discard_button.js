/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { Component } from "@odoo/owl";
import { clearPreAgreed } from "./agreement_new_button";

/**
 * "Discard" for the requester, at any stage before the request is submitted
 * to the manager (Draft / Waiting Guarantees), including a brand-new form.
 *
 * Like the Find Guarantor widget this is NOT a native header button, because
 * a native button would first save a new/dirty record. Here:
 *   - brand-new, never-saved request: nothing exists in the database, so it
 *     just leaves the form (back to the Staff Loans list);
 *   - saved request: edits are reverted, then resl.loan.action_discard_request
 *     deletes the record from the database, then back to the list.
 */
export class ReslDiscardButton extends Component {
    static template = "resl.DiscardButton";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    }

    get isVisible() {
        const data = this.props.record.data;
        return !!data.is_employee_user && ["draft", "guarantor_pending"].includes(data.status);
    }

    onClick() {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Discard request"),
            body: _t("Discard this request? It will be deleted and cannot be recovered."),
            confirmLabel: _t("Discard"),
            confirm: () => this.discard(),
            cancel: () => {},
        });
    }

    async discard() {
        const record = this.props.record;
        clearPreAgreed();   // a discarded request must not leave a remembered agreement behind
        if (record.resId) {
            // Revert unsaved edits so leaving the form never tries to save a
            // record that is about to be deleted.
            await record.discard();
            await this.orm.call("resl.loan", "action_discard_request", [[record.resId]]);
        }
        await this.action.doAction("resl.action_resl_loan_tree", { clearBreadcrumbs: true });
    }
}

registry.category("view_widgets").add("resl_discard_button", {
    component: ReslDiscardButton,
});