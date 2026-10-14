# -*- coding: utf-8 -*-

import base64
import io
from datetime import date, timedelta
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
except ImportError:
    Workbook = None


class EdsVenue(models.Model):
    """Registered training venue (EDS-019)."""
    _name = 'eds.venue'
    _description = 'Training Venue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='Venue / Hotel Name', required=True, tracking=True)
    venue_type = fields.Selection([
        ('hotel', 'Hotel / Conference Center'),
        ('internal_hall', 'Bank Internal Training Facility'),
        ('external_hall', 'External Hall / Auditorium'),
        ('other', 'Other Facility'),
    ], string='Venue / Facility Type', default='hotel', required=True, tracking=True)
    contact_person = fields.Char(string='Contact Person')
    contact_phone = fields.Char(string='Contact Phone')
    contact_email = fields.Char(string='Contact Email')
    city = fields.Char(string='City / Sub-City', default='Addis Ababa')
    country_id = fields.Many2one('res.country', string='Country')
    location_scope = fields.Selection([
        ('local', 'Local'), ('international', 'International'),
    ], string='Location Scope', default='local', required=True)
    address = fields.Text(string='Address / Location Details')
    location = fields.Char(string='Location Summary')
    capacity = fields.Integer(string='Seating / Hall Capacity', default=30, tracking=True)
    facilities = fields.Text(string='Facilities / Equipment (Audio/Visual, Projector, WiFi)')
    has_lodging = fields.Boolean(string='Hotel Lodging Available', default=False)
    has_catering = fields.Boolean(string='Catering & Refreshments Available', default=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'eds_venue_attachment_rel', 'venue_id', 'attachment_id',
        string='Hotel / Venue Documents & Proposals')
    notes = fields.Text(string='General Notes')
    active = fields.Boolean(string='Active', default=True)
    booking_ids = fields.One2many('eds.venue.booking', 'venue_id', string='Bookings')
    booking_count = fields.Integer(string='Booking Count', compute='_compute_booking_count')

    @api.depends('booking_ids')
    def _compute_booking_count(self):
        for rec in self:
            rec.booking_count = len(rec.booking_ids)

    @api.constrains('capacity')
    def _check_capacity(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_('Venue capacity must be greater than zero.'))

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.venue.booking',
            'view_mode': 'list,form',
            'domain': [('venue_id', '=', self.id)],
        }


