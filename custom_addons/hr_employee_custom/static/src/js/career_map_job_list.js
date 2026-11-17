/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useState } from "@odoo/owl";

/**
 * Custom ListView controller for the "All Career Map" page.
 *
 * Adds a row of quick-filter buttons above the list:
 *   • All Positions
 *   • Positions Without Career Map
 *   • Pending Approval
 *   • Map Created
 *
 * Each button toggles the matching search filter defined in the
 * search view (view_hr_job_career_map_search) by its @name attribute.
 */

// The search-filter names we defined in the search view XML
const CAREER_MAP_FILTERS = [
    "career_map_not_created",
    "career_map_pending",
    "career_map_created",
];

class CareerMapJobListController extends ListController {
    setup() {
        super.setup();
        this.careerMapFilter = useState({ active: "all" });
    }

    /**
     * Returns true when the given filter key matches the currently active one.
     * Called from the OWL template via t-att-class.
     */
    isCareerMapFilterActive(key) {
        return this.careerMapFilter.active === key;
    }

    /**
     * Check if a search item is currently active (present in the query).
     */
    _isFilterActive(searchItemId) {
        return this.env.searchModel.query.some(
            (q) => q.searchItemId === searchItemId
        );
    }

    /**
     * Activates a filter button.  Deactivates all career-map search filters
     * first, then toggles the selected one (unless "all" is chosen).
     */
    selectCareerMapFilter(key) {
        this.careerMapFilter.active = key;

        const searchModel = this.env.searchModel;

        // Find all career-map filter search items
        const allItems = searchModel.getSearchItems((item) =>
            CAREER_MAP_FILTERS.includes(item.name)
        );

        // First: deactivate all of them
        for (const item of allItems) {
            if (this._isFilterActive(item.id)) {
                searchModel.toggleSearchItem(item.id);
            }
        }

        // Then: activate the selected one (unless user clicked "All Positions")
        if (key !== "all") {
            const target = allItems.find((item) => item.name === key);
            if (target && !this._isFilterActive(target.id)) {
                searchModel.toggleSearchItem(target.id);
            }
        }
    }
}

// Tell this controller to use our custom OWL template
CareerMapJobListController.template = "hr_employee_custom.CareerMapListView";

// Register the view under js_class = "career_map_job_list"
registry.category("views").add("career_map_job_list", {
    ...listView,
    Controller: CareerMapJobListController,
});
