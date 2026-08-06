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
                rec.work_unit = (
                    "Head office"
                    if ou.work_unit_type == 'head_office'
                    else ou.name
                )
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
                    COALESCE(ou.name, '') AS place_of_assignment,
                    CASE 
                        WHEN ou.work_unit_type = 'head_office' THEN 'Head office'
                        ELSE COALESCE(ou.name, '')
                    END AS work_unit,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(SUM(att.worked_hours), 0.0) AS worked_hours,
                    COALESCE(SUM(att.late_time_hour), 0.0) AS late_time_hour,
                    COALESCE(SUM(att.early_exit_hour), 0.0) AS early_exit_hour,
                    COALESCE(SUM(att.over_time_hour), 0.0) AS over_time_hour,
                    COALESCE(SUM(att.pre_defined_lateness), 0.0) AS pre_defined,
                    COALESCE(SUM(att.acknowledged_late), 0.0) AS acknowledged_lateness,
                    COALESCE(SUM(att.pre_approved_early_checkout), 0.0) AS pre_approved_early_checkout,
                    COALESCE(SUM(att.acknowledged_exit), 0.0) AS acknowledged_early_checkout,
                    COUNT(CASE WHEN att.check_out_status = 'Force Checkout' OR att.is_force_checkout = TRUE THEN 1 END) AS force_checkout,
                    COALESCE(SUM(att.worked_hours), 0.0) AS working_hours,
                    NOW(),
                    NOW()
                FROM hr_employee emp
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_attendance att ON att.employee_id = emp.id 
                    AND att.check_in >= p_from::timestamp 
                    AND att.check_in <= (p_to + interval '1 day')::timestamp
                    AND (att.active = TRUE OR att.active IS NULL)
                WHERE emp.active = TRUE
                GROUP BY emp.id, emp.employee_identification, emp.name, ou.name, ou.work_unit_type, job.id, job.name;

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
                    CASE 
                        WHEN ou.work_unit_type = 'head_office' THEN 'Head office'
                        ELSE COALESCE(ou.name, '')
                    END AS work_unit,
                    COALESCE(mgr.name, '') AS manager_name,
                    TO_CHAR(att.check_in, 'Mon-YYYY') AS attendance_month,
                    att.check_in::date AS checkin_date,
                    att.check_in AS checkin_time,
                    att.check_out AS checkout_time,
                    COALESCE(att.check_in_status, att.check_out_status, '') AS remarks,
                    COALESCE(att.worked_hours, 0.0) AS worked_hours,
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

