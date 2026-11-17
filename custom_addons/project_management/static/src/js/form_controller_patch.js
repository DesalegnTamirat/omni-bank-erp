/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

patch(FormController.prototype, {
    /**
     * Option 2 Auto-Save Control:
     * Discard unsaved changes on leave unless the user explicitly clicked Save.
     */
    async beforeLeave({ forceLeave } = {}) {
        if (this.props.resModel && this.props.resModel.startsWith("pm.")) {
            if (this.model.root.dirty && !forceLeave) {
                // Explicitly discard uncommitted changes when leaving without saving
                await this.model.root.discard();
                return true;
            }
            return true;
        }
        return super.beforeLeave(...arguments);
    },

    /**
     * Prevent background auto-saving when browser tab/window changes visibility.
     */
    beforeVisibilityChange() {
        if (this.props.resModel && this.props.resModel.startsWith("pm.")) {
            return;
        }
        return super.beforeVisibilityChange(...arguments);
    },

    /**
     * Prevent silent urgent save on window unload.
     */
    async beforeUnload(ev) {
        if (this.props.resModel && this.props.resModel.startsWith("pm.")) {
            if (this.model.root.dirty) {
                ev.preventDefault();
                ev.returnValue = "You have unsaved changes in Project Management.";
            }
            return;
        }
        return super.beforeUnload(...arguments);
    },
});
