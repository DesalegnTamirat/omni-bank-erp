import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import {
    dmsDocFromRecord,
    dmsKind,
    dmsPreviewUrl,
    openDmsViewer,
    useDmsIsAdmin,
} from "./dms_viewer";

export class DmsPreview extends Component {
    static template = "documents_lite.Preview";
    static props = {
        ...standardWidgetProps,
        pane: { type: Boolean, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
        this.admin = useDmsIsAdmin();
    }

    get data() {
        return this.props.record.data;
    }

    get docId() {
        return this.props.record.resId;
    }

    get doc() {
        return dmsDocFromRecord(this.props.record);
    }

    get kind() {
        return dmsKind(this.data.mimetype);
    }

    get src() {
        return dmsPreviewUrl(this.doc);
    }

    get canDownload() {
        return this.doc.allowDownload || this.admin.isAdmin;
    }

    get pdfSrc() {
        return this.src + (this.canDownload ? "#navpanes=0" : "#toolbar=0&navpanes=0");
    }

    get thumbUrl() {
        return `/web/image/dms.document/${this.docId}/thumbnail?unique=${this.data.checksum || ""}`;
    }

    get showPane() {
        return this.props.pane && this.docId && this.data.file_size;
    }

    onContextMenu(ev) {
        if (!this.canDownload) {
            ev.preventDefault();
        }
    }

    open(ev) {
        ev.stopPropagation();
        openDmsViewer(this.dialog, this.props.record);
    }
}

export const dmsPreview = {
    component: DmsPreview,
    extractProps: () => ({}),
};
registry.category("view_widgets").add("dms_preview", dmsPreview);
registry.category("view_widgets").add("dms_preview_pane", {
    component: DmsPreview,
    extractProps: () => ({ pane: true }),
});
