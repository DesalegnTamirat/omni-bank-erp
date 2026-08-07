# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsVenueRequirement(models.Model):
    """Standardized Venue Requirement Specification (VRS) (FREDS037).

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
    vrs_document = fields.Binary(string='VRS Document')
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
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
                                  'before submitting (FREDS037).'))
            rec.state = 'submitted'
            rec.message_post(body=_('VRS %s submitted for Director PPDD approval (FREDS037).')
                             % rec.name)

    def action_director_approve(self):
        for rec in self:
            rec._require_director_authority()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted VRS documents can be approved.'))
            rec.write({'state': 'director_approved',
                       'approved_by_id': self.env.user.id,
                       'approval_date': fields.Datetime.now()})
            rec.message_post(body=_('VRS %s approved by Director PPDD - RFP may now be initiated '
                                    '(FREDS037).') % rec.name)

    def action_return_draft(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted VRS documents can be returned.'))
            rec.state = 'draft'
            rec.message_post(body=_('VRS %s returned to the officer for amendment.') % rec.name)

    def _require_director_authority(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('The Director - PPDD approval step requires L&D Manager authority '
                              '(FREDS037).'))


class EdsRfp(models.Model):
    """Structured Request for Proposal for training vendors and venues (FREDS030/031).

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
        help='For venue procurement: the approved VRS (FREDS037).')
    objectives = fields.Text(string='Training Objectives')
    scope_of_work = fields.Text(string='Scope of Work', required=True)
    technical_specifications = fields.Text(string='Technical Specifications')
    venue_accommodation_requirements = fields.Text(string='Venue & Accommodation Requirements')
    evaluation_criteria_ids = fields.One2many(
        'eds.rfp.criteria.line', 'rfp_id', string='Evaluation Criteria',
        help='Criteria published in the RFP (FREDS030).')
    submission_deadline = fields.Date(string='Submission Deadline', required=True, tracking=True)
    min_providers = fields.Integer(
        string='Minimum Providers', compute='_compute_min_providers', store=True,
        help='Configurable minimum number of qualified providers to issue to (default >= 3, FREDS030).')
    min_providers_met = fields.Boolean(string='Minimum Providers Met', compute='_compute_min_providers', store=True)
    provider_ids = fields.Many2many(
        'eds.external.provider', 'eds_rfp_provider_rel', 'rfp_id', 'provider_id',
        string='Qualified Providers',
        domain="[('pre_qualified', '=', True)]",
        help='Pre-qualified providers the RFP is issued to.')
    proposal_ids = fields.One2many('eds.vendor.proposal', 'rfp_id', string='Proposals')
    proposal_count = fields.Integer(string='Proposals', compute='_compute_proposal_count')
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

    def action_issue(self):
        """Draft -> Issued: validate venue approval and minimum provider count (FREDS030/037)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft RFPs can be issued.'))
            if rec.venue_requirement_id and rec.venue_requirement_id.state != 'director_approved':
                raise UserError(_('The venue requirement must be approved by the Director PPDD '
                                  'before the RFP is issued (FREDS037).'))
            if not rec.provider_ids:
                raise UserError(_('Select at least one qualified provider to issue the RFP to.'))
            if len(rec.provider_ids) < rec.min_providers:
                raise UserError(_('The RFP must be issued to at least %s qualified providers '
                                  '(FREDS030).') % rec.min_providers)
            rec.write({'state': 'issued', 'issuance_date': date.today()})
            rec.message_post(body=_('RFP %s issued to %s qualified providers (FREDS030).')
                             % (rec.name, len(rec.provider_ids)))

    def action_receive_proposals(self):
        """Issued -> Receiving: open the submission window (FREDS031)."""
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_('Only issued RFPs can start receiving proposals.'))
            rec.state = 'receiving'
            rec.message_post(body=_('RFP %s opened for proposal submission (two-envelope, FREDS031).')
                             % rec.name)

    def action_close_receiving(self):
        """Receiving -> Evaluation: receipts closed and envelopes are opened by the committee."""
        for rec in self:
            if rec.state != 'receiving':
                raise UserError(_('Only RFPs in the receiving stage can move to evaluation.'))
            if not rec.proposal_ids:
                raise UserError(_('At least one proposal must be registered before evaluation.'))
            rec.write({'state': 'evaluation', 'receipt_opened_date': datetime.now()})
            rec.message_post(body=_('RFP %s moved to evaluation - envelopes opened and logged '
                                    '(FREDS031).') % rec.name)

    def action_award(self):
        """Evaluation -> Awarded: pick the winning proposal and auto-generate the contract."""
        for rec in self:
            if rec.state != 'evaluation':
                raise UserError(_('Only RFPs under evaluation can be awarded.'))
            if not rec.awarded_proposal_id:
                raise UserError(_('Select the awarded proposal first (FREDS034).'))
            rec.state = 'awarded'
            rec.message_post(body=_('RFP %s awarded to %s (FREDS034).')
                             % (rec.name, rec.awarded_proposal_id.provider_id.name))
            contract = self.env['eds.training.contract'].create({
                'rfp_id': rec.id,
                'course_id': rec.course_id.id,
                'provider_id': rec.awarded_proposal_id.provider_id.id,
                'proposal_id': rec.awarded_proposal_id.id,
                'combined_score': rec.awarded_proposal_id.combined_score,
            })
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.training.contract',
                'res_id': contract.id,
                'view_mode': 'form',
            }

    def action_back_to_receiving(self):
        for rec in self:
            if rec.state != 'evaluation':
                raise UserError(_('Only RFPs under evaluation can return to receiving.'))
            rec.state = 'receiving'
            rec.message_post(body=_('RFP %s returned to receiving.') % rec.name)


class EdsRfpCriteriaLine(models.Model):
    """Published evaluation criteria line on an RFP (FREDS030)."""
    _name = 'eds.rfp.criteria.line'
    _description = 'RFP Evaluation Criteria Line'
    _order = 'sequence, id'

    rfp_id = fields.Many2one('eds.rfp', string='RFP', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Order', default=10)
    name = fields.Char(string='Criterion', required=True)
    weight = fields.Float(string='Weight (%)', default=10.0, required=True)


class EdsVendorProposal(models.Model):
    """Two-envelope proposal registration (FREDS031).

    Technical and financial envelopes are registered separately; the financial
    envelope is only opened after the technical evaluation passes the configured
    minimum threshold (FREDS032).
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
    technical_envelope = fields.Binary(string='Technical Envelope')
    technical_envelope_name = fields.Char(string='Technical Envelope Filename')
    financial_envelope = fields.Binary(string='Financial Envelope')
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
        help='Weighted blend of technical and financial scores (FREDS034).')
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
        """Open the technical envelope and log the event (FREDS031)."""
        for rec in self:
            if rec.state != 'registered':
                raise UserError(_('Only registered proposals can have their technical envelope opened.'))
            rec.write({'state': 'technical_opened', 'technical_opened_date': datetime.now()})
            rec.message_post(body=_('Technical envelope of %s opened and registered (FREDS031).')
                             % rec.name)

    def action_open_financial(self):
        """Open the financial envelope - gated on the technical threshold (FREDS032)."""
        for rec in self:
            if rec.state != 'technical_opened':
                raise UserError(_('Open the technical envelope before the financial envelope.'))
            if not rec.technical_score_id or rec.technical_score_id.state != 'approved':
                raise UserError(_('Complete and approve the technical evaluation first (FREDS032).'))
            if not rec.technical_score_id.threshold_met:
                raise UserError(_('The technical score of %s is below the minimum qualification '
                                  'threshold - the financial envelope must not be opened (FREDS032).')
                                % rec.technical_score)
            rec.write({'state': 'financial_opened', 'financial_opened_date': datetime.now()})
            rec.message_post(body=_('Financial envelope of %s opened - technical threshold met '
                                    '(FREDS032).') % rec.name)

    def action_mark_evaluated(self):
        for rec in self:
            if rec.state != 'financial_opened':
                raise UserError(_('Only proposals with both envelopes opened can be marked evaluated.'))
            rec.state = 'evaluated'
            rec.message_post(body=_('Proposal %s fully evaluated (FREDS034).') % rec.name)


