from odoo import models, fields, api
from odoo.exceptions import ValidationError
from psycopg2 import errors as pg_errors
import logging

_logger = logging.getLogger(__name__)


class OverTimeLeave(models.Model):
    _inherit = "leave.request"

    leave_reason = fields.Selection(selection_add=[('over_time', 'Over Time')])
    over_time = fields.Float(string="Eligible Over Time (Hours)", readonly=True, store=True)

    # -------------------------------
    # FETCH BUTTON
    # -------------------------------
    def action_fetch_overtime(self):
        for rec in self:
            # Preserve the base fetch behaviour (requester / accrued-leave
            # population); its stored procedures may not be installed here.
            try:
                with self.env.cr.savepoint():
                    super(OverTimeLeave, rec).action_fetch_leave()
            except pg_errors.UndefinedFunction:
                pass
            if rec.leave_reason == 'over_time':
                overtime_lines = self.env['over.time'].sudo().search([
                    ('employee_id', '=', rec.requester_name.id),
                    #('state', '=', 'approved'),
                    ('remaining_hours', '>', 0)
                ])

                total_hours = sum(overtime_lines.mapped('remaining_hours'))
                rec.over_time = total_hours
                _logger.warning("OT Employee %s ? %s Hours", rec.requester_name.id, total_hours)

        return True

    # -------------------------------
    # COMPUTE LEAVE INCLUDING OVERTIME
    # -------------------------------
    def n_compute_leave(self):
        # Parent model defines n_compute_leave() - delegate non-OT leave
        # reasons to it, then handle OT leaves here.
        non_ot = self.filtered(lambda r: r.leave_reason != 'over_time')
        if non_ot:
            super(OverTimeLeave, non_ot).n_compute_leave()
        for record in self:
            if record.leave_reason == 'over_time':
                try:
                    # Call stored procedure for overtime leave (savepoint so a
                    # missing function does not abort the whole transaction).
                    with self.env.cr.savepoint():
                        self.env.cr.execute('SELECT populate_computed_actual_leaves(%s)', (record.id,))
                except pg_errors.UndefinedFunction:
                    # Fallback if the stored procedure is unavailable: manual day
                    # count (including weekends), mirroring the parent's else branch.
                    if record.start_date and record.end_date:
                        record.computed_leave = (record.end_date - record.start_date).days + 1
                    else:
                        record.computed_leave = 0
        # The stored procedure writes computed_leave via raw SQL - refresh cache.
        self.invalidate_recordset(['computed_leave'])
        return True

    # -------------------------------
    # CONFIRM / NOTIFY
    # -------------------------------
    def notification(self):
        # OT leaves have no accrued/scheduled balance, so the parent's
        # annual-leave notification logic would reject them with a misleading
        # error. Validate + notify OT leaves here; delegate the rest.
        ot_records = self.filtered(lambda r: r.leave_reason == 'over_time')
        for rec in ot_records:
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

            # Notify the manager through the same channel used for regular leaves.
            rec.status = 'notification'
            employee = self.env['hr.employee'].search(
                [('name', '=', rec.requester_name.name)], limit=1)
            if employee:
                target = employee.alternate_parent or rec.manager_partner_id
                if target:
                    rec.mail_channel_msgs1(
                        target, rec.reference, rec.requester_name.name,
                        rec.operating_unit.name, rec.job_category)
            # Mirror the parent's generic notification branch.
            rec.copy_attachments_from_leave_request()

        non_ot = self - ot_records
        if non_ot:
            # Parent model defines notification() - delegate non-OT leaves to it.
            super(OverTimeLeave, non_ot).notification()
        return True
