# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    course_id = fields.Many2one('lms.course', string='Course to Assign', required=True, domain="[('state', '=', 'published')]")
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

    def action_execute_assignment(self):
        """Finds all matching employees and creates/updates enrollment records (FR-LMS-003)."""
        self.ensure_one()
        domain = [('active', '=', True)]

        if self.assignment_type == 'individual':
            target_employees = self.employee_ids
        elif self.assignment_type == 'department':
            if not self.department_ids:
                raise UserError(_('Please select at least one department.'))
            domain.append(('department_id', 'in', self.department_ids.ids))
            target_employees = self.env['hr.employee'].search(domain)
        elif self.assignment_type == 'operating_unit':
            if not self.operating_unit_ids:
                raise UserError(_('Please select at least one operating unit / branch.'))
            domain.append(('default_operating_unit_id', 'in', self.operating_unit_ids.ids))
            target_employees = self.env['hr.employee'].search(domain)
        elif self.assignment_type == 'job_position':
            if not self.job_ids:
                raise UserError(_('Please select at least one job position.'))
            domain.append(('job_id', 'in', self.job_ids.ids))
            target_employees = self.env['hr.employee'].search(domain)
        elif self.assignment_type == 'grade':
            if not self.grade_ids:
                raise UserError(_('Please select at least one employee grade.'))
            domain.append(('grade_id', 'in', self.grade_ids.ids))
            target_employees = self.env['hr.employee'].search(domain)
        elif self.assignment_type == 'all_staff':
            target_employees = self.env['hr.employee'].search(domain)
        else:
            target_employees = self.env['hr.employee'].browse([])

        if not target_employees:
            raise UserError(_('No active employees match the specified assignment criteria.'))

        Enrollment = self.env['lms.enrollment']
        count = 0
        courses_to_assign = [self.course_id]
        if self.learning_path_id:
            courses_to_assign = [pc.course_id for pc in self.learning_path_id.path_course_ids]

        for emp in target_employees:
            for crs in courses_to_assign:
                existing = Enrollment.search([('employee_id', '=', emp.id), ('course_id', '=', crs.id)], limit=1)
                if not existing:
                    Enrollment.create({
                        'employee_id': emp.id,
                        'course_id': crs.id,
                        'assignment_id': self.id,
                        'is_mandatory': self.is_mandatory,
                        'due_date': self.due_date,
                        'state': 'enrolled',
                    })
                    count += 1
                else:
                    if self.is_mandatory and not existing.is_mandatory:
                        existing.write({'is_mandatory': True, 'due_date': self.due_date})

        self.write({'state': 'executed', 'enrolled_count': count})
        self.message_post(body=_('Assignment executed successfully. %d new learner enrollment(s) created.') % count)
