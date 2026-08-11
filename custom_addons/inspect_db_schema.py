import odoo
from odoo.tools import config
config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'odoo19'])

from odoo.modules.registry import Registry
from odoo.api import Environment

db_name = 'odoo19'
registry = Registry(db_name)
with registry.cursor() as cr:
    env = Environment(cr, odoo.SUPERUSER_ID, {})
    print("=== INSTALLED MODULES ===")
    installed = env['ir.module.module'].search([('state', '=', 'installed')]).mapped('name')
    print("Installed modules count:", len(installed))
    for m in sorted(installed):
        if any(k in m for k in ['hr', 'recruitment', 'attendance', 'discipline', 'custom', 'unit', 'competency', 'planning']):
            print(" -", m)

    print("\n=== RELEVANT MODELS IN ENVIRONMENT ===")
    models = sorted(env.keys())
    relevant_models = [m for m in models if any(k in m for k in ['hr.', 'employee', 'version', 'contract', 'job', 'grade', 'education', 'experience', 'applicant', 'recruitment', 'discipline', 'attendance', 'operating'])]
    print("Relevant models found:", len(relevant_models))
    for rm in relevant_models:
        print("  *", rm)

    print("\n=== HR EMPLOYEE FIELDS ===")
    emp_fields = sorted(env['hr.employee']._fields.keys())
    print("hr.employee fields count:", len(emp_fields))
    for f in emp_fields:
        print(f"  - {f}: {env['hr.employee']._fields[f].type}")
