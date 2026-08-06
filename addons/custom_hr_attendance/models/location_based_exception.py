from odoo import models, fields, api
from odoo.exceptions import ValidationError


class LocationBasedException(models.Model):
    _name = "location.based.exception"
    _rec_name = "schedule_name"
    _description = "Location Based Exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(string="Active", default=True, index=True)
    schedule_name = fields.Char(
        string="Schedule Name",
        compute="_compute_schedule_name",
        store=True,
        readonly=True
    )

    start_time = fields.Float(
        string="Start Time",
        required=True,
        help="Enter time as decimal hours (e.g., 8.5 = 8:30, 8.75 = 8:45)"
    )

    end_time = fields.Float(
        string="End Time",
        required=True,
        help="Enter time as decimal hours (e.g., 17.25 = 5:15, 17.5 = 5:30)"
    )

    operating_unit = fields.Many2one('operating.unit', string="Location", index=True)

    duration = fields.Float(string="Duration (Hours)", compute='_compute_duration', store=True)
    time_range = fields.Char(string="Time Range", compute='_compute_time_range', store=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.depends('operating_unit.name')
    def _compute_schedule_name(self):
        for rec in self:
            rec.schedule_name = f"{rec.operating_unit.name} / Location Based" \
                if rec.operating_unit  else ""

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            rec.duration = round(rec.end_time - rec.start_time, 2) \
                if rec.start_time is not None and rec.end_time is not None else 0.0

    @api.depends('start_time', 'end_time')
    def _compute_time_range(self):
        for rec in self:
            if rec.start_time is not None and rec.end_time is not None:

                start_h = int(rec.start_time)
                start_m = round((rec.start_time - start_h) * 60)
                end_h = int(rec.end_time)
                end_m = round((rec.end_time - end_h) * 60)

                # Handle minute overflow
                if start_m >= 60:
                    start_h += start_m // 60
                    start_m %= 60
                if end_m >= 60:
                    end_h += end_m // 60
                    end_m %= 60

                rec.time_range = f"{start_h:02d}:{start_m:02d} - {end_h:02d}:{end_m:02d}"
            else:
                rec.time_range = ""


    @api.constrains('start_time', 'end_time')
    def _check_time_validity(self):
        for rec in self:

            for time_field, label in [(rec.start_time, "Start"), (rec.end_time, "End")]:
                if time_field is not None:
                    # Check time is within 24-hour range
                    if rec.start_time >= 24 or rec.end_time >= 24:
                        raise ValidationError("Time values must be less than 24 hours")
                    if rec.start_time < 0 or rec.end_time < 0:
                        raise ValidationError("Time values cannot be negative")
                    # Validate minutes
                    minutes = (time_field - int(time_field)) * 60
                    if not (0 <= round(minutes) < 60):
                        raise ValidationError(f"{label} time minutes must be between 0 and 59")

            # Validate time order and duration
            if rec.end_time <= rec.start_time:
                start_str = f"{int(rec.start_time):02d}:{round((rec.start_time - int(rec.start_time)) * 60):02d}"
                end_str = f"{int(rec.end_time):02d}:{round((rec.end_time - int(rec.end_time)) * 60):02d}"
                raise ValidationError(f"End time ({end_str}) must be after start time ({start_str})")

            duration = rec.end_time - rec.start_time
            if duration < 0.5:
                raise ValidationError("Shift duration must be at least 30 minutes")
            if duration > 4:
                raise ValidationError("Maximum allowed window is 4 hours.")

    @api.constrains('start_time', 'end_time', 'operating_unit')
    def _check_duplicate_time_range(self):
        for rec in self:
            if rec.operating_unit:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('operating_unit', '=', rec.operating_unit.id),
                    ('start_time', '=', rec.start_time),
                    ('end_time', '=', rec.end_time)
                ], limit=1)
                if duplicate:
                    start_str = f"{int(rec.start_time):02d}:{round((rec.start_time - int(rec.start_time)) * 60):02d}"
                    end_str = f"{int(rec.end_time):02d}:{round((rec.end_time - int(rec.end_time)) * 60):02d}"
                    raise ValidationError(
                        f"The location '{rec.operating_unit.name}' already has a schedule "
                        f"from {start_str} to {end_str}."
                    )
