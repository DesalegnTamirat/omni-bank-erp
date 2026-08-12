/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { ConnectionLostError } from "@web/core/network/rpc";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";

const { DateTime } = luxon;

/**
 * Smart Executive Check In / Check Out Attendance Dashboard.
 *
 * Lightweight, high-performance interface displaying live digital clock,
 * live client-side worked duration counter (starting from 00:00:00),
 * weekly total worked hours, and daily attendance breakdown.
 */
export class MyAttendance extends Component {
    static template = "custom_hr_attendance.MyAttendance";
    static props = ["*"];

    setup() {
        this.notification = useService("notification");
        this.action = useService("action");
        this.formatFloatTime = registry.category("formatters").get("float_time");

        this.state = useState({
            loading: true,
            hasEmployee: false,
            checkedIn: false,
            inProgress: false,
            employeeName: "",
            employeeAvatar: "",
            jobTitle: "",
            departmentName: "",
            hoursToday: "00:00",
            weeklyHoursFormatted: "00h 00m",
            dailyBreakdown: [],
            checkInTimeStr: "",
            checkInStatus: "",
            checkInRaw: false,
            hoursCompletedToday: 0.0,   // float hours of closed sessions today
            todayTotalFormatted: "00:00:00", // completed + live current session
            shiftInfo: null,
            // Live clock & live timer
            currentClockTime: "",
            currentClockDate: "",
            liveWorkedTimer: "00:00:00",
            // Settings panel
            showSettings: false,
            isAdmin: false,
            settingsSaving: false,
            settings: {
                enable_checkin_restriction: true,
                enable_checkout_restriction: true,
                enable_saturday_halfday: true,
                enable_lunch_break: false,
                enable_auto_absence: true,
                enable_checkin_gate: false,
                morning_time: 8.0,
                exit_time: 17.0,
                checkin_buffer: 0.5,
                force_checkout_hours: 14.0,
                saturday_exit_time: 14.75,
                lateness_violation_threshold: 3,
                force_checkout_violation_threshold: 2,
            },
        });

        this.timerInterval = null;

        onWillStart(async () => {
            await this.loadAttendanceData();
            await this.loadSettings();
            this.startLiveClock();
        });

        onWillUnmount(() => {
            if (this.timerInterval) {
                clearInterval(this.timerInterval);
            }
        });
    }

    startLiveClock() {
        this.updateClock();
        this.timerInterval = setInterval(() => this.updateClock(), 1000);
    }

