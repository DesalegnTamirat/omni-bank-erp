# -*- coding: utf-8 -*-

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class CBISInterviewSession(models.Model):
    """
    Competency-Based Interview Session (FR-CBIS-001 - FR-CBIS-012)
    =============================================================
    Manages interview cohorts linked to Job Vacancies, Managerial vs Non-Managerial
    types, multi-interviewer panel assignments, document verification gates, and
    >= 50% written exam qualification checks.
    """
    _name = "cbis.interview.session"
    _description = "CBIS Interview Session Cohort"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "interview_date desc, id desc"

    name = fields.Char(string="Session Reference", required=True, copy=False, readonly=True, default=lambda self: _("New"))
    
    # Vacancy from Recruitment (FR-CBIS-001, FR-CBIS-002)
    vacancy_id = fields.Many2one("job.vacancy", string="Job Vacancy", required=True, tracking=True, index=True)
    vacancy_reference = fields.Char(related="vacancy_id.reference", string="Vacancy Number", readonly=True, store=True)
    job_id = fields.Many2one(related="vacancy_id.job_position", string="Job Position", readonly=True, store=True)

    interview_type = fields.Selection([
        ("managerial", "Managerial  Interview"),
        ("non_managerial", "Non-Managerial  Interview"),
        ("junior", "Junior Interview"),
        ("transfer", " Transfer Interview"),
    ], string="Interview Type", default="non_managerial", required=True, tracking=True)

    interview_date = fields.Date(string="Interview Date", required=True, default=fields.Date.context_today, tracking=True)
    venue = fields.Char(string="Location / Room / Virtual Meeting Link", required=True)

    # Assigned Panel Members (FR-CBIS-009)
    panel_member_ids = fields.Many2many(
        "res.users",
        "cbis_session_panel_users_rel",
        "session_id",
        "user_id",
        string="Interview Panel Members",
        required=True,
        tracking=True
    )
    hr_observer_id = fields.Many2one("res.users", string="HR Observer / Facilitator", default=lambda self: self.env.user)

    # Candidates Assigned to Session (FR-CBIS-008, FR-CBIS-010)
    candidate_line_ids = fields.One2many("cbis.interview.candidate", "session_id", string="Scheduled Candidates")

    weight_profile_id = fields.Many2one("assessment.weight.profile", string="Scoring Weight Profile", tracking=True)
    
    candidate_count = fields.Integer(string="Candidates", compute="_compute_session_counts", store=True)
    completed_count = fields.Integer(string="Evaluated & Locked", compute="_compute_session_counts", store=True)

    # Competency Configuration & Weighting (Max 100%)
    competency_line_ids = fields.One2many("cbis.session.competency.line", "session_id", string="Competency Configuration & Weighting", copy=True)
    total_competency_weight = fields.Float(string="Total Weight (%)", compute="_compute_total_competency_weight", store=True)

    state = fields.Selection([
        ("draft", "Draft Schedule"),
        ("confirmed", "Confirmed / Panel Dispatched"),
        ("in_progress", "Interviews in Progress"),
        ("completed", "Completed & Locked"),
    ], string="Session Status", default="draft", tracking=True, required=True)

    @api.depends("competency_line_ids.weight_percentage")
    def _compute_total_competency_weight(self):
        for rec in self:
            rec.total_competency_weight = round(sum(line.weight_percentage for line in rec.competency_line_ids), 2)

    @api.constrains("competency_line_ids", "competency_line_ids.weight_percentage")
    def _check_total_competency_weight(self):
        for rec in self:
            if rec.competency_line_ids:
                tot = sum(line.weight_percentage for line in rec.competency_line_ids)
                if tot > 100.001:
                    raise ValidationError(_("The total percentage weight of all selected competencies must not exceed 100%%. Current total is %.2f%%.") % tot)


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("cbis.interview.session") or _("INT/%05d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("candidate_line_ids.state")
    def _compute_session_counts(self):
        for rec in self:
            rec.candidate_count = len(rec.candidate_line_ids)
            rec.completed_count = len(rec.candidate_line_ids.filtered(lambda c: c.state == "locked"))

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id_populate(self):
        """Auto-populates panel members and qualifying candidates when Vacancy is selected."""
        if not self.vacancy_id:
            return

        # 1. Auto-populate Panel Members
        panel_users = self._fetch_vacancy_panel_users()
        if panel_users:
            self.panel_member_ids = [(6, 0, panel_users.ids)]

        # 2. Auto-populate Candidates
        candidate_vals_list = self._fetch_vacancy_interview_candidates()
        if candidate_vals_list:
            lines = []
            for vals in candidate_vals_list:
                lines.append((0, 0, {
                    "candidate_type": vals["candidate_type"],
                    "employee_id": vals["employee_id"],
                    "applicant_id": vals["applicant_id"],
                    "exam_score_percentage": vals["exam_score_percentage"],
                    "passed_written_exam": vals["passed_written_exam"],
                    "documents_verified": vals["documents_verified"],
                }))
            self.candidate_line_ids = [(5, 0, 0)] + lines

        # 3. Auto-populate Competencies from Job Position Profile
        target_job = self.vacancy_id.job_position
        if target_job and not self.competency_line_ids:
            job_comp_rels = self.env["assessment.competency.job.rel"].search([("job_id", "=", target_job.id)])
            if job_comp_rels:
                c_lines = []
                for idx, rel in enumerate(job_comp_rels, start=1):
                    comp = rel.competency_id
                    q_prompt = comp.question_ids[0].name if hasattr(comp, 'question_ids') and comp.question_ids else ""
                    c_lines.append((0, 0, {
                        "competency_id": comp.id,
                        "evaluation_method": getattr(comp, "evaluation_method", False) or rel.evaluation_method or "star",
                        "weight_percentage": rel.weight_percentage,
                        "suggested_question": q_prompt,
                        "sequence": rel.sequence or idx * 10,
                    }))
                self.competency_line_ids = [(5, 0, 0)] + c_lines
            else:
                default_comps = self.env["competency.competency"].search([("status", "=", "active")], limit=4)
                if not default_comps:
                    default_comps = self.env["competency.competency"].search([], limit=4)
                if default_comps:
                    weight_each = round(100.0 / len(default_comps), 2)
                    c_lines = []
                    for idx, comp in enumerate(default_comps, start=1):
                        q_prompt = comp.question_ids[0].name if hasattr(comp, 'question_ids') and comp.question_ids else ""
                        c_lines.append((0, 0, {
                            "competency_id": comp.id,
                            "evaluation_method": getattr(comp, "evaluation_method", False) or "star",
                            "weight_percentage": weight_each,
                            "suggested_question": q_prompt,
                            "sequence": idx * 10,
                        }))
                    self.competency_line_ids = [(5, 0, 0)] + c_lines


    @api.onchange("weight_profile_id")
    def _onchange_weight_profile_id(self):
        """Recalculates composite weighted total scores for candidates when weight profile is changed."""
        if self.candidate_line_ids:
            self.candidate_line_ids._compute_final_interview_score()

    def _fetch_vacancy_panel_users(self):
        """Helper to fetch panel member users from new.internal.recruitment.panel, external.recruitment.panel, or vac.panel.members."""
        self.ensure_one()
        if not self.vacancy_id:
            return self.env["res.users"]

        vac = self.vacancy_id
        found_employees = self.env["hr.employee"]

        # 1. Fetch from new.internal.recruitment.selected panel lines (new_int_rec_panel)
        int_sel_records = self.env["new.internal.recruitment.selected"].sudo().search([
            "|", ("vacancy_id", "=", vac.id), ("vacancy_reference", "=", vac.reference)
        ])
        for int_sel in int_sel_records:
            if hasattr(int_sel, "new_int_rec_panel"):
                for p_line in int_sel.new_int_rec_panel:
                    emp = getattr(p_line, "delegate_employee_id", False) or getattr(p_line, "emp_name", False)
                    if emp:
                        found_employees |= emp

        # 2. Fetch from external.recruitment.selected panel lines (ext_rec_panel)
        ext_sel_records = self.env["external.recruitment.selected"].sudo().search([
            "|", ("vacancy_id", "=", vac.id), ("vacancy_reference", "=", vac.reference)
        ])
        for ext_sel in ext_sel_records:
            if hasattr(ext_sel, "ext_rec_panel"):
                for p_line in ext_sel.ext_rec_panel:
                    emp = getattr(p_line, "delegate_employee_id", False) or getattr(p_line, "emp_name", False)
                    if emp:
                        found_employees |= emp

        # 3. Fetch from job.vacancy direct panel members (memb_panel_vac)
        if hasattr(vac, "memb_panel_vac"):
            for p_line in vac.memb_panel_vac:
                emp = getattr(p_line, "delegate_employee_id", False) or getattr(p_line, "employee_id", False)
                if emp:
                    found_employees |= emp

        # 4. Map employees to res.users
        user_ids = set()
        for emp in found_employees:
            if emp.user_id:
                user_ids.add(emp.user_id.id)
            else:
                user = self.env["res.users"].sudo().search([
                    "|", "|",
                    ("employee_id", "=", emp.id),
                    ("partner_id", "=", emp.work_contact_id.id),
                    ("login", "=ilike", emp.work_email or emp.private_email or "")
                ], limit=1)
                if user:
                    user_ids.add(user.id)

        # 5. Direct user_ids on vac.panel.members
        if hasattr(vac, "memb_panel_vac"):
            for p_line in vac.memb_panel_vac:
                if getattr(p_line, "user_id", False):
                    user_ids.add(p_line.user_id.id)

        return self.env["res.users"].browse(list(user_ids))

    def _fetch_vacancy_interview_candidates(self):
        """Helper to fetch qualifying interview candidates (Written Exam >= 50% and select_flag is True)."""
        self.ensure_one()
        if not self.vacancy_id:
            return []

        vac = self.vacancy_id
        target_job = vac.job_position
        candidate_dict = {}

        disqualified_emp_ids = set()
        disqualified_app_ids = set()

        # 1. Check Internal Candidates from new.internal.recruitment.selected
        int_sel_records = self.env["new.internal.recruitment.selected"].sudo().search([
            "|", ("vacancy_id", "=", vac.id), ("vacancy_reference", "=", vac.reference)
        ])
        for sel in int_sel_records:
            if hasattr(sel, "new_int_rec_sel"):
                has_exam = getattr(sel, 'exam_scores_fetched', False) or (getattr(sel, 'written_weight', 0.0) or 0.0) > 0.0
                for cand in sel.new_int_rec_sel:
                    emp_id = cand.emp_name.id if cand.emp_name else False
                    if not emp_id:
                        continue
                    exam_score = cand.written_exam_score or 0.0
                    is_disqualified = False
                    if cand.select_flag is False:
                        is_disqualified = True
                    elif cand.selection_type == 'rejected':
                        is_disqualified = True
                    elif has_exam and exam_score < 50.0:
                        is_disqualified = True

                    if is_disqualified:
                        disqualified_emp_ids.add(emp_id)
                    else:
                        key = ("internal", emp_id)
                        candidate_dict[key] = {
                            "candidate_type": "internal",
                            "employee_id": emp_id,
                            "applicant_id": False,
                            "exam_score_percentage": exam_score if exam_score > 0 else 100.0,
                            "passed_written_exam": True,
                            "documents_verified": True,
                        }

        # 2. Check External Candidates from external.recruitment.selected
        ext_sel_records = self.env["external.recruitment.selected"].sudo().search([
            "|", ("vacancy_id", "=", vac.id), ("vacancy_reference", "=", vac.reference)
        ])
        for sel in ext_sel_records:
            if hasattr(sel, "ext_rec_sel"):
                has_exam = getattr(sel, 'exam_scores_fetched', False) or (getattr(sel, 'written_weight', 0.0) or 0.0) > 0.0
                for cand in sel.ext_rec_sel:
                    app_id = cand.applicant_name.id if cand.applicant_name else False
                    if not app_id:
                        continue
                    exam_score = cand.written_exam_score or 0.0
                    is_disqualified = False
                    if cand.select_flag is False:
                        is_disqualified = True
                    elif cand.selection_type == 'rejected':
                        is_disqualified = True
                    elif has_exam and exam_score < 50.0:
                        is_disqualified = True

                    if is_disqualified:
                        disqualified_app_ids.add(app_id)
                    else:
                        key = ("external", app_id)
                        candidate_dict[key] = {
                            "candidate_type": "external",
                            "employee_id": False,
                            "applicant_id": app_id,
                            "exam_score_percentage": exam_score if exam_score > 0 else 100.0,
                            "passed_written_exam": True,
                            "documents_verified": True,
                        }

        # 3. Written Exam attempts from Assessment System (exam.candidate.attempt)
        domain = [
            ("state", "=", "completed"),
            ("score_percentage", ">=", 50.0),
        ]
        or_conditions = [("session_id.vacancy_id", "=", vac.id), ("exam_id.vacancy_id", "=", vac.id)]
        if target_job:
            or_conditions.append(("job_id", "=", target_job.id))

        if len(or_conditions) == 3:
            domain.extend(["|", "|", or_conditions[0], or_conditions[1], or_conditions[2]])
        elif len(or_conditions) == 2:
            domain.extend(["|", or_conditions[0], or_conditions[1]])
        else:
            domain.append(or_conditions[0])

        exam_attempts = self.env["exam.candidate.attempt"].sudo().search(domain)
        for att in exam_attempts:
            if att.employee_id and att.employee_id.id not in disqualified_emp_ids:
                key = ("internal", att.employee_id.id)
                if key not in candidate_dict:
                    candidate_dict[key] = {
                        "candidate_type": "internal",
                        "employee_id": att.employee_id.id,
                        "applicant_id": False,
                        "exam_score_percentage": att.score_percentage,
                        "passed_written_exam": True,
                        "documents_verified": True,
                    }
            elif att.applicant_id and att.applicant_id.id not in disqualified_app_ids:
                key = ("external", att.applicant_id.id)
                if key not in candidate_dict:
                    candidate_dict[key] = {
                        "candidate_type": "external",
                        "employee_id": False,
                        "applicant_id": att.applicant_id.id,
                        "exam_score_percentage": att.score_percentage,
                        "passed_written_exam": True,
                        "documents_verified": True,
                    }

        # Remove any candidate explicitly in disqualified sets
        for emp_id in disqualified_emp_ids:
            candidate_dict.pop(("internal", emp_id), None)
        for app_id in disqualified_app_ids:
            candidate_dict.pop(("external", app_id), None)

        # 4. Fallback: Applicants for Vacancy only if no specific selection list
        if not candidate_dict and not int_sel_records and not ext_sel_records and target_job:
            applicants = self.env["hr.applicant"].sudo().search([
                ("active", "=", True),
                "|", ("job_vacancy_id", "=", vac.id), ("job_id", "=", target_job.id)
            ])
            for app in applicants:
                if app.id not in disqualified_app_ids:
                    key = ("external", app.id)
                    candidate_dict[key] = {
                        "candidate_type": "external",
                        "employee_id": False,
                        "applicant_id": app.id,
                        "exam_score_percentage": 100.0,
                        "passed_written_exam": True,
                        "documents_verified": True,
                    }

        return list(candidate_dict.values())

    def action_load_panel_and_candidates(self):
        """Action button to reload panel members and qualifying candidates from vacancy & recruitment selection tables."""
        for rec in self:
            if not rec.vacancy_id:
                raise UserError(_("Please select a Job Vacancy first."))

            # Load Panel Users
            panel_users = rec._fetch_vacancy_panel_users()
            if panel_users:
                rec.panel_member_ids = [(6, 0, panel_users.ids)]

            # Load Candidates
            candidate_vals_list = rec._fetch_vacancy_interview_candidates()
            valid_emp_ids = {vals["employee_id"] for vals in candidate_vals_list if vals["employee_id"]}
            valid_app_ids = {vals["applicant_id"] for vals in candidate_vals_list if vals["applicant_id"]}

            # 1. Unlink candidates who no longer qualify / failed written exam (<50%) and have no submitted evaluations
            invalid_lines = rec.candidate_line_ids.filtered(
                lambda l: ((l.employee_id and l.employee_id.id not in valid_emp_ids) or
                           (l.applicant_id and l.applicant_id.id not in valid_app_ids)) and
                          (not l.submitted_eval_count or l.submitted_eval_count == 0)
            )
            if invalid_lines:
                invalid_lines.unlink()

            # 2. Add newly qualifying candidates
            if candidate_vals_list:
                existing_emp_ids = set(rec.candidate_line_ids.mapped("employee_id.id"))
                existing_app_ids = set(rec.candidate_line_ids.mapped("applicant_id.id"))

                new_lines = []
                for vals in candidate_vals_list:
                    emp_id = vals["employee_id"]
                    app_id = vals["applicant_id"]
                    if emp_id and emp_id in existing_emp_ids:
                        continue
                    if app_id and app_id in existing_app_ids:
                        continue

                    new_lines.append((0, 0, {
                        "session_id": rec.id,
                        "candidate_type": vals["candidate_type"],
                        "employee_id": emp_id,
                        "applicant_id": app_id,
                        "exam_score_percentage": vals["exam_score_percentage"],
                        "passed_written_exam": vals["passed_written_exam"],
                        "documents_verified": vals["documents_verified"],
                    }))

                if new_lines:
                    rec.write({"candidate_line_ids": new_lines})

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Auto-Load Complete"),
                    "message": _("Loaded %d panel member(s) and %d candidate(s) from vacancy recruitment selection records.") % (
                        len(rec.panel_member_ids), len(rec.candidate_line_ids)
                    ),
                    "type": "success",
                    "sticky": False,
                }
            }

    def action_confirm_session(self):
        """Dispatches panel assignments and auto-provisions access (FR-CBIS-009, FR-AMS-NOT-07)"""
        for rec in self:
            if not rec.candidate_line_ids:
                raise UserError(_("Please assign at least one candidate before confirming the interview session."))
            if not rec.panel_member_ids:
                raise UserError(_("Please assign at least one panel member to conduct the interview evaluations."))

            for candidate in rec.candidate_line_ids:
                candidate._initialize_evaluations_for_panel()
                candidate.action_send_interview_invitation()
                
            rec.state = "confirmed"
            rec._notify_panel_members()

    def _notify_panel_members(self):
        """Sends notification to panel members via Email, In-App Notification, and Activity (FR-AMS-NOT-07)"""
        for member in self.panel_member_ids:
            subject = _("Interview Panel Assignment: %s - Bunna Bank") % (self.job_id.name or "Position")
            body = _("""
                <p>Dear %s,</p>
                <p>You have been assigned to the Interview Panel for <b>%s</b> (Vacancy Ref: <b>%s</b>).</p>
                <p><b>Date:</b> %s | <b>Venue:</b> %s</p>
                <p>Please log in to your Assessment System Dashboard to view your assigned candidates and evaluate them.</p>
            """) % (member.name, self.job_id.name, self.vacancy_reference, self.interview_date, self.venue)

            # 1. Send Outbound Email
            if member.email:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_to': member.email,
                }).send()

            # 2. Dispatch In-App Notification (Odoo Inbox & Bell Counter)
            if member.partner_id:
                self.env['mail.message'].sudo().create({
                    'subject': subject,
                    'body': body,
                    'model': 'cbis.interview.session',
                    'res_id': self.id,
                    'message_type': 'notification',
                    'partner_ids': [(4, member.partner_id.id)],
                    'notification_ids': [(0, 0, {
                        'res_partner_id': member.partner_id.id,
                        'notification_type': 'inbox',
                        'is_read': False,
                    })],
                })

            # 3. Schedule Activity on Panelist's Profile
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if activity_type:
                self.env['mail.activity'].sudo().create({
                    'res_model_id': self.env['ir.model'].sudo()._get('cbis.interview.session').id,
                    'res_id': self.id,
                    'activity_type_id': activity_type.id,
                    'summary': _("Conduct Interview Panel: %s") % (self.job_id.name or "Session"),
                    'note': body,
                    'user_id': member.id,
                    'date_deadline': self.interview_date or fields.Date.today(),
                })


