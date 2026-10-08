# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployeeChangeHistory(models.Model):
    """
    EM-073: Time-stamped and Auditable History of all Employee Master Data Changes.
    Maintains a complete log of old value, new value, change type, requester, and timestamp.
    """
    _name = 'hr.employee.change.history'
    _description = 'Employee Master Data Change History Audit'
    _order = 'applied_date desc, id desc'

    name = fields.Char(string='Audit Ref', required=True, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade', index=True)
    change_request_id = fields.Many2one('hr.employee.change.request', string='Change Request', ondelete='set null', index=True)
    field_id = fields.Many2one('ir.model.fields', string='Field', ondelete='set null')
    field_name = fields.Char(string='Field Technical Name')
    field_description = fields.Char(string='Field Description', required=True)
    old_value = fields.Text(string='Old Value')
    new_value = fields.Text(string='New Value')
    change_type = fields.Selection([
        ('name', 'Name Change'),
        ('education', 'Education & Qualifications'),
        ('marital', 'Marital Status'),
        ('dependent', 'Dependents / Relatives'),
        ('contact', 'Phone & Email'),
        ('emergency', 'Emergency Contact'),
        ('address', 'Residential Address'),
        ('job_org', 'Job & Organizational'),
        ('other', 'Other Field'),
    ], string='Change Type', default='other', required=True)
    applied_by_id = fields.Many2one('res.users', string='Applied By', default=lambda self: self.env.user, required=True)
    applied_date = fields.Datetime(string='Applied Date/Time', default=fields.Datetime.now, required=True, index=True)
    notes = fields.Text(string='Notes / Reason')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.employee.change.history') or _('New')
        return super().create(vals_list)
