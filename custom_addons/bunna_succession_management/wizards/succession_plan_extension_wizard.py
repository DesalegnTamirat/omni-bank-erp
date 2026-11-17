# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError, AccessError


class SuccessionPlanExtensionWizard(models.TransientModel):
    """
    Dedicated Executive Plan Extension Wizard.
    Simplified: only a justification text field (no root-cause dropdown).
    The Manager or PPDD Officer submits — extension is applied directly.
    All extensions are recorded in the governance audit trail.
    """
    _name = 'succession.plan.extension.wizard'
    _description = 'Extend Successor Development Plan'

    plan_id = fields.Many2one('succession.development.plan', required=True, readonly=True, index=True)
    candidate_id = fields.Many2one(
        related='plan_id.candidate_id', string='Candidate', readonly=True, index=True)
    employee_id = fields.Many2one(
        related='plan_id.employee_id', string='Employee', readonly=True, index=True)
    critical_position_id = fields.Many2one(
        related='plan_id.critical_position_id', string='Target Critical Position', readonly=True, index=True)
    current_end_date = fields.Date(
        related='plan_id.end_date', string='Current End Date', readonly=True)
    original_end_date = fields.Date(
        related='plan_id.original_end_date', string='Baseline End Date', readonly=True)
    extension_count = fields.Integer(
        related='plan_id.extension_count', string='Previous Extensions', readonly=True)

    proposed_end_date = fields.Date(
        string='Proposed Revised End Date', required=True)
    days_extended = fields.Integer(
        string='Additional Days Requested', compute='_compute_days_extended')

    # Justification only — root_cause dropdown removed per business decision
    justification = fields.Text(
        string='Mandatory Justification / Root Cause Analysis', required=True,
        help='Detailed explanation explaining why extra time is required to fulfill '
             'development objectives. Must be substantive (min 15 characters).')

    remedial_plan = fields.Text(
        string='Remedial Action Plan',
        help='Specific milestones and actions planned to ensure the plan finishes within the revised timeline.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan_id = self.env.context.get('default_plan_id')
        if plan_id:
            plan = self.env['succession.development.plan'].browse(plan_id)
            res['plan_id'] = plan.id
            if plan.end_date:
                # default to 30 days after current end date
                res['proposed_end_date'] = fields.Date.add(plan.end_date, days=30)
        return res

    @api.depends('proposed_end_date', 'current_end_date')
    def _compute_days_extended(self):
        for rec in self:
            if rec.proposed_end_date and rec.current_end_date:
                rec.days_extended = max((rec.proposed_end_date - rec.current_end_date).days, 0)
            else:
                rec.days_extended = 0

    @api.constrains('proposed_end_date', 'justification')
    def _check_extension_constraints(self):
        for rec in self:
            if rec.current_end_date and rec.proposed_end_date <= rec.current_end_date:
                raise ValidationError(_(
                    'Proposed Revised End Date (%s) must be strictly after the Current End Date (%s).') % (
                        rec.proposed_end_date, rec.current_end_date))
            if not rec.justification or len(rec.justification.strip()) < 15:
                raise ValidationError(_('Please provide a substantive justification (at least 15 characters) for extending the plan.'))

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
                'apply a development plan extension.'))

    def action_apply_extension(self):
        """Apply extension — single action for both Manager and PPDD."""
        self.ensure_one()
        self._validate_manager_or_ppdd_access()
        plan = self.plan_id
        if plan.state not in ('active', 'extended', 'extension_pending'):
            raise UserError(_('Only active or extended development plans can be extended.'))

        prev_end = plan.end_date
        if not plan.original_end_date:
            plan.original_end_date = prev_end

        new_count = plan.extension_count + 1
        days_added = (self.proposed_end_date - prev_end).days
        submitted_by = self.env.user

        # Create history log
        self.env['succession.development.plan.extension.log'].create({
            'plan_id': plan.id,
            'extension_number': new_count,
            'old_end_date': prev_end,
            'new_end_date': self.proposed_end_date,
            'days_extended': days_added,
            'justification': self.justification,
            'remedial_plan': self.remedial_plan or '',
            'requested_by_id': submitted_by.id,
            'request_date': fields.Date.today(),
            'approved_by_id': submitted_by.id,
            'approval_date': fields.Date.today(),
            'status': 'approved',
        })

        # Update plan
        plan.with_context(force_write=True).write({
            'end_date': self.proposed_end_date,
            'extension_count': new_count,
            'state': 'extended',
            'proposed_end_date': False,
            'extension_reason': self.justification,
            'extension_remedial_plan': self.remedial_plan,
        })

        msg_lines = [
            '<b>%s</b><br/>' % _('Successor Development Plan Extended'),
            '<ul>',
            '<li><b>%s:</b> %s (+%d days)</li>' % (_('Revised End Date'), self.proposed_end_date, days_added),
            '<li><b>%s:</b> #%d</li>' % (_('Extension Cycle'), new_count),
            '<li><b>%s:</b> %s (%s)</li>' % (
                _('Applied By'),
                submitted_by.name,
                'Manager' if plan.employee_id.parent_id.user_id == submitted_by else 'PPDD Officer'
            ),
            '<li><b>%s:</b> %s</li>' % (_('Justification'), self.justification),
        ]
        if self.remedial_plan:
            msg_lines.append('<li><b>%s:</b> %s</li>' % (_('Remedial Plan'), self.remedial_plan))
        msg_lines.append('</ul>')
        plan.message_post(body=''.join(msg_lines))

        # Log candidate governance event
        if hasattr(plan.candidate_id, '_log_candidate_event'):
            plan.candidate_id._log_candidate_event(
                'development_extended',
                'Development Plan %s extended to %s (+%d days). Submitted by: %s. Reason: %s' % (
                    plan.name, self.proposed_end_date, days_added, submitted_by.name, self.justification)
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Plan Extension Applied'),
                'message': _('Development Plan %s extension applied. Revised End Date: %s (+%d days).') % (plan.name, self.proposed_end_date, days_added),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
