from odoo import api, fields, models
from odoo.exceptions import ValidationError
from datetime import datetime

class HrAllocations(models.Model):
    _inherit = 'hr.leave.allocation'

    employee_idnfctn = fields.Char("Emp Id", related="employee_id.employee_identification")


class HrJob(models.Model):
    _inherit = 'hr.job'

    job_description = fields.Text(string="Job Description")



