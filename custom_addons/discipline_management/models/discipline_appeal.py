# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineAppeal(models.Model):
    _name = 'discipline.appeal'
    _description = 'Disciplinary Appeal Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'submission_date desc, id desc'

    name = fields.Char(
        string='Appeal Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    
    # Required inverse field for discipline.case appeal_ids (One2many)
    case_id = fields.Many2one(
        'discipline.case',
        string='Original Case',
        required=True,
        ondelete='cascade',
        tracking=True
    )
    
    employee_id = fields.Many2one(
        'hr.employee',
        string='Appellant Employee',
        related='case_id.employee_id',
        store=True,
        readonly=True
    )
    original_offense_id = fields.Many2one(
        'discipline.offense',
        string='Original Offense',
        related='case_id.offense_id',
        readonly=True
    )
    original_decision_date = fields.Date(
        string='Original Decision Date',
        related='case_id.final_decision_date',
        readonly=True
    )

    # Two-Level Appeal Structure
    appeal_level = fields.Selection([
        ('first', '1st Level Appeal'),
        ('second', '2nd Level Appeal'),
    ], string='Appeal Stage', default='first', required=True, tracking=True)

    parent_appeal_id = fields.Many2one('discipline.appeal', string='Prior 1st Level Appeal', tracking=True)

    case_origin_type = fields.Selection([
        ('manager', 'Appeal on Line Manager / Coach Decision'),
        ('committee', 'Appeal on Disciplinary Committee Decision'),
    ], string='Decision Source', compute='_compute_case_origin_type', store=True)

    appeal_target_authority = fields.Selection([
        ('directorate', 'Respective Directorate'),
        ('cpco', 'Chief People & Culture Officer (CPCO)'),
        ('secretary', 'Disciplinary Committee Secretary (POMD)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Designated Appeal Authority', compute='_compute_appeal_target_authority', store=True, tracking=True)

    is_submitted_on_behalf = fields.Boolean(
        string='Submitted on Behalf of Employee',
        default=False,
        help='Submitted by POMD or Committee Secretary on behalf of deactivated or suspended employee.'
    )
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', default=lambda self: self.env.user, tracking=True)

    @api.depends('case_id', 'case_id.initiator_type')
    def _compute_case_origin_type(self):
        for rec in self:
            if rec.case_id and rec.case_id.initiator_type == 'manager':
                rec.case_origin_type = 'manager'
            else:
                rec.case_origin_type = 'committee'

    @api.depends('case_origin_type', 'appeal_level')
    def _compute_appeal_target_authority(self):
        for rec in self:
            if rec.case_origin_type == 'manager':
                rec.appeal_target_authority = 'directorate' if rec.appeal_level == 'first' else 'cpco'
            else:
                rec.appeal_target_authority = 'secretary' if rec.appeal_level == 'first' else 'ceo'

    submission_date = fields.Date(
        string='Appeal Submission Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    appeal_grounds = fields.Text(string='Grounds for Appeal & Justification', required=True)
    supporting_document = fields.Binary(string='Supporting Appeal Document', attachment=True)
    document_filename = fields.Char(string='Document Filename')

    reviewer_id = fields.Many2one('res.users', string='Appeal Authority / Chair', tracking=True)
    review_date = fields.Date(string='Review Date', tracking=True)

    # Appeal Tracking & Decision Outcome
    decision_outcome = fields.Selection([
        ('upheld', 'Original Decision Upheld (Appeal Rejected)'),
        ('overturned', 'Decision Overturned (Exonerated)'),
        ('penalty_reduced', 'Penalty / Action Reduced'),
    ], string='Appeal Decision Outcome', tracking=True)

    revised_penalty_percentage = fields.Float(string='Revised Penalty Percentage (%)', tracking=True)
    revised_fine_days = fields.Float(string='Revised Salary Fine (Days)', tracking=True)
    revised_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / No Action'),
    ], string='Revised Punishment', tracking=True)

    appeal_decision_notes = fields.Text(string='Appeal Board Decision Rationale', tracking=True)

    state = fields.Selection([
        ('submitted', 'Appeal Submitted'),
        ('under_review', 'Under Review'),
        ('decided', 'Final Decision Rendered'),
        ('rejected_expired', 'Rejected (Window Expired)'),
    ], string='Status', default='submitted', required=True, tracking=True)

    # Appeal Window Enforcement (10 Calendar Days)
    @api.constrains('submission_date', 'case_id')
    def _check_appeal_window(self):
        for rec in self:
            if rec.appeal_level == 'second':
                continue
            if rec.case_id:
                base_date = rec.case_id.delivery_receipt_date or rec.case_id.final_decision_date
                if base_date:
                    deadline = base_date + timedelta(days=10)
                    if rec.submission_date > deadline:
                        raise ValidationError(_(
                            'Appeal Window Expired: Policy restricts appeal submission to 10 calendar days '
                            'from the decision notice receipt date (%s). Deadline was %s.'
                        ) % (base_date, deadline))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.appeal') or _('New')
        appeals = super().create(vals_list)
        for app in appeals:
            if app.case_id:
                app.case_id.with_context(force_write=True).write({'state': 'appealed'})
                app.case_id.message_post(body=_('Appeal %s (%s) submitted against Case decision.') % (app.name, app.appeal_level))
        return appeals

    def action_start_review(self):
        for rec in self:
            rec.write({
                'reviewer_id': self.env.user.id,
                'state': 'under_review'
            })

    def action_render_decision(self):
        """Apply appeal decision and update original case outcome."""
        for rec in self:
            if not rec.decision_outcome:
                raise UserError(_('Select an Appeal Decision Outcome before finalizing.'))

            rec.write({
                'review_date': fields.Date.context_today(self),
                'state': 'decided'
            })

            case = rec.case_id
            if not case:
                continue

            if rec.decision_outcome == 'upheld':
                case.with_context(force_write=True).write({'state': 'enforced'})
                case.message_post(body=_('Appeal %s decided: Original decision UPHELD.') % rec.name)

            elif rec.decision_outcome == 'overturned':
                # Revert employee disciplinary marks & restore mobility
                case.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                    'active_disciplinary_action': False,
                    'is_ineligible_for_promotion_transfer': False,
                    'is_suspended': False,
                    'suspension_type': False,
                })
                if case.employee_id.disciplinary_warning_count > 0:
                    case.employee_id.disciplinary_warning_count -= 1
                
                # Reactivate user account if employee had been archived
                if case.employee_id.user_id:
                    case.employee_id.user_id.sudo().write({'active': True})
                if not case.employee_id.active:
                    case.employee_id.sudo().write({'active': True})
                
                # Cancel pending payroll penalties
                if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                    case.payroll_penalty_ids.filtered(lambda p: p.state == 'pending').write({'state': 'cancelled'})
                
                case.with_context(force_write=True).write({'state': 'closed'})
                case.message_post(body=_('Appeal %s decided: Decision OVERTURNED. Employee exonerated and records restored.') % rec.name)

            elif rec.decision_outcome == 'penalty_reduced':
                case.with_context(force_write=True).write({
                    'penalty_percentage': rec.revised_penalty_percentage,
                    'fine_days': rec.revised_fine_days,
                    'state': 'enforced'
                })
                
                # Update pending payroll penalties
                if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                    pending_penalties = case.payroll_penalty_ids.filtered(lambda p: p.state == 'pending')
                    if pending_penalties:
                        pending_penalties.write({
                            'penalty_percentage': rec.revised_penalty_percentage,
                            'managerial_days': int(rec.revised_fine_days) if rec.revised_fine_days > 0 else 0
                        })
                
                case.message_post(body=_('Appeal %s decided: Penalty REDUCED (Pct: %s%%, Days: %s).') % (
                    rec.name, rec.revised_penalty_percentage, rec.revised_fine_days
                ))

    def action_create_second_appeal(self):
        """Submit 2nd Level Appeal if initial appeal was upheld upon review."""
        self.ensure_one()
        if self.state != 'decided' or self.decision_outcome != 'upheld':
            raise UserError(_('A second appeal can only be lodged if the first appeal was decided and upheld.'))
        if self.appeal_level == 'second':
            raise UserError(_('This record is already a 2nd level appeal.'))

        return {
            'name': _('Submit 2nd Level Appeal for Case %s') % self.case_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.case_id.id,
                'default_parent_appeal_id': self.id,
                'default_appeal_level': 'second',
                'default_submission_date': fields.Date.context_today(self),
            }
        }
                