from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import datetime
from .clean_utils import clean_job_position_name

class HrAllocations(models.Model):
    _inherit = 'hr.leave.allocation'

    employee_idnfctn = fields.Char("Emp Id", related="employee_id.employee_identification")


class HrJob(models.Model):
    _inherit = 'hr.job'

    job_description = fields.Text(string="Job  Description")

    def _compute_display_name(self):
        super()._compute_display_name()
        for rec in self:
            rec.display_name = clean_job_position_name(rec.display_name or rec.name)
