import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const ADMIN_GROUP = "documents_lite.group_dms_manager";

/** What the browser can show inline for a mimetype. */
export function dmsKind(mimetype, extension) {
    const m = (mimetype || "").toLowerCase();
    const ext = (extension || "").toLowerCase();
    if (m.startsWith("image/")) {
        return "image";
    }
    if (m === "application/pdf" || ext === "pdf") {
        return "pdf";
    }
    if (ext === "doc" || ext === "docx" || m === "application/msword" || m.includes("wordprocessingml")) {
        return "pdf";
    }
    if (m.startsWith("video/")) {
        return "video";
    }
    if (m.startsWith("audio/")) {
        return "audio";
    }
    if (m.startsWith("text/") || m === "application/json") {
        return "text";
    }
    return "other";
}

export function formatSize(bytes) {
    if (!bytes) {
        return "";
    }
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) {
        n /= 1024;
        i++;
    }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

/** Plain description of a dms.document record, whatever view it comes from. */
export function dmsDocFromRecord(record) {
    const d = record.data;
    const fileName = d.file_name || d.name || "";
    return {
        id: record.resId,
        name: d.name || fileName,
        fileName,
        mimetype: d.mimetype,
        extension: d.extension || (fileName.includes(".") ? fileName.split(".").pop().toLowerCase() : ""),
        size: d.file_size,
        checksum: d.checksum,
        allowDownload: d.allow_download !== false,
        folder: m2oName(d.folder_id),
        addedBy: m2oName(d.create_uid),
        modified: formatWhen(d.write_date),
    };
}

/** Display name of a many2one value, whatever shape the web client gives it. */
function m2oName(value) {
    if (!value) {
        return "";
    }
    return Array.isArray(value) ? value[1] || "" : value.display_name || value.name || "";
}

