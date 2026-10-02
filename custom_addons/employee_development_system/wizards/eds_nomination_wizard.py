# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsNominationWizard(models.TransientModel):
    """\"Nominate for Session\" wizard (, ...030).

    The officer picks a session, the eligible employees and - for TNA-based
    nominations - the source training needs. One nomination per employee is created
    and submitted directly into the approval chain. Employees whose approved TNA
    need is provided are nominated TNA-based; the rest fall back to ad-hoc and
    therefore require a justification + L&D approval .
    """
    _name = 'eds.nomination.wizard'
    _description = 'Nominate Employees for a Session'

    session_id = fields.Many2one(
        'eds.session', string='Session', required=True,
        domain="[('status', 'in', ('scheduled', 'ongoing', 'rescheduled'))]")
    course_name = fields.Char(string='Program', related='session_id.program_name', readonly=True)
    work_unit_id = fields.Many2one('operating.unit', string='Filter by Work Unit / Branch')
    department_id = fields.Many2one('hr.department', string='Filter by Department')
    job_position_id = fields.Many2one('hr.job', string='Filter by Job Position')
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        help='Employees to nominate for this session.')
    nomination_type = fields.Selection([
        ('tna_based', 'TNA-Based'),
        ('ad_hoc', 'Ad-Hoc (Justified Exception)'),
    ], string='Nomination Type', default='tna_based', required=True)
    tna_entry_ids = fields.Many2many(
        'eds.tna.entry', string='Source TNA Needs',
        domain="[('state', 'in', ('approved', 'converted')), "
               "('delivery_mode', 'in', ('classroom', 'blended'))]",
        help='Approved training needs to link. The wizard links each employee to their '
             'own need automatically .')
    justification = fields.Text(
        string='Justification',
        help='Mandatory when nominating ad-hoc . Applied to ad-hoc nominations.')

    def _get_nomination_employee_domain(self):
        base_domain = self.env['eds.hr.compat'].get_employee_domain(
            department=self.department_id, operating_unit=self.work_unit_id, job=self.job_position_id
        )
        base_domain.append(('active', '=', True))
        if self.nomination_type == 'tna_based' and self.session_id and self.session_id.course_id:
            if self.tna_entry_ids:
                tna_emps = self.tna_entry_ids.mapped('employee_id') | self.tna_entry_ids.mapped('hr_assigned_participant_ids')
                base_domain.append(('id', 'in', tna_emps.ids))
            else:
                approved_tnas = self.env['eds.tna.entry'].search([
                    ('state', 'in', ('approved', 'converted')),
                    ('course_id', '=', self.session_id.course_id.id),
                ])
                if approved_tnas:
                    tna_emps = approved_tnas.mapped('employee_id') | approved_tnas.mapped('hr_assigned_participant_ids')
                    base_domain.append(('id', 'in', tna_emps.ids))
        return base_domain

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Top of hierarchy: Department -> Operating Unit -> Job Position.
        - If department selected:
          work_unit_id domain restricted to operating units belonging to this department.
          If selected work_unit_id doesn't belong to the department, clear it.
          job_position_id and employee_ids restricted to the department.
        - If no department selected:
          All operating units, jobs, and employees are available.
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_id)
        if self.department_id:
            if self.work_unit_id and not self.env['eds.hr.compat'].is_operating_unit_in_departments(self.work_unit_id, self.department_id):
                self.work_unit_id = False
            if self.job_position_id and self.job_position_id.department_id and self.job_position_id.department_id != self.department_id:
                self.job_position_id = False
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'work_unit_id': ou_domain, 'job_position_id': job_domain, 'employee_ids': emp_domain}}

    @api.onchange('work_unit_id')
    def _onchange_work_unit_id(self):
        """Middle of hierarchy: Operating Unit -> Job Position.
        Filter job position and employee based on selected work unit and department.
        """
        if self.work_unit_id and not self.department_id:
            if hasattr(self.work_unit_id, 'department') and self.work_unit_id.department:
                self.department_id = self.work_unit_id.department
            elif 'operating_unit_id' in self.env['hr.department']._fields:
                linked_dept = self.env['hr.department'].search([('operating_unit_id', '=', self.work_unit_id.id)], limit=1)
                if linked_dept:
                    self.department_id = linked_dept

        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_id, operating_units=self.work_unit_id)
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'job_position_id': job_domain, 'employee_ids': emp_domain}}

    @api.onchange('job_position_id')
    def _onchange_job_position_id(self):
        if self.job_position_id and self.job_position_id.department_id:
            if not self.department_id:
                self.department_id = self.job_position_id.department_id
            if self.department_id.operating_unit_id and not self.work_unit_id:
                self.work_unit_id = self.department_id.operating_unit_id
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'employee_ids': emp_domain}}

    @api.onchange('session_id')
    def _onchange_session_id(self):
        self.employee_ids = False
        self.tna_entry_ids = False
        tna_domain = [('state', 'in', ('approved', 'converted')), ('delivery_mode', 'in', ('classroom', 'blended'))]
        if self.session_id and self.session_id.course_id:
            course = self.session_id.course_id
            tna_domain.append(('course_id', '=', course.id))
            if course.target_scope == 'targeted':
                if len(course.operating_unit_ids) == 1 and not self.work_unit_id:
                    self.work_unit_id = course.operating_unit_ids[0]
                if len(course.department_ids) == 1 and not self.department_id:
                    self.department_id = course.department_ids[0]
                if len(course.target_audience_ids) == 1 and not self.job_position_id:
                    self.job_position_id = course.target_audience_ids[0]
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'employee_ids': emp_domain, 'tna_entry_ids': tna_domain}}

    @api.onchange('tna_entry_ids')
    def _onchange_tna_entry_ids(self):
        if self.tna_entry_ids:
            emps = self.tna_entry_ids.mapped('employee_id') | self.tna_entry_ids.mapped('hr_assigned_participant_ids')
            if emps:
                self.employee_ids = [(6, 0, emps.ids)]
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'employee_ids': emp_domain}}

    @api.onchange('nomination_type')
    def _onchange_nomination_type(self):
        if self.nomination_type == 'tna_based':
            self.justification = False
        emp_domain = self._get_nomination_employee_domain()
        return {'domain': {'employee_ids': emp_domain}}

    def action_create_nominations(self):
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_('Select at least one employee to nominate.'))
        # Pre-validate: employees without a matching approved TNA need become ad-hoc
        # nominations, which always require a justification .
        missing_entry = any(not self._find_entry_for(emp) for emp in self.employee_ids)
        if (self.nomination_type == 'ad_hoc' or missing_entry) and not self.justification:
            raise UserError(_('Ad-hoc nominations require a mandatory justification. '
                              'Some employees have no matching approved training need, '
                              'so a justification is required.'))
        # Skip employees who already have a nomination for this session (unique constraint
        # on session_id + employee_id) instead of failing mid-loop.
        existing = self.env['eds.nomination'].search(
            [('session_id', '=', self.session_id.id),
             ('employee_id', 'in', self.employee_ids.ids),
             ('state', 'not in', ('withdrawn', 'rejected', 'declined'))])
        eligible = self.employee_ids - existing.mapped('employee_id')
        if not eligible:
            raise UserError(_('All selected employees already have a nomination for this session.'))
        if len(eligible) != len(self.employee_ids):
            self.session_id.message_post(
                body=_('%d employee(s) skipped - they already have a nomination for this session.') % (
                    len(self.employee_ids) - len(eligible)))
        created = self.env['eds.nomination']
        for employee in eligible:
            entry = self._find_entry_for(employee)
            nomination_type = self.nomination_type
            if nomination_type == 'tna_based' and not entry:
                nomination_type = 'ad_hoc'
            nomination = self.env['eds.nomination'].create({
                'session_id': self.session_id.id,
                'employee_id': employee.id,
                'nomination_type': nomination_type,
                'tna_entry_id': entry.id if entry else False,
                'justification': self.justification if nomination_type == 'ad_hoc' else False,
            })
            nomination.action_submit()
            created |= nomination
        return {
            'name': _('Nominations'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.nomination',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
            'target': 'current',
        }

    def _find_entry_for(self, employee):
        """The approved TNA need of this employee (per session program if possible)."""
        course = self.session_id.course_id
        if self.tna_entry_ids:
            matching = self.tna_entry_ids.filtered(
                lambda e: (e.employee_id == employee or employee in e.hr_assigned_participant_ids)
                and (not course or not e.course_id or e.course_id == course
                     or not e.proposed_program or e.proposed_program == course.name))
            if matching:
                return matching[:1]

        if course:
            entry = self.env['eds.tna.entry'].search([
                ('state', 'in', ('approved', 'converted')),
                ('course_id', '=', course.id),
                '|', ('employee_id', '=', employee.id),
                ('hr_assigned_participant_ids', 'in', employee.id),
            ], limit=1)
            if entry:
                return entry
        return self.env['eds.tna.entry']