class EdsEvaluationCriteria(models.Model):
    """Configurable weighted evaluation criteria templates (FREDS032/033)."""
    _name = 'eds.evaluation.criteria'
    _description = 'Evaluation Criteria Template'
    _order = 'evaluation_type, sequence, id'

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
    """Weighted evaluation of a vendor proposal (FREDS032/033).

    Technical and financial evaluations are separate records; a technical evaluation
    below the configured minimum threshold blocks financial evaluation (FREDS032).
    International provider + host-country evaluations use their own criteria set
    (FREDS033) and generate ranked recommendations for Director PPDD / CPCO review.
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
             'before the financial evaluation is permitted (FREDS032).')
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
            threshold = rec._get_int_param('eds.technical_min_threshold', 70)
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
        """Seed default criteria lines from the configurable template (FREDS032/033)."""
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
            rec.message_post(body=_('Evaluation %s submitted for approval (FREDS034).') % rec.name)

    def action_approve(self):
        for rec in self:
            rec._require_evaluation_approver()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted evaluations can be approved.'))
            rec.state = 'approved'
            rec.message_post(body=_('Evaluation %s approved - total score %s%% (FREDS034).')
                             % (rec.name, rec.total_score))

    def _require_evaluation_approver(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Evaluation approval requires L&D Manager authority (FREDS034).'))


class EdsVendorEvaluationLine(models.Model):
    """One scored criterion inside a vendor evaluation."""
    _name = 'eds.vendor.evaluation.line'
    _description = 'Vendor Evaluation Line'
    _order = 'evaluation_id, sequence, id'

    evaluation_id = fields.Many2one('eds.vendor.evaluation', string='Evaluation',
                                    required=True, ondelete='cascade')
    sequence = fields.Integer(string='Order', default=10)
    criterion_id = fields.Many2one('eds.evaluation.criteria', string='Criterion')
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
    """Training contract / service agreement (FREDS035).

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
    course_id = fields.Many2one('eds.course', string='Training Program', tracking=True)
    combined_score = fields.Float(string='Combined Score (%)', readonly=True,
                                  help='Snapshot of the winning proposal score (FREDS034).')
    contract_amount = fields.Monetary(string='Contract Amount', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    version = fields.Char(string='Version', default='v1.0', readonly=True)
    version_ids = fields.One2many('eds.training.contract.version', 'contract_id',
                                  string='Version History', copy=True)
    legal_comments = fields.Text(string='Legal Comments / Amendments')
    legal_reviewer_id = fields.Many2one('res.users', string='Legal Reviewer')
    signature = fields.Binary(string='Authorized Signature')
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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.training.contract') or _('New')
        return super().create(vals_list)

    # ── Workflow (FREDS035) ──────────────────────────────────────────────────
    def action_send_legal(self):
        """Draft -> Legal Review: route the draft agreement to the Legal Directorate."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft contracts can be routed to Legal.'))
            rec.state = 'legal_review'
            rec.message_post(body=_('Contract %s routed to the Legal Directorate for review '
                                    '(FREDS035).') % rec.name)

    def action_legal_approve(self):
        """Legal Review -> Approved (or Revision with a new version)."""
        for rec in self:
            rec._require_legal_authority()
            if rec.state != 'legal_review':
                raise UserError(_('Only contracts under legal review can be approved.'))
            if rec.legal_comments and not rec.version_ids:
                raise UserError(_('Record the amended contract version before approving '
                                  '(FREDS035).'))
            rec.write({'state': 'approved', 'legal_reviewer_id': self.env.user.id})
            rec.message_post(body=_('Contract %s approved by Legal (FREDS035).') % rec.name)

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
                                    '(FREDS035).') % (rec.name, new_version))

    def action_resubmit(self):
        """Revision -> Legal Review: the updated version goes back to Legal."""
        for rec in self:
            if rec.state != 'revision':
                raise UserError(_('Only contracts under revision can be resubmitted.'))
            rec.state = 'legal_review'
            rec.message_post(body=_('Revised contract %s resubmitted to Legal (FREDS035).') % rec.name)

    def action_record_signature(self):
        """Approved -> Signed: record the authorized signature."""
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only approved contracts can be signed.'))
            if not rec.signature and not rec.signed_by:
                raise UserError(_('Attach the signed document or record the signatory.'))
            rec.write({'state': 'signed', 'signature_date': date.today()})
            rec.message_post(body=_('Contract %s signed by %s (FREDS035).')
                             % (rec.name, rec.signed_by or 'authorized signatory'))

    def action_activate(self):
        for rec in self:
            if rec.state != 'signed':
                raise UserError(_('Only signed contracts can be activated.'))
            rec.state = 'active'
            rec.message_post(body=_('Contract %s activated - vendor performance monitoring '
                                    'enabled (FREDS036).') % rec.name)

    def _require_legal_authority(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Legal review handling requires L&D Manager authority (FREDS035).'))

    @staticmethod
    def _bump_version(version):
        try:
            major, minor = version.lower().lstrip('v').split('.')
            return 'v%s.%s' % (major, int(minor) + 1)
        except Exception:
            return 'v1.1'


class EdsTrainingContractVersion(models.Model):
    """Version history entry of a training contract (FREDS035)."""
    _name = 'eds.training.contract.version'
    _description = 'Training Contract Version'
    _order = 'id desc'

    contract_id = fields.Many2one('eds.training.contract', string='Contract',
                                  required=True, ondelete='cascade')
    version = fields.Char(string='Version', required=True)
    document = fields.Binary(string='Document')
    document_name = fields.Char(string='Document Filename')
    comment = fields.Text(string='Change Summary')
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    created_by_id = fields.Many2one('res.users', string='Created By',
                                    default=lambda self: self.env.user)
