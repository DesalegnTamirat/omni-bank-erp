/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PayrollDashboard extends Component {
    static template = "payroll.PayrollDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            totalPayslips: 0,
            activePayruns: 0,
            totalGross: 0,
            totalNet: 0,
            totalTax: 0,
            totalPension: 0,
            unresolvedExceptions: 0,
            recentPayruns: [],
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });
    }

    async loadDashboardData() {
        try {
            const payruns = await this.orm.searchRead(
                "hr.payslip.run",
                [],
                ["id", "name", "number", "state", "total_gross", "total_net", "total_tax", "total_pension_ee", "payslip_count"],
                { limit: 5, order: "date_start desc" }
            );

            let gross = 0;
            let net = 0;
            let tax = 0;
            let pension = 0;
            let slips = 0;

            payruns.forEach(r => {
                gross += r.total_gross || 0;
                net += r.total_net || 0;
                tax += r.total_tax || 0;
                pension += r.total_pension_ee || 0;
                slips += r.payslip_count || 0;
            });

            const excCount = await this.orm.searchCount("hr.payroll.exception", [["is_resolved", "=", false]]);

            this.state.activePayruns = payruns.length;
            this.state.totalPayslips = slips;
            this.state.totalGross = gross;
            this.state.totalNet = net;
            this.state.totalTax = tax;
            this.state.totalPension = pension;
            this.state.unresolvedExceptions = excCount;
            this.state.recentPayruns = payruns;
        } catch (e) {
            console.warn("Payroll Dashboard data load warning:", e);
        }
    }

    openPayrun(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.payslip.run",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllPayruns() {
        this.action.doAction("payroll.action_hr_payslip_run");
    }

    openAllExceptions() {
        this.action.doAction("payroll.action_hr_payroll_exception");
    }
}

registry.category("actions").add("payroll_dashboard_tag", PayrollDashboard);
