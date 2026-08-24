# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrEmployeeDelegationCancelWizard(models.TransientModel):
    _name = 'hr.employee.delegation.cancel.wizard'
    _description = 'Delegation Cancellation Wizard'

    delegation_id = fields.Many2one(
        'hr.employee.delegation',
        string="Delegation Request",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get('active_id')
    )
    delegator_id = fields.Many2one(
        'hr.employee',
        string="Manager / Delegator",
        related='delegation_id.employee_id',
        readonly=True
    )
    delegate_id = fields.Many2one(
        'hr.employee',
        string="Delegated Staff / Delegate",
        related='delegation_id.delegate_id',
        readonly=True
    )
    start_date = fields.Date(
        string="Scheduled Start Date",
        related='delegation_id.start_date',
        readonly=True
    )
    end_date = fields.Date(
        string="Scheduled End Date",
        related='delegation_id.end_date',
        readonly=True
    )
    reason_code = fields.Selection([
        ('early_return', 'Early Return from Leave / Mission'),
        ('reassigned', 'Delegated Responsibilities Reassigned'),
        ('no_longer_needed', 'Delegation No Longer Required'),
        ('operational_change', 'Operational / Organizational Change'),
        ('other', 'Other Reason'),
    ], string="Cancellation Reason", required=True, default='early_return')

    reason_details = fields.Text(string="Reason Notes / Details")

    effective_date = fields.Date(
        string="Effective Cancellation Date",
        required=True,
        default=fields.Date.today
    )

    def action_confirm_cancel(self):
        self.ensure_one()
        delegation = self.delegation_id
        if not delegation:
            raise UserError(_("No delegation record found to cancel."))

        # Compile final reason text
        reason_label = dict(self._fields['reason_code'].selection).get(self.reason_code, self.reason_code)
        if self.reason_details:
            full_reason = f"{reason_label}: {self.reason_details}"
        else:
            full_reason = reason_label

        delegation._cancel_and_notify(
            reason=full_reason,
            cancellation_date=self.effective_date,
            cancelled_by=self.env.user
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Delegation Cancelled"),
                'message': _("Delegation %s has been cancelled and notifications sent to the delegate and stakeholders.") % delegation.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }
