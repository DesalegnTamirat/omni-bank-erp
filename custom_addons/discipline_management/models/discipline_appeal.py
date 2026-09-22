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
    original_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('final_warning_penalty', 'Final Written Warning + Penalty'),
        ('second_warning_penalty', 'Second Written Warning + Penalty'),
        ('first_warning_penalty', 'First Written Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerated / No Action'),
    ], string='Original Punishment', compute='_compute_original_penalty_details', store=True, readonly=True)

    original_penalty_percentage = fields.Float(
        string='Original Penalty Percentage (%)',
        compute='_compute_original_penalty_details',
        store=True,
        readonly=True
    )
    original_fine_days = fields.Float(
        string='Original Salary Fine (Days)',
        compute='_compute_original_penalty_details',
        store=True,
        readonly=True
    )

    @api.depends('case_id', 'case_id.punishment_type', 'case_id.penalty_percentage', 'case_id.fine_days',
                 'parent_appeal_id', 'parent_appeal_id.revised_punishment_type', 'parent_appeal_id.revised_penalty_percentage', 'parent_appeal_id.revised_fine_days')
    def _compute_original_penalty_details(self):
        for rec in self:
            if rec.parent_appeal_id and rec.parent_appeal_id.state == 'decided':
                rec.original_punishment_type = rec.parent_appeal_id.revised_punishment_type or (rec.case_id and rec.case_id.punishment_type) or False
                rec.original_penalty_percentage = rec.parent_appeal_id.revised_penalty_percentage
                rec.original_fine_days = rec.parent_appeal_id.revised_fine_days
            elif rec.case_id:
                rec.original_punishment_type = rec.case_id.punishment_type
                rec.original_penalty_percentage = rec.case_id.penalty_percentage
                rec.original_fine_days = rec.case_id.fine_days
            else:
                rec.original_punishment_type = False
                rec.original_penalty_percentage = 0.0
                rec.original_fine_days = 0.0

    # Multi-Tier Appeal Structure
    appeal_level = fields.Selection([
        ('first', '1st Level Appeal'),
        ('second', '2nd Level Appeal'),
        ('third', '3rd Level Appeal (Final to CEO)'),
    ], string='Appeal Stage', default='first', required=True, tracking=True)

    parent_appeal_id = fields.Many2one('discipline.appeal', string='Prior Appeal Reference', tracking=True)
    child_appeal_ids = fields.One2many('discipline.appeal', 'parent_appeal_id', string='Subsequent Escalated Appeals')

    case_origin_type = fields.Selection([
        ('manager', 'Appeal on Line Manager / Coach Decision'),
        ('committee', 'Appeal on Disciplinary Committee Decision'),
    ], string='Decision Source', compute='_compute_case_origin_type', store=True)

    appeal_target_authority = fields.Selection([
        ('directorate', 'Respective Directorate Director (Coach of Manager)'),
        ('chief', 'Respective Chief Officer / CPCO (Coach of Director)'),
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
                if rec.appeal_level == 'first':
                    rec.appeal_target_authority = 'directorate'
                elif rec.appeal_level == 'second':
                    rec.appeal_target_authority = 'chief'
                else:
                    rec.appeal_target_authority = 'ceo'
            else:
                if rec.appeal_level == 'first':
                    rec.appeal_target_authority = 'secretary'
                else:
                    rec.appeal_target_authority = 'ceo'

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

    @api.onchange('decision_outcome')
    def _onchange_decision_outcome(self):
        """Automatically set revised punishment and clear penalties if decision is overturned."""
        if self.decision_outcome == 'overturned':
            self.revised_punishment_type = 'exonerate'
            self.revised_penalty_percentage = 0.0
            self.revised_fine_days = 0.0
        elif self.decision_outcome == 'upheld' and self.case_id:
            self.revised_punishment_type = self.case_id.punishment_type
            self.revised_penalty_percentage = self.case_id.penalty_percentage
            self.revised_fine_days = self.case_id.fine_days

    @api.onchange('revised_punishment_type')
    def _onchange_revised_punishment_type(self):
        """Auto-populate default penalty percentage and salary fine days based on severity policy matrix."""
        if not self.revised_punishment_type:
            return

        if self.revised_punishment_type in ['exonerate', 'verbal_warning', 'dismissal']:
            self.revised_penalty_percentage = 0.0
            self.revised_fine_days = 0.0
            return

        emp = self.employee_id or (self.case_id and self.case_id.employee_id)
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
        is_managerial = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor'])

        type_to_level_code = {
            'final_warning_penalty': 'level_2',
            'second_warning_penalty': 'level_3',
            'first_warning_penalty': 'level_4',
        }
        target_code = type_to_level_code.get(self.revised_punishment_type)

        severity_level = False
        if target_code:
            severity_level = self.env['discipline.severity.level'].search([('code', '=', target_code)], limit=1)

        if severity_level:
            pct = (getattr(severity_level, 'default_managerial_penalty_pct', 0.0) if is_managerial else getattr(severity_level, 'default_non_managerial_penalty_pct', 0.0)) or getattr(severity_level, 'default_penalty_percentage', 0.0)
            days = (getattr(severity_level, 'default_managerial_fine_days', 0.0) if is_managerial else getattr(severity_level, 'default_non_managerial_fine_days', 0.0)) or getattr(severity_level, 'default_fine_days', 0.0)
            self.revised_penalty_percentage = pct
            self.revised_fine_days = days
        else:
            fallback_map = {
                'final_warning_penalty': (20.0, 3.0 if is_managerial else 0.0),
                'second_warning_penalty': (10.0, 2.0 if is_managerial else 0.0),
                'first_warning_penalty': (5.0, 1.0 if is_managerial else 0.0),
            }
            if self.revised_punishment_type in fallback_map:
                pct, days = fallback_map[self.revised_punishment_type]
                self.revised_penalty_percentage = pct
                self.revised_fine_days = days

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Appeal Submitted'),
        ('under_review', 'Under Review'),
        ('decided', 'Final Decision Rendered'),
        ('rejected_expired', 'Rejected (Window Expired)'),
    ], string='Status', default='draft', required=True, tracking=True)

    is_appeal_reviewer_or_admin = fields.Boolean(
        string='Is Appeal Reviewer or Admin',
        compute='_compute_is_appeal_reviewer_or_admin'
    )

    can_user_review_current_stage = fields.Boolean(
        string='Can User Review Current Stage',
        compute='_compute_can_user_review_current_stage'
    )

    is_appellant_employee = fields.Boolean(
        string='Is Appellant Employee',
        compute='_compute_is_appellant_employee'
    )

    def _compute_is_appeal_reviewer_or_admin(self):
        user = self.env.user
        is_reviewer = (
            user.has_group('discipline_management.group_discipline_director') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_chief') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('base.group_system')
        )
        for rec in self:
            rec.is_appeal_reviewer_or_admin = is_reviewer

    @api.depends('appeal_target_authority', 'appeal_level', 'case_origin_type')
    def _compute_can_user_review_current_stage(self):
        user = self.env.user
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
        is_ceo = user.has_group('discipline_management.group_discipline_ceo')
        is_chief = user.has_group('discipline_management.group_discipline_chief') or user.has_group('discipline_management.group_discipline_cpco')
        is_director = user.has_group('discipline_management.group_discipline_director')
        is_pomd = user.has_group('discipline_management.group_discipline_pomd')

        for rec in self:
            target = rec.appeal_target_authority
            can_review = False
            if target == 'directorate':
                can_review = is_director or is_admin
            elif target == 'chief':
                can_review = is_chief or is_admin
            elif target == 'secretary':
                can_review = is_pomd or is_admin
            elif target == 'ceo':
                can_review = is_ceo or is_admin
            else:
                can_review = is_admin
            rec.can_user_review_current_stage = can_review

    @api.depends('case_id', 'case_id.employee_id', 'employee_id')
    def _compute_is_appellant_employee(self):
        current_user = self.env.user
        for rec in self:
            emp = rec.employee_id or (rec.case_id and rec.case_id.employee_id)
            if not emp and current_user.employee_id:
                emp = current_user.employee_id
            is_emp = bool(
                emp and (
                    (emp.user_id and emp.user_id.id == current_user.id) or
                    (current_user.employee_id and current_user.employee_id.id == emp.id) or
                    (hasattr(current_user, 'employee_ids') and emp.id in current_user.employee_ids.ids)
                )
            )
            # Default to True for new/unsaved records
            if not rec.id:
                is_emp = True
            rec.is_appellant_employee = is_emp

    can_submit_next_appeal = fields.Boolean(
        string='Can Submit Next Appeal',
        compute='_compute_can_submit_next_appeal'
    )
    next_appeal_button_label = fields.Char(
        string='Next Appeal Button Label',
        compute='_compute_can_submit_next_appeal'
    )

    # Backward compatibility alias
    can_submit_second_appeal = fields.Boolean(
        string='Can Submit 2nd Appeal',
        related='can_submit_next_appeal'
    )

    def _compute_can_submit_next_appeal(self):
        current_user = self.env.user
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin')
        for rec in self:
            is_emp = bool(
                rec.employee_id and (
                    (rec.employee_id.user_id and rec.employee_id.user_id.id == current_user.id) or
                    (current_user.employee_id and current_user.employee_id.id == rec.employee_id.id) or
                    (hasattr(current_user, 'employee_ids') and rec.employee_id.id in current_user.employee_ids.ids)
                )
            )
            is_dismissal_inactive = bool(
                rec.case_id and
                (rec.case_id.severity_level == 'level_1' or rec.case_id.punishment_type == 'dismissal') and
                (not rec.employee_id.active or (rec.employee_id.user_id and not rec.employee_id.user_id.active))
            )
            eligible_user = is_emp or (is_pomd and is_dismissal_inactive)

            # Check if record is decided and outcome is not fully exonerated
            is_decided_with_penalty = (
                rec.state == 'decided' and
                rec.decision_outcome in ('upheld', 'penalty_reduced')
            )

            # Check if next level is available
            has_next_level = False
            label = _('Submit Next Level Appeal')
            if rec.case_origin_type == 'manager':
                if rec.appeal_level == 'first':
                    has_next_level = True
                    label = _('Submit 2nd Level Appeal (To Chief Officer)')
                elif rec.appeal_level == 'second':
                    has_next_level = True
                    label = _('Submit 3rd Level Appeal (To CEO)')
            else:
                if rec.appeal_level == 'first':
                    has_next_level = True
                    label = _('Submit 2nd Level Appeal (To CEO)')

            # Check if child appeal is already created
            has_child = bool(rec.child_appeal_ids)

            rec.can_submit_next_appeal = eligible_user and is_decided_with_penalty and has_next_level and not has_child
            rec.next_appeal_button_label = label

    # Appeal Window Enforcement (10 Calendar Days for 1st level appeal)
    @api.constrains('submission_date', 'case_id')
    def _check_appeal_window(self):
        for rec in self:
            if rec.appeal_level in ('second', 'third'):
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

    # Duplicate Appeal Validation for Same Case
    @api.constrains('case_id', 'appeal_level')
    def _check_duplicate_appeals(self):
        """Validate that only one appeal can exist per case at the same appeal level,
        and that a higher-level appeal cannot be lodged before prior levels are decided."""
        for rec in self:
            if not rec.case_id:
                continue

            # 1. Prevent duplicate appeals for the same case and same appeal level
            duplicate_same_level = self.search([
                ('id', '!=', rec.id),
                ('case_id', '=', rec.case_id.id),
                ('appeal_level', '=', rec.appeal_level),
            ], limit=1)
            if duplicate_same_level:
                stage_name = dict(self._fields['appeal_level'].selection).get(rec.appeal_level, rec.appeal_level)
                raise ValidationError(_(
                    'Duplicate Appeal Error: An appeal record (%s) already exists for Case "%s" at the "%s" level. '
                    'You cannot create duplicate appeals for the same case.'
                ) % (duplicate_same_level.name, rec.case_id.name, stage_name))

            # 2. Prevent creating 2nd level appeal without a prior completed 1st level appeal
            if rec.appeal_level == 'second':
                first_appeal = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('appeal_level', '=', 'first'),
                ], limit=1)
                if not first_appeal:
                    raise ValidationError(_(
                        'Invalid Appeal Stage: A 2nd Level Appeal cannot be created for Case "%s" without an existing 1st Level Appeal.'
                    ) % rec.case_id.name)
                if first_appeal.state != 'decided':
                    raise ValidationError(_(
                        'Pending Appeal in Progress: Cannot lodge a 2nd Level Appeal because the 1st Level Appeal (%s) is still pending review.'
                    ) % first_appeal.name)

            # 3. Prevent creating 3rd level appeal without a prior completed 2nd level appeal
            elif rec.appeal_level == 'third':
                second_appeal = self.search([
                    ('id', '!=', rec.id),
                    ('case_id', '=', rec.case_id.id),
                    ('appeal_level', '=', 'second'),
                ], limit=1)
                if not second_appeal:
                    raise ValidationError(_(
                        'Invalid Appeal Stage: A 3rd Level Appeal cannot be created for Case "%s" without an existing 2nd Level Appeal.'
                    ) % rec.case_id.name)
                if second_appeal.state != 'decided':
                    raise ValidationError(_(
                        'Pending Appeal in Progress: Cannot lodge a 3rd Level Appeal because the 2nd Level Appeal (%s) is still pending review.'
                    ) % second_appeal.name)

    # Appeal Decision Outcome & Penalty Reduction Order Validation
    @api.constrains('decision_outcome', 'revised_punishment_type', 'revised_penalty_percentage', 'revised_fine_days', 'state')
    def _check_decision_outcome_validity(self):
        """Validate that the appeal decision outcome strictly complies with penalty hierarchy rules:
        1. 'penalty_reduced' must strictly reduce punishment severity or monetary deductions compared to baseline.
        2. 'upheld' must maintain the baseline penalty without modification.
        3. 'overturned' must fully exonerate the employee (zero penalty).
        """
        punishment_rank = {
            'dismissal': 5,
            'final_warning_penalty': 4,
            'second_warning_penalty': 3,
            'first_warning_penalty': 2,
            'verbal_warning': 1,
            'exonerate': 0,
            False: 0,
        }
        for rec in self:
            if rec.state not in ('under_review', 'decided') or not rec.decision_outcome:
                continue

            orig_punish = rec.original_punishment_type
            rev_punish = rec.revised_punishment_type
            orig_rank = punishment_rank.get(orig_punish, 0)
            rev_rank = punishment_rank.get(rev_punish, 0)

            orig_pct = round(rec.original_penalty_percentage, 2)
            rev_pct = round(rec.revised_penalty_percentage, 2)
            orig_days = round(rec.original_fine_days, 2)
            rev_days = round(rec.revised_fine_days, 2)

            if rec.decision_outcome == 'penalty_reduced':
                # Rule A: Cannot increase punishment severity rank
                if rev_rank > orig_rank:
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    rev_label = dict(self._fields['revised_punishment_type'].selection).get(rev_punish, rev_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised punishment ('%s') "
                        "is more severe than the baseline penalty ('%s'). An appeal cannot increase penalty severity."
                    ) % (rev_label, orig_label))

                # Rule B: Cannot increase monetary deductions
                if rev_pct > orig_pct or rev_days > orig_days:
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised penalty (%s%%, %s fine days) "
                        "is greater than the baseline penalty (%s%%, %s fine days)."
                    ) % (rev_pct, rev_days, orig_pct, orig_days))

                # Rule C: If punishment rank is identical, monetary deductions MUST be strictly reduced
                if rev_rank == orig_rank and rev_pct == orig_pct and rev_days == orig_days:
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Penalty / Action Reduced', but the revised punishment and penalties "
                        "are identical to the baseline penalty (%s, %s%%, %s fine days).\n\n"
                        "• To maintain the exact same penalty, please select 'Original Decision Upheld (Appeal Rejected)'.\n"
                        "• To reduce the penalty, select a lower severity punishment or decrease the penalty percentage / fine days."
                    ) % (orig_label, orig_pct, orig_days))

            elif rec.decision_outcome == 'upheld':
                # Upheld maintains the exact original penalty
                if rev_punish and (rev_rank != orig_rank or rev_pct != orig_pct or rev_days != orig_days):
                    orig_label = dict(self._fields['original_punishment_type'].selection).get(orig_punish, orig_punish or 'None')
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Original Decision Upheld (Appeal Rejected)', but modified the punishment "
                        "or penalty values. When upholding a decision, the baseline penalty (%s, %s%%, %s fine days) must remain unchanged."
                    ) % (orig_label, orig_pct, orig_days))

            elif rec.decision_outcome == 'overturned':
                # Overturned requires zero penalty
                if (rev_punish and rev_punish != 'exonerate') or rev_pct > 0 or rev_days > 0:
                    raise ValidationError(_(
                        "Invalid Appeal Decision: You selected 'Decision Overturned (Exonerated)'. "
                        "All penalties must be cleared to 0.00 and punishment set to 'Exonerated / No Action'."
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.appeal') or _('New')
        appeals = super().create(vals_list)
        for app in appeals:
            if app.state == 'submitted' and app.case_id:
                app.case_id.sudo().with_context(force_write=True).write({'state': 'appealed'})
                app.case_id.sudo().message_post(body=_('Appeal %s (%s) submitted against Case decision.') % (app.name, app.appeal_level))
        return appeals

    def action_submit_appeal(self):
        """Explicitly submit draft appeal and transition parent case to appealed state."""
        for rec in self:
            if not rec.appeal_grounds:
                raise UserError(_('Please provide the grounds and justification for your appeal before submitting.'))
            if rec.appeal_level == 'first' and rec.case_id:
                rec._check_appeal_window()
            rec.write({'state': 'submitted'})
            if rec.case_id:
                rec.case_id.sudo().with_context(force_write=True).write({'state': 'appealed'})
                rec.case_id.sudo().message_post(body=_('Appeal %s (%s) submitted against Case decision.') % (rec.name, rec.appeal_level))

    def write(self, vals):
        # Decision outcome and revised action fields can only be modified by designated stage authority or admin
        outcome_fields = {
            'decision_outcome', 'revised_punishment_type', 'revised_penalty_percentage',
            'revised_fine_days', 'appeal_decision_notes', 'review_date'
        }
        if not self.env.su and any(f in vals for f in outcome_fields):
            for rec in self:
                if not rec.can_user_review_current_stage:
                    target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                    raise UserError(_('Permission Denied: Decision outcome and revised action fields can only be modified by the designated appeal authority (%s) or HR Administrator.') % target_label)

        # Supporting document can only be uploaded / modified by the employee or POMD/Admin on behalf
        doc_fields = {'supporting_document', 'document_filename'}
        if not self.env.su and any(f in vals for f in doc_fields):
            for rec in self:
                current_user = self.env.user
                is_emp = bool(
                    rec.employee_id and (
                        (rec.employee_id.user_id and rec.employee_id.user_id.id == current_user.id) or
                        (current_user.employee_id and current_user.employee_id.id == rec.employee_id.id) or
                        (hasattr(current_user, 'employee_ids') and rec.employee_id.id in current_user.employee_ids.ids)
                    )
                )
                is_pomd_on_behalf = rec.is_submitted_on_behalf and (
                    current_user.has_group('discipline_management.group_discipline_pomd') or
                    current_user.has_group('discipline_management.group_discipline_admin') or
                    current_user.has_group('base.group_system')
                )
                if not (is_emp or is_pomd_on_behalf):
                    raise UserError(_('Permission Denied: Only the appellant employee can attach or modify supporting appeal documents.'))

        return super().write(vals)

    def action_start_review(self):
        for rec in self:
            if not rec.can_user_review_current_stage:
                target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                raise UserError(_('Authority Restriction: You do not have the required authority role (%s) to start review for this appeal stage.') % target_label)
            rec.write({
                'reviewer_id': self.env.user.id,
                'state': 'under_review'
            })
            if rec.case_id:
                rec.case_id.sudo().message_post(
                    body=_('Appeal %s review initiated by %s (%s).') % (rec.name, self.env.user.name, rec.appeal_target_authority or 'Review Authority')
                )

    def action_render_decision(self):
        """Apply appeal decision and update original case outcome."""
        for rec in self:
            if not rec.can_user_review_current_stage:
                target_label = dict(self._fields['appeal_target_authority'].selection).get(rec.appeal_target_authority, rec.appeal_target_authority)
                raise UserError(_('Authority Restriction: You do not have the required authority role (%s) to render decisions for this appeal stage.') % target_label)
            if not rec.decision_outcome:
                raise UserError(_('Select an Appeal Decision Outcome before finalizing.'))

            rec._check_decision_outcome_validity()

            rec.write({
                'review_date': fields.Date.context_today(self),
                'state': 'decided'
            })

            case = rec.case_id
            if not case:
                continue

            if rec.decision_outcome == 'upheld':
                case.sudo().with_context(force_write=True).write({'state': 'enforced'})
                case.sudo().message_post(body=_('Appeal %s decided: Original decision UPHELD.') % rec.name)

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
                    case.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending').write({'state': 'cancelled'})
                
                case.sudo().with_context(force_write=True).write({'state': 'closed'})
                case.sudo().message_post(body=_('Appeal %s decided: Decision OVERTURNED. Employee exonerated and records restored.') % rec.name)

            elif rec.decision_outcome == 'penalty_reduced':
                is_full_exoneration = (rec.revised_punishment_type == 'exonerate') or (rec.revised_penalty_percentage == 0.0 and rec.revised_fine_days == 0.0 and rec.revised_punishment_type in ['exonerate', False])
                
                if is_full_exoneration:
                    # Revert employee disciplinary marks & restore mobility
                    case.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                        'active_disciplinary_action': False,
                        'is_ineligible_for_promotion_transfer': False,
                        'is_suspended': False,
                        'suspension_type': False,
                    })
                    if case.employee_id.disciplinary_warning_count > 0:
                        case.employee_id.disciplinary_warning_count -= 1
                    
                    # Cancel pending payroll penalties
                    if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                        case.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending').write({'state': 'cancelled'})
                    
                    case.sudo().with_context(force_write=True).write({
                        'penalty_percentage': 0.0,
                        'fine_days': 0.0,
                        'punishment_type': 'exonerate',
                        'state': 'closed'
                    })
                    case.sudo().message_post(body=_('Appeal %s decided: Penalty REDUCED to ZERO (Exonerated). Employee records restored.') % rec.name)
                else:
                    new_vals = {
                        'penalty_percentage': rec.revised_penalty_percentage,
                        'fine_days': rec.revised_fine_days,
                        'state': 'enforced'
                    }
                    if rec.revised_punishment_type:
                        new_vals['punishment_type'] = rec.revised_punishment_type
                    case.sudo().with_context(force_write=True).write(new_vals)
                    
                    # Update pending payroll penalties
                    if hasattr(case, 'payroll_penalty_ids') and case.payroll_penalty_ids:
                        pending_penalties = case.payroll_penalty_ids.sudo().filtered(lambda p: p.state == 'pending')
                        if pending_penalties:
                            pending_penalties.write({
                                'penalty_percentage': rec.revised_penalty_percentage,
                                'managerial_days': int(rec.revised_fine_days) if rec.revised_fine_days > 0 else 0
                            })
                    
                    case.sudo().message_post(body=_('Appeal %s decided: Penalty REDUCED (Pct: %s%%, Days: %s).') % (
                        rec.name, rec.revised_penalty_percentage, rec.revised_fine_days
                    ))

    def action_create_next_appeal(self):
        """Submit Next Level Appeal if previous appeal was upheld or partially reduced upon review."""
        self.ensure_one()
        current_user = self.env.user
        is_emp = bool(
            self.employee_id and (
                (self.employee_id.user_id and self.employee_id.user_id.id == current_user.id) or
                (current_user.employee_id and current_user.employee_id.id == self.employee_id.id) or
                (hasattr(current_user, 'employee_ids') and self.employee_id.id in current_user.employee_ids.ids)
            )
        )
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin')
        is_dismissal_inactive = bool(
            self.case_id and
            (self.case_id.severity_level == 'level_1' or self.case_id.punishment_type == 'dismissal') and
            (not self.employee_id.active or (self.employee_id.user_id and not self.employee_id.user_id.active))
        )
        if not (is_emp or (is_pomd and is_dismissal_inactive)):
            raise UserError(_('Appeal Access Restriction: Only the subject employee (or POMD for dismissed/inactive employees) can submit an appeal escalation.'))

        if self.state != 'decided' or self.decision_outcome not in ('upheld', 'penalty_reduced'):
            raise UserError(_('A subsequent appeal can only be lodged if the current appeal was decided and not fully overturned/exonerated.'))

        # Determine next level
        if self.case_origin_type == 'manager':
            if self.appeal_level == 'first':
                next_level = 'second'
                next_title = _('Submit 2nd Level Appeal (To Chief Officer) for Case %s') % self.case_id.name
            elif self.appeal_level == 'second':
                next_level = 'third'
                next_title = _('Submit 3rd Level Appeal (To CEO) for Case %s') % self.case_id.name
            else:
                raise UserError(_('This record is already at the final 3rd level appeal stage (CEO).'))
        else:
            if self.appeal_level == 'first':
                next_level = 'second'
                next_title = _('Submit 2nd Level Appeal (To CEO) for Case %s') % self.case_id.name
            else:
                raise UserError(_('This record is already at the final 2nd level appeal stage (CEO).'))

        # Check if already submitted
        existing_child = self.search([('parent_appeal_id', '=', self.id)], limit=1)
        if existing_child:
            raise UserError(_('An escalated appeal (%s) has already been lodged for this record.') % existing_child.name)

        return {
            'name': next_title,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.case_id.id,
                'default_parent_appeal_id': self.id,
                'default_appeal_level': next_level,
                'default_submission_date': fields.Date.context_today(self),
            }
        }

    def action_create_second_appeal(self):
        """Backward compatibility alias for action_create_next_appeal."""
        return self.action_create_next_appeal()
                