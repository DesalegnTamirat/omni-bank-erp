from odoo import api, models, fields, _


class ServiceRequestType(models.Model):
    _name = "service.request.type"
    _description = "Service Request Type"
    _rec_name = "sr_type"

    sr_type = fields.Char(string="SR Type")
    sr_category = fields.Selection([("Acting", "Acting"),
                                    ("Transfer", "Transfer"),
                                    ("Others", "Others"),
                                    ("Resignation", "Resignation")], string="SR Category")
    sr_prefix = fields.Char(string="SR Sequence Prefix")
    authorizing_office = fields.Selection([("head_office", "Head Office"),
	                                       ("adama_area_office", "Adama Area Office"),
                                           ("debre_markos_area_office", "Debre Markos Area Office"),
                                           ("debre_brehan_area_office", "Debre Brehan Area Office"),
                                           ("hawassa_area_office", "Hawassa Area Office"),
                                           ("jimma_area_office", "Jimma Area Office"),
                                           ("bahir_dar_district_office", "Bahir Dar District Office"),
                                           ("east_aa_district_office", "East AA District Office"),
                                           ("west_aa_district_office", "West AA District Office"),
                                           ("south_aa_district_office", "South AA District Office"),
                                           ("dessie_district_office", "Dessie District Office"),
                                           ("mekelle_district_office", "Mekelle District Office")], string="Authorizing Office")
    authorizer = fields.Many2one("hr.employee", string="Authorizer")
    status = fields.Boolean(string="Status")



   


