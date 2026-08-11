# -*- coding: utf-8 -*-

from odoo import models, fields, api


class EmployeeEducation(models.Model):
    _name = 'employee.education'
    _description = 'Employee Education Details'
    _rec_name = 'school_name'
    _order = 'from_date desc, id desc'

    # ---------------------------------------------------------------
    # Dates
    # ---------------------------------------------------------------
    from_date = fields.Date(string='From Date')
    to_date   = fields.Date(string='To Date')

    # ---------------------------------------------------------------
    # Education details — matching Image 1 form layout
    # ---------------------------------------------------------------
    field = fields.Char(
        string='Education Field/Major',
        help='Field of study / major subject',
    )
    school_name = fields.Char(
        string='School / College Name',
        help='Name of the school, college or university attended',
    )
    CGPA = fields.Float(
        string='CGPA',
        digits=(5, 2),
        help='Cumulative Grade Point Average',
    )
    illiterate = fields.Boolean(
        string='Illiterate',
        default=False,
    )
    qualification = fields.Char(
        string='Qualification',
        help='Qualification obtained (e.g. BSc, MSc, PhD, Diploma)',
    )
    education_rank = fields.Char(
        string='Education Rank',
        help='Rank / level of education (e.g. 1st, 2nd, Honours)',
    )
    grade = fields.Char(
        string='Grade',
        help='Final grade or GPA obtained',
    )

    # ---------------------------------------------------------------
    # Education type — Selection dropdown (matches Image 1 right column)
    # ---------------------------------------------------------------
    edu_type = fields.Selection(
        selection=[
            ('primary',        'Primary'),
            ('secondary',      'Secondary'),
            ('tvet',           'TVET / Vocational'),
            ('diploma',        'Diploma'),
            ('bachelor',       'Bachelor\'s Degree'),
            ('postgraduate',   'Post-Graduate Diploma'),
            ('masters',        'Master\'s Degree'),
            ('phd',            'PhD / Doctorate'),
            ('other',          'Other'),
        ],
        string='Education Type',
    )

    # ---------------------------------------------------------------
    # Location
    # ---------------------------------------------------------------
    country_id = fields.Many2one(
        'res.country',
        string='Country',
        ondelete='restrict',
    )
    state_id = fields.Many2one(
        'res.country.state',
        string='State / Region',
        domain="[('country_id', '=', country_id)]",
        ondelete='restrict',
    )
    province = fields.Char(
        string='Province',
    )

    # ---------------------------------------------------------------
    # Link to employee
    # ---------------------------------------------------------------
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )


# -----------------------------------------------------------------------
# Extend hr.employee — education_ids + education_count smart button
# -----------------------------------------------------------------------
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    education_detail_ids = fields.One2many(
        'employee.education',
        'employee_id',
        string='Education Details',
    )

    education_detail_count = fields.Integer(
        string='Education Count',
        compute='_compute_education_detail_count',
        store=False,
    )

    @api.depends('education_detail_ids')
    def _compute_education_detail_count(self):
        for employee in self:
            employee.education_detail_count = len(employee.education_detail_ids)
