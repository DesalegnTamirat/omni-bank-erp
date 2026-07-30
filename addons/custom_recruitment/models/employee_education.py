# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EmployeeEducation(models.Model):
    _name = 'employee.education'
    _inherit = ['mail.thread']
    _description = 'Employee Education'
    _rec_name = 'school_name'
    _order = 'from_date desc'

    # The ONLY relational field — links back to the employee.
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade', index=True
    )

    edu_type = fields.Selection([
        ('certificate', 'Certificate'),
        ('diploma', 'Diploma'),
        ('degree', 'Degree'),
        ('masters', 'Masters'),
        ('phd', 'PhD'),
    ], string='Education Type')

    qualification = fields.Char(string='Qualification')
    field = fields.Char(string='Field of Study')
    school_name = fields.Char(string='School / Institution')

    from_date = fields.Date(string='From Date')
    to_date = fields.Date(string='To Date')

    grade = fields.Char(string='Grade')

    # Char, matching the existing varchar column — do NOT change to Float.
    # Existing data may contain non-numeric text, and Odoo's schema upgrade
    # cannot cast varchar -> numeric types safely (same failure mode we hit
    # earlier with app_reference).
    CGPA = fields.Char(string='CGPA')

    # Char, matching the existing varchar column — do NOT change to Integer,
    # for the same reason as CGPA above.
    education_rank = fields.Char(string='Rank')

    illiterate = fields.Boolean(string='Illiterate')

    # Plain text fields — no relation to res.country / res.country.state.
    country_id = fields.Char(string='Country')
    state_id = fields.Char(string='State')
    province = fields.Char(string='Province')

    active = fields.Boolean(string='Active', default=True)

    # message_main_attachment_id is supplied automatically by the
    # mail.thread mixin above — not redeclared here.

    @api.onchange('illiterate')
    def _onchange_illiterate(self):
        for rec in self:
            if rec.illiterate:
                rec.edu_type = False
                rec.qualification = False
                rec.field = False
                rec.school_name = False
                rec.from_date = False
                rec.to_date = False
                rec.grade = False
                rec.CGPA = False

    @api.constrains('from_date', 'to_date')
    def _check_dates(self):
        for rec in self:
            if rec.from_date and rec.to_date and rec.to_date < rec.from_date:
                raise ValidationError(_(
                    "To Date must be on or after From Date for %s."
                ) % (rec.school_name or rec.display_name))

    @api.constrains('CGPA')
    def _check_cgpa(self):
        """
        CGPA is stored as Char (matching existing data), but if a value IS
        provided it should still look like a number in a sane range —
        validated here in Python rather than at the DB type level.
        """
        for rec in self:
            if not rec.CGPA:
                continue
            try:
                value = float(rec.CGPA)
            except ValueError:
                raise ValidationError(_(
                    "CGPA must be a number (got '%s')."
                ) % rec.CGPA)
            if not (0.0 <= value <= 4.0):
                raise ValidationError(_(
                    "CGPA must be between 0.0 and 4.0 (got %s)."
                ) % rec.CGPA)


class HrEmployeeEducationInherit(models.Model):
    """Expose education records as a one2many from hr.employee."""
    _inherit = 'hr.employee'
    # Mark the employee as illiterate if they have no formal education
    illiterate = fields.Boolean(string='Illiterate', default=False)

    education_ids = fields.One2many(
        'employee.education', 'employee_id', string='Education'
    )