# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PlanningManpowerLine(models.Model):
    _name = 'planning.manpower.line'
    _description = 'Work Unit Man Power Line'
    _order = 'job_id, grade_id'

    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='job_id.department_id', store=True, readonly=True)

    work_unit_manpower_id = fields.Many2one(
        'planning.work.unit.manpower', string='Work Unit Man Power',
        ondelete='cascade')

    job_id = fields.Many2one('hr.job', string='Job Position', required=True)

    grade_id = fields.Many2one('employee.grade', string='Grade')

    employee_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non-Managerial'),
    ], string='Category', required=True, default='non_managerial')

    # One headcount field per fiscal-year month (July -> June), replacing
    # the old single `month` + `headcount` pair. This lets one position
    # (job/grade/category) live on a single row instead of duplicating a
    # row per month.
    hc_jul = fields.Integer(string='Jul', default=0)
    hc_aug = fields.Integer(string='Aug', default=0)
    hc_sep = fields.Integer(string='Sep', default=0)
    hc_oct = fields.Integer(string='Oct', default=0)
    hc_nov = fields.Integer(string='Nov', default=0)
    hc_dec = fields.Integer(string='Dec', default=0)
    hc_jan = fields.Integer(string='Jan', default=0)
    hc_feb = fields.Integer(string='Feb', default=0)
    hc_mar = fields.Integer(string='Mar', default=0)
    hc_apr = fields.Integer(string='Apr', default=0)
    hc_may = fields.Integer(string='May', default=0)
    hc_jun = fields.Integer(string='Jun', default=0)

    _MONTH_FIELDS = [
        'hc_jul', 'hc_aug', 'hc_sep', 'hc_oct', 'hc_nov', 'hc_dec',
        'hc_jan', 'hc_feb', 'hc_mar', 'hc_apr', 'hc_may', 'hc_jun',
    ]

    total_headcount = fields.Integer(
        string='Total Head Count', compute='_compute_total_headcount', store=True,
        help='Sum of head count across all 12 fiscal-year months for this position.')

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id, required=True)

    unit_cost = fields.Monetary(
        string='Unit Cost', currency_field='currency_id',
        help='Cost per head for this Job Position / Grade / Category.')

    total_cost = fields.Monetary(
        string='Total Cost', compute='_compute_total_cost',
        store=True, currency_field='currency_id')

    remarks = fields.Char(string='Remarks')

    _sql_constraints = [
        ('line_unique',
         'unique(work_unit_manpower_id, job_id, grade_id, employee_category)',
         'A line for this Job Position / Grade / Category already exists on '
         'this plan. Please edit the existing row and set head counts per '
         'month instead of adding a duplicate row.'),
    ]

    @api.depends(*_MONTH_FIELDS)
    def _compute_total_headcount(self):
        for rec in self:
            rec.total_headcount = sum(rec[f] or 0 for f in rec._MONTH_FIELDS)

    @api.depends('total_headcount', 'unit_cost')
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = (rec.total_headcount or 0) * (rec.unit_cost or 0.0)