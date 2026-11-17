/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

patch(FormController.prototype, {
    /**
     * When user clicks "New" while already on an unsaved new record:
     * Discard the previous new record instead of auto-saving it into the database.
     */
    async create() {
        if (this.model.root.isNew) {
            await this.model.root.discard();
            await this.model.load({ resId: false });
            return;
        }
        return super.create(...arguments);
    },

    /**
     * When navigating away (breadcrumbs, menu items, view changes):
     * If this is an uncommitted new record, discard it instead of auto-saving.
     */
    async beforeLeave({ forceLeave } = {}) {
        if (this.model.root.dirty && !forceLeave) {
            if (this.model.root.isNew) {
                await this.model.root.discard();
                return true;
            }
            return super.beforeLeave(...arguments);
        }
        return super.beforeLeave(...arguments);
    },

    /**
     * Do not auto-save uncommitted new records when browser tab visibility changes.
     */
    beforeVisibilityChange() {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeVisibilityChange(...arguments);
    },

    /**
     * Do not auto-save uncommitted new records on window unload / refresh.
     */
    async beforeUnload(ev) {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeUnload(...arguments);
    },

    /**
     * When paging through records while on an unsaved new record:
     * Discard the unsaved new record before loading the target record.
     */
    async onPagerUpdate({ offset, resIds }) {
        if (this.model.root.isNew && (await this.model.root.isDirty())) {
            await this.model.root.discard();
            await this.model.load({ resId: resIds[offset] });
            return;
        }
        return super.onPagerUpdate(...arguments);
    },
});
