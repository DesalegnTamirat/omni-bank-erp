# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AttendanceLatenessRule(models.Model):
    _name = 'attendance.lateness.rule'
    _description = 'Configurable Lateness Discipline Regulation Rule'
    _order = 'sequence, threshold_hours asc'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Rule Name / Description', required=True)
    threshold_hours = fields.Float(
        string='Threshold Hours',
        required=True,
        help='Lateness hours threshold (e.g., 0.01 for any late, 4.0, 8.0, 16.0 hours).'
    )
    offense_id = fields.Many2one(
        'discipline.offense',
        string='Warning Level / Offense',
        required=False,
        help='Select the warning level registered on discipline case (e.g., Oral Warning, 1st Written, 2nd Written, 3rd Written).'
    )
    deduction_days = fields.Float(
        string='Deduction / Fine (Days)',
        required=True,
        default=0.0,
        help='Salary deduction in days (e.g., 0 for no deduction, 0.5 for half day, 1.0 for 1 day, 2.0 for 2 days).'
    )
    reset_window_months = fields.Integer(
        string='Reset Window (Months)',
        required=True,
        default=1,
        help='Evaluation reset window in months (e.g., 1 for 1 month, 3 for 3 months, 6 for 6 months, 12 for 1 year).'
    )
    active = fields.Boolean(default=True)

    @api.constrains('threshold_hours', 'reset_window_months', 'deduction_days')
    def _check_positive_numbers(self):
        for rec in self:
            if rec.threshold_hours < 0:
                raise ValidationError(_("Threshold hours cannot be negative."))
            if rec.reset_window_months < 1:
                raise ValidationError(_("Reset window must be at least 1 month."))
            if rec.deduction_days < 0:
                raise ValidationError(_("Deduction days cannot be negative."))


class AttendanceAbsenceRule(models.Model):
    _name = 'attendance.absence.rule'
    _description = 'Configurable Absence Discipline Regulation Rule'
    _order = 'sequence, threshold_days asc'

    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Rule Name / Description', required=True)
    threshold_days = fields.Float(
        string='Threshold Days',
        required=True,
        help='Consecutive or cumulative unexcused absence days threshold (e.g., 1.0, 3.0 days).'
    )
    offense_id = fields.Many2one(
        'discipline.offense',
        string='Warning Level / Offense',
        required=False,
        help='Select the warning level registered on discipline case.'
    )
    deduction_days = fields.Float(
        string='Deduction / Fine (Days)',
        required=True,
        default=0.0,
        help='Salary deduction in days (e.g., 0 for no deduction, 1.0 for 1 day, 3.0 for 3 days).'
    )
    reset_window_months = fields.Integer(
        string='Reset Window (Months)',
        required=True,
        default=1,
        help='Evaluation reset window in months (e.g., 1, 3, 6, 12 months).'
    )
    active = fields.Boolean(default=True)

    @api.constrains('threshold_days', 'reset_window_months', 'deduction_days')
    def _check_positive_numbers(self):
        for rec in self:
            if rec.threshold_days < 0:
                raise ValidationError(_("Threshold days cannot be negative."))
            if rec.reset_window_months < 1:
                raise ValidationError(_("Reset window must be at least 1 month."))
            if rec.deduction_days < 0:
                raise ValidationError(_("Deduction days cannot be negative."))
