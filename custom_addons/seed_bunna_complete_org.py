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
    print("🚀 STARTING COMPLETE BUNNA BANK S.C. ORG STRUCTURE & DATA SEEDING")
    print("=================================================================")

    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        company = env['res.company'].search([], limit=1)

        # -------------------------------------------------------------
        # 1. PURGE OLD/STALE DATA FOR CLEAN SEEDING
        # -------------------------------------------------------------
        print("\n--- 1. Purging Database for Clean Seeding ---")
        
        # Unlink all attendance, overtime, preapprovals, discipline cases, versions, educations via SQL
        cr.execute("DELETE FROM employee_transfer_request")
        cr.execute("DELETE FROM discipline_appeal")
        cr.execute("DELETE FROM discipline_committee_vote")
        cr.execute("DELETE FROM discipline_committee_meeting")
        cr.execute("DELETE FROM discipline_investigation_liable")
        cr.execute("DELETE FROM discipline_investigation")
        cr.execute("DELETE FROM discipline_payroll_penalty")
        cr.execute("DELETE FROM discipline_suspension")
        cr.execute("DELETE FROM discipline_case")
        cr.execute("DELETE FROM hr_attendance")
        cr.execute("DELETE FROM over_time")
        cr.execute("DELETE FROM attendance_preapproval")
        cr.execute("DELETE FROM hr_version")
        cr.execute("DELETE FROM employee_education")
        cr.execute("DELETE FROM hr_applicant")

        # Keep admin user
        admin_user = env.ref('base.user_admin')
        admin_id = admin_user.id

        # Fast cleanup via SQL
        cr.execute("DELETE FROM hr_employee WHERE user_id NOT IN (1, 2, 3, 4)")
        cr.execute("DELETE FROM res_users WHERE id NOT IN (1, 2, 3, 4)")
        cr.execute("DELETE FROM hr_department WHERE name::text NOT LIKE '%Head Office%' AND name::text NOT LIKE '%District%'")

        # -------------------------------------------------------------
        # 2. OPERATING UNITS HIERARCHY (`operating.unit`)
        # -------------------------------------------------------------
        print("\n--- 2. Seeding Operating Units Hierarchy ---")
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

        # 2.1 Head Office Root OU
        ou_ho = get_or_create_ou('Head Office', 'head_office', sol_id=1001)

        # 2.2 Chief Offices OUs
        ou_cido = get_or_create_ou('Chief Information and Digital Office', 'head_office', parent_unit=ou_ho, sol_id=1002)
        ou_cpco = get_or_create_ou('Chief People and Culture Office', 'head_office', parent_unit=ou_ho, sol_id=1003)
        ou_cfo  = get_or_create_ou('Chief Financial Office', 'head_office', parent_unit=ou_ho, sol_id=1004)
        ou_crpo = get_or_create_ou('Chief Retail and Portfolio Office', 'head_office', parent_unit=ou_ho, sol_id=1005)

        # 2.3 Directorates OUs
        ou_eado_dir = get_or_create_ou('Enterprise Application Development and Operation Directorate', 'head_office', parent_unit=ou_cido, sol_id=1011)
        ou_pom_dir  = get_or_create_ou('People Operations Management Directorate', 'head_office', parent_unit=ou_cpco, sol_id=1012)
        ou_fa_dir   = get_or_create_ou('Financial Accounting Directorate', 'head_office', parent_unit=ou_cfo, sol_id=1013)
        ou_rb_dir   = get_or_create_ou('Retail Banking Directorate', 'head_office', parent_unit=ou_crpo, sol_id=1014)

        # 2.4 Divisions OUs
        ou_ead_div = get_or_create_ou('Enterprise Application Development Division', 'head_office', parent_unit=ou_eado_dir, sol_id=1021)
        ou_cbs_div = get_or_create_ou('Core Banking Support Division', 'head_office', parent_unit=ou_eado_dir, sol_id=1022)
        ou_rec_div = get_or_create_ou('Onboarding and Recruitment Division', 'head_office', parent_unit=ou_pom_dir, sol_id=1023)
        ou_er_div  = get_or_create_ou('Employee Relations Division', 'head_office', parent_unit=ou_pom_dir, sol_id=1024)

        # 2.5 Districts & Branch Operating Units
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
            dist_ou = get_or_create_ou(dist_name, 'district_office', parent_unit=ou_crpo, district=dist_name, sol_id=sol_counter)
            district_ous[dist_name] = dist_ou
            for b_name in branches:
                sol_counter += 1
                b_ou = get_or_create_ou(b_name, 'branch', parent_unit=dist_ou, district=dist_name, sol_id=sol_counter)
                branch_ous[b_name] = b_ou

        # -------------------------------------------------------------
        # 3. DEPARTMENTS HIERARCHY (`hr.department`)
        # -------------------------------------------------------------
        print("\n--- 3. Seeding Departments Hierarchy ---")
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
                if parent_dept and d.parent_id != parent_dept:
                    vals['parent_id'] = parent_dept.id
                if vals:
                    d.write(vals)
            return d

        # Root Head Office Department
        dept_ho = get_or_create_dept('Head Office', ou_ho)
        dept_ho.write({'parent_id': False})

        # 12 District Departments in `hr.department` matching Screenshot (Top Level parent_id=False)
        district_depts = {}
        for dist_name, branches in districts_spec:
            dist_ou = district_ous[dist_name]
            dept_name = f"{dist_name} Office" if not dist_name.endswith('Office') else dist_name
            dist_d = get_or_create_dept(dept_name, dist_ou, parent_dept=None)
            dist_d.write({'parent_id': False})
            district_depts[dist_name] = dist_d

        # -------------------------------------------------------------
        # 4. JOB GRADES & JOB POSITIONS (`employee.grade` & `hr.job`)
        # -------------------------------------------------------------
        print("\n--- 4. Seeding Job Grades & Job Positions ---")
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
                print(f"  + Created Job Position: {name}")
            else:
                j.write({'department_id': dept.id})
            return j

        # Executive Jobs (all in Head Office department)
        job_ceo       = get_or_create_job('Chief Executive Officer', dept_ho, grades[16])
        job_cido      = get_or_create_job('Chief Information and Digital Officer', dept_ho, grades[15])
        job_cpco      = get_or_create_job('Chief People and Culture Officer', dept_ho, grades[15])
        job_cfo       = get_or_create_job('Chief Financial Officer', dept_ho, grades[15])
        job_crpo      = get_or_create_job('Chief Retail and Portfolio Officer', dept_ho, grades[15])

        # Directorate & Division Managers (all in Head Office department)
        job_eado_dir  = get_or_create_job('Enterprise Application Development and Operation Director', dept_ho, grades[14])
        job_ead_div_m = get_or_create_job('Enterprise Application Development Division Manager', dept_ho, grades[13])
        job_pom_dir   = get_or_create_job('People Operations Management Director', dept_ho, grades[14])
        job_fa_dir    = get_or_create_job('Financial Accounting Director', dept_ho, grades[14])
        job_dist_dir  = get_or_create_job('District Director', dept_ho, grades[14])
        job_bm        = get_or_create_job('Branch Manager', district_depts['East Addis Ababa District'], grades[12])

        # IT Job Positions (Head Office department)
        job_prin_dev = get_or_create_job('Principal Enterprise Application Developer', dept_ho, grades[12])
        job_sr_dev   = get_or_create_job('Senior Enterprise Application Developer', dept_ho, grades[11])
        job_dev_off  = get_or_create_job('Enterprise Application Development Officer', dept_ho, grades[9])
        job_jr_dev   = get_or_create_job('Junior Enterprise Application Developer', dept_ho, grades[7])

        # HR Job Positions (Head Office department)
        job_sr_rec   = get_or_create_job('Senior Recruitment Specialist', dept_ho, grades[11])
        job_rec_spec = get_or_create_job('Recruitment Specialist', dept_ho, grades[9])
        job_hr_off   = get_or_create_job('HR Officer', dept_ho, grades[8])
        job_jr_hr    = get_or_create_job('Junior HR Officer', dept_ho, grades[7])

        # Finance Job Positions (Head Office department)
        job_prin_acc = get_or_create_job('Principal Accountant', dept_ho, grades[12])
        job_sr_acc   = get_or_create_job('Senior Accountant', dept_ho, grades[10])
        job_acc      = get_or_create_job('Accountant', dept_ho, grades[8])
        job_jr_acc   = get_or_create_job('Junior Accountant', dept_ho, grades[7])

        # Retail / Branch Job Positions
        job_sr_cso   = get_or_create_job('Senior Customer Service Officer', district_depts['East Addis Ababa District'], grades[9])
        job_cso      = get_or_create_job('Customer Service Officer', district_depts['East Addis Ababa District'], grades[7])
        job_jr_cso   = get_or_create_job('Junior Customer Service Officer', district_depts['East Addis Ababa District'], grades[6])

        # -------------------------------------------------------------
        # 5. EMPLOYEES & USERS DATASET (Structured Per User Specification)
        # -------------------------------------------------------------
        print("\n--- 5. Seeding Structured Employee & User Records ---")
        emp_model = env['hr.employee']
        user_model = env['res.users'].with_context(no_reset_password=True, mail_create_nolog=True)
        partner_model = env['res.partner']

        group_user = env.ref('base.group_user')
        group_att_user = env.ref('hr_attendance.group_hr_attendance_user')
        group_att_admin = env.ref('hr_attendance.group_hr_attendance_manager')
        group_hr_user = env.ref('hr.group_hr_user')
        group_hr_manager = env.ref('hr.group_hr_manager')

        # Employee Specification Array
        employee_specs = [
            # Top Executive & IT Line (User Specified Names - Department: Head Office)
            ('mulugeta_ceo', 'Mulugeta Alemayehu Awoke', 'EMP-00101', job_ceo, dept_ho, ou_ho, None, grades[16], 230000, 4.9, '1978-05-12', '2015-01-01', [group_hr_manager, group_att_admin]),
            ('yeshanew', 'Yeshanew Ayalew Shibeshi', 'EMP-00102', job_cido, dept_ho, ou_cido, 'mulugeta_ceo', grades[15], 180000, 4.8, '1982-08-20', '2016-03-15', [group_hr_manager, group_att_user]),
            ('derese', 'Derese Wudu Mekonnen', 'EMP-00103', job_eado_dir, dept_ho, ou_eado_dir, 'yeshanew', grades[14], 150000, 4.7, '1985-02-10', '2017-06-01', [group_hr_user, group_att_user]),
            ('eyob_div', 'Eyob Shewangzaw Bogale', 'EMP-00104', job_ead_div_m, dept_ho, ou_ead_div, 'derese', grades[13], 130000, 4.6, '1987-11-25', '2018-09-10', [group_hr_user, group_att_user]),

            # IT Developers under Eyob Shewangzaw Bogale (Division Manager)
            # All Officers, Senior, Principal report directly to Division Manager Eyob
            ('dawit', 'Dawit Alemu Fikre', 'EMP-00105', job_prin_dev, dept_ho, ou_ead_div, 'eyob_div', grades[12], 95000, 4.4, '1990-07-14', '2019-05-01', [group_att_user]),
            ('samuel', 'Samuel Bekele ForcedCO', 'EMP-00106', job_prin_dev, dept_ho, ou_ead_div, 'eyob_div', grades[12], 93000, 4.3, '1991-03-22', '2019-11-15', [group_user]),
            ('meron', 'Meron Hailemariam Tadesse', 'EMP-00107', job_sr_dev, dept_ho, ou_ead_div, 'eyob_div', grades[11], 82000, 4.2, '1992-09-20', '2020-02-01', [group_user]),
            ('surafel', 'Surafel Girma Belay', 'EMP-00108', job_sr_dev, dept_ho, ou_ead_div, 'eyob_div', grades[11], 80000, 4.1, '1993-04-10', '2020-08-15', [group_user]),
            ('abebe', 'Abebe Bikila Worku', 'EMP-00109', job_dev_off, dept_ho, ou_ead_div, 'eyob_div', grades[9], 65000, 4.0, '1994-05-10', '2021-01-10', [group_user]),
            ('hana', 'Hana Tadesse Bekele', 'EMP-00110', job_dev_off, dept_ho, ou_ead_div, 'eyob_div', grades[9], 63000, 3.9, '1995-12-01', '2021-06-01', [group_user]),
            ('marta', 'Marta Yosef Kebede', 'EMP-00111', job_jr_dev, dept_ho, ou_ead_div, 'eyob_div', grades[7], 48000, 3.8, '1997-01-20', '2022-03-15', [group_user]),
            ('chala', 'Chala Kebede Lema', 'EMP-00112', job_jr_dev, dept_ho, ou_ead_div, 'eyob_div', grades[7], 46000, 3.7, '1998-08-22', '2022-09-01', [group_user]),

            # HR Line (Solomon Kassa Desta & Tadesse Kassahun Gebre - POM Director / Manager)
            ('solomon', 'Solomon Kassa Desta', 'EMP-00113', job_cpco, dept_ho, ou_cpco, 'mulugeta_ceo', grades[15], 175000, 4.7, '1983-04-12', '2016-05-01', [group_hr_manager, group_att_user]),
            ('tadesse', 'Tadesse Kassahun Gebre', 'EMP-00114', job_pom_dir, dept_ho, ou_pom_dir, 'solomon', grades[14], 145000, 4.5, '1986-02-18', '2017-10-15', [group_hr_manager]),

            # HR Positions under Tadesse Kassahun Gebre
            ('senait', 'Senait Haile Wolde', 'EMP-00115', job_sr_rec, dept_ho, ou_rec_div, 'tadesse', grades[11], 78000, 4.3, '1991-10-10', '2019-04-01', [group_hr_user]),
            ('tigist', 'Tigist Assefa Mengistu', 'EMP-00116', job_sr_rec, dept_ho, ou_rec_div, 'tadesse', grades[11], 76000, 4.2, '1992-06-25', '2019-09-15', [group_hr_user]),
            ('eden', 'Eden Bogale Workneh', 'EMP-00117', job_rec_spec, dept_ho, ou_rec_div, 'tadesse', grades[9], 62000, 4.0, '1994-05-12', '2021-02-01', [group_user]),
            ('rahel', 'Rahel Solomon Tessema', 'EMP-00118', job_rec_spec, dept_ho, ou_rec_div, 'tadesse', grades[9], 60000, 3.9, '1995-01-11', '2021-07-15', [group_user]),
            ('biniam', 'Biniam Million Hailu', 'EMP-00119', job_hr_off, dept_ho, ou_er_div, 'tadesse', grades[8], 54000, 4.1, '1993-09-09', '2020-03-01', [group_user]),
            ('tariku', 'Tariku Abera Demissie', 'EMP-00120', job_hr_off, dept_ho, ou_er_div, 'tadesse', grades[8], 52000, 3.8, '1994-11-15', '2020-11-10', [group_user]),

            # Finance Line (Yared Worku Tesfaye & Alemu Desta Workneh - FA Director / Manager)
            ('yared', 'Yared Worku Tesfaye', 'EMP-00121', job_cfo, dept_ho, ou_cfo, 'mulugeta_ceo', grades[15], 180000, 4.8, '1984-11-05', '2016-02-01', [group_hr_user, group_att_user]),
            ('alemu', 'Alemu Desta Workneh', 'EMP-00122', job_fa_dir, dept_ho, ou_fa_dir, 'yared', grades[14], 148000, 4.6, '1987-01-05', '2017-08-01', [group_hr_user]),

            # Finance Positions under Alemu Desta Workneh
            ('bekele', 'Bekele Shiferaw Ayana', 'EMP-00123', job_prin_acc, dept_ho, ou_fa_dir, 'alemu', grades[12], 90000, 4.3, '1989-04-17', '2018-12-01', [group_user]),
            ('eyob_acc', 'Eyob Tekle Berhan', 'EMP-00124', job_prin_acc, dept_ho, ou_fa_dir, 'alemu', grades[12], 88000, 4.2, '1990-03-11', '2019-05-15', [group_user]),
            ('alemu_sr', 'Alemu Worku Tadesse', 'EMP-00125', job_sr_acc, dept_ho, ou_fa_dir, 'alemu', grades[10], 72000, 4.1, '1992-06-01', '2020-04-10', [group_user]),
            ('bekele_sr', 'Bekele Kassahun Desta', 'EMP-00126', job_sr_acc, dept_ho, ou_fa_dir, 'alemu', grades[10], 70000, 4.0, '1993-02-15', '2020-10-01', [group_user]),

            # Retail Banking & District Directors Line
            ('selam', 'Selamawit Gebre Egziabher', 'EMP-00127', job_crpo, dept_ho, ou_crpo, 'mulugeta_ceo', grades[15], 175000, 4.7, '1985-03-30', '2016-04-01', [group_hr_user, group_att_user]),
            
            # District Directors (under Selamawit Gebre Egziabher)
            ('kebede', 'Kebede Girma Feyissa', 'EMP-00128', job_dist_dir, district_depts['East Addis Ababa District'], district_ous['East Addis Ababa District'], 'selam', grades[14], 140000, 4.5, '1986-07-07', '2017-09-01', [group_att_user]),
            ('girma', 'Girma Bogale Tadesse', 'EMP-00129', job_dist_dir, district_depts['West Addis Ababa District'], district_ous['West Addis Ababa District'], 'selam', grades[14], 138000, 4.4, '1987-12-01', '2018-01-15', [group_att_user]),
            ('mesfin', 'Mesfin Worku Tilahun', 'EMP-00130', job_dist_dir, district_depts['Hawassa District'], district_ous['Hawassa District'], 'selam', grades[14], 136000, 4.4, '1988-10-10', '2018-06-01', [group_att_user]),
            ('yohannes', 'Yohannes Abebe Desta', 'EMP-00131', job_dist_dir, district_depts['Adama District'], district_ous['Adama District'], 'selam', grades[14], 135000, 4.3, '1989-02-14', '2018-11-10', [group_att_user]),

            # Arat Kilo Branch under East Addis Ababa District
            # All Branch Staff report directly to Branch Manager Astewal Getachew Nigusse
            ('astewal', 'Astewal Getachew Nigusse', 'EMP-00132', job_bm, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'kebede', grades[12], 92000, 4.3, '1990-05-22', '2019-07-01', [group_user]),
            ('genet', 'Genet Zewde Tefera', 'EMP-00133', job_sr_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[9], 64000, 4.2, '1993-08-12', '2020-09-01', [group_user]),
            ('mulu', 'Mulugeta Teshome Bedane', 'EMP-00134', job_sr_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[9], 62000, 4.1, '1994-11-20', '2021-02-15', [group_user]),
            ('feven', 'Feven Berhane Kidane', 'EMP-00135', job_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[7], 46000, 4.0, '1996-01-30', '2022-04-01', [group_user]),
            ('hiwot', 'Hiwot Mulugeta Alemu', 'EMP-00136', job_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[7], 45000, 3.9, '1996-09-09', '2022-08-10', [group_user]),
            ('leul', 'Leul Mekonnen Yohannes', 'EMP-00137', job_jr_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[6], 38000, 3.8, '1998-03-14', '2023-01-10', [group_user]),
            ('bethel', 'Bethelhem Samuel Haile', 'EMP-00138', job_jr_cso, district_depts['East Addis Ababa District'], branch_ous['Arat Kilo Branch'], 'astewal', grades[6], 37000, 3.7, '1998-06-18', '2023-05-01', [group_user]),
        ]

        created_employees = {}
        created_users = {}

        # Step A: Create User & Employee Records
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
                'job_grade': grade.id if grade else grades[8].id,
            }
            if emp:
                emp.write(emp_vals)
            else:
                emp = emp_model.create(emp_vals)

            created_employees[login] = emp
            print(f"  + Configured Employee: {name} ({emp_code})")

        # Assign Department Managers
        dept_ho.manager_id = created_employees['mulugeta_ceo'].id
        district_depts['East Addis Ababa District'].manager_id = created_employees['kebede'].id
        district_depts['West Addis Ababa District'].manager_id = created_employees['girma'].id
        district_depts['Hawassa District'].manager_id = created_employees['mesfin'].id
        district_depts['Adama District'].manager_id = created_employees['yohannes'].id

        # Step B: Assign Manager (parent_id & coach_id) hierarchy
        print("\n--- Assigning Manager Hierarchy Tree ---")
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
        print("\n--- 6. Seeding Employment Version History (hr.version) ---")
        version_model = env['hr.version']

        for login, emp in created_employees.items():
            hire_date = emp.first_contract_date or date(2020, 1, 1)
            dt_from = datetime.combine(hire_date, datetime.min.time())
            dt_to = datetime.now()

            version_vals = {
                'name': f"Initial Contract Version - {emp.name}",
                'employee_id': emp.id,
                'date_version': hire_date,
                'date_generated_from': dt_from,
                'date_generated_to': dt_to,
                'last_modified_date': dt_to,
                'last_modified_uid': admin_id,
                'hr_responsible_id': admin_id,
                'distance_home_work_unit': 'kilometers',
                'employee_type': 'employee',
                'marital': 'married' if random.choice([True, False]) else 'single',
                'job_grade': emp.job_grade.id if emp.job_grade else grades[8].id,
                'work_entry_source': 'calendar',
                'department_id': emp.department_id.id,
                'operating_unit_id': emp.default_operating_unit_id.id,
                'job_id': emp.job_id.id,
                'wage': emp.wage or 50000,
                'pms_score': emp.pms_score or 4.0,
                'is_current': True,
                'state': 'open',
                'kanban_state': 'done',
            }

            existing_versions = version_model.search([('employee_id', '=', emp.id)])
            if existing_versions:
                existing_versions[0].write(version_vals)
                if len(existing_versions) > 1:
                    existing_versions[1:].unlink()
            else:
                version_model.create(version_vals)
            print(f"  + Configured hr.version for {emp.name}")

        # -------------------------------------------------------------
        # 7. EDUCATIONAL & EXPERIENCE RECORDS
        # -------------------------------------------------------------
        print("\n--- 7. Seeding Educational Records ---")
        edu_model = env['employee.education']
        sample_schools = ['Addis Ababa University', 'Bahir Dar University', 'Hawassa University', 'Adama Science and Technology University']
        sample_qualifications = ['B.Sc in Computer Science', 'M.Sc in Information Technology', 'BA in Business Administration', 'B.Sc in Accounting & Finance']

        for login, emp in created_employees.items():
            if not edu_model.search([('employee_id', '=', emp.id)], limit=1):
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
        # 8. COMPLETE ATTENDANCE MODULE DEMO DATASET
        # -------------------------------------------------------------
        print("\n--- 8. Seeding Complete Attendance Module Demo Dataset ---")

        # A. Job Shifts (job.shift)
        shift_model = env['job.shift']
        shift_morning = shift_model.search([('code', '=', 'SHIFT-01')], limit=1)
        if not shift_morning:
            shift_morning = shift_model.create({
                'name': 'Morning Regular Shift',
                'code': 'SHIFT-01',
                'start_time': 8.0,
                'end_time': 17.0,
                'is_night_shift': False,
            })
        shift_night = shift_model.search([('code', '=', 'SHIFT-02')], limit=1)
        if not shift_night:
            shift_night = shift_model.create({
                'name': 'Night Operations Shift',
                'code': 'SHIFT-02',
                'start_time': 17.0,
                'end_time': 1.0,
                'is_night_shift': True,
            })
        shift_flex = shift_model.search([('code', '=', 'SHIFT-03')], limit=1)
        if not shift_flex:
            shift_flex = shift_model.create({
                'name': 'Flexible IT Shift',
                'code': 'SHIFT-03',
                'start_time': 9.0,
                'end_time': 18.0,
                'is_night_shift': False,
            })

        # B. Job Position Exceptions (job.position.exception)
        pos_exc_model = env['job.position.exception']
        abebe_emp = created_employees['abebe']
        if not pos_exc_model.search([('employee_id', '=', abebe_emp.id)], limit=1):
            pos_exc_model.create({
                'employee_id': abebe_emp.id,
                'shift_id': shift_flex.id,
                'status': 'active',
                'notify_status': 'notified',
            })
        genet_emp = created_employees['genet']
        if not pos_exc_model.search([('employee_id', '=', genet_emp.id)], limit=1):
            pos_exc_model.create({
                'employee_id': genet_emp.id,
                'shift_id': shift_night.id,
                'status': 'active',
                'notify_status': 'notified',
            })

        # C. Location Based Exceptions (location.based.exception)
        loc_exc_model = env['location.based.exception']
        arat_kilo_ou = branch_ous['Arat Kilo Branch']
        if not loc_exc_model.search([('operating_unit', '=', arat_kilo_ou.id)], limit=1):
            loc_exc_model.create({
                'operating_unit': arat_kilo_ou.id,
                'start_time': 7.5,
                'end_time': 11.5,
            })

        # D. Attendance Reasons (hr.attendance.reason)
        reason_model = env['hr.attendance.reason']
        r1 = reason_model.search([('code', '=', 'REASON-01')], limit=1)
        if not r1:
            r1 = reason_model.create({'name': 'Official Field Assignment', 'code': 'REASON-01', 'action_type': 'both', 'show_on_attendance_screen': True})
        else:
            r1.write({'action_type': 'both'})

        r2 = reason_model.search([('code', '=', 'REASON-02')], limit=1)
        if not r2:
            r2 = reason_model.create({'name': 'Traffic / Transit Delay', 'code': 'REASON-02', 'action_type': 'both', 'show_on_attendance_screen': True})
        else:
            r2.write({'action_type': 'both'})

        r3 = reason_model.search([('code', '=', 'REASON-03')], limit=1)
        if not r3:
            r3 = reason_model.create({'name': 'Medical Emergency / Health Check', 'code': 'REASON-03', 'action_type': 'both', 'show_on_attendance_screen': True})
        else:
            r3.write({'action_type': 'both'})

        # E. Attendance Pre-approvals (attendance.preapproval)
        pre_model = env['attendance.preapproval']
        today = date.today()
        tomorrow = today + timedelta(days=1)
        
        hana_emp = created_employees['hana']
        eyob_user = created_users['eyob_div']
        if not pre_model.search([('employee_id', '=', hana_emp.id)], limit=1):
            pre_model.create({
                'employee_id': hana_emp.id,
                'exception_type': 'predefined_late',
                'approval_reason': 'Attending morning banking systems integration workshop at NBE.',
                'date': tomorrow,
                'start_time': 8.5,
                'end_time': 10.5,
                'state': 'approved',
                'approved_by': eyob_user.id,
            })

        marta_emp = created_employees['marta']
        if not pre_model.search([('employee_id', '=', marta_emp.id)], limit=1):
            pre_model.create({
                'employee_id': marta_emp.id,
                'exception_type': 'predefined_early_exit',
                'approval_reason': 'Scheduled university exam in the afternoon.',
                'date': tomorrow,
                'start_time': 15.0,
                'end_time': 17.0,
                'state': 'requested',
            })

        # F. Overtime Requests (over.time)
        ot_model = env['over.time']
        dawit_emp = created_employees['dawit']
        if not ot_model.search([('employee_id', '=', dawit_emp.id)], limit=1):
            ot_model.create({
                'employee_id': dawit_emp.id,
                'date': tomorrow,
                'start_time': 17.5,
                'end_time': 20.5,
                'compensation_type': 'compensatory_day',
                'over_time_reason': 'Emergency Core Banking API Patching & Maintenance',
            })

        feven_emp = created_employees['feven']
        if not ot_model.search([('employee_id', '=', feven_emp.id)], limit=1):
            ot_model.create({
                'employee_id': feven_emp.id,
                'date': tomorrow,
                'start_time': 17.0,
                'end_time': 19.0,
                'compensation_type': 'compensatory_day',
                'over_time_reason': 'End-of-month branch audit preparation',
            })

        # G. Attendance Records (hr.attendance) with various statuses
        att_model = env['hr.attendance'].with_context(skip_duplicate_check=True)
        samuel_emp = created_employees['samuel']
        surafel_emp = created_employees['surafel']
        meron_emp = created_employees['meron']
        chala_emp = created_employees['chala']

        # Historical attendance records (1 to 5 days back)
        for d_back in range(1, 6):
            c_date = today - timedelta(days=d_back)
            if c_date.weekday() >= 5:
                continue

            dt_in = datetime.combine(c_date, datetime.min.time()) + timedelta(hours=8)
            dt_out = datetime.combine(c_date, datetime.min.time()) + timedelta(hours=17)

            # Dawit: On-time attendance
            if not att_model.search([('employee_id', '=', dawit_emp.id), ('check_in', '>=', c_date)], limit=1):
                att_model.create({
                    'employee_id': dawit_emp.id,
                    'check_in': dt_in,
                    'check_out': dt_out,
                    'check_in_status': 'Normal',
                })

            # Samuel: Late check-in (unacknowledged - ready for manager Eyob to test acknowledgement)
            if not att_model.search([('employee_id', '=', samuel_emp.id), ('check_in', '>=', c_date)], limit=1):
                att_model.create({
                    'employee_id': samuel_emp.id,
                    'check_in': dt_in + timedelta(minutes=45),
                    'check_out': dt_out,
                    'check_in_status': 'Late',
                    'late_time_hour': 0.75,
                    'is_acknowledged': False,
                })

            # Surafel: Late check-in (Manager Acknowledged)
            if not att_model.search([('employee_id', '=', surafel_emp.id), ('check_in', '>=', c_date)], limit=1):
                att_model.create({
                    'employee_id': surafel_emp.id,
                    'check_in': dt_in + timedelta(minutes=30),
                    'check_out': dt_out,
                    'check_in_status': 'Late',
                    'late_time_hour': 0.5,
                    'is_acknowledged': True,
                    'acknowledged_by': eyob_user.id,
                    'acknowledged_date': datetime.now(),
                    'acknowledged_late': 0.5,
                    'attendance_reason_ids': [(4, r2.id)],
                })

            # Meron: Early Exit
            if not att_model.search([('employee_id', '=', meron_emp.id), ('check_in', '>=', c_date)], limit=1):
                att_model.create({
                    'employee_id': meron_emp.id,
                    'check_in': dt_in,
                    'check_out': dt_out - timedelta(hours=1, minutes=30),
                    'check_out_status': 'Early Exit',
                    'early_exit_hour': 1.5,
                })

            # Chala: Flagged for Discipline Review
            if not att_model.search([('employee_id', '=', chala_emp.id), ('check_in', '>=', c_date)], limit=1):
                tadesse_user = created_users['tadesse']
                att_model.create({
                    'employee_id': chala_emp.id,
                    'check_in': dt_in + timedelta(hours=1, minutes=30),
                    'check_out': dt_out - timedelta(hours=2),
                    'check_in_status': 'Late',
                    'check_out_status': 'Early Exit',
                    'late_time_hour': 1.5,
                    'early_exit_hour': 2.0,
                    'flagged_for_discipline': True,
                    'flagged_reason': 'Unexcused 1.5h late check-in and 2h early departure.',
                    'flagged_by_id': tadesse_user.id,
                    'flagged_date': datetime.now(),
                })

            # Abebe: Overtime Approved for Payroll
            if not att_model.search([('employee_id', '=', abebe_emp.id), ('check_in', '>=', c_date)], limit=1):
                att_model.create({
                    'employee_id': abebe_emp.id,
                    'check_in': dt_in,
                    'check_out': dt_out + timedelta(hours=3),
                    'over_time_hour': 3.0,
                    'overtime_approved_for_payroll': True,
                })

        # -------------------------------------------------------------
        # 9. DISCIPLINE & RECRUITMENT DEMO DATA
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
        if not case_model.search([('employee_id', '=', disc_emp.id)], limit=1):
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
            ('Abebech Tadesse', 'abebech.candidate@gmail.com', '+251911223344', job_sr_dev),
            ('Kassahun Wolde', 'kassahun.candidate@gmail.com', '+251922334455', job_prin_acc),
            ('Yirgalem Haile', 'yirgalem.candidate@gmail.com', '+251933445566', job_cso),
        ]

        for p_name, p_email, p_phone, job_pos in applicants_data:
            if not applicant_model.search([('email_from', '=', p_email)], limit=1):
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

        final_emp_count = env['hr.employee'].search_count([])
        final_ver_count = env['hr.version'].search_count([])
        print("\n=================================================================")
        print(f"✅ COMPLETE ORG DATASET SEEDED SUCCESSFULLY!")
        print(f"   - Total Employees: {final_emp_count}")
        print(f"   - Total hr.version Records: {final_ver_count}")
        print("=================================================================")

if __name__ == '__main__':
    run_seed()
