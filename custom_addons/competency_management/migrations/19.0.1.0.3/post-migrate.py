"""Remove access rights for the now-abstract data validator."""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    access = env.ref(
        'competency_management.access_competency_data_validator_admin',
        raise_if_not_found=False,
    )
    if access:
        access.unlink()
