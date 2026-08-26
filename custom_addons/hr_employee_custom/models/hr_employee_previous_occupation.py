# -*- coding: utf-8 -*-

from odoo import models, fields, api


class EmployeePreviousOccupation(models.Model):
    _name = 'employee.previous.occupation'
    _description = 'Employee Previous Occupation'
    _rec_name = 'position'
    _order = 'from_date desc, id desc'

    # ---------------------------------------------------------------
    # Dates
    # ---------------------------------------------------------------
    from_date = fields.Date(string='From Date')
    to_date   = fields.Date(string='To Date')

    # ---------------------------------------------------------------
    # Job details — Left column (Image 2)
    # ---------------------------------------------------------------
    position = fields.Char(
        string='Position',
        help='Job title / position held',
    )
    organization = fields.Char(
        string='Organization',
        help='Name of the previous employer / organization',
    )
    salary_earned = fields.Float(
        string='Salary Earned',
        digits=(16, 2),
        help='Monthly/annual salary earned at this organization',
    )

    # ---------------------------------------------------------------
    # Reference — Left column (Image 2)
    # ---------------------------------------------------------------
    ref_name = fields.Char(
        string='Reference Name',
        help='Name of a reference contact at the previous organization',
    )
    ref_phone = fields.Char(
        string='Reference Phone',
        help='Phone number of the reference contact',
    )
    pension_contributed = fields.Boolean(
        string='Pension Contributed',
        default=False,
        help='Whether pension was contributed during this employment',
    )

    # ---------------------------------------------------------------
    # Experience & reason — Right column (Image 2)
    # ---------------------------------------------------------------
    experience_type = fields.Selection(
        selection=[
            ('banking',                  'Banking'),
            ('non_banking_accountable',  'Non Banking - Accountable'),
            ('non_banking_non_accountable', 'Non Banking - Non Accountable'),
            ('government',               'Government'),
            ('ngo',                      'NGO / International'),
            ('other',                    'Other'),
        ],
        string='Experience Type',
        help='Type / sector of experience gained',
    )
    reason_for_leaving = fields.Char(
        string='Reason for Leaving Organization',
        help='Reason the employee left this organization',
    )
    tax_paid = fields.Boolean(
        string='Tax Paid',
        default=False,
        help='Whether income tax was paid during this employment',
    )

    # ---------------------------------------------------------------
    # Reference contact — Right column (Image 2)
    # ---------------------------------------------------------------
    ref_position = fields.Char(
        string='Reference Position',
        help='Job title / position of the reference contact',
    )
    email = fields.Char(
        string='Email',
        help='Email address of the reference contact',
    )
    banking_experience = fields.Boolean(
        string='Banking Experience',
        default=False,
        help='Tick if this role involved banking experience',
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
# Extend hr.employee — previous_occupation_ids + count smart button
# -----------------------------------------------------------------------
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    previous_occupation_ids = fields.One2many(
        'employee.previous.occupation',
        'employee_id',
        string='Previous Occupations',
    )

    previous_occupation_count = fields.Integer(
        string='Previous Occupation Count',
        compute='_compute_previous_occupation_count',
        store=False,
    )

    @api.depends('previous_occupation_ids')
    def _compute_previous_occupation_count(self):
        for employee in self:
            employee.previous_occupation_count = len(employee.previous_occupation_ids)
