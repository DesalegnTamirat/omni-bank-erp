/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    StateSelectionField,
    stateSelectionField,
} from "@web/views/fields/state_selection/state_selection_field";

export const STATUS_COLORS = {
    'on_track': 20,
    'at_risk': 22,
    'off_track': 23,
    'on_hold': 21,
    'done': 24,
};

export const STATUS_COLOR_PREFIX = "o_status_bubble mx-0 o_color_bubble_";

export class ProjectStateSelectionField extends StateSelectionField {
    setup() {
        super.setup();
        this.colorPrefix = STATUS_COLOR_PREFIX;
        this.colors = STATUS_COLORS;
    }
}

export const projectStateSelectionField = {
    ...stateSelectionField,
    component: ProjectStateSelectionField,
};

registry.category("fields").add("project_state_selection", projectStateSelectionField);
