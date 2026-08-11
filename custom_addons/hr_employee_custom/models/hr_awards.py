# -*- coding: utf-8 -*-
from odoo import models, fields, api


class Hr_Awards_received_Info(models.Model):
    """Table for keep employee family information"""
    _name = 'hr.awards'
    _description = 'HR Awards Received'
    _rec_name = 'award_name'
    employee_id = fields.Many2one('hr.employee', string="Employee Name ", help='Select corresponding Employee')
    ref_num = fields.Char(string='Ref Num')
    employee_name = fields.Many2one('hr.employee', string="Employee Name", help='Select corresponding Employee')
    award_name = fields.Many2one('service.award', string="Award Name", help='Select corresponding Award')
    award_type = fields.Char(string="Award Type")
    institution_name = fields.Char(string="Institution Name", help="Institution Name")
    fiscal_year = fields.Integer(string="Fiscal Year")
    award_cost = fields.Integer(string="Award Amount")
    date_awarded = fields.Date(string="Date Awarded")
    comments = fields.Char(string="Comments")

    @api.onchange('award_name')
    @api.depends('award_name')
    def onchange_employee_name(self):
        award = self.env['service.award'].search([('id', '=', self.award_name.id)])
        self.award_type = award.award_type

