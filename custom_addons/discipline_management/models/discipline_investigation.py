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
    employee_name = fields.Char(string='Employee Name', compute='_compute_employee_name', store=True, readonly=True)
    role_in_incident = fields.Char(string='Role / Involvement in Incident', default='Primary Subject of Incident')
    degree_of_liability = fields.Selection([
        ('principal', 'Principal Offender'),
        ('accessory', 'Accessory / Accomplice'),
        ('supervisory_negligence', 'Supervisory Negligence'),
        ('witness', 'Witness (Non-Liable)'),
    ], string='Degree of Liability', required=True, default='principal')
    recommended_action = fields.Char(string='Recommended Action', default='Disciplinary Action per Policy')

    @api.depends('employee_id')
    def _compute_employee_name(self):
        for rec in self:
            rec.employee_name = rec.sudo().employee_id.name or ''


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

    @api.model
    def calculate_target_completion_date(self, start_date=None, target_days=None):
        """Calculate target completion date strictly based on working days (Monday-Friday) from configuration."""
        if not start_date:
            start_date = fields.Date.context_today(self)
        if isinstance(start_date, str):
            start_date = fields.Date.from_string(start_date)
        if target_days is None:
            ICP = self.env['ir.config_parameter'].sudo()
            target_days = int(ICP.get_param('discipline.investigation_target_days', 10))
        if target_days <= 0:
            return start_date

        curr = start_date
        counted = 0
        while counted < target_days:
            if curr.weekday() < 5:  # Monday to Friday
                counted += 1
                if counted == target_days:
                    break
            curr += timedelta(days=1)
        return curr

    def _default_target_completion_date(self):
        return self.calculate_target_completion_date()

    director_id = fields.Many2one('res.users', string='Internal Audit Director', default=_default_director_id, readonly=True, tracking=True)
    investigator_id = fields.Many2one(
        'res.users',
        string='Assisting Lead Auditor / Team Member',
        required=False,
        copy=False,
        tracking=True,
    )
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)
    target_completion_date = fields.Date(
        string='Target Completion Date',
        default=_default_target_completion_date,
        readonly=True,
        tracking=True,
        help='Target completion deadline strictly in working days, synchronized from Disciplinary Governance Settings.'
    )

    @api.onchange('investigation_date')
    def _onchange_investigation_date(self):
        if self.investigation_date and self.state == 'draft':
            self.target_completion_date = self.calculate_target_completion_date(self.investigation_date)

    title = fields.Char(string='Investigation Subject / Title', required=True, default=lambda self: _('Investigation of Misconduct'), tracking=True)
    
    # Narrative Audit Sections (Rich Text / Html)
    introduction = fields.Html(string='Executive Summary & Mandate')
    scope_limitations = fields.Html(string='Scope & Audit Methodology')
    summary_findings = fields.Html(string='Audit Findings')
    investigator_recommendation = fields.Html(string='Recommendations')

    # Cash Shortage Context & Financial Loss Details
    is_cash_shortage = fields.Boolean(
        string='Is Cash Shortage Misconduct',
        compute='_compute_is_cash_shortage',
        store=True,
        readonly=True
    )
    financial_loss_amount = fields.Float(string='Financial Shortage / Loss Amount (ETB)', default=0.0, tracking=True)
    loss_resolution_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('resolved', 'Resolved / Fully Recovered'),
        ('unresolved', 'Unresolved / Pending Recovery'),
    ], string='Loss Resolution Status', default='not_applicable', tracking=True)

    @api.depends('case_id', 'case_id.is_cash_shortage', 'case_id.cash_shortage_amount', 'offense_id')
    def _compute_is_cash_shortage(self):
        for rec in self:
            csh = False
            if rec.case_id and (rec.case_id.is_cash_shortage or rec.case_id.cash_shortage_amount > 0):
                csh = True
            elif rec.offense_id and rec.offense_id.category_id and rec.offense_id.category_id.code == 'CSH':
                csh = True
            elif rec.offense_id and '33.9' in (rec.offense_id.sub_article_code or ''):
                csh = True
            rec.is_cash_shortage = csh

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

    # Initial case evidence reference for quick inspection
    initial_case_attachment = fields.Binary(
        related='case_id.supporting_attachment',
        string='Initial Incident Evidence (Case Referral)',
        readonly=True,
    )
    initial_case_attachment_filename = fields.Char(
        related='case_id.attachment_filename',
        string='Initial Evidence Filename',
        readonly=True,
    )

    # Finding Outcome / Conclusion
    finding_outcome = fields.Selection([
        ('none', 'None'),
        ('substantiated', 'Substantiated'),
        ('non_substantiated', 'Non Substantiated'),
    ], string='Audit Conclusion', default='none', required=True, tracking=True)

    # Sequential Audit & Executive Handoff Lifecycle State
    state = fields.Selection([
        ('draft', 'Audit Referral / Received'),
        ('assigned', 'Under Investigation'),
        ('manager_review', 'Audit Manager Review'),
        ('director_review', 'Audit Director Approval'),
        ('submitted_ceo', 'Submitted to CEO'),
        ('forwarded_cpco', 'Forwarded to CPCO'),
        ('approved', 'Released to Committee / POMD'),
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
    can_cpco_forward_case = fields.Boolean(
        compute='_compute_can_cpco_forward_case',
        string='Can CPCO Forward Case'
    )

    @api.depends('state', 'case_id', 'case_id.state')
    @api.depends_context('uid')
    def _compute_can_ceo_forward_case(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        ceo_user = EmpModel.get_ceo_user()
        is_admin = current_user.has_group('discipline_management.group_discipline_admin') or current_user._is_superuser()
        emp = current_user.sudo().employee_id
        job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
        is_ceo = bool(
            (ceo_user and current_user.id == ceo_user.id) or
            (emp and (emp.executive_level == 'ceo' or any(k in job_name for k in ['ceo', 'president', 'chief executive']))) or
            current_user.has_group('discipline_management.group_discipline_ceo') or
            is_admin
        )
        for rec in self:
            rec.can_ceo_forward_case = bool(
                is_ceo and rec.state in ('submitted_ceo', 'approved') and (not rec.case_id or rec.case_id.state in ('ceo_review', 'investigating'))
            )

    @api.depends('state', 'case_id', 'case_id.state')
    @api.depends_context('uid')
    def _compute_can_cpco_forward_case(self):
        current_user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        ceo_user = EmpModel.get_ceo_user()

        # Strictly hide from CEO
        is_ceo = bool(
            (ceo_user and current_user.id == ceo_user.id) or
            current_user.has_group('discipline_management.group_discipline_ceo')
        )

        # Visible for CPCO only
        is_cpco = bool(
            not is_ceo and (
                (cpco_user and current_user.id == cpco_user.id) or
                current_user.has_group('discipline_management.group_discipline_cpco') or
                current_user._is_superuser()
            )
        )
        for rec in self:
            rec.can_cpco_forward_case = bool(
                is_cpco and rec.state == 'forwarded_cpco' and rec.case_id and rec.case_id.state == 'chairman_review'
            )

    @api.onchange('case_id')
    def _onchange_case_id(self):
        if self.case_id:
            if not self.applicable_policy and self.case_id.offense_id:
                self.applicable_policy = self.case_id.offense_id.name

    @api.onchange('finding_outcome', 'case_id')
    def _onchange_finding_outcome_populate_liable(self):
        if self.finding_outcome in ('substantiated', 'liable') and self.case_id and self.case_id.sudo().employee_id:
            if not self.liable_employee_ids:
                self.liable_employee_ids = [(0, 0, {
                    'employee_id': self.case_id.sudo().employee_id.id,
                    'role_in_incident': _('Primary Subject of Incident'),
                    'degree_of_liability': 'principal',
                    'recommended_action': _('Disciplinary Action per Policy'),
                })]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') in (_('New'), 'New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.investigation') or _('New')
            if not vals.get('target_completion_date'):
                start_dt = vals.get('investigation_date')
                vals['target_completion_date'] = self.calculate_target_completion_date(start_dt)
            if vals.get('case_id') and not vals.get('financial_loss_amount'):
                case = self.env['discipline.case'].browse(vals['case_id']).sudo()
                if case and case.cash_shortage_amount:
                    vals['financial_loss_amount'] = case.cash_shortage_amount
            if vals.get('finding_outcome') in ('substantiated', 'liable') and vals.get('case_id') and not vals.get('liable_employee_ids'):
                case = self.env['discipline.case'].browse(vals['case_id']).sudo()
                if case and case.employee_id:
                    vals['liable_employee_ids'] = [(0, 0, {
                        'employee_id': case.employee_id.id,
                        'role_in_incident': _('Primary Subject of Incident'),
                        'degree_of_liability': 'principal',
                        'recommended_action': _('Disciplinary Action per Policy'),
                    })]
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            if rec.finding_outcome in ('substantiated', 'liable') and not rec.liable_employee_ids and rec.case_id and rec.case_id.employee_id:
                self.env['discipline.investigation.liable'].sudo().create({
                    'investigation_id': rec.id,
                    'employee_id': rec.case_id.employee_id.id,
                    'role_in_incident': _('Primary Subject of Incident'),
                    'degree_of_liability': 'principal',
                    'recommended_action': _('Disciplinary Action per Policy'),
                })
        return res

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'assigned'):
                raise UserError(_('Active Investigation Protection: Investigations under review or submitted for executive action cannot be deleted.'))
            user = self.env.user
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
            is_creator = bool(rec.create_uid and rec.create_uid.id == user.id)
            if not (is_admin or is_creator or self.env.su):
                raise UserError(_('Permission Denied: You are not authorized to delete investigation %s.') % rec.name)
        return super().unlink()

    # -------------------------------------------------------------------------
    # WORKFLOW ACTION METHODS
    # -------------------------------------------------------------------------

    def action_start_investigation(self):
        """Audit Directorate formally commences the investigation and notifies the CEO (strictly confidential from employee & line managers)."""
        for rec in self:
            rec.write({'state': 'assigned'})

            if rec.finding_outcome in ('substantiated', 'liable') and not rec.liable_employee_ids and rec.case_id and rec.case_id.employee_id:
                self.env['discipline.investigation.liable'].sudo().create({
                    'investigation_id': rec.id,
                    'employee_id': rec.case_id.employee_id.id,
                    'role_in_incident': _('Primary Subject of Incident'),
                    'degree_of_liability': 'principal',
                    'recommended_action': _('Disciplinary Action per Policy'),
                })
            
            # Post chatter update on investigation record only (not visible to employee/managers)
            rec.message_post(body=Markup(_(
                'Formal internal audit investigation <strong>%s</strong> has commenced under Internal Audit Director <strong>%s</strong> (Target Completion: %s).'
            ) % (rec.name, self.env.user.name, rec.target_completion_date or _('Not Set'))))

            rec._send_investigation_started_discuss_notifications()

    action_assign_investigation = action_start_investigation

    def _post_single_discuss_dm(self, target_user, sender_partner, msg_body):
        """Helper to post a direct Discuss chat message to a specific user (e.g. CEO only)."""
        if not target_user or not target_user.partner_id or target_user.id == self.env.user.id:
            return
        try:
            channel = False
            if hasattr(self.env['discuss.channel'], '_get_or_create_chat'):
                channel = self.env['discuss.channel'].sudo().with_user(self.env.user)._get_or_create_chat(
                    partners_to=[target_user.partner_id.id]
                )
            elif hasattr(self.env['discuss.channel'], 'channel_get'):
                channel_info = self.env['discuss.channel'].sudo().channel_get(
                    partners_to=[sender_partner.id, target_user.partner_id.id]
                )
                if channel_info and channel_info.get('id'):
                    channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])

            if channel:
                channel.message_post(
                    body=Markup(msg_body),
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                    author_id=sender_partner.id,
                )
        except Exception as e:
            _logger.warning("Failed to post Discuss DM to user %s: %s", target_user.name, e)

    def _send_investigation_started_discuss_notifications(self):
        """Send confidential Odoo Discuss direct message ONLY to the CEO (who ordered the audit investigation).
        Subject Employee, Coach, Director, and CPCO are NOT notified at this stage to preserve strict audit confidentiality.
        """
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            if not ceo_user:
                continue

            ceo_name = (ceo_user.partner_id.name or ceo_user.name or _('CEO')).strip()
            sender_partner = self.env.user.partner_id
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Staff')
            emp_job = emp.job_id.name if emp and emp.job_id else ''
            dept_name = rec.case_id.sudo().department_id.name if rec.case_id and rec.case_id.sudo().department_id else ''
            case_name = rec.case_id.name if rec.case_id else rec.name

            offense_name = rec.offense_id.name if rec.offense_id else (rec.case_id.offense_id.name if rec.case_id and rec.case_id.offense_id else _('Alleged Misconduct Clause'))
            sev_name = rec.case_id.severity_level_id.name if (rec.case_id and rec.case_id.severity_level_id) else (dict(rec.case_id._fields['severity_level'].selection).get(rec.case_id.severity_level, rec.case_id.severity_level or _('N/A')) if rec.case_id else _('N/A'))
            
            ICP = self.env['ir.config_parameter'].sudo()
            target_days = int(ICP.get_param('discipline.investigation_target_days', 10))
            target_date_str = rec.target_completion_date.strftime('%B %d, %Y') if rec.target_completion_date else _('Standard Target (%d Working Days)') % target_days
            director_name = self.env.user.name

            msg_body = Markup(
                f"<p><strong>CONFIDENTIAL EXECUTIVE BRIEFING: AUDIT INVESTIGATION COMMENCED</strong></p>"
                f"<p>Dear {ceo_name},</p>"
                f"<p>Per your executive governance directive, the Internal Audit Directorate has officially commenced a confidential investigation regarding Disciplinary Case <strong>{case_name}</strong> (Investigation Ref: <strong>{rec.name}</strong>):</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp_name}" + (f" ({emp_job}, {dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Alleged Misconduct:</strong> {offense_name}</li>"
                f"<li><strong>Severity Classification:</strong> {sev_name}</li>"
                f"<li><strong>Target Completion Date:</strong> {target_date_str} (<strong>{target_days} Working Days</strong>)</li>"
                f"<li><strong>Internal Audit Director:</strong> {director_name}</li>"
                f"</ul>"
                f"<p>Upon conclusion of the audit inquiries, the full investigative dossier and signed findings report will be submitted directly to the Executive Office for your review.</p>"
            )

            rec._post_single_discuss_dm(ceo_user, sender_partner, msg_body)

    def _send_investigation_completed_discuss_notification(self):
        """Send confidential Odoo Discuss direct message containing investigation results ONLY to the CEO."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            if not ceo_user:
                continue

            ceo_name = (ceo_user.partner_id.name or ceo_user.name or _('CEO')).strip()
            sender_partner = self.env.user.partner_id
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Staff')
            emp_job = emp.job_id.name if emp and emp.job_id else ''
            dept_name = rec.case_id.sudo().department_id.name if rec.case_id and rec.case_id.sudo().department_id else ''
            case_name = rec.case_id.name if rec.case_id else rec.name
            outcome_label = _('Substantiated') if rec.finding_outcome in ('substantiated', 'liable') else _('Non Substantiated')
            liable_names = ', '.join([l.sudo().employee_id.name for l in rec.sudo().liable_employee_ids if l.sudo().employee_id]) if rec.liable_employee_ids else _('None (Non Substantiated)')
            director_name = self.env.user.name

            loss_info = ""
            if rec.is_cash_shortage and rec.financial_loss_amount > 0:
                loss_status = dict(rec._fields['loss_resolution_status'].selection).get(rec.loss_resolution_status, 'N/A')
                loss_info = f"<li><strong>Financial Shortage:</strong> ETB {rec.financial_loss_amount:,.2f} ({loss_status})</li>"

            today_str = fields.Date.context_today(self).strftime('%B %d, %Y')

            msg_body = Markup(
                f"<p><strong>CONFIDENTIAL EXECUTIVE BRIEFING: AUDIT INVESTIGATION COMPLETED</strong></p>"
                f"<p>Dear {ceo_name},</p>"
                f"<p>The Internal Audit Directorate has concluded its formal inquiry on Case <strong>{case_name}</strong> (Investigation Ref: <strong>{rec.name}</strong>) and hereby submits the final investigative findings directly for your executive determination:</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp_name}" + (f" ({emp_job}, {dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Investigation Finding Outcome:</strong> <strong>{outcome_label}</strong></li>"
                f"<li><strong>Liable Personnel:</strong> {liable_names}</li>"
                f"{loss_info}"
                f"<li><strong>Submitting Authority:</strong> {director_name} (Internal Audit Director)</li>"
                f"<li><strong>Completed On:</strong> {today_str}</li>"
                f"</ul>"
                f"<p><strong>Executive Review Required:</strong></p>"
                f"<p>The parent disciplinary case has been routed to your executive queue (<strong>CEO Review</strong>). The official signed investigation report is attached to the record for your review prior to forwarding to CPCO.</p>"
            )

            rec._post_single_discuss_dm(ceo_user, sender_partner, msg_body)

    def action_director_approve_and_announce(self):
        """Audit Directorate completes investigation and formally submits findings exclusively to the CEO (not directly to CPCO)."""
        for rec in self:
            if not rec.report_file:
                raise UserError(_('Mandatory Document Missing: Please upload the Official Signed Investigation Report (PDF) before finishing.'))

            # 2. Liable Outcome Validations
            if rec.finding_outcome == 'substantiated':
                if not rec.applicable_policy:
                    rec.applicable_policy = rec.offense_id.name if rec.offense_id else _('Discipline Misconduct Policy')
                if not rec.liable_employee_ids:
                    if rec.case_id and rec.case_id.sudo().employee_id:
                        self.env['discipline.investigation.liable'].sudo().create({
                            'investigation_id': rec.id,
                            'employee_id': rec.case_id.sudo().employee_id.id,
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
                'state': 'submitted_ceo',
                'reviewed_by_id': self.env.user.id,
                'management_review_date': today,
                'director_signoff_date': today,
            })

            liable_names = ', '.join([l.sudo().employee_id.name for l in rec.sudo().liable_employee_ids if l.sudo().employee_id]) if rec.liable_employee_ids else _('None')
            if rec.finding_outcome == 'substantiated':
                outcome_label = _('Substantiated')
            elif rec.finding_outcome == 'non_substantiated':
                outcome_label = _('Non Substantiated')
            else:
                outcome_label = _('None')
            
            # Resolve CEO user exclusively
            EmpModel = self.env['hr.employee'].sudo()
            ceo_user = EmpModel.get_ceo_user()
            ceo_name = ceo_user.name if ceo_user else _('Chief Executive Officer')

            announcement_body = Markup(_(
                '<strong>Audit Investigation Completed &amp; Submitted to CEO:</strong><br/>'
                '• Investigation Ref: <strong>%s</strong><br/>'
                '• Submitting Auditor / Director: %s<br/>'
                '• Finding Outcome: <strong>%s</strong><br/>'
                '• Liable Employee(s): %s<br/>'
                '• Financial Shortage: ETB %0.2f (%s)<br/>'
                '• Applicable Policy: %s<br/>'
                '• Target Authority for Next Action: <strong>%s (CEO)</strong><br/>'
                '• Completed On: %s'
            ) % (
                rec.name,
                self.env.user.name,
                outcome_label,
                liable_names,
                rec.financial_loss_amount,
                dict(rec._fields['loss_resolution_status'].selection).get(rec.loss_resolution_status, 'N/A'),
                rec.applicable_policy or 'N/A',
                ceo_name,
                today.strftime('%B %d, %Y') if today else _('Today'),
            ))

            rec.message_post(
                body=announcement_body,
                partner_ids=[ceo_user.partner_id.id] if (ceo_user and ceo_user.partner_id) else False,
            )

            # Update Parent Case & Route exclusively to CEO (ceo_review) without leaking findings to employee or CPCO
            if rec.case_id:
                rec.case_id.sudo().with_context(force_write=True).write({
                    'state': 'ceo_review',
                })
                rec.case_id.sudo().message_post(
                    body=Markup(_(
                        'Internal Audit Investigation <strong>%s</strong> completed and submitted to <strong>%s (CEO)</strong> for executive review.'
                    ) % (rec.name, ceo_name)),
                    partner_ids=[ceo_user.partner_id.id] if (ceo_user and ceo_user.partner_id) else False,
                )

            # Direct confidential Discuss chat notification sent exclusively to CEO
            rec._send_investigation_completed_discuss_notification()

    action_audit_complete_and_submit_to_ceo = action_director_approve_and_announce
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
        return self.action_director_approve_and_announce()

    def action_accept_findings(self):
        return self.action_director_approve_and_announce()

    def action_ceo_forward_case_to_committee_chair(self):
        """CEO forwards the parent disciplinary case and investigation to Disciplinary Committee Chairman (CPCO)."""
        for rec in self:
            if not rec.case_id:
                raise UserError(_('No disciplinary case linked to this investigation.'))
            rec.case_id.action_ceo_forward_to_committee_chair()
            rec.sudo().write({'state': 'forwarded_cpco'})

            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            cpco_name = cpco_user.name if cpco_user else _('Disciplinary Committee Chairman (CPCO)')
            outcome_label = _('Substantiated') if rec.finding_outcome in ('substantiated', 'liable') else _('Non Substantiated')

            rec.message_post(
                body=Markup(_(
                    '<strong>Executive Forwarding to Disciplinary Committee Chairman:</strong><br/>'
                    '• Authority: %s (Chief Executive Officer)<br/>'
                    '• Recipient / Assigned Reviewer: <strong>%s</strong> (Disciplinary Committee Chairman)<br/>'
                    '• Parent Disciplinary Case: <strong>%s</strong><br/>'
                    '• Audit Conclusion: <strong>%s</strong><br/>'
                    '• Status: <strong>Forwarded to CPCO (forwarded_cpco)</strong>'
                ) % (self.env.user.name, cpco_name, rec.case_id.name, outcome_label)),
                partner_ids=[cpco_user.partner_id.id] if (cpco_user and cpco_user.partner_id) else False,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Forwarded to Committee Chairman'),
                'message': _('Disciplinary Case %s and Audit Investigation %s have been forwarded to Disciplinary Committee Chairman (CPCO).') % (self.case_id.name, self.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }

    def action_cpco_forward_case_to_secretary(self):
        """CPCO forwards the parent disciplinary case and investigation to Committee Secretary (POMD) for committee meeting scheduling."""
        for rec in self:
            if not rec.case_id:
                raise UserError(_('No disciplinary case linked to this investigation.'))
            rec.case_id.action_chair_forward_to_secretary()
            rec.sudo().write({'state': 'approved'})

            EmpModel = self.env['hr.employee'].sudo()
            sec_user = EmpModel.get_secretary_user()
            sec_name = sec_user.name if sec_user else _('Committee Secretary (POMD)')

            rec.message_post(
                body=Markup(_(
                    '<strong>Investigation Released to Committee Secretary (POMD):</strong><br/>'
                    '• Action by: %s (CPCO)<br/>'
                    '• Recipient: <strong>%s</strong> (Committee Secretary / POMD)<br/>'
                    '• Parent Disciplinary Case: <strong>%s</strong><br/>'
                    '• Action: Schedule Disciplinary Committee Hearing<br/>'
                    '• Status: <strong>Released to Committee / POMD (approved)</strong>'
                ) % (self.env.user.name, sec_name, rec.case_id.name)),
                partner_ids=[sec_user.partner_id.id] if (sec_user and sec_user.partner_id) else False,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Forwarded to Secretary'),
                'message': _('Disciplinary Case %s and Audit Investigation %s have been forwarded to Committee Secretary (POMD).') % (self.case_id.name, self.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }



