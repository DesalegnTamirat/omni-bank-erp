# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class CompetencyReportWizard(models.TransientModel):
    """Ad-hoc Report Filtering & Export Wizard (FR-RPT-007, FR-RPT-009)."""
    _name = 'competency.report.wizard'
    _description = 'Competency Ad-Hoc Report Filter Wizard'

    cycle_id = fields.Many2one(
        'competency.assessment.cycle', string='Assessment Cycle', required=True,
        default=lambda self: self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1))
    department_ids = fields.Many2many('hr.department', string='Departments')
    pillar = fields.Selection([
        ('all', 'All Pillars'),
        ('core', 'Core Pillar'),
        ('leadership', 'Leadership Pillar'),
        ('technical', 'Technical Pillar'),
    ], string='Competency Pillar', default='all', required=True)
    
    report_type = fields.Selection([
        ('org_capability', 'Organizational Capability Report (Admin/PPDD)'),
        ('team_gap', 'Team Competency Gap Report (Supervisor)'),
        ('individual', 'Individual Competency Profile Report (Employee)'),
    ], string='Report Type', default='org_capability', required=True)
    
    employee_id = fields.Many2one('hr.employee', string='Employee Filter (For Individual Tier)')

    def action_print_pdf(self):
        """Generates QWeb PDF report according to selected filters."""
        self.ensure_one()
        if self.report_type == 'individual':
            emp = self.employee_id or self.env.user.employee_id
            asm = self.env['competency.assessment'].search([
                ('employee_id', '=', emp.id if emp else 0),
                ('cycle_id', '=', self.cycle_id.id)
            ], limit=1)
            if not asm:
                raise models.UserError(_("No assessment found for employee %s in cycle %s.") % (emp.name if emp else 'N/A', self.cycle_id.name))
            return self.env.ref('competency_management.action_report_competency_assessment_individual').report_action(asm)
        elif self.report_type == 'team_gap':
            return self.env.ref('competency_management.action_report_competency_team_gap').report_action(self)
        else:
            return self.env.ref('competency_management.action_report_competency_org_capability').report_action(self)

    def get_org_capability_data(self):
        """Computes aggregate analytics data for Tier 3 Admin report."""
        self.ensure_one()
        cycle = self.cycle_id
        dept_domain = [('id', 'in', self.department_ids.ids)] if self.department_ids else []
        departments = self.env['hr.department'].search(dept_domain, limit=15)
        
        # 1. Framework Health Summary
        active_comps = self.env['competency.competency'].search([('status', '=', 'active')])
        core_cnt = len(active_comps.filtered(lambda c: c.pillar == 'core'))
        lead_cnt = len(active_comps.filtered(lambda c: c.pillar == 'leadership'))
        tech_cnt = len(active_comps.filtered(lambda c: c.pillar == 'technical'))
        
        # 2. Mapping Coverage
        total_jobs = self.env['hr.job'].search_count([])
        mapped_job_ids = self.env['competency.role.mapping'].search([('state', '=', 'approved')]).mapped('job_position_id.id')
        mapped_count = len(set(mapped_job_ids))
        coverage_pct = round((mapped_count / total_jobs * 100), 1) if total_jobs else 0.0
        
        # 3. High-Priority Gaps
        line_domain = [('cycle_id', '=', cycle.id)]
        if self.department_ids:
            line_domain.append(('department_id', 'in', self.department_ids.ids))
        if self.pillar != 'all':
            line_domain.append(('pillar', '=', self.pillar))
            
        lines = self.env['competency.assessment.line'].search(line_domain)
        high_gap_lines = lines.filtered(lambda l: l.gap_priority == 'high')
        
        # Group by competency
        comp_gap_counts = {}
        for l in high_gap_lines:
            cname = l.competency_id.name
            comp_gap_counts[cname] = comp_gap_counts.get(cname, 0) + 1
            
        top_gaps = sorted(comp_gap_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # 4. Department Completion Rate
        dept_completion = []
        for dept in departments:
            dept_asms = self.env['competency.assessment'].search([('cycle_id', '=', cycle.id), ('department_id', '=', dept.id)])
            total_d = len(dept_asms)
            approved_d = len(dept_asms.filtered(lambda a: a.state in ('approved', 'locked')))
            pct_d = round((approved_d / total_d * 100), 1) if total_d else 0.0
            dept_completion.append({
                'name': dept.name,
                'total': total_d,
                'approved': approved_d,
                'rate': pct_d
            })
            
        return {
            'core_cnt': core_cnt,
            'lead_cnt': lead_cnt,
            'tech_cnt': tech_cnt,
            'total_jobs': total_jobs,
            'mapped_count': mapped_count,
            'coverage_pct': coverage_pct,
            'top_gaps': top_gaps,
            'dept_completion': dept_completion,
            'departments': departments,
            'lines': lines,
        }

    def get_team_gap_data(self):
        """Computes team data for Tier 2 Supervisor report."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        
        # Direct reports
        subordinates = self.env['hr.employee'].search([('parent_id', '=', emp.id if emp else 0)])
        if not subordinates and emp and emp.department_id and emp.department_id.manager_id.id == emp.id:
            subordinates = self.env['hr.employee'].search([('department_id', '=', emp.department_id.id), ('id', '!=', emp.id)])
            
        team_asms = self.env['competency.assessment'].search([
            ('employee_id', 'in', subordinates.ids),
            ('cycle_id', '=', self.cycle_id.id)
        ])
        
        lines = team_asms.mapped('line_ids')
        total_members = len(subordinates)
        assessed_members = len(team_asms)
        completion_rate = round((assessed_members / total_members * 100), 1) if total_members else 0.0
        
        below_count = len(lines.filtered(lambda l: l.achievement_status == 'below'))
        meets_count = len(lines.filtered(lambda l: l.achievement_status == 'meets'))
        exceeds_count = len(lines.filtered(lambda l: l.achievement_status == 'exceeds'))
        avg_gap = round(sum([l.gap for l in lines if l.gap]) / len(lines), 1) if lines else 0.0
        
        member_roster = []
        for sub in subordinates:
            sub_asm = team_asms.filtered(lambda a: a.employee_id.id == sub.id)
            if sub_asm:
                status_str = dict(sub_asm[0]._fields['state'].selection).get(sub_asm[0].state, sub_asm[0].state)
                sub_lines = sub_asm[0].line_ids
                top_gaps = sub_lines.filtered(lambda l: l.achievement_status == 'below').sorted(key=lambda l: l.gap or 0, reverse=True)[:3]
                gap_names = ", ".join([l.competency_id.name for l in top_gaps]) if top_gaps else _("None (Qualified)")
                overall_status = _("Needs Intervention") if top_gaps else _("Fit / Qualified")
            else:
                status_str = _("Not Started")
                gap_names = _("N/A")
                overall_status = _("Pending Assessment")
                
            member_roster.append({
                'name': sub.name,
                'job': sub.job_id.name if sub.job_id else 'N/A',
                'status': status_str,
                'overall_status': overall_status,
                'top_gaps': gap_names
            })
            
        return {
            'supervisor_name': emp.name if emp else user.name,
            'department_name': emp.department_id.name if emp and emp.department_id else 'N/A',
            'total_members': total_members,
            'assessed_members': assessed_members,
            'completion_rate': completion_rate,
            'below_count': below_count,
            'meets_count': meets_count,
            'exceeds_count': exceeds_count,
            'avg_gap': avg_gap,
            'member_roster': member_roster,
        }
