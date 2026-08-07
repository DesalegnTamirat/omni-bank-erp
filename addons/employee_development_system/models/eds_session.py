# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsVenue(models.Model):
    """Registered training venue (FREDS020/FR-EDS-019)."""
    _name = 'eds.venue'
    _description = 'Training Venue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='Venue Name', required=True, tracking=True)
    location = fields.Char(string='Location')
    capacity = fields.Integer(string='Capacity', default=30, tracking=True)
    facilities = fields.Text(string='Facilities / Equipment')
    active = fields.Boolean(string='Active', default=True)
    booking_ids = fields.One2many('eds.venue.booking', 'venue_id', string='Bookings')
    booking_count = fields.Integer(string='Bookings', compute='_compute_booking_count')

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
    """Booking of a venue for a session with conflict protection (FR-EDS-019/020).

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

    _sql_constraints = [
        ('date_range_valid', 'check(date_end > date_start)',
         'The booking end must be after its start!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.venue.booking') or _('New')
        return super().create(vals_list)

    @api.constrains('venue_id', 'date_start', 'date_end', 'state')
    def _check_venue_conflict(self):
        """No double-booking of a venue on overlapping slots (FR-EDS-019)."""
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
                    'Venue Conflict (FR-EDS-019): %s is already booked from %s to %s '
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
    """Cohort / batch grouping sessions of a course (FREDS023)."""
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
    session_count = fields.Integer(string='Sessions', compute='_compute_session_count')
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
    """A scheduled delivery of a course (FREDS020-023, FR-EDS-017...022).

    Carries the venue, trainers (constrained to the trainer register with matching
    competencies and availability - Task 4) and dates; enforces venue and trainer
    conflict checks (FR-EDS-019/020), and notifies participants on reschedule or
    cancellation (FR-EDS-022). Sessions are created from annual-plan lines on
    publication (FREDS024) and feed the planned-vs-actual variance (FREDS025).
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
                                        'monitoring (FREDS025).')
    batch_id = fields.Many2one('eds.batch', string='Batch / Cohort', ondelete='set null')
    date_start = fields.Datetime(string='Start Date', required=True, tracking=True)
    date_end = fields.Datetime(string='End Date', required=True, tracking=True)
    start_time = fields.Float(string='Start Time', default=8.5,
                              help='Start hour of the first day (e.g. 8.5 = 08:30).')
    duration_hours = fields.Float(string='Duration (Hours)', default=8.0, tracking=True)
    venue_id = fields.Many2one('eds.venue', string='Venue', ondelete='restrict',
                               tracking=True, domain="[('active', '=', True)]")
    trainer_ids = fields.Many2many(
        'eds.trainer', 'eds_session_trainer_rel', 'session_id', 'trainer_id',
        string='Trainers', tracking=True,
        help='Only active trainers from the register may be assigned (Task 4 register).')
    capacity = fields.Integer(
        string='Capacity', default=lambda self: self._get_default_capacity(),
        help='Maximum number of participants (default 25-30 from EDS settings, FREDS039).')
    approval_flow = fields.Selection([
        ('standard', 'Standard (Line Manager -> L&D)'),
        ('budget_hr', 'With Budget/HR Gate'),
    ], string='Approval Flow', default='standard',
        help='Per-program approval chain override (FR-EDS-026): programs involving budget '
             'add an explicit Budget/HR approval step.')
    nomination_ids = fields.One2many('eds.nomination', 'session_id', string='Nominations')
    nomination_count = fields.Integer(string='Nominations', compute='_compute_nomination_count')
    enrollment_ids = fields.One2many('eds.enrollment', 'session_id', string='Enrollments')
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
             '(FR-EDS-019/020).')
    booking_ids = fields.One2many('eds.venue.booking', 'session_id', string='Venue Bookings')
    booking_id = fields.Many2one('eds.venue.booking', string='Current Booking',
                                 compute='_compute_booking_id')

    # ── Task 7: attendance & delivery tracking (FREDS040/041/045) ─────────────
    attendance_ids = fields.One2many(
        'eds.session.attendance', 'session_id', string='Attendance Records')
    attendance_count = fields.Integer(string='Attendance', compute='_compute_delivery_counts')
    attendance_rate = fields.Float(
        string='Session Attendance %', compute='_compute_attendance_rate', store=True,
        digits=(5, 2),
        help='Attended / recorded participants for this session (FREDS040).')
    feedback_ids = fields.One2many('eds.feedback', 'session_id', string='Daily Feedback')
    feedback_count = fields.Integer(string='Feedback', compute='_compute_delivery_counts')
    assessment_ids = fields.One2many('eds.assessment', 'session_id', string='Assessments')
    assessment_count = fields.Integer(string='Assessment Count', compute='_compute_delivery_counts')
    international_training_ids = fields.One2many(
        'eds.international.training', 'session_id', string='International Training')
    international_training_count = fields.Integer(
        string='International Training Count', compute='_compute_delivery_counts')

    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('date_range_valid', 'check(date_end >= date_start)',
         'The session end must not be before its start!'),
        ('capacity_positive', 'check(capacity > 0)',
         'Session capacity must be greater than zero!'),
    ]

    @api.model
    def _get_default_capacity(self):
        """Default class size from EDS settings (BRD: 25-30, FREDS039)."""
        return self._get_int_param('eds.default_class_capacity', 30)

    @api.depends('date_start', 'venue_id', 'trainer_ids', 'status')
    def _compute_conflict_flag(self):
        for rec in self:
            rec.conflict_flag = bool(
                rec._get_venue_conflicts() or rec._get_trainer_conflicts()
                or rec._get_blocked_trainer_availability())

    def _search_conflict_flag(self, operator, value):
        """Search support for the computed conflict flag (e.g. the "Conflicts" filter)."""
        sessions = self.search([])
        target = bool(value)
        if operator in ('=', 'ilike', 'like'):
            matched = [s.id for s in sessions if s.conflict_flag == target]
        elif operator in ('!=', 'not ilike', 'not like'):
            matched = [s.id for s in sessions if s.conflict_flag != target]
        else:
            raise NotImplementedError(_('Operator %s is not supported on conflict_flag.') % operator)
        return [('id', 'in', matched)]

    @api.depends('booking_ids', 'booking_ids.state')
    def _compute_booking_id(self):
        for rec in self:
            active = rec.booking_ids.filtered(lambda b: b.state != 'cancelled')
            rec.booking_id = active[0] if active else False

    @api.depends('enrollment_ids', 'enrollment_ids.state')
    def _compute_enrollment_counts(self):
        """FR-EDS-027: live enrolled / waitlisted counts from the enrollments."""
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
        """Session-level attendance % (FREDS040)."""
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
        """Warn (but do not block) on venue/trainer conflicts during editing (FR-EDS-019/020)."""
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
                    'title': _('Scheduling Conflict (FR-EDS-019/020)'),
                    'message': '\n'.join(conflicts),
                },
            }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.session') or _('New')
        sessions = super().create(vals_list)
        for session in sessions:
            session._sync_plan_line_status()
        return sessions

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('date_start', 'date_end', 'status')):
            for rec in self:
                rec._sync_plan_line_status()
        if 'capacity' in vals:
            for rec in self:
                rec._promote_waitlisted()
        return res

    def _sync_plan_line_status(self):
        """FREDS025: reflect the session status on its annual plan line."""
        self.ensure_one()
        if not self.plan_line_id:
            return
        line = self.plan_line_id
        if self.status == 'completed':
            line.status = 'delivered'
        elif self.status == 'cancelled':
            line.status = 'cancelled'
        elif self.status in ('draft', 'scheduled', 'ongoing', 'rescheduled'):
            if line.status in ('planned', 'delayed', 'cancelled'):
                line.status = 'scheduled'

    # ── Conflict detection (FR-EDS-019/020) ──────────────────────────────────
    def _get_venue_conflicts(self):
        """Other sessions using the same venue on an overlapping window."""
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
        """Trainers whose availability register blocks this window (Task 4 availability)."""
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
        """Blocking enforcement of the venue + trainer conflict rules (FR-EDS-019/020)."""
        for rec in self:
            if rec.status in ('cancelled', 'completed'):
                continue
            venue = rec._get_venue_conflicts()
            if venue:
                raise ValidationError(_(
                    'Venue Conflict (FR-EDS-019): %s is already booked for session %s on an '
                    'overlapping slot.' % (rec.venue_id.name, venue[0].name)))
            trainers = rec._get_trainer_conflicts()
            if trainers:
                raise ValidationError(_(
                    'Trainer Conflict (FR-EDS-020): trainer(s) %s are already assigned to an '
                    'overlapping session.' % ', '.join(trainers.mapped('name'))))
            blocked = rec._get_blocked_trainer_availability()
            if blocked:
                raise ValidationError(_(
                    'Trainer Unavailable (FR-EDS-020): trainer(s) %s have a blocked availability '
                    'record in this period.' % ', '.join(blocked.mapped('name'))))

    # ── Session workflow (FREDS024/FR-EDS-022) ──────────────────────────────
    def action_confirm(self):
        """Draft -> Scheduled: validate conflicts + material gate and book the venue."""
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only draft sessions can be confirmed.'))
            if not rec.course_id and not rec.program_name:
                raise UserError(_('Link the session to a training program first.'))
            rec._check_session_conflicts()
            rec._check_material_approval()
            rec.status = 'scheduled'
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s confirmed and scheduled (FREDS024).') % rec.name)

    def action_start(self):
        """Scheduled -> Ongoing: delivery has begun.

        Attendance records are auto-created for every enrolled participant so the
        trainer only marks who attended (FREDS040).
        """
        for rec in self:
            if rec.status != 'scheduled':
                raise UserError(_('Only scheduled sessions can be started.'))
            rec.status = 'ongoing'
            rec._ensure_attendance_records()
            rec.message_post(body=_('Session %s started - attendance sheet opened for the '
                                    'trainer (FREDS040).') % rec.name)

    def action_complete(self):
        """Ongoing -> Completed: delivery finished.

        Posts the attendance summary; per-program attendance % and the 80% rule
        are computed on the attendance records (Task 10 certification reads them).
        """
        for rec in self:
            if rec.status != 'ongoing':
                raise UserError(_('Only ongoing sessions can be completed.'))
            rec.status = 'completed'
            present = len(rec.attendance_ids.filtered('attended'))
            total = len(rec.attendance_ids)
            rec.message_post(
                body=_('Session %s completed (FREDS025) - attendance %d/%d recorded '
                       '(FREDS040).') % (rec.name, present, total))

    def action_reschedule(self):
        """Scheduled/Ongoing -> Rescheduled: allow date edits, then confirm again (FR-EDS-022)."""
        for rec in self:
            if rec.status not in ('scheduled', 'ongoing'):
                raise UserError(_('Only scheduled or ongoing sessions can be rescheduled.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec.status = 'rescheduled'
            rec._notify_participants(_('Session %s has been rescheduled. Check the new dates.')
                                     % rec.name)

    def action_confirm_reschedule(self):
        """Rescheduled -> Scheduled: re-validate conflicts + material gate, re-book."""
        for rec in self:
            if rec.status != 'rescheduled':
                raise UserError(_('Only rescheduled sessions can be confirmed again.'))
            if not rec.date_start or not rec.date_end:
                raise UserError(_('Set the new session dates before confirming the reschedule.'))
            rec._check_session_conflicts()
            rec._check_material_approval()
            rec.status = 'scheduled'
            if rec.venue_id and not rec.booking_id:
                self.env['eds.venue.booking'].create({
                    'venue_id': rec.venue_id.id,
                    'session_id': rec.id,
                    'date_start': rec.date_start,
                    'date_end': rec.date_end,
                    'state': 'confirmed',
                })
            rec.message_post(body=_('Session %s rescheduled and confirmed (FR-EDS-022).') % rec.name)

    def action_cancel(self):
        """Cancel the session, release the venue, cancel enrollments and notify (FR-EDS-022)."""
        for rec in self:
            if rec.status in ('completed', 'cancelled'):
                raise UserError(_('Completed or cancelled sessions cannot be cancelled again.'))
            if rec.booking_id:
                rec.booking_id.action_cancel()
            rec.status = 'cancelled'
            for enrollment in rec.enrollment_ids.filtered(
                    lambda e: e.state in ('enrolled', 'waitlisted')):
                enrollment.action_cancel()
            rec._notify_participants(_('Session %s has been cancelled.') % rec.name)

    def _notify_participants(self, message):
        """FR-EDS-022: notify enrolled participants on reschedule/cancel (FR-EDS-029)."""
        self.ensure_one()
        self.message_post(body=message)
        partner_ids = self.enrollment_ids.filtered(lambda e: e.state == 'enrolled') \
            .mapped('employee_id').mapped('work_contact_id').filtered('id').ids
        if partner_ids:
            self.message_post(body=message, partner_ids=partner_ids)

    def _promote_waitlisted(self):
        """FR-EDS-028: FIFO promotion of this session's waitlist (delegates to enrollment)."""
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
        """Open the "Nominate for Session" wizard pre-filled with this session (FREDS038)."""
        self.ensure_one()
        return {
            'name': _('Nominate for Session'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.nomination.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
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

    # ── Task 7: attendance & delivery helpers (FREDS040/041/045) ─────────────
    def _check_material_approval(self):
        """FREDS045: a session whose course has materials cannot be confirmed until
        at least one material version is approved (quality + Director PPDD)."""
        self.ensure_one()
        if not self.course_id or not self.course_id.material_ids:
            return
        if not self.course_id.material_ids.filtered('is_approved'):
            raise UserError(_(
                'Training materials must be approved before the schedule is confirmed '
                '(FREDS045). Approve the materials on training program %s first.')
                % self.course_id.name)

    def _ensure_attendance_records(self):
        """Auto-create the attendance sheet for all enrolled participants (FREDS040)."""
        self.ensure_one()
        existing = self.attendance_ids.mapped('employee_id')
        enrolled = self.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
        for enrollment in enrolled:
            if enrollment.employee_id not in existing:
                self.env['eds.session.attendance'].create({
                    'session_id': self.id,
                    'employee_id': enrollment.employee_id.id,
                    'attended': True,
                })

    def action_view_attendance(self):
        self.ensure_one()
        return {
            'name': _('Attendance'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.session.attendance',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

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
