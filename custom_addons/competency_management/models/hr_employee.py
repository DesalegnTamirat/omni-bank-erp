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
