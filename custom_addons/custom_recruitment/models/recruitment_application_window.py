# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class RecruitmentApplicationWindow(models.Model):

    _inherit = 'recruitment.application.window'

    closing_date = fields.Date(
        string='Closing Date',
        help='BRD FR-REC-019: Vacancy auto-closes at this date. '
             'Applications after this date are rejected unless '
             'HR grants late inclusion with justification.'
    )

    @api.depends('closing_date')
    def _compute_is_closed_from_date(self):
        today = fields.Date.today()
        for rec in self:
            if rec.closing_date and rec.closing_date < today:
                if not rec.is_closed:
                    rec.is_closed = True

    def check_application_allowed_ext(self, application_date=None):

        self.ensure_one()
        today = application_date or fields.Date.today()
        if self.closing_date and today > self.closing_date:
            if not self.late_inclusion_allowed:
                return False, _("Application window closed on %s.") % self.closing_date
        return True, _("Application accepted.")
