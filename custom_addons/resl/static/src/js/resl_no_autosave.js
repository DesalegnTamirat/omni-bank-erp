/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { Record } from "@web/model/relational_model/record";

/**
 * A NEW staff loan request must never be written to the database unless the
 * user clicks a header button (Save = action_save_request, ...) or picks a
 * guarantor in Find Guarantor (that wizard creates the loan itself).
 *
 * Whatever triggers Odoo's auto-save (refresh, tab switch, leaving the form,
 * chatter, pager, ...), the actual INSERT goes through Record._save, so that is
 * blocked here for a not-yet-created resl.loan unless a button click allowed it.
 */
console.info("[RESL] no-autosave patch loaded");

function isNewLoan(record) {
    return !!record && record.resModel === "resl.loan" && !record.resId;
}

patch(Record.prototype, {
    async _save() {
        if (isNewLoan(this) && !this.model._reslAllowSave) {
            console.warn("[RESL] blocked auto-save of a new loan request", new Error().stack);
            return false;
        }
        return super._save(...arguments);
    },
});

patch(FormController.prototype, {
    // A button click on the form is an explicit user action: allow the save.
    async beforeExecuteActionButton() {
        const model = this.model;
        model._reslAllowSave = true;
        try {
            return await super.beforeExecuteActionButton(...arguments);
        } finally {
            model._reslAllowSave = false;
        }
    },

    // Clicking "New" on a new, unsaved form: just open a fresh form.
    async create() {
        if (isNewLoan(this.model.root)) {
            return this.model.load({ resId: false });
        }
        return super.create(...arguments);
    },

    // No "unsaved changes" browser prompt / sendBeacon for an unsaved loan.
    async beforeUnload() {
        if (isNewLoan(this.model.root)) {
            return;
        }
        return super.beforeUnload(...arguments);
    },

    beforeVisibilityChange() {
        if (isNewLoan(this.model.root)) {
            return;
        }
        return super.beforeVisibilityChange(...arguments);
    },

    async beforeLeave() {
        if (isNewLoan(this.model.root)) {
            return;
        }
        return super.beforeLeave(...arguments);
    },
});