from . import controllers
from . import models
from . import wizards
from odoo import api, SUPERUSER_ID

def _post_init_sync_photos(env):
    """Post-init hook executed automatically whenever module is installed/upgraded."""
    try:
        if hasattr(env, 'cr'):
            env['hr.employee'].sudo().action_sync_all_profile_photos()
        else:
            cr = env
            env_obj = api.Environment(cr, SUPERUSER_ID, {})
            env_obj['hr.employee'].sudo().action_sync_all_profile_photos()
    except Exception:
        pass

