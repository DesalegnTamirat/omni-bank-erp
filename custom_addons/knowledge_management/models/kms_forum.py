# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    upvote_count = fields.Integer(string='Upvotes', default=0, readonly=True)
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

    def action_upvote(self):
        for rec in self:
            rec.sudo().write({'upvote_count': rec.upvote_count + 1})

    def action_close(self):
        self.write({'state': 'closed'})


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
    upvote_count = fields.Integer(string='Helpful Upvotes', default=0, readonly=True)

    def action_accept_solution(self):
        for rec in self:
            # Unmark other answers for this topic
            rec.topic_id.post_ids.write({'is_accepted': False})
            rec.write({'is_accepted': True})
            rec.topic_id.write({'is_solved': True, 'state': 'solved'})
            # Award points to author of accepted answer
            if rec.author_id and rec.author_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.author_id.user_id,
                    points=10,
                    source='accepted_answer',
                    description=f'Provided accepted solution on topic: {rec.topic_id.name}'
                )

    def action_upvote(self):
        for rec in self:
            rec.sudo().write({'upvote_count': rec.upvote_count + 1})
            if rec.author_id and rec.author_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.author_id.user_id,
                    points=1,
                    source='answer_upvote',
                    description=f'Received upvote on answer'
                )
