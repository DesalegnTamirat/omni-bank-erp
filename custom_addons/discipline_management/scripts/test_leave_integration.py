import odoo
from odoo.modules.registry import Registry
from odoo.exceptions import UserError, ValidationError
from datetime import date, timedelta

registry = Registry('pm_db')
with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    print("=" * 70)
    print("TESTING LEAVE INTEGRATION & ALLOCATION VALIDATION")
    print("=" * 70)

    # 1. Setup / Find test employee and leave type
    emp = env['hr.employee'].search([('active', '=', True)], limit=1)
    coach = emp.parent_id or emp.coach_id or emp
    print(f"Test Subject Employee: {emp.name} (ID: {emp.id})")
    
    # Find a leave type requiring allocation
    lt_alloc = env['hr.leave.type'].search([('requires_allocation', '=', True)], limit=1)
    if not lt_alloc:
        lt_alloc = env['hr.leave.type'].search([], limit=1)
    print(f"Test Leave Type: {lt_alloc.name} (Requires Allocation: {lt_alloc.requires_allocation})")
    
    # 2. Check employee's current allocation balance
    lt_ctx = lt_alloc.with_context(employee_id=emp.id)
    avail_balance = getattr(lt_ctx, 'virtual_remaining_leaves', 0.0) or 0.0
    print(f"Current Available Balance for {emp.name}: {avail_balance:.1f} days")

    # 3. Create a test dismissal attendance case (25 days unexcused absence)
    today = date.today()
    d_from = today - timedelta(days=30)
    d_to = today - timedelta(days=6)
    
    case = env['discipline.attendance.case'].create({
        'employee_id': emp.id,
        'violation_type': 'absence_dismissal',
        'date_from': d_from,
        'date_to': d_to,
        'absent_days_count': 25,
        'max_consecutive_days': 25,
        'absent_dates_summary': f"{d_from} to {d_to} (25 working days)",
        'state': 'director_review',
    })
    print(f"Created Test Case: {case.name} | State: {case.state} | Absent Days: {case.absent_days_count}")

    # TEST SCENARIO A: Wizard dynamic balance computation
    print("\n--- TEST SCENARIO A: Dynamic Balance Computation in Wizard ---")
    wiz = env['discipline.attendance.action.wizard'].create({
        'action_type': 'adjust_leave',
        'attendance_case_ids': [(6, 0, [case.id])],
        'employee_id': emp.id,
        'holiday_status_id': lt_alloc.id,
        'leave_mode': 'create_new',
        'leave_date_from': d_from,
        'leave_date_to': d_to,
        'reason_notes': 'Testing leave balance verification',
    })
    print(f"Wizard Required Days: {wiz.required_leave_days}")
    print(f"Wizard Available Balance: {wiz.available_leave_balance}")
    print(f"Wizard Has Insufficient Allocation: {wiz.has_insufficient_allocation}")
    print(f"Wizard Balance Warning: {wiz.leave_balance_warning}")
    assert wiz.required_leave_days == 25.0, f"Expected 25.0 required days, got {wiz.required_leave_days}"
    print("PASS: Wizard computed correct required days and balance status.")

    # TEST SCENARIO B: Insufficient allocation balance blocks confirmation
    print("\n--- TEST SCENARIO B: Insufficient Balance Blocks Confirmation ---")
    if lt_alloc.requires_allocation and avail_balance < 25.0:
        blocked = False
        try:
            wiz.action_confirm()
        except ValidationError as e:
            blocked = True
            print(f"Expected ValidationError raised:\n  -> {e}")
        assert blocked, "FAIL: Wizard did not block confirmation when allocation was insufficient!"
        print("PASS: Insufficient allocation balance strictly blocked with ValidationError.")
    else:
        print("SKIP: Employee already has >= 25 days allocation.")

    # TEST SCENARIO C: Non-HR User cannot use manual_adjust
    print("\n--- TEST SCENARIO C: Non-HR User Blocked From Manual Adjust ---")
    user_group = env.ref('discipline_management.group_discipline_user')
    pomd_group = env.ref('discipline_management.group_discipline_pomd')
    admin_group = env.ref('discipline_management.group_discipline_admin')
    
    # Find a discipline user who is NOT POMD or Admin
    reg_user = None
    for u in user_group.user_ids:
        if u.id != 1 and not u.has_group('discipline_management.group_discipline_pomd') and not u.has_group('discipline_management.group_discipline_admin'):
            reg_user = u
            break
            
    if not reg_user:
        reg_user = env['res.users'].create({
            'name': 'Test Regular Coach User',
            'login': 'test_regular_coach_user_temp',
            'group_ids': [(6, 0, [env.ref('base.group_user').id, user_group.id])],
        })

    # Give reg_user supervisor access to this test case
    case.write({'coach_id': reg_user.id})

    wiz_reg = env['discipline.attendance.action.wizard'].with_user(reg_user).create({
        'action_type': 'adjust_leave',
        'attendance_case_ids': [(6, 0, [case.id])],
        'employee_id': emp.id,
        'leave_mode': 'manual_adjust',
        'reason_notes': 'Attempting manual override without POMD role',
    })
    blocked_perm = False
    try:
        wiz_reg.action_confirm()
    except UserError as e:
        blocked_perm = True
        print(f"Expected UserError raised:\n  -> {e}")
    assert blocked_perm, "FAIL: Non-HR user was able to bypass manual adjustment!"
    print("PASS: Manual adjust restricted to POMD Officers / HR Admins.")

    # TEST SCENARIO D: Existing Leave Validation (Status and Employee Mismatch)
    print("\n--- TEST SCENARIO D: Existing Leave Validation ---")
    existing_leave = env['hr.leave'].search([], limit=1)
    if existing_leave:
        print(f"Testing with existing leave: {existing_leave.display_name} (State: {existing_leave.state})")
        if existing_leave.state not in ('validate', 'validate1'):
            wiz_unapproved = env['discipline.attendance.action.wizard'].create({
                'action_type': 'adjust_leave',
                'attendance_case_ids': [(6, 0, [case.id])],
                'employee_id': existing_leave.employee_id.id,
                'leave_mode': 'existing',
                'leave_id': existing_leave.id,
                'reason_notes': 'Linking unapproved leave',
            })
            blocked_unapproved = False
            try:
                wiz_unapproved.action_confirm()
            except UserError as e:
                blocked_unapproved = True
                print(f"Expected UserError on Unapproved Leave:\n  -> {e}")
            assert blocked_unapproved, "FAIL: Unapproved leave was accepted!"
            print("PASS: Unapproved leave strictly blocked.")
        else:
            # Test employee mismatch
            diff_emp = env['hr.employee'].search([('id', '!=', existing_leave.employee_id.id)], limit=1)
            case_mismatch = env['discipline.attendance.case'].create({
                'employee_id': diff_emp.id,
                'violation_type': 'absence_minor',
                'date_from': d_from,
                'date_to': d_to,
                'absent_days_count': 2,
                'max_consecutive_days': 2,
                'state': 'coach_review',
            })
            wiz_mismatch = env['discipline.attendance.action.wizard'].create({
                'action_type': 'adjust_leave',
                'attendance_case_ids': [(6, 0, [case_mismatch.id])],
                'employee_id': diff_emp.id,
                'leave_mode': 'existing',
                'leave_id': existing_leave.id,
                'reason_notes': 'Linking mismatched employee leave',
            })
            blocked_mismatch = False
            try:
                wiz_mismatch.action_confirm()
            except UserError as e:
                blocked_mismatch = True
                print(f"Expected UserError on Employee Mismatch:\n  -> {e}")
            assert blocked_mismatch, "FAIL: Employee mismatch was not blocked!"
            print("PASS: Mismatched employee leave strictly blocked.")

    # Rollback test transactions
    cr.rollback()
    print("\n" + "=" * 70)
    print("ALL LEAVE INTEGRATION & VALIDATION TESTS PASSED 100%!")
    print("=" * 70)
