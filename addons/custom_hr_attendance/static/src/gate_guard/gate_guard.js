/** @odoo-module **/

import { patch } from '@web/core/utils/patch';
import { actionService } from '@web/webclient/actions/action_service';
import { menuService } from '@web/webclient/menus/menu_service';
import { session } from '@web/session';
import { _t } from '@web/core/l10n/translation';

/**
 * Checks whether an action request is exempt from the ERP Access Gate check.
 * Allowed exempt actions: Check In / Check Out dashboard & Discuss.
 */
function isActionExempt(actionRequest) {
  if (!actionRequest) return false;
  let tag = '';
  let xmlId = '';
  if (typeof actionRequest === 'string') {
    xmlId = actionRequest;
    tag = actionRequest;
  } else if (typeof actionRequest === 'number') {
    // Numeric action ID (e.g., action-187 for Employees) is NOT exempt
    return false;
  } else if (typeof actionRequest === 'object') {
    tag = actionRequest.tag || actionRequest.type || '';
    xmlId = actionRequest.xml_id || actionRequest.xmlid || '';
  }

  return (
    xmlId === 'custom_hr_attendance.my_attendance_action' ||
    xmlId === 'custom_hr_attendance.action_my_attendance' ||
    tag === 'custom_hr_attendance.my_attendance_action' ||
    tag === 'action_my_attendance' ||
    xmlId === 'mail.action_discuss' ||
    tag === 'mail.action_discuss' ||
    tag === 'mail'
  );
}

/**
 * Toggles a class on document.body so CSS can hide the top-left App Switcher (:::) icon
 * when an employee is NOT checked in.
 */
function updateGateBodyClass() {
  const isGateActive = Boolean(
    session.enable_checkin_gate &&
    !session.is_system_admin &&
    !session.attendance_checked_in,
  );
  if (isGateActive) {
    document.body?.classList.add('o_gate_active');
  } else {
    document.body?.classList.remove('o_gate_active');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', updateGateBodyClass);
} else {
  updateGateBodyClass();
}

// Re-evaluate on every DOM mutation or state update
const observer = new MutationObserver(updateGateBodyClass);
if (document.body) {
  observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Intercept clicks on the App Switcher (:::) icon in capture mode
 * to prevent opening the home menu grid when employee is NOT checked in.
 */
window.addEventListener(
  'click',
  (event) => {
    if (
      session.enable_checkin_gate &&
      !session.is_system_admin &&
      !session.attendance_checked_in
    ) {
      const toggleBtn = event.target.closest(
        ".o_home_menu_toggle, .o_navbar_apps_menu, .o_menu_toggle, .o_app_switcher_toggle, [title='Apps'], [title='Home Menu']",
      );
      if (toggleBtn) {
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        // Trigger a friendly warning notification
        const env =
          window.odoo?.env ||
          (window.owl && window.owl.Component
            ? window.owl.Component.env
            : null);
        if (env && env.services && env.services.notification) {
          env.services.notification.add(
            _t(
              'ERP Access Gate Active: You must Check In on the Attendance Dashboard before accessing system modules.',
            ),
            {
              title: _t('Check-In Required'),
              type: 'warning',
              sticky: false,
            },
          );
        }
        return false;
      }
    }
  },
  true, // Capture phase
);

/**
 * Patch actionService to block unauthorized action execution
 */
patch(actionService, {
  start(env) {
    const result = super.start(...arguments);
    const originalDoAction = result.doAction;

    result.doAction = async function (actionRequest, options) {
      updateGateBodyClass();
      if (
        session.enable_checkin_gate &&
        !session.is_system_admin &&
        !session.attendance_checked_in
      ) {
        if (!isActionExempt(actionRequest)) {
          const notification = env.services.notification;
          if (notification) {
            notification.add(
              _t(
                'ERP Access Gate Active: You must Check In on the Attendance Dashboard before accessing system modules.',
              ),
              {
                title: _t('Check-In Required'),
                type: 'warning',
                sticky: false,
              },
            );
          }
          // Prevent execution of requested action and redirect cleanly to Check In / Check Out
          return originalDoAction.call(
            this,
            'custom_hr_attendance.action_my_attendance',
            { clearBreadcrumbs: true },
          );
        }
      }
      return originalDoAction.apply(this, arguments);
    };

    return result;
  },
});

/**
 * Patch menuService to block unapproved menu clicks and filter menu tree
 */
patch(menuService, {
  start(env) {
    const result = super.start(...arguments);
    const originalSelectMenu = result.selectMenu;

    result.selectMenu = async function (menu) {
      updateGateBodyClass();
      if (
        session.enable_checkin_gate &&
        !session.is_system_admin &&
        !session.attendance_checked_in
      ) {
        const menuObj = typeof menu === 'object' ? menu : result.getMenu(menu);
        const xmlId = menuObj ? menuObj.xmlid || menuObj.xml_id || '' : '';
        const actionID = menuObj
          ? menuObj.actionID || menuObj.action_id || ''
          : '';

        const isExempt =
          xmlId === 'custom_hr_attendance.menu_check_in_out' ||
          xmlId === 'mail.menu_root_discuss' ||
          xmlId === 'mail.box_inbox' ||
          actionID === 'custom_hr_attendance.action_my_attendance' ||
          actionID === 'custom_hr_attendance.my_attendance_action';

        if (!isExempt) {
          const notification = env.services.notification;
          if (notification) {
            notification.add(
              _t(
                'ERP Access Gate Active: You must Check In on the Attendance Dashboard before accessing system modules.',
              ),
              {
                title: _t('Check-In Required'),
                type: 'warning',
                sticky: false,
              },
            );
          }
          return; // Completely stop menu selection
        }
      }
      return originalSelectMenu.apply(this, arguments);
    };

    // Filter menu tree for non-checked-in employees
    const originalGetMenuAsTree = result.getMenuAsTree;
    result.getMenuAsTree = function (menuId) {
      const tree = originalGetMenuAsTree.apply(this, arguments);
      if (
        session.enable_checkin_gate &&
        !session.is_system_admin &&
        !session.attendance_checked_in
      ) {
        if (tree && tree.childrenTree) {
          tree.childrenTree = tree.childrenTree.filter((child) => {
            return (
              child.xmlid === 'custom_hr_attendance.menu_check_in_out' ||
              child.id === 'custom_hr_attendance.menu_check_in_out' ||
              child.name === 'Check In / Check Out'
            );
          });
        }
      }
      return tree;
    };

    return result;
  },
});
