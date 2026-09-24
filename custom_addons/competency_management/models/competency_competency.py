# -*- coding: utf-8 -*-
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyRatingModel(models.Model):
    """Evaluation scale attachable to competencies."""
    _name = 'competency.rating.model'
    _description = 'Competency Rating Model'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    max_rating = fields.Integer(
        string='Number of Levels / Rank', default=4, required=True,
        help='Highest proficiency/rating value in this scale.')
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('competency.rating.model.line', 'rating_model_id', string='Proficiency Levels', copy=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Rating Model code must be unique!'),
    ]

    @api.onchange('max_rating')
    def _onchange_max_rating(self):
        if self.max_rating and self.max_rating > 0 and not self.line_ids:
            self._sync_level_lines()

    def action_generate_lines(self):
        """Action button to auto-generate or reset proficiency level lines based on max_rating."""
        for rec in self:
            rec._sync_level_lines(force_reset=True)

    def _sync_level_lines(self, force_reset=False):
        for rec in self:
            if not rec.max_rating or rec.max_rating <= 0:
                continue
            if force_reset or not rec.line_ids:
                if force_reset:
                    rec.line_ids = [(5, 0, 0)]
                line_vals = []
                for i in range(1, rec.max_rating + 1):
                    lvl_str = str(i)
                    name_str = f"Level {i}"
                    if rec.max_rating == 4:
                        def_names = {'1': 'Level 1 - Basic', '2': 'Level 2 - Intermediate', '3': 'Level 3 - Advanced', '4': 'Level 4 - Expert'}
                        name_str = def_names.get(lvl_str, name_str)
                    elif rec.max_rating == 5:
                        def_names = {'1': 'Very Bad', '2': 'Bad', '3': 'Good', '4': 'Better', '5': 'Best'}
                        name_str = def_names.get(lvl_str, name_str)
                    
                    line_vals.append((0, 0, {
                        'level': lvl_str,
                        'name': name_str,
                        'sequence': i * 10,
                    }))
                rec.line_ids = line_vals


class CompetencyRatingModelLine(models.Model):
    """Proficiency Level definition line for a Competency Rating Model."""
    _name = 'competency.rating.model.line'
    _description = 'Competency Rating Model Line'
    _order = 'sequence, level'

    rating_model_id = fields.Many2one('competency.rating.model', string='Rating Model', required=True, ondelete='cascade')
    level = fields.Char(string='Level / Rank', required=True, default='1')
    name = fields.Char(string='Level Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)

    _sql_constraints = [
        ('rating_model_level_uniq', 'unique(rating_model_id, level)', 'Level rank number must be unique per Rating Model!'),
    ]


class CompetencyLevelChangeLog(models.Model):
    """Audit log for definition changes on competency proficiency levels."""
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
    """Proficiency level line with mandatory behavioral indicators."""
    _name = 'competency.proficiency.level'
    _description = 'Competency Proficiency Level'
    _order = 'competency_id, level'

    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    level = fields.Char(string='Level / Rank', required=True, default='1')
    name = fields.Char(string='Level Name', required=True, default='Level 1 - Basic')
    definition = fields.Text(string='Definition')
    behavioral_indicators = fields.Text(string='Behavioral Indicators', required=True)

    _sql_constraints = [
        ('competency_level_uniq', 'unique(competency_id, level)',
         'This proficiency level already exists for this competency. You cannot create duplicate levels. Please edit the existing record instead.'),
    ]

    @api.constrains('competency_id', 'level')
    def _check_level_uniqueness_and_limit(self):
        for rec in self:
            if rec.competency_id:
                max_req = rec.competency_id.rating_model_id.max_rating if rec.competency_id.rating_model_id else 4
                all_levels = self.search([('competency_id', '=', rec.competency_id.id)])
                if len(all_levels) > max_req:
                    raise ValidationError(_("A competency using '%s' cannot have more than %d proficiency levels.") % (rec.competency_id.rating_model_id.name, max_req))
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
                name_str = rec.name or f"Level {rec.level}"
                raise ValidationError(_("Behavioral Indicators are required for Level %s (%s). Please fill in the behavioral indicators before saving.") % (rec.level, name_str))

    @api.model_create_multi
    def create(self, vals_list):
        force_write = self.env.context.get('force_write')
        for vals in vals_list:
            comp_id = vals.get('competency_id')
            if comp_id and not force_write and not self.env.su:
                comp = self.env['competency.competency'].browse(comp_id)
                if comp.state == 'approved':
                    raise ValidationError(_("Cannot add proficiency levels to an approved competency (%s - Version %s). Please create a new version.") % (comp.name, comp.version))
                if comp.status == 'retired' or comp.state == 'retired':
                    raise ValidationError(_("Cannot add proficiency levels to a retired competency (%s).") % comp.name)
        return super().create(vals_list)

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.competency_id and not force_write and not self.env.su:
                if rec.competency_id.state == 'approved':
                    raise ValidationError(_(
                        "Proficiency levels and behavioral indicators of approved competency '%s' (Version %s) "
                        "are strictly immutable. Please click 'Create New Version' on the competency to make changes."
                    ) % (rec.competency_id.name, rec.competency_id.version))
                if rec.competency_id.status == 'retired' or rec.competency_id.state == 'retired':
                    raise ValidationError(_("Cannot modify proficiency levels on a retired competency (%s).") % rec.competency_id.name)
                
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
                            "without going through the Competency Framework change/version-control workflow. "
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
                            body=Markup(_("Proficiency Level %s definition updated by %s.<br/><b>Old:</b> %s<br/><b>New:</b> %s")) % (
                                escape(str(rec.level or '')), escape(self.env.user.name or ''), escape(old_def or ''), escape(new_def or '')
                            )
                        )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_retired_or_approved(self):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.competency_id and not force_write and not self.env.su:
                if rec.competency_id.state == 'approved':
                    raise ValidationError(_("Cannot delete proficiency levels from an approved competency (%s - Version %s). Please create a new version.") % (rec.competency_id.name, rec.competency_id.version))
                if rec.competency_id.status == 'retired' or rec.competency_id.state == 'retired':
                    raise ValidationError(_("Cannot delete proficiency levels from a retired competency (%s).") % rec.competency_id.name)



