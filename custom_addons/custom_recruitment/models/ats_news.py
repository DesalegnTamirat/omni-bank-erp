# -*- coding: utf-8 -*-
"""
ats_news.py
===========
Recruitment News & Announcements Management (BRD FR-ATS-051 to FR-ATS-056).
Enables HR Administrators to publish news, vacancy announcements, business updates,
events, and general recruitment posts on the ATS website portal.
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date


class AtsNews(models.Model):
    _name = 'ats.news'
    _description = 'Recruitment News & Announcement'
    _order = 'is_featured desc, publish_date desc, id desc'

    name = fields.Char(
        string='Title',
        required=True,
    )
    post_type = fields.Selection([
        ('recruitment_news', 'Recruitment News'),
        ('vacancy_announcement', 'Vacancy Announcement'),
        ('business_update', 'Business Update'),
        ('event', 'Recruitment Event'),
        ('general', 'General Announcement'),
    ], string='Post Type', default='recruitment_news', required=True)

    summary = fields.Text(
        string='Short Summary',
        help='Brief teaser paragraph displayed on news listings.',
    )
    content = fields.Html(
        string='Full Article Content',
        required=True,
    )
    image = fields.Binary(
        string='Featured Image / Banner',
        attachment=True,
    )
    is_featured = fields.Boolean(
        string='Featured Post',
        default=False,
        help='Pin this post prominently on the ATS portal header/banner.',
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('expired', 'Expired'),
    ], string='Status', default='draft', required=True)

    publish_date = fields.Date(
        string='Publish Date',
        default=fields.Date.today,
        required=True,
    )
    expiry_date = fields.Date(
        string='Expiry Date',
        help='Date after which the post automatically expires and hides from public view.',
    )
    author_id = fields.Many2one(
        'res.users',
        string='Author',
        default=lambda self: self.env.user,
    )
    active = fields.Boolean(default=True)

    def action_publish(self):
        for rec in self:
            rec.write({'state': 'published'})

    def action_set_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def action_expire(self):
        for rec in self:
            rec.write({'state': 'expired'})

    @api.model
    def _cron_check_expired_news(self):
        """Cron job to automatically expire posts past their expiry date (FR-ATS-055)."""
        today = date.today()
        expired_posts = self.search([
            ('state', '=', 'published'),
            ('expiry_date', '!=', False),
            ('expiry_date', '<', today),
        ])
        expired_posts.write({'state': 'expired'})
