from odoo import models, fields, tools


class AttendancepreApprovalReport(models.Model):
    _name = 'attendance.preapproval.report'
    _description = 'PreDefined Attendance Report'
    _auto = False
    _order = 'date desc'

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    employee_identification = fields.Char(string="Employee ID", readonly=True)
    employee_name = fields.Char(string="Employee Name", readonly=True)
    place_of_assignment = fields.Char(string="Place of Assignment", readonly=True)
    work_unit = fields.Char(string="Work Unit", readonly=True)
    shift_name = fields.Char(string="Shift Name", readonly=True)

    exception_type = fields.Char(string="Exception Type", readonly=True)
    approval_reason = fields.Char(string="Approval Reason", readonly=True)
    date = fields.Date(string="Date", readonly=True)
    start_time = fields.Float(string="Start Time", readonly=True)
    end_time = fields.Float(string="End Time", readonly=True)
    duration = fields.Float(string="Duration", readonly=True)
    status = fields.Char(string="Status", readonly=True)
    request_date = fields.Datetime(string="Requested On", readonly=True)
    approved_by = fields.Char(string="Approved By", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW attendance_preapproval_report AS (
                SELECT
                    pa.id AS id,
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
                    COALESCE(pa.shift_name, '') AS shift_name,
                    CASE 
                        WHEN pa.exception_type = 'predefined_late' THEN 'Pre-Defined Lateness'
                        WHEN pa.exception_type = 'predefined_early_exit' THEN 'Pre-Defined Early Exit'
                        ELSE COALESCE(pa.exception_type, '')
                    END AS exception_type,
                    COALESCE(pa.approval_reason, '') AS approval_reason,
                    pa.date AS date,
                    pa.start_time AS start_time,
                    pa.end_time AS end_time,
                    GREATEST(0.0, COALESCE(pa.end_time, 0.0) - COALESCE(pa.start_time, 0.0)) AS duration,
                    COALESCE(pa.state, '') AS status,
                    pa.create_date AS request_date,
                    COALESCE(partner.name::text, '') AS approved_by
                FROM attendance_preapproval pa
                JOIN hr_employee emp ON pa.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_department dept ON emp.department_id = dept.id
                LEFT JOIN res_users usr ON pa.approved_by = usr.id
                LEFT JOIN res_partner partner ON usr.partner_id = partner.id
                WHERE emp.active = TRUE 
                  AND ((emp.employee_identification IS NOT NULL AND emp.employee_identification != '') OR emp.id = 1)
            )
        """)

