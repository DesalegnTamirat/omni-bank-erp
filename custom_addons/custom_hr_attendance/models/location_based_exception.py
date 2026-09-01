from odoo import models, fields, api
from odoo.exceptions import ValidationError


class LocationBasedException(models.Model):
    _name = "location.based.exception"
    _rec_name = "schedule_name"
    _description = "Location Based Exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(string="Active", default=True, index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled')
    ], string="Status", default='draft', tracking=True, index=True)
    applied_by_id = fields.Many2one('res.users', string="Applied By", readonly=True, copy=False)
    applied_date = fields.Datetime(string="Applied Date", readonly=True, copy=False)

    def action_apply(self):
        for rec in self:
            if not rec.shift_id:
                raise ValidationError("Please select a Shift Template before applying this exception.")
            if not rec.operating_unit_ids and not rec.operating_unit:
                raise ValidationError("A Location-Based Exception must specify at least one Location / Operating Unit.")
            rec.write({
                'state': 'active',
                'active': True,
                'applied_by_id': self.env.user.id,
                'applied_date': fields.Datetime.now()
            })
            rec.message_post(body=f"Shift Exception <b>{rec.shift_id.name}</b> applied and activated by {self.env.user.name}.")

    def action_cancel(self):
        for rec in self:
            rec.write({
                'state': 'cancelled',
                'active': False
            })
            rec.message_post(body=f"Shift Exception cancelled by {self.env.user.name}.")

    def action_draft(self):
        for rec in self:
            rec.write({
                'state': 'draft',
                'active': True
            })

    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
        help="Date when this location-based shift exception starts taking effect."
    )
    end_date = fields.Date(
        string="End Date",
        required=False,
        index=True,
        tracking=True,
        help="Optional end date. If left blank, exception continues indefinitely until edited. If set, reverts to default after this date."
    )

    @api.constrains('start_date', 'end_date')
    def _check_date_boundaries(self):
        for rec in self:
            if rec.end_date and rec.start_date and rec.end_date < rec.start_date:
                raise ValidationError(("End Date (%s) cannot be earlier than Start Date (%s).") % (rec.end_date, rec.start_date))

    @api.constrains('operating_unit_ids', 'operating_unit', 'active', 'state')
    def _check_operating_unit_required(self):
        for rec in self:
            if rec.state == 'active' and not rec.operating_unit_ids and not rec.operating_unit:
                raise ValidationError("A Location-Based Exception must specify at least one Location / Operating Unit.")

    schedule_name = fields.Char(
        string="Schedule Name",
        compute="_compute_schedule_name",
        store=True,
        readonly=True
    )

    district_id = fields.Many2one(
        'operating.unit',
        string="Filter by District",
        domain="[('work_unit_type', 'in', ['district_office', 'regional_office'])]",
        help="Optional administrative filter to narrow down branch selection by District Office."
    )

    operating_unit_ids = fields.Many2many(
        'operating.unit',
        'rel_location_exception_operating_unit',
        'location_exception_id',
        'operating_unit_id',
        string="Locations / Operating Units",
        index=True,
        help="Select one or multiple operating units / branch locations for this shift exception."
    )

    operating_unit = fields.Many2one(
        'operating.unit',
        string="Primary Location",
        compute="_compute_operating_unit",
        store=True,
        index=True
    )

    @api.depends('operating_unit_ids')
    def _compute_operating_unit(self):
        for rec in self:
            rec.operating_unit = rec.operating_unit_ids[0] if rec.operating_unit_ids else False

    allowed_shift_ids = fields.Many2many(
        'job.shift',
        compute='_compute_allowed_shift_ids',
        string="Allowed Shifts"
    )

    shift_id = fields.Many2one('job.shift', string="Shift Template", required=True, help="Link to an applicable shift definition")

    @api.depends('operating_unit_ids', 'operating_unit', 'district_id')
    def _compute_allowed_shift_ids(self):
        for rec in self:
            allowed_ids = set()
            targets = rec.operating_unit_ids or (rec.district_id if rec.district_id else self.env['operating.unit'].browse())
            if targets:
                for target_ou in targets:
                    allowed = self.env.user.sudo()._get_allowed_job_shift_ids(target_operating_unit=target_ou)
                    allowed_ids.update(allowed)
            else:
                allowed_ids.update(self.env.user.sudo()._get_allowed_job_shift_ids(target_operating_unit=False))
            rec.allowed_shift_ids = [(6, 0, list(allowed_ids))]

    @api.onchange('operating_unit_ids', 'district_id')
    def _onchange_locations_allowed_shifts(self):
        allowed_ids = set()
        targets = self.operating_unit_ids or (self.district_id if self.district_id else self.env['operating.unit'].browse())
        if targets:
            for target_ou in targets:
                allowed = self.env.user.sudo()._get_allowed_job_shift_ids(target_operating_unit=target_ou)
                allowed_ids.update(allowed)
        else:
            allowed_ids.update(self.env.user.sudo()._get_allowed_job_shift_ids(target_operating_unit=False))
        self.allowed_shift_ids = [(6, 0, list(allowed_ids))]
        if self.shift_id and self.shift_id.id not in allowed_ids:
            self.shift_id = False
        return {'domain': {'shift_id': [('id', 'in', list(allowed_ids))]}}

    start_time = fields.Float(string="Start Time", compute="_compute_shift_details", store=True, readonly=True)
    end_time = fields.Float(string="End Time", compute="_compute_shift_details", store=True, readonly=True)
    duration = fields.Float(string="Net Worked Duration (Hours)", compute="_compute_shift_details", store=True, readonly=True)
    has_lunch_break = fields.Boolean(string="Includes Lunch Break", compute="_compute_shift_details", store=True, readonly=True)
    morning_window = fields.Char(string="Morning Shift Window", compute="_compute_shift_details", store=True, readonly=True)
    lunch_window = fields.Char(string="Lunch Break Window", compute="_compute_shift_details", store=True, readonly=True)
    afternoon_window = fields.Char(string="Afternoon Shift Window", compute="_compute_shift_details", store=True, readonly=True)
    time_range = fields.Char(string="Time Range", compute="_compute_shift_details", store=True, readonly=True)

    @api.depends('shift_id', 'shift_id.start_time', 'shift_id.end_time', 'shift_id.has_lunch_break', 'shift_id.lunch_start_time', 'shift_id.lunch_duration', 'shift_id.is_night_shift')
    def _compute_shift_details(self):
        def _format_decimal_time(float_val):
            if float_val is None or float_val is False:
                return "00:00"
            val = float(float_val) % 24.0
            h = int(val)
            m = int(round((val - h) * 60))
            if m >= 60:
                h = (h + 1) % 24
                m = 0
            return f"{h:02d}:{m:02d}"

        for rec in self:
            s = rec.shift_id
            if not s:
                rec.start_time = 0.0
                rec.end_time = 0.0
                rec.duration = 0.0
                rec.has_lunch_break = False
                rec.morning_window = "-"
                rec.lunch_window = "No Lunch Break"
                rec.afternoon_window = "-"
                rec.time_range = "-"
                continue

            rec.start_time = s.start_time
            rec.end_time = s.end_time
            rec.has_lunch_break = s.has_lunch_break

            gross = s.end_time - s.start_time
            if s.is_night_shift or gross < 0:
                gross += 24.0

            lunch_deduction = s.lunch_duration if s.has_lunch_break else 0.0
            rec.duration = max(0.0, round(gross - lunch_deduction, 2))

            start_str = _format_decimal_time(s.start_time)
            end_str = _format_decimal_time(s.end_time)

            if s.has_lunch_break and s.lunch_start_time:
                l_start_str = _format_decimal_time(s.lunch_start_time)
                l_end = s.lunch_start_time + (s.lunch_duration or 1.0)
                l_end_str = _format_decimal_time(l_end)

                rec.morning_window = f"{start_str} - {l_start_str}"
                rec.lunch_window = f"{l_start_str} - {l_end_str} ({s.lunch_duration or 1.0:g}h break)"
                rec.afternoon_window = f"{l_end_str} - {end_str}"
                rec.time_range = f"{start_str} - {end_str} (Lunch: {l_start_str} - {l_end_str})"
            else:
                rec.morning_window = f"{start_str} - {end_str}"
                rec.lunch_window = "No Lunch Break"
                rec.afternoon_window = "N/A"
                rec.time_range = f"{start_str} - {end_str}"

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    @api.depends('operating_unit', 'operating_unit_ids')
    def _compute_schedule_name(self):
        for rec in self:
            if rec.operating_unit_ids:
                names = ", ".join(rec.operating_unit_ids.mapped('name'))
                rec.schedule_name = f"{names} / Location Based"
            elif rec.operating_unit:
                rec.schedule_name = f"{rec.operating_unit.name} / Location Based"
            else:
                rec.schedule_name = "Location Based Exception"




    @api.constrains('start_time', 'end_time', 'shift_id')
    def _check_time_validity(self):
        for rec in self:
            # Skip if no shift template is assigned or if start/end times are uninitialized (00:00)
            if not rec.shift_id or (rec.start_time == 0.0 and rec.end_time == 0.0):
                continue

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
            # if duration > 4:
            #     raise ValidationError("Maximum allowed window is 4 hours.")

    @api.constrains('shift_id', 'operating_unit')
    def _check_shift_applicability(self):
        for rec in self:
            if rec.shift_id:
                manager_emp = self.env.user.employee_id or (self.env.user.employee_ids[0] if self.env.user.employee_ids else False)
                manager_ou = manager_emp.default_operating_unit_id if manager_emp else False
                manager_dept = manager_emp.department_id if manager_emp else False
                if not rec.shift_id.is_applicable_for(
                    operating_unit=rec.operating_unit,
                    department=None,
                    assigner_operating_unit=manager_ou,
                    assigner_department=manager_dept
                ):
                    from odoo import _
                    raise ValidationError(
                        _(
                            "The selected shift '%s' is not configured to apply to location '%s' "
                            "nor to your operating unit (%s) or department (%s)."
                        ) % (
                            rec.shift_id.name,
                            rec.operating_unit.name if rec.operating_unit else "N/A",
                            manager_ou.name if manager_ou else "N/A",
                            manager_dept.name if manager_dept else "N/A"
                        )
                    )

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
