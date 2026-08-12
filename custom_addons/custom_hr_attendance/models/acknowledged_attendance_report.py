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

    check_in = fields.Datetime(
        string="Check In",
        readonly=True
    )

    check_out = fields.Datetime(
        string="Check Out",
        readonly=True
    )

    reason_type = fields.Char(
        string="Acknowledged Type",
        readonly=True
    )

    reason_name = fields.Char(
        string="Attendance Reason",
        readonly=True
    )

    acknowledged_by = fields.Char(
        string="Acknowledged By",
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
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name::text, '') AS employee_name,
                    COALESCE(ou.name::text, '') AS place_of_assignment,
                    att.check_in AS check_in,
                    att.check_out AS check_out,
                    COALESCE(att.reason_type, '') AS reason_type,
                    CASE 
                        WHEN pg_typeof(r.name)::text = 'jsonb' THEN COALESCE(r.name->>'en_US', r.name::text, '')
                        ELSE COALESCE(r.name::text, '')
                    END AS reason_name,
                    COALESCE(partner.name::text, '') AS acknowledged_by,
                    att.acknowledged_date AS acknowledged_date
                FROM hr_attendance att
                JOIN hr_employee emp ON att.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
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
                WHERE att.is_acknowledged = TRUE
                   OR att.acknowledged_late > 0
                   OR att.acknowledged_exit > 0
            )
        """)

