# -*- coding: utf-8 -*-

import base64
import io
from datetime import date, datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape
from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import notify_action
from .eds_currency_policy import validate_delivery_currency
from .eds_employee_projection import safe_employee_web_read


_CONFIRMED_SCHEDULE_FIELDS = frozenset({
    'source_type', 'course_id', 'plan_line_id', 'approved_plan_id',
    'unscheduled_request_id', 'company_id', 'batch_id',
    'date_start', 'date_end', 'response_deadline', 'start_time',
    'duration_hours', 'capacity', 'attendance_mode', 'delivery_method',
    'internal_fallback', 'is_virtual', 'venue_omission_reason',
    'venue_id', 'awarded_venue_id', 'sourcing_id',
    'commitment_required', 'commitment_years', 'commitment_terms',
})
_FIXED_SESSION_SOURCE_FIELDS = frozenset({
    'source_type', 'course_id', 'plan_line_id', 'approved_plan_id',
    'unscheduled_request_id', 'company_id', 'sourcing_id',
})

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Protection
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    Workbook = None


class EdsVenue(models.Model):
    """Registered training venue."""
    _name = 'eds.venue'
    _description = 'Training Venue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
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
    hall_ids = fields.One2many('eds.venue.hall', 'venue_id', string='Training Halls')
    hall_count = fields.Integer(
        string='Number of Halls', compute='_compute_hall_metrics', store=True, readonly=False, tracking=True)
    total_seats = fields.Integer(
        string='Total Seating Capacity', compute='_compute_hall_metrics', store=True)
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

    @api.depends('hall_ids', 'hall_ids.seat_capacity', 'hall_ids.active')
    def _compute_hall_metrics(self):
        for rec in self:
            active_halls = rec.hall_ids.filtered(lambda h: h.active)
            if active_halls:
                rec.hall_count = len(active_halls)
                rec.total_seats = sum(active_halls.mapped('seat_capacity'))
                rec.capacity = rec.total_seats
            else:
                rec.hall_count = rec.hall_count or 0
                rec.total_seats = rec.capacity or 0

    @api.onchange('location_scope')
    def _onchange_location_scope(self):
        if self.location_scope == 'local':
            self.country_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('location_scope', 'local') == 'local':
                vals['country_id'] = False
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if vals.get('location_scope') == 'local':
            vals['country_id'] = False
        return super().write(vals)

    @api.constrains('location_scope', 'country_id')
    def _check_country_scope(self):
        for rec in self:
            if rec.location_scope == 'international' and not rec.country_id:
                raise ValidationError(_('Select a country for an international venue.'))
            if rec.location_scope == 'local' and rec.country_id:
                raise ValidationError(_('Country applies only to international venues.'))

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


class EdsVenueHall(models.Model):
    """Specific hall / room inside a training venue."""
    _name = 'eds.venue.hall'
    _description = 'Training Venue Hall'
    _order = 'sequence, name, id'
    _rec_name = 'name'

    name = fields.Char(string='Hall / Room Name', required=True)
    venue_id = fields.Many2one('eds.venue', string='Venue', required=True, ondelete='cascade', index=True)
    seat_capacity = fields.Integer(string='Number of Seats / Capacity', required=True, default=30)
    sequence = fields.Integer(string='Sequence', default=10)
    hall_type = fields.Selection([
        ('conference', 'Conference Hall'),
        ('auditorium', 'Auditorium / Theater'),
        ('meeting', 'Meeting / Workshop Room'),
        ('computer_lab', 'Computer Lab'),
        ('boardroom', 'Executive Boardroom'),
        ('syndicate', 'Syndicate / Breakout Room'),
        ('other', 'Other Facility Space'),
    ], string='Hall Type', default='conference')
    floor = fields.Char(string='Floor / Wing / Block')
    facilities = fields.Text(string='Facilities & Equipment (Audio/Visual, Projector, WiFi)')
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')

    @api.depends('name', 'seat_capacity')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} ({rec.seat_capacity} seats)" if rec.seat_capacity else (rec.name or '')

    @api.constrains('seat_capacity')
    def _check_seat_capacity(self):
        for rec in self:
            if rec.seat_capacity <= 0:
                raise ValidationError(_('Hall seat capacity must be greater than zero.'))


