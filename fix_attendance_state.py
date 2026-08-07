admin_emp = env.ref('base.user_admin').employee_id
print("Admin Employee:", admin_emp.name if admin_emp else "None")
if admin_emp:
    print("Admin attendance_state field:", admin_emp.attendance_state)
    print("Admin last_attendance_id:", admin_emp.last_attendance_id)
    if admin_emp.last_attendance_id:
        print("  check_in:", admin_emp.last_attendance_id.check_in)
        print("  check_out:", admin_emp.last_attendance_id.check_out)
    
    open_atts = env['hr.attendance'].search([('employee_id', '=', admin_emp.id), ('check_out', '=', False)])
    print("Open attendances count:", len(open_atts))
    for att in open_atts:
        print("  ID:", att.id, "check_in:", att.check_in)

# Sync all employees attendance_state with their actual last_attendance
for emp in env['hr.employee'].search([]):
    last_att = env['hr.attendance'].search([('employee_id', '=', emp.id)], order='check_in desc', limit=1)
    if last_att and not last_att.check_out:
        if hasattr(last_att, 'lunch_out') and last_att.lunch_out and not getattr(last_att, 'lunch_in', False):
            emp.attendance_state = 'lunch_out'
        else:
            emp.attendance_state = 'checked_in'
    else:
        emp.attendance_state = 'checked_out'

env.cr.commit()
print("Synced all employees attendance_state!")
