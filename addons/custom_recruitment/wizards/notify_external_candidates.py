from datetime import datetime
from dateutil import relativedelta

from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError


class notify_external_candidates(models.TransientModel):
    _name = 'notify.external.candidates'
    _description = 'Notify External Candidates'

    # plan_version = fields.Many2one("manpower.plan", string='Manpower Plan Version', domain=[('status','=','current')])
    hr_job = fields.Many2one("hr.job", string='Applied Position')

    def notify_external_candidates(self):
        p_id = self.hr_job.id
        print ("Job ID : ", p_id)
        # cr = self.env.cr
        # self.env.cr.execute('SELECT internal_applicant(%s)', (p_id,))
        # cr.commit()
        # print("Employees Notified")
