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
        compute='_compute_latest_competency_assessment', store=False,
        help="Points to the employee's most recent approved/completed competency evaluation.")
    latest_competency_overall_score = fields.Float(
        string='Latest Competency Score (%)',
        compute='_compute_latest_competency_assessment', store=False,
        help="Overall weighted score percentage achieved in the latest evaluation.")
    latest_competency_assessment_date = fields.Date(
        string='Latest Assessment Date',
        compute='_compute_latest_competency_assessment', store=False)
    latest_competency_gap_summary = fields.Text(
        string='Latest Competency Gap Summary',
        compute='_compute_latest_competency_assessment', store=False,
        help="Summary of competency requirements, achieved levels, and gaps for Career Path and external analytics.")

    is_director_or_chief = fields.Boolean(
        string='Is Director or Chief',
        compute='_compute_is_director_or_chief',
        search='_search_is_director_or_chief',
        store=False,
        help="Designates whether the employee holds Grade XVI (Director) or Grade XVII (Chief)."
    )

    def _search_is_director_or_chief(self, operator, value):
        peer_config_model = self.env['competency.director.peer.config']
        all_active = self.env['hr.employee'].search([('active', '=', True)])
        matched_ids = [e.id for e in all_active if peer_config_model._is_director_or_chief(e)]

        is_true = (operator in ('=', '==') and bool(value)) or (operator in ('!=', '<>') and not bool(value))
        if is_true:
            return [('id', 'in', matched_ids)]
        else:
            return [('id', 'not in', matched_ids)]

    @api.depends('job_grade', 'grade_id', 'job_id', 'active')
    def _compute_is_director_or_chief(self):
        peer_config_model = self.env['competency.director.peer.config']
        for emp in self:
            emp.is_director_or_chief = peer_config_model._is_director_or_chief(emp)


    @api.depends('competency_assessment_ids', 'competency_assessment_ids.state', 'competency_assessment_ids.create_date', 'competency_assessment_ids.line_ids')
    def _compute_latest_competency_assessment(self):
        for emp in self:
            assessments = emp.competency_assessment_ids.filtered(
                lambda a: a.state in ('approved', 'locked')
            ).sorted(key=lambda a: (a.create_date or fields.Datetime.now(), a.id), reverse=True)
            if not assessments:
                # Fallback to any assessment if none approved
                assessments = emp.competency_assessment_ids.sorted(key=lambda a: (a.create_date or fields.Datetime.now(), a.id), reverse=True)

            latest = assessments[0] if assessments else False
            if latest:
                emp.latest_competency_assessment_id = latest.id
                emp.latest_competency_overall_score = getattr(latest, 'average_gap', 0.0) or 0.0
                emp.latest_competency_assessment_date = fields.Date.to_date(latest.create_date) if latest.create_date else False

                lines_summary = []
                for line in getattr(latest, 'line_ids', []):
                    comp_name = line.competency_id.name if line.competency_id else 'N/A'
                    req_lvl = line.required_level or 'N/A'
                    ach_lvl = line.current_level or 'N/A'
                    gap = getattr(line, 'gap', 0) or 0
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
                'average_gap': 0.0,
                'cycle_name': False,
                'state': False,
                'lines': [],
            }

        line_data = []
        for line in getattr(latest, 'line_ids', []):
            comp = line.competency_id
            line_data.append({
                'competency_id': comp.id if comp else False,
                'competency_name': comp.name if comp else '',
                'pillar': comp.pillar if comp else '',
                'required_level': line.required_level or '1',
                'current_level': line.current_level or '0',
                'weighted_current_level': line.weighted_current_level or 0.0,
                'gap': getattr(line, 'gap', 0.0) or 0.0,
            })

        return {
            'employee_id': self.id,
            'employee_name': self.name,
            'has_assessment': True,
            'assessment_id': latest.id,
            'evaluation_date': fields.Date.to_date(latest.create_date) if latest.create_date else False,
            'overall_score': getattr(latest, 'average_gap', 0.0) or 0.0,
            'average_gap': getattr(latest, 'average_gap', 0.0) or 0.0,
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
        compute='_compute_baseline_assessment_deadline',
        store=False,
        help='Automatically set to 3 months (90 days) from hire or employee creation.'
    )

    def _compute_baseline_assessment_deadline(self):
        for emp in self:
            base_date = fields.Date.to_date(emp.create_date) if emp.create_date else fields.Date.today()
            emp.baseline_assessment_deadline = base_date + timedelta(days=90)

    is_eligible_for_promotion = fields.Boolean(
        string='Eligible for Promotion',
        compute='_compute_is_eligible_for_promotion',
        store=False,
        help='False if employee missed baseline assessment deadline.'
    )

    @api.depends('competency_assessment_ids.state')
    def _compute_is_eligible_for_promotion(self):
        today = fields.Date.context_today(self)
        for emp in self:
            # Check baseline deadline compliance
            has_logged_assessment = bool(emp.competency_assessment_ids.filtered(lambda a: a.state in ('approved', 'locked')))
            missed_baseline = bool(emp.baseline_assessment_deadline and emp.baseline_assessment_deadline < today and not has_logged_assessment)
            emp.is_eligible_for_promotion = not missed_baseline

    @api.model
    def _cron_baseline_assessment_reminders(self):
        """Cron action: Sends reminders to supervisor 14 days before baseline deadline if no assessment logged."""
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=14)
        target_create_date = target_date - timedelta(days=90)
        employees_due = self.search([
            ('create_date', '>=', f"{target_create_date} 00:00:00"),
            ('create_date', '<=', f"{target_create_date} 23:59:59"),
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
