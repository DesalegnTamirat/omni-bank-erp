# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta

class EdsBudget(models.Model):
    _name = 'eds.budget'
    _description = 'EDS Annual L&D Budget Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Budget Reference', required=True, copy=False, default=lambda self: _('New'))
    fiscal_year = fields.Char(string='Fiscal Year', required=True, tracking=True, default='2025/2026')
    category = fields.Selection([
        ('internal', 'Internal Classroom Training'),
        ('local_external', 'Local External Training'),
        ('international', 'International Training'),
        ('sponsorship', 'Certification Sponsorship'),
        ('education_assistance', 'Staff Education Assistance'),
    ], string='Budget Category', required=True, tracking=True, default='internal')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    allocated = fields.Monetary(string='Allocated Budget', currency_field='currency_id', required=True, tracking=True)
    committed = fields.Monetary(string='Committed Amount', compute='_compute_amounts', currency_field='currency_id', store=True)
    spent = fields.Monetary(string='Spent Amount', compute='_compute_amounts', currency_field='currency_id', store=True)
    remaining = fields.Monetary(string='Remaining Balance', compute='_compute_amounts', currency_field='currency_id', store=True)
    utilization_pct = fields.Float(string='Utilization (%)', compute='_compute_amounts', store=True)
    line_ids = fields.One2many('eds.budget.line', 'budget_id', string='Budget Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.budget') or _('New')
        return super(EdsBudget, self).create(vals_list)

    @api.depends('allocated', 'line_ids.amount', 'line_ids.status')
    def _compute_amounts(self):
        for rec in self:
            committed = sum(rec.line_ids.filtered(lambda l: l.status in ['committed', 'paid']).mapped('amount'))
            spent = sum(rec.line_ids.filtered(lambda l: l.status == 'paid').mapped('amount'))
            rec.committed = committed
            rec.spent = spent
            rec.remaining = rec.allocated - spent
            rec.utilization_pct = (spent / rec.allocated * 100.0) if rec.allocated > 0 else 0.0

    def action_approve(self):
        for rec in self:
            rec.state = 'approved'
            rec.message_post(body=_("Annual L&D budget %s approved.") % rec.name)

    def action_lock(self):
        for rec in self:
            rec.state = 'locked'
            rec.message_post(body=_("Annual L&D budget %s locked.") % rec.name)

class EdsBudgetLine(models.Model):
    _name = 'eds.budget.line'
    _description = 'EDS Budget Line Item'

    budget_id = fields.Many2one('eds.budget', string='Parent Budget', ondelete='cascade', required=True)
    course_id = fields.Many2one('eds.course', string='Program / Course')
    session_id = fields.Many2one('eds.session', string='Training Session')
    cost_type = fields.Selection([
        ('venue', 'Venue & Facilities'),
        ('trainer', 'Trainer Fees / Honorarium'),
        ('materials', 'Training Materials & Printing'),
        ('accommodation', 'Accommodation & Travel'),
        ('per_diem', 'Per-Diem Allowance'),
        ('other', 'Other Incidentals'),
    ], string='Cost Category', required=True, default='venue')
    currency_id = fields.Many2one('res.currency', related='budget_id.currency_id')
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('committed', 'Committed'),
        ('paid', 'Paid'),
    ], string='Status', default='planned', required=True)

class EdsCost(models.Model):
    _name = 'eds.cost'
    _description = 'EDS Session Actual Cost Entry'
    _inherit = ['mail.thread']

    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade')
    budget_line_id = fields.Many2one('eds.budget.line', string='Budget Line')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Actual Cost Amount', currency_field='currency_id', required=True)
    payment_state = fields.Selection([
        ('draft', 'Draft'),
        ('committed', 'Committed'),
        ('paid', 'Paid & Reconciled'),
    ], string='Payment State', default='draft', required=True, tracking=True)
    finance_reference = fields.Char(string='Finance Reference / Payment Voucher No.', tracking=True)
    notes = fields.Text(string='Notes / Receipt Details')

class EdsLearningPartner(models.Model):
    _name = 'eds.learning.partner'
    _description = 'EDS Strategic Learning Partnership & MoU'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Partnership Name / Ref', required=True, copy=False, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='External Organization / Institution', required=True, tracking=True)
    proposal_type = fields.Selection([
        ('inbound', 'Inbound Provider Proposal'),
        ('ppdd_initiated', 'PPDD Initiated Strategic Request'),
    ], string='Proposal Type', default='inbound', required=True)
    screening_score = fields.Float(string='Screening Score (%)', required=True, tracking=True, help="Minimum 70% threshold per FREDS069.")
    is_eligible = fields.Boolean(string='Meets 70% Threshold', compute='_compute_eligibility', store=True)
    effective_date = fields.Date(string='MoU Effective Date', tracking=True)
    duration_years = fields.Integer(string='MoU Duration (Years)', default=2, help="Typically 2-3 years per FREDS071.")
    renewal_alert_date = fields.Date(string='Renewal Alert Date', compute='_compute_renewal_date', store=True)
    mou_document = fields.Binary(string='Signed MoU Document', attachment=True)
    mou_filename = fields.Char(string='MoU File Name')
    performance_rating = fields.Float(string='Average Partner Performance Rating (1-5)', default=4.0)
    state = fields.Selection([
        ('received', 'Proposal Received'),
        ('screened', 'Screened (70% Gate)'),
        ('ppdd_endorsement', 'PPDD Endorsed'),
        ('cpco_review', 'CPCO Reviewed'),
        ('ceo_approval', 'CEO Approved'),
        ('agreed', 'MoU Agreed & Signed'),
        ('active', 'Active Partnership'),
        ('expired', 'Expired'),
    ], string='Status', default='received', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.learning.partner') or _('New')
        return super(EdsLearningPartner, self).create(vals_list)

    @api.depends('screening_score')
    def _compute_eligibility(self):
        for rec in self:
            rec.is_eligible = rec.screening_score >= 70.0

    @api.depends('effective_date', 'duration_years')
    def _compute_renewal_date(self):
        for rec in self:
            if rec.effective_date and rec.duration_years:
                end_date = rec.effective_date + timedelta(days=365 * rec.duration_years)
                rec.renewal_alert_date = end_date - timedelta(days=60) # alert 60 days before expiration
            else:
                rec.renewal_alert_date = False

    def action_screen(self):
        for rec in self:
            if not rec.is_eligible:
                raise ValidationError(_("Partner screening score (%.1f%%) is below the mandatory 70%% threshold.") % rec.screening_score)
            rec.state = 'screened'
            rec.message_post(body=_("Partner proposal screened and passed 70%% gate."))

    def action_ppdd_endorse(self):
        for rec in self:
            rec.state = 'ppdd_endorsement'

    def action_cpco_review(self):
        for rec in self:
            rec.state = 'cpco_review'

    def action_ceo_approve(self):
        for rec in self:
            rec.state = 'ceo_approval'

    def action_sign_mou(self):
        for rec in self:
            if not rec.mou_document:
                raise ValidationError(_("Please attach the signed MoU document before finalizing."))
            rec.state = 'active'
            rec.message_post(body=_("Strategic MoU activated."))
