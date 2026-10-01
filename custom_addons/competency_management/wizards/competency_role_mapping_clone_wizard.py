# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyRoleMappingCloneLine(models.TransientModel):
    _name = 'competency.role.mapping.clone.line'
    _description = 'Clone Role Mapping Competency Line'

    wizard_id = fields.Many2one('competency.role.mapping.clone.wizard', string='Wizard', ondelete='cascade')
    source_line_id = fields.Many2one('competency.role.mapping.line', string='Source Line')
    competency_id = fields.Many2one('competency.competency', string='Competency', required=False)
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', readonly=True)
    required_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    weight = fields.Float(string='Weight', default=1.0)


class CompetencyRoleMappingCloneWizard(models.TransientModel):
    """Wizard to clone and adapt an existing role-competency mapping to another job position."""
    _name = 'competency.role.mapping.clone.wizard'
    _description = 'Clone & Adapt Competency Role Mapping'

    source_mapping_id = fields.Many2one(
        'competency.role.mapping', string='Source Role Mapping', required=True, readonly=True)
    source_job_id = fields.Many2one(
        'hr.job', string='Source Job Position', related='source_mapping_id.job_position_id', readonly=True)
    target_job_id = fields.Many2one(
        'hr.job', string='Target Job Position', required=True,
        help='Select the job position that will receive these competencies.')
    target_version = fields.Char(string='Target Version', default='v1.0', required=True)
    line_ids = fields.One2many(
        'competency.role.mapping.clone.line', 'wizard_id', string='Competency Requirements',
        help='Review and adapt proficiency levels before creating the new profile.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'competency.role.mapping':
            source = self.env['competency.role.mapping'].browse(active_id)
            res['source_mapping_id'] = source.id
            lines = []
            if source.line_ids:
                for line in source.line_ids:
                    if line.competency_id:
                        lines.append((0, 0, {
                            'source_line_id': line.id,
                            'competency_id': line.competency_id.id,
                            'required_proficiency': line.required_proficiency or '2',
                            'weight': line.weight or 1.0,
                        }))
            elif source.cluster_ids:
                for comp in source.cluster_ids.mapped('competency_ids'):
                    lines.append((0, 0, {
                        'competency_id': comp.id,
                        'required_proficiency': '2',
                        'weight': 1.0,
                    }))
            res['line_ids'] = lines
        return res

    def action_clone_and_adapt(self):
        """Clone competency mapping lines to the target job position in draft state and open it."""
        self.ensure_one()
        if not self.target_job_id:
            raise UserError(_('Please select a target Job Position.'))

        source = self.source_mapping_id
        Mapping = self.env['competency.role.mapping']
        MappingLine = self.env['competency.role.mapping.line']

        # Check existing mapping for target job
        existing = Mapping.search([
            ('job_position_id', '=', self.target_job_id.id),
            ('version', '=', self.target_version),
            ('state', '!=', 'archived'),
        ], limit=1)

        if existing and existing.state == 'approved':
            # Auto-increment version if target version already approved
            v_num = 1.0
            try:
                v_num = float(self.target_version.replace('v', '')) + 0.1
            except Exception:
                pass
            new_version = f"v{v_num:.1f}"
            target_mapping = Mapping.create({
                'job_position_id': self.target_job_id.id,
                'version': new_version,
                'state': 'draft',
                'effective_date': fields.Date.context_today(self),
                'change_description': _("Replicated & adapted from %s (%s).") % (
                    source.mapping_name or source.job_position_id.name,
                    source.version
                ),
                'cluster_ids': [(6, 0, source.cluster_ids.ids)],
            })
        elif existing and existing.state != 'approved':
            target_mapping = existing
            target_mapping.line_ids.unlink()
            target_mapping.write({
                'cluster_ids': [(6, 0, source.cluster_ids.ids)],
                'change_description': _("Replicated & adapted from %s (%s).") % (
                    source.mapping_name or source.job_position_id.name,
                    source.version
                ),
            })
        else:
            target_mapping = Mapping.create({
                'job_position_id': self.target_job_id.id,
                'version': self.target_version or 'v1.0',
                'state': 'draft',
                'effective_date': fields.Date.context_today(self),
                'change_description': _("Replicated & adapted from %s (%s).") % (
                    source.mapping_name or source.job_position_id.name,
                    source.version
                ),
                'cluster_ids': [(6, 0, source.cluster_ids.ids)],
            })

        # Multi-tiered extraction of competencies:
        # Tier 1: User's adaptations in wizard table (self.line_ids)
        # Tier 2: Source mapping lines (source.line_ids)
        # Tier 3: Source cluster competencies
        adapted_map = {}
        source_lines_list = list(source.line_ids)

        for idx, w_line in enumerate(self.line_ids):
            comp_id = False
            if w_line.competency_id:
                comp_id = w_line.competency_id.id
            elif w_line.source_line_id and w_line.source_line_id.competency_id:
                comp_id = w_line.source_line_id.competency_id.id
            elif idx < len(source_lines_list) and source_lines_list[idx].competency_id:
                comp_id = source_lines_list[idx].competency_id.id

            if comp_id:
                prof = w_line.required_proficiency or '2'
                weight = w_line.weight if w_line.weight else 1.0
                adapted_map[comp_id] = (prof, weight)

        # Fallback if self.line_ids was empty or deserialization lost all items
        if not adapted_map:
            if source.line_ids:
                for s_line in source.line_ids:
                    if s_line.competency_id:
                        adapted_map[s_line.competency_id.id] = (
                            s_line.required_proficiency or '2',
                            s_line.weight or 1.0
                        )
            elif source.cluster_ids:
                for comp in source.cluster_ids.mapped('competency_ids'):
                    adapted_map[comp.id] = ('2', 1.0)

        # Cluster integration: If source had clusters, ensure all competencies in those clusters are covered
        if source.cluster_ids:
            for c_comp in source.cluster_ids.mapped('competency_ids'):
                if c_comp.id not in adapted_map:
                    adapted_map[c_comp.id] = ('2', 1.0)

        # Bulk create mapping lines
        new_lines_vals = []
        for comp_id, (prof, weight) in adapted_map.items():
            new_lines_vals.append({
                'mapping_id': target_mapping.id,
                'competency_id': comp_id,
                'required_proficiency': prof,
                'override_default': True,
                'weight': weight,
            })

        if new_lines_vals:
            MappingLine.with_context(skip_mapping_unique_check=True).create(new_lines_vals)

        for line in target_mapping.line_ids:
            line._compute_matrix_proficiency()

        # Action: Direct navigation to the newly created/updated mapping form view
        form_view_id = self.env.ref('competency_management.view_competency_role_mapping_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Role-Competency Mapping: %s') % (target_mapping.mapping_name or target_mapping.job_position_id.name),
            'res_model': 'competency.role.mapping',
            'res_id': target_mapping.id,
            'view_mode': 'form',
            'views': [(form_view_id, 'form')],
            'target': 'main',
            'context': {
                'form_view_initial_mode': 'edit',
            },
        }
