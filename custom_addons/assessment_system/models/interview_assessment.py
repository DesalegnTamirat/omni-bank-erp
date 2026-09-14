# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class InterviewSession(models.Model):
    _name = "interview.session"
    _description = "Interview Assessment Session"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Session Reference", required=True, default=lambda self: _("New"), copy=False, tracking=True)
    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy", tracking=True)
    recruiting_position_id = fields.Many2one("hr.job", string="Recruiting Position", tracking=True)
    recruitment_type = fields.Selection([
        ('Internal', 'Internal Recruitment'),
        ('External', 'External Recruitment')
    ], string="Recruitment Type", default='Internal', tracking=True)
    assessment_date = fields.Date(string="Assessment Date", default=fields.Date.context_today, tracking=True)

    rate_sheet_id = fields.Many2one("interview.rate.sheet", string="Interview Rate Sheet", required=True, tracking=True)

    # Panel of Interviewers
    interviewer_ids = fields.Many2many(
        "hr.employee",
        "interview_session_interviewer_rel",
        "session_id",
        "employee_id",
        string="Interview Panel",
        required=True
    )
    no_of_interviewers = fields.Integer(
        string="Number of Interviewers",
        compute="_compute_no_of_interviewers",
        store=True,
        help="Dynamically determined based on the assigned interview panel."
    )

    # Candidate List
    applicant_ids = fields.Many2many(
        "hr.applicant",
        "interview_session_applicant_rel",
        "session_id",
        "applicant_id",
        string="External Candidates"
    )
    employee_candidate_ids = fields.Many2many(
        "hr.employee",
        "interview_session_employee_rel",
        "session_id",
        "employee_id",
        string="Internal Candidates"
    )
    no_of_candidates = fields.Integer(
        string="Number of Candidates",
        compute="_compute_no_of_candidates",
        store=True
    )

    state = fields.Selection([
        ('draft', 'Draft Configuration'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string="State", default='draft', tracking=True, copy=False)

    active = fields.Boolean(default=True)

    interviewer_assessment_ids = fields.One2many(
        "interview.assessment",
        "session_id",
        string="Interviewer Assessments"
    )
    final_result_ids = fields.One2many(
        "interview.final.result",
        "session_id",
        string="Final Candidate Results"
    )

    submitted_count = fields.Integer(string="Submitted Assessments", compute="_compute_submission_status")
    submission_status = fields.Char(string="Submission Status", compute="_compute_submission_status")
    is_all_submitted = fields.Boolean(string="All Submitted", compute="_compute_submission_status")

    @api.depends("interviewer_ids")
    def _compute_no_of_interviewers(self):
        for rec in self:
            rec.no_of_interviewers = len(rec.interviewer_ids)

    @api.depends("recruitment_type", "applicant_ids", "employee_candidate_ids")
    def _compute_no_of_candidates(self):
        for rec in self:
            if rec.recruitment_type == 'External':
                rec.no_of_candidates = len(rec.applicant_ids)
            else:
                rec.no_of_candidates = len(rec.employee_candidate_ids)

    @api.depends("interviewer_ids", "interviewer_assessment_ids.state")
    def _compute_submission_status(self):
        for rec in self:
            total = len(rec.interviewer_ids)
            submitted = len(rec.interviewer_assessment_ids.filtered(lambda a: a.state == 'submitted'))
            rec.submitted_count = submitted
            rec.submission_status = _("%d of %d Interviewers Submitted") % (submitted, total)
            rec.is_all_submitted = (total > 0 and submitted >= total)

    interviewer_domain_ids = fields.Many2many(
        "hr.employee",
        "interview_session_interviewer_domain_rel",
        "session_id",
        "employee_id",
        compute="_compute_panel_and_candidate_domains",
        string="Interviewer Domain Employees"
    )
    employee_candidate_domain_ids = fields.Many2many(
        "hr.employee",
        "interview_session_employee_domain_rel",
        "session_id",
        "employee_id",
        compute="_compute_panel_and_candidate_domains",
        string="Employee Candidate Domain"
    )
    applicant_candidate_domain_ids = fields.Many2many(
        "hr.applicant",
        "interview_session_applicant_domain_rel",
        "session_id",
        "applicant_id",
        compute="_compute_panel_and_candidate_domains",
        string="Applicant Candidate Domain"
    )

    @api.depends("vacancy_id", "recruitment_type")
    def _compute_panel_and_candidate_domains(self):
        for rec in self:
            if rec.vacancy_id:
                panel_emp_ids, cand_emp_ids, cand_app_ids = rec._get_panel_and_candidates_from_process(rec.vacancy_id)
                rec.interviewer_domain_ids = [(6, 0, panel_emp_ids)]
                rec.employee_candidate_domain_ids = [(6, 0, cand_emp_ids)]
                rec.applicant_candidate_domain_ids = [(6, 0, cand_app_ids)]
            else:
                rec.interviewer_domain_ids = [(5, 0, 0)]
                rec.employee_candidate_domain_ids = [(5, 0, 0)]
                rec.applicant_candidate_domain_ids = [(5, 0, 0)]

    def _get_panel_and_candidates_from_process(self, vacancy):
        if not vacancy:
            return [], [], []

        vac_id = vacancy.id
        vac_ref = vacancy.reference

        panel_emp_ids = []
        cand_emp_ids = []
        cand_app_ids = []

        # 1. Search Internal Recruitment Process Selected
        int_sel = self.env["new.internal.recruitment.selected"].search([
            '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
        ], limit=1)

        if int_sel:
            if int_sel.new_int_rec_panel:
                for panel in int_sel.new_int_rec_panel:
                    emp = panel.delegate_employee_id if (panel.delegation_state == 'approved' and panel.delegate_employee_id) else panel.emp_name
                    if emp and emp.id not in panel_emp_ids:
                        panel_emp_ids.append(emp.id)

            if int_sel.recr_selected_team_id:
                for member in int_sel.recr_selected_team_id:
                    user = member.employee_name or member.alternate_committee_member
                    if user:
                        emp = user.employee_id if getattr(user, 'employee_id', False) else self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
                        if emp and emp.id not in panel_emp_ids:
                            panel_emp_ids.append(emp.id)

            if int_sel.new_int_rec_sel:
                for cand in int_sel.new_int_rec_sel:
                    if cand.emp_name and cand.emp_name.id not in cand_emp_ids:
                        cand_emp_ids.append(cand.emp_name.id)

        # 2. Search External Recruitment Process Selected
        ext_sel = self.env["external.recruitment.selected"].search([
            '|', ('vacancy_id', '=', vac_id), ('vacancy_reference', '=', vac_ref)
        ], limit=1)

        if ext_sel:
            if ext_sel.ext_rec_panel:
                for panel in ext_sel.ext_rec_panel:
                    emp = panel.delegate_employee_id if (panel.delegation_state == 'approved' and panel.delegate_employee_id) else panel.emp_name
                    if emp and emp.id not in panel_emp_ids:
                        panel_emp_ids.append(emp.id)

            ext_team = getattr(ext_sel, 'recr_exter_selected_team_id', False) or getattr(ext_sel, 'recr_selected_team_id', False)
            if ext_team:
                for member in ext_team:
                    user = member.employee_name or member.alternate_committee_member
                    if user:
                        emp = user.employee_id if getattr(user, 'employee_id', False) else self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
                        if emp and emp.id not in panel_emp_ids:
                            panel_emp_ids.append(emp.id)

            if ext_sel.ext_rec_sel:
                for cand in ext_sel.ext_rec_sel:
                    if cand.applicant_name and cand.applicant_name.id not in cand_app_ids:
                        cand_app_ids.append(cand.applicant_name.id)

        # 3. Fallback to Job Vacancy Panel Members
        if not panel_emp_ids and vacancy.memb_panel_vac:
            for pm in vacancy.memb_panel_vac:
                emp = pm.employee_id
                if not emp and pm.panel_member_name:
                    emp = self.env['hr.employee'].search([('name', '=ilike', pm.panel_member_name)], limit=1)
                if emp and emp.id not in panel_emp_ids:
                    panel_emp_ids.append(emp.id)

        # 4. Fallback to candidate scores
        if not cand_emp_ids and not cand_app_ids:
            scores = self.env["recruitment.candidate.score"].search([
                ("vacancy_id", "=", vac_id), ("disqualified", "=", False)
            ])
            for score in scores:
                if score.employee_id and score.employee_id.id not in cand_emp_ids:
                    cand_emp_ids.append(score.employee_id.id)
                if score.applicant_id and score.applicant_id.id not in cand_app_ids:
                    cand_app_ids.append(score.applicant_id.id)

        return panel_emp_ids, cand_emp_ids, cand_app_ids

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id(self):
        if not self.vacancy_id:
            return

        if self.vacancy_id.job_position:
            self.recruiting_position_id = self.vacancy_id.job_position

        rec_type = 'Internal'
        if hasattr(self.vacancy_id, 'recruitment_type') and self.vacancy_id.recruitment_type:
            rec_type = 'External' if 'ext' in str(self.vacancy_id.recruitment_type).lower() else 'Internal'
        self.recruitment_type = rec_type

        panel_emp_ids, cand_emp_ids, cand_app_ids = self._get_panel_and_candidates_from_process(self.vacancy_id)

        self.interviewer_ids = [(6, 0, panel_emp_ids)]
        self.employee_candidate_ids = [(6, 0, cand_emp_ids)]
        self.applicant_ids = [(6, 0, cand_app_ids)]

        domain = {}
        if panel_emp_ids:
            domain['interviewer_ids'] = [('id', 'in', panel_emp_ids)]
        if cand_emp_ids:
            domain['employee_candidate_ids'] = [('id', 'in', cand_emp_ids)]
        if cand_app_ids:
            domain['applicant_ids'] = [('id', 'in', cand_app_ids)]

        return {'domain': domain}

    def action_load_panel_and_candidates(self):
        """Reload panel members and candidates directly from internal/external process record."""
        for rec in self:
            if rec.vacancy_id:
                panel_emp_ids, cand_emp_ids, cand_app_ids = rec._get_panel_and_candidates_from_process(rec.vacancy_id)
                rec.write({
                    'interviewer_ids': [(6, 0, panel_emp_ids)],
                    'employee_candidate_ids': [(6, 0, cand_emp_ids)],
                    'applicant_ids': [(6, 0, cand_app_ids)],
                })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("interview.session") or _("INT-SESSION")
        records = super().create(vals_list)
        for rec in records:
            if rec.vacancy_id:
                panel_emp_ids, cand_emp_ids, cand_app_ids = rec._get_panel_and_candidates_from_process(rec.vacancy_id)
                if not rec.interviewer_ids and panel_emp_ids:
                    rec.write({'interviewer_ids': [(6, 0, panel_emp_ids)]})
                if not rec.employee_candidate_ids and cand_emp_ids:
                    rec.write({'employee_candidate_ids': [(6, 0, cand_emp_ids)]})
                if not rec.applicant_ids and cand_app_ids:
                    rec.write({'applicant_ids': [(6, 0, cand_app_ids)]})
        return records

    def action_start_interview(self):
        for session in self:
            if not session.interviewer_ids:
                raise UserError(_("Please assign at least one interviewer to the Interview Panel."))
            if not session.rate_sheet_id:
                raise UserError(_("Please select an Interview Rate Sheet before starting the interview."))
            if session.recruitment_type == 'External' and not session.applicant_ids:
                raise UserError(_("Please assign external candidates (Applicants) to the interview."))
            if session.recruitment_type == 'Internal' and not session.employee_candidate_ids:
                raise UserError(_("Please assign internal candidates (Employees) to the interview."))

            # Generate individual assessment sheet for each interviewer
            Assessment = self.env["interview.assessment"]
            CandidateAss = self.env["interview.candidate.assessment"]
            CriteriaScore = self.env["interview.criteria.score"]

            for interviewer in session.interviewer_ids:
                # Check if assessment already exists for interviewer
                ass = session.interviewer_assessment_ids.filtered(lambda a: a.assessor_name == interviewer)
                if not ass:
                    ass = Assessment.create({
                        'session_id': session.id,
                        'assessor_name': interviewer.id,
                        'assessment_date': session.assessment_date,
                        'recruiting_position': session.recruiting_position_id.id if session.recruiting_position_id else False,
                        'recruitment_type': session.recruitment_type,
                        'vacancy_reference': session.vacancy_id.reference if session.vacancy_id else (session.name or ''),
                        'state': 'draft',
                    })

                # Create candidate assessment lines
                candidates = session.applicant_ids if session.recruitment_type == 'External' else session.employee_candidate_ids
                for cand in candidates:
                    app_id = cand.id if session.recruitment_type == 'External' else False
                    emp_id = cand.id if session.recruitment_type == 'Internal' else False

                    existing_cand_ass = ass.candidate_assessment_ids.filtered(
                        lambda c: (session.recruitment_type == 'External' and c.applicant_id.id == app_id) or
                                  (session.recruitment_type == 'Internal' and c.employee_id.id == emp_id)
                    )
                    if not existing_cand_ass:
                        cand_ass = CandidateAss.create({
                            'assessment_id': ass.id,
                            'applicant_id': app_id,
                            'employee_id': emp_id,
                            'attendance': 'present',
                        })
                        # Populate criteria score lines from rate sheet
                        for line in session.rate_sheet_id.line_ids:
                            CriteriaScore.create({
                                'candidate_assessment_id': cand_ass.id,
                                'assessment_id': ass.id,
                                'criteria_line_id': line.id,
                                'marks_awarded': 0.0,
                            })

            session.write({'state': 'in_progress'})

    def action_calculate_final_results(self):
        for session in self:
            submitted_assessments = session.interviewer_assessment_ids.filtered(lambda a: a.state == 'submitted')
            if not submitted_assessments:
                raise UserError(_("No interviewer assessments have been submitted yet."))

            # Reset previous final results
            session.final_result_ids.unlink()

            FinalResult = self.env["interview.final.result"]
            FinalResultLine = self.env["interview.final.result.line"]

            candidates = session.applicant_ids if session.recruitment_type == 'External' else session.employee_candidate_ids
            no_interviewers = len(session.interviewer_ids)

            for cand in candidates:
                app_id = cand if session.recruitment_type == 'External' else False
                emp_id = cand if session.recruitment_type == 'Internal' else False
                cand_name = cand.partner_name if (session.recruitment_type == 'External' and hasattr(cand, 'partner_name') and cand.partner_name) else cand.name

                interviewer_scores = []
                score_summary_parts = []
                detail_lines_vals = []

                for ass in submitted_assessments:
                    cand_ass = ass.candidate_assessment_ids.filtered(
                        lambda c: (session.recruitment_type == 'External' and c.applicant_id == app_id) or
                                  (session.recruitment_type == 'Internal' and c.employee_id == emp_id)
                    )
                    if cand_ass:
                        score = cand_ass.percentage_score
                        interviewer_scores.append(score)
                        score_summary_parts.append(f"{ass.assessor_name.name}: {score:.2f}")
                        detail_lines_vals.append({
                            'interviewer_id': ass.assessor_name.id,
                            'interviewer_name': ass.assessor_name.name,
                            'score': score,
                            'submitted_date': ass.assessment_date,
                        })

                # Calculate final average score = sum of scores given by all assigned interviewers / N
                if interviewer_scores and no_interviewers > 0:
                    final_average = sum(interviewer_scores) / float(no_interviewers)
                else:
                    final_average = 0.0

                summary_text = " | ".join(score_summary_parts)

                res_rec = FinalResult.create({
                    'session_id': session.id,
                    'applicant_id': app_id.id if app_id else False,
                    'employee_id': emp_id.id if emp_id else False,
                    'candidate_name': cand_name,
                    'attendance': 'present',
                    'no_of_assessments': len(interviewer_scores),
                    'individual_score_summary': summary_text,
                    'final_score': round(final_average, 2),
                    'result_status': 'passed' if final_average >= 50.0 else 'failed',
                })

                for d_vals in detail_lines_vals:
                    d_vals['final_result_id'] = res_rec.id
                    FinalResultLine.create(d_vals)

                # Push score to recruitment.candidate.score if vacancy is set
                session._push_final_score_to_recruitment(cand, app_id, emp_id, final_average)

            session.write({'state': 'completed'})

    def _push_final_score_to_recruitment(self, cand, app_id, emp_id, final_average):
        self.ensure_one()
        score_val = round(final_average, 2)
        if not self.vacancy_id:
            return
        CandScore = self.env["recruitment.candidate.score"]
        domain = [('vacancy_id', '=', self.vacancy_id.id)]
        if app_id:
            domain.append(('applicant_id', '=', app_id.id))
        elif emp_id:
            domain.append(('employee_id', '=', emp_id.id))
        else:
            return

        score_rec = CandScore.search(domain, limit=1)
        if score_rec:
            score_rec.write({'interview_score': score_val})

        # Push to Internal Recruitment Selection candidate lines
        if emp_id:
            int_sels = self.env["new.internal.recruitment.selected"].search([
                '|', ('vacancy_id', '=', self.vacancy_id.id),
                ('vacancy_reference', '=', self.vacancy_id.reference)
            ])
            for int_sel in int_sels:
                cand_lines = int_sel.new_int_rec_sel.filtered(lambda c: c.emp_name and c.emp_name.id == emp_id.id)
                cand_lines.write({'interview_score': score_val})

        # Push to External Recruitment Selection candidate lines
        if app_id:
            ext_sels = self.env["external.recruitment.selected"].search([])
            app_pname = getattr(app_id, 'partner_name', False)
            app_aname = getattr(app_id, 'name', False)
            app_names = [str(n).strip().lower() for n in [app_pname, app_aname] if n]
            for ext_sel in ext_sels:
                for cand_line in ext_sel.ext_rec_sel:
                    app_rec = cand_line.applicant_name if hasattr(cand_line, 'applicant_name') and cand_line.applicant_name else False
                    line_names = []
                    if cand_line.emp_name:
                        line_names.append(cand_line.emp_name.strip().lower())
                    if hasattr(cand_line, 'display_name') and cand_line.display_name:
                        line_names.append(cand_line.display_name.strip().lower())
                    if app_rec:
                        p_name = getattr(app_rec, 'partner_name', False)
                        a_name = getattr(app_rec, 'name', False)
                        if p_name:
                            line_names.append(str(p_name).strip().lower())
                        if a_name:
                            line_names.append(str(a_name).strip().lower())
                    
                    if (app_rec and app_rec.id == app_id.id) or any(n in line_names for n in app_names):
                        cand_line.write({'interview_score': score_val})

    def _check_and_auto_complete(self):
        for session in self:
            if session.is_all_submitted and session.state == 'in_progress':
                session.action_calculate_final_results()

    def action_reset_to_draft(self):
        for session in self:
            session.write({'state': 'draft'})

    def unlink(self):
        for rec in self:
            rec.write({"active": False})
        return True


class InterviewAssessment(models.Model):
    _name = "interview.assessment"
    _description = "Interview Assessment"
    _rec_name = "assessor_name"
    _order = "id desc"

    session_id = fields.Many2one("interview.session", string="Interview Session", ondelete="cascade")
    vacancy_reference = fields.Char(string="Vacancy Reference")
    recruiting_position = fields.Many2one("hr.job", string="Recruiting Position")
    assessor_name = fields.Many2one("hr.employee", string="Assessor", required=True)
    assessment_date = fields.Date(string="Assessment Date", default=fields.Date.context_today)
    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    active = fields.Boolean(default=True)

    recruitment_type = fields.Selection([
        ('Internal', 'Internal Recruitment'),
        ('External', 'External Recruitment')
    ], string="Recruitment Type", default='Internal')

    assessment_criteria = fields.Many2one("assessment.criteria", string="Assessment Criteria")
    weightage = fields.Float(string="Total Marks")
    candidate_attendance = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent')
    ], string="Attendance", default='present')
    marks_awarded = fields.Float(string="Marks Awarded")

    # Dynamic Rate Sheet Evaluation additions
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted')
    ], string="State", default='draft', required=True, copy=False)

    candidate_assessment_ids = fields.One2many(
        "interview.candidate.assessment",
        "assessment_id",
        string="Candidate Assessment Ratings"
    )
    criteria_score_ids = fields.One2many(
        "interview.criteria.score",
        "assessment_id",
        string="Rate Sheet Criteria Scores"
    )
    total_score = fields.Float(string="Total Score", compute="_compute_total_score", store=True)

    @api.depends("candidate_assessment_ids.percentage_score")
    def _compute_total_score(self):
        for rec in self:
            if rec.candidate_assessment_ids:
                rec.total_score = sum(c.percentage_score for c in rec.candidate_assessment_ids) / len(rec.candidate_assessment_ids)
            else:
                rec.total_score = 0.0

    @api.constrains('state', 'candidate_assessment_ids')
    def _check_submission_lock(self):
        for rec in self:
            if rec.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                pass  # Readonly constraint enforced in write()

    def write(self, vals):
        for rec in self:
            if rec.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can edit it. The assessment is strictly read-only."))
        return super().write(vals)

    def action_submit(self):
        for rec in self:
            if rec.state == 'submitted':
                continue
            # Recompute and validate scores for ALL candidates evaluated by this interviewer
            for cand_ass in rec.candidate_assessment_ids:
                cand_ass._compute_scores()
                cand_ass._validate_criteria_scores()
            rec._compute_total_score()
            rec.with_context(bypass_submission_lock=True).write({'state': 'submitted'})
            if rec.session_id:
                rec.session_id._check_and_auto_complete()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Submitted'),
                'message': _('All candidate evaluations for this interviewer have been computed and submitted successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def unlink(self):
        for rec in self:
            if rec.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can delete it. The assessment is strictly read-only."))
            rec.write({"active": False})
        return True


class InterviewCandidateAssessment(models.Model):
    _name = "interview.candidate.assessment"
    _description = "Interview Candidate Assessment"
    _order = "id asc"

    assessment_id = fields.Many2one("interview.assessment", string="Interviewer Assessment", ondelete="cascade", required=True)
    applicant_id = fields.Many2one("hr.applicant", string="External Applicant")
    employee_id = fields.Many2one("hr.employee", string="Internal Employee")
    candidate_name = fields.Char(string="Candidate Name", compute="_compute_candidate_name", store=True)

    attendance = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent')
    ], string="Attendance", default='present')

    criteria_score_ids = fields.One2many(
        "interview.criteria.score",
        "candidate_assessment_id",
        string="Criteria Scores"
    )
    total_marks = fields.Float(string="Total Marks Awarded", compute="_compute_scores", store=True)
    total_max_marks = fields.Float(string="Total Max Marks", compute="_compute_scores", store=True)
    percentage_score = fields.Float(string="Score (%)", compute="_compute_scores", store=True)
    notes = fields.Text(string="Interviewer Remarks / Feedback")

    def write(self, vals):
        for rec in self:
            if rec.assessment_id and rec.assessment_id.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can edit candidate ratings. It is strictly read-only."))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.assessment_id and rec.assessment_id.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can delete candidate ratings. It is strictly read-only."))
        return super().unlink()

    @api.depends("applicant_id", "employee_id")
    def _compute_candidate_name(self):
        for rec in self:
            if rec.applicant_id:
                rec.candidate_name = rec.applicant_id.partner_name or rec.applicant_id.name
            elif rec.employee_id:
                rec.candidate_name = rec.employee_id.name
            else:
                rec.candidate_name = _("Unknown Candidate")

    @api.depends("criteria_score_ids.marks_awarded", "criteria_score_ids.max_marks", "attendance")
    def _compute_scores(self):
        for rec in self:
            if rec.attendance == 'absent':
                rec.total_marks = 0.0
                rec.total_max_marks = sum(c.max_marks for c in rec.criteria_score_ids)
                rec.percentage_score = 0.0
            else:
                tot = sum(c.marks_awarded for c in rec.criteria_score_ids)
                tot_max = sum(c.max_marks for c in rec.criteria_score_ids)
                rec.total_marks = tot
                rec.total_max_marks = tot_max
                if tot_max > 0:
                    rec.percentage_score = round((tot / tot_max) * 100.0, 2)
                else:
                    rec.percentage_score = tot

    def _validate_criteria_scores(self):
        for rec in self:
            if rec.attendance == 'present':
                for cs in rec.criteria_score_ids:
                    if cs.marks_awarded < 0 or cs.marks_awarded > cs.max_marks:
                        raise ValidationError(_(
                            "Invalid score given for candidate '%s' under criterion '%s'. Marks awarded (%.2f) must be between 0 and %.2f."
                        ) % (rec.candidate_name, cs.criteria_name, cs.marks_awarded, cs.max_marks))


