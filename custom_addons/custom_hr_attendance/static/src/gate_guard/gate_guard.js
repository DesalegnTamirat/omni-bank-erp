/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { actionService } from "@web/webclient/actions/action_service";
import { menuService } from "@web/webclient/menus/menu_service";
import { NavBar } from "@web/webclient/navbar/navbar";
import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";

/**
 * Checks whether an action request is exempt from the ERP Access Gate check.
 * Allowed exempt actions: Check In / Check Out dashboard & Attendance management/settings.
 */
function isActionExempt(actionRequest, env) {
    if (session.is_gate_exempt) return true;
    if (!actionRequest) return false;
    let tag = "";
    let xmlId = "";
    let resModel = "";
    let actionId = null;

    if (typeof actionRequest === "string") {
        xmlId = actionRequest;
        tag = actionRequest;
    } else if (typeof actionRequest === "number") {
        actionId = actionRequest;
    } else if (typeof actionRequest === "object") {
        tag = actionRequest.tag || actionRequest.type || "";
        xmlId = actionRequest.xml_id || actionRequest.xmlid || "";
        resModel = actionRequest.res_model || "";
        actionId = actionRequest.id || null;
    }

    // Always exempt: Check In / Check Out attendance dashboard
    if (
        xmlId === "custom_hr_attendance.my_attendance_action" ||
        xmlId === "custom_hr_attendance.action_my_attendance" ||
        tag === "custom_hr_attendance.my_attendance_action" ||
        tag === "action_my_attendance" ||
        xmlId === "attendances" ||
        tag === "attendances"
    ) {
        return true;
    }

    // Attendance management actions & settings (allows admins/managers to manage attendance & toggle gate during emergency)
    const isAttendance =
        String(xmlId).startsWith("custom_hr_attendance.") ||
        String(xmlId).startsWith("hr_attendance.") ||
        String(resModel).startsWith("hr.attendance") ||
        String(resModel).startsWith("job.shift") ||
        String(resModel).startsWith("job.position") ||
        String(resModel).startsWith("location.based") ||
        String(resModel).startsWith("attendance.") ||
        String(resModel).startsWith("my.shift") ||
        String(resModel).startsWith("over.time") ||
        String(resModel).startsWith("overtime.") ||
        resModel === "res.config.settings" ||
        tag === "res.config.settings";

    if (isAttendance) {
        return true;
    }

    // If it's a numeric action ID, check if it belongs to an exempt menu in menuService
    if (actionId && env && env.services && env.services.menu) {
        const allMenus = env.services.menu.getAll() || [];
        const matchedMenu = allMenus.find((m) => m.actionID === actionId);
        if (matchedMenu) {
            const mXmlId = String(matchedMenu.xmlid || matchedMenu.xml_id || "");
            const mName = String(matchedMenu.name || "");
            if (
                mXmlId.startsWith("custom_hr_attendance.") ||
                mXmlId.startsWith("hr_attendance.") ||
                mName.includes("Attendance") ||
                mName.includes("Check In")
            ) {
                return true;
            }
        }
    }

    return false;
}

/**
 * Toggles a class on document.body so CSS can hide the top-left App Switcher (:::) icon
 * when an employee or administrator is NOT checked in.
 */
function updateGateBodyClass() {
    const isGateActive = Boolean(
        session.enable_checkin_gate &&
        !session.attendance_checked_in &&
        !session.is_gate_exempt
    );
    if (isGateActive) {
        document.body?.classList.add("o_gate_active");
        document.body?.classList.add("o_gate_regular_user");
    } else {
        document.body?.classList.remove("o_gate_active");
        document.body?.classList.remove("o_gate_regular_user");
    }
}

/**
 * Filter Settings Sidebar Tabs for non-System Administrators:
 * If the user is an Attendance Administrator but NOT a System Administrator (!session.is_system_admin),
 * hide non-attendance app tabs in the settings sidebar so they only see Attendance Settings.
 */
function updateSettingsTabs() {
    if (!session.is_system_admin && !session.is_gate_exempt) {
        const tabs = document.querySelectorAll(
            ".o_settings_container .settings_tab, .o_setting_container .settings_tab, .settings .tab, [data-key], .o_app_setting"
        );
        tabs.forEach((tab) => {
            const key = tab.getAttribute("data-key") || tab.getAttribute("name") || tab.getAttribute("id") || "";
            const text = (tab.textContent || "").trim();
            if (key === "general_settings" || text.includes("General Settings") || (key && key !== "custom_hr_attendance" && key !== "hr_attendance" && !text.includes("Attendances"))) {
                tab.style.setProperty("display", "none", "important");
            }
        });
    }
}

function handleStateUpdates() {
    updateGateBodyClass();
    updateSettingsTabs();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", handleStateUpdates);
} else {
    handleStateUpdates();
}

// Re-evaluate on DOM mutations
const observer = new MutationObserver(handleStateUpdates);
if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Intercept clicks on the App Switcher (:::) icon in capture mode
 * to prevent opening the home menu grid when employee is NOT checked in.
 */
