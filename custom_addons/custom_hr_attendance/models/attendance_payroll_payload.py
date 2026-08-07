# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AttendancePayrollPayload(models.Model):
    """
    Payroll Integration Contract Model.

    Acts as a staging table between the Attendance module and the future Payroll
    module (Module 8). Attendance events that carry financial implications
    (approved overtime, unauthorized absences) are written here as 'pending' records.

    When Module 8 is built, it polls WHERE state = 'pending' on this model and
    transitions records to 'transferred' then 'processed'. No direct dependency on
    the payroll module is introduced at this stage. This model is the one-way contract
    both sides must respect.

    Pattern mirrors discipline_management.discipline.payroll.penalty for
    consistency across ERP modules.
    """
    _name = 'attendance.payroll.payload'
    _description = 'Attendance Payroll Integration Payload'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Reference',
        compute='_compute_display_name',
        store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='restrict',
        tracking=True,
    )
    payload_type = fields.Selection([
        ('overtime', 'Approved Overtime'),
        ('unauthorized_absence', 'Unauthorized Absence Deduction'),
    ], string='Payload Type', required=True, index=True, tracking=True)

    # Source reference: exactly one of these is set depending on payload_type
    source_overtime_id = fields.Many2one(
        'over.time',
        string='Source Overtime Record',
        ondelete='set null',
        help='Populated for overtime payloads. Links to the approved over.time record.',
    )
    source_attendance_id = fields.Many2one(
        'hr.attendance',
        string='Source Attendance Record',
        ondelete='set null',
        help='Populated for absence deduction payloads. Links to the triggering hr.attendance record.',
    )

    hours = fields.Float(
        string='Hours',
        digits=(10, 4),
        help='Applicable hours: overtime hours for overtime type, absent hours for absence type.',
    )
    effective_date = fields.Date(
        string='Effective Date',
        required=True,
        index=True,
        help='The payroll period date this payload applies to.',
    )
    state = fields.Selection([
        ('pending', 'Pending Transmission'),
        ('transferred', 'Transmitted to Payroll'),
        ('processed', 'Processed in Payslip'),
    ], string='State', default='pending', required=True, index=True, tracking=True)

    # Populated by Module 8 when it consumes this payload
    payslip_reference = fields.Char(
        string='Payslip Reference',
        readonly=True,
        copy=False,
        help='Set by Module 8 (Payroll) when this payload has been included in a payslip.',
    )
    notes = fields.Text(
        string='Notes',
        help='Internal notes for audit trail or manual adjustments.',
    )

    @api.depends('employee_id', 'payload_type', 'effective_date')
    def _compute_display_name(self):
        type_labels = dict(self._fields['payload_type'].selection)
        for rec in self:
            type_label = type_labels.get(rec.payload_type, rec.payload_type or '')
            emp_name = rec.employee_id.name or ''
            date_str = str(rec.effective_date) if rec.effective_date else ''
            rec.display_name = f'[ATT-PAY] {emp_name} / {type_label} / {date_str}'

    @api.model
    def create_overtime_payload(self, overtime_record):
        """
        Creates a pending payroll payload from an approved over.time record.
        Called by over_time.py on approval. Returns the created payload record.
        """
        return self.create({
            'employee_id': overtime_record.employee_id.id,
            'payload_type': 'overtime',
            'source_overtime_id': overtime_record.id,
            'hours': overtime_record.overtime_hours,
            'effective_date': overtime_record.date,
            'notes': _('Auto-created from approved overtime: %s') % overtime_record.name,
        })

    @api.model
    def create_absence_payload(self, employee_id, absence_date, hours=8.0, attendance_id=None):
        """
        Creates a pending payroll payload for an unauthorized absence.
        Called by cron_automatic_absence_detection after confirming no approved leave.
        Returns the created payload record.
        """
        return self.create({
            'employee_id': employee_id,
            'payload_type': 'unauthorized_absence',
            'source_attendance_id': attendance_id,
            'hours': hours,
            'effective_date': absence_date,
            'notes': _('Auto-created by absence detection cron for date: %s') % absence_date,
        })
