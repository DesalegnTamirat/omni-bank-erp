# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CompetencyDashboard(models.TransientModel):
    """Executive & Employee Self-Service Competency Dashboard (FR-RPT-002, FR-RPT-010)."""
    _name = 'competency.dashboard'
    _description = 'Executive & Employee Competency Dashboard'

    name = fields.Char(string='Dashboard Title', default='Bunna Bank Competency & Talent Capability Dashboard')

    # Selected Assessment Cycle for Dynamic Dashboard Filtering
    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Select Assessment Cycle',
        default=lambda self: self._default_cycle_id(),
    )
    cycle_name = fields.Char(string='Cycle Name', compute='_compute_dashboard_metrics')
    cycle_deadline = fields.Date(string='Assessment Deadline', compute='_compute_dashboard_metrics')
    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_dashboard_metrics')

    # Role Access & Persona View Selector
    is_hr_admin = fields.Boolean(string='Is HR Admin', compute='_compute_user_access')
    persona_role = fields.Selection([
        ('executive', 'Executive / Director View'),
        ('hrbp', 'HRBP / Supervisor View'),
        ('manager', 'Manager Team View'),
        ('employee', 'Employee Self-Service View'),
    ], string='Dashboard Persona', compute='_compute_user_access', readonly=False, default='executive')

    # Employee Personal Status
    user_employee_id = fields.Many2one('hr.employee', string='My Employee Record', compute='_compute_dashboard_metrics')
    assessment_status = fields.Selection([
        ('assessed', 'Assessed in Selected Cycle'),
        ('not_assessed', 'Not Assessed Yet'),
    ], string='My Assessment Status', compute='_compute_dashboard_metrics')
    latest_assessment_id = fields.Many2one('competency.assessment', string='My Latest Assessment', compute='_compute_dashboard_metrics')
    latest_assessment_state = fields.Char(string='Latest Assessment Status', compute='_compute_dashboard_metrics')

    # Personal Metrics
    my_avg_gap = fields.Float(string='My Average Gap', compute='_compute_dashboard_metrics')
    my_exceeds_count = fields.Integer(string='My Exceeds Target Count', compute='_compute_dashboard_metrics')
    my_meets_count = fields.Integer(string='My Meets Target Count', compute='_compute_dashboard_metrics')
    my_below_count = fields.Integer(string='My Below Target Count', compute='_compute_dashboard_metrics')
    previous_avg_gap = fields.Float(string='Previous Cycle Avg Gap', compute='_compute_dashboard_metrics')
    gap_improvement = fields.Float(string='Gap Improvement', compute='_compute_dashboard_metrics')
    gap_trend_label = fields.Char(string='Gap Trend', compute='_compute_dashboard_metrics')

    # Bank-Wide Executive Metrics (Selected Cycle Filtered)
    total_active_competencies = fields.Integer(string='Total Framework Competencies', compute='_compute_dashboard_metrics')
    total_bank_assessments = fields.Integer(string='Total Assessed Employees in Cycle', compute='_compute_dashboard_metrics')
    overall_bank_avg_gap = fields.Float(string='Bank Average Gap', compute='_compute_dashboard_metrics')
    
    # TNA Measure Breakdown Numbers
    bank_below_count = fields.Integer(string='Training Needed (Below Required)', compute='_compute_dashboard_metrics')
    bank_meets_count = fields.Integer(string='Fit / Qualified (Meets Required)', compute='_compute_dashboard_metrics')
    bank_exceeds_count = fields.Integer(string='Overqualified (Exceeds Required)', compute='_compute_dashboard_metrics')

    # Pillar Average Gaps
    core_avg_gap = fields.Float(string='Core Pillar Average Gap', compute='_compute_dashboard_metrics')
    leadership_avg_gap = fields.Float(string='Leadership Pillar Average Gap', compute='_compute_dashboard_metrics')
    technical_avg_gap = fields.Float(string='Technical Pillar Average Gap', compute='_compute_dashboard_metrics')

    # Department x Pillar Heat Map HTML
    heatmap_html = fields.Html(string='Department x Pillar Gap Heat Map', compute='_compute_heatmap_html')

    def _default_cycle_id(self):
        cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        if not cycle:
            cycle = self.env['competency.assessment.cycle'].search([], order='id desc', limit=1)
        return cycle

    def _compute_user_access(self):
        user = self.env.user
        is_admin = user.has_group('competency_management.group_competency_admin')
        is_supervisor = user.has_group('competency_management.group_competency_supervisor')
        has_reports = self.env['hr.employee'].search_count([('parent_id.user_id', '=', user.id)]) > 0

        if is_admin:
            default_role = 'executive'
        elif is_supervisor and has_reports:
            default_role = 'manager'
        elif is_supervisor:
            default_role = 'hrbp'
        else:
            default_role = 'employee'

        for rec in self:
            rec.is_hr_admin = is_admin or is_supervisor
            if not rec.persona_role:
                rec.persona_role = default_role

    @api.depends('cycle_id')
    def _compute_dashboard_metrics(self):
        today = fields.Date.context_today(self)
        user = self.env.user
        emp = user.employee_id

        total_comps = self.env['competency.competency'].search_count([('status', '=', 'active')])

        for rec in self:
            cycle = rec.cycle_id or self._default_cycle_id()
            rec.cycle_name = cycle.name if cycle else _('No Cycle Selected')
            rec.cycle_deadline = cycle.assessment_deadline if cycle else False
            if cycle and cycle.assessment_deadline:
                rec.days_remaining = max(0, (cycle.assessment_deadline - today).days)
            else:
                rec.days_remaining = 0

            rec.user_employee_id = emp.id if emp else False
            rec.total_active_competencies = total_comps

            # Cycle-Filtered Assessment Domain
            cycle_domain = [('cycle_id', '=', cycle.id)] if cycle else []
            approved_cycle_domain = [('cycle_id', '=', cycle.id), ('state', 'in', ['approved', 'locked'])] if cycle else [('state', 'in', ['approved', 'locked'])]

            rec.total_bank_assessments = self.env['competency.assessment'].search_count(cycle_domain)

            # Assessment Line Domain for Selected Cycle
            line_domain = [('assessment_id.cycle_id', '=', cycle.id)] if cycle else []
            lines = self.env['competency.assessment.line'].search(line_domain)
            
            gaps = [l.gap for l in lines if l.gap is not None]
            rec.overall_bank_avg_gap = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

            # TNA Category Breakdown Counts
            rec.bank_below_count = len(lines.filtered(lambda l: l.tna_measure == 'below'))
            rec.bank_meets_count = len(lines.filtered(lambda l: l.tna_measure == 'meets'))
            rec.bank_exceeds_count = len(lines.filtered(lambda l: l.tna_measure == 'exceeds'))

            # Pillar Average Gaps
            core_gaps = [l.gap for l in lines if l.pillar == 'core' and l.gap is not None]
            rec.core_avg_gap = round(sum(core_gaps) / len(core_gaps), 2) if core_gaps else 0.0

            lead_gaps = [l.gap for l in lines if l.pillar == 'leadership' and l.gap is not None]
            rec.leadership_avg_gap = round(sum(lead_gaps) / len(lead_gaps), 2) if lead_gaps else 0.0

            tech_gaps = [l.gap for l in lines if l.pillar == 'technical' and l.gap is not None]
            rec.technical_avg_gap = round(sum(tech_gaps) / len(tech_gaps), 2) if tech_gaps else 0.0

            # Personal Status Metrics inside _compute_dashboard_metrics
            if emp:
                my_asm = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id),
                    ('cycle_id', '=', cycle.id)
                ], limit=1) if cycle else False
                
                # Search previous cycle for trend comparison
                prev_cycle = self.env['competency.assessment.cycle'].search([
                    ('id', '!=', cycle.id if cycle else 0)
                ], order='id desc', limit=1)
                
                prev_asm = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id),
                    ('cycle_id', '=', prev_cycle.id)
                ], limit=1) if prev_cycle else False

                if my_asm:
                    rec.assessment_status = 'assessed'
                    rec.latest_assessment_id = my_asm.id
                    rec.latest_assessment_state = dict(my_asm._fields['state'].selection).get(my_asm.state, my_asm.state)
                    rec.my_avg_gap = my_asm.average_gap
                    rec.my_exceeds_count = len(my_asm.line_ids.filtered(lambda l: l.achievement_status == 'exceeds'))
                    rec.my_meets_count = len(my_asm.line_ids.filtered(lambda l: l.achievement_status == 'meets'))
                    rec.my_below_count = len(my_asm.line_ids.filtered(lambda l: l.achievement_status == 'below'))
                else:
                    rec.assessment_status = 'not_assessed'
                    rec.latest_assessment_id = False
                    rec.latest_assessment_state = _('Not Started')
                    rec.my_avg_gap = 0.0
                    rec.my_exceeds_count = 0
                    rec.my_meets_count = 0
                    rec.my_below_count = 0

                if prev_asm:
                    rec.previous_avg_gap = prev_asm.average_gap
                    diff = round(prev_asm.average_gap - rec.my_avg_gap, 2)
                    rec.gap_improvement = diff
                    if diff > 0:
                        rec.gap_trend_label = _("Improved by %s points vs Previous Cycle") % diff
                    elif diff < 0:
                        rec.gap_trend_label = _("Gap increased by %s points vs Previous Cycle") % abs(diff)
                    else:
                        rec.gap_trend_label = _("Maintained vs Previous Cycle")
                else:
                    rec.previous_avg_gap = 0.0
                    rec.gap_improvement = 0.0
                    rec.gap_trend_label = _("Baseline Assessment")
            else:
                rec.assessment_status = 'not_assessed'
                rec.latest_assessment_id = False
                rec.latest_assessment_state = _('No Employee Record Linked')
                rec.my_avg_gap = 0.0
                rec.my_exceeds_count = 0
                rec.my_meets_count = 0
                rec.my_below_count = 0
                rec.previous_avg_gap = 0.0
                rec.gap_improvement = 0.0
                rec.gap_trend_label = _("N/A")

    @api.depends('cycle_id')
    def _compute_heatmap_html(self):
        departments = self.env['hr.department'].search([], limit=15)
        for rec in self:
            cycle = rec.cycle_id or rec._default_cycle_id()
            if not cycle:
                rec.heatmap_html = "<div class='alert alert-warning'>No active assessment cycle selected.</div>"
                continue

            html = ["""
            <div style="width: 100%; overflow-x: auto; background-color: #FFFFFF; border-radius: 8px; border: 1px solid #e1e8ed; padding: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.04);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h4 style="margin: 0; color: #541718; font-weight: 800;">🔥 Department × Pillar Competency Gap Heat Map</h4>
                    <div style="font-size: 11px;">
                        <span style="background-color: #541718; color: #FFF; padding: 3px 8px; border-radius: 4px; margin-right: 4px;">🚨 Gap > 1.0 (High Need)</span>
                        <span style="background-color: #c17540; color: #FFF; padding: 3px 8px; border-radius: 4px; margin-right: 4px;">⚠️ Gap 0.1–1.0 (Moderate)</span>
                        <span style="background-color: #425727; color: #FFF; padding: 3px 8px; border-radius: 4px;">✅ Gap ≤ 0.0 (Qualified)</span>
                    </div>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-family: 'Segoe UI', sans-serif; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #1d2b32; color: #FFFFFF; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px;">
                            <th style="padding: 10px 14px; text-align: left; border-radius: 4px 0 0 0;">Department</th>
                            <th style="padding: 10px 14px; text-align: center;">Core Pillar</th>
                            <th style="padding: 10px 14px; text-align: center;">Leadership Pillar</th>
                            <th style="padding: 10px 14px; text-align: center;">Technical Pillar</th>
                            <th style="padding: 10px 14px; text-align: center; border-radius: 0 4px 0 0;">Overall Dept Avg</th>
                        </tr>
                    </thead>
                    <tbody>
            """]

            for dept in departments:
                lines = self.env['competency.assessment.line'].search([
                    ('cycle_id', '=', cycle.id),
                    ('department_id', '=', dept.id)
                ])
                if not lines:
                    continue

                def get_tile(pillar_val):
                    p_lines = lines.filtered(lambda l: l.pillar == pillar_val) if pillar_val != 'overall' else lines
                    gaps = [l.gap for l in p_lines if l.gap is not None]
                    if not gaps:
                        return "<td style='padding: 10px; text-align: center; background-color: #f8f9fa; color: #999;'>—</td>"
                    avg_g = round(sum(gaps) / len(gaps), 2)
                    if avg_g > 1.0:
                        bg, fg, label = "#541718", "#FFFFFF", f"🚨 {avg_g}"
                    elif avg_g > 0.0:
                        bg, fg, label = "#c17540", "#FFFFFF", f"⚠️ {avg_g}"
                    else:
                        bg, fg, label = "#425727", "#FFFFFF", f"✅ {avg_g}"
                    return f"<td style='padding: 10px; text-align: center; background-color: {bg}; color: {fg}; font-weight: bold; border: 1px solid #FFFFFF;'>{label}</td>"

                html.append(f"""
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 10px 14px; font-weight: 600; color: #1d2b32;">{dept.name}</td>
                    {get_tile('core')}
                    {get_tile('leadership')}
                    {get_tile('technical')}
                    {get_tile('overall')}
                </tr>
                """)

            html.append("</tbody></table></div>")
            rec.heatmap_html = "".join(html)

    def action_start_self_assessment(self):
        """Action: Create or open self-assessment for current employee."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Employee Record'),
                    'message': _('Your user account is not linked to an Employee record.'),
                    'type': 'warning',
                }
            }

        cycle = self.cycle_id or self._default_cycle_id()
        if not cycle:
            raise models.UserError(_('There is currently no open Assessment Cycle. Please contact HR.'))

        existing = self.env['competency.assessment'].search([
            ('employee_id', '=', emp.id),
            ('cycle_id', '=', cycle.id),
            ('assessment_type', '=', 'self')
        ], limit=1)

        if existing:
            res_id = existing.id
        else:
            new_asm = self.env['competency.assessment'].create({
                'employee_id': emp.id,
                'cycle_id': cycle.id,
                'assessment_type': 'self',
                'assessor_id': user.id,
                'state': 'draft',
            })
            res_id = new_asm.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'My Self-Assessment',
            'res_model': 'competency.assessment',
            'res_id': res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_my_report(self):
        self.ensure_one()
        if self.latest_assessment_id:
            return self.env.ref('competency_management.action_report_competency_assessment').report_action(self.latest_assessment_id)
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Assessment Available'),
                    'message': _('Complete your assessment first to generate a PDF profile report.'),
                    'type': 'warning',
                }
            }

    def action_view_my_gap_chart(self):
        """Action: Open graph/pivot view of employee's competency gaps."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        domain = [('assessment_id.employee_id', '=', emp.id)] if emp else []
        return {
            'type': 'ir.actions.act_window',
            'name': 'My Competency Gap Graph & Breakdown',
            'res_model': 'competency.assessment.line',
            'view_mode': 'graph,pivot,list',
            'domain': domain,
            'target': 'current',
        }

    def action_open_tna_analytics_below(self):
        """Open detailed TNA Analytics pre-filtered for Underqualified (Below Target)."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_below'] = 1
        if self.cycle_id:
            domain = [('cycle_id', '=', self.cycle_id.id)]
        else:
            domain = []
        return {
            'type': 'ir.actions.act_window',
            'name': 'Underqualified Competency Lines (Training Needed)',
            'res_model': 'competency.assessment.line',
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_tna_analytics_meets(self):
        """Open detailed TNA Analytics pre-filtered for Fit / Qualified."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_meets'] = 1
        if self.cycle_id:
            domain = [('cycle_id', '=', self.cycle_id.id)]
        else:
            domain = []
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fit / Qualified Competency Lines',
            'res_model': 'competency.assessment.line',
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_tna_analytics_exceeds(self):
        """Open detailed TNA Analytics pre-filtered for Overqualified."""
        self.ensure_one()
        ctx = dict(self.env.context)
        ctx['search_default_filter_exceeds'] = 1
        if self.cycle_id:
            domain = [('cycle_id', '=', self.cycle_id.id)]
        else:
            domain = []
        return {
            'type': 'ir.actions.act_window',
            'name': 'Overqualified Competency Lines',
            'res_model': 'competency.assessment.line',
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_tna_analytics_all(self):
        """Open full TNA Analytics and Assessment Line Report."""
        self.ensure_one()
        ctx = dict(self.env.context)
        if self.cycle_id:
            domain = [('cycle_id', '=', self.cycle_id.id)]
        else:
            domain = []
        return {
            'type': 'ir.actions.act_window',
            'name': 'Comprehensive Competency & TNA Analytics Report',
            'res_model': 'competency.assessment.line',
            'view_mode': 'list,graph,pivot,form',
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }

    def action_open_matrix_config(self):
        """Action: Open Proficiency Matrix Settings configuration form."""
        self.ensure_one()
        config = self.env['competency.matrix.config'].get_active_config()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Competency Proficiency Matrix Configuration',
            'res_model': 'competency.matrix.config',
            'res_id': config.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_dashboard(self):
        """Action method to open the dashboard Singleton form view."""
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({'name': 'Bunna Bank Competency & Talent Capability Dashboard'})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Competency Overview Dashboard',
            'res_model': 'competency.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def _cron_send_scheduled_competency_reports(self):
        """Scheduled distribution cron method with supervisor group support and error handling (FR-RPT-008)."""
        import logging
        _logger = logging.getLogger(__name__)

        admin_group = self.env.ref('competency_management.group_competency_admin', raise_if_not_found=False)
        supervisor_group = self.env.ref('competency_management.group_competency_supervisor', raise_if_not_found=False)

        recipients = self.env['res.users']
        if admin_group:
            recipients |= admin_group.users
        if supervisor_group:
            recipients |= supervisor_group.users

        if not recipients:
            return False

        active_cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        cycle_name = active_cycle.name if active_cycle else 'Current Framework Status'
        total_comps = self.env['competency.competency'].search_count([('status', '=', 'active')])
        total_asms = self.env['competency.assessment'].search_count([('cycle_id', '=', active_cycle.id)]) if active_cycle else 0

        lines = self.env['competency.assessment.line'].search([('cycle_id', '=', active_cycle.id)]) if active_cycle else self.env['competency.assessment.line']
        below_cnt = len(lines.filtered(lambda l: l.tna_measure == 'below'))
        meets_cnt = len(lines.filtered(lambda l: l.tna_measure == 'meets'))
        exceeds_cnt = len(lines.filtered(lambda l: l.tna_measure == 'exceeds'))

        sent_count = 0
        for user in recipients:
            if not user.email:
                continue
            try:
                body = _("""
                <div style="font-family: Arial, sans-serif; color: #1d2b32; line-height: 1.5;">
                    <div style="background-color: #541718; color: #FFFFFF; padding: 16px 20px; border-radius: 6px; margin-bottom: 16px;">
                        <h2 style="margin: 0; font-size: 20px;">Bunna Bank S.C. — Scheduled Talent Capability &amp; TNA Report</h2>
                        <div style="font-size: 12px; color: #c17540; margin-top: 4px;">Cycle: %s</div>
                    </div>
                    <p>Hello <b>%s</b>,</p>
                    <p>Here is your scheduled competency capability and TNA assessment summary:</p>
                    <table style="width: 100%%; border-collapse: collapse; border: 1px solid #ddd; font-size: 13px; margin-bottom: 16px;">
                        <tr style="background-color: #f4f6f7;"><th style="padding: 8px; text-align: left; border: 1px solid #ddd;">Metric</th><th style="padding: 8px; text-align: right; border: 1px solid #ddd;">Value</th></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Framework Active Competencies</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Assessed Employees in Cycle</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">🚨 Underqualified (Training Needed) Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #541718;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">✅ Fit / Qualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #425727;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">⭐ Overqualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #1d2b32;"><b>%s</b></td></tr>
                    </table>
                    <p>Log in to the Bunna Bank ERP Portal to view full interactive gap analytics and department heat maps.</p>
                </div>
                """) % (cycle_name, user.name, total_comps, total_asms, below_cnt, meets_cnt, exceeds_cnt)

                mail_values = {
                    'subject': _('Scheduled Competency & TNA Report — %s') % cycle_name,
                    'body_html': body,
                    'email_to': user.email,
                }
                self.env['mail.mail'].create(mail_values).send()
                sent_count += 1
            except Exception as e:
                _logger.warning("Failed to send scheduled competency email report to %s (%s): %s", user.name, user.email, str(e))

        return sent_count
