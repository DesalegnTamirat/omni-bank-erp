# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

# BRD FR-REC-018: 5 working-day external application window (flexible)
# BRD FR-REC-019: Auto-close at closing date; HR can manually accept late applications
#                 with valid justification (late_inclusion_allowed + late_inclusion_justification).


class RecruitmentApplicationWindow(models.Model):
    """
    BRD FR-REC-018 / FR-REC-019: Application Window Enforcement.

    Extends the base model defined in recruitment_scoring.py with a convenience
    closing_date field that maps directly to the is_closed flag, aligning with
    the BRD requirement to auto-close vacancies at the specified closing date.
    """
    _inherit = 'recruitment.application.window'

    closing_date = fields.Date(
        string='Closing Date',
        help='BRD FR-REC-019: Vacancy auto-closes at this date. '
             'Applications after this date are rejected unless '
             'HR grants late inclusion with justification.'
    )

    @api.depends('closing_date')
    def _compute_is_closed_from_date(self):
        """BRD FR-REC-019: Auto-close vacancy at specified Closing Date."""
        today = fields.Date.today()
        for rec in self:
            if rec.closing_date and rec.closing_date < today:
                if not rec.is_closed:
                    rec.is_closed = True

    def check_application_allowed_ext(self, application_date=None):
        """
        BRD FR-REC-019: Reject applications after Closing Date unless HR
        has granted late inclusion with a valid justification.
        """
        self.ensure_one()
        today = application_date or fields.Date.today()
        if self.closing_date and today > self.closing_date:
            if not self.late_inclusion_allowed:
                return False, _("Application window closed on %s.") % self.closing_date
        return True, _("Application accepted.")
