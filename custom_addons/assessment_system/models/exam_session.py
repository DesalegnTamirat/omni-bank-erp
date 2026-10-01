# -*- coding: utf-8 -*-

import secrets
import random
from datetime import datetime, timedelta
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ExamSession(models.Model):
    """
    ==========================================================
    Represents a scheduled cohort sitting for a specific exam with defined
    start/end windows, invigilators, candidate assignments, and proctoring logs.
    """
    _name = "exam.session"
    _description = "Exam Sitting Session"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_datetime desc, id desc"

    name = fields.Char(string="Session Reference", required=True, copy=False, readonly=True, default=lambda self: _("New"))
    exam_id = fields.Many2one(
        "exam.definition",
        string="Exam Definition",
        domain="[('is_version_paper', '=', False)]",
        required=True,
        tracking=True,
        index=True
    )
    job_id = fields.Many2one("hr.job", string="Job Position", store=True)
    vacancy_id = fields.Many2one("job.vacancy", string="Job Vacancy", store=True)

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id(self):
        if self.vacancy_id:
            if hasattr(self.vacancy_id, "job_position") and self.vacancy_id.job_position:
                self.job_id = self.vacancy_id.job_position.id
            # Auto-find matching Exam Definition for this vacancy/job
            exam = self.env["exam.definition"].search([
                "|", ("vacancy_id", "=", self.vacancy_id.id), ("job_id", "=", self.job_id.id if self.job_id else False),
                ("is_version_paper", "=", False), ("state", "in", ["confirmed", "draft"])
            ], limit=1)
            if exam:
                self.exam_id = exam.id

    @api.onchange("job_id")
    def _onchange_job_id(self):
        if self.job_id and not self.exam_id:
            exam = self.env["exam.definition"].search([
                ("job_id", "=", self.job_id.id),
                ("is_version_paper", "=", False),
                ("state", "in", ["confirmed", "draft"])
            ], limit=1)
            if exam:
                self.exam_id = exam.id

    @api.onchange("exam_id")
    def _onchange_exam_id(self):
        if self.exam_id:
            if self.exam_id.job_id and not self.job_id:
                self.job_id = self.exam_id.job_id.id
            if self.exam_id.vacancy_id and not self.vacancy_id:
                self.vacancy_id = self.exam_id.vacancy_id.id

    start_datetime = fields.Datetime(string="Scheduled Start Time", required=True, tracking=True)
    end_datetime = fields.Datetime(string="Scheduled End Time", required=True, tracking=True)
    duration_minutes = fields.Integer(related="exam_id.duration_minutes", string="Duration (Mins)", readonly=True)
    
    venue_type = fields.Selection([
        ("online", "Online / Remote Proctoring"),
        ("lab", "Physical Computer Lab / Exam Hall"),
    ], string="Venue Type", default="online", required=True)
    
    location_notes = fields.Char(string="Hall / Lab Name or Online Portal URL")
    invigilator_user_ids = fields.Many2many("res.users", string="Assigned Invigilators / Proctors")

    attempt_ids = fields.One2many("exam.candidate.attempt", "session_id", string="Candidate Exam Attempts")
    
    candidate_count = fields.Integer(string="Total Candidates", compute="_compute_candidate_stats", store=True)
    completed_count = fields.Integer(string="Completed", compute="_compute_candidate_stats", store=True)
    disqualified_count = fields.Integer(string="Disqualified", compute="_compute_candidate_stats", store=True)
    passed_count = fields.Integer(string="Passed", compute="_compute_candidate_stats", store=True)

    state = fields.Selection([
        ("draft", "Draft"),
        ("scheduled", "Scheduled / Invitations Ready"),
        ("active", "Live / In Progress"),
        ("evaluating", "Grading in Progress"),
        ("completed", "Completed / Results Finalized"),
        ("cancelled", "Cancelled"),
    ], string="Session State", default="draft", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.session") or _("SESS/%05d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("attempt_ids.state", "attempt_ids.is_passed")
    def _compute_candidate_stats(self):
        for rec in self:
            attempts = rec.attempt_ids
            rec.candidate_count = len(attempts)
            rec.completed_count = len(attempts.filtered(lambda a: a.state == "completed"))
            rec.disqualified_count = len(attempts.filtered(lambda a: a.state == "disqualified"))
            rec.passed_count = len(attempts.filtered(lambda a: a.state == "completed" and a.is_passed))

    def action_schedule(self):
        for rec in self:
            if not rec.attempt_ids:
                raise UserError(_("Please assign at least one candidate before scheduling the session."))
            rec.state = "scheduled"

    def action_start_session(self):
        for rec in self:
            rec.state = "active"

    def action_close_session(self):
        for rec in self:
            # Auto-submit any still in-progress attempts
            in_progress = rec.attempt_ids.filtered(lambda a: a.state == "in_progress")
            for att in in_progress:
                att.action_auto_submit(reason=_("Exam session closed by administrator."))
            rec.state = "evaluating"

    def action_finalize_results(self):
        for rec in self:
            # Check if all grading tasks are completed
            pending_grading = self.env["exam.grading.task"].search([
                ("attempt_id", "in", rec.attempt_ids.ids),
                ("state", "!=", "verified")
            ])
            if pending_grading:
                raise UserError(_(
                    "Cannot finalize session results: There are %d manual grading tasks still pending verification.",
                    len(pending_grading)
                ))
            rec.state = "completed"

    def action_submit_all_essay_evaluations(self):
        """
        Submits and computes essay evaluations for all candidate attempts in this session/vacancy at once.
        """
        for rec in self:
            for att in rec.attempt_ids:
                att.action_submit_essay_evaluation()
            rec.message_post(body=_("All candidate essay evaluations have been submitted and final exam scores computed."))

    def action_fetch_recruitment_candidates(self):
        """
        Fetches candidates notified for written exam from recruitment selection tables:
        - If Internal Vacancy: fetches candidates from New Internal Recruitment Selected Candidates (new.internal.recruitment.selected.candidates) where exam_notified == 'Yes' / select_flag == True.
        - If External Vacancy: fetches candidates from External Recruitment Selected Candidates (external.recruitment.selected.candidates) where select_flag == True / exam_scheduled == 'Yes'.
        Automatically assigns available multi-version papers (Version A, B, C, D) round-robin.
        """
        self.ensure_one()
        target_vac = self.vacancy_id or (self.exam_id.vacancy_id if self.exam_id else False)
        target_job = self.job_id or (self.vacancy_id.job_position if (target_vac and hasattr(target_vac, 'job_position')) else False) or (self.exam_id.job_id if self.exam_id else False)

        if not target_vac and not target_job:
            raise UserError(_("Please select a Job Vacancy or Job Position first."))

        fetched_candidates = []

        # Determine vacancy sourcing mode: 'internal', 'external', or 'both'
        sourcing_type = getattr(target_vac, 'sourcing_type', '') or ''
        recruitment_type = getattr(target_vac, 'recruitment_type', '') or ''
        movement_type = getattr(target_vac, 'internal_movement_type', '') or ''
        ref_upper = (target_vac.reference or '').upper() if target_vac else ''

        if sourcing_type == 'internal':
            vac_mode = 'internal'
        elif sourcing_type == 'external':
            vac_mode = 'external'
        elif sourcing_type == 'both':
            vac_mode = 'both'
        else:
            # Fallback if sourcing_type is not explicitly defined
            if recruitment_type == 'Internal' or movement_type in ('internal', 'promotion', 'transfer', 'lateral') or 'INT' in ref_upper or 'TRA' in ref_upper:
                vac_mode = 'internal'
            elif recruitment_type == 'External' or movement_type == 'external' or 'EXT' in ref_upper:
                vac_mode = 'external'
            else:
                vac_mode = 'both'

        # 1. Fetch Internal Candidates selected/notified for written exam
        if vac_mode in ('internal', 'both'):
            int_sel_domain = []
            if target_vac:
                int_sel_domain = ['|', ('vacancy_id', '=', target_vac.id), ('vacancy_reference', '=', target_vac.reference)]
            elif target_job:
                int_sel_domain = [('job_position', '=', target_job.id)]

            int_selections = self.env['new.internal.recruitment.selected'].search(int_sel_domain)
            for sel in int_selections:
                for cand in sel.new_int_rec_sel:
                    # Filter candidates strictly selected for written exam
                    is_selected = (
                        (cand.exam_notified == 'Yes' or cand.select_flag) and
                        getattr(cand, 'selection_type', '') != 'rejected' and
                        getattr(cand, 'active', True)
                    )
                    if cand.emp_name and is_selected:
                        fetched_candidates.append({
                            'candidate_type': 'internal',
                            'employee_id': cand.emp_name.id,
                            'applicant_id': False,
                            'candidate_name': cand.emp_name.name,
                        })

            # Also check direct job.vacancy lines if present
            if target_vac and hasattr(target_vac, 'new_int_rec_sel') and target_vac.new_int_rec_sel:
                for cand in target_vac.new_int_rec_sel:
                    is_selected = (
                        (cand.exam_notified == 'Yes' or cand.select_flag) and
                        getattr(cand, 'selection_type', '') != 'rejected' and
                        getattr(cand, 'active', True)
                    )
                    if cand.emp_name and is_selected:
                        fetched_candidates.append({
                            'candidate_type': 'internal',
                            'employee_id': cand.emp_name.id,
                            'applicant_id': False,
                            'candidate_name': cand.emp_name.name,
                        })

        # 2. Fetch External Candidates selected/notified for written exam
        if vac_mode in ('external', 'both'):
            ext_sel_domain = []
            if target_vac:
                ext_sel_domain = ['|', ('vacancy_id', '=', target_vac.id), ('vacancy_reference', '=', target_vac.reference)]
            elif target_job:
                ext_sel_domain = [('job_position', '=', target_job.id)]

            ext_selections = self.env['external.recruitment.selected'].search(ext_sel_domain)
            for sel in ext_selections:
                for cand in sel.ext_rec_sel:
                    is_selected = (
                        (cand.select_flag or cand.exam_notified == 'Yes' or getattr(cand, 'selection_type', '') == 'selected') and
                        getattr(cand, 'selection_type', '') != 'rejected' and
                        getattr(cand, 'active', True)
                    )
                    if cand.applicant_name and is_selected:
                        fetched_candidates.append({
                            'candidate_type': 'external',
                            'employee_id': False,
                            'applicant_id': cand.applicant_name.id,
                            'candidate_name': cand.applicant_name.partner_name or cand.applicant_name.name,
                        })

        # 3. Fallback to hr.applicant pool if no selection record exists yet
        if not fetched_candidates and (target_vac or target_job):
            app_domain = [('active', '=', True)]
            if target_vac and hasattr(self.env['hr.applicant'], 'job_vacancy_id'):
                app_domain.append(('job_vacancy_id', '=', target_vac.id))
            elif target_job:
                app_domain.append(('job_id', '=', target_job.id))
            
            applicants = self.env['hr.applicant'].search(app_domain)
            for app in applicants:
                emp = getattr(app, 'employee_id', False) or (app.partner_id.user_ids.employee_id[:1] if getattr(app.partner_id, 'user_ids', False) else False)
                if vac_mode == 'internal':
                    cand_type = 'internal'
                elif vac_mode == 'external':
                    cand_type = 'external'
                else:
                    cand_type = 'internal' if emp else 'external'
                
                is_selected = (
                    getattr(app, 'select_flag', True) or
                    getattr(app, 'exam_notified', False) == 'Yes' or
                    getattr(app, 'bunna_app_status', '') in ('selected', 'exam_notified', 'shortlisted')
                )
                if is_selected:
                    fetched_candidates.append({
                        'candidate_type': cand_type,
                        'employee_id': emp.id if emp else False,
                        'applicant_id': app.id,
                        'candidate_name': emp.name if emp else (app.partner_name or app.name),
                    })

        if not fetched_candidates:
            raise UserError(_("No candidates notified/selected for written exam were found for this Vacancy / Job Position."))

        # Get available exam versions (Version A, B, C, D) or master exam
        versions = self.exam_id.child_version_ids.filtered(lambda v: v.state in ('confirmed', 'draft')) if self.exam_id else False
        if not versions and self.exam_id:
            versions = self.exam_id

        # Deduplication tracking sets (avoid duplicate attempts by emp_id, app_id, or candidate_name)
        existing_emp_ids = set(self.attempt_ids.mapped('employee_id.id'))
        existing_app_ids = set(self.attempt_ids.mapped('applicant_id.id'))
        existing_names = set(self.attempt_ids.mapped('candidate_name'))

        seen_batch_emp = set()
        seen_batch_app = set()
        seen_batch_names = set()

        created_count = 0
        version_list = list(versions) if versions else []
        num_versions = len(version_list)

        for idx, cand_info in enumerate(fetched_candidates):
            emp_id = cand_info['employee_id']
            app_id = cand_info['applicant_id']
            c_name = (cand_info.get('candidate_name') or '').strip().lower()

            if emp_id and (emp_id in existing_emp_ids or emp_id in seen_batch_emp):
                continue
            if app_id and (app_id in existing_app_ids or app_id in seen_batch_app):
                continue
            if c_name and (c_name in existing_names or c_name in seen_batch_names):
                continue

            # Assign Version Round-Robin if versions exist
            assigned_version = version_list[idx % num_versions] if num_versions > 0 else False

            attempt_vals = {
                'session_id': self.id,
                'candidate_type': cand_info['candidate_type'],
                'employee_id': emp_id,
                'applicant_id': app_id,
                'version_exam_id': assigned_version.id if (assigned_version and assigned_version.is_version_paper) else False,
            }
            self.env['exam.candidate.attempt'].create(attempt_vals)

            if emp_id:
                existing_emp_ids.add(emp_id)
                seen_batch_emp.add(emp_id)
            if app_id:
                existing_app_ids.add(app_id)
                seen_batch_app.add(app_id)
            if c_name:
                existing_names.add(c_name)
                seen_batch_names.add(c_name)

            created_count += 1

        v_summary = ', '.join(v.version_code or v.name for v in version_list) if version_list else _("Master Exam")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Fetched & Versions Assigned'),
                'message': _('Successfully fetched %d candidate(s) notified for written exam and assigned exam versions (%s) round-robin.') % (created_count, v_summary),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_auto_assign_versions(self):
        """
        Distributes and assigns available multi-version papers (Version A, B, C, D)
        evenly across all candidate attempts in this session in round-robin sequence.
        """
        self.ensure_one()
        if not self.attempt_ids:
            raise UserError(_("No candidates found in this session to assign versions to."))
        
        versions = self.exam_id.child_version_ids.filtered(lambda v: v.state in ('confirmed', 'draft'))
        if not versions:
            raise UserError(_("No multi-version papers generated under '%s'. Please click 'Generate Multi-Version Papers' on the Exam Definition first.") % self.exam_id.name)
        
        version_list = list(versions)
        num_versions = len(version_list)

        for idx, attempt in enumerate(self.attempt_ids):
            assigned_version = version_list[idx % num_versions]
            attempt.version_exam_id = assigned_version.id
            if attempt.state == 'assigned' and not attempt.start_datetime:
                attempt.answer_ids.unlink()
                attempt._initialize_candidate_questions()

        v_summary = ', '.join(v.version_code or v.name for v in versions)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Exam Versions Assigned'),
                'message': _('Multi-version papers (%s) successfully assigned across %d candidates in round-robin sequence.') % (
                    v_summary, len(self.attempt_ids)
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_send_invitations(self):
        """
        Sends exam invitations with secure unique login tokens (FR-EXM-017, FR-AMS-NOT-01).
        """
        for rec in self:
            for attempt in rec.attempt_ids.filtered(lambda a: a.state == "assigned"):
                attempt.action_send_invitation_email()
            rec.message_post(body=_("Exam invitations dispatched to %d candidate(s).") % len(rec.attempt_ids))


class ExamCandidateAttempt(models.Model):
    """
    Individual Candidate Exam Sitting (FR-EXM-018 - FR-EXM-028)
    ==========================================================
    Tracks an individual candidate's exam attempt, randomized question order,
    auto-save timestamps, anti-cheat proctoring events, scoring, and pass/fail status.
    """
    _name = "exam.candidate.attempt"
    _description = "Candidate Exam Sitting Attempt"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "session_id desc, candidate_name asc"

    name = fields.Char(string="Attempt Reference", readonly=True, default=lambda self: _("New"))
    session_id = fields.Many2one("exam.session", string="Exam Session", required=True, ondelete="cascade", index=True)
    exam_id = fields.Many2one(related="session_id.exam_id", string="Exam Definition", store=True, readonly=True)
    version_exam_id = fields.Many2one("exam.definition", string="Assigned Version Paper", domain="[('parent_exam_id', '=', exam_id)]", tracking=True)
    version_code = fields.Char(related="version_exam_id.version_code", string="Version", readonly=True)
    job_id = fields.Many2one(related="session_id.job_id", string="Job Position", store=True, readonly=True)
    
    # Candidate Identification
    candidate_type = fields.Selection([
        ("external", "External Applicant"),
        ("internal", "Internal Employee"),
        ("transfer", "Transfer Applicant"),
    ], string="Candidate Type", default="external", required=True)

    applicant_id = fields.Many2one("hr.applicant", string="Recruitment Applicant", tracking=True, index=True)
    employee_id = fields.Many2one("hr.employee", string="Internal Employee", tracking=True, index=True)
    user_id = fields.Many2one("res.users", string="Candidate User Account", compute="_compute_user_id", store=True, index=True)
    
    candidate_name = fields.Char(string="Candidate Name", compute="_compute_candidate_details", store=True)
    candidate_code = fields.Char(string="Candidate / Employee ID", compute="_compute_candidate_details", store=True, index=True)
    candidate_email = fields.Char(string="Candidate Email", compute="_compute_candidate_details", store=True)
    candidate_phone = fields.Char(string="Candidate Phone", compute="_compute_candidate_details", store=True)

    @api.depends("employee_id.user_id", "applicant_id", "candidate_email")
    def _compute_user_id(self):
        for rec in self:
            user = False
            if rec.employee_id and rec.employee_id.user_id:
                user = rec.employee_id.user_id
            elif rec.applicant_id and getattr(rec.applicant_id, "partner_id", False) and getattr(rec.applicant_id.partner_id, "user_ids", False):
                user = rec.applicant_id.partner_id.user_ids[:1]
            elif rec.candidate_email:
                user = self.env["res.users"].search([
                    "|", ("login", "=ilike", rec.candidate_email.strip()),
                    ("email", "=ilike", rec.candidate_email.strip())
                ], limit=1)
            rec.user_id = user

    # Secure Access Token (FR-EXM-018)
    access_token = fields.Char(string="Secure Access Token", readonly=True, copy=False, default=lambda self: secrets.token_urlsafe(32), index=True)
    token_expiry = fields.Datetime(string="Token Expiry", compute="_compute_token_expiry", store=True)
    exam_portal_url = fields.Char(string="Exam Sitting URL", compute="_compute_exam_portal_url")

    def _compute_exam_portal_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "http://localhost:8082")
        for rec in self:
            if rec.access_token:
                rec.exam_portal_url = f"{base_url}/exam/session/{rec.access_token}"
            else:
                rec.exam_portal_url = False

    def action_open_exam_portal(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/exam/session/{self.access_token}",
            "target": "new",
        }

    # Execution Timestamps
    invitation_sent_date = fields.Datetime(string="Invitation Sent At", readonly=True)
    login_datetime = fields.Datetime(string="First Login Time", readonly=True, tracking=True)
    start_datetime = fields.Datetime(string="Exam Started At", readonly=True, tracking=True)
    submit_datetime = fields.Datetime(string="Submitted At", readonly=True, tracking=True)
    duration_used_seconds = fields.Integer(string="Duration Used (Seconds)", readonly=True)

    # Anti-Cheating & Proctoring Stats (FR-EXM-021 - FR-EXM-023)
    tab_switch_count = fields.Integer(string="Tab Switches", default=0, readonly=True)
    copy_paste_attempt_count = fields.Integer(string="Copy/Paste Attempts", default=0, readonly=True)
    screenshot_attempt_count = fields.Integer(string="Screenshot Attempts", default=0, readonly=True)
    proctor_event_ids = fields.One2many("exam.proctor.event", "attempt_id", string="Proctoring Violation Events")

    # Questions & Answers
    answer_ids = fields.One2many("exam.candidate.answer", "attempt_id", string="Candidate Answers", copy=False)
    
    # Scoring Breakdown (FR-EXM-029, FR-EXM-033)
    total_marks_available = fields.Float(
        string="Max Marks",
        compute="_compute_total_score",
        store=True,
        readonly=True,
        help="Dynamic sum of maximum available marks for questions assigned to this candidate attempt."
    )
    objective_score = fields.Float(string="Auto-Scored Marks (MCQ/TF)", default=0.0, readonly=True, tracking=True)
    manual_score = fields.Float(string="Manually Graded Marks", default=0.0, readonly=True, tracking=True)
    total_score = fields.Float(string="Total Exam Score", compute="_compute_total_score", store=True, tracking=True)
    score_percentage = fields.Float(string="Score (%)", compute="_compute_total_score", store=True, tracking=True)
    
    is_passed = fields.Boolean(
        string="Passed (>=50%)",
        compute="_compute_pass_status",
        store=True,
        tracking=True,
        help="50% minimum passing score required."
    )

    disqualification_reason = fields.Text(string="Disqualification Reason", readonly=True, tracking=True)
    disqualification_log_id = fields.Many2one("exam.disqualification.log", string="Disqualification Record", readonly=True)

    state = fields.Selection([
        ("assigned", "Assigned / Pending Invitation"),
        ("invited", "Invited / Not Started"),
        ("in_progress", "Exam In Progress"),
        ("completed", "Completed / Submitted"),
        ("disqualified", "Disqualified (Anti-Cheating / Late)"),
    ], string="Attempt Status", default="assigned", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.candidate.attempt") or _("ATT/%06d") % self.search_count([])
        records = super().create(vals_list)
        for rec in records:
            rec._initialize_candidate_questions()
        return records

    @api.depends("applicant_id", "employee_id", "candidate_type")
    def _compute_candidate_details(self):
        for rec in self:
            if rec.candidate_type == "external" and rec.applicant_id:
                rec.candidate_name = rec.applicant_id.partner_name or rec.applicant_id.name
                rec.candidate_code = f"CAND-{rec.applicant_id.id:05d}"
                rec.candidate_email = rec.applicant_id.email_from
                rec.candidate_phone = rec.applicant_id.partner_phone or rec.applicant_id.partner_mobile
            elif rec.employee_id:
                rec.candidate_name = rec.employee_id.name
                rec.candidate_code = rec.employee_id.barcode or f"EMP-{rec.employee_id.id:05d}"
                rec.candidate_email = rec.employee_id.work_email or rec.employee_id.private_email
                rec.candidate_phone = rec.employee_id.mobile_phone or rec.employee_id.work_phone
            else:
                rec.candidate_name = "Candidate"
                rec.candidate_code = "N/A"
                rec.candidate_email = False
                rec.candidate_phone = False

    @api.depends("session_id.end_datetime")
    def _compute_token_expiry(self):
        for rec in self:
            if rec.session_id.end_datetime:
                # Token expires 1 hour after session end window
                rec.token_expiry = rec.session_id.end_datetime + timedelta(hours=1)
            else:
                rec.token_expiry = False

    @api.depends("objective_score", "manual_score", "answer_ids.marks_available", "exam_id.total_marks")
    def _compute_total_score(self):
        for rec in self:
            rec.total_score = round(rec.objective_score + rec.manual_score, 2)
            assigned_max = sum(ans.marks_available for ans in rec.answer_ids)
            if assigned_max > 0:
                rec.total_marks_available = round(assigned_max, 2)
            elif rec.exam_id and rec.exam_id.total_marks > 0:
                rec.total_marks_available = round(rec.exam_id.total_marks, 2)
            else:
                rec.total_marks_available = 0.0

            if rec.total_marks_available > 0:
                rec.score_percentage = round((rec.total_score / rec.total_marks_available) * 100.0, 2)
            else:
                rec.score_percentage = 0.0
            rec._sync_written_score_to_recruitment()

    def _sync_written_score_to_recruitment(self):
        """
        Synchronizes candidate's score_percentage from exam.candidate.attempt into:
        1. New Internal Recruitment Selected Candidates (new.internal.recruitment.selected.candidates) if Internal Candidate
        2. External Recruitment Selected Candidates (external.recruitment.selected.candidates) if External Candidate
        3. Central Candidate Score (recruitment.candidate.score) if present
        """
        for rec in self:
            pct = rec.score_percentage or 0.0

            # 1. Internal Employee Sync
            if rec.employee_id:
                int_cand_lines = self.env['new.internal.recruitment.selected.candidates'].sudo().search([
                    ('emp_name', '=', rec.employee_id.id)
                ])
                if int_cand_lines:
                    int_cand_lines.write({'written_exam_score': pct})

                scores = self.env['recruitment.candidate.score'].sudo().search([
                    ('employee_id', '=', rec.employee_id.id)
                ])
                if scores:
                    scores.write({'written_score': pct})

            # 2. External Applicant Sync
            if rec.applicant_id:
                ext_cand_lines = self.env['external.recruitment.selected.candidates'].sudo().search([
                    ('applicant_name', '=', rec.applicant_id.id)
                ])
                if ext_cand_lines:
                    ext_cand_lines.write({'written_exam_score': pct})

                scores = self.env['recruitment.candidate.score'].sudo().search([
                    ('applicant_id', '=', rec.applicant_id.id)
                ])
                if scores:
                    scores.write({'written_score': pct})

    @api.depends("score_percentage", "exam_id.passing_score_percentage", "state")
    def _compute_pass_status(self):
        for rec in self:
            passing_pct = rec.exam_id.passing_score_percentage or 50.0
            rec.is_passed = (rec.state == "completed" and rec.score_percentage >= passing_pct)

    def _initialize_candidate_questions(self):
        """
        Generates individual randomized questions & answer rows seeded for this attempt.
        Uses the assigned Exam Version Paper (Version A, B, C, D) if assigned, or master Exam.
        """
        self.ensure_one()
        target_exam = self.version_exam_id or self.exam_id
        if self.answer_ids or not target_exam:
            return
        
        # Seed randomizer with attempt ID to ensure deterministic reproducibility on audit
        seed_value = f"{self.id}_{self.access_token[:8]}"
        questions = target_exam.generate_question_pool_for_candidate(seed=seed_value)
        
        answer_vals = []
        for idx, q in enumerate(questions, start=1):
            answer_vals.append({
                "attempt_id": self.id,
                "question_id": q.id,
                "sequence": idx,
                "marks_available": q.marks,
            })
            
        self.env["exam.candidate.answer"].create(answer_vals)

    def action_start_exam(self):
        """Called when candidate opens the exam page and clicks Start"""
        self.ensure_one()
        now = fields.Datetime.now()
        
        # Late arrival check (BR-AMS-10, FR-EXM-020)
        lockout_mins = self.exam_id.late_arrival_lockout_minutes or 15
        cutoff = self.session_id.start_datetime + timedelta(minutes=lockout_mins)
        if now > cutoff:
            self._disqualify_candidate(
                reason=_("Late arrival: Attempted to start at %(now)s, exceeding %(mins)d min cutoff (%(cutoff)s).",
                         now=now, mins=lockout_mins, cutoff=cutoff),
                violation_type="late_arrival"
            )
            raise UserError(_("You cannot start this exam because the arrival window has closed (Late Arrival)."))
            
        if self.state in ["assigned", "invited"]:
            self.write({
                "state": "in_progress",
                "start_datetime": now,
                "login_datetime": self.login_datetime or now,
            })

    def action_submit_exam(self):
        """Called upon candidate final submission or timer auto-submit"""
        self.ensure_one()
        now = fields.Datetime.now()
        duration_sec = int((now - self.start_datetime).total_seconds()) if self.start_datetime else 0
        
        # 1. Run automated grading ONLY for objective questions (MCQ, True/False, Fill-in-Blank)
        self._auto_grade_objective_answers()
        
        # 2. Spawn manual grading tasks for Essay / Short Answer to be evaluated by Workunit
        self._spawn_manual_grading_tasks()
        
        self.write({
            "state": "completed",
            "submit_datetime": now,
            "duration_used_seconds": duration_sec,
        })

    def action_recalculate_scores(self):
        """Recalculates objective and manual scores for attempt"""
        for rec in self:
            rec._auto_grade_objective_answers()

    def action_submit_essay_evaluation(self):
        """
        Grades all essay/subjective questions per candidate at once, calculates total manual score,
        and computes the final exam score and pass/fail status (FR-EXM-033, FR-EXM-036).
        """
        for rec in self:
            manual_answers = rec.answer_ids.filtered(
                lambda a: a.question_id.question_type in ["short_answer", "essay", "fill_blank"]
            )
            for ans in manual_answers:
                if ans.marks_awarded < 0 or ans.marks_awarded > ans.marks_available:
                    raise ValidationError(
                        _("Marks awarded for question '%(q)s' must be between 0 and %(max)s.",
                          q=(ans.question_text or "Question")[:50], max=ans.marks_available)
                    )
                # Auto-evaluate non-empty candidate responses if marks_awarded is still 0
                if ans.marks_awarded == 0.0 and ans.text_answer and ans.text_answer.strip():
                    q = ans.question_id
                    expected_txt = (q.correct_text_answer or q.rubric_guidelines or q.explanation or "").strip().lower()
                    cand_txt = ans.text_answer.strip().lower()
                    if expected_txt:
                        key_terms = [t.strip() for t in expected_txt.replace('\n', ' ').replace(',', ' ').split() if len(t.strip()) > 3]
                        matched = [t for t in key_terms if t in cand_txt]
                        if key_terms and matched:
                            fraction = min(1.0, len(matched) / max(1, len(key_terms) // 2))
                            ans.marks_awarded = round(ans.marks_available * fraction, 2)
                        else:
                            ans.marks_awarded = ans.marks_available
                    else:
                        # Candidate answered non-empty text: award full marks on evaluation
                        ans.marks_awarded = ans.marks_available

                ans.is_correct = (ans.marks_awarded > 0)
                # Sync with grading task if present
                task = self.env["exam.grading.task"].search([("answer_id", "=", ans.id)], limit=1)
                if task:
                    task.write({
                        "marks_awarded": ans.marks_awarded,
                        "state": "verified",
                        "graded_by_user_id": self.env.user.id,
                        "graded_date": fields.Datetime.now(),
                        "verified_by_user_id": self.env.user.id,
                        "verified_date": fields.Datetime.now(),
                    })

            # Compute manual score and total final score
            rec.manual_score = round(sum(ans.marks_awarded for ans in manual_answers), 2)
            rec._auto_grade_objective_answers()
            rec.total_score = round(rec.objective_score + rec.manual_score, 2)
            if rec.total_marks_available > 0:
                rec.score_percentage = round((rec.total_score / rec.total_marks_available) * 100.0, 2)
            else:
                rec.score_percentage = 0.0
            passing_pct = rec.exam_id.passing_score_percentage or 50.0
            rec.is_passed = (rec.score_percentage >= passing_pct)
            rec._sync_written_score_to_recruitment()
            
            rec.message_post(
                body=_(
                    "Essay Evaluation Submitted: Manual Essay Score: %(manual)s, Total Written Exam Score: %(total)s / %(max)s (%(pct)s%%) - Status: %(status)s",
                    manual=rec.manual_score, total=rec.total_score, max=rec.total_marks_available,
                    pct=rec.score_percentage, status="PASSED" if rec.is_passed else "FAILED"
                )
            )

    def _auto_grade_objective_answers(self):
        """Calculates score automatically for objective questions (MCQ Single, MCQ Multi, True/False, and Fill-in-Blank)"""
        self.ensure_one()
        obj_score = 0.0
        for ans in self.answer_ids:
            q = ans.question_id
            q_type = q.question_type

            if q_type == "mcq_single":
                # Check selected option record
                if ans.selected_option_id and ans.selected_option_id.is_correct:
                    ans.marks_awarded = ans.marks_available
                    ans.is_correct = True
                elif ans.text_answer and q.option_ids:
                    # Fallback check if text_answer matches correct option text or ID
                    correct_opts = q.option_ids.filtered(lambda o: o.is_correct)
                    candidate_ans = ans.text_answer.strip().lower()
                    if any(o.option_text.strip().lower() == candidate_ans or str(o.id) == candidate_ans for o in correct_opts):
                        ans.marks_awarded = ans.marks_available
                        ans.is_correct = True
                    else:
                        ans.marks_awarded = 0.0
                        ans.is_correct = False
                else:
                    ans.marks_awarded = 0.0
                    ans.is_correct = False
                obj_score += ans.marks_awarded

            elif q_type == "true_false":
                is_correct = False
                candidate_str = (ans.text_answer or "").strip().lower()

                if ans.selected_option_id:
                    is_correct = ans.selected_option_id.is_correct
                elif candidate_str:
                    if q.option_ids:
                        correct_opt = q.option_ids.filtered(lambda o: o.is_correct)
                        if correct_opt and correct_opt[0].option_text.strip().lower() == candidate_str:
                            is_correct = True
                    elif q.correct_text_answer:
                        if q.correct_text_answer.strip().lower() == candidate_str:
                            is_correct = True
                    elif candidate_str in ["true", "t"]:
                        is_correct = True # Standard default true

                if is_correct:
                    ans.marks_awarded = ans.marks_available
                    ans.is_correct = True
                else:
                    ans.marks_awarded = 0.0
                    ans.is_correct = False
                obj_score += ans.marks_awarded

            elif q_type == "mcq_multiple":
                correct_ids = set(q.option_ids.filtered(lambda o: o.is_correct).ids)
                selected_ids = set(ans.selected_option_ids.ids)
                if correct_ids and correct_ids == selected_ids:
                    ans.marks_awarded = ans.marks_available
                    ans.is_correct = True
                else:
                    # Partial scoring if overlap and no wrong choices
                    overlap = correct_ids.intersection(selected_ids)
                    wrong = selected_ids.difference(correct_ids)
                    if overlap and not wrong and len(correct_ids) > 0:
                        fraction = len(overlap) / len(correct_ids)
                        ans.marks_awarded = round(ans.marks_available * fraction, 2)
                    else:
                        ans.marks_awarded = 0.0
                    ans.is_correct = (ans.marks_awarded == ans.marks_available)
                obj_score += ans.marks_awarded

            elif q_type == "fill_blank":
                candidate_txt = (ans.text_answer or "").strip().lower()
                expected_txt = (q.correct_text_answer or "").strip().lower()
                
                # If expected_txt is empty, extract from bracket slot in stem if present
                if not expected_txt and "[" in (q.name or "") and "]" in (q.name or ""):
                    expected_txt = q.name.split("[")[1].split("]")[0].strip().lower()

                if candidate_txt and expected_txt and (candidate_txt == expected_txt or expected_txt in candidate_txt):
                    ans.marks_awarded = ans.marks_available
                    ans.is_correct = True
                else:
                    ans.marks_awarded = 0.0
                    ans.is_correct = False
                obj_score += ans.marks_awarded
                
        self.objective_score = round(obj_score, 2)
        assigned_max = sum(ans.marks_available for ans in self.answer_ids)
        if assigned_max > 0:
            self.total_marks_available = round(assigned_max, 2)
        elif self.exam_id and self.exam_id.total_marks > 0:
            self.total_marks_available = round(self.exam_id.total_marks, 2)
        else:
            self.total_marks_available = 0.0

        self.total_score = round(self.objective_score + self.manual_score, 2)
        if self.total_marks_available > 0:
            self.score_percentage = round((self.total_score / self.total_marks_available) * 100.0, 2)
        else:
            self.score_percentage = 0.0
        passing_pct = self.exam_id.passing_score_percentage or 50.0
        self.is_passed = (self.score_percentage >= passing_pct)

    def _spawn_manual_grading_tasks(self):
        """Creates manual grading tasks for Essay and Fill-in-the-Blank questions"""
        self.ensure_one()
        manual_answers = self.answer_ids.filtered(
            lambda a: a.question_id.question_type in ["short_answer", "essay", "fill_blank"]
        )
        if not manual_answers:
            return

        # Find target grader: candidate's work unit manager first, then job's department manager
        grader = False
        emp = self.employee_id
        if not emp and self.applicant_id:
            emp = getattr(self.applicant_id, 'emp_id', False) or getattr(self.applicant_id, 'employee_id', False)

        if emp and emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
            grader = emp.department_id.manager_id.user_id

        if not grader and self.job_id and self.job_id.department_id and self.job_id.department_id.manager_id:
            grader = self.job_id.department_id.manager_id.user_id
        if not grader:
            grader = self.env.user

        for ans in manual_answers:
            # Check if task already exists
            existing = self.env["exam.grading.task"].search([("answer_id", "=", ans.id)], limit=1)
            if not existing:
                self.env["exam.grading.task"].create({
                    "attempt_id": self.id,
                    "answer_id": ans.id,
                    "question_id": ans.question_id.id,
                    "candidate_name": self.candidate_name,
                    "assigned_grader_id": grader.id if grader else False,
                    "job_id": self.job_id.id,
                    "marks_available": ans.marks_available,
                })

    def record_proctor_event(self, event_type, details=""):
        """Called by Javascript proctoring agent during exam"""
        self.ensure_one()
        self.env["exam.proctor.event"].create({
            "attempt_id": self.id,
            "event_type": event_type,
            "details": details,
            "timestamp": fields.Datetime.now(),
        })
        
        if event_type == "tab_switch":
            self.tab_switch_count += 1
            max_allowed = self.exam_id.tab_switch_violation_limit or 3
            if self.tab_switch_count >= max_allowed:
                self._disqualify_candidate(
                    reason=_("Exceeded maximum allowed tab switches (%(count)d / %(max)d violations).",
                             count=self.tab_switch_count, max=max_allowed),
                    violation_type="tab_switch"
                )
                return {"action": "disqualified", "message": "Exceeded tab switch limit"}
        elif event_type == "copy_paste":
            self.copy_paste_attempt_count += 1
        elif event_type == "screenshot":
            self.screenshot_attempt_count += 1
            
        return {"action": "logged", "count": self.tab_switch_count}

    def _disqualify_candidate(self, reason, violation_type="anti_cheat"):
        """Automated disqualification engine (FR-EXM-037 - FR-EXM-040)"""
        self.ensure_one()
        disq_log = self.env["exam.disqualification.log"].create({
            "attempt_id": self.id,
            "session_id": self.session_id.id,
            "applicant_id": self.applicant_id.id if self.applicant_id else False,
            "employee_id": self.employee_id.id if self.employee_id else False,
            "candidate_name": self.candidate_name,
            "candidate_code": self.candidate_code,
            "violation_type": violation_type,
            "reason": reason,
            "timestamp": fields.Datetime.now(),
        })
        
        self.write({
            "state": "disqualified",
            "disqualification_reason": reason,
            "disqualification_log_id": disq_log.id,
            "objective_score": 0.0,
            "manual_score": 0.0,
        })
        self.message_post(body=_("Candidate automatically DISQUALIFIED. Reason: %s") % reason)

    def action_send_invitation_email(self):
        """Sends exam invitation with unique token link via Email, In-App Notification, and Activity (FR-EXM-017, FR-AMS-NOT-01)"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8082')
        exam_url = f"{base_url}/exam/session/{self.access_token}"
        
        subject = _("Invitation: Written Assessment for %(job)s - %(bank)s",
                    job=self.job_id.name or "Position", bank="Bunna Bank")
        body = _("""
            <p>Dear %(name)s,</p>
            <p>You have been invited to sit for the written assessment for the position <b>%(job)s</b>.</p>
            <p><b>Exam Details:</b></p>
            <ul>
                <li><b>Date &amp; Time:</b> %(start)s</li>
                <li><b>Duration:</b> %(duration)d Minutes</li>
                <li><b>Late Arrival Cutoff:</b> %(late)d Minutes from start</li>
            </ul>
            <p><b>Access Link:</b> <a href="%(url)s" target="_blank" style="color:#1a73e8;text-decoration:underline;font-weight:bold;">%(url)s</a></p>
            <p><i>Note: Please ensure a stable internet connection. Copy/Paste, screen captures, and switching tabs are strictly monitored and will result in automated disqualification.</i></p>
            <p>Best regards,<br/>Bunna Bank HR Assessment Team</p>
        """, name=self.candidate_name, job=self.job_id.name, start=self.session_id.start_datetime,
             duration=self.session_id.duration_minutes, late=self.exam_id.late_arrival_lockout_minutes, url=exam_url)
        
        # 1. Dispatch Outbound Email
        if self.candidate_email:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body,
                'email_to': self.candidate_email,
            }).send()

        # 2. Determine target partner/user for In-App Notification
        target_partner = False
        target_user = False
        if self.employee_id:
            target_user = self.employee_id.user_id
            target_partner = self.employee_id.user_id.partner_id or self.employee_id.work_contact_id
        elif self.applicant_id and self.applicant_id.partner_id:
            target_partner = self.applicant_id.partner_id

        # 3. Dispatch In-App Notification (Odoo Inbox & Bell Counter)
        if target_partner:
            self.env['mail.message'].sudo().create({
                'subject': subject,
                'body': body,
                'model': 'exam.candidate.attempt',
                'res_id': self.id,
                'message_type': 'notification',
                'partner_ids': [(4, target_partner.id)],
                'notification_ids': [(0, 0, {
                    'res_partner_id': target_partner.id,
                    'notification_type': 'inbox',
                    'is_read': False,
                })],
            })

            # 4. Dispatch Direct Message in Discuss App
            try:
                start_dt = str(self.session_id.start_datetime or fields.Datetime.now())
                duration_min = self.session_id.duration_minutes or 60
                job_title = self.job_id.name or self.exam_id.name or "Position"
                cand_name = self.candidate_name or target_partner.name

                discuss_msg = Markup(
                    f"<p>Dear <b>{cand_name}</b>,<br/>"
                    f"You have been shortlisted for the Written Exam for position <b>{job_title}</b>.<br/>"
                    f"Date: {start_dt}<br/>"
                    f"Duration: {duration_min} Minutes<br/>"
                    f"Location: Online<br/>"
                    f"Here is Exam Link: <a href='{exam_url}' target='_blank' style='color:#1a73e8;text-decoration:underline;font-weight:bold;'>{exam_url}</a><br/><br/>"
                    f"All The Best!</p>"
                )
                chat_channel = self.env['discuss.channel'].sudo()._get_or_create_chat(partners_to=[target_partner.id])
                if chat_channel:
                    chat_channel.message_post(
                        body=discuss_msg,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )
            except Exception:
                pass
            
            # Send live toast notification if bus is active
            try:
                self.env['bus.bus'].sudo()._sendone(target_partner, 'mail.simple_notification', {
                    'title': _("Written Exam Invitation"),
                    'message': _("You have been invited to sit for the %s written examination.") % (self.job_id.name or "Assessment"),
                    'type': 'info',
                })
            except Exception:
                pass

        # 5. Schedule Odoo Systray Activity (To-Do Clock)
        if target_user:
            activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            if activity_type:
                self.env['mail.activity'].sudo().create({
                    'res_model_id': self.env['ir.model'].sudo()._get('exam.candidate.attempt').id,
                    'res_id': self.id,
                    'activity_type_id': activity_type.id,
                    'summary': _("Sit for Written Exam: %s") % (self.job_id.name or self.exam_id.name),
                    'note': body,
                    'user_id': target_user.id,
                    'date_deadline': fields.Date.today(),
                })

        # 6. Log in Attempt Chatter
        self.message_post(
            body=_("Invitation dispatched via Email, Discuss Direct Message, and In-App Notification to %s.") % (self.candidate_name or "Candidate"),
            subject=subject
        )

        self.write({"invitation_sent_date": fields.Datetime.now(), "state": "invited"})


class ExamCandidateAnswer(models.Model):
    """
    Individual Candidate Answer Record per Question
    """
    _name = "exam.candidate.answer"
    _description = "Candidate Answer Response"
    _order = "sequence asc, id asc"

    attempt_id = fields.Many2one("exam.candidate.attempt", string="Attempt", required=True, ondelete="cascade", index=True)
    question_id = fields.Many2one("exam.question", string="Question", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Question No.", default=1)
    
    question_type = fields.Selection(related="question_id.question_type", string="Question Type", readonly=True)
    question_text = fields.Text(related="question_id.name", string="Question Prompt", readonly=True)
    marks_available = fields.Float(string="Marks Available", default=1.0)
    marks_awarded = fields.Float(string="Marks Awarded", default=0.0)
    is_correct = fields.Boolean(string="Correct", default=False)
    
    # Candidate Inputs
    selected_option_id = fields.Many2one("exam.question.option", string="Selected Option (Single)")
    selected_option_ids = fields.Many2many("exam.question.option", string="Selected Options (Multi)")
    text_answer = fields.Text(string="Candidate Text Response")
    is_marked_for_review = fields.Boolean(string="Marked for Review", default=False)
    last_saved_datetime = fields.Datetime(string="Last Auto-Save Time")

    @api.constrains("marks_awarded", "marks_available")
    def _check_marks_awarded(self):
        for rec in self:
            if rec.marks_awarded < 0:
                raise ValidationError(_("Marks awarded cannot be negative."))
            if rec.marks_available > 0 and rec.marks_awarded > rec.marks_available:
                raise ValidationError(
                    _("Marks awarded (%.2f) cannot exceed the marks available (%.2f) for question '%s'.") % (
                        rec.marks_awarded,
                        rec.marks_available,
                        rec.question_text or rec.id
                    )
                )


class ExamProctorEvent(models.Model):
    """
    """
    _name = "exam.proctor.event"
    _description = "Anti-Cheating Proctoring Violation Event"
    _order = "timestamp desc, id desc"

    attempt_id = fields.Many2one("exam.candidate.attempt", string="Candidate Attempt", required=True, ondelete="cascade", index=True)
    timestamp = fields.Datetime(string="Timestamp", required=True, default=fields.Datetime.now)
    
    event_type = fields.Selection([
        ("tab_switch", "Tab Switch / Window Blur"),
        ("copy_paste", "Copy / Paste Attempt"),
        ("screenshot", "Screenshot / Print Screen Attempt"),
        ("late_arrival", "Late Arrival Attempt"),
        ("right_click", "Context Menu / Right Click Blocked"),
    ], string="Violation Type", required=True)

    details = fields.Char(string="Details / Event Log")
