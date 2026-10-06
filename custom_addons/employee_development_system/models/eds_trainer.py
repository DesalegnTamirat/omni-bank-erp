# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsTrainer(models.Model):
    """Internal / external trainer register (, ...016).

    A centralized internal trainer pool: profiles, competencies, ToT certification
    status, periodic review cycles (default every 2 years), participant feedback,
    quarterly performance reviews and availability (used by Task 5 conflict checks).
    """
    _name = 'eds.trainer'
    _description = 'Trainer Profile'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    name = fields.Char(string='Name', required=True, tracking=True)
    trainer_type = fields.Selection([
        ('internal', 'Internal Trainer'),
        ('external', 'External Trainer'),
    ], string='Trainer Type', default='internal', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Internal Employee',
        help='Set for internal trainers ().')
    external_partner_id = fields.Many2one(
        'res.partner', string='External Trainer (Partner)',
        help='Set for external trainers.')
    external_provider_id = fields.Many2one(
        'eds.external.provider', string='External Provider',
        help='The registered provider this external trainer belongs to ().')
    job_title = fields.Char(string='Job Title / Specialization')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')

    # EDS-F-06 Standard Profile Fields
    trainer_id_code = fields.Char(string='Trainer ID / Code')
    organization_name = fields.Char(string='Organization / Firm')
    address = fields.Text(string='Physical Address')
    
    # 2. Education & Certifications
    education_ids = fields.One2many('eds.trainer.education', 'trainer_id', string='Education & Certifications')

    # 3. Banking & Training Experience
    banking_experience_years = fields.Float(string='Total Years in Banking / Finance', default=0.0)
    trainer_experience_years = fields.Float(string='Total Years as a Trainer', default=0.0)
    institutions_worked_with = fields.Text(string='Banks / Institutions Worked With')

    # 4. Certified Topics / Areas of Expertise
    expertise_ids = fields.One2many('eds.trainer.expertise', 'trainer_id', string='Certified Topics & Expertise')

    # 5. Previous Training Delivered & Ratings
    delivery_history_ids = fields.One2many('eds.trainer.delivery.history', 'trainer_id', string='Previous Training Delivered')

    # 6. Fee Structure
    hourly_fee = fields.Monetary(string='Hourly Fee (ETB)', currency_field='currency_id')
    daily_fee = fields.Monetary(string='Daily Fee (ETB)', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    tax_status = fields.Char(string='Currency / Tax Status', default='ETB (VAT Inclusive)')
    fee_validity_period = fields.Char(string='Fee Validity Period', default='Annual / Current Fiscal Year')

    # Declaration & Signatures
    declaration_agreed = fields.Boolean(string='Agreed to Standards & Confidentiality', default=True)
    reviewed_by_officer = fields.Char(string='Reviewed by (L&D Officer)')
    approved_by_tl = fields.Char(string='Approved by (Team Leader, L&D)')

    def action_print_profile(self):
        """Prints official Form EDS-F-06 Trainer Profile PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_trainer_profile').report_action(self)
    competency_ids = fields.Many2many(
        'competency.competency', string='Competencies',
        help='Competencies the trainer is qualified to deliver (Task 5 uses this to '
             'constrain session trainer selection).')
    tot_certified = fields.Boolean(
        string='ToT Certified', tracking=True,
        help='Training-of-Trainers certification status ().')
    tot_certificate_ids = fields.One2many(
        'eds.trainer.certification', 'trainer_id', string='ToT Certificates')
    review_cycle_months = fields.Integer(
        string='Review Cycle (Months)', default=24, tracking=True,
        help='Periodic review cycle - default every 2 years ().')
    last_review_date = fields.Date(string='Last Review Date', tracking=True)
    next_review_date = fields.Date(
        string='Next Review Date', compute='_compute_next_review')
    review_overdue = fields.Boolean(
        string='Review Overdue', compute='_compute_next_review', search=True)
    availability_ids = fields.One2many(
        'eds.trainer.availability', 'trainer_id', string='Availability',
        help='Trainer availability slots used for session conflict checks (Task 5).')
    quarterly_review_ids = fields.One2many(
        'eds.trainer.quarterly.review', 'trainer_id', string='Quarterly Reviews')
    feedback_ids = fields.One2many(
        'eds.trainer.feedback', 'trainer_id', string='Participant Feedback')
    avg_rating = fields.Float(
        string='Average Rating', compute='_compute_avg_rating', store=True,
        digits=(3, 2),
        help='Computed from Level-1/Level-3 participant feedback and quarterly '
             'reviews ().')
    rating_count = fields.Integer(string='Rating Count', compute='_compute_avg_rating', store=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Status', default='active', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _check_internal_external_exclusive = models.Constraint(
        'CHECK(NOT (employee_id IS NOT NULL AND external_partner_id IS NOT NULL))',
        'A trainer cannot be both an internal employee and an external partner!',
    )

    @api.depends('last_review_date', 'review_cycle_months', 'create_date')
    def _compute_next_review(self):
        today = date.today()
        for rec in self:
            base = rec.last_review_date or (rec.create_date.date() if rec.create_date else today)
            rec.next_review_date = base + timedelta(days=rec.review_cycle_months * 30)
            rec.review_overdue = bool(rec.next_review_date and rec.next_review_date < today)

    @api.depends('feedback_ids.rating', 'quarterly_review_ids.rating')
    def _compute_avg_rating(self):
        for rec in self:
            # Selection fields map to their string keys ('1'..'5') - convert to ints
            ratings = [int(r) for r in rec.feedback_ids.mapped('rating') if r]
            ratings += [int(r) for r in rec.quarterly_review_ids.mapped('rating') if r]
            rec.avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
            rec.rating_count = len(ratings)

    @api.onchange('trainer_type')
    def _onchange_trainer_type(self):
        if self.trainer_type == 'internal' and self.employee_id:
            if not self.name or self.name == self.external_partner_id.name:
                self.name = self.employee_id.name
        elif self.trainer_type == 'external' and self.external_partner_id:
            if not self.name:
                self.name = self.external_partner_id.name

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.name = self.employee_id.name
            self.job_title = self.employee_id.job_title
            self.email = self.employee_id.work_email
            self.phone = self.employee_id.mobile_phone or self.employee_id.work_phone

    def action_activate(self):
        for rec in self:
            if rec.state != 'inactive':
                raise UserError(_('Only inactive trainers can be reactivated.'))
            rec.state = 'active'
            rec.message_post(body=_('Trainer %s reactivated.') % rec.name)

    def action_deactivate(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError(_('Only active trainers can be deactivated.'))
            rec.state = 'inactive'
            rec.message_post(body=_('Trainer %s deactivated.') % rec.name)

    def action_mark_reviewed(self):
        """Record a periodic review (2-year cycle by default)."""
        for rec in self:
            rec.last_review_date = date.today()
            rec.next_review_date = date.today() + timedelta(days=rec.review_cycle_months * 30)
            rec.message_post(body=_('Periodic review completed for trainer %s ().') % rec.name)

    @api.model
    def _get_qualified_trainers(self, competency_ids=None, date_start=None, date_end=None):
        """Helper for Task 5: trainers matching competencies and available in a period.

        Returns a recordset of `eds.trainer` whose competency set intersects the
        requested competencies and who have no blocking availability record in the
        requested window (/020).
        """
        domain = [('state', '=', 'active')]
        trainers = self.search(domain)
        if competency_ids:
            comp_ids = [c.id for c in competency_ids] if not isinstance(competency_ids, (list, tuple)) \
                else list(competency_ids)
            trainers = trainers.filtered(lambda t: comp_ids and bool(set(t.competency_ids.ids) & set(comp_ids)))
        if date_start and date_end:
            for t in trainers:
                for slot in t.availability_ids.filtered(lambda a: a.state == 'blocked'):
                    if slot.date_start <= date_end and slot.date_end >= date_start:
                        trainers -= t
                        break
        return trainers


class EdsTrainerCertification(models.Model):
    """Training-of-Trainers (ToT) certification record ()."""
    _name = 'eds.trainer.certification'
    _description = 'Trainer ToT Certification'
    _order = 'issued_date desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    name = fields.Char(string='Certification Name', required=True)
    issued_by = fields.Char(string='Issued By')
    issued_date = fields.Date(string='Issued Date', required=True)
    expiry_date = fields.Date(string='Expiry Date')
    status = fields.Selection([
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Status', compute='_compute_status', store=True)

    @api.depends('expiry_date')
    def _compute_status(self):
        today = date.today()
        for rec in self:
            if not rec.expiry_date:
                rec.status = 'valid'
            elif rec.expiry_date < today:
                rec.status = 'expired'
            elif rec.expiry_date <= today + timedelta(days=90):
                rec.status = 'expiring_soon'
            else:
                rec.status = 'valid'


class EdsTrainerAvailability(models.Model):
    """Trainer availability slot (; consumed by Task 5 conflict checks)."""
    _name = 'eds.trainer.availability'
    _description = 'Trainer Availability'
    _order = 'date_start'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    date_start = fields.Datetime(string='From', required=True)
    date_end = fields.Datetime(string='To', required=True)
    state = fields.Selection([
        ('available', 'Available'),
        ('blocked', 'Blocked'),
    ], string='Type', default='available', required=True)
    note = fields.Text(string='Note')

    _check_date_range_valid = models.Constraint(
        'CHECK(date_end > date_start)',
        'The "To" datetime must be after the "From" datetime!',
    )


class EdsTrainerQuarterlyReview(models.Model):
    """Quarterly performance review of a trainer ()."""
    _name = 'eds.trainer.quarterly.review'
    _description = 'Trainer Quarterly Review'
    _order = 'period desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    period = fields.Char(string='Period (e.g. Q1 2026)', required=True)
    review_date = fields.Date(string='Review Date', default=fields.Date.context_today)
    reviewer_id = fields.Many2one('res.users', string='Reviewed By', default=lambda self: self.env.user)
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Rating', required=True)
    strengths = fields.Text(string='Strengths')
    improvements = fields.Text(string='Areas for Improvement')
    action_plan = fields.Text(string='Action Plan')

    @api.depends('rating')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.period, rec.get_rating_label())

    def get_rating_label(self):
        self.ensure_one()
        return dict(self._fields['rating'].selection).get(self.rating, self.rating)


class EdsTrainerFeedback(models.Model):
    """Participant feedback about a trainer (Level-1 reaction / Level-3 behaviour, )."""
    _name = 'eds.trainer.feedback'
    _description = 'Trainer Participant Feedback'
    _order = 'date desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    date = fields.Date(string='Date', default=fields.Date.context_today)
    level = fields.Selection([
        ('level_1', 'Level 1 - Reaction'),
        ('level_3', 'Level 3 - Behaviour'),
    ], string='Evaluation Level', default='level_1', required=True)
    # session_id is linked to eds.session in Task 5 (session scheduling).
    participant_id = fields.Many2one('hr.employee', string='Participant')
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Rating', required=True)
    comment = fields.Text(string='Comment')


class EdsTrainerEducation(models.Model):
    """Education & Professional Certifications (EDS-F-06)."""
    _name = 'eds.trainer.education'
    _description = 'Trainer Education & Certification'
    _order = 'year_obtained desc, id desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    degree_title = fields.Char(string='Degree / Qualification / Certification', required=True)
    field_of_study = fields.Char(string='Field of Study / Specialization')
    institution_name = fields.Char(string='Institution / Awarding Body')
    year_obtained = fields.Char(string='Year Obtained')
    # Backward compatibility aliases
    qualification = fields.Char(related='degree_title', readonly=False)
    institution = fields.Char(related='institution_name', readonly=False)
    year = fields.Char(related='year_obtained', readonly=False)


class EdsTrainerExpertise(models.Model):
    """Certified Topics & Areas of Expertise (EDS-F-06)."""
    _name = 'eds.trainer.expertise'
    _description = 'Trainer Certified Topics & Expertise'
    _order = 'id'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    subject_domain = fields.Char(string='Subject / Banking Domain')
    course_topics = fields.Char(string='Specific Course Topics', required=True)
    target_level = fields.Selection([
        ('basic', 'Basic / Foundation'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced / Senior'),
        ('executive', 'Executive / Leadership'),
    ], string='Target Participant Level', default='intermediate', required=True)
    years_experience = fields.Float(string='Years of Experience in Domain', default=1.0)
    # Backward compatibility aliases
    topic = fields.Char(related='course_topics', readonly=False)
    level = fields.Selection(related='target_level', readonly=False)
    language = fields.Char(string='Language', default='English / Amharic')


class EdsTrainerDeliveryHistory(models.Model):
    """Previous Training Delivered & Historical Ratings (EDS-F-06)."""
    _name = 'eds.trainer.delivery.history'
    _description = 'Trainer Previous Delivery History'
    _order = 'delivery_year desc, id desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    program_title = fields.Char(string='Program Title', required=True)
    client_organization = fields.Char(string='Client / Bank Organization')
    delivery_year = fields.Char(string='Delivery Year')
    participant_count = fields.Integer(string='Participants')
    participant_rating = fields.Float(string='Avg. Rating (/5)', default=4.5)
    # Backward compatibility aliases
    program_name = fields.Char(related='program_title', readonly=False)
    client_year = fields.Char(related='client_organization', readonly=False)
    participants_count = fields.Integer(related='participant_count', readonly=False)
    avg_rating = fields.Float(related='participant_rating', readonly=False)
