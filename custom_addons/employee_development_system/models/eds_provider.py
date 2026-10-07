# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EdsExternalProvider(models.Model):
    """Approved database of local / international training providers.

    Carries accreditation, service offerings, pre-qualification, historical
    performance rating (computed from post-training evaluations, ),
    contractual information and eligibility records.
    """
    _name = 'eds.external.provider'
    _description = 'External Training Provider'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='Provider Name', required=True, tracking=True)
    code = fields.Char(string='Provider Code', readonly=True, copy=False,
                       default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Partner')
    category = fields.Selection([
        ('local', 'Local Provider'),
        ('international', 'International Provider'),
    ], string='Category', default='local', required=True, tracking=True)
    country_id = fields.Many2one('res.country', string='Country')
    provider_type = fields.Selection([
        ('university', 'University / Academic Institute'),
        ('consultancy', 'Consultancy Firm'),
        ('vendor', 'Software / Tech Vendor'),
        ('individual', 'Individual Consultant'),
        ('association', 'Professional Association'),
        ('regulatory', 'Regulatory / Standards Body'),
        ('other', 'Other'),
    ], string='Provider Type', default='consultancy', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    rate_per_session = fields.Monetary(string='Indicative Rate per Session', currency_field='currency_id')
    accreditation = fields.Char(string='Accreditation Status')
    service_offerings = fields.Text(string='Service Offerings')
    pre_qualified = fields.Boolean(
        string='Pre-Qualified', tracking=True,
        help='Pre-qualified vendors are eligible for RFP distribution.')
    rating = fields.Float(
        string='Average Rating', compute='_compute_rating', store=True, digits=(3, 2),
        help='Computed from the post-training performance history.')
    rating_count = fields.Integer(string='Evaluations', compute='_compute_rating', store=True)
    performance_history_ids = fields.One2many(
        'eds.provider.performance.history', 'provider_id',
        string='Performance History',
        help='Post-training vendor/venue evaluations.')
    contract_ids = fields.One2many('eds.training.contract', 'provider_id', string='Contracts')
    contract_count = fields.Integer(string='Contracts', compute='_compute_contract_count')
    trainer_ids = fields.One2many('eds.trainer', 'external_provider_id', string='External Trainers')
    contact_name = fields.Char(string='Contact Person')
    phone = fields.Char(string='Phone Number')
    email = fields.Char(string='Email Address')
    website = fields.Char(string='Website')
    years_of_experience = fields.Integer(string='Years of Experience', default=1)
    specialization_areas = fields.Text(string='Specialization & Training Domains')
    tax_id = fields.Char(string='TIN / Business License Number')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'eds_provider_attachment_rel', 'provider_id', 'attachment_id',
        string='Profile Documents & Certifications')
    notes = fields.Text(string='Vendor Profile Notes')
    active = fields.Boolean(string='Active', default=True)

    @api.depends('performance_history_ids.rating')
    def _compute_rating(self):
        for rec in self:
            ratings = [float(r.rating) for r in rec.performance_history_ids if r.rating]
            rec.rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
            rec.rating_count = len(ratings)

    @api.depends('contract_ids')
    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = len(rec.contract_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.external.provider') or _('New')
        return super().create(vals_list)

    def action_toggle_qualified(self):
        for rec in self:
            rec.pre_qualified = not rec.pre_qualified
            rec.message_post(body=_('Provider %s pre-qualification set to %s.')
                             % (rec.name, rec.pre_qualified))


class EdsProviderPerformanceHistory(models.Model):
    """Post-training evaluation of a provider or venue.

    Feeds the provider's historical performance profile automatically.
    """
    _name = 'eds.provider.performance.history'
    _description = 'Provider / Venue Performance History'
    _order = 'evaluation_date desc'

    provider_id = fields.Many2one('eds.external.provider', string='Provider',
                                  ondelete='cascade')
    # Venues are registered in  (eds.venue); this optional free-text keeps
    #  usable before then. session_id links in .
    venue_name = fields.Char(string='Venue', help='Venue evaluated (free text until ).')
    course_id = fields.Many2one('eds.course', string='Training Program')
    evaluation_date = fields.Date(string='Evaluation Date', default=fields.Date.context_today)
    service_quality = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Service Quality', required=True)
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Overall Rating', required=True)
    venue_readiness = fields.Text(string='Venue Readiness / Facilities / Catering / Accommodation')
    issues_raised = fields.Text(string='Issues Raised')
    corrective_actions = fields.Text(string='Corrective Actions Taken')
    notes = fields.Text(string='Notes')
    evaluated_by_id = fields.Many2one('res.users', string='Evaluated By',
                                      default=lambda self: self.env.user)
    session_id = fields.Many2one('eds.session', string='Training Session')
    contract_id = fields.Many2one('eds.training.contract', string='Contract Ref')
    score_content_relevance = fields.Selection([
        ('1', '1 - Poor'), ('2', '2 - Fair'), ('3', '3 - Good'), ('4', '4 - Very Good'), ('5', '5 - Excellent')
    ], string='Content Relevance & Syllabus Adherence', default='4')
    score_trainer_quality = fields.Selection([
        ('1', '1 - Poor'), ('2', '2 - Fair'), ('3', '3 - Good'), ('4', '4 - Very Good'), ('5', '5 - Excellent')
    ], string='Trainer Competence & Delivery', default='4')
    score_time_management = fields.Selection([
        ('1', '1 - Poor'), ('2', '2 - Fair'), ('3', '3 - Good'), ('4', '4 - Very Good'), ('5', '5 - Excellent')
    ], string='Punctuality & Schedule Adherence', default='4')
    score_logistics_handouts = fields.Selection([
        ('1', '1 - Poor'), ('2', '2 - Fair'), ('3', '3 - Good'), ('4', '4 - Very Good'), ('5', '5 - Excellent')
    ], string='Materials, Handouts & Exercises', default='4')
    score_responsiveness = fields.Selection([
        ('1', '1 - Poor'), ('2', '2 - Fair'), ('3', '3 - Good'), ('4', '4 - Very Good'), ('5', '5 - Excellent')
    ], string='Administrative Responsiveness & Reporting', default='4')
    recommend_future_tenders = fields.Selection([
        ('strongly_recommend', 'Strongly Recommended for Future Programs'),
        ('recommend', 'Recommended with Minor Improvements'),
        ('conditional', 'Conditional / Watchlist'),
        ('do_not_recommend', 'Do Not Recommend / Blacklist'),
    ], string='Future Procurement Recommendation', default='recommend', required=True)
    evaluated_by_officer = fields.Char(string='Evaluated by (L&D Officer)')
    approved_by_tl = fields.Char(string='Approved by (Team Leader, L&D)')

    def action_print_appraisal(self):
        """Prints official Form EDS-F-13 Provider Performance Appraisal PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_vendor_appraisal').report_action(self)
    _check_provider_or_venue_required = models.Constraint(
        'CHECK(provider_id IS NOT NULL OR venue_name IS NOT NULL)',
        'Link the evaluation to a provider or enter a venue name!',
    )
