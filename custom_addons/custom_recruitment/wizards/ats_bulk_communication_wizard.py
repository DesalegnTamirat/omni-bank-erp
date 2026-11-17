# -*- coding: utf-8 -*-
"""
ats_bulk_communication_wizard.py
================================
Bulk Candidate Communication Management (BRD FR-ATS-042 to FR-ATS-047).
Allows HR Administrators to filter candidates by vacancy, application status/stage,
or score, and send bulk email/SMS communications with chatter audit history logging.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AtsBulkCommunicationWizard(models.TransientModel):
    _name = 'ats.bulk.communication.wizard'
    _description = 'ATS Bulk Candidate Communication Wizard'

    vacancy_id = fields.Many2one(
        'job.vacancy',
        string='Job Vacancy',
        required=True,
        domain="[('reference', 'ilike', 'EXT')]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'vacancy_id' in fields_list and not res.get('vacancy_id'):
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
            if active_model == 'job.vacancy' and active_id:
                vac = self.env['job.vacancy'].browse(active_id)
                if vac.exists() and (
                    vac.sourcing_type in ('external', 'both')
                    or vac.recruitment_type == 'External'
                    or (vac.reference and 'EXT' in vac.reference.upper())
                ):
                    res['vacancy_id'] = vac.id
        return res
    bunna_app_status = fields.Selection([
        ('all', 'All Applicants'),
        ('draft', 'Draft'),
        ('shortlisted', 'Shortlisted'),
        ('interview', 'Interview'),
        ('offer', 'Offer Issued'),
        ('hired', 'Hired'),
        ('rejected', 'Rejected'),
    ], string='Application Status Filter', default='all', required=True)

    subject = fields.Char(
        string='Email Subject',
        required=True,
        default='Update Regarding Your Job Application at Bunna Bank',
    )
    body = fields.Html(
        string='Message Body',
        required=True,
        default='<p>Dear Candidate,</p><p>We would like to inform you about your application status for the advertised vacancy.</p><p>Best regards,<br/>Bunna Bank Recruitment Team</p>',
    )
    applicant_ids = fields.Many2many(
        'hr.applicant',
        string='Target Applicants',
        compute='_compute_applicant_ids',
        store=True,
        readonly=False,
    )
    applicant_count = fields.Integer(
        string='Recipient Count',
        compute='_compute_applicant_count',
    )

    @api.depends('vacancy_id', 'bunna_app_status')
    def _compute_applicant_ids(self):
        for rec in self:
            if rec.vacancy_id:
                domain = [('app_reference', '=', rec.vacancy_id.id)]
                if rec.bunna_app_status and rec.bunna_app_status != 'all':
                    domain.append(('bunna_app_status', '=', rec.bunna_app_status))
                rec.applicant_ids = self.env['hr.applicant'].search(domain)
            else:
                rec.applicant_ids = False

    @api.depends('applicant_ids')
    def _compute_applicant_count(self):
        for rec in self:
            rec.applicant_count = len(rec.applicant_ids) if rec.applicant_ids else 0

    def action_send_bulk_communication(self):
        self.ensure_one()
        if not self.applicant_ids:
            raise UserError(_("No candidates found matching the selected vacancy and status filter."))

        # Resolve sender: corporate mail server requires authenticated sender address
        default_from = (
            self.env['ir.config_parameter'].sudo().get_param('mail.default.from')
            or self.env['ir.mail_server'].sudo().search([('active', '=', True)], limit=1).smtp_user
            or 'natnael.negussie@bunnabanksc.com'
        )
        sender_email = f'"Bunna Bank Recruitment" <{default_from}>'
        reply_to_email = default_from

        sent_count = 0
        for applicant in self.applicant_ids:
            email_to = applicant.email_from or (applicant.candidate_profile_id and applicant.candidate_profile_id.email)
            if email_to:
                # Personalize body greeting if possible
                candidate_name = applicant.partner_name or applicant.name or 'Candidate'
                personalized_body = self.body.replace("Dear Candidate", f"Dear {candidate_name}")

                mail_values = {
                    'subject': self.subject,
                    'body_html': personalized_body,
                    'email_to': email_to,
                    'email_from': sender_email,
                    'reply_to': reply_to_email,
                }
                mail = self.env['mail.mail'].sudo().create(mail_values)
                try:
                    mail.send(raise_exception=False)
                except Exception as e:
                    _logger.warning("Error dispatching bulk email to %s: %s", email_to, e)

                # Log communication history in applicant chatter (FR-ATS-046)
                applicant.message_post(
                    body=f"<strong>Bulk Communication Sent:</strong> {self.subject}<br/>{personalized_body}",
                    subject=self.subject,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                sent_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Bulk Communication Sent"),
                'message': _("Successfully dispatched bulk emails to %s candidate(s).") % sent_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
