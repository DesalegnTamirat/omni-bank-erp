from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError


class GenerateEmployeeAttendanceReport(models.TransientModel):
    _name = 'generate.employee.attendance.report'

    date_from = fields.Date(string="Date From")
    date_to = fields.Date(string="Date To")

    def generate(self):
       p_from=self.date_from
       p_to =self.date_to
       print("********************GenerateEmployeeAttendanceReport")
       print ("___________________________Date From", p_from)
       print ("___________________________Date To", p_to)
       cr = self.env.cr
       cr.execute("SELECT populate_employee_attendance_report(%s, %s)", (p_from, p_to))
       cr.commit()
       print("Employee Attendance Report Populated")


