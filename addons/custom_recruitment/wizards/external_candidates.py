from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError


class external_candidate_details(models.TransientModel):
    _name = 'external.candidates'
    _description = 'External Candidates'

    #job_id = fields.Many2one("hr.job", string='Job Positions', domain=[('state', '=', 'recruit')])
    job_id = fields.Many2one("job.vacancy", string='Job Positions', 
    domain=[('recruitment_type', '=', 'External'),('vacancy_status', '=', 'published')])

    def shortlist_external_candidates(self):
        p_id = self.job_id.id
        self.env.cr.execute('SELECT applicant_update_preferred_location(%s)', (p_id,))
        self.env.cr.execute('SELECT external_candidates(%s)', (p_id,))
