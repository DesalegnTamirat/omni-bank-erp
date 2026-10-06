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
    work_unit_id = fields.Many2one('operating.unit', string='Assigned Work Unit / Branch', tracking=True)
    department_id = fields.Many2one('hr.department', string='Assigned Department', tracking=True)
    supervisor_id = fields.Many2one('hr.employee', string='Assigned Work Unit Supervisor', tracking=True)

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Top of hierarchy: Department -> Operating Unit.
        - If department selected:
          work_unit_id domain restricted to operating units belonging to this department.
          If selected work_unit_id doesn't belong to the department, clear it.
          supervisor_id restricted to the department.
        - If no department selected:
          All operating units and supervisors are available.
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_id)
        if self.department_id:
            if self.work_unit_id and not self.env['eds.hr.compat'].is_operating_unit_in_departments(self.work_unit_id, self.department_id):
                self.work_unit_id = False
            if self.supervisor_id and self.supervisor_id.department_id != self.department_id:
                self.supervisor_id = False
        sup_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id)
        return {'domain': {'work_unit_id': ou_domain, 'supervisor_id': sup_domain}}

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        """Middle of hierarchy: Operating Unit.
        Filter supervisor based on selected work unit and department.
        """
        if self.work_unit_id and not self.department_id:
            if hasattr(self.work_unit_id, 'department') and self.work_unit_id.department:
                self.department_id = self.work_unit_id.department
            elif 'operating_unit_id' in self.env['hr.department']._fields:
                linked_dept = self.env['hr.department'].search([('operating_unit_id', '=', self.work_unit_id.id)], limit=1)
                if linked_dept:
                    self.department_id = linked_dept

        if self.work_unit_id and self.supervisor_id:
            sup_ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.supervisor_id)
            if sup_ou and sup_ou != self.work_unit_id:
                self.supervisor_id = False
        sup_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id)
        return {'domain': {'supervisor_id': sup_domain}}

    @api.onchange('supervisor_id')
    def _onchange_supervisor_id(self):
        if self.supervisor_id:
            if self.supervisor_id.department_id and not self.department_id:
                self.department_id = self.supervisor_id.department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.supervisor_id)
            if ou and not self.work_unit_id:
                self.work_unit_id = ou
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

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.internship.application') or _('New')
        return super(EdsInternshipApplication, self).create(vals_list)

    def action_notify_units(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.status != 'received':
                raise UserError(_('Only received applications can be notified to work units.'))
            rec.status = 'notified'
            rec.message_post(body=_("Application notified to potential host work units."))

    def action_accept(self):
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.status != 'notified':
                raise UserError(_('Only notified applications can be accepted by a work unit.'))
            if not rec.work_unit_id:
                raise ValidationError(_("Please select an assigned work unit before accepting."))
            rec.status = 'accepted'
            rec.message_post(body=_("Internship application accepted by work unit %s.") % rec.work_unit_id.name)

    def action_place(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.status != 'accepted':
                raise UserError(_('Only accepted applications can be placed.'))
            if not rec.supervisor_id or not rec.start_date:
                raise ValidationError(_("Please assign a supervisor and start date before placement."))
            rec.status = 'placed'
            rec.message_post(body=_("Intern onboarded under supervisor %s.") % rec.supervisor_id.name)

    def action_start(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.status != 'placed':
                raise UserError(_('Only placed applications can be marked ongoing.'))
            rec.status = 'ongoing'

    def action_complete(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.status != 'ongoing':
                raise UserError(_('Only ongoing internships can be completed.'))
            if not rec.outcome_report:
                raise ValidationError(_("Please enter an outcome report summary before marking completed."))
            rec.status = 'completed'
            rec.message_post(body=_("Internship successfully completed."))

    def action_reject(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.status in ('completed', 'rejected'):
                raise UserError(_('Cannot reject an internship that is already completed or rejected.'))
            rec.status = 'rejected'
            rec.message_post(body=_("Internship application rejected."))

    # EDS-F-14 Clearance & Final Appraisal Fields
    clearance_library = fields.Boolean(string='Bank Library / Resource Clearance', default=True)
    clearance_id_badge = fields.Boolean(string='Temporary ID Badge Surrendered', default=True)
    clearance_it_assets = fields.Boolean(string='IT / Workstation Access Cleared', default=True)
    clearance_notes = fields.Char(string='Clearance Remarks')
    clearance_officer_name = fields.Char(string='Clearance Officer Name')
    clearance_date = fields.Date(string='Clearance Date')
    final_intern_rating = fields.Selection([
        ('1', '1 - Unsatisfactory'),
        ('2', '2 - Needs Improvement'),
        ('3', '3 - Satisfactory / Meets Expectations'),
        ('4', '4 - Very Good'),
        ('5', '5 - Outstanding'),
    ], string='Final Overall Performance Rating', default='4')
    mentor_overall_recommendation = fields.Selection([
        ('highly_recommended', 'Highly Recommended for Future Employment'),
        ('suitable', 'Suitable Graduate Trainee Candidate'),
        ('not_recommended', 'Not Recommended for Hiring'),
    ], string='Employment Recommendation', default='suitable')
    mentor_sign_name = fields.Char(string='Supervisor / Mentor Signature')
    intern_sign_name = fields.Char(string='Intern Acknowledgment Signature')

    def action_print_clearance_form(self):
        """Prints official Form EDS-F-14 Internship Appraisal & Clearance PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_internship_appraisal').report_action(self)

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
