# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class EdsEducationAssistance(models.Model):
    _name = 'eds.education.assistance'
    _description = 'EDS Staff Education Assistance'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Request Ref', required=True, copy=False, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    program = fields.Char(string='Degree / Program Name', required=True, tracking=True)
    institution = fields.Char(string='Educational Institution / University', required=True, tracking=True)
    degree_level = fields.Selection([
        ('diploma', 'Diploma / Advanced Diploma'),
        ('bachelor', 'BSc / BA Degree'),
        ('master', 'MSc / MBA / MA Degree'),
        ('phd', 'PhD / Doctorate'),
        ('professional', 'Professional Qualification'),
    ], string='Degree Level', default='bachelor', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    tuition_amount = fields.Monetary(string='Requested Tuition Amount', currency_field='currency_id', required=True, tracking=True)
    approved_amount = fields.Monetary(string='Approved Reimbursement Amount', currency_field='currency_id', tracking=True)
    academic_progress = fields.Text(string='Academic Progress / Transcript Summary')
    proof_document = fields.Binary(string='Academic Transcript & Proof of Payment', attachment=True)
    proof_filename = fields.Char(string='Document Name')
    approval_state = fields.Selection([
        ('draft', 'Draft Request'),
        ('submitted', 'Submitted to Line Manager'),
        ('dept_approved', 'Department Head Approved'),
        ('ppdd_validated', 'PPDD Validated'),
        ('cpco_approved', 'CPCO Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval Status', default='draft', required=True, tracking=True)
    reimbursement_state = fields.Selection([
        ('pending', 'Pending Disbursement'),
        ('disbursed', 'Reimbursed / Paid'),
    ], string='Reimbursement Status', default='pending', tracking=True)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.education.assistance') or _('New')
        return super(EdsEducationAssistance, self).create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.approval_state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            rec.approval_state = 'submitted'
            rec.message_post(body=_("Education assistance request submitted for Department Head review."))

    def action_dept_approve(self):
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.approval_state != 'submitted':
                raise UserError(_('Only submitted requests can be approved by Department Head.'))
            rec.approval_state = 'dept_approved'
            rec.message_post(body=_("Education assistance approved by Department Head."))

    def action_ppdd_validate(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.approval_state != 'dept_approved':
                raise UserError(_('Only department-approved requests can be validated by PPDD.'))
            rec.approval_state = 'ppdd_validated'
            rec.message_post(body=_("Education assistance validated by PPDD."))

    def action_cpco_approve(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.approval_state != 'ppdd_validated':
                raise UserError(_('Only PPDD-validated requests can be approved by CPCO.'))
            if not rec.approved_amount:
                rec.approved_amount = rec.tuition_amount
            rec.approval_state = 'cpco_approved'
            rec.message_post(body=_("Staff education assistance approved for %s (Amount: %s).") % (rec.employee_id.name, rec.approved_amount))

    def action_disburse(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.approval_state != 'cpco_approved':
                raise ValidationError(_("Cannot disburse funds until CPCO approval is completed."))
            if rec.reimbursement_state != 'pending':
                raise UserError(_("Reimbursement is already disbursed."))
            rec.reimbursement_state = 'disbursed'
            rec.message_post(body=_("Tuition reimbursement disbursed."))