class EdsVenueBooking(models.Model):
    """Booking of a venue for a session with conflict protection (/020).

    A venue cannot be double-booked on overlapping slots: the constraint below
    blocks any second booking (or session) on the same venue with an overlapping
    datetime window while it is requested/confirmed.
    """
    _name = 'eds.venue.booking'
    _description = 'Venue Booking'
    _order = 'date_start desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    venue_id = fields.Many2one('eds.venue', string='Venue', required=True, ondelete='cascade',
                               index=True)
    session_id = fields.Many2one('eds.session', string='Session', ondelete='set null')
    date_start = fields.Datetime(string='Start', required=True)
    date_end = fields.Datetime(string='End', required=True)
    state = fields.Selection([
        ('requested', 'Requested'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='requested', required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _check_date_range_valid = models.Constraint(
        'CHECK(date_end > date_start)',
        'The booking end must be after its start!',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('status', 'draft') != 'draft':
                raise UserError(_('A session must start as a draft and follow the delivery workflow.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.venue.booking') or _('New')
        return super().create(vals_list)

    @api.constrains('venue_id', 'date_start', 'date_end', 'state')
    def _check_venue_conflict(self):
        """No double-booking of a venue on overlapping slots ."""
        for rec in self:
            if rec.state == 'cancelled':
                continue
            conflicting = self.search([
                ('id', '!=', rec.id),
                ('venue_id', '=', rec.venue_id.id),
                ('state', '!=', 'cancelled'),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ], limit=1)
            if conflicting:
                raise ValidationError(_(
                    'Venue Conflict : %s is already booked from %s to %s '
                    '(booking %s). Choose a different slot or venue.')
                    % (rec.venue_id.name, conflicting.date_start, conflicting.date_end,
                       conflicting.name))

    def action_confirm(self):
        for rec in self:
            if rec.state != 'requested':
                raise UserError(_('Only requested bookings can be confirmed.'))
            rec.state = 'confirmed'
            rec.message_post(body=_('Venue booking %s confirmed.') % rec.name)

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            rec.state = 'cancelled'
            if rec.session_id and rec.session_id.state != 'cancelled':
                rec.session_id.message_post(
                    body=_('Venue booking %s for %s was cancelled.') % (rec.name, rec.venue_id.name))


class EdsBatch(models.Model):
    """Cohort / batch grouping sessions of a course."""
    _name = 'eds.batch'
    _description = 'Training Batch / Cohort'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program', required=True,
                                tracking=True)
    description = fields.Char(string='Batch Name / Period')
    max_capacity = fields.Integer(string='Max Capacity', default=30, tracking=True)
    session_ids = fields.One2many('eds.session', 'batch_id', string='Sessions')
    session_count = fields.Integer(string='Session Count', compute='_compute_session_count')
    participant_target = fields.Integer(string='Target Participants', default=0)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('planned', 'Planned'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('session_ids')
    def _compute_session_count(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.batch') or _('New')
        return super().create(vals_list)

    def action_plan(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft batches can be planned.'))
            rec.state = 'planned'
            rec.message_post(body=_('Batch %s planned.') % rec.name)

    def action_activate(self):
        for rec in self:
            if rec.state != 'planned':
                raise UserError(_('Only planned batches can be activated.'))
            rec.state = 'active'
            rec.message_post(body=_('Batch %s activated - sessions may be scheduled.') % rec.name)

    def action_close(self):
        for rec in self:
            if rec.state not in ('planned', 'active'):
                raise UserError(_('Only planned or active batches can be closed.'))
            rec.state = 'closed'
            rec.message_post(body=_('Batch %s closed.') % rec.name)


class EdsSession(models.Model):
    """A scheduled delivery of a course (-023, ...022).

    Carries the venue, trainers (constrained to the trainer register with matching
    competencies and availability - ) and dates; enforces venue and trainer
    conflict checks (/020), and notifies participants on reschedule or
    cancellation . Sessions are created from annual-plan lines on
    publication and feed the planned-vs-actual variance.
    """
    _name = 'eds.session'
    _description = 'Training Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program', tracking=True)
    program_name = fields.Char(string='Program Name',
                               help='Used when the session is not linked to a catalog course.')
    plan_line_id = fields.Many2one('eds.annual.plan.line', string='Annual Plan Line',
                                   ondelete='set null', index=True,
                                   help='Links the session to the annual plan for variance '
                                        'monitoring.')
    approved_plan_id = fields.Many2one(
        'eds.annual.plan', string='Approved Annual Plan',
        domain="[('state', 'in', ('published', 'amended')), ('fiscal_year', '=like', session_year + '%')]",
        default=lambda self: self._default_approved_plan(),
        help='Choose the approved plan for the training year; leave blank for an approved unplanned request.')
    session_year = fields.Char(string='Session Year', compute='_compute_session_year')
    delivery_method = fields.Selection([
        ('internal', 'Internal / ToT'),
        ('local_external', 'Local External'),
        ('international', 'International'),
    ], string='Delivery Type', default='internal', required=True)
    batch_id = fields.Many2one('eds.batch', string='Batch / Cohort', ondelete='set null')
    date_start = fields.Datetime(string='Start Date', required=True, index=True, tracking=True)
    date_end = fields.Datetime(string='End Date', required=True, tracking=True)
    start_time = fields.Float(string='Start Time', default=8.5,
                              help='Start hour of the first day (e.g. 8.5 = 08:30).')
    duration_hours = fields.Float(string='Duration (Hours)', default=8.0, tracking=True)
    venue_id = fields.Many2one('eds.venue', string='Venue', ondelete='restrict',
                               tracking=True, domain="[('active', '=', True)]")
    trainer_ids = fields.Many2many(
        'eds.trainer', 'eds_session_trainer_rel', 'session_id', 'trainer_id',
        string='Trainers', tracking=True,
        help='Only active trainers from the register may be assigned .')
    trainer_count = fields.Integer(string='Trainer Count', compute='_compute_trainer_count', store=True)
    capacity = fields.Integer(
        string='Capacity', default=lambda self: self._get_default_capacity(),
        help='Maximum number of participants (default 25-30 from EDS settings, ).')

    # Awarded Sourcing & Venue Winners (FREDS034/036/037)
    awarded_provider_id = fields.Many2one(
        'eds.external.provider', string='Awarded Training Provider / Vendor', tracking=True,
        help='Vendor selected / awarded for delivering this course session.')
    awarded_venue_id = fields.Many2one(
        'eds.venue', string='Awarded Hotel / Venue', tracking=True,
        help='Hotel or venue selected / awarded for hosting this session.')

    @api.onchange('awarded_venue_id')
    def _onchange_awarded_venue_id(self):
        if self.awarded_venue_id:
            self.venue_id = self.awarded_venue_id

    @api.model
    def _default_approved_plan(self):
        return self._find_approved_plan_for_year(str(fields.Date.context_today(self).year))

    @api.model
    def _find_approved_plan_for_year(self, year):
        return self.env['eds.annual.plan'].search([
            ('state', 'in', ('published', 'amended')),
            ('fiscal_year', '=like', year + '%'),
            ('company_id', '=', self.env.company.id),
        ], order='id desc', limit=1).id or False

    @api.depends('date_start')
    def _compute_session_year(self):
        for rec in self:
            rec.session_year = str(fields.Date.to_date(rec.date_start).year) if rec.date_start else str(fields.Date.context_today(rec).year)

    @api.onchange('date_start')
    def _onchange_date_start_plan(self):
        if self.date_start and not self.plan_line_id:
            self.approved_plan_id = self._find_approved_plan_for_year(
                str(fields.Date.to_date(self.date_start).year))

    @api.onchange('approved_plan_id')
    def _onchange_approved_plan_id(self):
        if self.plan_line_id.plan_id != self.approved_plan_id:
            self.plan_line_id = False

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.plan_line_id:
            self.approved_plan_id = self.plan_line_id.plan_id
            self.course_id = self.plan_line_id.course_id
            self.program_name = self.plan_line_id.program_name
            self.delivery_method = self.plan_line_id.delivery_method

    @api.onchange('delivery_method', 'awarded_provider_id')
    def _onchange_delivery_provider(self):
        if self.delivery_method == 'internal':
            self.awarded_provider_id = False
            self.trainer_ids = self.trainer_ids.filtered(
                lambda trainer: trainer.trainer_type == 'internal' and trainer.tot_certified)
        else:
            self.trainer_ids = self.trainer_ids.filtered(
                lambda trainer: trainer.trainer_type == 'external' and
                trainer.external_provider_id == self.awarded_provider_id)

    # Customizable Certificate Template & Wording
    certificate_title = fields.Char(
        string='Certificate Title',
        help='Leave empty to use the certificate title configured on the course.')
    certificate_body_text = fields.Text(
        string='Certificate Body Content',
        help='Custom body text for certificates issued for this session. Use placeholders like {employee_name}, {course_name}...')
    certificate_signatory_name = fields.Char(string='Authorized Signatory Name')
    certificate_signatory_title = fields.Char(
        string='Authorized Signatory Title',
        help='Leave empty to use the signatory title configured on the course.')

    def action_preview_certificate(self):
        self.ensure_one()
        return self.env.ref(
            'employee_development_system.action_report_eds_session_certificate_preview').report_action(self)

    approval_flow = fields.Selection([
        ('standard', 'Standard (Line Manager -> L&D)'),
        ('budget_hr', 'With Budget/HR Gate'),
    ], string='Approval Flow', default='standard',
        help='Per-program approval chain override : programs involving budget '
             'add an explicit Budget/HR approval step.')
    nomination_ids = fields.One2many('eds.nomination', 'session_id', string='Nominations')
    nomination_count = fields.Integer(string='Nomination Count', compute='_compute_nomination_count')
    enrollment_ids = fields.One2many('eds.enrollment', 'session_id', string='Enrollments')
    enrolled_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_enrolled_employee_ids',
        string='Enrolled Employees',
        help='Employees confirmed or attended for this session.')
    enrolled_count = fields.Integer(string='Enrolled', compute='_compute_enrollment_counts')
    waitlist_count = fields.Integer(string='Waitlisted', compute='_compute_enrollment_counts')
    recurrence = fields.Selection([
        ('single', 'Single Session'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-Weekly'),
        ('monthly', 'Monthly'),
        ('custom', 'Custom'),
    ], string='Recurrence', default='single')
    recurrence_details = fields.Text(string='Recurrence Details')
    status = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rescheduled', 'Rescheduled'),
    ], string='Status', default='draft', required=True, tracking=True)
    conflict_flag = fields.Boolean(
        string='Conflict', compute='_compute_conflict_flag', search='_search_conflict_flag',
        help='True when the venue or a trainer is already engaged on an overlapping slot '
             '(/020).')
    booking_ids = fields.One2many('eds.venue.booking', 'session_id', string='Venue Bookings')
    booking_id = fields.Many2one('eds.venue.booking', string='Current Booking',
                                 compute='_compute_booking_id')

    # ── attendance & delivery tracking (/041/045) ──
    attendance_ids = fields.One2many(
        'eds.session.attendance', 'session_id', string='Attendance Records',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    cost_ids = fields.One2many('eds.cost', 'session_id', string='Actual Costs')
    attendance_count = fields.Integer(
        string='Attendance', compute='_compute_delivery_counts',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    attendance_rate = fields.Float(
        string='Session Attendance %', compute='_compute_attendance_rate', store=True,
        digits=(5, 2),
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive',
        help='Attended / recorded participants for this session.')
    feedback_ids = fields.One2many('eds.feedback', 'session_id', string='Daily Feedback')
    feedback_count = fields.Integer(string='Feedback', compute='_compute_delivery_counts')
    assessment_ids = fields.One2many(
        'eds.assessment', 'session_id', string='Assessments',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    assessment_count = fields.Integer(
        string='Assessment Count', compute='_compute_delivery_counts',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    international_training_ids = fields.One2many(
        'eds.international.training', 'session_id', string='International Training')
    international_training_count = fields.Integer(
        string='International Training Count', compute='_compute_delivery_counts')

    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('date_start', 'date_end')
    def _check_date_range(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_('The session end date must not be before its start date.'))

    @api.constrains('capacity')
    def _check_capacity_positive(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_('Session capacity must be greater than zero.'))

    @api.model
    def _get_default_capacity(self):
        """Default class size from EDS settings (BRD §4.2: 25–30 per cohort)."""
        return self._get_int_param('eds.default_class_capacity', 30)

    @api.depends('date_start', 'date_end', 'venue_id', 'trainer_ids', 'status')
    def _compute_conflict_flag(self):
        for rec in self:
            if rec.status in ('completed', 'cancelled') or not rec.date_start or not rec.date_end:
                rec.conflict_flag = False
                continue
            rec.conflict_flag = bool(
                rec._get_venue_conflicts() or rec._get_trainer_conflicts()
                or rec._get_blocked_trainer_availability())

    def _search_conflict_flag(self, operator, value):
        """Search support for the computed conflict flag (e.g. the "Conflicts" filter)."""
        sessions = self.search([
            ('status', 'not in', ('completed', 'cancelled')),
            ('date_start', '!=', False),
            ('date_end', '!=', False),
        ])
        target = bool(value)
        if operator in ('=', 'ilike', 'like'):
            matched = [s.id for s in sessions if s.conflict_flag == target]
        elif operator in ('!=', 'not ilike', 'not like'):
            matched = [s.id for s in sessions if s.conflict_flag != target]
        else:
            raise UserError(_('Operator %s is not supported on conflict_flag.') % operator)
        return [('id', 'in', matched)]

    @api.depends('booking_ids', 'booking_ids.state')
    def _compute_booking_id(self):
        for rec in self:
            active = rec.booking_ids.filtered(lambda b: b.state != 'cancelled')
            rec.booking_id = active[0] if active else False

    @api.depends('trainer_ids')
    def _compute_trainer_count(self):
        for rec in self:
            rec.trainer_count = len(rec.trainer_ids)

    @api.depends('enrollment_ids.state', 'enrollment_ids.employee_id')
    def _compute_enrolled_employee_ids(self):
        for rec in self:
            rec.enrolled_employee_ids = rec.enrollment_ids.filtered(
                lambda e: e.state in ('enrolled', 'completed')
            ).mapped('employee_id')

    @api.depends('enrollment_ids', 'enrollment_ids.state')
    def _compute_enrollment_counts(self):
        """live enrolled / waitlisted counts from the enrollments."""
        for rec in self:
            rec.enrolled_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'enrolled'))
            rec.waitlist_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'waitlisted'))

    @api.depends('nomination_ids')
    def _compute_nomination_count(self):
        for rec in self:
            rec.nomination_count = len(rec.nomination_ids)

    @api.depends('attendance_ids', 'feedback_ids', 'assessment_ids',
                 'international_training_ids')
    def _compute_delivery_counts(self):
        for rec in self:
            rec.attendance_count = len(rec.attendance_ids)
            rec.feedback_count = len(rec.feedback_ids)
            rec.assessment_count = len(rec.assessment_ids)
            rec.international_training_count = len(rec.international_training_ids)

    @api.depends('attendance_ids', 'attendance_ids.attended')
    def _compute_attendance_rate(self):
        """Session-level attendance %."""
        for rec in self:
            total = len(rec.attendance_ids)
            rec.attendance_rate = (
                round(len(rec.attendance_ids.filtered('attended')) * 100.0 / total, 2)
                if total else 0.0)

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.program_name = self.course_id.name
            if not self.capacity:
                self.capacity = self._get_int_param('eds.default_class_capacity', 30)
            if self.course_id.duration_days and (not self.date_end or not self.date_start):
                self.duration_hours = self.course_id.duration_days * 8.0
            if not self.trainer_ids:
                qualified = self.env['eds.trainer']._get_qualified_trainers(
                    self.course_id.competency_line_ids.mapped('competency_id'),
                    self.date_start, self.date_end)
                if qualified:
                    self.trainer_ids = [(6, 0, qualified.ids)]

    @api.onchange('date_start', 'date_end', 'venue_id', 'trainer_ids')
    def _onchange_conflict_check(self):
        """Warn (but do not block) on venue/trainer conflicts during editing (/020)."""
        if not self.date_start or not self.date_end or self.status in ('cancelled',):
            return
        conflicts = []
        venue = self._get_venue_conflicts()
        if venue:
            conflicts.append(_('Venue %s is already booked on an overlapping slot (session %s).')
                             % (self.venue_id.name, venue[0].name))
        trainers = self._get_trainer_conflicts()
        for t in trainers:
            conflicts.append(_('Trainer %s is already assigned to an overlapping session.')
                             % t.name)
        blocked = self._get_blocked_trainer_availability()
        for t in blocked:
            conflicts.append(_('Trainer %s has a blocked availability record in this period.')
                             % t.name)
        if conflicts:
            return {
                'warning': {
                    'title': _('Scheduling Conflict (/020)'),
                    'message': '\n'.join(conflicts),
                },
            }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('date_start') and not vals.get('plan_line_id') and 'approved_plan_id' not in vals:
                vals['approved_plan_id'] = self._find_approved_plan_for_year(
                    str(fields.Date.to_date(vals['date_start']).year))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.session') or _('New')
            if vals.get('awarded_venue_id'):
                vals['venue_id'] = vals['awarded_venue_id']
            if vals.get('plan_line_id'):
                plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
                vals.setdefault('approved_plan_id', plan_line.plan_id.id)
                vals.setdefault('delivery_method', plan_line.delivery_method)
                vals.setdefault('course_id', plan_line.course_id.id or False)
                vals.setdefault('program_name', plan_line.program_name)
            if vals.get('plan_line_id') and not vals.get('awarded_provider_id'):
                selection = self.env['eds.course.vendor.selection'].search([
                    ('plan_line_id', '=', vals['plan_line_id']), ('state', '=', 'awarded'),
                    ('awarded_vendor_id', '!=', False),
                ], order='id desc', limit=1)
                if selection:
                    vals['awarded_provider_id'] = selection.awarded_vendor_id.id
                    winner = selection.line_ids.filtered(
                        lambda line: line.status in ('awarded', 'contract'))[:1]
                    if winner.trainer_id and 'trainer_ids' not in vals:
                        vals['trainer_ids'] = [(6, 0, winner.trainer_id.ids)]
            if vals.get('plan_line_id') and not vals.get('awarded_venue_id'):
                hotel_selection = self.env['eds.hotel.selection'].search([
                    ('plan_line_id', '=', vals['plan_line_id']),
                    ('state', '=', 'awarded'), ('awarded_venue_id', '!=', False),
                ], order='id desc', limit=1)
                if hotel_selection:
                    vals['awarded_venue_id'] = hotel_selection.awarded_venue_id.id
                    vals['venue_id'] = hotel_selection.awarded_venue_id.id
        sessions = super().create(vals_list)
        for session in sessions:
            session._sync_plan_line_status()
            session._populate_suggested_enrollments()
        return sessions

    def write(self, vals):
        previous_trainers = {rec.id: set(rec.trainer_ids.ids) for rec in self} if 'trainer_ids' in vals else {}
        if 'status' in vals and not self.env.su:
            raise UserError(_('Use the session workflow actions to change its status.'))
        if vals.get('plan_line_id'):
            plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
            vals = dict(vals)
            vals.setdefault('approved_plan_id', plan_line.plan_id.id)
            vals.setdefault('delivery_method', plan_line.delivery_method)
        if vals.get('awarded_venue_id'):
            vals = dict(vals, venue_id=vals['awarded_venue_id'])
        # Validate that finished or cancelled sessions cannot have schedule/trainers altered
        if any(f in vals for f in ('date_start', 'date_end', 'course_id', 'venue_id', 'trainer_ids')):
            for rec in self:
                if rec.status in ('completed', 'cancelled'):
                    raise UserError(_('Cannot modify schedule, course, venue, or trainers of a %s session.') % rec.status)
        if 'course_id' in vals:
            for rec in self:
                if rec.status != 'draft':
                    raise UserError(_('Cannot change the training program of a session that is already %s.') % rec.status)

        res = super().write(vals)
        if 'plan_line_id' in vals:
            for rec in self:
                rec._populate_suggested_enrollments()

        # Re-synchronize venue booking if dates or venue changed while scheduled/ongoing
        for rec in self:
            if rec.status in ('scheduled', 'ongoing'):
                if any(f in vals for f in ('date_start', 'date_end', 'venue_id')):
                    if rec.venue_id:
                        if rec.booking_id:
                            rec.booking_id.write({
                                'venue_id': rec.venue_id.id,
                                'date_start': rec.date_start,
                                'date_end': rec.date_end,
                            })
                        else:
                            self.env['eds.venue.booking'].create({
                                'venue_id': rec.venue_id.id,
                                'session_id': rec.id,
                                'date_start': rec.date_start,
                                'date_end': rec.date_end,
                                'state': 'confirmed',
                            })
                    elif rec.booking_id:
                        rec.booking_id.action_cancel()

        if any(f in vals for f in ('date_start', 'date_end', 'status')):
            for rec in self:
                rec._sync_plan_line_status()
        if 'capacity' in vals:
            for rec in self:
                rec._promote_waitlisted()
        if 'trainer_ids' in vals:
            for rec in self.filtered(lambda session: session.status in ('scheduled', 'ongoing', 'rescheduled')):
                new_trainers = rec.trainer_ids.filtered(
                    lambda trainer: trainer.id not in previous_trainers.get(rec.id, set()))
                rec._notify_assigned_trainers(new_trainers)
        return res

    def _write_workflow_status(self, status):
        """Internal transition after the public action checks its prerequisites."""
        result = super(EdsSession, self).write({'status': status})
        for session in self:
            session._sync_plan_line_status()
        return result

    def _populate_suggested_enrollments(self):
        for rec in self:
            demand = rec.plan_line_id.course_demand_id
            if not demand:
                continue
            existing = set(rec.enrollment_ids.filtered(
                lambda row: row.state not in ('cancelled', 'declined', 'replaced')
            ).mapped('employee_id').ids)
            to_create = []
            for employee_demand in demand.employee_demand_ids:
                employee_id = employee_demand.employee_id.id
                if employee_id in existing:
                    continue
                existing.add(employee_id)
                to_create.append({
                    'session_id': rec.id,
                    'employee_id': employee_id,
                    'course_demand_employee_id': employee_demand.id,
                    'source_summary': employee_demand.source_summary,
                    'source_count': employee_demand.source_count,
                    'state': 'suggested',
                    'selected': True,
                })
            if to_create:
                self.env['eds.enrollment'].create(to_create)

    def action_refresh_suggested_employees(self):
        self._populate_suggested_enrollments()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_invite_selected(self):
        for rec in self:
            if rec.status not in ('scheduled', 'rescheduled'):
                raise UserError(_('Confirm the session schedule before sending invitations.'))
            rec.enrollment_ids.filtered(
                lambda row: row.selected and row.state == 'suggested').action_invite()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _sync_plan_line_status(self):
        """reflect the session status on its annual plan line."""
        self.ensure_one()
        if not self.plan_line_id:
            return
        line = self.plan_line_id
        if self.status == 'completed':
            line._write_delivery_status('delivered')
        elif self.status == 'cancelled':
            line._write_delivery_status('cancelled')
        elif self.status in ('draft', 'scheduled', 'ongoing', 'rescheduled'):
            if line.status in ('planned', 'delayed', 'cancelled'):
                line._write_delivery_status('scheduled')

    def _get_venue_conflicts(self):
        """Other non-cancelled sessions sharing this venue on an overlapping window."""
        self.ensure_one()
        if not self.venue_id or not self.date_start or not self.date_end \
                or self.status == 'cancelled':
            return self.env['eds.session']
        return self.search([
            ('id', '!=', self.id),
            ('venue_id', '=', self.venue_id.id),
            ('status', 'in', ('scheduled', 'ongoing', 'rescheduled')),
            ('date_start', '<', self.date_end),
            ('date_end', '>', self.date_start),
        ])

    def _get_trainer_conflicts(self):
        """Other sessions sharing any trainer on an overlapping window."""
        self.ensure_one()
        if not self.trainer_ids or not self.date_start or not self.date_end \
                or self.status == 'cancelled':
            return self.env['eds.trainer']
        conflicting_sessions = self.search([
            ('id', '!=', self.id),
            ('status', 'in', ('scheduled', 'ongoing', 'rescheduled')),
            ('trainer_ids', 'in', self.trainer_ids.ids),
            ('date_start', '<', self.date_end),
            ('date_end', '>', self.date_start),
        ])
        return conflicting_sessions.mapped('trainer_ids')

    def _get_blocked_trainer_availability(self):
        """Trainers whose availability register blocks this window ."""
        self.ensure_one()
        if not self.trainer_ids or not self.date_start or not self.date_end:
            return self.env['eds.trainer']
        blocked = self.env['eds.trainer']
        for trainer in self.trainer_ids:
            for slot in trainer.availability_ids.filtered(lambda a: a.state == 'blocked'):
                if slot.date_start < self.date_end and slot.date_end > self.date_start:
                    blocked |= trainer
                    break
        return blocked

    @api.constrains('date_start', 'date_end', 'venue_id', 'trainer_ids', 'status')
    def _check_session_conflicts(self):
        """Blocking enforcement of the venue + trainer conflict rules."""
        for rec in self:
            if rec.status in ('cancelled', 'completed'):
                continue
            venue = rec._get_venue_conflicts()
            if venue:
                raise ValidationError(_(
                    'Venue Conflict: %s is already booked for session %s on an overlapping slot.'
                ) % (rec.venue_id.name, venue[0].name))
            trainers = rec._get_trainer_conflicts()
            if trainers:
                raise ValidationError(_(
                    'Trainer Conflict: trainer(s) %s are already assigned to an overlapping session.'
                ) % ', '.join(trainers.mapped('name')))
            blocked = rec._get_blocked_trainer_availability()
            if blocked:
                raise ValidationError(_(
                    'Trainer Unavailable: trainer(s) %s have a blocked availability record in this period.'
                ) % ', '.join(blocked.mapped('name')))

            # Check internal trainer approved leave
            if 'hr.leave' in self.env.registry:
                for t in rec.trainer_ids.filtered(lambda tr: tr.trainer_type == 'internal' and tr.employee_id):
                    emp = t.employee_id
                    leaves = self.env['hr.leave'].search([
                        ('employee_id', '=', emp.id),
                        ('state', '=', 'validate'),
                        ('date_from', '<', rec.date_end),
                        ('date_to', '>', rec.date_start),
                    ], limit=1)
                    if leaves:
                        raise ValidationError(_(
                            "Trainer On Leave: Internal trainer %s has approved leave from %s to %s."
                        ) % (emp.name, leaves.date_from, leaves.date_to))

    def action_print_all_certificates(self):
        """Generate and download a consolidated multi-page PDF with all certificates for this session."""
        self.ensure_one()
        certs = self.env['eds.certificate'].search([('session_id', '=', self.id)])
        if not certs and self.course_id:
            enrolled_emp_ids = self.enrollment_ids.filtered(lambda e: e.state == 'enrolled').mapped('employee_id').ids
            if enrolled_emp_ids:
                certs = self.env['eds.certificate'].search([
                    ('course_id', '=', self.course_id.id),
                    ('employee_id', 'in', enrolled_emp_ids),
                ])
        if not certs:
            raise UserError(_('No issued certificates found for this training session.'))
        return self.env.ref('employee_development_system.action_report_eds_certificate').report_action(certs)

    # ── Session workflow (EDS-022) ──────────────────────────────
    def action_confirm(self):
        """Draft -> Scheduled: validate conflicts + material gate and book the venue."""
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only draft sessions can be confirmed.'))
            if not rec.course_id and not rec.program_name:
                raise UserError(_('Link the session to a training program first.'))
            if not rec.plan_line_id:
                raise UserError(_(
                    'Select a program on an approved annual plan. Approved unscheduled '
                    'training requests create an addendum program first.'))
            if rec.plan_line_id and rec.plan_line_id.plan_id.state not in ('published', 'amended'):
                raise UserError(_('Sessions may be scheduled only from an approved annual plan.'))
            if rec.plan_line_id.plan_id.company_id != rec.company_id:
                raise UserError(_('The plan program and session must belong to the same company.'))
            if rec.approved_plan_id and rec.plan_line_id and rec.plan_line_id.plan_id != rec.approved_plan_id:
                raise UserError(_('The selected program belongs to another annual plan.'))
            if rec.approved_plan_id and not rec.approved_plan_id.fiscal_year.startswith(rec.session_year):
                raise UserError(_('Select an approved annual plan for the session year %s.') % rec.session_year)
            if not rec.venue_id:
                raise UserError(_('Choose a hotel or venue before confirming the schedule.'))
            if not rec.trainer_ids:
                raise UserError(_('Assign the internal ToT trainer or external organization trainer before confirming the schedule.'))
            if rec.delivery_method == 'internal':
                if rec.trainer_ids.filtered(lambda trainer: trainer.trainer_type != 'internal' or not trainer.tot_certified):
                    raise UserError(_('Internal delivery requires certified internal ToT trainers.'))
            elif not rec.awarded_provider_id:
                raise UserError(_('External delivery requires a selected training organization.'))
            elif rec.trainer_ids.filtered(lambda trainer: trainer.trainer_type != 'external' or
                                          trainer.external_provider_id != rec.awarded_provider_id):
                raise UserError(_('External trainers must belong to the selected training organization.'))
            rec._check_session_conflicts()
            rec._check_material_approval()
            rec._write_workflow_status('scheduled')
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s confirmed and scheduled.') % rec.name)
            rec.action_invite_selected()
            rec._notify_assigned_trainers()
            rec._notify_assessment_coordinators(_('Record pre-training assessment scores before this session starts.'))

    def action_start(self):
        """Scheduled -> Ongoing: delivery has begun.

        Attendance records are auto-created for every enrolled participant so
        L&D staff can record who attended.
        """
        today = fields.Date.today()
        for rec in self:
            if rec.status != 'scheduled':
                raise UserError(_('Only scheduled sessions can be started.'))
            if not rec.date_start:
                raise UserError(_('Session start date is not defined.'))
            if not self.env.context.get('test_skip_date_check') and fields.Date.to_date(rec.date_start) > today:
                raise UserError(_(
                    'Cannot start session %s before its scheduled start date (%s). Today is %s.'
                ) % (rec.name, fields.Date.to_date(rec.date_start), today))
            enrolled = rec.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
            if not enrolled:
                raise UserError(_(
                    'Cannot start session %s: No participants accepted their invitations. Invite and confirm participants before starting.'
                ) % rec.name)
            if not rec.trainer_ids:
                raise UserError(_(
                    'Cannot start session %s: At least one trainer must be assigned.'
                ) % rec.name)
            if not rec.venue_id and not rec.awarded_venue_id:
                raise UserError(_(
                    'Cannot start session %s: A venue must be specified.'
                ) % rec.name)

            rec._write_workflow_status('ongoing')
            rec._ensure_attendance_records()
            rec.message_post(body=_('Session %s started - attendance sheet opened for L&D staff.') % rec.name)

    def action_complete(self):
        """Ongoing -> Completed: delivery finished.

        Posts the attendance summary; enrolled participants transition to completed.
        """
        today = fields.Date.today()
        for rec in self:
            if rec.status != 'ongoing':
                raise UserError(_('Only ongoing sessions can be completed.'))
            if not rec.date_end:
                raise UserError(_('Session end date is not defined.'))
            if not self.env.context.get('test_skip_date_check') and fields.Date.to_date(rec.date_end) > today:
                raise UserError(_(
                    'Cannot complete session %s before its scheduled end date (%s). The training is still in progress.'
                ) % (rec.name, fields.Date.to_date(rec.date_end)))
            if not rec.attendance_ids:
                raise UserError(_(
                    'Cannot complete session %s: No attendance records found. Record participant attendance first.'
                ) % rec.name)

            rec._write_workflow_status('completed')
            present_employee_ids = set(rec.attendance_ids.filtered('attended').mapped('employee_id').ids)
            enrolled = rec.enrollment_ids.filtered(
                lambda e: e.state == 'enrolled' and e.employee_id.id in present_employee_ids
            )
            enrolled.write({'state': 'completed'})
            rec.enrollment_ids.filtered(lambda e: e.state == 'enrolled').write({'state': 'absent'})

            rec.message_post(
                body=_('Session %s completed. L&D has recorded participant attendance.') % rec.name
            )
            rec._sync_plan_line_status()
            rec._distribute_completion_evaluations()
            rec._notify_assessment_coordinators(_('Record post-training assessment scores for completed participants.'))

    def _notify_assessment_coordinators(self, message):
        """Prompt L&D staff, never trainers, to record scored assessments."""
        officer_group = self.env.ref('employee_development_system.group_eds_officer')
        for session in self:
            users = officer_group.user_ids.filtered(
                lambda user: session.company_id in user.company_ids and user.active)
            partners = users.mapped('partner_id')
            if (session.create_uid.has_group('employee_development_system.group_eds_officer')
                    and session.create_uid.partner_id):
                partners |= session.create_uid.partner_id
            if partners:
                session.message_post(body=message, partner_ids=partners.ids)

    def _notify_assigned_trainers(self, trainers=None):
        """Tell registered trainers about their assigned course and schedule."""
        for session in self:
            assigned = trainers if trainers is not None else session.trainer_ids
            partners = assigned.mapped('employee_id.user_id.partner_id') | assigned.mapped('external_partner_id')
            if not partners:
                continue
            course_name = session.course_id.name or session.program_name or session.name
            venue_name = session.venue_id.name or _('To be confirmed')
            session.message_post(
                body=_('You are assigned to deliver %s from %s to %s at %s. Open Training Delivery > My Assigned Sessions to view the schedule.') % (
                    course_name, session.date_start, session.date_end, venue_name),
                partner_ids=partners.ids,
            )

    def _require_ld_delivery_access(self):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            raise AccessError(_('Only L&D staff may view or record attendance and assessment results.'))

    def _distribute_completion_evaluations(self):
        """Open the participant survey and the coach's later behavior review."""
        for session in self:
            instrument = session.course_id.level1_instrument_id or self.env.ref(
                'employee_development_system.inst_level1_standard', raise_if_not_found=False)
            for enrollment in session.enrollment_ids.filtered(lambda e: e.state == 'completed'):
                employee = enrollment.employee_id
                existing = self.env['eds.evaluation.level1'].search([
                    ('session_id', '=', session.id), ('employee_id', '=', employee.id)], limit=1)
                if not existing:
                    questions = instrument.question_ids if instrument and instrument.state == 'published' else self.env['eds.evaluation.instrument.question']
                    existing = self.env['eds.evaluation.level1'].create({
                        'session_id': session.id, 'employee_id': employee.id,
                        'instrument_id': instrument.id if questions else False,
                        'line_ids': [(0, 0, {'question_id': question.id}) for question in questions],
                    })
                partner = employee.user_id.partner_id or employee.work_contact_id
                if partner and existing.state == 'distributed':
                    existing.message_post(
                        body=_('Please complete your training feedback for %s.') % session.name,
                        partner_ids=[partner.id])
                manager = employee.parent_id
                if manager and manager.user_id and not self.env['eds.evaluation.level3'].search([
                        ('session_id', '=', session.id), ('employee_id', '=', employee.id)], limit=1):
                    review = self.env['eds.evaluation.level3'].create({
                        'session_id': session.id, 'employee_id': employee.id,
                        'manager_id': manager.id,
                        'due_date': fields.Date.to_date(session.date_end) + timedelta(days=60),
                        'line_ids': [(0, 0, {'competency_id': competency.id}) for competency in
                                     session.course_id.competency_line_ids.mapped('competency_id')],
                    })
                    review.message_post(
                        body=_('Please review %s’s on-the-job application of %s by %s.') % (
                            employee.name, session.name, review.due_date),
                        partner_ids=[manager.user_id.partner_id.id])

    def action_reschedule(self):
        """Scheduled/Ongoing -> Rescheduled: allow date edits, then confirm again ."""
        for rec in self:
            if rec.status not in ('scheduled', 'ongoing'):
                raise UserError(_('Only scheduled or ongoing sessions can be rescheduled.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec._write_workflow_status('rescheduled')
            rec._notify_participants(_('Session %s has been rescheduled. Check the new dates.')
                                     % rec.name)
            rec._notify_assigned_trainers()

    def action_mark_all_attended(self):
        """Quickly mark all roster records as attended."""
        self._require_ld_delivery_access()
        for rec in self:
            rec._ensure_attendance_records()
            rec.attendance_ids.write({'attended': True})
            rec.message_post(body=_("All session participants marked as attended."))

    def action_open_attendance_import(self):
        """Open the spreadsheet attendance import wizard for this session."""
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Import Attendance Data'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.attendance.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_confirm_reschedule(self):
        """Rescheduled -> Scheduled: re-validate conflicts + material gate, re-book."""
        for rec in self:
            if rec.status != 'rescheduled':
                raise UserError(_('Only rescheduled sessions can be confirmed again.'))
            if not rec.date_start or not rec.date_end:
                raise UserError(_('Set the new session dates before confirming the reschedule.'))
            rec._check_session_conflicts()
            rec._check_material_approval()
            rec._write_workflow_status('scheduled')
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s rescheduled and confirmed .') % rec.name)
            rec._notify_assigned_trainers()

    def action_cancel(self):
        """Cancel the session, release the venue, cancel enrollments and notify ."""
        for rec in self:
            if rec.status in ('completed', 'cancelled'):
                raise UserError(_('Completed or cancelled sessions cannot be cancelled again.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec._write_workflow_status('cancelled')
            for enrollment in rec.enrollment_ids.filtered(
                    lambda e: e.state in ('enrolled', 'waitlisted')):
                enrollment.action_cancel()
            rec._notify_participants(_('Session %s has been cancelled.') % rec.name)

    def _notify_participants(self, message):
        """Notify enrolled participants on reschedule/cancel with direct action link."""
        self.ensure_one()
        action_link = f"/web#id={self.id}&model=eds.session"
        formatted_message = Markup(f"""<p>{escape(str(message))}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">👉 View Training Session</a>
</div>""")
        self.message_post(body=formatted_message)
        partner_ids = self.enrollment_ids.filtered(lambda e: e.state == 'enrolled') \
            .mapped('employee_id').mapped('work_contact_id').filtered('id').ids
        if partner_ids:
            self.message_post(body=formatted_message, partner_ids=partner_ids)

    def _promote_waitlisted(self):
        """FIFO promotion of this session's waitlist (delegates to enrollment)."""
        self.ensure_one()
        if 'eds.enrollment' in self.env.registry:
            self.env['eds.enrollment']._promote_waitlisted(self)

    def action_view_nominations(self):
        self.ensure_one()
        return {
            'name': _('Nominations'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.nomination',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_nominate(self):
        """Open the "Nominate for Session" wizard pre-filled with this session."""
        self.ensure_one()
        return {
            'name': _('Nominate for Session'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.nomination.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_session_id': self.id,
                'session_readonly': True,
            },
        }

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'name': _('Enrollments'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    # ── attendance & delivery helpers (/041/045) ──
    def _check_material_approval(self):
        """a session whose course has materials cannot be confirmed until
        at least one material version is approved (quality + Director PPDD)."""
        self.ensure_one()
        if not self.course_id or not self.course_id.material_ids:
            return
        if not self.course_id.material_ids.filtered('is_approved'):
            raise UserError(_(
                'Training materials must be approved before the schedule is confirmed '
                '(). Approve the materials on training program %s first.')
                % self.course_id.name)

    def _ensure_attendance_records(self):
        """Auto-create the attendance sheet for all enrolled participants."""
        self.ensure_one()
        existing = self.attendance_ids.mapped('employee_id')
        enrolled = self.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
        for enrollment in enrolled:
            if enrollment.employee_id not in existing:
                self.env['eds.session.attendance'].create({
                    'session_id': self.id,
                    'employee_id': enrollment.employee_id.id,
                    'attendance_date': fields.Date.to_date(self.date_start) if self.date_start else fields.Date.context_today(self),
                    'attended': True,
                })

    def action_view_attendance(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Attendance'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.session.attendance',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_export_attendance_xlsx(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if Workbook is None:
            raise UserError(_('The openpyxl library is needed to export Excel attendance.'))
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Attendance'
        sheet['A1'], sheet['B1'] = 'Program', self.course_id.name or self.program_name or ''
        sheet['A2'], sheet['B2'] = 'Session', self.name
        sheet['A3'], sheet['B3'] = 'Trainer', ', '.join(self.trainer_ids.mapped('name'))
        venue = self.venue_id
        sheet['A4'], sheet['B4'] = 'Venue', '%s — %s' % (
            venue.name or '', venue.location or venue.address or '') if venue else ''
        sheet['A5'], sheet['B5'] = 'Dates', '%s to %s' % (self.date_start, self.date_end)
        headers = ['Employee ID', 'Employee Name', 'Work Unit', 'Department', 'Job Position']
        for column, label in enumerate(headers, 1):
            sheet.cell(7, column, label)
        start = fields.Date.to_date(self.date_start)
        end = fields.Date.to_date(self.date_end)
        day = start
        date_columns = []
        while day <= end and len(date_columns) < 366:
            column = len(headers) + len(date_columns) + 1
            cell = sheet.cell(7, column, day)
            cell.number_format = 'yyyy-mm-dd'
            date_columns.append((column, day))
            day += timedelta(days=1)
        if day <= end:
            raise UserError(_('Attendance export supports sessions of up to 366 calendar days.'))
        attendance = {(record.employee_id.id, record.attendance_date): record
                      for record in self.attendance_ids}
        participants = self.enrollment_ids.filtered(
            lambda row: row.state in ('enrolled', 'completed')).sorted(
                key=lambda row: row.employee_id.name or '')
        for row_number, enrollment in enumerate(participants, 8):
            employee = enrollment.employee_id
            values = [employee.id, employee.name,
                      enrollment.work_unit_id.name or '', enrollment.department_id.name or '',
                      enrollment.job_position_id.name or '']
            for column, value in enumerate(values, 1):
                sheet.cell(row_number, column, value)
            for column, attendance_date in date_columns:
                record = attendance.get((employee.id, attendance_date))
                sheet.cell(row_number, column,
                           ('Present' if record.attended else 'Absent') if record else '')
        fill = PatternFill('solid', fgColor='541718')
        for cell in sheet[7]:
            cell.fill = fill
            cell.font = Font(color='FFFFFF', bold=True)
            cell.alignment = Alignment(horizontal='center')
        for key, width in {'A': 16, 'B': 30, 'C': 28, 'D': 25, 'E': 26}.items():
            sheet.column_dimensions[key].width = width
        for column, _day in date_columns:
            sheet.column_dimensions[sheet.cell(7, column).column_letter].width = 17
        sheet.freeze_panes = 'F8'
        output = io.BytesIO()
        workbook.save(output)
        attachment = self.env['ir.attachment'].create({
            'name': 'Attendance_%s.xlsx' % self.name.replace('/', '_'),
            'type': 'binary', 'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': 'eds.session', 'res_id': self.id,
        })
        return {'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % attachment.id,
                'target': 'self'}

    def action_view_feedback(self):
        self.ensure_one()
        return {
            'name': _('Daily Feedback'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.feedback',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_view_assessments(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Pre/Post Assessments'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.assessment',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_view_international_training(self):
        self.ensure_one()
        return {
            'name': _('International Training'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.international.training',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }
