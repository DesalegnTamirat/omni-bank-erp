# -*- coding: utf-8 -*-
"""
Synchronization & Master Data Seeding Script
Seeds and aligns master data from /mnt/extra-addons/seed_data_docs into Odoo 19 ERP database.
Matches records using canonical business keys and updates/overrides all unaligned fields.
Includes batched commits and tracking suppression to prevent locks and concurrency errors.
"""
import csv
import os
import re
import datetime
import logging
import openpyxl
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

_logger = logging.getLogger('sync_docs_data')
DATA_DIR = '/mnt/extra-addons/seed_data_docs'


def clean_str(val):
    if val is None or val == '' or val == 'NULL' or val == 'None':
        return False
    if isinstance(val, float) and val.is_integer():
        val = str(int(val))
    else:
        val = str(val)
    val = val.strip()
    return val if val else False


def parse_date(val):
    if not val:
        return False
    if isinstance(val, datetime.date):
        return val.strftime('%Y-%m-%d')
    if isinstance(val, datetime.datetime):
        return val.date().strftime('%Y-%m-%d')
    val_str = clean_str(val)
    if not val_str:
        return False
    val_str = val_str.split(' ')[0].split('T')[0]
    try:
        dt = datetime.datetime.strptime(val_str, '%Y-%m-%d')
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return False


def parse_float(val, default=0.0):
    val_str = clean_str(val)
    if not val_str:
        return default
    try:
        return float(val_str)
    except Exception:
        return default


def parse_bool(val):
    if val is True or val is False:
        return val
    val_str = clean_str(val)
    if not val_str:
        return False
    return val_str.lower() in ('true', 't', '1', 'yes')


def normalize_name(name):
    if not name:
        return ''
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', str(name))
    return re.sub(r'\s+', ' ', cleaned).strip().lower()


