import sys
sys.path.insert(0, 'd:/projects/odoo19/source/odoo')
import odoo
from odoo.modules.registry import Registry
from odoo import api, SUPERUSER_ID
from odoo.osv import expression

odoo.tools.config.parse_config(['-c', 'd:/projects/odoo19/config/odoo.conf'])
registry = Registry('odoo_dev')
with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    rules = env['ir.rule'].search([('model_id.model', '=', 'helpdesk.ticket')])
    user = env['res.users'].browse(9)
    print('User 9:', user.name)
    print('User 9 helpdesk_team_ids:', user.helpdesk_team_ids.ids)
    
    t = env['helpdesk.ticket'].browse(121)
    print('Ticket 121 fields:')
    print('  user_id:', t.user_id.id if t.user_id else None)
    print('  create_uid:', t.create_uid.id)
    print('  team_id:', t.team_id.id if t.team_id else None)
    print('  partner_id:', t.partner_id.id if t.partner_id else None)
    print('  message_partner_ids:', t.message_partner_ids.ids)

    print('\nTesting each rule individually for user 9 on ticket 121:')
    for r in rules:
        user_matches_group = False
        if not r.groups:
            user_matches_group = True
        else:
            for g in r.groups:
                if g in user.group_ids:
                    user_matches_group = True
                    break
        if user_matches_group:
            is_global = getattr(r, 'global')
            print(f"\nRule: '{r.name}' (id={r.id}, global={is_global})")
            print(f"  Domain: {r.domain_force}")
            try:
                dom = expression.normalize_domain(eval(r.domain_force, {
                    'user': user,
                    'company_ids': [user.company_id.id],
                }))
                res = env['helpdesk.ticket'].search([('id', '=', 121)] + dom)
                print(f"  Matches ticket 121? {bool(res)}")
            except Exception as e:
                print('  Eval error:', e)

    print('\nTotal search for ticket 121 with user 9 context:')
    try:
        t_user = env['helpdesk.ticket'].with_user(user).search([('id', '=', 121)])
        print('User 9 CAN see ticket 121:', bool(t_user))
    except Exception as e:
        print('User 9 search failed:', e)
