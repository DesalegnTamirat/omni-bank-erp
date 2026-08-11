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

def run_seed():
    print("=================================================================")
    print("🚀 STARTING COMPREHENSIVE END-TO-END DEMO DATA SEEDING FOR ODOO 19")
    print("=================================================================")

    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        
        admin_user = env.ref('base.user_admin')
        admin_id = admin_user.id
        company = env['res.company'].search([], limit=1)

        # -------------------------------------------------------------
        # 1. ORGANIZATIONAL STRUCTURE: OPERATING UNITS
        # -------------------------------------------------------------
        print("\n--- 1. Seeding Operating Units Hierarchy ---")
        ou_model = env['operating.unit']

        def get_or_create_ou(name, work_unit_type, parent_unit=None, district=None, sol_id=100):
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
                if district:
                    vals['district'] = district
                ou = ou_model.create(vals)
                print(f"  + Created Operating Unit: {name} ({work_unit_type})")
            else:
                if parent_unit and not ou.parent_unit:
                    ou.parent_unit = parent_unit.id
            return ou

        # 1.1 Head Office Root
        ou_ho = get_or_create_ou('Head Office', 'head_office', sol_id=1001)

        # 1.2 Chief Offices (under Head Office)
        ou_cido = get_or_create_ou('Chief Information and Digital Office', 'head_office', parent_unit=ou_ho, sol_id=1002)
        ou_cpco = get_or_create_ou('Chief People and Culture Office', 'head_office', parent_unit=ou_ho, sol_id=1003)
        ou_crpo = get_or_create_ou('Chief Retail and Portfolio Office', 'head_office', parent_unit=ou_ho, sol_id=1004)
        ou_cfo  = get_or_create_ou('Chief Financial Office', 'head_office', parent_unit=ou_ho, sol_id=1005)

        # 1.3 Directorates
        ou_eado_dir = get_or_create_ou('Enterprise Application Development and Operation Directorate', 'head_office', parent_unit=ou_cido, sol_id=1011)
        ou_pom_dir  = get_or_create_ou('People Operations Management Directorate', 'head_office', parent_unit=ou_cpco, sol_id=1012)
        ou_rb_dir   = get_or_create_ou('Retail Banking Directorate', 'head_office', parent_unit=ou_crpo, sol_id=1013)
        ou_fa_dir   = get_or_create_ou('Financial Accounting Directorate', 'head_office', parent_unit=ou_cfo, sol_id=1014)

        # 1.4 Divisions
        ou_ead_div = get_or_create_ou('Enterprise Application Development Division', 'head_office', parent_unit=ou_eado_dir, sol_id=1021)
        ou_cbs_div = get_or_create_ou('Core Banking Support Division', 'head_office', parent_unit=ou_eado_dir, sol_id=1022)
        ou_rec_div = get_or_create_ou('Onboarding and Recruitment Division', 'head_office', parent_unit=ou_pom_dir, sol_id=1023)
        ou_er_div  = get_or_create_ou('Employee Relations Division', 'head_office', parent_unit=ou_pom_dir, sol_id=1024)

        # 1.5 Districts & Branch Operating Units
        districts_spec = [
            ('East Addis Ababa District', ['Arat Kilo Branch', 'Bole Branch', 'Kazanchis Branch']),
            ('West Addis Ababa District', ['Merkato Branch', 'Mexico Branch', 'Piassa Branch']),
            ('South Addis Ababa District', ['Sarbet Branch', 'Gotera Branch']),
            ('Bahir Dar District', ['Bahir Dar Main Branch', 'Tana Branch']),
            ('Dessie District', ['Dessie Main Branch', 'Piazza Branch Dessie']),
            ('Mekelle District', ['Mekelle Main Branch', 'Kedamay Weyane Branch']),
            ('Debre Markos District', ['Debre Markos Main Branch']),
            ('Debre Birhan District', ['Debre Birhan Main Branch']),
            ('Hawassa District', ['Hawassa Main Branch', 'Tabor Branch']),
            ('Adama District', ['Adama Main Branch', 'Geda Branch']),
            ('Jimma District', ['Jimma Main Branch']),
        ]

        district_ous = {}
        branch_ous = {}
        sol_counter = 2000

        for dist_name, branches in districts_spec:
            sol_counter += 10
            dist_ou = get_or_create_ou(dist_name, 'district_office', parent_unit=ou_ho, district=dist_name, sol_id=sol_counter)
            district_ous[dist_name] = dist_ou
            for b_name in branches:
                sol_counter += 1
                b_ou = get_or_create_ou(b_name, 'branch', parent_unit=dist_ou, district=dist_name, sol_id=sol_counter)
                branch_ous[b_name] = b_ou

        # -------------------------------------------------------------
        # 2. DEPARTMENTS (`hr.department`) - COMPLETE HIERARCHY & DISTRICTS
        # -------------------------------------------------------------
        print("\n--- 2. Seeding Departments & District Tree ---")
        dept_model = env['hr.department']

        def get_or_create_dept(name, ou=None, parent_dept=None):
            d = dept_model.search([('name', '=', name)], limit=1)
            if not d:
                vals = {'name': name, 'company_id': company.id}
                if ou and 'operating_unit_id' in dept_model._fields:
                    vals['operating_unit_id'] = ou.id
                if parent_dept:
                    vals['parent_id'] = parent_dept.id
                d = dept_model.create(vals)
                print(f"  + Created Department: {name}")
            else:
                vals = {}
                if ou and 'operating_unit_id' in dept_model._fields and not d.operating_unit_id:
                    vals['operating_unit_id'] = ou.id
                if parent_dept and not d.parent_id:
                    vals['parent_id'] = parent_dept.id
                if vals:
                    d.write(vals)
            return d

        # Root Head Office Department
        dept_ho = get_or_create_dept('Head Office', ou_ho)
        dept_exec = get_or_create_dept('Executive Office', ou_ho, parent_dept=dept_ho)

        # Chief Offices Departments
        dept_cido = get_or_create_dept('Chief Information and Digital Office', ou_cido, parent_dept=dept_ho)
        dept_cpco = get_or_create_dept('Chief People and Culture Office', ou_cpco, parent_dept=dept_ho)
        dept_cfo  = get_or_create_dept('Chief Financial Office', ou_cfo, parent_dept=dept_ho)
        dept_crpo = get_or_create_dept('Chief Retail and Portfolio Office', ou_crpo, parent_dept=dept_ho)

        # Directorates Departments
        dept_eado_dir = get_or_create_dept('Enterprise Application Development and Operation Directorate', ou_eado_dir, parent_dept=dept_cido)
        dept_pom_dir  = get_or_create_dept('People Operations Management Directorate', ou_pom_dir, parent_dept=dept_cpco)
        dept_fa_dir   = get_or_create_dept('Financial Accounting Directorate', ou_fa_dir, parent_dept=dept_cfo)
        dept_rb_dir   = get_or_create_dept('Retail Banking Directorate', ou_rb_dir, parent_dept=dept_crpo)
        dept_risk     = get_or_create_dept('Risk and Compliance', ou_ho, parent_dept=dept_ho)

        # Legacy / Alias Departments for compatibility
        dept_it   = get_or_create_dept('Information Technology', ou_ead_div, parent_dept=dept_eado_dir)
        dept_hr   = get_or_create_dept('Human Resources', ou_rec_div, parent_dept=dept_pom_dir)
        dept_fin  = get_or_create_dept('Finance and Accounting', ou_fa_dir, parent_dept=dept_fa_dir)
        dept_rb   = get_or_create_dept('Retail Banking', district_ous['East Addis Ababa District'], parent_dept=dept_rb_dir)

        # Divisions Departments
        dept_ead_div = get_or_create_dept('Enterprise Application Development Division', ou_ead_div, parent_dept=dept_eado_dir)
        dept_cbs_div = get_or_create_dept('Core Banking Support Division', ou_cbs_div, parent_dept=dept_eado_dir)
        dept_rec_div = get_or_create_dept('Onboarding and Recruitment Division', ou_rec_div, parent_dept=dept_pom_dir)
        dept_er_div  = get_or_create_dept('Employee Relations Division', ou_er_div, parent_dept=dept_pom_dir)

        # 12 District Departments in `hr.department`
        district_depts = {}
        for dist_name, branches in districts_spec:
            dist_ou = district_ous[dist_name]
            dist_d = get_or_create_dept(dist_name, dist_ou, parent_dept=dept_rb_dir)
            district_depts[dist_name] = dist_d

        # -------------------------------------------------------------
        # 3. JOB GRADES & JOB POSITIONS
        # -------------------------------------------------------------
        print("\n--- 3. Seeding Job Grades & Job Positions ---")
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

        def get_or_create_job(name, dept, grade_rec=None, min_pms=3.5, min_exp_years=2):
            j = job_model.search([('name', '=', name)], limit=1)
            if not j:
                vals = {
                    'name': name,
                    'department_id': dept.id,
                    'minimum_pms_score': min_pms,
                    'minimum_number_years_in_company': min_exp_years,
                }
                if grade_rec and 'grade' in job_model._fields:
                    vals['grade'] = grade_rec.id
                j = job_model.create(vals)
                print(f"  + Created Job Position: {name}")
            return j

        job_ceo      = get_or_create_job('Chief Executive Officer', dept_exec, grades[16], min_pms=4.5, min_exp_years=10)
        job_hr_dir   = get_or_create_job('HR Director', dept_cpco, grades[14], min_pms=4.2, min_exp_years=6)
        job_it_dir   = get_or_create_job('IT Director', dept_cido, grades[15], min_pms=4.2, min_exp_years=6)
        job_fin_dir  = get_or_create_job('Finance Director', dept_cfo, grades[14], min_pms=4.2, min_exp_years=6)
        job_rb_mgr   = get_or_create_job('Retail Banking Manager', dept_rb_dir, grades[13], min_pms=4.0, min_exp_years=5)
        job_sr_dev   = get_or_create_job('Senior Software Engineer', dept_ead_div, grades[11], min_pms=3.8, min_exp_years=3)
        job_dev      = get_or_create_job('Software Developer', dept_ead_div, grades[9], min_pms=3.5, min_exp_years=1)
        job_dba      = get_or_create_job('Database Administrator', dept_ead_div, grades[10], min_pms=3.8, min_exp_years=3)
        job_hr_off   = get_or_create_job('HR Officer', dept_er_div, grades[8], min_pms=3.5, min_exp_years=2)
        job_rec_spec = get_or_create_job('Recruitment Specialist', dept_rec_div, grades[9], min_pms=3.8, min_exp_years=2)
        job_cso      = get_or_create_job('Customer Service Officer', dept_rb, grades[7], min_pms=3.5, min_exp_years=1)
        job_accountant= get_or_create_job('Senior Accountant', dept_fa_dir, grades[10], min_pms=3.8, min_exp_years=3)

        # -------------------------------------------------------------
        # 4. EMPLOYEES & USERS DATASET (30 Complete Employees)
        # -------------------------------------------------------------
        print("\n--- 4. Seeding Employees, Users, & Hierarchy ---")
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

        employee_specs = [
            # Top Execs
            ('admin', 'Administrator', 'EMP-00101', job_ceo, dept_exec, ou_ho, None, grades[16], 220000, 4.9, '1980-01-15', '2016-01-01', [group_hr_manager, group_att_admin]),
            ('solomon', 'Solomon Kassa Desta', 'EMP-00102', job_hr_dir, dept_cpco, ou_rec_div, 'admin', grades[14], 150000, 4.6, '1985-04-12', '2018-03-01', [group_hr_manager, group_att_user]),
            ('meron', 'Meron Hailemariam Tadesse', 'EMP-00103', job_it_dir, dept_cido, ou_ead_div, 'admin', grades[15], 160000, 4.7, '1986-09-20', '2017-06-15', [group_hr_manager, group_att_user, group_it_driver] if group_it_driver else [group_hr_manager]),
            ('yared', 'Yared Worku Tesfaye', 'EMP-00104', job_fin_dir, dept_cfo, ou_fa_dir, 'admin', grades[14], 155000, 4.5, '1984-11-05', '2018-01-10', [group_hr_user, group_att_user]),
            ('selam', 'Selamawit Gebre Egziabher', 'EMP-00105', job_rb_mgr, district_depts['East Addis Ababa District'], district_ous['East Addis Ababa District'], 'admin', grades[13], 140000, 4.4, '1988-03-30', '2019-02-01', [group_hr_user, group_att_user, group_job_pos] if group_job_pos else [group_hr_user]),

            # IT Team under Meron
            ('dawit', 'Dawit Alemu Fikre', 'EMP-00106', job_sr_dev, dept_ead_div, ou_ead_div, 'meron', grades[11], 85000, 4.3, '1990-07-14', '2020-05-01', [group_att_user]),
            ('hana', 'Hana Tadesse Bekele', 'EMP-00107', job_dev, dept_ead_div, ou_ead_div, 'dawit', grades[9], 60000, 3.9, '1993-12-01', '2021-08-15', [group_user]),
            ('abebe', 'Abebe Bikila Worku', 'EMP-00108', job_dev, dept_cbs_div, ou_cbs_div, 'dawit', grades[9], 62000, 4.1, '1992-05-10', '2021-02-01', [group_user]),
            ('chala', 'Chala Kebede Lema', 'EMP-00109', job_dba, dept_ead_div, ou_ead_div, 'meron', grades[10], 75000, 4.2, '1991-08-22', '2020-11-10', [group_user]),

            # HR Team under Solomon
            ('tadesse', 'Tadesse Kassahun Gebre', 'EMP-00110', job_rec_spec, dept_rec_div, ou_rec_div, 'solomon', grades[9], 65000, 4.4, '1992-02-18', '2020-09-01', [group_hr_user]),
            ('tigist', 'Tigist Assefa Mengistu', 'EMP-00111', job_hr_off, dept_er_div, ou_er_div, 'solomon', grades[8], 55000, 4.0, '1994-06-25', '2022-01-15', [group_hr_user]),
            ('senait', 'Senait Haile Wolde', 'EMP-00112', job_hr_off, dept_rec_div, ou_rec_div, 'tadesse', grades[8], 52000, 3.8, '1995-10-10', '2022-06-01', [group_user]),

            # Finance Team under Yared
            ('alemu', 'Alemu Desta Workneh', 'EMP-00113', job_accountant, dept_fa_dir, ou_fa_dir, 'yared', grades[10], 72000, 4.1, '1989-01-05', '2019-10-01', [group_user]),
            ('bekele', 'Bekele Shiferaw Ayana', 'EMP-00114', job_accountant, dept_fa_dir, ou_fa_dir, 'alemu', grades[10], 70000, 3.9, '1991-04-17', '2021-03-15', [group_user]),

            # Branch Staff under Selam & District Managers
            ('genet', 'Genet Zewde Tefera', 'EMP-00115', job_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'selam', grades[7], 45000, 4.2, '1996-08-12', '2022-09-01', [group_user]),
            ('mulu', 'Mulugeta Teshome Bedane', 'EMP-00116', job_cso, district_depts['East Addis Ababa District'], branch_ous['Bole Branch'], 'selam', grades[7], 46000, 4.0, '1995-11-20', '2022-04-10', [group_user]),
            ('kebede', 'Kebede Girma Feyissa', 'EMP-00117', job_rb_mgr, district_depts['West Addis Ababa District'], district_ous['West Addis Ababa District'], 'admin', grades[13], 135000, 4.3, '1987-07-07', '2018-11-01', [group_att_user]),
            ('leul', 'Leul Mekonnen Yohannes', 'EMP-00118', job_cso, district_depts['West Addis Ababa District'], branch_ous['Merkato Branch'], 'kebede', grades[7], 44000, 3.7, '1997-03-14', '2023-01-10', [group_user]),
            ('astewal', 'Astewal Getachew Nigusse', 'EMP-00119', job_cso, district_depts['West Addis Ababa District'], branch_ous['Mexico Branch'], 'kebede', grades[7], 45000, 4.1, '1996-05-22', '2022-11-01', [group_user]),
            ('girma', 'Girma Bogale Tadesse', 'EMP-00120', job_rb_mgr, district_depts['Hawassa District'], district_ous['Hawassa District'], 'admin', grades[13], 130000, 4.2, '1986-12-01', '2019-05-15', [group_att_user]),
            ('hiwot', 'Hiwot Mulugeta Alemu', 'EMP-00121', job_cso, district_depts['Hawassa District'], branch_ous['Hawassa Main Branch'], 'girma', grades[7], 43000, 4.0, '1997-09-09', '2023-02-01', [group_user]),
            ('feven', 'Feven Berhane Kidane', 'EMP-00122', job_cso, district_depts['Hawassa District'], branch_ous['Tabor Branch'], 'girma', grades[7], 42000, 3.8, '1998-01-30', '2023-05-10', [group_user]),
            ('mesfin', 'Mesfin Worku Tilahun', 'EMP-00123', job_rb_mgr, district_depts['Adama District'], district_ous['Adama District'], 'admin', grades[13], 132000, 4.4, '1987-10-10', '2019-01-15', [group_att_user]),
            ('yohannes', 'Yohannes Abebe Desta', 'EMP-00124', job_cso, district_depts['Adama District'], branch_ous['Adama Main Branch'], 'mesfin', grades[7], 44000, 4.1, '1996-02-14', '2022-10-01', [group_user]),
            ('bethel', 'Bethelhem Samuel Haile', 'EMP-00125', job_cso, district_depts['Adama District'], branch_ous['Geda Branch'], 'mesfin', grades[7], 43000, 3.9, '1997-06-18', '2023-03-01', [group_user]),
        ]

        created_employees = {}
        created_users = {}

        # Step A: Create or locate users & employees
        for login, name, emp_code, job, dept, ou, manager_login, grade, salary, pms, dob, hire_date, groups in employee_specs:
            user = env['res.users'].search([('login', '=', login)], limit=1)
            if not user:
                partner = partner_model.create({
                    'name': name,
                    'email': f"{login}@bunnabanksc.com",
                    'city': 'Addis Ababa',
                })
                u_vals = {
                    'name': name,
                    'login': login,
                    'password': 'password123',
                    'email': f"{login}@bunnabanksc.com",
                    'partner_id': partner.id,
                }
                user = user_model.create(u_vals)
                for g in groups:
                    if g:
                        g.sudo().write({'user_ids': [(4, user.id)]})
                print(f"  + Created User: {login}")
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
                'gender': 'male' if 'Alemu' in name or 'Solomon' in name or 'Yared' in name or 'Dawit' in name or 'Abebe' in name or 'Chala' in name or 'Tadesse' in name or 'Bekele' in name or 'Mulugeta' in name or 'Kebede' in name or 'Leul' in name or 'Girma' in name or 'Mesfin' in name or 'Yohannes' in name else 'female',
            }
            if 'job_grade' in emp_model._fields and grade:
                emp_vals['job_grade'] = grade.id
            if 'grade_id' in emp_model._fields and grade:
                emp_vals['grade_id'] = grade.id

            if not emp:
                emp = emp_model.create(emp_vals)
                print(f"  + Created Employee: {name} ({emp_code})")
            else:
                emp.write(emp_vals)

            created_employees[login] = emp

        # Assign Department Managers
        dept_ho.manager_id = created_employees['admin'].id
        dept_cpco.manager_id = created_employees['solomon'].id
        dept_cido.manager_id = created_employees['meron'].id
        dept_cfo.manager_id = created_employees['yared'].id
        district_depts['East Addis Ababa District'].manager_id = created_employees['selam'].id
        district_depts['West Addis Ababa District'].manager_id = created_employees['kebede'].id
        district_depts['Hawassa District'].manager_id = created_employees['girma'].id
        district_depts['Adama District'].manager_id = created_employees['mesfin'].id

        # Step B: Assign Manager (parent_id & coach_id) relationships
        print("\n--- Assigning Manager Hierarchy ---")
        for login, _, _, _, _, _, manager_login, _, _, _, _, _, _ in employee_specs:
            emp = created_employees[login]
            if manager_login and manager_login in created_employees:
                mgr_emp = created_employees[manager_login]
                emp.write({
                    'parent_id': mgr_emp.id,
                    'coach_id': mgr_emp.id,
                })

        # Fill missing fields for existing employees in DB that weren't in spec
        print("\n--- Updating Existing DB Employees with Default Hierarchy/OU ---")
        unassigned_emps = emp_model.search([('default_operating_unit_id', '=', False)])
        if unassigned_emps:
            unassigned_emps.write({'default_operating_unit_id': ou_ho.id, 'operating_unit_id': ou_ho.id})

        # -------------------------------------------------------------
        # 5. EMPLOYMENT VERSION (`hr.version`) RECORDS
        # -------------------------------------------------------------
        print("\n--- 5. Seeding Employment Version History (hr.version) ---")
        version_model = env['hr.version']

        for login, emp in created_employees.items():
            existing_ver = version_model.search([('employee_id', '=', emp.id)], limit=1)
            if not existing_ver:
                hire_date = emp.first_contract_date or date(2020, 1, 1)
                dt_from = datetime.combine(hire_date, datetime.min.time())
                dt_to = datetime.now()

                v_vals = {
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
                    'department_id': emp.department_id.id if emp.department_id else dept_ead_div.id,
                    'operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else ou_ho.id,
                    'job_id': emp.job_id.id if emp.job_id else job_dev.id,
                    'wage': emp.wage or 50000,
                    'pms_score': emp.pms_score or 4.0,
                    'is_current': True,
                }
                version_model.create(v_vals)
                print(f"  + Created Employment Version for {emp.name}")

        # -------------------------------------------------------------
        # 6. EDUCATIONAL BACKGROUND (`employee.education`) & EXPERIENCE
        # -------------------------------------------------------------
        print("\n--- 6. Seeding Educational & Experience Records ---")
        edu_model = env['employee.education']

        sample_schools = ['Addis Ababa University', 'Bahir Dar University', 'Hawassa University', 'Adama Science and Technology University', 'Haramaya University']
        sample_qualifications = ['B.Sc in Computer Science', 'M.Sc in Information Technology', 'BA in Business Administration', 'MBA in Management', 'B.Sc in Accounting & Finance']

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
        # 7. ATTENDANCE & PREDEFINED ATTENDANCE RECORDS
        # -------------------------------------------------------------
        print("\n--- 7. Seeding Attendance & Overtime Records ---")
        att_model = env['hr.attendance'].with_context(skip_duplicate_check=True)
        pre_model = env['attendance.preapproval']
        ot_model = env['over.time']

        today = date.today()
        # Seed attendance for past 10 working days
        for days_back in range(1, 11):
            check_date = today - timedelta(days=days_back)
            if check_date.weekday() >= 5:  # Skip weekends
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

        # Predefined attendance exception (preapproval)
        sample_emp = created_employees['dawit']
        existing_pre = pre_model.search([('employee_id', '=', sample_emp.id)], limit=1)
        if not existing_pre:
            pre_model.create({
                'employee_id': sample_emp.id,
                'exception_type': 'predefined_late',
                'approval_reason': 'Morning medical checkup pre-approved',
                'date': today + timedelta(days=2),
                'start_time': 8.0,
                'end_time': 10.0,
                'state': 'approved',
                'approved_by': admin_id,
            })
            print("  + Created Predefined Attendance Preapproval record")

        # Overtime record
        existing_ot = ot_model.search([('employee_id', '=', sample_emp.id)], limit=1)
        if not existing_ot:
            ot_model.create({
                'employee_id': sample_emp.id,
                'date': today + timedelta(days=1),
                'start_time': 17.5,
                'end_time': 20.5,
                'compensation_type': 'compensatory_day',
                'over_time_reason': 'Core banking system deployment and testing',
            })
            print("  + Created Overtime Record")

        # -------------------------------------------------------------
        # 8. DISCIPLINE MANAGEMENT DEMO DATA
        # -------------------------------------------------------------
        print("\n--- 8. Seeding Discipline Offenses & Cases ---")
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
            print("  + Created Discipline Case DISC-2026-001 for Hana Tadesse")

        # -------------------------------------------------------------
        # 9. RECRUITMENT PREREQUISITES & APPLICANTS
        # -------------------------------------------------------------
        print("\n--- 9. Seeding Recruitment Candidates & Applicant Prerequisites ---")
        applicant_model = env['hr.applicant']
        stage_model = env['hr.recruitment.stage']

        initial_stage = stage_model.search([], limit=1)

        applicants_data = [
            ('Abebech Tadesse', 'abebech.candidate@gmail.com', '+251911223344', job_dev, 'B.Sc Computer Science', 3.7, 4),
            ('Kassahun Wolde', 'kassahun.candidate@gmail.com', '+251922334455', job_accountant, 'BA Accounting', 3.8, 5),
            ('Yirgalem Haile', 'yirgalem.candidate@gmail.com', '+251933445566', job_cso, 'BA Economics', 3.5, 2),
        ]

        for p_name, p_email, p_phone, job_pos, qual, gpa, exp_yrs in applicants_data:
            app = applicant_model.search([('partner_name', '=', p_name)], limit=1)
            if not app:
                app_vals = {
                    'partner_name': p_name,
                    'email_from': p_email,
                    'partner_phone': p_phone,
                    'job_id': job_pos.id,
                    'department_id': job_pos.department_id.id if job_pos.department_id else dept_ead_div.id,
                    'salary_expected': 65000,
                    'salary_proposed': 60000,
                }
                if initial_stage:
                    app_vals['stage_id'] = initial_stage.id
                applicant_model.create(app_vals)
                print(f"  + Created Recruitment Applicant: {p_name}")

        cr.commit()
        print("\n=================================================================")
        print("✅ DEMO DATA SEEDING COMPLETED SUCCESSFULLY WITH ALL RELATIONSHIPS!")
        print("=================================================================")

if __name__ == '__main__':
    run_seed()
