# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from .eds_action_notification import clear_action_activities, notify_action, role_users
from .eds_employee_projection import safe_employee_web_read

class EdsInternshipApplication(models.Model):
    _name = 'eds.internship.application'
    _description = 'EDS Internship Facilitation & Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('supervisor_id',))

    is_internal = fields.Boolean(string='Internal Employee', default=False, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Internal Employee', tracking=True)
    name = fields.Char(string='Application Ref', required=True, copy=False, default=lambda self: _('New'))
    applicant_name = fields.Char(string='Intern Applicant Name', required=True, tracking=True)
    email = fields.Char(string='Email Address')
    phone = fields.Char(string='Phone Number')
    institution = fields.Char(string='University / Institution')
    field_of_study = fields.Char(string='Field of Study / Specialization')
    scanned_application = fields.Binary(string='Scanned Letter / Application', attachment=True)
    scanned_filename = fields.Char(string='Document File Name')
    submitted_date = fields.Date(string='Received Date', default=fields.Date.context_today, required=True)
    start_date = fields.Date(string='Internship Start Date', tracking=True)
    end_date = fields.Date(string='Internship End Date', tracking=True)
    completion_due = fields.Boolean(compute='_compute_completion_due')
    can_manage_host = fields.Boolean(compute='_compute_can_manage_host')
    can_edit_work_unit = fields.Boolean(compute='_compute_can_manage_host')
    can_manage_evaluation = fields.Boolean(compute='_compute_can_manage_host')
    can_reject = fields.Boolean(compute='_compute_can_manage_host')
    start_confirmed_on = fields.Date(string='Start Confirmed On', readonly=True, copy=False)
    start_confirmed_by_id = fields.Many2one('res.users', string='Start Confirmed By', readonly=True, copy=False)
    completion_confirmed_on = fields.Date(string='Completion Confirmed On', readonly=True, copy=False)
    completion_confirmed_by_id = fields.Many2one('res.users', string='Completion Confirmed By', readonly=True, copy=False)
    work_unit_id = fields.Many2one('operating.unit', string='Assigned Work Unit / Branch', tracking=True)
    department_id = fields.Many2one('hr.department', string='Assigned Department', tracking=True)
    supervisor_id = fields.Many2one('hr.employee', string='Assigned Work Unit Supervisor', tracking=True)

    @api.depends('end_date')
    def _compute_completion_due(self):
        for rec in self:
            rec.completion_due = bool(
                rec.end_date and fields.Date.context_today(rec) >= rec.end_date)

    @api.depends('work_unit_id', 'supervisor_id', 'status')
    @api.depends_context('uid')
    def _compute_can_manage_host(self):
        for rec in self:
            staff = rec._is_eds_staff()
            host = rec._is_host_manager()
            supervisor = rec._is_assigned_supervisor()
            rec.can_manage_host = bool(
                (staff and rec.status not in ('completed', 'rejected'))
                or (host and rec.status in ('accepted', 'placed', 'ongoing')))
            rec.can_edit_work_unit = bool(staff and rec.status == 'received')
            rec.can_manage_evaluation = bool(
                rec.status == 'ongoing' and (staff or host or supervisor))
            rec.can_reject = bool(
                (staff and rec.status in ('received', 'notified', 'accepted', 'placed'))
                or (host and rec.status == 'notified'))

    def _is_eds_staff(self):
        return self.env.su or self.env.user.has_group(
            'employee_development_system.group_eds_officer')

    def _is_host_manager(self):
        self.ensure_one()
        return bool(
            self.env.user.has_group('employee_development_system.group_eds_line_manager')
            and self.work_unit_id
            and self.work_unit_id in self.env['eds.hr.compat'].get_managed_operating_units())

    def _is_assigned_supervisor(self):
        self.ensure_one()
        return bool(self.supervisor_id and self.supervisor_id.sudo().user_id == self.env.user)

    def _require_host_or_staff(self):
        for rec in self:
            if not self.env.su:
                rec.check_access('write')
            if not (rec._is_eds_staff() or rec._is_host_manager()):
                raise AccessError(_(
                    'Only the selected host work unit manager or L&D staff may act on this internship.'))

    def _check_supervisor_lookup_access(self):
        """Allow HR-backed placement suggestions only from an EDS form actor."""
        if self.env.su:
            return
        if self._origin and self._origin.id:
            self._origin.check_access('read')
        else:
            self.env['ir.model.access'].check(self._name, 'create')

    @api.constrains('is_internal', 'employee_id', 'applicant_name')
    def _check_applicant_requirements(self):
        for rec in self:
            if rec.is_internal and not rec.employee_id:
                raise ValidationError(_('Please select an internal employee.'))
            if not rec.applicant_name:
                raise ValidationError(_('Applicant name is required.'))

    @api.onchange('is_internal')
    def _onchange_is_internal(self):
        if not self.is_internal:
            self.employee_id = False
        else:
            if not self.institution:
                self.institution = self.env.company.name or 'Bunna Bank S.C.'

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.is_internal and self.employee_id:
            emp = self.employee_id
            self.applicant_name = emp.name
            self.email = emp.work_email or (emp.user_id and emp.user_id.email) or ''
            self.phone = emp.mobile_phone or emp.work_phone or ''
            if emp.department_id:
                self.department_id = emp.department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(emp)
            if ou:
                self.work_unit_id = ou
            if not self.institution:
                self.institution = self.env.company.name or 'Bunna Bank S.C.'
            if not self.field_of_study and emp.job_id:
                self.field_of_study = emp.job_id.name

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
            if self.supervisor_id:
                self._check_supervisor_lookup_access()
            if self.supervisor_id and self.supervisor_id.sudo().department_id != self.department_id:
                self.supervisor_id = False
            if self.is_internal and self.employee_id and self.employee_id.department_id != self.department_id:
                self.employee_id = False
                self.applicant_name = False
                self.email = False
                self.phone = False
        sup_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id)
        emp_domain = [('department_id', '=', self.department_id.id)] if self.department_id else []
        return {'domain': {'work_unit_id': ou_domain, 'supervisor_id': sup_domain, 'employee_id': emp_domain}}

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
            self._check_supervisor_lookup_access()
            sup_ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.supervisor_id)
            if sup_ou and sup_ou != self.work_unit_id:
                self.supervisor_id = False
        sup_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id)
        return {'domain': {'supervisor_id': sup_domain}}

    @api.onchange('supervisor_id')
    def _onchange_supervisor_id(self):
        if self.supervisor_id:
            self._check_supervisor_lookup_access()
            if (self.status == 'received' and self.supervisor_id.sudo().department_id
                    and not self.department_id):
                self.department_id = self.supervisor_id.sudo().department_id
            ou = self.env['eds.hr.compat'].get_employee_operating_unit(self.supervisor_id)
            if ou and not self.work_unit_id:
                self.work_unit_id = ou
    progress_notes = fields.Text(string='Placement & Progress Notes')
    outcome_report = fields.Text(string='Final Internship Performance & Outcome Summary')
    rejection_reason = fields.Text(string='Rejection Justification', tracking=True)
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

    @api.constrains('start_date', 'end_date', 'start_confirmed_on',
                    'department_id', 'work_unit_id', 'supervisor_id')
    def _check_placement(self):
        compat = self.env['eds.hr.compat']
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_('The internship end date cannot precede its start date.'))
            if rec.start_confirmed_on and rec.start_date and rec.start_date > rec.start_confirmed_on:
                raise ValidationError(_('The internship start date cannot be after the confirmed start.'))
            if rec.start_confirmed_on and rec.end_date and rec.end_date < rec.start_confirmed_on:
                raise ValidationError(_('The internship end date cannot precede the confirmed start.'))
            if (rec.department_id and rec.work_unit_id
                    and not compat.is_operating_unit_in_departments(
                        rec.work_unit_id, rec.department_id)):
                raise ValidationError(_('The assigned work unit is outside the selected department.'))
            if rec.supervisor_id and rec.department_id and rec.supervisor_id.sudo().department_id != rec.department_id:
                raise ValidationError(_('The supervisor must belong to the selected department.'))
            if rec.supervisor_id and rec.work_unit_id:
                supervisor_unit = compat.get_employee_operating_unit(rec.supervisor_id)
                if supervisor_unit and supervisor_unit != rec.work_unit_id:
                    raise ValidationError(_('The supervisor must belong to the assigned work unit.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('status', 'received') != 'received':
                raise AccessError(_('An internship must begin in Application Received.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.internship.application') or _('New')
        return super(EdsInternshipApplication, self).create(vals_list)

    def write(self, vals):
        previous_supervisors = ({rec.id: rec.supervisor_id.id for rec in self}
                                if 'supervisor_id' in vals else {})
        if not self.env.su:
            protected = {
                'status', 'start_confirmed_on', 'start_confirmed_by_id',
                'completion_confirmed_on', 'completion_confirmed_by_id',
            }
            if protected.intersection(vals):
                raise AccessError(_('Use the internship workflow buttons to change its status.'))
            host_fields = {
                'supervisor_id', 'start_date', 'end_date',
                'progress_notes', 'outcome_report', 'clearance_library',
                'clearance_id_badge', 'clearance_it_assets', 'clearance_notes',
                'clearance_officer_name', 'clearance_date', 'final_intern_rating',
                'mentor_overall_recommendation', 'mentor_sign_name',
                'intern_sign_name', 'evaluation_ids',
            }
            supervisor_fields = {
                'progress_notes', 'outcome_report', 'final_intern_rating',
                'mentor_overall_recommendation', 'mentor_sign_name',
                'evaluation_ids',
            }
            for rec in self:
                rec.check_access('write')
                if rec._is_eds_staff():
                    if (rec.status != 'received'
                            and {'work_unit_id', 'department_id'}.intersection(vals)):
                        raise AccessError(_(
                            'The host work unit and department are fixed after notification.'))
                    continue
                if rec._is_host_manager():
                    allowed = ({'rejection_reason'} if rec.status == 'notified'
                               else host_fields if rec.status in ('accepted', 'placed', 'ongoing')
                               else set())
                elif rec._is_assigned_supervisor():
                    allowed = supervisor_fields if rec.status == 'ongoing' else set()
                else:
                    raise AccessError(_('You cannot edit this internship application.'))
                if set(vals) - allowed:
                    raise AccessError(_('You cannot edit these internship fields at this stage.'))

        result = super().write(vals)
        if 'supervisor_id' in vals and vals['supervisor_id']:
            for rec in self:
                if (rec.supervisor_id.id != previous_supervisors.get(rec.id)
                        and rec.status in ('accepted', 'placed', 'ongoing')):
                    supervisor_user = rec.supervisor_id.sudo().user_id
                    if supervisor_user and supervisor_user.active:
                        notify_action(
                            rec, supervisor_user, _('Internship supervisor assigned'),
                            _('You have been assigned to supervise %s in %s. '
                              'The internship runs from %s to %s.') % (
                                  rec.applicant_name, rec.work_unit_id.name,
                                  rec.start_date or _('a date to be set'),
                                  rec.end_date or _('a date to be set')),
                            action_required=False)
        return result

    def action_notify_units(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            rec.check_access('write')
            if rec.status != 'received':
                raise UserError(_('Only received applications can be notified to work units.'))
            if not rec.work_unit_id:
                raise ValidationError(_('Select the proposed host work unit before notifying it.'))
            manager_user = rec.work_unit_id.manager_id.sudo().user_id
            if not manager_user or not manager_user.active:
                raise ValidationError(_('The host work unit needs an active manager user to review this application.'))
            if not manager_user.has_group('employee_development_system.group_eds_line_manager'):
                raise ValidationError(_('The host work unit manager needs the EDS Line Manager role.'))
            rec.sudo().write({'status': 'notified'})
            notify_action(rec, manager_user, _('Review internship application'),
                          _('Internship application %s needs a host work unit decision.') % rec.name)

    def action_accept(self):
        for rec in self:
            rec._require_host_or_staff()
            if rec.status != 'notified':
                raise UserError(_('Only notified applications can be accepted by a work unit.'))
            if not rec.work_unit_id:
                raise ValidationError(_("Please select an assigned work unit before accepting."))
            rec.sudo().write({'status': 'accepted', 'rejection_reason': False})
            clear_action_activities(rec)
            notify_action(rec, role_users(rec, 'group_eds_officer'),
                          _('Place accepted intern'),
                          _('Host work unit %s accepted internship application %s.')
                          % (rec.work_unit_id.name, rec.name))
            supervisor_user = rec.supervisor_id.sudo().user_id
            if supervisor_user and supervisor_user.active:
                notify_action(
                    rec, supervisor_user, _('Internship supervisor assigned'),
                    _('You have been assigned to supervise %s in %s. '
                      'The host will confirm the start and schedule.') % (
                          rec.applicant_name, rec.work_unit_id.name),
                    action_required=False)

    def action_place(self):
        for rec in self:
            rec._require_host_or_staff()
            if rec.status != 'accepted':
                raise UserError(_('Only accepted applications can be placed.'))
            if not rec.supervisor_id or not rec.start_date or not rec.end_date:
                raise ValidationError(_("Assign a supervisor and both internship dates before placement."))
            supervisor_user = rec.supervisor_id.sudo().user_id
            if not supervisor_user or not supervisor_user.active:
                raise ValidationError(_(
                    'The assigned internship supervisor needs an active Odoo account.'))
            rec.sudo().write({'status': 'placed'})
            clear_action_activities(rec)
            notify_action(rec, supervisor_user,
                          _('Supervise placed intern'),
                          _('Intern %s is placed with you from %s to %s.')
                          % (rec.applicant_name, rec.start_date, rec.end_date),
                          action_required=False)

    def action_start(self):
        for rec in self:
            rec._require_host_or_staff()
            if rec.status not in ('accepted', 'placed'):
                raise UserError(_('Only accepted or placed applications can be started.'))
            if not rec.supervisor_id or not rec.start_date or not rec.end_date:
                raise ValidationError(_(
                    'Assign a supervisor and both internship dates before confirming the start.'))
            if (self.env['eds.hr.compat'].get_employee_operating_unit(rec.supervisor_id)
                    != rec.work_unit_id):
                raise ValidationError(_(
                    'The assigned supervisor must belong to the host work unit.'))
            supervisor_user = rec.supervisor_id.sudo().user_id
            if not supervisor_user or not supervisor_user.active:
                raise ValidationError(_(
                    'The assigned internship supervisor needs an active Odoo account.'))
            if fields.Date.context_today(self) < rec.start_date:
                raise ValidationError(_('The internship cannot start before its placement date.'))
            if fields.Date.context_today(self) > rec.end_date:
                raise ValidationError(_(
                    'The internship end date has passed. Adjust the dates before confirming the start.'))
            rec.sudo().write({
                'status': 'ongoing',
                'start_confirmed_on': fields.Date.context_today(rec),
                'start_confirmed_by_id': self.env.user.id,
            })
            clear_action_activities(rec)
            notify_action(
                rec, supervisor_user, _('Evaluate active intern'),
                _('Intern %s has started in %s. Record periodic and final evaluations.')
                % (rec.applicant_name, rec.work_unit_id.name))
            notify_action(
                rec, role_users(rec, 'group_eds_officer'),
                _('Internship start confirmed'),
                _('%s started the internship on %s.')
                % (rec.applicant_name, rec.start_confirmed_on),
                action_required=False)

    def action_complete(self):
        for rec in self:
            rec._require_host_or_staff()
            if rec.status != 'ongoing':
                raise UserError(_('Only ongoing internships can be completed.'))
            if not rec.end_date or fields.Date.context_today(rec) < rec.end_date:
                raise ValidationError(_(
                    'The internship end date has not been reached. Adjust it if the placement ended early.'))
            rec.sudo().write({
                'status': 'completed',
                'completion_confirmed_on': fields.Date.context_today(rec),
                'completion_confirmed_by_id': self.env.user.id,
            })
            clear_action_activities(rec)
            recipients = (rec.work_unit_id.manager_id.sudo().user_id
                          | rec.supervisor_id.sudo().user_id
                          | role_users(rec, 'group_eds_officer'))
            notify_action(rec, recipients,
                          _('Internship completed'),
                          _('Internship for %s has been completed.')
                          % rec.applicant_name,
                          action_required=False)

    def action_reject(self):
        for rec in self:
            rec._require_host_or_staff()
            if (rec.status != 'notified' and not rec._is_eds_staff()) or rec.status not in (
                    'received', 'notified', 'accepted', 'placed'):
                raise UserError(_('Only a pending internship application can be rejected.'))
            if not (rec.rejection_reason or '').strip():
                raise ValidationError(_('Enter a rejection justification before rejecting the application.'))
            rec.sudo().write({'status': 'rejected'})
            clear_action_activities(rec)
            rec.message_post(body=_("Internship application rejected: %s") % rec.rejection_reason)
            notify_action(
                rec, role_users(rec, 'group_eds_officer'),
                _('Internship application rejected'),
                _('Internship application %s was rejected by %s. Reason: %s')
                % (rec.name, self.env.user.name, rec.rejection_reason),
                action_required=False)

    # Clearance & Final Appraisal Fields
    clearance_library = fields.Boolean(string='Bank Library / Resource Clearance')
    clearance_id_badge = fields.Boolean(string='Temporary ID Badge Surrendered')
    clearance_it_assets = fields.Boolean(string='IT / Workstation Access Cleared')
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
        """Prints official Form Internship Appraisal & Clearance PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_internship_appraisal').report_action(self)

class EdsInternshipEvaluation(models.Model):
    _name = 'eds.internship.evaluation'
    _description = 'EDS Internship Periodic Assessment'
    _order = 'create_date desc, id desc'

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

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            Application = self.env['eds.internship.application']
            for vals in vals_list:
                application = Application.browse(vals.get('application_id')).exists()
                if not application:
                    raise ValidationError(_('Select an internship application to evaluate.'))
                application.check_access('read')
                if (application.status != 'ongoing'
                        or not (application._is_host_manager()
                                or application._is_assigned_supervisor())):
                    raise AccessError(_(
                        'Only the host manager or assigned supervisor may evaluate an active internship.'))
                if vals.get('evaluated_by') not in (None, self.env.user.id):
                    raise AccessError(_('You may record only your own internship evaluation.'))
                vals['evaluated_by'] = self.env.user.id
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            if set(vals) - {'period', 'date', 'rating', 'comments'}:
                raise AccessError(_('You may edit only your own evaluation details.'))
            for rec in self:
                rec.check_access('write')
                application = rec.application_id
                application.check_access('read')
                if (application.status != 'ongoing'
                        or not (application._is_host_manager()
                                or application._is_assigned_supervisor())
                        or rec.evaluated_by != self.env.user):
                    raise AccessError(_(
                        'Only the original evaluator may update an active internship evaluation.'))
        return super().write(vals)
