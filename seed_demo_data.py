# -*- coding: utf-8 -*-
"""
Omni-Bank ERP - Demo / Dummy Data Seed Script
==============================================
Run this inside the Odoo container against the `Learn` database:

    docker exec -i odoo19-app odoo shell -d Learn --no-http < seed_demo_data.py

Uses the ORM (not raw SQL) so sequences, computed fields, translated names
and Python/SQL constraints work exactly like in the UI. Safe to re-run: every
section checks for existing records before creating new ones. All records are
prefixed with "DEMO" so they are easy to spot and clean up.
"""

import logging
from datetime import date, datetime, timedelta

_logger = logging.getLogger('seed_demo_data')

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)


def _find(model, domain):
    return env[model].search(domain, limit=1)


def _section(title):
    print('\n== %s ==' % title)


def _mk_partner(name):
    existing = _find('res.partner', [('name', '=', name)])
    if existing:
        return existing
    return env['res.partner'].create({'name': name})


def _mk_report_code(code, name):
    existing = _find('hr.report.code', [('code', '=', str(code))])
    if existing:
        return existing
    return env['hr.report.code'].create({'code': str(code), 'name': name})


def _mk_employee_category(name):
    existing = _find('employee.category', [('category_name', '=', name)])
    if existing:
        return existing
    return env['employee.category'].create({'category_name': name})


def _mk_payroll_structure(code, name):
    existing = _find('hr.payroll.structure', [('code', '=', code)])
    if existing:
        return existing
    return env['hr.payroll.structure'].create({
        'name': name, 'code': code, 'company_id': env.company.id})


def _mk_department(name, manager=None):
    existing = _find('hr.department', [('name', '=', name)])
    if existing:
        return existing
    vals = {'name': name}
    if manager:
        vals['manager_id'] = manager.id
    return env['hr.department'].create(vals)


def _mk_operating_unit(name, sol_id, work_unit_type, department, parent=None,
                       code=None, hardship=0.0, district='Addis Ababa',
                       region='Addis Ababa'):
    existing = _find('operating.unit', [('name', '=', name)])
    if existing:
        return existing
    vals = {
        'name': name,
        'sol_id': sol_id,
        'work_unit_type': work_unit_type,
        'department': department.id,
        'district': district,
        'region': region,
        'hardship_allowance': hardship,
    }
    if parent:
        vals['parent_unit'] = parent.id
    if code:
        vals['code'] = code.id
    return env['operating.unit'].create(vals)


def _mk_job(name, department, grade=None, category='Non Managerial',
            employment='Permanent', probation=6, state='open'):
    existing = _find('hr.job', [('name', '=', name)])
    if existing:
        return existing
    vals = {
        'name': name,
        'department_id': department.id,
        'employee_category': category,
        'type_of_employment': employment,
        'probation_period': probation,
        'state': state,
    }
    if grade:
        vals['grade'] = grade.id
    return env['hr.job'].create(vals)


def _mk_user(login, name, groups, operating_units):
    group_ids = []
    for xmlid in groups:
        grp = env.ref(xmlid, raise_if_not_found=False)
        if grp:
            group_ids.append(grp.id)
    existing = _find('res.users', [('login', '=', login)])
    if existing:
        # Idempotent on re-runs: add any newly requested groups
        # (this project's res.users uses group_ids, not groups_id)
        missing = [g for g in group_ids if g not in existing.group_ids.ids]
        if missing:
            existing.write({'group_ids': [(4, g) for g in missing]})
        return existing
    return env['res.users'].create({
        'name': name,
        'login': login,
        'password': 'demo1234',
        'group_ids': [(6, 0, group_ids)],
        'assigned_operating_unit_ids': [(6, 0, operating_units.ids)],
    })


def _mk_employee(name, identification, department, job, grade, operating_unit,
                 parent=None, coach=None, user=None, calendar=None,
                 active=True, email=None):
    existing = _find('hr.employee', [('name', '=', name)])
    if existing:
        return existing
    vals = {
        'name': name,
        'employee_identification': identification,
        'identification_id': identification,
        'department_id': department.id,
        'job_position': job.id,
        'job_grade': grade.id,
        'default_operating_unit_id': operating_unit.id if operating_unit else False,
        'active': active,
        'company_id': env.company.id,
    }
    if parent:
        vals['parent_id'] = parent.id
    if coach:
        vals['coach_id'] = coach.id
    if user:
        vals['user_id'] = user.id
    if calendar:
        vals['resource_calendar_id'] = calendar.id
    if email:
        vals['work_email'] = email
    return env['hr.employee'].create(vals)


def _mk_contract(employee, date_start, wage, contract_type=None,
                 state='draft', date_end=False, job_category=None,
                 job_grade=None, operating_unit=None, department=None, job=None,
                 calendar=None, employee_tin=None, salary_account=None,
                 allowances=None):
    existing = _find('hr.contract', [('employee_id', '=', employee.id),
                                     ('state', '=', state)])
    if existing:
        return existing
    vals = {
        'employee_id': employee.id,
        'date_start': date_start,
        'wage': wage,
        'state': state,
    }
    if job_category:
        vals['job_category'] = job_category.id if hasattr(job_category, 'id') else job_category
    if job_grade is None:
        job_grade = employee.job_grade
    if job_grade:
        vals['job_grade'] = job_grade.id if hasattr(job_grade, 'id') else job_grade
    if contract_type:
        vals['type_id'] = contract_type.id
        vals['employee_category'] = contract_type.id
    if date_end:
        vals['date_end'] = date_end
    if operating_unit:
        vals['operating_unit_id'] = operating_unit.id
    if department:
        vals['department_id'] = department.id
    if job:
        vals['job_id'] = job.id
    if calendar:
        vals['resource_calendar_id'] = calendar.id
    if employee_tin:
        vals['employee_tin'] = employee_tin
    if salary_account:
        vals['salary_account'] = salary_account
    if allowances:
        for key, value in allowances.items():
            if key in env['hr.contract']._fields:
                vals[key] = value
    return env['hr.contract'].create(vals)


