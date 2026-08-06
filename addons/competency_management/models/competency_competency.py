# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyRatingModel(models.Model):
    """Evaluation scale attachable to competencies (FR-CFD-0172)."""
    _name = 'competency.rating.model'
    _description = 'Competency Rating Model'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    max_rating = fields.Integer(
        string='Maximum Rating', default=4,
        help='Highest proficiency/rating value in this scale.')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Rating Model code must be unique!'),
    ]


class CompetencyProficiencyLevel(models.Model):
    """One proficiency level (Basic..Expert) with behavioral indicators (FR-COM-004/005)."""
    _name = 'competency.proficiency.level'
    _description = 'Competency Proficiency Level'
    _order = 'competency_id, level'

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Level', required=True)
    name = fields.Char(string='Level Name', required=True)
    definition = fields.Text(string='Definition')
    behavioral_indicators = fields.Text(string='Behavioral Indicators')

    _sql_constraints = [
        ('competency_level_uniq', 'unique(competency_id, level)',
         'This proficiency level already exists for the competency!'),
    ]


class Competency(models.Model):
    """Competency dictionary entry (FR-COM-002/003, FR-CFD-001/002)."""
    _name = 'competency.competency'
    _description = 'Competency'
    _inherit = ['mail.thread']
    _order = 'pillar, code'

    name = fields.Char(string='Competency Name', required=True, tracking=True)
    code = fields.Char(string='Competency Code', required=True, tracking=True)
    pillar = fields.Selection([
        ('core', 'Core Competency'),
        ('leadership', 'Leadership Competency'),
        ('technical', 'Technical Competency'),
    ], string='Pillar', required=True, tracking=True)
    functional_domain = fields.Char(string='Functional Domain')
    definition = fields.Text(string='Definition', tracking=True)
    rating_model_id = fields.Many2one('competency.rating.model', string='Rating Model')
    proficiency_level_ids = fields.One2many(
        'competency.proficiency.level', 'competency_id', string='Proficiency Levels')
    applicable_job_ids = fields.Many2many('hr.job', string='Applicable Job Positions')
    status = fields.Selection([
        ('active', 'Active'),
        ('retired', 'Retired'),
    ], string='Status', default='active', tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    is_seed = fields.Boolean(string='Seeded Record')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Competency Code must be unique!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            # Auto-create the standard 4 proficiency levels unless provided.
            if not record.proficiency_level_ids:
                record._generate_default_proficiency_levels()
        return records

    def _generate_default_proficiency_levels(self):
        defaults = [
            ('1', 'Basic', 'Foundational understanding; applies with guidance.'),
            ('2', 'Intermediate', 'Solid working knowledge; applies independently.'),
            ('3', 'Advanced', 'Deep expertise; serves as go-to resource.'),
            ('4', 'Expert', 'Mastery and thought leadership; shapes organizational direction.'),
        ]
        Level = self.env['competency.proficiency.level']
        for level, name, definition in defaults:
            Level.create({
                'competency_id': self.id,
                'level': level,
                'name': name,
                'definition': definition,
            })

    def unlink(self):
        if any(rec.is_seed for rec in self):
            raise ValidationError(_('Seeded competencies cannot be deleted. Archive them instead.'))
        return super().unlink()
