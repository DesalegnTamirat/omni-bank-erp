"""Normalize legacy local provider location and zero-valued currency records."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    etb = env['res.currency'].with_context(active_test=False).search(
        [('name', '=', 'ETB')], limit=1)
    if not etb:
        return
    providers = env['eds.external.provider'].search([('category', '=', 'local')])
    for provider in providers:
        values = {}
        if provider.country_id:
            values['country_id'] = False
        # Changing the currency on a priced record would change its meaning.
        if not provider.rate_per_session and provider.currency_id != etb:
            values['currency_id'] = etb.id
        if values:
            provider.write(values)