def _utc(d, h, m=0):
    return datetime(d.year, d.month, d.day, h, m)


def _mk_attendance(employee, check_in, check_out=False, in_status='Normal',
                   out_status='Normal', late=0.0, early=0.0, pre_late=0.0,
                   pre_early=0.0, lunch_out=False, lunch_in=False,
                   force=False, reason_ids=None, regularization=False):
    existing = _find('hr.attendance', [('employee_id', '=', employee.id),
                                       ('check_in', '=', check_in)])
    if existing:
        return existing
    vals = {
        'employee_id': employee.id,
        'date': check_in.date(),
        'check_in': check_in,
        'check_in_status': in_status,
        'late_time_hour': late,
        'pre_defined_lateness': pre_late,
        'regularization': regularization,
    }
    if check_out:
        vals['check_out'] = check_out
        vals['check_out_status'] = out_status
        vals['early_exit_hour'] = early
        vals['pre_approved_early_checkout'] = pre_early
    if lunch_out:
        vals['lunch_out'] = lunch_out
    if lunch_in:
        vals['lunch_in'] = lunch_in
    if force:
        vals['is_force_checkout'] = True
    if reason_ids:
        vals['attendance_reason_ids'] = [(6, 0, reason_ids.ids)]
    return env['hr.attendance'].create(vals)

# ---------------------------------------------------------------------------
# SECTION 1 - Config: Codes, Categories, Grades, Departments, Jobs, OUs
# ---------------------------------------------------------------------------
_section('SECTION 1: Config')

rc_hq = _mk_report_code(1, 'Head Office')
rc_branch = _mk_report_code(2, 'Branch')
rc_sub = _mk_report_code(3, 'Sub-Branch')
rc_district = _mk_report_code(4, 'District')
rc_region = _mk_report_code(5, 'Region')

cat_mgr = _mk_employee_category('Managerial')
cat_non = _mk_employee_category('Non Managerial')

ps_mgr = _mk_payroll_structure('MGR_DEMO', 'DEMO Managerial Structure')
ps_non = _mk_payroll_structure('NMGR_DEMO', 'DEMO Non-Managerial Structure')

grade_specs = [
    ('I', 'DEMO Grade I', cat_non, 5000, 1.15, ps_non),
    ('II', 'DEMO Grade II', cat_non, 6000, 1.15, ps_non),
    ('III', 'DEMO Grade III', cat_non, 8000, 1.15, ps_non),
    ('IV', 'DEMO Grade IV', cat_non, 10000, 1.15, ps_non),
    ('V', 'DEMO Grade V', cat_mgr, 15000, 1.18, ps_mgr),
    ('VI', 'DEMO Grade VI', cat_mgr, 25000, 1.18, ps_mgr),
    ('VII', 'DEMO Grade VII', cat_mgr, 40000, 1.20, ps_mgr),
]
grades = {}
for code, name, cat, base, factor, struct in grade_specs:
    existing = _find('employee.grade', [('grade_code', '=', code)])
    if existing:
        grades[code] = existing
        continue
    grades[code] = env['employee.grade'].create({
        'grade_code': code,
        'grade_name': name,
        'category': cat.id,
        'base_salary': base,
        'salary_factor': factor,
        'salary_structure': struct.id,
    })
print('  grades ready:', sorted(grades.keys()))

hr_dept = _mk_department('DEMO Human Resources')
fin_dept = _mk_department('DEMO Finance')
it_dept = _mk_department('DEMO Information Technology')
ops_dept = _mk_department('DEMO Operations')
credit_dept = _mk_department('DEMO Credit')
cs_dept = _mk_department('DEMO Customer Service')
legal_dept = _mk_department('DEMO Legal')
risk_dept = _mk_department('DEMO Risk Management')
audit_dept = _mk_department('DEMO Internal Audit')

# employee.job records (hr.contract.job_category is Many2one -> employee.job)
ej_mgr = _find('employee.job', [('job_name', '=', 'DEMO Managerial Job')])
if not ej_mgr:
    ej_mgr = env['employee.job'].create({
        'job_code': 'DMG', 'job_name': 'DEMO Managerial Job',
        'job_category': 'Managerial'})
ej_nm = _find('employee.job', [('job_name', '=', 'DEMO Non Managerial Job')])
if not ej_nm:
    ej_nm = env['employee.job'].create({
        'job_code': 'DNM', 'job_name': 'DEMO Non Managerial Job',
        'job_category': 'Non Managerial'})

job_ceo = _mk_job('DEMO CEO / President', ops_dept, grades['VII'], 'Managerial')
job_vp = _mk_job('DEMO Vice President', ops_dept, grades['VI'], 'Managerial')
job_hr_mgr = _mk_job('DEMO HR Manager', hr_dept, grades['VI'], 'Managerial')
job_hr_off = _mk_job('DEMO HR Officer', hr_dept, grades['IV'], 'Non Managerial')
job_fin_mgr = _mk_job('DEMO Finance Manager', fin_dept, grades['VI'], 'Managerial')
job_fin_off = _mk_job('DEMO Finance Officer', fin_dept, grades['III'], 'Non Managerial')
job_it_off = _mk_job('DEMO IT Officer', it_dept, grades['IV'], 'Non Managerial')
job_bm = _mk_job('DEMO Branch Manager', ops_dept, grades['V'], 'Managerial')
job_loan = _mk_job('DEMO Loan Officer', credit_dept, grades['IV'], 'Non Managerial')
job_cs = _mk_job('DEMO Customer Service Officer', cs_dept, grades['III'], 'Non Managerial')
job_teller = _mk_job('DEMO Teller', cs_dept, grades['II'], 'Non Managerial')
job_security = _mk_job('DEMO Security Guard', ops_dept, grades['I'], 'Non Managerial')
job_driver = _mk_job('DEMO Driver', ops_dept, grades['I'], 'Non Managerial')
job_recep = _mk_job('DEMO Receptionist', cs_dept, grades['I'], 'Non Managerial')

