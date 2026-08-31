# -*- coding: utf-8 -*-
import csv
import os
import re
import datetime
import logging
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

CSV_DIR = '/mnt/extra-addons/seed_data_csv'

def clean_str(val):
    if not val or val == 'NULL' or val == 'None':
        return False
    val = val.strip()
    return val if val else False

def parse_date(val):
    val = clean_str(val)
    if not val:
        return False
    # Take YYYY-MM-DD portion
    val = val.split(' ')[0].split('T')[0]
    try:
        datetime.datetime.strptime(val, '%Y-%m-%d')
        return val
    except Exception:
        return False

def parse_float(val, default=0.0):
    val = clean_str(val)
    if not val:
        return default
    try:
        return float(val)
    except Exception:
        return default

def parse_bool(val):
    val = clean_str(val)
    if not val:
        return False
    return val.lower() in ('true', 't', '1', 'yes')

def generate_username(full_name, father_name_input, existing_logins):
    full_name = clean_str(full_name) or "user"
    parts = [p.lower() for p in re.findall(r'[a-zA-Z0-9]+', full_name)]
    
    first = parts[0] if parts else "user"
    
    father_clean = clean_str(father_name_input)
    if father_clean:
        f_parts = [p.lower() for p in re.findall(r'[a-zA-Z0-9]+', father_clean)]
        father = f_parts[0] if f_parts else (parts[1] if len(parts) > 1 else "employee")
    else:
        father = parts[1] if len(parts) > 1 else "employee"
        
    base_login = f"{first}.{father}".lower()
    
    login = base_login
    counter = 1
    while login in existing_logins:
        counter += 1
        login = f"{base_login}.{counter}"
        
    existing_logins.add(login)
    return login

