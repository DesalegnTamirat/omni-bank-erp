# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class KmsForumTopic(models.Model):
    """
    Discussion Forum & Q&A Topics (FR-KMS-032).
    Enables informal peer knowledge exchange, operational questions, and collective problem solving.
    """
    _name = 'kms.forum.topic'
    _description = 'Knowledge Forum Topic / Question'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'is_pinned desc, write_date desc'

    name = fields.Char(string='Topic / Question Title', required=True, tracking=True)
    cop_id = fields.Many2one('kms.cop', string='Community of Practice', tracking=True)
    category_id = fields.Many2one('kms.category', string='Topic Category', required=True)
    tag_ids = fields.Many2many('kms.tag', string='Tags')

    author_id = fields.Many2one(
        'hr.employee',
        string='Asked / Started By',
        required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    content = fields.Html(string='Question Details / Discussion Context', required=True)

    is_pinned = fields.Boolean(string='Pinned Topic', default=False)
    is_solved = fields.Boolean(string='Solved / Answer Accepted', default=False, tracking=True)

    post_ids = fields.One2many('kms.forum.post', 'topic_id', string='Answers & Replies')
    post_count = fields.Integer(string='Replies Count', compute='_compute_post_count')
    upvote_user_ids = fields.Many2many(
        'res.users', 'kms_forum_topic_upvote_rel', 'topic_id', 'user_id',
        string='Users Who Upvoted', copy=False,
    )
    upvote_count = fields.Integer(string='Upvotes', compute='_compute_upvote_count', store=True)
    view_count = fields.Integer(string='Views', default=0, readonly=True)

    state = fields.Selection([
        ('open', 'Open for Answers'),
        ('solved', 'Solved / Answered'),
        ('closed', 'Closed / Read-Only'),
    ], string='Status', default='open', tracking=True)

    @api.depends('post_ids')
    def _compute_post_count(self):
        for rec in self:
            rec.post_count = len(rec.post_ids)

    @api.depends('upvote_user_ids')
    def _compute_upvote_count(self):
        for rec in self:
            rec.upvote_count = len(rec.upvote_user_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('knowledge_management.group_kms_manager'):
            employee_id = self.env.user.employee_id.id
            for vals in vals_list:
                if vals.get('author_id', employee_id) != employee_id:
                    raise AccessError(_('You may only start a forum topic under your own name.'))
                if any(key in vals for key in ('is_pinned', 'is_solved', 'upvote_count', 'upvote_user_ids', 'view_count')):
                    raise AccessError(_('Forum moderation and vote fields cannot be set on creation.'))
                if vals.get('state', 'open') != 'open':
                    raise AccessError(_('A forum topic must begin open.'))
        records = super(KmsForumTopic, self).create(vals_list)
        for rec in records:
            self.env['kms.audit.log']._log_audit_event(
                action='upload', resource_type='forum', resource_name=f'Topic: {rec.name}',
                details=f"Created forum question/topic '{rec.name}'",
            )
        return records

    def write(self, vals):
        if not self.env.su:
            protected = {'is_solved', 'upvote_count', 'upvote_user_ids', 'view_count', 'state'}
            if protected.intersection(vals):
                raise AccessError(_('Use forum actions to change status or votes.'))
            if not self.env.user.has_group('knowledge_management.group_kms_manager') and any(
                topic.state != 'open' for topic in self
            ):
                raise UserError(_('Answered or closed topics cannot be edited.'))
            if not self.env.user.has_group('knowledge_management.group_kms_manager') and (
                'author_id' in vals or 'is_pinned' in vals
            ):
                raise AccessError(_('Only a KMS manager may change forum authorship or pin topics.'))
        result = super().write(vals)
        if vals:
            for rec in self:
                self.env['kms.audit.log']._log_audit_event(
                    action='modify', resource_type='forum', resource_name=f'Topic: {rec.name}',
                    details=f"Updated topic fields: {', '.join(sorted(vals))}",
                )
        return result

    def unlink(self):
        names = self.mapped('name')
        result = super().unlink()
        for name in names:
            self.env['kms.audit.log']._log_audit_event(
                action='delete', resource_type='forum', resource_name=f'Topic: {name}',
                details='Deleted forum topic',
            )
        return result

    def action_upvote(self):
        for rec in self:
            rec.check_access('read')
            self.env.cr.execute('SELECT id FROM kms_forum_topic WHERE id = %s FOR UPDATE', (rec.id,))
            rec.invalidate_recordset(['upvote_user_ids'])
            operation = 3 if self.env.user in rec.upvote_user_ids else 4
            rec.sudo().write({'upvote_user_ids': [(operation, self.env.uid)]})

    def action_close(self):
        for rec in self:
            if not self.env.su and not self.env.user.has_group('knowledge_management.group_kms_manager'):
                if rec.author_id.sudo().user_id != self.env.user:
                    raise AccessError(_('Only the topic author or KMS manager may close this topic.'))
            if rec.state != 'closed':
                rec.sudo().write({'state': 'closed'})


class KmsForumPost(models.Model):
    """Answers and Replies within a Forum Topic."""
    _name = 'kms.forum.post'
    _description = 'Forum Answer / Reply'
    _order = 'is_accepted desc, upvote_count desc, create_date asc'

    topic_id = fields.Many2one('kms.forum.topic', string='Topic', required=True, ondelete='cascade')
    author_id = fields.Many2one(
        'hr.employee',
        string='Answered By',
        required=True,
        default=lambda self: self.env.user.employee_id
    )
    content = fields.Html(string='Response Content', required=True)
    is_accepted = fields.Boolean(string='Accepted Solution', default=False)
    vote_ids = fields.One2many('kms.forum.post.vote', 'post_id', string='Votes')
    upvote_count = fields.Integer(string='Helpful Upvotes', compute='_compute_upvote_count', store=True)

    @api.depends('vote_ids', 'vote_ids.vote_type', 'vote_ids.is_active')
    def _compute_upvote_count(self):
        for rec in self:
            rec.upvote_count = len(rec.vote_ids.filtered(lambda v: v.vote_type == 'up' and v.is_active))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('knowledge_management.group_kms_manager'):
            employee_id = self.env.user.employee_id.id
            for vals in vals_list:
                if vals.get('author_id', employee_id) != employee_id:
                    raise AccessError(_('You may only post answers under your own name.'))
                if vals.get('is_accepted') or 'vote_ids' in vals:
                    raise AccessError(_('An answer cannot be accepted or voted on at creation.'))
                topic = self.env['kms.forum.topic'].browse(vals.get('topic_id'))
                topic.check_access('read')
                if topic.state != 'open':
                    raise UserError(_('Answers can only be posted to open topics.'))
        records = super(KmsForumPost, self).create(vals_list)
        for rec in records:
            self.env['kms.audit.log']._log_audit_event(
                action='upload', resource_type='forum',
                resource_name=f'Reply on: {rec.topic_id.name}',
                details=f"Posted reply to topic '{rec.topic_id.name}'",
            )
        return records

    def write(self, vals):
        if not self.env.su:
            if 'is_accepted' in vals or 'vote_ids' in vals or 'upvote_count' in vals:
                raise AccessError(_('Use forum actions to accept or vote on an answer.'))
            if not self.env.user.has_group('knowledge_management.group_kms_manager') and (
                'author_id' in vals or 'topic_id' in vals
            ):
                raise AccessError(_('Only a KMS manager may change answer authorship or topic.'))
            if any(post.topic_id.state != 'open' or post.is_accepted for post in self):
                raise UserError(_('Answers cannot be edited after a solution is accepted or a topic closes.'))
        result = super().write(vals)
        if vals:
            for rec in self:
                self.env['kms.audit.log']._log_audit_event(
                    action='modify', resource_type='forum',
                    resource_name=f'Reply on: {rec.topic_id.name}',
                    details=f"Updated answer fields: {', '.join(sorted(vals))}",
                )
        return result

    def unlink(self):
        names = [f'Reply on: {rec.topic_id.name}' for rec in self]
        result = super().unlink()
        for name in names:
            self.env['kms.audit.log']._log_audit_event(
                action='delete', resource_type='forum', resource_name=name,
                details='Deleted forum answer',
            )
        return result

    def action_accept_solution(self):
        for rec in self:
            topic = rec.topic_id
            topic.check_access('read')
            if not self.env.su and not self.env.user.has_group('knowledge_management.group_kms_manager'):
                if topic.author_id.sudo().user_id != self.env.user:
                    raise AccessError(_('Only the topic author or KMS manager may accept a solution.'))
            self.env.cr.execute('SELECT id FROM kms_forum_topic WHERE id = %s FOR UPDATE', (topic.id,))
            topic.invalidate_recordset(['state', 'is_solved'])
            rec.invalidate_recordset(['is_accepted'])
            if topic.is_solved and rec.is_accepted:
                continue
            if topic.state != 'open' or topic.is_solved:
                raise UserError(_('This topic already has a solution or is closed.'))
            # Locking the topic and accepting once prevents repeated point awards.
            topic.post_ids.sudo().write({'is_accepted': False})
            rec.sudo().write({'is_accepted': True})
            topic.sudo().write({'is_solved': True, 'state': 'solved'})
            self.env['kms.audit.log']._log_audit_event(
                action='approve', resource_type='forum',
                resource_name=f'Solution on: {rec.topic_id.name}',
                details=f"Marked answer as accepted solution on topic '{rec.topic_id.name}'",
            )
            # Award points to author of accepted answer
            author = rec.sudo().author_id
            if author and author.user_id:
                self.env['kms.contributor.point']._award_points(
                    author.user_id,
                    points=10,
                    source='accepted_answer',
                    description=f'Provided accepted solution on topic: {rec.topic_id.name}'
                )

    def action_upvote(self):
        Vote = self.env['kms.forum.post.vote']
        for rec in self:
            rec.check_access('read')
            if rec.author_id.sudo().user_id == self.env.user and not self.env.su:
                raise AccessError(_('You cannot upvote your own answer.'))
            existing = Vote.search([('post_id', '=', rec.id), ('user_id', '=', self.env.uid)], limit=1)
            if existing:
                existing.sudo().write({'is_active': not existing.is_active})
            else:
                Vote.create({
                    'post_id': rec.id,
                    'user_id': self.env.uid,
                    'vote_type': 'up',
                })
                author_user = rec.sudo().author_id.user_id
                if author_user:
                    self.env['kms.contributor.point']._award_points(
                        author_user,
                        points=1,
                        source='answer_upvote',
                        description='Received upvote on answer'
                    )


class KmsForumPostVote(models.Model):
    """Vote record preventing multiple votes on a forum post by the same user (FR-KMS-032)."""
    _name = 'kms.forum.post.vote'
    _description = 'Forum Post Vote'

    post_id = fields.Many2one('kms.forum.post', string='Post', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade', default=lambda self: self.env.user, index=True)
    vote_type = fields.Selection([
        ('up', 'Upvote'),
        ('down', 'Downvote'),
    ], string='Vote Type', default='up', required=True)
    is_active = fields.Boolean(string='Active Vote', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('knowledge_management.group_kms_manager'):
            for vals in vals_list:
                if vals.get('user_id', self.env.uid) != self.env.uid:
                    raise AccessError(_('You may only cast your own forum vote.'))
                post = self.env['kms.forum.post'].browse(vals.get('post_id'))
                post.check_access('read')
                if post.author_id.sudo().user_id == self.env.user:
                    raise AccessError(_('You cannot upvote your own answer.'))
        records = super().create(vals_list)
        for rec in records:
            self.env['kms.audit.log']._log_audit_event(
                action='modify', resource_type='forum',
                resource_name=f'Vote on: {rec.post_id.topic_id.name}',
                details='Cast forum answer vote',
            )
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals:
            for rec in self:
                self.env['kms.audit.log']._log_audit_event(
                    action='modify', resource_type='forum',
                    resource_name=f'Vote on: {rec.post_id.topic_id.name}',
                    details=f"Updated vote fields: {', '.join(sorted(vals))}",
                )
        return result

    def unlink(self):
        names = [f'Vote on: {rec.post_id.topic_id.name}' for rec in self]
        result = super().unlink()
        for name in names:
            self.env['kms.audit.log']._log_audit_event(
                action='modify', resource_type='forum', resource_name=name,
                details='Removed forum answer vote',
            )
        return result

    _unique_post_user = models.Constraint(
        'unique(post_id, user_id)',
        'A user can only vote once per forum post!',
    )
