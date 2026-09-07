# -*- coding: utf-8 -*-
import base64
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
    my_core_avg_gap = fields.Float(string='My Core Avg Gap', compute='_compute_dashboard_metrics')
    my_leadership_avg_gap = fields.Float(string='My Leadership Avg Gap', compute='_compute_dashboard_metrics')
    my_technical_avg_gap = fields.Float(string='My Technical Avg Gap', compute='_compute_dashboard_metrics')
    my_exceeds_count = fields.Integer(string='My Exceeds Target Count', compute='_compute_dashboard_metrics')
    my_meets_count = fields.Integer(string='My Meets Target Count', compute='_compute_dashboard_metrics')
    my_below_count = fields.Integer(string='My Below Target Count', compute='_compute_dashboard_metrics')
    previous_avg_gap = fields.Float(string='Previous Cycle Avg Gap', compute='_compute_dashboard_metrics')
    gap_improvement = fields.Float(string='Gap Improvement', compute='_compute_dashboard_metrics')
    gap_trend_label = fields.Char(string='Gap Trend', compute='_compute_dashboard_metrics')

    # Admin Filter & Role Access Flags
    filter_department_id = fields.Many2one('hr.department', string='Filter Department')
    is_admin_user = fields.Boolean(string='Is Admin User', compute='_compute_user_access')
    is_supervisor_user = fields.Boolean(string='Is Supervisor User', compute='_compute_user_access')
    is_employee_only = fields.Boolean(string='Is Employee Only', compute='_compute_user_access')

    # Data Quality Strip Fields
    unmapped_positions_count = fields.Integer(string='Unmapped Job Positions', compute='_compute_data_quality_metrics')
    missing_supervisors_count = fields.Integer(string='Employees Missing Supervisor', compute='_compute_data_quality_metrics')

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
            rec.is_hr_admin = is_admin
            rec.is_admin_user = is_admin
            rec.is_supervisor_user = is_supervisor or is_admin
            rec.is_employee_only = not (is_admin or is_supervisor)
            if not rec.persona_role:
                rec.persona_role = default_role

    def _compute_data_quality_metrics(self):
        total_jobs = self.env['hr.job'].search_count([])
        mapped_job_ids = self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id')
        unmapped = max(0, total_jobs - len(set(mapped_job_ids)))
        missing_sups = self.env['hr.employee'].search_count([('active', '=', True), ('parent_id', '=', False)])
        for rec in self:
            rec.unmapped_positions_count = unmapped
            rec.missing_supervisors_count = missing_sups

    @api.depends('cycle_id', 'filter_department_id')
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

            # Cycle & Department Filtered Assessment Domain
            cycle_domain = [('cycle_id', '=', cycle.id)] if cycle else []
            line_domain = [('assessment_id.cycle_id', '=', cycle.id)] if cycle else []
            if rec.filter_department_id:
                cycle_domain.append(('department_id', '=', rec.filter_department_id.id))
                line_domain.append(('department_id', '=', rec.filter_department_id.id))

            rec.total_bank_assessments = self.env['competency.assessment'].search_count(cycle_domain)

            # Assessment Line Domain for Selected Cycle & Dept
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

            # Personal Status Metrics
            if emp:
                my_asm = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id),
                    ('cycle_id', '=', cycle.id)
                ], limit=1) if cycle else False
                
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
                    
                    my_lines = my_asm.line_ids
                    m_cgaps = [l.gap for l in my_lines if l.pillar == 'core' and l.gap is not None]
                    m_lgaps = [l.gap for l in my_lines if l.pillar == 'leadership' and l.gap is not None]
                    m_tgaps = [l.gap for l in my_lines if l.pillar == 'technical' and l.gap is not None]
                    rec.my_core_avg_gap = round(sum(m_cgaps) / len(m_cgaps), 2) if m_cgaps else 0.0
                    rec.my_leadership_avg_gap = round(sum(m_lgaps) / len(m_lgaps), 2) if m_lgaps else 0.0
                    rec.my_technical_avg_gap = round(sum(m_tgaps) / len(m_tgaps), 2) if m_tgaps else 0.0
                else:
                    rec.assessment_status = 'not_assessed'
                    rec.latest_assessment_id = False
                    rec.latest_assessment_state = _('Not Started')
                    rec.my_avg_gap = 0.0
                    rec.my_core_avg_gap = 0.0
                    rec.my_leadership_avg_gap = 0.0
                    rec.my_technical_avg_gap = 0.0
                    rec.my_exceeds_count = 0
                    rec.my_meets_count = 0
                    rec.my_below_count = 0
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

    @api.depends('cycle_id', 'filter_department_id')
    def _compute_heatmap_html(self):
        for rec in self:
            if rec.filter_department_id:
                departments = rec.filter_department_id
            else:
                departments = self.env['hr.department'].search([], limit=15)
            cycle = rec.cycle_id or rec._default_cycle_id()
            if not cycle:
                rec.heatmap_html = "<div class='alert alert-warning'>No active assessment cycle selected.</div>"
                continue

            html = ["""
            <div style="width: 100%; overflow-x: auto; background-color: #FFFFFF; border-radius: 8px; border: 1px solid #e2e8f0; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);">
                <div style="font-size: 15px; font-weight: 600; color: #1d2b32; margin-bottom: 12px;">Department × pillar competency gap heatmap</div>
                <div style="font-size: 12px; color: #726732; margin-bottom: 16px; display: flex; gap: 18px; align-items: center;">
                    <span style="display: flex; align-items: center; gap: 6px;">
                        <span style="display: inline-block; width: 10px; height: 10px; background-color: #541718; border-radius: 2px;"></span>
                        High need (Gap &gt; 1.0)
                    </span>
                    <span style="display: flex; align-items: center; gap: 6px;">
                        <span style="display: inline-block; width: 10px; height: 10px; background-color: #c17540; border-radius: 2px;"></span>
                        Moderate need (Gap 0.1–1.0)
                    </span>
                    <span style="display: flex; align-items: center; gap: 6px;">
                        <span style="display: inline-block; width: 10px; height: 10px; background-color: #726732; border-radius: 2px;"></span>
                        Qualified (Gap &le; 0.0)
                    </span>
                </div>
                <table style="width: 100%; border-collapse: collapse; font-family: inherit; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f8fafc; color: #1d2b32; font-size: 12px; font-weight: 600; border-bottom: 2px solid #e2e8f0;">
                            <th style="padding: 10px 14px; text-align: left;">Department</th>
                            <th style="padding: 10px 14px; text-align: center;">Core pillar</th>
                            <th style="padding: 10px 14px; text-align: center;">Leadership pillar</th>
                            <th style="padding: 10px 14px; text-align: center;">Technical pillar</th>
                            <th style="padding: 10px 14px; text-align: center;">Overall avg gap</th>
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
                        return "<td style='padding: 10px; text-align: center; background-color: #f8fafc; color: #94a3b8;'>—</td>"
                    avg_g = round(sum(gaps) / len(gaps), 2)
                    if avg_g > 1.0:
                        bg, fg, label = "#541718", "#FFFFFF", f"{avg_g}"
                    elif avg_g > 0.0:
                        bg, fg, label = "#c17540", "#FFFFFF", f"{avg_g}"
                    else:
                        bg, fg, label = "#726732", "#FFFFFF", f"{avg_g}"
                    return f"<td style='padding: 10px; text-align: center; background-color: {bg}; color: {fg}; font-weight: 600; border: 1px solid #FFFFFF;'>{label}</td>"

                html.append(f"""
                <tr style="border-bottom: 1px solid #f1f5f9;">
                    <td style="padding: 10px 14px; font-weight: 500; color: #1d2b32;">{dept.name}</td>
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

    def action_employee_primary_action(self):
        """Contextual single primary action button for Employee hero area."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            raise models.UserError(_("No employee record found for user %s.") % user.name)

        cycle = self.cycle_id or self._default_cycle_id()
        asm = self.env['competency.assessment'].search([
            ('employee_id', '=', emp.id),
            ('cycle_id', '=', cycle.id)
        ], limit=1) if cycle else False

        if not asm:
            asm = self.env['competency.assessment'].create({
                'employee_id': emp.id,
                'cycle_id': cycle.id if cycle else False,
                'assessment_type': 'self',
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('My Competency Assessment'),
            'res_model': 'competency.assessment',
            'res_id': asm.id,
            'view_mode': 'form',
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
        """Action method to open the dashboard Singleton form view or client action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'competency_dashboard_action',
            'name': 'Competency & TNA Dashboard',
        }

    @api.model
    def get_dashboard_data(self, cycle_id=None, department_id=None, persona=None):
        """RPC API endpoint supplying structured JSON metrics and Chart.js datasets to OWL frontend (FR-RPT-002, FR-RPT-010)."""
        user = self.env.user
        emp = user.employee_id
        is_admin = user.has_group('competency_management.group_competency_admin')
        is_supervisor = user.has_group('competency_management.group_competency_supervisor') or is_admin

        # Determine Operating Unit boundary for current user (direct access, declared dependency).
        # `assigned_operating_unit_ids` is the manager's supervisory/reporting scope (Scenario 2 boundary);
        # it takes priority over the broader `operating_unit_ids` (general multi-branch access) so that
        # dashboard scoping matches the record rules in security/competency_security.xml exactly.
        user_ou_ids = []
        if not is_admin:
            if getattr(user, 'assigned_operating_unit_ids', False):
                user_ou_ids = user.assigned_operating_unit_ids.ids
            elif getattr(user, 'operating_unit_ids', False):
                user_ou_ids = user.operating_unit_ids.ids
            elif user.default_operating_unit_id:
                user_ou_ids = [user.default_operating_unit_id.id]
            elif emp:
                emp_ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
                if emp_ou:
                    user_ou_ids = [emp_ou.id]

        # Selected Cycle resolution
        if cycle_id:
            cycle = self.env['competency.assessment.cycle'].browse(int(cycle_id))
        else:
            cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
            if not cycle:
                cycle = self.env['competency.assessment.cycle'].search([], order='id desc', limit=1)

        # Active Assessment Cycle Info for Dashboard Header Banner
        open_cycle = self.env['competency.assessment.cycle'].search([('state', 'in', ['open', 'in_review'])], order='id desc', limit=1)
        active_cycle_info = {}
        if open_cycle:
            p_start = open_cycle.period_start.strftime('%b %d, %Y') if open_cycle.period_start else 'N/A'
            p_end = open_cycle.period_end.strftime('%b %d, %Y') if open_cycle.period_end else 'N/A'
            deadline = open_cycle.assessment_deadline.strftime('%b %d, %Y') if open_cycle.assessment_deadline else 'N/A'
            state_label = 'Open for Submissions' if open_cycle.state == 'open' else 'In Review'
            active_cycle_info = {
                'has_active': True,
                'name': open_cycle.name,
                'state': open_cycle.state,
                'state_label': state_label,
                'period_start': p_start,
                'period_end': p_end,
                'deadline': deadline,
            }
        else:
            active_cycle_info = {
                'has_active': False,
            }

        # Available Cycles list
        all_cycles = self.env['competency.assessment.cycle'].search_read([], ['id', 'name', 'state', 'assessment_deadline'], order='id desc')

        # Available Departments list
        if user_ou_ids:
            dept_domain = ['|', ('operating_unit_id', 'in', user_ou_ids), ('id', 'in', self.env['hr.employee'].sudo().search(['|', ('default_operating_unit_id', 'in', user_ou_ids), ('operating_unit_id', 'in', user_ou_ids)]).mapped('department_id.id'))]
            all_departments = self.env['hr.department'].search_read(dept_domain, ['id', 'name'], order='name asc')
        else:
            all_departments = self.env['hr.department'].search_read([], ['id', 'name'], order='name asc')

        # Selected Persona logic
        persona = persona or 'executive'

        # Baseline domains
        line_domain = [('cycle_id', '=', cycle.id)] if cycle else []
        asm_domain = [('cycle_id', '=', cycle.id)] if cycle else []

        # Operating Unit Strict Boundary Restriction for non-admin users
        if user_ou_ids:
            ou_emp_ids = self.env['hr.employee'].sudo().search([
                '|', ('default_operating_unit_id', 'in', user_ou_ids),
                '|', ('operating_unit_id', 'in', user_ou_ids),
                ('department_id.operating_unit_id', 'in', user_ou_ids)
            ]).ids
            line_domain.append(('employee_id', 'in', ou_emp_ids))
            asm_domain.append(('employee_id', 'in', ou_emp_ids))

        if department_id:
            line_domain.append(('department_id', '=', int(department_id)))
            asm_domain.append(('department_id', '=', int(department_id)))

        # Persona-based & Role-based employee scoping
        if persona == 'employee' and emp:
            line_domain.append(('employee_id', '=', emp.id))
            asm_domain.append(('employee_id', '=', emp.id))
        elif (persona == 'supervisor' or persona == 'manager') and emp:
            subordinate_emp_ids = self.env['hr.employee'].sudo().search([('id', 'child_of', emp.id)]).ids
            dept_emp_ids = []
            if emp.department_id:
                dept_emp_ids = self.env['hr.employee'].sudo().search([('department_id', 'child_of', emp.department_id.id)]).ids
            scoped_emp_ids = list(set(subordinate_emp_ids + dept_emp_ids + [emp.id]))
            line_domain.append(('employee_id', 'in', scoped_emp_ids))
            asm_domain.append(('employee_id', 'in', scoped_emp_ids))
        elif not is_admin and not is_supervisor and emp:
            line_domain.append(('employee_id', '=', emp.id))
            asm_domain.append(('employee_id', '=', emp.id))

        lines = self.env['competency.assessment.line'].search(line_domain)
        asms_total = self.env['competency.assessment'].search_count(asm_domain)
        has_real_data = bool(lines)

        below_cnt = len(lines.filtered(lambda l: l.achievement_status == 'below'))
        meets_cnt = len(lines.filtered(lambda l: l.achievement_status == 'meets'))
        exceeds_cnt = len(lines.filtered(lambda l: l.achievement_status == 'exceeds'))

        # Pillar Average Gaps
        core_lines = lines.filtered(lambda l: l.pillar == 'core')
        lead_lines = lines.filtered(lambda l: l.pillar == 'leadership')
        tech_lines = lines.filtered(lambda l: l.pillar == 'technical')

        core_avg = round(sum([l.gap for l in core_lines if l.gap is not None]) / len(core_lines), 2) if core_lines else 0.0
        lead_avg = round(sum([l.gap for l in lead_lines if l.gap is not None]) / len(lead_lines), 2) if lead_lines else 0.0
        tech_avg = round(sum([l.gap for l in tech_lines if l.gap is not None]) / len(tech_lines), 2) if tech_lines else 0.0
        bank_avg = round(sum([l.gap for l in lines if l.gap is not None]) / len(lines), 2) if lines else 0.0

        # Data Quality Counters (Scoped to User OU if non-admin)
        if user_ou_ids:
            ou_emp_domain = [
                '|', ('default_operating_unit_id', 'in', user_ou_ids),
                '|', ('operating_unit_id', 'in', user_ou_ids),
                ('department_id.operating_unit_id', 'in', user_ou_ids)
            ]
            ou_employees = self.env['hr.employee'].sudo().search(ou_emp_domain)
            ou_jobs = ou_employees.mapped('job_id')
            total_jobs = len(ou_jobs)
            mapped_job_ids = set(self.env['competency.role.mapping'].search([('state', '=', 'approved'), ('job_position_id', 'in', ou_jobs.ids)]).mapped('job_position_id.id'))
            unmapped_cnt = max(0, total_jobs - len(mapped_job_ids))
            missing_sups_cnt = len(ou_employees.filtered(lambda e: e.active and not e.parent_id))
        else:
            total_jobs = self.env['hr.job'].search_count([])
            mapped_job_ids = set(self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id'))
            unmapped_cnt = max(0, total_jobs - len(mapped_job_ids))
            missing_sups_cnt = self.env['hr.employee'].search_count([('active', '=', True), ('parent_id', '=', False)])

        # Personal Metrics (Employee)
        my_asm = False
        if emp and cycle:
            my_asm = self.env['competency.assessment'].search([
                ('employee_id', '=', emp.id),
                ('cycle_id', '=', cycle.id)
            ], limit=1)

        # Radar chart labels and values
        radar_labels = []
        radar_assessed = []
        radar_required = []
        if my_asm and my_asm.line_ids:
            for l in my_asm.line_ids[:8]:
                radar_labels.append(l.competency_id.name)
                c_val = int(l.current_level) if l.current_level and str(l.current_level).isdigit() else 0
                r_val = int(l.required_level) if l.required_level and str(l.required_level).isdigit() else 0
                radar_assessed.append(c_val)
                radar_required.append(r_val)
        elif lines:
            grouped_comp = {}
            for l in lines[:50]:
                cid = l.competency_id
                c_val = int(l.current_level) if l.current_level and str(l.current_level).isdigit() else None
                r_val = int(l.required_level) if l.required_level and str(l.required_level).isdigit() else 1
                if cid not in grouped_comp:
                    grouped_comp[cid] = {'assessed': [], 'required': []}
                if c_val is not None:
                    grouped_comp[cid]['assessed'].append(c_val)
                grouped_comp[cid]['required'].append(r_val)

            for comp, vals in list(grouped_comp.items())[:6]:
                radar_labels.append(comp.name)
                avg_ass = round(sum(vals['assessed']) / len(vals['assessed']), 1) if vals['assessed'] else 0.0
                avg_req = round(sum(vals['required']) / len(vals['required']), 1) if vals['required'] else 0.0
                radar_assessed.append(avg_ass)
                radar_required.append(avg_req)

        # Multi-cycle trend history for Employee
        trend_cycles = self.env['competency.assessment.cycle'].search([], order='id asc', limit=5)
        trend_labels = [c.name for c in trend_cycles]
        trend_values = []
        for c in trend_cycles:
            casm = self.env['competency.assessment'].search([
                ('employee_id', '=', emp.id if emp else 0),
                ('cycle_id', '=', c.id)
            ], limit=1)
            trend_values.append(casm.average_gap if casm else 0.0)

        # Team metrics for Supervisor
        team_roster = []
        team_avg_gap = 0.0
        if emp:
            subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id)])
            team_asms = self.env['competency.assessment'].search([
                ('employee_id', 'in', subordinates.ids),
                ('cycle_id', '=', cycle.id if cycle else 0)
            ])
            t_lines = team_asms.mapped('line_ids')
            team_avg_gap = round(sum([l.gap for l in t_lines if l.gap is not None]) / len(t_lines), 2) if t_lines else 0.0
            
            for sub in subordinates:
                s_asm = team_asms.filtered(lambda a: a.employee_id.id == sub.id)
                top_gaps = s_asm[0].line_ids.filtered(lambda l: l.achievement_status == 'below').sorted(key=lambda l: l.gap or 0, reverse=True)[:2] if s_asm else []
                team_roster.append({
                    'id': sub.id,
                    'name': sub.name,
                    'job': sub.job_id.name if sub.job_id else 'N/A',
                    'assessment_id': s_asm[0].id if s_asm else False,
                    'status': dict(s_asm[0]._fields['state'].selection).get(s_asm[0].state, 'Not Started') if s_asm else 'Not Started',
                    'top_gaps': ", ".join([l.competency_id.name for l in top_gaps]) if top_gaps else 'Fit / Qualified'
                })

        # Department Heatmap Data Matrix
        heatmap_rows = []
        if has_real_data:
            if user_ou_ids:
                heatmap_dept_domain = ['|', ('operating_unit_id', 'in', user_ou_ids), ('id', 'in', self.env['hr.employee'].search(['|', ('default_operating_unit_id', 'in', user_ou_ids), ('operating_unit_id', 'in', user_ou_ids)]).mapped('department_id.id'))]
                heatmap_depts = self.env['hr.department'].search(heatmap_dept_domain, order='name asc', limit=15)
            else:
                heatmap_depts = self.env['hr.department'].search([], order='name asc', limit=15)

            for d in heatmap_depts:
                d_lines = lines.filtered(lambda l: l.department_id.id == d.id)
                if not d_lines:
                    continue
                d_core = [l.gap for l in d_lines if l.pillar == 'core' and l.gap is not None]
                d_lead = [l.gap for l in d_lines if l.pillar == 'leadership' and l.gap is not None]
                d_tech = [l.gap for l in d_lines if l.pillar == 'technical' and l.gap is not None]
                
                c_val = round(sum(d_core)/len(d_core), 2) if d_core else 0.0
                l_val = round(sum(d_lead)/len(d_lead), 2) if d_lead else 0.0
                t_val = round(sum(d_tech)/len(d_tech), 2) if d_tech else 0.0
                
                heatmap_rows.append({
                    'dept_id': d.id,
                    'dept_name': d.name,
                    'core': c_val,
                    'leadership': l_val,
                    'technical': t_val,
                    'overall': round((c_val + l_val + t_val) / 3.0, 2),
                })

        return {
            'user': {
                'name': user.name,
                'is_admin': is_admin,
                'is_supervisor': is_supervisor,
                'has_subordinates': bool(emp and self.env['hr.employee'].search_count([('parent_id', '=', emp.id)])),
                'employee_name': emp.name if emp else user.name,
                'job_name': emp.job_id.name if emp and emp.job_id else 'N/A',
            },
            'cycle': {
                'id': cycle.id if cycle else False,
                'name': cycle.name if cycle else 'No Cycle Selected',
                'deadline': str(cycle.assessment_deadline) if cycle and cycle.assessment_deadline else '',
            },
            'active_cycle_info': active_cycle_info,
            'all_cycles': all_cycles,
            'all_departments': all_departments,
            'stats': {
                'has_data': has_real_data,
                'bank_avg_gap': bank_avg,
                'below_cnt': below_cnt,
                'meets_cnt': meets_cnt,
                'exceeds_cnt': exceeds_cnt,
                'total_assessments': len(set(lines.mapped('assessment_id.id'))),
                'core_avg': core_avg,
                'lead_avg': lead_avg,
                'tech_avg': tech_avg,
                'unmapped_cnt': unmapped_cnt,
                'missing_sups_cnt': missing_sups_cnt,
                'team_avg_gap': team_avg_gap,
                'my_avg_gap': my_asm.average_gap if my_asm else 0.0,
                'my_status': dict(my_asm._fields['state'].selection).get(my_asm.state, 'Not Started') if my_asm else 'Not Started',
                'my_asm_id': my_asm.id if my_asm else False,
            },
            'charts': {
                'tna_donut': {
                    'labels': ['Underqualified (Training Needed)', 'Fit / Qualified', 'Overqualified'],
                    'data': [below_cnt, meets_cnt, exceeds_cnt],
                    'colors': ['#541718', '#726732', '#c17540']
                },
                'pillar_bar': {
                    'labels': ['Core Pillar', 'Leadership Pillar', 'Technical Pillar'],
                    'datasets': [
                        {
                            'label': 'Below Target',
                            'data': [
                                len(core_lines.filtered(lambda l: l.achievement_status == 'below')),
                                len(lead_lines.filtered(lambda l: l.achievement_status == 'below')),
                                len(tech_lines.filtered(lambda l: l.achievement_status == 'below')),
                            ],
                            'backgroundColor': '#541718',
                        },
                        {
                            'label': 'Meets Target',
                            'data': [
                                len(core_lines.filtered(lambda l: l.achievement_status == 'meets')),
                                len(lead_lines.filtered(lambda l: l.achievement_status == 'meets')),
                                len(tech_lines.filtered(lambda l: l.achievement_status == 'meets')),
                            ],
                            'backgroundColor': '#726732',
                        },
                        {
                            'label': 'Exceeds Target',
                            'data': [
                                len(core_lines.filtered(lambda l: l.achievement_status == 'exceeds')),
                                len(lead_lines.filtered(lambda l: l.achievement_status == 'exceeds')),
                                len(tech_lines.filtered(lambda l: l.achievement_status == 'exceeds')),
                            ],
                            'backgroundColor': '#c17540',
                        }
                    ]
                },
                'employee_radar': {
                    # Real per-competency ratings only — never fabricate sample values here.
                    # An empty payload means "no assessment recorded yet"; the widget must show
                    # an explicit empty state rather than invented numbers.
                    'has_data': bool(radar_labels),
                    'labels': radar_labels,
                    'assessed': radar_assessed,
                    'required': radar_required,
                },
                'employee_trend': {
                    'labels': trend_labels,
                    'data': trend_values,
                }
            },
            'team_roster': team_roster,
            'heatmap_rows': heatmap_rows,
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
            recipients |= admin_group.user_ids
        if supervisor_group:
            recipients |= supervisor_group.user_ids

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

        # Generate PDF report document attachment per FR-RPT-008
        pdf_attachment = False
        if active_cycle:
            try:
                report_wiz = self.env['competency.report.wizard'].create({
                    'cycle_id': active_cycle.id,
                    'report_type': 'org_capability',
                    'pillar': 'all',
                })
                pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf('competency_management.action_report_competency_org_capability', [report_wiz.id])
                if pdf_content:
                    pdf_attachment = self.env['ir.attachment'].create({
                        'name': 'Organizational_Capability_Report_%s.pdf' % active_cycle.name,
                        'type': 'binary',
                        'datas': base64.b64encode(pdf_content),
                        'res_model': 'competency.dashboard',
                        'mimetype': 'application/pdf',
                    })
            except Exception as e:
                _logger.warning("Failed to render QWeb PDF report attachment for cron: %s", str(e))

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
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Underqualified (Training Needed) Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #541718;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Fit / Qualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #726732;"><b>%s</b></td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #ddd;">Overqualified Lines</td><td style="padding: 8px; text-align: right; border: 1px solid #ddd; color: #1d2b32;"><b>%s</b></td></tr>
                    </table>
                    <p>The full <b>Organizational Capability &amp; TNA PDF Report</b> is attached to this email. Log in to the Bunna Bank ERP Portal to view interactive gap analytics.</p>
                </div>
                """) % (cycle_name, user.name, total_comps, total_asms, below_cnt, meets_cnt, exceeds_cnt)

                mail_values = {
                    'subject': _('Scheduled Competency & TNA Report — %s') % cycle_name,
                    'body_html': body,
                    'email_to': user.email,
                    'attachment_ids': [(4, pdf_attachment.id)] if pdf_attachment else [],
                }
                self.env['mail.mail'].create(mail_values).send()
                sent_count += 1
            except Exception as e:
                _logger.warning("Failed to send scheduled competency email report to %s (%s): %s", user.name, user.email, str(e))

        return sent_count