class CBISInterviewCandidate(models.Model):
    """
    Scheduled Candidate for Competency Interview (FR-CBIS-008, BR-AMS-15, BR-AMS-16)
    ================================================================================
    Enforces eligibility: Candidate must have written exam >= 50% (or direct assign),
    and External Candidates must have 'Original Documents Verified' checked.
    """
    _name = "cbis.interview.candidate"
    _description = "Scheduled Candidate Interview Record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "session_id desc, scheduled_time asc, id asc"
    _sql_constraints = [
        ("session_employee_uniq", "unique(session_id, employee_id)", "An internal employee can only be listed once per interview session!"),
        ("session_applicant_uniq", "unique(session_id, applicant_id)", "An external applicant can only be listed once per interview session!"),
    ]

    def _auto_init(self):
        res = super()._auto_init()
        # Clean up un-evaluated duplicate candidate rows and disqualified (<50% written exam / unselected) candidate rows
        self.env.cr.execute("""
            DELETE FROM cbis_interview_candidate c1
            USING cbis_interview_candidate c2
            WHERE c1.session_id = c2.session_id
              AND (
                  (c1.employee_id IS NOT NULL AND c1.employee_id = c2.employee_id)
                  OR (c1.applicant_id IS NOT NULL AND c1.applicant_id = c2.applicant_id)
              )
              AND c1.id < c2.id
              AND (c1.submitted_eval_count IS NULL OR c1.submitted_eval_count = 0);

            DELETE FROM cbis_interview_candidate cic
            USING new_internal_recruitment_selected_candidates nisc, new_internal_recruitment_selected nis, cbis_interview_session cis
            WHERE cic.session_id = cis.id
              AND (cis.vacancy_id = nis.vacancy_id OR (cis.vacancy_reference IS NOT NULL AND cis.vacancy_reference = nis.vacancy_reference))
              AND nisc.new_int_sel_cand = nis.id
              AND cic.employee_id = nisc.emp_name
              AND ((nis.exam_scores_fetched = TRUE OR COALESCE(nis.written_weight, 0) > 0) AND (nisc.written_exam_score < 50.0 OR nisc.select_flag = FALSE))
              AND (cic.submitted_eval_count IS NULL OR cic.submitted_eval_count = 0);
        """)
        return res

    session_id = fields.Many2one("cbis.interview.session", string="Interview Session", required=True, ondelete="cascade", index=True)
    vacancy_id = fields.Many2one(related="session_id.vacancy_id", string="Vacancy", readonly=True, store=True)
    job_id = fields.Many2one(related="session_id.job_id", string="Job Position", readonly=True, store=True)

    candidate_type = fields.Selection([
        ("external", "External Applicant"),
        ("internal", "Internal Employee"),
        ("transfer", "Transfer Applicant"),
    ], string="Candidate Type", default="external", required=True)

    applicant_id = fields.Many2one("hr.applicant", string="Recruitment Applicant", index=True)
    employee_id = fields.Many2one("hr.employee", string="Internal Employee", index=True)

    candidate_name = fields.Char(string="Candidate Name", compute="_compute_candidate_info", store=True)
    candidate_code = fields.Char(string="Candidate / Employee ID", compute="_compute_candidate_info", store=True, index=True)
    candidate_email = fields.Char(string="Email", compute="_compute_candidate_info", store=True)
    candidate_phone = fields.Char(string="Phone", compute="_compute_candidate_info", store=True)

    scheduled_time = fields.Datetime(string="Scheduled Time Slot")
    
    # Eligibility Gates (BR-AMS-15, BR-AMS-16)
    exam_score_percentage = fields.Float(string="Written Exam Score (%)", readonly=True, default=100.0)
    passed_written_exam = fields.Boolean(string="Passed Written Exam (>=50%)", default=True)
    documents_verified = fields.Boolean(
        string="Original Documents Verified",
        default=False,
        help="Mandatory verification check for external candidates prior to interview."
    )

    # Panel Evaluations (FR-CBIS-013 - FR-CBIS-023)
    evaluation_ids = fields.One2many("cbis.interviewer.evaluation", "candidate_interview_id", string="Interviewer Evaluation Sheets")
    
    panel_count = fields.Integer(string="Total Panelists", compute="_compute_evaluation_progress", store=True)
    submitted_eval_count = fields.Integer(string="Submitted Evaluations", compute="_compute_evaluation_progress", store=True)
    
    # Composite Interview Score Calculation
    is_absent = fields.Boolean(string="Candidate Marked Absent", default=False, tracking=True)
    average_interview_score = fields.Float(string="Average Interview Score (%)", compute="_compute_final_interview_score", store=True, tracking=True)
    pms_rating_score = fields.Float(string="PMS Rating Score (%)", readonly=True, help="FR-CBIS-031: Read from HRIS PMS")
    composite_total_score = fields.Float(string="Composite Weighted Total (%)", compute="_compute_final_interview_score", store=True, tracking=True)
    
    is_passed = fields.Boolean(string="Passed All Assessment Floors (>=50%)", compute="_compute_final_interview_score", store=True)

    state = fields.Selection([
        ("pending", "Pending Interview"),
        ("in_progress", "Interview in Progress"),
        ("evaluated", "Evaluations Completed"),
        ("locked", "Locked & Read-Only"),
        ("absent", "Marked Absent (0 Marks)"),
    ], string="Candidate Status", default="pending", tracking=True, required=True)

    @api.depends(
        "applicant_id", "employee_id", "candidate_type",
        "employee_id.name", "employee_id.barcode", "employee_id.identification_id",
        "applicant_id.partner_name"
    )
    def _compute_candidate_info(self):
        for rec in self:
            if rec.employee_id:
                rec.candidate_name = rec.employee_id.name or "Internal Employee"
                rec.candidate_code = (
                    rec.employee_id.barcode
                    or getattr(rec.employee_id, "emp_id", False)
                    or rec.employee_id.identification_id
                    or f"EMP-{rec.employee_id.id:05d}"
                )
                rec.candidate_email = rec.employee_id.work_email or rec.employee_id.private_email
                rec.candidate_phone = rec.employee_id.mobile_phone or rec.employee_id.work_phone
                if rec.candidate_type != "internal":
                    rec.candidate_type = "internal"

            elif rec.applicant_id:
                rec.candidate_name = rec.applicant_id.partner_name or getattr(rec.applicant_id, "name", False) or "External Applicant"
                rec.candidate_code = getattr(rec.applicant_id, "applicant_number", False) or f"CAND-{rec.applicant_id.id:05d}"
                rec.candidate_email = rec.applicant_id.email_from
                rec.candidate_phone = rec.applicant_id.partner_phone or rec.applicant_id.partner_mobile
                if rec.candidate_type != "external":
                    rec.candidate_type = "external"

            else:
                rec.candidate_name = False
                rec.candidate_code = False
                rec.candidate_email = False
                rec.candidate_phone = False

    @api.onchange("employee_id", "applicant_id", "candidate_type")
    def _onchange_candidate_info_live(self):
        self._compute_candidate_info()

    @api.depends("evaluation_ids.state")
    def _compute_evaluation_progress(self):
        for rec in self:
            rec.panel_count = len(rec.evaluation_ids)
            rec.submitted_eval_count = len(rec.evaluation_ids.filtered(lambda e: e.state == "submitted"))

    @api.depends(
        "evaluation_ids.total_score", "evaluation_ids.state", "is_absent",
        "exam_score_percentage", "pms_rating_score", "session_id.weight_profile_id"
    )
    def _compute_final_interview_score(self):
        for rec in self:
            if rec.is_absent:
                rec.average_interview_score = 0.0
                rec.composite_total_score = 0.0
                rec.is_passed = False
                continue

            submitted_evals = rec.evaluation_ids.filtered(lambda e: e.state == "submitted")
            if submitted_evals:
                rec.average_interview_score = round(sum(e.total_score for e in submitted_evals) / len(submitted_evals), 2)
            else:
                rec.average_interview_score = 0.0

            # Compute weighted composite score via Weight Profile or default 50/50 distribution
            profile = rec.session_id.weight_profile_id
            if profile and profile.line_ids:
                composite_val = 0.0
                for line in profile.line_ids:
                    if line.component == "exam":
                        composite_val += (rec.exam_score_percentage * (line.weight_percentage / 100.0))
                    elif line.component == "interview":
                        composite_val += (rec.average_interview_score * (line.weight_percentage / 100.0))
                    elif line.component == "pms":
                        composite_val += (rec.pms_rating_score * (line.weight_percentage / 100.0))
                rec.composite_total_score = round(composite_val, 2)
            else:
                rec.composite_total_score = round((rec.exam_score_percentage * 0.5) + (rec.average_interview_score * 0.5), 2)

            exam_ok = (rec.exam_score_percentage >= 50.0)
            interview_ok = (rec.average_interview_score >= 50.0 or not submitted_evals)
            rec.is_passed = (exam_ok and interview_ok)
            rec._sync_interview_score_to_recruitment()

    def _sync_interview_score_to_recruitment(self):
        """Syncs candidate average_interview_score to recruitment selection records (new.internal.recruitment.selected.candidates & external.recruitment.selected.candidates)."""
        for rec in self:
            score = rec.average_interview_score or 0.0
            if rec.employee_id:
                int_cands = self.env["new.internal.recruitment.selected.candidates"].sudo().search([
                    ("emp_name", "=", rec.employee_id.id)
                ])
                if int_cands:
                    int_cands.write({"interview_score": score})

            if rec.applicant_id:
                ext_cands = self.env["external.recruitment.selected.candidates"].sudo().search([
                    ("applicant_name", "=", rec.applicant_id.id)
                ])
                if ext_cands:
                    ext_cands.write({"interview_score": score})

    def _initialize_evaluations_for_panel(self):
        """Creates individual evaluation sheets for each assigned panel member"""
        self.ensure_one()
        for panelist in self.session_id.panel_member_ids:
            existing = self.evaluation_ids.filtered(lambda e: e.interviewer_user_id == panelist)
            if not existing:
                eval_sheet = self.env["cbis.interviewer.evaluation"].create({
                    "candidate_interview_id": self.id,
                    "interviewer_user_id": panelist.id,
                })
                eval_sheet._initialize_competency_lines()

    @api.constrains("candidate_type", "documents_verified")
    def _check_document_verification(self):
        """BR-AMS-16, FR-EXM-051: External candidates require verified documents"""
        for rec in self:
            if rec.candidate_type == "external" and not rec.documents_verified and rec.session_id.state != "draft":
                raise ValidationError(_(
                    "Validation Error: Original documents must be verified for external candidate '%s' before interview confirmation.",
                    rec.candidate_name
                ))

    def action_mark_absent(self):
        """First-class action: Marks candidate absent with zero marks (FR-CBIS-020)"""
        for rec in self:
            rec.write({
                "is_absent": True,
                "state": "absent",
            })
            for ev in rec.evaluation_ids:
                ev.write({"state": "submitted", "is_absent": True, "total_score": 0.0})
            rec.message_post(body=_("Candidate marked ABSENT from interview by panel."))

    def action_send_interview_invitation(self):
        """Sends interview invitation via Email and Discuss Direct Message (FR-AMS-NOT-03)"""
        for rec in self:
            subject = _("Interview Invitation: %s - Bunna Bank") % (rec.job_id.name or "Position")
            body = _("""
                <p>Dear %(name)s,</p>
                <p>You have been shortlisted for the Interview for position <b>%(job)s</b>.</p>
                <p><b>Date:</b> %(date)s<br/><b>Location:</b> %(venue)s</p>
                <p>All The Best!</p>
            """) % {
                'name': rec.candidate_name,
                'job': rec.job_id.name or "Position",
                'date': rec.scheduled_time or rec.session_id.interview_date,
                'venue': rec.session_id.venue or "Head Office",
            }
            if rec.candidate_email:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_to': rec.candidate_email,
                }).send()

            target_partner = False
            if rec.employee_id:
                target_partner = rec.employee_id.user_id.partner_id or rec.employee_id.work_contact_id
            elif rec.applicant_id and rec.applicant_id.partner_id:
                target_partner = rec.applicant_id.partner_id

            if target_partner:
                try:
                    cand_name = rec.candidate_name or target_partner.name
                    job_title = rec.job_id.name or "Position"
                    int_date = str(rec.scheduled_time or rec.session_id.interview_date)
                    int_venue = rec.session_id.venue or "Head Office"

                    discuss_msg = Markup(
                        f"<p>Dear <b>{cand_name}</b>,<br/>"
                        f"You have been shortlisted for the Interview for position <b>{job_title}</b>.<br/>"
                        f"Date: {int_date}<br/>"
                        f"Location: {int_venue}<br/><br/>"
                        f"All The Best!</p>"
                    )
                    chat = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[target_partner.id])
                    if chat:
                        chat.message_post(body=discuss_msg, message_type='comment', subtype_xmlid='mail.mt_comment')
                except Exception:
                    pass


