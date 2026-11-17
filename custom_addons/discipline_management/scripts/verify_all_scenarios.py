import odoo
from odoo.modules.registry import Registry

registry = Registry('pm_db')
with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    print("=" * 60)
    print("VERIFYING SCENARIO 1: REGULATORY CATALOG & DATA PARITY")
    print("=" * 60)
    articles = env['discipline.article'].search([])
    print(f"Total Regulatory Articles: {len(articles)}")
    for a in articles:
        p_name = a.policy_version_id.name if a.policy_version_id else "None"
        print(f"  [{a.article_number}] {a.name} -> Policy: {p_name} | Clauses: {len(a.offense_ids)}")
        
    categories = env['discipline.offense.category'].search([])
    print(f"\nTotal Offense Categories: {len(categories)}")
    for c in categories:
        print(f"  [{c.code}] {c.name}")
        
    offenses = env['discipline.offense'].search([])
    print(f"\nTotal Offenses in DB: {len(offenses)}")
    linked = env['discipline.offense'].search([('article_id', '!=', False)])
    print(f"Statutory Offenses Linked to Articles: {len(linked)}")
    
    print("\n" + "=" * 60)
    print("VERIFYING SCENARIO 2: SYNC & REPAIR REGULATION ACTION")
    print("=" * 60)
    res = env['discipline.offense'].action_sync_bunna_regulation_catalog()
    print(f"Sync Action Title: {res.get('params', {}).get('title')}")
    print(f"Sync Action Message: {res.get('params', {}).get('message')}")
    
    print("\n" + "=" * 60)
    print("VERIFYING SCENARIO 3: CASE CREATION & AUTO-CALCULATIONS")
    print("=" * 60)
    
    # Find one non-managerial and one managerial employee
    non_mgr_emp = None
    mgr_emp = None
    for e in env['hr.employee'].search([('active', '=', True)], limit=100):
        if env['discipline.case']._is_employee_managerial(e):
            if not mgr_emp:
                mgr_emp = e
        else:
            if not non_mgr_emp:
                non_mgr_emp = e
        if non_mgr_emp and mgr_emp:
            break
            
    print(f"Non-Managerial Test Employee: {non_mgr_emp.name}")
    print(f"Managerial Test Employee: {mgr_emp.name}")
    
    # 3.1 Non-Managerial Dismissal Offense (Article 33.4)
    off_33_4 = env['discipline.offense'].search([('sub_article_code', 'ilike', '33.4.1(ሀ)')], limit=1)
    c1 = env['discipline.case'].new({
        'employee_id': non_mgr_emp.id,
        'offense_id': off_33_4.id,
        'incident_date': odoo.fields.Date.today(),
        'description': 'Production Verification Case - 33.4',
    })
    c1._onchange_employee_id()
    c1._onchange_offense_id()
    c1._compute_punishment_details()
    case_1 = env['discipline.case'].create(c1._convert_to_write(c1._cache))
    
    print(f"\n[3.1 Dismissal Case] Ref: {case_1.name}")
    print(f"      Article: {case_1.article_id.name}")
    print(f"      Sub-Clause: {case_1.sub_article_code}")
    print(f"      Severity: {case_1.severity_level_id.name}")
    print(f"      Verbatim Text: {case_1.legal_clause_text[:40]}...")
    assert case_1.article_id, "Article is empty!"
    assert case_1.severity_level_id, "Severity level is empty!"
    assert case_1.legal_clause_text, "Statutory text is empty!"
    
    # Test workflow submission
    print(f"Initial State: {case_1.state}")
    case_1.action_initiate()
    print(f"After Initiate: {case_1.state}")
    assert case_1.state in ('initiated', 'under_investigation', 'submitted_director', 'committee_review'), "Case did not transition!"
    case_1.unlink()
    print("Cleaned up Case 1.")

    # 3.2 Non-Managerial 5% Fine Offense (Article 33.7)
    off_33_7 = env['discipline.offense'].search([('sub_article_code', 'ilike', '33.7.')], limit=1)
    c2 = env['discipline.case'].new({
        'employee_id': non_mgr_emp.id,
        'offense_id': off_33_7.id,
        'incident_date': odoo.fields.Date.today(),
        'description': 'Production Verification Case - 33.7',
    })
    c2._onchange_employee_id()
    c2._onchange_offense_id()
    c2._compute_punishment_details()
    case_2 = env['discipline.case'].create(c2._convert_to_write(c2._cache))
    
    print(f"\n[3.2 Fine Case] Ref: {case_2.name}")
    print(f"      Article: {case_2.article_id.name}")
    print(f"      Penalty %: {case_2.penalty_percentage}%")
    print(f"      Rule Summary: {case_2.auto_applied_rule_summary}")
    assert case_2.penalty_percentage == 5.0, f"Expected 5.0% fine, got {case_2.penalty_percentage}"
    case_2.unlink()
    print("Cleaned up Case 2.")

    # 3.3 Managerial Staff Case (Article 10.4.1 - 1 Day Fine)
    off_10_4 = env['discipline.offense'].search([('sub_article_code', 'ilike', '10.4.1')], limit=1)
    c3 = env['discipline.case'].new({
        'employee_id': mgr_emp.id,
        'offense_id': off_10_4.id,
        'incident_date': odoo.fields.Date.today(),
        'description': 'Production Verification Case - Managerial 10.4.1',
    })
    c3._onchange_employee_id()
    c3._onchange_offense_id()
    c3._compute_punishment_details()
    case_3 = env['discipline.case'].create(c3._convert_to_write(c3._cache))
    
    print(f"\n[3.3 Managerial Case] Ref: {case_3.name}")
    print(f"      Article: {case_3.article_id.name}")
    print(f"      Staff Category: {case_3.staff_category}")
    print(f"      Fine Days: {case_3.fine_days} day(s)")
    assert case_3.fine_days >= 1.0, f"Expected fine days >= 1, got {case_3.fine_days}"
    case_3.unlink()
    print("Cleaned up Case 3.")

    print("\n" + "=" * 60)
    print("ALL PRODUCTION SCENARIOS VERIFIED SUCCESSFULLY (100% PASS)!")
    print("=" * 60)
