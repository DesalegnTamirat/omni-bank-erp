from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class PostprocessingSalaryInformationDetails(models.TransientModel):
    _name = 'post.processing.salary.information'
    _description = 'Post processing Salary Information'

    # commented out: 'hr.period' model does not exist in this module (belongs to an uninstalled payroll module)
    # hr_period = fields.Many2one("hr.period", string='Payroll Period', domain=[('state','=','open')])

    # def populate(self):
        # print("self Date : ", self.date)
        # print("self hr_period: ", self.hr_period)

        # # assign value to hr_period field
        # self.hr_period = self.env['hr.period'].search([('state', '=', 'open')])

        # # assign value to fuel_rate field

    def call_post_process_payroll(self):
        if not self.hr_period:
            raise UserError(_("Please select a payroll period."))

        p_id = self.hr_period.id
        
        cr = self.env.cr
        cr.execute("SELECT post_payroll_process(%s)", (p_id,))
        cr.commit()
        print("Post Process Payroll Executed")
        # cr.close()