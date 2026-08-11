import odoo
from odoo.tools import config
config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'odoo19'])

from odoo.modules.registry import Registry
from odoo.api import Environment

db_name = 'odoo19'
registry = Registry(db_name)
with registry.cursor() as cr:
    env = Environment(cr, odoo.SUPERUSER_ID, {})
    
    target_models = ['hr.version', 'employee.education', 'operating.unit', 'discipline.case', 'discipline.offense', 'hr.applicant', 'employee.grade', 'hr.job']
    for tm in target_models:
        if tm in env:
            print(f"\n=== MODEL {tm} FIELDS ===")
            for fn, fo in sorted(env[tm]._fields.items()):
                print(f"  {fn}: {fo.type} (req={getattr(fo, 'required', False)})")
        else:
            print(f"\nModel {tm} NOT in env!")
