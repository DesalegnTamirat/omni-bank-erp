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
            monthlyHoursFormatted: "00h 00m",
            dailyBreakdown: [],
            checkInTimeStr: "",
            checkInStatus: "",
            checkInRaw: false,
            hoursCompletedToday: 0.0,   // float hours of closed sessions today
            hoursCompletedWeek: 0.0,    // float hours of closed sessions this week
            hoursCompletedMonth: 0.0,   // float hours of closed sessions this month
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
                enable_checkin_gate: false,
                dead_time: 0.25,
                checkin_buffer: 0.5,
                post_shift_grace_hours: 3.0,
                lunch_duration: 1.0,
                lunch_grace_time: 0.25,
                lateness_hours_violation_threshold: 4.0,
                lateness_eval_window_months: 3,
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
                        const completedSecsToday = Math.round((this.state.hoursCompletedToday || 0) * 3600);
                        const totalSecsToday = completedSecsToday + diffSecs;
                        const tHrs = Math.floor(totalSecsToday / 3600);
                        const tMins = Math.floor((totalSecsToday % 3600) / 60);
                        const tSecs = totalSecsToday % 60;
                        this.state.todayTotalFormatted =
                            String(tHrs).padStart(2, '0') + ":" +
                            String(tMins).padStart(2, '0') + ":" +
                            String(tSecs).padStart(2, '0');

                        // WEEKLY TOTAL = completed sessions this week + live elapsed
                        const completedSecsWeek = Math.round((this.state.hoursCompletedWeek || 0) * 3600);
                        const totalSecsWeek = completedSecsWeek + diffSecs;
                        const wHrs = Math.floor(totalSecsWeek / 3600);
                        const wMins = Math.floor((totalSecsWeek % 3600) / 60);
                        this.state.weeklyHoursFormatted =
                            String(wHrs).padStart(2, '0') + "h " +
                            String(wMins).padStart(2, '0') + "m";

                        // MONTHLY TOTAL = completed sessions this month + live elapsed
                        const completedSecsMonth = Math.round((this.state.hoursCompletedMonth || 0) * 3600);
                        const totalSecsMonth = completedSecsMonth + diffSecs;
                        const mHrs = Math.floor(totalSecsMonth / 3600);
                        const mMins = Math.floor((totalSecsMonth % 3600) / 60);
                        this.state.monthlyHoursFormatted =
                            String(mHrs).padStart(2, '0') + "h " +
                            String(mMins).padStart(2, '0') + "m";
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
        this.state.monthlyHoursFormatted = data.monthly_hours_formatted || "00h 00m";
        this.state.dailyBreakdown = data.daily_breakdown || [];
        this.state.checkInTimeStr = data.check_in_time_str || "";
        this.state.checkInStatus = data.check_in_status || "";
        this.state.checkInRaw = data.check_in_raw || false;
        this.state.hoursCompletedToday = data.hours_today_completed || 0.0;
        this.state.hoursCompletedWeek = data.hours_weekly_completed || 0.0;
        this.state.hoursCompletedMonth = data.hours_monthly_completed || 0.0;
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
            if (res && res.settings) {
                this.state.isAdmin = res.is_admin || false;
                const s = res.settings;
                Object.assign(this.state.settings, s);
                this.state.settings.morning_time_str = this.floatToTimeStr(s.morning_time);
                this.state.settings.exit_time_str = this.floatToTimeStr(s.exit_time);
                this.state.settings.saturday_exit_time_str = this.floatToTimeStr(s.saturday_exit_time);
                this.state.settings.lunch_out_time_str = this.floatToTimeStr(s.lunch_out_time);
                this.state.settings.dead_time_str = this.floatToTimeStr(s.dead_time);
                this.state.settings.checkin_buffer_str = this.floatToTimeStr(s.checkin_buffer);
                this.state.settings.post_shift_grace_hours_str = this.floatToTimeStr(s.post_shift_grace_hours);
                this.state.settings.lunch_duration_str = this.floatToTimeStr(s.lunch_duration);
                this.state.settings.lunch_grace_time_str = this.floatToTimeStr(s.lunch_grace_time);
                this.state.settings.lateness_hours_violation_threshold_str = this.floatToTimeStr(s.lateness_hours_violation_threshold);
            }
        } catch (e) {
            // Silently ignore
        }
    }

    toggleSettings() {
        this.state.showSettings = !this.state.showSettings;
    }

    async saveSettings() {
        if (this.state.settingsSaving) return;
        this.state.settingsSaving = true;
        try {
            const s = this.state.settings;
            const payload = {
                ...s,
                morning_time: this.timeStrToFloat(s.morning_time_str !== undefined ? s.morning_time_str : s.morning_time),
                exit_time: this.timeStrToFloat(s.exit_time_str !== undefined ? s.exit_time_str : s.exit_time),
                saturday_exit_time: this.timeStrToFloat(s.saturday_exit_time_str !== undefined ? s.saturday_exit_time_str : s.saturday_exit_time),
                lunch_out_time: this.timeStrToFloat(s.lunch_out_time_str !== undefined ? s.lunch_out_time_str : s.lunch_out_time),
                dead_time: this.timeStrToFloat(s.dead_time_str !== undefined ? s.dead_time_str : s.dead_time),
                checkin_buffer: this.timeStrToFloat(s.checkin_buffer_str !== undefined ? s.checkin_buffer_str : s.checkin_buffer),
                post_shift_grace_hours: this.timeStrToFloat(s.post_shift_grace_hours_str !== undefined ? s.post_shift_grace_hours_str : s.post_shift_grace_hours),
                lunch_duration: this.timeStrToFloat(s.lunch_duration_str !== undefined ? s.lunch_duration_str : s.lunch_duration),
                lunch_grace_time: this.timeStrToFloat(s.lunch_grace_time_str !== undefined ? s.lunch_grace_time_str : s.lunch_grace_time),
                lateness_hours_violation_threshold: this.timeStrToFloat(s.lateness_hours_violation_threshold_str !== undefined ? s.lateness_hours_violation_threshold_str : s.lateness_hours_violation_threshold),
            };

            const res = await rpc("/custom_hr_attendance/save_settings", {
                settings: payload,
            });
            if (res && res.status === 'success') {
                this.notification.add(
                    _t("Attendance settings saved successfully."),
                    { title: _t("Settings Saved"), type: "success" }
                );
                Object.assign(this.state.settings, payload);
                this.state.showSettings = false;
            } else {
                throw new Error(res ? res.error : "Failed to save settings");
            }
        } catch (e) {
            this.notification.add(
                _t("Failed to save settings. Check your permissions."),
                { title: _t("Error"), type: "danger" }
            );
        } finally {
            this.state.settingsSaving = false;
        }
    }

    floatToTimeStr(val) {
        if (val === undefined || val === null || isNaN(val)) return "00:00";
        const h = Math.floor(val);
        const m = Math.round((val - h) * 60);
        const hStr = String(h % 24).padStart(2, '0');
        const mStr = String(m % 60).padStart(2, '0');
        return `${hStr}:${mStr}`;
    }

    timeStrToFloat(timeStr) {
        if (timeStr === undefined || timeStr === null) return 0.0;
        const str = String(timeStr).trim();
        if (!str) return 0.0;
        if (str.includes(':')) {
            const parts = str.split(':');
            const hours = parseInt(parts[0], 10) || 0;
            const minutes = parseInt(parts[1], 10) || 0;
            return parseFloat((hours + minutes / 60.0).toFixed(4));
        }
        const val = parseFloat(str);
        if (isNaN(val)) return 0.0;
        if (val > 12 && Number.isInteger(val)) {
            return parseFloat((val / 60.0).toFixed(4));
        }
        return val;
    }

    onInputMorningTime(ev) {
        this.state.settings.morning_time_str = ev.target.value;
    }
    onInputExitTime(ev) {
        this.state.settings.exit_time_str = ev.target.value;
    }
    onInputSaturdayExitTime(ev) {
        this.state.settings.saturday_exit_time_str = ev.target.value;
    }
    onInputLunchOutTime(ev) {
        this.state.settings.lunch_out_time_str = ev.target.value;
    }

    onInputDeadTime(ev) {
        this.state.settings.dead_time_str = ev.target.value;
    }
    onInputCheckinBuffer(ev) {
        this.state.settings.checkin_buffer_str = ev.target.value;
    }
    onInputPostShiftGraceHours(ev) {
        this.state.settings.post_shift_grace_hours_str = ev.target.value;
    }
    onInputLunchDuration(ev) {
        this.state.settings.lunch_duration_str = ev.target.value;
    }
    onInputLunchGraceTime(ev) {
        this.state.settings.lunch_grace_time_str = ev.target.value;
    }
    onInputLatenessHoursThreshold(ev) {
        this.state.settings.lateness_hours_violation_threshold_str = ev.target.value;
    }
    onInputLatenessEvalWindowMonths(ev) {
        this.state.settings.lateness_eval_window_months = parseInt(ev.target.value, 10) || 0;
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
    onToggleSaturdayDistrict(ev) {
        this.state.settings.saturday_halfday_district = ev.target.checked;
    }
    onToggleLunchBreak(ev) {
        this.state.settings.enable_lunch_break = ev.target.checked;
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
        this.action.doAction("custom_hr_attendance.action_my_shift_schedule_resolved");
    }
}

registry.category("actions").add("custom_hr_attendance.my_attendance_action", MyAttendance);
