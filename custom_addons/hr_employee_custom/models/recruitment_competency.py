from odoo import api, models,fields,_
class RecruitmentCompetancies(models.Model):
    _name = "recruitment.competency"
    _description = "Recruitment Competancies"
    _rec_name = "competency"

    competency = fields.Char(string="Competency")
    status = fields.Selection([('yes', 'Y'), ('no', 'N')],
                              string='Status', default='yes')
