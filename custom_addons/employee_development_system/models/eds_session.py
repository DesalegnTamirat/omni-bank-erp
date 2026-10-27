# -*- coding: utf-8 -*-

import base64
import io
from datetime import date, datetime, time, timedelta
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import notify_action
from .eds_currency_policy import validate_delivery_currency

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


class EdsVenueBooking(models.Model):
    """Booking of a venue for a session with conflict protection.

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
    venue_id = fields.Many2one('eds.venue', string='Venue', ondelete='restrict',
                               tracking=True, domain="[('active', '=', True)]")
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

    @api.model
    def _sourcing_values_for_plan_line(self, plan_line, unscheduled_request=None):
        request = unscheduled_request or (plan_line.unscheduled_request_id if plan_line else False)
        sourcing, hotel = self._sourcing_for_plan_line(plan_line, request)
        method = (sourcing.delivery_method or (request.delivery_method if request else False)
                  or (plan_line.delivery_method if plan_line else 'internal'))
        winner = sourcing.line_ids.filtered(lambda line: line.status == 'awarded')[:1]
        values = {
            'delivery_method': method,
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
                session.plan_line_id, session.unscheduled_request_id)
            if session.internal_fallback:
                if values['awarded_provider_id'] or values['delivery_method'] == 'internal':
                    values.update({'internal_fallback': False, 'internal_fallback_reason': False})
                else:
                    values.update({'delivery_method': 'internal', 'awarded_provider_id': False})
            if not values['awarded_venue_id'] and session.venue_id == session.awarded_venue_id:
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

    @api.onchange('awarded_venue_id')
    def _onchange_awarded_venue_id(self):
        if self.awarded_venue_id:
            self.venue_id = self.awarded_venue_id

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
        self.awarded_venue_id = False
        self.venue_id = False
        self.trainer_ids = False
        self.internal_fallback = False
        self.internal_fallback_reason = False
        self.enrollment_ids = [(5, 0, 0)]
        self.omitted_suggestion_employee_ids = [(5, 0, 0)]
        self._onchange_certificate_course_defaults()

    @api.onchange('approved_plan_id')
    def _onchange_approved_plan_id(self):
        if self.plan_line_id.plan_id != self.approved_plan_id:
            self.plan_line_id = False
            self.course_id = False
            self.program_name = False
            self._onchange_certificate_course_defaults()

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.plan_line_id:
            self.enrollment_ids = [(5, 0, 0)]
            self.omitted_suggestion_employee_ids = [(5, 0, 0)]
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
            self.awarded_venue_id = False
            self.trainer_ids = False

    @api.onchange('unscheduled_request_id')
    def _onchange_unscheduled_request_id(self):
        request = self.unscheduled_request_id
        if request:
            self.enrollment_ids = [(5, 0, 0)]
            self.omitted_suggestion_employee_ids = [(5, 0, 0)]
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
            self._onchange_certificate_course_defaults()

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

    def _onchange_sourcing_from_plan_line(self):
        if not self.plan_line_id and not self.unscheduled_request_id:
            return
        values = self._sourcing_values_for_plan_line(self.plan_line_id, self.unscheduled_request_id)
        if self.internal_fallback and not values['awarded_provider_id'] and values['delivery_method'] != 'internal':
            values.update({'delivery_method': 'internal', 'awarded_provider_id': False})
        self.delivery_method = values['delivery_method']
        self.awarded_provider_id = values['awarded_provider_id']
        self.awarded_venue_id = values['awarded_venue_id']
        if values['awarded_venue_id']:
            self.venue_id = values['awarded_venue_id']
        if self.delivery_method != 'internal':
            winner = self._sourcing_for_plan_line(self.plan_line_id, self.unscheduled_request_id)[0].line_ids.filtered(
                lambda line: line.status == 'awarded')[:1]
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
    enrolled_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_enrolled_employee_ids',
        string='Enrolled Employees',
        help='Employees confirmed or attended for this session.')
    enrolled_count = fields.Integer(string='Enrolled', compute='_compute_enrollment_counts')
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
    conflict_flag = fields.Boolean(
        string='Conflict', compute='_compute_conflict_flag', search='_search_conflict_flag',
        help='True when the venue or a trainer is already engaged on an overlapping slot.')
    booking_ids = fields.One2many('eds.venue.booking', 'session_id', string='Venue Bookings')
    booking_id = fields.Many2one('eds.venue.booking', string='Current Booking',
                                 compute='_compute_booking_id')

    # ── attendance & delivery tracking ──
    attendance_ids = fields.One2many(
        'eds.session.attendance', 'session_id', string='Attendance Records',
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

    @api.depends('enrollment_ids.state', 'enrollment_ids.employee_id',
                 'enrollment_ids.response_date', 'enrollment_ids.nomination_id.employee_confirmed')
    def _compute_enrolled_employee_ids(self):
        for rec in self:
            rec.enrolled_employee_ids = rec._accepted_attendance_enrollments().mapped('employee_id')

    def _accepted_attendance_enrollments(self):
        self.ensure_one()
        return self.enrollment_ids.filtered(
            lambda row: row.state in ('enrolled', 'completed', 'absent')
            and (not row.nomination_id or row.response_date
                 or row.nomination_id.employee_confirmed == 'confirmed'))

    def _attendance_roster_enrollments(self):
        """Employees shown on the session roster, including selected draft suggestions."""
        self.ensure_one()
        return self.enrollment_ids.filtered(
            lambda row: (row.state == 'suggested' and row.selected)
            or row.state in ('invited', 'enrolled', 'completed', 'absent'))

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
            rec.enrolled_count = len(rec.enrollment_ids.filtered(
                lambda e: e.state in ('enrolled', 'waitlisted', 'completed', 'absent')
                and (not e.nomination_id or e.response_date
                     or e.nomination_id.employee_confirmed == 'confirmed')))
            rec.pending_count = len(rec.enrollment_ids.filtered(
                lambda e: e.state == 'invited' or e.state == 'suggested' and e.selected or (
                    e.state in ('enrolled', 'waitlisted') and e.nomination_id
                    and e.nomination_id.employee_confirmed == 'pending')))
            rec.waitlist_count = len(rec.enrollment_ids.filtered(lambda e: e.state == 'waitlisted'))

    def _expire_pending_invitations(self):
        """Expire only the opened sessions; no background job or full roster scan."""
        due = self.filtered(
            lambda rec: rec.status in ('scheduled', 'rescheduled', 'ongoing')
            and rec.response_deadline and rec.response_deadline < fields.Datetime.now())
        if due:
            due.mapped('enrollment_ids')._expire_overdue()

    def web_read(self, specification):
        self._expire_pending_invitations()
        return super().web_read(specification)

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

    @api.onchange('date_start', 'date_end', 'venue_id', 'trainer_ids')
    def _onchange_conflict_check(self):
        """Warn (but do not block) on venue/trainer conflicts during editing."""
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
                    'title': _('Scheduling Conflict'),
                    'message': '\n'.join(conflicts),
                },
            }

    @api.model
    def _session_source_key(self, values):
        if values.get('status', 'draft') == 'cancelled':
            return False
        if values.get('source_type', 'annual_plan') == 'unscheduled':
            request_id = values.get('unscheduled_request_id')
            return ('unscheduled', request_id) if request_id else False
        plan_id, course_id = values.get('approved_plan_id'), values.get('course_id')
        return ('annual_plan', plan_id, course_id) if plan_id and course_id else False

    @api.model
    def _check_session_source_available(self, key, exclude_ids=()):
        if not key:
            return
        if key[0] == 'unscheduled':
            self.env.cr.execute(
                'SELECT id FROM eds_unscheduled_request WHERE id = %s FOR UPDATE', [key[1]])
            domain = [('source_type', '=', 'unscheduled'),
                      ('unscheduled_request_id', '=', key[1])]
        else:
            self.env.cr.execute(
                'SELECT id FROM eds_annual_plan WHERE id = %s FOR UPDATE', [key[1]])
            domain = [('source_type', '=', 'annual_plan'),
                      ('approved_plan_id', '=', key[1]), ('course_id', '=', key[2])]
        domain += [('status', '!=', 'cancelled')]
        if exclude_ids:
            domain.append(('id', 'not in', list(exclude_ids)))
        if self.search_count(domain):
            raise ValidationError(_(
                'A session already exists for this approved plan and course or unscheduled request. '
                'Use the existing session, or cancel it before creating a replacement.'))

    @api.constrains('source_type', 'approved_plan_id', 'course_id',
                    'unscheduled_request_id', 'status')
    def _check_unique_session_source(self):
        for session in self:
            session._check_session_source_available(session._session_source_key({
                'source_type': session.source_type,
                'approved_plan_id': session.approved_plan_id.id,
                'course_id': session.course_id.id,
                'unscheduled_request_id': session.unscheduled_request_id.id,
                'status': session.status,
            }), exclude_ids=session.ids)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_session_plan_course_unique
                ON eds_session (approved_plan_id, course_id)
             WHERE source_type = 'annual_plan' AND status != 'cancelled'
               AND approved_plan_id IS NOT NULL AND course_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_session_request_unique
                ON eds_session (unscheduled_request_id)
             WHERE source_type = 'unscheduled' AND status != 'cancelled'
               AND unscheduled_request_id IS NOT NULL
        """)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            internal_trainers = vals.get('trainer_ids') if vals.get('internal_fallback') else None
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.session') or _('New')
            if vals.get('awarded_venue_id'):
                vals['venue_id'] = vals['awarded_venue_id']
            if vals.get('plan_line_id'):
                plan_line = self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])
                request = plan_line.unscheduled_request_id
                vals['source_type'] = 'unscheduled' if request else 'annual_plan'
                vals['approved_plan_id'] = plan_line.plan_id.id
                vals['unscheduled_request_id'] = request.id or False
                vals['course_id'] = plan_line.course_id.id or False
                vals['program_name'] = plan_line.course_id.name or False
                vals.update(self._sourcing_values_for_plan_line(plan_line))
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
                    vals.update(self._sourcing_values_for_plan_line(plan_line))
                else:
                    vals.update(self._sourcing_values_for_plan_line(plan_line, request))
            elif vals.get('course_id'):
                vals['program_name'] = self.env['eds.course'].browse(vals['course_id']).name
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
        source_keys = set()
        for vals in vals_list:
            key = self._session_source_key(vals)
            if key in source_keys and key:
                raise ValidationError(_('Only one session can be created for each approved source and course.'))
            if key:
                source_keys.add(key)
                self._check_session_source_available(key)
        sessions = super().create(vals_list)
        for session in sessions:
            session._sync_plan_line_status()
            session._populate_suggested_enrollments()
        return sessions

    def write(self, vals):
        vals = dict(vals)
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
                rec.status != 'draft' or rec.attendance_ids for rec in self):
            raise UserError(_('Set attendance recording before scheduling or recording attendance.'))
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
            vals.update(self._sourcing_values_for_plan_line(plan_line))
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
                vals.update(self._sourcing_values_for_plan_line(plan_line))
            else:
                vals['plan_line_id'] = False
                vals.update(self._sourcing_values_for_plan_line(plan_line, request))
        elif 'course_id' in vals:
            vals['program_name'] = (
                self.env['eds.course'].browse(vals['course_id']).name
                if vals['course_id'] else False)
        elif 'program_name' in vals:
            vals.pop('program_name')
        if vals.get('awarded_venue_id'):
            vals = dict(vals, venue_id=vals['awarded_venue_id'])
        if {'source_type', 'approved_plan_id', 'plan_line_id', 'course_id',
            'unscheduled_request_id', 'status'} & vals.keys():
            for rec in self:
                key = self._session_source_key({
                    'source_type': vals.get('source_type', rec.source_type),
                    'approved_plan_id': vals.get('approved_plan_id', rec.approved_plan_id.id),
                    'course_id': vals.get('course_id', rec.course_id.id),
                    'unscheduled_request_id': vals.get('unscheduled_request_id', rec.unscheduled_request_id.id),
                    'status': vals.get('status', rec.status),
                })
                self._check_session_source_available(key, exclude_ids=rec.ids)
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
        if changed_sources or 'plan_line_id' in vals:
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
            evaluations = self.env['eds.evaluation.level1'].search([
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
            demands = rec.plan_line_id.course_demand_ids | rec.plan_line_id.course_demand_id
            if not demands:
                continue
            existing = {row.employee_id.id: row for row in rec.enrollment_ids}
            omitted = set(rec.omitted_suggestion_employee_ids.ids)
            to_create = []
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
                    'selected': True,
                })
            if to_create:
                self.env['eds.enrollment'].create(to_create)

    def action_refresh_suggested_employees(self):
        if any(rec.status != 'draft' for rec in self):
            raise UserError(_('Suggested employees can only be refreshed before scheduling. Add new participants directly to the scheduled roster.'))
        self._populate_suggested_enrollments()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
                    invitation.employee_id.name,
                    invitation.session_id.course_id.name,
                    ', '.join(missing.mapped('name')),
                ))
        return warnings

    def action_invite_selected(self):
        self._expire_pending_invitations()
        for rec in self:
            if rec.status not in ('scheduled', 'rescheduled'):
                raise UserError(_('Confirm the session schedule before sending invitations.'))
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
        """Print only issued certificates belonging to this exact session."""
        self.ensure_one()
        certs = self.env['eds.certificate'].search([
            ('session_id', '=', self.id), ('state', '=', 'issued'),
        ])
        if not certs:
            raise UserError(_('No issued certificates found for this training session.'))
        return self.env.ref('employee_development_system.action_report_eds_certificate').report_action(certs)

    # ── Session workflow ──────────────────────────────
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
                if sourced['awarded_provider_id'] or sourced['delivery_method'] == 'internal':
                    raise UserError(_('Internal fallback is available only when external delivery has no awarded provider.'))
                if not (rec.internal_fallback_reason or '').strip():
                    raise UserError(_('Explain why this session is changing to internal delivery.'))
            rec._sync_sourcing_from_plan_line()
            sourcing, hotel = rec._sourcing_for_plan_line(rec.plan_line_id, rec.unscheduled_request_id)
            if rec.delivery_method != 'internal':
                winner = sourcing.line_ids.filtered(lambda line: line.status == 'awarded')[:1]
                if not winner or not winner.vendor_id:
                    raise UserError(_('Complete training provider sourcing and award a provider for this program before scheduling.'))
                if not hotel:
                    raise UserError(_('Award a hotel or venue for this external program before scheduling.'))
            if hotel:
                expected_scope = ('international' if hotel.delivery_method == 'international'
                                  else 'local')
                if hotel.awarded_venue_id.location_scope != expected_scope:
                    raise UserError(_('The awarded venue location does not match its hotel sourcing arrangement.'))
            if rec.awarded_venue_id and rec.venue_id != rec.awarded_venue_id:
                raise UserError(_('This session must use its awarded hotel or venue.'))
            if not rec.venue_id:
                raise UserError(_('Choose an internal venue or award a hotel before confirming the schedule.'))
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
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s confirmed and scheduled.') % rec.name)
            rec._notify_assigned_trainers()
            rec._notify_assessment_coordinators(_(
                'Prepare pre-training questions. You may send them to employees, '
                'enter answers manually, or import completed responses.'))
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
            if not rec.venue_id and not rec.awarded_venue_id:
                raise UserError(_(
                    'Cannot start session %s: A venue must be specified.'
                ) % rec.name)

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
            rec._notify_assessment_coordinators(_(
                'Prepare post-training questions. You may send them to employees, '
                'enter answers manually, or import completed responses.'))

    def _notify_assessment_coordinators(self, message):
        """Prompt L&D staff to choose the assessment entry route."""
        title = (_('Prepare pre-training assessments') if 'pre-training' in message
                 else _('Prepare post-training assessments'))
        self._notify_delivery_staff(title, message)

    def _notify_delivery_staff(self, title, message):
        """Notify EDS staff responsible for session delivery administration."""
        officer_group = self.env.ref('employee_development_system.group_eds_officer')
        for session in self:
            users = officer_group.user_ids.filtered(
                lambda user: session.company_id in user.company_ids and user.active)
            if session.create_uid.has_group('employee_development_system.group_eds_officer'):
                users |= session.create_uid
            notify_action(session, users, title, message)

    def _notify_assigned_trainers(self, trainers=None):
        """Tell registered trainers about their assigned course and schedule."""
        for session in self:
            assigned = trainers if trainers is not None else session.trainer_ids
            trainer_users = assigned.mapped('employee_id.user_id')
            partners = assigned.mapped('external_partner_id') - trainer_users.mapped('partner_id')
            if not partners and not trainer_users:
                continue
            course_name = session.course_id.name or session.program_name or session.name
            venue_name = session.venue_id.name or _('To be confirmed')
            message = _('You are assigned to deliver %s from %s to %s at %s.') % (
                course_name, session.date_start, session.date_end, venue_name)
            notify_action(session, trainer_users, _('Training delivery assignment'), message,
                          action_required=False)
            if partners:
                session.message_post(body=message, partner_ids=partners.ids,
                                     author_id=self.env.user.partner_id.id)

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
                    })
                partner = employee.user_id.partner_id or employee.work_contact_id
                if partner and existing.state == 'distributed':
                    message = _('Please complete your training feedback for %s.') % session.name
                    if employee.user_id:
                        notify_action(existing, employee.user_id,
                                      _('Complete training feedback'), message)
                    else:
                        existing.message_post(body=message, partner_ids=[partner.id])
                manager = employee.parent_id
                if manager and manager.user_id and not self.env['eds.evaluation.level3'].search([
                        ('session_id', '=', session.id), ('employee_id', '=', employee.id)], limit=1):
                    notification_at, period = self.env[
                        'eds.evaluation.level3']._configured_notification_time()
                    review = self.env['eds.evaluation.level3'].create({
                        'session_id': session.id, 'employee_id': employee.id,
                        'manager_id': manager.id,
                        'due_date': notification_at.date(),
                        'notification_at': notification_at,
                        'evaluation_period': period,
                        'line_ids': [(0, 0, {'competency_id': competency.id}) for competency in
                                     session.course_id.competency_line_ids.mapped('competency_id')],
                    })

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
            accepted = set(rec._accepted_attendance_enrollments().mapped('employee_id').ids)
            rec.attendance_ids.filtered(
                lambda mark: mark.employee_id.id in accepted).write({'attended': True})
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
        """Rescheduled -> Scheduled: re-validate conflicts and re-book."""
        for rec in self:
            if rec.status != 'rescheduled':
                raise UserError(_('Only rescheduled sessions can be confirmed again.'))
            if not rec.date_start or not rec.date_end:
                raise UserError(_('Set the new session dates before confirming the reschedule.'))
            rec._check_session_conflicts()
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
            rec._notify_participants(
                _('Session %s is confirmed for %s to %s at %s. Please review your invitation or enrollment.')
                % (rec.name, rec.date_start, rec.date_end,
                   rec.venue_id.name or _('venue to be confirmed')),
                remind_invited=True)

    def action_cancel(self):
        """Cancel the session, release the venue, cancel enrollments and notify ."""
        for rec in self:
            if rec.status in ('completed', 'cancelled'):
                raise UserError(_('Completed or cancelled sessions cannot be cancelled again.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec._write_workflow_status('cancelled')
            rec._notify_participants(_('Session %s has been cancelled.') % rec.name)
            for enrollment in rec.enrollment_ids.filtered(
                    lambda e: e.state in ('invited', 'enrolled', 'waitlisted')):
                enrollment.action_cancel()

    def _notify_participants(self, message, *, remind_invited=False):
        """Notify enrolled participants on reschedule/cancel with direct action link."""
        self.ensure_one()
        action_link = f"/web#id={self.id}&model=eds.session"
        formatted_message = Markup(f"""<p>{escape(str(message))}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">👉 View Training Session</a>
</div>""")
        self.message_post(body=formatted_message)
        active_enrollments = self.enrollment_ids.filtered(
            lambda e: e.state in ('invited', 'enrolled', 'waitlisted'))
        employees = active_enrollments.mapped('employee_id')
        users = employees.mapped('user_id')
        if remind_invited:
            for invitation in active_enrollments.filtered(lambda row: row.state == 'invited'):
                user = invitation.employee_id.user_id
                if user:
                    notify_action(invitation.sudo(), user, _('Training invitation'), message)
                    users -= user
        notify_action(self, users, _('Training schedule update'), message, action_required=False)

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

    def _ensure_attendance_records(self):
        """Create every scheduled date/slot when marking the full roster present."""
        self.ensure_one()
        slots = self._attendance_slots()
        existing = {(row.employee_id.id, row.attendance_date, row.attendance_slot)
                    for row in self.attendance_ids}
        enrolled = self._accepted_attendance_enrollments().filtered(
            lambda row: row.state == 'enrolled')
        values = []
        for enrollment in enrolled:
            for attendance_date, slot, _hours in slots:
                key = (enrollment.employee_id.id, attendance_date, slot)
                if key not in existing:
                    values.append({
                        'session_id': self.id, 'employee_id': enrollment.employee_id.id,
                        'attendance_date': attendance_date, 'attendance_slot': slot,
                        'attended': True,
                    })
        if values:
            self.env['eds.session.attendance'].create(values)

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
        day_count = (end.date() - start.date()).days + 1
        # Older plan-generated sessions stored dates at midnight. Multi-day
        # sessions with identical start/end clock times also describe a daily
        # class, not continuous training through every intervening night.
        date_only = self.date_start.time() == self.date_end.time() == time.min
        same_clock_multiday = day_count > 1 and start.time() == end.time()
        if end <= start and not date_only:
            return []
        if date_only:
            daily_hours = (self.duration_hours or 8.0) / day_count
        elif same_clock_multiday:
            total_hours = self.duration_hours or 8.0
            daily_hours = total_hours / day_count if total_hours > 12 else total_hours
        else:
            daily_hours = 0.0
        regular_multiday = day_count > 1 and start.time() < end.time()
        slots = []
        day = start.date()
        while day <= end.date():
            midnight = datetime.combine(day, time.min)
            noon = midnight + timedelta(hours=12)
            next_day = midnight + timedelta(days=1)
            if date_only or same_clock_multiday:
                active_start = midnight + timedelta(hours=self.start_time)
                active_end = min(active_start + timedelta(hours=daily_hours), next_day)
            elif regular_multiday:
                active_start = datetime.combine(day, start.time())
                active_end = datetime.combine(day, end.time())
            else:
                active_start, active_end = start, end
            periods = ([('day', midnight, next_day)] if self.attendance_mode == 'daily'
                       else [('morning', midnight, noon), ('afternoon', noon, next_day)])
            for slot, period_start, period_end in periods:
                hours = (min(active_end, period_end) - max(active_start, period_start)).total_seconds() / 3600
                if hours > 0:
                    slots.append((day, slot, round(hours, 2)))
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
                key=lambda row: row.employee_id.name or '')
        for row_number, enrollment in enumerate(participants, 8):
            employee = enrollment.employee_id
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
            notify_action(assessment, assessment.employee_id.user_id, title, message,
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
