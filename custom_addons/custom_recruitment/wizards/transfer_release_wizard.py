# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TransferRequestReleaseWizard(models.TransientModel):
    _name = "transfer.request.release.wizard"
    _description = "Employee Transfer Request Release Wizard"

    transfer_request_id = fields.Many2one(
        "employee.transfer.request",
        string="Transfer Request",
        required=True,
    )
    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True)
    current_position = fields.Char(string="Current Position", readonly=True)
    current_work_unit = fields.Char(string="Current Work Unit / Location", readonly=True)
    target_work_unit = fields.Char(string="Target Placement Unit", readonly=True)
    target_position = fields.Char(string="Target Position", readonly=True)
    target_grade = fields.Char(string="Target Job Grade", readonly=True)

    releasing_manager_id = fields.Many2one(
        "hr.employee",
        string="Releasing Coach / Manager",
        required=True,
    )
    release_date = fields.Date(
        string="Release Date",
        required=True,
        default=fields.Date.context_today,
    )
    handover_status = fields.Selection([
        ("completed", "Handover Completed"),
        ("pending", "Pending Handover"),
    ], string="Handover Status", default="completed", required=True)
    release_remarks = fields.Text(string="Release & Clearance Remarks")

    def action_confirm_release(self):
        self.ensure_one()
        req = self.transfer_request_id
        if not req:
            raise UserError(_("No transfer request found to release."))
        if hasattr(req, '_check_current_user_is_releasing_manager'):
            req._check_current_user_is_releasing_manager()
        req = req.sudo()

        if req.state != "pending_release":
            raise UserError(_("Transfer request is not in 'Pending Manager Release' state."))

        # 1. Update release and handover fields on the transfer request
        req.write({
            "release_date": self.release_date,
            "handover_status": self.handover_status,
            "release_remarks": self.release_remarks,
            "releasing_manager_id": self.releasing_manager_id.id if self.releasing_manager_id else req.releasing_manager_id.id,
        })

        # 2. Finalize transfer: update employee master data, position, operating unit, contracts & transfer history
        req.action_complete_transfer()

        # 3. Close open activities for release on this transfer request
        activities = self.env["mail.activity"].sudo().search([
            ("res_model", "=", "employee.transfer.request"),
            ("res_id", "=", req.id),
        ])
        for act in activities:
            try:
                act.action_done()
            except Exception:
                pass

        # 4. Post release completion confirmation to chatter
        handover_label = dict(self._fields["handover_status"].selection).get(self.handover_status, self.handover_status)
        target_unit = req.target_operating_unit_id.name or req.requested_operating_unit_id.name or "New Work Unit"
        mgr_name = self.releasing_manager_id.name if self.releasing_manager_id else self.env.user.name

        req.message_post(
            body=_(
                "<p><b>✅ Transfer Release Form Completed</b></p>"
                "<p>Employee released by <b>%s</b> effective <b>%s</b>.</p>"
                "<p><b>Handover Status:</b> %s<br/>"
                "<b>Remarks:</b> %s</p>"
                "<p>Employee master data and operating unit successfully transferred to <b>%s</b>.</p>"
            ) % (
                mgr_name,
                self.release_date,
                handover_label,
                self.release_remarks or "None",
                target_unit,
            )
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Release Completed"),
                "message": _("Employee %s has been officially released and transferred.") % (self.employee_id.name if self.employee_id else ""),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }
