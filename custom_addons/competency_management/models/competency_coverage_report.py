# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class CompetencyCoverageReport(models.Model):
    """Competency mapping coverage report identifying unmapped roles and job families (FR-MAP-007)."""
    _name = 'competency.coverage.report'
    _description = 'Competency Mapping Coverage Report'
    _auto = False
    _order = 'job_id'

    job_id = fields.Many2one('hr.job', string='Job Position', readonly=True)
    job_name = fields.Char(string='Job Position Name', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    mapping_status = fields.Selection([
        ('mapped', 'Approved Mapping'),
        ('draft', 'Draft Mapping'),
        ('unmapped', 'Unmapped / Missing'),
    ], string='Coverage Status', readonly=True)
    active_version = fields.Char(string='Active Version', readonly=True)
    mapped_competencies_count = fields.Integer(string='Mapped Competencies', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW competency_coverage_report AS (
                SELECT
                    j.id AS id,
                    j.id AS job_id,
                    COALESCE(j.name->>'en_US', j.name::text) AS job_name,
                    j.department_id AS department_id,
                    CASE
                        WHEN (SELECT m.state FROM competency_role_mapping m WHERE m.job_position_id = j.id AND m.state = 'approved' ORDER BY m.id DESC LIMIT 1) = 'approved' THEN 'mapped'
                        WHEN EXISTS (SELECT 1 FROM competency_role_mapping m WHERE m.job_position_id = j.id AND m.state IN ('draft', 'under_approval')) THEN 'draft'
                        ELSE 'unmapped'
                    END AS mapping_status,
                    (SELECT m.version FROM competency_role_mapping m WHERE m.job_position_id = j.id AND m.state = 'approved' ORDER BY m.id DESC LIMIT 1) AS active_version,
                    COALESCE((
                        SELECT COUNT(l.id)
                        FROM competency_role_mapping_line l
                        JOIN competency_role_mapping m ON l.mapping_id = m.id
                        WHERE m.job_position_id = j.id AND m.state = 'approved'
                    ), 0) AS mapped_competencies_count
                FROM hr_job j
                WHERE j.active = TRUE
            )
        """)
