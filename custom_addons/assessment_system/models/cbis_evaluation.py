# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class CBISInterviewerEvaluation(models.Model):
    """
    ==================================================================
    Dedicated evaluation form for assigned interviewers featuring STAR/STARR/Likert
    scoring, conflict of interest declaration, draft saves, and event-driven auto-lock.
    """
    _name = "cbis.interviewer.evaluation"
    _description = "Interviewer Evaluation Sheet"
    _inherit = ["mail.thread"]
    _order = "candidate_interview_id asc, id asc"

    candidate_interview_id = fields.Many2one(
        "cbis.interview.candidate",
        string="Candidate Interview Record",
        required=True,
        ondelete="cascade",
        index=True
    )
    session_id = fields.Many2one(related="candidate_interview_id.session_id", string="Session", readonly=True, store=True)
    vacancy_id = fields.Many2one(related="candidate_interview_id.vacancy_id", string="Vacancy", readonly=True, store=True)
    job_id = fields.Many2one(related="candidate_interview_id.job_id", string="Job Position", readonly=True, store=True)

    candidate_name = fields.Char(related="candidate_interview_id.candidate_name", string="Candidate Name", readonly=True)
    candidate_code = fields.Char(related="candidate_interview_id.candidate_code", string="Candidate ID", readonly=True)

    interviewer_user_id = fields.Many2one("res.users", string="Interviewer", required=True, index=True)
    
    # Conflict of Interest Declaration (BR-AMS-17)
    conflict_of_interest_declared = fields.Boolean(
        string="Conflict of Interest Declared",
        default=False,
        help="Panel members must declare any conflict of interest prior to scoring."
    )
    conflict_notes = fields.Text(string="Conflict of Interest Details")

    # Evaluation Lines
    line_ids = fields.One2many("cbis.interviewer.evaluation.line", "evaluation_id", string="Competency Ratings", copy=True)
    
    total_score = fields.Float(string="Total Evaluation Score (%)", compute="_compute_total_score", store=True, tracking=True)
    general_comments = fields.Text(string="Overall Interviewer Comments & Recommendation", tracking=True)
    candidate_status = fields.Selection([

        ("present", "Present"),
        ("absent", "Absent"),
    ], string="Candidate Status", default="present", required=True, tracking=True)
    is_absent = fields.Boolean(string="Marked Absent", default=False)


    submission_datetime = fields.Datetime(string="Submission Date & Time", readonly=True, tracking=True)
    is_locked = fields.Boolean(string="Evaluation Locked (Immutable)", default=False, readonly=True, tracking=True)

    # Method Flags for Dynamic UI Table Column Visibility
    has_star_method = fields.Boolean(string="Has STAR Method", compute="_compute_method_flags")
    has_starr_method = fields.Boolean(string="Has STARR Method", compute="_compute_method_flags")
    has_likert_method = fields.Boolean(string="Has Likert Method", compute="_compute_method_flags")
    has_star_or_starr_method = fields.Boolean(string="Has STAR/STARR Method", compute="_compute_method_flags")

    is_current_interviewer = fields.Boolean(
        string="Is Current Interviewer",
        compute="_compute_is_current_interviewer",
        help="True if current logged-in user is the assigned interviewer or system administrator."
    )

    can_submit_evaluation = fields.Boolean(
        string="Can Submit Evaluation",
        compute="_compute_can_submit_evaluation",
        help="If single candidate, always visible. If multiple candidates, visible ONLY on the last candidate."
    )

    def _compute_is_current_interviewer(self):
        current_uid = self.env.user.id
        is_admin = self.env.is_admin()
        for rec in self:
            rec.is_current_interviewer = bool((rec.interviewer_user_id.id == current_uid) or is_admin)

    @api.depends("session_id", "vacancy_id", "interviewer_user_id", "candidate_interview_id")
    def _compute_can_submit_evaluation(self):
        for rec in self:
            if not rec.interviewer_user_id:
                rec.can_submit_evaluation = True
                continue

            domain = [("interviewer_user_id", "=", rec.interviewer_user_id.id)]
            if rec.session_id:
                domain.append(("session_id", "=", rec.session_id.id))
            elif rec.vacancy_id:
                domain.append(("vacancy_id", "=", rec.vacancy_id.id))
            else:
                rec.can_submit_evaluation = True
                continue

            sibling_evals = self.search(domain, order="candidate_interview_id asc, id asc")
            if len(sibling_evals) <= 1:
                # Single candidate in session: visible
                rec.can_submit_evaluation = True
            else:
                # Multiple candidates: only visible on the last candidate
                last_eval = sibling_evals[-1]
                rec.can_submit_evaluation = bool(rec.id == last_eval.id)

    state = fields.Selection([
        ("draft", "Draft / In Progress"),
        ("submitted", "Submitted / Locked"),
    ], string="Evaluation Status", default="draft", tracking=True, required=True)

    @api.onchange("candidate_status")
    def _onchange_candidate_status(self):
        for rec in self:
            rec.is_absent = (rec.candidate_status == "absent")
            for line in rec.line_ids:
                line._compute_component_marks()

    @api.depends("line_ids.evaluation_method")
    def _compute_method_flags(self):
        for rec in self:
            methods = set(rec.line_ids.mapped("evaluation_method"))
            rec.has_star_method = ("star" in methods)
            rec.has_starr_method = ("starr" in methods)
            rec.has_likert_method = ("likert" in methods)
            rec.has_star_or_starr_method = bool(methods & {"star", "starr"})

    @api.depends("line_ids.weighted_score", "line_ids.weight_percentage", "is_absent", "candidate_status")
    def _compute_total_score(self):
        for rec in self:
            if rec.candidate_status == "absent" or rec.is_absent:
                rec.total_score = 0.0
            else:
                tot_weight = sum(line.weight_percentage for line in rec.line_ids)
                tot_weighted_marks = sum(line.weighted_score for line in rec.line_ids)
                if tot_weight > 0:
                    rec.total_score = round((tot_weighted_marks / tot_weight) * 100.0, 2)
                else:
                    rec.total_score = 0.0


    def _initialize_competency_lines(self):
        """Populates evaluation sheet with competencies linked to the interview session, job position profile, or default competency list."""
        self.ensure_one()
        if self.line_ids:
            return

        session = self.session_id
        line_vals = []
        if session and session.competency_line_ids:
            for idx, s_line in enumerate(session.competency_line_ids, start=1):
                comp = s_line.competency_id
                line_vals.append({
                    "evaluation_id": self.id,
                    "competency_id": comp.id,
                    "evaluation_method": s_line.evaluation_method,
                    "weight_percentage": s_line.weight_percentage,
                    "suggested_question": s_line.suggested_question or (comp.question_ids[0].name if hasattr(comp, 'question_ids') and comp.question_ids else ""),
                    "sequence": s_line.sequence or idx * 10,
                })
        else:
            job = self.job_id
            mapping_lines = self.env["assessment.competency.job.rel"].search([("job_id", "=", job.id)]) if job else False
            if mapping_lines:
                for map_rel in mapping_lines:
                    comp = map_rel.competency_id
                    suggested_q = comp.question_ids[0].name if hasattr(comp, 'question_ids') and comp.question_ids else ""
                    eval_method = getattr(comp, 'evaluation_method', False) or map_rel.evaluation_method or "star"
                    line_vals.append({
                        "evaluation_id": self.id,
                        "competency_id": comp.id,
                        "evaluation_method": eval_method,
                        "weight_percentage": map_rel.weight_percentage,
                        "suggested_question": suggested_q,
                        "sequence": map_rel.sequence,
                    })
            else:
                default_comps = self.env["competency.competency"].search([("status", "=", "active")], limit=4)
                if not default_comps:
                    default_comps = self.env["competency.competency"].search([], limit=4)
                weight_each = round(100.0 / len(default_comps), 2) if default_comps else 25.0
                for idx, comp in enumerate(default_comps, start=1):
                    suggested_q = comp.question_ids[0].name if hasattr(comp, 'question_ids') and comp.question_ids else ""
                    eval_method = getattr(comp, 'evaluation_method', False) or "star"
                    line_vals.append({
                        "evaluation_id": self.id,
                        "competency_id": comp.id,
                        "evaluation_method": eval_method,
                        "weight_percentage": weight_each,
                        "suggested_question": suggested_q,
                        "sequence": idx * 10,
                    })

        self.env["cbis.interviewer.evaluation.line"].create(line_vals)

    def action_save_draft(self):
        """Allows saving partial evaluation in progress (FR-CBIS-018)"""
        current_user = self.env.user
        is_admin = self.env.is_admin()
        for rec in self:
            if rec.interviewer_user_id != current_user and not is_admin:
                raise UserError(_("You can only edit and save draft evaluations assigned to yourself."))
            rec.sudo().write({"state": "draft"})

    def action_submit_evaluation(self):
        """
        Submits final evaluation for the CURRENT candidate evaluation only.
        Each candidate is evaluated and submitted individually (FR-CBIS-019).
        Strictly enforces that interviewers can only submit their own assigned evaluation.
        The candidate interview record is auto-locked only when ALL interviewers
        have submitted their evaluation for that specific candidate (FR-CBIS-021).
        """
        # When evaluating multiple candidates, submitting on the last candidate submits all draft evaluations for this interviewer
        if len(self) == 1:
            domain = [
                ('interviewer_user_id', '=', self.interviewer_user_id.id),
                ('state', '=', 'draft'),
            ]
            if self.session_id:
                domain.append(('session_id', '=', self.session_id.id))
            elif self.vacancy_id:
                domain.append(('vacancy_id', '=', self.vacancy_id.id))
            sibling_drafts = self.search(domain)
            if len(sibling_drafts) > 1:
                return self.action_submit_all_evaluations()
        current_user = self.env.user
        is_admin = self.env.is_admin()

        for rec in self:
            if rec.interviewer_user_id != current_user and not is_admin:
                raise UserError(_("You are only authorized to evaluate and submit evaluations assigned to yourself."))

            if rec.state == "submitted":
                continue

            # Validate ratings for this candidate only
            if not rec.is_absent:
                for line in rec.line_ids:
                    if line.evaluation_method == "star":
                        if any(s not in ["1", "2", "3", "4", "5"] for s in [line.star_situation, line.star_task, line.star_action, line.star_result]):
                            raise ValidationError(_(
                                "Candidate '%s': Please select a rating (1 to 5) for all STAR components in competency '%s'.",
                                rec.candidate_name,
                                line.competency_id.name
                            ))
                    elif line.evaluation_method == "starr":
                        if any(s not in ["1", "2", "3", "4", "5"] for s in [line.star_situation, line.star_task, line.star_action, line.star_result, line.starr_reflection]):
                            raise ValidationError(_(
                                "Candidate '%s': Please select a rating (1 to 5) for all STARR components in competency '%s'.",
                                rec.candidate_name,
                                line.competency_id.name
                            ))
                    elif line.evaluation_method == "likert":
                        if line.likert_score not in ["1", "2", "3", "4", "5"]:
                            raise ValidationError(_(
                                "Candidate '%s': Please select a valid Likert rating (1 to 5) for competency '%s'.",
                                rec.candidate_name,
                                line.competency_id.name
                            ))

            # Submit only this candidate evaluation
            rec._compute_total_score()
            rec.sudo().write({
                "state": "submitted",
                "is_locked": True,
                "submission_datetime": fields.Datetime.now(),
            })

            # Recompute scores for the candidate interview record with elevated permissions (sudo)
            candidate_record = rec.candidate_interview_id.sudo()
            if candidate_record:
                candidate_record._compute_final_interview_score()
                candidate_record._compute_evaluation_progress()

                # Auto-lock the candidate record ONLY when ALL assigned interviewers have submitted
                all_evals = candidate_record.evaluation_ids
                unsubmitted = all_evals.filtered(lambda e: e.state != "submitted")
                if all_evals and not unsubmitted:
                    candidate_record.write({"state": "locked"})
                    candidate_record.message_post(
                        body=_("All %d panel evaluations submitted. Candidate evaluation set is now AUTO-LOCKED and immutable (FR-CBIS-021).") % len(all_evals)
                    )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Evaluation Submitted'),
                'message': _("Evaluation for '%s' has been submitted and locked successfully. You may now proceed to the next candidate.") % (self.candidate_name or ''),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_submit_all_evaluations(self):
        """
        Submits ALL draft candidate evaluations for THIS interviewer in the same session/vacancy at once.
        - Strictly isolated to the current interviewer's own assigned evaluations.
        - Panel members cannot submit evaluations belonging to other panel members.
        - Absent candidates: auto-submitted without score validation.
        - Already-submitted records: silently skipped.
        - Each candidate interview record is auto-locked only when ALL interviewers have submitted (FR-CBIS-021).
        """
        current_user = self.env.user
        is_admin = self.env.is_admin()

        # Strict security validation: Panel members cannot submit other panelists' sheets
        for rec in self:
            if rec.interviewer_user_id != current_user and not is_admin:
                raise UserError(_("You can only submit and lock your own assigned candidate evaluations."))

        # Target interviewer is strictly the logged-in user (or explicitly selected single interviewer for admin)
        target_interviewer_id = current_user.id if not is_admin else (self[0].interviewer_user_id.id if self else current_user.id)

        # Collect distinct sessions and vacancies in scope
        session_ids = self.mapped('session_id').ids
        vacancy_ids = self.mapped('vacancy_id').ids

        domain = [
            ('interviewer_user_id', '=', target_interviewer_id),
            ('state', '=', 'draft'),
        ]
        if session_ids:
            domain.append(('session_id', 'in', session_ids))
        elif vacancy_ids:
            domain.append(('vacancy_id', 'in', vacancy_ids))

        evals_to_submit = self.search(domain)
        if not evals_to_submit:
            evals_to_submit = self.filtered(lambda r: r.interviewer_user_id.id == target_interviewer_id and r.state == 'draft')

        submitted_count = 0
        skipped_absent = 0
        errors = []

        for eval_rec in evals_to_submit:
            if eval_rec.state == "submitted":
                continue

            # Absent candidates — no rating validation, submit directly
            if eval_rec.candidate_status == "absent" or eval_rec.is_absent:
                eval_rec._compute_total_score()
                eval_rec.write({
                    "state": "submitted",
                    "is_locked": True,
                    "submission_datetime": fields.Datetime.now(),
                })
                skipped_absent += 1
                submitted_count += 1
            else:
                # Validate ratings for present candidates
                candidate_errors = []
                for line in eval_rec.line_ids:
                    if line.evaluation_method == "star":
                        if any(s not in ["1", "2", "3", "4", "5"] for s in [line.star_situation, line.star_task, line.star_action, line.star_result]):
                            candidate_errors.append(
                                _("• '%s' — competency '%s': incomplete STAR rating.") % (eval_rec.candidate_name, line.competency_id.name)
                            )
                    elif line.evaluation_method == "starr":
                        if any(s not in ["1", "2", "3", "4", "5"] for s in [line.star_situation, line.star_task, line.star_action, line.star_result, line.starr_reflection]):
                            candidate_errors.append(
                                _("• '%s' — competency '%s': incomplete STARR rating.") % (eval_rec.candidate_name, line.competency_id.name)
                            )
                    elif line.evaluation_method == "likert":
                        if line.likert_score not in ["1", "2", "3", "4", "5"]:
                            candidate_errors.append(
                                _("• '%s' — competency '%s': incomplete Likert rating.") % (eval_rec.candidate_name, line.competency_id.name)
                            )

                if candidate_errors:
                    errors.extend(candidate_errors)
                    continue  # Skip incomplete candidate, continue with others

                eval_rec._compute_total_score()
                eval_rec.sudo().write({
                    "state": "submitted",
                    "is_locked": True,
                    "submission_datetime": fields.Datetime.now(),
                })
                submitted_count += 1

            # Auto-lock candidate interview record ONLY when ALL assigned panel members have submitted
            candidate_record = eval_rec.candidate_interview_id.sudo()
            if candidate_record:
                candidate_record._compute_final_interview_score()
                candidate_record._compute_evaluation_progress()
                all_evals = candidate_record.evaluation_ids
                if all_evals and not all_evals.filtered(lambda e: e.state != "submitted"):
                    candidate_record.write({"state": "locked"})
                    candidate_record.message_post(
                        body=_("All %d panel evaluations submitted. Candidate evaluation set is now AUTO-LOCKED and immutable (FR-CBIS-021).") % len(all_evals)
                    )

        if errors:
            err_detail = "\n".join(errors)
            raise ValidationError(
                _("The following candidates have incomplete ratings and were NOT submitted:\n\n%s\n\nPlease complete their scores and try again, or submit them individually.") % err_detail
            )

        msg = _("%d candidate evaluation(s) submitted and locked successfully.") % submitted_count
        if skipped_absent:
            msg += _(" (%d absent candidate(s) included.)") % skipped_absent

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('All Evaluations Submitted'),
                'message': msg,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }


