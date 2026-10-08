/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { MonetaryField } from "@web/views/fields/monetary/monetary_field";
import { FloatField } from "@web/views/fields/float/float_field";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { registry } from "@web/core/registry";
import { currencies } from "@web/core/currency";
import { patch } from "@web/core/utils/patch";
import { formatFloat } from "@web/core/utils/numbers";
import { parseMonetary } from "@web/views/fields/parsers";
import { FormStatusIndicator } from "@web/views/form/form_status_indicator/form_status_indicator";
import { onWillDestroy, useEffect, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Clear "Br" / ETB symbol in currencies cache so frontend monetary formatters do not prepend Br
for (const id in currencies) {
    if (currencies[id] && (currencies[id].symbol === "Br" || currencies[id].name === "ETB")) {
        currencies[id].symbol = "";
    }
}

function parsePbmsRecordId(val) {
    if (!val) return false;
    if (typeof val === "number") return val;
    if (Array.isArray(val) && val.length) {
        return parsePbmsRecordId(val[0]);
    }
    if (typeof val === "object") {
        if (typeof val.id === "number") return val.id;
        if (typeof val.resId === "number") return val.resId;
        if (val.id) return parsePbmsRecordId(val.id);
    }
    const n = parseInt(val, 10);
    return isNaN(n) ? false : n;
}

function parsePbmsRecordName(val) {
    if (!val) return "";
    if (Array.isArray(val) && val.length > 1) {
        return String(val[1] || "");
    }
    if (typeof val === "object") {
        return String(val.displayName || val.display_name || val.name || "");
    }
    return String(val);
}

// ---------------------------------------------------------------------------
// Integer vs monetary display of planning figures.
//
// Mirrors the form view: Workforce and Fixed Asset figures are always counts;
// Deposit, Customer Base, FX, Digital Banking and General Expense are counts
// only when their configured measurement basis is not monetary
// (is_<category>_monetary on the record).
// ---------------------------------------------------------------------------
// PBMS_PURE_BEGIN
const PBMS_MONETARY_FLAG = {
    deposit: "is_deposit_monetary",
    customer_base: "is_customer_base_monetary",
    fx: "is_fx_monetary",
    digital_banking: "is_digital_banking_monetary",
    general_expense: "is_expense_monetary",
};
// Measurement basis shipped in the planning config defaults; used only when no
// record is available to read the flag from (e.g. a collapsed group header).
const PBMS_INTEGER_BY_DEFAULT = new Set(["manpower", "fixed_asset", "customer_base", "digital_banking"]);
const PBMS_PLANNING_VALUE_RE =
    /^(m0[1-9]|m1[0-2]|quarter[1-4]_total|annual_total|opening_balance|proposed_annual_total|approved_annual_total|variance_amount|rollup_q[1-4]_total)$/;
// Universal Q1-Q4 rollups hold a COST for these categories, so they stay monetary.
const PBMS_ROLLUP_RE = /^rollup_q[1-4]_total$/;
const PBMS_ROLLUP_MONETARY_CATEGORIES = new Set(["manpower", "fixed_asset"]);
const PBMS_CASCADABLE_CATEGORIES = new Set([
    "deposit",
    "customer_base",
    "digital_banking",
    "fx",
]);
const PBMS_SUMMARY_RE = /^(deposit|customer_base|fx|digital_banking|expense)_(proposed_total|approved_total|annual_total|q[1-4]_total)$/;
const PBMS_SUMMARY_CATEGORY = {
    deposit: "deposit",
    customer_base: "customer_base",
    fx: "fx",
    digital_banking: "digital_banking",
    expense: "general_expense",
};

const PBMS_PLANNING_MODELS = new Set([
    "pbms.planning.category",
    "pbms.plan.category.line",
    "pbms.existing.manpower.summary",
    "pbms.existing.employee.line",
    "pbms.annual.plan",
    "pbms.plan.version",
]);

const PBMS_INTEGER_HEADCOUNT_FIELDS = new Set([
    "quantity",
    "display_approved_annual_total",
    "fulfillment_promotion",
    "fulfillment_transfer",
    "fulfillment_lateral",
    "fulfillment_external",
    "fulfillment_total",
    "fulfillment_balance",
    "manpower_total_headcount",
    "manpower_approved_headcount",
    "manpower_total_promotion",
    "manpower_total_transfer",
    "manpower_total_lateral",
    "manpower_total_external",
    "manpower_total_fulfillment",
    "manpower_fulfillment_balance",
    "manpower_line_count",
    "existing_total_active",
    "existing_total_authorized",
    "active_staff_count",
    "vacant_count",
    "existing_establishment",
    "total_establishment",
    "approved_plan_count",
    "active_employee_count",
    "vacant_position_count",
]);

function pbmsIsGroup(source) {
    return Boolean(source) && !source.data && Boolean(source.aggregates || source.groupByField);
}

function pbmsGroupDomain(group) {
    try {
        let dom = typeof group.groupDomain === "function" ? group.groupDomain() : group.groupDomain;
        if (!dom && group.list?.domain) {
            dom = group.list.domain;
        }
        if (dom && typeof dom.toList === "function") {
            return dom.toList();
        }
        return Array.isArray(dom) ? dom : [];
    } catch (e) {
        return [];
    }
}

function pbmsGroupAncestorsDomain(group) {
    const domain = [];
    let curr = group;
    while (curr) {
        if (curr.groupByField?.name && curr.value !== undefined && curr.value !== false) {
            const fieldName = curr.groupByField.name;
            const val = Array.isArray(curr.value) ? curr.value[0] : curr.value;
            domain.push([fieldName, "=", val]);
        }
        curr = curr.parent || curr.parentGroup || curr.list?.parentGroup || curr.list?.parent;
    }
    return domain;
}

function pbmsGroupFirstRecordData(group) {
    return group?.list?.records?.[0]?.data;
}

function pbmsCategoryOf(source, list) {
    if (pbmsIsGroup(source)) {
        const gname = source.groupByField?.name;
        if ((gname === "category" || gname === "line_type") && typeof source.value === "string") {
            return source.value;
        }
        for (const term of pbmsGroupAncestorsDomain(source)) {
            if (Array.isArray(term) && (term[0] === "category" || term[0] === "line_type") && term[1] === "=" && term[2]) {
                return term[2];
            }
        }
        for (const term of pbmsGroupDomain(source)) {
            if (Array.isArray(term) && (term[0] === "category" || term[0] === "line_type") && term[1] === "=" && term[2]) {
                return term[2];
            }
        }
        const firstData = pbmsGroupFirstRecordData(source);
        const fromRecord = firstData?.category || firstData?.line_type;
        if (fromRecord) {
            return fromRecord;
        }
        return list?.context?.default_category || list?.context?.default_line_type;
    }
    return (
        source?.data?.category ||
        source?.data?.line_type ||
        source?.context?.default_category ||
        source?.context?.default_line_type ||
        list?.context?.default_category ||
        list?.context?.default_line_type ||
        source?.model?.env?.searchModel?.context?.default_category ||
        source?.model?.env?.searchModel?.context?.default_line_type
    );
}

function pbmsCategoryIsInteger(category, data) {
    if (!category) {
        return false;
    }
    if (category === "manpower" || category === "fixed_asset") {
        return true;
    }
    if (data && data.line_type && typeof data.is_monetary === "boolean") {
        return !data.is_monetary;
    }
    const flag = PBMS_MONETARY_FLAG[category];
    if (!flag) {
        return false;
    }
    if (data && typeof data[flag] === "boolean") {
        return !data[flag];
    }
    return PBMS_INTEGER_BY_DEFAULT.has(category);
}

/**
 * @param source a record, or a group (group header / footer aggregate)
 */
function isIntegerPlanningValue(source, fieldName, list) {
    if (!fieldName) {
        return false;
    }
    if (PBMS_INTEGER_HEADCOUNT_FIELDS.has(fieldName)) {
        return true;
    }
    let category;
    const summary = PBMS_SUMMARY_RE.exec(fieldName);
    if (summary) {
        category = PBMS_SUMMARY_CATEGORY[summary[1]];
    } else if (PBMS_PLANNING_VALUE_RE.test(fieldName)) {
        category = pbmsCategoryOf(source, list);
        if (PBMS_ROLLUP_RE.test(fieldName) && PBMS_ROLLUP_MONETARY_CATEGORIES.has(category)) {
            return false;
        }
    } else {
        return false;
    }
    const data = pbmsIsGroup(source) ? pbmsGroupFirstRecordData(source) : source?.data;
    return pbmsCategoryIsInteger(category, data);
}

function planningSources(list) {
    if (!list) {
        return [];
    }
    if (list.isGrouped && Array.isArray(list.groups)) {
        return list.groups;
    }
    return list.records || [];
}

/** A footer total is shown as a count only if every row/group it adds up is a count. */
function isIntegerForSources(sources, fieldName, list) {
    if (!sources.length) {
        return isIntegerPlanningValue(undefined, fieldName, list);
    }
    return sources.every((source) => isIntegerPlanningValue(source, fieldName, list));
}

/**
 * True when the rows/groups behind a footer total mix counts and amounts.
 * Adding a headcount to a Birr amount is meaningless, so such a total is
 * left blank instead of showing a wrong number.
 */
function isMixedForSources(sources, fieldName, list) {
    if (sources.length < 2) {
        return false;
    }
    const kinds = new Set(sources.map((source) => isIntegerPlanningValue(source, fieldName, list)));
    return kinds.size > 1;
}
// PBMS_PURE_END

/**
 * Patch FloatField to respect integer format (0 decimal places) for PBMS integer & headcount fields in edit/view modes.
 */
patch(FloatField.prototype, {
    get formattedValue() {
        const resModel = this.props?.record?.resModel || "";
        if (PBMS_PLANNING_MODELS.has(resModel)) {
            const fieldName = this.props?.name;
            if (fieldName && isIntegerPlanningValue(this.props.record, fieldName, this.props.list)) {
                if (typeof this.value === "number") {
                    return formatFloat(this.value, { digits: [16, 0] });
                }
            }
        }
        return super.formattedValue;
    },

    parse(value) {
        const resModel = this.props?.record?.resModel || "";
        if (PBMS_PLANNING_MODELS.has(resModel)) {
            const fieldName = this.props?.name;
            if (fieldName && isIntegerPlanningValue(this.props.record, fieldName, this.props.list)) {
                const parsed = super.parse(value);
                return typeof parsed === "number" && !isNaN(parsed) ? Math.round(parsed) : parsed;
            }
        }
        return super.parse(value);
    },
});

/**
 * Patch MonetaryField to strip "Br" and non-breaking space prefix/suffix across
 * all PBMS and monetary fields in list, form, and kanban views, and format integer categories without decimals.
 */
patch(MonetaryField.prototype, {
    get inputOptions() {
        const resModel = this.props?.record?.resModel || "";
        if (PBMS_PLANNING_MODELS.has(resModel)) {
            const fieldName = this.props?.name;
            if (fieldName && isIntegerPlanningValue(this.props.record, fieldName, this.props.list)) {
                return {
                    getValue: () => this.formattedValue,
                    refName: "numpadDecimal",
                    parse: (v) => {
                        const parsed = parseMonetary(v, { allowOperation: true });
                        return typeof parsed === "number" && !isNaN(parsed) ? Math.round(parsed) : parsed;
                    },
                };
            }
        }
        return super.inputOptions;
    },

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
        const resModel = this.props?.record?.resModel || "";
        if (PBMS_PLANNING_MODELS.has(resModel)) {
            const fieldName = this.props?.name;
            if (fieldName && isIntegerPlanningValue(this.props.record, fieldName, this.props.list)) {
                if (typeof this.value === "number") {
                    return formatFloat(this.value, { digits: [16, 0] });
                }
            }
        }
        let val = super.formattedValue;
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

    parse(value) {
        const resModel = this.props?.record?.resModel || "";
        if (PBMS_PLANNING_MODELS.has(resModel)) {
            const fieldName = this.props?.name;
            if (fieldName && isIntegerPlanningValue(this.props.record, fieldName, this.props.list)) {
                const parsed = super.parse(value);
                return typeof parsed === "number" && !isNaN(parsed) ? Math.round(parsed) : parsed;
            }
        }
        return super.parse(value);
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

const PBMS_FA_QUARTER_RE = /^quarter([1-4])_total$/;

const PBMS_SOURCING_FIELDS = new Set([
    "manpower_total_promotion",
    "manpower_total_transfer",
    "manpower_total_lateral",
    "manpower_total_external",
    "manpower_total_fulfillment",
    "manpower_fulfillment_balance",
]);


/**
 * Group-header total for a PBMS planning column: whole number when the group's
 * category is a count (Workforce, Fixed Asset, count-based Customer Base ...),
 * 2 decimals when it is an amount. Returns undefined when it does not apply.
 */
function pbmsGroupAggregateText(renderer, group, column) {
    const resModel = renderer.props.list?.resModel || "";
    if (!PBMS_PLANNING_MODELS.has(resModel) || !group?.aggregates) {
        return undefined;
    }
    // Fixed-asset quarters live in fa_q1..fa_q4 (quantities), not in the grouped quarter sums.
    if (
        resModel === "pbms.plan.category.line"
        && PBMS_FA_QUARTER_RE.test(column.name)
        && pbmsCategoryOf(group, renderer.props.list) === "fixed_asset"
    ) {
        return "";
    }
    const raw = group.aggregates[column.name];
    if (typeof raw !== "number") {
        return undefined;
    }
    if (!PBMS_PLANNING_VALUE_RE.test(column.name) && !PBMS_SUMMARY_RE.test(column.name)) {
        return undefined;
    }
    const isInteger = isIntegerPlanningValue(group, column.name, renderer.props.list);
    return formatFloat(raw, { digits: isInteger ? [16, 0] : [16, 2] });
}

/**
 * Patch ListRenderer to respect integer types (0 decimals), options="{'no_symbol': True}",
 * and strip currency prefix (such as 'Br ') from footer column aggregates,
 * group aggregates, and record cell values across PBMS views.
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this._pbmsDestroyed = false;
        onWillDestroy(() => {
            this._pbmsDestroyed = true;
        });
        try {
            this.actionService = useService("action");
        } catch (e) {
            this.actionService = null;
        }
        try {
            this.user = useService("user");
        } catch (e) {
            this.user = null;
        }
        this.pbmsState = useState({ updateKey: 0 });
        this._pbmsUserRoles = {
            isManager: false,
            isPeopleSolutions: false,
            isCpco: false,
            isDistrictReviewer: false,
            isHoReviewer: false,
            isApprover: false,
            isChief: false,
            isCommittee: false,
            isCeo: false,
        };
        if (this.user) {
            Promise.all([
                this.user.hasGroup("bunna_pbms.group_pbms_manager"),
                this.user.hasGroup("bunna_pbms.group_pbms_people_solutions"),
                this.user.hasGroup("bunna_pbms.group_pbms_cpco"),
                this.user.hasGroup("bunna_pbms.group_pbms_district_reviewer"),
                this.user.hasGroup("bunna_pbms.group_pbms_ho_reviewer"),
                this.user.hasGroup("bunna_pbms.group_pbms_approver"),
                this.user.hasGroup("bunna_pbms.group_pbms_respective_chief"),
                this.user.hasGroup("bunna_pbms.group_pbms_budget_hiring_committee"),
                this.user.hasGroup("bunna_pbms.group_pbms_ceo"),
                this.user.hasGroup("base.group_system"),
            ]).then(([mgr, ps, cpco, dist, ho, appr, chief, comm, ceo, sys]) => {
                const isAdmin = Boolean(mgr || sys);
                this._pbmsUserRoles = {
                    isManager: isAdmin,
                    isPeopleSolutions: Boolean(ps),
                    isCpco: Boolean(cpco),
                    isDistrictReviewer: Boolean(dist),
                    isHoReviewer: Boolean(ho),
                    isApprover: Boolean(appr),
                    isChief: Boolean(chief),
                    isCommittee: Boolean(comm),
                    isCeo: Boolean(ceo),
                };
                if (!this._pbmsDestroyed) {
                    this.pbmsState.updateKey++;
                }
            }).catch(() => {});
        }
    },

    get hasOpenFormViewColumn() {
        const resModel = this.props.list?.resModel || "";
        if (resModel === "pbms.planning.category") {
            return false;
        }
        return super.hasOpenFormViewColumn;
    },

    isRecordReadonly(record) {
        const resModel = this.props.list?.resModel || "";
        if (resModel === "pbms.planning.category" && record.data?.can_edit_content === false) {
            return true;
        }
        return super.isRecordReadonly(...arguments);
    },

    isCellReadonly(column, record) {
        const resModel = this.props.list?.resModel || "";
        if (
            resModel === "pbms.planning.category"
            && PBMS_SOURCING_FIELDS.has(column.name)
            && record.data?.can_edit_sourcing_fields === false
        ) {
            return true;
        }
        return super.isCellReadonly(...arguments);
    },

    formatAggregateValue(group, column) {
        const planningText = pbmsGroupAggregateText(this, group, column);
        if (planningText !== undefined) {
            return planningText;
        }
        return super.formatAggregateValue ? super.formatAggregateValue(...arguments) : "";
    },

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
                isIntegerForSources(planningSources(this.props.list), fieldName, this.props.list) ||
                fieldType === "integer" ||
                column.widget === "integer" ||
                /headcount|promotion|transfer|lateral|external|fulfillment|count|quantity/i.test(fieldName)
            );

            if (
                PBMS_PLANNING_MODELS.has(resModel)
                && isMixedForSources(planningSources(this.props.list), fieldName, this.props.list)
            ) {
                aggregates[fieldName].value = "";
                continue;
            }

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
        const planningText = pbmsGroupAggregateText(this, group, column);
        if (planningText !== undefined) {
            return { ...super.formatGroupAggregate(...arguments), value: planningText };
        }
        const res = super.formatGroupAggregate(...arguments);
        const resModel = this.props.list?.resModel || "";
        const isPbms = resModel.startsWith("pbms.") || resModel.startsWith("bunna.");
        const hasNoSymbol = Boolean(column.options?.no_symbol || column.options?.noSymbol);

        if (hasNoSymbol || isPbms) {
            const field = this.fields?.[column.name];
            const fieldType = column.fieldType || field?.type;
            const isInteger = (
                isIntegerPlanningValue(group, column.name, this.props.list) ||
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

        if (resModel === "pbms.plan.category.line" && record.data?.line_type === "fixed_asset") {
            const fa = PBMS_FA_QUARTER_RE.exec(column.name);
            if (fa) {
                return formatFloat(record.data?.[`fa_q${fa[1]}`] || 0, { digits: [16, 0] });
            }
        }
        if (PBMS_PLANNING_MODELS.has(resModel) && isIntegerPlanningValue(record, column.name, this.props.list)) {
            const rawValue = record.data?.[column.name];
            if (typeof rawValue === "number") {
                return formatFloat(rawValue, { digits: [16, 0] });
            }
        }

        if ((hasNoSymbol || isPbms) && typeof val === "string") {
            val = val
                .replace(/^[\s\u00a0]*Br[\s\u00a0]*/i, "")
                .replace(/[\s\u00a0]*Br[\s\u00a0]*$/i, "")
                .trim();
        }
        return val;
    },

    hasPbmsGroupSelector(group) {
        if (!this.hasSelectors) {
            return false;
        }
        const resModel = this.props.list?.resModel || "";
        if (!resModel.startsWith("pbms.")) {
            return false;
        }
        return Boolean(group?.groupByField?.name);
    },

    getGroupRecords(group) {
        if (!group) {
            return [];
        }
        if (group.list?.isGrouped && group.list?.groups) {
            return group.list.groups.flatMap((childGroup) => this.getGroupRecords(childGroup));
        }
        return group.list?.records || [];
    },

    isGroupSelected(group) {
        const records = this.getGroupRecords(group);
        if (!records.length) {
            return false;
        }
        return records.every((r) => r.selected);
    },

    isGroupIndeterminate(group) {
        const records = this.getGroupRecords(group);
        if (!records.length) {
            return false;
        }
        const hasSelected = records.some((r) => r.selected);
        const hasUnselected = records.some((r) => !r.selected);
        return hasSelected && hasUnselected;
    },

    async ensureGroupRecordsLoaded(group) {
        if (group.isFolded) {
            await group.toggle();
        }
        if (group.list?.isGrouped && group.list?.groups) {
            for (const childGroup of group.list.groups) {
                await this.ensureGroupRecordsLoaded(childGroup);
            }
        }
    },

    async toggleGroupSelection(group) {
        if (!this.canSelectRecord) {
            return;
        }
        const isSelected = this.isGroupSelected(group);
        const targetState = !isSelected;
        await this.ensureGroupRecordsLoaded(group);
        if (this._pbmsDestroyed) {
            return;
        }
        const records = this.getGroupRecords(group);
        if (this.props.list?.model?.mutex) {
            await this.props.list.model.mutex.exec(async () => {
                for (const record of records) {
                    record._toggleSelection(targetState);
                }
            });
            this.props.list.model.notify();
        } else {
            for (const record of records) {
                record.toggleSelection(targetState);
            }
        }
    },

    isPbmsOperatingUnitGroup(group) {
        const resModel = this.props.list?.resModel || "";
        if (resModel !== "pbms.plan.category.line") {
            return false;
        }
        const fieldName = group?.groupByField?.name;
        if (!fieldName) {
            return false;
        }
        if (fieldName === "line_type" || fieldName === "category") {
            if (group.list?.isGrouped && group.list?.groups?.length) {
                return false;
            }
            return true;
        }
        if (["source_unit_id", "org_unit_id", "operating_unit_id"].includes(fieldName)) {
            if (group.list?.isGrouped && group.list?.groups?.length) {
                const childField = group.list.groups[0]?.groupByField?.name;
                if (childField === "line_type" || childField === "category") {
                    return false;
                }
            }
            return true;
        }
        return false;
    },

    getPbmsGroupPlanInfo(group) {
        if (this.pbmsState) {
            const _ = this.pbmsState.updateKey;
        }
        if (group._pbmsPlanInfo) {
            return group._pbmsPlanInfo;
        }
        const records = this.getGroupRecords(group);
        if (records.length && records[0]?.data) {
            const d = records[0].data;
            const planId = parsePbmsRecordId(d.plan_id) || records[0].resId || parsePbmsRecordId(d.id);
            const planName = parsePbmsRecordName(d.plan_id) || records[0].data?.display_name || "";
            if (planId) {
                group._pbmsPlanInfo = {
                    planId,
                    planName,
                    requestNumber: d.request_number,
                    state: d.plan_state || d.state,
                    category: d.plan_cat || d.category || d.line_type,
                    canUseReviewerActions: Boolean(d.plan_can_use_reviewer_actions || d.can_use_reviewer_actions),
                    canUseReviewerWizards: Boolean(d.plan_can_use_reviewer_wizards || d.can_use_reviewer_wizards),
                    canChiefReview: Boolean(d.plan_can_chief_review || d.can_chief_review),
                    canSubmitPlan: Boolean(d.plan_can_submit_plan || d.can_submit_plan),
                    canDistrictReview: Boolean(d.plan_can_district_review || d.can_district_review),
                    canHoReview: Boolean(d.plan_can_ho_review || d.can_ho_review),
                    canPeopleSolutionsReview: Boolean(d.plan_can_people_solutions_review || d.can_people_solutions_review),
                    canCpcoReview: Boolean(d.plan_can_cpco_review || d.can_cpco_review),
                    canCommitteeReview: Boolean(d.plan_can_committee_review || d.can_committee_review),
                    canCeoApprove: Boolean(d.plan_can_ceo_approve || d.can_ceo_approve),
                    canHoEndorse: Boolean(d.plan_can_ho_endorse || d.can_ho_endorse),
                    canCpcoEndorse: Boolean(d.plan_can_cpco_endorse || d.can_cpco_endorse),
                    canDeletePlan: Boolean(d.plan_can_delete_plan || d.can_delete_plan),
                    isCycleOpen: Boolean(d.plan_is_cycle_open || d.is_cycle_open),
                    isDistrictUnit: Boolean(d.plan_is_district_unit || d.is_district_unit),
                    isHeadOfficeUnit: Boolean(d.plan_is_head_office_unit || d.is_head_office_unit),
                    hasCascadedTargets: Boolean(d.plan_has_cascaded_targets || d.has_cascaded_targets),
                    isTargetsCascaded: Boolean(d.plan_is_targets_cascaded || d.is_targets_cascaded),
                    orgUnitType: d.org_unit_type || d.work_unit_type,
                };
                return group._pbmsPlanInfo;
            }
        }
        if (!group._pbmsPlanInfoLoading && !group._pbmsPlanInfo && group.value) {
            group._pbmsPlanInfoLoading = true;
            const val = Array.isArray(group.value) ? group.value[0] : group.value;
            const groupDom = pbmsGroupDomain(group);
            const ancestorDom = pbmsGroupAncestorsDomain(group);
            const searchDomain = [["plan_id", "!=", false]];
            if (groupDom && groupDom.length) {
                for (const d of groupDom) {
                    if (Array.isArray(d) && d.length === 3) {
                        searchDomain.push(d);
                    }
                }
            }
            if (ancestorDom && ancestorDom.length) {
                for (const d of ancestorDom) {
                    if (Array.isArray(d) && d.length === 3 && !searchDomain.some(sd => Array.isArray(sd) && sd[0] === d[0])) {
                        searchDomain.push(d);
                    }
                }
            }
            const fieldName = group.groupByField?.name || "source_unit_id";
            if (!searchDomain.some(d => Array.isArray(d) && d[0] === fieldName)) {
                searchDomain.push([fieldName, "=", val]);
            }
            const cat = pbmsCategoryOf(group, this.props.list) || this.props.list?.context?.default_line_type || this.props.list?.context?.default_category;
            if (cat && !searchDomain.some(d => Array.isArray(d) && (d[0] === "line_type" || d[0] === "category"))) {
                searchDomain.push(["line_type", "=", cat]);
            }
            if (this.props.list?.domain && Array.isArray(this.props.list.domain)) {
                for (const d of this.props.list.domain) {
                    if (Array.isArray(d) && d.length === 3 && !searchDomain.some(sd => Array.isArray(sd) && sd[0] === d[0])) {
                        searchDomain.push(d);
                    }
                }
            }
            this.orm.searchRead(
                "pbms.plan.category.line",
                searchDomain,
                [
                    "plan_id", "plan_state", "plan_cat",
                    "plan_can_use_reviewer_actions", "plan_can_use_reviewer_wizards",
                    "plan_can_chief_review", "plan_can_submit_plan",
                    "plan_can_district_review", "plan_can_ho_review",
                    "plan_can_people_solutions_review", "plan_can_cpco_review",
                    "plan_can_committee_review", "plan_can_ceo_approve",
                    "plan_can_ho_endorse", "plan_can_cpco_endorse",
                    "plan_can_delete_plan",
                    "plan_is_cycle_open", "plan_is_district_unit",
                    "plan_is_head_office_unit", "plan_has_cascaded_targets",
                    "plan_is_targets_cascaded", "org_unit_type", "request_number"
                ],
                { limit: 1 }
            ).then((res) => {
                if (this._pbmsDestroyed) {
                    return;
                }
                if (res && res.length) {
                    const d = res[0];
                    const planId = parsePbmsRecordId(d.plan_id);
                    const planName = parsePbmsRecordName(d.plan_id);
                    if (planId) {
                        group._pbmsPlanInfo = {
                            planId,
                            planName,
                            requestNumber: d.request_number,
                            state: d.plan_state,
                            category: d.plan_cat,
                            canUseReviewerActions: Boolean(d.plan_can_use_reviewer_actions),
                            canUseReviewerWizards: Boolean(d.plan_can_use_reviewer_wizards),
                            canChiefReview: Boolean(d.plan_can_chief_review),
                            canSubmitPlan: Boolean(d.plan_can_submit_plan),
                            canDistrictReview: Boolean(d.plan_can_district_review),
                            canHoReview: Boolean(d.plan_can_ho_review),
                            canPeopleSolutionsReview: Boolean(d.plan_can_people_solutions_review),
                            canCpcoReview: Boolean(d.plan_can_cpco_review),
                            canCommitteeReview: Boolean(d.plan_can_committee_review),
                            canCeoApprove: Boolean(d.plan_can_ceo_approve),
                            canHoEndorse: Boolean(d.plan_can_ho_endorse),
                            canCpcoEndorse: Boolean(d.plan_can_cpco_endorse),
                            canDeletePlan: Boolean(d.plan_can_delete_plan),
                            isCycleOpen: Boolean(d.plan_is_cycle_open),
                            isDistrictUnit: Boolean(d.plan_is_district_unit),
                            isHeadOfficeUnit: Boolean(d.plan_is_head_office_unit),
                            hasCascadedTargets: Boolean(d.plan_has_cascaded_targets),
                            isTargetsCascaded: Boolean(d.plan_is_targets_cascaded),
                            orgUnitType: d.org_unit_type,
                        };
                        if (this.pbmsState && !this._pbmsDestroyed) {
                            this.pbmsState.updateKey++;
                        }
                    }
                }
            }).catch(() => {});
        }
        return null;
    },

    async reloadPbmsListIfMounted() {
        if (this._pbmsDestroyed) {
            return;
        }
        try {
            await this.props.list?.model?.root?.load?.();
        } catch (error) {
            // Dialog close or navigation may destroy the view during a grouped reload.
            if (!this._pbmsDestroyed) {
                throw error;
            }
        }
    },

    getPbmsStateLabel(state) {
        const labels = {
            draft: _t("Draft"),
            submitted: _t("Submitted"),
            info_requested: _t("Info Requested"),
            returned: _t("Returned"),
            district_approved: _t("District Approved"),
            district_endorsed: _t("District Endorsed"),
            chief_review: _t("Chief Review"),
            people_solutions_review: _t("People Solutions Review"),
            cpco_review: _t("CPCO Review"),
            committee_review: _t("Committee Review"),
            ceo_approval: _t("CEO Approval"),
            ho_reviewed: _t("HO Reviewed"),
            ho_endorse: _t("HO Endorsed"),
            cpco_endorse: _t("CPCO Endorsed"),
            approved: _t("Approved"),
            rejected: _t("Rejected"),
        };
        return labels[state] || state || "";
    },

    getPbmsStateBadgeClass(state) {
        if (state === "approved") {
            return "badge-pbms-approved";
        }
        if (["returned", "rejection_recommended", "rejected"].includes(state)) {
            return "badge-pbms-rejected";
        }
        if (state === "info_requested") {
            return "badge-pbms-revision";
        }
        if (state === "draft") {
            return "badge-pbms-draft";
        }
        return "badge-pbms-in-review";
    },

    checkPbmsUserRoles() {
        if (!this._pbmsUserRoles) {
            this._pbmsUserRoles = {
                isManager: false,
                isPeopleSolutions: false,
                isCpco: false,
                isDistrictReviewer: false,
                isHoReviewer: false,
                isApprover: false,
                isChief: false,
                isCommittee: false,
                isCeo: false,
            };
        }
        return this._pbmsUserRoles;
    },

    getPbmsGroupButtons(group, plan) {
        if (this.pbmsState) {
            const _ = this.pbmsState.updateKey;
        }
        if (!plan) {
            return [];
        }
        const state = plan.state;
        const cat = plan.category;
        const roles = this.checkPbmsUserRoles();

        // In approved or rejected state, show export, cascade (for approved HO consolidate or district), delete, and open
        if (state === "approved" || state === "rejected") {
            const finalButtons = [];
            finalButtons.push({
                id: "export",
                label: _t("Export"),
                icon: "fa-file-excel-o",
                className: "btn btn-pbms-export btn-sm",
                title: _t("Export Plan to Excel"),
            });
            const isHoPlan = Boolean(
                plan.isHeadOfficeUnit ||
                plan.orgUnitType === "head_office" ||
                plan.workUnitType === "head_office" ||
                (plan.planName && (plan.planName.toLowerCase().includes("head office") || plan.planName.toLowerCase().includes("retail operation"))) ||
                (group.value && (String(group.value).toLowerCase().includes("retail operation") || String(group.value).toLowerCase().includes("head office") || String(group.value).toLowerCase().includes("ceo office")))
            );
            if (state === "approved" && isHoPlan && PBMS_CASCADABLE_CATEGORIES.has(cat)) {
                if (plan.isTargetsCascaded) {
                    finalButtons.push({
                        id: "already_cascaded",
                        label: _t("Cascaded"),
                        icon: "fa-check-circle",
                        className: "btn btn-outline-success btn-sm disabled",
                        title: _t("Targets have already been cascaded to districts."),
                    });
                } else {
                    finalButtons.push({
                        id: "cascade_ho",
                        label: _t("Cascade Targets to Districts"),
                        icon: "fa-share-alt",
                        className: "btn btn-pbms-cascade btn-sm",
                        title: _t("Cascade Approved Corporate Targets to Districts"),
                    });
                }
            }
            const isDistrictPlan = Boolean(
                plan.isDistrictUnit ||
                plan.orgUnitType === "district_office" ||
                plan.workUnitType === "district_office" ||
                (plan.planName && plan.planName.toLowerCase().includes("district"))
            );
            if (state === "approved" && isDistrictPlan && PBMS_CASCADABLE_CATEGORIES.has(cat) && plan.hasCascadedTargets) {
                if (plan.isTargetsCascaded) {
                    finalButtons.push({
                        id: "already_cascaded",
                        label: _t("Cascaded"),
                        icon: "fa-check-circle",
                        className: "btn btn-outline-success btn-sm disabled",
                        title: _t("Targets have already been cascaded to branches."),
                    });
                } else {
                    finalButtons.push({
                        id: "cascade_district",
                        label: _t("Cascade Targets to Branches"),
                        icon: "fa-share-alt",
                        className: "btn btn-pbms-cascade btn-sm",
                        title: _t("Cascade Targets to Branches"),
                    });
                }
            }
            if (roles.isManager) {
                finalButtons.push({
                    id: "delete",
                    label: _t("Delete"),
                    icon: "fa-trash",
                    className: "btn btn-pbms-delete btn-sm",
                    title: _t("Delete Plan"),
                });
            }
            finalButtons.push({
                id: "open",
                label: _t("Open"),
                icon: "fa-external-link",
                className: "btn btn-pbms-open btn-sm",
                title: _t("Open Plan"),
            });
            return finalButtons;
        }

        const buttons = [];

        // 1. Export Excel (available for all authenticated viewers)
        buttons.push({
            id: "export",
            label: _t("Export"),
            icon: "fa-file-excel-o",
            className: "btn btn-pbms-export btn-sm",
            title: _t("Export Plan to Excel"),
        });

        // 2. Primary workflow action: Strictly visible ONLY to the specific role responsible
        // for the CURRENT stage, AND hidden once the stage has passed ("after above").
        if (state === "people_solutions_review" && cat === "manpower" && plan.canPeopleSolutionsReview) {
            buttons.push({
                id: "escalate_cpco",
                label: _t("Escalate to CPCO"),
                icon: "fa-share-square-o",
                className: "btn btn-pbms-escalate btn-sm",
                title: _t("Assess & Escalate to CPCO"),
            });
        } else if (state === "cpco_review" && cat === "manpower" && plan.canCpcoReview) {
            buttons.push({
                id: "submit_committee",
                label: _t("Submit to Committee"),
                icon: "fa-users",
                className: "btn btn-pbms-committee btn-sm",
                title: _t("Submit to Budget Hiring Committee"),
            });
        } else if (state === "committee_review" && plan.canCommitteeReview) {
            if (cat === "manpower") {
                buttons.push({
                    id: "endorse_ceo",
                    label: _t("Endorse to CEO"),
                    icon: "fa-check-circle",
                    className: "btn btn-pbms-approve btn-sm",
                    title: _t("Endorse to CEO"),
                });
            } else if (cat === "fixed_asset") {
                buttons.push({
                    id: "committee_approve",
                    label: _t("Approve Asset"),
                    icon: "fa-check-circle",
                    className: "btn btn-pbms-approve btn-sm",
                    title: _t("Committee Final Approve"),
                });
            } else if (cat === "initiative_budget") {
                buttons.push({
                    id: "committee_approve",
                    label: _t("Approve Initiative"),
                    icon: "fa-check-circle",
                    className: "btn btn-pbms-approve btn-sm",
                    title: _t("Committee Final Approve"),
                });
            }
        } else if (state === "ceo_approval" && cat === "manpower" && plan.canCeoApprove) {
            buttons.push({
                id: "ceo_approve",
                label: _t("CEO Final Approve"),
                icon: "fa-check-square",
                className: "btn btn-pbms-final-approve btn-sm",
                title: _t("CEO Final Approve"),
            });
        } else if (state === "chief_review" && plan.canChiefReview) {
            buttons.push({
                id: "chief_approve",
                label: _t("Chief Approve & Escalate"),
                icon: "fa-check-circle",
                className: "btn btn-pbms-approve btn-sm",
                title: _t("Chief Approve & Escalate"),
            });
        } else if (["submitted", "info_requested"].includes(state) && plan.canDistrictReview) {
            if (!plan.isDistrictUnit && !plan.isHeadOfficeUnit) {
                buttons.push({
                    id: "district_approve",
                    label: _t("District Approve"),
                    icon: "fa-check-circle",
                    className: "btn btn-pbms-approve btn-sm",
                    title: _t("District Approve"),
                });
            } else if (plan.isDistrictUnit) {
                buttons.push({
                    id: "endorse_ho",
                    label: _t("Endorse to HO"),
                    icon: "fa-send",
                    className: "btn btn-pbms-endorse btn-sm",
                    title: _t("Endorse to Head Office"),
                });
            }
        } else if (plan.isDistrictUnit && state === "district_approved" && plan.canDistrictReview) {
            buttons.push({
                id: "endorse_ho",
                label: _t("Endorse to HO"),
                icon: "fa-send",
                className: "btn btn-pbms-endorse btn-sm",
                title: _t("Endorse to Head Office"),
            });
        } else if (plan.canHoReview && !(["deposit", "customer_base", "fx", "digital_banking"].includes(cat) && !plan.isDistrictUnit && !plan.isHeadOfficeUnit) && (
            (["district_approved", "district_endorsed", "ho_reviewed"].includes(state)) ||
            (plan.isHeadOfficeUnit && ["submitted", "info_requested"].includes(state))
        )) {
            if (cat === "fixed_asset" || cat === "initiative_budget") {
                buttons.push({
                    id: "submit_committee",
                    label: _t("Submit to Committee"),
                    icon: "fa-users",
                    className: "btn btn-pbms-approve btn-sm",
                    title: _t("Submit to Budget Hiring Committee"),
                });
            } else if (cat !== "manpower") {
                buttons.push({
                    id: "final_approve",
                    label: _t("Final Approve"),
                    icon: "fa-check-square-o",
                    className: "btn btn-pbms-final-approve btn-sm",
                    title: _t("Final Approve"),
                });
            }
        } else if (state === "ho_endorse" && cat === "manpower" && plan.canHoEndorse) {
            buttons.push({
                id: "ho_endorse",
                label: _t("Endorse to CPCO"),
                icon: "fa-check-circle",
                className: "btn btn-pbms-endorse btn-sm",
                title: _t("Endorse to CPCO"),
            });
        } else if (state === "cpco_endorse" && cat === "manpower" && plan.canCpcoEndorse) {
            buttons.push({
                id: "cpco_endorse",
                label: _t("Endorse to Operations"),
                icon: "fa-check-circle",
                className: "btn btn-pbms-endorse btn-sm",
                title: _t("Endorse to People Operations & Management"),
            });
        } else if (["draft", "returned"].includes(state) && plan.canSubmitPlan && plan.isCycleOpen) {
            buttons.push({
                id: "submit",
                label: _t("Submit"),
                icon: "fa-paper-plane",
                className: "btn btn-pbms-submit btn-sm",
                title: _t("Submit Plan"),
            });
        }

        // 3. Reviewer wizard actions: Strictly visible ONLY if the user is authorized to review
        // the CURRENT active stage. Once the plan advances ("after above"), reviewers of earlier
        // stages can NO LONGER comment, request info, return, or reject.
        const isMobilizationCategory = ["deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"].includes(cat);
        const isHoEligibleReview = Boolean(
            plan.canHoReview &&
            !(isMobilizationCategory && !plan.isDistrictUnit && !plan.isHeadOfficeUnit) &&
            ((["district_approved", "district_endorsed", "ho_reviewed"].includes(state)) ||
             (plan.isHeadOfficeUnit && ["submitted", "info_requested"].includes(state))) &&
            cat !== "manpower"
        );
        const isDistrictEligibleReview = Boolean(
            (["submitted", "info_requested"].includes(state) && plan.canDistrictReview) ||
            (plan.isDistrictUnit && state === "district_approved" && plan.canDistrictReview)
        );
        const canReviewCurrentStage = Boolean(
            (state === "people_solutions_review" && plan.canPeopleSolutionsReview) ||
            (state === "cpco_review" && plan.canCpcoReview) ||
            (state === "committee_review" && plan.canCommitteeReview) ||
            (state === "ceo_approval" && plan.canCeoApprove) ||
            (state === "chief_review" && plan.canChiefReview) ||
            isDistrictEligibleReview ||
            isHoEligibleReview
        );

        if (canReviewCurrentStage && (plan.canUseReviewerActions || plan.canUseReviewerWizards)) {
            buttons.push({
                id: "comment",
                label: _t("Comment"),
                icon: "fa-commenting-o",
                className: "btn btn-pbms-comment btn-sm",
                title: _t("Add Review Comment"),
            });
            buttons.push({
                id: "request_info",
                label: _t("Request Info"),
                icon: "fa-question-circle",
                className: "btn btn-pbms-request-info btn-sm",
                title: _t("Request Information"),
            });
            buttons.push({
                id: "return",
                label: _t("Return"),
                icon: "fa-undo",
                className: "btn btn-pbms-return btn-sm",
                title: _t("Return for Revision"),
            });
            buttons.push({
                id: "reject",
                label: _t("Reject"),
                icon: "fa-ban",
                className: "btn btn-pbms-reject btn-sm",
                title: _t("Reject Plan"),
            });
        }

        // 4. Delete button for SPPMD Administrator (or planner in draft state)
        if (roles.isManager || (plan.canDeletePlan && state === "draft")) {
            buttons.push({
                id: "delete",
                label: _t("Delete"),
                icon: "fa-trash",
                className: "btn btn-outline-danger btn-sm",
                title: _t("Delete Plan"),
            });
        }

        // 5. Open
        buttons.push({
            id: "open",
            label: _t("Open"),
            icon: "fa-external-link",
            className: "btn btn-pbms-open btn-sm",
            title: _t("Open Plan Form"),
        });

        return buttons;
    },

    async onPbmsGroupButtonClick(group, plan, btn) {
        const rawPlanId = parsePbmsRecordId(plan?.planId || plan);
        if (!rawPlanId) {
            return;
        }
        const planId = rawPlanId;
        if (btn.id === "export") {
            const action = await this.orm.call("pbms.planning.category", "action_export_excel", [[planId]]);
            if (action) {
                await this.actionService.doAction(action);
            }
            return;
        }
        if (btn.id === "open") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "pbms.planning.category",
                res_id: planId,
                views: [[false, "form"]],
                target: "current",
            });
            return;
        }
        if (btn.id === "cascade_ho") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Cascade Targets to Districts"),
                res_model: "pbms.target.cascade.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    default_cascade_level: "ho_to_district",
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }
        if (btn.id === "cascade_district") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Cascade Targets to Branches"),
                res_model: "pbms.target.cascade.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    default_cascade_level: "district_to_branch",
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }
        if (btn.id === "already_cascaded") {
            const res = await this.orm.call("pbms.planning.category", "action_already_cascaded_notice", [[planId]]);
            if (res && typeof res === "object") {
                await this.actionService.doAction(res);
            }
            return;
        }
        if (btn.id === "delete") {
            const confirmed = window.confirm(_t("Are you sure you want to delete this plan? This action cannot be undone."));
            if (!confirmed) {
                return;
            }
            await this.orm.unlink("pbms.planning.category", [planId]);
            await this.reloadPbmsListIfMounted();
            return;
        }
        if (btn.id === "comment") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Plan Review Comment"),
                res_model: "pbms.review.comment.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }
        if (btn.id === "request_info") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Request Information"),
                res_model: "pbms.request.info.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }
        if (btn.id === "return") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Return Plan for Revision"),
                res_model: "pbms.return.revision.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }
        if (btn.id === "reject") {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: _t("Reject Plan"),
                res_model: "pbms.reject.wizard",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_plan_id: planId,
                    active_id: planId,
                    active_ids: [planId],
                    active_model: "pbms.planning.category",
                },
            }, {
                onClose: () => this.reloadPbmsListIfMounted(),
            });
            return;
        }

        const methodMap = {
            escalate_cpco: "action_people_solutions_escalate_cpco",
            submit_committee: (plan.category === "fixed_asset" || plan.category === "initiative_budget") ? "action_submit_to_committee" : "action_cpco_submit_to_committee",
            district_approve: plan.category === "manpower" ? "action_district_approve_workforce" : "action_district_approve",
            endorse_ho: "action_district_approve",
            chief_approve: "action_chief_approve_escalate",
            endorse_ceo: "action_committee_approve",
            committee_approve: "action_committee_approve_resource",
            ceo_approve: "action_ceo_approve",
            final_approve: "action_ho_approve",
            ho_endorse: "action_ho_endorse_to_cpco",
            cpco_endorse: "action_cpco_endorse_to_solutions",
            submit: "action_submit",
        };

        const method = methodMap[btn.id];
        if (method) {
            const res = await this.orm.call("pbms.planning.category", method, [[planId]]);
            if (res && typeof res === "object") {
                await this.actionService.doAction(res);
            }
            await this.reloadPbmsListIfMounted();
        }
    },
});


