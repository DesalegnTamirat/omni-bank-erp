# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import (
    clear_action_activities, notify_action, role_users,
)
from .eds_employee_projection import safe_employee_web_read

class EdsEducationAssistance(models.Model):
    _name = 'eds.education.assistance'
    _description = 'EDS Staff Education Assistance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

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
            if not self.env.su:
                employee = self.env['hr.employee'].browse(vals.get('employee_id'))
                staff = self.env.user.has_group(
                    'employee_development_system.group_eds_officer')
                if not staff and employee.sudo().user_id != self.env.user:
                    raise AccessError(_('You may request education assistance only for yourself.'))
                if (vals.get('approval_state', 'draft') != 'draft'
                        or vals.get('reimbursement_state', 'pending') != 'pending'
                        or vals.get('approved_amount')):
                    raise AccessError(_('Approval and reimbursement fields are set by workflow actions.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.education.assistance') or _('New')
        return super(EdsEducationAssistance, self).create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if {'approval_state', 'reimbursement_state', 'employee_id'} & vals.keys():
                raise AccessError(_('Use the education assistance workflow actions for decisions.'))
            details = {'program', 'institution', 'degree_level', 'tuition_amount', 'currency_id'}
            if details & vals.keys() and any(rec.approval_state != 'draft' for rec in self):
                raise UserError(_('Request details cannot change after submission.'))
            if 'approved_amount' in vals:
                self._require_group('group_eds_officer')
                if any(rec.approval_state not in ('dept_approved', 'ppdd_validated') for rec in self):
                    raise UserError(_('Set the proposed reimbursement during PPDD review.'))
            if {'proof_document', 'academic_progress'} & vals.keys() and any(
                    rec.reimbursement_state == 'disbursed' for rec in self):
                raise UserError(_('A disbursed education request is closed to edits.'))
        return super().write(vals)

    @api.constrains('tuition_amount', 'approved_amount')
    def _check_amounts(self):
        for rec in self:
            if (rec.tuition_amount < 0 or rec.approved_amount < 0
                    or rec.approved_amount > rec.tuition_amount):
                raise ValidationError(_(
                    'Requested and approved amounts must be nonnegative; the approved '
                    'amount cannot exceed the requested tuition.'))

    def _workflow_write(self, vals):
        return super(EdsEducationAssistance, self).write(vals)

    def action_submit(self):
        for rec in self:
            if rec.approval_state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            if (not self.env.su and rec.employee_id.sudo().user_id != self.env.user
                    and not self.env.user.has_group(
                        'employee_development_system.group_eds_officer')):
                raise AccessError(_('You may submit only your own education request.'))
            rec._workflow_write({'approval_state': 'submitted'})
            rec.message_post(body=_("Education assistance request submitted for Department Head review."))
            manager = rec.employee_id.sudo().parent_id.user_id
            if (not manager or not manager.active or not manager.has_group(
                    'employee_development_system.group_eds_line_manager')):
                manager = role_users(rec, 'group_eds_manager')
            notify_action(rec, manager, _('Review education assistance'),
                          _('Education assistance request %s needs department review.')
                          % rec.name)

    def action_dept_approve(self):
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.approval_state != 'submitted':
                raise UserError(_('Only submitted requests can be approved by Department Head.'))
            actual_managers = (rec.employee_id.sudo().parent_id.user_id
                               | rec.employee_id.sudo().department_id.manager_id.user_id)
            compat = self.env['eds.hr.compat']
            unit = compat.get_employee_operating_unit(rec.employee_id)
            managed_unit = bool(unit and unit.id in compat.get_managed_operating_units().ids)
            if (not self.env.su and self.env.user == rec.employee_id.sudo().user_id):
                raise AccessError(_('An employee cannot approve their own request.'))
            if (not self.env.su and self.env.user not in actual_managers
                    and not managed_unit
                    and not self.env.user.has_group(
                        'employee_development_system.group_eds_manager')):
                raise AccessError(_('Only the employee manager or Department Head may approve this request.'))
            rec._workflow_write({'approval_state': 'dept_approved'})
            clear_action_activities(rec)
            rec.message_post(body=_("Education assistance approved by Department Head."))
            notify_action(rec, role_users(rec, 'group_eds_officer'),
                          _('Validate education assistance'),
                          _('Education assistance request %s needs PPDD validation.')
                          % rec.name)

    def action_ppdd_validate(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.approval_state != 'dept_approved':
                raise UserError(_('Only department-approved requests can be validated by PPDD.'))
            rec._workflow_write({'approval_state': 'ppdd_validated'})
            clear_action_activities(rec)
            rec.message_post(body=_("Education assistance validated by PPDD."))
            notify_action(rec, role_users(rec, 'group_eds_cpco'),
                          _('Approve education assistance'),
                          _('Education assistance request %s needs CPCO approval.')
                          % rec.name)

    def action_cpco_approve(self):
        for rec in self:
            rec._require_group('group_eds_cpco')
            if rec.approval_state != 'ppdd_validated':
                raise UserError(_('Only PPDD-validated requests can be approved by CPCO.'))
            rec._workflow_write({
                'approved_amount': rec.approved_amount or rec.tuition_amount,
                'approval_state': 'cpco_approved',
            })
            clear_action_activities(rec)
            rec.message_post(body=_("Staff education assistance approved for %s (Amount: %s).") % (rec.employee_id.sudo().name, rec.approved_amount))
            notify_action(rec, rec.employee_id.sudo().user_id | rec.create_uid,
                          _('Education assistance approved'),
                          _('Education assistance request %s was approved.') % rec.name,
                          action_required=False)

    def action_disburse(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.approval_state != 'cpco_approved':
                raise ValidationError(_("Cannot disburse funds until CPCO approval is completed."))
            if rec.reimbursement_state != 'pending':
                raise UserError(_("Reimbursement is already disbursed."))
            if not rec.proof_document:
                raise ValidationError(_('Attach the academic transcript and proof of payment before disbursement.'))
            rec._workflow_write({'reimbursement_state': 'disbursed'})
            rec.message_post(body=_("Tuition reimbursement disbursed."))
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Education reimbursement paid'),
                          _('Education assistance request %s was reimbursed.') % rec.name,
                          action_required=False)
