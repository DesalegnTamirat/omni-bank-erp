# -*- coding: utf-8 -*-
import csv
import os
import re
import datetime
import logging
import odoo
from odoo import api, SUPERUSER_ID, fields
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

def run_seed():
    print("=== SEEDING JOB GRADES AND UPDATING EMPLOYEE JOB GRADES ===")
    odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf'])
    registry = Registry('ERP')
    
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        
        # -------------------------------------------------------------
        # 1. SEED EMPLOYEE GRADES
        # -------------------------------------------------------------
        grade_file = os.path.join(CSV_DIR, 'employee_grade.csv')
        if not os.path.exists(grade_file):
            grade_file = 'docs/data/employee_grade.csv'
            
        grade_map = {} # legacy_id -> employee.grade record
        
        if os.path.exists(grade_file):
            print(f"Reading {grade_file}...")
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
                        b_salary = 1000.0  # Constraint requires base_salary > 0
                        
                    s_factor = parse_float(row.get('salary_factor'), default=1.0)
                    if s_factor <= 1.0:
                        s_factor = 1.100  # Constraint requires salary_factor > 1
                        
                    # Search for existing grade by code or name
                    grade_rec = env['employee.grade'].search([('grade_code', '=', code_raw)], limit=1)
                    if not grade_rec:
                        grade_rec = env['employee.grade'].search([('grade_name', '=', name_raw)], limit=1)
                        
                    vals = {
                        'grade_name': name_raw,
                        'grade_code': code_raw,
                        'category': cat_rec.id if cat_rec else False,
                        'base_salary': b_salary,
                        'salary_factor': s_factor,
                        'start_date': parse_date(row.get('start_date')) or fields.Date.today(),
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
                        
            cr.commit()
            print(f"Successfully seeded {len(grade_map)} Employee Grades.")
        else:
            print(f"ERROR: File {grade_file} not found!")

        # -------------------------------------------------------------
        # 2. UPDATE EMPLOYEE JOB GRADES
        # -------------------------------------------------------------
        emp_file = os.path.join(CSV_DIR, 'hr emp.csv')
        if not os.path.exists(emp_file):
            emp_file = 'docs/data/hr emp.csv'
            
        if os.path.exists(emp_file) and grade_map:
            print(f"Updating Employee Job Grades from {emp_file}...")
            updated_emp_count = 0
            with open(emp_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    legacy_grade_id = clean_str(row.get('job_grade'))
                    if not legacy_grade_id:
                        continue
                        
                    grade_rec = grade_map.get(legacy_grade_id)
                    if not grade_rec:
                        continue
                        
                    emp_id_num = clean_str(row.get('employee_identification')) or clean_str(row.get('identification_id')) or clean_str(row.get('emp_number'))
                    name = clean_str(row.get('name'))
                    work_email = clean_str(row.get('work_email'))
                    
                    emp = False
                    if work_email:
                        emp = env['hr.employee'].search([('work_email', '=', work_email)], limit=1)
                    if not emp and emp_id_num:
                        emp = env['hr.employee'].search([('employee_identification', '=', emp_id_num)], limit=1)
                    if not emp and name:
                        emp = env['hr.employee'].search([('name', '=', name)], limit=1)
                        
                    if emp:
                        emp.write({'job_grade': grade_rec.id})
                        updated_emp_count += 1
                        if updated_emp_count % 500 == 0:
                            print(f"Updated {updated_emp_count} employees...")
                            cr.commit()
                            
            cr.commit()
            print(f"SUCCESS: Updated {updated_emp_count} Employees with job_grade!")

        # -------------------------------------------------------------
        # 3. UPDATE HR JOB GRADES
        # -------------------------------------------------------------
        job_file = os.path.join(CSV_DIR, 'hr_job.csv')
        if not os.path.exists(job_file):
            job_file = 'docs/data/hr_job.csv'
            
        if os.path.exists(job_file) and grade_map:
            print(f"Updating HR Job Grades from {job_file}...")
            updated_job_count = 0
            with open(job_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = clean_str(row.get('name'))
                    legacy_grade_id = clean_str(row.get('grade'))
                    if not name or not legacy_grade_id:
                        continue
                        
                    grade_rec = grade_map.get(legacy_grade_id)
                    if not grade_rec:
                        continue
                        
                    job = env['hr.job'].search([('name', '=', name)], limit=1)
                    if job:
                        job.write({'grade': grade_rec.id})
                        updated_job_count += 1
                        
            cr.commit()
            print(f"SUCCESS: Updated {updated_job_count} HR Jobs with grade!")

if __name__ == '__main__':
    run_seed()
