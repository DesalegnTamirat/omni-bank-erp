# -*- coding: utf-8 -*-
import logging
from datetime import date, timedelta
from odoo import fields, exceptions

_logger = logging.getLogger(__name__)

def run_attendance_and_tracking_tests(env):
    print("=" * 80)
    print("STARTING ATTENDANCE DISCIPLINE & EXECUTIVE TRACKING E2E VERIFICATION SUITE")
    print("=" * 80)

    admin_user = env.ref('base.user_admin')
    today = date.today()

    # --------------------------------------------------------------------------
    # TEST 1: Simplified Bank-Wide Attendance Violation Scanner
    # --------------------------------------------------------------------------
    print("\n[TEST 1] Bank-Wide Attendance Violation Scanner Wizard...")
    
    # Ensure config parameters exist
    env['ir.config_parameter'].sudo().set_param('discipline.cumulative_absence_threshold', '2')
    env['ir.config_parameter'].sudo().set_param('discipline.tardiness_threshold_minutes', '60')

    # Test preset 'this_month'
    scan_wizard = env['discipline.attendance.scan.wizard'].with_user(admin_user).create({
        'period_preset': 'this_month',
        'skip_existing_active_cases': True,
    })
    assert scan_wizard.date_from == today.replace(day=1), "Expected date_from to be 1st of current month"
    assert scan_wizard.date_to == today, "Expected date_to to be today"
    assert scan_wizard.total_employees_count > 0, "Expected active employees count > 0"
    print(f"  ✓ Scan Wizard initialized bank-wide with {scan_wizard.total_employees_count} employees in scope.")

    # Test preset 'this_week'
    scan_wizard.write({'period_preset': 'this_week'})
    assert scan_wizard.date_from <= today, "Expected date_from to be Monday of this week"
    print("  ✓ Evaluation period switched to 'this_week' dynamically.")

    # Execute bank-wide scan action (smoke run without crash)
    result = scan_wizard.action_scan_and_initiate()
    assert result.get('type') in ('ir.actions.act_window', 'ir.actions.client'), "Expected window action or notification result"
    print(f"  ✓ Bank-wide scan executed successfully returning action type: '{result.get('type')}'")

    # --------------------------------------------------------------------------
    # TEST 2: Attendance Disciplinary Case & Leave Adjustment Wizard
    # --------------------------------------------------------------------------
    print("\n[TEST 2] Attendance Case & Leave Adjustment Lifecycle...")
    
    # Find an open active attendance case, or create one for an employee without active cases
    att_case = env['discipline.attendance.case'].search([
        ('state', 'in', ['draft', 'coach_review', 'director_review']),
        ('absent_days_count', '>', 0)
    ], limit=1)

    if not att_case:
        existing_emp_ids = env['discipline.attendance.case'].search([
            ('state', 'not in', ['enforced', 'leave_adjusted', 'exonerated', 'hr_refused'])
        ]).mapped('employee_id.id')
        emp = env['hr.employee'].search([('active', '=', True), ('id', 'not in', existing_emp_ids)], limit=1)
        if not emp:
            emp = env['hr.employee'].search([('active', '=', True)], limit=1)
        att_case = env['discipline.attendance.case'].with_user(admin_user).create({
            'employee_id': emp.id,
            'violation_type': 'absence_prolonged',
            'incident_date': today - timedelta(days=60),
            'date_from': today - timedelta(days=67),
            'date_to': today - timedelta(days=60),
            'absent_days_count': 3,
            'max_consecutive_days': 3,
            'state': 'draft',
        })
    print(f"  ✓ Target Attendance Case: {att_case.name} for {att_case.employee_id.name} ({att_case.absent_days_count} absent days, state={att_case.state})")

    # Test Leave Action Wizard (Direct Administrative Adjustment Override)
    orig_absent = att_case.absent_days_count
    leave_wizard = env['discipline.attendance.action.wizard'].with_user(admin_user).create({
        'action_type': 'adjust_leave',
        'leave_mode': 'manual_adjust',
        'attendance_case_ids': [(6, 0, [att_case.id])],
        'reason_notes': 'Covered under certified retroactive medical certificate verified by Clinic.',
    })
    print("  ✓ Attendance Action Wizard initialized with target case.")

    leave_wizard.action_confirm()
    assert att_case.state == 'leave_adjusted', f"Expected leave_adjusted, got {att_case.state}"
    assert att_case.covered_leave_days == orig_absent, f"Expected {orig_absent} covered days, got {att_case.covered_leave_days}"
    assert att_case.remaining_unexcused_days == 0, f"Expected 0 remaining unexcused, got {att_case.remaining_unexcused_days}"
    print(f"  ✓ Attendance case successfully adjusted: state='{att_case.state}', remaining unexcused={att_case.remaining_unexcused_days}")

    # --------------------------------------------------------------------------
    # TEST 3: Executive SLA Tracking & Follow-up Discuss Reminders
    # --------------------------------------------------------------------------
    print("\n[TEST 3] Executive SLA Countdown & Discuss Reminder System...")
    emp = att_case.employee_id or env['hr.employee'].search([('active', '=', True)], limit=1)
    
    # Create a discipline case in Executive Review stage
    offense = env['discipline.offense'].search([], limit=1)
    sec_user = env['res.users'].search([('login', '=', 'secretary_user')], limit=1)
    if not sec_user:
        sec_user = env['res.users'].create({
            'name': 'Executive Board Secretary',
            'login': 'secretary_exec_test',
            'email': 'sec_exec@bunnabank.et',
        })
    
    boss_user = env['res.users'].search([('login', '=', 'boss_user')], limit=1)
    if not boss_user:
        boss_user = env['res.users'].create({
            'name': 'Chief Human Capital Officer',
            'login': 'chief_exec_test',
            'email': 'chief_exec@bunnabank.et',
        })
    
    # Link secretary to boss
    sec_user.write({'discipline_assigned_executive_id': boss_user.id})

    # 4. Create executive case awaiting this boss
    exec_case = env['discipline.case'].with_user(admin_user).create({
        'employee_id': emp.id,
        'offense_id': offense.id,
        'incident_date': today - timedelta(days=20),
        'description': 'Executive review case for follow-up verification.',
        'state': 'submitted_chief',
        'chief_id': boss_user.id,
        'current_stage_authority_user_id': boss_user.id,
        'stage_entry_date': fields.Datetime.now() - timedelta(days=10),
    })

    # Trigger SLA compute
    exec_case._compute_stage_sla_tracking()
    print(f"  ✓ Executive case tracked: SLA Status = '{exec_case.sla_status}', Countdown = '{exec_case.sla_countdown_display}'")
    assert exec_case.sla_status in ('warning', 'overdue', 'on_track'), "Valid SLA status expected"

    # Send Discuss DM reminder as Secretary
    res_notify = exec_case.with_user(sec_user).action_secretary_remind_boss()
    assert exec_case.last_secretary_reminder_date is not False, "Expected reminder timestamp to be recorded"
    assert res_notify.get('params', {}).get('type') == 'success', "Expected success notification"
    print("  ✓ Secretary Discuss DM reminder successfully delivered to executive.")

    # Verify 4-Hour anti-spam cooldown
    res_cooldown = exec_case.with_user(sec_user).action_secretary_remind_boss()
    assert res_cooldown.get('params', {}).get('type') == 'warning', "Expected cooldown warning notification"
    print(f"  ✓ Anti-spam cooldown working as designed: {res_cooldown['params']['title']} - {res_cooldown['params']['message']}")

    # Test daily morning cron
    env['discipline.case']._cron_case_expiration_followup_alerts()
    print("  ✓ Daily executive SLA tracker cron executed without errors.")

    print("\n" + "=" * 80)
    print("ALL ATTENDANCE & TRACKING E2E WORKFLOW TESTS PASSED (100%)!")
    print("=" * 80)
    return True
