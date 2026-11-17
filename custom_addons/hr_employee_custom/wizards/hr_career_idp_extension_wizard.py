# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HrCareerIdpExtensionWizard(models.TransientModel):
    """
    Employee IDP Completion Date Extension Request Wizard.
    Allows an employee on an active IDP to submit a proposed revised date with justification.
    """
    _name = "hr.career.idp.extension.wizard"
    _description = "Request IDP Completion Date Extension"

    idp_id = fields.Many2one(
        'hr.career.idp', string='Development Plan', required=True, readonly=True
    )
    employee_id = fields.Many2one(
        'hr.employee', related='idp_id.employee_id', string='Employee', readonly=True
    )
    current_completion_date = fields.Date(
        string='Current Completion Date',
        related='idp_id.target_completion_date',
        readonly=True
    )
    proposed_completion_date = fields.Date(
        string='Proposed New Completion Date', required=True
    )
    days_extended = fields.Integer(
        string='Additional Days Requested',
        compute='_compute_days_extended'
    )
    reason = fields.Text(
        string='Extension Justification / Reason',
        required=True,
        help='Please explain why the extension is needed (e.g., operational workload, course availability, medical leave).'
    )

    @api.depends('proposed_completion_date', 'current_completion_date')
    def _compute_days_extended(self):
        for rec in self:
            if rec.proposed_completion_date and rec.current_completion_date:
                delta = (rec.proposed_completion_date - rec.current_completion_date).days
                rec.days_extended = max(0, delta)
            else:
                rec.days_extended = 0

    @api.constrains('proposed_completion_date', 'current_completion_date')
    def _check_dates(self):
        for rec in self:
            if rec.current_completion_date and rec.proposed_completion_date:
                if rec.proposed_completion_date <= rec.current_completion_date:
                    raise ValidationError(_(
                        "The Proposed New Completion Date (%s) must be strictly after the current completion date (%s)."
                    ) % (rec.proposed_completion_date, rec.current_completion_date))

    def action_submit_extension(self):
        self.ensure_one()
        idp = self.idp_id
        if idp.state != 'active':
            raise ValidationError(_(
                "An extension request can only be submitted when the Development Plan is Active / In Progress."
            ))

        idp.write({
            'state': 'extension_requested',
            'proposed_completion_date': self.proposed_completion_date,
            'extension_reason': self.reason,
            'extension_request_date': fields.Date.today(),
        })

        days_added = (self.proposed_completion_date - (idp.target_completion_date or fields.Date.today())).days
        idp.message_post(
            body=_(
                "<b>Completion Date Extension Requested by Employee:</b><br/>"
                "• <b>Current Target Date:</b> %s<br/>"
                "• <b>Proposed New Date:</b> %s (+%d days)<br/>"
                "• <b>Justification:</b> %s<br/>"
                "<i>Awaiting reviewing manager's evaluation and approval.</i>"
            ) % (idp.target_completion_date, self.proposed_completion_date, days_added, self.reason)
        )

        mgr = idp.manager_id or (idp.employee_id and idp.employee_id.parent_id)
        if mgr and mgr.user_id:
            idp.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('IDP Date Extension Requested: %s') % idp.name,
                note=_(
                    '%s has requested to extend their IDP completion date to %s (+%d days).\n'
                    'Justification: %s\n'
                    'Please review and approve or reject the request.'
                ) % (idp.employee_id.name, self.proposed_completion_date, days_added, self.reason),
                user_id=mgr.user_id.id,
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extension Request Submitted'),
                'message': _('Your completion date extension request has been submitted to your manager for review.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }


class HrCareerIdpExtensionRejectWizard(models.TransientModel):
    """
    Manager IDP Completion Date Extension Rejection Wizard.
    Allows a manager to provide formal feedback when declining an extension request.
    """
    _name = "hr.career.idp.extension.reject.wizard"
    _description = "Reject IDP Date Extension"

    idp_id = fields.Many2one(
        'hr.career.idp', string='Development Plan', required=True, readonly=True
    )
    rejection_reason = fields.Text(
        string='Reason for Rejection / Manager Feedback',
        required=True,
        help='Provide guidance on why the extension cannot be granted and next steps.'
    )

    def action_confirm_rejection(self):
        self.ensure_one()
        idp = self.idp_id
        is_admin = self.env.is_superuser() or self.env.user._is_admin() or self.env.user.id in (1, 2)
        current_emp = self.env.user.employee_id
        is_self = bool(
            (idp.employee_id and idp.sudo().employee_id.user_id == self.env.user) or
            (idp.employee_id and current_emp and idp.employee_id.id == current_emp.id)
        )
        if is_self and not is_admin:
            raise ValidationError(_(
                "Maker-Checker Violation: You cannot review or reject your own extension request. "
                "Only your Direct Supervisor / Line Manager or HR can review it."
            ))

        idp.write({
            'state': 'active',
            'proposed_completion_date': False,
            'extension_reason': False,
        })

        idp.message_post(
            body=_(
                "<b>IDP Completion Date Extension Declined by %s:</b><br/>"
                "• <b>Reason:</b> %s<br/>"
                "The Development Plan continues Active with its original completion date (%s)."
            ) % (self.env.user.name, self.rejection_reason, idp.target_completion_date)
        )

        if idp.employee_id and idp.employee_id.user_id:
            idp.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('IDP Extension Request Declined: %s') % idp.name,
                note=_(
                    'Your manager has reviewed and declined your completion date extension request.\n'
                    'Manager Feedback: %s\n'
                    'Your target completion date remains %s.'
                ) % (self.rejection_reason, idp.target_completion_date),
                user_id=idp.employee_id.user_id.id,
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extension Declined'),
                'message': _('Extension request declined. The plan continues Active with the current target date.'),
                'type': 'info',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
