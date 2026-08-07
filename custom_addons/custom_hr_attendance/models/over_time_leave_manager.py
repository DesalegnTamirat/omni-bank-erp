import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class OverTimeLeaveManager(models.Model):
    _inherit = "leave.request.manager"

    leave_reason = fields.Selection(
        selection_add=[('over_time', 'Over Time')]
    )

    over_time = fields.Float(
        string="Eligible Over Time (Hours)",
        readonly=True
    )

    # =========================================================
    # INTERNAL: GET EMPLOYEE FROM REQUESTER USER (FIXED)
    # =========================================================
    def _get_employee(self):
        self.ensure_one()

        if not self.requester_user_id:
            raise ValidationError("Requester user is not defined.")

        # ALWAYS normalize to recordset (SAFE FIX)
        user = self.env['res.users'].browse(self.requester_user_id)
        if not user.exists():
            raise ValidationError("Requester user does not exist.")

        if not user.employee_id:
            raise ValidationError("No employee is linked to the requester user.")

        return user.employee_id

    def fetch(self):
        print("fetch")

    # =========================================================
    # SHOW OT BALANCE
    # =========================================================
    @api.onchange('leave_reason', 'requester_user_id')
    def _onchange_fetch_ot_balance(self):
        for rec in self:
            rec.over_time = 0.0

            if rec.leave_reason != 'over_time' or not rec.requester_user_id:
                continue

            employee = rec.requester_user_id.employee_id
            if not employee:
                continue

            ot_lines = self.env['over.time'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['draft', 'partially_used']),
                ('remaining_hours', '>', 0),
            ])

            rec.over_time = sum(ot_lines.mapped('remaining_hours'))

    def confirm_leave(self):
        for rec in self:
            if rec.leave_reason != 'over_time':
                continue

            employee = rec._get_employee()
            # Convert days to hours (assuming 8h workday)
            required_hours = rec.computed_leave * 8

            # 1. Fetch available OT records
            ot_lines = self.env['over.time'].search([
                ('employee_id', '=', employee.id),
                ('remaining_hours', '>', 0)
            ], order='date asc')

            total_available = sum(ot_lines.mapped('remaining_hours'))

            # 2. Guard Clause: Check balance
            if total_available < (required_hours - 0.001):  # Small delta for float safety
                raise ValidationError(
                    f"Insufficient overtime balance. Available: {total_available} hrs"
                )

            # 3. Create Consumptions (Automation handles the rest)
            for ot in ot_lines:
                if required_hours <= 0:
                    break

                take = min(required_hours, ot.remaining_hours)
                if take > 0:
                    self.env['over.time.consumption'].create({
                        'over_time_id': ot.id,
                        'leave_request_id': rec.id,
                        'hours': take,
                    })
                    required_hours -= take

        return super().confirm_leave()

    def reject(self):
        for rec in self:
            if rec.leave_reason == 'over_time':
                # Simply deleting these records triggers the 'over.time' 
                # recompute, restoring 'remaining_hours' automatically.
                consumptions = self.env['over.time.consumption'].search([
                    ('leave_request_id', '=', rec.id)
                ])
                if consumptions:
                    consumptions.unlink()

            rec.state = "reject"
            rec._notify_rejection()

    # =========================================================
    # NOTIFICATION
    # =========================================================
    def _notify_rejection(self):
        for rec in self:
            employee = rec._get_employee()
            partner = employee.user_id.partner_id
            if not partner:
                continue

            channel = self.env['discuss.channel'].channel_get([partner.id])
            channel_id = self.env['discuss.channel'].browse(channel["id"])

            message = f"""
                <b>Leave Request Rejected</b><br/>
                Reference: {rec.reference}<br/>
                Employee: {employee.name}<br/>
                Operating Unit: {rec.operating_unit}<br/>
                Status: Rejected<br/><br/>
                Sorry, your leave request has been rejected.
            """

            channel_id.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