/**
 * Patch FormStatusIndicator so that the custom header Save button(s)
 * appear when editing or creating a record, and disappear when saved or clean.
 */
patch(FormStatusIndicator.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(
            () => {
                const isEditingOrCreate = Boolean(
                    this.props.model?.root?.isNew || this.displayButtons
                );
                const formEl =
                    this.saveButton?.el?.closest(".o_form_view_container, .o_form_view, .o_content, .o_action_manager") ||
                    document.querySelector(".o_form_view_container, .o_form_view");
                if (formEl) {
                    formEl.classList.toggle("o_form_is_editing", isEditingOrCreate);
                    formEl.classList.toggle("o_form_is_saved", !isEditingOrCreate);
                    const saveBtns = formEl.querySelectorAll(
                        'button[name="action_save_plan"], button[name="action_save_request"], .o_pbms_save_btn'
                    );
                    for (const btn of saveBtns) {
                        btn.classList.toggle("d-none", !isEditingOrCreate);
                    }
                }
            },
            () => [this.props.model?.root?.isNew, this.displayButtons, this.indicatorMode, this.state.fieldIsDirty]
        );
    },
});


/**
 * Patch Many2OneField to dynamically filter out already-planned items (e.g. Savings Deposit)
 * from dropdown autocomplete options in real-time as lines are added in PBMS plan forms.
 */
