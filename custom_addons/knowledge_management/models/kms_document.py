# -*- coding: utf-8 -*-
import base64
import logging
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError, ValidationError
from ..utils.text_extract import extract_document_text

_logger = logging.getLogger(__name__)

# A published revision is an audit record. Content and access policy changes
# must be made on a new draft, then approved as a new version.
_REVISION_FIELDS = {
    'name', 'code', 'category_id', 'doc_type_id', 'classification_id',
    'classification', 'authorized_employee_ids', 'tag_ids', 'department_id',
    'operating_unit_id', 'owner_id', 'reviewer_id', 'approver_id',
    'effective_date', 'review_due_date', 'version', 'previous_version_id',
    'change_summary', 'file_data', 'file_name', 'summary', 'content_text',
    'is_view_only', 'require_watermark', 'require_encryption',
    'allowed_download_group_ids', 'active',
}


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
    classification = fields.Selection([
        ('public', 'Public'),
        ('internal', 'Internal'),
        ('confidential', 'Confidential'),
        ('restricted', 'Restricted'),
    ], string='Security Classification Scope', compute='_compute_classification', store=True, readonly=True)
    authorized_employee_ids = fields.Many2many(
        'hr.employee',
        'kms_doc_authorized_employee_rel',
        'doc_id',
        'employee_id',
        string='Authorized Employees (Restricted Access)',
        help='Specific employees granted access when document is restricted.'
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
    file_data = fields.Binary(
        string='Document File', attachment=True,
        groups='knowledge_management.group_kms_contributor',
    )
    file_name = fields.Char(string='Filename')
    file_size = fields.Integer(string='File Size (Bytes)', compute='_compute_file_metadata', store=True)
    mimetype = fields.Char(string='MIME Type', compute='_compute_file_metadata', store=True)
    is_pdf = fields.Boolean(string='Is PDF File', compute='_compute_file_metadata', store=True)

    summary = fields.Text(string='Executive Summary / Scope', tracking=True)
    content_text = fields.Text(string='Full Content Text / Extracted Text', help='Used for deep full-text indexed searches.')
    fts_query = fields.Char(
        string='Full-Text Search',
        store=False,
        search='_search_fts',
        help='Indexed PostgreSQL tsvector full-text search across Title, Summary, and Content.'
    )

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
    require_encryption = fields.Boolean(
        string='Session-Bound Download Encryption',
        default=False,
        tracking=True,
        help='Encrypts download payload with session-bound key so it can only be opened inside verified KMS session (FR-KMS-016).'
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
            if vals.get('file_data') and 'content_text' not in vals:
                vals['content_text'] = extract_document_text(vals['file_data'], vals.get('file_name'))
            if 'classification' in vals and not self.env.su:
                raise AccessError(_('Document classification is derived from the selected security level.'))
            if vals.get('state', 'draft') != 'draft' and not self.env.su:
                raise AccessError(_('New documents must start as drafts.'))
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('kms.document') or _('New')
        records = super(KmsDocument, self).create(vals_list)
        for rec in records:
            rec._log_audit_action('upload', 'Document created in Draft', strict=True)
        return records

    def write(self, vals):
        if 'file_data' in vals and 'content_text' not in vals:
            vals = dict(vals, content_text=extract_document_text(
                vals['file_data'], vals.get('file_name') or (self.file_name if len(self) == 1 else '')
            ))
        target = vals.get('state')
        if 'classification' in vals and not self.env.su:
            raise AccessError(_('Document classification is derived from the selected security level.'))
        if self.ids:
            # Serialize edits and publication so a late draft edit cannot race
            # with a review or approval transition.
            self.env.cr.execute(
                'SELECT id FROM kms_document WHERE id IN %s ORDER BY id FOR UPDATE',
                (tuple(self.ids),),
            )
            self.invalidate_recordset(['state'])
        if _REVISION_FIELDS.intersection(vals):
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(_(
                        'Documents under review or already published cannot be edited. '
                        'Return a reviewed document to draft, or initiate a new revision.'
                    ))
        if {'date_approved', 'is_latest_version', 'view_count', 'download_count'} & vals.keys() and not self.env.su:
            raise AccessError(_('Document lifecycle and usage counters cannot be edited directly.'))
        if target:
            if target == 'approved' and not (
                self.env.su or self.env.user.has_group('knowledge_management.group_kms_reviewer')
            ):
                raise AccessError(_('Only KMS reviewers may approve documents.'))
            if target == 'archived' and not (
                self.env.su or self.env.user.has_group('knowledge_management.group_kms_manager')
            ):
                raise AccessError(_('Only KMS managers may archive documents.'))
            if target == 'draft' and any(rec.state == 'review' for rec in self) and not (
                self.env.su or self.env.user.has_group('knowledge_management.group_kms_reviewer')
            ):
                raise AccessError(_('Only KMS reviewers may return submitted documents to draft.'))
            allowed = {
                'draft': {'review'}, 'review': {'draft', 'approved'},
                'approved': {'archived'}, 'archived': set(),
            }
            for rec in self:
                if target not in allowed.get(rec.state, set()):
                    raise UserError(_('Invalid document transition: %s to %s.') % (rec.state, target))
                if target == 'review' and not rec.sudo().file_data:
                    raise UserError(_('A document file is required before review.'))
                if target == 'approved' and not rec.sudo().file_data:
                    raise UserError(_('A document file is required for approval.'))
                if target == 'approved' and rec.approver_id and not (
                    self.env.su
                    or self.env.user.has_group('knowledge_management.group_kms_manager')
                    or rec.approver_id.sudo().user_id == self.env.user
                ):
                    raise AccessError(_('Only the designated approver may publish this document.'))
                if target == 'approved' and rec.previous_version_id:
                    previous = rec.previous_version_id
                    self.env.cr.execute(
                        'SELECT id FROM kms_document WHERE id = %s FOR UPDATE',
                        (previous.id,),
                    )
                    previous.invalidate_recordset(['state', 'is_latest_version'])
                    if previous.state != 'approved' or not previous.is_latest_version:
                        raise UserError(_('The preceding version is no longer the active approved document.'))
            if target == 'approved':
                vals = dict(vals, date_approved=fields.Datetime.now(),
                            is_latest_version=True)
            elif target == 'archived':
                vals = dict(vals, is_latest_version=False)
        result = super(KmsDocument, self).write(vals)
        if _REVISION_FIELDS.intersection(vals):
            self._log_audit_action('modify', 'Draft document content or metadata updated', strict=True)
        if target == 'review':
            self._log_audit_action('modify', 'Submitted for review', strict=True)
        elif target == 'draft':
            self._log_audit_action('modify', 'Returned to draft after review', strict=True)
        if target == 'approved':
            for rec in self:
                if not self.env['kms.document.version'].sudo().search_count([
                    ('document_id', '=', rec.id), ('version_number', '=', rec.version),
                ]):
                    self.env['kms.document.version'].sudo().with_context(_kms_version_snapshot=True).create({
                        'document_id': rec.id, 'version_number': rec.version,
                        'file_data': rec.sudo().file_data, 'file_name': rec.file_name,
                        'effective_date': rec.effective_date,
                        'change_summary': rec.change_summary or _('Initial approval'),
                        'approved_by_id': self.env.user.employee_id.id or False,
                    })
                if rec.previous_version_id and rec.previous_version_id.state == 'approved':
                    rec.previous_version_id.sudo().write({
                        'state': 'archived',
                    })
                rec._log_audit_action('approve', f'Approved version {rec.version}', strict=True)
                owner = rec.sudo().owner_id
                if owner and owner.user_id:
                    self.env['kms.contributor.point']._award_points(
                        owner.user_id, points=20, source='document_publish',
                        description=f'Published approved document: {rec.name} ({rec.code})',
                    )
        elif target == 'archived':
            self._log_audit_action('archive', 'Document archived or superseded', strict=True)
        return result

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Submitted, approved, and archived documents must be retained.'))
        self._log_audit_action('delete', 'Draft document deleted', strict=True)
        return super().unlink()

    @api.depends('file_data', 'file_name')
    def _compute_file_metadata(self):
        persisted_ids = [rec.id for rec in self if isinstance(rec.id, int)]
        attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'kms.document'), ('res_id', 'in', persisted_ids),
            ('res_field', '=', 'file_data'),
        ]) if persisted_ids else self.env['ir.attachment'].browse()
        sizes = {attachment.res_id: attachment.file_size for attachment in attachments}
        for rec in self:
            encoded = rec.sudo().file_data if rec.id not in sizes else False
            has_file = rec.id in sizes or bool(encoded)
            if has_file:
                rec.file_size = sizes[rec.id] if rec.id in sizes else len(base64.b64decode(encoded))
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

    @api.depends('classification_id', 'classification_id.code')
    def _compute_classification(self):
        code_map = {
            'PUB': 'public', 'PUBLIC': 'public',
            'INT': 'internal', 'INTERNAL': 'internal',
            'CONF': 'confidential', 'CONFIDENTIAL': 'confidential',
            'SCONF': 'restricted', 'RESTRICTED': 'restricted',
        }
        for rec in self:
            if rec.classification_id and rec.classification_id.code:
                code = rec.classification_id.code.upper().split('-', 1)[0]
                rec.classification = code_map.get(code, 'restricted')
            else:
                rec.classification = 'restricted'

    @api.onchange('classification')
    def _onchange_classification(self):
        if self.classification:
            inv_map = {
                'public': 'PUB',
                'internal': 'INT',
                'confidential': 'CONF',
                'restricted': 'SCONF',
            }
            target_code = inv_map.get(self.classification)
            if target_code:
                cl = self.env['kms.classification'].search([('code', '=', target_code)], limit=1)
                if cl:
                    self.classification_id = cl.id

    @api.onchange('classification_id')
    def _onchange_classification_id(self):
        if self.classification_id:
            code_map = {
                'PUB': 'public', 'PUBLIC': 'public',
                'INT': 'internal', 'INTERNAL': 'internal',
                'CONF': 'confidential', 'CONFIDENTIAL': 'confidential',
                'SCONF': 'restricted', 'RESTRICTED': 'restricted',
            }
            self.classification = code_map.get(self.classification_id.code.upper().split('-', 1)[0], 'restricted')
            if getattr(self.classification_id, 'view_only_default', False):
                self.is_view_only = True
            if getattr(self.classification_id, 'watermark_mandatory', False):
                self.require_watermark = True

    # Lifecycle Actions
    def action_submit_for_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft documents can be submitted.'))
            if not rec.file_data:
                raise UserError(_('Cannot submit a document without an uploaded file.'))
            rec.write({'state': 'review'})
            action_link = f"/web#id={rec.id}&model=kms.document"
            msg_text = _('Document %s (%s) submitted for review and approval.') % (rec.name, rec.code)
            body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">📄 Review Document</a>
