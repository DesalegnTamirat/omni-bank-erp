# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import clear_action_activities, notify_action, role_users
from .eds_employee_projection import safe_employee_web_read


class EdsIdp(models.Model):
    """Individual Development Plan."""
    _name = 'eds.idp'
    _description = 'Individual Development Plan (IDP)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, id desc'
    _rec_name = 'name'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read,
            ('employee_id', 'manager_id'))

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, default=lambda self: self._default_employee_id(),
        tracking=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', related='employee_id.department_id',
        store=True, readonly=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position', related='employee_id.job_id',
        store=True, readonly=True)
    manager_id = fields.Many2one(
        'hr.employee', string='Supervisor / Manager', related='employee_id.parent_id',
        store=True, readonly=True)
    year = fields.Char(string='Plan Year', default=lambda self: str(fields.Date.today().year),
                       required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Review'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    line_ids = fields.One2many('eds.idp.line', 'idp_id', string='Development Goals & Activities')
    notes = fields.Text(string='Development Summary & Career Aspirations')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def _default_employee_id(self):
        return self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su:
                employee = self.env['hr.employee'].sudo().browse(
                    vals.get('employee_id') or self._default_employee_id().id)
                staff = self.env.user.has_group(
                    'employee_development_system.group_eds_officer')
                compat = self.env['eds.hr.compat']
                unit = compat.get_employee_operating_unit(employee)
                manager = (self.env.user.has_group(
                    'employee_development_system.group_eds_line_manager')
                    and (employee.sudo().parent_id.user_id == self.env.user
                         or bool(unit and unit.id in compat.get_managed_operating_units().ids)))
                if not (staff or manager or employee.sudo().user_id == self.env.user):
                    raise AccessError(_('You may create a development plan only for yourself or a direct report.'))
                if vals.get('state', 'draft') != 'draft':
                    raise AccessError(_('Development plans must start as drafts.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.idp') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if {'state', 'employee_id'} & vals.keys():
                raise AccessError(_('Use development plan workflow actions to change its status.'))
            if {'year', 'notes'} & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(_('Plan details cannot change after submission.'))
        return super().write(vals)

    def _workflow_write(self, vals):
        return super(EdsIdp, self).write(vals)

    def _is_employee_or_staff(self):
        self.ensure_one()
        return (self.env.su or self.employee_id.sudo().user_id == self.env.user
                or self.env.user.has_group('employee_development_system.group_eds_officer'))

    def _require_actual_manager(self):
        self._require_group('group_eds_line_manager')
        compat = self.env['eds.hr.compat']
        unit = compat.get_employee_operating_unit(self.employee_id)
        managed_unit = bool(unit and unit.id in compat.get_managed_operating_units().ids)
        if (not self.env.su and self.manager_id.sudo().user_id != self.env.user
                and not managed_unit
                and not self.env.user.has_group(
                    'employee_development_system.group_eds_manager')):
            raise AccessError(_('Only this employee manager may approve or complete the plan.'))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft IDPs can be submitted."))
            if not rec._is_employee_or_staff():
                raise AccessError(_('You may submit only your own development plan.'))
            if not rec.line_ids:
                raise ValidationError(_('Add at least one development goal before submission.'))
            rec._workflow_write({'state': 'submitted'})
            rec.message_post(body=_("IDP %s submitted for manager review.") % rec.name)
            reviewer = rec.manager_id.sudo().user_id
            if (not reviewer or not reviewer.active or not reviewer.has_group(
                    'employee_development_system.group_eds_line_manager')):
                reviewer = role_users(rec, 'group_eds_manager')
            notify_action(rec, reviewer, _('Review development plan'),
                          _('Development plan %s for %s needs manager review.')
                          % (rec.name, rec.employee_id.sudo().name))

    def action_approve(self):
        for rec in self:
            rec._require_actual_manager()
            if rec.state != 'submitted':
                raise UserError(_("Only submitted IDPs can be approved."))
            rec._workflow_write({'state': 'approved'})
            rec.message_post(body=_("IDP %s approved by manager.") % rec.name)
            clear_action_activities(rec)
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Development plan approved'),
                          _('Your development plan %s was approved. You can begin its activities.')
                          % rec.name, action_required=False)

    def action_start(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved IDPs can be moved to in progress."))
            compat = self.env['eds.hr.compat']
            unit = compat.get_employee_operating_unit(rec.employee_id)
            managed_unit = bool(unit and unit.id in compat.get_managed_operating_units().ids)
            if (not rec._is_employee_or_staff()
                    and rec.manager_id.sudo().user_id != self.env.user
                    and not managed_unit):
                raise AccessError(_('Only the employee or their manager may start this plan.'))
            rec._workflow_write({'state': 'in_progress'})

    def action_complete(self):
        for rec in self:
            if rec.state not in ('approved', 'in_progress'):
                raise UserError(_("Only approved or in-progress IDPs can be completed."))
            rec._require_actual_manager()
            if rec.line_ids.filtered(lambda line: line.status != 'achieved'):
                raise ValidationError(_('Complete all development goals before closing the plan.'))
            rec._workflow_write({'state': 'completed'})
            rec.message_post(body=_("IDP %s marked as completed.") % rec.name)
            notify_action(rec, rec.employee_id.sudo().user_id,
                          _('Development plan completed'),
                          _('Your development plan %s is marked complete.') % rec.name,
                          action_required=False)


class EdsIdpLine(models.Model):
    """Specific goal / competency focus in an IDP."""
    _name = 'eds.idp.line'
    _description = 'IDP Learning Goal Line'
    _order = 'create_date desc, id desc'

    idp_id = fields.Many2one('eds.idp', string='IDP', ondelete='cascade', required=True)
    competency_id = fields.Many2one('competency.competency', string='Target Competency')
    target_skill = fields.Char(string='Target Skill / Knowledge Area', required=True)
    learning_action = fields.Selection([
        ('course', 'Classroom / E-Learning Course'),
        ('ojt', 'On-the-Job Practice / Project'),
        ('mentoring', 'Mentoring / Coaching'),
        ('self_study', 'Self-Directed Study & Research'),
    ], string='Learning Action Type', default='course', required=True)
    proposed_course_id = fields.Many2one('eds.course', string='Mapped Course')
    target_date = fields.Date(string='Target Completion Date')
    status = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('achieved', 'Achieved'),
        ('deferred', 'Deferred'),
    ], string='Status', default='planned', required=True)
    progress_notes = fields.Text(string='Progress & Evidence')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                plan = self.env['eds.idp'].browse(vals.get('idp_id'))
                if plan.state != 'draft':
                    raise UserError(_('Add development goals while the plan is a draft.'))
                if not plan._is_employee_or_staff() and plan.manager_id.sudo().user_id != self.env.user:
                    raise AccessError(_('You may add goals only to your own or your team plan.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if 'idp_id' in vals:
                raise AccessError(_('Move a goal by creating it on the intended plan.'))
            for line in self:
                if line.idp_id.state not in ('draft', 'in_progress'):
                    raise UserError(_('Goals on a closed or pending plan cannot be edited.'))
                if line.idp_id.state == 'in_progress' and set(vals) - {'status', 'progress_notes'}:
                    raise UserError(_('Only goal progress can change after plan approval.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(line.idp_id.state != 'draft' for line in self):
            raise UserError(_('Only draft development goals can be removed.'))
        return super().unlink()


class EdsSelfDevelopment(models.Model):
    """Self-directed learning activity logged by employee."""
    _name = 'eds.self.development'
    _description = 'Employee Self-Development Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'activity_date desc, id desc'
    _rec_name = 'title'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    title = fields.Char(string='Activity Title', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env['hr.employee'].sudo().search([('user_id', '=', self.env.user.id)], limit=1),
        tracking=True)
    activity_type = fields.Selection([
        ('reading', 'Book / Research Publication'),
        ('webinar', 'Webinar / Conference'),
        ('mooc', 'Online Self-Paced Course'),
        ('project', 'Independent Practice Project'),
        ('other', 'Other Self-Study'),
    ], string='Activity Type', default='webinar', required=True, tracking=True)
    activity_date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    hours_spent = fields.Float(string='Hours Spent', default=1.0)
    key_takeaways = fields.Text(string='Key Learnings & Impact')
    certificate_attachment = fields.Binary(string='Certificate / Proof of Completion', attachment=True)
    certificate_name = fields.Char(string='Filename')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Recorded'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                employee = self.env['hr.employee'].sudo().browse(
                    vals.get('employee_id') or self.env['hr.employee'].sudo().search([
                        ('user_id', '=', self.env.user.id)], limit=1).id)
                if employee.sudo().user_id != self.env.user and not self.env.user.has_group(
                        'employee_development_system.group_eds_officer'):
                    raise AccessError(_('You may record self-development only for yourself.'))
                if vals.get('state', 'draft') != 'draft':
                    raise AccessError(_('Self-development must start as a draft.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if {'state', 'employee_id'} & vals.keys():
                raise AccessError(_('Use the self-development submit action.'))
            content_fields = {
                'title', 'activity_type', 'activity_date', 'hours_spent',
                'key_takeaways', 'certificate_attachment', 'certificate_name',
            }
            if content_fields & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(_('A recorded self-development activity cannot be edited.'))
        return super().write(vals)

    @api.constrains('hours_spent')
    def _check_hours_spent(self):
        for rec in self:
            if rec.hours_spent <= 0:
                raise ValidationError(_('Hours spent must be greater than zero.'))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft self-development activities can be recorded.'))
            if (not self.env.su and rec.employee_id.sudo().user_id != self.env.user
                    and not self.env.user.has_group(
                        'employee_development_system.group_eds_officer')):
                raise AccessError(_('You may record only your own self-development activity.'))
            super(EdsSelfDevelopment, rec).write({'state': 'submitted'})
            rec.message_post(body=_("Self-development activity recorded."))
