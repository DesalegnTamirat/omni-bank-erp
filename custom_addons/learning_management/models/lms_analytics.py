# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class LmsBranchComplianceReport(models.Model):
    """
    Branch & Operating Unit Compliance Matrix (FR-LMS-023, FR-LMS-024, FR-LMS-025).
    Aggregates training enrollments, completions, and compliance percentage by Operating Unit and Course.
    """
    _name = 'lms.branch.compliance.report'
    _description = 'Branch LMS Compliance Matrix'
    _auto = False
    _order = 'operating_unit_id, course_id'

    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit / Branch', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    course_id = fields.Many2one('lms.course', string='Mandatory Course', readonly=True)
    is_mandatory = fields.Boolean(string='Mandatory', readonly=True)

    total_assigned = fields.Integer(string='Total Assigned', readonly=True)
    total_completed = fields.Integer(string='Completed', readonly=True)
    total_in_progress = fields.Integer(string='In Progress', readonly=True)
    total_overdue = fields.Integer(string='Overdue', readonly=True)
    compliance_percentage = fields.Float(string='Compliance Rate (%)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    row_number() OVER () AS id,
                    e.default_operating_unit_id AS operating_unit_id,
                    e.department_id AS department_id,
                    en.course_id AS course_id,
                    en.is_mandatory AS is_mandatory,
                    COUNT(en.id) AS total_assigned,
                    COUNT(CASE WHEN en.state = 'completed' THEN 1 END) AS total_completed,
                    COUNT(CASE WHEN en.state = 'in_progress' THEN 1 END) AS total_in_progress,
                    COUNT(CASE WHEN en.is_overdue = true THEN 1 END) AS total_overdue,
                    CASE 
                        WHEN COUNT(en.id) > 0 THEN 
                            ROUND((COUNT(CASE WHEN en.state = 'completed' THEN 1 END)::numeric / COUNT(en.id)::numeric) * 100.0, 2)
                        ELSE 0.0 
                    END AS compliance_percentage
                FROM lms_enrollment en
                JOIN hr_employee e ON e.id = en.employee_id
                GROUP BY e.default_operating_unit_id, e.department_id, en.course_id, en.is_mandatory
            )
        """)
