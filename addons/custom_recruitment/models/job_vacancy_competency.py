from odoo import api, models, fields, _
from odoo.exceptions import ValidationError


class JobVacancyCompetency(models.Model):
    _name = 'job.vacancy.competency'
    _description = "Job Vacancy Required Competency"
    _rec_name = 'competency_id'

    vacancy_id = fields.Many2one(
        'job.vacancy', string="Vacancy",
        ondelete='cascade', required=True
    )
    competency_id = fields.Many2one(
        'recruitment.competency', string="Competency",
        required=True,
        domain=[('status', '=', 'yes')],
        help="FR-REC-012: Competency required for the vacancy."
    )
    required_level = fields.Selection(
        [('1', 'Basic'),
         ('2', 'Intermediate'),
         ('3', 'Advanced'),
         ('4', 'Expert')],
        string="Required Level", required=True,
        help="FR-REC-012: Required proficiency level for this competency."
    )

    _sql_constraints = [
        ('vacancy_competency_unique',
         'unique(vacancy_id, competency_id)',
         'This competency is already added to the vacancy.'),
    ]