# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError
from ..models.performance_notification_helper import send_performance_notification


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

        record = self.env[self.res_model].sudo().browse(self.res_id)
        if not record.exists():
            raise UserError('The record you are rejecting no longer exists.')

        reason_text = self.reason.strip()
        doc_title = (
            getattr(record, 'planning_name', False)
            or getattr(record, 'name', False)
            or getattr(record, 'display_name', False)
            or 'Performance Document'
        )

        record.write({
            'state': 'rejected',
            'rejection_reason': reason_text,
        })

        # Clear existing activities for employee
        try:
            record.activity_feedback(['mail.mail_activity_data_todo'], feedback=f"Document rejected: {reason_text}")
        except Exception:
            pass

        # Locate manager / planning
        manager = (
            getattr(record, 'manager_id', False)
            or (record.employee_id.parent_id if hasattr(record, 'employee_id') and record.employee_id else False)
            or (record.employee_id.coach_id if hasattr(record, 'employee_id') and record.employee_id else False)
        )
        mgr_user = manager.user_id if manager else False
        partner = mgr_user.partner_id if mgr_user else False
        partner_ids = [partner.id] if partner else []

        emp = getattr(record, 'employee_id', False)
        emp_name = emp.name if emp else (getattr(record, 'operating_unit_id', False).name if hasattr(record, 'operating_unit_id') and record.operating_unit_id else 'Employee')
        manager_name = manager.name if manager else 'Manager / Planning Administrator'

        period = getattr(record, 'appraisal_period_id', False)
        period_name = period.name if period else ''
        fy = getattr(record, 'fiscal_year_id', False)
        fy_name = fy.name if fy else ''

        details = [
            ("Document Name", f"<strong>{doc_title}</strong>"),
            ("Rejected By", f"<strong>{emp_name}</strong>"),
            ("Manager / Planning", manager_name),
        ]
        if period_name:
            details.append(("Appraisal Period", f"{period_name} ({fy_name})"))
        if hasattr(record, 'operating_unit_id') and record.operating_unit_id:
            details.append(("Operating Unit", record.operating_unit_id.name))
        details.extend([
            ("Rejection Reason", f'<span style="color: #c53030; font-weight: bold; font-style: italic;">{reason_text}</span>'),
            ("Current Status", '<span style="background-color: #fed7d7; color: #9b2c2c; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">REJECTED</span>'),
        ])

        send_performance_notification(
            record=record,
            title="⚠️ Performance Document Rejected",
            badge_text="REJECTED",
            badge_bg="#dc3545",
            border_color="#dc3545",
            intro_text=f"Employee <strong>{emp_name}</strong> has <strong>REJECTED</strong> the performance document <strong>{doc_title}</strong>. Please review the reason provided below, adjust targets or measurements if necessary, and re-notify.",
            details=details,
            action_btn_text="🎯 Open Performance Record",
            action_btn_color="#541718",
            footer_note=f"Please make adjustments to the document and click <b>Notify</b> to re-notify <b>{emp_name}</b>.",
            recipient_partner_ids=partner_ids,
            activity_user_id=mgr_user.id if mgr_user else False,
            activity_summary=f"Rejected: {doc_title} - Reason: {reason_text[:60]}",
        )

        return {'type': 'ir.actions.act_window_close'}
