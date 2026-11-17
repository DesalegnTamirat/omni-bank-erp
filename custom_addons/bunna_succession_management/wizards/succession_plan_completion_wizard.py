# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SuccessionPlanCompletionWizard(models.TransientModel):
    """
    Dedicated Executive Plan Completion Wizard.
    Prompts the evaluating manager / PPDD officer to evaluate candidate outcomes
    across all development activity types (mentoring, stretch assignments, job rotation, training),
    rate overall achievement, and optionally promote readiness to Ready Now.
    """
    _name = 'succession.plan.completion.wizard'
    _description = 'Successor Development Plan Completion Evaluation'

    plan_id = fields.Many2one('succession.development.plan', required=True, readonly=True)
    candidate_id = fields.Many2one(
        related='plan_id.candidate_id', string='Candidate', readonly=True)
    employee_id = fields.Many2one(
        related='plan_id.employee_id', string='Employee', readonly=True)
    evaluating_manager_id = fields.Many2one(
        related='plan_id.evaluating_manager_id', string='Assigned Mentor / Evaluator', readonly=True)
    critical_position_id = fields.Many2one(
        related='plan_id.critical_position_id', string='Target Critical Position', readonly=True)
    plan_start_date = fields.Date(
        related='plan_id.start_date', string='Plan Start Date', readonly=True)
    plan_end_date = fields.Date(
        related='plan_id.end_date', string='Plan End Date', readonly=True)

    actual_completion_date = fields.Date(
        string='Actual Completion Date', default=fields.Date.today, required=True)

    achievement_level = fields.Selection([
        ('exceeded', 'Exceeded Expectations - Outstanding Leadership & Mastery'),
        ('met', 'Fully Met Objectives - Demonstrated Target Competencies'),
        ('partially_met', 'Partially Met - Minor Gaps Remaining'),
    ], string='Development Achievement', required=True, default='met')

    activity_summary_display = fields.Text(
        string='Development Activities Summary (By Activity Type)',
        compute='_compute_activity_summary_display', readonly=True)

    completion_evaluation = fields.Text(
        string='Mandatory Manager Evaluation & Justification', required=True,
        help='Detailed evaluation notes documenting candidate performance, acquired competencies, and verification across each activity type (mentoring, stretch assignments, rotation, training).')

    close_remaining_activities = fields.Boolean(
        string='Mark Incomplete Activities as Completed', default=True,
        help='Automatically set status to Completed (100% progress) for any activities currently in progress or planned.')

    update_candidate_readiness = fields.Boolean(
        string='Promote Candidate Readiness to "Ready Now"', default=True,
        help='Upgrade candidate readiness level to Ready Now upon successful plan completion.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan_id = self.env.context.get('default_plan_id')
        if plan_id:
            plan = self.env['succession.development.plan'].browse(plan_id)
            res['plan_id'] = plan.id
            res['completion_evaluation'] = plan.completion_notes or ''
        return res

    @api.depends('plan_id', 'plan_id.development_activity_ids')
    def _compute_activity_summary_display(self):
        for rec in self:
            acts = rec.plan_id.development_activity_ids
            if not acts:
                rec.activity_summary_display = 'No activities recorded.'
                continue
            lines = []
            for a in acts:
                type_label = dict(a._fields['activity_type'].selection).get(a.activity_type, a.activity_type)
                status_label = dict(a._fields['status'].selection).get(a.status, a.status)
                lines.append(f"• [{type_label}] {a.activity_description} — Status: {status_label} ({a.progress_percent}%)")
            rec.activity_summary_display = '\n'.join(lines)

    @api.constrains('completion_evaluation')
    def _check_evaluation(self):
        for rec in self:
            if not rec.completion_evaluation or len(rec.completion_evaluation.strip()) < 15:
                raise ValidationError(_(
                    'Substantive Evaluation Required!\n'
                    'Please provide at least 15 characters documenting candidate performance across the development activity types.'))

    def action_confirm_completion(self):
        self.ensure_one()
        plan = self.plan_id
        if plan.state not in ('active', 'extended'):
            raise UserError(_('Only active or extended development plans can be completed.'))

        # Close activities if requested
        if self.close_remaining_activities:
            pending_acts = plan.development_activity_ids.filtered(
                lambda a: a.status in ('planned', 'in_progress'))
            for act in pending_acts:
                act.write({
                    'status': 'completed',
                    'progress_percent': 100,
                    'outcome_notes': (act.outcome_notes or '') + '\n' + _('Verified and marked completed on %s.') % self.actual_completion_date,
                })

        comp_type = 'extended' if plan.extension_count > 0 else 'standard'
        achievement_label = dict(self._fields['achievement_level'].selection).get(self.achievement_level, '')

        # Update Plan
        plan.with_context(force_write=True).write({
            'state': 'completed',
            'completion_type': comp_type,
            'actual_completion_date': self.actual_completion_date,
            'completion_notes': self.completion_evaluation,
            'achievement_level': self.achievement_level,
            'completed_by_id': self.env.user.id,
        })

        # Upgrade Candidate Readiness if requested
        if self.update_candidate_readiness and plan.candidate_id:
            ready_now = self.env['succession.readiness.level'].search([
                ('is_ready_for_deployment', '=', True)
            ], limit=1)
            if not ready_now:
                ready_now = self.env['succession.readiness.level'].search([
                    ('code', '=', 'ready_now')
                ], limit=1)
            if ready_now:
                plan.candidate_id.write({'readiness_level_id': ready_now.id})

        # Post audit log in plan chatter
        plan.message_post(body=_(
            '<b>Successor Development Plan %(name)s marked as COMPLETED</b><br/>'
            '<ul>'
            '<li><b>Completion Type:</b> %(ctype)s</li>'
            '<li><b>Actual Completion Date:</b> %(date)s</li>'
            '<li><b>Achievement Level:</b> %(ach)s</li>'
            '<li><b>Sign-Off Completed By:</b> %(user)s</li>'
            '<li><b>Assigned Mentor / Evaluator:</b> %(mentor)s</li>'
            '<li><b>Evaluation &amp; Justification:</b> %(notes)s</li>'
            '</ul>'
        ) % {
            'name': plan.name,
            'ctype': dict(plan._fields['completion_type'].selection).get(comp_type, ''),
            'date': self.actual_completion_date,
            'ach': achievement_label,
            'user': self.env.user.name,
            'mentor': plan.evaluating_manager_id.name if plan.evaluating_manager_id else 'Not assigned',
            'notes': self.completion_evaluation,
        })

        # Log candidate governance event
        if hasattr(plan.candidate_id, '_log_candidate_event'):
            plan.candidate_id._log_candidate_event(
                'note',
                'Development Plan %s completed on schedule. Achievement: %s. Evaluation: %s' % (
                    plan.name, achievement_label, self.completion_evaluation)
            )

        return {'type': 'ir.actions.act_window_close'}