class EdsVenueBooking(models.Model):
    """Booking of a venue for a session.

    A named hall has one schedulable space. A hotel may host concurrent sessions
    in different rooms, so hotel bookings do not conflict at the venue level.
    """
    _name = 'eds.venue.booking'
    _description = 'Venue Booking'
    _order = 'create_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    venue_id = fields.Many2one('eds.venue', string='Venue', required=True, ondelete='cascade',
                               index=True)
    hall_id = fields.Many2one('eds.venue.hall', string='Assigned Hall / Room',
                             domain="[('venue_id', '=', venue_id), ('active', '=', True)]",
                             ondelete='set null')
    hall_seats = fields.Integer(string='Hall Capacity', related='hall_id.seat_capacity', readonly=True)
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

    @api.constrains('venue_id', 'hall_id', 'date_start', 'date_end', 'state')
    def _check_venue_conflict(self):
        """Prevent double-booking a venue or specific hall."""
        for rec in self:
            if rec.state == 'cancelled':
                continue
            domain = [
                ('id', '!=', rec.id),
                ('venue_id', '=', rec.venue_id.id),
                ('state', '!=', 'cancelled'),
                ('date_start', '<', rec.date_end),
                ('date_end', '>', rec.date_start),
            ]
            if rec.hall_id:
                domain.append(('hall_id', '=', rec.hall_id.id))
            elif rec.venue_id.venue_type == 'hotel':
                continue
            conflicting = self.search(domain, limit=1)
            if conflicting:
                target_desc = f"{rec.venue_id.name} ({rec.hall_id.name})" if rec.hall_id else rec.venue_id.name
                raise ValidationError(_(
                    'Venue / Hall Conflict: %s is already booked from %s to %s '
                    '(booking %s). Choose a different slot, hall, or venue.')
                    % (target_desc, conflicting.date_start, conflicting.date_end,
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
            if rec.session_id and rec.session_id.status != 'cancelled':
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

    def write(self, vals):
        if 'course_id' in vals:
            for batch in self:
                if (vals['course_id'] or False) != (batch.course_id.id or False) and batch.session_ids.filtered(
                        lambda session: session.status != 'draft'):
                    raise UserError(_(
                        'A cohort linked to a confirmed session cannot change its training program.'))
        return super().write(vals)

    def unlink(self):
        if any(batch.session_ids.filtered(lambda session: session.status != 'draft')
               for batch in self):
            raise UserError(_(
                'A cohort linked to a confirmed session cannot be deleted.'))
        return super().unlink()

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
    """A scheduled delivery of a course.

    Carries the venue, trainers (constrained to the trainer register with matching
    competencies and availability - ) and dates; enforces venue and trainer
    conflict checks, and notifies participants on reschedule or
    cancellation . Sessions are created from annual-plan lines on
    publication and feed the planned-vs-actual variance.
    """
    _name = 'eds.session'
    _description = 'Training Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _rec_name = 'name'

    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        """Resolve session forms by role before Odoo caches the requested view."""
        if view_type == 'form':
            user = self.env.user
            staff_groups = (
                'employee_development_system.group_eds_officer',
                'employee_development_system.group_eds_manager',
                'employee_development_system.group_eds_admin',
                'employee_development_system.group_eds_executive',
            )
            if not any(user.has_group(group) for group in staff_groups):
                view_xmlid = (
                    'employee_development_system.view_eds_session_trainer_form'
                    if user.has_group('employee_development_system.group_eds_trainer')
                    else 'employee_development_system.view_eds_session_employee_form'
                )
                role_view = self.env.ref(view_xmlid, raise_if_not_found=False)
                if role_view:
                    view_id = role_view.id
        return super().get_view(view_id=view_id, view_type=view_type, **options)

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    source_type = fields.Selection([
        ('annual_plan', 'Approved Annual Plan'),
        ('unscheduled', 'Approved Unscheduled Request'),
    ], string='Session Source', default='annual_plan', required=True, tracking=True)
    course_id = fields.Many2one('eds.course', string='Training Program', tracking=True)
    program_name = fields.Char(string='Program Name',
                               readonly=True, help='Catalog course name retained for reports.')
    plan_line_id = fields.Many2one('eds.annual.plan.line', string='Annual Plan Line',
                                   ondelete='set null', index=True,
                                   help='Links the session to the annual plan for variance '
                                        'monitoring.')
    approved_plan_id = fields.Many2one(
        'eds.annual.plan', string='Approved Annual Plan',
        domain="[('state', 'in', ('published', 'amended')), ('company_id', '=', company_id)]",
        help='Select the published plan whose program will be delivered.')
    unscheduled_request_id = fields.Many2one(
        'eds.unscheduled.request', string='Approved Unscheduled Request',
        domain="[('state', '=', 'approved'), ('course_id', '!=', False), ('company_id', '=', company_id)]",
        ondelete='restrict', index=True,
        help='Select an approved request after its training program is in the course catalog.')
    session_year = fields.Char(string='Session Year', compute='_compute_session_year')
    delivery_method = fields.Selection([
        ('internal', 'Internal / ToT'),
        ('local_external', 'Local External'),
        ('international', 'International'),
        ('elearning', 'E-Learning'),
    ], string='Execution Delivery Type', default='internal', required=True)
    planned_delivery_method = fields.Selection(
        related='plan_line_id.delivery_method', string='Planned Delivery Type', readonly=True)
    internal_fallback = fields.Boolean(
        string='Use Internal Delivery Instead', tracking=True,
        help='Use a certified internal trainer when no provider has been awarded for an external program.')
    internal_fallback_reason = fields.Char(string='Reason for Internal Delivery')
    batch_id = fields.Many2one('eds.batch', string='Batch / Cohort', ondelete='set null')
    date_start = fields.Datetime(string='Start Date', required=True, index=True, tracking=True)
    response_deadline = fields.Datetime(
        string='Invitation Response Deadline', compute='_compute_response_deadline',
        store=True, readonly=False, tracking=True,
        help='Employees must respond by this time. Defaults to two days before the session starts.')
    date_end = fields.Datetime(string='End Date', required=True, tracking=True)
    attendance_mode = fields.Selection([
        ('daily', 'Once per Day'),
        ('split', 'Morning and Afternoon'),
    ], string='Attendance Recording', default='daily', required=True,
        help='Choose one attendance mark for each scheduled day, or separate morning and afternoon marks.')
    start_time = fields.Float(string='Start Time', default=8.5,
                              help='Start hour of the first day (e.g. 8.5 = 08:30).')
    duration_hours = fields.Float(string='Duration (Hours)', default=8.0, tracking=True)
    is_virtual = fields.Boolean(
        string='No Hotel Needed', tracking=True,
        help='Use when no physical hotel or venue is needed, such as online training. Explain why.')
    online_meeting_platform = fields.Selection([
        ('google_meet', 'Google Meet'),
        ('zoom', 'Zoom'),
        ('teams', 'Microsoft Teams'),
        ('other', 'Other Video / Call Platform'),
    ], string='Online Meeting Platform', default='google_meet', tracking=True)
    online_meeting_url = fields.Char(
        string='Online Meeting Link / Details', tracking=True)
    venue_omission_reason = fields.Text(
        string='Reason for No Hotel / Venue', tracking=True,
        help='Required when saving a session without a hotel or venue.')
    venue_id = fields.Many2one('eds.venue', string='Venue', ondelete='restrict',
                               tracking=True, domain="[('active', '=', True)]")
    hall_id = fields.Many2one('eds.venue.hall', string='Assigned Hall / Room',
                             domain="[('venue_id', '=', venue_id), ('active', '=', True)]",
                             tracking=True, ondelete='set null')
    hall_seats = fields.Integer(string='Hall Capacity', related='hall_id.seat_capacity', readonly=True)
    allowed_venue_ids = fields.Many2many(
        'eds.venue', compute='_compute_allowed_venue_ids',
        string='Awarded Venues for This Program',
        help='Venues awarded for this approved plan program or unscheduled request.')
    trainer_ids = fields.Many2many(
        'eds.trainer', 'eds_session_trainer_rel', 'session_id', 'trainer_id',
        string='Trainers', tracking=True,
        help='Choose active internal ToT trainers, or trainers registered with the awarded provider.')
    trainer_count = fields.Integer(string='Trainer Count', compute='_compute_trainer_count', store=True)
    capacity = fields.Integer(
        string='Capacity', default=lambda self: self._get_default_capacity(),
        help='Maximum number of participants (default 25-30 from EDS settings).')

    # Awarded Sourcing & Venue Winners
    awarded_provider_id = fields.Many2one(
        'eds.external.provider', string='Awarded Training Provider / Vendor', tracking=True,
        help='Vendor selected / awarded for delivering this course session.')
    allowed_provider_ids = fields.Many2many(
        'eds.external.provider', compute='_compute_allowed_provider_ids',
        string='Awarded Providers for This Program')
    sourcing_id = fields.Many2one(
        'eds.course.vendor.selection', string='Provider Sourcing', index=True, tracking=True,
        ondelete='restrict',
        help='The provider sourcing record shared by deliveries of this approved program.')
    awarded_bid_id = fields.Many2one(
        'eds.course.vendor.line', string='Selected Awarded Bid', index=True,
        tracking=True, ondelete='restrict',
        help='Choose one awarded bid for this delivery. An awarded bid may serve multiple sessions.')
    provider_change_reason = fields.Text(
        string='Provider Change Justification', copy=False,
        help='Required when changing the provider after a session is scheduled. Each change is retained in the chatter.')
    decision_remark = fields.Text(
        string='Decision / Exception Remark', tracking=True,
        help='Explain a material session choice or unplanned operational change.')
    commitment_required = fields.Boolean(
        string='Requires Training Commitment', tracking=True,
        help='Employees must acknowledge the stated service commitment when accepting an invitation.')
    commitment_years = fields.Integer(
        string='Commitment Duration (Years)', tracking=True)
    commitment_terms = fields.Text(
        string='Commitment Terms / Resignation Instructions', tracking=True,
        help='Explain the commitment and what an employee should do if they cannot fulfill it.')
    training_commitment_ids = fields.One2many(
        'training.commitment', 'eds_session_id', string='Employee Commitments', readonly=True)
    awarded_venue_id = fields.Many2one(
        'eds.venue', string='Awarded Hotel / Venue', tracking=True,
        help='Hotel or venue selected / awarded for hosting this session.')
    omitted_suggestion_employee_ids = fields.Many2many(
        'hr.employee', 'eds_session_omitted_employee_rel', 'session_id', 'employee_id',
        string='Removed Suggested Employees', copy=False,
        help='Employees removed from the draft roster stay removed when suggestions are refreshed.')

    @api.model
    def _sourcing_for_plan_line(self, plan_line, unscheduled_request=None):
        request = unscheduled_request or (plan_line.unscheduled_request_id if plan_line else False)
        if request:
            domain = [('unscheduled_request_id', '=', request.id)]
        elif plan_line:
            domain = [('plan_line_id', '=', plan_line.id), ('source_type', '=', 'annual_plan')]
        else:
            return self.env['eds.course.vendor.selection'], self.env['eds.hotel.selection']
        sourcing = self.env['eds.course.vendor.selection'].search(
            domain + [('state', '=', 'awarded')], order='id desc', limit=1)
        hotel = self.env['eds.hotel.selection'].search(
            domain + [('state', '=', 'awarded'), ('awarded_venue_id', '!=', False)],
            order='id desc', limit=1)
        if request and plan_line:
            # Existing addendum sourcing predates the explicit request source.
            if not sourcing:
                sourcing = self.env['eds.course.vendor.selection'].search([
                    ('plan_line_id', '=', plan_line.id), ('state', '=', 'awarded'),
                ], order='id desc', limit=1)
            if not hotel:
                hotel = self.env['eds.hotel.selection'].search([
                    ('plan_line_id', '=', plan_line.id), ('state', '=', 'awarded'),
                    ('awarded_venue_id', '!=', False),
                ], order='id desc', limit=1)
        return sourcing, hotel

    is_external_delivery = fields.Boolean(
        string='External Delivery', compute='_compute_is_external_delivery')

    @api.depends('delivery_method', 'awarded_provider_id')
    def _compute_is_external_delivery(self):
        for rec in self:
            rec.is_external_delivery = bool(
                rec.delivery_method in ('local_external', 'international') or rec.awarded_provider_id)

    @api.depends('sourcing_id', 'sourcing_id.line_ids.status',
                 'sourcing_id.line_ids.vendor_id')
    def _compute_allowed_provider_ids(self):
        for session in self:
            session.allowed_provider_ids = session.sourcing_id.line_ids.filtered(
                lambda bid: bid.status == 'awarded').mapped('vendor_id')

    @api.model
    def _awarded_bid_for_provider(self, sourcing, provider):
        """Resolve the single awarded bid behind a provider selection."""
        if not provider:
            return self.env['eds.course.vendor.line']
        bid = sourcing.line_ids.filtered(
            lambda line: line.status == 'awarded' and line.vendor_id == provider)[:1]
        if not bid:
            raise ValidationError(_(
                'Select a training provider awarded for this program or request.'))
        return bid

    def _get_allowed_awarded_venues(self):
        """Return active venue awards for this session's approved source only."""
        self.ensure_one()
        selection_model = self.env['eds.hotel.selection'].sudo()
        request = (self.unscheduled_request_id or self.plan_line_id.unscheduled_request_id
                   if self.source_type == 'unscheduled' else False)
        if request:
            selections = selection_model.search([
                ('source_type', '=', 'unscheduled'),
                ('unscheduled_request_id', '=', request.id),
                ('state', '=', 'awarded'),
                ('awarded_venue_id', '!=', False),
            ])
            if not selections and self.plan_line_id:
                # Older addendum awards were linked to the plan line directly.
                selections = selection_model.search([
                    ('plan_line_id', '=', self.plan_line_id.id),
                    ('state', '=', 'awarded'),
                    ('awarded_venue_id', '!=', False),
                ])
        elif self.source_type == 'annual_plan' and self.plan_line_id:
            selections = selection_model.search([
                ('source_type', '=', 'annual_plan'),
                ('plan_line_id', '=', self.plan_line_id.id),
                ('state', '=', 'awarded'),
                ('awarded_venue_id', '!=', False),
            ])
            if not selections:
                # Venue sourcing is unique per approved plan and course, even if
                # several plan lines happen to reference the same course.
                selections = selection_model.search([
                    ('source_type', '=', 'annual_plan'),
                    ('annual_plan_id', '=', self.plan_line_id.plan_id.id),
                    ('course_id', '=', self.plan_line_id.course_id.id),
                    ('state', '=', 'awarded'),
                    ('awarded_venue_id', '!=', False),
                ])
        else:
            return self.env['eds.venue']
        venues = selections.mapped('awarded_venue_ids') | selections.mapped('awarded_venue_id')
        return venues.filtered('active')

    @api.depends('source_type', 'plan_line_id', 'unscheduled_request_id')
    def _compute_allowed_venue_ids(self):
        for session in self:
            session.allowed_venue_ids = session._get_allowed_awarded_venues()

    @api.constrains('venue_id', 'delivery_method', 'plan_line_id',
                    'unscheduled_request_id', 'source_type')
    def _check_selected_venue_award(self):
        for session in self:
            venue = session.venue_id
            if not venue or not (session.plan_line_id or session.unscheduled_request_id):
                continue
            if not venue.active:
                raise ValidationError(_('Choose an active training venue.'))
            if session.delivery_method == 'internal' and venue.venue_type == 'internal_hall':
                continue
            if venue.id not in session._get_allowed_awarded_venues().ids:
                raise ValidationError(_(
                    'Choose a venue awarded for this approved program or request. '
                    'Bank internal facilities may be selected directly for internal delivery.'))

    @api.model
    def _sourcing_values_for_plan_line(self, plan_line, unscheduled_request=None,
                                       preferred_bid=None, preferred_provider=None):
        request = unscheduled_request or (plan_line.unscheduled_request_id if plan_line else False)
        sourcing, hotel = self._sourcing_for_plan_line(plan_line, request)
        method = (sourcing.delivery_method or (request.delivery_method if request else False)
                  or (plan_line.delivery_method if plan_line else 'internal'))
        awards = sourcing.line_ids.filtered(lambda line: line.status == 'awarded')
        if preferred_provider:
            preferred_bid = self._awarded_bid_for_provider(sourcing, preferred_provider)
        elif preferred_bid and preferred_bid not in awards:
            raise ValidationError(_('The selected bid is not awarded under this provider sourcing.'))
        winner = (preferred_bid if preferred_bid and preferred_bid in awards else
                  awards if len(awards) == 1 else self.env['eds.course.vendor.line'])
        values = {
            'delivery_method': method,
            'sourcing_id': sourcing.id or False,
            'awarded_bid_id': winner.id if method != 'internal' else False,
            'awarded_provider_id': winner.vendor_id.id if method != 'internal' else False,
            'awarded_venue_id': hotel.awarded_venue_id.id or False,
        }
        if hotel:
            values['venue_id'] = hotel.awarded_venue_id.id
        return values

    def _sync_sourcing_from_plan_line(self):
        for session in self.filtered(lambda rec: (rec.plan_line_id or rec.unscheduled_request_id)
                                     and rec.status == 'draft'):
            values = session._sourcing_values_for_plan_line(
                session.plan_line_id, session.unscheduled_request_id,
                session.awarded_bid_id, session.awarded_provider_id)
            if session.internal_fallback:
                sourcing = session.env['eds.course.vendor.selection'].browse(
                    values['sourcing_id'])
                if (sourcing.line_ids.filtered(lambda bid: bid.status == 'awarded')
                        or values['delivery_method'] == 'internal'):
                    values.update({'internal_fallback': False, 'internal_fallback_reason': False})
                else:
                    values.update({'delivery_method': 'internal', 'awarded_bid_id': False,
                                   'awarded_provider_id': False})
            if session.is_virtual or session.venue_id:
                # Keep the user's optional virtual venue or explicit physical choice.
                # Confirmation checks that an external venue was actually awarded.
                values.pop('venue_id', None)
            elif not values['awarded_venue_id'] and session.venue_id == session.awarded_venue_id:
                values['venue_id'] = False
            if values['delivery_method'] == 'internal':
                values['trainer_ids'] = [(6, 0, session.trainer_ids.filtered(
                    lambda trainer: trainer.trainer_type == 'internal' and trainer.tot_certified).ids)]
            else:
                sourcing, _hotel = session._sourcing_for_plan_line(
                    session.plan_line_id, session.unscheduled_request_id)
                eligible = session.trainer_ids.filtered(
                    lambda trainer: trainer.state == 'active'
                    and trainer.trainer_type == 'external'
                    and trainer.external_provider_id.id == values['awarded_provider_id'])
                if not eligible:
                    eligible = sourcing.line_ids.filtered(
                        lambda line: line.status == 'awarded').trainer_id.filtered(
                            lambda trainer: trainer.state == 'active'
                            and trainer.trainer_type == 'external'
                            and trainer.external_provider_id.id == values['awarded_provider_id'])
                values['trainer_ids'] = [(6, 0, eligible.ids)]
            session.with_context(eds_sync_sourcing=True).write(values)
            session._deselect_already_allocated_suggestions()

    @api.onchange('awarded_venue_id')
    def _onchange_awarded_venue_id(self):
        if self.awarded_venue_id and not self.is_virtual:
            self.venue_id = self.awarded_venue_id

    @api.onchange('is_virtual')
    def _onchange_is_virtual(self):
        if self.is_virtual:
            self.venue_id = False
            self.hall_id = False
        elif self.awarded_venue_id:
            self.venue_id = self.awarded_venue_id

    @api.onchange('venue_id')
    def _onchange_venue_id_reset_hall(self):
        if self.venue_id and self.hall_id and self.hall_id.venue_id != self.venue_id:
            self.hall_id = False
        if self.venue_id and not self.hall_id and self.venue_id.capacity:
            self.capacity = self.venue_id.capacity

    @api.onchange('hall_id')
    def _onchange_hall_id_sync_capacity(self):
        if self.hall_id and self.hall_id.seat_capacity:
            self.capacity = self.hall_id.seat_capacity

    @api.depends('date_start')
    def _compute_session_year(self):
        for rec in self:
            rec.session_year = str(fields.Date.to_date(rec.date_start).year) if rec.date_start else str(fields.Date.context_today(rec).year)

    @api.onchange('source_type')
    def _onchange_source_type(self):
        self.plan_line_id = False
        self.approved_plan_id = False
        self.unscheduled_request_id = False
        self.course_id = False
        self.program_name = False
        self.awarded_provider_id = False
        self.sourcing_id = False
        self.awarded_bid_id = False
        self.awarded_venue_id = False
        self.venue_id = False
        self.trainer_ids = False
        self.internal_fallback = False
        self.internal_fallback_reason = False
        self.enrollment_ids = [(5, 0, 0)]
        self._onchange_certificate_course_defaults()

    @api.onchange('approved_plan_id')
    def _onchange_approved_plan_id(self):
        if self.plan_line_id.plan_id != self.approved_plan_id:
            self.plan_line_id = False
            self.course_id = False
            self.program_name = False
            self.sourcing_id = False
            self.awarded_bid_id = False
            self.awarded_provider_id = False
            self.awarded_venue_id = False
            self.venue_id = False
            self._onchange_certificate_course_defaults()

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.plan_line_id:
            self.venue_id = False
            self.enrollment_ids = [(5, 0, 0)]
            self.internal_fallback = False
            self.internal_fallback_reason = False
            self.approved_plan_id = self.plan_line_id.plan_id
            self.course_id = self.plan_line_id.course_id
            self.program_name = self.course_id.name
            self._onchange_certificate_course_defaults()
            self._onchange_sourcing_from_plan_line()
        elif self.source_type == 'annual_plan':
            self.course_id = False
            self.program_name = False
            self._onchange_certificate_course_defaults()
            self.awarded_provider_id = False
            self.sourcing_id = False
            self.awarded_bid_id = False
            self.awarded_venue_id = False
            self.venue_id = False
            self.trainer_ids = False

    @api.onchange('unscheduled_request_id')
    def _onchange_unscheduled_request_id(self):
        request = self.unscheduled_request_id
        if request:
            self.venue_id = False
            self.enrollment_ids = [(5, 0, 0)]
            self.internal_fallback = False
            self.internal_fallback_reason = False
            self.plan_line_id = request.plan_line_ids[:1]
            self.approved_plan_id = request.annual_plan_id
            self.course_id = request.course_id
            self.program_name = request.course_id.name
            self._onchange_certificate_course_defaults()
            if self.plan_line_id:
                self._onchange_sourcing_from_plan_line()
            else:
                self._onchange_sourcing_from_plan_line()
        elif self.source_type == 'unscheduled':
            self.plan_line_id = False
            self.approved_plan_id = False
            self.course_id = False
            self.program_name = False
            self.sourcing_id = False
            self.awarded_bid_id = False
            self.awarded_provider_id = False
            self.awarded_venue_id = False
            self.venue_id = False
            self._onchange_certificate_course_defaults()

    @api.onchange('delivery_method', 'awarded_provider_id')
    def _onchange_delivery_provider(self):
        if self.delivery_method == 'internal':
            self.awarded_provider_id = False
            self.awarded_bid_id = False
            self.trainer_ids = self.trainer_ids.filtered(
                lambda trainer: trainer.trainer_type == 'internal' and trainer.tot_certified)
        else:
            if not self.awarded_provider_id:
                self.awarded_bid_id = False
                self.trainer_ids = False
                return
            bid = self.sourcing_id.line_ids.filtered(
                lambda line: line.status == 'awarded'
                and line.vendor_id == self.awarded_provider_id)[:1]
            self.awarded_bid_id = bid
            self.trainer_ids = self.trainer_ids.filtered(
                lambda trainer: trainer.state == 'active'
                and trainer.trainer_type == 'external' and
                trainer.external_provider_id == self.awarded_provider_id)
            if not self.trainer_ids and bid.trainer_id and bid.trainer_id.state == 'active':
                self.trainer_ids = bid.trainer_id

    @api.onchange('awarded_bid_id')
    def _onchange_awarded_bid_id(self):
        self.awarded_provider_id = self.awarded_bid_id.vendor_id
        self.trainer_ids = self.trainer_ids.filtered(
            lambda trainer: trainer.state == 'active' and trainer.trainer_type == 'external'
            and trainer.external_provider_id == self.awarded_provider_id)
        if (not self.trainer_ids and self.awarded_bid_id.trainer_id
                and self.awarded_bid_id.trainer_id.state == 'active'):
            self.trainer_ids = self.awarded_bid_id.trainer_id

    def _onchange_sourcing_from_plan_line(self):
        if not self.plan_line_id and not self.unscheduled_request_id:
            return
        sourcing, _hotel = self._sourcing_for_plan_line(
            self.plan_line_id, self.unscheduled_request_id)
        preferred_bid = (self.awarded_bid_id
                         if self.awarded_bid_id.selection_id == sourcing else False)
        preferred_provider = (self.awarded_provider_id
                              if self.awarded_provider_id in sourcing.awarded_vendor_ids else False)
        values = self._sourcing_values_for_plan_line(
            self.plan_line_id, self.unscheduled_request_id,
            preferred_bid, preferred_provider)
        sourcing = self.env['eds.course.vendor.selection'].browse(values['sourcing_id'])
        has_awards = bool(sourcing.line_ids.filtered(lambda bid: bid.status == 'awarded'))
        if self.internal_fallback and not has_awards and values['delivery_method'] != 'internal':
            values.update({'delivery_method': 'internal', 'awarded_bid_id': False,
                           'awarded_provider_id': False})
        self.delivery_method = values['delivery_method']
        self.sourcing_id = values['sourcing_id']
        self.awarded_bid_id = values['awarded_bid_id']
        self.awarded_provider_id = values['awarded_provider_id']
        self.awarded_venue_id = values['awarded_venue_id']
        if values['awarded_venue_id'] and not self.is_virtual:
            self.venue_id = values['awarded_venue_id']
        elif (self.is_virtual or self.delivery_method != 'internal'
              or self.venue_id.venue_type != 'internal_hall'):
            self.venue_id = False
        if self.delivery_method != 'internal':
            winner = self.awarded_bid_id
            eligible = self.trainer_ids.filtered(
                lambda trainer: trainer.state == 'active' and trainer.trainer_type == 'external'
                and trainer.external_provider_id == self.awarded_provider_id)
            self.trainer_ids = eligible or winner.trainer_id.filtered(
                lambda trainer: trainer.state == 'active' and trainer.trainer_type == 'external'
                and trainer.external_provider_id == self.awarded_provider_id)
        else:
            self.trainer_ids = self.trainer_ids.filtered(
                lambda trainer: trainer.trainer_type == 'internal' and trainer.tot_certified)

    @api.onchange('internal_fallback')
    def _onchange_internal_fallback(self):
        if not self.internal_fallback:
            self.internal_fallback_reason = False
        self._onchange_sourcing_from_plan_line()

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

    def _course_certificate_values(self, course):
        return {
            field_name: (course[field_name] or False) if course else False
            for field_name in (
                'certificate_title', 'certificate_body_text',
                'certificate_signatory_name', 'certificate_signatory_title')
        }

    def _onchange_certificate_course_defaults(self):
        for session in self:
            for field_name, value in session._course_certificate_values(session.course_id).items():
                session[field_name] = value

    def action_preview_certificate(self):
        self.ensure_one()
        return self.env.ref(
            'employee_development_system.action_report_eds_session_certificate_preview').report_action(self)

    nomination_ids = fields.One2many('eds.nomination', 'session_id', string='Nominations')
    nomination_count = fields.Integer(string='Nomination Count', compute='_compute_nomination_count')
    enrollment_ids = fields.One2many('eds.enrollment', 'session_id', string='Enrollments')
    # The form only needs IDs for domains. A relation to hr.employee would
    # trigger HR record-rule checks while computing or reading this helper.
    enrolled_employee_ids = fields.Json(
        compute='_compute_enrolled_employee_ids', compute_sudo=True,
        string='Enrolled Employee IDs',
        help='Employee IDs confirmed or attended for this session, used by form filters.')
    enrolled_count = fields.Integer(string='Enrolled', compute='_compute_enrollment_counts')
    invited_count = fields.Integer(string='Invited', compute='_compute_enrollment_counts')
    declined_count = fields.Integer(string='Declined', compute='_compute_enrollment_counts')
    replaced_count = fields.Integer(string='Replaced', compute='_compute_enrollment_counts')
    expired_count = fields.Integer(string='Expired', compute='_compute_enrollment_counts')
    roster_status_summary = fields.Html(
        string='Roster Status', compute='_compute_enrollment_counts', sanitize=False)
    attendance_matrix_html = fields.Html(
        string='Attendance Matrix', compute='_compute_attendance_matrix_html', sanitize=False)
    planned_participant_count = fields.Integer(
        string='Planned Participants', compute='_compute_planned_participant_count')
    pending_count = fields.Integer(string='Pending Responses', compute='_compute_enrollment_counts')
    waitlist_count = fields.Integer(string='Waitlisted', compute='_compute_enrollment_counts')
    status = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rescheduled', 'Rescheduled'),
    ], string='Status', default='draft', required=True, tracking=True)
    booking_ids = fields.One2many('eds.venue.booking', 'session_id', string='Venue Bookings')
    booking_id = fields.Many2one('eds.venue.booking', string='Current Booking',
                                 compute='_compute_booking_id')

    # ── attendance & delivery tracking ──
    attendance_ids = fields.One2many(
        'eds.session.attendance', 'session_id', string='Attendance Records',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    attendance_summary_ids = fields.One2many(
        'eds.session.attendance.summary', 'session_id', string='Attendance Summary & Report',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    cost_ids = fields.One2many('eds.cost', 'session_id', string='Actual Costs')
    attendance_count = fields.Integer(
        string='Attendance Marks', compute='_compute_delivery_counts',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    attendance_rate = fields.Float(
        string='Session Attendance %', compute='_compute_attendance_rate', store=True,
        digits=(5, 2),
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive',
        help='Present marks divided by expected marks for accepted participants and scheduled periods.')
    feedback_ids = fields.One2many('eds.feedback', 'session_id', string='Daily Feedback')
    feedback_count = fields.Integer(string='Feedback', compute='_compute_delivery_counts')
    assessment_ids = fields.One2many(
        'eds.assessment', 'session_id', string='Assessments',
        groups='employee_development_system.group_eds_officer,employee_development_system.group_eds_executive')
    pre_assessment_question_ids = fields.One2many(
        'eds.assessment.question', 'session_id', string='Pre-Assessment Questions',
        domain=[('assessment_type', '=', 'pre')],
        groups='employee_development_system.group_eds_officer')
    post_assessment_question_ids = fields.One2many(
        'eds.assessment.question', 'session_id', string='Post-Assessment Questions',
        domain=[('assessment_type', '=', 'post')],
        groups='employee_development_system.group_eds_officer')
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

    @api.depends('date_start')
    def _compute_response_deadline(self):
        for rec in self:
            rec.response_deadline = (
                rec.date_start - timedelta(days=2) if rec.date_start else False)

    @api.constrains('date_start', 'response_deadline')
    def _check_response_deadline(self):
        for rec in self:
            if rec.date_start and rec.response_deadline and rec.response_deadline >= rec.date_start:
                raise ValidationError(_('The invitation response deadline must be before the session starts.'))

    @api.constrains('capacity')
    def _check_capacity_positive(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_('Session capacity must be greater than zero.'))

    @api.model
    def _get_default_capacity(self):
        """Default class size from EDS settings (BRD §4.2: 25–30 per cohort)."""
        return self._get_int_param('eds.default_class_capacity', 30)

    @api.depends('booking_ids', 'booking_ids.state')
    def _compute_booking_id(self):
        for rec in self:
            active = rec.booking_ids.filtered(lambda b: b.state != 'cancelled')
            rec.booking_id = active[0] if active else False

    @api.depends('trainer_ids')
    def _compute_trainer_count(self):
        for rec in self:
            rec.trainer_count = len(rec.trainer_ids)

    @api.depends('enrollment_ids.state', 'enrollment_ids.employee_id',
                 'enrollment_ids.response_date', 'enrollment_ids.nomination_id.employee_confirmed')
    def _compute_enrolled_employee_ids(self):
        for rec in self:
            employee_ids = rec._accepted_attendance_enrollments().mapped('employee_id').ids
            # Odoo serializes an empty JSON list as False; [0] keeps the form
            # domain valid and cannot match an actual employee.
            rec.enrolled_employee_ids = employee_ids or [0]

    def _accepted_attendance_enrollments(self):
        self.ensure_one()
        return self.enrollment_ids.filtered(
            lambda row: row.state in ('enrolled', 'completed', 'incomplete', 'absent')
            and (not row.nomination_id or row.response_date
                 or row.nomination_id.employee_confirmed == 'confirmed'))

    def _attendance_roster_enrollments(self):
        """Employees shown on the session roster, including selected draft suggestions."""
        self.ensure_one()
        return self.enrollment_ids.filtered(
            lambda row: (row.state == 'suggested' and row.selected)
            or row.state in ('invited', 'enrolled', 'completed', 'incomplete', 'absent'))

    @api.depends('plan_line_id.planned_participants', 'unscheduled_request_id.participant_count')
    def _compute_planned_participant_count(self):
        for rec in self:
            rec.planned_participant_count = (
                rec.plan_line_id.planned_participants if rec.plan_line_id
                else rec.unscheduled_request_id.participant_count if rec.unscheduled_request_id
                else 0)

    @api.depends('enrollment_ids', 'enrollment_ids.state', 'enrollment_ids.response_date',
                 'enrollment_ids.nomination_id.employee_confirmed')
    def _compute_enrollment_counts(self):
        """Show employee responses, independently of capacity and planned demand."""
        for rec in self:
            rec.invited_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'invited'))
            rec.declined_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'declined'))
            rec.replaced_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'replaced'))
            rec.expired_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'expired'))
            rec.enrolled_count = len(rec.enrollment_ids.filtered(
                lambda e: e.state in ('enrolled', 'completed', 'incomplete', 'absent')
                and (not e.nomination_id or e.response_date
                     or e.nomination_id.employee_confirmed == 'confirmed')))
            rec.pending_count = len(rec.enrollment_ids.filtered(
                lambda e: e.state == 'invited' or e.state == 'suggested' and e.selected or (
                    e.state in ('enrolled', 'waitlisted') and e.nomination_id
                    and e.nomination_id.employee_confirmed == 'pending')))
            rec.waitlist_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'waitlisted'))

            rec.roster_status_summary = (
                f'<div class="d-inline-flex flex-wrap align-items-center gap-2 py-1">'
                f'<span class="badge rounded-pill text-bg-primary fs-6 px-3 py-2 shadow-sm" style="font-weight: 500;">'
                f'<i class="fa fa-envelope-o me-1"></i>Invite - {rec.invited_count}</span>'
                f'<span class="badge rounded-pill text-bg-danger fs-6 px-3 py-2 shadow-sm" style="font-weight: 500;">'
                f'<i class="fa fa-times-circle me-1"></i>Declined - {rec.declined_count}</span>'
                f'<span class="badge rounded-pill text-bg-warning fs-6 px-3 py-2 shadow-sm" style="font-weight: 500;">'
                f'<i class="fa fa-user-plus me-1"></i>Replaced - {rec.replaced_count}</span>'
                f'<span class="badge rounded-pill text-bg-success fs-6 px-3 py-2 shadow-sm" style="font-weight: 500;">'
                f'<i class="fa fa-check-circle me-1"></i>Enrolled - {rec.enrolled_count}</span>'
                f'<span class="badge rounded-pill text-bg-secondary fs-6 px-3 py-2 shadow-sm" style="font-weight: 500;">'
                f'<i class="fa fa-clock-o me-1"></i>Expired - {rec.expired_count}</span>'
                f'</div>'
            )

    @api.depends('attendance_ids.attended', 'attendance_ids.employee_id',
                 'attendance_ids.attendance_date', 'attendance_ids.attendance_slot',
                 'enrollment_ids.state', 'date_start', 'date_end', 'attendance_mode')
    def _compute_attendance_matrix_html(self):
        for rec in self:
            slots = rec._attendance_slots()
            enrollments = rec._accepted_attendance_enrollments().sorted(
                key=lambda row: row.employee_id.sudo().name or '')
            if not slots:
                rec.attendance_matrix_html = (
                    '<div class="alert alert-info py-3 mb-0" role="status">'
                    '<i class="fa fa-info-circle me-1"></i> '
                    'Schedule session start and end dates to enable the attendance sheet.'
                    '</div>'
                )
                continue
            if not enrollments:
                rec.attendance_matrix_html = (
                    '<div class="alert alert-warning py-3 mb-0" role="status">'
                    '<i class="fa fa-exclamation-triangle me-1"></i> '
                    'No enrolled or accepted participants on this session roster yet.'
                    '</div>'
                )
                continue

            session_real_id = rec.id if isinstance(rec.id, int) else (rec._origin.id if (hasattr(rec, '_origin') and rec._origin and isinstance(rec._origin.id, int)) else '')

            att_map = {
                (att.employee_id.id, att.attendance_date, att.attendance_slot): att
                for att in rec.attendance_ids
            }
            summary_map = {
                s.employee_id.id: s for s in rec.attendance_summary_ids
            }

            table_rows = []
            for emp_idx, enrollment in enumerate(enrollments, 1):
                emp = enrollment.employee_id.sudo()
                present_count = 0
                absent_count = 0

                day_cells = []
                start_date = slots[0][0] if slots else None
                is_split = rec.attendance_mode == 'split'
                for slot_idx, (att_date, slot, _hours) in enumerate(slots, 1):
                    att = att_map.get((emp.id, att_date, slot))
                    date_str = att_date.strftime("%b %d")
                    cal_day = (att_date - start_date).days + 1 if start_date else slot_idx
                    slot_label = 'Morning' if slot == 'morning' else ('Afternoon' if slot == 'afternoon' else '')
                    time_desc = f"{date_str} {slot_label} (Day {cal_day})" if slot_label else f"{date_str} (Day {cal_day})"
                    if att is None:
                        # Empty / Unrecorded slot
                        cell_html = (
                            f'<span class="eds-att-cell is-empty" '
                            f'data-session-id="{session_real_id}" data-emp-id="{emp.id}" '
                            f'data-date="{att_date}" data-slot="{slot}" '
                            f'title="Unrecorded. Click to mark Present for {emp.name} on {time_desc}" '
                            f'style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; cursor: pointer; user-select: none; background-color: #f8f9fa; color: #6c757d; border: 1px dashed #ced4da;">'
                            f'&nbsp;</span>'
                        )
                    elif att.attended:
                        present_count += 1
                        cell_html = (
                            f'<span class="eds-att-cell is-present" '
                            f'data-session-id="{session_real_id}" data-emp-id="{emp.id}" '
                            f'data-date="{att_date}" data-slot="{slot}" '
                            f'title="Present. Click to mark Absent for {emp.name} on {time_desc}" '
                            f'style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; cursor: pointer; user-select: none; background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc;">'
                            f'P</span>'
                        )
                    else:
                        absent_count += 1
                        cell_html = (
                            f'<span class="eds-att-cell is-absent" '
                            f'data-session-id="{session_real_id}" data-emp-id="{emp.id}" '
                            f'data-date="{att_date}" data-slot="{slot}" '
                            f'title="Absent. Click to clear for {emp.name} on {time_desc}" '
                            f'style="display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; cursor: pointer; user-select: none; background-color: #f8d7da; color: #842029; border: 1px solid #f5c2c7;">'
                            f'A</span>'
                        )
                    day_cells.append(
                        f'<td class="text-center align-middle p-1 eds-att-cell-td" '
                        f'data-session-id="{session_real_id}" data-emp-id="{emp.id}" data-date="{att_date}" data-slot="{slot}" '
                        f'style="width: 85px !important; min-width: 85px !important; max-width: 85px !important; border-right: 1px solid #e9ecef; border-bottom: 1px solid #e9ecef;">{cell_html}</td>'
                    )

                total_slots = len(slots)
                rate = (present_count / total_slots * 100.0) if total_slots else 0.0
                meets = rate >= 80.0
                if present_count == 0 and absent_count == 0:
                    status_badge = '<span class="badge rounded-pill text-bg-light text-muted px-2 py-1" style="font-size: 0.75rem;">Not Started</span>'
                elif meets:
                    status_badge = f'<span class="badge rounded-pill text-bg-success px-2 py-1" style="font-size: 0.75rem;">Meets (&ge;80%)</span>'
                else:
                    status_badge = f'<span class="badge rounded-pill text-bg-danger px-2 py-1" style="font-size: 0.75rem;">Below (&lt;80%)</span>'

                dept_parts = [p for p in (enrollment.work_unit_id.name, enrollment.department_id.name) if p]
                dept_label = ' / '.join(dept_parts) if dept_parts else '-'

                table_rows.append(
                    f'<tr data-emp-id="{emp.id}" data-session-id="{session_real_id}">'
                    f'<td class="text-center text-muted small" style="width: 45px !important; min-width: 45px !important; max-width: 45px !important; position: sticky; left: 0; background-color: #ffffff; z-index: 5; border-right: 1px solid #dee2e6; border-bottom: 1px solid #e9ecef;">{emp_idx}</td>'
                    f'<td class="text-start fw-bold text-nowrap" style="width: 220px !important; min-width: 220px !important; max-width: 220px !important; position: sticky; left: 45px; background-color: #ffffff; z-index: 5; border-right: 2px solid #ced4da; border-bottom: 1px solid #e9ecef; padding-left: 8px; box-shadow: 2px 0 4px rgba(0,0,0,0.06);">'
                    f'<i class="fa fa-user-circle-o text-primary me-1"></i>{emp.name}'
                    f'</td>'
                    f'<td class="text-start small text-muted text-nowrap" style="width: 180px !important; min-width: 180px !important; max-width: 180px !important; padding-left: 8px; border-right: 1px solid #dee2e6; border-bottom: 1px solid #e9ecef;">{dept_label}</td>'
                    + ''.join(day_cells) +
                    f'<td class="text-center fw-bold text-success eds-row-present" style="width: 65px !important; min-width: 65px !important; max-width: 65px !important; border-right: 1px solid #e9ecef; border-bottom: 1px solid #e9ecef;">{present_count}</td>'
                    f'<td class="text-center fw-bold text-danger eds-row-absent" style="width: 65px !important; min-width: 65px !important; max-width: 65px !important; border-right: 1px solid #e9ecef; border-bottom: 1px solid #e9ecef;">{absent_count}</td>'
                    f'<td class="text-center fw-bold text-nowrap eds-row-rate" style="width: 75px !important; min-width: 75px !important; max-width: 75px !important; border-right: 1px solid #e9ecef; border-bottom: 1px solid #e9ecef;">{rate:.1f}%</td>'
                    f'<td class="text-center text-nowrap eds-row-status" style="width: 110px !important; min-width: 110px !important; max-width: 110px !important; border-right: 1px solid #e9ecef; border-bottom: 1px solid #e9ecef;">{status_badge}</td>'
                    f'</tr>'
                )

            header_cells = []
            start_date = slots[0][0] if slots else None
            is_split = rec.attendance_mode == 'split'
            for slot_idx, (att_date, slot, _hours) in enumerate(slots, 1):
                cal_day = (att_date - start_date).days + 1 if start_date else slot_idx
                date_str = att_date.strftime("%b %d")
                if is_split:
                    if slot == 'morning':
                        slot_badge = '<span class="badge text-bg-primary px-2 py-0" style="font-size: 0.70rem; font-weight: 600;">Morning</span>'
                        slot_name_full = 'Morning'
                    else:
                        slot_badge = '<span class="badge text-bg-warning px-2 py-0" style="font-size: 0.70rem; font-weight: 600;">Afternoon</span>'
                        slot_name_full = 'Afternoon'
                    slot_sub = f'<div class="text-muted fw-bold" style="font-size: 0.68rem; line-height: 1.2; margin-top: 2px;">{date_str} <span class="fw-normal text-secondary">(D{cal_day})</span></div>'
                    full_title = f"{date_str} - {slot_name_full} (Day {cal_day})"
                else:
                    slot_badge = f'<div class="fw-bold text-dark small" style="font-size: 0.78rem; line-height: 1.2;">Day {cal_day}</div>'
                    slot_sub = f'<div class="text-muted" style="font-size: 0.70rem; line-height: 1.2; margin-top: 2px;">{date_str}</div>'
                    full_title = f"Day {cal_day} ({date_str})"

                header_cells.append(
                    f'<th class="text-center px-1 py-1 align-top" style="width: 85px !important; min-width: 85px !important; max-width: 85px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 6; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;" title="{full_title}">'
                    f'<div class="text-center">{slot_badge}</div>'
                    f'{slot_sub}'
                    f'<button type="button" class="btn btn-link btn-xs p-0 text-primary text-decoration-none eds-att-day-all mt-1" '
                    f'data-session-id="{session_real_id}" data-date="{att_date}" data-slot="{slot}" '
                    f'title="Mark all participants Present for {full_title}" '
                    f'style="font-size: 0.68rem; line-height: 1;">'
                    f'<i class="fa fa-check-square-o"></i> All</button>'
                    f'</th>'
                )

            total_cols_width = 45 + 220 + 180 + (len(slots) * 85) + 65 + 65 + 75 + 110

            rec.attendance_matrix_html = (
                f'<div class="o_list_renderer o_renderer eds-attendance-matrix-wrapper" data-session-id="{session_real_id}" style="width: 100%; max-width: 100%;">'
                f'<div style="overflow-x: auto !important; overflow-y: auto !important; max-height: 580px; width: 100%; border: 1px solid #dee2e6; border-radius: 4px; background-color: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">'
                f'<table class="o_list_table table table-sm table-hover table-striped mb-0 eds-attendance-matrix-table" data-session-id="{session_real_id}" '
                f'style="table-layout: fixed !important; width: {total_cols_width}px !important; min-width: {total_cols_width}px !important; border-collapse: separate !important; border-spacing: 0 !important;">'
                f'<colgroup>'
                f'<col style="width: 45px !important; min-width: 45px !important;"/>'
                f'<col style="width: 220px !important; min-width: 220px !important;"/>'
                f'<col style="width: 180px !important; min-width: 180px !important;"/>'
                + ''.join(f'<col style="width: 85px !important; min-width: 85px !important;"/>' for _ in slots) +
                f'<col style="width: 65px !important; min-width: 65px !important;"/>'
                f'<col style="width: 65px !important; min-width: 65px !important;"/>'
                f'<col style="width: 75px !important; min-width: 75px !important;"/>'
                f'<col style="width: 110px !important; min-width: 110px !important;"/>'
                f'</colgroup>'
                f'<thead class="o_list_table_header">'
                f'<tr>'
                f'<th class="text-center text-muted" style="width: 45px !important; position: sticky; left: 0; top: 0; background-color: #f8f9fa; z-index: 15; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;">#</th>'
                f'<th class="text-start text-nowrap" style="width: 220px !important; position: sticky; left: 45px; top: 0; background-color: #f8f9fa; z-index: 15; border-right: 2px solid #ced4da; border-bottom: 2px solid #dee2e6; padding-left: 8px; box-shadow: 2px 0 4px rgba(0,0,0,0.06);">Participant</th>'
                f'<th class="text-start text-nowrap" style="width: 180px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 8; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6; padding-left: 8px;">Work Unit / Department</th>'
                + ''.join(header_cells) +
                f'<th class="text-center text-success fw-bold text-nowrap" style="width: 65px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 8; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;">Present</th>'
                f'<th class="text-center text-danger fw-bold text-nowrap" style="width: 65px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 8; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;">Absent</th>'
                f'<th class="text-center fw-bold text-nowrap" style="width: 75px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 8; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;">Rate %</th>'
                f'<th class="text-center fw-bold text-nowrap" style="width: 110px !important; position: sticky; top: 0; background-color: #f8f9fa; z-index: 8; border-right: 1px solid #dee2e6; border-bottom: 2px solid #dee2e6;">Status</th>'
                f'</tr>'
                f'</thead>'
                f'<tbody class="o_list_table_tbody">'
                + ''.join(table_rows) +
                f'</tbody>'
                f'</table>'
                f'</div>'
                f'</div>'
            )

    def action_toggle_attendance_cell(self, *args, **kwargs):
        """Cycle participant attendance: Empty -> Present -> Absent -> Empty."""
        self._require_ld_delivery_access()
        clean_args = list(args)
        if clean_args and (isinstance(clean_args[0], (list, tuple)) or hasattr(clean_args[0], '_name')):
            clean_args.pop(0)

        employee_id = kwargs.get('employee_id') or (clean_args[0] if len(clean_args) > 0 else None)
        attendance_date = kwargs.get('attendance_date') or (clean_args[1] if len(clean_args) > 1 else None)
        attendance_slot = kwargs.get('attendance_slot') or (clean_args[2] if len(clean_args) > 2 else None) or 'day'
        session_id = kwargs.get('session_id') or (clean_args[3] if len(clean_args) > 3 else None)

        session = None
        if self and self.ids and self.ids[0] and isinstance(self.ids[0], int):
            s = self.browse(self.ids[0])
            if s.exists():
                session = s
        if not session and session_id:
            try:
                sid = int(session_id)
                s = self.env['eds.session'].browse(sid)
                if s.exists():
                    session = s
            except (ValueError, TypeError):
                pass
        if not session and self.env.context.get('active_id'):
            try:
                s = self.env['eds.session'].browse(int(self.env.context['active_id']))
                if s.exists():
                    session = s
            except (ValueError, TypeError):
                pass

        if not session:
            raise UserError(_("Session not found."))

        if not employee_id:
            raise UserError(_("Missing participant ID for attendance."))
        if not attendance_date:
            raise UserError(_("Missing attendance date."))

        try:
            employee_id = int(employee_id)
        except (ValueError, TypeError):
            raise UserError(_("Invalid participant ID: %s") % employee_id)

        domain = [
            ('session_id', '=', session.id),
            ('employee_id', '=', employee_id),
            ('attendance_date', '=', attendance_date),
            ('attendance_slot', '=', attendance_slot),
        ]
        rec = self.env['eds.session.attendance'].sudo().search(domain, limit=1)
        if not rec:
            # Empty -> Present
            rec = self.env['eds.session.attendance'].sudo().create({
                'session_id': session.id,
                'employee_id': employee_id,
                'attendance_date': attendance_date,
                'attendance_slot': attendance_slot,
                'attended': True,
                'recorded_by': self.env.user.id,
                'company_id': session.company_id.id,
            })
            new_state = 'present'
        elif rec.attended:
            # Present -> Absent
            rec.sudo().write({'attended': False})
            new_state = 'absent'
        else:
            # Absent -> Empty (delete record)
            rec.sudo().unlink()
            new_state = 'empty'

        session._sync_attendance_summaries()
        return {'status': 'ok', 'state': new_state}

    def action_mark_day_all_present(self, *args, **kwargs):
        """Mark all accepted participants as Present for a specific scheduled date/slot."""
        self._require_ld_delivery_access()
        clean_args = list(args)
        if clean_args and (isinstance(clean_args[0], (list, tuple)) or hasattr(clean_args[0], '_name')):
            clean_args.pop(0)

        attendance_date = kwargs.get('attendance_date') or (clean_args[0] if len(clean_args) > 0 else None)
        attendance_slot = kwargs.get('attendance_slot') or (clean_args[1] if len(clean_args) > 1 else None) or 'day'
        session_id = kwargs.get('session_id') or (clean_args[2] if len(clean_args) > 2 else None)

        session = None
        if self and self.ids and self.ids[0] and isinstance(self.ids[0], int):
            s = self.browse(self.ids[0])
            if s.exists():
                session = s
        if not session and session_id:
            try:
                sid = int(session_id)
                s = self.env['eds.session'].browse(sid)
                if s.exists():
                    session = s
            except (ValueError, TypeError):
                pass
        if not session and self.env.context.get('active_id'):
            try:
                s = self.env['eds.session'].browse(int(self.env.context['active_id']))
                if s.exists():
                    session = s
            except (ValueError, TypeError):
                pass

        if not session:
            raise UserError(_("Session not found."))

        if not attendance_date:
            raise UserError(_("Missing attendance date."))

        accepted_enrollments = session._accepted_attendance_enrollments()
        emp_ids = accepted_enrollments.mapped('employee_id').ids
        Attendance = self.env['eds.session.attendance'].sudo()
        for emp_id in emp_ids:
            domain = [
                ('session_id', '=', session.id),
                ('employee_id', '=', emp_id),
                ('attendance_date', '=', attendance_date),
                ('attendance_slot', '=', attendance_slot),
            ]
            rec = Attendance.search(domain, limit=1)
            if rec:
                rec.attended = True
            else:
                Attendance.create({
                    'session_id': session.id,
                    'employee_id': emp_id,
                    'attendance_date': attendance_date,
                    'attendance_slot': attendance_slot,
                    'attended': True,
                    'recorded_by': self.env.user.id,
                    'company_id': session.company_id.id,
                })
        session._sync_attendance_summaries()
        return {'status': 'ok'}

    def _expire_pending_invitations(self):
        """Expire only the opened sessions; no background job or full roster scan."""
        due = self.filtered(
            lambda rec: rec.status in ('scheduled', 'rescheduled', 'ongoing')
            and rec.response_deadline and rec.response_deadline < fields.Datetime.now())
        if due:
            due.mapped('enrollment_ids')._expire_overdue()

    def web_read(self, specification):
        self._expire_pending_invitations()
        return safe_employee_web_read(
            self, specification, super().web_read, ('coordinator_id',))

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        # Expire only the visible page before reading its counters. A list view
        # must not leave overdue invitations pending until a form is opened.
        self.search(domain, offset=offset, limit=limit or 80, order=order)._expire_pending_invitations()
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit,
            order=order, count_limit=count_limit)

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

    @api.depends('attendance_ids', 'attendance_ids.attended', 'enrollment_ids.state',
                 'enrollment_ids.response_date', 'enrollment_ids.nomination_id.employee_confirmed',
                 'date_start', 'date_end', 'attendance_mode')
    def _compute_attendance_rate(self):
        """Session-level attendance %."""
        for rec in self:
            accepted = rec._accepted_attendance_enrollments().mapped('employee_id')
            marks = rec.attendance_ids.filtered(lambda row: row.employee_id in accepted)
            scheduled_marks = len(rec._attendance_slots()) * len(accepted)
            total = max(len(marks), scheduled_marks)
            rec.attendance_rate = (
                round(len(marks.filtered('attended')) * 100.0 / total, 2)
                if total else 0.0)

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.onchange('course_id')
    def _onchange_course_id(self):
        self._onchange_certificate_course_defaults()
        if self.course_id:
            self.program_name = self.course_id.name
            if not self.plan_line_id and not self.unscheduled_request_id:
                self.delivery_method = self.course_id.recommended_source or 'internal'
            if not self.capacity:
                self.capacity = self._get_int_param('eds.default_class_capacity', 30)
            if self.course_id.duration_days and (not self.date_end or not self.date_start):
                self.duration_hours = self.course_id.duration_days * 8.0

    @api.constrains('sourcing_id', 'awarded_bid_id', 'awarded_provider_id',
                    'plan_line_id', 'unscheduled_request_id', 'course_id',
                    'trainer_ids', 'delivery_method')
    def _check_awarded_bid_source(self):
        for session in self:
            sourcing = session.sourcing_id
            bid = session.awarded_bid_id
            if sourcing:
                if sourcing.state != 'awarded' and session.status != 'draft':
                    raise ValidationError(_('Provider sourcing must be completed before scheduling.'))
                if (sourcing.course_id != session.course_id
                        or (session.source_type == 'unscheduled'
                            and sourcing.unscheduled_request_id != session.unscheduled_request_id)
                        or (session.source_type == 'annual_plan'
                            and sourcing.plan_line_id != session.plan_line_id)):
                    raise ValidationError(_('Provider sourcing must match this session’s approved program.'))
            if bid and (not sourcing or bid.selection_id != sourcing
                        or bid.status != 'awarded' or bid.vendor_id != session.awarded_provider_id):
                raise ValidationError(_('Select an awarded bid from this session’s provider sourcing.'))
            if (sourcing and session.delivery_method != 'internal'
                    and session.awarded_provider_id and not bid):
                raise ValidationError(_(
                    'Select a training provider awarded for this program or request.'))
            if session.delivery_method != 'internal' and session.awarded_provider_id:
                if (session.status in ('scheduled', 'ongoing', 'rescheduled')
                        and not session.trainer_ids):
                    raise ValidationError(_(
                        'Select at least one active trainer attached to the selected training provider.'))
                invalid_trainers = session.trainer_ids.filtered(
                    lambda trainer: trainer.state != 'active'
                    or trainer.trainer_type != 'external'
                    or trainer.external_provider_id != session.awarded_provider_id)
                if invalid_trainers:
                    raise ValidationError(_(
                        'Every external trainer must be active and attached to the selected training provider.'))

    @api.constrains('commitment_required', 'commitment_years', 'commitment_terms')
    def _check_commitment_configuration(self):
        for session in self:
            if session.commitment_required and (
                    session.commitment_years <= 0
                    or not (session.commitment_terms or '').strip()):
                raise ValidationError(_(
                    'Enter a positive commitment duration in years and the terms before enabling commitment.'))

    @api.constrains('batch_id', 'course_id')
    def _check_batch_course(self):
        for session in self:
            if session.batch_id and session.batch_id.course_id != session.course_id:
                raise ValidationError(_(
                    'The selected cohort must belong to the session training program.'))

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            venue_explicit = 'venue_id' in vals
            requested_venue = vals.get('venue_id')
            if vals.get('is_virtual') and requested_venue:
                raise ValidationError(_('A session marked No Hotel Needed cannot have a hotel or venue.'))
            internal_trainers = vals.get('trainer_ids') if vals.get('internal_fallback') else None
            requested_bid = (self.env['eds.course.vendor.line'].browse(vals['awarded_bid_id'])
                             if vals.get('awarded_bid_id') else False)
            requested_provider = (
                self.env['eds.external.provider'].browse(vals['awarded_provider_id'])
                if vals.get('awarded_provider_id') else False)
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.session') or _('New')
            if vals.get('awarded_venue_id') and not venue_explicit and not vals.get('is_virtual'):
                vals['venue_id'] = vals['awarded_venue_id']
            if vals.get('plan_line_id'):
                plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
                request = plan_line.unscheduled_request_id
                vals['source_type'] = 'unscheduled' if request else 'annual_plan'
                vals['approved_plan_id'] = plan_line.plan_id.id
                vals['unscheduled_request_id'] = request.id or False
                vals['course_id'] = plan_line.course_id.id or False
                vals['program_name'] = plan_line.course_id.name or False
                vals.update(self._sourcing_values_for_plan_line(
                    plan_line, preferred_bid=requested_bid,
                    preferred_provider=requested_provider))
            elif vals.get('unscheduled_request_id'):
                request = self.env['eds.unscheduled.request'].browse(
                    vals['unscheduled_request_id'])
                vals['source_type'] = 'unscheduled'
                vals['course_id'] = request.course_id.id or False
                vals['program_name'] = request.course_id.name or False
                plan_line = request.plan_line_ids[:1]
                if plan_line:
                    vals['plan_line_id'] = plan_line.id
                    vals['approved_plan_id'] = plan_line.plan_id.id
                    vals.update(self._sourcing_values_for_plan_line(
                        plan_line, preferred_bid=requested_bid,
                        preferred_provider=requested_provider))
                else:
                    vals.update(self._sourcing_values_for_plan_line(
                        plan_line, request, preferred_bid=requested_bid,
                        preferred_provider=requested_provider))
            elif vals.get('course_id'):
                vals['program_name'] = self.env['eds.course'].browse(vals['course_id']).name
            if venue_explicit or vals.get('is_virtual'):
                vals['venue_id'] = False if vals.get('is_virtual') else requested_venue or False
            if vals.get('course_id'):
                defaults = self._course_certificate_values(
                    self.env['eds.course'].browse(vals['course_id']))
                for field_name, value in defaults.items():
                    vals.setdefault(field_name, value)
            if vals.get('internal_fallback'):
                if vals.get('awarded_provider_id'):
                    raise UserError(_('An awarded provider is already available. Use the sourced delivery type.'))
                vals['delivery_method'] = 'internal'
                if internal_trainers is not None:
                    vals['trainer_ids'] = internal_trainers
            if vals.get('source_type', 'annual_plan') == 'annual_plan' and vals.get('approved_plan_id'):
                plan = self.env['eds.annual.plan'].browse(vals['approved_plan_id'])
                if plan.state == 'archived':
                    raise UserError(_('Archived annual plans cannot be used for new sessions.'))
        sessions = super().create(vals_list)
        for session in sessions:
            session._sync_plan_line_status()
            session._populate_suggested_enrollments()
        return sessions

    def _check_confirmed_schedule_write(self, vals):
        """Keep confirmed schedule details fixed, including values derived by write."""
        locked_fields = _CONFIRMED_SCHEDULE_FIELDS.intersection(vals)
        for rec in self:
            if rec.status == 'draft':
                continue
            changed_schedule_fields = set()
            for field_name in locked_fields:
                field_type = rec._fields[field_name].type
                current, requested = rec[field_name], vals[field_name]
                if field_type == 'many2one':
                    current = current.id or False
                    requested = (requested.id if hasattr(requested, 'id')
                                 else requested or False)
                elif field_type == 'datetime':
                    requested = (fields.Datetime.to_datetime(requested)
                                 if requested else False)
                elif field_type in ('char', 'text', 'selection'):
                    current, requested = current or False, requested or False
                elif field_type == 'boolean':
                    current, requested = bool(current), bool(requested)
                if current != requested:
                    changed_schedule_fields.add(field_name)
            if changed_schedule_fields & _FIXED_SESSION_SOURCE_FIELDS:
                raise UserError(_(
                    'The approved source, course, company, and sourcing of a '
                    'confirmed session cannot change during rescheduling.'))
            if rec.status == 'rescheduled':
                continue
            requested_provider_id = rec.awarded_provider_id.id or False
            if 'awarded_provider_id' in vals:
                requested_provider_id = vals['awarded_provider_id'] or False
            elif 'awarded_bid_id' in vals:
                requested_provider_id = (
                    self.env['eds.course.vendor.line'].browse(
                        vals['awarded_bid_id']).vendor_id.id
                    if vals['awarded_bid_id'] else False)
            provider_changing = requested_provider_id != (rec.awarded_provider_id.id or False)
            if ('awarded_bid_id' in vals
                    and (vals['awarded_bid_id'] or False) != (rec.awarded_bid_id.id or False)
                    and not provider_changing):
                changed_schedule_fields.add('awarded_bid_id')
            trainer_changing = False
            if 'trainer_ids' in vals:
                before = set(rec.trainer_ids.ids)
                after = set(before)
                for command in vals['trainer_ids'] or [(5, 0, 0)]:
                    operation = command[0]
                    if operation == 6:
                        after = set(command[2])
                    elif operation == 4:
                        after.add(command[1])
                    elif operation == 3:
                        after.discard(command[1])
                    elif operation == 5:
                        after.clear()
                    else:
                        after = None
                        break
                trainer_changing = after is None or after != before
                trainer_changing = trainer_changing and not (
                    provider_changing and (vals.get('provider_change_reason') or '').strip())
            if changed_schedule_fields or trainer_changing:
                if rec.status in ('completed', 'cancelled'):
                    raise UserError(_(
                        'The schedule of a completed or cancelled session cannot be changed.'))
                raise UserError(_(
                    'Use Reschedule before changing dates, cohort, commitment, venue, '
                    'trainers, or other confirmed schedule details.'))

    def write(self, vals):
        vals = dict(vals)
        self._check_confirmed_schedule_write(vals)
        if len(self) > 1 and {'awarded_provider_id', 'awarded_bid_id'} & vals.keys():
            for session in self:
                session.write(vals)
            return True
        if vals.get('venue_id') and (
                vals.get('is_virtual') or
                ('is_virtual' not in vals and any(rec.is_virtual for rec in self))):
            raise ValidationError(_('A session marked No Hotel Needed cannot have a hotel or venue.'))
        if vals.get('is_virtual'):
            vals['venue_id'] = False
        venue_explicit = 'venue_id' in vals
        requested_venue = vals.get('venue_id')
        previous_plan_lines = (self.mapped('plan_line_id') if 'plan_line_id' in vals
                               else self.env['eds.annual.plan.line'])
        if {'commitment_required', 'commitment_years', 'commitment_terms'} & vals.keys():
            if any(rec.status != 'rescheduled' and rec.enrollment_ids.filtered(
                    lambda row: row.state != 'suggested')
                   for rec in self):
                raise UserError(_(
                    'Commitment terms cannot change after invitations are sent. '
                    'Use Reschedule to revise the terms and request fresh acceptance.'))
        requested_provider = (
            self.env['eds.external.provider'].browse(vals['awarded_provider_id'])
            if vals.get('awarded_provider_id') else self.env['eds.external.provider'])
        requested_bid = (self.env['eds.course.vendor.line'].browse(vals['awarded_bid_id'])
                         if vals.get('awarded_bid_id') else self.env['eds.course.vendor.line'])
        if 'awarded_provider_id' in vals:
            if requested_provider:
                if 'plan_line_id' in vals:
                    plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
                    request = plan_line.unscheduled_request_id
                elif 'unscheduled_request_id' in vals:
                    request = self.env['eds.unscheduled.request'].browse(
                        vals['unscheduled_request_id'])
                    plan_line = request.plan_line_ids[:1]
                else:
                    plan_line, request = self.plan_line_id, self.unscheduled_request_id
                sourcing, _hotel = self._sourcing_for_plan_line(plan_line, request)
                if not sourcing and 'plan_line_id' not in vals and 'unscheduled_request_id' not in vals:
                    sourcing = self.sourcing_id
                if sourcing or plan_line or request:
                    # The visible provider choice wins over a stale hidden bid.
                    requested_bid = self._awarded_bid_for_provider(
                        sourcing, requested_provider)
                    vals['awarded_bid_id'] = requested_bid.id
                elif requested_bid and requested_bid.vendor_id != requested_provider:
                    raise ValidationError(_(
                        'The selected provider and awarded bid must belong to the same award.'))
            else:
                if requested_bid:
                    raise ValidationError(_(
                        'Clear the awarded bid when removing its training provider.'))
                vals['awarded_bid_id'] = False
        previous_providers = {}
        if 'awarded_bid_id' in vals or 'awarded_provider_id' in vals:
            for rec in self:
                new_bid = requested_bid if 'awarded_bid_id' in vals else rec.awarded_bid_id
                new_provider = (new_bid.vendor_id if 'awarded_bid_id' in vals else
                                requested_provider if 'awarded_provider_id' in vals else
                                self.env['eds.external.provider'])
                if rec.awarded_provider_id == new_provider:
                    continue
                if rec.status in ('completed', 'cancelled'):
                    raise UserError(_('The provider of a completed or cancelled session cannot change.'))
                if rec.status not in ('draft', 'cancelled'):
                    if not (vals.get('provider_change_reason') or '').strip():
                        raise UserError(_('Explain the provider change before saving this session.'))
                    if not new_bid or new_bid.selection_id != rec.sourcing_id or new_bid.status != 'awarded':
                        raise UserError(_('Choose another awarded training provider from this session’s sourcing.'))
                    if 'trainer_ids' not in vals:
                        selected = rec.trainer_ids.filtered(
                            lambda trainer: trainer.state == 'active'
                            and trainer.trainer_type == 'external'
                            and trainer.external_provider_id == new_provider)
                        if not selected and new_bid.trainer_id and new_bid.trainer_id.state == 'active':
                            selected = new_bid.trainer_id
                        if not selected:
                            raise UserError(_(
                                'Select at least one active trainer attached to the new provider.'))
                        vals['trainer_ids'] = [(6, 0, selected.ids)]
                    previous_providers[rec.id] = rec.awarded_provider_id.name or _('No provider')
        if 'awarded_bid_id' in vals:
            vals['awarded_provider_id'] = requested_bid.vendor_id.id or False
        if 'enrollment_ids' in vals:
            vals['enrollment_ids'] = [
                (0, 0, dict(command[2], state='suggested'))
                if command[0] == 0 and isinstance(command[2], dict)
                and not command[2].get('nomination_id') else command
                for command in vals['enrollment_ids']
            ]
        previous_courses = {rec.id: rec.course_id.id for rec in self}
        if any(
                rec.attendance_ids and any(
                    field in vals and fields.Datetime.to_datetime(vals[field]) != getattr(rec, field)
                    for field in ('date_start', 'date_end'))
                for rec in self):
            raise UserError(_(
                'Session dates cannot change after attendance is recorded. '
                'Correct or remove the attendance marks before rescheduling.'))
        if 'attendance_mode' in vals and any(
                vals['attendance_mode'] != rec.attendance_mode
                and (rec.status not in ('draft', 'scheduled', 'rescheduled', 'ongoing') or rec.attendance_ids.filtered(lambda a: a.attended))
                for rec in self):
            raise UserError(_(
                'Attendance recording mode cannot change while attendance records exist. '
                'Clear attendance marks before changing the recording mode.'))
        changed_sources = {}
        for rec in self:
            source_changed = (
                ('source_type' in vals and vals['source_type'] != rec.source_type)
                or ('plan_line_id' in vals and (vals['plan_line_id'] or False)
                    != (rec.plan_line_id.id or False))
                or ('unscheduled_request_id' in vals
                    and (vals['unscheduled_request_id'] or False)
                    != (rec.unscheduled_request_id.id or False)))
            if source_changed:
                if rec.status != 'draft':
                    raise UserError(_('The approved source cannot change after scheduling.'))
                changed_sources[rec.id] = rec.enrollment_ids.ids
        if changed_sources:
            vals['omitted_suggestion_employee_ids'] = [(5, 0, 0)]
            vals.setdefault('venue_id', False)
        if 'delivery_method' in vals or vals.get('plan_line_id'):
            method = vals.get('delivery_method')
            if vals.get('plan_line_id'):
                method = self._sourcing_values_for_plan_line(
                    self.env['eds.annual.plan.line'].browse(vals['plan_line_id']))['delivery_method']
            for session in self:
                for cost in session.cost_ids:
                    validate_delivery_currency(self.env, method or session.delivery_method, cost.currency_id.id)
        previous_trainers = {rec.id: set(rec.trainer_ids.ids) for rec in self} if 'trainer_ids' in vals else {}
        if 'status' in vals and not self.env.su:
            raise UserError(_('Use the session workflow actions to change its status.'))
        if vals.get('plan_line_id'):
            plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
            request = plan_line.unscheduled_request_id
            vals.update({
                'source_type': 'unscheduled' if request else 'annual_plan',
                'approved_plan_id': plan_line.plan_id.id,
                'unscheduled_request_id': request.id or False,
                'course_id': plan_line.course_id.id or False,
                'program_name': plan_line.course_id.name or False,
            })
            vals.update(self._sourcing_values_for_plan_line(
                plan_line, preferred_bid=requested_bid,
                preferred_provider=requested_provider))
        elif vals.get('unscheduled_request_id'):
            request = self.env['eds.unscheduled.request'].browse(
                vals['unscheduled_request_id'])
            vals.update({
                'source_type': 'unscheduled',
                'approved_plan_id': request.annual_plan_id.id or False,
                'course_id': request.course_id.id or False,
                'program_name': request.course_id.name or False,
            })
            plan_line = request.plan_line_ids[:1]
            if plan_line:
                vals.update({
                    'plan_line_id': plan_line.id,
                    'approved_plan_id': plan_line.plan_id.id,
                })
                vals.update(self._sourcing_values_for_plan_line(
                    plan_line, preferred_bid=requested_bid,
                    preferred_provider=requested_provider))
            else:
                vals['plan_line_id'] = False
                vals.update(self._sourcing_values_for_plan_line(
                    plan_line, request, preferred_bid=requested_bid,
                    preferred_provider=requested_provider))
        elif 'course_id' in vals:
            vals['program_name'] = (
                self.env['eds.course'].browse(vals['course_id']).name
                if vals['course_id'] else False)
        elif 'program_name' in vals:
            vals.pop('program_name')
        if {'source_type', 'plan_line_id', 'approved_plan_id', 'unscheduled_request_id'} & vals.keys():
            for rec in self:
                source_type = vals.get('source_type', rec.source_type)
                if source_type != 'annual_plan':
                    continue
                plan_id = vals.get('approved_plan_id', rec.approved_plan_id.id)
                plan_line_id = vals.get('plan_line_id', rec.plan_line_id.id)
                if plan_id and self.env['eds.annual.plan'].browse(plan_id).state == 'archived' and (
                        rec.source_type != 'annual_plan'
                        or plan_id != rec.approved_plan_id.id
                        or plan_line_id != rec.plan_line_id.id):
                    raise UserError(_('Archived annual plans cannot be selected for a session.'))
        if changed_sources and (venue_explicit or vals.get('is_virtual') or all(
                rec.is_virtual for rec in self)):
            vals['venue_id'] = requested_venue or False
        if (vals.get('awarded_venue_id') and 'venue_id' not in vals
                and not (vals.get('is_virtual') or all(rec.is_virtual for rec in self))):
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

        self._check_confirmed_schedule_write(vals)
        res = super().write(vals)
        if 'sourcing_id' in vals:
            self._deselect_already_allocated_suggestions()
            self.mapped('enrollment_ids')._check_unique_sourcing_enrollment()
            self.env['eds.nomination'].search([('session_id', 'in', self.ids)])._check_unique_sourcing_nomination()
        for rec in self.filtered(lambda row: row.id in previous_providers):
            message = _('Training provider changed from %s to %s: %s') % (
                previous_providers[rec.id], rec.awarded_provider_id.name,
                vals['provider_change_reason'].strip())
            rec._notify_participants(message)
        if 'course_id' in vals:
            defaults = self._course_certificate_values(
                self.env['eds.course'].browse(vals['course_id']))
            defaults = {name: value for name, value in defaults.items() if name not in vals}
            if defaults:
                for rec in self:
                    if previous_courses[rec.id] != rec.course_id.id:
                        super(EdsSession, rec).write(defaults)
        for rec in self.filtered(lambda row: row.id in changed_sources):
            self.env['eds.enrollment'].browse(changed_sources[rec.id]).exists().with_context(
                eds_replacing_source=True).unlink()
        if 'internal_fallback' in vals and not self.env.context.get('eds_sync_sourcing'):
            self._sync_sourcing_from_plan_line()
        if changed_sources or 'plan_line_id' in vals or 'unscheduled_request_id' in vals:
            for rec in self:
                rec._populate_suggested_enrollments()

        # Re-synchronize venue booking if dates or venue changed while scheduled/ongoing
        for rec in self:
            if rec.status in ('scheduled', 'ongoing'):
                if any(f in vals for f in ('date_start', 'date_end', 'venue_id', 'hall_id')):
                    if rec.venue_id:
                        if rec.booking_id:
                            rec.booking_id.write({
                                'venue_id': rec.venue_id.id,
                                'hall_id': rec.hall_id.id if rec.hall_id else False,
                                'date_start': rec.date_start,
                                'date_end': rec.date_end,
                            })
                        else:
                            self.env['eds.venue.booking'].create({
                                'venue_id': rec.venue_id.id,
                                'hall_id': rec.hall_id.id if rec.hall_id else False,
                                'session_id': rec.id,
                                'date_start': rec.date_start,
                                'date_end': rec.date_end,
                                'state': 'confirmed',
                            })
                    elif rec.booking_id:
                        rec.booking_id.action_cancel()

        if any(f in vals for f in ('date_start', 'date_end', 'status', 'plan_line_id')):
            self._sync_plan_lines(previous_plan_lines | self.mapped('plan_line_id'))
        if 'capacity' in vals:
            for rec in self:
                rec._promote_waitlisted()
        if 'trainer_ids' in vals:
            for rec in self.filtered(lambda session: session.status in ('scheduled', 'ongoing')):
                new_trainers = rec.trainer_ids.filtered(
                    lambda trainer: trainer.id not in previous_trainers.get(rec.id, set()))
                rec._notify_assigned_trainers(new_trainers)
            evaluations = self.env['eds.evaluation.level1'].sudo().search([
                ('session_id', 'in', self.ids),
                ('state', 'in', ('submitted', 'consolidated')),
            ])
            self.env['eds.trainer.feedback'].sync_from_level1(evaluations)
        return res

    def _write_workflow_status(self, status):
        """Internal transition after the public action checks its prerequisites."""
        result = super(EdsSession, self).write({'status': status})
        for session in self:
            session._sync_plan_line_status()
        return result

    def _populate_suggested_enrollments(self):
        for rec in self:
            existing = {row.employee_id.id: row for row in rec.enrollment_ids}
            allocated = rec._allocated_employee_ids_in_other_sessions()
            omitted = set(rec.omitted_suggestion_employee_ids.ids)
            to_create = []

            # Populate target employees from unscheduled training request
            if rec.unscheduled_request_id and rec.unscheduled_request_id.employee_ids:
                req_summary = _('Unscheduled Request: %s') % rec.unscheduled_request_id.name
                for emp in rec.unscheduled_request_id.employee_ids:
                    if emp.id in existing:
                        current = existing[emp.id]
                        if current.state == 'suggested' and current.selected and emp.id in allocated:
                            current.write({'selected': False})
                        continue
                    if emp.id in omitted:
                        continue
                    to_create.append({
                        'session_id': rec.id,
                        'employee_id': emp.id,
                        'source_summary': req_summary,
                        'source_count': 1,
                        'state': 'suggested',
                        'selected': emp.id not in allocated,
                    })

            demands = rec.plan_line_id.course_demand_ids | rec.plan_line_id.course_demand_id
            if demands:
                by_employee = {}
                for employee_demand in demands.mapped('employee_demand_ids').filtered(
                        lambda row: not row.excluded_from_planning):
                    by_employee.setdefault(employee_demand.employee_id.id, []).append(employee_demand)
                stale = rec.enrollment_ids.filtered(
                    lambda row: row.state == 'suggested' and row.course_demand_employee_id
                    and row.employee_id.id not in by_employee)
                if stale:
                    stale.with_context(eds_replacing_source=True).unlink()
                ranked = sorted(by_employee.items(), key=lambda item: (
                    -max(row.overall_priority_score for row in item[1]), item[0]))
                for employee_id, matches in ranked:
                    top_match = max(matches, key=lambda row: (
                        row.overall_priority_score, row.source_count, -row.id))
                    source_labels = []
                    for match in matches:
                        for label in (match.source_summary or '').split(', '):
                            if label and label not in source_labels:
                                source_labels.append(label)
                    summary = ', '.join(source_labels)
                    if employee_id in existing:
                        current = existing[employee_id]
                        if current.state == 'suggested':
                            updates = {}
                            if current.selected and employee_id in allocated:
                                updates['selected'] = False
                            if current.course_demand_employee_id != top_match:
                                updates['course_demand_employee_id'] = top_match.id
                            if current.source_summary != summary:
                                updates['source_summary'] = summary
                            if current.source_count != len(source_labels):
                                updates['source_count'] = len(source_labels)
                            if updates:
                                current.write(updates)
                        continue
                    if employee_id in omitted:
                        continue
                    to_create.append({
                        'session_id': rec.id,
                        'employee_id': employee_id,
                        'course_demand_employee_id': top_match.id,
                        'source_summary': summary,
                        'source_count': len(source_labels),
                        'state': 'suggested',
                        'selected': employee_id not in allocated,
                    })
            if to_create:
                self.env['eds.enrollment'].create(to_create)

    def _allocated_employee_ids_in_other_sessions(self):
        self.ensure_one()
        if not self.sourcing_id:
            return set()
        rows = self.env['eds.enrollment'].sudo().search([
            ('session_id.sourcing_id', '=', self.sourcing_id.id),
            ('session_id', '!=', self.id),
            ('session_id.status', '!=', 'cancelled'),
            ('state', 'in', ('suggested', 'invited', 'enrolled', 'waitlisted',
                             'completed', 'incomplete', 'absent')),
        ])
        return set(rows.filtered(lambda row: row.state != 'suggested' or row.selected)
                   .mapped('employee_id').ids)

    def _deselect_already_allocated_suggestions(self):
        for session in self:
            allocated = session._allocated_employee_ids_in_other_sessions()
            conflicts = session.enrollment_ids.filtered(
                lambda row: row.state == 'suggested' and row.selected
                and row.employee_id.id in allocated)
            if conflicts:
                conflicts.write({'selected': False})

    def action_refresh_suggested_employees(self):
        if any(rec.status != 'draft' for rec in self):
            raise UserError(_('Suggested employees can only be refreshed before scheduling. Add new participants directly to the scheduled roster.'))
        self._populate_suggested_enrollments()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_create_followup_session(self):
        """Open another delivery under the same approved program and sourcing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Prepare Another Training Session'),
            'res_model': 'eds.session',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_source_type': self.source_type,
                'default_approved_plan_id': self.approved_plan_id.id,
                'default_plan_line_id': self.plan_line_id.id,
                'default_unscheduled_request_id': self.unscheduled_request_id.id,
                'default_course_id': self.course_id.id,
                'default_sourcing_id': self.sourcing_id.id,
                'default_delivery_method': self.delivery_method,
                'default_commitment_required': self.commitment_required,
                'default_commitment_years': self.commitment_years,
                'default_commitment_terms': self.commitment_terms,
            },
        }

    def _missing_prerequisites_for_invitations(self, invitations):
        """Return advisory gaps using issued certificates or completed sessions."""
        required_courses = invitations.mapped('session_id.course_id.prerequisite_course_ids')
        if not required_courses:
            return []
        employee_ids = invitations.mapped('employee_id').ids
        certificate_model = self.env['eds.certificate'].sudo()
        enrollment_model = self.env['eds.enrollment'].sudo()
        certificates = certificate_model.search([
            ('employee_id', 'in', employee_ids),
            ('course_id', 'in', required_courses.ids),
            ('state', '=', 'issued'),
        ])
        completions = enrollment_model.search([
            ('employee_id', 'in', employee_ids),
            ('session_id.course_id', 'in', required_courses.ids),
            ('state', '=', 'completed'),
        ])
        completed_by_employee = {employee_id: set() for employee_id in employee_ids}
        for certificate in certificates:
            completed_by_employee[certificate.employee_id.id].add(certificate.course_id.id)
        for enrollment in completions:
            completed_by_employee[enrollment.employee_id.id].add(enrollment.session_id.course_id.id)

        warnings = []
        for invitation in invitations:
            prerequisites = invitation.session_id.course_id.prerequisite_course_ids
            missing = prerequisites.filtered(
                lambda course: course.id not in completed_by_employee[invitation.employee_id.id]
            )
            if missing:
                warnings.append(_('%s — %s: %s') % (
                    invitation.employee_id.sudo().name,
                    invitation.session_id.course_id.name,
                    ', '.join(missing.mapped('name')),
                ))
        return warnings

    def action_invite_selected(self):
        for rec in self:
            if rec.status != 'scheduled':
                raise UserError(_('Confirm the session schedule before sending invitations.'))
        self._expire_pending_invitations()
        invitations = self.mapped('enrollment_ids').filtered(
            lambda row: row.selected and row.state == 'suggested')
        warnings = self._missing_prerequisites_for_invitations(invitations)
        if warnings:
            wizard = self.env['eds.prerequisite.warning.wizard'].create({
                'enrollment_ids': [(6, 0, invitations.ids)],
                'warning_text': '\n'.join(warnings),
            })
            return {
                'name': _('Prerequisite Warning'),
                'type': 'ir.actions.act_window',
                'res_model': 'eds.prerequisite.warning.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }
        invitations.action_invite()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.ids[0] if self else False},
        }

    def action_select_all_invitations(self):
        for rec in self:
            if rec.status in ('draft', 'rescheduled'):
                rec.enrollment_ids.write({'selected': True})
            else:
                rec.enrollment_ids.filtered(lambda row: row.state == 'suggested').write({'selected': True})
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return True

    def action_deselect_all_invitations(self):
        for rec in self:
            if rec.status in ('draft', 'rescheduled'):
                rec.enrollment_ids.write({'selected': False})
            else:
                rec.enrollment_ids.filtered(lambda row: row.state == 'suggested').write({'selected': False})
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return True

    def _sync_plan_line_status(self):
        """Derive one plan-line status from every sibling delivery session."""
        self.ensure_one()
        self._sync_plan_lines(self.plan_line_id)

    @api.model
    def _sync_plan_lines(self, lines):
        for line in lines:
            statuses = set(line.session_ids.mapped('status'))
            if not statuses:
                target = 'planned'
            elif statuses & {'draft', 'scheduled', 'ongoing', 'rescheduled'}:
                target = 'scheduled'
            elif 'completed' in statuses:
                target = 'delivered'
            else:
                target = 'cancelled'
            if line.status != target:
                line._write_delivery_status(target)

    def unlink(self):
        lines = self.mapped('plan_line_id')
        result = super().unlink()
        self.env['eds.session']._sync_plan_lines(lines)
        return result

    def _get_venue_conflicts(self):
        """Other sessions sharing a named hall on an overlapping window."""
        self.ensure_one()
        if not self.venue_id or self.venue_id.venue_type == 'hotel' \
                or not self.date_start or not self.date_end \
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
        """Block overlaps for named halls and individual trainers."""
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
        """Print only issued certificates belonging to this exact session."""
        self.ensure_one()
        certs = self.env['eds.certificate'].search([
            ('session_id', '=', self.id), ('state', '=', 'issued'),
        ])
        if not certs:
            raise UserError(_('No issued certificates found for this training session.'))
        return self.env.ref('employee_development_system.action_report_eds_certificate').report_action(certs)

    # ── Session workflow ──────────────────────────────
    def _training_location_label(self):
        self.ensure_one()
        return (self.venue_id.name or
                (_('No hotel needed') if self.is_virtual else _('Venue to be confirmed')))

    def _validate_venue_choice(self):
        """Keep the optional virtual venue and physical award rules in one place."""
        for rec in self:
            if rec.venue_id:
                rec._check_selected_venue_award()
            elif not rec.is_virtual:
                if rec.delivery_method == 'internal':
                    raise UserError(_('Choose an internal venue before confirming the schedule.'))
                raise UserError(_(
                    'Award a hotel or venue for this external program before confirming the schedule.'))
            elif not (rec.venue_omission_reason or '').strip():
                raise UserError(_(
                    'Explain why this session needs no hotel or venue.'))

    @api.constrains('venue_id', 'is_virtual', 'venue_omission_reason')
    def _check_scheduled_venue_configuration(self):
        for rec in self:
            if rec.is_virtual:
                if rec.venue_id:
                    raise ValidationError(_(
                        'A session marked No Hotel Needed cannot have a hotel or venue.'))
                if not (rec.venue_omission_reason or '').strip():
                    raise ValidationError(_('Explain why no hotel or venue is needed.'))
        self.filtered(lambda rec: rec.status in ('scheduled', 'ongoing'))._validate_venue_choice()

    def action_confirm(self):
        """Draft -> Scheduled: validate conflicts and book the venue."""
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only draft sessions can be confirmed.'))
            if not rec.response_deadline or rec.response_deadline <= fields.Datetime.now():
                raise UserError(_('Set a future invitation response deadline before confirming the schedule.'))
            if not rec.course_id:
                raise UserError(_('Select a catalog course through an approved plan program or unscheduled request.'))
            if rec.source_type == 'annual_plan':
                if not rec.approved_plan_id or not rec.plan_line_id:
                    raise UserError(_('Select an approved annual plan and one of its programs.'))
                if rec.approved_plan_id.state not in ('published', 'amended'):
                    raise UserError(_('Sessions may be scheduled only from an approved annual plan.'))
                if rec.plan_line_id.plan_id != rec.approved_plan_id or rec.plan_line_id.is_addendum:
                    raise UserError(_('Select a regular program from the approved annual plan.'))
                if rec.plan_line_id.is_completed:
                    raise UserError(_('Program "%s" has already been marked as completed in the Annual Plan and cannot be scheduled for further sessions.') % (rec.plan_line_id.course_id.name or rec.plan_line_id.program_name))
                if rec.approved_plan_id.company_id != rec.company_id:
                    raise UserError(_('The annual plan and session must belong to the same company.'))
                source_course = rec.plan_line_id.course_id
            elif rec.source_type == 'unscheduled':
                request = rec.unscheduled_request_id
                if not request or request.state != 'approved':
                    raise UserError(_('Select an approved unscheduled training request.'))
                if request.company_id != rec.company_id:
                    raise UserError(_('The unscheduled request and session must belong to the same company.'))
                if rec.plan_line_id and (
                        not rec.plan_line_id.is_addendum
                        or rec.plan_line_id.unscheduled_request_id != request):
                    raise UserError(_('The addendum program does not belong to this unscheduled request.'))
                source_course = request.course_id
            else:
                raise UserError(_('Select the approved source of this session first.'))
            if rec.course_id != source_course:
                raise UserError(_('The training program must match the approved source course.'))
            if rec.internal_fallback:
                sourced = rec._sourcing_values_for_plan_line(rec.plan_line_id, rec.unscheduled_request_id)
                sourcing = self.env['eds.course.vendor.selection'].browse(sourced['sourcing_id'])
                if (sourcing.line_ids.filtered(lambda bid: bid.status == 'awarded')
                        or sourced['delivery_method'] == 'internal'):
                    raise UserError(_('Internal fallback is available only when external delivery has no awarded provider.'))
                if not (rec.internal_fallback_reason or '').strip():
                    raise UserError(_('Explain why this session is changing to internal delivery.'))
            rec._sync_sourcing_from_plan_line()
            rec.enrollment_ids._check_unique_sourcing_enrollment()
            sourcing, hotel = rec._sourcing_for_plan_line(rec.plan_line_id, rec.unscheduled_request_id)
            if rec.delivery_method != 'internal':
                winner = rec.awarded_bid_id
                if not sourcing or sourcing.state != 'awarded' or not sourcing.line_ids.filtered(
                        lambda line: line.status == 'awarded'):
                    raise UserError(_('Complete training provider sourcing and award a provider for this program before scheduling.'))
                if (not winner or winner.selection_id != sourcing or winner.status != 'awarded'
                        or winner.vendor_id != rec.awarded_provider_id):
                    raise UserError(_('Select an awarded bid from this provider sourcing before scheduling.'))
            if hotel:
                expected_scope = ('international' if hotel.delivery_method == 'international'
                                  else 'local')
                if hotel.awarded_venue_id.location_scope != expected_scope:
                    raise UserError(_('The awarded venue location does not match its hotel sourcing arrangement.'))
            rec._validate_venue_choice()
            if not rec.trainer_ids:
                raise UserError(_('Assign the internal ToT trainer or external organization trainer before confirming the schedule.'))
            if rec.delivery_method == 'internal':
                if rec.trainer_ids.filtered(lambda trainer: trainer.trainer_type != 'internal' or not trainer.tot_certified or trainer.state != 'active'):
                    raise UserError(_('Internal delivery requires certified internal ToT trainers.'))
            elif not rec.awarded_provider_id:
                raise UserError(_('Complete training provider sourcing before scheduling external delivery.'))
            elif rec.trainer_ids.filtered(lambda trainer: trainer.state != 'active' or trainer.trainer_type != 'external' or
                                          trainer.external_provider_id != rec.awarded_provider_id):
                raise UserError(_('External trainers must belong to the selected training organization.'))
            rec._check_session_conflicts()
            rec._write_workflow_status('scheduled')
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'hall_id': rec.hall_id.id if rec.hall_id else False,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s confirmed and scheduled.') % rec.name)
            rec._notify_assigned_trainers()
            rec._notify_assessment_coordinators(_(
                'Enter each participant\'s pre-training total score in the '
                'Pre/Post Learning Scores table on this session.'))
        return self.action_invite_selected()

    def action_start(self):
        """Scheduled -> Ongoing: open the attendance roster for L&D staff."""
        today = fields.Date.today()
        for rec in self:
            rec._expire_pending_invitations()
            if rec.status != 'scheduled':
                raise UserError(_('Only scheduled sessions can be started.'))
            if not rec.date_start:
                raise UserError(_('Session start date is not defined.'))
            if not self.env.context.get('test_skip_date_check') and fields.Date.to_date(rec.date_start) > today:
                raise UserError(_(
                    'Cannot start session %s before its scheduled start date (%s). Today is %s.'
                ) % (rec.name, fields.Date.to_date(rec.date_start), today))
            enrolled = rec._accepted_attendance_enrollments().filtered(
                lambda row: row.state == 'enrolled')
            if not enrolled:
                raise UserError(_(
                    'Cannot start session %s: No participants accepted their invitations. Invite and confirm participants before starting.'
                ) % rec.name)
            if not rec.trainer_ids:
                raise UserError(_(
                    'Cannot start session %s: At least one trainer must be assigned.'
                ) % rec.name)
            rec._validate_venue_choice()

            rec._write_workflow_status('ongoing')
            rec.message_post(body=_('Session %s started - attendance sheet opened for L&D staff.') % rec.name)
            rec._notify_delivery_staff(
                _('Record training attendance'),
                _('Session %s has started. Record participant attendance.') % rec.name)

    def action_complete(self):
        """Ongoing -> Completed: delivery finished.

        Posts the attendance summary; enrolled participants transition to completed.
        """
        today = fields.Date.today()
        for rec in self:
            rec._expire_pending_invitations()
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
            accepted = rec._accepted_attendance_enrollments().filtered(
                lambda row: row.state == 'enrolled')
            if not accepted:
                raise UserError(_(
                    'Cannot complete session %s without participants who accepted their invitations.')
                    % rec.name)
            expected = {(enrollment.employee_id.id, day, slot)
                        for enrollment in accepted
                        for day, slot, _hours in rec._attendance_slots()}
            recorded = {(row.employee_id.id, row.attendance_date, row.attendance_slot)
                        for row in rec.attendance_ids}
            if expected - recorded:
                raise UserError(_(
                    'Cannot complete session %s: %s attendance marks are missing. '
                    'Record Present or Absent for every scheduled date and period.')
                    % (rec.name, len(expected - recorded)))

            category = rec.course_id.category if rec.course_id else 'developmental'
            rule = self.env['eds.certificate.rule'].sudo().search([
                ('active', '=', True), ('category', '=', category),
            ], order='id desc', limit=1)
            minimum = (rule.min_attendance_pct if rule and rule.require_attendance else
                       0.0 if rule else 80.0)
            scheduled_periods = len(rec._attendance_slots())
            present_counts = {}
            for mark in rec.attendance_ids.filtered('attended'):
                present_counts[mark.employee_id.id] = present_counts.get(mark.employee_id.id, 0) + 1
            attendance_pct = {
                row.employee_id.id: (
                    100.0 * present_counts.get(row.employee_id.id, 0) / scheduled_periods
                    if scheduled_periods else 0.0)
                for row in accepted
            }
            completing = accepted.filtered(lambda row:
                present_counts.get(row.employee_id.id, 0) > 0
                and attendance_pct[row.employee_id.id] >= minimum)
            incomplete = accepted.filtered(lambda row:
                present_counts.get(row.employee_id.id, 0) > 0
                and row not in completing)
            absent = accepted - completing - incomplete
            if rec.commitment_required and completing.filtered(
                    lambda row: not row.commitment_accepted_at):
                raise UserError(_(
                    'Every completing participant must accept the session commitment before completion.'))

            rec._write_workflow_status('completed')
            enrolled = completing
            enrolled.write({'state': 'completed'})
            incomplete.write({'state': 'incomplete'})
            absent.write({'state': 'absent'})
            rec._create_completed_training_commitments(enrolled)

            rec.message_post(
                body=_('Session %s completed. L&D has recorded participant attendance.') % rec.name
            )
            rec._sync_plan_line_status()
            rec._distribute_completion_evaluations()
            self.env['eds.certificate']._sync_session_candidates(rec)
            for row in incomplete | absent:
                message = (_('You attended %s but did not meet the %.1f%% completion attendance requirement.')
                           % (rec.course_id.name or rec.program_name, minimum)
                           if row in incomplete else
                           _('No attended periods were recorded for your %s session.')
                           % (rec.course_id.name or rec.program_name))
                employee = row.employee_id.sudo()
                employee_user = employee.user_id
                if employee_user:
                    notify_action(row.sudo(), employee_user,
                                  _('Training attendance outcome'), message,
                                  action_required=False)
                elif employee.work_contact_id:
                    row.sudo().message_post(
                        body=message, partner_ids=[employee.work_contact_id.id])
            rec._notify_assessment_coordinators(_(
                'Enter each participant\'s post-training total score in the '
                'Pre/Post Learning Scores table on this session.'))

    def _create_completed_training_commitments(self, enrollments):
        self.ensure_one()
        if not self.commitment_required:
            return
        Commitment = self.env['training.commitment'].sudo()
        for enrollment in enrollments:
            if Commitment.search_count([('eds_enrollment_id', '=', enrollment.id)]):
                continue
            start = fields.Date.to_date(self.date_end)
            end = start + relativedelta(years=enrollment.commitment_years_at_accept) - timedelta(days=1)
            Commitment.create({
                'commitment_id': enrollment.employee_id.id,
                'training_reference': self.name,
                'training_type': self.course_id.name or self.program_name,
                'commitment_duration': enrollment.commitment_years_at_accept,
                'start_date': start,
                'end_date': end,
                'terms': enrollment.commitment_terms_at_accept,
                'state': 'active',
                'eds_session_id': self.id,
                'eds_enrollment_id': enrollment.id,
                'eds_accepted_at': enrollment.commitment_accepted_at,
            })

    def _notify_assessment_coordinators(self, message):
        """Prompt L&D staff to enter total learning scores on the session."""
        title = (_('Record pre-training scores') if 'pre-training' in message
                 else _('Record post-training scores'))
        self._notify_delivery_staff(title, message)

    def _notify_delivery_staff(self, title, message):
        """Notify EDS staff responsible for session delivery administration."""
        officer_group = self.env.ref('employee_development_system.group_eds_officer').sudo()
        for session in self:
            users = officer_group.user_ids.filtered(
                lambda user: user.active and session.company_id.id in user.company_ids.ids)
            creator = session.create_uid.sudo()
            if (creator.has_group('employee_development_system.group_eds_officer')
                    and session.company_id.id in creator.company_ids.ids):
                users |= creator
            notify_action(session, users, title, message)

    def _notify_assigned_trainers(self, trainers=None, *, reschedule_void=False):
        """Tell registered trainers about their assigned course and schedule."""
        for session in self:
            assigned = trainers if trainers is not None else session.trainer_ids
            trainer_users = assigned.mapped('employee_id').sudo().mapped('user_id')
            partners = assigned.mapped('external_partner_id') - trainer_users.mapped('partner_id')
            if not partners and not trainer_users:
                continue
            course_name = session.course_id.name or session.program_name or session.name
            if reschedule_void:
                message = _(
                    'The previous delivery assignment for %s from %s to %s has been '
                    'withdrawn for rescheduling. Those dates are no longer confirmed. '
                    'A new assignment notice will follow if you are assigned to the '
                    'revised schedule.') % (course_name, session.date_start, session.date_end)
                title = _('Training delivery rescheduled')
            else:
                venue_name = session._training_location_label()
                message = _(
                    'You are assigned to deliver %s from %s to %s. '
                    'Location/arrangement: %s.') % (
                        course_name, session.date_start, session.date_end, venue_name)
                title = _('Training delivery assignment')
            notify_action(session, trainer_users, title, message,
                          action_required=False)
            if partners:
                session.message_post(body=message, partner_ids=partners.ids,
                                     author_id=self.env.user.partner_id.id)

    def _require_ld_delivery_access(self):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            raise AccessError(_('Only L&D staff may view or record attendance and assessment results.'))

    def _require_reschedule_access(self):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            raise AccessError(_('Only L&D staff may reschedule training sessions.'))
        self.check_access('write')

    def _distribute_completion_evaluations(self):
        """Open the participant survey and the coach's later behavior review."""
        for session in self:
            instrument = (session.level1_session_instrument_id
                          or session.course_id.level1_instrument_id) or self.env.ref(
                'employee_development_system.inst_level1_standard', raise_if_not_found=False)
            if not instrument or instrument.state != 'published' or not instrument.question_ids:
                raise ValidationError(_(
                    'Publish the session Level 1 questions before completing training.'))
            recipients = session.enrollment_ids.filtered(
                lambda e: e.state in ('completed', 'incomplete'))
            unreachable = recipients.filtered(
                lambda row: not (
                    (row.employee_id.sudo().user_id.active
                     and not row.employee_id.sudo().user_id.share
                     and row.employee_id.sudo().user_id.partner_id)
                    or row.employee_id.sudo().work_email
                    or row.employee_id.sudo().work_contact_id.email
                    or row.employee_id.sudo().user_id.partner_id.email))
            if unreachable:
                raise UserError(_(
                    'Add a work email or user account for these participants '
                    'before sending Level 1 feedback: %s') % ', '.join(
                        unreachable.sudo().mapped('employee_id.name')))
            for enrollment in recipients:
                employee = enrollment.employee_id.sudo()
                existing = self.env['eds.evaluation.level1'].sudo().search([
                    ('session_id', '=', session.id), ('employee_id', '=', employee.id)], limit=1)
                if not existing:
                    existing = self.env['eds.evaluation.level1'].sudo().create({
                        'session_id': session.id, 'employee_id': employee.id,
                        'instrument_id': instrument.id,
                    })
                active_user = (employee.user_id if employee.user_id.active
                               and not employee.user_id.share else False)
                partner = (active_user.partner_id if active_user else
                           employee.work_contact_id.filtered('email')
                           or employee.user_id.partner_id.filtered('email'))
                if existing.state == 'distributed' and not existing.notification_sent_at:
                    message = _('Please complete your training feedback for %s.') % session.name
                    if active_user:
                        notified = notify_action(
                            existing, employee.user_id,
                            _('Complete training feedback'), message)
                        if not notified and employee.user_id.id == self.env.uid:
                            # The generic notifier excludes its actor. Use the
                            # system sender so a participant who completes the
                            # session also receives an inbox item and popup.
                            notified = notify_action(
                                existing.with_user(SUPERUSER_ID),
                                employee.user_id,
                                _('Complete training feedback'), message)
                        if notified:
                            existing.notification_sent_at = fields.Datetime.now()
                    elif partner or employee.work_email:
                        link = '/web#id=%s&amp;model=eds.evaluation.level1&amp;view_type=form' % existing.id
                        body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
                            escape(message), Markup(link), escape(_('Open feedback survey')))
                        if partner:
                            existing.message_post(body=body, partner_ids=[partner.id],
                                                  notify_skip_followers=True)
                        else:
                            absolute_link = (existing.get_base_url().rstrip('/')
                                             + link.replace('&amp;', '&'))
                            email_body = Markup('<p>%s</p><p><a href="%s">%s</a></p>') % (
                                escape(message), escape(absolute_link),
                                escape(_('Open feedback survey')))
                            existing.env['mail.mail'].sudo().create({
                                'subject': _('Complete training feedback'),
                                'body_html': str(email_body),
                                'email_to': employee.work_email,
                            })
                        existing.notification_sent_at = fields.Datetime.now()
                coach = employee.coach_id
                manager = (coach if coach and coach.user_id and coach.user_id.active
                           else employee.parent_id)
                if (enrollment.state == 'completed' and manager and manager.user_id
                        and manager.user_id.active and not manager.user_id.share
                        and not self.env['eds.evaluation.level3'].search([
                        ('session_id', '=', session.id), ('employee_id', '=', employee.id)], limit=1)):
                    notification_at, period = self.env[
                        'eds.evaluation.level3']._configured_notification_time()
                    review = self.env['eds.evaluation.level3'].create({
                        'session_id': session.id, 'employee_id': employee.id,
                        'manager_id': manager.id,
                        'due_date': notification_at.date(),
                        'notification_at': notification_at,
                        'evaluation_period': period,
                        'line_ids': ([(0, 0, {
                            'competency_id': question.competency_id.id,
                            'behavior_description': question.prompt,
                        }) for question in session.level3_question_ids]
                                     if session.level3_question_ids else
                                     [(0, 0, {'competency_id': competency.id})
                                      for competency in session.course_id.competency_line_ids.mapped(
                                          'competency_id')]),
                    })
            if not self.env['eds.evaluation.level4'].search([('session_id', '=', session.id)], limit=1):
                notif_time = self.env['eds.evaluation.level4']._configured_notification_time()
                self.env['eds.evaluation.level4'].create({
                    'session_id': session.id,
                    'course_id': session.course_id.id,
                    'due_date': notif_time.date(),
                    'notification_at': notif_time,
                    'evaluator_id': self.env.uid,
                })

    def action_reschedule(self):
        """Scheduled/Ongoing -> Rescheduled: allow date edits, then confirm again ."""
        self._require_reschedule_access()
        for rec in self:
            if rec.status not in ('scheduled', 'ongoing'):
                raise UserError(_('Only scheduled or ongoing sessions can be rescheduled.'))
            if rec.attendance_ids:
                raise UserError(_(
                    'Attendance has already been recorded. Correct or remove the '
                    'attendance marks before rescheduling this session.'))
            rec._notify_assigned_trainers(reschedule_void=True)
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec._write_workflow_status('rescheduled')
            rec.enrollment_ids._reset_for_session_reschedule()
            rec.message_post(body=_(
                'Session %s is being rescheduled. Previous invitation responses '
                'and commitment acceptance were cleared; new invitations will '
                'be sent after confirmation.') % rec.name)

    def action_mark_all_attended(self):
        """Quickly mark all roster records as attended."""
        self._require_ld_delivery_access()
        for rec in self:
            rec._ensure_attendance_records()
            accepted = set(rec._accepted_attendance_enrollments().mapped('employee_id').ids)
            rec.attendance_ids.filtered(
                lambda mark: mark.employee_id.id in accepted).write({'attended': True})
            rec.message_post(body=_("All session participants marked as attended."))
            rec._sync_attendance_summaries()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {
                    'res_model': self._name,
                    'res_id': self.id,
                    'title': _('Attendance Marked'),
                    'message': _('All session participants marked as attended.'),
                    'type': 'success',
                },
            }
        return True

    def action_populate_attendance(self):
        """Ensure attendance roster and summaries are synchronized with empty days by default."""
        self._require_ld_delivery_access()
        self.check_access('write')
        for rec in self:
            # Clean up any dummy unrecorded rows that have no notes
            rec.attendance_ids.filtered(lambda a: not a.attended and not (a.notes or '').strip()).unlink()
            rec._sync_attendance_summaries()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {
                    'res_model': self._name,
                    'res_id': self.id,
                    'title': _('Attendance Roster Ready'),
                    'message': _('Attendance sheet is synchronized. Days are empty by default. Click any cell to mark Present (P) or Absent (A).'),
                    'type': 'success',
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attendance Roster Ready'),
                'message': _('Attendance sheet is synchronized. Days are empty by default. Click any cell to mark Present (P) or Absent (A).'),
                'type': 'success',
                'sticky': False,
            },
        }

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
        """Rescheduled -> Scheduled: re-validate conflicts and re-book."""
        self._require_reschedule_access()
        for rec in self:
            if rec.status != 'rescheduled':
                raise UserError(_('Only rescheduled sessions can be confirmed again.'))
            if not rec.date_start or not rec.date_end:
                raise UserError(_('Set the new session dates before confirming the reschedule.'))
            if not rec.response_deadline or rec.response_deadline <= fields.Datetime.now():
                raise UserError(_(
                    'Set a future invitation response deadline before confirming '
                    'the rescheduled session.'))
            if rec.batch_id and rec.batch_id.course_id != rec.course_id:
                raise UserError(_(
                    'The selected cohort must belong to the session training program.'))
            if rec.plan_line_id or rec.unscheduled_request_id:
                sourced = rec._sourcing_values_for_plan_line(
                    rec.plan_line_id, rec.unscheduled_request_id)
                sourcing = self.env['eds.course.vendor.selection'].browse(
                    sourced['sourcing_id'])
                if rec.internal_fallback:
                    if (sourcing.line_ids.filtered(lambda bid: bid.status == 'awarded')
                            or sourced['delivery_method'] == 'internal'):
                        raise UserError(_(
                            'Internal fallback is available only when external '
                            'delivery has no awarded provider.'))
                    if not (rec.internal_fallback_reason or '').strip():
                        raise UserError(_(
                            'Explain why this session is changing to internal delivery.'))
                    if rec.delivery_method != 'internal':
                        raise UserError(_(
                            'Internal fallback must use internal delivery.'))
                elif (rec.delivery_method == 'internal'
                      and sourced['delivery_method'] != 'internal'):
                    raise UserError(_(
                        'Use the justified internal fallback for an externally '
                        'sourced program without an awarded provider.'))
            rec._check_awarded_bid_source()
            if rec.delivery_method != 'internal':
                sourcing, hotel = rec._sourcing_for_plan_line(
                    rec.plan_line_id, rec.unscheduled_request_id)
                winner = rec.awarded_bid_id
                if (not sourcing or sourcing.state != 'awarded'
                        or not winner or winner.selection_id != sourcing
                        or winner.status != 'awarded'
                        or winner.vendor_id != rec.awarded_provider_id):
                    raise UserError(_(
                        'Select an awarded provider from this session’s sourcing before '
                        'confirming the reschedule.'))
                if hotel:
                    expected_scope = ('international' if hotel.delivery_method == 'international'
                                      else 'local')
                    if hotel.awarded_venue_id.location_scope != expected_scope:
                        raise UserError(_(
                            'The awarded venue location does not match its hotel sourcing arrangement.'))
            if not rec.trainer_ids:
                raise UserError(_(
                    'Assign the internal ToT trainer or external organization trainer '
                    'before confirming the reschedule.'))
            if rec.delivery_method == 'internal':
                if rec.trainer_ids.filtered(
                        lambda trainer: trainer.trainer_type != 'internal'
                        or not trainer.tot_certified or trainer.state != 'active'):
                    raise UserError(_(
                        'Internal delivery requires certified internal ToT trainers.'))
            elif not rec.awarded_provider_id:
                raise UserError(_(
                    'Complete training provider sourcing before confirming external delivery.'))
            elif rec.trainer_ids.filtered(
                    lambda trainer: trainer.state != 'active'
                    or trainer.trainer_type != 'external'
                    or trainer.external_provider_id != rec.awarded_provider_id):
                raise UserError(_(
                    'External trainers must belong to the selected training organization.'))
            rec._validate_venue_choice()
            rec._check_session_conflicts()
            rec._write_workflow_status('scheduled')
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'hall_id': rec.hall_id.id if rec.hall_id else False,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s rescheduled and confirmed .') % rec.name)
            rec._notify_assigned_trainers()
            rec._notify_delivery_staff(
                _('Training schedule reconfirmed'),
                _('Session %s has been rescheduled for %s to %s. Review any '
                  'pre-training total scores and delivery preparations against '
                  'the revised dates.') % (rec.name, rec.date_start, rec.date_end))
            rec.enrollment_ids._reinvite_after_session_reschedule()

    def action_cancel(self):
        """Cancel the session, release the venue, cancel enrollments and notify ."""
        for rec in self:
            if rec.status in ('completed', 'cancelled'):
                raise UserError(_('Completed or cancelled sessions cannot be cancelled again.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec._write_workflow_status('cancelled')
            rec.enrollment_ids._cancel_rescheduled_invitations()
            rec._notify_participants(_('Session %s has been cancelled.') % rec.name)
            for enrollment in rec.enrollment_ids.filtered(
                    lambda e: e.state in ('invited', 'enrolled', 'waitlisted')):
                enrollment.action_cancel()

    def _notify_participants(self, message, *, remind_invited=False):
        """Notify each participant on their own enrollment, not the staff session."""
        self.ensure_one()
        # Keep the operational audit on the session without mailing its full
        # staff form link to participant followers.
        self.with_context(eds_popup_managed=True).message_post(
            body=Markup('<p>%s</p>') % escape(str(message)),
            subtype_xmlid='mail.mt_note', notify_skip_followers=True)
        active_enrollments = self.enrollment_ids.filtered(
            lambda e: e.state in ('invited', 'enrolled', 'waitlisted'))
        notified_users = set()
        for enrollment in active_enrollments:
            user = enrollment.employee_id.sudo().user_id
            if not user or user.id in notified_users:
                continue
            notified_users.add(user.id)
            if remind_invited and enrollment.state == 'invited':
                notify_action(enrollment.sudo(), user, _('Training invitation'), message)
            else:
                notify_action(enrollment.sudo(), user, _('Training schedule update'),
                              message, action_required=False)

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
            'context': {'default_session_id': self.id, 'default_entry_method': 'manual'},
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

    # ── attendance & delivery helpers ──
    def action_open_materials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/eds/session/{self.id}/materials',
            'target': 'new',
        }

    def _ensure_attendance_records(self, *, attended=True):
        """Create missing participant/date/slot rows without changing existing marks."""
        self.ensure_one()
        slots = self._attendance_slots()
        if not slots:
            raise UserError(_('Set the session start and end dates before preparing attendance.'))
        existing = {(row.employee_id.id, row.attendance_date, row.attendance_slot)
                    for row in self.attendance_ids}
        employee_ids = set(self._accepted_attendance_enrollments().mapped('employee_id').ids)
        if not employee_ids:
            raise UserError(_('Enroll at least one accepted participant before preparing attendance.'))
        values = []
        for employee_id in sorted(employee_ids):
            for attendance_date, slot, _hours in slots:
                key = (employee_id, attendance_date, slot)
                if key not in existing:
                    values.append({
                        'session_id': self.id, 'employee_id': employee_id,
                        'attendance_date': attendance_date, 'attendance_slot': slot,
                        'attended': attended, 'recorded_by': self.env.user.id,
                        'company_id': self.company_id.id,
                    })
        if values:
            # HR employee relations are internal to this EDS operation. The
            # caller has session write access, while creating the derived rows
            # must not grant Employee-module access to L&D staff.
            rows = self.env['eds.session.attendance'].sudo().with_context(
                eds_defer_attendance_refresh=True)
            created = rows.browse()
            for start in range(0, len(values), 500):
                created |= rows.create(values[start:start + 500])
            created._refresh_program_attendance()
        self._sync_attendance_summaries()
        return len(values)

    def action_refresh_attendance_summary(self):
        """Manually refresh attendance summary and report."""
        self._sync_attendance_summaries()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {
                    'res_model': self._name,
                    'res_id': self.id,
                    'title': _('Attendance Report Updated'),
                    'message': _('Attendance summary and report have been refreshed.'),
                    'type': 'success',
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Attendance Report Updated'),
                'message': _('Attendance summary and report have been refreshed.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def _sync_attendance_summaries(self):
        """Synchronize the participant attendance summary records for reporting."""
        Summary = self.env['eds.session.attendance.summary'].sudo()
        threshold = float(self.env['ir.config_parameter'].sudo().get_param('eds.min_attendance_pct', '80.0') or 80.0)
        for session in self:
            attendance_emps = session.attendance_ids.mapped('employee_id')
            # This report mirrors recorded attendance. An enrolled employee
            # without any attendance marks has no summary row, and deleting
            # their last mark removes the row during this synchronization.
            all_emps = attendance_emps

            slots = session._attendance_slots()
            scheduled_slot_count = len(slots) if slots else 0

            existing_summaries = Summary.search([('session_id', '=', session.id)])
            to_delete = existing_summaries.filtered(lambda s: s.employee_id not in all_emps)
            if to_delete:
                to_delete.unlink()
                existing_summaries -= to_delete

            for emp in all_emps:
                emp_attendance = session.attendance_ids.filtered(lambda a: a.employee_id == emp)
                recorded_count = len(emp_attendance)
                present_count = len(emp_attendance.filtered('attended'))
                total_slots = max(recorded_count, scheduled_slot_count)
                absent_count = recorded_count - present_count
                unrecorded_count = max(0, total_slots - recorded_count)
                pct = round(present_count * 100.0 / total_slots, 2) if total_slots else 0.0
                meets = bool(total_slots) and (pct >= threshold)
                status_val = 'meets' if meets else 'below'

                existing = existing_summaries.filtered(lambda s: s.employee_id == emp)
                vals = {
                    'total_slots': total_slots,
                    'present_count': present_count,
                    'absent_count': absent_count,
                    'unrecorded_count': unrecorded_count,
                    'attendance_percentage': pct,
                    'min_threshold': threshold,
                    'meets_min_attendance': meets,
                    'status': status_val,
                    'company_id': session.company_id.id or self.env.company.id,
                }
                if existing:
                    existing.write(vals)
                else:
                    Summary.create({
                        'session_id': session.id,
                        'employee_id': emp.id,
                        **vals,
                    })

    def _attendance_slots(self):
        """Scheduled local dates and their attendance periods with planned hours."""
        self.ensure_one()
        if not self.date_start or not self.date_end:
            return []
        timezone = self.company_id.resource_calendar_id.tz or self.env.user.tz or 'UTC'
        local_session = self.with_context(tz=timezone)
        start = fields.Datetime.context_timestamp(local_session, self.date_start).replace(tzinfo=None)
        end = fields.Datetime.context_timestamp(local_session, self.date_end).replace(tzinfo=None)
        if (end.date() - start.date()).days > 365:
            raise UserError(_('Attendance supports sessions of up to 366 calendar days.'))
        if end.date() < start.date():
            return []
        day_count = (end.date() - start.date()).days + 1

        slots = []
        day = start.date()
        while day <= end.date():
            if self.attendance_mode == 'daily':
                daily_h = round((self.duration_hours / day_count) if (self.duration_hours and day_count) else 8.0, 2)
                slots.append((day, 'day', daily_h))
            else:
                # Morning and Afternoon (split mode)
                half_h = round((self.duration_hours / (day_count * 2)) if (self.duration_hours and day_count) else 4.0, 2)
                slots.append((day, 'morning', half_h))
                slots.append((day, 'afternoon', half_h))
            day += timedelta(days=1)
        return slots

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
        sheet['A6'], sheet['B6'] = 'Attendance Recording', dict(
            self._fields['attendance_mode'].selection).get(self.attendance_mode, '')
        headers = ['Employee ID', 'Employee Name', 'Work Unit', 'Department', 'Job Position']
        for column, label in enumerate(headers, 1):
            sheet.cell(7, column, label)
        date_columns = []
        for attendance_date, slot, _hours in self._attendance_slots():
            column = len(headers) + len(date_columns) + 1
            sheet.cell(6, column, {'day': 'Daily', 'morning': 'Morning',
                                   'afternoon': 'Afternoon'}[slot])
            cell = sheet.cell(7, column, attendance_date)
            cell.number_format = 'yyyy-mm-dd'
            date_columns.append((column, attendance_date, slot))
        attendance = {(record.employee_id.id, record.attendance_date, record.attendance_slot): record
                      for record in self.attendance_ids}
        participants = self._accepted_attendance_enrollments().sorted(
                key=lambda row: row.employee_id.sudo().name or '')
        for row_number, enrollment in enumerate(participants, 8):
            employee = enrollment.employee_id.sudo()
            values = [employee.id, employee.name,
                      enrollment.work_unit_id.name or '', enrollment.department_id.name or '',
                      enrollment.job_position_id.name or '']
            for column, value in enumerate(values, 1):
                sheet.cell(row_number, column, value)
            for column, attendance_date, slot in date_columns:
                record = attendance.get((employee.id, attendance_date, slot))
                sheet.cell(row_number, column,
                           ('Present' if record.attended else 'Absent') if record else '')
        fill = PatternFill('solid', fgColor='541718')
        for cell in sheet[7]:
            cell.fill = fill
            cell.font = Font(color='FFFFFF', bold=True)
            cell.alignment = Alignment(horizontal='center')
        for key, width in {'A': 16, 'B': 30, 'C': 28, 'D': 25, 'E': 26}.items():
            sheet.column_dimensions[key].width = width
        for column, _day, _slot in date_columns:
            sheet.column_dimensions[sheet.cell(7, column).column_letter].width = 17
            if participants:
                validation = DataValidation(type='list', formula1='"Present,Absent"',
                                            allow_blank=True)
                validation.error = _('Choose Present or Absent.')
                validation.errorTitle = _('Invalid attendance')
                validation.showErrorMessage = True
                sheet.add_data_validation(validation)
                validation.add('%s8:%s%s' % (
                    sheet.cell(7, column).column_letter,
                    sheet.cell(7, column).column_letter, 7 + len(participants)))
                for row_number in range(8, 8 + len(participants)):
                    sheet.cell(row_number, column).protection = Protection(locked=False)
        sheet.protection.sheet = True
        sheet.protection.selectLockedCells = False
        sheet.protection.selectUnlockedCells = False
        sheet.freeze_panes = 'F8'
        output = io.BytesIO()
        workbook.save(output)
        attachment = self.env['ir.attachment'].with_context(skip_eds_file_check=True).create({
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
            'name': _('Training Assessments'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.assessment',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id, 'default_entry_method': 'manual'},
        }

    def _seed_assessment_questions(self, assessment_type):
        self._require_ld_delivery_access()
        self.ensure_one()
        self.env['eds.assessment.question'].seed_from_instrument(self, assessment_type)
        question_field = ('pre_assessment_question_ids' if assessment_type == 'pre'
                          else 'post_assessment_question_ids')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment questions'),
                'message': _('%s questions are ready for this session.') % len(self[question_field]),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_seed_pre_assessment_questions(self):
        return self._seed_assessment_questions('pre')

    def action_seed_post_assessment_questions(self):
        return self._seed_assessment_questions('post')

    def _distribute_assessment(self, assessment_type):
        self._require_ld_delivery_access()
        self.ensure_one()
        allowed_states = ('scheduled', 'ongoing') if assessment_type == 'pre' else ('ongoing', 'completed')
        if self.status not in allowed_states:
            raise UserError(_('%s assessments cannot be distributed at this session stage.') %
                            (_('Pre-training') if assessment_type == 'pre' else _('Post-training')))
        assessments = self.env['eds.assessment'].distribute_for_session(self, assessment_type)
        title = (_('Pre-training assessment') if assessment_type == 'pre'
                 else _('Post-training assessment'))
        message = _('Please answer the %s questions for %s (%s).') % (
            _('pre-training') if assessment_type == 'pre' else _('post-training'),
            self.course_id.name or self.program_name or self.name, self.name)
        employee_action = self.env.ref('employee_development_system.action_eds_assessment_own')
        employee_form = self.env.ref('employee_development_system.view_eds_assessment_employee_form')
        for assessment in assessments:
            notify_action(assessment, assessment.employee_id.sudo().user_id, title, message,
                          action_id=employee_action.id, form_view_id=employee_form.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': _('%s new assessment(s) were sent. Previously sent or completed responses were left unchanged.') % len(assessments),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_distribute_pre_assessment(self):
        return self._distribute_assessment('pre')

    def action_distribute_post_assessment(self):
        return self._distribute_assessment('post')

    def action_open_assessment_import(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        action = self.env.ref('employee_development_system.action_eds_assessment_import').read()[0]
        action['context'] = dict(self.env.context, default_session_id=self.id)
        return action

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