class Competency(models.Model):
    """Competency dictionary entry.
    
    NOTE: Shared globally across all companies (intentionally not company-scoped
    to maintain a unified bank-wide competency framework for Bunna Bank S.C.).
    """
    _name = 'competency.competency'
    _description = 'Competency'
    _inherit = ['mail.thread']
    _order = 'pillar, code, version desc'

    name = fields.Char(string='Competency Name', required=True, tracking=True)
    code = fields.Char(string='Competency Code', required=True, tracking=True)
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    parent_competency_id = fields.Many2one(
        'competency.competency', string='Base Competency', index=True, readonly=True, ondelete='set null')
    previous_version_id = fields.Many2one(
        'competency.competency', string='Previous Version', index=True, readonly=True, ondelete='set null')
    child_version_ids = fields.One2many(
        'competency.competency', 'previous_version_id', string='Successor Versions')
    version_count = fields.Integer(
        compute='_compute_version_count', string='Total Versions')
    change_description = fields.Text(
        string='Version Change Description', tracking=True)
    version_history_ids = fields.Many2many(
        'competency.competency', compute='_compute_version_history',
        string='Version History', context={'active_test': False})
    pillar = fields.Selection([
        ('core', 'Core Competencies'),
        ('leadership', 'Leadership Competencies'),
        ('technical', 'Technical Competencies'),
    ], string='Pillar', required=True, tracking=True)
    functional_domain = fields.Char(string='Functional Domain')
    definition = fields.Text(string='Definition', tracking=True)

    @api.model
    def _default_rating_model_id(self):
        m = self.env['competency.rating.model'].search([('code', '=', '4SCALE')], limit=1)
        if not m:
            m = self.env['competency.rating.model'].search([], limit=1)
        return m.id if m else False

    rating_model_id = fields.Many2one('competency.rating.model', string='Rating Model', default=_default_rating_model_id)
    is_rating_model_readonly = fields.Boolean(compute='_compute_is_rating_model_readonly')

    def _compute_is_rating_model_readonly(self):
        count = self.env['competency.rating.model'].search_count([])
        is_ro = (count <= 1)
        for rec in self:
            rec.is_rating_model_readonly = is_ro
    proficiency_level_ids = fields.One2many(
        'competency.proficiency.level', 'competency_id', string='Proficiency Levels', copy=False)
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
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], string='Approval State', default='draft', tracking=True)

    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Status', compute='_compute_status', store=True)

    active = fields.Boolean(default=True, tracking=True)

    @api.depends('state')
    def _compute_status(self):
        for rec in self:
            if rec.state == 'approved':
                rec.status = 'active'
            else:
                rec.status = 'inactive'

    @api.onchange('rating_model_id')
    def _onchange_rating_model_id(self):
        if self.rating_model_id:
            self._sync_proficiency_levels_from_rating_model()

    def _sync_proficiency_levels_from_rating_model(self):
        for rec in self:
            if not rec.rating_model_id:
                continue
            model_lines = rec.rating_model_id.line_ids
            if not model_lines:
                rec.rating_model_id._sync_level_lines()
                model_lines = rec.rating_model_id.line_ids

            matrix_config = self.env['competency.matrix.config'].get_active_config()
            new_lines = []
            for mline in model_lines:
                lvl_str = str(mline.level)
                b_ind = getattr(matrix_config, f'tech_indicator_level_{lvl_str}', f"Level {lvl_str} ({mline.name}) behavioral indicator for {rec.name or 'competency'}.")
                new_lines.append((0, 0, {
                    'level': lvl_str,
                    'name': mline.name,
                    'behavioral_indicators': b_ind,
                    'definition': f"{mline.name} proficiency level.",
                }))

            rec.proficiency_level_ids = [(5, 0, 0)] + new_lines

    @api.depends('name', 'version')
    def _compute_display_name(self):
        for rec in self:
            if rec.version:
                rec.display_name = f"{rec.name} ({rec.version})"
            else:
                rec.display_name = rec.name or ''

    @api.depends('parent_competency_id')
    def _compute_version_count(self):
        for rec in self:
            root_id = rec.parent_competency_id.id if rec.parent_competency_id else rec.id
            rec.version_count = self.with_context(active_test=False).search_count([
                '|', ('id', '=', root_id), ('parent_competency_id', '=', root_id)
            ])

    def _compute_version_history(self):
        for rec in self:
            root_id = rec.parent_competency_id.id if rec.parent_competency_id else rec.id
            rec.version_history_ids = self.with_context(active_test=False).search([
                '|', ('id', '=', root_id), ('parent_competency_id', '=', root_id)
            ], order='id desc')

    def action_view_versions(self):
        self.ensure_one()
        root_id = self.parent_competency_id.id if self.parent_competency_id else self.id
        return {
            'name': _("Versions of %s") % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'competency.competency',
            'view_mode': 'list,form',
            'domain': ['|', ('id', '=', root_id), ('parent_competency_id', '=', root_id)],
            'context': {'active_test': False, 'default_parent_competency_id': root_id},
        }

    @staticmethod
    def _bump_version(version):
        if not version:
            return 'v2.0'
        try:
            clean = version.lower().lstrip('v')
            if '.' in clean:
                parts = clean.split('.')
                major = int(parts[0])
                return f"v{major + 1}.0"
            else:
                return f"v{int(clean) + 1}.0"
        except Exception:
            return 'v2.0'

    def action_create_new_version(self):
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_("Only approved competencies can be versioned."))
            
        root = self.parent_competency_id or self
        
        # Check if there is already a draft or submitted version in this lineage
        existing_pending = self.with_context(active_test=False).search([
            ('id', '!=', self.id),
            '|', ('id', '=', root.id), ('parent_competency_id', '=', root.id),
            ('state', 'in', ('draft', 'submitted'))
        ], limit=1)
        if existing_pending:
            raise UserError(_(
                "A pending version (%s - Version %s, State: %s) already exists for this competency. "
                "Please finalize or discard the existing pending version before creating another one."
            ) % (existing_pending.name, existing_pending.version, existing_pending.state))

        # Determine next version string
        all_versions = self.with_context(active_test=False).search([
            '|', ('id', '=', root.id), ('parent_competency_id', '=', root.id)
        ])
        new_version_str = self._bump_version(self.version)
        existing_v_strs = set(all_versions.mapped('version'))
        counter = 1
        while new_version_str in existing_v_strs:
            new_version_str = f"v{len(all_versions) + counter}.0"
            counter += 1

        level_vals = []
        for pl in self.proficiency_level_ids:
            level_vals.append((0, 0, {
                'level': pl.level,
                'name': pl.name,
                'definition': pl.definition,
                'behavioral_indicators': pl.behavioral_indicators,
            }))

        new_comp = self.copy(default={
            'name': self.name,
            'code': self.code,
            'version': new_version_str,
            'state': 'draft',
            'status': 'inactive',
            'active': True,
            'parent_competency_id': root.id,
            'previous_version_id': self.id,
            'change_description': _("New version branched from %s.") % self.version,
            'definition': self.definition,
            'proficiency_level_ids': level_vals,
        })

        self.message_post(body=_("New draft version %s (ID %s) created from this version.") % (new_comp.version, new_comp.id))
        new_comp.message_post(body=_("Version %s created from approved version %s (ID %s).") % (new_comp.version, self.version, self.id))

        return {
            'name': _("Competency: %s (%s)") % (new_comp.name, new_comp.version),
            'type': 'ir.actions.act_window',
            'res_model': 'competency.competency',
            'res_id': new_comp.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_submit(self):
        for rec in self:
            req_count = rec.rating_model_id.max_rating if rec.rating_model_id else 4
            if not rec.proficiency_level_ids or len(rec.proficiency_level_ids) < req_count:
                raise ValidationError(_("Competency '%s' must have all %d proficiency levels defined before submitting for approval.") % (rec.name, req_count))
            rec.write({'state': 'submitted'})

    def action_approve(self):
        if not self.env.user.has_group('competency_management.group_competency_admin') and not self.env.su:
            raise UserError(_("Only Competency Administrators can approve competency dictionary entries."))
        for rec in self:
            root_id = rec.parent_competency_id.id if rec.parent_competency_id else rec.id
            old_versions = self.with_context(active_test=False).search([
                ('id', '!=', rec.id),
                '|', ('id', '=', root_id), ('parent_competency_id', '=', root_id),
                ('state', '=', 'approved')
            ])
            for old in old_versions:
                # 1. Update active role mapping lines pointing to old to now point to rec
                mapping_lines = self.env['competency.role.mapping.line'].search([('competency_id', '=', old.id)])
                if mapping_lines:
                    mapping_lines.write({'competency_id': rec.id})
                
                # 2. Update clusters pointing to old to point to rec
                clusters = self.env['competency.cluster'].search([('competency_ids', 'in', [old.id])])
                for cluster in clusters:
                    cluster.write({'competency_ids': [(3, old.id), (4, rec.id)]})

                # 3. Update frameworks if applicable
                if 'competency.framework.line' in self.env:
                    fw_lines = self.env['competency.framework.line'].search([('competency_id', '=', old.id)])
                    if fw_lines:
                        fw_lines.write({'competency_id': rec.id})

                # 4. Retire / supersede old version
                old.with_context(force_write=True).write({
                    'state': 'retired',
                    'active': False,
                })
                old.message_post(body=Markup(_(
                    "Superseded and retired by new approved version <b>%s</b> on %s."
                )) % (escape(rec.version or ''), escape(str(fields.Date.today()))))

            rec.write({'state': 'approved', 'active': True})
            if old_versions:
                rec.message_post(body=Markup(_(
                    "Approved as active version <b>%s</b>, superseding previous version(s) (%s). "
                    "All active role mappings and clusters have been migrated to this version."
                )) % (escape(rec.version or ''), escape(", ".join(old_versions.mapped('version')))))
            else:
                rec.message_post(body=Markup(_("Competency approved as active version <b>%s</b>.")) % escape(rec.version or ''))

    def action_retire(self):
        """Retire/inactivate competency and auto-disappear from clusters & job mappings."""
        for rec in self:
            rec.write({'state': 'retired', 'active': False})
            # Auto-disappear from clusters and role mappings
            clusters = self.env['competency.cluster'].search([('competency_ids', 'in', [rec.id])])
            for cluster in clusters:
                cluster.write({'competency_ids': [(3, rec.id)]})
            self.env['competency.role.mapping.line'].search([('competency_id', '=', rec.id)]).unlink()
            rec.message_post(body=_("Competency '%s' has been retired and automatically unlinked from all clusters and role mappings.") % rec.name)

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'approved':
                raise UserError(_("Approved competencies cannot be reset to draft. Use 'Create New Version' to make changes."))
            if rec.child_version_ids.filtered(lambda c: c.state == 'approved'):
                raise UserError(_("This version has been superseded by a newer approved version and cannot be reset to draft."))
            rec.write({'state': 'draft', 'active': True})

    @api.constrains('name', 'parent_competency_id', 'previous_version_id')
    def _check_unique_name_case_insensitive(self):
        for rec in self:
            if not rec.name:
                continue
            rec_root_id = rec.parent_competency_id.id if rec.parent_competency_id else rec.id
            duplicates = self.with_context(active_test=False).search([
                ('id', '!=', rec.id),
                ('name', '=ilike', rec.name.strip())
            ])
            for dup in duplicates:
                dup_root_id = dup.parent_competency_id.id if dup.parent_competency_id else dup.id
                if rec_root_id != dup_root_id:
                    raise ValidationError(_("A competency with the name '%s' already exists (Code: %s). Competency names must be unique across different competencies.") % (rec.name.strip(), dup.code))

    @api.constrains('code', 'parent_competency_id', 'previous_version_id')
    def _check_unique_code_lineage(self):
        for rec in self:
            if not rec.code:
                continue
            rec_root_id = rec.parent_competency_id.id if rec.parent_competency_id else rec.id
            duplicates = self.with_context(active_test=False).search([
                ('id', '!=', rec.id),
                ('code', '=ilike', rec.code.strip())
            ])
            for dup in duplicates:
                dup_root_id = dup.parent_competency_id.id if dup.parent_competency_id else dup.id
                if rec_root_id != dup_root_id:
                    raise ValidationError(_("A competency with the code '%s' already exists for a different competency (%s). Code must be unique across different competencies.") % (rec.code.strip(), dup.name))

    _sql_constraints = [
        ('code_version_uniq', 'unique(code, version)', 'The Competency Code and Version combination must be unique!'),
    ]

    @api.constrains('proficiency_level_ids', 'rating_model_id')
    def _check_proficiency_levels_completeness(self):
        for rec in self:
            if not rec.rating_model_id:
                continue
            levels = rec.proficiency_level_ids
            existing_lvl_codes = set(levels.mapped('level'))
            model_lines = rec.rating_model_id.line_ids
            required_lvl_codes = set(model_lines.mapped('level')) if model_lines else {str(i) for i in range(1, rec.rating_model_id.max_rating + 1)}
            
            if len(levels) > rec.rating_model_id.max_rating:
                raise ValidationError(_("Competency '%s' cannot have more than %d proficiency levels under rating model '%s'.") % (rec.name, rec.rating_model_id.max_rating, rec.rating_model_id.name))
                
            if len(levels) != len(existing_lvl_codes):
                raise ValidationError(_("Duplicate proficiency levels detected on competency '%s'. Each level must be unique.") % rec.name)
                
            missing = required_lvl_codes - existing_lvl_codes
            if missing:
                raise ValidationError(_("Competency '%s' is missing required level(s) for rating model '%s': %s.") % (rec.name, rec.rating_model_id.name, ", ".join(sorted(missing))))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('version'):
                vals['version'] = 'v1.0'
            if not vals.get('proficiency_level_ids'):
                rating_model_id = vals.get('rating_model_id')
                if not rating_model_id:
                    rating_model_id = self._default_rating_model_id()
                    vals['rating_model_id'] = rating_model_id
                if rating_model_id:
                    rating_model = self.env['competency.rating.model'].browse(rating_model_id)
                    model_lines = rating_model.line_ids
                    if not model_lines:
                        rating_model._sync_level_lines()
                        model_lines = rating_model.line_ids
                    matrix_config = self.env['competency.matrix.config'].get_active_config()
                    comp_name = vals.get('name', 'competency')
                    new_lines = []
                    for mline in model_lines:
                        lvl_str = str(mline.level)
                        b_ind = getattr(matrix_config, f'tech_indicator_level_{lvl_str}', f"Level {lvl_str} ({mline.name}) behavioral indicator for {comp_name}.")
                        new_lines.append((0, 0, {
                            'level': lvl_str,
                            'name': mline.name,
                            'behavioral_indicators': b_ind,
                            'definition': f"{mline.name} proficiency level.",
                        }))
                    if new_lines:
                        vals['proficiency_level_ids'] = new_lines
        return super().create(vals_list)

    def _generate_default_proficiency_levels(self):
        self.ensure_one()
        self._sync_proficiency_levels_from_rating_model()

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        allow_def_edit = self.env.context.get('eds_allow_definition_edit')
        
        for rec in self:
            # 1. Retired status lock
            if (rec.state == 'retired' or rec.status == 'retired') and not force_write and not self.env.su:
                if set(vals.keys()) - {'status', 'active'}:
                    raise ValidationError(_("This competency (%s) is retired and cannot be edited. Reactivate the competency or use an Admin override instead.") % rec.name)
            
            # 2. Approved immutability lock (definition, levels, and identity fields cannot be modified on approved competencies)
            if rec.state == 'approved' and not force_write and not self.env.su:
                immutable_fields = {'name', 'code', 'pillar', 'functional_domain', 'rating_model_id', 'definition', 'proficiency_level_ids'}
                changed_fields = {k for k in vals.keys() if k in immutable_fields and vals[k] != getattr(rec, k, False)}
                if 'proficiency_level_ids' in vals:
                    changed_fields.add('proficiency_level_ids')
                if changed_fields:
                    raise ValidationError(_(
                        "Competency '%s' (Version %s) is approved and strictly immutable. "
                        "Neither the definition nor proficiency levels/behavioral indicators can be edited. "
                        "Please use 'Create New Version' to introduce changes."
                    ) % (rec.name, rec.version))

            # 3. Governed-edit check for name or pillar on approved framework
            if ('name' in vals or 'pillar' in vals) and not force_write and not allow_def_edit and not self.env.su:
                new_name = vals.get('name', rec.name)
                new_pillar = vals.get('pillar', rec.pillar)
                if new_name != rec.name or new_pillar != rec.pillar:
                    if 'competency.framework.line' in self.env:
                        approved_fw = self.env['competency.framework.line'].search([
                            ('competency_id', '=', rec.id),
                            ('framework_id.state', '=', 'approved')
                        ], limit=1)
                        if approved_fw:
                            raise ValidationError(_(
                                "Competency name or pillar cannot be re-edited for a competency on an approved framework (%s) "
                                "without going through the Competency Framework change/version-control workflow. "
                                "Create a new framework version or submit an approved change request."
                            ) % approved_fw.framework_id.name)
                        
        return super().write(vals)

    def unlink(self):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if not force_write and not self.env.su:
                if rec.state == 'approved':
                    raise ValidationError(_("Approved competencies cannot be deleted (%s - Version %s). You must retire the competency or supersede it with a new version.") % (rec.name, rec.version))
                if rec.status == 'retired' or rec.state == 'retired':
                    raise ValidationError(_('Retired competencies cannot be deleted.'))
        return super().unlink()

    @api.model
    def action_seed_matrix_data(self):
        """Seed competencies, framework, clusters, and role mappings from docs/edited Final Comptency Matrix......xlsx."""
        import os, zipfile, re, logging
        import xml.etree.ElementTree as ET

        _logger = logging.getLogger(__name__)

        possible_paths = [
            r'docs/edited Final Comptency Matrix......xlsx',
            r'/mnt/extra-addons/competency_management/data/competency_matrix.xlsx',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'edited Final Comptency Matrix......xlsx')),
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'competency_matrix.xlsx')),
        ]
        
        target_path = False
        for p in possible_paths:
            if os.path.exists(p):
                target_path = p
                break
                
        if not target_path:
            _logger.info("Matrix XLSX seed file not found. Skipping auto-seed.")
            return True

        with zipfile.ZipFile(target_path, 'r') as z:
            strings_xml = z.read('xl/sharedStrings.xml')
            stree = ET.fromstring(strings_xml)
            shared_strings = [''.join(t.text or '' for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')) for si in stree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si')]

            def get_val(cell):
                t = cell.attrib.get('t')
                v = cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                if v is None: return ''
                val = v.text
                if t == 's': return shared_strings[int(val)] if int(val) < len(shared_strings) else val
                return val

            wb_xml = z.read('xl/workbook.xml')
            wbtree = ET.fromstring(wb_xml)
            sheets_info = [child.attrib['name'] for child in wbtree.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets')]

            raw_mappings = []
            domain_comps_map = {}
            for idx, sname in enumerate(sheets_info, 1):
                if sname == 'Proficiency': continue
                try:
                    sheet_xml = z.read(f'xl/worksheets/sheet{idx}.xml')
                except Exception:
                    continue
                stree = ET.fromstring(sheet_xml)
                rows = list(stree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'))
                if not rows: continue
                
                for r in rows[1:]:
                    vals = [get_val(c).strip() for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c')]
                    if len(vals) >= 4 and vals[1].strip():
                        cat = vals[0].strip()
                        cname = re.sub(r'\s+', ' ', vals[1].strip())
                        jtitle = re.sub(r'\s+', ' ', vals[2].strip())
                        prof = vals[3].strip()
                        wunit = vals[4].strip() if len(vals) > 4 else ''
                        raw_mappings.append((cat, cname, jtitle, prof, wunit, sname))
                        domain_comps_map.setdefault(sname, set()).add(cname)

        rating_model = self.env['competency.rating.model'].search([('code', '=', '4SCALE')], limit=1)
        if not rating_model:
            rating_model = self.env['competency.rating.model'].create({
                'name': '4-Point Proficiency Scale',
                'code': '4SCALE',
                'max_rating': 4,
                'description': 'Standard 4-Level scale (Level 1 Basic, Level 2 Intermediate, Level 3 Advanced, Level 4 Expert)'
            })

        core_names = {'Execution Mastery', 'Professional Authenticity', 'Ethical Influence', 'Collaboration', 'Creativity'}
        leadership_names = {'Strategy Management', 'Continuous Improvement', 'Prudential Decision Making', 'Self Leadership', 'People Leadership', 'Ambidexterity Leadership', 'Ambidextrous Leadership', 'Self-Leadership'}

        distinct_comps = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            cat_lower = cat.lower()
            if 'core' in cat_lower or cname_clean in core_names:
                pillar = 'core'
            elif 'lead' in cat_lower or cname_clean in leadership_names:
                pillar = 'leadership'
            else:
                pillar = 'technical'
            
            if cname_clean not in distinct_comps:
                distinct_comps[cname_clean] = (pillar, sname)

        # Parse definitions from docx file if present
        doc_defs = {}
        docx_path = False
        possible_docx = [
            r'docs/Final Competency Framework Reviesd.docx',
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'Final Competency Framework Reviesd.docx')),
        ]
        for dp in possible_docx:
            if os.path.exists(dp):
                docx_path = dp
                break
        if docx_path:
            try:
                import docx
                d_doc = docx.Document(docx_path)
                for tbl in d_doc.tables:
                    if len(tbl.columns) >= 2:
                        for row in tbl.rows:
                            tc1 = row.cells[0].text.strip() if len(row.cells) > 0 else ''
                            tc2 = row.cells[1].text.strip() if len(row.cells) > 1 else ''
                            if tc1 and tc2 and tc1 not in ('Competency', 'Framework Pillar', 'Pillar', 'Instead of...'):
                                c1_clean = ' '.join(tc1.split()).lower()
                                c2_clean = ' '.join(tc2.split())
                                doc_defs[c1_clean] = c2_clean
            except Exception:
                pass

        matrix_config = self.env['competency.matrix.config'].get_active_config()

        tech_counter = 1
        comp_records = {}
        for cname, (pillar, domain) in sorted(distinct_comps.items()):
            comp = self.env['competency.competency'].search([('name', '=ilike', cname)], limit=1)
            rich_def = doc_defs.get(cname.lower(), f"Bunna Bank {pillar.capitalize()} Competency: {cname}")
            
            if not comp:
                if pillar == 'core':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'core']) + 1
                    code = f"CORE-{c_cnt:02d}"
                elif pillar == 'leadership':
                    c_cnt = len([c for c in comp_records.values() if c.pillar == 'leadership']) + 1
                    code = f"LEAD-{c_cnt:02d}"
                else:
                    code = f"TECH-{tech_counter:03d}"
                    tech_counter += 1

                comp = self.env['competency.competency'].create({
                    'name': cname,
                    'code': code,
                    'pillar': pillar,
                    'functional_domain': domain if pillar == 'technical' else 'Bank-Wide',
                    'definition': rich_def,
                    'rating_model_id': rating_model.id,
                    'status': 'active',
                })
            else:
                if not comp.definition or comp.definition.startswith("Bunna Bank "):
                    comp.write({'definition': rich_def})

            comp_records[cname] = comp

            for lvl_val, lvl_name in [
                ('1', 'Basic'),
                ('2', 'Intermediate'),
                ('3', 'Advanced'),
                ('4', 'Expert'),
            ]:
                if pillar == 'technical':
                    b_ind = getattr(matrix_config, f'tech_indicator_level_{lvl_val}', f"Level {lvl_val} ({lvl_name}) technical behavioral indicator for {cname}.")
                else:
                    b_ind = f"Level {lvl_val} ({lvl_name}) behavioral indicators for {cname}."

                existing_lvl = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', comp.id),
                    ('level', '=', lvl_val)
                ], limit=1)
                if not existing_lvl:
                    self.env['competency.proficiency.level'].create({
                        'competency_id': comp.id,
                        'level': lvl_val,
                        'behavioral_indicators': b_ind,
                    })
                else:
                    existing_lvl.write({'behavioral_indicators': b_ind})

        framework = self.env['competency.framework'].search([('code', '=', 'BUNNA-FW-v1.0')], limit=1)
        if not framework:
            framework = self.env['competency.framework'].create({
                'name': "Bunna Bank Integrated Competency Framework",
                'code': 'BUNNA-FW-v1.0',
                'version': 'v1.0',
                'description': "Bunna Bank's official Integrated Competency Framework comprising Core, Leadership, and Technical competencies.",
                'state': 'draft',
            })
        
        fw_existing_comps = framework.line_ids.mapped('competency_id.id')
        fw_line_vals = []
        for cname, comp in comp_records.items():
            if comp.id not in fw_existing_comps:
                fw_line_vals.append({
                    'framework_id': framework.id,
                    'competency_id': comp.id,
                })
        if fw_line_vals:
            self.env['competency.framework.line'].create(fw_line_vals)

        if framework.state != 'approved':
            framework.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })

        clusters = {}
        core_comps = [c.id for c in comp_records.values() if c.pillar == 'core']
        core_cluster = self.env['competency.cluster'].search([('code', '=', 'CLUSTER-CORE')], limit=1)
        if not core_cluster:
            core_cluster = self.env['competency.cluster'].create({
                'name': 'Core Competency Cluster',
                'code': 'CLUSTER-CORE',
                'description': 'Universal Core Competencies required across all Bunna Bank roles.',
                'competency_ids': [(6, 0, core_comps)],
                'min_proficiency': '2',
            })
        else:
            core_cluster.write({'competency_ids': [(6, 0, core_comps)]})
        clusters['core'] = core_cluster

        lead_comps = [c.id for c in comp_records.values() if c.pillar == 'leadership']
        lead_cluster = self.env['competency.cluster'].search([('code', '=', 'CLUSTER-LEAD')], limit=1)
        if not lead_cluster:
            lead_cluster = self.env['competency.cluster'].create({
                'name': 'Leadership Capability Cluster',
                'code': 'CLUSTER-LEAD',
                'description': 'Leadership and Supervisory Competencies for managerial and leadership roles.',
                'competency_ids': [(6, 0, lead_comps)],
                'min_proficiency': '2',
            })
        else:
            lead_cluster.write({'competency_ids': [(6, 0, lead_comps)]})
        clusters['leadership'] = lead_cluster

        for sname, cnames in domain_comps_map.items():
            domain_comp_ids = [comp_records[cn].id for cn in cnames if cn in comp_records]
            code_safe = re.sub(r'[^A-Z0-9]', '', sname.upper())[:10]
            cluster_code = f"CLUSTER-TECH-{code_safe}"
            t_cluster = self.env['competency.cluster'].search([('code', '=', cluster_code)], limit=1)
            if not t_cluster and domain_comp_ids:
                t_cluster = self.env['competency.cluster'].create({
                    'name': f"{sname} Technical Cluster",
                    'code': cluster_code,
                    'description': f"Technical Competency Cluster for {sname} functional domain.",
                    'competency_ids': [(6, 0, domain_comp_ids)],
                    'min_proficiency': '2',
                })
            elif t_cluster and domain_comp_ids:
                t_cluster.write({'competency_ids': [(6, 0, domain_comp_ids)]})
            clusters[sname] = t_cluster

        job_mappings = {}
        job_domains = {}
        for cat, cname, jtitle, prof, wunit, sname in raw_mappings:
            if not jtitle: continue
            cname_clean = cname.replace('Ambidexterity Leadership', 'Ambidextrous Leadership').replace('Self Leadership', 'Self-Leadership')
            comp = comp_records.get(cname_clean)
            if not comp: continue
            
            prof_str = str(prof).strip()
            req_prof = prof_str if prof_str in ('1', '2', '3', '4') else '2'
            job_mappings.setdefault(jtitle, {})[comp.id] = req_prof
            job_domains.setdefault(jtitle, set()).add(sname)

        mapping_count = 0
        for jtitle, comp_dict in job_mappings.items():
            job = self.env['hr.job'].search([('name', '=ilike', jtitle)], limit=1)
            if not job:
                job = self.env['hr.job'].create({
                    'name': jtitle,
                    'description': f"Job Position for {jtitle}",
                })

            mapping = self.env['competency.role.mapping'].search([('job_position_id', '=', job.id)], limit=1)
            if not mapping:
                applicable_cluster_ids = [core_cluster.id]
                j_lower = jtitle.lower()
                if any(k in j_lower for k in ['manager', 'director', 'chief', 'leader', 'head', 'supervisor']):
                    applicable_cluster_ids.append(lead_cluster.id)
                for dom in job_domains.get(jtitle, []):
                    if dom in clusters and clusters[dom]:
                        applicable_cluster_ids.append(clusters[dom].id)

                mapping = self.env['competency.role.mapping'].create({
                    'job_position_id': job.id,
                    'version': 'v1.0',
                    'state': 'draft',
                    'effective_date': fields.Date.context_today(self),
                    'change_description': 'Official Bunna Bank Competency Framework matrix import',
                    'cluster_ids': [(6, 0, list(set(applicable_cluster_ids)))],
                })

            existing_comp_ids = mapping.line_ids.mapped('competency_id.id')
            line_create_vals = []
            for cid, req_p in comp_dict.items():
                if cid not in existing_comp_ids:
                    line_create_vals.append({
                        'mapping_id': mapping.id,
                        'competency_id': cid,
                        'required_proficiency': req_p,
                        'weight': 1.0,
                    })
            if line_create_vals:
                self.env['competency.role.mapping.line'].create(line_create_vals)

            if mapping.state != 'approved':
                mapping.with_context(force_write=True).write({
                    'state': 'approved',
                    'approved_by_id': self.env.user.id,
                    'approval_date': fields.Datetime.now(),
                })
            mapping_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Matrix Seeding Complete'),
                'message': _('Seeded %s competencies (with docx definitions), %s clusters, and %s job position role mappings successfully.') % (len(comp_records), len(clusters), mapping_count),
                'type': 'success',
                'sticky': False,
            }
        }


