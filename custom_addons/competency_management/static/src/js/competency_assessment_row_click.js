/** @odoo-module **/

/**
 * Competency Assessment Row-Click and Auto-Save Enhancements:
 * 1. Clicking anywhere on an assessment row (including current_level, competency name, info icon)
 *    instantly opens the detail/guidance popup.
 *    Only 'comments' and 'evidence_attachment_ids' allow inline editing and do NOT trigger the popup.
 * 2. On the detail popup:
 *    - Clicking Level 1-4 indicator buttons executes Python action to save and close automatically.
 *    - Selecting a level from the current_level dropdown auto-saves immediately and closes the modal.
 *    - Typing remarks/comments auto-saves immediately.
 * 3. On the assessment form:
 *    - Editing remarks inline auto-saves immediately.
 *    - All selections and comments are preserved in 'draft' state, allowing employees
 *      to continue from where they left off upon returning.
 */

document.addEventListener("click", function (event) {
    // 1. Check if click is inside an assessment line table
    const table = event.target.closest("div[name='core_line_ids'], div[name='leadership_line_ids'], div[name='technical_line_ids']");
    if (!table) return;

    const row = event.target.closest("tr");
    if (!row) return;

    const cell = event.target.closest("td");
    if (!cell) return;

    const cellName = cell.getAttribute("name") || "";

    // Ignore ONLY remarks/comments and supporting documents upload
    if (
        cellName === "comments" ||
        cellName === "evidence_attachment_ids" ||
        event.target.closest(".o_field_many2many_binary, .o_field_binary_file")
    ) {
        return;
    }

    // If user clicked the button itself, let standard action run
    if (event.target.closest("button[name='action_open_guide']")) {
        return;
    }

    // Trigger open guide button in this row
    const openBtn = row.querySelector("button[name='action_open_guide']");
    if (openBtn) {
        event.preventDefault();
        event.stopPropagation();
        openBtn.click();
    }
}, true);

// 2. Auto-save in detail modal when current_level or remarks change
document.addEventListener("change", function (event) {
    // A) Modal auto-save
    const modal = event.target.closest(".modal.o_technical_modal, .modal.show, .modal");
    if (modal) {
        const lineForm = modal.querySelector(".o_form_view");
        if (!lineForm) return;

        // Check if it's the competency assessment line form
        const isLineForm = lineForm.querySelector("[name='competency_definition']") || lineForm.querySelector("[name='indicator_level_1']");
        if (!isLineForm) return;

        const targetName = event.target.getAttribute("name") || (event.target.closest("[name]")?.getAttribute("name") || "");

        if (targetName === "current_level") {
            const nextBtn = modal.querySelector("button[name='action_save_and_next']:not([disabled])");
            if (nextBtn) {
                setTimeout(() => nextBtn.click(), 100);
            } else {
                const finishBtn = modal.querySelector("button[name='action_save_and_close']:not([disabled])");
                if (finishBtn) {
                    setTimeout(() => finishBtn.click(), 100);
                }
            }
        } else if (targetName === "comments") {
            const saveBtn = modal.querySelector("button[name='action_save_and_close'], .o_form_button_save");
            if (saveBtn && !saveBtn.disabled) {
                setTimeout(() => {
                    saveBtn.click();
                }, 100);
            }
        }
        return;
    }

    // B) Main form inline table changes (such as editing comments) auto-save
    const table = event.target.closest("div[name='core_line_ids'], div[name='leadership_line_ids'], div[name='technical_line_ids']");
    if (table) {
        const targetName = event.target.getAttribute("name") || (event.target.closest("[name]")?.getAttribute("name") || "");
        if (targetName === "comments") {
            const mainSaveBtn = document.querySelector(".o_control_panel .o_form_button_save:not([disabled]), button.o_form_button_save:not([disabled])");
            if (mainSaveBtn) {
                setTimeout(() => {
                    mainSaveBtn.click();
                }, 300);
            }
        }
    }
}, true);
