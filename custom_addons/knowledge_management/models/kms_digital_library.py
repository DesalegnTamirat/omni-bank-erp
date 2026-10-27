# -*- coding: utf-8 -*-
import base64
import hashlib
import logging
from urllib.parse import urlparse
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from ..utils.text_extract import extract_document_text

_logger = logging.getLogger(__name__)


class KmsDigitalLibrary(models.Model):
    """
    Curated Digital Library (FR-KMS-006, FR-KMS-007, FR-KMS-008, FR-KMS-009).
    Houses e-books, whitepapers, research studies, industry publications, and course references.
    Distinct from the governed Document Repository: browsable, consultative, not bound to strict approval workflows.
    """
    _name = 'kms.digital.library'
    _description = 'Digital Library Asset'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'is_recommended desc, create_date desc'

    name = fields.Char(string='Resource Title', required=True, tracking=True, index=True)
    author = fields.Char(string='Author / Contributing Organization', tracking=True)
    publisher = fields.Char(string='Publisher / Source')
    publication_year = fields.Char(string='Publication Year')
    isbn_or_ref = fields.Char(string='ISBN / Regulatory Reference ID')

    resource_type = fields.Selection([
        ('ebook', 'E-Book / Textbook'),
        ('whitepaper', 'Whitepaper / Research Paper'),
        ('regulatory', 'Regulatory Publication / Circular Reference'),
        ('training_reference', 'Training Reference Material'),
        ('industry_report', 'Banking Industry / Market Report'),
        ('article', 'Insight Article / Guide'),
    ], string='Resource Type', required=True, default='ebook', tracking=True)

    category_id = fields.Many2one('kms.category', string='Domain / Topic Category', required=True, index=True)
    tag_ids = fields.Many2many('kms.tag', string='Tags')

    # Recommendation & Role Targeting (FR-KMS-008)
    is_recommended = fields.Boolean(string='Featured / Recommended Reading', default=False, tracking=True)
    curator_notes = fields.Text(string='Curator Recommendation Notes')
    target_job_ids = fields.Many2many(
        'hr.job',
        'kms_library_job_rel',
        'resource_id',
        'job_id',
        string='Recommended for Job Roles',
        help='Roles for which this resource is highly recommended.'
    )
    target_department_ids = fields.Many2many(
        'hr.department',
        'kms_library_dept_rel',
        'resource_id',
        'dept_id',
        string='Target Departments'
    )
    recommended_for_me = fields.Boolean(
        string='Recommended for Me',
        compute='_compute_recommended_for_me',
        search='_search_recommended_for_me',
    )

    # Training Reference Catalog Linkage (FR-KMS-007)
    course_reference_note = fields.Char(
        string='Linked Training Reference',
        help='Title or code of linked training course(s).'
    )

    # Content File or External URL (FR-KMS-009)
    is_external_link = fields.Boolean(string='Is External Reference Link', default=False)
    external_url = fields.Char(string='External Reference URL')

    file_data = fields.Binary(
        string='Attached Digital Asset', attachment=True,
        groups='knowledge_management.group_kms_contributor',
    )
    file_name = fields.Char(string='Filename')
    file_size_display = fields.Char(string='Size', compute='_compute_file_display', store=True)
    preview_text = fields.Text(string='Extracted Text Preview', readonly=True)

    cover_image = fields.Binary(string='Cover Thumbnail', attachment=True)
    summary = fields.Text(string='Executive Summary & Key Takeaways', tracking=True)

    # Metrics
    view_count = fields.Integer(string='Reads / Views', default=0, readonly=True)
    download_count = fields.Integer(string='Downloads', default=0, readonly=True)
    rating_average = fields.Float(string='Rating', default=5.0)

    active = fields.Boolean(default=True)

    @api.depends('is_recommended', 'target_job_ids', 'target_department_ids')
    @api.depends_context('uid')
    def _compute_recommended_for_me(self):
        employee = self.env.user.employee_id
        job_id = employee.job_id.id if employee and employee.job_id else False
        department_id = employee.department_id.id if employee and employee.department_id else False
        for rec in self:
            untargeted = not rec.target_job_ids and not rec.target_department_ids
            rec.recommended_for_me = bool(rec.is_recommended and (
                untargeted
                or job_id and job_id in rec.target_job_ids.ids
                or department_id and department_id in rec.target_department_ids.ids
            ))

    def _search_recommended_for_me(self, operator, value):
        employee = self.env.user.employee_id
        job_id = employee.job_id.id if employee and employee.job_id else 0
        department_id = employee.department_id.id if employee and employee.department_id else 0
        domain = [
            '&', ('is_recommended', '=', True),
            '|', '|',
            ('target_job_ids', 'in', [job_id]),
            ('target_department_ids', 'in', [department_id]),
            '&', ('target_job_ids', '=', False), ('target_department_ids', '=', False),
        ]
        positive = True in value if isinstance(value, (list, tuple, set)) else bool(value)
        return domain if (operator in ('=', 'in')) == positive else ['!'] + domain

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('file_data'):
                vals['preview_text'] = extract_document_text(vals['file_data'], vals.get('file_name'))
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            rec._log_audit_action('upload', 'Digital library asset created', strict=True)
            if vals.get('file_data'):
                # A user cannot collect points again by uploading identical
                # binary content under a new catalog title.
                encoded = vals['file_data']
                checksum = hashlib.sha256(encoded.encode('ascii') if isinstance(encoded, str) else encoded).hexdigest()
                description = f'Library upload checksum: {checksum}'
                if not self.env['kms.contributor.point'].sudo().search_count([
                    ('user_id', '=', self.env.user.id),
                    ('source', '=', 'library_upload'),
                    ('description', '=', description),
                ]):
                    self.env['kms.contributor.point']._award_points(
                        self.env.user, points=8, source='library_upload',
                        description=description,
                    )
        return records

    def write(self, vals):
        if 'file_data' in vals:
            vals = dict(vals, preview_text=extract_document_text(
                vals['file_data'], vals.get('file_name') or (self.file_name if len(self) == 1 else '')
            ))
        result = super().write(vals)
        if set(vals) - {'view_count', 'download_count'}:
            self._log_audit_action('modify', 'Digital library asset updated', strict=True)
        return result

    def unlink(self):
        self._log_audit_action('delete', 'Digital library asset deleted', strict=True)
        return super().unlink()

    @api.constrains('is_external_link', 'external_url')
    def _check_external_url(self):
        for rec in self:
            if rec.is_external_link and rec.external_url:
                parsed = urlparse(rec.external_url.strip())
                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                    raise ValidationError(_('External library references must use an HTTP or HTTPS URL.'))

    @api.depends('file_data', 'file_name')
    def _compute_file_display(self):
        persisted_ids = [rec.id for rec in self if isinstance(rec.id, int)]
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'kms.digital.library'), ('res_id', 'in', persisted_ids),
            ('res_field', '=', 'file_data'),
        ]) if persisted_ids else self.env['ir.attachment'].browse()
        sizes = {attachment.res_id: attachment.file_size for attachment in attachments}
        for rec in self:
            encoded = rec.sudo().file_data if rec.id not in sizes else False
            if rec.id in sizes or encoded:
                size_kb = (sizes[rec.id] if rec.id in sizes else len(base64.b64decode(encoded))) / 1024.0
                if size_kb > 1024:
                    rec.file_size_display = f"{size_kb / 1024.0:.2f} MB"
                else:
                    rec.file_size_display = f"{size_kb:.1f} KB"
            else:
                rec.file_size_display = False

    def _log_audit_action(self, action_type, details=None, strict=False):
        for rec in self:
            try:
                self.env['kms.audit.log']._log_audit_event(
                    action=action_type,
                    resource_type='digital_library',
                    resource_name=f"{rec.isbn_or_ref or 'LIB'} - {rec.name}",
                    details=details or f"Action {action_type} performed on library asset {rec.name}"
                )
            except Exception as e:
                _logger.warning("Could not log digital library audit: %s", e)
                if strict:
                    raise

    def action_read_resource(self):
        self.ensure_one()
        self.check_access('read')
        if self.is_external_link and self.external_url:
            self._log_audit_action('view', f'Opened external library reference: {self.name}', strict=True)
            self.env.cr.execute(
                'UPDATE kms_digital_library SET view_count = COALESCE(view_count, 0) + 1 WHERE id = %s',
                (self.id,),
            )
            self.invalidate_recordset(['view_count'])
            return {
                'type': 'ir.actions.act_url',
                'url': self.external_url,
                'target': 'new',
            }
        elif self.sudo().file_data:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/kms/library/{self.id}/view',
                'target': 'new',
            }
        else:
            raise UserError(_('No document or external link is associated with this library item.'))

    def action_download_resource(self):
        self.ensure_one()
        self.check_access('read')
        if not self.sudo().file_data:
            raise UserError(_('No downloadable file attached.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/kms/library/{self.id}/download',
            'target': 'self',
        }
