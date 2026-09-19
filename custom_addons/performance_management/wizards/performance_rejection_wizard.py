# -*- coding: utf-8 -*-
from markupsafe import Markup
from odoo import fields, models
from odoo.exceptions import UserError


class PerformanceRejectionWizard(models.TransientModel):
    _name = 'performance.rejection.wizard'
    _description = 'Performance Rejection Reason Wizard'

    reason = fields.Text(
        string='Reason for Rejection',
        required=True,
        help='Please specify the reason why you are rejecting this document.',
    )
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError('Please provide a valid reason for rejection.')

        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError('The record you are rejecting no longer exists.')

        reason_text = self.reason.strip()
        doc_title = getattr(record, 'name', False) or getattr(record, 'planning_name', '') or 'Performance Document'

        record.write({
            'state': 'rejected',
            'rejection_reason': reason_text,
        })

        # Locate manager
        manager = (
            getattr(record, 'manager_id', False)
            or (record.employee_id.parent_id if hasattr(record, 'employee_id') and record.employee_id else False)
            or (record.employee_id.coach_id if hasattr(record, 'employee_id') and record.employee_id else False)
        )
        partner = manager.user_id.partner_id if (manager and manager.user_id) else False

        # Build clean formatted HTML notification
        body_html = Markup(
            '<div style="font-family: Arial, sans-serif; font-size: 13px; line-height: 1.5;">'
            '<div style="padding: 10px 14px; background-color: #fbf0f0; border-left: 4px solid #541718; border-radius: 4px; margin-bottom: 8px;">'
            '<strong style="color: #541718; font-size: 14px;">⚠️ Performance Document Rejected by Employee</strong><br/>'
            '<span style="color: #333;"><strong>Document:</strong> %s</span>'
            '</div>'
            '<div style="padding: 10px 14px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 4px; margin-bottom: 8px;">'
            '<strong style="color: #1d2b32;">Reason for Rejection:</strong>'
            '<p style="margin: 6px 0 0 0; color: #541718; font-style: italic;">%s</p>'
            '</div>'
            '<p style="color: #666; font-size: 12px; margin: 0;">Please review the document, adjust targets or measurements if necessary, and click <b>Notify</b> to re-notify the employee.</p>'
            '</div>'
        ) % (doc_title, reason_text)

        partner_ids = [partner.id] if partner else []
        if partner:
            record.message_subscribe(partner_ids=partner_ids)

        record.message_post(
            body=body_html,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=partner_ids,
        )

        # Notify manager via direct message_notify and schedule activity
        if partner:
            try:
                record.message_notify(
                    partner_ids=partner_ids,
                    body=body_html,
                    subject='Performance Document Rejected: %s' % doc_title,
                    record_name=doc_title,
                )
            except Exception:
                pass

        if manager and manager.user_id:
            try:
                record.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=manager.user_id.id,
                    summary='Performance Document Rejected: %s' % doc_title,
                    note=Markup(
                        'The employee has rejected this document with reason:<br/>'
                        '<blockquote style="border-left: 3px solid #541718; margin: 4px 0; padding-left: 8px; color: #541718;">%s</blockquote>'
                        'Please review, make adjustments if needed, and re-notify the employee.'
                    ) % reason_text,
                )
            except Exception:
                pass

        return {'type': 'ir.actions.act_window_close'}
