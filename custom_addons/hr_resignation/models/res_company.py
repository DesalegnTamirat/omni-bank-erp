# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class ResCompany(models.Model):
    _inherit = 'res.company'

    signatory_employee_id = fields.Many2one(
        'hr.employee',
        string="Authorized HR Manager",
        default=lambda self: self._default_signatory_employee_id(),
        ondelete='set null'
    )
    signatory_job_id = fields.Many2one(
        'hr.job',
        string="Signatory Job Position",
        default=lambda self: self._default_signatory_job_id(),
        ondelete='set null'
    )

    certificate_signatory_name = fields.Char(
        string="Signatory Display Name",
        compute="_compute_signatory_details",
        store=True,
        readonly=False
    )
    certificate_signatory_title = fields.Char(
        string="Signatory Display Title",
        compute="_compute_signatory_details",
        store=True,
        readonly=False
    )

    certificate_signature = fields.Binary(
        string="Authorized Signature",
        attachment=False,
        help="Upload transparent PNG or JPG image of the authorized signatory's signature."
    )
    certificate_stamp = fields.Binary(
        string="Official Stamp / Seal",
        attachment=False,
        help="Upload transparent PNG or JPG image of the official company stamp or seal."
    )
    certificate_signing_mode = fields.Selection(
        [
            ('digital', 'Digital (Include Uploaded Signature and Stamp)'),
            ('manual', 'Manual (Print Blank for Physical Hand Signing and Stamping)'),
        ],
        string="Certificate Print Option",
        default='digital',
        help="Choose 'Digital' to print with uploaded signature and stamp, or 'Manual' to leave blank space for physical hand signing and stamping."
    )

    @api.model
    def _default_signatory_employee_id(self):
        # 1. Automatically pick user assigned to "HR Resignation: HR Manager" group
        hr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
        if hr_group and hr_group.user_ids:
            active_hr_user = hr_group.user_ids.filtered(lambda u: u.active)[:1]
            if active_hr_user:
                emp = self.env['hr.employee'].sudo().search([('user_id', '=', active_hr_user.id)], limit=1)
                if emp:
                    return emp.id
        # Fallback to current logged-in employee if no resignation manager is found
        emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return emp.id if emp else False

    @api.model
    def _default_signatory_job_id(self):
        emp_id = self._default_signatory_employee_id()
        if emp_id:
            emp = self.env['hr.employee'].sudo().browse(emp_id)
            job = getattr(emp, 'job_position', False) or getattr(emp, 'job_id', False)
            if job:
                return job.id
        return False

    @api.depends('signatory_employee_id', 'signatory_employee_id.name', 'signatory_job_id', 'signatory_job_id.name')
    def _compute_signatory_details(self):
        for rec in self:
            if rec.signatory_employee_id:
                rec.certificate_signatory_name = rec.signatory_employee_id.name
            elif not rec.certificate_signatory_name:
                rec.certificate_signatory_name = "Director, Human Resource Management"

            if rec.signatory_job_id:
                rec.certificate_signatory_title = rec.signatory_job_id.name
            elif not rec.certificate_signatory_title:
                rec.certificate_signatory_title = "Human Resource Management Division"

    @api.onchange('signatory_employee_id')
    def _onchange_signatory_employee_id(self):
        if self.signatory_employee_id:
            self.certificate_signatory_name = self.signatory_employee_id.name
            job = getattr(self.signatory_employee_id, 'job_position', False) or getattr(self.signatory_employee_id, 'job_id', False)
            if job:
                self.signatory_job_id = job.id
                self.certificate_signatory_title = job.name
            else:
                self.signatory_job_id = False
                self.certificate_signatory_title = False

    @api.onchange('signatory_job_id')
    def _onchange_signatory_job_id(self):
        if self.signatory_job_id:
            self.certificate_signatory_title = self.signatory_job_id.name
