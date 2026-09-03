# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CompetencyRoleMapping(models.Model):
    """Role-Competency mapping: master reference for assessment & gap analysis (FR-COM-006, FR-MAP-001..006)."""
    _name = 'competency.role.mapping'
    _description = 'Role-Competency Mapping'
    _inherit = ['mail.thread']
    _order = 'job_position_id, grade_id, version desc'
    _rec_name = 'mapping_name'

    mapping_name = fields.Char(
        string='Role Mapping', compute='_compute_mapping_name', store=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position', required=True, tracking=True)
    grade_id = fields.Many2one('employee.grade', string='Job Grade', compute='_compute_grade_id', store=True, readonly=True)
    line_ids = fields.One2many('competency.role.mapping.line', 'mapping_id', string='Competency Lines')
    cluster_ids = fields.Many2many('competency.cluster', string='Competency Clusters')
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('archived', 'Archived / Superseded'),
    ], string='Status', default='draft', tracking=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, required=True)
    change_description = fields.Text(string='Change Description')
    last_review_date = fields.Date(string='Last Review Date')
    next_review_date = fields.Date(string='Next Review Date')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)



    is_operating_unit_specific = fields.Boolean(
        string='Specific to Operating Unit', default=False, tracking=True,
        help="Check this if this competency mapping applies only to specific Operating Units (e.g. specific Branches/Districts). If left unchecked, it applies globally to all operating units."
    )
    operating_unit_ids = fields.Many2many(
        'operating.unit', string='Specific Operating Units', tracking=True
    )

    @api.depends('job_position_id')
    def _compute_grade_id(self):
        for rec in self:
            if rec.job_position_id:
                job = rec.job_position_id
                rec.grade_id = getattr(job, 'grade', False) or getattr(job, 'grade_id', False)
            else:
                rec.grade_id = False

    @api.depends('job_position_id', 'grade_id', 'is_operating_unit_specific', 'operating_unit_ids')
    def _compute_mapping_name(self):
        for rec in self:
            parts = [rec.job_position_id.name] if rec.job_position_id else ['(No Job)']
            if rec.grade_id:
                parts.append('(%s)' % rec.grade_id.grade_name)
            if rec.is_operating_unit_specific and rec.operating_unit_ids:
                ou_names = ", ".join(rec.operating_unit_ids.mapped('name'))
                parts.append('[OU: %s]' % ou_names)
            rec.mapping_name = ' '.join(parts)

    @api.constrains('job_position_id', 'state', 'is_operating_unit_specific', 'operating_unit_ids')
    def _check_single_active_mapping_per_job(self):
        """Allow multiple active mappings per Job Position if they target distinct Operating Units."""
        for rec in self:
            if rec.job_position_id and rec.state in ('draft', 'under_approval', 'approved'):
                domain = [
                    ('job_position_id', '=', rec.job_position_id.id),
                    ('state', 'in', ('draft', 'under_approval', 'approved')),
                    ('id', '!=', rec.id),
                    ('is_operating_unit_specific', '=', rec.is_operating_unit_specific),
                ]
                if rec.is_operating_unit_specific and rec.operating_unit_ids:
                    domain.append(('operating_unit_ids', 'in', rec.operating_unit_ids.ids))

                active_mappings = self.search(domain)
                if active_mappings:
                    raise ValidationError(_(
                        "A matching active competency mapping for Job Position '%s' already exists (%s). "
                        "Please archive or update the existing mapping."
                    ) % (rec.job_position_id.name, active_mappings[0].mapping_name))

    @api.onchange('cluster_ids')
    def _onchange_cluster_ids(self):
        if not self.cluster_ids:
            return

        existing_comp_ids = set()
        for line in self.line_ids:
            if line.competency_id:
                existing_comp_ids.add(line.competency_id.id)

        new_virtual_lines = self.env['competency.role.mapping.line']
        for cluster in self.cluster_ids:
            for comp in cluster.competency_ids:
                if comp.id and comp.id not in existing_comp_ids:
                    existing_comp_ids.add(comp.id)
                    new_virtual_lines += self.env['competency.role.mapping.line'].new({
                        'competency_id': comp.id,
                        'override_default': False,
                        'weight': 1.0,
                    })

        if new_virtual_lines:
            self.line_ids = self.line_ids + new_virtual_lines

    def action_populate_from_clusters(self):
        """Rule 5: Populate competency lines from selected clusters taking the UNION (deduplicating)."""
        for rec in self:
            if not rec.cluster_ids:
                raise UserError(_("Please select at least one cluster first."))
            
            cluster_comps = rec.cluster_ids.mapped('competency_ids')
            existing_comp_ids = set(rec.line_ids.mapped('competency_id.id'))
            
            new_lines_vals = []
            added_count = 0
            for comp in cluster_comps:
                if comp.id not in existing_comp_ids:
                    existing_comp_ids.add(comp.id)
                    new_lines_vals.append({
                        'mapping_id': rec.id,
                        'competency_id': comp.id,
                        'override_default': False,
                        'weight': 1.0,
                    })
                    added_count += 1
            
            if new_lines_vals:
                created_lines = self.env['competency.role.mapping.line'].create(new_lines_vals)
                for l in created_lines:
                    l._compute_matrix_proficiency()
                rec.message_post(body=_("Populated %d new unique competency lines from selected clusters.") % added_count)
            else:
                rec.message_post(body=_("All competencies from selected clusters are already mapped."))

    @api.constrains('line_ids')
    def _check_unique_competency_lines(self):
        for rec in self:
            comp_ids = rec.line_ids.mapped('competency_id.id')
            if len(comp_ids) != len(set(comp_ids)):
                raise ValidationError(_("Duplicate competencies detected in the mapping lines for '%s'. Each competency can only be added once per role mapping.") % rec.mapping_name)

    def action_submit_for_approval(self):
        """Draft -> Under Approval workflow."""
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_('Add at least one competency line before submitting for approval.'))
            rec.with_context(force_write=True).write({'state': 'under_approval'})
            rec.message_post(body=_('Role-competency mapping %s submitted for approval.') % rec.mapping_name)

    def action_approve(self):
        """Under Approval -> Approved with version supersession."""
        for rec in self:
            prior_approved = self.search([
                ('job_position_id', '=', rec.job_position_id.id),
                ('state', '=', 'approved'),
                ('id', '!=', rec.id)
            ])
            if prior_approved:
                prior_approved.with_context(force_write=True).write({'state': 'archived'})
                for p in prior_approved:
                    p.message_post(body=_("Mapping version %s has been automatically superseded/archived by new approved version %s.") % (p.version, rec.version))
            
            rec.with_context(force_write=True).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Role-competency mapping %s (Version %s) approved.') % (rec.mapping_name, rec.version))
            rec._notify_assigned_employees()

    def _notify_assigned_employees(self):
        """Notify all employees assigned to this job position about updated competency expectations."""
        for rec in self:
            if not rec.job_position_id:
                continue
            employees = self.env['hr.employee'].search([('job_id', '=', rec.job_position_id.id)])
            users = employees.mapped('user_id')
            for u in users:
                if not u.partner_id:
                    continue
                msg = _(
                    "Competency expectations for your job position '%s' have been updated (Version %s). "
                    "Please review your role mapping to prepare and improve before upcoming assessments."
                ) % (rec.job_position_id.name, rec.version)
                rec.message_post(
                    body=msg,
                    partner_ids=[u.partner_id.id],
                    subtype_xmlid='mail.mt_comment'
                )

    def action_archive(self):
        self.with_context(force_write=True).write({'state': 'archived'})

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        for rec in self:
            if rec.state != 'draft' and not force_write and not self.env.su:
                locked_fields = {'job_position_id', 'grade_id', 'version', 'record_type', 'effective_date', 'change_description', 'line_ids', 'cluster_ids'}
                if set(vals.keys()) & locked_fields:
                    raise ValidationError(_("This role-competency mapping (%s - Version %s) is finalized and cannot be edited. Use 'Create New Version' instead.") % (rec.mapping_name, rec.version))
        return super().write(vals)

    def action_create_new_version(self):
        """Copy approved mapping into a new draft version after archiving the prior version."""
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_('Only approved mappings can be versioned.'))
            
        new_version_str = self._bump_version(self.version)
        change_desc = self.env.context.get('change_description') or _("New version created from %s.") % self.version
        
        # Archive current approved mapping to satisfy single-active constraint
        self.with_context(force_write=True).write({'state': 'archived'})
        self.message_post(body=_("Mapping version %s archived to allow creation of new version %s.") % (self.version, new_version_str))

        new_mapping = self.copy(default={
            'version': new_version_str,
            'state': 'draft',
            'approved_by_id': False,
            'approval_date': False,
            'change_description': change_desc,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'competency.role.mapping',
            'res_id': new_mapping.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model
    def get_role_competency_requirements(self, job_position_id):
        """API method for Recruitment candidate screening to retrieve required competencies & levels (FR-COM-029)."""
        if not job_position_id:
            return []
        mapping = self.search([
            ('job_position_id', '=', job_position_id),
            ('state', '=', 'approved'),
        ], limit=1)
        if not mapping:
            return []
        res = []
        for line in mapping.line_ids:
            res.append({
                'competency_id': line.competency_id.id,
                'competency_code': line.competency_id.code,
                'competency_name': line.competency_id.name,
                'pillar': line.competency_id.pillar,
                'required_proficiency': line.required_proficiency,
                'weight': line.weight,
            })
        return res

    @staticmethod
    def _bump_version(version):
        try:
            major, minor = version.lower().lstrip('v').split('.')
            return 'v%s.%s' % (major, int(minor) + 1)
        except Exception:
            return 'v1.1'


class CompetencyRoleMappingLine(models.Model):
    """One required competency assignment inside a role mapping."""
    _name = 'competency.role.mapping.line'
    _description = 'Role-Competency Mapping Line'

    mapping_id = fields.Many2one(
        'competency.role.mapping', string='Role Mapping', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade',
        domain="[('state', '=', 'approved'), ('status', '=', 'active')]")
    pillar = fields.Selection(related='competency_id.pillar', string='Pillar', store=True, readonly=True)
    competency_definition = fields.Text(related='competency_id.definition', string='Competency Definition', store=True, readonly=True)

    indicator_level_1 = fields.Text(string='Level 1 Indicator', compute='_compute_level_indicators')
    indicator_level_2 = fields.Text(string='Level 2 Indicator', compute='_compute_level_indicators')
    indicator_level_3 = fields.Text(string='Level 3 Indicator', compute='_compute_level_indicators')
    indicator_level_4 = fields.Text(string='Level 4 Indicator', compute='_compute_level_indicators')

    @api.depends('competency_id')
    def _compute_level_indicators(self):
        matrix_config = self.env['competency.matrix.config'].sudo().get_active_config()
        for rec in self:
            if rec.competency_id:
                levels = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id)
                ])
                l_map = {l.level: l.behavioral_indicators for l in levels if l.behavioral_indicators}
                
                rec.indicator_level_1 = l_map.get('1') or (getattr(matrix_config, 'tech_indicator_level_1') if rec.competency_id.pillar == 'technical' else 'Level 1 (Basic) behavioral indicators.')
                rec.indicator_level_2 = l_map.get('2') or (getattr(matrix_config, 'tech_indicator_level_2') if rec.competency_id.pillar == 'technical' else 'Level 2 (Intermediate) behavioral indicators.')
                rec.indicator_level_3 = l_map.get('3') or (getattr(matrix_config, 'tech_indicator_level_3') if rec.competency_id.pillar == 'technical' else 'Level 3 (Advanced) behavioral indicators.')
                rec.indicator_level_4 = l_map.get('4') or (getattr(matrix_config, 'tech_indicator_level_4') if rec.competency_id.pillar == 'technical' else 'Level 4 (Expert) behavioral indicators.')
            else:
                rec.indicator_level_1 = False
                rec.indicator_level_2 = False
                rec.indicator_level_3 = False
                rec.indicator_level_4 = False

    @api.constrains('competency_id')
    def _check_competency_status(self):
        for line in self:
            if line.competency_id and line.competency_id.state == 'retired':
                raise ValidationError(_("The competency '%s' is retired and cannot be mapped.") % line.competency_id.name)

    override_default = fields.Boolean(
        string='Override Default', default=False,
        help='Enable to customize the required proficiency level away from the Matrix Configuration default.')
    
    is_matrix_configured = fields.Boolean(
        string='Has Matrix Default', compute='_compute_matrix_proficiency', store=True)
        
    default_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Matrix Default Level', compute='_compute_matrix_proficiency', store=True)

    required_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2', store=True)

    weight = fields.Float(
        string='Weight', default=1.0,
        help='Relative importance of this competency for the role.')

    _sql_constraints = [
        ('mapping_competency_uniq', 'unique(mapping_id, competency_id)',
         'This competency is already mapped for the role!'),
    ]

    @api.depends('competency_id', 'mapping_id.job_position_id', 'mapping_id.grade_id')
    def _compute_matrix_proficiency(self):
        """Multi-tiered Matrix Level Calculation: 1. Job Position Matrix -> 2. Job Grade Matrix -> 3. Standard Baseline."""
        for line in self:
            if not line.competency_id:
                line.is_matrix_configured = False
                line.default_proficiency = False
                continue
            
            grade = line.mapping_id.grade_id if line.mapping_id else False
            job = line.mapping_id.job_position_id if line.mapping_id else False
            config = self.env['competency.matrix.config'].get_active_config()
            matrix_lvl = False
            
            # 1. First priority: Check Job Position Matrix
            if job:
                j_line = self.env['competency.job.matrix'].search([
                    ('config_id', '=', config.id),
                    ('job_id', '=', job.id)
                ], limit=1)
                if j_line:
                    matrix_lvl = j_line.required_core_level if line.competency_id.pillar == 'core' else (
                        j_line.required_leadership_level if line.competency_id.pillar == 'leadership' and j_line.required_leadership_level != '0' else j_line.required_technical_level
                    )
            
            # 2. Second priority: If not set in Job Position Matrix, check Job Grade Matrix
            if (not matrix_lvl or matrix_lvl not in ('1', '2', '3', '4')) and grade:
                g_line = self.env['competency.grade.matrix'].search([
                    ('config_id', '=', config.id),
                    ('grade_id', '=', grade.id)
                ], limit=1)
                if g_line:
                    matrix_lvl = g_line.required_core_level if line.competency_id.pillar == 'core' else (
                        g_line.required_leadership_level if line.competency_id.pillar == 'leadership' and g_line.required_leadership_level != '0' else g_line.required_technical_level
                    )
            
            # 3. Third priority: Baseline Fallback if not configured in either matrix
            if not matrix_lvl or matrix_lvl not in ('1', '2', '3', '4'):
                matrix_lvl = '3' if line.competency_id.pillar == 'technical' else '2'

            if matrix_lvl in ('1', '2', '3', '4'):
                line.is_matrix_configured = True
                line.default_proficiency = matrix_lvl
                if not line.override_default:
                    line.required_proficiency = matrix_lvl
            else:
                line.is_matrix_configured = False
                line.default_proficiency = False
                if not line.override_default and not line.required_proficiency:
                    line.required_proficiency = '2'

    @api.onchange('competency_id', 'mapping_id.job_position_id', 'mapping_id.grade_id')
    def _onchange_competency_for_matrix_level(self):
        if self.competency_id:
            self._compute_matrix_proficiency()

    @api.onchange('override_default')
    def _onchange_override_default(self):
        if not self.override_default and self.default_proficiency:
            self.required_proficiency = self.default_proficiency

    def action_reset_to_default_proficiency(self):
        """Rule 2: Button to fall back to the default proficiency configured in the matrix."""
        for line in self:
            if line.default_proficiency:
                line.write({
                    'override_default': False,
                    'required_proficiency': line.default_proficiency,
                })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.mapping_id and line.mapping_id.state != 'draft' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_('Cannot add lines to a role-competency mapping (%s) that is not in Draft state. Please create a new version.') % line.mapping_id.mapping_name)
        return lines

    def write(self, vals):
        res = super().write(vals)
        for line in self:
            if line.mapping_id and line.mapping_id.state != 'draft' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_('Cannot modify lines on a role-competency mapping (%s) that is not in Draft state. Please create a new version.') % line.mapping_id.mapping_name)
        return res

    @api.ondelete(at_uninstall=False)
    def _prevent_unlink_on_approved(self):
        for line in self:
            if line.mapping_id and line.mapping_id.state != 'draft' and not self.env.context.get('force_write') and not self.env.su:
                raise ValidationError(_('Cannot delete lines from a role-competency mapping (%s) that is not in Draft state. Please create a new version.') % line.mapping_id.mapping_name)
