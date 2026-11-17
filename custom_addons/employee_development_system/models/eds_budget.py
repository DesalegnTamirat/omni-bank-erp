# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from datetime import timedelta

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import notify_action

class EdsBudget(models.Model):
    _name = 'eds.budget'
    _description = 'EDS Annual L&D Budget Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Budget Reference', required=True, copy=False, default=lambda self: _('New'))
    fiscal_year = fields.Char(string='Fiscal Year', required=True, index=True, tracking=True, default='2025/2026')
    category = fields.Selection([
        ('internal', 'Internal Classroom Training'),
        ('local_external', 'Local External Training'),
        ('international', 'International Training'),
        ('sponsorship', 'Certification Sponsorship'),
        ('education_assistance', 'Staff Education Assistance'),
        ('bod', "BoD's Team (Executive/Governance)"),
        ('summit', 'Annual Summit & Strategic Conferences'),
        ('below_mlm', 'All Staff Below MLM'),
        ('in_house_class', 'Local In-house (Classroom)'),
        ('in_house_elearning', 'Local In-house E-Learning / Virtual'),
        ('bank_level', 'Bank Level Programs'),
    ], string='Budget Category', required=True, tracking=True, default='internal')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: currency_for_delivery(self.env, 'internal'))
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, index=True)
    allocated = fields.Monetary(string='Approved Budget', currency_field='currency_id', required=True, tracking=True)

    # Quarterly Breakdown Structure (aligned with Budget_Year_Plan template)
    q1_allocated = fields.Monetary(string='Q1 (Jul–Sep)', currency_field='currency_id', tracking=True)
    q2_allocated = fields.Monetary(string='Q2 (Oct–Dec)', currency_field='currency_id', tracking=True)
    q3_allocated = fields.Monetary(string='Q3 (Jan–Mar)', currency_field='currency_id', tracking=True)
    q4_allocated = fields.Monetary(string='Q4 (Apr–Jun)', currency_field='currency_id', tracking=True)
    unallocated = fields.Monetary(string='Q1-Q4 / TBD (Unallocated)', currency_field='currency_id', tracking=True)
    total_estimated = fields.Monetary(
        string='Total Estimated Budget', currency_field='currency_id',
        compute='_compute_quarterly_totals', store=True)
    budget_variance = fields.Monetary(
        string='Variance (Approved − Estimated)', currency_field='currency_id',
        compute='_compute_quarterly_totals', store=True)

    committed = fields.Monetary(string='Committed Amount', compute='_compute_amounts', currency_field='currency_id', store=True)
    spent = fields.Monetary(string='Spent Amount', compute='_compute_amounts', currency_field='currency_id', store=True)
    remaining = fields.Monetary(string='Remaining Balance', compute='_compute_amounts', currency_field='currency_id', store=True)
    utilization_pct = fields.Float(string='Utilization (%)', compute='_compute_amounts', store=True)
    line_ids = fields.One2many('eds.budget.line', 'budget_id', string='Budget Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Status', default='draft', required=True, index=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('state', 'draft') != 'draft':
                raise AccessError(_('Budgets must start as drafts.'))
            category = vals.get('category', 'internal')
            if category in ('internal', 'local_external', 'international', 'in_house_class', 'in_house_elearning'):
                method = 'international' if category == 'international' else 'internal'
                if vals.get('currency_id'):
                    validate_delivery_currency(self.env, method, vals['currency_id'])
                else:
                    vals['currency_id'] = currency_for_delivery(self.env, method).id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.budget') or _('New')
        return super(EdsBudget, self).create(vals_list)

    @api.onchange('category')
    def _onchange_category_currency(self):
        if self.category in ('internal', 'local_external', 'in_house_class', 'in_house_elearning'):
            self.currency_id = currency_for_delivery(self.env, 'internal')
        elif self.category == 'international' and (not self.currency_id or self.currency_id.name == 'ETB'):
            self.currency_id = currency_for_delivery(self.env, 'international')

    def write(self, vals):
        vals = dict(vals)
        if not self.env.su:
            if 'state' in vals:
                raise AccessError(_('Use budget approval actions to change status.'))
            budget_fields = {
                'fiscal_year', 'category', 'currency_id', 'company_id', 'allocated',
                'q1_allocated', 'q2_allocated', 'q3_allocated', 'q4_allocated',
                'unallocated', 'line_ids',
            }
            if budget_fields & vals.keys() and any(rec.state != 'draft' for rec in self):
                raise UserError(_('An approved budget cannot be changed.'))
        if 'category' in vals and 'currency_id' not in vals and vals['category'] in (
                'internal', 'local_external', 'international', 'in_house_class', 'in_house_elearning'):
            vals['currency_id'] = currency_for_delivery(self.env, vals['category']).id
        if {'category', 'currency_id'} & vals.keys():
            for rec in self:
                category = vals.get('category', rec.category)
                if category in ('internal', 'local_external', 'international', 'in_house_class', 'in_house_elearning'):
                    validate_delivery_currency(self.env, category,
                                               vals.get('currency_id', rec.currency_id.id))
        return super().write(vals)

    def _workflow_write(self, vals):
        return super(EdsBudget, self).write(vals)

    @api.depends('q1_allocated', 'q2_allocated', 'q3_allocated', 'q4_allocated', 'unallocated', 'allocated')
    def _compute_quarterly_totals(self):
        for rec in self:
            rec.total_estimated = (
                (rec.q1_allocated or 0.0) +
                (rec.q2_allocated or 0.0) +
                (rec.q3_allocated or 0.0) +
                (rec.q4_allocated or 0.0) +
                (rec.unallocated or 0.0)
            )
            rec.budget_variance = rec.allocated - rec.total_estimated

    @api.depends('allocated', 'line_ids.amount', 'line_ids.status')
    def _compute_amounts(self):
        for rec in self:
            committed = sum(rec.line_ids.filtered(lambda l: l.status in ['committed', 'paid']).mapped('amount'))
            spent = sum(rec.line_ids.filtered(lambda l: l.status == 'paid').mapped('amount'))
            rec.committed = committed
            rec.spent = spent
            rec.remaining = rec.allocated - committed
            rec.utilization_pct = (spent / rec.allocated * 100.0) if rec.allocated > 0 else 0.0

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_approve(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'draft':
                raise UserError(_('Only draft budgets can be approved.'))
            rec._workflow_write({'state': 'approved'})
            rec.message_post(body=_("Annual L&D budget %s approved.") % rec.name)
            notify_action(rec, rec.create_uid, _('L&D budget approved'),
                          _('Budget %s for %s is approved.') % (rec.name, rec.fiscal_year),
                          action_required=False)

    def action_lock(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'approved':
                raise UserError(_('Only approved budgets can be locked.'))
            rec._workflow_write({'state': 'locked'})
            rec.message_post(body=_("Annual L&D budget %s locked.") % rec.name)

class EdsBudgetLine(models.Model):
    _name = 'eds.budget.line'
    _description = 'EDS Budget Line Item'
    _order = 'create_date desc, id desc'

    budget_id = fields.Many2one('eds.budget', string='Parent Budget', ondelete='cascade', required=True)
    course_id = fields.Many2one('eds.course', string='Program / Course')
    session_id = fields.Many2one('eds.session', string='Training Session')
    quarter = fields.Selection([
        ('q1', 'Q1 (Jul–Sep)'),
        ('q2', 'Q2 (Oct–Dec)'),
        ('q3', 'Q3 (Jan–Mar)'),
        ('q4', 'Q4 (Apr–Jun)'),
        ('unallocated', 'Q1–Q4 / TBD (Unallocated)'),
    ], string='Quarter', default='q1')
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

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                budget = self.env['eds.budget'].browse(vals.get('budget_id'))
                if budget.state != 'draft':
                    raise UserError(_('Add budget lines before budget approval.'))
                if vals.get('status', 'planned') != 'planned':
                    raise AccessError(_('Budget lines must start as planned.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if {'budget_id', 'course_id', 'session_id', 'quarter', 'cost_type', 'amount'} & vals.keys() \
                    and any(line.budget_id.state != 'draft' for line in self):
                raise UserError(_('Approved budget allocations cannot be edited.'))
            if vals.get('status') == 'paid' and not self.env.user.has_group(
                    'employee_development_system.group_eds_manager'):
                raise AccessError(_('Only L&D management may mark a budget line paid.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(line.budget_id.state != 'draft' for line in self):
            raise UserError(_('Approved budget lines cannot be removed.'))
        return super().unlink()

class EdsCost(models.Model):
    _name = 'eds.cost'
    _description = 'EDS Session Actual Cost Entry'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    session_id = fields.Many2one('eds.session', string='Training Session', required=True,
                                 ondelete='cascade', index=True)
    budget_line_id = fields.Many2one('eds.budget.line', string='Budget Line')
    delivery_method = fields.Selection(related='session_id.delivery_method', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: currency_for_delivery(self.env, 'internal'))
    amount = fields.Monetary(string='Actual Cost Amount', currency_field='currency_id', required=True)
    payment_state = fields.Selection([
        ('draft', 'Draft'),
        ('committed', 'Committed'),
        ('paid', 'Paid & Reconciled'),
    ], string='Payment State', default='draft', required=True, tracking=True)
    payment_date = fields.Date(string='Payment Date', index=True,
                               help='Date used to convert a paid foreign-currency cost into the reporting currency.')
    finance_reference = fields.Char(string='Finance Reference / Payment Voucher No.', tracking=True)
    notes = fields.Text(string='Notes / Receipt Details')

    @api.onchange('session_id')
    def _onchange_session_currency(self):
        if self.session_id and (
                self.session_id.delivery_method != 'international'
                or not self.currency_id or self.currency_id.name == 'ETB'):
            self.currency_id = currency_for_delivery(self.env, self.session_id.delivery_method)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('payment_state', 'draft') != 'draft':
                raise AccessError(_('Actual costs must start as drafts.'))
            if vals.get('session_id'):
                method = self.env['eds.session'].browse(vals['session_id']).delivery_method
                if vals.get('currency_id'):
                    validate_delivery_currency(self.env, method, vals['currency_id'])
                else:
                    vals['currency_id'] = currency_for_delivery(self.env, method).id
            if vals.get('payment_state') == 'paid' and not vals.get('payment_date'):
                vals['payment_date'] = fields.Date.context_today(self)
        return super().create(vals_list)

    def write(self, vals):
        if (not self.env.su and any(rec.payment_state == 'paid' for rec in self)
                and {'session_id', 'budget_line_id', 'currency_id', 'amount',
                     'payment_state', 'payment_date', 'finance_reference'} & vals.keys()):
            raise UserError(_('A paid cost is immutable; record a separate adjustment.'))
        if not self.env.su and vals.get('payment_state') == 'paid':
            if not self.env.user.has_group('employee_development_system.group_eds_manager'):
                raise AccessError(_('Only L&D management may reconcile a cost as paid.'))
            if not (vals.get('finance_reference') or all(self.mapped('finance_reference'))):
                raise ValidationError(_('Enter a finance reference before marking a cost paid.'))
        if not self.env.su and 'payment_state' in vals and any(
                rec.payment_state == 'paid' for rec in self):
            raise UserError(_('A paid cost cannot return to another payment state.'))
        if {'session_id', 'currency_id'} & vals.keys():
            for rec in self:
                session = self.env['eds.session'].browse(vals['session_id']) if vals.get('session_id') else rec.session_id
                validate_delivery_currency(self.env, session.delivery_method,
                                           vals.get('currency_id', rec.currency_id.id))
        if vals.get('payment_state') == 'paid' and not vals.get('payment_date'):
            vals = dict(vals, payment_date=fields.Date.context_today(self))
        return super().write(vals)

class EdsLearningPartner(models.Model):
    _name = 'eds.learning.partner'
    _description = 'EDS Strategic Learning Partnership & MoU'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Partnership Name / Ref', required=True, copy=False, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='External Organization / Institution', required=True, tracking=True)
    proposal_type = fields.Selection([
        ('inbound', 'Inbound Provider Proposal'),
        ('ppdd_initiated', 'PPDD Initiated Strategic Request'),
    ], string='Proposal Type', default='inbound', required=True)
    screening_score = fields.Float(string='Screening Score (%)', required=True, tracking=True, help="Minimum 70% threshold per .")
    is_eligible = fields.Boolean(string='Meets 70% Threshold', compute='_compute_eligibility', store=True)
    effective_date = fields.Date(string='MoU Effective Date', tracking=True)
    duration_years = fields.Integer(string='MoU Duration (Years)', default=2, help="Typically 2-3 years per .")
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
            if not self.env.su and vals.get('state', 'received') != 'received':
                raise AccessError(_('Partnerships must start as received proposals.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.learning.partner') or _('New')
        return super(EdsLearningPartner, self).create(vals_list)

    def write(self, vals):
        if not self.env.su and 'state' in vals:
            raise AccessError(_('Use partnership approval actions to change status.'))
        return super().write(vals)

    def _workflow_write(self, vals):
        return super(EdsLearningPartner, self).write(vals)

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

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_screen(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'received':
                raise UserError(_('Only received proposals can be screened.'))
            if not rec.is_eligible:
                raise ValidationError(_("Partner screening score (%.1f%%) is below the mandatory 70%% threshold.") % rec.screening_score)
            rec._workflow_write({'state': 'screened'})
            rec.message_post(body=_("Partner proposal screened and passed 70%% gate."))

    def action_ppdd_endorse(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'screened':
                raise UserError(_('Only screened partner proposals can be endorsed by PPDD.'))
            rec._workflow_write({'state': 'ppdd_endorsement'})

    def action_cpco_review(self):
        for rec in self:
            rec._require_group('group_eds_cpco')
            if rec.state != 'ppdd_endorsement':
                raise UserError(_('Only PPDD-endorsed proposals can be reviewed by CPCO.'))
            rec._workflow_write({'state': 'cpco_review'})

    def action_ceo_approve(self):
        for rec in self:
            rec._require_group('group_eds_chief')
            if rec.state != 'cpco_review':
                raise UserError(_('Only CPCO-reviewed proposals can be approved by CEO.'))
            rec._workflow_write({'state': 'ceo_approval'})

    def action_sign_mou(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'ceo_approval':
                raise UserError(_('Only CEO-approved proposals can be signed and activated.'))
            if not rec.mou_document:
                raise ValidationError(_("Please attach the signed MoU document before finalizing."))
            rec._workflow_write({'state': 'active'})
            rec.message_post(body=_("Strategic MoU signed and activated."))
