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

    # Two-Level Appeal Routing (FR-DIS-033)
    appeal_level = fields.Selection([
        ('level_1', 'First Appeal'),
        ('level_2', 'Second Appeal (Final)'),
    ], string='Appeal Level', default='level_1', required=True, tracking=True)

    appeal_source_type = fields.Selection([
        ('manager', 'Appeal against Line Manager / Director Decision'),
        ('committee', 'Appeal against Disciplinary Committee Decision'),
    ], string='Decision Source Type', compute='_compute_appeal_source_type', store=True, tracking=True)

    submitted_on_behalf = fields.Boolean(string='Submitted on Behalf of Employee', default=False, tracking=True)
    submitted_by_id = fields.Many2one('res.users', string='Submitted By', default=lambda self: self.env.user, tracking=True)

    reviewer_id = fields.Many2one('res.users', string='Appeal Authority / Reviewer', compute='_compute_appeal_reviewer', store=True, readonly=False, tracking=True)
    review_date = fields.Date(string='Review Date', tracking=True)

    # Appeal Tracking & Decision Outcome
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
        ('under_review', 'Under Appeal Review'),
        ('decided', 'Final Decision Rendered'),
        ('rejected_expired', 'Rejected (Window Expired)'),
    ], string='Status', default='submitted', required=True, tracking=True)

    @api.depends('case_id', 'case_id.committee_meeting_ids')
    def _compute_appeal_source_type(self):
        for rec in self:
            if rec.case_id and rec.case_id.committee_meeting_ids:
                rec.appeal_source_type = 'committee'
            else:
                rec.appeal_source_type = 'manager'

    @api.depends('appeal_level', 'appeal_source_type', 'case_id')
    def _compute_appeal_reviewer(self):
        """FR-DIS-033:

        Line Manager Decision:
          Level 1 -> Respective Directorate
          Level 2 -> CPCO
        Committee Decision:
          Level 1 -> Disciplinary Committee Secretary
          Level 2 -> CEO
        """
        for rec in self:
            case = rec.case_id
            if rec.appeal_source_type == 'manager':
                if rec.appeal_level == 'level_1':
                    rec.reviewer_id = case.director_id if case and case.director_id else self.env.user
                else:
                    cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
                    cpco_u = cpco_group.user_ids[0] if (cpco_group and cpco_group.user_ids) else (cpco_group.all_user_ids[0] if (cpco_group and cpco_group.all_user_ids) else False)
                    rec.reviewer_id = cpco_u or self.env.user
            else:
                # Committee decision
                if rec.appeal_level == 'level_1':
                    sec_group = self.env.ref('discipline_management.group_discipline_committee_secretary', raise_if_not_found=False)
                    sec_u = sec_group.user_ids[0] if (sec_group and sec_group.user_ids) else (sec_group.all_user_ids[0] if (sec_group and sec_group.all_user_ids) else False)
                    rec.reviewer_id = sec_u or self.env.user
                else:
                    ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
                    ceo_u = ceo_group.user_ids[0] if (ceo_group and ceo_group.user_ids) else (ceo_group.all_user_ids[0] if (ceo_group and ceo_group.all_user_ids) else False)
                    rec.reviewer_id = ceo_u or (case.ceo_id if case and case.ceo_id else self.env.user)

    # Appeal Window Enforcement (10 Calendar Days)
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
            if not vals.get('reviewer_id'):
                admin_group = self.env.ref('discipline_management.group_discipline_admin', raise_if_not_found=False)
                if admin_group and admin_group.user_ids:
                    vals['reviewer_id'] = admin_group.user_ids[0].id
        appeals = super().create(vals_list)
        for app in appeals:
            if app.case_id:
                app.case_id.with_context(force_write=True).write({'state': 'appealed'})
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
                