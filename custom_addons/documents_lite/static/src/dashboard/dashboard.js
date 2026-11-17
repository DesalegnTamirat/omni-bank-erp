/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class DmsDashboard extends Component {
    static template = "documents_lite.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, error: false, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call("dms.dashboard", "get_dashboard_data", []);
        } catch (error) {
            this.state.error = true;
            console.error("DMS dashboard failed to load", error);
        }
        this.state.loading = false;
    }

    get kpiCols() {
        const count = this.state.data?.kpis?.length || 4;
        return Math.min(count, 4);
    }

    openKpi(kpi) {
        if (kpi.action) {
            return this.action.doAction(kpi.action);
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: kpi.label,
            res_model: "dms.document",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: kpi.domain || [],
        });
    }

    openFolder(folder) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: folder.name,
            res_model: "dms.document",
            views: [[false, "kanban"], [false, "list"], [false, "form"]],
            domain: [["folder_id", "=", folder.id]],
            context: { default_folder_id: folder.id },
        });
    }

    openDocument(docId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.document",
            res_id: docId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openUploadWizard() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Upload Document"),
            res_model: "dms.upload.wizard",
            views: [[false, "form"]],
            target: "new",
        }, {
            onClose: () => this.load(),
        });
    }

    viewAllDocuments() {
        return this.action.doAction("documents_lite.dms_document_action");
    }
}

registry.category("actions").add("documents_lite_dashboard", DmsDashboard);
