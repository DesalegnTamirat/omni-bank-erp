/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

patch(DynamicGroupList.prototype, {
    get records() {
        return this.groups
            .filter((group) => !group.isFolded || (group.records && group.records.some((r) => r.selected)))
            .map((group) => group.records)
            .flat();
    },
});

patch(ListRenderer.prototype, {
    getGroupNameCellColSpan(group) {
        let colspan = super.getGroupNameCellColSpan(group);
        if (this.hasSelectors && colspan > 1) {
            colspan--;
        }
        return colspan;
    },

    isGroupSelected(group) {
        if (this.props.list?.isDomainSelected) {
            return true;
        }
        const records = group.list?.records;
        if (records && records.length > 0) {
            return records.every((r) => r.selected);
        }
        return Boolean(group._selected);
    },

    isGroupIndeterminate(group) {
        if (this.props.list?.isDomainSelected) {
            return false;
        }
        const records = group.list?.records;
        if (records && records.length > 0) {
            const some = records.some((r) => r.selected);
            const all = records.every((r) => r.selected);
            return some && !all;
        }
        return false;
    },

    async toggleGroupSelection(group) {
        const isAll = this.isGroupSelected(group);
        const targetState = !isAll;

        if (group.isFolded && (!group.list?.records || !group.list.records.length)) {
            await group.list.load();
        }

        const records = group.list?.records || [];
        if (records.length) {
            const mutex = this.props.list?.model?.mutex || group.list?.model?.mutex;
            if (mutex) {
                await mutex.exec(() => {
                    for (const record of records) {
                        record._toggleSelection(targetState);
                    }
                });
            } else {
                for (const record of records) {
                    record.toggleSelection(targetState);
                }
            }
        }
        group._selected = targetState;
    },
});
