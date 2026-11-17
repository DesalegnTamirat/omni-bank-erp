import sys
sys.path.append('d:/projects/odoo19/source/odoo')
import odoo
from odoo.tools import config

config.parse_config(['-c', 'd:/projects/odoo19/config/odoo.conf'])
registry = odoo.modules.registry.Registry('odoo_dev')

with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    
    # 1. Inspect existing jobs and grades
    Job = env['hr.job']
    Grade = env['employee.grade']
    Rule = env['hr.salary.rule']
    Structure = env['hr.payroll.structure']
    GradeRule = env['grade.salary.rule']
    PosRule = env['position.salary.rule']
    Line = env['pbms.plan.category.line']

    sample_grade = Grade.search([], limit=1)
    sample_job = Job.search([], limit=1)
    print(f"Sample Grade: {sample_grade.display_name if sample_grade else 'None'} (Base: {sample_grade.base_salary if sample_grade else 0})")
    print(f"Sample Job: {sample_job.name if sample_job else 'None'}")

    # Find or setup ALW rules
    alw_rule_grade = Rule.search([('category_id.code', '=', 'ALW')], limit=1)
    alw_rule_pos = Rule.search([('category_id.code', '=', 'ALW'), ('id', '!=', alw_rule_grade.id)], limit=1)
    alw_rule_both = Rule.search([('category_id.code', '=', 'ALW'), ('id', 'not in', [alw_rule_grade.id, alw_rule_pos.id])], limit=1)
    
    print(f"ALW Rule 1 (Grade): {alw_rule_grade.code} - {alw_rule_grade.name}")
    print(f"ALW Rule 2 (Pos): {alw_rule_pos.code} - {alw_rule_pos.name}")
    print(f"ALW Rule 3 (Both): {alw_rule_both.code} - {alw_rule_both.name}")

    # Ensure structure includes them
    if sample_grade.salary_structure:
        current_rules = sample_grade.salary_structure.rule_ids
        rules_to_add = (alw_rule_grade | alw_rule_pos | alw_rule_both) - current_rules
        if rules_to_add:
            sample_grade.salary_structure.write({'rule_ids': [(4, r.id) for r in rules_to_add]})
            print(f"Added {len(rules_to_add)} rules to structure {sample_grade.salary_structure.name}")

    # Setup Direction 1: Grade rule
    existing_gr = GradeRule.search([('salary_rule_id', '=', alw_rule_grade.id), ('grade2', '=', sample_grade.id)])
    if not existing_gr:
        existing_gr = GradeRule.create({
            'salary_rule_id': alw_rule_grade.id,
            'grade2': sample_grade.id,
            'value': 2500.0,
        })
    else:
        existing_gr.write({'value': 2500.0})
    print(f"Configured Grade Rule: {alw_rule_grade.code} for grade {sample_grade.display_name} = 2,500.00")

    # Setup Direction 2: Position rule
    existing_pr = PosRule.search([('salary_rule_id', '=', alw_rule_pos.id), ('position', '=', sample_job.id), ('grade_id', '=', False)])
    if not existing_pr:
        existing_pr = PosRule.create({
            'salary_rule_id': alw_rule_pos.id,
            'position': sample_job.id,
            'grade_id': False,
            'value': 3500.0,
        })
    else:
        existing_pr.write({'value': 3500.0})
    print(f"Configured Position Rule: {alw_rule_pos.code} for position {sample_job.name} = 3,500.00")

    # Setup Direction 3: Both Position + Grade rule
    existing_both = PosRule.search([('salary_rule_id', '=', alw_rule_both.id), ('position', '=', sample_job.id), ('grade_id', '=', sample_grade.id)])
    if not existing_both:
        existing_both = PosRule.create({
            'salary_rule_id': alw_rule_both.id,
            'position': sample_job.id,
            'grade_id': sample_grade.id,
            'value': 4000.0,
        })
    else:
        existing_both.write({'value': 4000.0})
    print(f"Configured Pos+Grade Rule: {alw_rule_both.code} for pos {sample_job.name} + grade {sample_grade.display_name} = 4,000.00")

    # Now create a test workforce line or test compute on new record
    test_line = Line.new({
        'line_type': 'manpower',
        'position_type': 'existing',
        'job_id': sample_job.id,
        'job_grade_id': sample_grade.id,
        'pension_rate': 11.0,
        'q1': 1,
        'q2': 1,
        'q3': 1,
        'q4': 1,
    })
    print("test_line created. Calling _compute_base_salary...")
    test_line._compute_base_salary()
    print("Calling _compute_monthly_allowance...")
    test_line._compute_monthly_allowance()
    print("Calling _compute_compensation_breakdown...")
    test_line._compute_compensation_breakdown()

    print("\n--- TEST RESULTS ---")
    print(f"Base Salary: {test_line.base_salary:,.2f}")
    print(f"Monthly Allowance: {test_line.monthly_allowance:,.2f} (Expected: 10,000.00 = 2,500 + 3,500 + 4,000)")
    print(f"Allowance Breakdown: {test_line.allowance_breakdown}")
    print(f"Pension (11%): {test_line.monthly_pension:,.2f}")
    print(f"Monthly Total Compensation: {test_line.monthly_total_compensation:,.2f}")
    print(f"Annual Unit Cost: {test_line.unit_cost:,.2f}")

    expected_allowance = 2500.0 + 3500.0 + 4000.0
    expected_pension = (test_line.base_salary or 0.0) * 0.11
    expected_total = (test_line.base_salary or 0.0) + expected_allowance + expected_pension
    assert abs(test_line.monthly_allowance - expected_allowance) < 0.01, f"Monthly allowance mismatch: {test_line.monthly_allowance} != {expected_allowance}"
    assert abs(test_line.monthly_total_compensation - expected_total) < 0.01, f"Total compensation mismatch: {test_line.monthly_total_compensation} != {expected_total}"
    print("\nALL ASSERTIONS PASSED SUCCESSFULLY!")

    cr.rollback()
    print("Database transaction rolled back cleanly.")
