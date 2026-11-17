import datetime
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AutomaticAppraisalNotifyWizard(models.TransientModel):
    _name = 'automatic.appraisal.notify.wizard'
    _description = 'Automatic Appraisal Notify Wizard'

    state = fields.Selection([
        ('draft', 'Draft'),
        ('result', 'Result'),
    ], default='draft', string='Status')

    planning_name = fields.Many2one(
        'corporate.scorecard',
        string='Planning Name',
        required=True,
        domain="[('state', '!=', 'cancelled')]",
        help='Select the Corporate Scorecard planning cycle.',
    )
    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        compute='_compute_planning_details',
        store=True,
        readonly=True,
    )
    fiscal_year = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        compute='_compute_planning_details',
        store=True,
        readonly=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period',
        compute='_compute_planning_details',
        store=True,
        readonly=True,
    )
    appraisal_period = fields.Char(
        string='Appraisal Period',
        compute='_compute_planning_details',
        store=True,
        readonly=True,
    )
    tier = fields.Selection([
        ('tier2', 'Tier 2 (Work Units)'),
    ], string='Tier', required=True, default='tier2',
       help='Select the performance tier to notify appraisals.')

    accept_by = fields.Date(
        string='Accept By Deadline',
        required=True,
        default=fields.Date.context_today,
        help='Deadline for work units/employees to review and accept or reject their appraisal.',
    )
    draft_appraisal_count = fields.Integer(
        string='Draft Appraisals Found',
        compute='_compute_draft_appraisal_count',
    )

    # Result state tracking fields
    notified_count = fields.Integer(string='Notified Count', default=0)
    draft_total_count = fields.Integer(string='Total Draft Count', default=0)
    skipped_count = fields.Integer(string='Skipped Count', default=0)
    summary_header_html = fields.Html(string='Summary Cards', sanitize=False)
    skipped_details_html = fields.Html(string='Adjustment Details', sanitize=False)
    notified_appraisal_ids = fields.Many2many(
        't2.appraisal', 'wizard_t2_app_notified_rel', string='Notified Appraisals'
    )
    skipped_appraisal_ids = fields.Many2many(
        't2.appraisal', 'wizard_t2_app_skipped_rel', string='Skipped Appraisals'
    )

    @api.depends('planning_name')
    def _compute_planning_details(self):
        for rec in self:
            if rec.planning_name:
                fy = rec.planning_name.fiscal_year_id
                period = rec.planning_name.appraisal_period_id
                rec.fiscal_year_id = fy
                rec.fiscal_year = fy
                rec.appraisal_period_id = period
                rec.appraisal_period = period.name if period else ''
            else:
                rec.fiscal_year_id = False
                rec.fiscal_year = False
                rec.appraisal_period_id = False
                rec.appraisal_period = ''

    @api.depends('planning_name', 'tier')
    def _compute_draft_appraisal_count(self):
        for rec in self:
            if rec.planning_name and rec.tier == 'tier2':
                fy = rec.planning_name.fiscal_year_id
                period = rec.planning_name.appraisal_period_id
                if not fy or not period:
                    rec.draft_appraisal_count = 0
                    continue
                base_domain = [
                    ('fiscal_year_id', '=', fy.id),
                    ('appraisal_period_id', '=', period.id),
                    ('state', '=', 'draft'),
                ]
                by_plan = self.env['t2.appraisal'].search_count(base_domain + [('planning_name', '=', rec.planning_name.name)])
                rec.draft_appraisal_count = by_plan if by_plan else self.env['t2.appraisal'].search_count(base_domain)
            else:
                rec.draft_appraisal_count = 0

    @api.constrains('accept_by')
    def _check_accept_by(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.accept_by and rec.accept_by < today:
                raise ValidationError("Acceptance deadline ('Accept By') cannot be earlier than the current date.")

    def action_notify(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if not self.planning_name:
            raise UserError('Please select a Planning Name before proceeding.')

        if self.accept_by and self.accept_by < today:
            raise UserError(f"The 'Accept By' deadline cannot be earlier than today ({today}).")

        if self.tier == 'tier2':
            fy = self.planning_name.fiscal_year_id
            period = self.planning_name.appraisal_period_id
            if not fy or not period:
                raise UserError('The selected Corporate Scorecard must have a valid Fiscal Year and Appraisal Period.')

            base_domain = [
                ('fiscal_year_id', '=', fy.id),
                ('appraisal_period_id', '=', period.id),
                ('state', '=', 'draft'),
            ]
            by_plan = self.env['t2.appraisal'].search(base_domain + [('planning_name', '=', self.planning_name.name)])
            draft_appraisals = by_plan if by_plan else self.env['t2.appraisal'].search(base_domain)

            if not draft_appraisals:
                raise UserError(
                    f"No draft Tier 2 Appraisals found for '{self.planning_name.name}' "
                    f"({fy.name} - {period.name}). All appraisals may already be notified or none have been generated yet."
                )

            # Assign accept_by deadline to draft appraisals
            draft_appraisals.write({'accept_by': self.accept_by or today})

            valid_apps = self.env['t2.appraisal']
            skipped_apps = self.env['t2.appraisal']
            skipped_details_map = {}

            for app in draft_appraisals:
                issues = []
                if not app.line_ids:
                    issues.append("No appraisal lines found.")
                else:
                    appraised_lines = app.line_ids.filtered(lambda l: l.appraised == 'yes')
                    if not appraised_lines:
                        issues.append("No measures marked as Appraised (Yes).")
                    else:
                        # Check missing or <= 0 uploaded values on appraised lines
                        zero_lines = appraised_lines.filtered(lambda l: (l.uploaded_value or 0.0) <= 0.0)
                        if zero_lines:
                            names = ", ".join(zero_lines.mapped(lambda l: l.measure_id.name or 'KPI Measure'))
                            issues.append(f"Missing or zero uploaded values for appraised measures: {names}")

                        # Check percentage measures exceeding 100%
                        over_pct = appraised_lines.filtered(
                            lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
                        )
                        if over_pct:
                            names = ", ".join(over_pct.mapped(lambda l: f"{l.measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                            issues.append(f"Percentage measures exceed 100%: {names}")

                if issues:
                    skipped_apps |= app
                    skipped_details_map[app] = issues
                else:
                    # Freshly calculate appraisal scores
                    try:
                        app.action_populate_score()
                    except Exception:
                        pass
                    valid_apps |= app

            # Notify valid appraisals
            if valid_apps:
                valid_apps.action_notify()

            # Audit log to Corporate Scorecard chatter
            if self.planning_name:
                log_body = f"<strong>Automatic Appraisal Notification Run (Tier 2):</strong><br/>• Notified <strong>{len(valid_apps)}</strong> of <strong>{len(draft_appraisals)}</strong> draft appraisals."
                if skipped_apps:
                    log_body += f"<br/>• <strong>{len(skipped_apps)}</strong> appraisal(s) require adjustment:<br/>"
                    for app, issues in skipped_details_map.items():
                        emp_lbl = app.employee_id.name or (app.operating_unit_id.name if app.operating_unit_id else 'Work Unit')
                        log_body += f"&nbsp;&nbsp;• <b>{emp_lbl}</b>: {'; '.join(issues)}<br/>"
                try:
                    self.planning_name.message_post(body=log_body)
                except Exception:
                    pass

            # If ALL draft appraisals were valid and notified (0 skipped), open them immediately
            if not skipped_apps:
                try:
                    action = self.env['ir.actions.act_window']._for_xml_id('performance_management.action_t2_appraisal')
                except Exception:
                    action = {
                        'type': 'ir.actions.act_window',
                        'res_model': 't2.appraisal',
                    }
                action['name'] = f"Notified Tier 2 Appraisals (All {len(valid_apps)} Notified)"
                action['domain'] = [('id', 'in', valid_apps.ids)]
                action['views'] = [(False, 'list'), (False, 'form')]
                action['view_mode'] = 'list,form'
                action['target'] = 'current'
                return action

            # Build HTML summary cards and adjustment guide
            total_draft = len(draft_appraisals)
            n_valid = len(valid_apps)
            n_skipped = len(skipped_apps)

            summary_cards_html = f"""
            <div style="display: flex; gap: 12px; margin-bottom: 16px;">
                <div style="flex: 1; padding: 12px; background: #f0fdf4; border: 1.5px solid #86efac; border-radius: 8px; text-align: center;">
                    <div style="font-size: 11px; font-weight: 700; color: #15803d; text-transform: uppercase; letter-spacing: 0.5px;">Successfully Notified</div>
                    <div style="font-size: 24px; font-weight: 800; color: #166534; line-height: 1.2; margin-top: 2px;">
                        {n_valid} <span style="font-size: 13px; font-weight: 600; color: #4b5563;">/ {total_draft} Draft</span>
                    </div>
                </div>
                <div style="flex: 1; padding: 12px; background: #fff7ed; border: 1.5px solid #fdba74; border-radius: 8px; text-align: center;">
                    <div style="font-size: 11px; font-weight: 700; color: #c2410c; text-transform: uppercase; letter-spacing: 0.5px;">Requires Adjustment</div>
                    <div style="font-size: 24px; font-weight: 800; color: #9a3412; line-height: 1.2; margin-top: 2px;">
                        {n_skipped} <span style="font-size: 13px; font-weight: 600; color: #4b5563;">/ {total_draft} Draft</span>
                    </div>
                </div>
            </div>
            """

            html_cards = []
            for app, issues in skipped_details_map.items():
                emp_name = app.employee_id.name or (app.operating_unit_id.name if app.operating_unit_id else 'Work Unit')
                unit_name = app.operating_unit_id.name if app.operating_unit_id else 'N/A'
                issues_html = "".join([f"<li style='margin-bottom: 4px;'>{iss}</li>" for iss in issues])
                card = f"""
                <div style="margin-bottom: 8px; padding: 10px 12px; background: #fffaf0; border: 1px solid #feebc8; border-left: 4px solid #dd6b20; border-radius: 6px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <strong style="color: #9c4221; font-size: 13px;">👤 {emp_name}</strong>
                        <span style="font-size: 11px; background: #fefcbf; color: #744210; padding: 2px 8px; border-radius: 4px; font-weight: 600;">Work Unit: {unit_name}</span>
                    </div>
                    <ul style="margin: 0; padding-left: 18px; color: #4a5568; font-size: 12px; line-height: 1.4;">
                        {issues_html}
                    </ul>
                </div>
                """
                html_cards.append(card)
            formatted_details_html = "".join(html_cards)

            # Update wizard state to 'result'
            self.write({
                'state': 'result',
                'notified_count': n_valid,
                'draft_total_count': total_draft,
                'skipped_count': n_skipped,
                'summary_header_html': summary_cards_html,
                'skipped_details_html': formatted_details_html,
                'notified_appraisal_ids': [(6, 0, valid_apps.ids)],
                'skipped_appraisal_ids': [(6, 0, skipped_apps.ids)],
            })

            return {
                'name': f"Notification Results ({n_valid} of {total_draft} Notified)",
                'type': 'ir.actions.act_window',
                'res_model': 'automatic.appraisal.notify.wizard',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        return {'type': 'ir.actions.act_window_close'}

    def action_view_drafts_to_adjust(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id('performance_management.action_t2_appraisal')
        except Exception:
            action = {
                'type': 'ir.actions.act_window',
                'res_model': 't2.appraisal',
            }
        action['name'] = f"Tier 2 Appraisals Requiring Adjustment ({self.skipped_count})"
        action['domain'] = [('id', 'in', self.skipped_appraisal_ids.ids)]
        action['views'] = [(False, 'list'), (False, 'form')]
        action['view_mode'] = 'list,form'
        action['target'] = 'current'
        return action

    def action_view_notified(self):
        self.ensure_one()
        try:
            action = self.env['ir.actions.act_window']._for_xml_id('performance_management.action_t2_appraisal')
        except Exception:
            action = {
                'type': 'ir.actions.act_window',
                'res_model': 't2.appraisal',
            }
        action['name'] = f"Notified Tier 2 Appraisals ({self.notified_count} of {self.draft_total_count})"
        action['domain'] = [('id', 'in', self.notified_appraisal_ids.ids)]
        action['views'] = [(False, 'list'), (False, 'form')]
        action['view_mode'] = 'list,form'
        action['target'] = 'current'
        return action