# Operating Units (district/region/department are required)
ou_hq = _mk_operating_unit('DEMO Head Office', 10, 'head_office', hr_dept,
                           code=rc_hq, hardship=1500.0)
ou_bole = _mk_operating_unit('DEMO Bole Branch', 11, 'branch', ops_dept,
                             parent=ou_hq, code=rc_branch, hardship=800.0)
ou_merkato = _mk_operating_unit('DEMO Merkato Branch', 12, 'branch', ops_dept,
                                parent=ou_hq, code=rc_branch, hardship=1000.0)
ou_piassa = _mk_operating_unit('DEMO Piassa Sub-Branch', 13, 'sub_branch', cs_dept,
                               parent=ou_merkato, code=rc_sub, hardship=600.0)
ou_district = _mk_operating_unit('DEMO Addis Ababa District', 14, 'district_office',
                                 ops_dept, parent=ou_hq, code=rc_district,
                                 hardship=500.0)
ou_region = _mk_operating_unit('DEMO Adama Regional Office', 15, 'regional_office',
                               ops_dept, parent=ou_hq, code=rc_region, hardship=1200.0)
ou_service = _mk_operating_unit('DEMO Service Center', 16, 'service_center',
                                cs_dept, parent=ou_bole, code=rc_sub, hardship=300.0)

for dept, ou in [(hr_dept, ou_hq), (fin_dept, ou_hq), (it_dept, ou_hq),
                 (ops_dept, ou_hq), (credit_dept, ou_bole), (cs_dept, ou_merkato),
                 (legal_dept, ou_hq), (risk_dept, ou_hq), (audit_dept, ou_hq)]:
    if dept and not dept.operating_unit_id:
        dept.operating_unit_id = ou.id

all_units = env['operating.unit'].search([('name', 'like', 'DEMO%')])
print('  operating.units created:', len(all_units))

# ---------------------------------------------------------------------------
# SECTION 2 - Users & Employees
# ---------------------------------------------------------------------------
_section('SECTION 2: Users & Employees')

cal_std = env.ref('resource.resource_calendar_std', raise_if_not_found=False) or \
    env['resource.calendar'].search([], limit=1)

ct_perm = env['hr.contract.type'].search([('name', '=', 'Permanent')], limit=1) or \
    env['hr.contract.type'].search([], limit=1)
ct_temp = env['hr.contract.type'].search([('name', '=', 'Temporary')], limit=1) or ct_perm

base_groups = ['base.group_user']
hr_user_groups = base_groups + ['hr.group_hr_user']
hr_mgr_groups = hr_user_groups + ['hr.group_hr_manager']
att_groups = ['hr_attendance.group_hr_attendance_user']
# Discipline Management groups (module security requires one of these to read discipline.case)
disc_admin = ['discipline_management.group_discipline_admin']
disc_officer = ['discipline_management.group_discipline_officer']
disc_user = ['discipline_management.group_discipline_user']

u_ceo = _mk_user('demo.ceo@omni.bank', 'DEMO CEO User',
                  hr_mgr_groups + disc_admin, all_units)
u_hr_mgr = _mk_user('demo.hr@omni.bank', 'DEMO HR Manager User',
                    hr_mgr_groups + att_groups + disc_admin, all_units)
u_bm1 = _mk_user('demo.bm1@omni.bank', 'DEMO Branch Manager 1 User',
                  hr_user_groups + att_groups + disc_officer, all_units)
u_bm2 = _mk_user('demo.bm2@omni.bank', 'DEMO Branch Manager 2 User',
                  hr_user_groups + disc_officer, all_units)
u_officer = _mk_user('demo.off@omni.bank', 'DEMO IT Officer User',
                     hr_user_groups + disc_officer, all_units)
u_emp = _mk_user('demo.emp@omni.bank', 'DEMO Regular Employee User',
                 base_groups + disc_user, all_units)

emp_ceo = _mk_employee('DEMO Abel Bekele', '90001', ops_dept, job_ceo, grades['VII'],
                       ou_hq, user=u_ceo, calendar=cal_std,
                       email='abel.bekele@omni.bank')
emp_vp = _mk_employee('DEMO Sara Hailu', '90002', ops_dept, job_vp, grades['VI'],
                      ou_hq, parent=emp_ceo, coach=emp_ceo, calendar=cal_std,
                      email='sara.hailu@omni.bank')
emp_hr_mgr = _mk_employee('DEMO Meron Tadesse', '90003', hr_dept, job_hr_mgr,
                          grades['VI'], ou_hq, parent=emp_vp, coach=emp_vp,
                          user=u_hr_mgr, calendar=cal_std,
                          email='meron.tadesse@omni.bank')
emp_hr_off = _mk_employee('DEMO Dawit Girma', '90004', hr_dept, job_hr_off,
                          grades['IV'], ou_hq, parent=emp_hr_mgr,
                          coach=emp_hr_mgr, calendar=cal_std,
                          email='dawit.girma@omni.bank')
emp_fin_mgr = _mk_employee('DEMO Hana Tesfaye', '90005', fin_dept, job_fin_mgr,
                           grades['VI'], ou_hq, parent=emp_vp, coach=emp_vp,
                           calendar=cal_std, email='hana.tesfaye@omni.bank')
emp_fin_off = _mk_employee('DEMO Yonatan Alemu', '90006', fin_dept, job_fin_off,
                           grades['III'], ou_bole, parent=emp_fin_mgr,
                           coach=emp_fin_mgr, calendar=cal_std,
                           email='yonatan.alemu@omni.bank')
emp_it_off = _mk_employee('DEMO Samuel Kebede', '90007', it_dept, job_it_off,
                          grades['IV'], ou_hq, parent=emp_vp, coach=emp_vp,
                          user=u_officer, calendar=cal_std,
                          email='samuel.kebede@omni.bank')
emp_bm1 = _mk_employee('DEMO Selam Wondimu', '90008', ops_dept, job_bm,
                       grades['V'], ou_bole, parent=emp_vp, coach=emp_vp,
                       user=u_bm1, calendar=cal_std,
                       email='selam.wondimu@omni.bank')
