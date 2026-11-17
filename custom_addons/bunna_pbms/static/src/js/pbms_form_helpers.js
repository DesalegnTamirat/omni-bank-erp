/** @odoo-module **/

import { FormStatusIndicator } from "@web/views/form/form_status_indicator/form_status_indicator";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { NavBar } from "@web/webclient/navbar/navbar";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useEffect } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

/**
 * Automatically tag PBMS views and top navbar with scoping classes so custom styling
 * is strictly limited to bunna_pbms and never leaks into other modules.
 */
function isPbmsModel(resModel) {
    return Boolean(resModel && typeof resModel === "string" && resModel.startsWith("pbms."));
}

function checkIsPbmsApp(env, currentApp) {
    const app = currentApp || env?.services?.menu?.getCurrentApp();
    if (app?.xmlid && app.xmlid.startsWith("bunna_pbms")) {
        return true;
    }
    const brand = document.querySelector(".o_menu_brand");
    const brandText = brand ? (brand.textContent || "").trim() : "";
    if (brandText.includes("Plan & Budget") || brandText.includes("PBMS")) {
        return true;
    }
    // Only check current active navbar section items, never global apps drawer
    if (document.querySelector(".o_menu_sections [data-menu-xmlid^='bunna_pbms.']")) {
        return true;
    }
    return false;
}

patch(NavBar.prototype, {
    setup() {
        super.setup(...arguments);
        const updatePbmsNavbarScope = () => {
            const isPbms = checkIsPbmsApp(this.env, this.currentApp);
            document.body.classList.toggle("o_pbms_app", isPbms);
            const navbarEl = this.root?.el || document.querySelector(".o_main_navbar, .o_navbar");
            if (navbarEl) {
                navbarEl.classList.toggle("o_pbms_navbar", isPbms);
            }
        };
        useEffect(
            () => {
                updatePbmsNavbarScope();
            },
            () => [this.currentApp]
        );
    },
});

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(() => {
            const isPbms = isPbmsModel(this.props.resModel);
            if (isPbms) {
                document.body.classList.add("o_pbms_app");
            } else if (!checkIsPbmsApp(this.env)) {
                document.body.classList.remove("o_pbms_app");
            }
        }, () => [this.props.resModel]);
    },
    get className() {
        const res = super.className;
        if (isPbmsModel(this.props.resModel)) {
            if (typeof res === "string") {
                return (res + " o_pbms_form o_pbms_view").trim();
            }
            return Object.assign({}, res, { o_pbms_form: true, o_pbms_view: true });
        }
        return res;
    },
    async beforeExecuteActionButton(clickParams) {
        this._pbmsExecutingAction = true;
        try {
            return await super.beforeExecuteActionButton(...arguments);
        } finally {
            setTimeout(() => {
                this._pbmsExecutingAction = false;
            }, 400);
        }
    },
    async save(params) {
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (isPbms) {
            this._pbmsWasNew = Boolean(this.model.root.isNew);
        }
        try {
            return await super.save(...arguments);
        } catch (error) {
            if (isPbms) {
                const errorMsg = error?.data?.message || error?.message || _t("Save operation failed.");
                this.env.services.notification.add(errorMsg, {
                    title: _t("Save Failed"),
                    type: "danger",
                    sticky: false,
                });
            }
            throw error;
        }
    },
    async onRecordSaved(record, changes) {
        await super.onRecordSaved(...arguments);
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (isPbms && !this._pbmsExecutingAction) {
            const wasNew = Boolean(this._pbmsWasNew || !record.resId);
            this._pbmsWasNew = false;
            const title = wasNew ? _t("Created Successfully") : _t("Updated Successfully");
            const message = wasNew
                ? _t("Record created successfully.")
                : _t("Record updated successfully.");
            this.env.services.notification.add(message, {
                title: title,
                type: "success",
                sticky: false,
            });
        }
    },
    async onSaveError(error, options, leaving) {
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (isPbms) {
            const errorMsg = error?.data?.message || error?.message || _t("Save operation failed.");
            this.env.services.notification.add(errorMsg, {
                title: _t("Save Failed"),
                type: "danger",
                sticky: false,
            });
        }
        return super.onSaveError(...arguments);
    },
    get deleteConfirmationDialogProps() {
        const props = super.deleteConfirmationDialogProps;
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (!isPbms) {
            return props;
        }
        const origConfirm = props.confirm;
        return {
            ...props,
            confirm: async () => {
                try {
                    await origConfirm();
                    this.env.services.notification.add(_t("Record deleted successfully."), {
                        title: _t("Deleted Successfully"),
                        type: "success",
                        sticky: false,
                    });
                } catch (err) {
                    const msg = err.data?.message || err.message || _t("Could not delete record.");
                    this.env.services.notification.add(msg, {
                        title: _t("Deletion Failed"),
                        type: "danger",
                        sticky: false,
                    });
                    throw err;
                }
            },
        };
    },
});

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(() => {
            const isPbms = isPbmsModel(this.props.resModel);
            if (isPbms) {
                document.body.classList.add("o_pbms_app");
            } else if (!checkIsPbmsApp(this.env)) {
                document.body.classList.remove("o_pbms_app");
            }
        }, () => [this.props.resModel]);
    },
    get className() {
        const res = super.className;
        if (isPbmsModel(this.props.resModel)) {
            if (typeof res === "string") {
                return (res + " o_pbms_list o_pbms_view").trim();
            }
            return Object.assign({}, res, { o_pbms_list: true, o_pbms_view: true });
        }
        return res;
    },
    async onRecordSaved(record) {
        await super.onRecordSaved(...arguments);
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (isPbms) {
            this.env.services.notification.add(_t("Record updated successfully."), {
                title: _t("Updated Successfully"),
                type: "success",
                sticky: false,
            });
        }
    },
    get deleteConfirmationDialogProps() {
        const props = super.deleteConfirmationDialogProps;
        const isPbms = isPbmsModel(this.props.resModel) || checkIsPbmsApp(this.env);
        if (!isPbms) {
            return props;
        }
        return {
            ...props,
            confirm: async () => {
                try {
                    await this.model.root.deleteRecords();
                    this.env.services.notification.add(_t("Record(s) deleted successfully."), {
                        title: _t("Deleted Successfully"),
                        type: "success",
                        sticky: false,
                    });
                } catch (err) {
                    const msg = err.data?.message || err.message || _t("Could not delete record(s).");
                    this.env.services.notification.add(msg, {
                        title: _t("Deletion Failed"),
                        type: "danger",
                        sticky: false,
                    });
                    throw err;
                }
            },
        };
    },
});

