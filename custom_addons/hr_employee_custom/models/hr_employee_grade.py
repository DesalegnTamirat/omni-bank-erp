# -*- coding: utf-8 -*-
import re
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

ROMAN_VALUES = [
    (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
    (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
    (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'),
]


def int_to_roman(num):
    result = []
    for value, symbol in ROMAN_VALUES:
        count, num = divmod(num, value)
        result.append(symbol * count)
    return ''.join(result)


def roman_to_int(s):
    values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    total = 0
    prev = 0
    for ch in reversed(s.upper()):
        val = values.get(ch, 0)
        total += -val if val < prev else val
        prev = max(prev, val)
    return total


class HrEmployeeGrade(models.Model):
    _name = 'employee.grade'
    _description = 'Employee Grade'
    _rec_name = "grade_name"

    active = fields.Boolean(default=True)

    # grade_code = fields.Char("Grade Code")
    grade_code = fields.Char("Grade Code", default=lambda self: self._default_grade_code())

    grade_name = fields.Char("Grade Name", default=lambda self: self._default_grade_name())

    parent_grade = fields.Char("Parent Grade")

    grade_level = fields.Selection(
        [
            ('junior', 'Junior'),
            ('senior', 'Senior'),
        ],
        string="Grade Level",
        required=True,
        default='junior',
    )
    category = fields.Many2one('employee.category', string='Category'
                               )
    # manager=fields.Boolean(string='Manager')
    # non_manager=fields.Boolean(string='Non Manager')

    salary_structure = fields.Many2one('hr.payroll.structure', 'Salary Structure')
    base_salary = fields.Float("Base Salary")
    salary_factor = fields.Float("Salary Factor", digits=(16, 3), default=1.000)
    # start_date = fields.Date("Start Date")
    start_date = fields.Date("Start Date", default=fields.Date.context_today)
    # end_date = fields.Date("End Date")
    end_date = fields.Date(
        "End Date",
        default=lambda self: fields.Date.from_string('2099-12-31'),
    )

    increment_id = fields.One2many(
        'employee.grade.increment', 'grade_id',
        string='Increments',
    )

    @api.constrains('base_salary')
    def _check_base_salary(self):
        for record in self:
            if record.base_salary <= 0:
                raise ValidationError(_("Base Salary must be greater than zero."))

    @api.constrains('salary_factor')
    def _check_salary_factor(self):
        for record in self:
            if record.salary_factor <= 1:
                raise ValidationError(_("Salary Factor must be greater than 1."))

    @api.model
    def _default_grade_name(self):
        code = self._default_grade_code()
        return f"Grade {code}"

    @api.constrains('grade_code')
    def _check_unique_code(self):
        for rec in self:
            if rec.grade_code:
                existing = self.search([
                    ('id', '!=', rec.id),
                    ('grade_code', '=ilike', rec.grade_code)
                ], limit=1)
                if existing:
                    raise ValidationError(f"The Grade Code '{rec.grade_code}' already exists.")

    @api.constrains('grade_name')
    def _check_name_is_alphabetic(self):
        for record in self:
            if record.grade_name and not re.search(r'[a-zA-Z]', record.grade_name):
                raise ValidationError("Grade Name must contain letters. Pure numbers are not allowed.")

    # @api.constrains('grade_code')
    # def _check_grade_code_length(self):
    #     for record in self:
    #         if record.grade_code and len(record.grade_code) < 2:
    #             raise ValidationError("Grade Code must be at least 2 characters long.")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._generate_increments()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'base_salary' in vals or 'salary_factor' in vals:
            self._generate_increments()
        return res

    def _generate_increments(self):
        """(Re)builds the single increment row per grade, with all 10
        steps stored as columns instead of separate records.
        increment 1 = base_salary * salary_factor
        increment n = increment (n-1) * salary_factor
        """
        Increment = self.env['employee.grade.increment']
        for rec in self:
            rec.increment_id.unlink()
            if not rec.base_salary or not rec.salary_factor:
                continue
            amount = rec.base_salary
            vals = {'grade_id': rec.id}
            for seq in range(1, 11):
                amount = amount * rec.salary_factor
                vals[f'amount_{seq}'] = amount
            Increment.create(vals)

    def action_save_grade(self):
        self.ensure_one()
        self._generate_increments()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved Successfully',
                'message': f"Employee Grade '{self.grade_name}' has been saved.",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_archive_grade(self):
        name = self.grade_name
        self.write({'active': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Archived',
                'message': f"Employee Grade '{name}' has been archived successfully.",
                'type': 'warning',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': 'Employee Grades',
                    'res_model': 'employee.grade',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'current',
                },
            }
        }

    @api.model
    def _default_grade_code(self):
        """Finds the highest roman-numeral prefix currently in use
        (ignoring any postfix like '-A') and returns the next one up.
        e.g. existing codes III, IV, V-A -> next default is VI.
        """
        records = self.search([], order='id desc', limit=200)
        highest = 0
        roman_pattern = re.compile(r'^([IVXLCDM]+)')
        for rec in records:
            if not rec.grade_code:
                continue
            match = roman_pattern.match(rec.grade_code.upper())
            if match:
                try:
                    value = roman_to_int(match.group(1))
                    highest = max(highest, value)
                except Exception:
                    continue
        return int_to_roman(highest + 1)


class HrEmployeeGradeIncrement(models.Model):
    _name = 'employee.grade.increment'
    _description = 'Employee Grade Increment Row'

    _sql_constraints = [
        (
            'unique_grade_increment',
            'unique(grade_id)',
            'Each Employee Grade can only have one Increment row.',
        ),
    ]

    grade_id = fields.Many2one(
        'employee.grade', string='Grade',
        required=True, ondelete='cascade',
    )
    amount_1 = fields.Float("Increment 1")
    amount_2 = fields.Float("Increment 2")
    amount_3 = fields.Float("Increment 3")
    amount_4 = fields.Float("Increment 4")
    amount_5 = fields.Float("Increment 5")
    amount_6 = fields.Float("Increment 6")
    amount_7 = fields.Float("Increment 7")
    amount_8 = fields.Float("Increment 8")
    amount_9 = fields.Float("Increment 9")
    amount_10 = fields.Float("Increment 10")


# Adds grade_id to hr.employee
class HrEmployeeGradeAssignment(models.Model):
    _inherit = 'hr.employee'

    grade_id = fields.Many2one(
        'employee.grade',
        string='Employee Grade',
        related='job_grade',
        store=True,
        readonly=False
    )
