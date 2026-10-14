# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsHotelSelection(models.Model):
    """Compare hotel bids for one approved plan program and pass the winner to sessions."""

    _name = 'eds.hotel.selection'
    _description = 'Hotel / Venue Selection'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, default=lambda self: _('New'), readonly=True, copy=False)
    plan_line_id = fields.Many2one(
        'eds.annual.plan.line', string='Approved Plan Program', required=True,
        domain="[('plan_id.state', 'in', ('published', 'amended'))]", tracking=True)
    annual_plan_id = fields.Many2one(related='plan_line_id.plan_id', string='Annual Plan', store=True)
    program_name = fields.Char(related='plan_line_id.program_name', string='Program', store=True)
    delivery_method = fields.Selection(related='plan_line_id.delivery_method', store=True)
    currency_id = fields.Many2one('res.currency', string='Bid Currency', required=True,
                                  default=lambda self: self.env.company.currency_id)
    bid_ids = fields.One2many('eds.hotel.bid', 'selection_id', string='Hotel Bids')
    awarded_venue_id = fields.Many2one('eds.venue', compute='_compute_awarded_venue', store=True)
    state = fields.Selection([
        ('draft', 'Draft'), ('evaluation', 'Evaluation'), ('awarded', 'Awarded'),
    ], default='draft', required=True, tracking=True)
    notes = fields.Text()

    @api.model
    def _currency_for_line(self, line):
        if line and line.delivery_method == 'international':
            return self.env['res.currency'].search([('name', '=', 'USD')], limit=1) or self.env.company.currency_id
        return self.env.company.currency_id

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        self.currency_id = self._currency_for_line(self.plan_line_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.hotel.selection') or _('New')
            if vals.get('plan_line_id') and not vals.get('currency_id'):
                vals['currency_id'] = self._currency_for_line(
                    self.env['eds.annual.plan.line'].browse(vals['plan_line_id'])).id
        return super().create(vals_list)

    @api.constrains('plan_line_id')
    def _check_approved_plan(self):
        for rec in self:
            if rec.plan_line_id.plan_id.state not in ('published', 'amended'):
                raise ValidationError(_('Hotel sourcing requires an approved annual plan program.'))

    @api.depends('bid_ids.status', 'bid_ids.venue_id')
    def _compute_awarded_venue(self):
        for rec in self:
            winner = rec.bid_ids.filtered(lambda bid: bid.status == 'awarded')[:1]
            rec.awarded_venue_id = winner.venue_id if winner else False

    def action_start_evaluation(self):
        for rec in self:
            if rec.state != 'draft' or not rec.bid_ids:
                raise UserError(_('Add hotel bids to a draft selection before evaluation.'))
            rec.state = 'evaluation'

    def _sync_awarded_hotel_to_sessions(self):
        for rec in self:
            if not rec.awarded_venue_id:
                continue
            sessions = self.env['eds.session'].search([
                ('plan_line_id', '=', rec.plan_line_id.id),
                ('status', 'not in', ('completed', 'cancelled')),
            ])
            sessions.write({'awarded_venue_id': rec.awarded_venue_id.id})


class EdsHotelBid(models.Model):
    _name = 'eds.hotel.bid'
    _description = 'Hotel / Venue Bid'
    _order = 'total_score desc, id'

    selection_id = fields.Many2one('eds.hotel.selection', required=True, ondelete='cascade', index=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', required=True,
                               domain="[('active', '=', True)]")
    currency_id = fields.Many2one('res.currency', string='Bid Currency', required=True,
                                  default=lambda self: self.env.company.currency_id)
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('selection_id') and not vals.get('currency_id'):
                vals['currency_id'] = self.env['eds.hotel.selection'].browse(
                    vals['selection_id']).currency_id.id
        return super().create(vals_list)

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

    def action_award(self):
        for rec in self:
            if rec.selection_id.state != 'evaluation':
                raise UserError(_('Start hotel evaluation before awarding.'))
            if rec.technical_score < 6 or rec.price_quoted <= 0:
                raise UserError(_('The winning hotel needs a facility score of at least 6/10 and a positive quote.'))
            if rec.selection_id.bid_ids.filtered(lambda bid: bid.id != rec.id and bid.status == 'awarded'):
                raise UserError(_('Another hotel has already been awarded for this program.'))
            if not rec.award_attachment:
                raise UserError(_('Attach the award letter before awarding the hotel.'))
            rec.status = 'awarded'
            rec.selection_id.state = 'awarded'
            rec.selection_id._sync_awarded_hotel_to_sessions()

    def action_reject(self):
        for rec in self:
            if rec.status == 'awarded':
                raise UserError(_('An awarded hotel cannot be rejected.'))
            rec.status = 'rejected'
