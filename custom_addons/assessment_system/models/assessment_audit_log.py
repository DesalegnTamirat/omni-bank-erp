# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class AssessmentAuditLog(models.Model):
    """
    ==========================================================
    Append-only, read-only audit log for all critical assessment operations:
    score overrides, disqualifications, appeal reversals, and result withdrawals.
    """
    _name = "assessment.audit.log"
    _description = "Assessment Management Immutable Audit Log"
    _order = "timestamp desc, id desc"
    _rec_name = "event_type"

    timestamp = fields.Datetime(string="Timestamp", default=fields.Datetime.now, required=True, readonly=True, index=True)
    user_id = fields.Many2one("res.users", string="Acting User", default=lambda self: self.env.user, required=True, readonly=True, index=True)
    
    event_type = fields.Selection([
        ("score_override", "Score Manual Override (FR-EXM-035)"),
        ("disqualification", "Automated Anti-Cheat Disqualification (FR-EXM-039)"),
        ("appeal_reversal", "Appeal Disqualification Reversal (FR-EXM-041)"),
        ("evaluation_locked", "Interview Evaluation Auto-Locked (FR-CBIS-021)"),
        ("publication_issued", "Assessment Results Published (FR-EXM-068)"),
        ("publication_withdrawal", "Result Publication Withdrawn (FR-EXM-070)"),
        ("question_approved", "Question Bank Approval (FR-EXM-006)"),
    ], string="Audit Event Type", required=True, readonly=True, index=True)

    model_name = fields.Char(string="Target Model", readonly=True)
    res_id = fields.Integer(string="Record ID", readonly=True)
    description = fields.Text(string="Audit Details & Justification", required=True, readonly=True)
    ip_address = fields.Char(string="IP Address / Host", readonly=True)

    @api.model
    def log_event(self, event_type, model_name, res_id, description, user_id=None):
        """Helper method to append an immutable audit record"""
        vals = {
            "timestamp": fields.Datetime.now(),
            "user_id": user_id or self.env.user.id,
            "event_type": event_type,
            "model_name": model_name,
            "res_id": res_id,
            "description": description,
        }
        return self.sudo().create(vals)

    def unlink(self):
        """Enforce strict immutability: audit logs can never be deleted"""
        raise models.UserError(_("Security Violation: Audit log records are permanent and cannot be deleted."))

    def write(self, vals):
        """Enforce strict immutability: audit logs can never be modified in-place"""
        raise models.UserError(_("Security Violation: Audit log records are immutable and cannot be edited."))
