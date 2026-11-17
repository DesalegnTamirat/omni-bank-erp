# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class HrDelegatedApproval(models.Model):
    _inherit = "hr.delegated.approval"

    @api.model
    def _refresh_delegated_approvals(self, delegation_id=None):
        """Extend standard delegated approvals scanning to include pending HR resignations,
        manager handovers / release dates, and clearance tasks.
        """
        super()._refresh_delegated_approvals(delegation_id=delegation_id)

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

        Resignation = self.env['hr.resignation'].sudo()
        Clearance = self.env['hr.resignation.clearance'].sudo()

        for deleg in active_dels:
            mgr_emp = deleg.employee_id
            mgr_user = mgr_emp.user_id

            # -------------------------------------------------------------
            # 1. Resignations pending Manager Handover / Release Date
            # -------------------------------------------------------------
            try:
                mgr_resignations = Resignation.search([
                    '|',
                    ('coach_id', '=', mgr_emp.id),
                    ('employee_id.parent_id', '=', mgr_emp.id),
                    ('state', 'in', ['approved', 'handover_completed']),
                ])
                for res in mgr_resignations:
                    existing = self.sudo().search([
                        ('res_model', '=', 'hr.resignation'),
                        ('res_id', '=', res.id),
                        ('delegation_id', '=', deleg.id),
                    ], limit=1)

                    if res.state == 'approved':
                        req_type = _("Resignation Handover")
                        summary = _("Pending Handover Notes for %s (%s)") % (res.employee_id.name, res.name)
                    else:
                        req_type = _("Resignation Release Date")
                        summary = _("Pending Release Date for %s (%s)") % (res.employee_id.name, res.name)

                    vals = {
                        'name': f"{res.name} - {res.employee_id.name}",
                        'res_model': 'hr.resignation',
                        'res_id': res.id,
                        'delegation_id': deleg.id,
                        'delegating_manager_id': mgr_emp.id,
                        'delegate_id': current_emp.id if current_emp else False,
                        'requester_id': res.employee_id.id,
                        'request_date': res.application_date or today,
                        'request_type': req_type,
                        'summary': summary,
                        'notes': res.reason or '',
                        'activity_id': False,
                        'state': 'requested',
                    }

                    if existing:
                        existing.sudo().write(vals)
                    else:
                        self.sudo().create(vals)
            except Exception as e:
                _logger.debug("Error checking manager resignations for delegation %s: %s", deleg.id, e)

            # -------------------------------------------------------------
            # 2. Resignations pending HR Manager Approval
            # -------------------------------------------------------------
            is_hr_mgr = False
            if mgr_user:
                hr_mgr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
                if hr_mgr_group and mgr_user in hr_mgr_group.user_ids:
                    is_hr_mgr = True

            if is_hr_mgr:
                try:
                    hr_pending_resignations = Resignation.search([
                        ('state', '=', 'submitted'),
                    ])
                    for res in hr_pending_resignations:
                        existing = self.sudo().search([
                            ('res_model', '=', 'hr.resignation'),
                            ('res_id', '=', res.id),
                            ('delegation_id', '=', deleg.id),
                        ], limit=1)

                        vals = {
                            'name': f"{res.name} - {res.employee_id.name} (HR Approval)",
                            'res_model': 'hr.resignation',
                            'res_id': res.id,
                            'delegation_id': deleg.id,
                            'delegating_manager_id': mgr_emp.id,
                            'delegate_id': current_emp.id if current_emp else False,
                            'requester_id': res.employee_id.id,
                            'request_date': res.application_date or today,
                            'request_type': _("Resignation HR Approval"),
                            'summary': _("Pending HR Approval for %s (%s)") % (res.employee_id.name, res.name),
                            'notes': res.reason or '',
                            'activity_id': False,
                            'state': 'requested',
                        }

                        if existing:
                            existing.sudo().write(vals)
                        else:
                            self.sudo().create(vals)
                except Exception as e:
                    _logger.debug("Error checking HR resignations for delegation %s: %s", deleg.id, e)

            # -------------------------------------------------------------
            # 3. Clearance Tasks assigned to delegating officer
            # -------------------------------------------------------------
            if mgr_user:
                try:
                    pending_clearances = Clearance.search([
                        ('responsible_user', '=', mgr_user.id),
                        ('state', '=', 'pending'),
                    ])
                    for cl in pending_clearances:
                        existing = self.sudo().search([
                            ('res_model', '=', 'hr.resignation.clearance'),
                            ('res_id', cl.id),
                            ('delegation_id', '=', deleg.id),
                        ], limit=1)

                        vals = {
                            'name': cl.display_name or f"Clearance #{cl.id}",
                            'res_model': 'hr.resignation.clearance',
                            'res_id': cl.id,
                            'delegation_id': deleg.id,
                            'delegating_manager_id': mgr_emp.id,
                            'delegate_id': current_emp.id if current_emp else False,
                            'requester_id': cl.employee_id.id if cl.employee_id else False,
                            'request_date': cl.resignation_id.release_date or cl.sla_deadline or today,
                            'request_type': _("Separation Clearance Task"),
                            'summary': _("Clearance for %s (%s)") % (
                                cl.employee_id.sudo().name or '',
                                cl.work_unit_id.name or '',
                            ),
                            'notes': cl.notes or '',
                            'activity_id': False,
                            'state': 'requested',
                        }

                        if existing:
                            existing.sudo().write(vals)
                        else:
                            self.sudo().create(vals)
                except Exception as e:
                    _logger.debug("Error checking clearance tasks for delegation %s: %s", deleg.id, e)


class HrEmployeeDelegation(models.Model):
    _inherit = "hr.employee.delegation"

    def _compute_delegated_approval_count(self):
        super()._compute_delegated_approval_count()
        today = fields.Date.today()
        current_uid = self.env.uid

        for rec in self:
            if rec.state == 'submitted' and rec.start_date and rec.end_date and rec.start_date <= today <= rec.end_date:
                if rec.delegate_id and rec.delegate_id.user_id.id == current_uid:
                    mgr_user = rec.employee_id.user_id
                    extra_count = 0

                    # 1. Direct reports pending handover / release date
                    extra_count += self.env['hr.resignation'].sudo().search_count([
                        ('coach_id', '=', rec.employee_id.id),
                        ('state', 'in', ['approved', 'handover_completed']),
                    ])

                    # 2. If delegator is HR manager: pending submitted resignations
                    if mgr_user:
                        hr_mgr_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
                        if hr_mgr_group and mgr_user in hr_mgr_group.user_ids:
                            extra_count += self.env['hr.resignation'].sudo().search_count([
                                ('state', '=', 'submitted'),
                            ])

                        # 3. Clearance tasks
                        extra_count += self.env['hr.resignation.clearance'].sudo().search_count([
                            ('responsible_user', '=', mgr_user.id),
                            ('state', '=', 'pending'),
                        ])

                    rec.delegated_approval_count = (rec.delegated_approval_count or 0) + extra_count
