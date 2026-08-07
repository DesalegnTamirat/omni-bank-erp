# -*- coding: utf-8 -*-

from odoo import models, fields,api
from odoo import tools


# PAYROLL MODULE NOT INSTALLED — this SQL-view model queries the
# hr_salary_rule / position_salary_rule / grade_salary_rule tables directly,
# which only exist once a payroll module (e.g. hr_payroll_community) is
# installed. Commented out entirely until then; uncomment to restore.
# class ActingPositionRule(models.Model):
#     _name = 'acting.position.rule'
#     _auto = False
#     _description = 'Acting Allowance Position Rule'

#     position_id=fields.Many2one("hr.job",string="Position Id")
#     position_name=fields.Char(string="Position Name")
#     salary_rule_id=fields.Many2one("hr.salary.rule", string="Salary Rule", help='Salary Rule')
#     salary_rule_name=fields.Char(string="Salary Rule Name")
#     internal_name=fields.Char(string="Internal Name")
#     contract_rule_value=fields.Float(string="Value")
    

#     #@api.model_cr
#     def init(self):

#             tools.drop_view_if_exists(self._cr, 'acting_position_rule')
#             self._cr.execute("""
#                 CREATE OR REPLACE VIEW acting_position_rule AS (
#                 select 	row_number() OVER () AS id,hj.id position_id, hj."name" position_name,hsr.id salary_rule_id, hsr."name" salary_rule_name ,hsr.internal_name, 
#                 case 
# 				when hsr.name='Fuel Allowance' then	
# 				psr.value*hsr.value
# 				else psr.value
# 				end contract_rule_value 
#                 from 	position_salary_rule psr, hr_job hj,hr_salary_rule hsr
#                 where 	psr.position_id=hsr.id 
#                 and 	psr.position=hj.id 
#                 and 	hsr.active ='Y'
#                 and 	hsr.category_id in (1,2)
#                 and 	hsr.id>=95
#                 union 
#                 select 	row_number() OVER () AS id,hj.id position_id, hj.name position_name,hsr.id salary_rule_id, hsr."name" salary_rule_name,hsr.internal_name, 
#                 case 
# 				when hsr.name='Fuel Allowance' then	
# 				gsr.value*hsr.value
# 				else gsr.value
# 				end contract_rule_value
#                 from 	grade_salary_rule gsr, employee_grade eg, hr_salary_rule hsr,hr_job hj
#                 where 	gsr.grade_id=hsr.id 
#                 and 	gsr.grade2=eg.id
#                 and 	hj.grade =eg.id
#                 and 	hsr.active ='Y'
#                 and 	hsr.id>=95
#                 and 	hsr.category_id in (1,2)
#                 and 	hsr.id not in (select distinct position_id from position_salary_rule)
#                 order by 2,4
#                 )
#                 """)
