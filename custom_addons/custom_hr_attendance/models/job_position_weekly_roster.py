from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta

class JobPositionWeeklyRoster(models.Model):
    _name = "job.position.weekly.roster"
    _rec_name = "name"
    _description = "Weekly Job Shift Roster Exception"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "start_date desc, id desc"

    name = fields.Char(
        string="Roster Name",
        compute="_compute_name",
        store=True,
        index=True
    )
    active = fields.Boolean(string="Active", default=True, index=True)
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee Name",
        required=True,
        index=True,
        tracking=True
    )
    job_position = fields.Char(
        string="Job Position",
        related='employee_id.job_position.name',
        store=True,
        readonly=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string="Department",
        related='employee_id.department_id',
        store=True,
        readonly=True
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string="Operating Unit",
        related='employee_id.default_operating_unit_id',
        store=True,
        readonly=True
    )

    start_date = fields.Date(
        string="Week Start Date (Monday)",
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    end_date = fields.Date(
        string="Week End Date (Sunday)",
        compute="_compute_end_date",
        store=True,
        readonly=False,
        tracking=True
    )
    status = fields.Selection(
        string="Status",
        selection=[('active', "Active"), ('inactive', "Inactive")],
        default='active',
        tracking=True
    )
    notes = fields.Text(string="Notes & Special Instructions")

    # Day 1: Monday
    mon_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Monday Schedule", default='shift', required=True)
    mon_shift_id = fields.Many2one('job.shift', string="Monday Shift")

    # Day 2: Tuesday
    tue_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Tuesday Schedule", default='shift', required=True)
    tue_shift_id = fields.Many2one('job.shift', string="Tuesday Shift")

    # Day 3: Wednesday
    wed_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Wednesday Schedule", default='shift', required=True)
    wed_shift_id = fields.Many2one('job.shift', string="Wednesday Shift")

    # Day 4: Thursday
    thu_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Thursday Schedule", default='shift', required=True)
    thu_shift_id = fields.Many2one('job.shift', string="Thursday Shift")

    # Day 5: Friday
    fri_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Friday Schedule", default='shift', required=True)
    fri_shift_id = fields.Many2one('job.shift', string="Friday Shift")

    # Day 6: Saturday
    sat_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Saturday Schedule", default='shift', required=True)
    sat_shift_id = fields.Many2one('job.shift', string="Saturday Shift")

    # Day 7: Sunday
    sun_type = fields.Selection([('shift', 'Assigned Shift'), ('day_off', 'Day Off')], string="Sunday Schedule", default='day_off', required=True)
    sun_shift_id = fields.Many2one('job.shift', string="Sunday Shift")

    @api.depends('employee_id', 'start_date')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or "Employee"
            s_date = rec.start_date.strftime('%Y-%m-%d') if rec.start_date else ""
            rec.name = f"{emp} - Weekly Roster ({s_date})"

    @api.depends('start_date')
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date:
                rec.end_date = rec.start_date + timedelta(days=6)

    @api.constrains('start_date', 'end_date', 'employee_id', 'status', 'active')
    def _check_overlap(self):
        for rec in self:
            if not rec.employee_id or not rec.start_date:
                continue
            end = rec.end_date or (rec.start_date + timedelta(days=6))
            if rec.active and rec.status == 'active':
                overlap = self.search([
                    ('id', '!=', rec.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('active', '=', True),
                    ('status', '=', 'active'),
                    ('start_date', '<=', end),
                    ('end_date', '>=', rec.start_date)
                ], limit=1)
                if overlap:
                    raise ValidationError(_(
                        "An active weekly shift roster for employee '%s' already exists for week of %s to %s."
                    ) % (rec.employee_id.name, overlap.start_date, overlap.end_date))

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can create Weekly Roster Exceptions."))

        records = super().create(vals_list)
        for rec in records:
            if rec.employee_id and rec.employee_id.user_id:
                body = f"📅 <b>Weekly Shift Roster Assigned</b><br/>A new weekly shift schedule has been assigned to you for the week starting <b>{rec.start_date}</b>."
                rec._send_notification_to_employee(rec, body)
        return records

    def write(self, vals):
        if not (self.env.user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user') or
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or
                self.env.is_superuser()):
            raise UserError(_("Only Job Position Officers or Attendance Administrators can edit Weekly Roster Exceptions."))
        return super().write(vals)

    def _send_notification_to_employee(self, record, body_html):
        emp_user = record.employee_id.user_id
        if not emp_user or not emp_user.partner_id:
            return

        from markupsafe import Markup
        markup_body = Markup(body_html)

        try:
            record.sudo().message_subscribe(partner_ids=[emp_user.partner_id.id])
            record.sudo().message_post(
                body=markup_body,
                partner_ids=[emp_user.partner_id.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )
        except Exception:
            pass

        try:
            sender = self.env.user if self.env.user else self.env.ref('base.user_admin')
            channel = self.env['discuss.channel'].sudo().with_user(sender)._get_or_create_chat(
                partners_to=[emp_user.partner_id.id]
            )
            if channel:
                channel.sudo().with_user(sender).message_post(
                    body=markup_body,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment'
                )
        except Exception:
            pass

    def get_schedule_for_date(self, target_date):
        """
        Returns schedule dict for a specific target_date:
        {'is_day_off': True/False, 'shift_id': job.shift record or False}
        """
        self.ensure_one()
        # Monday=0, Tuesday=1, ..., Sunday=6
        weekday = target_date.weekday()
        day_map = {
            0: (self.mon_type, self.mon_shift_id),
            1: (self.tue_type, self.tue_shift_id),
            2: (self.wed_type, self.wed_shift_id),
            3: (self.thu_type, self.thu_shift_id),
            4: (self.fri_type, self.fri_shift_id),
            5: (self.sat_type, self.sat_shift_id),
            6: (self.sun_type, self.sun_shift_id),
        }
        stype, shift = day_map.get(weekday, ('shift', False))
        if stype == 'day_off':
            return {'is_day_off': True, 'shift_id': False}
        return {'is_day_off': False, 'shift_id': shift}
