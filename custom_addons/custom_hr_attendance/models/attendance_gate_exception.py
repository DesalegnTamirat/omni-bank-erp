# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AttendanceGateException(models.Model):
    _name = 'attendance.gate.exception'
    _description = 'ERP Gate Access Exemption'
    _order = 'create_date desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        required=True,
        index=True,
        ondelete='cascade',
        help="Employee permitted to access ERP modules without checking in.",
    )
    user_id = fields.Many2one(
        'res.users',
        related='employee_id.user_id',
        string="Related User",
        readonly=True,
        store=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        related='employee_id.department_id',
        string="Department",
        readonly=True,
        store=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        related='employee_id.job_id',
        string="Job Position",
        readonly=True,
        store=True,
    )
    reason = fields.Char(
        string="Reason for Exemption",
        help="Business justification (e.g. Executive, Urgent Field Mission, System Support).",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        help="Toggle off to temporarily revoke the exemption without deleting the record.",
    )
    created_by = fields.Many2one(
        'res.users',
        string="Granted By",
        default=lambda self: self.env.user,
        readonly=True,
    )

    @api.constrains('employee_id')
    def _check_unique_employee(self):
        for rec in self:
            domain = [('employee_id', '=', rec.employee_id.id), ('id', '!=', rec.id)]
            if self.search_count(domain):
                raise ValidationError(_("An exemption record already exists for employee '%s'.") % rec.employee_id.name)