emp_bm2 = _mk_employee('DEMO Ermias Fikre', '90009', ops_dept, job_bm,
                       grades['V'], ou_merkato, parent=emp_vp, coach=emp_vp,
                       user=u_bm2, calendar=cal_std,
                       email='ermias.fikre@omni.bank')
emp_loan = _mk_employee('DEMO Mahlet Desta', '90010', credit_dept, job_loan,
                        grades['IV'], ou_bole, parent=emp_bm1, coach=emp_bm1,
                        calendar=cal_std, email='mahlet.desta@omni.bank')
emp_cs = _mk_employee('DEMO Beza Getachew', '90011', cs_dept, job_cs,
                      grades['III'], ou_merkato, parent=emp_bm2, coach=emp_bm2,
                      calendar=cal_std, email='beza.getachew@omni.bank')
emp_teller = _mk_employee('DEMO Nahom Assefa', '90012', cs_dept, job_teller,
                          grades['II'], ou_bole, parent=emp_bm1, coach=emp_bm1,
                          calendar=cal_std, email='nahom.assefa@omni.bank')
emp_security = _mk_employee('DEMO Tigist Bekele', '90013', ops_dept, job_security,
                            grades['I'], ou_piassa, parent=emp_bm2, coach=emp_bm2,
                            calendar=cal_std, email='tigist.bekele@omni.bank')
emp_driver = _mk_employee('DEMO Kalkidan Molla', '90014', ops_dept, job_driver,
                          grades['I'], ou_hq, parent=emp_vp, coach=emp_vp,
                          calendar=cal_std, email='kalkidan.molla@omni.bank')
emp_recep = _mk_employee('DEMO Biruk Teshome', '90015', cs_dept, job_recep,
                         grades['I'], ou_service, parent=emp_bm1, coach=emp_bm1,
                         user=u_emp, calendar=cal_std,
                         email='biruk.teshome@omni.bank')
emp_archived = _mk_employee('DEMO Fikadu Haile', '90017', ops_dept, job_security,
                            grades['I'], ou_bole, parent=emp_bm1, coach=emp_bm1,
                            active=False, calendar=cal_std,
                            email='fikadu.haile@omni.bank')

all_employees = env['hr.employee'].search([('name', 'like', 'DEMO%')])
print('  demo employees:', len(all_employees))

# ---------------------------------------------------------------------------
# SECTION 3 - Contracts (all states)
# ---------------------------------------------------------------------------
_section('SECTION 3: Contracts')

_mk_contract(emp_ceo, date(2010, 3, 1), 40000, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_hq,
             department=ops_dept, job=job_ceo, calendar=cal_std,
             employee_tin='TIN-90001', salary_account='SA-90001',
             allowances={'housing_allowance': 8000, 'mobile_allowance': 1000,
                         'fuel_allowance': 2500, 'representation_allowance': 5000})
_mk_contract(emp_vp, date(2012, 7, 1), 30000, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_hq,
             department=ops_dept, job=job_vp, calendar=cal_std,
             employee_tin='TIN-90002', salary_account='SA-90002',
             allowances={'housing_allowance': 6000, 'mobile_allowance': 800})
_mk_contract(emp_hr_mgr, date(2013, 1, 15), 25000, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_hq,
             department=hr_dept, job=job_hr_mgr, calendar=cal_std,
             employee_tin='TIN-90003', salary_account='SA-90003',
             allowances={'housing_allowance': 5000, 'mobile_allowance': 700})
_mk_contract(emp_hr_off, date(2016, 9, 1), 12000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_hq,
             department=hr_dept, job=job_hr_off, calendar=cal_std,
             employee_tin='TIN-90004', salary_account='SA-90004',
             allowances={'transportation_allowance': 1200, 'mobile_allowance': 500})
_mk_contract(emp_fin_mgr, date(2011, 6, 1), 26000, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_hq,
             department=fin_dept, job=job_fin_mgr, calendar=cal_std,
             employee_tin='TIN-90005', salary_account='SA-90005',
             allowances={'housing_allowance': 5200})
_mk_contract(emp_fin_off, date(2019, 4, 1), 9000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_bole,
             department=fin_dept, job=job_fin_off, calendar=cal_std,
             employee_tin='TIN-90006', salary_account='SA-90006',
             allowances={'transportation_allowance': 1000})
_mk_contract(emp_it_off, date(2018, 2, 1), 13000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_hq,
             department=it_dept, job=job_it_off, calendar=cal_std,
             employee_tin='TIN-90007', salary_account='SA-90007',
             allowances={'transportation_allowance': 1200, 'mobile_allowance': 600})
_mk_contract(emp_bm1, date(2014, 10, 1), 18000, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_bole,
             department=ops_dept, job=job_bm, calendar=cal_std,
             employee_tin='TIN-90008', salary_account='SA-90008',
             allowances={'hardship_allowance': 800, 'mobile_allowance': 700})
_mk_contract(emp_bm2, date(2015, 11, 1), 18500, ct_perm, 'open',
             job_category=ej_mgr, operating_unit=ou_merkato,
             department=ops_dept, job=job_bm, calendar=cal_std,
             employee_tin='TIN-90009', salary_account='SA-90009',
             allowances={'hardship_allowance': 1000, 'mobile_allowance': 700})
_mk_contract(emp_loan, date(2017, 5, 1), 11000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_bole,
             department=credit_dept, job=job_loan, calendar=cal_std,
             employee_tin='TIN-90010', salary_account='SA-90010',
             allowances={'transportation_allowance': 1100, 'mobile_allowance': 500})
_mk_contract(emp_cs, date(2020, 3, 1), 8500, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_merkato,
             department=cs_dept, job=job_cs, calendar=cal_std,
             employee_tin='TIN-90011', salary_account='SA-90011',
             allowances={'transportation_allowance': 900})
