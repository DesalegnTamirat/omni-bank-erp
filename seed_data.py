import sys
from datetime import datetime, timedelta
import random

# This script is meant to be run via `odoo shell -d odoo19 < seed_data.py`
# `env` is globally available in the Odoo shell.

try:
    print("Starting data seeding process...")

    # 1. Admin User
    admin_user = env.ref('base.user_admin')
    
    # Ensure employee grade exists for contract
    if 'employee.grade' in env:
        grade = env['employee.grade'].search([], limit=1)
        if not grade:
            grade = env['employee.grade'].create({'name': 'Grade 1'})
    else:
        grade = None

    admin_emp = env['hr.employee'].search([('user_id', '=', admin_user.id)], limit=1)
    if not admin_emp:
        emp_vals = {
            'name': 'Administrator',
            'user_id': admin_user.id,
        }
        if grade and 'job_grade' in env['hr.employee']._fields:
            emp_vals['job_grade'] = grade.id
        admin_emp = env['hr.employee'].create(emp_vals)
        print(f"Created Admin Employee: {admin_emp.name}")
    else:
        print(f"Found existing Admin Employee: {admin_emp.name}")

    # Ensure admin has a contract
    if 'hr.contract' in env:
        admin_contract = env['hr.contract'].search([('employee_id', '=', admin_emp.id)], limit=1)
        if not admin_contract:
            contract_vals = {
                'name': 'Admin Permanent Contract',
                'employee_id': admin_emp.id,
                'state': 'open',
                'wage': 150000,
            }
            if grade and 'job_grade' in env['hr.contract']._fields:
                contract_vals['job_grade'] = grade.id
            env['hr.contract'].create(contract_vals)
            print("Created Admin Contract.")
    else:
        print("hr_contract module not installed. Skipping contract creation.")

    # 2. Create Test Employees and Users
    test_users_data = [
        {'name': 'Abebe Kebede', 'login': 'abebe', 'password': '123', 'wage': 80000, 'dept': 'IT Department'},
        {'name': 'Chala Lema', 'login': 'chala', 'password': '123', 'wage': 65000, 'dept': 'HR Department'},
    ]

    for data in test_users_data:
        # Create Department
        dept = env['hr.department'].search([('name', '=', data['dept'])], limit=1)
        if not dept:
            dept = env['hr.department'].create({'name': data['dept']})

        # Create User
        user = env['res.users'].search([('login', '=', data['login'])], limit=1)
        if not user:
            user = env['res.users'].create({
                'name': data['name'],
                'login': data['login'],
                'password': data['password'],
            })
            print(f"Created User: {user.login}")

        # Create Employee
        emp = env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        if not emp:
            emp_vals = {
                'name': data['name'],
                'user_id': user.id,
                'department_id': dept.id,
            }
            if grade and 'job_grade' in env['hr.employee']._fields:
                emp_vals['job_grade'] = grade.id
            emp = env['hr.employee'].create(emp_vals)
            print(f"Created Employee: {emp.name}")
        
        # Create Contract
        if 'hr.contract' in env:
            contract = env['hr.contract'].search([('employee_id', '=', emp.id)], limit=1)
            if not contract:
                contract_vals = {
                    'name': f"{data['name']} Contract",
                    'employee_id': emp.id,
                    'state': 'open',
                    'wage': data['wage'],
                }
                if grade and 'job_grade' in env['hr.contract']._fields:
                    contract_vals['job_grade'] = grade.id
                env['hr.contract'].create(contract_vals)
                print(f"Created Contract for {emp.name}.")

    # 3. Create mock past attendances for Admin to populate the chart
    print("Generating mock attendances for the past week...")
    now = datetime.now()
    
    # Delete recent attendances to prevent overlap validation errors
    recent_attendances = env['hr.attendance'].search([
        ('employee_id', '=', admin_emp.id),
        ('check_in', '>=', (now - timedelta(days=10)).strftime('%Y-%m-%d 00:00:00'))
    ])
    if recent_attendances:
        recent_attendances.unlink()

    for i in range(1, 8): # past 7 days
        check_in_date = now - timedelta(days=i)
        
        # Skip Sundays (if desired, but let's add some data anyway to see the chart)
        # If it's Sunday (weekday 6), maybe don't work, but let's add 4 hours
        is_sunday = check_in_date.weekday() == 6
        
        hours_worked = random.randint(3, 5) if is_sunday else random.randint(7, 9)
        minutes_worked = random.randint(0, 59)
        
        # Check in at ~08:30 AM local time, meaning ~05:30 UTC
        check_in = check_in_date.replace(hour=5, minute=random.randint(15, 45), second=0, microsecond=0)
        check_out = check_in + timedelta(hours=hours_worked, minutes=minutes_worked)
        
        env['hr.attendance'].create({
            'employee_id': admin_emp.id,
            'check_in': check_in.strftime('%Y-%m-%d %H:%M:%S'),
            'check_out': check_out.strftime('%Y-%m-%d %H:%M:%S'),
        })

    env.cr.commit()
    print("========================================")
    print("✅ Mock Data Seeded Successfully!")
    print("Users created: 'abebe' / 'chala' (Password for both: '123')")
    print("========================================")

except Exception as e:
    env.cr.rollback()
    print(f"❌ Error during seeding: {str(e)}")
