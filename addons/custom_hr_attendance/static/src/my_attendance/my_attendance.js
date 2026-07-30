/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { ConnectionLostError } from "@web/core/network/rpc";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { isIosApp } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/l10n/translation";

const { DateTime } = luxon;

/**
 * Full-page personal "Check In / Check Out" screen.
 *
 * Odoo 19's hr_attendance only exposes this as a small systray dropdown
 * (see hr_attendance.attendance_menu). Bunna Bank's legacy layout instead
 * had it as its own top-menu tab showing a big centered greet-card with
 * the employee's photo, name, and a single Check In / Check Out button.
 * This client action recreates that screen using the same server logic
 * the systray widget relies on (via the bunna_hr_attendance controller
 * endpoints), without modifying core hr_attendance.
 */
export class MyAttendance extends Component {
    static template = "custom_hr_attendance.MyAttendance";
    static props = ["*"];

    setup() {
        this.notification = useService("notification");
        this.formatFloatTime = registry.category("formatters").get("float_time");

        this.state = useState({
            loading: true,
            hasEmployee: false,
            checkedIn: false,
            inProgress: false,
            employeeName: "",
            employeeAvatar: "",
            hoursToday: "00:00",
            lastCheckIn: "",
            lastCheckOut: "",
        });

        onWillStart(() => this.loadAttendanceData());
    }

    async loadAttendanceData() {
        const data = await rpc("/custom_hr_attendance/my_attendance_data");
        this._fill(data);
    }

    _fill(data) {
        this.state.loading = false;
        if (!data || !data.id) {
            this.state.hasEmployee = false;
            return;
        }
        this.state.hasEmployee = true;
        this.state.checkedIn = data.attendance_state === "checked_in";
        this.state.employeeName = data.employee_name;
        this.state.employeeAvatar = data.employee_avatar;
        this.state.hoursToday = this.formatFloatTime(data.hours_today || 0);
        const attendance = data.attendance || {};
        this.state.lastCheckIn = attendance.check_in
            ? deserializeDateTime(attendance.check_in).toLocaleString(DateTime.TIME_SIMPLE)
            : "";
        this.state.lastCheckOut = attendance.check_out
            ? deserializeDateTime(attendance.check_out).toLocaleString(DateTime.TIME_SIMPLE)
            : "";
    }

    async _toggle(latitude = false, longitude = false) {
        try {
            const data = await rpc("/custom_hr_attendance/my_attendance_toggle", {
                latitude,
                longitude,
            });
            this._fill(data);
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.notification.add(
                    _t("Connection lost. Check in/out could not be recorded."),
                    { title: _t("Attendance Error"), type: "danger" }
                );
            } else {
                throw error;
            }
        } finally {
            this.state.inProgress = false;
        }
    }

    async onClickToggle() {
        if (this.state.inProgress) {
            return;
        }
        this.state.inProgress = true;
        await this._toggle();
    }
}

registry.category("actions").add("custom_hr_attendance.my_attendance_action", MyAttendance);
