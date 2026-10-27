import re

from odoo import fields, models, _
from odoo.exceptions import ValidationError


class EdsCurrencyQuickCreate(models.TransientModel):
    _name = 'eds.currency.quick.create'
    _description = 'Add a Currency for International Training'

    code = fields.Char(string='Currency Name / Code', required=True,
                       help='Enter a three-letter code such as EUR, GBP or AED.')

    def action_create_currency(self):
        self.ensure_one()
        code = (self.code or '').strip().upper()
        if not re.fullmatch(r'[A-Z]{3}', code):
            raise ValidationError(_('Enter a three-letter currency code, for example EUR or GBP.'))
        currency_model = self.env['res.currency'].sudo().with_context(active_test=False)
        currency = currency_model.search([('name', '=', code)], limit=1)
        if currency and not currency.active:
            currency.active = True
        elif not currency:
            currency = currency_model.create({
                'name': code,
                'symbol': code,
                'rounding': 0.01,
                'active': True,
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Currency Available'),
                'message': _('%s is available. Select it on the international training record.') % code,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
