# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AuditConfig(models.Model):
    _name = 'audit.config'
    _description = 'Audit Trail Configuration'

    name = fields.Char(string="Configuration Name", default="Audit Trail Configuration", required=True)
    audit_trail_enabled = fields.Boolean(
        string="Enable Audit Trail Logging",
        default=True,
        help="Master toggle switch for Audit Trail tracking. When enabled, configured business models are logged. "
             "When disabled, all audit logging activities stop immediately to conserve system resources."
    )

    @api.model
    def get_config(self):
        config = self.search([], limit=1)
        if not config:
            enabled_param = self.env['ir.config_parameter'].sudo().get_param('audit_trail.enabled', 'True')
            is_enabled = str(enabled_param).strip().lower() not in ('false', '0', 'off', 'no')
            config = self.sudo().create({
                'name': 'Audit Trail Configuration',
                'audit_trail_enabled': is_enabled
            })
        return config

    def write(self, vals):
        res = super().write(vals)
        if 'audit_trail_enabled' in vals:
            for rec in self:
                enabled = rec.audit_trail_enabled
                self.env['ir.config_parameter'].sudo().set_param(
                    'audit_trail.enabled', str(enabled)
                )
                if enabled:
                    self.env['audit.rule'].sudo()._sync_models_internal()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            enabled = rec.audit_trail_enabled
            self.env['ir.config_parameter'].sudo().set_param(
                'audit_trail.enabled', str(enabled)
            )
            if enabled:
                self.env['audit.rule'].sudo()._sync_models_internal()
        return records

    def action_sync_models(self):
        return self.env['audit.rule'].action_sync_models()

    @api.model
    def action_open_audit_config(self):
        """Always opens the single dedicated Audit Trail Configuration form."""
        config = self.get_config()
        return {
            'name': _('Audit Trail Configuration'),
            'type': 'ir.actions.act_window',
            'res_model': 'audit.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }
