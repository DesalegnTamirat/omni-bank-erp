/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { actionService } from "@web/webclient/actions/action_service";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";

patch(actionService, {
    start(env) {
        const result = super.start(...arguments);
        const originalDoAction = result.doAction;

        result.doAction = async function (actionRequest, options) {
            // Enforce ERP Access Gate for regular employees when enabled
            if (session.enable_checkin_gate && !session.is_system_admin) {
                const isCheckedIn = Boolean(session.attendance_checked_in);
                if (!isCheckedIn) {
                    let actionTag = "";
                    if (typeof actionRequest === "string") {
                        actionTag = actionRequest;
                    } else if (actionRequest && typeof actionRequest === "object") {
                        actionTag = actionRequest.tag || actionRequest.xml_id || actionRequest.res_model || actionRequest.type || "";
                    }

                    // Allowed exempt actions (Check In / Check Out dashboard & Discuss)
                    const isExempt =
                        actionTag === "custom_hr_attendance.my_attendance_action" ||
                        actionTag === "custom_hr_attendance.action_my_attendance" ||
                        actionTag === "action_my_attendance" ||
                        actionTag === "mail.action_discuss" ||
                        actionTag === "mail";

                    if (!isExempt) {
                        // Display a clear, friendly notification toast
                        const notification = env.services.notification;
                        if (notification) {
                            notification.add(
                                _t("ERP Access Gate Active: You must Check In on the Attendance Dashboard before accessing system modules."),
                                {
                                    title: _t("Check-In Required"),
                                    type: "warning",
                                    sticky: false,
                                }
                            );
                        }
                        // Immediately redirect to the Check In / Check Out Attendance Dashboard
                        return originalDoAction.call(this, "custom_hr_attendance.action_my_attendance", { clearBreadcrumbs: true });
                    }
                }
            }
            return originalDoAction.apply(this, arguments);
        };

        return result;
    },
});
