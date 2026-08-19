# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import datetime
import pytz


class HrAttendanceManualWizard(models.TransientModel):
    """
    Enhanced Manual Attendance Creation Wizard.
    Supports 3 modes:
    1. Individual Entry (Single employee, single date, check-in/out or check-in only)
    2. Batch Entry (Operating Unit employees, date range, lunch break splitting, Coach approval for >3 days)
    3. Finacle EOD Rest Entry (Morning OFF, Afternoon OFF, Full Day OFF for bank ops staff & drivers)
    """
    _name = 'hr.attendance.manual.wizard'
    _description = 'Manual Attendance Entry Wizard'

    entry_type = fields.Selection([
        ('individual', 'Individual Employee (Single Day)'),
        ('batch', 'Batch Operating Unit (Multi-Day / Outage)'),
        ('finacle_rest', 'Duty OFF(Half-Day / Full-Day)')
    ], string='Entry Mode', default='individual', required=True)

    # --- Individual Mode Fields ---
    @api.model
    def _get_default_employee(self):
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return emp.id if emp else False

    @api.model
    def _get_employee_domain(self):
        if self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return [('active', '=', True)]
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if emp:
            return ['&', ('active', '=', True), '|', '|',
                ('parent_id', '=', emp.id),
                ('attendance_manager_id', '=', self.env.uid),
                ('default_operating_unit_id', '=', emp.default_operating_unit_id.id if emp.default_operating_unit_id else False)
            ]
        return [('active', '=', True)]

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        default=_get_default_employee,
        domain=lambda self: self._get_employee_domain(),
    )
    work_date = fields.Date(
        string='Attendance Date',
        default=fields.Date.context_today,
    )
    check_in_time = fields.Float(
        string='Check-In Time',
        default=8.0,
        help='Check-in time (e.g. 8.0 = 08:00 AM)',
    )
    check_out_time = fields.Float(
        string='Check-Out Time',
        default=17.0,
        help='Check-out time (e.g. 17.0 = 05:00 PM)',
    )

    # --- Batch & Finacle Rest Fields ---
    @api.model
    def _get_default_operating_unit(self):
        emp = self.env.user.employee_id
        if emp and emp.default_operating_unit_id:
            return emp.default_operating_unit_id.id
        return False

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        default=_get_default_operating_unit,
    )
    
    employee_ids = fields.Many2many(
        'hr.employee',
        'manual_wiz_emp_rel',
        'wiz_id',
        'emp_id',
        string='Employees',
        domain=lambda self: self._get_employee_domain(),
    )

    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
    )
    end_date = fields.Date(
        string='End Date',
        default=fields.Date.context_today,
    )
    duration_days = fields.Integer(
        string='Duration (Days)',
        compute='_compute_duration_days',
        store=True,
    )

    rest_type = fields.Selection([
        ('morning_off', 'Morning OFF'),
        ('afternoon_off', 'Afternoon OFF'),
        ('full_day_off', 'Full Day OFF')
    ], string='Rest / Exception Type', default='morning_off')

    use_employee_shifts = fields.Boolean(
        string='Use Individual Assigned Shifts & Lunch Splits',
        default=True,
    )
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Attendances',
        default=False,
        help='If checked, existing attendances for selected employees on target dates will be replaced.',
    )
    check_in_time_only = fields.Float(string='Default Check-In Time', default=8.0)
    check_out_time_only = fields.Float(string='Default Check-Out Time', default=17.0)

    # --- Common Fields ---
    justification = fields.Text(
        string='Reason / Justification',
        required=True,
        help='Mandatory explanation for manual attendance entry.',
    )
    attendance_reason_ids = fields.Many2many(
        'hr.attendance.reason',
        string='Attendance Reasons',
    )

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                rec.duration_days = (rec.end_date - rec.start_date).days + 1
            else:
                rec.duration_days = 0

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id:
            emps = self.env['hr.employee'].search([
                ('default_operating_unit_id', '=', self.operating_unit_id.id),
                ('active', '=', True)
            ])
            self.employee_ids = [(6, 0, emps.ids)]

    @api.onchange('work_date')
    def _onchange_work_date(self):
        if self.work_date:
            if not self.check_in_time:
                self.check_in_time = 8.0
            if not self.check_out_time:
                self.check_out_time = 17.0

    @api.constrains('work_date', 'start_date', 'end_date', 'entry_type')
    def _check_back_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.entry_type == 'individual' and rec.work_date:
                if rec.work_date > today:
                    raise ValidationError(_('Manual attendance entry can only be created for past dates or today.'))
            elif rec.entry_type == 'batch' and rec.end_date:
                if rec.end_date > today:
                    raise ValidationError(_('Manual attendance batch entry can only be created for past dates or today.'))
                if rec.start_date and rec.end_date < rec.start_date:
                    raise ValidationError(_('End Date cannot be before Start Date.'))

    def _float_time_to_utc_dt(self, target_date, float_time):
        """Converts local EAT date and float time into a UTC Datetime object."""
        if float_time is None or float_time is False:
            return False
        import datetime
        import pytz
        eat_tz = pytz.timezone('Africa/Addis_Ababa')
        
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        if minutes >= 60:
            hours = (hours + 1) % 24
            minutes = 0
            
        local_dt = eat_tz.localize(datetime.datetime.combine(target_date, datetime.time(hours, minutes)))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    def action_create_manual_attendance(self):
        """Main execution action for Individual, Batch, or Finacle Rest entries."""
        self.ensure_one()
        today = fields.Date.context_today(self)

        # ----------------------------------------------------
        # SCENARIO 1: INDIVIDUAL ENTRY
        # ----------------------------------------------------
        if self.entry_type == 'individual':
            if not self.employee_id or not self.work_date or self.check_in_time is False:
                raise ValidationError(_('Employee, Attendance Date, and Check-In Time are required for individual entry.'))

            dt_check_in = self._float_time_to_utc_dt(self.work_date, self.check_in_time)
            dt_check_out = self._float_time_to_utc_dt(self.work_date, self.check_out_time) if self.check_out_time else False

            if dt_check_out and dt_check_out <= dt_check_in:
                raise ValidationError(_('Check-Out time must be strictly after Check-In time.'))

            vals = {
                'employee_id': self.employee_id.id,
                'work_date': self.work_date,
                'check_in': dt_check_in,
                'check_out': dt_check_out,
                'is_acknowledged': True,
                'acknowledged_by': self.env.user.id,
                'acknowledged_date': fields.Datetime.now(),
                'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
            }

            att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)
            if hasattr(att, 'message_post'):
                att.message_post(body=_('Manual attendance created by %s. Justification: %s') % (self.env.user.name, self.justification))

            return {
                'name': _('Manual Attendance Created'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.attendance',
                'res_id': att.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # ----------------------------------------------------
        # SCENARIO 2: BATCH OPERATING UNIT ENTRY
        # ----------------------------------------------------
        elif self.entry_type == 'batch':
            if not self.employee_ids or not self.start_date or not self.end_date:
                raise ValidationError(_('Employees, Start Date, and End Date are required for batch entry.'))

            duration = (self.end_date - self.start_date).days + 1

            # ROUTING RULE FOR >3 DAYS: Requires Coach Approval
            if duration > 3:
                coach = self.env.user.employee_id.coach_id if self.env.user.employee_id else None
                if not coach:
                    # Fallback to parent manager or system admin
                    coach = self.env.user.employee_id.parent_id if self.env.user.employee_id else None
                
                req_vals = {
                    'name': _('Batch Request (%s to %s)') % (self.start_date, self.end_date),
                    'manager_id': self.env.user.id,
                    'coach_id': coach.id if coach else self.env.user.employee_id.id,
                    'operating_unit_id': self.operating_unit_id.id if self.operating_unit_id else self.env.user.employee_id.default_operating_unit_id.id,
                    'start_date': self.start_date,
                    'end_date': self.end_date,
                    'employee_ids': [(6, 0, self.employee_ids.ids)],
                    'use_employee_shifts': self.use_employee_shifts,
                    'overwrite_existing': self.overwrite_existing,
                    'check_in_time_only': self.check_in_time_only,
                    'check_out_time_only': self.check_out_time_only,
                    'justification': self.justification,
                    'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    'state': 'to_approve',
                }
                req = self.env['hr.attendance.batch.request'].sudo().create(req_vals)
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Batch Request Submitted to Coach'),
                        'message': _('Batch attendance duration (%d days) exceeds 3 days. Request %s has been submitted to your Coach for approval.') % (duration, req.name),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            # <= 3 DAYS: Direct Batch Execution
            req_obj = self.env['hr.attendance.batch.request'].sudo().new({
                'manager_id': self.env.user.id,
                'coach_id': self.env.user.employee_id.id if self.env.user.employee_id else False,
                'operating_unit_id': self.operating_unit_id.id if self.operating_unit_id else False,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'employee_ids': [(6, 0, self.employee_ids.ids)],
                'rest_type': 'none',
                'use_employee_shifts': self.use_employee_shifts,
                'overwrite_existing': self.overwrite_existing,
                'check_in_time_only': self.check_in_time_only,
                'check_out_time_only': self.check_out_time_only,
                'justification': self.justification,
                'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
            })
            created = req_obj._generate_batch_attendances()

            return {
                'name': _('Batch Attendance Created'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.attendance',
                'domain': [('id', 'in', created.ids)],
                'view_mode': 'list,form',
                'target': 'current',
            }

        # ----------------------------------------------------
        # SCENARIO 3: FINACLE EOD COMPENSATORY REST
        # ----------------------------------------------------
        elif self.entry_type == 'finacle_rest':
            if not self.employee_ids or not self.work_date:
                raise ValidationError(_('Employees and Target Date are required for Finacle EOD Rest grant.'))

            req_obj = self.env['hr.attendance.batch.request'].sudo().new({
                'manager_id': self.env.user.id,
                'coach_id': self.env.user.employee_id.id if self.env.user.employee_id else False,
                'operating_unit_id': self.operating_unit_id.id if self.operating_unit_id else False,
                'start_date': self.work_date,
                'end_date': self.work_date,
                'employee_ids': [(6, 0, self.employee_ids.ids)],
                'rest_type': self.rest_type,
                'use_employee_shifts': True,
                'justification': self.justification,
                'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
            })
            created = req_obj._generate_batch_attendances()

            return {
                'name': _('Finacle EOD Rest Attendance Created'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.attendance',
                'domain': [('id', 'in', created.ids)],
                'view_mode': 'list,form',
                'target': 'current',
            }
