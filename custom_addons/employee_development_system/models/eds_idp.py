# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsIdp(models.Model):
    """Individual Development Plan (FREDS052)."""
    _name = 'eds.idp'
    _description = 'Individual Development Plan (IDP)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, id desc'
    _rec_name = 'name'

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
        return self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.idp') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft IDPs can be submitted."))
            rec.state = 'submitted'
            rec.message_post(body=_("IDP %s submitted for manager review.") % rec.name)

    def action_approve(self):
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.state != 'submitted':
                raise UserError(_("Only submitted IDPs can be approved."))
            rec.state = 'approved'
            rec.message_post(body=_("IDP %s approved by manager.") % rec.name)

    def action_start(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only approved IDPs can be moved to in progress."))
            rec.state = 'in_progress'

    def action_complete(self):
        for rec in self:
            if rec.state not in ('approved', 'in_progress'):
                raise UserError(_("Only approved or in-progress IDPs can be completed."))
            rec.state = 'completed'
            rec.message_post(body=_("IDP %s marked as completed.") % rec.name)


class EdsIdpLine(models.Model):
    """Specific goal / competency focus in an IDP."""
    _name = 'eds.idp.line'
    _description = 'IDP Learning Goal Line'

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


class EdsSelfDevelopment(models.Model):
    """Self-directed learning activity logged by employee (FREDS053)."""
    _name = 'eds.self.development'
    _description = 'Employee Self-Development Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'activity_date desc, id desc'
    _rec_name = 'title'

    title = fields.Char(string='Activity Title', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1),
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
    certificate_attachment = fields.Binary(string='Certificate / Proof of Completion')
    certificate_name = fields.Char(string='Filename')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Recorded & Verified'),
    ], string='Status', default='draft', required=True, tracking=True)

    def action_submit(self):
        for rec in self:
            rec.state = 'submitted'
            rec.message_post(body=_("Self-development activity recorded."))
