# -*- coding: utf-8 -*-
from odoo import fields, models, _


class RecruitmentPenaltyDeduction(models.Model):
    _name = 'recruitment.penalty.deduction'
    _description = 'Candidate Score Penalty / Deduction'
    _rec_name = 'penalty_type'

    active = fields.Boolean(default=True)

    candidate_score_id = fields.Many2one(
        'recruitment.candidate.score',
        string='Candidate Score',
        required=True,
        ondelete='cascade',
        index=True,
    )
    penalty_type = fields.Selection([
        ('first_penalty', 'First Penalty'),
        ('second_penalty', 'Second Penalty'),
        ('last_active_penalty', 'Last Active Penalty'),
        ('other', 'Other'),
    ], string='Penalty Type', required=True)
    penalty_date = fields.Date(string='Penalty Date')
    deduction_percentage = fields.Float(
        string='Deduction (%)',
        digits=(5, 2),
        help="Percentage points to deduct from the candidate's final score."
    )
    description = fields.Text(string='Description / Notes')
    applied = fields.Boolean(
        string='Applied',
        default=False,
        help="Check to apply this deduction to the final score calculation."
    )


    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
