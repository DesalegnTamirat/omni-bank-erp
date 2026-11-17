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

            // Only run if this table has an is_selected column
            const th = table.querySelector('th[data-name="is_selected"]');
            if (!th) {
                return;
            }

            const box = th.querySelector("input[type='checkbox']");
            if (!box) {
                return;
            }

            const records = this.props.list?.records || [];
            const isAll = records.length > 0 && records.every((r) => Boolean(r.data.is_selected));
            const isAny = records.some((r) => Boolean(r.data.is_selected));

            box.checked = isAll;
            box.indeterminate = !isAll && isAny;
        };

        this.updateSelectAllHeader = updateSelectAllHeader;

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
        const colName = column?.name || "is_selected";
        const records = this.props.list.records;
        return records.length > 0 && records.every((r) => Boolean(r.data[colName]));
    },

    async toggleAutoMatchRecord(record, column, ev) {
        if (!record) {
            return;
        }
        if (ev) {
            ev.stopPropagation();
        }
        const colName = column?.name || "is_selected";
        const currentValue = Boolean(record.data[colName]);
        const newValue = !currentValue;

        // Immediately update all DOM checkboxes in this row
        const table = this.tableRef?.el;
        if (table) {
            const row = table.querySelector(`tr[data-id="${record.id}"]`);
            if (row) {
                const inputs = row.querySelectorAll('input[type="checkbox"]');
                inputs.forEach((input) => {
                    input.checked = newValue;
                });
            }
        } else if (ev?.target) {
            const input = ev.target.tagName === "INPUT" ? ev.target : ev.target.querySelector("input");
            if (input) {
                input.checked = newValue;
            }
        }

        try {
            if (this.props.list?.enterEditMode) {
                await this.props.list.enterEditMode(record);
            }
            await record.update({ [colName]: newValue });
        } catch (e) {
            console.warn("record.update note:", e);
            record.data[colName] = newValue;
            if (record._changes) {
                record._changes[colName] = newValue;
            }
            record.dirty = true;
        }

        if (typeof this.updateSelectAllHeader === "function") {
            this.updateSelectAllHeader();
        }
    },

    async onCellClicked(record, column, ev, newWindow) {
        if (column && column.name === "is_selected") {
            await this.toggleAutoMatchRecord(record, column, ev);
            return;
        }
        return super.onCellClicked(...arguments);
    },

    async toggleAutoMatchSelectAll(column, ev) {
        if (!this.props.list || !this.props.list.records) {
            return;
        }
        const colName = column?.name || "is_selected";
        const records = this.props.list.records;
        if (!records.length) {
            return;
        }
        const isAll = records.every((r) => Boolean(r.data[colName]));
        const newValue = !isAll;
        if (ev && ev.target) {
            ev.target.checked = newValue;
            ev.target.indeterminate = false;
        }

        const table = this.tableRef?.el;
        if (table) {
            const rowCheckboxes = table.querySelectorAll('tbody td input[type="checkbox"]');
            for (const cb of rowCheckboxes) {
                cb.checked = newValue;
            }
        }

        const targetRecords = records.filter((r) => Boolean(r.data[colName]) !== newValue);
        for (let i = 0; i < targetRecords.length; i++) {
            const record = targetRecords[i];
            const isLast = i === targetRecords.length - 1;
            try {
                if (typeof record._update === "function" && record.model?.mutex) {
                    await record.model.mutex.exec(() =>
                        record._update({ [colName]: newValue }, { withoutOnchange: !isLast })
                    );
                } else {
                    await record.update({ [colName]: newValue });
                }
            } catch (e) {
                console.warn("batch update note:", e);
            }
        }

        if (typeof this.updateSelectAllHeader === "function") {
            this.updateSelectAllHeader();
        }
    },
});
