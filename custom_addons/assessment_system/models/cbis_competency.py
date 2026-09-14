# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class Competency(models.Model):
    """
    Extends the central competency.competency model from competency_management with CBIS interview evaluation configuration.
    """
    _inherit = "competency.competency"

    evaluation_method = fields.Selection([
        ("star", "STAR Method (Situation, Task, Action, Result)"),
        ("starr", "STARR Method (Situation, Task, Action, Result, Reflection)"),
        ("likert", "Likert Scale (1 - 5 Behavioral Anchors)"),
    ], string="Evaluation Method", default="star")

    question_ids = fields.One2many(
        "assessment.competency.question",
        "competency_id",
        string="Suggested Interview Questions",
        copy=True
    )

    behavioral_anchor_ids = fields.One2many(
        "assessment.competency.anchor",
        "competency_id",
        string="Behavioral Anchors (1-5 Guide)",
        copy=True
    )

    job_mapping_ids = fields.One2many(
        "assessment.competency.job.rel",
        "competency_id",
        string="Linked Job Positions"
    )


class AssessmentCompetencyQuestion(models.Model):
    """
    Suggested Interview Questions per Competency
    """
    _name = "assessment.competency.question"
    _description = "Competency Suggested Interview Question"
    _order = "sequence asc, id asc"

    def _auto_init(self):
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'assessment_competency_question') THEN
                    DELETE FROM assessment_competency_question 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
            END $$;
        """)
        return super()._auto_init()

    competency_id = fields.Many2one(
        "competency.competency",
        string="Competency",
        required=True,
        ondelete="cascade"
    )
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Text(string="Suggested Question Prompt", required=True)
    look_for = fields.Text(string="What to Look For / Desired Indicators")
    difficulty = fields.Selection([
        ("basic", "Basic / Junior"),
        ("medium", "Intermediate"),
        ("complex", "Senior / Managerial"),
    ], string="Difficulty Level", default="medium")


class AssessmentCompetencyAnchor(models.Model):
    """
    Behavioral Anchors (1 to 5) for Objective Scoring Guidelines
    """
    _name = "assessment.competency.anchor"
    _description = "Competency Behavioral Scoring Anchor"
    _order = "score_level asc"

    def _auto_init(self):
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'assessment_competency_anchor') THEN
                    DELETE FROM assessment_competency_anchor 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
            END $$;
        """)
        return super()._auto_init()

    competency_id = fields.Many2one(
        "competency.competency",
        string="Competency",
        required=True,
        ondelete="cascade"
    )
    score_level = fields.Selection([
        ("1", "1 - Unsatisfactory / Below Standard"),
        ("2", "2 - Marginal / Developing"),
        ("3", "3 - Competent / Meets Standard"),
        ("4", "4 - Advanced / Exceeds Standard"),
        ("5", "5 - Outstanding / Role Model"),
    ], string="Rating Level", required=True)
    
    behavioral_description = fields.Text(string="Observable Behavioral Indicators", required=True)


class AssessmentCompetencyJobRel(models.Model):
    """
    =================================================
    Maps required competencies to job positions with weights summing to 100% per job.
    """
    _name = "assessment.competency.job.rel"
    _description = "Job Position Competency Profile"
    _order = "job_id asc, sequence asc"

    def _auto_init(self):
        self.env.cr.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'assessment_competency_job_rel') THEN
                    DELETE FROM assessment_competency_job_rel 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cbis_interviewer_evaluation_line') THEN
                    DELETE FROM cbis_interviewer_evaluation_line 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'exam_question') THEN
                    UPDATE exam_question SET competency_id = NULL 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'exam_definition_distribution') THEN
                    UPDATE exam_definition_distribution SET competency_id = NULL 
                    WHERE competency_id IS NOT NULL 
                      AND competency_id NOT IN (SELECT id FROM competency_competency);
                END IF;
            END $$;
        """)
        return super()._auto_init()

    job_id = fields.Many2one("hr.job", string="Job Position", required=True, ondelete="cascade", index=True)
    competency_id = fields.Many2one("competency.competency", string="Competency", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    
    evaluation_method = fields.Selection(
        related="competency_id.evaluation_method",
        string="Method",
        readonly=True
    )
    
    weight_percentage = fields.Float(
        string="Weight (%)",
        required=True,
        default=20.0,
        help="Weight of this competency in the interview evaluation"
    )
    
    target_score = fields.Float(string="Target Benchmark Score (out of 5 / 100)", default=3.0)

    @api.constrains("job_id", "weight_percentage")
    def _check_weight_percentage(self):
        for line in self:
            if line.weight_percentage <= 0 or line.weight_percentage > 100:
                raise ValidationError(_("Competency weight percentage must be greater than 0% and at most 100%."))
            if line.job_id:
                total_weight = sum(self.search([("job_id", "=", line.job_id.id)]).mapped("weight_percentage"))
                if total_weight > 100.001:
                    raise ValidationError(_("Total competency weight for job '%s' cannot exceed 100%% (Current Total: %.2f%%).") % (line.job_id.name, total_weight))

