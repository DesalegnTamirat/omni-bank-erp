# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

OFFER_RESPONSE_DAYS = 3  # Number of days before offer expires


class RecruitmentOfferLetter(models.Model):
    """
    Extends the offer letter model defined in recruitment_scoring.py with:
    - applicant_id / employee_id links
    - expiry_date compute
    - rejection_reason / notes fields
    - action_send / action_accept / action_decline workflow buttons
    """
    _inherit = 'recruitment.offer.letter'

    # ── Extra relational links ────────────────────────────────────────────────
    applicant_id = fields.Many2one(
        'hr.applicant', string='Applicant (External)'
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee (Internal)'
    )

    # ── Expiry tracking (parallel to response_deadline in scoring.py) ─────────
    expiry_date = fields.Date(
        string='Offer Expiry Date',
        compute='_compute_expiry_date', store=True, readonly=False
    )

    rejection_reason = fields.Text(string='Rejection / Decline Reason')
    notes = fields.Text(string='Internal Notes')

    # ── Computed fields ──────────────────────────────────────────────────────
    @api.depends('offer_date')
    def _compute_expiry_date(self):
        for rec in self:
            if rec.offer_date:
                rec.expiry_date = rec.offer_date + timedelta(days=OFFER_RESPONSE_DAYS)
            else:
                rec.expiry_date = False

    # ── Workflow buttons ─────────────────────────────────────────────────────
    def action_send(self):
        self.write({'state': 'sent'})

    def action_accept(self):
        self.write({'state': 'accepted', 'response_date': fields.Date.today()})

    def action_decline(self):
        if not self.rejection_reason:
            raise ValidationError(_("Please provide a reason for declining the offer."))
        self.write({'state': 'declined', 'response_date': fields.Date.today()})
