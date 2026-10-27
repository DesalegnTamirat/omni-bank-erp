"""Keep employee-scoped access rules current after HR assignment changes."""

from odoo import models


class IrRule(models.Model):
    _inherit = 'ir.rule'

    def _compute_domain_context_values(self):
        # KMS and LMS rules use the current employee's department, branch, job,
        # and grade. Odoo caches evaluated rule domains by user and context;
        # these values must participate in the key when HR changes them.
        yield from super()._compute_domain_context_values()
        employee = self.env.user.sudo().employee_id
        yield employee.id
        yield employee.department_id.id
        yield employee.default_operating_unit_id.id
        yield employee.job_id.id
        yield employee.job_id.grade.id
