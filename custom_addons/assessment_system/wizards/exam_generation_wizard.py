# -*- coding: utf-8 -*-

import string
import random
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ExamGenerationWizard(models.TransientModel):
    """
    Written Exam Multi-Version Generation Wizard
    ============================================
    Generates tailored exam papers and multi-version sets based on
    Vacancy, Job Position, Difficulty Level, Question Types distribution,
    and Version counts from approved Question Bank questions.
    """
    _name = "exam.generation.wizard"
    _description = "Generate Written Exam Versions"

    name = fields.Char(string="Exam Title", required=True, default=lambda self: _("Written Assessment"))
    vacancy_id = fields.Many2one("job.vacancy", string="Target Vacancy")
    job_id = fields.Many2one("hr.job", string="Target Job Position", required=True)
    
    difficulty_level = fields.Selection([
        ("all", "All Levels (Mixed Basic/Easy/Hard)"),
        ("basic", "Basic Level Only"),
        ("easy", "Easy Level Only"),
        ("hard", "Hard Level Only"),
    ], string="Difficulty Level", default="all", required=True)

    duration_minutes = fields.Integer(string="Exam Duration (Minutes)", default=60, required=True)
    passing_score_percentage = fields.Float(string="Passing Score (%)", default=50.0, required=True)

    # Question Type Counts & Allocations
    essay_count = fields.Integer(string="Essay Questions", default=2)
    marks_per_essay = fields.Float(string="Marks per Essay", default=10.0)

    mcq_count = fields.Integer(string="Multiple-Choice (MCQ) Questions", default=10)
    marks_per_mcq = fields.Float(string="Marks per MCQ", default=2.0)

    true_false_count = fields.Integer(string="True / False Questions", default=5)
    marks_per_tf = fields.Float(string="Marks per True/False", default=1.0)

    fill_blank_count = fields.Integer(string="Fill-in-the-Blank Questions", default=5)
    marks_per_blank = fields.Float(string="Marks per Blank", default=2.0)

    # Number of Exam Versions (e.g., 10 Versions)
    version_count = fields.Integer(
        string="Number of Exam Versions",
        default=10,
        required=True,
        help="Number of distinct exam papers to generate with shuffled/sampled questions."
    )

    total_questions = fields.Integer(string="Total Questions per Version", compute="_compute_totals")
    total_marks = fields.Float(string="Total Marks", compute="_compute_totals")

    @api.onchange("job_id")
    def _onchange_job_id(self):
        if self.job_id:
            self.name = _("Written Assessment - %s") % self.job_id.name

    @api.onchange("vacancy_id")
    def _onchange_vacancy_id(self):
        if self.vacancy_id and self.vacancy_id.job_position:
            self.job_id = self.vacancy_id.job_position.id

    @api.depends("essay_count", "mcq_count", "true_false_count", "fill_blank_count",
                 "marks_per_essay", "marks_per_mcq", "marks_per_tf", "marks_per_blank")
    def _compute_totals(self):
        for rec in self:
            rec.total_questions = (
                max(0, rec.essay_count) +
                max(0, rec.mcq_count) +
                max(0, rec.true_false_count) +
                max(0, rec.fill_blank_count)
            )
            rec.total_marks = (
                max(0, rec.essay_count) * max(0, rec.marks_per_essay) +
                max(0, rec.mcq_count) * max(0, rec.marks_per_mcq) +
                max(0, rec.true_false_count) * max(0, rec.marks_per_tf) +
                max(0, rec.fill_blank_count) * max(0, rec.marks_per_blank)
            )

    def _get_question_pool(self, q_types, required_count):
        """Find approved questions matching criteria"""
        domain = [
            ("state", "=", "approved"),
            ("active", "=", True),
            ("question_type", "in", q_types),
        ]
        if self.job_id:
            domain.append(("job_id", "=", self.job_id.id))
            
        if self.difficulty_level != "all":
            domain.append(("difficulty", "=", self.difficulty_level))

        available = self.env["exam.question"].search(domain)
        
        # If not enough with strict job_id, allow global/general questions for that type
        if len(available) < required_count and self.job_id:
            fallback_domain = [
                ("state", "=", "approved"),
                ("active", "=", True),
                ("question_type", "in", q_types),
                ("job_id", "=", False),
            ]
            if self.difficulty_level != "all":
                fallback_domain.append(("difficulty", "=", self.difficulty_level))
            fallback_pool = self.env["exam.question"].search(fallback_domain)
            available = available | fallback_pool

        return available

    def action_generate_exams(self):
        """Generates Master Exam Definition and N child Version Papers"""
        self.ensure_one()
        if self.total_questions <= 0:
            raise UserError(_("Please specify at least 1 question across the question types."))
        if self.version_count <= 0:
            raise UserError(_("Number of exam versions must be at least 1."))

        # 1. Check pool availability
        types_config = [
            ("Essay", ["essay", "short_answer"], self.essay_count, self.marks_per_essay),
            ("Multiple Choice (MCQ)", ["mcq_single", "mcq_multiple"], self.mcq_count, self.marks_per_mcq),
            ("True / False", ["true_false"], self.true_false_count, self.marks_per_tf),
            ("Fill in the Blank", ["fill_blank"], self.fill_blank_count, self.marks_per_blank),
        ]

        pools = {}
        for label, q_types, count, marks in types_config:
            if count > 0:
                pool = self._get_question_pool(q_types, count)
                if len(pool) < count:
                    raise UserError(_(
                        "Insufficient approved questions in Question Bank for '%(type)s'. Required at least %(req)d, but only %(found)d approved questions found for position '%(job)s'.",
                        type=label, req=count, found=len(pool), job=self.job_id.name
                    ))
                pools[label] = {
                    "q_types": q_types,
                    "pool": list(pool),
                    "count": count,
                    "marks": marks,
                }

        # 2. Create Master Exam Definition
        master_exam = self.env["exam.definition"].create({
            "name": self.name,
            "job_id": self.job_id.id,
            "vacancy_id": self.vacancy_id.id if self.vacancy_id else False,
            "duration_minutes": self.duration_minutes,
            "passing_score_percentage": self.passing_score_percentage,
            "selection_mode": "auto_distribution",
            "state": "confirmed",
            "version_code": "Master",
        })

        # Create master distribution rules
        dist_vals = []
        for label, cfg in pools.items():
            primary_type = cfg["q_types"][0]
            dist_vals.append((0, 0, {
                "exam_id": master_exam.id,
                "question_type": primary_type,
                "difficulty": self.difficulty_level if self.difficulty_level != "all" else False,
                "number_of_questions": cfg["count"],
                "marks_per_question": cfg["marks"],
            }))
        # 3. Sample Master Base Question Set (shared across all version papers)
        master_questions = []
        for label, cfg in pools.items():
            pool = cfg["pool"]
            count = cfg["count"]
            if len(pool) >= count:
                sampled = random.sample(pool, count)
            else:
                sampled = pool[:count]
            master_questions.extend(sampled)

        master_exam.write({
            "distribution_line_ids": dist_vals,
            "manual_question_ids": [(6, 0, [q.id for q in master_questions])],
        })

        # 4. Generate N Version Papers (e.g. Version A, Version B...) using exact same questions in randomized order
        version_labels = list(string.ascii_uppercase) + [f"V{i}" for i in range(27, 100)]
        created_versions = []

        for i in range(self.version_count):
            v_code = version_labels[i] if i < len(version_labels) else f"V{i+1}"
            
            # Take exact master questions and shuffle order for this version paper
            v_questions = list(master_questions)
            version_rng = random.Random(f"wizard_v_{master_exam.id}_{v_code}_{i}")
            version_rng.shuffle(v_questions)

            version_paper = self.env["exam.definition"].create({
                "name": f"{self.name} - Version {v_code}",
                "job_id": self.job_id.id,
                "vacancy_id": self.vacancy_id.id if self.vacancy_id else False,
                "duration_minutes": self.duration_minutes,
                "passing_score_percentage": self.passing_score_percentage,
                "selection_mode": "manual_select",
                "manual_question_ids": [(6, 0, [q.id for q in v_questions])],
                "is_version_paper": True,
                "version_code": v_code,
                "parent_exam_id": master_exam.id,
                "state": "confirmed",
            })
            created_versions.append(version_paper.id)

        # 4. Return action viewing the master exam with generated versions
        return {
            "name": _("Exam Master: %s") % master_exam.name,
            "type": "ir.actions.act_window",
            "res_model": "exam.definition",
            "res_id": master_exam.id,
            "view_mode": "form",
            "target": "current",
        }
