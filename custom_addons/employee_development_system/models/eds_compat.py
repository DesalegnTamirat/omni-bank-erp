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
        Employee = self.env['hr.employee']
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
        for field_name in ('default_operating_unit_id', 'operating_unit_id'):
            if hasattr(employee, field_name):
                val = getattr(employee, field_name)
                if val:
                    return val
        return False

    @api.model
    def get_employee_job(self, employee):
        """Safely retrieve job position (job_id or job_position)."""
        if not employee:
            return False
        for field_name in ('job_id', 'job_position'):
            if hasattr(employee, field_name):
                val = getattr(employee, field_name)
                if val:
                    return val
        return False

    @api.model
    def get_employee_service_start(self, employee):
        """Safely retrieve employment start date."""
        if not employee:
            return False
        for field_name in ('first_contract_date', 'hire_date', 'join_date'):
            if hasattr(employee, field_name):
                val = getattr(employee, field_name)
                if val:
                    return val
        return employee.create_date.date() if employee.create_date else False