</div>""")
            partner_ids = []
            # HR contact and linked user are private employee fields in Odoo 19.
            # Elevate only the identity lookup, not the document transition.
            reviewer_emp = (rec.reviewer_id or rec.approver_id).sudo()
            if reviewer_emp and reviewer_emp.work_contact_id:
                partner_ids.append(reviewer_emp.work_contact_id.id)
            rec.message_post(body=body, partner_ids=partner_ids)
            reviewer_user = reviewer_emp.user_id if reviewer_emp else False
            if reviewer_user:
                try:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=reviewer_user.id,
                        summary=_('Review Document: %s') % rec.name,
                        note=body
                    )
                except Exception:
                    pass

    def action_approve(self):
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('Only documents under review can be approved.'))
            rec.write({
                'state': 'approved',
            })
            action_link = f"/web#id={rec.id}&model=kms.document"
            msg_text = _('Document %s (%s) approved and published to the active repository.') % (rec.name, rec.code)
            body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">👁️ View Published Document</a>
</div>""")
            partner_ids = []
            owner = rec.sudo().owner_id
            if owner and owner.work_contact_id:
                partner_ids.append(owner.work_contact_id.id)
            rec.message_post(body=body, partner_ids=partner_ids)

    def action_reject(self):
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('Only documents under review can be returned to draft.'))
            rec.write({'state': 'draft'})
            action_link = f"/web#id={rec.id}&model=kms.document"
            msg_text = _('Document %s (%s) rejected and returned to draft.') % (rec.name, rec.code)
            body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">✏️ View &amp; Revise Document</a>
