import odoo
from odoo.modules.registry import Registry
from odoo.exceptions import UserError, ValidationError, AccessError
from datetime import date, timedelta

odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'pm_db'])
registry = Registry('pm_db')

test_results = []

def record_test(name, success, message=""):
    test_results.append({'name': name, 'success': success, 'message': message})
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {name} {('- ' + message) if message else ''}")

with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    # Pre-fetch users
    admin = env.ref('base.user_admin')
    pm = env['res.users'].search([('login', '=', 'manager@project.com')], limit=1)
    pc = env['res.users'].search([('login', '=', 'coordinator@project.com')], limit=1)
    m1 = env['res.users'].search([('login', '=', 'member1@project.com')], limit=1)
    m2 = env['res.users'].search([('login', '=', 'member2@project.com')], limit=1)

    stage_todo = env['pm.task.stage'].search([('name', '=ilike', 'To Do')], limit=1)
    stage_in_progress = env['pm.task.stage'].search([('name', '=ilike', 'In Progress')], limit=1)
    stage_in_review = env['pm.task.stage'].search([('name', '=ilike', 'In Review')], limit=1)
    stage_completed = env['pm.task.stage'].search([('is_closed', '=', True)], limit=1)

    print("\n========================================================")
    print("STARTING COMPLETE END-TO-END SYSTEM TEST SUITE")
    print("========================================================\n")

    # -----------------------------------------------------------
    # SCENARIO 1: Date & Timeline Constraints
    # -----------------------------------------------------------
    print("--- SCENARIO 1: Date & Timeline Constraints ---")
    
    # 1.1 Project End Date < Start Date
    try:
        env['pm.project'].create({
            'name': 'Invalid Date Project',
            'manager_id': pm.id,
            'date_start': date(2026, 10, 1),
            'date_end': date(2026, 9, 1),
        })
        record_test("1.1 Project End Date < Start Date", False, "Failed to block project with end date < start date")
    except ValidationError:
        record_test("1.1 Project End Date < Start Date", True, "Successfully blocked invalid project dates")

    # Create a valid test project
    test_project = env['pm.project'].create({
        'name': 'Comprehensive Test Project 2026',
        'manager_id': pm.id,
        'coordinator_id': pc.id,
        'member_ids': [(6, 0, [m1.id, m2.id])],
        'date_start': date(2026, 6, 1),
        'date_end': date(2026, 12, 31),
    })
    
    # 1.2 Milestone Deadline beyond Project End Date
    try:
        env['pm.milestone'].create({
            'name': 'Overdue Milestone',
            'project_id': test_project.id,
            'date_start': date(2026, 6, 1),
            'date_deadline': date(2027, 2, 1), # Beyond 2026-12-31
        })
        record_test("1.2 Milestone Beyond Project Scope", False, "Failed to block milestone exceeding project end date")
    except ValidationError:
        record_test("1.2 Milestone Beyond Project Scope", True, "Successfully blocked milestone exceeding project end date")

    # Create valid milestone
    test_milestone = env['pm.milestone'].create({
        'name': 'Test Phase I: Setup',
        'project_id': test_project.id,
        'date_start': date(2026, 6, 1),
        'date_deadline': date(2026, 8, 31),
    })

    # 1.3 Task Deadline beyond Project End Date
    try:
        env['pm.task'].create({
            'name': 'Exceeding Task',
            'project_id': test_project.id,
            'date_start': date(2026, 6, 1),
            'date_deadline': date(2027, 5, 1),
        })
        record_test("1.3 Task Beyond Project Scope", False, "Failed to block task exceeding project end date")
    except ValidationError:
        record_test("1.3 Task Beyond Project Scope", True, "Successfully blocked task exceeding project end date")

    # Create valid parent Task A
    task_a = env['pm.task'].create({
        'name': 'Task A: Foundation & Setup',
        'project_id': test_project.id,
        'milestone_id': test_milestone.id,
        'user_ids': [(6, 0, [m1.id])],
        'date_start': date(2026, 6, 1),
        'date_deadline': date(2026, 7, 15),
    })

    # 1.4 Subtask Deadline < Subtask Start Date
    try:
        env['pm.task.subtask'].create({
            'name': 'Inverted Subtask',
            'task_id': task_a.id,
            'date_start': date(2026, 6, 20),
            'date_deadline': date(2026, 6, 10),
        })
        record_test("1.4 Subtask Deadline < Start Date", False, "Failed to block inverted subtask dates")
    except ValidationError:
        record_test("1.4 Subtask Deadline < Start Date", True, "Successfully blocked inverted subtask dates")

    # 1.5 Subtask Deadline beyond Task Deadline
    try:
        env['pm.task.subtask'].create({
            'name': 'Exceeding Subtask',
            'task_id': task_a.id,
            'date_start': date(2026, 6, 1),
            'date_deadline': date(2026, 8, 1), # Beyond task deadline 2026-07-15
        })
        record_test("1.5 Subtask Exceeding Task Deadline", False, "Failed to block subtask exceeding parent deadline")
    except ValidationError:
        record_test("1.5 Subtask Exceeding Task Deadline", True, "Successfully blocked subtask exceeding parent deadline")

    # -----------------------------------------------------------
    # SCENARIO 2: Allocated Hours Sync & Auto-Rollup
    # -----------------------------------------------------------
    print("\n--- SCENARIO 2: Allocated Hours Sync & Auto-Rollup ---")
    
    sub1 = env['pm.task.subtask'].create({
        'name': 'Subtask A1',
        'task_id': task_a.id,
        'user_ids': [(6, 0, [m1.id])],
        'date_start': date(2026, 6, 1),
        'date_deadline': date(2026, 6, 15),
        'allocated_hours': 25.0,
    })
    sub2 = env['pm.task.subtask'].create({
        'name': 'Subtask A2',
        'task_id': task_a.id,
        'user_ids': [(6, 0, [m1.id])],
        'date_start': date(2026, 6, 16),
        'date_deadline': date(2026, 7, 15),
        'allocated_hours': 35.0,
    })
    
    task_a._compute_allocated_hours()
    record_test("2.1 Task Allocated Hours Auto-Sum from Subtasks", task_a.allocated_hours == 60.0, f"Expected 60.0h, got {task_a.allocated_hours}h")

    # -----------------------------------------------------------
    # SCENARIO 3: Dependency Blocking & Guarded Stage Progression
    # -----------------------------------------------------------
    print("\n--- SCENARIO 3: Dependency Blocking & Guarded Stage Progression ---")
    
    task_b = env['pm.task'].create({
        'name': 'Task B: Dependent Feature Development',
        'project_id': test_project.id,
        'milestone_id': test_milestone.id,
        'user_ids': [(6, 0, [m2.id])],
        'date_start': date(2026, 7, 16),
        'date_deadline': date(2026, 8, 31),
        'allocated_hours': 40.0,
        'blocked_by_ids': [(6, 0, [task_a.id])],
    })
    
    task_b._compute_is_blocked()
    record_test("3.1 Task B is_blocked when Task A is not closed", task_b.is_blocked, "Task B is blocked by Task A")

    # Attempt to start work on Task B while blocked -> Must raise UserError
    try:
        task_b.action_start_work()
        record_test("3.2 Block Starting Work on Blocked Task", False, "Allowed starting work on blocked task")
    except UserError:
        record_test("3.2 Block Starting Work on Blocked Task", True, "Successfully blocked starting work on dependent task")

    # -----------------------------------------------------------
    # SCENARIO 4: Subtask Execution & Stage Workflow Progression
    # -----------------------------------------------------------
    print("\n--- SCENARIO 4: Subtask Execution & Stage Workflow Progression ---")
    
    # Member 1 starts work on Task A
    task_a.action_start_work()
    record_test("4.1 Action 'Start Work' moves to In Progress", task_a.stage_id.id == stage_in_progress.id, f"Stage is {task_a.stage_id.name}")

    # Complete subtasks on Task A
    sub1.write({'is_done': True})
    task_a._compute_progress_rate()
    record_test("4.2 Progress % updates on Subtask completion (50%)", task_a.progress_rate == 50.0, f"Progress is {task_a.progress_rate}%")

    sub2.write({'is_done': True})
    task_a._compute_progress_rate()
    record_test("4.3 Progress % updates to 100% when all subtasks done", task_a.progress_rate == 100.0, f"Progress is {task_a.progress_rate}%")

    # Member 1 submits Task A for review
    task_a.action_submit_review()
    record_test("4.4 Action 'Submit for Review' moves to In Review", task_a.stage_id.id == stage_in_review.id, f"Stage is {task_a.stage_id.name}")

    # Manager approves Task A
    task_a.action_approve_complete()
    record_test("4.5 Action 'Approve & Complete' moves to Completed", task_a.is_closed, f"Task A is closed: {task_a.is_closed}")

    # Verify Task B is automatically unblocked now
    task_b._compute_is_blocked()
    record_test("4.6 Task B automatically UNBLOCKS after Task A completes", not task_b.is_blocked, f"Task B is_blocked={task_b.is_blocked}")

    # Now Task B can start work
    task_b.action_start_work()
    record_test("4.7 Task B can now start work", task_b.stage_id.id == stage_in_progress.id, f"Task B stage is {task_b.stage_id.name}")

    # Complete Task B
    task_b.action_approve_complete()
    record_test("4.8 Task B completed", task_b.is_closed, "Task B closed")

    # -----------------------------------------------------------
    # SCENARIO 5: Hierarchy Lifecycle Auto-Rollup (Milestone & Project)
    # -----------------------------------------------------------
    print("\n--- SCENARIO 5: Hierarchy Lifecycle Auto-Rollup ---")
    
    test_milestone._compute_task_stats()
    test_milestone._compute_milestone_state()
    record_test("5.1 Milestone automatically transitions to Completed (100%)", test_milestone.state == 'completed' and test_milestone.progress_rate == 100.0, f"Milestone state={test_milestone.state}, progress={test_milestone.progress_rate}%")

    test_project._compute_task_stats()
    test_project._compute_project_status()
    test_project._compute_health_state()
    record_test("5.2 Project automatically transitions to Completed (100%)", test_project.status == 'completed' and test_project.progress_rate == 100.0, f"Project status={test_project.status}, progress={test_project.progress_rate}%")

    # -----------------------------------------------------------
    # SCENARIO 6: Security & Role-Based Record Rules
    # -----------------------------------------------------------
    print("\n--- SCENARIO 6: Security & Role-Based Record Rules ---")
    
    cr.commit()

# Test with Member context in separate cursor
with registry.cursor() as cr:
    # 6.1 Member 1 editing Member 2's task -> Must raise AccessError
    env_m1 = odoo.api.Environment(cr, m1.id, {})
    try:
        t_b_m1 = env_m1['pm.task'].browse(task_b.id)
        t_b_m1.write({'name': 'Tampered by Member 1'})
        record_test("6.1 Member blocked from editing other members tasks", False, "Failed to block member editing colleague task")
    except AccessError:
        record_test("6.1 Member blocked from editing other members tasks", True, "AccessError caught: Member cannot edit colleague task")

    # 6.2 Manager can edit any task
    env_pm = odoo.api.Environment(cr, pm.id, {})
    try:
        t_b_pm = env_pm['pm.task'].browse(task_b.id)
        t_b_pm.write({'priority': '3'})
        record_test("6.2 Project Manager can govern any task", True, "Project Manager updated task priority")
    except Exception as e:
        record_test("6.2 Project Manager can govern any task", False, str(e))

print("\n========================================================")
print(f"TEST SUITE COMPLETED: {sum(1 for r in test_results if r['success'])}/{len(test_results)} PASSED")
print("========================================================\n")
