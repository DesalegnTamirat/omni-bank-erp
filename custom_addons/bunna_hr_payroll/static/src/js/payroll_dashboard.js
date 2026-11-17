/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

class BunnaPayrollDashboard extends Component {
    static template = "bunna_hr_payroll.PayrollDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            isSyncing: false,
            hasData: false,
            allPeriods: [],
            selectedPeriodId: false,
            selectedPeriod: {},
            overallProgress: 0,
            stepper: [],
            kpis: {
                gross_salary: 0,
                net_salary: 0,
                total_deductions: 0,
                basic_salary: 0,
                total_allowances: 0,
                total_employer_cost: 0,
                tax_amount: 0,
                pension_emp: 0,
                pension_comp: 0,
                pf_emp: 0,
                pf_comp: 0,
                od_asbeza_amount: 0,
                cash_indemnity_amount: 0,
                cost_sharing_amount: 0,
                labour_union_amount: 0,
                loans_amount: 0,
                total_employees: 0,
                total_slips: 0,
                done_slips: 0,
                waiting_slips: 0,
                draft_slips: 0,
                cancelled_slips: 0,
                total_batches: 0,
                done_batches: 0,
                draft_batches: 0,
            },
            cbsJournal: {
                total_entries: 0,
                total_debit: 0,
                total_credit: 0,
                difference: 0,
                is_balanced: false,
                groups: [],
            },
            cbsIntegration: {
                active: false,
                od_asbeza_synced: false,
                cash_indemnity_synced: false,
            },
            activeCoverageTab: 'summary',
            coverage: {
                total_workforce: 0,
                with_slip_count: 0,
                with_slip_percentage: 0,
                without_slip_count: 0,
                without_slip_percentage: 0,
                proportional_count: 0,
                missing_breakdown: {},
                missing_employees: [],
                proportional_slips: [],
            },
            departments: [],
            recentBatches: [],
        });

        this._refreshInterval = null;

        onMounted(async () => {
            await this._loadDashboardData();
            // Periodic background sync every 3 minutes
            this._refreshInterval = setInterval(async () => {
                await this._loadDashboardData(this.state.selectedPeriodId, true);
            }, 3 * 60 * 1000);
        });

        onWillUnmount(() => {
            if (this._refreshInterval) {
                clearInterval(this._refreshInterval);
            }
        });
    }

    async _loadDashboardData(periodId = null, silent = false) {
        if (!silent) {
            this.state.isLoading = true;
        }
        try {
            const result = await this.orm.call(
                "hr.payroll.period",
                "get_payroll_dashboard_data",
                [],
                { period_id: periodId || this.state.selectedPeriodId || false }
            );

            if (result) {
                this.state.hasData = true;
                this.state.no_periods_configured = result.no_periods_configured || false;
                this.state.allPeriods = result.all_periods || [];
                this.state.selectedPeriod = result.selected_period || {};
                this.state.selectedPeriodId = result.selected_period ? result.selected_period.id : false;
                this.state.overallProgress = result.overall_progress || 0;
                this.state.stepper = result.stepper || [];
                this.state.kpis = Object.assign({}, this.state.kpis, result.kpis || {});
                this.state.cbsJournal = Object.assign({}, this.state.cbsJournal, result.cbs_journal || {});
                this.state.cbsIntegration = Object.assign({}, this.state.cbsIntegration, result.cbs_integration || {});
                this.state.coverage = Object.assign({}, this.state.coverage, result.coverage || {});
                this.state.departments = result.departments || [];
                this.state.recentBatches = result.recent_batches || [];
            }
        } catch (error) {
            console.error("Failed to load Bunna Payroll Dashboard data:", error);
            if (!silent) {
                this.notification.add("Could not load dashboard data. Please try again.", {
                    type: "danger",
                });
            }
        } finally {
            this.state.isLoading = false;
        }
    }

    formatCurrency(amount) {
        const num = Number(amount || 0);
        return num.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }) + " ETB";
    }

    formatCompact(amount) {
        const num = Number(amount || 0);
        if (num >= 1000000) {
            return (num / 1000000).toFixed(2) + "M ETB";
        } else if (num >= 1000) {
            return (num / 1000).toFixed(1) + "K ETB";
        }
        return this.formatCurrency(num);
    }

    formatNumber(num) {
        return Number(num || 0).toLocaleString("en-US");
    }

    async onPeriodChange(ev) {
        const periodId = parseInt(ev.target.value, 10);
        if (periodId) {
            this.state.selectedPeriodId = periodId;
            await this._loadDashboardData(periodId);
        }
    }

    async refreshDashboard() {
        await this._loadDashboardData(this.state.selectedPeriodId);
        this.notification.add("Payroll Dashboard data refreshed", { type: "info" });
    }

    get isPeriodClosed() {
        return this.state.selectedPeriod && this.state.selectedPeriod.state === 'closed';
    }

    // =========================================================
    // Quick Workflow Actions & Drilldowns
    // =========================================================

    openPeriodForm() {
        if (!this.state.selectedPeriodId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.payroll.period",
            res_id: this.state.selectedPeriodId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllPeriods() {
        this.action.doAction("bunna_hr_payroll.action_hr_payroll_period");
    }

    openCreatePeriod() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "New Payroll Period",
            res_model: "hr.payroll.period",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openFetchIndemnity() {
        if (this.isPeriodClosed) {
            this.notification.add("This payroll period is CLOSED. Cash indemnity fetching is disabled (Viewing Mode Only).", { type: "warning" });
            return;
        }
        this.action.doAction({
            name: "Fetch Cash Indemnity from CBS",
            type: "ir.actions.act_window",
            res_model: "cbs.cash.indemnity.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_period_id: this.state.selectedPeriodId,
            },
        });
    }

    async triggerSyncOdAsbeza() {
        if (this.isPeriodClosed) {
            this.notification.add("This payroll period is CLOSED. Adjustment synchronization is disabled (Viewing Mode Only).", { type: "warning" });
            return;
        }
        this.state.isSyncing = true;
        try {
            const action = await this.orm.call(
                "hr.payroll.adjustment",
                "action_fetch_cbs_od_asbeza",
                [[]],
                {}
            );
            if (action && action.tag === "display_notification") {
                this.notification.add(action.params.message, {
                    type: action.params.type || "success",
                    title: action.params.title,
                });
            }
            await this._loadDashboardData(this.state.selectedPeriodId);
        } catch (error) {
            console.error("OD & ASBEZA Sync failed:", error);
            this.notification.add(error.message || "Failed to sync OD & ASBEZA from CBS.", {
                type: "danger",
                title: "CBS Sync Error",
            });
        } finally {
            this.state.isSyncing = false;
        }
    }

    openAutoBatchWizard() {
        if (this.isPeriodClosed) {
            this.notification.add("This payroll period is CLOSED. Batch generation is locked; opening existing batches list.", { type: "info" });
            this.openBatchesList();
            return;
        }
        this.action.doAction({
            name: "Auto-Generate Payroll Batches",
            type: "ir.actions.act_window",
            res_model: "hr.payroll.auto.batch.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_period_id: this.state.selectedPeriodId,
            },
        });
    }

    openBatchesList() {
        this.action.doAction({
            name: "Payroll Batches",
            type: "ir.actions.act_window",
            res_model: "hr.payslip.run",
            views: [[false, "list"], [false, "form"]],
            domain: this.state.selectedPeriodId ? [["period_id", "=", this.state.selectedPeriodId]] : [],
            context: {
                default_period_id: this.state.selectedPeriodId,
            },
        });
    }

    openBatchRecord(batchId) {
        if (!batchId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.payslip.run",
            res_id: batchId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPayslipsList(stateFilter = null) {
        const domain = this.state.selectedPeriodId ? [["period_id", "=", this.state.selectedPeriodId]] : [];
        if (stateFilter) {
            domain.push(["state", "=", stateFilter]);
        }
        this.action.doAction({
            name: stateFilter ? `Payslips (${stateFilter.toUpperCase()})` : "All Payslips",
            type: "ir.actions.act_window",
            res_model: "hr.payslip",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: {
                default_period_id: this.state.selectedPeriodId,
            },
        });
    }

    openJournalWizard() {
        if (this.isPeriodClosed) {
            this.notification.add("This payroll period is CLOSED. Journal generation is locked; opening existing journal entries list.", { type: "info" });
            this.openJournalEntriesList();
            return;
        }
        this.action.doAction({
            name: "Generate CBS Journal Entries",
            type: "ir.actions.act_window",
            res_model: "bunna.payroll.journal.wizard",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_period_id: this.state.selectedPeriodId,
            },
        });
    }

    openJournalEntriesList(groupCode = null) {
        const domain = this.state.selectedPeriodId ? [["period_id", "=", this.state.selectedPeriodId]] : [];
        if (groupCode) {
            domain.push(["group_code", "=", groupCode]);
        }
        this.action.doAction({
            name: groupCode ? `CBS Journal Entries (Group ${groupCode})` : "CBS Journal Entries",
            type: "ir.actions.act_window",
            res_model: "bunna.payroll.journal.entry",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: {
                default_period_id: this.state.selectedPeriodId,
                search_default_group_by_group: 1,
            },
        });
    }

    async closePeriodAction() {
        if (!this.state.selectedPeriodId) return;
        if (this.isPeriodClosed) {
            this.notification.add("This payroll period is already finalized and CLOSED.", { type: "info" });
            return;
        }
        try {
            await this.orm.call(
                "hr.payroll.period",
                "action_close_period",
                [[this.state.selectedPeriodId]]
            );
            this.notification.add("Payroll Period closed successfully.", { type: "success" });
            await this._loadDashboardData(this.state.selectedPeriodId);
        } catch (error) {
            this.notification.add(error.message || "Failed to close period.", { type: "danger" });
        }
    }

    setCoverageTab(tab) {
        this.state.activeCoverageTab = tab;
    }

    openEmployeeForm(empId) {
        if (!empId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.employee",
            res_id: empId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openContractForm(empId) {
        if (!empId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Employment Contract / Version",
            res_model: "hr.version",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_employee_id: empId,
            },
        });
    }

    openPayslipForm(slipId) {
        if (!slipId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "hr.payslip",
            res_id: slipId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onStepClick(step) {
        if (!step || !step.action_name) return;
        if (this.isPeriodClosed) {
            // Closed period: Only viewing actions are permitted
            switch (step.action_name) {
                case "open_period_form":
                    this.openPeriodForm();
                    break;
                case "open_batches_list":
                case "open_auto_batch_wizard":
                    this.openBatchesList();
                    break;
                case "open_payslips_list":
                    this.openPayslipsList();
                    break;
                case "open_journal_entries_list":
                case "open_journal_wizard":
                    this.openJournalEntriesList();
                    break;
                default:
                    this.openPeriodForm();
                    break;
            }
            return;
        }
        switch (step.action_name) {
            case "open_period_form":
                this.openPeriodForm();
                break;
            case "open_fetch_indemnity_wizard":
                this.openFetchIndemnity();
                break;
            case "open_auto_batch_wizard":
                this.openAutoBatchWizard();
                break;
            case "open_batches_list":
                this.openBatchesList();
                break;
            case "open_payslips_list":
                this.openPayslipsList();
                break;
            case "open_journal_wizard":
                this.openJournalWizard();
                break;
            case "open_journal_entries_list":
                this.openJournalEntriesList();
                break;
            case "close_period_action":
                this.closePeriodAction();
                break;
            default:
                break;
        }
    }
}

registry.category("actions").add("bunna_hr_payroll.payroll_dashboard", BunnaPayrollDashboard);

export { BunnaPayrollDashboard };
