from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class ComputeBonusWizard(models.TransientModel):
    _name = 'compute.bonus.wizard'
    _description = 'Bonus Wizard'

    date = fields.Date(string='Date',help="Date")
    # commented out: 'hr.period' model does not exist in this module (belongs to an uninstalled payroll module)
    # hr_period = fields.Many2one("hr.period", string='Payroll Period', domain=[('state','=','open')])
    fuel_rate = fields.Float(string="Fuel Rate")

    def populate(self):
        print("self Date : ", self.date)
        print("self hr_period: ", self.hr_period)
        print("self Fuel Rate ", self.fuel_rate)


    def call_populate_bonus(self):
        cr = self.env.cr
        cr.execute("SELECT populate_bonus()")
        cr.commit()
        print("Populate Bonus Executed")
        # cr.close()

    