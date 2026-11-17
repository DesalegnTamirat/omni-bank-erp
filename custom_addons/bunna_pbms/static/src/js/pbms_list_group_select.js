/** @odoo-module **/
/**
 * PBMS List Group Select — cascade group checkbox to all child rows.
 *
 * Works together with pbms_list_group_select.xml which injects a checkbox
 * element into each group header row.
 *
 * Behaviour:
 *  • All children unselected  → checkbox is unchecked
 *  • Some children selected   → checkbox is indeterminate (–)
 *  • All children selected    → checkbox is checked
 *  • Click unchecked/indet.   → select ALL child records
 *  • Click checked            → deselect ALL child records
 */

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useEffect } from "@odoo/owl";

patch(ListRenderer.prototype, {

    setup() {
        super.setup(...arguments);

        // After every render, update the indeterminate property on group checkboxes
        // (HTML doesn't have an `indeterminate` attribute, only a JS property).
        useEffect(() => {
            this._syncGroupCheckboxes();
        });
    },

    /**
     * Sync checked / indeterminate state for all group-header checkboxes.
     * Called after every render cycle.
     */
    _syncGroupCheckboxes() {
        if (!this.rootRef || !this.rootRef.el) {
            return;
        }
        const resModel = this.props.list?.resModel;
        if (!resModel || !resModel.startsWith("pbms.")) {
            return;
        }
        const checkboxes = this.rootRef.el.querySelectorAll(
            "tr.o_group_header .o_pbms_group_checkbox"
        );
        checkboxes.forEach((cb) => {
            // Walk up to find the matching group row so we can identify the group.
            // The data-group-id attribute is on the <tr>.
            const tr = cb.closest("tr.o_group_header");
            if (!tr) return;
            const groupId = tr.dataset.groupId;
            if (!groupId) return;

            // Find the group in the list model
            const groups = this.props.list.groups || [];
            const group = groups.find((g) => String(g.id) === String(groupId));
            if (!group || !group.list || !group.list.records) return;

            const records = group.list.records;
            if (!records.length) {
                cb.checked = false;
                cb.indeterminate = false;
                return;
            }
            const selectedCount = records.filter((r) => r.selected).length;
            if (selectedCount === 0) {
                cb.checked = false;
                cb.indeterminate = false;
            } else if (selectedCount === records.length) {
                cb.checked = true;
                cb.indeterminate = false;
            } else {
                cb.checked = false;
                cb.indeterminate = true;
            }
        });
    },

    /**
     * Called when the user clicks the checkbox on a group header row.
     * Selects or deselects every child record in that group.
     *
     * @param {MouseEvent} ev
     * @param {Group}      group
     */
    onGroupCheckboxChange(ev, group) {
        ev.stopPropagation();
        if (!this.canSelectRecord) {
            return;
        }
        if (!group || !group.list || !group.list.records) {
            return;
        }
        const records = group.list.records;
        if (!records.length) {
            return;
        }
        // If all are selected → deselect all; otherwise → select all
        const allSelected = records.every((rec) => rec.selected);
        const targetState = !allSelected;
        for (const record of records) {
            if (record.selected !== targetState) {
                record.toggleSelection(targetState);
            }
        }
    },

    /**
     * True when every record in the group is selected.
     * Used in the template for the initial `checked` attribute.
     */
    isGroupFullySelected(group) {
        if (!group || !group.list || !group.list.records || !group.list.records.length) {
            return false;
        }
        return group.list.records.every((rec) => rec.selected);
    },

    /**
     * True when some (but not all) records in the group are selected.
     * Used in the template for the initial `data-indeterminate` attribute
     * (actual `indeterminate` JS property is set in _syncGroupCheckboxes).
     */
    isGroupPartiallySelected(group) {
        if (!group || !group.list || !group.list.records || !group.list.records.length) {
            return false;
        }
        const records = group.list.records;
        const selectedCount = records.filter((rec) => rec.selected).length;
        return selectedCount > 0 && selectedCount < records.length;
    },
});
