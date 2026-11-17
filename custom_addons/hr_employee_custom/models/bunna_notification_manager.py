# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class BunnaNotificationManager(models.Model):
    """
    EM-NOTIF-001: Centralized Bank-wide Notification Management & Control Center.
    Enforces privacy, strictly isolates notifications to individual recipients across all modules,
    and prevents noise pollution from broadcast role groups and system email failure alerts.
    """
    _name = 'bunna.notification.manager'
    _description = 'Bank Notification Control Center'
    _rec_name = 'name'

    name = fields.Char(string='Configuration Name', default='Bunna Bank Central Notification Policy', required=True)
    active = fields.Boolean(string='Active', default=True)

    strict_personal_isolation = fields.Boolean(
        string='Strict Personal Isolation',
        default=True,
        help="When enabled, non-admin users only ever see notifications addressed directly to their individual "
             "partner profile across ALL modules (Planning/PBMS, Attendance, Leaves, Master Data, Recruitment, etc.)."
    )

    suppress_email_failures = fields.Boolean(
        string='Suppress Email Failure Alerts',
        default=True,
        help="When enabled, email/SMTP delivery failure notifications (e.g. 'Email Failure: Time Off') "
             "are hidden from business users and restricted to System Administrators."
    )

    auto_filter_group_broadcasts = fields.Boolean(
        string='Filter Broad Group Broadcasts',
        default=True,
        help="When a workflow notification has a direct assigned reviewer, manager, or owner, "
             "prevents broadcasting to every member of the role group."
    )

    total_unread_count = fields.Integer(
        string='Bank Unread Notifications',
        compute='_compute_notification_metrics',
        help="Total unread notifications currently pending in the bank database."
    )

    my_unread_count = fields.Integer(
        string='My Unread Notifications',
        compute='_compute_notification_metrics',
        help="Unread notifications for the currently logged-in user."
    )

    total_failure_count = fields.Integer(
        string='Total Email/Delivery Failures',
        compute='_compute_notification_metrics',
        help="Total failed/bounced delivery notifications in the system."
    )

    @api.model
    def get_config(self):
        """Returns the active notification configuration singleton."""
        config = self.sudo().search([('active', '=', True)], limit=1)
        if not config:
            config = self.sudo().create({
                'name': 'Bunna Bank Central Notification Policy',
                'strict_personal_isolation': True,
                'suppress_email_failures': True,
                'auto_filter_group_broadcasts': True,
            })
        return config

    def _compute_notification_metrics(self):
        """Computes bank-wide and user-specific notification metrics."""
        user_partner_id = self.env.user.partner_id.id
        Notif = self.env['mail.notification'].sudo()
        
        # Total unread bank-wide
        total_unread = Notif.search_count([('is_read', '=', False)])
        
        # User unread
        my_unread = Notif.search_count([('res_partner_id', '=', user_partner_id), ('is_read', '=', False)])
        
        # Total failures
        total_failures = Notif.search_count([('notification_status', 'in', ('bounce', 'exception', 'canceled'))])

        for rec in self:
            rec.total_unread_count = total_unread
            rec.my_unread_count = my_unread
            rec.total_failure_count = total_failures

    def action_clear_my_backlog(self):
        """Marks all pending unread notifications for the current user as read."""
        user_partner_id = self.env.user.partner_id.id
        notifs = self.env['mail.notification'].sudo().search([
            ('res_partner_id', '=', user_partner_id),
            ('is_read', '=', False)
        ])
        count = len(notifs)
        if notifs:
            notifs.write({'is_read': True})

        # Also dismiss failure alerts for this partner
        failures = self.env['mail.notification'].sudo().search([
            ('res_partner_id', '=', user_partner_id),
            ('notification_status', 'in', ('bounce', 'exception', 'canceled'))
        ])
        if failures:
            failures.write({'notification_status': 'sent', 'is_read': True})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Notification Backlog Cleared'),
                'message': _('Successfully cleared %d unread notifications for your account.') % count,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_clear_all_failures(self):
        """System Administrator action to dismiss all bounced/exception failure alerts across the bank."""
        if not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only System Administrators can clear bank-wide delivery failures."))
        failures = self.env['mail.notification'].sudo().search([
            ('notification_status', 'in', ('bounce', 'exception', 'canceled'))
        ])
        count = len(failures)
        if failures:
            failures.write({'notification_status': 'sent', 'is_read': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Email Failures Cleared'),
                'message': _('Successfully cleared %d delivery failure alerts across the bank.') % count,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_clear_user_backlog_dialog(self):
        """Opens wizard to clear backlog for a specific employee or user."""
        return {
            'name': _('Clear Employee Notification Backlog'),
            'type': 'ir.actions.act_window',
            'res_model': 'bunna.notification.clear.wizard',
            'view_mode': 'form',
            'target': 'new',
        }


class BunnaNotificationClearWizard(models.TransientModel):
    _name = 'bunna.notification.clear.wizard'
    _description = 'Wizard to Clear Specific Employee Notification Backlog'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    clear_all_employees = fields.Boolean(string='Clear for ALL Bank Users', default=False)

    def action_execute_clear(self):
        self.ensure_one()
        Notif = self.env['mail.notification'].sudo()
        if self.clear_all_employees:
            if not self.env.user.has_group('base.group_system'):
                raise UserError(_("Only System Administrators can clear bank-wide notification backlogs."))
            unread_notifs = Notif.search([('is_read', '=', False)])
            count = len(unread_notifs)
            unread_notifs.write({'is_read': True})
            msg = _("Cleared %d unread notifications across the entire bank.") % count
        else:
            if not self.employee_id.user_id or not self.employee_id.user_id.partner_id:
                raise UserError(_("The selected employee does not have a linked system user or partner."))
            partner_id = self.employee_id.user_id.partner_id.id
            unread_notifs = Notif.search([('res_partner_id', '=', partner_id), ('is_read', '=', False)])
            count = len(unread_notifs)
            unread_notifs.write({'is_read': True})
            
            # Also clear any failure statuses
            failures = Notif.search([
                ('res_partner_id', '=', partner_id),
                ('notification_status', 'in', ('bounce', 'exception', 'canceled'))
            ])
            failures.write({'notification_status': 'sent', 'is_read': True})
            msg = _("Cleared %d unread notifications for %s.") % (count, self.employee_id.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Backlog Cleanup Completed'),
                'message': msg,
                'type': 'success',
                'sticky': False,
            }
        }
