# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployeeChangeFieldConfig(models.Model):
    """
    EM-069: Configurable Rules for Employee Master Data Change Requests.
    Defines which fields require mandatory supporting document attachments.
    """
    _name = 'hr.employee.change.field.config'
    _description = 'Master Data Change Field Configuration'
    _order = 'category, name'

    name = fields.Char(string='Rule Name', required=True, translate=True)
    field_id = fields.Many2one(
        'ir.model.fields',
        string='Employee Field',
        required=True,
        domain="[('model', '=', 'hr.employee')]",
        ondelete='cascade'
    )
    field_name = fields.Char(related='field_id.name', string='Field Name', store=True, readonly=True)
    category = fields.Selection([
        ('personal', 'Personal Information'),
        ('contact', 'Contact Information'),
        ('identification', 'Identification Information'),
        ('education', 'Educational Information'),
        ('professional', 'Professional Information'),
        ('employment', 'Employment Information'),
        ('organization', 'Organizational Assignment'),
        ('position', 'Position Information'),
        ('salary_benefits', 'Salary and Benefits'),
        ('bank_payment', 'Bank and Payment Information'),
        ('emergency', 'Emergency Contact'),
        ('other', 'Other Information'),
    ], string='Change Category', required=True, default='personal')
    requires_attachment = fields.Boolean(
        string='Requires Attachment?',
        default=True,
        help="If checked, any request attempting to modify this field must include at least one supporting document attachment."
    )
    help_text = fields.Text(
        string='Document Instructions',
        help="Guidance displayed to the requester explaining which document is required (e.g. Legal Name Change Evidence)."
    )
    active = fields.Boolean(string='Active', default=True)

    _unique_field_id = models.Constraint(
        'unique(field_id)',
        'A change document rule already exists for this field!'
    )
