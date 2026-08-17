# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import datetime
import pytz
import logging

_logger = logging.getLogger(__name__)


class HrAttendanceBatchRequest(models.Model):
    """
    Batch Attendance Entry Request for >3 days.
    Allows Managers to submit batch attendance requests for employees under their
    Operating Unit when duration exceeds 3 days, routing to the Manager's Coach for approval.
    """
    _name = 'hr.attendance.batch.request'
    _description = 'Batch Attendance Entry Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Request Reference', required=True, default=lambda self: _('New'), copy=False)
    manager_id = fields.Many2one('res.users', string='Submitted By (Manager)', default=lambda self: self.env.user, required=True, readonly=True)
    @api.model
    def _get_default_coach(self):
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if emp:
            return (emp.coach_id.id or emp.parent_id.id) if (emp.coach_id or emp.parent_id) else False
        return False

    @api.model
    def _get_default_ou(self):
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if emp and emp.default_operating_unit_id:
            return emp.default_operating_unit_id.id
        return False

    coach_id = fields.Many2one('hr.employee', string='Approving Coach / Supervisor', default=_get_default_coach, required=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', default=_get_default_ou, required=True, readonly=True)
    
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration_days', store=True)
    
    employee_ids = fields.Many2many('hr.employee', 'batch_req_emp_rel', 'batch_id', 'employee_id', string='Employees', required=True)
    
    rest_type = fields.Selection([
        ('none', 'Standard Shift Attendance'),
        ('morning_off', 'Finacle EOD Rest - Morning OFF (08:00 AM - 01:00 PM)'),
        ('afternoon_off', 'Finacle EOD Rest - Afternoon OFF (12:00 PM - 05:00 PM)'),
        ('full_day_off', 'Finacle EOD Rest - Full Day OFF')
    ], string='Rest / Exception Type', default='none', required=True)

    use_employee_shifts = fields.Boolean(string='Use Individual Assigned Shifts', default=True)
    overwrite_existing = fields.Boolean(string='Overwrite Existing Attendances', default=False, help='If enabled, existing attendances for target dates will be replaced.')
    check_in_time_only = fields.Float(string='Default Check-In Time', default=8.0)
    check_out_time_only = fields.Float(string='Default Check-Out Time', default=17.0)

    justification = fields.Text(string='Reason / Justification', required=True)
    attendance_reason_ids = fields.Many2many('hr.attendance.reason', string='Attendance Reasons')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Status', default='to_approve', tracking=True, index=True)

    is_responsible_approver = fields.Boolean(
        string='Is Responsible Approver',
        compute='_compute_is_responsible_approver'
    )
    is_creator = fields.Boolean(
        string='Is Request Creator',
        compute='_compute_is_creator'
    )

    @api.depends('manager_id')
    def _compute_is_creator(self):
        current_uid = self.env.uid
        for rec in self:
            rec.is_creator = (rec.manager_id.id == current_uid)

    @api.depends('coach_id', 'manager_id')
    def _compute_is_responsible_approver(self):
        user = self.env.user
        is_admin = user.has_group('hr_attendance.group_hr_attendance_manager') or user.has_group('base.group_system')
        for rec in self:
            is_coach = False
            if rec.coach_id:
                is_coach = (rec.coach_id.user_id.id == user.id) or (rec.coach_id.attendance_manager_id.id == user.id)
            rec.is_responsible_approver = is_admin or is_coach

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.attendance.batch.request') or _('Batch Request')
        return super(HrAttendanceBatchRequest, self).create(vals_list)

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                rec.duration_days = (rec.end_date - rec.start_date).days + 1
            else:
                rec.duration_days = 0

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.start_date and rec.end_date:
                if rec.end_date < rec.start_date:
                    raise ValidationError(_('End Date cannot be before Start Date.'))
                if rec.end_date > today:
                    raise ValidationError(_('Manual attendance batch request can only be created for past dates or today.'))

    def action_approve(self):
        """Coach approves request and generates batch attendances."""
        for rec in self:
            if not rec.is_responsible_approver:
                raise UserError(_('Only the assigned Coach/Supervisor (%s) or an Attendance Manager can approve or reject this request.') % (rec.coach_id.name if rec.coach_id else 'Coach'))
            if rec.state != 'to_approve':
                continue
            rec._generate_batch_attendances()
            rec.write({
                'state': 'approved'
            })
            if hasattr(rec, 'message_post'):
                rec.message_post(body=_('Batch Attendance Request approved by %s. Attendance records created.') % self.env.user.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Batch Request Approved'),
                'message': _('Batch Attendance Request approved successfully. Attendance records created.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }

    def action_reject(self):
        """Coach rejects request."""
        for rec in self:
            if not rec.is_responsible_approver:
                raise UserError(_('Only the assigned Coach/Supervisor (%s) or an Attendance Manager can approve or reject this request.') % (rec.coach_id.name if rec.coach_id else 'Coach'))
            rec.write({'state': 'rejected'})
            if hasattr(rec, 'message_post'):
                rec.message_post(body=_('Batch Attendance Request rejected by %s.') % self.env.user.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Batch Request Rejected'),
                'message': _('Batch Attendance Request has been rejected.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }

    def _generate_batch_attendances(self):
        """Core batch generator logic with lunch break splits and shift validation."""
        self.ensure_one()
        local_tz = pytz.timezone('Africa/Addis_Ababa')
        created_attendances = self.env['hr.attendance']
        Attendance = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True)

        cur_date = self.start_date
        while cur_date <= self.end_date:
            day_start_utc = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time.min)).astimezone(pytz.utc).replace(tzinfo=None)
            day_end_utc = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time.max)).astimezone(pytz.utc).replace(tzinfo=None)

            for emp in self.employee_ids:
                existing = Attendance.search([
                    ('employee_id', '=', emp.id),
                    ('check_in', '>=', day_start_utc),
                    ('check_in', '<=', day_end_utc)
                ])
                if existing:
                    if not self.overwrite_existing:
                        _logger.info("Batch Attendance: Skipping date %s for employee %s (existing attendance found).", cur_date, emp.name)
                        continue
                    else:
                        _logger.info("Batch Attendance: Overwriting %d existing record(s) on date %s for employee %s.", len(existing), cur_date, emp.name)
                        existing.unlink()

                shift_start = self.check_in_time_only
                shift_end = self.check_out_time_only
                has_lunch = True
                lunch_start = 12.0
                lunch_end = 13.0

                if self.use_employee_shifts:
                    shift_info = emp._get_employee_shift_info(target_date=cur_date) if hasattr(emp, '_get_employee_shift_info') else None
                    if shift_info:
                        if shift_info.get('is_day_off'):
                            continue # Skip day off
                        shift_start = shift_info.get('start_time', 8.0)
                        shift_end = shift_info.get('end_time', 17.0)
                        has_lunch = shift_info.get('has_lunch_break', True)
                        lunch_start = shift_info.get('lunch_start_time', 12.0)
                        lunch_end = lunch_start + shift_info.get('lunch_duration', 1.0)

                # Process rest / exception types
                if self.rest_type == 'full_day_off':
                    dt_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(int(shift_start), int((shift_start % 1)*60))))
                    dt_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(int(shift_end), int((shift_end % 1)*60))))
                    att_vals = {
                        'employee_id': emp.id,
                        'check_in': dt_in.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_out': dt_out.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_in_status': 'Finacle EOD Rest',
                        'check_out_status': 'Finacle EOD Rest',
                        'late_time_hour': 0.0,
                        'early_exit_hour': 0.0,
                        'is_acknowledged': True,
                        'acknowledged_by': self.manager_id.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                    }
                    created_attendances |= Attendance.create(att_vals)

                elif self.rest_type == 'morning_off':
                    # Morning OFF (08:00 AM - 01:00 PM Rest): System creates Acknowledged Morning Rest session (08:00 - 13:00 / 12:00)
                    # Employee then checks in by himself/herself for the afternoon session (13:00)
                    start_h = int(shift_start)
                    start_m = int((shift_start % 1) * 60)
                    end_h = int(lunch_end)
                    end_m = int((lunch_end % 1) * 60)
                    
                    dt_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(start_h, start_m)))
                    dt_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(end_h, end_m)))
                    
                    att_vals = {
                        'employee_id': emp.id,
                        'check_in': dt_in.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_out': dt_out.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_in_status': 'Finacle Morning Rest',
                        'check_out_status': 'Finacle Morning Rest',
                        'late_time_hour': 0.0,
                        'early_exit_hour': 0.0,
                        'is_acknowledged': True,
                        'acknowledged_by': self.manager_id.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                    }
                    created_attendances |= Attendance.create(att_vals)

                elif self.rest_type == 'afternoon_off':
                    # Afternoon OFF (12:00 PM - 05:00 PM Rest): Employee checks in/out morning session by himself/herself.
                    # System creates Acknowledged Afternoon Rest session (12:00 / 13:00 - 17:00)
                    start_h = int(lunch_start)
                    start_m = int((lunch_start % 1) * 60)
                    end_h = int(shift_end)
                    end_m = int((shift_end % 1) * 60)
                    
                    dt_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(start_h, start_m)))
                    dt_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(end_h, end_m)))
                    
                    att_vals = {
                        'employee_id': emp.id,
                        'check_in': dt_in.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_out': dt_out.astimezone(pytz.utc).replace(tzinfo=None),
                        'check_in_status': 'Finacle Afternoon Rest',
                        'check_out_status': 'Finacle Afternoon Rest',
                        'late_time_hour': 0.0,
                        'early_exit_hour': 0.0,
                        'is_acknowledged': True,
                        'acknowledged_by': self.manager_id.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                    }
                    created_attendances |= Attendance.create(att_vals)

                else:
                    # Standard Shift Attendance: Split into 2 sessions if lunch break exists
                    if has_lunch and (lunch_end < shift_end):
                        # Morning Session
                        s1_in_h, s1_in_m = int(shift_start), int((shift_start % 1) * 60)
                        s1_out_h, s1_out_m = int(lunch_start), int((lunch_start % 1) * 60)
                        dt1_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(s1_in_h, s1_in_m)))
                        dt1_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(s1_out_h, s1_out_m)))
                        
                        att1_vals = {
                            'employee_id': emp.id,
                            'check_in': dt1_in.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_out': dt1_out.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_in_status': 'Normal',
                            'check_out_status': 'Normal',
                            'late_time_hour': 0.0,
                            'early_exit_hour': 0.0,
                            'is_acknowledged': True,
                            'acknowledged_by': self.manager_id.id,
                            'acknowledged_date': fields.Datetime.now(),
                            'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                        }
                        created_attendances |= Attendance.create(att1_vals)

                        # Afternoon Session
                        s2_in_h, s2_in_m = int(lunch_end), int((lunch_end % 1) * 60)
                        s2_out_h, s2_out_m = int(shift_end), int((shift_end % 1) * 60)
                        dt2_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(s2_in_h, s2_in_m)))
                        dt2_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(s2_out_h, s2_out_m)))
                        
                        att2_vals = {
                            'employee_id': emp.id,
                            'check_in': dt2_in.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_out': dt2_out.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_in_status': 'Normal',
                            'check_out_status': 'Normal',
                            'late_time_hour': 0.0,
                            'early_exit_hour': 0.0,
                            'is_acknowledged': True,
                            'acknowledged_by': self.manager_id.id,
                            'acknowledged_date': fields.Datetime.now(),
                            'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                        }
                        created_attendances |= Attendance.create(att2_vals)

                    else:
                        in_h, in_m = int(shift_start), int((shift_start % 1) * 60)
                        out_h, out_m = int(shift_end), int((shift_end % 1) * 60)
                        dt_in = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(in_h, in_m)))
                        dt_out = local_tz.localize(datetime.datetime.combine(cur_date, datetime.time(out_h, out_m)))
                        
                        att_vals = {
                            'employee_id': emp.id,
                            'check_in': dt_in.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_out': dt_out.astimezone(pytz.utc).replace(tzinfo=None),
                            'check_in_status': 'Normal',
                            'check_out_status': 'Normal',
                            'late_time_hour': 0.0,
                            'early_exit_hour': 0.0,
                            'is_acknowledged': True,
                            'acknowledged_by': self.manager_id.id,
                            'acknowledged_date': fields.Datetime.now(),
                            'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)]
                        }
                        created_attendances |= Attendance.create(att_vals)

            cur_date += datetime.timedelta(days=1)

        return created_attendances
