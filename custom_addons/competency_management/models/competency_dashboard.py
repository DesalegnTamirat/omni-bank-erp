# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class CompetencyDashboard(models.TransientModel):
    """Executive & Employee Self-Service Competency Dashboard (FR-RPT-002, FR-RPT-010)."""
    _name = 'competency.dashboard'
    _description = 'Executive & Employee Competency Dashboard'

    name = fields.Char(string='Dashboard Title', default='Bunna Bank Competency & Talent Capability Dashboard')
    
    # Active Cycle Metrics
    active_cycle_id = fields.Many2one('competency.assessment.cycle', string='Current Active Cycle', compute='_compute_dashboard_metrics')
    active_cycle_name = fields.Char(string='Active Cycle Name', compute='_compute_dashboard_metrics')
    active_cycle_deadline = fields.Date(string='Assessment Deadline', compute='_compute_dashboard_metrics')

    # Employee Personal Status
    user_employee_id = fields.Many2one('hr.employee', string='My Employee Record', compute='_compute_dashboard_metrics')
    assessment_status = fields.Selection([
        ('assessed', 'Assessed in Current Cycle'),
        ('not_assessed', 'Not Assessed Yet'),
    ], string='My Assessment Status', compute='_compute_dashboard_metrics')
    latest_assessment_id = fields.Many2one('competency.assessment', string='My Latest Assessment', compute='_compute_dashboard_metrics')
    latest_assessment_state = fields.Char(string='Latest Assessment Status', compute='_compute_dashboard_metrics')

    # General & Personal Gap Metrics
    total_active_competencies = fields.Integer(string='Total Framework Competencies', compute='_compute_dashboard_metrics')
    total_bank_assessments = fields.Integer(string='Total Completed Assessments', compute='_compute_dashboard_metrics')
    overall_bank_avg_gap = fields.Float(string='Bank Average Gap', compute='_compute_dashboard_metrics')
    my_avg_gap = fields.Float(string='My Average Gap', compute='_compute_dashboard_metrics')
    
    my_exceeds_count = fields.Integer(string='My Exceeds Target Count', compute='_compute_dashboard_metrics')
    my_meets_count = fields.Integer(string='My Meets Target Count', compute='_compute_dashboard_metrics')
    my_below_count = fields.Integer(string='My Below Target Count', compute='_compute_dashboard_metrics')
    
    # Deadline & Gap Trend Analytics
    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_dashboard_metrics')
    previous_avg_gap = fields.Float(string='Previous Cycle Avg Gap', compute='_compute_dashboard_metrics')
    gap_improvement = fields.Float(string='Gap Improvement', compute='_compute_dashboard_metrics')
    gap_trend_label = fields.Char(string='Gap Trend', compute='_compute_dashboard_metrics')

    my_idp_id = fields.Many2one('competency.idp', string='My Development Plan (IDP)', compute='_compute_dashboard_metrics')
    my_idp_state = fields.Char(string='IDP Status', compute='_compute_dashboard_metrics')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        return res

    def _compute_dashboard_metrics(self):
        today = fields.Date.context_today(self)
        user = self.env.user
        emp = user.employee_id

        # Active Cycle
        active_cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        if not active_cycle:
            active_cycle = self.env['competency.assessment.cycle'].search([('state', '!=', 'closed')], limit=1)

        # Active Competencies
        total_comps = self.env['competency.competency'].search_count([('status', '=', 'active')])

        # Bank Total Completed Assessments
        total_bank_asm = self.env['competency.assessment'].search_count([('state', 'in', ['approved', 'locked'])])
        
        # Bank Avg Gap
        all_lines = self.env['competency.assessment.line'].search([('assessment_id.state', 'in', ['approved', 'locked'])])
        gaps = [l.gap for l in all_lines if l.gap is not None]
        bank_avg = round(sum(gaps) / len(gaps), 2) if gaps else 0.0

        for rec in self:
            rec.active_cycle_id = active_cycle.id if active_cycle else False
            rec.active_cycle_name = active_cycle.name if active_cycle else _('No Active Cycle')
            rec.active_cycle_deadline = active_cycle.assessment_deadline if active_cycle else False
            if active_cycle and active_cycle.assessment_deadline:
                rec.days_remaining = max(0, (active_cycle.assessment_deadline - today).days)
            else:
                rec.days_remaining = 0

            rec.user_employee_id = emp.id if emp else False
            rec.total_active_competencies = total_comps
            rec.total_bank_assessments = total_bank_asm
            rec.overall_bank_avg_gap = bank_avg

            if emp:
                my_asm_list = self.env['competency.assessment'].search([
                    ('employee_id', '=', emp.id)
                ], order='id desc', limit=2)
                
                my_asm = my_asm_list[0] if len(my_asm_list) > 0 else False
                prev_asm = my_asm_list[1] if len(my_asm_list) > 1 else False
                
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
                        rec.gap_trend_label = _("Improved by %s points") % diff
                    elif diff < 0:
                        rec.gap_trend_label = _("Gap increased by %s points") % abs(diff)
                    else:
                        rec.gap_trend_label = _("Maintained")
                else:
                    rec.previous_avg_gap = 0.0
                    rec.gap_improvement = 0.0
                    rec.gap_trend_label = _("Baseline Cycle")

                my_idp = self.env['competency.idp'].search([
                    ('employee_id', '=', emp.id)
                ], order='id desc', limit=1)
                if my_idp:
                    rec.my_idp_id = my_idp.id
                    rec.my_idp_state = dict(my_idp._fields['state'].selection).get(my_idp.state, my_idp.state)
                else:
                    rec.my_idp_id = False
                    rec.my_idp_state = _('None')
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
                rec.my_idp_id = False
                rec.my_idp_state = _('None')

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

        cycle = self.active_cycle_id or self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        if not cycle:
            cycle = self.env['competency.assessment.cycle'].search([('state', '!=', 'closed')], limit=1)
        if not cycle:
            raise models.UserError(_('There is currently no open Assessment Cycle.'))

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
            new_asm.action_auto_fill_lines()
            res_id = new_asm.id

        return {
            'type': 'ir.actions.act_window',
            'name': 'My Self-Assessment',
            'res_model': 'competency.assessment',
            'res_id': res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_my_idp(self):
        self.ensure_one()
        if self.my_idp_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'My Individual Development Plan',
                'res_model': 'competency.idp',
                'res_id': self.my_idp_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Individual Development Plans',
                'res_model': 'competency.idp',
                'view_mode': 'list,form',
                'domain': [('employee_id', '=', self.user_employee_id.id)] if self.user_employee_id else [],
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
