# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class PerformanceRejectionReplyWizard(models.TransientModel):
    _name = 'performance.rejection.reply.wizard'
    _description = 'Manager Response to Employee Rejection'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    action_type = fields.Selection([
        ('notify', 'Re-Notify Employee'),
        ('reset_draft', 'Reset to Draft'),
    ], string='Action to Perform', required=True, default='notify')

    rejection_reason = fields.Text(
        string='Employee Rejection Reason',
        readonly=True,
    )
    manager_reply = fields.Text(
        string='Manager Response / Reply',
        required=True,
        help='Please explain your response or the adjustments made to address the employee rejection reason.',
    )

    def action_submit_reply(self):
        self.ensure_one()
        if not self.manager_reply or not self.manager_reply.strip():
            raise UserError('Please provide a response/reply to the employee before proceeding.')

        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError('The record you are replying to no longer exists.')

        reply_text = self.manager_reply.strip()
        record.write({
            'manager_rejection_reply': reply_text,
        })
        record.message_post(body=f"<strong>Manager Response to Employee Rejection:</strong><br/>{reply_text}")

        if self.action_type == 'notify':
            return record.action_notify()
        elif self.action_type == 'reset_draft':
            return record.action_reset_draft()
        return {'type': 'ir.actions.act_window_close'}
