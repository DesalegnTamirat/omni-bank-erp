# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TalentRosterLinkWizard(models.TransientModel):
    _name = 'talent.roster.link.wizard'
    _description = 'Link Talent Roster Candidate to New Vacancy'

    roster_id = fields.Many2one('talent.roster', string='Talent Roster Candidate', required=True)
    target_vacancy_id = fields.Many2one(
        'job.vacancy', string='Target Job Vacancy', required=True,
        domain=[('vacancy_status', '=', 'published')]
    )
    notes = fields.Text(string='Re-linking Notes')

    def confirm_link_to_vacancy(self):
        self.ensure_one
        roster = self.roster_id
        vacancy = self.target_vacancy_id

        # 1. Create a new hr.applicant record for target vacancy
        applicant = self.env['hr.applicant'].create({
            'partner_name': roster.name,
            'email_from': roster.email,
            'partner_phone': roster.phone,
            'gender': roster.gender,
            'application_type': roster.application_type,
            'app_reference': vacancy.id,
            'job_id': vacancy.job_position.id if vacancy.job_position else False,
            'bunna_app_status': 'shortlisted',
        })

        # Copy original CV attachment if available
        if roster.cv_attachment_id:
            self.env['ir.attachment'].create({
                'name': roster.cv_attachment_id.name,
                'datas': roster.cv_attachment_id.datas,
                'res_model': 'hr.applicant',
                'res_id': applicant.id,
                'mimetype': roster.cv_attachment_id.mimetype,
            })

        # 2. Create Candidate Score Record for the new recruitment process
        score_vals = {
            'vacancy_id': vacancy.id,
            'applicant_id': applicant.id if roster.application_type == 'External' else False,
            'employee_id': roster.employee_id.id if roster.application_type == 'Internal' else False,
            'gender': roster.gender,
            'selection_status': 'pending',
        }
        score_rec = self.env['recruitment.candidate.score'].create(score_vals)
        applicant.write({'candidate_score_id': score_rec.id})

        # 3. Update Talent Roster record status
        roster.write({
            'status': 'reused',
        })
        roster.message_post(body=_(
            "Candidate re-linked to new vacancy <b>%s</b> (Ref: %s). New Applicant record #%d created."
        ) % (vacancy.job_position.name if vacancy.job_position else vacancy.reference, vacancy.reference, applicant.id))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidate Linked Successfully'),
                'message': _('%s has been linked to vacancy %s without requiring credential creation.') % (roster.name, vacancy.reference),
                'type': 'success',
                'sticky': False,
            }
        }


class TalentRosterTransferWizard(models.TransientModel):
    _name = 'talent.roster.transfer.wizard'
    _description = 'Transfer Candidates to Talent Roster'

    candidate_score_ids = fields.Many2many('recruitment.candidate.score', string='Candidates to Transfer')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids')
        active_model = self.env.context.get('active_model')
        if active_model == 'recruitment.candidate.score' and active_ids:
            res['candidate_score_ids'] = [(6, 0, active_ids)]
        return res

    def action_transfer_candidates(self):
        self.ensure_one
        if not self.candidate_score_ids:
            raise UserError(_("Please select candidates to transfer to Talent Roster."))

        transferred_count = 0
        for score in self.candidate_score_ids:
            if score.disqualified:
                continue  # Restricted as per business rule

            # Check if already transferred
            existing = self.env['talent.roster'].search([
                ('candidate_score_id', '=', score.id),
                ('status', '=', 'active')
            ], limit=1)
            if existing:
                continue

            app = score.applicant_id
            emp = score.employee_id

            name = score.candidate_name or _("Unknown Candidate")
            email = app.email_from if app else (emp.work_email if emp else False)
            phone = app.partner_phone if app else (emp.mobile_phone or emp.work_phone if emp else False)
            app_type = score.recruitment_type.capitalize if score.recruitment_type else 'External'

            self.env['talent.roster'].create({
                'name': name,
                'applicant_id': app.id if app else False,
                'employee_id': emp.id if emp else False,
                'candidate_score_id': score.id,
                'source_vacancy_id': score.vacancy_id.id,
                'application_type': 'Internal' if score.recruitment_type == 'internal' else 'External',
                'email': email,
                'phone': phone,
                'gender': score.gender,
                'written_score': score.written_score,
                'interview_score': score.interview_score,
                'pms_score': score.pms_score,
                'final_score': score.final_score,
                'previous_rank': score.rank,
                'status': 'active',
                'notes': _("Transferred from vacancy %s (Selection Status: %s)") % (
                    score.vacancy_id.reference, score.selection_status
                ),
            })
            transferred_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Complete'),
                'message': _('%d candidate(s) transferred to Talent Roster.') % transferred_count,
                'type': 'success',
                'sticky': False,
            }
        }
