/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Many2One, computeM2OProps } from "@web/views/fields/many2one/many2one";
import { Many2OneField, buildM2OFieldDescription } from "@web/views/fields/many2one/many2one_field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Open the assessment line's guidance form from its competency name. */
export class CompetencyGuideLink extends Component {
    static template = "competency_management.CompetencyGuideLink";
    static props = {
        ...standardFieldProps,
        method: { type: String, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busy = useState({ value: false });
    }

    get name() {
        return this.props.record.data[this.props.name]?.display_name || "";
    }

    async openGuide(event) {
        event.preventDefault();
        event.stopPropagation();
        if (this.busy.value) {
            return;
        }
        const record = this.props.record;
        const root = record.model.root;
        const competencyId = record.data.competency_id?.id;
        const relationName = ["core_line_ids", "leadership_line_ids", "technical_line_ids", "line_ids"]
            .find((name) => root.data?.[name]?.records?.includes(record));
        this.busy.value = true;
        try {
            if (relationName) {
                // Only an embedded one2many has a parent form record. Persist any
                // edited ratings and new lines through that form before opening
                // a separate action. This saves fields; it never submits the assessment.
                if ((!record.resId || (await root.isDirty())) && !(await root.save())) {
                    return;
                }
            }
            let resId = record.resId;
            if (!resId && relationName && competencyId) {
                const matches = root.data[relationName].records.filter(
                    (line) => line.data.competency_id?.id === competencyId && line.resId
                );
                if (matches.length === 1) {
                    resId = matches[0].resId;
                }
            }
            if (!resId) {
                this.notification.add(_t("Save this competency line before opening its details."), {
                    type: "warning",
                });
                return;
            }
            const action = await this.orm.call(
                record.resModel,
                this.props.method || "action_open_guide",
                [[resId]],
                { context: record.context }
            );
            await this.action.doAction(action, {
                onClose: () => relationName ? root.load() : record.load(),
            });
        } finally {
            this.busy.value = false;
        }
    }
}

registry.category("fields").add("competency_guide_link", {
    component: CompetencyGuideLink,
    displayName: _t("Competency guidance link"),
    supportedTypes: ["many2one"],
    extractProps: ({ options }) => ({ method: options.method || "action_open_guide" }),
});

/** Keep the role mapping's editable selector while making an existing name open guidance. */
export class CompetencyMappingGuide extends CompetencyGuideLink {
    static template = "competency_management.CompetencyMappingGuide";
    static components = { Many2One };
    static props = {
        ...Many2OneField.props,
        method: { type: String, optional: true },
    };

    setup() {
        super.setup();
        this.editing = useState({ value: false });
    }

    get pickerProps() {
        return {
            ...computeM2OProps(this.props),
            canOpen: false,
            update: async (value, options = {}) => {
                await this.props.record.update({ [this.props.name]: value }, options);
                this.editing.value = false;
            },
        };
    }

    startEditing(event) {
        event.preventDefault();
        event.stopPropagation();
        this.editing.value = true;
    }
}

registry.category("fields").add("competency_mapping_guide", {
    ...buildM2OFieldDescription(CompetencyMappingGuide),
    displayName: _t("Role competency guidance link"),
});

/** The entire behavioral indicator card is a rating choice. */
export class CompetencyLevelPicker extends Component {
    static template = "competency_management.CompetencyLevelPicker";
    static props = {
        ...standardFieldProps,
        level: String,
    };

    setup() {
        this.action = useService("action");
        this.busy = useState({ value: false });
    }

    get label() {
        return {
            1: _t("Level 1 — Basic"),
            2: _t("Level 2 — Intermediate"),
            3: _t("Level 3 — Advanced"),
            4: _t("Level 4 — Expert"),
        }[this.props.level];
    }

    get indicator() {
        return this.props.record.data[this.props.name] || "";
    }

    get canRate() {
        return Boolean(this.props.record.data.can_edit_ratings);
    }

    get isSelected() {
        return this.props.record.data.current_level === this.props.level;
    }

    async selectLevel(event) {
        event.preventDefault();
        event.stopPropagation();
        if (!this.canRate || this.busy.value) {
            return;
        }
        this.busy.value = true;
        try {
            // Save the whole modal record, including any edited remarks or
            // attachments, before closing it.
            const record = this.props.record;
            await record.update({ current_level: this.props.level });
            if (await record.save()) {
                await this.action.doAction({ type: "ir.actions.act_window_close" });
            }
        } finally {
            this.busy.value = false;
        }
    }
}

registry.category("fields").add("competency_level_picker", {
    component: CompetencyLevelPicker,
    displayName: _t("Behavioral indicator level choice"),
    supportedTypes: ["text"],
    extractProps: ({ options }) => ({ level: String(options.level) }),
});
