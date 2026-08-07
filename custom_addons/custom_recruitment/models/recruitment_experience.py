from odoo import api, models,fields,_
class RecruitmentExperience(models.Model):
    _name = "recruitment.experience"
    _description = "Recruitment Experience"
    _rec_name = "experience"

    experience = fields.Char(string="Experience")
    status = fields.Selection([('yes', 'Y'), ('no', 'N')],
                              string='Status', default='yes')