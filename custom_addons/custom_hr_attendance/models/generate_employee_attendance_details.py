from odoo import models, fields, api, tools

class GenerateEmployeeAttendanceDetails(models.Model):
    _name = "generate.employee.attendance.details"
    _description = "Generated Employee Attendance Details"

    employee_id = fields.Many2one("hr.employee", string="Employee")
    employee_identification = fields.Char(string="Emp Number", required=True)
    employee_name = fields.Char(string="Employee Name")

    job_title = fields.Char(string="Job Position")
    job_grade = fields.Char(string="Grade")
    place_of_assignment = fields.Char(string="Place of Assignment")
    work_unit = fields.Char(string="Work Unit")
    manager_name = fields.Char(string="Manager Name")

    attendance_month = fields.Char(string="Attendance Month")
    checkin_date = fields.Date(string="Checkin Date")
    checkin_time = fields.Datetime(string="Checkin Time")
    checkout_time = fields.Datetime(string="Checkout Time")
    remarks = fields.Char(string="Remarks")

    worked_hours = fields.Float(string="Worked Hours")
    payable_hours = fields.Float(string="Total Compensable (Hours)")
    leave_hours = fields.Float(string="Leave Hours")
    late_time_hour = fields.Float(string="Late Time (Hours)")
    early_exit_hour = fields.Float(string="Early Exit (Hours)")
    over_time_hour = fields.Float(string="Overtime (Hours)")

    pre_defined = fields.Float(string="Pre-Defined Lateness")
    acknowledged_lateness = fields.Float(string="Acknowledged Lateness")
    technical_issue = fields.Float(string="Technical Issue")
    pre_approved_early_checkout = fields.Float(string="Pre-Approved Early Checkout")
    acknowledged_early_checkout = fields.Float(string="Acknowledged Early Checkout")
    force_checkout = fields.Integer(string="Force Checkout")
    working_hours = fields.Float(string="Working Hours")
    attendance_percentage = fields.Float(string="Attendance Percentage")
    absent_hours = fields.Float(string="Absent Hours")

    @api.onchange('employee_identification')
    def _onchange_employee_identification(self):
        for rec in self:
            if not rec.employee_identification:
                rec.employee_id = False
                rec.employee_name = False
                rec.place_of_assignment = False
                rec.work_unit = False
                rec.job_title = False
                return

            employee = self.env['hr.employee'].search(
                [('employee_identification', '=', rec.employee_identification)],
                limit=1
            )

            if not employee:
                rec.employee_id = False
                rec.employee_name = False
                rec.place_of_assignment = False
                rec.work_unit = False
                rec.job_title = False


            # Hidden FK
            rec.employee_id = employee.id

            # Auto-filled data
            rec.employee_name = employee.name
            rec.job_title = employee.job_position.name if employee.job_position else False

            if employee.default_operating_unit_id:
                ou = employee.default_operating_unit_id
                rec.place_of_assignment = ou.name
                rec.work_unit = ou.name
            else:
                rec.place_of_assignment = False
                rec.work_unit = False

    def init(self):
        """
        Odoo standard initialization hook to create/replace PostgreSQL stored functions
        automatically upon module installation and upgrade.
        """
        tools.drop_view_if_exists(self.env.cr, 'generate_detail_employee_attendance_report')
        sql = """
        CREATE OR REPLACE FUNCTION generate_daily_employee_attendance_detail_report(
            p_from DATE,
            p_to DATE,
            p_report_type VARCHAR
        ) RETURNS VOID AS $$
        BEGIN
            -- Clear previous results for clean report generation
            TRUNCATE TABLE generate_employee_attendance_details;

            IF p_report_type = 'attendance_summary' THEN
                INSERT INTO generate_employee_attendance_details (
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
                    working_hours,
                    attendance_percentage,
                    absent_hours,
                    create_date,
                    write_date
                )
                SELECT 
                    emp.id AS employee_id,
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name, '') AS employee_name,
                    COALESCE(ou.name, '') AS place_of_assignment,
                    COALESCE(ou.name, '') AS work_unit,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(SUM(att.worked_hours), 0.0) AS worked_hours,
                    (COALESCE(SUM(att.worked_hours), 0.0) 
                     + COALESCE(leave_agg.total_leave_hours, 0.0)
                     + COALESCE(SUM(att.pre_defined_lateness), 0.0) 
                     + COALESCE(SUM(att.pre_approved_early_checkout), 0.0) 
                     + COALESCE(SUM(att.acknowledged_late), 0.0) 
                     + COALESCE(SUM(att.acknowledged_exit), 0.0)) AS payable_hours,
                    COALESCE(leave_agg.total_leave_hours, 0.0) AS leave_hours,
                    COALESCE(SUM(att.late_time_hour), 0.0) AS late_time_hour,
                    COALESCE(SUM(att.early_exit_hour), 0.0) AS early_exit_hour,
                    COALESCE(SUM(att.over_time_hour), 0.0) AS over_time_hour,
                    COALESCE(SUM(att.pre_defined_lateness), 0.0) AS pre_defined,
                    COALESCE(SUM(att.acknowledged_late), 0.0) AS acknowledged_lateness,
                    COALESCE(SUM(att.pre_approved_early_checkout), 0.0) AS pre_approved_early_checkout,
                    COALESCE(SUM(att.acknowledged_exit), 0.0) AS acknowledged_early_checkout,
                    COUNT(CASE WHEN att.check_out_status = 'Force Checkout' OR att.is_force_checkout = TRUE THEN 1 END) AS force_checkout,
                    COALESCE(exp_wh.total_wh, 0.0) AS working_hours,
                    CASE 
                        WHEN COALESCE(exp_wh.total_wh, 0.0) > 0 THEN 
                            ROUND(CAST((LEAST(exp_wh.total_wh, 
                                COALESCE(SUM(att.worked_hours), 0.0) 
                                + COALESCE(leave_agg.total_leave_hours, 0.0)
                                + COALESCE(SUM(att.pre_defined_lateness), 0.0) 
                                + COALESCE(SUM(att.pre_approved_early_checkout), 0.0) 
                                + COALESCE(SUM(att.acknowledged_late), 0.0) 
                                + COALESCE(SUM(att.acknowledged_exit), 0.0)
                            ) / exp_wh.total_wh) * 100 AS numeric), 2)
                        ELSE 0.0 
                    END AS attendance_percentage,
                    GREATEST(0.0, COALESCE(exp_wh.total_wh, 0.0) - (
                        COALESCE(SUM(att.worked_hours), 0.0) 
                        + COALESCE(leave_agg.total_leave_hours, 0.0)
                        + COALESCE(SUM(att.pre_defined_lateness), 0.0) 
                        + COALESCE(SUM(att.pre_approved_early_checkout), 0.0) 
                        + COALESCE(SUM(att.acknowledged_late), 0.0) 
                        + COALESCE(SUM(att.acknowledged_exit), 0.0)
                    )) AS absent_hours,
                    NOW(),
                    NOW()
                FROM hr_employee emp
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_attendance att ON att.employee_id = emp.id 
                    AND att.check_in >= p_from::timestamp 
                    AND att.check_in <= (p_to + interval '1 day')::timestamp
                    AND (att.active = TRUE OR att.active IS NULL)
                LEFT JOIN LATERAL (
                    SELECT SUM(
                        CASE 
                            WHEN l.number_of_days > 0 THEN l.number_of_days * 8.0
                            WHEN l.number_of_hours > 0 THEN l.number_of_hours
                            ELSE 8.0
                        END
                    ) AS total_leave_hours
                    FROM hr_leave l
                    WHERE l.employee_id = emp.id
                      AND l.state = 'validate'
                      AND l.date_from::date <= p_to
                      AND l.date_to::date >= p_from
                ) leave_agg ON TRUE
                LEFT JOIN LATERAL (
                    SELECT SUM(
                        COALESCE(
                            -- 1. Check Approved Leave (hr_leave) on this date
                            (
                                SELECT 0.0
                                FROM hr_leave l
                                WHERE l.employee_id = emp.id
                                  AND l.state = 'validate'
                                  AND l.date_from::date <= d::date
                                  AND l.date_to::date >= d::date
                                LIMIT 1
                            ),
                            -- 2. Check Date-based Roster Exception (job_position_roster_exception_line)
                            (
                                SELECT CASE 
                                    WHEN rl.schedule_type = 'day_off' THEN 0.0
                                    WHEN js.id IS NOT NULL THEN 
                                        GREATEST(0.0, (js.end_time - js.start_time) - CASE WHEN js.has_lunch_break THEN COALESCE(js.lunch_duration, 1.0) ELSE 0.0 END)
                                    ELSE 8.0
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
                                WHEN EXTRACT(DOW FROM d) = 6 THEN (CASE WHEN ou.work_unit_type IN ('head_office', 'district') THEN 4.0 ELSE 8.0 END)
                                ELSE 0.0
                            END
                        )
                    ) AS total_wh
                    FROM generate_series(p_from, p_to, '1 day'::interval) d
                ) exp_wh ON TRUE
                WHERE emp.active = TRUE
                GROUP BY emp.id, emp.employee_identification, emp.name, ou.name, ou.work_unit_type, job.id, job.name, exp_wh.total_wh, leave_agg.total_leave_hours;

            ELSE
                -- Daily Employee Attendance Detail mode (per-attendance row)
                INSERT INTO generate_employee_attendance_details (
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
                    working_hours,
                    create_date,
                    write_date
                )
                SELECT 
                    emp.id AS employee_id,
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name, '') AS employee_name,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(CAST(emp.job_position AS VARCHAR), 'XIV') AS job_grade,
                    COALESCE(ou.name, '') AS place_of_assignment,
                    COALESCE(ou.name, '') AS work_unit,
                    COALESCE(mgr.name, '') AS manager_name,
                    TO_CHAR(att.check_in, 'Mon-YYYY') AS attendance_month,
                    att.check_in::date AS checkin_date,
                    att.check_in AS checkin_time,
                    att.check_out AS checkout_time,
                    COALESCE(att.check_in_status, att.check_out_status, '') AS remarks,
                    COALESCE(att.worked_hours, 0.0) AS worked_hours,
                    (COALESCE(att.worked_hours, 0.0) 
                     + COALESCE(att.pre_defined_lateness, 0.0) 
                     + COALESCE(att.pre_approved_early_checkout, 0.0) 
                     + COALESCE(att.acknowledged_late, 0.0) 
                     + COALESCE(att.acknowledged_exit, 0.0)) AS payable_hours,
                    COALESCE(att.late_time_hour, 0.0) AS late_time_hour,
                    COALESCE(att.early_exit_hour, 0.0) AS early_exit_hour,
                    COALESCE(att.over_time_hour, 0.0) AS over_time_hour,
                    COALESCE(att.pre_defined_lateness, 0.0) AS pre_defined,
                    COALESCE(att.acknowledged_late, 0.0) AS acknowledged_lateness,
                    COALESCE(att.pre_approved_early_checkout, 0.0) AS pre_approved_early_checkout,
                    COALESCE(att.acknowledged_exit, 0.0) AS acknowledged_early_checkout,
                    CASE WHEN att.check_out_status = 'Force Checkout' OR att.is_force_checkout = TRUE THEN 1 ELSE 0 END AS force_checkout,
                    COALESCE(att.worked_hours, 0.0) AS working_hours,
                    NOW(),
                    NOW()
                FROM hr_attendance att
                JOIN hr_employee emp ON att.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_employee mgr ON emp.parent_id = mgr.id
                WHERE att.check_in >= p_from::timestamp 
                  AND att.check_in <= (p_to + interval '1 day')::timestamp
                  AND (att.active = TRUE OR att.active IS NULL)
                  AND emp.active = TRUE;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
        self.env.cr.execute(sql)

