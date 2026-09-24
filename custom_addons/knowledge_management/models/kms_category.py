# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class KmsCategory(models.Model):
    """Hierarchical Knowledge Category Taxonomy (FR-KMS-002, FR-KMS-003)."""
    _name = 'kms.category'
    _description = 'Knowledge Category'
    _order = 'complete_name'
    _parent_store = True

    name = fields.Char(string='Category Name', required=True, translate=True)
    complete_name = fields.Char(string='Complete Name', compute='_compute_complete_name', recursive=True, store=True)
    code = fields.Char(string='Code', required=True)
    parent_id = fields.Many2one('kms.category', string='Parent Category', index=True, ondelete='cascade')
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many('kms.category', 'parent_id', string='Subcategories')
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index', default=0)
    active = fields.Boolean(default=True)

    document_count = fields.Integer(string='Documents Count', compute='_compute_document_count')

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'The category code must be unique!'
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = f"{rec.parent_id.complete_name} / {rec.name}"
            else:
                rec.complete_name = rec.name

    def _compute_document_count(self):
        doc_data = self.env['kms.document'].read_group(
            [('category_id', 'in', self.ids)],
            ['category_id'],
            ['category_id']
        )
        mapped_data = {data['category_id'][0]: data['category_id_count'] for data in doc_data}
        for rec in self:
            rec.document_count = mapped_data.get(rec.id, 0)


class KmsDocumentType(models.Model):
    """Document Type taxonomy: SOP, Policy, Manual, Circular, Directive (FR-KMS-002)."""
    _name = 'kms.document.type'
    _description = 'Knowledge Document Type'
    _order = 'sequence, name'

    name = fields.Char(string='Document Type', required=True, translate=True)
    code = fields.Char(string='Type Code', required=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(string='Description')
    requires_approval = fields.Boolean(string='Requires Multi-level Approval', default=True)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'The document type code must be unique!'
    )


class KmsClassification(models.Model):
    """Security Classification Level: Public, Internal, Confidential, Strictly Confidential (FR-KMS-002, FR-KMS-014, FR-KMS-018)."""
    _name = 'kms.classification'
    _description = 'Document Security Classification'
    _order = 'security_level asc, name'

    name = fields.Char(string='Classification Name', required=True)
    code = fields.Char(string='Code', required=True)
    security_level = fields.Integer(
        string='Security Rank / Level',
        required=True,
        default=2,
        help='1: Public, 2: Internal Use, 3: Confidential, 4: Strictly Confidential'
    )
    badge_color = fields.Selection([
        ('success', 'Green / Public'),
        ('info', 'Blue / Internal'),
        ('warning', 'Orange / Confidential'),
        ('danger', 'Maroon / Strictly Confidential'),
    ], string='Badge Color', default='info', required=True)
    watermark_mandatory = fields.Boolean(
        string='Watermark Mandatory on Download',
        default=True,
        help='Automatically stamp downloaded files with downloader identity, timestamp and department.'
    )
    download_restricted_default = fields.Boolean(
        string='Download Restricted by Default',
        default=False,
        help='If checked, only authorized groups/roles can download; others have view-only access.'
    )
    view_only_default = fields.Boolean(
        string='Enforce View-Only by Default',
        default=False,
        help='Disables download entirely for this classification tier.'
    )
    description = fields.Text(string='Classification Policy Description')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Classification code must be unique!'
    )
    _security_level_unique = models.Constraint(
        'UNIQUE(security_level)',
        'Security level rank must be unique!'
    )


class KmsTag(models.Model):
    """Taxonomy tag vocabulary (FR-KMS-002, FR-KMS-003)."""
    _name = 'kms.tag'
    _description = 'Knowledge Tag'
    _order = 'name'

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=1)
    active = fields.Boolean(default=True)

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'Tag name must be unique!'
    )
