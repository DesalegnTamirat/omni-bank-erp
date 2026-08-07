from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
from odoo.exceptions import UserError
from odoo import fields, models
from odoo.http import request


class EmployeeIncrementSetup(models.Model):
    _name = "employee.increment.setup"
    _inherit = "mail.thread"

    # ACCOUNTING FISCAL YEAR MODULE NOT INSTALLED — 'account.fiscal.year' model
    # does not exist in this database. This field was required=True; uncomment
    # once that module is installed.
    # fiscal_year = fields.Many2one("account.fiscal.year", string="Fiscal Year", required=True)
    # fiscal_year = fields.Many2one("account.fiscal.year", string="Fiscal Year", required=True)
    pms_score_from = fields.Float(string="PMS Score From")
    pms_score_to = fields.Float(string="PMS Score To")
    pms_ranking = fields.Selection([('Outstanding', 'Outstanding'),
                                 ('Excellent', 'Excellent'),
                                 ('Satisfactory', 'Satisfactory'),
                                 ('Unsatisfactory', 'Unsatisfactory')], string="PMS Rank",required=True)
    increment_factor = fields.Float(string="Increment Multiple" ,required=True)
    work_unit = fields.Many2one("operating.unit", string="Work Unit")
    state = fields.Selection([('draft', 'Draft'), ('applied', 'Applied')], string="State", default="draft", readonly=True)
