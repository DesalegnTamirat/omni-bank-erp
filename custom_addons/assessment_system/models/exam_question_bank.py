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
    competency_pillar = fields.Selection([
        ("core", "Core Competencies"),
        ("leadership", "Leadership Competencies"),
        ("technical", "Technical Competencies"),
    ], string="Competency Pillar", compute="_compute_pillar", store=True, readonly=False, tracking=True, index=True)

    @api.depends("competency_id", "competency_id.pillar")
    def _compute_pillar(self):
        for rec in self:
            if rec.competency_id and rec.competency_id.pillar:
                rec.competency_pillar = rec.competency_id.pillar
            elif not rec.competency_pillar:
                rec.competency_pillar = False
    
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

    eligible_job_ids = fields.Json(string="Eligible Job IDs", compute="_compute_eligible_job_ids", default=[])
    eligible_competency_ids = fields.Json(string="Eligible Competency IDs", compute="_compute_eligible_competency_ids", default=[])

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ou_id = res.get("operating_unit_id")
        ou = self.env["operating.unit"].browse(ou_id) if ou_id else False
        res["eligible_job_ids"] = self._get_active_ou_jobs(ou).ids or []

        job_id = res.get("job_id")
        job = self.env["hr.job"].browse(job_id) if job_id else False
        res["eligible_competency_ids"] = self._get_job_competencies(job, ou).ids or []
        return res

    def _resolve_record_id(self, rec):
        """Safely extract integer database ID from a record or NewId in memory."""
        if not rec:
            return False
        return getattr(rec, "_origin", rec).id or (isinstance(rec.id, int) and rec.id) or (rec.ids and rec.ids[0]) or False

    def _get_active_ou_jobs(self, ou):
        """Return only active job positions configured or held by employees in the given operating unit."""
        ou_id = self._resolve_record_id(ou)
        if not ou_id:
            return self.env["hr.job"].search([("active", "=", True)])

        ou_positions = self.env["operating.unit.job.position"].search([
            ("operating_unit_id", "=", ou_id)
        ]).mapped("job_position_id").filtered(lambda j: j.active)

        emp_positions = self.env["hr.employee"].search([
            ("active", "=", True),
            "|",
            ("default_operating_unit_id", "=", ou_id),
            ("operating_unit_id", "=", ou_id),
        ]).mapped("job_position").filtered(lambda j: j.active)

        jobs = (ou_positions | emp_positions)
        if not jobs:
            depts = self.env["hr.department"].search([
                ("operating_unit_id", "=", ou_id)
            ])
            if depts:
                jobs = self.env["hr.job"].search([
                    ("department_id", "in", depts.ids),
                    ("active", "=", True)
                ])
        return jobs or self.env["hr.job"].search([("active", "=", True)])

    def _get_job_competencies(self, job=None, ou=None):
        """Return competencies mapped to the selected job position from Competency Role Mapping,
        Recruitment Vacancies, and HR Job competencies. If no job is selected, returns competencies
        for all jobs in the operating unit.
        """
        jid = self._resolve_record_id(job)
        comps = self.env["competency.competency"].browse([])

        if jid:
            # 1. From Competency Management Module: Competence Role Mapping (competency.role.mapping)
            mappings = self.env["competency.role.mapping"].search([
                ("job_position_id", "=", jid),
                ("state", "in", ["approved", "draft", "under_approval"]),
            ])
            if not mappings:
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "=", jid),
                ])
            comps |= mappings.mapped("line_ids.competency_id")

            # 2. From Recruitment Module: Job Vacancy Competencies (job.vacancy.competency)
            vac_comps = self.env["job.vacancy.competency"].search([
                ("vacancy_id.job_position", "=", jid),
            ]).mapped("competency_id")
            comps |= vac_comps

            # 3. From HR Job direct competencies (hr_competencies_info_job)
            job_rec = self.env["hr.job"].browse(jid)
            comp_rel = getattr(job_rec, "competencies_id", False) or getattr(job_rec, "competencies_ids", False)
            if comp_rel:
                for line in comp_rel:
                    c = getattr(line, "competencies", False) or getattr(line, "competency_id", False)
                    if c:
                        comps |= c

            active_comps = comps.filtered(
                lambda c: getattr(c, "active", True) and getattr(c, "status", "active") in ("active", False)
            )
            if active_comps:
                return active_comps

        # If job is not selected, fallback to jobs in the operating unit
        ou_id = self._resolve_record_id(ou)
        if ou_id:
            active_jobs = self._get_active_ou_jobs(ou)
            if active_jobs:
                mappings = self.env["competency.role.mapping"].search([
                    ("job_position_id", "in", active_jobs.ids),
                ])
                comps |= mappings.mapped("line_ids.competency_id")
                vac_comps = self.env["job.vacancy.competency"].search([
                    ("vacancy_id.job_position", "in", active_jobs.ids),
                ]).mapped("competency_id")
                comps |= vac_comps
                active_comps = comps.filtered(
                    lambda c: getattr(c, "active", True) and getattr(c, "status", "active") in ("active", False)
                )
                if active_comps:
                    return active_comps

        # Fallback to all active competencies if none found
        return self.env["competency.competency"].search([("active", "=", True)], limit=100)

    @api.depends("operating_unit_id")
    def _compute_eligible_job_ids(self):
        for rec in self:
            rec.eligible_job_ids = self._get_active_ou_jobs(rec.operating_unit_id).ids or []

    @api.depends("job_id", "operating_unit_id")
    def _compute_eligible_competency_ids(self):
        for rec in self:
            rec.eligible_competency_ids = self._get_job_competencies(rec.job_id, rec.operating_unit_id).ids or []

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        active_jobs = self._get_active_ou_jobs(self.operating_unit_id)
        self.eligible_job_ids = active_jobs.ids or []
        jid = self._resolve_record_id(self.job_id)
        if jid and jid not in active_jobs.ids:
            self.job_id = False
            self.competency_id = False
        comps = self._get_job_competencies(self.job_id, self.operating_unit_id)
        self.eligible_competency_ids = comps.ids or []
        return {
            "domain": {
                "job_id": [("id", "in", active_jobs.ids or []), ("active", "=", True)],
                "competency_id": [("id", "in", comps.ids or []), ("active", "=", True)],
            }
        }

    @api.onchange("job_id")
    def _onchange_job_id(self):
        comps = self._get_job_competencies(self.job_id, self.operating_unit_id)
        self.eligible_competency_ids = comps.ids or []
        cid = self._resolve_record_id(self.competency_id)
        if cid and cid not in comps.ids:
            self.competency_id = False
        return {
            "domain": {
                "competency_id": [("id", "in", comps.ids or []), ("active", "=", True)],
            }
        }
    
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
    _rec_name = "option_text"

    question_id = fields.Many2one("exam.question", string="Question", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    option_text = fields.Char(string="Option Text", required=True)
    is_correct = fields.Boolean(string="Is Correct Answer", default=False)
    score_fraction = fields.Float(
        string="Score Fraction",
        default=1.0,
        help="For partial credit in multiple-choice questions (e.g., 0.5 for 2 correct answers)"
    )

    @api.depends("option_text")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.option_text or _("Option #%s") % rec.id
