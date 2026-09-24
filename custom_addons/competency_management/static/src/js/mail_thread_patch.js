/** @odoo-module **/

import { Thread } from "@mail/core/common/thread";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    async onClickUnreadMessagesBanner() {
        const thread = this.props.thread;
        if (!thread) {
            return;
        }
        const separator = thread.self_member_id?.new_message_separator_ui;
        if (separator) {
            await thread.loadAround(separator);
        }
        const targetMsg = thread.firstUnreadMessage
            || (separator && thread.messages ? thread.messages.find((m) => m.id >= separator) : null)
            || (thread.messages && thread.messages.length ? thread.messages[0] : null);
        if (targetMsg && typeof targetMsg.notIn === "function" && this.messageHighlight) {
            this.messageHighlight.highlightMessage(targetMsg, thread);
        }
    },
});
