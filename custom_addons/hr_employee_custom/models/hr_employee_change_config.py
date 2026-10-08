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
        ('name', 'Name Change'),
        ('education', 'Education & Qualifications'),
        ('marital', 'Marital Status'),
        ('dependent', 'Dependents / Relatives'),
        ('contact', 'Phone & Email'),
        ('emergency', 'Emergency Contact'),
        ('address', 'Residential Address'),
        ('work_permit', 'Work Permit & Visa'),
        ('job_org', 'Job & Organizational'),
        ('other', 'Other Field'),
    ], string='Change Category', required=True, default='other')
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

    _sql_constraints = [
        ('unique_field_id', 'unique(field_id)', 'A change document rule already exists for this field!')
    ]
