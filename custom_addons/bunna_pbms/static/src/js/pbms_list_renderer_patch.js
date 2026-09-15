/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { patch } from "@web/core/utils/patch";
import { formatFloat } from "@web/core/utils/numbers";

/**
 * Patch ListRenderer to respect options="{'no_symbol': True}" and strip currency
 * prefix (such as 'Br ') from footer column aggregates and group aggregates for PBMS views.
 */
patch(ListRenderer.prototype, {
    computeAggregates() {
        const aggregates = super.computeAggregates(...arguments);
        const resModel = this.props.list?.resModel || "";
        const isPbms = resModel.startsWith("pbms.") || resModel.startsWith("bunna.");

        for (const column of this.columns) {
            const fieldName = column.name;
            if (!aggregates[fieldName]) {
                continue;
            }

            const hasNoSymbol = Boolean(column.options?.no_symbol || column.options?.noSymbol);
            if (hasNoSymbol || isPbms) {
                const raw = aggregates[fieldName].rawValue;
                if (typeof raw === "number") {
                    let digits = [16, 2];
                    if (column.attrs?.digits) {
                        try {
                            const parsed = JSON.parse(column.attrs.digits);
                            if (Array.isArray(parsed)) {
                                digits = parsed;
                            } else if (typeof parsed === "number") {
                                digits = [16, parsed];
                            }
                        } catch (e) {}
                    } else if (column.options?.digits) {
                        if (Array.isArray(column.options.digits)) {
                            digits = column.options.digits;
                        } else if (typeof column.options.digits === "number") {
                            digits = [16, column.options.digits];
                        }
                    }
                    aggregates[fieldName].value = formatFloat(raw, { digits });
                } else if (typeof aggregates[fieldName].value === "string") {
                    aggregates[fieldName].value = aggregates[fieldName].value
                        .replace(/^Br\s*/i, "")
                        .replace(/\s*Br$/i, "")
                        .trim();
                }
            }
        }

        return aggregates;
    },

    formatGroupAggregate(group, column) {
        const res = super.formatGroupAggregate(...arguments);
        const resModel = this.props.list?.resModel || "";
        const isPbms = resModel.startsWith("pbms.") || resModel.startsWith("bunna.");
        const hasNoSymbol = Boolean(column.options?.no_symbol || column.options?.noSymbol);

        if (hasNoSymbol || isPbms) {
            const raw = group.aggregates[column.name];
            if (typeof raw === "number") {
                let digits = [16, 2];
                if (column.attrs?.digits) {
                    try {
                        const parsed = JSON.parse(column.attrs.digits);
                        if (Array.isArray(parsed)) {
                            digits = parsed;
                        } else if (typeof parsed === "number") {
                            digits = [16, parsed];
                        }
                    } catch (e) {}
                } else if (column.options?.digits) {
                    if (Array.isArray(column.options.digits)) {
                        digits = column.options.digits;
                    } else if (typeof column.options.digits === "number") {
                        digits = [16, column.options.digits];
                    }
                }
                return {
                    ...res,
                    value: formatFloat(raw, { digits }),
                };
            } else if (typeof res?.value === "string") {
                return {
                    ...res,
                    value: res.value
                        .replace(/^Br\s*/i, "")
                        .replace(/\s*Br$/i, "")
                        .trim(),
                };
            }
        }

        return res;
    },
});
