# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class RecruitmentQualifications(models.Model):
    _name = "recruitment.qualification"
    _description = "Recruitment Qualifications"
    _rec_name = "display_name"

    qualification = fields.Char(string="Qualification Level", required=True)
    specialization = fields.Char(string="Specialization / Field of Study")
    status = fields.Selection([('yes', 'Y'), ('no', 'N')],
                              string='Status', default='yes')

    display_name = fields.Char(string="Qualification", compute="_compute_display_name", store=True)

    @api.depends('qualification', 'specialization')
    def _compute_display_name(self):
        for rec in self:
            if rec.qualification and rec.specialization:
                rec.display_name = f"{rec.qualification} - {rec.specialization}"
            elif rec.qualification:
                rec.display_name = rec.qualification
            elif rec.specialization:
                rec.display_name = rec.specialization
            else:
                rec.display_name = _("New Qualification")

