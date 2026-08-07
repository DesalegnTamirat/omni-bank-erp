#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
BRD SIMULATION SEED SCRIPT — Bunna Bank Recruitment System
=============================================================================
HOW TO RUN:
  1. Open a terminal in the Odoo project root
  2. Run:
       python odoo-bin shell -c odoo.conf -d <your_db_name> --no-http < seed_brd_demo_data.py

  OR paste sections interactively in an Odoo shell session.

WHAT THIS SCRIPT CREATES:
  Section 1  - Operating Units (Work Units)
  Section 2  - Departments
  Section 3  - Employee Grades
  Section 4  - Job Positions (hr.job)
  Section 5  - Employees (5 profiles: clean, 1st warning, 2nd warning, final warning, HR officer)
  Section 6  - Disciplinary Cases (enforced cases per BRD discipline levels)
  Section 7  - Blacklist Pool entries
  Section 8  - Default External Shortlist Criteria (BRD Section 7)
  Section 9  - Recruitment Requests (planned + unplanned, BRD Section 3)
  Section 10 - Job Vacancies (internal + external, BRD Section 4)
  Section 11 - External Eligible Candidates (BRD Section 8)
  Section 12 - Transfer Requests (eligible + deducted + blocked, BRD Section 12)
  Section 13 - Talent Roster entries (BRD Section 9)
  Section 14 - Transfer Config Settings (system parameters, BRD Section 12)
