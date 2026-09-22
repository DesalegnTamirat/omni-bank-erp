# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DisciplineRevocationWizard(models.TransientModel):
    _name = 'discipline.revocation.wizard'
    _description = 'Disciplinary Case Formal Revocation Wizard'

    case_id = fields.Many2one('discipline.case', string='Case to Revoke', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', readonly=True)
    
    # Mandatory Justification Requirement
    revocation_reason = fields.Text(string='Formal Revocation Justification & Legal Basis', required=True)
    approval_notes = fields.Text(string='Senior Management Approval Details', required=True)

    def action_confirm_revocation(self):
        """to: Revoke case with mandatory justification preserving original record."""
        self.ensure_one()
        # Revocation Authority Check
        if not self.env.user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Revocation Authority Violation: Only authorized HR Administrators or Senior Management can revoke disciplinary cases.'))

        case = self.case_id
        if not self.revocation_reason:
            raise UserError(_('Formal revocation justification is mandatory.'))

        today = fields.Date.context_today(self)

        # Mark case as revoked without deleting
        case.write({
            'state': 'revoked',
            'is_revoked': True,
            'revocation_reason': self.revocation_reason,
            'revoked_by_id': self.env.user.id,
            'revocation_date': today,
        })

        # Revert employee disciplinary status
        emp = case.employee_id
        emp.active_disciplinary_action = False
        if emp.disciplinary_warning_count > 0:
            emp.disciplinary_warning_count -= 1

        # Cancel any active/pending payroll penalties associated with this case
        case.payroll_penalty_ids.write({'state': 'cancelled'})

        # Post immutable audit log in chatter
        case.message_post(
            body=_('CASE REVOKED by HR Administrator %s on %s.\nJustification: %s\nApproval Details: %s') % (
                self.env.user.name, today, self.revocation_reason, self.approval_notes
            )
        )
        return {'type': 'ir.actions.act_window_close'}
