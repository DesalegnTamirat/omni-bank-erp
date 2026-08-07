# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError


class AuditLog(models.Model):
    """
    CBS-style Audit Log Table.
    One row per field change (write) or one row per record (create/unlink).
    """
    _name = 'audit.log'
    _description = 'Audit Log'
    _order = 'create_date desc'
    _rec_name = 'display_name_computed'

    # ── What was changed ──────────────────────────────────────────────────
    module = fields.Char(
        string='Module', index=True,
        help='Odoo module that owns the changed model'
    )
    model_id = fields.Many2one(
        'ir.model', string='Model', ondelete='set null', index=True
    )
    model_name = fields.Char(string='Model (Technical)', index=True)
    model_description = fields.Char(string='Model Label')
    res_id = fields.Integer(string='Record ID', index=True)
    res_name = fields.Char(string='Record Name')

    # ── What operation ────────────────────────────────────────────────────
    operation = fields.Selection([
        ('create', 'Create'),
        ('write',  'Write / Update'),
        ('unlink', 'Delete'),
    ], string='Operation', required=True, index=True)

    # ── Field-level detail (for write operations) ─────────────────────────
    field_id = fields.Many2one(
        'ir.model.fields', string='Field', ondelete='set null'
    )
    field_name        = fields.Char(string='Field (Technical)')
    field_description = fields.Char(string='Field Label')
    field_type        = fields.Char(string='Field Type')
    old_value         = fields.Text(string='Old Value')
    new_value         = fields.Text(string='New Value')

    # ── Who / When / Where ────────────────────────────────────────────────
    user_id = fields.Many2one(
        'res.users', string='User', ondelete='set null', index=True
    )
    user_name  = fields.Char(string='User Name')
    user_login = fields.Char(string='User Login')
    ip_address = fields.Char(string='IP Address')
    create_date = fields.Datetime(
        string='Date & Time', readonly=True, index=True
    )

    # ── Computed display ──────────────────────────────────────────────────
    display_name_computed = fields.Char(
        string='Display Name', compute='_compute_display_name_field', store=False
    )

    @api.depends('operation', 'model_description', 'res_name', 'field_description')
    def _compute_display_name_field(self):
        for log in self:
            parts = [log.operation.upper(), log.model_description or log.model_name]
            if log.res_name:
                parts.append(f'"{log.res_name}"')
            if log.field_description and log.operation == 'write':
                parts.append(f'[{log.field_description}]')
            log.display_name_computed = ' / '.join(parts)

    # ── Prevent any modification of audit logs ────────────────────────────
    def write(self, vals):
        raise ValidationError(
            _('Audit logs are immutable and cannot be modified.')
        )

    def unlink(self):
        # Allow only audit managers to delete logs (for retention/archival)
        if not self.env.user.has_group('audit_trail.group_audit_manager'):
            raise ValidationError(
                _('Only Audit Managers can delete audit log entries.')
            )
        return super().unlink()

    # ── Utility: bulk create (bypass ORM overhead) ────────────────────────
    @api.model
    def sudo_create_log(self, vals_list):
        """
        Fast log creation that bypasses the write() protection above.
        Called internally from the ORM patch.
        """
        return super(AuditLog, self.sudo()).create(vals_list)
