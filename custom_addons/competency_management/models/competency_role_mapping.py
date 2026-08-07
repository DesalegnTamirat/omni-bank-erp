# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyRoleMapping(models.Model):
    """Role-Competency mapping: master reference for assessment & gap analysis (FR-MAP-001..007).

    Uses `hr.job` (Job Position) + `employee.grade` (Employee Grade), the same
    entities used everywhere else in this ERP.
    """
    _name = 'competency.role.mapping'
    _description = 'Role-Competency Mapping'
    _inherit = ['mail.thread']
    _order = 'job_position_id, grade_id, version'
    _rec_name = 'mapping_name'

    mapping_name = fields.Char(
        string='Role Mapping', compute='_compute_mapping_name', store=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position', required=True, tracking=True)
    grade_id = fields.Many2one('employee.grade', string='Employee Grade', tracking=True)
    line_ids = fields.One2many('competency.role.mapping.line', 'mapping_id', string='Competency Lines')
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today)
    last_review_date = fields.Date(string='Last Review Date')
    next_review_date = fields.Date(string='Next Review Date')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

    @api.depends('job_position_id', 'grade_id')
    def _compute_mapping_name(self):
        for rec in self:
            parts = [rec.job_position_id.name] if rec.job_position_id else ['(No Job)']
            if rec.grade_id:
                parts.append('(%s)' % rec.grade_id.grade_name)
            rec.mapping_name = ' '.join(parts)

    _sql_constraints = [
        ('job_grade_version_uniq', 'unique(job_position_id, grade_id, version)',
         'This mapping version already exists for the job/grade!'),
    ]

    def action_submit_for_approval(self):
        """Draft -> Under Approval (FR-MAP-006 approval workflow)."""
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_('Add at least one competency line before submitting for approval.'))
            rec.state = 'under_approval'
            rec.message_post(body=_('Role-competency mapping %s submitted for approval.') % rec.mapping_name)

    def action_approve(self):
        """Under Approval -> Approved."""
        for rec in self:
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec.message_post(body=_('Role-competency mapping %s approved.') % rec.mapping_name)

    def action_archive(self):
        self.write({'state': 'archived'})

    def action_create_new_version(self):
        """Copy approved mapping into a new draft version (FR-MAP-005 version control)."""
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_('Only approved mappings can be versioned.'))
        # copy() automatically duplicates the One2many competency lines
        new_mapping = self.copy(default={
            'mapping_name': self.mapping_name,
            'job_position_id': self.job_position_id.id,
            'grade_id': self.grade_id.id,
            'version': self._bump_version(self.version),
            'state': 'draft',
            'approved_by_id': False,
            'approval_date': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'competency.role.mapping',
            'res_id': new_mapping.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @staticmethod
    def _bump_version(version):
        try:
            major, minor = version.lower().lstrip('v').split('.')
            return 'v%s.%s' % (major, int(minor) + 1)
        except Exception:
            return 'v1.1'


class CompetencyRoleMappingLine(models.Model):
    """Required competency + proficiency level for a role (FR-CFD-0174)."""
    _name = 'competency.role.mapping.line'
    _description = 'Role-Competency Mapping Line'

    mapping_id = fields.Many2one(
        'competency.role.mapping', string='Role Mapping', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
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