_mk_contract(emp_teller, date(2021, 8, 1), 7000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_bole,
             department=cs_dept, job=job_teller, calendar=cal_std,
             employee_tin='TIN-90012', salary_account='SA-90012',
             allowances={'transportation_allowance': 800})
_mk_contract(emp_security, date(2016, 1, 1), 6000, ct_perm, 'open',
             job_category=ej_nm, operating_unit=ou_piassa,
             department=ops_dept, job=job_security, calendar=cal_std,
             employee_tin='TIN-90013', salary_account='SA-90013',
             allowances={'transportation_allowance': 600})
_mk_contract(emp_driver, date(2018, 6, 1), 6500, ct_temp, 'open',
             job_category=ej_nm, operating_unit=ou_hq,
             department=ops_dept, job=job_driver, calendar=cal_std,
             employee_tin='TIN-90014', salary_account='SA-90014',
             allowances={'transportation_allowance': 500})
_mk_contract(emp_recep, date(2022, 2, 1), 5500, ct_temp, 'open',
             job_category=ej_nm, operating_unit=ou_service,
             department=cs_dept, job=job_recep, calendar=cal_std,
             employee_tin='TIN-90015', salary_account='SA-90015',
             allowances={'transportation_allowance': 500})
_mk_contract(emp_archived, date(2015, 1, 1), 6000, ct_temp, 'close',
             date_end=TODAY - timedelta(days=30),
             job_category=ej_nm, operating_unit=ou_bole,
             department=ops_dept, job=job_security, calendar=cal_std,
             employee_tin='TIN-90017', salary_account='SA-90017')

