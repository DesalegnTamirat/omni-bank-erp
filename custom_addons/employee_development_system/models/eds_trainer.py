# -*- coding: utf-8 -*-
import base64
import binascii
from datetime import date, timedelta
from pathlib import PurePath

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_TOT_CERT_MAX_BYTES = 10 * 1024 * 1024
_TOT_CERT_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}


class EdsTrainer(models.Model):
    """Internal / external trainer register.

    A centralized internal trainer pool: profiles, competencies, ToT certification
    status, periodic review cycles (default every 2 years), participant feedback,
    quarterly performance reviews and availability (used by conflict checks).
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
        help='Set for internal trainers.')
    external_partner_id = fields.Many2one(
        'res.partner', string='External Trainer (Partner)',
        help='EDS creates this contact when an external trainer is registered.')
    external_partner_managed = fields.Boolean(default=False, copy=False)
    external_provider_id = fields.Many2one(
        'eds.external.provider', string='External Provider',
        help='The registered provider this external trainer belongs to.')
    job_title = fields.Char(string='Job Title / Specialization')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    employee_job_position = fields.Char(
        string='Job Position', compute='_compute_employee_contact')
    employee_phone = fields.Char(
        string='Phone', compute='_compute_employee_contact')
    employee_email = fields.Char(
        string='Email', compute='_compute_employee_contact')

    # Standard Profile Fields
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
    session_ids = fields.Many2many(
        'eds.session', 'eds_session_trainer_rel', 'trainer_id', 'session_id',
        string='EDS Session Assignments', readonly=True)

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
        """Prints official Form Trainer Profile PDF."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_trainer_profile').report_action(self)
    competency_ids = fields.Many2many(
        'competency.competency', string='Competencies',
        help='Competencies the trainer is qualified to deliver .')
    tot_certified = fields.Boolean(
        string='ToT Certified', tracking=True,
        help='Training-of-Trainers certification status.')
    tot_certificate_ids = fields.One2many(
        'eds.trainer.certification', 'trainer_id', string='ToT Certificates')
    review_cycle_months = fields.Integer(
        string='Review Cycle (Months)', default=24, tracking=True,
        help='Periodic review cycle - default every 2 years.')
    last_review_date = fields.Date(string='Last Review Date', tracking=True)
    next_review_date = fields.Date(
        string='Next Review Date', compute='_compute_next_review', store=True)
    review_overdue = fields.Boolean(
        string='Review Overdue', compute='_compute_review_overdue',
        search='_search_review_overdue')
    availability_ids = fields.One2many(
        'eds.trainer.availability', 'trainer_id', string='Availability',
        help='Trainer availability slots used for session conflict checks .')
    quarterly_review_ids = fields.One2many(
        'eds.trainer.quarterly.review', 'trainer_id', string='Quarterly Reviews')
    feedback_ids = fields.One2many(
        'eds.trainer.feedback', 'trainer_id', string='Participant Feedback')
    daily_feedback_ids = fields.Many2many(
        'eds.feedback', compute='_compute_daily_feedback_ids',
        string='Daily Session Feedback', readonly=True)
    avg_rating = fields.Float(
        string='Average Rating', compute='_compute_avg_rating', store=True,
        digits=(3, 2),
        help='Computed from Level-1/Level-3 participant feedback and quarterly '
             'reviews.')
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
    _check_review_cycle_positive = models.Constraint(
        'CHECK(review_cycle_months > 0)', 'Review cycle must be at least one month.')

    @api.depends('employee_id.job_position', 'employee_id.job_title',
                 'employee_id.mobile_phone', 'employee_id.work_phone',
                 'employee_id.work_email')
    def _compute_employee_contact(self):
        for rec in self:
            employee = rec.employee_id
            rec.employee_job_position = (
                employee.job_position.name or employee.job_title or '') if employee else ''
            rec.employee_phone = (
                employee.mobile_phone or employee.work_phone or '') if employee else ''
            rec.employee_email = (employee.work_email or '') if employee else ''

    def _compute_daily_feedback_ids(self):
        feedback = self.env['eds.feedback'].search([('trainer_id', 'in', self.ids)])
        for rec in self:
            rec.daily_feedback_ids = feedback.filtered(
                lambda row: row.trainer_id == rec and row.session_id in rec.session_ids)

    def _ensure_external_contact(self):
        for rec in self.filtered(lambda trainer: trainer.trainer_type == 'external'
                                 and not trainer.external_partner_id):
            partner_vals = {
                'name': rec.name,
                'email': rec.email or False,
                'phone': rec.phone or False,
                'company_type': 'person',
            }
            partner = self.env['res.partner'].sudo().create(partner_vals)
            rec.with_context(skip_external_partner_sync=True).write({
                'external_partner_id': partner.id,
                'external_partner_managed': True,
            })

    def _grant_employee_trainer_role(self):
        """The trainer role grants a personal session view, not delivery administration."""
        group = self.env.ref('employee_development_system.group_eds_trainer')
        users = self.filtered(
            lambda trainer: trainer.state == 'active' and trainer.trainer_type == 'internal'
            and trainer.employee_id.user_id).mapped('employee_id.user_id')
        for user in users:
            if group not in user.group_ids:
                user.sudo().write({'group_ids': [(4, group.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        trainers = super().create(vals_list)
        trainers._ensure_external_contact()
        trainers._grant_employee_trainer_role()
        return trainers

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('skip_external_partner_sync'):
            if {'name', 'email', 'phone', 'external_provider_id'} & vals.keys():
                for rec in self.filtered(lambda trainer: trainer.trainer_type == 'external'
                                         and trainer.external_partner_managed
                                         and trainer.external_partner_id):
                    partner_vals = {
                        'name': rec.name,
                        'email': rec.email or False,
                        'phone': rec.phone or False,
                    }
                    rec.external_partner_id.sudo().write(partner_vals)
        if {'employee_id', 'trainer_type', 'state'} & vals.keys():
            self._grant_employee_trainer_role()
        return result

    @api.depends('last_review_date', 'review_cycle_months', 'create_date')
    def _compute_next_review(self):
        for rec in self:
            base = rec.last_review_date or (rec.create_date.date() if rec.create_date else fields.Date.today())
            rec.next_review_date = base + relativedelta(months=max(rec.review_cycle_months, 1))

    @api.depends('next_review_date')
    def _compute_review_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.review_overdue = bool(rec.next_review_date and rec.next_review_date < today)

    @api.model
    def _search_review_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_('Review Overdue only supports true/false filtering.'))
        overdue = bool(value) if operator == '=' else not bool(value)
        return [('next_review_date', '<' if overdue else '>=', fields.Date.today())]

    @api.depends('feedback_ids.score_pct', 'quarterly_review_ids.rating')
    def _compute_avg_rating(self):
        for rec in self:
            ratings = [row.score_pct / 20 for row in rec.feedback_ids if row.score_pct]
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

    @api.onchange('external_provider_id')
    def _onchange_external_provider_id(self):
        if self.trainer_type == 'external' and self.external_provider_id:
            self.organization_name = self.external_provider_id.name

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
        """Record today's review date for an authorized internal or external trainer."""
        allowed_groups = (
            'employee_development_system.group_eds_officer',
            'employee_development_system.group_eds_manager',
            'employee_development_system.group_eds_admin',
        )
        if not any(self.env.user.has_group(group) for group in allowed_groups):
            raise AccessError(_('Only L&D staff can mark a trainer reviewed.'))
        today = fields.Date.context_today(self)
        for rec in self:
            rec.write({'last_review_date': today})
            rec.activity_ids.filtered(
                lambda activity: (activity.summary or '').startswith('Review trainer profile: ')
            ).sudo().unlink()
            rec.message_post(body=_('Periodic review completed for trainer %s on %s.') % (
                rec.name, today))

    @api.model
    def _get_qualified_trainers(self, competency_ids=None, date_start=None, date_end=None):
        """Helper for : trainers matching competencies and available in a period.

        Returns a recordset of `eds.trainer` whose competency set intersects the
        requested competencies and who have no blocking availability record in the
        requested window.
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
    """Training-of-Trainers (ToT) certification record."""
    _name = 'eds.trainer.certification'
    _description = 'Trainer ToT Certification'
    _order = 'issued_date desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    name = fields.Char(string='Certification Name', required=True)
    issued_by = fields.Char(string='Issued By')
    issued_date = fields.Date(string='Issued Date', required=True)
    expiry_date = fields.Date(string='Expiry Date')
    document = fields.Binary(string='Certificate File (maximum 10 MB)', attachment=True)
    filename = fields.Char(string='Filename')
    status = fields.Selection([
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Status', compute='_compute_status')

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

    @api.model
    def _check_document(self, document, filename):
        if not document:
            return
        extension = PurePath(filename or '').suffix.lower()
        if extension not in _TOT_CERT_EXTENSIONS:
            raise ValidationError(_(
                'ToT certificates must be PDF, PNG, or JPEG files.'))
        try:
            encoded = document.encode('ascii') if isinstance(document, str) else document
            if len(encoded) > 4 * ((_TOT_CERT_MAX_BYTES + 2) // 3) + 4:
                raise ValidationError(_('ToT certificate files cannot exceed 10 MB.'))
            size = len(base64.b64decode(encoded, validate=True))
        except (UnicodeEncodeError, TypeError, binascii.Error, ValueError) as exc:
            raise ValidationError(_('The ToT certificate is not a valid file.')) from exc
        if size > _TOT_CERT_MAX_BYTES:
            raise ValidationError(_('ToT certificate files cannot exceed 10 MB.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_document(vals.get('document'), vals.get('filename'))
        return super().create(vals_list)

    def write(self, vals):
        if {'document', 'filename'} & vals.keys():
            for rec in self:
                document = vals.get('document', rec.document)
                if document:
                    self._check_document(document, vals.get('filename', rec.filename))
        return super().write(vals)

    def action_preview_document(self):
        self.ensure_one()
        self.check_access('read')
        if not self.document:
            raise UserError(_('Attach and save a certificate file first.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/eds.trainer.certification/{self.id}/document?download=false',
            'target': 'new',
        }

    def action_download_document(self):
        self.ensure_one()
        self.check_access('read')
        if not self.document:
            raise UserError(_('Attach and save a certificate file first.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/eds.trainer.certification/{self.id}/document?download=true',
            'target': 'new',
        }


class EdsTrainerAvailability(models.Model):
    """Trainer availability slot (; consumed by conflict checks)."""
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
    """Quarterly performance review of a trainer."""
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
    """Trainer-linked participant feedback, including employee Level-1 responses."""
    _name = 'eds.trainer.feedback'
    _description = 'Trainer Participant Feedback'
    _order = 'date desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    session_id = fields.Many2one('eds.session', string='Delivered Session', required=True,
                                 ondelete='cascade', index=True)
    eligible_session_ids = fields.Many2many(
        'eds.session', compute='_compute_selection_domains')
    eligible_participant_ids = fields.Many2many(
        'hr.employee', compute='_compute_selection_domains')
    date = fields.Date(string='Date', default=fields.Date.context_today)
    level = fields.Selection([
        ('level_1', 'Level 1 - Reaction'),
        ('level_3', 'Level 3 - Behaviour'),
    ], string='Evaluation Level', default='level_1', required=True)
    participant_id = fields.Many2one('hr.employee', string='Participant')
    source_level1_id = fields.Many2one(
        'eds.evaluation.level1', string='Employee Questionnaire',
        ondelete='cascade', readonly=True, index=True, copy=False)
    source_kind = fields.Selection([
        ('manual', 'Trainer Feedback'),
        ('level1', 'Session Level-1 Questionnaire'),
    ], string='Source', default='manual', required=True, readonly=True)
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Rating')
    score_pct = fields.Float(string='Trainer Score (%)', compute='_compute_score_pct', store=True)
    comment = fields.Text(string='Comment')

    _unique_level1_source = models.Constraint(
        'UNIQUE(trainer_id, source_level1_id)',
        'This employee questionnaire is already shown for this trainer.')
    _unique_participant_delivery = models.Constraint(
        'UNIQUE(trainer_id, session_id, participant_id, level)',
        'Feedback for this trainer, session, participant and level already exists.')

    @api.depends('trainer_id', 'session_id', 'session_id.enrollment_ids.state')
    def _compute_selection_domains(self):
        for rec in self:
            rec.eligible_session_ids = rec.trainer_id.session_ids
            rec.eligible_participant_ids = rec.session_id.enrollment_ids.filtered(
                lambda row: row.state in ('enrolled', 'completed')
            ).mapped('employee_id')

    @api.depends('rating', 'source_level1_id.score_trainer')
    def _compute_score_pct(self):
        for rec in self:
            rec.score_pct = (rec.source_level1_id.score_trainer if rec.source_level1_id
                             else int(rec.rating or 0) * 20)

    @api.constrains('trainer_id', 'session_id', 'participant_id', 'level', 'source_level1_id', 'rating')
    def _check_feedback_belongs_to_delivery(self):
        for rec in self:
            if rec.trainer_id not in rec.session_id.trainer_ids:
                raise ValidationError(_(
                    'Choose a session that this trainer was assigned to deliver.'))
            if rec.source_level1_id:
                source = rec.source_level1_id
                if source.session_id != rec.session_id or (
                        rec.participant_id and source.employee_id != rec.participant_id):
                    raise ValidationError(_('The employee questionnaire belongs to another session or participant.'))
            elif not rec.participant_id or not rec.rating:
                raise ValidationError(_('Select a participant and rating for manual trainer feedback.'))
            if (not rec.source_level1_id and rec.level == 'level_1' and
                    self.env['eds.evaluation.level1'].sudo().search_count([
                        ('session_id', '=', rec.session_id.id),
                        ('employee_id', '=', rec.participant_id.id),
                        ('state', 'in', ('submitted', 'consolidated')),
                    ])):
                raise ValidationError(_(
                    'This participant already submitted a Level-1 questionnaire for this session.'))
            if rec.participant_id and rec.participant_id not in rec.eligible_participant_ids:
                raise ValidationError(_(
                    'The participant must be enrolled in or have completed this session.'))
            if rec.participant_id and self.search_count([
                ('trainer_id', '=', rec.trainer_id.id),
                ('session_id', '=', rec.session_id.id),
                ('participant_id', '=', rec.participant_id.id),
                ('level', '=', rec.level),
                ('id', '!=', rec.id),
            ]):
                raise ValidationError(_(
                    'Feedback for this trainer, session, participant and level already exists.'))

    @api.model
    def sync_from_level1(self, evaluations):
        """Show submitted session trainer scores without duplicate manual entries."""
        for evaluation in evaluations.sudo().filtered(
                lambda rec: rec.state in ('submitted', 'consolidated')):
            session = evaluation.session_id
            if not session:
                continue
            self.sudo().search([
                ('source_level1_id', '=', evaluation.id),
                ('trainer_id', 'not in', session.trainer_ids.ids),
            ]).unlink()
            if not session.trainer_ids:
                continue
            enrolled = evaluation.employee_id in session.enrollment_ids.filtered(
                lambda row: row.state in ('enrolled', 'completed')).mapped('employee_id')
            if not enrolled:
                continue
            for trainer in session.trainer_ids:
                existing = self.sudo().search([
                    ('trainer_id', '=', trainer.id),
                    ('source_level1_id', '=', evaluation.id),
                ], limit=1)
                if not existing:
                    existing = self.sudo().search([
                        ('trainer_id', '=', trainer.id),
                        ('session_id', '=', session.id),
                        ('participant_id', '=', evaluation.employee_id.id),
                        ('level', '=', 'level_1'),
                    ], limit=1)
                values = {
                    'trainer_id': trainer.id,
                    'session_id': session.id,
                    'participant_id': False if evaluation.is_anonymous else evaluation.employee_id.id,
                    'date': evaluation.submitted_date or fields.Date.today(),
                    'level': 'level_1',
                    'source_kind': 'level1',
                    'source_level1_id': evaluation.id,
                    'rating': False,
                }
                if existing:
                    existing.write(values)
                else:
                    self.sudo().create(values)


class EdsTrainerEducation(models.Model):
    """Education & Professional Certifications."""
    _name = 'eds.trainer.education'
    _description = 'Trainer Education & Certification'
    _order = 'year_obtained desc, id desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    degree_title = fields.Char(string='Degree / Qualification / Certification', required=True)
    field_of_study = fields.Char(string='Field of Study / Specialization')
    institution_name = fields.Char(string='Institution / Awarding Body')
    year_obtained = fields.Char(string='Year Obtained')
    # Backward compatibility aliases
    qualification = fields.Char(string='Legacy Qualification Alias', related='degree_title', readonly=False)
    institution = fields.Char(string='Legacy Institution Alias', related='institution_name', readonly=False)
    year = fields.Char(string='Legacy Year Alias', related='year_obtained', readonly=False)


class EdsTrainerExpertise(models.Model):
    """Certified Topics & Areas of Expertise."""
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
    topic = fields.Char(string='Legacy Topic Alias', related='course_topics', readonly=False)
    level = fields.Selection(string='Legacy Level Alias', related='target_level', readonly=False)
    language = fields.Char(string='Language', default='English / Amharic')


class EdsTrainerDeliveryHistory(models.Model):
    """Previous Training Delivered & Historical Ratings."""
    _name = 'eds.trainer.delivery.history'
    _description = 'Trainer Previous Delivery History'
    _order = 'delivery_year desc, id desc'

    trainer_id = fields.Many2one('eds.trainer', string='Trainer', required=True, ondelete='cascade')
    program_title = fields.Char(string='Program Title', required=True)
    client_organization = fields.Char(string='Client / Bank Organization')
    delivery_year = fields.Char(string='Delivery Year')
    participant_count = fields.Integer(string='Participants')
    participant_rating = fields.Float(string='Avg. Rating', default=4.5)
    # Backward compatibility aliases
    program_name = fields.Char(string='Legacy Program Alias', related='program_title', readonly=False)
    client_year = fields.Char(string='Legacy Client Alias', related='client_organization', readonly=False)
    participants_count = fields.Integer(string='Legacy Participant Count Alias', related='participant_count', readonly=False)
    avg_rating = fields.Float(string='Legacy Rating Alias', related='participant_rating', readonly=False)
