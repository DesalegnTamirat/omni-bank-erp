# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class HrRecruitmentPolicy(models.Model):
    _name = 'hr.recruitment.policy'
    _description = 'HR Policies Configuration'
    _order = 'id desc'

    name = fields.Char(string="Policy Name", default="Bank Central HR Policy", required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)

    # ── Left Column: Tenure & Discipline Criteria ───────────────────────
    minimum_number_years_in_company = fields.Integer(
        string="Minimum Number of Years in the Company",
        default=1,
        help="Minimum service years required in the Bank for internal transfers or promotions."
    )
    current_location_exp = fields.Float(
        string="Current Location Experience",
        default=1.0,
        help="Minimum experience in current location/branch required."
    )
    no_of_months_since_last_written_notice = fields.Integer(
        string="No of Months since last Written notice",
        default=12,
        help="Minimum months required since the last written warning or disciplinary notice."
    )
    no_of_months_since_last_promotion = fields.Integer(
        string="No of Months since last Promotion",
        default=12,
        help="Minimum months required since the employee's last promotion."
    )
    minimum_pms_score = fields.Float(
        string="Minimum PMS Score",
        default=75.0,
        help="Minimum mandatory performance evaluation score threshold (percentage)."
    )
    demoted_employee = fields.Boolean(
        string="Demoted Employee",
        default=False,
        help="Policy flag regarding demoted employees."
    )
    promotion_revoked = fields.Boolean(
        string="Promotion Revoked",
        default=False,
        help="Policy flag regarding revoked promotions."
    )

    # ── Right Column: Weightage & Applicant Settings ─────────────────────
    weightage_written_exam = fields.Float(
        string="Weightage Written Exam",
        default=0.0,
        help="Standard evaluation weightage allocated for written exams."
    )
    weightage_interview = fields.Float(
        string="Weightage Interview",
        default=0.0,
        help="Standard evaluation weightage allocated for interviews."
    )
    weightage_pms = fields.Float(
        string="Weightage PMS",
        default=0.0,
        help="Standard evaluation weightage allocated for Performance Management (PMS)."
    )
    non_experienced_applicant = fields.Boolean(
        string="Non Experienced Applicant",
        default=False,
        help="Policy flag indicating whether non-experienced applicants are permitted."
    )

    def _sync_to_job_positions(self):
        """Pushes central policy settings to all hr.job records."""
        policy_fields = [
            'minimum_number_years_in_company',
            'current_location_exp',
            'no_of_months_since_last_written_notice',
            'no_of_months_since_last_promotion',
            'minimum_pms_score',
            'demoted_employee',
            'promotion_revoked',
            'weightage_written_exam',
            'weightage_interview',
            'weightage_pms',
            'non_experienced_applicant',
        ]
        HrJob = self.env['hr.job'].sudo()
        for policy in self:
            vals = {f: policy[f] for f in policy_fields if f in policy._fields and f in HrJob._fields}
            if vals:
                try:
                    jobs = HrJob.search([])
                    if jobs:
                        jobs.write(vals)
                        _logger.info("Synchronized HR Policy '%s' to %d Job Positions.", policy.name, len(jobs))
                except Exception as e:
                    _logger.warning("Could not sync HR Policy to job positions: %s", e)

    def action_sync_to_all_jobs(self):
        """Manual button to synchronize this policy across all Job Positions."""
        self.ensure_one()
        self._sync_to_job_positions()
        job_count = self.env['hr.job'].search_count([])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("HR Policies Applied"),
                'message': _("Successfully synchronized HR Policy '%s' to all %d Job Positions.") % (self.name, job_count),
                'sticky': False,
                'type': 'success',
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_to_job_positions()
        return records

    def write(self, vals):
        res = super().write(vals)
        policy_fields = {
            'minimum_number_years_in_company',
            'current_location_exp',
            'no_of_months_since_last_written_notice',
            'no_of_months_since_last_promotion',
            'minimum_pms_score',
            'demoted_employee',
            'promotion_revoked',
            'weightage_written_exam',
            'weightage_interview',
            'weightage_pms',
            'non_experienced_applicant',
        }
        if any(f in vals for f in policy_fields):
            self._sync_to_job_positions()
        return res


class HrJobPolicySync(models.Model):
    _inherit = 'hr.job'

    @api.model_create_multi
    def create(self, vals_list):
        """When a new Job Position is created, auto-populate policy values from active HR Policies."""
        policy = self.env['hr.recruitment.policy'].sudo().search([('active', '=', True)], limit=1)
        if policy:
            policy_fields = [
                'minimum_number_years_in_company',
                'current_location_exp',
                'no_of_months_since_last_written_notice',
                'no_of_months_since_last_promotion',
                'minimum_pms_score',
                'demoted_employee',
                'promotion_revoked',
                'weightage_written_exam',
                'weightage_interview',
                'weightage_pms',
                'non_experienced_applicant',
            ]
            for vals in vals_list:
                for f in policy_fields:
                    if f not in vals and hasattr(policy, f):
                        vals[f] = getattr(policy, f)
        return super().create(vals_list)

