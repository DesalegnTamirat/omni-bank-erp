/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class SuccessionReportsHub extends Component {
    static template = "bunna_succession_management.SuccessionReportsHub";
    setup() {}
}

registry.category("actions").add("succession_reports_hub", SuccessionReportsHub);
