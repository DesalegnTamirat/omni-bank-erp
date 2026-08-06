from odoo import api, models,fields,_
class BlacklistPool(models.Model):
    _name = "blacklist.pool"
    _description = "Blacklist Pool"
    _rec_name = "candidate"
    active = fields.Boolean(default=True)
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    candidate = fields.Char(string="Candidate Name")
    gender = fields.Selection([('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
                              string="Gender", default="Male")
    national_id = fields.Char(string="National Id")

