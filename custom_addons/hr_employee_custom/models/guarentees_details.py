# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

class Guarentees(models.Model):
    _name = "guarentees.details"
    _description = "Guarantee Info"
    _rec_name = "type_guarantee"
    
    service_request_id = fields.Many2one('employee.service.request', string="Service Request", ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string="Employee", help='Select corresponding Employee')
    ref_num = fields.Char("Ref Num")
    type_guarantee = fields.Char("Type of Guarantee")
    effective_date = fields.Date("Effective Date")
    name_of_staff = fields.Many2one('hr.employee', string="Name Of Staff", help='Select corresponding Employee')
    external_person_name = fields.Char(string="External Person Name", help="External Person Name")
    guarantee_amount = fields.Float(string="Guarantee Amount", help="Guarantee Amount")
    name_of_institution = fields.Char("Name of Institution")
    state = fields.Selection([
        ('active', 'Active'), 
        ('inactive', 'In Active')
    ], string='Status')
    type = fields.Selection([
        ('internal', 'Internal'), 
        ('external', 'External')
    ], string='Type', default='internal')
    status = fields.Char("Status of the promises")

    def approve(self):
        for record in self:
            guarentee_details = self.env["hr.employee"].search([("user_id", "=", self.env.uid)], limit=1)
            vals = {
                "employee_id": guarentee_details.id if guarentee_details else False,
                "ref_num": record.ref_num,
                "type_guarantee": record.type_guarantee,
                "effective_date": record.effective_date,
                "name_of_staff": record.name_of_staff.id if record.name_of_staff else False,
                "name_of_institution": record.name_of_institution,
                "type": record.type,
                "status": record.status,
            }
            self.env["guarentees.details"].create(vals)
            vals2 = {
                "employee_id": record.employee_id.id if record.employee_id else False,
                "status": "approved",
            }
            if record.employee_id:
                status_recs = self.env["guarentees.details"].search([('employee_id', '=', record.employee_id.id)])
                status_recs.write(vals2)


class HrEmployeeGuaranteeInherit(models.Model):
    _inherit = 'hr.employee'

    gurentee_ids = fields.One2many('guarentees.details', 'employee_id', string='Guarantee')
    guarantee_count = fields.Integer(
        string='Guarantee Count',
        compute='_compute_guarantee_count',
    )

    def _compute_guarantee_count(self):
        for employee in self:
            employee.guarantee_count = self.env['guarentees.details'].search_count(
                [('employee_id', '=', employee.id)]
            )

