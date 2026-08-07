

# -*- coding:utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class HrPayrollStructure(models.Model):
    """
    Salary structure used to define:
    - Basic Salary
    - Allowances
    - Deductions
    """
    _name = 'hr.payroll.structure'
    _description = 'Salary Structure'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(string='Reference', required=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    note = fields.Text(string='Description')
    parent_id = fields.Many2one(
        'hr.payroll.structure',
        string='Parent Structure',
        ondelete='cascade'
    )
    children_ids = fields.One2many(
        'hr.payroll.structure',
        'parent_id',
        string='Child Structures',
        copy=True
    )

    @api.constrains('parent_id')
    def _check_parent_id(self):
        """Prevent circular parent structure references"""
        if not self._check_recursion():
            raise ValidationError(
                _('You cannot create a recursive salary structure.')
            )

    def copy(self, default=None):
        """Override copy to append (copy) to the code"""
        self.ensure_one()
        if default is None:
            default = {}
        default['code'] = _("%s (copy)") % (self.code)
        return super().copy(default)

    def _get_parent_structure(self):
        """Get complete parent structure hierarchy"""
        parent = self.mapped('parent_id')
        if parent:
            parent = parent._get_parent_structure()
        return parent + self
