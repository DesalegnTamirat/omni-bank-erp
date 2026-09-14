# -*- coding: utf-8 -*-

import string
import random
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ExamDefinition(models.Model):
    """
    ========================================================
    Configures written exams linked to specific job vacancies, recruitment requests,
    with automated question distribution, timer durations, passing score thresholds,
    and randomization parameters.
    """
    _name = "exam.definition"
    _description = "Assessment Exam Definition"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Exam Title", required=True, tracking=True)
    code = fields.Char(string="Exam Code", readonly=True, copy=False, default=lambda self: _("New"))
    active = fields.Boolean(default=True, tracking=True)

    job_id = fields.Many2one("hr.job", string="Target Job Position", required=True, tracking=True, index=True)
    vacancy_id = fields.Many2one("job.vacancy", string="Linked Job Vacancy", tracking=True, index=True)
    recruitment_request_id = fields.Many2one("recruitment.request", string="Recruitment Request", tracking=True)

    assessment_type = fields.Selection([
        ("recruitment", "Recruitment Exam"),
        ("transfer", "Internal Transfer Exam"),
        ("promotion", "Promotion Assessment Exam"),
    ], string="Assessment Scope", default="recruitment", required=True, tracking=True)

    # Timing & Delivery Configuration
    duration_minutes = fields.Integer(string="Duration (Minutes)", default=60, required=True, tracking=True)
    passing_score_percentage = fields.Float(
        string="Passing Score (%)",
        default=50.0,
        required=True,
        tracking=True,
        help="Floor requirement Defaults to 50%."
    )
    
    late_arrival_lockout_minutes = fields.Integer(
        string="Late Arrival Lockout (Minutes)",
        default=15,
        required=True,
        help="Candidates arriving after this window from exam start will be locked out and disqualified."
    )
    
    tab_switch_violation_limit = fields.Integer(
        string="Max Allowed Tab Switches",
        default=3,
        required=True,
        help="Violation threshold before auto-disqualification"
    )

    # Randomization & Security Controls
    randomize_questions = fields.Boolean(string="Randomize Question Order", default=True)
    randomize_options = fields.Boolean(string="Randomize Answer Choices", default=True)
    block_copy_paste = fields.Boolean(string="Enforce Copy/Paste Lock", default=True)
    block_screenshot = fields.Boolean(string="Prevent Screenshot / Screen Capture", default=True)
    exclude_previously_used_questions = fields.Boolean(
        string="Exclude Questions Taken in Past Exams",
        default=True,
        help="When enabled, questions previously administered to candidates in past exam sessions will be excluded from newly generated exams."
    )
    question_cooldown_days = fields.Integer(
        string="Question Cooldown Period (Days)",
        default=60,
        help="Number of days to prevent reusing past exam questions (e.g. 60 days). Set to 0 to exclude all past administered questions forever."
    )

    # Question Selection Mode
    selection_mode = fields.Selection([
        ("auto_distribution", "Automated Draw by Competency & Difficulty"),
        ("manual_select", "Manual Specific Question Selection"),
    ], string="Question Selection Mode", default="auto_distribution", required=True)

    distribution_line_ids = fields.One2many(
        "exam.definition.distribution",
        "exam_id",
        string="Question Distribution Rules",
        copy=True
    )

    manual_question_ids = fields.Many2many(
        "exam.question",
        "exam_definition_manual_question_rel",
        "exam_id",
        "question_id",
        string="Selected Questions",
        domain="[('state', '=', 'approved')]"
    )

    total_questions = fields.Integer(string="Total Questions", compute="_compute_totals", store=True)
    total_marks = fields.Float(string="Total Marks", compute="_compute_totals", store=True)

    session_ids = fields.One2many("exam.session", "exam_id", string="Scheduled Sessions")
    session_count = fields.Integer(string="Sessions", compute="_compute_session_count")

    # Multi-Version Exam Support
    is_version_paper = fields.Boolean(string="Is Version Paper", default=False)
    version_code = fields.Char(string="Version Code", default="Master")
    parent_exam_id = fields.Many2one("exam.definition", string="Master Exam Template", ondelete="cascade")
    child_version_ids = fields.One2many("exam.definition", "parent_exam_id", string="Exam Paper Versions")
    child_version_count = fields.Integer(string="Generated Versions", compute="_compute_version_count")
    number_of_versions_to_generate = fields.Integer(
        string="Versions to Generate",
        default=4,
        help="Number of randomized multi-version exam papers (e.g., Version A, B, C, D) to generate directly from the configured rules."
    )

    state = fields.Selection([
        ("draft", "Draft"),
        ("confirmed", "Confirmed / Ready to Schedule"),
        ("in_progress", "Live / In Progress"),
        ("closed", "Closed / Completed"),
        ("archived", "Archived"),
    ], string="Status", default="draft", tracking=True, required=True)

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id(self):
        if self.vacancy_id:
            if hasattr(self.vacancy_id, "job_position") and self.vacancy_id.job_position:
                self.job_id = self.vacancy_id.job_position
            elif hasattr(self.vacancy_id, "job_id") and self.vacancy_id.job_id:
                self.job_id = self.vacancy_id.job_id

            if hasattr(self.vacancy_id, "recruitment_request_id") and self.vacancy_id.recruitment_request_id:
                self.recruitment_request_id = self.vacancy_id.recruitment_request_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("exam.definition") or _("EXM/%05d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("distribution_line_ids.number_of_questions", "distribution_line_ids.marks_per_question",
                 "manual_question_ids.marks", "selection_mode")
    def _compute_totals(self):
        for rec in self:
            if rec.selection_mode == "auto_distribution":
                rec.total_questions = sum(line.number_of_questions for line in rec.distribution_line_ids)
                rec.total_marks = sum(line.number_of_questions * line.marks_per_question for line in rec.distribution_line_ids)
            else:
                rec.total_questions = len(rec.manual_question_ids)
                rec.total_marks = sum(q.marks for q in rec.manual_question_ids)

    def _compute_session_count(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)

    def _compute_version_count(self):
        for rec in self:
            rec.child_version_count = len(rec.child_version_ids)

    def action_view_versions(self):
        self.ensure_one()
        return {
            "name": _("Exam Versions for %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "exam.definition",
            "view_mode": "list,form",
            "domain": [("parent_exam_id", "=", self.id)],
            "context": {"default_parent_exam_id": self.id, "default_job_id": self.job_id.id, "default_is_version_paper": True},
        }

    def action_confirm(self):
        for rec in self:
            if rec.total_questions <= 0:
                raise ValidationError(_("Exam '%s' must have at least one question configured.") % rec.name)
            if rec.passing_score_percentage < 50.0:
                raise ValidationError(_("Passing score must be at least 50.0%% per Bank Policy "))
            rec.state = "confirmed"

    def action_reset_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_view_sessions(self):
        self.ensure_one()
        return {
            "name": _("Exam Sessions for %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "exam.session",
            "view_mode": "list,form",
            "domain": [("exam_id", "=", self.id)],
            "context": {"default_exam_id": self.id, "default_job_id": self.job_id.id},
        }

    def action_generate_multi_versions(self):
        """
        Directly generates randomized multi-version exam papers (Version A, B, C, D...)
        based on the exact criteria, distribution rules, timer, and security settings
        already configured on this exam definition. Does NOT open an external wizard.
        """
        self.ensure_one()
        if self.selection_mode == "auto_distribution" and not self.distribution_line_ids:
            raise UserError(_("Please configure at least one Automated Question Distribution Rule before generating versions."))
        if self.selection_mode == "manual_select" and not self.manual_question_ids:
            raise UserError(_("Please select at least one question before generating versions."))

        version_count = max(1, min(self.number_of_versions_to_generate or 4, 26))

        # Check for previously scheduled versions (PROTECTED from deletion)
        scheduled_versions = self.child_version_ids.filtered(lambda v: v.session_count > 0)
        
        # Only clean up unscheduled/draft versions when regenerating
        unscheduled_versions = self.child_version_ids.filtered(lambda v: v.session_count == 0)
        if unscheduled_versions:
            unscheduled_versions.unlink()

        alphabet = string.ascii_uppercase
        start_idx = len(scheduled_versions)
        generated_versions = self.env["exam.definition"]

        # Track previously used questions across versions & past candidate sessions to prevent repetitive questions
        used_question_ids = set()
        for sv in scheduled_versions:
            used_question_ids.update(sv.manual_question_ids.ids)

        # If enabled, automatically exclude questions already administered to candidates in past exam sessions
        if self.exclude_previously_used_questions:
            # 1. From candidate answers in previous exam sessions
            candidate_ans_domain = [('question_id', '!=', False)]
            if self.job_id:
                candidate_ans_domain.append(('attempt_id.job_id', '=', self.job_id.id))
            if self.question_cooldown_days > 0:
                cutoff_date = fields.Datetime.now() - timedelta(days=self.question_cooldown_days)
                candidate_ans_domain.append(('create_date', '>=', cutoff_date))
            
            past_candidate_q_ids = self.env['exam.candidate.answer'].search(candidate_ans_domain).mapped('question_id.id')
            used_question_ids.update(past_candidate_q_ids)

            # 2. From previously completed/active exam sessions for this job
            session_domain = [('state', 'in', ['active', 'evaluating', 'completed'])]
            if self.job_id:
                session_domain.append(('job_id', '=', self.job_id.id))
            if self.question_cooldown_days > 0:
                cutoff_date = fields.Datetime.now() - timedelta(days=self.question_cooldown_days)
                session_domain.append(('start_datetime', '>=', cutoff_date))
            
            past_sessions = self.env['exam.session'].search(session_domain)
            for sess in past_sessions:
                if sess.exam_id and sess.exam_id.manual_question_ids:
                    used_question_ids.update(sess.exam_id.manual_question_ids.ids)

        for i in range(version_count):
            letter_idx = start_idx + i
            letter = alphabet[letter_idx] if letter_idx < len(alphabet) else str(letter_idx + 1)
            v_code = f"Version {letter}"
            v_title = f"{self.name} - {v_code}"

            # Sample questions, prioritizing fresh questions not yet used in previous versions
            sampled_questions = self.generate_question_pool_for_candidate(
                seed=f"{self.id}_{letter}_{random.random()}",
                exclude_question_ids=list(used_question_ids)
            )

            # Record sampled questions into tracking set
            for q in sampled_questions:
                used_question_ids.add(q.id)

            v_vals = {
                "name": v_title,
                "job_id": self.job_id.id,
                "vacancy_id": self.vacancy_id.id if self.vacancy_id else False,
                "recruitment_request_id": self.recruitment_request_id.id if self.recruitment_request_id else False,
                "assessment_type": self.assessment_type,
                "duration_minutes": self.duration_minutes,
                "passing_score_percentage": self.passing_score_percentage,
                "late_arrival_lockout_minutes": self.late_arrival_lockout_minutes,
                "tab_switch_violation_limit": self.tab_switch_violation_limit,
                "randomize_questions": self.randomize_questions,
                "randomize_options": self.randomize_options,
                "block_copy_paste": self.block_copy_paste,
                "block_screenshot": self.block_screenshot,
                "selection_mode": "manual_select",
                "manual_question_ids": [(6, 0, [q.id for q in sampled_questions])],
                "is_version_paper": True,
                "version_code": v_code,
                "parent_exam_id": self.id,
                "state": "confirmed",
            }
            new_version = self.env["exam.definition"].create(v_vals)
            generated_versions |= new_version

        # Return action to view generated versions
        return {
            "name": _("Generated Multi-Version Papers for %s (%d Versions)") % (self.name, len(generated_versions)),
            "type": "ir.actions.act_window",
            "res_model": "exam.definition",
            "view_mode": "list,form",
            "domain": [("parent_exam_id", "=", self.id)],
            "context": {
                "default_parent_exam_id": self.id,
                "default_job_id": self.job_id.id,
                "default_is_version_paper": True
            },
        }

    def generate_question_pool_for_candidate(self, seed=None, exclude_question_ids=None):
        """
        Pulls questions from Question Bank based on configured distribution rules.
        If exclude_question_ids is provided, prioritizes fresh unused questions.
        Returns a list of exam.question records.
        """
        self.ensure_one()
        questions = []
        exclude_set = set(exclude_question_ids or [])
        
        if self.selection_mode == "manual_select":
            if self.manual_question_ids:
                questions = list(self.manual_question_ids)
            elif self.parent_exam_id:
                # Auto-heal empty version paper from parent exam
                questions = self.parent_exam_id.generate_question_pool_for_candidate(seed=seed, exclude_question_ids=exclude_question_ids)
                if questions:
                    self.write({"manual_question_ids": [(6, 0, [q.id for q in questions])]})
            else:
                # Fallback to general approved question pool if no manual questions exist
                questions = list(self.env["exam.question"].search([("state", "=", "approved"), ("active", "=", True)], limit=10))
                if questions:
                    self.write({"manual_question_ids": [(6, 0, [q.id for q in questions])]})
        else:
            for dist in self.distribution_line_ids:
                base_domain = [
                    ("state", "=", "approved"),
                    ("active", "=", True),
                ]
                if dist.question_type:
                    base_domain.append(("question_type", "=", dist.question_type))

                target_job = dist.job_id or self.job_id

                # --- Tier 1: Exact Match (Competency + Difficulty + Job) ---
                t1_domain = list(base_domain)
                if dist.competency_id:
                    t1_domain.append(("competency_id", "=", dist.competency_id.id))
                if dist.difficulty:
                    t1_domain.append(("difficulty", "=", dist.difficulty))
                if target_job:
                    t1_domain.append(("job_id", "=", target_job.id))
                available = self.env["exam.question"].search(t1_domain)

                # --- Tier 2: Any Difficulty for this Competency & Job ---
                if len(available) < dist.number_of_questions and dist.competency_id:
                    t2_domain = list(base_domain) + [("competency_id", "=", dist.competency_id.id)]
                    if target_job:
                        t2_domain.append(("job_id", "in", [target_job.id, False]))
                    available = self.env["exam.question"].search(t2_domain)

                # --- Tier 3: Any Competency for this Question Type & Job ---
                if len(available) < dist.number_of_questions:
                    t3_domain = list(base_domain)
                    if target_job:
                        t3_domain.append(("job_id", "in", [target_job.id, False]))
                    available = self.env["exam.question"].search(t3_domain)

                # --- Tier 4: Global Approved Questions for this Question Type ---
                if len(available) < dist.number_of_questions:
                    t4_domain = list(base_domain)
                    available = self.env["exam.question"].search(t4_domain)

                # --- Tier 5: Absolute Fallback to ANY Approved Question in Bank ---
                if not available:
                    available = self.env["exam.question"].search([("state", "=", "approved"), ("active", "=", True)])

                if not available:
                    raise UserError(_("No approved questions exist in the Question Bank. Please create and approve questions first."))
                
                # --- Anti-Repetition Filter: prioritize questions not yet used in previous versions ---
                fresh_pool = [q for q in available if q.id not in exclude_set]
                if len(fresh_pool) >= dist.number_of_questions:
                    sampled = random.sample(fresh_pool, dist.number_of_questions)
                else:
                    # Take all fresh questions and fill remaining from general pool
                    sampled = list(fresh_pool)
                    remaining_needed = dist.number_of_questions - len(sampled)
                    recycled_pool = [q for q in available if q not in sampled]
                    if recycled_pool:
                        sampled.extend(random.sample(recycled_pool, min(remaining_needed, len(recycled_pool))))
                    # If still short, sample from available with replacement
                    while len(sampled) < dist.number_of_questions and available:
                        sampled.append(random.choice(list(available)))

                questions.extend(sampled)
        
        if self.randomize_questions and questions:
            rand_gen = random.Random(seed) if seed else random
            rand_gen.shuffle(questions)
            
        return questions


class ExamDefinitionDistribution(models.Model):
    """
    Question Distribution Rules per Competency, Difficulty, and Question Type
    """
    _name = "exam.definition.distribution"
    _description = "Exam Question Distribution Rule"
    _order = "sequence asc, id asc"

    exam_id = fields.Many2one("exam.definition", string="Exam", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    
    job_id = fields.Many2one(
        "hr.job",
        string="Job Filter",
        help="Leave empty to use Exam's target job position"
    )
    competency_id = fields.Many2one("competency.competency", string="Competency Area", required=False)
    eligible_competency_ids = fields.Many2many("competency.competency", compute="_compute_eligible_competency_ids")

    @api.depends("job_id", "exam_id.job_id")
    def _compute_eligible_competency_ids(self):
        for rec in self:
            target_job = rec.job_id or (rec.exam_id and rec.exam_id.job_id)
            if target_job:
                all_comps = self.env["competency.competency"]

                # 1. Primary table: hr_competencies_info_job
                info_job_lines = self.env["hr_competencies_info_job"].search([
                    ("job_id", "=", target_job.id)
                ])
                if info_job_lines:
                    comps = info_job_lines.mapped("competencies")
                    if comps and comps._name == "competency.competency":
                        all_comps |= comps.filtered(
                            lambda c: getattr(c, "status", None) == "active" and getattr(c, "pillar", None) in ["core", "leadership", "technical"]
                        )
                    elif comps and comps._name == "recruitment.competency":
                        comp_names = [c.competency for c in comps if getattr(c, "competency", False)]
                        if comp_names:
                            all_comps |= self.env["competency.competency"].search([
                                ("name", "in", comp_names),
                                ("status", "=", "active"),
                                ("pillar", "in", ["core", "leadership", "technical"])
                            ])

                # 2. Applicable jobs on competency.competency
                comp1 = self.env["competency.competency"].search([
                    ("applicable_job_ids", "in", target_job.id),
                    ("status", "=", "active"),
                    ("pillar", "in", ["core", "leadership", "technical"])
                ])
                all_comps |= comp1

                # 3. Job Competency Profiles (assessment.competency.job.rel)
                rel_lines = self.env["assessment.competency.job.rel"].search([
                    ("job_id", "=", target_job.id)
                ])
                all_comps |= rel_lines.mapped("competency_id").filtered(
                    lambda c: c.status == "active" and c.pillar in ["core", "leadership", "technical"]
                )

                # 4. Role Mappings (competency.role.mapping)
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "=", target_job.id)
                ])
                all_comps |= mappings.mapped("line_ids.competency_id").filtered(
                    lambda c: c.status == "active" and c.pillar in ["core", "leadership", "technical"]
                )

                if not all_comps:
                    all_comps = self.env["competency.competency"].search([
                        ("pillar", "in", ["core", "leadership", "technical"]),
                        ("status", "=", "active")
                    ])

                # Pick 1 representative competency for each Pillar Category existing for this position
                pillar_comps = self.env["competency.competency"]
                for p in ["core", "leadership", "technical"]:
                    p_match = all_comps.filtered(lambda c: c.pillar == p)
                    if p_match:
                        pillar_comps |= p_match[0]

                rec.eligible_competency_ids = pillar_comps
            else:
                pillar_comps = self.env["competency.competency"]
                for p in ["core", "leadership", "technical"]:
                    p_match = self.env["competency.competency"].search([
                        ("pillar", "=", p),
                        ("status", "=", "active")
                    ], limit=1)
                    if p_match:
                        pillar_comps |= p_match
                rec.eligible_competency_ids = pillar_comps

    @api.onchange("job_id", "exam_id")
    def _onchange_job_id_filter_competency(self):
        target_job = self.job_id or (self.exam_id and self.exam_id.job_id)
        if target_job:
            all_comps = self.env["competency.competency"]
            info_job_lines = self.env["hr_competencies_info_job"].search([
                ("job_id", "=", target_job.id)
            ])
            if info_job_lines:
                comps = info_job_lines.mapped("competencies")
                if comps and comps._name == "competency.competency":
                    all_comps |= comps.filtered(
                        lambda c: getattr(c, "status", None) == "active" and getattr(c, "pillar", None) in ["core", "leadership", "technical"]
                    )
                elif comps and comps._name == "recruitment.competency":
                    comp_names = [c.competency for c in comps if getattr(c, "competency", False)]
                    if comp_names:
                        all_comps |= self.env["competency.competency"].search([
                            ("name", "in", comp_names),
                            ("status", "=", "active"),
                            ("pillar", "in", ["core", "leadership", "technical"])
                        ])
            comp1 = self.env["competency.competency"].search([
                ("applicable_job_ids", "in", target_job.id),
                ("status", "=", "active"),
                ("pillar", "in", ["core", "leadership", "technical"])
            ])
            all_comps |= comp1

            pillar_comps = self.env["competency.competency"]
            for p in ["core", "leadership", "technical"]:
                p_match = all_comps.filtered(lambda c: c.pillar == p)
                if p_match:
                    pillar_comps |= p_match[0]

            if pillar_comps and self.competency_id and self.competency_id.id not in pillar_comps.ids:
                self.competency_id = False
            elif not pillar_comps and self.competency_id:
                self.competency_id = False

    difficulty = fields.Selection([
        ("basic", "Basic"),
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ], string="Difficulty Level")
    
    question_type = fields.Selection([
        ("essay", "Essay"),
        ("mcq_single", "MCQ Single Answer"),
        ("mcq_multiple", "MCQ Multiple Answers"),
        ("true_false", "True / False"),
        ("fill_blank", "Fill in the Blank"),
        ("short_answer", "Short Answer"),
    ], string="Question Type")

    number_of_questions = fields.Integer(string="No. of Questions", required=True, default=5)
    marks_per_question = fields.Float(string="Marks Per Question", required=True, default=2.0)
