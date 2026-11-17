/** @odoo-module **/

import { registry } from "@web/core/registry";

let currentPillTimeout = null;
let currentClickHandler = null;

export function showAttendanceTopPill(params = {}) {
    if (typeof document === "undefined") return;

    const message = params.message || "";
    const subtitle = params.subtitle || "";
    const type = params.type || "success";
    const icon = params.icon || (type === "warning" ? "fa-exclamation-triangle" : (type === "danger" ? "fa-ban" : "fa-check"));
    const duration = params.duration || 5000;

    // Remove existing pill and backdrop if present
    cleanupPillImmediate();

    const backdrop = document.createElement("div");
    backdrop.id = "o_attendance_top_pill_backdrop";
    backdrop.className = "o_attendance_top_pill_backdrop";

    const pill = document.createElement("div");
    pill.id = "o_attendance_top_pill";
    pill.className = `o_attendance_top_pill o_pill_${type}`;

    let statusDotColor = "#10b981"; // emerald
    if (type === "warning") statusDotColor = "#f59e0b";
    else if (type === "danger") statusDotColor = "#ef4444";
    else if (type === "info") statusDotColor = "#3b82f6";

    // 1. Pulse dot
    const pulseDot = document.createElement("span");
    pulseDot.className = "o_pill_pulse_dot";
    pulseDot.style.background = statusDotColor;
    pill.appendChild(pulseDot);

    // 2. Status icon
    const iconEl = document.createElement("i");
    iconEl.className = `fa ${icon} o_pill_icon`;
    pill.appendChild(iconEl);

    // 3. Text wrapper with safe textContent (prevents HTML/XSS injection)
    const textWrapper = document.createElement("div");
    textWrapper.className = "o_pill_text_wrapper";

    const msgSpan = document.createElement("span");
    msgSpan.className = "o_pill_message";
    msgSpan.textContent = message;
    textWrapper.appendChild(msgSpan);

    if (subtitle) {
        const subSpan = document.createElement("span");
        subSpan.className = "o_pill_subtitle";
        subSpan.textContent = subtitle;
        textWrapper.appendChild(subSpan);
    }
    pill.appendChild(textWrapper);

    // 4. Close button
    const closeBtn = document.createElement("button");
    closeBtn.className = "o_pill_close_btn";
    closeBtn.title = "Close";
    closeBtn.innerHTML = "&times;";
    closeBtn.onclick = (e) => {
        e.stopPropagation();
        dismissPill();
    };
    pill.appendChild(closeBtn);

    document.body.appendChild(backdrop);
    document.body.appendChild(pill);

    const onDismiss = () => {
        dismissPill();
    };

    // Dismiss on clicking backdrop or pill
    backdrop.addEventListener("click", onDismiss);
    pill.addEventListener("click", onDismiss);

    // Global click listener after short tick so the triggering submit click doesn't immediately dismiss it
    setTimeout(() => {
        currentClickHandler = (e) => {
            dismissPill();
        };
        document.addEventListener("click", currentClickHandler, { once: true, capture: true });
    }, 100);

    // Auto dismiss after duration (default 5000ms / 5s)
    currentPillTimeout = setTimeout(() => {
        dismissPill();
    }, duration);
}

function cleanupPillImmediate() {
    if (currentPillTimeout) {
        clearTimeout(currentPillTimeout);
        currentPillTimeout = null;
    }
    if (currentClickHandler) {
        document.removeEventListener("click", currentClickHandler, { capture: true });
        currentClickHandler = null;
    }
    const backdrop = document.getElementById("o_attendance_top_pill_backdrop");
    const pill = document.getElementById("o_attendance_top_pill");
    if (pill && pill.parentNode) pill.remove();
    if (backdrop && backdrop.parentNode) backdrop.remove();
}

function dismissPill() {
    if (currentPillTimeout) {
        clearTimeout(currentPillTimeout);
        currentPillTimeout = null;
    }
    if (currentClickHandler) {
        document.removeEventListener("click", currentClickHandler, { capture: true });
        currentClickHandler = null;
    }
    const backdrop = document.getElementById("o_attendance_top_pill_backdrop");
    const pill = document.getElementById("o_attendance_top_pill");

    if (pill) {
        pill.classList.add("o_pill_fade_out");
    }
    if (backdrop) {
        backdrop.classList.add("o_pill_fade_out");
    }
    setTimeout(() => {
        if (pill && pill.parentNode) {
            pill.remove();
        }
        if (backdrop && backdrop.parentNode) {
            backdrop.remove();
        }
    }, 250);
}

/**
 * Client Action: attendance_action_pill
 * Dispatches the centered floating pill and softly reloads the current form controller
 * so the record is updated in the browser without a jarring page refresh.
 */
function attendanceActionPillHandler(env, action) {
    const params = action.params || {};
    showAttendanceTopPill(params);

    if (params.reload !== false) {
        const controller = env.services.action && env.services.action.currentController;
        if (controller && controller.jsId) {
            env.services.action.restore(controller.jsId).catch(() => {});
        }
    }
}

registry.category("actions").add("attendance_action_pill", attendanceActionPillHandler);
