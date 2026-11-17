# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import notify_action, role_users


class EdsHotelSelection(models.Model):
    """Compare hotel bids for one approved plan program and pass the winner to sessions."""

    _name = 'eds.hotel.selection'
    _description = 'Hotel / Venue Selection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: _('New'), readonly=True, copy=False)
    source_type = fields.Selection([
        ('annual_plan', 'Approved Annual Plan'),
        ('unscheduled', 'Approved Unscheduled Request'),
    ], string='Sourcing Source', default='annual_plan', required=True, tracking=True)
    plan_line_id = fields.Many2one(
        'eds.annual.plan.line', string='Approved Plan Program',
        domain="[('plan_id.state', 'in', ('published', 'amended')), ('is_addendum', '=', False)]", tracking=True)
    unscheduled_request_id = fields.Many2one(
        'eds.unscheduled.request', string='Approved Unscheduled Request', tracking=True,
        domain="[('state', '=', 'approved'), ('course_id', '!=', False)]", index=True)
    annual_plan_id = fields.Many2one(
        'eds.annual.plan', compute='_compute_source_details', string='Annual Plan', store=True)
    course_id = fields.Many2one(
        'eds.course', compute='_compute_source_details', string='Catalog Course', store=True)
    program_name = fields.Char(compute='_compute_source_details', string='Program', store=True)
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local Hotel / External Venue'),
        ('international', 'International Hotel / Venue'),
    ], string='Venue Arrangement', required=True)
    planned_delivery_method = fields.Selection(
        [('internal', 'Internal / ToT'), ('local_external', 'Local External'),
         ('international', 'International')],
        compute='_compute_planned_delivery_method', string='Planned Delivery', readonly=True)
    delivery_override = fields.Boolean(string='Change Venue Arrangement', tracking=True)
    delivery_change_reason = fields.Char(string='Reason for Venue Change')
    internal_venue_id = fields.Many2one(
        'eds.venue', string='Bank Internal Venue',
        domain="[('active', '=', True), ('location_scope', '=', 'local')]",
        help='Choose a local bank facility from the venue register without a hotel bid.')
    currency_id = fields.Many2one('res.currency', string='Bid Currency', required=True,
                                  default=lambda self: currency_for_delivery(self.env, 'internal'))
    bid_ids = fields.One2many('eds.hotel.bid', 'selection_id', string='Hotel Bids')
    awarded_bid_ids = fields.Many2many(
        'eds.hotel.bid', compute='_compute_awarded_venues', string='Awarded Hotel Bids')
    awarded_venue_ids = fields.Many2many(
        'eds.venue', compute='_compute_awarded_venues', string='Awarded Hotels')
    awarded_venue_count = fields.Integer(
        string='Awarded Hotels Count', compute='_compute_awarded_venues')
    awarded_venue_id = fields.Many2one('eds.venue', compute='_compute_awarded_venue_id', store=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('evaluation', 'Evaluation'), ('awarded', 'Awarded'),
    ], default='draft', required=True, tracking=True)
    notes = fields.Text()

    @api.depends('source_type', 'plan_line_id.plan_id', 'plan_line_id.course_id',
                 'plan_line_id.program_name',
                 'unscheduled_request_id.annual_plan_id', 'unscheduled_request_id.course_id.name')
    def _compute_source_details(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                rec.annual_plan_id = rec.unscheduled_request_id.annual_plan_id
                rec.course_id = rec.unscheduled_request_id.course_id
                rec.program_name = rec.unscheduled_request_id.course_id.name
            else:
                rec.annual_plan_id = rec.plan_line_id.plan_id
                rec.course_id = rec.plan_line_id.course_id
                rec.program_name = rec.plan_line_id.program_name

    @api.depends('source_type', 'plan_line_id.delivery_method',
                 'unscheduled_request_id.delivery_method')
    def _compute_planned_delivery_method(self):
        for rec in self:
            rec.planned_delivery_method = rec._delivery_for_source(
                rec.plan_line_id, rec.unscheduled_request_id)

    @api.onchange('source_type')
    def _onchange_source_type(self):
        self.plan_line_id = False
        self.unscheduled_request_id = False

    @api.onchange('unscheduled_request_id')
    def _onchange_unscheduled_request_id(self):
        request = self.unscheduled_request_id
        self.plan_line_id = request.plan_line_ids[:1] if request else False
        if request:
            self.delivery_override = False
            self.delivery_change_reason = False
            self.delivery_method = self._delivery_for_source(self.plan_line_id, request)
            self.currency_id = currency_for_delivery(self.env, self.delivery_method)

    @api.model
    def _currency_for_line(self, line):
        return currency_for_delivery(self.env, self._delivery_for_line(line))

    @api.model
    def _delivery_for_line(self, line):
        return self._delivery_for_source(line, line.unscheduled_request_id)

    @api.model
    def _delivery_for_source(self, line, request):
        return (request.delivery_method if request else False) or (line.delivery_method if line else 'internal')

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.source_type != 'annual_plan':
            return
        self.delivery_override = False
        self.delivery_change_reason = False
        self.delivery_method = self._delivery_for_line(self.plan_line_id)
        self.currency_id = self._currency_for_line(self.plan_line_id)

    @api.onchange('delivery_method')
    def _onchange_delivery_method(self):
        if self.delivery_method:
            self.currency_id = currency_for_delivery(self.env, self.delivery_method)
        if self.delivery_method != 'internal':
            self.internal_venue_id = False

    @api.onchange('delivery_override')
    def _onchange_delivery_override(self):
        if not self.delivery_override:
            self.delivery_method = self._delivery_for_source(
                self.plan_line_id, self.unscheduled_request_id)
            self.delivery_change_reason = False
            self.currency_id = currency_for_delivery(self.env, self.delivery_method)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.hotel.selection') or _('New')
            if vals.get('unscheduled_request_id'):
                request = self.env['eds.unscheduled.request'].browse(vals['unscheduled_request_id'])
                vals['source_type'] = 'unscheduled'
                vals['plan_line_id'] = request.plan_line_ids[:1].id or False
                vals.setdefault('delivery_method', self._delivery_for_source(
                    request.plan_line_ids[:1], request))
            if vals.get('plan_line_id') and not vals.get('delivery_method'):
                vals['delivery_method'] = self._delivery_for_line(
                    self.env['eds.annual.plan.line'].browse(vals['plan_line_id']))
            if vals.get('plan_line_id') and not vals.get('currency_id'):
                vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
            if vals.get('delivery_method') and not vals.get('currency_id'):
                vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
            if vals.get('delivery_method') and vals.get('currency_id'):
                validate_delivery_currency(self.env, vals['delivery_method'], vals['currency_id'])
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if {'source_type', 'plan_line_id', 'unscheduled_request_id', 'delivery_method',
            'delivery_override', 'delivery_change_reason', 'internal_venue_id'} & vals.keys():
            if any(rec.state != 'draft' for rec in self):
                raise UserError(_('The venue arrangement cannot change after evaluation starts.'))
        if vals.get('unscheduled_request_id'):
            request = self.env['eds.unscheduled.request'].browse(vals['unscheduled_request_id'])
            vals.update({'source_type': 'unscheduled',
                         'plan_line_id': request.plan_line_ids[:1].id or False})
            vals.setdefault('delivery_method', self._delivery_for_source(
                request.plan_line_ids[:1], request))
        if vals.get('plan_line_id') and 'delivery_method' not in vals:
            vals['delivery_method'] = self._delivery_for_line(
                self.env['eds.annual.plan.line'].browse(vals['plan_line_id']))
        if vals.get('plan_line_id') and 'currency_id' not in vals:
            vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
        elif vals.get('delivery_method') and 'currency_id' not in vals:
            vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
        if {'plan_line_id', 'currency_id', 'delivery_method'} & vals.keys():
            for rec in self:
                validate_delivery_currency(self.env, vals.get('delivery_method', rec.delivery_method),
                                           vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    @api.constrains('source_type', 'plan_line_id', 'unscheduled_request_id',
                    'delivery_method', 'delivery_override', 'delivery_change_reason',
                    'internal_venue_id', 'bid_ids')
    def _check_approved_plan(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                if not rec.unscheduled_request_id or rec.unscheduled_request_id.state != 'approved':
                    raise ValidationError(_('Hotel sourcing requires an approved unscheduled request.'))
                if (rec.plan_line_id and
                        rec.plan_line_id.unscheduled_request_id != rec.unscheduled_request_id):
                    raise ValidationError(_('The addendum program must belong to the unscheduled request.'))
            elif (rec.unscheduled_request_id or not rec.plan_line_id or rec.plan_line_id.is_addendum
                  or rec.plan_line_id.plan_id.state not in ('published', 'amended')):
                raise ValidationError(_('Hotel sourcing requires an approved annual plan program.'))
            if rec.delivery_method != rec.planned_delivery_method and (
                    not rec.delivery_override or not (rec.delivery_change_reason or '').strip()):
                raise ValidationError(_(
                    'Enable Change Venue Arrangement and explain why the venue differs from the approved plan.'))
            if rec.internal_venue_id and rec.internal_venue_id.location_scope != 'local':
                raise ValidationError(_('Select a local bank internal training facility.'))
            expected_scope = 'international' if rec.delivery_method == 'international' else 'local'
            if rec.bid_ids.filtered(lambda bid: bid.venue_id.location_scope != expected_scope):
                raise ValidationError(_('Hotel bids must match the selected venue arrangement.'))
            for bid in rec.bid_ids:
                validate_delivery_currency(self.env, rec.delivery_method, bid.currency_id.id)

    def _award_source_domain(self):
        self.ensure_one()
        if self.source_type == 'unscheduled':
            return [('source_type', '=', 'unscheduled'),
                    ('unscheduled_request_id', '=', self.unscheduled_request_id.id)]
        if self.annual_plan_id and self.course_id:
            return [('source_type', '=', 'annual_plan'),
                    ('annual_plan_id', '=', self.annual_plan_id.id),
                    ('course_id', '=', self.course_id.id)]
        return [('source_type', '=', 'annual_plan'),
                ('plan_line_id', '=', self.plan_line_id.id)]

    @api.constrains('source_type', 'plan_line_id', 'unscheduled_request_id', 'state')
    def _check_unique_sourcing_source(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                source, table = rec.unscheduled_request_id, 'eds_unscheduled_request'
            else:
                source, table = rec.annual_plan_id, 'eds_annual_plan'
            if not source:
                continue  # The source validation reports the missing approved record.
            self.env.cr.execute('SELECT id FROM %s WHERE id = %%s FOR UPDATE' % table, [source.id])
            if self.sudo().search_count(rec._award_source_domain() + [('id', '!=', rec.id)]):
                raise ValidationError(_(
                    'This approved course or request already has hotel sourcing. '
                    'Add other hotel bids to the existing sourcing record.'))

    def _check_no_other_award(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                source, table = rec.unscheduled_request_id, 'eds_unscheduled_request'
            elif rec.annual_plan_id and rec.course_id:
                source, table = rec.annual_plan_id, 'eds_annual_plan'
            else:
                source, table = rec.plan_line_id, 'eds_annual_plan_line'
            self.env.cr.execute('SELECT id FROM %s WHERE id = %%s FOR UPDATE' % table, [source.id])
            if self.sudo().search_count(rec._award_source_domain() + [
                    ('state', '=', 'awarded'), ('id', '!=', rec.id)]):
                raise UserError(_(
                    'A hotel or venue is already awarded for this approved program or request.'))

    @api.constrains('state', 'source_type', 'plan_line_id', 'annual_plan_id',
                    'course_id', 'unscheduled_request_id')
    def _check_award_uniqueness(self):
        self.filtered(lambda rec: rec.state == 'awarded')._check_no_other_award()

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_hotel_award_plan_unique
                ON eds_hotel_selection (plan_line_id)
             WHERE state = 'awarded' AND source_type = 'annual_plan'
               AND plan_line_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_hotel_award_request_unique
                ON eds_hotel_selection (unscheduled_request_id)
             WHERE state = 'awarded' AND source_type = 'unscheduled'
               AND unscheduled_request_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_hotel_award_plan_course_unique
                ON eds_hotel_selection (annual_plan_id, course_id)
             WHERE state = 'awarded' AND source_type = 'annual_plan'
               AND annual_plan_id IS NOT NULL AND course_id IS NOT NULL
        """)

    @api.depends('bid_ids.status', 'bid_ids.venue_id', 'state', 'internal_venue_id')
    def _compute_awarded_venue_id(self):
        for rec in self:
            awarded = rec.bid_ids.filtered(lambda bid: bid.status == 'awarded')
            hotel_venues = awarded.mapped('venue_id')
            internal_v = rec.internal_venue_id if (rec.internal_venue_id and rec.state == 'awarded') else self.env['eds.venue']
            all_venues = hotel_venues | internal_v
            rec.awarded_venue_id = all_venues[:1] if all_venues else False

    @api.depends('bid_ids.status', 'bid_ids.venue_id', 'state', 'internal_venue_id')
    def _compute_awarded_venues(self):
        for rec in self:
            awarded = rec.bid_ids.filtered(lambda bid: bid.status == 'awarded')
            rec.awarded_bid_ids = awarded
            hotel_venues = awarded.mapped('venue_id')
            internal_v = rec.internal_venue_id if (rec.internal_venue_id and rec.state == 'awarded') else self.env['eds.venue']
            all_venues = hotel_venues | internal_v
            rec.awarded_venue_ids = all_venues
            rec.awarded_venue_count = len(all_venues)

    def action_start_evaluation(self):
        for rec in self:
            if rec.state != 'draft' or not rec.bid_ids:
                raise UserError(_('Add hotel bids to a draft selection before evaluation.'))
            expected_scope = 'international' if rec.delivery_method == 'international' else 'local'
            if rec.bid_ids.filtered(lambda bid: bid.venue_id.location_scope != expected_scope):
                raise UserError(_('Hotel bids must match the selected venue arrangement.'))
            rec.state = 'evaluation'

    def action_confirm_internal_venue(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft bank internal venue selections can be confirmed.'))
            if not rec.internal_venue_id:
                raise UserError(_('Choose a bank internal training facility first.'))
            rec._check_no_other_award()
            rec.state = 'awarded'
            rec._sync_awarded_hotel_to_sessions()

    def _sync_awarded_hotel_to_sessions(self):
        for rec in self:
            if not rec.awarded_venue_id:
                continue
            source_domain = ([('unscheduled_request_id', '=', rec.unscheduled_request_id.id)]
                             if rec.source_type == 'unscheduled' else
                             [('plan_line_id', '=', rec.plan_line_id.id), ('source_type', '=', 'annual_plan')])
            sessions = self.env['eds.session'].search(
                source_domain + [('status', 'not in', ('completed', 'cancelled'))])
            physical_sessions = sessions.filtered(lambda session: not session.is_virtual)
            virtual_sessions = sessions - physical_sessions
            for sess in physical_sessions:
                if not sess.venue_id or sess.venue_id not in rec.awarded_venue_ids:
                    sess.write({'venue_id': rec.awarded_venue_id.id, 'awarded_venue_id': rec.awarded_venue_id.id})
                else:
                    sess.write({'awarded_venue_id': sess.venue_id.id})
            virtual_sessions.write({'awarded_venue_id': rec.awarded_venue_id.id})


class EdsHotelBid(models.Model):
    _name = 'eds.hotel.bid'
    _description = 'Hotel / Venue Bid'
    _order = 'total_score desc, id desc'

    selection_id = fields.Many2one('eds.hotel.selection', required=True, ondelete='cascade', index=True)
    venue_scope = fields.Selection(
        [('local', 'Local'), ('international', 'International')],
        compute='_compute_venue_scope', string='Venue Location')
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', required=True,
                               domain="[('active', '=', True)]")
    currency_id = fields.Many2one('res.currency', string='Bid Currency', required=True,
                                  default=lambda self: currency_for_delivery(self.env, 'internal'))
    price_quoted = fields.Monetary(currency_field='currency_id', string='Quoted Price', required=True)
    technical_score = fields.Float(string='Facility / Service Score (0–10)')
    financial_score = fields.Float(string='Price Score (0–10)', compute='_compute_scores', store=True)
    total_score = fields.Float(string='Weighted Total /100', compute='_compute_scores', store=True)
    status = fields.Selection([
        ('pending', 'Pending'), ('rejected', 'Rejected'), ('awarded', 'Awarded'),
    ], default='pending', required=True)
    award_attachment = fields.Binary(string='Award Letter', attachment=True)
    award_filename = fields.Char()
    contract_attachment = fields.Binary(string='Hotel Contract', attachment=True)
    contract_filename = fields.Char()
    notes = fields.Text()

    @api.depends('selection_id.delivery_method')
    @api.depends_context('default_venue_scope')
    def _compute_venue_scope(self):
        for bid in self:
            method = bid.selection_id.delivery_method
            bid.venue_scope = (
                'international' if method == 'international' else 'local'
            ) if method else self.env.context.get('default_venue_scope', 'local')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('selection_id') and not vals.get('currency_id'):
                vals['currency_id'] = self.env['eds.hotel.selection'].browse(
                    vals['selection_id']).currency_id.id
            if vals.get('selection_id') and vals.get('currency_id'):
                selection = self.env['eds.hotel.selection'].browse(vals['selection_id'])
                validate_delivery_currency(self.env, selection.delivery_method, vals['currency_id'])
        return super().create(vals_list)

    def write(self, vals):
        if {'selection_id', 'currency_id'} & vals.keys():
            for rec in self:
                selection = (self.env['eds.hotel.selection'].browse(vals['selection_id'])
                             if vals.get('selection_id') else rec.selection_id)
                validate_delivery_currency(self.env, selection.delivery_method,
                                           vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    @api.onchange('selection_id')
    def _onchange_selection_currency(self):
        if self.selection_id:
            self.currency_id = self.selection_id.currency_id

    def _price_in_selection_currency(self):
        self.ensure_one()
        if not self.price_quoted:
            return 0.0
        if self.currency_id == self.selection_id.currency_id:
            return self.price_quoted
        return self.currency_id._convert(
            self.price_quoted, self.selection_id.currency_id,
            self.env.company, fields.Date.context_today(self))

    @api.depends('technical_score', 'price_quoted', 'currency_id', 'selection_id.currency_id',
                 'selection_id.bid_ids.price_quoted', 'selection_id.bid_ids.currency_id')
    def _compute_scores(self):
        for rec in self:
            prices = [bid._price_in_selection_currency()
                      for bid in rec.selection_id.bid_ids if bid.price_quoted > 0]
            own_price = rec._price_in_selection_currency()
            rec.financial_score = round(min(prices) / own_price * 10, 2) if prices and own_price > 0 else 0.0
            rec.total_score = round(rec.technical_score * 6 + rec.financial_score * 4, 2)

    @api.constrains('selection_id', 'venue_id', 'price_quoted', 'technical_score')
    def _check_bid(self):
        for rec in self:
            if rec.price_quoted < 0 or rec.technical_score < 0 or rec.technical_score > 10:
                raise ValidationError(_('Hotel price must be non-negative and facility score must be between 0 and 10.'))
            if rec.selection_id.delivery_method == 'international' and rec.venue_id.location_scope != 'international':
                raise ValidationError(_('International programs require an international hotel or venue.'))
            if rec.selection_id.delivery_method != 'international' and rec.venue_id.location_scope != 'local':
                raise ValidationError(_('Local programs require a local hotel or venue.'))
            if self.search_count([
                    ('selection_id', '=', rec.selection_id.id),
                    ('venue_id', '=', rec.venue_id.id), ('id', '!=', rec.id)]):
                raise ValidationError(_('This hotel already has a bid in the selection.'))

    def init(self):
        # Drop legacy single-award constraint so multiple hotels can be awarded
        self.env.cr.execute("""
            DROP INDEX IF EXISTS eds_hotel_bid_award_unique
        """)

    def action_award(self):
        for rec in self:
            if rec.selection_id.state not in ('evaluation', 'awarded'):
                raise UserError(_('Start hotel evaluation before awarding.'))
            rec.selection_id._check_no_other_award()
            if rec.technical_score < 6 or rec.price_quoted <= 0:
                raise UserError(_('The winning hotel needs a facility score of at least 6/10 and a positive quote.'))
            rec.status = 'awarded'
            rec.selection_id.state = 'awarded'
            rec.selection_id._sync_awarded_hotel_to_sessions()
            selection = rec.selection_id
            recipients = role_users(selection, 'group_eds_officer') | selection.annual_plan_id.creator_id
            if selection.unscheduled_request_id:
                recipients |= selection.unscheduled_request_id.create_uid
            notify_action(selection, recipients, _('Training venue selected'),
                          _('%s was awarded for %s. Sessions can now use this venue.')
                          % (rec.venue_id.name, selection.program_name),
                          action_required=False)

    def action_reject(self):
        for rec in self:
            if rec.status == 'awarded':
                raise UserError(_('An awarded hotel cannot be rejected.'))
            rec.status = 'rejected'
