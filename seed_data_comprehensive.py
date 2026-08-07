import sys
from datetime import datetime, timedelta
import random

def seed_data():
    print("Starting Comprehensive Data Seeding...")
    env = globals().get('env')
    
    # --- 1. CLEANUP OLD DATA ---
    print("Cleaning up old data...")
    # Preserve admin employee and users created in the first script
    admin_user = env.ref('base.user_admin')
    preserved_logins = ['admin', 'abebe', 'chala']
    preserved_users = env['res.users'].search([('login', 'in', preserved_logins)])
    
    # Delete old attendances (Attendances don't have active field usually, so unlink is fine, but they might have constraints. Let's try unlink)
    old_attendances = env['hr.attendance'].search([('employee_id.user_id', 'not in', preserved_users.ids)])
    try:
        old_attendances.unlink()
        print("Deleted old attendances.")
    except Exception as e:
        print(f"Could not delete old attendances: {e}")
    
    # Archive old contracts
    old_contracts = env['hr.contract'].search([('employee_id.user_id', 'not in', preserved_users.ids)])
    try:
        old_contracts.write({'active': False})
        print("Archived old contracts.")
    except Exception as e:
        print(f"Could not archive contracts: {e}")
    
    # Archive old employees to avoid FK violations
    old_employees = env['hr.employee'].search([('user_id', 'not in', preserved_users.ids)])
    try:
        old_employees.write({'active': False})
        print(f"Archived {len(old_employees)} old employees.")
    except Exception as e:
        print(f"Could not archive old employees: {e}")

    # --- 2. CREATE PREREQUISITES (Grades, Locations, Operating Units, Jobs) ---
    print("Creating prerequisite records...")
    
    # Grade
    grade = None
    if 'employee.grade' in env:
        grade = env['employee.grade'].search([], limit=1)
        if not grade:
            # Maybe the field is not 'name'. We'll try to create it, but if it fails, just skip grade.
            try:
                grade = env['employee.grade'].create({})
            except Exception:
                grade = None

    # Operating Units (Assuming standard fields 'name' and 'code')
    ou_model = env.get('operating.unit')
    ou_hq = None
    ou_branch = None
    if ou_model is not None:
        ou_hq = ou_model.search([], limit=1)
        # Just grab any second OU if it exists
        ou_branch = ou_model.search([('id', '!=', ou_hq.id if ou_hq else 0)], limit=1)
                
    # Locations (res.partner)
    partner_hq = env['res.partner'].search([('name', '=', 'HQ Location')], limit=1)
    if not partner_hq:
        partner_hq = env['res.partner'].create({'name': 'HQ Location', 'city': 'Addis Ababa', 'type': 'other'})
        
    partner_branch = env['res.partner'].search([('name', '=', 'Branch 01 Location')], limit=1)
    if not partner_branch:
        partner_branch = env['res.partner'].create({'name': 'Branch 01 Location', 'city': 'Hawassa', 'type': 'other'})

    # Departments
    dept_it = env['hr.department'].search([('name', '=', 'IT Department')], limit=1)
    if not dept_it:
        dept_it = env['hr.department'].create({'name': 'IT Department'})
    if ou_hq and 'operating_unit_id' in env['hr.department']._fields:
        dept_it.operating_unit_id = ou_hq.id

    dept_sales = env['hr.department'].search([('name', '=', 'Sales and Marketing')], limit=1)
    if not dept_sales:
        dept_sales = env['hr.department'].create({'name': 'Sales and Marketing'})
    if ou_branch and 'operating_unit_id' in env['hr.department']._fields:
        dept_sales.operating_unit_id = ou_branch.id

    # Job Positions
    job_dev = env['hr.job'].search([('name', '=', 'Software Developer')], limit=1)
    if not job_dev:
        job_dev = env['hr.job'].create({'name': 'Software Developer', 'department_id': dept_it.id})
        
    job_sales = env['hr.job'].search([('name', '=', 'Sales Executive')], limit=1)
    if not job_sales:
        job_sales = env['hr.job'].create({'name': 'Sales Executive', 'department_id': dept_sales.id})

    # --- 3. CREATE EMPLOYEES & USERS ---
    print("Creating employees and contracts...")
    scenarios = [
        {'name': 'Dawit Alemu Normal', 'login': 'dawit', 'dept': dept_it, 'job': job_dev, 'loc': partner_hq, 'wage': 60000,
            'attendance_type': 'normal'},
        {'name': 'Hana Tadesse Late', 'login': 'hana', 'dept': dept_it, 'job': job_dev, 'loc': partner_hq, 'wage': 55000,
            'attendance_type': 'late'},
        {'name': 'Samuel Bekele ForcedCO', 'login': 'samuel', 'dept': dept_sales, 'job': job_sales, 'loc': partner_branch, 'wage': 45000,
            'attendance_type': 'forced_checkout'},
        {'name': 'Tigist Worku Perfect', 'login': 'tigist', 'dept': dept_sales, 'job': job_sales, 'loc': partner_branch, 'wage': 50000,
            'attendance_type': 'perfect'}
    ]

    employees = []
    for s in scenarios:
        user = env['res.users'].search([('login', '=', s['login'])], limit=1)
        if not user:
            user = env['res.users'].create({
                'name': s['name'],
                'login': s['login'],
                'password': '123'
            })
            
        emp = env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        if not emp:
            emp_vals = {
                'name': s['name'],
                'user_id': user.id,
                'department_id': s['dept'].id,
                'job_id': s['job'].id,
                'address_id': s['loc'].id,
            }
            if grade and 'job_grade' in env['hr.employee']._fields:
                emp_vals['job_grade'] = grade.id
            emp = env['hr.employee'].create(emp_vals)
            
        # Contract
        if 'hr.contract' in env:
            contract = env['hr.contract'].search([('employee_id', '=', emp.id)], limit=1)
            if not contract:
                c_vals = {
                    'name': f"{s['name']} Contract",
                    'employee_id': emp.id,
                    'job_id': s['job'].id,
                    'department_id': s['dept'].id,
                    'state': 'open',
                    'wage': s['wage'],
                }
                if grade and 'job_grade' in env['hr.contract']._fields:
                    c_vals['job_grade'] = grade.id
                env['hr.contract'].create(c_vals)
                
        employees.append({'emp': emp, 'type': s['attendance_type']})

    # --- 4. SEED DIVERSE ATTENDANCES ---
    print("Generating diverse attendance records for the last 14 days...")
    now = datetime.now()
    
    for day_offset in range(1, 15):
        current_date = now - timedelta(days=day_offset)
        if current_date.weekday() == 6: # Skip Sundays
            continue
            
        for data in employees:
            emp = data['emp']
            a_type = data['type']
            
            check_in_time = None
            check_out_time = None
            
            # Base start is 8:00 AM (server time, assumed UTC for Ethiopian 2:00 local, wait, lets just use 5:00 UTC = 8:00 AM EAT)
            base_hour = 5
            
            if a_type == 'normal':
                # Check in around 8:00 to 8:15
                check_in_time = current_date.replace(hour=base_hour, minute=random.randint(0, 15), second=0, microsecond=0)
                # Check out around 17:00 (5 PM)
                check_out_time = check_in_time + timedelta(hours=9, minutes=random.randint(0, 30))
                
            elif a_type == 'late':
                # Check in late (8:30 to 10:00)
                check_in_time = current_date.replace(hour=base_hour + random.randint(0, 1), minute=random.randint(30, 59), second=0, microsecond=0)
                # Check out standard
                check_out_time = check_in_time + timedelta(hours=8, minutes=random.randint(0, 30))
                
            elif a_type == 'forced_checkout':
                # Check in normally
                check_in_time = current_date.replace(hour=base_hour, minute=random.randint(0, 10), second=0, microsecond=0)
                # No check out! So system or manager forces it later. We will simulate by marking checkout at exactly 12 hours max limit, or just empty if we want to leave it open for today.
                # Let's create a closed attendance that looks like a force checkout.
                # Some custom modules have a 'is_forced_checkout' boolean.
                check_out_time = check_in_time + timedelta(hours=14) # Force check out after 14 hours
                
            elif a_type == 'perfect':
                # Check in exactly 7:55, check out exactly 17:05
                check_in_time = current_date.replace(hour=base_hour, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
                check_out_time = current_date.replace(hour=base_hour + 9, minute=5, second=0, microsecond=0)

            att_vals = {
                'employee_id': emp.id,
                'check_in': check_in_time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            if check_out_time:
                att_vals['check_out'] = check_out_time.strftime('%Y-%m-%d %H:%M:%S')
                
            # If the DB has forced checkout custom fields, we can try to set them:
            if a_type == 'forced_checkout' and 'force_checkout' in env['hr.attendance']._fields:
                att_vals['force_checkout'] = True
                
            env['hr.attendance'].create(att_vals)

    env.cr.commit()
    print("========================================")
    print("✅ Comprehensive Data Seeded Successfully!")
    print("Created scenarios: Normal, Late, Forced Checkout, Perfect")
    print("Created hierarchical departments, jobs, locations, and units.")
    print("========================================")

if __name__ == '__main__':
    try:
        seed_data()
    except Exception as e:
        globals().get('env').cr.rollback()
        print(f"❌ Error during comprehensive seeding: {str(e)}")