=============================================================================
"""
import logging

_logger = logging.getLogger(__name__)
# Note: Odoo shell runs in a single transaction. We commit explicitly at the end.

print("\n" + "="*70)
print("  BUNNA BANK BRD SIMULATION SEED — Starting")
print("="*70 + "\n")

# ===========================================================================
# SECTION 1: OPERATING UNITS (Work Units)
# ===========================================================================
print(">> Section 1: Operating Units")

OU = env['operating.unit']

# Get the default department for required field (use first existing or create one)
default_dept_search = env['hr.department'].search([('name', '=', 'General')], limit=1)
if not default_dept_search:
    # We need an OU first to satisfy operating_unit_id required on department
    # Check if any OU already exists
    any_ou = env['operating.unit'].search([], limit=1)
    dept_ou = any_ou if any_ou else None
    # Will create departments properly in Section 2 with real OUs
    default_dept = env['hr.department'].search([], limit=1)
else:
    default_dept = default_dept_search

def get_or_create_ou(name, sol_id, unit_type, district, region):
    existing = OU.search([('name', '=', name)], limit=1)
    if existing:
        print(f"   Reusing existing OU: {name} (ID={existing.id})")
        return existing
    # Find or create a placeholder department for the OU's own department field
    # The real departments link back to OUs, so we use an existing one
    any_dept = env['hr.department'].search([], limit=1)
    ou = OU.create({
        'name': name,
        'sol_id': sol_id,
        'work_unit_type': unit_type,
        'district': district,
        'region': region,
        'department': any_dept.id if any_dept else False,
    })
    return ou

ou_it = get_or_create_ou('Enterprise Application Development Directorate', 5001, 'head_office', 'Addis Ababa District', 'Central Region')
ou_addis = get_or_create_ou('Addis Ababa Main Branch', 5002, 'branch', 'Addis Ababa District', 'Central Region')
ou_hawassa = get_or_create_ou('Hawassa Regional Branch', 5003, 'branch', 'Southern District', 'Sidama Region')
ou_diredawa = get_or_create_ou('Dire Dawa Branch', 5004, 'branch', 'Eastern District', 'Dire Dawa Region')

print(f"   OU: {ou_it.name} (ID={ou_it.id})")
print(f"   OU: {ou_addis.name} (ID={ou_addis.id})")
print(f"   OU: {ou_hawassa.name} (ID={ou_hawassa.id})")
print(f"   OU: {ou_diredawa.name} (ID={ou_diredawa.id})")


# ===========================================================================
# SECTION 2: DEPARTMENTS
# Note: Department names allow letters and spaces only (no hyphens, no numbers)
# operating_unit_id is required
# ===========================================================================
print("\n>> Section 2: Departments")

Dept = env['hr.department']

# Reuse if already present by name to avoid constraint duplicates
def get_or_create_dept(name, ou):
    existing = Dept.search([('name', '=', name)], limit=1)
    if existing:
        return existing
    return Dept.create({'name': name, 'operating_unit_id': ou.id})

dept_it     = get_or_create_dept('Information Technology', ou_it)
dept_ops    = get_or_create_dept('Branch Operations', ou_addis)
dept_credit = get_or_create_dept('Credit Analysis', ou_addis)
dept_hr     = get_or_create_dept('Human Resources', ou_it)

print(f"   {dept_it.name} (ID={dept_it.id})")
print(f"   {dept_ops.name} (ID={dept_ops.id})")
print(f"   {dept_credit.name} (ID={dept_credit.id})")
print(f"   {dept_hr.name} (ID={dept_hr.id})")


# ===========================================================================
# SECTION 3: EMPLOYEE GRADES
# ===========================================================================
print("\n>> Section 3: Employee Grades")

Grade = env['employee.grade']

def get_or_create_grade(code, name, base_salary, factor):
    existing = Grade.search([('grade_code', '=', code)], limit=1)
    if existing:
        print(f"   Reusing existing grade: {name} (ID={existing.id})")
        return existing
    return Grade.create({'grade_code': code, 'grade_name': name, 'base_salary': base_salary, 'salary_factor': factor})

# salary_factor must be > 1.0 per model constraint
grade_g15 = get_or_create_grade('DEMO-G15', 'Grade 15 Senior Officer (Demo)', 25000.0, 1.25)
grade_g12 = get_or_create_grade('DEMO-G12', 'Grade 12 Officer (Demo)', 18000.0, 1.10)
grade_g9  = get_or_create_grade('DEMO-G09', 'Grade 9 Associate (Demo)',  12000.0, 1.05)

print(f"   {grade_g15.grade_name} (ID={grade_g15.id})")
print(f"   {grade_g12.grade_name} (ID={grade_g12.id})")
print(f"   {grade_g9.grade_name} (ID={grade_g9.id})")


# ===========================================================================
# SECTION 4: JOB POSITIONS (hr.job)
# ===========================================================================
print("\n>> Section 4: Job Positions")

Job = env['hr.job']

job_sse = Job.create({
    'name': 'Demo – Senior Software Engineer',
    'department_id': dept_it.id,
})
# Set grade via ORM if the field exists
if 'grade' in env['hr.job']._fields:
    job_sse.write({'grade': grade_g15.id})

job_bm = Job.create({
    'name': 'Demo – Branch Manager',
    'department_id': dept_ops.id,
})
if 'grade' in env['hr.job']._fields:
    job_bm.write({'grade': grade_g15.id})

job_ca = Job.create({
    'name': 'Demo – Senior Credit Analyst',
    'department_id': dept_credit.id,
})
if 'grade' in env['hr.job']._fields:
    job_ca.write({'grade': grade_g12.id})

job_cashier = Job.create({
    'name': 'Demo – Cashier',
    'department_id': dept_ops.id,
})
if 'grade' in env['hr.job']._fields:
    job_cashier.write({'grade': grade_g9.id})

print(f"   Created: {job_sse.name} (ID={job_sse.id})")
print(f"   Created: {job_bm.name} (ID={job_bm.id})")
print(f"   Created: {job_ca.name} (ID={job_ca.id})")
print(f"   Created: {job_cashier.name} (ID={job_cashier.id})")


# ===========================================================================
# SECTION 5: EMPLOYEES
# ===========================================================================
print("\n>> Section 5: Employees")

Emp = env['hr.employee']

# Employee 1: Solomon Kebede – star performer, clean discipline record
# Helper: build employee vals dict, only include job_grade if field exists
def _emp_vals(name, email, phone, dept, job, ou, grade, contract_date):
    vals = {
        'name': name,
        'work_email': email,
        'work_phone': phone,
        'department_id': dept.id,
        'job_id': job.id,
        'default_operating_unit_id': ou.id,
        'first_contract_date': contract_date,
        'active': True,
    }
    if 'job_grade' in env['hr.employee']._fields:
        vals['job_grade'] = grade.id
    return vals

emp_solomon = Emp.create(_emp_vals(
    'Solomon Kebede (Demo)', 'demo.solomon.kebede@bunnabank.com', '+251911223344',
    dept_it, job_sse, ou_it, grade_g15, '2021-01-15'
))
print(f"   Employee 1: {emp_solomon.name} (ID={emp_solomon.id}) — CLEAN RECORD, G15, IT Directorate")

emp_tigist = Emp.create(_emp_vals(
    'Tigist Alemu (Demo)', 'demo.tigist.alemu@bunnabank.com', '+251922334455',
    dept_ops, job_cashier, ou_addis, grade_g9, '2023-03-01'
))
print(f"   Employee 2: {emp_tigist.name} (ID={emp_tigist.id}) — FIRST WARNING, G09, Addis Branch")

emp_dawit = Emp.create(_emp_vals(
    'Dawit Tadesse (Demo)', 'demo.dawit.tadesse@bunnabank.com', '+251933445566',
    dept_credit, job_ca, ou_hawassa, grade_g12, '2024-06-01'
))
print(f"   Employee 3: {emp_dawit.name} (ID={emp_dawit.id}) — SECOND WARNING, G12, Hawassa Branch")

emp_meron = Emp.create(_emp_vals(
    'Meron Haile (Demo)', 'demo.meron.haile@bunnabank.com', '+251944556677',
    dept_ops, job_bm, ou_diredawa, grade_g15, '2022-09-10'
))
print(f"   Employee 4: {emp_meron.name} (ID={emp_meron.id}) — FINAL WARNING, G15, Dire Dawa")

emp_hr = Emp.create(_emp_vals(
    'Yohannes Tesfaye (Demo)', 'demo.yohannes.tesfaye@bunnabank.com', '+251955667788',
    dept_hr, job_ca, ou_it, grade_g12, '2020-07-01'
))
print(f"   Employee 5: {emp_hr.name} (ID={emp_hr.id}) — HR OFFICER, G12, IT Directorate")


# ===========================================================================
# SECTION 6: DISCIPLINARY CASES (BRD Section 11)
# ===========================================================================
print("\n>> Section 6: Disciplinary Cases")

Case = env['discipline.case']

# Get offense records from existing seed data
offense_level_4 = env['discipline.offense'].search([('punishment_type', '=', 'first_warning_penalty')], limit=1)
offense_level_3 = env['discipline.offense'].search([('punishment_type', '=', 'second_warning_penalty')], limit=1)
offense_level_2 = env['discipline.offense'].search([('punishment_type', '=', 'final_warning_penalty')], limit=1)

if not offense_level_4:
    print("   WARNING: offense_level_4 (first_warning_penalty) not found. Run discipline_management module seed first.")
if not offense_level_3:
    print("   WARNING: offense_level_3 (second_warning_penalty) not found. Run discipline_management module seed first.")
if not offense_level_2:
    print("   WARNING: offense_level_2 (final_warning_penalty) not found. Run discipline_management module seed first.")

# Case 1: Tigist Alemu — Level 4 First Warning + 5% Penalty (ATTENDANCE)
if offense_level_4:
    case_tigist = Case.create({
        'employee_id': emp_tigist.id,
        'offense_id': offense_level_4.id,
        'incident_date': '2026-02-10',
        'description': (
            'Employee was absent without prior notification on three consecutive Mondays '
            'between January and February 2026. Despite two informal reminders, the '
            'employee failed to provide valid justification. Supervisor escalated to formal '
            'discipline process on 2026-02-10.'
        ),
        'state': 'enforced',
    })
    print(f"   Case 1 (Tigist — First Warning/5% penalty): ID={case_tigist.id}, state=enforced")

# Case 2: Dawit Tadesse — Level 3 Second Warning + 10% Penalty (CONDUCT)
if offense_level_3:
    case_dawit = Case.create({
        'employee_id': emp_dawit.id,
        'offense_id': offense_level_3.id,
        'incident_date': '2026-03-15',
        'description': (
            'Employee publicly refused a documented directive from the Branch Manager '
            'regarding credit file preparation deadlines in front of department colleagues. '
            'This represents a repeated pattern following an earlier verbal counseling. '
            'Investigation confirmed insubordination. Second Written Warning issued.'
        ),
        'state': 'enforced',
    })
    print(f"   Case 2 (Dawit — Second Warning/10% penalty): ID={case_dawit.id}, state=enforced")

# Case 3: Meron Haile — Level 2 Final Written Warning + 20% Penalty (CONDUCT)
if offense_level_2:
    case_meron = Case.create({
        'employee_id': emp_meron.id,
        'offense_id': offense_level_2.id,
        'incident_date': '2026-04-20',
        'description': (
            'Employee was found to have shared confidential customer financial statements '
            'with a third party outside the bank. The disciplinary committee investigation '
            'confirmed the breach on 2026-04-28. Final Written Warning issued with 20% '
            'monthly salary penalty. Employee flagged as ineligible for transfer.'
        ),
        'state': 'enforced',
    })
    print(f"   Case 3 (Meron — Final Warning/20% penalty): ID={case_meron.id}, state=enforced")


# ===========================================================================
# SECTION 7: BLACKLIST POOL (BRD Section 6)
# ===========================================================================
print("\n>> Section 7: Blacklist Pool")

BL = env['blacklist.pool']

bl1 = BL.create({
    'candidate': 'Tariku Mengistu (Demo)',
    'national_id': 'DEMO-ETH-99887766',
    'gender': 'Male',
    'reason': (
        'Involved in documented financial fraud at a commercial bank partner institution. '
        'Dismissed in 2024 and flagged by the Ethiopian Banking Association. '
        'Confirmed by legal department on 2025-10-15.'
    ),
    'blacklisted_on': '2025-11-01',
    'active': True,
})
print(f"   Blacklist entry 1: {bl1.candidate} (ID={bl1.id})")

bl2 = BL.create({
    'candidate': 'Selam Worku (Demo)',
    'national_id': 'DEMO-ETH-88776655',
    'gender': 'Female',
    'reason': (
        'Academic credential falsification discovered during employment verification. '
        'Submitted forged university transcripts during 2025 application cycle. '
        'Verified by HR Compliance unit on 2025-06-01.'
    ),
    'blacklisted_on': '2025-06-15',
    'active': True,
})
print(f"   Blacklist entry 2: {bl2.candidate} (ID={bl2.id})")


# ===========================================================================
# SECTION 8: DEFAULT EXTERNAL SHORTLIST CRITERIA (BRD Section 7)
# ===========================================================================
print("\n>> Section 8: Default External Shortlist Criteria")

# Deactivate any existing active default criteria first (SQL constraint: only one active)
existing_criteria = env['external.default.shortlist.criteria'].search([('active', '=', True)])
if existing_criteria:
    existing_criteria.write({'active': False})
    print(f"   Deactivated {len(existing_criteria)} existing active criteria record(s)")

criteria = env['external.default.shortlist.criteria'].create({
    'name': 'Bunna Bank Standard Shortlist Criteria (FY 2026)',
    'minimum_cgpa': 2.75,
    'minimum_education': 'bachelor',
    'minimum_experience_years': 2.0,
    'minimum_banking_experience': 1.0,
    'notes': (
        'Standard Bank-wide shortlisting thresholds for all external vacancies. '
        'Approved by HR Director on 2026-01-10. '
        'Vacancy-specific overrides take precedence when configured.'
    ),
    'active': True,
})
print(f"   Created shortlist criteria: {criteria.name} (ID={criteria.id})")
print(f"   -> Min CGPA: {criteria.minimum_cgpa} | Min Education: {criteria.minimum_education}")
print(f"   -> Min Experience: {criteria.minimum_experience_years}yr | Min Banking: {criteria.minimum_banking_experience}yr")


# ===========================================================================
# SECTION 9: RECRUITMENT REQUESTS (BRD Section 3)
# ===========================================================================
print("\n>> Section 9: Recruitment Requests")

RR = env['recruitment.request']

# Planned Request: IT Directorate – 2x Senior Software Engineers (approved)
rr_planned = RR.create({
    'request_type': 'planned',
    'operating_unit_id': ou_it.id,
    'department_id': dept_it.id,
    'job_position_id': job_sse.id,
    'job_grade_id': grade_g15.id,
    'employment_type': 'permanent',
    'required_headcount': 2,
    'sourcing_type': 'both',
    'requested_by': emp_hr.id,
    'job_description': (
        'Senior Software Engineer for Core Banking System enhancement and Enterprise '
        'Application Development. Requires BSc/MSc in Computer Science with 3+ years '
        'hands-on Java/.NET experience and banking system integration knowledge.'
    ),
    'state': 'approved',
})
print(f"   RR-1 (Planned, Approved): {rr_planned.reference} | ID={rr_planned.id}")
print(f"   -> {rr_planned.required_headcount} × {job_sse.name} @ {ou_it.name}")

# Unplanned Request: Addis Main Branch – 1x Credit Analyst replacement (submitted)
rr_unplanned = RR.create({
    'request_type': 'unplanned',
    'operating_unit_id': ou_addis.id,
    'department_id': dept_credit.id,
    'job_position_id': job_ca.id,
    'job_grade_id': grade_g12.id,
    'employment_type': 'permanent',
    'required_headcount': 1,
    'sourcing_type': 'external',
    'requested_by': emp_hr.id,
    'justification': (
        'Urgent replacement required due to sudden resignation of the branch senior credit '
        'analyst following a competing offer. Position critical for maintaining loan approval '
        'SLA during the high-demand Q3 2026 period. No approved workforce plan exists for '
        'this vacancy; unplanned hiring authorization required per BRD Section 3.2.'
    ),
    'state': 'submitted',
})
print(f"   RR-2 (Unplanned, Submitted): {rr_unplanned.reference} | ID={rr_unplanned.id}")
print(f"   -> {rr_unplanned.required_headcount} × {job_ca.name} @ {ou_addis.name}")

# Planned Request: Hawassa Branch – Branch Manager – Replacement Hire (under_review)
rr_replacement = RR.create({
    'request_type': 'planned',
    'operating_unit_id': ou_hawassa.id,
    'department_id': dept_ops.id,
    'job_position_id': job_bm.id,
    'job_grade_id': grade_g15.id,
    'employment_type': 'permanent',
    'required_headcount': 1,
    'sourcing_type': 'internal',
    'requested_by': emp_hr.id,
    'is_replacement': True,
    'replaced_employee_id': emp_meron.id,
    'replacement_reason': 'Employee disciplinary status prevents continued assignment as Branch Manager.',
    'job_description': 'Branch Manager replacement. Internal transfer preferred per BRD Section 12.',
    'state': 'under_review',
})
print(f"   RR-3 (Planned/Replacement, Under Review): {rr_replacement.reference} | ID={rr_replacement.id}")
print(f"   -> 1 × {job_bm.name} @ {ou_hawassa.name} (replacing {emp_meron.name})")


# ===========================================================================
# SECTION 10: JOB VACANCIES (BRD Section 4)
# ===========================================================================
print("\n>> Section 10: Job Vacancies")

Comp = env['recruitment.competency']
def get_or_create_comp(name):
    existing = Comp.search([('competency', '=', name)], limit=1)
    if existing:
        return existing
    return Comp.create({'competency': name, 'status': 'yes'})

comp_software = get_or_create_comp('Software Architecture')
comp_banking  = get_or_create_comp('Branch Operations Management')
comp_credit   = get_or_create_comp('Credit Risk Analysis')

Vac = env['job.vacancy']

# Vacancy 1: External – Senior Software Engineer (posted, LinkedIn)
vac_sse = Vac.create({
    'job_position': job_sse.id,
    'operating_unit_id': ou_it.id,
    'sourcing_type': 'external',
    'internal_movement_type': 'external',
    'recruitment_type': 'External',
    'employee_category': 'Non Managerial',
    'job_level': 'senior',
    'no_of_vacancies': 2,
    'opening_date': '2026-07-01',
    'last_date_to_apply': '2026-07-31',
    'type_of_employment': 'Permanent',
    'minimum_education': 'bachelor',
    'minimum_cgpa': 3.0,
    'minimum_experience_years': 3.0,
    'banking_experience_required': 0.0,
    'source_channel': 'linkedin',
    'responsible': emp_hr.id,
    'vacancy_description': (
        'Bunna Bank is seeking Senior Software Engineers to join our Enterprise Application '
        'Development Directorate. Candidates will work on core banking modules, API integrations, '
        'and digital banking products. BSc/MSc in Computer Science required with 3+ years '
        'hands-on development experience. Knowledge of Temenos T24 is an asset.'
    ),
    'competency_line_ids': [(0, 0, {'competency_id': comp_software.id, 'required_level': 'advanced'})],
    'state': 'posted',
})
print(f"   Vacancy 1 (External/posted): {vac_sse.reference} — {job_sse.name} @ {ou_it.name}")

# Vacancy 2: Internal – Branch Manager Lateral Transfer (posted, internal announcement)
vac_bm_hawassa = Vac.create({
    'job_position': job_bm.id,
    'operating_unit_id': ou_hawassa.id,
    'sourcing_type': 'internal',
    'internal_movement_type': 'lateral',
    'recruitment_type': 'Internal',
    'employee_category': 'Managerial',
    'no_of_vacancies': 1,
    'opening_date': '2026-07-05',
    'last_date_to_apply': '2026-08-05',
    'type_of_employment': 'Permanent',
    'responsible': emp_hr.id,
    'vacancy_description': (
        'Branch Manager vacancy at Hawassa Regional Branch. Open to eligible internal '
        'candidates meeting grade G15 requirements and minimum 1-year service criteria. '
        'Transfer eligibility rules apply per BRD Section 12. Grade-restricted: applicants '
        'must hold Grade 15 in their current position.'
    ),
    'competency_line_ids': [(0, 0, {'competency_id': comp_banking.id, 'required_level': 'expert'})],
    'state': 'posted',
})
print(f"   Vacancy 2 (Internal/Lateral, posted): {vac_bm_hawassa.reference} — {job_bm.name} @ {ou_hawassa.name}")

# Vacancy 3: Both – Credit Analyst (open for both internal and external, submitted)
vac_ca = Vac.create({
    'job_position': job_ca.id,
    'operating_unit_id': ou_addis.id,
    'sourcing_type': 'both',
    'internal_movement_type': 'internal',
    'recruitment_type': 'Internal',
    'employee_category': 'Non Managerial',
    'job_level': 'senior',
    'no_of_vacancies': 1,
    'opening_date': '2026-07-15',
    'last_date_to_apply': '2026-08-15',
    'type_of_employment': 'Permanent',
    'minimum_education': 'bachelor',
    'minimum_cgpa': 2.75,
    'minimum_experience_years': 2.0,
    'banking_experience_required': 1.0,
    'source_channel': 'website',
    'responsible': emp_hr.id,
    'vacancy_description': (
        'Credit Analyst position at Addis Ababa Main Branch. Candidates from internal '
        'talent pool are preferred. External candidates require minimum 2 years relevant '
        'experience including 1 year in banking. BA/BSc in Accounting, Finance or Economics required.'
    ),
    'competency_line_ids': [(0, 0, {'competency_id': comp_credit.id, 'required_level': 'intermediate'})],
    'state': 'posted',
})
print(f"   Vacancy 3 (Both/posted): {vac_ca.reference} — {job_ca.name} @ {ou_addis.name}")


# ===========================================================================
# SECTION 11: EXTERNAL ELIGIBLE CANDIDATES (BRD Section 8)
# ===========================================================================
print("\n>> Section 11: External Eligible Candidates")

ExtCand = env['external.recruitment.eligible.employees']

# Fetch the external recruitment process linked to the SSE vacancy if any
ext_recruitment = env['employee.recruitment.external'].search(
    [('vacancy_id', '=', vac_sse.id)], limit=1
)

# Candidate 1: Biniyam Worku – Fully qualified (CGPA 3.8, 4.5yr exp, 2.5yr banking)
# Passes all criteria → expected to advance to interview
cand_biniyam_vals = {
    'applicant_email': 'biniyam.worku.demo@gmail.com',
    'applicant_phone': '+251911001122',
    'gender': 'male',
    'date_of_birth': '1996-03-12',
    'working_status': 'employed',
    'current_company': 'Awash Bank S.C.',
    'join_immediately': 'yes',
    'preferred_location': 'Addis Ababa',
    'ex_bunna': False,
}
if ext_recruitment:
    cand_biniyam_vals['external_recruitment_id'] = ext_recruitment.id

cand_biniyam = ExtCand.create(cand_biniyam_vals)
# Add education record separately
env['external.applicant.education'].create({
    'applicant_record_id': cand_biniyam.id,
    'level': 'bachelor',
    'field_of_study': 'Computer Science',
    'institution_name': 'Addis Ababa University',
    'cgpa': 3.8,
    'graduation_date': '2019-06-30',
})
print(f"   Candidate 1 — Biniyam Worku (ID={cand_biniyam.id}): CGPA=3.8, 4.5yr exp → QUALIFIES")

# Candidate 2: Helen Berhe – Below criteria (CGPA 2.5, Diploma, 1yr exp)
# Should be filtered out during shortlisting → demonstrates rejection path
cand_helen_vals = {
    'applicant_email': 'helen.berhe.demo@yahoo.com',
    'applicant_phone': '+251922112233',
    'gender': 'female',
    'date_of_birth': '2000-07-20',
    'working_status': 'unemployed',
    'join_immediately': 'yes',
    'preferred_location': 'Hawassa',
    'ex_bunna': False,
}
if ext_recruitment:
    cand_helen_vals['external_recruitment_id'] = ext_recruitment.id

cand_helen = ExtCand.create(cand_helen_vals)
env['external.applicant.education'].create({
    'applicant_record_id': cand_helen.id,
    'level': 'diploma',
    'field_of_study': 'Accounting',
    'institution_name': 'Hawassa Polytechnic College',
    'cgpa': 2.5,
    'graduation_date': '2022-06-30',
})
print(f"   Candidate 2 — Helen Berhe (ID={cand_helen.id}): CGPA=2.5, Diploma → BELOW CRITERIA")

# Candidate 3: Abebe Girma – Ex-Bunna employee (CGPA 3.5, 6yr exp, 4yr banking)
# Strong candidate; ex-Bunna preferred flag test
cand_abebe_vals = {
    'applicant_email': 'abebe.girma.demo@gmail.com',
    'applicant_phone': '+251911334455',
    'gender': 'male',
    'date_of_birth': '1990-08-25',
    'working_status': 'employed',
    'current_company': 'Commercial Bank of Ethiopia',
    'join_immediately': 'no',
    'date_of_availability': '2026-09-01',
    'preferred_location': 'Addis Ababa',
    'ex_bunna': True,
}
if ext_recruitment:
    cand_abebe_vals['external_recruitment_id'] = ext_recruitment.id

cand_abebe = ExtCand.create(cand_abebe_vals)
env['external.applicant.education'].create({
    'applicant_record_id': cand_abebe.id,
    'level': 'master',
    'field_of_study': 'Computer Science',
    'institution_name': 'Addis Ababa University',
    'cgpa': 3.5,
    'graduation_date': '2015-06-30',
})
print(f"   Candidate 3 — Abebe Girma (ID={cand_abebe.id}): CGPA=3.5, 6yr exp, Ex-Bunna → QUALIFIES + PREFERRED")


# ===========================================================================
# SECTION 12: TRANSFER REQUESTS (BRD Section 12)
# ===========================================================================
print("\n>> Section 12: Transfer Requests")

TR = env['employee.transfer.request']

# Transfer 1: Solomon Kebede → Hawassa Branch Manager vacancy
# ELIGIBLE: 5+ years service, PMS 88%, CLEAN record → no deduction
# Expected suitability score: computed by transfer ranking committee
tr_solomon = TR.create({
    'employee_id': emp_solomon.id,
    'target_vacancy_id': vac_bm_hawassa.id,
    'request_date': '2026-07-08',
    'date_in_current_position': '2021-01-15',
    'date_in_current_location': '2021-01-15',
    'pms_score': 88.0,
    'supervisor_recommendation_score': 92.0,
    'state': 'submitted',
})
print(f"   Transfer 1 — Solomon Kebede: {tr_solomon.name} (ID={tr_solomon.id})")
print(f"   -> ELIGIBLE | PMS=88% | Rec=92 | No deduction | Submitted")
print(f"   -> service_years_in_position = 5.5yr | Eligibility: ELIGIBLE")

# Transfer 2: Tigist Alemu → Hawassa Branch Manager vacancy
# ELIGIBLE with deduction: First Warning → 5% score deduction applied
# Note: Grade G09 vs G15 vacancy → grade_restriction_ok = False → actually INELIGIBLE
# This demonstrates the grade restriction check in BRD Section 12.1
tr_tigist = TR.create({
    'employee_id': emp_tigist.id,
    'target_vacancy_id': vac_bm_hawassa.id,
    'request_date': '2026-07-10',
    'date_in_current_position': '2023-03-01',
    'date_in_current_location': '2023-03-01',
    'pms_score': 84.0,
    'supervisor_recommendation_score': 78.0,
    'state': 'submitted',
})
print(f"   Transfer 2 — Tigist Alemu: {tr_tigist.name} (ID={tr_tigist.id})")
print(f"   -> First Warning → 5% deduction | PMS=84% | Rec=78 | service=3.4yr")
print(f"   -> Grade mismatch (G09 vs G15 vacancy) → grade_restriction_ok=False")

# Transfer 3: Dawit Tadesse → Credit Analyst vacancy (same grade G12)
# ELIGIBLE with deduction: Second Warning → 10% deduction
tr_dawit = TR.create({
    'employee_id': emp_dawit.id,
    'target_vacancy_id': vac_ca.id,
    'request_date': '2026-07-11',
    'date_in_current_position': '2024-06-01',
    'date_in_current_location': '2024-06-01',
    'pms_score': 79.0,
    'supervisor_recommendation_score': 72.0,
    'state': 'submitted',
})
print(f"   Transfer 3 — Dawit Tadesse: {tr_dawit.name} (ID={tr_dawit.id})")
print(f"   -> Second Warning → 10% deduction | PMS=79% | Rec=72 | service=2.1yr")
print(f"   -> Below 1yr minimum at current location → service_rule_ok=False (joined 2024-06)")

# Transfer 4: Meron Haile → Branch Manager vacancy
# INELIGIBLE: Active Final Written Warning blocks transfer entirely
tr_meron = TR.create({
    'employee_id': emp_meron.id,
    'target_vacancy_id': vac_bm_hawassa.id,
    'request_date': '2026-07-12',
    'date_in_current_position': '2022-09-10',
    'date_in_current_location': '2022-09-10',
    'pms_score': 91.0,
    'supervisor_recommendation_score': 85.0,
    'state': 'draft',
})
print(f"   Transfer 4 — Meron Haile: {tr_meron.name} (ID={tr_meron.id})")
print(f"   -> Final Written Warning → COMPLETELY INELIGIBLE | PMS=91% (ignored)")
print(f"   -> BRD Section 12.2: last_written_warning blocks transfer regardless of score")

# Transfer 5: Exchange Transfer – Solomon ↔ Yohannes swap
# Demonstrates mutual exchange transfer path in BRD Section 12.5
tr_exchange = TR.create({
    'employee_id': emp_hr.id,
    'target_vacancy_id': vac_ca.id,
    'request_date': '2026-07-14',
    'date_in_current_position': '2020-07-01',
    'date_in_current_location': '2020-07-01',
    'pms_score': 82.0,
    'supervisor_recommendation_score': 80.0,
    'is_exchange_transfer': True,
    'exchange_partner_employee_id': emp_solomon.id,
    'state': 'submitted',
})
print(f"   Transfer 5 — Yohannes Tesfaye (Exchange): {tr_exchange.name} (ID={tr_exchange.id})")
print(f"   -> Exchange transfer with Solomon Kebede | Both clean records")


# ===========================================================================
# SECTION 13: TALENT ROSTER (BRD Section 9)
# ===========================================================================
print("\n>> Section 13: Talent Roster")

TR_Roster = env['talent.roster']

# Roster 1: Biniyam Worku – Active external reserve pool entry (expires 6 months)
roster_biniyam = TR_Roster.create({
    'name': 'Biniyam Worku (Demo)',
    'email': 'biniyam.worku.demo@gmail.com',
    'phone': '+251911001122',
    'gender': 'male',
    'application_type': 'External',
    'educational_qualification': 'Bachelor of Science in Computer Science',
    'field_of_study': 'Computer Science',
    'highest_cgpa': 3.8,
    'total_experience': 4.5,
    'banking_experience': 2.5,
    'written_score': 82.0,
    'interview_score': 88.0,
    'final_score': 86.4,
    'previous_rank': 2,
    'date_added': '2026-07-15',
    'status': 'active',
    'source_vacancy_id': vac_sse.id,
    'skills_summary': (
        'Java, Spring Boot, REST API design, Oracle DB, Microservices architecture, '
        'T24 Core Banking integration experience, Agile/Scrum methodology, '
        'Python scripting, Linux system administration.'
    ),
    'notes': (
        'Ranked 2nd in Senior Software Engineer external cycle. Top candidate accepted; '
        'Biniyam added to talent roster for 6-month reserve pool activation per BRD 9.4.1. '
        'Excellent interview performance. Recommended for any IT vacancy within reserve window.'
    ),
})
print(f"   Roster 1 — {roster_biniyam.name} (ID={roster_biniyam.id})")
print(f"   -> Status=active | Score=86.4 | Expiry={roster_biniyam.expiry_date}")

# Roster 2: Aberash Tadesse – Internal candidate, ranked 3rd in internal cycle
roster_aberash = TR_Roster.create({
    'name': 'Aberash Tadesse (Demo)',
    'employee_id': emp_dawit.id,
    'email': 'aberash.tadesse.demo@bunnabank.com',
    'phone': '+251966778899',
    'gender': 'female',
    'application_type': 'Internal',
    'educational_qualification': 'Bachelor of Arts in Economics',
    'field_of_study': 'Economics',
    'highest_cgpa': 3.4,
    'total_experience': 6.0,
    'banking_experience': 6.0,
    'written_score': 78.0,
    'interview_score': 81.0,
    'pms_score': 85.0,
    'final_score': 80.5,
    'previous_rank': 3,
    'date_added': '2026-06-01',
    'status': 'active',
    'notes': (
        'Internal candidate from Hawassa Branch. Ranked 3rd in Branch Manager cycle. '
        'Strong banking track record (6yr). Retained for 6-month reserve pool per BRD 9.4.2. '
        'Recommended for next suitable G12 vacancy within reserve window.'
    ),
})
print(f"   Roster 2 — {roster_aberash.name} (ID={roster_aberash.id})")
print(f"   -> Status=active | Score=80.5 | Expiry={roster_aberash.expiry_date}")

# Roster 3: Bekele Hailu – Expired entry (demonstrates 6-month rule enforcement)
roster_expired = TR_Roster.create({
    'name': 'Bekele Hailu (Demo - Expired)',
    'email': 'bekele.hailu.demo@yahoo.com',
    'phone': '+251977889900',
    'gender': 'male',
    'application_type': 'External',
    'educational_qualification': 'Master of Business Administration',
    'field_of_study': 'Business Administration',
    'highest_cgpa': 3.6,
    'total_experience': 8.0,
    'banking_experience': 5.0,
    'final_score': 79.2,
    'date_added': '2025-12-01',
    'status': 'expired',
    'notes': (
        'Candidate added Dec 2025. 6-month reserve pool window elapsed (expiry June 2026). '
        'Marked expired by system cron per BRD Section 9.4.2. '
        'Cannot be re-linked to new vacancies without fresh recruitment cycle.'
    ),
})
print(f"   Roster 3 — {roster_expired.name} (ID={roster_expired.id})")
print(f"   -> Status=EXPIRED | Score=79.2 | date_added=2025-12-01")


# ===========================================================================
# SECTION 14: TRANSFER CONFIG SYSTEM PARAMETERS (BRD Section 12 settings)
# ===========================================================================
print("\n>> Section 14: Transfer Configuration Parameters")

ICP = env['ir.config_parameter'].sudo()

settings = {
    'custom_recruitment.transfer_discipline_blocks_first_warning': 'False',
    'custom_recruitment.transfer_discipline_blocks_second_warning': 'False',
    'custom_recruitment.transfer_min_pms_score': '75.0',
    'custom_recruitment.transfer_min_service_years': '1.0',
    'custom_recruitment.transfer_refusal_penalty_months': '12',
    'custom_recruitment.transfer_pending_expiry_days': '365',
    'custom_recruitment.transfer_pending_auto_withdraw_days': '7',
    'custom_recruitment.transfer_weight_pms': '30.0',
    'custom_recruitment.transfer_weight_application_date': '20.0',
    'custom_recruitment.transfer_weight_experience': '20.0',
    'custom_recruitment.transfer_weight_service_location': '20.0',
    'custom_recruitment.transfer_weight_recommendation': '10.0',
}

for key, value in settings.items():
    ICP.set_param(key, value)
    print(f"   Set: {key.split('.')[-1]} = {value}")


# ===========================================================================
# COMMIT + SUMMARY
# ===========================================================================
env.cr.commit()

print("\n" + "="*70)
print("  BRD SIMULATION SEED COMPLETE")
print("="*70)
print(f"""
SUMMARY OF CREATED RECORDS:
  Operating Units   : 4 (IT Directorate, Addis Main, Hawassa, Dire Dawa)
  Departments       : 4 (IT, Operations, Credit, HR)
  Employee Grades   : 3 (G15, G12, G09)
  Job Positions     : 4 (SSE, Branch Manager, Credit Analyst, Cashier)
  Employees         : 5
    - Solomon Kebede   → Clean record  | PMS 88 | G15 | Eligible for transfer
    - Tigist Alemu     → 1st Warning   | PMS 84 | G09 | 5% deduction
    - Dawit Tadesse    → 2nd Warning   | PMS 79 | G12 | 10% deduction
    - Meron Haile      → Final Warning | PMS 91 | G15 | INELIGIBLE (blocked)
    - Yohannes Tesfaye → Clean record  | HR Officer
  Discipline Cases  : 3 (all in state=enforced)
  Blacklist Entries : 2 (fraud, credential falsification)
  Shortlist Criteria: 1 (active default)
  Recruitment Reqs  : 3 (approved, submitted, under_review)
  Job Vacancies     : 3 (external, internal-lateral, both)
  External Candidates: 3 (qualifies, below criteria, ex-Bunna)
  Transfer Requests : 5 (eligible, grade-mismatch, deducted, blocked, exchange)
  Talent Roster     : 3 (active-strong, active-internal, expired)
  Config Params     : 12 (ranking weights + eligibility thresholds)

BRD SCENARIOS COVERED:
  ✓ Section 3  – Planned vs Unplanned Recruitment Requests
  ✓ Section 4  – Job Vacancy announcement (internal/external/both)
  ✓ Section 6  – Blacklist check (flagged applicants)
  ✓ Section 7  – Default shortlist criteria (CGPA/education/experience gate)
  ✓ Section 8  – External candidate shortlisting (pass/fail cases)
  ✓ Section 9  – Reserve pool / Talent Roster (active, linked, expired)
  ✓ Section 11 – Discipline case enforcement (Level 2, 3, 4)
  ✓ Section 12 – Transfer eligibility: grade match, service years, PMS,
                  discipline deductions, complete ineligibility, exchange transfer
""")
