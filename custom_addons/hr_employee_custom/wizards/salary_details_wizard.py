# -*- coding: utf-8 -*-
from datetime import datetime
from dateutil import relativedelta

from odoo import fields, models
from odoo import _
from odoo.exceptions import UserError


class salary_rules(models.TransientModel):
    _name = 'populate.salary.details'
    _description = 'populate.salary.details'

    job_grade = fields.Many2one("employee.grade", string='Job Grade', help="Job Grade")

    def populate(self):
        # Call the hr_contract() function
        print("executing the PL/PGSQL Function hr_contract")
        self.env.cr.execute('SELECT hr_contract()')

    def cancel(self):
        print("self",self)
