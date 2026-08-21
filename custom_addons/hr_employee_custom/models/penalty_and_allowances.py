from odoo import api, models, fields, _
from odoo import models, fields
from odoo.http import request
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import smtplib
import base64
import mimetypes

class EmpAllowance(models.Model):
    _name = "emp.allowance"

    employee_id = fields.Many2one("hr.employee", string="Employee Id")
    # PAYROLL MODULE NOT INSTALLED — uncomment once hr.salary.rule exists.
    # allowance = fields.Many2one("hr.salary.rule", "Allowance name", domain="[('category_id', '=', 'Allowance')]")
    allowance_amount = fields.Float(string="Allowance Amount")
    contract_id = fields.Integer(string="Contract Id")
    structure_id = fields.Integer(string="Structure Id")
    allowance_date = fields.Date(string="Allowance Date")
    # allowance_id = fields.Integer(string="Allowance Id")
    status = fields.Selection(
        [("draft", "Draft"), ("transferred", "Transferred")],
        string="Status", default="draft")

# class EmployeeAllowance(models.Model):
#     _name = "allowances"
#
#     employee_id = fields.Many2one("hr.employee", string="Allowances")
#     allowance_type = fields.Many2one("Allowance name")
#     allowance_amount = fields.Float(string="Allowance Amount")
#     allowance_date = fields.Date(string="Allowance Date")
#
# class HrAllowance(models.Model):
#     _inherit = 'hr.employee'
#
#     allowance = fields.One2many('allowances', 'employee_id', string="Allowances")
#

# PAYROLL MODULE NOT INSTALLED — the 5 classes below extend hr.payslip,
# which requires a payroll module (e.g. hr_payroll_community). Commented
# out until that module is installed; uncomment to restore.
# class MarriageRuleInput(models.Model):
#     _inherit = 'hr.payslip'

#     def get_inputs(self, contract_ids, date_from, date_to):
#         res = super().get_inputs(contract_ids, date_from, date_to)
#         contract_obj = self.env['hr.version']
#         for i in contract_ids:
#             if contract_ids[0]:
#                 emp_id = contract_obj.browse(i[0].id).employee_id
#                 for result in res:
#                     if emp_id.allowance_amount != 0:
#                         if result.get('code') == 'MARRIAGE':
#                             result['amount'] = emp_id.allowance_amount
#         return res


# class FuneralAllowanceInput(models.Model):
#     _inherit = 'hr.payslip'

#     def get_inputs(self, contract_ids, date_from, date_to):
#         res = super().get_inputs(contract_ids, date_from, date_to)
#         contract_obj = self.env['hr.version']
#         for i in contract_ids:
#             if contract_ids[0]:
#                 emp_id = contract_obj.browse(i[0].id).employee_id
#                 for result in res:
#                     if emp_id.allowance_amount != 0:
#                         if result.get('code') == 'FUNERAL':
#                             result['amount'] = emp_id.allowance_amount
#         return res

# class FitnessAllowanceInput(models.Model):
#     _inherit = 'hr.payslip'

#     def get_inputs(self, contract_ids, date_from, date_to):
#         res = super().get_inputs(contract_ids, date_from, date_to)
#         contract_obj = self.env['hr.version']
#         for i in contract_ids:
#             if contract_ids[0]:
#                 emp_id = contract_obj.browse(i[0].id).employee_id
#                 for result in res:
#                     if emp_id.allowance_amount != 0:
#                         if result.get('code') == 'FITNESS':
#                             result['amount'] = emp_id.allowance_amount
#         return res

# class VacationAllowanceInput(models.Model):
#     _inherit = 'hr.payslip'

#     def get_inputs(self, contract_ids, date_from, date_to):
#         res = super().get_inputs(contract_ids, date_from, date_to)
#         contract_obj = self.env['hr.version']
#         for i in contract_ids:
#             if contract_ids[0]:
#                 emp_id = contract_obj.browse(i[0].id).employee_id
#                 for result in res:
#                     if emp_id.allowance_amount != 0:
#                         if result.get('code') == 'VACATION':
#                             result['amount'] = emp_id.allowance_amount
#         return res


# class DisciplinePenalityRuleInput(models.Model):
#     _inherit = 'hr.payslip'
    
