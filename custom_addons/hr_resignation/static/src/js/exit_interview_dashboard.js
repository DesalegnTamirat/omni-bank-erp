/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ExitInterviewDashboard extends Component {
    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            view: "dash",          // "dash" | "list" | "rep"
            loading: true,
            // filter selections
            f_ou:       "all",
            f_pos:      "all",
            f_sep:      "all",
            // filter options
            operating_units: [],
            positions:  [],
            sep_types:  [],
            // analytics data
            kpis:       {},
            bars:       [],
            keeps:      [],
            donuts:     [],
            cg:         "#e5e7eb 0% 100%",
            likerts:    [],
            yes_no:     [],
            text_qs:    [],
            interviews: [],
            // report view
            cur_interview: null,
            // bars collapse
            showAllBars: false,
        });

        onWillStart(async () => {
            await this._loadFilters();
            await this._loadData();
        });
    }

    // ── data loading ────────────────────────────────────────────────────────

    async _loadFilters() {
        try {
            const opts = await this.orm.call(
                "hr.exit.interview.dashboard", "get_filter_options", []);
            this.state.operating_units = opts.operating_units || [];
            this.state.positions   = opts.positions   || [];
            this.state.sep_types   = opts.separation_types || [];
        } catch (e) {
            console.error("Failed to load filter options:", e);
        }
    }


        async openReportTab() {
            this.state.view = 'rep';
            if (!this.state.cur_interview && this.state.interviews && this.state.interviews.length > 0) {
                const first_id = this.state.interviews[0].id;
                this.state.loading = true;
                this.state.cur_interview = await this.orm.call("hr.exit.interview.dashboard", "get_employee_report", [first_id]);
                this.state.loading = false;
            }
        }

        async onChangeReportEmployee(ev) {

        const id = parseInt(ev.target.value);
        if (id) {
            this.state.loading = true;
            this.state.cur_interview = await this.orm.call("hr.exit.interview.dashboard", "get_employee_report", [id]);
            this.state.loading = false;
        } else {
            this.state.cur_interview = null;
        }
    }
    
    async onPrintReport() {
        if (!this.state.cur_interview) return;
        const id = this.state.cur_interview.id;
        if (!id) {
            alert("Error: Missing Interview ID!");
            return;
        }
        this.action.doAction({
            type: 'ir.actions.report',
            report_type: 'qweb-pdf',
            report_name: 'hr_resignation.report_exit_interview',
            report_file: 'hr_resignation.report_exit_interview',
            name: 'Exit Interview',
            context: { active_ids: [id], active_model: 'hr.exit.interview' }
        });
    }
    toggleShowAllBars() {
        this.state.showAllBars = !this.state.showAllBars;
    }

    async _loadData() {
        this.state.loading = true;
        try {
            const filters = {
                operating_unit: this.state.f_ou,
                position:       this.state.f_pos,
                sep_type:       this.state.f_sep,
            };
            const data = await this.orm.call(
                "hr.exit.interview.dashboard", "get_analytics_data", [], { filters });

            this.state.kpis       = data.kpis       || {};
            this.state.bars       = data.bars        || [];
            this.state.keeps      = data.keeps       || [];
            this.state.donuts     = data.donuts      || [];
            this.state.cg         = data.cg          || "#e5e7eb 0% 100%";
            this.state.likerts    = data.likerts     || [];
            this.state.yes_no     = data.yes_no      || [];
            this.state.text_qs    = data.text_qs     || [];
            this.state.interviews = data.interviews  || [];

            // Keep selected interview in sync when filtering in report view
            if (this.state.view === 'rep') {
                if (this.state.interviews && this.state.interviews.length > 0) {
                    const currentId = this.state.cur_interview ? this.state.cur_interview.id : null;
                    const exists = this.state.interviews.some(inv => inv.id === currentId);
                    if (!exists) {
                        const first_id = this.state.interviews[0].id;
                        this.state.cur_interview = await this.orm.call("hr.exit.interview.dashboard", "get_employee_report", [first_id]);
                    }
                } else {
                    this.state.cur_interview = null;
                }
            }
        } catch (e) {
            console.error("Failed to load analytics data:", e);
        }
        this.state.loading = false;
    }

    // ── filter handlers ─────────────────────────────────────────────────────

    onFilterChange(field, ev) {
        this.state[field] = ev.target.value;
        this._loadData();
    }

    // ── navigation ───────────────────────────────────────────────────────────

    showDash() { this.state.view = "dash"; }
    showList() { this.state.view = "list"; }

    // Click row → open the exit interview form
    openInterview(interview) {
        const interviewId = (interview && typeof interview === 'object') ? interview.id : interview;
        if (interviewId) {
            this.action.doAction({
                type:      "ir.actions.act_window",
                name:      "Exit Interview",
                res_model: "hr.exit.interview",
                res_id:    interviewId,
                view_mode: "form",
                views:     [[false, "form"]],
                target:    "current",
            });
        }
    }

    // Click resignation → open the resignation form
    openResignation(interview) {
        if (interview.resignation_id) {
            this.action.doAction({
                type:      "ir.actions.act_window",
                name:      "Resignation",
                res_model: "hr.resignation",
                res_id:    interview.resignation_id,
                view_mode: "form",
                views:     [[false, "form"]],
                target:    "current",
            });
        }
    }

    printPDF(iv) {
        if (!iv || !iv.id) return;
        this.action.doAction({
            type: 'ir.actions.report',
            report_type: 'qweb-pdf',
            report_name: 'hr_resignation.report_exit_interview',
            report_file: 'hr_resignation.report_exit_interview',
            name: 'Exit Interview',
            context: { active_ids: [iv.id], active_model: 'hr.exit.interview' }
        });
    }

    openListView(type, answer=null) {
        let domain = [['state', '=', 'completed']];
        let res_model = 'hr.exit.interview';
        let name = "Exit Interviews";

        if (['answer', 'text', 'question', 'rating', 'recommend'].includes(type)) {
            res_model = 'hr.exit.interview.line';
            domain = [['interview_id.state', '=', 'completed']];
            if (type === 'answer' && answer) {
                domain.push(['answer', 'ilike', answer]);
                name = "Responses: " + answer;
            } else if (type === 'question' && answer) {
                domain.push(['question_name', 'ilike', answer]);
                name = "Responses: " + answer;
            } else if (type === 'text') {
                domain.push(['question_type', 'in', ['text', 'custom']]);
                name = "All Text Responses";
            } else if (type === 'rating') {
                domain.push(['question_type', 'in', ['rating', 'satisfaction']]);
                name = "Manager & Satisfaction Ratings";
            } else if (type === 'recommend') {
                domain.push(['question_name', 'ilike', 'recommend']);
                name = "Would Recommend Responses";
            }
            
            if (this.state.f_ou && this.state.f_ou !== 'all') {
                domain.push(
                    '|', '|', '|', '|', '|',
                    ['interview_id.employee_id.department_id.name', '=', this.state.f_ou],
                    ['interview_id.employee_id.default_operating_unit_id.name', '=', this.state.f_ou],
                    ['interview_id.employee_id.department_id.operating_unit_id.name', '=', this.state.f_ou],
                    ['interview_id.employee_id.operating_unit_ids.name', '=', this.state.f_ou],
                    ['interview_id.resignation_id.operating_unit_id.name', '=', this.state.f_ou],
                    ['interview_id.resignation_id.department_id.name', '=', this.state.f_ou]
                );
            }
            if (this.state.f_pos && this.state.f_pos !== 'all') {
                domain.push(
                    '|',
                    ['interview_id.employee_id.job_id.name', '=', this.state.f_pos],
                    ['interview_id.employee_id.job_position.name', '=', this.state.f_pos]
                );
            }
            if (this.state.f_sep && this.state.f_sep !== 'all') {
                domain.push(['interview_id.resignation_id.resignation_type_id.name', '=', this.state.f_sep]);
            }
        } else {
            if (type === 'regrettable') {
                domain.push(['resignation_id.performance_rating', 'in', ['high', 'excellent']]);
                name = "Regrettable Exits";
            } else if (type === 'completion') {
                domain = [['resignation_id', '!=', false]];
                name = "Exit Interviews (Completion Status)";
            } else if (type === 'all') {
                name = "Completed Exit Interviews";
            }

            if (this.state.f_ou && this.state.f_ou !== 'all') {
                domain.push(
                    '|', '|', '|', '|', '|',
                    ['employee_id.department_id.name', '=', this.state.f_ou],
                    ['employee_id.default_operating_unit_id.name', '=', this.state.f_ou],
                    ['employee_id.department_id.operating_unit_id.name', '=', this.state.f_ou],
                    ['employee_id.operating_unit_ids.name', '=', this.state.f_ou],
                    ['resignation_id.operating_unit_id.name', '=', this.state.f_ou],
                    ['resignation_id.department_id.name', '=', this.state.f_ou]
                );
            }
            if (this.state.f_pos && this.state.f_pos !== 'all') {
                domain.push(
                    '|',
                    ['employee_id.job_id.name', '=', this.state.f_pos],
                    ['employee_id.job_position.name', '=', this.state.f_pos]
                );
            }
            if (this.state.f_sep && this.state.f_sep !== 'all') {
                domain.push(['resignation_id.resignation_type_id.name', '=', this.state.f_sep]);
            }
        }

        this.action.doAction({
            name: name,
            type: "ir.actions.act_window",
            res_model: res_model,
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }


    onQuestionClick(ev) {
        const question = ev.currentTarget.dataset.question;
        if (question) {
            this.openListView('question', question);
        }
    }
    onBarClick(ev) {
        const answer = ev.currentTarget.dataset.answer;
        if (answer) {
            this.openListView('answer', answer);
        }
    }

    onKpiClickAll() {
        this.openListView('all');
    }

    onKpiClickCompletion() {
        this.openListView('completion');
    }

    onKpiClickRating() {
        this.openListView('rating');
    }

    onKpiClickRecommend() {
        this.openListView('recommend');
    }

    onKpiClickRegrettable() {
        this.openListView('regrettable');
    }

    onFilterChangeOU(ev) {
        this.onFilterChange('f_ou', ev);
    }

    onFilterChangePos(ev) {
        this.onFilterChange('f_pos', ev);
    }

    onFilterChangeSep(ev) {
        this.onFilterChange('f_sep', ev);
    }
}

ExitInterviewDashboard.template = "hr_resignation.ExitInterviewDashboard";
registry.category("actions").add("hr_resignation.exit_interview_dashboard", ExitInterviewDashboard);
