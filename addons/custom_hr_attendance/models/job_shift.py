from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import time


class JobShift(models.Model):
    _name = "job.shift"
    _description = "Job Shift"
    _order = "start_time"

    active = fields.Boolean(string="Active", default=True, index=True)
    name = fields.Char(string="Shift Name", required=True)
    code = fields.Char(string="Code", required=True)

    def unlink(self):
        """Soft delete: Archive records instead of removing from DB"""
        for rec in self:
            rec.write({"active": False})
        return True

    start_time = fields.Float(
        string="Start Time",
        required=True,
        help="Start time in 24h format (e.g. 7.0 = 07:00)",
    )

    end_time = fields.Float(
        string="End Time",
        required=True,
        help="End time in 24h format (e.g. 23.0 = 23:00)",
    )

    is_night_shift = fields.Boolean(
        string="Night Shift", help="Enable if the shift crosses midnight"
    )

    time_range = fields.Char(
        string="Time Range", compute="_compute_time_range", store=True
    )

    # -------------------------
    # COMPUTE
    # -------------------------
    @staticmethod
    def _float_to_time(float_time):
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))

        if minutes >= 60:
            hours += 1
            minutes -= 60
        if hours >= 24:
            hours = 0

        return time(hours, minutes)

    @api.depends("start_time", "end_time", "is_night_shift")
    def _compute_time_range(self):
        for record in self:

            if record.start_time < 0 or record.end_time < 0:
                raise ValidationError("Time values cannot be negative.")

            if record.start_time >= 24 or record.end_time > 24:
                raise ValidationError("Time must be within 24-hour range.")

            start = self._float_to_time(record.start_time)
            end = self._float_to_time(record.end_time)

            record.start_time = start.hour + round(start.minute / 60.0, 2)
            record.end_time = end.hour + round(end.minute / 60.0, 2)

            if record.is_night_shift:
                record.time_range = (
                    f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')} (Next Day)"
                )
            else:
                record.time_range = (
                    f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
                )

    # -------------------------
    # CONSTRAINTS
    # -------------------------
    @api.constrains("start_time", "end_time", "is_night_shift")
    def _check_time_validity(self):
        for record in self:
            if not record.is_night_shift and record.end_time <= record.start_time:
                raise ValidationError(
                    "End time must be after start time unless it is a night shift."
                )
