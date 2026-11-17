import { onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { openDmsViewer } from "./dms_viewer";

/**
 * Upload + drag and drop for the Documents kanban / list.
 * Files are posted to /dms/upload with the folder picked in the search panel
 * (or the record the action is linked to).
 */
const ALLOWED_FILE_EXTENSIONS = [
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "bmp",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf", "txt", "csv",
];
const ALLOWED_FILE_RE = new RegExp(`\\.(${ALLOWED_FILE_EXTENSIONS.join("|")})$`, "i");

function useDmsUpload(controller) {
    const fileUpload = useService("file_upload");
    const notification = useService("notification");
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
        await fileUpload.upload("/dms/upload", files, {
            buildFormData: (fd) => {
                fd.append("folder_id", currentFolderId());
                if (ctx.default_res_model && ctx.default_res_id) {
                    fd.append("res_model", ctx.default_res_model);
                    fd.append("res_id", ctx.default_res_id);
                }
            },
        });
    };

    useBus(fileUpload.bus, "FILE_UPLOAD_LOADED", () => {
        notification.add(_t("Upload complete."), { type: "success" });
        controller.env.searchModel.search();
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
        pickFiles() {
            const input = document.createElement("input");
            input.type = "file";
            input.multiple = true;
            input.accept = ALLOWED_FILE_EXTENSIONS.map((e) => `.${e}`).join(",");
            input.onchange = () => upload(input.files);
            input.click();
        },
        upload,
    };
}

export class DmsKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.dms = useDmsUpload(this);
        this.dmsDialog = useService("dialog");
    }
    /** A click on a card shows the document full screen instead of opening the form. */
    async openRecord(record) {
        openDmsViewer(this.dmsDialog, record);
    }
    onUploadClick() {
        this.dms.pickFiles();
    }
}

export class DmsListController extends ListController {
    setup() {
        super.setup();
        this.dms = useDmsUpload(this);
        this.dmsDialog = useService("dialog");
    }
    async openRecord(record) {
        openDmsViewer(this.dmsDialog, record);
    }
    onUploadClick() {
        this.dms.pickFiles();
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
