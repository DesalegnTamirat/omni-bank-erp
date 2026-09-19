# -*- coding: utf-8 -*-
import base64
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError, ValidationError

_logger = logging.getLogger(__name__)


class KmsDocument(models.Model):
    """
    Governed Central Document Repository (FR-KMS-001 to FR-KMS-005, FR-KMS-014 to FR-KMS-018).
    Governs institutional documents: SOPs, Policies, Manuals, Regulatory Directives.
    Enforces strict lifecycle: Draft -> Under Review -> Approved -> Archived with full version control.
    """
    _name = 'kms.document'
    _description = 'Governed Knowledge Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(string='Document Title', required=True, tracking=True, index=True)
    code = fields.Char(
        string='Document Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        index=True
    )
    category_id = fields.Many2one(
        'kms.category',
        string='Category',
        required=True,
        tracking=True,
        index=True
    )
    doc_type_id = fields.Many2one(
        'kms.document.type',
        string='Document Type',
        required=True,
        tracking=True,
        index=True
    )
    classification_id = fields.Many2one(
        'kms.classification',
        string='Security Classification',
        required=True,
        tracking=True,
        index=True
    )
    tag_ids = fields.Many2many('kms.tag', string='Tags')

    # Organizational Scoping & Governance
    department_id = fields.Many2one(
        'hr.department',
        string='Target Department',
        tracking=True,
        index=True,
        help='Restricts or scopes this policy/SOP to a specific department. Leave empty for bank-wide applicability.'
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit / Branch',
        tracking=True,
        index=True,
        help='Scope to a specific branch or operating unit. Leave empty for all branches.'
    )
    owner_id = fields.Many2one(
        'hr.employee',
        string='Content Owner / SME',
        required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    reviewer_id = fields.Many2one('hr.employee', string='Designated Reviewer', tracking=True)
    approver_id = fields.Many2one('hr.employee', string='Approval Authority', tracking=True)
    date_approved = fields.Datetime(string='Approval Date', readonly=True, copy=False)

    # Dates
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, tracking=True)
    review_due_date = fields.Date(string='Next Review Due Date', tracking=True)

    # Lifecycle State Machine
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('approved', 'Approved & Active'),
        ('archived', 'Archived / Superseded'),
    ], string='Status', default='draft', tracking=True, required=True, index=True)

    # Version Control
    version = fields.Char(string='Version', default='1.0', required=True, tracking=True)
    is_latest_version = fields.Boolean(string='Is Latest Active Version', default=True, index=True)
    previous_version_id = fields.Many2one('kms.document', string='Preceding Version', readonly=True, copy=False)
    version_ids = fields.One2many('kms.document.version', 'document_id', string='Version History')
    change_summary = fields.Text(string='Revision Notes / Changelog')

    # Document File & Full-Text Content
    file_data = fields.Binary(string='Document File', attachment=True)
    file_name = fields.Char(string='Filename')
    file_size = fields.Integer(string='File Size (Bytes)', compute='_compute_file_metadata', store=True)
    mimetype = fields.Char(string='MIME Type', compute='_compute_file_metadata', store=True)
    is_pdf = fields.Boolean(string='Is PDF File', compute='_compute_file_metadata', store=True)

    summary = fields.Text(string='Executive Summary / Scope', tracking=True)
    content_text = fields.Text(string='Full Content Text / Extracted Text', help='Used for deep full-text indexed searches.')

    # Security & Protection Controls (FR-KMS-014, FR-KMS-015, FR-KMS-016, FR-KMS-018)
    is_view_only = fields.Boolean(
        string='Strict View-Only',
        default=False,
        tracking=True,
        help='If enabled, download is completely disabled for all users except KMS Administrators.'
    )
    require_watermark = fields.Boolean(
        string='Dynamic Watermark on Download',
        default=True,
        help='Automatically stamps downloader identity, department, and timestamp onto every page of the downloaded PDF.'
    )
    allowed_download_group_ids = fields.Many2many(
        'res.groups',
        'kms_doc_download_rel',
        'doc_id',
        'group_id',
        string='Authorized Download Roles',
        help='Leave empty to allow all authorized viewers to download watermarked copies.'
    )

    # Analytics & Usage Metrics
    view_count = fields.Integer(string='Total Views', default=0, readonly=True)
    download_count = fields.Integer(string='Total Downloads', default=0, readonly=True)
    audit_log_ids = fields.One2many('kms.audit.log', 'document_id', string='Audit Records')

    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('kms.document') or _('New')
        records = super(KmsDocument, self).create(vals_list)
        for rec in records:
            rec._log_audit_action('upload', 'Document created in Draft')
        return records

    @api.depends('file_data', 'file_name')
    def _compute_file_metadata(self):
        for rec in self:
            if rec.file_data:
                raw = base64.b64decode(rec.file_data)
                rec.file_size = len(raw)
                fname = (rec.file_name or '').lower()
                if fname.endswith('.pdf'):
                    rec.mimetype = 'application/pdf'
                    rec.is_pdf = True
                elif fname.endswith(('.doc', '.docx')):
                    rec.mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    rec.is_pdf = False
                elif fname.endswith(('.xls', '.xlsx')):
                    rec.mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    rec.is_pdf = False
                else:
                    rec.mimetype = 'application/octet-stream'
                    rec.is_pdf = False
            else:
                rec.file_size = 0
                rec.mimetype = False
                rec.is_pdf = False

    @api.onchange('classification_id')
    def _onchange_classification_id(self):
        if self.classification_id:
            if self.classification_id.view_only_default:
                self.is_view_only = True
            if self.classification_id.watermark_mandatory:
                self.require_watermark = True

    # Lifecycle Actions
    def action_submit_for_review(self):
        for rec in self:
            if not rec.file_data:
                raise UserError(_('Cannot submit a document without an uploaded file.'))
            rec.write({'state': 'review'})
            rec.message_post(body=_('Document submitted for review and approval.'))
            rec._log_audit_action('modify', 'Submitted for review')

    def action_approve(self):
        for rec in self:
            # Snapshot previous version if this is an update
            if rec.version_ids:
                pass  # Version snapshots already managed
            rec.write({
                'state': 'approved',
                'date_approved': fields.Datetime.now(),
                'is_latest_version': True
            })
            # Create a snapshot in kms.document.version
            self.env['kms.document.version'].create({
                'document_id': rec.id,
                'version_number': rec.version,
                'file_data': rec.file_data,
                'file_name': rec.file_name,
                'effective_date': rec.effective_date,
                'change_summary': rec.change_summary or _('Initial approval'),
                'approved_by_id': self.env.user.employee_id.id if self.env.user.employee_id else False,
            })
            rec.message_post(body=_('Document approved and published to the active repository.'))
            rec._log_audit_action('approve', f'Approved version {rec.version}')
            # Award points to content owner
            if rec.owner_id and rec.owner_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.owner_id.user_id,
                    points=20,
                    source='document_publish',
                    description=f'Published approved document: {rec.name} ({rec.code})'
                )

    def action_reject(self):
        for rec in self:
            rec.write({'state': 'draft'})
            rec.message_post(body=_('Document rejected and returned to draft.'))
            rec._log_audit_action('modify', 'Document rejected back to Draft')

    def action_archive(self):
        for rec in self:
            rec.write({'state': 'archived', 'is_latest_version': False})
            rec.message_post(body=_('Document archived and superseded.'))
            rec._log_audit_action('archive', 'Document archived')

    def action_create_new_version(self):
        """Creates a revision draft with incremented version number (FR-KMS-004)."""
        self.ensure_one()
        current_ver = self.version or '1.0'
        try:
            parts = current_ver.split('.')
            if len(parts) == 2:
                new_ver = f"{parts[0]}.{int(parts[1]) + 1}"
            else:
                new_ver = f"{current_ver}.1"
        except Exception:
            new_ver = f"{current_ver}-rev"

        new_doc = self.copy({
            'name': self.name,
            'version': new_ver,
            'state': 'draft',
            'previous_version_id': self.id,
            'change_summary': _('Revision based on %s (v%s)') % (self.code, self.version),
            'date_approved': False,
            'is_latest_version': False,
        })
        self.message_post(body=_('New revision draft initiated: %s (v%s)') % (new_doc.code, new_ver))
        return {
            'name': _('Document Revision'),
            'type': 'ir.actions.act_window',
            'res_model': 'kms.document',
            'view_mode': 'form',
            'res_id': new_doc.id,
            'target': 'current',
        }

    def action_view_versions(self):
        self.ensure_one()
        return {
            'name': _('Version History - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.document.version',
            'view_mode': 'list,form',
            'domain': [('document_id', '=', self.id)],
            'context': {'default_document_id': self.id},
        }

    def action_download_watermarked(self):
        """Action handler that triggers download through secure watermarked controller."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('No file is attached to this document.'))

        # Check view-only security
        if self.is_view_only and not self.env.user.has_group('knowledge_management.group_kms_manager'):
            raise AccessError(_('This document is marked as Strict View-Only. Downloading is prohibited by policy.'))

        # Check role-based download permissions (FR-KMS-014)
        if self.allowed_download_group_ids:
            user_groups = self.env.user.groups_id
            if not any(g in user_groups for g in self.allowed_download_group_ids) and not self.env.user.has_group('knowledge_management.group_kms_manager'):
                raise AccessError(_('Your assigned role does not have download permissions for this document.'))

        # Log audit record
        self._log_audit_action('download', 'Document downloaded by user')
        self.sudo().write({'download_count': self.download_count + 1})

        return {
            'type': 'ir.actions.act_url',
            'url': f'/kms/document/{self.id}/download',
            'target': 'self',
        }

    def _log_audit_action(self, action_type, details=None):
        for rec in self:
            try:
                emp = self.env.user.employee_id
                self.env['kms.audit.log'].sudo().create({
                    'user_id': self.env.user.id,
                    'employee_id': emp.id if emp else False,
                    'action': action_type,
                    'document_id': rec.id,
                    'resource_type': 'document',
                    'resource_name': f"{rec.code} - {rec.name} (v{rec.version})",
                    'details': details or f"Action {action_type} performed",
                })
            except Exception as e:
                _logger.warning("Could not log KMS audit entry: %s", e)