def run_sync():
    print("=================================================================")
    print(" STARTING MASTER DATA SEEDING & ALIGNMENT FROM docs/data")
    print("=================================================================")

    odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'ERP'])
    registry = Registry('ERP')

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {
            'mail_create_nosubscribe': True,
            'mail_notrack': True,
            'tracking_disable': True,
            'no_reset_password': True,
        })

        # =============================================================
        # 1. SEED OPERATING UNITS (operating_unit.csv)
        # =============================================================
        ou_file = os.path.join(DATA_DIR, 'operating_unit.csv')
        ou_map = {}  # legacy_id -> operating.unit record
        ou_updated = 0
        ou_created = 0

        if os.path.exists(ou_file):
            print("\n--- 1. Processing Operating Units ---")
            with open(ou_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    legacy_id = clean_str(row.get('id'))
                    name = clean_str(row.get('name'))
                    code_raw = clean_str(row.get('code'))
                    sol_id = clean_str(row.get('sol_id')) or code_raw or "100"
                    if not name:
                        continue

                    # Report code resolution
                    report_code_rec = False
                    if code_raw:
                        digits = re.sub(r'\D', '', code_raw)
                        if digits and int(digits) > 0:
                            code_int = int(digits)
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
                        w_type = 'district_office' if w_type == 'area_office' else 'branch'

                    vals = {
                        'name': name,
                        'sol_id': sol_id,
                        'active': parse_bool(row.get('active', 'true')),
                        'work_unit_type': w_type,
                        'district': clean_str(row.get('district')) or False,
                        'region': clean_str(row.get('region')) or False,
                        'branch_grade': clean_str(row.get('branch_grade')) or False,
                        'hardship_allowance': parse_float(row.get('hardship_allowance')),
                    }
                    if report_code_rec:
                        vals['code'] = report_code_rec.id

                    # Match by sol_id, name, or code
                    ou = False
                    if sol_id and sol_id != '100':
                        ou = env['operating.unit'].search([('sol_id', '=', sol_id)], limit=1)
                    if not ou:
                        ou = env['operating.unit'].search([('name', '=', name)], limit=1)

                    try:
                        with env.cr.savepoint():
                            if ou:
                                ou.write(vals)
                                ou_updated += 1
                            else:
                                ou = env['operating.unit'].create(vals)
                                ou_created += 1
                    except Exception as e:
                        _logger.warning(f"Error on OU {name}: {e}")

                    if legacy_id and ou:
                        ou_map[legacy_id] = ou

            cr.commit()
            print(f"Operating Units: {ou_created} created, {ou_updated} updated (Mapped: {len(ou_map)})")

        # =============================================================
        # 2. SEED JOB GRADES (job grade.xlsx)
        # =============================================================
        grade_file = os.path.join(DATA_DIR, 'job grade.xlsx')
        grade_map = {}  # legacy_id -> employee.grade record
        grade_created = 0
        grade_updated = 0

        if os.path.exists(grade_file):
            print("\n--- 2. Processing Job Grades ---")
            wb = openpyxl.load_workbook(grade_file, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            header = [clean_str(h) for h in rows[0]]

            for row_vals in rows[1:]:
                row = dict(zip(header, row_vals))
                legacy_id = clean_str(row.get('id'))
                code_raw = clean_str(row.get('grade_code'))
                name_raw = clean_str(row.get('grade_name'))

                if not name_raw and not code_raw:
                    continue
                if not name_raw:
                    name_raw = code_raw
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
                s_factor = parse_float(row.get('salary_factor'), default=1.0)

                vals = {
                    'grade_name': name_raw.strip(),
                    'grade_code': code_raw.strip(),
                    'category': cat_rec.id if cat_rec else False,
                    'base_salary': b_salary if b_salary > 0 else 1000.0,
                    'salary_factor': s_factor if s_factor > 1.0 else 1.10,
                    'active': parse_bool(row.get('status', 'true')),
                }
                s_date = parse_date(row.get('start_date'))
                if s_date:
                    vals['start_date'] = s_date
                e_date = parse_date(row.get('end_date'))
                if e_date:
                    vals['end_date'] = e_date

                grade_rec = env['employee.grade'].search([('grade_code', '=ilike', code_raw.strip())], limit=1)
                if not grade_rec:
                    grade_rec = env['employee.grade'].search([('grade_name', '=ilike', name_raw.strip())], limit=1)

                try:
                    with env.cr.savepoint():
                        if grade_rec:
                            grade_rec.write(vals)
                            grade_updated += 1
                        else:
                            grade_rec = env['employee.grade'].create(vals)
                            grade_created += 1
                except Exception as e:
                    try:
                        with env.cr.savepoint():
                            vals['grade_code'] = f"{code_raw.strip()}_{legacy_id}"
                            grade_rec = env['employee.grade'].create(vals)
                            grade_created += 1
                    except Exception:
                        grade_rec = env['employee.grade'].search([('grade_name', '=ilike', name_raw.strip())], limit=1)

                if legacy_id and grade_rec:
                    grade_map[legacy_id] = grade_rec

            cr.commit()
            print(f"Job Grades: {grade_created} created, {grade_updated} updated (Mapped: {len(grade_map)})")

        # =============================================================
        # 3. SEED DEPARTMENTS (hr_departement.csv)
        # =============================================================
        dept_file = os.path.join(DATA_DIR, 'hr_departement.csv')
        dept_map = {}  # legacy_id -> hr.department record
        dept_parents = {}  # legacy_id -> parent_legacy_id
        dept_created = 0
        dept_updated = 0

        if os.path.exists(dept_file):
            print("\n--- 3. Processing Departments ---")
            with open(dept_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
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

                    ou_leg_id = clean_str(row.get('operating_unit'))
                    ou_rec = ou_map.get(ou_leg_id) if ou_leg_id else False

                    vals = {
                        'name': clean_name,
                        'active': parse_bool(row.get('active', 'true')),
                    }
                    if ou_rec:
                        vals['operating_unit_id'] = ou_rec.id

                    dept = env['hr.department'].search([('name', '=', clean_name)], limit=1)
                    if not dept:
                        dept = env['hr.department'].search([('name', '=ilike', clean_name)], limit=1)

                    try:
                        with env.cr.savepoint():
                            if dept:
                                dept.write(vals)
                                dept_updated += 1
                            else:
                                dept = env['hr.department'].create(vals)
                                dept_created += 1
                    except Exception as e:
                        _logger.warning(f"Error on Dept {clean_name}: {e}")

                    if legacy_id and dept:
                        dept_map[legacy_id] = dept
                        p_id = clean_str(row.get('parent_id'))
                        if p_id:
                            dept_parents[legacy_id] = p_id

            # Pass 2: Link Department Hierarchy
            for l_id, p_id in dept_parents.items():
                d_rec = dept_map.get(l_id)
                p_rec = dept_map.get(p_id)
                if d_rec and p_rec and d_rec.id != p_rec.id:
                    try:
                        with env.cr.savepoint():
                            d_rec.write({'parent_id': p_rec.id})
                    except Exception:
                        pass

            cr.commit()
            print(f"Departments: {dept_created} created, {dept_updated} updated (Mapped: {len(dept_map)})")

        # =============================================================
        # 4. SEED JOB POSITIONS (job position.xlsx)
        # =============================================================
        job_file = os.path.join(DATA_DIR, 'job position.xlsx')
        job_map = {}  # legacy_id -> hr.job record
        job_created = 0
        job_updated = 0

        if os.path.exists(job_file):
            print("\n--- 4. Processing Job Positions ---")
            wb = openpyxl.load_workbook(job_file, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            header = [clean_str(h) for h in rows[0]]

            for row_vals in rows[1:]:
                row = dict(zip(header, row_vals))
                legacy_id = clean_str(row.get('id'))
                name = clean_str(row.get('name'))
                if not name:
                    continue

                dept_leg_id = clean_str(row.get('department_id'))
                dept_rec = dept_map.get(dept_leg_id) if dept_leg_id else False

                grade_str = clean_str(row.get('grade'))
                grade_rec = False
                if grade_str:
                    grade_rec = grade_map.get(grade_str)
                    if not grade_rec:
                        grade_rec = env['employee.grade'].search([('grade_code', '=', grade_str)], limit=1)
                    if not grade_rec:
                        grade_rec = env['employee.grade'].search([('grade_name', '=', grade_str)], limit=1)

                vals = {
                    'name': name.strip(),
                    'job_code': clean_str(row.get('job_code')) or False,
                    'department_id': dept_rec.id if dept_rec else False,
                    'expected_employees': int(parse_float(row.get('expected_employees'), default=1)),
                }
                if grade_rec:
                    vals['grade'] = grade_rec.id

                # Match by job_code or name
                job = False
                if vals['job_code']:
                    job = env['hr.job'].search([('job_code', '=', vals['job_code'])], limit=1)
                if not job:
                    if dept_rec:
                        job = env['hr.job'].search([('name', '=', name.strip()), ('department_id', '=', dept_rec.id)], limit=1)
                    if not job:
                        job = env['hr.job'].search([('name', '=', name.strip())], limit=1)

                try:
                    with env.cr.savepoint():
                        if job:
                            job.write(vals)
                            job_updated += 1
                        else:
                            job = env['hr.job'].create(vals)
                            job_created += 1
                except Exception as e:
                    _logger.warning(f"Error on Job {name}: {e}")

                if legacy_id and job:
                    job_map[legacy_id] = job

            cr.commit()
            print(f"Job Positions: {job_created} created, {job_updated} updated (Mapped: {len(job_map)})")

        # =============================================================
        # 5. SEED EMPLOYEES (hr_employee.xlsx)
        # =============================================================
        emp_file = os.path.join(DATA_DIR, 'hr_employee.xlsx')
        emp_map = {}  # legacy_id -> hr.employee record
        emp_parents = {}  # legacy_id -> parent_legacy_id
        emp_coaches = {}  # legacy_id -> coach_legacy_id
        emp_created = 0
        emp_updated = 0

        if os.path.exists(emp_file):
            print("\n--- 5. Processing Employees & Aligning Data ---")
            wb = openpyxl.load_workbook(emp_file, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            header = [clean_str(h) for h in rows[0]]

            total_emp_rows = len(rows) - 1
            print(f"Total rows in hr_employee.xlsx: {total_emp_rows}")

            # Pre-cache all existing employees for rapid O(1) matching
            print("Caching existing database employees...")
            all_db_emps = env['hr.employee'].search([])
            emp_by_email = {}
            emp_by_name = {}
            emp_by_num = {}

            for e in all_db_emps:
                if e.work_email:
                    emp_by_email[e.work_email.strip().lower()] = e
                if e.name:
                    emp_by_name[normalize_name(e.name)] = e
                if hasattr(e, 'emp_number') and e.emp_number:
                    emp_by_num[str(e.emp_number).strip()] = e
                if hasattr(e, 'employee_identification') and e.employee_identification:
                    emp_by_num[str(e.employee_identification).strip()] = e

            count = 0
            for row_vals in rows[1:]:
                count += 1
                row = dict(zip(header, row_vals))
                legacy_id = clean_str(row.get('id'))
                name = clean_str(row.get('name'))
                if not name:
                    continue

                work_email = clean_str(row.get('work_email'))
                emp_number = clean_str(row.get('emp_number')) or clean_str(row.get('employee_identification'))
                norm_name = normalize_name(name)

                # Find match in current DB
                emp = False
                if work_email and work_email.lower() in emp_by_email:
                    emp = emp_by_email[work_email.lower()]
                elif emp_number and emp_number in emp_by_num:
                    emp = emp_by_num[emp_number]
                elif norm_name and norm_name in emp_by_name:
                    emp = emp_by_name[norm_name]

                # Resolve relationships
                dept_leg_id = clean_str(row.get('department_id'))
                dept_rec = dept_map.get(dept_leg_id) if dept_leg_id else False

                job_leg_id = clean_str(row.get('job_id'))
                job_rec = job_map.get(job_leg_id) if job_leg_id else False
                if not job_rec:
                    job_title_str = clean_str(row.get('job_title')) or clean_str(row.get('job_name'))
                    if job_title_str:
                        job_rec = env['hr.job'].search([('name', '=ilike', job_title_str.strip())], limit=1)

                grade_leg_id = clean_str(row.get('job_grade'))
                grade_rec = grade_map.get(grade_leg_id) if grade_leg_id else False
                if not grade_rec and grade_leg_id:
                    grade_rec = env['employee.grade'].search([('grade_code', '=', grade_leg_id)], limit=1)

                ou_leg_id = clean_str(row.get('default_operating_unit_id'))
                ou_rec = ou_map.get(ou_leg_id) if ou_leg_id else False

                vals = {
                    'name': name.strip(),
                    'active': parse_bool(row.get('active', 'true')),
                    'work_email': work_email or False,
                    'mobile_phone': clean_str(row.get('mobile_phone')) or False,
                    'work_phone': clean_str(row.get('work_phone')) or False,
                    'job_title': clean_str(row.get('job_title')) or False,
                }

                if dept_rec:
                    vals['department_id'] = dept_rec.id
                if job_rec:
                    vals['job_id'] = job_rec.id
                if grade_rec and 'job_grade' in env['hr.employee']._fields:
                    vals['job_grade'] = grade_rec.id
                if ou_rec and 'default_operating_unit_id' in env['hr.employee']._fields:
                    vals['default_operating_unit_id'] = ou_rec.id

                # Gender & Marital
                gender = clean_str(row.get('gender'))
                if gender and gender.lower() in ('male', 'female', 'other'):
                    vals['gender'] = gender.lower()
                marital = clean_str(row.get('marital'))
                if marital and marital.lower() in ('single', 'married', 'cohabitant', 'widower', 'divorced'):
                    vals['marital'] = marital.lower()

                # Dates
                bday = parse_date(row.get('birthday'))
                if bday:
                    vals['birthday'] = bday
                s_date = parse_date(row.get('service_start_date')) or parse_date(row.get('joining_date')) or parse_date(row.get('start_date'))
                if s_date and 'start_date' in env['hr.employee']._fields:
                    vals['start_date'] = s_date

                # ID & Pension
                ident = clean_str(row.get('identification_id')) or clean_str(row.get('employee_identification'))
                if ident:
                    vals['identification_id'] = ident
                pension = clean_str(row.get('pension_number')) or clean_str(row.get('pension_no'))
                if pension and 'pension_number' in env['hr.employee']._fields:
                    vals['pension_number'] = pension

                # Custom Bunna Fields
                if 'father_name' in env['hr.employee']._fields:
                    fn = clean_str(row.get('father_name')) or clean_str(row.get('father_name1'))
                    if fn:
                        vals['father_name'] = fn
                if 'grand_father_name' in env['hr.employee']._fields:
                    gfn = clean_str(row.get('grand_father_name')) or clean_str(row.get('grand_father_name1'))
                    if gfn:
                        vals['grand_father_name'] = gfn
                if 'mother_name' in env['hr.employee']._fields:
                    mn = clean_str(row.get('mother_name')) or clean_str(row.get('mother_name1'))
                    if mn:
                        vals['mother_name'] = mn

                success = False
                try:
                    with env.cr.savepoint():
                        if emp:
                            emp.write(vals)
                            emp_updated += 1
                        else:
                            emp = env['hr.employee'].create(vals)
                            emp_created += 1
                            if work_email:
                                emp_by_email[work_email.lower()] = emp
                            emp_by_name[norm_name] = emp
                    success = True
                except Exception:
                    # Retry with safe minimal values
                    try:
                        with env.cr.savepoint():
                            min_vals = {'name': name.strip()}
                            if dept_rec:
                                min_vals['department_id'] = dept_rec.id
                            if job_rec:
                                min_vals['job_id'] = job_rec.id
                            if emp:
                                emp.write(min_vals)
                                emp_updated += 1
                            else:
                                emp = env['hr.employee'].create(min_vals)
                                emp_created += 1
                        success = True
                    except Exception as inner_e:
                        _logger.warning(f"Could not sync employee {name}: {inner_e}")

                if legacy_id and emp and success:
                    emp_map[legacy_id] = emp
                    p_leg_id = clean_str(row.get('parent_id'))
                    if p_leg_id:
                        emp_parents[legacy_id] = p_leg_id
                    c_leg_id = clean_str(row.get('coach_id'))
                    if c_leg_id:
                        emp_coaches[legacy_id] = c_leg_id

                if count % 100 == 0:
                    cr.commit()
                    print(f"Processed & committed {count} / {total_emp_rows} employees...")

            cr.commit()
            print(f"Employees Pass 1: {emp_created} created, {emp_updated} updated (Mapped: {len(emp_map)})")

            # Pass 2: Link Employee Reporting Hierarchy (Managers & Coaches)
            print("\n--- Linking Employee Hierarchy (Managers & Coaches) ---")
            parent_links = 0
            coach_links = 0

            hier_count = 0
            for l_id, p_leg_id in emp_parents.items():
                e_rec = emp_map.get(l_id)
                m_rec = emp_map.get(p_leg_id)
                if e_rec and m_rec and e_rec.id != m_rec.id:
                    try:
                        with env.cr.savepoint():
                            e_rec.write({'parent_id': m_rec.id})
                            parent_links += 1
                    except Exception:
                        pass
                hier_count += 1
                if hier_count % 200 == 0:
                    cr.commit()

            for l_id, c_leg_id in emp_coaches.items():
                e_rec = emp_map.get(l_id)
                c_rec = emp_map.get(c_leg_id)
                if e_rec and c_rec and e_rec.id != c_rec.id:
                    try:
                        with env.cr.savepoint():
                            e_rec.write({'coach_id': c_rec.id})
                            coach_links += 1
                    except Exception:
                        pass
                hier_count += 1
                if hier_count % 200 == 0:
                    cr.commit()

            cr.commit()
            print(f"Hierarchy Pass 2: Linked {parent_links} managers and {coach_links} coaches.")

        # =============================================================
        # 6. SEED PARTNERS (res partner.csv)
        # =============================================================
        partner_file = os.path.join(DATA_DIR, 'res partner.csv')
        if os.path.exists(partner_file):
            print("\n--- 6. Processing Res Partners ---")
            with open(partner_file, 'r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.DictReader(f)
                p_count = 0
                p_updated = 0
                p_created = 0
                for row in reader:
                    p_count += 1
                    name = clean_str(row.get('name'))
                    if not name:
                        continue
                    email = clean_str(row.get('email'))
                    if email:
                        email = email.replace('\\', '').strip()
                    phone = clean_str(row.get('phone')) or clean_str(row.get('mobile'))
                    if phone:
                        phone = phone.replace('\\', '').strip()

                    partner = False
                    try:
                        if email and '@' in email:
                            partner = env['res.partner'].search([('email', '=', email)], limit=1)
                        if not partner and phone:
                            partner = env['res.partner'].search([('phone', '=', phone)], limit=1)
                        if not partner and name:
                            clean_p_name = name.replace('\\', '').strip()
                            partner = env['res.partner'].search([('name', '=', clean_p_name)], limit=1)
                    except Exception:
                        partner = False

                    vals = {
                        'name': name,
                        'email': email or False,
                        'phone': phone or False,
                        'street': clean_str(row.get('street')) or False,
                        'city': clean_str(row.get('city')) or False,
                        'active': parse_bool(row.get('active', 'true')),
                    }
                    try:
                        with env.cr.savepoint():
                            if partner:
                                partner.write(vals)
                                p_updated += 1
                            else:
                                env['res.partner'].create(vals)
                                p_created += 1
                    except Exception:
                        pass

                    if p_count % 500 == 0:
                        cr.commit()
                        print(f"Processed & committed {p_count} partners...")

                cr.commit()
                print(f"Partners: {p_created} created, {p_updated} updated.")

        cr.commit()
        print("\n=================================================================")
        print(" MASTER DATA SEEDING & ALIGNMENT COMPLETED SUCCESSFULLY!")
        print("=================================================================")


if __name__ == '__main__':
    run_sync()
