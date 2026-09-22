# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KmsAuditLog(models.Model):
    """
    Non-Editable KMS Activity Audit Log (FR-KMS-017, FR-KMS-022, FR-KMS-023).
    Captures complete immutable history of views, downloads, uploads, approvals, and modifications
    for compliance, internal audit, and regulatory inspection.
    """
    _name = 'kms.audit.log'
    _description = 'KMS Activity Audit Record'
    _order = 'create_date desc'
    _rec_name = 'action'

    user_id = fields.Many2one('res.users', string='User', required=True, readonly=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Staff Member', readonly=True, index=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Branch / Unit', readonly=True)

    action = fields.Selection([
        ('view', 'Document / Resource Viewed'),
        ('download', 'Document / Resource Downloaded'),
        ('upload', 'New Resource Uploaded / Created'),
        ('modify', 'Resource Modified / Updated'),
        ('approve', 'Resource Approved / Validated'),
        ('archive', 'Resource Archived'),
        ('access_denied', 'Access / Download Attempt Denied'),
        ('join', 'Joined Community'),
        ('leave', 'Left Community'),
    ], string='Action Taken', required=True, readonly=True, index=True)

    resource_type = fields.Selection([
        ('document', 'Governed Policy / SOP'),
        ('digital_library', 'Digital Library Asset'),
        ('cop', 'Community of Practice'),
        ('forum', 'Knowledge Forum / Q&A'),
        ('lesson_learned', 'Lesson Learned'),
        ('tacit_session', 'Knowledge Capture Session'),
    ], string='Asset Type', default='document', readonly=True, index=True)

    document_id = fields.Many2one('kms.document', string='Governed Document Reference', readonly=True, ondelete='set null')
    resource_name = fields.Char(string='Resource Name / Code', readonly=True)
    details = fields.Text(string='Event Audit Trail & Metadata', readonly=True)
    create_date = fields.Datetime(string='Timestamp', readonly=True, index=True)

    @api.model
    def log_audit_event(self, action, resource_type, resource_name, details='', doc_id=False, user=None):
        """Unified logging method for bank-wide audit compliance (BRD 7.3, NFR-KMS-001)."""
        user = user or self.env.user
        emp = user.employee_id
        return self.sudo().create({
            'user_id': user.id,
            'employee_id': emp.id if emp else False,
            'department_id': emp.department_id.id if emp and emp.department_id else False,
            'operating_unit_id': emp.default_operating_unit_id.id if emp and emp.default_operating_unit_id else False,
            'action': action,
            'resource_type': resource_type,
            'resource_name': resource_name,
            'details': details or f"Action {action} performed on {resource_name}",
            'document_id': doc_id,
        })

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('user_id'):
                vals['user_id'] = self.env.user.id
            if not vals.get('employee_id'):
                emp = self.env.user.employee_id
                if emp:
                    vals['employee_id'] = emp.id
                    vals['department_id'] = emp.department_id.id if emp.department_id else False
                    vals['operating_unit_id'] = emp.default_operating_unit_id.id if emp.default_operating_unit_id else False
        return super(KmsAuditLog, self).create(vals_list)

    def write(self, vals):
        """Immutable security constraint: Audit records can never be altered."""
        raise UserError(_('Compliance Guard: KMS Audit Trail records are immutable and cannot be modified.'))

    def unlink(self):
        """Immutable security constraint: Audit records can never be deleted."""
        raise UserError(_('Compliance Guard: KMS Audit Trail records are permanent and cannot be deleted.'))
