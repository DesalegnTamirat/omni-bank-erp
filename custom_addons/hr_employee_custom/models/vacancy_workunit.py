# -*- coding: utf-8 -*-

from odoo import models, fields,api
from odoo import tools


class VacancyWorkunit(models.Model):
    _name = 'vacancy.workunit'
    _auto = False
    _description = 'Vacancy Workunit'

    workunit_id=fields.Integer(string="Workunit Id")
    workunit_name=fields.Char(string="Workunit Name")
    _rec_name = 'workunit_name'
    
    #@api.model_cr
    def init(self):
            tools.drop_view_if_exists(self.env.cr, 'vacancy_workunit')
            self.env.cr.execute("""
                CREATE OR REPLACE VIEW vacancy_workunit AS (
                select 	row_number() OVER () AS id,id workunit_id, name workunit_name from 
                operating_unit
                )
                """)
