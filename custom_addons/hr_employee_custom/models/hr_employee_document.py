# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


# -----------------------------------------------------------------------
# Configuration model — Document Types (managed from Settings / Config)
# -----------------------------------------------------------------------
class HrDocumentType(models.Model):
    _name = 'hr.document.type'
    _description = 'HR Document Type'
    _rec_name = 'name'
    _order = 'name asc'

    name = fields.Char(
        string='Document Type',
        required=True,
        help='Name of the document type (e.g. Employment Letter, MC, PL …)',
    )
    code = fields.Char(
        string='Code',
        help='Short code for the document type (e.g. EL, MC, PL)',
    )
    description = fields.Text(
        string='Description',
        help='Optional description of this document type',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        'A document type with this name already exists.',
    )

    def _check_hr_management_rights(self):
        user = self.env.user
        is_hr = (
            user.has_group('hr.group_hr_user')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )
        if not is_hr and not self.env.su:
            raise UserError(_("Only HR Officers and Administrators can create, edit, or delete Employee Documents."))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_hr_management_rights()
        return super().create(vals_list)

    def write(self, vals):
        self._check_hr_management_rights()
        return super().write(vals)

    def unlink(self):
        """Soft delete: Set active=False for all records instead of deleting from DB."""
        self._check_hr_management_rights()
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Main Document model
# -----------------------------------------------------------------------
class HrEmployeeDocument(models.Model):
    _name = 'hr.employee.document'
    _description = 'Employee Document'
    _rec_name = 'name'
    _order = 'issue_date desc, id desc'

    # ---------------------------------------------------------------
    # Core fields
    # ---------------------------------------------------------------
    name = fields.Char(
        string='Document Number',
        required=True,
        help='Unique document reference / number',
    )
    document_name = fields.Char(
        string='Document Name',
        help='Descriptive name of the document',
    )
    employee_ref = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ---------------------------------------------------------------
    # Classification — Many2one to configurable Document Type table
    # ---------------------------------------------------------------
    document_type_id = fields.Many2one(
        comodel_name='hr.document.type',
        string='Document Type',
        ondelete='restrict',
        help='Select the document type from the configured list.',
    )

    # ---------------------------------------------------------------
    # Dates & notification
    # ---------------------------------------------------------------
    issue_date = fields.Date(
        string='Issue Date',
        default=fields.Date.today,
    )
    expiry_date = fields.Date(
        string='Expiry Date',
    )
    notification_type = fields.Selection(
        selection=[
            ('email', 'Email'),
            ('sms',   'SMS'),
            ('both',  'Email & SMS'),
        ],
        string='Notification Type',
    )
    before_days = fields.Integer(
        string='Days',
        default=0,
        help='Number of days before expiry to send the notification',
    )

    # ---------------------------------------------------------------
    # Attachment — base64 stored directly in PostgreSQL DB column.
    # attachment=False  →  no delegation to ir.attachment filestore.
    # attachment_filename → tells Odoo the original filename so it
    #   serves the correct Content-Type (PDF opens inline, images
    #   preview, any other file is offered as a download).
    # ---------------------------------------------------------------
    attachment = fields.Binary(
        string='Attachment',
        attachment=False,
        help='Upload a PDF, image, or any document file. '
             'Stored as base64 in the database.',
    )
    attachment_filename = fields.Char(
        string='Attachment Filename',
    )

    # ---------------------------------------------------------------
    # Notes
    # ---------------------------------------------------------------
    description = fields.Text(string='Description')
    active = fields.Boolean(string='Active', default=True)

    def unlink(self):
        """Soft delete: Set active=False for all records instead of deleting from DB."""
        for rec in self:
            rec.write({'active': False})
        return True


# -----------------------------------------------------------------------
# Extend hr.employee — document_ids + document_count smart button
# -----------------------------------------------------------------------
class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    document_ids = fields.One2many(
        'hr.employee.document',
        'employee_ref',
        string='Documents',
    )

    document_count = fields.Integer(
        string='Document Count',
        compute='_compute_document_count',
        store=False,
    )

    @api.depends('document_ids')
    def _compute_document_count(self):
        for employee in self:
            employee.document_count = len(employee.document_ids)
