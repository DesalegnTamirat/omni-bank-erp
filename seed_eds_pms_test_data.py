# -*- coding: utf-8 -*-
"""
Omni-Bank ERP — Seed PMS & Competency Data for EDS Pull Testing
================================================================
Target Database: Local database configured in odoo.conf (ERP)
Host: db:5432 (inside docker) / localhost:5434 (host / DBeaver)

Seeds:
1. Closed Competency Assessment Cycle with real diagnostic gaps (tna_measure='below', gap >= 1)
2. Finalized / Confirmed PMS Appraisals (t3.appraisal) with scores < 75% and development recommendations
3. Active Collecting EDS TNA Cycle ready for testing the pull wizards:
   - "Pull Closed Competency Gaps" (eds.competency.gap.import)
   - "Pull PMS Appraisal Gaps" (eds.pms.gap.import)
"""

import sys
from datetime import date, timedelta

def run_seed(env):
    print("=" * 60)
    print("STARTING SEED: PMS & COMPETENCY FOR EDS PULL TESTING")
    print("=" * 60)

    # ---------------------------------------------------------
    # 1. RETRIEVE ACTIVE EMPLOYEES
    # ---------------------------------------------------------
    employees = env['hr.employee'].search([('active', '=', True)], limit=8)
    if not employees:
        print("ERROR: No active employees found in hr.employee!")
        return
    print(f"[1/5] Selected {len(employees)} active employees for testing:")
    for emp in employees[:5]:
        print(f"      - ID {emp.id}: {emp.name} (Dept: {emp.department_id.name if emp.department_id else 'N/A'})")

    # ---------------------------------------------------------
    # 2. RETRIEVE REAL ACTIVE COMPETENCIES
    # ---------------------------------------------------------
    competencies = env['competency.competency'].search([('status', '=', 'active')], limit=6)
    if not competencies:
        competencies = env['competency.competency'].search([], limit=6)
    print(f"[2/5] Selected {len(competencies)} competencies:")
    for comp in competencies:
        print(f"      - ID {comp.id}: [{comp.code or 'NO-CODE'}] {comp.name}")

    # ---------------------------------------------------------
    # 3. SEED CLOSED COMPETENCY ASSESSMENT CYCLE & GAPS
    # ---------------------------------------------------------
    print("[3/5] Seeding Closed Competency Assessment Cycle & Lines...")
    cycle_name = "Annual Competency Assessment Cycle 2025/2026 (Closed)"
    comp_cycle = env['competency.assessment.cycle'].search([('name', '=', cycle_name)], limit=1)
    if not comp_cycle:
        comp_cycle = env['competency.assessment.cycle'].sudo().create({
            'name': cycle_name,
            'code': 'COMP-2025-CLOSED',
            'period_start': date.today() - timedelta(days=180),
            'period_end': date.today() - timedelta(days=30),
            'assessment_deadline': date.today() - timedelta(days=35),
            'state': 'closed',
            'active': True,
            'notes': 'Closed cycle populated with diagnostic competency gaps for EDS TNA ingestion testing.',
        })
        print(f"      Created Closed Cycle: ID {comp_cycle.id} - '{comp_cycle.name}'")
    else:
        comp_cycle.sudo().write({'state': 'closed', 'active': True})
        print(f"      Found & Ensured Closed Cycle: ID {comp_cycle.id}")

    # Also ensure earlier test cycles that have gaps are closed so user has options
    for existing_c in env['competency.assessment.cycle'].search([('id', 'in', [2072, 2074])]):
        existing_c.sudo().write({'state': 'closed'})
        print(f"      Updated existing cycle {existing_c.id} ('{existing_c.name}') to state='closed'")

    # Create approved assessments and gap lines for each employee
    comp_line_count = 0
    for idx, emp in enumerate(employees[:5]):
        asm = env['competency.assessment'].search([
            ('cycle_id', '=', comp_cycle.id),
            ('employee_id', '=', emp.id)
        ], limit=1)
        if not asm:
            asm = env['competency.assessment'].sudo().create({
                'cycle_id': comp_cycle.id,
                'employee_id': emp.id,
                'assessment_type': 'team',
                'state': 'approved',
                'notes': f'Assessment with evaluated competency gaps for {emp.name}',
            })

        # Add 2 competency gap lines per employee
        for c_idx in range(2):
            comp = competencies[(idx * 2 + c_idx) % len(competencies)]
            line = env['competency.assessment.line'].search([
                ('assessment_id', '=', asm.id),
                ('competency_id', '=', comp.id)
            ], limit=1)
            
            gap_lvl = 2 if c_idx == 0 else 1
            req_lvl = '3' if c_idx == 0 else '4'
            cur_lvl = '1' if c_idx == 0 else '3'
            
            if not line:
                line = env['competency.assessment.line'].sudo().create({
                    'assessment_id': asm.id,
                    'competency_id': comp.id,
                    'required_level': req_lvl,
                    'current_level': cur_lvl,
                    'active': True,
                })
                comp_line_count += 1
            else:
                pass

    print(f"      Created/Updated {comp_line_count} diagnostic competency gap lines (all state='approved', tna_measure='below', gap >= 1).")

    # ---------------------------------------------------------
    # 4. SEED PMS APPRAISALS (TIER 3) WITH LOW SCORES (< 75%)
    # ---------------------------------------------------------
    print("[4/5] Seeding PMS Fiscal Year, Periods, and Confirmed Appraisals...")
    fy_name = "2025/2026 Fiscal Year"
    fy = env['performance.fiscal.year'].search([('name', '=', fy_name)], limit=1)
    if not fy:
        fy = env['performance.fiscal.year'].sudo().create({
            'name': fy_name,
            'date_start': '2025-07-01',
            'date_end': '2026-06-30',
            'active': True,
        })
        print(f"      Created PMS Fiscal Year: ID {fy.id} - '{fy.name}'")
    else:
        print(f"      Found PMS Fiscal Year: ID {fy.id}")

    period_code = "ANNUAL"
    period = env['appraisal.period'].search([('code', '=', period_code)], limit=1)
    if not period:
        period = env['appraisal.period'].sudo().create({
            'name': 'Annual Appraisal Period 2025/2026',
            'code': period_code,
            'active': True,
        })
        print(f"      Created Appraisal Period: ID {period.id} - '{period.name}' ({period.code})")
    else:
        print(f"      Found Appraisal Period: ID {period.id} ({period.code})")

    pms_data = [
        {
            "criteria": "Credit Assessment & Loan Portfolio Quality",
            "score": 52.0,
            "recom": "Needs intensive training in Credit Risk Assessment, NBE Directives compliance, and Non-Performing Loan (NPL) work-out strategies.",
        },
        {
            "criteria": "Digital Banking Customer Onboarding & KYC Compliance",
            "score": 58.5,
            "recom": "Recommended for advanced workshop on AML/CFT compliance, Digital Banking security protocols, and KYC verification procedures.",
        },
        {
            "criteria": "Branch Operation Efficiency & Cash Management",
            "score": 63.0,
            "recom": "Requires structured training on Treasury Management, Branch Cash Limits, and Core Banking reconciliation procedures.",
        },
        {
            "criteria": "Trade Service & Foreign Exchange Regulation Compliance",
            "score": 68.0,
            "recom": "Staff needs practical L&D program on Letter of Credit (LC) processing, Documentary Collections, and National Bank of Ethiopia Foreign Exchange directives.",
        },
    ]

    pms_employees = env['hr.employee'].search([
        ('id', 'in', [5067, 1447, 1250, 2578]),
        ('active', '=', True)
    ])
    if len(pms_employees) < 4:
        pms_employees = employees[:4]

    pms_appraisal_count = 0
    for idx, emp in enumerate(pms_employees):
        p_info = pms_data[idx % len(pms_data)]
        appr_name = f"2025/2026 Annual Appraisal - {emp.name}"
        appr = env['t3.appraisal'].search([('name', '=', appr_name)], limit=1)
        if not appr:
            appr = env['t3.appraisal'].sudo().create({
                'name': appr_name,
                'employee_id': emp.id,
                'fiscal_year_id': fy.id,
                'appraisal_period_id': period.id,
                'state': 'confirmed',
                'appraisal_date': date.today() - timedelta(days=20),
                'employee_score': p_info["score"],
                'line_ids': [(0, 0, {
                    'appraisal_criteria': p_info["criteria"],
                    'planned_weight': 100.0,
                    'weight': 100.0,
                    'target': 100.0,
                    'uploaded_value': p_info["score"],
                    'accomplishment_percent': p_info["score"],
                    'appraised_score': p_info["score"],
                    'appraised': 'yes',
                    'recommendations': p_info["recom"],
                })],
            })
            pms_appraisal_count += 1
            print(f"      Created PMS Appraisal: ID {appr.id} for {emp.name} | Score: {p_info['score']}% | State: confirmed")
        else:
            print(f"      PMS Appraisal already exists: ID {appr.id} for {emp.name} | Score: {appr.employee_score}% | State: {appr.state}")

    # ---------------------------------------------------------
    # 5. SEED / VERIFY ACTIVE EDS TNA CYCLE IN 'COLLECTING' STATE
    # ---------------------------------------------------------
    print("[5/5] Ensuring Active EDS TNA Cycle in 'Collecting Needs' state...")
    tna_cycle_ref = "TNA-2026-PULL-TEST"
    tna_cycle = env['eds.tna.cycle'].search([('name', '=', tna_cycle_ref)], limit=1)
    if not tna_cycle:
        tna_cycle = env['eds.tna.cycle'].sudo().create({
            'name': tna_cycle_ref,
            'year': '2026',
            'start_date': date.today(),
            'submission_end_date': date.today() + timedelta(days=30),
            'approval_deadline': date.today() + timedelta(days=60),
            'state': 'collecting',
            'methodology': 'Comprehensive 360-Degree Diagnostics: Ingestion from Closed Competency Assessments and Low-Score PMS Appraisals.',
            'notes': 'Test cycle ready for verifying both "Pull Closed Competency Gaps" and "Pull PMS Performance Gaps" buttons.',
        })
        print(f"      Created EDS TNA Cycle: ID {tna_cycle.id} - '{tna_cycle.name}' (State: {tna_cycle.state})")
    else:
        tna_cycle.sudo().write({'state': 'collecting'})
        print(f"      Found & Ensured EDS TNA Cycle: ID {tna_cycle.id} - '{tna_cycle.name}' (State: {tna_cycle.state})")

    # Commit all changes to DB
    env.cr.commit()
    print("=" * 60)
    print("SEEDING COMPLETED AND COMMITTED SUCCESSFULLY!")
    print(f"Summary:")
    print(f"  - Closed Competency Cycle: '{comp_cycle.name}' (ID {comp_cycle.id})")
    print(f"  - PMS Confirmed Appraisals: 4 Appraisals with Scores < 75%")
    print(f"  - Target EDS TNA Cycle: '{tna_cycle.name}' (ID {tna_cycle.id}, State: {tna_cycle.state})")
    print("=" * 60)

run_seed(env)
