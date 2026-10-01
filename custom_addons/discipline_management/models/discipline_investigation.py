# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


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
    
    # Audit Team Hierarchy & Assignment
    @api.model
    def _default_director_id(self):
        emp_model = self.env['hr.employee'].sudo()
        director_user = emp_model.get_audit_director_user()
        return director_user.id if director_user else False

    @api.model
    def _default_audit_manager_id(self):
        emp = self.env['hr.employee'].sudo().search([('job_id.name', 'ilike', 'Audit Manager'), ('user_id', '!=', False)], limit=1)
        return emp.user_id.id if emp and emp.user_id else False

    director_id = fields.Many2one('res.users', string='Internal Audit Director', default=_default_director_id, tracking=True)
    audit_manager_id = fields.Many2one('res.users', string='Assigned Audit Manager', default=_default_audit_manager_id, tracking=True)
    investigator_id = fields.Many2one('res.users', string='Lead Investigator / Auditor', required=False, tracking=True)
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)
    target_completion_date = fields.Date(string='Target Completion Date', tracking=True)

    title = fields.Char(string='Investigation Subject / Title', required=True, default=lambda self: _('Investigation of Misconduct'), tracking=True)
    
    # Narrative Audit Sections (Rich Text / Html)
    introduction = fields.Html(string='Executive Summary & Mandate', tracking=True)
    scope_limitations = fields.Html(string='Scope & Audit Methodology', tracking=True)
    summary_findings = fields.Html(string='Factual Audit Findings (Facts Established)', tracking=True)
    investigator_recommendation = fields.Html(string='Audit Recommendations & Proposed Actions', tracking=True)

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
        ('draft', 'Unassigned / Referral'),
        ('assigned', 'Under Investigation'),
        ('manager_review', 'Audit Manager Review'),
        ('director_review', 'Audit Director Approval'),
        ('approved', 'Reviewed & Announced'),
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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.investigation') or _('New')
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WORKFLOW ACTION METHODS
    # -------------------------------------------------------------------------

    def action_assign_investigation(self):
        """Audit Director / Manager assigns Lead Auditor and target date."""
        for rec in self:
            if not rec.investigator_id:
                raise UserError(_('Please assign a Lead Investigator / Auditor before starting investigation.'))
            rec.write({'state': 'assigned'})
            rec.message_post(body=_(
                'Investigation %s assigned to Lead Auditor <strong>%s</strong> (Target Completion: %s).'
            ) % (rec.name, rec.investigator_id.name, rec.target_completion_date or _('Not Set')))

    def action_submit_for_manager_review(self):
        """Lead Auditor submits completed investigation packet for Audit Manager QA Review."""
        for rec in self:
            # 1. Mandatory Text Validations
            if not rec.summary_findings or rec.summary_findings.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Factual Audit Findings (Facts Established) must be completed before submitting.'))
            if not rec.investigator_recommendation or rec.investigator_recommendation.strip() in ['', '<p><br></p>', '<p></p>']:
                raise UserError(_('Audit Recommendations & Proposed Actions must be completed before submitting.'))

            # 2. Mandatory Signed PDF Report Document
            if not rec.report_file:
                raise UserError(_('Mandatory Document Missing: Please upload the Official Signed Investigation Report (PDF) before submitting.'))

            # 3. Liable Outcome Validations
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

            # 4. Financial Loss Resolution Check
            if rec.financial_loss_amount > 0 and rec.loss_resolution_status == 'not_applicable':
                raise UserError(_('Financial Shortage is ETB %s. Please update Loss Resolution Status to Resolved or Unresolved.') % rec.financial_loss_amount)

            rec.write({'state': 'manager_review'})
            rec.message_post(body=_('Investigation findings and signed report submitted for Audit Manager Quality Review by %s.') % self.env.user.name)

    def action_manager_approve(self):
        """Audit Manager completes quality review and forwards to Audit Director."""
        for rec in self:
            rec.write({
                'state': 'director_review',
                'manager_signed_off_by_id': self.env.user.id,
                'manager_review_date': fields.Date.context_today(self),
            })
            rec.message_post(body=_('Audit Manager Quality Review approved by %s. Forwarded for Director Final Approval.') % self.env.user.name)

    def action_manager_return(self):
        """Audit Manager returns investigation to Lead Auditor for revision."""
        for rec in self:
            if not rec.manager_review_notes:
                raise UserError(_('Please provide Manager Review Notes explaining what revisions are required.'))
            rec.write({'state': 'assigned'})
            rec.message_post(body=_(
                'Investigation returned for revision by Audit Manager %s.<br/>'
                '<strong>Revision Notes:</strong> %s'
            ) % (self.env.user.name, rec.manager_review_notes))

    def action_director_approve_and_announce(self):
        """Audit Director approves and formally announces completed findings to Disciplinary System."""
        for rec in self:
            today = fields.Date.context_today(self)
            rec.write({
                'state': 'approved',
                'reviewed_by_id': self.env.user.id,
                'management_review_date': today,
                'director_signoff_date': today,
            })

            liable_names = ', '.join(rec.liable_employee_ids.mapped('employee_id.name')) if rec.liable_employee_ids else _('None (Exonerated)')
            outcome_label = _('Misconduct Confirmed (Liable)') if rec.finding_outcome == 'liable' else _('No Fault Found (Exonerated)')
            announcement_body = _(
                '<strong>Audit Investigation Approved &amp; Formally Announced:</strong><br/>'
                '• Investigation Ref: %s<br/>'
                '• Lead Auditor: %s | Manager: %s | Director: %s<br/>'
                '• Outcome: <strong>%s</strong><br/>'
                '• Liable Employee(s): %s<br/>'
                '• Financial Loss: ETB %0.2f (%s)<br/>'
                '• Policy Violated: %s<br/>'
                '• Announcement Date: %s'
            ) % (
                rec.name,
                rec.investigator_id.name if rec.investigator_id else 'N/A',
                rec.manager_signed_off_by_id.name if rec.manager_signed_off_by_id else (rec.audit_manager_id.name if rec.audit_manager_id else 'N/A'),
                self.env.user.name,
                outcome_label,
                liable_names,
                rec.financial_loss_amount,
                dict(rec._fields['loss_resolution_status'].selection).get(rec.loss_resolution_status, 'N/A'),
                rec.applicable_policy or 'N/A',
                today
            )

            rec.message_post(body=announcement_body)

            # Update Parent Case & Route to CEO for Executive Review
            if rec.case_id:
                rec.case_id.message_post(body=announcement_body)
                rec.case_id.with_context(force_write=True).write({
                    'state': 'ceo_review',
                })
                rec.case_id.message_post(body=_(
                    'Audit investigation %s concluded and announced. Case submitted to Chief Executive Officer (CEO) for executive review.'
                ) % rec.name)

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


