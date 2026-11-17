import { onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { openDmsViewer } from "./dms_viewer";

/**
 * Upload + drag and drop for the Documents kanban / list.
 * Files can be uploaded through the upload modal dialog with folder / custom permissions,
 * or dropped directly to /dms/upload.
 */
const ALLOWED_FILE_EXTENSIONS = [
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "bmp",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf", "txt", "csv",
];
const ALLOWED_FILE_RE = new RegExp(`\\.(${ALLOWED_FILE_EXTENSIONS.join("|")})$`, "i");

function useDmsUpload(controller) {
    const fileUpload = useService("file_upload");
    const notification = useService("notification");
    const actionService = useService("action");

    // Only Admins can upload; Viewers get no Upload button and no drop zone.
    const state = useState({ canUpload: false });
    onWillStart(async () => {
        state.canUpload = await user.hasGroup("documents_lite.group_dms_manager");
    });

    const currentFolderId = () => {
        const sm = controller.env.searchModel;
        const section = sm?.getSections?.((s) => s.type === "category" && s.fieldName === "folder_id")[0];
        return (section && section.activeValueId) || controller.props.context.default_folder_id || false;
    };

    const upload = async (files) => {
        files = [...files];
        const MAX_SIZE = 5 * 1024 * 1024; // keep in sync with documents_lite.max_file_size_mb
        const badType = files.filter((f) => !ALLOWED_FILE_RE.test(f.name));
        if (badType.length) {
            notification.add(
                _t("%s is not an allowed file type. Only PDF, images and documents can be uploaded.", badType[0].name),
                { type: "danger" }
            );
            files = files.filter((f) => ALLOWED_FILE_RE.test(f.name));
        }
        const tooBig = files.filter((f) => f.size > MAX_SIZE);
        if (tooBig.length) {
            notification.add(_t("%s is larger than 5 MB and was skipped.", tooBig[0].name), { type: "danger" });
            files = files.filter((f) => f.size <= MAX_SIZE);
        }
        if (!state.canUpload || !files.length) {
            return;
        }
        const ctx = controller.props.context;
        try {
            await fileUpload.upload("/dms/upload", files, {
                buildFormData: (fd) => {
                    fd.append("folder_id", currentFolderId());
                    if (ctx.default_res_model && ctx.default_res_id) {
                        fd.append("res_model", ctx.default_res_model);
                        fd.append("res_id", ctx.default_res_id);
                    }
                },
            });
            notification.add(_t("Upload complete."), { type: "success" });
            controller.env.searchModel?.search();
        } catch (err) {
            notification.add(_t("Upload failed: %s", err.message || err), { type: "danger" });
        }
    };

    useBus(fileUpload.bus, "FILE_UPLOAD_LOADED", () => {
        controller.env.searchModel?.search();
    });

    useBus(fileUpload.bus, "FILE_UPLOAD_ERROR", (ev) => {
        notification.add(_t("Upload failed: %s", ev.detail?.error || "Error"), { type: "danger" });
    });

    // Drop zone: plain DOM so it works whatever the view layout is.
    let overlay = null;
    let depth = 0;
    const hasFiles = (ev) => state.canUpload && ev.dataTransfer && [...ev.dataTransfer.types].includes("Files");
    const show = () => {
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.className = "o_dms_dropzone";
            overlay.textContent = _t("Drop files to upload");
            document.body.appendChild(overlay);
        }
    };
    const hide = () => {
        depth = 0;
        overlay?.remove();
        overlay = null;
    };
    const onDragEnter = (ev) => {
        if (hasFiles(ev) && !document.querySelector(".modal.show")) {
            depth++;
            show();
        }
    };
    const onDragOver = (ev) => {
        if (hasFiles(ev)) {
            ev.preventDefault();
        }
    };
    const onDragLeave = (ev) => {
        if (hasFiles(ev) && --depth <= 0) {
            hide();
        }
    };
    const onDrop = (ev) => {
        if (hasFiles(ev)) {
            ev.preventDefault();
            hide();
            upload(ev.dataTransfer.files);
        }
    };
    const events = { dragenter: onDragEnter, dragover: onDragOver, dragleave: onDragLeave, drop: onDrop };
    onMounted(() => {
        for (const [name, fn] of Object.entries(events)) {
            window.addEventListener(name, fn);
        }
    });
    onWillUnmount(() => {
        hide();
        for (const [name, fn] of Object.entries(events)) {
            window.removeEventListener(name, fn);
        }
    });

    return {
        state,
        openUploadWizard() {
            const folderId = currentFolderId();
            actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Upload Document"),
                res_model: "dms.upload.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_folder_id: folderId || false,
                    default_res_model: controller.props.context.default_res_model || false,
                    default_res_id: controller.props.context.default_res_id || false,
                },
            }, {
                onClose: () => {
                    controller.env.searchModel?.search();
                },
            });
        },
        upload,
    };
}

export class DmsKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.dms = useDmsUpload(this);
        this.dmsDialog = useService("dialog");
        this.notification = useService("notification");
    }
    /** A click on a card shows the document full screen instead of opening the form. */
    async openRecord(record) {
        openDmsViewer(this.dmsDialog, record);
    }
    onUploadClick() {
        this.dms.openUploadWizard();
    }
}

export class DmsListController extends ListController {
    setup() {
        super.setup();
        this.dms = useDmsUpload(this);
        this.dmsDialog = useService("dialog");
        this.notification = useService("notification");
    }
    async openRecord(record) {
        openDmsViewer(this.dmsDialog, record);
    }
    onUploadClick() {
        this.dms.openUploadWizard();
    }
}

export class DmsFormController extends FormController {
    setup() {
        super.setup();
        this.notification = useService("notification");
    }
    async saveButtonClicked(params = {}) {
        const isNew = !this.model.root.resId;
        try {
            const saved = await super.saveButtonClicked(params);
            if (saved !== false) {
                this.notification.add(
                    isNew ? _t("Document created successfully.") : _t("Document updated successfully."),
                    { type: "success" }
                );
            }
            return saved;
        } catch (err) {
            this.notification.add(
                _t("Failed to save document: %s", err.message || err),
                { type: "danger" }
            );
            throw err;
        }
    }
    async beforeUnlink() {
        try {
            const res = await super.beforeUnlink(...arguments);
            this.notification.add(_t("Document deleted successfully."), { type: "success" });
            return res;
        } catch (err) {
            this.notification.add(_t("Failed to delete document: %s", err.message || err), { type: "danger" });
            throw err;
        }
    }
}

registry.category("views").add("dms_kanban", {
    ...kanbanView,
    Controller: DmsKanbanController,
    buttonTemplate: "documents_lite.KanbanButtons",
});
registry.category("views").add("dms_list", {
    ...listView,
    Controller: DmsListController,
    buttonTemplate: "documents_lite.ListButtons",
});
registry.category("views").add("dms_form", {
    ...formView,
    Controller: DmsFormController,
});