</div>""")
            partner_ids = []
            owner = rec.sudo().owner_id
            if owner and owner.work_contact_id:
                partner_ids.append(owner.work_contact_id.id)
            rec.message_post(body=body, partner_ids=partner_ids)

    def action_archive(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved documents can be archived.'))
            rec.write({'state': 'archived'})
            rec.message_post(body=_('Document archived and superseded.'))

    def action_create_new_version(self):
        """Creates a revision draft with incremented version number (FR-KMS-004)."""
        self.ensure_one()
        self.check_access('read')
        if self.state != 'approved':
            raise UserError(_('Only approved documents can be revised.'))
        if not (
            self.env.su or self.owner_id.sudo().user_id == self.env.user
            or self.env.user.has_group('knowledge_management.group_kms_reviewer')
        ):
            raise AccessError(_('Only the document owner or a KMS reviewer may initiate a revision.'))
        current_ver = self.version or '1.0'
        try:
            parts = current_ver.split('.')
            if len(parts) == 2:
                new_ver = f"{parts[0]}.{int(parts[1]) + 1}"
            else:
                new_ver = f"{current_ver}.1"
        except Exception:
            new_ver = f"{current_ver}-rev"

        existing = self.search([
            ('previous_version_id', '=', self.id),
            ('state', 'in', ['draft', 'review']),
        ], limit=1)
        if existing:
            new_doc = existing
        else:
            # copy() also carries employee audience and other HR-backed relations.
            # The authorized reviewer has passed the access check above, but
            # Odoo 19 does not grant that role direct write access to HR records.
            new_doc = self.sudo().copy({
                'name': self.name,
                'version': new_ver,
                'state': 'draft',
                'previous_version_id': self.id,
                'change_summary': _('Revision based on %s (v%s)') % (self.code, self.version),
                'date_approved': False,
                'is_latest_version': False,
                'view_count': 0,
                'download_count': 0,
            }).with_user(self.env.user)
            # A reviewer must be able to open and edit the resulting draft.
            new_doc.check_access('read')
            new_doc.check_access('write')
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

    def _action_view_audit(self, action):
        self.ensure_one()
        self.check_access('read')
        return {
            'name': _('Document %s History - %s') % (action.title(), self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'kms.audit.log',
            'view_mode': 'list',
            'domain': [('document_id', '=', self.id), ('action', '=', action)],
        }

    def action_view_read_history(self):
        return self._action_view_audit('view')

    def action_view_download_history(self):
        return self._action_view_audit('download')

    def action_view_document(self):
        """Open an authorized PDF or safe text preview in the browser."""
        self.ensure_one()
        self.check_access('read')
        if not self.sudo().file_data:
            raise UserError(_('An attached file is required for viewing.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/kms/document/{self.id}/view',
            'target': 'new',
        }

    def action_preview_document(self):
        """Open the first PDF page for a smaller, watermarked preview."""
        self.ensure_one()
        self.check_access('read')
        if not self.is_pdf or not self.sudo().file_data:
            raise UserError(_('An attached PDF is required for first-page preview.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/kms/document/{self.id}/view?preview=1',
            'target': 'new',
        }

    def action_download_watermarked(self):
        """Action handler that triggers download through secure watermarked controller."""
        self.ensure_one()
        self.check_access('read')
        if not self.sudo().file_data:
            raise UserError(_('No file is attached to this document.'))

        # Check view-only security
        if self.is_view_only and not self.env.user.has_group('knowledge_management.group_kms_manager'):
            raise AccessError(_('This document is marked as Strict View-Only. Downloading is prohibited by policy.'))

        # Check role-based download permissions (FR-KMS-014)
        if self.allowed_download_group_ids:
            user_groups = self.env.user.group_ids
            if not any(g in user_groups for g in self.allowed_download_group_ids) and not self.env.user.has_group('knowledge_management.group_kms_manager'):
                raise AccessError(_('Your assigned role does not have download permissions for this document.'))

        return {
            'type': 'ir.actions.act_url',
            'url': f'/kms/document/{self.id}/download',
            'target': 'self',
        }

    def _log_audit_action(self, action_type, details=None, strict=False):
        for rec in self:
            try:
                self.env['kms.audit.log']._log_audit_event(
                    action=action_type, document_id=rec.id,
                    resource_type='document',
                    resource_name=f"{rec.code} - {rec.name} (v{rec.version})",
                    details=details or f"Action {action_type} performed",
                )
            except Exception as e:
                _logger.warning("Could not log KMS audit entry: %s", e)
                if strict:
                    raise

    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS kms_document_fts_gin_idx ON kms_document 
            USING gin(to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, '')));
        """)

    def _search_fts(self, operator, value):
        if not value or not isinstance(value, str):
            return []
        query = value.strip()
        if not query:
            return []
        # A capped ID list cannot correctly implement a negative search:
        # matches beyond the cap would be returned as false negatives.
        if operator in ('not in', '!=', 'not like', 'not ilike'):
            raise UserError(_('Negated full-text search is not supported.'))
        visible_ids = []
        offset = 0
        page_size = 200
        query_fn = 'websearch_to_tsquery'
        while len(visible_ids) < 2000 and offset < 5000:
            sql = """
                SELECT id FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ {query_fn}('english', %s)
                ORDER BY id DESC LIMIT %s OFFSET %s
            """
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute(sql.format(query_fn=query_fn), (query, page_size, offset))
                    page = [row[0] for row in self.env.cr.fetchall()]
            except Exception:
                if query_fn != 'websearch_to_tsquery':
                    raise
                query_fn = 'plainto_tsquery'
                offset = 0
                visible_ids = []
                continue
            if not page:
                break
            readable = set(self.search([('id', 'in', page)]).ids)
            visible_ids.extend(doc_id for doc_id in page if doc_id in readable)
            offset += len(page)
            if len(page) < page_size:
                break
        return [('id', 'in', visible_ids[:2000])]

    @api.model
    def _search_fulltext(self, query, extra_domain=None, limit=80):
        """
        FR-KMS-006: Ranked full-text search across Title, Summary, and Content using tsvector and GIN index.
        Returns recordset ordered by ts_rank DESC.
        """
        limit = max(1, min(int(limit or 80), 500))
        if not query or not str(query).strip():
            return self.search(extra_domain or [], limit=limit)
        q = str(query).strip()
        # Apply ORM record rules on each bounded page. Limiting the SQL before
        # access checks could hide an employee's permitted results behind rows
        # they cannot read.
        ranked_ids = []
        offset = 0
        page_size = 200
        while len(ranked_ids) < limit and offset < 5000:
            sql = """
                SELECT id FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ {tsquery}('english', %s)
                ORDER BY ts_rank(
                    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, '')),
                    {tsquery}('english', %s)
                ) DESC, id DESC
                LIMIT %s OFFSET %s
            """
            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute(sql.format(tsquery='websearch_to_tsquery'), (q, q, page_size, offset))
                    rows = self.env.cr.fetchall()
            except Exception:
                self.env.cr.execute(sql.format(tsquery='plainto_tsquery'), (q, q, page_size, offset))
                rows = self.env.cr.fetchall()
            ids = [row[0] for row in rows]
            if not ids:
                break
            domain = [('id', 'in', ids)] + list(extra_domain or [])
            readable = set(self.search(domain).ids)
            ranked_ids.extend(doc_id for doc_id in ids if doc_id in readable)
            offset += len(ids)
            if len(ids) < page_size:
                break
        return self.browse(ranked_ids[:limit])
