# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineCommitteeAttendance(models.Model):
    """Structured Attendance Line for Committee Panel Members during Hearing."""
    _name = 'discipline.committee.attendance'
    _description = 'Disciplinary Committee Member Attendance'
    _order = 'role_order asc, id asc'

    meeting_id = fields.Many2one('discipline.committee.meeting', string='Meeting', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Committee Member', required=True)
    role = fields.Selection([
        ('chair', 'Committee Chairperson (CPCO)'),
        ('secretary', 'Committee Secretary (POMD)'),
        ('legal', 'Legal Directorate Member'),
        ('director', 'Respective Directorate Director'),
        ('union', 'Labour Union Representative'),
        ('ad_hoc', 'Ad-hoc / Designated Member'),
    ], string='Panel Role', required=True, default='ad_hoc')
    role_order = fields.Integer(string='Sort Order', default=10)
    is_present = fields.Boolean(string='Present', default=False)
    attendance_status = fields.Selection([
        ('present', 'Present in Person / Virtual'),
        ('absent', 'Absent (Unexcused)'),
        ('excused', 'Excused / Prior Notice'),
        ('represented', 'Represented by Alternate'),
    ], string='Attendance Status', default='absent')
    remarks = fields.Char(string='Remarks / Representation Note')

    @api.onchange('is_present')
    def _onchange_is_present(self):
        if self.is_present:
            self.attendance_status = 'present'
        elif self.attendance_status == 'present':
            self.attendance_status = 'absent'


class DisciplineCommitteeMeeting(models.Model):
    _name = 'discipline.committee.meeting'
    _description = 'Disciplinary Committee Meeting & Hearing'
    _inherit = ['mail.thread']
    _order = 'meeting_date desc, id desc'

    name = fields.Char(string='Meeting Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', related='case_id.employee_id', store=True, readonly=True)
    
    # Case & Misconduct Context (Read-Only Brief)
    job_id = fields.Many2one('hr.job', string='Job Title', related='case_id.employee_id.job_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department / Branch', related='case_id.employee_id.department_id', store=True, readonly=True)
    staff_category = fields.Selection(string='Staff Category', related='case_id.staff_category', store=True, readonly=True)
    offense_id = fields.Many2one('discipline.offense', string='Misconduct Clause / Offense', related='case_id.offense_id', store=True, readonly=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='case_id.offense_category_id', store=True, readonly=True)
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', related='case_id.severity_level_id', store=True, readonly=True)
    severity_level = fields.Char(string='Severity Classification', related='case_id.severity_level', store=True, readonly=True)
    incident_date = fields.Date(string='Misconduct Incident Date', related='case_id.incident_date', store=True, readonly=True)
    
    # Audit Investigation Brief (if applicable)
    investigation_id = fields.Many2one('discipline.investigation', string='Audit Investigation Reference', compute='_compute_investigation_brief', store=True)
    investigation_outcome = fields.Selection(string='Audit Finding Outcome', related='investigation_id.finding_outcome', readonly=True)
    financial_loss_amount = fields.Float(string='Financial Loss Amount (ETB)', related='investigation_id.financial_loss_amount', readonly=True)

    @api.depends('case_id', 'case_id.investigation_ids')
    def _compute_investigation_brief(self):
        for rec in self:
            rec.investigation_id = rec.case_id.investigation_ids[:1].id if rec.case_id and rec.case_id.investigation_ids else False

    # Meeting Schedule & Logistics
    meeting_date = fields.Datetime(string='Scheduled Hearing Time', required=True, tracking=True)
    meeting_end_time = fields.Datetime(string='Estimated End Time', tracking=True)
    location = fields.Char(string='Hearing Room / Location', default='Main HR Conference Room', tracking=True)
    meeting_link = fields.Char(string='Virtual Meeting Link / Video Room')

    # Designated Statutory Panel Roles
    committee_chair_id = fields.Many2one('res.users', string='Committee Chair (CPCO)', required=True, tracking=True)
    respective_director_id = fields.Many2one('res.users', string='Director of Respective Office', tracking=True)
    legal_director_id = fields.Many2one('res.users', string='Legal Directorate Member', tracking=True)
    pomd_secretary_id = fields.Many2one('res.users', string='People Operations Director (Secretary)', tracking=True)
    labour_union_rep_id = fields.Many2one('res.users', string='Labour Union Representative', tracking=True)
    member_ids = fields.Many2many('res.users', 'discipline_committee_members_rel', 'meeting_id', 'user_id', string='Committee Members', required=True)

    # Attendance & Quorum Requirements
    attendance_ids = fields.One2many('discipline.committee.attendance', 'meeting_id', string='Panel Attendance')
    total_expected_members = fields.Integer(string='Total Expected Members', compute='_compute_quorum', store=True)
    present_members_count = fields.Integer(string='Members Present Count', compute='_compute_quorum', store=True, tracking=True)
    required_quorum_percentage = fields.Float(string='Required Quorum (%)', default=50.0, required=True, help='Minimum percentage of members present required for valid decision')
    is_quorum_met = fields.Boolean(string='Quorum Validated', compute='_compute_quorum', store=True, tracking=True)

    # Deliberations, Minutes & Employee Defense
    agenda = fields.Html(string='Meeting Agenda & Points of Order')
    employee_defense_summary = fields.Html(string='Employee Defense, Statements & Mitigating Facts', tracking=True)
    meeting_minutes = fields.Html(string='Official Hearing Deliberations & Minutes', tracking=True)

    # Document & Evidence Attachments
    signed_minutes_file = fields.Binary(string='Official Signed Meeting Minutes (PDF)', attachment=True)
    signed_minutes_filename = fields.Char(string='Signed Minutes Filename')
    attendance_sheet_file = fields.Binary(string='Signed Attendance Sheet (PDF)', attachment=True)
    attendance_sheet_filename = fields.Char(string='Attendance Sheet Filename')
    employee_statement_file = fields.Binary(string='Employee Written Defense / Statement', attachment=True)
    employee_statement_filename = fields.Char(string='Statement Filename')

    # Recommendation & Sanction Decision
    final_recommendation = fields.Selection([
        ('dismissal', 'Recommend Dismissal'),
        ('final_warning', 'Recommend Final Written Warning'),
        ('second_warning', 'Recommend Second Written Warning'),
        ('first_warning', 'Recommend First Written Warning'),
        ('verbal_warning', 'Recommend Verbal Warning'),
        ('demotion', 'Recommend Demotion'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
        ('further_investigation', 'Require Further Investigation'),
    ], string='Committee Recommendation (Summary)', tracking=True)

    recommended_penalty_type = fields.Selection([
        ('verbal_warning', 'Verbal Warning'),
        ('first_warning_penalty', '1st Written Warning'),
        ('second_warning_penalty', '2nd Written Warning'),
        ('final_warning_penalty', 'Final Written Warning'),
        ('demotion', 'Demotion in Rank / Job Level'),
        ('dismissal', 'Dismissal / Termination of Employment'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
        ('further_investigation', 'Require Further Investigation'),
        ('custom', 'Other Prescribed Measure'),
    ], string='Recommended Disciplinary Measure', tracking=True)

    recommended_penalty_percentage = fields.Float(string='Recommended Salary Deduction Rate (%)', tracking=True)
    recommended_fine_days = fields.Integer(string='Recommended Salary Fine (Days)', tracking=True)
    recommended_warning_validity_days = fields.Integer(string='Warning Active Validity (Days)', default=30, tracking=True)
    recommendation_rationale = fields.Html(string='Committee Deliberation & Verdict Rationale', tracking=True)

    # Member Voting
    vote_ids = fields.One2many('discipline.committee.vote', 'meeting_id', string='Member Votes')
    in_favor_count = fields.Integer(string='Votes In Favor', compute='_compute_vote_counts', store=True)
    against_count = fields.Integer(string='Votes Against', compute='_compute_vote_counts', store=True)
    abstain_count = fields.Integer(string='Abstentions', compute='_compute_vote_counts', store=True)

    # 5-Stage Lifecycle
    state = fields.Selection([
        ('draft', 'Scheduled'),
        ('in_progress', 'Hearing In Progress'),
        ('director_review', 'Pending Director Review Sign-off'),
        ('voting', 'Voting in Progress'),
        ('minutes_recorded', 'Minutes & Votes Captured'),
        ('completed', 'Finalized & Submitted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Director Sequential Sign-off Tracking
    director_signed_off = fields.Boolean(
        string='Immediate Director Sign-off Completed',
        default=False,
        tracking=True,
        help='Immediate Director of employee under investigation must sign first to initiate final review.'
    )
    director_signoff_date = fields.Date(string='Director Sign-off Date', tracking=True)
    director_signoff_by_id = fields.Many2one('res.users', string='Signed Off By (Director)', tracking=True)
    director_signoff_remarks = fields.Text(string='Director Sign-off Remarks', tracking=True)
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

    @api.depends('attendance_ids.is_present', 'attendance_ids', 'member_ids', 'required_quorum_percentage', 'state')
    def _compute_quorum(self):
        for rec in self:
            expected = len(rec.attendance_ids) or len(rec.member_ids) or 5
            rec.total_expected_members = expected
            
            if rec.attendance_ids:
                present_count = len(rec.attendance_ids.filtered(lambda a: a.is_present))
            else:
                present_count = len(rec.member_ids) if rec.state != 'draft' else 0
            
            rec.present_members_count = present_count
            if expected > 0:
                quorum_pct = (present_count / expected) * 100.0
                rec.is_quorum_met = (quorum_pct >= rec.required_quorum_percentage) and (rec.state != 'draft')
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
        """Auto-populate the 5 mandatory committee roles and attendance matrix."""
        if self.case_id and self.case_id.employee_id:
            emp = self.case_id.employee_id
            EmpModel = self.env['hr.employee'].sudo()
            
            # 1. Chairperson: CPCO
            self.committee_chair_id = EmpModel.get_cpco_user()

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

            # 3. Member: Legal Directorate Representative
            self.legal_director_id = EmpModel.get_legal_user()

            # 4. Member & Secretary: POMD
            self.pomd_secretary_id = EmpModel.get_secretary_user()

            # 5. Member: Labour Union Representative
            self.labour_union_rep_id = EmpModel.get_union_user()

            # Assemble full member set & attendance lines
            role_map = [
                ('chair', 1, self.committee_chair_id),
                ('secretary', 2, self.pomd_secretary_id),
                ('legal', 3, self.legal_director_id),
                ('director', 4, self.respective_director_id),
                ('union', 5, self.labour_union_rep_id),
            ]
            members = set()
            att_lines = []
            for r_code, r_order, u in role_map:
                if u:
                    members.add(u.id)
                    att_lines.append((0, 0, {
                        'user_id': u.id,
                        'role': r_code,
                        'role_order': r_order,
                        'is_present': False,
                        'attendance_status': 'absent',
                    }))
            
            self.member_ids = [(6, 0, list(members))]
            if not self.attendance_ids:
                self.attendance_ids = att_lines

    @api.model_create_multi
    def create(self, vals_list):
        EmpModel = self.env['hr.employee'].sudo()

        def _to_id(obj):
            if not obj:
                return False
            if isinstance(obj, int):
                return obj
            if hasattr(obj, 'id'):
                return obj.id
            return False

        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.committee.meeting') or _('New')
            
            case_id = vals.get('case_id')
            case = self.env['discipline.case'].browse(case_id) if case_id else False
            emp = case.employee_id if case else False

            if not vals.get('committee_chair_id'):
                vals['committee_chair_id'] = _to_id(EmpModel.get_cpco_user())
            else:
                vals['committee_chair_id'] = _to_id(vals.get('committee_chair_id'))

            if not vals.get('pomd_secretary_id'):
                vals['pomd_secretary_id'] = _to_id(EmpModel.get_secretary_user())
            else:
                vals['pomd_secretary_id'] = _to_id(vals.get('pomd_secretary_id'))

            if not vals.get('legal_director_id'):
                vals['legal_director_id'] = _to_id(EmpModel.get_legal_user())
            else:
                vals['legal_director_id'] = _to_id(vals.get('legal_director_id'))

            if not vals.get('labour_union_rep_id'):
                vals['labour_union_rep_id'] = _to_id(EmpModel.get_union_user())
            else:
                vals['labour_union_rep_id'] = _to_id(vals.get('labour_union_rep_id'))

            if not vals.get('respective_director_id'):
                if emp:
                    if emp.department_id and emp.department_id.manager_id and emp.department_id.manager_id.user_id:
                        vals['respective_director_id'] = _to_id(emp.department_id.manager_id.user_id)
                    else:
                        for sup in emp.get_supervisor_chain():
                            if sup.executive_level in ('director', 'chief', 'ceo') and sup.user_id:
                                vals['respective_director_id'] = _to_id(sup.user_id)
                                break
            else:
                vals['respective_director_id'] = _to_id(vals.get('respective_director_id'))

            if not vals.get('member_ids'):
                m_ids = [vals.get('committee_chair_id'), vals.get('pomd_secretary_id'),
                         vals.get('legal_director_id'), vals.get('labour_union_rep_id'),
                         vals.get('respective_director_id')]
                m_ids = [uid for uid in m_ids if uid]
                if m_ids:
                    vals['member_ids'] = [(6, 0, m_ids)]

        records = super().create(vals_list)
        for rec in records:
            if not rec.attendance_ids:
                rec._create_default_attendance_lines()
        return records

    def _create_default_attendance_lines(self):
        """Create structured attendance lines for all designated panel members."""
        self.ensure_one()
        role_map = [
            ('chair', 1, self.committee_chair_id),
            ('secretary', 2, self.pomd_secretary_id),
            ('legal', 3, self.legal_director_id),
            ('director', 4, self.respective_director_id),
            ('union', 5, self.labour_union_rep_id),
        ]
        for r_code, r_order, u in role_map:
            if u:
                self.env['discipline.committee.attendance'].create({
                    'meeting_id': self.id,
                    'user_id': u.id,
                    'role': r_code,
                    'role_order': r_order,
                    'is_present': False,
                    'attendance_status': 'absent',
                })

    def action_mark_all_present(self):
        """Quick action for Secretary to mark all designated panel members present."""
        for rec in self:
            for att in rec.attendance_ids:
                att.write({'is_present': True, 'attendance_status': 'present'})

    def action_schedule_and_notify(self):
        """Schedule hearing and notify panel members and employee."""
        for rec in self:
            if not rec.meeting_date:
                raise UserError(_('Please specify the Scheduled Hearing Time before notifying participants.'))
            rec.write({'state': 'in_progress'})
            
            partner_ids = [m.partner_id.id for m in rec.member_ids if m.partner_id]
            if rec.employee_id.user_id and rec.employee_id.user_id.partner_id:
                partner_ids.append(rec.employee_id.user_id.partner_id.id)
            
            rec.case_id.message_post(
                body=_('Disciplinary Committee Hearing %s scheduled for %s at %s.') % (rec.name, rec.meeting_date, rec.location),
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_comment'
            )

    def action_request_director_review(self):
        """Send hearing deliberations to Department Director for formal sign-off before voting."""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('Hearing must be In Progress before requesting director review.'))
            if not rec.is_quorum_met:
                raise ValidationError(_(
                    'Quorum Error: Quorum is not met (%s of %s members present). '
                    'Please confirm panel attendance before proceeding.'
                ) % (rec.present_members_count, rec.total_expected_members))
            
            rec.write({'state': 'director_review'})
            rec.case_id.message_post(
                body=_('Committee meeting %s: Deliberations and minutes submitted for Director sign-off prior to voting.') % rec.name
            )

    def action_director_signoff(self):
        """Department Director approves deliberations; voting is now opened."""
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
                body=_('Director sign-off confirmed by %s on %s. Panel voting is now open.') % (
                    self.env.user.name, fields.Date.context_today(self)
                )
            )

    def action_record_minutes_and_votes(self):
        for rec in self:
            if rec.state not in ['voting', 'in_progress']:
                raise UserError(_('Voting must be in progress before recording minutes.'))
            if not rec.meeting_minutes or rec.meeting_minutes.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Official Hearing Deliberations & Minutes must be recorded before proceeding.'))
            rec.write({'state': 'minutes_recorded'})

    def action_finalize_meeting(self):
        """Quorum Validation + sequential sign-off check + verdict mapping before final completion."""
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
        for rec in self:
            if not rec.director_signed_off:
                raise UserError(_(
                    'Sequential Sign-off Required: Department Director must sign off on the deliberations '
                    'before the committee meeting can be finalized.'
                ))

            if not rec.is_quorum_met:
                raise ValidationError(_(
                    'Quorum Validation Error: Meeting cannot be finalized. Quorum requirement not met '
                    '(%s present out of %s members; %s%% required).'
                ) % (rec.present_members_count, rec.total_expected_members, rec.required_quorum_percentage))
            
            # Resolve selected recommendation
            verdict = rec.recommended_penalty_type or rec.final_recommendation
            if not verdict:
                raise UserError(_('A final committee recommendation / prescribed sanction must be selected.'))

            punish_val = recom_to_punishment.get(verdict, verdict)

            # Ensure all present members have cast a vote
            cast_votes = len(rec.vote_ids)
            if cast_votes < rec.present_members_count:
                raise UserError(_(
                    'Incomplete Votes: %d member(s) present but only %d vote(s) recorded. '
                    'All present members must cast a vote before finalizing.'
                ) % (rec.present_members_count, cast_votes))

            rec.write({
                'state': 'completed',
                'recommended_penalty_type': punish_val,
                'final_recommendation': verdict if verdict in dict(rec._fields['final_recommendation'].selection) else False,
            })
            
            # Auto-populate the decided punishment, fine days, and percentage on the parent case
            if rec.case_id:
                case_vals = {
                    'decided_punishment_type': punish_val,
                    'punishment_type': punish_val,
                }
                if rec.recommended_penalty_percentage:
                    case_vals['decided_penalty_percentage'] = rec.recommended_penalty_percentage
                if rec.recommended_fine_days:
                    case_vals['decided_fine_days'] = rec.recommended_fine_days
                    
                rec.case_id.with_context(force_write=True).write(case_vals)

            rec.case_id.message_post(
                body=_(
                    'Disciplinary Committee Meeting %s completed. Quorum Validated. '
                    'Director sign-off: %s. Verdict: %s. Votes — For: %d | Against: %d | Abstain: %d.'
                ) % (rec.name, rec.director_signoff_date, punish_val,
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