print('  contracts:', env['hr.contract'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 4 - Attendance (all statuses)
# ---------------------------------------------------------------------------
_section('SECTION 4: Attendance')

reasons = env['hr.attendance.reason'].search([], limit=5)
YESTERDAY = TODAY - timedelta(days=1)

# The custom hr.attendance.create() blocks creating two records for the same
# employee within 30s (based on create_date). Seeding dozens of rows in a loop
# would trip it, so temporarily disable the duplicate window, then restore it.
_dup_param = env['ir.config_parameter'].sudo()
_dup_old = _dup_param.get_param('hr_attendance.duplicate_checkin_window_seconds', '30')
_dup_param.set_param('hr_attendance.duplicate_checkin_window_seconds', '0')

# Past working days - normal / late / early-exit records
for day_offset in range(2, 6):
    d = TODAY - timedelta(days=day_offset)
    if d.weekday() >= 5:
        continue
    for emp in [emp_hr_off, emp_fin_off, emp_it_off, emp_loan, emp_cs,
                emp_teller, emp_security, emp_driver, emp_recep]:
        if day_offset % 3 == 0:
            _mk_attendance(emp, _utc(d, 6, 0), _utc(d, 14, 0))
        elif day_offset % 3 == 1:
            _mk_attendance(emp, _utc(d, 6, 45), _utc(d, 14, 0),
                           in_status='Late', late=45.0)
        else:
            _mk_attendance(emp, _utc(d, 6, 0), _utc(d, 12, 30),
                           out_status='Unauthorized Early Exit', early=90.0)

y = YESTERDAY
_mk_attendance(emp_hr_mgr, _utc(y, 5, 55), _utc(y, 14, 5))
_mk_attendance(emp_bm1, _utc(y, 5, 50), _utc(y, 14, 0))
_mk_attendance(emp_bm2, _utc(y, 7, 0), _utc(y, 14, 0),
               in_status='Late', late=120.0)
_mk_attendance(emp_fin_mgr, _utc(y, 6, 0), _utc(y, 13, 0),
               out_status='Unauthorized Early Exit', early=60.0)
_mk_attendance(emp_ceo, _utc(y, 6, 0), _utc(y, 14, 0),
               lunch_out=_utc(y, 9, 0), lunch_in=_utc(y, 10, 0))
_mk_attendance(emp_recep, _utc(y, 7, 30), _utc(y, 14, 0),
               in_status='Pre-Defined Lateness', pre_late=90.0)
_mk_attendance(emp_teller, _utc(y, 6, 0), _utc(y, 12, 0),
               out_status='Pre-Defined Early Exit', pre_early=120.0)
_mk_attendance(emp_loan, _utc(y, 6, 30), _utc(y, 14, 0),
               in_status='Acknowledged Lateness', late=30.0,
               reason_ids=reasons[:2])
_mk_attendance(emp_security, _utc(y, 6, 0), _utc(y, 20, 0),
               out_status='Force Checkout', force=True)
_mk_attendance(emp_driver, _utc(y, 6, 0), _utc(y, 14, 0), regularization=True)

t = TODAY
_mk_attendance(emp_hr_mgr, _utc(t, 5, 58), _utc(t, 14, 2))
_mk_attendance(emp_bm1, _utc(t, 6, 5), _utc(t, 14, 0))
_mk_attendance(emp_it_off, _utc(t, 5, 50))
_mk_attendance(emp_cs, _utc(t, 6, 40), _utc(t, 14, 0), in_status='Late', late=40.0)

_dup_param.set_param('hr_attendance.duplicate_checkin_window_seconds', _dup_old)
print('  attendance records:', env['hr.attendance'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 5 - Overtime (8h unused cap per employee)
# ---------------------------------------------------------------------------
_section('SECTION 5: Overtime')

# Small overtime blocks (2-3h each) so total unused stays under the 8h cap.
ot_specs = [
    (emp_it_off, TOMORROW, 18.0, 21.0, 'Deploying the new server'),  # 3h so a 2h consumption leaves it partially_used
    (emp_fin_off, TOMORROW, 17.0, 19.0, 'Monthly reconciliation'),
    (emp_loan, TOMORROW, 18.0, 20.0, 'Processing loan batch'),
    (emp_hr_off, TOMORROW, 17.5, 19.0, 'Payroll data cleanup'),
    (emp_cs, TOMORROW + timedelta(days=1), 18.0, 20.0, 'Customer migration'),
    (emp_teller, TOMORROW + timedelta(days=1), 18.0, 19.5, 'Cash count audit'),
    (emp_security, TOMORROW + timedelta(days=2), 20.0, 22.0, 'Night security coverage'),
    (emp_hr_mgr, TOMORROW, 17.0, 20.0, 'HR policy review'),
    (emp_recep, TOMORROW + timedelta(days=3), 8.0, 16.0, 'Weekend server maintenance'),  # 8h - happy-path demo employee (demo.emp login)
]
for emp, d, s, e, reason in ot_specs:
    existing = _find('over.time', [('employee_id', '=', emp.id),
                                   ('date', '=', d)])
    if existing:
        continue
    try:
        env['over.time'].create({
            'employee_id': emp.id,
            'date': d,
            'start_time': s,
            'end_time': e,
            'compensation_type': 'compensatory_day',
            'over_time_reason': reason,
        })
    except Exception as exc:
        print('  OT skipped for %s on %s: %s' % (emp.name, d, exc))
print('  overtime records:', env['over.time'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 6 - Pre-Approvals + Job/Location Exceptions
# ---------------------------------------------------------------------------
_section('SECTION 6: Pre-Approvals & Exceptions')

pa_specs = [
    (emp_recep, 'predefined_late', TOMORROW, 7.5, 8.5,
     'Doctor appointment in the morning', 'approved', u_hr_mgr),
    (emp_teller, 'predefined_early_exit', TOMORROW, 12.0, 13.0,
     'School pickup', 'requested', False),
    (emp_cs, 'predefined_late', TOMORROW + timedelta(days=1), 8.0, 9.0,
     'Traffic delay', 'draft', False),
    (emp_driver, 'predefined_early_exit', TOMORROW + timedelta(days=1),
     11.0, 12.0, 'Vehicle maintenance', 'rejected', False),
]
for emp, etype, d, s, e, reason, state, approver in pa_specs:
    existing = _find('attendance.preapproval', [
        ('employee_id', '=', emp.id), ('date', '=', d),
        ('exception_type', '=', etype)])
    if existing:
        continue
    vals = {
        'employee_id': emp.id,
        'exception_type': etype,
        'approval_reason': reason,
        'date': d,
        'start_time': s,
        'end_time': e,
        'state': state,
    }
    if approver:
        vals['approved_by'] = approver.id
    env['attendance.preapproval'].create(vals)
print('  preapprovals:', env['attendance.preapproval'].search_count([]))

# Job position exceptions
shift_night = env['job.shift'].search([('name', '=', 'Night Shift')], limit=1)
shift_morning = env['job.shift'].search([('name', '=', 'Morning Shift 1')], limit=1)
if not _find('job.position.exception', [('employee_id', '=', emp_security.id)]):
    if shift_night:
        env['job.position.exception'].create({
            'employee_id': emp_security.id,
            'shift_id': shift_night.id,
        })
if not _find('job.position.exception', [('employee_id', '=', emp_driver.id)]):
    if shift_morning:
        env['job.position.exception'].create({
            'employee_id': emp_driver.id,
            'shift_id': shift_morning.id,
        })

# Location based exception
if not _find('location.based.exception', [
        ('operating_unit', '=', ou_piassa.id), ('start_time', '=', 8.0)]):
    env['location.based.exception'].create({
        'operating_unit': ou_piassa.id,
        'start_time': 8.0,
        'end_time': 11.5,
    })
print('  job.position.exceptions:', env['job.position.exception'].search_count([]))
print('  location.exceptions:', env['location.based.exception'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 7 - Leave Requests + OT Consumption (OT -> leave flow)
# ---------------------------------------------------------------------------
_section('SECTION 7: Leave Requests & OT Consumption')

# Employee-side leave requests (custom leave.request model)
lr_specs = [
    (emp_it_off, 'annual_leave', TODAY + timedelta(days=10),
     TODAY + timedelta(days=13), 'Annual leave request'),
    (emp_fin_off, 'sick_leave', TODAY + timedelta(days=5),
     TODAY + timedelta(days=6), 'Sick leave'),
    (emp_loan, 'wedding_leave', TODAY + timedelta(days=20),
     TODAY + timedelta(days=22), 'Wedding leave'),
    (emp_recep, 'annual_leave', TODAY + timedelta(days=15),
     TODAY + timedelta(days=16), 'Annual leave'),
]
leave_requests = []
for emp, reason, sdate, edate, comment in lr_specs:
    existing = _find('leave.request', [('requester_name', '=', emp.id),
                                       ('start_date', '=', sdate)])
    if existing:
        leave_requests.append(existing)
        continue
    lr = env['leave.request'].create({
        'requester_name': emp.id,
        'leave_reason': reason,
        'start_date': sdate,
        'end_date': edate,
        'comments': 'DEMO %s' % comment,
        'gender': 'male',
        'job_position': emp.job_position.id,
        'job_grade': str(emp.job_grade.id),
        'operating_unit': emp.default_operating_unit_id.id,
        'requester_user_id': emp.user_id.id if emp.user_id else False,
    })
    leave_requests.append(lr)

# Backfill requester_user_id on previously-seeded requests (idempotent re-runs).
for emp in env['hr.employee'].search([('name', 'like', 'DEMO'),
                                      ('user_id', '!=', False)]):
    reqs = env['leave.request'].search([
        ('requester_name', '=', emp.id),
        ('requester_user_id', '=', False)])
    if reqs:
        reqs.write({'requester_user_id': emp.user_id.id})
print('  leave requests:', env['leave.request'].search_count([]))

# OT consumption flow: an overtime request consumed via leave.request.manager
# Find the IT officer's OT record and create a manager-side leave + consumption.
ot_rec = _find('over.time', [('employee_id', '=', emp_it_off.id)])
if ot_rec and ot_rec.remaining_hours >= 2:
    lrm = _find('leave.request.manager', [('reference', '=', 'DEMO-OTLR-0001')])
    if not lrm:
        lrm = env['leave.request.manager'].create({
            'reference': 'DEMO-OTLR-0001',
            'requester_name': emp_it_off.name,
            'leave_reason': 'over_time',
            'start_date': TODAY + timedelta(days=2),
            'end_date': TODAY + timedelta(days=2),
            'over_time': ot_rec.remaining_hours,
            'gender': 'male',
        })
    consumed = _find('over.time.consumption', [
        ('over_time_id', '=', ot_rec.id),
        ('leave_request_id', '=', lrm.id)])
    if not consumed:
        env['over.time.consumption'].create({
            'over_time_id': ot_rec.id,
            'leave_request_id': lrm.id,
            'hours': 2.0,
        })
    ot_rec.invalidate_recordset(['state', 'remaining_hours', 'used_hours'])
    print('  OT %s state=%s remaining=%s' % (ot_rec.over_time, ot_rec.state,
                                             ot_rec.remaining_hours))

print('  leave.request.manager:', env['leave.request.manager'].search_count([]))
print('  over.time.consumption:', env['over.time.consumption'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 8 - Discipline (new discipline_management models)
# ---------------------------------------------------------------------------
_section('SECTION 8: Discipline')

# Offenses are pre-seeded by the module (offense_level_1..5 + 3 categories).
# We only need to create cases referencing them.
off_l3 = env['discipline.offense'].search([('severity_level', '=', 'level_3')], limit=1)
off_l4 = env['discipline.offense'].search([('severity_level', '=', 'level_4')], limit=1)
off_l5 = env['discipline.offense'].search([('severity_level', '=', 'level_5')], limit=1)
off_fallback = env['discipline.offense'].search([], limit=1)
off_l3 = off_l3 or off_fallback
off_l4 = off_l4 or off_fallback
off_l5 = off_l5 or off_fallback

case_specs = [
    (emp_teller, off_l4, TODAY - timedelta(days=10),
     'Repeated lateness without prior approval', 'enforced'),
    (emp_driver, off_l3, TODAY - timedelta(days=15),
     'Minor accident with the company vehicle', 'committee_review'),
    (emp_cs, off_l5, TODAY - timedelta(days=20),
     'Discourteous conduct towards a customer', 'investigating'),
    (emp_security, off_l3, TODAY - timedelta(days=25),
     'Dispute with a co-worker at the gate', 'draft'),
]
case_ids = []
for emp, off, idate, desc, state in case_specs:
    existing = _find('discipline.case', [('employee_id', '=', emp.id),
                                         ('incident_date', '=', idate)])
    if existing:
        case_ids.append(existing)
        continue
    try:
        case = env['discipline.case'].create({
            'employee_id': emp.id,
            'offense_id': off.id,
            'incident_date': idate,
            'description': 'DEMO %s' % desc,
            'state': state,
            'initiator_id': u_hr_mgr.id,
            'reviewer_id': u_bm1.id,
            'approver_id': u_ceo.id,
            'sla_target_days': 7,
        })
        case_ids.append(case)
    except Exception as exc:
        print('  case skipped for %s: %s' % (emp.name, exc))
print('  discipline.case:', env['discipline.case'].search_count([]))

# Investigation for the investigating case
inv_case = _find('discipline.case', [('state', '=', 'investigating')])
if inv_case and not _find('discipline.investigation',
                          [('case_id', '=', inv_case.id)]):
    env['discipline.investigation'].create({
        'case_id': inv_case.id,
        'employee_id': inv_case.employee_id.id,
        'investigator_id': u_hr_mgr.id,
        'investigation_date': TODAY - timedelta(days=12),
        'misconduct_type': 'conduct',
        'examination_date': TODAY - timedelta(days=11),
        'summary_findings': 'DEMO - witness statements collected',
        'applicable_policy': 'DEMO Disciplinary Policy v1',
        'investigator_recommendation': 'DEMO - recommend first written warning',
        'state': 'submitted',
    })

# Committee meeting for the committee_review case
cm_case = _find('discipline.case', [('state', '=', 'committee_review')])
if cm_case and not _find('discipline.committee.meeting',
                         [('case_id', '=', cm_case.id)]):
    env['discipline.committee.meeting'].create({
        'case_id': cm_case.id,
        'employee_id': cm_case.employee_id.id,
        'meeting_date': datetime.combine(TODAY + timedelta(days=2),
                                         datetime.min.time()),
        'committee_chair_id': u_hr_mgr.id,
        'member_ids': [(6, 0, [u_hr_mgr.id, u_bm1.id, u_bm2.id])],
        'present_members_count': 3,
        'required_quorum_percentage': 60.0,
        'state': 'draft',  # displays as 'Scheduled'
    })

# Suspension + payroll penalty for the enforced case
enf_case = _find('discipline.case', [('state', '=', 'enforced')])
if enf_case:
    if not _find('discipline.suspension', [('case_id', '=', enf_case.id)]):
        env['discipline.suspension'].create({
            'case_id': enf_case.id,
            'employee_id': enf_case.employee_id.id,
            'suspension_type': 'without_pay',
            'start_date': TODAY + timedelta(days=1),
            'end_date': TODAY + timedelta(days=3),
            'state': 'active',
            'reason': 'DEMO suspension following the enforced case',
            'working_days_count': 2,
        })
    if not _find('discipline.payroll.penalty', [('case_id', '=', enf_case.id)]):
        env['discipline.payroll.penalty'].create({
            'case_id': enf_case.id,
            'employee_id': enf_case.employee_id.id,
            'penalty_type': 'percentage',
            'penalty_percentage': 5.0,
            'effective_date': TODAY + timedelta(days=5),
            'state': 'pending',
            'notes': 'DEMO - 5% salary deduction from enforced case',
        })

# Appeals on the enforced + committee cases (discipline.appeal)
appeal_specs = [
    (enf_case, 'submitted',
     'Employee disputes the decision as too harsh given a clean record'),
    (cm_case, 'under_review',
     'Employee contests the witness statements and requests a re-hearing'),
    (enf_case, 'decided',
     'Formal appeal filed after internal mediation failed'),
]
for a_case, a_state, grounds in appeal_specs:
    if not a_case:
        continue
    existing = _find('discipline.appeal', [('case_id', '=', a_case.id),
                                           ('state', '=', a_state)])
    if existing:
        continue
    env['discipline.appeal'].create({
        'name': 'DEMO-APL-%03d' % (env['discipline.appeal'].search_count([]) + 1),
        'case_id': a_case.id,
        'employee_id': a_case.employee_id.id,
        'submission_date': TODAY - timedelta(days=3),
        'appeal_grounds': 'DEMO - %s' % grounds,
        'state': a_state,
        'reviewer_id': u_ceo.id,
        'decision_outcome': 'penalty_reduced' if a_state == 'decided' else False,
        'appeal_decision_notes': 'DEMO - penalty reduced to 3%' \
            if a_state == 'decided' else False,
    })
print('  discipline.appeal:', env['discipline.appeal'].search_count([]))

print('  discipline.investigation:', env['discipline.investigation'].search_count([]))
print('  discipline.committee.meeting:', env['discipline.committee.meeting'].search_count([]))
print('  discipline.suspension:', env['discipline.suspension'].search_count([]))
print('  discipline.payroll.penalty:', env['discipline.payroll.penalty'].search_count([]))

# ---------------------------------------------------------------------------
# SECTION 9 - Service Requests + Transfer Forms
# ---------------------------------------------------------------------------
_section('SECTION 9: Service Requests & Transfer Forms')

if 'service.request.type' in env and not env['service.request.type'].search_count([]):
    for st, cat in [('DEMO Acting', 'Acting'), ('DEMO Transfer', 'Transfer'),
                    ('DEMO Resignation', 'Resignation'), ('DEMO Others', 'Others'),
                    ('DEMO Guarantee Letter', 'Others'),
                    ('DEMO Support Letter', 'Others')]:
        env['service.request.type'].create({
            'sr_type': st,
            'sr_category': cat,
            'authorizing_office': 'head_office',
            'status': True,
        })

if 'employee.service.request' in env:
    sr_specs = [
        ('Acting', 'Acting', 'submitted', emp_hr_off,
         {'acting_vacant_position': job_hr_mgr.id,
          'acting_suggested_employee': emp_hr_off.id,
          'start_date': TODAY, 'end_date': TODAY + timedelta(days=60)}),
        ('Transfer', 'Transfer', 'in_progress', emp_loan,
         {'transfer_ou1': ou_merkato.id, 'transfer_ou2': ou_piassa.id,
          'transfer_ou3': ou_service.id}),
        ('Resignation', 'Resignation', 'completed', emp_driver, {}),
        ('DEMO Others', 'Others', 'draft', emp_cs, {}),
        ('DEMO Guarantee Letter', 'Self Service Letter', 'rejected',
         emp_teller,
         {'letter_name': 'Guarantee Letter',
          'name_of_the_external_person': 'John Smith',
          'name_of_the_organization': 'DEMO Construction PLC',
          'organization_address': 'Bole Road, Addis Ababa',
          'organization_email_address': 'hr@democonstruction.et',
          'type_guarantee': 'out', 'guarantee_amount': 50000.0}),
    ]
    for sr_type_name, sr_category, status, emp, extra in sr_specs:
        existing = _find('employee.service.request', [
            ('requestor', '=', emp.id), ('sr_category', '=', sr_category)])
        if existing:
            continue
        sr_type = env['service.request.type'].search(
            [('sr_type', '=', sr_type_name)], limit=1)
        vals = {
            'employee_id': emp.id,
            'requestor': emp.id,
            'sr_category': sr_category,
            'sr_comments': 'DEMO %s request for testing.' % sr_category,
            'authorizing_office': 'head_office',
            'status': status,
            'sr_date': TODAY,
            'expecting_date': TODAY,
        }
        if sr_type:
            vals['sr_type'] = sr_type.id
        vals.update(extra)
        req = env['employee.service.request'].create(vals)
        if hasattr(req, '_assign_reference_if_new'):
            req._assign_reference_if_new()
    print('  service requests:', env['employee.service.request'].search_count([]))

if 'transfer.form' in env:
    tr_specs = [
        (emp_loan, ou_merkato, 'draft', 'company'),
        (emp_fin_off, ou_district, 'populate', 'employee'),
        (emp_cs, ou_bole, 'authorize', 'company'),
        (emp_teller, ou_service, 'approve', 'employee'),
        (emp_recep, ou_piassa, 'reject', 'company'),
    ]
    for emp, target_ou, state, initiated in tr_specs:
        existing = _find('transfer.form', [('employee_name', '=', emp.id)])
        if existing:
            continue
        env['transfer.form'].create({
            'employee_name': emp.id,
            'requested_operating_unit': target_ou.id,
            'assigned_operating_unit': target_ou.id,
            'reason_for_transfer': 'DEMO transfer request for testing.',
            'transfer_requested_date': TODAY,
            'state': state,
            'transfer_initiated_by': initiated,
            'releiving_date': TODAY + timedelta(days=30),
            'reporting_date': TODAY + timedelta(days=35),
        })
    print('  transfer forms:', env['transfer.form'].search_count([]))

# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------
print('\n================ DEMO DATA SEEDED ================')
models_to_count = [
    'hr.report.code', 'employee.category', 'employee.grade', 'hr.department',
    'hr.job', 'operating.unit', 'hr.employee', 'hr.contract', 'hr.attendance',
    'over.time', 'attendance.preapproval', 'job.position.exception',
    'location.based.exception', 'leave.request', 'leave.request.manager',
    'over.time.consumption', 'discipline.offense', 'discipline.case',
    'discipline.investigation', 'discipline.committee.meeting',
    'discipline.suspension', 'discipline.appeal', 'discipline.payroll.penalty',
    'employee.service.request', 'transfer.form',
]
for model in models_to_count:
    if model in env:
        print('  %s: %s' % (model, env[model].search_count([])))

env.cr.commit()
print('\nDone - changes committed.')
