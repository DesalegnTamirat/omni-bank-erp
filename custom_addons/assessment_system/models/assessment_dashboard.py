# -*- coding: utf-8 -*-
from odoo import models, api, fields
from datetime import date, timedelta


class AssessmentDashboard(models.Model):
    _name = "assessment.dashboard"
    _description = "Assessment Management Dashboard Data Aggregator"

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, assessment_type="all"):
        """Fetches consolidated KPIs, personal queues, and charts data with date and type filters."""
        uid = self.env.uid
        user = self.env.user
        today = fields.Date.context_today(self)

        # ── 1. Models ───────────────────────────────────────────────────────
        exam_session_model = self.env.get("exam.session")
        attempt_model = self.env.get("exam.candidate.attempt")
        grading_task_model = self.env.get("exam.grading.task")
        cbis_session_model = self.env.get("cbis.interview.session")
        cbis_candidate_model = self.env.get("cbis.interview.candidate")
        cbis_eval_model = self.env.get("cbis.interviewer.evaluation")
        transfer_model = self.env.get("transfer.assessment.record")
        pub_model = self.env.get("assessment.result.publication")

        # ── 2. Build Date Domains ───────────────────────────────────────────
        attempt_domain = []
        exam_session_domain = []
        cbis_session_domain = []
        cbis_eval_domain = []
        transfer_domain = []

        if date_from:
            attempt_domain.append(("create_date", ">=", date_from))
            exam_session_domain.append(("create_date", ">=", date_from))
            cbis_session_domain.append(("create_date", ">=", date_from))
            cbis_eval_domain.append(("create_date", ">=", date_from))
            transfer_domain.append(("create_date", ">=", date_from))
        if date_to:
            attempt_domain.append(("create_date", "<=", date_to + " 23:59:59"))
            exam_session_domain.append(("create_date", "<=", date_to + " 23:59:59"))
            cbis_session_domain.append(("create_date", "<=", date_to + " 23:59:59"))
            cbis_eval_domain.append(("create_date", "<=", date_to + " 23:59:59"))
            transfer_domain.append(("create_date", "<=", date_to + " 23:59:59"))

        # ── 3. Written Exam KPIs ────────────────────────────────────────────
        total_exam_sessions = exam_session_model.search_count(exam_session_domain) if exam_session_model else 0
        draft_exam_sessions = exam_session_model.search_count(exam_session_domain + [("state", "=", "draft")]) if exam_session_model else 0
        active_exam_sessions = exam_session_model.search_count(exam_session_domain + [("state", "=", "active")]) if exam_session_model else 0
        
        total_sittings = attempt_model.search_count(attempt_domain) if attempt_model else 0
        completed_sittings = attempt_model.search_count(attempt_domain + [("state", "=", "completed")]) if attempt_model else 0
        active_sittings = attempt_model.search_count(attempt_domain + [("state", "=", "in_progress")]) if attempt_model else 0
        disqualified_sittings = attempt_model.search_count(attempt_domain + [("state", "=", "disqualified")]) if attempt_model else 0
        
        passed_sittings = attempt_model.search_count(attempt_domain + [("state", "=", "completed"), ("passed", "=", True)]) if attempt_model else 0
        failed_sittings = attempt_model.search_count(attempt_domain + [("state", "=", "completed"), ("passed", "=", False)]) if attempt_model else 0

        pending_grading_tasks = grading_task_model.search_count([("state", "=", "pending")]) if grading_task_model else 0
        overdue_grading_tasks = grading_task_model.search_count([("state", "=", "pending"), ("is_overdue", "=", True)]) if grading_task_model else 0
        my_grading_tasks = grading_task_model.search_count([("assigned_grader_id", "=", uid), ("state", "=", "pending")]) if grading_task_model else 0

        # ── 4. CBIS Interview KPIs ──────────────────────────────────────────
        total_interview_sessions = cbis_session_model.search_count(cbis_session_domain) if cbis_session_model else 0
        total_scheduled_candidates = cbis_candidate_model.search_count([]) if cbis_candidate_model else 0
        
        total_evaluations_submitted = cbis_eval_model.search_count(cbis_eval_domain + [("state", "=", "submitted")]) if cbis_eval_model else 0
        total_evaluations_pending = cbis_eval_model.search_count(cbis_eval_domain + [("state", "=", "draft")]) if cbis_eval_model else 0
        my_pending_evaluations = cbis_eval_model.search_count([("interviewer_user_id", "=", uid), ("state", "=", "draft")]) if cbis_eval_model else 0

        # ── 5. Transfer Assessment KPIs ─────────────────────────────────────
        total_transfers = transfer_model.search_count(transfer_domain) if transfer_model else 0
        approved_transfers = transfer_model.search_count(transfer_domain + [("state", "=", "approved")]) if transfer_model else 0
        pending_transfers = transfer_model.search_count(transfer_domain + [("state", "in", ["draft", "submitted", "under_review"])]) if transfer_model else 0
        total_publications = pub_model.search_count([]) if pub_model else 0

        # ── 6. Action Queues ────────────────────────────────────────────────
        my_action_evals = []
        if cbis_eval_model:
            for ev in cbis_eval_model.search([("interviewer_user_id", "=", uid), ("state", "=", "draft")], limit=5):
                my_action_evals.append({
                    "id": ev.id,
                    "candidate_code": getattr(ev, "candidate_code", "—") or "—",
                    "candidate_name": getattr(ev, "candidate_name", "—") or "—",
                    "job_title": ev.job_id.name if getattr(ev, "job_id", False) else "—",
                    "session_name": ev.session_id.name if getattr(ev, "session_id", False) else "—",
                })

        return {
            "stats": {
                # Written Exam System
                "total_sittings": total_sittings,
                "draft_exam_sessions": draft_exam_sessions,
                "active_sittings": active_sittings,
                "completed_sittings": completed_sittings,
                "passed_sittings": passed_sittings,
                "failed_sittings": failed_sittings,
                "disqualified_sittings": disqualified_sittings,
                "pending_grading_tasks": pending_grading_tasks,
                "overdue_grading_tasks": overdue_grading_tasks,
                "my_grading_tasks": my_grading_tasks,
                "total_exam_sessions": total_exam_sessions,
                # CBIS Interview System
                "interview_total": total_scheduled_candidates,
                "interview_completed": total_evaluations_submitted,
                "interview_pending": total_evaluations_pending,
                "my_pending_evaluations": my_pending_evaluations,
                "total_interview_sessions": total_interview_sessions,
                # Transfer Assessment
                "transfer_total": total_transfers,
                "transfer_approved": approved_transfers,
                "transfer_pending": pending_transfers,
                "total_publications": total_publications,
            },
            "my_action_evals": my_action_evals,
            "user_name": user.name,
        }
