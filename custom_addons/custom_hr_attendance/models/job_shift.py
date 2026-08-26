from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import time


class JobShift(models.Model):
    _name = "job.shift"
    _description = "Job Shift"
    _order = "start_time"

    active = fields.Boolean(string="Active", default=True, index=True)
    name = fields.Char(string="Shift Name", required=True)
    code = fields.Char(string="Code", required=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can create new job shift schedules."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can modify job shift schedules."))
        return super().write(vals)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager') and not self.env.is_superuser():
            raise UserError(_("Only Attendance Administrators can delete job shift schedules."))
        for rec in self:
            rec.write({'active': False})
        return True

    start_time = fields.Float(
        string="Start Time",
        required=True,
        help="Start time in 24h format (e.g. 7.0 = 07:00)"
    )

    end_time = fields.Float(
        string="End Time",
        required=True,
        help="End time in 24h format (e.g. 23.0 = 23:00)"
    )

    is_night_shift = fields.Boolean(
        string="Night Shift",
        help="Enable if the shift crosses midnight"
    )

    time_range = fields.Char(
        string="Time Range",
        compute="_compute_time_range",
        store=True
    )

    # -------------------------
    # LUNCH BREAK CONFIGURATION
    # -------------------------
    has_lunch_break = fields.Boolean(
        string="Includes Lunch Break",
        default=False,
        help="Check if this shift includes a shift-specific lunch break."
    )
    lunch_start_time = fields.Float(
        string="Lunch Start Time",
        help="Lunch start time in 24h format (e.g. 12.0 = 12:00)"
    )
    lunch_duration = fields.Float(
        string="Lunch Duration (Hours)",
        default=1.0,
        help="Lunch break duration in hours (e.g. 1.0 = 1 hour)"
    )

    # -------------------------
    # APPLICABILITY SCOPE
    # -------------------------
    applies_to_branches = fields.Boolean(
        string="Applies to All Branches / Districts",
        default=False,
        help="If enabled, this shift is applicable to all branch/district work units automatically."
    )
    operating_unit_ids = fields.Many2many(
        'operating.unit',
        'job_shift_operating_unit_rel',
        'shift_id',
        'operating_unit_id',
        string="Applicable Operating Units"
    )
    department_ids = fields.Many2many(
        'hr.department',
        'job_shift_department_rel',
        'shift_id',
        'department_id',
        string="Applicable Departments"
    )

    allowed_operating_unit_ids = fields.Many2many(
        'operating.unit',
        compute='_compute_allowed_operating_unit_ids',
        string="Allowed Operating Units Domain"
    )

    @api.depends('department_ids')
    def _compute_allowed_operating_unit_ids(self):
        for record in self:
            if not record.department_ids:
                record.allowed_operating_unit_ids = self.env['operating.unit'].browse()
            else:
                ous = self.env['operating.unit'].sudo().search([
                    '|',
                    ('department', 'in', record.department_ids.ids),
                    ('id', 'in', self.env['hr.department'].sudo().search([('id', 'in', record.department_ids.ids)]).mapped('operating_unit_id').ids)
                ])
                record.allowed_operating_unit_ids = ous

    @api.onchange('department_ids')
    def _onchange_department_ids(self):
        if not self.department_ids:
            self.operating_unit_ids = [(5, 0, 0)]
            return {'domain': {'operating_unit_ids': [('id', '=', False)]}}
        
        ous = self.env['operating.unit'].sudo().search([
            '|',
            ('department', 'in', self.department_ids.ids),
            ('id', 'in', self.env['hr.department'].sudo().search([('id', 'in', self.department_ids.ids)]).mapped('operating_unit_id').ids)
        ])
        
        if self.operating_unit_ids:
            valid_ous = self.operating_unit_ids.filtered(lambda ou: ou in ous)
            self.operating_unit_ids = [(6, 0, valid_ous.ids)]
            
        return {'domain': {'operating_unit_ids': [('id', 'in', ous.ids)]}}

    # -------------------------
    # COMPUTE
    # -------------------------
    @staticmethod
    def _float_to_time(float_time):
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        return time(hours, minutes)

    @api.depends('start_time', 'end_time', 'is_night_shift')
    def _compute_time_range(self):
        for record in self:
            start = self._float_to_time(record.start_time)
            end = self._float_to_time(record.end_time)

            if record.is_night_shift:
                record.time_range = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')} (Next Day)"
            else:
                record.time_range = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    # -------------------------
    # CONSTRAINTS
    # -------------------------
    @api.constrains('start_time', 'end_time', 'is_night_shift', 'has_lunch_break', 'lunch_start_time', 'lunch_duration')
    def _check_time_validity(self):
        for record in self:
            if record.start_time < 0 or record.end_time < 0:
                raise ValidationError("Time values cannot be negative.")

            if record.start_time >= 24 or record.end_time > 24:
                raise ValidationError("Time must be within 24-hour range.")

            if not record.is_night_shift and record.end_time <= record.start_time:
                raise ValidationError(
                    "End time must be after start time unless it is a night shift."
                )

            if record.has_lunch_break:
                if record.lunch_start_time < 0 or record.lunch_duration <= 0:
                    raise ValidationError("Lunch start time cannot be negative and lunch duration must be greater than zero.")
                if record.lunch_start_time >= 24:
                    raise ValidationError("Lunch start time must be within 24-hour range.")

                lunch_end = record.lunch_start_time + record.lunch_duration
                if not record.is_night_shift:
                    if record.lunch_start_time < record.start_time or lunch_end > record.end_time:
                        raise ValidationError("Lunch break must fall within the shift start time and end time.")
                else:
                    pass

    def is_applicable_for(self, operating_unit=None, department=None, assigner_operating_unit=None, assigner_department=None):
        self.ensure_one()

        # Rule 1: Unassigned shift -> applies everywhere
        if not self.applies_to_branches and not self.operating_unit_ids and not self.department_ids:
            return True

        # Rule 2: applies_to_branches=True -> APPLICABLE to branches except head office
        if self.applies_to_branches:
            target_ou = operating_unit or assigner_operating_unit
            if target_ou:
                code = (target_ou.code or '').upper()
                name = (target_ou.name or '').upper()
                is_head_office = ('HEAD' in code or 'HEAD' in name or 'MAIN' in code or 'MAIN' in name or code == 'HO')
                if is_head_office:
                    return False
            return True

        # Collect OUs to check (both target location/employee OU, assigner/coach OU, and parent units)
        ous_to_check = []
        for ou in [operating_unit, assigner_operating_unit]:
            if ou:
                if ou not in ous_to_check:
                    ous_to_check.append(ou)
                if hasattr(ou, 'parent_unit') and ou.parent_unit and ou.parent_unit not in ous_to_check:
                    ous_to_check.append(ou.parent_unit)

        # Rule 3: If operating_unit_ids is specified, location MUST match
        if self.operating_unit_ids:
            if not ous_to_check or not any(ou in self.operating_unit_ids for ou in ous_to_check):
                return False  # Target location does not match restricted operating units

        # Collect Departments to check
        depts_to_check = [d for d in [department, assigner_department] if d]

        # Rule 4: If department_ids is specified, department MUST match
        if self.department_ids:
            dept_matched = False
            if depts_to_check:
                for dept in depts_to_check:
                    curr = dept
                    while curr:
                        if curr in self.department_ids:
                            dept_matched = True
                            break
                        curr = curr.parent_id

            if not dept_matched and ous_to_check:
                for ou in ous_to_check:
                    depts_linked = self.env['hr.department'].sudo().search([
                        '|',
                        ('operating_unit_id', '=', ou.id),
                        ('operating_unit', '=', ou.id)
                    ])
                    if any(d in self.department_ids or d.parent_id in self.department_ids for d in depts_linked):
                        dept_matched = True
                        break
                    if hasattr(ou, 'department') and ou.department and (ou.department in self.department_ids or ou.department.parent_id in self.department_ids):
                        dept_matched = True
                        break

            if not dept_matched:
                return False  # Target department does not match restricted departments

        return True

    @api.model
    def get_allowed_shift_ids(self, operating_unit_id=None, department_id=None, assigner_operating_unit_id=None, assigner_department_id=None):
        """
        Returns list of shift IDs allowed for the given target operating unit/department and assigner operating unit/department.
        """
        ou = self.env['operating.unit'].browse(operating_unit_id) if operating_unit_id else False
        dept = self.env['hr.department'].browse(department_id) if department_id else False
        a_ou = self.env['operating.unit'].browse(assigner_operating_unit_id) if assigner_operating_unit_id else False
        a_dept = self.env['hr.department'].browse(assigner_department_id) if assigner_department_id else False

        shifts = self.search([('active', '=', True)])
        allowed = shifts.filtered(lambda s: s.is_applicable_for(
            operating_unit=ou,
            department=dept,
            assigner_operating_unit=a_ou,
            assigner_department=a_dept
        ))
        return allowed.ids
        return allowed.ids

