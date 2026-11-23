# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError, UserError

from .eds_action_notification import notify_action
from .eds_employee_projection import safe_employee_web_read


class EdsWorkplaceAssignment(models.Model):
    """Workplace learning assignment.

    Supports straightforward assignment of a Buddy, Mentor, Coach, or OJT guide
    to an employee without heavy task micromanagement.
    """
    _name = 'eds.workplace.assignment'
    _description = 'Workplace Learning Assignment (Buddy / Mentoring / Coaching)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read,
            ('employee_id', 'mentor_id'))

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    program_type = fields.Selection([
        ('buddy', 'Buddy Support'),
        ('ojt', 'On-the-Job Training (OJT)'),
        ('coaching', 'Coaching Program'),
        ('mentoring', 'Mentoring Program'),
        ('induction', 'Induction Guide'),
    ], string='Program Type', default='buddy', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Participant / Protégé', required=True, tracking=True)
    mentor_id = fields.Many2one(
        'hr.employee', string='Assigned Buddy / Mentor / Coach', required=True, tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', related='employee_id.department_id',
        store=True, readonly=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position', related='employee_id.job_id',
        store=True, readonly=True)
    start_date = fields.Date(
        string='Start Date', default=fields.Date.context_today, required=True, tracking=True)
    end_date = fields.Date(string='Target End Date', tracking=True)
    focus_areas = fields.Char(string='Competencies / Focus Areas')
    notes = fields.Text(string='Assignment Objectives & Guidance Notes')
    decision_remark = fields.Text(string='Decision / Cancellation Justification', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('employee_id', 'mentor_id')
    def _check_mentor_not_self(self):
        for rec in self:
            if rec.employee_id and rec.mentor_id and rec.employee_id.id == rec.mentor_id.id:
                raise ValidationError(_("An employee cannot be assigned as their own buddy/mentor!"))

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_('The assignment end date cannot precede its start date.'))

    def _require_assignment_actor(self):
        self.ensure_one()
        self._require_group('group_eds_line_manager')
        if (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer')):
            return
        compat = self.env['eds.hr.compat']
        unit = compat.get_employee_operating_unit(self.employee_id)
        managed_unit = bool(unit and unit.id in compat.get_managed_operating_units().ids)
        if (self.employee_id.sudo().parent_id.user_id != self.env.user
                and not managed_unit):
            raise AccessError(_('Only the employee manager or L&D may manage this assignment.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su:
                if vals.get('state', 'draft') != 'draft':
                    raise AccessError(_('Workplace assignments must start as drafts.'))
                employee = self.env['hr.employee'].sudo().browse(vals.get('employee_id'))
                compat = self.env['eds.hr.compat']
                unit = compat.get_employee_operating_unit(employee)
                if (not self.env.user.has_group(
                        'employee_development_system.group_eds_officer')
                        and employee.sudo().parent_id.user_id != self.env.user
                        and not (unit and unit.id in compat.get_managed_operating_units().ids)):
                    raise AccessError(_('Only the employee manager or L&D may create this assignment.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.workplace.assignment') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if 'state' in vals:
                raise AccessError(_('Use workplace assignment workflow actions to change status.'))
            fixed = {'employee_id', 'mentor_id', 'program_type', 'company_id', 'start_date'}
            if fixed & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(_('Assignees and program details cannot change after activation.'))
            if any(rec.state in ('completed', 'cancelled') for rec in self) and (
                    fixed | {'end_date', 'focus_areas', 'notes'}) & vals.keys():
                raise UserError(_('A closed workplace assignment cannot be edited.'))
        return super().write(vals)

    def _workflow_write(self, vals):
        return super(EdsWorkplaceAssignment, self).write(vals)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_activate(self):
        for rec in self:
            rec._require_assignment_actor()
            if rec.state != 'draft':
                raise UserError(_("Only draft assignments can be activated."))
            rec._workflow_write({'state': 'active'})
            rec.message_post(body=_("Workplace learning assignment '%s' is now active.") % rec.name)
            notify_action(rec, rec.employee_id.sudo().user_id | rec.mentor_id.sudo().user_id,
                          _('Workplace learning assigned'),
                          _('Workplace learning assignment %s is active.') % rec.name,
                          action_required=False)

    def action_complete(self):
        for rec in self:
            rec._require_assignment_actor()
            if rec.state != 'active':
                raise UserError(_("Only active assignments can be marked as completed."))
            rec._workflow_write({'state': 'completed'})
            rec.message_post(body=_("Workplace learning assignment '%s' completed successfully.") % rec.name)
            notify_action(rec, rec.employee_id.sudo().user_id | rec.mentor_id.sudo().user_id,
                          _('Workplace learning completed'),
                          _('Workplace learning assignment %s is complete.') % rec.name,
                          action_required=False)

    def action_cancel(self):
        for rec in self:
            rec._require_assignment_actor()
            if rec.state not in ('draft', 'active'):
                raise UserError(_("Only draft or active assignments can be cancelled."))
            if not (rec.decision_remark or '').strip():
                raise ValidationError(_('Explain why this workplace assignment is cancelled.'))
            rec._workflow_write({'state': 'cancelled'})
            rec.message_post(body=_("Workplace learning assignment '%s' cancelled.") % rec.name)
            notify_action(rec, rec.employee_id.sudo().user_id | rec.mentor_id.sudo().user_id,
                          _('Workplace learning cancelled'),
                          _('Workplace learning assignment %s was cancelled: %s')
                          % (rec.name, rec.decision_remark), action_required=False)
