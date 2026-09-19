# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PmsRanking(models.Model):
    _name = 'pms.ranking'
    _description = 'PMS Ranking'
    _order = 'score_from desc'

    score_from = fields.Float(required=True, digits=(10, 2), string='Score From')
    score_to = fields.Float(required=True, digits=(10, 2), string='Score To')
    ranking = fields.Selection(
        selection=[
            ('outstanding', 'Outstanding'),
            ('excellent', 'Excellent'),
            ('satisfactory', 'Satisfactory'),
            ('unsatisfactory', 'Unsatisfactory'),
        ], string='PMS Ranking', default='outstanding',
        required=True,
    )

    @api.constrains('score_from', 'score_to')
    def _check_score(self):
        for rec in self:
            if rec.score_from > 100 or rec.score_from < 0:
                raise ValidationError('Score From must be between 0 and 100')
            if rec.score_to > 100 or rec.score_to < 0:
                raise ValidationError('Score To must be between 0 and 100')
            if rec.score_from >= rec.score_to:
                raise ValidationError('Score From must be less than Score To')