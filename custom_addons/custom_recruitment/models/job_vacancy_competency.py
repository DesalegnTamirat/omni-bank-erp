# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class JobVacancyCompetency(models.Model):
    """Line model holding one required competency per job vacancy."""
    _name = 'job.vacancy.competency'
    _description = 'Job Vacancy Competency'
    _rec_name = 'competency_id'

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.competency_id.name or str(rec.id)
    _order = 'vacancy_id, sequence, id'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    def _auto_init(self):
        try:
            with self.env.cr.savepoint():
                self.env.cr.execute("""
                    DO $$ 
                    BEGIN 
                        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'job_vacancy_competency') 
                           AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'competency_competency') THEN
                            DELETE FROM job_vacancy_competency 
                            WHERE competency_id IS NOT NULL 
                              AND competency_id NOT IN (SELECT id FROM competency_competency);
                        END IF;
                    END $$;
                """)
        except Exception as e:
            _logger.warning("Safe cleanup on job_vacancy_competency: %s", e)
        return super()._auto_init()

    vacancy_id = fields.Many2one(
        'job.vacancy', string='Job Vacancy',
        required=True, ondelete='cascade', index=True,
    )
    competency_id = fields.Many2one(
        'competency.competency', string='Competency',
        required=True,
    )
    required_level = fields.Selection([
        ('basic', 'Basic'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('expert', 'Expert'),
    ], string='Required Level', required=True, default='intermediate')
    notes = fields.Text(string='Notes')

    @api.constrains('vacancy_id', 'competency_id')
    def _check_unique_vacancy_competency(self):
        for rec in self:
            if rec.vacancy_id and rec.competency_id and rec.active:
                dup = self.search([
                    ('id', '!=', rec.id),
                    ('vacancy_id', '=', rec.vacancy_id.id),
                    ('competency_id', '=', rec.competency_id.id),
                    ('active', '=', True),
                ], limit=1)
                if dup:
                    raise ValidationError(_(
                        "The competency '%s' is already added to this Vacancy. Duplicate competencies are not allowed."
                    ) % (rec.competency_id.display_name or rec.competency_id.name))

    # ── Archiving (soft-delete) ──────────────────────────────────────────────
    def unlink(self):
        self.write({'active': False})
        return True


class HrCompetenciesInfoJob(models.Model):
    """Extension of hr_competencies_info_job in custom_recruitment:
    Links job position competencies tab directly to competency.competency from Competency Management module.
    """
    _inherit = 'hr_competencies_info_job'

    competencies = fields.Many2one('competency.competency', string="Competency", ondelete='set null')

