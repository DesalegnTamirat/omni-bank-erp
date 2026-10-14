from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Give existing internal trainer profiles the read-only trainer badge."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['eds.trainer'].search([
        ('trainer_type', '=', 'internal'),
        ('state', '=', 'active'),
        ('employee_id.user_id', '!=', False),
    ])._grant_employee_trainer_role()
