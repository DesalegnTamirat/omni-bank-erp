# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrPayrollAccount(models.Model):
    """Standalone Payroll Account model for Bunna Bank Payroll.
    Maintains payroll debit/credit accounts completely decoupled from Odoo's core GL account module.
    """
    _name = 'hr.payroll.account'
    _description = 'Payroll Account'
    _order = 'code, name'

    code = fields.Char(string='Account Code', required=True, index=True)
    name = fields.Char(string='Account Name', required=True, index=True)
    account_type = fields.Selection([
        ('debit', 'Debit / Expense'),
        ('credit', 'Credit / Liability'),
        ('both', 'Debit & Credit'),
    ], string='Account Type', default='both', help="Indicates whether this account is typically used for debiting, crediting, or both.")
    banking_type = fields.Selection([
        ('conventional', 'Conventional'),
        ('ifb', 'IFB (Interest-Free Banking)'),
        ('both', 'Both (Conventional & IFB)'),
    ], string='Banking Type', default='both', help="Specifies if this GL account is used for Conventional, IFB, or Both. If not specified or set to Both, it can be used by both.")
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('code', 'company_id')
    def _check_code_company_uniq(self):
        for rec in self:
            if rec.code:
                domain = [('code', '=', rec.code), ('company_id', '=', rec.company_id.id), ('id', '!=', rec.id)]
                if self.search_count(domain):
                    raise ValidationError(_('Payroll Account Code must be unique per company!'))

    @api.depends('code', 'name', 'banking_type')
    def _compute_display_name(self):
        for rec in self:
            label = f"{rec.code} {rec.name}" if rec.code and rec.name else (rec.name or rec.code or '')
            if rec.banking_type and rec.banking_type != 'both':
                label = f"{label} [{rec.banking_type.upper()}]"
            rec.display_name = label

    @api.model
    def init(self):
        super().init()
        try:
            self.env.cr.execute("""
                UPDATE hr_payroll_account
                SET account_type = 'both'
                WHERE code = '0127020305';

                UPDATE hr_payroll_account
                SET banking_type = 'both'
                WHERE banking_type IS NULL;
            """)
        except Exception:
            pass


class HrPayrollAnalyticAccount(models.Model):
    """Standalone Payroll Analytic Account for cost center tracking."""
    _name = 'hr.payroll.analytic.account'
    _description = 'Payroll Analytic Account'
    _order = 'code, name'

    code = fields.Char(string='Analytic Code', index=True)
    name = fields.Char(string='Analytic Name', required=True, index=True)
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            if rec.code and rec.name:
                rec.display_name = f"{rec.code} {rec.name}"
            else:
                rec.display_name = rec.name or rec.code or ''


class HrPayrollTax(models.Model):
    """Standalone Payroll Tax definition for deduction tracking."""
    _name = 'hr.payroll.tax'
    _description = 'Payroll Tax'
    _order = 'sequence, name'

    sequence = fields.Integer(string='Sequence', default=10)
    code = fields.Char(string='Tax Code', index=True)
    name = fields.Char(string='Tax Name', required=True)
    rate = fields.Float(string='Rate (%)')
    active = fields.Boolean(string='Active', default=True)
    note = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