class CBISSessionCompetencyLine(models.Model):
    """
    Session-level Competency Selection and Percentage Weighting (Max 100% Total Weight).
    Configured by HR and Interviewers prior to evaluation.
    """
    _name = "cbis.session.competency.line"
    _description = "Session Competency Weight Configuration Line"
    _order = "sequence asc, id asc"

    session_id = fields.Many2one("cbis.interview.session", string="Interview Session", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    
    competency_id = fields.Many2one("competency.competency", string="Competency", required=True)
    evaluation_method = fields.Selection([
        ("star", "STAR Method (Situation, Task, Action, Result)"),
        ("starr", "STARR Method (Situation, Task, Action, Result, Reflection)"),
        ("likert", "Likert Scale (1 - 5 Behavioral Anchors)"),
    ], string="Evaluation Method", default="star", required=True)

    weight_percentage = fields.Float(
        string="Weight (%)",
        required=True,
        default=25.0,
        help="Percentage weight of this competency in the interview evaluation (Total across competencies must not exceed 100%)."
    )

    suggested_question = fields.Text(string="Suggested Question Prompt")

    @api.onchange("competency_id")
    def _onchange_competency_id(self):
        if self.competency_id:
            if hasattr(self.competency_id, "evaluation_method") and self.competency_id.evaluation_method:
                self.evaluation_method = self.competency_id.evaluation_method
            if hasattr(self.competency_id, "question_ids") and self.competency_id.question_ids:
                self.suggested_question = self.competency_id.question_ids[0].name

    @api.constrains("weight_percentage")
    def _check_weight_percentage(self):
        for line in self:
            if line.weight_percentage <= 0 or line.weight_percentage > 100:
                raise ValidationError(_("Competency weight percentage must be greater than 0% and at most 100%."))

