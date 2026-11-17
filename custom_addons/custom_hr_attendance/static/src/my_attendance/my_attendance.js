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
        this.menu = useService("menu");
        this.formatFloatTime = registry.category("formatters").get("float_time");

        this.state = useState({
            loading: true,
            hasEmployee: false,
            isWorkdayCompleted: false,
            modalNotice: {
                show: false,
                type: "error",
                statusTag: "",
                title: "",
                subtitle: "",
                message: "",
                icon: "fa-ban",
                badgeStyle: "width: 52px; height: 52px; background: #fee2e2; color: #dc2626;",
                buttonText: "Understood",
                footerNotice: "",
                autoDismissSeconds: 6,
                progressPercent: 100,
            },
            checkedIn: false,
            inProgress: false,
            employeeName: "",
            employeeAvatar: "",
            jobTitle: "",
            departmentName: "",
            hoursToday: "00:00",
            weeklyHoursFormatted: "00h 00m",
            weeklyTargetHoursFormatted: "40h 00m",
            monthlyHoursFormatted: "00h 00m",
            dailyBreakdown: [],
            currentWeekOffset: 0,
            weekRangeLabel: "",
            isCurrentWeek: true,
            isLoadingWeek: false,
            todaySessions: [],
            checkInTimeStr: "",
            checkInStatus: "",
            checkInRaw: false,
            shiftEndRaw: false,
            isShiftEnded: false,
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
                    let effectiveNow = now;
                    // Cap live counter at scheduled shift end time
                    if (this.state.shiftEndRaw) {
                        const shiftEndDt = DateTime.fromISO(this.state.shiftEndRaw);
                        if (shiftEndDt && shiftEndDt.isValid && now > shiftEndDt) {
                            effectiveNow = shiftEndDt;
                            this.state.isShiftEnded = true;
                        } else {
                            this.state.isShiftEnded = false;
                        }
                    } else {
                        this.state.isShiftEnded = false;
                    }

                    const diffSecs = Math.max(0, Math.floor(effectiveNow.diff(checkInDt, 'seconds').seconds));
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
                        this.state.hoursToday =
                            String(tHrs).padStart(2, '0') + "h " +
                            String(tMins).padStart(2, '0') + "m";

                        // Synchronize today's row in weekly breakdown live
                        if (this.state.dailyBreakdown && this.state.dailyBreakdown.length && this.state.isCurrentWeek) {
                            const todayRow = this.state.dailyBreakdown.find(d => d.is_today);
                            if (todayRow) {
                                todayRow.hours_formatted = this.state.hoursToday;
                                todayRow.hours = totalSecsToday / 3600.0;
                                const expHrs = todayRow.expected_hours || 8.0;
                                todayRow.percentage = Math.min(100, Math.round((todayRow.hours / expHrs) * 100));
                                todayRow.is_completed = (todayRow.hours >= expHrs && expHrs > 0);
                            }
                        }

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
            this.state.isShiftEnded = false;
            const completedSecsToday = Math.round((this.state.hoursCompletedToday || 0) * 3600);
            const tHrs = Math.floor(completedSecsToday / 3600);
            const tMins = Math.floor((completedSecsToday % 3600) / 60);
            this.state.hoursToday =
                String(tHrs).padStart(2, '0') + "h " +
                String(tMins).padStart(2, '0') + "m";
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
        this.state.isWorkdayCompleted = !!data.is_workday_completed;
        // Dynamically sync Web Client session state for immediate ERP Gate enforcement
        session.attendance_checked_in = this.state.checkedIn;
        this.state.employeeName = data.employee_name || "";
        this.state.employeeAvatar = data.employee_avatar || "";
        this.state.jobTitle = data.job_title || "Employee";
        this.state.departmentName = data.department_name || "";
        const hToday = data.hours_today || 0;
        const hHrs = Math.floor(hToday);
        const hMins = Math.floor((hToday - hHrs) * 60);
        this.state.hoursToday = String(hHrs).padStart(2, '0') + "h " + String(hMins).padStart(2, '0') + "m";

        this.state.weeklyHoursFormatted = data.weekly_hours_formatted || "00h 00m";
        this.state.weeklyTargetHoursFormatted = data.weekly_target_hours_formatted || "40h 00m";
        this.state.weekRangeLabel = data.week_range_label || "";
        this.state.isCurrentWeek = data.is_current_week !== undefined ? data.is_current_week : true;
        this.state.currentWeekOffset = 0;
        this.state.monthlyHoursFormatted = data.monthly_hours_formatted || "00h 00m";
        this.state.dailyBreakdown = data.daily_breakdown || [];
        this.state.todaySessions = data.today_sessions || [];
        this.state.checkInTimeStr = data.check_in_time_str || "";
        this.state.checkInStatus = data.check_in_status || "";
        this.state.checkInRaw = data.check_in_raw || false;
        this.state.shiftEndRaw = data.shift_end_raw || false;
        this.state.hoursCompletedToday = data.hours_today_completed || 0.0;
        this.state.hoursCompletedWeek = data.hours_weekly_completed || 0.0;
        this.state.hoursCompletedMonth = data.hours_monthly_completed || 0.0;
        this.state.shiftInfo = data.shift_info || null;

        this.updateClock();
    }

    async onPrevWeek() {
        this.state.currentWeekOffset -= 1;
        await this._fetchWeeklyBreakdown();
    }

    async onNextWeek() {
        if (this.state.currentWeekOffset < 0) {
            this.state.currentWeekOffset += 1;
            await this._fetchWeeklyBreakdown();
        }
    }

    async onCurrentWeek() {
        if (this.state.currentWeekOffset !== 0) {
            this.state.currentWeekOffset = 0;
            await this._fetchWeeklyBreakdown();
        }
    }

    async _fetchWeeklyBreakdown() {
        this.state.isLoadingWeek = true;
        try {
            const res = await rpc("/custom_hr_attendance/get_weekly_breakdown", {
                week_offset: this.state.currentWeekOffset
            });
            if (res && res.daily_breakdown) {
                this.state.dailyBreakdown = res.daily_breakdown;
                this.state.weeklyHoursFormatted = res.weekly_hours_formatted || "00h 00m";
                this.state.weeklyTargetHoursFormatted = res.weekly_target_hours_formatted || "40h 00m";
                this.state.weekRangeLabel = res.week_range_label || "";
                this.state.isCurrentWeek = !!res.is_current_week;
                if (this.state.isCurrentWeek) {
                    this.state.hoursCompletedWeek = res.hours_weekly_completed || 0.0;
                }
            }
        } catch (e) {
            console.error("Failed to load weekly breakdown:", e);
        } finally {
            this.state.isLoadingWeek = false;
            this.updateClock();
        }
    }

    async _toggle(latitude = false, longitude = false) {
        try {
            const data = await rpc("/custom_hr_attendance/my_attendance_toggle", {
                latitude,
                longitude,
            });
            this._fill(data);
            if (this.menu) {
                this.menu.reload();
            }
            if (data && data.attendance_state) {
                session.attendance_checked_in = (data.attendance_state === 'checked_in');
                if (session.attendance_checked_in) {
                    document.body?.classList.remove("o_gate_active");
                    document.body?.classList.remove("o_gate_regular_user");
                }
            }
            if (data && data.notification) {
                this.showConfirmationModal(data.notification);
            }
        } catch (error) {
            const isCheckout = this.state.checkedIn;
            const actionTitle = isCheckout ? _t("Checkout Restricted") : _t("Check-In Restricted");
            const actionSubtitle = isCheckout ? _t("Checkout attempt was not recorded") : _t("Check-in attempt was not recorded");

            if (error instanceof ConnectionLostError) {
                this.showNoticeModal(
                    _t("Connection Lost"),
                    actionSubtitle,
                    _t("Could not reach attendance server. Please check your network and retry."),
                    { type: "error", icon: "fa-wifi", duration: 6 }
                );
            } else if (error && error.data && error.data.message) {
                const fullMsg = error.data.message;
                const parts = fullMsg.split("\n\n");
                const title = parts.length > 1 ? parts[0] : actionTitle;
                const body = parts.length > 1 ? parts.slice(1).join("\n\n") : fullMsg;

                let icon = "fa-ban";
                const lowerMsg = fullMsg.toLowerCase();
                if (lowerMsg.includes("lunch")) {
                    icon = "fa-cutlery";
                } else if (lowerMsg.includes("closed at") || lowerMsg.includes("cutoff") || lowerMsg.includes("expired") || lowerMsg.includes("not open yet") || lowerMsg.includes("starts at")) {
                    icon = "fa-clock-o";
                } else if (lowerMsg.includes("day off")) {
                    icon = "fa-coffee";
                } else if (lowerMsg.includes("holiday")) {
                    icon = "fa-sun-o";
                } else if (lowerMsg.includes("early departure") || lowerMsg.includes("leaving early") || lowerMsg.includes("still in progress")) {
                    icon = "fa-ban";
                } else if (lowerMsg.includes("suspension") || lowerMsg.includes("inactive")) {
                    icon = "fa-user-times";
                }

                this.showNoticeModal(
                    title,
                    actionSubtitle,
                    body,
                    { type: "error", icon: icon, duration: 6 }
                );
            } else if (error && error.message) {
                this.showNoticeModal(
                    actionTitle,
                    actionSubtitle,
                    error.message,
                    { type: "error", icon: "fa-ban", duration: 6 }
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
                this.state.settings.checkin_grace_period_str = this.floatToTimeStr(s.checkin_grace_period);
                this.state.settings.dead_time_str = this.floatToTimeStr(s.dead_time);
                this.state.settings.checkin_buffer_str = this.floatToTimeStr(s.checkin_buffer);
                this.state.settings.lunch_duration_str = this.floatToTimeStr(s.lunch_duration);
                this.state.settings.lateness_hours_violation_threshold_str = this.floatToTimeStr(s.lateness_hours_violation_threshold);
            }
        } catch (e) {
            // Silently ignore
        }
    }

    toggleSettings() {
        this.state.showSettings = !this.state.showSettings;
    }

    closeNoticeModal() {
        this.clearAutoDismiss();
        this.state.modalNotice.show = false;
    }

    clearAutoDismiss() {
        if (this._autoDismissInterval) {
            clearInterval(this._autoDismissInterval);
            this._autoDismissInterval = null;
        }
        this._autoDismissPaused = false;
    }

    pauseAutoDismiss() {
        this._autoDismissPaused = true;
    }

    resumeAutoDismiss() {
        this._autoDismissPaused = false;
    }

    startAutoDismiss(durationSeconds = 6) {
        this.clearAutoDismiss();
        const totalMs = durationSeconds * 1000;
        let remainingMs = totalMs;
        this.state.modalNotice.autoDismissSeconds = durationSeconds;
        this.state.modalNotice.progressPercent = 100;
        this._autoDismissPaused = false;

        const intervalMs = 50;
        this._autoDismissInterval = setInterval(() => {
            if (this._autoDismissPaused) {
                return;
            }
            remainingMs -= intervalMs;
            if (remainingMs <= 0) {
                this.closeNoticeModal();
            } else {
                this.state.modalNotice.autoDismissSeconds = Math.ceil(remainingMs / 1000);
                this.state.modalNotice.progressPercent = Math.max(0, (remainingMs / totalMs) * 100);
            }
        }, intervalMs);
    }

    showNoticeModal(title, subtitle, message, options = {}) {
        const isError = options.type !== "info" && options.type !== "success";
        this.state.modalNotice.show = true;
        this.state.modalNotice.type = isError ? "error" : (options.type || "info");
        this.state.modalNotice.title = title || (isError ? _t("Attendance Restricted") : _t("Notice"));
        this.state.modalNotice.subtitle = subtitle || "";
        this.state.modalNotice.message = message || "";
        this.state.modalNotice.statusTag = "";
        this.state.modalNotice.footerNotice = "";

        if (isError) {
            this.state.modalNotice.icon = options.icon || "fa-ban";
            this.state.modalNotice.badgeStyle = "width: 52px; height: 52px; background: #fee2e2; color: #dc2626;";
            this.state.modalNotice.buttonText = _t("Understood");
            this.startAutoDismiss(options.duration || 6);
        } else {
            this.clearAutoDismiss();
            this.state.modalNotice.icon = options.icon || "fa-info-circle";
            this.state.modalNotice.badgeStyle = "width: 52px; height: 52px; background: #eff6ff; color: #2563eb;";
            this.state.modalNotice.buttonText = _t("Understood");
            this.state.modalNotice.autoDismissSeconds = 0;
            this.state.modalNotice.progressPercent = 100;
        }
    }

    showConfirmationModal(notif) {
        this.clearAutoDismiss();
        this.state.modalNotice.show = true;
        this.state.modalNotice.type = "success";
        this.state.modalNotice.statusTag = "";
        this.state.modalNotice.footerNotice = "";
        this.state.modalNotice.title = notif.title || _t("Attendance Recorded");
        this.state.modalNotice.subtitle = notif.subtitle || "";
        this.state.modalNotice.message = notif.message || "";
        this.state.modalNotice.icon = notif.icon || "fa-check";
        this.state.modalNotice.badgeStyle = notif.badge_style || "width: 52px; height: 52px; background: #dcfce7; color: #16a34a;";
        this.state.modalNotice.buttonText = notif.button_text || _t("Continue");
        this.startAutoDismiss(10);
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
                checkin_grace_period: this.timeStrToFloat(s.checkin_grace_period_str !== undefined ? s.checkin_grace_period_str : s.checkin_grace_period),
                dead_time: this.timeStrToFloat(s.dead_time_str !== undefined ? s.dead_time_str : s.dead_time),
                checkin_buffer: this.timeStrToFloat(s.checkin_buffer_str !== undefined ? s.checkin_buffer_str : s.checkin_buffer),
                lunch_duration: this.timeStrToFloat(s.lunch_duration_str !== undefined ? s.lunch_duration_str : s.lunch_duration),
                lateness_hours_violation_threshold: this.timeStrToFloat(s.lateness_hours_violation_threshold_str !== undefined ? s.lateness_hours_violation_threshold_str : s.lateness_hours_violation_threshold),
            };

            // Client-side quick check
            if (payload.morning_time >= payload.exit_time) {
                this.notification.add(
                    _t("Morning Start Time must be earlier than Shift Exit Time."),
                    { title: _t("Validation Error"), type: "danger" }
                );
                return;
            }
            if (payload.enable_lunch_break) {
                if (payload.lunch_out_time <= payload.morning_time) {
                    this.notification.add(
                        _t("Lunch Start Time must be strictly after Morning Start Time."),
                        { title: _t("Validation Error"), type: "danger" }
                    );
                    return;
                }
                if (payload.lunch_out_time + payload.lunch_duration >= payload.exit_time) {
                    this.notification.add(
                        _t("Lunch break must end before the Shift Exit Time."),
                        { title: _t("Validation Error"), type: "danger" }
                    );
                    return;
                }
            }

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
                const errMsg = (res && res.error) ? res.error : _t("Failed to save settings.");
                this.notification.add(errMsg, { title: _t("Invalid Configuration"), type: "danger" });
            }
        } catch (e) {
            this.notification.add(
                e.message || _t("Failed to save settings. Check your permissions."),
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

    onInputCheckinGracePeriod(ev) {
        this.state.settings.checkin_grace_period_str = ev.target.value;
    }
    onInputDeadTime(ev) {
        this.state.settings.dead_time_str = ev.target.value;
    }
    onInputCheckinBuffer(ev) {
        this.state.settings.checkin_buffer_str = ev.target.value;
    }
    onInputLunchDuration(ev) {
        this.state.settings.lunch_duration_str = ev.target.value;
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
    onToggleCheckinGrace(ev) {
        this.state.settings.enable_checkin_grace = ev.target.checked;
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
