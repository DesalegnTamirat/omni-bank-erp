# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    allowed_role_mapping_job_ids = fields.Many2many(
        'hr.job',
        string='Allowed Role Mapping Job Positions',
        compute='_compute_allowed_role_mapping_job_ids',
        compute_sudo=True,
    )

    team_employee_ids = fields.Many2many(
        'hr.employee',
        string='Team Employees',
        compute='_compute_team_employee_ids',
        compute_sudo=True,
    )

    @api.depends('employee_id', 'employee_id.coach_id', 'employee_id.parent_id')
    def _compute_team_employee_ids(self):
        emp_ids = self.mapped('employee_id').ids
        if not emp_ids:
            self.team_employee_ids = self.env['hr.employee']
            return
        all_subs = self.env['hr.employee'].sudo().search([
            '|', ('coach_id', 'in', emp_ids), ('parent_id', 'in', emp_ids)
        ])
        sub_by_emp = {}
        for sub in all_subs:
            if sub.coach_id and sub.coach_id.id in emp_ids:
                sub_by_emp.setdefault(sub.coach_id.id, self.env['hr.employee'])
                sub_by_emp[sub.coach_id.id] |= sub
            if sub.parent_id and sub.parent_id.id in emp_ids:
                sub_by_emp.setdefault(sub.parent_id.id, self.env['hr.employee'])
                sub_by_emp[sub.parent_id.id] |= sub
        for user in self:
            emp = user.employee_id
            if emp:
                user.team_employee_ids = emp | sub_by_emp.get(emp.id, self.env['hr.employee'])
            else:
                user.team_employee_ids = self.env['hr.employee']

    @api.depends('employee_id', 'employee_id.job_id', 'employee_id.department_id')
    def _compute_allowed_role_mapping_job_ids(self):
        for user in self:
            user.allowed_role_mapping_job_ids = user._get_allowed_role_mapping_jobs()

    def _get_allowed_role_mapping_jobs(self):
        """Calculates allowed job positions for Role-Competency Mapping visibility:
        1. Competency Administrator / Officer: All job positions across the bank.
        2. Department Leader: All job positions in managed department(s) and sub-departments.
        3. Operating Unit Leader: All job positions in managed Operating Unit(s).
        4. Coach / Supervisor: Own job position + all positions of direct team members.
        5. Regular Employee: Own job position only.
        """
        self.ensure_one()

        # 1. Admin / HR Officer: Bank-wide access is handled via [(1, '=', 1)] record rules.
        # Returning an empty recordset avoids unnecessarily querying all jobs in the database.
        if (self._is_admin() or 
            self.has_group('competency_management.group_competency_officer') or 
            self.has_group('competency_management.group_competency_admin')):
            return self.env['hr.job']

        emp = self.employee_id
        if not emp:
            return self.env['hr.job']

        allowed_job_ids = set()

        # Own job position is always visible
        own_pos = getattr(emp, 'job_position', False)
        if own_pos:
            allowed_job_ids.add(own_pos.id)
        if emp.job_id:
            allowed_job_ids.add(emp.job_id.id)

        # 2. Department Leader: All positions in managed department(s) and sub-departments
        managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
        if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.id == emp.id:
            managed_depts |= emp.department_id

        if managed_depts:
            all_depts = self.env['hr.department'].sudo().search([('id', 'child_of', managed_depts.ids)])
            dept_jobs = self.env['hr.job'].sudo().search([('department_id', 'in', all_depts.ids)])
            allowed_job_ids.update(dept_jobs.ids)
            dept_emp_jobs = self.env['hr.employee'].sudo().search([('department_id', 'in', all_depts.ids)]).mapped('job_id')
            allowed_job_ids.update(dept_emp_jobs.ids)

        # 3. Operating Unit Leader: All positions in managed Operating Unit(s)
        managed_ous = self.env['operating.unit'].sudo().search([('manager_id', '=', emp.id)])
        if emp.operating_unit_id and getattr(emp.operating_unit_id, 'manager_id', False) and emp.operating_unit_id.manager_id.id == emp.id:
            managed_ous |= emp.operating_unit_id
        if emp.default_operating_unit_id and getattr(emp.default_operating_unit_id, 'manager_id', False) and emp.default_operating_unit_id.manager_id.id == emp.id:
            managed_ous |= emp.default_operating_unit_id

        # Also check if user has an explicit Operating Unit manager group
        user_group_names = [g.name for g in self.group_ids]
        is_ou_manager = bool(managed_ous) or any(g in user_group_names for g in ['Manager of Operating Units', 'Workunit Manager'])
        if is_ou_manager:
            ou_targets = managed_ous or getattr(self, 'assigned_operating_unit_ids', self.env['operating.unit'])
            if ou_targets:
                ou_emps = self.env['hr.employee'].sudo().search([
                    '|', ('default_operating_unit_id', 'in', ou_targets.ids),
                         ('operating_unit_id', 'in', ou_targets.ids)
                ])
                allowed_job_ids.update(ou_emps.mapped('job_id').ids)
                if 'operating.unit.job.position' in self.env:
                    ou_positions = self.env['operating.unit.job.position'].sudo().search([('operating_unit_id', 'in', ou_targets.ids)])
                    allowed_job_ids.update(ou_positions.mapped('job_position_id').ids)
                ou_mappings = self.env['competency.role.mapping'].sudo().search([
                    ('is_operating_unit_specific', '=', True),
                    ('operating_unit_ids', 'in', ou_targets.ids)
                ])
                allowed_job_ids.update(ou_mappings.mapped('job_position_id').ids)

        # 4. Coach / Supervisor: Direct reports and coachees
        team_emps = emp.child_ids | self.env['hr.employee'].sudo().search([('coach_id', '=', emp.id)])
        if team_emps:
            allowed_job_ids.update(team_emps.mapped('job_id').ids)

        # 5. Regular Employee: Falls through with emp.job_id only

        return self.env['hr.job'].sudo().browse(list(allowed_job_ids))

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        self._sync_supervisor_group(users)
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'employee_id' in vals or 'employee_ids' in vals:
            self._sync_supervisor_group(self)
        return res

    @api.model
    def _sync_supervisor_group(self, users):
        sup_group = self.env.ref('competency_management.group_competency_supervisor', raise_if_not_found=False)
        if not sup_group or not users:
            return
        emp_ids = [u.employee_id.id for u in users if u.employee_id]
        if not emp_ids:
            return
        coaches_and_parents = self.env['hr.employee'].sudo().search([
            ('active', '=', True),
            '|', ('coach_id', 'in', emp_ids), ('parent_id', 'in', emp_ids)
        ])
        supervisor_emp_ids = set(coaches_and_parents.mapped('coach_id').ids + coaches_and_parents.mapped('parent_id').ids)
        for user in users:
            if user.employee_id and user.employee_id.id in supervisor_emp_ids:
                user_groups = user.group_ids if 'group_ids' in user._fields else getattr(user, 'groups_id', self.env['res.groups'])
                if sup_group not in user_groups:
                    field_name = 'group_ids' if 'group_ids' in user._fields else 'groups_id'
                    user.sudo().write({field_name: [(4, sup_group.id)]})

