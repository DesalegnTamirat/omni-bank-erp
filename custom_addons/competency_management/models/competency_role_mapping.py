# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    grade_id = fields.Many2one('employee.grade', string='Employee Grade', tracking=True)
    line_ids = fields.One2many('competency.role.mapping.line', 'mapping_id', string='Competency Lines')
    cluster_ids = fields.Many2many('competency.cluster', string='Competency Clusters')
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('archived', 'Archived / Superseded'),
    ], string='Status', default='draft', tracking=True)
    record_type = fields.Selection([
        ('production', 'Production'),
        ('demo', 'Demo / Training'),
        ('test', 'Test'),
    ], string='Record Type', default='production', required=True, tracking=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, required=True)
    change_description = fields.Text(string='Change Description')
    last_review_date = fields.Date(string='Last Review Date')
    next_review_date = fields.Date(string='Next Review Date')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

    _sql_constraints = [
        ('job_version_uniq', 'unique(job_position_id, version)',
         'A mapping for this Job Position at this version already exists. Edit the existing record or create a new version instead.'),
    ]

    @api.depends('job_position_id', 'grade_id')
    def _compute_mapping_name(self):
        for rec in self:
            parts = [rec.job_position_id.name] if rec.job_position_id else ['(No Job)']
            if rec.grade_id:
                parts.append('(%s)' % rec.grade_id.grade_name)
            rec.mapping_name = ' '.join(parts)

    @api.constrains('job_position_id', 'version')
    def _check_unique_job_position_version(self):
        for rec in self:
            if rec.job_position_id and rec.version:
                duplicates = self.search([
                    ('job_position_id', '=', rec.job_position_id.id),
                    ('version', '=', rec.version),
                    ('id', '!=', rec.id)
                ])
                if duplicates:
                    raise ValidationError(_("A mapping for this Job Position at this version already exists. Edit the existing record or create a new version instead."))

    @api.onchange('job_position_id')
    def _onchange_job_position_id(self):
        if self.job_position_id and self.job_position_id.name:
            jname = self.job_position_id.name.upper()
            if 'DEMO' in jname or 'TEST' in jname:
                self.record_type = 'demo' if 'DEMO' in jname else 'test'

    def action_submit_for_approval(self):
        """Draft -> Under Approval workflow."""
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_('Add at least one competency line before submitting for approval.'))
            if rec.record_type != 'production' or (rec.job_position_id and rec.job_position_id.name and any(kw in rec.job_position_id.name.upper() for kw in ('DEMO', 'TEST'))):
                raise ValidationError(_("Demo or Test mapping records cannot be submitted or approved for live production use."))
            rec.with_context(force_write=True).write({'state': 'under_approval'})
            rec.message_post(body=_('Role-competency mapping %s submitted for approval.') % rec.mapping_name)

    def action_approve(self):
        """Under Approval -> Approved with version supersession."""
        for rec in self:
            if rec.record_type != 'production' or (rec.job_position_id and rec.job_position_id.name and any(kw in rec.job_position_id.name.upper() for kw in ('DEMO', 'TEST'))):
                raise ValidationError(_("Demo or Test mapping records cannot be submitted or approved for live production use."))
            
            # Automatically supersede/archive prior approved versions of the same job position
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
        """Copy approved mapping into a new draft version (version control FR-COM-006)."""
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_('Only approved mappings can be versioned.'))
            
        new_version_str = self._bump_version(self.version)
        change_desc = self.env.context.get('change_description') or _("New version created from %s.") % self.version
        
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
        domain="[('approved_framework_ids', '!=', False)]")
    required_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', required=True, default='2')
    weight = fields.Float(
        string='Weight', default=1.0,
        help='Relative importance of this competency for the role.')

    _sql_constraints = [
        ('mapping_competency_uniq', 'unique(mapping_id, competency_id)',
         'This competency is already mapped for the role!'),
    ]

    @api.constrains('competency_id')
    def _check_competency_on_approved_framework(self):
        for line in self:
            if line.competency_id and not line.competency_id.approved_framework_ids:
                raise ValidationError(_("The competency '%s' does not belong to any Approved Competency Framework. Only competencies on an approved framework can be mapped to job roles.") % line.competency_id.name)

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
