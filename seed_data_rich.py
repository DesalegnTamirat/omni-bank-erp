import random
from datetime import datetime, timedelta, date

def seed_rich_dataset():
    env = globals().get('env')
    print("==================================================")
    print("🚀 Starting Rich Dataset Generation (25+ Employees)")
    print("==================================================")

    # 1. PREREQUISITES
    # Grade
    grade = None
    if 'employee.grade' in env:
        grade = env['employee.grade'].search([], limit=1)
        if not grade:
            try:
                grade = env['employee.grade'].create({})
            except Exception:
                grade = None

    # Locations / Partners
    partners_data = [
        {'name': 'Bunna Bank Head Office', 'city': 'Addis Ababa', 'street': 'Ras Abebe Aregay St'},
        {'name': 'Bole Branch', 'city': 'Addis Ababa', 'street': 'Bole Road'},
        {'name': 'Hawassa Branch', 'city': 'Hawassa', 'street': 'Main Ave'},
        {'name': 'Adama Branch', 'city': 'Adama', 'street': 'Expressway Blvd'},
        {'name': 'Bahir Dar Branch', 'city': 'Bahir Dar', 'street': 'Lake Tana St'},
    ]
    partners = []
    for pd in partners_data:
        p = env['res.partner'].search([('name', '=', pd['name'])], limit=1)
        if not p:
            p = env['res.partner'].create(pd)
        partners.append(p)
    partner_hq = partners[0]

    # Operating Units
    ou_model = env.get('operating.unit')
    ou_hq = None
    if ou_model is not None:
        ou_hq = ou_model.search([], limit=1)

    # Departments
    depts_data = [
        'Executive Office',
        'Human Resources',
        'Information Technology',
        'Finance and Accounting',
        'Retail Banking',
        'Risk and Compliance'
    ]
    depts = {}
    for dname in depts_data:
        d = env['hr.department'].search([('name', '=', dname)], limit=1)
        if not d:
            d_vals = {'name': dname}
            if ou_hq and 'operating_unit_id' in env['hr.department']._fields:
                d_vals['operating_unit_id'] = ou_hq.id
            d = env['hr.department'].create(d_vals)
        depts[dname] = d

    # Job Positions
    jobs_data = [
        ('Chief Executive Officer', depts['Executive Office']),
        ('HR Director', depts['Human Resources']),
        ('HR Officer', depts['Human Resources']),
        ('IT Director', depts['Information Technology']),
        ('Senior Software Engineer', depts['Information Technology']),
        ('Junior Software Engineer', depts['Information Technology']),
        ('Database Administrator', depts['Information Technology']),
        ('Finance Director', depts['Finance and Accounting']),
        ('Senior Accountant', depts['Finance and Accounting']),
        ('Retail Banking Manager', depts['Retail Banking']),
        ('Customer Service Officer', depts['Retail Banking']),
        ('Branch Operations Officer', depts['Retail Banking']),
        ('Risk Analyst', depts['Risk and Compliance']),
    ]
    jobs = {}
    for jtitle, drec in jobs_data:
        j = env['hr.job'].search([('name', '=', jtitle)], limit=1)
        if not j:
            j = env['hr.job'].create({'name': jtitle, 'department_id': drec.id})
        jobs[jtitle] = j

    # Security Groups for Users
    group_user = env.ref('base.group_user', raise_if_not_found=False)
    group_att_user = env.ref('hr_attendance.group_hr_attendance_user', raise_if_not_found=False)
    group_att_manager = env.ref('hr_attendance.group_hr_attendance_officer', raise_if_not_found=False)
    group_hr_manager = env.ref('hr.group_hr_manager', raise_if_not_found=False)

    # 2. DEFINING 25 EMPLOYEES & HIERARCHY
    # Format: (login, name, emp_id, title, dept, salary, gender, role)
    employee_specs = [
        # Executives & Directors (Managers)
        ('admin', 'Administrator', 'EMP-001', 'Chief Executive Officer', 'Executive Office', 220000, 'male', 'top'),
        ('solomon', 'Solomon Kassa Desta', 'EMP-002', 'HR Director', 'Human Resources', 150000, 'male', 'dir'),
        ('meron', 'Meron Hailemariam Tadesse', 'EMP-003', 'IT Director', 'Information Technology', 160000, 'female', 'dir'),
        ('yared', 'Yared Worku Tesfaye', 'EMP-004', 'Finance Director', 'Finance and Accounting', 155000, 'male', 'dir'),
        ('selam', 'Selamawit Gebre Egziabher', 'EMP-005', 'Retail Banking Manager', 'Retail Banking', 140000, 'female', 'dir'),

        # HR Team
        ('abebe', 'Abebe Kebede Lema', 'EMP-006', 'HR Officer', 'Human Resources', 65000, 'male', 'emp'),
        ('chala', 'Chala Lema Wolde', 'EMP-007', 'HR Officer', 'Human Resources', 60000, 'male', 'emp'),
        ('bethel', 'Bethelhem Assefa Zewde', 'EMP-008', 'HR Officer', 'Human Resources', 62000, 'female', 'emp'),

        # IT Team
        ('dawit', 'Dawit Alemu Normal', 'EMP-009', 'Senior Software Engineer', 'Information Technology', 95000, 'male', 'lead'),
        ('hana', 'Hana Tadesse Late', 'EMP-010', 'Junior Software Engineer', 'Information Technology', 55000, 'female', 'emp'),
        ('samuel', 'Samuel Bekele ForcedCO', 'EMP-011', 'Database Administrator', 'Information Technology', 85000, 'male', 'emp'),
        ('tigist', 'Tigist Worku Perfect', 'EMP-012', 'Senior Software Engineer', 'Information Technology', 90000, 'female', 'emp'),
        ('surafel', 'Surafel Girma Belay', 'EMP-013', 'Junior Software Engineer', 'Information Technology', 50000, 'male', 'emp'),
        ('marta', 'Marta Yosef Kebede', 'EMP-014', 'Junior Software Engineer', 'Information Technology', 52000, 'female', 'emp'),

        # Finance Team
        ('kebede', 'Kebede Mengistu Fikru', 'EMP-015', 'Senior Accountant', 'Finance and Accounting', 75000, 'male', 'lead'),
        ('hiwot', 'Hiwot Mulugeta Desta', 'EMP-016', 'Senior Accountant', 'Finance and Accounting', 72000, 'female', 'emp'),
        ('eyob', 'Eyob Tekle Berhan', 'EMP-017', 'Senior Accountant', 'Finance and Accounting', 70000, 'male', 'emp'),

        # Retail Banking Team
        ('tinsae', 'Tinsae Getachew Alemu', 'EMP-018', 'Customer Service Officer', 'Retail Banking', 45000, 'male', 'emp'),
        ('eden', 'Eden Bogale Workneh', 'EMP-019', 'Customer Service Officer', 'Retail Banking', 44000, 'female', 'emp'),
        ('khalid', 'Khalid Ahmed Hassan', 'EMP-020', 'Branch Operations Officer', 'Retail Banking', 58000, 'male', 'emp'),
        ('rahel', 'Rahel Solomon Tessema', 'EMP-021', 'Customer Service Officer', 'Retail Banking', 46000, 'female', 'emp'),
        ('yonas', 'Yonas Berhanu Kidane', 'EMP-022', 'Branch Operations Officer', 'Retail Banking', 60000, 'male', 'emp'),

        # Risk & Compliance
        ('biniam', 'Biniam Million Hailu', 'EMP-023', 'Risk Analyst', 'Risk and Compliance', 80000, 'male', 'lead'),
        ('senait', 'Senait Negash Woldu', 'EMP-024', 'Risk Analyst', 'Risk and Compliance', 78000, 'female', 'emp'),
        ('tariku', 'Tariku Abera Demissie', 'EMP-025', 'Risk Analyst', 'Risk and Compliance', 76000, 'male', 'emp'),
    ]

    created_employees = {}
    created_users = {}

    # Map Directors
    dir_map = {
        'Executive Office': 'admin',
        'Human Resources': 'solomon',
        'Information Technology': 'meron',
        'Finance and Accounting': 'yared',
        'Retail Banking': 'selam',
        'Risk and Compliance': 'admin',
    }

    print(f"Creating {len(employee_specs)} full employee profiles...")

    for login, full_name, emp_code, job_title, dept_name, salary, gender, role in employee_specs:
        # Create User — skip for admin (already exists)
        if login == 'admin':
            user = env.ref('base.user_admin')
            created_users[login] = user
            emp = user.employee_id
            if not emp:
                emp = env['hr.employee'].search([('name', '=', full_name)], limit=1)
            created_employees[login] = emp or env['hr.employee'].browse()
            continue

        user = env['res.users'].search([('login', '=', login)], limit=1)
        if not user:
            user_vals = {
                'name': full_name,
                'login': login,
                'password': '123',
            }
            user = env['res.users'].with_context(no_reset_password=True, mail_create_nolog=True, mail_create_nosubscribe=True).create(user_vals)
            user.email = f"{login}@bunnabank.et"

            # Assign Groups via SQL to bypass audit_trail patch
            base_group_ids = []
            if group_user: base_group_ids.append(group_user.id)
            if role in ('top', 'dir'):
                if group_att_manager: base_group_ids.append(group_att_manager.id)
                if group_hr_manager: base_group_ids.append(group_hr_manager.id)
            else:
                if group_att_user: base_group_ids.append(group_att_user.id)
            for gid in base_group_ids:
                env.cr.execute(
                    "INSERT INTO res_groups_users_rel (gid, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (gid, user.id)
                )

        created_users[login] = user

        # Employee Record
        emp = env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        if not emp:
            emp = env['hr.employee'].search([('name', '=', full_name)], limit=1)

        loc = random.choice(partners)
        emp_vals = {
            'name': full_name,
            'user_id': user.id,
            'department_id': depts[dept_name].id,
            'job_id': jobs[job_title].id,
            'job_title': job_title,
            'work_email': f"{login}@bunnabank.et",
            'work_phone': f"+251 11 5{random.randint(100,999)} {random.randint(1000,9999)}",
            'mobile_phone': f"+251 9{random.randint(10,99)} {random.randint(100,999)} {random.randint(100,999)}",
            'address_id': loc.id,
            'work_contact_id': loc.id,
            'active': True,
        }

        # Handle custom fields dynamically if they exist on model
        fields_dict = env['hr.employee']._fields
        if 'employee_identification' in fields_dict:
            emp_vals['employee_identification'] = emp_code
        if 'identification_id' in fields_dict:
            emp_vals['identification_id'] = emp_code
        if 'gender' in fields_dict:
            emp_vals['gender'] = gender
        if 'sex' in fields_dict:
            emp_vals['sex'] = gender
        if 'personal_email' in fields_dict:
            emp_vals['personal_email'] = f"{login}.personal@gmail.com"
        if 'private_email' in fields_dict:
            emp_vals['private_email'] = f"{login}.private@gmail.com"
        if 'personal_phone' in fields_dict:
            emp_vals['personal_phone'] = f"+251 911 {random.randint(100000,999999)}"
        if 'service_start_date' in fields_dict:
            emp_vals['service_start_date'] = date(2023, random.randint(1,12), random.randint(1,28))
        if 'start_date' in fields_dict:
            emp_vals['start_date'] = date(2023, random.randint(1,12), random.randint(1,28))
        if grade and 'job_grade' in fields_dict:
            emp_vals['job_grade'] = grade.id

        if not emp:
            emp = env['hr.employee'].create(emp_vals)
        else:
            emp.write(emp_vals)

        created_employees[login] = emp

        # Contract
        if 'hr.contract' in env:
            contract = env['hr.contract'].search([('employee_id', '=', emp.id)], limit=1)
            c_vals = {
                'name': f"Contract - {full_name}",
                'employee_id': emp.id,
                'job_id': jobs[job_title].id,
                'department_id': depts[dept_name].id,
                'wage': salary,
                'state': 'open',
                'date_start': date(2023, 1, 1),
            }
            if grade and 'job_grade' in env['hr.contract']._fields:
                c_vals['job_grade'] = grade.id

            if not contract:
                env['hr.contract'].create(c_vals)
            else:
                contract.write(c_vals)

    # Set Managers & Hierarchy
    print("Linking Manager Hierarchy...")
    for login, full_name, emp_code, job_title, dept_name, salary, gender, role in employee_specs:
        emp = created_employees[login]
        mgr_login = dir_map.get(dept_name)
        if mgr_login and mgr_login != login:
            mgr_emp = created_employees.get(mgr_login)
            if mgr_emp:
                emp.write({
                    'parent_id': mgr_emp.id,
                    'coach_id': mgr_emp.id,
                })

    # 3. SEED DIVERSE ATTENDANCE RECORDS (Past 21 Days)
    print("Generating 3 weeks of realistic attendance records...")
    now = datetime.now()
    
    # Clean old attendances to ensure zero conflicts
    env['hr.attendance'].search([]).unlink()

    for day_offset in range(1, 22):
        att_date = now - timedelta(days=day_offset)
        if att_date.weekday() == 6: # Skip Sunday
            continue

        for login, emp in created_employees.items():
            # Randomize attendance scenario
            scenario_choice = random.choices(
                ['normal', 'late', 'early_exit', 'force_co'],
                weights=[60, 20, 10, 10]
            )[0]

            base_start_hour = 5 # 8:00 AM local EAT is 5:00 UTC
            
            if scenario_choice == 'normal':
                check_in = att_date.replace(hour=base_start_hour, minute=random.randint(0, 15), second=0)
                check_out = check_in + timedelta(hours=9, minutes=random.randint(0, 30))
            elif scenario_choice == 'late':
                check_in = att_date.replace(hour=base_start_hour + random.randint(0, 1), minute=random.randint(31, 59), second=0)
                check_out = check_in + timedelta(hours=8, minutes=random.randint(0, 20))
            elif scenario_choice == 'early_exit':
                check_in = att_date.replace(hour=base_start_hour, minute=random.randint(0, 10), second=0)
                check_out = check_in + timedelta(hours=5) # Left early
            elif scenario_choice == 'force_co':
                check_in = att_date.replace(hour=base_start_hour, minute=random.randint(0, 10), second=0)
                check_out = check_in + timedelta(hours=14) # Force checkout limit

            vals = {
                'employee_id': emp.id,
                'check_in': check_in.strftime('%Y-%m-%d %H:%M:%S'),
                'check_out': check_out.strftime('%Y-%m-%d %H:%M:%S'),
            }
            env['hr.attendance'].create(vals)

    # 4. SEED DISCIPLINE CASES
    disc_case_model = env.get('discipline.case') or env.get('disciplinary.case')
    if disc_case_model is not None:
        print("Seeding Disciplinary Cases...")
        # Create cases for Hana (late) and Samuel (force checkout)
        hana_emp = created_employees.get('hana')
        samuel_emp = created_employees.get('samuel')

        if hana_emp:
            try:
                disc_case_model.create({
                    'name': 'CASE-2026-001',
                    'employee_id': hana_emp.id,
                    'department_id': hana_emp.department_id.id,
                    'reason': 'Repeated Lateness Violation (3 late check-ins recorded)',
                })
            except Exception as e:
                print(f"Skipped creating discipline case for Hana: {e}")

        if samuel_emp:
            try:
                disc_case_model.create({
                    'name': 'CASE-2026-002',
                    'employee_id': samuel_emp.id,
                    'department_id': samuel_emp.department_id.id,
                    'reason': 'Repeated Force Checkout Violation (2 unclosed sessions)',
                })
            except Exception as e:
                print(f"Skipped creating discipline case for Samuel: {e}")

    # Sync all attendance states
    for emp in created_employees.values():
        emp.attendance_state = 'checked_out'

    env.cr.commit()
    print("==================================================")
    print("✅ Rich Dataset Successfully Generated!")
    print(f"Total Employees: {len(created_employees)}")
    print("All logins configured with password: '123'")
    print("==================================================")

if __name__ == '__main__':
    seed_rich_dataset()
