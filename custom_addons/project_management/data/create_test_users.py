import odoo
from odoo.modules.registry import Registry
from odoo.exceptions import AccessError
from datetime import date, timedelta

odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'pm_db'])
registry = Registry('pm_db')

with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    group_internal = env.ref('base.group_user')
    group_user = env.ref('project_management.group_pm_user')
    group_coordinator = env.ref('project_management.group_pm_coordinator')
    group_manager = env.ref('project_management.group_pm_manager')
    
    # Helper to create/update user
    def get_or_create_user(name, login, groups):
        u = env['res.users'].search([('login', '=', login)], limit=1)
        if not u:
            u = env['res.users'].create({
                'name': name,
                'login': login,
                'email': login,
                'password': 'admin',
                'group_ids': [(6, 0, [g.id for g in groups])],
            })
            print(f"Created user {name} ({login})")
        else:
            u.write({
                'name': name,
                'password': 'admin',
                'group_ids': [(6, 0, [g.id for g in groups])],
            })
            print(f"Updated user {name} ({login})")
        return u

    # 1. Create Role Users
    pm = get_or_create_user('Sarah Jenkins (Project Manager)', 'manager@project.com', [group_internal, group_user, group_coordinator, group_manager])
    pc = get_or_create_user('Alex Rivera (Project Coordinator)', 'coordinator@project.com', [group_internal, group_user, group_coordinator])
    m1 = get_or_create_user('Dawit Tadesse (Senior Developer)', 'member1@project.com', [group_internal, group_user])
    m2 = get_or_create_user('Bethlehem Haile (QA Engineer)', 'member2@project.com', [group_internal, group_user])

    # 2. Update Projects and Tasks assignments
    p1 = env['pm.project'].search([('name', '=', 'ERP Upgrade and Enhancement Project')], limit=1)
    if p1:
        p1.write({
            'manager_id': pm.id,
            'coordinator_id': pc.id,
            'member_ids': [(6, 0, [m1.id, m2.id])],
        })
        print("Updated ERP Project with Manager, Coordinator, and Team Members.")

    t1 = env['pm.task'].search([('name', '=', 'HR Domain Module Design, Customization, and Configuration (Phase I)')], limit=1)
    if t1:
        t1.write({
            'user_ids': [(6, 0, [m1.id])],
        })
        print("Assigned Task 1 to Dawit Tadesse (member1).")

    t2 = env['pm.task'].search([('name', '=', 'Data Migration and Production Readiness Phase I')], limit=1)
    if t2:
        t2.write({
            'user_ids': [(6, 0, [m2.id])],
        })
        print("Assigned Task 2 to Bethlehem Haile (member2).")

    cr.commit()
    print("All test users and sample task assignments committed!")

# 3. Security Record Rule Verification
with registry.cursor() as cr:
    # Test 1: Member 1 editing own assigned task (Task 1)
    env_m1 = odoo.api.Environment(cr, m1.id, {})
    task1_as_m1 = env_m1['pm.task'].browse(t1.id)
    task1_as_m1.write({'progress_rate': 60.0})
    print("PASS: Dawit Tadesse (member1) successfully updated progress on his own assigned Task 1.")

    # Test 2: Member 1 attempting to edit Member 2's task (Task 2) -> MUST BE BLOCKED
    try:
        task2_as_m1 = env_m1['pm.task'].browse(t2.id)
        task2_as_m1.write({'progress_rate': 99.0})
        print("FAIL: Security rule did not block Dawit from editing Bethlehem's task!")
    except AccessError as e:
        print("PASS: Security rule successfully blocked Dawit from editing Bethlehem's task (AccessError caught).")

    # Test 3: Project Manager editing any task
    env_pm = odoo.api.Environment(cr, pm.id, {})
    task2_as_pm = env_pm['pm.task'].browse(t2.id)
    task2_as_pm.write({'allocated_hours': 95.0})
    print("PASS: Sarah Jenkins (Project Manager) can edit and govern any task.")
