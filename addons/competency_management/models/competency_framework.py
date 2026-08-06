# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyFramework(models.Model):
    """Version-controlled competency framework (FR-COM-001..007, FR-CFD-004/005)."""
    _name = 'competency.framework'
    _description = 'Competency Framework'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Framework Name', required=True, tracking=True)
    code = fields.Char(string='Framework Code', required=True, tracking=True)
    version = fields.Char(string='Version', default='v1.0', required=True, tracking=True)
    effective_date = fields.Date(string='Effective Date', default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('under_approval', 'Under Approval'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], string='Status', default='draft', tracking=True)
    description = fields.Text(string='Description')
    line_ids = fields.One2many('competency.framework.line', 'framework_id', string='Competency Lines')
    change_description = fields.Text(
        string='Change Description',
        help='Reason for this version change (FR-COM-007).')
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    approval_history_ids = fields.One2many(
        'competency.approval.history', 'framework_id', string='Approval History')

    _sql_constraints = [
        ('code_version_uniq', 'unique(code, version)',
         'A framework version with this code already exists!'),
    ]

    @api.constrains('line_ids', 'state')
    def _check_lines(self):
        for rec in self:
            if rec.state in ('under_approval', 'approved') and not rec.line_ids:
                raise ValidationError(
                    _('An approved framework must contain at least one competency line.'))

    def action_submit_for_approval(self):
        """Draft -> Under Approval (FR-COM-006 approval workflow)."""
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_('Add at least one competency line before submitting for approval.'))
            rec.write({'state': 'under_approval'})
            rec._log_approval_step('submitted', 'Submitted for approval')
            rec.message_post(body=_('Competency framework %s submitted for approval.') % rec.name)

    def action_approve(self):
        """Under Approval -> Approved (FR-COM-006/007)."""
        for rec in self:
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec._log_approval_step('approved', 'Approved')
            rec.message_post(body=_('Competency framework %s approved.') % rec.name)

    def action_retire(self):
        """Approved -> Retired (FR-CFD-0170 framework lifecycle)."""
        for rec in self:
            rec.write({'state': 'retired'})
            rec._log_approval_step('retired', 'Retired')
            rec.message_post(body=_('Competency framework %s retired.') % rec.name)

    def action_create_new_version(self):
        """Deep-copy an approved framework with an incremented version (FR-COM-007, FR-CFD-004)."""
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_('Only approved frameworks can be versioned.'))
        # copy() automatically duplicates the One2many framework lines, but a new
        # draft version must start with a CLEAN approval history (FR-COM-007).
        new_framework = self.copy(default={
            'name': self.name,
            'code': self.code,
            'version': self._bump_version(self.version),
            'state': 'draft',
            'approved_by_id': False,
            'approval_date': False,
            'change_description': False,
            'approval_history_ids': [(5, 0, 0)],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'competency.framework',
            'res_id': new_framework.id,
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

    def _log_approval_step(self, action, comment):
        self.env['competency.approval.history'].create({
            'framework_id': self.id,
            'action': action,
            'comment': comment,
            'user_id': self.env.user.id,
        })


class CompetencyFrameworkLine(models.Model):
    """One competency membership inside a framework."""
    _name = 'competency.framework.line'
    _description = 'Competency Framework Line'

    framework_id = fields.Many2one(
        'competency.framework', string='Framework', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('framework_competency_uniq', 'unique(framework_id, competency_id)',
         'This competency is already part of the framework!'),
    ]


class CompetencyApprovalHistory(models.Model):
    """Immutable approval trail for framework governance (FR-COM-007 audit)."""
    _name = 'competency.approval.history'
    _description = 'Competency Approval History'
    _order = 'create_date desc'

    framework_id = fields.Many2one(
        'competency.framework', string='Framework', required=True, ondelete='cascade')
    action = fields.Selection([
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], string='Action', required=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, readonly=True)
    comment = fields.Text(string='Comment')

    def unlink(self):
        # Immutability: approval history is non-editable and non-deletable (FR-COM-057)
        raise ValidationError(_('Approval history entries cannot be deleted.'))
