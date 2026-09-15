# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrPayrollStructure(models.Model):
    """
    Salary Structure Definition Model.
    Bundles salary rules applicable to specific employee cadres, executive grades, or operational contract types.
    """
    _name = 'hr.payroll.structure'
    _description = 'Employee Salary Structure'
    _order = 'name'

    name = fields.Char(string='Structure Name', required=True, translate=True)
    code = fields.Char(string='Structure Code', required=True, index=True)
    rule_ids = fields.One2many(
        'hr.salary.rule',
        'structure_id',
        string='Salary Rules',
        copy=True
    )
    parent_id = fields.Many2one(
        'hr.payroll.structure',
        string='Parent Structure',
        help="Optional parent structure from which this structure can inherit salary rules."
    )
    children_ids = fields.One2many(
        'hr.payroll.structure',
        'parent_id',
        string='Children Structures'
    )
    child_ids = fields.One2many(
        'hr.payroll.structure',
        'parent_id',
        string='Child Structures'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Description & Regulatory Context')

    @api.constrains('code', 'company_id')
    def _check_code_unique(self):
        for rec in self:
            dup = self.search([('code', '=', rec.code), ('company_id', '=', rec.company_id.id), ('id', '!=', rec.id)], limit=1)
            if dup:
                raise ValidationError(_("Salary structure code '%s' must be unique per company!") % rec.code)

    def get_all_rules(self):
        """
        Return an ordered RecordSet of all active rules defined on this structure
        as well as inherited from ancestor structures.
        """
        all_rules = self.env['hr.salary.rule']
        current = self
        while current:
            all_rules |= current.rule_ids.filtered(lambda r: r.active)
            current = current.parent_id
        return all_rules.sorted(key=lambda r: (r.sequence, r.id))
