/** @odoo-module **/

import { session } from "@web/session";

// ---- Configuration ---------------------------------------------------
// Values come from odoo.conf ([options] idle_logout_timeout / idle_logout_warning),
// injected server-side into session_info by models/ir_http.py. Falls back to
// 3 min / 30s if the keys aren't set in odoo.conf.
const IDLE_LIMIT_MS = (session.idle_logout_timeout ?? 180) * 1000;
const WARNING_AT_MS = (session.idle_logout_warning ?? 30) * 1000;
const DANGER_AT_MS = Math.min(10 * 1000, WARNING_AT_MS);
// -----------------------------------------------------------------------

let remainingMs = IDLE_LIMIT_MS;
let tickInterval = null;
let widgetEl = null;

function buildWidget() {
    if (widgetEl) {
        return widgetEl;
    }
    widgetEl = document.createElement("div");
    widgetEl.id = "idle-logout-widget";
    widgetEl.title = "Click to stay logged in";
    Object.assign(widgetEl.style, {
        position: "fixed",
        top: "8px",
        right: "8px",
        zIndex: 2000,
        padding: "5px 12px",
        borderRadius: "14px",
        fontSize: "12px",
        fontFamily: "sans-serif",
        fontWeight: "600",
        color: "#fff",
        background: "#714B67",
        display: "none",
        alignItems: "center",
        gap: "6px",
        cursor: "pointer",
        boxShadow: "0 1px 4px rgba(0,0,0,.25)",
        transition: "background .3s",
        userSelect: "none",
    });
    widgetEl.innerHTML =
        '<span>\u{1F512}</span><span id="idle-logout-time"></span>' +
        '<span style="opacity:.85">(click to stay)</span>';
    widgetEl.addEventListener("click", resetTimer);
    document.body.appendChild(widgetEl);
    return widgetEl;
}

function formatTime(ms) {
    const totalSec = Math.max(0, Math.ceil(ms / 1000));
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
}

function updateWidget() {
    const el = buildWidget();
    const timeEl = el.querySelector("#idle-logout-time");
    if (remainingMs <= WARNING_AT_MS) {
        el.style.display = "flex";
        timeEl.textContent = formatTime(remainingMs);
        el.style.background = remainingMs <= DANGER_AT_MS ? "#cc0000" : "#e08b00";
    } else {
        el.style.display = "none";
    }
}

async function doLogout() {
    clearInterval(tickInterval);
    try {
        await fetch("/web/session/logout", { method: "GET" });
    } finally {
        window.location.href = "/web/login";
    }
}

function tick() {
    remainingMs -= 1000;
    updateWidget();
    if (remainingMs <= 0) {
        doLogout();
    }
}

function resetTimer() {
    remainingMs = IDLE_LIMIT_MS;
    updateWidget();
}

function startWatcher() {
    tickInterval = setInterval(tick, 1000);
    ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "click"].forEach((evt) => {
        document.addEventListener(evt, resetTimer, true);
    });
    resetTimer();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startWatcher);
} else {
    startWatcher();
}
