# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KmsCommunityOfPractice(models.Model):
    """
    Communities of Practice (CoP) Spaces (FR-KMS-028).
    Dedicated functional spaces for practitioners in a shared domain to share experience,
    discuss problems, run brown-bag sessions, and jointly develop institutional know-how.
    """
    _name = 'kms.cop'
    _description = 'Community of Practice Space'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Community Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Html(string='Mission & Scope', required=True)
    category_id = fields.Many2one('kms.category', string='Domain Category', required=True)
    lead_id = fields.Many2one('hr.employee', string='Community Lead / Champion', required=True, tracking=True)
    moderator_ids = fields.Many2many(
        'hr.employee',
        'kms_cop_moderator_rel',
        'cop_id',
        'employee_id',
        string='Moderators / Facilitators'
    )
    member_ids = fields.Many2many(
        'hr.employee',
        'kms_cop_member_rel',
        'cop_id',
        'employee_id',
        string='Members'
    )
    is_member = fields.Boolean(string='Is Current User Member', compute='_compute_is_member')
    state = fields.Selection([
        ('active', 'Active Community'),
        ('inactive', 'Inactive / Archived'),
    ], string='Status', default='active', tracking=True)

    meeting_cadence = fields.Selection([
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ], string='Meeting Cadence', default='monthly')

    meeting_guidelines = fields.Text(string='Charter & Code of Conduct')

    # Counters
    member_count = fields.Integer(string='Members Count', compute='_compute_counts')
    session_count = fields.Integer(string='Capture Sessions Count', compute='_compute_counts')
    lesson_count = fields.Integer(string='Lessons Learned Count', compute='_compute_counts')
    discussion_count = fields.Integer(string='Discussions Count', compute='_compute_counts')

    color = fields.Integer(string='Color Index', default=4)
    image = fields.Binary(string='Community Banner / Logo', attachment=True)
    active = fields.Boolean(default=True)

    _unique_code = models.Constraint(
        'unique(code)',
        'Community of Practice code must be unique!',
    )

    @api.depends('member_ids')
    def _compute_is_member(self):
        curr_emp = self.env.user.employee_id
        for rec in self:
            rec.is_member = curr_emp and (curr_emp.id in rec.member_ids.ids)

    def _compute_counts(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)
            rec.session_count = self.env['kms.knowledge.session'].search_count([('cop_id', '=', rec.id)])
            rec.lesson_count = self.env['kms.lesson.learned'].search_count([('cop_id', '=', rec.id)])
            rec.discussion_count = self.env['kms.forum.topic'].search_count([('cop_id', '=', rec.id)])

    def _log_audit_action(self, action_type, details=None):
        for rec in self:
            try:
                self.env['kms.audit.log'].sudo().log_audit_event(
                    action=action_type,
                    resource_type='cop',
                    resource_name=f"{rec.code} - {rec.name}",
                    details=details or f"Action {action_type} performed on CoP {rec.name}"
                )
            except Exception as e:
                _logger = __import__('logging').getLogger(__name__)
                _logger.warning("Could not log CoP audit: %s", e)

    def action_join(self):
        emp = self.env.user.employee_id
        if not emp:
            raise UserError(_('No employee profile is linked to your user account.'))
        for rec in self:
            if emp.id not in rec.member_ids.ids:
                rec.sudo().write({'member_ids': [(4, emp.id)]})
                rec.sudo().message_post(body=_('%s has joined the community.') % emp.name)
                rec._log_audit_action('join', f"{emp.name} joined community of practice {rec.name}")
        return True

    def action_leave(self):
        emp = self.env.user.employee_id
        if not emp:
            raise UserError(_('No employee profile is linked to your user account.'))
        for rec in self:
            if emp.id in rec.member_ids.ids:
                rec.sudo().write({'member_ids': [(3, emp.id)]})
                rec.sudo().message_post(body=_('%s has left the community.') % emp.name)
                rec._log_audit_action('leave', f"{emp.name} left community of practice {rec.name}")
        return True

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'name': _('Knowledge Sessions - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.knowledge.session',
            'view_mode': 'list,form',
            'domain': [('cop_id', '=', self.id)],
            'context': {'default_cop_id': self.id},
        }

    def action_view_lessons(self):
        self.ensure_one()
        return {
            'name': _('Lessons Learned - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.lesson.learned',
            'view_mode': 'list,form',
            'domain': [('cop_id', '=', self.id)],
            'context': {'default_cop_id': self.id},
        }

    def action_view_discussions(self):
        self.ensure_one()
        return {
            'name': _('Discussions - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'kms.forum.topic',
            'view_mode': 'list,form',
            'domain': [('cop_id', '=', self.id)],
            'context': {'default_cop_id': self.id},
        }
