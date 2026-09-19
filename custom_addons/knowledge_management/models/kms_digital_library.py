# -*- coding: utf-8 -*-
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    # Training Reference Catalog Linkage (FR-KMS-007)
    course_reference_note = fields.Char(
        string='Linked Training Reference',
        help='Title or code of linked training course(s).'
    )

    # Content File or External URL (FR-KMS-009)
    is_external_link = fields.Boolean(string='Is External Reference Link', default=False)
    external_url = fields.Char(string='External Reference URL')

    file_data = fields.Binary(string='Attached Digital Asset', attachment=True)
    file_name = fields.Char(string='Filename')
    file_size_display = fields.Char(string='Size', compute='_compute_file_display', store=True)

    cover_image = fields.Binary(string='Cover Thumbnail', attachment=True)
    summary = fields.Text(string='Executive Summary & Key Takeaways', tracking=True)

    # Metrics
    view_count = fields.Integer(string='Reads / Views', default=0, readonly=True)
    download_count = fields.Integer(string='Downloads', default=0, readonly=True)
    rating_average = fields.Float(string='Rating', default=5.0)

    active = fields.Boolean(default=True)

    @api.depends('file_data', 'file_name')
    def _compute_file_display(self):
        for rec in self:
            if rec.file_data:
                raw = base64.b64decode(rec.file_data)
                size_kb = len(raw) / 1024.0
                if size_kb > 1024:
                    rec.file_size_display = f"{size_kb / 1024.0:.2f} MB"
                else:
                    rec.file_size_display = f"{size_kb:.1f} KB"
            else:
                rec.file_size_display = False

    def action_read_resource(self):
        self.ensure_one()
        self.sudo().write({'view_count': self.view_count + 1})
        if self.is_external_link and self.external_url:
            return {
                'type': 'ir.actions.act_url',
                'url': self.external_url,
                'target': 'new',
            }
        elif self.file_data:
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{self._name}/{self.id}/file_data/{self.file_name or "resource.pdf"}?download=false',
                'target': 'new',
            }
        else:
            raise UserError(_('No document or external link is associated with this library item.'))

    def action_download_resource(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('No downloadable file attached.'))
        self.sudo().write({'download_count': self.download_count + 1})
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/file_data/{self.file_name or "resource.pdf"}?download=true',
            'target': 'self',
        }
