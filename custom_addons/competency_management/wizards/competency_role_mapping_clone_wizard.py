# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyRoleMappingCloneLine(models.TransientModel):
    _name = 'competency.role.mapping.clone.line'
    _description = 'Clone Role Mapping Competency Line'

    wizard_id = fields.Many2one('competency.role.mapping.clone.wizard', string='Wizard', ondelete='cascade')
    competency_id = fields.Many2one('competency.competency', string='Competency', required=True)
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
            for line in source.line_ids:
                lines.append((0, 0, {
                    'competency_id': line.competency_id.id,
                    'required_proficiency': line.required_proficiency or '2',
                    'weight': line.weight or 1.0,
                }))
            res['line_ids'] = lines
        return res

    def action_clone_and_adapt(self):
        """Clone competency mapping lines to the target job position in draft state and open it."""
        self.ensure_one()
        if not self.target_job_id:
            raise UserError(_('Please select a target Job Position.'))
        if not self.line_ids:
            raise UserError(_('Please specify at least one competency line.'))

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
        else:
            new_version = self.target_version

        # If an unapproved draft already exists for target job and version, reuse or raise
        if existing and existing.state != 'approved':
            target_mapping = existing
            target_mapping.line_ids.unlink()
        else:
            target_mapping = Mapping.create({
                'job_position_id': self.target_job_id.id,
                'version': new_version,
                'state': 'draft',
                'effective_date': fields.Date.context_today(self),
                'change_description': _("Replicated & adapted from %s (%s).") % (
                    self.source_mapping_id.mapping_name or self.source_job_id.name,
                    self.source_mapping_id.version
                ),
                'cluster_ids': [(6, 0, self.source_mapping_id.cluster_ids.ids)],
            })

        for line in self.line_ids:
            MappingLine.create({
                'mapping_id': target_mapping.id,
                'competency_id': line.competency_id.id,
                'required_proficiency': line.required_proficiency,
                'override_default': True,
                'weight': line.weight,
            })

        # Return action to open the newly created mapping immediately
        form_view_id = self.env.ref('competency_management.view_competency_role_mapping_form').id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Role-Competency Mapping: %s') % target_mapping.mapping_name,
            'res_model': 'competency.role.mapping',
            'res_id': target_mapping.id,
            'view_mode': 'form',
            'views': [(form_view_id, 'form')],
            'target': 'current',
        }