patch(KanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(() => {
            const isPbms = isPbmsModel(this.props.resModel);
            if (isPbms) {
                document.body.classList.add("o_pbms_app");
            } else if (!checkIsPbmsApp(this.env)) {
                document.body.classList.remove("o_pbms_app");
            }
        }, () => [this.props.resModel]);
    },
    get className() {
        const res = super.className;
        if (isPbmsModel(this.props.resModel)) {
            if (typeof res === "string") {
                return (res + " o_pbms_kanban o_pbms_view").trim();
            }
            return Object.assign({}, res, { o_pbms_kanban: true, o_pbms_view: true });
        }
        return res;
    },
});

/**
 * Patch FormStatusIndicator so that the custom header Save button(s)
 * appear when editing or creating a record in form view (PBMS ONLY).
 */
patch(FormStatusIndicator.prototype, {
    setup() {
        super.setup(...arguments);
        useEffect(
            () => {
                const resModel = this.props.model?.root?.resModel;
                if (!resModel || !resModel.startsWith("pbms.")) {
                    return;
                }
                const isEditingOrCreate = Boolean(
                    this.props.model?.root?.isNew || this.displayButtons
                );
                const formEl =
                    this.saveButton?.el?.closest(".o_form_view_container, .o_form_view, .o_content, .o_action_manager") ||
                    document.querySelector(".o_form_view.o_pbms_form, .o_pbms_form");
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
 * Patch Many2OneField to dynamically filter out already-planned items
 * from autocomplete dropdown options in real-time as lines are added in PBMS plan forms.
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

            const unitType = parent.data.org_unit_type || parent.data.work_unit_type;
            if (unitType === "district_office" || unitType === "head_office" || unitType === "regional_office") {
                return props;
            }

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

function resolveCategoryFromTextOrName(name, text) {
    const sName = (name || "").toLowerCase();
    const sText = (text || "").toLowerCase();
    if (sName.includes("customer_base") || sText.includes("customer base")) return "customer_base";
    if (sName.includes("deposit") || sText.includes("deposit")) return "deposit";
    if (sName.includes("fx") || sText.includes("fx")) return "fx";
    if (sName.includes("digital") || sText.includes("digital")) return "digital_banking";
    if (sName.includes("expense") || sText.includes("expense")) return "general_expense";
    if (sName.includes("manpower") || sName.includes("workforce") || sText.includes("manpower") || sText.includes("workforce")) return "manpower";
    if (sName.includes("fixed_asset") || sText.includes("fixed asset")) return "fixed_asset";
    if (sName.includes("credit_portfolio") || sText.includes("credit portfolio") || sText.includes("income plan")) return "credit_portfolio";
    if (sName.includes("initiative") || sText.includes("initiative")) return "initiative_budget";
    if (sName.includes("loan_disbursement") || sText.includes("disbursement")) return "loan_disbursement_collection";
    if (sName.includes("loan_outstanding") || sText.includes("outstanding") || sText.includes("advances")) return "loan_outstanding";
    return null;
}

if (typeof window !== "undefined") {
    window._pbmsLastActiveTabCategory = null;
    document.addEventListener("click", (ev) => {
        const tabEl = ev.target.closest(".o_notebook .nav-link, .o_notebook [role='tab'], .o_notebook .nav-item, .o_notebook .nav-link button");
        if (tabEl) {
            const name = tabEl.getAttribute("name") || tabEl.getAttribute("data-name") || "";
            const text = (tabEl.innerText || "").trim();
            const cat = resolveCategoryFromTextOrName(name, text);
            if (cat) {
                window._pbmsLastActiveTabCategory = cat;
            }
        }
    }, true);
}

function getActivePlanningCategoryFromDom() {
    // 1. Try active notebook nav link or tab button
    const activeTab = document.querySelector(
        ".o_notebook .nav-link.active, .o_notebook [role='tab'][aria-selected='true'], .o_notebook .nav-item .active"
    );
    if (activeTab) {
        const name = activeTab.getAttribute("name") || activeTab.getAttribute("data-name") || "";
        const text = (activeTab.innerText || "").trim();
        const cat = resolveCategoryFromTextOrName(name, text);
        if (cat) return cat;
    }

    // 2. Try active tab-pane
    const activePane = document.querySelector(".o_notebook .tab-pane.active");
    if (activePane) {
        const name = activePane.getAttribute("name") || "";
        const text = (activePane.getAttribute("string") || "").trim();
        const cat = resolveCategoryFromTextOrName(name, text);
        if (cat) return cat;
    }

    // 3. Fallback to tracked click
    if (typeof window !== "undefined" && window._pbmsLastActiveTabCategory) {
        return window._pbmsLastActiveTabCategory;
    }

    return null;
}

const actionServiceDef = registry.category("services").get("action");
if (actionServiceDef && actionServiceDef.start) {
    const origActionStart = actionServiceDef.start;
    actionServiceDef.start = function (env) {
        const actionManager = origActionStart.apply(this, arguments);
        const origDoActionButton = actionManager.doActionButton;
        const origDoAction = actionManager.doAction;

        actionManager.doAction = async function (action, options) {
            const res = await origDoAction.call(this, action, options);
            try {
                const currentApp = env.services.menu?.getCurrentApp();
                const isPbms = Boolean(
                    currentApp?.xmlid?.startsWith("bunna_pbms") ||
                    (typeof action === "object" && (
                        action?.res_model?.startsWith("pbms.") ||
                        action?.xml_id?.startsWith("bunna_pbms.")
                    ))
                );
                document.body.classList.toggle("o_pbms_app", isPbms);
                const navbarEl = document.querySelector(".o_main_navbar, .o_navbar");
                if (navbarEl) {
                    navbarEl.classList.toggle("o_pbms_navbar", isPbms);
                }
            } catch (_) {}
            return res;
        };

        actionManager.doActionButton = async function (params, options) {
            if (
                params &&
                (params.name === "action_export_excel" || params.name === "action_open_import_wizard") &&
                params.resModel === "pbms.planning.category"
            ) {
                const activeCat = getActivePlanningCategoryFromDom();
                if (activeCat) {
                    const extraCtx = {
                        target_category: activeCat,
                        active_category: activeCat,
                        active_tab_category: activeCat,
                        default_format_type: activeCat,
                        default_category: activeCat,
                    };
                    params.context = Object.assign({}, params.context, extraCtx);
                    if (params.buttonContext) {
                        params.buttonContext = Object.assign({}, params.buttonContext, extraCtx);
                    }
                }
            }
            const isPbms = Boolean(
                (params?.resModel && isPbmsModel(params.resModel)) ||
                checkIsPbmsApp(env)
            );
            if (!isPbms) {
                return origDoActionButton.call(this, params, options);
            }
            try {
                return await origDoActionButton.call(this, params, options);
            } catch (error) {
                const errorMsg = error?.data?.message || error?.message || _t("Action execution failed.");
                env.services.notification.add(errorMsg, {
                    title: _t("Action Failed"),
                    type: "danger",
                    sticky: false,
                });
                throw error;
            }
        };
        return actionManager;
    };
}

/**
 * -----------------------------------------------------------------------------
 * 1. Simple Dropdown Menus: lightweight toggling & outside click closing
 * Strictly scoped so it never breaks Odoo OWL navigation dropdowns.
 * -----------------------------------------------------------------------------
 */
document.addEventListener("click", (ev) => {
    // 1. Let Odoo's native OWL Dropdown component handle top navbar dropdowns
    if (ev.target.closest(".o_main_navbar, .o_menu_sections, .o_navbar, .o_menu_brand, .o_navbar_apps_menu")) {
        return;
    }

    // 2. Only handle form dropdowns inside PBMS
    const isPbms = document.querySelector(".o_pbms_form, .o_pbms_list, .o_pbms_view") || document.body.classList.contains("o_pbms_app");
    if (!isPbms) {
        return;
    }

    const toggle = ev.target.closest(
        ".o_pbms_form .dropdown-toggle, .o_pbms_form [data-bs-toggle='dropdown'], .o_pbms_view .dropdown-toggle, .o_pbms_view [data-bs-toggle='dropdown']"
    );
    const allOpenMenus = document.querySelectorAll(".o_pbms_form .dropdown-menu.show, .o_pbms_view .dropdown-menu.show");

    if (toggle) {
        const dropdownParent = toggle.closest(".dropdown, .o-dropdown, .o_dropdown");
        const menu = dropdownParent ? dropdownParent.querySelector(".dropdown-menu, .o-dropdown--menu") : null;
        if (menu) {
            ev.preventDefault();
            const isOpen = menu.classList.contains("show");
            allOpenMenus.forEach((m) => {
                if (m !== menu) {
                    m.classList.remove("show");
                    m.closest(".dropdown, .o-dropdown, .o_dropdown")?.classList.remove("show");
                }
            });
            if (!isOpen) {
                menu.classList.add("show");
                dropdownParent.classList.add("show");
            } else {
                menu.classList.remove("show");
                dropdownParent.classList.remove("show");
            }
            return;
        }
    }

    // Clicking outside any dropdown menu closes all open form menus
    if (!ev.target.closest(".dropdown-menu, .o-dropdown--menu")) {
        allOpenMenus.forEach((m) => {
            m.classList.remove("show");
            m.closest(".dropdown, .o-dropdown, .o_dropdown")?.classList.remove("show");
        });
    }
});

/**
 * -----------------------------------------------------------------------------
 * 2. Reject Special Characters: (@ # $ % & * ! ^ ( ) + = { } [ ] | \ / < > ? ~)
 * Allow letters, numbers, spaces, and decimal/thousand separators in PBMS inputs.
 * -----------------------------------------------------------------------------
 */
const PROHIBITED_CHARS_REGEX = /[@#$%&*!^()+={}[\]|\\/<>?~]/;

document.addEventListener(
    "keydown",
    (ev) => {
        const isPbms = document.querySelector(".o_pbms_form, .o_pbms_list, .o_pbms_view");
        const input = ev.target.closest(
            ".o_pbms_form input, .o_pbms_form textarea, .o_pbms_list input, .o_pbms_list textarea"
        ) || (isPbms ? ev.target.closest("input, textarea") : null);

        if (!input || ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1) {
            return;
        }

        if (PROHIBITED_CHARS_REGEX.test(ev.key)) {
            ev.preventDefault();
            ev.stopPropagation();
        }
    },
    true
);

document.addEventListener(
    "paste",
    (ev) => {
        const isPbms = document.querySelector(".o_pbms_form, .o_pbms_list, .o_pbms_view");
        const input = ev.target.closest(
            ".o_pbms_form input, .o_pbms_form textarea, .o_pbms_list input, .o_pbms_list textarea"
        ) || (isPbms ? ev.target.closest("input, textarea") : null);

        if (!input) return;
        const clipboardData = ev.clipboardData || window.clipboardData;
        if (!clipboardData) return;
        const pastedText = clipboardData.getData("text");
        if (PROHIBITED_CHARS_REGEX.test(pastedText)) {
            ev.preventDefault();
            const cleanText = pastedText.replace(/[@#$%&*!^()+={}[\]|\\/<>?~]/g, "");
            document.execCommand("insertText", false, cleanText);
        }
    },
    true
);
