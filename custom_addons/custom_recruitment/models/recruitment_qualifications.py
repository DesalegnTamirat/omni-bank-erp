from odoo import api, models,fields,_
class RecruitmentQualifications(models.Model):
    _name = "recruitment.qualification"
    _description = "Recruitment Qualifications"
    _rec_name = "qualification"

    qualification = fields.Char(string="Qualification")
    status = fields.Selection([('yes', 'Y'), ('no', 'N')],
                              string='Status', default='yes')
