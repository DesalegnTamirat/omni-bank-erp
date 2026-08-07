import sys
sys.path.insert(0, r'F:\Odoo_Devs\odoo19')
import odoo
from odoo.api import Environment

odoo.tools.config.parse_config(['-c', 'odoo.conf'])
from odoo.modules.registry import Registry
registry = Registry('Odoo19')
with registry.cursor() as cr:
    env = Environment(cr, odoo.SUPERUSER_ID, {})
    
    # Get the rule from external ID
    try:
        rule = env.ref('custom_planning.rule_planning_work_unit_manpower_user')
        print("Rule Name:", rule.name)
        print("Rule Domain in DB:", rule.domain_force)
        
        # Let's update the rule domain directly in DB to match what we need:
        new_domain = "['|', '|', ('work_unit_id', '=', user.employee_id.default_operating_unit_id.id), ('create_uid', '=', user.id), ('approver_id.user_id', '=', user.id)]"
        if rule.domain_force != new_domain:
            print("Updating rule domain in DB...")
            rule.write({'domain_force': new_domain})
            cr.commit()
            print("DB updated and committed successfully!")
            
            # Re-read
            print("New Domain in DB:", rule.domain_force)
        else:
            print("Domain in DB already matches!")
    except Exception as e:
        print("Error getting rule:", str(e))