patch(Many2OneField.prototype, {
    get m2oProps() {
        const props = super.m2oProps;
        try {
            const record = this.props.record;
            const fieldName = this.props.name;
            if (!record || record.resModel !== "pbms.plan.category.line") {
                return props;
            }

            const TRACKED_FIELDS = [
                "deposit_type_id",
                "channel_id",
                "fx_source_type",
                "expense_account_id",
                "category_id",
                "credit_portfolio_item_id",
                "loan_product_id"
            ];
            if (!TRACKED_FIELDS.includes(fieldName)) {
                return props;
            }

            const parent = record.model?.root;
            if (!parent || !parent.data) {
                return props;
            }

            // District and Head Office plans consolidate branch lines and allow duplicates
            const unitType = parent.data.org_unit_type || parent.data.work_unit_type;
            if (unitType === "district_office" || unitType === "head_office" || unitType === "regional_office") {
                return props;
            }

            // Search for sibling lines in the parent's One2many lists that contain this record
            const usedIds = [];
            for (const key in parent.data) {
                const val = parent.data[key];
                if (val && typeof val === "object" && Array.isArray(val.records)) {
                    const containsCurrent = val.records.some((r) => r.id === record.id);
                    if (containsCurrent) {
                        for (const sibling of val.records) {
                            if (sibling.id !== record.id) {
                                const sibVal = sibling.data?.[fieldName];
                                let sibId = false;
                                if (Array.isArray(sibVal) && sibVal.length) {
                                    sibId = sibVal[0];
                                } else if (sibVal && typeof sibVal === "object" && typeof sibVal.id === "number") {
                                    sibId = sibVal.id;
                                } else if (typeof sibVal === "number") {
                                    sibId = sibVal;
                                }
                                if (sibId && !usedIds.includes(sibId)) {
                                    usedIds.push(sibId);
                                }
                            }
                        }
                        break;
                    }
                }
            }

            if (usedIds.length > 0) {
                const origDomainFn = props.domain;
                props.domain = () => {
                    const baseDomain = typeof origDomainFn === "function" ? origDomainFn() : (origDomainFn || []);
                    return [...baseDomain, ["id", "not in", usedIds]];
                };
            }
        } catch (err) {
            console.warn("[PBMS] Dynamic Many2one domain evaluation error:", err);
        }
        return props;
    },
});


