# -*- coding: utf-8 -*-
from odoo import models, api, fields

class MailNotification(models.Model):
    """
    Centralized Notification Filter:
    1. Suppresses email failure alerts ('Email Failure: Time Off', etc.) from business users.
    2. Ensures web client store only serves notifications where res_partner_id matches current user.
    """
    _inherit = 'mail.notification'

    def _filtered_for_web_client(self):
        res = super()._filtered_for_web_client()
        cfg = self.env['bunna.notification.manager'].sudo().get_config()
        is_admin = self.env.user.has_group('base.group_system')

        # 1. Suppress email failure alerts for non-admin users
        if cfg and cfg.suppress_email_failures and not is_admin:
            res = res.filtered(lambda n: n.notification_status not in ('bounce', 'exception', 'canceled'))

        # 2. Strict personal isolation: users only see their own notifications in the web client
        if cfg and cfg.strict_personal_isolation and not is_admin:
            my_partner = self.env.user.partner_id
            res = res.filtered(lambda n: n.res_partner_id == my_partner)

        return res


class MailThread(models.AbstractModel):
    """
    Centralized MailThread Interceptor:
    Ensures notifications across ALL modules (Planning/PBMS, Attendance, Leaves, Master Data, etc.)
    are routed strictly to direct stakeholders and approvers instead of blasting entire role groups.
    """
    _inherit = 'mail.thread'

    def _notify_thread_by_inbox(self, message, recipients_data, msg_vals=False, **kwargs):
        cfg = self.env['bunna.notification.manager'].sudo().get_config()
        if cfg and cfg.strict_personal_isolation and cfg.auto_filter_group_broadcasts and recipients_data and self:
            direct_partner_ids = set()
            for rec in self:
                # 1. Direct Author / Requester / Owner:
                for author_f in (
                    'requested_by', 'requested_by_id', 'employee_id',
                    'applicant_id', 'user_id', 'create_uid'
                ):
                    if hasattr(rec, author_f):
                        val = getattr(rec, author_f)
                        if hasattr(val, 'partner_id') and val.partner_id:
                            direct_partner_ids.add(val.partner_id.id)
                        elif hasattr(val, 'user_id') and val.user_id and val.user_id.partner_id:
                            direct_partner_ids.add(val.user_id.partner_id.id)

                # 2. Direct Approver / Responsible Officer / Manager:
                for approver_f in (
                    'hr_officer_id', 'coach_id', 'parent_id', 'responsible_user_id',
                    'assigned_to', 'approver_id', 'reviewer_id', 'manager_id', 'line_manager_id'
                ):
                    if hasattr(rec, approver_f):
                        val = getattr(rec, approver_f)
                        if hasattr(val, 'partner_id') and val.partner_id:
                            direct_partner_ids.add(val.partner_id.id)
                        elif hasattr(val, 'user_id') and val.user_id and val.user_id.partner_id:
                            direct_partner_ids.add(val.user_id.partner_id.id)

            # Explicit message mentions always receive the notification
            if message and message.partner_ids:
                direct_partner_ids |= set(message.partner_ids.ids)

            # If direct stakeholders were identified and there are more than 2 recipients (role group broadcast),
            # strictly limit inbox delivery to the direct stakeholders:
            if direct_partner_ids and len(recipients_data) > 2:
                recipients_data = [r for r in recipients_data if r.get('id') in direct_partner_ids]

        return super()._notify_thread_by_inbox(message, recipients_data, msg_vals=msg_vals, **kwargs)
