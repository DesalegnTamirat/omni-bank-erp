# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class HrDelegatedApproval(models.Model):
    _name = "hr.delegated.approval"
    _description = "Delegated Approval"
    _order = "state desc, request_date desc, id desc"


    name = fields.Char(string="Reference / Subject", readonly=True)
    res_model = fields.Char(string="Module / Model", readonly=True)
    res_id = fields.Integer(string="Record ID", readonly=True)
    delegation_id = fields.Many2one('hr.employee.delegation', string="Delegation Reference", readonly=True, ondelete='cascade')
    delegating_manager_id = fields.Many2one('hr.employee', string="Delegating Manager", readonly=True)
    delegate_id = fields.Many2one('hr.employee', string="Acting Delegate", readonly=True)
    requester_id = fields.Many2one('hr.employee', string="Requester", readonly=True)
    request_date = fields.Date(string="Request Date", readonly=True)
    request_type = fields.Char(string="Request Type", readonly=True)
    summary = fields.Char(string="Summary", readonly=True)
    notes = fields.Text(string="Justification / Details", readonly=True)
    state = fields.Selection([
        ('requested', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string="Status", default='requested', readonly=True)
    action_date = fields.Datetime(string="Action Date", readonly=True)
    activity_id = fields.Many2one('mail.activity', string="Activity", readonly=True)

    @api.model
    def _refresh_delegated_approvals(self, delegation_id=None):
        """ Scans pending approval requests across the ERP for active delegations
        where the current user is the authorized delegate today.
        Creates or updates tracking records without deleting history.
        """
        today = fields.Date.today()
        current_uid = self.env.uid
        current_emp = self.env.user.employee_id

        domain = [
            ('delegate_id.user_id', '=', current_uid),
            ('state', '=', 'submitted'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ]
        if delegation_id:
            domain.append(('id', '=', delegation_id))

        active_dels = self.env['hr.employee.delegation'].sudo().search(domain)
        if not active_dels:
            return

        for deleg in active_dels:
            mgr_emp = deleg.employee_id
            mgr_user = mgr_emp.user_id

            # 1. Check Mail Activities assigned to the delegating manager
            if mgr_user:
                activities = self.env['mail.activity'].sudo().search([
                    ('user_id', '=', mgr_user.id),
                    ('res_model', 'not in', ['hr.employee', 'hr.employee.delegation', 'hr.attendance', 'mail.channel', 'mail.activity', 'discuss.channel']),
                ])
                for act in activities:
                    if not act.res_model or not act.res_id:
                        continue
                    try:
                        target_rec = self.env[act.res_model].sudo().browse(act.res_id)
                        if not target_rec.exists():
                            continue

                        existing = self.sudo().search([
                            ('res_model', '=', act.res_model),
                            ('res_id', '=', act.res_id),
                            ('delegation_id', '=', deleg.id),
                        ], limit=1)

                        req_emp = False
                        if hasattr(target_rec, 'employee_id') and target_rec.employee_id:
                            req_emp = target_rec.employee_id.id
                        elif hasattr(target_rec, 'create_uid') and target_rec.create_uid.employee_id:
                            req_emp = target_rec.create_uid.employee_id.id

                        req_date = getattr(target_rec, 'date', False) or getattr(target_rec, 'create_date', False)
                        if req_date and hasattr(req_date, 'date'):
                            req_date = req_date.date()

                        target_state = getattr(target_rec, 'state', 'requested')
                        rec_state = 'approved' if target_state in ['approved', 'done', 'validate'] else ('rejected' if target_state in ['rejected', 'refused', 'cancel'] else 'requested')

                        vals = {
                            'name': act.res_name or f"{act.res_model} #{act.res_id}",
                            'res_model': act.res_model,
                            'res_id': act.res_id,
                            'delegation_id': deleg.id,
                            'delegating_manager_id': mgr_emp.id,
                            'delegate_id': current_emp.id if current_emp else False,
                            'requester_id': req_emp,
                            'request_date': req_date or today,
                            'request_type': act.activity_type_id.name or 'Approval To-Do',
                            'summary': act.summary or act.res_name,
                            'notes': act.note or '',
                            'activity_id': act.id,
                        }

                        if existing:
                            if existing.state == 'requested' and rec_state != 'requested':
                                vals['state'] = rec_state
                            existing.sudo().write(vals)
                        else:
                            vals['state'] = rec_state
                            self.sudo().create(vals)
                    except Exception as e:
                        _logger.debug(f"Error reading activity target {act.res_model} {act.res_id}: {e}")

            # 2. Check Attendance Preapprovals for Manager's Subordinates
            if 'attendance.preapproval' in self.env:
                try:
                    subs = self.env['hr.employee'].sudo().search([
                        '|', ('parent_id', '=', mgr_emp.id), ('coach_id', '=', mgr_emp.id)
                    ])
                    if subs:
                        preapps = self.env['attendance.preapproval'].sudo().search([
                            ('employee_id', 'in', subs.ids),
                            ('state', 'in', ['requested', 'approved', 'rejected']),
                        ])
                        for pa in preapps:
                            existing = self.sudo().search([
                                ('res_model', '=', 'attendance.preapproval'),
                                ('res_id', '=', pa.id),
                                ('delegation_id', '=', deleg.id),
                            ], limit=1)

                            type_label = dict(pa._fields['exception_type'].selection).get(pa.exception_type, pa.exception_type)
                            pa_state = 'approved' if pa.state == 'approved' else ('rejected' if pa.state == 'rejected' else 'requested')

                            vals = {
                                'name': f"Attendance Preapproval - {pa.employee_id.name}",
                                'res_model': 'attendance.preapproval',
                                'res_id': pa.id,
                                'delegation_id': deleg.id,
                                'delegating_manager_id': mgr_emp.id,
                                'delegate_id': current_emp.id if current_emp else False,
                                'requester_id': pa.employee_id.id,
                                'request_date': pa.date or today,
                                'request_type': f"Predefined Attendance ({type_label})",
                                'summary': f"{type_label} for {pa.employee_id.name} ({pa.time_range})",
                                'notes': pa.approval_reason or '',
                                'activity_id': False,
                            }

                            if existing:
                                if existing.state != pa_state:
                                    vals['state'] = pa_state
                                existing.sudo().write(vals)
                            else:
                                vals['state'] = pa_state
                                self.sudo().create(vals)
                except Exception as e:
                    _logger.debug(f"Error checking attendance preapprovals: {e}")

            # 3. Check Employee Service Requests for Manager's Subordinates
            if 'employee.service.request' in self.env:
                try:
                    subs = self.env['hr.employee'].sudo().search([
                        '|', ('parent_id', '=', mgr_emp.id), ('coach_id', '=', mgr_emp.id)
                    ])
                    if subs:
                        sr_requests = self.env['employee.service.request'].sudo().search([
                            ('employee_id', 'in', subs.ids),
                        ])
                        for sr in sr_requests:
                            existing = self.sudo().search([
                                ('res_model', '=', 'employee.service.request'),
                                ('res_id', '=', sr.id),
                                ('delegation_id', '=', deleg.id),
                            ], limit=1)

                            sr_state = 'approved' if sr.state in ['approved', 'done', 'hr_approved'] else ('rejected' if sr.state in ['rejected', 'cancelled'] else 'requested')

                            vals = {
                                'name': sr.name or f"Service Request #{sr.id}",
                                'res_model': 'employee.service.request',
                                'res_id': sr.id,
                                'delegation_id': deleg.id,
                                'delegating_manager_id': mgr_emp.id,
                                'delegate_id': current_emp.id if current_emp else False,
                                'requester_id': sr.employee_id.id,
                                'request_date': getattr(sr, 'request_date', False) or today,
                                'request_type': getattr(sr.service_type_id, 'name', 'Service Request') if hasattr(sr, 'service_type_id') else 'Service Request',
                                'summary': sr.name or 'Employee Service Request',
                                'notes': getattr(sr, 'reason', '') or getattr(sr, 'description', '') or '',
                                'activity_id': False,
                            }

                            if existing:
                                if existing.state != sr_state:
                                    vals['state'] = sr_state
                                existing.sudo().write(vals)
                            else:
                                vals['state'] = sr_state
                                self.sudo().create(vals)
                except Exception as e:
                    _logger.debug(f"Error checking service requests: {e}")

    @api.model
    def action_open_delegated_approvals_hub(self):
        """ Server action executed when clicking 'Delegated Approvals' menu """
        self._refresh_delegated_approvals()
        return {
            'name': _("Delegated Approvals"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.delegated.approval',
            'view_mode': 'list,form',
            'target': 'current',
            'context': {'create': False, 'delete': False},
            'help': _("""
                <p class="o_view_nocontent_smiling_face">
                    No delegated approvals found!
                </p>
                <p>
                    When a manager delegates authority to you, pending and completed approval requests assigned to them will appear here.
                </p>
            """),

        }

    def action_approve_delegated(self):
        """ Executes approval on the underlying record with complete delegation audit trail. """
        self.ensure_one()
        target_model = self.res_model
        target_id = self.res_id
        target_rec = self.env[target_model].sudo().browse(target_id)
        if not target_rec.exists():
            raise UserError(_("The underlying record no longer exists."))

        delegate_name = self.env.user.name
        manager_emp = self.delegating_manager_id
        manager_user = manager_emp.user_id or self.env.ref('base.user_admin')
        del_name = self.delegation_id.name or _("Active Delegation")
        req_name = self.name or f"{target_model} #{target_id}"

        # Execute as delegating manager user context
        rec_as_mgr = target_rec.with_user(manager_user)

        approved = False
        for method_name in ['action_approve', 'action_manager_approve', 'button_approve', 'action_validate']:
            if hasattr(rec_as_mgr, method_name):
                try:
                    method = getattr(rec_as_mgr, method_name)
                    method()
                    approved = True
                    break
                except Exception as e:
                    _logger.warning(f"Error invoking {method_name} as manager on {target_model} {target_id}: {e}")

        if not approved and hasattr(target_rec, 'state'):
            target_rec.sudo().write({'state': 'approved'})

        if hasattr(target_rec, 'approved_by'):
            target_rec.sudo().write({'approved_by': self.env.uid})

        # Post audit chatter note
        if hasattr(target_rec, 'message_post'):
            target_rec.sudo().message_post(
                body=_(
                    "<p><strong>Approved via Delegated Approvals Hub</strong><br/>"
                    "Approved by <strong>%(delegate)s</strong> on behalf of Manager <strong>%(manager)s</strong> "
                    "under Delegation Reference <strong>%(delegation)s</strong>.</p>"
                ) % {
                    'delegate': delegate_name,
                    'manager': manager_emp.name,
                    'delegation': del_name,
                }
            )

        # Complete activity if present
        if self.activity_id and self.activity_id.exists():
            try:
                self.activity_id.sudo().action_feedback(
                    feedback=_("Approved via Delegation Hub by %s on behalf of %s.") % (delegate_name, manager_emp.name)
                )
            except Exception as e:
                _logger.warning(f"Error closing activity: {e}")

        # Update status in Delegated Approvals hub rather than deleting
        self.write({
            'state': 'approved',
            'action_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Request Approved"),
                'message': _("Successfully approved %s on behalf of %s.") % (req_name, manager_emp.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_reject_delegated(self):
        """ Executes rejection on the underlying record with audit trail. """
        self.ensure_one()
        target_model = self.res_model
        target_id = self.res_id
        target_rec = self.env[target_model].sudo().browse(target_id)
        if not target_rec.exists():
            raise UserError(_("The underlying record no longer exists."))

        delegate_name = self.env.user.name
        manager_emp = self.delegating_manager_id
        manager_user = manager_emp.user_id or self.env.ref('base.user_admin')
        del_name = self.delegation_id.name or _("Active Delegation")
        req_name = self.name or f"{target_model} #{target_id}"

        rec_as_mgr = target_rec.with_user(manager_user)

        rejected = False
        for method_name in ['action_reject', 'action_refuse', 'button_reject']:
            if hasattr(rec_as_mgr, method_name):
                try:
                    method = getattr(rec_as_mgr, method_name)
                    method()
                    rejected = True
                    break
                except Exception as e:
                    _logger.warning(f"Error invoking {method_name} as manager on {target_model} {target_id}: {e}")

        if not rejected and hasattr(target_rec, 'state'):
            target_rec.sudo().write({'state': 'rejected'})

        if hasattr(target_rec, 'message_post'):
            target_rec.sudo().message_post(
                body=_(
                    "<p><strong>Rejected via Delegated Approvals Hub</strong><br/>"
                    "Rejected by <strong>%(delegate)s</strong> on behalf of Manager <strong>%(manager)s</strong> "
                    "under Delegation Reference <strong>%(delegation)s</strong>.</p>"
                ) % {
                    'delegate': delegate_name,
                    'manager': manager_emp.name,
                    'delegation': del_name,
                }
            )

        if self.activity_id and self.activity_id.exists():
            try:
                self.activity_id.sudo().action_feedback(
                    feedback=_("Rejected via Delegation Hub by %s on behalf of %s.") % (delegate_name, manager_emp.name)
                )
            except Exception as e:
                _logger.warning(f"Error closing activity: {e}")

        # Update status in Delegated Approvals hub rather than deleting
        self.write({
            'state': 'rejected',
            'action_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Request Rejected"),
                'message': _("Request %s has been rejected on behalf of %s.") % (req_name, manager_emp.name),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }
