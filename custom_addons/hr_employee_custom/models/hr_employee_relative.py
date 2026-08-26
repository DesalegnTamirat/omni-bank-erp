# -*- coding: utf-8 -*-

from odoo import models, fields, api


class EmployeeRelative(models.Model):
    _name = 'employee.relative'
    _description = 'Employee Relative'
    _rec_name = 'name'
    _order = 'relative_type asc, name asc'

    # ---------------------------------------------------------------
    # Relative type — Selection matching the dropdown in Image 2
    # ---------------------------------------------------------------
    relative_type = fields.Selection(
        selection=[
            ('aunt',      'Aunt'),
            ('brother',   'Brother'),
            ('daughter',  'Daughter'),
            ('father',    'Father'),
            ('husband',   'Husband'),
            ('mother',    'Mother'),
            ('sister',    'Sister'),
            ('sibling',   'Sibling'),
            ('dependent', 'Dependent'),
            ('son',       'Son'),
            ('child',     'Child'),
            ('uncle',     'Uncle'),
            ('wife',      'Wife'),
            ('spouse',    'Spouse'),
            ('other',     'Other'),
        ],
        string='Relative Type',
        required=True,
    )

    # ---------------------------------------------------------------
    # Personal information
    # ---------------------------------------------------------------
    name = fields.Char(
        string='Name',
        required=True,
    )
    birthday = fields.Date(
        string='Date of Birth',
    )
    place_of_birth = fields.Char(
        string='Place of Birth',
    )
    occupation = fields.Char(
        string='Occupation',
    )
    gender = fields.Selection(
        selection=[
            ('male',   'Male'),
            ('female', 'Female'),
        ],
        string='Gender',
    )

    # ---------------------------------------------------------------
    # Contact & identity
    # ---------------------------------------------------------------
    reletive_phone = fields.Char(
        string='Phone',
        help='Phone number of the relative',
    )
    relative_email_id = fields.Char(
        string='Email',
        help='Email address of the relative',
    )
    relative_national_id = fields.Char(
        string='National ID',
        help='National identification number of the relative',
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
# Extend hr.employee — relative_ids + relative_count smart button
# -----------------------------------------------------------------------
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    relative_ids = fields.One2many(
        'employee.relative',
        'employee_id',
        string='Relatives',
    )

    relative_count = fields.Integer(
        string='Relative Count',
        compute='_compute_relative_count',
        store=False,
    )

    @api.depends('relative_ids')
    def _compute_relative_count(self):
        for employee in self:
            employee.relative_count = len(employee.relative_ids)
