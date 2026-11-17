"""Explicit, audited provider changes for confirmed training sessions."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsSessionProviderChange(models.Model):
    _inherit = 'eds.session'

    change_provider = fields.Boolean(
        string='Change Provider', copy=False,
        help='Enable this to choose a replacement for the current training provider.')
    new_provider_id = fields.Many2one(
        'eds.external.provider', string='New Training Provider', copy=False,
        help='Only providers awarded for this session’s approved program can replace the current provider.')
    new_provider_reason = fields.Text(
        string='Reason and Justification', copy=False,
        help='Explain why the provider is changing. The previous and new provider and this explanation are retained in the session chatter.')

    @api.onchange('change_provider')
    def _onchange_change_provider(self):
        for session in self:
            session.new_provider_id = False
            session.new_provider_reason = False

    @api.constrains('change_provider', 'new_provider_id', 'new_provider_reason',
                    'awarded_provider_id', 'status', 'delivery_method')
    def _check_provider_change_request(self):
        for session in self.filtered('change_provider'):
            if session.status not in ('scheduled', 'ongoing', 'rescheduled'):
                raise ValidationError(_(
                    'A provider can be changed only on a scheduled, ongoing, or rescheduled session.'))
            if session.delivery_method == 'internal':
                raise ValidationError(_(
                    'Internal training does not have an external provider to replace.'))
            if not session.new_provider_id or session.new_provider_id == session.awarded_provider_id:
                raise ValidationError(_(
                    'Choose a new provider different from the current provider.'))
            if not (session.new_provider_reason or '').strip():
                raise ValidationError(_('Enter the reason and justification for changing provider.'))

    def action_apply_provider_change(self):
        """Use the existing award, trainer, notification, and audit validations."""
        self.ensure_one()
        if not self.change_provider:
            raise UserError(_('Select Change Provider first.'))
        self._check_provider_change_request()
        reason = self.new_provider_reason.strip()
        self.write({
            'awarded_provider_id': self.new_provider_id.id,
            'provider_change_reason': reason,
            'change_provider': False,
            'new_provider_id': False,
            'new_provider_reason': False,
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}
