# -*- coding: utf-8 -*-
import io
import csv
import base64
import xlsxwriter
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class CompetencyReportWizard(models.TransientModel):
    """Ad-hoc Cascading Report Filtering & Multi-Format Export Wizard (PDF, Excel, CSV) (FR-RPT-007, FR-RPT-009)."""
    _name = 'competency.report.wizard'
    _description = 'Competency Cascading Report & Export Wizard'

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
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('supervisor_review', 'Supervisor Review'),
        ('hr_verified', 'HR Verified'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
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

    def _build_line_domain(self):
        """Construct domain based on wizard selections and enforce server-side boundary isolation."""
        domain = [('cycle_id', '=', self.cycle_id.id), ('is_primary_reporting_line', '=', True)]

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
            domain.append(('assessment_id.state', '=', self.stage_filter))
        return domain

    def action_generate_report(self):
        """Primary action: Generate Report based on Export Format & Report Type selections."""
        self.ensure_one()
        if self.export_format == 'pdf':
            return self.action_print_pdf()
        elif self.export_format == 'csv':
            return self.action_export_csv()
        else:
            return self.action_export_xlsx()

    def action_apply_filter(self):
        """Action: Open filtered list/pivot view tailored to selected report_type."""
        self.ensure_one()

        if self.report_type == 'detailed_matrix':
            domain = self._build_line_domain()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Comprehensive Competency Performance & Gap Matrix'),
                'res_model': 'competency.assessment.line',
                'view_mode': 'list,pivot,graph,form',
                'domain': domain,
                'target': 'current',
            }

        elif self.report_type == 'dept_role_gap':
            domain = self._build_line_domain()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Departmental & Role Competency Gap Analysis'),
                'res_model': 'competency.assessment.line',
                'view_mode': 'pivot,list,graph',
                'domain': domain,
                'context': {
                    'group_by': ['department_id', 'job_id'],
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
        # Group lines by (employee_id, competency_id)
        grouped = {}
        for l in lines:
            key = (l.employee_id.id, l.competency_id.id)
            grouped.setdefault(key, []).append(l)

        for (emp_id, comp_id), comp_lines in grouped.items():
            emp = self.env['hr.employee'].sudo().browse(emp_id)
            comp = self.env['competency.competency'].sudo().browse(comp_id)

            self_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'self' and l.current_level]
            peer_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'peer' and l.current_level]
            sub_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'subordinate' and l.current_level]
            sup_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'supervisor' and l.current_level]
            team_lines = [l for l in comp_lines if l.assessment_id.assessment_type == 'team' and l.current_level]

            self_val = int(self_lines[0].current_level) if self_lines else None
            peer_avg = round(sum(int(l.current_level) for l in peer_lines) / len(peer_lines), 2) if peer_lines else None
            sub_avg = round(sum(int(l.current_level) for l in sub_lines) / len(sub_lines), 2) if sub_lines else None
            sup_avg = round(sum(int(l.current_level) for l in sup_lines) / len(sup_lines), 2) if sup_lines else None
            team_avg = round(sum(int(l.current_level) for l in team_lines) / len(team_lines), 2) if team_lines else None

            # Calculate Weighted Final Rating
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
            if team_avg is not None:
                weighted_num += team_avg * w_team
                weighted_den += w_team

            final_rating = round(weighted_num / weighted_den, 2) if weighted_den > 0 else (self_val or 0.0)

            # Authoritative Role-Mapping required level lookup (Item 10)
            role_map = self.env['competency.role.mapping'].sudo().search([
                ('job_position_id', '=', emp.job_id.id if emp.job_id else 0),
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
            gap_val = round(req_val - final_rating, 2)

            if gap_val > 0:
                status_str = 'Underqualified'
            elif gap_val < 0:
                status_str = 'Overqualified'
            else:
                status_str = 'Fit / Qualified'

            ou_obj = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
            grade_obj = getattr(emp, 'grade_id', False)

            rows.append({
                'cycle_name': self.cycle_id.name,
                'emp_id_code': emp.id,
                'emp_name': emp.name,
                'operating_unit_name': ou_obj.name if ou_obj else 'N/A',
                'department_name': emp.department_id.name if emp.department_id else 'N/A',
                'job_name': emp.job_id.name if emp.job_id else 'N/A',
                'grade_name': (getattr(grade_obj, 'grade_name', False) or getattr(grade_obj, 'name', False) or 'N/A') if grade_obj else 'N/A',
                'competency_name': comp.name,
                'pillar_name': dict(comp._fields['pillar'].selection).get(comp.pillar, comp.pillar),
                'domain_name': comp.functional_domain or 'General',
                'self_rating': self_val if self_val is not None else 'N/A',
                'peer_avg': peer_avg if peer_avg is not None else 'N/A',
                'subordinate_avg': sub_avg if sub_avg is not None else 'N/A',
                'supervisor_avg': sup_avg if sup_avg is not None else 'N/A',
                'team_avg': team_avg if team_avg is not None else 'N/A',
                'weighted_rating': final_rating,
                'required_level': f"Level {req_val}",
                'weighted_gap': gap_val,
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
            writer.writerow([
                'Cycle', 'Employee ID', 'Employee Name', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                'Competency Name', 'Pillar', 'Functional Domain',
                'Self Rating', 'Peer Avg', 'Subordinate Avg', 'Supervisor Avg', 'Team Avg',
                'Weighted Current Rating', 'Required Level', 'Weighted Gap', 'Qualification Status'
            ])
            for r in rows:
                writer.writerow([
                    r['cycle_name'], r['emp_id_code'], r['emp_name'], r['operating_unit_name'], r['department_name'], r['job_name'], r['grade_name'],
                    r['competency_name'], r['pillar_name'], r['domain_name'],
                    r['self_rating'], r['peer_avg'], r['subordinate_avg'], r['supervisor_avg'], r['team_avg'],
                    r['weighted_rating'], r['required_level'], r['weighted_gap'], r['achievement_status']
                ])

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
                gaps = [x['weighted_gap'] for x in items if isinstance(x['weighted_gap'], (int, float))]
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
                writer.writerow([
                    self.cycle_id.name, a.name, a.employee_id.id, a.employee_id.name,
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

        csv_bytes = output.getvalue().encode('utf-8')
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
            rows = self._get_360_report_data_rows()
            headers = [
                'Cycle', 'Employee ID', 'Employee Name', 'Operating Unit', 'Department', 'Job Position', 'Job Grade',
                'Competency Name', 'Pillar', 'Functional Domain',
                'Self Rating', 'Peer Avg', 'Subordinate Avg', 'Supervisor Avg', 'Team Avg',
                'Weighted Current Rating', 'Required Level', 'Weighted Gap', 'Qualification Status'
            ]
            for col_num, header in enumerate(headers):
                worksheet.write(0, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 18)

            for row_num, r in enumerate(rows, start=1):
                worksheet.write(row_num, 0, r['cycle_name'], cell_format)
                worksheet.write(row_num, 1, r['emp_id_code'], cell_format)
                worksheet.write(row_num, 2, r['emp_name'], cell_format)
                worksheet.write(row_num, 3, r['operating_unit_name'], cell_format)
                worksheet.write(row_num, 4, r['department_name'], cell_format)
                worksheet.write(row_num, 5, r['job_name'], cell_format)
                worksheet.write(row_num, 6, r['grade_name'], cell_format)
                worksheet.write(row_num, 7, r['competency_name'], cell_format)
                worksheet.write(row_num, 8, r['pillar_name'], cell_format)
                worksheet.write(row_num, 9, r['domain_name'], cell_format)
                worksheet.write(row_num, 10, r['self_rating'], num_format if isinstance(r['self_rating'], (int, float)) else cell_format)
                worksheet.write(row_num, 11, r['peer_avg'], num_format if isinstance(r['peer_avg'], (int, float)) else cell_format)
                worksheet.write(row_num, 12, r['subordinate_avg'], num_format if isinstance(r['subordinate_avg'], (int, float)) else cell_format)
                worksheet.write(row_num, 13, r['supervisor_avg'], num_format if isinstance(r['supervisor_avg'], (int, float)) else cell_format)
                worksheet.write(row_num, 14, r['team_avg'], num_format if isinstance(r['team_avg'], (int, float)) else cell_format)
                worksheet.write(row_num, 15, r['weighted_rating'], num_format)
                worksheet.write(row_num, 16, r['required_level'], cell_format)
                worksheet.write(row_num, 17, r['weighted_gap'], num_format)
                worksheet.write(row_num, 18, r['achievement_status'], cell_format)

        elif self.report_type == 'dept_role_gap':
            worksheet = workbook.add_worksheet('Dept & Role Gap')
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
                worksheet.write(0, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 20)

            for row_num, ((dept, job), items) in enumerate(sorted(grouped.items()), start=1):
                meets = sum(1 for x in items if x['achievement_status'] == 'Fit / Qualified')
                below = sum(1 for x in items if x['achievement_status'] == 'Underqualified')
                exceeds = sum(1 for x in items if x['achievement_status'] == 'Overqualified')
                gaps = [x['weighted_gap'] for x in items if isinstance(x['weighted_gap'], (int, float))]
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
                worksheet.write(0, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 18)

            for row_num, a in enumerate(asms, start=1):
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
                worksheet.write(0, col_num, header, header_format)
                worksheet.set_column(col_num, col_num, 18)

            for row_num, (d_name, items) in enumerate(sorted(dept_map.items()), start=1):
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
            emp = self.employee_ids[:1] or self.env.user.employee_id
            asm = self.env['competency.assessment'].search([
                ('employee_id', '=', emp.id if emp else 0),
                ('cycle_id', '=', self.cycle_id.id)
            ], limit=1)
            if not asm:
                raise UserError(_("No assessment found for employee %s in cycle %s.") % (emp.name if emp else 'N/A', self.cycle_id.name))
            return self.env.ref('competency_management.action_report_competency_assessment_individual').report_action(asm)
        elif self.report_type == 'dept_role_gap':
            return self.env.ref('competency_management.action_report_competency_team_gap').report_action(self)
        elif self.report_type == 'detailed_matrix':
            return self.env.ref('competency_management.action_report_competency_detailed_matrix').report_action(self)
        elif self.report_type == 'campaign_progress':
            return self.env.ref('competency_management.action_report_competency_campaign_progress').report_action(self)
        else:
            return self.env.ref('competency_management.action_report_competency_org_capability').report_action(self)

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

