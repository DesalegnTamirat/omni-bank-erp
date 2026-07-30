from odoo import api, models,fields,_
class Service_award_details(models.Model):
    _name = "service.award"
    _description = "Service Award Details"
    _rec_name = "award_name"

    award_name = fields.Char("Award Name")
    award_type = fields.Char("Award Type")
    elegible_period_of_service = fields.Integer("Elegible Period of Service")
    start_date = fields.Date("Start Date")
    end_date = fields.Date("End Date")

