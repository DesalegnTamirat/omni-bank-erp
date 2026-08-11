import os
import random
from datetime import datetime, timedelta, date

import odoo
from odoo.tools import config
config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'odoo19'])

from odoo.modules.registry import Registry
from odoo.api import Environment

db_name = 'odoo19'
registry = Registry(db_name)

def clean_and_seed_36_employees():
    print("=================================================================")
    print("🧹 CLEANING DATABASE & SEEDING CLEAN 36 EMPLOYEES & DISTRICTS")
    print("=================================================================")

    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        company = env['res.company'].search([], limit=1)
        admin_user = env.ref('base.user_admin')
        admin_id = admin_user.id

        # -------------------------------------------------------------
        # 1. PURGE UNNECESSARY / STALE DATA
        # -------------------------------------------------------------
        print("\n--- 1. Purging Stale Employees & Orphan Records ---")
        
        # Keep list of valid employee logins
        valid_logins = [
            'admin', 'solomon', 'meron', 'yared', 'selam',
            'dawit', 'hana', 'abebe', 'chala', 'tadesse',
            'tigist', 'senait', 'alemu', 'bekele', 'genet',
            'mulu', 'kebede', 'leul', 'astewal', 'girma',
            'hiwot', 'feven', 'mesfin', 'yohannes', 'bethel',
            'biniam', 'tariku', 'eden', 'eyob', 'khalid',
            'marta', 'rahel', 'samuel', 'surafel', 'tinsae',
            'yonas'
        ]

        # Search employees not in valid logins
        stale_emps = env['hr.employee'].search([('user_id.login', 'not in', valid_logins)])
        if stale_emps:
            print(f"  - Deleting {len(stale_emps)} stale employee records...")
            # Unlink related custom records first
            cr.execute("DELETE FROM hr_version WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            cr.execute("DELETE FROM employee_education WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            cr.execute("DELETE FROM hr_attendance WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            cr.execute("DELETE FROM over_time WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            cr.execute("DELETE FROM attendance_preapproval WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            cr.execute("DELETE FROM discipline_case WHERE employee_id IN %s", (tuple(stale_emps.ids),))
            stale_emps.unlink()

        # Delete unused non-admin users created for stale emps
        stale_users = env['res.users'].search([('login', 'not in', valid_logins), ('id', '!=', admin_id), ('id', '!=', 1)])
        if stale_users:
            print(f"  - Deleting {len(stale_users)} stale user accounts...")
            stale_partners = stale_users.mapped('partner_id')
            stale_users.unlink()
            if stale_partners:
                stale_partners.unlink()

        # -------------------------------------------------------------
        # 2. SEED TOP-LEVEL DISTRICT DEPARTMENTS (`hr.department`)
        # -------------------------------------------------------------
        print("\n--- 2. Seeding Top-Level District Departments (Matching Screenshot 1) ---")
        dept_model = env['hr.department']
        ou_model = env['operating.unit']

        # Function to get or create top-level department
        def get_or_create_top_dept(name):
            d = dept_model.search([('name', '=', name)], limit=1)
            if not d:
                d = dept_model.create({
                    'name': name,
                    'company_id': company.id,
                    'parent_id': False,  # Top level so it appears in the primary sidebar list!
                })
                print(f"  + Created Top Department: {name}")
            else:
                d.write({'parent_id': False})  # Ensure it is top-level
            return d

        district_dept_names = [
            'Head Office',
            'Adama District Office',
            'Bahir Dar District Office',
            'Debre Berhan District Office',
            'Debre Markos District Office',
            'Dessie District Office',
            'East Addis Ababa District Office',
            'Hawassa District Office',
            'Jimma District Office',
            'Mekelle District Office',
            'South Addis Ababa District Office',
            'West Addis Ababa District Office'
        ]

        top_depts = {}
        for d_name in district_dept_names:
            top_depts[d_name] = get_or_create_top_dept(d_name)

        # -------------------------------------------------------------
        # 3. SEED OPERATING UNITS
        # -------------------------------------------------------------
        print("\n--- 3. Seeding Operating Units Hierarchy ---")
        def get_or_create_ou(name, work_unit_type, parent_unit=None, sol_id=100):
            ou = ou_model.search([('name', '=', name)], limit=1)
            if not ou:
                vals = {
                    'name': name,
                    'company_id': company.id,
                    'work_unit_type': work_unit_type,
                    'sol_id': sol_id,
                }
                if parent_unit:
                    vals['parent_unit'] = parent_unit.id
                ou = ou_model.create(vals)
            return ou

        ou_ho = get_or_create_ou('Head Office', 'head_office', sol_id=1001)

        # Create OUs for District Offices
        district_ous = {}
        sol_c = 2000
        for d_name in district_dept_names:
            if d_name != 'Head Office':
                sol_c += 10
                district_ous[d_name] = get_or_create_ou(d_name, 'district_office', parent_unit=ou_ho, sol_id=sol_c)
            else:
                district_ous[d_name] = ou_ho

        # Link Operating Unit to Department where missing
        for d_name, d_rec in top_depts.items():
            if 'operating_unit_id' in dept_model._fields:
                d_rec.operating_unit_id = district_ous[d_name].id

        # -------------------------------------------------------------
        # 4. JOB GRADES & POSITIONS
        # -------------------------------------------------------------
        print("\n--- 4. Seeding Job Grades & Positions ---")
        grade_model = env['employee.grade']
        grades = {}
        for g_num in range(1, 17):
            g_code = f"GRADE-{g_num:02d}"
            g_rec = grade_model.search([('grade_code', '=', g_code)], limit=1)
            if not g_rec:
                g_rec = grade_model.create({
                    'grade_code': g_code,
                    'grade_name': f"Grade {g_num}",
                    'grade_level': 'senior' if g_num >= 10 else 'junior',
                    'base_salary': 15000 + (g_num * 10000),
                    'salary_factor': 1.2,
                })
            grades[g_num] = g_rec

        job_model = env['hr.job']
        def get_or_create_job(name, dept, grade_rec=None):
            j = job_model.search([('name', '=', name)], limit=1)
            if not j:
                vals = {
                    'name': name,
                    'department_id': dept.id,
                    'minimum_pms_score': 3.5,
                    'minimum_number_years_in_company': 2,
                }
                if grade_rec and 'grade' in job_model._fields:
                    vals['grade'] = grade_rec.id
                j = job_model.create(vals)
            return j

        job_ceo      = get_or_create_job('Chief Executive Officer', top_depts['Head Office'], grades[16])
        job_hr_dir   = get_or_create_job('HR Director', top_depts['Head Office'], grades[14])
        job_it_dir   = get_or_create_job('IT Director', top_depts['Head Office'], grades[15])
        job_fin_dir  = get_or_create_job('Finance Director', top_depts['Head Office'], grades[14])
        job_rb_mgr   = get_or_create_job('Retail Banking Manager', top_depts['East Addis Ababa District Office'], grades[13])
        job_sr_dev   = get_or_create_job('Senior Software Engineer', top_depts['Head Office'], grades[11])
        job_dev      = get_or_create_job('Software Developer', top_depts['Head Office'], grades[9])
        job_jr_dev   = get_or_create_job('Junior Software Engineer', top_depts['Head Office'], grades[7])
        job_dba      = get_or_create_job('Database Administrator', top_depts['Head Office'], grades[10])
        job_hr_off   = get_or_create_job('HR Officer', top_depts['Head Office'], grades[8])
        job_rec_spec = get_or_create_job('Recruitment Specialist', top_depts['Head Office'], grades[9])
        job_cso      = get_or_create_job('Customer Service Officer', top_depts['East Addis Ababa District Office'], grades[7])
        job_boo      = get_or_create_job('Branch Operations Officer', top_depts['West Addis Ababa District Office'], grades[8])
        job_accountant= get_or_create_job('Senior Accountant', top_depts['Head Office'], grades[10])
        job_risk_analyst= get_or_create_job('Risk Analyst', top_depts['Head Office'], grades[10])

        # -------------------------------------------------------------
        # 5. EXACT CLEAN 36 EMPLOYEES DATASET
        # -------------------------------------------------------------
        print("\n--- 5. Seeding Exact Clean 36 Employees Dataset ---")
        emp_model = env['hr.employee']
        user_model = env['res.users'].with_context(no_reset_password=True, mail_create_nolog=True)
        partner_model = env['res.partner']

        group_user = env.ref('base.group_user')
        group_att_user = env.ref('hr_attendance.group_hr_attendance_user')
        group_att_admin = env.ref('hr_attendance.group_hr_attendance_manager')
        group_hr_user = env.ref('hr.group_hr_user')
        group_hr_manager = env.ref('hr.group_hr_manager')
        group_it_driver = env.ref('custom_hr_attendance.group_hr_attendance_it_driver_user', raise_if_not_found=False)
        group_job_pos = env.ref('custom_hr_attendance.group_hr_attendance_job_position_user', raise_if_not_found=False)

        # 36 Defined Employees distributed across Head Office & 12 Districts
        employee_specs = [
            # Top Management & HO (20 Employees)
            ('admin', 'Administrator', 'EMP-00101', job_ceo, top_depts['Head Office'], district_ous['Head Office'], None, grades[16], 220000, 4.9, '1980-01-15', '2016-01-01', [group_hr_manager, group_att_admin]),
            ('solomon', 'Solomon Kassa Desta', 'EMP-00102', job_hr_dir, top_depts['Head Office'], district_ous['Head Office'], 'admin', grades[14], 150000, 4.6, '1985-04-12', '2018-03-01', [group_hr_manager, group_att_user]),
            ('meron', 'Meron Hailemariam Tadesse', 'EMP-00103', job_it_dir, top_depts['Head Office'], district_ous['Head Office'], 'admin', grades[15], 160000, 4.7, '1986-09-20', '2017-06-15', [group_hr_manager, group_att_user, group_it_driver] if group_it_driver else [group_hr_manager]),
            ('yared', 'Yared Worku Tesfaye', 'EMP-00104', job_fin_dir, top_depts['Head Office'], district_ous['Head Office'], 'admin', grades[14], 155000, 4.5, '1984-11-05', '2018-01-10', [group_hr_user, group_att_user]),
            ('dawit', 'Dawit Alemu Fikre', 'EMP-00106', job_sr_dev, top_depts['Head Office'], district_ous['Head Office'], 'meron', grades[11], 85000, 4.3, '1990-07-14', '2020-05-01', [group_att_user]),
            ('hana', 'Hana Tadesse Bekele', 'EMP-00107', job_dev, top_depts['Head Office'], district_ous['Head Office'], 'dawit', grades[9], 60000, 3.9, '1993-12-01', '2021-08-15', [group_user]),
            ('abebe', 'Abebe Bikila Worku', 'EMP-00108', job_dev, top_depts['Head Office'], district_ous['Head Office'], 'dawit', grades[9], 62000, 4.1, '1992-05-10', '2021-02-01', [group_user]),
            ('chala', 'Chala Kebede Lema', 'EMP-00109', job_dba, top_depts['Head Office'], district_ous['Head Office'], 'meron', grades[10], 75000, 4.2, '1991-08-22', '2020-11-10', [group_user]),
            ('tadesse', 'Tadesse Kassahun Gebre', 'EMP-00110', job_rec_spec, top_depts['Head Office'], district_ous['Head Office'], 'solomon', grades[9], 65000, 4.4, '1992-02-18', '2020-09-01', [group_hr_user]),
            ('tigist', 'Tigist Assefa Mengistu', 'EMP-00111', job_hr_off, top_depts['Head Office'], district_ous['Head Office'], 'solomon', grades[8], 55000, 4.0, '1994-06-25', '2022-01-15', [group_hr_user]),
            ('senait', 'Senait Haile Wolde', 'EMP-00112', job_hr_off, top_depts['Head Office'], district_ous['Head Office'], 'tadesse', grades[8], 52000, 3.8, '1995-10-10', '2022-06-01', [group_user]),
            ('alemu', 'Alemu Desta Workneh', 'EMP-00113', job_accountant, top_depts['Head Office'], district_ous['Head Office'], 'yared', grades[10], 72000, 4.1, '1989-01-05', '2019-10-01', [group_user]),
            ('bekele', 'Bekele Shiferaw Ayana', 'EMP-00114', job_accountant, top_depts['Head Office'], district_ous['Head Office'], 'alemu', grades[10], 70000, 3.9, '1991-04-17', '2021-03-15', [group_user]),
            ('eyob', 'Eyob Tekle Berhan', 'EMP-00127', job_accountant, top_depts['Head Office'], district_ous['Head Office'], 'yared', grades[10], 71000, 4.0, '1990-03-11', '2020-02-01', [group_user]),
            ('biniam', 'Biniam Million Hailu', 'EMP-00128', job_risk_analyst, top_depts['Head Office'], district_ous['Head Office'], 'admin', grades[10], 73000, 4.2, '1990-09-09', '2019-07-01', [group_user]),
            ('tariku', 'Tariku Abera Demissie', 'EMP-00129', job_risk_analyst, top_depts['Head Office'], district_ous['Head Office'], 'biniam', grades[10], 72000, 4.1, '1991-11-15', '2020-04-01', [group_user]),
            ('marta', 'Marta Yosef Kebede', 'EMP-00130', job_jr_dev, top_depts['Head Office'], district_ous['Head Office'], 'dawit', grades[7], 48000, 3.8, '1996-01-20', '2023-01-15', [group_user]),
            ('surafel', 'Surafel Girma Belay', 'EMP-00131', job_dev, top_depts['Head Office'], district_ous['Head Office'], 'dawit', grades[9], 61000, 4.0, '1993-04-10', '2021-11-01', [group_user]),
            ('samuel', 'Samuel Bekele ForcedCO', 'EMP-00132', job_dev, top_depts['Head Office'], district_ous['Head Office'], 'meron', grades[9], 63000, 4.1, '1992-08-08', '2021-05-10', [group_user]),
            ('eden', 'Eden Bogale Workneh', 'EMP-00133', job_cso, top_depts['Head Office'], district_ous['Head Office'], 'admin', grades[7], 45000, 4.0, '1997-05-12', '2023-02-01', [group_user]),

            # East Addis Ababa District Office (3 Employees)
            ('selam', 'Selamawit Gebre Egziabher', 'EMP-00105', job_rb_mgr, top_depts['East Addis Ababa District Office'], district_ous['East Addis Ababa District Office'], 'admin', grades[13], 140000, 4.4, '1988-03-30', '2019-02-01', [group_hr_user, group_att_user, group_job_pos] if group_job_pos else [group_hr_user]),
            ('genet', 'Genet Zewde Tefera', 'EMP-00115', job_cso, top_depts['East Addis Ababa District Office'], district_ous['East Addis Ababa District Office'], 'selam', grades[7], 45000, 4.2, '1996-08-12', '2022-09-01', [group_user]),
            ('mulu', 'Mulugeta Teshome Bedane', 'EMP-00116', job_cso, top_depts['East Addis Ababa District Office'], district_ous['East Addis Ababa District Office'], 'selam', grades[7], 46000, 4.0, '1995-11-20', '2022-04-10', [group_user]),

            # West Addis Ababa District Office (3 Employees)
            ('kebede', 'Kebede Girma Feyissa', 'EMP-00117', job_rb_mgr, top_depts['West Addis Ababa District Office'], district_ous['West Addis Ababa District Office'], 'admin', grades[13], 135000, 4.3, '1987-07-07', '2018-11-01', [group_att_user]),
            ('leul', 'Leul Mekonnen Yohannes', 'EMP-00118', job_cso, top_depts['West Addis Ababa District Office'], district_ous['West Addis Ababa District Office'], 'kebede', grades[7], 44000, 3.7, '1997-03-14', '2023-01-10', [group_user]),
            ('astewal', 'Astewal Getachew Nigusse', 'EMP-00119', job_cso, top_depts['West Addis Ababa District Office'], district_ous['West Addis Ababa District Office'], 'kebede', grades[7], 45000, 4.1, '1996-05-22', '2022-11-01', [group_user]),

            # Hawassa District Office (3 Employees)
            ('girma', 'Girma Bogale Tadesse', 'EMP-00120', job_rb_mgr, top_depts['Hawassa District Office'], district_ous['Hawassa District Office'], 'admin', grades[13], 130000, 4.2, '1986-12-01', '2019-05-15', [group_att_user]),
            ('hiwot', 'Hiwot Mulugeta Alemu', 'EMP-00121', job_cso, top_depts['Hawassa District Office'], district_ous['Hawassa District Office'], 'girma', grades[7], 43000, 4.0, '1997-09-09', '2023-02-01', [group_user]),
            ('feven', 'Feven Berhane Kidane', 'EMP-00122', job_cso, top_depts['Hawassa District Office'], district_ous['Hawassa District Office'], 'girma', grades[7], 42000, 3.8, '1998-01-30', '2023-05-10', [group_user]),

            # Adama District Office (3 Employees)
            ('mesfin', 'Mesfin Worku Tilahun', 'EMP-00123', job_rb_mgr, top_depts['Adama District Office'], district_ous['Adama District Office'], 'admin', grades[13], 132000, 4.4, '1987-10-10', '2019-01-15', [group_att_user]),
            ('yohannes', 'Yohannes Abebe Desta', 'EMP-00124', job_cso, top_depts['Adama District Office'], district_ous['Adama District Office'], 'mesfin', grades[7], 44000, 4.1, '1996-02-14', '2022-10-01', [group_user]),
            ('bethel', 'Bethelhem Samuel Haile', 'EMP-00125', job_cso, top_depts['Adama District Office'], district_ous['Adama District Office'], 'mesfin', grades[7], 43000, 3.9, '1997-06-18', '2023-03-01', [group_user]),

            # Other District Offices (4 Staff across remaining districts)
            ('khalid', 'Khalid Ahmed Hassan', 'EMP-00126', job_boo, top_depts['Bahir Dar District Office'], district_ous['Bahir Dar District Office'], 'admin', grades[8], 54000, 4.1, '1994-10-12', '2021-09-01', [group_user]),
            ('rahel', 'Rahel Solomon Tessema', 'EMP-00134', job_cso, top_depts['Dessie District Office'], district_ous['Dessie District Office'], 'admin', grades[7], 44000, 4.0, '1997-01-11', '2023-04-01', [group_user]),
            ('tinsae', 'Tinsae Getachew Alemu', 'EMP-00135', job_cso, top_depts['Mekelle District Office'], district_ous['Mekelle District Office'], 'admin', grades[7], 43000, 3.9, '1998-03-03', '2023-06-01', [group_user]),
            ('yonas', 'Yonas Berhanu Kidane', 'EMP-00136', job_cso, top_depts['Debre Markos District Office'], district_ous['Debre Markos District Office'], 'admin', grades[7], 44000, 4.1, '1996-07-07', '2022-12-01', [group_user]),
        ]

        created_employees = {}
        created_users = {}

        # Create or update 36 employees
        for login, name, emp_code, job, dept, ou, manager_login, grade, salary, pms, dob, hire_date, groups in employee_specs:
            user = env['res.users'].search([('login', '=', login)], limit=1)
            if not user:
                partner = partner_model.create({
                    'name': name,
                    'email': f"{login}@bunnabanksc.com",
                    'city': 'Addis Ababa',
                })
                user = user_model.create({
                    'name': name,
                    'login': login,
                    'password': 'password123',
                    'email': f"{login}@bunnabanksc.com",
                    'partner_id': partner.id,
                })
                for g in groups:
                    if g:
                        g.sudo().write({'user_ids': [(4, user.id)]})
            created_users[login] = user

            emp = emp_model.search([('employee_identification', '=', emp_code)], limit=1)
            if not emp:
                emp = emp_model.search([('user_id', '=', user.id)], limit=1)

            emp_vals = {
                'name': name,
                'employee_identification': emp_code,
                'job_id': job.id,
                'job_position': job.id,
                'department_id': dept.id,
                'default_operating_unit_id': ou.id,
                'operating_unit_id': ou.id,
                'user_id': user.id,
                'wage': salary,
                'pms_score': pms,
                'birthday': dob,
                'first_contract_date': hire_date,
                'service_hire_date': hire_date,
                'service_start_date': hire_date,
                'work_email': f"{login}@bunnabanksc.com",
                'gender': 'male' if 'Alemu' in name or 'Solomon' in name or 'Yared' in name or 'Dawit' in name or 'Abebe' in name or 'Chala' in name or 'Tadesse' in name or 'Bekele' in name or 'Mulugeta' in name or 'Kebede' in name or 'Leul' in name or 'Girma' in name or 'Mesfin' in name or 'Yohannes' in name or 'Tariku' in name or 'Biniam' in name or 'Surafel' in name or 'Samuel' in name or 'Eyob' in name or 'Khalid' in name or 'Yonas' in name else 'female',
            }
            if 'job_grade' in emp_model._fields and grade:
                emp_vals['job_grade'] = grade.id

            if not emp:
                emp = emp_model.create(emp_vals)
            else:
                emp.write(emp_vals)

            created_employees[login] = emp

        # Assign Department Managers
        top_depts['Head Office'].manager_id = created_employees['admin'].id
        top_depts['East Addis Ababa District Office'].manager_id = created_employees['selam'].id
        top_depts['West Addis Ababa District Office'].manager_id = created_employees['kebede'].id
        top_depts['Hawassa District Office'].manager_id = created_employees['girma'].id
        top_depts['Adama District Office'].manager_id = created_employees['mesfin'].id

        # Assign Parent/Coach Hierarchy
        for login, _, _, _, _, _, manager_login, _, _, _, _, _, _ in employee_specs:
            emp = created_employees[login]
            if manager_login and manager_login in created_employees:
                mgr_emp = created_employees[manager_login]
                emp.write({
                    'parent_id': mgr_emp.id,
                    'coach_id': mgr_emp.id,
                })

        # -------------------------------------------------------------
        # 6. EMPLOYMENT VERSION (`hr.version`) RECORDS
        # -------------------------------------------------------------
        print("\n--- 6. Seeding Employment Version History ---")
        version_model = env['hr.version']
        for login, emp in created_employees.items():
            existing_ver = version_model.search([('employee_id', '=', emp.id)], limit=1)
            if not existing_ver:
                hire_date = emp.first_contract_date or date(2020, 1, 1)
                dt_from = datetime.combine(hire_date, datetime.min.time())
                dt_to = datetime.now()

                version_model.create({
                    'name': f"Initial Version - {emp.name}",
                    'employee_id': emp.id,
                    'date_version': hire_date,
                    'date_generated_from': dt_from,
                    'date_generated_to': dt_to,
                    'last_modified_date': dt_to,
                    'last_modified_uid': admin_id,
                    'hr_responsible_id': admin_id,
                    'distance_home_work_unit': 'km',
                    'employee_type': 'employee',
                    'marital': 'married' if random.choice([True, False]) else 'single',
                    'job_grade': emp.job_grade.id if emp.job_grade else grades[8].id,
                    'work_entry_source': 'attendance',
                    'department_id': emp.department_id.id,
                    'operating_unit_id': emp.default_operating_unit_id.id,
                    'job_id': emp.job_id.id,
                    'wage': emp.wage or 50000,
                    'pms_score': emp.pms_score or 4.0,
                    'is_current': True,
                })

        # -------------------------------------------------------------
        # 7. EDUCATIONAL & EXPERIENCE RECORDS
        # -------------------------------------------------------------
        print("\n--- 7. Seeding Educational Records ---")
        edu_model = env['employee.education']
        sample_schools = ['Addis Ababa University', 'Bahir Dar University', 'Hawassa University', 'Adama Science and Technology University']
        sample_qualifications = ['B.Sc in Computer Science', 'M.Sc in Information Technology', 'BA in Business Administration', 'B.Sc in Accounting & Finance']

        for login, emp in created_employees.items():
            existing_edu = edu_model.search([('employee_id', '=', emp.id)], limit=1)
            if not existing_edu:
                edu_model.create({
                    'employee_id': emp.id,
                    'school_name': random.choice(sample_schools),
                    'qualification': random.choice(sample_qualifications),
                    'field': 'Computer Science / Finance / Business',
                    'CGPA': round(random.uniform(3.2, 3.9), 2),
                    'from_date': date(2012, 9, 1),
                    'to_date': date(2016, 7, 1),
                })

        # -------------------------------------------------------------
        # 8. ATTENDANCE & OVERTIME RECORDS
        # -------------------------------------------------------------
        print("\n--- 8. Seeding Attendance & Overtime Records ---")
        att_model = env['hr.attendance'].with_context(skip_duplicate_check=True)
        pre_model = env['attendance.preapproval']
        ot_model = env['over.time']
        today = date.today()

        for days_back in range(1, 11):
            check_date = today - timedelta(days=days_back)
            if check_date.weekday() >= 5:
                continue

            for login in ['dawit', 'hana', 'abebe', 'tadesse', 'tigist', 'alemu', 'genet', 'mulu']:
                emp = created_employees[login]
                check_in_dt = datetime.combine(check_date, datetime.min.time()) + timedelta(hours=8, minutes=random.randint(0, 30))
                check_out_dt = datetime.combine(check_date, datetime.min.time()) + timedelta(hours=17, minutes=random.randint(0, 45))
                late_hrs = max(0.0, (check_in_dt.minute - 15) / 60.0) if check_in_dt.minute > 15 else 0.0

                att_rec = att_model.search([('employee_id', '=', emp.id), ('check_in', '>=', check_in_dt - timedelta(hours=1)), ('check_in', '<=', check_in_dt + timedelta(hours=1))], limit=1)
                if not att_rec:
                    att_vals = {
                        'employee_id': emp.id,
                        'check_in': check_in_dt,
                        'check_out': check_out_dt,
                        'check_in_status': 'Late' if late_hrs > 0 else 'Normal',
                        'late_time_hour': late_hrs,
                        'is_acknowledged': True if late_hrs > 0 else False,
                    }
                    if late_hrs > 0:
                        att_vals['acknowledged_by'] = admin_id
                        att_vals['acknowledged_date'] = datetime.now()
                        att_vals['acknowledged_late'] = late_hrs
                    try:
                        att_model.create(att_vals)
                    except Exception:
                        pass

        # -------------------------------------------------------------
        # 9. DISCIPLINE MANAGEMENT & RECRUITMENT DEMO DATA
        # -------------------------------------------------------------
        print("\n--- 9. Seeding Discipline & Recruitment Demo Data ---")
        offense_cat_model = env['discipline.offense.category']
        offense_model = env['discipline.offense']
        case_model = env['discipline.case']

        off_cat = offense_cat_model.search([('code', '=', 'CAT-ATT-01')], limit=1)
        if not off_cat:
            off_cat = offense_cat_model.create({'name': 'Attendance & Punctuality', 'code': 'CAT-ATT-01'})

        offense = offense_model.search([('name', '=', 'Repeated Unexcused Lateness')], limit=1)
        if not offense:
            offense = offense_model.create({
                'name': 'Repeated Unexcused Lateness',
                'category_id': off_cat.id,
                'severity_level': 'level_5',
                'punishment_type': 'verbal_warning',
                'approval_authority': 'direct_manager',
            })

        disc_emp = created_employees['hana']
        existing_case = case_model.search([('employee_id', '=', disc_emp.id)], limit=1)
        if not existing_case:
            case_model.create({
                'name': 'DISC-2026-001',
                'employee_id': disc_emp.id,
                'incident_date': today - timedelta(days=5),
                'description': 'Repeated lateness exceeding 30 minutes on 3 consecutive days without prior authorization.',
                'offense_id': offense.id,
                'company_id': company.id,
                'state': 'initiated',
            })

        applicant_model = env['hr.applicant']
        stage_model = env['hr.recruitment.stage']
        initial_stage = stage_model.search([], limit=1)

        applicants_data = [
            ('Abebech Tadesse', 'abebech.candidate@gmail.com', '+251911223344', job_dev),
            ('Kassahun Wolde', 'kassahun.candidate@gmail.com', '+251922334455', job_accountant),
            ('Yirgalem Haile', 'yirgalem.candidate@gmail.com', '+251933445566', job_cso),
        ]

        for p_name, p_email, p_phone, job_pos in applicants_data:
            app = applicant_model.search([('partner_name', '=', p_name)], limit=1)
            if not app:
                app_vals = {
                    'partner_name': p_name,
                    'email_from': p_email,
                    'partner_phone': p_phone,
                    'job_id': job_pos.id,
                    'department_id': job_pos.department_id.id,
                    'salary_expected': 65000,
                    'salary_proposed': 60000,
                }
                if initial_stage:
                    app_vals['stage_id'] = initial_stage.id
                applicant_model.create(app_vals)

        cr.commit()

        final_count = env['hr.employee'].search_count([])
        print("\n=================================================================")
        print(f"✅ CLEAN DATABASE SEEDING COMPLETED! Total active employees: {final_count}")
        print("=================================================================")

if __name__ == '__main__':
    clean_and_seed_36_employees()