class InterviewCriteriaScore(models.Model):
    _name = "interview.criteria.score"
    _description = "Interview Criteria Score"
    _order = "sequence asc, id asc"

    candidate_assessment_id = fields.Many2one("interview.candidate.assessment", string="Candidate Assessment", ondelete="cascade", required=True)
    assessment_id = fields.Many2one("interview.assessment", string="Interviewer Assessment", ondelete="cascade", index=True)
    candidate_name = fields.Char(related="candidate_assessment_id.candidate_name", string="Candidate Name", store=True)
    criteria_line_id = fields.Many2one("interview.rate.sheet.line", string="Criteria Line", required=True)
    sequence = fields.Integer(related="criteria_line_id.sequence", store=True)
    criteria_name = fields.Char(related="criteria_line_id.name", string="Area of Assessment", store=True)
    max_marks = fields.Float(related="criteria_line_id.max_marks", string="Max Marks", store=True)
    marks_awarded = fields.Float(string="Marks Awarded", default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('assessment_id') and vals.get('candidate_assessment_id'):
                cand_ass = self.env['interview.candidate.assessment'].browse(vals['candidate_assessment_id'])
                if cand_ass and cand_ass.assessment_id:
                    vals['assessment_id'] = cand_ass.assessment_id.id
        return super().create(vals_list)

    def write(self, vals):
        for cs in self:
            if cs.candidate_assessment_id.assessment_id and cs.candidate_assessment_id.assessment_id.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can edit criteria marks. It is strictly read-only."))
        return super().write(vals)

    def unlink(self):
        for cs in self:
            if cs.candidate_assessment_id.assessment_id and cs.candidate_assessment_id.assessment_id.state == 'submitted' and not self.env.context.get('bypass_submission_lock'):
                raise ValidationError(_("Once an interviewer submits the result, no one can delete criteria marks. It is strictly read-only."))
        return super().unlink()

    @api.constrains("marks_awarded", "max_marks")
    def _check_marks_awarded(self):
        for cs in self:
            if cs.marks_awarded < 0:
                raise ValidationError(_("Marks awarded cannot be negative."))
            if cs.max_marks and cs.marks_awarded > cs.max_marks:
                raise ValidationError(_(
                    "Marks awarded (%.2f) for '%s' exceeds maximum allowed marks (%.2f)."
                ) % (cs.marks_awarded, cs.criteria_name, cs.max_marks))


class InterviewFinalResult(models.Model):
    _name = "interview.final.result"
    _description = "Final Interview Result"
    _order = "final_score desc, id asc"

    session_id = fields.Many2one("interview.session", string="Interview Session", ondelete="cascade", required=True)
    applicant_id = fields.Many2one("hr.applicant", string="Applicant")
    employee_id = fields.Many2one("hr.employee", string="Employee")
    candidate_name = fields.Char(string="Candidate Name", required=True)
    attendance = fields.Selection([('present', 'Present'), ('absent', 'Absent')], string="Attendance", default='present')
    no_of_assessments = fields.Integer(string="Interviewer Count")
    individual_score_summary = fields.Text(string="Individual Scores")
    final_score = fields.Float(string="Calculated Final Average Score", digits=(5, 2))
    result_status = fields.Selection([('passed', 'Passed'), ('failed', 'Failed')], string="Result Status", default='passed')

    detail_line_ids = fields.One2many("interview.final.result.line", "final_result_id", string="Interviewer Score Breakdown")


class InterviewFinalResultLine(models.Model):
    _name = "interview.final.result.line"
    _description = "Interview Final Result Line"
    _order = "id asc"

    final_result_id = fields.Many2one("interview.final.result", string="Final Result", ondelete="cascade", required=True)
    interviewer_id = fields.Many2one("hr.employee", string="Interviewer")
    interviewer_name = fields.Char(string="Interviewer Name")
    score = fields.Float(string="Interviewer Score (%)", digits=(5, 2))
    submitted_date = fields.Date(string="Date")
