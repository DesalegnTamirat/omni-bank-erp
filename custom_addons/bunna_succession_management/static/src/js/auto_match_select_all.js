/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onMounted, onPatched } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        try {
            this.orm = useService("orm");
        } catch (_) {
            this.orm = this.env.services?.orm;
        }
        try {
            this.actionService = useService("action");
        } catch (_) {
            this.actionService = this.env.services?.action;
        }

        const updateSelectAllHeader = () => {
            const table = this.tableRef?.el;
            if (!table) {
                return;
            }

            // Only run if this table has an is_selected column (Auto Match candidate table)
            const th = table.querySelector('th[data-name="is_selected"]');
            if (!th) {
                return;
            }

            const records = this.props.list?.records?.filter((r) => !r.data.already_nominated) || [];
            const isAll = records.length > 0 && records.every((r) => Boolean(r.data.is_selected));
            const isAny = records.some((r) => Boolean(r.data.is_selected));

            let box = th.querySelector("input.o_automatch_select_all_box");
            if (!box) {
                th.innerHTML = "";
                const container = document.createElement("div");
                container.className = "d-inline-flex align-items-center justify-content-center w-100";

                box = document.createElement("input");
                box.type = "checkbox";
                box.className = "form-check-input cursor-pointer o_automatch_select_all_box m-0";
                box.style.cursor = "pointer";
                box.title = "Select All / Deselect All";

                container.appendChild(box);
                th.appendChild(container);
                th.style.cursor = "pointer";
                th.onclick = (ev) => {
                    if (ev.target !== box) {
                        ev.stopPropagation();
                        box.click();
                    }
                };

                // Master select all / deselect all in 1 click
                box.onclick = async (ev) => {
                    ev.stopPropagation();
                    const currentRecords = this.props.list?.records?.filter((r) => !r.data.already_nominated) || [];
                    if (!currentRecords.length) {
                        return;
                    }

                    const allChecked = currentRecords.every((r) => Boolean(r.data.is_selected));
                    const targetVal = !allChecked;
                    box.checked = targetVal;
                    box.indeterminate = false;

                    // Immediately update row checkboxes in DOM for instant visual feedback
                    const rowCheckboxes = table.querySelectorAll('tbody td[name="is_selected"] input[type="checkbox"]:not(:disabled)');
                    for (const cb of rowCheckboxes) {
                        cb.checked = targetVal;
                    }

                    const root = this.props.list?.model?.root;
                    const orm = this.orm || this.env.services?.orm;
                    const validModels = ["succession.auto.match.wizard", "succession.candidate.nomination.wizard"];

                    // Fast 1-click backend bulk update and reload
                    if (root && root.resId && validModels.includes(root.resModel) && orm) {
                        try {
                            const action = await orm.call(
                                root.resModel,
                                targetVal ? "action_select_all" : "action_deselect_all",
                                [[root.resId]]
                            );
                            if (typeof root.load === "function") {
                                await root.load();
                            } else if (action && (this.actionService || this.env.services?.action)) {
                                const actService = this.actionService || this.env.services?.action;
                                await actService.doAction(action);
                            }
                        } catch (e) {
                            console.error("Auto match select all error:", e);
                        }
                    } else {
                        // In-memory fallback
                        for (const rec of currentRecords) {
                            if (Boolean(rec.data.is_selected) !== targetVal) {
                                await rec.update({ is_selected: targetVal });
                            }
                        }
                    }
                };
            }

            box.checked = isAll;
            box.indeterminate = !isAll && isAny;
        };

        const removeTopScrollbar = () => {
            const table = this.tableRef?.el;
            if (!table) {
                return;
            }
            const renderer = table.parentElement;
            const container = renderer?.parentElement;
            if (container) {
                container.querySelectorAll(".o_automatch_top_scrollbar").forEach((el) => el.remove());
            }
        };

        onMounted(() => {
            removeTopScrollbar();
            updateSelectAllHeader();
        });
        onPatched(() => {
            removeTopScrollbar();
            updateSelectAllHeader();
        });
    },

    isAutoMatchAllSelected(column) {
        if (!this.props.list || !this.props.list.records) {
            return false;
        }
        const records = this.props.list.records.filter((r) => !r.data.already_nominated);
        return records.length > 0 && records.every((r) => Boolean(r.data[column.name]));
    },

    async toggleAutoMatchSelectAll(column, ev) {
        if (!this.props.list || !this.props.list.records) {
            return;
        }
        const records = this.props.list.records.filter((r) => !r.data.already_nominated);
        if (!records.length) {
            return;
        }
        const isAll = records.every((r) => Boolean(r.data[column.name]));
        const newValue = !isAll;
        if (ev && ev.target) {
            ev.target.checked = newValue;
            ev.target.indeterminate = false;
        }

        const table = this.tableRef?.el;
        if (table) {
            const rowCheckboxes = table.querySelectorAll('tbody td[name="is_selected"] input[type="checkbox"]:not(:disabled)');
            for (const cb of rowCheckboxes) {
                cb.checked = newValue;
            }
        }

        const root = this.props.list?.model?.root;
        const orm = this.orm || this.env.services?.orm;
        const validModels = ["succession.auto.match.wizard", "succession.candidate.nomination.wizard"];

        if (root && root.resId && validModels.includes(root.resModel) && orm) {
            try {
                const action = await orm.call(
                    root.resModel,
                    newValue ? "action_select_all" : "action_deselect_all",
                    [[root.resId]]
                );
                if (typeof root.load === "function") {
                    await root.load();
                } else if (action && (this.actionService || this.env.services?.action)) {
                    const actService = this.actionService || this.env.services?.action;
                    await actService.doAction(action);
                }
            } catch (e) {
                console.error("Auto match select all error:", e);
            }
        } else {
            for (const record of records) {
                if (Boolean(record.data[column.name]) !== newValue) {
                    await record.update({ [column.name]: newValue });
                }
            }
        }
    },
});
