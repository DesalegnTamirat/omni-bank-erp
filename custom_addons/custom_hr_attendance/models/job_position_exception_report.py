from odoo import models, fields, tools


class JobPositionExceptionReport(models.Model):
    _name = 'job.position.exception.report'
    _description = 'Job Position Exception Report'
    _auto = False

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    employee_identification = fields.Char(string="Employee ID", readonly=True)
    employee_name = fields.Char(string="Employee Name", readonly=True)
    place_of_assignment = fields.Char(string="Place of Assignment", readonly=True)
    work_unit = fields.Char(string="Work Unit", readonly=True)
    job_title = fields.Char(string="Job Title", readonly=True)
    manager_name = fields.Char(string="Manager Name", readonly=True)

    shift_name = fields.Char(string='Shift Name', readonly=True)
    time_range = fields.Char(string='Time Range', readonly=True)
    day_off = fields.Date(string='Day Off', readonly=True)
    status = fields.Char(string='Status', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW job_position_exception_report AS (
                SELECT
                    jpe.id AS id,
                    emp.id AS employee_id,
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name::text, '') AS employee_name,
                    COALESCE(ou.name::text, '') AS place_of_assignment,
                    COALESCE(ou.name::text, '') AS work_unit,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(mgr.name::text, '') AS manager_name,
                    COALESCE(js.name::text, '') AS shift_name,
                    COALESCE(jpe.time_range, js.time_range, '') AS time_range,
                    jpe.day_off AS day_off,
                    COALESCE(jpe.status, 'active') AS status
                FROM job_position_exception jpe
                JOIN hr_employee emp ON jpe.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_employee mgr ON emp.parent_id = mgr.id
                LEFT JOIN job_shift js ON jpe.shift_id = js.id

                UNION ALL

                SELECT
                    (1000000 + rel.id) AS id,
                    emp.id AS employee_id,
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name::text, '') AS employee_name,
                    COALESCE(ou.name::text, '') AS place_of_assignment,
                    COALESCE(ou.name::text, '') AS work_unit,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(mgr.name::text, '') AS manager_name,
                    COALESCE(js.name::text, 'Roster Shift') AS shift_name,
                    COALESCE(js.time_range, '') AS time_range,
                    rel.date AS day_off,
                    'roster' AS status
                FROM job_position_roster_exception_line rel
                JOIN hr_employee emp ON rel.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_employee mgr ON emp.parent_id = mgr.id
                LEFT JOIN job_shift js ON rel.shift_id = js.id
            )
        """)



