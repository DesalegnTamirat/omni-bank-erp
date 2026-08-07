# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EmployeeEducation(models.Model):
    """Stores educational background records per employee,
    embedded as a tab on the HR Employee form."""
    _name = 'employee.education'
    _description = 'Employee Education'
    _order = 'from_date desc, id'
    _rec_name = 'qualification'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(default=True)

    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, ondelete='cascade', index=True,
    )
    illiterate = fields.Boolean(string='Illiterate', default=False)
    edu_type = fields.Selection([
        ('formal', 'Formal'),
        ('informal', 'Informal'),
        ('professional', 'Professional'),
        ('vocational', 'Vocational'),
    ], string='Education Type')
    qualification = fields.Char(string='Qualification / Degree')
    field = fields.Char(string='Field of Study')
    school_name = fields.Char(string='School / Institution')
    from_date = fields.Date(string='From Date')
    to_date = fields.Date(string='To Date')
    grade = fields.Char(string='Grade / Division')
    CGPA = fields.Float(string='CGPA / GPA', digits=(3, 2))
    education_rank = fields.Integer(string='Education Rank', default=0)

    # ── Location ──────────────────────────────────────────────────────────────
    country_id = fields.Many2one('res.country', string='Country')
    state_id = fields.Many2one(
        'res.country.state', string='Region / State',
        domain="[('country_id', '=', country_id)]",
    )
    province = fields.Char(string='Province / City')

    # ── Archiving (soft-delete) ───────────────────────────────────────────────
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True


class HrEmployeeEducationInherit(models.Model):
    """Adds the education_ids One2many to hr.employee."""
    _inherit = 'hr.employee'

    education_ids = fields.One2many(
        'employee.education', 'employee_id',
        string='Education Records',
    )
