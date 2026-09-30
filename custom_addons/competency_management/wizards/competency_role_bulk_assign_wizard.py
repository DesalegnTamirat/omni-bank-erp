# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CompetencyRoleBulkAssignLine(models.TransientModel):
    _name = 'competency.role.bulk.assign.line'
    _description = 'Bulk Assign Competency Line'

    wizard_id = fields.Many2one('competency.role.bulk.assign.wizard', string='Wizard', ondelete='cascade')
    competency_id = fields.Many2one('competency.competency', string='Competency', required=True)
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', readonly=True)
    required_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    weight = fields.Float(string='Weight', default=1.0)


class CompetencyRoleBulkAssignWizard(models.TransientModel):
    _name = 'competency.role.bulk.assign.wizard'
    _description = 'Bulk Competency Assignment Wizard'

    job_ids = fields.Many2many(
        'hr.job', string='Target Job Positions', required=True,
        help='Select multiple job positions to assign these competencies to.')
    line_ids = fields.One2many(
        'competency.role.bulk.assign.line', 'wizard_id', string='Competencies to Assign', required=True)
    skip_approved = fields.Boolean(
        string='Skip Roles with Approved Profiles', default=True,
        help='If checked, existing approved role mappings will be safely skipped to preserve governance.')

    def action_bulk_assign(self):
        self.ensure_one()
        if not self.job_ids:
            raise UserError(_('Please select at least one Job Position.'))
        if not self.line_ids:
            raise UserError(_('Please add at least one Competency line to assign.'))

        Mapping = self.env['competency.role.mapping']
        MappingLine = self.env['competency.role.mapping.line']

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for job in self.job_ids:
            # Check if an approved mapping already exists for this job position
            approved_existing = Mapping.search([
                ('job_position_id', '=', job.id),
                ('state', '=', 'approved'),
            ], limit=1)

            if approved_existing and self.skip_approved:
                skipped_count += 1
                continue

            # Check if a draft or pending mapping exists for this job position
            draft_existing = Mapping.search([
                ('job_position_id', '=', job.id),
                ('state', 'in', ('draft', 'under_approval')),
            ], order='id desc', limit=1)

            if draft_existing:
                # Append or update draft mapping
                for line in self.line_ids:
                    existing_line = draft_existing.line_ids.filtered(lambda l: l.competency_id.id == line.competency_id.id)
                    if existing_line:
                        existing_line.write({
                            'required_proficiency': line.required_proficiency,
                            'override_default': True,
                            'weight': line.weight,
                        })
                    else:
                        MappingLine.create({
                            'mapping_id': draft_existing.id,
                            'competency_id': line.competency_id.id,
                            'required_proficiency': line.required_proficiency,
                            'override_default': True,
                            'weight': line.weight,
                        })
                updated_count += 1
            else:
                # Create brand new Draft mapping
                new_mapping = Mapping.create({
                    'job_position_id': job.id,
                    'state': 'draft',
                    'version': 'v1.0',
                    'effective_date': fields.Date.context_today(self),
                    'change_description': _('Bulk auto-assigned competencies via Bulk Assignment Wizard.'),
                })
                for line in self.line_ids:
                    MappingLine.create({
                        'mapping_id': new_mapping.id,
                        'competency_id': line.competency_id.id,
                        'required_proficiency': line.required_proficiency,
                        'override_default': True,
                        'weight': line.weight,
                    })
                created_count += 1

        total_configured = created_count + updated_count
        msg = _(
            "Bulk Competency Assignment Summary:\n\n"
            "• %d Job Position(s) configured successfully (%d new draft profiles created, %d existing draft profiles updated).\n"
            "• %d Job Position(s) skipped (already approved & protected)."
        ) % (total_configured, created_count, updated_count, skipped_count)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bulk Assignment Complete'),
                'message': msg,
                'type': 'success',
                'sticky': True,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Role-Competency Mappings'),
                    'res_model': 'competency.role.mapping',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                },
            }
        }