def seed_all():
    print("=== STARTING ODOO 14 MASTER DATA SEEDING INTO ODOO 19 ===")
    registry = Registry('ERP')
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        # -------------------------------------------------------------
        # 1. SEED OPERATING UNITS
        # -------------------------------------------------------------
        ou_file = os.path.join(CSV_DIR, 'operating_unit.csv')
        ou_map = {} # legacy_id -> operating.unit record
        
        if os.path.exists(ou_file):
            print("Importing Operating Units...")
            with open(ou_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    legacy_id = clean_str(row.get('id'))
                    name = clean_str(row.get('name'))
                    code = clean_str(row.get('code'))
                    if not name:
                        continue
                        
                    ou = False
                    if code:
                        ou = env['operating.unit'].search([('code', '=', code)], limit=1)
                    if not ou:
                        ou = env['operating.unit'].search([('name', '=', name)], limit=1)
                        
                    code_str = clean_str(row.get('code'))
                    code_int = False
                    if code_str:
                        digits = re.sub(r'\D', '', code_str)
                        if digits and int(digits) > 0:
                            code_int = int(digits)
                            
                    report_code_rec = False
                    if code_int:
                        report_code_rec = env['hr.report.code'].search([('code', '=', code_int)], limit=1)
                        if not report_code_rec:
                            try:
                                with env.cr.savepoint():
                                    report_code_rec = env['hr.report.code'].create({
                                        'name': name,
                                        'code': code_int
                                    })
                            except Exception:
                                report_code_rec = env['hr.report.code'].search([('code', '=', code_int)], limit=1)
                            
                    w_type = clean_str(row.get('work_unit_type'))
                    valid_w_types = {'branch', 'sub_branch', 'head_office', 'regional_office', 'district_office', 'service_center', 'other'}
                    if not w_type or w_type not in valid_w_types:
                        if w_type == 'area_office':
                            w_type = 'district_office'
                        else:
                            w_type = 'branch'

                    sol_val = clean_str(row.get('sol_id')) or code_str or "100"
                    vals = {
                        'name': name,
                        'code': report_code_rec.id if report_code_rec else False,
                        'sol_id': sol_val,
                        'active': parse_bool(row.get('active', 'true')),
                        'work_unit_type': w_type,
                        'district': clean_str(row.get('district')) or False,
                        'region': clean_str(row.get('region')) or False,
                        'branch_grade': clean_str(row.get('branch_grade')) or False,
                        'hardship_allowance': parse_float(row.get('hardship_allowance')),
                    }
                    
                    if not ou:
                        ou = env['operating.unit'].create(vals)
                    else:
                        ou.write(vals)
                        
                    if legacy_id:
                        ou_map[legacy_id] = ou
            print(f"Loaded {len(ou_map)} Operating Units.")

        # -------------------------------------------------------------
        # 2. SEED DEPARTMENTS
        # -------------------------------------------------------------
        dept_file = os.path.join(CSV_DIR, 'hr_departement.csv')
        dept_map = {} # legacy_id -> hr.department record
        dept_parent_raw = {} # legacy_id -> legacy_parent_id
        
        if os.path.exists(dept_file):
            print("Importing Departments...")
            with open(dept_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    legacy_id = clean_str(row.get('id'))
                    name = clean_str(row.get('name'))
                    if not name:
                        continue
                        
                    clean_name = re.sub(r'[^a-zA-Z\u00C0-\u024F\s]', ' ', name)
                    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
                    if not clean_name:
                        clean_name = f"Department {legacy_id}"
                        
                    dept = env['hr.department'].search([('name', '=', clean_name)], limit=1)
                    ou_legacy_id = clean_str(row.get('operating_unit'))
                    ou_rec = ou_map.get(ou_legacy_id) if ou_legacy_id else False
                    
                    vals = {
                        'name': clean_name,
                        'active': parse_bool(row.get('active', 'true')),
                    }
                    if ou_rec:
                        vals['operating_unit_id'] = ou_rec.id
                        
                    if not dept:
                        dept = env['hr.department'].create(vals)
                    else:
                        dept.write(vals)
                        
                    if legacy_id:
                        dept_map[legacy_id] = dept
                        p_id = clean_str(row.get('parent_id'))
                        if p_id:
                            dept_parent_raw[legacy_id] = p_id
                            
            # Link department parents
            for l_id, p_l_id in dept_parent_raw.items():
                d_rec = dept_map.get(l_id)
                p_rec = dept_map.get(p_l_id)
                if d_rec and p_rec and d_rec.id != p_rec.id:
                    d_rec.write({'parent_id': p_rec.id})
            print(f"Loaded {len(dept_map)} Departments.")

        # -------------------------------------------------------------
        # 2.5 SEED EMPLOYEE GRADES
        # -------------------------------------------------------------
        grade_file = os.path.join(CSV_DIR, 'employee_grade.csv')
        grade_map = {} # legacy_id -> employee.grade record
        
        if os.path.exists(grade_file):
            print("Importing Employee Grades...")
            with open(grade_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    legacy_id = clean_str(row.get('id'))
                    code_raw = clean_str(row.get('grade_code'))
                    name_raw = clean_str(row.get('grade_name'))
                    
                    if not name_raw:
                        name_raw = code_raw or f"Grade {legacy_id}"
                    if not re.search(r'[a-zA-Z]', name_raw):
                        name_raw = f"Grade {name_raw}"
                        
                    if not code_raw:
                        code_raw = name_raw.strip()
                        
                    cat_name = clean_str(row.get('category'))
                    cat_rec = False
                    if cat_name:
                        cat_rec = env['employee.category'].search([('category_name', '=', cat_name)], limit=1)
                        if not cat_rec:
                            cat_rec = env['employee.category'].create({'category_name': cat_name})
                            
                    b_salary = parse_float(row.get('base_salary'), default=0.0)
                    if b_salary <= 0:
                        b_salary = 1000.0
                    s_factor = parse_float(row.get('salary_factor'), default=1.0)
                    if s_factor <= 1.0:
                        s_factor = 1.100
                        
                    grade_rec = env['employee.grade'].search([('grade_code', '=', code_raw)], limit=1)
                    if not grade_rec:
                        grade_rec = env['employee.grade'].search([('grade_name', '=', name_raw)], limit=1)
                        
                    vals = {
                        'grade_name': name_raw,
                        'grade_code': code_raw,
                        'category': cat_rec.id if cat_rec else False,
                        'base_salary': b_salary,
                        'salary_factor': s_factor,
                        'start_date': parse_date(row.get('start_date')) or datetime.date.today(),
                        'end_date': parse_date(row.get('end_date')) or False,
                        'active': parse_bool(row.get('status', 'true')),
                    }
                    if not grade_rec:
                        existing_code = env['employee.grade'].search([('grade_code', '=ilike', code_raw)], limit=1)
                        if existing_code:
                            code_raw = f"{code_raw}_{legacy_id}"
                            vals['grade_code'] = code_raw
                        grade_rec = env['employee.grade'].create(vals)
                    else:
                        grade_rec.write(vals)
                        
                    if legacy_id:
                        grade_map[legacy_id] = grade_rec
            print(f"Loaded {len(grade_map)} Employee Grades.")

        # -------------------------------------------------------------
        # 3. SEED JOB POSITIONS
        # -------------------------------------------------------------
        job_file = os.path.join(CSV_DIR, 'hr_job.csv')
        job_map = {} # legacy_id -> hr.job record
        
        if os.path.exists(job_file):
            print("Importing Job Positions...")
            with open(job_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                count = 0
                for row in reader:
                    count += 1
                    legacy_id = clean_str(row.get('id'))
                    name = clean_str(row.get('name'))
                    if not name:
                        continue
                        
                    dept_legacy_id = clean_str(row.get('department_id'))
                    dept_rec = dept_map.get(dept_legacy_id) if dept_legacy_id else False
                    
                    grade_str = clean_str(row.get('grade'))
                    grade_rec = False
                    if grade_str:
                        if grade_str in grade_map:
                            grade_rec = grade_map[grade_str]
                        elif grade_str.isdigit():
                            grade_rec = env['employee.grade'].browse(int(grade_str)).exists()
                        if not grade_rec:
                            grade_rec = env['employee.grade'].search([('grade_name', '=', grade_str)], limit=1)
                        if not grade_rec:
                            grade_rec = env['employee.grade'].search([('grade_code', '=', grade_str)], limit=1)
                        if not grade_rec:
                            try:
                                with env.cr.savepoint():
                                    grade_rec = env['employee.grade'].create({
                                        'grade_name': grade_str,
                                        'grade_code': grade_str,
                                    })
                            except Exception:
                                grade_rec = env['employee.grade'].search([], limit=1)

                    job = env['hr.job'].search([('name', '=', name)], limit=1)
                    vals = {
                        'name': name,
                        'job_code': clean_str(row.get('job_code')) or False,
                        'grade': grade_rec.id if grade_rec else False,
                        'department_id': dept_rec.id if dept_rec else False,
                    }
                    if not job:
                        job = env['hr.job'].create(vals)
                    else:
                        job.write(vals)
                        
                    if legacy_id:
                        job_map[legacy_id] = job
            print(f"Loaded {len(job_map)} Job Positions.")

        # -------------------------------------------------------------
        # 4. SEED EMPLOYEES & USERS
        # -------------------------------------------------------------
        emp_file = os.path.join(CSV_DIR, 'hr emp.csv')
        emp_map = {} # legacy_id -> hr.employee record
        emp_parent_raw = {} # legacy_id -> legacy_parent_id
        emp_coach_raw = {}  # legacy_id -> legacy_coach_id
        
        # Existing logins set
        existing_logins = set(env['res.users'].search([]).mapped('login'))
        
        if os.path.exists(emp_file):
            print("Importing 4,629 Employees & User Accounts...")
            with open(emp_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                emp_count = 0
                for row in reader:
                    emp_count += 1
                    legacy_id = clean_str(row.get('id'))
                    name = clean_str(row.get('name'))
                    if not name:
                        continue
                        
                    father_name = clean_str(row.get('father_name')) or clean_str(row.get('father_name1'))
                    grand_father = clean_str(row.get('grand_father_name')) or clean_str(row.get('grand_father_name1'))
                    mother_name = clean_str(row.get('mother_name')) or clean_str(row.get('mother_name1'))
                    
                    work_email = clean_str(row.get('work_email'))
                    personal_email = clean_str(row.get('personal_email'))
                    
                    # Generate unique login
                    login = generate_username(name, father_name, existing_logins)
                    
                    # Check or Create res.users
                    user = False
                    if work_email:
                        user = env['res.users'].search([('login', '=', work_email)], limit=1)
                    if not user:
                        user = env['res.users'].search([('login', '=', login)], limit=1)
                        
                    if not user:
                        group_user = env.ref('base.group_user')
                        user = env['res.users'].with_context(
                            no_reset_password=True,
                            mail_create_nosubscribe=True,
                            mail_create_nolog=True,
                            tracking_disable=True,
                        ).create({
                            'name': name,
                            'login': login,
                            'password': '123',
                            'email': work_email or personal_email or f"{login}@bunnabank.com",
                            'group_ids': [(6, 0, [group_user.id])],
                        })
                    else:
                        # Ensure password is set to 123
                        user.with_context(no_reset_password=True).write({'password': '123'})

                    # Relate Department, Job, OU
                    dept_rec = dept_map.get(clean_str(row.get('department_id')))
                    job_rec = job_map.get(clean_str(row.get('job_id')))
                    ou_rec = ou_map.get(clean_str(row.get('default_operating_unit_id')))
                    
                    emp_id_num = clean_str(row.get('employee_identification')) or clean_str(row.get('identification_id')) or clean_str(row.get('emp_number'))
                    pension_no = clean_str(row.get('pension_number')) or clean_str(row.get('pension_no'))
                    
                    gender = clean_str(row.get('gender')) or clean_str(row.get('sex'))
                    if gender:
                        gender = gender.lower()
                        if gender not in ('male', 'female'):
                            gender = False
                    else:
                        gender = False
                            
                    marital = clean_str(row.get('marital'))
                    if marital:
                        marital = marital.lower()
                        if marital not in ('single', 'married', 'cohabitant', 'widower', 'divorced'):
                            marital = 'single'
                    else:
                        marital = 'single'

                    emp = env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
                    if not emp and emp_id_num:
                        emp = env['hr.employee'].search([('employee_identification', '=', emp_id_num)], limit=1)
                    if not emp:
                        emp = env['hr.employee'].search([('name', '=', name)], limit=1)
                        
                    vals = {
                        'name': name,
                        'user_id': user.id,
                        'active': parse_bool(row.get('active', 'true')),
                        'father_name': father_name or False,
                        'grand_father_name': grand_father or False,
                        'mother_name': mother_name or False,
                        'employee_identification': emp_id_num or False,
                        'identification_id': emp_id_num or False,
                        'pension_number': pension_no or False,
                        'pension_no': pension_no or False,
                        'gender': gender,
                        'marital': marital,
                        'birthday': parse_date(row.get('birthday')),
                        'service_start_date': parse_date(row.get('service_start_date')) or parse_date(row.get('joining_date')) or parse_date(row.get('start_date')),
                        'service_hire_date': parse_date(row.get('service_hire_date')) or parse_date(row.get('joining_date')),
                        'work_email': work_email or f"{login}@bunnabank.com",
                        'work_phone': clean_str(row.get('work_phone')) or False,
                        'mobile_phone': clean_str(row.get('mobile_phone')) or clean_str(row.get('personal_phone')) or clean_str(row.get('personal_mobile')),
                        'personal_email': personal_email or False,
                        'personal_phone': clean_str(row.get('personal_phone')) or clean_str(row.get('personal_mobile')),
                        'emergency_contact': clean_str(row.get('emergency_contact')),
                        'emergency_phone': clean_str(row.get('emergency_phone')),
                        'house_number': clean_str(row.get('house_number')),
                        'city': clean_str(row.get('city')),
                        'sub_city': clean_str(row.get('sub_city')),
                        'region': clean_str(row.get('region')),
                        'woreda': clean_str(row.get('woreda')),
                        'kebele': clean_str(row.get('kebele')),
                    }
                    
                    emp_job_grade_str = clean_str(row.get('job_grade'))
                    if emp_job_grade_str:
                        g_rec = False
                        if emp_job_grade_str in grade_map:
                            g_rec = grade_map[emp_job_grade_str]
                        elif emp_job_grade_str.isdigit():
                            g_rec = env['employee.grade'].browse(int(emp_job_grade_str)).exists()
                        if not g_rec:
                            g_rec = env['employee.grade'].search([('grade_name', '=', emp_job_grade_str)], limit=1)
                        if not g_rec:
                            g_rec = env['employee.grade'].search([('grade_code', '=', emp_job_grade_str)], limit=1)
                                
                        if g_rec:
                            vals['job_grade'] = g_rec.id
                            vals['grade_id'] = g_rec.id
                    
                    if dept_rec:
                        vals['department_id'] = dept_rec.id
                    if job_rec:
                        vals['job_id'] = job_rec.id
                    if ou_rec:
                        vals['default_operating_unit_id'] = ou_rec.id
                        vals['operating_unit_id'] = ou_rec.id
                        
                    if not emp:
                        emp = env['hr.employee'].create(vals)
                    else:
                        emp.write(vals)
                        
                    if legacy_id:
                        emp_map[legacy_id] = emp
                        p_emp_id = clean_str(row.get('parent_id'))
                        c_emp_id = clean_str(row.get('coach_id'))
                        if p_emp_id:
                            emp_parent_raw[legacy_id] = p_emp_id
                        if c_emp_id:
                            emp_coach_raw[legacy_id] = c_emp_id
                            
                    if emp_count % 500 == 0:
                        print(f"Processed {emp_count} employees...")
                        cr.commit()

            # Link Employee Managers & Coaches
            print("Linking Employee Managers and Coaches...")
            for l_id, p_l_id in emp_parent_raw.items():
                e_rec = emp_map.get(l_id)
                p_rec = emp_map.get(p_l_id)
                if e_rec and p_rec and e_rec.id != p_rec.id:
                    e_rec.write({'parent_id': p_rec.id})
                    
            for l_id, c_l_id in emp_coach_raw.items():
                e_rec = emp_map.get(l_id)
                c_rec = emp_map.get(c_l_id)
                if e_rec and c_rec and e_rec.id != c_rec.id:
                    e_rec.write({'coach_id': c_rec.id})

            cr.commit()
            print(f"SUCCESSFULLY SEEDED {len(emp_map)} EMPLOYEES AND USERS!")

if __name__ == '__main__':
    seed_all()
