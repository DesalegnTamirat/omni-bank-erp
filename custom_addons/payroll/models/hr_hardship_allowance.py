# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrHardshipAllowanceRate(models.Model):
    """
    Location-Based Hardship Allowance Rate Specification Model (FR-PAY-007).
    Maps bank branch location codes and regions to hardship tiers and percentage rates.
    """
    _name = 'hr.hardship.allowance.rate'
    _description = 'Hardship Allowance Rate Table'
    _order = 'rate_percentage desc, code'

    name = fields.Char(string='Hardship Tier Name', required=True)
    code = fields.Char(string='Tier Code', required=True, index=True)
    tier_level = fields.Selection([
        ('tier_1', 'Tier 1 (High / Remote - 30%)'),
        ('tier_2', 'Tier 2 (Moderate Hardship - 20%)'),
        ('tier_3', 'Tier 3 (Mild Hardship - 10%)'),
        ('tier_4', 'Tier 4 (Developing Zone - 5%)'),
        ('standard', 'Standard / No Hardship (0%)'),
    ], string='Classification Level', default='standard', required=True)
    rate_percentage = fields.Float(string='Allowance Percentage (%)', required=True, digits=(5, 2), default=0.0)
    tax_exempt = fields.Boolean(string='Statutory Tax Exempt', default=False, help="Whether this hardship rate is exempt from personal income tax.")
    tax_exempt_limit = fields.Float(string='Tax Exemption Cap (ETB)', digits=(16, 2), default=0.0)
    description = fields.Text(string='Policy & Criteria Description')
    active = fields.Boolean(string='Active', default=True)


class HrHardshipAllowanceHistory(models.Model):
    """
    Employee Hardship Allowance Audit Ledger (FR-PAY-009).
    Maintains complete immutable historical trace of hardship allowance eligibility, location assignments, rates, and effective dates.
    """
    _name = 'hr.hardship.allowance.history'
    _description = 'Employee Hardship Allowance Audit History'
    _order = 'effective_date desc, id desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    branch_id = fields.Many2one('hr.department', string='Assigned Branch / Location')
    location_code = fields.Char(string='Location Code')
    hardship_rate_id = fields.Many2one('hr.hardship.allowance.rate', string='Hardship Rate Tier')
    rate_percentage = fields.Float(string='Applied Rate (%)', digits=(5, 2))
    effective_date = fields.Date(string='Effective Date', required=True, index=True)
    end_date = fields.Date(string='End Date')
    initiator_id = fields.Many2one('res.users', string='Initiator', default=lambda self: self.env.user)
    approver_id = fields.Many2one('res.users', string='Approver')
    source_transfer_id = fields.Many2one('transfer.form', string='Triggering Transfer Action')
    notes = fields.Text(string='Audit Remarks')
