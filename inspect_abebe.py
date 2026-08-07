abebe = env['res.users'].search([('login', '=', 'abebe')], limit=1).employee_id
print("Abebe Employee:", abebe.name if abebe else "None")
if abebe:
    print("Abebe attendance_state:", abebe.attendance_state)
    print("Abebe last_attendance_id:", abebe.last_attendance_id)
    if abebe.last_attendance_id:
        print("  last_att check_in:", abebe.last_attendance_id.check_in)
        print("  last_att check_out:", abebe.last_attendance_id.check_out)
    
    open_atts = env['hr.attendance'].search([('employee_id', '=', abebe.id), ('check_out', '=', False)])
    print("Abebe Open Attendances count:", len(open_atts))
    for a in open_atts:
        print(f"  Open Att ID: {a.id} | check_in: {a.check_in} | check_out: {a.check_out}")

    res = env['hr.attendance']._get_employee_info_response(abebe)
    print("Odoo _get_employee_info_response keys/vals for Abebe:")
    for k, v in res.items():
        print(f"  {k}: {v}")
