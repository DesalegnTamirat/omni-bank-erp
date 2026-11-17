# -*- coding: utf-8 -*-
from odoo import api, models


class HrEmployeeScopeLabel(models.Model):
    _inherit = 'hr.employee'

    @api.depends_context('resl_show_ou')
    def _compute_display_name(self):
        super()._compute_display_name()
        if not self.env.context.get('resl_show_ou'):
            return
        for emp in self.sudo():
            bits = [b for b in (emp.job_title or emp.job_id.name,
                                emp.default_operating_unit_id.name) if b]
            if bits:
                emp.display_name = "%s (%s)" % (emp.display_name, ' - '.join(bits))
