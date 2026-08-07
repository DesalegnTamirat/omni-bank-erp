from odoo import api, models,fields,_

class assessment_criteria(models.Model):
    _name = "assessment.criteria"
    _description = "Assessment Criteria"
    _rec_name = "assessment_criteria"
    active = fields.Boolean(default=True)
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    assessment_criteria = fields.Char("Assessment Criteria")
    weightage = fields.Float("Weight")
    status = fields.Boolean("Status")
