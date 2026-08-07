admin_emp = env.ref('base.user_admin').employee_id
atts = env['hr.attendance'].search([('employee_id', '=', admin_emp.id)], order='check_in asc')
print(f"Total attendances for Admin ({admin_emp.name}): {len(atts)}")
for a in atts:
    print(f"  ID: {a.id} | check_in: {a.check_in} | check_out: {a.check_out}")
