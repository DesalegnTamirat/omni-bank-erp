# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup


class DisciplineInvestigationLiableEmployee(models.Model):
    """Child table for each employee found liable in an investigation."""
    _name = 'discipline.investigation.liable'
    _description = 'Liable Employee in Investigation'

    investigation_id = fields.Many2one('discipline.investigation', string='Investigation', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Liable Employee', required=True)
    role_in_incident = fields.Char(string='Role / Involvement in Incident', default='Primary Subject of Incident')
    degree_of_liability = fields.Selection([
        ('principal', 'Principal Offender'),
        ('accessory', 'Accessory / Accomplice'),
        ('supervisory_negligence', 'Supervisory Negligence'),
        ('witness', 'Witness (Non-Liable)'),
    ], string='Degree of Liability', required=True, default='principal')
    recommended_action = fields.Char(string='Recommended Action', default='Disciplinary Action per Policy')


class DisciplineInvestigation(models.Model):
    _name = 'discipline.investigation'
    _description = 'Disciplinary Investigation & Findings'
    _inherit = ['mail.thread']
    _order = 'investigation_date desc, id desc'

    name = fields.Char(string='Investigation Ref', required=True, default=lambda self: _('New'), copy=False)
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', store=True, readonly=True)
    offense_id = fields.Many2one('discipline.offense', string='Offense Type / Misconduct', related='case_id.offense_id', store=True, readonly=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='case_id.offense_category_id', store=True, readonly=True)
    
    # Referral context from parent case
    case_description = fields.Text(related='case_id.description', string='Initiator Allegation & Incident Description', readonly=True)
    chief_review_notes = fields.Text(related='case_id.chief_review_notes', string='Executive Remark (Chief)', readonly=True)
    ceo_assignment_notes = fields.Text(related='case_id.ceo_assignment_notes', string='CEO Directive & Mandate', readonly=True)

    # Audit Team Hierarchy & Assignment
    @api.model
    def _default_director_id(self):
        emp_model = self.env['hr.employee'].sudo()
        director_user = emp_model.get_audit_director_user()
        return director_user.id if director_user else False

    def _default_target_completion_date(self):
        return fields.Date.context_today(self) + timedelta(days=10)

    director_id = fields.Many2one('res.users', string='Internal Audit Director', default=_default_director_id, readonly=True, tracking=True)
    investigator_id = fields.Many2one(
        'res.users',
        string='Assisting Lead Auditor / Team Member',
        required=False,
        tracking=True,
        help='Optional selection of assisting auditor/staff under Audit Director for information.'
    )
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)
    target_completion_date = fields.Date(string='Target Completion Date', default=_default_target_completion_date, tracking=True)

    title = fields.Char(string='Investigation Subject / Title', required=True, default=lambda self: _('Investigation of Misconduct'), tracking=True)
    
    # Narrative Audit Sections (Rich Text / Html)
    introduction = fields.Html(string='Executive Summary & Mandate')
    scope_limitations = fields.Html(string='Scope & Audit Methodology')
    summary_findings = fields.Html(string='Factual Audit Findings (Facts Established)')
    investigator_recommendation = fields.Html(string='Audit Recommendations & Proposed Actions')

    # Financial Shortage / Loss Details
    financial_loss_amount = fields.Float(string='Financial Shortage / Loss Amount (ETB)', default=0.0, tracking=True)
    loss_resolution_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('resolved', 'Resolved / Fully Recovered'),
        ('unresolved', 'Unresolved / Pending Recovery'),
    ], string='Loss Resolution Status', default='not_applicable', tracking=True)

    # Policy Articles & Liable Personnel
    liable_employee_ids = fields.One2many('discipline.investigation.liable', 'investigation_id', string='Liable Employees')
    applicable_policy = fields.Char(string='Applicable Policy / Rule Violated',
                                    help='Reference the specific bank HR policy clause or regulation violated.')
    policy_clause = fields.Char(string='Policy Clause / Section Number')
    policy_violation_references = fields.Text(string='Detailed References to Relevant Policy Articles')

    # Supporting Evidence & Witness Statements
    witness_statements = fields.Html(string='Witness Statements & Interrogation Notes')
    evidence_description = fields.Html(string='Evidence Description & Chain of Custody')

    # Document & Evidence Attachments
    report_file = fields.Binary(string='Official Signed Investigation Report (PDF)', attachment=True)
    report_filename = fields.Char(string='Report Filename')
    statement_file = fields.Binary(string='Witness & Suspect Statements Document', attachment=True)
    statement_filename = fields.Char(string='Statement Filename')
    evidence_file = fields.Binary(string='Corroborating Evidence File', attachment=True)
    evidence_filename = fields.Char(string='Evidence Filename')

    # Finding Outcome
    finding_outcome = fields.Selection([
        ('liable', 'Misconduct Confirmed (Liable)'),
        ('exonerated', 'No Fault Found (Exonerated / Allegation Unfounded)'),
    ], string='Investigation Finding Outcome', default='liable', required=True, tracking=True)

    # 5-Tier Audit Lifecycle State
    state = fields.Selection([
        ('draft', 'Audit Referral / Received'),
        ('assigned', 'Under Investigation'),
        ('manager_review', 'Audit Manager Review'),
        ('director_review', 'Audit Director Approval'),
        ('approved', 'Investigation Completed'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Manager Quality Review Sign-off
    manager_review_date = fields.Date(string='Manager Review Date', tracking=True)
    manager_review_notes = fields.Text(string='Audit Manager Review Notes', tracking=True)
    manager_signed_off_by_id = fields.Many2one('res.users', string='Reviewed By (Manager)', tracking=True)

    # Director Final Sign-off & Announcement
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed & Approved By (Director)', tracking=True)
    management_review_date = fields.Date(string='Management Review Date', tracking=True)
    director_signoff_date = fields.Date(string='Director Sign-off Date', tracking=True)
    director_review_notes = fields.Text(string='Director Approval Remarks', tracking=True)

    can_ceo_forward_case = fields.Boolean(
        compute='_compute_can_ceo_forward_case',
        string='Can CEO Forward Case'
    )

    @api.depends('state', 'case_id', 'case_id.state')
    def _compute_can_ceo_forward_case(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('base.group_system')
        emp = current_user.employee_id
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
        is_ceo = bool(
            (ceo_user and current_user.id == ceo_user.id) or
            (emp and (emp.executive_level == 'ceo' or any(k in job_name for k in ['ceo', 'president', 'chief executive']))) or
            current_user.has_group('discipline_management.group_discipline_ceo') or
            is_admin
        )
        for rec in self:
            rec.can_ceo_forward_case = bool(is_ceo and rec.state == 'approved' and rec.case_id and rec.case_id.state == 'ceo_review')

    @api.onchange('case_id')
    def _onchange_case_id(self):
        if self.case_id:
            if not self.applicable_policy and self.case_id.offense_id:
                self.applicable_policy = self.case_id.offense_id.name
            if not self.summary_findings and self.case_id.description:
                self.summary_findings = f'<p>{self.case_id.description}</p>'

    @api.onchange('finding_outcome', 'case_id')
    def _onchange_finding_outcome_populate_liable(self):
        if self.finding_outcome == 'liable' and self.case_id and self.case_id.employee_id:
            if not self.liable_employee_ids:
                self.liable_employee_ids = [(0, 0, {
                    'employee_id': self.case_id.employee_id.id,
                    'role_in_incident': _('Primary Subject of Incident'),
                    'degree_of_liability': 'principal',
                    'recommended_action': _('Disciplinary Action per Policy'),
                })]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') in (_('New'), 'New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.investigation') or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTION METHODS
    # -------------------------------------------------------------------------

    def action_start_investigation(self):
        """Audit Directorate formally commences the investigation and dispatches notifications to all 5 key stakeholders."""
        for rec in self:
            rec.write({'state': 'assigned'})
            
            # Post chatter update on investigation record
            rec.message_post(body=Markup(_(
                'Formal internal audit investigation <strong>%s</strong> has commenced under Internal Audit Director <strong>%s</strong> (Target Completion: %s).'
            ) % (rec.name, self.env.user.name, rec.target_completion_date or _('Not Set'))))
            
            # Post chatter update on parent case record
            if rec.case_id:
                rec.case_id.message_post(body=Markup(_(
                    'Internal Audit Directorate has formally commenced investigation on case <strong>%s</strong> (Investigation Ref: <strong>%s</strong>).'
                ) % (rec.case_id.name, rec.name)))

            rec._send_investigation_started_discuss_notifications()

    action_assign_investigation = action_start_investigation

    def _send_investigation_started_discuss_notifications(self):
        """Send 1-on-1 Odoo Discuss direct messages to 5 key stakeholders: Employee, Coach, Director, Chief, and CEO."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            sender_user = self.env.user
            sender_partner = sender_user.partner_id

            # Stakeholder Resolution
            emp_user = rec.employee_id.user_id if rec.employee_id else False
            coach_user = (rec.case_id.reported_by_id and rec.case_id.reported_by_id.user_id) or (rec.employee_id.parent_id and rec.employee_id.parent_id.user_id) if rec.employee_id else False
            director_user = rec.case_id.director_id or (rec.case_id.initiator_id if rec.case_id.initiator_id != emp_user else False)
            chief_user = rec.case_id.chief_id or EmpModel.get_cpco_user()
            ceo_user = EmpModel.get_ceo_user()

            incident_str = rec.case_id.incident_date.strftime('%B %d, %Y') if (rec.case_id and rec.case_id.incident_date) else _('N/A')
            offense_name = rec.offense_id.name if rec.offense_id else (rec.case_id.offense_id.name if rec.case_id and rec.case_id.offense_id else _('Alleged Misconduct Clause'))
            sev_name = rec.case_id.severity_level_id.name if (rec.case_id and rec.case_id.severity_level_id) else (dict(rec.case_id._fields['severity_level'].selection).get(rec.case_id.severity_level, rec.case_id.severity_level or _('N/A')) if rec.case_id else _('N/A'))
            target_date_str = rec.target_completion_date.strftime('%B %d, %Y') if rec.target_completion_date else _('Standard Target (10 Days)')

            # Helper to safely post 1-on-1 discuss message
            def _post_discuss_msg(recipient_user, header_title, msg_html):
                if not recipient_user or not recipient_user.partner_id or recipient_user.id == sender_user.id:
                    return
                try:
                    rec.message_subscribe(partner_ids=[recipient_user.partner_id.id])
                    channel = False
                    if hasattr(self.env['discuss.channel'], '_get_or_create_chat'):
                        channel = self.env['discuss.channel'].with_user(sender_user)._get_or_create_chat(partners_to=[recipient_user.partner_id.id])
                    elif hasattr(self.env['discuss.channel'], 'channel_get'):
                        channel_info = self.env['discuss.channel'].sudo().channel_get(partners_to=[sender_partner.id, recipient_user.partner_id.id])
                        if channel_info and 'id' in channel_info:
                            channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])
                    
                    if channel:
                        channel.message_post(
                            body=msg_html,
                            message_type='comment',
                            subtype_xmlid='mail.mt_comment',
                            author_id=sender_partner.id,
                        )
                except Exception:
                    pass

            # 1. Notify Subject Employee
            if emp_user:
                emp_msg = Markup(_(
                    '<p><strong>Official Notice: Disciplinary Audit Investigation Commenced</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Please be notified that the Internal Audit Directorate has formally commenced an investigation regarding disciplinary case Ref: <strong>%s</strong> (Investigation Ref: <strong>%s</strong>).</p>'
                    '<ul>'
                    '<li><strong>Alleged Misconduct:</strong> %s</li>'
                    '<li><strong>Incident Date:</strong> %s</li>'
                    '<li><strong>Target Completion:</strong> %s</li>'
                    '</ul>'
                    '<p>The Internal Audit Directorate may contact you to provide testimony, interrogation statements, and corroborating records.</p>'
                ) % (
                    emp_user.name,
                    rec.case_id.name if rec.case_id else rec.name,
                    rec.name,
                    offense_name,
                    incident_str,
                    target_date_str,
                ))
                _post_discuss_msg(emp_user, 'Audit Investigation Commenced', emp_msg)

            # 2. Notify Immediate Coach / Reporting Manager
            if coach_user:
                coach_msg = Markup(_(
                    '<p><strong>Notice: Internal Audit Investigation Started for Subordinate Employee</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Formal internal audit inquiry has officially commenced regarding your team member <strong>%s</strong> under Case Ref: <strong>%s</strong> (Investigation Ref: <strong>%s</strong>).</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s)</li>'
                    '<li><strong>Alleged Offense:</strong> %s</li>'
                    '<li><strong>Target Completion:</strong> %s</li>'
                    '</ul>'
                    '<p>You can track the ongoing case status in Bunna Bank ERP under <strong>Discipline Management</strong>.</p>'
                ) % (
                    coach_user.name,
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.case_id.name if rec.case_id else rec.name,
                    rec.name,
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.job_id.name if rec.employee_id and rec.employee_id.job_id else _('Position'),
                    offense_name,
                    target_date_str,
                ))
                _post_discuss_msg(coach_user, 'Audit Started - Subordinate', coach_msg)

            # 3. Notify Directorate Director
            if director_user and director_user.id != coach_user.id:
                dir_msg = Markup(_(
                    '<p><strong>Audit Directorate Update: Investigation In Progress</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Formal audit investigation (Ref: <strong>%s</strong>) has been initiated for escalated case <strong>%s</strong> regarding employee <strong>%s</strong>.</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s)</li>'
                    '<li><strong>Department / Unit:</strong> %s</li>'
                    '<li><strong>Alleged Offense:</strong> %s</li>'
                    '<li><strong>Target Completion:</strong> %s</li>'
                    '</ul>'
                ) % (
                    director_user.name,
                    rec.name,
                    rec.case_id.name if rec.case_id else rec.name,
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.job_id.name if rec.employee_id and rec.employee_id.job_id else _('Position'),
                    rec.case_id.department_id.name if rec.case_id and rec.case_id.department_id else _('Department'),
                    offense_name,
                    target_date_str,
                ))
                _post_discuss_msg(director_user, 'Audit Started - Department', dir_msg)

            # 4. Notify Respective Chief Officer
            if chief_user:
                chief_msg = Markup(_(
                    '<p><strong>Executive Update: Audit Investigation Commenced</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Internal Audit Directorate has formally commenced the investigation for disciplinary case Ref: <strong>%s</strong> (Investigation Ref: <strong>%s</strong>) regarding employee <strong>%s</strong>.</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                    '<li><strong>Offense Clause:</strong> %s</li>'
                    '<li><strong>Severity Level:</strong> %s</li>'
                    '<li><strong>Target Completion:</strong> %s</li>'
                    '</ul>'
                ) % (
                    chief_user.name,
                    rec.case_id.name if rec.case_id else rec.name,
                    rec.name,
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.job_id.name if rec.employee_id and rec.employee_id.job_id else _('Position'),
                    rec.case_id.department_id.name if rec.case_id and rec.case_id.department_id else _('Department'),
                    offense_name,
                    sev_name,
                    target_date_str,
                ))
                _post_discuss_msg(chief_user, 'Executive Update: Audit Started', chief_msg)

            # 5. Notify Chief Executive Officer (CEO)
            if ceo_user:
                ceo_msg = Markup(_(
                    '<p><strong>CEO Briefing: Formal Disciplinary Investigation Commenced</strong></p>'
                    '<p>Dear %s,</p>'
                    '<p>Per your executive directive, the Internal Audit Directorate has officially commenced formal investigation on case Ref: <strong>%s</strong> (Investigation Ref: <strong>%s</strong>).</p>'
                    '<ul>'
                    '<li><strong>Subject Employee:</strong> %s (%s, %s)</li>'
                    '<li><strong>Offense Clause:</strong> %s</li>'
                    '<li><strong>Severity Level:</strong> %s</li>'
                    '<li><strong>Target Completion Date:</strong> %s</li>'
                    '</ul>'
                    '<p>Upon completion, the full investigative dossier and signed findings report will be submitted for committee action.</p>'
                ) % (
                    ceo_user.name,
                    rec.case_id.name if rec.case_id else rec.name,
                    rec.name,
                    rec.employee_id.name if rec.employee_id else _('Staff'),
                    rec.employee_id.job_id.name if rec.employee_id and rec.employee_id.job_id else _('Position'),
                    rec.case_id.department_id.name if rec.case_id and rec.case_id.department_id else _('Department'),
                    offense_name,
                    sev_name,
                    target_date_str,
                ))
                _post_discuss_msg(ceo_user, 'CEO Briefing: Audit Commenced', ceo_msg)

    def action_director_approve_and_announce(self):
        """Audit Directorate completes investigation and formally submits findings directly to CPCO while notifying CEO."""
        for rec in self:
            # 1. Mandatory Validations
            if not rec.summary_findings or rec.summary_findings.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Factual Audit Findings (Facts Established) must be completed before finishing the investigation.'))
            if not rec.investigator_recommendation or rec.investigator_recommendation.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Audit Recommendations & Proposed Actions must be completed before finishing the investigation.'))
            if not rec.report_file:
                raise UserError(_('Mandatory Document Missing: Please upload the Official Signed Investigation Report (PDF) before finishing.'))

            # 2. Liable Outcome Validations
            if rec.finding_outcome == 'liable':
                if not rec.applicable_policy:
                    rec.applicable_policy = rec.offense_id.name if rec.offense_id else _('Discipline Misconduct Policy')
                if not rec.liable_employee_ids:
                    if rec.case_id and rec.case_id.employee_id:
                        self.env['discipline.investigation.liable'].create({
                            'investigation_id': rec.id,
                            'employee_id': rec.case_id.employee_id.id,
                            'role_in_incident': 'Primary Subject of Incident',
                            'degree_of_liability': 'principal',
                            'recommended_action': 'Disciplinary Action per Policy',
                        })
                    else:
                        raise UserError(_('At least one Liable Employee must be recorded when misconduct is confirmed.'))

            # 3. Financial Loss Resolution Check
            if rec.financial_loss_amount > 0 and rec.loss_resolution_status == 'not_applicable':
                raise UserError(_('Financial Shortage is ETB %s. Please update Loss Resolution Status to Resolved or Unresolved.') % rec.financial_loss_amount)

            today = fields.Date.context_today(self)
            rec.write({
                'state': 'approved',
                'reviewed_by_id': self.env.user.id,
                'management_review_date': today,
                'director_signoff_date': today,
            })

            liable_names = ', '.join(rec.liable_employee_ids.mapped('employee_id.name')) if rec.liable_employee_ids else _('None (Exonerated)')
            outcome_label = _('Misconduct Confirmed (Liable)') if rec.finding_outcome == 'liable' else _('No Fault Found (Exonerated)')
            
            # Resolve CPCO and CEO users
            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            ceo_user = EmpModel.get_ceo_user()
            
            cpco_name = cpco_user.name if cpco_user else _('Chief People & Culture Officer')
            ceo_name = ceo_user.name if ceo_user else _('Chief Executive Officer')

            announcement_body = Markup(_(
                '<strong>Audit Investigation Completed &amp; Formally Announced:</strong><br/>'
                '• Investigation Ref: <strong>%s</strong><br/>'
                '• Submitting Auditor / Director: %s<br/>'
                '• Finding Outcome: <strong>%s</strong><br/>'
                '• Liable Employee(s): %s<br/>'
                '• Financial Shortage: ETB %0.2f (%s)<br/>'
                '• Applicable Policy: %s<br/>'
                '• Target Authority for Next Action: <strong>%s (CPCO)</strong><br/>'
                '• Executive FYI: %s (CEO)<br/>'
                '• Completed On: %s'
            ) % (
                rec.name,
                self.env.user.name,
                outcome_label,
                liable_names,
                rec.financial_loss_amount,
                dict(rec._fields['loss_resolution_status'].selection).get(rec.loss_resolution_status, 'N/A'),
                rec.applicable_policy or 'N/A',
                cpco_name,
                ceo_name,
                today.strftime('%B %d, %Y') if today else _('Today'),
            ))

            rec.message_post(body=announcement_body)

            # Update Parent Case & Route directly to CPCO (chairman_review) with multi-recipient notifications
            if rec.case_id:
                rec.case_id.with_context(force_write=True).write({
                    'state': 'chairman_review',
                })
                
                partners_to_notify = []
                if cpco_user and cpco_user.partner_id:
                    partners_to_notify.append(cpco_user.partner_id.id)
                if ceo_user and ceo_user.partner_id:
                    partners_to_notify.append(ceo_user.partner_id.id)
                if rec.case_id.employee_id and rec.case_id.employee_id.user_id and rec.case_id.employee_id.user_id.partner_id:
                    partners_to_notify.append(rec.case_id.employee_id.user_id.partner_id.id)

                rec.case_id.message_post(
                    body=announcement_body,
                    partner_ids=list(set(partners_to_notify)) if partners_to_notify else False,
                )

    action_audit_complete_and_submit_to_cpco = action_director_approve_and_announce

    def action_director_return(self):
        """Audit Director returns investigation to Lead Auditor & Manager."""
        for rec in self:
            if not rec.director_review_notes:
                raise UserError(_('Please provide Director Approval Remarks explaining why the investigation is returned.'))
            rec.write({'state': 'assigned'})
            rec.message_post(body=_(
                'Investigation returned by Audit Director %s.<br/>'
                '<strong>Director Remarks:</strong> %s'
            ) % (self.env.user.name, rec.director_review_notes))

    # Aliases for backward compatibility
    def action_announce_findings(self):
        return self.action_director_approve_and_announce()

    def action_submit_findings(self):
        return self.action_submit_for_manager_review()

    def action_accept_findings(self):
        return self.action_director_approve_and_announce()

    def action_ceo_forward_case_to_committee_chair(self):
        """CEO forwards the parent disciplinary case to Disciplinary Committee Chairman directly from the investigation record."""
        for rec in self:
            if not rec.case_id:
                raise UserError(_('No disciplinary case linked to this investigation.'))
            rec.case_id.action_ceo_forward_to_committee_chair()
            rec.message_post(body=_(
                'Parent Disciplinary Case %s forwarded to Disciplinary Committee Chairman by CEO %s.'
            ) % (rec.case_id.name, self.env.user.name))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Case Forwarded'),
                'message': _('Disciplinary Case %s has been forwarded to Disciplinary Committee Chairman (CPCO).') % self.case_id.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }


