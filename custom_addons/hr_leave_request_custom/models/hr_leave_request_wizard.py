# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_round
import logging

_logger = logging.getLogger(__name__)


class HrLeaveRequestWizard(models.TransientModel):
    """Data-entry wizard for creating a new Time Off / Leave Request.

    This exists specifically to stop Odoo's web client from silently
    persisting a real hr.leave record while the user is still filling in
    the form (the autosave-on-refresh/navigate-away behaviour). Because
    this is a TransientModel, any implicit autosave the client performs
    while the user is typing only ever touches a throwaway wizard row
    that is never shown in any Time Off list, never enters the approval
    workflow, and is auto-vacuumed by Odoo.

    The REAL hr.leave record is only ever created inside
    action_wizard_save / action_wizard_notify — i.e. only when the user
    explicitly clicks "Save" or "Notify Request".
    """
    _name = 'hr.leave.request.wizard'
    _description = 'New Leave Request'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        HrLeave = self.env['hr.leave']
        employee = HrLeave._get_current_employee()
        if employee:
            try:
                fetch_vals = HrLeave._get_employee_fetch_values(employee)
                for key, value in fetch_vals.items():
                    if key in self._fields:
                        defaults[key] = value
                defaults['employee_id'] = employee.id
            except Exception as e:
                _logger.error(f"Error auto-fetching employee data on New: {str(e)}")
        return defaults

    employee_id = fields.Many2one('hr.employee', string='Requester Name')
    job_position = fields.Char(string='Job Position')
    job_grade = fields.Char(string='Job Grade')
    job_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non Managerial'),
    ], string='Job Category')
    operating_unit = fields.Many2one('operating.unit', string='Operating Unit')
    accrued_leave_balance = fields.Float(string='Accrued Leave Balance', digits=(16, 2), readonly=True)
    scheduled_leave_balance = fields.Float(string='Scheduled Leave Balance', digits=(16, 2), readonly=True)
    computed_leave = fields.Float(string='Computed Leave', digits=(16, 2), readonly=True)
    number_of_days = fields.Float(string='Duration (Days)', default=0.0)
    half_day_type = fields.Selection([
        ('start', 'Starting Half Day'),
        ('end', 'Ending Half Day'),
    ], string='Select Half Day', default='end')

    holiday_status_id = fields.Many2one('hr.leave.type', string='Leave Reason')
    attachment = fields.Binary(string='Attachment')
    attachment_name = fields.Char(string='Attachment Name')
    comments = fields.Text(string='Comments')
    leave_start_date = fields.Date(string='Start Date')
    leave_end_date = fields.Date(string='End Date')
    starting_half_day = fields.Boolean(string='Morning Half Day')
    ending_half_day = fields.Boolean(string='Ending Half Day')
    half_day = fields.Boolean(string='Half day')
    delegated_employee_id = fields.Many2one('hr.employee', string='Delegated Employee')

    # Tracks whether "Compute Actual Leave Days" has produced an
    # up-to-date result for the current dates/half-day settings. Drives
    # visibility of the Notify Request button in the footer, so it can't
    # be clicked before the user has computed the leave. Reset whenever
    # an input that affects the computation changes.
    is_computed = fields.Boolean(string='Is Computed', default=False)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if not self.employee_id:
            return
        HrLeave = self.env['hr.leave']
        for field_name, value in HrLeave._get_employee_fetch_values(self.employee_id).items():
            if field_name in self._fields:
                setattr(self, field_name, value)

    @api.onchange('leave_start_date', 'leave_end_date', 'half_day',
                   'starting_half_day', 'ending_half_day')
    def _onchange_invalidate_computed(self):
        self.is_computed = False
        self.computed_leave = 0.0

    def _compute_days(self):
        self.ensure_one()
        start_date = self.leave_start_date
        end_date = self.leave_end_date
        if not start_date or not end_date:
            raise UserError(_(
                "Please fill in both Start Date and End Date before computing."))
        if end_date < start_date:
            raise UserError(_("End Date cannot be earlier than Start Date."))

        delta_days = (end_date - start_date).days + 1
        days = float(delta_days)

        if self.half_day:
            days = 0.5 if days == 1 else max(0.5, days - 0.5)
        else:
            if self.starting_half_day and self.ending_half_day and days > 1:
                days = max(0.5, days - 1.0)
            elif self.starting_half_day or self.ending_half_day:
                days = max(0.5, days - 0.5)

        return float_round(days, precision_digits=2)

    def action_compute_actual_leave_days(self):
        self.ensure_one()
        self.computed_leave = self._compute_days()
        self.is_computed = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Leave Request'),
                'message': _('Computed Leave: %s day(s)') % self.computed_leave,
                'type': 'success',
                'sticky': False,
            },
        }

    def _build_leave_vals(self, status):
        self.ensure_one()
        if not self.employee_id:
            raise UserError(_("Please select an employee first."))
        if not self.holiday_status_id:
            raise UserError(_("Please select a Leave Reason before saving."))
        if not self.leave_start_date or not self.leave_end_date:
            raise UserError(_(
                "Please fill in both Start Date and End Date before saving."))

        days = self.computed_leave or self._compute_days()

        return {
            'employee_id': self.employee_id.id,
            'requester_name': self.employee_id.name or '',
            'job_position': self.job_position,
            'job_grade': self.job_grade,
            'job_category': self.job_category,
            'operating_unit': self.operating_unit.id if self.operating_unit else False,
            'accrued_leave_balance': self.accrued_leave_balance,
            'scheduled_leave_balance': self.scheduled_leave_balance,
            'holiday_status_id': self.holiday_status_id.id,
            'attachment': self.attachment,
            'attachment_name': self.attachment_name,
            'comments': self.comments,
            'leave_start_date': self.leave_start_date,
            'leave_end_date': self.leave_end_date,
            'starting_half_day': self.starting_half_day,
            'ending_half_day': self.ending_half_day,
            'half_day': self.half_day,
            'delegated_employee_id': self.delegated_employee_id.id if self.delegated_employee_id else False,
            'computed_leave': days,
            'number_of_days': days,
            'date_from': fields.Datetime.to_datetime(self.leave_start_date),
            'date_to': fields.Datetime.to_datetime(self.leave_end_date),
            'request_date_from': self.leave_start_date,
            'request_date_to': self.leave_end_date,
            'fetch_status': 'fetched',
            'custom_saved': True,
            'is_edit_mode': False,
            'leave_request_status': status,
        }

    def _open_created_leave(self, leave):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Leave Request'),
            'res_model': 'hr.leave',
            'res_id': leave.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_wizard_save(self):
        """The FIRST point at which a real hr.leave row is ever
        created — equivalent to the old 'Save' button, saves as Draft."""
        self.ensure_one()
        vals = self._build_leave_vals('draft')
        leave = self.env['hr.leave'].with_context(allow_leave_create=True).create(vals)
        leave._show_notification(_("Leave request saved as Draft."))
        return self._open_created_leave(leave)

    def action_wizard_notify(self):
        """Creates the request AND notifies it in one click — equivalent
        to Save followed immediately by the old 'Notify Request'
        button."""
        self.ensure_one()
        if not self.is_computed or not self.computed_leave:
            self.action_compute_actual_leave_days()

        vals = self._build_leave_vals('notify')
        leave = self.env['hr.leave'].with_context(allow_leave_create=True).create(vals)

        template = self.env.ref(
            'hr_holidays.mail_template_leave_approval', raise_if_not_found=False)
        if template:
            try:
                template.send_mail(leave.id, force_send=True)
            except Exception as e:
                _logger.warning(f"Could not send email notification: {str(e)}")
        if leave.employee_id and leave.employee_id.parent_id:
            try:
                leave.employee_id.parent_id.user_id.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=f'Leave Request: {leave.holiday_status_id.name if leave.holiday_status_id else "Leave"}',
                    note=f'{leave.employee_id.name} has requested leave from {leave.leave_start_date} to {leave.leave_end_date}',
                    user_id=leave.employee_id.parent_id.user_id.id,
                )
            except Exception as e:
                _logger.warning(f"Could not create activity: {str(e)}")

        leave._show_notification(_("Leave request notified successfully."))
        return self._open_created_leave(leave)