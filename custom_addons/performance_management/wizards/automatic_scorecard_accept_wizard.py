import datetime
from odoo import api, fields, models
from odoo.exceptions import UserError


class AutomaticScorecardAcceptWizard(models.TransientModel):
    _name = 'automatic.scorecard.accept.wizard'
    _description = 'Automatic Scorecard Acceptance Wizard'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('result', 'Result'),
    ], default='draft', string='Status')

    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        required=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period',
        required=True,
    )
    tier = fields.Selection([
        ('all', 'All Tiers (Tier 2 & Tier 3)'),
        ('tier2', 'Tier 2 (Work Units)'),
        ('tier3', 'Tier 3 (Employee)'),
    ], string='Tier', required=True, default='all',
       help='Select which tier of scorecards to automatically accept.')

    accept_by_deadline = fields.Date(
        string='Accept By Deadline',
        required=True,
        default=fields.Date.context_today,
        help='Scorecards in Notified status with an Accept By deadline on or before this date will be auto-accepted.',
    )
    cutoff_date = fields.Date(
        string='Accept By Deadline',
        related='accept_by_deadline',
        readonly=False,
        store=True,
    )

    overdue_t2_count = fields.Integer(
        string='Overdue Tier 2 Scorecards',
        compute='_compute_overdue_counts',
    )
    overdue_t3_count = fields.Integer(
        string='Overdue Tier 3 Scorecards',
        compute='_compute_overdue_counts',
    )
    total_overdue_count = fields.Integer(
        string='Total Overdue Scorecards',
        compute='_compute_overdue_counts',
    )

    # Result state tracking
    accepted_t2_count = fields.Integer(string='Accepted Tier 2 Count', default=0)
    accepted_t3_count = fields.Integer(string='Accepted Tier 3 Count', default=0)
    summary_html = fields.Html(string='Summary', sanitize=False)
    accepted_t2_ids = fields.Many2many('t2.scorecard', 'wizard_t2_auto_accept_rel', string='Auto-Accepted Tier 2')
    accepted_t3_ids = fields.Many2many('t3.scorecard', 'wizard_t3_auto_accept_rel', string='Auto-Accepted Tier 3')

    @api.depends('fiscal_year_id', 'appraisal_period_id', 'accept_by_deadline', 'cutoff_date', 'tier')
    def _compute_overdue_counts(self):
        for rec in self:
            deadline = rec.accept_by_deadline or rec.cutoff_date
            if not rec.fiscal_year_id or not rec.appraisal_period_id or not deadline:
                rec.overdue_t2_count = 0
                rec.overdue_t3_count = 0
                rec.total_overdue_count = 0
                continue

            base_domain = [
                ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                ('appraisal_period_id', '=', rec.appraisal_period_id.id),
                ('state', '=', 'notified'),
                ('accept_by', '<=', deadline),
            ]

            t2 = self.env['t2.scorecard'].search_count(base_domain) if rec.tier in ('all', 'tier2') else 0
            t3 = self.env['t3.scorecard'].search_count(base_domain) if rec.tier in ('all', 'tier3') else 0

            rec.overdue_t2_count = t2
            rec.overdue_t3_count = t3
            rec.total_overdue_count = t2 + t3

    def action_auto_accept(self):
        self.ensure_one()
        deadline = self.accept_by_deadline or self.cutoff_date
        if not self.fiscal_year_id or not self.appraisal_period_id:
            raise UserError('Please select a Fiscal Year and Appraisal Period.')
        if not deadline:
            raise UserError('Please specify an Accept By Deadline.')

        base_domain = [
            ('fiscal_year_id', '=', self.fiscal_year_id.id),
            ('appraisal_period_id', '=', self.appraisal_period_id.id),
            ('state', '=', 'notified'),
            ('accept_by', '<=', deadline),
        ]

        t2_records = self.env['t2.scorecard']
        t3_records = self.env['t3.scorecard']

        if self.tier in ('all', 'tier2'):
            t2_records = self.env['t2.scorecard'].search(base_domain)
        if self.tier in ('all', 'tier3'):
            t3_records = self.env['t3.scorecard'].search(base_domain)

        total_found = len(t2_records) + len(t3_records)
        if total_found == 0:
            raise UserError(
                f"No overdue notified scorecards found for Fiscal Year '{self.fiscal_year_id.name}', "
                f"Period '{self.appraisal_period_id.name}', and Accept By Deadline '{deadline}'."
            )

        # Trigger auto-acceptance
        if t2_records:
            t2_records.action_auto_accept()
        if t3_records:
            t3_records.action_auto_accept()

        summary_cards = f"""
        <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <div style="flex: 1; padding: 14px; background: #f5f3ff; border: 1.5px solid #c4b5fd; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; font-weight: 700; color: #6d28d9; text-transform: uppercase; letter-spacing: 0.5px;">Tier 2 (Work Units)</div>
                <div style="font-size: 26px; font-weight: 800; color: #5b21b6; line-height: 1.2; margin-top: 2px;">
                    {len(t2_records)} <span style="font-size: 13px; font-weight: 600; color: #6b7280;">Auto-Accepted</span>
                </div>
            </div>
            <div style="flex: 1; padding: 14px; background: #fdf4ff; border: 1.5px solid #f0abfc; border-radius: 8px; text-align: center;">
                <div style="font-size: 11px; font-weight: 700; color: #a21caf; text-transform: uppercase; letter-spacing: 0.5px;">Tier 3 (Employees)</div>
                <div style="font-size: 26px; font-weight: 800; color: #86198f; line-height: 1.2; margin-top: 2px;">
                    {len(t3_records)} <span style="font-size: 13px; font-weight: 600; color: #6b7280;">Auto-Accepted</span>
                </div>
            </div>
        </div>
        <div class="alert alert-success d-flex align-items-center" role="alert">
            <i class="fa fa-check-circle fa-2x me-3 text-success"/>
            <div>
                <strong>{total_found}</strong> scorecard(s) have been successfully transitioned from <strong>Notified</strong> to <strong>Auto Accepted</strong> by the system.
            </div>
        </div>
        """

        self.write({
            'state': 'result',
            'accepted_t2_count': len(t2_records),
            'accepted_t3_count': len(t3_records),
            'summary_html': summary_cards,
            'accepted_t2_ids': [(6, 0, t2_records.ids)],
            'accepted_t3_ids': [(6, 0, t3_records.ids)],
        })

        return {
            'name': f"Automatic Acceptance Results ({total_found} Accepted)",
            'type': 'ir.actions.act_window',
            'res_model': 'automatic.scorecard.accept.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_t2(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id('performance_management.action_t2_scorecard')
        except Exception:
            action = {'type': 'ir.actions.act_window', 'res_model': 't2.scorecard'}
        action['name'] = f"Auto-Accepted Tier 2 Scorecards ({self.accepted_t2_count})"
        action['domain'] = [('id', 'in', self.accepted_t2_ids.ids)]
        action['views'] = [(False, 'list'), (False, 'form')]
        action['view_mode'] = 'list,form'
        action['target'] = 'current'
        return action

    def action_view_t3(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id('performance_management.action_t3_scorecard')
        except Exception:
            action = {'type': 'ir.actions.act_window', 'res_model': 't3.scorecard'}
        action['name'] = f"Auto-Accepted Tier 3 Scorecards ({self.accepted_t3_count})"
        action['domain'] = [('id', 'in', self.accepted_t3_ids.ids)]
        action['views'] = [(False, 'list'), (False, 'form')]
        action['view_mode'] = 'list,form'
        action['target'] = 'current'
        return action
