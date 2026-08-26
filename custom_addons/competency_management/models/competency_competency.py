# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyRatingModel(models.Model):
    """Evaluation scale attachable to competencies ."""
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


class CompetencyLevelChangeLog(models.Model):
    """Audit log for definition changes on competency proficiency levels (FR-COM-006)."""
    _name = 'competency.level.change.log'
    _description = 'Competency Level Definition Change Log'
    _order = 'effective_date desc, id desc'

    level_id = fields.Many2one(
        'competency.proficiency.level', string='Proficiency Level', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    old_definition = fields.Text(string='Previous Definition')
    new_definition = fields.Text(string='New Definition')
    change_description = fields.Text(string='Change Description', required=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, required=True)
    user_id = fields.Many2one(
        'res.users', string='User Responsible', default=lambda self: self.env.user, required=True, readonly=True)


class CompetencyProficiencyLevel(models.Model):
    """One proficiency level (Basic..Expert) with mandatory behavioral indicators (FR-COM-003, FR-COM-004, FR-COM-005)."""
    _name = 'competency.proficiency.level'
    _description = 'Competency Proficiency Level'
    _order = 'competency_id, level'

    LEVEL_NAME_MAP = {
        '1': 'Basic',
        '2': 'Intermediate',
        '3': 'Advanced',
        '4': 'Expert',
    }

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Level', required=True, default='1')
    name = fields.Selection([
        ('Basic', 'Basic'),
        ('Intermediate', 'Intermediate'),
        ('Advanced', 'Advanced'),
        ('Expert', 'Expert'),
    ], string='Level Name', compute='_compute_name', store=True, readonly=True)
    definition = fields.Text(string='Definition')
    behavioral_indicators = fields.Text(string='Behavioral Indicators', required=True)

    _sql_constraints = [
        ('competency_level_uniq', 'unique(competency_id, level)',
         'This proficiency level already exists for this competency. You cannot create duplicate levels. Please edit the existing record instead.'),
    ]

    @api.depends('level')
    def _compute_name(self):
        for rec in self:
            rec.name = self.LEVEL_NAME_MAP.get(str(rec.level or '1'), 'Basic')

    @api.onchange('level')
    def _onchange_level(self):
        if self.level:
            self.name = self.LEVEL_NAME_MAP.get(str(self.level), 'Basic')

    @api.constrains('competency_id', 'level')
    def _check_level_uniqueness_and_limit(self):
        for rec in self:
            if rec.competency_id:
                all_levels = self.search([('competency_id', '=', rec.competency_id.id)])
                if len(all_levels) > 4:
                    raise ValidationError(_("A competency cannot have more than 4 proficiency levels. Exactly 4 levels (Level 1 - Basic, Level 2 - Intermediate, Level 3 - Advanced, Level 4 - Expert) are required."))
                duplicates = self.search([
                    ('competency_id', '=', rec.competency_id.id),
                    ('level', '=', rec.level),
                    ('id', '!=', rec.id)
                ])
                if duplicates:
                    raise ValidationError(_("This proficiency level (Level %s) already exists for this competency. You cannot create duplicate levels. Please edit the existing record instead.") % rec.level)

    @api.constrains('behavioral_indicators')
    def _check_behavioral_indicators(self):
        for rec in self:
            if not rec.behavioral_indicators or not rec.behavioral_indicators.strip():
                name_str = rec.name or self.LEVEL_NAME_MAP.get(str(rec.level or '1'), 'Basic')
                raise ValidationError(_("Behavioral Indicators are required for Level %s (%s). Please fill in the behavioral indicators before saving.") % (rec.level, name_str))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            lvl = str(vals.get('level') or '1')
            vals['name'] = self.LEVEL_NAME_MAP.get(lvl, 'Basic')
            comp_id = vals.get('competency_id')
            if comp_id:
                comp = self.env['competency.competency'].browse(comp_id)
                if comp.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                    raise ValidationError(_("Cannot add proficiency levels to a retired competency (%s).") % comp.name)
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.competency_id and rec.competency_id.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot modify proficiency levels on a retired competency (%s).") % rec.competency_id.name)

        if 'level' in vals or 'name' in vals:
            for rec in self:
                lvl = str(vals.get('level', rec.level) or '1')
                vals['name'] = self.LEVEL_NAME_MAP.get(lvl, 'Basic')
                
        if 'definition' in vals:
            for rec in self:
                new_def = (vals.get('definition') or '').strip()
                old_def = (rec.definition or '').strip()
                if new_def != old_def:
                    approved_fw = self.env['competency.framework.line'].search([
                        ('competency_id', '=', rec.competency_id.id),
                        ('framework_id.state', '=', 'approved')
                    ], limit=1)
                    if approved_fw and not self.env.context.get('eds_allow_definition_edit') and not self.env.context.get('force_write'):
                        raise ValidationError(_(
                            "Definition text cannot be freely re-edited for a competency on an approved framework "
                            "without going through the Competency Framework change/version-control workflow (FR-COM-006). "
                            "Create a new framework version or submit an approved change request."
                        ))
                    
                    change_desc = self.env.context.get('change_description') or _("Updated Level %s definition.") % rec.level
                    eff_date = self.env.context.get('effective_date') or fields.Date.context_today(self)
                    self.env['competency.level.change.log'].sudo().create({
                        'level_id': rec.id,
                        'competency_id': rec.competency_id.id,
                        'old_definition': old_def,
                        'new_definition': new_def,
                        'change_description': change_desc,
                        'effective_date': eff_date,
                        'user_id': self.env.user.id,
                    })
                    if rec.competency_id:
                        rec.competency_id.message_post(
                            body=_("Proficiency Level %s definition updated by %s.<br/><b>Old:</b> %s<br/><b>New:</b> %s") % (
                                rec.level, self.env.user.name, old_def, new_def
                            )
                        )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_retired(self):
        for rec in self:
            if rec.competency_id and rec.competency_id.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_("Cannot delete proficiency levels from a retired competency (%s).") % rec.competency_id.name)



