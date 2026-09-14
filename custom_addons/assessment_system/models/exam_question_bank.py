# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ExamQuestionBank(models.Model):
    """
    ==================================================
    Central repository for exam questions organized by job position, competency,
    and question type, with strict approval workflows and versioning.
    """
    _name = "exam.question"
    _description = "Exam Question Bank Entry"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Text(string="Question Stem / Problem Statement", required=True, tracking=True)
    code = fields.Char(string="Question Code", readonly=True, copy=False, default=lambda self: _("New"))
    active = fields.Boolean(default=True, tracking=True)
    
    question_type = fields.Selection([
        ("essay", "Essay Question"),
        ("mcq_single", "Multiple Choice (Single Answer)"),
        ("mcq_multiple", "Multiple Choice (Multiple Answers)"),
        ("true_false", "True / False"),
        ("fill_blank", "Fill in the Blank"),
        ("short_answer", "Short Answer"),
    ], string="Question Type", required=True, default="mcq_single", tracking=True)

    job_id = fields.Many2one("hr.job", string="Target Job Position", tracking=True, index=True)
    operating_unit_id = fields.Many2one("operating.unit", string="Submitting Work Unit", default=lambda self: self.env.user.employee_id.operating_unit_id, tracking=True, index=True)
    department_id = fields.Many2one("hr.department", string="Department", tracking=True)
    competency_id = fields.Many2one("competency.competency", string="Competency Area", tracking=True, index=True)
    
    difficulty = fields.Selection([
        ("basic", "Basic"),
        ("easy", "Easy"),
        ("medium", "Medium (Application)"),
        ("hard", "Hard"),
    ], string="Difficulty Level", required=True, default="basic", tracking=True)

    marks = fields.Float(string="Marks Allocated", default=1.0, required=True, tracking=True)
    explanation = fields.Text(string="Answer Explanation / Scoring Rubric", help="Guidelines for auto or manual grading")

    # Options for MCQ / True False
    option_ids = fields.One2many("exam.question.option", "question_id", string="Options / Choices", copy=True)
    
    # Fill in the blank / Short answer reference answer
    correct_text_answer = fields.Char(string="Accepted Text Answer", help="For Fill-in-Blank auto-scoring (case-insensitive)")
    rubric_guidelines = fields.Text(string="Essay Grading Rubric & Expected Key Points")

    # Work Unit Document Submission (PDF, Word, etc.)
    submission_file = fields.Binary(string="Question Document (PDF/Word)", attachment=True)
    submission_filename = fields.Char(string="Attachment Filename")

    eligible_job_ids = fields.Many2many("hr.job", compute="_compute_eligible_job_ids")
    eligible_competency_ids = fields.Many2many("competency.competency", compute="_compute_eligible_competency_ids")

    @api.depends("operating_unit_id")
    def _compute_eligible_job_ids(self):
        for rec in self:
            if rec.operating_unit_id:
                ou_positions = self.env["operating.unit.job.position"].search([
                    ("operating_unit_id", "=", rec.operating_unit_id.id)
                ]).mapped("job_position_id")
                if ou_positions:
                    rec.eligible_job_ids = ou_positions
                else:
                    depts = self.env["hr.department"].search([
                        ("operating_unit_id", "=", rec.operating_unit_id.id)
                    ])
                    dept_jobs = self.env["hr.job"].search([("department_id", "in", depts.ids)]) if depts else False
                    rec.eligible_job_ids = dept_jobs if dept_jobs else self.env["hr.job"].search([])
            else:
                rec.eligible_job_ids = self.env["hr.job"].search([])

    @api.depends("job_id")
    def _compute_eligible_competency_ids(self):
        for rec in self:
            if rec.job_id:
                all_comps = self.env["competency.competency"]

                # 1. Primary table: hr_competencies_info_job
                info_job_lines = self.env["hr_competencies_info_job"].search([
                    ("job_id", "=", rec.job_id.id)
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
                    ("applicable_job_ids", "in", rec.job_id.id),
                    ("status", "=", "active"),
                    ("pillar", "in", ["core", "leadership", "technical"])
                ])
                all_comps |= comp1

                # 3. Job Competency Profiles (assessment.competency.job.rel)
                rel_lines = self.env["assessment.competency.job.rel"].search([
                    ("job_id", "=", rec.job_id.id)
                ])
                all_comps |= rel_lines.mapped("competency_id").filtered(
                    lambda c: c.status == "active" and c.pillar in ["core", "leadership", "technical"]
                )

                # 4. Role Mappings (competency.role.mapping)
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "=", rec.job_id.id)
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

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id:
            ou_positions = self.env["operating.unit.job.position"].search([
                ("operating_unit_id", "=", self.operating_unit_id.id)
            ]).mapped("job_position_id")

            job_ids = list(set(ou_positions.ids))
            if not job_ids:
                depts = self.env["hr.department"].search([
                    ("operating_unit_id", "=", self.operating_unit_id.id)
                ])
                if depts:
                    dept_jobs = self.env["hr.job"].search([
                        ("department_id", "in", depts.ids)
                    ])
                    job_ids = list(set(dept_jobs.ids))

            if job_ids and self.job_id and self.job_id.id not in job_ids:
                self.job_id = False
            elif not job_ids:
                self.job_id = False

    @api.onchange("job_id")
    def _onchange_job_id(self):
        if self.job_id:
            all_comps = self.env["competency.competency"]

            info_job_lines = self.env["hr_competencies_info_job"].search([
                ("job_id", "=", self.job_id.id)
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
                ("applicable_job_ids", "in", self.job_id.id),
                ("status", "=", "active"),
                ("pillar", "in", ["core", "leadership", "technical"])
            ])
            all_comps |= comp1

            rel_lines = self.env["assessment.competency.job.rel"].search([
                ("job_id", "=", self.job_id.id)
            ])
            all_comps |= rel_lines.mapped("competency_id").filtered(
                lambda c: c.status == "active" and c.pillar in ["core", "leadership", "technical"]
            )

            mappings = self.env["competency.role.mapping"].search([
                ("job_position_id", "=", self.job_id.id)
            ])
            all_comps |= mappings.mapped("line_ids.competency_id").filtered(
                lambda c: c.status == "active" and c.pillar in ["core", "leadership", "technical"]
            )

            pillar_comps = self.env["competency.competency"]
            for p in ["core", "leadership", "technical"]:
                p_match = all_comps.filtered(lambda c: c.pillar == p)
                if p_match:
                    pillar_comps |= p_match[0]

            if pillar_comps and self.competency_id and self.competency_id.id not in pillar_comps.ids:
                self.competency_id = False
            elif not pillar_comps and self.competency_id:
                self.competency_id = False
    submission_notes = fields.Text(string="Work Unit Notes / Submission Details")
    rejection_reason = fields.Text(string="HR Rejection Reason / Revision Notes", tracking=True)

    # Approval Workflow & Version Control (FR-EXM-006, FR-EXM-007)
    state = fields.Selection([
        ("draft", "Draft / Submitted"),
        ("review", "Under HR Review"),
        ("approved", "Approved for Exams"),
        ("rejected", "Rejected"),
        ("deactivated", "Deactivated / Obsolete"),
    ], string="Status", default="draft", tracking=True, required=True)

    version = fields.Integer(string="Version", default=1, readonly=True)
    created_by_user_id = fields.Many2one("res.users", string="Author", default=lambda self: self.env.user, readonly=True)
    reviewed_by_user_id = fields.Many2one("res.users", string="Reviewed By", readonly=True, tracking=True)
    approved_by_user_id = fields.Many2one("res.users", string="Approved By", readonly=True, tracking=True)
    approval_date = fields.Datetime(string="Approval Date", readonly=True)
    last_used_date = fields.Datetime(string="Last Used in Exam", readonly=True)
    usage_count = fields.Integer(string="Times Used", default=0, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("exam.question") or _("QST/%05d") % self.search_count([])
        return super().create(vals_list)

    def write(self, vals):
        # Increment version number if stem or options change on approved question
        if "name" in vals or "option_ids" in vals or "marks" in vals:
            for rec in self:
                if rec.state == "approved":
                    vals["version"] = rec.version + 1
        return super().write(vals)

    def action_submit_review(self):
        for rec in self:
            rec._validate_question_content()
            rec.state = "review"

    def action_approve(self):
        for rec in self:
            rec._validate_question_content()
            rec.write({
                "state": "approved",
                "approved_by_user_id": self.env.user.id,
                "approval_date": fields.Datetime.now()
            })

    def action_reject(self):
        for rec in self:
            rec.state = "rejected"

    def action_deactivate(self):
        for rec in self:
            rec.write({"state": "deactivated", "active": False})

    def action_reset_draft(self):
        for rec in self:
            rec.state = "draft"

    def _validate_question_content(self):
        """Ensure question has valid answer keys before approval, auto-healing missing default choices"""
        self.ensure_one()
        if self.question_type == "true_false":
            if not self.option_ids:
                is_true_correct = (self.correct_text_answer or "True").strip().lower() in ["true", "t"]
                self.env["exam.question.option"].create([
                    {"question_id": self.id, "sequence": 1, "option_text": "True", "is_correct": is_true_correct, "score_fraction": 1.0 if is_true_correct else 0.0},
                    {"question_id": self.id, "sequence": 2, "option_text": "False", "is_correct": not is_true_correct, "score_fraction": 1.0 if not is_true_correct else 0.0},
                ])
            else:
                correct_opts = self.option_ids.filtered(lambda o: o.is_correct)
                if len(correct_opts) == 0:
                    self.option_ids[0].is_correct = True
        elif self.question_type == "mcq_single":
            if self.option_ids:
                correct_opts = self.option_ids.filtered(lambda o: o.is_correct)
                if len(correct_opts) == 0:
                    self.option_ids[0].is_correct = True
        elif self.question_type == "mcq_multiple":
            if self.option_ids:
                correct_opts = self.option_ids.filtered(lambda o: o.is_correct)
                if len(correct_opts) == 0:
                    self.option_ids[0].is_correct = True
        elif self.question_type == "fill_blank":
            if not self.correct_text_answer:
                if "[" in (self.name or "") and "]" in (self.name or ""):
                    self.correct_text_answer = self.name.split("[")[1].split("]")[0].strip()


class ExamQuestionOption(models.Model):
    """
    Multiple Choice / True-False Options
    """
    _name = "exam.question.option"
    _description = "Exam Question Option Choice"
    _order = "sequence asc, id asc"

    question_id = fields.Many2one("exam.question", string="Question", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    option_text = fields.Char(string="Option Text", required=True)
    is_correct = fields.Boolean(string="Is Correct Answer", default=False)
    score_fraction = fields.Float(
        string="Score Fraction",
        default=1.0,
        help="For partial credit in multiple-choice questions (e.g., 0.5 for 2 correct answers)"
    )
