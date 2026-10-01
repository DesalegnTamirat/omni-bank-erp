# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class CompetencyBenchmark(models.Model):
    """Competency Benchmarking against internal/external standards (FR-GAP-009)."""
    _name = 'competency.benchmark'
    _description = 'Competency Benchmark Standard'
    _order = 'competency_id, effective_date desc'

    name = fields.Char(string='Benchmark Title', compute='_compute_name', store=True)
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade',
        domain="[('approved_framework_ids', '!=', False)]")
    source = fields.Selection([
        ('internal', 'Internal Banking Best Practice'),
        ('external', 'External Industry / Global Standard'),
    ], string='Benchmark Source', default='internal', required=True)
    benchmark_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Benchmark Proficiency Level', required=True, default='3')
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, required=True)
    notes = fields.Text(string='Benchmark Details & Rationale')

    @api.depends('competency_id', 'source', 'benchmark_level')
    def _compute_name(self):
        for rec in self:
            cname = rec.competency_id.name if rec.competency_id else _('Unassigned')
            rec.name = _("Benchmark [%s] Level %s (%s)") % (cname, rec.benchmark_level or '3', rec.source or 'Internal')


class CompetencyBenchmarkComparison(models.Model):
    """Competency benchmarking comparison report view comparing employee ratings against benchmarks (FR-GAP-009)."""
    _name = 'competency.benchmark.comparison'
    _description = 'Competency Benchmark Comparison Report'
    _auto = False
    _order = 'department_name, employee_name'

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_name = fields.Char(string='Employee Name', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    department_name = fields.Char(string='Department Name', readonly=True)
    competency_id = fields.Many2one('competency.competency', string='Competency', readonly=True)
    current_level = fields.Integer(string='Current Level', readonly=True)
    required_level = fields.Integer(string='Required Level', readonly=True)
    benchmark_level = fields.Integer(string='Benchmark Level', readonly=True)
    gap_vs_required = fields.Integer(string='Gap vs Role Required', readonly=True)
    gap_vs_benchmark = fields.Integer(string='Gap vs Benchmark', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW competency_benchmark_comparison AS (
                SELECT
                    l.id AS id,
                    e.id AS employee_id,
                    e.name AS employee_name,
                    e.department_id AS department_id,
                    d.name AS department_name,
                    l.competency_id AS competency_id,
                    CAST(l.current_level AS INTEGER) AS current_level,
                    CAST(l.required_level AS INTEGER) AS required_level,
                    COALESCE(CAST((
                        SELECT b.benchmark_level 
                        FROM competency_benchmark b 
                        WHERE b.competency_id = l.competency_id 
                        ORDER BY b.effective_date DESC LIMIT 1
                    ) AS INTEGER), CAST(l.required_level AS INTEGER)) AS benchmark_level,
                    (CAST(l.required_level AS INTEGER) - CAST(l.current_level AS INTEGER)) AS gap_vs_required,
                    (COALESCE(CAST((
                        SELECT b.benchmark_level 
                        FROM competency_benchmark b 
                        WHERE b.competency_id = l.competency_id 
                        ORDER BY b.effective_date DESC LIMIT 1
                    ) AS INTEGER), CAST(l.required_level AS INTEGER)) - CAST(l.current_level AS INTEGER)) AS gap_vs_benchmark
                FROM competency_assessment_line l
                JOIN competency_assessment a ON l.assessment_id = a.id
                JOIN hr_employee e ON a.employee_id = e.id
                LEFT JOIN hr_department d ON e.department_id = d.id
            )
        """)
