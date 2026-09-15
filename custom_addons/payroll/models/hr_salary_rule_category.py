# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrSalaryRuleCategory(models.Model):
    """
    Salary Rule Category Hierarchy Model.
    Groups individual salary rules into standard accounting buckets:
    Basic, Allowances, Gross, Statutory Deductions, Disciplinary/Voluntary Deductions, Net, and Employer Contributions.
    """
    _name = 'hr.salary.rule.category'
    _description = 'Salary Rule Category Hierarchy'
    _order = 'sequence, id'

    name = fields.Char(string='Category Name', required=True, translate=True)
    code = fields.Char(string='Code', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    parent_id = fields.Many2one(
        'hr.salary.rule.category',
        string='Parent Category',
        index=True,
        ondelete='cascade'
    )
    children_ids = fields.One2many(
        'hr.salary.rule.category',
        'parent_id',
        string='Child Categories'
    )
    child_ids = fields.One2many(
        'hr.salary.rule.category',
        'parent_id',
        string='Child Categories'
    )
    note = fields.Text(string='Description')

    @api.constrains('code')
    def _check_code_unique(self):
        for rec in self:
            duplicate = self.search([('code', '=', rec.code), ('id', '!=', rec.id)], limit=1)
            if duplicate:
                raise ValidationError(_("Salary rule category code '%s' must be unique!") % rec.code)

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        """Prevent recursive parent-child hierarchy definitions."""
        if not self._check_recursion():
            raise ValidationError(_('Error! You cannot create recursive hierarchy for salary rule categories.'))
