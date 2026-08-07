# -*- coding: utf-8 -*-

from odoo import models, fields,api
from odoo import tools


class StaffAttendanceDetails(models.Model):
    _name = 'staff.attendance.details'
    _auto = False
    _description = 'Staff Attendance Details'

    he_id=fields.Many2one("hr.employee",string="Employee ID", readonly=1)
    emp_num=fields.Char(string="Employee Number", readonly=1)
    employee_name=fields.Char(string="Employee Name", readonly=1)
    manager_name=fields.Char(string="Manager Name", readonly=1)
    job_position=fields.Char(string="Job Position", readonly=1)
    work_unit=fields.Char(string="Work Unit", readonly=1)
    department_name=fields.Char(string="Department Name", readonly=1)
    work_unit=fields.Char(string="Work Unit", readonly=1)
    checkin_time=fields.Date(string="Checkin Time", readonly=1)
    checkout_time =fields.Date(string="Checkout Time", readonly=1)
    worked_hours=fields.Float(string="Worked Hours", readonly=1)
    

    def init(self):
            tools.drop_view_if_exists(self._cr, 'staff_attendance_details')
            self._cr.execute("""
                CREATE OR REPLACE VIEW staff_attendance_details AS (
                select 	row_number() OVER () AS id,he.id he_id, he.employee_identification emp_num, 
                he.name employee_name, he_mgr.name manager_name, hj."name" job_position, ou.name work_unit,hd.name department_name,ha.check_in checkin_time,ha.check_out checkout_time,ha.worked_hours worked_hours 
                from 	hr_employee he, hr_attendance ha , operating_unit ou ,hr_job hj ,hr_department hd ,hr_employee he_mgr
                where  	he.id=ha.employee_id 
                and 	he.job_position =hj.id 
                and 	he.default_operating_unit_id =ou.id
                and 	he.department_id =hd.id
                and 	he.parent_id =he_mgr.id
                order by 1,6
                )
                """)
