# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import clear_action_activities, notify_action, notify_role_action


class EdsVenueRequirement(models.Model):
    """Standardized Venue Requirement Specification (VRS).

    Prepared by the L&D officer, approved by the Director - PPDD, and only then may
    an RFP for venue procurement be initiated.
    """
    _name = 'eds.venue.requirement'
    _description = 'Venue Requirement Specification (VRS)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program', required=True,
                                tracking=True)
    session_id = fields.Many2one('eds.session', string='Training Session', tracking=True)
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    facilitator_count = fields.Integer(string='No. of Facilitators', default=1)
    participant_count = fields.Integer(string='Expected Participants', default=30)
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration_days', store=True, readonly=False)
    target_audience = fields.Char(string='Target Audience')
    preferred_location = fields.Char(string='Preferred Location / City', related='location_preference', readonly=False)
    estimated_budget = fields.Monetary(string='Estimated Budget', currency_field='currency_id')
    delivery_method = fields.Selection(related='session_id.delivery_method', readonly=True)

    @api.depends('date_start', 'date_end')
    def _compute_duration_days(self):
        for rec in self:
            if rec.date_start and rec.date_end:
                rec.duration_days = max(1, (rec.date_end - rec.date_start).days + 1)
            else:
                rec.duration_days = 1
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: currency_for_delivery(self.env, 'local'))

    # 2. Room & Seating
    seating_layout = fields.Selection([
        ('ushape', 'U-Shape'),
        ('theater', 'Theater'),
        ('classroom', 'Classroom'),
        ('cluster', 'Cluster / Round Tables'),
        ('boardroom', 'Boardroom'),
    ], string='Seating Layout', default='classroom', tracking=True)
    breakout_rooms = fields.Integer(string='Breakout Rooms Required', default=0)

    # 3. Equipment & Facilities Checkboxes
    has_projector = fields.Boolean(string='Projector / Screen', default=True)
    has_sound_system = fields.Boolean(string='Sound System & Microphones', default=True)
    has_flipcharts = fields.Boolean(string='Flip Charts & Markers', default=True)
    has_wifi = fields.Boolean(string='Wi-Fi / Internet', default=True)
    has_videoconference = fields.Boolean(string='Video-Conferencing Set-up')
    has_power_backup = fields.Boolean(string='Power Backup / Generator', default=True)
    has_air_conditioning = fields.Boolean(string='Air Conditioning', default=True)
    has_parking = fields.Boolean(string='Parking Space Available')
    has_accessibility = fields.Boolean(string='Accessibility (Ramp / Lift)')
    has_reg_desk = fields.Boolean(string='Registration Desk Available', default=True)
    other_tech_requirements = fields.Text(string='Other Technical Requirements')

    # 4. Catering & Lunch Specifications
    catering_morning_tea = fields.Boolean(string='Morning Tea/Coffee', default=True)
    catering_lunch = fields.Boolean(string='Lunch Buffet', default=True)
    catering_afternoon_tea = fields.Boolean(string='Afternoon Tea/Coffee', default=True)
    catering_water = fields.Boolean(string='Bottled Water', default=True)
    menu_type = fields.Selection([
        ('fasting', 'Fasting Only'),
        ('non_fasting', 'Non-Fasting Only'),
        ('mixed', 'Mixed / Standard Buffet'),
    ], string='Menu Type', default='mixed')
    special_dietary_needs = fields.Char(string='Special Dietary Needs')
    catering_count = fields.Integer(string='Catering Heads / Pax', default=30)

    # 5. Accommodation Details
    rooms_required = fields.Integer(string='Rooms Required', default=0)
    room_nights = fields.Integer(string='Nights', default=0)
    accommodation_notes = fields.Text(string='Accommodation Details')

    # Signatories
    prepared_by = fields.Char(string='Prepared by (L&D Officer)')
    reviewed_by = fields.Char(string='Reviewed by (Team Leader, L&D)')
    director_sign = fields.Char(string='Approved by (Director, PPDD)')

    vrs_document = fields.Binary(string='VRS Document', attachment=True)
    vrs_document_name = fields.Char(string='VRS Document Filename')
    capacity_required = fields.Integer(string='Required Capacity', default=30)
    location_preference = fields.Char(string='Location Preference')
    facilities_required = fields.Text(string='Facilities Required')
    accommodation_required = fields.Boolean(string='Accommodation Required')
    catering_required = fields.Boolean(string='Catering Required')
    special_requirements = fields.Text(string='Special Requirements')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('director_approved', 'Director PPDD Approved'),
        ('rfp_initiated', 'RFP Initiated'),
    ], string='Status', default='draft', required=True, tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    rfp_ids = fields.One2many('eds.rfp', 'venue_requirement_id', string='RFPs')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.onchange('session_id')
    def _onchange_session_currency(self):
        method = self.session_id.delivery_method if self.session_id else 'local'
        if method != 'international' or not self.currency_id or self.currency_id.name == 'ETB':
            self.currency_id = currency_for_delivery(self.env, method)

    def write(self, vals):
        vals = dict(vals)
        if 'session_id' in vals and 'currency_id' not in vals:
            method = (self.env['eds.session'].browse(vals['session_id']).delivery_method
                      if vals['session_id'] else 'local')
            vals['currency_id'] = currency_for_delivery(self.env, method).id
        if {'session_id', 'currency_id'} & vals.keys():
            for requirement in self:
                method = ((self.env['eds.session'].browse(vals['session_id']).delivery_method
                           if vals['session_id'] else 'local')
                          if 'session_id' in vals else requirement.delivery_method or 'local')
                validate_delivery_currency(self.env, method,
                                           vals.get('currency_id', requirement.currency_id.id))
        return super().write(vals)

    def action_print_vrs(self):
        """Prints official Form Venue Requirement Specification PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_vrs').report_action(self)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            method = (self.env['eds.session'].browse(vals['session_id']).delivery_method
                      if vals.get('session_id') else 'local')
            if vals.get('currency_id'):
                validate_delivery_currency(self.env, method, vals['currency_id'])
            else:
                vals['currency_id'] = currency_for_delivery(self.env, method).id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.venue.requirement') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft VRS documents can be submitted.'))
            if not rec.vrs_document and not rec.facilities_required:
                raise UserError(_('Attach the VRS document or specify the required facilities '
                                  'before submitting.'))
            rec.state = 'submitted'
            rec.message_post(body=_('VRS %s submitted for Director PPDD approval.')
                             % rec.name)
            notify_role_action(
                rec, 'group_eds_director', None,
                _('Approve venue requirements'),
                _('Venue requirements %s need Director approval.') % rec.name)

    def action_director_approve(self):
        for rec in self:
            rec._require_director_authority()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted VRS documents can be approved.'))
            rec.write({'state': 'director_approved',
                       'approved_by_id': self.env.user.id,
                       'approval_date': fields.Datetime.now()})
            rec.message_post(body=_('VRS %s approved by Director PPDD - RFP may now be initiated '
                                    '().') % rec.name)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Venue requirements approved'),
                _('Venue requirements %s are approved. You may initiate the RFP.') % rec.name)

    def action_return_draft(self):
        for rec in self:
            rec._require_director_authority()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted VRS documents can be returned.'))
            rec.state = 'draft'
            rec.message_post(body=_('VRS %s returned to the officer for amendment.') % rec.name)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Venue requirements returned'),
                _('Venue requirements %s were returned for amendment.') % rec.name)

    def _require_director_authority(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_director')):
            raise UserError(_('The Director PPDD approval step requires the EDS Director role.'))


class EdsRfp(models.Model):
    """Structured Request for Proposal for training vendors and venues.

    Lightweight state machine (draft -> issued -> receiving -> evaluation -> awarded)
    with two-envelope proposal registration, configurable minimum number of qualified
    providers (default >= 3) and evaluation criteria.
    """
    _name = 'eds.rfp'
    _description = 'Request for Proposal (RFP)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program', required=True,
                                tracking=True)
    venue_requirement_id = fields.Many2one(
        'eds.venue.requirement', string='Venue Requirement',
        domain=[('state', '=', 'director_approved')],
        help='For venue procurement: the approved VRS.')
    objectives = fields.Text(string='Training Objectives')
    scope_of_work = fields.Text(string='Scope of Work', required=True)
    technical_specifications = fields.Text(string='Technical Specifications')
    venue_accommodation_requirements = fields.Text(string='Venue & Accommodation Requirements')
    evaluation_criteria_ids = fields.One2many(
        'eds.rfp.criteria.line', 'rfp_id', string='Evaluation Criteria',
        help='Criteria published in the RFP.')
    submission_deadline = fields.Date(string='Submission Deadline', required=True, tracking=True)
    min_providers = fields.Integer(
        string='Minimum Providers', compute='_compute_min_providers', store=True,
        help='Configurable minimum number of qualified providers to issue to (default >= 3).')
    min_providers_met = fields.Boolean(string='Minimum Providers Met', compute='_compute_min_providers', store=True)
    provider_ids = fields.Many2many(
        'eds.external.provider', 'eds_rfp_provider_rel', 'rfp_id', 'provider_id',
        string='Qualified Providers',
        domain="[('pre_qualified', '=', True)]",
        help='Pre-qualified providers the RFP is issued to.')
    proposal_ids = fields.One2many('eds.vendor.proposal', 'rfp_id', string='Proposals')
    proposal_count = fields.Integer(string='Proposal Count', compute='_compute_proposal_count')
    issuance_date = fields.Date(string='Issuance Date', readonly=True)
    receipt_opened_date = fields.Datetime(string='Receipts Opened At', readonly=True)
    awarded_proposal_id = fields.Many2one('eds.vendor.proposal', string='Awarded Proposal',
                                          readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('receiving', 'Receiving Proposals'),
        ('evaluation', 'Under Evaluation'),
        ('awarded', 'Awarded'),
    ], string='Status', default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('state')
    def _compute_min_providers(self):
        for rec in self:
            rec.min_providers = rec._get_int_param('eds.rfp_min_providers', 3)
            rec.min_providers_met = len(rec.provider_ids) >= rec.min_providers

    @api.depends('proposal_ids')
    def _compute_proposal_count(self):
        for rec in self:
            rec.proposal_count = len(rec.proposal_ids)

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.rfp') or _('New')
        return super().create(vals_list)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_issue(self):
        """Draft -> Issued: validate venue approval and minimum provider count."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'draft':
                raise UserError(_('Only draft RFPs can be issued.'))
            if rec.venue_requirement_id and rec.venue_requirement_id.state != 'director_approved':
                raise UserError(_('The venue requirement must be approved by the Director PPDD '
                                  'before the RFP is issued.'))
            if not rec.provider_ids:
                raise UserError(_('Select at least one qualified provider to issue the RFP to.'))
            if len(rec.provider_ids) < rec.min_providers:
                raise UserError(_('The RFP must be issued to at least %s qualified providers '
                                  '().') % rec.min_providers)
            rec.write({'state': 'issued', 'issuance_date': date.today()})
            rec.message_post(body=_('RFP %s issued to %s qualified providers.')
                             % (rec.name, len(rec.provider_ids)))

    def action_receive_proposals(self):
        """Issued -> Receiving: open the submission window."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'issued':
                raise UserError(_('Only issued RFPs can start receiving proposals.'))
            rec.state = 'receiving'
            rec.message_post(body=_('RFP %s opened for proposal submission (two-envelope).')
                             % rec.name)

    def action_close_receiving(self):
        """Receiving -> Evaluation: receipts closed and envelopes are opened by the committee."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'receiving':
                raise UserError(_('Only RFPs in the receiving stage can move to evaluation.'))
            if not rec.proposal_ids:
                raise UserError(_('At least one proposal must be registered before evaluation.'))
            rec.write({'state': 'evaluation', 'receipt_opened_date': datetime.now()})
            rec.message_post(body=_('RFP %s moved to evaluation - envelopes opened and logged '
                                    '().') % rec.name)

    def action_award(self):
        """Evaluation -> Awarded: pick the winning proposal and auto-generate the contract."""
        last_contract = False
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'evaluation':
                raise UserError(_('Only RFPs under evaluation can be awarded.'))
            if not rec.awarded_proposal_id:
                raise UserError(_('Select the awarded proposal first.'))
            rec.state = 'awarded'
            rec.message_post(body=_('RFP %s awarded to %s.')
                             % (rec.name, rec.awarded_proposal_id.provider_id.name))
            last_contract = self.env['eds.training.contract'].create({
                'rfp_id': rec.id,
                'course_id': rec.course_id.id,
                'provider_id': rec.awarded_proposal_id.provider_id.id,
                'proposal_id': rec.awarded_proposal_id.id,
                'combined_score': rec.awarded_proposal_id.combined_score,
            })
            notify_role_action(
                last_contract, 'group_eds_officer', 'group_eds_admin',
                _('Route awarded contract to Legal'),
                _('RFP %s was awarded to %s. Review contract %s and send it for Legal review.')
                % (rec.name, rec.awarded_proposal_id.provider_id.name,
                   last_contract.name))
        if last_contract:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.training.contract',
                'res_id': last_contract.id,
                'view_mode': 'form',
            }

    def action_back_to_receiving(self):
        for rec in self:
            if rec.state != 'evaluation':
                raise UserError(_('Only RFPs under evaluation can return to receiving.'))
            rec.state = 'receiving'
            rec.message_post(body=_('RFP %s returned to receiving.') % rec.name)


