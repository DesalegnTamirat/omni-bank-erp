/** @odoo-module **/

/**
 * New staff loan requests are only "real" once the header Save button
 * (action_save_request) ran: a request Odoo auto-saved is hidden until then.
 * The standard cloud-icon Save (and Alt+S) would create/save the record
 * WITHOUT flagging it, so while our Save button is on the page those two are
 * redirected to it. Plain DOM code: it does not depend on Odoo internals.
 */
function reslSaveButton() {
    return document.querySelector("button[name='action_save_request']");
}

document.addEventListener(
    "click",
    (ev) => {
        const target = ev.target;
        if (!target || !target.closest || !target.closest(".o_form_button_save")) {
            return;
        }
        const btn = reslSaveButton();
        if (btn) {
            ev.preventDefault();
            ev.stopPropagation();
            btn.click();
        }
    },
    true
);

document.addEventListener(
    "keydown",
    (ev) => {
        if (ev.altKey && ev.key && ev.key.toLowerCase() === "s") {
            const btn = reslSaveButton();
            if (btn) {
                ev.preventDefault();
                ev.stopPropagation();
                btn.click();
            }
        }
    },
    true
);