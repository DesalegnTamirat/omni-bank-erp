# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


def _get_or_create_service_award(env, name, award_type):
    """Safely fetch or seed standard service award categories for EDS credentials."""
    AwardModel = env['service.award'].sudo()
    record = AwardModel.search([('award_name', '=', name)], limit=1)
    if not record:
        try:
            with env.cr.savepoint():
                record = AwardModel.create({
                    'award_name': name,
                    'award_type': award_type,
                })
        except Exception:
            _logger.exception("Could not create service.award %s; searching again", name)
            record = AwardModel.search([('award_name', '=', name)], limit=1)
    return record


class HrAwardsEds(models.Model):
    """Extend hr.awards to link directly to EDS credentials and digital documents."""
    _inherit = 'hr.awards'

    eds_certificate_id = fields.Many2one(
        'eds.certificate', string='EDS Issued Certificate',
        index=True, ondelete='set null')
    eds_enrollment_id = fields.Many2one(
        'eds.enrollment', string='EDS Session Enrollment',
        index=True, ondelete='set null')
    eds_trainer_cert_id = fields.Many2one(
        'eds.trainer.certification', string='EDS Trainer Certification',
        index=True, ondelete='set null')
    eds_sponsorship_id = fields.Many2one(
        'eds.sponsorship', string='EDS Sponsorship',
        index=True, ondelete='set null')
    eds_credential_type = fields.Selection([
        ('internal_cert', 'EDS Internal Completion Certificate'),
        ('external_cert', 'EDS External Provider Certificate'),
        ('trainer_cert', 'EDS Certified Trainer (ToT)'),
        ('sponsorship', 'EDS Sponsored Qualification / Degree'),
        ('international', 'EDS International Training Credential'),
    ], string='EDS Credential Type', index=True)
    certificate_attachment_id = fields.Many2one(
        'ir.attachment', string='Certificate Document',
        ondelete='set null')
    certificate_document = fields.Binary(
        related='certificate_attachment_id.datas', string='Certificate File', readonly=True)
    certificate_filename = fields.Char(
        related='certificate_attachment_id.name', string='Certificate Filename', readonly=True)

    def action_download_certificate(self):
        """Allow direct download/view of the certificate from the awards list/form."""
        self.ensure_one()
        if self.certificate_attachment_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{self.certificate_attachment_id.id}?download=true',
                'target': 'self',
            }
        elif self.eds_certificate_id and self.eds_certificate_id.file:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/eds.certificate/{self.eds_certificate_id.id}/file/{self.eds_certificate_id.filename or "certificate.pdf"}?download=true',
                'target': 'self',
            }
        return False

    def action_view_source_record(self):
        """Navigate to the originating EDS credential record."""
        self.ensure_one()
        if self.eds_certificate_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.certificate',
                'res_id': self.eds_certificate_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if self.eds_enrollment_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.session',
                'res_id': self.eds_enrollment_id.session_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if self.eds_trainer_cert_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.trainer',
                'res_id': self.eds_trainer_cert_id.trainer_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if self.eds_sponsorship_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.sponsorship',
                'res_id': self.eds_sponsorship_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return False


