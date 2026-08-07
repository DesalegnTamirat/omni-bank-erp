# -*- coding: utf-8 -*-
from odoo import fields, models, _


class RecruitmentExperienceWeightConfig(models.Model):
    """Per-operating-unit experience weighting configuration for internal
    recruitment eligibility scoring.

    Allows HR to specify that experience gained in certain work units counts
    at a different percentage (e.g. 100% for head-office units, 50% for
    branch units) when computing eligibility for internal vacancies.
    """
    _name = 'recruitment.experience.weight.config'
    _description = 'Internal Recruitment Experience Weight Configuration'
    _rec_name = 'operating_unit_id'

    active = fields.Boolean(default=True)

    internal_recruitment_id = fields.Many2one(
        'employee.recruitment.internal',
        string='Internal Recruitment',
        required=True,
        ondelete='cascade',
        index=True,
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Work Unit',
        required=True,
        help="The work unit whose experience is weighted at this percentage."
    )
    weight_percentage = fields.Float(
        string='Weight (%)',
        digits=(5, 2),
        default=100.0,
        help="Percentage at which experience from this work unit is counted "
             "(e.g. 100 for full credit, 50 for half credit)."
    )


    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True