function formatWhen(value) {
    if (!value) {
        return "";
    }
    try {
        return value.toLocaleString
            ? value.toLocaleString({ year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
            : String(value);
    } catch {
        return "";
    }
}

export function dmsPreviewUrl(doc) {
    return `/dms/preview/${doc.id}?unique=${doc.checksum || ""}`;
}

/** Open the full-screen viewer on a record, with its siblings for next / previous. */
export function openDmsViewer(dialog, record) {
    const root = record.model?.root;
    const records = root?.records?.some((r) => r.resId === record.resId) ? root.records : [record];
    dialog.add(DmsViewer, {
        docs: records.map(dmsDocFromRecord),
        index: Math.max(
            0,
            records.findIndex((r) => r.resId === record.resId)
        ),
    });
}

export function useDmsIsAdmin() {
    const state = useState({ isAdmin: false });
    onWillStart(async () => {
        state.isAdmin = await user.hasGroup(ADMIN_GROUP);
    });
    return state;
}

export class DmsViewer extends Component {
    static template = "documents_lite.Viewer";
    static components = { Dialog };
    static props = {
        docs: Array,
        index: { type: Number, optional: true },
        close: Function,
    };

    setup() {
        this.action = useService("action");
        this.imgRef = useRef("img");
        this.stripRef = useRef("strip");
        this.state = useState({
            index: this.props.index || 0,
            loading: true,
            zoom: 1,
            fitWidth: 0,
            showInfo: false,
        });
        this.admin = useDmsIsAdmin();
        this.shownIndex = -1;
        this.onKeydown = (ev) => {
            if (ev.key === "ArrowRight") {
                this.next();
            } else if (ev.key === "ArrowLeft") {
                this.prev();
            } else if (this.kind === "image" && (ev.key === "+" || ev.key === "=")) {
                this.zoomIn();
            } else if (this.kind === "image" && ev.key === "-") {
                this.zoomOut();
            } else if (this.kind === "image" && ev.key === "0") {
                this.resetZoom();
            }
        };
        onMounted(() => {
            document.addEventListener("keydown", this.onKeydown);
            this.state.showInfo = window.innerWidth >= 1200;
            this.scrollStrip();
        });
        onPatched(() => this.scrollStrip());
        onWillUnmount(() => document.removeEventListener("keydown", this.onKeydown));
    }

    // ------------------------------------------------------------ current document
    get doc() {
        return this.props.docs[this.state.index];
    }
    get kind() {
        return dmsKind(this.doc.mimetype, this.doc.extension);
    }
    get src() {
        return dmsPreviewUrl(this.doc);
    }
    get pdfSrc() {
        // Chrome / Edge hide the PDF toolbar (and its download button) with these flags.
        return this.src + (this.canDownload ? "#navpanes=0" : "#toolbar=0&navpanes=0");
    }
    get canDownload() {
        return this.doc.allowDownload || this.admin.isAdmin;
    }
    get downloadUrl() {
        return `/dms/download/${this.doc.id}`;
    }
    get sizeLabel() {
        return formatSize(this.doc.size);
    }
    get counter() {
        return this.props.docs.length > 1 ? `${this.state.index + 1} / ${this.props.docs.length}` : "";
    }
    get hasMany() {
        return this.props.docs.length > 1;
    }
    get metaLine() {
        const doc = this.doc;
        return [(doc.extension || "").toUpperCase(), this.sizeLabel, doc.folder, this.counter]
            .filter(Boolean)
            .join("  ·  ");
    }
    get infoRows() {
        const doc = this.doc;
        const rows = [
            [_t("Name"), doc.name],
            [_t("File"), doc.fileName !== doc.name ? doc.fileName : ""],
            [_t("Folder"), doc.folder],
            [_t("Type"), doc.extension ? doc.extension.toUpperCase() : ""],
            [_t("Size"), this.sizeLabel],
            [_t("Modified"), doc.modified],
            [_t("Added by"), doc.addedBy],
            [_t("Download"), this.canDownload ? _t("Allowed") : _t("Disabled")],
        ];
        return rows.filter(([, value]) => value).map(([label, value]) => ({ label, value }));
    }
    get showSpinner() {
        return this.state.loading && ["image", "pdf", "text"].includes(this.kind);
    }
    get noPreviewText() {
        return _t("No preview is available for this type of file.");
    }

    // ------------------------------------------------------------ navigation
    goTo(index) {
        this.state.index = index;
        this.state.zoom = 1;
        this.state.loading = true;
    }
    next() {
        this.goTo((this.state.index + 1) % this.props.docs.length);
    }
    prev() {
        const n = this.props.docs.length;
        this.goTo((this.state.index - 1 + n) % n);
    }
    onLoaded() {
        this.state.loading = false;
    }
    toggleInfo() {
        this.state.showInfo = !this.state.showInfo;
    }
    thumbUrl(doc) {
        return dmsKind(doc.mimetype) === "image"
            ? `/web/image/dms.document/${doc.id}/thumbnail?unique=${doc.checksum || ""}`
            : false;
    }
    scrollStrip() {
        if (this.shownIndex === this.state.index) {
            return;
        }
        this.shownIndex = this.state.index;
        const active = this.stripRef.el?.querySelector(".o_dms_thumb_active");
        active?.scrollIntoView({ inline: "center", block: "nearest" });
    }

    // ------------------------------------------------------------ image zoom
    get zoomLabel() {
        return `${Math.round(this.state.zoom * 100)}%`;
    }
    get imgStyle() {
        return this.state.zoom > 1 && this.state.fitWidth
            ? `width:${Math.round(this.state.fitWidth * this.state.zoom)}px;max-width:none;max-height:none;`
            : "";
    }
    measureFit() {
        if (this.state.zoom === 1 && this.imgRef.el) {
            this.state.fitWidth = this.imgRef.el.getBoundingClientRect().width;
        }
    }
    zoomIn() {
        this.measureFit();
        this.state.zoom = Math.min(4, this.state.zoom + 0.5);
    }
    zoomOut() {
        this.state.zoom = Math.max(1, this.state.zoom - 0.5);
    }
    resetZoom() {
        this.state.zoom = 1;
    }
    toggleZoom() {
        if (this.state.zoom === 1) {
            this.measureFit();
            this.state.zoom = 2;
        } else {
            this.state.zoom = 1;
        }
    }

    // ------------------------------------------------------------ misc
    onContextMenu(ev) {
        if (!this.canDownload) {
            ev.preventDefault();
        }
    }
    openDetails() {
        const resId = this.doc.id;
        this.props.close();
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dms.document",
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