class EdsCertificateAwardSync(models.Model):
    """Synchronize fully issued bank certificates to Employee Master Awards Received."""
    _inherit = 'eds.certificate'

    def _sync_to_hr_awards(self):
        Award = self.env['hr.awards'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        for cert in self:
            if cert.state != 'issued' or not cert.employee_id:
                continue
            attachment = False
            if cert.file:
                attachment = Attachment.search([
                    ('res_model', '=', 'eds.certificate'),
                    ('res_id', '=', cert.id),
                    ('res_field', '=', 'file'),
                ], limit=1)
                if not attachment:
                    attachment = Attachment.create({
                        'name': cert.filename or f"Certificate_{cert.code}.pdf",
                        'type': 'binary',
                        'datas': cert.file,
                        'res_model': 'eds.certificate',
                        'res_id': cert.id,
                        'mimetype': 'application/pdf',
                    })

            award_type_label = (
                'Internal Training Certificate'
                if cert.delivery_method_at_issue == 'internal'
                else 'Blended / Training Certificate'
            )
            award_def = _get_or_create_service_award(
                cert.env, 'Training Completion Certificate', award_type_label)

            existing = Award.search([('eds_certificate_id', '=', cert.id)], limit=1)
            course_title = cert.course_id.name or cert.certificate_title or (
                cert.session_id and cert.session_id.program_name) or _('Training Program')
            session_ref = cert.session_id.name if cert.session_id else 'N/A'
            dates_text = cert.training_dates_text or (
                cert.session_id and cert.session_id.date_start and cert.session_id.date_start.strftime('%Y-%m-%d')
            ) or ''

            vals = {
                'employee_id': cert.employee_id.id,
                'employee_name': cert.employee_id.id,
                'ref_num': cert.code,
                'award_name': award_def.id if award_def else False,
                'award_type': award_type_label,
                'institution_name': cert.provider_name_at_issue or cert.company_id.name or 'Bunna Bank S.C.',
                'fiscal_year': cert.issue_date.year if cert.issue_date else fields.Date.context_today(cert).year,
                'date_awarded': cert.issue_date or fields.Date.context_today(cert),
                'comments': (
                    f"Training Course: {course_title}\n"
                    f"Session: {session_ref} ({dates_text})\n"
                    f"Signatory: {cert.signatory_name or ''} ({cert.signatory_title or ''})\n"
                    f"Verification: {cert.verification_url or 'N/A'}"
                ),
                'active': True,
                'eds_certificate_id': cert.id,
                'eds_credential_type': 'internal_cert',
                'certificate_attachment_id': attachment.id if attachment else False,
            }
            if existing:
                existing.write(vals)
            else:
                Award.create(vals)

    def _sync_void_to_hr_awards(self):
        Award = self.env['hr.awards'].sudo()
        for cert in self:
            linked_awards = Award.search([('eds_certificate_id', '=', cert.id)])
            for award in linked_awards:
                today_str = fields.Date.context_today(cert).strftime('%Y-%m-%d')
                void_note = f"[VOIDED on {today_str}] "
                new_comments = void_note + (award.comments or '')
                award.write({
                    'active': False,
                    'comments': new_comments,
                })

    def action_issue(self):
        res = super().action_issue()
        self._sync_to_hr_awards()
        return res

    def action_void(self):
        res = super().action_void()
        self._sync_void_to_hr_awards()
        return res


class EdsEnrollmentAwardSync(models.Model):
    """Synchronize external provider attached certificates directly to Employee Master Awards Received."""
    _inherit = 'eds.enrollment'

    def _sync_external_certificate_to_hr_awards(self):
        Award = self.env['hr.awards'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        for line in self:
            if not line.provider_certificate_file or not line.employee_id:
                # If provider certificate was removed, deactivate existing award
                existing = Award.search([('eds_enrollment_id', '=', line.id)])
                if existing and not line.provider_certificate_file:
                    existing.write({'active': False})
                continue

            attachment = Attachment.search([
                ('res_model', '=', 'eds.enrollment'),
                ('res_id', '=', line.id),
                ('res_field', '=', 'provider_certificate_file'),
            ], limit=1)
            if not attachment and line.provider_certificate_file:
                attachment = Attachment.create({
                    'name': line.provider_certificate_filename or f"Provider_Cert_{line.id}.pdf",
                    'type': 'binary',
                    'datas': line.provider_certificate_file,
                    'res_model': 'eds.enrollment',
                    'res_id': line.id,
                    'mimetype': 'application/pdf',
                })

            session = line.session_id
            provider = (
                line.training_provider_name
                or (session and session.awarded_provider_id and session.awarded_provider_id.name)
                or 'External Training Institution'
            )
            issue_date = (
                line.provider_certificate_issue_date
                or (session and session.date_end and session.date_end.date())
                or fields.Date.context_today(line)
            )
            ref = line.provider_certificate_number or (session.name if session else f"EXT-{line.id}")
            program_name = (
                (session and session.program_name)
                or (session and session.course_id and session.course_id.name)
                or _('External Training Program')
            )
            dates_text = (
                f"{session.date_start.strftime('%Y-%m-%d')} to {session.date_end.strftime('%Y-%m-%d')}"
                if (session and session.date_start and session.date_end) else 'Completed'
            )

            award_def = _get_or_create_service_award(
                line.env, 'External Training Certificate', 'External Provider Certificate')

            existing = Award.search([('eds_enrollment_id', '=', line.id)], limit=1)
            vals = {
                'employee_id': line.employee_id.id,
                'employee_name': line.employee_id.id,
                'ref_num': ref,
                'award_name': award_def.id if award_def else False,
                'award_type': 'External Provider Certificate',
                'institution_name': provider,
                'fiscal_year': issue_date.year,
                'date_awarded': issue_date,
                'comments': (
                    f"External Training: {program_name}\n"
                    f"Provider / Institution: {provider}\n"
                    f"Session: {session.name if session else 'N/A'} ({dates_text})\n"
                    f"Provider Certificate Ref: {line.provider_certificate_number or 'N/A'}"
                ),
                'active': True,
                'eds_enrollment_id': line.id,
                'eds_credential_type': 'external_cert',
                'certificate_attachment_id': attachment.id if attachment else False,
            }
            if existing:
                existing.write(vals)
            else:
                Award.create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_external_certificate_to_hr_awards()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('provider_certificate_file', 'provider_certificate_number',
                                   'provider_certificate_issue_date', 'training_provider_name',
                                   'employee_id')):
            self._sync_external_certificate_to_hr_awards()
        return res


class EdsTrainerCertificationAwardSync(models.Model):
    """Synchronize internal Trainer ToT accreditations to Employee Master Awards Received."""
    _inherit = 'eds.trainer.certification'

    def _sync_to_hr_awards(self):
        Award = self.env['hr.awards'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        for rec in self:
            trainer = rec.trainer_id
            if not trainer or trainer.trainer_type != 'internal' or not trainer.employee_id:
                continue

            attachment = False
            if rec.document:
                attachment = Attachment.search([
                    ('res_model', '=', 'eds.trainer.certification'),
                    ('res_id', '=', rec.id),
                    ('res_field', '=', 'document'),
                ], limit=1)
                if not attachment:
                    attachment = Attachment.create({
                        'name': rec.filename or f"Trainer_Cert_{rec.id}.pdf",
                        'type': 'binary',
                        'datas': rec.document,
                        'res_model': 'eds.trainer.certification',
                        'res_id': rec.id,
                        'mimetype': 'application/pdf',
                    })

            award_def = _get_or_create_service_award(
                rec.env, 'Trainer ToT Certification', 'Trainer Certification / Accreditation')

            existing = Award.search([('eds_trainer_cert_id', '=', rec.id)], limit=1)
            expiry_str = rec.expiry_date.strftime('%Y-%m-%d') if rec.expiry_date else 'Permanent'
            vals = {
                'employee_id': trainer.employee_id.id,
                'employee_name': trainer.employee_id.id,
                'ref_num': f"TOT-{rec.id}",
                'award_name': award_def.id if award_def else False,
                'award_type': 'Trainer ToT Certification',
                'institution_name': rec.issued_by or 'Bunna Bank S.C.',
                'fiscal_year': rec.issued_date.year if rec.issued_date else fields.Date.context_today(rec).year,
                'date_awarded': rec.issued_date or fields.Date.context_today(rec),
                'comments': (
                    f"Certification: {rec.name}\n"
                    f"Issued By: {rec.issued_by or 'Bunna Bank S.C.'}\n"
                    f"Valid Until: {expiry_str}\n"
                    f"Status: {rec.status}"
                ),
                'active': True,
                'eds_trainer_cert_id': rec.id,
                'eds_credential_type': 'trainer_cert',
                'certificate_attachment_id': attachment.id if attachment else False,
            }
            if existing:
                existing.write(vals)
            else:
                Award.create(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_to_hr_awards()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('name', 'issued_by', 'issued_date', 'expiry_date', 'document', 'filename')):
            self._sync_to_hr_awards()
        return res


class EdsSponsorshipAwardSync(models.Model):
    """Synchronize completed degree/certification sponsorships to Employee Master Awards Received."""
    _inherit = 'eds.sponsorship'

    def _sync_to_hr_awards(self):
        Award = self.env['hr.awards'].sudo()
        Attachment = self.env['ir.attachment'].sudo()
        for rec in self:
            if rec.state != 'completed' or not rec.employee_id:
                continue

            attachment = False
            if rec.bond_agreement:
                attachment = Attachment.search([
                    ('res_model', '=', 'eds.sponsorship'),
                    ('res_id', '=', rec.id),
                    ('res_field', '=', 'bond_agreement'),
                ], limit=1)
                if not attachment:
                    attachment = Attachment.create({
                        'name': rec.bond_filename or f"Sponsorship_{rec.name}.pdf",
                        'type': 'binary',
                        'datas': rec.bond_agreement,
                        'res_model': 'eds.sponsorship',
                        'res_id': rec.id,
                        'mimetype': 'application/pdf',
                    })

            award_def = _get_or_create_service_award(
                rec.env, 'Sponsored Qualification / Degree', 'Professional Degree / Certification')

            existing = Award.search([('eds_sponsorship_id', '=', rec.id)], limit=1)
            award_date = rec.bond_end_date or fields.Date.context_today(rec)
            vals = {
                'employee_id': rec.employee_id.id,
                'employee_name': rec.employee_id.id,
                'ref_num': rec.name,
                'award_name': award_def.id if award_def else False,
                'award_type': 'Sponsored Qualification / Degree',
                'institution_name': rec.institution_name or 'Accredited Institution',
                'fiscal_year': award_date.year,
                'date_awarded': award_date,
                'comments': (
                    f"Sponsored Qualification: {rec.program_name}\n"
                    f"Field of Study: {rec.field_of_study or 'N/A'}\n"
                    f"Institution: {rec.institution_name or 'N/A'}\n"
                    f"Status: Service Bond Obligation Fulfilled"
                ),
                'active': True,
                'eds_sponsorship_id': rec.id,
                'eds_credential_type': 'sponsorship',
                'certificate_attachment_id': attachment.id if attachment else False,
            }
            if existing:
                existing.write(vals)
            else:
                Award.create(vals)

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals and vals['state'] == 'completed':
            self._sync_to_hr_awards()
        return res


class EdsAwardSyncManager(models.AbstractModel):
    """Utility service to backfill all historical EDS credentials into hr.awards."""
    _name = 'eds.award.sync.manager'
    _description = 'EDS Award Synchronization Manager'

    @api.model
    def action_backfill_all_eds_awards(self):
        """Idempotently syncs all existing issued certificates, attached provider certificates,
        trainer certifications, and completed sponsorships into hr.awards."""
        _logger.info("Starting EDS credentials sync to hr.awards...")
        
        # 1. Issued certificates
        certs = self.env['eds.certificate'].sudo().search([('state', '=', 'issued')])
        _logger.info("Syncing %d issued certificates to hr.awards", len(certs))
        certs._sync_to_hr_awards()

        # 2. Uploaded provider certificates on enrollments
        enrollments = self.env['eds.enrollment'].sudo().search([
            ('provider_certificate_file', '!=', False),
            ('employee_id', '!=', False),
        ])
        _logger.info("Syncing %d provider certificates on enrollments to hr.awards", len(enrollments))
        enrollments._sync_external_certificate_to_hr_awards()

        # 3. Trainer ToT certifications
        trainers = self.env['eds.trainer.certification'].sudo().search([
            ('trainer_id.trainer_type', '=', 'internal'),
            ('trainer_id.employee_id', '!=', False),
        ])
        _logger.info("Syncing %d trainer certifications to hr.awards", len(trainers))
        trainers._sync_to_hr_awards()

        # 4. Completed sponsorships
        sponsorships = self.env['eds.sponsorship'].sudo().search([
            ('state', '=', 'completed'),
            ('employee_id', '!=', False),
        ])
        _logger.info("Syncing %d completed sponsorships to hr.awards", len(sponsorships))
        sponsorships._sync_to_hr_awards()

        _logger.info("EDS credentials sync to hr.awards complete.")
        return True
