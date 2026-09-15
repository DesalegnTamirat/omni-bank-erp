# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from datetime import date


class HrPayslipSegment(models.Model):
    """
    Sub-Period Proration Time Slice Model.
    
    Implements dynamic multi-segment time slicing for payroll cycles intersecting with
    employee lifecycle events (mid-month joiners, branch transfers, promotions, demotions, increments).
    Computes exact prorated basic wages, grade adjustments, and location-dependent hardship benefits
    standardized against a 30-day commercial banking divisor.
    """
    _name = 'hr.payslip.segment'
    _description = 'Payroll Proration Sub-Period Time Slice'
    _order = 'date_start asc, id asc'

    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Parent Payslip',
        required=True,
        ondelete='cascade',
        index=True
    )
    name = fields.Char(string='Segment Label', required=True)
    segment_type = fields.Selection([
        ('standard', 'Full Period Standard'),
        ('joiner', 'Mid-Month Joiner'),
        ('separation', 'Mid-Month Separation Settlement'),
        ('pre_transfer', 'Pre-Transfer Sub-Period'),
        ('post_transfer', 'Post-Transfer Sub-Period'),
        ('pre_promotion', 'Pre-Promotion (Former Grade/Step)'),
        ('post_promotion', 'Post-Promotion (New Grade/Step)'),
        ('pre_demotion', 'Pre-Demotion (Former Grade)'),
        ('post_demotion', 'Post-Demotion (Adjusted Grade)'),
        ('increment', 'Salary Increment Proration'),
    ], string='Segment Category', default='standard', required=True)

    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    
    # Days calculation
    days_count = fields.Integer(string='Active Calendar/Worked Days', default=30)
    total_period_days = fields.Integer(string='Total Period Standard Divisor', default=30)
    proration_factor = fields.Float(
        string='Proration Factor (Days / 30)',
        compute='_compute_proration_factor',
        store=True,
        digits=(10, 6)
    )

    # Location & Hardship Integration
    branch_id = fields.Many2one('hr.department', string='Branch / Office Unit')
    hardship_rate_id = fields.Many2one('hr.hardship.allowance.rate', string='Applicable Hardship Rate')
    hardship_percentage = fields.Float(string='Hardship Rate (%)', default=0.0)

    # Grade & Salary Components for this Segment
    grade_id = fields.Many2one('employee.grade', string='Job Grade')
    basic_salary = fields.Float(string='Segment Full Basic Salary (ETB)', digits=(16, 2), default=0.0)
    transport_allowance = fields.Float(string='Segment Full Transport Allowance (ETB)', digits=(16, 2), default=0.0)
    housing_allowance = fields.Float(string='Segment Full Housing Allowance (ETB)', digits=(16, 2), default=0.0)
    other_allowance = fields.Float(string='Segment Full Other Allowance (ETB)', digits=(16, 2), default=0.0)

    # Prorated Calculated Results
    prorated_basic_salary = fields.Float(
        string='Prorated Basic Salary',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )
    prorated_hardship_allowance = fields.Float(
        string='Prorated Hardship Allowance',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )
    prorated_transport_allowance = fields.Float(
        string='Prorated Transport Allowance',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )
    prorated_housing_allowance = fields.Float(
        string='Prorated Housing Allowance',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )
    prorated_other_allowance = fields.Float(
        string='Prorated Other Allowance',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )
    total_prorated_earnings = fields.Float(
        string='Segment Total Gross',
        compute='_compute_prorated_amounts',
        store=True,
        digits=(16, 2)
    )

    @api.depends('days_count', 'total_period_days')
    def _compute_proration_factor(self):
        """Compute the fractional weight of this segment against standard 30 days divisor."""
        for seg in self:
            divisor = seg.total_period_days or 30
            seg.proration_factor = max(0.0, float(seg.days_count or 0) / float(divisor))

    @api.depends('basic_salary', 'transport_allowance', 'housing_allowance', 'other_allowance',
                 'hardship_percentage', 'proration_factor')
    def _compute_prorated_amounts(self):
        """Calculate exact prorated figures applying the segment factor."""
        for seg in self:
            factor = seg.proration_factor
            seg.prorated_basic_salary = round(seg.basic_salary * factor, 2)
            
            # Hardship allowance is calculated as % of basic salary in this location
            full_hardship = (seg.basic_salary * seg.hardship_percentage) / 100.0
            seg.prorated_hardship_allowance = round(full_hardship * factor, 2)
            
            seg.prorated_transport_allowance = round(seg.transport_allowance * factor, 2)
            seg.prorated_housing_allowance = round(seg.housing_allowance * factor, 2)
            seg.prorated_other_allowance = round(seg.other_allowance * factor, 2)
            
            seg.total_prorated_earnings = (
                seg.prorated_basic_salary +
                seg.prorated_hardship_allowance +
                seg.prorated_transport_allowance +
                seg.prorated_housing_allowance +
                seg.prorated_other_allowance
            )
