import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Smart button counter: documents linked to the current record (works on any model). */
export class DmsStat extends Component {
    static template = "documents_lite.Stat";
    static props = { ...standardFieldProps, string: { type: String, optional: true } };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ count: 0 });
        onWillStart(() => this.load(this.props.record));
        onWillUpdateProps((next) => this.load(next.record));
    }

    async load(record) {
        this.state.count = record.resId
            ? await this.orm.searchCount("dms.document", [
                  ["res_model", "=", record.resModel],
                  ["res_id", "=", record.resId],
              ])
            : 0;
    }

    get label() {
        return this.props.string || _t("Documents");
    }
}

registry.category("fields").add("dms_stat", {
    component: DmsStat,
    supportedTypes: ["integer"],
    isEmpty: () => false,
    extractProps: ({ string }) => ({ string }),
});
