/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { evaluateBooleanExpr } from "@web/core/py_js/py";

patch(ListController.prototype, {
    evalViewModifier(modifier) {
        if (!modifier) {
            return super.evalViewModifier(...arguments);
        }
        let evalContext = this.model && this.model.root ? { ...this.model.root.evalContext } : {};
        
        // Always provide default values for state-related variables to prevent NameError
        evalContext.state = false;
        evalContext.states = [];
        evalContext.has_under_review = false;
        evalContext.all_under_review = false;
        evalContext.all_submitted = false;

        const selection = this.model && this.model.root && this.model.root.selection;
        if (selection && selection.length > 0) {
            const states = new Set(
                selection.map((r) => r.data && r.data.state).filter(Boolean)
            );
            const isSingleState = states.size === 1;
            const singleState = isSingleState ? states.values().next().value : false;
            evalContext.state = singleState || (states.has("under_review") ? "under_review" : false);
            evalContext.states = Array.from(states);
            evalContext.has_under_review = states.has("under_review");
            evalContext.all_under_review = isSingleState && states.has("under_review");
            evalContext.all_submitted = isSingleState && states.has("submitted");
        }

        try {
            return evaluateBooleanExpr(modifier, evalContext);
        } catch (e) {
            return false;
        }
    },
});
