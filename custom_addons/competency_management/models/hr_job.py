# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrJobCompetency(models.Model):
    """hr.job extension: direct relation to competency role mappings and API for Career Path / Recruitment."""
    _inherit = 'hr.job'

    competency_role_mapping_ids = fields.One2many(
        'competency.role.mapping', 'job_id', string='Competency Role Mappings',
        help="Competencies explicitly assigned to this job position.")
    required_competency_count = fields.Integer(
        string='Required Competencies Count', compute='_compute_required_competency_count',
        help="Total count of competencies assigned to this job position or grade.")

    @api.depends('competency_role_mapping_ids')
    def _compute_required_competency_count(self):
        for job in self:
            job.required_competency_count = len(job.competency_role_mapping_ids)

    def get_required_competencies(self, grade_id=None):
        """API helper method for Career Path, Recruitment, and external modules.
        
        Returns a list of dicts containing required competencies for this Job Position.
        Evaluates Job Position exceptions first; if none defined, falls back to Job Grade if grade_id is supplied.
        """
        self.ensure_one()
        Mapping = self.env['competency.role.mapping']
        
        # 1. Search for position-specific mappings first (Job Position governs)
        mappings = Mapping.search([('job_id', '=', self.id)])
        governance_type = 'job_position'

        # 2. Fallback to Job Grade if position mappings are empty and grade_id is supplied
        if not mappings and grade_id:
            grade_obj = self.env['employee.grade'].browse(grade_id) if isinstance(grade_id, int) else grade_id
            if grade_obj and grade_obj.exists():
                mappings = Mapping.search([('grade_id', '=', grade_obj.id)])
                governance_type = 'job_grade'

        result = []
        for m in mappings:
            lvl = m.required_proficiency_level_id
            result.append({
                'mapping_id': m.id,
                'competency_id': m.competency_id.id if m.competency_id else False,
                'competency_name': m.competency_id.name if m.competency_id else '',
                'competency_code': getattr(m.competency_id, 'code', '') or '',
                'cluster_id': m.competency_id.cluster_id.id if m.competency_id and m.competency_id.cluster_id else False,
                'cluster_name': m.competency_id.cluster_id.name if m.competency_id and m.competency_id.cluster_id else '',
                'required_level_id': lvl.id if lvl else False,
                'required_level_name': lvl.name if lvl else '',
                'required_level_code': getattr(lvl, 'level_code', '') or '',
                'required_level_score': getattr(lvl, 'level_score', 0.0) or 0.0,
                'governance': governance_type,
            })
        return result
