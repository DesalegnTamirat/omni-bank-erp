from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class OverTimeLeave(models.Model):
    _inherit = "leave.request"

    leave_reason = fields.Selection(selection_add=[('over_time', 'Over Time')])
    over_time = fields.Float(string="Eligible Over Time (Hours)", readonly=True, store=True)

    # -------------------------------
    # FETCH BUTTON
    # -------------------------------
    def fetch(self):
        res = super().fetch()

        for rec in self:
            if rec.leave_reason == 'over_time':
                overtime_lines = self.env['over.time'].sudo().search([
                    ('employee_id', '=', rec.requester_name.id),
                    #('state', '=', 'approved'),
                    ('remaining_hours', '>', 0)
                ])

                total_hours = sum(overtime_lines.mapped('remaining_hours'))
                rec.over_time = total_hours
                _logger.warning("OT Employee %s ? %s Hours", rec.requester_name.id, total_hours)

        return res

    # -------------------------------
    # COMPUTE LEAVE INCLUDING OVERTIME
    # -------------------------------
    def n_compute_leave(self):
        res = super().n_compute_leave()
        for record in self:
            print("Fetching Requester Details")
            print("User ID ************************ ", self.env.user.id)
            print("Request ID ************************ ", record.id)
    
            if record.leave_reason == 'over_time':
                                # Call stored procedure for overtime leave
                self.env.cr.execute('SELECT populate_computed_actual_leaves(%s)', (record.id,))
            return res
                    
               

    # -------------------------------
    # CONFIRM / NOTIFY
    # -------------------------------
    def notification(self):
        for rec in self:
            if rec.leave_reason == 'over_time':
                # Minimum overtime = 4 hours (0.5 day)
                if rec.over_time < 4:
                    raise ValidationError("Minimum overtime is 4 hours (0.5 day).")

                # Convert hours to days
                ot_days = rec.over_time / 8

                # Requested leave must NOT exceed accrued OT
                if round(rec.computed_leave, 2) > round(ot_days, 2):
                    raise ValidationError(
                        "Your requested leave (%.2f days) exceeds your accrued overtime (%.2f days)."
                        % (rec.computed_leave, ot_days)
                    )
        return super().notification()

