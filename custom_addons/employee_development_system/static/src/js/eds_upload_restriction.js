/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";
import { humanNumber } from "@web/core/utils/numbers";
import { BinaryField } from "@web/views/fields/binary/binary_field";
import { FileUploader } from "@web/views/fields/file_handler";
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";

const ALLOWED_EXTS = [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".svg"];
const ACCEPT_ATTRIBUTE = ".pdf,image/*";

function isEdsModel(resModel) {
    if (!resModel || typeof resModel !== "string") {
        return false;
    }
    return resModel.startsWith("eds.") || resModel === "training.commitment";
}

function getEdsMaxBytes() {
    const maxMb = session.eds_max_upload_size_mb || 10;
    return maxMb * 1024 * 1024;
}

function validateEdsFile(file, notificationService) {
    if (!file) {
        return false;
    }
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    const isAllowedFormat =
        ALLOWED_EXTS.includes(ext) ||
        file.type === "application/pdf" ||
        (file.type && file.type.startsWith("image/"));

    if (!isAllowedFormat) {
        notificationService.add(
            _t("Upload restricted: Only PDF documents and image files are allowed in EDS. ('%(name)s' is not accepted)", {
                name: file.name,
            }),
            { type: "danger" }
        );
        return false;
    }

    const maxBytes = getEdsMaxBytes();
    if (file.size > maxBytes) {
        const maxMb = session.eds_max_upload_size_mb || 10;
        notificationService.add(
            _t("Upload restricted: File '%(name)s' (%(size)s) exceeds the maximum allowed file size of %(maxMb)s MB in EDS.", {
                name: file.name,
                size: humanNumber(file.size) + "B",
                maxMb: maxMb,
            }),
            { type: "danger" }
        );
        return false;
    }
    return true;
}

// 1. Restrict BinaryField
patch(BinaryField.prototype, {
    setup() {
        super.setup(...arguments);
        if (isEdsModel(this.props.record?.resModel)) {
            this.props.acceptedFileExtensions = ACCEPT_ATTRIBUTE;
            this.props.allowedMIMETypes = "application/pdf,image/png,image/jpeg,image/webp,image/gif,image/bmp,image/svg+xml";
        }
    },
});

// 2. Restrict FileUploader
patch(FileUploader.prototype, {
    async onSelectFileButtonClick(ev) {
        const currentModel = this.props.record?.resModel ||
                             document.querySelector(".o_form_view")?.dataset?.modelName;
        if (isEdsModel(currentModel) && this.fileInputRef?.el) {
            this.fileInputRef.el.setAttribute("accept", ACCEPT_ATTRIBUTE);
        }
        return super.onSelectFileButtonClick(...arguments);
    },
    async onFileChange(ev) {
        const currentModel = this.props.record?.resModel ||
                             document.querySelector(".o_form_view")?.dataset?.modelName;
        if (isEdsModel(currentModel) && ev.target.files) {
            for (const file of ev.target.files) {
                if (!validateEdsFile(file, this.notification)) {
                    ev.target.value = null;
                    return null;
                }
            }
        }
        return super.onFileChange(...arguments);
    },
});

// 3. Restrict Chatter Attachment Uploads
if (AttachmentUploadService) {
    patch(AttachmentUploadService.prototype, {
        async upload(thread, composer, file, options) {
            const threadModel = thread?.model || options?.thread?.model;
            if (isEdsModel(threadModel)) {
                if (!validateEdsFile(file, this.notificationService)) {
                    return;
                }
            }
            return super.upload(...arguments);
        },
    });
}
