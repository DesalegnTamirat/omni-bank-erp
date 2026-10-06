# -*- coding: utf-8 -*-
import io
import csv
import base64
import os
import xlsxwriter
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError

class CompetencyReportWizard(models.TransientModel):
    """Multi-format export wizard (PDF, Excel, CSV) with cascading department/pillar filters."""
    _name = 'competency.report.wizard'
    _description = 'Competency Cascading Report & Export Wizard'



    def web_read(self, specification):
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR / People Solution Officers and Competency Administrators can access reporting."))
        return super(CompetencyReportWizard, self.sudo()).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR / People Solution Officers and Competency Administrators can access reporting."))
        return super(CompetencyReportWizard, self.sudo()).read(fields=fields, load=load)

    @api.model
    def _get_user_scope_ou_ids(self, user):
        """Resolve the Operating Unit boundary for a non-admin user.

        `assigned_operating_unit_ids` (the manager's supervisory/reporting scope, set on
        Job Position assignment) is authoritative and MUST take priority over the broader
        `operating_unit_ids` (general multi-branch working access, e.g. teller access) so
        that report/wizard scoping matches the ir.rule record rules in
        security/competency_security.xml exactly. Falling back to the wrong field here would
        let a manager export data for branches they are not assigned to supervise.
        """
        if getattr(user, 'assigned_operating_unit_ids', False):
            return user.assigned_operating_unit_ids.ids
        if getattr(user, 'operating_unit_ids', False):
            return user.operating_unit_ids.ids
        if getattr(user, 'default_operating_unit_id', False):
            return [user.default_operating_unit_id.id]
        emp = user.employee_id
        if emp:
            emp_ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
            if emp_ou:
                return [emp_ou.id]
        return []

    # Report Configuration & Format Selection
    report_type = fields.Selection([
        ('detailed_matrix', 'Comprehensive Competency Performance & Gap Matrix (Detailed)'),
        ('dept_role_gap', 'Departmental & Role Competency Gap Analysis'),
        ('individual', 'Individual Employee Competency Profile'),
        ('campaign_progress', 'Assessment Completion & Campaign Progress Tracking'),
    ], string='Report Type', default='detailed_matrix', required=True)

    export_format = fields.Selection([
        ('xlsx', 'Excel Spreadsheet (.xlsx)'),
        ('pdf', 'PDF Document (.pdf)'),
        ('csv', 'CSV Dataset (.csv)'),
    ], string='Export Format', default='xlsx', required=True)

    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Campaign / Cycle', required=True,
        default=lambda self: self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        or self.env['competency.assessment.cycle'].search([], order='id desc', limit=1))

    comparison_cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Comparison Cycle (Previous)',
        help='Select the earlier / previous cycle to compare ratings and gap progression against the selected cycle.'
    )

    assessment_type_filter = fields.Selection([
        ('all', 'All Ratings (Composite 360°)'),
        ('self', 'Self-Assessment Only'),
        ('peer', 'Peer Evaluation Only'),
        ('subordinate', 'Subordinate Evaluation Only'),
        ('supervisor', 'Supervisor Rating Only'),
    ], string='Assessment Type Filter', default='all', required=True,
       help='Filter reporting data strictly by one assessment rating type, calculating the gap directly between required proficiency and that single rating.')

    include_self_gap = fields.Boolean(string='Include Self Rating Gap', default=False)
    include_peer_gap = fields.Boolean(string='Include Peer Rating Gap', default=False)
    include_subordinate_gap = fields.Boolean(string='Include Subordinate Rating Gap', default=False)
    include_supervisor_gap = fields.Boolean(string='Include Supervisor Rating Gap', default=False)

    # User Permission Flags for Role-Based UI Scoping
    is_dept_readonly = fields.Boolean(compute='_compute_user_permissions')
    is_ou_readonly = fields.Boolean(compute='_compute_user_permissions')
    is_emp_readonly = fields.Boolean(compute='_compute_user_permissions')

    # Cascading Organizational Filters: Department -> Operating Unit / Workunit -> Job Position -> Employee
    department_ids = fields.Many2many('hr.department', string='Departments')
    operating_unit_ids = fields.Many2many('operating.unit', string='Workunits / Branches')
    job_ids = fields.Many2many('hr.job', string='Job Roles / Positions')
    grade_ids = fields.Many2many('employee.grade', string='Job Grades')
    employee_ids = fields.Many2many('hr.employee', string='Specific Employees')

    # Evaluation & Status Filters
    stage_filter = fields.Selection([
        ('all', 'All Stages'),
        ('draft', 'Draft (In Progress)'),
        ('submitted', 'Submitted'),
        ('closed', 'Cycle Closed'),
    ], string='Assessment Stage', default='all', required=True)

    pillar = fields.Selection([
        ('all', 'All Competency Pillars'),
        ('core', 'Core Pillar'),
        ('leadership', 'Leadership Pillar'),
        ('technical', 'Technical Pillar'),
    ], string='Competency Pillars / Categories', default='all', required=True)

    competency_ids = fields.Many2many('competency.competency', string='Competencies')
    competency_domain = fields.Char(compute='_compute_dynamic_domains')
    operating_unit_domain = fields.Char(compute='_compute_dynamic_domains')
    employee_domain = fields.Char(compute='_compute_dynamic_domains')

    required_level = fields.Selection([
        ('all', 'All Required Proficiency Levels'),
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency Levels', default='all', required=True)

    current_level = fields.Selection([
        ('all', 'All Current Levels'),
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Current Rating Level', default='all', required=True)

    achievement_status = fields.Selection([
        ('all', 'All Statuses'),
        ('below', 'Underqualified (Gap > 0)'),
        ('meets', 'Fit / Qualified (Gap = 0)'),
        ('exceeds', 'Overqualified (Gap < 0)'),
    ], string='Proficiency Filter', default='all', required=True)

    is_status_readonly = fields.Boolean(compute='_compute_status_readonly', store=False)

    @api.depends_context('uid')
    def _compute_user_permissions(self):
        user = self.env.user.sudo()
        is_admin = bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        emp = user.employee_id
        is_supervisor = user.has_group('competency_management.group_competency_supervisor') or (emp and bool(emp.child_ids))

        # Check if user is a Department Leader / Manager
        is_dept_manager = False
        if emp:
            managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
            if managed_depts or (emp.department_id and emp.department_id.manager_id.id == emp.id):
                is_dept_manager = True

        for rec in self:
            if is_admin or not emp:
                # 1. Administrator: Unrestricted across all departments, OUs, and employees
                rec.is_dept_readonly = False
                rec.is_ou_readonly = False
                rec.is_emp_readonly = False
            elif is_dept_manager:
                # 2. Department Leader: Department locked, but Operating Units & Employees within that department are selectable
                rec.is_dept_readonly = True
                rec.is_ou_readonly = False
                rec.is_emp_readonly = False
            else:
                # 3. Below Operating Unit (Coach, Unit Supervisor, Regular User):
                # Both Department and Operating Unit are strictly read-only!
                rec.is_dept_readonly = True
                rec.is_ou_readonly = True
                # A supervisor / coach below OU can select their team members; a regular employee is locked to themselves
                rec.is_emp_readonly = False if is_supervisor else True

    @api.model
    def default_get(self, fields_list):
        # Access guard: only Officers and Administrators may open reporting wizards
        _user = self.env.user
        if not (self.env.is_admin() or self.env.su
                or _user.has_group('competency_management.group_competency_officer')
                or _user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can access reporting."))
        res = super().default_get(fields_list)
        user = self.env.user.sudo()
        emp = user.employee_id
        is_admin = bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )
        if not emp or is_admin:
            return res

        managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
        is_dept_manager = bool(managed_depts or (emp.department_id and emp.department_id.manager_id.id == emp.id))

        if is_dept_manager:
            depts = managed_depts or emp.department_id
            if depts and 'department_ids' in fields_list:
                res['department_ids'] = [(6, 0, depts.ids)]
        else:
            # Below Operating Unit (Coach / Regular User)
            user_ou_ids = self._get_user_scope_ou_ids(user)
            if emp.department_id and 'department_ids' in fields_list:
                res['department_ids'] = [(6, 0, [emp.department_id.id])]
            if user_ou_ids and 'operating_unit_ids' in fields_list:
                res['operating_unit_ids'] = [(6, 0, user_ou_ids)]

            is_supervisor = user.has_group('competency_management.group_competency_supervisor') or bool(emp.child_ids)
            if not is_supervisor and 'employee_ids' in fields_list:
                res['employee_ids'] = [(6, 0, [emp.id])]

        return res

    @api.depends('required_level', 'current_level')
    def _compute_status_readonly(self):
        """Auto-compute achievement_status and set readonly if both required_level and current_level are specific."""
        for rec in self:
            if rec.required_level and rec.required_level != 'all' and rec.current_level and rec.current_level != 'all':
                req = int(rec.required_level)
                curr = int(rec.current_level)
                gap = req - curr
                if gap > 0:
                    rec.achievement_status = 'below'
                elif gap == 0:
                    rec.achievement_status = 'meets'
                else:
                    rec.achievement_status = 'exceeds'
                rec.is_status_readonly = True
            else:
                rec.is_status_readonly = False

    @api.depends('pillar', 'department_ids', 'operating_unit_ids')
    def _compute_dynamic_domains(self):
        for rec in self:
            # 1. Competency Domain
            if rec.pillar and rec.pillar != 'all':
                comp_dom = [('pillar', '=', rec.pillar), ('state', '=', 'approved')]
            else:
                comp_dom = [('state', '=', 'approved')]
            rec.competency_domain = str(comp_dom)

            # 2. Operating Unit Domain
            if rec.department_ids:
                ou_direct = self.env['operating.unit'].search([('department', 'in', rec.department_ids.ids)])
                ou_from_dept = rec.department_ids.mapped('operating_unit_id')
                dept_emps = self.env['hr.employee'].search([('department_id', 'in', rec.department_ids.ids)])
                ou_from_emps = dept_emps.mapped('default_operating_unit_id') | dept_emps.mapped('operating_unit_id')
                allowed_ous = (ou_direct | ou_from_dept | ou_from_emps).filtered(lambda u: u.id)
                rec.operating_unit_domain = str([('id', 'in', allowed_ous.ids)])
            else:
                rec.operating_unit_domain = '[]'

            # 3. Employee Domain
            emp_conditions = [('active', '=', True)]
            if rec.department_ids and rec.operating_unit_ids:
                emp_conditions.append(('department_id', 'in', rec.department_ids.ids))
                emp_conditions.extend([
                    '|',
                    ('default_operating_unit_id', 'in', rec.operating_unit_ids.ids),
                    ('operating_unit_id', 'in', rec.operating_unit_ids.ids)
                ])
            elif rec.operating_unit_ids:
                emp_conditions.extend([
                    '|',
                    ('default_operating_unit_id', 'in', rec.operating_unit_ids.ids),
                    ('operating_unit_id', 'in', rec.operating_unit_ids.ids)
                ])
            elif rec.department_ids:
                emp_conditions.append(('department_id', 'in', rec.department_ids.ids))

            rec.employee_domain = str(emp_conditions)

    @api.onchange('cycle_id', 'department_ids')
    def _onchange_department_ids(self):
        """Cascading Filter 1: Department -> Operating Unit, Jobs, and Employees."""
        if self.department_ids:
            ou_direct = self.env['operating.unit'].search([('department', 'in', self.department_ids.ids)])
            ou_from_dept = self.department_ids.mapped('operating_unit_id')
            dept_emps = self.env['hr.employee'].search([('department_id', 'in', self.department_ids.ids)])
            ou_from_emps = dept_emps.mapped('default_operating_unit_id') | dept_emps.mapped('operating_unit_id')
            allowed_ous = (ou_direct | ou_from_dept | ou_from_emps).filtered(lambda u: u.id)
            domain_ou = [('id', 'in', allowed_ous.ids)]
            domain_job = [('department_id', 'in', self.department_ids.ids)]

            # Prune selected operating units that no longer match the selected departments
            if self.operating_unit_ids:
                self.operating_unit_ids = self.operating_unit_ids.filtered(lambda u: u.id in allowed_ous.ids)

            # Prune selected jobs
            if self.job_ids:
                matching_jobs = self.env['hr.job'].search(domain_job)
                self.job_ids = self.job_ids & matching_jobs

            if not self.operating_unit_ids:
                domain_emp = [('active', '=', True), ('department_id', 'in', self.department_ids.ids)]
            else:
                domain_emp = [
                    ('active', '=', True),
                    ('department_id', 'in', self.department_ids.ids),
                    '|', ('default_operating_unit_id', 'in', self.operating_unit_ids.ids), ('department_id.operating_unit_id', 'in', self.operating_unit_ids.ids)
                ]
            if self.employee_ids:
                matching_emps = self.env['hr.employee'].search(domain_emp)
                self.employee_ids = self.employee_ids & matching_emps
        else:
            domain_ou = []
            domain_job = []
            if self.operating_unit_ids:
                domain_emp = [
                    ('active', '=', True),
                    '|', ('default_operating_unit_id', 'in', self.operating_unit_ids.ids), ('department_id.operating_unit_id', 'in', self.operating_unit_ids.ids)
                ]
                if self.employee_ids:
                    matching_emps = self.env['hr.employee'].search(domain_emp)
                    self.employee_ids = self.employee_ids & matching_emps
            else:
                domain_emp = [('active', '=', True)]

        return {'domain': {'operating_unit_ids': domain_ou, 'job_ids': domain_job, 'employee_ids': domain_emp}}

    @api.onchange('operating_unit_ids')
    def _onchange_operating_unit_ids(self):
        """Cascading Filter 2: Operating Unit -> Employee."""
        domain_emp = [('active', '=', True)]
        if self.operating_unit_ids and self.department_ids:
            domain_emp.append(('department_id', 'in', self.department_ids.ids))
            domain_emp.extend([
                '|', ('default_operating_unit_id', 'in', self.operating_unit_ids.ids),
                     ('operating_unit_id', 'in', self.operating_unit_ids.ids)
            ])
        elif self.operating_unit_ids:
            domain_emp.extend([
                '|', ('default_operating_unit_id', 'in', self.operating_unit_ids.ids),
                     ('operating_unit_id', 'in', self.operating_unit_ids.ids)
            ])
        elif self.department_ids:
            domain_emp.append(('department_id', 'in', self.department_ids.ids))

        if self.employee_ids:
            matching_emps = self.env['hr.employee'].search(domain_emp)
            self.employee_ids = self.employee_ids & matching_emps

        return {'domain': {'employee_ids': domain_emp}}

    @api.onchange('job_ids')
    def _onchange_job_ids(self):
        """Cascading Filter 3: Job Position -> Employee."""
        if self.job_ids:
            domain_emp = [('active', '=', True), ('job_id', 'in', self.job_ids.ids)]
            if self.department_ids:
                domain_emp.append(('department_id', 'in', self.department_ids.ids))
            return {'domain': {'employee_ids': domain_emp}}
        return {}

    @api.onchange('pillar')
    def _onchange_pillar(self):
        """Cascading Filter 4: Pillar -> Competencies."""
        if self.pillar and self.pillar != 'all':
            domain_comp = [('pillar', '=', self.pillar), ('state', '=', 'approved')]
            if self.competency_ids:
                self.competency_ids = self.competency_ids.filtered(lambda c: c.pillar == self.pillar)
        else:
            domain_comp = [('state', '=', 'approved')]
        return {'domain': {'competency_ids': domain_comp}}

    def _build_line_domain(self, cycle=None):
        """Construct domain based on wizard selections and enforce server-side boundary isolation."""
        target_cycle = cycle or self.cycle_id
        domain = [('cycle_id', '=', target_cycle.id), ('is_primary_reporting_line', '=', True)]

        user = self.env.user.sudo()
        emp = user.employee_id
        is_admin = bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )

        # Server-side Boundary Scoping for non-admins
        if not is_admin and emp:
            managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
            is_dept_manager = bool(managed_depts or (emp.department_id and emp.department_id.manager_id.id == emp.id))
            if is_dept_manager:
                # Scoped to their managed department(s)
                depts = managed_depts or emp.department_id
                domain.append(('department_id', 'in', depts.ids))
            else:
                user_ou_ids = self._get_user_scope_ou_ids(user)
                is_supervisor = user.has_group('competency_management.group_competency_supervisor') or bool(emp.child_ids)
                if is_supervisor:
                    # Scoped to their operating unit or team
                    if user_ou_ids:
                        domain.append('|')
                        domain.append(('employee_id.default_operating_unit_id', 'in', user_ou_ids))
                        domain.append(('department_id.operating_unit_id', 'in', user_ou_ids))
                else:
                    # Individual employee: only themselves
                    domain.append(('employee_id', '=', emp.id))

        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.operating_unit_ids:
            domain.append('|')
            domain.append(('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids))
            domain.append(('department_id.operating_unit_id', 'in', self.operating_unit_ids.ids))
        if self.job_ids:
            domain.append(('employee_id.job_id', 'in', self.job_ids.ids))
        if self.grade_ids:
            domain.append(('employee_id.grade_id', 'in', self.grade_ids.ids))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.competency_ids:
            domain.append(('competency_id', 'in', self.competency_ids.ids))
        if self.pillar != 'all':
            domain.append(('pillar', '=', self.pillar))
        if self.required_level != 'all':
            domain.append(('required_level', '=', self.required_level))
        if self.current_level != 'all':
            domain.append(('current_level', '=', self.current_level))
        if self.achievement_status != 'all':
            domain.append(('achievement_status', '=', self.achievement_status))
        if self.stage_filter != 'all':
            if self.stage_filter == 'closed':
                domain.append(('assessment_id.cycle_id.state', '=', 'closed'))
            else:
                domain.append(('assessment_id.state', '=', self.stage_filter))

        if self.assessment_type_filter == 'self':
            domain.append(('self_rating', '>', 0))
        elif self.assessment_type_filter == 'peer':
            domain.append(('peer_avg', '>', 0))
        elif self.assessment_type_filter == 'subordinate':
            domain.append(('subordinate_avg', '>', 0))
        elif self.assessment_type_filter == 'supervisor':
            domain.append(('supervisor_avg', '>', 0))
        return domain

    def action_generate_report(self):
        """Primary action: Generate Report based on Export Format & Report Type selections."""
        self.ensure_one()
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR / People Solution Officers and Competency Administrators can generate competency reports."))
        if self.export_format == 'pdf':
            return self.action_print_pdf()
        elif self.export_format == 'csv':
            return self.action_export_csv()
        else:
            return self.action_export_xlsx()

    def action_apply_filter(self):
        """Action: Open filtered list/pivot view tailored to selected report_type."""
        self.ensure_one()
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR / People Solution Officers and Competency Administrators can access reporting views."))

        if self.report_type == 'detailed_matrix':
            domain = self._build_line_domain()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Comprehensive Competency Performance & Gap Matrix'),
                'res_model': 'competency.assessment.line',
                'view_mode': 'list,pivot,graph,form',
                'views': [
                    (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
                ],
                'domain': domain,
                'context': {
                    'search_default_filter_primary_reporting': 1,
                    'assessment_type_filter': self.assessment_type_filter or 'all',
                    'create': False,
                    'edit': False,
                    'delete': False,
                },
                'target': 'current',
            }

        elif self.report_type == 'dept_role_gap':
            domain = self._build_line_domain()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Departmental & Role Competency Gap Analysis'),
                'res_model': 'competency.assessment.line',
                'view_mode': 'pivot,list,graph,form',
                'views': [
                    (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                    (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
                ],
                'domain': domain,
                'context': {
                    'search_default_filter_primary_reporting': 1,
                    'group_by': ['department_id', 'job_id'],
                    'create': False,
                    'edit': False,
                    'delete': False,
                },
                'target': 'current',
            }

        elif self.report_type == 'individual':
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            if self.operating_unit_ids:
                asm_domain.extend([
                    '|', ('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids),
                    ('employee_id.operating_unit_id', 'in', self.operating_unit_ids.ids)
                ])
            if self.job_ids:
                asm_domain.append(('job_id', 'in', self.job_ids.ids))
            if self.employee_ids:
                asm_domain.append(('employee_id', 'in', self.employee_ids.ids))
            if self.stage_filter and self.stage_filter != 'all':
                asm_domain.append(('state', '=', self.stage_filter))

            return {
                'type': 'ir.actions.act_window',
                'name': _('Individual Employee Competency Profiles'),
                'res_model': 'competency.assessment',
                'view_mode': 'list,form,pivot,graph',
                'domain': asm_domain,
                'context': {
                    'group_by': ['department_id'],
                },
                'target': 'current',
            }

        elif self.report_type == 'campaign_progress':
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            if self.operating_unit_ids:
                asm_domain.extend([
                    '|', ('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids),
                    ('employee_id.operating_unit_id', 'in', self.operating_unit_ids.ids)
                ])
            if self.stage_filter and self.stage_filter != 'all':
                asm_domain.append(('state', '=', self.stage_filter))

            return {
                'type': 'ir.actions.act_window',
                'name': _('Assessment Completion & Campaign Progress Tracking'),
                'res_model': 'competency.assessment',
                'view_mode': 'pivot,list,graph',
                'domain': asm_domain,
                'context': {
                    'group_by': ['department_id', 'state'],
                },
                'target': 'current',
            }

    def _get_360_report_data_rows(self):
        """Compute comprehensive 360 weighted data rows for reports and exports."""
        self.ensure_one()
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        config_data = config.read(['weight_self', 'weight_peer', 'weight_subordinate', 'weight_supervisor', 'weight_team']) if config else []
        if config_data:
            c_dict = config_data[0]
            w_self = float(c_dict.get('weight_self') or 2.0)
            w_peer = float(c_dict.get('weight_peer') or 1.0)
            w_sub = float(c_dict.get('weight_subordinate') or 1.0)
            w_sup = float(c_dict.get('weight_supervisor') or 3.0)
            w_team = float(c_dict.get('weight_team') or 0.0)
        else:
            w_self, w_peer, w_sub, w_sup, w_team = 2.0, 1.0, 1.0, 3.0, 0.0

        line_domain = self._build_line_domain()
        lines = self.env['competency.assessment.line'].sudo().search(line_domain)

        rows = []
        rating_filter = self.assessment_type_filter or 'all'

        for l in lines:
            emp = l.employee_id
            comp = l.competency_id

            self_val = float(l.self_rating) if l.self_rating and l.self_rating > 0 else None
            peer_avg = float(l.peer_avg) if l.peer_avg and l.peer_avg > 0 else None
            sub_avg = float(l.subordinate_avg) if l.subordinate_avg and l.subordinate_avg > 0 else None
            sup_avg = float(l.supervisor_avg) if l.supervisor_avg and l.supervisor_avg > 0 else None
            final_rating = float(l.weighted_current_level) if l.weighted_current_level else 0.0

            req_str = l.required_level or '2'
            req_val = int(req_str) if str(req_str).isdigit() else 2

            self_gap = float(l.self_gap) if l.self_gap is not None else None
            peer_gap = float(l.peer_gap) if l.peer_gap is not None else None
            sub_gap = float(l.subordinate_gap) if l.subordinate_gap is not None else None
            sup_gap = float(l.supervisor_gap) if l.supervisor_gap is not None else None
            weighted_gap = float(l.gap) if l.gap is not None else round(req_val - final_rating, 2)

            if rating_filter == 'self':
                if self_val is None or self_val <= 0:
                    continue
                active_rating = self_val
                active_gap = self_gap
                gap_for_status = self_gap
            elif rating_filter == 'peer':
                if peer_avg is None or peer_avg <= 0:
                    continue
                active_rating = peer_avg
                active_gap = peer_gap
                gap_for_status = peer_gap
            elif rating_filter == 'subordinate':
                if sub_avg is None or sub_avg <= 0:
                    continue
                active_rating = sub_avg
                active_gap = sub_gap
                gap_for_status = sub_gap
            elif rating_filter == 'supervisor':
                if sup_avg is None or sup_avg <= 0:
                    continue
                active_rating = sup_avg
                active_gap = sup_gap
                gap_for_status = sup_gap
            else:
                active_rating = final_rating
                active_gap = weighted_gap
                gap_for_status = weighted_gap

            if gap_for_status is not None:
                if gap_for_status > 0:
                    status_str = 'Underqualified'
                elif gap_for_status < 0:
                    status_str = 'Overqualified'
                else:
                    status_str = 'Fit / Qualified'
            else:
                status_str = 'Not Evaluated'

            # Strictly enforce wizard level & status filters
            if self.achievement_status != 'all':
                if self.achievement_status == 'below' and status_str != 'Underqualified':
                    continue
                elif self.achievement_status == 'meets' and status_str != 'Fit / Qualified':
                    continue
                elif self.achievement_status == 'exceeds' and status_str != 'Overqualified':
                    continue

            if self.current_level != 'all':
                try:
                    c_int = int(self.current_level)
                    if active_rating is None or round(active_rating) != c_int:
                        continue
                except (ValueError, TypeError):
                    pass

            if self.required_level != 'all':
                try:
                    r_int = int(self.required_level)
                    if req_val != r_int:
                        continue
                except (ValueError, TypeError):
                    pass

            ou_obj = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
            grade_obj = getattr(emp, 'grade_id', False)
            emp_job = l.job_id or getattr(emp, 'job_position', False) or emp.job_id
            gender_lbl = 'N/A'
            if hasattr(emp, 'gender') and emp.gender:
                gender_lbl = dict(emp._fields['gender'].selection).get(emp.gender, emp.gender.capitalize())

            rows.append({
                'cycle_name': self.cycle_id.name,
                'emp_id_code': emp.id,
                'emp_name': emp.name,
                'gender': gender_lbl,
                'operating_unit_name': ou_obj.name if ou_obj else 'N/A',
                'department_name': emp.department_id.name if emp.department_id else 'N/A',
                'job_name': emp_job.name if emp_job else 'N/A',
                'grade_name': (getattr(grade_obj, 'grade_name', False) or getattr(grade_obj, 'name', False) or 'N/A') if grade_obj else 'N/A',
                'competency_name': comp.name,
                'pillar_name': dict(comp._fields['pillar'].selection).get(comp.pillar, comp.pillar),
                'domain_name': comp.functional_domain or 'General',
                'self_rating': self_val if self_val is not None else 'N/A',
                'peer_avg': peer_avg if peer_avg is not None else 'N/A',
                'subordinate_avg': sub_avg if sub_avg is not None else 'N/A',
                'supervisor_avg': sup_avg if sup_avg is not None else 'N/A',
                'self_gap': self_gap if self_gap is not None else 'N/A',
                'peer_gap': peer_gap if peer_gap is not None else 'N/A',
                'subordinate_gap': sub_gap if sub_gap is not None else 'N/A',
                'supervisor_gap': sup_gap if sup_gap is not None else 'N/A',
                'weighted_rating': round(final_rating, 2),
                'required_level': f"Level {req_val}",
                'weighted_gap': weighted_gap,
                'active_rating': active_rating if active_rating is not None else 'N/A',
                'active_gap': active_gap if active_gap is not None else 'N/A',
                'achievement_status': status_str,
            })
        return rows

    def action_export_csv(self):
        """Action: Export report dataset as CSV file matching selected report_type."""
        self.ensure_one()
        output = io.StringIO()

        writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        if self.report_type == 'detailed_matrix':
            rows = self._get_360_report_data_rows()
            rating_filter = self.assessment_type_filter or 'all'
            if rating_filter != 'all':
                label_map = {
                    'self': ('Self Rating', 'Self Rating Gap'),
                    'peer': ('Peer Avg Rating', 'Peer Rating Gap'),
                    'subordinate': ('Subordinate Avg Rating', 'Subordinate Rating Gap'),
                    'supervisor': ('Supervisor Rating', 'Supervisor Rating Gap'),
                }
                r_lbl, g_lbl = label_map.get(rating_filter, ('Current Rating', 'Gap'))
                headers = [
                    'Cycle', 'Employee ID', 'Employee Name', 'Gender', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                    'Competency Name', 'Pillar', 'Functional Domain',
                    r_lbl, 'Required Level', g_lbl, 'Qualification Status'
                ]
                writer.writerow(headers)
                for r in rows:
                    writer.writerow([
                        r['cycle_name'], r['emp_id_code'], r['emp_name'], r['gender'], r['operating_unit_name'], r['department_name'], r['job_name'], r['grade_name'],
                        r['competency_name'], r['pillar_name'], r['domain_name'],
                        r['active_rating'], r['required_level'], r['active_gap'], r['achievement_status']
                    ])
            else:
                headers = [
                    'Cycle', 'Employee ID', 'Employee Name', 'Gender', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                    'Competency Name', 'Pillar', 'Functional Domain',
                    'Self Rating', 'Peer Avg', 'Subordinate Avg', 'Supervisor Avg',
                    'Self Gap', 'Peer Gap', 'Subordinate Gap', 'Supervisor Gap',
                    'Weighted Current Rating', 'Required Level', 'Weighted Gap', 'Qualification Status'
                ]
                writer.writerow(headers)
                for r in rows:
                    row_vals = [
                        r['cycle_name'], r['emp_id_code'], r['emp_name'], r['gender'], r['operating_unit_name'], r['department_name'], r['job_name'], r['grade_name'],
                        r['competency_name'], r['pillar_name'], r['domain_name'],
                        r['self_rating'], r['peer_avg'], r['subordinate_avg'], r['supervisor_avg'],
                        r['self_gap'], r['peer_gap'], r['subordinate_gap'], r['supervisor_gap'],
                        r['weighted_rating'], r['required_level'], r['weighted_gap'], r['achievement_status']
                    ]
                    writer.writerow(row_vals)

        elif self.report_type == 'dept_role_gap':
            rows = self._get_360_report_data_rows()
            grouped = {}
            for r in rows:
                key = (r['department_name'], r['job_name'])
                grouped.setdefault(key, []).append(r)

            writer.writerow([
                'Cycle', 'Department', 'Job Position', 'Total Evaluated Lines',
                'Fit / Qualified Count', 'Underqualified Count', 'Overqualified Count', 'Average Gap'
            ])
            for (dept, job), items in sorted(grouped.items()):
                meets = sum(1 for x in items if x['achievement_status'] == 'Fit / Qualified')
                below = sum(1 for x in items if x['achievement_status'] == 'Underqualified')
                exceeds = sum(1 for x in items if x['achievement_status'] == 'Overqualified')
                gaps = [x['active_gap'] for x in items if isinstance(x['active_gap'], (int, float))]
                avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0
                writer.writerow([
                    self.cycle_id.name, dept, job, len(items),
                    meets, below, exceeds, avg_gap
                ])

        elif self.report_type == 'individual':
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            if self.operating_unit_ids:
                asm_domain.extend(['|', ('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids), ('employee_id.operating_unit_id', 'in', self.operating_unit_ids.ids)])
            if self.job_ids:
                asm_domain.append(('job_id', 'in', self.job_ids.ids))
            if self.employee_ids:
                asm_domain.append(('employee_id', 'in', self.employee_ids.ids))
            if self.stage_filter and self.stage_filter != 'all':
                asm_domain.append(('state', '=', self.stage_filter))

            asms = self.env['competency.assessment'].sudo().search(asm_domain)
            writer.writerow([
                'Cycle', 'Assessment Ref', 'Staff ID', 'Employee Name', 'Department', 'Operating Unit',
                'Job Position', 'Total Competencies', 'Gap Count', 'Average Gap', 'Overall Score', 'Status'
            ])
            for a in asms:
                emp_ou = getattr(a.employee_id, 'default_operating_unit_id', False) or getattr(a.employee_id, 'operating_unit_id', False) or getattr(a.department_id, 'operating_unit_id', False)
                ou_name = emp_ou.name if emp_ou else 'N/A'
                tot_comps = len(a.line_ids)
                gap_cnt = len(a.line_ids.filtered(lambda l: l.gap and l.gap > 0))
                overall_score = round(sum([float(l.weighted_current_level or l.current_level or 0) for l in a.line_ids]) / tot_comps, 2) if tot_comps else 0.0
                emp_code = getattr(a.employee_id, 'staff_id', False) or getattr(a.employee_id, 'employee_code', False) or getattr(a.employee_id, 'identification_id', False) or str(a.employee_id.id)
                writer.writerow([
                    self.cycle_id.name, a.name, emp_code, a.employee_id.name,
                    a.department_id.name if a.department_id else 'N/A',
                    ou_name, a.job_id.name if a.job_id else 'N/A',
                    tot_comps, gap_cnt, round(a.average_gap or 0.0, 2),
                    overall_score, dict(a._fields['state'].selection).get(a.state, a.state)
                ])

        elif self.report_type == 'campaign_progress':
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            asms = self.env['competency.assessment'].sudo().search(asm_domain)
            dept_map = {}
            for a in asms:
                dept_name = a.department_id.name if a.department_id else 'Unassigned'
                dept_map.setdefault(dept_name, []).append(a)

            writer.writerow([
                'Cycle', 'Department', 'Total Assessments', 'Draft', 'Submitted',
                'Supervisor Review', 'HR Verified', 'Approved', 'Locked', 'Completion Rate %'
            ])
            for d_name, items in sorted(dept_map.items()):
                draft_cnt = sum(1 for x in items if x.state == 'draft')
                sub_cnt = sum(1 for x in items if x.state == 'submitted')
                sup_cnt = sum(1 for x in items if x.state == 'supervisor_review')
                hr_cnt = sum(1 for x in items if x.state == 'hr_verified')
                app_cnt = sum(1 for x in items if x.state == 'approved')
                lock_cnt = sum(1 for x in items if x.state == 'locked')
                done_cnt = app_cnt + lock_cnt
                rate = round((done_cnt / len(items)) * 100, 1) if items else 0.0
                writer.writerow([
                    self.cycle_id.name, d_name, len(items), draft_cnt, sub_cnt,
                    sup_cnt, hr_cnt, app_cnt, lock_cnt, f"{rate}%"
                ])

        csv_bytes = output.getvalue().encode('utf-8-sig')
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'Competency_{self.report_type}_{self.cycle_id.name}.csv',
            'datas': base64.b64encode(csv_bytes),
            'mimetype': 'text/csv',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _aggregate_cycle_lines(self, lines, cycle):
        """Aggregate evaluation lines for a specific cycle into structured per-competency records."""
        config = self.env['competency.matrix.config'].sudo().get_active_config()
        config_data = config.read(['weight_self', 'weight_peer', 'weight_subordinate', 'weight_supervisor']) if config else []
        if config_data:
            c_dict = config_data[0]
            w_self = float(c_dict.get('weight_self') or 2.0)
            w_peer = float(c_dict.get('weight_peer') or 1.0)
            w_sub = float(c_dict.get('weight_subordinate') or 1.0)
            w_sup = float(c_dict.get('weight_supervisor') or 3.0)
        else:
            w_self, w_peer, w_sub, w_sup = 2.0, 1.0, 1.0, 3.0

        grouped = {}
        for l in lines:
            key = (l.employee_id.id, l.competency_id.id)
            grouped.setdefault(key, []).append(l)

        res = {}
        for (emp_id, comp_id), comp_lines in grouped.items():
            emp = self.env['hr.employee'].sudo().browse(emp_id)
            comp = self.env['competency.competency'].sudo().browse(comp_id)

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self' and l.current_level]
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer' and l.current_level]
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate' and l.current_level]
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type in ('supervisor', 'team') and l.current_level]

            self_val = int(self_lines[0].current_level) if self_lines else None
            peer_avg = round(sum(int(l.current_level) for l in peer_lines) / len(peer_lines), 2) if peer_lines else None
            sub_avg = round(sum(int(l.current_level) for l in sub_lines) / len(sub_lines), 2) if sub_lines else None
            sup_avg = int(sup_lines[0].current_level) if (len(sup_lines) == 1 and str(sup_lines[0].current_level).isdigit()) else (round(sum(int(l.current_level) for l in sup_lines) / len(sup_lines), 2) if sup_lines else None)

            weighted_num = 0.0
            weighted_den = 0.0
            if self_val is not None:
                weighted_num += self_val * w_self
                weighted_den += w_self
            if peer_avg is not None:
                weighted_num += peer_avg * w_peer
                weighted_den += w_peer
            if sub_avg is not None:
                weighted_num += sub_avg * w_sub
                weighted_den += w_sub
            if sup_avg is not None:
                weighted_num += sup_avg * w_sup
                weighted_den += w_sup

            final_rating = round(weighted_num / weighted_den, 2) if weighted_den > 0 else (self_val or 0.0)

            emp_job = getattr(emp, 'job_position', False) or emp.job_id
            role_map = self.env['competency.role.mapping'].sudo().search([
                ('job_position_id', '=', emp_job.id if emp_job else 0),
                ('state', '=', 'approved')
            ], limit=1)
            req_val = None
            if role_map:
                map_line = role_map.line_ids.filtered(lambda l: l.competency_id.id == comp.id)
                if map_line and map_line[0].required_proficiency:
                    try:
                        req_val = int(map_line[0].required_proficiency)
                    except (ValueError, TypeError):
                        req_val = None
            if req_val is None:
                req_str = comp_lines[0].required_level or '1'
                req_val = int(req_str) if str(req_str).isdigit() else 1

            self_gap = round(req_val - self_val, 2) if self_val is not None else None
            peer_gap = round(req_val - peer_avg, 2) if peer_avg is not None else None
            sub_gap = round(req_val - sub_avg, 2) if sub_avg is not None else None
            sup_gap = round(req_val - sup_avg, 2) if sup_avg is not None else None
            weighted_gap = round(req_val - final_rating, 2)

            ou_obj = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
            grade_obj = getattr(emp, 'grade_id', False)

            res[(emp_id, comp_id)] = {
                'emp_id': emp.id,
                'emp_name': emp.name,
                'emp_id_code': getattr(emp, 'identification_id', '') or getattr(emp, 'barcode', '') or str(emp.id),
                'dept_name': emp.department_id.name if emp.department_id else 'N/A',
                'ou_name': ou_obj.name if ou_obj else 'N/A',
                'job_name': emp_job.name if emp_job else 'N/A',
                'grade_name': (getattr(grade_obj, 'grade_name', False) or getattr(grade_obj, 'name', False) or 'N/A') if grade_obj else 'N/A',
                'comp_name': comp.name,
                'pillar_name': dict(comp._fields['pillar'].selection).get(comp.pillar, comp.pillar),
                'domain_name': comp.functional_domain or 'General',
                'req_val': req_val,
                'self_val': self_val,
                'self_gap': self_gap,
                'peer_avg': peer_avg,
                'peer_gap': peer_gap,
                'sub_avg': sub_avg,
                'sub_gap': sub_gap,
                'sup_avg': sup_avg,
                'sup_gap': sup_gap,
                'weighted_rating': final_rating,
                'weighted_gap': weighted_gap,
            }
        return res

    @api.model
    def get_bunna_logo_base64(self):
        """Returns base64 string of official Bunna Bank logo for QWeb PDF reports."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            alt_path = '/mnt/extra-addons/custom_recruitment/static/src/img/bunna_bank_official_logo.png'
            if os.path.exists(alt_path):
                logo_path = alt_path
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def _setup_worksheet_header(self, worksheet, workbook, title):
        """Inserts Bunna Bank logo and corporate branding header onto an xlsx worksheet."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            alt_path = '/mnt/extra-addons/custom_recruitment/static/src/img/bunna_bank_official_logo.png'
            if os.path.exists(alt_path):
                logo_path = alt_path

        if os.path.exists(logo_path):
            worksheet.insert_image('A1', logo_path, {'x_scale': 0.28, 'y_scale': 0.28, 'x_offset': 8, 'y_offset': 6})

        title_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 13,
            'font_color': '#541718', 'valign': 'vcenter'
        })
        sub_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#726732', 'valign': 'vcenter'
        })
        meta_fmt = workbook.add_format({
            'italic': True, 'font_name': 'Arial', 'font_size': 9,
            'font_color': '#475569', 'valign': 'vcenter'
        })

        worksheet.set_row(0, 20)
        worksheet.set_row(1, 18)
        worksheet.set_row(2, 16)
        worksheet.set_row(3, 10)

        worksheet.write('D1', 'BUNNA BANK S.C.', title_fmt)
        worksheet.write('D2', title or 'Competency Capability & Gap Report', sub_fmt)

        cycle_name = self.cycle_id.name if self.cycle_id else 'All Cycles'
        focus_label = dict(self._fields['assessment_type_filter'].selection).get(self.assessment_type_filter, 'All 360° Ratings')
        now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M')
        meta_text = f"Campaign: {cycle_name}   |   Focus: {focus_label}   |   Exported: {now_str}"
        worksheet.write('D3', meta_text, meta_fmt)

        worksheet.set_header('&L&G&C&12&"Arial,Bold"BUNNA BANK S.C.&R&D')
        worksheet.set_footer('&LConfidential - Internal Banking Assessment&RPage &P of &N')
        worksheet.repeat_rows(4)

        return 4

    def _export_two_cycle_comparison_xlsx(self, workbook, header_format, cell_format, num_format):
        if not self.comparison_cycle_id:
            raise UserError(_("Please select a Comparison Cycle (Previous) to generate the Two-Cycle Comparison Report."))

        worksheet = workbook.add_worksheet('Two-Cycle Comparison')
        start_row = self._setup_worksheet_header(worksheet, workbook, 'Two-Cycle Competency Progression & Gap Improvement')
        worksheet.freeze_panes(start_row + 2, 4)

        group_header_format = workbook.add_format({
            'bold': True, 'bg_color': '#2C3E50', 'font_color': '#FFFFFF',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        delta_pos_format = workbook.add_format({
            'border': 1, 'valign': 'vcenter', 'num_format': '+0.00;-0.00;0.00',
            'bg_color': '#D4EDDA', 'font_color': '#155724', 'bold': True
        })
        delta_neg_format = workbook.add_format({
            'border': 1, 'valign': 'vcenter', 'num_format': '+0.00;-0.00;0.00',
            'bg_color': '#F8D7DA', 'font_color': '#721C24', 'bold': True
        })
        delta_neutral_format = workbook.add_format({
            'border': 1, 'valign': 'vcenter', 'num_format': '+0.00;-0.00;0.00'
        })

        curr_lines = self.env['competency.assessment.line'].sudo().search(self._build_line_domain(cycle=self.cycle_id))
        prev_lines = self.env['competency.assessment.line'].sudo().search(self._build_line_domain(cycle=self.comparison_cycle_id))

        curr_data = self._aggregate_cycle_lines(curr_lines, self.cycle_id)
        prev_data = self._aggregate_cycle_lines(prev_lines, self.comparison_cycle_id)

        all_keys = sorted(set(curr_data.keys()) | set(prev_data.keys()))

        worksheet.merge_range(start_row, 0, start_row, 5, "Employee Information", group_header_format)
        worksheet.merge_range(start_row, 6, start_row, 8, "Competency Master", group_header_format)
        worksheet.merge_range(start_row, 9, start_row, 15, f"Previous Cycle ({self.comparison_cycle_id.name})", group_header_format)
        worksheet.merge_range(start_row, 16, start_row, 22, f"Current Cycle ({self.cycle_id.name})", header_format)
        worksheet.merge_range(start_row, 23, start_row, 27, "Growth & Delta Analysis (Δ)", group_header_format)

        headers = [
            'Emp ID', 'Employee Name', 'Department', 'Operating Unit', 'Job Position', 'Grade',
            'Competency', 'Pillar', 'Domain',
            'Prev Req Level', 'Prev Self Rating', 'Prev Self Gap', 'Prev Peer Avg', 'Prev Sup Rating', 'Prev Weighted Level', 'Prev Weighted Gap',
            'Curr Req Level', 'Curr Self Rating', 'Curr Self Gap', 'Curr Peer Avg', 'Curr Sup Rating', 'Curr Weighted Level', 'Curr Weighted Gap',
            'Self Rating Δ', 'Peer Rating Δ', 'Supervisor Rating Δ', 'Weighted Level Δ', 'Gap Improvement (Δ)'
        ]
        for col_num, h in enumerate(headers):
            worksheet.write(start_row + 1, col_num, h, header_format)
            worksheet.set_column(col_num, col_num, 16)

        row_num = start_row + 2
        for key in all_keys:
            c = curr_data.get(key, {})
            p = prev_data.get(key, {})
            base = c or p

            worksheet.write(row_num, 0, base.get('emp_id', ''), cell_format)
            worksheet.write(row_num, 1, base.get('emp_name', ''), cell_format)
            worksheet.write(row_num, 2, base.get('dept_name', ''), cell_format)
            worksheet.write(row_num, 3, base.get('ou_name', ''), cell_format)
            worksheet.write(row_num, 4, base.get('job_name', ''), cell_format)
            worksheet.write(row_num, 5, base.get('grade_name', ''), cell_format)
            worksheet.write(row_num, 6, base.get('comp_name', ''), cell_format)
            worksheet.write(row_num, 7, base.get('pillar_name', ''), cell_format)
            worksheet.write(row_num, 8, base.get('domain_name', ''), cell_format)

            # Prev Cycle
            worksheet.write(row_num, 9, p.get('req_val', 'N/A'), cell_format)
            worksheet.write(row_num, 10, p.get('self_val', 'N/A'), num_format if isinstance(p.get('self_val'), (int, float)) else cell_format)
            worksheet.write(row_num, 11, p.get('self_gap', 'N/A'), num_format if isinstance(p.get('self_gap'), (int, float)) else cell_format)
            worksheet.write(row_num, 12, p.get('peer_avg', 'N/A'), num_format if isinstance(p.get('peer_avg'), (int, float)) else cell_format)
            worksheet.write(row_num, 13, p.get('sup_avg', 'N/A'), num_format if isinstance(p.get('sup_avg'), (int, float)) else cell_format)
            worksheet.write(row_num, 14, p.get('weighted_rating', 'N/A'), num_format if isinstance(p.get('weighted_rating'), (int, float)) else cell_format)
            worksheet.write(row_num, 15, p.get('weighted_gap', 'N/A'), num_format if isinstance(p.get('weighted_gap'), (int, float)) else cell_format)

            # Curr Cycle
            worksheet.write(row_num, 16, c.get('req_val', 'N/A'), cell_format)
            worksheet.write(row_num, 17, c.get('self_val', 'N/A'), num_format if isinstance(c.get('self_val'), (int, float)) else cell_format)
            worksheet.write(row_num, 18, c.get('self_gap', 'N/A'), num_format if isinstance(c.get('self_gap'), (int, float)) else cell_format)
            worksheet.write(row_num, 19, c.get('peer_avg', 'N/A'), num_format if isinstance(c.get('peer_avg'), (int, float)) else cell_format)
            worksheet.write(row_num, 20, c.get('sup_avg', 'N/A'), num_format if isinstance(c.get('sup_avg'), (int, float)) else cell_format)
            worksheet.write(row_num, 21, c.get('weighted_rating', 'N/A'), num_format if isinstance(c.get('weighted_rating'), (int, float)) else cell_format)
            worksheet.write(row_num, 22, c.get('weighted_gap', 'N/A'), num_format if isinstance(c.get('weighted_gap'), (int, float)) else cell_format)

            # Deltas
            self_d = (c['self_val'] - p['self_val']) if (isinstance(c.get('self_val'), (int, float)) and isinstance(p.get('self_val'), (int, float))) else 'N/A'
            peer_d = (c['peer_avg'] - p['peer_avg']) if (isinstance(c.get('peer_avg'), (int, float)) and isinstance(p.get('peer_avg'), (int, float))) else 'N/A'
            sup_d = (c['sup_avg'] - p['sup_avg']) if (isinstance(c.get('sup_avg'), (int, float)) and isinstance(p.get('sup_avg'), (int, float))) else 'N/A'
            w_d = (c['weighted_rating'] - p['weighted_rating']) if (isinstance(c.get('weighted_rating'), (int, float)) and isinstance(p.get('weighted_rating'), (int, float))) else 'N/A'
            gap_impr = (p['weighted_gap'] - c['weighted_gap']) if (isinstance(p.get('weighted_gap'), (int, float)) and isinstance(c.get('weighted_gap'), (int, float))) else 'N/A'

            worksheet.write(row_num, 23, self_d, num_format if isinstance(self_d, (int, float)) else cell_format)
            worksheet.write(row_num, 24, peer_d, num_format if isinstance(peer_d, (int, float)) else cell_format)
            worksheet.write(row_num, 25, sup_d, num_format if isinstance(sup_d, (int, float)) else cell_format)
            worksheet.write(row_num, 26, w_d, num_format if isinstance(w_d, (int, float)) else cell_format)

            if isinstance(gap_impr, (int, float)):
                fmt = delta_pos_format if gap_impr > 0 else (delta_neg_format if gap_impr < 0 else delta_neutral_format)
                worksheet.write(row_num, 27, gap_impr, fmt)
            else:
                worksheet.write(row_num, 27, 'N/A', cell_format)

            row_num += 1

    def action_export_xlsx(self):
        """Action: Export report dataset as Excel (.xlsx) file matching selected report_type."""
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#541718',
            'font_color': '#FFFFFF',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        cell_format = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        num_format = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '0.00'})

        if self.report_type == 'detailed_matrix':
            worksheet = workbook.add_worksheet('Detailed Matrix')
            start_row = self._setup_worksheet_header(worksheet, workbook, 'Detailed Competency Performance & Gap Matrix Report')
            rows = self._get_360_report_data_rows()
            rating_filter = self.assessment_type_filter or 'all'

            if rating_filter != 'all':
                label_map = {
                    'self': ('Self Rating', 'Self Rating Gap'),
                    'peer': ('Peer Avg Rating', 'Peer Rating Gap'),
                    'subordinate': ('Subordinate Avg Rating', 'Subordinate Rating Gap'),
                    'supervisor': ('Supervisor Rating', 'Supervisor Rating Gap'),
                }
                r_lbl, g_lbl = label_map.get(rating_filter, ('Current Rating', 'Gap'))
                headers = [
                    'Cycle', 'Employee ID', 'Employee Name', 'Gender', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                    'Competency Name', 'Pillar', 'Functional Domain',
                    r_lbl, 'Required Level', g_lbl, 'Qualification Status'
                ]
                for col_num, header in enumerate(headers):
                    worksheet.write(start_row, col_num, header, header_format)
                    worksheet.set_column(col_num, col_num, 18)

                for row_num, r in enumerate(rows, start=start_row + 1):
                    worksheet.write(row_num, 0, r['cycle_name'], cell_format)
                    worksheet.write(row_num, 1, r['emp_id_code'], cell_format)
                    worksheet.write(row_num, 2, r['emp_name'], cell_format)
                    worksheet.write(row_num, 3, r['gender'], cell_format)
                    worksheet.write(row_num, 4, r['operating_unit_name'], cell_format)
                    worksheet.write(row_num, 5, r['department_name'], cell_format)
                    worksheet.write(row_num, 6, r['job_name'], cell_format)
                    worksheet.write(row_num, 7, r['grade_name'], cell_format)
                    worksheet.write(row_num, 8, r['competency_name'], cell_format)
                    worksheet.write(row_num, 9, r['pillar_name'], cell_format)
                    worksheet.write(row_num, 10, r['domain_name'], cell_format)
                    worksheet.write(row_num, 11, r['active_rating'], num_format if isinstance(r['active_rating'], (int, float)) else cell_format)
                    worksheet.write(row_num, 12, r['required_level'], cell_format)
                    worksheet.write(row_num, 13, r['active_gap'], num_format if isinstance(r['active_gap'], (int, float)) else cell_format)
                    worksheet.write(row_num, 14, r['achievement_status'], cell_format)
            else:
                headers = [
                    'Cycle', 'Employee ID', 'Employee Name', 'Gender', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                    'Competency Name', 'Pillar', 'Functional Domain',
                    'Self Rating', 'Peer Avg', 'Subordinate Avg', 'Supervisor Avg',
                    'Self Gap', 'Peer Gap', 'Subordinate Gap', 'Supervisor Gap',
                    'Weighted Current Rating', 'Required Level', 'Weighted Gap', 'Qualification Status'
                ]

                for col_num, header in enumerate(headers):
                    worksheet.write(start_row, col_num, header, header_format)
                    worksheet.set_column(col_num, col_num, 18)

                for row_num, r in enumerate(rows, start=start_row + 1):
                    col_idx = 0
                    for val in [r['cycle_name'], r['emp_id_code'], r['emp_name'], r['gender'], r['operating_unit_name'], r['department_name'], r['job_name'], r['grade_name'], r['competency_name'], r['pillar_name'], r['domain_name']]:
                        worksheet.write(row_num, col_idx, val, cell_format)
                        col_idx += 1
                    for rating_val in [r['self_rating'], r['peer_avg'], r['subordinate_avg'], r['supervisor_avg']]:
                        worksheet.write(row_num, col_idx, rating_val, num_format if isinstance(rating_val, (int, float)) else cell_format)
                        col_idx += 1
                    for gap_val in [r['self_gap'], r['peer_gap'], r['subordinate_gap'], r['supervisor_gap']]:
                        worksheet.write(row_num, col_idx, gap_val, num_format if isinstance(gap_val, (int, float)) else cell_format)
                        col_idx += 1
                    worksheet.write(row_num, col_idx, r['weighted_rating'], num_format)
                    col_idx += 1
                    worksheet.write(row_num, col_idx, r['required_level'], cell_format)
                    col_idx += 1
                    worksheet.write(row_num, col_idx, r['weighted_gap'], num_format)
                    col_idx += 1
                    worksheet.write(row_num, col_idx, r['achievement_status'], cell_format)

        elif self.report_type == 'two_cycle_comparison':
            self._export_two_cycle_comparison_xlsx(workbook, header_format, cell_format, num_format)

        elif self.report_type == 'dept_role_gap':
            worksheet = workbook.add_worksheet('Dept & Role Gap')
            start_row = self._setup_worksheet_header(worksheet, workbook, 'Department & Role Competency Gap Summary Report')
            rows = self._get_360_report_data_rows()
            grouped = {}
            for r in rows:
                key = (r['department_name'], r['job_name'])
                grouped.setdefault(key, []).append(r)

            headers = [
                'Cycle', 'Department', 'Job Position', 'Total Evaluated Lines',
                'Fit / Qualified Count', 'Underqualified Count', 'Overqualified Count', 'Average Gap'
            ]
            for col_num, header in enumerate(headers):
                worksheet.write(start_row, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 20)

            for row_num, ((dept, job), items) in enumerate(sorted(grouped.items()), start=start_row + 1):
                meets = sum(1 for x in items if x['achievement_status'] == 'Fit / Qualified')
                below = sum(1 for x in items if x['achievement_status'] == 'Underqualified')
                exceeds = sum(1 for x in items if x['achievement_status'] == 'Overqualified')
                gaps = [x['active_gap'] for x in items if isinstance(x['active_gap'], (int, float))]
                avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0
                worksheet.write(row_num, 0, self.cycle_id.name, cell_format)
                worksheet.write(row_num, 1, dept, cell_format)
                worksheet.write(row_num, 2, job, cell_format)
                worksheet.write(row_num, 3, len(items), cell_format)
                worksheet.write(row_num, 4, meets, cell_format)
                worksheet.write(row_num, 5, below, cell_format)
                worksheet.write(row_num, 6, exceeds, cell_format)
                worksheet.write(row_num, 7, avg_gap, num_format)

        elif self.report_type == 'individual':
            worksheet = workbook.add_worksheet('Employee Profiles')
            start_row = self._setup_worksheet_header(worksheet, workbook, 'Employee Competency Assessment Profile Roster')
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            if self.operating_unit_ids:
                asm_domain.extend(['|', ('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids), ('employee_id.operating_unit_id', 'in', self.operating_unit_ids.ids)])
            if self.job_ids:
                asm_domain.append(('job_id', 'in', self.job_ids.ids))
            if self.employee_ids:
                asm_domain.append(('employee_id', 'in', self.employee_ids.ids))
            if self.stage_filter and self.stage_filter != 'all':
                asm_domain.append(('state', '=', self.stage_filter))

            asms = self.env['competency.assessment'].sudo().search(asm_domain)
            headers = [
                'Cycle', 'Assessment Ref', 'Staff ID', 'Employee Name', 'Department', 'Operating Unit',
                'Job Position', 'Total Competencies', 'Gap Count', 'Average Gap', 'Overall Score', 'Status'
            ]
            for col_num, header in enumerate(headers):
                worksheet.write(start_row, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 18)

            for row_num, a in enumerate(asms, start=start_row + 1):
                emp_ou = getattr(a.employee_id, 'default_operating_unit_id', False) or getattr(a.employee_id, 'operating_unit_id', False) or getattr(a.department_id, 'operating_unit_id', False)
                ou_name = emp_ou.name if emp_ou else 'N/A'
                tot_comps = len(a.line_ids)
                gap_cnt = len(a.line_ids.filtered(lambda l: l.gap and l.gap > 0))
                overall_score = round(sum([float(l.weighted_current_level or l.current_level or 0) for l in a.line_ids]) / tot_comps, 2) if tot_comps else 0.0
                worksheet.write(row_num, 0, self.cycle_id.name, cell_format)
                worksheet.write(row_num, 1, a.name, cell_format)
                worksheet.write(row_num, 2, a.employee_id.id, cell_format)
                worksheet.write(row_num, 3, a.employee_id.name, cell_format)
                worksheet.write(row_num, 4, a.department_id.name if a.department_id else 'N/A', cell_format)
                worksheet.write(row_num, 5, ou_name, cell_format)
                worksheet.write(row_num, 6, a.job_id.name if a.job_id else 'N/A', cell_format)
                worksheet.write(row_num, 7, tot_comps, cell_format)
                worksheet.write(row_num, 8, gap_cnt, cell_format)
                worksheet.write(row_num, 9, round(a.average_gap or 0.0, 2), num_format)
                worksheet.write(row_num, 10, overall_score, num_format)
                worksheet.write(row_num, 11, dict(a._fields['state'].selection).get(a.state, a.state), cell_format)

        elif self.report_type == 'campaign_progress':
            worksheet = workbook.add_worksheet('Campaign Progress')
            start_row = self._setup_worksheet_header(worksheet, workbook, 'Assessment Campaign Progress Tracking Report')
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            asms = self.env['competency.assessment'].sudo().search(asm_domain)
            dept_map = {}
            for a in asms:
                dept_name = a.department_id.name if a.department_id else 'Unassigned'
                dept_map.setdefault(dept_name, []).append(a)

            headers = [
                'Cycle', 'Department', 'Total Assessments', 'Draft', 'Submitted',
                'Supervisor Review', 'HR Verified', 'Approved', 'Locked', 'Completion Rate %'
            ]
            for col_num, header in enumerate(headers):
                worksheet.write(start_row, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 18)

            for row_num, (d_name, items) in enumerate(sorted(dept_map.items()), start=start_row + 1):
                draft_cnt = sum(1 for x in items if x.state == 'draft')
                sub_cnt = sum(1 for x in items if x.state == 'submitted')
                sup_cnt = sum(1 for x in items if x.state == 'supervisor_review')
                hr_cnt = sum(1 for x in items if x.state == 'hr_verified')
                app_cnt = sum(1 for x in items if x.state == 'approved')
                lock_cnt = sum(1 for x in items if x.state == 'locked')
                done_cnt = app_cnt + lock_cnt
                rate = round((done_cnt / len(items)) * 100, 1) if items else 0.0
                worksheet.write(row_num, 0, self.cycle_id.name, cell_format)
                worksheet.write(row_num, 1, d_name, cell_format)
                worksheet.write(row_num, 2, len(items), cell_format)
                worksheet.write(row_num, 3, draft_cnt, cell_format)
                worksheet.write(row_num, 4, sub_cnt, cell_format)
                worksheet.write(row_num, 5, sup_cnt, cell_format)
                worksheet.write(row_num, 6, hr_cnt, cell_format)
                worksheet.write(row_num, 7, app_cnt, cell_format)
                worksheet.write(row_num, 8, lock_cnt, cell_format)
                worksheet.write(row_num, 9, f"{rate}%", cell_format)

        workbook.close()
        xlsx_bytes = output.getvalue()
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'Competency_{self.report_type}_{self.cycle_id.name}.xlsx',
            'datas': base64.b64encode(xlsx_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_print_pdf(self):
        """Action: Print QWeb PDF report."""
        self.ensure_one()
        if self.report_type == 'individual':
            asm_domain = [('cycle_id', '=', self.cycle_id.id)]
            if self.employee_ids:
                asm_domain.append(('employee_id', 'in', self.employee_ids.ids))
            elif self.department_ids:
                asm_domain.append(('department_id', 'in', self.department_ids.ids))
            elif self.operating_unit_ids:
                asm_domain.extend(['|', ('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids), ('employee_id.operating_unit_id', 'in', self.operating_unit_ids.ids)])
            else:
                emp = self.env.user.employee_id
                if emp:
                    asm_domain.append(('employee_id', '=', emp.id))

            asms = self.env['competency.assessment'].sudo().search(asm_domain, limit=30)
            if not asms:
                raise UserError(_("No assessment found matching the selected filters for cycle %s.") % self.cycle_id.name)
            return self.env.ref('competency_management.action_report_competency_assessment_individual').report_action(asms)
        elif self.report_type == 'dept_role_gap':
            return self.env.ref('competency_management.action_report_competency_team_gap').report_action(self)
        elif self.report_type == 'detailed_matrix':
            return self.env.ref('competency_management.action_report_competency_detailed_matrix').report_action(self)
        elif self.report_type == 'campaign_progress':
            return self.env.ref('competency_management.action_report_competency_campaign_progress').report_action(self)
        else:
            return self.env.ref('competency_management.action_report_competency_org_capability').report_action(self)

    def get_team_gap_data(self):
        """Computes aggregate analytics data for Tier 2 Supervisor QWeb report."""
        self.ensure_one()
        rows = self._get_360_report_data_rows()

        emp_groups = {}
        for r in rows:
            emp_groups.setdefault(r['emp_name'], []).append(r)

        total_members = len(emp_groups)
        assessed_members = sum(1 for e, items in emp_groups.items() if any(x['active_rating'] not in ('N/A', None, 0, 0.0) for x in items))
        completion_rate = round((assessed_members / total_members * 100), 1) if total_members else 0.0

        below_count = sum(1 for r in rows if r['achievement_status'] == 'Underqualified')
        numeric_gaps = [r['active_gap'] for r in rows if isinstance(r.get('active_gap'), (int, float))]
        avg_gap = round(sum(numeric_gaps) / len(numeric_gaps), 2) if numeric_gaps else 0.0

        member_roster = []
        for emp_name, items in sorted(emp_groups.items()):
            job = items[0]['job_name'] if items else 'N/A'
            under = sum(1 for x in items if x['achievement_status'] == 'Underqualified')
            has_rating = any(x['active_rating'] not in ('N/A', None, 0, 0.0) for x in items)

            if under > 0:
                overall = 'Needs Intervention'
            elif has_rating:
                overall = 'Fit / Qualified'
            else:
                overall = 'Pending'

            top_gap_items = [x['competency_name'] for x in items if x['achievement_status'] == 'Underqualified']
            top_gaps_str = ', '.join(top_gap_items[:3]) if top_gap_items else 'None (Fully Qualified)'

            member_roster.append({
                'name': emp_name,
                'job': job,
                'status': 'Assessed' if has_rating else 'Pending',
                'overall_status': overall,
                'top_gaps': top_gaps_str,
            })

        user_emp = self.env.user.employee_id
        return {
            'supervisor_name': user_emp.name if user_emp else self.env.user.name,
            'total_members': total_members,
            'assessed_members': assessed_members,
            'completion_rate': completion_rate,
            'below_count': below_count,
            'avg_gap': avg_gap,
            'member_roster': member_roster,
        }

    def get_org_capability_data(self):
        """Computes aggregate analytics data for Tier 3 Admin QWeb report."""
        self.ensure_one()
        cycle = self.cycle_id
        dept_domain = [('id', 'in', self.department_ids.ids)] if self.department_ids else []
        departments = self.env['hr.department'].search(dept_domain, limit=15)
        
        active_comps = self.env['competency.competency'].search([('status', '=', 'active')])
        core_cnt = len(active_comps.filtered(lambda c: c.pillar == 'core'))
        lead_cnt = len(active_comps.filtered(lambda c: c.pillar == 'leadership'))
        tech_cnt = len(active_comps.filtered(lambda c: c.pillar == 'technical'))
        
        total_jobs = self.env['hr.job'].search_count([])
        mapped_job_ids = self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id')
        mapped_count = len(set(mapped_job_ids))
        coverage_pct = round((mapped_count / total_jobs * 100), 1) if total_jobs else 0.0
        
        line_domain = self._build_line_domain()
        lines = self.env['competency.assessment.line'].search(line_domain)
        high_gap_lines = lines.filtered(lambda l: l.gap_priority == 'high')
        
        comp_gap_counts = {}
        for l in high_gap_lines:
            cname = l.competency_id.name
            comp_gap_counts[cname] = comp_gap_counts.get(cname, 0) + 1
            
        top_gaps = sorted(comp_gap_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        dept_completion = []
        for dept in departments:
            dept_asms = self.env['competency.assessment'].search([('cycle_id', '=', cycle.id), ('department_id', '=', dept.id)])
            total_d = len(dept_asms)
            approved_d = len(dept_asms.filtered(lambda a: a.state in ('approved', 'locked')))
            pct_d = round((approved_d / total_d * 100), 1) if total_d else 0.0
            dept_completion.append({
                'name': dept.name,
                'total': total_d,
                'approved': approved_d,
                'rate': pct_d
            })
            
        return {
            'core_cnt': core_cnt,
            'lead_cnt': lead_cnt,
            'tech_cnt': tech_cnt,
            'total_jobs': total_jobs,
            'mapped_count': mapped_count,
            'coverage_pct': coverage_pct,
            'top_gaps': top_gaps,
            'dept_completion': dept_completion,
            '360_rows': self._get_360_report_data_rows()[:20],
        }


class CompetencyRaterBreakdownWizard(models.TransientModel):
    """Pop-up modal wizard to display full multi-rater 360 breakdown for a competency reporting line."""
    _name = 'competency.rater.breakdown.wizard'
    _description = '360° Rater Score Breakdown & Audit Wizard'

    line_id = fields.Many2one('competency.assessment.line', string='Reporting Line', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Evaluatee Employee', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', readonly=True)
    cycle_id = fields.Many2one('competency.assessment.cycle', string='Assessment Cycle', readonly=True)
    competency_id = fields.Many2one('competency.competency', string='Competency', readonly=True)
    functional_domain = fields.Char(related='competency_id.functional_domain', string='Functional Domain', readonly=True)
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', readonly=True)
    competency_definition = fields.Text(related='competency_id.definition', string='Competency Definition', readonly=True)
    required_level = fields.Selection(related='line_id.required_level', string='Required Level', readonly=True)

    # 360 Multi-Rater Averages
    self_rating = fields.Float(string='Self Rating', readonly=True)
    peer_avg = fields.Float(string='Peer Avg', readonly=True)
    subordinate_avg = fields.Float(string='Subordinate Avg', readonly=True)
    supervisor_avg = fields.Float(string='Supervisor Avg', readonly=True)
    team_avg = fields.Float(string='Team Avg', readonly=True)
    weighted_current_level = fields.Float(string='Weighted Current Level', readonly=True)

    # Detailed rater line breakdown
    rater_line_ids = fields.One2many('competency.rater.breakdown.line', 'wizard_id', string='Individual Rater Scores', readonly=True)


class CompetencyRaterBreakdownLine(models.TransientModel):
    _name = 'competency.rater.breakdown.line'
    _description = '360° Rater Score Detail Line'

    wizard_id = fields.Many2one('competency.rater.breakdown.wizard', string='Wizard', ondelete='cascade')
    assessor_name = fields.Char(string='Assessor / Rater Name', readonly=True)
    rater_type = fields.Selection([
        ('self', 'Self Assessment'),
        ('peer', 'Peer Assessment'),
        ('subordinate', 'Subordinate Assessment'),
        ('supervisor', 'Supervisor Assessment'),
        ('team', 'Team Assessment'),
    ], string='Rater Role / Source', readonly=True)
    rating_level_str = fields.Char(string='Assessed Level', readonly=True)
    rating_num = fields.Integer(string='Level (Numeric)', readonly=True)
    assessment_name = fields.Char(string='Assessment Ref', readonly=True)
    assessment_state = fields.Char(string='Status', readonly=True)
    comments = fields.Text(string='Comments / Remarks', readonly=True)

