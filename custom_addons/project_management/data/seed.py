from datetime import date, timedelta

admin = env.ref('base.user_admin')

# 1. Initiative
initiative = env['pm.initiative'].search([('name', '=', 'Digital Banking Modernization 2026-2028')], limit=1)
if not initiative:
    initiative = env['pm.initiative'].create({
        'name': 'Digital Banking Modernization 2026-2028',
        'code': 'INIT-2026-01',
        'owner_id': admin.id,
        'date_start': date(2026, 1, 1),
        'date_end': date(2028, 12, 31),
        'state': 'in_progress',
        'objective': '<p>Comprehensive enterprise enhancement of core banking, customer onboarding, and API gateway services.</p>',
    })

# 2. Projects
p1 = env['pm.project'].search([('name', '=', 'ERP Upgrade and Enhancement Project')], limit=1)
if not p1:
    p1 = env['pm.project'].create({
        'name': 'ERP Upgrade and Enhancement Project',
        'code': 'PRJ-ERP-01',
        'initiative_id': initiative.id,
        'manager_id': admin.id,
        'tag_type': 'internal',
        'date_start': date(2026, 6, 15),
        'date_end': date(2027, 9, 30),
        'status': 'active',
        'priority': '2',
        'description': '<p>Core ERP upgrade including custom business logic and performance optimizations.</p>',
    })

p2 = env['pm.project'].search([('name', '=', 'Digital Customer Onboarding System')], limit=1)
if not p2:
    p2 = env['pm.project'].create({
        'name': 'Digital Customer Onboarding System',
        'code': 'PRJ-ONB-02',
        'initiative_id': initiative.id,
        'manager_id': admin.id,
        'tag_type': 'external',
        'date_start': date(2025, 6, 23),
        'date_end': date(2026, 5, 4),
        'status': 'active',
        'priority': '3',
        'description': '<p>Customer facing onboarding web portal and mobile responsive journey.</p>',
    })

# 3. Milestones
m1 = env['pm.milestone'].search([('name', '=', 'HR Domain Module Design & Customization (Phase I)')], limit=1)
if not m1:
    m1 = env['pm.milestone'].create({
        'name': 'HR Domain Module Design & Customization (Phase I)',
        'project_id': p1.id,
        'date_start': date(2026, 6, 15),
        'date_deadline': date(2026, 11, 30),
        'state': 'in_progress',
        'description': 'Deliver core custom domain specifications and configurations.',
    })

stage_todo = env.ref('project_management.stage_to_do')
stage_in_progress = env.ref('project_management.stage_in_progress')
tag_internal = env.ref('project_management.tag_internal')

# 4. Project Tasks
t1 = env['pm.task'].search([('name', '=', 'HR Domain Module Design, Customization, and Configuration (Phase I)')], limit=1)
if not t1:
    t1 = env['pm.task'].create({
        'name': 'HR Domain Module Design, Customization, and Configuration (Phase I)',
        'project_id': p1.id,
        'milestone_id': m1.id,
        'user_ids': [(4, admin.id)],
        'date_start': date(2026, 7, 1),
        'date_deadline': date(2026, 11, 30),
        'stage_id': stage_in_progress.id,
        'priority': '2',
        'allocated_hours': 120.0,
        'progress_rate': 45.0,
        'tag_ids': [(4, tag_internal.id)],
        'description': '<p>Design and implement custom attendance, leave, and discipline workflows.</p>',
    })
    env['pm.task.subtask'].create([
        {
            'name': 'Business Requirements Review & Approval',
            'task_id': t1.id,
            'is_done': True,
            'date_start': date(2026, 7, 1),
            'date_deadline': date(2026, 7, 15),
            'allocated_hours': 20.0,
        },
        {
            'name': 'Model Schema & Security Architecture Design',
            'task_id': t1.id,
            'is_done': True,
            'date_start': date(2026, 7, 16),
            'date_deadline': date(2026, 8, 10),
            'allocated_hours': 40.0,
        },
        {
            'name': 'UI Views & Controller Logic Implementation',
            'task_id': t1.id,
            'is_done': False,
            'date_start': date(2026, 8, 11),
            'date_deadline': date(2026, 10, 30),
            'allocated_hours': 60.0,
        }
    ])
    env['pm.task.progress.log'].create({
        'task_id': t1.id,
        'user_id': admin.id,
        'hours_spent': 15.0,
        'progress_percent': 45.0,
        'summary': 'Completed schema review and started view implementation.',
    })

t2 = env['pm.task'].search([('name', '=', 'Data Migration and Production Readiness Phase I')], limit=1)
if not t2:
    t2 = env['pm.task'].create({
        'name': 'Data Migration and Production Readiness Phase I',
        'project_id': p1.id,
        'milestone_id': m1.id,
        'user_ids': [(4, admin.id)],
        'date_start': date(2026, 10, 1),
        'date_deadline': date(2026, 11, 30),
        'stage_id': stage_todo.id,
        'priority': '1',
        'allocated_hours': 80.0,
        'blocked_by_ids': [(4, t1.id)],
    })

# 5. Non-Project Tasks
t_np = env['pm.task'].search([('name', '=', 'Server SSL Certificate & DNS Health Audit')], limit=1)
if not t_np:
    env['pm.task'].create({
        'name': 'Server SSL Certificate & DNS Health Audit',
        'is_project_task': False,
        'user_ids': [(4, admin.id)],
        'date_start': date.today(),
        'date_deadline': date.today() + timedelta(days=5),
        'stage_id': stage_in_progress.id,
        'priority': '2',
        'allocated_hours': 8.0,
        'progress_rate': 25.0,
        'description': '<p>Routine operational maintenance for production certificates and DNS lookup speed.</p>',
    })

env.cr.commit()
print("Sample seed data committed successfully!")
