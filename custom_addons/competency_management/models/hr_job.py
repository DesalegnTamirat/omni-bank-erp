# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrJobCompetency(models.Model):
    """hr.job extension: direct relation to competency role mappings and API for Career Path / Recruitment."""
    _inherit = 'hr.job'

    competency_role_mapping_ids = fields.One2many(
        'competency.role.mapping', 'job_position_id', string='Competency Role Mappings',
        help="Competencies explicitly assigned to this job position.")
    competency_mapping_ids = fields.One2many(
        'competency.role.mapping', 'job_position_id', string='Competency Role Mappings (Alias)',
        help="Alias for competency_role_mapping_ids.")
    competency_mapping_count = fields.Integer(
        string='Competency Mapping Count', compute='_compute_competency_mapping_count',
        help="Total number of competency role mappings for this job position.")
    required_competency_count = fields.Integer(
        string='Required Competencies Count', compute='_compute_required_competency_count',
        help="Total count of competencies assigned to this job position or grade.")

    @api.depends('competency_role_mapping_ids')
    def _compute_competency_mapping_count(self):
        for job in self:
            job.competency_mapping_count = len(job.competency_role_mapping_ids)

    @api.depends('competency_role_mapping_ids')
    def _compute_required_competency_count(self):
        for job in self:
            job.required_competency_count = len(job.competency_role_mapping_ids)

    def action_view_competency_mappings(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('competency_management.action_competency_role_mapping')
        action['domain'] = [('job_position_id', '=', self.id)]
        action['context'] = {'default_job_position_id': self.id}
        return action

    def get_required_competencies(self, grade_id=None):
        """API helper method for Career Path, Recruitment, and external modules.
        
        Returns a list of dicts containing required competencies for this Job Position.
        Evaluates Job Position exceptions first; if none defined, falls back to Job Grade if grade_id is supplied.
        """
        self.ensure_one()
        Mapping = self.env['competency.role.mapping']
        
        # 1. Search for position-specific mappings first (Job Position governs)
        mappings = Mapping.search([('job_position_id', '=', self.id), ('state', '=', 'approved')])
        if not mappings:
            mappings = Mapping.search([('job_position_id', '=', self.id)])
        governance_type = 'job_position'

        # 2. Fallback to Job Grade if position mappings are empty
        if not mappings:
            grade_obj = False
            if grade_id:
                grade_obj = self.env['employee.grade'].browse(grade_id) if isinstance(grade_id, int) else grade_id
            if not grade_obj or not grade_obj.exists():
                grade_obj = Mapping._resolve_job_grade(self)

            if grade_obj and grade_obj.exists():
                mappings = Mapping.search([('grade_id', '=', grade_obj.id), ('state', '=', 'approved')])
                if not mappings:
                    mappings = Mapping.search([('grade_id', '=', grade_obj.id)])
                governance_type = 'job_grade'

        all_comps = mappings.mapped('line_ids.competency_id')
        comp_ids = all_comps.ids
        cluster_by_comp = {}
        if comp_ids:
            clusters = self.env['competency.cluster'].search([('competency_ids', 'in', comp_ids)])
            for cl in clusters:
                for cid in cl.competency_ids.ids:
                    if cid not in cluster_by_comp:
                        cluster_by_comp[cid] = cl

        result = []
        for m in mappings:
            for line in m.line_ids:
                comp = line.competency_id
                if not comp:
                    continue
                lvl_val = line.required_proficiency or '2'
                selection_dict = dict(line._fields['required_proficiency'].selection) if 'required_proficiency' in line._fields else {}
                cluster = cluster_by_comp.get(comp.id)
                result.append({
                    'mapping_id': m.id,
                    'line_id': line.id,
                    'competency_id': comp.id,
                    'competency_name': comp.name or '',
                    'competency_code': getattr(comp, 'code', '') or '',
                    'cluster_id': cluster.id if cluster else False,
                    'cluster_name': cluster.name if cluster else '',
                    'pillar': comp.pillar or '',
                    'required_proficiency': lvl_val,
                    'required_level_name': selection_dict.get(lvl_val, f"Level {lvl_val}"),
                    'weight': line.weight,
                    'governance': governance_type,
                })
        return result
