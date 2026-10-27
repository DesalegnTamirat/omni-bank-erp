"""Start the safe nightly LMS reconciliation on existing EDS databases."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('employee_development_system.cron_eds_lms_sync', raise_if_not_found=False)
    if cron:
        cron.write({'active': True})
