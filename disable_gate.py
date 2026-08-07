params = env['ir.config_parameter'].sudo()
params.set_param('hr_attendance.enable_checkin_gate', 'False')
env.cr.commit()
print("Disabled enable_checkin_gate")
