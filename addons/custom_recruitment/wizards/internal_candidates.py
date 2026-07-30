from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class internal_candidate_details(models.TransientModel):
    _name = 'internal.candidates'
    _description = 'Internal Candidates'


    #job_id = fields.Many2one("hr.job", string='Job Positions', domain=[('state', '=', 'recruit')])
    job_id = fields.Many2one("job.vacancy", string='Job Positions', domain=[('recruitment_type', '=', 'Internal')])

    def shortlist_internal_candidates(self):
        p_id = self.job_id.id
        self.env.cr.execute('SELECT internal_candidates(%s)', (p_id,))