class Competency(models.Model):
    """Competency dictionary entry (FR-COM-002, FR-COM-003)."""
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
    applicable_job_ids = fields.Many2many(
        'hr.job', string='Applicable Job Positions',
        compute='_compute_applicable_job_ids', store=True)

    @api.depends('status')
    def _compute_applicable_job_ids(self):
        RoleMappingLine = self.env['competency.role.mapping.line']
        for rec in self:
            lines = RoleMappingLine.search([
                ('competency_id', '=', rec.id),
                ('mapping_id.state', '=', 'approved')
            ])
            rec.applicable_job_ids = lines.mapped('mapping_id.job_position_id')
    change_log_ids = fields.One2many(
        'competency.level.change.log', 'competency_id', string='Definition Change Logs', readonly=True)
    status = fields.Selection([
        ('active', 'Active'),
        ('retired', 'Retired'),
    ], string='Status', default='active', tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    framework_line_ids = fields.One2many(
        'competency.framework.line', 'competency_id', string='Framework Lines')
    approved_framework_ids = fields.Many2many(
        'competency.framework', string='Approved Frameworks',
        compute='_compute_approved_framework_ids',
        search='_search_approved_framework_ids')

    def _compute_approved_framework_ids(self):
        FrameworkLine = self.env['competency.framework.line']
        for rec in self:
            lines = FrameworkLine.search([
                ('competency_id', '=', rec.id),
                ('framework_id.state', '=', 'approved')
            ])
            rec.approved_framework_ids = lines.mapped('framework_id')

    def _search_approved_framework_ids(self, operator, value):
        FrameworkLine = self.env['competency.framework.line']
        lines = FrameworkLine.search([('framework_id.state', '=', 'approved')])
        competency_ids = lines.mapped('competency_id').ids
        if operator in ('!=', 'not in') and not value:
            return [('id', 'in', competency_ids)]
        elif operator in ('=', 'in') and not value:
            return [('id', 'not in', competency_ids)]
        return [('id', 'in', competency_ids)]

    @api.constrains('name')
    def _check_unique_name_case_insensitive(self):
        for rec in self:
            if rec.name:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('name', '=ilike', rec.name.strip())
                ], limit=1)
                if duplicate:
                    raise ValidationError(_("A competency with the name '%s' already exists (Code: %s). Competency names must be unique.") % (rec.name.strip(), duplicate.code))

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Competency Code must be unique!'),
    ]

    @api.constrains('proficiency_level_ids')
    def _check_proficiency_levels_completeness(self):
        for rec in self:
            levels = rec.proficiency_level_ids
            existing_lvl_codes = set(levels.mapped('level'))
            required_lvl_codes = {'1', '2', '3', '4'}
            
            if len(levels) > 4:
                raise ValidationError(_("A competency cannot have more than 4 proficiency levels. Exactly 4 levels (Level 1 - Basic, Level 2 - Intermediate, Level 3 - Advanced, Level 4 - Expert) are required."))
                
            if len(levels) != len(existing_lvl_codes):
                raise ValidationError(_("Duplicate proficiency levels detected on competency '%s'. Each competency must have unique levels (Level 1, Level 2, Level 3, Level 4).") % rec.name)
                
            missing = required_lvl_codes - existing_lvl_codes
            if missing:
                missing_names = []
                name_map = {'1': 'Level 1 (Basic)', '2': 'Level 2 (Intermediate)', '3': 'Level 3 (Advanced)', '4': 'Level 4 (Expert)'}
                for m in sorted(missing):
                    missing_names.append(name_map.get(m, m))
                raise ValidationError(_("Competencies must have all 4 proficiency levels. Missing level(s): %s.") % ", ".join(missing_names))

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
            ('1', 'Basic', 'Foundational understanding; applies with guidance.',
             'Demonstrates basic awareness and foundational knowledge; applies skills under direct supervision and guidance.'),
            ('2', 'Intermediate', 'Solid working knowledge; applies independently.',
             'Applies solid working knowledge independently in routine operational situations; resolves standard technical issues.'),
            ('3', 'Advanced', 'Deep expertise; serves as go-to resource.',
             'Demonstrates advanced proficiency and deep subject matter expertise; guides and mentors team members on complex scenarios.'),
            ('4', 'Expert', 'Mastery and thought leadership; shapes organizational direction.',
             'Displays strategic mastery and thought leadership; defines institutional standards and drives organizational innovation.'),
        ]
        Level = self.env['competency.proficiency.level']
        for level, name, definition, indicators in defaults:
            Level.create({
                'competency_id': self.id,
                'level': level,
                'name': name,
                'definition': definition,
                'behavioral_indicators': indicators,
            })

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        allow_def_edit = self.env.context.get('eds_allow_definition_edit')
        
        for rec in self:
            # 1. Retired status lock
            if rec.status == 'retired' and not force_write and not self.env.su:
                if set(vals.keys()) - {'status', 'active'}:
                    raise ValidationError(_("This competency (%s) is retired and cannot be edited. Reactivate the competency or use an Admin override instead.") % rec.name)
            
            # 2. Governed-edit check for name or pillar on approved framework
            if ('name' in vals or 'pillar' in vals) and not force_write and not allow_def_edit and not self.env.su:
                new_name = vals.get('name', rec.name)
                new_pillar = vals.get('pillar', rec.pillar)
                if new_name != rec.name or new_pillar != rec.pillar:
                    approved_fw = self.env['competency.framework.line'].search([
                        ('competency_id', '=', rec.id),
                        ('framework_id.state', '=', 'approved')
                    ], limit=1)
                    if approved_fw:
                        raise ValidationError(_(
                            "Competency name or pillar cannot be re-edited for a competency on an approved framework (%s) "
                            "without going through the Competency Framework change/version-control workflow (FR-COM-006). "
                            "Create a new framework version or submit an approved change request."
                        ) % approved_fw.framework_id.name)
                        
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.status == 'retired' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_('Retired competencies cannot be deleted.'))
        return super().unlink()

