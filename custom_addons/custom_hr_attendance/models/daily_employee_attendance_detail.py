# -*- coding: utf-8 -*-
from odoo import models, fields, api


class DailyEmployeeAttendanceDetail(models.Model):
    _name = 'daily.employee.attendance.detail'
    _description = 'Daily Employee Attendance Detail'
    _order = 'checkin_date desc, work_unit, employee_name'

    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='cascade', index=True)
    employee_identification = fields.Char(string='Employee ID', index=True)
    employee_name = fields.Char(string='Employee Name', index=True)
    place_of_assignment = fields.Char(string='Place of Assignment')
    work_unit = fields.Char(string='Work Unit', index=True)
    job_title = fields.Char(string='Job Title')
    job_grade = fields.Char(string='Grade')
    manager_name = fields.Char(string='Manager Name')
    attendance_month = fields.Char(string='Attendance Month')

    checkin_date = fields.Date(string='Checkin Date', index=True)
    checkin_time = fields.Datetime(string='Checkin Time')
    checkout_time = fields.Datetime(string='Checkout Time')
    remarks = fields.Char(string='Remarks')

    worked_hours = fields.Float(string='Worked Hours', digits=(16, 2))
    payable_hours = fields.Float(string='Payable Hours', digits=(16, 2))
    late_time_hour = fields.Float(string='Late Time (Hours)', digits=(16, 2))
    early_exit_hour = fields.Float(string='Early Exit (Hours)', digits=(16, 2))
    over_time_hour = fields.Float(string='Overtime (Hours)', digits=(16, 2))

    pre_defined = fields.Float(string='Pre-Defined Lateness', digits=(16, 2))
    acknowledged_lateness = fields.Float(string='Acknowledged Lateness', digits=(16, 2))
    pre_approved_early_checkout = fields.Float(string='Pre-Approved Early Checkout', digits=(16, 2))
    acknowledged_early_checkout = fields.Float(string='Acknowledged Early Checkout', digits=(16, 2))
    force_checkout = fields.Integer(string='Force Checkout')

    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    def _auto_init(self):
        super()._auto_init()
        self.init()

    def init(self):
        """
        Creates or updates the high-performance PostgreSQL stored function
        to generate the Daily Employee Attendance Detail report for a specific user session.
        """
        sql = """
        CREATE OR REPLACE FUNCTION generate_daily_employee_attendance_detail_report(
            p_from DATE,
            p_to DATE,
            p_user_id INTEGER DEFAULT 1
        ) RETURNS VOID AS $$
        BEGIN
            -- Clean clearance for current user to avoid multi-user collision
            DELETE FROM daily_employee_attendance_detail WHERE create_uid = p_user_id;

            INSERT INTO daily_employee_attendance_detail (
                create_uid,
                write_uid,
                employee_id,
                employee_identification,
                employee_name,
                job_title,
                job_grade,
                place_of_assignment,
                work_unit,
                manager_name,
                attendance_month,
                checkin_date,
                checkin_time,
                checkout_time,
                remarks,
                worked_hours,
                payable_hours,
                late_time_hour,
                early_exit_hour,
                over_time_hour,
                pre_defined,
                acknowledged_lateness,
                pre_approved_early_checkout,
                acknowledged_early_checkout,
                force_checkout,
                date_from,
                date_to,
                create_date,
                write_date
            )
            SELECT 
                p_user_id AS create_uid,
                p_user_id AS write_uid,
                emp.id AS employee_id,
                COALESCE(NULLIF(emp.employee_identification, ''), NULLIF(emp.identification_id, ''), emp.id::text) AS employee_identification,
                COALESCE(emp.name, '') AS employee_name,
                CASE 
                    WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                    ELSE COALESCE(job.name::text, '')
                END AS job_title,
                COALESCE(CAST(emp.job_position AS VARCHAR), 'XIV') AS job_grade,
                COALESCE(
                    CASE 
                        WHEN pg_typeof(dept.name)::text = 'jsonb' THEN COALESCE(dept.name->>'en_US', dept.name::text)
                        ELSE dept.name::text 
                    END,
                    ou.name,
                    ''
                ) AS place_of_assignment,
                COALESCE(ou.name, '') AS work_unit,
                COALESCE(mgr.name, '') AS manager_name,
                TO_CHAR(att.check_in, 'Mon-YYYY') AS attendance_month,
                att.check_in::date AS checkin_date,
                att.check_in AS checkin_time,
                att.check_out AS checkout_time,
                COALESCE(att.check_in_status, att.check_out_status, '') AS remarks,
                COALESCE(att.worked_hours, 0.0) AS worked_hours,
                COALESCE(att.worked_hours, 0.0) AS payable_hours,
                COALESCE(att.late_time_hour, 0.0) AS late_time_hour,
                COALESCE(att.early_exit_hour, 0.0) AS early_exit_hour,
                COALESCE(att.over_time_hour, 0.0) AS over_time_hour,
                COALESCE(att.pre_defined_lateness, 0.0) AS pre_defined,
                COALESCE(att.acknowledged_late, 0.0) AS acknowledged_lateness,
                COALESCE(att.pre_approved_early_checkout, 0.0) AS pre_approved_early_checkout,
                COALESCE(att.acknowledged_exit, 0.0) AS acknowledged_early_checkout,
                CASE WHEN att.check_out_status = 'Force Checkout' OR att.is_force_checkout = TRUE THEN 1 ELSE 0 END AS force_checkout,
                p_from AS date_from,
                p_to AS date_to,
                NOW(),
                NOW()
            FROM hr_attendance att
            JOIN hr_employee emp ON att.employee_id = emp.id
            LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
            LEFT JOIN hr_department dept ON emp.department_id = dept.id
            LEFT JOIN hr_job job ON emp.job_position = job.id
            LEFT JOIN hr_employee mgr ON emp.parent_id = mgr.id
            WHERE att.check_in >= p_from::timestamp 
              AND att.check_in <= (p_to + interval '1 day')::timestamp
              AND (att.active = TRUE OR att.active IS NULL)
              AND emp.active = TRUE
              AND (
                  (emp.employee_identification IS NOT NULL AND emp.employee_identification != '')
                  OR (emp.identification_id IS NOT NULL AND emp.identification_id != '')
                  OR emp.id = 1
              );
        END;
        $$ LANGUAGE plpgsql;
        """
        self.env.cr.execute(sql)
