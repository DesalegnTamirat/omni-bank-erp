"""Currency rules for EDS training delivery costs.

The currency is selected for a program, never for each expense item.  The
rules intentionally use ETB rather than the user's company currency because
EDS local training is denominated in Ethiopian birr.
"""

from odoo.exceptions import UserError, ValidationError


def currency_for_delivery(env, delivery_method):
    code = 'USD' if delivery_method == 'international' else 'ETB'
    currency = env['res.currency'].with_context(active_test=False).search(
        [('name', '=', code)], limit=1)
    if not currency:
        raise UserError('%s currency must be configured before entering training costs.' % code)
    return currency


def validate_delivery_currency(env, delivery_method, currency_id):
    currency = env['res.currency'].browse(currency_id).exists()
    if not currency:
        raise ValidationError('Select a valid currency for this training cost.')
    if delivery_method != 'international' and currency.name != 'ETB':
        raise ValidationError(
            'Internal and local external training must use ETB. '
            'Select International to use another currency.')
    return currency
