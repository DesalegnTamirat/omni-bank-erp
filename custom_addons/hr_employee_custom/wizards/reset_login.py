from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class reset_login_details(models.TransientModel):
    _name = 'reset.login'
    _description = 'Reset Login Information'

    date = fields.Date(string='Date',help="Date")
    user_name = fields.Many2one("hr.employee", string='Employee Name',required=True)
    user_login = fields.Char(string="User Login",required=True)

    def reset_login(self):
        p_id = self.user_name.user_id
        n_id=self.user_login
        print("Employee Id: ", p_id)
        print("Employee Name: ", n_id)


        if not self.user_login:
            raise UserError(_("Please Enter a Valid Login for the Employee."))

        employee = self.user_name
        employee.user_id.login = self.user_login

        print("Username Reset")

        # cr = self.env.cr
        # cr.execute("SELECT pre_process_payroll(%s,%s)", (p_id,n_id ))
        # cr.commit()
        # print("Username Reset")
        # cr.close()