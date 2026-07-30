from odoo import api, models,fields,_
class BlacklistPool(models.Model):
    _name = "blacklist.pool"
    _description = "Blacklist Pool"
    _rec_name = "candidate"

    candidate = fields.Char(string="Candidate Name")
    gender = fields.Selection([('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
                              string="Gender", default="Male")
    national_id = fields.Char(string="National Id")

