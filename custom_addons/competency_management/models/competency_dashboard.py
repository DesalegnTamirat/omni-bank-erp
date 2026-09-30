# -*- coding: utf-8 -*-
import base64
import html
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CompetencyDashboard(models.TransientModel):
    """Executive & Employee Self-Service Competency Dashboard."""
    _name = 'competency.dashboard'
    _description = 'Executive & Employee Competency Dashboard'

    name = fields.Char(string='Dashboard Title', default='Bunna Bank Competency & Talent Capability Dashboard')

    # Selected Assessment Cycle for Dynamic Dashboard Filtering
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Select Assessment Cycle',
        default=lambda self: self._default_cycle_id(),
    )
    # Admin Filter & Role Access Flags
    filter_department_id = fields.Many2one('hr.department', string='Filter Department')
    is_admin_user = fields.Boolean(string='Is Admin User', compute='_compute_user_access')
    is_supervisor_user = fields.Boolean(string='Is Supervisor User', compute='_compute_user_access')
    is_employee_only = fields.Boolean(string='Is Employee Only', compute='_compute_user_access')

    def _default_cycle_id(self):
        cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], limit=1)
        if not cycle:
            cycle = self.env['competency.assessment.cycle'].sudo().search([], order='id desc', limit=1)
        return cycle

    def _compute_user_access(self):
        user = self.env.user
        is_admin = user.has_group('competency_management.group_competency_admin')
        is_supervisor = user.has_group('competency_management.group_competency_supervisor')
        has_reports = self.env['hr.employee'].search_count([('parent_id.user_id', '=', user.id)]) > 0

        if is_admin:
            default_role = 'executive'
        elif is_supervisor and has_reports:
            default_role = 'manager'
        elif is_supervisor:
            default_role = 'hrbp'
        else:
            default_role = 'employee'

        for rec in self:
            rec.is_hr_admin = is_admin
            rec.is_admin_user = is_admin
            rec.is_supervisor_user = is_supervisor or is_admin
            rec.is_employee_only = not (is_admin or is_supervisor)
            if not rec.persona_role:
                rec.persona_role = default_role



    def action_start_self_assessment(self):
        """Action: Create or open self-assessment for current employee."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            raise UserError(_("No employee record found for user %s.") % user.name)

        cycle = self.cycle_id
        if not cycle or cycle.state != 'open':
            cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], limit=1)
        if not cycle:
            raise UserError(_('There is currently no open Assessment Cycle. Please contact HR.'))

        existing = self.env['competency.assessment'].search([
            ('employee_id', '=', emp.id),
            ('cycle_id', '=', cycle.id),
            ('assessment_type', '=', 'self')
        ], limit=1)

        if existing:
            res_id = existing.id
        else:
            new_asm = self.env['competency.assessment'].create({
                'employee_id': emp.id,
                'cycle_id': cycle.id,
                'assessment_type': 'self',
                'assessor_id': user.id,
                'state': 'draft',
            })
            res_id = new_asm.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'My Self-Assessment',
            'res_model': 'competency.assessment',
            'res_id': res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_my_report(self):
        self.ensure_one()
        if self.latest_assessment_id:
            return self.env.ref('competency_management.action_report_competency_assessment').report_action(self.latest_assessment_id)
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Assessment Available'),
                    'message': _('Complete your assessment first to generate a PDF profile report.'),
                    'type': 'warning',
                }
            }

    def action_view_my_gap_chart(self):
        """Action: Open graph/pivot view of employee's competency gaps."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        domain = [('assessment_id.employee_id', '=', emp.id)] if emp else []
        return {
            'type': 'ir.actions.act_window',
            'name': 'My Competency Gap Graph & Breakdown',
            'res_model': 'competency.assessment.line',
            'view_mode': 'graph,pivot,list',
            'domain': domain,
            'target': 'current',
        }

    def action_open_tna_analytics_below(self):
        """Open detailed TNA Analytics pre-filtered for Underqualified (Below Target)."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_primary_reporting'] = 1
        ctx['search_default_filter_below'] = 1
        ctx['create'] = False
        ctx['edit'] = False
        ctx['delete'] = False
        domain = [('is_primary_reporting_line', '=', True), ('achievement_status', '=', 'below')]
        if self.cycle_id:
            domain.append(('cycle_id', '=', self.cycle_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Underqualified Competency Lines (Training Needed)',
            'res_model': 'competency.assessment.line',
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_tna_analytics_meets(self):
        """Open detailed TNA Analytics pre-filtered for Fit / Qualified."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_primary_reporting'] = 1
        ctx['search_default_filter_meets'] = 1
        ctx['create'] = False
        ctx['edit'] = False
        ctx['delete'] = False
        domain = [('is_primary_reporting_line', '=', True), ('achievement_status', '=', 'meets')]
        if self.cycle_id:
            domain.append(('cycle_id', '=', self.cycle_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fit / Qualified Competency Lines',
            'res_model': 'competency.assessment.line',
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_tna_analytics_exceeds(self):
        """Open detailed TNA Analytics pre-filtered for Overqualified."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_primary_reporting'] = 1
        ctx['search_default_filter_exceeds'] = 1
        ctx['create'] = False
        ctx['edit'] = False
        ctx['delete'] = False
        domain = [('is_primary_reporting_line', '=', True), ('achievement_status', '=', 'exceeds')]
        if self.cycle_id:
            domain.append(('cycle_id', '=', self.cycle_id.id))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Overqualified Competency Lines',
            'res_model': 'competency.assessment.line',
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_employee_primary_action(self):
        """Contextual single primary action button for Employee hero area."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            raise UserError(_("No employee record found for user %s.") % user.name)

        cycle = self.cycle_id or self._default_cycle_id()
        asm = self.env['competency.assessment'].search([
            ('employee_id', '=', emp.id),
            ('cycle_id', '=', cycle.id)
        ], limit=1) if cycle else False

        if not asm:
            asm = self.env['competency.assessment'].create({
                'employee_id': emp.id,
                'cycle_id': cycle.id if cycle else False,
                'assessment_type': 'self',
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('My Competency Assessment'),
            'res_model': 'competency.assessment',
            'res_id': asm.id,
            'views': [[False, 'form']],
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _get_fully_assessed_employee_ids(self, cycle_id=False, asm_domain=None):
        """Return the set of employee IDs where every assessment assigned to them in this cycle
        is in a non-draft state (i.e. all raters have submitted).
        Uses a single SQL GROUP BY/HAVING query instead of loading all assessment rows into memory.
        """
        if not cycle_id and not asm_domain:
            return set()

        # Resolve cycle_id from domain if not passed directly
        cid = cycle_id
        if not cid and asm_domain:
            for item in (asm_domain or []):
                if isinstance(item, (list, tuple)) and len(item) == 3 and item[0] == 'cycle_id' and item[1] == '=':
                    cid = item[2]
                    break
        if not cid:
            return set()

        # Resolve optional employee scope from domain
        scoped_emp_ids = None
        if asm_domain:
            for item in asm_domain:
                if isinstance(item, (list, tuple)) and len(item) == 3 and item[0] == 'employee_id' and item[1] == 'in':
                    scoped_emp_ids = tuple(item[2])
                    break

        if scoped_emp_ids is not None and not scoped_emp_ids:
            return set()

        if scoped_emp_ids:
            self.env.cr.execute("""
                SELECT employee_id
                FROM competency_assessment
                WHERE cycle_id = %s
                  AND employee_id IN %s
                  AND active = true
                GROUP BY employee_id
                HAVING COUNT(CASE WHEN state = 'draft' THEN 1 END) = 0
            """, (cid, scoped_emp_ids))
        else:
            self.env.cr.execute("""
                SELECT employee_id
                FROM competency_assessment
                WHERE cycle_id = %s
                  AND active = true
                GROUP BY employee_id
                HAVING COUNT(CASE WHEN state = 'draft' THEN 1 END) = 0
            """, (cid,))

        return {row[0] for row in self.env.cr.fetchall()}

    def action_open_tna_analytics_all(self):
        """Open full TNA Analytics and Assessment Line Report grouped by employee."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_group_by_employee'] = 1
        ctx['search_default_filter_primary_reporting'] = 1
        ctx['create'] = False
        ctx['edit'] = False
        ctx['delete'] = False
        domain = [('is_primary_reporting_line', '=', True), '|', ('weighted_current_level', '>', 0), ('achievement_status', '!=', False)]
        if self.cycle_id:
            domain.append(('cycle_id', '=', self.cycle_id.id))
            fully_assessed_ids = self._get_fully_assessed_employee_ids(cycle_id=self.cycle_id.id)
            domain.append(('employee_id', 'in', list(fully_assessed_ids)))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assessed Employees Competency Reporting',
            'res_model': 'competency.assessment.line',
            'search_view_id': [self.env.ref('competency_management.view_competency_assessment_line_report_search').id, 'search'],
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    @api.model
    def action_open_assessed_employees(self, cycle_id=False, department_id=False, operating_unit_id=False):
        """Open Assessed Employees Competency Reporting, strictly scoped to employees
        where all assigned evaluations are submitted."""
        domain = [('is_primary_reporting_line', '=', True), '|', ('weighted_current_level', '>', 0), ('achievement_status', '!=', False)]
        if cycle_id:
            domain.append(('cycle_id', '=', int(cycle_id)))
            fully_assessed_ids = self._get_fully_assessed_employee_ids(cycle_id=int(cycle_id))
            domain.append(('employee_id', 'in', list(fully_assessed_ids)))
        if department_id:
            domain.append(('department_id', '=', int(department_id)))
        if operating_unit_id:
            ou_emp_ids = self.env['hr.employee'].sudo().search([
                '|', ('default_operating_unit_id', '=', int(operating_unit_id)),
                '|', ('operating_unit_id', '=', int(operating_unit_id)),
                ('department_id.operating_unit_id', '=', int(operating_unit_id))
            ]).ids
            domain.append(('employee_id', 'in', ou_emp_ids))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assessed Employees Competency Reporting',
            'res_model': 'competency.assessment.line',
            'search_view_id': [self.env.ref('competency_management.view_competency_assessment_line_report_search').id, 'search'],
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': {
                'search_default_group_by_employee': 1,
                'search_default_filter_primary_reporting': 1,
                'create': False,
                'edit': False,
                'delete': False,
            },
            'target': 'current',
        }

    @api.model
    def action_open_unmapped_positions(self):
        """Open list of job positions that do not have an approved competency role mapping."""
        user = self.env.user
        is_admin = user.has_group('competency_management.group_competency_admin')
        user_ou_ids = []
        if not is_admin:
            if getattr(user, 'assigned_operating_unit_ids', False):
                user_ou_ids = user.assigned_operating_unit_ids.ids
            elif getattr(user, 'operating_unit_ids', False):
                user_ou_ids = user.operating_unit_ids.ids

        if user_ou_ids:
            ou_emp_domain = [
                '|', ('default_operating_unit_id', 'in', user_ou_ids),
                ('department_id.operating_unit_id', 'in', user_ou_ids)
            ]
            ou_employees = self.env['hr.employee'].sudo().search(ou_emp_domain)
            target_jobs = ou_employees.mapped('job_id')
            mapped_job_ids = set(self.env['competency.role.mapping'].search([
                ('state', '=', 'approved'),
                ('job_position_id', 'in', target_jobs.ids)
            ]).mapped('job_position_id.id'))
            unmapped_job_ids = [j.id for j in target_jobs if j.id not in mapped_job_ids]
        else:
            mapped_job_ids = set(self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id'))
            unmapped_job_ids = self.env['hr.job'].search([('id', 'not in', list(mapped_job_ids))]).ids

        return {
            'type': 'ir.actions.act_window',
            'name': _('Unmapped Job Positions (Awaiting Role Competency Mapping)'),
            'res_model': 'hr.job',
            'views': [[False, 'list'], [False, 'kanban'], [False, 'form']],
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', unmapped_job_ids)],
            'target': 'current',
        }

    @api.model
    def action_open_missing_supervisors(self):
        """Open list of active employees missing an assigned supervisor (parent_id)."""
        user = self.env.user
        is_admin = user.has_group('competency_management.group_competency_admin')
        user_ou_ids = []
        if not is_admin:
            if getattr(user, 'assigned_operating_unit_ids', False):
                user_ou_ids = user.assigned_operating_unit_ids.ids
            elif getattr(user, 'operating_unit_ids', False):
                user_ou_ids = user.operating_unit_ids.ids

        if user_ou_ids:
            domain = [
                ('active', '=', True),
                ('parent_id', '=', False),
                '|', ('default_operating_unit_id', 'in', user_ou_ids),
                ('department_id.operating_unit_id', 'in', user_ou_ids)
            ]
        else:
            domain = [('active', '=', True), ('parent_id', '=', False)]

        return {
            'type': 'ir.actions.act_window',
            'name': _('Employees Missing Assigned Supervisor'),
            'res_model': 'hr.employee',
            'views': [[False, 'list'], [False, 'kanban'], [False, 'form']],
            'view_mode': 'list,kanban,form',
            'domain': domain,
            'target': 'current',
        }

    @api.model
    def action_open_matrix_config(self):
        """Action: Open Proficiency Matrix Settings configuration form."""
        config = self.env['competency.matrix.config'].get_active_config()
        view_id = self.env.ref('competency_management.view_competency_matrix_config_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Competency Proficiency Matrix Configuration'),
            'res_model': 'competency.matrix.config',
            'res_id': config.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'current',
        }

    def action_open_dashboard(self):
        """Action method to open the dashboard Singleton form view or client action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'competency_dashboard_action',
            'name': 'Competency & TNA Dashboard',
        }

    @api.model
    def get_dashboard_data(self, cycle_id=None, department_id=None, operating_unit_id=None, persona=None):
        """RPC API endpoint supplying structured JSON metrics and Chart.js datasets to the OWL frontend."""
        user = self.env.user.sudo()
        emp = user.employee_id
        is_admin = bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )

        # Check if user is a Department Leader
        is_dept_manager = False
        managed_depts = self.env['hr.department'].sudo().browse()
        if emp:
            managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
            if not managed_depts and emp.department_id and emp.department_id.manager_id.id == emp.id:
                managed_depts = emp.department_id
            if managed_depts:
                is_dept_manager = True

        has_subordinates = bool(emp and self.env['hr.employee'].sudo().search_count([('parent_id', '=', emp.id)]) > 0)
        is_supervisor = bool(
            user.has_group('competency_management.group_competency_supervisor')
            or (emp and bool(emp.child_ids))
            or has_subordinates
            or is_dept_manager
        )

        # Check if user is an Operating Unit Leader
        emp_ou = False
        if emp:
            emp_ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
        if not emp_ou and user.default_operating_unit_id:
            emp_ou = user.default_operating_unit_id

        is_ou_leader = False
        if emp and emp_ou and emp_ou.manager_id and emp_ou.manager_id.id == emp.id:
            has_superior_in_ou = bool(
                (emp.parent_id and (emp.parent_id.default_operating_unit_id == emp_ou or emp.parent_id.operating_unit_id == emp_ou)) or
                (emp.coach_id and (emp.coach_id.default_operating_unit_id == emp_ou or emp.coach_id.operating_unit_id == emp_ou))
            )
            if not has_superior_in_ou:
                is_ou_leader = True

        # Access & Scoping rules:
        # If admin: can select department and operating unit. Persona = executive.
        # If leader of one department: department is readonly (fixed to managed dept), can select operating unit. Persona = manager.
        # If leader of operating unit: operating unit is fixed, can select department within OU. Persona = manager.
        # If subordinate coach: both department and operating unit are fixed. Persona = manager. Restricted strictly to team.
        # If employee: both department and operating unit are fixed. Persona = employee. Restricted strictly to self.
        if is_admin:
            is_dept_readonly = False
            is_ou_readonly = False
            persona = 'executive'

            if operating_unit_id:
                ou_id_int = int(operating_unit_id)
                direct_depts = self.env['hr.department'].sudo().search([
                    '|', ('operating_unit_id', '=', ou_id_int),
                    ('operating_unit', '=', ou_id_int)
                ])
                ou_emps = self.env['hr.employee'].sudo().search([
                    '|', ('default_operating_unit_id', '=', ou_id_int),
                    '|', ('operating_unit_id', '=', ou_id_int),
                    ('department_id.operating_unit_id', '=', ou_id_int)
                ])
                emp_depts = ou_emps.mapped('department_id')
                dept_pool = (direct_depts | emp_depts).filtered(lambda d: d.id)
                all_departments = [{'id': d.id, 'name': d.name} for d in dept_pool.sorted(key=lambda d: d.name or '')]
            else:
                all_departments = self.env['hr.department'].sudo().search_read([], ['id', 'name'], order='name asc')

            all_operating_units = self.env['operating.unit'].sudo().search_read([], ['id', 'name'], order='name asc')
        elif is_dept_manager:
            is_dept_readonly = True
            is_ou_readonly = False
            persona = 'manager'
            lead_dept = managed_depts[:1]
            department_id = lead_dept.id
            all_departments = [{'id': d.id, 'name': d.name} for d in managed_depts]

            ou_direct = self.env['operating.unit'].sudo().search([('department', 'in', managed_depts.ids)])
            ou_from_dept = managed_depts.mapped('operating_unit_id')
            dept_emps = self.env['hr.employee'].sudo().search([('department_id', 'in', managed_depts.ids)])
            ou_from_emps = dept_emps.mapped('default_operating_unit_id') | dept_emps.mapped('operating_unit_id')
            allowed_ous = (ou_direct | ou_from_dept | ou_from_emps).filtered(lambda u: u.id)
            all_operating_units = [{'id': u.id, 'name': u.name} for u in allowed_ous]
        elif is_ou_leader and emp_ou:
            is_dept_readonly = False
            is_ou_readonly = True
            persona = 'manager'
            operating_unit_id = emp_ou.id
            all_operating_units = [{'id': emp_ou.id, 'name': emp_ou.name}]
            ou_emps = self.env['hr.employee'].sudo().search([
                '|', ('default_operating_unit_id', '=', emp_ou.id),
                '|', ('operating_unit_id', '=', emp_ou.id),
                ('department_id.operating_unit_id', '=', emp_ou.id)
            ])
            ou_depts = ou_emps.mapped('department_id').filtered(lambda d: d.id)
            all_departments = [{'id': d.id, 'name': d.name} for d in ou_depts]
        else:
            is_dept_readonly = True
            is_ou_readonly = True
            persona = 'manager' if is_supervisor else 'employee'
            user_dept = emp.department_id if emp else False
            department_id = user_dept.id if user_dept else False
            all_departments = [{'id': user_dept.id, 'name': user_dept.name}] if user_dept else []
            operating_unit_id = emp_ou.id if emp_ou else False
            all_operating_units = [{'id': emp_ou.id, 'name': emp_ou.name}] if emp_ou else []

        # Validate operating_unit_id within allowed OUs
        if operating_unit_id:
            allowed_ou_ids = [u['id'] for u in all_operating_units]
            if int(operating_unit_id) not in allowed_ou_ids:
                operating_unit_id = False

        # Selected Cycle resolution
        if cycle_id:
            cycle = self.env['competency.assessment.cycle'].sudo().browse(int(cycle_id))
        else:
            cycle = self.env['competency.assessment.cycle'].sudo().search([('state', '=', 'open')], limit=1)
            if not cycle:
                cycle = self.env['competency.assessment.cycle'].sudo().search([], order='id desc', limit=1)

        # Active Assessment Cycle Info for Dashboard Header Banner
        open_cycle = self.env['competency.assessment.cycle'].sudo().search([('state', 'in', ['open', 'in_review'])], order='id desc', limit=1)
        active_cycle_info = {}
        if open_cycle:
            p_start = open_cycle.period_start.strftime('%b %d, %Y') if open_cycle.period_start else 'N/A'
            p_end = open_cycle.period_end.strftime('%b %d, %Y') if open_cycle.period_end else 'N/A'
            deadline = open_cycle.assessment_deadline.strftime('%b %d, %Y') if open_cycle.assessment_deadline else 'N/A'
            today = fields.Date.context_today(self)
            is_deadline_passed = bool(open_cycle.assessment_deadline and today > open_cycle.assessment_deadline)

            if is_deadline_passed:
                state_label = 'Deadline Passed'
            elif open_cycle.state == 'open':
                state_label = 'Open for Submissions'
            else:
                state_label = 'In Review'

            active_cycle_info = {
                'has_active': True,
                'name': open_cycle.name,
                'state': open_cycle.state,
                'is_deadline_passed': is_deadline_passed,
                'state_label': state_label,
                'period_start': p_start,
                'period_end': p_end,
                'deadline': deadline,
            }
        else:
            active_cycle_info = {
                'has_active': False,
            }

        # Available Cycles list
        all_cycles = self.env['competency.assessment.cycle'].sudo().search_read([], ['id', 'name', 'state', 'assessment_deadline'], order='id desc')

        # Baseline domains
        line_domain = [('cycle_id', '=', cycle.id)] if cycle else []
        asm_domain = [('cycle_id', '=', cycle.id)] if cycle else []

        # Persona-based & Role-based employee scoping
        subordinate_emp_ids = []
        if emp and is_supervisor:
            subordinate_emp_ids = self.env['hr.employee'].sudo().search([
                '|', ('parent_id', '=', emp.id),
                ('coach_id', '=', emp.id)
            ]).ids

        if persona == 'employee' and emp:
            scoped_emp_ids = [emp.id]
        elif persona == 'manager' and emp:
            if is_dept_manager and managed_depts:
                dept_emp_ids = self.env['hr.employee'].sudo().search([('department_id', 'in', managed_depts.ids)]).ids
                scoped_emp_ids = list(set(subordinate_emp_ids + dept_emp_ids + [emp.id]))
            elif is_ou_leader and emp_ou:
                ou_emp_ids = self.env['hr.employee'].sudo().search([
                    '|', ('default_operating_unit_id', '=', emp_ou.id),
                    '|', ('operating_unit_id', '=', emp_ou.id),
                    ('department_id.operating_unit_id', '=', emp_ou.id)
                ]).ids
                scoped_emp_ids = list(set(subordinate_emp_ids + ou_emp_ids + [emp.id]))
            else:
                # Subordinate coach: only their direct/indirect subordinates and themselves.
                # Strictly prevents viewing OU total data, department peers, or their boss's assessment data.
                scoped_emp_ids = list(set(subordinate_emp_ids + [emp.id]))
        else:
            scoped_emp_ids = False

        if scoped_emp_ids:
            line_domain.append(('employee_id', 'in', scoped_emp_ids))
            asm_domain.append(('employee_id', 'in', scoped_emp_ids))

        # Only apply global department_id filter if admin or dept manager with multiple depts or ou leader
        if department_id and (is_admin or (is_dept_manager and len(managed_depts) > 1) or is_ou_leader):
            line_domain.append(('department_id', 'child_of', int(department_id)))
            asm_domain.append(('department_id', 'child_of', int(department_id)))

        # Only apply global operating_unit_id filter if admin or dept manager
        if operating_unit_id and (is_admin or is_dept_manager):
            ou_emp_ids = self.env['hr.employee'].sudo().search([
                '|', ('default_operating_unit_id', '=', int(operating_unit_id)),
                '|', ('operating_unit_id', '=', int(operating_unit_id)),
                ('department_id.operating_unit_id', '=', int(operating_unit_id))
            ]).ids
            line_domain.append(('employee_id', 'in', ou_emp_ids))
            asm_domain.append(('employee_id', 'in', ou_emp_ids))

        # Fully Assessed Employees: Only employees where ALL assigned raters (self, supervisor, peers, subordinates)
        # have submitted their results in this cycle. If any evaluation is still in 'draft', the employee is NOT counted.
        fully_assessed_emp_ids = self._get_fully_assessed_employee_ids(
            cycle_id=cycle.id if cycle else False,
            asm_domain=asm_domain
        )

        if fully_assessed_emp_ids:
            asms_total = len(fully_assessed_emp_ids)
            emp_ids_tuple = tuple(fully_assessed_emp_ids)
            cycle_id_val = cycle.id if cycle else 0

            extra_filter = ""
            params = [cycle_id_val, emp_ids_tuple]

            dept_filter_val = int(department_id) if department_id else None
            if dept_filter_val:
                extra_filter += " AND department_id = %s"
                params.append(dept_filter_val)

            self.env.cr.execute(f"""
                SELECT
                    COUNT(CASE WHEN achievement_status = 'below' THEN 1 END)      AS below_cnt,
                    COUNT(CASE WHEN achievement_status = 'meets' THEN 1 END)       AS meets_cnt,
                    COUNT(CASE WHEN achievement_status = 'exceeds' THEN 1 END)     AS exceeds_cnt,
                    ROUND(AVG(CASE WHEN pillar = 'core'       THEN gap END)::numeric, 2) AS core_avg,
                    ROUND(AVG(CASE WHEN pillar = 'leadership' THEN gap END)::numeric, 2) AS lead_avg,
                    ROUND(AVG(CASE WHEN pillar = 'technical'  THEN gap END)::numeric, 2) AS tech_avg,
                    ROUND(AVG(gap)::numeric, 2)                                    AS bank_avg,
                    COUNT(*)                                                        AS total_lines,
                    COUNT(CASE WHEN pillar = 'core' AND achievement_status = 'below' THEN 1 END) AS core_below,
                    COUNT(CASE WHEN pillar = 'leadership' AND achievement_status = 'below' THEN 1 END) AS lead_below,
                    COUNT(CASE WHEN pillar = 'technical' AND achievement_status = 'below' THEN 1 END) AS tech_below,
                    COUNT(CASE WHEN pillar = 'core' AND achievement_status = 'meets' THEN 1 END) AS core_meets,
                    COUNT(CASE WHEN pillar = 'leadership' AND achievement_status = 'meets' THEN 1 END) AS lead_meets,
                    COUNT(CASE WHEN pillar = 'technical' AND achievement_status = 'meets' THEN 1 END) AS tech_meets,
                    COUNT(CASE WHEN pillar = 'core' AND achievement_status = 'exceeds' THEN 1 END) AS core_exceeds,
                    COUNT(CASE WHEN pillar = 'leadership' AND achievement_status = 'exceeds' THEN 1 END) AS lead_exceeds,
                    COUNT(CASE WHEN pillar = 'technical' AND achievement_status = 'exceeds' THEN 1 END) AS tech_exceeds
                FROM competency_assessment_line
                WHERE cycle_id = %s
                  AND employee_id IN %s
                  AND is_primary_reporting_line = true
                  AND active = true
                  AND (weighted_current_level > 0 OR achievement_status IS NOT NULL)
                  {extra_filter}
            """, params)

            row = self.env.cr.fetchone()
            if row:
                (below_cnt, meets_cnt, exceeds_cnt, core_avg, lead_avg, tech_avg, bank_avg, _total,
                 core_below, lead_below, tech_below,
                 core_meets, lead_meets, tech_meets,
                 core_exceeds, lead_exceeds, tech_exceeds) = row
                below_cnt = below_cnt or 0
                meets_cnt = meets_cnt or 0
                exceeds_cnt = exceeds_cnt or 0
                core_avg = float(core_avg or 0.0)
                lead_avg = float(lead_avg or 0.0)
                tech_avg = float(tech_avg or 0.0)
                bank_avg = float(bank_avg or 0.0)
                core_below = core_below or 0
                lead_below = lead_below or 0
                tech_below = tech_below or 0
                core_meets = core_meets or 0
                lead_meets = lead_meets or 0
                tech_meets = tech_meets or 0
                core_exceeds = core_exceeds or 0
                lead_exceeds = lead_exceeds or 0
                tech_exceeds = tech_exceeds or 0
            else:
                below_cnt = meets_cnt = exceeds_cnt = 0
                core_avg = lead_avg = tech_avg = bank_avg = 0.0
                core_below = lead_below = tech_below = 0
                core_meets = lead_meets = tech_meets = 0
                core_exceeds = lead_exceeds = tech_exceeds = 0
            has_real_data = bool(row and asms_total > 0)
        else:
            asms_total = 0
            below_cnt = meets_cnt = exceeds_cnt = 0
            core_avg = lead_avg = tech_avg = bank_avg = 0.0
            core_below = lead_below = tech_below = 0
            core_meets = lead_meets = tech_meets = 0
            core_exceeds = lead_exceeds = tech_exceeds = 0
            has_real_data = False

        # Data Quality Counters (Scoped to selected or fixed OU if set)
        target_ou_ids = [int(operating_unit_id)] if operating_unit_id else []
        if target_ou_ids:
            ou_emp_domain = [
                '|', ('default_operating_unit_id', 'in', target_ou_ids),
                '|', ('operating_unit_id', 'in', target_ou_ids),
                ('department_id.operating_unit_id', 'in', target_ou_ids)
            ]
            ou_employees = self.env['hr.employee'].sudo().search(ou_emp_domain)
            ou_jobs = ou_employees.mapped('job_id')
            total_jobs = len(ou_jobs)
            mapped_job_ids = set(self.env['competency.role.mapping'].search([('state', '=', 'approved'), ('job_position_id', 'in', ou_jobs.ids)]).mapped('job_position_id.id'))
            unmapped_cnt = max(0, total_jobs - len(mapped_job_ids))
            missing_sups_cnt = len(ou_employees.filtered(lambda e: e.active and not e.parent_id))
        else:
            total_jobs = self.env['hr.job'].search_count([])
            mapped_job_ids = set(self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id'))
            unmapped_cnt = max(0, total_jobs - len(mapped_job_ids))
            missing_sups_cnt = self.env['hr.employee'].search_count([('active', '=', True), ('parent_id', '=', False)])

        # Personal Metrics (Logged in Employee)
        my_asm = False
        if emp:
            if cycle:
                # 1. Prioritize self-assessment for this cycle so the employee's full competency profile is loaded
                my_asm = self.env['competency.assessment'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('cycle_id', '=', cycle.id),
                    ('assessment_type', '=', 'self')
                ], limit=1)
                # 2. If no self-assessment, pick the assessment with the most lines for this cycle
                if not my_asm:
                    asms = self.env['competency.assessment'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('cycle_id', '=', cycle.id)
                    ])
                    if asms:
                        my_asm = max(asms, key=lambda a: len(a.line_ids))
            if not my_asm:
                my_asm = self.env['competency.assessment'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('assessment_type', '=', 'self')
                ], order='id desc', limit=1)
            if not my_asm:
                asms = self.env['competency.assessment'].sudo().search([
                    ('employee_id', '=', emp.id)
                ])
                if asms:
                    my_asm = max(asms, key=lambda a: len(a.line_ids))

        # First Source of Truth: The Employee's Job Position Competency Role Mapping
        # As assigned competencies originate from the role mapping (not individual assessments which can be configured for partial pillars)
        radar_labels = []
        radar_assessed = []
        radar_required = []
        radar_pillars = []

        mapping = False
        if emp:
            job_pos = getattr(emp, 'job_position', False) or emp.job_id
            if job_pos:
                emp_ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
                # Priority 1: Specific Operating Unit Mapping
                if emp_ou:
                    mapping = self.env['competency.role.mapping'].sudo().search([
                        ('job_position_id', '=', job_pos.id),
                        ('state', '=', 'approved'),
                        ('is_operating_unit_specific', '=', True),
                        ('operating_unit_ids', 'in', [emp_ou.id])
                    ], order='id desc', limit=1)
                # Priority 2: Global / All Operating Units Mapping
                if not mapping:
                    mapping = self.env['competency.role.mapping'].sudo().search([
                        ('job_position_id', '=', job_pos.id),
                        ('state', '=', 'approved'),
                        ('is_operating_unit_specific', '=', False)
                    ], order='id desc', limit=1)
                # Priority 3: General Fallback (any approved)
                if not mapping:
                    mapping = self.env['competency.role.mapping'].sudo().search([
                        ('job_position_id', '=', job_pos.id),
                        ('state', '=', 'approved')
                    ], order='id desc', limit=1)
                # Priority 4: Draft/Any mapping
                if not mapping:
                    mapping = self.env['competency.role.mapping'].sudo().search([
                        ('job_position_id', '=', job_pos.id)
                    ], order='id desc', limit=1)

        # Pre-fetch assessed levels for this employee in the active cycle
        assessed_levels_by_comp_id = {}
        if emp:
            # 1. Primary reporting lines have the official weighted / final scores
            if cycle:
                p_lines = self.env['competency.assessment.line'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('cycle_id', '=', cycle.id),
                    ('is_primary_reporting_line', '=', True)
                ])
                for pl in p_lines:
                    if pl.competency_id:
                        c_val = int(round(pl.weighted_current_level)) if pl.weighted_current_level else (int(pl.current_level) if pl.current_level and str(pl.current_level).isdigit() else 0)
                        if c_val > 0:
                            assessed_levels_by_comp_id[pl.competency_id.id] = c_val

            # 2. Check all assessment lines for this employee in this cycle (self, supervisor, etc.)
            cycle_domain = [('employee_id', '=', emp.id)]
            if cycle:
                cycle_domain.append(('cycle_id', '=', cycle.id))
            asm_lines = self.env['competency.assessment.line'].sudo().search(cycle_domain)
            for al in asm_lines:
                if al.competency_id and al.competency_id.id not in assessed_levels_by_comp_id:
                    c_val = int(round(al.weighted_current_level)) if al.weighted_current_level else (int(al.current_level) if al.current_level and str(al.current_level).isdigit() else 0)
                    if c_val > 0:
                        assessed_levels_by_comp_id[al.competency_id.id] = c_val

        # Primary source: Populate from Role Mapping
        if mapping and mapping.line_ids:
            for mline in mapping.line_ids:
                if mline.competency_id and mline.competency_id.name not in radar_labels:
                    radar_labels.append(mline.competency_id.name)
                    m_req = getattr(mline, 'required_proficiency', False) or getattr(mline, 'required_level', False)
                    req = int(m_req) if m_req and str(m_req).isdigit() else 1
                    radar_required.append(req)
                    radar_assessed.append(assessed_levels_by_comp_id.get(mline.competency_id.id, 0))
                    radar_pillars.append(mline.competency_id.pillar or 'core')

        # Fallback / augmentation: include any additional competencies present in the employee's assessment
        if my_asm and my_asm.line_ids:
            for l in my_asm.line_ids:
                if l.competency_id and l.competency_id.name not in radar_labels:
                    radar_labels.append(l.competency_id.name)
                    c_val = assessed_levels_by_comp_id.get(
                        l.competency_id.id,
                        int(l.current_level) if l.current_level and str(l.current_level).isdigit() else (int(round(l.weighted_current_level)) if l.weighted_current_level else 0)
                    )
                    r_val = int(l.required_level) if l.required_level and str(l.required_level).isdigit() else 1
                    radar_assessed.append(c_val)
                    radar_required.append(r_val)
                    radar_pillars.append(l.competency_id.pillar or 'core')

        # Multi-cycle trend history for Employee
        trend_cycles = self.env['competency.assessment.cycle'].sudo().search([], order='id asc', limit=5)
        trend_labels = [c.name for c in trend_cycles]
        trend_values = []
        for c in trend_cycles:
            casm = self.env['competency.assessment'].sudo().search([
                ('employee_id', '=', emp.id if emp else 0),
                ('cycle_id', '=', c.id),
                ('assessment_type', '=', 'self')
            ], limit=1)
            if not casm:
                casm = self.env['competency.assessment'].sudo().search([
                    ('employee_id', '=', emp.id if emp else 0),
                    ('cycle_id', '=', c.id)
                ], limit=1)
            trend_values.append(casm.average_gap if casm else 0.0)

        # Team metrics for Supervisor / Manager
        team_roster = []
        team_avg_gap = 0.0
        if emp:
            subordinates = self.env['hr.employee'].sudo().search([
                '|', ('parent_id', '=', emp.id),
                ('coach_id', '=', emp.id)
            ])
            if subordinates:
                t_lines = self.env['competency.assessment.line'].sudo().search([
                    ('employee_id', 'in', subordinates.ids),
                    ('cycle_id', '=', cycle.id if cycle else 0),
                    ('is_primary_reporting_line', '=', True)
                ])
                t_gaps = [l.gap for l in t_lines if l.gap is not None and ((l.weighted_current_level or 0) > 0 or l.achievement_status)]
                team_avg_gap = round(sum(t_gaps) / len(t_gaps), 2) if t_gaps else 0.0

                # Pre-fetch all assessments and group lines for subordinates to avoid N+1 queries in loop
                all_sub_asms = self.env['competency.assessment'].sudo().search([
                    ('employee_id', 'in', subordinates.ids),
                    ('cycle_id', '=', cycle.id if cycle else 0),
                ])
                sub_asms_map = {}
                for a in all_sub_asms:
                    sub_asms_map.setdefault(a.employee_id.id, []).append(a)

                sub_lines_map = {}
                for l in t_lines:
                    sub_lines_map.setdefault(l.employee_id.id, []).append(l)

                for sub in subordinates:
                    sub_p_lines = sub_lines_map.get(sub.id, [])
                    sub_asms = sub_asms_map.get(sub.id, [])
                    submitted_asms = [a for a in sub_asms if a.state != 'draft']
                    is_sub_fully_assessed = bool(sub_asms and len(submitted_asms) == len(sub_asms))

                    if is_sub_fully_assessed:
                        status_str = _('Fully Assessed (%d/%d raters)') % (len(submitted_asms), len(sub_asms))
                    elif submitted_asms:
                        status_str = _('In Progress (%d/%d raters submitted)') % (len(submitted_asms), len(sub_asms))
                    elif sub_asms:
                        status_str = _('Pending (%d raters assigned)') % len(sub_asms)
                    else:
                        status_str = _('Not Started')

                    top_gaps = sorted(
                        [l for l in sub_p_lines if l.achievement_status == 'below'],
                        key=lambda l: l.gap or 0,
                        reverse=True
                    )[:2]
                    team_roster.append({
                        'id': sub.id,
                        'name': sub.name,
                        'job': sub.job_id.name if sub.job_id else 'N/A',
                        'assessment_id': submitted_asms[0].id if submitted_asms else (sub_p_lines[0].assessment_id.id if sub_p_lines else False),
                        'status': status_str,
                        'top_gaps': ", ".join([l.competency_id.name for l in top_gaps]) if (is_sub_fully_assessed and top_gaps) else ('Fit / Qualified' if is_sub_fully_assessed else ('Awaiting Evaluation' if sub_asms else 'Not Assigned'))
                    })

        # Department Heatmap Data Matrix (aggregated via SQL for high performance)
        heatmap_rows = []
        if persona != 'employee' and has_real_data and fully_assessed_emp_ids:
            dept_extra_filter = ""
            dept_params = [cycle_id_val, emp_ids_tuple]
            if dept_filter_val:
                dept_extra_filter += " AND cal.department_id = %s"
                dept_params.append(dept_filter_val)

            self.env.cr.execute(f"""
                SELECT
                    d.id,
                    d.name,
                    ROUND(AVG(CASE WHEN cal.pillar = 'core' THEN cal.gap END)::numeric, 2) AS core_avg,
                    ROUND(AVG(CASE WHEN cal.pillar = 'leadership' THEN cal.gap END)::numeric, 2) AS lead_avg,
                    ROUND(AVG(CASE WHEN cal.pillar = 'technical' THEN cal.gap END)::numeric, 2) AS tech_avg
                FROM competency_assessment_line cal
                JOIN hr_department d ON cal.department_id = d.id
                WHERE cal.cycle_id = %s
                  AND cal.employee_id IN %s
                  AND cal.is_primary_reporting_line = true
                  AND cal.active = true
                  AND (cal.weighted_current_level > 0 OR cal.achievement_status IS NOT NULL)
                  AND cal.gap IS NOT NULL
                  {dept_extra_filter}
                GROUP BY d.id, d.name
                ORDER BY d.name
                LIMIT 15;
            """, dept_params)
            for d_id, d_name_raw, c_val, l_val, t_val in self.env.cr.fetchall():
                c_val = float(c_val or 0.0)
                l_val = float(l_val or 0.0)
                t_val = float(t_val or 0.0)
                if isinstance(d_name_raw, dict):
                    clean_name = d_name_raw.get(self.env.lang) or d_name_raw.get('en_US') or (next(iter(d_name_raw.values()), '') if d_name_raw else '')
                else:
                    clean_name = str(d_name_raw or '')
                heatmap_rows.append({
                    'dept_id': d_id,
                    'dept_name': html.escape(clean_name),
                    'core': c_val,
                    'leadership': l_val,
                    'technical': t_val,
                    'overall': round((c_val + l_val + t_val) / 3.0, 2),
                })

        return {
            'persona': persona,
            'is_dept_readonly': is_dept_readonly,
            'is_ou_readonly': is_ou_readonly,
            'selected_department_id': int(department_id) if department_id else False,
            'selected_operating_unit_id': int(operating_unit_id) if operating_unit_id else False,
            'all_departments': all_departments,
            'all_operating_units': all_operating_units,
            'fully_assessed_emp_ids': list(fully_assessed_emp_ids),
            'user': {
                'name': user.name,
                'is_admin': is_admin,
                'is_supervisor': is_supervisor,
                'has_subordinates': bool(emp and self.env['hr.employee'].search_count([('parent_id', '=', emp.id)])),
                'employee_name': emp.name if emp else user.name,
                'job_name': (getattr(emp, 'job_position', False) or emp.job_id).name if (emp and (getattr(emp, 'job_position', False) or emp.job_id)) else 'N/A',
            },
            'cycle': {
                'id': cycle.id if cycle else False,
                'name': cycle.name if cycle else 'No Cycle Selected',
                'deadline': str(cycle.assessment_deadline) if cycle and cycle.assessment_deadline else '',
            },
            'active_cycle_info': active_cycle_info,
            'all_cycles': all_cycles,
            'stats': {
                'has_data': has_real_data,
                'bank_avg_gap': bank_avg,
                'below_cnt': below_cnt,
                'meets_cnt': meets_cnt,
                'exceeds_cnt': exceeds_cnt,
                'total_assessments': asms_total,
                'core_avg': core_avg,
                'lead_avg': lead_avg,
                'tech_avg': tech_avg,
                'unmapped_cnt': unmapped_cnt,
                'missing_sups_cnt': missing_sups_cnt,
                'team_avg_gap': team_avg_gap,
                'my_avg_gap': my_asm.average_gap if my_asm else 0.0,
                'my_status': dict(my_asm._fields['state'].selection).get(my_asm.state, 'Not Started') if my_asm else 'Not Started',
                'my_asm_id': my_asm.id if my_asm else False,
            },
            'charts': {
                'tna_donut': {
                    'labels': ['Underqualified (Training Needed)', 'Fit / Qualified', 'Overqualified'],
                    'data': [below_cnt, meets_cnt, exceeds_cnt],
                    'colors': ['#541718', '#726732', '#c17540']
                },
                'pillar_bar': {
                    'labels': ['Core Pillar', 'Leadership Pillar', 'Technical Pillar'],
                    'datasets': [
                        {
                            'label': 'Below Target',
                            'data': [core_below, lead_below, tech_below],
                            'backgroundColor': '#541718',
                        },
                        {
                            'label': 'Meets Target',
                            'data': [core_meets, lead_meets, tech_meets],
                            'backgroundColor': '#726732',
                        },
                        {
                            'label': 'Exceeds Target',
                            'data': [core_exceeds, lead_exceeds, tech_exceeds],
                            'backgroundColor': '#c17540',
                        }
                    ]
                },
                'employee_radar': {
                    # Real per-competency ratings only — never fabricate sample values here.
                    # An empty payload means "no assessment recorded yet"; the widget must show
                    # an explicit empty state rather than invented numbers.
                    'has_data': bool(radar_labels),
                    'labels': radar_labels,
                    'assessed': radar_assessed,
                    'required': radar_required,
                    'pillars': radar_pillars,
                },
                'employee_trend': {
                    'labels': trend_labels,
                    'data': trend_values,
                }
            },
            'team_roster': team_roster,
            'heatmap_rows': heatmap_rows,
        }
