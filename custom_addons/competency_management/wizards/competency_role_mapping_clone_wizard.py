# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyRoleMappingCloneWizard(models.TransientModel):
    """Bulk competency mapping & clone-and-adapt wizard for similar job positions (FR-MAP-004)."""
    _name = 'competency.role.mapping.clone.wizard'
    _description = 'Clone & Adapt Competency Role Mapping'

    source_mapping_id = fields.Many2one(
        'competency.role.mapping', string='Source Role Mapping', required=True, readonly=True)
    target_job_ids = fields.Many2many(
        'hr.job', string='Target Job Positions', required=True,
        help='Select similar job positions to receive cloned competency mapping profiles.')
    target_version = fields.Char(string='Target Version', default='v1.0', required=True)
    copy_lines = fields.Boolean(string='Copy Competency Lines', default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'competency.role.mapping':
            res['source_mapping_id'] = active_id
        return res

    def action_clone_and_adapt(self):
        """Clone source mapping lines across target job positions in draft state (FR-MAP-004)."""
        self.ensure_one()
        if not self.target_job_ids:
            raise UserError(_('Please select at least one target Job Position.'))
            
        created_mappings = self.env['competency.role.mapping']
        Mapping = self.env['competency.role.mapping']
        MappingLine = self.env['competency.role.mapping.line']
        
        for job in self.target_job_ids:
            existing = Mapping.search([
                ('job_position_id', '=', job.id),
                ('version', '=', self.target_version)
            ], limit=1)
            if existing:
                raise ValidationError(_("A mapping for Job Position '%s' at version '%s' already exists (ID: %s).") % (job.name, self.target_version, existing.id))
                
            new_map = Mapping.create({
                'job_position_id': job.id,
                'version': self.target_version,
                'record_type': 'production',
                'change_description': _("Cloned & adapted from %s (Version %s).") % (self.source_mapping_id.mapping_name, self.source_mapping_id.version),
                'cluster_ids': [(6, 0, self.source_mapping_id.cluster_ids.ids)],
            })
            
            if self.copy_lines:
                for line in self.source_mapping_id.line_ids:
                    MappingLine.create({
                        'mapping_id': new_map.id,
                        'competency_id': line.competency_id.id,
                        'required_proficiency': line.required_proficiency,
                        'weight': line.weight,
                    })
            created_mappings |= new_map

        return {
            'type': 'ir.actions.act_window',
            'name': _('Cloned Role Mappings'),
            'res_model': 'competency.role.mapping',
            'domain': [('id', 'in', created_mappings.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }
