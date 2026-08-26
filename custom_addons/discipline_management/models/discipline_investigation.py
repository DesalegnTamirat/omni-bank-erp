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
    investigator_id = fields.Many2one('res.users', string='Lead Investigator / Auditor', required=True, default=lambda self: self.env.user, readonly=True, tracking=True)
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

    # Part 2: Date of Examination
    examination_date = fields.Date(string='Date of Examination', required=True, default=fields.Date.context_today, tracking=True)

    # Part 3: Summary of Findings
    summary_findings = fields.Text(string='Summary of Findings (Facts Established)', required=True, tracking=True)

    # Part 4: Liable Employees (child model)
    liable_employee_ids = fields.One2many('discipline.investigation.liable', 'investigation_id', string='Liable Employees')

    # Part 5: Applicable Policy / Rule Violated
    applicable_policy = fields.Char(string='Applicable Policy / Rule Violated', required=True,
                                    help='Reference the specific bank HR policy clause or regulation violated.')
    policy_clause = fields.Char(string='Policy Clause / Section Number')

    # Part 6: Witness Statements & Evidence
    witness_statements = fields.Text(string='Witness Statements & Interviews')
    evidence_description = fields.Text(string='Evidence Description & Chain of Custody')

    # Part 7: Investigator Conclusion & Recommendation
    investigator_recommendation = fields.Text(string='Investigator Conclusion & Recommendation', required=True)

    # Part 8: Management Review Sign-off
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

    def action_submit_findings(self):
        for rec in self:
            if not rec.liable_employee_ids:
                raise UserError(_('At least one Liable Employee must be recorded before submitting findings.'))
            if not rec.applicable_policy:
                raise UserError(_('The applicable policy / rule violated must be specified.'))
            rec.write({'state': 'submitted'})
            rec.case_id.message_post(body=_(
                'Investigation findings submitted by investigator %s. '
                'Liable employees: %s.'
            ) % (rec.investigator_id.name, ', '.join(rec.liable_employee_ids.mapped('employee_id.name'))))

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

