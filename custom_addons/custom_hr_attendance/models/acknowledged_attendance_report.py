from odoo import models, fields, tools


class AcknowledgedAttendanceReport(models.Model):
    _name = 'acknowledged.attendance.report'
    _description = 'Acknowledged Attendance Report'
    _auto = False
    _order = 'acknowledged_date desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        readonly=True
    )

    employee_identification = fields.Char(
        string="Employee ID",
        readonly=True
    )

    employee_name = fields.Char(
        string="Employee Name",
        readonly=True
    )

    place_of_assignment = fields.Char(
        string="Place of Assignment",
        readonly=True
    )

    work_unit = fields.Char(
        string="Work Unit",
        readonly=True
    )

    check_in = fields.Datetime(
        string="Check In",
        readonly=True
    )

    check_out = fields.Datetime(
        string="Check Out",
        readonly=True
    )

    worked_hours = fields.Float(
        string="Worked Hours",
        readonly=True
    )

    late_time_hour = fields.Float(
        string="Late Time",
        readonly=True
    )

    early_exit_hour = fields.Float(
        string="Early Exit",
        readonly=True
    )

    acknowledged_late = fields.Float(
        string="Acknowledged Late",
        readonly=True
    )

    acknowledged_exit = fields.Float(
        string="Acknowledged Exit",
        readonly=True
    )

    excused_hours = fields.Float(
        string="Excused Hours",
        readonly=True
    )

    reason_type = fields.Char(
        string="Acknowledged Type",
        readonly=True
    )

    entry_type = fields.Selection([
        ('individual', 'Individual'),
        ('batch', 'Batch'),
    ], string="Entry Mode", readonly=True)

    reason_name = fields.Char(
        string="Attendance Reason",
        readonly=True
    )

    acknowledged_by = fields.Char(
        string="Acknowledged By",
        readonly=True
    )

    acknowledged_by_id = fields.Many2one(
        'res.users',
        string="Acknowledged By User",
        readonly=True
    )

    acknowledged_date = fields.Datetime(
        string="Acknowledged Date",
        readonly=True
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW acknowledged_attendance_report AS (
                SELECT
                    att.id AS id,
                    emp.id AS employee_id,
                    COALESCE(NULLIF(emp.employee_identification, ''), NULLIF(emp.identification_id, ''), emp.id::text) AS employee_identification,
                    COALESCE(emp.name::text, '') AS employee_name,
                    COALESCE(
                        CASE 
                            WHEN pg_typeof(dept.name)::text = 'jsonb' THEN COALESCE(dept.name->>'en_US', dept.name::text)
                            ELSE dept.name::text 
                        END,
                        ou.name,
                        ''
                    ) AS place_of_assignment,
                    COALESCE(ou.name::text, '') AS work_unit,
                    att.check_in AS check_in,
                    att.check_out AS check_out,
                    COALESCE(att.worked_hours, 0.0) AS worked_hours,
                    COALESCE(att.late_time_hour, 0.0) AS late_time_hour,
                    COALESCE(att.early_exit_hour, 0.0) AS early_exit_hour,
                    COALESCE(att.acknowledged_late, 0.0) AS acknowledged_late,
                    COALESCE(att.acknowledged_exit, 0.0) AS acknowledged_exit,
                    (COALESCE(att.acknowledged_late, 0.0) + COALESCE(att.acknowledged_exit, 0.0)) AS excused_hours,
                    COALESCE(att.reason_type, '') AS reason_type,
                    CASE 
                        WHEN att.in_mode = 'batch' OR att.out_mode = 'batch' THEN 'batch'
                        ELSE 'individual'
                    END AS entry_type,
                    CASE 
                        WHEN pg_typeof(r.name)::text = 'jsonb' THEN COALESCE(r.name->>'en_US', r.name::text, '')
                        ELSE COALESCE(r.name::text, '')
                    END AS reason_name,
                    COALESCE(partner.name::text, '') AS acknowledged_by,
                    att.acknowledged_by AS acknowledged_by_id,
                    att.acknowledged_date AS acknowledged_date
                FROM hr_attendance att
                JOIN hr_employee emp ON att.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_department dept ON emp.department_id = dept.id
                LEFT JOIN res_users usr ON att.acknowledged_by = usr.id
                LEFT JOIN res_partner partner ON usr.partner_id = partner.id
                LEFT JOIN hr_attendance_reason r ON (
                    r.id = (
                        SELECT hr_attendance_reason_id 
                        FROM hr_attendance_hr_attendance_reason_rel 
                        WHERE hr_attendance_id = att.id 
                        LIMIT 1
                    )
                )
                WHERE (att.is_acknowledged = TRUE
                   OR att.acknowledged_late > 0
                   OR att.acknowledged_exit > 0)
                  AND emp.active = TRUE
                  AND ((emp.employee_identification IS NOT NULL AND emp.employee_identification != '') OR emp.id = 1)
            )
        """)

