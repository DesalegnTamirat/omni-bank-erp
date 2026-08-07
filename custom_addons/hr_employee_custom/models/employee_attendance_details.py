# -*- coding: utf-8 -*-

from odoo import models, fields,api
from odoo import tools


class EmployeeAttendanceDetails(models.Model):
    _name = 'employee.attendance.details'
    _description = 'Employee Attendance Details'

    employee_id=fields.Many2one("hr.employee",string="Employee ID", readonly=1)
    employee_name=fields.Char(string="Employee Name", readonly=1)
    emp_number=fields.Char(string="Emp Number", readonly=1)
    job_position=fields.Char(string="Job Position", readonly=1)
    emp_grade=fields.Char(string="Grade", readonly=1)
    work_unit =fields.Char(string="Work Unit", readonly=1)
    manager_name=fields.Char(string="Manager Name", readonly=1)
    attendance_month=fields.Char(string="Attendance Month", readonly=1)
    checkin_date=fields.Char(string="Checkin Date", readonly=1)
    checkin_time=fields.Char(string="Checkin Time", readonly=1)
    checkout_time = fields.Char(string="Checkout Time", readonly=1)
    worked_hours = fields.Char(string="Worked Hours", readonly=1)
    remarks = fields.Char(string="Checkout Remarks", readonly=1)
