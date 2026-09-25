/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

/**
 * Replaces the native <button type="action"> for "Find Guarantor".
 *
 * A native header button always forces Odoo to save the record first if
 * it's new/dirty (that's true for type="object" and type="action" buttons
 * alike — it's how the form controller's button-click pipeline works, not
 * something an XML attribute can turn off). That's exactly what we don't
 * want here: searching for a guarantor shouldn't create a draft loan by
 * itself. Only an explicit Save, or actually picking a guarantor
 * (resl.guarantor.lookup.line.action_select, which creates the loan itself
 * when needed), is allowed to do that.
 *
 * This widget is a plain button with its own onClick, so it never goes
 * through that save-first pipeline. It opens the same wizard action the
 * old button did, passing along the current record's id (or false, if the
 * record hasn't been saved yet — the wizard and action_select both handle
 * that case).
 */
export class ReslFindGuarantorButton extends Component {
    static template = "resl.FindGuarantorButton";
    static props = ["*"];

    setup() {
        this.action = useService("action");
    }

    get isVisible() {
        const data = this.props.record.data;
        if (!data.is_employee_user || data.has_active_guarantor) {
            return false;
        }
        if (!["draft", "guarantor_pending"].includes(data.status)) {
            return false;
        }
        if (data.status === "draft" && !data.is_eligible) {
            return false;
        }
        return true;
    }

    async onClick() {
        const record = this.props.record;
        await this.action.doAction("resl.action_resl_guarantor_lookup", {
            additionalContext: { default_loan_id: record.resId || false },
            onClose: (closeInfo) => {
                const newLoanId = closeInfo && closeInfo.new_loan_id;
                if (newLoanId) {
                    // A brand-new loan was created by the wizard (the form
                    // behind it was still on "New"). Navigate to it now
                    // that the dialog has fully closed — doing this from
                    // the server response itself is what raced with the
                    // dialog's teardown and threw "Component is destroyed".
                    this.action.doAction({
                        type: "ir.actions.act_window",
                        res_model: "resl.loan",
                        res_id: newLoanId,
                        views: [[false, "form"]],
                        target: "main",
                    });
                } else {
                    record.load();
                }
            },
        });
    }
}

registry.category("view_widgets").add("resl_find_guarantor_button", {
    component: ReslFindGuarantorButton,
});