# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)
OFFER_RESPONSE_DAYS = 3  # Number of days before offer expires (72 hours)


class RecruitmentOfferLetter(models.Model):
    """
    Extends recruitment.offer.letter for External Recruitment Offer Management:
    - Filter vacancy_id for External Vacancies only.
    - Dynamically filter selected candidates for the chosen vacancy reference.
    - Exclude candidates who already have an active offer letter.
    - Automatically escalate / promote the top Reserve Candidate if an offer is declined or expires after 3 days.
    """
    _inherit = 'recruitment.offer.letter'

    vacancy_id = fields.Many2one(
        'job.vacancy', string='Vacancy Reference', required=True, tracking=True,
        domain="[('reference', 'ilike', 'EXT')]"
    )
    vacancy_reference = fields.Char(
        related='vacancy_id.reference', string='Vacancy Reference String', store=True
    )
    
    ext_candidate_id = fields.Many2one(
        'external.recruitment.selected.candidates',
        string='Candidate Name',
        required=True,
        tracking=True,
        domain="[('selection_type', 'in', ['selected', 'Selected'])]",
        help="Selected candidate from external recruitment whose Result is Selected."
    )

    applicant_id = fields.Many2one(
        'hr.applicant', string='Applicant (External)'
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee (Internal)'
    )

    candidate_email = fields.Char(string="Candidate Email")
    job_position_name = fields.Char(string="Job Position")

    expiry_date = fields.Date(
        string='Offer Expiry Date',
        compute='_compute_expiry_date', store=True, readonly=False
    )
    rejection_reason = fields.Text(string='Rejection / Decline Reason')
    notes = fields.Text(string='Internal Notes')

    @api.depends('offer_date')
    def _compute_expiry_date(self):
        for rec in self:
            if rec.offer_date:
                rec.expiry_date = rec.offer_date + timedelta(days=OFFER_RESPONSE_DAYS)
            else:
                rec.expiry_date = False

    @api.onchange('vacancy_id')
    def _onchange_vacancy_id_filter_candidates(self):
        """
        BRD Offer Letter Requirement:
        1. Fetch candidates from external.recruitment.selected.candidates for the selected vacancy ONLY.
        2. Filter candidates whose Result is SELECTED ONLY ('selection_type in [selected, Selected]').
        3. Exclude candidates who ALREADY have an active offer letter created.
        """
        if not self.vacancy_id:
            self.ext_candidate_id = False
            return {'domain': {'ext_candidate_id': [('selection_type', 'in', ['selected', 'Selected'])]}}

        vac_ref = self.vacancy_id.reference
        
        # 1. Search parent external.recruitment.selected records for this vacancy reference
        sel_records = self.env['external.recruitment.selected'].search([
            '|', ('vacancy_reference', '=', vac_ref), ('vacancy_id', '=', self.vacancy_id.id)
        ])
        
        # 2. Search ONLY candidates for this specific vacancy where selection_type is 'selected' / 'Selected'
        selected_candidates = self.env['external.recruitment.selected.candidates'].search([
            ('ext_rec_sel_cand', 'in', sel_records.ids),
            ('selection_type', 'in', ['selected', 'Selected'])
        ])

        # 3. Exclude candidates who already have an active offer letter
        existing_offers = self.search([
            ('vacancy_id', '=', self.vacancy_id.id),
            ('state', 'not in', ['declined', 'expired'])
        ])
        offered_candidate_ids = existing_offers.mapped('ext_candidate_id').ids

        remaining_candidates = selected_candidates.filtered(lambda c: c.id not in offered_candidate_ids)

        self.ext_candidate_id = False
        return {
            'domain': {
                'ext_candidate_id': [('id', 'in', remaining_candidates.ids)]
            }
        }

    @api.onchange('ext_candidate_id')
    def _onchange_ext_candidate_id(self):
        """Auto-populate applicant details from selected external candidate record."""
        if self.ext_candidate_id:
            cand = self.ext_candidate_id
            self.applicant_id = cand.applicant_name.id if cand.applicant_name else False
            self.candidate_email = cand.applicant_email
            if cand.ext_rec_sel_cand and cand.ext_rec_sel_cand.job_position:
                self.job_position_name = cand.ext_rec_sel_cand.job_position.name
            elif self.vacancy_id and self.vacancy_id.job_position:
                self.job_position_name = self.vacancy_id.job_position.name

    def action_send(self):
        """Send offer letter to candidate and set 3-day response deadline."""
        for rec in self:
            rec.write({'state': 'sent'})
            if not rec.offer_date:
                rec.offer_date = fields.Date.today()
            rec.expiry_date = rec.offer_date + timedelta(days=OFFER_RESPONSE_DAYS)
            
            # Send notification email if email exists
            email_target = rec.candidate_email or (rec.applicant_id.email_from if rec.applicant_id else False)
            if email_target:
                pos_str = rec.job_position_name or (rec.vacancy_id.job_position.name if rec.vacancy_id and rec.vacancy_id.job_position else 'Position')
                message_body = _(
                    "Dear Candidate,<br><br>"
                    "We are pleased to extend a formal Offer Letter for the position of <b>%s</b> at Bunna Bank S.C.<br>"
                    "Please review and respond within <b>3 calendar days</b> (Expiry Date: <b>%s</b>).<br><br>"
                    "Best Regards,<br>HR Recruitment Team, Bunna Bank S.C."
                ) % (pos_str, rec.expiry_date)
                
                try:
                    mail_values = {
                        'subject': _("Job Offer Letter - %s - Bunna Bank S.C.") % pos_str,
                        'body_html': message_body,
                        'email_to': email_target,
                    }
                    self.env['mail.mail'].sudo().create(mail_values).send()
                except Exception as ex:
                    _logger.warning("Failed to dispatch offer letter email: %s", ex)

            rec.message_post(body=_("Offer Letter sent to candidate %s. Expiry Date: %s.") % (
                rec.ext_candidate_id.emp_name if rec.ext_candidate_id else (rec.applicant_id.partner_name if rec.applicant_id else 'Candidate'),
                rec.expiry_date
            ))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Offer Sent'),
                'message': _('Offer letter dispatched. Candidate has 3 days to respond.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_accept(self):
        """Candidate accepts offer."""
        for rec in self:
            rec.write({'state': 'accepted', 'response_date': fields.Date.today()})
            rec.message_post(body=_("Offer Letter successfully ACCEPTED by candidate."))
            if rec.ext_candidate_id:
                rec.ext_candidate_id.remarks = _("Offer Accepted on %s") % fields.Date.today()

    def action_decline(self):
        """Candidate declines offer — open popup wizard to require decline reason if not filled."""
        self.ensure_one()
        if not self.rejection_reason:
            return {
                'name': _('Reason for Declining Offer'),
                'type': 'ir.actions.act_window',
                'res_model': 'recruitment.offer.decline.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_offer_letter_id': self.id,
                }
            }
        
        self.write({'state': 'declined', 'response_date': fields.Date.today()})
        if self.ext_candidate_id:
            self.ext_candidate_id.write({
                'selection_type': 'rejected',
                'remarks': _("%s") % self.rejection_reason
            })
        
        self.message_post(body=_("Offer Letter DECLINED by candidate (%s). Escalating to Reserve Pool...") % self.rejection_reason)
        self._cascade_to_next_reserve_candidate()

    def _cascade_to_next_reserve_candidate(self):
        """
        Auto-Escalation Engine (3-Day Expiry / Decline Rule):
        Finds the top-ranked Reserve Candidate ('reserved') for this vacancy,
        automatically promotes them to 'selected', updates their remarks, and
        dispatches notification to HR to create their offer letter.
        """
        self.ensure_one()
        if not self.vacancy_id:
            return

        vac_ref = self.vacancy_id.reference
        
        # Search candidate roster for this vacancy
        sel_records = self.env['external.recruitment.selected'].search([
            '|', ('vacancy_reference', '=', vac_ref), ('vacancy_id', '=', self.vacancy_id.id)
        ])

        if not sel_records:
            return

        # Find reserve candidates sorted by weighted score desc
        reserve_candidates = self.env['external.recruitment.selected.candidates'].search([
            ('ext_rec_sel_cand', 'in', sel_records.ids),
            ('selection_type', 'in', ['reserved', 'Reserve', 'Reserved'])
        ], order='weighted_score desc')

        if reserve_candidates:
            top_reserve = reserve_candidates[0]
            top_reserve.write({
                'selection_type': 'selected',
                'remarks': _("Automatically promoted from Reserve Pool on %s .") % fields.Date.today()
            })
            
            msg = _(
                "<b>AUTO-PROMOTION ALERT:</b><br>"
                "Candidate <b>%s</b> has been automatically promoted from the Reserve Pool "
                "to <b>SELECTED</b> status for vacancy <b>%s</b> due to decline/expiry of the previous candidate.<br>"
                "Weighted Score: <b>%.2f%%</b>"
            ) % (
                top_reserve.applicant_name.partner_name if top_reserve.applicant_name else (top_reserve.emp_name or 'Reserve Candidate'),
                vac_ref,
                top_reserve.weighted_score or 0.0
            )

            # Log on selection process and offer letter chatter
            if hasattr(self.vacancy_id, 'message_post'):
                self.vacancy_id.message_post(body=msg)
            for s in sel_records:
                if hasattr(s, 'message_post'):
                    s.message_post(body=msg)
                
            # Create a draft offer letter for the newly promoted reserve candidate
            new_offer = self.create({
                'vacancy_id': self.vacancy_id.id,
                'ext_candidate_id': top_reserve.id,
                'applicant_id': top_reserve.applicant_name.id if top_reserve.applicant_name else False,
                'candidate_email': top_reserve.applicant_email,
                'notes': _("Auto-created for promoted reserve candidate %s.") % (top_reserve.emp_name or 'Candidate')
            })
            new_offer.message_post(body=_("Draft offer letter automatically created following reserve candidate promotion."))
        else:
            msg = _("No more reserve candidates available in the pool for vacancy %s.") % vac_ref
            if hasattr(self.vacancy_id, 'message_post'):
                self.vacancy_id.message_post(body=msg)
            self.message_post(body=msg)

    @api.model
    def _cron_expire_pending_offers(self):
        """
        Automated Cron Task (Runs Daily):
        Expires offers that have exceeded the 3-day response window without candidate response,
        and automatically escalates/promotes the top Reserve Candidate!
        """
        today = fields.Date.today()
        expired_offers = self.search([
            ('state', '=', 'sent'),
            ('expiry_date', '<', today)
        ])
        for rec in expired_offers:
            rec.write({
                'state': 'expired',
                'rejection_reason': _("Auto-expired: Candidate failed to respond within 3-day deadline (%s).") % rec.expiry_date
            })
            if rec.ext_candidate_id:
                rec.ext_candidate_id.write({
                    'selection_type': 'rejected',
                    'remarks': _("Offer Expired (3-day deadline exceeded)")
                })
            rec.message_post(body=_("Offer Letter EXPIRED (3 days elapsed without response). Escalating to Reserve Pool..."))
            rec._cascade_to_next_reserve_candidate()


class RecruitmentOfferDeclineWizard(models.TransientModel):
    _name = 'recruitment.offer.decline.wizard'
    _description = 'Decline Offer Letter Wizard'

    offer_letter_id = fields.Many2one('recruitment.offer.letter', string='Offer Letter', required=True)
    reason = fields.Text(string='Reason for Declining', required=True)

    def action_confirm_decline(self):
        self.ensure_one()
        offer = self.offer_letter_id
        offer.rejection_reason = self.reason
        offer.write({'state': 'declined', 'response_date': fields.Date.today()})
        
        if offer.ext_candidate_id:
            offer.ext_candidate_id.write({
                'selection_type': 'rejected',
                'remarks': _("Declined Offer Letter: %s") % self.reason
            })
        
        offer.message_post(body=_("Offer Letter DECLINED by candidate (%s). Escalating to Reserve Pool...") % self.reason)
        offer._cascade_to_next_reserve_candidate()
        return {'type': 'ir.actions.act_window_close'}