class EdsRfpCriteriaLine(models.Model):
    """Published evaluation criteria line on an RFP."""
    _name = 'eds.rfp.criteria.line'
    _description = 'RFP Evaluation Criteria Line'
    _order = 'sequence, create_date desc, id desc'

    rfp_id = fields.Many2one('eds.rfp', string='RFP', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Order', default=10)
    name = fields.Char(string='Criterion', required=True)
    weight = fields.Float(string='Weight (%)', default=10.0, required=True)


class EdsVendorProposal(models.Model):
    """Two-envelope proposal registration.

    Technical and financial envelopes are registered separately; the financial
    envelope is only opened after the technical evaluation passes the configured
    minimum threshold.
    """
    _name = 'eds.vendor.proposal'
    _description = 'Vendor Proposal (Two-Envelope)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    rfp_id = fields.Many2one('eds.rfp', string='RFP', required=True, ondelete='cascade')
    provider_id = fields.Many2one('eds.external.provider', string='Provider', required=True)
    registration_date = fields.Datetime(string='Registration Date', default=fields.Datetime.now,
                                        readonly=True)
    technical_envelope = fields.Binary(string='Technical Envelope', attachment=True)
    technical_envelope_name = fields.Char(string='Technical Envelope Filename')
    financial_envelope = fields.Binary(string='Financial Envelope', attachment=True)
    financial_envelope_name = fields.Char(string='Financial Envelope Filename')
    technical_received_date = fields.Datetime(string='Technical Receipt Date', readonly=True)
    financial_received_date = fields.Datetime(string='Financial Receipt Date', readonly=True)
    technical_opened_date = fields.Datetime(string='Technical Opened At', readonly=True)
    financial_opened_date = fields.Datetime(string='Financial Opened At', readonly=True)
    technical_score_id = fields.Many2one(
        'eds.vendor.evaluation', string='Technical Evaluation', ondelete='set null')
    financial_score_id = fields.Many2one(
        'eds.vendor.evaluation', string='Financial Evaluation', ondelete='set null')
    technical_score = fields.Float(string='Technical Score', related='technical_score_id.total_score')
    financial_score = fields.Float(string='Financial Score', related='financial_score_id.total_score')
    technical_threshold_met = fields.Boolean(
        string='Technical Threshold Met', related='technical_score_id.threshold_met')
    combined_score = fields.Float(
        string='Combined Score', compute='_compute_combined_score', store=True,
        help='Weighted blend of technical and financial scores.')
    state = fields.Selection([
        ('registered', 'Registered'),
        ('technical_opened', 'Technical Opened'),
        ('financial_opened', 'Financial Opened'),
        ('evaluated', 'Evaluated'),
    ], string='Status', default='registered', required=True, tracking=True)

    @api.depends('technical_score', 'financial_score', 'technical_threshold_met')
    def _compute_combined_score(self):
        for rec in self:
            blend = rec._get_int_param('eds.technical_financial_blend', 70)
            if rec.technical_score and rec.financial_score and rec.technical_threshold_met:
                rec.combined_score = round(
                    (rec.technical_score * blend + rec.financial_score * (100 - blend)) / 100.0, 2)
            else:
                rec.combined_score = 0.0

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.vendor.proposal') or _('New')
            if not vals.get('technical_received_date'):
                vals['technical_received_date'] = fields.Datetime.now()
        return super().create(vals_list)

    def action_open_technical(self):
        """Open the technical envelope and log the event."""
        for rec in self:
            if rec.state != 'registered':
                raise UserError(_('Only registered proposals can have their technical envelope opened.'))
            rec.write({'state': 'technical_opened', 'technical_opened_date': datetime.now()})
            rec.message_post(body=_('Technical envelope of %s opened and registered.')
                             % rec.name)

    def action_open_financial(self):
        """Open the financial envelope - gated on the technical threshold."""
        for rec in self:
            if rec.state != 'technical_opened':
                raise UserError(_('Open the technical envelope before the financial envelope.'))
            if not rec.technical_score_id or rec.technical_score_id.state != 'approved':
                raise UserError(_('Complete and approve the technical evaluation first.'))
            if not rec.technical_score_id.threshold_met:
                raise UserError(_('The technical score of %s is below the minimum qualification '
                                  'threshold - the financial envelope must not be opened.')
                                % rec.technical_score)
            rec.write({'state': 'financial_opened', 'financial_opened_date': datetime.now()})
            rec.message_post(body=_('Financial envelope of %s opened - technical threshold met '
                                    '().') % rec.name)

    def action_mark_evaluated(self):
        for rec in self:
            if rec.state != 'financial_opened':
                raise UserError(_('Only proposals with both envelopes opened can be marked evaluated.'))
            rec.state = 'evaluated'
            rec.message_post(body=_('Proposal %s fully evaluated.') % rec.name)


class EdsEvaluationCriteria(models.Model):
    """Configurable weighted evaluation criteria templates."""
    _name = 'eds.evaluation.criteria'
    _description = 'Evaluation Criteria Template'
    _order = 'evaluation_type, sequence, create_date desc, id desc'

    name = fields.Char(string='Criterion', required=True)
    evaluation_type = fields.Selection([
        ('technical', 'Technical'),
        ('financial', 'Financial'),
        ('international', 'International / Host-Country'),
    ], string='Evaluation Type', required=True, default='technical')
    sequence = fields.Integer(string='Order', default=10)
    weight = fields.Float(string='Default Weight (%)', default=10.0)
    description = fields.Text(string='Description')


class EdsVendorEvaluation(models.Model):
    """Weighted evaluation of a vendor proposal.

    Technical and financial evaluations are separate records; a technical evaluation
    below the configured minimum threshold blocks financial evaluation.
    International provider + host-country evaluations use their own criteria set
    and generate ranked recommendations for Director PPDD / CPCO review.
    """
    _name = 'eds.vendor.evaluation'
    _description = 'Vendor Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    rfp_id = fields.Many2one('eds.rfp', string='RFP')
    proposal_id = fields.Many2one('eds.vendor.proposal', string='Proposal')
    provider_id = fields.Many2one('eds.external.provider', string='Provider')
    evaluation_type = fields.Selection([
        ('technical', 'Technical'),
        ('financial', 'Financial'),
        ('international', 'International / Host-Country'),
    ], string='Evaluation Type', default='technical', required=True)
    line_ids = fields.One2many('eds.vendor.evaluation.line', 'evaluation_id',
                               string='Criteria Scores')
    total_score = fields.Float(
        string='Total Score (%)', compute='_compute_total_score', store=True,
        help='Weighted score across the criteria lines.')
    threshold_met = fields.Boolean(
        string='Minimum Threshold Met', compute='_compute_threshold_met', store=True,
        help='Technical evaluations must meet the configurable minimum threshold '
             'before the financial evaluation is permitted.')
    evaluator_id = fields.Many2one('res.users', string='Evaluator',
                                   default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.depends('line_ids', 'line_ids.contribution')
    def _compute_total_score(self):
        for rec in self:
            rec.total_score = round(sum(rec.line_ids.mapped('contribution')), 2)

    @api.depends('total_score', 'evaluation_type')
    def _compute_threshold_met(self):
        for rec in self:
            if rec.evaluation_type != 'technical':
                rec.threshold_met = True
                continue
            threshold = rec._get_int_param('eds.technical_min_threshold', 40)
            rec.threshold_met = bool(rec.total_score and rec.total_score >= threshold)

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.vendor.evaluation') or _('New')
        return super().create(vals_list)

    def _default_criteria(self):
        """Seed default criteria lines from the configurable template."""
        self.ensure_one()
        criteria = self.env['eds.evaluation.criteria'].search(
            [('evaluation_type', '=', self.evaluation_type)])
        if criteria:
            self.line_ids = [(0, 0, {
                'criterion_id': c.id,
                'name': c.name,
                'weight': c.weight,
            }) for c in criteria]

    def action_apply_template(self):
        self._default_criteria()
        return True

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft evaluations can be submitted.'))
            if not rec.line_ids:
                raise UserError(_('Add criteria scores before submitting the evaluation.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Evaluation %s submitted for approval.') % rec.name)
            notify_role_action(
                rec, 'group_eds_manager', 'group_eds_admin',
                _('Approve provider evaluation'),
                _('Provider evaluation %s needs approval.') % rec.name)

    def action_approve(self):
        for rec in self:
            rec._require_evaluation_approver()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted evaluations can be approved.'))
            rec.state = 'approved'
            rec.message_post(body=_('Evaluation %s approved - total score %s%%.')
                             % (rec.name, rec.total_score))
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Provider evaluation approved'),
                _('Provider evaluation %s is approved.') % rec.name,
                action_required=False)

    def _require_evaluation_approver(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Evaluation approval requires L&D Manager authority.'))


class EdsVendorEvaluationLine(models.Model):
    """One scored criterion inside a vendor evaluation."""
    _name = 'eds.vendor.evaluation.line'
    _description = 'Vendor Evaluation Line'
    _order = 'evaluation_id, sequence, create_date desc, id desc'

    evaluation_id = fields.Many2one('eds.vendor.evaluation', string='Evaluation',
                                    required=True, ondelete='cascade')
    sequence = fields.Integer(string='Order', default=10)
    criterion_id = fields.Many2one('eds.evaluation.criteria', string='Criterion Template')
    name = fields.Char(string='Criterion', required=True)
    weight = fields.Float(string='Weight (%)', default=10.0, required=True)
    score = fields.Float(string='Score (0-100)', default=0.0, required=True)
    contribution = fields.Float(
        string='Contribution', compute='_compute_contribution', store=True)

    @api.depends('weight', 'score')
    def _compute_contribution(self):
        for rec in self:
            rec.contribution = round(rec.weight * rec.score / 100.0, 2)


class EdsTrainingContract(models.Model):
    """Training contract / service agreement.

    Auto-generated from the awarded RFP and evaluation data, routed to the Legal
    Directorate for review, with legal comments/amendments, version history and
    recorded signatures.
    """
    _name = 'eds.training.contract'
    _description = 'Training Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    rfp_id = fields.Many2one('eds.rfp', string='RFP', readonly=True)
    proposal_id = fields.Many2one('eds.vendor.proposal', string='Awarded Proposal', readonly=True)
    provider_id = fields.Many2one('eds.external.provider', string='Provider', required=True,
                                  tracking=True)
    provider_category = fields.Selection(related='provider_id.category', readonly=True)
    course_id = fields.Many2one('eds.course', string='Training Program', tracking=True)
    combined_score = fields.Float(string='Combined Score (%)', readonly=True,
                                  help='Snapshot of the winning proposal score.')
    contract_amount = fields.Monetary(string='Contract Amount', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: currency_for_delivery(self.env, 'local'))
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    version = fields.Char(string='Version', default='v1.0', readonly=True)
    version_ids = fields.One2many('eds.training.contract.version', 'contract_id',
                                  string='Version History', copy=True)
    legal_comments = fields.Text(string='Legal Comments / Amendments')
    legal_reviewer_id = fields.Many2one('res.users', string='Legal Reviewer')
    signature = fields.Binary(string='Authorized Signature', attachment=True)
    signature_name = fields.Char(string='Signature Filename')
    signed_by = fields.Char(string='Signed By')
    signature_date = fields.Date(string='Signature Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('legal_review', 'Legal Review'),
        ('revision', 'Revision'),
        ('approved', 'Approved'),
        ('signed', 'Signed'),
        ('active', 'Active'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            provider = self.env['eds.external.provider'].browse(vals.get('provider_id'))
            method = provider.category or 'local'
            if vals.get('currency_id'):
                validate_delivery_currency(self.env, method, vals['currency_id'])
            else:
                vals['currency_id'] = currency_for_delivery(self.env, method).id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.training.contract') or _('New')
        return super().create(vals_list)

    @api.onchange('provider_id')
    def _onchange_provider_currency(self):
        method = self.provider_id.category or 'local'
        if method != 'international' or not self.currency_id or self.currency_id.name == 'ETB':
            self.currency_id = currency_for_delivery(self.env, method)

    def write(self, vals):
        vals = dict(vals)
        if 'provider_id' in vals and 'currency_id' not in vals:
            provider = self.env['eds.external.provider'].browse(vals['provider_id'])
            vals['currency_id'] = currency_for_delivery(self.env, provider.category or 'local').id
        if {'provider_id', 'currency_id'} & vals.keys():
            for contract in self:
                provider = (self.env['eds.external.provider'].browse(vals['provider_id'])
                            if vals.get('provider_id') else contract.provider_id)
                validate_delivery_currency(
                    self.env, provider.category or 'local',
                    vals.get('currency_id', contract.currency_id.id))
        return super().write(vals)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    # ── Workflow ──────────────────────────────────────────────────
    def action_send_legal(self):
        """Draft -> Legal Review: route the draft agreement to the Legal Directorate."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'draft':
                raise UserError(_('Only draft contracts can be routed to Legal.'))
            rec.state = 'legal_review'
            rec.message_post(body=_('Contract %s routed to the Legal Directorate for review '
                                    '().') % rec.name)
            notify_role_action(
                rec, 'group_eds_manager', 'group_eds_admin',
                _('Review training contract'),
                _('Training contract %s needs legal review.') % rec.name)

    def action_legal_approve(self):
        """Legal Review -> Approved (or Revision with a new version)."""
        for rec in self:
            rec._require_legal_authority()
            if rec.state != 'legal_review':
                raise UserError(_('Only contracts under legal review can be approved.'))
            if rec.legal_comments and not rec.version_ids:
                raise UserError(_('Record the amended contract version before approving '
                                  '().'))
            rec.write({'state': 'approved', 'legal_reviewer_id': self.env.user.id})
            rec.message_post(body=_('Contract %s approved by Legal.') % rec.name)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Training contract approved'),
                _('Training contract %s is approved and ready for signature.') % rec.name)

    def action_request_revision(self):
        """Legal Review -> Revision: capture legal comments and bump the version."""
        for rec in self:
            rec._require_legal_authority()
            if rec.state != 'legal_review':
                raise UserError(_('Only contracts under legal review can be returned for revision.'))
            if not rec.legal_comments:
                raise UserError(_('Enter the legal comments before returning the contract.'))
            new_version = rec._bump_version(rec.version)
            self.env['eds.training.contract.version'].create({
                'contract_id': rec.id,
                'version': new_version,
                'comment': rec.legal_comments,
            })
            rec.write({'state': 'revision', 'version': new_version})
            rec.message_post(body=_('Contract %s returned with legal comments - version %s '
                                    '().') % (rec.name, new_version))
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Training contract returned'),
                _('Training contract %s was returned for revision: %s')
                % (rec.name, rec.legal_comments))

    def action_resubmit(self):
        """Revision -> Legal Review: the updated version goes back to Legal."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'revision':
                raise UserError(_('Only contracts under revision can be resubmitted.'))
            rec.state = 'legal_review'
            rec.message_post(body=_('Revised contract %s resubmitted to Legal.') % rec.name)
            notify_role_action(
                rec, 'group_eds_manager', 'group_eds_admin',
                _('Review revised training contract'),
                _('Revised training contract %s needs legal review.') % rec.name)

    def action_record_signature(self):
        """Approved -> Signed: record the authorized signature."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'approved':
                raise UserError(_('Only approved contracts can be signed.'))
            if not rec.signature and not rec.signed_by:
                raise UserError(_('Attach the signed document or record the signatory.'))
            rec.write({'state': 'signed', 'signature_date': date.today()})
            rec.message_post(body=_('Contract %s signed by %s.')
                             % (rec.name, rec.signed_by or 'authorized signatory'))
            clear_action_activities(rec)

    def action_activate(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'signed':
                raise UserError(_('Only signed contracts can be activated.'))
            rec.state = 'active'
            rec.message_post(body=_('Contract %s activated - vendor performance monitoring '
                                    'enabled.') % rec.name)

    def _require_legal_authority(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Legal review handling requires L&D Manager authority.'))

    @staticmethod
    def _bump_version(version):
        try:
            major, minor = version.lower().lstrip('v').split('.')
            return 'v%s.%s' % (major, int(minor) + 1)
        except Exception:
            return 'v1.1'


class EdsTrainingContractVersion(models.Model):
    """Version history entry of a training contract."""
    _name = 'eds.training.contract.version'
    _description = 'Training Contract Version'
    _order = 'id desc'

    contract_id = fields.Many2one('eds.training.contract', string='Contract',
                                  required=True, ondelete='cascade')
    version = fields.Char(string='Version', required=True)
    document = fields.Binary(string='Document', attachment=True)
    document_name = fields.Char(string='Document Filename')
    comment = fields.Text(string='Change Summary')
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    created_by_id = fields.Many2one('res.users', string='Created By',
                                    default=lambda self: self.env.user)


class EdsCourseVendorSelection(models.Model):
    """Post-Plan Course Vendor Sourcing & Evaluation.

    Allows sourcing multiple vendors for an approved planned course,
    applying technical/functional and financial percentage scoring templates,
    tracking vendor status (Awarded with file upload, Contract with attachment, Pending, Rejected),
    and automatically sorting proposals by highest total weighted value.
    """
    _name = 'eds.course.vendor.selection'
    _description = 'Course Vendor Selection & Evaluation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default=lambda self: _('New'))
    source_type = fields.Selection([
        ('annual_plan', 'Approved Annual Plan'),
        ('unscheduled', 'Approved Unscheduled Request'),
    ], string='Sourcing Source', default='annual_plan', required=True, tracking=True)
    annual_plan_id = fields.Many2one(
        'eds.annual.plan', string='Approved Annual Plan', tracking=True,
        domain="[('state', 'in', ('published', 'amended'))]")
    plan_line_id = fields.Many2one(
        'eds.annual.plan.line', string='Approved Plan Program', tracking=True,
        domain="[('plan_id', '=', annual_plan_id), ('is_addendum', '=', False)]")
    unscheduled_request_id = fields.Many2one(
        'eds.unscheduled.request', string='Approved Unscheduled Request', tracking=True,
        domain="[('state', '=', 'approved'), ('course_id', '!=', False)]", index=True)
    course_id = fields.Many2one(
        'eds.course', string='Catalog Course', tracking=True,
        help='Filled from the approved plan program when it uses a catalog course.')
    program_name = fields.Char(compute='_compute_program_name', string='Program Name')
    delivery_method = fields.Selection([
        ('internal', 'Internal / ToT'),
        ('local_external', 'Local External'),
        ('international', 'International'),
    ], string='Delivery Chosen for Execution', required=True,
        help='May differ from the approved plan. Sessions use this delivery type after sourcing is completed.')
    planned_delivery_method = fields.Selection(
        selection=[('internal', 'Internal / ToT'), ('local_external', 'Local External'),
                   ('international', 'International')], compute='_compute_planned_delivery_method',
        string='Planned Delivery', readonly=True)
    delivery_override = fields.Boolean(
        string='Change Delivery Type', tracking=True,
        help='Enable to change the delivery type approved for this program. A reason is required.')
    delivery_change_reason = fields.Char(
        string='Reason for Delivery Change',
        help='Explain why the execution delivery type differs from the approved plan.')
    template_type = fields.Selection([
        ('standard_70_30', 'Standard (70% Technical/Functional, 30% Financial)'),
        ('specialized_80_20', 'High Specialization (80% Technical/Functional, 20% Financial)'),
        ('balanced_50_50', 'Balanced (50% Technical, 50% Financial)'),
        ('custom', 'Custom Weighting'),
    ], string='Evaluation Template', default='standard_70_30', required=True, tracking=True)
    technical_weight = fields.Float(string='Technical / Functional Weight (%)', default=70.0)
    financial_weight = fields.Float(string='Financial / Price Weight (%)', default=30.0)

    line_ids = fields.One2many(
        'eds.course.vendor.line', 'selection_id', string='Vendor Proposals & Bids')
    vendor_count = fields.Integer(string='Vendors Count', compute='_compute_vendor_count')
    awarded_vendor_id = fields.Many2one(
        'eds.external.provider', string='First Awarded Vendor',
        compute='_compute_awarded_vendor_stored', store=True,
        help='Legacy single-vendor reference. Use Awarded Vendors for all sourcing awards.')
    awarded_bid_ids = fields.Many2many(
        'eds.course.vendor.line', string='Awarded Bids',
        compute='_compute_awarded_vendor_non_stored')
    awarded_vendor_ids = fields.Many2many(
        'eds.external.provider', string='Awarded Vendors',
        compute='_compute_awarded_vendor_non_stored')
    awarded_vendor_count = fields.Integer(
        string='Awarded Vendors', compute='_compute_awarded_vendor_non_stored')
    currency_id = fields.Many2one(
        'res.currency', string='Bid Currency', required=True,
        default=lambda self: currency_for_delivery(self.env, 'internal'),
        help='International sourcing defaults to USD; another currency can be selected.')
    state = fields.Selection([
        ('draft', 'Draft Sourcing'),
        ('evaluation', 'Under Evaluation'),
        ('awarded', 'Awarded / Contracted'),
    ], string='Status', default='draft', required=True, tracking=True)
    notes = fields.Text(string='Sourcing Notes & Objectives')

    @api.depends('source_type', 'plan_line_id.program_name', 'unscheduled_request_id.course_id.name')
    def _compute_program_name(self):
        for rec in self:
            rec.program_name = (rec.unscheduled_request_id.course_id.name
                                if rec.source_type == 'unscheduled' else rec.plan_line_id.program_name)

    @api.depends('source_type', 'plan_line_id.delivery_method', 'unscheduled_request_id.delivery_method')
    def _compute_planned_delivery_method(self):
        for rec in self:
            rec.planned_delivery_method = (rec.unscheduled_request_id.delivery_method
                                           if rec.source_type == 'unscheduled'
                                           else rec.plan_line_id.delivery_method)

    @api.onchange('source_type')
    def _onchange_source_type(self):
        self.annual_plan_id = False
        self.plan_line_id = False
        self.unscheduled_request_id = False
        self.course_id = False

    @api.onchange('unscheduled_request_id')
    def _onchange_unscheduled_request_id(self):
        request = self.unscheduled_request_id
        self.plan_line_id = request.plan_line_ids[:1] if request else False
        self.annual_plan_id = request.annual_plan_id if request else False
        self.course_id = request.course_id if request else False
        if request:
            self.delivery_override = False
            self.delivery_change_reason = False
            self.delivery_method = request.delivery_method
            self.currency_id = currency_for_delivery(self.env, request.delivery_method)

    @api.onchange('template_type')
    def _onchange_template_type(self):
        if self.template_type == 'standard_70_30':
            self.technical_weight = 70.0
            self.financial_weight = 30.0
        elif self.template_type == 'specialized_80_20':
            self.technical_weight = 80.0
            self.financial_weight = 20.0
        elif self.template_type == 'balanced_50_50':
            self.technical_weight = 50.0
            self.financial_weight = 50.0

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.source_type != 'annual_plan':
            return
        self.course_id = self.plan_line_id.course_id
        self.delivery_override = False
        self.delivery_change_reason = False
        self.delivery_method = self.plan_line_id.delivery_method
        self.currency_id = self._currency_for_plan_line(self.plan_line_id)

    @api.onchange('delivery_override')
    def _onchange_delivery_override(self):
        if not self.delivery_override:
            self.delivery_method = self.planned_delivery_method
            self.delivery_change_reason = False
            if self.delivery_method:
                self.currency_id = currency_for_delivery(self.env, self.delivery_method)

    @api.onchange('delivery_method')
    def _onchange_delivery_method(self):
        if self.delivery_method:
            self.currency_id = currency_for_delivery(self.env, self.delivery_method)

    @api.model
    def _currency_for_plan_line(self, plan_line):
        return plan_line.budget_currency_id if plan_line else currency_for_delivery(self.env, 'internal')

    @api.onchange('annual_plan_id')
    def _onchange_annual_plan_id(self):
        if self.source_type != 'annual_plan':
            return
        if self.plan_line_id.plan_id != self.annual_plan_id:
            self.plan_line_id = False
            self.course_id = False
        regular_lines = self.annual_plan_id.line_ids.filtered(lambda line: not line.is_addendum)
        if self.annual_plan_id and not self.plan_line_id and len(regular_lines) == 1:
            self.plan_line_id = regular_lines
            self.course_id = self.plan_line_id.course_id
            self.delivery_override = False
            self.delivery_change_reason = False
            self.delivery_method = self.plan_line_id.delivery_method
            self.currency_id = self._currency_for_plan_line(self.plan_line_id)

    @api.depends('line_ids')
    def _compute_vendor_count(self):
        for rec in self:
            rec.vendor_count = len(rec.line_ids)

    @api.depends('line_ids.status', 'line_ids.vendor_id')
    def _compute_awarded_vendor_stored(self):
        for rec in self:
            awarded = rec.line_ids.filtered(lambda line: line.status == 'awarded').sorted('id')
            rec.awarded_vendor_id = awarded[:1].vendor_id if awarded else False

    @api.depends('line_ids.status', 'line_ids.vendor_id')
    def _compute_awarded_vendor_non_stored(self):
        for rec in self:
            awarded = rec.line_ids.filtered(lambda line: line.status == 'awarded').sorted('id')
            rec.awarded_bid_ids = awarded
            rec.awarded_vendor_ids = awarded.mapped('vendor_id')
            rec.awarded_vendor_count = len(awarded)

    def _sourcing_source_domain(self):
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

    @api.constrains('source_type', 'annual_plan_id', 'plan_line_id', 'course_id',
                    'unscheduled_request_id', 'state')
    def _check_unique_sourcing_source(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                source, table = rec.unscheduled_request_id, 'eds_unscheduled_request'
            else:
                source, table = rec.annual_plan_id, 'eds_annual_plan'
            if not source:
                continue  # The source validation reports the missing approved record.
            self.env.cr.execute('SELECT id FROM %s WHERE id = %%s FOR UPDATE' % table, [source.id])
            if self.sudo().search_count(rec._sourcing_source_domain() + [('id', '!=', rec.id)]):
                raise ValidationError(_(
                    'This approved course or request already has provider sourcing. '
                    'Add other provider bids to the existing sourcing record.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('state', 'draft') != 'draft':
                raise UserError(_('Provider sourcing must start as a draft.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.course.vendor.selection') or _('New')
            if vals.get('source_type') == 'unscheduled' and vals.get('unscheduled_request_id'):
                request = self.env['eds.unscheduled.request'].browse(vals['unscheduled_request_id'])
                vals['annual_plan_id'] = request.annual_plan_id.id or False
                vals['plan_line_id'] = request.plan_line_ids[:1].id or False
                vals['course_id'] = request.course_id.id or False
                vals.setdefault('delivery_method', request.delivery_method)
            if vals.get('plan_line_id') and 'course_id' not in vals:
                vals['course_id'] = self.env['eds.annual.plan.line'].browse(vals['plan_line_id']).course_id.id or False
            if vals.get('plan_line_id') and not vals.get('delivery_method'):
                vals['delivery_method'] = self.env['eds.annual.plan.line'].browse(vals['plan_line_id']).delivery_method
            if vals.get('plan_line_id') and not vals.get('currency_id'):
                vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
            if vals.get('delivery_method') and not vals.get('currency_id'):
                vals['currency_id'] = currency_for_delivery(self.env, vals['delivery_method']).id
            if vals.get('delivery_method') and vals.get('currency_id'):
                validate_delivery_currency(self.env, vals['delivery_method'], vals['currency_id'])
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if vals.get('state') == 'awarded' and not self.env.context.get('eds_provider_award_transition'):
            raise UserError(_('Complete provider sourcing through the award action.'))
        source_fields = {'source_type', 'annual_plan_id', 'plan_line_id',
                         'unscheduled_request_id', 'delivery_method',
                         'delivery_override', 'delivery_change_reason'}
        if source_fields & vals.keys() and any(rec.state != 'draft' for rec in self):
            raise UserError(_('The sourcing source and delivery choice cannot change after evaluation starts.'))
        if vals.get('unscheduled_request_id'):
            request = self.env['eds.unscheduled.request'].browse(vals['unscheduled_request_id'])
            vals.update({'source_type': 'unscheduled',
                         'annual_plan_id': request.annual_plan_id.id or False,
                         'plan_line_id': request.plan_line_ids[:1].id or False,
                         'course_id': request.course_id.id or False})
            vals.setdefault('delivery_method', request.delivery_method)
        if vals.get('plan_line_id') and 'course_id' not in vals:
            vals = dict(vals, course_id=self.env['eds.annual.plan.line'].browse(vals['plan_line_id']).course_id.id or False)
        if vals.get('plan_line_id') and 'delivery_method' not in vals:
            vals = dict(vals, delivery_method=self.env['eds.annual.plan.line'].browse(vals['plan_line_id']).delivery_method)
        if vals.get('plan_line_id') and 'currency_id' not in vals:
            vals = dict(vals, currency_id=currency_for_delivery(self.env, vals['delivery_method']).id)
        elif vals.get('delivery_method') and 'currency_id' not in vals:
            vals = dict(vals, currency_id=currency_for_delivery(self.env, vals['delivery_method']).id)
        if {'plan_line_id', 'currency_id', 'delivery_method'} & vals.keys():
            for rec in self:
                validate_delivery_currency(self.env, vals.get('delivery_method', rec.delivery_method),
                                           vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    def _sync_awarded_vendor_to_sessions(self):
        for rec in self:
            source_domain = ([('unscheduled_request_id', '=', rec.unscheduled_request_id.id)]
                             if rec.source_type == 'unscheduled' else
                             [('plan_line_id', '=', rec.plan_line_id.id), ('source_type', '=', 'annual_plan')])
            sessions = self.env['eds.session'].search(source_domain + [('status', '=', 'draft')])
            for session in sessions:
                session._sync_sourcing_from_plan_line()

    def action_start_evaluation(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft sourcing records can start evaluation.'))
            if rec.delivery_method == 'internal':
                raise UserError(_('Internal delivery does not require vendor evaluation. Confirm internal delivery instead.'))
            if rec.source_type == 'unscheduled':
                if rec.unscheduled_request_id.state != 'approved':
                    raise UserError(_('Vendor sourcing requires an approved unscheduled request.'))
            elif rec.annual_plan_id.state not in ('published', 'amended'):
                raise UserError(_('Vendor sourcing requires an approved Annual Plan.'))
            if not rec.line_ids:
                raise UserError(_('Add at least one vendor before starting evaluation.'))
            expected_category = 'international' if rec.delivery_method == 'international' else 'local'
            if rec.line_ids.filtered(lambda line: line.vendor_id and line.vendor_id.category != expected_category):
                raise UserError(_('Remove provider bids that do not match the selected delivery type.'))
            rec.state = 'evaluation'

    def action_mark_awarded(self):
        for rec in self:
            if rec.delivery_method != 'internal' and rec.state not in ('evaluation', 'awarded'):
                raise UserError(_('Start provider evaluation before completing sourcing.'))
            if rec.delivery_method == 'internal' and rec.state not in ('draft', 'awarded'):
                raise UserError(_('Internal delivery must be confirmed from a draft sourcing record.'))
            awarded = rec.line_ids.filtered(lambda line: line.status == 'awarded')
            if rec.delivery_method != 'internal' and not awarded:
                raise UserError(_('Award a qualified vendor before completing sourcing.'))
            if rec.delivery_method == 'internal' and awarded:
                raise UserError(_('An awarded provider cannot be used with internal delivery. Select external delivery instead.'))
            expected_category = 'international' if rec.delivery_method == 'international' else 'local'
            if awarded.filtered(lambda bid: not bid.vendor_id
                                or bid.vendor_id.category != expected_category
                                or not bid.technical_threshold_met):
                raise UserError(_('Every awarded provider must match the delivery type and pass the technical gate.'))
            changed = rec.state != 'awarded'
            if changed and rec.delivery_method != rec.planned_delivery_method:
                if not rec.delivery_override or not rec.delivery_change_reason:
                    raise UserError(_('Enable Change Delivery Type and explain why the approved delivery type is changing.'))
            related_sessions = (self.env['eds.session'].search([
                ('unscheduled_request_id', '=', rec.unscheduled_request_id.id)])
                if rec.source_type == 'unscheduled' else rec.plan_line_id.session_ids)
            if changed and related_sessions.filtered(
                    lambda session: session.status not in ('draft', 'cancelled')
                    and session.delivery_method != rec.delivery_method):
                raise UserError(_('A session has already been scheduled with a different delivery type. Resolve that schedule before changing delivery.'))
            if changed:
                rec.with_context(eds_provider_award_transition=True).write({'state': 'awarded'})
            rec._sync_awarded_vendor_to_sessions()
            if changed and rec.delivery_method != rec.planned_delivery_method:
                source = rec.unscheduled_request_id if rec.source_type == 'unscheduled' else rec.annual_plan_id
                source.message_post(body=_('Delivery for %s changed from %s to %s: %s') % (
                    rec.program_name,
                    dict(rec._fields['planned_delivery_method'].selection).get(rec.planned_delivery_method),
                    dict(rec._fields['delivery_method'].selection).get(rec.delivery_method),
                    rec.delivery_change_reason))

    @api.constrains('source_type', 'annual_plan_id', 'plan_line_id', 'unscheduled_request_id',
                    'course_id', 'technical_weight', 'financial_weight',
                    'delivery_method', 'delivery_override', 'delivery_change_reason')
    def _check_plan_and_weights(self):
        for rec in self:
            if rec.source_type == 'unscheduled':
                request = rec.unscheduled_request_id
                if not request or request.state != 'approved' or rec.course_id != request.course_id:
                    raise ValidationError(_('Select an approved unscheduled request and its catalog course.'))
                if rec.plan_line_id and rec.plan_line_id.unscheduled_request_id != request:
                    raise ValidationError(_('The addendum program must belong to the unscheduled request.'))
                if rec.annual_plan_id != request.annual_plan_id:
                    raise ValidationError(_('The annual plan must match the unscheduled request.'))
            else:
                if rec.unscheduled_request_id or not rec.annual_plan_id or not rec.plan_line_id:
                    raise ValidationError(_('Select an approved annual plan and one of its regular programs.'))
                if rec.annual_plan_id.state not in ('published', 'amended'):
                    raise ValidationError(_('Vendor sourcing requires an approved Annual Plan.'))
                if (rec.plan_line_id.plan_id != rec.annual_plan_id or rec.plan_line_id.is_addendum
                        or rec.plan_line_id.course_id != rec.course_id):
                    raise ValidationError(_('The selected program must belong to the chosen Annual Plan; its catalog course must match.'))
            if rec.technical_weight < 0 or rec.financial_weight < 0 or abs(
                    rec.technical_weight + rec.financial_weight - 100.0) > 0.01:
                raise ValidationError(_('Technical and financial weights must total 100%.'))
            if rec.delivery_method != rec.planned_delivery_method:
                if not rec.delivery_override or not (rec.delivery_change_reason or '').strip():
                    raise ValidationError(_(
                        'Enable Change Delivery Type and enter a reason before changing the approved delivery type.'))


class EdsCourseVendorLine(models.Model):
    """Vendor line inside course vendor sourcing.

    Calculates weighted total score from technical/functional % and financial %.
    Sorted by total_score desc.
    """
    _name = 'eds.course.vendor.line'
    _description = 'Course Vendor Evaluation Line'
    _order = 'total_score desc, id desc'

    selection_id = fields.Many2one(
        'eds.course.vendor.selection', string='Vendor Selection', required=True, ondelete='cascade', index=True)
    delivery_category = fields.Selection(
        [('local', 'Local'), ('international', 'International')],
        compute='_compute_delivery_category', string='Provider Category')
    vendor_id = fields.Many2one(
        'eds.external.provider', string='Vendor / Training Provider')
    trainer_id = fields.Many2one(
        'eds.trainer', string='Proposed Trainer',
        domain="[('trainer_type','=','external'),('external_provider_id','=',vendor_id),('state','=','active')]",
        help='Optional named trainer from this provider; the session may choose a different trainer.')
    vendor_name = fields.Char(string='Vendor Name')
    price_quoted = fields.Monetary(
        string='Quoted Price', currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one('res.currency', string='Bid Currency', required=True,
                                  default=lambda self: currency_for_delivery(self.env, 'internal'))
    quality_score = fields.Float(string='Technical Quality & Relevance (0-10)')
    experience_score = fields.Float(string='Firm & Trainer Experience (0-10)')
    scalability_score = fields.Float(string='Delivery & Scalability (0-10)')
    demo_score = fields.Float(string='Demo Presentation (0-10)')
    price_score = fields.Float(string='Financial Proposal (0-10)')
    technical_score = fields.Float(
        string='Technical / Functional Score (0-100)', compute='_compute_template_scores', store=True)
    financial_score = fields.Float(
        string='Financial Score (0-100)', compute='_compute_template_scores', store=True)
    technical_threshold_met = fields.Boolean(
        string='Technical Gate Met', compute='_compute_template_scores', store=True)
    total_score = fields.Float(
        string='Total Score', compute='_compute_total_score', store=True)

    status = fields.Selection([
        ('draft', 'Draft'),
        ('awarded', 'Awarded'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True)

    award_attachment = fields.Binary(string='Award Letter (Optional)', attachment=True)
    award_filename = fields.Char(string='Award Filename')
    contract_attachment = fields.Binary(string='Signed Contract (Optional)', attachment=True)
    contract_filename = fields.Char(string='Contract Filename')
    notes = fields.Char(string='Remarks / Evaluation Summary')
    award_justification = fields.Text(
        string='Award Remark / Justification',
        help='Explain this provider award or any unusual selection decision.')

    @api.depends('selection_id.delivery_method')
    @api.depends_context('default_delivery_category')
    def _compute_delivery_category(self):
        for line in self:
            method = line.selection_id.delivery_method
            line.delivery_category = (
                'international' if method == 'international' else 'local'
            ) if method else self.env.context.get('default_delivery_category', 'local')

    @api.model_create_multi
    def create(self, vals_list):
        self._lock_vendor_selections(vals.get('selection_id') for vals in vals_list)
        for vals in vals_list:
            if not self.env.su and vals.get('status', 'draft') != 'draft':
                raise UserError(_('Provider bids must start as drafts and follow evaluation.'))
            if vals.get('selection_id') and not vals.get('currency_id'):
                vals['currency_id'] = self.env['eds.course.vendor.selection'].browse(
                    vals['selection_id']).currency_id.id
            if vals.get('selection_id') and vals.get('currency_id'):
                selection = self.env['eds.course.vendor.selection'].browse(vals['selection_id'])
                validate_delivery_currency(self.env, selection.delivery_method, vals['currency_id'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('status') == 'awarded' and not self.env.context.get('eds_provider_bid_award'):
            raise UserError(_('Award a provider through the bid evaluation action.'))
        if {'selection_id', 'vendor_id', 'status'} & vals.keys():
            self._lock_vendor_selections(
                list(self.mapped('selection_id').ids) + [vals.get('selection_id')])
        if {'selection_id', 'currency_id'} & vals.keys():
            for rec in self:
                selection = (self.env['eds.course.vendor.selection'].browse(vals['selection_id'])
                             if vals.get('selection_id') else rec.selection_id)
                validate_delivery_currency(self.env, selection.delivery_method,
                                           vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    def _lock_vendor_selections(self, selection_ids):
        """Serialize bid edits before checking duplicate vendors or awards."""
        for selection_id in sorted({int(value) for value in selection_ids if value}):
            self.env.cr.execute(
                'SELECT id FROM eds_course_vendor_selection WHERE id = %s FOR UPDATE',
                [selection_id],
            )

    @api.onchange('selection_id')
    def _onchange_selection_currency(self):
        if self.selection_id:
            self.currency_id = self.selection_id.currency_id

    @api.onchange('vendor_id')
    def _onchange_vendor_id(self):
        if self.vendor_id and not self.vendor_name:
            self.vendor_name = self.vendor_id.name
        if self.trainer_id and self.trainer_id.external_provider_id != self.vendor_id:
            self.trainer_id = False

    @api.onchange('quality_score', 'experience_score', 'scalability_score', 'demo_score', 'price_score')
    def _onchange_score_range(self):
        fields_to_check = ('quality_score', 'experience_score', 'scalability_score',
                           'demo_score', 'price_score')
        invalid = [field for field in fields_to_check if getattr(self, field) < 0 or getattr(self, field) > 10]
        for field in invalid:
            setattr(self, field, 0.0)
        if invalid:
            return {'warning': {
                'title': _('Invalid vendor score'),
                'message': _('Each vendor criterion must be scored from 0 to 10. Invalid entries were reset to zero.'),
            }}

    @api.depends('quality_score', 'experience_score', 'scalability_score', 'demo_score',
                 'price_score', 'selection_id.technical_weight')
    def _compute_template_scores(self):
        for rec in self:
            # Source matrix: 30% quality, 20% experience, 10% scalability,
            # 10% demonstration, 30% financial; each input is scored 0-10.
            technical_points = (rec.quality_score * 3 + rec.experience_score * 2
                                + rec.scalability_score + rec.demo_score)
            rec.technical_score = technical_points / 70.0 * 100.0
            rec.financial_score = rec.price_score * 10.0
            rec.technical_threshold_met = technical_points >= 40.0

    @api.constrains('quality_score', 'experience_score', 'scalability_score',
                    'demo_score', 'price_score', 'vendor_id', 'trainer_id',
                    'selection_id', 'status')
    def _check_vendor_scores(self):
        for rec in self:
            scores = (rec.quality_score, rec.experience_score, rec.scalability_score,
                      rec.demo_score, rec.price_score)
            if any(score < 0 or score > 10 for score in scores):
                raise ValidationError(_('Vendor matrix scores must be between 0 and 10.'))
            if rec.vendor_id and self.search_count([
                    ('selection_id', '=', rec.selection_id.id), ('vendor_id', '=', rec.vendor_id.id),
                    ('id', '!=', rec.id)]):
                raise ValidationError(_('A vendor may appear only once in a course selection.'))
            if rec.vendor_id and rec.selection_id.delivery_method != 'internal':
                expected_category = ('international' if rec.selection_id.delivery_method == 'international'
                                     else 'local')
                if rec.vendor_id.category != expected_category:
                    raise ValidationError(_('The provider must match the selected delivery type.'))
            if rec.trainer_id and (rec.trainer_id.trainer_type != 'external' or
                                   rec.trainer_id.external_provider_id != rec.vendor_id):
                raise ValidationError(_('The proposed trainer must belong to the selected provider.'))
            if rec.status == 'awarded' and (not rec.vendor_id
                    or not rec.technical_threshold_met
                    or rec.selection_id.delivery_method == 'internal'):
                raise ValidationError(_(
                    'An awarded bid needs a registered provider, an external delivery type, '
                    'and a passing technical score.'))

    @api.depends('technical_score', 'financial_score', 'technical_threshold_met', 'selection_id.technical_weight',
                 'selection_id.financial_weight')
    def _compute_total_score(self):
        for rec in self:
            t_w = rec.selection_id.technical_weight
            f_w = rec.selection_id.financial_weight
            sum_w = t_w + f_w
            if sum_w > 0 and rec.technical_threshold_met:
                rec.total_score = round((rec.technical_score * t_w + rec.financial_score * f_w) / sum_w, 2)
            else:
                rec.total_score = 0.0

    def action_award(self):
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only a draft vendor bid can be awarded.'))
            if rec.selection_id.delivery_method == 'internal':
                raise UserError(_('Choose local external or international delivery before awarding a provider.'))
            if rec.vendor_id and rec.vendor_id.category != (
                    'international' if rec.selection_id.delivery_method == 'international' else 'local'):
                raise UserError(_('The provider category must match the chosen delivery type.'))
            if rec.selection_id.state not in ('evaluation', 'awarded'):
                raise UserError(_('Start provider evaluation before awarding a bid.'))
            if not rec.technical_threshold_met:
                raise UserError(_(
                    'Score the vendor first. At least 40 of the 70 technical points are required before awarding.'))
            if not rec.vendor_id:
                raise UserError(_('Select a registered training provider before awarding.'))
            # Serialize concurrent bid decisions on the parent. Multiple distinct
            # providers may be awarded, including after sourcing is completed.
            self.env.cr.execute(
                'SELECT id FROM eds_course_vendor_selection WHERE id = %s FOR UPDATE',
                [rec.selection_id.id])
            rec.with_context(eds_provider_bid_award=True).write({'status': 'awarded'})
            rec.selection_id.message_post(body=_('Provider %s awarded for sourcing %s. %s') % (
                rec.vendor_id.display_name, rec.selection_id.name,
                rec.award_justification or ''))
            if rec.selection_id.state == 'awarded':
                rec.selection_id._sync_awarded_vendor_to_sessions()

    def action_reject(self):
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only a draft vendor bid can be rejected.'))
            rec.status = 'rejected'
