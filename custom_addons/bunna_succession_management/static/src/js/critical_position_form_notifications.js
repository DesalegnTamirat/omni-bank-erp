/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this.notificationService = useService("notification");
    },

    async save(params) {
        const record = this.model.root;
        const isCriticalPosition = Boolean(record && record.resModel === "succession.critical.position");
        const wasNew = Boolean(isCriticalPosition && record.isNew);

        const saved = await super.save(...arguments);

        if (saved && isCriticalPosition && wasNew) {
            const posName = (this.model.root.data.job_id && this.model.root.data.job_id[1]) ||
                            this.model.root.data.display_name ||
                            _t("Critical Position");
            this.notificationService.add(
                _t("Critical Position '%s' has been created successfully.", posName),
                {
                    title: _t("Created Successfully"),
                    type: "success",
                    sticky: false,
                }
            );
        }
        return saved;
    },
});
