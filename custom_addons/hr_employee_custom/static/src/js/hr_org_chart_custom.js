/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { HrOrgChart } from "@hr_org_chart/fields/hr_org_chart";

if (HrOrgChart) {
    patch(HrOrgChart.prototype, {
        onEmployeeRedirect(employeeId) {
            // Disable employee profile navigation from org chart hierarchy
            return;
        },
        _onEmployeeRedirect(employeeId) {
            // Disable employee profile navigation from org chart hierarchy
            return;
        },
        _onEmployeeSubordinatesRedirect(employeeId) {
            // Disable subordinates navigation from org chart hierarchy
            return;
        }
    });
}

// Global capture-phase event listener to prevent click navigation on org chart profile elements
document.addEventListener("click", function (event) {
    const orgChartContainer = event.target.closest("#o_employee_org_chart, .o_employee_org_chart_wrapper, .o_org_chart");
    if (orgChartContainer) {
        const clickableTarget = event.target.closest("a, .o_employee_redirect, .o_media_object, .o_org_chart_entry_content, [data-employee-id]");
        if (clickableTarget && !event.target.closest(".o_org_chart_show_more, button")) {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            return false;
        }
    }
}, true);