/**
 * Detect the currently active notebook page category from DOM tabs
 */
function getActivePlanningCategoryFromDom() {
    const activeTabLink = document.querySelector(
        ".o_notebook .nav-link.active, .o_notebook [role='tab'][aria-selected='true'], .o_notebook .nav-item .active"
    );
    if (!activeTabLink) return null;

    const pageName = activeTabLink.getAttribute("name") || "";
    const pageText = (activeTabLink.innerText || "").trim().toLowerCase();

    if (pageName === "page_fixed_asset" || pageText.includes("fixed asset")) {
        return "fixed_asset";
    }
    if (
        pageName === "page_manpower" ||
        pageName === "page_manpower_request" ||
        pageName === "page_existing_manpower" ||
        pageName === "page_people_solutions_review" ||
        pageName === "page_cpco_review" ||
        pageText.includes("workforce") ||
        pageText.includes("manpower")
    ) {
        return "manpower";
    }
    if (pageName === "page_expense" || pageText.includes("general expense") || pageText.includes("expense")) {
        return "general_expense";
    }
    if (pageName === "page_deposit" || pageText.includes("deposit mobilization") || pageText.includes("deposit")) {
        return "deposit";
    }
    if (pageName === "page_customer_base" || pageText.includes("customer base")) {
        return "customer_base";
    }
    if (pageName === "page_fx" || pageText.includes("fx mobilization") || pageText.includes("fx")) {
        return "fx";
    }
    if (pageName === "page_digital_banking" || pageText.includes("digital banking")) {
        return "digital_banking";
    }
    if (pageName === "page_credit_portfolio" || pageText.includes("credit portfolio")) {
        return "credit_portfolio";
    }
    if (pageName === "page_initiative_budget" || pageText.includes("initiative budget")) {
        return "initiative_budget";
    }
    if (pageName === "page_loan_disbursement" || pageText.includes("loan disbursement")) {
        return "loan_disbursement_collection";
    }
    if (pageName === "page_loan_outstanding" || pageText.includes("loan & advances") || pageText.includes("loan outstanding")) {
        return "loan_outstanding";
    }
    return null;
}

/**
 * Patch action service so that clicking Export or Import from anywhere on the plan form
 * automatically detects the active notebook tab category and passes it to the Python backend.
 */
const actionServiceDef = registry.category("services").get("action");
if (actionServiceDef && actionServiceDef.start) {
    const origActionStart = actionServiceDef.start;
    actionServiceDef.start = function (env) {
        const actionManager = origActionStart.apply(this, arguments);
        const origDoActionButton = actionManager.doActionButton;
        actionManager.doActionButton = async function (params, options) {
            if (
                params &&
                (params.name === "action_export_excel" || params.name === "action_open_import_wizard") &&
                params.resModel === "pbms.planning.category"
            ) {
                const activeCat = getActivePlanningCategoryFromDom();
                if (activeCat) {
                    params.context = Object.assign({}, params.context, {
                        target_category: activeCat,
                        active_category: activeCat,
                        active_tab_category: activeCat,
                    });
                }
            }
            return origDoActionButton.call(this, params, options);
        };
        return actionManager;
    };
}