window.addEventListener(
    "click",
    (event) => {
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            const toggleBtn = event.target.closest(
                ".o_home_menu_toggle, .o_navbar_apps_menu, .o_menu_toggle, .o_app_switcher_toggle, [title='Apps'], [title='Home Menu']"
            );
            if (toggleBtn) {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();

                const env = window.odoo?.env || (window.owl && window.owl.Component ? window.owl.Component.env : null);
                if (env && env.services && env.services.notification) {
                    env.services.notification.add(
                        _t("ERP Access Gate Active: You must Check In on the Attendance Dashboard before accessing system modules."),
                        {
                            title: _t("Check-In Required"),
                            type: "warning",
                            sticky: false,
                        }
                    );
                }
                if (env && env.services && env.services.action) {
                    env.services.action.doAction(
                        { type: "ir.actions.client", tag: "custom_hr_attendance.my_attendance_action" },
                        { clearBreadcrumbs: true }
                    );
                }
                return false;
            }
        }
    },
    true // Capture phase
);

/**
 * If an attendance gate validation error dialog is displayed, intercept clicking Close
 * and immediately mount the Check In / Check Out client action smoothly (no reload).
 */
window.addEventListener(
    "click",
    (event) => {
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            const btn = event.target.closest(
                ".modal-footer .btn, .o_dialog .btn, .modal-header .btn-close, .modal-backdrop"
            );
            if (btn) {
                const dialog = document.querySelector(".o_dialog, .modal");
                if (dialog && dialog.textContent.includes("You must check in before accessing the system")) {
                    const env = window.odoo?.env || (window.owl && window.owl.Component ? window.owl.Component.env : null);
                    if (env && env.services && env.services.action) {
                        env.services.action.doAction(
                            { type: "ir.actions.client", tag: "custom_hr_attendance.my_attendance_action" },
                            { clearBreadcrumbs: true }
                        );
                    }
                }
            }
        }
    },
    true
);

/**
 * Patch actionService to block unauthorized action execution and redirect to check-in
 */
patch(actionService, {
    start(env) {
        const result = super.start(...arguments);
        const originalDoAction = result.doAction;

        result.doAction = async function (actionRequest, options) {
            handleStateUpdates();
            if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
                if (!isActionExempt(actionRequest, env)) {
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
                    // Prevent execution of requested action and redirect cleanly to Check In / Check Out client action
                    return originalDoAction.call(
                        this,
                        { type: "ir.actions.client", tag: "custom_hr_attendance.my_attendance_action" },
                        { clearBreadcrumbs: true }
                    );
                }
            }
            return originalDoAction.apply(this, arguments);
        };

        // When non-exempt user is un-checked-in, automatically switch to Check In / Check Out client action on startup
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            Promise.resolve().then(() => {
                result.doAction(
                    { type: "ir.actions.client", tag: "custom_hr_attendance.my_attendance_action" },
                    { clearBreadcrumbs: true }
                );
            });
        }

        return result;
    },
});

/**
 * Patch NavBar.prototype to directly govern currentApp and currentAppSections.
 * For un-checked-in regular employees: returns undefined for currentApp and [] for currentAppSections,
 * guaranteeing clean focus mode (Option 1) on both initial login and refresh.
 * For un-checked-in attendance administrators: immediately surfaces the Attendances root app and
 * attendance configuration/management submenus (Option 2) without needing a page refresh.
 */
patch(NavBar.prototype, {
    get currentApp() {
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            // Un-checked-in non-exempt employees: NO brand at all, pure clean screen (Option 1)
            return undefined;
        }
        return super.currentApp;
    },

    get currentAppSections() {
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            // Un-checked-in non-exempt employees: NO submenus at all (Option 1)
            return [];
        }
        return super.currentAppSections;
    },
});

/**
 * Patch menuService to block unapproved menu clicks and prevent stale session storage
 */
patch(menuService, {
    async start(env) {
        const result = await super.start(...arguments);
        const originalSelectMenu = result.selectMenu;

        result.selectMenu = async function (menu) {
            handleStateUpdates();
            if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
                const menuObj = typeof menu === "number" ? result.getMenu(menu) : menu;
                const xmlId = String(menuObj ? (menuObj.xmlid || menuObj.xml_id || "") : "");
                const name = String(menuObj ? (menuObj.name || "") : "");
                const actionID = menuObj ? (menuObj.actionID || menuObj.action_id || "") : "";

                const isExempt =
                    xmlId.startsWith("custom_hr_attendance.") ||
                    xmlId.startsWith("hr_attendance.") ||
                    name.includes("Attendance") ||
                    name.includes("Check In") ||
                    actionID === "custom_hr_attendance.action_my_attendance" ||
                    actionID === "custom_hr_attendance.my_attendance_action";

                if (!isExempt) {
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
                    return env.services.action.doAction(
                        { type: "ir.actions.client", tag: "custom_hr_attendance.my_attendance_action" },
                        { clearBreadcrumbs: true }
                    );
                }
            }
            return originalSelectMenu.apply(this, arguments);
        };

        // For non-exempt employees: clear stale session storage so it doesn't resurrect attendance menus on refresh
        if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
            try {
                browser.sessionStorage.removeItem("menu_id");
            } catch (e) {}
        }

        // Filter menu tree for non-checked-in, non-exempt users
        const originalGetMenuAsTree = result.getMenuAsTree;
        result.getMenuAsTree = function (menuId) {
            const tree = originalGetMenuAsTree.apply(this, arguments);
            if (session.enable_checkin_gate && !session.attendance_checked_in && !session.is_gate_exempt) {
                if (tree && Array.isArray(tree.childrenTree)) {
                    return { ...tree, childrenTree: [] };
                }
            }
            return tree;
        };

        return result;
    },
});
