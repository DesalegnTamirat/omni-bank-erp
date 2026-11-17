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

        def _get_model(name):
            return self.env[name] if name in self.env else None

        def _count(model, domain=None):
            if model is None:
                return 0
            return model.sudo().search_count(domain or [])

        # ── 1. Models ───────────────────────────────────────────────────────
        exam_session_model = _get_model("exam.session")
        attempt_model = _get_model("exam.candidate.attempt")
        grading_task_model = _get_model("exam.grading.task")
        cbis_session_model = _get_model("cbis.interview.session")
        interview_session_model = _get_model("interview.session")
        cbis_candidate_model = _get_model("cbis.interview.candidate")
        cbis_eval_model = _get_model("cbis.interviewer.evaluation")
        interview_candidate_model = _get_model("interview.candidate.assessment")
        interview_eval_model = _get_model("interview.assessment")
        transfer_model = _get_model("transfer.assessment.record")
        pub_model = _get_model("assessment.result.publication")

        # ── 2. Build Date Domains ───────────────────────────────────────────
        base_date_domain = []
        if date_from:
            base_date_domain.append(("create_date", ">=", date_from))
        if date_to:
            base_date_domain.append(("create_date", "<=", date_to + " 23:59:59"))

        attempt_domain = list(base_date_domain)
        exam_session_domain = list(base_date_domain)
        cbis_session_domain = list(base_date_domain)
        cbis_eval_domain = list(base_date_domain)
        transfer_domain = list(base_date_domain)
        grading_task_domain = list(base_date_domain)
        pub_domain = list(base_date_domain)

        # ── 3. Written Exam KPIs ────────────────────────────────────────────
        total_exam_sessions = _count(exam_session_model, exam_session_domain)
        draft_exam_sessions = _count(exam_session_model, exam_session_domain + [("state", "=", "draft")])
        active_exam_sessions = _count(exam_session_model, exam_session_domain + [("state", "=", "active")])
        
        total_sittings = _count(attempt_model, attempt_domain)
        completed_sittings = _count(attempt_model, attempt_domain + [("state", "=", "completed")])
        active_sittings = _count(attempt_model, attempt_domain + [("state", "=", "in_progress")])
        disqualified_sittings = _count(attempt_model, attempt_domain + [("state", "=", "disqualified")])
        
        passed_sittings = _count(attempt_model, attempt_domain + [("state", "=", "completed"), ("is_passed", "=", True)])
        failed_sittings = _count(attempt_model, attempt_domain + [("state", "=", "completed"), ("is_passed", "=", False)])

        pending_grading_tasks = _count(grading_task_model, grading_task_domain + [("state", "=", "pending")])
        overdue_grading_tasks = _count(grading_task_model, grading_task_domain + [("state", "=", "pending"), ("is_overdue", "=", True)])
        my_grading_tasks = _count(grading_task_model, grading_task_domain + [("assigned_grader_id", "=", uid), ("state", "=", "pending")])

        # ── 4. CBIS Interview KPIs ──────────────────────────────────────────
        total_interview_sessions = _count(cbis_session_model, cbis_session_domain) + _count(interview_session_model, cbis_session_domain)
        total_scheduled_candidates = _count(cbis_candidate_model, cbis_session_domain) + _count(interview_candidate_model, cbis_session_domain)

        total_evaluations_submitted = 0
        total_evaluations_pending = 0
        my_pending_evaluations = 0

        # Primary: CBIS interviewer evaluation model
        if cbis_eval_model is not None:
            total_evaluations_submitted += _count(cbis_eval_model, cbis_eval_domain + [("state", "=", "submitted")])
            total_evaluations_pending += _count(cbis_eval_model, cbis_eval_domain + [("state", "=", "draft")])
            my_pending_evaluations += _count(cbis_eval_model, [("interviewer_user_id", "=", uid), ("state", "=", "draft")])
        elif interview_eval_model is not None:
            total_evaluations_submitted += _count(interview_eval_model, cbis_eval_domain + [("state", "=", "submitted")])
            total_evaluations_pending += _count(interview_eval_model, cbis_eval_domain + [("state", "in", ["draft", "pending"])])
            emp_id = user.employee_id.id if user.employee_id else False
            my_domain = [("state", "in", ["draft", "pending"])]
            if emp_id:
                my_domain.append(("assessor_name", "=", emp_id))
            else:
                my_domain.append(("create_uid", "=", uid))
            my_pending_evaluations += _count(interview_eval_model, my_domain)

        # ── 5. Transfer Assessment KPIs ─────────────────────────────────────
        total_transfers = _count(transfer_model, transfer_domain)
        approved_transfers = _count(transfer_model, transfer_domain + [("state", "=", "approved")])
        pending_transfers = _count(transfer_model, transfer_domain + [("state", "in", ["draft", "submitted", "under_review"])])
        total_publications = _count(pub_model, pub_domain)

        # ── 6. Action Queues ────────────────────────────────────────────────
        my_action_evals = []
        if cbis_eval_model is not None:
            ev_domain = [("interviewer_user_id", "=", uid), ("state", "=", "draft")]
            for ev in cbis_eval_model.sudo().search(ev_domain, limit=5):
                my_action_evals.append({
                    "id": ev.id,
                    "candidate_code": ev.candidate_code or f"INT-{ev.id:04d}",
                    "candidate_name": ev.candidate_name or _("Candidate"),
                    "job_title": ev.job_id.name if ev.job_id else "—",
                    "session_name": ev.session_id.name if ev.session_id else "—",
                })
        elif interview_eval_model is not None:
            emp_id = user.employee_id.id if user.employee_id else False
            ev_domain = [("state", "in", ["draft", "pending"])]
            if emp_id:
                ev_domain.append(("assessor_name", "=", emp_id))
            else:
                ev_domain.append(("create_uid", "=", uid))
            for ev in interview_eval_model.sudo().search(ev_domain, limit=5):
                my_action_evals.append({
                    "id": ev.id,
                    "candidate_code": getattr(ev, "code", False) or getattr(ev, "reference", False) or f"INT-{ev.id:04d}",
                    "candidate_name": ev.candidate_assessment_id.candidate_name if getattr(ev, "candidate_assessment_id", False) else (ev.applicant_name.name if getattr(ev, "applicant_name", False) else "Candidate"),
                    "job_title": ev.job_id.name if getattr(ev, "job_id", False) else "—",
                    "session_name": ev.interview_session_id.name if getattr(ev, "interview_session_id", False) else "—",
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
