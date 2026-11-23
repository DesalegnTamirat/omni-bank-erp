# -*- coding: utf-8 -*-
from odoo import models, api


class EdsHrCompat(models.AbstractModel):
    """Shared compatibility helper for defensive access to external HR and bank fields (B3, D1)."""
    _name = 'eds.hr.compat'
    _description = 'EDS HR and External Module Compatibility Helper'

    @api.model
    def find_employee(self, identifier):
        """Find an employee safely using any configured unique code or name."""
        if not identifier:
            return self.env['hr.employee'].browse()

        identifier = str(identifier).strip()
        Employee = self.env['hr.employee'].sudo()
        emp_fields = Employee._fields

        domain_parts = []
        if 'registration_number' in emp_fields:
            domain_parts.append(('registration_number', '=', identifier))
        if 'identification_id' in emp_fields:
            domain_parts.append(('identification_id', '=', identifier))
        if 'barcode' in emp_fields:
            domain_parts.append(('barcode', '=', identifier))

        # Check by codes first
        if domain_parts:
            domain = ['|'] * (len(domain_parts) - 1) + domain_parts if len(domain_parts) > 1 else domain_parts
            emp = Employee.search(domain, limit=1)
            if emp:
                return emp

        # Fallback to name search
        return Employee.search([('name', '=ilike', identifier)], limit=1)

    @api.model
    def get_employee_operating_unit(self, employee):
        """Safely retrieve employee operating unit without hardcoding specific custom module names."""
        if not employee:
            return False
        employee_sudo = employee.sudo()
        for field_name in ('default_operating_unit_id', 'operating_unit_id'):
            if hasattr(employee_sudo, field_name):
                val = getattr(employee_sudo, field_name)
                if val:
                    return val
        return False

    @api.model
    def get_employee_job(self, employee):
        """Safely retrieve job position (job_id or job_position)."""
        if not employee:
            return False
        employee_sudo = employee.sudo()
        for field_name in ('job_id', 'job_position'):
            if hasattr(employee_sudo, field_name):
                val = getattr(employee_sudo, field_name)
                if val:
                    return val
        return False

    @api.model
    def get_employee_service_start(self, employee):
        """Safely retrieve employment start date."""
        if not employee:
            return False
        employee_sudo = employee.sudo()
        for field_name in ('first_contract_date', 'service_start_date', 'service_hire_date', 'joined_date', 'employment_date', 'hire_date', 'join_date'):
            if hasattr(employee_sudo, field_name):
                val = getattr(employee_sudo, field_name)
                if val:
                    return val
        # A record's creation date does not establish an employee's service tenure.
        # In particular, it must not make a sponsorship applicant eligible.
        return False

    @api.model
    def get_operating_unit_domain(self, departments=None):
        """Return search/view domain for operating.unit based on department(s).

        Hierarchy: Department -> Operating Unit -> Job Position.
        - If no department selected: return [] (all operating units allowed).
        - If department(s) selected: return domain for operating units belonging to those department(s).
        """
        if not departments:
            return []
        dept_ids = departments.ids if hasattr(departments, 'ids') else (
            [departments] if isinstance(departments, int) else list(departments)
        )
        dept_ids = [i for i in dept_ids if i]
        if not dept_ids:
            return []

        ou_model = self.env['operating.unit']
        ou_fields = ou_model._fields
        domain_parts = []

        # 1. Direct link on operating.unit: department (or department_id)
        if 'department' in ou_fields:
            domain_parts.append(('department', 'in', dept_ids))
        if 'department_id' in ou_fields:
            domain_parts.append(('department_id', 'in', dept_ids))

        # 2. Reverse link on hr.department: operating_unit_id
        if 'operating_unit_id' in self.env['hr.department']._fields:
            depts = self.env['hr.department'].browse(dept_ids)
            linked_ou_ids = depts.mapped('operating_unit_id').ids
            if linked_ou_ids:
                domain_parts.append(('id', 'in', linked_ou_ids))

        if len(domain_parts) > 1:
            return ['|'] * (len(domain_parts) - 1) + domain_parts
        elif domain_parts:
            return domain_parts
        return []

    @api.model
    def is_operating_unit_in_departments(self, operating_unit, departments):
        """Check if an operating unit belongs to the given department(s)."""
        if not operating_unit or not departments:
            return True
        ou_domain = self.get_operating_unit_domain(departments)
        if not ou_domain:
            return True
        ou_id = operating_unit.id if hasattr(operating_unit, 'id') else operating_unit
        return bool(self.env['operating.unit'].search_count([('id', '=', ou_id)] + ou_domain))

    @api.model
    def get_department_domain(self, operating_units=None):
        """Return search/view domain for hr.department based on operating unit(s)."""
        if not operating_units:
            return []
        ou_ids = operating_units.ids if hasattr(operating_units, 'ids') else (
            [operating_units] if isinstance(operating_units, int) else list(operating_units)
        )
        ou_ids = [i for i in ou_ids if i]
        if not ou_ids:
            return []
        domain_parts = []
        if 'operating_unit_id' in self.env['hr.department']._fields:
            domain_parts.append(('operating_unit_id', 'in', ou_ids))
        if 'department' in self.env['operating.unit']._fields:
            ous = self.env['operating.unit'].browse(ou_ids)
            dept_ids = ous.mapped('department').ids
            if dept_ids:
                domain_parts.append(('id', 'in', dept_ids))
        if len(domain_parts) > 1:
            return ['|'] * (len(domain_parts) - 1) + domain_parts
        elif domain_parts:
            return domain_parts
        return []

    @api.model
    def get_job_domain(self, departments=None, operating_units=None):
        """Return domain for hr.job restricted to department(s) and/or operating unit(s).

        Hierarchy: Department -> Operating Unit -> Job Position.
        - If operating units are selected:
          Jobs mapped to those operating units via operating.unit.job.position,
          and/or jobs under the department(s) of those operating units / selected departments,
          plus bank-wide jobs (department_id = False).
        - If only department(s) are selected:
          Jobs belonging to those department(s), plus bank-wide jobs (department_id = False).
        - If neither:
          All jobs ([]).
        """
        dept_ids = []
        if departments:
            dept_ids = departments.ids if hasattr(departments, 'ids') else (
                [departments] if isinstance(departments, int) else list(departments)
            )
            dept_ids = [i for i in dept_ids if i]

        ou_ids = []
        if operating_units:
            ou_ids = operating_units.ids if hasattr(operating_units, 'ids') else (
                [operating_units] if isinstance(operating_units, int) else list(operating_units)
            )
            ou_ids = [i for i in ou_ids if i]

        if ou_ids:
            job_ids = []
            if 'operating.unit.job.position' in self.env:
                ou_jobs = self.env['operating.unit.job.position'].search([
                    ('operating_unit_id', 'in', ou_ids)
                ])
                job_ids = ou_jobs.mapped('job_position_id').ids

            ous = self.env['operating.unit'].browse(ou_ids)
            for ou in ous:
                if hasattr(ou, 'department') and ou.department and ou.department.id not in dept_ids:
                    dept_ids.append(ou.department.id)
            if 'operating_unit_id' in self.env['hr.department']._fields:
                linked_depts = self.env['hr.department'].search([('operating_unit_id', 'in', ou_ids)]).ids
                for ld in linked_depts:
                    if ld not in dept_ids:
                        dept_ids.append(ld)

            domain_clauses = []
            if job_ids:
                domain_clauses.append(('id', 'in', job_ids))
            if dept_ids:
                domain_clauses.append(('department_id', 'in', dept_ids))
            domain_clauses.append(('department_id', '=', False))

            if len(domain_clauses) > 1:
                return ['|'] * (len(domain_clauses) - 1) + domain_clauses
            return domain_clauses

        if dept_ids:
            return ['|', ('department_id', 'in', dept_ids), ('department_id', '=', False)]

        return []

    @api.model
    def get_employee_domain(self, department=None, operating_unit=None, job=None):
        """Return domain for hr.employee restricted by department, operating unit, and/or job."""
        domain = []
        emp_fields = self.env['hr.employee']._fields

        if job:
            job_id = job.id if hasattr(job, 'id') else job
            if job_id:
                job_parts = []
                if 'job_id' in emp_fields:
                    job_parts.append(('job_id', '=', job_id))
                if 'job_position' in emp_fields:
                    job_parts.append(('job_position', '=', job_id))
                if len(job_parts) > 1:
                    domain.extend(['|'] * (len(job_parts) - 1) + job_parts)
                elif job_parts:
                    domain.extend(job_parts)

        if department:
            dept_ids = department.ids if hasattr(department, 'ids') else (
                [department] if isinstance(department, int) else list(department)
            )
            dept_ids = [i for i in dept_ids if i]
            if dept_ids:
                domain.append(('department_id', 'in', dept_ids))

        if operating_unit:
            ou_ids = operating_unit.ids if hasattr(operating_unit, 'ids') else (
                [operating_unit] if isinstance(operating_unit, int) else list(operating_unit)
            )
            ou_ids = [i for i in ou_ids if i]
            if ou_ids:
                ou_parts = []
                if 'default_operating_unit_id' in emp_fields:
                    ou_parts.append(('default_operating_unit_id', 'in', ou_ids))
                if 'operating_unit_id' in emp_fields:
                    ou_parts.append(('operating_unit_id', 'in', ou_ids))
                if len(ou_parts) > 1:
                    domain.extend(['|'] * (len(ou_parts) - 1) + ou_parts)
                elif ou_parts:
                    domain.extend(ou_parts)

        return domain

    @api.model
    def get_managed_operating_units(self, user=None):
        """Units led through HR managers or the employee reporting hierarchy."""
        return self.get_managed_training_scope(user=user)[0]

    @api.model
    def get_managed_training_scope(self, user=None):
        """Return the work units and departments an employee can represent.

        Imported HR records often lack unit manager or department links. The
        formal employee.parent_id hierarchy supplies those assignments;
        coaching relationships do not grant management authority.
        """
        user = user or self.env.user
        Employee = self.env['hr.employee'].sudo()
        Unit = self.env['operating.unit'].sudo()
        Department = self.env['hr.department'].sudo()
        employee = Employee.search([('user_id', '=', user.id)], limit=1)
        if not employee:
            return Unit.browse(), Department.browse()

        reports = Employee.search([
            ('id', 'child_of', employee.id), ('id', '!=', employee.id),
            ('active', '=', True),
        ])
        direct_departments = Department.search([('manager_id', '=', employee.id)])
        managed_departments = (Department.search([('id', 'child_of', direct_departments.ids)])
                               if direct_departments else Department.browse())
        managed = Unit.search([('manager_id', '=', employee.id)])
        if managed_departments:
            managed |= Unit.search([('department', 'in', managed_departments.ids)])
            managed |= managed_departments.mapped('operating_unit_id')
            department_staff = Employee.search([
                ('department_id', 'in', managed_departments.ids),
                ('active', '=', True),
            ])
            managed |= department_staff.mapped('default_operating_unit_id')
            if 'operating_unit_id' in Employee._fields:
                managed |= department_staff.mapped('operating_unit_id')
        report_units = reports.mapped('default_operating_unit_id')
        if 'operating_unit_id' in Employee._fields:
            report_units |= reports.mapped('operating_unit_id')
        # A supervisor below another employee in the same unit is not the
        # unit's leader. Explicit unit/department managers remain authorized.
        ancestor = employee.parent_id
        visited_ancestors = set()
        while ancestor and report_units and ancestor.id not in visited_ancestors:
            visited_ancestors.add(ancestor.id)
            ancestor_unit = self.get_employee_operating_unit(ancestor)
            if ancestor_unit:
                report_units -= ancestor_unit
            if 'operating_unit_id' in Employee._fields:
                report_units -= ancestor.operating_unit_id
            ancestor = ancestor.parent_id
        managed |= report_units
        frontier = managed
        while frontier:
            children = Unit.search([('parent_unit', 'in', frontier.ids)]) - managed
            managed |= children
            frontier = children

        managed_departments |= reports.mapped('department_id')
        managed_departments |= managed.mapped('department')
        if managed:
            managed_departments |= Department.search([
                ('operating_unit_id', 'in', managed.ids)])
            own_unit = self.get_employee_operating_unit(employee)
            if employee.department_id and own_unit in managed:
                managed_departments |= employee.department_id
        return managed, managed_departments

    @api.model
    def get_managed_departments(self, user=None):
        return self.get_managed_training_scope(user=user)[1]

    @api.model
    def get_managed_employee_read_domain(self):
        """Permit a leader to choose employees in managed units in the UI."""
        units = self.get_managed_operating_units()
        unit_domain = self.get_employee_domain(operating_unit=units)
        own_employee = [('user_id', '=', self.env.user.id)]
        return ['|'] + own_employee + unit_domain if unit_domain else own_employee

    @api.model
    def get_available_work_units_for_department(self, units, department,
                                                allowed_departments=None):
        """Map a permitted department to permitted units using HR assignments."""
        if not department or not units:
            return units
        # Many2many values on an unsaved Odoo form are NewId records. Search
        # domains need their persisted originals.
        units = units._origin or units
        department = department._origin or department
        if allowed_departments:
            allowed_departments = allowed_departments._origin or allowed_departments
        Unit = self.env['operating.unit'].sudo()
        unit_domain = self.get_operating_unit_domain(departments=department)
        matched = (Unit.search([('id', 'in', units.ids)] + unit_domain)
                   if unit_domain else Unit.browse())
        Employee = self.env['hr.employee'].sudo()
        employees = Employee.search(self.get_employee_domain(
            department=department, operating_unit=units))
        matched |= employees.mapped('default_operating_unit_id') & units
        if 'operating_unit_id' in Employee._fields:
            matched |= employees.mapped('operating_unit_id') & units
        if not matched and allowed_departments and len(allowed_departments) == 1:
            # A legacy unit without a department link still belongs to the
            # leader's one permitted department.
            matched = units
        return matched

    @api.model
    def _register_hook(self):
        super()._register_hook()
        try:
            # 1. Deactivate restrictive record rule on hr.employee that blocks non-managers from reading employees in EDS
            self.env.cr.execute("""
                UPDATE ir_rule
                SET active = false
                WHERE id IN (
                    SELECT res_id FROM ir_model_data
                    WHERE module = 'employee_development_system'
                      AND name = 'rule_eds_manager_work_unit_employee_read'
                );
            """)

            # 2. Clean up res_groups privilege_id so only the 6 core roles
            # (User, Officer, Team Leader, Director, Chief, Admin) show in the UI privilege dropdown.
            self.env.cr.execute("""
                UPDATE res_groups
                SET privilege_id = NULL
                WHERE privilege_id IN (
                    SELECT id FROM res_groups_privilege
                    WHERE category_id IN (
                        SELECT res_id FROM ir_model_data
                        WHERE module = 'employee_development_system'
                          AND name = 'module_category_eds'
                    )
                )
                AND id NOT IN (
                    SELECT res_id FROM ir_model_data
                    WHERE module = 'employee_development_system'
                      AND name IN (
                          'group_eds_employee',
                          'group_eds_officer',
                          'group_eds_team_leader',
                          'group_eds_director',
                          'group_eds_chief',
                          'group_eds_admin'
                      )
                );
            """)

            # 3. Ensure clean role labels for the 6 visible roles
            role_names = {
                'group_eds_employee': 'User',
                'group_eds_officer': 'Officer',
                'group_eds_team_leader': 'Team Leader',
                'group_eds_director': 'Director',
                'group_eds_chief': 'Chief',
                'group_eds_admin': 'Admin',
            }
            for xml_name, label in role_names.items():
                self.env.cr.execute("""
                    UPDATE res_groups
                    SET name = jsonb_set(COALESCE(name, '{}'::jsonb), '{en_US}', to_jsonb(%s::text))
                    WHERE id = (
                        SELECT res_id FROM ir_model_data
                        WHERE module = 'employee_development_system' AND name = %s
                    );
                """, (label, xml_name))
        except Exception:
            pass
