# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64


class DisciplineCommitteeMeeting(models.Model):
    _name = 'discipline.committee.meeting'
    _description = 'Disciplinary Committee Meeting'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'meeting_date desc, id desc'

    name = fields.Char(string='Meeting Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', related='case_id.employee_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    meeting_date = fields.Datetime(string='Scheduled Meeting Time', required=True, tracking=True)
    meeting_end_time = fields.Datetime(string='Scheduled Meeting End Time', tracking=True)
    location = fields.Char(string='Meeting Room / Location', default='Main HR Conference Room')
    virtual_meeting_link = fields.Char(string='Virtual Meeting Link / Room URL')

    # Statutory Committee Composition (FR-DIS-015)
    chair_id = fields.Many2one('res.users', string='Chairperson (CPCO)', required=True, tracking=True)
    director_member_id = fields.Many2one('res.users', string='Respective Office Director', required=True, tracking=True)
    legal_member_id = fields.Many2one('res.users', string='Legal Director', required=True, tracking=True)
    secretary_id = fields.Many2one('res.users', string='People Operation Director (Secretary)', required=True, tracking=True)

    # Legacy field preserved for backward compatibility
    committee_chair_id = fields.Many2one('res.users', string='Committee Chair', related='chair_id', store=True, readonly=False)
    member_ids = fields.Many2many('res.users', 'discipline_committee_members_rel', 'meeting_id', 'user_id', string='All Committee Members', compute='_compute_all_members', store=True)

    # Digital Signature Lines
    signature_line_ids = fields.One2many('discipline.committee.signature', 'meeting_id', string='Committee Signatures')
    all_signed = fields.Boolean(string='All Required Signatures Captured', compute='_compute_signature_status', store=True)
    total_signatures_count = fields.Integer(string='Signatures Count', compute='_compute_signature_status', store=True)
    signed_signatures_count = fields.Integer(string='Signed Count', compute='_compute_signature_status', store=True)

    # Quorum Requirements
    total_expected_members = fields.Integer(string='Total Expected Members', compute='_compute_quorum', store=True)
    present_members_count = fields.Integer(string='Members Present Count', default=4, tracking=True)
    required_quorum_percentage = fields.Float(string='Required Quorum (%)', default=75.0, required=True, help='Minimum quorum required (statutory 4 members)')
    is_quorum_met = fields.Boolean(string='Quorum Validated', compute='_compute_quorum', store=True, tracking=True)

    # Minutes & Deliberation (Secretary writes during meeting)
    agenda = fields.Text(string='Meeting Agenda')
    meeting_minutes = fields.Text(string='Official Meeting Minutes', tracking=True)
    minute_document = fields.Binary(string='Official Signed Minute Document', attachment=True)
    minute_filename = fields.Char(string='Minute Filename')

    # Secretary Punishment Adjustment (Unlocked during meeting)
    decided_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('exonerate', 'Exonerate Employee / Case Dismissed'),
        ('custom', 'Custom Administrative Action'),
    ], string='Committee Decided Punishment', tracking=True)

    decided_penalty_percentage = fields.Float(string='Decided Penalty Percentage (%)', tracking=True)
    decided_fine_days = fields.Float(string='Decided Salary Fine (Days)', tracking=True)
    new_job_id = fields.Many2one('hr.job', string='Demotion Target Job Position', tracking=True)
    new_grade_id = fields.Char(string='Demotion Target Grade Scale', tracking=True)

    # Recommendation
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

    # Legacy vote lines preserved
    vote_ids = fields.One2many('discipline.committee.vote', 'meeting_id', string='Member Votes')
    in_favor_count = fields.Integer(string='Votes In Favor', compute='_compute_vote_counts', store=True)
    against_count = fields.Integer(string='Votes Against', compute='_compute_vote_counts', store=True)
    abstain_count = fields.Integer(string='Abstentions', compute='_compute_vote_counts', store=True)

    # State Machine
    state = fields.Selection([
        ('scheduling', 'Scheduling (Secretary)'),
        ('scheduled', 'Scheduled & Notified'),
        ('in_progress', 'Meeting In Session / Deliberation'),
        ('signing', 'Awaiting Digital Signatures'),
        ('completed', 'Finalized & Minutes Generated'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='scheduling', required=True, tracking=True)

    # Sequential sign-off tracking
    director_signed_off = fields.Boolean(
        string='Director Sign-off Completed',
        compute='_compute_signature_status',
        store=True,
        help='Immediate Director of employee must sign first.'
    )
    director_signoff_date = fields.Date(string='Director Sign-off Date', tracking=True)
    director_signoff_by_id = fields.Many2one('res.users', string='Signed Off By (Director)', tracking=True)

    is_current_user_secretary = fields.Boolean(string='Is Current User Secretary', compute='_compute_is_current_user_secretary')
    is_current_user_member = fields.Boolean(string='Is Current User Member', compute='_compute_is_current_user_member')
    can_current_user_sign = fields.Boolean(string='Can Current User Sign', compute='_compute_can_current_user_sign')

    @api.depends('secretary_id')
    def _compute_is_current_user_secretary(self):
        current_uid = self.env.uid
        is_admin = self.env.user.has_group('discipline_management.group_discipline_admin')
        for rec in self:
            rec.is_current_user_secretary = (rec.secretary_id.id == current_uid) or is_admin

    @api.depends('member_ids')
    def _compute_is_current_user_member(self):
        current_uid = self.env.uid
        for rec in self:
            rec.is_current_user_member = current_uid in rec.member_ids.ids

    @api.depends('signature_line_ids.is_signed', 'signature_line_ids.member_id', 'state')
    def _compute_can_current_user_sign(self):
        current_uid = self.env.uid
        for rec in self:
            if rec.state != 'signing':
                rec.can_current_user_sign = False
                continue
            line = rec.signature_line_ids.filtered(lambda l: l.member_id.id == current_uid and not l.is_signed)
            rec.can_current_user_sign = bool(line)

    @api.depends('chair_id', 'director_member_id', 'legal_member_id', 'secretary_id')
    def _compute_all_members(self):
        for rec in self:
            members = set()
            for u in [rec.chair_id, rec.director_member_id, rec.legal_member_id, rec.secretary_id]:
                if u:
                    members.add(u.id)
            rec.member_ids = [(6, 0, list(members))]

    @api.depends('signature_line_ids', 'signature_line_ids.is_signed', 'signature_line_ids.role')
    def _compute_signature_status(self):
        for rec in self:
            lines = rec.signature_line_ids
            rec.total_signatures_count = len(lines)
            rec.signed_signatures_count = len(lines.filtered(lambda l: l.is_signed))
            rec.all_signed = (rec.total_signatures_count > 0 and rec.signed_signatures_count >= rec.total_signatures_count)
            dir_line = lines.filtered(lambda l: l.role == 'director')
            rec.director_signed_off = bool(dir_line and dir_line[0].is_signed)

    @api.depends('member_ids', 'present_members_count', 'required_quorum_percentage')
    def _compute_quorum(self):
        for rec in self:
            rec.total_expected_members = len(rec.member_ids) or 4
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
    def _onchange_case_id_populate_statutory_committee(self):
        """Auto-populate the 4 statutory committee members per FR-DIS-015."""
        if not self.case_id:
            return

        case = self.case_id
        emp = case.employee_id

        # 1. CPCO (Chairperson)
        cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
        cpco_user = cpco_group.user_ids[0] if (cpco_group and cpco_group.user_ids) else (cpco_group.all_user_ids[0] if (cpco_group and cpco_group.all_user_ids) else False)
        if not cpco_user:
            cpco_user = self.env['res.users'].search([('name', 'ilike', 'Chief People')], limit=1)
        self.chair_id = cpco_user or self.env.user

        # 2. Respective Office Director (Member)
        director_user = False
        dept = emp.department_id if emp else False
        if dept and dept.manager_id and dept.manager_id.user_id:
            director_user = dept.manager_id.user_id
        elif dept and dept.parent_id and dept.parent_id.manager_id and dept.parent_id.manager_id.user_id:
            director_user = dept.parent_id.manager_id.user_id
        elif emp and emp.parent_id and emp.parent_id.parent_id and emp.parent_id.parent_id.user_id:
            director_user = emp.parent_id.parent_id.user_id
        if not director_user:
            dir_group = self.env.ref('discipline_management.group_discipline_director', raise_if_not_found=False)
            director_user = dir_group.user_ids[0] if (dir_group and dir_group.user_ids) else (dir_group.all_user_ids[0] if (dir_group and dir_group.all_user_ids) else False)
        self.director_member_id = director_user or self.env.user

        # 3. Legal Director (Member)
        legal_dept = self.env['hr.department'].search([('name', 'ilike', 'Legal Services')], limit=1)
        legal_user = legal_dept.manager_id.user_id if legal_dept and legal_dept.manager_id and legal_dept.manager_id.user_id else False
        if not legal_user:
            legal_user = self.env['res.users'].search([('name', 'ilike', 'Legal')], limit=1)
        self.legal_member_id = legal_user or self.env.user

        # 4. People Operation Director (Member & Secretary)
        sec_group = self.env.ref('discipline_management.group_discipline_committee_secretary', raise_if_not_found=False)
        sec_user = sec_group.user_ids[0] if (sec_group and sec_group.user_ids) else (sec_group.all_user_ids[0] if (sec_group and sec_group.all_user_ids) else False)
        if not sec_user:
            pomd_dept = self.env['hr.department'].search(['|', ('name', 'ilike', 'People Operation'), ('name', 'ilike', 'POMD')], limit=1)
            sec_user = pomd_dept.manager_id.user_id if pomd_dept and pomd_dept.manager_id and pomd_dept.manager_id.user_id else False
        self.secretary_id = sec_user or self.env.user

        # Initialize punishments from case
        self.decided_punishment_type = case.punishment_type or case.original_punishment_type
        self.decided_penalty_percentage = case.penalty_percentage or case.original_penalty_percentage
        self.decided_fine_days = case.fine_days or case.original_fine_days

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.committee.meeting') or _('New')

            # Auto-populate statutory committee members if not passed
            case = self.env['discipline.case'].browse(vals.get('case_id')) if vals.get('case_id') else False
            emp = case.employee_id if case else False

            if not vals.get('chair_id'):
                cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
                cpco_user = cpco_group.user_ids[0] if (cpco_group and cpco_group.user_ids) else (cpco_group.all_user_ids[0] if (cpco_group and cpco_group.all_user_ids) else False)
                vals['chair_id'] = cpco_user.id if cpco_user else self.env.uid

            if not vals.get('director_member_id'):
                director_user = False
                dept = emp.department_id if emp else False
                if dept and dept.manager_id and dept.manager_id.user_id:
                    director_user = dept.manager_id.user_id
                elif dept and dept.parent_id and dept.parent_id.manager_id and dept.parent_id.manager_id.user_id:
                    director_user = dept.parent_id.manager_id.user_id
                elif emp and emp.parent_id and emp.parent_id.parent_id and emp.parent_id.parent_id.user_id:
                    director_user = emp.parent_id.parent_id.user_id
                if not director_user:
                    dir_group = self.env.ref('discipline_management.group_discipline_director', raise_if_not_found=False)
                    director_user = dir_group.user_ids[0] if (dir_group and dir_group.user_ids) else (dir_group.all_user_ids[0] if (dir_group and dir_group.all_user_ids) else False)
                vals['director_member_id'] = director_user.id if director_user else self.env.uid

            if not vals.get('legal_member_id'):
                legal_dept = self.env['hr.department'].search([('name', 'ilike', 'Legal Services')], limit=1)
                legal_user = legal_dept.manager_id.user_id if legal_dept and legal_dept.manager_id and legal_dept.manager_id.user_id else False
                if not legal_user:
                    legal_user = self.env['res.users'].search([('name', 'ilike', 'Legal')], limit=1)
                vals['legal_member_id'] = legal_user.id if legal_user else self.env.uid

            if not vals.get('secretary_id'):
                sec_group = self.env.ref('discipline_management.group_discipline_committee_secretary', raise_if_not_found=False)
                sec_user = sec_group.user_ids[0] if (sec_group and sec_group.user_ids) else (sec_group.all_user_ids[0] if (sec_group and sec_group.all_user_ids) else False)
                if not sec_user:
                    pomd_dept = self.env['hr.department'].search(['|', ('name', 'ilike', 'People Operation'), ('name', 'ilike', 'POMD')], limit=1)
                    sec_user = pomd_dept.manager_id.user_id if pomd_dept and pomd_dept.manager_id and pomd_dept.manager_id.user_id else False
                vals['secretary_id'] = sec_user.id if sec_user else self.env.uid

        meetings = super().create(vals_list)
        for m in meetings:
            m._ensure_signature_lines()
        return meetings

    def _ensure_signature_lines(self):
        """Create signature lines for statutory members if not present."""
        self.ensure_one()
        roles_config = [
            ('director', self.director_member_id, 1, _('Respective Office Director')),
            ('legal', self.legal_member_id, 2, _('Legal Director')),
            ('secretary', self.secretary_id, 3, _('People Operation Director (Secretary)')),
            ('chair', self.chair_id, 4, _('Chairperson (CPCO)')),
        ]
        for role_key, user, seq, desc in roles_config:
            if user:
                existing = self.signature_line_ids.filtered(lambda l: l.role == role_key)
                if not existing:
                    self.env['discipline.committee.signature'].create({
                        'meeting_id': self.id,
                        'member_id': user.id,
                        'role': role_key,
                        'role_description': desc,
                        'sign_sequence': seq,
                    })
                elif existing and existing.member_id != user:
                    existing.write({'member_id': user.id, 'role_description': desc, 'sign_sequence': seq})

    # -------------------------------------------------------------
    # Secretary Workflow & Actions
    # -------------------------------------------------------------
    def action_schedule_and_notify(self):
        """Phase 1 -> Phase 2: Secretary schedules meeting and sends invites."""
        for rec in self:
            if not rec.meeting_date:
                raise UserError(_('Please specify Scheduled Meeting Time before scheduling.'))
            if not rec.chair_id or not rec.director_member_id or not rec.legal_member_id or not rec.secretary_id:
                raise UserError(_('All 4 statutory committee roles (Chairperson, Respective Director, Legal Director, Secretary) must be assigned.'))

            rec._ensure_signature_lines()
            rec.write({'state': 'scheduled'})

            # Build invitees list
            partner_ids = []
            for u in [rec.chair_id, rec.director_member_id, rec.legal_member_id, rec.secretary_id]:
                if u and u.partner_id:
                    partner_ids.append(u.partner_id.id)
            if rec.employee_id.user_id and rec.employee_id.user_id.partner_id:
                partner_ids.append(rec.employee_id.user_id.partner_id.id)

            rec.case_id.message_post(
                body=_(
                    '<strong>Disciplinary Committee Meeting Scheduled</strong><br/>'
                    'Meeting Ref: %s<br/>'
                    'Date & Time: %s<br/>'
                    'Location: %s<br/>'
                    'Affected Employee: %s<br/>'
                    'Committee Members: %s, %s, %s, %s'
                ) % (
                    rec.name, rec.meeting_date, rec.location or 'TBD',
                    rec.employee_id.name,
                    rec.chair_id.name, rec.director_member_id.name, rec.legal_member_id.name, rec.secretary_id.name
                ),
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_comment'
            )

            # Schedule activities for committee members
            for u in [rec.chair_id, rec.director_member_id, rec.legal_member_id, rec.secretary_id]:
                if u:
                    rec.activity_schedule(
                        'mail.mail_activity_data_meeting',
                        summary=_('Disciplinary Hearing: %s') % rec.case_id.name,
                        note=_('Hearing scheduled for employee %s on %s at %s.') % (rec.employee_id.name, rec.meeting_date, rec.location),
                        user_id=u.id,
                        date_deadline=fields.Date.context_today(self)
                    )

    def action_start_meeting(self):
        """Phase 2 -> Phase 3: Meeting is in session / Deliberation."""
        for rec in self:
            rec.write({'state': 'in_progress'})
            rec.case_id.message_post(body=_('Disciplinary Committee Meeting %s is now in session for deliberation.') % rec.name)

    def action_request_signatures(self):
        """Phase 3 -> Phase 4: Secretary requests digital signatures from all members."""
        for rec in self:
            if not rec.meeting_minutes:
                raise UserError(_('Official Meeting Minutes must be recorded before requesting signatures.'))
            if not rec.decided_punishment_type:
                raise UserError(_('Please select the Decided Punishment outcome before requesting signatures.'))

            rec._ensure_signature_lines()
            rec.write({'state': 'signing'})

            # Notify all members to sign
            for line in rec.signature_line_ids:
                if not line.is_signed and line.member_id:
                    rec.activity_schedule(
                        'mail.mail_activity_data_todo',
                        summary=_('Sign Disciplinary Minute: %s') % rec.name,
                        note=_('Please review the meeting minutes and sign digitally for case %s.') % rec.case_id.name,
                        user_id=line.member_id.id,
                        date_deadline=fields.Date.context_today(self)
                    )
            rec.case_id.message_post(body=_('Committee meeting minutes recorded. Digital signatures requested from all committee members.'))

    def action_member_sign_popup(self):
        """Open popup wizard / view for the current user to sign."""
        self.ensure_one()
        current_uid = self.env.uid
        line = self.signature_line_ids.filtered(lambda l: l.member_id.id == current_uid and not l.is_signed)
        if not line:
            raise UserError(_('No pending signature required for your user account on this meeting.'))
        return {
            'name': _('Sign Disciplinary Minute'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.committee.signature',
            'res_id': line[0].id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_finalize_and_enforce(self):
        """Phase 4 -> Final: Validates all signatures, generates minutes, and enforces case."""
        for rec in self:
            rec._ensure_signature_lines()

            # Quorum validation
            if not rec.is_quorum_met:
                raise ValidationError(_(
                    'Quorum Validation Error: Meeting cannot be finalized. Quorum requirement not met '
                    '(%s present out of %s members; %s%% required).'
                ) % (rec.present_members_count, rec.total_expected_members, rec.required_quorum_percentage))

            # Signatures validation
            unsigned = rec.signature_line_ids.filtered(lambda l: not l.is_signed or not l.signature)
            if unsigned:
                missing_names = ', '.join(unsigned.mapped('member_id.name'))
                raise UserError(_(
                    'Digital Signatures Pending: The following committee member(s) have not signed the minutes: %s.\n'
                    'All designated members must provide their digital signature before finalization.'
                ) % missing_names)

            # Sequential verification: Immediate Director must have signed first
            dir_line = rec.signature_line_ids.filtered(lambda l: l.role == 'director')
            chair_line = rec.signature_line_ids.filtered(lambda l: l.role == 'chair')
            if dir_line and chair_line:
                if dir_line[0].signed_date and chair_line[0].signed_date and dir_line[0].signed_date > chair_line[0].signed_date:
                    raise ValidationError(_('Sequential Sign-off Error: The Immediate Director must sign before Chairperson final approval.'))

            rec.write({'state': 'completed'})

            # Sync decided punishments to case
            case = rec.case_id
            case.with_context(force_write=True).write({
                'decided_punishment_type': rec.decided_punishment_type,
                'decided_penalty_percentage': rec.decided_penalty_percentage,
                'decided_fine_days': rec.decided_fine_days,
                'new_job_id': rec.new_job_id.id if rec.new_job_id else case.new_job_id.id,
                'new_grade_id': rec.new_grade_id or case.new_grade_id,
                'punishment_type': rec.decided_punishment_type,
                'penalty_percentage': rec.decided_penalty_percentage,
                'fine_days': rec.decided_fine_days,
            })

            # Auto-generate Minute Document PDF / Attachment
            rec._generate_minute_document()

            # Enforce Case decision
            case.sudo().with_context(from_committee=True).action_approve_and_enforce()

            rec.case_id.message_post(
                body=_(
                    '<strong>Disciplinary Committee Meeting Finalized &amp; Enforced</strong><br/>'
                    'Recommendation / Outcome: %s<br/>'
                    'Punishment: %s | Penalty: %s%% | Fine: %s Days<br/>'
                    'All member digital signatures validated.'
                ) % (rec.final_recommendation or rec.decided_punishment_type,
                     rec.decided_punishment_type, rec.decided_penalty_percentage, rec.decided_fine_days)
            )

    def _generate_minute_document(self):
        """Generate official meeting minutes document and attach to chatter."""
        self.ensure_one()
        report_ref = 'discipline_management.action_report_disciplinary_committee_minute'
        try:
            report = self.env.ref(report_ref, raise_if_not_found=True)
            pdf_content, unused_format = self.env['ir.actions.report']._render_qweb_pdf(report, [self.id])
            filename = 'Minute_%s.pdf' % self.name.replace('/', '_')
            self.minute_document = base64.b64encode(pdf_content)
            self.minute_filename = filename
            att = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'discipline.case',
                'res_id': self.case_id.id,
                'mimetype': 'application/pdf',
            })
            self.case_id.message_post(body=_('Official Disciplinary Meeting Minute attached: %s') % filename, attachment_ids=[att.id])
        except Exception:
            text_body = (
                "DISCIPLINARY COMMITTEE OFFICIAL MEETING MINUTES\n"
                "================================================\n"
                "Meeting Ref   : %s\n"
                "Case Ref      : %s\n"
                "Employee      : %s\n"
                "Meeting Date  : %s\n"
                "Deliberation  : %s\n"
                "Decision      : %s\n\n"
                "Signatures Captured:\n"
            ) % (self.name, self.case_id.name, self.employee_id.name, self.meeting_date, self.meeting_minutes, self.decided_punishment_type)
            for line in self.signature_line_ids:
                text_body += "- %s (%s): SIGNED on %s\n" % (line.member_id.name, line.role_description, line.signed_date)
            self.minute_document = base64.b64encode(text_body.encode('utf-8'))
            self.minute_filename = 'Minute_%s.txt' % self.name.replace('/', '_')
            att = self.env['ir.attachment'].create({
                'name': self.minute_filename,
                'type': 'binary',
                'datas': self.minute_document,
                'res_model': 'discipline.case',
                'res_id': self.case_id.id,
                'mimetype': 'text/plain',
            })
            self.case_id.message_post(body=_('Official Disciplinary Meeting Minute text attached: %s') % self.minute_filename, attachment_ids=[att.id])


class DisciplineCommitteeSignature(models.Model):
    _name = 'discipline.committee.signature'
    _description = 'Disciplinary Committee Member Digital Signature'
    _order = 'sign_sequence asc, id asc'

    meeting_id = fields.Many2one('discipline.committee.meeting', string='Meeting', required=True, ondelete='cascade')
    member_id = fields.Many2one('res.users', string='Committee Member', required=True)
    role = fields.Selection([
        ('director', 'Respective Office Director'),
        ('legal', 'Legal Director'),
        ('secretary', 'People Operation Director (Secretary)'),
        ('chair', 'Chairperson (CPCO)'),
        ('other', 'Additional Member'),
    ], string='Role', required=True, default='other')
    role_description = fields.Char(string='Role Title')
    sign_sequence = fields.Integer(string='Sign Sequence', default=1)

    signature = fields.Binary(string='Digital Signature', attachment=True)
    signed_date = fields.Datetime(string='Signed Date & Time')
    is_signed = fields.Boolean(string='Signed', default=False)
    comments = fields.Text(string='Deliberation Remarks / Justification')

    is_locked_pending_prior_signoff = fields.Boolean(
        string='Locked Pending Prior Sign-off',
        compute='_compute_is_locked_pending_prior_signoff',
        help='FR-DIS-020.3: the Chairperson (CPCO) final-approval signature stays '
             'disabled/locked until the Immediate Director has signed first.'
    )

    @api.depends('role', 'meeting_id.signature_line_ids.is_signed', 'meeting_id.signature_line_ids.role')
    def _compute_is_locked_pending_prior_signoff(self):
        for rec in self:
            if rec.role == 'chair':
                dir_line = rec.meeting_id.signature_line_ids.filtered(lambda l: l.role == 'director')
                rec.is_locked_pending_prior_signoff = bool(dir_line and not dir_line[0].is_signed)
            else:
                rec.is_locked_pending_prior_signoff = False

    def write(self, vals):
        if 'signature' in vals or vals.get('is_signed'):
            for rec in self:
                if rec.role == 'chair' and (vals.get('signature') or vals.get('is_signed')):
                    dir_line = rec.meeting_id.signature_line_ids.filtered(lambda l: l.role == 'director')
                    if dir_line and not dir_line[0].is_signed and dir_line[0].id not in self.ids:
                        raise UserError(_('Sequential Sign-off Required: The Immediate Director must sign first before Chairperson approval.'))
            if 'signature' in vals and 'is_signed' not in vals:
                vals['is_signed'] = bool(vals['signature'])
                if not vals.get('signed_date'):
                    vals['signed_date'] = fields.Datetime.now()
        return super().write(vals)

    def action_save_signature(self):
        """Save signature drawn by user via signature widget."""
        for rec in self:
            if not rec.signature:
                raise UserError(_('Please provide your digital signature using the signature pad before saving.'))

            # Sequential signing check: Director must sign before CPCO
            if rec.role == 'chair':
                dir_line = rec.meeting_id.signature_line_ids.filtered(lambda l: l.role == 'director')
                if dir_line and not dir_line[0].is_signed:
                    raise UserError(_('Sequential Sign-off Required: The Immediate Director must sign first before Chairperson approval.'))

            rec.write({
                'is_signed': True,
                'signed_date': fields.Datetime.now(),
            })
            rec.meeting_id.message_post(
                body=_('Digital signature submitted by %s (%s) on %s.') % (
                    rec.member_id.name, rec.role_description or rec.role, fields.Datetime.now()
                )
            )
        return {'type': 'ir.actions.act_window_close'}


class DisciplineCommitteeVote(models.Model):
    _name = 'discipline.committee.vote'
    _description = 'Disciplinary Committee Member Vote (Legacy)'

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
