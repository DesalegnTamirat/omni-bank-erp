# -*- coding: utf-8 -*-
from odoo import fields, models, api


class SuccessionGovernancePolicy(models.Model):
    _name = 'succession.governance.policy'
    _description = 'Succession Governance Policy'

    name = fields.Char(default='Global Succession Policy', required=True, index=True)

    @api.model
    def get_policy(self):
        policy = self.sudo().search([], limit=1)
        ready_now = self.env['succession.readiness.level'].sudo().search([
            ('name', 'ilike', 'Ready Now')
        ], order='sequence asc', limit=1)
        if not policy:
            policy = self.sudo().create({
                'name': 'Global Succession Policy',
                'deployment_readiness_level_id': ready_now.id if ready_now else False,
            })
        elif not policy.deployment_readiness_level_id and ready_now:
            policy.sudo().write({'deployment_readiness_level_id': ready_now.id})
        return policy

    def write(self, vals):
        res = super().write(vals)
        if 'deployment_readiness_level_id' in vals:
            target_level = self.deployment_readiness_level_id
            target_seq = target_level.sequence if target_level else 10
            for lvl in self.env['succession.readiness.level'].search([]):
                lvl.write({'is_ready_for_deployment': bool(lvl.sequence and lvl.sequence <= target_seq)})
        return res

    # SUCCESSION GOVERNANCE RULES
    deployment_readiness_level_id = fields.Many2one(
        'succession.readiness.level', domain="[('active', '=', True)]",
        string='Minimum Readiness for Immediate Deployment',
        index=True,
        help="The minimum readiness level an employee must attain to be eligible for immediate deployment/placement into a Critical Position. Candidates with lower readiness must complete a Development Plan (IDP)."
    )
    succ_min_successors_global = fields.Integer(
        string='Minimum Successors Required (Global Default)',
        default=2,
        help="The minimum number of approved successor candidates required for "
             "any Critical Position before its succession risk can drop below "
             "'High'. This is the bank-wide default; each position can override "
             "it individually. Best practice: 2-3 successors."
    )
    succ_require_spmc_approval = fields.Boolean(
        string='Require SPMC Approval for Critical Positions',
        default=True,
        help="When enabled, all Critical Positions must pass through the full "
             "PPDD to SPMC governance workflow before candidates can be formally "
             "nominated. Disable only during initial system setup or data migration."
    )

    invitation_expiry_days = fields.Integer(
        string='Invitation Expiration Window (Days)',
        default=3,
        help="Number of days an employee has to accept or decline a succession invitation before it expires (e.g. 3 or 4 days). After expiration, status becomes Expired and acceptance is blocked."
    )

    # READINESS & PIPELINE RULES
    succ_readiness_review_months = fields.Integer(
        string='Readiness Review Reminder (Months)',
        default=6,
        help="Number of months between mandatory readiness review dates for each "
             "approved candidate. After this period, the candidate's readiness "
             "level will be flagged for update by PPDD. Recommended: 6 months."
    )
    succ_idp_mandatory = fields.Boolean(
        string='Require Successor Development Plan Before Candidate Approval',
        default=True,
        help="When enabled, a Successor Development Plan must be created "
             "for a candidate before SPMC can mark them as 'Approved'. Enforces "
             "best-practice development governance."
    )
    succ_career_discussion_mandatory = fields.Boolean(
        string='Require Career Discussion for Development Plan (IDP)',
        default=True,
        help="When enabled, a confirmed Career Discussion between the Line Manager "
             "and employee is required after the Successor Development Plan "
             "is created, before the plan can be activated. Ensures alignment and "
             "mutual commitment to the development roadmap."
    )
    succ_idp_max_duration_months = fields.Integer(
        string='Max Plan Duration (Months)',
        default=12,
        help='Maximum duration in months for a successor development plan.'
    )
    succ_min_idp_progress_for_pool = fields.Float(
        string='Min Plan Progress to Enter Pool (%)',
        default=70.0,
        help='Minimum development plan progress percentage required to enter the active pool.'
    )
    succ_auto_match_min_score = fields.Float(
        string='Auto-Match Minimum Eligibility Score (%)',
        default=30.0,
        help="Minimum competency match percentage for a candidate to appear."
    )

    # ALERTS & NOTIFICATIONS
    succ_risk_review_months = fields.Integer(
        string='Succession Risk Review Cycle (Months)',
        default=6,
        help="How often (in months) the system should automatically trigger a "
             "risk recalculation and alert PPDD to review critical positions. "
             "Recommended: every 6 months (twice a year)."
    )
    succ_alert_critical_no_successors = fields.Boolean(
        string='Alert PPDD When Critical Position Has No Successors',
        default=True,
        help="When enabled, the system will send an email/internal notification "
             "to the PPDD team whenever an Approved Critical Position has zero "
             "nominated candidates. Triggered weekly by the scheduled cron job."
    )
    succ_alert_idp_overdue = fields.Boolean(
        string='Alert When Development Plan Activities Are Overdue',
        default=True,
        help="When enabled, email notifications are sent to the responsible "
             "manager and PPDD when a Succession Development Plan activity "
             "passes its target completion date without being marked done."
    )
    succ_alert_readiness_expiry = fields.Boolean(
        string='Alert When Readiness Review Is Overdue',
        default=True,
        help="Triggers an alert when a candidate's last readiness assessment "
             "exceeds the configured Readiness Review Cycle without update. "
             "Ensures the pipeline data remains current and reliable."
    )

    # DEVELOPMENT PLAN PRIORITIZATION & URGENCY (Configurable Rules)
    urgency_rule_ids = fields.One2many(
        'succession.development.urgency.level',
        'policy_id',
        string='Urgency Level Rules',
        help='Flexible score ranges (1-10) and their corresponding Urgency Levels.'
    )

