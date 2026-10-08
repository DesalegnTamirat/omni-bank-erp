from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class preprocessing_salary_information_details(models.TransientModel):
    _name = 'preprocessing.salary.information'
    _description = 'Preprocessing Salary Information'

    date = fields.Date(string='Date',help="Date")
    # commented out: 'hr.period' model does not exist in this module (belongs to an uninstalled payroll module)
    # hr_period = fields.Many2one("hr.period", string='Payroll Period', domain=[('state','=','open')])
    fuel_rate = fields.Float(string="Fuel Rate")

    def populate(self):
        print("self Date : ", self.date)
        print("self hr_period: ", self.hr_period)
        print("self Fuel Rate ", self.fuel_rate)

        # assign value to hr_period field
        # self.hr_period = self.env['hr.period'].search([('state', '=', 'open')])  # 'hr.period' model missing

        # assign value to fuel_rate field
        if not self.fuel_rate:
            self.fuel_rate = 0.0

    def call_pre_process_payroll(self):
        if not self.hr_period:
            raise UserError(_("Please select a payroll period."))

        p_id = self.hr_period.id
        f_rate = self.fuel_rate or 0.0
        cr = self.env.cr
        cr.execute("SELECT pre_process_payroll(%s, %s)", (p_id, f_rate))
        cr.commit()
        print("Pre Process Payroll Executed")
        # cr.close()