class CBISInterviewerEvaluationLine(models.Model):
    """
    ============================================================
    Supports STAR, STARR, and Likert evaluation formats with behavioral comments.
    """
    _name = "cbis.interviewer.evaluation.line"
    _description = "Competency Evaluation Rating Line"
    _order = "sequence asc, id asc"

    evaluation_id = fields.Many2one("cbis.interviewer.evaluation", string="Evaluation", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    
    competency_id = fields.Many2one("competency.competency", string="Competency", required=True)
    competency_description = fields.Text(related="competency_id.definition", string="Competency Description", readonly=True)
    
    evaluation_method = fields.Selection([
        ("star", "STAR Method"),
        ("starr", "STARR Method"),
        ("likert", "Likert Scale (1-5)"),
    ], string="Method", default="star", required=True)

    weight_percentage = fields.Float(string="Weight (%)", default=20.0, required=True)
    suggested_question = fields.Text(string="Suggested Interview Question Prompt")

    RATING_SELECTION = [
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ]

    # STAR / STARR / Likert Component Rating Dropdowns (1 to 5 Selection)
    star_situation = fields.Selection(RATING_SELECTION, string="S (Situation)")
    star_task = fields.Selection(RATING_SELECTION, string="T (Task)")
    star_action = fields.Selection(RATING_SELECTION, string="A (Action)")
    star_result = fields.Selection(RATING_SELECTION, string="R (Result)")
    starr_reflection = fields.Selection(RATING_SELECTION, string="Refl (Reflection)")
    likert_score = fields.Selection(RATING_SELECTION, string="Likert Rating")

    # STAR / STARR Observation Notes
    situation_notes = fields.Text(string="Situation (S) Notes")
    task_notes = fields.Text(string="Task (T) Notes")
    action_notes = fields.Text(string="Action (A) Notes")
    result_notes = fields.Text(string="Result (R) Notes")
    reflection_notes = fields.Text(string="Reflection (R) Notes (STARR)")

    # Component Weight and Calculated Marks Breakdown
    component_weight = fields.Float(string="Component Weight (%)", compute="_compute_component_marks", store=True)
    situation_mark = fields.Float(string="Situation Mark", compute="_compute_component_marks", store=True)
    task_mark = fields.Float(string="Task Mark", compute="_compute_component_marks", store=True)
    action_mark = fields.Float(string="Action Mark", compute="_compute_component_marks", store=True)
    result_mark = fields.Float(string="Result Mark", compute="_compute_component_marks", store=True)
    reflection_mark = fields.Float(string="Reflection Mark", compute="_compute_component_marks", store=True)

    # Competency Aggregate Rating and Scores
    score = fields.Float(string="Average Rating (1 - 5)", compute="_compute_component_marks", store=True)
    score_percentage = fields.Float(string="Score (%)", compute="_compute_component_marks", store=True)
    weighted_score = fields.Float(string="Weighted Score (%)", compute="_compute_component_marks", store=True)
    
    interviewer_remarks = fields.Text(string="Interviewer Remarks / Justification")

    @api.depends(
        "evaluation_id.candidate_status", "evaluation_id.is_absent",
        "evaluation_method", "weight_percentage",
        "star_situation", "star_task", "star_action", "star_result",
        "starr_reflection", "likert_score"
    )
    def _compute_component_marks(self):
        for line in self:
            if line.evaluation_id and (line.evaluation_id.candidate_status == "absent" or line.evaluation_id.is_absent):
                line.component_weight = 0.0
                line.situation_mark = 0.0
                line.task_mark = 0.0
                line.action_mark = 0.0
                line.result_mark = 0.0
                line.reflection_mark = 0.0
                line.score = 0.0
                line.score_percentage = 0.0
                line.weighted_score = 0.0
                continue

            method = line.evaluation_method or "star"
            weight = line.weight_percentage or 0.0


            s_rat = float(line.star_situation or "3")
            t_rat = float(line.star_task or "3")
            a_rat = float(line.star_action or "3")
            r_rat = float(line.star_result or "3")
            re_rat = float(line.starr_reflection or "3")
            l_rat = float(line.likert_score or "3")

            if method == "star":
                comp_weight = weight / 4.0
                line.component_weight = round(comp_weight, 2)

                s_mark = (s_rat / 5.0) * comp_weight
                t_mark = (t_rat / 5.0) * comp_weight
                a_mark = (a_rat / 5.0) * comp_weight
                r_mark = (r_rat / 5.0) * comp_weight

                line.situation_mark = round(s_mark, 2)
                line.task_mark = round(t_mark, 2)
                line.action_mark = round(a_mark, 2)
                line.result_mark = round(r_mark, 2)
                line.reflection_mark = 0.0

                avg_rating = (s_rat + t_rat + a_rat + r_rat) / 4.0
                line.score = round(avg_rating, 2)
                line.score_percentage = round((avg_rating / 5.0) * 100.0, 2)
                line.weighted_score = round(s_mark + t_mark + a_mark + r_mark, 2)

            elif method == "starr":
                comp_weight = weight / 5.0
                line.component_weight = round(comp_weight, 2)

                s_mark = (s_rat / 5.0) * comp_weight
                t_mark = (t_rat / 5.0) * comp_weight
                a_mark = (a_rat / 5.0) * comp_weight
                r_mark = (r_rat / 5.0) * comp_weight
                re_mark = (re_rat / 5.0) * comp_weight

                line.situation_mark = round(s_mark, 2)
                line.task_mark = round(t_mark, 2)
                line.action_mark = round(a_mark, 2)
                line.result_mark = round(r_mark, 2)
                line.reflection_mark = round(re_mark, 2)

                avg_rating = (s_rat + t_rat + a_rat + r_rat + re_rat) / 5.0
                line.score = round(avg_rating, 2)
                line.score_percentage = round((avg_rating / 5.0) * 100.0, 2)
                line.weighted_score = round(s_mark + t_mark + a_mark + r_mark + re_mark, 2)

            else:  # likert
                line.component_weight = round(weight, 2)
                line.situation_mark = 0.0
                line.task_mark = 0.0
                line.action_mark = 0.0
                line.result_mark = 0.0
                line.reflection_mark = 0.0

                line.score = round(l_rat, 2)
                line.score_percentage = round((l_rat / 5.0) * 100.0, 2)
                line.weighted_score = round((l_rat / 5.0) * weight, 2)

    @api.constrains("evaluation_method", "star_situation", "star_task", "star_action", "star_result", "starr_reflection", "likert_score")
    def _check_score_range(self):
        for line in self:
            method = line.evaluation_method or "star"
            if method == "star":
                checks = [
                    (line.star_situation, "Situation"),
                    (line.star_task, "Task"),
                    (line.star_action, "Action"),
                    (line.star_result, "Result"),
                ]
            elif method == "starr":
                checks = [
                    (line.star_situation, "Situation"),
                    (line.star_task, "Task"),
                    (line.star_action, "Action"),
                    (line.star_result, "Result"),
                    (line.starr_reflection, "Reflection"),
                ]
            else:  # likert
                checks = [
                    (line.likert_score, "Likert Rating"),
                ]

            for val, name in checks:
                if val and val not in ["1", "2", "3", "4", "5"]:
                    raise ValidationError(_("Rating for %s in competency '%s' must be selected from 1 to 5.") % (name, line.competency_id.name))


