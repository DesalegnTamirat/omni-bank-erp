# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineInvestigationLiableEmployee(models.Model):
    """DIS-6: FR-DIS-013 Part 4 — Child line for each employee found liable."""
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
    investigator_id = fields.Many2one('res.users', string='Lead Investigator / Auditor', required=True, default=lambda self: self.env.user, tracking=True)
    investigation_date = fields.Date(string='Investigation Date', required=True, default=fields.Date.context_today, tracking=True)

    # FR-DIS-013 Part 1: Type of Misconduct
    misconduct_type = fields.Selection([
        ('attendance', 'Attendance Violation'),
        ('insubordination', 'Insubordination'),
        ('fraud', 'Fraud / Misappropriation'),
        ('policy_breach', 'Policy / Procedure Breach'),
        ('conduct', 'Conduct Unbecoming'),
        ('other', 'Other'),
    ], string='Type of Misconduct', required=True, tracking=True)
    misconduct_type_notes = fields.Char(string='Misconduct Type Details')

    # FR-DIS-013 Part 2: Date of Examination
    examination_date = fields.Date(string='Date of Examination', required=True, default=fields.Date.context_today, tracking=True)

    # FR-DIS-013 Part 3: Summary of Findings
    summary_findings = fields.Text(string='Summary of Findings (Facts Established)', required=True, tracking=True)

    # FR-DIS-013 Part 4: Liable Employees (child model)
    liable_employee_ids = fields.One2many('discipline.investigation.liable', 'investigation_id', string='Liable Employees')

    # FR-DIS-013 Part 5: Applicable Policy / Rule Violated
    applicable_policy = fields.Char(string='Applicable Policy / Rule Violated', required=True,
                                    help='Reference the specific bank HR policy clause or regulation violated.')
    policy_clause = fields.Char(string='Policy Clause / Section Number')

    # FR-DIS-013 Part 6: Witness Statements & Evidence
    witness_statements = fields.Text(string='Witness Statements & Interviews')
    evidence_description = fields.Text(string='Evidence Description & Chain of Custody')

    # FR-DIS-013 Part 7: Investigator Conclusion & Recommendation
    investigator_recommendation = fields.Text(string='Investigator Conclusion & Recommendation', required=True)

    # FR-DIS-013 Part 8: Management Review Sign-off
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed & Approved By (Management)', tracking=True)
    management_review_date = fields.Date(string='Management Review Date', tracking=True)
    management_review_notes = fields.Text(string='Management Review Notes / Approval Remarks')

    # Document & Evidence Attachments (FR-DIS-014)
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.investigation') or _('New')
        return super().create(vals_list)

    def action_submit_findings(self):
        for rec in self:
            if not rec.liable_employee_ids:
                raise UserError(_('FR-DIS-013: At least one Liable Employee must be recorded before submitting findings.'))
            if not rec.applicable_policy:
                raise UserError(_('FR-DIS-013: The applicable policy / rule violated must be specified.'))
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