    updateClock() {
        const now = DateTime.now();
        this.state.currentClockTime = now.toFormat("hh:mm:ss a");
        this.state.currentClockDate = now.toFormat("cccc, LLL dd, yyyy");

        if (this.state.checkedIn && this.state.checkInRaw) {
            try {
                // check_in_raw is always "YYYY-MM-DDTHH:MM:SSZ" (UTC) — Luxon converts to local
                const checkInDt = DateTime.fromISO(this.state.checkInRaw);

                if (checkInDt && checkInDt.isValid) {
                    const diffSecs = Math.max(0, Math.floor(now.diff(checkInDt, 'seconds').seconds));
                    if (!isNaN(diffSecs)) {
                        const hrs = Math.floor(diffSecs / 3600);
                        const mins = Math.floor((diffSecs % 3600) / 60);
                        const secs = diffSecs % 60;
                        // ACTIVE WORKED TIME = only current session, starts from 00:00:00
                        this.state.liveWorkedTimer =
                            String(hrs).padStart(2, '0') + ":" +
                            String(mins).padStart(2, '0') + ":" +
                            String(secs).padStart(2, '0');

                        // TODAY'S TOTAL = completed sessions + live elapsed
                        const completedSecs = Math.round((this.state.hoursCompletedToday || 0) * 3600);
                        const totalSecs = completedSecs + diffSecs;
                        const tHrs = Math.floor(totalSecs / 3600);
                        const tMins = Math.floor((totalSecs % 3600) / 60);
                        const tSecs = totalSecs % 60;
                        this.state.todayTotalFormatted =
                            String(tHrs).padStart(2, '0') + ":" +
                            String(tMins).padStart(2, '0') + ":" +
                            String(tSecs).padStart(2, '0');
                    } else {
                        this.state.liveWorkedTimer = "00:00:00";
                        this.state.todayTotalFormatted = "00:00:00";
                    }
                } else {
                    this.state.liveWorkedTimer = "00:00:00";
                    this.state.todayTotalFormatted = "00:00:00";
                }
            } catch (e) {
                this.state.liveWorkedTimer = "00:00:00";
                this.state.todayTotalFormatted = "00:00:00";
            }
        } else {
            this.state.liveWorkedTimer = "00:00:00";
            this.state.todayTotalFormatted = this.state.hoursToday;
        }
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
        // Dynamically sync Web Client session state for immediate ERP Gate enforcement
        session.attendance_checked_in = this.state.checkedIn;
        this.state.employeeName = data.employee_name || "";
        this.state.employeeAvatar = data.employee_avatar || "";
        this.state.jobTitle = data.job_title || "Employee";
        this.state.departmentName = data.department_name || "";
        this.state.hoursToday = this.formatFloatTime(data.hours_today || 0);
        this.state.weeklyHoursFormatted = data.weekly_hours_formatted || "00h 00m";
        this.state.dailyBreakdown = data.daily_breakdown || [];
        this.state.checkInTimeStr = data.check_in_time_str || "";
        this.state.checkInStatus = data.check_in_status || "";
        this.state.checkInRaw = data.check_in_raw || false;
        this.state.hoursCompletedToday = data.hours_today_completed || 0.0;
        this.state.shiftInfo = data.shift_info || null;

        this.updateClock();
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

    async loadSettings() {
        try {
            const res = await rpc("/custom_hr_attendance/get_settings");
            if (res) {
                this.state.isAdmin = res.is_admin || false;
                Object.assign(this.state.settings, res.settings || {});
            }
        } catch (e) {
            // Not an admin or endpoint unavailable, silently ignore
        }
    }

    toggleSettings() {
        this.state.showSettings = !this.state.showSettings;
    }

    async saveSettings() {
        if (this.state.settingsSaving) return;
        this.state.settingsSaving = true;
        try {
            await rpc("/custom_hr_attendance/save_settings", {
                settings: this.state.settings,
            });
            this.notification.add(
                _t("Attendance settings saved successfully."),
                { title: _t("Settings Saved"), type: "success" }
            );
            this.state.showSettings = false;
        } catch (e) {
            this.notification.add(
                _t("Failed to save settings. Check your permissions."),
                { title: _t("Error"), type: "danger" }
            );
        } finally {
            this.state.settingsSaving = false;
        }
    }

    onInputMorningTime(ev) {
        this.state.settings.morning_time = parseFloat(ev.target.value) || 0;
    }
    onInputExitTime(ev) {
        this.state.settings.exit_time = parseFloat(ev.target.value) || 0;
    }
    onInputCheckinBuffer(ev) {
        this.state.settings.checkin_buffer = parseFloat(ev.target.value) || 0;
    }
    onInputForceCheckoutHours(ev) {
        this.state.settings.force_checkout_hours = parseFloat(ev.target.value) || 0;
    }
    onInputSaturdayExitTime(ev) {
        this.state.settings.saturday_exit_time = parseFloat(ev.target.value) || 0;
    }
    onInputLatenessThreshold(ev) {
        this.state.settings.lateness_violation_threshold = parseInt(ev.target.value, 10) || 0;
    }
    onInputForceCheckoutThreshold(ev) {
        this.state.settings.force_checkout_violation_threshold = parseInt(ev.target.value, 10) || 0;
    }
    onToggleCheckinRestrict(ev) {
        this.state.settings.enable_checkin_restriction = ev.target.checked;
    }
    onToggleCheckoutRestrict(ev) {
        this.state.settings.enable_checkout_restriction = ev.target.checked;
    }
    onToggleSaturdayHalfday(ev) {
        this.state.settings.enable_saturday_halfday = ev.target.checked;
    }
    onToggleLunchBreak(ev) {
        this.state.settings.enable_lunch_break = ev.target.checked;
    }
    onToggleAutoAbsence(ev) {
        this.state.settings.enable_auto_absence = ev.target.checked;
    }
    onToggleCheckinGate(ev) {
        this.state.settings.enable_checkin_gate = ev.target.checked;
    }

    async onClickToggle() {
        if (this.state.inProgress) {
            return;
        }
        this.state.inProgress = true;
        await this._toggle();
    }

    onOpenMySchedule() {
        this.action.doAction("custom_hr_attendance.action_my_roster_exception");
    }
}

registry.category("actions").add("custom_hr_attendance.my_attendance_action", MyAttendance);
