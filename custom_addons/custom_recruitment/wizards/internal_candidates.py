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
        string='Vacancy Reference',
        domain=[
            '|', ('sourcing_type', 'in', ['internal', 'both']),
            '|', ('reference', '=like', '%INT%'), ('reference', '=like', '%LAT%')
        ]
    )

    def shortlist_internal_candidates(self):
        if not self.job_id:
            raise UserError(_("Please select a vacancy."))
        ref = self.job_id.reference or ''
        is_internal = self.job_id.sourcing_type in ('internal', 'both') or 'INT' in ref.upper() or 'LAT' in ref.upper()
        if not is_internal:
            raise UserError(_(
                "Please select an internal vacancy. Use the external shortlist wizard for external vacancies."
            ))
        p_id = self.job_id.id
        # Ensure vacancy is marked as both internal and external for 'both' type shortlisting
        self.job_id.with_context(skip_lock_check=True).write({
            'sourcing_type': 'both',
            'recruitment_type': 'Internal',
        })

        # Sync recruitment records (creates both internal and external records if missing)
        self.job_id._sync_published_vacancy_records()
        # Run the internal shortlist stored procedure
        self.env.cr.execute('SELECT public.internal_candidates(%s)', (p_id,))
        
        # Invalidate ORM cache so raw SQL modifications are immediately loaded in the Odoo UI
        self.env.invalidate_all()

        # Find the internal recruitment process record for this vacancy
        int_rec = self.env['employee.recruitment.internal'].search([
            '|', ('vacancy_id', '=', self.job_id.id), ('vacancy_reference', '=', self.job_id.reference)
        ], limit=1)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Recruitment Process'),
            'res_model': 'employee.recruitment.internal',
            'res_id': int_rec.id if int_rec else False,
            'view_mode': 'form' if int_rec else 'list',
            'target': 'current',
        }

