"""Remove the retired trainer reminder job and normalize local venues."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    reminder = env.ref(
        'employee_development_system.cron_eds_trainer_review_reminder',
        raise_if_not_found=False)
    if reminder:
        reminder.unlink()
    venues = env['eds.venue'].search([
        ('location_scope', '=', 'local'), ('country_id', '!=', False),
    ])
    venues.write({'country_id': False})