#     def get_inputs(self, contract_ids, date_from, date_to):
#         res = super().get_inputs(contract_ids, date_from, date_to)
#         contract_obj = self.env['hr.version']
#         for contract_id in contract_ids:
#             if contract_id:
#                 emp_id = contract_obj.browse(contract_id[0].id).employee_id
#                 rec = self.env["discipline.action"].search([("employee_name", "=", emp_id.name), ("status", "=", "approved")])
#                 emp = self.env["hr.employee"].search([("name", "=", emp_id.name)])
#                 print("****************emp", emp)
#                 for result in res:
#                         for dt in emp.emp_disc_records_id:
#                             if dt.fine_imposed != 0 and dt.code == 'PENALTY':
#                                 print("************* dt", dt, self.date_from, dt.penalty_effective_date, self.date_to)
#                                 if self.date_from <= dt.penalty_effective_date and dt.penalty_effective_date <= self.date_to:
#                                     print("************", dt, dt.fine_imposed)
#                                     result['amount'] = dt.fine_imposed
                        
#         return res
#     # def get_inputs(self, contract_ids, date_from, date_to):
#         # res = super().get_inputs(contract_ids, date_from, date_to)
#         # contract_obj = self.env['hr.version']
#         # for i in contract_ids:
#             # if contract_ids[0]:
#                 # emp_id = contract_obj.browse(i[0].id).employee_id
#                 # print("*************emp_id",emp_id, emp_id.penalty_amount, emp_id.code)
#                 # for result in res:
#                     # if emp_id.penalty_amount != 0:
#                         # if emp_id.code == 'PENALTY':
#                             # result['amount'] = emp_id.penalty_amount
#                             # print("***********amount", result['amount'], 
# 							# emp_id.penalty_amount, emp_id.code)
                            
#         # return res


class HrVersion(models.Model):
    _inherit = 'hr.version'

    penalty_amount = fields.Float(string="Penalty Amount")#, compute="_compute_penalty_amount")
    code = fields.Char(string="Code")#, compute="_compute_code")
    allowance_amount = fields.Float(string="Allowance Amount")#, compute="_compute_allowance_amount")
    pf = fields.Float(string="Provident Fund")
    pension_co = fields.Float(string="Pension Company")
    pension_emp = fields.Float(string="Pension Employee")
    indemnity_tax = fields.Float(string="Indemnity Tax")
    total_cash_indemnity= fields.Float(string="Total Cash Indemnity")

    # def _compute_penalty_amount(self):
        # for val in self:
            # rec = self.env["discipline.action"].search([("employee_name", "=", val.employee_id.name), ("status", "=", "approved")])
            # if rec.fine_imposed:
                # self.penalty_amount = rec.fine_imposed
                # return self.penalty_amount
            # else:
                # self.penalty_amount = 0.0
                # return self.penalty_amount
    # def _compute_code(self):
        # for val in self:
            # rec = self.env["discipline.action"].search([("employee_name", "=", val.name), ("status", "=", "approved")])
            # if rec.fine_imposed:
                # self.code = "PENALTY"
                # return self.code
            # else:
                # self.code = ""
                # return self.code
    # def _compute_allowance_amount(self):
        # rec = self.env["emp.allowance"].search([("employee_id", "=", self.employee_id.name)])
        # self.allowance_amount = rec.allowance_amount
        # return self.allowance_amount


class HrContract(models.Model):
    _inherit = 'hr.employee'

    penalty_amount = fields.Float(string="Penalty Amount")#, compute="_compute_penalty_amount")
    code = fields.Char(string="Code")#, compute="_compute_code")
    allowance_amount = fields.Float(string="Allowance Amount")#, compute="_compute_allowance_amount")
    # allowance = fields.One2many('emp.allowance', 'employee_id', string="Allowances")

    # def _compute_code(self):
        # for val in self:
            # rec = self.env["discipline.action"].search([("employee_name", "=", val.name), ("status", "=", "approved")])
            # if rec.fine_imposed:
                # self.code = "PENALTY"
                # return self.code
            # else:
                # self.code = ""
                # return self.code
				
    # def _compute_penalty_amount(self):
        # for val in self:
            # rec = self.env["discipline.action"].search([("employee_name", "=", val.name), ("status", "=", "approved")])
            # if rec.fine_imposed:
                # self.penalty_amount = rec.fine_imposed
                # return self.penalty_amount
            # else:
                # self.penalty_amount = 0.0
                # return self.penalty_amount


    # def _compute_allowance_amount(self):
        # rec = self.env["emp.allowance"].search([("employee_id", "=", self.name)])
        # self.allowance_amount = rec.allowance_amount
        # return self.allowance_amount
