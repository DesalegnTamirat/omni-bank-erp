# -*- coding: utf-8 -*-
from datetime import datetime
from dateutil import relativedelta

from odoo import models, fields, api

class salary_rules(models.TransientModel):
    _name = 'populate.salary.information'
    _description = 'populate.salary.information'

    job_grade = fields.Many2one("employee.grade",string='Job Grade',help="Job Grade")

    def populate(self):
        self.env.cr.execute("SELECT hr_contract()")
        self.env.cr.commit()
        print('contract rules executed')
        print("Job Grade ",job.grade)
        return {'type': 'ir.actions.act_window_close'}

    def cancel(self):
        print("self",self)

    # def run_contract_rules(self):
    #     self.env.cr.execute("SELECT contract_rules()")
    #     self.env.cr.commit()
    #     print('contract rules executed')
    #     return {'type': 'ir.actions.act_window_close'}