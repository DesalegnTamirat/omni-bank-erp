# -*- coding: utf-8 -*-
import base64
import logging
from markupsafe import Markup, escape
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
    classification = fields.Selection([
        ('public', 'Public'),
        ('internal', 'Internal'),
        ('confidential', 'Confidential'),
        ('restricted', 'Restricted'),
    ], string='Security Classification Scope', compute='_compute_classification', store=True, readonly=False)
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
    file_data = fields.Binary(string='Document File', attachment=True)
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
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('kms.document') or _('New')
        records = super(KmsDocument, self).create(vals_list)
        for rec in records:
            rec._log_audit_action('upload', 'Document created in Draft')
        return records

    def write(self, vals):
        if 'state' in vals and vals['state'] in ('approved', 'published', 'archived'):
            if not self.env.user.has_group('knowledge_management.group_kms_manager') and not self.env.su:
                raise AccessError(_("Only KMS Managers can publish or archive documents."))
        return super(KmsDocument, self).write(vals)

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

    @api.depends('classification_id', 'classification_id.code')
    def _compute_classification(self):
        code_map = {
            'PUB': 'public', 'public': 'public',
            'INT': 'internal', 'internal': 'internal',
            'CONF': 'confidential', 'confidential': 'confidential',
            'SCONF': 'restricted', 'restricted': 'restricted',
        }
        for rec in self:
            if rec.classification_id and rec.classification_id.code:
                rec.classification = code_map.get(rec.classification_id.code, 'internal')
            elif not rec.classification:
                rec.classification = 'internal'

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
            code_map = {'PUB': 'public', 'INT': 'internal', 'CONF': 'confidential', 'SCONF': 'restricted'}
            self.classification = code_map.get(self.classification_id.code, 'internal')
            if getattr(self.classification_id, 'view_only_default', False):
                self.is_view_only = True
            if getattr(self.classification_id, 'watermark_mandatory', False):
                self.require_watermark = True

    # Lifecycle Actions
    def action_submit_for_review(self):
        for rec in self:
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
            reviewer_emp = rec.reviewer_id or rec.approver_id
            if reviewer_emp and reviewer_emp.work_contact_id:
                partner_ids.append(reviewer_emp.work_contact_id.id)
            rec.message_post(body=body, partner_ids=partner_ids)
            rec._log_audit_action('modify', 'Submitted for review')
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
            rec._log_audit_action('approve', f'Approved version {rec.version}')
            # Award points to content owner
            if owner and owner.user_id:
                self.env['kms.contributor.point'].award_points(
                    owner.user_id,
                    points=20,
                    source='document_publish',
                    description=f'Published approved document: {rec.name} ({rec.code})'
                )

    def action_reject(self):
        for rec in self:
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
            user_groups = self.env.user.group_ids
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
        try:
            self.env.cr.execute("""
                SELECT id FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ websearch_to_tsquery('english', %s)
            """, (query,))
            ids = [r[0] for r in self.env.cr.fetchall()]
        except Exception:
            self.env.cr.execute("""
                SELECT id FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ plainto_tsquery('english', %s)
            """, (query,))
            ids = [r[0] for r in self.env.cr.fetchall()]
        if operator in ('not in', '!=', 'not like', 'not ilike'):
            return [('id', 'not in', ids)]
        return [('id', 'in', ids)]

    @api.model
    def _search_fulltext(self, query, extra_domain=None, limit=80):
        """
        FR-KMS-006: Ranked full-text search across Title, Summary, and Content using tsvector and GIN index.
        Returns recordset ordered by ts_rank DESC.
        """
        if not query or not str(query).strip():
            return self.search(extra_domain or [], limit=limit)
        q = str(query).strip()
        try:
            sql = """
                SELECT id, ts_rank(
                    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, '')),
                    websearch_to_tsquery('english', %s)
                ) AS rank
                FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ websearch_to_tsquery('english', %s)
                ORDER BY rank DESC, id DESC
                LIMIT %s
            """
            self.env.cr.execute(sql, (q, q, limit))
            rows = self.env.cr.fetchall()
        except Exception:
            sql_fallback = """
                SELECT id, ts_rank(
                    to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, '')),
                    plainto_tsquery('english', %s)
                ) AS rank
                FROM kms_document
                WHERE to_tsvector('english', coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content_text, ''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC, id DESC
                LIMIT %s
            """
            self.env.cr.execute(sql_fallback, (q, q, limit))
            rows = self.env.cr.fetchall()

        ids = [r[0] for r in rows]
        if not ids:
            return self.browse()
        base_domain = [('id', 'in', ids)]
        if extra_domain:
            base_domain = ['&'] + base_domain + extra_domain
        records = self.search(base_domain)
        id_map = {rec.id: rec for rec in records}
        return self.browse([i for i in ids if i in id_map])
