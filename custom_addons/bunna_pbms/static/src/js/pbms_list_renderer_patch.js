/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { MonetaryField } from "@web/views/fields/monetary/monetary_field";
import { registry } from "@web/core/registry";
import { currencies } from "@web/core/currency";
import { patch } from "@web/core/utils/patch";
import { formatFloat } from "@web/core/utils/numbers";

// Clear "Br" / ETB symbol in currencies cache so frontend monetary formatters do not prepend Br
for (const id in currencies) {
    if (currencies[id] && (currencies[id].symbol === "Br" || currencies[id].name === "ETB")) {
        currencies[id].symbol = "";
    }
}

/**
 * Patch MonetaryField to strip "Br" and non-breaking space prefix/suffix across
 * all PBMS and monetary fields in list, form, and kanban views.
 */
patch(MonetaryField.prototype, {
    get currencySymbol() {
        const sym = super.currencySymbol;
        if (sym === "Br" || sym === "ETB") {
            return "";
        }
        const resModel = this.props?.record?.resModel || "";
        if (resModel.startsWith("pbms.") || resModel.startsWith("bunna.")) {
            return "";
        }
        return sym;
    },

    get formattedValue() {
        let val = super.formattedValue;
        const resModel = this.props?.record?.resModel || "";
        const isPbms = resModel.startsWith("pbms.") || resModel.startsWith("bunna.");
        if (isPbms || this.props?.hideSymbol || this.currencySymbol === "") {
            if (typeof val === "string") {
                val = val
                    .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                    .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
                    .trim();
            }
        }
        return val;
    },
});

// Wrap registry monetary formatter to guarantee any widget or field using it has "Br" stripped
const originalFormatMonetary = registry.category("formatters").get("monetary");
if (originalFormatMonetary) {
    registry.category("formatters").add(
        "monetary",
        function (value, options = {}) {
            let res = originalFormatMonetary(value, options);
            if (typeof res === "string") {
                res = res
                    .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                    .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
                    .trim();
            }
            return res;
        },
        { force: true }
    );
}

/**
 * Patch ListRenderer to respect integer types (0 decimals), options="{'no_symbol': True}",
 * and strip currency prefix (such as 'Br ') from footer column aggregates,
 * group aggregates, and record cell values across PBMS views.
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

            const field = this.fields?.[fieldName];
            const fieldType = column.fieldType || field?.type;
            const isInteger = (
                fieldType === "integer" ||
                column.widget === "integer" ||
                /headcount|promotion|transfer|lateral|external|fulfillment|count|quantity/i.test(fieldName)
            );

            const hasNoSymbol = Boolean(column.options?.no_symbol || column.options?.noSymbol);
            if (hasNoSymbol || isPbms) {
                const raw = aggregates[fieldName].rawValue;
                if (typeof raw === "number") {
                    let digits = isInteger ? [16, 0] : [16, 2];
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
                        .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                        .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
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
            const field = this.fields?.[column.name];
            const fieldType = column.fieldType || field?.type;
            const isInteger = (
                fieldType === "integer" ||
                column.widget === "integer" ||
                /headcount|promotion|transfer|lateral|external|fulfillment|count|quantity/i.test(column.name)
            );

            const raw = group.aggregates[column.name];
            if (typeof raw === "number") {
                let digits = isInteger ? [16, 0] : [16, 2];
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
                        .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                        .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
                        .trim(),
                };
            }
        }

        return res;
    },

    getFormattedValue(column, record) {
        let val = super.getFormattedValue(...arguments);
        const resModel = this.props.list?.resModel || "";
        const isPbms = resModel.startsWith("pbms.") || resModel.startsWith("bunna.");
        const hasNoSymbol = Boolean(column.options?.no_symbol || column.options?.noSymbol);

        if ((hasNoSymbol || isPbms) && typeof val === "string") {
            val = val
                .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
                .trim();
        }
        return val;
    },
});
