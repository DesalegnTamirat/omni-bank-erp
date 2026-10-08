# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_datetime
from markupsafe import Markup
import base64
import os
import logging

_logger = logging.getLogger(__name__)


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
        ('present', 'Present in Person'),
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
    
    # Audit Investigation Brief
    investigation_id = fields.Many2one('discipline.investigation', string='Audit Investigation Reference', compute='_compute_investigation_brief', store=True)
    investigation_outcome = fields.Selection(string='Audit Finding Outcome', related='investigation_id.finding_outcome', readonly=True)
    financial_loss_amount = fields.Float(string='Financial Loss Amount (ETB)', related='investigation_id.financial_loss_amount', readonly=True)

    @api.depends('case_id', 'case_id.investigation_ids')
    def _compute_investigation_brief(self):
        for rec in self:
            rec.investigation_id = rec.case_id.investigation_ids[:1].id if rec.case_id and rec.case_id.investigation_ids else False

    # Meeting Schedule & Logistics (In-Person Hearing)
    meeting_date = fields.Datetime(string='Scheduled Hearing Date & Time', required=True, tracking=True)
    location = fields.Char(string='Hearing Room / Physical Location', default='Main HR Conference Room', required=True, tracking=True)

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

    # Deliberations, Minutes & Employee Defense (Recorded by Secretary / Chairman)
    agenda = fields.Html(string='Meeting Agenda & Points of Order')
    employee_defense_summary = fields.Html(string='Summary of Employee Defense & Statements')
    meeting_minutes = fields.Html(string='Official Hearing Deliberations & Findings')

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
    recommendation_rationale = fields.Html(string='Deliberation Verdict Rationale & Policy Justification')

    # Member Voting
    vote_ids = fields.One2many('discipline.committee.vote', 'meeting_id', string='Member Votes')
    in_favor_count = fields.Integer(string='Votes In Favor', compute='_compute_vote_counts', store=True)
    against_count = fields.Integer(string='Votes Against', compute='_compute_vote_counts', store=True)
    abstain_count = fields.Integer(string='Abstentions', compute='_compute_vote_counts', store=True)

    # Streamlined 4-Stage Lifecycle
    state = fields.Selection([
        ('draft', 'Draft / Planning'),
        ('scheduled', 'Hearing Scheduled'),
        ('in_progress', 'Hearing In Progress'),
        ('completed', 'Finalized & Submitted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.depends('attendance_ids.is_present', 'attendance_ids', 'member_ids', 'required_quorum_percentage', 'state')
    def _compute_quorum(self):
        for rec in self:
            expected = len(rec.attendance_ids) or len(rec.member_ids) or 5
            rec.total_expected_members = expected
            
            if rec.attendance_ids:
                present_count = len(rec.attendance_ids.filtered(lambda a: a.is_present))
            else:
                present_count = len(rec.member_ids) if rec.state not in ('draft', 'scheduled') else 0
            
            rec.present_members_count = present_count
            if expected > 0:
                quorum_pct = (present_count / expected) * 100.0
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

            self._sync_panel_attendance_matrix()

    @api.onchange('committee_chair_id', 'pomd_secretary_id', 'respective_director_id', 'legal_director_id', 'labour_union_rep_id')
    def _onchange_panel_officers(self):
        """Dynamically update attendance matrix whenever any panel officer is modified."""
        self._sync_panel_attendance_matrix()

    def _sync_panel_attendance_matrix(self):
        """Synchronize the 5 panel officers into member_ids and attendance lines."""
        role_map = [
            ('chair', 1, self.committee_chair_id),
            ('secretary', 2, self.pomd_secretary_id),
            ('legal', 3, self.legal_director_id),
            ('director', 4, self.respective_director_id),
            ('union', 5, self.labour_union_rep_id),
        ]
        members = []
        att_lines = []
        for r_code, r_order, u in role_map:
            if u:
                members.append(u.id)
                att_lines.append((0, 0, {
                    'user_id': u.id,
                    'role': r_code,
                    'role_order': r_order,
                    'is_present': False,
                    'attendance_status': 'absent',
                }))
        self.member_ids = [(6, 0, members)]
        self.attendance_ids = [(5, 0, 0)] + att_lines

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

    def _send_discuss_direct_message(self, sender_user, target_partner, msg_html):
        """Safely dispatch 1-on-1 Odoo Discuss direct chat message."""
        if not target_partner or not sender_user:
            return
        try:
            channel = self.env['discuss.channel'].sudo().with_user(sender_user)._get_or_create_chat(
                partners_to=[target_partner.id]
            )
            if channel:
                channel.sudo().with_user(sender_user).message_post(
                    body=Markup(msg_html),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_user.partner_id.id,
                )
        except Exception as e:
            _logger.warning("Failed to dispatch Discuss direct message to partner %s: %s", target_partner.id, str(e))

    def action_confirm_schedule_and_send_summons(self):
        """Confirm schedule and dispatch hearing notice to designated committee panel members."""
        for rec in self:
            if not rec.meeting_date:
                raise UserError(_('Please specify the Scheduled Hearing Date & Time before confirming the schedule.'))
            rec.write({'state': 'scheduled'})
            
            # Collect recipient panel members (employee is not notified at this stage; they are notified after final decision)
            recipient_partners = []
            recipient_users = []
            
            panel_users = [
                rec.committee_chair_id,
                rec.pomd_secretary_id,
                rec.respective_director_id,
                rec.legal_director_id,
                rec.labour_union_rep_id,
            ]
            for m in rec.member_ids:
                if m not in panel_users:
                    panel_users.append(m)
            
            for u in panel_users:
                if u and u.partner_id:
                    recipient_users.append(u)
                    recipient_partners.append(u.partner_id)
            
            formatted_date = format_datetime(rec.env, rec.meeting_date, dt_format='MMM d, y, h:mm a') if rec.meeting_date else 'N/A'

            msg = _(
                '<div style="font-family: inherit; line-height: 1.6;">'
                '<div style="background-color: #f8f9fa; border-left: 4px solid #714B67; padding: 10px 15px; margin-bottom: 10px; border-radius: 4px;">'
                '<h4 style="margin: 0 0 5px 0; color: #714B67; font-weight: bold;">⚖️ Hearing Session Schedule — Disciplinary Committee</h4>'
                '<div style="font-size: 13px; color: #555;">Hearing Ref: <strong>%s</strong> | Linked Case: <strong>%s</strong></div>'
                '</div>'
                '<table style="width: 100%%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px;">'
                '<tr><td style="padding: 4px 0; width: 35%%; color: #666;"><strong>Subject Employee:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Scheduled Date &amp; Time:</strong></td><td style="padding: 4px 0; font-weight: bold; color: #714B67;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Physical Hearing Venue:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Chairperson:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Secretary:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                '</table>'
                '<div style="background-color: #fff3cd; border: 1px solid #ffeeba; padding: 8px 12px; border-radius: 4px; font-size: 12px; color: #856404;">'
                '⚠️ <strong>Mandatory Panel Attendance Notice:</strong> This is an official notice to designated committee members. All designated panel members are required to attend the hearing session in person at the scheduled time and venue.'
                '</div>'
                '</div>'
            ) % (
                rec.name,
                rec.case_id.name if rec.case_id else 'N/A',
                rec.employee_id.name if rec.employee_id else 'N/A',
                formatted_date,
                rec.location or _('Main HR Conference Room'),
                rec.committee_chair_id.name if rec.committee_chair_id else 'N/A',
                rec.pomd_secretary_id.name if rec.pomd_secretary_id else 'N/A',
            )

            p_ids = [p.id for p in recipient_partners if p]
            if p_ids:
                rec.sudo().message_subscribe(partner_ids=list(set(p_ids)))
                if rec.case_id:
                    rec.case_id.sudo().message_subscribe(partner_ids=list(set(p_ids)))

            if rec.case_id:
                rec.case_id.message_post(
                    body=Markup(msg),
                    partner_ids=list(set(p_ids)) if p_ids else False,
                    subtype_xmlid='mail.mt_comment'
                )
            rec.message_post(body=Markup(msg))

            # Dispatch Direct 1-on-1 Chat in Odoo Discuss to each committee member
            sender = self.env.user
            for target_partner in recipient_partners:
                if target_partner:
                    self._send_discuss_direct_message(sender, target_partner, msg)

    def action_begin_hearing_session(self):
        """Begin the active hearing session on the meeting day (unlocks roll call and minute recording)."""
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.message_post(body=_('Disciplinary Hearing session officially commenced by %s. Panel is in session.') % self.env.user.name)

    def action_reset_to_draft(self):
        """Reset meeting to draft for rescheduling."""
        for rec in self:
            rec.write({'state': 'draft'})

    def action_cancel_meeting(self):
        """Cancel the scheduled hearing."""
        for rec in self:
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Disciplinary Committee Meeting cancelled by %s.') % self.env.user.name)

    def action_mark_all_present(self):
        """Quick action for Secretary to mark all designated panel members present."""
        for rec in self:
            for att in rec.attendance_ids:
                att.write({'is_present': True, 'attendance_status': 'present'})

    # Backward compatibility aliases
    action_start_hearing_and_notify = action_confirm_schedule_and_send_summons
    action_schedule_and_notify = action_confirm_schedule_and_send_summons

    def action_conclude_and_submit_recommendation(self):
        """Conclude Hearing & Deliberations, sync sanction to Case, advance Case to pending_approval, and notify CEO/CPCO."""
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
            # 1. Quorum validation
            if not rec.is_quorum_met:
                if rec.present_members_count == 0 and rec.attendance_ids:
                    rec.action_mark_all_present()
                elif not rec.is_quorum_met:
                    raise ValidationError(_(
                        'Quorum Validation Error: Meeting cannot be finalized. Quorum requirement not met '
                        '(%s present out of %s members; %s%% required).'
                    ) % (rec.present_members_count, rec.total_expected_members, rec.required_quorum_percentage))

            # 2. Minutes validation
            if not rec.meeting_minutes or rec.meeting_minutes.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Official Hearing Deliberations & Findings must be recorded before concluding the hearing.'))

            # 3. Resolve selected recommendation
            verdict = rec.recommended_penalty_type or rec.final_recommendation
            if not verdict:
                raise UserError(_('Please select a Recommended Disciplinary Measure before submitting.'))

            punish_val = recom_to_punishment.get(verdict, verdict)

            rec.write({
                'state': 'completed',
                'recommended_penalty_type': punish_val,
                'final_recommendation': verdict if verdict in dict(rec._fields['final_recommendation'].selection) else False,
            })

            # 4. Auto-populate decided punishment on Parent Case and advance directly to pending_approval
            if rec.case_id:
                case_vals = {
                    'decided_punishment_type': punish_val,
                    'punishment_type': punish_val,
                    'state': 'pending_approval',
                    'is_locked_for_committee': False,
                }
                if rec.recommended_penalty_percentage:
                    case_vals['decided_penalty_percentage'] = rec.recommended_penalty_percentage
                if rec.recommended_fine_days:
                    case_vals['decided_fine_days'] = rec.recommended_fine_days

                rec.case_id.with_context(force_write=True).write(case_vals)

                # 5. Determine designated approving executive and notify
                EmpModel = self.env['hr.employee'].sudo()
                ceo_user = EmpModel.get_ceo_user()
                cpco_user = EmpModel.get_cpco_user()
                
                is_dismissal = (punish_val == 'dismissal')
                target_exec_user = ceo_user if is_dismissal else cpco_user
                target_role = _('Chief Executive Officer (CEO)') if is_dismissal else _('Chief People & Culture Officer (CPCO)')
                target_name = target_exec_user.name if target_exec_user else target_role

                verdict_label = dict(rec._fields['recommended_penalty_type'].selection).get(punish_val, punish_val)

                notification_body = _(
                    '<div style="font-family: inherit; line-height: 1.6;">'
                    '<div style="background-color: #e8f4fd; border-left: 4px solid #0056b3; padding: 10px 15px; margin-bottom: 10px; border-radius: 4px;">'
                    '<h4 style="margin: 0 0 5px 0; color: #0056b3; font-weight: bold;">⚖️ Hearing Concluded &amp; Recommendation Submitted</h4>'
                    '<div style="font-size: 13px; color: #555;">Hearing Ref: <strong>%s</strong> | Status: <strong>Pending Executive Final Approval</strong></div>'
                    '</div>'
                    '<table style="width: 100%%; font-size: 13px; border-collapse: collapse; margin-bottom: 10px;">'
                    '<tr><td style="padding: 4px 0; width: 35%%; color: #666;"><strong>Subject Employee:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Committee Recommended Verdict:</strong></td><td style="padding: 4px 0; font-weight: bold; color: #c0392b;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Designated Approving Executive:</strong></td><td style="padding: 4px 0; font-weight: bold;">%s</td></tr>'
                    '<tr><td style="padding: 4px 0; color: #666;"><strong>Finalized By Secretary:</strong></td><td style="padding: 4px 0;">%s</td></tr>'
                    '</table>'
                    '</div>'
                ) % (
                    rec.name,
                    rec.employee_id.name if rec.employee_id else _('Employee'),
                    verdict_label,
                    target_name,
                    self.env.user.name,
                )

                partners_to_notify = []
                if target_exec_user and target_exec_user.partner_id:
                    partners_to_notify.append(target_exec_user.partner_id.id)
                if ceo_user and ceo_user.partner_id:
                    partners_to_notify.append(ceo_user.partner_id.id)
                if cpco_user and cpco_user.partner_id:
                    partners_to_notify.append(cpco_user.partner_id.id)
                if rec.respective_director_id and rec.respective_director_id.partner_id:
                    partners_to_notify.append(rec.respective_director_id.partner_id.id)

                rec.message_post(body=Markup(notification_body))
                if rec.case_id:
                    rec.case_id.message_post(
                        body=Markup(notification_body),
                        partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                    )

                # Dispatch Direct 1-on-1 Chat in Odoo Discuss to each executive
                sender = self.env.user
                for pid in set(partners_to_notify):
                    p_obj = self.env['res.partner'].browse(pid)
                    if p_obj.exists():
                        self._send_discuss_direct_message(sender, p_obj, notification_body)

    # Legacy aliases
    action_finalize_meeting = action_conclude_and_submit_recommendation
    action_finalize_and_submit_for_approval = action_conclude_and_submit_recommendation

    # Helper methods for PDF Report
    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official logo for QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        gender = getattr(self.employee_id, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(self.employee_id, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def action_print_hearing_report(self):
        """Print official Disciplinary Committee Hearing Minutes & Resolution Report PDF."""
        self.ensure_one()
        return self.env.ref('discipline_management.action_report_committee_resolution').report_action(self)


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
