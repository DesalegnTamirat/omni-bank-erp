# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class EdsInternshipApplication(models.Model):
    _name = 'eds.internship.application'
    _description = 'EDS Internship Facilitation & Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Application Ref', required=True, copy=False, default=lambda self: _('New'))
    applicant_name = fields.Char(string='Intern Applicant Name', required=True, tracking=True)
    email = fields.Char(string='Email Address')
    phone = fields.Char(string='Phone Number')
    institution = fields.Char(string='University / Institution', required=True)
    field_of_study = fields.Char(string='Field of Study / Specialization', required=True)
    scanned_application = fields.Binary(string='Scanned Letter / Application', attachment=True, required=True)
    scanned_filename = fields.Char(string='Document File Name')
    submitted_date = fields.Date(string='Received Date', default=fields.Date.context_today, required=True)
    start_date = fields.Date(string='Internship Start Date', tracking=True)
    end_date = fields.Date(string='Internship End Date', tracking=True)
    work_unit_id = fields.Many2one('operating.unit', string='Assigned Work Unit / Department', tracking=True)
    supervisor_id = fields.Many2one('hr.employee', string='Assigned Work Unit Supervisor', tracking=True)
    progress_notes = fields.Text(string='Placement & Progress Notes')
    outcome_report = fields.Text(string='Final Internship Performance & Outcome Summary')
    evaluation_ids = fields.One2many('eds.internship.evaluation', 'application_id', string='Periodic Evaluations')
    status = fields.Selection([
        ('received', 'Application Received'),
        ('notified', 'Work Units Notified'),
        ('accepted', 'Accepted by Work Unit'),
        ('placed', 'Placed / Onboarded'),
        ('ongoing', 'Internship Ongoing'),
        ('completed', 'Internship Completed'),
        ('rejected', 'Application Rejected'),
    ], string='Status', default='received', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.internship.application') or _('New')
        return super(EdsInternshipApplication, self).create(vals_list)

    def action_notify_units(self):
        for rec in self:
            rec.status = 'notified'
            rec.message_post(body=_("Application notified to potential host work units."))

    def action_accept(self):
        for rec in self:
            if not rec.work_unit_id:
                raise ValidationError(_("Please select an assigned work unit before accepting."))
            rec.status = 'accepted'
            rec.message_post(body=_("Internship application accepted by work unit %s.") % rec.work_unit_id.name)

    def action_place(self):
        for rec in self:
            if not rec.supervisor_id or not rec.start_date:
                raise ValidationError(_("Please assign a supervisor and start date before placement."))
            rec.status = 'placed'
            rec.message_post(body=_("Intern onboarded under supervisor %s.") % rec.supervisor_id.name)

    def action_start(self):
        for rec in self:
            rec.status = 'ongoing'

    def action_complete(self):
        for rec in self:
            if not rec.outcome_report:
                raise ValidationError(_("Please enter an outcome report summary before marking completed."))
            rec.status = 'completed'
            rec.message_post(body=_("Internship successfully completed."))

    def action_reject(self):
        for rec in self:
            rec.status = 'rejected'

class EdsInternshipEvaluation(models.Model):
    _name = 'eds.internship.evaluation'
    _description = 'EDS Internship Periodic Assessment'

    application_id = fields.Many2one('eds.internship.application', string='Internship Application', ondelete='cascade', required=True)
    period = fields.Selection([
        ('midterm', 'Mid-Term Progress Review'),
        ('final', 'Final Internship Evaluation'),
    ], string='Review Period', default='midterm', required=True)
    date = fields.Date(string='Evaluation Date', default=fields.Date.context_today)
    rating = fields.Selection([
        ('1', '1 - Unsatisfactory'),
        ('2', '2 - Needs Improvement'),
        ('3', '3 - Satisfactory / Meets Expectations'),
        ('4', '4 - Very Good'),
        ('5', '5 - Outstanding'),
    ], string='Performance Rating', default='3', required=True)
    comments = fields.Text(string='Supervisor Remarks & Feedback', required=True)
    evaluated_by = fields.Many2one('res.users', string='Evaluator', default=lambda self: self.env.user)
