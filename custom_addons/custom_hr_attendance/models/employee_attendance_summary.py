# -*- coding: utf-8 -*-
from odoo import models, fields, api


class EmployeeAttendanceSummary(models.Model):
    _name = 'employee.attendance.summary'
    _description = 'Employee Attendance Summary'
    _order = 'work_unit, employee_name'

    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='cascade', index=True)
    employee_identification = fields.Char(string='Employee ID', index=True)
    employee_name = fields.Char(string='Employee Name', index=True)
    place_of_assignment = fields.Char(string='Place of Assignment')
    work_unit = fields.Char(string='Work Unit', index=True)
    job_title = fields.Char(string='Job Title')

    expected_hours = fields.Float(string='Expected Hours', digits=(16, 2))
    worked_hours = fields.Float(string='Worked Hours', digits=(16, 2))
    payable_hours = fields.Float(string='Total Compensable (Hours)', digits=(16, 2))
    attendance_percentage = fields.Float(string='Attendance Percentage', digits=(16, 2))
    leave_hours = fields.Float(string='Leave Hours', digits=(16, 2))
    absent_hours = fields.Float(string='Absent Hours', digits=(16, 2))
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
        to generate the aggregated Employee Attendance Summary for a specific user session.
        """
        sql = """
        CREATE OR REPLACE FUNCTION generate_employee_attendance_summary_report(
            p_from DATE,
            p_to DATE,
            p_user_id INTEGER DEFAULT 1
        ) RETURNS VOID AS $$
        BEGIN
            -- Clean clearance for current user to avoid multi-user collision
            DELETE FROM employee_attendance_summary WHERE create_uid = p_user_id;

            INSERT INTO employee_attendance_summary (
                create_uid,
                write_uid,
                employee_id,
                employee_identification,
                employee_name,
                place_of_assignment,
                work_unit,
                job_title,
                worked_hours,
                payable_hours,
                leave_hours,
                late_time_hour,
                early_exit_hour,
                over_time_hour,
                pre_defined,
                acknowledged_lateness,
                pre_approved_early_checkout,
                acknowledged_early_checkout,
                force_checkout,
                expected_hours,
                attendance_percentage,
                absent_hours,
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
                COALESCE(
                    CASE 
                        WHEN pg_typeof(dept.name)::text = 'jsonb' THEN COALESCE(dept.name->>'en_US', dept.name::text)
                        ELSE dept.name::text 
                    END,
                    ou.name,
                    ''
                ) AS place_of_assignment,
                COALESCE(ou.name, '') AS work_unit,
                CASE 
                    WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                    ELSE COALESCE(job.name::text, '')
                END AS job_title,
                COALESCE(SUM(att.worked_hours), 0.0) AS worked_hours,
                (COALESCE(SUM(att.worked_hours), 0.0) 
                 + COALESCE(leave_agg.total_leave_hours, 0.0)) AS payable_hours,
                COALESCE(leave_agg.total_leave_hours, 0.0) AS leave_hours,
                COALESCE(SUM(att.late_time_hour), 0.0) AS late_time_hour,
                COALESCE(SUM(att.early_exit_hour), 0.0) AS early_exit_hour,
                COALESCE(SUM(att.over_time_hour), 0.0) AS over_time_hour,
                COALESCE(SUM(att.pre_defined_lateness), 0.0) AS pre_defined,
                COALESCE(SUM(att.acknowledged_late), 0.0) AS acknowledged_lateness,
                COALESCE(SUM(att.pre_approved_early_checkout), 0.0) AS pre_approved_early_checkout,
                COALESCE(SUM(att.acknowledged_exit), 0.0) AS acknowledged_early_checkout,
                COUNT(CASE WHEN att.check_out_status = 'Force Checkout' OR att.is_force_checkout = TRUE THEN 1 END) AS force_checkout,
                COALESCE(exp_wh.total_wh, 0.0) AS expected_hours,
                CASE 
                    WHEN COALESCE(exp_wh.total_wh, 0.0) > 0 THEN 
                        ROUND(CAST((LEAST(exp_wh.total_wh, 
                            COALESCE(SUM(att.worked_hours), 0.0) 
                            + COALESCE(leave_agg.total_leave_hours, 0.0)
                        ) / exp_wh.total_wh) * 100 AS numeric), 2)
                    ELSE 0.0 
                END AS attendance_percentage,
                GREATEST(0.0, COALESCE(exp_wh.total_wh, 0.0) - (
                    COALESCE(SUM(att.worked_hours), 0.0) 
                    + COALESCE(leave_agg.total_leave_hours, 0.0)
                )) AS absent_hours,
                p_from AS date_from,
                p_to AS date_to,
                NOW(),
                NOW()
            FROM hr_employee emp
            LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
            LEFT JOIN hr_department dept ON emp.department_id = dept.id
            LEFT JOIN hr_job job ON emp.job_position = job.id
            LEFT JOIN hr_attendance att ON att.employee_id = emp.id 
                AND att.check_in >= p_from::timestamp 
                AND att.check_in <= (p_to + interval '1 day')::timestamp
                AND (att.active = TRUE OR att.active IS NULL)
            LEFT JOIN LATERAL (
                SELECT SUM(
                    CASE 
                        WHEN (
                            COALESCE(l.request_date_to, (l.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date)
                            - COALESCE(l.request_date_from, (l.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) + 1
                        ) <= 0 THEN 0.0
                        ELSE
                            (
                                GREATEST(0, (
                                    LEAST(COALESCE(l.request_date_to, (l.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date), p_to)
                                    - GREATEST(COALESCE(l.request_date_from, (l.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date), p_from) + 1
                                ))::numeric
                                /
                                (
                                    COALESCE(l.request_date_to, (l.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date)
                                    - COALESCE(l.request_date_from, (l.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) + 1
                                )::numeric
                            )
                            *
                            CASE 
                                WHEN l.number_of_hours > 0 THEN l.number_of_hours
                                WHEN l.number_of_days > 0 THEN l.number_of_days * 8.0
                                ELSE 8.0
                            END
                    END
                ) AS total_leave_hours
                FROM hr_leave l
                WHERE l.employee_id = emp.id
                  AND l.state = 'validate'
                  AND COALESCE(l.request_date_from, (l.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) <= p_to
                  AND COALESCE(l.request_date_to, (l.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) >= p_from
            ) leave_agg ON TRUE
            LEFT JOIN LATERAL (
                SELECT SUM(
                    COALESCE(
                        -- 1. Check Public Holiday (company-wide or calendar-wide)
                        (
                            SELECT 0.0
                            FROM resource_calendar_leaves rcl
                            WHERE rcl.resource_id IS NULL
                              AND (rcl.calendar_id IS NULL OR rcl.calendar_id = (SELECT rr.calendar_id FROM resource_resource rr WHERE rr.id = emp.resource_id))
                              AND (rcl.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date <= d::date
                              AND (rcl.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date >= d::date
                            LIMIT 1
                        ),
                        -- 2. Check Roster Exception (job_position_roster_exception_line)
                        (
                            SELECT 
                                CASE 
                                    WHEN rl.schedule_type = 'day_off' THEN 0.0
                                    WHEN rl.schedule_type = 'shift' AND js.id IS NOT NULL THEN 
                                        GREATEST(0.0, (js.end_time - js.start_time) - CASE WHEN js.has_lunch_break THEN COALESCE(js.lunch_duration, 1.0) ELSE 0.0 END)
                                    ELSE NULL
                                END
                            FROM job_position_roster_exception_line rl
                            JOIN job_position_roster_exception re ON rl.roster_id = re.id
                            LEFT JOIN job_shift js ON rl.shift_id = js.id
                            WHERE (rl.employee_id = emp.id OR re.employee_id = emp.id)
                              AND re.status = 'active'
                              AND (re.active = TRUE OR re.active IS NULL)
                              AND rl.date = d::date
                            ORDER BY re.start_date DESC, re.id DESC
                            LIMIT 1
                        ),
                        -- 3. Check Job Position Exception (job_position_exception)
                        (
                            SELECT GREATEST(0.0, (js.end_time - js.start_time) - CASE WHEN js.has_lunch_break THEN COALESCE(js.lunch_duration, 1.0) ELSE 0.0 END)
                            FROM job_position_exception jpe
                            JOIN job_shift js ON jpe.shift_id = js.id
                            WHERE jpe.employee_id = emp.id
                              AND jpe.status = 'active'
                              AND (jpe.active = TRUE OR jpe.active IS NULL)
                              AND jpe.start_date <= d::date
                              AND (jpe.end_date IS NULL OR jpe.end_date >= d::date)
                            ORDER BY jpe.start_date DESC, jpe.id DESC
                            LIMIT 1
                        ),
                        -- 4. Check Location Exception (location_based_exception)
                        (
                            SELECT GREATEST(0.0, (COALESCE(js.end_time, lbe.end_time, 17.0) - COALESCE(js.start_time, lbe.start_time, 8.0)) - CASE WHEN COALESCE(js.has_lunch_break, lbe.has_lunch_break, FALSE) THEN COALESCE(js.lunch_duration, 1.0) ELSE 0.0 END)
                            FROM location_based_exception lbe
                            LEFT JOIN job_shift js ON lbe.shift_id = js.id
                            WHERE (lbe.active = TRUE OR lbe.active IS NULL)
                              AND (lbe.operating_unit = emp.default_operating_unit_id OR lbe.id IN (
                                  SELECT location_exception_id FROM rel_location_exception_operating_unit WHERE operating_unit_id = emp.default_operating_unit_id
                              ))
                              AND lbe.start_date <= d::date
                              AND (lbe.end_date IS NULL OR lbe.end_date >= d::date)
                            LIMIT 1
                        ),
                        -- 5. Default Global Working Calendar
                        CASE 
                            WHEN EXTRACT(DOW FROM d) BETWEEN 1 AND 5 THEN 8.0
                            WHEN EXTRACT(DOW FROM d) = 6 THEN (CASE WHEN ou.work_unit_type IN ('head_office', 'head_offices', 'ho', 'district', 'district_office', 'regional_office') THEN 4.0 ELSE 8.0 END)
                            ELSE 0.0
                        END
                    )
                ) AS total_wh
                FROM generate_series(p_from, p_to, '1 day'::interval) d
            ) exp_wh ON TRUE
            WHERE emp.active = TRUE
              AND (
                  (emp.employee_identification IS NOT NULL AND emp.employee_identification != '')
                  OR (emp.identification_id IS NOT NULL AND emp.identification_id != '')
                  OR emp.id = 1
              )
            GROUP BY emp.id, emp.employee_identification, emp.identification_id, emp.name, dept.id, dept.name, ou.name, ou.work_unit_type, job.id, job.name, exp_wh.total_wh, leave_agg.total_leave_hours;
        END;
        $$ LANGUAGE plpgsql;
        """
        self.env.cr.execute(sql)
