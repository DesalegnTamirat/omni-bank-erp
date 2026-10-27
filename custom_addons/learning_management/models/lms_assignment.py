# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging

from odoo.exceptions import AccessError, UserError


_logger = logging.getLogger(__name__)


class LmsCourseAssignment(models.Model):
    """
    Automated & Rule-Based Course Assignment Engine (FR-LMS-003, FR-LMS-027).
    Deploys mandatory or elective training by Job Role, Department, Operating Unit, Grade, or Employee.
    Generates enrollment records and triggers automated assignment notifications.
    """
    _name = 'lms.course.assignment'
    _description = 'LMS Course Assignment Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Assignment Campaign Name', required=True, tracking=True)
    course_id = fields.Many2one('lms.course', string='Course to Assign', domain="[('state', '=', 'published')]")
    learning_path_id = fields.Many2one('lms.learning.path', string='Or Entire Learning Path')

    assignment_type = fields.Selection([
        ('individual', 'Specific Employees'),
        ('department', 'By Department'),
        ('operating_unit', 'By Operating Unit / Branch'),
        ('job_position', 'By Job Position / Role'),
        ('grade', 'By Employee Grade'),
        ('all_staff', 'All Bank Staff (Bank-Wide Mandatory)'),
    ], string='Assignment Scope', default='department', required=True, tracking=True)

    is_mandatory = fields.Boolean(string='Mandatory Assignment', default=True, tracking=True)
    due_date = fields.Date(string='Completion Deadline Date', required=True, tracking=True)

    # Scoping Selectors
    employee_ids = fields.Many2many('hr.employee', 'lms_assign_emp_rel', 'assign_id', 'emp_id', string='Target Employees')
    department_ids = fields.Many2many('hr.department', 'lms_assign_dept_rel', 'assign_id', 'dept_id', string='Target Departments')
    operating_unit_ids = fields.Many2many('operating.unit', 'lms_assign_ou_rel', 'assign_id', 'ou_id', string='Target Operating Units / Branches')
    job_ids = fields.Many2many('hr.job', 'lms_assign_job_rel', 'assign_id', 'job_id', string='Target Job Positions')
    grade_ids = fields.Many2many('employee.grade', 'lms_assign_grade_rel', 'assign_id', 'grade_id', string='Target Employee Grades')

    # Competency Gap Targeting Linkage (from competency_management)
    target_competency_id = fields.Many2one('competency.competency', string='Target Competency Gap Focus')

    state = fields.Selection([
        ('draft', 'Draft Configuration'),
        ('executed', 'Dispatched & Enrolled'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    enrolled_count = fields.Integer(string='Learners Enrolled', readonly=True)
    delivery_backfilled = fields.Boolean(
        string='Assignment Delivery History Reconciled', default=False, copy=False,
        help='Set after existing enrollments have been linked to this campaign.')

    @api.constrains('course_id', 'learning_path_id')
    def _check_course_or_path(self):
        for rec in self:
            if not rec.course_id and not rec.learning_path_id:
                raise UserError(_('Select a course or a learning path.'))

    def _check_assignment_manager(self):
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            raise AccessError(_('Only LMS managers may dispatch course assignments.'))

    def _courses_to_assign(self):
        self.ensure_one()
        courses_to_assign = self.course_id
        if self.learning_path_id:
            if not self.learning_path_id.active or not self.learning_path_id.path_course_ids:
                raise UserError(_('Select an active learning path with at least one course.'))
            courses_to_assign = self.learning_path_id.path_course_ids.mapped('course_id')
        if not courses_to_assign:
            raise UserError(_('Select a course or a learning path.'))
        # The form's course domain is only a UI hint. Validate the selected
        # course and every path stage here so RPC and imports cannot assign
        # material that has not been approved or has been superseded.
        for course in self.course_id | courses_to_assign:
            if course.state != 'published' or not course.is_latest_version or not course.active:
                raise UserError(_('Only active, latest published courses can be assigned: %s.') % course.name)
        return courses_to_assign

    def _target_employees(self, allow_empty=False):
        self.ensure_one()
        domain = [('active', '=', True)]

        if self.assignment_type == 'individual':
            target_employees = self.employee_ids.sudo().filtered('active')
        elif self.assignment_type == 'department':
            if not self.department_ids:
                raise UserError(_('Please select at least one department.'))
            domain.append(('department_id', 'in', self.department_ids.ids))
            target_employees = self.env['hr.employee'].sudo().search(domain)
        elif self.assignment_type == 'operating_unit':
            if not self.operating_unit_ids:
                raise UserError(_('Please select at least one operating unit / branch.'))
            domain.append(('default_operating_unit_id', 'in', self.operating_unit_ids.ids))
            target_employees = self.env['hr.employee'].sudo().search(domain)
        elif self.assignment_type == 'job_position':
            if not self.job_ids:
                raise UserError(_('Please select at least one job position.'))
            domain.append(('job_id', 'in', self.job_ids.ids))
            target_employees = self.env['hr.employee'].sudo().search(domain)
        elif self.assignment_type == 'grade':
            if not self.grade_ids:
                raise UserError(_('Please select at least one employee grade.'))
            # hr.employee.grade_id points to a different model in this ERP.
            # LMS grade targets use employee.grade via the employee's job.
            domain.append(('job_id.grade', 'in', self.grade_ids.ids))
            target_employees = self.env['hr.employee'].sudo().search(domain)
        elif self.assignment_type == 'all_staff':
            target_employees = self.env['hr.employee'].sudo().search(domain)
        else:
            target_employees = self.env['hr.employee'].sudo().browse([])

        if self.target_competency_id and target_employees:
            # Only approved, current assessment gaps should target staff. A
            # draft rating or an older superseded cycle is not assignment
            # evidence, and the primary line avoids duplicate 360 ratings.
            gap_lines = self.env['competency.assessment.line'].sudo().search([
                ('competency_id', '=', self.target_competency_id.id),
                ('state', 'in', ('approved', 'locked')),
                ('cycle_id.is_open_or_latest', '=', True),
                ('is_primary_reporting_line', '=', True),
                ('gap', '>', 0),
            ])
            target_employees &= gap_lines.mapped('employee_id')

        if not target_employees and not allow_empty:
            raise UserError(_('No active employees match the specified assignment criteria.'))
        return target_employees

    def _dispatch_matching_employees(self, allow_empty=False):
        """Assign new matches once, including employees who joined after launch.

        A delivery row records each campaign/employee/course pair. This keeps a
        finished attempt linked to its original campaign while making a later
        campaign eligible to start a new certification attempt.
        """
        self.ensure_one()
        self._check_assignment_manager()
        if self.state not in ('draft', 'executed'):
            raise UserError(_('Cancelled assignment campaigns cannot be dispatched.'))
        # Serialize dispatches, including a manual click racing the daily job.
        self.env.cr.execute('SELECT id FROM lms_course_assignment WHERE id = %s FOR UPDATE', (self.id,))
        courses_to_assign = self._courses_to_assign()
        target_employees = self._target_employees(allow_empty=allow_empty)
        Enrollment = self.env['lms.enrollment'].sudo()
        Delivery = self.env['lms.assignment.delivery'].sudo()
        count = 0

        for offset in range(0, len(target_employees), 200):
            employees = target_employees[offset:offset + 200]
            delivered = {
                (row.employee_id.id, row.course_id.id)
                for row in Delivery.search([
                    ('assignment_id', '=', self.id),
                    ('employee_id', 'in', employees.ids),
                    ('course_id', 'in', courses_to_assign.ids),
                ])
            }
            existing_records = Enrollment.search([
                ('employee_id', 'in', employees.ids),
                ('course_id', 'in', courses_to_assign.ids),
            ], order='attempt_number desc, id desc')
            existing_by_pair = {}
            for rec in existing_records:
                existing_by_pair.setdefault((rec.employee_id.id, rec.course_id.id), rec)
            to_create = []
            to_deliver = []
            for emp in employees:
                for crs in courses_to_assign:
                    key = (emp.id, crs.id)
                    if key in delivered:
                        continue
                    existing = existing_by_pair.get((emp.id, crs.id))
                    if existing and existing.state in ('enrolled', 'in_progress'):
                        if self.is_mandatory:
                            due_date = self.due_date
                            if existing.is_mandatory and existing.due_date:
                                due_date = min(existing.due_date, due_date)
                            existing.write({'is_mandatory': True, 'due_date': due_date})
                        to_deliver.append({
                            'assignment_id': self.id,
                            'employee_id': emp.id,
                            'course_id': crs.id,
                            'enrollment_id': existing.id,
                        })
                    else:
                        to_create.append({
                            'employee_id': emp.id,
                            'course_id': crs.id,
                            'assignment_id': self.id,
                            'is_mandatory': self.is_mandatory,
                            'due_date': self.due_date,
                            'state': 'enrolled',
                        })
            if to_create:
                created = Enrollment.create(to_create)
                count += len(created)
                to_deliver.extend({
                    'assignment_id': self.id,
                    'employee_id': rec.employee_id.id,
                    'course_id': rec.course_id.id,
                    'enrollment_id': rec.id,
                } for rec in created)
            if to_deliver:
                Delivery.create(to_deliver)
        return count

    def _backfill_legacy_deliveries(self):
        """Preserve existing executed campaigns during the delivery-model upgrade.

        Previous versions linked only enrollments created by a campaign. Existing
        completed or active attempts are treated as already assigned so the first
        scheduled reconciliation cannot suddenly re-enroll the whole bank.
        """
        self.ensure_one()
        self._check_assignment_manager()
        if self.delivery_backfilled:
            return
        courses = self._courses_to_assign()
        employees = self._target_employees(allow_empty=True)
        Enrollment = self.env['lms.enrollment'].sudo()
        Delivery = self.env['lms.assignment.delivery'].sudo()
        for offset in range(0, len(employees), 200):
            batch = employees[offset:offset + 200]
            existing = Enrollment.search([
                ('employee_id', 'in', batch.ids),
                ('course_id', 'in', courses.ids),
            ], order='attempt_number desc, id desc')
            latest = {}
            for rec in existing:
                latest.setdefault((rec.employee_id.id, rec.course_id.id), rec)
            if latest:
                Delivery.create([{
                    'assignment_id': self.id,
                    'employee_id': rec.employee_id.id,
                    'course_id': rec.course_id.id,
                    'enrollment_id': rec.id,
                } for rec in latest.values()])
        self.write({'delivery_backfilled': True})

    def action_execute_assignment(self):
        """Dispatch the initial audience of a draft assignment campaign."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only a draft assignment campaign can be executed.'))
        count = self._dispatch_matching_employees()

        self.write({'state': 'executed', 'enrolled_count': count, 'delivery_backfilled': True})
        self.message_post(body=_('Assignment executed successfully. %d new learner enrollment(s) created.') % count)

    @api.model
    def cron_reconcile_assignments(self):
        """Give new hires and transferred employees their active campaigns."""
        for campaign in self.sudo().search([('state', '=', 'executed')]):
            try:
                with self.env.cr.savepoint():
                    courses = (campaign.learning_path_id.path_course_ids.mapped('course_id')
                               if campaign.learning_path_id else campaign.course_id)
                    if (not courses or (campaign.learning_path_id and not campaign.learning_path_id.active)
                            or any(course.state != 'published' or not course.is_latest_version
                                   or not course.active for course in courses)):
                        continue
                    if not campaign.delivery_backfilled:
                        campaign._backfill_legacy_deliveries()
                    count = campaign._dispatch_matching_employees(allow_empty=True)
                    if count:
                        campaign.write({'enrolled_count': campaign.enrolled_count + count})
            except Exception:
                _logger.exception('LMS assignment reconciliation failed for campaign %s', campaign.id)
