# -*- coding: utf-8 -*-
import base64
from datetime import date, timedelta
from odoo.exceptions import ValidationError, UserError

def run_e2e_tests(env):
    print("=" * 80)
    print("STARTING DISCIPLINE MANAGEMENT COMPREHENSIVE E2E VERIFICATION SUITE")
    print("=" * 80)

    # 1. Fetch Key Administrative Actors & Reference Records
    admin_user = env.ref('base.user_admin')
    root_user = env.ref('base.user_root')
    
    # Offenses
    offense_minor = env['discipline.offense'].search([
        ('punishment_type', 'in', ['verbal_warning', 'first_warning_penalty'])
    ], limit=1)
    
    offense_major = env['discipline.offense'].search([
        ('punishment_type', 'in', ['final_warning_penalty', 'dismissal'])
    ], limit=1)

    # Non-managerial employee
    emp_non_mgr = env['hr.employee'].search([
        ('active', '=', True),
        ('user_id', '!=', False),
        ('parent_id', '!=', False),
        ('job_id.is_managerial', '=', False)
    ], limit=1)
    if not emp_non_mgr:
        emp_non_mgr = env['hr.employee'].search([('active', '=', True), ('user_id', '!=', False)], limit=1)

    # Managerial employee
    emp_mgr = env['hr.employee'].search([
        ('active', '=', True),
        ('id', '!=', emp_non_mgr.id),
        ('job_id.is_managerial', '=', True)
    ], limit=1)
    if not emp_mgr:
        emp_mgr = env['hr.employee'].search([('active', '=', True), ('id', '!=', emp_non_mgr.id)], limit=1)

    target_job = env['hr.job'].search([('id', '!=', emp_mgr.job_id.id)], limit=1)

    # Designated Administrative & Executive Stakeholders
    EmpModel = env['hr.employee'].sudo()
    ceo_user = EmpModel.get_ceo_user() or admin_user
    cpco_user = EmpModel.get_cpco_user() or admin_user
    pomd_user = EmpModel.get_secretary_user() or admin_user

    today = date.today()

    # --------------------------------------------------------------------------
    # TEST 1: Direct Enforcement Lifecycle (Non-Managerial Minor Offense)
    # --------------------------------------------------------------------------
    print("\n[TEST 1] Non-Managerial Direct Enforcement Lifecycle...")
    case1 = env['discipline.case'].with_user(admin_user).create({
        'employee_id': emp_non_mgr.id,
        'offense_id': offense_minor.id,
        'incident_date': today - timedelta(days=2),
        'description': 'Direct enforcement E2E automated test incident report.',
        'punishment_type': 'verbal_warning',
    })
    assert case1.state == 'draft', f"Expected draft, got {case1.state}"
    print(f"  ✓ Case created: {case1.name} in state '{case1.state}'")

    case1.action_initiate()
    assert case1.state == 'initiated', f"Expected initiated, got {case1.state}"
    print(f"  ✓ Case initiated -> '{case1.state}'")

    # Enforce sanction directly
    case1.action_approve_and_enforce()
    assert case1.state in ('enforced', 'closed'), f"Expected enforced/closed, got {case1.state}"
    print(f"  ✓ Case directly enforced and closed -> state: '{case1.state}'")

    # --------------------------------------------------------------------------
    # TEST 2: Committee Hearing Escalation, Minutes Upload & Demotion
    # --------------------------------------------------------------------------
    print("\n[TEST 2] Committee Hearing Escalation, Minutes Upload & Demotion Lifecycle...")
    case2 = env['discipline.case'].with_user(admin_user).create({
        'employee_id': emp_mgr.id,
        'offense_id': offense_major.id,
        'incident_date': today - timedelta(days=5),
        'description': 'Managerial gross misconduct incident requiring committee deliberation and demotion.',
        'punishment_type': 'final_warning_penalty',
        'case_action_track': 'committee_escalation',
    })
    case2.action_initiate()
    print(f"  ✓ Major Case created: {case2.name} in state '{case2.state}'")

    case2.action_send_to_committee()
    assert case2.state == 'committee_review', f"Expected committee_review, got {case2.state}"
    print(f"  ✓ Case referred to Disciplinary Committee -> '{case2.state}'")

    # Create Committee Hearing Session
    meeting = env['discipline.committee.meeting'].with_user(admin_user).create({
        'case_id': case2.id,
        'meeting_date': today,
        'location': 'Executive Boardroom B / Level 4',
        'committee_chair_id': cpco_user.id,
        'pomd_secretary_id': pomd_user.id,
    })
    assert meeting.state == 'draft', f"Expected draft meeting, got {meeting.state}"
    print(f"  ✓ Committee Meeting created: {meeting.name} in state '{meeting.state}'")

    # Secretary confirms schedule & summons
    meeting.with_user(pomd_user).action_confirm_schedule_and_send_summons()
    assert meeting.state == 'scheduled', f"Expected scheduled, got {meeting.state}"
    print(f"  ✓ Meeting scheduled -> '{meeting.state}'")

    # Chair commences active hearing session
    meeting.with_user(cpco_user).action_begin_hearing_session()
    assert meeting.state == 'in_progress', f"Expected in_progress, got {meeting.state}"
    print(f"  ✓ Chair began hearing session -> '{meeting.state}'")

    # Secretary attaches minutes and fills recommendations
    dummy_pdf = base64.b64encode(b"%PDF-1.4 Official Hearing Deliberation Minutes").decode('ascii')
    meeting.with_user(pomd_user).write({
        'signed_minutes_file': dummy_pdf,
        'signed_minutes_filename': 'Executive_Hearing_Minutes.pdf',
        'final_recommendation': 'final_warning',
        'recommended_penalty_percentage': 20.0,
        'recommended_warning_validity_days': 365,
        'is_demotion_recommended': True if emp_mgr.job_id.is_managerial else False,
        'demotion_target_job_id': target_job.id if emp_mgr.job_id.is_managerial else False,
        'recommendation_rationale': 'Detailed hearing review determined misconduct warranted final warning and job demotion.',
    })
    print("  ✓ Hearing minutes uploaded and sanction recommendations recorded.")

    # Secretary submits minutes to Committee Chairman
    meeting.with_user(pomd_user).action_submit_to_chairman()
    assert meeting.state in ('review', 'chair_review'), f"Expected review/chair_review, got {meeting.state}"
    print(f"  ✓ Secretary submitted minutes to Chair -> state: '{meeting.state}'")

    # Chairman reviews and submits to CEO
    meeting.with_user(cpco_user).action_submit_to_ceo()
    assert meeting.state in ('concluded', 'completed'), f"Expected concluded/completed, got {meeting.state}"
    assert case2.state == 'pending_approval', f"Expected case pending_approval, got {case2.state}"
    print(f"  ✓ Chairman submitted recommendation to CEO -> meeting state: '{meeting.state}', case state: '{case2.state}'")

    # CEO executes final enforcement
    original_job = emp_mgr.job_id
    case2.with_user(ceo_user).action_approve_and_enforce()
    assert case2.state in ('enforced', 'closed'), f"Expected enforced/closed, got {case2.state}"
    print(f"  ✓ CEO approved and enforced sanction -> case state: '{case2.state}'")

    # --------------------------------------------------------------------------
    # TEST 3: Disciplinary Appeal Lifecycle
    # --------------------------------------------------------------------------
    print("\n[TEST 3] Disciplinary Appeal Lifecycle...")
    # Employee creates appeal against Case 1 sanction
    appeal = env['discipline.appeal'].with_user(emp_non_mgr.user_id).create({
        'case_id': case1.id,
        'submission_date': today,
        'appeal_grounds': 'Procedural irregularity during initial fact collection and mitigating circumstances.',
    })
    assert appeal.state == 'draft', f"Expected draft appeal, got {appeal.state}"
    print(f"  ✓ Appeal registered: {appeal.name} in state '{appeal.state}'")

    # Employee submits appeal
    appeal.with_user(emp_non_mgr.user_id).action_submit_appeal()
    assert appeal.state in ('submitted', 'under_review', 'in_progress'), f"Expected submitted/under_review, got {appeal.state}"
    print(f"  ✓ Employee submitted appeal -> state: '{appeal.state}'")

    # Appellate authority starts review
    appeal.with_user(admin_user).action_start_review()
    assert appeal.state == 'under_review', f"Expected under_review, got {appeal.state}"
    print(f"  ✓ Appellate authority started review -> state: '{appeal.state}'")

    # Appellate authority renders decision
    reviewer_user = appeal.designated_reviewer_id or appeal.reviewer_id or admin_user
    appeal.with_user(admin_user).write({
        'decision_outcome': 'upheld',
        'appeal_decision_notes': 'Appeal reviewed by Appellate Board; sanction upheld.',
        'decision_date': today,
    })
    appeal.with_user(reviewer_user).action_render_decision()
    assert appeal.state == 'decided', f"Expected decided, got {appeal.state}"
    print(f"  ✓ Appeal decision rendered and concluded -> state: '{appeal.state}'")

    # --------------------------------------------------------------------------
    # TEST 4: Revocation Wizard Lifecycle (Case Annulment & Penalty Purge)
    # --------------------------------------------------------------------------
    print("\n[TEST 4] Legal Revocation & Annulment Lifecycle...")
    revocation_wizard = env['discipline.revocation.wizard'].with_user(admin_user).create({
        'case_id': case1.id,
        'revocation_reason': 'Annulled following arbitration tribunal decree.',
        'approval_notes': 'Formally verified and approved by Corporate Legal Affairs.',
    })
    revocation_wizard.action_confirm_revocation()
    assert case1.state == 'revoked', f"Expected revoked, got {case1.state}"
    print(f"  ✓ Case successfully revoked -> state: '{case1.state}'")

    print("\n" + "=" * 80)
    print("ALL 4 END-TO-END WORKFLOW TESTS COMPLETED SUCCESSFULLY WITH 100% PASS RATE!")
    print("=" * 80)
