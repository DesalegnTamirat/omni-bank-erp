# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class TalentRoster(models.Model):
    _name = 'talent.roster'
    _inherit = ['mail.thread']
    _description = 'Talent Roster Management'
    _order = 'final_score desc, date_added desc'

    name = fields.Char(string='Candidate Name', required=True, tracking=True)
    applicant_id = fields.Many2one('hr.applicant', string='Original Applicant', ondelete='set null')
    employee_id = fields.Many2one('hr.employee', string='Employee (Internal)', ondelete='set null')
    eligible_candidate_id = fields.Many2one('external.recruitment.eligible.employees', string='Eligible Candidate Record', ondelete='set null')
    candidate_score_id = fields.Many2one('recruitment.candidate.score', string='Source Candidate Score Record', ondelete='set null')
    source_vacancy_id = fields.Many2one('job.vacancy', string='Source Vacancy', tracking=True)
    
    application_type = fields.Selection([
        ('Internal', 'Internal'),
        ('External', 'External'),
    ], string='Application Type', default='External', required=True)

    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender')

    educational_qualification = fields.Char(string='Qualification')
    field_of_study = fields.Char(string='Field of Study')
    highest_cgpa = fields.Float(string='CGPA / GPA', digits=(4, 2))
    total_experience = fields.Float(string='Total Experience (Years)', digits=(4, 1))
    banking_experience = fields.Float(string='Banking Experience (Years)', digits=(4, 1))
    skills_summary = fields.Text(string='Skills / Competencies Summary')

    written_score = fields.Float(string='Written Exam Score', digits=(5, 2))
    interview_score = fields.Float(string='Interview Score', digits=(5, 2))
    pms_score = fields.Float(string='PMS Score', digits=(5, 2))
    final_score = fields.Float(string='Final Score', digits=(5, 2))
    previous_rank = fields.Integer(string='Previous Vacancy Rank')

    date_added = fields.Date(string='Date Added', default=fields.Date.context_today, required=True)
    expiry_date = fields.Date(string='Reserve Expiry Date', compute='_compute_expiry_date', store=True, readonly=False)
    
    status = fields.Selection([
        ('active', 'Active (Available)'),
        ('reused', 'Reused / Re-linked'),
        ('expired', 'Expired'),
    ], string='Roster Status', default='active', tracking=True)

    notes = fields.Text(string='HR Notes & Evaluation Summary')
    cv_attachment_id = fields.Many2one('ir.attachment', string='CV / Resume Attachment', compute='_compute_cv_attachment_id', store=False)
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.depends('date_added')
    def _compute_expiry_date(self):
        for rec in self:
            if rec.date_added:
                rec.expiry_date = rec.date_added + timedelta(days=180)  # 6 Months Expiry
            else:
                rec.expiry_date = fields.Date.today() + timedelta(days=180)

    def _compute_cv_attachment_id(self):
        for rec in self:
            att = False
            if rec.applicant_id:
                att = self.env['ir.attachment'].search([
                    ('res_model', '=', 'hr.applicant'),
                    ('res_id', '=', rec.applicant_id.id)
                ], limit=1, order='id desc')
            if not att and rec.eligible_candidate_id:
                att = self.env['ir.attachment'].search([
                    ('res_model', '=', 'external.recruitment.eligible.employees'),
                    ('res_id', '=', rec.eligible_candidate_id.id)
                ], limit=1, order='id desc')
            rec.cv_attachment_id = att.id if att else False

    def action_download_cv(self):
        self.ensure_one()
        if not self.cv_attachment_id:
            raise ValidationError(_("No CV attachment found for candidate %s.") % self.name)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.cv_attachment_id.id}?download=true',
            'target': 'new',
        }

    def action_open_link_wizard(self):
        self.ensure_one()
        return {
            'name': _('Link Candidate to New Vacancy'),
            'type': 'ir.actions.act_window',
            'res_model': 'talent.roster.link.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_roster_id': self.id,
            }
        }

    @api.model
    def _cron_expire_talent_roster(self):
        """Automatically expire reserve status after 6 Months (180 Days)."""
        today = fields.Date.today()
        expired_records = self.search([
            ('status', '=', 'active'),
            ('expiry_date', '<', today),
        ])
        expired_records.write({'status': 'expired'})
        for rec in expired_records:
            rec.message_post(body=_("Talent Roster entry automatically expired after 6 months."))

    @api.model
    def action_sync_external_candidates(self):
        """Sync / import eligible external applicants into Talent Roster."""
        Eligible = self.env['external.recruitment.eligible.employees'].sudo()
        candidates = Eligible.search([])
        imported_count = 0

        for cand in candidates:
            # Check if already in Talent Roster
            domain = [('eligible_candidate_id', '=', cand.id)]
            if cand.applicant_email:
                domain = ['|', ('eligible_candidate_id', '=', cand.id), ('email', '=ilike', cand.applicant_email)]
            existing = self.search(domain, limit=1)
            if existing:
                continue

            name = (
                cand.applicant_name.partner_name or
                cand.applicant_name.display_name if cand.applicant_name else
                cand.applicant_email or _("External Candidate")
            )
            
            vacancy_id = cand.external_recruitment_id.vacancy_id.id if cand.external_recruitment_id and cand.external_recruitment_id.vacancy_id else False

            qual_val = cand.educational_qualification
            if qual_val and hasattr(cand._fields['educational_qualification'], 'selection'):
                qual_dict = dict(cand._fields['educational_qualification'].selection or [])
                qual_val = qual_dict.get(qual_val, qual_val)

            self.create({
                'name': name,
                'applicant_id': cand.applicant_name.id if cand.applicant_name else False,
                'eligible_candidate_id': cand.id,
                'source_vacancy_id': vacancy_id,
                'application_type': 'External',
                'email': cand.applicant_email,
                'phone': cand.applicant_phone,
                'gender': cand.gender,
                'educational_qualification': qual_val,
                'field_of_study': cand.field_of_study,
                'highest_cgpa': cand.highest_cgpa,
                'total_experience': cand.total_experience,
                'banking_experience': cand.banking_experience,
                'status': 'active',
                'notes': _("Imported from External Recruitment Eligible Candidates (Vacancy Ref: %s)") % (
                    cand.external_recruitment_id.vacancy_reference or 'N/A'
                ),
            })
            imported_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Candidates Imported'),
                'message': _('%d external candidate(s) imported into Talent Roster.') % imported_count,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

