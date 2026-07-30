from odoo import api, models,fields,_

class assessment_criteria(models.Model):
    _name = "assessment.criteria"
    _description = "Assessment Criteria"
    _rec_name = "assessment_criteria"
    assessment_criteria = fields.Char("Assessment Criteria")
    weightage = fields.Float("Weight")
    status = fields.Boolean("Status")
