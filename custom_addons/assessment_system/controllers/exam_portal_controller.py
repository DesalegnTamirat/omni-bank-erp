# -*- coding: utf-8 -*-

import json
from datetime import datetime
from odoo import http, fields, _
from odoo.http import request


class ExamPortalController(http.Controller):
    """
    Secure Online Exam Delivery & Proctoring Engine (FR-EXM-018 - FR-EXM-028)
    ========================================================================
    Renders clean, distraction-free candidate assessment UI outside backend chrome,
    handles client-server timer synchronization, auto-save (every 30s), anti-cheat
    event logging, and automated submission.
    """

    @http.route("/exam/session/<string:token>", type="http", auth="public", website=True, sitemap=False)
    def render_exam_session(self, token, **kwargs):
        attempt = request.env["exam.candidate.attempt"].sudo().search([
            ("access_token", "=", token)
        ], limit=1)

        if not attempt:
            return request.render("assessment_system.exam_error_page", {
                "error_title": _("Invalid Access Link"),
                "error_message": _("This assessment access link is invalid or does not exist. Please contact Bunna Bank HR."),
            })

        # Check session state
        session = attempt.session_id
        now = fields.Datetime.now()

        if attempt.state == "completed":
            return request.render("assessment_system.exam_completed_page", {
                "attempt": attempt,
                "message": _("Your examination has already been successfully submitted. Thank you."),
            })
        elif attempt.state == "disqualified":
            return request.render("assessment_system.exam_disqualified_page", {
                "attempt": attempt,
                "reason": attempt.disqualification_reason or _("Anti-cheating violation threshold exceeded."),
            })

        # Check if exam window is active or not yet started
        if (session.start_datetime and now < session.start_datetime) or session.state in ["draft", "scheduled"]:
            start_iso = session.start_datetime.isoformat() if session.start_datetime else ""
            now_iso = now.isoformat()
            return request.render("assessment_system.exam_waiting_page", {
                "attempt": attempt,
                "session": session,
                "exam": attempt.exam_id,
                "start_time_iso": start_iso,
                "server_time_iso": now_iso,
                "duration_minutes": session.duration_minutes or (attempt.exam_id.duration_minutes if attempt.exam_id else 60),
                "message": _("This examination session has not started yet. It is scheduled to start on %s.") % (session.start_datetime or "Soon"),
            })
        elif session.end_datetime and now > session.end_datetime and attempt.state not in ["in_progress", "completed"]:
            return request.render("assessment_system.exam_error_page", {
                "error_title": _("Exam Window Closed"),
                "error_message": _("The scheduled time window for this examination has closed."),
            })

        # Auto-initialize questions if not yet populated
        if not attempt.answer_ids:
            attempt._initialize_candidate_questions()

        # If candidate state is assigned/invited, activate exam attempt directly
        if attempt.state in ["assigned", "invited"]:
            attempt.write({
                "state": "in_progress",
                "start_datetime": now,
                "login_datetime": attempt.login_datetime or now,
            })

        # Render active exam interface
        return request.render("assessment_system.exam_portal_interface", {
            "attempt": attempt,
            "session": session,
            "exam": attempt.exam_id,
            "answers": attempt.answer_ids.sorted(key=lambda a: a.sequence),
        })

    @http.route("/exam/session/<string:token>/start", type="jsonrpc", auth="public", methods=["POST"])
    def start_exam(self, token, **kwargs):
        attempt = request.env["exam.candidate.attempt"].sudo().search([("access_token", "=", token)], limit=1)
        if not attempt:
            return {"status": "error", "message": "Invalid token"}
        try:
            attempt.action_start_exam()
            return {"status": "success", "start_datetime": str(attempt.start_datetime)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @http.route("/exam/session/<string:token>/save", type="jsonrpc", auth="public", methods=["POST"])
    def auto_save_answers(self, token, **kwargs):
        """Auto-save endpoint called every 30s and before final submission (FR-EXM-027)"""
        attempt = request.env["exam.candidate.attempt"].sudo().search([("access_token", "=", token)], limit=1)
        if not attempt or attempt.state == "completed":
            return {"status": "error", "message": "Attempt not active or already completed"}

        answers_payload = kwargs.get("answers", [])
        for ans_data in answers_payload:
            ans_id = ans_data.get("answer_id")
            answer = attempt.answer_ids.filtered(lambda a: a.id == ans_id)
            if not answer:
                continue

            vals = {"last_saved_datetime": fields.Datetime.now()}
            if "selected_option_id" in ans_data:
                opt_id = ans_data["selected_option_id"]
                vals["selected_option_id"] = int(opt_id) if opt_id else False
            if "selected_option_ids" in ans_data:
                vals["selected_option_ids"] = [(6, 0, ans_data["selected_option_ids"] or [])]
            if "text_answer" in ans_data:
                vals["text_answer"] = ans_data["text_answer"] or ""
            if "is_marked_for_review" in ans_data:
                vals["is_marked_for_review"] = bool(ans_data["is_marked_for_review"])

            answer.write(vals)

        return {"status": "saved", "saved_at": str(fields.Datetime.now())}

    @http.route("/exam/session/<string:token>/event", type="jsonrpc", auth="public", methods=["POST"])
    def record_proctor_event(self, token, **kwargs):
        """Receives anti-cheating violation signals from client agent (FR-EXM-021 - FR-EXM-023)"""
        attempt = request.env["exam.candidate.attempt"].sudo().search([("access_token", "=", token)], limit=1)
        if not attempt or attempt.state == "completed":
            return {"status": "ignored"}

        event_type = kwargs.get("event_type", "tab_switch")
        details = kwargs.get("details", "")
        res = attempt.record_proctor_event(event_type, details)
        return res

    @http.route("/exam/session/<string:token>/submit", type="jsonrpc", auth="public", methods=["POST"])
    def submit_exam(self, token, **kwargs):
        """Final submission triggered by candidate or timer auto-submit (FR-EXM-024)"""
        attempt = request.env["exam.candidate.attempt"].sudo().search([("access_token", "=", token)], limit=1)
        if not attempt:
            return {"status": "error", "message": "Invalid token"}

        # Save final answers payload first
        answers_payload = kwargs.get("answers", [])
        if answers_payload:
            self.auto_save_answers(token, answers=answers_payload)

        # Execute automated grading & status update
        attempt.action_submit_exam()
        return {
            "status": "submitted",
            "objective_score": attempt.objective_score,
            "total_score": attempt.total_score,
            "score_percentage": attempt.score_percentage,
            "is_passed": attempt.is_passed,
        }
