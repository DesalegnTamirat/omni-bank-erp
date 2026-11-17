# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError, AccessError


class SuccessionPlanEarlyCompletionWizard(models.TransientModel):
    """
    Wizard to record early completion of a Successor Development Plan.
    Enforces mandatory justification (text only — no category required),
    validates early completion dates, optionally completes active activities,
    and promotes candidate readiness.
    Can be submitted by the candidate's Manager or PPDD Officer.
    """
    _name = 'succession.plan.early.completion.wizard'
    _description = 'Complete Succession Plan Ahead of Schedule'

    plan_id = fields.Many2one('succession.development.plan', required=True, readonly=True)
    candidate_id = fields.Many2one(
        related='plan_id.candidate_id', string='Candidate', readonly=True)
    employee_id = fields.Many2one(
        related='plan_id.employee_id', string='Employee', readonly=True)
    critical_position_id = fields.Many2one(
        related='plan_id.critical_position_id', string='Target Critical Position', readonly=True)
    plan_start_date = fields.Date(
        related='plan_id.start_date', string='Plan Start Date', readonly=True)
    planned_end_date = fields.Date(
        related='plan_id.end_date', string='Planned End Date', readonly=True)

    actual_completion_date = fields.Date(
        string='Actual Completion Date', default=fields.Date.today, required=True)
    days_ahead = fields.Integer(
        string='Days Ahead of Schedule', compute='_compute_days_ahead')

    # Justification only — single mandatory textarea
    justification = fields.Text(
        string='Justification', required=True,
        help='Substantive justification explaining why the development plan '
             'was completed ahead of schedule (minimum 15 characters).')

    completion_evaluation = fields.Text(
        string='Final Outcome / Evaluation Notes')

    close_remaining_activities = fields.Boolean(
        string='Complete All In-Progress Activities', default=True,
        help='Automatically set progress to 100% and status to Completed for any remaining planned or in-progress activities.')

    update_candidate_readiness = fields.Boolean(
        string='Promote Candidate Readiness to "Ready Now"', default=True,
        help='Check to automatically upgrade the candidate readiness level to Ready Now upon early plan completion.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan_id = self.env.context.get('default_plan_id')
        if plan_id:
            plan = self.env['succession.development.plan'].browse(plan_id)
            res['plan_id'] = plan.id
        return res

    @api.depends('actual_completion_date', 'planned_end_date')
    def _compute_days_ahead(self):
        for rec in self:
            if rec.planned_end_date and rec.actual_completion_date:
                rec.days_ahead = max((rec.planned_end_date - rec.actual_completion_date).days, 0)
            else:
                rec.days_ahead = 0

    @api.constrains('actual_completion_date', 'justification')
    def _check_early_completion_constraints(self):
        for rec in self:
            if rec.plan_start_date and rec.actual_completion_date < rec.plan_start_date:
                raise ValidationError(_('Actual Completion Date cannot be earlier than Plan Start Date (%s).') % rec.plan_start_date)
            if rec.planned_end_date and rec.actual_completion_date >= rec.planned_end_date:
                raise ValidationError(_(
                    'Early completion requires the actual completion date (%s) to be strictly before the planned end date (%s).\n'
                    'If the plan ended on or after this date, please use the standard "Mark Completed" action.') % (
                        rec.actual_completion_date, rec.planned_end_date))
            if not rec.justification or len(rec.justification.strip()) < 15:
                raise ValidationError(_('Please provide a substantive justification (at least 15 characters) explaining the early completion.'))

    def _validate_manager_or_ppdd_access(self):
        """Allow PPDD, Admin, or the candidate's direct Manager."""
        self.ensure_one()
        user = self.env.user
        is_ppdd = user.has_group('bunna_succession_management.group_succession_ppdd')
        is_admin = user.has_group('bunna_succession_management.group_succession_admin')
        is_manager = (
            self.plan_id.employee_id.parent_id.user_id == user
        )
        if not (is_ppdd or is_admin or is_manager):
            raise AccessError(_(
                'Only the candidate\'s direct Manager or a PPDD Officer can '
                'complete a development plan ahead of schedule.'))

    def action_confirm_early_completion(self):
        self.ensure_one()
        self._validate_manager_or_ppdd_access()
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
                    'outcome_notes': (act.outcome_notes or '') + '\n' + _('Completed ahead of schedule on %s.') % self.actual_completion_date,
                })

        # Update Plan — single justification recorded
        plan.with_context(force_write=True).write({
            'state': 'completed_ahead',
            'completion_type': 'early',
            'actual_completion_date': self.actual_completion_date,
            'early_completion_reason': self.justification,
            'completion_notes': self.justification,
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

        # Post audit log
        plan.message_post(body=_(
            '<b>Successor Development Plan %(name)s marked as COMPLETED AHEAD OF SCHEDULE</b><br/>'
            '<ul>'
            '<li><b>Actual Completion Date:</b> %(date)s (%(days)d days early)</li>'
            '<li><b>Completed By:</b> %(user)s (%(role)s)</li>'
            '<li><b>Justification:</b> %(reason)s</li>'
            '</ul>'
        ) % {
            'name': plan.name,
            'date': self.actual_completion_date,
            'days': self.days_ahead,
            'user': self.env.user.name,
            'role': 'Manager' if plan.employee_id.parent_id.user_id == self.env.user else 'PPDD Officer',
            'reason': self.justification,
        })

        # Log candidate governance event
        if hasattr(plan.candidate_id, '_log_candidate_event'):
            plan.candidate_id._log_candidate_event(
                'development_completed_early',
                'Development Plan %s completed %d days ahead of schedule. Submitted by: %s. Reason: %s' % (
                    plan.name, self.days_ahead, self.env.user.name, self.justification)
            )

        return {'type': 'ir.actions.act_window_close'}
