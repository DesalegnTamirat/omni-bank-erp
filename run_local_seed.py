# -*- coding: utf-8 -*-
import sys
import odoo
from odoo.modules.registry import Registry

odoo.tools.config.parse_config([
    '--db_host=db',
    '--db_user=odoo',
    '--db_password=odoo',
    '--db_port=5432',
    '-d', 'ERP',
    '--no-http'
])

reg = Registry('ERP')
with reg.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    with open('/tmp/seed_eds_pms_test_data.py', 'r', encoding='utf-8') as f:
        code = f.read()
    exec(code, {'env': env, 'odoo': odoo})
