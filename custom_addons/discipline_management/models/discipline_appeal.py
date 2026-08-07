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

    # FR-DIS-034: Appeal Tracking & Decision Outcome
    decision_outcome = fields.Selection([
        ('upheld', 'Original Decision Upheld (Appeal Rejected)'),
        ('overturned', 'Decision Overturned (Exonerated)'),
        ('penalty_reduced', 'Penalty / Action Reduced'),
    ], string='Appeal Decision Outcome', tracking=True)

    revised_penalty_percentage = fields.Float(string='Revised Penalty Percentage (%)', tracking=True)
    revised_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Written Warning + 20% Salary Deduction'),
        ('second_warning_penalty', 'Second Written Warning + 10% Salary Deduction'),
        ('first_warning_penalty', 'First Written Warning + 5% Salary Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / No Action'),
    ], string='Revised Punishment', tracking=True)

    appeal_decision_notes = fields.Text(string='Appeal Board Decision Rationale', tracking=True)

    state = fields.Selection([
        ('submitted', 'Appeal Submitted'),
        ('under_review', 'Under Appeal Committee Review'),
        ('decided', 'Final Decision Rendered'),
        ('rejected_expired', 'Rejected (Window Expired)'),
    ], string='Status', default='submitted', required=True, tracking=True)

    # FR-DIS-032: Appeal Window Enforcement (10 Calendar Days)
    @api.constrains('submission_date', 'case_id')
    def _check_appeal_window(self):
        for rec in self:
            if rec.case_id and rec.case_id.final_decision_date:
                deadline = rec.case_id.final_decision_date + timedelta(days=10)
                if rec.submission_date > deadline:
                    raise ValidationError(_(
                        'Appeal Window Expired: Policy restricts appeal submission to 10 calendar days '
                        'from the decision notice date (%s). Deadline was %s.'
                    ) % (rec.case_id.final_decision_date, deadline))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.appeal') or _('New')
        appeals = super().create(vals_list)
        for app in appeals:
            if app.case_id:
                app.case_id.write({'state': 'appealed'})
                app.case_id.message_post(body=_('Appeal %s submitted by employee against Case decision.') % app.name)
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
                case.write({'state': 'enforced'})
                case.message_post(body=_('Appeal %s decided: Original decision UPHELD.') % rec.name)

            elif rec.decision_outcome == 'overturned':
                # Revert employee disciplinary marks
                if hasattr(case.employee_id, 'active_disciplinary_action'):
                    case.employee_id.active_disciplinary_action = False
                if hasattr(case.employee_id, 'disciplinary_warning_count') and case.employee_id.disciplinary_warning_count > 0:
                    case.employee_id.disciplinary_warning_count -= 1
                
                # Cancel pending payroll penalties
                if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                    case.payroll_penalty_ids.write({'state': 'cancelled'})
                
                case.write({'state': 'closed'})
                case.message_post(body=_('Appeal %s decided: Decision OVERTURNED. Employee exonerated.') % rec.name)

            elif rec.decision_outcome == 'penalty_reduced':
                case.write({'penalty_percentage': rec.revised_penalty_percentage, 'state': 'enforced'})
                
                # Update pending payroll penalties
                if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                    pending_penalties = case.payroll_penalty_ids.filtered(lambda p: p.state == 'pending')
                    if pending_penalties:
                        pending_penalties.write({'penalty_percentage': rec.revised_penalty_percentage})
                
                case.message_post(body=_('Appeal %s decided: Penalty REDUCED to %s%%.') % (rec.name, rec.revised_penalty_percentage))
                