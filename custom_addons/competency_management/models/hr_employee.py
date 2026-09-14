# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _


class HrEmployeeCompetency(models.Model):
    """hr.employee extension: competency profile smart buttons."""
    _inherit = 'hr.employee'

    competency_assessment_ids = fields.One2many(
        'competency.assessment', 'employee_id', string='Competency Assessments')
    competency_assessment_count = fields.Integer(
        string='Competency Assessments', compute='_compute_competency_assessment_count')

    latest_competency_assessment_id = fields.Many2one(
        'competency.assessment', string='Latest Competency Assessment',
        compute='_compute_latest_competency_assessment', store=True,
        help="Points to the employee's most recent approved/completed competency evaluation.")
    latest_competency_overall_score = fields.Float(
        string='Latest Competency Score (%)',
        compute='_compute_latest_competency_assessment', store=True,
        help="Overall weighted score percentage achieved in the latest evaluation.")
    latest_competency_assessment_date = fields.Date(
        string='Latest Assessment Date',
        compute='_compute_latest_competency_assessment', store=True)
    latest_competency_gap_summary = fields.Text(
        string='Latest Competency Gap Summary',
        compute='_compute_latest_competency_assessment',
        help="Summary of competency requirements, achieved levels, and gaps for Career Path and external analytics.")

    @api.depends('competency_assessment_ids', 'competency_assessment_ids.state', 'competency_assessment_ids.overall_score', 'competency_assessment_ids.evaluation_date')
    def _compute_latest_competency_assessment(self):
        for emp in self:
            assessments = emp.competency_assessment_ids.filtered(
                lambda a: a.state in ('approved', 'completed', 'locked') or not a.state
            ).sorted(key=lambda a: (a.evaluation_date or fields.Date.today(), a.id), reverse=True)
            if not assessments:
                # Fallback to any assessment if none approved
                assessments = emp.competency_assessment_ids.sorted(key=lambda a: (a.evaluation_date or fields.Date.today(), a.id), reverse=True)

            latest = assessments[0] if assessments else False
            if latest:
                emp.latest_competency_assessment_id = latest.id
                emp.latest_competency_overall_score = getattr(latest, 'overall_score', 0.0) or 0.0
                emp.latest_competency_assessment_date = getattr(latest, 'evaluation_date', False) or False

                lines_summary = []
                for line in getattr(latest, 'line_ids', []):
                    comp_name = line.competency_id.name if line.competency_id else 'N/A'
                    req_lvl = line.required_level_id.name if getattr(line, 'required_level_id', False) else 'N/A'
                    ach_lvl = line.achieved_level_id.name if getattr(line, 'achieved_level_id', False) else 'N/A'
                    gap = getattr(line, 'gap', 0.0) or 0.0
                    lines_summary.append(f"- {comp_name}: Required={req_lvl}, Achieved={ach_lvl}, Gap={gap}")
                emp.latest_competency_gap_summary = "\n".join(lines_summary) if lines_summary else "No line details available."
            else:
                emp.latest_competency_assessment_id = False
                emp.latest_competency_overall_score = 0.0
                emp.latest_competency_assessment_date = False
                emp.latest_competency_gap_summary = "No competency assessment logged."

    def get_latest_competency_evaluation(self):
        """API helper method for Career Path, HR Analytics, and external modules to fetch the employee's latest evaluation."""
        self.ensure_one()
        latest = self.latest_competency_assessment_id
        if not latest:
            return {
                'employee_id': self.id,
                'employee_name': self.name,
                'has_assessment': False,
                'assessment_id': False,
                'evaluation_date': False,
                'overall_score': 0.0,
                'cycle_name': False,
                'state': False,
                'lines': [],
            }

        line_data = []
        for line in getattr(latest, 'line_ids', []):
            line_data.append({
                'competency_id': line.competency_id.id if line.competency_id else False,
                'competency_name': line.competency_id.name if line.competency_id else '',
                'required_level_id': line.required_level_id.id if getattr(line, 'required_level_id', False) else False,
                'required_level_name': line.required_level_id.name if getattr(line, 'required_level_id', False) else '',
                'achieved_level_id': line.achieved_level_id.id if getattr(line, 'achieved_level_id', False) else False,
                'achieved_level_name': line.achieved_level_id.name if getattr(line, 'achieved_level_id', False) else '',
                'gap': getattr(line, 'gap', 0.0) or 0.0,
            })

        return {
            'employee_id': self.id,
            'employee_name': self.name,
            'has_assessment': True,
            'assessment_id': latest.id,
            'evaluation_date': latest.evaluation_date or False,
            'overall_score': getattr(latest, 'overall_score', 0.0) or 0.0,
            'cycle_name': latest.cycle_id.name if getattr(latest, 'cycle_id', False) else '',
            'state': latest.state or '',
            'lines': line_data,
        }

    @api.depends('competency_assessment_ids')
    def _compute_competency_assessment_count(self):
        for rec in self:
            rec.competency_assessment_count = len(rec.competency_assessment_ids)

    baseline_assessment_deadline = fields.Date(
        string='Baseline Assessment Deadline',
        help='Automatically set to 3 months (90 days) from hire or job/department position change.'
    )
    is_eligible_for_promotion = fields.Boolean(
        string='Eligible for Promotion',
        compute='_compute_is_eligible_for_promotion',
        store=True,
        help='False if employee missed baseline assessment deadline.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('baseline_assessment_deadline'):
                vals['baseline_assessment_deadline'] = fields.Date.context_today(self) + timedelta(days=90)
        return super().create(vals_list)

    def write(self, vals):
        if 'job_id' in vals or 'department_id' in vals:
            vals['baseline_assessment_deadline'] = fields.Date.context_today(self) + timedelta(days=90)
        return super().write(vals)

    @api.depends('baseline_assessment_deadline', 'competency_assessment_ids.state')
    def _compute_is_eligible_for_promotion(self):
        today = fields.Date.context_today(self)
        for emp in self:
            # Check baseline deadline compliance
            has_logged_assessment = bool(emp.competency_assessment_ids.filtered(lambda a: a.state in ('approved', 'locked')))
            missed_baseline = bool(emp.baseline_assessment_deadline and emp.baseline_assessment_deadline < today and not has_logged_assessment)
            
            if missed_baseline:
                emp.is_eligible_for_promotion = False
            else:
                emp.is_eligible_for_promotion = True

    @api.model
    def _cron_baseline_assessment_reminders(self):
        """Cron action: Sends reminders to supervisor 14 days before baseline deadline if no assessment logged."""
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=14)
        employees_due = self.search([
            ('baseline_assessment_deadline', '=', target_date),
            ('parent_id', '!=', False)
        ])
        for emp in employees_due:
            has_assessment = emp.competency_assessment_ids.filtered(lambda a: a.state in ('approved', 'locked'))
            if not has_assessment and emp.parent_id.user_id:
                emp.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('REMINDER: Baseline Competency Assessment Due Soon for %s') % emp.name,
                    note=_('3-Month Baseline Assessment deadline for %s is on %s (14 days remaining).') % (emp.name, emp.baseline_assessment_deadline),
                    user_id=emp.parent_id.user_id.id,
                )

    def action_view_competency_assessments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Competency Assessments',
            'res_model': 'competency.assessment',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
        }
