# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineCommitteeMeeting(models.Model):
    _name = 'discipline.committee.meeting'
    _description = 'Disciplinary Committee Meeting'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'meeting_date desc, id desc'

    name = fields.Char(string='Meeting Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', related='case_id.employee_id', store=True, readonly=True)
    meeting_date = fields.Datetime(string='Scheduled Meeting Time', required=True, tracking=True)
    meeting_end_time = fields.Datetime(string='Scheduled Meeting End Time', tracking=True)
    location = fields.Char(string='Meeting Room / Location', default='Main HR Conference Room')

    committee_chair_id = fields.Many2one('res.users', string='Committee Chair (CPCO)', required=True, tracking=True)
    respective_director_id = fields.Many2one('res.users', string='Director of Respective Office', tracking=True)
    legal_director_id = fields.Many2one('res.users', string='Legal Director', tracking=True)
    pomd_secretary_id = fields.Many2one('res.users', string='People Operation Director (Secretary)', tracking=True)
    meeting_link = fields.Char(string='Virtual Meeting Link / Room')
    member_ids = fields.Many2many('res.users', 'discipline_committee_members_rel', 'meeting_id', 'user_id', string='Committee Members', required=True)

    # Quorum Requirements
    total_expected_members = fields.Integer(string='Total Expected Members', compute='_compute_quorum', store=True)
    present_members_count = fields.Integer(string='Members Present Count', required=True, default=4, tracking=True)
    required_quorum_percentage = fields.Float(string='Required Quorum (%)', default=50.0, required=True, help='Minimum percentage of members present required for valid decision')
    is_quorum_met = fields.Boolean(string='Quorum Validated', compute='_compute_quorum', store=True, tracking=True)

    # Minutes & Decision Capture
    agenda = fields.Text(string='Meeting Agenda')
    meeting_minutes = fields.Text(string='Official Meeting Minutes', tracking=True)
    final_recommendation = fields.Selection([
        ('dismissal', 'Recommend Dismissal'),
        ('final_warning', 'Recommend Final Written Warning'),
        ('second_warning', 'Recommend Second Written Warning'),
        ('first_warning', 'Recommend First Written Warning'),
        ('verbal_warning', 'Recommend Verbal Warning'),
        ('demotion', 'Recommend Demotion'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
        ('further_investigation', 'Require Further Investigation'),
    ], string='Committee Recommendation', tracking=True)

    vote_ids = fields.One2many('discipline.committee.vote', 'meeting_id', string='Member Votes')
    in_favor_count = fields.Integer(string='Votes In Favor', compute='_compute_vote_counts', store=True)
    against_count = fields.Integer(string='Votes Against', compute='_compute_vote_counts', store=True)
    abstain_count = fields.Integer(string='Abstentions', compute='_compute_vote_counts', store=True)

    state = fields.Selection([
        ('draft', 'Scheduled'),
        ('in_progress', 'Meeting In Progress'),
        # Director must review agenda before voting is opened
        ('director_review', 'Pending Director Review Sign-off'),
        ('voting', 'Voting in Progress'),
        ('minutes_recorded', 'Minutes & Votes Captured'),
        ('completed', 'Finalized & Submitted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Sequential sign-off tracking
    director_signed_off = fields.Boolean(
        string='Immediate Director Sign-off Completed',
        default=False,
        tracking=True,
        help='Immediate Director of employee under investigation must sign first to initiate final review.'
    )
    director_signoff_date = fields.Date(string='Director Sign-off Date', tracking=True)
    director_signoff_by_id = fields.Many2one('res.users', string='Signed Off By (Director)', tracking=True)
    can_director_signoff = fields.Boolean(compute='_compute_can_director_signoff', string='Can Director Signoff')

    def _compute_can_director_signoff(self):
        user = self.env.user
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
        for rec in self:
            is_resp_dir = bool(rec.respective_director_id and rec.respective_director_id.id == user.id)
            is_dir_role = (
                is_resp_dir or
                user.has_group('discipline_management.group_discipline_director') or
                (user.employee_id and user.employee_id.executive_level in ('director', 'chief', 'ceo')) or
                is_admin
            )
            rec.can_director_signoff = is_dir_role

    @api.depends('member_ids', 'present_members_count', 'required_quorum_percentage')
    def _compute_quorum(self):
        for rec in self:
            rec.total_expected_members = len(rec.member_ids)
            if rec.total_expected_members > 0:
                quorum_pct = (rec.present_members_count / rec.total_expected_members) * 100.0
                rec.is_quorum_met = (quorum_pct >= rec.required_quorum_percentage)
            else:
                rec.is_quorum_met = False

    @api.depends('vote_ids.vote')
    def _compute_vote_counts(self):
        for rec in self:
            rec.in_favor_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'in_favor'))
            rec.against_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'against'))
            rec.abstain_count = len(rec.vote_ids.filtered(lambda v: v.vote == 'abstain'))

    @api.onchange('case_id')
    def _onchange_case_id_populate_committee(self):
        """Auto-populate mandatory committee roles (Chair: CPCO, Secretary: POMD Director, Legal: Legal Director, Respective Director)."""
        if self.case_id and self.case_id.employee_id:
            emp = self.case_id.employee_id
            
            # 1. Chairperson: Chief People and Culture Officer (CPCO)
            cpco_emp = self.env['hr.employee'].search([
                '|', ('job_id.name', 'ilike', 'Chief People'),
                ('job_id.name', 'ilike', 'CPCO')
            ], limit=1)
            if cpco_emp and cpco_emp.user_id:
                self.committee_chair_id = cpco_emp.user_id
            else:
                cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
                cpco_users = (cpco_group.all_user_ids or cpco_group.user_ids) if cpco_group else self.env['res.users']
                self.committee_chair_id = cpco_users[0] if cpco_users else self.env.user

            # 2. Member: Respective Directorate Director
            resp_dir_user = False
            if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
                resp_dir_user = emp.department_id.manager_id.user_id
            else:
                for sup in emp.get_supervisor_chain():
                    if sup.executive_level in ('director', 'chief', 'ceo') and sup.user_id:
                        resp_dir_user = sup.user_id
                        break
            self.respective_director_id = resp_dir_user or False

            # 3. Member: Legal Director (Director of Legal Directorate)
            legal_emp = self.env['hr.employee'].search([
                '|', ('job_id.name', 'ilike', 'Legal Director'),
                ('job_id.name', 'ilike', 'Legal Services Director')
            ], limit=1)
            if not legal_emp:
                legal_emp = self.env['hr.employee'].search([('job_id.name', 'ilike', 'Legal')], limit=1)
            if legal_emp and legal_emp.user_id:
                self.legal_director_id = legal_emp.user_id
            else:
                legal_group = self.env.ref('discipline_management.group_discipline_legal', raise_if_not_found=False)
                legal_users = (legal_group.all_user_ids or legal_group.user_ids) if legal_group else self.env['res.users']
                self.legal_director_id = legal_users[0] if legal_users else False

            # 4. Member & Secretary: People Operations Management Director (POMD)
            pomd_emp = self.env['hr.employee'].search([
                '|', ('job_id.name', 'ilike', 'People Operations Management Director'),
                ('job_id.name', 'ilike', 'People Operation')
            ], limit=1)
            if pomd_emp and pomd_emp.user_id:
                self.pomd_secretary_id = pomd_emp.user_id
            else:
                pomd_group = self.env.ref('discipline_management.group_discipline_pomd', raise_if_not_found=False)
                pomd_users = (pomd_group.all_user_ids or pomd_group.user_ids) if pomd_group else self.env['res.users']
                self.pomd_secretary_id = pomd_users[0] if pomd_users else self.env.user

            # Assemble full member set
            members = set()
            if self.committee_chair_id:
                members.add(self.committee_chair_id.id)
            if self.respective_director_id:
                members.add(self.respective_director_id.id)
            if self.legal_director_id:
                members.add(self.legal_director_id.id)
            if self.pomd_secretary_id:
                members.add(self.pomd_secretary_id.id)
            
            self.member_ids = [(6, 0, list(members))]
            self.present_members_count = len(members)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.committee.meeting') or _('New')
        return super().create(vals_list)

    def action_schedule_and_notify(self):
        """Schedule meeting and notify members & employee."""
        for rec in self:
            rec.write({'state': 'in_progress'})
            # Post message and send notification to committee members and employee
            partner_ids = [m.partner_id.id for m in rec.member_ids if m.partner_id]
            if rec.employee_id.user_id and rec.employee_id.user_id.partner_id:
                partner_ids.append(rec.employee_id.user_id.partner_id.id)
            
            rec.case_id.message_post(
                body=_('Disciplinary Committee Meeting %s scheduled for %s at %s.') % (rec.name, rec.meeting_date, rec.location),
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_comment'
            )

    def action_request_director_review(self):
        """Send case packet to Department Director for sign-off before voting."""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('Meeting must be In Progress before requesting director review.'))
            rec.write({'state': 'director_review'})
            rec.case_id.message_post(
                body=_('Committee meeting %s: Agenda submitted for Director sign-off prior to voting.') % rec.name
            )

    def action_director_signoff(self):
        """Department Director approves; voting can now commence."""
        for rec in self:
            if rec.state != 'director_review':
                raise UserError(_('This action is only valid when pending Director Review.'))
            if not rec.can_director_signoff:
                raise UserError(_('Permission Denied: Only the Respective Directorate Director or HR Administrator can execute director sign-off.'))
            rec.write({
                'state': 'voting',
                'director_signed_off': True,
                'director_signoff_date': fields.Date.context_today(self),
                'director_signoff_by_id': self.env.user.id,
            })
            rec.case_id.message_post(
                body=_('Director sign-off confirmed by %s on %s. Voting is now open.') % (
                    self.env.user.name, fields.Date.context_today(self)
                )
            )

    def action_record_minutes_and_votes(self):
        for rec in self:
            if rec.state not in ['voting', 'in_progress']:
                raise UserError(_('Voting must be in progress before recording minutes.'))
            if not rec.director_signed_off and rec.state == 'voting':
                # Allowed — this is just recording
                pass
            if not rec.meeting_minutes:
                raise UserError(_('Official Meeting Minutes must be recorded before proceeding.'))
            rec.write({'state': 'minutes_recorded'})

    def action_finalize_meeting(self):
        """Quorum Validation +sequential sign-off check before final decision."""
        for rec in self:
            # Director must have signed off before finalisation
            if not rec.director_signed_off:
                raise UserError(_(
                    'Sequential Sign-off Required: Department Director must sign off on the agenda '
                    'before the committee meeting can be finalized .'
                ))

            if not rec.is_quorum_met:
                raise ValidationError(_(
                    'Quorum Validation Error: Meeting cannot be finalized. Quorum requirement not met '
                    '(%s present out of %s members; %s%% required).'
                ) % (rec.present_members_count, rec.total_expected_members, rec.required_quorum_percentage))
            
            if not rec.final_recommendation:
                raise UserError(_('A final committee recommendation must be selected.'))

            # Ensure all present members have cast a vote
            cast_votes = len(rec.vote_ids)
            if cast_votes < rec.present_members_count:
                raise UserError(_(
                    'Incomplete Votes: %d member(s) present but only %d vote(s) recorded. '
                    'All present members must cast a vote before finalizing.'
                ) % (rec.present_members_count, cast_votes))

            rec.write({'state': 'completed'})
            
            # Auto-populate the decided punishment on the case from committee recommendation
            recom_to_punishment = {
                'dismissal': 'dismissal',
                'final_warning': 'final_warning_penalty',
                'second_warning': 'second_warning_penalty',
                'first_warning': 'first_warning_penalty',
                'verbal_warning': 'verbal_warning',
                'demotion': 'demotion',
                'exonerate': 'exonerate',
                'custom': 'custom',
            }
            if rec.case_id and rec.final_recommendation in recom_to_punishment:
                punish_val = recom_to_punishment[rec.final_recommendation]
                rec.case_id.with_context(force_write=True).write({
                    'decided_punishment_type': punish_val,
                    'punishment_type': punish_val,
                })

            rec.case_id.message_post(
                body=_(
                    'Disciplinary Committee Meeting %s completed. Quorum Validated. '
                    'Director sign-off: %s. Recommendation: %s. Votes — For: %d | Against: %d | Abstain: %d.'
                ) % (rec.name, rec.director_signoff_date, rec.final_recommendation,
                     rec.in_favor_count, rec.against_count, rec.abstain_count)
            )


class DisciplineCommitteeVote(models.Model):
    _name = 'discipline.committee.vote'
    _description = 'Disciplinary Committee Member Vote'

    meeting_id = fields.Many2one('discipline.committee.meeting', string='Meeting', required=True, ondelete='cascade')
    member_id = fields.Many2one('res.users', string='Committee Member', required=True, default=lambda self: self.env.user)
    vote = fields.Selection([
        ('in_favor', 'In Favor of Proposed Action'),
        ('against', 'Against Proposed Action'),
        ('abstain', 'Abstain'),
    ], string='Vote', required=True)
    comments = fields.Text(string='Vote Justification / Remarks')

    _sql_constraints = [
        ('uniq_member_vote', 'unique(meeting_id, member_id)', 'A committee member can only vote once per meeting!')
    ]
