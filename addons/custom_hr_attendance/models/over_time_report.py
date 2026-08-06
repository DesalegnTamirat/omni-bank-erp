from odoo import models, fields, tools


class OverTimeReport(models.Model):
    _name = 'overtime.report'
    _description = 'Over Time Report'
    _auto = False
    _order = 'date desc'

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    employee_identification = fields.Char(string="Employee ID", readonly=True)
    employee_name = fields.Char(string="Employee Name", readonly=True)
    place_of_assignment = fields.Char(string="Place of Assignment", readonly=True)
    work_unit = fields.Char(string="Work Unit", readonly=True)
    job_title = fields.Char(string="Job Title", readonly=True)
    manager_name = fields.Char(string="Manager Name", readonly=True)
    date = fields.Date(string="Date", readonly=True)

    over_time_hours = fields.Float(string="Total Over Time", readonly=True)
    used_hours = fields.Float(string="Used Hours", readonly=True)
    remaining_hours = fields.Float(string="Remaining Hours", readonly=True)
    state = fields.Char(string="Status", readonly=True)

    def init(self):
        self.env.cr.execute(f"DROP TABLE IF EXISTS {self._table} CASCADE;")
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW overtime_report AS (
                SELECT
                    ot.id AS id,
                    emp.id AS employee_id,
                    COALESCE(emp.employee_identification, '') AS employee_identification,
                    COALESCE(emp.name::text, '') AS employee_name,
                    COALESCE(ou.name::text, '') AS place_of_assignment,
                    CASE 
                        WHEN ou.work_unit_type = 'head_office' THEN 'Head office'
                        ELSE COALESCE(ou.name::text, '')
                    END AS work_unit,
                    CASE 
                        WHEN pg_typeof(job.name)::text = 'jsonb' THEN COALESCE(job.name->>'en_US', job.name::text, '')
                        ELSE COALESCE(job.name::text, '')
                    END AS job_title,
                    COALESCE(mgr.name::text, '') AS manager_name,
                    ot.date AS date,
                    COALESCE(ot.over_time_hour, 0.0) AS over_time_hours,
                    COALESCE(ot.used_hours, 0.0) AS used_hours,
                    COALESCE(ot.remaining_hours, 0.0) AS remaining_hours,
                    COALESCE(ot.state, '') AS state
                FROM over_time ot
                JOIN hr_employee emp ON ot.employee_id = emp.id
                LEFT JOIN operating_unit ou ON emp.default_operating_unit_id = ou.id
                LEFT JOIN hr_job job ON emp.job_position = job.id
                LEFT JOIN hr_employee mgr ON emp.parent_id = mgr.id
            )
        """)


