from . import controllers
from . import models
from . import wizards


def post_init_hook(env):
    """Automatically sync operating unit helpdesk teams after installation."""
    try:
        env["operating.unit"].sync_all_employee_operating_units()
    except Exception:
        pass

