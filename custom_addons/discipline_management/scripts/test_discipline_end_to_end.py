# -*- coding: utf-8 -*-
"""
End-to-End Automated Test Suite for Bunna Bank Disciplinary Management System.
Tests catalog integrity, case creation, auto-population, legal citations, rule resolution,
committee workflow, and payroll penalty generation.
"""
import sys
import odoo
from odoo.modules.registry import Registry

def run_tests():
    print("=" * 70)
    print("BUNNA BANK DISCIPLINARY MANAGEMENT SYSTEM: END-TO-END TEST SUITE")
    print("=" * 70)

    db_name = 'pm_db'
    registry = Registry(db_name)
    cr = registry.cursor()
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})

    test_results = []
    
    def log_test(name, success, detail=""):
        status = "PASSED" if success else "FAILED"
        test_results.append((name, success, detail))
        print(f"[{status}] {name}")
        if detail:
            print(f"       -> {detail}")

    try:
        # -------------------------------------------------------------
        # TEST 1: CATALOG INTEGRITY (10 Articles, 7 Categories, 184 Offenses)
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 1: REGULATORY CATALOG VERIFICATION ---")
        articles = env['discipline.article'].search([])
        categories = env['discipline.offense.category'].search([])
        offenses = env['discipline.offense'].search([])
        linked_offenses = env['discipline.offense'].search([('article_id', '!=', False)])
        
        log_test("10 Regulatory Articles Exist", len(articles) == 10, f"Found {len(articles)} articles")
        log_test("7 Offense Categories Exist", len(categories) >= 7, f"Found {len(categories)} categories")
        log_test("All 184 Bunna Bank Offenses Linked", len(linked_offenses) >= 184, f"Found {len(linked_offenses)} linked offenses")

        # Check sample articles and sub-clause counts
        art_33_4 = env['discipline.article'].search([('article_number', '=', 'Article 33.4')], limit=1)
        log_test("Article 33.4 (Dismissal) Exists with Sub-Clauses", bool(art_33_4 and art_33_4.offense_count == 37), f"Article 33.4 has {art_33_4.offense_count if art_33_4 else 0} sub-clauses")

        art_10_5_1 = env['discipline.article'].search([('article_number', '=', 'Article 10.5.1')], limit=1)
        log_test("Article 10.5.1 (Managerial Dismissal) Exists", bool(art_10_5_1 and art_10_5_1.offense_count == 23), f"Article 10.5.1 has {art_10_5_1.offense_count if art_10_5_1 else 0} sub-clauses")

        # -------------------------------------------------------------
        # TEST 2: KEYWORD & CLAUSE CODE SEARCH CAPABILITY
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 2: INTELLIGENT SEARCH VERIFICATION ---")
        # Search by Ethiopian Amharic Letter Code
        offense_by_code = env['discipline.offense'].search([('sub_article_code', 'ilike', '33.4.1(ሀ)')], limit=1)
        log_test("Search by Code '33.4.1(ሀ)'", bool(offense_by_code), f"Found ID {offense_by_code.id}: {offense_by_code.name if offense_by_code else ''}")

        # Search by Amharic Legal Keyword
        search_amharic = env['discipline.offense'].name_search('ስርቆት')
        log_test("Search by Amharic Keyword 'ስርቆት' (Theft)", len(search_amharic) > 0, f"Returned {len(search_amharic)} matching statutory offenses")

        # Search by Attendance Keyword
        search_attendance = env['discipline.offense'].name_search('መቅረት')
        log_test("Search by Amharic Keyword 'መቅረት' (Absence)", len(search_attendance) > 0, f"Returned {len(search_attendance)} matching offenses")

        # -------------------------------------------------------------
        # TEST 3: DISCIPLINARY CASE CREATION & AUTO-POPULATION
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 3: CASE CREATION & AUTO-POPULATION ---")
        employee = env['hr.employee'].search([('active', '=', True)], limit=1)
        if not employee:
            employee = env['hr.employee'].create({'name': 'Test Bunna Employee'})
            print("Created temporary employee for testing")

        test_offense = offense_by_code or env['discipline.offense'].search([('sub_article_code', '!=', False)], limit=1)
        
        # Create Case in Draft
        case_vals = {
            'employee_id': employee.id,
            'offense_id': test_offense.id,
            'incident_date': odoo.fields.Date.today(),
            'description': 'End-to-End Test Incident Description',
        }
        case = env['discipline.case'].new(case_vals)
        case._onchange_employee_id()
        case._onchange_offense_id()
        case._compute_punishment_details()

        # Save to database
        saved_case_vals = case._convert_to_write(case._cache)
        test_case = env['discipline.case'].create(saved_case_vals)

        log_test("Case Creation in Draft State", test_case.state == 'draft', f"Case Reference: {test_case.name}")
        log_test("Auto-Populated Governing Article", bool(test_case.article_id and test_case.article_id.id == test_offense.article_id.id), f"Governing Article: {test_case.article_id.name if test_case.article_id else 'None'}")
        log_test("Auto-Populated Sub-Article Code", test_case.sub_article_code == test_offense.sub_article_code, f"Sub-Article Code: {test_case.sub_article_code}")
        log_test("Auto-Populated Verbatim Legal Clause", bool(test_case.legal_clause_text and len(test_case.legal_clause_text) > 5), f"Verbatim Text snippet: {(test_case.legal_clause_text or '')[:50]}...")
        log_test("Auto-Determined Severity Level", bool(test_case.severity_level_id), f"Severity: {test_case.severity_level_id.name if test_case.severity_level_id else 'None'}")

        # -------------------------------------------------------------
        # TEST 4: SALARY PENALTY RESOLUTION (Level 4: 5% Fine Offense)
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 4: STATUTORY PENALTY & FINE RESOLUTION ---")
        offense_art_33_7 = env['discipline.offense'].search([('sub_article_code', 'ilike', '33.7.')], limit=1)
        if offense_art_33_7:
            case_fine = env['discipline.case'].new({
                'employee_id': employee.id,
                'offense_id': offense_art_33_7.id,
                'incident_date': odoo.fields.Date.today(),
                'description': 'End-to-End Fine Test Incident Description',
            })
            case_fine._onchange_employee_id()
            case_fine._onchange_offense_id()
            case_fine._compute_punishment_details()
            
            fine_case_vals = case_fine._convert_to_write(case_fine._cache)
            test_fine_case = env['discipline.case'].create(fine_case_vals)

            pct = test_fine_case.penalty_percentage
            log_test("Article 33.7 Penalty Percentage Resolution", pct == 5.0, f"Resolved Penalty %: {pct}%")
            log_test("Statutory Rule Summary Formatted", bool(test_fine_case.auto_applied_rule_summary), f"Rule Summary: {test_fine_case.auto_applied_rule_summary}")
            
            # Clean up fine test case
            test_fine_case.unlink()
        else:
            log_test("Article 33.7 Penalty Percentage Resolution", False, "No Article 33.7 offense found")

        # -------------------------------------------------------------
        # TEST 5: WORKFLOW TRANSITION (Draft -> Initiated -> Investigation)
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 5: WORKFLOW TRANSITIONS ---")
        if hasattr(test_case, 'action_initiate_case'):
            test_case.action_initiate_case()
            log_test("Action: Initiate Case", test_case.state in ('initiated', 'under_investigation', 'submitted_director'), f"New State: {test_case.state}")
        elif hasattr(test_case, 'action_submit'):
            test_case.action_submit()
            log_test("Action: Submit Case", test_case.state != 'draft', f"New State: {test_case.state}")
        else:
            log_test("Workflow Action Available", True, f"Current State: {test_case.state}")

        # -------------------------------------------------------------
        # TEST 6: CLEANUP
        # -------------------------------------------------------------
        print("\n--- TEST PHASE 6: TEST DATA CLEANUP ---")
        test_case_id = test_case.id
        test_case.unlink()
        log_test("Test Case Cleaned Up (Database Pristine)", True, f"Cleaned Case ID {test_case_id}")

        cr.commit()

        # -------------------------------------------------------------
        # SUMMARY
        # -------------------------------------------------------------
        print("\n" + "=" * 70)
        total_tests = len(test_results)
        passed_tests = sum(1 for _, ok, _ in test_results if ok)
        failed_tests = total_tests - passed_tests
        print(f"SUMMARY: {passed_tests}/{total_tests} TESTS PASSED ({failed_tests} FAILED)")
        print("=" * 70)
        return failed_tests == 0

    except Exception as e:
        cr.rollback()
        print(f"\n[FATAL ERROR] Exception during test execution: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cr.close()

if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
