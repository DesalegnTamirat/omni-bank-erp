# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AttendanceGateException(models.Model):
    _name = 'attendance.gate.exception'
    _description = 'ERP Gate Access Exemption'
    _order = 'create_date desc'
    _rec_name = 'employee_id'

    @api.model
    def init(self):
        super().init()
        try:
            self.env.cr.execute("""
                UPDATE attendance_gate_exception
                SET state = 'submitted'
                WHERE state IS NULL
            """)
        except Exception:
            pass

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
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
    ], string="Status", default='draft', required=True, index=True, copy=False)

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

    @api.constrains('employee_id', 'active', 'state')
    def _check_unique_employee(self):
        for rec in self:
            if not rec.active or rec.state == 'draft':
                continue
            domain = [
                ('employee_id', '=', rec.employee_id.id),
                ('id', '!=', rec.id),
                ('active', '=', True),
                ('state', '=', 'submitted'),
            ]
            if self.search_count(domain):
                raise ValidationError(_("An active exemption record already exists for employee '%s'.") % rec.employee_id.name)

    def write(self, vals):
        for rec in self:
            if rec.state == 'submitted' and not self.env.su:
                disallowed = {'employee_id', 'reason'} & set(vals.keys())
                if disallowed:
                    raise ValidationError(_("Submitted gate exemptions cannot be modified. Revoke and create a new exemption if needed."))
        return super().write(vals)

    def action_submit(self):
        for rec in self:
            rec.write({'state': 'submitted', 'active': True})
        emp_name = self[0].employee_id.name if self and self[0].employee_id else "Employee"
        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _("ERP Gate Exemption Submitted"),
                'subtitle': _("Gate bypass active for %s") % emp_name,
                'type': 'success',
                'icon': 'fa-check-circle',
                'reload': True,
            }
        }

    def action_activate(self):
        for rec in self:
            rec.write({'active': True})
        emp_name = self[0].employee_id.name if self and self[0].employee_id else "Employee"
        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _("ERP Gate Exemption Active"),
                'subtitle': _("Gate bypass granted for %s") % emp_name,
                'type': 'success',
                'icon': 'fa-shield-alt',
                'reload': True,
            }
        }

    def action_deactivate(self):
        for rec in self:
            rec.write({'active': False})
        emp_name = self[0].employee_id.name if self and self[0].employee_id else "Employee"
        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _("ERP Gate Exemption Revoked"),
                'subtitle': _("Gate restriction enforced for %s") % emp_name,
                'type': 'warning',
                'icon': 'fa-ban',
                'reload': True,
            }
        }
