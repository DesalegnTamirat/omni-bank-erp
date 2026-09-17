# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineInvestigationLiableEmployee(models.Model):
    """Part 4 — Child line for each employee found liable."""
    _name = 'discipline.investigation.liable'
    _description = 'Liable Employee in Investigation'

    investigation_id = fields.Many2one('discipline.investigation', string='Investigation', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Liable Employee', required=True)
    role_in_incident = fields.Char(string='Role / Involvement in Incident')
    degree_of_liability = fields.Selection([
        ('principal', 'Principal Offender'),
        ('accessory', 'Accessory / Participant'),
        ('witness', 'Witness'),
    ], string='Degree of Liability', required=True, default='principal')
    recommended_action = fields.Char(string='Recommended Action')


class DisciplineInvestigation(models.Model):
    _name = 'discipline.investigation'
    _description = 'Disciplinary Investigation & Findings'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'investigation_date desc, id desc'

    name = fields.Char(string='Investigation Ref', required=True, default=lambda self: _('New'), copy=False)
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', store=True, readonly=True)
    offense_id = fields.Many2one('discipline.offense', string='Offense Type / Misconduct', related='case_id.offense_id', store=True, readonly=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='case_id.offense_category_id', store=True, readonly=True)
    investigator_id = fields.Many2one('res.users', string='Lead Investigator / Auditor', required=False, tracking=True)
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)

    # Part 1: Type of Misconduct
    misconduct_type = fields.Selection([
        ('attendance', 'Attendance Violation'),
        ('insubordination', 'Insubordination'),
        ('fraud', 'Fraud / Misappropriation'),
        ('policy_breach', 'Policy / Procedure Breach'),
        ('conduct', 'Conduct Unbecoming'),
        ('other', 'Other'),
    ], string='Legacy Misconduct Type', tracking=True)
    misconduct_type_notes = fields.Char(string='Misconduct Type Details')

    @api.onchange('case_id')
    def _onchange_case_id(self):
        if self.case_id:
            if not self.applicable_policy and self.case_id.offense_id:
                self.applicable_policy = self.case_id.offense_id.name
            if not self.summary_findings and self.case_id.description:
                self.summary_findings = self.case_id.description

    # Standardized 8-Part Investigation Structure
    # 1. Title / Subject
    title = fields.Char(string='Investigation Subject / Title', required=True, default=lambda self: _('Investigation of Misconduct'), tracking=True)
    
    # 2. Introduction
    introduction = fields.Text(string='1. Introduction', tracking=True)
    
    # 3. Scope & Limitations of Investigation
    scope_limitations = fields.Text(string='2. Scope & Limitations of Investigation', tracking=True)

    # 4. Investigation Findings
    summary_findings = fields.Text(string='3. Investigation Findings (Facts Established)', tracking=True)

    # 5. Financial Shortage / Loss Amount (If applicable)
    financial_loss_amount = fields.Float(string='4. Financial Shortage / Loss Amount (ETB)', default=0.0, tracking=True)

    # 6. Resolution Status of Financial / Property Loss (Resolved / Unresolved)
    loss_resolution_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('resolved', 'Resolved / Fully Recovered'),
        ('unresolved', 'Unresolved / Pending Recovery'),
    ], string='5. Loss Resolution Status', default='not_applicable', tracking=True)

    # 7. Liable Employees & Policy Violations
    liable_employee_ids = fields.One2many('discipline.investigation.liable', 'investigation_id', string='Liable Employees')
    applicable_policy = fields.Char(string='Applicable Policy / Rule Violated',
                                    help='Reference the specific bank HR policy clause or regulation violated.')
    policy_clause = fields.Char(string='Policy Clause / Section Number')
    policy_violation_references = fields.Text(string='6. Detailed References to Relevant Policy Articles')

    # Supporting Evidence & Witness Statements
    witness_statements = fields.Text(string='Witness Statements & Interviews')
    evidence_description = fields.Text(string='Evidence Description & Chain of Custody')

    # 8. Recommendations
    investigator_recommendation = fields.Text(string='7. Recommendations & Proposed Actions')

    # Management Review Sign-off
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed & Approved By (Management)', tracking=True)
    management_review_date = fields.Date(string='Management Review Date', tracking=True)
    management_review_notes = fields.Text(string='Management Review Notes / Approval Remarks')

    # Document & Evidence Attachments
    report_file = fields.Binary(string='Investigation Report Document', attachment=True)
    report_filename = fields.Char(string='Report Filename')
    evidence_file = fields.Binary(string='Evidence File', attachment=True)
    evidence_filename = fields.Char(string='Evidence Filename')
    statement_file = fields.Binary(string='Witness Statement Document', attachment=True)
    statement_filename = fields.Char(string='Statement Filename')

    finding_outcome = fields.Selection([
        ('liable', 'Misconduct Confirmed (Liable)'),
        ('exonerated', 'No Fault Found (Exonerated / Allegation Unfounded)'),
    ], string='Investigation Finding Outcome', default='liable', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft Findings'),
        ('submitted', 'Submitted to Case'),
        ('approved', 'Reviewed & Accepted'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Suspension Request during Investigation (Requirement 3)
    is_suspension_required = fields.Boolean(
        string='Requires Suspension during Investigation',
        default=False,
        tracking=True,
        help='Check if the employee under investigation should be suspended from work during investigation.'
    )
    suspension_type = fields.Selection([
        ('with_pay', 'Suspension With Pay'),
        ('without_pay', 'Suspension Without Pay'),
    ], string='Requested Suspension Type', default='without_pay', tracking=True)
    suspension_duration_days = fields.Integer(string='Requested Suspension Duration (Days)', default=30, tracking=True)
    suspension_reason = fields.Text(string='Suspension Justification / Reason', tracking=True)
    suspension_request_state = fields.Selection([
        ('none', 'Not Requested'),
        ('requested', 'Suspension Requested'),
        ('approved', 'Suspension Approved by HR'),
        ('rejected', 'Suspension Rejected'),
    ], string='Suspension Status', default='none', tracking=True)
    suspension_id = fields.Many2one('discipline.suspension', string='Linked Suspension Record', readonly=True)

    def action_request_suspension(self):
        for rec in self:
            if not rec.is_suspension_required:
                raise UserError(_('Please check "Requires Suspension during Investigation" before requesting suspension.'))
            if not rec.suspension_reason:
                raise UserError(_('Please provide a Suspension Justification / Reason.'))
            if rec.suspension_duration_days <= 0 or rec.suspension_duration_days > 30:
                raise UserError(_('Suspension duration must be between 1 and 30 days.'))
            
            # Create draft suspension record
            susp_vals = {
                'case_id': rec.case_id.id,
                'employee_id': rec.case_id.employee_id.id,
                'suspension_type': rec.suspension_type,
                'start_date': fields.Date.context_today(self),
                'reason': rec.suspension_reason,
            }
            susp = self.env['discipline.suspension'].create(susp_vals)
            rec.write({
                'suspension_id': susp.id,
                'suspension_request_state': 'requested'
            })
            rec.case_id.message_post(body=_(
                'Suspension Request created by Investigator %s for Employee %s (%s, %d days).'
            ) % (self.env.user.name, rec.case_id.employee_id.name, rec.suspension_type, rec.suspension_duration_days))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.investigation') or _('New')
        return super().create(vals_list)

    def action_announce_findings(self):
        """Announce completed investigation findings to CEO, Committee Secretary (POMD), and Committee Chairman (CPCO)."""
        for rec in self:
            if rec.finding_outcome == 'liable' and not rec.liable_employee_ids:
                raise UserError(_('At least one Liable Employee must be recorded when misconduct is confirmed.'))
            if not rec.summary_findings:
                raise UserError(_('Investigation Findings summary must be filled out before announcing.'))
            if not rec.investigator_recommendation:
                raise UserError(_('Investigator Recommendations & Proposed Actions must be filled out before announcing.'))

            rec.write({'state': 'submitted'})

            liable_names = ', '.join(rec.liable_employee_ids.mapped('employee_id.name')) if rec.liable_employee_ids else _('None (Exonerated)')
            outcome_label = _('Misconduct Confirmed (Liable)') if rec.finding_outcome == 'liable' else _('No Fault Found (Exonerated)')
            announcement_body = _(
                '<strong>Audit Investigation Completed &amp; Findings Announced:</strong><br/>'
                '• Investigation Ref: %s<br/>'
                '• Lead Investigator: %s<br/>'
                '• Outcome: <strong>%s</strong><br/>'
                '• Liable Employee(s): %s<br/>'
                '• Policy Violated: %s<br/>'
                '• Summary Findings: %s<br/>'
                '• Recommendations: %s'
            ) % (
                rec.name,
                rec.investigator_id.name if rec.investigator_id else 'Audit Team',
                outcome_label,
                liable_names,
                rec.applicable_policy or 'N/A',
                rec.summary_findings or 'N/A',
                rec.investigator_recommendation or 'N/A'
            )

            # Post on Investigation record
            rec.message_post(body=announcement_body)

            # Handle Case Updates & Routing based on finding outcome
            if rec.case_id:
                rec.case_id.message_post(body=announcement_body)
                
                if rec.finding_outcome == 'exonerated':
                    # Exoneration: Case stays in investigating waiting for CEO endorsement
                    ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
                    ceo_users = (ceo_group.all_user_ids or ceo_group.user_ids) if ceo_group else self.env['res.users']
                    for ceo in ceo_users:
                        rec.case_id.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Action Required: Endorse Audit Exoneration for %s') % rec.case_id.name,
                            note=_('Audit investigation %s concluded NO FAULT (Exonerated). Please review findings and click "Endorse Exoneration & Direct Reinstatement".') % rec.name,
                            user_id=ceo.id
                        )
                    pomd_group = self.env.ref('discipline_management.group_discipline_pomd', raise_if_not_found=False)
                    pomd_users = (pomd_group.all_user_ids or pomd_group.user_ids) if pomd_group else self.env['res.users']
                    for pomd in pomd_users:
                        rec.case_id.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Information: Audit Findings Exonerated %s') % rec.case_id.name,
                            note=_('Audit investigation %s concluded with Exoneration. Pending CEO executive endorsement to revoke suspension.') % rec.name,
                            user_id=pomd.id
                        )
                else:
                    # Liable: Update parent Case: move to committee_review and lock for committee
                    rec.case_id.with_context(force_write=True).write({
                        'state': 'committee_review',
                        'is_locked_for_committee': True
                    })

                    # Broadcast Notifications / Activities:
                    # 1. Chief Executive Officer (CEO)
                    ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
                    ceo_users = (ceo_group.all_user_ids or ceo_group.user_ids) if ceo_group else self.env['res.users']
                    for ceo in ceo_users:
                        rec.case_id.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Audit Findings Announced: Case %s (%s)') % (rec.case_id.name, rec.employee_id.name),
                            note=_('Audit investigation %s is completed. Liable: %s. Case is now under Disciplinary Committee review.') % (rec.name, liable_names),
                            user_id=ceo.id
                        )

                    # 2. Committee Secretary (POMD)
                    pomd_group = self.env.ref('discipline_management.group_discipline_pomd', raise_if_not_found=False)
                    pomd_users = (pomd_group.all_user_ids or pomd_group.user_ids) if pomd_group else self.env['res.users']
                    for pomd in pomd_users:
                        rec.case_id.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Schedule Hearing: Audit Findings Received for Case %s') % rec.case_id.name,
                            note=_('Audit investigation %s findings are announced. Please schedule Disciplinary Committee meeting and notify members.') % rec.name,
                            user_id=pomd.id
                        )

                    # 3. Committee Chairman (CPCO)
                    cpco_group = self.env.ref('discipline_management.group_discipline_cpco', raise_if_not_found=False)
                    cpco_users = (cpco_group.all_user_ids or cpco_group.user_ids) if cpco_group else self.env['res.users']
                    for cpco in cpco_users:
                        rec.case_id.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Committee Chair Notification: Audit Findings for Case %s') % rec.case_id.name,
                            note=_('Audit investigation %s findings received. Committee review is now active for case %s.') % (rec.name, rec.case_id.name),
                            user_id=cpco.id
                        )

    def action_submit_findings(self):
        """Backward compatibility alias for action_announce_findings."""
        return self.action_announce_findings()

    def action_accept_findings(self):
        for rec in self:
            if not rec.reviewed_by_id:
                rec.reviewed_by_id = self.env.user
            if not rec.management_review_date:
                rec.management_review_date = fields.Date.context_today(self)
            rec.write({'state': 'approved'})
            rec.case_id.message_post(body=_(
                'Investigation findings officially reviewed and accepted by %s on %s.'
            ) % (rec.reviewed_by_id.name, rec.management_review_date))

