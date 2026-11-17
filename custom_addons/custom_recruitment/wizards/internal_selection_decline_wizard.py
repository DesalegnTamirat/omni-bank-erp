# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class InternalSelectionDeclineWizard(models.TransientModel):
    """
    Interactive Wizard for responding to candidate selection (Accept or Decline)
    for Internal Promotions and Lateral Transfers.
    """
    _name = 'internal.selection.decline.wizard'
    _description = 'Promotion or Transfer Offer Response Wizard'

    candidate_id = fields.Many2one(
        'new.internal.recruitment.selected.candidates',
        string='Selected Candidate'
    )
    transfer_request_id = fields.Many2one(
        'employee.transfer.request',
        string='Transfer Request'
    )
    transfer_letter_id = fields.Many2one(
        'transfer.letter',
        string='Transfer Letter'
    )

    response_action = fields.Selection([
        ('accept', 'Accept Transfer Offer / ዝውውሩን እቀበላለሁ'),
        ('decline', 'Decline / Refuse Transfer Offer / ዝውውሩን አልቀበልም'),
    ], string='Your Decision / ውሳኔዎ', default='accept', required=True)

    employee_name = fields.Char(string='Employee Name', compute='_compute_offer_details')
    current_operating_unit_name = fields.Char(string='Current Work Unit', compute='_compute_offer_details')
    target_operating_unit_name = fields.Char(string='Target Work Unit / Branch', compute='_compute_offer_details')
    target_job_position_name = fields.Char(string='Target Job Position', compute='_compute_offer_details')
    current_job_grade_name = fields.Char(string='Job Grade', compute='_compute_offer_details')

    rejection_reason = fields.Text(
        string='Reason for Declining / ውድቅ የማድረጊያ ምክንያት',
        help='State the specific reason why the offer is being declined.'
    )

    @api.depends('transfer_request_id', 'transfer_letter_id', 'candidate_id')
    def _compute_offer_details(self):
        for rec in self:
            if rec.transfer_request_id:
                req = rec.transfer_request_id.sudo()
                rec.employee_name = req.employee_name or (req.employee_id.name if req.employee_id else "")
                rec.current_operating_unit_name = req.current_operating_unit_id.name if req.current_operating_unit_id else ""
                rec.target_operating_unit_name = (
                    (req.requested_operating_unit_id.name if req.requested_operating_unit_id else "")
                    or (req.target_operating_unit_id.name if req.target_operating_unit_id else "")
                )
                rec.target_job_position_name = req.target_job_position_id.name if req.target_job_position_id else ""

                grade_name = ""
                try:
                    if req.id:
                        self.env.cr.execute("""
                            SELECT COALESCE(eg.grade_name, eg.grade_code, '')
                            FROM employee_transfer_request tr
                            JOIN employee_grade eg ON eg.id = tr.current_job_grade_id
                            WHERE tr.id = %s
                        """, (req.id,))
                        row = self.env.cr.fetchone()
                        if row and row[0]:
                            grade_name = row[0]
                except Exception:
                    pass
                if not grade_name:
                    try:
                        g = req.current_job_grade_id
                        grade_name = getattr(g, 'grade_name', '') or getattr(g, 'grade_code', '') or ""
                    except Exception:
                        grade_name = ""
                rec.current_job_grade_name = grade_name
            elif rec.transfer_letter_id:
                let = rec.transfer_letter_id.sudo()
                rec.employee_name = let.employee_name
                rec.current_operating_unit_name = let.current_work_unit_name
                rec.target_operating_unit_name = let.new_work_unit_name
                rec.target_job_position_name = let.new_position_name
                rec.current_job_grade_name = let.job_grade_name or ""
            elif rec.candidate_id:
                cand = rec.candidate_id.sudo()
                rec.employee_name = cand.employee_id.name if cand.employee_id else ""
                rec.current_operating_unit_name = ""
                rec.target_operating_unit_name = ""
                rec.target_job_position_name = ""
                rec.current_job_grade_name = ""
            else:
                rec.employee_name = ""
                rec.current_operating_unit_name = ""
                rec.target_operating_unit_name = ""
                rec.target_job_position_name = ""
                rec.current_job_grade_name = ""

    def action_confirm_response(self):
        """Processes candidate response (Accept or Decline)."""
        self.ensure_one()
        if self.response_action == 'accept':
            if self.transfer_request_id:
                return self.transfer_request_id.sudo().with_context(skip_transfer_write_check=True).action_accept_transfer()
            elif self.transfer_letter_id:
                return self.transfer_letter_id.sudo().action_accept_transfer()
            elif self.candidate_id and hasattr(self.candidate_id, 'action_accept_selection'):
                return self.candidate_id.sudo().action_accept_selection()
            return {'type': 'ir.actions.act_window_close'}
        else:
            if not self.rejection_reason or not self.rejection_reason.strip():
                raise UserError(_("Please provide a reason for declining the offer."))
            return self.action_confirm_decline()

    def action_confirm_decline(self):
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise UserError(_("Please provide a reason for declining the offer."))

        reason = self.rejection_reason.strip()

        if self.candidate_id:
            self.candidate_id._check_current_user_is_candidate()
            self.candidate_id.sudo().with_context(skip_candidate_check=True).confirm_decline_promotion(reason)
        elif self.transfer_request_id:
            self.transfer_request_id.sudo().with_context(skip_transfer_write_check=True).confirm_decline_transfer(reason)
        elif self.transfer_letter_id:
            self.transfer_letter_id.sudo().confirm_decline_transfer(reason)
        else:
            raise UserError(_("No candidate or transfer record associated with this wizard."))

        return {'type': 'ir.actions.act_window_close'}
