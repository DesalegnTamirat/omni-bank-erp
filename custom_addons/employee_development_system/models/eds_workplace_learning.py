# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EdsWorkplaceAssignment(models.Model):
    """Workplace learning assignment (FREDS046 - FREDS051).

    Supports straightforward assignment of a Buddy, Mentor, Coach, or OJT guide
    to an employee without heavy task micromanagement.
    """
    _name = 'eds.workplace.assignment'
    _description = 'Workplace Learning Assignment (Buddy / Mentoring / Coaching)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.workplace.assignment') or _('New')
        return super().create(vals_list)

    def action_activate(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft assignments can be activated."))
            rec.state = 'active'
            rec.message_post(body=_("Workplace learning assignment '%s' is now active.") % rec.name)

    def action_complete(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_("Only active assignments can be marked as completed."))
            rec.state = 'completed'
            rec.message_post(body=_("Workplace learning assignment '%s' completed successfully.") % rec.name)

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'
            rec.message_post(body=_("Workplace learning assignment '%s' cancelled.") % rec.name)
