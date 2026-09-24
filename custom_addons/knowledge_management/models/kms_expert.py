# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class KmsExpert(models.Model):
    """
    Expert & Skill Directory (FR-KMS-027).
    Searchable bank-wide directory of Subject Matter Experts (SMEs).
    Connects employees to their recognized functional competencies (competency.competency)
    and tacit knowledge domain expertise.
    """
    _name = 'kms.expert'
    _description = 'Subject Matter Expert'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'endorsement_count desc, name'

    name = fields.Char(string='Expert Profile Name', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', string='Bank Employee', required=True, tracking=True, index=True)
    job_id = fields.Many2one('hr.job', related='employee_id.job_id', string='Job Position', readonly=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', readonly=True)

    # Competency Linkage (from existing competency_management module)
    competency_ids = fields.Many2many(
        'competency.competency',
        'kms_expert_competency_rel',
        'expert_id',
        'competency_id',
        string='Recognized Competencies'
    )

    primary_domain = fields.Selection([
        ('credit', 'Credit Risk & Lending'),
        ('trade_finance', 'Trade Services & Foreign Operations'),
        ('retail', 'Retail & Branch Operations'),
        ('treasury', 'Treasury & International Banking'),
        ('digital', 'Digital Banking, Mobile & FinTech'),
        ('it_security', 'IT Infrastructure & Cyber Resilience'),
        ('compliance', 'AML/CFT & Regulatory Compliance'),
        ('finance', 'Financial Control, Tax & Accounting'),
        ('hr', 'People & Organizational Development'),
        ('audit', 'Internal Audit & Risk Assurance'),
    ], string='Primary Domain of Expertise', required=True, tracking=True)

    expertise_summary = fields.Html(string='Specialized Knowledge & Experience Profile', required=True)
    certifications_held = fields.Text(string='Professional Certifications & Accreditations')
    years_experience = fields.Float(string='Years of Domain Experience')

    availability_status = fields.Selection([
        ('available', 'Available for Consultations & Mentoring'),
        ('busy', 'Limited Availability'),
        ('unavailable', 'Currently Unavailable'),
    ], string='Advisory Availability', default='available', tracking=True)

    preferred_contact_channel = fields.Selection([
        ('email', 'Corporate Email'),
        ('teams', 'MS Teams / Chat'),
        ('in_person', 'In-Person / Office Hours'),
    ], string='Preferred Contact Channel', default='email')

    # Peer Endorsements
    endorsement_count = fields.Integer(string='Endorsements', default=0, readonly=True)
    endorsement_ids = fields.One2many('kms.expert.endorsement', 'expert_id', string='Endorsements Received')

    active = fields.Boolean(default=True)

    _employee_unique = models.Constraint(
        'UNIQUE(employee_id)',
        'An expert directory profile already exists for this employee!'
    )

    @api.depends('employee_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.employee_id.name if rec.employee_id else _('New Expert Profile')

    def action_endorse(self):
        endorser = self.env.user.employee_id
        if not endorser:
            return
        for rec in self:
            existing = self.env['kms.expert.endorsement'].search([
                ('expert_id', '=', rec.id),
                ('endorser_id', '=', endorser.id)
            ], limit=1)
            if not existing and endorser.id != rec.employee_id.id:
                self.env['kms.expert.endorsement'].create({
                    'expert_id': rec.id,
                    'endorser_id': endorser.id,
                    'comment': _('Endorsed as SME in %s') % dict(self._fields['primary_domain'].selection).get(rec.primary_domain, ''),
                })
                rec.sudo().write({'endorsement_count': rec.endorsement_count + 1})


class KmsExpertEndorsement(models.Model):
    _name = 'kms.expert.endorsement'
    _description = 'Expert Endorsement'
    _order = 'create_date desc'

    expert_id = fields.Many2one('kms.expert', string='Expert', required=True, ondelete='cascade')
    endorser_id = fields.Many2one('hr.employee', string='Endorsed By', required=True)
    comment = fields.Char(string='Endorsement Note')
    create_date = fields.Datetime(string='Date', readonly=True)
