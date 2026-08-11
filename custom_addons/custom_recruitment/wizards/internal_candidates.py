from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError
from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError

class internal_candidate_details(models.TransientModel):
    _name = 'internal.candidates'
    _description = 'Internal Candidates'


    #job_id = fields.Many2one("hr.job", string='Job Positions', domain=[('state', '=', 'recruit')])
    job_id = fields.Many2one(
        "job.vacancy",
        string='Job Positions',
        domain=[
            '&',
            '|', ('reference', '=like', 'BB/INT/%'), ('reference', '=like', 'BB/LAT/%'),
            ('vacancy_status', '=', 'published')
        ]
    )

    def shortlist_internal_candidates(self):
        # Validate using reference prefix for internal vacancies (INT or LAT)
        if not self.job_id.reference or not (self.job_id.reference.startswith('BB/INT/') or self.job_id.reference.startswith('BB/LAT/')):
            raise UserError(_(
                "Please select an internal vacancy (reference starting with 'BB/INT/' or 'BB/LAT/'). "
                "Use the external shortlist wizard for external vacancies."
            ))
        p_id = self.job_id.id
        # Ensure vacancy is marked as both internal and external for 'both' type shortlisting
        self.job_id.with_context(skip_lock_check=True).write({
            'sourcing_type': 'both',
            'recruitment_type': 'Internal',
        })

        # Sync recruitment records (creates both internal and external records if missing)
        self.job_id._sync_published_vacancy_records
        # Run the internal shortlist stored procedure
        self.env.cr.execute('SELECT public.internal_candidates(%s)', (p_id,))

