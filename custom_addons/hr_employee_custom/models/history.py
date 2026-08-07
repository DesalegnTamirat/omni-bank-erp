# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError


class DepartmentDetails(models.Model):
    _inherit = 'hr.employee'

    # @api.onchange('department_id')
    # def _onchange_department(self):
    #     employee_id = self.env['hr.employee'].search([('id', '=', self._origin.id)])
    #     vals = {
    #         'employee_id': self._origin.id,
    #         'employee_name': employee_id.name,
    #         'updated_date': datetime.now(),
    #         'changed_field': 'Department',
    #         'current_value': self.department_id.name
    #
    #     }
    #     self.env['department.history'].sudo().create(vals)



    # @api.onchange('job_id')
    # def onchange_job_id(self):
    #     employee_id = self.env['hr.employee'].search([('id', '=', self._origin.id)])
    #     vals = {
    #         'employee_id': self._origin.id,
    #         'employee_name': employee_id.name,
    #         'updated_date': datetime.today(),
    #         'changed_field': 'Job Position',
    #         'current_value': self.job_id.name
    #
    #     }
    #     self.env['department.history'].sudo().create(vals)

    @api.onchange('timesheet_cost')
    def _onchange_timesheet_cost(self):
        employee_id = self.env['hr.employee'].search([('id', '=', self._origin.id)])
        vals = {
            'employee_id': self._origin.id,
            'employee_name': employee_id.name,
            'updated_date': datetime.now(),
            'current_value': self.timesheet_cost
        }
        self.env['timesheet.cost'].sudo().create(vals)


    def department_details(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Job History"),
                'view_mode': 'tree',
                'res_model': 'department.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)],
            }
        elif res_user.has_group('__export__.res_groups_139_2fb4a56d'):
            return {
                'name': _("Job History"),
                'view_mode': 'tree',
                'res_model': 'department.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)],
            }
        elif self.id == self.env.user.employee_id.id:
            return {
                'name': _("Job History"),
                'view_mode': 'tree',
                'res_model': 'department.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
            }
        else:
            raise UserError('You cannot access this field!!!!')

    def transfer_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Transfer History"),
                'view_mode': 'tree',
                'res_model': 'transfer.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        if self.id == self.env.user.employee_id.id:
            return {
                'name': _("Transfer History"),
                'view_mode': 'tree',
                'res_model': 'transfer.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')

    def training_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Training History"),
                'view_mode': 'tree',
                'res_model': 'training.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        if self.id == self.env.user.employee_id.id:
            return {
                'name': _("Training History"),
                'view_mode': 'tree',
                'res_model': 'training.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')
    def re_instated_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Re instated History"),
                'view_mode': 'tree',
                'res_model': 're.instated.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        if self.id == self.env.user.employee_id.id:
            return {
                'name': _("Re instated History"),
                'view_mode': 'tree',
                'res_model': 're.instated.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')

    def job_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("job History"),
                'view_mode': 'tree',
                'res_model': 'job.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        if self.id == self.env.user.employee_id.id:
            return {
                'name': _("job History"),
                'view_mode': 'tree',
                'res_model': 'job.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')
    def time_sheet(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Timesheet Cost Details"),
                'view_mode': 'tree',
                'res_model': 'timesheet.cost',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        elif self.id == self.env.user.employee_id.id:
            return {
                'name': _("Timesheet Cost Details"),
                'view_mode': 'tree',
                'res_model': 'timesheet.cost',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')


    def salary_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Salary History"),
                'view_mode': 'tree',
                'res_model': 'salary.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        elif self.id == self.env.user.employee_id.id:
            return {
                'name': _("Salary History"),
                'view_mode': 'tree',
                'res_model': 'salary.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')


    def contract_history(self):
        res_user = self.env['res.users'].search([('id', '=', self._uid)])
        if res_user.has_group('hr.group_hr_manager'):
            return {
                'name': _("Contract History"),
                'view_mode': 'tree',
                'res_model': 'contract.history',
                'type': 'ir.actions.act_window',
                'target': 'new',
                'domain': [('employee_id', '=', self.id)]
            }
        if self.id == self.env.user.employee_id.id:
            return {
                'name': _("Contract History"),
                'view_mode': 'tree',
                'res_model': 'contract.history',
                'type': 'ir.actions.act_window',
                'target': 'new'
            }
        else:
            raise UserError('You cannot access this field!!!!')


class WageDetails(models.Model):
    _inherit = 'hr.contract'

    salary_rule_status = fields.Char(string='Salary Rule Status', default="New")
    @api.onchange('wage')
    def onchange_wage(self):
        vals = {
            'employee_id': self.employee_id.id,
            'employee_name': self.employee_id,
            'updated_date': datetime.today(),
            'current_value': self.wage,
            'salary_element': 'Basic Salary'

        }
        self.env['salary.history'].sudo().create(vals)

    # @api.onchange('hra')
    # def onchange_hra(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.hra,
    #         'salary_element': 'House Rent Allowance'
    #     }
    #     self.env['salary.history'].sudo().create(vals)

    # @api.onchange('da')
    # def onchange_da(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.da,
    #         'salary_element': 'Daily Allowance'
    #
    #     }
    #     self.env['salary.history'].sudo().create(vals)
    # @api.onchange('travel_allowance')
    # def onchange_travel_allowance(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.travel_allowance,
    #         'salary_element': 'Travel Allowance'
    #
    #     }
    #     self.env['salary.history'].sudo().create(vals)
    #
    # @api.onchange('meal_allowance')
    # def onchange_meal_allowance(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.meal_allowance,
    #         'salary_element': 'Meal Allowance'
    #
    #     }
    #     self.env['salary.history'].sudo().create(vals)
    #
    # @api.onchange('medical_allowance')
    # def onchange_medical_allowance(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.medical_allowance,
    #         'salary_element': 'Medical Allowance'
    #
    #     }
    #     self.env['salary.history'].sudo().create(vals)
    #
    # @api.onchange('other_allowance')
    # def onchange_other_allowance(self):
    #     vals = {
    #         'employee_id': self.employee_id.id,
    #         'employee_name': self.employee_id,
    #         'updated_date': datetime.today(),
    #         'current_value': self.other_allowance,
    #         'salary_element': 'Other Allowance'
    #
    #     }
    #     self.env['salary.history'].sudo().create(vals)


    @api.onchange('name')
    def onchange_name(self):
        vals = {
            'employee_id': self.employee_id.id,
            'employee_name': self.employee_id,
            'updated_date': datetime.today(),
            'changed_field': 'Contract Reference',
            'current_value': self.name,

        }
        self.env['contract.history'].create(vals)

    @api.onchange('date_start')
    def onchange_datestart(self):
        vals = {
            'employee_id': self.employee_id.id,
            'employee_name': self.employee_id,
            'updated_date': datetime.today(),
            'changed_field': 'Start Date',
            'current_value': self.date_start,

        }
        self.env['contract.history'].create(vals)

    @api.onchange('date_end')
    def onchange_dateend(self):
        vals = {
            'employee_id': self.employee_id.id,
            'employee_name': self.employee_id,
            'updated_date': datetime.today(),
            'changed_field': 'End Date',
            'current_value': self.date_end,

        }
        self.env['contract.history'].create(vals)


class DepartmentHistory(models.Model):
    _name = 'department.history'

    employee_id = fields.Many2one('hr.employee', string='Employee Name')
    employee_name = fields.Char(string='Employee Name', help="Name")
    job_name = fields.Many2one('employee.job', string='Job Name')
    job_grade = fields.Many2one('employee.grade', string='Grade')
    new_job_title = fields.Many2one('hr.job', string='Position', help="Position")
    job_history_start_date = fields.Date(string='Job History Start Date', help="Job History Start Date")
    job_history_end_date = fields.Date(string='Job History End Date', help="Job History End Date")
    reason = fields.Char(string='Reason for Change ', help="Reason for Change ")
    officer_id = fields.Integer(string='Officer ID', help="Assigned Officer")
    # From bunna_hr_addons
    operating_unit = fields.Many2one('operating.unit', string='Operating Unit',
                                     help="Operating Unit")

class TimesheetCost(models.Model):
    _name = 'timesheet.cost'

    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Name', help="Name")
    updated_date = fields.Date(string='Updated On', help="Updated Date of Time Sheet")
    current_value = fields.Char(string='Current Cost', help="Updated Value of Time Sheet")


class SalaryHistory(models.Model):
    _name = 'salary.history'

    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Name', help="Name")
    updated_date = fields.Date(string='Updated On', help="Salary Updated Date")
    salary_element = fields.Char(string='Salary Element', help="Updated Salary Element")
    current_value = fields.Float(string='Current Value', help="Updated Value")
    old_value = fields.Float(string='Old Value', help="Old Value")
    total_value=fields.Float(string="Total Value")
    payroll_period_id =fields.Integer(string='Payroll Period Id')
    contract_id=fields.Integer(string='Contract Id')
    start_interval=fields.Integer(string='Start Interval')
    end_interval=fields.Integer(string='End Interval')	
    base_salary=fields.Float(string='Base Salary')
    factor=fields.Float(string='Factor')


class ContractHistory(models.Model):
    _name = 'contract.history'

    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Name', help="Name")
    updated_date = fields.Date(string='Updated On', help="Contract Updated Date")
    changed_field = fields.Char(string='Changed Field', help="Updated Field's")
    current_value = fields.Char(string='Current Contract', help="Updated Value of Contract")

class transfer_history(models.Model):
    _name = 'transfer.history'
    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Name', help="Name")
    from_operating_unit = fields.Many2one('operating.unit',string='From Operating Unit', help="From Operating Unit")
    from_operating_unit2 = fields.Many2one('operating.unit',string='From Operating Unit', help="From Operating Unit")
    from_department = fields.Many2one('hr.department',string='From Department', help="From Department")
    from_department2 = fields.Many2one('hr.department',string='From Department', help="From Department")
    from_position = fields.Many2one('hr.job',string='From Position', help="From Position")
    from_position2 = fields.Many2one('hr.job',string='From Position', help="From Position")
    from_grade = fields.Many2one('employee.grade',string="From Grade ", help="From Grade")
    from_grade2 = fields.Many2one('employee.grade',string="From Grade ", help="From Grade")
    date = fields.Date(string='Date', help="Date")
    transfer_reason=fields.Char(string="Transfer Reason",help="Transfer Reason")

    date2 = fields.Date(string='Date', help="Date")
    to_operting_unit = fields.Many2one('operating.unit',string='To Operting Unit', help="To Operting Unit")
    to_operting_unit2 = fields.Many2one('operating.unit',string='To Operting Unit', help="To Operting Unit")
    to_department = fields.Many2one('hr.department',string='To Department', help="To Department")
    to_department2 = fields.Many2one('hr.department',string='To Department', help="To Department")
    to_position = fields.Many2one('hr.job',string='To Position', help="To Position")
    to_position2 = fields.Many2one('hr.job',string='To Position', help="To Position")
    to_grade = fields.Many2one('employee.grade',string='To Grade', help="To Grade")
    to_grade2 = fields.Many2one('employee.grade',string='To Grade', help="To Grade")

class TrainingHistory(models.Model):
    _name = 'training.history'
    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Id', help="Employee")
    training_name = fields.Char(string='Training Name', help="Training Name")
    training_type  = fields.Selection([('internal', 'Internal'),('external', 'External')],
        string='Training Type', default='internal')
    name_of_institution = fields.Char(string='Name of Institution', help="Name of Institution")
    start_date = fields.Date(string='Start Date', help="Start Date")
    end_date = fields.Date(string='End Date', help="End Date")
    status = fields.Char(string='Status', help="Status")
    comments = fields.Char(string='Comments', help="Comments")


class Re_instated_History(models.Model):
    _name = 're.instated.history'
    employee_id = fields.Integer(string='Employee Id', help="Employee")
    employee_name = fields.Char(string='Employee Id', help="Employee")
    # employee_name = fields.Many2one('hr.employee', 'Employee Name')
    new_job_grade = fields.Many2one('employee.grade', 'New Job Grade')
    new_job_title = fields.Many2one('hr.job', string='Job Title', help="Job Title")
    new_salary = fields.Char(string='New Salary', help="New Salary")
    salary = fields.Integer(string='New Salary', help="New Salary")
    date = fields.Date(string='Date', help="Date")
    reason = fields.Char(string='Reason ', help="Reason ")
    other_info = fields.Char(string='Other Info ', help="Other Info ")



